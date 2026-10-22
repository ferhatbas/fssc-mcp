"""Gerçek token kullanımı: Claude transkriptlerindeki usage değerleri adım pencerelerine ve ajan rollerine bağlanır."""
import json
import os
import re
from datetime import datetime, timedelta, timezone

from server import token_usage as TU
from server.runs import PipelineRun, StepRecord


def _iso(dt):
    return dt.isoformat().replace("+00:00", "Z")


def _write_transcript(root, project_dir, rows):
    name = re.sub(r"[^A-Za-z0-9]", "-", os.path.abspath(project_dir))
    d = os.path.join(root, name)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "s1.jsonl"), "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")


def _msg(mid, ts, inp, out, cw=0, cr=0, typ="assistant"):
    return {"type": typ, "timestamp": _iso(ts), "sessionId": "s1",
            "message": {"id": mid, "usage": {"input_tokens": inp, "output_tokens": out, "cache_creation_input_tokens": cw, "cache_read_input_tokens": cr}}}


async def test_kullanim_adimlara_ve_rollere_baglanir(hub, tmp_project, tmp_path, monkeypatch):
    root = tmp_path / "claude_projects"
    monkeypatch.setenv("FSSC_CLAUDE_PROJECTS_DIR", str(root))
    t0 = datetime(2026, 10, 14, 10, 0, 0, tzinfo=timezone.utc)
    run = PipelineRun(project_id=hub.active_project_id)
    run.steps = [StepRecord(order=6, issue_id="JIRA-6", role="QA", kind="phase", started_at=t0.isoformat(), finished_at=(t0 + timedelta(minutes=5)).isoformat()),
                 StepRecord(order=9, issue_id="JIRA-9", role="PO", kind="phase", started_at=(t0 + timedelta(minutes=6)).isoformat(),
                            finished_at=(t0 + timedelta(minutes=10)).isoformat())]
    hub.runs[run.run_id] = run
    _write_transcript(str(root), tmp_project, [
        _msg("m1", t0 + timedelta(minutes=1), 10, 500, 1000, 20000),
        _msg("m1", t0 + timedelta(minutes=1, seconds=1), 10, 500, 1000, 20000),            # aynı mesajın tekrarı: bir kez sayılır
        _msg("m2", t0 + timedelta(minutes=2), 5, 300, 0, 21000),
        _msg("m3", t0 + timedelta(minutes=7), 7, 900, 500, 22000),                         # PO penceresi
        _msg("m4", t0 + timedelta(minutes=30), 1, 50, 0, 100),                             # hiçbir adımda değil
        _msg("u1", t0 + timedelta(minutes=2), 99, 99, typ="user"),                         # asistan olmayan satır sayılmaz
    ])
    s = TU.summarize(hub)
    assert s["available"] and s["sessions"] == 1
    assert s["total"] == {"input": 23, "output": 1750, "cache_write": 1500, "cache_read": 63100, "messages": 4}
    assert s["by_agent"]["QA"]["output"] == 800 and s["by_agent"]["QA"]["messages"] == 2 and s["by_agent"]["PO"]["output"] == 900
    assert s["unattributed"]["output"] == 50 and s["by_run"][run.run_id]["output"] == 1700
    assert "total_tokens" in s["estimated"]


async def test_transkript_yoksa_kullanilamaz_der(hub, tmp_project, tmp_path, monkeypatch):
    monkeypatch.setenv("FSSC_CLAUDE_PROJECTS_DIR", str(tmp_path / "bos"))
    s = TU.summarize(hub)
    assert s["available"] is False and s["total"]["output"] == 0


async def test_uc_nokta(client, hub, tmp_project, tmp_path, monkeypatch):
    monkeypatch.setenv("FSSC_CLAUDE_PROJECTS_DIR", str(tmp_path / "bos"))
    r = client.get("/api/usage/tokens").json()
    assert r["available"] is False and r["source"] == "claude-transcript"
