"""SCM: atomik yazımın geçici dosyaları (.fs-workspace/*.tmp) git add'e girmez; böylece kaybolan geçici dosya commit'i düşürmez."""
import os
import subprocess

from server import scm


async def test_workspace_tmp_files_are_ignored_and_do_not_break_commit(tmp_path):
    d = str(tmp_path)
    os.makedirs(os.path.join(d, ".fs-workspace"))
    with open(os.path.join(d, "app.py"), "w", encoding="utf-8") as f:
        f.write("print(1)\n")
    with open(os.path.join(d, ".fs-workspace", "runs.json.tmp"), "w", encoding="utf-8") as f:
        f.write("{}")
    res = await scm.commit_all(d, "test")
    assert res["status"] == "COMMITTED", res
    files = subprocess.run(["git", "ls-files"], cwd=d, capture_output=True, text=True).stdout.split()
    assert "app.py" in files and not any(x.endswith(".tmp") for x in files)
