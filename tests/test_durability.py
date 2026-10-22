"""Veri dayanıklılığı: anlık görüntü, bütünlük uyarısı, geri yükleme, registry yedeği, test yalıtımı (gerçek registry/projeye dokunmama)."""
import json
import os

import pytest

from server import durability as DUR
from server import telemetry as TEL


def _ws(tmp_path):
    ws = tmp_path / ".fs-workspace"
    (ws / "specs").mkdir(parents=True, exist_ok=True)
    return ws


def _write(ws, jira=3, specs=1):
    (ws / "jira_issues.json").write_text(json.dumps({f"JIRA-{i}": {"id": f"JIRA-{i}"} for i in range(jira)}), encoding="utf-8")
    (ws / "specs" / "specs.json").write_text(json.dumps([{"id": f"S-{i}"} for i in range(specs)]), encoding="utf-8")
    (ws / "tasks.json").write_text("{}", encoding="utf-8")


def test_snapshot_degismediyse_yazilmaz_ve_budanir(tmp_path):
    ws = _ws(tmp_path)
    _write(ws, jira=10)
    first = DUR.snapshot_workspace(str(tmp_path), "startup")
    assert first and DUR.snapshot_workspace(str(tmp_path), "auto") is None              # aynı içerik
    _write(ws, jira=11)
    assert DUR.snapshot_workspace(str(tmp_path), "auto")
    snaps = DUR.list_snapshots(str(tmp_path))
    assert snaps[0]["counts"]["jira_issues.json"] == 11 and len(snaps) == 2
    for n in range(12, 20):                                                             # budama: en yeni 3 + zirve
        _write(ws, jira=n)
        DUR.snapshot_workspace(str(tmp_path), "auto", keep=3)
    names = {s["name"] for s in DUR.list_snapshots(str(tmp_path))}
    assert len(names) <= 4


def test_zirve_gorusu_hasarli_durum_iyi_goruntuyu_budamaz(tmp_path):
    ws = _ws(tmp_path)
    _write(ws, jira=50)
    good = DUR.snapshot_workspace(str(tmp_path), "startup")
    for n in range(1, 8):                                                               # hasarlı (küçük) durumlar çoğalır
        _write(ws, jira=n)
        DUR.snapshot_workspace(str(tmp_path), "auto", keep=3)
    assert good in {s["name"] for s in DUR.list_snapshots(str(tmp_path))}


def test_butunluk_uyarisi_ve_geri_yukleme(tmp_path):
    ws = _ws(tmp_path)
    _write(ws, jira=40, specs=2)
    good = DUR.snapshot_workspace(str(tmp_path), "startup")
    assert DUR.integrity_warnings(str(tmp_path)) == []
    _write(ws, jira=2, specs=0)                                                         # varsayılanla ezilme
    warns = {w["file"]: w for w in DUR.integrity_warnings(str(tmp_path))}
    assert warns["jira_issues.json"]["peak"] == 40 and warns["jira_issues.json"]["snapshot"] == good
    restored = DUR.restore_snapshot(str(tmp_path), good, files=["jira_issues.json", "specs/specs.json"])
    assert set(restored) == {"jira_issues.json", "specs/specs.json"}
    assert len(json.loads((ws / "jira_issues.json").read_text(encoding="utf-8"))) == 40
    assert any(s["reason"] == "pre-restore" for s in DUR.list_snapshots(str(tmp_path)))  # geri yükleme öncesi görüntü
    with pytest.raises(KeyError):
        DUR.restore_snapshot(str(tmp_path), "yok")


def test_registry_yedegi_donen_ve_tekrarsiz(tmp_path):
    reg = tmp_path / "history" / "projects_registry.json"
    reg.parent.mkdir()
    reg.write_text("{\"a\": 1}", encoding="utf-8")
    assert DUR.backup_registry(str(reg), keep=2)
    assert DUR.backup_registry(str(reg), keep=2) is None                                 # aynı içerik
    for n in range(2, 6):
        reg.write_text(json.dumps({"a": n}), encoding="utf-8")
        DUR.backup_registry(str(reg), keep=2)
    assert len(os.listdir(reg.parent / "backups")) == 2


def test_hub_baslangicta_yazmadan_once_goruntu_alir_ve_uyarir(tmp_path):
    project = tmp_path / "proj"
    ws = _ws(project)
    _write(ws, jira=30)
    DUR.snapshot_workspace(str(project), "earlier")
    _write(ws, jira=1)                                                                   # sunucu kapalıyken ezilmiş durum
    registry = tmp_path / "history" / "projects_registry.json"
    hub = TEL.TelemetryHub(registry_path=str(registry), default_project_path=str(project), flush_delay_s=0.0)
    assert any(w["file"] == "jira_issues.json" for w in hub.data_warnings.get("(varsayılan)", []))
    assert DUR.list_snapshots(str(project))[0]["reason"] in ("startup", "earlier")


def test_data_endpointleri(client, hub, tmp_project):
    ws = _ws(__import__("pathlib").Path(tmp_project))
    hub.projects[hub.active_project_id]["path"] = tmp_project
    hub.flush_now()                                    # bekleyen yazımlar testin dosyalarını sonradan ezmesin
    _write(ws, jira=25)
    created = client.post("/api/data/snapshots", json={"reason": "manual"}).json()
    assert created["snapshot"]
    _write(ws, jira=1)
    health = client.get("/api/data/health").json()
    assert any(w["file"] == "jira_issues.json" for w in health["warnings"]) and health["snapshots"]
    res = client.post(f"/api/data/snapshots/{created['snapshot']}/restore", json={"files": ["jira_issues.json"]})
    assert res.status_code == 200 and res.json()["restored"] == ["jira_issues.json"]
    assert "JIRA-24" in hub.jira_issues                                           # canlı durum diskten yeniden okundu
    assert client.post("/api/data/snapshots/yok/restore", json={}).status_code == 404
    assert client.get("/api/server/info").json()["data_warnings"] >= 0


def test_test_yalitimi_gercek_yollari_reddeder(monkeypatch):
    real_registry = os.path.join(TEL.REPO_ROOT, "history", "projects_registry.json")
    monkeypatch.setattr(TEL, "PROJECTS_REGISTRY_FILE", real_registry)
    with pytest.raises(RuntimeError):
        TEL._refuse_real_paths_under_pytest()
    monkeypatch.setattr(TEL, "PROJECTS_REGISTRY_FILE", os.path.join(os.environ["AGY_DATA_DIR"], "x.json"))
    monkeypatch.setattr(TEL, "DEFAULT_PROJECT_PATH", os.path.abspath(os.path.join(TEL.REPO_ROOT, "..", "demo_project")))
    with pytest.raises(RuntimeError):
        TEL._refuse_real_paths_under_pytest()
