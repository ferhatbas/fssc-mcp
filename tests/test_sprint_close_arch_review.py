"""Sıkı DoD: sprint kapanışı mimar gözden geçirmesi ister; planlanmamışsa sprint BLOCKED'a düşmez, gözden geçirme kapanıştan önce eklenir."""
from server import sprint as SP
from server import sprint_flow as SPF
from server.runs import PipelineRun


async def test_kapanista_eksik_gozden_gecirme_otomatik_planlanir(hub, tmp_project):
    await hub.update_settings({"autonomy": {"strict_dod": True}, "sprint": {"enabled": True}})
    SP.new_sprint(hub, 1, "Hedef")
    run = PipelineRun(project_id=hub.active_project_id)
    run.mode = "sprint"
    close = SPF.new_close_record(1)
    run.steps = [close]
    run.cursor = 0
    out = await SPF.run_close_step(hub, run, close)
    assert out.status == "NEXT"
    assert [s.kind for s in run.steps] == ["review", "close"] and run.current_step.kind == "review"
    assert close.status == "PENDING" and SP.get_sprint(hub, 1)["status"] != "BLOCKED"
    assert any(e["action"] == "ARCH_REVIEW_PLANNED" for e in hub.events)


async def test_gozden_gecirme_zaten_planliysa_tekrar_eklenmez(hub, tmp_project):
    await hub.update_settings({"autonomy": {"strict_dod": True}, "sprint": {"enabled": True}})
    SP.new_sprint(hub, 1, "Hedef")
    run = PipelineRun(project_id=hub.active_project_id)
    run.mode = "sprint"
    close = SPF.new_close_record(1)
    run.steps = [SPF.new_review_record(1), close]
    run.cursor = 1
    await SPF.run_close_step(hub, run, close)                 # review var (bitmemiş olsa da) → eklenmez, kapanış sürer
    assert [s.kind for s in run.steps].count("review") == 1


async def test_po_adimi_sprint_kipinde_nihai_kabul_demez(hub, tmp_project):
    from server import pipeline as P
    from server.runs import StepRecord
    from server.pipeline import handler_for
    run = PipelineRun(project_id=hub.active_project_id)
    run.mode = "sprint"
    rec = StepRecord(order=9, issue_id="JIRA-9", role="PO", kind="phase", sprint=2)
    ctx = P.make_context(hub, run, rec)
    h = handler_for(hub, rec)
    assert h.display_title(ctx) == "Sprint 2 kabulü (PO UAT)"
    text = " ".join(h.thinking_for(ctx))
    assert "Sprint 2" in text and "Nihai" not in text and "nihai" not in text
    legacy = PipelineRun(project_id=hub.active_project_id)                 # sabit 1-10 akışta adım gerçekten nihai kabuldür
    assert h.display_title(P.make_context(hub, legacy, StepRecord(order=9, issue_id="JIRA-9", role="PO", kind="phase"))) == ctx.title


# ---------------------------------------------------------------------------
# PRECONDITION_LOST ile engelli sprint: gözden geçirme koşuya eklenir, bitince sprint kapanır; runner beklemez
# ---------------------------------------------------------------------------
async def _blocked_sprint(hub):
    await hub.update_settings({"autonomy": {"strict_dod": True}, "sprint": {"enabled": True}})
    sp = SP.new_sprint(hub, 1, "Hedef")
    sp["blocked"] = {"reason": "PRECONDITION_LOST", "since": "2026-10-13T17:27:40+00:00", "previous_status": "IN_REVIEW",
                     "detail": "Sıkı DoD kapanış koşulu eksik: ARCHITECT kod ve mimari gözden geçirmesi yapılmadı"}
    sp["dod"] = {"ok": False, "missing": ["ARCHITECT kod ve mimari gözden geçirmesi yapılmadı"], "arch_review": {"done": False}}
    SP.set_sprint_status(hub, sp, "BLOCKED")
    return sp


async def test_engelli_sprint_icin_gozden_gecirme_planlanir_ve_sprint_kapanir(hub, tmp_project):
    from server import driver as DRV
    from server import quality as Q
    from server.runs import StepRecord
    sp = await _blocked_sprint(hub)
    SP.new_sprint(hub, 2, "Sonraki")                              # güncel sprint 2: eski sprint kapanırken geriye dönmemeli
    SP.ensure_state(hub)["current_sprint"] = 2
    assert DRV.claimable_work(hub)["reason"] == "BLOCKED"          # planlanmadan önce yönetici bekleniyor
    run = PipelineRun(project_id=hub.active_project_id)
    run.mode = "sprint"
    run.status = "ABANDONED"
    run.steps = [StepRecord(order=5, issue_id="JIRA-5", role="BACKEND_DEV", kind="phase", sprint=2, status="DONE"),
                 StepRecord(order=6, issue_id="JIRA-6", role="QA", kind="phase", sprint=2, status="PENDING")]
    run.cursor = 1
    hub.runs[run.run_id] = run
    res = await SPF.plan_review_for_blocked(hub, 1)
    assert res["run_id"] == run.run_id and not res["already_planned"]
    assert [s.kind for s in run.steps] == ["phase", "phase", "review"] and run.steps[2].sprint == 1 and sp["blocked"]["review_planned"]["run_id"] == run.run_id
    assert (await SPF.plan_review_for_blocked(hub, 1))["already_planned"] is True       # idempotent
    assert DRV.claimable_work(hub)["reason"] != "BLOCKED"                                # artık yönetici beklenmez
    # gözden geçirme tamamlanınca sprint kapanır
    async def create(tasks):
        pass
    await Q.expand_review_findings(hub, run, run.steps[2], {"findings": []}, create)
    assert sp["status"] == "CLOSED" and sp["blocked"] is None and sp["dod"]["ok"] and sp["dod"]["missing"] == []
    assert SP.ensure_state(hub)["current_sprint"] == 2
    assert any(e["action"] == "SPRINT_CLOSED_AFTER_REVIEW" for e in hub.events)


async def test_baska_eksik_varsa_sprint_engelli_kalir_nedeni_guncellenir(hub, tmp_project):
    from server import quality as Q
    sp = await _blocked_sprint(hub)
    sp["dod"]["missing"].append("Regresyon kümesi geçmedi: TC-1")
    sp["blocked"]["review_planned"] = {"run_id": "r"}
    sp["arch_review"] = {"done": True}
    assert await Q.settle_blocked_sprint(hub, sp) is False
    assert sp["status"] == "BLOCKED" and "Regresyon" in sp["blocked"]["detail"] and "review_planned" not in sp["blocked"]


async def test_engelli_degilse_ya_da_kosu_yoksa_hata(hub, tmp_project):
    import pytest
    SP.new_sprint(hub, 1, "Hedef")
    with pytest.raises(ValueError):
        await SPF.plan_review_for_blocked(hub, 1)                 # engelli değil
    await _blocked_sprint(hub)
    with pytest.raises(ValueError):
        await SPF.plan_review_for_blocked(hub, 1)                 # koşu yok
