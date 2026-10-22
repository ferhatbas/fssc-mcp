"""
Claude oturum aynası (G2 / K3): Claude Code / Claude Desktop Code sekmesi oturum transkriptlerinin okunması ve izlenmesi.

Claude Code her oturumu `~/.claude/projects/<kodlanmış çalışma klasörü>/<session-id>.jsonl` olarak diskte tutar
(`D:\\x\\y` → `D--x-y`). Satırlar: `user` (istem ve araç sonuçları), `assistant` (`message.content` içinde `text`,
`thinking`, `tool_use` blokları), `attachment`, `queue-operation`, `custom-title` … Bu modül yalnızca okur; hiçbir şey yazmaz.

Sınırlar (dürüst): düşünce bloklarının METNİ istemci sürümüne/modele göre boş olabilir (yalnızca imza saklanır); Claude Desktop
Chat sekmesi oturumlarının yerel transkripti yoktur. Bu durumlarda ayna "düşünce saklanmamış" der, uydurmaz.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from .i18n import translate as tx

FSSC_TOOL_PREFIX = "mcp__fssc-visual-observer__"
MAX_INPUT_CHARS = 6000
POLL_INTERVAL_S = 2.0


def transcripts_root(override: Optional[str] = None) -> str:
    """`~/.claude/projects` (ayar `claude.transcripts_dir` ya da `CLAUDE_TRANSCRIPTS_DIR` ile değiştirilebilir)."""
    cand = override or os.environ.get("CLAUDE_TRANSCRIPTS_DIR") or os.path.join(os.path.expanduser("~"), ".claude", "projects")
    return os.path.abspath(cand)


def encode_project_dir(path: str) -> str:
    """Claude Code'un klasör adı kodlaması: harf/rakam dışındaki her karakter `-` olur (`D:\\Personal\\mcp_server` → `D--Personal-mcp-server`)."""
    p = os.path.abspath(path).replace("/", "\\") if os.name == "nt" else os.path.abspath(path)
    return re.sub(r"[^A-Za-z0-9]", "-", p)


def project_transcript_dir(project_dir: str, root: Optional[str] = None) -> str:
    return os.path.join(transcripts_root(root), encode_project_dir(project_dir))


def _title_from_head(path: str, max_lines: int = 60) -> Dict[str, Any]:
    """Dosyanın başından başlık/ilk istem/giriş noktası (büyük dosyanın tamamı okunmaz)."""
    info: Dict[str, Any] = {"title": None, "first_prompt": None, "entrypoint": None, "version": None, "git_branch": None, "cwd": None}
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            for i, line in enumerate(f):
                if i >= max_lines:
                    break
                try:
                    e = json.loads(line)
                except Exception:
                    continue
                t = e.get("type")
                if t == "custom-title" and e.get("customTitle"):
                    info["title"] = str(e["customTitle"])[:120]
                elif t == "user" and info["first_prompt"] is None:
                    c = (e.get("message") or {}).get("content")
                    if isinstance(c, str):
                        info["first_prompt"] = c[:200]
                if e.get("entrypoint") and not info["entrypoint"]:
                    info["entrypoint"] = e.get("entrypoint")
                if e.get("version") and not info["version"]:
                    info["version"] = e.get("version")
                if e.get("gitBranch") and not info["git_branch"]:
                    info["git_branch"] = e.get("gitBranch")
                if e.get("cwd") and not info["cwd"]:
                    info["cwd"] = e.get("cwd")
    except OSError:
        pass
    return info


def list_sessions(project_dir: str, root: Optional[str] = None, limit: int = 30) -> List[Dict[str, Any]]:
    """Projenin (FS-SC deposunun) Claude Code oturumları, en yeniden eskiye."""
    d = project_transcript_dir(project_dir, root)
    if not os.path.isdir(d):
        return []
    rows: List[Dict[str, Any]] = []
    for name in os.listdir(d):
        if not name.endswith(".jsonl"):
            continue
        path = os.path.join(d, name)
        try:
            st = os.stat(path)
        except OSError:
            continue
        rows.append({"session_id": name[:-6], "file": path, "size": st.st_size,
                     "modified_at": datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).isoformat(), **_title_from_head(path)})
    rows.sort(key=lambda r: r["modified_at"], reverse=True)
    return rows[:limit]


def _cap(value: Any, limit: int = MAX_INPUT_CHARS) -> Any:
    try:
        s = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    except Exception:
        s = str(value)
    if len(s) <= limit:
        return value
    return s[:limit] + tx("… (kırpıldı; {n} karakter)", n=len(s))


def parse_entry(raw: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Bir transkript satırını normalleştirilmiş olaylara çevirir (bir satırda birden çok blok olabilir)."""
    t = raw.get("type")
    base = {"ts": raw.get("timestamp"), "session_id": raw.get("sessionId"), "uuid": raw.get("uuid"), "parent_uuid": raw.get("parentUuid")}
    out: List[Dict[str, Any]] = []
    if t == "user":
        content = (raw.get("message") or {}).get("content")
        if isinstance(content, str):
            if content.strip():
                out.append({**base, "kind": "user_text", "text": content[:MAX_INPUT_CHARS]})
        elif isinstance(content, list):
            for b in content:
                if not isinstance(b, dict):
                    continue
                if b.get("type") == "tool_result":
                    body = b.get("content")
                    if isinstance(body, list):
                        body = " ".join(str(x.get("text", "")) for x in body if isinstance(x, dict))
                    out.append({**base, "kind": "tool_result", "tool_use_id": b.get("tool_use_id"), "is_error": bool(b.get("is_error")),
                                "text": _cap(body)})
                elif b.get("type") == "text" and str(b.get("text") or "").strip():
                    out.append({**base, "kind": "user_text", "text": str(b["text"])[:MAX_INPUT_CHARS]})
    elif t == "assistant":
        msg = raw.get("message") or {}
        model = msg.get("model")
        usage = msg.get("usage") or {}
        for b in (msg.get("content") or []):
            if not isinstance(b, dict):
                continue
            bt = b.get("type")
            if bt == "thinking":
                text = str(b.get("thinking") or "")
                out.append({**base, "kind": "thinking", "text": text[:MAX_INPUT_CHARS] if text else "", "empty": not bool(text.strip()),
                            "duration_ms": raw.get("thinkingDurationMs"), "model": model})
            elif bt == "text" and str(b.get("text") or "").strip():
                out.append({**base, "kind": "assistant_text", "text": str(b["text"])[:MAX_INPUT_CHARS], "model": model,
                            "usage": {k: usage.get(k) for k in ("input_tokens", "output_tokens", "cache_read_input_tokens") if k in usage}})
            elif bt == "tool_use":
                name = str(b.get("name") or "")
                inp = b.get("input") if isinstance(b.get("input"), dict) else {}
                out.append({**base, "kind": "tool_use", "tool": name, "tool_use_id": b.get("id"), "fssc": name.startswith(FSSC_TOOL_PREFIX),
                            "run_id": inp.get("run_id") if isinstance(inp, dict) else None, "input": _cap(inp), "model": model})
    elif t in ("queue-operation",) and raw.get("operation") == "enqueue":
        out.append({**base, "kind": "queued_prompt", "text": str(raw.get("content") or "")[:MAX_INPUT_CHARS]})
    return out


def read_events(path: str, offset: int = 0, max_bytes: int = 8_000_000) -> Tuple[List[Dict[str, Any]], int]:
    """`offset` baytından itibaren yeni satırları okur; (olaylar, yeni offset). Yarım satır bir sonraki okumaya bırakılır."""
    events: List[Dict[str, Any]] = []
    try:
        with open(path, "rb") as f:
            f.seek(offset)
            data = f.read(max_bytes)
    except OSError:
        return events, offset
    if not data:
        return events, offset
    last_nl = data.rfind(b"\n")
    if last_nl < 0:
        return events, offset
    chunk, consumed = data[:last_nl + 1], last_nl + 1
    for line in chunk.decode("utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            raw = json.loads(line)
        except Exception:
            continue
        events.extend(parse_entry(raw))
    return events, offset + consumed


def session_events(path: str, limit: int = 400, kinds: Optional[List[str]] = None) -> Dict[str, Any]:
    """Oturumun son `limit` olayı (tamamı okunur; büyük dosyada son 8 MB)."""
    try:
        size = os.path.getsize(path)
    except OSError:
        return {"events": [], "offset": 0, "size": 0}
    start = max(0, size - 8_000_000)
    events, new_offset = read_events(path, start)
    if kinds:
        events = [e for e in events if e.get("kind") in kinds]
    thinking_total = sum(1 for e in events if e.get("kind") == "thinking")
    thinking_empty = sum(1 for e in events if e.get("kind") == "thinking" and e.get("empty"))
    return {"events": events[-max(1, min(int(limit), 2000)):], "offset": new_offset, "size": size,
            "thinking": {"total": thinking_total, "empty": thinking_empty,
                         "note": tx("Düşünce metni bu transkriptte saklanmamış (yalnızca imza).") if thinking_total and thinking_empty == thinking_total else None}}


class TranscriptWatcher:
    """Seçilen transkript dosyalarını yoklar, yeni olayları panoya yayınlar (`CLAUDE_TRANSCRIPT_EVENT`) ve isteğe bağlı günlüğe yazar."""

    def __init__(self, hub, interval_s: float = POLL_INTERVAL_S):
        self.hub = hub
        self.interval_s = interval_s
        self.files: Dict[str, int] = {}          # path → offset
        self._task: Optional[asyncio.Task] = None
        self.last_event_at: Optional[str] = None
        self.events_seen = 0

    def watch(self, path: str, from_start: bool = False) -> None:
        if path in self.files:
            return
        try:
            self.files[path] = 0 if from_start else os.path.getsize(path)
        except OSError:
            self.files[path] = 0
        self.start()

    def unwatch(self, path: str) -> None:
        self.files.pop(path, None)

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._loop(), name="claude-transcript-watcher")

    async def stop(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass

    async def poll_once(self) -> int:
        n = 0
        for path in list(self.files.keys()):
            events, new_offset = await asyncio.to_thread(read_events, path, self.files[path])
            self.files[path] = new_offset
            for e in events:
                n += 1
                self.events_seen += 1
                self.last_event_at = e.get("ts") or datetime.now(timezone.utc).isoformat()
                try:
                    await self.hub.broadcast({"type": "CLAUDE_TRANSCRIPT_EVENT", "file": path, "event": e})
                except Exception:
                    pass
                if e.get("kind") in ("thinking", "assistant_text") or (e.get("kind") == "tool_use" and e.get("fssc")):
                    try:
                        from . import claude_log as CL
                        await CL.record(self.hub, direction="client", tool=e.get("tool") or e.get("kind"), run_id=e.get("run_id"),
                                        text=e.get("text") if e.get("kind") != "tool_use" else None, args=e.get("input") if e.get("kind") == "tool_use" else None,
                                        status=e.get("kind"), session_id=e.get("session_id"))
                    except Exception:
                        pass
        return n

    async def _loop(self) -> None:
        while True:
            await asyncio.sleep(self.interval_s)
            try:
                await self.poll_once()
            except Exception:
                continue

    def status(self) -> Dict[str, Any]:
        return {"watching": list(self.files.keys()), "running": bool(self._task and not self._task.done()),
                "events_seen": self.events_seen, "last_event_at": self.last_event_at}


def watcher(hub) -> TranscriptWatcher:
    w = getattr(hub, "_transcript_watcher", None)
    if w is None:
        w = TranscriptWatcher(hub)
        hub._transcript_watcher = w
    return w
