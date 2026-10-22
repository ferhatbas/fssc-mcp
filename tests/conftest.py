"""
Ortak pytest fixture'ları.

Tüm testler izole bir `TelemetryHub` ile çalışır: kayıt dosyası ve varsayılan proje
klasörü geçici dizinlerdedir; `server.main.hub` bu örnekle değiştirilir. Böylece test
koşmak gerçek `history/projects_registry.json` dosyasına dokunmaz.
"""

import os
import sys

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# Statik klasörler (uploads/, reports/screenshots/) import anında oluşturulur;
# testlerde geçici bir veri dizinine yönlendirilir. server.* modülleri bundan sonra import edilmeli.
_DATA_DIR = os.environ.setdefault("AGY_DATA_DIR", os.path.join(ROOT, ".pytest_data"))
os.makedirs(_DATA_DIR, exist_ok=True)

# VERİ KAYBI ÖNLEMİ: `server.telemetry` içe aktarılınca modül düzeyinde bir TelemetryHub kurulur ve registry + varsayılan proje (../demo_project)
# diske yazılır. Bu yollar HER ZAMAN geçici dizine zorlanır (kullanıcının gerçek ortamında ayarlı olsa bile).
os.environ["AGY_REGISTRY_PATH"] = os.path.join(_DATA_DIR, "sandbox_history", "projects_registry.json")
os.environ["AGY_DEFAULT_PROJECT"] = os.path.join(_DATA_DIR, "sandbox_default_project")

from server.telemetry import TelemetryHub  # noqa: E402


@pytest.fixture(autouse=True)
def isolated_agent_registry(tmp_path, monkeypatch):
    """G6: şirket geneli ajan kaydı (agents/registry.json) testlerde geçici dosyaya yazılır; gerçek kayda dokunulmaz."""
    path = tmp_path / "global_agents" / "registry.json"
    monkeypatch.setenv("FSSC_AGENT_REGISTRY", str(path))
    return path


@pytest.fixture
def tmp_project(tmp_path):
    """Pipeline çıktılarının yazılacağı geçici hedef proje klasörü."""
    project_dir = tmp_path / "target_project"
    project_dir.mkdir()
    return str(project_dir)


@pytest.fixture
async def hub(tmp_path, tmp_project):
    """Geçici registry ve hedef projeyle izole TelemetryHub (yazıcı gecikmesi 0); kapanışta flush edilir."""
    registry = tmp_path / "history" / "projects_registry.json"
    instance = TelemetryHub(
        registry_path=str(registry),
        default_project_path=tmp_project,
        flush_delay_s=0.0,
    )
    # Teknoloji kararları kapısı (adım >= 2) genel testleri engellemesin: önerilenler hazır cevaplanmış gelsin.
    # Kapının kendisi tests/test_decisions.py içinde ayrıca test edilir (orada temizlenir).
    # F2: kapıyı yalnızca onaylı bir tech_requirements kaydı geçirir (önceden dolu tech_decisions kapıyı geçirmez).
    from server.decisions import DEFAULT_TECH_QUESTIONS, auto_answers, make_decisions
    from server.tech_requirements import apply_approval, build_requirements
    approved_req = build_requirements(DEFAULT_TECH_QUESTIONS, "", "", tmp_project)
    apply_approval(approved_req, accept_recommended=True, by="TEST")
    approved_req["first_approved_at"] = "2026-01-01T00:00:00+00:00"
    instance.settings = {
        **(instance.settings or {}),
        "tech_requirements": approved_req,
        "tech_decisions": make_decisions(DEFAULT_TECH_QUESTIONS, auto_answers(DEFAULT_TECH_QUESTIONS), "", "user"),
        # Tam yaşam döngüsü yan etkileri (gerçek test/build komutları, git commit) genel testlerde kapalı;
        # tests/test_lifecycle.py bunları açıkça açar.
        "auto_verify": False,
        "auto_commit": False,
        # Sprint kipi varsayılanda açık; genel testler sabit 1-10 akışı bekler (sprint testleri kendi açar).
        "sprint": {"enabled": False},
        # G1: sıkı DoD ve proje sanal ortamı varsayılanda açık; genel testler eski (hızlı) davranışı bekler, G1 testleri kendi açar.
        "autonomy": {"strict_dod": False},
        "python_isolation": "host",
        # Arayüz işi varken otomatik tasarım görevi (DESIGNER) genel testlerde kapalı; tests/test_designer.py açıkça açar.
        "design_first": False,
    }
    yield instance
    await instance.aclose()


@pytest.fixture
def patched_main(hub, monkeypatch):
    """server.main (ve runner'ın varsayılan hub'ı) izole hub'ı kullansın."""
    import server.main as main_module
    import server.telemetry as telemetry_module

    monkeypatch.setattr(main_module, "hub", hub)
    monkeypatch.setattr(telemetry_module, "hub", hub)
    return main_module


@pytest.fixture
def client(patched_main):
    """FastAPI TestClient (lifespan dahil)."""
    from fastapi.testclient import TestClient

    with TestClient(patched_main.app) as c:
        yield c
