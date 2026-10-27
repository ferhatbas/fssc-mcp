"""Ekran sözleşmeleri (e2e/screens) proje kökünde kalır; yanlışlıkla apps/<uygulama>/e2e altına taşınmış olanlar köke geri alınır."""
import os
import time

from server import layout as LAY
from server.project_bootstrap import rehome_misplaced_contracts, sweep_stray_root_files


def _write(path, text, mtime=None):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    if mtime:
        os.utime(path, (mtime, mtime))


def test_contract_folder_is_not_relocated_into_an_app():
    layout = LAY.layout_of(type("H", (), {"get_settings": lambda self: {"project_layout": "apps"}})())
    if LAY.is_apps(layout):
        assert LAY.relocate(layout, "e2e/screens/giris.json", "FRONTEND_DEV", "docs") == "e2e/screens/giris.json"


def test_newer_misplaced_contract_replaces_root_copy(tmp_path):
    now = time.time()
    _write(str(tmp_path / "e2e/screens/giris.json"), "old", now - 100)
    _write(str(tmp_path / "apps/web/e2e/screens/giris.json"), "new", now)
    moved = rehome_misplaced_contracts(str(tmp_path))
    assert moved == ["giris.json"]
    assert (tmp_path / "e2e/screens/giris.json").read_text() == "new"
    assert not (tmp_path / "apps/web/e2e").exists()


def test_older_misplaced_contract_is_dropped(tmp_path):
    now = time.time()
    _write(str(tmp_path / "e2e/screens/giris.json"), "fresh", now)
    _write(str(tmp_path / "apps/web/e2e/screens/giris.json"), "stale", now - 100)
    rehome_misplaced_contracts(str(tmp_path))
    assert (tmp_path / "e2e/screens/giris.json").read_text() == "fresh"
    assert not (tmp_path / "apps/web/e2e/screens/giris.json").exists()


def test_sweep_also_rehomes_contracts(tmp_path):
    _write(str(tmp_path / "apps/web/e2e/screens/kayit.json"), "x")
    sweep_stray_root_files(str(tmp_path))
    assert (tmp_path / "e2e/screens/kayit.json").exists()
