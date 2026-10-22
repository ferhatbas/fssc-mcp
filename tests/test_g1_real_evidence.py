"""
G1 — Gerçek kanıt: sahte yeşil yollar kapalı.

- Sıkı DoD ve Python yalıtımı varsayılan olarak açık, şablon yedeği ürün koşusunda kapalı.
- pytest ilk hatada durmaz; junit XML'den başarısız testler ad ad düzeltme bağlamına gider; tam günlük dosyada.
- Kabul kriteri kanıtı "kimlik anılması" değil, junit'te GEÇEN testtir.
- Proje bağımlılıkları projenin sanal ortamına kurulur (FS-SC'nin yorumlayıcısına değil).
- E2E: çalıştırma komutu ve sağlık adresi yoksa pano değil, FAILED (APP_NOT_CONFIGURED).
- Erişilemeyen hedef / sağlık adresinin 5xx dönmesi "geçti" sayılmaz.
- Geçersiz LLM çıktısı 3 denemeden sonra yer tutucu üretmez: adım FAILED, koşu sürer, sonuç 'with_failures'.
- QA bulguları Jira'da BUG maddesi olur; mimar incelemesi kod farkını (yamayı) görür.
"""
import asyncio
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from server import guard as G
from server import meetings as M
from server import scm as SCM
from server import verify as V
from server.telemetry import TelemetryHub

CLIENT = {"name": "pytest-g1", "version": "1"}


def _write(project: str, rel: str, content: str) -> None:
    path = os.path.join(project, *rel.split("/"))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def _env(from_agent: str, to_agent: str, intent: str, files, **payload) -> str:
    return json.dumps({
        "trace_id": "t", "from_agent": from_agent, "to_agent": to_agent, "intent": intent, "status": "SUCCESS",
        "payload": {"summary": "ok", "friendly_dialogue": "ok", "thinking": "ok", "what_doing": "ok", "what_next": "ok", "files": files, **payload},
    })


# ---------------------------------------------------------------------------
# Varsayılanlar
# ---------------------------------------------------------------------------
async def test_fresh_hub_defaults_are_strict_isolated_and_without_template_fallback(tmp_path):
    hub = TelemetryHub(registry_path=str(tmp_path / "r.json"), default_project_path=str(tmp_path / "p"), flush_delay_s=0.0)
    try:
        s = hub.get_settings()
        assert M.autonomy(hub)["strict_dod"] is True
        assert s["python_isolation"] == "venv"
        assert s["llm_fallback"] is False
        await hub.update_settings({"python_isolation": "host", "llm_fallback": True})
        assert hub.get_settings()["python_isolation"] == "host" and hub.get_settings()["llm_fallback"] is True
        await hub.update_settings({"python_isolation": "bogus"})
        assert hub.get_settings()["python_isolation"] == "host"      # geçersiz değer öncekini korur
    finally:
        await hub.aclose()


def test_scm_ignores_verify_logs_and_project_venv():
    assert ".fs-workspace/verify/" in SCM.FSSC_IGNORE_LINES and ".fs-workspace/venv/" in SCM.FSSC_IGNORE_LINES


# ---------------------------------------------------------------------------
# Doğrulama motoru
# ---------------------------------------------------------------------------
def test_pytest_command_does_not_stop_at_first_failure_and_emits_junit(tmp_project):
    cmd = V.pytest_command(tmp_project)
    assert " -x" not in cmd and "--maxfail=25" in cmd and "--junitxml=" in cmd and "junit.xml" in cmd


async def test_run_verification_keeps_full_log_and_names_failed_tests(tmp_project):
    _write(tmp_project, "requirements.txt", "")
    _write(tmp_project, "tests/test_two.py",
           "# AC-1 ve AC-2 kanıtı\n"
           "def test_ac1_passes():\n    assert True\n\n"
           "def test_ac2_fails():\n    assert 1 == 2, 'AC-2 beklenen davranış sağlanmadı'\n")
    commands = V.infer_commands(tmp_project, isolation="host")
    res = await V.run_verification(tmp_project, {"test": commands["test"]}, do_install=False, isolation="host", tag="g1")
    assert res["status"] == "FAILED" and res["failed_step"] == "test"
    assert res["tests"]["passed"] == 1 and res["tests"]["failed"] == 1
    assert [t["id"] for t in res["failed_tests"]] == ["tests/test_two.py::test_ac2_fails"]
    test_res = next(r for r in res["results"] if r["name"] == "test")
    assert test_res["log_file"] and os.path.isfile(os.path.join(tmp_project, test_res["log_file"]))
    assert os.path.isfile(V.junit_path(tmp_project))
    excerpt = V.failure_excerpt(res, limit=3000, project_dir=tmp_project)
    assert "Başarısız testler" in excerpt and "test_ac2_fails" in excerpt and "tam günlük" in excerpt
    public = V.public_summary(res)
    assert public["failed_tests"][0]["id"].endswith("test_ac2_fails") and public["results"][-1]["log_file"] and public["tests"]["failed"] == 1
    # Kabul kriteri kanıtı junit'e bağlıdır: AC-1'in testi geçti → kanıt; AC-2'nin testi kaldı → kanıt değil (aynı dosyada anılsa bile)
    ev = G.ac_evidence(tmp_project)
    assert "AC-1" in ev and "AC-2" not in ev


def test_ac_evidence_without_junit_falls_back_to_mentions(tmp_project):
    _write(tmp_project, "tests/test_x.py", "# AC-7\ndef test_a():\n    assert True\n")
    assert "AC-7" in G.ac_evidence(tmp_project)


async def test_timeout_kills_process_tree_and_marks_failed(tmp_project):
    _write(tmp_project, "sleeper.py", "import time\ntime.sleep(30)\n")
    res = await V.run_command(f"{V._py()} sleeper.py", tmp_project, timeout_s=1.5)
    assert res["timed_out"] is True and res["exit_code"] == -1 and "süreç ağacı" in res["output"]


async def test_venv_isolation_creates_project_venv_and_runs_tests_inside_it(tmp_project):
    _write(tmp_project, "requirements.txt", "")
    _write(tmp_project, "tests/test_ok.py", "import sys\n\ndef test_ok():\n    assert 'venv' in sys.prefix.lower() or 'venv' in sys.executable.lower()\n")
    cmds = V.infer_commands(tmp_project, isolation="venv")
    assert V.venv_python(tmp_project).replace("\\", "/") in cmds["test"].replace("\\", "/").replace('"', "")
    res = await V.run_verification(tmp_project, cmds, do_install=True, isolation="venv", tag="venv")
    assert os.path.isfile(V.venv_python(tmp_project)), res
    assert res["status"] == "PASSED" and res["isolation"] == "venv", res["summary"]
    assert res["tests"]["passed"] == 1


# ---------------------------------------------------------------------------
# Sağlık denetimi ve E2E
# ---------------------------------------------------------------------------
class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        code = {"/ok": 200, "/auth": 401, "/err": 500, "/missing": 404}.get(self.path, 404)
        self.send_response(code)
        self.send_header("Content-Length", "2")
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *args):  # sessiz
        pass


@pytest.fixture
def http_base():
    srv = HTTPServer(("127.0.0.1", 0), _Handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        yield f"http://127.0.0.1:{srv.server_address[1]}"
    finally:
        srv.shutdown()


async def test_health_probe_rejects_5xx_and_404_but_accepts_auth_protected(http_base):
    from server.app_runner import wait_until_up
    assert await wait_until_up(f"{http_base}/ok", 3) == 200
    assert await wait_until_up(f"{http_base}/auth", 3) == 401
    assert await wait_until_up(f"{http_base}/err", 1.5) is None
    assert await wait_until_up(f"{http_base}/missing", 1.5) is None


async def test_e2e_without_run_command_and_health_url_fails_instead_of_testing_the_dashboard(client, hub, tmp_project):
    hub.step_by_step_mode = False
    await hub.update_settings({"approval_mode": "auto", "auto_verify": True})
    run = client.post("/api/runs", json={"steps": [7], "engine": "mcp_client", "client": CLIENT}).json()["run"]
    rid = run["run_id"]
    client.post(f"/api/runs/{rid}/next-step", json={"client": CLIENT})
    done = client.get(f"/api/runs/{rid}").json()["run"]
    assert done["is_terminal"]
    step = done["steps"][0]
    assert step["status"] == "FAILED" and done["outcome"] == "with_failures" and done["failed_steps"] == 1
    summary = json.load(open(os.path.join(tmp_project, "reports", "e2e_summary.json"), encoding="utf-8"))
    assert summary["status"] == "FAILED" and summary["verdict"] == "APP_NOT_CONFIGURED"
    assert any(e["action"] == "APP_NOT_CONFIGURED" for e in hub.events)


async def test_playwright_marks_unreachable_target_failed_not_passed(tmp_path):
    from server.playwright_tester import run_playwright_e2e_tests
    res = await run_playwright_e2e_tests(target_url="http://127.0.0.1:9", test_scenario="x", project_dir=str(tmp_path), project_id="p")
    assert res["status"] in ("FAILED", "SKIPPED") and res["verdict"] != "VERIFIED_FOR_PRODUCTION"
    if res["status"] == "FAILED":
        assert res["verdict"] == "TARGET_UNREACHABLE" and res["passed_steps"] == 0


# ---------------------------------------------------------------------------
# LLM çıktısı ve kalite kapıları
# ---------------------------------------------------------------------------
async def test_invalid_output_without_fallback_fails_the_step_and_the_run_continues(client, hub, tmp_project, monkeypatch):
    import server.engine.mcp_client as m
    monkeypatch.setattr(m, "MAX_STEP_ATTEMPTS", 2)
    hub.step_by_step_mode = False
    await hub.update_settings({"approval_mode": "auto"})
    run = client.post("/api/runs", json={"steps": [1, 2], "engine": "mcp_client", "client": CLIENT}).json()["run"]
    rid = run["run_id"]
    client.post(f"/api/runs/{rid}/next-step", json={"client": CLIENT})
    first = client.post(f"/api/runs/{rid}/steps/1/result", json={"result_json": "garbage", "client": CLIENT}).json()
    assert first["status"] == "REJECTED"
    second = client.post(f"/api/runs/{rid}/steps/1/result", json={"result_json": "garbage", "client": CLIENT}).json()
    assert second["status"] == "NEXT" and second["step_failed"] is True and second["next_order"] == 2
    assert not os.path.exists(os.path.join(tmp_project, "FS-docs", "PRD.md"))      # yer tutucu PRD YAZILMADI
    r = client.get(f"/api/runs/{rid}").json()["run"]
    assert r["steps"][0]["status"] == "FAILED" and r["failed_steps"] == 1 and r["outcome"] is None    # koşu sürüyor; sonuç bitince 'with_failures'
    audits = [a["action"] for a in hub.jira_issues["JIRA-1"]["audit_trail"]]
    assert "LLM_OUTPUT_FAILED" in audits and "LLM_FALLBACK" not in audits
    assert hub.jira_issues["JIRA-1"]["status"] == "IN_PROGRESS"


async def test_qa_bugs_become_bug_issues(client, hub, tmp_project):
    hub.step_by_step_mode = False
    await hub.update_settings({"approval_mode": "auto"})
    run = client.post("/api/runs", json={"steps": [6], "engine": "mcp_client", "client": CLIENT}).json()["run"]
    rid = run["run_id"]
    client.post(f"/api/runs/{rid}/next-step", json={"client": CLIENT})
    env = _env("QA", "E2E_TESTER", "APPROVE_BUILD", [{"path": "tests/test_app.py", "content": "def test_a():\n    assert True\n"}],
               verdict="APPROVED", bugs=[{"bug_id": "BUG-QA-01", "severity": "HIGH", "issue": "Boş kullanıcı adı 500 dönüyor", "resolution": "doğrulama eklenmeli"},
                                         {"bug_id": "BUG-QA-02", "severity": "LOW", "issue": "Log satırı yanlış", "resolution": ""}])
    res = client.post(f"/api/runs/{rid}/steps/6/result", json={"result_json": env, "client": CLIENT}).json()
    assert res["status"] in ("NEXT", "RUN_COMPLETE")
    bugs = [i for i in hub.jira_issues.values() if i.get("work_type") == "BUG" and i.get("origin") == "QA"]
    assert len(bugs) == 2
    high = next(b for b in bugs if "Boş kullanıcı adı" in b["title"])
    assert high["priority"] == "P0" and high["status"] == "BACKLOG" and high["assignee"] == "BACKEND_DEV"
    assert next(b for b in bugs if "Log satırı" in b["title"])["priority"] == "P2"


async def test_architect_review_prompt_includes_the_patch(hub, tmp_project):
    from server import pipeline as P
    from server.runs import PipelineRun, StepRecord
    from server.steps.flow import ReviewHandler
    run = PipelineRun(project_id=hub.active_project_id, mode="sprint",
                      steps=[StepRecord(order=1003, issue_id="SPRINT-1", role="ARCHITECT", kind="review", sprint=1, title="inceleme")])
    ctx = P.make_context(hub, run, run.steps[0])
    setattr(ctx, "git_diff", {"base": "abcdef123456", "stat": " src/a.py | 2 +-", "patch": "diff --git a/src/a.py b/src/a.py\n+def hello():\n+    return 1\n"})
    prompt = ReviewHandler(1003, 1).build_user_prompt(ctx)
    assert "## Fark" in prompt and "+def hello():" in prompt and "## Yama" in prompt
