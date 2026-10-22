"""Sunucu kimliği ve bağımsız sunucu: hub'ın bir Claude oturumunun MCP süreci içinde barındırılması koşuyu düşürüyordu (saha: submit_step_result
"Error executing tool"). stdio süreci web sunucusu yoksa bağımsız bir `--mode web` başlatır; eski/gömülü kip panoda uyarı olur."""

import os
import subprocess
import sys
import time

import pytest

import server.main as M


def test_server_info_endpoint_reports_process_mode_and_freshness(client):
    info = client.get("/api/server/info").json()
    assert info["pid"] == os.getpid() and info["port"] == M.SERVER_PORT and info["mode"] in ("web", "all", "stdio-proxy", "stdio-embedded")
    assert isinstance(info["code_stale"], bool) and isinstance(info["changed_files"], list) and info["uptime_s"] >= 0 and info["started_at"]
    assert info["hosted_in_claude_session"] is (info["mode"] == "stdio-embedded")


def test_code_is_stale_only_when_a_source_file_is_newer_than_the_process_start(monkeypatch):
    monkeypatch.setattr(M, "_STARTED_AT", 0.0)                          # süreç "çok eski": her kaynak dosya daha yeni
    stale = M._server_info()
    assert stale["code_stale"] is True and stale["changed_files"] and all(f.startswith(("server/", "agents/")) for f in stale["changed_files"])
    monkeypatch.setattr(M, "_STARTED_AT", time.time() + 3600)           # süreç "gelecekte" başlamış: hiçbir dosya daha yeni değil
    fresh = M._server_info()
    assert fresh["code_stale"] is False and fresh["changed_files"] == []


@pytest.mark.parametrize("mode,ok", [("web", True), ("stdio-proxy", True), ("stdio-embedded", False)])
def test_setup_card_warns_when_the_hub_lives_inside_a_claude_session(client, monkeypatch, mode, ok):
    monkeypatch.setattr(M, "_SERVER_MODE", mode)
    steps = {s["key"]: s for s in client.get("/api/runner/setup").json()["steps"]}
    assert steps["server_host"]["ok"] is ok
    assert ("Claude oturumunun içinde" in steps["server_host"]["text"]) is (not ok)
    assert "fssc.ps1 start" in steps["server_host"]["fix"]
    assert "code_fresh" in steps


class _FakeProc:
    pass


def _spawn(monkeypatch, tmp_path, popen, ready=True):
    monkeypatch.setattr(subprocess, "Popen", popen)
    monkeypatch.setattr(M, "_state_ok", lambda timeout=1.5: ready)
    return M._spawn_detached_web_server(wait_s=1.0, log_path=tmp_path / "logs" / "server.log")


def test_spawn_starts_a_detached_web_server_with_the_log_redirected(monkeypatch, tmp_path):
    calls = []

    def popen(cmd, **kw):
        calls.append((cmd, kw))
        return _FakeProc()

    assert _spawn(monkeypatch, tmp_path, popen) is True
    cmd, kw = calls[0]
    assert cmd == [sys.executable, "-m", "server.main", "--mode", "web"]
    assert kw["stdin"] == subprocess.DEVNULL and kw["stderr"] == subprocess.STDOUT and kw["stdout"] is not None    # MCP stdout'u kirlenmez
    assert kw["env"]["PYTHONIOENCODING"] == "utf-8" and kw["env"]["OBSERVER_PORT"] == str(M.SERVER_PORT)
    assert (tmp_path / "logs" / "server.log").exists()
    if sys.platform.startswith("win"):
        # NEW_GROUP | NO_WINDOW | BREAKAWAY; DETACHED_PROCESS (0x8) YOK: konsolsuz sunucu her git/cmd alt sürecinde yeni pencere açtırır
        assert kw["creationflags"] & 0x00000200 and kw["creationflags"] & 0x08000000 and kw["creationflags"] & 0x01000000
        assert not kw["creationflags"] & 0x00000008
    else:
        assert kw["start_new_session"] is True


def test_spawn_retries_without_job_breakaway_and_falls_back_when_it_cannot_start(monkeypatch, tmp_path):
    flags = []

    def picky(cmd, **kw):
        flags.append(kw.get("creationflags"))
        if kw.get("creationflags", 0) & 0x01000000:
            raise PermissionError("iş nesnesi kopmaya izin vermiyor")
        return _FakeProc()

    if sys.platform.startswith("win"):
        assert _spawn(monkeypatch, tmp_path, picky) is True and len(flags) == 2 and flags[0] & 0x01000000 and not flags[1] & 0x01000000

    def broken(cmd, **kw):
        raise OSError("başlatılamadı")

    assert _spawn(monkeypatch, tmp_path, broken) is False                 # çağıran gömülü kipe düşer
    assert _spawn(monkeypatch, tmp_path, lambda cmd, **kw: _FakeProc(), ready=False) is False       # hazır olmadı: gömülü kip
