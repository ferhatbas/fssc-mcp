"""
Proje içi yol yardımcıları: ekibin ürettiği insan okur belgelerin klasörü (`docs_root`) tek yerden okunur.

Yeni projede `FS-docs`, göç etmemiş (eski) FS-SC projesinde `docs`. Kod tabanında sabit `docs/` yolu yazılmaz;
sınıf düzeyindeki sabit yollar `DOCS_TOKEN` (`<docs>`) ile yazılır ve `resolve_tokens` ile çözülür.
"""

from __future__ import annotations

import os
import re
from typing import Any, Optional

DEFAULT_DOCS_ROOT = "FS-docs"
LEGACY_DOCS_ROOT = "docs"
WORKSPACE_DIR = ".fs-workspace"
DOCS_TOKEN = "<docs>"

# FS-SC'nin eski sürümlerde `docs/` altına yazdığı bilinen dosyalar (göç yalnızca bunları taşır)
KNOWN_DOC_FILES = (
    "PRD.md", "ARCHITECTURE.md", "openapi_spec.json", "QA_REPORT.md", "handshake_sync.json",
    "uat/acceptance_criteria.md", "manuals/user_guide.md", "reports/status_report.md",
)
KNOWN_DOC_DIRS = ("tasks",)

_BAD_PARTS = {"..", ".git", WORKSPACE_DIR.lower()}


def sanitize_docs_root(value: Any) -> Optional[str]:
    """Ayar değerini doğrular: göreli, tek klasör, `..`/`.git`/`.fs-workspace` yok. Geçersizse None."""
    if not isinstance(value, str):
        return None
    v = value.strip().replace("\\", "/")
    if v.startswith("/"):
        return None
    v = v.strip("/")
    if not v or v == "." or re.match(r"^[A-Za-z]:", v) or v.startswith("~"):
        return None
    parts = v.split("/")
    for p in parts:
        if not p or p.rstrip(". ").lower() in _BAD_PARTS or p != p.rstrip(". "):
            return None
        if any(c in p for c in '<>:"|?*'):
            return None
    return "/".join(parts)


def _legacy_layout(project_dir: str) -> bool:
    """`FS-docs/` yokken `docs/` altında FS-SC'nin bilinen dosyalarından en az ikisi varsa eski düzendir."""
    if not project_dir or os.path.isdir(os.path.join(project_dir, DEFAULT_DOCS_ROOT)):
        return False
    if not os.path.isdir(os.path.join(project_dir, WORKSPACE_DIR)):
        return False
    docs = os.path.join(project_dir, LEGACY_DOCS_ROOT)
    if not os.path.isdir(docs):
        return False
    hits = sum(1 for rel in KNOWN_DOC_FILES if os.path.isfile(os.path.join(docs, *rel.split("/"))))
    return hits >= 2


def docs_root(project_dir: str, setting: Any = None) -> str:
    """Projenin belge klasörü (göreli). Önce ayar, sonra eski düzen sezgisi, sonra `FS-docs`."""
    configured = sanitize_docs_root(setting)
    if configured:
        return configured
    return LEGACY_DOCS_ROOT if _legacy_layout(project_dir) else DEFAULT_DOCS_ROOT


def docs_path(project_dir: str, rel: str = "", setting: Any = None) -> str:
    """Belge klasörü altındaki göreli yol (`FS-docs/PRD.md`)."""
    root = docs_root(project_dir, setting)
    rel = rel.replace("\\", "/").lstrip("/")
    return f"{root}/{rel}" if rel else root


def resolve_tokens(value: Any, root: str, extra: Optional[dict] = None) -> Any:
    """Metin, liste ve sözlüklerdeki `<docs>` belirtecini (ve `{docs_root}` yer tutucusunu) çözer; `extra`: ek belirteçler (`<reports>`)."""
    if isinstance(value, str):
        out = value.replace(DOCS_TOKEN, root).replace("{docs_root}", root)
        for token, replacement in (extra or {}).items():
            out = out.replace(token, replacement)
        return out
    if isinstance(value, list):
        return [resolve_tokens(v, root, extra) for v in value]
    if isinstance(value, tuple):
        return tuple(resolve_tokens(v, root, extra) for v in value)
    if isinstance(value, dict):
        return {k: resolve_tokens(v, root, extra) for k, v in value.items()}
    return value


def hub_docs_path(hub: Any, rel: str = "", project_dir: Optional[str] = None) -> str:
    """Etkin projenin (ya da verilen klasörün) belge klasörü altındaki göreli yol."""
    try:
        from .layout import docs_setting
        setting = docs_setting(hub.get_settings())       # apps düzeninde düzenin belge klasörü, düz düzende `docs_root` ayarı
    except Exception:
        setting = None
    if not project_dir:
        try:
            project_dir = (hub.projects.get(hub.active_project_id) or {}).get("path") or ""
        except Exception:
            project_dir = ""
    return docs_path(project_dir or "", rel, setting)


_PROTECTED = {".git", WORKSPACE_DIR}


def is_protected_path(rel: str) -> bool:
    """Ajan teslimiyle yazılamayacak yol mu? `.git` ve `.fs-workspace` (her yazım biçimiyle)."""
    norm = str(rel).replace("\\", "/")
    for part in norm.split("/"):
        # Windows: büyük/küçük harf, sondaki nokta/boşluk ve alternatif veri akışı (`.git::$INDEX_ALLOCATION`, `.git:x`)
        name = part.split(":", 1)[0].rstrip(". ").lower()
        if name in _PROTECTED:
            return True
        # 8.3 kısa adlar (GIT~1, FS-WOR~1) korunan adların kısaltmasıdır
        if "~" in name and (name.startswith("git~") or name.startswith("fs-wor~")):
            return True
    return False
