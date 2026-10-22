"""F1: `docs/` → `FS-docs/` göçü. Projenin kendi dosyalarına dokunulmaz, çakışmada ezilmez, git geçmişi korunur."""

import hashlib
import os
import shutil
import subprocess

import pytest

from server.migrate_docs import migrate_docs
from server.paths import docs_root

HAS_GIT = shutil.which("git") is not None


def _digest_tree(root):
    out = {}
    for cur, _, files in os.walk(root):
        if ".git" in cur.split(os.sep):
            continue
        for f in files:
            p = os.path.join(cur, f)
            out[os.path.relpath(p, root).replace("\\", "/")] = hashlib.sha256(open(p, "rb").read()).hexdigest()
    return out


def _write(root, rel, text):
    p = os.path.join(root, *rel.split("/"))
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def _populated_project(tmp_path):
    root = str(tmp_path / "proj")
    os.makedirs(os.path.join(root, ".fs-workspace"))
    # FS-SC'nin ürettiği dosyalar
    for rel in ("PRD.md", "ARCHITECTURE.md", "openapi_spec.json", "QA_REPORT.md", "handshake_sync.json",
                "uat/acceptance_criteria.md", "manuals/user_guide.md", "reports/status_report.md", "tasks/T-01.md", "tasks/task_7.md"):
        _write(root, f"docs/{rel}", f"fssc {rel}\n")
    # PROJENİN KENDİ docs/ dosyaları (taşınmamalı, değişmemeli)
    own = {
        "docs/CONTRIBUTING.md": "kendi dosyam\n",
        "docs/guides/setup.md": "kurulum\n",
        "docs/tasks/roadmap.md": "benim görev notum\n",
        "docs/reports/annual.md": "yıllık\n",
        "docs/PRD-old.md": "eski\n",
        "README.md": "readme\n",
        "CHANGELOG.md": "changelog\n",
        "src/app.py": "print(1)\n",
    }
    for rel, text in own.items():
        _write(root, rel, text)
    return root, own


def test_preview_changes_nothing(tmp_path):
    root, _ = _populated_project(tmp_path)
    before = _digest_tree(root)
    res = migrate_docs(root, apply=False)
    assert res["applied"] is False and len(res["moved"]) == 10
    assert _digest_tree(root) == before
    assert not os.path.exists(os.path.join(root, "FS-docs"))


def test_apply_moves_only_known_files_and_leaves_user_files_untouched(tmp_path):
    root, own = _populated_project(tmp_path)
    before = _digest_tree(root)
    assert docs_root(root) == "docs"
    res = migrate_docs(root, apply=True)
    assert len(res["moved"]) == 10 and res["conflicts"] == []
    after = _digest_tree(root)

    # projenin kendi dosyaları baytı baytına aynı ve yerinde
    for rel in own:
        assert after.get(rel) == before[rel], rel
    # FS-SC dosyaları yeni yerde, içerik aynı, eski yerde yok
    for rel in ("PRD.md", "ARCHITECTURE.md", "uat/acceptance_criteria.md", "tasks/T-01.md", "tasks/task_7.md"):
        assert after[f"FS-docs/{rel}"] == before[f"docs/{rel}"]
        assert f"docs/{rel}" not in after
    # taşınanların dışında hiçbir dosya eklenmedi/silinmedi
    assert set(after) == (set(before) - {k for k in before if k.startswith("docs/") and k not in own}) | {
        "FS-docs/" + k[len("docs/"):] for k in before if k.startswith("docs/") and k not in own}
    assert docs_root(root) == "FS-docs"


def test_conflict_is_skipped_not_overwritten(tmp_path):
    root, _ = _populated_project(tmp_path)
    _write(root, "FS-docs/PRD.md", "YENI İÇERİK\n")
    res = migrate_docs(root, apply=True)
    assert any("PRD.md" in c for c in res["conflicts"])
    assert open(os.path.join(root, "FS-docs", "PRD.md"), encoding="utf-8").read() == "YENI İÇERİK\n"
    # çakışan eski dosya yerinde kaldı
    assert open(os.path.join(root, "docs", "PRD.md"), encoding="utf-8").read() == "fssc PRD.md\n"


def test_second_run_is_noop(tmp_path):
    root, _ = _populated_project(tmp_path)
    migrate_docs(root, apply=True)
    snapshot = _digest_tree(root)
    again = migrate_docs(root, apply=True)
    assert again["moved"] == [] and _digest_tree(root) == snapshot


def test_prompt_copies_are_rewritten_as_new_version(tmp_path):
    root, _ = _populated_project(tmp_path)
    from server.fs_workspace import save_agent_markdown, get_agent_markdown_info
    save_agent_markdown(root, "PM", "PM", "# PM\nYaz: `docs/prd/auth_service.md` ve docs/manuals/user_guide.md\n", "eski", author="t")
    res = migrate_docs(root, apply=True)
    assert "PM" in res["prompts_updated"]
    info = get_agent_markdown_info(root, "PM", "PM")
    assert "{docs_root}/PRD.md" in info["active_content"] and "{docs_root}/manuals/user_guide.md" in info["active_content"]
    assert "docs/prd" not in info["active_content"]
    assert len(info["versions"]) >= 2  # eski sürüm geçmişte duruyor


@pytest.mark.skipif(not HAS_GIT, reason="git yok")
def test_git_mv_keeps_history_and_does_not_touch_user_files(tmp_path):
    root, own = _populated_project(tmp_path)
    run = lambda *a: subprocess.run(["git", *a], cwd=root, check=True, capture_output=True, text=True)
    run("init", "-q")
    run("add", "-A")
    run("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "base")
    res = migrate_docs(root, apply=True)
    assert res["used_git_mv"] is True
    status = run("status", "--porcelain").stdout
    assert "R " in status or "R  " in status  # yeniden adlandırma olarak izleniyor
    for rel in own:
        assert rel not in status, f"kullanıcı dosyası değişmiş görünüyor: {rel}"


def test_api_preview_then_apply(client, hub, tmp_path):
    root, own = _populated_project(tmp_path)
    pid = hub.active_project_id
    hub.projects[pid]["path"] = root
    res = client.post(f"/api/projects/{pid}/migrate-docs", json={})
    assert res.status_code == 200 and res.json()["applied"] is False
    assert not os.path.exists(os.path.join(root, "FS-docs"))
    res = client.post(f"/api/projects/{pid}/migrate-docs", json={"apply": True})
    assert res.json()["applied"] is True and os.path.isfile(os.path.join(root, "FS-docs", "PRD.md"))
    assert hub.get_settings()["docs_root"] == "FS-docs"
    assert client.post("/api/projects/yok/migrate-docs", json={}).status_code == 404
