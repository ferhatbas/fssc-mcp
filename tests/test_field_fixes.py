"""Saha notlarından (saha notları) hızlı düzeltmeler:
C1 test girdilerindeki sahte parolalar commit'i durdurup düzeltme turu yemesin; C3 Node projesi için boş Python sanal ortamı kurulmasın;
D1 PM/ARCHITECT faz teslimi gerekli belgesiz kabul edilmesin."""

import asyncio
import json
import os

import pytest

from server import guard as G
from server import verify as V


# ---------------------------------------------------------------------------
# C1 — test dosyalarındaki atanmış parola/secret yanlış pozitifi
# ---------------------------------------------------------------------------
def _write(root, rel, text):
    p = os.path.join(root, *rel.split("/"))
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)


@pytest.mark.parametrize("rel", ["apps/backend/src/auth/auth.spec.ts", "src/auth.test.ts", "tests/test_auth.py", "test/e2e/login.ts",
                                 "src/__tests__/a.ts", "app/fixtures/users.json", "conftest.py", "src/auth_test.py"])
def test_fake_passwords_in_test_files_do_not_stop_the_commit(tmp_path, rel):
    _write(str(tmp_path), rel, "const user = { password: 'Sifre-12345', email: 'a@b.c' };\n")
    assert G.scan_files(str(tmp_path), [rel]) == []


@pytest.mark.parametrize("rel", ["apps/backend/src/auth/auth.service.ts", "src/config.ts", "Dockerfile", "docs/ARCHITECTURE.md", "src/contest.ts", "src/latest.py"])
def test_assigned_secrets_in_product_code_still_stop_the_commit(tmp_path, rel):
    _write(str(tmp_path), rel, "const user = { password: 'Sifre-12345', email: 'a@b.c' };\n")
    found = G.scan_files(str(tmp_path), [rel])
    assert found and found[0]["kind"] == "ASSIGNED_SECRET"


def test_high_confidence_secrets_are_flagged_even_in_test_files(tmp_path):
    _write(str(tmp_path), "tests/test_keys.py", "KEY = 'AKIA" + "ABCDEFGHIJKLMNOP'\n-----BEGIN PRIVATE KEY-----\n")
    kinds = {f["kind"] for f in G.scan_files(str(tmp_path), ["tests/test_keys.py"])}
    assert {"AWS_ACCESS_KEY", "PRIVATE_KEY"} <= kinds


# ---------------------------------------------------------------------------
# C3 — Node projesi için sanal ortam kurulmaz; Python projesi için kurulur
# ---------------------------------------------------------------------------
def test_venv_is_not_created_for_a_project_without_python(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(V, "ensure_venv", lambda project_dir, timeout_s=180.0: calls.append(project_dir) or {"ok": True, "python": "x", "created": True, "error": None})
    _write(str(tmp_path), "apps/backend/package.json", json.dumps({"scripts": {"test": "jest"}}))
    _write(str(tmp_path), "apps/backend/src/main.ts", "export {};\n")
    res = asyncio.run(V.run_verification(str(tmp_path), {"test": "python -c \"print('ok')\""}, ["apps/backend/src/main.ts"], isolation="venv"))
    assert calls == [] and res["isolation"] == "none"                                      # boş venv ve "isolation: venv" yok


def test_venv_is_created_when_the_project_has_python(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(V, "ensure_venv", lambda project_dir, timeout_s=180.0: calls.append(project_dir) or {"ok": False, "python": None, "created": False, "error": "yok"})
    _write(str(tmp_path), "apps/api/requirements.txt", "pytest\n")
    res = asyncio.run(V.run_verification(str(tmp_path), {"test": "python -c \"print('ok')\""}, [], isolation="venv"))
    assert calls == [str(tmp_path)] and res["isolation"] == "venv" and res["failed_step"] == "venv"
    py_only = tmp_path / "other"
    py_only.mkdir()
    _write(str(py_only), "src/main.py", "print(1)\n")
    calls.clear()
    asyncio.run(V.run_verification(str(py_only), {}, ["src/main.py"], isolation="venv"))
    assert calls == [str(py_only)]                                                          # yalnızca .py teslimi de Python sayılır


# ---------------------------------------------------------------------------
# D1 — PM / ARCHITECT teslimi gerekli belge olmadan kabul edilmez
# ---------------------------------------------------------------------------
CLIENT = {"name": "claude-code", "version": "2.1"}


def _legacy_run(client, hub, steps):
    client.post("/api/settings/engine", json={"execution_engine": "mcp_client", "approval_mode": "auto", "pacing": "instant", "auto_verify": False, "auto_commit": False})
    hub.step_by_step_mode = False
    return client.post("/api/runs", json={"steps": steps, "engine": "mcp_client"}).json()["run"]["run_id"]


def _template_env(hub, rid):
    from server import pipeline as P
    run = hub.runs[rid]
    record = run.current_step
    return P.handler_for(hub, record).template_output(P.make_context(hub, run, record))


def test_pm_delivery_without_the_prd_is_rejected_and_the_step_stays_open(client, hub):
    rid = _legacy_run(client, hub, [1])
    nxt = client.post(f"/api/runs/{rid}/next-step", json={"client": CLIENT}).json()
    assert nxt["status"] == "STEP" and nxt["agent_id"] == "PM"
    empty = {"trace_id": rid, "from_agent": "PM", "to_agent": "ARCHITECT", "intent": "SUBMIT_PRD", "status": "SUCCESS", "payload": {"summary": "x"}}
    res = client.post(f"/api/runs/{rid}/steps/{nxt['order']}/result", json={"result_json": json.dumps(empty), "client": CLIENT}).json()
    assert res["status"] == "REJECTED" and "PRD.md" in " ".join(res["validation_errors"])
    assert hub.runs[rid].current_step.status != "DONE"                                       # sahte teslim adımı bitirmez
    ok = client.post(f"/api/runs/{rid}/steps/{nxt['order']}/result", json={"result_json": json.dumps(_template_env(hub, rid)), "client": CLIENT}).json()
    assert ok["status"] in ("NEXT", "RUN_COMPLETE"), ok


def test_architect_delivery_needs_the_architecture_and_the_contract(client, hub):
    rid = _legacy_run(client, hub, [1, 2])
    nxt = client.post(f"/api/runs/{rid}/next-step", json={"client": CLIENT}).json()
    client.post(f"/api/runs/{rid}/steps/{nxt['order']}/result", json={"result_json": json.dumps(_template_env(hub, rid)), "client": CLIENT})
    nxt = client.post(f"/api/runs/{rid}/next-step", json={"client": CLIENT}).json()
    assert nxt["status"] == "STEP" and nxt["agent_id"] == "ARCHITECT"
    only_doc = _template_env(hub, rid)
    only_doc["payload"]["files"] = [{"path": "docs/notes.md", "content": "x"}]
    res = client.post(f"/api/runs/{rid}/steps/{nxt['order']}/result", json={"result_json": json.dumps(only_doc), "client": CLIENT}).json()
    assert res["status"] == "REJECTED" and "openapi_spec.json" in " ".join(res["validation_errors"])
