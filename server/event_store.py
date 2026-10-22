"""
Kalıcı olay deposu (JSONL) — ajan zaman çizelgesi için.

Bellekteki olay kuyruğu 500 ile sınırlıdır ve registry de aynı kuyruğu saklar; bu yüzden eski
geçmiş diskte yoktu. Her olay projenin `.fs-workspace/events.jsonl` dosyasına bir satır olarak eklenir.
Sorgular iş parçacığında (asyncio.to_thread) çalıştırılmalıdır.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

EVENTS_FILE = "events.jsonl"
MAX_LINE_CHARS = 200_000
_ID_SEQ_RE = re.compile(r"(\d+)$")


def _seq(event: Dict[str, Any]) -> int:
    """`evt-000123` → 123 (kayıt sırası). Kimlik başka biçimdeyse 0."""
    m = _ID_SEQ_RE.search(str(event.get("id") or ""))
    return int(m.group(1)) if m else 0


def _sort_key(event: Dict[str, Any]) -> Tuple[float, int]:
    """Yeniden eskiye sıralama anahtarı: zaman damgası, eşitlikte kayıt sırası (aynı milisaniyedeki olaylar kararlı sıralansın)."""
    ts = _parse_ts(event.get("timestamp"))
    return (ts.timestamp() if ts else 0.0, _seq(event))


def events_path(project_path: str) -> str:
    return os.path.join(os.path.abspath(project_path), ".fs-workspace", EVENTS_FILE)


def append_event(project_path: str, event: Dict[str, Any]) -> None:
    """Olayı JSONL dosyasına ekler (küçük, sıralı yazım; hatalar sessizce yutulur)."""
    try:
        path = events_path(project_path)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        line = json.dumps(event, ensure_ascii=False, default=str)
        if len(line) > MAX_LINE_CHARS:
            slim = {k: v for k, v in event.items() if k != "payload"}
            slim["payload"] = {"_truncated": True}
            line = json.dumps(slim, ensure_ascii=False, default=str)
        with open(path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def _iter_events(project_path: str) -> Iterable[Dict[str, Any]]:
    path = events_path(project_path)
    if not os.path.isfile(path):
        return
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except Exception:
                continue


def _parse_ts(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def tail_events(project_path: str, limit: int = 500) -> List[Dict[str, Any]]:
    """Dosyadaki son `limit` olayı eskiden yeniye döner (bellekteki canlı kuyruğu yeniden doldurmak için)."""
    if not project_path or limit <= 0:
        return []
    return sorted(_iter_events(project_path), key=_sort_key)[-int(limit):]


def query_events(
    project_path: str,
    agent_id: Optional[str] = None,
    since: Optional[str] = None,
    until: Optional[str] = None,
    limit: int = 500,
    fallback: Optional[Iterable[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """
    Ajanın (gönderen veya alıcı olarak) yer aldığı olayları, en yeniden eskiye döner.
    Dosya yoksa `fallback` (bellekteki kuyruk) kullanılır. Aynı olay kimliği tekilleştirilir.
    """
    aid = (agent_id or "").upper()
    since_dt, until_dt = _parse_ts(since), _parse_ts(until)
    seen = set()
    out: List[Dict[str, Any]] = []

    sources: List[Iterable[Dict[str, Any]]] = []
    file_events = list(_iter_events(project_path))
    if file_events:
        sources.append(file_events)
    if fallback is not None:
        sources.append(list(fallback))

    for source in sources:
        for e in source:
            eid = e.get("id")
            if eid in seen:
                continue
            if aid and aid != "ALL":
                if str(e.get("from_agent", "")).upper() != aid and str(e.get("to_agent", "")).upper() != aid:
                    continue
            ts = _parse_ts(e.get("timestamp"))
            if since_dt and ts and ts < since_dt:
                continue
            if until_dt and ts and ts > until_dt:
                continue
            seen.add(eid)
            out.append(e)

    out.sort(key=_sort_key, reverse=True)
    return out[: max(1, int(limit or 500))]


def summarize_interactions(agent_id: str, events: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Karşı ajan başına gönderilen/alınan sayıları ve son zamanı çıkarır."""
    aid = agent_id.upper()
    summary: Dict[str, Dict[str, Any]] = {}
    for e in events:
        frm, to = str(e.get("from_agent", "")).upper(), str(e.get("to_agent", "")).upper()
        if frm == aid:
            other, key = to, "sent"
        elif to == aid:
            other, key = frm, "received"
        else:
            continue
        entry = summary.setdefault(other, {"sent": 0, "received": 0, "last_at": None, "last_action": None})
        entry[key] += 1
        ts = e.get("timestamp")
        if ts and (entry["last_at"] is None or ts > entry["last_at"]):
            entry["last_at"] = ts
            entry["last_action"] = e.get("action")
    return summary
