"""Proje klasör düzeni (talimat: meta-repo-setup.md): kökte `apps/<rol>/`, `devops/`, `docs/`; tek repo; düzen ayarlardan tanımlanır.

Kapsam: ayar modeli, yol kuralları (taşıma / doğrulama), ajan istemi, şablon motoru koşusunun düzene uyması, LLM teslimlerinin denetimi,
doğrulama komutlarının apps/<rol> manifestlerini bulması, ayar ve göç uçları (git mv, durum yollarının çevrilmesi, doğrulama komutu öneki).
Düz düzen (ayar yok) davranışı mevcut testlerle (test_paths, test_lifecycle ...) korunur.
"""

import json
import os
import subprocess
import time

import pytest

from server import layout as LAY
from server.runs import PipelineRun, StepRecord

APPS = LAY.sanitize_layout({})


# ---------------------------------------------------------------------------
# Ayar modeli
# ---------------------------------------------------------------------------
def test_defaults_and_absent_setting_means_flat():
    assert APPS["mode"] == "apps" and APPS["apps_dir"] == "apps" and APPS["devops_dir"] == "devops" and APPS["docs_dir"] == "docs"
    assert APPS["roles"] == {"backend": "backend", "web": "web", "mobile": "mobile", "admin": "admin"} and APPS["enforce"] is True
    assert LAY.layout_of({})["mode"] == "flat" and not LAY.is_apps(LAY.layout_of(None))        # ayar yok: eski projeler aynen çalışır
    assert LAY.layout_of({"project_layout": {"mode": "apps"}})["mode"] == "apps"
    assert LAY.docs_setting({"docs_root": "FS-docs"}) == "FS-docs"                                # düz düzende docs_root ayarı
    assert LAY.docs_setting({"project_layout": {"mode": "apps", "docs_dir": "belgeler"}}) == "belgeler"


def test_sanitize_rejects_unsafe_names_and_resolves_conflicts():
    bad = LAY.sanitize_layout({"mode": "x", "apps_dir": "../x", "devops_dir": "a/b", "docs_dir": ".git", "roles": {"Backend": "ok", "web": "a b", "1x": "y"}})
    assert bad["mode"] == "apps" and bad["apps_dir"] == "apps" and bad["devops_dir"] == "devops" and bad["docs_dir"] == "docs"
    assert bad["roles"] == {"backend": "ok", "web": "web"}                                       # geçersiz klasör adı rol adına döner, geçersiz rol atılır
    clash = LAY.sanitize_layout({"apps_dir": "src", "devops_dir": "SRC", "docs_dir": "src/docs"})
    assert len({clash[k].split("/")[0].lower() for k in ("apps_dir", "devops_dir", "docs_dir")}) == 3        # üç kök klasör birbirinden farklı
    custom = LAY.sanitize_layout({"apps_dir": "services", "devops_dir": "ops", "docs_dir": "documentation/main", "roles": {"api": "api", "ui": "frontend"}, "enforce": False})
    assert custom["apps_dir"] == "services" and custom["docs_dir"] == "documentation/main" and custom["roles"] == {"api": "api", "ui": "frontend"} and custom["enforce"] is False
    assert LAY.sanitize_layout({"mode": "flat"})["mode"] == "flat"


def test_default_layout_for_new_and_populated_folders(tmp_path):
    fresh = tmp_path / "fresh"
    fresh.mkdir()
    assert LAY.default_layout_for(str(fresh))["mode"] == "apps"                                  # boş klasör: önerilen düzen
    (tmp_path / "old").mkdir()
    (tmp_path / "old" / "package.json").write_text("{}", encoding="utf-8")
    assert LAY.default_layout_for(str(tmp_path / "old"))["mode"] == "flat"                        # ürün dosyası var: dayatılmaz
    (tmp_path / "ws").mkdir()
    (tmp_path / "ws" / ".fs-workspace").mkdir()
    assert LAY.default_layout_for(str(tmp_path / "ws"))["mode"] == "flat"                         # mevcut FS-SC projesi


# ---------------------------------------------------------------------------
# Yol kuralları
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("path,role,expected", [
    ("src/main.py", "BACKEND_DEV", "apps/backend/src/main.py"),
    ("package.json", "BACKEND_DEV", "apps/backend/package.json"),
    ("tests/test_app.py", "QA", "apps/backend/tests/test_app.py"),
    ("frontend/src/App.tsx", "FRONTEND_DEV", "apps/web/src/App.tsx"),
    ("src/App.tsx", "FRONTEND_DEV", "apps/web/src/App.tsx"),
    ("src/screens/Home.tsx", "MOBILE_DEV", "apps/mobile/src/screens/Home.tsx"),
    ("server/index.js", "BACKEND_DEV", "apps/backend/index.js"),
    ("Dockerfile", "DEVOPS", "devops/Dockerfile"),
    ("docker-compose.yml", "DEVOPS", "devops/docker-compose.yml"),
    ("k8s/deploy.yaml", "DEVOPS", "devops/k8s/deploy.yaml"),
    ("deploy.sh", "DEVOPS", "devops/deploy.sh"),
    ("reports/e2e_summary.json", "E2E_TESTER", "docs/reports/e2e_summary.json"),
    ("README.md", "DOCUMENTOR", "README.md"),
    ("CHANGELOG.md", "DOCUMENTOR", "CHANGELOG.md"),
    (".github/workflows/ci.yml", "DEVOPS", ".github/workflows/ci.yml"),
    ("docs/PRD.md", "PM", "docs/PRD.md"),
    ("apps/backend/src/x.ts", "BACKEND_DEV", "apps/backend/src/x.ts"),
    ("devops/Dockerfile", "DEVOPS", "devops/Dockerfile"),
])
def test_relocate_maps_flat_paths_to_the_layout(path, role, expected):
    assert LAY.relocate(APPS, path, role, "docs") == expected
    assert LAY.violations(APPS, [expected], "docs", role) == []                                  # taşınan yol düzene uyar


def test_violations_name_the_suggested_path_and_flat_layout_is_unrestricted():
    msgs = LAY.violations(APPS, ["src/main.ts", "docs/PRD.md", "README.md", "apps/other/x.ts", "apps/x.ts"], "docs", "BACKEND_DEV")
    text = "\n".join(msgs)
    assert len(msgs) == 3 and "apps/backend/src/main.ts" in text and "apps/other/x.ts" in text and "apps/x.ts" in text
    assert "docs/PRD.md" not in text and "README.md" not in text
    assert LAY.violations(LAY.flat_layout(), ["src/main.ts"], "FS-docs") == []
    assert LAY.relocate(LAY.flat_layout(), "src/main.ts", "BACKEND_DEV", "FS-docs") == "src/main.ts"


def test_custom_names_flow_through_paths_and_prompt():
    lay = LAY.sanitize_layout({"apps_dir": "services", "devops_dir": "ops", "docs_dir": "documentation", "roles": {"backend": "api", "web": "ui"}})
    assert LAY.relocate(lay, "src/main.ts", "BACKEND_DEV", "documentation") == "services/api/src/main.ts"
    assert LAY.relocate(lay, "frontend/a.tsx", "FRONTEND_DEV", "documentation") == "services/ui/a.tsx"
    assert LAY.relocate(lay, "Dockerfile", "DEVOPS", "documentation") == "ops/Dockerfile"
    text = LAY.prompt_section(lay, "documentation")
    assert "services/<uygulama>/" in text and "`ops/`" in text and "`documentation/`" in text and "backend → `services/api/`" in text
    assert "sunucuca reddedilir" in text and "cd services/api && npm test" in text
    assert "reddedilir" not in LAY.prompt_section({**lay, "enforce": False}, "documentation")
    assert LAY.prompt_section(LAY.flat_layout(), "FS-docs") == ""


def test_relocate_envelope_resolves_tokens_and_moves_current_file():
    env = {"payload": {"files": [{"path": "<docs>/PRD.md", "content": "x"}, {"path": "src/main.py", "content": "y"}, {"path": "Dockerfile", "content": "z"}]},
           "metadata": {"current_file": "src/main.py"}}
    moved = LAY.relocate_envelope(APPS, env, "BACKEND_DEV", "docs", resolve=lambda v: v.replace("<docs>", "docs"))
    assert moved == 2 and [f["path"] for f in env["payload"]["files"]] == ["docs/PRD.md", "apps/backend/src/main.py", "devops/Dockerfile"]
    assert env["metadata"]["current_file"] == "apps/backend/src/main.py"


# ---------------------------------------------------------------------------
# Doğrulama komutları apps/<rol> manifestlerini bulur
# ---------------------------------------------------------------------------
def test_infer_commands_finds_manifests_under_apps(tmp_path, monkeypatch):
    from server import verify as V
    monkeypatch.setattr(V.shutil, "which", lambda name: f"/bin/{name}")
    (tmp_path / "apps" / "backend").mkdir(parents=True)
    (tmp_path / "apps" / "backend" / "package.json").write_text(json.dumps({"scripts": {"build": "tsc", "test": "jest"}}), encoding="utf-8")
    (tmp_path / "apps" / "api" / "tests").mkdir(parents=True)
    (tmp_path / "apps" / "api" / "requirements.txt").write_text("pytest\n", encoding="utf-8")
    (tmp_path / "devops" / "tools").mkdir(parents=True)
    (tmp_path / "devops" / "tools" / "package.json").write_text("{}", encoding="utf-8")            # apps dışı klasörde ikinci seviye taranmaz
    cmds = V.infer_commands(str(tmp_path))
    assert "cd apps/backend && npm install" in cmds["install"] and "cd apps/api && " in cmds["install"]
    assert "cd apps/backend && npm run build" in cmds["build"] and "cd apps/backend && npm test" in cmds["test"] and "cd apps/api && " in cmds["test"]
    assert "devops" not in cmds["install"] and "tools" not in cmds["install"]
    assert V.infer_commands(str(tmp_path), app_roots=("apps",)) == cmds
    (tmp_path / "services" / "web").mkdir(parents=True)
    (tmp_path / "services" / "web" / "package.json").write_text(json.dumps({"scripts": {"test": "vitest"}}), encoding="utf-8")
    assert "cd services/web && npm test" in V.infer_commands(str(tmp_path), app_roots=("services",))["test"]


def test_multi_folder_commands_return_to_the_root_between_folders(tmp_path, monkeypatch):
    """`cd` kabukta kalıcıdır: `cd apps/a && x && cd apps/b && y` ikinci `cd`yi yanlış yerden çözerdi (apps düzeninde iki uygulama olağandır)."""
    import asyncio
    from server import verify as V
    for name in ("a", "b"):
        (tmp_path / "apps" / name).mkdir(parents=True)
    chain = V._chain([("apps/a", "python -c \"open('../../a.txt', 'w').write('1')\""), ("apps/b", "python -c \"open('../../b.txt', 'w').write('2')\"")])
    assert chain.startswith("cd apps/a && ") and chain.count("&& cd ../.. && cd apps/b && ") == 1
    res = asyncio.run(V.run_command(chain, str(tmp_path), 60.0))
    assert res["exit_code"] == 0, res
    assert (tmp_path / "a.txt").read_text() == "1" and (tmp_path / "b.txt").read_text() == "2"          # iki klasörde de koştu
    assert V._chain([("apps/a", "x")]) == "cd apps/a && x" and V._chain([(".", "x"), ("sub", "y")]) == "x && cd sub && y"
    assert V._cd_back("apps/backend") == "../.." and V._cd_back("web") == ".."
    monkeypatch.setattr(V.shutil, "which", lambda name: f"/bin/{name}")
    (tmp_path / "apps" / "a" / "requirements.txt").write_text("pytest\n", encoding="utf-8")
    (tmp_path / "apps" / "b" / "package.json").write_text("{}", encoding="utf-8")
    install = V.infer_commands(str(tmp_path))["install"]
    assert install == f"cd apps/a && {V._py(str(tmp_path))} -m pip install -q -r requirements.txt && cd ../.. && cd apps/b && npm install --silent --no-audit --no-fund"


def test_saved_root_commands_are_adapted_to_the_app_folders(tmp_path, monkeypatch):
    """Şablonun/mimarın kökte yazdığı komutlar apps düzeninde koşamaz (kökte requirements.txt yok): sunucunun çıkardığı `cd`li komut kullanılır."""
    from server import verify as V
    monkeypatch.setattr(V.shutil, "which", lambda name: f"/bin/{name}")
    backend = tmp_path / "apps" / "backend"
    (backend / "tests").mkdir(parents=True)
    (backend / "requirements.txt").write_text("pytest\n", encoding="utf-8")
    (backend / "tests" / "test_a.py").write_text("def test_a():\n    assert True\n", encoding="utf-8")
    saved = {"install": "python -m pip install -q -r requirements.txt", "test": "python -m pytest -q", "build": "npm run build",
             "lint": "make lint", "run": "python -m uvicorn src.main:app", "health_url": "http://127.0.0.1:8000/health"}
    cmds = V.effective_commands(str(tmp_path), "host", saved)
    assert cmds["install"].startswith("cd apps/backend && ") and "pip install -q -r requirements.txt" in cmds["install"]
    assert cmds["test"].startswith("cd apps/backend && ") and "--junitxml" in cmds["test"]              # sunucunun junit'li pytest komutu
    assert "build" not in cmds                                                                          # karşılığı yok, kökte package.json yok: koşamaz, atlanır
    assert cmds["lint"] == "make lint"                                                                  # çıkarsama bilmediği komuta dokunulmaz
    assert V.effective_commands(str(tmp_path), "host", {"test": "cd apps/backend && python -m pytest -x"})["test"] == "cd apps/backend && python -m pytest -x"
    assert V.effective_commands(str(tmp_path), "host", {"test": "npm --prefix apps/web test"})["test"] == "npm --prefix apps/web test"
    (tmp_path / "requirements.txt").write_text("pytest\n", encoding="utf-8")                           # kökte manifest var (düz düzen): kayıtlı komut kazanır
    assert V.effective_commands(str(tmp_path), "host", saved)["install"] == "python -m pip install -q -r requirements.txt"
    assert V._first_tool('"C:/Py 312/python.exe" -m pytest') == "python" and V._first_tool("python3.12 -m pip") == "python" and V._first_tool("cargo test") == "cargo"


def test_template_architect_verification_is_prefixed_in_apps_layout(client, hub, tmp_project):
    _set_layout(client, hub)
    hub.step_by_step_mode = False
    res = client.post("/api/runs", json={"steps": [1, 2, 3], "engine": "template", "step_by_step": False, "prompt": "Test"})
    assert _wait_done(client, res.json()["run"]["run_id"])["status"] == "COMPLETED"
    ver = hub.get_settings()["verification"]
    assert ver["install"] == "cd apps/backend && python -m pip install -q -r requirements.txt"
    assert ver["test"] == "cd apps/backend && python -m pytest -q" and ver["run"].startswith("cd apps/backend && python -m uvicorn")
    assert ver["health_url"] == "http://127.0.0.1:8000/health"                                           # adres öneki almaz
    from server import pipeline as P
    cmds = P.verification_commands(hub, tmp_project)
    assert cmds["install"].startswith("cd apps/backend && ") and cmds["test"].startswith("cd apps/backend && ")


def test_container_image_and_dockerfile_are_found_under_the_layout(tmp_path):
    from server import guard as G
    (tmp_path / "apps" / "backend").mkdir(parents=True)
    (tmp_path / "apps" / "backend" / "package.json").write_text("{}", encoding="utf-8")
    (tmp_path / "devops").mkdir()
    (tmp_path / "devops" / "Dockerfile").write_text("FROM node:20\n", encoding="utf-8")
    assert G.sandbox_image(str(tmp_path)) == "node:20-slim" and G.sandbox_image(str(tmp_path), "custom:1") == "custom:1"
    assert G.find_dockerfile(str(tmp_path)) == "devops/Dockerfile"
    (tmp_path / "Dockerfile").write_text("FROM x\n", encoding="utf-8")
    assert G.find_dockerfile(str(tmp_path)) == "Dockerfile"


# ---------------------------------------------------------------------------
# Şablon motoru koşusu apps/devops/docs düzenine uyar; düz düzen bozulmaz
# ---------------------------------------------------------------------------
def _set_layout(client, hub, **fields):
    pid = hub.active_project_id
    res = client.post(f"/api/projects/{pid}/layout", json={"layout": {"mode": "apps", **fields}})
    assert res.status_code == 200, res.text
    return res.json()["layout"]


def _wait_done(client, run_id, timeout=60):
    end = time.time() + timeout
    while time.time() < end:
        run = client.get(f"/api/runs/{run_id}").json()["run"]
        if run["status"] in ("COMPLETED", "FAILED", "CANCELLED"):
            return run
        time.sleep(0.1)
    raise AssertionError("zaman aşımı")


def test_template_run_in_apps_layout_writes_only_apps_devops_docs(client, hub, tmp_project):
    lay = _set_layout(client, hub)
    assert lay["mode"] == "apps" and hub.get_settings()["project_layout"]["docs_dir"] == "docs"
    hub.step_by_step_mode = False
    res = client.post("/api/runs", json={"steps": [1, 2, 3, 4, 5, 6, 8, 10], "engine": "template", "step_by_step": False, "prompt": "Test"})
    assert res.status_code == 200, res.text
    done = _wait_done(client, res.json()["run"]["run_id"])
    assert done["status"] == "COMPLETED", done
    exists = lambda rel: os.path.isfile(os.path.join(tmp_project, *rel.split("/")))             # noqa: E731
    for rel in ("docs/PRD.md", "docs/openapi_spec.json", "docs/handshake_sync.json", "docs/QA_REPORT.md",
                "docs/manuals/user_guide.md", "docs/reports/status_report.md",
                "apps/backend/src/main.py", "apps/backend/src/auth.py", "apps/backend/requirements.txt", "apps/backend/tests/test_app.py",
                "apps/web/src/App.tsx", "apps/web/src/api_client.ts", "devops/Dockerfile", "devops/docker-compose.yml", "README.md"):
        assert exists(rel), rel
    root = {n for n in os.listdir(tmp_project) if n not in (".git", ".fs-workspace", ".gitignore")}
    assert root <= {"apps", "devops", "docs", "README.md"}, root                                # kökte yalnızca düzenin klasörleri ve depo dosyası
    assert not exists("src/main.py") and not os.path.exists(os.path.join(tmp_project, "FS-docs")) and not os.path.exists(os.path.join(tmp_project, "frontend"))
    for cur, _dirs, files in os.walk(os.path.join(tmp_project, "docs")):
        for f in files:
            text = open(os.path.join(cur, f), encoding="utf-8", errors="ignore").read()
            assert "<docs>" not in text and "<reports>" not in text and "{docs_root}" not in text, f


def test_flat_layout_is_unchanged_without_the_setting(client, hub, tmp_project):
    hub.step_by_step_mode = False
    res = client.post("/api/runs", json={"steps": [1, 2, 3, 8], "engine": "template", "step_by_step": False, "prompt": "Test"})
    done = _wait_done(client, res.json()["run"]["run_id"])
    assert done["status"] == "COMPLETED", done
    assert os.path.isfile(os.path.join(tmp_project, "src", "main.py")) and os.path.isfile(os.path.join(tmp_project, "devops", "Dockerfile"))     # kalıcı kural: Docker dosyası düz düzende de devops/ altında
    assert os.path.isfile(os.path.join(tmp_project, "FS-docs", "PRD.md")) and not os.path.exists(os.path.join(tmp_project, "apps"))


# ---------------------------------------------------------------------------
# LLM (MCP istemcisi) teslimi doğrulanır; istem düzeni anlatır
# ---------------------------------------------------------------------------
NOTES = ("Kullanıcılar sisteme kayıt olup giriş yapabilmeli. Yöneticiler kayıtları listeleyip filtreleyebilmeli. "
         "Her işlem için denetim kaydı tutulmalı.")
CLIENT = {"name": "claude-code", "version": "2.1"}


def _drive_to_first_task(client, hub, **layout):
    client.post("/api/settings/sprint", json={"enabled": True, "commit_approval": "auto", "auto_chain": True, "max_tasks": 3})
    client.post("/api/settings/engine", json={"execution_engine": "mcp_client", "approval_mode": "auto", "pacing": "instant", "auto_verify": False, "auto_commit": False})
    hub.step_by_step_mode = False
    _set_layout(client, hub, **layout)
    rid = client.post("/api/specs/upload", data={"title": "Notlar", "client_name": "Acme", "meeting_notes": NOTES}).json()["intake"]["run_id"]
    assert client.post("/api/runner/claim", json={"client": CLIENT}).json()["status"] == "CLAIMED"
    from server import pipeline as P
    for _ in range(60):
        run = hub.runs[rid]
        if run.current_step is not None and run.current_step.kind == "task":
            return rid
        nxt = client.post(f"/api/runs/{rid}/next-step", json={"client": CLIENT}).json()
        assert nxt["status"] == "STEP", nxt
        record = run.current_step
        env = P.handler_for(hub, record).template_output(P.make_context(hub, run, record))
        LAY.relocate_envelope(LAY.layout_of(hub), env, record.role, hub_docs(hub))        # uyumlu bir LLM'in teslimi
        res = client.post(f"/api/runs/{rid}/steps/{nxt['order']}/result", json={"result_json": json.dumps(env), "client": CLIENT}).json()
        assert res["status"] in ("NEXT", "RUN_COMPLETE"), res
    raise AssertionError("görev adımına gelinemedi")


def hub_docs(hub):
    from server.paths import hub_docs_path
    return hub_docs_path(hub, "")


def test_llm_delivery_must_follow_the_layout_and_the_prompt_explains_it(client, hub, tmp_project):
    rid = _drive_to_first_task(client, hub)
    assert os.path.isfile(os.path.join(tmp_project, "docs", "PRD.md")) and not os.path.exists(os.path.join(tmp_project, "FS-docs"))     # belge klasörü düzenden
    nxt = client.post(f"/api/runs/{rid}/next-step", json={"client": CLIENT}).json()
    assert nxt["status"] == "STEP" and "Proje klasör düzeni (ZORUNLU" in nxt["user_context"] and "apps/<uygulama>/" in nxt["user_context"]
    assert "cd apps/backend && npm test" in nxt["user_context"]
    order = nxt["order"]
    role = hub.runs[rid].current_step.role
    folder = LAY.app_folder(APPS, LAY.role_key_for(role))                                        # önerilen yol, teslimi yazan ajanın uygulaması
    flat = {"trace_id": rid, "from_agent": role, "to_agent": "QA", "intent": "SUBMIT_CODE", "status": "SUCCESS",
            "payload": {"summary": "x", "task_key": "T-01", "files": [{"path": "src/main.ts", "content": "export {};\n"}, {"path": "package.json", "content": "{}"}]}}
    res = client.post(f"/api/runs/{rid}/steps/{order}/result", json={"result_json": json.dumps(flat), "client": CLIENT}).json()
    assert res["status"] == "REJECTED"
    text = " ".join(res["validation_errors"])
    assert "kökte ürün dosyası olamaz" in text and f"{folder}/src/main.ts" in text and f"{folder}/package.json" in text
    assert not os.path.exists(os.path.join(tmp_project, "src"))                                  # reddedilen teslim diske hiç yazılmaz
    ok = {**flat, "payload": {**flat["payload"], "files": [{"path": f"{folder}/src/main.ts", "content": "export {};\n"},
                                                           {"path": f"{folder}/package.json", "content": "{}"}]}}
    res = client.post(f"/api/runs/{rid}/steps/{order}/result", json={"result_json": json.dumps(ok), "client": CLIENT}).json()
    assert res["status"] in ("NEXT", "WAITING_APPROVAL", "RUN_COMPLETE"), res
    assert os.path.isfile(os.path.join(tmp_project, *folder.split("/"), "src", "main.ts"))


def test_with_enforcement_off_the_delivery_is_moved_instead_of_rejected(client, hub, tmp_project):
    rid = _drive_to_first_task(client, hub, enforce=False)
    nxt = client.post(f"/api/runs/{rid}/next-step", json={"client": CLIENT}).json()
    assert "reddedilir" not in nxt["user_context"]
    role = hub.runs[rid].current_step.role
    folder = LAY.app_folder(LAY.layout_of(hub), LAY.role_key_for(role))
    flat = {"trace_id": rid, "from_agent": role, "to_agent": "QA", "intent": "SUBMIT_CODE", "status": "SUCCESS",
            "payload": {"summary": "x", "task_key": "T-01", "files": [{"path": "src/main.ts", "content": "export {};\n"}]}}
    res = client.post(f"/api/runs/{rid}/steps/{nxt['order']}/result", json={"result_json": json.dumps(flat), "client": CLIENT}).json()
    assert res["status"] in ("NEXT", "WAITING_APPROVAL", "RUN_COMPLETE"), res
    assert os.path.isfile(os.path.join(tmp_project, *folder.split("/"), "src", "main.ts")) and not os.path.exists(os.path.join(tmp_project, "src"))


def test_architect_file_hints_are_relocated_into_the_layout(client, hub):
    _drive_to_first_task(client, hub)
    hints = [i["files_hint"] for i in hub.jira_issues.values() if str(i.get("kind", "")).lower() == "task" and i.get("files_hint")]
    assert hints and all(h.startswith(("apps/", "devops/", "docs/")) for hs in hints for h in hs), hints


# ---------------------------------------------------------------------------
# Uçlar: düzeni oku/ayarla, proje eklerken varsayılan, göç
# ---------------------------------------------------------------------------
def test_layout_endpoints_and_new_project_default(client, hub, tmp_path):
    pid = hub.active_project_id
    info = client.get(f"/api/projects/{pid}/layout").json()
    assert info["layout"]["mode"] == "flat" and info["default"]["mode"] == "apps" and "migration_preview" in info
    set_res = client.post(f"/api/projects/{pid}/layout", json={"layout": {"mode": "apps", "devops_dir": "ops", "roles": {"backend": "api"}}}).json()
    assert set_res["layout"]["devops_dir"] == "ops" and set_res["layout"]["roles"] == {"backend": "api"}
    assert hub.get_settings()["project_layout"]["devops_dir"] == "ops"
    assert client.post("/api/projects/nope/layout", json={"layout": {}}).status_code == 409

    fresh = tmp_path / "yeni-proje"
    fresh.mkdir()
    added = client.post("/api/projects/add", json={"path": str(fresh), "name": "Yeni"}).json()["project"]
    assert hub.projects[added["id"]]["settings"]["project_layout"]["mode"] == "apps"             # boş klasör: önerilen düzen
    old = tmp_path / "eski-proje"
    old.mkdir()
    (old / "package.json").write_text("{}", encoding="utf-8")
    added2 = client.post("/api/projects/add", json={"path": str(old), "name": "Eski"}).json()["project"]
    assert hub.projects[added2["id"]]["settings"]["project_layout"]["mode"] == "flat"            # ürün dosyası olan klasör dayatılmaz


def _git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout


def _flat_git_project(root):
    """demo_project benzeri düz proje: kökte NestJS uygulaması, FS-docs, test/, db/, Dockerfile, README; git deposu."""
    files = {
        "package.json": json.dumps({"dependencies": {"@nestjs/core": "10"}, "scripts": {"test": "jest"}}),
        "tsconfig.json": "{}", "src/main.ts": "export {};\n", "src/auth/auth.service.ts": "export {};\n", "test/e2e/full.spec.ts": "export {};\n",
        "db/schema.sql": "select 1;\n", "FS-docs/PRD.md": "# PRD\n", "FS-docs/ARCHITECTURE.md": "Kod: `src/<modül>/` ve `package.json`; belgeler `FS-docs/`.\n",
        "FS-docs/sprints/sprint-1.json": "{}", "Dockerfile": "FROM node:20\n", "README.md": "# x\n", ".gitignore": "node_modules/\ndist/\n",
        "scripts/.gitkeep": "",                                                    # yer tutucu klasör: planda "boş" diye işaretlenir
    }
    for rel, text in files.items():
        p = os.path.join(root, *rel.split("/"))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
    os.makedirs(os.path.join(root, "node_modules", "x"), exist_ok=True)            # izlenmeyen ağır klasör (git mv yerine taşınır)
    with open(os.path.join(root, "node_modules", "x", "i.js"), "w", encoding="utf-8") as fh:
        fh.write("1")
    os.makedirs(os.path.join(root, "dist"), exist_ok=True)
    with open(os.path.join(root, "dist", "main.js"), "w", encoding="utf-8") as fh:
        fh.write("1")
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@t")
    _git(root, "config", "user.name", "t")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "init")


def test_migrate_layout_moves_files_with_git_and_rewrites_state(client, hub, tmp_project):
    _flat_git_project(tmp_project)
    pid = hub.active_project_id
    hub.jira_issues["JIRA-1"]["files_hint"] = ["src/main.ts", "package.json", "FS-docs/PRD.md"]
    hub.jira_issues["JIRA-1"]["files_affected"] = ["src/auth/auth.service.ts"]
    hub.jira_issues["JIRA-2"]["files_hint"] = ["config/app.ts", "devops/ci.yml"]       # kökte hiç olmayan klasör: yazan ajanın uygulamasına uydurulur
    run = PipelineRun(project_id=pid, engine="mcp_client", mode="sprint",
                      steps=[StepRecord(order=1, issue_id="JIRA-1", role="PM", kind="phase", status="DONE", artifacts=["FS-docs/PRD.md", "src/main.ts"])])
    hub.register_run(run)
    run.finish("ABANDONED", reason="server-restart")
    hub.settings = {**hub.settings, "verification": {"install": "npm install", "test": "npm test", "run": "node dist/main.js",
                                                     "health_url": "http://127.0.0.1:3000/health"}}

    plan = client.post(f"/api/projects/{pid}/migrate-layout", json={}).json()                 # kuru plan: hiçbir şey değişmez
    assert plan["status"] == "PLAN" and os.path.isfile(os.path.join(tmp_project, "src", "main.ts"))
    moves = {m["from"]: m["to"] for m in plan["plan"]["moves"]}
    assert moves["src"] == "apps/backend/src" and moves["package.json"] == "apps/backend/package.json" and moves["FS-docs"] == "docs"
    assert moves["test"] == "apps/backend/test" and moves["db"] == "apps/backend/db" and moves["Dockerfile"] == "devops/Dockerfile"
    assert moves["node_modules"] == "apps/backend/node_modules" and "README.md" not in moves and ".gitignore" not in moves and not plan["plan"]["conflicts"]
    assert next(m for m in plan["plan"]["moves"] if m["from"] == "scripts")["empty"] is True and next(m for m in plan["plan"]["moves"] if m["from"] == "src")["empty"] is False

    res = client.post(f"/api/projects/{pid}/migrate-layout", json={"apply": True})
    assert res.status_code == 200, res.text
    out = res.json()
    assert out["status"] == "APPLIED" and out["commit"]["status"] == "COMMITTED"
    for rel in ("apps/backend/src/main.ts", "apps/backend/package.json", "apps/backend/test/e2e/full.spec.ts", "apps/backend/db/schema.sql", "docs/PRD.md",
                "docs/sprints/sprint-1.json", "devops/Dockerfile", "README.md", "apps/backend/node_modules/x/i.js", "apps/backend/dist/main.js"):
        assert os.path.isfile(os.path.join(tmp_project, *rel.split("/"))), rel
    root = {n for n in os.listdir(tmp_project) if n not in (".git", ".fs-workspace", ".gitignore")}
    assert root == {"apps", "devops", "docs", "README.md"}, root
    assert _git(tmp_project, "status", "--porcelain").strip() == ""                               # tek commit, çalışma ağacı temiz
    renames = _git(tmp_project, "show", "--name-status", "--format=", "HEAD", "-M")
    assert "R100	src/main.ts	apps/backend/src/main.ts" in renames and "R100	FS-docs/PRD.md	docs/PRD.md" in renames       # geçmiş korunur (git mv)
    # kayıtlı durum yeni yollara çevrildi
    assert hub.jira_issues["JIRA-1"]["files_hint"] == ["apps/backend/src/main.ts", "apps/backend/package.json", "docs/PRD.md"]
    assert hub.jira_issues["JIRA-1"]["files_affected"] == ["apps/backend/src/auth/auth.service.ts"]
    assert hub.jira_issues["JIRA-2"]["files_hint"] == ["apps/backend/config/app.ts", "devops/ci.yml"]     # düz ipucu uyduruldu, uyumlu olan aynen
    assert os.path.isfile(os.path.join(tmp_project, "apps", "backend", "scripts", ".gitkeep"))
    assert hub.runs[run.run_id].steps[0].artifacts == ["docs/PRD.md", "apps/backend/src/main.ts"]
    settings = hub.get_settings()
    assert settings["project_layout"]["mode"] == "apps" and not settings.get("docs_root")
    assert settings["verification"]["install"] == "cd apps/backend && npm install" and settings["verification"]["run"] == "cd apps/backend && node dist/main.js"
    assert settings["verification"]["health_url"] == "http://127.0.0.1:3000/health"             # adres değişmez
    arch = open(os.path.join(tmp_project, "docs", "ARCHITECTURE.md"), encoding="utf-8").read()
    assert "`apps/backend/src/<modül>/`" in arch and "`apps/backend/package.json`" in arch and "`docs/`" in arch      # belgelerdeki `kod` yolları çevrildi
    # ikinci uygulama: yapılacak iş yok, düzen zaten uygulandı
    again = client.post(f"/api/projects/{pid}/migrate-layout", json={"apply": True}).json()
    assert again["status"] == "APPLIED" and again["moved"] == []


def test_migrate_layout_refuses_while_a_step_is_in_flight_or_on_conflict(client, hub, tmp_project):
    _flat_git_project(tmp_project)
    pid = hub.active_project_id
    run = PipelineRun(project_id=pid, engine="mcp_client", mode="sprint", steps=[StepRecord(order=1, issue_id="JIRA-1", role="PM", kind="phase", status="ACTIVE")])
    run.status = "ACTIVE"
    hub.register_run(run)
    busy = client.post(f"/api/projects/{pid}/migrate-layout", json={"apply": True})
    assert busy.status_code == 409 and "Süren bir adım" in busy.json()["error"] and os.path.isfile(os.path.join(tmp_project, "src", "main.ts"))
    run.steps[0].status = "WAITING_APPROVAL"                                                      # onay beklemek göçü engellemez
    run.status = "WAITING_APPROVAL"
    os.makedirs(os.path.join(tmp_project, "apps", "backend", "src"), exist_ok=True)               # hedef zaten var: çakışma
    conflict = client.post(f"/api/projects/{pid}/migrate-layout", json={"apply": True})
    assert conflict.status_code == 409 and "Çakışma" in conflict.json()["error"] and os.path.isfile(os.path.join(tmp_project, "src", "main.ts"))


def test_rewrite_verification_handles_cd_prefixes_and_root_manifest():
    pairs = [("frontend", "apps/web")]
    from server.migrate_layout import rewrite_verification
    out = rewrite_verification({"install": "cd frontend && npm install", "test": "npm test", "health_url": "http://x/h"}, pairs, "apps/backend")
    assert out == {"install": "cd apps/web && npm install", "test": "cd apps/backend && npm test", "health_url": "http://x/h"}
    assert LAY.prefix_verification({"build": "npm run build", "run": "cd x && y"}, "apps/api") == {"build": "cd apps/api && npm run build", "run": "cd x && y"}


def test_docker_dosyalari_her_kipte_devops_altinda_olmali():
    apps, flat = LAY.DEFAULT_LAYOUT, LAY.flat_layout()
    for lay in (apps, flat):                                                         # düz (eski) düzende de geçerli
        bad = LAY.docker_violations(lay, ["docker-compose.dev.yml", "apps/backend/Dockerfile", "apps/backend/.dockerignore", "Dockerfile.dev", "compose.yaml",
                                          "devops/Dockerfile", "devops/backend/Dockerfile", "devops/docker-compose.yml", "apps/backend/src/docker/docker-dev.spec.ts", "docs/docker.md"])
        assert [b.split(":")[0] for b in bad] == ["docker-compose.dev.yml", "apps/backend/Dockerfile", "apps/backend/.dockerignore", "Dockerfile.dev", "compose.yaml"]
    assert LAY.docker_suggestion(apps, "apps/backend/Dockerfile") == "devops/backend/Dockerfile"
    assert LAY.docker_suggestion(apps, "docker-compose.dev.yml") == "devops/docker-compose.dev.yml"
    assert "devops/backend/Dockerfile" in LAY.docker_violations(apps, ["apps/backend/Dockerfile"])[0] and "context: .." in LAY.docker_violations(apps, ["Dockerfile"])[0]
    rule = LAY.devops_rule_section(apps, "demo_project")
    assert "KALICI KURAL" in rule and "name: demo_project" in rule and "demo_project-" in rule and "bind-mount" in rule


def test_docker_dosyasi_olan_llm_teslimi_reddedilir_ve_devops_altindaki_gecer(client, hub, tmp_project):
    import json
    hub.step_by_step_mode = False
    rid = client.post("/api/runs", json={"steps": [3], "engine": "mcp_client", "client": {"name": "curl"}}).json()["run"]["run_id"]
    client.post(f"/api/runs/{rid}/next-step", json={"client": {"name": "curl"}})

    def env(path):
        return json.dumps({"from_agent": "BACKEND_DEV", "to_agent": "FRONTEND_DEV", "intent": "BACKEND_API_EXPOSED", "status": "SUCCESS",
                           "payload": {"summary": "s", "files": [{"path": path, "content": "FROM node:20\n"}, {"path": "src/main.py", "content": "app = 1\n"}]},
                           "metadata": {"tokens_used": 5}})
    bad = client.post(f"/api/runs/{rid}/steps/3/result", json={"result_json": env("docker-compose.dev.yml")}).json()
    assert bad["status"] == "REJECTED" and any("devops/docker-compose.dev.yml" in e for e in bad["validation_errors"])
    import os
    assert not os.path.exists(os.path.join(tmp_project, "docker-compose.dev.yml"))


def test_find_dockerfile_cok_uygulamali_devops_yapisini_bulur(tmp_path):
    from server import guard as G
    (tmp_path / "devops" / "backend").mkdir(parents=True)
    (tmp_path / "devops" / "backend" / "Dockerfile").write_text("FROM node:20\n", encoding="utf-8")
    assert G.find_dockerfile(str(tmp_path)) == "devops/backend/Dockerfile"


def test_docker_dosyalari_devops_altina_tasinir_compose_yollari_ve_basvurular_guncellenir(tmp_path):
    from server import docker_relocate as DR
    root = tmp_path
    (root / "apps" / "backend" / "src").mkdir(parents=True)
    (root / "devops").mkdir()
    (root / "docs").mkdir()
    (root / "apps" / "backend" / "Dockerfile").write_text("FROM node:24\nCOPY package.json ./\n", encoding="utf-8")
    (root / "apps" / "backend" / ".dockerignore").write_text("node_modules\n", encoding="utf-8")
    (root / "docker-compose.dev.yml").write_text(
        "services:\n  backend:\n    build:\n      context: ./apps/backend\n      dockerfile: Dockerfile\n    ports:\n      - \"127.0.0.1:5050:5050\"\n"
        "    volumes:\n      - ./apps/backend/src:/app/src:ro\n", encoding="utf-8")
    (root / "devops" / "Dockerfile").write_text("FROM node:24\n", encoding="utf-8")                  # çakışma yok: farklı ad
    (root / "docs" / "DOCKER.md").write_text("Dosyalar: `docker-compose.dev.yml`, `apps/backend/Dockerfile`.\n`docker compose -f docker-compose.dev.yml up`\n", encoding="utf-8")
    spec = root / "apps" / "backend" / "src" / "docker.spec.ts"
    spec.write_text("const a = resolve(ROOT, 'docker-compose.dev.yml'); const b = resolve(BACKEND, 'Dockerfile');\n", encoding="utf-8")
    lay = LAY.DEFAULT_LAYOUT
    p = DR.plan(str(root), lay)
    assert {m["from"]: m["to"] for m in p["moves"]} == {"docker-compose.dev.yml": "devops/docker-compose.dev.yml", "apps/backend/Dockerfile": "devops/backend/Dockerfile",
                                                       "apps/backend/.dockerignore": "devops/backend/.dockerignore"} and p["conflicts"] == []
    res = DR.apply(str(root), lay)
    assert len(res["moved"]) == 3 and not (root / "docker-compose.dev.yml").exists() and not (root / "apps" / "backend" / "Dockerfile").exists()
    compose = (root / "devops" / "docker-compose.dev.yml").read_text(encoding="utf-8")
    assert "context: ../apps/backend" in compose and "dockerfile: ../../devops/backend/Dockerfile" in compose and "- ../apps/backend/src:/app/src:ro" in compose
    assert "devops/docker-compose.dev.yml" in (root / "docs" / "DOCKER.md").read_text(encoding="utf-8") and "devops/backend/Dockerfile" in (root / "docs" / "DOCKER.md").read_text(encoding="utf-8")
    assert "'devops/docker-compose.dev.yml'" in spec.read_text(encoding="utf-8")                      # spec'te alıntılanmış dosya adı çevrildi
    assert res["remaining_refs"] == ["apps/backend/src/docker.spec.ts"]                              # resolve(BACKEND,'Dockerfile') çevrilemedi: bildirilir
    assert DR.plan(str(root), lay)["moves"] == []                                                    # ikinci çalıştırma değişiklik yapmaz


def test_docker_tasima_hedef_varsa_uzerine_yazmaz(tmp_path):
    from server import docker_relocate as DR
    (tmp_path / "devops").mkdir()
    (tmp_path / "devops" / "Dockerfile").write_text("A", encoding="utf-8")
    (tmp_path / "Dockerfile").write_text("B", encoding="utf-8")
    res = DR.apply(str(tmp_path), LAY.DEFAULT_LAYOUT)
    assert res["moved"] == [] and res["conflicts"][0]["to"] == "devops/Dockerfile"
    assert (tmp_path / "devops" / "Dockerfile").read_text(encoding="utf-8") == "A" and (tmp_path / "Dockerfile").exists()
