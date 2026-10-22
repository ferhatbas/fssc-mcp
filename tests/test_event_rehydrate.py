"""Registry boşalsa bile canlı olay akışı `.fs-workspace/events.jsonl` dosyasından geri yüklenir; olay kimlikleri çakışmaz."""
import copy

from server.event_store import append_event, tail_events


def _evt(n):
    return {"id": f"evt-{n:06d}", "type": "AGENT_INTERACTION", "from_agent": "PM", "to_agent": "ARCHITECT", "action": "A",
            "timestamp": f"2026-10-13T10:00:{n:02d}+00:00"}


def test_tail_events_sirali_ve_sinirli(tmp_path):
    for n in (3, 1, 2, 5, 4):
        append_event(str(tmp_path), _evt(n))
    assert [e["id"] for e in tail_events(str(tmp_path), 3)] == ["evt-000003", "evt-000004", "evt-000005"]
    assert tail_events(str(tmp_path / "yok"), 3) == [] and tail_events("", 3) == []


def test_bos_registry_olaylari_dosyadan_yukler(hub, tmp_path):
    for n in range(1, 8):
        append_event(str(tmp_path), _evt(n))
    proj = {"path": str(tmp_path), "events": [], "tasks": {}}
    hub._load_active_from_projects(proj)
    assert len(hub.events) == 7
    assert hub._event_seq == 7                  # yeni olay evt-000008 olur, dosyadakilerle çakışmaz


def test_dolu_registry_dosyayla_ezilmez(hub, tmp_path):
    append_event(str(tmp_path), _evt(1))
    mem = copy.deepcopy(_evt(9))
    hub._load_active_from_projects({"path": str(tmp_path), "events": [mem], "tasks": {}})
    assert [e["id"] for e in hub.events] == ["evt-000009"]


# ---- Kalıcılık boşlukları: koşu geçmişi, E2E raporları, müzakere oturumları, küçülerek ezme ----
import json
import os

from server import fs_workspace as FW
from server.runs import PipelineRun


def _write_ws(path, **proj_extra):
    proj = {"id": "p", "name": "p", "jira_issues": {"JIRA-1": {"id": "JIRA-1"}}, "tasks": {}, "uploaded_specs": [], "stats": {}, **proj_extra}
    FW.write_files_atomic(FW.build_workspace_files(str(path), proj))


def test_runs_json_registry_bos_olsa_da_geri_yuklenir(hub, tmp_path):
    done = PipelineRun(project_id="p", run_id="run-done", status="COMPLETED").to_dict()
    live = PipelineRun(project_id="p", run_id="run-live", status="ACTIVE").to_dict()
    _write_ws(tmp_path, runs=[done, live])
    hub.runs.clear()
    hub._apply_workspace_overrides({"path": str(tmp_path)}, str(tmp_path))
    assert set(hub.runs) == {"run-done", "run-live"}
    assert hub.runs["run-done"].status == "COMPLETED"
    assert hub.runs["run-live"].status == "ABANDONED"            # sunucu yeniden başladı
    hub._apply_workspace_overrides({"path": str(tmp_path)}, str(tmp_path))   # ikinci yükleme çoğaltmaz
    assert len(hub.runs) == 2


def test_playwright_raporlari_calisma_klasorunden_yuklenir(hub, tmp_path):
    _write_ws(tmp_path, playwright_reports=[{"id": "r1", "status": "PASSED"}])
    proj = {"path": str(tmp_path), "playwright_reports": []}
    hub._apply_workspace_overrides(proj, str(tmp_path))
    assert proj["playwright_reports"] == [{"id": "r1", "status": "PASSED"}]


def test_muzakere_oturumlari_kalici(hub, tmp_path):
    hub.deliberation_engine.open({"title": "Mimari", "session_id": "DELIB-1"})
    hub.deliberation_engine.active_session.add_message("PM", "PM", "Plan A", "PROPOSAL")
    snap = hub.deliberation_engine.snapshot()
    _write_ws(tmp_path, deliberation=snap)
    hub.deliberation_engine.restore(None)
    assert hub.deliberation_engine.get_latest_session() is None
    proj = {"path": str(tmp_path)}
    hub._apply_workspace_overrides(proj, str(tmp_path))
    hub._load_active_from_projects(proj)
    latest = hub.deliberation_engine.get_latest_session()
    assert latest["session_id"] == "DELIB-1" and latest["messages"][0]["message"] == "Plan A"


def test_buyuk_dosya_kucuk_icerikle_ezilirse_yedek_kalir(tmp_path):
    f = tmp_path / "jira_issues.json"
    f.write_text("x" * 30_000, encoding="utf-8")
    FW.write_files_atomic({str(f): "{}"})
    assert f.read_text(encoding="utf-8") == "{}"
    assert (tmp_path / "jira_issues.json.shrunk.bak").read_text(encoding="utf-8") == "x" * 30_000
    g = tmp_path / "kucuk.json"                                 # küçük dosyada yedek üretilmez
    g.write_text("abc", encoding="utf-8")
    FW.write_files_atomic({str(g): "{}"})
    assert not os.path.exists(str(g) + ".shrunk.bak")


def test_baslik_sayaclari_olaylardan_yeniden_turetilir(hub, tmp_path):
    for n in range(1, 6):
        e = _evt(n)
        e["tokens_used"] = 100
        append_event(str(tmp_path), e)
    proj = {"path": str(tmp_path), "events": [], "tasks": {"T-1": {}, "T-2": {}}, "stats": {"total_events": 0, "total_tokens": 0}}
    hub._load_active_from_projects(proj)
    assert hub.stats["total_events"] == 5 and hub.stats["total_tokens"] == 500 and hub.stats["active_tasks_count"] == 2
    assert hub.agents["PM"]["total_tokens"] == 500


def test_sayaclar_registry_sifir_kaydetmis_olsa_da_duzelir(hub, tmp_path):
    evs = []
    for n in range(1, 4):
        e = _evt(n)
        e["tokens_used"] = 10
        evs.append(e)
    proj = {"path": str(tmp_path), "events": evs, "tasks": {}, "stats": {"total_events": 0, "total_tokens": 0}}
    hub._load_active_from_projects(proj)
    assert hub.stats["total_events"] == 3 and hub.stats["total_tokens"] == 30
    big = {"path": str(tmp_path), "events": evs, "tasks": {}, "stats": {"total_events": 900, "total_tokens": 5000}}
    hub._load_active_from_projects(big)                                  # birikimli sayaç düşürülmez
    assert hub.stats["total_events"] == 900 and hub.stats["total_tokens"] == 5000
