"""
TelemetryHub çekirdek davranış testleri (izole hub fixture'ı ile).
"""

import asyncio
import json
import os

import pytest

from agents.schemas import A2AMessage, AgentRole, MessageIntent


class FakeWS:
    """Gönderim başarısı/başarısızlığı ayarlanabilen sahte WebSocket."""

    def __init__(self, fail: bool = False):
        self.fail = fail
        self.sent = []

    async def accept(self):
        return None

    async def send_text(self, payload: str):
        if self.fail:
            raise RuntimeError("socket closed")
        self.sent.append(json.loads(payload))


async def test_event_ids_are_unique_beyond_deque_capacity(hub):
    """B4: 500'lük deque dolsa bile olay kimlikleri çakışmamalı."""
    from server.config import MAX_HISTORY_EVENTS

    ids = []
    for i in range(MAX_HISTORY_EVENTS + 5):
        e = await hub.record_event(
            trace_id="t", from_agent="PM", to_agent="ARCHITECT",
            action="TASK_DISPATCH", status="SUCCESS", payload={"i": i}
        )
        ids.append(e["id"])
    assert len(set(ids)) == len(ids)
    assert ids[-1] == f"evt-{MAX_HISTORY_EVENTS + 5:06d}"
    assert hub.stats["event_seq"] == MAX_HISTORY_EVENTS + 5


async def test_broadcast_drops_dead_connection_and_keeps_others(hub):
    """B1: ölü soket yayını kesmemeli, sadece listeden düşmeli."""
    good, dead = FakeWS(), FakeWS(fail=True)
    hub.active_connections.update({good, dead})

    await hub.broadcast({"type": "PING"})

    assert good in hub.active_connections
    assert dead not in hub.active_connections
    assert good.sent[-1]["type"] == "PING"


async def test_mcp_tool_functions_record_event_and_task(patched_main, hub):
    from server.main import emit_agent_event, update_task_state

    res1 = await emit_agent_event(
        trace_id="trace-001", from_agent="PM", to_agent="ARCHITECT",
        action="DISPATCH_PRD", status="SUCCESS",
        payload='{"title": "Auth"}', current_file="docs/prd.md", tokens_used=120
    )
    assert "recorded" in res1

    res2 = await update_task_state(
        task_id="FEAT-01", new_state="ARCHITECTURE", title="User Auth",
        assignee="ARCHITECT", priority="P0"
    )
    assert "FEAT-01" in res2

    snapshot = hub.get_snapshot()
    assert len(snapshot["events"]) == 1
    assert snapshot["events"][0]["from_agent"] == "PM"
    assert snapshot["tasks"][0]["id"] == "FEAT-01"


async def test_registry_is_written_to_isolated_path(hub, tmp_path):
    """A3.1: kalıcılık yalnızca enjekte edilen yola yazılmalı."""
    await hub.record_event(
        trace_id="t", from_agent="PM", to_agent="ARCHITECT",
        action="TASK_DISPATCH", status="SUCCESS", payload={}
    )
    await hub.flush_async()

    assert os.path.isfile(hub.registry_path)
    data = json.loads(open(hub.registry_path, encoding="utf-8").read())
    assert data["active_project_id"] in data["projects"]
    assert str(tmp_path) in hub.registry_path
    # Atomik yazım: geçici dosya kalmamalı
    assert not os.path.exists(hub.registry_path + ".tmp")


async def test_approval_gate_token_flow(hub):
    """B2: onay token bazlı çözülmeli; yanlış token bekleyeni serbest bırakmamalı."""
    waiter = asyncio.create_task(hub.wait_for_step_approval({"order": 1, "title": "x"}, timeout_s=5))
    await asyncio.sleep(0.05)

    assert hub.pending_step_approval is not None
    token = hub.pending_step_approval["approval_token"]

    wrong = await hub.approve_step("PROCEED", token="nope")
    assert wrong["status"] == "NO_PENDING_STEP"
    assert not waiter.done()

    ok = await hub.approve_step("PROCEED", token=token)
    assert ok["status"] == "APPROVED"
    assert await waiter == "PROCEED"
    assert hub.pending_step_approval is None


async def test_approval_gate_times_out(hub):
    decision = await hub.wait_for_step_approval({"order": 2}, timeout_s=0.05)
    assert decision == "TIMEOUT"
    assert hub.pending_step_approval is None
    assert hub.gate.pending_tokens == []


async def test_reset_cancels_pending_approval(hub):
    waiter = asyncio.create_task(hub.wait_for_step_approval({"order": 3}, timeout_s=5))
    await asyncio.sleep(0.05)
    await hub.reset()
    assert await waiter == "CANCELLED"


def test_a2a_message_accepts_all_pipeline_roles():
    msg = A2AMessage(
        trace_id="req-1", from_agent=AgentRole.BACKEND_DEV, to_agent=AgentRole.QA,
        intent=MessageIntent.BACKEND_API_EXPOSED, payload={"files": []}
    )
    assert msg.from_agent == "BACKEND_DEV"
    assert AgentRole("SCM") is AgentRole.SCM
