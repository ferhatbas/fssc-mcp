"""Yönetici müdahalesi: dashboard'dan not/acil not ve onay modalından 'Revize iste' (aynı adım geri bildirimle yeniden üretilir)."""

import json
import time

from server import sprint as SP

NOTE = "Docker kullanılsın: Dockerfile ve docker-compose.yml hazırla."


def _env(from_agent, to_agent, intent, files, **payload):
    return json.dumps({
        "from_agent": from_agent, "to_agent": to_agent, "intent": intent, "status": "SUCCESS",
        "payload": {"summary": f"{from_agent} teslim etti.", "friendly_dialogue": "hazır", "thinking": "t", "what_doing": "w", "what_next": "n",
                    "files": files, **payload},
        "metadata": {"tokens_used": 50},
    })


def _backend_env(body="def add(a, b):\n    return a + b\n"):
    return _env("BACKEND_DEV", "FRONTEND_DEV", "BACKEND_API_EXPOSED", [{"path": "src/calc.py", "content": body}])


def _start(client, steps):
    rid = client.post("/api/runs", json={"steps": steps, "engine": "mcp_client", "client": {"name": "t"}}).json()["run"]["run_id"]
    return rid


def _next(client, rid):
    return client.post(f"/api/runs/{rid}/next-step", json={"client": {"name": "t"}}).json()


def _wait_status(client, rid, status, timeout=8.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        run = client.get(f"/api/runs/{rid}").json()["run"]
        if run["status"] == status:
            return run
        time.sleep(0.1)
    raise AssertionError(f"timeout: {run['status']} != {status}")


# ---------------------------------------------------------------------------
# Yönetici notları
# ---------------------------------------------------------------------------
def test_note_reaches_next_step_context_and_is_not_carried_over(client, hub):
    hub.step_by_step_mode = False
    rid = _start(client, [3, 4])
    res = client.post(f"/api/runs/{rid}/notes", json={"text": NOTE})
    assert res.status_code == 200 and res.json()["note"]["id"] == "N-1" and res.json()["paused"] is False

    step = _next(client, rid)
    assert step["status"] == "STEP" and step["order"] == 3
    assert "## Yönetici notları" in step["user_context"] and NOTE in step["user_context"]
    # aynı adım tekrar istenirse (submit başarılı olana dek) not yine görünür
    assert NOTE in _next(client, rid)["user_context"]
    note = hub.runs[rid].manager_notes[0]
    assert note["delivered_step"] == 3 and note["delivered_at"]

    sub = client.post(f"/api/runs/{rid}/steps/3/result", json={"result_json": _backend_env()}).json()
    assert sub["status"] == "NEXT"
    later = _next(client, rid)
    assert later["order"] == 4 and "Yönetici notları" not in later["user_context"] and NOTE not in later["user_context"]
    assert any(e["action"] == "MANAGER_NOTE" and e["from_agent"] == "MANAGER" for e in hub.events)


def test_urgent_note_pauses_run_until_resumed(client, hub):
    hub.step_by_step_mode = False
    rid = _start(client, [3])
    res = client.post(f"/api/runs/{rid}/notes", json={"text": "Dur, önce portu değiştir.", "urgent": True}).json()
    assert res["paused"] is True and res["note"]["urgent"] is True
    assert hub.runs[rid].paused and hub.runs[rid].pause_reason == "manager-note"
    assert _next(client, rid)["status"] == "PAUSED"
    client.post(f"/api/runs/{rid}/resume")
    step = _next(client, rid)
    assert step["status"] == "STEP" and "Dur, önce portu değiştir." in step["user_context"]


def test_note_validation_and_unknown_run(client, hub):
    rid = _start(client, [3])
    assert client.post(f"/api/runs/{rid}/notes", json={"text": "   "}).status_code == 400
    assert client.post("/api/runs/run-yok/notes", json={"text": "x"}).status_code == 404
    client.post(f"/api/runs/{rid}/cancel", json={"reason": "t"})
    assert client.post(f"/api/runs/{rid}/notes", json={"text": "geç kaldı"}).status_code == 400
    assert client.get(f"/api/runs/{rid}/notes").json()["notes"] == []


def test_notes_survive_persistence_roundtrip(client, hub):
    rid = _start(client, [3])
    client.post(f"/api/runs/{rid}/notes", json={"text": NOTE})
    from server.runs import PipelineRun
    restored = PipelineRun.from_dict(hub.runs[rid].to_dict())
    assert restored.manager_notes and restored.manager_notes[0]["text"] == NOTE


# ---------------------------------------------------------------------------
# Revize iste
# ---------------------------------------------------------------------------
def _deliver_and_wait(client, rid, order, env):
    _next(client, rid)
    res = client.post(f"/api/runs/{rid}/steps/{order}/result", json={"result_json": env}).json()
    assert res["status"] == "WAITING_APPROVAL", res
    return res["approval_token"]


def test_revise_requires_comment_and_reopens_same_step_with_feedback(client, hub):
    hub.settings = {**hub.settings, "approval_mode": "every_step"}
    hub.step_by_step_mode = True
    rid = _start(client, [3, 4])
    token = _deliver_and_wait(client, rid, 3, _backend_env("def add(a, b):\n    return a - b\n"))

    # gerekçesiz revize reddedilir, bekleyen onay bozulmaz
    bad = client.post("/api/pipeline/approve-step", json={"decision": "REVISE", "token": token, "comment": "  "})
    assert bad.status_code == 400 and bad.json()["status"] == "INVALID"
    assert hub.runs[rid].status == "WAITING_APPROVAL"

    ok = client.post("/api/pipeline/approve-step", json={"decision": "REVISE", "token": token, "comment": "Toplama yerine çıkarma yazılmış, düzelt."})
    assert ok.status_code == 200
    run = _wait_status(client, rid, "ACTIVE")
    assert run["cursor"] == 0 and run["steps"][0]["order"] == 3 and run["steps"][0]["status"] == "PENDING"

    poll = client.post(f"/api/runs/{rid}/approval", json={"timeout_s": 1}).json()
    assert poll["status"] == "REVISE" and poll["next"] == "STEP" and poll["next_order"] == 3

    step = _next(client, rid)
    assert step["status"] == "STEP" and step["order"] == 3
    assert "REVİZE İSTEĞİ" in step["user_context"] and "Toplama yerine çıkarma yazılmış" in step["user_context"]
    assert any(e["action"] == "REVISE_REQUESTED" for e in hub.events)

    # düzeltilmiş teslim aynı sıra numarasıyla kabul edilir ve yeniden onaya gider
    again = client.post(f"/api/runs/{rid}/steps/3/result", json={"result_json": _backend_env()}).json()
    assert again["status"] == "WAITING_APPROVAL"
    client.post("/api/pipeline/approve-step", json={"decision": "PROCEED", "token": again["approval_token"]})
    run = _wait_status(client, rid, "ACTIVE")
    assert run["cursor"] == 1
    later = _next(client, rid)
    assert later["order"] == 4 and "REVİZE İSTEĞİ" not in later["user_context"]


def test_revise_not_supported_for_meetings_and_template_runs(client, hub):
    """Toplantı adımları yinelenen karar/soru üretir; şablon motoru içeriği yeniden üretmez → 400, onay bozulmaz."""
    from server import pipeline as P
    from server.runs import PipelineRun, StepRecord
    run = PipelineRun(project_id=hub.active_project_id, mode="sprint", status="WAITING_APPROVAL",
                      steps=[StepRecord(order=1008, issue_id="SPRINT-1", role="SCRUM_MASTER", kind="meeting")])
    assert "revize desteklenmiyor" in P.can_revise(hub, run, run.current_step)
    tpl = PipelineRun(project_id=hub.active_project_id, engine="template", status="WAITING_APPROVAL",
                      steps=[StepRecord(order=1, issue_id="JIRA-1", role="PM", kind="phase")])
    assert "yalnızca MCP istemcisi" in P.can_revise(hub, tpl, tpl.current_step)
    idle = PipelineRun(project_id=hub.active_project_id, status="ACTIVE", steps=[StepRecord(order=3, issue_id="JIRA-3", role="BACKEND_DEV", kind="phase")])
    assert "onay beklerken" in P.can_revise(hub, idle, idle.current_step)


def test_revise_of_architect_step_does_not_duplicate_backlog(client, hub):
    """Mimar adımı revize edilince önceki teslimin backlog görevleri geri alınır; yeniden teslimde çoğalmaz."""
    hub.settings = {**hub.settings, "approval_mode": "every_step"}
    hub.step_by_step_mode = True
    rid = _start(client, [2])
    backlog = [{"id": "T-01", "title": "Birinci görev", "role": "BACKEND_DEV"}, {"id": "T-02", "title": "İkinci görev", "role": "BACKEND_DEV"}]
    env = lambda: _env("ARCHITECT", "BACKEND_DEV", "DISPATCH_CONTRACT", [{"path": "docs/openapi_spec.json", "content": "{}"}], backlog=backlog)
    token = _deliver_and_wait(client, rid, 2, env())
    tasks = lambda: [i for i in hub.jira_issues.values() if i.get("kind") == "task"]
    assert len(tasks()) == 2

    client.post("/api/pipeline/approve-step", json={"decision": "REVISE", "token": token, "comment": "Görev sayısını azalt."})
    _wait_status(client, rid, "ACTIVE")
    assert tasks() == []                                     # önceki teslimin görevleri geri alındı
    _next(client, rid)
    again = client.post(f"/api/runs/{rid}/steps/2/result", json={"result_json": env()}).json()
    assert again["status"] == "WAITING_APPROVAL" and len(tasks()) == 2   # çoğalmadı


# ---------------------------------------------------------------------------
# Notlara cevap kanalı: payload.manager_replies → notta `reply`, MANAGER_REPLY olayı; cevapsızsa uyarı
# ---------------------------------------------------------------------------
def test_agent_reply_is_recorded_under_the_note_and_unanswered_warns(client, hub):
    hub.step_by_step_mode = False
    rid = _start(client, [3, 4])
    client.post(f"/api/runs/{rid}/notes", json={"text": "Bana çalışan bir uç verebilir misin?"})
    step = _next(client, rid)
    assert "Cevap zorunlu (N-1)" in step["user_context"] and "payload.manager_replies" in step["user_context"]
    env = json.loads(_backend_env())
    env["payload"]["manager_replies"] = [{"note_id": "n-1", "answer": "Evet: POST /api/v1/auth/register çalışıyor; giriş ucu henüz yok."},
                                         {"note_id": "N-99", "answer": "olmayan not"}, {"note_id": "N-1", "answer": ""}]
    client.post(f"/api/runs/{rid}/steps/3/result", json={"result_json": json.dumps(env)})
    note = hub.runs[rid].manager_notes[0]
    assert note["reply"]["by"] == "BACKEND_DEV" and note["reply"]["step"] == 3 and "giriş ucu henüz yok" in note["reply"]["answer"]
    assert not note.get("unanswered")
    replies = [e for e in hub.events if e["action"] == "MANAGER_REPLY"]
    assert len(replies) == 1 and replies[0]["to_agent"] == "MANAGER" and replies[0]["payload"]["note_id"] == "N-1"

    client.post(f"/api/runs/{rid}/notes", json={"text": "Peki ya OTP?"})                     # N-2: ikinci adımda cevapsız kalır
    _next(client, rid)
    client.post(f"/api/runs/{rid}/steps/4/result", json={"result_json": _env("FRONTEND_DEV", "QA", "UI_READY", [{"path": "src/ui.py", "content": "x = 1\n"}])})
    n2 = hub.runs[rid].manager_notes[1]
    assert n2["unanswered"] is True and not n2.get("reply")
    assert any(e["action"] == "MANAGER_NOTE_UNANSWERED" and e["payload"]["note_ids"] == ["N-2"] for e in hub.events)


def test_template_engine_runs_do_not_demand_replies(client, hub):
    hub.step_by_step_mode = False
    rid = client.post("/api/runs", json={"steps": [3], "engine": "template", "client": {"name": "t"}}).json()["run"]["run_id"]
    client.post(f"/api/runs/{rid}/notes", json={"text": "not"})
    time.sleep(1.0)
    assert not any(e["action"] == "MANAGER_NOTE_UNANSWERED" for e in hub.events)
