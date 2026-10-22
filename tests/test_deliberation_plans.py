"""C6: müzakerede 2-3 alternatif mimari plan, kullanıcı seçimi ve adım 2 bağlamına enjeksiyon."""

import asyncio
import json

import pytest
from mcp import Client
from mcp.types import Implementation

from server import pipeline as P
from server.runs import build_run
from server.steps import get_handler


def _s(res):
    return res.structured_content or json.loads(res.content[0].text)


PLANS = [
    {"id": "A", "title": "Plan A: Modüler Monolit", "summary": "FastAPI + React", "stack": ["FastAPI", "React"], "pros": ["Hızlı"], "cons": ["Ölçek"], "risk": "LOW", "recommended": True},
    {"id": "B", "title": "Plan B: Mikroservis", "summary": "Kuyruk tabanlı", "stack": ["FastAPI", "Kafka"], "pros": ["Ölçek"], "cons": ["Operasyon"], "risk": "MEDIUM"},
]


async def test_plan_choice_flow_via_mcp(patched_main, hub, tmp_project, client):
    async with Client(patched_main.mcp, client_info=Implementation(name="pytest", version="0")) as c:
        opened = _s(await c.call_tool("open_deliberation", {"title": "EventPulse"}))
        sid = opened["session"]["session_id"]
        res = await c.call_tool("deliberation_turn", {"session_id": sid, "agent_id": "ARCHITECT", "message": "İki alternatif var.", "sentiment": "PROPOSAL", "proposals_json": json.dumps(PLANS)})
        assert "2 plan" in res.content[0].text
        assert [p["id"] for p in hub.deliberation_engine.active_session.proposals] == ["A", "B"]

        closed = await c.call_tool("close_deliberation", {"session_id": sid, "consensus_json": json.dumps({"agreed_stack": ["FastAPI"]})})
        assert closed.content[0].text.startswith("AWAITING_PLAN_CHOICE")
        assert hub.deliberation_engine.active_session.status == "AWAITING_PLAN_CHOICE"

        waiting = _s(await c.call_tool("wait_for_approval", {"run_id": sid, "timeout_s": 1}))
        assert waiting["status"] == "STILL_WAITING"

        # Kullanıcı dashboard'dan Plan B'yi seçer
        r = client.post("/api/deliberation/choose-plan", json={"session_id": sid, "plan_id": "b"})
        assert r.status_code == 200 and r.json()["session"]["chosen_plan_id"] == "B"

        approved = _s(await c.call_tool("wait_for_approval", {"run_id": sid, "timeout_s": 5}))
        assert approved["status"] == "APPROVED" and approved["plan_id"] == "B"
        session = hub.deliberation_engine.get_latest_session()
        assert session["status"] == "CONSENSUS_REACHED"
        assert session["consensus_summary"]["chosen_plan"] == "Plan B: Mikroservis"
        assert session["consensus_summary"]["decision"] == "APPROVED_BY_USER"
        assert any(e["action"] == "PLAN_CHOSEN" for e in hub.events)

    # Adım 2 (ARCHITECT) bağlamına seçilen plan enjekte edilir
    run = build_run(hub.active_project_id, tmp_project, hub.get_jira_issues(), [2], engine="mcp_client")
    ctx = P.make_context(hub, run, run.steps[0])
    prompt = get_handler(2).build_user_prompt(ctx)
    assert "Plan B: Mikroservis" in prompt and "Kafka" in prompt


async def test_close_with_explicit_choice_skips_waiting(hub):
    eng = hub.deliberation_engine
    sid = eng.open({"title": "x"})["session_id"]
    await eng.add_turn(sid, "ARCHITECT", "planlar", "PROPOSAL", proposals=PLANS)
    session = await eng.close(sid, {"chosen_plan_id": "A"})
    # Ajanlar öneri çıkarır; nihai karar yöneticinin: onay gelene kadar KESİN değildir
    assert session["status"] == "AWAITING_APPROVAL" and session["chosen_plan_id"] is None and session["consensus_summary"]["proposed_plan_id"] == "A"
    final = await eng.approve(sid, "")                              # öneriyi onayla
    assert final["status"] == "CONSENSUS_REACHED" and final["chosen_plan_id"] == "A" and final["consensus_summary"]["chosen_plan"] == "Plan A: Modüler Monolit"


def test_choose_plan_unknown_returns_404(client, hub):
    sid = hub.deliberation_engine.open({"title": "x"})["session_id"]
    r = client.post("/api/deliberation/choose-plan", json={"session_id": sid, "plan_id": "Z"})
    assert r.status_code == 404
