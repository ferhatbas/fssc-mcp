"""Müzakere: ajanlar ÖNERİ çıkarır, nihai karar yöneticinindir; revize turları ve geçmiş; onaylanan karar resmî kayda ve uygulama işine dönüşür."""
from server import sprint as SP
from server.engine.api import LocalRunsApi

PLANS = [
    {"id": "A", "title": "Plan A: Modüler Monolit", "summary": "NestJS", "stack": ["NestJS", "PostGIS"], "pros": ["Hızlı"], "cons": ["Ölçek"], "risk": "LOW", "recommended": True},
    {"id": "B", "title": "Plan B: Mikroservis", "summary": "Kuyruk", "stack": ["Kafka"], "pros": ["Ölçek"], "cons": ["Operasyon"], "risk": "MEDIUM"},
]


async def _opened(hub, title="Mimari"):
    eng = hub.deliberation_engine
    sid = eng.open({"title": title})["session_id"]
    await eng.add_turn(sid, "ARCHITECT", "planlar", "PROPOSAL", proposals=PLANS)
    return eng, sid


async def test_ajan_konsensusu_oneridir_yonetici_onaylayana_kadar_nihai_degildir(hub):
    eng, sid = await _opened(hub)
    s = await eng.close(sid, {"chosen_plan_id": "A"})
    assert s["status"] == "AWAITING_APPROVAL" and s["chosen_plan_id"] is None and s["consensus_summary"]["decision"] == "PROPOSED_BY_CONSENSUS"
    assert eng.history == []                                                         # nihai olmayan karar geçmişe "karar" diye girmez
    assert s["approval_token"]


async def test_revize_istegi_yeni_tur_acar_ve_bekleyen_istemciye_REVISE_doner(hub):
    eng, sid = await _opened(hub)
    await eng.close(sid, {"chosen_plan_id": "A"})
    api = LocalRunsApi(hub)
    waiting = await api.wait_approval(sid, timeout_s=1)
    assert waiting["status"] == "STILL_WAITING"
    s = await eng.request_revision(sid, "Mikroservis maliyetini de değerlendirin, PostGIS yerine SQLite olmaz")
    assert s["status"] == "ACTIVE" and s["round"] == 2 and s["rounds"][-1]["feedback"].startswith("Mikroservis")
    assert s["messages"][-1]["agent_id"] == "MANAGER" and s["messages"][-1]["sentiment"] == "CRITIQUE"
    rev = await api.wait_approval(sid, timeout_s=1)
    assert rev["status"] == "REVISE" and "Mikroservis" in rev["feedback"]
    await eng.add_turn(sid, "ARCHITECT", "maliyet karşılaştırması", "PROPOSAL")
    again = await eng.close(sid, {"chosen_plan_id": "A"})
    assert again["status"] == "AWAITING_APPROVAL" and again["round"] == 2                 # aynı oturumda yeniden öneri


async def test_onay_nihai_karar_olur_resmi_kayit_ve_gecmis(hub):
    eng, sid = await _opened(hub)
    await eng.close(sid, {"chosen_plan_id": "A"})
    final = await eng.approve(sid, "B")                                                   # yönetici ajanların önerisinden farklı planı seçebilir
    cs = final["consensus_summary"]
    assert final["status"] == "CONSENSUS_REACHED" and final["chosen_plan_id"] == "B" and cs["decision"] == "APPROVED_BY_USER" and cs["decision_ref"].startswith("DEC-")
    dec = next(d for d in SP.ensure_state(hub)["decisions"] if d["id"] == cs["decision_ref"])
    assert dec["human_approved"] is True and "Kafka" in dec["text"] and dec["alternatives"] == ["Plan A: Modüler Monolit"]
    assert [h["session_id"] for h in eng.history] == [sid]
    # onaylanan karar sonradan yeniden tartışılabilir: revize geçmişten çıkarır, yeniden onaylanınca eklenir
    await eng.request_revision(sid, "Bütçe değişti, yeniden bakalım")
    assert eng.history == []
    await eng.close(sid, {"chosen_plan_id": "B"})
    await eng.approve(sid, "")
    assert len(eng.history) == 1 and eng.history[0]["round"] == 2


async def test_yeni_konu_acilinca_yarim_kalan_oturum_gecmiste_kalir(hub):
    eng, sid = await _opened(hub, "Birinci konu")
    sid2 = eng.open({"title": "İkinci konu"})["session_id"]
    rows = {r["session_id"]: r for r in eng.history_list()}
    assert rows[sid]["status"] == "SUPERSEDED" and rows[sid2]["status"] == "ACTIVE" and len(rows) == 2


async def test_onay_uygulama_isi_acar_acil_ise_calisan_sprinte_alir(hub):
    await hub.update_settings({"sprint": {"enabled": True}})
    eng, sid = await _opened(hub)
    await eng.close(sid, {"chosen_plan_id": "A"})
    out = await LocalRunsApi(hub).choose_plan(sid, "", apply="next")
    task = out["task"]
    assert task and "Kararı rol bazlı görevlere böl" in task["title"] and hub.jira_issues[task["issue_id"]]["origin"] == "MANAGER"
    assert hub.jira_issues[task["issue_id"]]["assignee"] == "ARCHITECT" and hub.jira_issues[task["issue_id"]]["work_type"] == "DECISION_PLAN"
    assert out["session"]["consensus_summary"]["implementation_task"]["key"] == task["key"]
    eng2, sid2 = await _opened(hub, "İkinci")
    await eng2.close(sid2, {"chosen_plan_id": "B"})
    assert (await LocalRunsApi(hub).choose_plan(sid2, "", apply="none"))["task"] is None


def test_uclar_onay_revize_gecmis(client, hub):
    eng = hub.deliberation_engine
    sid = eng.open({"title": "x"})["session_id"]
    r = client.post("/api/deliberation/revise", json={"session_id": sid, "feedback": ""})
    assert r.status_code == 400                                                           # geri bildirim şart
    assert client.get("/api/deliberation/history").json()["sessions"][0]["session_id"] == sid
    assert client.get(f"/api/deliberation/session/{sid}").json()["session"]["session_id"] == sid
    assert client.get("/api/deliberation/session/YOK").status_code == 404


def test_eski_otomatik_konsensus_yonetici_onayi_bekleyen_oneriye_doner(hub):
    eng = hub.deliberation_engine
    legacy = {"session_id": "DELIB-20260101000000", "title": "Eski", "spec_summary": "", "status": "CONSENSUS_REACHED", "messages": [], "chosen_plan_id": "A",
              "proposals": [{"id": "A", "title": "Plan A", "summary": "", "stack": [], "pros": [], "cons": [], "risk": "LOW", "recommended": True}],
              "consensus_summary": {"chosen_plan": "Plan A", "chosen_plan_id": "A", "decision": "APPROVED_BY_CONSENSUS", "agreed_stack": []}}
    approved = {**legacy, "session_id": "DELIB-20260102000000", "consensus_summary": {**legacy["consensus_summary"], "decision": "APPROVED_BY_USER", "approved_by": "USER"}}
    eng.restore({"active": legacy, "history": [legacy, approved]})
    cur = eng.get_latest_session()
    assert cur["status"] == "AWAITING_APPROVAL" and cur["chosen_plan_id"] is None and cur["consensus_summary"]["proposed_plan_id"] == "A"
    assert [h["session_id"] for h in eng.history] == ["DELIB-20260102000000"]                 # yalnızca insan onaylı karar nihai kalır


async def test_sablon_muzakere_yigini_onayli_teknoloji_kararlarindan_turetir(hub):
    items = [{"id": "TR-1", "category": "backend", "value": "Node.js/NestJS", "status": "ONAYLANDI"},
             {"id": "TR-2", "category": "database", "value": "PostgreSQL (+PostGIS)", "status": "ONAYLANDI"},
             {"id": "TR-3", "category": "client", "value": "Web + mobile (both)", "status": "ONAYLANDI"}]
    await hub.update_settings({"tech_requirements": {"status": "ONAYLANDI", "items": items}})
    s = await hub.deliberation_engine.run_deliberation({"title": "Etkinlik"}, None, delay_between_messages=0)
    text = " ".join(m["message"] for m in s["messages"]) + str(s["proposals"]) + str(s["consensus_summary"])
    assert "NestJS" in text and "PostgreSQL" in text and "Jest" in text
    assert "FastAPI" not in text and "Pytest" not in text and "React 18" not in text


async def test_onayli_karar_yoksa_sablon_eski_varsayilana_duser(hub):
    s = await hub.deliberation_engine.run_deliberation({"title": "X"}, None, delay_between_messages=0)
    assert "FastAPI" in s["consensus_summary"]["agreed_stack"][0]


async def test_karar_plani_gorevleri_gecerli_adimin_arkasina_yonetici_onceligiyle_girer(hub, tmp_project):
    from server import pipeline as P
    from server import sprint as SPR
    from server.runs import PipelineRun, StepRecord
    await hub.update_settings({"sprint": {"enabled": True}})
    sp = SPR.new_sprint(hub, 1, "Hedef")
    SPR.set_sprint_status(hub, sp, "IN_PROGRESS")
    run = PipelineRun(project_id=hub.active_project_id)
    run.mode, run.status = "sprint", "ACTIVE"
    plan = StepRecord(order=500, issue_id="JIRA-500", role="ARCHITECT", kind="task", sprint=1, status="ACTIVE", work_type="DECISION_PLAN")
    nxt = StepRecord(order=600, issue_id="JIRA-600", role="BACKEND_DEV", kind="task", sprint=1, status="PENDING")
    run.steps = [plan, nxt]
    run.cursor = 0
    hub.runs[run.run_id] = run
    payload = {"backlog": [{"id": "T-1", "title": "Auth API", "role": "BACKEND_DEV", "acceptance_criteria": ["giriş çalışır"]},
                           {"id": "T-2", "title": "Giriş ekranı", "role": "FRONTEND_DEV", "depends_on": ["T-1"], "acceptance_criteria": ["form görünür"]}]}
    n = await P.expand_decision_plan(hub, run, plan, payload)
    assert n == 2 and [s.role for s in run.steps[1:3]] == ["BACKEND_DEV", "FRONTEND_DEV"] and run.steps[3] is nxt              # bekleyen iş geriye kalır
    ids = [s.issue_id for s in run.steps[1:3]]
    assert all(hub.jira_issues[i]["expedite"] == "now" and hub.jira_issues[i]["sprint"] == 1 and hub.jira_issues[i]["origin"] == "DECISION" for i in ids)
    assert set(ids) <= set(SPR.get_sprint(hub, 1)["committed_issue_ids"])
    assert await P.expand_decision_plan(hub, run, plan, {"backlog": []}) == 0


async def test_sunucu_uretimli_oturumda_revize_turunu_sunucu_kendisi_uretir(hub):
    import asyncio
    eng = hub.deliberation_engine
    eng.auto_round_delay = 0
    s = await eng.run_deliberation({"title": "EventPulse", "meeting_notes": "n"}, None, delay_between_messages=0)
    sid = s["session_id"]
    assert s["auto_rounds"] is True and s["status"] == "AWAITING_APPROVAL"
    before = len(s["messages"])
    out = await eng.request_revision(sid, "mobil olmadan sadece web arayüzü; test etme imkanı ver")
    assert out["status"] == "ACTIVE" and out["round"] == 2
    for _ in range(50):
        await asyncio.sleep(0.02)
        if eng.active_session.status == "AWAITING_APPROVAL":
            break
    cur = eng.get_session_dict(sid)
    assert cur["status"] == "AWAITING_APPROVAL" and cur["approval_token"] and len(cur["messages"]) > before + 5      # yeni tur üretildi, yönetici onayına döndü
    assert all("mobil" not in str(x).lower() for p in cur["proposals"] for x in p["stack"])                          # yığından mobil çıktı
    assert any("test sunucu" in str(x).lower() for x in next(p for p in cur["proposals"] if p["id"] == "A")["stack"])
    final = await eng.approve(sid, "A")
    assert final["status"] == "CONSENSUS_REACHED"
