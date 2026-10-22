"""Ekip performansı: test işleri sprint kapasitesini yemez, kanıtsız kriterler gruplanır, kopya maddeler birleşir."""
from server import quality as Q
from server import sprint as SP
from server.runs import PipelineRun, StepRecord
from server.steps.base import StepEvent, StepResult


def _issue(hub, iid, order, title, work_type="FEATURE", origin=None, ac=None, status="BACKLOG", issue_type="TASK"):
    hub.jira_issues[iid] = {"id": iid, "key": f"DEV-{order}", "order": order, "title": title, "description": "", "issue_type": issue_type,
                            "kind": "task", "status": status, "priority": "P1", "assignee": "QA" if "TEST" in work_type else "BACKEND_DEV",
                            "acceptance_criteria": [], "attachments": [], "audit_trail": [], "created_at": "", "updated_at": "",
                            "work_type": work_type, "origin": origin or "", "ac_refs": list(ac or [])}


def test_test_isleri_kapasitenin_yarisini_asmaz(hub):
    for k in range(6):
        _issue(hub, f"T{k}", k + 1, f"AC-{k} için test yaz", work_type="TEST", origin="UAT", ac=[f"AC-{k}"])
    for k in range(6):
        _issue(hub, f"F{k}", 20 + k, f"Özellik {k}", work_type="FEATURE")
    chosen, out = SP.select_items(hub, 6, 1)
    assert len(chosen) == 6
    assert sum(1 for c in chosen if SP.is_test_work(c)) == 3 and sum(1 for c in chosen if c["work_type"] == "FEATURE") == 3
    assert {o["reason"] for o in out} == {"KAPASİTE"}


def test_ozellik_kalmadiysa_bos_yer_testle_dolar(hub):
    for k in range(5):
        _issue(hub, f"T{k}", k + 1, f"AC-{k} için test yaz", work_type="TEST", origin="UAT", ac=[f"AC-{k}"])
    chosen, _ = SP.select_items(hub, 4, 1)
    assert len(chosen) == 4                                   # sprint boş kalmaz


async def test_test_payi_ayari(hub):
    await hub.update_settings({"sprint": {"enabled": True, "test_share_pct": 25}})
    for k in range(4):
        _issue(hub, f"T{k}", k + 1, f"AC-{k} için test yaz", work_type="TEST", origin="UAT", ac=[f"AC-{k}"])
        _issue(hub, f"F{k}", 20 + k, f"Özellik {k}", work_type="FEATURE")
    chosen, _ = SP.select_items(hub, 4, 1)
    assert sum(1 for c in chosen if SP.is_test_work(c)) == 1


def test_kopya_maddeler_birlesir_ac_farkli_olanlar_birlesmez(hub):
    _issue(hub, "A", 1, "OpenAPI giriş ucu için 400 ve 429 yanıtlarını tanımlamıyor")
    _issue(hub, "B", 2, "[QA] BUG-QA-10: OpenAPI login ucu için 400 ve 429 yanıtlarını tanımlamıyor", work_type="BUG", issue_type="BUG")
    _issue(hub, "C", 3, "OpenAPI giriş ucu için 400 ve 429 yanıtlarını tanımlamıyor")
    _issue(hub, "D", 4, "AC-28 için test/E2E senaryosu yaz", work_type="TEST", ac=["AC-28"])
    _issue(hub, "E", 5, "AC-32 için test/E2E senaryosu yaz", work_type="TEST", ac=["AC-32"])
    assert SP.merge_duplicates(hub, apply=False) and not hub.jira_issues["B"].get("deleted")        # kuru rapor değiştirmez
    out = SP.merge_duplicates(hub)
    assert {o["duplicate"] for o in out} == {"DEV-2", "DEV-3"}
    assert hub.jira_issues["B"]["deleted"] and hub.jira_issues["B"]["duplicate_of"] == "A" and hub.jira_issues["C"]["deleted"]
    assert not hub.jira_issues["A"].get("deleted") and hub.jira_issues["A"]["merged_from"] == ["DEV-2", "DEV-3"]
    assert not hub.jira_issues["D"].get("deleted") and not hub.jira_issues["E"].get("deleted")      # farklı AC'ler kopya sayılmaz
    assert SP.merge_duplicates(hub) == []                                                            # ikinci çalıştırma değişiklik yapmaz


async def test_kanitsiz_kriterler_gruplanir(hub, tmp_project):
    await hub.update_settings({"autonomy": {"strict_dod": True}, "sprint": {"enabled": True, "ac_test_batch": 3}})
    st = SP.ensure_state(hub)
    required = [f"AC-{k}" for k in range(1, 8)]
    ids = []
    for n, ac in enumerate(required, 31):
        await hub.update_jira_issue(f"JIRA-{n}", {"order": n, "title": f"İş {ac}", "kind": "task", "status": "DONE", "assignee": "BACKEND_DEV", "ac_refs": [ac], "closed_in_sprint": 1})
        st["acs"][ac] = {"text": ac, "story": None}
        ids.append(f"JIRA-{n}")
    sp = SP.new_sprint(hub, 1, "Hedef")
    sp["committed_issue_ids"] = ids
    run = PipelineRun(project_id=hub.active_project_id)
    rec = StepRecord(order=9, issue_id="JIRA-9", role="PO", kind="phase", sprint=1)
    result = StepResult(summary="PO", action="UAT_APPROVED", next_agent_id="DOCUMENTOR", events=[StepEvent(from_agent="PO", to_agent="DOCUMENTOR", action="UAT_APPROVED")])
    created = []

    async def create(tasks):
        created.extend(tasks)
    payload = {"criteria": [{"id": ac, "decision": "ACCEPTED", "reason": "x"} for ac in required]}
    await Q.apply_po_criteria(hub, run, rec, payload, result, tmp_project, create)
    tests = [t for t in created if t["work_type"] == "TEST"]
    assert [t["ac_refs"] for t in tests] == [["AC-1", "AC-2", "AC-3"], ["AC-4", "AC-5", "AC-6"], ["AC-7"]]       # 7 kriter → 3 görev (7 yerine)
    assert tests[0]["title"] == "AC-1, AC-2, AC-3 için test/E2E senaryolarını yaz" and tests[2]["title"] == "AC-7 için test/E2E senaryosu yaz"
    assert len(tests[0]["acceptance_criteria"]) == 3 and all(t["role"] == "QA" for t in tests)


async def test_panodan_eklenen_is_sprint_adayi_olur(hub):
    await hub.update_settings({"sprint": {"enabled": True}})
    issue = await hub.add_jira_issue({"title": "Swagger tarzı bir işlem ekleyelim", "issue_type": "TASK", "description": "TASK: Swagger tarzı bir işlem ekleyelim"})
    assert issue["kind"] == "task" and issue["origin"] == "MANAGER" and issue["work_type"] == "FEATURE"
    chosen, _ = SP.select_items(hub, 5, 1)
    assert issue["id"] in [c["id"] for c in chosen]                      # eskiden kind yoktu: hiç aday olmazdı


def test_eski_elle_girilen_is_sahiplenilir_omurga_dokunulmaz(hub):
    hub.jira_issues["JIRA-4"] = {"id": "JIRA-4", "key": "DEV-4", "order": 4, "title": "Frontend iskeleti", "description": "x", "issue_type": "TASK", "status": "BACKLOG",
                                 "acceptance_criteria": ["a"], "assignee": "FRONTEND_DEV"}
    hub.jira_issues["JIRA-95"] = {"id": "JIRA-95", "key": "DEV-95", "order": 95, "title": "Swagger tarzı bir işlem ekleyelim", "description": "TASK: Swagger tarzı bir işlem ekleyelim",
                                  "issue_type": "TASK", "status": "BACKLOG", "acceptance_criteria": [], "assignee": "BACKEND_DEV"}
    assert SP.select_items(hub, 5, 1)[0] == []                          # kind yok: görünmez
    assert SP.adopt_manual_tasks(hub) == ["JIRA-95"]
    i = hub.jira_issues["JIRA-95"]
    assert i["kind"] == "task" and i["origin"] == "MANAGER" and i["needs_grooming"] and len(i["acceptance_criteria"]) == 2 and "Yönetici isteği" in i["description"]
    assert not hub.jira_issues["JIRA-4"].get("kind")                    # faz omurgası sprint görevi olmaz
    assert [c["id"] for c in SP.select_items(hub, 5, 1)[0]] == ["JIRA-95"]
    assert SP.adopt_manual_tasks(hub) == []                             # ikinci çalıştırma değişiklik yapmaz


async def test_retro_aksiyonu_anlamsiz_baslik_gerekceden_turetilir(hub):
    from server import learning as L
    created = []

    async def create(tasks):
        created.extend(tasks)
    rec = {"id": "RA-4-1", "target": "N-2", "value": "", "reason": "Yönetici swagger tarzı denenebilir bir arayüz istedi; yeni kütüphane ADR gerektirir."}
    out = await L._apply_backlog(hub, rec, create)
    assert out["status"] == "APPLIED" and created[0]["title"].startswith("Yönetici swagger tarzı denenebilir bir arayüz istedi")


async def test_cift_gonderim_ikinci_is_acmaz(hub):
    await hub.update_settings({"sprint": {"enabled": True}})
    data = {"title": "Backend projeyi docker container içine alalım", "issue_type": "TASK", "assignee": "DEVOPS"}
    first = await hub.add_jira_issue(dict(data))
    assert hub.find_recent_duplicate(dict(data))["id"] == first["id"]
    assert hub.find_recent_duplicate({**data, "assignee": "QA"}) is None                       # farklı sorumlu aynı iş değil
    assert hub.find_recent_duplicate({**data, "title": "Başka bir iş"}) is None
    first["created_at"] = "2020-01-01T00:00:00+00:00"
    assert hub.find_recent_duplicate(dict(data)) is None                                       # pencere dışı: gerçekten yeni iş olabilir


def test_ozellik_payi_refactor_ve_iyilestirme_yiginina_ezdirilmez(hub):
    for k in range(6):
        _issue(hub, f"R{k}", k + 1, f"Refactor {k}", work_type="REFACTOR", origin="ARCHITECT")
        _issue(hub, f"I{k}", 10 + k, f"İyileştirme {k}", work_type="IMPROVEMENT", origin="RETRO")
    for k in range(6):
        _issue(hub, f"F{k}", 30 + k, f"Özellik {k}", work_type="FEATURE", origin="ARCHITECT")
    chosen, _ = SP.select_items(hub, 6, 1)
    kinds = [c["work_type"] for c in chosen]
    assert len(chosen) == 6 and kinds.count("FEATURE") == 3 and kinds.count("REFACTOR") + kinds.count("IMPROVEMENT") == 3     # %50 özellik payı


def test_p0_hata_ve_yoneticinin_one_aldigi_is_kota_disidir(hub):
    for k in range(4):
        _issue(hub, f"R{k}", k + 1, f"Refactor {k}", work_type="REFACTOR")
    _issue(hub, "B0", 20, "Kritik hata", work_type="BUG", issue_type="BUG")
    hub.jira_issues["B0"]["priority"] = "P0"
    _issue(hub, "M0", 21, "Yönetici işi", work_type="IMPROVEMENT")
    hub.jira_issues["M0"]["expedite"] = "next_sprint"
    for k in range(4):
        _issue(hub, f"F{k}", 30 + k, f"Özellik {k}", work_type="FEATURE")
    chosen, _ = SP.select_items(hub, 4, 1)
    ids = [c["id"] for c in chosen]
    assert "B0" in ids and "M0" in ids                                         # P0 hata ve öne alınan iş her zaman girer
    assert sum(1 for c in chosen if c["work_type"] == "FEATURE") >= 1


def test_ozellik_kalmadiysa_kalite_isleri_bos_yeri_doldurur(hub):
    for k in range(5):
        _issue(hub, f"R{k}", k + 1, f"Refactor {k}", work_type="REFACTOR")
    assert len(SP.select_items(hub, 4, 1)[0]) == 4


async def test_toplanti_kapasitenin_yarisindan_azini_secerse_tamamlanir(hub):
    from server import sprint_flow as SPF
    await hub.update_settings({"sprint": {"enabled": True, "max_tasks": 6}})
    for k in range(6):
        _issue(hub, f"F{k}", 30 + k, f"Özellik {k}", work_type="FEATURE")
    SP.ensure_state(hub)["meeting_commitments"]["1"] = {"items": ["F0"], "out_of_scope": []}
    chosen, _ = SPF._proposal(hub, 1, 6)
    assert [c["id"] for c in chosen][0] == "F0" and len(chosen) == 6          # tek işle kalmaz: sunucu dengeli seçimle doldurur


async def test_sprint_butcesi_artinca_duran_proje_surer(hub):
    from server import sprint_flow as SPF
    await hub.update_settings({"sprint": {"enabled": True}, "autonomy": {"budget": {"max_sprints": 2}}})
    st = SP.ensure_state(hub)
    SP.new_sprint(hub, 1, "a"); SP.new_sprint(hub, 2, "b")
    st["project_status"] = "PAUSED"
    assert await SPF.resume_if_budget_allows(hub) is False and st["project_status"] == "PAUSED"      # bütçe hâlâ dolu
    await hub.update_settings({"autonomy": {"budget": {"max_sprints": 5}}})
    assert await SPF.resume_if_budget_allows(hub) is True and st["project_status"] == "ACTIVE"
    assert await SPF.resume_if_budget_allows(hub) is False                                           # ACTIVE iken dokunmaz


def test_kriter_sicili_hikayelerden_geri_kurulur_ve_metin_gelir(hub):
    hub.sprint_state = {}                                                      # durum kaybı: sicil boş
    hub.jira_issues["S1"] = {"id": "S1", "key": "DEV-31", "order": 31, "kind": "story", "issue_type": "STORY", "status": "BACKLOG", "title": "Sohbet",
                             "ac_refs": ["AC-39", "AC-40", "AC-41", "AC-42"], "acceptance_criteria": ["Yalnızca onaylılar erişir", "Hatırlatma 24 saat önce", "Arşivde salt-okunur"]}
    assert SP.ac_text(hub, "AC-42") == "Arşivde salt-okunur" and SP.ac_text(hub, "AC-40") == "Yalnızca onaylılar erişir"     # sondan hizalama
    assert SP.ac_text(hub, "AC-39") == "" and SP.ac_text(hub, "AC-99") == ""
    SP.ensure_state(hub)["acs"]["AC-42"]["text"] = "elle düzeltildi"
    SP.ensure_state(hub)                                                       # tekrar çağrı sicili ezmez
    assert SP.ac_text(hub, "AC-42") == "elle düzeltildi"


def test_gorev_isteminde_kriter_metinleri_sunucudan_gelir(hub, tmp_project):
    from server.runs import PipelineRun, StepRecord
    from server.steps.tasks import TaskHandler
    from server import pipeline as P
    hub.sprint_state = {}
    hub.jira_issues["S1"] = {"id": "S1", "key": "DEV-31", "order": 31, "kind": "story", "issue_type": "STORY", "status": "BACKLOG", "title": "Sohbet",
                             "ac_refs": ["AC-42"], "acceptance_criteria": ["Etkinlik arşivlenince sohbet salt-okunur olur."]}
    issue = {"id": "JIRA-219", "title": "AC-42 sağlanmadı", "ac_refs": ["AC-42", "AC-99"], "acceptance_criteria": ["x"], "assignee": "BACKEND_DEV", "kind": "task"}
    run = PipelineRun(project_id=hub.active_project_id)
    rec = StepRecord(order=219, issue_id="JIRA-219", role="BACKEND_DEV", kind="task")
    run.steps = [rec]
    ctx = P.make_context(hub, run, rec)
    prompt = TaskHandler(219, issue).build_user_prompt(ctx)
    assert "AC-42: Etkinlik arşivlenince sohbet salt-okunur olur." in prompt and "AC-99: (metin kayıtlı değil" in prompt


def test_ac_lookup_ve_endpoint(client, hub):
    hub.sprint_state = {}
    hub.jira_issues["S1"] = {"id": "S1", "key": "DEV-31", "order": 31, "kind": "story", "issue_type": "STORY", "status": "BACKLOG", "title": "Sohbet",
                             "ac_refs": ["AC-41", "AC-42"], "acceptance_criteria": ["Hatırlatma 24 saat önce", "Arşivde salt-okunur"]}
    rows = SP.ac_lookup(hub, ["ac-42", "AC-99"])
    assert rows[0]["text"] == "Arşivde salt-okunur" and rows[0]["story"] == "DEV-31" and rows[1]["text"] == ""
    r = client.get("/api/acceptance-criteria?ids=AC-41,AC-42").json()["criteria"]
    assert [c["text"] for c in r] == ["Hatırlatma 24 saat önce", "Arşivde salt-okunur"]


async def test_min_tasks_kapasite_tabani_ve_tamamlama(hub):
    from server import sprint_flow as SPF
    await hub.update_settings({"sprint": {"enabled": True, "max_tasks": 16, "min_tasks": 12}})
    assert SP.cfg(hub)["min_tasks"] == 12 and SP.cfg(hub)["max_tasks"] == 16
    st = SP.ensure_state(hub)
    for n in (1, 2, 3):                                                                 # hız düşük: sprintte 3 iş bitti
        sp = SP.new_sprint(hub, n, "g")
        sp["status"], sp["metrics"], sp["completed_issue_ids"] = "CLOSED", {"x": 1}, ["a", "b", "c"]
    cap, why = SP.capacity(hub)
    assert cap == 12 and "min_tasks" in why                                             # hız kapasitesi 4 olurdu: taban 12
    for k in range(20):
        _issue(hub, f"F{k}", 30 + k, f"Özellik {k}", work_type="FEATURE")
    SP.ensure_state(hub)["meeting_commitments"]["4"] = {"items": ["F0", "F1"], "out_of_scope": []}
    chosen, _ = SPF._proposal(hub, 4, cap)
    assert len(chosen) == 12 and [c["id"] for c in chosen][:2] == ["F0", "F1"]            # toplantı 2 seçti: sunucu tabana tamamlar
    await hub.update_settings({"sprint": {"max_tasks": 5, "min_tasks": 9}})
    assert SP.cfg(hub)["min_tasks"] == 5                                                # taban tavanı aşamaz


def test_hazir_frontend_isi_backend_yiginin_arkasinda_beklemez(hub):
    for k in range(6):
        _issue(hub, f"B{k}", k + 1, f"Backend {k}", work_type="FEATURE")
    for k in range(3):
        _issue(hub, f"U{k}", 40 + k, f"Arayüz {k}", work_type="REFACTOR")
        hub.jira_issues[f"U{k}"]["assignee"] = "FRONTEND_DEV"
    chosen, _ = SP.select_items(hub, 6, 1)
    assert len(chosen) == 6 and sum(1 for c in chosen if c["assignee"] == "FRONTEND_DEV") == 2         # ui_min_tasks varsayılanı 2
    hub.jira_issues["B0"]["priority"] = "P0"
    chosen, _ = SP.select_items(hub, 6, 1)
    assert "B0" in {c["id"] for c in chosen}                                                            # P0 işi yerinden edilmez


def test_frontend_isi_yoksa_taban_kapasiteyi_bozmaz(hub):
    for k in range(4):
        _issue(hub, f"B{k}", k + 1, f"Backend {k}", work_type="FEATURE")
    chosen, _ = SP.select_items(hub, 4, 1)
    assert len(chosen) == 4
