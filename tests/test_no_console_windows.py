"""Windows'ta "birçok cmd ekranı açılıp kapanıyor" (saha, 2026-10-13): konsolsuz çalışan sunucu, açtığı her konsol uygulaması (git, cmd, npm, docker) için
yeni bir pencere açtırır. Kök neden: sunucu DETACHED_PROCESS ile başlatılıyordu ve `/api/server/info` her yoklamada `git rev-parse` çalıştırıyordu.
Düzeltme: `server/proc.hidden()` (CREATE_NO_WINDOW), sunucu gizli bir konsolla başlar, HEAD `git` çalıştırılmadan okunur."""

import ast
import subprocess
from pathlib import Path

import pytest

from server import main as M
from server import proc as PROC

SERVER = Path(__file__).resolve().parent.parent / "server"
SPAWNERS = {("subprocess", n) for n in ("run", "Popen", "check_output", "check_call", "call")} | {("asyncio", "create_subprocess_exec"), ("asyncio", "create_subprocess_shell")}


def test_hidden_adds_create_no_window_on_windows_and_nothing_elsewhere(monkeypatch):
    monkeypatch.setattr(PROC, "IS_WINDOWS", True)
    assert PROC.hidden() == {"creationflags": PROC.CREATE_NO_WINDOW}
    assert PROC.hidden(cwd="x", creationflags=PROC.CREATE_NEW_PROCESS_GROUP) == {"cwd": "x", "creationflags": PROC.CREATE_NEW_PROCESS_GROUP | PROC.CREATE_NO_WINDOW}
    monkeypatch.setattr(PROC, "IS_WINDOWS", False)
    assert PROC.hidden() == {} and PROC.hidden(cwd="x") == {"cwd": "x"}
    assert PROC.CREATE_NO_WINDOW == 0x08000000 and PROC.CREATE_NEW_PROCESS_GROUP == 0x200 and PROC.CREATE_BREAKAWAY_FROM_JOB == 0x01000000


def _spawn_calls(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute) or not isinstance(node.func.value, ast.Name):
            continue
        if (node.func.value.id, node.func.attr) in SPAWNERS:
            yield node


def _hides_window(call: ast.Call) -> bool:
    for kw in call.keywords:
        if kw.arg == "creationflags":
            return True
        if kw.arg is None and isinstance(kw.value, ast.Call) and getattr(kw.value.func, "id", "") == "hidden":
            return True                                                      # **hidden()
        if kw.arg is None and isinstance(kw.value, ast.Name) and kw.value.id in {"kwargs", "base", "extra"}:
            return True                                                      # önceden hidden() ile kurulmuş sözlük (verify/app_runner/main)
    return False


def test_every_process_the_server_starts_hides_its_console_window():
    offenders = []
    for path in sorted(SERVER.rglob("*.py")):
        if path.name == "proc.py":
            continue
        for call in _spawn_calls(path):
            if not _hides_window(call):
                offenders.append(f"{path.relative_to(SERVER.parent)}:{call.lineno}")
    assert not offenders, "Alt süreç **hidden() olmadan başlatılıyor (Windows'ta pencere açılıp kapanır): " + ", ".join(offenders)


def test_git_head_is_read_from_files_and_starts_no_process(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("pano yoklaması süreç başlatmamalı")
    monkeypatch.setattr(subprocess, "run", boom)
    monkeypatch.setattr(subprocess, "Popen", boom)
    head = M._git_head()
    monkeypatch.undo()
    root = SERVER.parent
    if not (root / ".git").exists():
        pytest.skip("git deposu yok")
    expected = subprocess.run(["git", "rev-parse", "--short=7", "HEAD"], cwd=str(root), capture_output=True, text=True, **PROC.hidden()).stdout.strip()
    assert head == expected and len(head) == 7


def test_git_head_follows_packed_refs_worktrees_and_detached_heads(monkeypatch, tmp_path):
    repo = tmp_path / "repo"
    (repo / "server").mkdir(parents=True)
    monkeypatch.setattr(M, "__file__", str(repo / "server" / "main.py"))
    git = repo / ".git"
    git.mkdir()
    sha = "abcdef0123456789abcdef0123456789abcdef01"
    (git / "HEAD").write_text("ref: refs/heads/dal\n", encoding="utf-8")
    assert M._git_head() == ""                                                # ref dosyası da packed-refs de yok
    (git / "packed-refs").write_text(f"# pack-refs\n{sha} refs/heads/dal\n^{'0' * 40}\n", encoding="utf-8")
    assert M._git_head() == "abcdef0"                                         # packed-refs
    (git / "refs" / "heads").mkdir(parents=True)
    (git / "refs" / "heads" / "dal").write_text("1234567890abcdef1234567890abcdef12345678\n", encoding="utf-8")
    assert M._git_head() == "1234567"                                         # gevşek ref, packed-refs'i geçer
    (git / "HEAD").write_text(sha + "\n", encoding="utf-8")
    assert M._git_head() == "abcdef0"                                         # ayrık HEAD
    # çalışma ağacı: .git bir dosya, HEAD çalışma ağacı dizininde, dallar ortak dizinde
    wt = tmp_path / "wt"
    (wt / "server").mkdir(parents=True)
    (git / "worktrees" / "wt").mkdir(parents=True)
    (git / "worktrees" / "wt" / "HEAD").write_text("ref: refs/heads/dal\n", encoding="utf-8")
    (git / "worktrees" / "wt" / "commondir").write_text("../..\n", encoding="utf-8")
    (wt / ".git").write_text(f"gitdir: {git / 'worktrees' / 'wt'}\n", encoding="utf-8")
    monkeypatch.setattr(M, "__file__", str(wt / "server" / "main.py"))
    assert M._git_head() == "1234567"
