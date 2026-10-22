"""
MCP çekme (pull) modeli uçtan uca: süreç içi `mcp.Client` ile araçları Claude Desktop gibi çağırır.
"""

import asyncio
import json
import os

import pytest
from mcp import Client
from mcp.types import Implementation


def _pm_envelope(run_id: str) -> str:
    return json.dumps({
        "trace_id": run_id,
        "from_agent": "PM",
        "to_agent": "ARCHITECT",
        "intent": "TASK_DISPATCH",
        "status": "SUCCESS",
        "payload": {
            "summary": "PM PRD'yi hazırladı.",
            "friendly_dialogue": "Mimar, PRD hazır!",
            "thinking": "Notları analiz ettim.",
            "what_doing": "PRD yazıyor",
            "what_next": "Mimari tasarım",
            "user_stories": [{"id": "US-01", "as_a": "Kullanıcı", "i_want": "giriş", "so_that": "erişim"}],
            "acceptance_criteria": ["API < 120ms"],
            "files": [{"path": "FS-docs/PRD.md", "content": "# PRD\n\nTest PRD içeriği.\n"}],
        },
        "metadata": {"tokens_used": 321, "current_file": "FS-docs/PRD.md"},
    })


def _structured(result):
    if result.structured_content:
        return result.structured_content
    return json.loads(result.content[0].text)


@pytest.fixture
def mcp_server(patched_main):
    return patched_main.mcp


async def test_pull_model_run_with_approval(mcp_server, hub, tmp_project):
    """start → next (adım 1) → submit → WAITING_APPROVAL → onay → adım 2 → submit → RUN_COMPLETE."""
    hub.step_by_step_mode = True
    async with Client(mcp_server, client_info=Implementation(name="pytest-claude-desktop", version="0.1")) as c:
        res = _structured(await c.call_tool("start_pipeline_run", {"steps": [1, 2]}))
        assert res["status"] == "STARTED"
        run_id = res["run"]["run_id"]
        assert res["run"]["engine"] == "mcp_client"
        assert res["run"]["status"] == "QUEUED"
        assert res["run"]["client_name"] == "pytest-claude-desktop"

        # İdempotent: ikinci başlatma aynı koşuyu döner
        again = _structured(await c.call_tool("start_pipeline_run", {"steps": [1, 2]}))
        assert again["status"] == "EXISTING" and again["run"]["run_id"] == run_id

        step = _structured(await c.call_tool("get_next_step", {"run_id": run_id}))
        assert step["status"] == "STEP"
        assert step["order"] == 1 and step["agent_id"] == "PM"
        assert "Product Manager" in step["system_prompt"]
        assert '"payload"' in step["output_contract"]
        assert hub.runs[run_id].status == "ACTIVE"
        assert hub.jira_issues["JIRA-1"]["status"] == "IN_PROGRESS"

        # Aynı adım submit edilene kadar tekrar döner (idempotent)
        step_again = _structured(await c.call_tool("get_next_step", {"run_id": run_id}))
        assert step_again["order"] == 1

        await c.call_tool("report_thinking", {"run_id": run_id, "agent_id": "PM", "text": "PRD'yi derliyorum."})
        assert hub.agents["PM"]["current_thinking"] == "PRD'yi derliyorum."

        # Bozuk JSON → REJECTED (koşu bozulmaz)
        bad = _structured(await c.call_tool("submit_step_result", {"run_id": run_id, "order": 1, "result_json": "bu json değil"}))
        assert bad["status"] == "REJECTED" and bad["validation_errors"]

        # Yanlış sıra → REJECTED
        wrong = _structured(await c.call_tool("submit_step_result", {"run_id": run_id, "order": 2, "result_json": _pm_envelope(run_id)}))
        assert wrong["status"] == "REJECTED"

        ok = _structured(await c.call_tool("submit_step_result", {
            "run_id": run_id, "order": 1, "result_json": _pm_envelope(run_id), "tokens_in": 1200, "tokens_out": 321,
        }))
        assert ok["status"] == "WAITING_APPROVAL" and ok["approval_token"]
        assert os.path.isfile(os.path.join(tmp_project, "FS-docs", "PRD.md"))
        assert hub.jira_issues["JIRA-1"]["status"] == "IN_REVIEW"   # teslim edildi, yönetici onayı bekliyor (onayda DONE)
        assert hub.runs[run_id].steps[0].tokens_out == 321
        assert any(e["action"] == "TASK_DISPATCH" and e["from_agent"] == "PM" for e in hub.events)

        waiting = _structured(await c.call_tool("wait_for_approval", {"run_id": run_id, "timeout_s": 1}))
        assert waiting["status"] == "STILL_WAITING"

        # Kullanıcı dashboard'dan onaylar → karar anında uygulanır
        token = hub.pending_step_approval["approval_token"]
        assert (await hub.approve_step("PROCEED", token=token))["status"] == "APPROVED"
        approved = _structured(await c.call_tool("wait_for_approval", {"run_id": run_id, "timeout_s": 5}))
        assert approved["status"] == "APPROVED" and approved["next_order"] == 2
        assert hub.jira_issues["JIRA-1"]["status"] == "DONE"   # onayla birlikte madde kapanır

        step2 = _structured(await c.call_tool("get_next_step", {"run_id": run_id}))
        assert step2["status"] == "STEP" and step2["order"] == 2 and step2["agent_id"] == "ARCHITECT"
        assert "FS-docs/PRD.md" in step2["user_context"]  # önceki artefakt bağlama eklendi

        env2 = json.loads(_pm_envelope(run_id))
        env2.update({"from_agent": "ARCHITECT", "to_agent": "BACKEND_DEV", "intent": "DISPATCH_CONTRACT"})
        env2["payload"]["files"] = [{"path": "FS-docs/openapi_spec.json", "content": "{\"openapi\": \"3.0.0\"}"}]
        done = _structured(await c.call_tool("submit_step_result", {"run_id": run_id, "order": 2, "result_json": json.dumps(env2)}))
        assert done["status"] == "WAITING_APPROVAL"
        await hub.approve_step("PROCEED", token=hub.pending_step_approval["approval_token"])
        final = _structured(await c.call_tool("wait_for_approval", {"run_id": run_id, "timeout_s": 5}))
        assert final["status"] == "APPROVED" and final["next"] == "RUN_COMPLETE"

        end = _structured(await c.call_tool("get_next_step", {"run_id": run_id}))
        assert end["status"] == "RUN_COMPLETE"
        assert hub.runs[run_id].status == "COMPLETED"
        assert hub.active_run_id is None

        runs = _structured(await c.call_tool("list_runs", {}))
        assert runs["runs"][0]["run_id"] == run_id

    assert hub.connected_clients["pytest-claude-desktop"]["calls"] >= 5


async def test_path_traversal_in_files_is_rejected(mcp_server, hub, tmp_project):
    hub.step_by_step_mode = False
    async with Client(mcp_server, client_info=Implementation(name="pytest", version="0")) as c:
        run_id = _structured(await c.call_tool("start_pipeline_run", {"steps": [1]}))["run"]["run_id"]
        await c.call_tool("get_next_step", {"run_id": run_id})
        env = json.loads(_pm_envelope(run_id))
        env["payload"]["files"] = [{"path": "../../evil.md", "content": "x"}]
        res = _structured(await c.call_tool("submit_step_result", {"run_id": run_id, "order": 1, "result_json": json.dumps(env)}))
        assert res["status"] == "REJECTED"
        assert not os.path.exists(os.path.join(tmp_project, "..", "..", "evil.md"))


async def test_template_fallback_after_max_attempts(mcp_server, hub, tmp_project, monkeypatch):
    """Şablon yedeği yalnızca `llm_fallback` açıkken (deneme); G1 varsayılanı kapalıdır (bkz. test_g1_real_evidence)."""
    import server.engine.mcp_client as m
    monkeypatch.setattr(m, "MAX_STEP_ATTEMPTS", 2)
    await hub.update_settings({"llm_fallback": True, "approval_mode": "auto"})   # update_settings adım-adım bayrağını onay modundan türetir
    hub.step_by_step_mode = False
    async with Client(mcp_server, client_info=Implementation(name="pytest", version="0")) as c:
        run_id = _structured(await c.call_tool("start_pipeline_run", {"steps": [1]}))["run"]["run_id"]
        await c.call_tool("get_next_step", {"run_id": run_id})
        first = _structured(await c.call_tool("submit_step_result", {"run_id": run_id, "order": 1, "result_json": "garbage"}))
        assert first["status"] == "REJECTED"
        second = _structured(await c.call_tool("submit_step_result", {"run_id": run_id, "order": 1, "result_json": "garbage"}))
        assert second["status"] == "RUN_COMPLETE"  # şablon yedeği ile tamamlandı
        assert os.path.isfile(os.path.join(tmp_project, "FS-docs", "PRD.md"))
        audits = [a["action"] for a in hub.jira_issues["JIRA-1"]["audit_trail"]]
        assert "LLM_FALLBACK" in audits


async def test_abandoned_run_is_revived_by_next_step(mcp_server, hub, tmp_project):
    from datetime import datetime, timedelta, timezone
    hub.step_by_step_mode = False
    async with Client(mcp_server, client_info=Implementation(name="pytest", version="0")) as c:
        run_id = _structured(await c.call_tool("start_pipeline_run", {"steps": [1, 2]}))["run"]["run_id"]
        await c.call_tool("get_next_step", {"run_id": run_id})
        run = hub.runs[run_id]
        run.last_seen = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        api = hub._runs_api
        assert await api.mcp.sweep_once() == 1
        assert run.status == "ABANDONED"
        step = _structured(await c.call_tool("get_next_step", {"run_id": run_id}))
        assert step["status"] == "STEP" and step["order"] == 1
        assert run.status == "ACTIVE"
        cancelled = await c.call_tool("cancel_pipeline_run", {"run_id": run_id, "reason": "test"})
        assert "CANCELLED" in cancelled.content[0].text
        assert run.status == "CANCELLED"


async def test_prompt_and_tool_listing(mcp_server):
    async with Client(mcp_server, client_info=Implementation(name="pytest", version="0")) as c:
        tools = {t.name for t in (await c.list_tools()).tools}
        for name in ("start_pipeline_run", "get_next_step", "submit_step_result", "wait_for_approval",
                     "report_thinking", "cancel_pipeline_run", "list_runs", "open_deliberation",
                     "deliberation_turn", "close_deliberation", "emit_agent_event", "run_playwright_e2e"):
            assert name in tools, name
        prompts = {p.name for p in (await c.list_prompts()).prompts}
        assert "run_software_company" in prompts
        rendered = await c.get_prompt("run_software_company", {"project_id": "demo-app", "steps": "1-10"})
        text = rendered.messages[0].content.text
        assert "start_pipeline_run" in text and "wait_for_approval" in text


async def test_deliberation_via_mcp(mcp_server, hub):
    async with Client(mcp_server, client_info=Implementation(name="pytest", version="0")) as c:
        opened = _structured(await c.call_tool("open_deliberation", {"title": "EventPulse"}))
        sid = opened["session"]["session_id"]
        assert opened["turn_order"][0] == "PM" and opened["participants"]
        await c.call_tool("deliberation_turn", {"session_id": sid, "agent_id": "ARCHITECT", "message": "Plan A vs Plan B", "sentiment": "PROPOSAL"})
        await c.call_tool("close_deliberation", {"session_id": sid, "consensus_json": json.dumps({"chosen_plan": "Plan A"})})
        latest = hub.deliberation_engine.get_latest_session()
        assert latest["status"] == "AWAITING_APPROVAL"                      # ajan önerisi: nihai karar yöneticide
        assert latest["consensus_summary"]["chosen_plan"] == "Plan A"
        assert any(e["action"] == "DELIBERATION_SPEECH" for e in hub.events)
