"""Jira durumu adım yaşam döngüsünü izler: teslim sonrası onay beklerken IN_REVIEW, onayla DONE."""

import asyncio
import json

from tests.test_stale_fix import GOOD_BODY, _env


async def test_issue_is_in_review_while_waiting_then_done_after_approval(client, hub):
    hub.step_by_step_mode = True
    await hub.update_settings({"approval_mode": "every_step", "auto_verify": False, "auto_commit": False})
    rid = client.post("/api/runs", json={"steps": [3], "engine": "mcp_client", "client": {"name": "t"}}).json()["run"]["run_id"]
    client.post(f"/api/runs/{rid}/next-step", json={"client": {"name": "t"}})
    assert hub.jira_issues["JIRA-3"]["status"] == "IN_PROGRESS"

    res = client.post(f"/api/runs/{rid}/steps/3/result", json={"result_json": _env(GOOD_BODY)}).json()
    assert res["status"] == "WAITING_APPROVAL"
    assert hub.jira_issues["JIRA-3"]["status"] == "IN_REVIEW"

    client.post("/api/pipeline/approve-step", json={"decision": "PROCEED", "token": res["approval_token"]})
    for _ in range(100):      # karar koşuya olay döngüsünde ayrı görevle uygulanır; yük altında HTTP yanıtından sonra tamamlanabilir
        if hub.jira_issues["JIRA-3"]["status"] == "DONE":
            break
        await asyncio.sleep(0.05)
    assert hub.jira_issues["JIRA-3"]["status"] == "DONE"
    assert any(e.get("action") == "APPROVED" for e in hub.jira_issues["JIRA-3"]["audit_trail"])
