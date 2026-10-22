"""F1: `docs_root` yardımcısı, belirteç çözümü ve eski düzen (göç etmemiş proje) davranışı."""

import os
import time

import pytest

from server.paths import (DEFAULT_DOCS_ROOT, docs_path, docs_root, is_protected_path, resolve_tokens, sanitize_docs_root)


def _legacy_project(root, files=("PRD.md", "ARCHITECTURE.md", "openapi_spec.json")):
    (root / ".fs-workspace").mkdir(parents=True, exist_ok=True)
    docs = root / "docs"
    docs.mkdir(exist_ok=True)
    for name in files:
        (docs / name).write_text("eski", encoding="utf-8")
    return str(root)


def test_new_project_uses_fs_docs(tmp_path):
    assert docs_root(str(tmp_path)) == DEFAULT_DOCS_ROOT == "FS-docs"
    assert docs_path(str(tmp_path), "PRD.md") == "FS-docs/PRD.md"


def test_legacy_layout_detected_only_with_known_files(tmp_path):
    legacy = _legacy_project(tmp_path / "a")
    assert docs_root(legacy) == "docs"
    # projenin kendi docs/ klasörü (FS-SC dosyası yok) eski düzen sayılmaz
    own = tmp_path / "b"
    (own / ".fs-workspace").mkdir(parents=True)
    (own / "docs").mkdir()
    (own / "docs" / "guide.md").write_text("x", encoding="utf-8")
    assert docs_root(str(own)) == "FS-docs"
    # tek bir bilinen dosya (PRD.md) tek başına yetmez
    one = _legacy_project(tmp_path / "c", files=("PRD.md",))
    assert docs_root(one) == "FS-docs"
    # .fs-workspace yoksa FS-SC projesi değildir
    no_ws = tmp_path / "d"
    (no_ws / "docs").mkdir(parents=True)
    for n in ("PRD.md", "ARCHITECTURE.md"):
        (no_ws / "docs" / n).write_text("x", encoding="utf-8")
    assert docs_root(str(no_ws)) == "FS-docs"


def test_fs_docs_existing_or_setting_wins(tmp_path):
    legacy = _legacy_project(tmp_path / "a")
    assert docs_root(legacy, "belgeler") == "belgeler"
    os.makedirs(os.path.join(legacy, "FS-docs"))
    assert docs_root(legacy) == "FS-docs"


@pytest.mark.parametrize("bad", ["", ".", "..", "../x", "a/../b", "/abs", "C:/x", ".git", ".fs-workspace", "x/.GIT", "docs.", None, 5, "a:b"])
def test_sanitize_rejects_unsafe(bad):
    assert sanitize_docs_root(bad) is None


def test_sanitize_accepts_relative():
    assert sanitize_docs_root("FS-docs") == "FS-docs"
    assert sanitize_docs_root("team\\docs/") == "team/docs"
    assert sanitize_docs_root("\\team") is None  # baştaki ayraç mutlak yol sayılır


def test_resolve_tokens_deep():
    out = resolve_tokens({"a": ["<docs>/x.md", {"b": "{docs_root}/y"}], "n": 3}, "FS-docs")
    assert out == {"a": ["FS-docs/x.md", {"b": "FS-docs/y"}], "n": 3}


@pytest.mark.parametrize("rel", [".git/config", ".GIT/config", ".fs-workspace/settings.json", ".Fs-Workspace/x", "sub/.git/hooks/pre-commit",
                                 ".git./config", ".git /config", ".git::$INDEX_ALLOCATION/x", "GIT~1/config", "FS-WOR~1/settings.json",
                                 ".git\\config"])
def test_protected_paths(rel):
    assert is_protected_path(rel)


@pytest.mark.parametrize("rel", ["src/main.py", "FS-docs/PRD.md", ".gitignore", ".github/workflows/ci.yml", "docs/.gitkeep", ".gitattributes", "fs-workspace-notes.md"])
def test_unprotected_paths(rel):
    assert not is_protected_path(rel)


def _wait_done(client, run_id, timeout=30.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        run = client.get(f"/api/runs/{run_id}").json()["run"]
        if run["is_terminal"]:
            return run
        time.sleep(0.1)
    raise AssertionError("timeout")


def test_unmigrated_project_keeps_writing_to_docs(client, hub, tmp_project):
    """Göç etmemiş (eski düzen) proje bozulmaz: çıktılar docs/ altında kalır, FS-docs/ oluşmaz."""
    from pathlib import Path
    _legacy_project(Path(tmp_project))
    hub.step_by_step_mode = False
    res = client.post("/api/runs", json={"steps": [1, 2], "engine": "template", "step_by_step": False, "prompt": "Test"})
    assert res.status_code == 200, res.text
    done = _wait_done(client, res.json()["run"]["run_id"])
    assert done["status"] == "COMPLETED", done
    assert os.path.isfile(os.path.join(tmp_project, "docs", "PRD.md"))
    assert os.path.getsize(os.path.join(tmp_project, "docs", "PRD.md")) > 10
    assert not os.path.exists(os.path.join(tmp_project, "FS-docs"))


def test_new_project_run_writes_only_fs_docs(client, hub, tmp_project):
    hub.step_by_step_mode = False
    res = client.post("/api/runs", json={"steps": [1, 2, 3, 5, 8, 10], "engine": "template", "step_by_step": False, "prompt": "Test"})
    done = _wait_done(client, res.json()["run"]["run_id"])
    assert done["status"] == "COMPLETED", done
    for rel in ("PRD.md", "openapi_spec.json", "handshake_sync.json", "manuals/user_guide.md", "reports/status_report.md"):
        assert os.path.isfile(os.path.join(tmp_project, "FS-docs", *rel.split("/"))), rel
    assert not os.path.exists(os.path.join(tmp_project, "docs"))
    # sabit "docs/" yolu içeren çözülmemiş belirteç ya da eski yol dosyalara sızmamalı
    for cur, _, files in os.walk(os.path.join(tmp_project, "FS-docs")):
        for f in files:
            text = open(os.path.join(cur, f), encoding="utf-8", errors="ignore").read()
            assert "<docs>" not in text and "{docs_root}" not in text, f
