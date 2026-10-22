"""Koşu geçmişi kaybolsa da madde kanıtındaki commit'ler git geçmişinden (`feat(JIRA-n): ...`) okunur."""
import subprocess

from server import scm as SCM


def _git(cwd, *args):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=cwd, check=True, capture_output=True)


def test_commits_by_issue_ve_onbellek(tmp_path):
    d = str(tmp_path)
    _git(d, "init", "-q")
    (tmp_path / "a.txt").write_text("1")
    _git(d, "add", "."); _git(d, "commit", "-q", "-m", "feat(JIRA-72): AC-7 için test")
    (tmp_path / "a.txt").write_text("2")
    _git(d, "commit", "-q", "-am", "fix(JIRA-72): düzeltme 1")
    (tmp_path / "a.txt").write_text("3")
    _git(d, "commit", "-q", "-am", "chore: ilgisiz")
    SCM._ISSUE_COMMITS_CACHE.clear()
    got = SCM.commits_by_issue(d)
    assert list(got) == ["JIRA-72"] and [c["subject"].split(":")[0] for c in got["JIRA-72"]] == ["feat(JIRA-72)", "fix(JIRA-72)"]
    assert SCM.commits_by_issue(d) is got                                  # reflog değişmedi: önbellekten
    (tmp_path / "a.txt").write_text("4")
    _git(d, "commit", "-q", "-am", "feat(JIRA-73): yeni")
    assert "JIRA-73" in SCM.commits_by_issue(d)                            # yeni commit: yeniden okunur


def test_git_olmayan_klasor_bos_doner(tmp_path):
    assert SCM.commits_by_issue(str(tmp_path)) == {} and SCM.commits_by_issue("") == {}
