"""
Tam otomatik geliştirme döngüsü: backlog genişletme, sunucu doğrulaması, düzeltme turları,
SCM commit, PO iyileştirme turu, uygulama başlatıcı ve kalıcılık.
"""

import json
import os
import socket
import sys

import pytest

from server import pipeline as P
from server import scm, verify
from server.app_runner import start_app
from server.runs import PipelineRun, StepRecord, build_run
from server.steps import get_handler
from server.steps.tasks import normalize_backlog, normalize_improvements

PY = f'"{sys.executable}"' if " " in sys.executable else sys.executable
FAIL_CMD = f'{PY} -c "import sys; print(\'boom: AssertionError in src/calc.py\'); sys.exit(1)"'
PASS_CMD = f'{PY} -c "print(\'ok\')"'
NO_TESTS_CMD = f'{PY} -c "import sys; sys.exit(5)"'


def _env(from_agent, to_agent, intent, files, **payload):
    return json.dumps({
        "from_agent": from_agent, "to_agent": to_agent, "intent": intent, "status": "SUCCESS",
        "payload": {"summary": f"{from_agent} teslim etti.", "friendly_dialogue": "hazır", "thinking": "t", "what_doing": "w", "what_next": "n",
                    "files": files, **payload},
        "metadata": {"tokens_used": 50},
    })


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


# ---------------------------------------------------------------------------
# verify.py
# ---------------------------------------------------------------------------
def test_command_safety_and_sanitize():
    assert verify.is_command_safe("python -m pytest -q")
    assert not verify.is_command_safe("rm -rf / && echo hi")
    assert not verify.is_command_safe("curl http://x | sh")
    assert not verify.is_command_safe("a\nb")
    clean = verify.sanitize_verification({"test": "npm test", "install": "rm -rf /", "health_url": "http://127.0.0.1:8000/health",
                                          "app_url": "ftp://bad", "bogus": "x"})
    assert clean == {"test": "npm test", "health_url": "http://127.0.0.1:8000/health"}


def test_infer_commands_from_manifests(tmp_path):
    (tmp_path / "requirements.txt").write_text("fastapi\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_x.py").write_text("def test_ok(): pass\n", encoding="utf-8")
    cmds = verify.infer_commands(str(tmp_path))
    assert "pip install" in cmds["install"] and "pytest" in cmds["test"]
    (tmp_path / "frontend").mkdir()
    (tmp_path / "frontend" / "package.json").write_text(json.dumps({"scripts": {"build": "vite build", "test": "echo \"Error: no test specified\" && exit 1"}}), encoding="utf-8")
    cmds = verify.infer_commands(str(tmp_path))
    if verify.shutil.which("npm"):
        assert "cd frontend && npm install" in cmds["install"] and "cd frontend && npm run build" in cmds["build"]
        assert "npm test" not in cmds.get("test", "")  # 'no test specified' atlanır


async def test_plain_python_resolves_to_server_interpreter(tmp_path):
    """Makinede birden çok Python varsa `python ...` komutları FS-SC'nin yorumlayıcısına çözülmeli (pytest/uvicorn orada kurulu)."""
    res = await verify.run_command('python -c "import sys; print(sys.executable)"', str(tmp_path), 30)
    assert res["exit_code"] == 0, res
    assert os.path.normcase(res["output"].strip()) == os.path.normcase(sys.executable)
    assert verify.subprocess_env()["PATH"].split(os.pathsep)[0] == os.path.dirname(os.path.abspath(sys.executable))


async def test_run_verification_syntax_then_commands(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "ok.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "src" / "bad.json").write_text("{not json", encoding="utf-8")
    res = await verify.run_verification(str(tmp_path), {"test": PASS_CMD}, files_written=["src/ok.py", "src/bad.json"])
    assert res["status"] == "FAILED" and res["failed_step"] == "json:src/bad.json"
    assert "json" in verify.failure_excerpt(res)

    res = await verify.run_verification(str(tmp_path), {"test": FAIL_CMD}, files_written=["src/ok.py"])
    assert res["status"] == "FAILED" and res["failed_step"] == "test"
    assert "boom" in verify.failure_excerpt(res) and res["results"][0]["name"].startswith("py_compile")

    res = await verify.run_verification(str(tmp_path), {"test": NO_TESTS_CMD}, files_written=[])
    assert res["status"] == "SKIPPED"  # pytest 5: hiç test yok

    res = await verify.run_verification(str(tmp_path), {"install": PASS_CMD, "test": PASS_CMD}, files_written=[], do_install=False)
    assert res["status"] == "PASSED" and res["ran_install"] is False and [r["name"] for r in res["results"]] == ["test"]
    pub = verify.public_summary(res)
    assert pub["status"] == "PASSED" and pub["results"][0]["cmd"] == PASS_CMD


# ---------------------------------------------------------------------------
# Backlog normalizasyonu
# ---------------------------------------------------------------------------
def test_normalize_backlog_orders_dependencies_and_limits():
    raw = [
        {"id": "T-02", "title": "UI listesi", "role": "frontend", "depends_on": ["T-01"], "files": ["frontend\\src\\List.tsx"]},
        {"id": "T-01", "title": "API filtre", "role": "BACKEND_DEV", "acceptance_criteria": ["?category= çalışır"], "priority": "P0"},
        "Dokümantasyon güncelle",
        {"title": ""},
        42,
        {"id": "T-02", "title": "Tekrar id", "role": "ROBOT"},
    ]
    tasks = normalize_backlog(raw, max_tasks=3)
    assert [t["task_key"] for t in tasks] == ["T-01", "T-02", "T-03"]
    assert tasks[0]["role"] == "BACKEND_DEV" and tasks[1]["role"] == "FRONTEND_DEV" and tasks[1]["files_hint"] == ["frontend/src/List.tsx"]
    assert tasks[2]["title"] == "Dokümantasyon güncelle" and tasks[2]["role"] == "BACKEND_DEV"
    imps = normalize_improvements(["Şifre sıfırlama akışı eksik", {"title": "Harita görünümü", "role": "FRONTEND_DEV"}])
    assert [i["task_key"] for i in imps] == ["UAT-01", "UAT-02"] and imps[0]["priority"] == "P0" and imps[1]["role"] == "FRONTEND_DEV"


# ---------------------------------------------------------------------------
# Pipeline: backlog genişletme (MCP istemcisi akışı, REST ikizi ile)
# ---------------------------------------------------------------------------
def test_architect_backlog_expands_run_and_saves_verification(client, hub, tmp_project):
    hub.step_by_step_mode = False
    run = client.post("/api/runs", json={"steps": [2, 3], "engine": "mcp_client", "client": {"name": "curl", "version": "1"}}).json()["run"]
    rid = run["run_id"]
    nxt = client.post(f"/api/runs/{rid}/next-step", json={"client": {"name": "curl"}}).json()
    assert nxt["status"] == "STEP" and nxt["order"] == 2 and nxt["kind"] == "phase" and nxt["total_steps"] == 2
    assert "backlog" in nxt["output_contract"] and "verification" in nxt["output_contract"]

    env = _env("ARCHITECT", "BACKEND_DEV", "DISPATCH_CONTRACT",
               [{"path": "docs/openapi_spec.json", "content": "{\"openapi\": \"3.0.0\"}"}, {"path": "docs/ARCHITECTURE.md", "content": "# Mimari\nModüler monolit"}],
               backlog=[
                   {"id": "T-02", "title": "Etkinlik listesi ekranı", "role": "FRONTEND_DEV", "depends_on": ["T-01"], "files": ["frontend/src/Events.tsx"],
                    "acceptance_criteria": ["Liste API'den yüklenir"]},
                   {"id": "T-01", "title": "Etkinlik CRUD API", "role": "BACKEND_DEV", "description": "GET/POST /events", "acceptance_criteria": ["201 döner"]},
                   {"id": "T-03", "title": "Docker compose servisleri", "role": "DEVOPS"},
               ],
               verification={"install": "pip install -r requirements.txt", "test": "python -m pytest -q", "lint": "rm -rf /",
                             "run": "uvicorn src.main:app --port 8000", "health_url": "http://127.0.0.1:8000/health"})
    res = client.post(f"/api/runs/{rid}/steps/2/result", json={"result_json": env, "client": {"name": "curl"}}).json()
    assert res["status"] == "NEXT", res
    assert res["inserted_steps"] == 3 and res["total_steps"] == 5 and res["next_order"] == 3 and res["next_kind"] == "phase"

    r = client.get(f"/api/runs/{rid}").json()["run"]
    assert [s["order"] for s in r["steps"]] == [2, 3, 11, 12, 13]
    assert [s["role"] for s in r["steps"][2:]] == ["BACKEND_DEV", "FRONTEND_DEV", "DEVOPS"]  # bağımlılık sırası: T-01 önce
    assert r["backlog_expanded"] is True
    j11 = hub.jira_issues["JIRA-11"]
    assert j11["kind"] == "task" and j11["task_key"] == "T-01" and j11["parent_id"] == "JIRA-2" and j11["status"] == "BACKLOG"
    assert hub.jira_issues["JIRA-12"]["depends_on"] == ["JIRA-11"]
    ver = hub.get_settings()["verification"]
    assert ver["test"] == "python -m pytest -q" and "lint" not in ver and ver["health_url"].endswith("/health")
    assert any(e["action"] == "BACKLOG_PUBLISHED" for e in hub.events)

    # İskelet adımı (3) → sonra görev adımı (11): prompt görev bağlamını ve mimari artefaktı taşır
    nxt = client.post(f"/api/runs/{rid}/next-step", json={"client": {"name": "curl"}}).json()
    assert nxt["order"] == 3 and "BACKEND İSKELETİ" in nxt["user_context"]
    client.post(f"/api/runs/{rid}/steps/3/result", json={"result_json": _env("BACKEND_DEV", "FRONTEND_DEV", "BACKEND_API_EXPOSED",
                                                                              [{"path": "src/main.py", "content": "app = 1\n"}])})
    nxt = client.post(f"/api/runs/{rid}/next-step", json={"client": {"name": "curl"}}).json()
    assert nxt["status"] == "STEP" and nxt["order"] == 11 and nxt["kind"] == "task" and nxt["task_key"] == "T-01" and nxt["agent_id"] == "BACKEND_DEV"
    assert "Senior Backend" in nxt["todo_title"] and "Etkinlik CRUD API" in nxt["todo_title"]
    uc = nxt["user_context"]
    assert "GET/POST /events" in uc and "201 döner" in uc and "Mimari artefakt: docs/ARCHITECTURE.md" in uc and "src/main.py" in uc
    assert hub.jira_issues["JIRA-11"]["status"] == "IN_PROGRESS"
    # Görev teslimi dosyasız olamaz
    bad = client.post(f"/api/runs/{rid}/steps/11/result", json={"result_json": _env("BACKEND_DEV", "QA", "SUBMIT_CODE", [])}).json()
    assert bad["status"] == "REJECTED" and "files" in bad["validation_errors"][0]
    ok = client.post(f"/api/runs/{rid}/steps/11/result", json={"result_json": _env("BACKEND_DEV", "QA", "SUBMIT_CODE",
                                                                                    [{"path": "src/events.py", "content": "EVENTS = []\n"}], task_key="T-01")}).json()
    assert ok["status"] == "NEXT" and ok["next_order"] == 12 and ok["verification"] is None  # auto_verify kapalı
    assert hub.jira_issues["JIRA-11"]["status"] == "DONE"
    assert os.path.isfile(os.path.join(tmp_project, "src", "events.py"))


def test_backlog_only_written_to_jira_for_single_step_run(client, hub):
    hub.step_by_step_mode = False
    run = client.post("/api/runs", json={"steps": [2], "engine": "mcp_client", "client": {"name": "curl"}}).json()["run"]
    rid = run["run_id"]
    client.post(f"/api/runs/{rid}/next-step", json={"client": {"name": "curl"}})
    env = _env("ARCHITECT", "BACKEND_DEV", "DISPATCH_CONTRACT", [{"path": "docs/openapi_spec.json", "content": "{}"}],
               backlog=[{"id": "T-01", "title": "Tek görev", "role": "BACKEND_DEV"}])
    res = client.post(f"/api/runs/{rid}/steps/2/result", json={"result_json": env}).json()
    assert res["status"] == "RUN_COMPLETE" and res["inserted_steps"] == 0
    assert hub.jira_issues["JIRA-11"]["kind"] == "task" and hub.runs[rid].backlog_expanded is False
    # Sonradan yalnızca bu görevi koşmak mümkün (order 11)
    run2 = build_run(hub.active_project_id, hub.default_project_path, hub.get_jira_issues(), [11], engine="mcp_client")
    assert run2.steps[0].kind == "task" and run2.steps[0].title == "Tek görev"


# ---------------------------------------------------------------------------
# Pipeline: doğrulama → düzeltme turu → limit; geçince commit
# ---------------------------------------------------------------------------
async def test_verification_failure_opens_bounded_fix_rounds(client, hub, tmp_project):
    hub.step_by_step_mode = False
    await hub.update_settings({"approval_mode": "auto", "auto_verify": True, "auto_commit": False, "max_fix_rounds": 2, "verification": {"test": FAIL_CMD}})
    run = client.post("/api/runs", json={"steps": [3], "engine": "mcp_client", "client": {"name": "curl"}}).json()["run"]
    rid = run["run_id"]
    client.post(f"/api/runs/{rid}/next-step", json={"client": {"name": "curl"}})
    res = client.post(f"/api/runs/{rid}/steps/3/result", json={"result_json": _env("BACKEND_DEV", "FRONTEND_DEV", "BACKEND_API_EXPOSED",
                                                                                    [{"path": "src/calc.py", "content": "def add(a, b):\n    return a - b\n"}])}).json()
    assert res["status"] == "NEXT" and res["fix_requested"] is True and res["next_kind"] == "fix" and res["next_order"] == 3
    assert res["verification"]["status"] == "FAILED" and res["verification"]["failed_step"] == "test"
    assert "Düzeltme adımı eklendi" in res["message"]
    r = hub.runs[rid]
    assert [(s.order, s.kind, s.fix_round) for s in r.steps] == [(3, "phase", 0), (3, "fix", 1)]
    assert hub.jira_issues["JIRA-3"]["status"] == "IN_PROGRESS"
    assert any(e["action"] == "VERIFICATION_FAILED" and e["from_agent"] == "QA" for e in hub.events)
    assert any(e["action"] == "REPORT_BUG" and e["to_agent"] == "BACKEND_DEV" for e in hub.events)
    assert hub.agents["BACKEND_DEV"]["status"] == "BUG_FIX"

    nxt = client.post(f"/api/runs/{rid}/next-step", json={"client": {"name": "curl"}}).json()
    assert nxt["status"] == "STEP" and nxt["order"] == 3 and nxt["kind"] == "fix" and nxt["fix_round"] == 1 and nxt["agent_id"] == "BACKEND_DEV"
    assert "düzeltme 1" in nxt["todo_title"]
    assert "boom: AssertionError" in nxt["user_context"] and "Mevcut dosya: src/calc.py" in nxt["user_context"] and "return a - b" in nxt["user_context"]

    # 1. düzeltme de kalır → 2. tur
    res = client.post(f"/api/runs/{rid}/steps/3/result", json={"result_json": _env("BACKEND_DEV", "QA", "SUBMIT_FIX",
                                                                                    [{"path": "src/calc.py", "content": "def add(a, b):\n    return a + b\n"}])}).json()
    assert res["fix_requested"] is True and hub.runs[rid].steps[-1].fix_round == 2
    client.post(f"/api/runs/{rid}/next-step", json={"client": {"name": "curl"}})
    # 2. düzeltme de kalır → limit: adım FAILED, koşu yine de ilerler (biter)
    res = client.post(f"/api/runs/{rid}/steps/3/result", json={"result_json": _env("BACKEND_DEV", "QA", "SUBMIT_FIX",
                                                                                    [{"path": "src/calc.py", "content": "def add(a, b):\n    return a + b  # v3\n"}])}).json()
    assert res["status"] == "RUN_COMPLETE" and res["fix_requested"] is False
    assert "düzeltme hakkı bitti" in res["message"]
    assert hub.runs[rid].status == "COMPLETED" and hub.runs[rid].fix_rounds_total == 2
    audits = [a["action"] for a in hub.jira_issues["JIRA-3"]["audit_trail"]]
    assert "FIX_REQUESTED" in audits and "FIX_LIMIT_REACHED" in audits
    # G1: düzeltme hakkı biten son adım kayıtta da FAILED görünür (DONE değil); koşu "tamamlandı ama hatalı" sonucunu verir
    statuses = [s.status for s in hub.runs[rid].steps]
    assert statuses[-1] == "FAILED" and all(s == "DONE" for s in statuses[:-1])
    done = client.get(f"/api/runs/{rid}").json()["run"]
    assert done["outcome"] == "with_failures" and done["failed_steps"] == 1


async def test_syntax_error_is_caught_without_test_command(client, hub, tmp_project):
    hub.step_by_step_mode = False
    await hub.update_settings({"approval_mode": "auto", "auto_verify": True, "auto_commit": False, "max_fix_rounds": 1, "verification": {}})
    run = client.post("/api/runs", json={"steps": [3], "engine": "mcp_client", "client": {"name": "curl"}}).json()["run"]
    rid = run["run_id"]
    client.post(f"/api/runs/{rid}/next-step", json={"client": {"name": "curl"}})
    res = client.post(f"/api/runs/{rid}/steps/3/result", json={"result_json": _env("BACKEND_DEV", "FRONTEND_DEV", "BACKEND_API_EXPOSED",
                                                                                    [{"path": "src/broken.py", "content": "def x(:\n  pass\n"}])}).json()
    assert res["fix_requested"] is True and res["verification"]["failed_step"].startswith("py_compile:src/broken.py")
    client.post(f"/api/runs/{rid}/next-step", json={"client": {"name": "curl"}})
    res = client.post(f"/api/runs/{rid}/steps/3/result", json={"result_json": _env("BACKEND_DEV", "QA", "SUBMIT_FIX",
                                                                                    [{"path": "src/broken.py", "content": "def x():\n    pass\n"}])}).json()
    assert res["status"] == "RUN_COMPLETE" and res["verification"]["status"] == "SKIPPED"  # sözdizimi geçti, test komutu yok


@pytest.mark.skipif(not scm.git_available(), reason="git yok")
async def test_passing_verification_commits_via_scm(client, hub, tmp_project):
    hub.step_by_step_mode = False
    await hub.update_settings({"approval_mode": "auto", "auto_verify": True, "auto_commit": True, "verification": {"test": PASS_CMD}})
    run = client.post("/api/runs", json={"steps": [3], "engine": "mcp_client", "client": {"name": "curl"}}).json()["run"]
    rid = run["run_id"]
    client.post(f"/api/runs/{rid}/next-step", json={"client": {"name": "curl"}})
    res = client.post(f"/api/runs/{rid}/steps/3/result", json={"result_json": _env("BACKEND_DEV", "FRONTEND_DEV", "BACKEND_API_EXPOSED",
                                                                                    [{"path": "src/main.py", "content": "app = 1\n"}])}).json()
    assert res["status"] == "RUN_COMPLETE" and res["verification"]["status"] == "PASSED" and res["commit"]
    assert hub.runs[rid].steps[0].commit == res["commit"]
    assert os.path.isdir(os.path.join(tmp_project, ".git")) and os.path.isfile(os.path.join(tmp_project, ".gitignore"))
    log = await scm.recent_log(tmp_project)
    assert log and log[0].startswith(res["commit"]) and "feat(JIRA-3)" in log[0]
    assert any(e["action"] == "COMMITTED" and e["from_agent"] == "SCM" for e in hub.events)
    assert any(a["action"] == "COMMITTED" for a in hub.jira_issues["JIRA-3"]["audit_trail"])


@pytest.mark.skipif(not scm.git_available(), reason="git yok")
async def test_scm_guards(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "a.txt").write_text("a", encoding="utf-8")
    first = await scm.commit_all(str(repo), "feat(JIRA-1): ilk")
    assert first["status"] == "COMMITTED" and first["created_repo"] is True and first["hash"]
    again = await scm.commit_all(str(repo), "feat(JIRA-1): tekrar")
    assert again["status"] == "NOTHING"
    nested = repo / "sub"
    nested.mkdir()
    (nested / "b.txt").write_text("b", encoding="utf-8")
    res = await scm.commit_all(str(nested), "feat: iç içe")
    assert res["status"] == "SKIPPED" and "başka bir deponun altında" in res["reason"]
    assert scm.commit_message("fix", "JIRA-11", "Liste", 2) == "fix(JIRA-11): Liste (düzeltme 2)"


# ---------------------------------------------------------------------------
# Pipeline: PO reddi → iyileştirme turu (görevler + QA/UAT yeniden), tur sınırı
# ---------------------------------------------------------------------------
def test_po_rejection_opens_improvement_round_once(client, hub, tmp_project):
    hub.step_by_step_mode = False
    run = client.post("/api/runs", json={"steps": [6, 9, 10], "engine": "mcp_client", "client": {"name": "curl"}}).json()["run"]
    rid = run["run_id"]
    client.post(f"/api/runs/{rid}/next-step", json={"client": {"name": "curl"}})
    client.post(f"/api/runs/{rid}/steps/6/result", json={"result_json": _env("QA", "E2E_TESTER", "APPROVE_BUILD",
                                                                              [{"path": "docs/QA_REPORT.md", "content": "ok"}], verdict="APPROVED")})
    nxt = client.post(f"/api/runs/{rid}/next-step", json={"client": {"name": "curl"}}).json()
    assert nxt["order"] == 9 and "kalan iyileştirme turu: 1" in nxt["user_context"]
    rejected = _env("PO", "PM", "UAT_REJECTED", [{"path": "docs/uat/acceptance_criteria.md", "content": "# UAT\nRED"}],
                    uat_status="REJECTED", score=55,
                    improvements=[{"title": "Şifre sıfırlama akışı", "role": "BACKEND_DEV", "acceptance_criteria": ["E-posta ile sıfırlama"]},
                                  "Etkinlik haritası görünümü"])
    res = client.post(f"/api/runs/{rid}/steps/9/result", json={"result_json": rejected}).json()
    assert res["status"] == "NEXT" and res["inserted_steps"] == 4 and res["next_kind"] == "task"
    r = hub.runs[rid]
    assert [(s.order, s.kind, s.round) for s in r.steps] == [(6, "phase", 1), (9, "phase", 1), (11, "task", 2), (12, "task", 2), (6, "phase", 2), (9, "phase", 2), (10, "phase", 1)]
    assert r.uat_round == 1
    # UAT reddedildi: PO maddesi DONE görünmez (ret kaydı denetim izinde), iyileştirme turundan sonra yeniden değerlendirilir
    assert hub.jira_issues["JIRA-9"]["status"] != "DONE"
    assert hub.jira_issues["JIRA-9"]["audit_trail"][-1]["action"] == "UAT_REJECTED"
    j11 = hub.jira_issues["JIRA-11"]
    assert j11["parent_id"] == "JIRA-9" and j11["issue_type"] == "FEATURE" and j11["task_key"] == "UAT-01" and j11["priority"] == "P0"
    assert any(e["action"] == "REQUEST_ENHANCEMENT" and e["from_agent"] == "PO" for e in hub.events)

    # İyileştirme görevleri + QA 2. tur
    for order in (11, 12):
        nxt = client.post(f"/api/runs/{rid}/next-step", json={"client": {"name": "curl"}}).json()
        assert nxt["order"] == order and nxt["kind"] == "task"
        client.post(f"/api/runs/{rid}/steps/{order}/result", json={"result_json": _env("BACKEND_DEV", "QA", "SUBMIT_CODE", [{"path": f"src/f{order}.py", "content": "x=1\n"}])})
    nxt = client.post(f"/api/runs/{rid}/next-step", json={"client": {"name": "curl"}}).json()
    assert nxt["order"] == 6 and "Koşu özeti" in nxt["user_context"] and "src/f11.py" in nxt["user_context"]
    client.post(f"/api/runs/{rid}/steps/6/result", json={"result_json": _env("QA", "E2E_TESTER", "APPROVE_BUILD", [{"path": "docs/QA_REPORT.md", "content": "ok2"}])})
    nxt = client.post(f"/api/runs/{rid}/next-step", json={"client": {"name": "curl"}}).json()
    assert nxt["order"] == 9 and "İyileştirme turu hakkı kalmadı" in nxt["user_context"]
    # İkinci red: tur hakkı yok → görevler yalnızca Jira'ya yazılır, koşu docs (10) ile devam eder
    res = client.post(f"/api/runs/{rid}/steps/9/result", json={"result_json": rejected}).json()
    assert res["status"] == "NEXT" and res["inserted_steps"] == 0 and res["next_order"] == 10
    assert any(a["action"] == "UAT_LIMIT_REACHED" for a in hub.jira_issues["JIRA-9"]["audit_trail"])
    assert hub.jira_issues["JIRA-13"]["parent_id"] == "JIRA-9"


# ---------------------------------------------------------------------------
# Şablon motoru: düzeltme/görev adımları çevrimdışı da koşar; kalıcılık
# ---------------------------------------------------------------------------
def test_task_and_fix_records_roundtrip():
    run = PipelineRun(project_id="p", steps=[StepRecord(order=11, issue_id="JIRA-11", role="BACKEND_DEV", kind="task", title="x",
                                                        verification={"status": "FAILED"}, commit="abc123", fix_round=0)])
    run.insert_after_cursor([StepRecord(order=11, issue_id="JIRA-11", role="BACKEND_DEV", kind="fix", fix_round=1)])
    run.uat_round, run.backlog_expanded = 1, True
    d = run.to_dict()
    back = PipelineRun.from_dict(d)
    assert [s.kind for s in back.steps] == ["task", "fix"] and back.steps[0].commit == "abc123" and back.steps[1].fix_round == 1
    assert back.uat_round == 1 and back.backlog_expanded is True and d["progress"]["fixes"] == 1 and d["progress"]["current_index"] == 0
    assert run.files_written() == []
    old = PipelineRun.from_dict({"project_id": "p", "steps": [{"order": 1, "issue_id": "JIRA-1", "role": "PM"}]})
    assert old.steps[0].kind == "phase"  # eski kayıtlar


def test_task_handler_template_and_registry():
    issue = {"id": "JIRA-11", "kind": "task", "title": "Görev", "assignee": "FRONTEND_DEV", "task_key": "T-07"}
    h = get_handler(11, issue)
    assert h.agent_id == "FRONTEND_DEV" and h.kind == "task" and h.verify_after and h.commit_after
    fix = get_handler(11, issue, StepRecord(order=11, issue_id="JIRA-11", role="BACKEND_DEV", kind="fix", fix_round=2))
    assert fix.kind == "fix" and fix.fix_round == 2 and fix.agent_id == "BACKEND_DEV" and fix.action == "SUBMIT_FIX"
    assert get_handler(3).agent_id == "BACKEND_DEV" and get_handler(3).kind if hasattr(get_handler(3), "kind") else True


# ---------------------------------------------------------------------------
# Uygulama başlatıcı (E2E adımı için)
# ---------------------------------------------------------------------------
async def test_app_runner_starts_waits_and_stops(tmp_path):
    port = _free_port()
    res = await start_app(str(tmp_path), f"{PY} -m http.server {port} --bind 127.0.0.1", f"http://127.0.0.1:{port}/", timeout_s=30)
    assert res["ok"] is True and res["status"] == 200 and res["app"].alive
    await res["app"].stop()
    assert not res["app"].alive
    bad = await start_app(str(tmp_path), f"{PY} -c \"import sys; sys.exit(3)\"", f"http://127.0.0.1:{_free_port()}/", timeout_s=3)
    assert bad["ok"] is False and "yanıt vermedi" in bad["error"]


async def test_settings_accept_lifecycle_keys(hub):
    s = await hub.update_settings({"auto_verify": False, "max_fix_rounds": 99, "max_uat_rounds": "2", "verification": {"test": "pytest", "run": "rm -rf /"}})
    assert s["auto_verify"] is False and s["max_fix_rounds"] == 50 and s["max_uat_rounds"] == 2
    assert s["verification"] == {"test": "pytest"}
