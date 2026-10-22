"""
Koşu REST ikizleri ve şablon motoru uçtan uca (TestClient + izole hub).
"""

import asyncio
import json
import os
import time

import pytest


def _wait_for(client, run_id, predicate, timeout=20.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        run = client.get(f"/api/runs/{run_id}").json()["run"]
        if predicate(run):
            return run
        time.sleep(0.1)
    raise AssertionError(f"timeout waiting for run {run_id}")


def test_template_engine_runs_to_completion_without_approval(client, hub, tmp_project, monkeypatch):
    """Şablon motoru: onay kapalıyken adım 1-3 (LLM) + 5 (sunucu) kendi kendine tamamlanır, dosyalar yazılır."""
    hub.step_by_step_mode = False
    res = client.post("/api/runs", json={"steps": [1, 2, 3, 5], "engine": "template", "step_by_step": False, "prompt": "Test"})
    assert res.status_code == 200, res.text
    run = res.json()["run"]
    assert run["engine"] == "template" and run["status"] in ("ACTIVE", "COMPLETED")

    done = _wait_for(client, run["run_id"], lambda r: r["is_terminal"])
    assert done["status"] == "COMPLETED", done
    # Mimari adımı (2) şablonda 2 backlog görevi üretir; sunucu bunları iskeletten (3) sonra, el sıkışmadan (5) önce ekler
    assert [s["order"] for s in done["steps"]] == [1, 2, 3, 11, 12, 5]
    assert [s["kind"] for s in done["steps"]] == ["phase", "phase", "phase", "task", "task", "phase"]
    assert [s["status"] for s in done["steps"]] == ["DONE"] * 6
    assert done["backlog_expanded"] is True and done["progress"]["tasks"] == 2
    for rel in ("FS-docs/PRD.md", "FS-docs/openapi_spec.json", "src/main.py", "src/auth.py", "FS-docs/handshake_sync.json", "FS-docs/tasks/T-01.md"):
        assert os.path.isfile(os.path.join(tmp_project, rel)), rel
    assert hub.jira_issues["JIRA-3"]["status"] == "DONE"
    assert hub.jira_issues["JIRA-11"]["kind"] == "task" and hub.jira_issues["JIRA-11"]["parent_id"] == "JIRA-2"
    assert hub.jira_issues["JIRA-12"]["assignee"] == "FRONTEND_DEV" and hub.jira_issues["JIRA-12"]["status"] == "DONE"
    assert hub.get_settings()["verification"]["test"] == "python -m pytest -q"
    actions = [e["action"] for e in hub.events]
    assert "A2A_CONTRACT_SYNC" in actions and "A2A_CONTRACT_CONFIRM" in actions
    assert hub.active_run_id is None


def test_template_engine_waits_for_approval_and_rest_approve_advances(client, hub, tmp_project):
    hub.step_by_step_mode = True
    res = client.post("/api/runs", json={"steps": [1, 2], "engine": "template", "step_by_step": True})
    assert res.status_code == 200
    run_id = res.json()["run"]["run_id"]

    waiting = _wait_for(client, run_id, lambda r: r["status"] == "WAITING_APPROVAL")
    assert waiting["steps"][0]["status"] == "WAITING_APPROVAL"
    pending = client.get("/api/pipeline/pending-step").json()["pending_step"]
    assert pending["order"] == 1 and pending["run_id"] == run_id

    # İkinci koşu → 409 (proje başına tek aktif koşu)
    dup = client.post("/api/runs", json={"steps": [1], "engine": "template"})
    assert dup.status_code == 409 and dup.json()["status"] == "EXISTING"

    ok = client.post("/api/pipeline/approve-step", json={"decision": "PROCEED", "token": pending["approval_token"]})
    assert ok.status_code == 200
    waiting2 = _wait_for(client, run_id, lambda r: r["status"] == "WAITING_APPROVAL" and r["cursor"] == 1)
    assert waiting2["steps"][1]["status"] == "WAITING_APPROVAL"

    pending2 = client.get("/api/pipeline/pending-step").json()["pending_step"]
    client.post("/api/pipeline/approve-step", json={"decision": "AUTO_ALL", "token": pending2["approval_token"]})
    done = _wait_for(client, run_id, lambda r: r["is_terminal"])
    assert done["status"] == "COMPLETED"


def test_rest_pull_flow_mirrors_mcp_tools(client, hub, tmp_project):
    hub.step_by_step_mode = False
    res = client.post("/api/runs", json={"steps": [1], "engine": "mcp_client", "client": {"name": "curl", "version": "1"}})
    assert res.status_code == 200
    run = res.json()["run"]
    assert run["status"] == "QUEUED"

    nxt = client.post(f"/api/runs/{run['run_id']}/next-step", json={"client": {"name": "curl"}}).json()
    assert nxt["status"] == "STEP" and nxt["order"] == 1
    assert "system_prompt" in nxt and "output_contract" in nxt

    envelope = {
        "from_agent": "PM", "to_agent": "ARCHITECT", "intent": "TASK_DISPATCH", "status": "SUCCESS",
        "payload": {"summary": "ok", "files": [{"path": "docs/PRD.md", "content": "# PRD"}]},
        "metadata": {"tokens_used": 10},
    }
    sub = client.post(f"/api/runs/{run['run_id']}/steps/1/result", json={"result_json": json.dumps(envelope)}).json()
    assert sub["status"] == "RUN_COMPLETE", sub
    assert client.get(f"/api/runs/{run['run_id']}").json()["run"]["status"] == "COMPLETED"
    assert client.get("/api/mcp/clients").json()["clients"][0]["name"] == "curl"


def test_engine_settings_roundtrip_and_validation(client, hub):
    assert client.get("/api/settings/engine").json()["settings"]["execution_engine"] == "mcp_client"
    res = client.post("/api/settings/engine", json={"execution_engine": "template", "approval_mode": "critical_only", "pacing": "bogus"})
    settings = res.json()["settings"]
    assert settings["execution_engine"] == "template"
    assert settings["approval_mode"] == "critical_only"
    assert settings["pacing"] == "natural"  # geçersiz değer yok sayıldı
    assert hub.projects[hub.active_project_id]["settings"]["execution_engine"] == "template"


def test_execute_batch_uses_template_engine(client, hub, tmp_project):
    hub.step_by_step_mode = False
    res = client.post("/api/jira/execute-batch", json={"selected_issues": [1], "step_by_step": False})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["engine"] == "template" and body["run_id"]
    done = _wait_for(client, body["run_id"], lambda r: r["is_terminal"])
    assert done["status"] == "COMPLETED"


def test_runs_survive_restart_as_abandoned(hub, tmp_project):
    """Registry'ye yazılan sonlanmamış koşu, yeni hub'da ABANDONED olarak yüklenir."""
    from server.runs import build_run
    from server.telemetry import TelemetryHub

    run = build_run(hub.active_project_id, tmp_project, hub.get_jira_issues(), [1, 2], engine="mcp_client")
    run.status = "ACTIVE"
    hub.register_run(run)
    hub.flush_now()

    reloaded = TelemetryHub(registry_path=hub.registry_path, default_project_path=tmp_project, flush_delay_s=0)
    assert run.run_id in reloaded.runs
    assert reloaded.runs[run.run_id].status == "ABANDONED"
    assert reloaded.runs[run.run_id].cancel_reason == "server-restart"


def test_pause_and_resume_run(client, hub):
    """Duraklatılan koşuda get_next_step PAUSED döner; devam edilince STEP; şablon/REST ikizi aynı motoru kullanır."""
    hub.step_by_step_mode = False
    run = client.post("/api/runs", json={"steps": [1, 2], "engine": "mcp_client", "client": {"name": "curl", "version": "1"}}).json()["run"]
    rid = run["run_id"]
    assert client.post(f"/api/runs/{rid}/pause", json={"reason": "test"}).json()["status"] == "PAUSED"
    nxt = client.post(f"/api/runs/{rid}/next-step", json={"client": {"name": "curl"}}).json()
    assert nxt["status"] == "PAUSED"
    waited = client.post(f"/api/runs/{rid}/approval", json={"timeout_s": 1}).json()
    assert waited["status"] == "PAUSED"
    assert client.post(f"/api/runs/{rid}/resume").json()["status"] == "RESUMED"
    nxt = client.post(f"/api/runs/{rid}/next-step", json={"client": {"name": "curl"}}).json()
    assert nxt["status"] == "STEP" and nxt["order"] == 1
    assert client.get(f"/api/runs/{rid}").json()["run"]["paused"] is False
    assert client.post(f"/api/runs/{rid}/cancel", json={"reason": "cleanup"}).status_code == 200
    assert client.post(f"/api/runs/{rid}/pause", json={}).status_code == 409
