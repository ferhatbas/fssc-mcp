"""PI planlama raporları: veriden SVG'li tek dosyalık sayfa; veri yoksa uydurma yok."""
from server import reports as RP
from server import sprint as SP


async def _seed(hub):
    await hub.update_settings({"sprint": {"enabled": True}})
    sp = SP.new_sprint(hub, 1, "Hedef")
    sp["committed_issue_ids"] = ["JIRA-1", "JIRA-2"]
    SP.set_sprint_status(hub, sp, "CLOSED")
    sp["metrics"] = {"first_pass_rate": 0.5, "fix_rounds": 1, "uat_rejections": 0, "active_min": 30}
    for n, st in ((1, "DONE"), (2, "BACKLOG")):
        await hub.update_jira_issue(f"JIRA-{n}", {"order": n, "title": f"İş {n}", "kind": "task", "issue_type": "TASK", "status": st, "sprint": 1,
                                                  "work_type": "FEATURE", "audit_action": "TASK_CREATED" if st != "DONE" else "STATUS_DONE"})


async def test_pi_verisi_ve_html(hub, tmp_project):
    await _seed(hub)
    d = RP.pi_data(hub)
    assert d["summary"]["tasks_total"] == 2 and d["summary"]["tasks_done"] == 1 and d["summary"]["predictability"] == 50
    assert d["sprints"][0]["committed"] == 2 and d["forecast"]["remaining"] == 1 and d["flow"]
    page = RP.render_html(d)
    assert page.count("<svg") >= 5 and "Sprint burndown" in page and "Kümülatif akış" in page and "PI Planlama Raporları" in page


async def test_veri_yoksa_bos_rapor_cokmez(hub, tmp_project):
    page = RP.render_html(RP.pi_data(hub))
    assert "Veri yok" in page and "NaN" not in page


async def test_uclar_calisir(client, hub, tmp_project):
    await _seed(hub)
    assert client.get("/api/reports/pi").json()["summary"]["tasks_total"] == 2
    r = client.get("/api/reports/pi.html")
    assert r.status_code == 200 and "text/html" in r.headers["content-type"]


async def test_sprint_secimi_ayrinti_ve_gomulu_kip(hub, tmp_project):
    await _seed(hub)
    d = RP.pi_data(hub, 1)
    assert d["selected"] == 1 and d["sprint_detail"]["n"] == 1 and len(d["sprint_detail"]["items"]) == 2
    assert [o["n"] for o in d["sprint_options"]] == [1]
    page = RP.render_html(d, embed=True, theme="dark")
    assert "Sprint 1 görevleri" in page and "Yazdır / PDF" not in page and 'data-theme="dark"' in page and "· Sprint 1" in page
    assert "Sprint 1 görevleri" not in RP.render_html(RP.pi_data(hub))                      # seçim yoksa tüm proje


async def test_sprint_parametreli_uc(client, hub, tmp_project):
    await _seed(hub)
    r = client.get("/api/reports/pi.html?sprint=1&embed=1&theme=light")
    assert r.status_code == 200 and "Sprint 1 görevleri" in r.text
    assert client.get("/api/reports/pi?sprint=1").json()["sprint_detail"]["n"] == 1


async def test_rol_bazli_calisma_frontend_teslimlerini_listeler(hub, tmp_project):
    from server.runs import PipelineRun, StepRecord
    run = PipelineRun(project_id=hub.active_project_id)
    run.steps = [StepRecord(order=1, issue_id="JIRA-1", role="FRONTEND_DEV", kind="task", sprint=1, status="DONE", title="Web iskeleti", started_at="2026-10-17T15:19:00+00:00",
                            finished_at="2026-10-17T15:41:00+00:00", commit="eab6bba"),
                 StepRecord(order=2, issue_id="JIRA-2", role="BACKEND_DEV", kind="task", sprint=1, status="DONE", title="API", started_at="2026-10-17T14:00:00+00:00", finished_at="2026-10-17T14:10:00+00:00")]
    hub.runs[run.run_id] = run
    d = RP.pi_data(hub)
    assert {r["role"] for r in d["roles"]["roles"]} == {"FRONTEND_DEV", "BACKEND_DEV"} and d["roles"]["by_sprint"]["1"]["FRONTEND_DEV"] == 1
    assert d["roles"]["ui_work"][0]["commit"] == "eab6bba" and d["roles"]["ui_work"][0]["minutes"] == 22.0
    page = RP.render_html(d)
    assert "Frontend / Designer teslimleri" in page and "eab6bba" in page and "Rol bazlı çalışma" in page
