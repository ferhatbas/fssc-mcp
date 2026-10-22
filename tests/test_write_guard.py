"""F1 / A7: ajan teslimi `.fs-workspace/` ve `.git/` altına yazamaz (her yazım biçimiyle)."""

import os

import pytest

from server.llm.parsing import StepOutputError
from server.pipeline import write_files


@pytest.mark.parametrize("rel", [
    ".git/config", ".GIT/config", ".Git/hooks/pre-commit", "sub/.git/config",
    ".fs-workspace/settings.json", ".FS-WORKSPACE/jira_issues.json", ".fs-workspace/agents/PM.md",
    ".git./config", ".git /config", ".git::$INDEX_ALLOCATION/x", "GIT~1/config", "FS-WOR~1/settings.json",
    ".git\\config", ".fs-workspace\\settings.json",
])
def test_protected_paths_rejected(tmp_path, rel):
    with pytest.raises(StepOutputError):
        write_files(str(tmp_path), [{"path": rel, "content": "x"}])
    assert not os.path.exists(tmp_path / ".git") and not os.path.exists(tmp_path / ".fs-workspace")


def test_rejection_is_atomic_per_call_prefix(tmp_path):
    """Geçerli dosyadan sonra gelen korunan yol hata verir; hata öncesi yazılanlar yerinde kalır (mevcut davranış), korunan yol yazılmaz."""
    with pytest.raises(StepOutputError):
        write_files(str(tmp_path), [{"path": "src/a.py", "content": "1"}, {"path": ".git/HEAD", "content": "x"}])
    assert not os.path.exists(tmp_path / ".git")


@pytest.mark.parametrize("rel", ["src/a.py", "FS-docs/PRD.md", ".gitignore", ".github/workflows/ci.yml", ".env.example"])
def test_normal_paths_still_written(tmp_path, rel):
    assert write_files(str(tmp_path), [{"path": rel, "content": "ok"}]) == [rel]
    assert (tmp_path / rel).read_text(encoding="utf-8") == "ok"


def test_traversal_still_rejected(tmp_path):
    for rel in ("../x.txt", "a/../../x.txt"):
        with pytest.raises(StepOutputError):
            write_files(str(tmp_path), [{"path": rel, "content": "x"}])


@pytest.mark.skipif(os.name == "nt", reason="sembolik bağ oluşturma Windows'ta ayrıcalık ister")
def test_symlink_into_protected_dir_rejected(tmp_path):
    (tmp_path / ".git").mkdir()
    os.symlink(tmp_path / ".git", tmp_path / "gitlink")
    with pytest.raises(StepOutputError):
        write_files(str(tmp_path), [{"path": "gitlink/config", "content": "x"}])


def test_envelope_with_protected_path_is_rejected_via_api(client, hub, tmp_project):
    """Uçtan uca: LLM zarfı .fs-workspace'e yazmaya çalışırsa adım REJECTED döner ve dosya oluşmaz."""
    import json
    hub.step_by_step_mode = False
    res = client.post("/api/runs", json={"steps": [1], "engine": "mcp_client", "client": {"name": "curl", "version": "1"}})
    assert res.status_code == 200, res.text
    rid = res.json()["run"]["run_id"]
    assert client.post(f"/api/runs/{rid}/next-step", json={"client": {"name": "curl"}}).json()["status"] == "STEP"
    evil = os.path.join(tmp_project, ".fs-workspace", "evil.json")
    env = {"from_agent": "PM", "to_agent": "ARCHITECT", "intent": "TASK_DISPATCH", "status": "SUCCESS",
           "payload": {"summary": "x", "files": [{"path": "docs/PRD.md", "content": "# PRD"}, {"path": ".fs-workspace/evil.json", "content": "{}"}]}, "metadata": {"tokens_used": 1}}
    out = client.post(f"/api/runs/{rid}/steps/1/result", json={"result_json": json.dumps(env)}).json()
    assert out["status"] == "REJECTED", out
    assert any("Korunan yol" in e for e in out["validation_errors"]), out
    assert not os.path.exists(evil)
