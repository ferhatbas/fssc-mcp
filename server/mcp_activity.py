"""
Claude (MCP istemcisi) ile FS-SC arasındaki iletişimin görünürlüğü.

FS-SC bir şey itmez: istemci (Claude Desktop / Claude Code) sunucudan araç çağrılarıyla (`get_next_step`,
`submit_step_result`, `wait_for_approval`, `report_thinking`) iş çeker ve teslim eder. Bu modül
- son çağrıları halka tamponda tutar (aynı `wait_for_approval` yoklaması tek satırda sayılır),
- koşunun GERÇEK durumundan "şimdi sıra kimde" bilgisini türetir (ajan kartlarının son olaya bakan durumundan bağımsız).
"""

from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
from typing import Any, Deque, Dict, List, Optional

from .i18n import translate as tx, N_

LOG_MAX = 200
SNAPSHOT_CALLS = 60
# Son çağrıdan bu yana geçen süreye göre istemci durumu
CONNECTED_S = 120        # bu süre içinde çağrı: bağlı
WAITING_S = 900          # bu süre içinde: bekliyor / düşünüyor olabilir; üstü: uzakta


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _log(hub) -> Deque[Dict[str, Any]]:
    log = getattr(hub, "_mcp_calls", None)
    if log is None:
        log = deque(maxlen=LOG_MAX)
        hub._mcp_calls = log
    return log


async def log_call(hub, tool: str, run=None, client: Optional[Dict[str, str]] = None, **info: Any) -> Dict[str, Any]:
    """Bir MCP araç çağrısını kaydeder ve panolara yayınlar. Art arda aynı yoklama (STILL_WAITING) tek satırda toplanır."""
    log = _log(hub)
    entry: Dict[str, Any] = {
        "ts": _now(), "tool": tool, "run_id": getattr(run, "run_id", None),
        "client": (client or {}).get("name") or "", "count": 1, **{k: v for k, v in info.items() if v is not None},
    }
    last = log[-1] if log else None
    if last and last["tool"] == tool and last.get("run_id") == entry["run_id"] and last.get("result") == entry.get("result") and tool == "wait_for_approval":
        last["count"] = int(last.get("count", 1)) + 1
        last["ts"] = entry["ts"]
        entry = last
    else:
        log.append(entry)
    await hub.broadcast({"type": "MCP_CALL", "call": entry})
    return entry


def _age_s(iso: Optional[str], now: Optional[datetime] = None) -> Optional[float]:
    if not iso:
        return None
    try:
        t = datetime.fromisoformat(iso)
    except ValueError:
        return None
    return max(0.0, ((now or datetime.now(timezone.utc)) - t).total_seconds())


def compute_turn(hub, now: Optional[datetime] = None) -> Dict[str, Any]:
    """Şimdi sıra kimde? `who`: claude (üretiyor) | claude_wait (Claude'dan çağrı bekleniyor) | manager (yönetici) | server | idle."""
    run = hub.runs.get(getattr(hub, "active_run_id", None) or "")
    if run is None:
        # Etkin koşu yoksa en yeni sürdürülebilir koşu: açık olan ya da sunucu yeniden başlayınca ABANDONED olan (Claude'un çağrısıyla sürer)
        resumable = [r for r in hub.runs.values()
                     if r.project_id == hub.active_project_id and (not r.is_terminal or r.status == "ABANDONED")]
        run = max(resumable, key=lambda r: r.created_at, default=None)
    if run is None:
        return {"who": "idle", "label": tx("Etkin koşu yok"), "detail": tx("Claude'da 'pipeline'ı çalıştır' dersen ya da dashboard'dan koşu başlatırsan iş başlar."), "run_id": None}
    step = run.current_step
    base = {"run_id": run.run_id, "run_status": run.status, "engine": run.engine, "order": step.order if step else None,
            "agent_id": step.role if step else None, "title": (step.title if step else "") or "", "kind": step.kind if step else None,
            "since": (step.started_at if step else None) or run.last_seen}
    if run.status == "ABANDONED":
        return {**base, "who": "claude_wait", "label": tx("Claude bekleniyor (koşu terk edilmiş görünüyor)"),
                "detail": tx("Sunucu yeniden başladı ya da Claude uzun süredir çağrı yapmadı. Claude bir sonraki çağrısında koşu kaldığı yerden sürer.")}
    if run.is_terminal:
        return {**base, "who": "idle", "label": tx("Koşu {status}", status=run.status), "detail": ""}
    if run.engine != "mcp_client":
        return {**base, "who": "server", "label": tx("Şablon motoru çalışıyor (Claude devrede değil)"), "detail": tx("Bu koşu sunucudaki şablon motoruyla yürüyor.")}
    sprint = None
    try:
        from . import sprint as SP
        sprints = SP.ensure_state(hub).get("sprints", [])
        # Daha yeni bir sprint açıldıysa eski sprintin engeli sırayı yöneticiye vermez
        sprint = next((s for s in sprints if s.get("status") == "BLOCKED"
                       and not any((o.get("sprint_number") or 0) > (s.get("sprint_number") or 0) for o in sprints)), None)
    except Exception:
        sprint = None
    if run.status == "WAITING_APPROVAL":
        return {**base, "who": "manager", "label": tx("Sıra sende: adım #{n} onayı bekliyor", n=base['order']),
                "detail": tx("Dashboard'da adımı incele; onayla ya da revize iste.")}
    if sprint is not None:
        reason = (sprint.get("blocked") or {}).get("detail", "")
        try:
            from . import meetings as M
            has_question = bool(M.open_blocking(hub))
        except Exception:
            has_question = False
        if has_question:
            return {**base, "who": "manager", "label": tx("Sıra sende: engelleyici soru bekliyor"),
                    "detail": tx("Sprint {n} durdu: {reason}. Sorular panelinden cevapla.", n=sprint.get('sprint_number'), reason=reason)}
        return {**base, "who": "manager", "label": tx("Sıra sende: Sprint {n} engelde", n=sprint.get('sprint_number')),
                "detail": tx("{reason}. Cevaplanacak açık soru yok; engeli kaldırmak yönetici kararıdır.", reason=reason)}
    if run.paused:
        return {**base, "who": "manager", "label": tx("Koşu duraklatıldı"), "detail": run.pause_reason or tx("Devam ettirene kadar Claude'a yeni adım verilmez.")}
    if run.status == "QUEUED":
        return {**base, "who": "claude_wait", "label": tx("Claude bekleniyor"), "detail": tx("Koşu kuyrukta; Claude get_next_step çağırınca başlar.")}
    if step is not None and getattr(step, "server_side", False):
        return {**base, "who": "server", "label": tx("Sunucu adımı #{n} yürütülüyor", n=step.order), "detail": ""}
    if step is not None:
        return {**base, "who": "claude", "label": tx("Claude üretiyor: {role} · adım #{n}", role=step.role, n=step.order), "detail": base["title"]}
    return {**base, "who": "idle", "label": tx("Bekleniyor"), "detail": ""}


def snapshot(hub) -> Dict[str, Any]:
    """GET /api/mcp/activity yanıtı: sıra kimde, istemci bağlantısı ve son çağrılar (yeniden eskiye)."""
    now = datetime.now(timezone.utc)
    clients = sorted(hub.connected_clients.values(), key=lambda c: c.get("last_seen", ""), reverse=True)
    client = clients[0] if clients else None
    age = _age_s(client.get("last_seen"), now) if client else None
    if client is None:
        state = "none"
    elif age is not None and age <= CONNECTED_S:
        state = "connected"
    elif age is not None and age <= WAITING_S:
        state = "waiting"
    else:
        state = "away"
    calls: List[Dict[str, Any]] = list(_log(hub))[-SNAPSHOT_CALLS:][::-1]
    return {
        "turn": compute_turn(hub, now),
        "client": ({**client, "age_s": age} if client else None),
        "client_state": state,
        "calls": calls,
        "server_time": now.isoformat(),
    }
