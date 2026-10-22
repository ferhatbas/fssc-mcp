"""Ajan havuzu: şirket geneli tanımlar projelere kendiliğinden eklenmez; yönetici havuzdan bağlı ya da bağımsız kopya olarak ekler; projeden gerçekten çıkarılır."""
from server import agent_registry as AR

POOL_AGENT = {"id": "MOBILE_DEV", "name": "Mobil Geliştirici", "role": "Mobile Developer", "role_base": "FRONTEND_DEV", "capabilities": ["FEATURE", "BUG"], "focus": ["mobil"]}


async def _second_project(hub, tmp_path):
    path = tmp_path / "second_project"
    path.mkdir()
    return hub.register_project(str(path), "ikinci")["id"]


async def test_pool_agent_is_not_auto_added_and_can_be_added_linked_or_as_copy(client, hub, tmp_path, isolated_agent_registry):
    assert client.post("/api/agents/global", json=POOL_AGENT).status_code == 200
    second = await _second_project(hub, tmp_path)
    await hub.switch_project(second)
    assert "MOBILE_DEV" not in hub.agents                                                   # havuzda ama bu projede yok
    pool = {a["id"]: a for a in client.get("/api/agents/global").json()["agents"]}
    assert pool["MOBILE_DEV"]["in_project"] is False

    res = client.post("/api/agents/pool/MOBILE_DEV/add", json={"mode": "linked"})
    assert res.status_code == 200 and res.json()["agent"]["scope"] == "global" and hub.agents["MOBILE_DEV"]["inherits"] == "MOBILE_DEV"
    assert client.post("/api/agents/pool/MOBILE_DEV/add", json={}).status_code == 400       # zaten var

    cp = client.post("/api/agents/pool/MOBILE_DEV/add", json={"mode": "copy", "id": "MOBILE_DEV_KOPYA"}).json()["agent"]
    assert cp["scope"] == "project" and "inherits" not in cp and cp["pool_origin"] == "MOBILE_DEV" and cp["focus"] == ["mobil"]
    assert client.post("/api/agents/pool/YOK/add", json={}).status_code == 400


async def test_removing_a_pooled_agent_from_the_project_really_removes_it_and_it_stays_out(client, hub, isolated_agent_registry):
    client.post("/api/agents/global", json=POOL_AGENT)
    hub._sync_global_agents()
    hub.agents.pop("MOBILE_DEV", None)
    client.post("/api/agents/pool/MOBILE_DEV/add", json={"mode": "linked"})
    assert client.delete("/api/agents/MOBILE_DEV").status_code == 200
    hub._sync_global_agents()
    assert "MOBILE_DEV" not in hub.agents and "MOBILE_DEV" in AR.load_global()              # havuzda durur, projeden çıktı
