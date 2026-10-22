"""
SCM ajanı — sunucu tarafı Git işlemleri.

Doğrulaması geçen her geliştirme adımından sonra proje klasöründe commit atar. Koruyucular:
- `git` yoksa sessizce atlar (sebep döner).
- Proje klasörü bir deponun ALT klasörüyse (toplevel ≠ proje kökü) commit atılmaz; aksi halde kullanıcının
  başka bir deposuna istemeden commit girer.
- Depo yoksa `git init` ile proje kökünde yeni depo açılır ve temel bir .gitignore yazılır.
Dal değiştirilmez; commit, kullanıcının o anki dalına atılır (çalışma ağacını şaşırtmamak için).
"""

from __future__ import annotations

import asyncio
import os
import re
import shutil
import subprocess
from typing import Any, Dict, List, Optional, Tuple

from .i18n import translate as tx
from .proc import hidden

GIT_AUTHOR = os.environ.get("FSSC_GIT_AUTHOR", "FS-SC SCM Agent")
GIT_EMAIL = os.environ.get("FSSC_GIT_EMAIL", "scm@fssc.local")

# Her projede (yeni ya da mevcut depo) bulunması gereken FS-SC satırları (hedef belge §5.4, karar 18).
# Git'e girer: FS-docs/**, ürün kodu, .fs-workspace/{jira_issues,sprint_state,questions}.json, agents/**.
FSSC_IGNORE_LINES = [
    ".fs-workspace/settings.json",
    ".fs-workspace/events.jsonl",
    ".fs-workspace/runs.json",
    ".fs-workspace/meetings/*.jsonl",
    ".fs-workspace/e2e/screenshots/",
    ".fs-workspace/specs/uploads/",
    ".fs-workspace/app_run.log",
    ".fs-workspace/verify/",
    ".fs-workspace/venv/",
    ".fs-workspace/claude_log.jsonl",
    ".fs-workspace/claude-sessions/",
    ".fs-workspace/claude-mcp.json",
    ".mcp.json",
    ".agents/mcp_config.json",            # Antigravity MCP ayarı (makineye özel yol)
    ".fs-workspace/**/*.shrunk.bak",
    ".fs-workspace/snapshots/",
    "/submit_*.js", "/step_*.json", "/build_step_*.js", "/complete_build_step_*.js", "/envelope*.json",   # ajan geçici dosyaları köke düşse bile git'e girmez
    ".fs-workspace/tmp/",                   # ajanın geçici betik/zarf dosyaları (kökte değil burada)
    ".fs-workspace/*.tmp",                  # atomik yazımın geçici dosyaları (runs.json.tmp...): git add sırasında kaybolup commit'i düşürüyordu
    ".fs-workspace/**/*.tmp",
    ".env",
    ".env.*",
    "!.env.example",
]
FSSC_IGNORE_HEADER = "# FS-SC: makine durumu ve yerel dosyalar (otomatik eklendi)"
# Daha önce izlenmişse indeksten çıkarılacak yollar (dosyalar diskten silinmez)
FSSC_UNTRACK = [
    ".fs-workspace/settings.json", ".fs-workspace/events.jsonl", ".fs-workspace/runs.json",
    ".fs-workspace/meetings/*.jsonl", ".fs-workspace/e2e/screenshots", ".fs-workspace/specs/uploads",
    ".fs-workspace/app_run.log", ".fs-workspace/verify", ".fs-workspace/venv",
    ".fs-workspace/claude_log.jsonl", ".fs-workspace/claude-sessions", ".fs-workspace/claude-mcp.json",
    ".mcp.json", ".agents/mcp_config.json",
]

DEFAULT_GITIGNORE = """# FS-SC SCM ajanı tarafından oluşturuldu
node_modules/
dist/
build/
__pycache__/
*.py[cod]
.venv/
venv/
.pytest_cache/
coverage/
"""


def merge_gitignore(existing: str) -> str:
    """Mevcut .gitignore'u bozmadan eksik FS-SC satırlarını sona ekler (yoksa değişmeden döner)."""
    have = {ln.strip() for ln in existing.splitlines()}
    missing = [ln for ln in FSSC_IGNORE_LINES if ln not in have]
    if not missing:
        return existing
    out = existing
    if out and not out.endswith("\n"):
        out += "\n"
    if FSSC_IGNORE_HEADER not in have:
        out += ("\n" if out else "") + FSSC_IGNORE_HEADER + "\n"
    return out + "\n".join(missing) + "\n"


def ensure_gitignore(project_dir: str) -> bool:
    """.gitignore'u oluşturur ya da eksik FS-SC satırlarıyla tamamlar. Değiştiyse True."""
    gi = os.path.join(project_dir, ".gitignore")
    try:
        existing = open(gi, encoding="utf-8").read() if os.path.isfile(gi) else DEFAULT_GITIGNORE
        merged = merge_gitignore(existing)
        if os.path.isfile(gi) and merged == existing:
            return False
        with open(gi, "w", encoding="utf-8", newline="\n") as f:
            f.write(merged)
        return True
    except OSError:
        return False


async def untrack_ignored(project_dir: str) -> None:
    """İzlenen ama artık ignore edilen FS-SC dosyalarını indeksten çıkarır (diskte kalır)."""
    await _git(["rm", "-r", "--cached", "-q", "--ignore-unmatch", "--", *FSSC_UNTRACK], project_dir)


def git_available() -> bool:
    return shutil.which("git") is not None


async def _git(args: List[str], cwd: str, timeout_s: float = 60.0) -> Dict[str, Any]:
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "LC_ALL": "C.UTF-8", "PYTHONIOENCODING": "utf-8"}
    try:
        proc = await asyncio.create_subprocess_exec(
            "git", *args, cwd=cwd, env=env,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT, stdin=asyncio.subprocess.DEVNULL, **hidden(),
        )
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout_s)
        return {"code": proc.returncode, "out": (out or b"").decode("utf-8", errors="replace").strip()}
    except asyncio.TimeoutError:
        return {"code": -1, "out": tx("git zaman aşımı")}
    except Exception as e:  # noqa: BLE001
        return {"code": -1, "out": str(e)}


def _same_path(a: str, b: str) -> bool:
    try:
        return os.path.normcase(os.path.realpath(a)) == os.path.normcase(os.path.realpath(b))
    except Exception:
        return False


async def repo_state(project_dir: str) -> Dict[str, Any]:
    """{'repo': bool, 'toplevel': str|None, 'nested': bool, 'branch': str|None}"""
    res = await _git(["rev-parse", "--show-toplevel"], project_dir)
    if res["code"] != 0:
        return {"repo": False, "toplevel": None, "nested": False, "branch": None}
    top = res["out"].splitlines()[-1].strip() if res["out"] else ""
    nested = not _same_path(top, project_dir)
    br = await _git(["rev-parse", "--abbrev-ref", "HEAD"], project_dir)
    return {"repo": True, "toplevel": top, "nested": nested, "branch": br["out"] if br["code"] == 0 else None}


async def ensure_repo(project_dir: str) -> Dict[str, Any]:
    """Depo yoksa açar. Dönüş: {'ok': bool, 'created': bool, 'reason': str}"""
    if not git_available():
        return {"ok": False, "created": False, "reason": tx("git bulunamadı")}
    state = await repo_state(project_dir)
    if state["repo"] and not state["nested"]:
        return {"ok": True, "created": False, "reason": ""}
    if state["repo"] and state["nested"]:
        return {"ok": False, "created": False, "reason": tx("proje klasörü başka bir deponun altında ({top}); commit atlanıyor", top=state['toplevel'])}
    init = await _git(["init", "-q"], project_dir)
    if init["code"] != 0:
        return {"ok": False, "created": False, "reason": tx("git init başarısız: {out}", out=init['out'][:200])}
    return {"ok": True, "created": True, "reason": ""}


async def commit_all(project_dir: str, message: str) -> Dict[str, Any]:
    """
    Tüm değişiklikleri commit'ler. Dönüş: {'status': 'COMMITTED'|'NOTHING'|'SKIPPED'|'FAILED', 'hash': str|None,
    'reason': str, 'branch': str|None, 'created_repo': bool}
    """
    ensured = await ensure_repo(project_dir)
    if not ensured["ok"]:
        return {"status": "SKIPPED", "hash": None, "reason": ensured["reason"], "branch": None, "created_repo": False}
    ensure_gitignore(project_dir)
    from .project_bootstrap import sweep_stray_root_files
    await asyncio.to_thread(sweep_stray_root_files, project_dir)   # ajanın köke bıraktığı geçici betik/zarf dosyaları .fs-workspace/tmp/ altına
    await untrack_ignored(project_dir)
    add = await _git(["add", "-A", "--", "."], project_dir)
    for _ in range(2):                                   # geçici dosya (atomik yazım) git add sırasında kaybolursa "unable to index": kısa bekleyip bir kez daha dene
        if add["code"] == 0 or not any(k in add["out"] for k in ("unable to index", "No such file", "unable to stat")):
            break
        await asyncio.sleep(0.4)
        add = await _git(["add", "-A", "--", "."], project_dir)
    if add["code"] != 0:
        return {"status": "FAILED", "hash": None, "reason": f"git add: {add['out'][:200]}", "branch": None, "created_repo": ensured["created"]}
    # Sır taraması (§12 madde 4): commit öncesi aşamalı dosyalar taranır; bulgu varsa commit atılmaz, dosyalar aşamadan çıkarılır
    from . import guard as G
    names = await _git(["diff", "--cached", "--name-only"], project_dir)
    findings = G.scan_files(project_dir, [n for n in names["out"].splitlines() if n.strip()]) if names["code"] == 0 else []
    if findings:
        await _git(["reset", "-q"], project_dir)
        return {"status": "SECRET", "hash": None, "reason": "; ".join(f"{f['file']}:{f['line']} {f['kind']} ({f['preview']})" for f in findings[:5]),
                "findings": findings[:20], "branch": None, "created_repo": ensured["created"]}
    staged = await _git(["diff", "--cached", "--quiet"], project_dir)
    if staged["code"] == 0:
        state = await repo_state(project_dir)
        return {"status": "NOTHING", "hash": None, "reason": tx("değişiklik yok"), "branch": state.get("branch"), "created_repo": ensured["created"]}
    commit = await _git([
        "-c", f"user.name={GIT_AUTHOR}", "-c", f"user.email={GIT_EMAIL}",
        "commit", "-q", "-m", message[:400],   # projenin kendi commit kancaları (varsa) atlanmaz; kanca kalırsa commit FAILED olur
    ], project_dir)
    if commit["code"] != 0:
        return {"status": "FAILED", "hash": None, "reason": f"git commit: {commit['out'][:300]}", "branch": None, "created_repo": ensured["created"]}
    h = await _git(["rev-parse", "--short", "HEAD"], project_dir)
    state = await repo_state(project_dir)
    return {"status": "COMMITTED", "hash": h["out"] if h["code"] == 0 else None, "reason": "", "branch": state.get("branch"),
            "created_repo": ensured["created"]}


async def tag(project_dir: str, name: str, message: str = "") -> Dict[str, Any]:
    """Sprint etiketi (geri dönüş noktası). Depo yoksa ya da iç içeyse atlanır; var olan etiketin üzerine yazılmaz."""
    state = await repo_state(project_dir) if git_available() else {"repo": False, "nested": False}
    if not state.get("repo") or state.get("nested"):
        return {"status": "SKIPPED", "reason": tx("depo yok ya da iç içe")}
    head = await _git(["rev-parse", "--verify", "-q", "HEAD"], project_dir)
    if head["code"] != 0:
        return {"status": "SKIPPED", "reason": tx("commit yok")}
    res = await _git(["-c", f"user.name={GIT_AUTHOR}", "-c", f"user.email={GIT_EMAIL}", "tag", "-a", name, "-m", message or name], project_dir)
    if res["code"] != 0:
        return {"status": "FAILED", "reason": res["out"][:200]}
    return {"status": "TAGGED", "tag": name}


async def diff_text(project_dir: str, limit: int = 14000) -> Dict[str, str]:
    """Son sprint etiketinden (yoksa ilk commit'ten) bu yana oluşan fark: istatistik + kırpılmış yama. ARCHITECT gözden geçirmesinin girdisi (§6.3)."""
    if not git_available():
        return {"base": "", "stat": "", "patch": ""}
    tags = await _git(["tag", "--list", "fssc/sprint-*", "--sort=-creatordate"], project_dir)
    base = (tags["out"].splitlines() or [""])[0] if tags["code"] == 0 else ""
    if not base:
        root = await _git(["rev-list", "--max-parents=0", "HEAD"], project_dir)
        base = (root["out"].splitlines() or [""])[0] if root["code"] == 0 else ""
    if not base:
        return {"base": "", "stat": "", "patch": ""}
    stat = await _git(["diff", "--stat", f"{base}..HEAD"], project_dir)
    patch = await _git(["diff", "--no-color", "-U2", f"{base}..HEAD"], project_dir, timeout_s=60.0)
    text = patch["out"] if patch["code"] == 0 else ""
    return {"base": base, "stat": stat["out"] if stat["code"] == 0 else "", "patch": text[:limit] + (tx("\n... (kırpıldı)") if len(text) > limit else "")}


async def recent_log(project_dir: str, limit: int = 15) -> List[str]:
    if not git_available():
        return []
    res = await _git(["log", f"-{limit}", "--pretty=format:%h %s"], project_dir)
    return res["out"].splitlines() if res["code"] == 0 and res["out"] else []


_ISSUE_COMMITS_CACHE: Dict[str, Tuple[float, Dict[str, List[Dict[str, str]]]]] = {}
_COMMIT_SUBJECT_RX = re.compile(r"^\w+\(([A-Za-z]+-\d+)\)")


def commits_by_issue(project_dir: str) -> Dict[str, List[Dict[str, str]]]:
    """Git geçmişinden madde → commit listesi (`feat(JIRA-72): ...` başlığından), eskiden yeniye. Koşu geçmişi (runs.json) kaybolsa da commit kanıtı
    kalsın diye. `git` yalnızca yeni commit olduğunda (reflog değişince) çalışır; sonuç önbelleğe alınır, her çağrıda süreç açılmaz."""
    if not project_dir:
        return {}
    try:
        stamp = os.path.getmtime(os.path.join(project_dir, ".git", "logs", "HEAD"))
    except OSError:
        return {}
    key = os.path.abspath(project_dir)
    cached = _ISSUE_COMMITS_CACHE.get(key)
    if cached and cached[0] == stamp:
        return cached[1]
    out: Dict[str, List[Dict[str, str]]] = {}
    try:
        r = subprocess.run(["git", "log", "--format=%h%x09%cI%x09%an%x09%s", "-n", "3000"], cwd=project_dir, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=20, stdin=subprocess.DEVNULL, **hidden())
        for line in reversed((r.stdout or "").splitlines()):
            parts = line.split("	", 3)
            m = _COMMIT_SUBJECT_RX.match(parts[3]) if len(parts) == 4 else None
            if m:
                out.setdefault(m.group(1).upper(), []).append({"commit": parts[0], "at": parts[1], "author": parts[2], "subject": parts[3]})
    except Exception:  # noqa: BLE001
        return {}
    _ISSUE_COMMITS_CACHE[key] = (stamp, out)
    return out


def commit_message(kind: str, issue_id: str, title: str, fix_round: int = 0) -> str:
    prefix = {"task": "feat", "fix": "fix", "phase": "chore"}.get(kind, "chore")
    if kind == "phase":
        prefix = "feat"
    suffix = tx(" (düzeltme {n})", n=fix_round) if fix_round else ""
    return f"{prefix}({issue_id}): {title.strip()[:120]}{suffix}"
