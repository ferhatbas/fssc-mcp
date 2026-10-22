"""
Claude ↔ FS-SC tam etkileşim günlüğü (G2 / K2).

`mcp_activity.py` yalnızca "hangi araç, hangi sonuç" özetini bellekte tutar. Bu modül her etkileşimi İKİ YÖNLÜ ve TAM kaydeder:
- `to_claude`  : sunucunun Claude'a verdiği şey (adım promptu, bağlam, çıktı sözleşmesi, display_md, onay/bekleme yanıtları)
- `to_server`  : Claude'un sunucuya gönderdiği şey (ham `result_json`, düşünce metni, çağrı argümanları)
- `manager`    : yöneticinin panodan yaptıkları (onay, revize, not, soru cevabı, karar)
- `client`     : istemci tarafı kancaları/transkriptinden gelen olaylar (Claude Code hooks, oturum aynası)
- `server`     : sunucunun kendi eylemleri (koşu başlatma, doğrulama, commit) — isteğe bağlı

Kayıt kalıcıdır: aktif projenin `.fs-workspace/claude_log.jsonl` dosyasına satır satır eklenir (sunucu yeniden başlasa da kaybolmaz);
bellekte son `MAX_MEM` kayıt tutulur. Panoya her kayıt `CLAUDE_LOG` olayıyla "hafif" (kırpılmış) biçimde yayınlanır; tam gövde REST ile okunur.
Sır değerleri (`guard.redact`) maskelenir; alan boyutu `MAX_FIELD` ile sınırlıdır.
"""
from __future__ import annotations

import json
import os
from collections import deque
from datetime import datetime, timezone
from .i18n import translate as tx, N_
from typing import Any, Deque, Dict, Iterable, List, Optional

LOG_FILE = os.path.join(".fs-workspace", "claude_log.jsonl")
MAX_MEM = 500
MAX_FIELD = 120_000      # alan başına en çok karakter (prompt + bağlam bundan küçüktür)
LITE_FIELD = 1_500       # WS yayınındaki kırpılmış gövde
DIRECTIONS = ("to_claude", "to_server", "manager", "client", "server")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def project_path(hub) -> Optional[str]:
    info = (getattr(hub, "projects", {}) or {}).get(getattr(hub, "active_project_id", None)) or {}
    return info.get("path") or getattr(hub, "default_project_path", None)


def log_path(project_dir: str) -> str:
    return os.path.join(os.path.abspath(project_dir), LOG_FILE)


def _mem(hub) -> Deque[Dict[str, Any]]:
    mem = getattr(hub, "_claude_log", None)
    if mem is None:
        mem = deque(maxlen=MAX_MEM)
        hub._claude_log = mem
    return mem


def _seq(hub) -> int:
    n = int(getattr(hub, "_claude_log_seq", 0) or 0) + 1
    hub._claude_log_seq = n
    return n


def _redact_text(text: str) -> str:
    try:
        from . import guard as G
        return G.redact(text)
    except Exception:
        return text


def _serialize(value: Any, limit: int = MAX_FIELD) -> Any:
    """JSON'a çevrilebilir, maskelenmiş ve boyutu sınırlı kopya. Dizeler ve iç içe yapılar tek seferde dize olarak kırpılır."""
    if value is None:
        return None
    if isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        text = _redact_text(value)
        return text if len(text) <= limit else text[:limit] + tx("\n… (kırpıldı; toplam {n} karakter)", n=len(text))
    try:
        dumped = json.dumps(value, ensure_ascii=False, default=str)
    except Exception:
        dumped = str(value)
    if len(dumped) <= limit:
        try:
            return json.loads(_redact_text(dumped))
        except Exception:
            return _redact_text(dumped)
    return _redact_text(dumped[:limit]) + tx("\n… (kırpıldı; toplam {n} karakter)", n=len(dumped))


def _lite(entry: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(entry)
    for key in ("args", "result", "text"):
        v = out.get(key)
        if v is None:
            continue
        s = v if isinstance(v, str) else json.dumps(v, ensure_ascii=False, default=str)
        if len(s) > LITE_FIELD:
            out[key] = s[:LITE_FIELD] + "…"
            out[f"{key}_truncated"] = True
    return out


def _append_file(project_dir: Optional[str], entry: Dict[str, Any]) -> None:
    if not project_dir:
        return
    try:
        path = log_path(project_dir)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
    except Exception:
        pass


async def record(hub, *, direction: str, tool: str, run_id: Optional[str] = None, order: Optional[int] = None, agent_id: Optional[str] = None,
                 kind: Optional[str] = None, client: Optional[Dict[str, str]] = None, args: Any = None, result: Any = None,
                 status: Optional[str] = None, duration_ms: Optional[int] = None, text: Optional[str] = None, error: Optional[str] = None,
                 session_id: Optional[str] = None, collapse: bool = False) -> Dict[str, Any]:
    """Bir etkileşimi kaydeder. `collapse=True`: aynı araç+koşu+sonuçla art arda gelen yoklama (STILL_WAITING) tek kayıtta sayılır."""
    direction = direction if direction in DIRECTIONS else "server"
    mem = _mem(hub)
    if collapse and mem:
        last = mem[-1]
        if last.get("tool") == tool and last.get("run_id") == run_id and last.get("status") == status and last.get("direction") == direction:
            last["count"] = int(last.get("count", 1)) + 1
            last["ts"] = _now()
            try:
                await hub.broadcast({"type": "CLAUDE_LOG", "entry": _lite(last), "updated": True})
            except Exception:
                pass
            return last
    entry: Dict[str, Any] = {
        "id": f"cl-{_seq(hub):06d}", "ts": _now(), "direction": direction, "tool": tool, "run_id": run_id, "order": order,
        "agent_id": (agent_id or None), "kind": kind, "client": (client or {}).get("name") if isinstance(client, dict) else (client or None),
        "status": status, "duration_ms": duration_ms, "count": 1, "session_id": session_id,
        "args": _serialize(args), "result": _serialize(result), "text": _serialize(text), "error": _serialize(error, 2000),
        "project_id": getattr(hub, "active_project_id", None),
    }
    mem.append(entry)
    _append_file(project_path(hub), entry)
    try:
        await hub.broadcast({"type": "CLAUDE_LOG", "entry": _lite(entry)})
    except Exception:
        pass
    return entry


def _iter_file(project_dir: Optional[str]) -> Iterable[Dict[str, Any]]:
    if not project_dir:
        return
    path = log_path(project_dir)
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


def _matches(e: Dict[str, Any], run_id: Optional[str], tool: Optional[str], direction: Optional[str], since: Optional[str], q: Optional[str]) -> bool:
    if run_id and e.get("run_id") != run_id:
        return False
    if tool and e.get("tool") != tool:
        return False
    if direction and e.get("direction") != direction:
        return False
    if since and str(e.get("ts") or "") < since:
        return False
    if q:
        blob = json.dumps({k: e.get(k) for k in ("tool", "args", "result", "text", "agent_id", "status", "error")}, ensure_ascii=False, default=str).lower()
        if q.lower() not in blob:
            return False
    return True


def query(hub, run_id: Optional[str] = None, tool: Optional[str] = None, direction: Optional[str] = None, since: Optional[str] = None,
          q: Optional[str] = None, limit: int = 200, offset: int = 0, lite: bool = True) -> Dict[str, Any]:
    """Yeniden eskiye: dosya + bellek birleşimi (kimlikle tekilleştirilmiş). `lite`: gövdeler kırpılmış döner (liste görünümü)."""
    seen = set()
    rows: List[Dict[str, Any]] = []
    for src in (list(_mem(hub)), list(_iter_file(project_path(hub)))):
        for e in src:
            if e.get("id") in seen:
                continue
            seen.add(e.get("id"))
            if _matches(e, run_id, tool, direction, since, q):
                rows.append(e)
    rows.sort(key=lambda e: (str(e.get("ts") or ""), str(e.get("id") or "")), reverse=True)
    total = len(rows)
    page = rows[max(0, int(offset)): max(0, int(offset)) + max(1, min(int(limit), 1000))]
    return {"total": total, "entries": [_lite(e) if lite else e for e in page], "tools": sorted({str(e.get("tool")) for e in rows if e.get("tool")}),
            "runs": sorted({str(e.get("run_id")) for e in rows if e.get("run_id")})}


def get_entry(hub, entry_id: str) -> Optional[Dict[str, Any]]:
    for e in reversed(list(_mem(hub))):
        if e.get("id") == entry_id:
            return e
    for e in _iter_file(project_path(hub)):
        if e.get("id") == entry_id:
            return e
    return None


def export_markdown(entries: List[Dict[str, Any]]) -> str:
    """Yeniden eskiye gelen listeyi kronolojik Markdown'a çevirir (yöneticinin okuyacağı tam döküm)."""
    arrow = {"to_claude": "FS-SC → Claude", "to_server": "Claude → FS-SC", "manager": tx("Yönetici → FS-SC"), "client": tx("Claude oturumu"), "server": "FS-SC"}
    lines = [tx("# Claude ↔ FS-SC etkileşim günlüğü"), ""]
    for e in sorted(entries, key=lambda x: (str(x.get("ts") or ""), str(x.get("id") or ""))):
        head = f"## {e.get('ts', '')[:19]} · {arrow.get(e.get('direction'), e.get('direction'))} · `{e.get('tool')}`"
        meta = " · ".join(x for x in (tx("koşu {run_id}", run_id=e.get('run_id')) if e.get("run_id") else "", tx("adım #{order}", order=e.get('order')) if e.get("order") is not None else "",
                                      str(e.get("agent_id") or ""), str(e.get("status") or ""), f"×{e.get('count')}" if int(e.get("count", 1) or 1) > 1 else "") if x)
        lines += [head, meta, ""]
        for key, label in (("text", tx("Metin")), ("args", tx("Argümanlar")), ("result", tx("Sonuç")), ("error", tx("Hata"))):
            v = e.get(key)
            if v in (None, "", {}, []):
                continue
            body = v if isinstance(v, str) else json.dumps(v, ensure_ascii=False, indent=1, default=str)
            lines += [f"**{label}:**", "```", body, "```", ""]
    return "\n".join(lines)
