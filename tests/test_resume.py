"""Koşuyu kaldığı yerden sürdürme (G5 eki).

Kullanıcı şikâyeti: sunucu yeniden başladıktan sonra pano/Claude yeni bir koşu kurdu ve iş PM adım #1'den baştan başladı
(sprint 1 sürerken "Sprint 2" planlanıyordu). Beklenen: terk edilmiş koşu varsa o kaldığı adımdan sürer; sprint açıksa yenisi
planlanmaz; yükleme beklemiyorsa PM → ARCHITECT değerlendirmesi tekrarlanmaz; baştan başlamak ayrı ve açık bir eylemdir (force_new).
"""

import json

from server import sprint as SP
from server.runs import PipelineRun, StepRecord

NOTES = ("Kullanıcılar sisteme kayıt olup giriş yapabilmeli. Yöneticiler kayıtları listeleyip filtreleyebilmeli. "
         "Her işlem için denetim kaydı tutulmalı.")
CLIENT = {"name": "claude-code", "version": "2.1"}


def _setup(client, hub, **sprint):
    client.post("/api/settings/sprint", json={"enabled": True, "commit_approval": "auto", "auto_chain": True, "max_tasks": 3, **sprint})
    client.post("/api/settings/engine", json={"execution_engine": "mcp_client", "approval_mode": "auto", "pacing": "instant",
                                              "auto_verify": False, "auto_commit": False})
    hub.step_by_step_mode = False


def _upload(client):
    return client.post("/api/specs/upload", data={"title": "Notlar", "client_name": "Acme", "meeting_notes": NOTES}).json()


def _envelope(hub, rid):
    """"LLM" yerine: adımın şablon çıktısı (gerçek koşuda istemci üretir)."""
    from server import pipeline as P
    run = hub.runs[rid]
    record = run.current_step
    handler = P.handler_for(hub, record)
    return json.dumps(handler.template_output(P.make_context(hub, run, record)))


def _drive(client, hub, rid, until, max_calls=80):
    """İstemci rolü: `until(run)` doğru olana kadar get_next_step + şablon çıktısıyla submit."""
    for _ in range(max_calls):
        run = hub.runs[rid]
        if until(run):
            return run
        nxt = client.post(f"/api/runs/{rid}/next-step", json={"client": CLIENT}).json()
        if nxt["status"] == "RUN_COMPLETE":              # sunucu tarafı kapanış adımı get_next_step içinde koşuyu bitirebilir
            return hub.runs[rid]
        assert nxt["status"] == "STEP", nxt
        res = client.post(f"/api/runs/{rid}/steps/{nxt['order']}/result", json={"result_json": _envelope(hub, rid), "client": CLIENT}).json()
        assert res["status"] in ("NEXT", "RUN_COMPLETE"), res
    raise AssertionError("koşu beklenen duruma gelmedi")


def _restart(hub, rid):
    """Sunucu yeniden başladı: süren koşu ABANDONED yüklenir (telemetry.load_registry), bellekteki etkin koşu işareti kalmaz."""
    from server import driver as DRV
    hub.runs[rid].finish("ABANDONED", reason="server-restart")
    DRV.release_lease(hub, rid)                                             # kira bellekte tutulur: yeniden başlatmada kaybolur
    hub.active_run_id = None


def _start_run(client, hub, **sprint):
    _setup(client, hub, **sprint)
    rid = _upload(client)["intake"]["run_id"]
    assert client.post("/api/runner/claim", json={"client": CLIENT}).json()["status"] == "CLAIMED"
    return rid


def _first_task_reached(run):
    return run.current_step is not None and run.current_step.kind == "task"


def _empty_abandoned(hub, mode="sprint"):
    """Sonradan kurulmuş, hiç ilerlememiş terk edilmiş koşu (kullanıcının gördüğü 'baştan başlayan' koşu)."""
    fresh = PipelineRun(project_id=hub.active_project_id, engine="mcp_client", mode=mode,
                        steps=[StepRecord(order=1, issue_id="JIRA-1", role="PM", kind="phase", title="PM"),
                               StepRecord(order=2, issue_id="JIRA-2", role="ARCHITECT", kind="phase", title="Mimari")])
    hub.register_run(fresh)
    fresh.finish("ABANDONED", reason="server-restart")
    hub.active_run_id = None
    return fresh


# ---------------------------------------------------------------------------
# Sunucu yeniden başlayınca iş kaldığı adımdan sürer
# ---------------------------------------------------------------------------
def test_start_after_restart_resumes_the_abandoned_run_at_the_same_step(client, hub):
    rid = _start_run(client, hub)
    run = _drive(client, hub, rid, _first_task_reached)
    cursor, order, done = run.cursor, run.current_step.order, sum(1 for s in run.steps if s.status == "DONE")
    assert cursor > 3 and done >= 3                                         # PM, ARCHITECT, kickoff, plan bitti
    _restart(hub, rid)
    assert hub.active_run_for(hub.active_project_id) is None

    res = client.post("/api/runs", json={"engine": "mcp_client", "client": CLIENT})
    body = res.json()
    assert res.status_code == 200 and body["status"] == "RESUMED" and body["run"]["run_id"] == rid
    assert "canlandırıldı" in body["message"] and f"adım {done}/" in body["message"] and "kaldığı yerden" in body["message"]
    assert list(hub.runs) == [rid]                                          # yeni koşu kurulmadı
    run = hub.runs[rid]
    assert run.status == "ACTIVE" and run.cursor == cursor and hub.active_run_id == rid
    assert not [s for s in run.steps if s.status == "SKIPPED"]              # beklerken SKIPPED yapılan adımlar PENDING'e döndü
    assert sum(1 for s in run.steps if s.status == "DONE") == done          # biten adımlar korundu
    nxt = client.post(f"/api/runs/{rid}/next-step", json={"client": CLIENT}).json()
    assert nxt["status"] == "STEP" and nxt["order"] == order and nxt["agent_id"] != "PM"       # PM adım #1'den değil


def test_the_run_with_most_progress_is_resumed_and_a_fresh_empty_one_is_superseded(client, hub):
    rid = _start_run(client, hub)
    _drive(client, hub, rid, _first_task_reached)
    _restart(hub, rid)
    fresh = _empty_abandoned(hub)                                           # daha YENİ ama boş
    assert fresh.created_at > hub.runs[rid].created_at

    body = client.post("/api/runs", json={"engine": "mcp_client"}).json()
    assert body["status"] == "RESUMED" and body["run"]["run_id"] == rid
    assert hub.runs[rid].status == "ACTIVE"
    assert fresh.status == "CANCELLED" and fresh.cancel_reason == f"superseded:{rid}"        # canlanıp ikinci koşu olamaz
    nxt = client.post(f"/api/runs/{fresh.run_id}/next-step", json={"client": CLIENT}).json()
    assert nxt["status"] != "STEP" and hub.runs[fresh.run_id].status == "CANCELLED"


def test_claim_work_also_prefers_the_run_with_progress(client, hub):
    rid = _start_run(client, hub)
    _drive(client, hub, rid, _first_task_reached)
    _restart(hub, rid)
    fresh = _empty_abandoned(hub)
    claim = client.post("/api/runner/claim", json={"client": CLIENT}).json()
    assert claim["status"] == "CLAIMED" and claim["run_id"] == rid
    assert fresh.status == "CANCELLED"


def test_force_new_starts_over_and_drops_the_abandoned_run(client, hub):
    rid = _start_run(client, hub)
    _drive(client, hub, rid, _first_task_reached)
    _restart(hub, rid)
    # İlerlemiş koşuyu çöpe atan force_new onaysız reddedilir (yanlışlıkla/yapay zekâ tarafından silinmesin); yalnızca proje adı yazılarak onaylanan uçla yapılır
    refused = client.post("/api/runs", json={"engine": "mcp_client", "force_new": True})
    assert refused.status_code == 409 and refused.json()["code"] == "FORCE_NEW_NEEDS_CONFIRMATION" and hub.runs[rid].status == "ABANDONED"
    name = hub.projects[hub.active_project_id]["name"]
    body = client.post(f"/api/runs/{rid}/restart-fresh", json={"confirm_name": name}).json()
    assert body["status"] == "STARTED" and body["run"]["run_id"] != rid
    assert hub.runs[rid].status == "CANCELLED" and hub.runs[rid].cancel_reason == "restart-fresh"
    assert hub.active_run_for(hub.active_project_id).run_id == body["run"]["run_id"]


def test_resume_endpoint_revives_an_abandoned_run_and_cancel_makes_it_unrevivable(client, hub):
    rid = _start_run(client, hub)
    _drive(client, hub, rid, _first_task_reached)
    _restart(hub, rid)
    res = client.post(f"/api/runs/{rid}/resume", json={}).json()
    assert res["status"] == "RESUMED" and hub.runs[rid].status == "ACTIVE" and hub.active_run_id == rid

    _restart(hub, rid)
    cancelled = client.post(f"/api/runs/{rid}/cancel", json={}).json()
    assert cancelled["status"] == "CANCELLED" and hub.runs[rid].status == "CANCELLED"
    nxt = client.post(f"/api/runs/{rid}/next-step", json={"client": CLIENT}).json()
    assert nxt["status"] == "CANCELLED" and hub.runs[rid].status == "CANCELLED"              # get_next_step iptal edileni canlandırmaz
    claim = client.post("/api/runner/claim", json={"client": CLIENT}).json()
    assert claim.get("run_id") != rid


def test_a_delivered_step_awaiting_approval_comes_back_awaiting_approval_instead_of_being_rerun(client, hub):
    """Gerçek olay: JIRA-37 düzeltmesi teslim edildi, doğrulandı ve commit'lendi; yönetici onayı beklerken sunucu yeniden başladı.
    Eski davranış: adım SKIPPED → PENDING olup üçüncü kez yeniden üretiliyordu."""
    rid = _start_run(client, hub)
    _drive(client, hub, rid, _first_task_reached)
    client.post("/api/settings/engine", json={"approval_mode": "every_step"})            # her adım yönetici onayı bekler
    hub.step_by_step_mode = True
    run = hub.runs[rid]
    run.step_by_step = True                                                  # koşu bayrağını başlangıçta alır
    nxt = client.post(f"/api/runs/{rid}/next-step", json={"client": CLIENT}).json()
    assert nxt["status"] == "STEP"
    order, issue = nxt["order"], run.current_step.issue_id
    sub = client.post(f"/api/runs/{rid}/steps/{order}/result", json={"result_json": _envelope(hub, rid), "client": CLIENT}).json()
    assert sub["status"] == "WAITING_APPROVAL" and run.current_step.finished_at and run.current_step.status == "WAITING_APPROVAL"
    delivered_summary = run.current_step.summary

    _restart(hub, rid)                                                       # onay beklerken sunucu yeniden başladı
    hub.pending_step_approval = None                                         # bellekteki onay kartı kaybolur
    assert run.current_step.status == "SKIPPED"

    res = client.post("/api/runs", json={"engine": "mcp_client", "client": CLIENT}).json()
    assert res["status"] == "RESUMED" and res["run"]["run_id"] == rid
    run = hub.runs[rid]
    assert run.status == "WAITING_APPROVAL" and run.current_step.status == "WAITING_APPROVAL" and run.current_step.order == order
    assert run.current_step.summary == delivered_summary                    # teslim yeniden üretilmedi
    card = hub.pending_step_approval
    assert card and card["run_id"] == rid and card["order"] == order and card["issue_id"] == issue    # dashboard onay kartı geri geldi
    # pano adım inceleme penceresi her artefaktta content.length okur: dosya yolu dizesi değil {name, path, type, content} nesnesi olmalı
    assert card["artifacts"] and all(isinstance(a, dict) and {"name", "path", "type", "content"} <= set(a) and isinstance(a["content"], str)
                                     for a in card["artifacts"])
    assert any(a["content"] for a in card["artifacts"])                    # içerik diskten okunur: yönetici neyi onayladığını görür
    nxt = client.post(f"/api/runs/{rid}/next-step", json={"client": CLIENT}).json()
    assert nxt["status"] == "WAITING_APPROVAL" and nxt["approval_token"] == run.approval_token      # istemciye de "onay bekle" denir

    approved = client.post("/api/pipeline/approve-step", json={"decision": "PROCEED", "token": run.approval_token}).json()
    assert approved["status"] == "APPROVED"
    after = client.post(f"/api/runs/{rid}/next-step", json={"client": CLIENT}).json()
    assert after["status"] in ("STEP", "RUN_COMPLETE") and (after.get("order") != order)             # bir sonraki adıma geçti


def test_legacy_mode_resumes_only_when_the_requested_steps_are_covered(client, hub):
    client.post("/api/settings/engine", json={"execution_engine": "mcp_client", "approval_mode": "auto", "pacing": "instant",
                                              "auto_verify": False, "auto_commit": False})
    hub.step_by_step_mode = False                                           # sprint kipi kapalı: sabit 1-10 akışı
    first = client.post("/api/runs", json={"steps": [1, 2], "engine": "mcp_client"}).json()
    rid = first["run"]["run_id"]
    assert first["status"] == "STARTED" and hub.runs[rid].mode == "legacy"
    _drive(client, hub, rid, lambda r: r.cursor >= 1)                       # adım 1 bitti, 2 sırada
    _restart(hub, rid)

    other = client.post("/api/runs", json={"steps": [3], "engine": "mcp_client"}).json()      # farklı iş: yeni koşu
    assert other["status"] == "STARTED" and other["run"]["run_id"] != rid and hub.runs[rid].status == "ABANDONED"
    client.post(f"/api/runs/{other['run']['run_id']}/cancel", json={})

    again = client.post("/api/runs", json={"steps": [1, 2], "engine": "mcp_client"}).json()   # aynı iş: kaldığı yerden
    assert again["status"] == "RESUMED" and again["run"]["run_id"] == rid and hub.runs[rid].cursor == 1


# ---------------------------------------------------------------------------
# Sprint açıkken yenisi planlanmaz; yükleme yokken PM → ARCHITECT tekrarlanmaz
# ---------------------------------------------------------------------------
def test_run_started_after_cancel_continues_the_open_sprint_instead_of_planning_the_next(client, hub):
    rid = _start_run(client, hub)
    _drive(client, hub, rid, lambda r: any(s.kind == "task" and s.status == "DONE" for s in r.steps) and _first_task_reached(r))
    sp = SP.get_sprint(hub, 1)
    assert sp["status"] == "IN_PROGRESS" and len(sp["committed_issue_ids"]) >= 2
    delivered = [s.issue_id for s in hub.runs[rid].steps if s.kind == "task" and s.status == "DONE"]
    assert delivered
    client.post(f"/api/runs/{rid}/cancel", json={})
    assert hub.runs[rid].status == "CANCELLED"

    body = client.post("/api/runs", json={"engine": "mcp_client"}).json()
    assert body["status"] == "STARTED"
    new = hub.runs[body["run"]["run_id"]]
    kinds = [s.kind for s in new.steps]
    assert "plan" not in kinds and "rescope" not in kinds and not [s for s in new.steps if s.role in ("PM",)]       # kickoff/plan/PM yok
    tasks = [s.issue_id for s in new.steps if s.kind == "task"]
    assert tasks and not set(tasks) & set(delivered)                        # bitmiş iş tekrarlanmaz
    assert set(tasks) | set(delivered) == set(sp["committed_issue_ids"])    # kalan taahhütlü işler
    assert all(s.sprint == 1 for s in new.steps) and kinds[-1] == "close"
    assert SP.last_sprint_number(hub) == 1 and new.run_id in SP.get_sprint(hub, 1)["run_ids"]      # sprint 2 planlanmadı

    _drive(client, hub, new.run_id, lambda r: r.is_terminal)                # kalan işler, kapılar, retro: sprint kapanır
    assert SP.get_sprint(hub, 1)["status"] == "CLOSED"


def test_new_run_skips_pm_and_architect_when_work_is_planned_and_nothing_is_pending(client, hub):
    rid = _start_run(client, hub)
    _drive(client, hub, rid, lambda r: r.cursor >= 2)                       # PM + ARCHITECT bitti: iş planı var, sprint henüz yok
    assert SP.existing_stories(hub) and not SP.ensure_state(hub).get("pending_intake")
    client.post(f"/api/runs/{rid}/cancel", json={})

    body = client.post("/api/runs", json={"engine": "mcp_client"}).json()
    steps = hub.runs[body["run"]["run_id"]].steps
    assert [s.kind for s in steps] == ["meeting", "plan"] and all(s.sprint == 1 for s in steps)   # baştan değil: yalnızca sprint 1 planı


def test_fresh_project_still_starts_with_pm_and_architect(client, hub):
    _setup(client, hub)
    body = client.post("/api/runs", json={"engine": "mcp_client"}).json()
    assert body["status"] == "STARTED"
    roles = [s.role for s in hub.runs[body["run"]["run_id"]].steps]
    assert roles[:2] == ["PM", "ARCHITECT"]
