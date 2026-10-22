"""Takım/departman modeli ve /api/teams uçları (Petek topolojisi)."""

from server.teams import DEPARTMENTS, default_team, normalize_team


def test_default_team_assigns_all_agents(hub):
    team = default_team("p", "Proje", hub.agents)
    assigned = [a for d in team["departments"] for a in d["agent_ids"]]
    assert sorted(assigned) == sorted(hub.agents.keys())
    by_id = {d["id"]: d["agent_ids"] for d in team["departments"]}
    assert by_id["ANALIZ"] == ["PM", "PO", "ARCHITECT"]
    assert by_id["TEST"] == ["QA", "E2E_TESTER"]


def test_normalize_team_drops_unknown_and_fills_leftovers(hub):
    custom = {"departments": [{"id": "test", "agent_ids": ["qa", "NOPE"]}, {"id": "BOGUS", "agent_ids": ["PM"]}]}
    team = normalize_team(custom, hub.agents)
    by_id = {d["id"]: d["agent_ids"] for d in team["departments"]}
    assert by_id["TEST"] == ["QA"]
    assert "BOGUS" not in by_id
    assert "PM" in by_id["YAZILIM"] and "E2E_TESTER" in by_id["YAZILIM"]  # atanmamışlar YAZILIM'a
    assert {d["id"] for d in team["departments"]} == {d["id"] for d in DEPARTMENTS}


def test_teams_endpoints_roundtrip(client, hub):
    res = client.get("/api/teams?include_partners=1")
    assert res.status_code == 200
    body = res.json()
    assert body["teams"][0]["project_id"] == hub.active_project_id
    assert body["departments"][0]["id"] == "ANALIZ"

    res = client.post("/api/teams", json={"name": "Özel Ekip", "departments": [{"id": "ANALIZ", "agent_ids": ["PM"]}]})
    assert res.status_code == 200
    saved = res.json()["team"]
    assert saved["name"] == "Özel Ekip"
    assert hub.get_settings()["teams"][0]["name"] == "Özel Ekip"

    again = client.get("/api/teams?include_partners=0").json()["teams"]
    assert len(again) == 1 and again[0]["name"] == "Özel Ekip"
    by_id = {d["id"]: d["agent_ids"] for d in again[0]["departments"]}
    assert by_id["ANALIZ"] == ["PM"] and "ARCHITECT" in by_id["YAZILIM"]
