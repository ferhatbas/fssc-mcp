"""G6 — ajan yönetimi (plan §4.2): tanım modeli, iki kapsam (proje + şirket geneli), yetenek eşlemesi, profil, sağlık, dışa/içe aktarma, şablonlar.

Kabul (plan §5): UI'dan eklenen "Mobil Geliştirici" ajanı sprint planında gerçek görev alır ve teslim eder; global ajan iki projede görünür, proje farkı korunur.
"""

import json
import os
import time

import pytest

from server import agent_registry as AR
from server import pipeline as P
from server import sprint as SP
from server.steps.tasks import normalize_backlog

CLIENT = {"name": "claude-code", "version": "2.1"}
MOBILE = {"id": "MOBILE_DEV", "name": "Mobil Geliştirici", "role": "Mobile Developer", "role_base": "FRONTEND_DEV", "description": "Flutter / React Native ekranları",
          "capabilities": ["SCAFFOLD", "FEATURE", "BUG"], "focus": ["mobil", "android"], "profile": {"effort": "high", "language": "tr"},
          "prompt_addendum": "Her ekran için küçük ekran (360px) davranışını da test et."}
NOTES = ("Mobil uygulamada kullanıcı telefondan giriş yapabilmelidir. Yönetici panelinde kayıtlar listelenip filtrelenebilmelidir. "
         "Her işlem için denetim kaydı tutulmalıdır.")


# ---------------------------------------------------------------------------
# Tanım modeli
# ---------------------------------------------------------------------------
def test_definition_is_normalized_and_invalid_input_is_rejected():
    d = AR.normalize_definition({"name": " Veri Müh. ", "role_base": "backend_dev", "capabilities": "feature, test, bilinmeyen", "focus": "ETL, Rapor",
                                 "profile": {"effort": "HIGH", "max_tokens": "4000", "tools_allow": ["Read", "Read", "Grep"], "language": "EN", "model": "x"}})
    assert d["name"] == "Veri Müh." and d["role_base"] == "BACKEND_DEV"
    assert d["capabilities"] == ["FEATURE", "TEST"] and d["focus"] == ["etl", "rapor"]                    # bilinmeyen yetenek atılır, odak küçük harf
    assert d["profile"] == {"model": "x", "effort": "high", "language": "en", "max_tokens": 4000, "tools_allow": ["Read", "Grep"]}
    assert d["active"] is True and d["prompt_addendum"] == ""
    # yetenek verilmezse temel rolünkiler
    assert AR.normalize_definition({"name": "X", "role_base": "QA"})["capabilities"] == ["TEST", "E2E_SCENARIO", "BUG", "TEST_DESIGN", "SECURITY_TEST", "PERF_SMOKE"]
    for bad in ({"role_base": "PM"}, {"profile": {"effort": "turbo"}}, {"profile": {"max_tokens": "çok"}}, {"profile": {"language": "fr"}}, {"profile": "x"}):
        with pytest.raises(AR.AgentError):
            AR.normalize_definition(bad)
    assert AR.normalize_definition({"focus": ["a"]}, partial=True) == {"focus": ["a"]}                  # kısmi: yalnızca verilenler
    assert AR.clean_id(" Mobil Geliştirici-2 ") == "MOBIL_GELI_TIRICI_2" and AR.clean_id("../x") == "X"


# ---------------------------------------------------------------------------
# UI'dan ekleme ve kapsam
# ---------------------------------------------------------------------------
def test_agent_added_from_the_ui_carries_the_g6_fields(client, hub):
    res = client.post("/api/agents/add", json=MOBILE)
    assert res.status_code == 200, res.text
    agent = res.json()["agent"]
    assert agent["id"] == "MOBILE_DEV" and agent["scope"] == "project" and agent["role_base"] == "FRONTEND_DEV"
    assert agent["capabilities"] == ["SCAFFOLD", "FEATURE", "BUG"] and agent["focus"] == ["mobil", "android"] and agent["profile"]["effort"] == "high"
    listed = {a["id"]: a for a in client.get("/api/agents").json()["agents"]}
    assert listed["MOBILE_DEV"]["scope"] == "project" and listed["BACKEND_DEV"]["scope"] == "core"
    assert "FRONTEND_DEV" in client.get("/api/agents").json()["base_roles"]
    # eski biçim (yalnızca ad + rol) çalışmaya devam eder
    legacy = client.post("/api/agents/add", json={"id": "OLD_DEV", "name": "Eski", "role": "BACKEND_DEV"}).json()["agent"]
    assert legacy["role_base"] == "BACKEND_DEV" and legacy["capabilities"] and legacy["active"] is True
    # güncelleme: profil ve pasifleştirme
    upd = client.put("/api/agents/MOBILE_DEV", json={"active": False, "profile": {"effort": "low"}}).json()["agent"]
    assert upd["active"] is False and upd["profile"] == {"effort": "low"}


def test_invalid_definitions_and_core_roles_get_a_clear_400(client):
    assert client.post("/api/agents/add", json={"id": "X1", "role_base": "PM"}).status_code == 400
    assert client.post("/api/agents/add", json={"id": "X2", "profile": {"effort": "turbo"}}).status_code == 400
    assert client.post("/api/agents/global", json={"id": "QA", "name": "Kendi QA"}).status_code == 400            # çekirdek rol globale taşınmaz
    assert client.post("/api/agents/global", json={"name": ""}).status_code == 400
    assert client.post("/api/agents/QA/promote-definition").status_code == 400
    assert client.post("/api/agents/NOPE/promote-definition").status_code == 404
    assert client.delete("/api/agents/global/NOPE").status_code == 404


# ---------------------------------------------------------------------------
# Yetenek eşlemesi: backlog normalizasyonu
# ---------------------------------------------------------------------------
def test_backlog_roles_follow_agent_capabilities_not_a_fixed_list():
    roles = {"MOBILE_DEV": {"role_base": "FRONTEND_DEV", "capabilities": ["FEATURE", "SCAFFOLD"], "focus": ["mobil", "android"], "name": "M", "description": ""}}
    raw = [
        {"title": "Giriş ekranı", "role": "MOBILE_DEV", "work_type": "FEATURE"},                                  # kimlik tam eşleşir
        {"title": "Android bildirimleri", "role": "UNKNOWN_ROLE", "work_type": "FEATURE"},                         # bilinmeyen rol + odak sözcüğü
        {"title": "Kayıt listesi", "role": "UNKNOWN_ROLE", "work_type": "FEATURE"},                               # odak yok: varsayılan
        {"title": "Mobil kılavuz", "role": "DOCUMENTOR"},                                                         # açık çekirdek rol kazanır
        {"title": "Mobil test", "work_type": "TEST"},                                                             # TEST yeteneği yok
    ]
    got = {t["title"]: t["role"] for t in normalize_backlog(raw, custom_roles=roles)}
    assert got == {"Giriş ekranı": "MOBILE_DEV", "Android bildirimleri": "MOBILE_DEV", "Kayıt listesi": "BACKEND_DEV", "Mobil kılavuz": "DOCUMENTOR", "Mobil test": "QA"}
    # özel ajan yokken eski davranış: MOBILE_DEV takma adı FRONTEND_DEV olur
    assert normalize_backlog([{"title": "x", "role": "MOBILE_DEV"}])[0]["role"] == "FRONTEND_DEV"
    # takma ad, özel ajan kimliğiyle çakışırsa ajan kazanır; rolsüz özel ajan görevinin iş türü yeteneğinden gelir
    assert normalize_backlog([{"title": "x", "role": "MOBILE_DEV"}], custom_roles=roles)[0]["work_type"] == "FEATURE"


def test_inactive_agents_do_not_receive_tasks(client, hub):
    client.post("/api/agents/add", json=MOBILE)
    assert "MOBILE_DEV" in AR.routing_roles(hub) and "MOBILE_DEV" in AR.task_role_ids(hub)
    client.put("/api/agents/MOBILE_DEV", json={"active": False})
    assert "MOBILE_DEV" not in AR.routing_roles(hub) and "MOBILE_DEV" not in AR.task_role_ids(hub)
    assert P.backlog_for(hub, [{"title": "Mobil giriş", "role": "MOBILE_DEV"}], 5)[0]["role"] == "FRONTEND_DEV"


def test_architect_prompt_lists_the_custom_agents(client, hub):
    from server.config import OPTIONAL_AGENTS
    assert all(f"`{a['id']}`" in AR.roles_prompt_section(hub) for a in OPTIONAL_AGENTS)          # yalnızca varsayılan uzmanlar listelenir
    client.post("/api/agents/add", json=MOBILE)
    text = AR.roles_prompt_section(hub)
    assert "`MOBILE_DEV`" in text and "FEATURE" in text and "mobil, android" in text and "FRONTEND_DEV" in text


# ---------------------------------------------------------------------------
# Kabul: özel ajan sprint planında görev alır ve teslim eder
# ---------------------------------------------------------------------------
def _sprint_setup(client, hub, engine="template"):
    client.post("/api/settings/sprint", json={"enabled": True, "commit_approval": "auto", "auto_chain": True, "max_tasks": 50})
    client.post("/api/settings/engine", json={"execution_engine": engine, "approval_mode": "auto", "pacing": "instant", "auto_verify": False, "auto_commit": False})
    hub.step_by_step_mode = False


def _wait_run(client, rid, timeout=150.0):
    end = time.time() + timeout
    while time.time() < end:
        run = client.get(f"/api/runs/{rid}").json()["run"]
        if run["is_terminal"]:
            return run
        time.sleep(0.2)
    raise AssertionError("zaman aşımı")


def test_ui_added_agent_takes_a_sprint_task_and_delivers_it_with_the_template_engine(client, hub):
    client.post("/api/agents/add", json=MOBILE)
    _sprint_setup(client, hub)
    rid = client.post("/api/specs/upload", data={"title": "Notlar", "client_name": "Acme", "meeting_notes": NOTES}).json()["intake"]["run_id"]
    done = _wait_run(client, rid)
    assert done["status"] == "COMPLETED", done["status"]
    mobile_tasks = [i for i in hub.jira_issues.values() if i.get("kind") == "task" and i.get("assignee") == "MOBILE_DEV"]
    assert len(mobile_tasks) == 1 and mobile_tasks[0]["work_type"] == "FEATURE" and mobile_tasks[0]["status"] == "DONE"
    steps = [s for s in done["steps"] if s["role"] == "MOBILE_DEV"]
    assert steps and all(s["status"] == "DONE" for s in steps)                                              # gerçekten adım aldı ve teslim etti
    others = [i["assignee"] for i in hub.jira_issues.values() if i.get("kind") == "task" and i.get("work_type") == "FEATURE" and i.get("assignee") != "MOBILE_DEV"]
    assert others and set(others) <= {"BACKEND_DEV", "FRONTEND_DEV"}                                      # odağı olmayan hikâyeler çekirdek rollerde kalır
    health = client.get("/api/agents/MOBILE_DEV/health").json()["health"]
    assert health["delivered"] >= 1 and health["first_pass_rate"] == 1.0 and health["failed_steps"] == 0 and health["scope"] == "project"


def test_llm_engine_step_for_a_custom_agent_carries_its_prompt_profile_and_addendum(client, hub):
    client.post("/api/agents/add", json=MOBILE)
    _sprint_setup(client, hub, engine="mcp_client")
    rid = client.post("/api/specs/upload", data={"title": "Notlar", "client_name": "Acme", "meeting_notes": NOTES}).json()["intake"]["run_id"]
    assert client.post("/api/runner/claim", json={"client": CLIENT}).json()["status"] == "CLAIMED"
    seen = None
    for _ in range(120):
        run = hub.runs[rid]
        nxt = client.post(f"/api/runs/{rid}/next-step", json={"client": CLIENT}).json()
        if nxt["status"] == "SESSION_BOUNDARY":                      # oturum sınırı: yeni oturum gibi yeniden sahiplen
            client.post("/api/runner/claim", json={"client": CLIENT})
            continue
        if nxt["status"] != "STEP":
            break
        record = run.current_step
        if record.role == "MOBILE_DEV" and record.kind == "task":
            seen = nxt
            break
        env = P.handler_for(hub, record).template_output(P.make_context(hub, run, record))
        res = client.post(f"/api/runs/{rid}/steps/{nxt['order']}/result", json={"result_json": json.dumps(env), "client": CLIENT}).json()
        assert res["status"] in ("NEXT", "RUN_COMPLETE", "SESSION_BOUNDARY"), res
        if res["status"] == "SESSION_BOUNDARY":
            client.post("/api/runner/claim", json={"client": CLIENT})
    assert seen is not None, "özel ajanın görev adımına gelinemedi"
    assert seen["agent_id"] == "MOBILE_DEV" and seen["agent_name"] == "Mobil Geliştirici"
    assert seen["agent_profile"] == {"effort": "high", "language": "tr"}
    assert "Bu ajana özel ek yönerge (MOBILE_DEV)" in seen["system_prompt"] and "360px" in seen["system_prompt"]
    assert "Rolün: MOBILE_DEV" in seen["user_context"] and "Flutter" in seen["user_context"]              # ipucu ajanın açıklamasından + temel rolden
    info = client.get("/api/agents/MOBILE_DEV/prompt").json()["prompt_info"]
    assert info["parent_standard"] == "developer.md"                                                      # istem şablonu temel rolünkidir
    env = P.handler_for(hub, hub.runs[rid].current_step).template_output(P.make_context(hub, hub.runs[rid], hub.runs[rid].current_step))
    res = client.post(f"/api/runs/{rid}/steps/{seen['order']}/result", json={"result_json": json.dumps(env), "client": CLIENT}).json()
    assert res["status"] in ("NEXT", "RUN_COMPLETE", "SESSION_BOUNDARY")
    assert hub.jira_issues[seen["issue_id"]]["status"] == "DONE" and hub.jira_issues[seen["issue_id"]]["assignee"] == "MOBILE_DEV"


# ---------------------------------------------------------------------------
# İki kapsam: şirket geneli ajan iki projede görünür, proje farkı korunur
# ---------------------------------------------------------------------------
async def _second_project(hub, tmp_path):
    path = tmp_path / "second_project"
    path.mkdir()
    proj = hub.register_project(str(path), "ikinci")
    return proj["id"]


async def test_global_agent_is_visible_in_two_projects_and_project_differences_are_kept(client, hub, tmp_path, isolated_agent_registry):
    first = hub.active_project_id
    res = client.post("/api/agents/global", json={**MOBILE, "id": "MOBILE_DEV", "auto_assign": True})
    assert res.status_code == 200, res.text
    assert res.json()["agent"]["scope"] == "global" and "MOBILE_DEV" in res.json()["global_ids"]
    assert isolated_agent_registry.exists() and json.loads(isolated_agent_registry.read_text(encoding="utf-8"))["agents"]["MOBILE_DEV"]["role_base"] == "FRONTEND_DEV"

    # birinci projede fark: bu projede yalnızca iOS odaklı
    upd = client.put("/api/agents/MOBILE_DEV", json={"focus": ["ios"], "profile": {"effort": "low"}}).json()["agent"]
    assert upd["focus"] == ["ios"] and upd["profile"] == {"effort": "low", "language": "tr"} and set(upd["overrides"]) == {"focus", "profile"}

    second = await _second_project(hub, tmp_path)
    await hub.switch_project(second)
    other = {a["id"]: a for a in client.get("/api/agents").json()["agents"]}["MOBILE_DEV"]
    assert other["scope"] == "global" and other["focus"] == ["mobil", "android"] and other["profile"]["effort"] == "high"      # ikinci projede görünür, fark yok
    assert client.get("/api/agents/global").json()["agents"][0]["id"] == "MOBILE_DEV"

    # globalde değişiklik: farkı olmayan alanlar her yerde güncellenir
    client.post("/api/agents/global", json={**MOBILE, "id": "MOBILE_DEV", "description": "Güncellendi", "capabilities": ["FEATURE"]})
    assert {a["id"]: a for a in client.get("/api/agents").json()["agents"]}["MOBILE_DEV"]["description"] == "Güncellendi"
    await hub.switch_project(first)
    back = {a["id"]: a for a in client.get("/api/agents").json()["agents"]}["MOBILE_DEV"]
    assert back["description"] == "Güncellendi" and back["capabilities"] == ["FEATURE"]                    # globalden geldi
    assert back["focus"] == ["ios"] and back["profile"]["effort"] == "low"                                # proje farkı korundu

    # farkı geri al
    reset = client.put("/api/agents/MOBILE_DEV", json={"reset_overrides": ["focus", "profile"]}).json()["agent"]
    assert reset["focus"] == ["mobil", "android"] and reset["profile"]["effort"] == "high" and reset["overrides"] == {}


async def test_deleting_a_global_agent_keeps_project_copies_and_project_delete_only_deactivates(client, hub, tmp_path):
    client.post("/api/agents/global", json={**MOBILE, "id": "MOBILE_DEV", "auto_assign": True})
    assert client.delete("/api/agents/MOBILE_DEV").status_code == 200                                      # projeden "sil": yalnızca pasifleşir
    agent = hub.agents["MOBILE_DEV"]
    assert agent["active"] is False and agent["inherits"] == "MOBILE_DEV" and "MOBILE_DEV" not in AR.routing_roles(hub)
    hub._sync_global_agents()
    assert hub.agents["MOBILE_DEV"]["active"] is False                                                     # eşitleme farkı ezmez
    assert client.delete("/api/agents/global/MOBILE_DEV").status_code == 200
    kept = hub.agents["MOBILE_DEV"]
    assert "inherits" not in kept and AR.scope_of(kept) == "project" and AR.load_global() == {}            # kayıp yok: proje sahipliğine geçti


async def test_project_agent_can_be_promoted_to_a_company_definition(client, hub, tmp_path):
    client.post("/api/agents/add", json=MOBILE)
    assert AR.load_global() == {}
    res = client.post("/api/agents/MOBILE_DEV/promote-definition")
    assert res.status_code == 200 and res.json()["agent"]["scope"] == "global"
    assert AR.load_global()["MOBILE_DEV"]["focus"] == ["mobil", "android"]
    second = await _second_project(hub, tmp_path)
    await hub.switch_project(second)
    assert "MOBILE_DEV" not in hub.agents                                                                  # havuza terfi: diğer projeye kendiliğinden eklenmez
    client.post("/api/agents/pool/MOBILE_DEV/add", json={"mode": "linked"})
    assert "MOBILE_DEV" in hub.agents and AR.scope_of(hub.agents["MOBILE_DEV"]) == "global"


# ---------------------------------------------------------------------------
# Dışa / içe aktarma ve şablon kütüphanesi
# ---------------------------------------------------------------------------
def test_agent_package_round_trip_and_replace_rules(client, hub):
    client.post("/api/agents/add", json=MOBILE)
    pkg = client.get("/api/agents/MOBILE_DEV/export").json()["package"]
    assert pkg["format"] == AR.PACKAGE_FORMAT and pkg["definition"]["id"] == "MOBILE_DEV" and pkg["definition"]["focus"] == ["mobil", "android"]
    assert "status" not in pkg["definition"] and "tokens_in" not in pkg["definition"]                      # çalışma zamanı alanları pakette yok
    assert pkg["prompt_md"].strip()                                                                        # güncel istem de pakette
    assert client.post("/api/agents/import", json={"package": pkg}).status_code == 409                    # aynı kimlik: replace gerekir
    pkg["definition"]["id"] = "MOBILE_DEV_2"
    pkg["definition"]["name"] = "Mobil 2"
    pkg["prompt_md"] = "# Özel istem\nMobil 2 kuralları"
    res = client.post("/api/agents/import", json={"package": pkg, "scope": "project"})
    assert res.status_code == 200, res.text
    imported = res.json()["agent"]
    assert imported["id"] == "MOBILE_DEV_2" and imported["name"] == "Mobil 2" and imported["role_base"] == "FRONTEND_DEV" and imported["scope"] == "project"
    assert "Mobil 2 kuralları" in client.get("/api/agents/MOBILE_DEV_2/prompt").json()["prompt_info"]["active_content"]
    replaced = client.post("/api/agents/import", json={"package": {**pkg, "definition": {**pkg["definition"], "name": "Yeniden"}}, "replace": True}).json()["agent"]
    assert replaced["name"] == "Yeniden"
    for bad in ({"package": {"format": "x"}}, {"package": {"format": AR.PACKAGE_FORMAT, "definition": {"id": "QA"}}}, {"package": "metin"}, {}):
        assert client.post("/api/agents/import", json=bad).status_code == 400
    gl = client.post("/api/agents/import", json={"package": {**pkg, "definition": {**pkg["definition"], "id": "MOBILE_DEV_3"}}, "scope": "global"}).json()["agent"]
    assert gl["scope"] == "global" and "MOBILE_DEV_3" in AR.load_global()


def test_template_library_adds_whole_teams_and_skips_existing(client, hub):
    keys = {t["key"] for t in client.get("/api/agent-templates").json()["templates"]}
    assert {"mobile-team", "data-team"} <= keys
    client.post("/api/agents/add", json={"id": "MOBILE_DEV", "name": "Zaten var", "role_base": "FRONTEND_DEV"})
    res = client.post("/api/agent-templates/mobile-team/apply", json={}).json()
    assert res["added"] == ["MOBILE_QA"] and res["skipped"] == ["MOBILE_DEV"]
    assert hub.agents["MOBILE_QA"]["role_base"] == "QA" and "E2E_SCENARIO" in hub.agents["MOBILE_QA"]["capabilities"]
    assert client.get("/api/agents/MOBILE_QA/prompt").json()["prompt_info"]["parent_standard"] == "qa.md"      # istem şablonu temel rolden (QA) gelir
    res2 = client.post("/api/agent-templates/data-team/apply", json={"scope": "global"}).json()
    assert sorted(res2["added"]) == ["DATA_ENGINEER", "SECURITY_ANALYST"] and set(AR.load_global()) == {"DATA_ENGINEER", "SECURITY_ANALYST"}
    assert hub.agents["SECURITY_ANALYST"]["evaluates"] == ["BACKEND_DEV", "FRONTEND_DEV"]
    assert client.post("/api/agent-templates/yok/apply", json={}).status_code == 404
    with pytest.raises(AR.AgentError):
        AR.template_definitions("../mobile-team")                                       # anahtar dosya yoluna kaçamaz (ad süzülür)
    assert AR.template_definitions("mobile-team")[0]["id"] == "MOBILE_DEV"


# ---------------------------------------------------------------------------
# Çekirdek ajanlar ve geriye uyum
# ---------------------------------------------------------------------------
def test_core_agents_keep_working_and_cannot_be_deactivated_into_routing(client, hub):
    from server.config import OPTIONAL_AGENTS
    optional = {a["id"] for a in OPTIONAL_AGENTS}                                              # varsayılan isteğe bağlı çekirdek ajanlar
    assert set(AR.routing_roles(hub)) == optional and AR.task_role_ids(hub) == set(AR.BASE_ROLES) | optional
    qa = hub.agents["QA"]
    assert AR.scope_of(qa) == "core" and AR.capabilities_of(qa) == ["TEST", "E2E_SCENARIO", "BUG", "TEST_DESIGN", "SECURITY_TEST", "PERF_SMOKE"] and AR.base_role_of(qa) == "QA"
    out = client.put("/api/agents/QA", json={"description": "Yeni açıklama"}).json()["agent"]
    assert out["description"] == "Yeni açıklama" and out["scope"] == "core"
    assert client.delete("/api/agents/QA").status_code == 200 and hub.agents["QA"]["role"] == "QA"        # çekirdek ajan silinmez, varsayılana döner
    h = client.get("/api/agents/QA/health").json()["health"]
    assert h["agent_id"] == "QA" and h["delivered"] == 0 and h["first_pass_rate"] is None
