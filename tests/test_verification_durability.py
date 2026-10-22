"""E2E çalıştırma yapılandırması (verification) git'e giren dosyada saklanır; eksikse mesaj öneri verir; yapılandırma hatası DEVOPS işi olur."""
import json
import os

from server import fs_workspace as FW
from server import pipeline as P
from server import quality as Q
from server import sprint as SP
from server.runs import PipelineRun


def test_verification_ayri_dosyaya_yazilir_ve_okunur(tmp_path):
    proj = {"id": "p", "name": "p", "jira_issues": {}, "tasks": {}, "uploaded_specs": [], "stats": {},
            "settings": {"verification": {"run": "node dist/main.js", "health_url": "http://127.0.0.1:3000/health"}}}
    FW.write_files_atomic(FW.build_workspace_files(str(tmp_path), proj))
    assert json.loads((tmp_path / ".fs-workspace" / "verification.json").read_text(encoding="utf-8"))["health_url"].endswith("/health")
    assert FW.load_project_from_workspace(str(tmp_path))["verification"]["run"] == "node dist/main.js"
    empty = {**proj, "settings": {"verification": {}}}
    assert "verification.json" not in [os.path.basename(p) for p in FW.build_workspace_files(str(tmp_path), empty)]


async def test_ayar_sifirlaninca_git_yedegindeki_verification_geri_gelir(hub, tmp_path):
    ws = tmp_path / ".fs-workspace"
    ws.mkdir()
    (ws / "verification.json").write_text(json.dumps({"run": "cd apps/backend && node dist/main.js", "health_url": "http://127.0.0.1:3000/health"}), encoding="utf-8")
    proj = {"path": str(tmp_path), "settings": {"verification": {}}}
    hub._apply_workspace_overrides(proj, str(tmp_path))
    assert proj["settings"]["verification"]["run"].startswith("cd apps/backend")
    kept = {"path": str(tmp_path), "settings": {"verification": {"run": "npm start", "health_url": "http://x/health"}}}
    hub._apply_workspace_overrides(kept, str(tmp_path))                         # kullanıcının güncel ayarı ezilmez
    assert kept["settings"]["verification"]["run"] == "npm start"


def test_calistirma_komutu_adaylari(tmp_path):
    (tmp_path / "apps" / "backend").mkdir(parents=True)
    (tmp_path / "apps" / "backend" / "package.json").write_text(json.dumps({"scripts": {"start": "node dist/main.js", "test": "jest"}}), encoding="utf-8")
    assert P.detect_run_candidates(str(tmp_path)) == ["cd apps/backend && npm start"]
    assert P.detect_run_candidates(str(tmp_path / "yok")) == []


async def test_e2e_yapilandirma_hatasi_devops_isi_acar(hub, tmp_project):
    await hub.update_settings({"autonomy": {"strict_dod": True}})
    sp = SP.new_sprint(hub, 1, "Hedef")
    hub.playwright_reports.insert(0, {"status": "FAILED", "verdict": "APP_NOT_CONFIGURED", "engine_error": "verification.run ve health_url tanımlı değil"})
    created = []

    async def create(tasks):
        created.extend(tasks)
    await Q.close_report(hub, PipelineRun(project_id=hub.active_project_id), sp, tmp_project, create)
    bug = next(t for t in created if t["task_key"] == "E2E")
    assert bug["role"] == "DEVOPS" and "ayar" in bug["title"] and "health_url" in bug["acceptance_criteria"][0]
