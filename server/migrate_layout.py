"""
Düz düzendeki projeyi `apps/ devops/ docs/` düzenine taşır (talimat: `medi-gate/meta-repo-setup.md`; yönetici kararı 2026-10-12: tek repo, `demo_project` de taşınır).

Ajanlar dosya YAZAR ama taşıyamaz ya da silemez; bu yüzden göç bir SUNUCU eylemidir. Önce kuru plan (`apply=False`), sonra uygulama:
- git deposunda izlenen girdiler `git mv` ile (geçmiş korunur), izlenmeyenler (node_modules, dist ...) yeniden adlandırılarak taşınır;
- kayıtlı durumdaki yollar yeni yollara çevrilir: Jira dosya ipuçları ve etkilenen dosyalar, koşu artefaktları, sprint/ADR/toplantı/soru bağlantıları,
  teknoloji gereksinimleri dosyaları, doğrulama komutları (`cd apps/backend && …`) ve belgelerdeki `kod` içi yollar;
- `project_layout` ayarı yazılır (`docs_root` otomatiğe döner) ve tek commit atılır.
Süren bir adım (ajan teslim üretirken) varken uygulanmaz; onay bekleyen ya da duraklatılmış koşu sorun değildir.
"""

from __future__ import annotations

import asyncio
import os
import re
import shutil
import subprocess
from typing import Any, Dict, List, Optional, Tuple

from . import layout as LAY
from . import meetings as M
from .proc import hidden
from . import scm as SCM
from . import sprint as SP
from .i18n import translate as tx, N_

MANIFESTS = ("package.json", "requirements.txt", "pyproject.toml", "composer.json", "go.mod", "pom.xml", "Cargo.toml", "pubspec.yaml")


class MigrationError(Exception):
    def __init__(self, message: str, status_code: int = 409, **extra: Any):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.extra = extra

    def to_dict(self) -> Dict[str, Any]:
        return {"error": self.message, **self.extra}


# ---------------------------------------------------------------------------
# Dosya taşıma
# ---------------------------------------------------------------------------
def _git(project_dir: str, args: List[str], timeout: float = 180.0) -> Tuple[int, str]:
    try:
        r = subprocess.run(["git", *args], cwd=project_dir, capture_output=True, text=True, timeout=timeout, **hidden())
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    except Exception as e:  # noqa: BLE001
        return 127, str(e)


def _is_repo(project_dir: str) -> bool:
    return os.path.isdir(os.path.join(project_dir, ".git"))


def _tracked(project_dir: str, rel: str) -> bool:
    code, out = _git(project_dir, ["ls-files", "--", rel])
    return code == 0 and bool(out.strip())


def move_entries(project_dir: str, moves: List[Dict[str, str]]) -> List[Dict[str, str]]:
    """Planın taşımalarını uygular; her biri için kullanılan yöntemi (`git mv` | `move`) döner."""
    use_git = _is_repo(project_dir)
    done: List[Dict[str, str]] = []
    for m in moves:
        src, dst = os.path.join(project_dir, m["from"]), os.path.join(project_dir, m["to"])
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        method = "move"
        if use_git and _tracked(project_dir, m["from"]):
            code, _out = _git(project_dir, ["mv", "--", m["from"], m["to"]])
            method = "git mv" if code == 0 else "move"
            if code != 0:
                shutil.move(src, dst)
        else:
            shutil.move(src, dst)
        done.append({**m, "method": method})
    return done


# ---------------------------------------------------------------------------
# Yol yeniden yazımı
# ---------------------------------------------------------------------------
_BACKTICK = re.compile(r"`([^`\n]{1,160})`")


def rewrite_docs_text(project_dir: str, docs_dir: str, pairs: List[Tuple[str, str]]) -> int:
    """Belge klasöründeki Markdown dosyalarında `kod` içine alınmış, taşınan bir önekle başlayan yolları çevirir (örn. `src/x/` → `apps/backend/src/x/`)."""
    changed = 0
    root = os.path.join(project_dir, docs_dir)
    for cur, _dirs, files in os.walk(root):
        for name in files:
            if not name.lower().endswith(".md"):
                continue
            path = os.path.join(cur, name)
            try:
                with open(path, "r", encoding="utf-8", newline="") as fh:
                    text = fh.read()
            except OSError:
                continue
            new = _BACKTICK.sub(lambda m: "`" + LAY.rewrite_path(m.group(1), pairs) + "`", text)
            if new != text:
                with open(path, "w", encoding="utf-8", newline="") as fh:
                    fh.write(new)
                changed += 1
    return changed


def rewrite_verification(verification: Dict[str, Any], pairs: List[Tuple[str, str]], root_folder: Optional[str]) -> Dict[str, Any]:
    """Kayıtlı doğrulama komutları: `cd <eski>` → `cd <yeni>`; kökteki manifest klasöre taşındıysa `cd <klasör> && ` öneki (adresler değişmez)."""
    out: Dict[str, Any] = {}
    for key, val in (verification or {}).items():
        if key in ("health_url", "app_url") or not isinstance(val, str) or not val.strip():
            out[key] = val
            continue
        parts = [p.strip() for p in val.split("&&")]
        had_cd = False
        for i, part in enumerate(parts):
            m = re.match(r"^cd\s+(\"?)([^\s\"]+)\1(.*)$", part)
            if m:
                had_cd = True
                parts[i] = f"cd {LAY.rewrite_path(m.group(2), pairs)}{m.group(3)}"
        cmd = " && ".join(parts)
        out[key] = cmd if (had_cd or not root_folder) else f"cd {root_folder} && {cmd}"
    return out


def rewrite_state(hub, plan: Dict[str, Any]) -> Dict[str, int]:
    """Bellekteki (ve dolayısıyla kalıcı) durumdaki yolları çevirir. Yalnızca bilinen yol alanlarına dokunur (alan adları değil, değerler değişir)."""
    pairs = LAY.path_rewrites(plan)
    counts = {"jira": 0, "runs": 0, "sprint": 0, "questions": 0, "settings": 0}

    def rw(v: Any) -> Any:
        return LAY.rewrite_path(v, pairs) if isinstance(v, str) and v else v

    def rw_list(lst: Any) -> Any:
        return [rw(x) for x in lst] if isinstance(lst, list) else lst

    layout = plan.get("layout") or LAY.sanitize_layout({})
    for issue in hub.jira_issues.values():
        before = repr((issue.get("files_hint"), issue.get("files_affected"), issue.get("attachments")))
        for key in ("files_hint", "files_affected"):
            if isinstance(issue.get(key), list):
                issue[key] = rw_list(issue[key])
        if isinstance(issue.get("files_hint"), list):
            # taşınan girdilerle eşleşmeyen düz ipuçları (kökte hiç olmamış klasörler) yazan ajanın uygulamasına uydurulur
            issue["files_hint"] = LAY.relocate_hints(layout, issue["files_hint"], str(issue.get("assignee") or ""), layout["docs_dir"])
        for entry in issue.get("audit_trail") or []:
            if isinstance(entry, dict) and isinstance(entry.get("files_affected"), list):
                entry["files_affected"] = rw_list(entry["files_affected"])
        for att in issue.get("attachments") or []:
            if isinstance(att, dict) and isinstance(att.get("path"), str):
                att["path"] = rw(att["path"])
        if repr((issue.get("files_hint"), issue.get("files_affected"), issue.get("attachments"))) != before:
            counts["jira"] += 1
    for run in hub.runs.values():
        if run.project_id != hub.active_project_id:
            continue
        for step in run.steps:
            new = [rw(a) if isinstance(a, str) else a for a in (step.artifacts or [])]
            if new != list(step.artifacts or []):
                step.artifacts = new
                counts["runs"] += 1
    state = SP.ensure_state(hub)
    for sp in state.get("sprints", []):
        if sp.get("commitment_ref"):
            sp["commitment_ref"] = rw(sp["commitment_ref"])
        if isinstance(sp.get("meetings"), dict):
            sp["meetings"] = {k: rw(v) for k, v in sp["meetings"].items()}
        counts["sprint"] += 1
    for m in state.get("meetings", []):
        if isinstance(m, dict) and m.get("file"):
            m["file"] = rw(m["file"])
    for d in state.get("decisions", []):
        if isinstance(d, dict) and d.get("adr"):
            d["adr"] = rw(d["adr"])
    for q in M.store(hub).get("questions", []):
        if isinstance(q, dict) and q.get("adr_ref"):
            q["adr_ref"] = rw(q["adr_ref"])
            counts["questions"] += 1
    req = (hub.get_settings() or {}).get("tech_requirements")
    if isinstance(req, dict) and isinstance(req.get("files"), list):
        req["files"] = rw_list(req["files"])
        counts["settings"] += 1
    hub.mark_dirty()
    return counts


# ---------------------------------------------------------------------------
# Giriş noktası
# ---------------------------------------------------------------------------
def _in_flight(hub, project_id: str) -> Optional[str]:
    for run in hub.runs.values():
        step = run.current_step
        if run.project_id == project_id and run.status == "ACTIVE" and step is not None and step.status == "ACTIVE":
            return tx("{run_id} adım #{order}", run_id=run.run_id, order=step.order)
    return None


async def migrate_layout(hub, project_id: str, apply: bool = False, layout_override: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """`apply=False`: yalnızca plan (hiçbir şey değişmez). `apply=True`: dosyaları taşır, durumu çevirir, ayarı yazar, commit atar."""
    proj = hub.projects.get(project_id)
    project_dir = os.path.abspath((proj or {}).get("path") or "")
    if not proj or not os.path.isdir(project_dir):
        raise MigrationError(tx("Proje ya da proje klasörü bulunamadı."), 404)
    settings = hub.get_settings() if project_id == hub.active_project_id else (proj.get("settings") or {})
    current = LAY.layout_of(settings)
    layout = LAY.sanitize_layout(layout_override or {}, fallback=current if LAY.is_apps(current) else None)
    layout["mode"] = "apps"
    plan = await asyncio.to_thread(LAY.plan_migration, project_dir, layout)
    result: Dict[str, Any] = {"project_id": project_id, "status": "PLAN", "layout": layout, "plan": plan, "already_apps": LAY.is_apps(current)}
    if not apply:
        return result
    if project_id != hub.active_project_id:
        raise MigrationError(tx("Göç yalnızca etkin projede uygulanır; önce projeyi seçin."), 409)
    busy = _in_flight(hub, project_id)
    if busy:
        raise MigrationError(tx("Süren bir adım var ({busy}); teslim edilene ya da onaya gelene kadar bekleyin.", busy=busy), 409, in_flight=busy)
    if plan["conflicts"]:
        raise MigrationError(tx("Çakışma var; önce elle çözün: ") + "; ".join(plan["conflicts"][:5]), 409, conflicts=plan["conflicts"])

    pairs = LAY.path_rewrites(plan)
    moved = await asyncio.to_thread(move_entries, project_dir, plan["moves"])
    root_manifest_moved = any(m["from"] in MANIFESTS for m in plan["moves"])
    root_folder = LAY.app_folder(layout, plan["root_role"]) if root_manifest_moved else None
    counts = rewrite_state(hub, plan)                      # bellekteki durumu değiştirir: olay döngüsünde koşar
    docs_changed = await asyncio.to_thread(rewrite_docs_text, project_dir, layout["docs_dir"], pairs)
    settings_now = hub.get_settings()
    verification = rewrite_verification(settings_now.get("verification") or {}, pairs, root_folder)
    await hub.update_settings({"project_layout": layout, "docs_root": None, "verification": verification})
    commit: Dict[str, Any] = {"status": "SKIPPED", "reason": tx("git deposu yok")}
    if _is_repo(project_dir):
        commit = await SCM.commit_all(project_dir, tx("chore: proje klasör düzeni apps/devops/docs olarak taşındı (FS-SC göçü)"))
    await hub.broadcast({"type": "JIRA_UPDATED", "jira_issues": list(hub.jira_issues.values())})
    await hub.broadcast({"type": "LAYOUT_MIGRATED", "project_id": project_id, "layout": layout, "moved": len(moved)})
    result.update({"status": "APPLIED", "moved": moved, "rewritten": {**counts, "docs": docs_changed}, "verification": verification, "commit": commit})
    return result
