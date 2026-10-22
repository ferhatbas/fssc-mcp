"""Claude iletişim günlüğü: iş döngüsü dışındaki tüm MCP araç çağrıları (list_runs, start_pipeline_run...) kaydedilir."""

import pytest

from server import mcp_activity as MA


def _calls(hub):
    return MA.snapshot(hub)["calls"]


async def test_non_loop_tool_call_is_logged_with_result_and_args(patched_main, hub):
    await patched_main.list_runs(project_id="demo_project")
    first = _calls(hub)[0]
    assert first["tool"] == "list_runs" and first["result"] == "OK" and "project_id=demo_project" in first["title"]


async def test_failed_tool_call_is_logged_as_error_and_still_raises(patched_main, hub):
    with pytest.raises(Exception):
        await patched_main.cancel_pipeline_run(run_id="run-yok")
    first = _calls(hub)[0]
    assert first["tool"] == "cancel_pipeline_run" and first["result"].startswith("ERROR") and "run_id=run-yok" in first["title"]


async def test_pull_loop_tools_are_not_logged_twice(patched_main, hub, client):
    rid = client.post("/api/runs", json={"steps": [3], "engine": "mcp_client", "client": {"name": "claude-code"}}).json()["run"]["run_id"]
    await patched_main.get_next_step(run_id=rid)
    entries = [c for c in _calls(hub) if c["tool"] == "get_next_step"]
    assert len(entries) == 1 and entries[0]["result"] == "STEP" and entries[0]["agent_id"] == "BACKEND_DEV"


def test_rest_log_endpoint_records_proxy_calls_and_marks_client(client, hub):
    ok = client.post("/api/mcp/log", json={"tool": "list_runs", "result": "OK", "title": "project_id=x", "client": {"name": "claude-code", "version": "9.9"}})
    assert ok.status_code == 200
    act = client.get("/api/mcp/activity").json()
    assert act["calls"][0]["tool"] == "list_runs" and act["client"]["name"] == "claude-code" and act["client"]["version"] == "9.9"
    assert client.post("/api/mcp/log", json={"result": "OK"}).status_code == 400


async def test_stdio_proxy_mode_posts_the_call_to_the_web_server(patched_main, hub, monkeypatch):
    """stdio (proxy) sürecinde kayıt yerel hub'a değil, web sunucusunun /api/mcp/log ucuna gider."""
    class StubApi:
        def __init__(self):
            self.posts = []

        async def list_runs(self, project_id=None, limit=50):
            return {"runs": [], "active_run_id": None}

        async def _call(self, method, path, json=None, params=None):
            self.posts.append((method, path, json))
            return {"status": "OK"}

    stub = StubApi()
    monkeypatch.setattr(patched_main, "_PROXY_BASE_URL", "http://127.0.0.1:1")
    monkeypatch.setattr(patched_main, "runs_api", lambda: stub)
    await patched_main.list_runs(project_id="p")
    assert stub.posts and stub.posts[0][0] == "POST" and stub.posts[0][1] == "/api/mcp/log"
    assert stub.posts[0][2]["tool"] == "list_runs" and stub.posts[0][2]["result"] == "OK"
    assert _calls(hub) == []     # yerel hub'a yazılmadı


async def test_logging_failure_never_breaks_the_tool(patched_main, hub, monkeypatch):
    async def boom(*a, **kw):
        raise RuntimeError("günlük kapalı")
    monkeypatch.setattr(MA, "log_call", boom)
    res = await patched_main.list_runs(project_id="")
    assert res is not None
