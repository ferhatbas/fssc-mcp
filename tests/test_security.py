"""A4: şifre redaksiyonu, kimlik çözümleme, spec dosyası silme, promote hedefi, CORS."""

import io
import os

from server.config import CORS_ORIGINS
from server.fs_workspace import strip_project_sections


def test_cors_has_no_wildcard():
    assert "*" not in CORS_ORIGINS
    assert "http://127.0.0.1:5173" in CORS_ORIGINS


def test_profiles_are_redacted_everywhere(client, hub):
    body = client.get("/api/tester/profiles").json()
    assert body["profiles"] and all("password" not in p for p in body["profiles"])
    assert all(p["has_password"] is True for p in body["profiles"])

    snap = client.get("/api/state").json()
    assert all("password" not in p for p in snap["test_profiles"])
    assert "test_profiles" not in snap["active_project"]  # tam kayıt değil, özet
    assert set(snap["active_project"]) >= {"id", "name", "path", "is_active"}

    saved = client.post("/api/tester/profiles", json={"id": "custom-1", "name": "X", "username": "x@y", "password": "S3cret!", "role": "USER"}).json()["profile"]
    assert "password" not in saved
    assert hub.test_profiles[-1]["password"] == "S3cret!"  # sunucu tarafında saklanır

    proj = client.post("/api/projects/add", json={"path": hub.default_project_path}).json()["project"]
    assert "test_profiles" not in proj and "events" not in proj


def test_resolve_credentials_fills_password_from_profile(hub):
    cred = hub.resolve_credentials({"username": "admin@enterprise.local", "role": "ADMIN", "profile_id": "preset-admin"})
    assert cred["password"] == "AdminSuperSecure2026!" and "profile_id" not in cred
    typed = hub.resolve_credentials({"password": "typed"}, profile_id="preset-admin")
    assert typed["password"] == "typed" and typed["username"] == "admin@enterprise.local"
    assert hub.resolve_credentials(None) is None


async def test_run_endpoints_accept_profile_id(client, hub, monkeypatch):
    import server.main as main_module
    seen = {}

    async def fake_pw(target_url, test_scenario, credentials=None, **kwargs):
        seen["credentials"] = credentials
        return {"status": "PASSED", "screenshots": [], "logs": [], "verdict": "VERIFIED_FOR_PRODUCTION", "scenario": test_scenario,
                "target_url": target_url, "test_user": (credentials or {}).get("username"), "role": (credentials or {}).get("role")}

    monkeypatch.setattr(main_module, "run_playwright_e2e_tests", fake_pw)
    res = client.post("/api/tester/run-playwright", json={"target_url": "http://127.0.0.1:1", "profile_id": "preset-user"})
    assert res.status_code == 200
    assert seen["credentials"]["password"] == "StandardUserPass123!" and seen["credentials"]["username"] == "user@enterprise.local"


async def test_delete_spec_removes_files_inside_uploads_only(client, hub, patched_main, tmp_path):
    uploads = os.path.join(hub.projects[hub.active_project_id]["path"], ".fs-workspace", "specs", "uploads")
    res = client.post(
        "/api/specs/upload",
        data={"title": "t", "client_name": "c", "meeting_notes": "n", "auto_generate_tasks": "false"},
        files={"files": ("notes.txt", io.BytesIO(b"x"), "text/plain")},
    )
    spec = res.json()["spec"]
    saved = spec["files"][0]["saved_path"]
    assert os.path.isfile(saved) and os.path.abspath(saved).startswith(os.path.abspath(uploads))

    # kök dışı bir yol asla silinmez
    outside = tmp_path / "keep.txt"
    outside.write_text("keep")
    assert hub._remove_upload_file(str(outside)) is False and outside.exists()

    assert client.delete(f"/api/specs/{spec['id']}/files/notes.txt").status_code == 200
    assert not os.path.exists(saved)


def test_strip_project_sections():
    content = "---\nagent_id: PM\nproject_scope: x\n---\n\n# PM Prompt\n\nKurallar.\n\n---\n\n## 🧠 Öğrenilen Dersler ve Proje Tecrübeleri\n- proje notu\n"
    assert strip_project_sections(content) == "# PM Prompt\n\nKurallar.\n"


def test_promote_writes_to_lang_dir_and_strips(tmp_path, monkeypatch):
    import server.fs_workspace as ws
    prompts_dir = tmp_path / "prompts"
    (prompts_dir / "tr").mkdir(parents=True)
    (prompts_dir / "tr" / "pm.md").write_text("# Std\n", encoding="utf-8")
    monkeypatch.setattr(ws, "GLOBAL_PROMPTS_DIR", str(prompts_dir))
    monkeypatch.setattr(ws, "DEFAULT_PROMPT_LANG", "tr")
    project = tmp_path / "proj"
    project.mkdir()
    ws.save_agent_markdown(str(project), "PM", "PM", "---\nagent_id: PM\n---\n\n# Proje PM\n\nYeni kural.\n\n## 🧠 Öğrenilen Dersler\n- x\n", "v2", "User")
    result = ws.promote_to_global(str(project), "PM", "PM")
    assert result["global_path"].endswith(os.path.join("tr", "pm.md"))
    promoted = open(result["global_path"], encoding="utf-8").read()
    assert promoted == "# Proje PM\n\nYeni kural.\n"
    assert os.path.isfile(result["backup_path"]) and ".fs-workspace" in result["backup_path"]
    assert not (prompts_dir / "pm.md").exists()  # kök klasöre yazılmaz
