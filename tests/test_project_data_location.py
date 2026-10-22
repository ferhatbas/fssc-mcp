"""F1 / A8, A9: proje verisi hedef projede durur (FS-SC kökünde oluşmaz); .gitignore §5.4 kuralları."""

import os
import shutil
import subprocess

import pytest

from server import scm
from server.playwright_tester import SCREENSHOTS_REL, screenshot_url, screenshots_dir_for

HAS_GIT = shutil.which("git") is not None


# ---- .gitignore (A8) -------------------------------------------------------
def test_merge_gitignore_preserves_user_lines_and_is_idempotent():
    user = "node_modules/\n# benim kuralım\nsecret.txt\n.env\n"
    merged = scm.merge_gitignore(user)
    assert merged.startswith(user)
    for line in scm.FSSC_IGNORE_LINES:
        assert line in merged.splitlines()
    assert merged.splitlines().count(".env") == 1  # zaten vardı, tekrarlanmadı
    assert scm.merge_gitignore(merged) == merged


def test_ignore_lines_follow_spec():
    lines = set(scm.FSSC_IGNORE_LINES)
    # git'e GİRMEZ (§5.4 + karar 18)
    for must in (".fs-workspace/settings.json", ".fs-workspace/events.jsonl", ".fs-workspace/runs.json", ".fs-workspace/meetings/*.jsonl",
                 ".fs-workspace/e2e/screenshots/", ".fs-workspace/specs/uploads/", ".fs-workspace/app_run.log", ".env", ".env.*"):
        assert must in lines
    # git'e GİRER: bunlar ignore edilmemeli
    for tracked in ("jira_issues.json", "sprint_state.json", "questions.json", "agents", "FS-docs"):
        assert not any(tracked in ln for ln in lines)


@pytest.mark.skipif(not HAS_GIT, reason="git yok")
async def test_commit_updates_gitignore_in_existing_repo_and_untracks_settings(tmp_path):
    root = str(tmp_path)
    git = lambda *a: subprocess.run(["git", *a], cwd=root, check=True, capture_output=True, text=True).stdout
    git("init", "-q")
    ws = tmp_path / ".fs-workspace"
    ws.mkdir()
    (ws / "settings.json").write_text('{"path": "C:/x", "last_active": 1}', encoding="utf-8")
    (ws / "jira_issues.json").write_text("{}", encoding="utf-8")
    (ws / "specs").mkdir()
    (ws / "specs" / "uploads").mkdir()
    (ws / "specs" / "uploads" / "ham.txt").write_text("yönetici notu", encoding="utf-8")
    (tmp_path / ".gitignore").write_text("*.log\n", encoding="utf-8")
    (tmp_path / "app.py").write_text("print(1)\n", encoding="utf-8")
    git("add", "-f", "-A")  # settings.json ve yükleme zorla izlenir (eski FS-SC davranışı)
    git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "eski")
    assert ".fs-workspace/settings.json" in git("ls-files")

    (tmp_path / "app.py").write_text("print(2)\n", encoding="utf-8")
    res = await scm.commit_all(root, "feat: x")
    assert res["status"] == "COMMITTED", res

    tracked = git("ls-files").splitlines()
    assert ".fs-workspace/settings.json" not in tracked          # indeksten çıktı
    assert ".fs-workspace/specs/uploads/ham.txt" not in tracked   # ham yönetici metni git'te değil
    assert ".fs-workspace/jira_issues.json" in tracked            # proje hafızası git'te
    assert (ws / "settings.json").exists()                         # diskte duruyor
    gi = (tmp_path / ".gitignore").read_text(encoding="utf-8")
    assert gi.startswith("*.log\n") and ".fs-workspace/settings.json" in gi

    # ikinci commit: yalnızca gerçek değişiklik varsa; settings her senkronda değişse bile "değişiklik yok" kolu çalışır
    (ws / "settings.json").write_text('{"path": "C:/x", "last_active": 2}', encoding="utf-8")
    assert (await scm.commit_all(root, "feat: y"))["status"] == "NOTHING"


@pytest.mark.skipif(not HAS_GIT, reason="git yok")
async def test_new_repo_gets_gitignore_with_fssc_lines(tmp_path):
    (tmp_path / "a.py").write_text("1\n", encoding="utf-8")
    res = await scm.commit_all(str(tmp_path), "feat: ilk")
    assert res["status"] == "COMMITTED" and res["created_repo"] is True
    gi = (tmp_path / ".gitignore").read_text(encoding="utf-8")
    for line in scm.FSSC_IGNORE_LINES:
        assert line in gi.splitlines()


# ---- Ekran görüntüleri ve yüklemeler (A9) ----------------------------------------
def test_screenshots_dir_is_inside_target_project(tmp_path):
    d = screenshots_dir_for(str(tmp_path))
    assert os.path.normcase(d) == os.path.normcase(os.path.join(str(tmp_path), ".fs-workspace", "e2e", "screenshots"))
    assert SCREENSHOTS_REL == ".fs-workspace/e2e/screenshots"
    assert screenshot_url("p1", "a.png") == "/api/projects/p1/screenshots/a.png"


def test_screenshots_without_project_never_use_fssc_root(tmp_path):
    from server.paths import WORKSPACE_DIR  # noqa: F401
    d = os.path.normcase(screenshots_dir_for(None))
    repo = os.path.normcase(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
    assert not d.startswith(repo)


def test_project_files_are_served_per_project(client, hub, tmp_project):
    pid = hub.active_project_id
    shots = screenshots_dir_for(tmp_project)
    with open(os.path.join(shots, "s.png"), "wb") as f:
        f.write(b"\x89PNG-test")
    got = client.get(f"/api/projects/{pid}/screenshots/s.png")
    assert got.status_code == 200 and got.content == b"\x89PNG-test"
    assert client.get(f"/api/projects/{pid}/screenshots/yok.png").status_code == 404
    assert client.get("/api/projects/yok/screenshots/s.png").status_code == 404
    # yol geçişi: dosya adı temizlenir, proje dışına çıkamaz
    secret = os.path.join(tmp_project, "secret.txt")
    open(secret, "w").write("gizli")
    assert client.get(f"/api/projects/{pid}/screenshots/..%2F..%2F..%2Fsecret.txt").status_code == 404


async def test_playwright_screenshots_land_in_project(tmp_path):
    """Gerçek tarayıcı varsa ekran görüntüleri projenin klasörüne düşer ve URL'ler proje başına servis yolunu gösterir."""
    pytest.importorskip("playwright")
    import server.playwright_tester as pw
    result = await pw.run_playwright_e2e_tests(target_url="data:text/html,<h1>x</h1>", test_scenario="t", project_dir=str(tmp_path), project_id="p1")
    if result["status"] == "SKIPPED":
        pytest.skip("Chromium kurulu değil")
    shots = list((tmp_path / ".fs-workspace" / "e2e" / "screenshots").glob("*.png"))
    assert shots and all(u.startswith("/api/projects/p1/screenshots/") for u in result["screenshots"])
