"""El kaldırma modları (C4): should_wait kararları ve 'not al ve devam et' akışı; hız ayarı (C5)."""

import time

import pytest

from server import pipeline as P
from server.runs import build_run
from server.steps import get_handler
from server.steps.base import StepResult


def _result(status="SUCCESS"):
    return StepResult(summary="x", action="A", next_agent_id=None, status=status)


@pytest.mark.parametrize("mode,order,status,expected", [
    ("auto", 2, "SUCCESS", "SKIP"),
    ("auto", 2, "FAILED", "SKIP"),
    ("critical_only", 1, "SUCCESS", "SKIP"),
    ("critical_only", 2, "SUCCESS", "WAIT"),      # ARCHITECT kritik
    ("critical_only", 3, "FAILED", "WAIT"),       # başarısız adım
    ("critical_only", 9, "SUCCESS", "WAIT"),      # PO UAT kritik
    ("every_step", 3, "SUCCESS", "WAIT"),
    ("note_and_continue", 3, "SUCCESS", "NOTE"),
    ("note_and_continue", 6, "FAILED", "WAIT"),
])
async def test_should_wait_matrix(hub, tmp_project, mode, order, status, expected):
    await hub.update_settings({"approval_mode": mode})
    run = build_run(hub.active_project_id, tmp_project, hub.get_jira_issues(), [order], engine="template", step_by_step=True)
    assert P.should_wait(hub, run, get_handler(order), _result(status)) == expected


async def test_run_step_flag_false_skips_regardless_of_mode(hub, tmp_project):
    await hub.update_settings({"approval_mode": "every_step"})
    run = build_run(hub.active_project_id, tmp_project, hub.get_jira_issues(), [2], engine="template", step_by_step=False)
    assert P.should_wait(hub, run, get_handler(2), _result()) == "SKIP"


def test_note_and_continue_records_raised_hands(client, hub, tmp_project):
    client.post("/api/pipeline/approval-mode", json={"approval_mode": "note_and_continue"})
    assert hub.step_by_step_mode is True
    res = client.post("/api/runs", json={"steps": [1, 2], "engine": "template", "step_by_step": True})
    run_id = res.json()["run"]["run_id"]
    deadline = time.time() + 20
    while time.time() < deadline:
        run = client.get(f"/api/runs/{run_id}").json()["run"]
        if run["is_terminal"]:
            break
        time.sleep(0.1)
    assert run["status"] == "COMPLETED"  # hiç durmadan bitti
    hands = client.get("/api/pipeline/raised-hands").json()
    assert hands["unreviewed"] == 2
    assert [h["order"] for h in hands["raised_hands"]] == [2, 1]
    assert hands["raised_hands"][0]["critical"] is True
    audits = [a["action"] for a in hub.jira_issues["JIRA-1"]["audit_trail"]]
    assert "HAND_RAISED" in audits

    hid = hands["raised_hands"][0]["id"]
    assert client.post(f"/api/pipeline/raised-hands/{hid}/resolve", json={"reviewed": True}).json()["hand"]["reviewed"] is True
    assert client.get("/api/pipeline/raised-hands").json()["unreviewed"] == 1


def test_step_mode_toggle_maps_to_approval_mode(client, hub):
    client.post("/api/pipeline/set-step-mode", json={"step_by_step": False})
    assert hub.get_settings()["approval_mode"] == "auto" and hub.step_by_step_mode is False
    client.post("/api/pipeline/set-step-mode", json={"step_by_step": True})
    assert hub.get_settings()["approval_mode"] == "every_step" and hub.step_by_step_mode is True
    res = client.post("/api/pipeline/approval-mode", json={"approval_mode": "bogus"})
    assert res.status_code == 400


async def test_pacing_instant_skips_sleep(hub, tmp_project, monkeypatch):
    import asyncio
    calls = []
    async def fake_sleep(s):
        calls.append(s)
    monkeypatch.setattr(P.asyncio, "sleep", fake_sleep)
    run = build_run(hub.active_project_id, tmp_project, hub.get_jira_issues(), [1], engine="template")
    await hub.update_settings({"pacing": "instant"})
    await P.pace(hub, run, 2.0)
    assert calls == []
    await hub.update_settings({"pacing": "natural"})
    await P.pace(hub, run, 5.0)
    assert calls == [3.0]  # tavan 3 sn
    run.engine = "mcp_client"
    await P.pace(hub, run, 5.0)
    assert calls == [3.0]  # MCP istemcisinde uyunmaz


async def test_auto_all_is_scoped_to_its_run(hub, tmp_project):
    """AUTO_ALL kararı yalnızca verildiği koşunun kalan adımlarını atlar; sonraki koşu yine onay bekler."""
    from server.runs import build_run
    from server.steps.registry import SERVER_SIDE_ORDERS

    await hub.update_settings({"approval_mode": "every_step"})
    issues = hub.get_jira_issues()
    run_a = build_run(project_id=hub.active_project_id, project_dir=tmp_project, issues=issues, selected=[1, 2], engine="template",
                      custom_prompt="", step_by_step=True, server_side_orders=SERVER_SIDE_ORDERS)
    hub.register_run(run_a)
    run_a.approval_token = hub.gate.mint()
    hub.gate.register(run_a.approval_token, {"order": 1})
    await P.apply_approval_decision(hub, run_a, "AUTO_ALL")
    assert hub.auto_proceed_all is True and hub.auto_proceed_run_id == run_a.run_id
    assert hub.step_by_step_mode is True  # hub modu değişmedi

    handler = get_handler(2, next(i for i in issues if i["id"] == "JIRA-2"))
    ok = StepResult(status="SUCCESS", summary="x", action=handler.action, next_agent_id=handler.next_agent_id)
    assert P.should_wait(hub, run_a, handler, ok) == "SKIP"

    run_b = build_run(project_id=hub.active_project_id, project_dir=tmp_project, issues=issues, selected=[2], engine="template",
                      custom_prompt="", step_by_step=True, server_side_orders=SERVER_SIDE_ORDERS)
    assert P.should_wait(hub, run_b, handler, ok) == "WAIT"  # başka koşu etkilenmez

    await P.finalize_run(hub, run_a, status="COMPLETED")
    assert hub.auto_proceed_all is False and hub.auto_proceed_run_id is None
