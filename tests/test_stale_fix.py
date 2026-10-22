"""Doğrulama geçince aynı görevin bekleyen (bayat) düzeltme adımları kaldırılır; örn. altyapı hatasından kalanlar."""

import json
import sys

from server.runs import StepRecord

PY = f'"{sys.executable}"' if " " in sys.executable else sys.executable
FAIL_CMD = f'{PY} -c "import sys; print(\'boom: AssertionError in src/calc.py\'); sys.exit(1)"'
PASS_CMD = f'{PY} -c "print(\'ok\')"'
# Geçerli Python (sözdizimi denetimi geçsin); asıl başarısızlık FAIL_CMD'den gelir
BAD_BODY = "def add(a, b):\n    return a - b\n"
GOOD_BODY = "def add(a, b):\n    return a + b\n"


def _env(body):
    return json.dumps({
        "from_agent": "BACKEND_DEV", "to_agent": "FRONTEND_DEV", "intent": "BACKEND_API_EXPOSED", "status": "SUCCESS",
        "payload": {"summary": "teslim", "friendly_dialogue": "hazır", "thinking": "t", "what_doing": "w", "what_next": "n",
                    "files": [{"path": "src/calc.py", "content": body}]},
        "metadata": {"tokens_used": 50},
    })


async def test_passing_fix_drops_remaining_stale_fix_steps(client, hub):
    hub.step_by_step_mode = False
    await hub.update_settings({"approval_mode": "auto", "auto_verify": True, "auto_commit": False, "max_fix_rounds": 3,
                               "verification": {"test": FAIL_CMD}})
    rid = client.post("/api/runs", json={"steps": [3], "engine": "mcp_client", "client": {"name": "t"}}).json()["run"]["run_id"]
    client.post(f"/api/runs/{rid}/next-step", json={"client": {"name": "t"}})
    first = client.post(f"/api/runs/{rid}/steps/3/result", json={"result_json": _env(BAD_BODY)}).json()
    assert first["fix_requested"] is True

    # önceki başarısız denemelerden kalan ikinci bir bekleyen düzeltme adımı
    run = hub.runs[rid]
    fix1 = next(s for s in run.steps if s.kind == "fix")
    run.steps.append(StepRecord(order=fix1.order, issue_id=fix1.issue_id, role=fix1.role, kind="fix", fix_round=2, title=fix1.title))
    assert [s.fix_round for s in run.steps if s.kind == "fix"] == [1, 2]

    await hub.update_settings({"verification": {"test": PASS_CMD}})
    step = client.post(f"/api/runs/{rid}/next-step", json={"client": {"name": "t"}}).json()
    assert step["kind"] == "fix" and step["fix_round"] == 1
    done = client.post(f"/api/runs/{rid}/steps/3/result", json={"result_json": _env(GOOD_BODY)}).json()

    assert done["verification"]["status"] == "PASSED", done["verification"]
    assert done["status"] == "RUN_COMPLETE"                     # bayat 2. düzeltme adımı istenmedi
    assert not [s for s in hub.runs[rid].steps if s.kind == "fix" and s.status == "PENDING"]
    assert any(e.get("action") == "STALE_FIX_DROPPED" for e in hub.jira_issues["JIRA-3"]["audit_trail"])


async def test_failing_verification_keeps_fix_steps(client, hub):
    """Doğrulama başarısızsa düzeltme adımları korunur (yalnızca geçen doğrulama bayatları kaldırır)."""
    hub.step_by_step_mode = False
    await hub.update_settings({"approval_mode": "auto", "auto_verify": True, "auto_commit": False, "max_fix_rounds": 3,
                               "verification": {"test": FAIL_CMD}})
    rid = client.post("/api/runs", json={"steps": [3], "engine": "mcp_client", "client": {"name": "t"}}).json()["run"]["run_id"]
    client.post(f"/api/runs/{rid}/next-step", json={"client": {"name": "t"}})
    res = client.post(f"/api/runs/{rid}/steps/3/result", json={"result_json": _env(BAD_BODY)}).json()
    assert res["fix_requested"] is True
    assert [s.fix_round for s in hub.runs[rid].steps if s.kind == "fix"] == [1]
