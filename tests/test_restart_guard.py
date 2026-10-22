"""Baştan başlat: ilerlemiş koşuyu çöpe atan `force_new` yalnızca panodaki iki aşamalı (proje adı) onayla yapılır; MCP aracı ve düz REST reddedilir.
Testler yalıtılmış hub'da çalışır; gerçek projelerin koşularına dokunmaz."""
import pytest

from server.engine.api import RunsApiError
from server.runs import PipelineRun, StepRecord


def _abandoned(hub, done=2, mode="legacy"):
    run = PipelineRun(project_id=hub.active_project_id)
    run.mode, run.status = mode, "ABANDONED"
    run.steps = [StepRecord(order=n, issue_id=f"JIRA-{n}", role="PM", kind="phase", status="DONE" if n <= done else "PENDING") for n in range(1, 5)]
    hub.runs[run.run_id] = run
    return run


def _api(hub):
    from server.engine.api import LocalRunsApi
    return LocalRunsApi(hub)


async def test_ilerlemis_kosuda_force_new_reddedilir(hub, tmp_project):
    run = _abandoned(hub, done=2)
    with pytest.raises(RunsApiError) as e:
        await _api(hub).start_run(project_id=hub.active_project_id, steps=[1, 2], engine="mcp_client", force_new=True)
    assert e.value.status_code == 409 and e.value.extra["code"] == "FORCE_NEW_NEEDS_CONFIRMATION"
    assert e.value.extra["run_id"] == run.run_id and e.value.extra["done_steps"] == 2
    assert run.status == "ABANDONED"                                       # hiçbir şey bırakılmadı


async def test_rest_force_new_de_reddedilir(client, hub, tmp_project):
    run = _abandoned(hub, done=1)
    r = client.post("/api/runs", json={"steps": [1, 2], "engine": "mcp_client", "force_new": True, "client": {"name": "t"}})
    assert r.status_code == 409 and r.json()["code"] == "FORCE_NEW_NEEDS_CONFIRMATION"
    assert hub.runs[run.run_id].status == "ABANDONED"


async def test_ilerlemesi_olmayan_kosu_icin_force_new_serbest(hub, tmp_project):
    _abandoned(hub, done=0)
    res = await _api(hub).start_run(project_id=hub.active_project_id, steps=[1, 2], engine="mcp_client", force_new=True)
    assert res["status"] == "STARTED"


async def test_onayli_yeniden_baslatma_proje_adini_ister(client, hub, tmp_project):
    run = _abandoned(hub, done=3)
    name = hub.projects[hub.active_project_id]["name"]
    bad = client.post(f"/api/runs/{run.run_id}/restart-fresh", json={"confirm_name": "yanlis"})
    assert bad.status_code == 400 and bad.json()["code"] == "CONFIRM_NAME_MISMATCH" and hub.runs[run.run_id].status == "ABANDONED"
    assert client.post(f"/api/runs/{run.run_id}/restart-fresh", json={}).status_code == 400           # ad yoksa da olmaz
    ok = client.post(f"/api/runs/{run.run_id}/restart-fresh", json={"confirm_name": name})
    assert ok.status_code == 200 and ok.json()["status"] == "STARTED"
    assert hub.runs[run.run_id].status == "CANCELLED" and hub.runs[run.run_id].cancel_reason == "restart-fresh"
    assert ok.json()["run"]["run_id"] != run.run_id


async def test_mcp_araci_force_new_ile_kosuyu_atamaz(patched_main, hub, tmp_project):
    from mcp import Client
    from mcp.types import Implementation
    from server import main as M
    run = _abandoned(hub, done=2)
    async with Client(M.mcp, client_info=Implementation(name="pytest", version="0")) as c:
        res = await c.call_tool("start_pipeline_run", {"steps": [1, 2], "force_new": True}, raise_on_error=False) if "raise_on_error" in c.call_tool.__code__.co_varnames else await c.call_tool("start_pipeline_run", {"steps": [1, 2], "force_new": True})
    text = res.content[0].text
    assert getattr(res, "is_error", getattr(res, "isError", True)) and "çöpe atar" in text and "proje adı" in text
    assert hub.runs[run.run_id].status == "ABANDONED"
