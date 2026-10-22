"""“Zaten karşılanıyor” kontrolü: dosyaları commit'li ve doğrulaması geçen TEST/DEVOPS/DOCS görevi ajana verilmeden sunucuca kapanır;
özellik görevleri ve kanıtı yetmeyenler kapanmaz (eksik dosyaların listesi ajana kanıt olarak gider)."""
import subprocess
import sys

from server import satisfied as SAT
from server.runs import PipelineRun, StepRecord

PY = f'"{sys.executable}"' if " " in sys.executable else sys.executable
PASS_CMD = f'{PY} -c "print(\'ok\')"'
FAIL_CMD = f'{PY} -c "import sys; sys.exit(1)"'


def _git(project: str, *args: str) -> None:
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=project, check=True, capture_output=True)


async def _setup(client, hub, project: str, *, work_type="TEST", hints=("tests/test_a.py", "README.md"), commit=True, verify_cmd=PASS_CMD):
    for rel in hints:
        full = f"{project}/{rel}"
        import os
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w", encoding="utf-8") as f:
            f.write("# var\n")
    _git(project, "init", "-q")
    if commit:
        _git(project, "add", "-A")
        _git(project, "commit", "-q", "-m", "init")
    hub.step_by_step_mode = False
    await hub.update_settings({"approval_mode": "auto", "auto_verify": True, "auto_commit": False, "verification": {"test": verify_cmd}})
    await hub.update_jira_issue("JIRA-90", {"order": 90, "title": "Jest test paketi", "description": "d", "issue_type": "TASK", "kind": "task", "status": "BACKLOG", "assignee": "QA",
                                            "work_type": work_type, "files_hint": list(hints), "acceptance_criteria": ["testler geçer"], "task_key": "T-90"})
    rec = StepRecord(order=90, issue_id="JIRA-90", role="QA", kind="task", title="Jest test paketi", work_type=work_type)
    run = PipelineRun(project_id=hub.active_project_id, steps=[rec], engine="mcp_client", project_dir=project)
    run.step_by_step = False
    hub.runs[run.run_id] = run
    return run, rec


async def test_task_with_committed_files_and_passing_verification_is_closed_without_an_agent(client, hub, tmp_project):
    run, rec = await _setup(client, hub, tmp_project)
    nxt = client.post(f"/api/runs/{run.run_id}/next-step", json={"client": {"name": "curl"}}).json()
    assert nxt["status"] == "RUN_COMPLETE", nxt                                         # ajana adım verilmedi
    assert rec.status == "DONE" and rec.action == "ALREADY_SATISFIED" and rec.commit_status == "NOTHING" and all(c["ok"] for c in rec.dod)
    assert hub.jira_issues["JIRA-90"]["status"] == "DONE"
    assert any(a["action"] == "ALREADY_SATISFIED" for a in hub.jira_issues["JIRA-90"]["audit_trail"])
    assert any(e["action"] == "TASK_ALREADY_SATISFIED" for e in hub.events)


async def test_feature_tasks_are_never_closed_by_file_existence(client, hub, tmp_project):
    run, rec = await _setup(client, hub, tmp_project, work_type="FEATURE")
    nxt = client.post(f"/api/runs/{run.run_id}/next-step", json={"client": {"name": "curl"}}).json()
    assert nxt["status"] == "STEP" and rec.action != "ALREADY_SATISFIED"
    assert "Mevcut durum kanıtı" in nxt["user_context"] and "VAR  tests/test_a.py" in nxt["user_context"]        # ajana kanıt gider


async def test_failing_verification_or_uncommitted_files_do_not_close_the_task(client, hub, tmp_project):
    run, rec = await _setup(client, hub, tmp_project, verify_cmd=FAIL_CMD)
    nxt = client.post(f"/api/runs/{run.run_id}/next-step", json={"client": {"name": "curl"}}).json()
    assert nxt["status"] == "STEP" and rec.status == "ACTIVE" and rec.action != "ALREADY_SATISFIED"      # doğrulama kalınca ajan çalışır
    assert any(a["action"] == "SATISFIED_CHECK_FAILED" for a in hub.jira_issues["JIRA-90"]["audit_trail"])


async def test_uncommitted_hint_files_are_not_evidence(client, hub, tmp_project):
    run, rec = await _setup(client, hub, tmp_project, commit=False)
    nxt = client.post(f"/api/runs/{run.run_id}/next-step", json={"client": {"name": "curl"}}).json()
    assert nxt["status"] == "STEP" and rec.action != "ALREADY_SATISFIED"


async def test_missing_hint_file_means_the_agent_only_delivers_what_is_missing(client, hub, tmp_project):
    run, rec = await _setup(client, hub, tmp_project, hints=("tests/test_a.py",))
    await hub.update_jira_issue("JIRA-90", {"files_hint": ["tests/test_a.py", "test/e2e/README.md"]})
    nxt = client.post(f"/api/runs/{run.run_id}/next-step", json={"client": {"name": "curl"}}).json()
    assert nxt["status"] == "STEP"
    assert "YOK  test/e2e/README.md" in nxt["user_context"] and "yalnızca eksiği" in nxt["user_context"]


async def test_setting_can_turn_the_check_off(client, hub, tmp_project):
    run, rec = await _setup(client, hub, tmp_project)
    await hub.update_settings({"skip_satisfied_tasks": False})
    nxt = client.post(f"/api/runs/{run.run_id}/next-step", json={"client": {"name": "curl"}}).json()
    assert nxt["status"] == "STEP"


def test_existence_and_context_section(tmp_path):
    (tmp_path / "a.txt").write_text("x", encoding="utf-8")
    rows = SAT.existence(str(tmp_path), ["a.txt", "b.txt"])
    assert rows[0]["exists"] and rows[0]["size"] == 1 and not rows[1]["exists"]
    assert SAT.context_section(str(tmp_path), {"files_hint": ["b.txt"]}) == ""        # hiçbiri yoksa ek bölüm yok


def test_noop_test_placeholder_is_not_a_real_test_but_docs_only_delivery_needs_none():
    from server import guard as G
    from server import verify as V
    assert V.is_noop_test('cd apps/backend && node -e "process.exit(0)" && cd ../.. && cd apps/web && node -e "process.exit(0)"')
    assert not V.is_noop_test("cd apps/backend && npm test --silent -- --runTestsByPath src/a.spec.ts")
    noop = {"status": "PASSED", "results": [{"name": "lint", "status": "PASSED"}, {"name": "test", "status": "PASSED", "noop": True}]}
    real = {"status": "PASSED", "results": [{"name": "test", "status": "PASSED"}]}
    assert not G.tests_ran(noop) and G.tests_ran(real)                              # boş komut "test koştu" sayılmaz
    d = G.task_dod(noop, "COMMITTED", False, written=["apps/backend/test/e2e/README.md", "devops/Dockerfile"])
    assert all(c["ok"] for c in d) and "Test gerekmedi" in next(c["text"] for c in d if c["key"] == "tests_ran")
    d = G.task_dod(noop, "COMMITTED", False, written=["apps/backend/src/a.ts"])        # kod değişti ama test koşmadı: DoD reddeder
    assert not next(c["ok"] for c in d if c["key"] == "tests_ran")
    assert not all(c["ok"] for c in G.task_dod(noop, "NOTHING", False))                # try_close (written yok): boş komut kapatma kanıtı olamaz


def _claim_env(evidence):
    import json
    return json.dumps({"from_agent": "BACKEND_DEV", "to_agent": "QA", "intent": "SUBMIT_CODE", "status": "SUCCESS",
                       "payload": {"summary": "Görev mevcut kodla karşılanıyor.", "friendly_dialogue": "hazır", "thinking": "t", "what_doing": "w", "what_next": "n",
                                   "files": [], "task_key": "T-90", "already_satisfied": {"evidence": evidence}},
                       "metadata": {"tokens_used": 50}})


async def test_feature_task_can_be_closed_by_evidence_tests_that_the_server_runs(client, hub, tmp_project):
    run, rec = await _setup(client, hub, tmp_project, work_type="FEATURE")
    nxt = client.post(f"/api/runs/{run.run_id}/next-step", json={"client": {"name": "curl"}}).json()
    assert nxt["status"] == "STEP" and "already_satisfied" in nxt["output_contract"]
    res = client.post(f"/api/runs/{run.run_id}/steps/90/result", json={"result_json": _claim_env([{"criterion": "testler geçer", "test": "tests/test_a.py"}])}).json()
    assert res["status"] == "RUN_COMPLETE" and res["verification"]["status"] == "PASSED", res
    assert rec.status == "DONE" and rec.commit_status == "NOTHING" and hub.jira_issues["JIRA-90"]["status"] == "DONE"
    assert any(a["action"] == "SATISFIED_BY_EVIDENCE" for a in hub.jira_issues["JIRA-90"]["audit_trail"])


async def test_evidence_claim_is_rejected_when_the_test_is_missing_or_does_not_cover_every_criterion(client, hub, tmp_project):
    run, rec = await _setup(client, hub, tmp_project, work_type="FEATURE")
    await hub.update_jira_issue("JIRA-90", {"acceptance_criteria": ["kriter 1", "kriter 2"]})
    client.post(f"/api/runs/{run.run_id}/next-step", json={"client": {"name": "curl"}})
    few = client.post(f"/api/runs/{run.run_id}/steps/90/result", json={"result_json": _claim_env([{"criterion": "kriter 1", "test": "tests/test_a.py"}])}).json()
    assert few["status"] == "REJECTED" and "2 kabul kriteri" in few["validation_errors"][0]
    ghost = client.post(f"/api/runs/{run.run_id}/steps/90/result", json={"result_json": _claim_env(
        [{"criterion": "kriter 1", "test": "tests/test_a.py"}, {"criterion": "kriter 2", "test": "tests/yok.py"}])}).json()
    assert ghost["status"] == "REJECTED" and "yok" in ghost["validation_errors"][0]
    assert rec.status != "DONE"


async def test_evidence_claim_with_failing_tests_does_not_close_the_task(client, hub, tmp_project):
    run, rec = await _setup(client, hub, tmp_project, work_type="FEATURE", verify_cmd=FAIL_CMD)
    client.post(f"/api/runs/{run.run_id}/next-step", json={"client": {"name": "curl"}})
    res = client.post(f"/api/runs/{run.run_id}/steps/90/result", json={"result_json": _claim_env([{"criterion": "testler geçer", "test": "tests/test_a.py"}])}).json()
    assert res["verification"]["status"] == "FAILED" and rec.status != "DONE" or res.get("fix_requested") is True
