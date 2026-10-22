"""
REST API testleri (TestClient + izole hub): koşu kilidi, onay ucu, yükleme sanitasyonu, proje geçişi.
"""

import asyncio
import io
import os

import pytest


def test_execute_batch_returns_409_when_run_is_active(client, hub):
    """A1.3: aynı anda tek pipeline koşusu."""
    hub.active_run_id = "jira-batch-existing"
    res = client.post("/api/jira/execute-batch", json={"selected_issues": [1], "step_by_step": False})
    assert res.status_code == 409
    assert res.json()["active_run_id"] == "jira-batch-existing"

    hub.active_run_id = None
    hub.step_by_step_mode = False
    res = client.post("/api/jira/execute-batch", json={"selected_issues": [1], "step_by_step": False})
    assert res.status_code == 200
    assert res.json()["status"] == "STARTED"
    assert res.json()["run_id"]


def test_approve_step_without_pending_returns_409(client):
    res = client.post("/api/pipeline/approve-step", json={"decision": "PROCEED"})
    assert res.status_code == 409
    assert res.json()["status"] == "NO_PENDING_STEP"


def test_upload_rejects_path_traversal(client, hub, patched_main):
    """A4.1 / F1-A9: yüklemeler hedef projenin `.fs-workspace/specs/uploads/` klasörüne yazılır; project_id ve dosya adı dışarı çıkamaz."""
    project_path = hub.projects[hub.active_project_id]["path"]
    uploads_dir = os.path.join(project_path, ".fs-workspace", "specs", "uploads")
    # kayıtsız / geçersiz proje kimliği reddedilir
    bad = client.post(
        "/api/specs/upload",
        data={"title": "x", "client_name": "c", "meeting_notes": "n", "auto_generate_tasks": "false",
              "project_id": "../../escape"},
        files={"files": ("evil.txt", io.BytesIO(b"pwned"), "text/plain")},
    )
    assert bad.status_code == 400, bad.text
    res = client.post(
        "/api/specs/upload",
        data={"title": "x", "client_name": "c", "meeting_notes": "n", "auto_generate_tasks": "false"},
        files={"files": ("../../evil.txt", io.BytesIO(b"pwned"), "text/plain")},
    )
    assert res.status_code == 200, res.text
    saved = res.json()["spec"]["files"][0]
    # Ad temizlenmiş ve dosya projenin yükleme klasörü altında kalmış olmalı
    assert saved["filename"] == "evil.txt"
    assert os.path.abspath(saved["saved_path"]).startswith(os.path.abspath(uploads_dir))
    assert saved["file_url"] == f"/api/projects/{hub.active_project_id}/uploads/evil.txt"
    assert not os.path.exists(os.path.join(uploads_dir, "..", "..", "evil.txt"))
    # FS-SC kökünde yükleme klasörü oluşmaz / yazılmaz
    assert not os.path.exists(os.path.join(os.environ["AGY_DATA_DIR"], "uploads", hub.active_project_id, "evil.txt"))
    # dosya, proje başına servis yolundan okunur
    got = client.get(saved["file_url"])
    assert got.status_code == 200 and got.content == b"pwned"


def test_switch_project_response_is_trimmed(client, hub, tmp_path):
    """A2.7: REST yanıtı tam durumu taşımaz; durum PROJECT_SWITCHED WS mesajından gelir."""
    other = tmp_path / "other_project"
    other.mkdir()
    res = client.post("/api/projects/switch", json={"path": str(other)})
    assert res.status_code == 200
    body = res.json()
    assert set(body.keys()) == {"status", "active_project"}
    assert body["active_project"]["id"] == "other_project"
    assert hub.active_project_id == "other_project"


def test_fs_browse_lists_only_directories(client, tmp_path):
    """Gözat: yalnızca dizinler, gizli/.-ile başlayanlar atlanır, FS-SC/git işaretleri, üst klasör; olmayan yol 404."""
    tmp_path = tmp_path / "browse_root"  # hub fixture'ı tmp_path'e history/ ve target_project/ yazar
    tmp_path.mkdir()
    (tmp_path / "alpha").mkdir()
    (tmp_path / "beta").mkdir()
    (tmp_path / "beta" / ".fs-workspace").mkdir()
    (tmp_path / ".hidden").mkdir()
    (tmp_path / "file.txt").write_text("x", encoding="utf-8")
    res = client.get("/api/fs/browse", params={"path": str(tmp_path)})
    assert res.status_code == 200, res.text
    body = res.json()
    names = [d["name"] for d in body["dirs"]]
    assert names == ["alpha", "beta"] and body["is_root_list"] is False
    assert next(d for d in body["dirs"] if d["name"] == "beta")["has_workspace"] is True
    assert body["parent"] and os.path.normcase(body["parent"]) == os.path.normcase(str(tmp_path.parent))
    assert body["roots"]
    # Kök listesi (sürücüler/öneriler) ve olmayan yol
    assert client.get("/api/fs/browse").json()["is_root_list"] is True
    assert client.get("/api/fs/browse", params={"path": str(tmp_path / "yok")}).status_code == 404
    # Gizli klasör isteğe bağlı
    shown = client.get("/api/fs/browse", params={"path": str(tmp_path), "show_hidden": 1}).json()
    assert ".hidden" in [d["name"] for d in shown["dirs"]]


def test_default_model_is_claude_and_legacy_gemini_default_migrates(client, hub):
    cfg = client.get("/api/settings/model").json()
    model = cfg.get("model_config") or cfg
    assert model["provider"] == "claude" and model["model_id"] == "claude-sonnet-5-5"
    # Eski varsayılan (seçilmemiş Gemini) kayıtları Claude'a taşınır; kullanıcı seçimi korunur
    hub.projects[hub.active_project_id]["model_config"] = {"provider": "gemini", "model_id": "gemini-2.5-pro", "temperature": 0.5, "max_tokens": 4096}
    migrated = hub.get_model_config()
    assert migrated["provider"] == "claude" and migrated["temperature"] == 0.5
    hub.projects[hub.active_project_id]["model_config"] = {"provider": "gemini", "model_id": "gemini-2.5-flash"}
    assert hub.get_model_config()["model_id"] == "gemini-2.5-flash"


def test_pending_step_endpoint_reports_run_id(client, hub):
    hub.active_run_id = "run-1"
    res = client.get("/api/pipeline/pending-step")
    assert res.json()["active_run_id"] == "run-1"


def test_post_event_passes_dialogue_fields_and_stamps_the_time(client):
    """Canlı Ekip Konuşması balonu: olay ucu friendly_dialogue/thinking/what_doing/what_next alanlarını taşır ve olaya zaman damgası basar."""
    res = client.post("/api/events", json={
        "from_agent": "scm", "to_agent": "backend_dev", "action": "COMMIT", "status": "SUCCESS", "payload": {},
        "friendly_dialogue": "Commit atıldı: 98102f0 · fix(JIRA-37): NestJS backend iskeleti (düzeltme 1)",
        "thinking": "diff temiz", "what_doing": "commit", "what_next": "doğrulama"})
    assert res.status_code == 200
    ev = res.json()["event"]
    assert ev["friendly_dialogue"].startswith("Commit atıldı: 98102f0") and ev["thinking"] == "diff temiz"
    assert ev["what_doing"] == "commit" and ev["what_next"] == "doğrulama"
    assert ev["from_agent"] == "SCM" and ev["to_agent"] == "BACKEND_DEV" and "T" in ev["timestamp"]

