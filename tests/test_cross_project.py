"""C3: projeler arası ekip mesajı (Web ↔ Mobil)."""

import json

from mcp import Client
from mcp.types import Implementation


def test_message_to_active_project_becomes_live_event(client, hub):
    pid = hub.active_project_id
    r = client.post(f"/api/projects/{pid}/message", json={"from_agent": "FRONTEND_DEV", "to_agent": "PM", "message": "Web ekibinden selam!"})
    assert r.status_code == 200
    ev = r.json()["event"]
    assert ev["action"] == "CROSS_PROJECT_MESSAGE" and ev["from_project"] == pid and ev["to_project"] == pid
    assert hub.events[-1]["id"] == ev["id"]


def test_message_to_other_project_is_queued_there(client, hub, tmp_path):
    other = tmp_path / "mobile_app"
    other.mkdir()
    hub.register_project(str(other), name="Mobil")
    src = hub.active_project_id
    r = client.post("/api/projects/mobile_app/message", json={"from_agent": "PM", "to_agent": "ARCHITECT", "message": "Mobil ekip, API kontratı hazır."})
    assert r.status_code == 200
    ev = r.json()["event"]
    assert ev["to_project"] == "mobile_app" and ev["from_project"] == src
    assert hub.projects["mobile_app"]["events"][-1]["action"] == "CROSS_PROJECT_MESSAGE"
    assert all(e["id"] != ev["id"] for e in hub.events)  # aktif projenin canlı kuyruğuna girmez
    assert client.post("/api/projects/nope/message", json={"message": "x"}).status_code == 404


async def test_cross_project_mcp_tool(patched_main, hub):
    async with Client(patched_main.mcp, client_info=Implementation(name="pytest", version="0")) as c:
        res = await c.call_tool("send_cross_project_message", {"target_project_id": hub.active_project_id, "from_agent": "QA", "to_agent": "PM", "message": "merhaba"})
        assert res.content[0].text.startswith("OK:")
        assert hub.events[-1]["action"] == "CROSS_PROJECT_MESSAGE"
