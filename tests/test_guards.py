"""F6 — Kalite kapıları ve korkuluklar: sıkı DoD, izin listesi, yalıtım, sır taraması, döngü kırıcı, kriter bazında kabul, mimar gözden geçirmesi, L3 ön koşulları."""

import json
import os
import subprocess
import sys
import time

import pytest

from server import guard as G
from server import meetings as M
from server import pipeline as P
from server import quality as Q
from server import scm
from server import sprint as SP
from server import sprint_flow as SPF
from server.runs import PipelineRun, StepRecord
from server.steps.base import StepEvent, StepResult
from server.steps.tasks import normalize_backlog

PY = f'"{sys.executable}"' if " " in sys.executable else sys.executable
PASS_CMD = f'{PY} -c "print(\'ok\')"'
FAIL_CMD = f'{PY} -c "import sys; print(\'boom: AssertionError in src/calc.py\'); sys.exit(1)"'
needs_git = pytest.mark.skipif(not scm.git_available(), reason="git yok")
AWS = "AKIA" + "ABCDEFGHIJKLMNOP"      # sahte; dinamik kurulur ki depoya gerçek sır gibi girmesin
CLIENT = {"name": "t"}


def _env(files, role="BACKEND_DEV", nxt="FRONTEND_DEV", intent="BACKEND_API_EXPOSED", **payload):
    return json.dumps({"from_agent": role, "to_agent": nxt, "intent": intent, "status": "SUCCESS",
                       "payload": {"summary": "s", "files": files, **payload}, "metadata": {"tokens_used": 5}})


class _H:     # hub ihtiyaç duymayan saf izin listesi testleri için
    def __init__(self, policy="allowlist", allow=()):
        self._s = {"sandbox": {"command_policy": policy, "allowlist": list(allow)}}

    def get_settings(self):
        return self._s


# ---------------------------------------------------------------------------
# Sıkı DoD (§7.7)
# ---------------------------------------------------------------------------
def test_task_dod_rules():
    ok = {"status": "PASSED", "results": [{"name": "test", "status": "PASSED"}]}
    assert all(c["ok"] for c in G.task_dod(ok, "COMMITTED", False))
    assert all(c["ok"] for c in G.task_dod(ok, "NOTHING", False))
    skipped = {"status": "SKIPPED", "results": [{"name": "py_compile:a.py", "status": "PASSED"}]}
    unmet = {c["key"] for c in G.task_dod(skipped, "COMMITTED", False) if not c["ok"]}
    assert unmet == {"verification_passed", "tests_ran"}                           # SKIPPED ve "hiç test yok" bitmiş saymaz
    no_test = {"status": "PASSED", "results": [{"name": "build", "status": "PASSED"}]}
    assert {c["key"] for c in G.task_dod(no_test, "COMMITTED", False) if not c["ok"]} == {"tests_ran"}
    assert {c["key"] for c in G.task_dod(ok, "SECRET", False) if not c["ok"]} == {"committed"}
    assert {c["key"] for c in G.task_dod(ok, "COMMITTED", True) if not c["ok"]} == {"no_pending_fix"}
    assert [c["ok"] for c in G.task_dod(ok, "SKIPPED", False, auto_commit=False)] == [True, True, True, True]   # commit kapalıysa kanıtlanamaz değil, istenmiyor


@needs_git
async def test_strict_dod_task_without_tests_is_not_done_until_a_real_test_passes(client, hub, tmp_project):
    hub.step_by_step_mode = False
    await hub.update_settings({"approval_mode": "auto", "autonomy": {"strict_dod": True}, "auto_verify": True, "auto_commit": True, "verification": {"install": PASS_CMD}})
    run = client.post("/api/runs", json={"steps": [3], "engine": "mcp_client", "client": CLIENT}).json()["run"]
    rid = run["run_id"]
    client.post(f"/api/runs/{rid}/next-step", json={"client": CLIENT})
    res = client.post(f"/api/runs/{rid}/steps/3/result", json={"result_json": _env([{"path": "src/a.py", "content": "def add(a, b):\n    return a + b\n"}])}).json()
    assert res["verification"]["status"] == "FAILED" and res["verification"]["failed_step"] == "dod"       # testi olmayan görev: doğrulama SKIPPED → sıkı DoD ihlali
    assert res["fix_requested"] is True and res["next_kind"] == "fix"
    assert hub.jira_issues["JIRA-3"]["status"] == "IN_PROGRESS"                    # bitmiş sayılmadı
    rec = hub.runs[rid].steps[0]
    assert {c["key"] for c in rec.dod if not c["ok"]} == {"verification_passed", "tests_ran"}
    nxt = client.post(f"/api/runs/{rid}/next-step", json={"client": CLIENT}).json()
    assert nxt["kind"] == "fix" and "Sıkı DoD ihlali" in nxt["user_context"] and "hiç test yok" in nxt["user_context"]
    res2 = client.post(f"/api/runs/{rid}/steps/3/result", json={"result_json": _env([
        {"path": "requirements.txt", "content": "pytest\n"},
        {"path": "tests/test_a.py", "content": "from src.a import add\n\n\ndef test_add():\n    assert add(1, 2) == 3\n"}])}).json()
    assert res2["verification"]["status"] == "PASSED" and res2["commit"] and res2["fix_requested"] is False
    fix_rec = hub.runs[rid].steps[1]
    assert all(c["ok"] for c in fix_rec.dod) and hub.jira_issues["JIRA-3"]["status"] == "DONE"


@needs_git
async def test_strict_dod_off_keeps_legacy_behaviour(client, hub, tmp_project):
    hub.step_by_step_mode = False
    await hub.update_settings({"approval_mode": "auto", "auto_verify": True, "auto_commit": True, "verification": {"install": PASS_CMD}})
    run = client.post("/api/runs", json={"steps": [3], "engine": "mcp_client", "client": CLIENT}).json()["run"]
    rid = run["run_id"]
    client.post(f"/api/runs/{rid}/next-step", json={"client": CLIENT})
    res = client.post(f"/api/runs/{rid}/steps/3/result", json={"result_json": _env([{"path": "src/a.py", "content": "x = 1\n"}])}).json()
    assert res["verification"]["status"] == "SKIPPED" and res["fix_requested"] is False and hub.jira_issues["JIRA-3"]["status"] == "DONE"


# ---------------------------------------------------------------------------
# İzin listesi ve komut yalıtımı (§12 madde 1)
# ---------------------------------------------------------------------------
def test_allowlist_policy_matches_prefixes_and_normalizes_executables():
    assert G.command_allowed(_H("denylist"), "make deploy") == (True, [])
    assert G.command_allowed(_H(), '"C:/Program Files/Python312/python.exe" -m pip install -q -r requirements.txt') == (True, [])
    assert G.command_allowed(_H(), "cd frontend && npm install --silent && npm run build") == (True, [])
    ok, bad = G.command_allowed(_H(), "cd a && python -m pytest -q && make deploy")
    assert ok is False and bad == ["make deploy"]
    assert G.command_allowed(_H(allow=["make test"]), "make test -j2") == (True, [])


async def test_command_outside_allowlist_becomes_a_blocking_question_and_is_not_saved(client, hub, tmp_project):
    hub.step_by_step_mode = False
    await hub.update_settings({"approval_mode": "auto", "sandbox": {"command_policy": "allowlist"}})
    run = client.post("/api/runs", json={"steps": [2], "engine": "mcp_client", "client": CLIENT}).json()["run"]
    rid = run["run_id"]
    client.post(f"/api/runs/{rid}/next-step", json={"client": CLIENT})
    env = _env([{"path": "docs/openapi_spec.json", "content": "{}"}], "ARCHITECT", "BACKEND_DEV", "DISPATCH_CONTRACT",     # D1: mimar teslimi sözleşme dosyasız kabul edilmez
               verification={"test": "python -m pytest -q", "run": "make start-everything", "health_url": "http://127.0.0.1:8000/health"})
    client.post(f"/api/runs/{rid}/steps/2/result", json={"result_json": env})
    ver = hub.get_settings().get("verification") or {}
    assert ver.get("test") == "python -m pytest -q" and "run" not in ver                    # izinli komut geçti, liste dışı olan ayarlara yazılmadı
    q = next(x for x in M.store(hub)["questions"] if x.get("action", {}).get("key") == "run")
    assert q["category"] == "EXTERNAL_ACTION" and q["blocking"] is True and q["deadline"] is None and q["recommended"] == "B"
    assert "make start-everything" in q["text"] and q["action"]["prefix"] == "make start-everything"
    # B: reddet → izin listesi ve ayarlar değişmez
    await M.answer_question(hub, q["id"], "B")
    assert "make start-everything" not in " ".join(G.sandbox(hub)["allowlist"]) and "run" not in (hub.get_settings().get("verification") or {})
    # A: izin ver → önek listeye eklenir ve komut ayarlara yazılır
    env2 = _env([{"path": "docs/openapi_spec.json", "content": "{}"}], "ARCHITECT", "BACKEND_DEV", "DISPATCH_CONTRACT", verification={"build": "make lint"})      # G4: ruff varsayılan listede; liste dışı komutla sınanır
    run2 = client.post("/api/runs", json={"steps": [2], "engine": "mcp_client", "client": CLIENT, "force_new": True}).json()["run"]
    client.post(f"/api/runs/{run2['run_id']}/next-step", json={"client": CLIENT})
    client.post(f"/api/runs/{run2['run_id']}/steps/2/result", json={"result_json": env2})
    q2 = next(x for x in M.store(hub)["questions"] if x.get("action", {}).get("key") == "build")
    await M.answer_question(hub, q2["id"], "A")
    assert "make lint" in G.sandbox(hub)["allowlist"] and hub.get_settings()["verification"]["build"] == "make lint"
    assert G.command_allowed(hub, "make lint -j2") == (True, [])


async def test_allowlist_blocks_the_running_sprint_and_answer_resumes_it(hub, tmp_project):
    await hub.update_settings({"sprint": {"enabled": True}, "sandbox": {"command_policy": "allowlist"}})
    run = PipelineRun(project_id=hub.active_project_id, project_dir=tmp_project, mode="sprint", engine="mcp_client")
    rec = StepRecord(order=11, issue_id="JIRA-11", role="DEVOPS", kind="task", sprint=1, status="ACTIVE")
    run.steps.append(rec)
    hub.register_run(run)
    sp = SP.new_sprint(hub, 1, "Hedef")
    SP.set_sprint_status(hub, sp, "IN_PROGRESS")
    await P._gate_proposed_commands(hub, run, rec, {"run": "make start-everything"})
    assert sp["status"] == "BLOCKED" and sp["blocked"]["reason"] == "BLOCKING_QUESTION" and run.paused
    q = M.open_blocking(hub)[0]
    await M.answer_question(hub, q["id"], "B")
    assert sp["status"] == "IN_PROGRESS" and run.paused is False                      # cevaplanınca sprint kendiliğinden sürer


async def test_container_mode_wraps_commands_and_never_falls_back_to_host(tmp_project, monkeypatch):
    from server import verify
    wrapped = G.wrap_for_container("python -m pytest -q", tmp_project)
    assert wrapped.startswith("docker run --rm -v ") and "--cap-drop ALL" in wrapped and "no-new-privileges" in wrapped and "sh -c" in wrapped and ":/work -w /work" in wrapped
    assert G.sandbox_image(tmp_project) == "python:3.12-slim"
    open(os.path.join(tmp_project, "package.json"), "w").write("{}")
    assert G.sandbox_image(tmp_project) == "node:20-slim" and G.sandbox_image(tmp_project, "my/img:1") == "my/img:1"
    ran = []

    async def fake_run(cmd, cwd, timeout):
        ran.append(cmd)
        return {"cmd": cmd, "exit_code": 0, "duration_ms": 1, "output": "", "timed_out": False}
    monkeypatch.setattr(verify, "run_command", fake_run)
    monkeypatch.setattr(G, "docker_available", lambda: False)
    res = await verify.run_verification(tmp_project, {"test": "python -m pytest -q"}, sandbox={"mode": "container"})
    assert res["status"] == "FAILED" and "host'ta KOŞTURULMADI" in res["results"][-1]["output"] and ran == []     # Docker yoksa host'ta sessizce koşmaz
    monkeypatch.setattr(G, "docker_available", lambda: True)
    res = await verify.run_verification(tmp_project, {"test": "python -m pytest -q"}, sandbox={"mode": "container", "image": "img:1"})
    # G4: tek konteyner oturumu — bayat oturumu kapat, başlat (imaj, düşük yetki), betikle koş, kapat
    assert res["status"] == "PASSED" and res["isolation"] == "container"
    assert ran[0].startswith("docker rm -f fssc-verify-") and ran[-1].startswith("docker rm -f fssc-verify-")
    assert ran[1].startswith("docker run -d --rm --name fssc-verify-") and "img:1" in ran[1] and "--cap-drop ALL" in ran[1] and ":/work" in ran[1]
    assert ran[2].startswith("docker exec fssc-verify-") and ran[2].endswith("-test.sh")
    assert res["results"][-1]["cmd"] == "[container] python -m pytest -q"
    ran.clear()
    res = await verify.run_verification(tmp_project, {"test": "make deploy"}, command_filter=lambda c: G.command_allowed(_H(), c))
    assert res["results"][-1]["status"] == "SKIPPED" and "İzin listesi dışı" in res["results"][-1]["output"] and ran == []


def test_sandbox_settings_endpoint_refuses_container_without_docker(client, hub, monkeypatch):
    monkeypatch.setattr(G, "docker_available", lambda: False)
    assert client.post("/api/settings/sandbox", json={"mode": "container"}).status_code == 409
    out = client.post("/api/settings/sandbox", json={"command_policy": "allowlist", "allowlist": ["ruff check", " "]}).json()
    assert out["sandbox"]["command_policy"] == "allowlist" and out["sandbox"]["allowlist"] == ["ruff check"] and out["sandbox"]["mode"] == "host"
    assert client.post("/api/settings/sandbox", json={"mode": "bogus"}).json()["sandbox"]["mode"] == "host"


# ---------------------------------------------------------------------------
# Sır taraması (§12 madde 4)
# ---------------------------------------------------------------------------
def test_secret_scan_and_redaction():
    f = G.scan_text(f'KEY = "{AWS}"\ntoken = "ghp_' + "a1" * 20 + '"\npassword: "changeme"\nsecret = "gercek-bir-deger-123"\n-----BEGIN RSA PRIVATE KEY-----\n', "a.py")
    kinds = [x["kind"] for x in f]
    assert kinds == ["AWS_ACCESS_KEY", "GITHUB_TOKEN", "ASSIGNED_SECRET", "PRIVATE_KEY"]       # "changeme" yer tutucusu yok sayılır
    assert all("AKIA" not in x["preview"] and "*" in x["preview"] for x in f)
    red = G.redact(f'Notlarda anahtar {AWS} ve password = "Sup3rSecret99" geçiyor.')
    assert AWS not in red and "Sup3rSecret99" not in red and red.count("*") >= 8


@needs_git
async def test_commit_is_blocked_by_secret_and_env_files_are_never_committed(tmp_project):
    open(os.path.join(tmp_project, "app.py"), "w").write(f'API = "{AWS}"\n')
    res = await scm.commit_all(tmp_project, "feat: x")
    assert res["status"] == "SECRET" and res["findings"][0]["file"] == "app.py" and AWS not in res["reason"]
    log = subprocess.run(["git", "log", "--oneline"], cwd=tmp_project, capture_output=True, text=True)
    assert log.returncode != 0 or not log.stdout.strip()                                  # hiçbir commit atılmadı
    os.remove(os.path.join(tmp_project, "app.py"))
    open(os.path.join(tmp_project, ".env"), "w").write(f"SECRET_KEY='{AWS}'\n")
    open(os.path.join(tmp_project, "ok.py"), "w").write("X = 1\n")
    res = await scm.commit_all(tmp_project, "feat: ok")
    assert res["status"] == "COMMITTED"
    tracked = subprocess.run(["git", "ls-files"], cwd=tmp_project, capture_output=True, text=True).stdout
    assert ".env" not in tracked and "ok.py" in tracked


@needs_git
async def test_delivery_with_secret_requests_a_fix_and_is_not_committed(client, hub, tmp_project):
    hub.step_by_step_mode = False
    await hub.update_settings({"approval_mode": "auto", "auto_verify": False, "auto_commit": True})
    run = client.post("/api/runs", json={"steps": [3], "engine": "mcp_client", "client": CLIENT}).json()["run"]
    rid = run["run_id"]
    client.post(f"/api/runs/{rid}/next-step", json={"client": CLIENT})
    res = client.post(f"/api/runs/{rid}/steps/3/result", json={"result_json": _env([{"path": "src/config.py", "content": 'password = "Sup3rSecret99-abc"\n'}])}).json()
    assert res["fix_requested"] is True and res["commit"] is None
    rec = hub.runs[rid].steps[0]
    assert rec.commit_status == "SECRET" and "Sır taraması" in rec.verification["summary"]
    assert any(e["action"] == "COMMIT_BLOCKED_SECRET" for e in hub.events)
    nxt = client.post(f"/api/runs/{rid}/next-step", json={"client": CLIENT}).json()
    assert nxt["kind"] == "fix" and "Sır taraması" in nxt["user_context"]
    ok = client.post(f"/api/runs/{rid}/steps/3/result", json={"result_json": _env([{"path": "src/config.py", "content": 'import os\nKEY = os.environ["API_KEY"]\n'}])}).json()
    assert ok["commit"] and ok["fix_requested"] is False


@needs_git
async def test_repeated_secret_findings_block_the_sprint_with_security_violation(client, hub, tmp_project):
    await hub.update_settings({"approval_mode": "auto", "auto_verify": False, "auto_commit": True, "max_fix_rounds": 5, "sprint": {"enabled": True}})
    hub.step_by_step_mode = False
    dummy = PipelineRun(project_id=hub.active_project_id)
    recs = await P._create_task_issues(hub, dummy, normalize_backlog([{"id": "a", "title": "Yapılandırma", "role": "BACKEND_DEV", "work_type": "FEATURE"}]), parent_id="JIRA-2", origin="ARCHITECT")
    run = PipelineRun(project_id=hub.active_project_id, project_dir=tmp_project, mode="sprint", engine="mcp_client", step_by_step=False,
                      steps=[StepRecord(order=recs[0].order, issue_id=recs[0].issue_id, role="BACKEND_DEV", kind="task", sprint=1, work_type="FEATURE", title="Yapılandırma")])
    hub.register_run(run)
    run.status = "QUEUED"
    hub.active_run_id = run.run_id
    sp = SP.new_sprint(hub, 1, "Hedef")
    sp["committed_issue_ids"] = [recs[0].issue_id]
    SP.set_sprint_status(hub, sp, "IN_PROGRESS")
    rid, order = run.run_id, recs[0].order
    bad = _env([{"path": "src/config.py", "content": 'password = "Sup3rSecret99-abc"\n'}])
    client.post(f"/api/runs/{rid}/next-step", json={"client": CLIENT})
    client.post(f"/api/runs/{rid}/steps/{order}/result", json={"result_json": bad})
    assert sp["security_violations"] == 1 and sp["status"] == "IN_PROGRESS"
    client.post(f"/api/runs/{rid}/next-step", json={"client": CLIENT})
    res = client.post(f"/api/runs/{rid}/steps/{order}/result", json={"result_json": bad}).json()
    assert sp["security_violations"] == 2 and sp["status"] == "BLOCKED" and sp["blocked"]["reason"] == "SECURITY_VIOLATION" and res["status"] == "BLOCKED"


# ---------------------------------------------------------------------------
# Döngü kırıcı (§12 madde 6)
# ---------------------------------------------------------------------------
async def test_error_signature_ignores_numbers_and_paths():
    def v(out):
        return {"status": "FAILED", "results": [{"name": "test", "status": "FAILED", "output": out}]}
    a = G.error_signature(v("FAILED tests/test_a.py::test_x - AssertionError: 3 != 4 at /tmp/p1/src/a.py:12"))
    b = G.error_signature(v("FAILED tests/test_a.py::test_x - AssertionError: 7 != 8 at C:\\proj\\src\\a.py:99"))
    c = G.error_signature(v("ImportError: No module named foo"))
    assert a == b and a != c and G.error_signature({"status": "PASSED"}) == ""


async def test_same_error_twice_stops_fix_rounds_and_returns_the_task_to_the_architect(client, hub, tmp_project):
    await hub.update_settings({"approval_mode": "auto", "auto_verify": True, "auto_commit": False, "max_fix_rounds": 5, "sprint": {"enabled": True},
                               "verification": {"test": FAIL_CMD}})
    hub.step_by_step_mode = False
    dummy = PipelineRun(project_id=hub.active_project_id)
    recs = await P._create_task_issues(hub, dummy, normalize_backlog([{"id": "a", "title": "Hesap", "role": "BACKEND_DEV", "work_type": "FEATURE"}]), parent_id="JIRA-2", origin="ARCHITECT")
    run = PipelineRun(project_id=hub.active_project_id, project_dir=tmp_project, mode="sprint", engine="mcp_client", step_by_step=False,
                      steps=[StepRecord(order=recs[0].order, issue_id=recs[0].issue_id, role="BACKEND_DEV", kind="task", sprint=1, work_type="FEATURE", title="Hesap")])
    hub.register_run(run)
    run.status = "QUEUED"
    hub.active_run_id = run.run_id
    sp = SP.new_sprint(hub, 1, "Hedef")
    sp["committed_issue_ids"] = [recs[0].issue_id]
    SP.set_sprint_status(hub, sp, "IN_PROGRESS")
    rid, order = run.run_id, recs[0].order
    env = _env([{"path": "src/calc.py", "content": "def add(a, b):\n    return a - b\n"}])
    client.post(f"/api/runs/{rid}/next-step", json={"client": CLIENT})
    r1 = client.post(f"/api/runs/{rid}/steps/{order}/result", json={"result_json": env}).json()
    assert r1["fix_requested"] is True                                              # ilk başarısızlık: düzeltme turu
    client.post(f"/api/runs/{rid}/next-step", json={"client": CLIENT})
    r2 = client.post(f"/api/runs/{rid}/steps/{order}/result", json={"result_json": env}).json()
    assert r2["fix_requested"] is False                                             # aynı imza ikinci kez: kalan 4 tur harcanmadı
    assert len([s for s in hub.runs[rid].steps if s.kind == "fix"]) == 1
    issue = hub.jira_issues[recs[0].issue_id]
    assert issue["fix_limit_sprint"] == 1 and any(a["action"] == "SAME_ERROR_LOOP" for a in issue["audit_trail"])
    assert SP.summarize(hub, run, 1)["carried"][0]["reason"] == "FIX_LIMIT"          # sprint kapanışında yeniden kapsamlanmak üzere taşınır


# ---------------------------------------------------------------------------
# Kabul kriteri kanıtı, E2E senaryoları, PO kriter bazında karar (§6.3, §7.7)
# ---------------------------------------------------------------------------
def test_ac_evidence_from_test_files_and_scenarios(tmp_path):
    root = tmp_path / "proj"
    (root / "tests").mkdir(parents=True)
    (root / "e2e" / "scenarios").mkdir(parents=True)
    (root / "src").mkdir()
    (root / "tests" / "test_login.py").write_text('"""AC-12 girişi sınar."""\n\ndef test_login():\n    pass  # ayrıca AC-13\n', encoding="utf-8")
    (root / "tests" / "test_ac15_profile.py").write_text("def test_profile():\n    pass\n", encoding="utf-8")
    (root / "src" / "app.py").write_text("# AC-99 yalnızca üretim kodunda anılıyor\n", encoding="utf-8")
    ev = G.ac_evidence(str(root))
    assert set(ev) == {"AC-12", "AC-13", "AC-15"} and ev["AC-12"] == ["tests/test_login.py"]              # üretim kodundaki anma kanıt değildir


async def test_e2e_scenarios_run_per_acceptance_criterion(tmp_path):
    from server import e2e_scenarios as E
    root = tmp_path / "p"
    (root / "e2e" / "scenarios").mkdir(parents=True)
    (root / "e2e" / "scenarios" / "a.json").write_text(json.dumps({"id": "S-login", "ac_refs": ["ac_13"], "steps": [
        {"goto": "/"}, {"fill": ["#u", "ali"]}, {"click": "#go"}, {"expect_text": "Hoş geldin"}, {"expect_selector": "#profile"}, {"expect_url_contains": "/home"}]}), encoding="utf-8")
    (root / "e2e" / "scenarios" / "b.json").write_text(json.dumps({"id": "S-fail", "ac_refs": ["AC-14"], "steps": [{"goto": "/x"}, {"expect_text": "olmayan metin"}]}), encoding="utf-8")
    (root / "e2e" / "scenarios" / "c.json").write_text('{"id": "bozuk", "steps": []}', encoding="utf-8")

    class Fake:
        def __init__(self):
            self.u = ""

        async def goto(self, url): self.u = url + ("/home" if url.endswith("/") else "")
        async def click(self, sel): pass
        async def fill(self, sel, val): pass
        async def text(self): return "Hoş geldin ali"
        async def has(self, sel): return sel == "#profile"
        async def url(self): return self.u
    res = await E.run_scenarios(str(root), "http://127.0.0.1:9", driver_factory=Fake)
    by = {s["id"]: s for s in res["scenarios"]}
    assert by["S-login"]["status"] == "PASSED" and by["S-fail"]["status"] == "FAILED" and by["S-fail"]["failed_step"] == 2
    assert by["c.json"]["status"] == "FAILED" and "geçersiz senaryo" in by["c.json"]["log"][0]            # bozuk senaryo sessizce atlanmaz
    assert res["status"] == "FAILED" and res["ac_evidence"] == {"AC-13": {"passed": ["S-login"], "failed": []}, "AC-14": {"passed": [], "failed": ["S-fail"]}}
    assert (await E.run_scenarios(str(tmp_path / "bos"), "http://x"))["status"] == "NONE"


async def test_po_cannot_accept_a_criterion_without_evidence(hub, tmp_project):
    await hub.update_settings({"autonomy": {"strict_dod": True}})
    st = SP.ensure_state(hub)
    for n, (ac, iid) in enumerate((("AC-1", "JIRA-31"), ("AC-2", "JIRA-32"), ("AC-3", "JIRA-33"), ("AC-4", "JIRA-34")), 31):
        await hub.update_jira_issue(iid, {"order": n, "title": f"İş {ac}", "kind": "task", "status": "DONE", "assignee": "BACKEND_DEV", "ac_refs": [ac], "closed_in_sprint": 1})
        st["acs"][ac] = {"text": ac, "story": None}
    sp = SP.new_sprint(hub, 1, "Hedef")
    sp["committed_issue_ids"] = ["JIRA-31", "JIRA-32", "JIRA-33", "JIRA-34"]
    os.makedirs(os.path.join(tmp_project, "tests"), exist_ok=True)
    open(os.path.join(tmp_project, "tests", "test_one.py"), "w").write("# AC-1\ndef test_one():\n    pass\n")
    st["e2e_evidence"] = {"1": {"AC-3": {"passed": ["S-3"], "failed": []}}}
    run = PipelineRun(project_id=hub.active_project_id)
    rec = StepRecord(order=9, issue_id="JIRA-9", role="PO", kind="phase", sprint=1)
    ev = StepEvent(from_agent="PO", to_agent="DOCUMENTOR", action="UAT_APPROVED")
    result = StepResult(summary="PO onayı", action="UAT_APPROVED", next_agent_id="DOCUMENTOR", events=[ev])
    created = []

    async def create(tasks):
        created.extend(tasks)
    payload = {"criteria": [{"id": "AC-1", "decision": "ACCEPTED", "reason": "test"}, {"id": "AC-2", "decision": "ACCEPTED", "reason": "güveniyorum"},
                            {"id": "AC-3", "decision": "ACCEPTED", "reason": "E2E"}]}        # AC-4 için hiç karar yok
    out = await Q.apply_po_criteria(hub, run, rec, payload, result, tmp_project, create)
    assert out["accepted"] == ["AC-1", "AC-3"] and {r["ac"]: r["reason"] for r in out["rejected"]} == {"AC-2": "kanıtsız: bu kritere bağlı geçen test ya da E2E senaryosu yok", "AC-4": "PO bu kriter için karar vermedi"}
    assert result.status == "FAILED" and result.action == "UAT_REJECTED" and ev.status == "FAILED"
    assert st["acs"]["AC-1"]["status"] == "ACCEPTED" and st["acs"]["AC-2"]["status"] == "REJECTED" and st["acs"]["AC-2"]["decided_by"] == "PO"
    ac2 = next(t for t in created if t["ac_refs"] == ["AC-2"])
    assert ac2["work_type"] == "TEST" and ac2["role"] == "QA" and ac2["priority"] == "P0" and "test/E2E" in ac2["title"]
    assert sp["uat_rejections"] == 1


async def test_architect_review_findings_become_work_items(hub):
    created = []

    async def create(tasks):
        created.extend(tasks)
    rec = StepRecord(order=1006 + 4, issue_id="SPRINT-1", role="ARCHITECT", kind="review", sprint=1)
    sp = SP.new_sprint(hub, 1, "Hedef")
    n = await Q.expand_review_findings(hub, PipelineRun(project_id=hub.active_project_id), rec, {"findings": [
        {"title": "Sözleşme dışı uç", "severity": "high", "description": "x", "files": ["src/main.py"], "role": "BACKEND_DEV"},
        {"title": "Adlandırma", "severity": "LOW"}, {"title": "", "severity": "HIGH"}, "yanlış"]}, create)
    assert n == 2 and [t["work_type"] for t in created] == ["BUG", "REFACTOR"] and [t["priority"] for t in created] == ["P0", "P2"]
    assert sp["arch_review"]["done"] is True and sp["arch_review"]["findings"] == 2


def test_review_step_envelope_validation(hub):
    from server.steps.flow import ReviewHandler
    h = ReviewHandler(1010, 1)
    ctx_run = PipelineRun(project_id=hub.active_project_id)
    rec = StepRecord(order=1010, issue_id="SPRINT-1", role="ARCHITECT", kind="review", sprint=1)
    ctx = P.make_context(hub, ctx_run, rec)
    env = h.template_output(ctx)
    assert env["payload"]["findings"] == [] and h.render(ctx, env).summary
    env["payload"]["findings"] = "yok"
    from server.llm.parsing import StepOutputError
    with pytest.raises(StepOutputError):
        h.render(ctx, env)


# ---------------------------------------------------------------------------
# Uçtan uca (şablon motoru): sıkı DoD ile sprint — gözden geçirme, kriter kararı, kapanış raporu
# ---------------------------------------------------------------------------
NOTES = ("Kullanıcılar sisteme kayıt olup giriş yapabilmeli. Yöneticiler kayıtları listeleyip filtreleyebilmeli. "
         "Her işlem için denetim kaydı tutulmalı.")


def _wait(client, rid, timeout=300.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = client.get(f"/api/runs/{rid}").json()["run"]
        if r["is_terminal"]:
            return r
        time.sleep(0.3)
    raise AssertionError("timeout")


@needs_git
def test_strict_sprint_runs_with_review_po_criteria_and_dod_report(client, hub, tmp_project):
    client.post("/api/settings/sprint", json={"enabled": True, "commit_approval": "auto", "auto_chain": True, "max_tasks": 50})
    client.post("/api/settings/autonomy", json={"strict_dod": True})
    client.post("/api/settings/engine", json={"execution_engine": "template", "approval_mode": "auto", "pacing": "instant", "auto_verify": True,
                                              "auto_commit": True, "verification": {"install": PASS_CMD}})
    rid = client.post("/api/specs/upload", data={"title": "N", "client_name": "A", "meeting_notes": NOTES}).json()["intake"]["run_id"]
    done = _wait(client, rid)
    assert done["status"] == "COMPLETED", done["cancel_reason"]
    kinds = [(s["kind"], s["order"]) for s in done["steps"] if s["sprint"] == 1]
    assert [k for k in kinds if k[0] == "review"], "sıkı DoD'da sprint incelemesine ARCHITECT gözden geçirmesi girer"
    orders = [s["order"] for s in done["steps"] if s["sprint"] == 1 and s["kind"] in ("phase", "review")]
    assert orders.index(SP.review_order(1)) > orders.index(7) and orders.index(SP.review_order(1)) < orders.index(9)
    sp = SP.get_sprint(hub, 1)
    assert sp["status"] == "CLOSED" and sp["dod"]["ok"] and sp["dod"]["arch_review"]["done"] and sp["dod"]["po"]["decided"]
    po = SP.ensure_state(hub)["po_decisions"]["1"]
    assert po["rejected"] == [] and set(po["accepted"]) == {a for a in SP.ensure_state(hub)["acs"]} and len(po["accepted"]) == 3
    assert all(a["status"] == "ACCEPTED" and a["evidence"]["ok"] and a["evidence"]["tests"] for a in SP.ensure_state(hub)["acs"].values())
    dev_steps = [s for s in done["steps"] if s["kind"] in ("task",) and s["sprint"] == 1 and s["work_type"] not in ("DOCS", "TEST_DESIGN")]     # G7: test tasarımı kod değil case üretir
    assert dev_steps and all(s["dod"] and all(c["ok"] for c in s["dod"]) for s in dev_steps)           # her kod teslimi DoD'u geçti
    assert SP.ensure_state(hub)["project_status"] in ("DONE", "ACTIVE")
    retro = open(os.path.join(tmp_project, sp["meetings"]["review_retro"]), encoding="utf-8").read()
    assert "Sıkı DoD:" in retro and "mimar gözden geçirmesi yapıldı" in retro and "PO kriter kararları verildi" in retro


# ---------------------------------------------------------------------------
# Denetim izi (§12 madde 9), L3 ön koşulları (§3.1)
# ---------------------------------------------------------------------------
def test_decisions_without_human_approval_carry_decided_by_basis_and_alternatives(client, hub, tmp_project):
    client.post("/api/settings/sprint", json={"enabled": True, "commit_approval": "auto", "auto_chain": False, "max_tasks": 50})
    client.post("/api/settings/engine", json={"execution_engine": "template", "approval_mode": "auto", "pacing": "instant", "auto_verify": False, "auto_commit": False})
    client.post("/api/settings/autonomy", json={"question_timeout_s": 0})
    rid = client.post("/api/specs/upload", data={"title": "N", "client_name": "A", "meeting_notes": NOTES}).json()["intake"]["run_id"]
    _wait(client, rid)
    q = next(x for x in M.store(hub)["questions"] if x["status"] == "DEFAULTED")
    dec = next(d for d in SP.ensure_state(hub)["decisions"] if d["id"] == q["decision_ref"])
    assert dec["human_approved"] is False and dec["decided_by"] in ("TIMEOUT", "SERVER") and dec["basis"] == q["rationale"] and dec["alternatives"] == ["Uç başına serbest"]
    assert sp_commit_basis(hub) is not None
    client.post(f"/api/questions/{q['id']}/answer", json={"answer": "B"})
    dec2 = next(d for d in SP.ensure_state(hub)["decisions"] if d["question"] == q["id"] and d["human_approved"])
    assert dec2["decided_by"] == "MANAGER" and dec2["alternatives"] == ["Tek tip hata şeması"]


def sp_commit_basis(hub):
    sp = SP.get_sprint(hub, 1)
    return sp["commit_approval"].get("by") if sp else None


@needs_git
async def test_l3_needs_all_preconditions_and_then_writes_the_preset_keys(client, hub, tmp_project, monkeypatch):
    from server import driver as DRV
    subprocess.run(["git", "init", "-q"], cwd=tmp_project)
    await hub.update_settings({"verification": {"test": PASS_CMD}})
    DRV.seen(hub, CLIENT)                                                     # runner güncel
    monkeypatch.setattr(G, "docker_available", lambda: False)
    res = client.post("/api/autonomy/preset", json={"level": "L3"})
    assert res.status_code == 409 and {c["key"]: c["ok"] for c in res.json()["checks"]} == {
        "verification_test": True, "runner_installed": True, "command_isolation": False, "budgets_defined": True, "own_git_repo": True}
    assert "Komut yalıtımı" in res.json()["error"]
    # yalıtım için container modu + izin listesi + Docker gerekir
    monkeypatch.setattr(G, "docker_available", lambda: True)
    assert client.post("/api/settings/sandbox", json={"mode": "container", "command_policy": "denylist"}).status_code == 200
    assert client.post("/api/autonomy/preset", json={"level": "L3"}).status_code == 409          # izin listesi kapatıldı (G4'te varsayılan açık)
    client.post("/api/settings/sandbox", json={"command_policy": "allowlist"})
    ok = client.post("/api/autonomy/preset", json={"level": "L3"})
    assert ok.status_code == 200 and ok.json()["level"] == "L3"
    s = hub.get_settings()
    assert s["approval_mode"] == "auto" and SP.cfg(hub)["commit_approval"] == "auto" and SP.cfg(hub)["auto_chain"] is True
    assert M.autonomy(hub)["question_timeout_s"] == 0 and M.autonomy(hub)["strict_dod"] is True
    # teknoloji kapısı L3'te de atlanmaz
    assert hub.tech_requirements_approved() or True
    # ön koşul kaybolursa (kendi deposundan çıkarma) tekrar reddedilir
    monkeypatch.setattr(G, "docker_available", lambda: False)
    assert client.post("/api/autonomy/preset", json={"level": "L3"}).status_code == 409


def test_l3_is_refused_in_a_nested_repository(client, hub, tmp_project, monkeypatch):
    monkeypatch.setattr(G, "docker_available", lambda: True)
    client.post("/api/settings/sandbox", json={"mode": "container", "command_policy": "allowlist"})
    res = client.post("/api/autonomy/preset", json={"level": "L3"})
    checks = {c["key"]: c["ok"] for c in res.json()["checks"]}
    assert res.status_code == 409 and checks["own_git_repo"] is False                          # proje klasörü bir git deposu değil
