"""Koşu bekçisi: çalışırken 10 dk, duraklatılmışken 30 dk yoklama aralığı; izlenen iş; takvimi okuyan MCP aracı ve ayar ucu."""
import json

from server import driver as DRV
from server import sprint as SP
from server.runs import PipelineRun, StepRecord


def _abandoned(hub):
    run = PipelineRun(project_id=hub.active_project_id)
    run.mode = "sprint"
    run.status = "ABANDONED"
    run.steps = [StepRecord(order=5, issue_id="JIRA-5", role="BACKEND_DEV", kind="phase", status="DONE"),
                 StepRecord(order=6, issue_id="JIRA-6", role="QA", kind="phase", status="PENDING")]
    hub.runs[run.run_id] = run
    return run


def test_varsayilan_araliklar_ve_sinirlar():
    c = DRV.sanitize_runner({})
    assert c["interval_min"] == 10 and c["interval_paused_min"] == 30
    assert DRV.sanitize_runner({"interval_paused_min": 99999})["interval_paused_min"] == 1440
    assert DRV.sanitize_runner({"interval_paused_min": 0})["interval_paused_min"] == 1
    assert DRV.sanitize_runner({"interval_min": "x"})["interval_min"] == 10


async def test_duraklatilmis_uygulamada_aralik_uzar(hub, tmp_project):
    assert DRV.check_interval_min(hub) == 10 and DRV.runner_schedule(hub)["paused"] is False
    SP.ensure_state(hub)["project_status"] = "PAUSED"
    s = DRV.runner_schedule(hub)
    assert s["paused"] is True and s["interval_minutes"] == 30 and s["suggested_cron"] == "*/30 * * * *"
    SP.ensure_state(hub)["project_status"] = "ACTIVE"
    run = _abandoned(hub)
    run.paused = True                                                   # yalnızca izlenen koşu duraklatıldı
    assert DRV.check_interval_min(hub) == 30
    await hub.update_settings({"runner": {"interval_min": 5, "interval_paused_min": 90}})
    assert DRV.check_interval_min(hub) == 90 and DRV.runner_schedule(hub)["suggested_cron"] == "0 */2 * * *"
    run.paused = False
    assert DRV.check_interval_min(hub) == 5


async def test_izlenen_is_terk_edilmis_kosu_ve_takili(hub, tmp_project):
    assert DRV.runner_schedule(hub)["job"] is None
    run = _abandoned(hub)
    job = DRV.runner_schedule(hub)["job"]
    assert job["run_id"] == run.run_id and job["status"] == "ABANDONED" and job["stalled"] is True
    assert job["done_steps"] == 1 and job["total_steps"] == 2
    run.status = "ACTIVE"                                               # canlı ve taze: takılı değil
    run.touch()
    assert DRV.runner_schedule(hub)["job"]["stalled"] is False


async def test_ayar_ve_takvim_uclari(client, hub, tmp_project):
    res = client.post("/api/settings/runner", json={"interval_min": 7, "interval_paused_min": 45, "abandon_factor": 4}).json()
    assert res["runner"]["interval_min"] == 7 and res["runner"]["interval_paused_min"] == 45
    s = client.get("/api/runner/schedule").json()
    assert s["active_interval_min"] == 7 and s["paused_interval_min"] == 45 and s["abandon_after_min"] == 28 and s["interval_minutes"] == 7
    out = client.post("/api/runner/check-now").json()
    assert out["auto_state"]["last_reason"] == "DISABLED" and out["schedule"]["interval_minutes"] == 7        # otomatik runner kapalı: oturum açılmaz
    st = client.get("/api/runner/setup").json()
    assert st["auto_runner"]["interval_min"] == 7


async def test_mcp_araci_takvimi_okur(hub, tmp_project):
    from mcp import Client
    from mcp.types import Implementation
    from server import main as M
    async with Client(M.mcp, client_info=Implementation(name="pytest", version="0")) as c:
        text = (await c.call_tool("get_runner_schedule", {})).content[0].text
    data = json.loads(text)
    assert data["interval_minutes"] == 10 and data["paused_interval_min"] == 30 and "suggested_cron" in data


# ---------------------------------------------------------------------------
# Yapay zekânın zamanlanmış görevi talimatlardan okuyup kendisinin kurması: görev metni, eylem ve koşu başlatma yanıtındaki ipucu
# ---------------------------------------------------------------------------
async def test_takvim_gorev_metni_ve_eylem_verir(hub, tmp_project):
    s = DRV.runner_schedule(hub)
    assert s["action"] == "none_or_delete_if_exists" and s["job"] is None and s["task_name"].startswith("FS-SC koşu bekçisi")
    assert "0. get_runner_schedule çağır" in s["task_prompt"] and "1. claim_work çağır" in s["task_prompt"]
    _abandoned(hub)
    s = DRV.runner_schedule(hub)
    assert s["action"] == "create_or_update_scheduled_task" and s["runner_fresh"] is False          # iş var, claim_work çağıran görev görünmüyor
    DRV.seen(hub, {"name": "scheduled-task"})                                                        # zamanlanmış görev yakın zamanda çağırdı
    s = DRV.runner_schedule(hub)
    assert s["runner_fresh"] is True and s["action"] == "update_interval_if_different"


async def test_kosu_baslatma_yanitinda_ipucu(hub, tmp_project):
    from server.engine.api import LocalRunsApi
    api = LocalRunsApi(hub)
    res = await api.start_run(project_id=hub.active_project_id, steps=[1, 2], engine="mcp_client")
    assert res["status"] == "STARTED" and res["schedule_hint"]["action"] == "create_or_update_scheduled_task"
    assert res["schedule_hint"]["interval_minutes"] == 10 and "get_runner_schedule" in res["schedule_hint"]["message"]
    DRV.seen(hub, {"name": "scheduled-task"})                                                        # görev çalışıyorsa ipucu gelmez
    again = await api.start_run(project_id=hub.active_project_id, steps=[1, 2], engine="mcp_client")
    assert "schedule_hint" not in again
