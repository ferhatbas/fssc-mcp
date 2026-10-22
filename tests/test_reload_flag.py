"""`--reload` geliştirme kipi: yalnızca web modunda; Windows'ta asyncio alt süreçleri (doğrulama komutları) bozulmamalı."""

import asyncio
import subprocess
import sys

import pytest

import server.main as main_module


def _run_main(monkeypatch, argv):
    calls = []
    monkeypatch.setattr(main_module.uvicorn, "run", lambda *a, **kw: calls.append((a, kw)))
    monkeypatch.setattr(sys, "argv", ["server.main", *argv])
    main_module.main()
    return calls


def test_reload_runs_uvicorn_with_import_string_and_watches_server_dir(monkeypatch):
    (args, kwargs), = _run_main(monkeypatch, ["--mode", "web", "--reload"])
    assert args == ("server.main:app",) and kwargs["reload"] is True
    assert kwargs["reload_dirs"] and kwargs["reload_dirs"][0].endswith("server")


@pytest.mark.skipif(not sys.platform.startswith("win"), reason="SelectorEventLoop sorunu yalnızca Windows'ta")
def test_reload_keeps_proactor_loop_on_windows(monkeypatch):
    """Regresyon: uvicorn reload kipi Windows'ta SelectorEventLoop kurar ve asyncio alt süreçleri NotImplementedError verir."""
    (_, kwargs), = _run_main(monkeypatch, ["--mode", "web", "--reload"])
    assert kwargs["loop"] == "none"


@pytest.mark.skipif(not sys.platform.startswith("win"), reason="Windows'a özgü")
def test_default_event_loop_can_spawn_shell_subprocess():
    """Reload'suz varsayılan döngü (Proactor) kabuk komutu başlatabilmeli; doğrulama koşucusu buna dayanır."""
    from server.verify import run_command
    res = asyncio.run(run_command(f'"{sys.executable}" -c "print(1)"', ".", 20))
    assert res["exit_code"] == 0 and "Komut başlatılamadı" not in res["output"]


def test_reload_requires_web_mode(monkeypatch):
    with pytest.raises(SystemExit):
        _run_main(monkeypatch, ["--mode", "stdio", "--reload"])
