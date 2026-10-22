"""Claude (MCP istemcisi) iletişim görünürlüğü: çağrı günlüğü, 'sıra kimde' ve ajan durumunun hata/çalışıyor eşlemesi."""

import json

from server import mcp_activity as MA


def _env():
    return json.dumps({
        "from_agent": "BACKEND_DEV", "to_agent": "FRONTEND_DEV", "intent": "BACKEND_API_EXPOSED", "status": "SUCCESS",
        "payload": {"summary": "teslim", "friendly_dialogue": "hazır", "thinking": "t", "what_doing": "w", "what_next": "n",
                    "files": [{"path": "src/calc.py", "content": "def add(a, b):\n    return a + b\n"}]},
        "metadata": {"tokens_used": 50},
    })


def _start(client, steps):
    return client.post("/api/runs", json={"steps": steps, "engine": "mcp_client", "client": {"name": "claude-code", "version": "9.9"}}).json()["run"]["run_id"]


def _activity(client):
    return client.get("/api/mcp/activity").json()


def test_no_run_means_idle_and_no_client(client, hub):
    act = _activity(client)
    assert act["turn"]["who"] == "idle" and act["client"] is None and act["client_state"] == "none" and act["calls"] == []


def test_claude_turn_and_call_log_follow_the_pull_loop(client, hub):
    rid = _start(client, [3])
    # koşu kuyrukta: Claude'dan çağrı bekleniyor
    assert _activity(client)["turn"]["who"] == "claude_wait"

    step = client.post(f"/api/runs/{rid}/next-step", json={"client": {"name": "claude-code", "version": "9.9"}}).json()
    assert step["status"] == "STEP"
    act = _activity(client)
    assert act["turn"]["who"] == "claude" and act["turn"]["agent_id"] == "BACKEND_DEV" and act["turn"]["order"] == 3
    assert act["client"]["name"] == "claude-code" and act["client_state"] == "connected"
    assert act["calls"][0]["tool"] == "get_next_step" and act["calls"][0]["result"] == "STEP" and act["calls"][0]["agent_id"] == "BACKEND_DEV"

    client.post(f"/api/runs/{rid}/thinking", json={"agent_id": "BACKEND_DEV", "text": "Planlıyorum", "client": {"name": "claude-code"}})
    assert _activity(client)["calls"][0]["tool"] == "report_thinking"

    sub = client.post(f"/api/runs/{rid}/steps/3/result", json={"result_json": _env(), "client": {"name": "claude-code"}}).json()
    assert sub["status"] == "WAITING_APPROVAL"
    act = _activity(client)
    assert act["calls"][0]["tool"] == "submit_step_result" and act["calls"][0]["result"] == "WAITING_APPROVAL"
    # onay bekleyen adımda sıra yöneticidedir
    assert act["turn"]["who"] == "manager" and "onay" in act["turn"]["label"].lower()


def test_repeated_wait_polls_collapse_into_one_row(client, hub):
    rid = _start(client, [3])
    client.post(f"/api/runs/{rid}/next-step", json={"client": {"name": "claude-code"}})
    client.post(f"/api/runs/{rid}/steps/3/result", json={"result_json": _env(), "client": {"name": "claude-code"}})
    for _ in range(3):
        client.post(f"/api/runs/{rid}/approval", json={"timeout_s": 1, "client": {"name": "claude-code"}})
    waits = [c for c in _activity(client)["calls"] if c["tool"] == "wait_for_approval"]
    assert len(waits) == 1 and waits[0]["result"] == "STILL_WAITING" and waits[0]["count"] == 3


def test_abandoned_run_is_reported_as_waiting_for_claude(client, hub):
    rid = _start(client, [3])
    client.post(f"/api/runs/{rid}/next-step", json={"client": {"name": "claude-code"}})
    hub.runs[rid].finish("ABANDONED", reason="server-restart")
    turn = _activity(client)["turn"]
    assert turn["who"] == "claude_wait" and "bekleniyor" in turn["label"]


def test_call_log_is_bounded(client, hub):
    import asyncio
    async def fill():
        for i in range(MA.LOG_MAX + 25):
            await MA.log_call(hub, "report_thinking", None, None, result="OK", title=str(i))
    asyncio.run(fill())
    assert len(MA._log(hub)) == MA.LOG_MAX
    assert len(MA.snapshot(hub)["calls"]) == MA.SNAPSHOT_CALLS


async def test_event_status_maps_to_agent_status(hub):
    """IN_PROGRESS (ör. 'soru açıldı') hata değildir; yalnızca FAILED/ERROR ajanı ERROR yapar."""
    await hub.record_event("t", "DEVOPS", "MANAGER", "QUESTION_RAISED", "IN_PROGRESS", {})
    assert hub.agents["DEVOPS"]["status"] == "WORKING"
    await hub.record_event("t", "DEVOPS", "MANAGER", "SOMETHING", "FAILED", {})
    assert hub.agents["DEVOPS"]["status"] == "ERROR"
    await hub.record_event("t", "DEVOPS", "MANAGER", "SOMETHING", "SUCCESS", {})
    assert hub.agents["DEVOPS"]["status"] == "WORKING"


def test_abandoned_run_is_found_even_without_active_run_id(client, hub):
    """Sunucu yeniden başlayınca active_run_id boşalır; koşu yine de 'Claude bekleniyor' olarak görünmelidir."""
    rid = _start(client, [3])
    client.post(f"/api/runs/{rid}/next-step", json={"client": {"name": "claude-code"}})
    hub.runs[rid].finish("ABANDONED", reason="server-restart")
    hub.active_run_id = None
    turn = _activity(client)["turn"]
    assert turn["run_id"] == rid and turn["who"] == "claude_wait"


def test_outcome_of_json_text_is_ok_not_a_brace():
    from server.main import _outcome_of
    assert _outcome_of('{\n  "questions": []\n}') == "OK"
    assert _outcome_of("[1, 2]") == "OK"
    assert _outcome_of("Tamam, kaydedildi") == "Tamam, kaydedildi"
    assert _outcome_of({"status": "STEP"}) == "STEP"


def _blocked_turn(client, hub, monkeypatch, sprints, open_questions):
    from server import meetings as M
    from server import sprint as SP
    rid = _start(client, [3])
    client.post(f"/api/runs/{rid}/next-step", json={"client": {"name": "claude-code"}})
    monkeypatch.setattr(SP, "ensure_state", lambda h: {"sprints": sprints})
    monkeypatch.setattr(M, "open_blocking", lambda h: open_questions)
    return _activity(client)["turn"]


_BLOCKED_S1 = {"sprint_number": 1, "status": "BLOCKED", "blocked": {"detail": "Sıkı DoD kapanış koşulu eksik"}}


def test_blocked_sprint_without_open_question_is_not_called_a_question(client, hub, monkeypatch):
    turn = _blocked_turn(client, hub, monkeypatch, [_BLOCKED_S1], [])
    assert turn["who"] == "manager" and "soru" not in turn["label"].lower() and "Sprint 1 engelde" in turn["label"]
    assert "açık soru yok" in turn["detail"]


def test_blocked_sprint_with_open_question_asks_for_an_answer(client, hub, monkeypatch):
    turn = _blocked_turn(client, hub, monkeypatch, [_BLOCKED_S1], [{"id": "Q-1"}])
    assert turn["label"] == "Sıra sende: engelleyici soru bekliyor" and "Sorular panelinden" in turn["detail"]


def test_older_blocked_sprint_does_not_take_the_turn_from_claude(client, hub, monkeypatch):
    sprints = [_BLOCKED_S1, {"sprint_number": 2, "status": "IN_PROGRESS", "blocked": None}]
    turn = _blocked_turn(client, hub, monkeypatch, sprints, [])
    assert turn["who"] == "claude"
