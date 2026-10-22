"""
Klasör gözatıcı (dashboard "Gözat" düğmesi için).

Tarayıcı güvenlik nedeniyle yerel klasörün tam yolunu veremez; bu yüzden proje bağlarken klasör seçimi sunucu tarafında
yapılır: yalnızca DİZİN adları listelenir (dosya içeriği okunmaz), gizli/sistem klasörleri varsayılan olarak atlanır.
Sunucu 127.0.0.1'e bağlıdır; bu uç yalnızca aynı makinedeki dashboard tarafından kullanılır.
"""

from __future__ import annotations

import os
import stat
import sys
from .i18n import translate as tx, N_
from typing import Any, Dict, List, Optional

_SKIP_NAMES = {"$recycle.bin", "system volume information", "windows", "program files", "program files (x86)",
               "programdata", "node_modules", "__pycache__", "recovery", "perflogs"}


class BrowseError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def _is_hidden(path: str, name: str) -> bool:
    if name.startswith("."):
        return True
    if sys.platform.startswith("win"):
        try:
            attrs = os.stat(path).st_file_attributes  # type: ignore[attr-defined]
            return bool(attrs & (stat.FILE_ATTRIBUTE_HIDDEN | stat.FILE_ATTRIBUTE_SYSTEM))  # type: ignore[attr-defined]
        except (OSError, AttributeError):
            return False
    return False


def roots() -> List[Dict[str, str]]:
    """Sürücüler (Windows) ya da kök dizin (POSIX)."""
    out: List[Dict[str, str]] = []
    if sys.platform.startswith("win"):
        drives: List[str] = []
        try:
            drives = list(os.listdrives())  # Python 3.12+
        except AttributeError:
            import string
            drives = [f"{c}:\\" for c in string.ascii_uppercase if os.path.exists(f"{c}:\\")]
        for d in drives:
            out.append({"name": d.rstrip("\\"), "path": d})
    else:
        out.append({"name": "/", "path": "/"})
    return out


def suggestions() -> List[Dict[str, str]]:
    """Sık kullanılan başlangıç noktaları: kullanıcı klasörü, depo kökünün üstü, Masaüstü/Belgeler."""
    home = os.path.expanduser("~")
    repo_parent = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    cands = [(tx("Kullanıcı klasörü"), home), (tx("Projeler (depo üstü)"), repo_parent),
             (tx("Masaüstü"), os.path.join(home, "Desktop")), (tx("Belgeler"), os.path.join(home, "Documents"))]
    return [{"name": n, "path": p} for n, p in cands if os.path.isdir(p)]


def browse(path: Optional[str], show_hidden: bool = False, limit: int = 400) -> Dict[str, Any]:
    """Verilen klasörün alt klasörlerini döner; yol boşsa sürücüler/öneriler."""
    if not path or not str(path).strip():
        return {"path": "", "parent": None, "dirs": [], "roots": roots(), "suggestions": suggestions(), "is_root_list": True}
    raw = str(path).strip().strip('"')
    if sys.platform.startswith("win") and len(raw) == 2 and raw[1] == ":":
        raw += "\\"
    norm = os.path.abspath(os.path.expanduser(raw))
    if not os.path.exists(norm):
        raise BrowseError(tx("Klasör bulunamadı: {norm}", norm=norm), 404)
    if not os.path.isdir(norm):
        norm = os.path.dirname(norm)
    parent = os.path.dirname(norm.rstrip("\\/")) or None
    if parent == norm:
        parent = None
    dirs: List[Dict[str, Any]] = []
    try:
        with os.scandir(norm) as it:
            entries = sorted(it, key=lambda e: e.name.lower())
    except PermissionError:
        raise BrowseError(tx("Erişim reddedildi: {norm}", norm=norm), 403)
    except OSError as e:
        raise BrowseError(tx("Klasör okunamadı: {e}", e=e), 400)
    for e in entries:
        try:
            if not e.is_dir(follow_symlinks=False):
                continue
        except OSError:
            continue
        full = os.path.join(norm, e.name)
        if not show_hidden and (e.name.lower() in _SKIP_NAMES or _is_hidden(full, e.name)):
            continue
        dirs.append({
            "name": e.name,
            "path": full,
            "has_workspace": os.path.isdir(os.path.join(full, ".fs-workspace")),
            "is_git": os.path.isdir(os.path.join(full, ".git")),
        })
        if len(dirs) >= limit:
            break
    return {
        "path": norm,
        "parent": parent,
        "dirs": dirs,
        "roots": roots(),
        "suggestions": suggestions(),
        "is_root_list": False,
        "has_workspace": os.path.isdir(os.path.join(norm, ".fs-workspace")),
        "is_git": os.path.isdir(os.path.join(norm, ".git")),
        "truncated": len(dirs) >= limit,
    }
