"""DESIGNER çekirdek ajan: varsayılan gelir, frontend'den önce tasarım görevi açılır, tasarım yönetici onayı olmadan geçmez, frontend onaylı tasarıma uyar."""
import os

from server import sprint_flow as SPF
from server.config import DEFAULT_AGENTS
from server.pipeline import should_wait
from server.runs import PipelineRun, StepRecord
from server.steps.tasks import TaskHandler, normalize_backlog


def test_designer_cekirdek_ajan_olarak_varsayilan_gelir():
    ids = [a["id"] for a in DEFAULT_AGENTS]
    assert "DESIGNER" in ids and ids.index("DESIGNER") == ids.index("FRONTEND_DEV") + 1


def test_backlog_designer_rolunu_ve_design_is_turunu_tanir():
    t = normalize_backlog([{"id": "T-1", "title": "Tasarım sistemi", "role": "ui_designer", "work_type": "design"},
                           {"id": "T-2", "title": "Giriş ekranı", "role": "FRONTEND_DEV", "depends_on": ["T-1"]}])
    assert t[0]["role"] == "DESIGNER" and t[0]["work_type"] == "DESIGN" and t[1]["depends_on"] == ["T-1"]
    assert normalize_backlog([{"title": "x", "work_type": "DESIGN"}])[0]["role"] == "DESIGNER"


async def test_arayuz_isi_varken_tasarim_gorevi_acilir_ve_frontend_ona_baglanir(hub, tmp_project):
    await hub.update_settings({"sprint": {"enabled": True}, "design_first": True})
    await hub.update_jira_issue("JIRA-30", {"order": 30, "title": "Giriş ekranı", "kind": "task", "issue_type": "TASK", "status": "BACKLOG", "assignee": "FRONTEND_DEV", "work_type": "FEATURE"})
    out = await SPF.ensure_design_task(hub)
    assert out and out["frontend_linked"] == 1
    d = hub.jira_issues[out["issue_id"]]
    assert d["assignee"] == "DESIGNER" and d["work_type"] == "DESIGN" and d["priority"] == "P0"
    assert out["issue_id"] in hub.jira_issues["JIRA-30"]["depends_on"]
    assert await SPF.ensure_design_task(hub) is None                       # ikinci kez açılmaz


async def test_tasarim_dosyasi_ya_da_ayar_kapaliysa_gorev_acilmaz(hub, tmp_project):
    await hub.update_settings({"sprint": {"enabled": True}, "design_first": True})
    await hub.update_jira_issue("JIRA-30", {"order": 30, "title": "Ekran", "kind": "task", "issue_type": "TASK", "status": "BACKLOG", "assignee": "FRONTEND_DEV", "work_type": "FEATURE"})
    os.makedirs(os.path.join(tmp_project, "docs", "design"), exist_ok=True)
    open(os.path.join(tmp_project, "docs", "design", "design-system.html"), "w", encoding="utf-8").write("<html></html>")
    from server.paths import hub_docs_path
    rel = hub_docs_path(hub, "design/design-system.html", tmp_project)
    os.makedirs(os.path.dirname(os.path.join(tmp_project, rel)), exist_ok=True)
    open(os.path.join(tmp_project, rel), "w", encoding="utf-8").write("<html></html>")
    assert await SPF.ensure_design_task(hub) is None
    await hub.update_settings({"design_first": False})
    assert await SPF.ensure_design_task(hub) is None


async def test_tasarim_adimi_otomatik_kipte_de_onay_bekler_sablon_kuru_kosuda_degil(hub, tmp_project):
    issue = {"id": "JIRA-9", "order": 9, "title": "Tasarım", "assignee": "DESIGNER", "work_type": "DESIGN", "task_key": "T-01"}
    h = TaskHandler(9, issue)
    assert h.ui_design and h.force_approval and not h.verify_after and h.next_agent_id == "FRONTEND_DEV"
    run = PipelineRun(project_id=hub.active_project_id)
    run.step_by_step = True
    await hub.update_settings({"approval_mode": "auto"})

    class R:
        status = "SUCCESS"
    run.engine = "mcp_client"
    assert should_wait(hub, run, h, R()) == "WAIT"
    run.engine = "template"
    assert should_wait(hub, run, h, R()) == "SKIP"
    normal = TaskHandler(10, {"id": "JIRA-10", "order": 10, "title": "x", "assignee": "BACKEND_DEV", "work_type": "FEATURE"})
    run.engine = "mcp_client"
    assert should_wait(hub, run, normal, R()) == "SKIP"


def test_frontend_onayli_tasarim_referansi_alir(tmp_path):
    from types import SimpleNamespace
    d = tmp_path / "docs" / "design"
    (d / "screens").mkdir(parents=True)
    (d / "design-system.html").write_text(":root{--primary:#3a48cc}", encoding="utf-8")
    (d / "screens" / "giris.html").write_text("<p>giris</p>", encoding="utf-8")
    ctx = SimpleNamespace(project_dir=str(tmp_path), r=lambda v: v.replace("<docs>", "docs"))
    h = TaskHandler(11, {"id": "JIRA-11", "order": 11, "title": "Giriş", "assignee": "FRONTEND_DEV", "work_type": "FEATURE"})
    ref = h._design_reference(ctx)
    assert "uymak ZORUNLU" in ref and "--primary:#3a48cc" in ref and "giris.html" in ref
    ctx2 = SimpleNamespace(project_dir=str(tmp_path / "yok"), r=lambda v: v.replace("<docs>", "docs"))
    assert h._design_reference(ctx2) == ""


async def test_yonetici_tasarimi_hemen_baslatir_gorev_acilir_ve_one_alinir(hub, tmp_project):
    await hub.update_settings({"sprint": {"enabled": True}, "design_first": False})
    run = PipelineRun(project_id=hub.active_project_id)
    run.mode, run.status = "sprint", "ACTIVE"
    run.steps = [StepRecord(order=10, issue_id="JIRA-10", role="BACKEND_DEV", kind="task", sprint=1, status="ACTIVE"),
                 StepRecord(order=11, issue_id="JIRA-11", role="BACKEND_DEV", kind="task", sprint=1, status="PENDING")]
    run.cursor = 0
    hub.runs[run.run_id] = run
    from server import sprint as SPR
    sp = SPR.new_sprint(hub, 1, "H")
    SPR.set_sprint_status(hub, sp, "IN_PROGRESS")
    out = await SPF.start_design_now(hub)                                  # frontend işi olmasa da, ayar kapalı olsa da yönetici başlatabilir
    d = hub.jira_issues[out["issue_id"]]
    assert d["work_type"] == "DESIGN" and d["assignee"] == "DESIGNER" and out["expedite"]["mode"] == "now"
    assert run.steps[1].issue_id == out["issue_id"]                       # geçerli adımın hemen arkasında
    again = await SPF.start_design_now(hub)                                # ikinci çağrı yeni görev açmaz
    assert again["issue_id"] == out["issue_id"]


async def test_tasarim_gibi_her_is_jira_mudahale_ve_muzakereden_ayni_kuralla_acilir(hub, tmp_project):
    await hub.update_settings({"sprint": {"enabled": True}})
    out = await SPF.create_manager_task(hub, "Giriş ekranı için mockup tasarla", None, urgent=False)       # müdahale / müzakere yolu
    i = hub.jira_issues[out["issue_id"]]
    assert i["assignee"] == "DESIGNER" and i["work_type"] == "DESIGN" and i["origin"] == "MANAGER"
    await hub.update_jira_issue("JIRA-300", {"order": 300, "title": "Kayıt ekranı çizimi", "issue_type": "TASK", "status": "BACKLOG", "assignee": "DESIGNER"})   # Jira'dan elle (kind yok)
    from server import sprint as SPR
    SPR.adopt_manual_tasks(hub)
    assert hub.jira_issues["JIRA-300"]["work_type"] == "DESIGN" and hub.jira_issues["JIRA-300"]["kind"] == "task"
    await hub.update_jira_issue("JIRA-301", {"order": 301, "title": "Docker güncelle", "issue_type": "TASK", "status": "BACKLOG", "assignee": "DEVOPS"})
    SPR.adopt_manual_tasks(hub)
    assert hub.jira_issues["JIRA-301"]["work_type"] == "DEVOPS"


async def test_frontend_tasarimdan_sonra_siralanir_tasarim_adimi_onay_kapisinda_koşuyu_tutar(hub, tmp_project):
    from server import sprint as SPR
    await hub.update_settings({"sprint": {"enabled": True}, "design_first": True})
    await hub.update_jira_issue("JIRA-30", {"order": 30, "title": "Giriş ekranı", "kind": "task", "issue_type": "TASK", "status": "BACKLOG", "assignee": "FRONTEND_DEV", "work_type": "FEATURE", "priority": "P0"})
    out = await SPF.ensure_design_task(hub)
    chosen, _ = SPR.select_items(hub, 5, 1)
    order = [c["id"] for c in chosen]
    assert order.index(out["issue_id"]) < order.index("JIRA-30")           # tasarım önce; adımı onay kapısında beklediği için frontend adımı onaydan önce çalışmaz
    # tasarım hiç seçilmediyse (ör. kapasite) frontend bağımlılığı sağlanmadığı için tek başına seçilmez
    only_fe = [c for c in SPR.select_items(hub, 1, 1)[0] if c["id"] == "JIRA-30"]
    assert only_fe == []


async def test_claude_design_baglantisi_yalnizca_claude_ai_olabilir_ve_designer_yonergesine_girer(hub, tmp_project):
    await hub.update_settings({"claude_design_url": "https://claude.ai/artifact/abc123"})
    assert hub.get_settings()["claude_design_url"] == "https://claude.ai/artifact/abc123"
    await hub.update_settings({"claude_design_url": "https://evil.example.com/x"})
    assert hub.get_settings()["claude_design_url"] == "https://claude.ai/artifact/abc123"             # geçersiz bağlantı kabul edilmez
    from types import SimpleNamespace
    ctx = SimpleNamespace(hub=hub, r=lambda v: v)
    h = TaskHandler(9, {"id": "JIRA-9", "order": 9, "title": "Tasarım", "assignee": "DESIGNER", "work_type": "DESIGN", "task_key": "T-01"})
    text = h.output_contract(ctx)
    assert "CLAUDE DESIGN KAYNAĞI: https://claude.ai/artifact/abc123" in text and "Artifact aracın yoksa" in text
    await hub.update_settings({"claude_design_url": ""})
    assert "CLAUDE DESIGN (isteğe bağlı)" in h.output_contract(ctx) and hub.get_settings()["claude_design_url"] == ""


async def test_tamamlanmis_tasarimdan_sonra_yonetici_yenileme_turu_acar_ve_notu_ajana_gider(hub, tmp_project):
    await hub.update_settings({"sprint": {"enabled": True}, "design_first": False})
    first = await SPF.ensure_design_task(hub, force=True)
    await hub.update_jira_issue(first["issue_id"], {"status": "DONE"})              # ilk tasarım turu bitti
    out = await SPF.start_design_now(hub, "Tüm ekranlar için daha profesyonel mockup ve akış istiyorum")
    d = hub.jira_issues[out["issue_id"]]
    assert out["redesign"] and out["round"] == 2 and d["work_type"] == "DESIGN" and d["redesign"] is True and d["origin"] == "MANAGER"
    assert "profesyonel mockup" in d["description"] and any("flows.md" in c for c in d["acceptance_criteria"])
    again = await SPF.start_design_now(hub, "ikinci istek")                         # açık yenileme varken yenisi açılmaz
    assert again["issue_id"] == out["issue_id"]
    from server.pipeline import make_context, handler_for
    from server.runs import PipelineRun, StepRecord
    rec = StepRecord(order=d["order"], issue_id=d["id"], role="DESIGNER", kind="task", status="PENDING")
    contract = handler_for(hub, rec).output_contract(make_context(hub, PipelineRun(project_id=hub.active_project_id), rec))
    assert "YENİLEME" in contract and "flows.md" in contract and "profesyonel mockup ve akış istiyorum" in contract
