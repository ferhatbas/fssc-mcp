"""F5 — Claude Desktop sürücüsü (sunucu tarafı): claim_work, kira, oturum sınırı, bütçe/takılma, display_md, etkinlik akışı.

Not: gerçek Claude Desktop zamanlanmış görevi bu testlerde YOKTUR. Runner, MCP araçlarının REST ikizleriyle (claim_work / get_next_step /
submit_step_result) ve şablon işleyicilerinin ürettiği zarflarla benzetilir; gerçek Desktop kabulü ayrıca insan tarafından doğrulanmalıdır (bkz. F5 raporu).
"""

import asyncio
import json
import time
from datetime import datetime, timedelta, timezone

import pytest

from server import display as DISP
from server import driver as DRV
from server import meetings as M
from server import pipeline as P
from server import sprint as SP
from server.runs import PipelineRun, StepRecord

NOTES = ("Kullanıcılar sisteme kayıt olup giriş yapabilmeli. Yöneticiler kayıtları listeleyip filtreleyebilmeli. "
         "Her işlem için denetim kaydı tutulmalı.")
CLIENT = {"name": "claude-desktop-runner", "version": "1"}


def _setup(client, hub, **sprint):
    client.post("/api/settings/sprint", json={"enabled": True, "commit_approval": "auto", "auto_chain": True, "max_tasks": 3, **sprint})
    client.post("/api/settings/engine", json={"execution_engine": "mcp_client", "approval_mode": "auto", "pacing": "instant", "auto_verify": False, "auto_commit": False})
    hub.step_by_step_mode = False


def _upload(client, notes=NOTES):
    return client.post("/api/specs/upload", data={"title": "Notlar", "client_name": "Acme", "meeting_notes": notes}).json()


def _envelope(hub, run_id):
    """"LLM" yerine: adımın şablon çıktısı (gerçek koşuda istemci üretir)."""
    run = hub.runs[run_id]
    record = run.current_step
    handler = P.handler_for(hub, record)
    env = handler.template_output(P.make_context(hub, run, record))
    nxt_agent = env.get("to_agent")
    if record.kind not in ("meeting",) and nxt_agent and env["payload"].get("friendly_dialogue"):
        env["payload"]["handoff"] = [{"to": nxt_agent, "message": env["payload"]["friendly_dialogue"]}]     # gerçek istemci devir notu bırakır (§10.8)
    return json.dumps(env)


def _claim(client):
    return client.post("/api/runner/claim", json={"client": CLIENT}).json()


def _session(client, hub, max_calls=200):
    """Bir runner oturumu: claim_work → (get_next_step → submit)* → sınır/durma. Döner: (claim, [yanıtlar], bitiş durumu)."""
    claim = _claim(client)
    log = []
    if claim["status"] != "CLAIMED":
        return claim, log, claim["status"]
    rid = claim["run_id"]
    for _ in range(max_calls):
        nxt = client.post(f"/api/runs/{rid}/next-step", json={"client": CLIENT}).json()
        log.append(("next", nxt))
        if nxt["status"] != "STEP":
            return claim, log, nxt["status"]
        res = client.post(f"/api/runs/{rid}/steps/{nxt['order']}/result", json={"result_json": _envelope(hub, rid), "client": CLIENT}).json()
        log.append(("submit", res))
        if res["status"] != "NEXT":
            return claim, log, res["status"]
    raise AssertionError("oturum bitmedi")


# ---------------------------------------------------------------------------
# Uçtan uca (benzetilmiş runner): insan dokunmadan iki sprint, oturum sınırları, tek çağrıyla biten boş çalıştırma
# ---------------------------------------------------------------------------
def test_runner_closes_two_sprints_across_sessions_and_idles_in_one_call(client, hub, tmp_project):
    _setup(client, hub, max_tasks=3)
    client.post("/api/settings/runner", json={"runner": {"max_steps_per_session": 100}})   # yalnızca değerlendirme sınırları işlesin
    res = _upload(client)
    assert res["intake"]["run_status"] == "STARTED"
    sessions, boundaries = 0, []
    for _ in range(40):
        claim, log, end = _session(client, hub)
        if claim["status"] != "CLAIMED":
            break
        sessions += 1
        boundaries.append(end)
        for kind, body in log:
            assert body.get("display_md"), (kind, body["status"])         # her yanıtta sunucunun hazır anlatımı var
        if end in ("RUN_COMPLETE", "BLOCKED", "WAITING_APPROVAL"):
            continue
    assert sessions >= 4 and "SESSION_BOUNDARY" in boundaries
    states = [s["status"] for s in SP.ensure_state(hub)["sprints"]]
    assert states[:2] == ["CLOSED", "CLOSED"] and len(states) >= 2          # insan dokunmadan sprintler kapandı
    assert SP.ensure_state(hub)["project_status"] in ("DONE", "PAUSED")
    # iş yokken çalıştırma tek çağrıyla biter
    calls_before = hub.runner["claims"]
    idle = _claim(client)
    assert idle["status"] == "IDLE" and idle["reason"] in ("PROJECT_DONE", "PROJECT_PAUSED", "NO_WORK") and hub.runner["claims"] == calls_before + 1
    assert "suggestion" in idle or "message" in idle


def test_display_md_has_step_header_incoming_message_and_spend(client, hub):
    _setup(client, hub, max_tasks=3)
    _upload(client)
    seen = {"start": [], "end": []}
    for _ in range(12):
        claim, log, end = _session(client, hub)
        if claim["status"] != "CLAIMED":
            break
        for kind, body in log:
            if kind == "next" and body["status"] == "STEP":
                seen["start"].append(body["display_md"])
            if kind == "submit":
                seen["end"].append(body["display_md"])
    assert any(t.startswith("▶ Sprint 1 · adım") and "BACKEND_DEV" in t for t in seen["start"])
    assert any("Gelen mesaj —" in t for t in seen["start"])                    # devir notu alıcıya ve oturuma görünür
    assert any("✔ " in t and "teslim etti" in t for t in seen["end"])
    assert any("Harcama: sprint" in t and "dk /" in t and "token" in t for t in seen["end"])
    assert any("Giden mesaj —" in t for t in seen["end"]) and any("Sıradaki:" in t for t in seen["end"])
    assert any(t.startswith("🗣 Toplantı M-") for t in seen["end"])            # toplantı turları, kararlar, sorular


async def test_verbosity_full_adds_summary_and_file_list(hub):
    await hub.update_settings({"display": {"verbosity": "full"}})
    run = PipelineRun(project_id=hub.active_project_id, steps=[StepRecord(order=11, issue_id="JIRA-11", role="BACKEND_DEV", kind="task", sprint=1, title="Giriş")])
    text = DISP.step_end_md(hub, run, run.steps[0], "BACKEND_DEV", summary="JWT eklendi.", written=["src/a.py", "tests/test_a.py"])
    assert "  JWT eklendi." in text and "  - src/a.py" in text
    await hub.update_settings({"display": {"verbosity": "summary"}})
    assert "  - src/a.py" not in DISP.step_end_md(hub, run, run.steps[0], "BACKEND_DEV", summary="JWT eklendi.", written=["src/a.py"])


# ---------------------------------------------------------------------------
# Kira, tekillik, terk edilen koşunun kaldığı adımdan sürmesi
# ---------------------------------------------------------------------------
def test_lease_is_single_and_a_dead_session_resumes_at_the_same_step(client, hub):
    _setup(client, hub)
    rid = _upload(client)["intake"]["run_id"]
    first = _claim(client)
    assert first["status"] == "CLAIMED" and first["run_id"] == rid
    assert _claim(client)["reason"] == "LEASED"                                   # ikinci oturum IDLE alır
    nxt = client.post(f"/api/runs/{rid}/next-step", json={"client": CLIENT}).json()
    assert nxt["status"] == "STEP"
    order = nxt["order"]
    # oturum kapandı (teslim yok): kira dolunca sonraki çalıştırma AYNI adımdan sürer
    hub.runner["lease"]["expires_at"] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    again = _claim(client)
    assert again["status"] == "CLAIMED"
    nxt2 = client.post(f"/api/runs/{rid}/next-step", json={"client": CLIENT}).json()
    assert nxt2["status"] == "STEP" and nxt2["order"] == order and nxt2["system_prompt"] == nxt["system_prompt"]


async def test_abandoned_run_is_revived_by_claim_work_at_the_same_step(client, hub):
    from server.engine.mcp_client import McpClientEngine
    _setup(client, hub)
    rid = _upload(client)["intake"]["run_id"]
    _claim(client)
    nxt = client.post(f"/api/runs/{rid}/next-step", json={"client": CLIENT}).json()
    run = hub.runs[rid]
    run.last_seen = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()      # terk süresi (≥ 3 × aralık = 30 dk) aşıldı
    runs_api = hub._runs_api if getattr(hub, "_runs_api", None) else None
    engine = runs_api.mcp if runs_api else McpClientEngine(hub)
    assert await engine.sweep_once() == 1 and run.status == "ABANDONED"
    again = _claim(client)
    assert again["status"] == "CLAIMED" and again["run_id"] == rid and hub.runs[rid].status != "ABANDONED"
    nxt2 = client.post(f"/api/runs/{rid}/next-step", json={"client": CLIENT}).json()
    assert nxt2["status"] == "STEP" and nxt2["order"] == nxt["order"]


async def test_sprint_run_abandon_time_is_at_least_three_runner_intervals(hub):
    await hub.update_settings({"runner": {"interval_min": 10}})
    assert DRV.abandon_after_s(hub) == 1800 and DRV.lease_ttl_s(hub) == 900


# ---------------------------------------------------------------------------
# Oturum sınırı (§9.4) ve bağımsız değerlendirme (§6.6)
# ---------------------------------------------------------------------------
def test_session_boundary_before_evaluation_and_fresh_claim_required(client, hub):
    _setup(client, hub, max_tasks=3)
    client.post("/api/settings/runner", json={"runner": {"max_steps_per_session": 100}})
    _upload(client)
    reasons = []
    for _ in range(14):
        claim, log, end = _session(client, hub)
        if end == "SESSION_BOUNDARY":
            rid = claim["run_id"]
            last_submit = [b for k, b in log if k == "submit"][-1]
            run_ = hub.runs[rid]
            nxt_llm = next((s for s in run_.steps[run_.cursor:] if not s.server_side and s.kind not in ("plan", "close")), None)
            reasons.append((last_submit["message"], nxt_llm))
            # sınırdan sonra claim_work çağrılmadan çekilirse reddedilir; taze oturum (claim) şart
            blocked = client.post(f"/api/runs/{rid}/next-step", json={"client": CLIENT}).json()
            assert blocked["status"] == "SESSION_BOUNDARY" and "taze oturumda" in blocked["message"]
            if reasons[-1][1] is not None and (reasons[-1][1].kind == "meeting" or reasons[-1][1].role in ("QA", "PO")):
                assert "EVALUATION" in reasons[-1][0]
        if claim["status"] != "CLAIMED":
            break
    assert any("EVALUATION" in r[0] for r in reasons)                                   # geliştirmeden değerlendirmeye geçerken sınır kondu
    assert any(r[1] is not None and (r[1].kind == "meeting" or r[1].role in ("QA", "PO")) for r in reasons)


def test_session_boundary_after_max_steps_per_session(client, hub):
    _setup(client, hub, max_tasks=50)
    client.post("/api/settings/runner", json={"runner": {"max_steps_per_session": 2}})
    _upload(client)
    claim, log, end = _session(client, hub)
    submits = [b for k, b in log if k == "submit"]
    assert end == "SESSION_BOUNDARY" and len(submits) == 2 and "MAX_STEPS" in submits[-1]["message"]


# ---------------------------------------------------------------------------
# Bütçe, takılma, token ölçümü (§3.5)
# ---------------------------------------------------------------------------
def test_step_budget_exceeded_blocks_the_sprint_and_manager_can_unblock(client, hub):
    _setup(client, hub, max_tasks=50)
    client.post("/api/settings/runner", json={"runner": {"max_steps_per_session": 100}})
    client.post("/api/settings/autonomy", json={"budget": {"max_steps_per_sprint": 4}})
    _upload(client)
    end = None
    for _ in range(12):
        claim, log, end = _session(client, hub)
        if end == "BLOCKED" or claim["status"] == "BLOCKED":
            break
    sp = SP.get_sprint(hub, 1)
    assert sp["status"] == "BLOCKED" and sp["blocked"]["reason"] == "BUDGET_EXCEEDED" and "adım" in sp["blocked"]["detail"]
    blocked_claim = _claim(client)
    assert blocked_claim["status"] == "BLOCKED" and blocked_claim["reason"] == "BUDGET_EXCEEDED"
    last = [b for k, b in log if k == "submit"]
    if last:
        assert last[-1]["status"] == "BLOCKED" and "Durdu" in last[-1]["display_md"] and "Harcama: sprint" in last[-1]["display_md"]
    # sınır hâlâ aşılıyorken sürdürme reddedilir; sınırı artırınca sürer
    assert client.post("/api/sprints/1/unblock").status_code == 409
    client.post("/api/settings/autonomy", json={"budget": {"max_steps_per_sprint": 400}})
    ok = client.post("/api/sprints/1/unblock").json()
    assert ok["status"] == "OK" and SP.get_sprint(hub, 1)["status"] == "IN_PROGRESS" and hub.runs[blocked_claim.get("run_id") or next(iter(hub.runs))].paused is False
    assert _claim(client)["status"] in ("CLAIMED", "IDLE")


async def test_stall_detection_and_consecutive_failures_block_the_sprint(hub):
    await hub.update_settings({"autonomy": {"budget": {"stall_steps": 3, "max_consecutive_failed_steps": 99}}})
    run = PipelineRun(project_id=hub.active_project_id, mode="sprint", engine="mcp_client")
    rec = StepRecord(order=11, issue_id="JIRA-11", role="BACKEND_DEV", kind="task", sprint=1, status="DONE")
    run.steps.append(rec)
    sp = SP.new_sprint(hub, 1, "Hedef")
    SP.set_sprint_status(hub, sp, "IN_PROGRESS")
    assert await DRV.enforce_budgets(hub, run, rec, progress=True, failed=False) is None
    assert await DRV.enforce_budgets(hub, run, rec, progress=False, failed=False) is None
    assert await DRV.enforce_budgets(hub, run, rec, progress=False, failed=False) is None
    assert await DRV.enforce_budgets(hub, run, rec, progress=False, failed=False) == "STALLED"
    assert sp["status"] == "BLOCKED" and sp["blocked"]["reason"] == "STALLED" and run.paused and run.pause_reason == "BLOCKED:STALLED"
    # ilerleme sayacı sıfırlanırsa (yönetici sürdürür) tekrar çalışır
    await hub.update_settings({"autonomy": {"budget": {"stall_steps": 50, "max_consecutive_failed_steps": 2}}})
    await DRV.unblock_sprint(hub, 1)
    assert await DRV.enforce_budgets(hub, run, rec, progress=False, failed=True) is None
    assert await DRV.enforce_budgets(hub, run, rec, progress=False, failed=True) == "BUDGET_EXCEEDED" and "art arda başarısız" in sp["blocked"]["detail"]


async def test_budget_warning_at_percent_and_token_limit_per_task(hub):
    events = []
    orig = hub.broadcast

    async def spy(msg):
        events.append(msg.get("type"))
        return await orig(msg)
    hub.broadcast = spy
    await hub.update_settings({"autonomy": {"budget": {"max_tokens_per_sprint": 1000, "warn_at_percent": 50, "max_tokens_per_task": 600}}})
    run = PipelineRun(project_id=hub.active_project_id, mode="sprint", engine="mcp_client")
    rec = StepRecord(order=11, issue_id="JIRA-11", role="BACKEND_DEV", kind="task", sprint=1, status="DONE", tokens_in=300, tokens_out=300)
    run.steps.append(rec)
    sp = SP.new_sprint(hub, 1, "Hedef")
    SP.set_sprint_status(hub, sp, "IN_PROGRESS")
    assert await DRV.enforce_budgets(hub, run, rec, progress=True, failed=False) is None and "BUDGET_WARNING" in events and "tokens" in sp["warned"]
    assert sp["status"] == "IN_PROGRESS"                                         # uyarı iş sürer
    rec.tokens_out = 800
    assert await DRV.enforce_budgets(hub, run, rec, progress=True, failed=False) == "BUDGET_EXCEEDED" and "token" in sp["blocked"]["detail"]
    # görev başına sınır: görev durdurulur, bekleyen düzeltme turları iptal, TOKEN_LIMIT ile taşınır
    await hub.update_jira_issue("JIRA-11", {"order": 11, "title": "t", "kind": "task", "status": "IN_PROGRESS", "assignee": "BACKEND_DEV"})
    run.steps.append(StepRecord(order=11, issue_id="JIRA-11", role="BACKEND_DEV", kind="fix", sprint=1, status="PENDING"))
    assert await DRV.check_task_tokens(hub, run, rec) is True
    assert hub.jira_issues["JIRA-11"]["token_limit_sprint"] == 1 and run.steps[-1].status == "SKIPPED"
    sp["committed_issue_ids"] = ["JIRA-11"]
    summary = SP.summarize(hub, run, 1)
    assert summary["carried"][0]["reason"] == "TOKEN_LIMIT" and "TOKEN_LIMIT" in SP.RESCOPE_REASONS


def test_token_estimate_uses_payload_size_when_client_does_not_report(client, hub, tmp_project):
    hub.step_by_step_mode = False
    run = client.post("/api/runs", json={"steps": [3], "engine": "mcp_client", "client": CLIENT}).json()["run"]
    rid = run["run_id"]
    client.post(f"/api/runs/{rid}/next-step", json={"client": CLIENT})
    big = "x" * 8000
    env = {"from_agent": "BACKEND_DEV", "to_agent": "FRONTEND_DEV", "intent": "BACKEND_API_EXPOSED", "status": "SUCCESS",
           "payload": {"summary": "s", "files": [{"path": "src/big.py", "content": f"DATA = '{big}'\n"}]}, "metadata": {"tokens_used": 5}}
    client.post(f"/api/runs/{rid}/steps/3/result", json={"result_json": json.dumps(env)})
    assert hub.runs[rid].steps[0].tokens_out >= 2000          # ≈ 8000 karakter / 4; sabit işleyici tahmini (420) değil
    run2 = client.post("/api/runs", json={"steps": [3], "engine": "mcp_client", "client": CLIENT, "force_new": True}).json()["run"]
    client.post(f"/api/runs/{run2['run_id']}/next-step", json={"client": CLIENT})
    client.post(f"/api/runs/{run2['run_id']}/steps/3/result", json={"result_json": json.dumps(env), "tokens_in": 111, "tokens_out": 222})
    assert hub.runs[run2["run_id"]].steps[0].tokens_out == 222 and hub.runs[run2["run_id"]].steps[0].tokens_in == 111   # bildirilen değer kullanılır


# ---------------------------------------------------------------------------
# IDLE / BLOCKED / DONE / PAUSED durumları
# ---------------------------------------------------------------------------
def test_claim_work_idle_when_nothing_to_do(client, hub):
    r = _claim(client)
    assert r["status"] == "IDLE" and r["reason"] == "NO_WORK"
    SP.ensure_state(hub)["project_status"] = "DONE"
    assert _claim(client)["reason"] == "PROJECT_DONE"
    SP.ensure_state(hub)["project_status"] = "PAUSED"
    assert _claim(client)["reason"] == "PROJECT_PAUSED"
    assert hub.runner["last_result"]["status"] == "IDLE"


def test_claim_work_blocked_while_waiting_for_manager_and_when_paused(client, hub):
    _setup(client, hub, commit_approval="manual")
    rid = _upload(client)["intake"]["run_id"]
    for _ in range(20):
        claim, log, end = _session(client, hub)
        if claim["status"] != "CLAIMED" or end == "WAITING_APPROVAL":
            break
    waiting = _claim(client)
    assert waiting["status"] == "BLOCKED" and waiting["reason"] == "AWAITING_MANAGER" and waiting["detail"] == "sprint_commit"
    assert client.post("/api/sprints/1/commit").json()["status"] == "APPROVED"
    time.sleep(0.3)
    client.post(f"/api/runs/{rid}/pause", json={"reason": "bakım"})
    paused = _claim(client)
    assert paused["status"] == "BLOCKED" and paused["reason"] == "PAUSED"


# ---------------------------------------------------------------------------
# Otonomi: seviye ön ayarları (anahtarlar yazılır), L3 ön koşulları, durdur
# ---------------------------------------------------------------------------
def test_level_presets_write_keys_and_level_is_derived_not_stored(client, hub):
    for level, expect in (("L0", ("every_step", "manual", False, None, False)), ("L1", ("critical_only", "manual", False, None, False)),
                          ("L2", ("note_and_continue", "timeout_default", False, 1800, True))):
        res = client.post("/api/autonomy/preset", json={"level": level}).json()
        s = hub.get_settings()
        assert res["level"] == level
        assert (s["approval_mode"], SP.cfg(hub)["commit_approval"], SP.cfg(hub)["auto_chain"], M.autonomy(hub)["question_timeout_s"], M.autonomy(hub)["strict_dod"]) == expect
        assert "level" not in (s.get("autonomy") or {})
    client.post("/api/settings/engine", json={"approval_mode": "auto"})
    assert M.current_level(hub) == "CUSTOM"                         # anahtarlar ön ayara uymuyorsa seviye CUSTOM
    assert client.post("/api/autonomy/preset", json={"level": "L9"}).status_code == 400


def test_l3_is_refused_until_preconditions_hold_and_teknoloji_gate_is_unchanged(client, hub):
    res = client.post("/api/autonomy/preset", json={"level": "L3"})
    assert res.status_code == 409
    keys = {c["key"]: c["ok"] for c in res.json()["checks"]}
    assert keys["command_isolation"] is False and keys["runner_installed"] is False and keys["budgets_defined"] is True   # yalıtım F6'da gelir
    assert M.current_level(hub) != "L3" and hub.get_settings()["approval_mode"] != "auto"
    pre = client.get("/api/autonomy/l3-preconditions").json()
    assert pre["ok"] is False and len(pre["checks"]) == 5
    assert client.post("/api/settings/autonomy", json={"level": "L3"}).status_code == 409


async def test_stop_autonomy_writes_l0_and_pauses_the_active_run(client, hub):
    _setup(client, hub)
    rid = _upload(client)["intake"]["run_id"]
    _claim(client)
    res = client.post("/api/autonomy/stop").json()
    assert res["status"] == "STOPPED" and res["level"] == "L0" and res["paused_run"] == rid
    assert hub.runs[rid].paused and hub.runs[rid].pause_reason == "autonomy_stopped" and DRV.lease_valid(hub) is None
    assert _claim(client)["reason"] == "PAUSED"


def test_sprint_cancel_returns_open_items_to_backlog(client, hub):
    _setup(client, hub, max_tasks=3)
    _upload(client)
    for _ in range(3):
        _session(client, hub)
    n = SP.ensure_state(hub)["current_sprint"]
    res = client.post(f"/api/sprints/{n}/cancel").json()
    sp = SP.get_sprint(hub, n)
    assert res["status"] == "OK" and sp["status"] == "CANCELLED"
    for iid in sp["committed_issue_ids"]:
        i = hub.jira_issues[iid]
        assert i["status"] == "DONE" or (i["status"] == "BACKLOG" and not i.get("sprint") and i["carry_over"]["last_reason"] == "NOT_STARTED")
    assert client.post(f"/api/sprints/{n}/cancel").status_code == 409


# ---------------------------------------------------------------------------
# MCP araçları ve görünürlük
# ---------------------------------------------------------------------------
async def test_new_mcp_tools_are_registered_and_blocking_questions_cannot_be_answered_by_an_agent(client, hub):
    import server.main as main
    tools = {t.name for t in await main.mcp.list_tools()}
    assert {"claim_work", "get_activity_feed", "get_sprint_state", "list_questions", "answer_question", "get_tech_requirements", "add_manager_input"} <= tools
    assert "approve_tech_requirements" not in tools            # onay ajan tarafından çağrılamaz (yalnızca yönetici, dashboard)
    store = M.store(hub)["questions"]
    store.append({"id": "Q-1", "sprint": 1, "meeting_id": "M-1", "category": "TECHNOLOGY", "raised_by": "DEVOPS", "text": "t", "options": [{"key": "A", "label": "a"}, {"key": "B", "label": "b"}],
                  "recommended": "A", "rationale": "r", "blocking": True, "raised_at": "x", "deadline": None, "status": "OPEN", "answer": None, "answered_by": None,
                  "answered_at": None, "decision_ref": None, "adr_ref": None, "adr_draft": None})
    store.append({**store[0], "id": "Q-2", "category": "DESIGN", "blocking": False})
    api = main.runs_api()
    with pytest.raises(Exception) as e:
        await api.answer_question("Q-1", "A")
    assert "dashboard" in str(e.value)
    res = await api.answer_question("Q-2", "A")
    assert res["question"]["status"] == "ANSWERED"


def test_activity_feed_and_sprint_state_and_manager_input(client, hub):
    _setup(client, hub, max_tasks=3)
    out = client.post("/api/manager-input", json={"text": NOTES, "title": "Sohbetten not"}).json()
    assert out["status"] == "QUEUED" and out["run_id"] and SP.ensure_state(hub)["pending_intake"]["spec_ids"] == [out["spec"]["id"]]
    for _ in range(3):
        _session(client, hub)
    feed = client.get("/api/activity?limit=15").json()
    md = feed["markdown"]
    assert "FS-SC · proje" in md and "Harcama: sprint" in md and "Runner: son görülme" in md and "Son etkinlik:" in md
    assert feed["events"] and any("HANDOFF" in l or "SPRINT_" in l or "MEETING" in l for l in feed["events"])
    state = client.get("/api/sprints/state").json()
    assert state["current_sprint"]["sprint_number"] >= 1 and state["usage"]["tokens"] > 0 and state["budget"]["stall_steps"] == 6 and state["runner"]["fresh"] is True
    status = client.get("/api/runner/status").json()
    assert status["fresh"] is True and status["claims"] >= 1 and status["client"]["name"] == CLIENT["name"]
    assert client.post("/api/manager-input", json={"text": "  "}).status_code == 400


def test_runner_settings_endpoint_and_sanitization(client, hub):
    out = client.post("/api/settings/runner", json={"interval_min": 5, "max_steps_per_session": 999, "verbosity": "full"}).json()
    assert out["runner"]["interval_min"] == 5 and out["runner"]["max_steps_per_session"] == 100 and out["display"]["verbosity"] == "full"
    assert client.post("/api/settings/runner", json={"display": {"verbosity": "bogus"}}).json()["display"]["verbosity"] == "full"
