"""
G2 — Claude köprüsü: tam etkileşim günlüğü (K2), başsız Claude Code oturumu (K1), transkript aynası ve kancalar (K3).
"""
import json
import os
import sys
import time

import pytest

from server import claude_bridge as CB
from server import claude_log as CL
from server import claude_transcripts as CT

CLIENT = {"name": "pytest-g2", "version": "1"}


def _pm_env(trace: str = "t") -> str:
    return json.dumps({
        "trace_id": trace, "from_agent": "PM", "to_agent": "ARCHITECT", "intent": "TASK_DISPATCH", "status": "SUCCESS",
        "payload": {"summary": "PRD hazır", "friendly_dialogue": "ok", "thinking": "ok", "what_doing": "ok", "what_next": "ok",
                    "files": [{"path": "FS-docs/PRD.md", "content": "# PRD\n"}]},
    })


# ---------------------------------------------------------------------------
# K2: tam etkileşim günlüğü
# ---------------------------------------------------------------------------
async def test_claude_log_records_both_directions_with_full_bodies(client, hub, tmp_project):
    hub.step_by_step_mode = False
    await hub.update_settings({"approval_mode": "auto"})
    run = client.post("/api/runs", json={"steps": [1], "engine": "mcp_client", "client": CLIENT}).json()["run"]
    rid = run["run_id"]
    client.post(f"/api/runs/{rid}/next-step", json={"client": CLIENT})
    client.post(f"/api/runs/{rid}/thinking", json={"agent_id": "PM", "text": "PRD'yi derliyorum, önce notları okudum.", "client": CLIENT})
    client.post(f"/api/runs/{rid}/notes", json={"text": "Mobil öncelikli olsun"})
    raw = _pm_env(rid)
    client.post(f"/api/runs/{rid}/steps/1/result", json={"result_json": raw, "client": CLIENT})

    body = client.get("/api/claude/log").json()
    tools = {(e["tool"], e["direction"]) for e in body["entries"]}
    assert ("get_next_step", "to_claude") in tools and ("submit_step_result", "to_server") in tools
    assert ("report_thinking", "to_server") in tools and ("manager_note", "manager") in tools
    assert rid in body["runs"]

    # Claude'a giden TAM yanıt (rol promptu + bağlam) tam gövdede okunur; listede kırpılmıştır
    nxt = next(e for e in body["entries"] if e["tool"] == "get_next_step")
    full = client.get(f"/api/claude/log/{nxt['id']}").json()
    assert "Product Manager" in full["result"]["system_prompt"] and full["result"]["order"] == 1
    assert nxt.get("result_truncated") is True
    # Claude'dan gelen HAM teslim aynen saklanır
    sub = next(e for e in body["entries"] if e["tool"] == "submit_step_result")
    full_sub = client.get(f"/api/claude/log/{sub['id']}").json()
    assert full_sub["args"]["result_json"] == raw and full_sub["result"]["status"] in ("NEXT", "RUN_COMPLETE") and full_sub["duration_ms"] is not None
    think = next(e for e in body["entries"] if e["tool"] == "report_thinking")
    assert "notları okudum" in think["text"]

    # Süzgeçler ve arama
    assert {e["tool"] for e in client.get("/api/claude/log?tool=submit_step_result").json()["entries"]} == {"submit_step_result"}
    assert all(e["direction"] == "to_claude" for e in client.get("/api/claude/log?direction=to_claude").json()["entries"])
    assert any(e["tool"] == "get_next_step" for e in client.get("/api/claude/log?q=Product%20Manager").json()["entries"])
    # Kalıcı dosya ve dışa aktarma
    path = CL.log_path(tmp_project)
    assert os.path.isfile(path) and len(open(path, encoding="utf-8").read().strip().splitlines()) >= 4
    md = client.get("/api/claude/log/export").text
    assert "FS-SC → Claude" in md and "Claude → FS-SC" in md and "Yönetici → FS-SC" in md


async def test_claude_log_collapses_repeated_polls_and_masks_secrets(hub):
    for _ in range(3):
        await CL.record(hub, direction="to_server", tool="wait_for_approval", run_id="run-1", status="STILL_WAITING", collapse=True)
    rows = CL.query(hub, tool="wait_for_approval")["entries"]
    assert len(rows) == 1 and rows[0]["count"] == 3
    e = await CL.record(hub, direction="to_server", tool="x", args={"api_key": "sk-abcdefghijklmnopqrstuvwxyz0123456789"})
    assert "sk-abcdefghijklmnopqrstuvwxyz0123456789" not in json.dumps(e, ensure_ascii=False)


# ---------------------------------------------------------------------------
# K3: transkript aynası
# ---------------------------------------------------------------------------
def _transcript_lines(sid: str = "sess-1"):
    return [
        {"type": "user", "message": {"role": "user", "content": "pipeline'ı çalıştır"}, "uuid": "u1", "timestamp": "2026-10-12T10:00:00Z", "sessionId": sid, "cwd": "D:\\x"},
        {"type": "custom-title", "customTitle": "Pipeline koşusu", "sessionId": sid},
        {"type": "assistant", "message": {"model": "claude-x", "content": [
            {"type": "thinking", "thinking": "", "signature": "abc"},
            {"type": "text", "text": "Koşuyu başlatıyorum."},
            {"type": "tool_use", "id": "tu1", "name": "mcp__fssc-visual-observer__get_next_step", "input": {"run_id": "run-77"}},
        ], "usage": {"input_tokens": 5, "output_tokens": 9}}, "uuid": "a1", "timestamp": "2026-10-12T10:00:01Z", "sessionId": sid, "thinkingDurationMs": 120},
        {"type": "user", "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "tu1", "content": [{"type": "text", "text": "{\"status\": \"STEP\"}"}]}]},
         "uuid": "u2", "timestamp": "2026-10-12T10:00:02Z", "sessionId": sid},
    ]


def test_transcript_parsing_offsets_and_listing(tmp_path):
    if os.name == "nt":
        assert CT.encode_project_dir(r"D:\Personal\projects\idvlp\mcp_server") == "D--Personal-projects-idvlp-mcp-server"
    root = tmp_path / "claude-projects"
    proj = tmp_path / "proj"
    proj.mkdir()
    tdir = root / CT.encode_project_dir(str(proj))
    tdir.mkdir(parents=True)
    f = tdir / "sess-1.jsonl"
    f.write_text("\n".join(json.dumps(x) for x in _transcript_lines()) + "\n", encoding="utf-8")

    events, off = CT.read_events(str(f), 0)
    kinds = [e["kind"] for e in events]
    assert kinds == ["user_text", "thinking", "assistant_text", "tool_use", "tool_result"]
    tu = events[3]
    assert tu["fssc"] is True and tu["run_id"] == "run-77" and tu["tool"].endswith("get_next_step")
    assert events[1]["empty"] is True and events[1]["duration_ms"] == 120
    assert off == os.path.getsize(f)
    # Yarım satır bir sonraki okumaya kalır
    with open(f, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "devam"}]}, "sessionId": "sess-1"})[:20])
    more, off2 = CT.read_events(str(f), off)
    assert more == [] and off2 == off
    with open(f, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "devam"}]}, "sessionId": "sess-1"})[20:] + "\n")
    more, off3 = CT.read_events(str(f), off)
    assert [e["kind"] for e in more] == ["assistant_text"] and off3 > off

    se = CT.session_events(str(f))
    assert se["thinking"]["total"] == 1 and se["thinking"]["empty"] == 1 and "saklanmamış" in se["thinking"]["note"]
    sessions = CT.list_sessions(str(proj), str(root))
    assert len(sessions) == 1 and sessions[0]["session_id"] == "sess-1" and sessions[0]["title"] == "Pipeline koşusu" and sessions[0]["first_prompt"].startswith("pipeline")


async def test_transcript_watcher_broadcasts_and_logs_new_events(hub, tmp_path, monkeypatch):
    f = tmp_path / "s.jsonl"
    f.write_text(json.dumps(_transcript_lines()[0]) + "\n", encoding="utf-8")
    sent = []

    async def fake_broadcast(data):
        sent.append(data)
    monkeypatch.setattr(hub, "broadcast", fake_broadcast)
    w = CT.TranscriptWatcher(hub, interval_s=0.05)
    w.watch(str(f))                      # sondan izler: eski satır yayınlanmaz
    assert await w.poll_once() == 0
    with open(f, "a", encoding="utf-8") as fh:
        fh.write("\n".join(json.dumps(x) for x in _transcript_lines()[2:]) + "\n")
    n = await w.poll_once()
    assert n == 4
    kinds = [m["event"]["kind"] for m in sent if m.get("type") == "CLAUDE_TRANSCRIPT_EVENT"]
    assert kinds == ["thinking", "assistant_text", "tool_use", "tool_result"]
    rows = CL.query(hub, direction="client")["entries"]
    assert any(r["tool"].endswith("get_next_step") and r["run_id"] == "run-77" for r in rows)
    assert w.status()["events_seen"] == 4
    await w.stop()


async def test_hook_endpoint_records_and_watches_transcript(client, hub, tmp_path):
    f = tmp_path / "hooked.jsonl"
    f.write_text("", encoding="utf-8")
    res = client.post("/api/claude/hook", json={"hook_event_name": "PostToolUse", "session_id": "h1", "transcript_path": str(f),
                                                "tool_name": "mcp__fssc-visual-observer__get_next_step", "tool_input": {"run_id": "run-h"},
                                                "tool_response": {"status": "STEP"}}).json()
    assert res["status"] == "OK" and str(f) in res["watching"]
    rows = CL.query(hub, direction="client")["entries"]
    assert rows and rows[0]["run_id"] == "run-h" and rows[0]["status"] == "PostToolUse" and rows[0]["session_id"] == "h1"
    st = client.get("/api/claude/status").json()
    assert str(f) in st["transcripts"]["watching"] and st["transcript_dirs"][0]["scope"] == "fssc"
    await CT.watcher(hub).stop()


# ---------------------------------------------------------------------------
# K1: başsız köprü
# ---------------------------------------------------------------------------
def test_bridge_build_command_and_cli_status(monkeypatch):
    monkeypatch.setattr(CB, "desktop_bundled_cli", lambda: None)          # makinedeki Claude Desktop CLI'si sonucu değiştirmesin
    cmd = CB.build_command("claude", "merhaba", "C:/x/mcp.json", max_turns=7, model="m1", session_id="sid-1", extra_args="--foo bar")
    assert cmd[:3] == ["claude", "-p", "merhaba"] and "stream-json" in cmd and "--max-turns" in cmd and cmd[cmd.index("--max-turns") + 1] == "7"
    assert cmd[cmd.index("--allowedTools") + 1] == CB.ALLOWED_TOOLS and "--strict-mcp-config" in cmd and "--session-id" in cmd and "--foo" in cmd
    cmd2 = CB.build_command("claude", "x", "m.json", resume="old-sid")
    assert "--resume" in cmd2 and "--session-id" not in cmd2
    st = CB.cli_status("definitely-missing-cli-xyz", use_cache=False)
    assert st["ok"] is False and "bulunamadı" in st["error"] and "npm install" in st["install_hint"]


FAKE_CLI = r'''
import json, sys
if "--version" in sys.argv:
    print("fake-claude 0.0.1"); sys.exit(0)
sid = "fake-sess-1"
def out(o): print(json.dumps(o), flush=True)
out({"type": "system", "subtype": "init", "session_id": sid, "tools": ["mcp__fssc-visual-observer__claim_work"], "model": "fake"})
out({"type": "assistant", "session_id": sid, "message": {"content": [
    {"type": "thinking", "thinking": "önce iş var mı bakayım"},
    {"type": "text", "text": "İşi üstleniyorum."},
    {"type": "tool_use", "id": "tu1", "name": "mcp__fssc-visual-observer__claim_work", "input": {}}]}})
out({"type": "user", "session_id": sid, "message": {"content": [{"type": "tool_result", "tool_use_id": "tu1", "content": [{"type": "text", "text": "{\"status\": \"IDLE\"}"}]}]}})
out({"type": "result", "subtype": "success", "is_error": False, "num_turns": 1, "duration_ms": 12, "session_id": sid, "result": "IDLE: bekleyen iş yok"})
'''


async def test_bridge_runs_fake_cli_records_session_and_log(client, hub, tmp_project, tmp_path):
    script = tmp_path / "fake_claude.py"
    script.write_text(FAKE_CLI, encoding="utf-8")
    cli = f'"{sys.executable}" "{script}"'
    assert client.post("/api/settings/claude", json={"cli": cli, "max_turns": 9999}).json()["claude"]["max_turns"] == 500
    res = client.post("/api/claude/start", json={"prompt": "FS-SC işini yürüt"})
    assert res.status_code == 200 and res.json()["status"] == "STARTED", res.text
    st = None
    for _ in range(200):
        st = client.get("/api/claude/status").json()["bridge"]
        if not st["running"]:
            break
        time.sleep(0.05)
    assert st and st["running"] is False and st["exit_code"] == 0, st
    assert st["session_id"] == "fake-sess-1" and st["events"] >= 5 and st["result"]["num_turns"] == 1 and st["cli"]["ok"] is True
    assert st["cmd"][2] == "<prompt>"       # istem günlükte, komut satırında gizli
    sessions = client.get("/api/claude/sessions").json()["sessions"]
    assert sessions and sessions[0]["session_id"] == "fake-sess-1"
    events = client.get("/api/claude/sessions/fake-sess-1/events").json()["events"]
    kinds = [e["kind"] for e in events]
    assert kinds == ["system", "thinking", "assistant_text", "tool_use", "tool_result", "result"]
    assert events[1]["text"] == "önce iş var mı bakayım" and events[1]["empty"] is False
    assert os.path.isfile(os.path.join(tmp_project, ".fs-workspace", "claude-sessions", "fake-sess-1.jsonl"))
    assert os.path.isfile(os.path.join(tmp_project, ".fs-workspace", "claude-mcp.json"))
    rows = client.get("/api/claude/log").json()["entries"]
    tools = [(r["tool"], r["direction"]) for r in rows]
    assert ("claude_start", "server") in tools and ("claude_finished", "server") in tools
    assert ("mcp__fssc-visual-observer__claim_work", "client") in tools and ("thinking", "client") in tools
    # Yeniden bağlanma aynı oturum kimliğini --resume ile sürdürür (sahte CLI argümanı yok sayar)
    res2 = client.post("/api/claude/start", json={"resume": "fake-sess-1"}).json()
    assert res2["status"] == "STARTED" and res2["state"]["resume_of"] == "fake-sess-1" and "--resume" in CB.build_command(cli, "x", "m", resume="fake-sess-1")
    for _ in range(200):
        if not client.get("/api/claude/status").json()["bridge"]["running"]:
            break
        time.sleep(0.05)


async def test_bridge_refuses_without_cli(client, hub):
    await hub.update_settings({"claude": {"cli": "definitely-missing-cli-xyz"}})
    res = client.post("/api/claude/start", json={})
    assert res.status_code == 503 and res.json()["status"] == "CLI_UNAVAILABLE" and "install_hint" in res.json()
    assert client.post("/api/claude/stop").json()["status"] == "NOT_RUNNING"
