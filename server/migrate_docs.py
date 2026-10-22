"""
`docs/` → `FS-docs/` göçü (hedef belge §5.3, karar 13).

Tek seferliktir ve YALNIZCA FS-SC'nin eski sürümlerde ürettiği bilinen dosyaları taşır (`paths.KNOWN_DOC_FILES`,
`docs/tasks/` altındaki FS-SC adlı görev notları). Projenin kendi `docs/` içeriğine dokunulmaz. Hedefte aynı yolda
dosya varsa o dosya ATLANIR (asla ezilmez). Proje bir git deposunun kökündeyse ve dosya izleniyorsa `git mv`, değilse düz taşıma.
Varsayılan kuru önizlemedir; `apply=True` ile uygulanır.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from typing import Any, Dict, List

from .paths import DEFAULT_DOCS_ROOT, KNOWN_DOC_FILES, LEGACY_DOCS_ROOT, WORKSPACE_DIR
from .proc import hidden
from .i18n import translate as tx, N_

# FS-SC'nin görev notu adları: task_7.md, T-01.md, T-01_fix1.md, UAT-01.md
_TASK_NOTE_RE = re.compile(r"^(task_\d+|[A-Z]+-\d+(_fix\d+)?)\.md$")

# Eski prompt kopyalarındaki sabit yollar → yer tutucu (A13)
_PROMPT_REWRITES = [
    (re.compile(r"docs/prd/auth_service\.md"), "{docs_root}/PRD.md"),
    (re.compile(r"docs/architecture/auth_contract\.json"), "{docs_root}/openapi_spec.json"),
    (re.compile(r"docs/(manuals|api|reports|uat)/"), r"{docs_root}/\1/"),
    (re.compile(r"docs/(PRD\.md|ARCHITECTURE\.md|openapi_spec\.json|QA_REPORT\.md|handshake_sync\.json)"), r"{docs_root}/\1"),
]


def _candidates(project_dir: str) -> List[str]:
    """Taşınacak göreli yollar (docs köküne göre), yalnızca var olan dosyalar."""
    docs = os.path.join(project_dir, LEGACY_DOCS_ROOT)
    found = [rel for rel in KNOWN_DOC_FILES if os.path.isfile(os.path.join(docs, *rel.split("/")))]
    tasks_dir = os.path.join(docs, "tasks")
    if os.path.isdir(tasks_dir):
        for name in sorted(os.listdir(tasks_dir)):
            if _TASK_NOTE_RE.match(name) and os.path.isfile(os.path.join(tasks_dir, name)):
                found.append(f"tasks/{name}")
    return found


def _git(args: List[str], cwd: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=30, encoding="utf-8", errors="replace", **hidden())


def _is_repo_root(project_dir: str) -> bool:
    if not shutil.which("git"):
        return False
    try:
        res = _git(["rev-parse", "--show-toplevel"], project_dir)
    except Exception:
        return False
    if res.returncode != 0 or not res.stdout.strip():
        return False
    top = os.path.normcase(os.path.realpath(res.stdout.strip().splitlines()[-1]))
    return top == os.path.normcase(os.path.realpath(project_dir))


def _is_tracked(project_dir: str, rel: str) -> bool:
    try:
        return _git(["ls-files", "--error-unmatch", "--", rel], project_dir).returncode == 0
    except Exception:
        return False


def migrate_docs(project_dir: str, apply: bool = False) -> Dict[str, Any]:
    """
    Dönüş: {applied, source, target, moved[], conflicts[], skipped_user_files, prompts_updated[], notes[]}
    `moved` kuru önizlemede "taşınacaklar" anlamına gelir.
    """
    project_dir = os.path.abspath(project_dir)
    result: Dict[str, Any] = {
        "applied": bool(apply), "source": LEGACY_DOCS_ROOT, "target": DEFAULT_DOCS_ROOT,
        "moved": [], "conflicts": [], "prompts_updated": [], "notes": [], "used_git_mv": False,
    }
    if not os.path.isdir(project_dir):
        result["notes"].append(tx("Proje klasörü yok."))
        return result

    docs = os.path.join(project_dir, LEGACY_DOCS_ROOT)
    target_root = os.path.join(project_dir, DEFAULT_DOCS_ROOT)
    candidates = _candidates(project_dir)
    # Göç kapsamı dışında kalan (projenin kendi) dosyalar: yalnızca sayı olarak raporlanır, dokunulmaz
    total_files = sum(len(fs) for _, _, fs in os.walk(docs)) if os.path.isdir(docs) else 0
    result["untouched_files"] = max(0, total_files - len(candidates))

    use_git = _is_repo_root(project_dir)
    emptied_dirs = set()
    for rel in candidates:
        src = os.path.join(docs, *rel.split("/"))
        dst = os.path.join(target_root, *rel.split("/"))
        if os.path.exists(dst):
            result["conflicts"].append(tx("{new}/{rel} zaten var; {old}/{rel} taşınmadı", new=DEFAULT_DOCS_ROOT, old=LEGACY_DOCS_ROOT, rel=rel))
            continue
        result["moved"].append(f"{LEGACY_DOCS_ROOT}/{rel} -> {DEFAULT_DOCS_ROOT}/{rel}")
        if not apply:
            continue
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        src_rel = f"{LEGACY_DOCS_ROOT}/{rel}"
        dst_rel = f"{DEFAULT_DOCS_ROOT}/{rel}"
        if use_git and _is_tracked(project_dir, src_rel):
            res = _git(["mv", "--", src_rel, dst_rel], project_dir)
            if res.returncode == 0:
                result["used_git_mv"] = True
            else:
                shutil.move(src, dst)
                result["notes"].append(tx("git mv başarısız, düz taşındı: {rel}", rel=rel))
        else:
            shutil.move(src, dst)
        emptied_dirs.add(os.path.dirname(src))

    if apply:
        # Yalnızca bizim boşalttığımız alt klasörleri sil (docs/ kökü ve projenin kendi klasörleri kalır)
        for d in sorted(emptied_dirs, key=len, reverse=True):
            if os.path.abspath(d) != os.path.abspath(docs):
                try:
                    os.rmdir(d)
                except OSError:
                    pass
        result["prompts_updated"] = _rewrite_prompt_copies(project_dir)
    else:
        result["prompts_updated"] = _rewrite_prompt_copies(project_dir, dry_run=True)
    return result


def _rewrite_prompt_copies(project_dir: str, dry_run: bool = False) -> List[str]:
    """`.fs-workspace/agents/<AJAN>.md` içindeki eski sabit yolları `{docs_root}` ile değiştirir (yeni sürüm olarak)."""
    from .fs_workspace import save_agent_markdown

    agents_dir = os.path.join(project_dir, WORKSPACE_DIR, "agents")
    updated: List[str] = []
    if not os.path.isdir(agents_dir):
        return updated
    for name in sorted(os.listdir(agents_dir)):
        path = os.path.join(agents_dir, name)
        if not name.endswith(".md") or not os.path.isfile(path):
            continue
        try:
            text = open(path, encoding="utf-8").read()
        except OSError:
            continue
        new = text
        for rx, repl in _PROMPT_REWRITES:
            new = rx.sub(repl, new)
        if new == text:
            continue
        agent_id = name[:-3]
        if not dry_run:
            role = agent_id
            m = re.search(r"^role:\s*(.+)$", text, re.M)
            if m:
                role = m.group(1).strip()
            save_agent_markdown(project_dir, agent_id, role, new, tx("docs/ yolları {{docs_root}} yer tutucusuna çevrildi (F1 göçü)"), author="System (docs migration)")
        updated.append(agent_id)
    return updated
