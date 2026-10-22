"""MCP istemcisine giden koşu yanıtı özet olmalı: tam kayıt yüzlerce KB (doğrulama çıktıları) ve istemcinin bağlamını doldurur."""
import json

from server.mcp_models import compact_run


def test_compact_run_drops_heavy_step_fields_and_keeps_what_the_client_needs():
    steps = [{"order": i, "role": "BACKEND_DEV", "status": "DONE" if i < 150 else "PENDING", "kind": "task", "title": f"iş {i}",
              "verification": {"results": [{"output": "x" * 3000}]}, "summary": "s" * 500, "dod": {"a": "b" * 300}} for i in range(200)]
    run = {"run_id": "run-1", "status": "ACTIVE", "project_id": "p", "cursor": 150, "progress": {"done": 150, "total": 200}, "steps": steps,
           "manager_notes": [{"text": "not", "urgent": False, "extra": "y" * 5000}], "handoffs": [{"m": "z" * 9000}]}
    out = compact_run(run)
    assert len(json.dumps(run)) > 600_000 and len(json.dumps(out)) < 4_000
    assert out["run_id"] == "run-1" and out["steps_total"] == 200 and out["steps_done"] == 150 and out["progress"]["done"] == 150
    assert [s["order"] for s in out["next_steps"]] == list(range(150, 162))
    assert "verification" not in json.dumps(out) and "handoffs" not in out
    assert compact_run(None) == {}
