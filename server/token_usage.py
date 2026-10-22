"""Gerçek token kullanımı: Claude oturumlarının transkriptlerinden (`~/.claude/projects/<proje>/*.jsonl`, her asistan mesajında `usage`).

Neden: panodaki token sayıları tahmindi (sabit 60 / işleyici sabitleri / modelin kendi tahmini); MCP istemcisi gerçek kullanımı bildirmez. Transkriptte ise her asistan mesajının
gerçek `usage` değeri vardır (girdi, çıktı, önbellek yazma/okuma). Burada mesajlar zaman damgasıyla adım pencerelerine (başlangıç..bitiş) ve ajan rollerine bağlanır.

Not: bu bilgi yalnızca bilgilendiricidir; abonelik girişinde token başına ücret kesilmez. Önbellek okuma çok büyük görünür (her turda bağlamın yeniden okunması), asıl iş yükü çıktı + yeni girişidir.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

_CACHE: Dict[str, Tuple[float, int, List[Dict[str, Any]]]] = {}


def claude_projects_dir() -> str:
    return os.environ.get("FSSC_CLAUDE_PROJECTS_DIR") or os.path.join(os.path.expanduser("~"), ".claude", "projects")


def transcript_dirs(project_dir: str) -> List[str]:
    """Projenin Claude transkript klasörü: yol, harf/rakam dışındaki her karakter `-` olacak biçimde (D:\\a\\b → D--a-b)."""
    base = claude_projects_dir()
    name = re.sub(r"[^A-Za-z0-9]", "-", os.path.abspath(project_dir))
    out = []
    try:
        for d in os.listdir(base):
            if d == name:
                out.append(os.path.join(base, d))
    except OSError:
        pass
    return out


def _parse_ts(value: Any) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def _read_file(path: str) -> List[Dict[str, Any]]:
    """Bir transkriptin asistan kullanım satırları; (mtime, boyut) değişmedikçe önbellekten."""
    try:
        st = os.stat(path)
    except OSError:
        return []
    hit = _CACHE.get(path)
    if hit and hit[0] == st.st_mtime and hit[1] == st.st_size:
        return hit[2]
    rows: List[Dict[str, Any]] = []
    seen = set()
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            if '"usage"' not in line:
                continue
            try:
                d = json.loads(line)
            except ValueError:
                continue
            msg = d.get("message") or {}
            u = msg.get("usage")
            if d.get("type") != "assistant" or not isinstance(u, dict):
                continue
            mid = msg.get("id") or d.get("uuid")
            if mid in seen:                                   # aynı mesajın parçalı kayıtları bir kez sayılır
                continue
            seen.add(mid)
            ts = _parse_ts(d.get("timestamp"))
            if ts is None:
                continue
            rows.append({"ts": ts, "in": int(u.get("input_tokens") or 0), "out": int(u.get("output_tokens") or 0),
                         "cache_write": int(u.get("cache_creation_input_tokens") or 0), "cache_read": int(u.get("cache_read_input_tokens") or 0),
                         "session": d.get("sessionId") or os.path.basename(path)})
    _CACHE[path] = (st.st_mtime, st.st_size, rows)
    return rows


def read_usage(project_dir: str) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for d in transcript_dirs(project_dir):
        try:
            names = [n for n in os.listdir(d) if n.endswith(".jsonl")]
        except OSError:
            continue
        for n in names:
            rows.extend(_read_file(os.path.join(d, n)))
    rows.sort(key=lambda r: r["ts"])
    return rows


def _zero() -> Dict[str, int]:
    return {"input": 0, "output": 0, "cache_write": 0, "cache_read": 0, "messages": 0}


def _add(acc: Dict[str, int], r: Dict[str, Any]) -> None:
    acc["input"] += r["in"]
    acc["output"] += r["out"]
    acc["cache_write"] += r["cache_write"]
    acc["cache_read"] += r["cache_read"]
    acc["messages"] += 1


def step_windows(hub, project_id: str) -> List[Dict[str, Any]]:
    """Projenin koşu adımlarının zaman pencereleri: başlangıçtan bitişe (bitiş yoksa sonraki adımın başlangıcına / şimdiye)."""
    wins: List[Dict[str, Any]] = []
    for run in hub.runs.values():
        if run.project_id != project_id:
            continue
        for s in run.steps:
            a = _parse_ts(getattr(s, "started_at", None))
            if a is None:
                continue
            b = _parse_ts(getattr(s, "finished_at", None))
            wins.append({"start": a, "end": b, "role": s.role, "order": s.order, "run_id": run.run_id, "issue_id": s.issue_id, "kind": s.kind})
    wins.sort(key=lambda w: w["start"])
    now = datetime.now(timezone.utc)
    for i, w in enumerate(wins):
        if w["end"] is None:
            nxt = wins[i + 1]["start"] if i + 1 < len(wins) else now
            w["end"] = nxt
    return wins


def summarize(hub) -> Dict[str, Any]:
    """Gerçek kullanım özeti: toplam, ajan (rol) ve koşu kırılımı + panodaki tahminle karşılaştırma."""
    pid = hub.active_project_id
    project_dir = (hub.projects.get(pid) or {}).get("path") or hub.default_project_path
    rows = read_usage(project_dir)
    est = {"total_tokens": int((hub.stats or {}).get("total_tokens", 0) or 0), "total_events": int((hub.stats or {}).get("total_events", 0) or 0)}
    out: Dict[str, Any] = {"available": bool(rows), "source": "claude-transcript", "project_dir": project_dir, "estimated": est,
                           "total": _zero(), "by_agent": {}, "by_run": {}, "unattributed": _zero(), "sessions": 0}
    if not rows:
        return out
    wins = step_windows(hub, pid)
    out["sessions"] = len({r["session"] for r in rows})
    out["first"], out["last"] = rows[0]["ts"].isoformat(), rows[-1]["ts"].isoformat()
    wi = 0
    for r in rows:
        _add(out["total"], r)
        while wi < len(wins) and wins[wi]["end"] < r["ts"]:
            wi += 1
        w = wins[wi] if wi < len(wins) and wins[wi]["start"] <= r["ts"] <= wins[wi]["end"] else None
        if w is None:
            _add(out["unattributed"], r)
            continue
        _add(out["by_agent"].setdefault(w["role"], _zero()), r)
        _add(out["by_run"].setdefault(w["run_id"], _zero()), r)
    return out
