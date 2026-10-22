"""Projeyi panodan kaldırıp verilerini silme (iki adımlı onayın sunucu tarafı).

Kapsamlar:
- `data`  : `.fs-workspace` + belge klasörü (FS-docs/docs) silinir; kod ve `.git` kalır.
- `folder`: proje klasörünün tamamı silinir.
İkisinde de proje kayıttan düşer. Korumalar: FS-SC deposu (ve üst klasörleri), sürücü kökü ve kullanıcı klasörü silinemez;
onay adımı olarak proje adı birebir yazılmalıdır. Son proje de silinebilir (pano "proje yok" durumuna geçer).
"""
from __future__ import annotations

import os
import shutil
import stat
from typing import Any, Dict

from .paths import docs_root
from .i18n import translate as tx, N_

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SCOPES = ("data", "folder")


class PurgeError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def _same_or_inside(path: str, other: str) -> bool:
    a, b = os.path.normcase(os.path.abspath(path)), os.path.normcase(os.path.abspath(other))
    return a == b or a.startswith(b.rstrip("\\/") + os.sep)


def check_deletable(path: str) -> None:
    """Silinmemesi gereken yolları reddeder."""
    p = os.path.abspath(path)
    if os.path.dirname(p) == p:
        raise PurgeError(tx("Sürücü kökü silinemez."))
    if _same_or_inside(REPO_ROOT, p):
        raise PurgeError(tx("FS-SC'nin kendi klasörü (ya da üst klasörü) silinemez."))
    if _same_or_inside(os.path.expanduser("~"), p):
        raise PurgeError(tx("Kullanıcı klasörü (ya da üst klasörü) silinemez."))


def _rmtree(path: str) -> None:
    def onerror(func, p, _exc):  # Windows'ta salt okunur .git nesneleri
        try:
            os.chmod(p, stat.S_IWRITE)
            func(p)
        except Exception:
            pass
    shutil.rmtree(path, onerror=onerror)


def purge_targets(project: Dict[str, Any], scope: str) -> list:
    path = os.path.abspath(project.get("path") or "")
    if scope == "folder":
        return [path]
    from .layout import docs_setting
    docs = docs_root(path, docs_setting(project.get("settings") or {}))
    return [os.path.join(path, ".fs-workspace"), docs]


async def purge_project(hub, project_id: str, scope: str, confirm_name: str) -> Dict[str, Any]:
    from .pipeline import cancel_run
    proj = hub.projects.get(project_id)
    if not proj:
        raise PurgeError(tx("Proje bulunamadı."), 404)
    if scope not in SCOPES:
        raise PurgeError(tx("Kapsam 'data' ya da 'folder' olmalı."))
    if (confirm_name or "").strip() != proj.get("name"):
        raise PurgeError(tx("Onay için proje adı birebir yazılmalı."))
    path = os.path.abspath(proj.get("path") or "")
    if not proj.get("path"):
        raise PurgeError(tx("Projenin klasör yolu yok."))
    check_deletable(path)

    for run in list(hub.runs.values()):
        if run.project_id == project_id:
            await cancel_run(hub, run, reason="project-purged")
            hub.runs.pop(run.run_id, None)

    if hub.active_project_id == project_id:
        other = next((pid for pid in hub.projects if pid != project_id), None)
        if other:
            await hub.switch_project(other)
    hub.projects.pop(project_id, None)
    if hub.active_project_id == project_id:          # son proje: pano "proje yok" durumuna geçer
        await hub.clear_active_project()
    hub.mark_dirty()

    removed = []
    for target in purge_targets(proj, scope):
        if os.path.isdir(target):
            _rmtree(target)
            removed.append(target)
    return {"status": "PURGED", "project_id": project_id, "scope": scope, "removed": removed}
