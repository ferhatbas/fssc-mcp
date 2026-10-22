"""
G3 — Sürücü ve dayanıklılık: koşu kilidi, doğrulama kalp atışı, atlanan adımlar, proxy zaman aşımı, timeout_default taahhüt,
acil girdi → adhoc toplantı ve kapsam değişikliği, bozuk kayıt dosyasından kurtarma, otomatik runner ve kurulum durumu.
"""
import asyncio
import json
import os
import sys
import time

import pytest

from server import claude_bridge as CB
from server import driver as DRV
from server import sprint as SP
from server import sprint_flow as SPF
from server.runs import PipelineRun, StepRecord
from server.telemetry import TelemetryHub
from test_g2_claude_bridge import FAKE_CLI
from test_sprint import _sprint_settings, _upload, _wait

CLIENT = {"name": "pytest-g3", "version": "1"}


def _env(from_agent: str, to_agent: str, intent: str, files) -> str:
    return json.dumps({
        "trace_id": "t", "from_agent": from_agent, "to_agent": to_agent, "intent": intent, "status": "SUCCESS",
        "payload": {"summary": "ok", "friendly_dialogue": "ok", "thinking": "ok", "what_doing": "ok", "what_next": "ok", "files": files},
    })


def test_advance_skips_skipped_steps_and_completes():
    run = PipelineRun(project_id="p", steps=[StepRecord(order=1, issue_id="J1", role="PM"),
                                              StepRecord(order=2, issue_id="J2", role="ARCHITECT", status="SKIPPED"),
                                              StepRecord(order=3, issue_id="J3", role="BACKEND_DEV")])
    run.advance()
    assert run.cursor == 2 and run.current_step is not None and run.current_step.order == 3
    run.advance()
    assert run.is_terminal and run.status == "COMPLETED"


async def test_concurrent_submits_are_serialized_by_the_run_lock(hub, tmp_project):
    from server.engine.api import LocalRunsApi
    api = LocalRunsApi(hub)
    hub.step_by_step_mode = False
    await hub.update_settings({"approval_mode": "auto"})
    rid = (await api.start_run(project_id=hub.active_project_id, steps=[1, 2], engine="mcp_client", client=CLIENT))["run"]["run_id"]
    await api.next_step(rid, CLIENT)
    env = _env("PM", "ARCHITECT", "TASK_DISPATCH", [{"path": "FS-docs/PRD.md", "content": "# PRD\n"}])
    a, b = await asyncio.gather(api.submit_result(rid, 1, env, client=CLIENT), api.submit_result(rid, 1, env, client=CLIENT))
    assert sorted([a["status"], b["status"]]) == ["NEXT", "REJECTED"]       # ikinci teslim 'sıra uyuşmuyor' alır, çift ilerleme yok
    assert hub.runs[rid].cursor == 1 and hub.runs[rid].steps[0].status == "DONE"


async def test_heartbeat_touches_the_run_during_long_verification(client, hub, tmp_project, monkeypatch):
    from server import pipeline as P
    monkeypatch.setattr(P, "VERIFY_HEARTBEAT_S", 0.15)
    seen = []
    rid_holder = {}

    async def slow_verify(*args, **kwargs):
        for _ in range(6):
            await asyncio.sleep(0.15)
            seen.append(hub.runs[rid_holder["rid"]].last_seen)
        return {"status": "PASSED", "results": [{"name": "test", "status": "PASSED", "exit_code": 0, "cmd": "x", "output": "", "duration_ms": 1}],
                "failed_step": None, "ran_install": False, "summary": "ok", "tests": None, "failed_tests": [], "isolation": "host"}
    monkeypatch.setattr(P, "run_verification", slow_verify)
    hub.step_by_step_mode = False
    await hub.update_settings({"approval_mode": "auto", "auto_verify": True, "verification": {"test": "echo ok"}})
    run = client.post("/api/runs", json={"steps": [3], "engine": "mcp_client", "client": CLIENT}).json()["run"]
    rid_holder["rid"] = run["run_id"]
    client.post(f"/api/runs/{run['run_id']}/next-step", json={"client": CLIENT})
    res = client.post(f"/api/runs/{run['run_id']}/steps/3/result",
                      json={"result_json": _env("BACKEND_DEV", "QA", "SUBMIT_CODE", [{"path": "src/a.py", "content": "x = 1\n"}]), "client": CLIENT}).json()
    assert res["verification"]["status"] == "PASSED"
    assert len(set(seen)) >= 3       # last_seen doğrulama sürerken birden çok kez güncellendi


async def test_proxy_read_timeout_covers_long_verifications():
    from server.engine.proxy import ProxyRunsApi
    p = ProxyRunsApi("http://127.0.0.1:1")
    try:
        assert p._client.timeout.read >= 600 and p._client.timeout.connect <= 30
    finally:
        await p.aclose()


# ---------------------------------------------------------------------------
# timeout_default taahhüt (§7.5)
# ---------------------------------------------------------------------------
def test_timeout_default_commit_is_finalized_by_the_server_after_the_deadline(client, hub):
    _sprint_settings(client, commit_approval="timeout_default", max_tasks=50, auto_chain=False)
    client.post("/api/settings/autonomy", json={"question_timeout_s": 2})
    rid = _upload(client)["intake"]["run_id"]
    waiting = _wait(client, rid, lambda r: r["status"] == "WAITING_APPROVAL")
    assert waiting["gate_kind"] == "sprint"
    done = _wait(client, rid, lambda r: r["is_terminal"], timeout=150)
    assert done["status"] == "COMPLETED", done["cancel_reason"]
    sp = SP.get_sprint(hub, 1)
    assert sp["commit_approval"]["by"] == "TIMEOUT" and sp["status"] == "CLOSED"
    assert any(e["action"] == "SPRINT_COMMIT_DEFAULTED" for e in hub.events)


def test_timeout_default_with_zero_timeout_commits_immediately(client, hub):
    _sprint_settings(client, commit_approval="timeout_default", max_tasks=50, auto_chain=False)
    client.post("/api/settings/autonomy", json={"question_timeout_s": 0})
    rid = _upload(client)["intake"]["run_id"]
    done = _wait(client, rid, lambda r: r["is_terminal"], timeout=150)
    assert done["status"] == "COMPLETED" and not any(s["status"] == "WAITING_APPROVAL" for s in done["steps"])
    assert SP.get_sprint(hub, 1)["commit_approval"]["by"] == "TIMEOUT"


# ---------------------------------------------------------------------------
# Acil girdi → adhoc toplantı → kapsam değişikliği (§8.4)
# ---------------------------------------------------------------------------
async def _sprint_fixture(hub):
    await hub.update_settings({"sprint": {"enabled": True, "max_tasks": 3}})
    sp = SP.new_sprint(hub, 1, "Sprint 1 hedefi")
    for iid, order, status, sprint in (("JIRA-11", 11, "DONE", 1), ("JIRA-12", 12, "IN_PROGRESS", 1), ("JIRA-13", 13, "IN_PROGRESS", 1), ("JIRA-14", 14, "BACKLOG", None)):
        await hub.update_jira_issue(iid, {"order": order, "title": f"İş {iid}", "kind": "task", "work_type": "FEATURE", "status": status,
                                          "assignee": "BACKEND_DEV", "priority": "P1", "sprint": sprint, "depends_on": []})
    sp["committed_issue_ids"] = ["JIRA-11", "JIRA-12", "JIRA-13"]
    SP.set_sprint_status(hub, sp, "IN_PROGRESS")
    SP.ensure_state(hub)["current_sprint"] = 1
    run = PipelineRun(project_id=hub.active_project_id, mode="sprint", status="ACTIVE", steps=[
        StepRecord(order=11, issue_id="JIRA-11", role="BACKEND_DEV", kind="task", sprint=1, title="İş 11", status="DONE"),
        StepRecord(order=12, issue_id="JIRA-12", role="BACKEND_DEV", kind="task", sprint=1, title="İş 12", status="ACTIVE"),
        StepRecord(order=13, issue_id="JIRA-13", role="BACKEND_DEV", kind="task", sprint=1, title="İş 13"),
        StepRecord(order=6, issue_id="JIRA-6", role="QA", kind="phase", sprint=1, title="QA"),
    ])
    run.cursor = 1
    hub.register_run(run)
    hub.active_run_id = run.run_id
    return run, sp


async def test_urgent_input_schedules_adhoc_meeting_and_applies_scope_change(hub, tmp_project):
    run, sp = await _sprint_fixture(hub)
    info = await SPF.schedule_adhoc(hub, "Ödeme sağlayıcısı değişti; bu sprintte webhook öncelikli", spec_id="spec-1")
    assert info and info["inserted"] is True and info["sprint"] == 1
    meeting = run.steps[2]
    assert meeting.kind == "meeting" and meeting.work_type == "adhoc" and meeting.sprint == 1
    assert run.manager_notes[-1]["text"].startswith("ACİL GİRDİ:") and run.manager_notes[-1]["urgent"] is False     # koşu DURMAZ
    assert sp["scope_changes"][-1]["source"] == "urgent_input" and any(e["action"] == "URGENT_INPUT" for e in hub.events)
    assert (await SPF.schedule_adhoc(hub, "ikinci acil not"))["inserted"] is False     # bekleyen adhoc varsa yenisi eklenmez

    # Toplantı promptu acil girdiyi, başlamış/başlamamış işleri ve backlog adaylarını gösterir
    from server import pipeline as P
    from server.steps.flow import MeetingHandler
    ctx = P.make_context(hub, run, meeting)
    prompt = MeetingHandler(meeting.order, "adhoc").build_user_prompt(ctx)
    assert "Acil yönetici girdisi" in prompt and "webhook öncelikli" in prompt
    assert "JIRA-12 · İş JIRA-12 · BACKEND_DEV · BAŞLADI" in prompt and "JIRA-13 · İş JIRA-13 · BACKEND_DEV · başlamadı" in prompt
    assert "JIRA-14" in prompt and "Backlog adayları" in prompt

    # Toplantı sonucu: başlamamış JIRA-13 kapsam dışı, JIRA-14 taahhüde; başlamış JIRA-12'ye dokunulmaz
    run.cursor = 2
    out = await SPF.apply_adhoc(hub, run, meeting, {"commitment": {"out_of_scope": [{"issue_id": "JIRA-13", "reason": "webhook öne alındı"},
                                                                                     {"issue_id": "JIRA-12", "reason": "başlamış; reddedilmeli"}],
                                                                    "items": ["JIRA-14"]}})
    assert out == {"removed": ["JIRA-13"], "added": ["JIRA-14"]}
    assert sp["committed_issue_ids"] == ["JIRA-11", "JIRA-12", "JIRA-14"]
    assert hub.jira_issues["JIRA-13"]["status"] == "BACKLOG" and hub.jira_issues["JIRA-13"]["sprint"] is None
    assert hub.jira_issues["JIRA-13"]["carry_over"]["last_reason"] == "NOT_STARTED" and hub.jira_issues["JIRA-14"]["sprint"] == 1
    ids = [s.issue_id for s in run.steps]
    assert "JIRA-13" not in ids and ids.index("JIRA-14") > ids.index(meeting.issue_id) and ids.index("JIRA-14") < ids.index("JIRA-6")
    assert sp["scope_changes"][-1]["source"] == "adhoc" and any(e["action"] == "SCOPE_CHANGED" for e in hub.events)


async def test_urgent_input_without_sprint_run_returns_none(hub):
    assert await SPF.schedule_adhoc(hub, "acil") is None


# ---------------------------------------------------------------------------
# Bozuk kayıt dosyası: .corrupt kopyası + .bak'tan kurtarma
# ---------------------------------------------------------------------------
async def test_corrupt_registry_is_backed_up_and_recovered_from_bak(tmp_path):
    reg = tmp_path / "history" / "registry.json"
    reg.parent.mkdir()
    good = {"active_project_id": "p1", "projects": {"p1": {"id": "p1", "name": "P1", "path": str(tmp_path / "p1"), "created_at": "x", "last_active": "x"}},
            "runs": [], "saved_at": "x"}
    (reg.parent / "registry.json.bak").write_text(json.dumps(good), encoding="utf-8")
    reg.write_text("{ bozuk json", encoding="utf-8")
    hub = TelemetryHub(registry_path=str(reg), default_project_path=str(tmp_path / "d"), flush_delay_s=0.0)
    try:
        assert hub.load_error and "yedekten" in hub.load_error
        assert "p1" in hub.projects and hub.active_project_id == "p1"
        assert any(f.name.startswith("registry.json.corrupt-") for f in reg.parent.iterdir())
        assert hub.get_snapshot()["load_error"] == hub.load_error
        hub.flush_now()
        assert json.loads(reg.read_text(encoding="utf-8"))["projects"]["p1"]["name"] == "P1"
        assert (reg.parent / "registry.json.bak").exists()
    finally:
        await hub.aclose()


async def test_corrupt_registry_without_backup_starts_empty_but_keeps_the_corrupt_copy(tmp_path):
    reg = tmp_path / "history" / "registry.json"
    reg.parent.mkdir()
    reg.write_text("not json at all", encoding="utf-8")
    hub = TelemetryHub(registry_path=str(reg), default_project_path=str(tmp_path / "d"), flush_delay_s=0.0)
    try:
        assert hub.load_error and "yedek yok" in hub.load_error and hub.projects == {}
        assert any(f.name.startswith("registry.json.corrupt-") and f.read_text(encoding="utf-8") == "not json at all" for f in reg.parent.iterdir())
    finally:
        await hub.aclose()


# ---------------------------------------------------------------------------
# Otomatik runner (Desktop zamanlanmış görevinin sunucu tarafı karşılığı) ve kurulum durumu
# ---------------------------------------------------------------------------
async def test_auto_runner_starts_a_session_only_when_work_is_claimable(client, hub, tmp_project, tmp_path, monkeypatch):
    script = tmp_path / "fake_claude.py"
    script.write_text(FAKE_CLI, encoding="utf-8")
    cli = f'"{sys.executable}" "{script}"'
    hub.step_by_step_mode = False
    await hub.update_settings({"approval_mode": "auto"})
    assert DRV.claimable_work(hub)["reason"] == "NO_WORK"
    run = client.post("/api/runs", json={"steps": [1], "engine": "mcp_client", "client": CLIENT}).json()["run"]
    cw = DRV.claimable_work(hub)
    assert cw["claimable"] is True and cw["run_id"] == run["run_id"]
    res = client.post("/api/settings/claude", json={"cli": cli, "auto_runner": True, "auto_runner_interval_min": 999}).json()
    assert res["claude"]["auto_runner"] is True and res["claude"]["auto_runner_interval_min"] == 60 and res["auto_runner"]["running"] is True
    b = CB.bridge(hub)
    st = await b.auto_tick()
    assert st["last_reason"].startswith("STARTED") and st["starts"] == 1
    for _ in range(200):
        if not b.state["running"]:
            break
        await asyncio.sleep(0.05)
    assert b.state["running"] is False and b.state["session_id"] == "fake-sess-1"
    # İş yokken oturum açılmaz
    hub.runs[run["run_id"]].finish("CANCELLED")
    await hub.update_settings({"sprint": {"enabled": False}})
    st2 = await b.auto_tick()
    assert st2["last_reason"] == "NO_WORK" and st2["starts"] == 1
    # Kapatınca döngü durur
    off = client.post("/api/settings/claude", json={"auto_runner": False}).json()
    assert off["auto_runner"]["enabled"] is False
    setup = client.get("/api/runner/setup").json()
    assert {s["key"] for s in setup["steps"]} >= {"server", "desktop", "cli", "auto_runner", "scheduled_task"}
    assert setup["cli"]["ok"] is True and setup["desktop"]["config_path"].endswith("claude_desktop_config.json") and "claimable" in setup


def test_claimable_work_reasons(hub):
    assert DRV.claimable_work(hub)["reason"] == "NO_WORK"
    run = PipelineRun(project_id=hub.active_project_id, engine="template", status="ACTIVE", steps=[StepRecord(order=1, issue_id="JIRA-1", role="PM")])
    hub.register_run(run)
    assert DRV.claimable_work(hub)["reason"] == "TEMPLATE_ENGINE"
    run.engine = "mcp_client"
    run.paused = True
    assert DRV.claimable_work(hub)["reason"] == "PAUSED"
    run.paused = False
    run.status = "WAITING_APPROVAL"
    assert DRV.claimable_work(hub)["reason"] == "AWAITING_MANAGER"
    run.status = "ACTIVE"
    assert DRV.claimable_work(hub) == {"claimable": True, "reason": "RUN_ACTIVE", "run_id": run.run_id}


async def test_urgent_manager_input_opens_a_task_and_expedites_it_into_the_running_sprint(hub, tmp_project):
    from server.engine.api import LocalRunsApi
    run, sp = await _sprint_fixture(hub)
    out = await LocalRunsApi(hub).add_manager_input("Backend projeyi docker container içine alalım dev olarak, port 5050 olsun", urgent=True)
    task = out["task"]
    issue = hub.jira_issues[task["issue_id"]]
    assert task["role"] == "DEVOPS" and issue["kind"] == "task" and issue["origin"] == "MANAGER" and issue["work_type"] == "DEVOPS" and issue["priority"] == "P0"
    assert issue["needs_grooming"] and issue["acceptance_criteria"]                                 # taslak kabul kriteri
    assert task["expedite"]["mode"] == "now" and issue["sprint"] == 1 and task["issue_id"] in sp["committed_issue_ids"]
    ids = [s.issue_id for s in run.steps]
    assert task["issue_id"] in ids and ids.index(task["issue_id"]) < ids.index("JIRA-6")           # geçerli adımdan sonra, faz adımlarından önce
    assert "Backlog'a iş açıldı" in out["message"] and out["adhoc"]
    again = await LocalRunsApi(hub).add_manager_input("Backend projeyi docker container içine alalım dev olarak, port 5050 olsun", urgent=False)
    assert again["task"]["existing"] is True                                                         # aynı girdi ikinci iş açmaz


async def test_non_urgent_manager_input_is_visible_on_the_board_immediately_and_long_notes_are_specs(hub, tmp_project):
    from server.engine.api import LocalRunsApi
    run, sp = await _sprint_fixture(hub)
    out = await LocalRunsApi(hub).add_manager_input("Giriş ekranına parola göster düğmesi ekle", urgent=False)
    issue = hub.jira_issues[out["task"]["issue_id"]]
    assert out["task"]["role"] == "FRONTEND_DEV" and issue["status"] == "BACKLOG" and issue["priority"] == "P1" and out["task"]["expedite"]["mode"] == "next_sprint"
    long = await LocalRunsApi(hub).add_manager_input("Şartname. " + "kapsam " * 120, urgent=False)
    assert long["task"] is None and long["pending_intake"]                                           # uzun not şartname: yalnızca değerlendirmeye girer


async def test_oncelik_yurutme_sirasini_belirler_ve_kuyruktaki_is_one_alinabilir(hub, tmp_project):
    from server import sprint as SP2
    run, sp = await _sprint_fixture(hub)
    # yürütme sırası: öne alınan iş, toplantı listesinde sonda olsa da başa gelir; bağımlı iş bağımlılığından sonra
    items = [hub.jira_issues["JIRA-14"]]
    for iid, order in (("JIRA-30", 30), ("JIRA-31", 31), ("JIRA-32", 32)):
        await hub.update_jira_issue(iid, {"order": order, "title": iid, "kind": "task", "work_type": "FEATURE", "status": "BACKLOG", "assignee": "BACKEND_DEV", "priority": "P1", "depends_on": []})
        items.append(hub.jira_issues[iid])
    hub.jira_issues["JIRA-32"]["expedite"] = "next_sprint"
    hub.jira_issues["JIRA-30"]["depends_on"] = ["JIRA-32"]
    ids = [i["id"] for i in SP2.execution_order(items)]
    assert ids[0] == "JIRA-32" and ids.index("JIRA-32") < ids.index("JIRA-30")

    # planlanmış sprintin kuyruğundaki iş "Önce yap" ile geçerli adımın hemen arkasına taşınır
    at = [s.issue_id for s in run.steps].index("JIRA-6")                                       # faz adımından önce: sprintin sonundaki işler
    run.steps[at:at] = [StepRecord(order=int(hub.jira_issues[i]["order"]), issue_id=i, role="BACKEND_DEV", kind="task", sprint=1, title=i) for i in ("JIRA-30", "JIRA-31", "JIRA-32")]
    before = [s.issue_id for s in run.steps]
    assert before.index("JIRA-31") > before.index("JIRA-13")
    for iid in ("JIRA-30", "JIRA-31", "JIRA-32"):
        await hub.update_jira_issue(iid, {"sprint": 1})
    out = await SPF.expedite_issue(hub, "JIRA-31", "now")
    assert out["mode"] == "now" and out["moved"] is True
    after = [s.issue_id for s in run.steps]
    assert after[run.cursor + 1] == "JIRA-31" and after.count("JIRA-31") == 1                 # geçerli adımın hemen arkasında, kopya yok
    assert hub.jira_issues["JIRA-31"]["expedite"] == "now"
    import pytest
    with pytest.raises(PermissionError):
        await SPF.expedite_issue(hub, "JIRA-30", "next_sprint")                                  # zaten kuyrukta: sıradaki sprint seçeneği anlamsız
