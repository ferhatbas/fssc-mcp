"""Yönetici backlog'u yönetir: alan düzenleme, sprinte sabitleme, sıralama; sprint seçimi bunlara uyar."""

from server import sprint as SP


def _task(hub, iid, order, prio="P1"):
    hub.jira_issues[iid] = {"id": iid, "key": f"DEV-{order}", "order": order, "title": iid, "description": "", "issue_type": "TASK",
                            "kind": "task", "status": "BACKLOG", "priority": prio, "assignee": "BACKEND_DEV", "acceptance_criteria": [],
                            "attachments": [], "audit_trail": [], "created_at": "", "updated_at": ""}


def test_pinned_issue_is_candidate_only_for_its_sprint(hub):
    for n, iid in enumerate(("A", "B", "C"), start=1):
        _task(hub, iid, n)
    hub.jira_issues["B"]["planned_sprint"] = 2
    assert [i["id"] for i in SP.select_items(hub, 5, 1)[0]] == ["A", "C"]
    assert [i["id"] for i in SP.select_items(hub, 5, 2)[0]][0] == "B"      # sabitlenen önce gelir


def test_reorder_moves_item_and_selection_follows(hub):
    for n, iid in enumerate(("A", "B", "C"), start=1):
        _task(hub, iid, n)
    assert SP.reorder_backlog(hub, "C", "up", 1) and SP.reorder_backlog(hub, "C", "up", 1)
    assert [i["id"] for i in SP.select_items(hub, 5, 1)[0]] == ["C", "A", "B"]
    assert SP.reorder_backlog(hub, "C", "up", 1) is False                   # zaten başta


def test_plan_endpoint_edits_pins_and_rejects_started_work(client, hub):
    _task(hub, "A", 1); _task(hub, "B", 2)
    ok = client.post("/api/jira/issues/B/plan", json={"title": "Yeni başlık", "priority": "P0", "planned_sprint": 3})
    assert ok.status_code == 200, ok.text
    assert hub.jira_issues["B"]["title"] == "Yeni başlık" and hub.jira_issues["B"]["planned_sprint"] == 3
    assert client.post("/api/jira/issues/B/plan", json={"move": "up"}).status_code in (200, 409)
    assert client.post("/api/jira/issues/B/plan", json={"planned_sprint": 0}).status_code == 400
    hub.jira_issues["A"]["status"] = "IN_PROGRESS"
    assert client.post("/api/jira/issues/A/plan", json={"planned_sprint": 2}).status_code == 409
    assert client.post("/api/jira/issues/YOK/plan", json={}).status_code == 404
