"""
Ajan zaman çizelgesi: JSONL olay deposu ve /api/agents/{id}/timeline ucu.
"""

import json
import os

from server.event_store import append_event, events_path, query_events, summarize_interactions


def test_event_store_append_and_query(tmp_project):
    for i in range(5):
        append_event(tmp_project, {"id": f"evt-{i:06d}", "from_agent": "PM" if i % 2 == 0 else "QA",
                                   "to_agent": "ARCHITECT", "action": "X", "timestamp": f"2026-09-17T10:0{i}:00+00:00"})
    assert os.path.isfile(events_path(tmp_project))
    pm = query_events(tmp_project, "PM")
    assert [e["id"] for e in pm] == ["evt-000004", "evt-000002", "evt-000000"]  # yeniden eskiye
    arch = query_events(tmp_project, "ARCHITECT", since="2026-09-17T10:03:00+00:00")
    assert {e["id"] for e in arch} == {"evt-000003", "evt-000004"}
    # fallback (bellek) ile tekilleştirme
    merged = query_events(tmp_project, "PM", fallback=[{"id": "evt-000004"}, {"id": "evt-000099", "from_agent": "PM", "to_agent": "QA", "timestamp": "2026-09-17T11:00:00+00:00"}])
    assert [e["id"] for e in merged][:2] == ["evt-000099", "evt-000004"]
    summary = summarize_interactions("PM", merged)
    assert summary["ARCHITECT"]["sent"] == 3 and summary["QA"]["sent"] == 1


async def test_record_event_writes_jsonl_and_timeline_endpoint(client, hub, tmp_project):
    await hub.record_event(trace_id="t", from_agent="PM", to_agent="ARCHITECT", action="TASK_DISPATCH", status="SUCCESS", payload={})
    await hub.record_event(trace_id="t", from_agent="ARCHITECT", to_agent="PM", action="DISPATCH_CONTRACT", status="SUCCESS", payload={})
    await hub.record_event(trace_id="t", from_agent="QA", to_agent="BACKEND_DEV", action="REPORT_BUG", status="FAILED", payload={})
    await hub.record_task_audit("JIRA-1", "PM", "USER_NOTE", notes="PRD gözden geçirildi")
    hub.deliberation_engine.open({"title": "x"})
    await hub.deliberation_engine.add_turn(hub.deliberation_engine.active_session.session_id, "PM", "Plan A diyorum", "PROPOSAL")

    lines = open(events_path(tmp_project), encoding="utf-8").read().strip().splitlines()
    assert len(lines) == 4 and json.loads(lines[0])["action"] == "TASK_DISPATCH"

    res = client.get("/api/agents/pm/timeline?limit=50")
    assert res.status_code == 200
    body = res.json()
    assert body["agent_id"] == "PM"
    actions = [e["action"] for e in body["events"]]
    assert actions == ["DELIBERATION_SPEECH", "DISPATCH_CONTRACT", "TASK_DISPATCH"]  # QA→BACKEND_DEV dahil değil
    assert body["audits"][0]["action"] == "USER_NOTE" and body["audits"][0]["issue_id"] == "JIRA-1"
    assert len(body["deliberation"]) == 1
    assert body["interactions"]["ARCHITECT"] == {"sent": 1, "received": 1, "last_at": body["interactions"]["ARCHITECT"]["last_at"], "last_action": "DISPATCH_CONTRACT"}
