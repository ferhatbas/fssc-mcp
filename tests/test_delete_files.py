"""Teslimde `payload.delete[]`: yalnızca var olan dosyalar silinir; korunan/yönetim yolları ve klasörler reddedilir."""
import pytest

from server.llm.parsing import StepOutputError
from server.pipeline import DELETE_LIMIT, delete_files


def _mk(root, rel, text="x"):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def test_deletes_existing_files(tmp_path):
    _mk(tmp_path, "apps/backend/src/a.ts")
    _mk(tmp_path, "apps/backend/src/b.ts")
    assert delete_files(str(tmp_path), ["apps/backend/src/a.ts", "apps/backend/src/b.ts"]) == ["apps/backend/src/a.ts", "apps/backend/src/b.ts"]
    assert not (tmp_path / "apps/backend/src/a.ts").exists()


def test_empty_is_noop(tmp_path):
    assert delete_files(str(tmp_path), None) == []
    assert delete_files(str(tmp_path), []) == []


@pytest.mark.parametrize("bad", ["../outside.txt", ".git/config", ".fs-workspace/settings.json", "README.md", "apps/web/package.json", "tsconfig.json"])
def test_rejects_protected_and_management_paths(tmp_path, bad):
    _mk(tmp_path, "README.md")
    _mk(tmp_path, "apps/web/package.json")
    _mk(tmp_path, "tsconfig.json")
    with pytest.raises(StepOutputError):
        delete_files(str(tmp_path), [bad])


def test_rejects_folder_and_missing(tmp_path):
    (tmp_path / "apps" / "x").mkdir(parents=True)
    with pytest.raises(StepOutputError):
        delete_files(str(tmp_path), ["apps/x"])
    with pytest.raises(StepOutputError):
        delete_files(str(tmp_path), ["apps/yok.ts"])


def test_rejects_non_list_and_limit(tmp_path):
    with pytest.raises(StepOutputError):
        delete_files(str(tmp_path), "apps/a.ts")
    names = [f"apps/f{i}.ts" for i in range(DELETE_LIMIT + 1)]
    for n in names:
        _mk(tmp_path, n)
    with pytest.raises(StepOutputError):
        delete_files(str(tmp_path), names)
