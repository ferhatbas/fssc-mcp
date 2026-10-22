"""Jira işini öne alma: "Önce yap" (çalışan sprint koşusunda geçerli adımdan hemen sonra) ve "sıradaki sprintin başı" (planlamada en üst)."""
import pytest

from server import sprint as SP
from server import sprint_flow as SPF
from server.runs import PipelineRun, StepRecord


async def _issue(hub, iid, order, **kw):
    base = {"order": order, "title": f"İş {iid}", "kind": "task", "status": "BACKLOG", "assignee": "BACKEND_DEV", "issue_type": "TASK", "priority": "P2"}
    return await hub.update_jira_issue(iid, {**base, **kw})


async def _sprint_run(hub, status="ACTIVE"):
    await hub.update_settings({"sprint": {"enabled": True, "max_tasks": 2}})
    sp = SP.new_sprint(hub, 1, "Hedef")
    sp["committed_issue_ids"] = ["JIRA-31", "JIRA-32"]
    SP.set_sprint_status(hub, sp, "IN_PROGRESS")
    run = PipelineRun(project_id=hub.active_project_id)
    run.mode, run.status = "sprint", status
    run.steps = [StepRecord(order=31, issue_id="JIRA-31", role="BACKEND_DEV", kind="task", sprint=1, status="DONE"),
                 StepRecord(order=32, issue_id="JIRA-32", role="BACKEND_DEV", kind="task", sprint=1, status="ACTIVE"),
                 StepRecord(order=6, issue_id="JIRA-6", role="QA", kind="phase", sprint=1, status="PENDING"),
                 StepRecord(order=1013, issue_id="SPRINT-1", role="SCRUM_MASTER", kind="close", sprint=1, status="PENDING")]
    run.cursor = 1
    hub.runs[run.run_id] = run
    return sp, run


async def test_once_yap_calisan_kosuda_hemen_sonraki_adim_olur(hub, tmp_project):
    sp, run = await _sprint_run(hub)
    await _issue(hub, "JIRA-90", 90, depends_on=["JIRA-77"])
    res = await SPF.expedite_issue(hub, "JIRA-90", "now")
    assert res["mode"] == "now" and res["sprint"] == 1 and res["order"] == 90 and not res["fallback"]
    assert [s.order for s in run.steps] == [31, 32, 90, 6, 1013]                   # geçerli adım (32) bitince sıradaki: 90
    assert run.steps[2].kind == "task" and run.steps[2].sprint == 1
    assert "JIRA-90" in sp["committed_issue_ids"] and sp["scope_changes"][-1]["source"] == "expedite" and sp["scope_changes"][-1]["added"] == ["JIRA-90"]
    issue = hub.jira_issues["JIRA-90"]
    assert issue["sprint"] == 1 and issue["expedite"] == "now" and issue["audit_trail"][-1]["action"] == "EXPEDITED"
    assert any("kapasitesi (2) aşıldı" in w for w in res["warnings"]) and any("JIRA-77" in w for w in res["warnings"])
    assert any(e["action"] == "SCOPE_CHANGED" and e["payload"].get("expedite") for e in hub.events)
    again = await SPF.expedite_issue(hub, "JIRA-90", "now")                         # zaten sıradaki adım: tekrar öne alma hata değil, değişiklik de yapmaz
    assert again["moved"] is False and [s.order for s in run.steps] == [31, 32, 90, 6, 1013]
    with pytest.raises(PermissionError):
        await SPF.expedite_issue(hub, "JIRA-90", "next_sprint")                    # kuyruktaki iş sıradaki sprint için işaretlenemez


async def test_terk_edilmis_sprint_kosusuna_da_eklenir(hub, tmp_project):
    sp, run = await _sprint_run(hub, status="ABANDONED")
    await _issue(hub, "JIRA-91", 91)
    assert (await SPF.expedite_issue(hub, "JIRA-91", "now"))["mode"] == "now"
    assert 91 in [s.order for s in run.steps]


async def test_kosu_yoksa_siradaki_sprintin_basina_duser(hub, tmp_project):
    await hub.update_settings({"sprint": {"enabled": True}})
    await _issue(hub, "JIRA-92", 92)
    res = await SPF.expedite_issue(hub, "JIRA-92", "now")
    assert res["mode"] == "next_sprint" and res["fallback"] is True
    assert hub.jira_issues["JIRA-92"]["expedite"] == "next_sprint" and not hub.jira_issues["JIRA-92"].get("sprint")


async def test_siradaki_sprintin_basi_planlamada_en_uste_cikar(hub, tmp_project):
    await hub.update_settings({"sprint": {"enabled": True}})
    await _issue(hub, "JIRA-40", 40, priority="P0", work_type="BUG")                # normalde P0 hata önde olurdu
    await _issue(hub, "JIRA-41", 41, planned_sprint=1)                              # sabitlenmiş iş de önde olurdu
    await _issue(hub, "JIRA-42", 42)
    await SPF.expedite_issue(hub, "JIRA-42", "next_sprint")
    chosen, _ = SP.select_items(hub, 3, 1)
    assert [i["id"] for i in chosen][:3] == ["JIRA-42", "JIRA-41", "JIRA-40"]
    await SPF.expedite_issue(hub, "JIRA-42", "")                                     # bayrak kaldırılır
    assert hub.jira_issues["JIRA-42"]["expedite"] is None
    chosen, _ = SP.select_items(hub, 3, 1)
    assert [i["id"] for i in chosen][0] == "JIRA-41"


async def test_elle_girilen_is_kind_eksikse_task_olur_ve_gecersizler_reddedilir(hub, tmp_project):
    await hub.update_jira_issue("JIRA-93", {"order": 93, "title": "Panodan girildi", "issue_type": "TASK", "status": "BACKLOG", "assignee": "BACKEND_DEV"})   # kind yok
    await SPF.expedite_issue(hub, "JIRA-93", "next_sprint")
    assert hub.jira_issues["JIRA-93"]["kind"] == "task"
    await hub.update_jira_issue("JIRA-94", {"order": 94, "title": "Epik", "issue_type": "EPIC", "status": "BACKLOG"})
    with pytest.raises(ValueError):
        await SPF.expedite_issue(hub, "JIRA-94", "now")
    with pytest.raises(ValueError):
        await SPF.expedite_issue(hub, "JIRA-93", "paralel")
    with pytest.raises(KeyError):
        await SPF.expedite_issue(hub, "JIRA-999", "now")


async def test_plan_ucu_expedite_alanini_isler(client, hub, tmp_project):
    await _issue(hub, "JIRA-95", 95)
    r = client.post("/api/jira/issues/JIRA-95/plan", json={"expedite": "next_sprint", "priority": "P0"})
    assert r.status_code == 200 and r.json()["expedite"]["mode"] == "next_sprint" and r.json()["issue"]["priority"] == "P0"
    assert client.post("/api/jira/issues/JIRA-95/plan", json={"expedite": "xyz"}).status_code == 400
    assert client.post("/api/jira/issues/JIRA-999/plan", json={"expedite": "now"}).status_code == 404


async def test_surmekte_olan_sprintin_kuyrugundaki_is_silinebilir_baslamis_silinemez(hub, tmp_project):
    from server import jira_plus as JP
    sp, run = await _sprint_run(hub)
    await _issue(hub, "JIRA-90", 90)
    await SPF.expedite_issue(hub, "JIRA-90", "now")
    await JP.delete_issue(hub, "JIRA-90", "MANAGER", "şablon içerik")
    assert 90 not in [s.order for s in run.steps] and "JIRA-90" not in sp["committed_issue_ids"]
    assert hub.jira_issues["JIRA-90"]["deleted"] and hub.jira_issues["JIRA-90"]["sprint"] is None
    assert sp["scope_changes"][-1]["source"] == "manager_delete" and sp["scope_changes"][-1]["removed"] == ["JIRA-90"]
    await _issue(hub, "JIRA-32", 32, sprint=1)
    with pytest.raises(PermissionError):
        await JP.delete_issue(hub, "JIRA-32", "MANAGER", "")                       # çalışan adım: kuyrukta değil
