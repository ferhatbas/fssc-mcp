"""Proje silme (iki adımlı onay): kapsamlar, ad onayı, korumalar."""
import os

from server import purge as P


def _add(client, tmp_path, name):
    d = tmp_path / name
    d.mkdir()
    (d / "src").mkdir()
    (d / "src" / "app.py").write_text("x", encoding="utf-8")
    pid = client.post("/api/projects/add", json={"path": str(d), "name": name}).json()["project"]["id"]
    return pid, d


def test_purge_requires_exact_name_and_valid_scope(client, tmp_path):
    pid, d = _add(client, tmp_path, "alpha")
    assert client.post(f"/api/projects/{pid}/purge", json={"scope": "data", "confirm_name": "yanlis"}).status_code == 400
    assert client.post(f"/api/projects/{pid}/purge", json={"scope": "all", "confirm_name": "alpha"}).status_code == 400
    assert (d / ".fs-workspace").is_dir()                       # reddedilince hiçbir şey silinmedi


def test_purge_data_keeps_code_and_removes_project(client, tmp_path):
    pid, d = _add(client, tmp_path, "beta")
    res = client.post(f"/api/projects/{pid}/purge", json={"scope": "data", "confirm_name": "beta"}).json()
    assert res["status"] == "PURGED"
    assert not (d / ".fs-workspace").exists() and (d / "src" / "app.py").is_file()
    assert pid not in {p["id"] for p in client.get("/api/projects").json()["projects"]}


def test_purge_folder_removes_everything_and_switches_active(client, tmp_path):
    pid, d = _add(client, tmp_path, "gamma")
    client.post("/api/projects/switch", json={"project_id": pid})
    res = client.post(f"/api/projects/{pid}/purge", json={"scope": "folder", "confirm_name": "gamma"})
    assert res.status_code == 200 and not d.exists()
    assert client.get("/api/projects").json()["active_project_id"] != pid


def test_last_project_can_be_purged_and_board_goes_empty(client, hub, tmp_path):
    pid, d = _add(client, tmp_path, "solo")
    for other in [p for p in list(hub.projects) if p != pid]:
        hub.projects.pop(other)
    client.post("/api/projects/switch", json={"project_id": pid})
    res = client.post(f"/api/projects/{pid}/purge", json={"scope": "data", "confirm_name": "solo"})
    assert res.status_code == 200 and not hub.projects and hub.active_project_id == ""
    assert client.get("/api/projects").json()["projects"] == []
    assert hub.uploaded_specs == [] and hub.project_summary() is None


def test_protected_paths_are_refused():
    for bad in (P.REPO_ROOT, os.path.dirname(P.REPO_ROOT), os.path.abspath(os.sep), os.path.expanduser("~")):
        try:
            P.check_deletable(bad)
            raise AssertionError(bad)
        except P.PurgeError:
            pass
