"""
Başsız Claude Code köprüsü (G2 / K1): panodan "▶ Claude'u başlat".

Sunucu, Claude Code CLI'yi (`claude -p … --output-format stream-json`) alt süreç olarak başlatır. Üretim yine kullanıcının
aboneliğiyle, Claude'un kendi modeliyle yapılır (API anahtarı yok); sunucu yalnızca süreci başlatır, akışı okur, kaydeder ve panoya akıtır.
Yalnızca FS-SC MCP araçlarına izin verilir (`--allowedTools mcp__fssc-visual-observer__*`), dosya yazma/komut koşma yapılamaz
(hedef belge §12 madde 11 korkuluğu). Oturum kimliği sunucuda tutulur: "Yeniden bağlan" aynı oturumu `--resume` ile sürdürür.

Akış biçimi (Claude Code stream-json): `{"type":"system","subtype":"init","session_id":…}`, `{"type":"assistant","message":{content:[text|tool_use|thinking]}}`,
`{"type":"user","message":{content:[tool_result]}}`, `{"type":"result","subtype":"success|error…","num_turns":…,"session_id":…}`.
Bilinmeyen satırlar ham olarak saklanır; ayrıştırıcı toleranslıdır (sürümle değişebilir).

CLI kurulu değilse `status()` bunu söyler ve pano kurulum yönergesini gösterir; sunucu hiçbir şey kurmaz.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from .config import SERVER_HOST, SERVER_PORT
from .i18n import translate as tx, N_
from .proc import hidden

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SESSIONS_REL = os.path.join(".fs-workspace", "claude-sessions")
ALLOWED_TOOLS = "mcp__fssc-visual-observer__*"
DEFAULT_CLAUDE: Dict[str, Any] = {"cli": "claude", "max_turns": 80, "model": "", "extra_args": "", "transcripts_dir": "", "auto_watch": True,
                                  "auto_runner": False, "auto_runner_interval_min": 2}
AUTO_RUNNER_MIN_INTERVAL_S = 15.0     # döngü en az bu sıklıkta yoklar (testler düşürür)
STDERR_TAIL = 4000

RUNNER_PROMPT = N_("""FS-SC ekibinin sıradaki işini yürüt. Yalnızca fssc-visual-observer MCP araçlarını kullan; dosya düzenleme, komut çalıştırma.

1. claim_work çağır. Yanıt IDLE ya da BLOCKED ise nedenini tek satırla yaz ve bitir.
2. get_next_step çağır. Yanıttaki display_md metnini aynen yaz.
3. Adımı, verilen rol promptu ve bağlamla üret. Yalnızca bu bağlama dayan. Önce report_thinking ile 1-2 cümle bildir.
4. submit_step_result ile teslim et. Yanıttaki display_md metnini aynen yaz.
5. Yanıt NEXT ise 2. adıma dön. REJECTED ise validation_errors'a göre düzeltip aynı order ile tekrar gönder.
   Başka bir durumda (SESSION_BOUNDARY, BLOCKED, WAITING_APPROVAL, RUN_COMPLETE) durumu tek satırla yaz ve bitir.

Kullanıcıya soru sorma. Sorunun yeri teslimdeki questions alanıdır.""")


def scheduled_task_prompt() -> str:
    """Claude Desktop zamanlanmış görevinin talimatı: başsız runner talimatı + görevin kendi aralığını get_runner_schedule'dan okuyup eşitlemesi."""
    step0 = tx("0. get_runner_schedule çağır. Zamanlanmış görev araçların varsa (update_scheduled_task) bu görevin aralığını `interval_minutes` ile eşitle "
               "(duraklatılmışsa daha uzun). `job` yoksa (koşu bitti / iş yok) bu görevi sil ve bitir. Araç yoksa bu adımı atla.\n")
    claim = tx("1. claim_work çağır.")
    return tx(RUNNER_PROMPT).replace(claim, step0 + claim, 1)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sanitize_claude(raw: Any, fallback: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    raw = raw if isinstance(raw, dict) else {}
    base = fallback if isinstance(fallback, dict) else {}
    out = {**DEFAULT_CLAUDE, **{k: v for k, v in base.items() if k in DEFAULT_CLAUDE}}
    if isinstance(raw.get("cli"), str) and raw["cli"].strip():
        out["cli"] = raw["cli"].strip()[:400]
    if "max_turns" in raw:
        try:
            out["max_turns"] = max(1, min(int(raw["max_turns"]), 500))
        except (TypeError, ValueError):
            pass
    for key in ("model", "extra_args", "transcripts_dir"):
        if key in raw and isinstance(raw[key], str):
            out[key] = raw[key].strip()[:300]
    if "auto_watch" in raw:
        out["auto_watch"] = bool(raw["auto_watch"])
    if "auto_runner" in raw:
        out["auto_runner"] = bool(raw["auto_runner"])
    if "auto_runner_interval_min" in raw:
        try:
            out["auto_runner_interval_min"] = max(1, min(int(raw["auto_runner_interval_min"]), 60))
        except (TypeError, ValueError):
            pass
    return out


def cfg(hub) -> Dict[str, Any]:
    return sanitize_claude((hub.get_settings() or {}).get("claude"))


# Başsız oturumun ücretli (API faturalı) yola düşmesini önleyen ortam değişkenleri: yalnızca abonelik girişi kullanılır
PAID_API_ENV = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL", "ANTHROPIC_BEDROCK_BASE_URL", "ANTHROPIC_VERTEX_BASE_URL",
                "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_USE_FOUNDRY", "AWS_BEARER_TOKEN_BEDROCK")


def subscription_only_env(env: Dict[str, str]) -> Dict[str, str]:
    """API anahtarı / özel uç nokta / bulut sağlayıcı değişkenlerini çıkarır. FS-SC hiçbir zaman API anahtarıyla (token başına ücretli) çalışmaz: üretim kullanıcının
    Claude aboneliğiyledir. Giriş yoksa oturum "Not logged in" ile hemen biter (0 token), sessizce ücretli yola düşmez."""
    return {k: v for k, v in env.items() if k.upper() not in PAID_API_ENV}


def _version_key(name: str) -> tuple:
    return tuple(int(p) if p.isdigit() else 0 for p in re.split(r"[.\-]", name))


def desktop_bundled_cli() -> Optional[str]:
    """Claude Desktop'ın paketlediği Claude Code CLI'si (PATH'te `claude` yoksa): `<Claude veri klasörü>/claude-code/<sürüm>/<karma>/claude(.exe)`, en yeni sürüm.
    Saha (2026-10-14): CLI makinede vardı ama PATH'te olmadığından otomatik runner başsız oturum açamıyordu."""
    exe = "claude.exe" if os.name == "nt" else "claude"
    roots = [os.path.join(os.environ.get("APPDATA", ""), "Claude", "claude-code"),
             os.path.join(os.path.expanduser("~"), "Library", "Application Support", "Claude", "claude-code"),
             os.path.join(os.path.expanduser("~"), ".config", "Claude", "claude-code")]
    best: Optional[tuple] = None
    for root in roots:
        try:
            versions = os.listdir(root)
        except OSError:
            continue
        for ver in versions:
            vdir = os.path.join(root, ver)
            try:
                hashes = os.listdir(vdir)
            except OSError:
                continue
            for h in hashes:
                cand = os.path.join(vdir, h, exe)
                if os.path.isfile(cand) and (best is None or _version_key(ver) > best[0]):
                    best = (_version_key(ver), cand)
    return best[1] if best else None


def _resolve_exe(exe: str) -> Optional[str]:
    """Çalıştırılabilir yol: verilen dosya, PATH'te bulunan, yoksa (yalnızca varsayılan `claude` adı için) Claude Desktop'ın paketlediği CLI."""
    found = exe if os.path.isfile(exe) else (shutil.which(exe) or shutil.which(exe + ".cmd") or shutil.which(exe + ".exe"))
    if not found and os.path.basename(exe).lower() in ("claude", "claude.exe"):
        found = desktop_bundled_cli()
    return found


def _split_cli(cli: str) -> List[str]:
    cli = str(cli or "claude").strip()
    if os.path.isfile(cli):
        return [cli]
    try:
        parts = shlex.split(cli, posix=(os.name != "nt"))
    except ValueError:
        parts = cli.split()
    parts = [p.strip('"') for p in parts] or ["claude"]
    if parts[0].lower() in ("claude", "claude.exe") and not (shutil.which(parts[0]) or shutil.which(parts[0] + ".cmd") or shutil.which(parts[0] + ".exe")):
        bundled = desktop_bundled_cli()
        if bundled:
            parts[0] = bundled                         # PATH'te yok ama Desktop'ın paketlediği CLI var
    return parts


_STATUS_CACHE: Dict[str, Dict[str, Any]] = {}


def cli_status(cli: str = "claude", use_cache: bool = True) -> Dict[str, Any]:
    """Claude Code CLI bulunuyor mu, sürümü ne? (10 sn zaman aşımı; sonuç önbelleklenir.)"""
    key = str(cli or "claude")
    if use_cache and key in _STATUS_CACHE:
        return _STATUS_CACHE[key]
    parts = _split_cli(key)
    exe = parts[0]
    path = _resolve_exe(exe)
    out: Dict[str, Any] = {"ok": False, "cli": key, "path": path, "version": None, "error": None,
                           "install_hint": tx("npm install -g @anthropic-ai/claude-code && claude  (giriş yapın); ya da ayarlarda claude.cli yolunu verin. "
                                             "Claude Desktop kuruluysa paketlediği CLI otomatik bulunur.")}
    if not path:
        out["error"] = tx("'{exe}' PATH'te bulunamadı", exe=exe)
        _STATUS_CACHE[key] = out
        return out
    try:
        r = subprocess.run([path, *parts[1:], "--version"], capture_output=True, text=True, timeout=15, **hidden())
        text = (r.stdout or r.stderr or "").strip().splitlines()
        out["version"] = text[0][:80] if text else None
        out["ok"] = r.returncode == 0
        if r.returncode != 0:
            out["error"] = tx("--version çıkış kodu {code}", code=r.returncode)
    except Exception as e:  # noqa: BLE001
        out["error"] = tx("sürüm sorgusu başarısız: {error}", error=e)
    _STATUS_CACHE[key] = out
    return out


def mcp_config_path(hub) -> str:
    """Alt sürecin kullanacağı MCP yapılandırması: stdio süreci BU sunucuya (doğru port) proxy'lensin diye üretilir."""
    from . import claude_log as CL
    base = CL.project_path(hub) or REPO_ROOT
    path = os.path.join(os.path.abspath(base), ".fs-workspace", "claude-mcp.json")
    cfg_ = {"mcpServers": {"fssc-visual-observer": {
        "command": sys.executable, "args": ["-m", "server.main", "--mode", "stdio"], "cwd": REPO_ROOT,
        "env": {"PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8", "OBSERVER_PORT": str(SERVER_PORT), "PYTHONPATH": REPO_ROOT},
    }}}
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cfg_, f, ensure_ascii=False, indent=1)
    except Exception:
        return os.path.join(REPO_ROOT, ".mcp.json")
    return path


def build_command(cli: str, prompt: str, mcp_config: str, max_turns: int = 80, model: str = "", session_id: Optional[str] = None,
                  resume: Optional[str] = None, extra_args: str = "", allowed_tools: str = ALLOWED_TOOLS) -> List[str]:
    cmd = [*_split_cli(cli), "-p", prompt, "--output-format", "stream-json", "--verbose", "--max-turns", str(int(max_turns)),
           "--permission-mode", "default", "--allowedTools", allowed_tools, "--mcp-config", mcp_config, "--strict-mcp-config"]
    if model:
        cmd += ["--model", model]
    if resume:
        cmd += ["--resume", resume]
    elif session_id:
        cmd += ["--session-id", session_id]
    if extra_args:
        try:
            cmd += shlex.split(extra_args, posix=(os.name != "nt"))
        except ValueError:
            cmd += extra_args.split()
    return cmd


def _lite_event(raw: Dict[str, Any]) -> List[Dict[str, Any]]:
    """stream-json satırını panoya uygun küçük olaylara çevirir."""
    t = raw.get("type")
    ts = _now()
    sid = raw.get("session_id")
    out: List[Dict[str, Any]] = []
    if t == "system":
        out.append({"ts": ts, "kind": "system", "subtype": raw.get("subtype"), "session_id": sid, "model": raw.get("model"),
                    "tools": [x for x in (raw.get("tools") or []) if isinstance(x, str) and x.startswith("mcp__")][:40],
                    "mcp_servers": raw.get("mcp_servers")})
    elif t == "assistant":
        for b in ((raw.get("message") or {}).get("content") or []):
            if not isinstance(b, dict):
                continue
            if b.get("type") == "text" and str(b.get("text") or "").strip():
                out.append({"ts": ts, "kind": "assistant_text", "session_id": sid, "text": str(b["text"])[:6000]})
            elif b.get("type") == "thinking":
                text = str(b.get("thinking") or "")
                out.append({"ts": ts, "kind": "thinking", "session_id": sid, "text": text[:6000], "empty": not bool(text.strip())})
            elif b.get("type") == "tool_use":
                inp = b.get("input") if isinstance(b.get("input"), dict) else {}
                out.append({"ts": ts, "kind": "tool_use", "session_id": sid, "tool": b.get("name"), "tool_use_id": b.get("id"),
                            "run_id": inp.get("run_id"), "input": inp if len(json.dumps(inp, default=str)) < 6000 else {"_truncated": True}})
    elif t == "user":
        for b in ((raw.get("message") or {}).get("content") or []):
            if isinstance(b, dict) and b.get("type") == "tool_result":
                body = b.get("content")
                if isinstance(body, list):
                    body = " ".join(str(x.get("text", "")) for x in body if isinstance(x, dict))
                out.append({"ts": ts, "kind": "tool_result", "session_id": sid, "tool_use_id": b.get("tool_use_id"), "is_error": bool(b.get("is_error")),
                            "text": str(body or "")[:6000]})
    elif t == "result":
        out.append({"ts": ts, "kind": "result", "session_id": sid, "subtype": raw.get("subtype"), "is_error": bool(raw.get("is_error")),
                    "num_turns": raw.get("num_turns"), "duration_ms": raw.get("duration_ms"), "total_cost_usd": raw.get("total_cost_usd"),
                    "text": str(raw.get("result") or "")[:4000]})
    else:
        out.append({"ts": ts, "kind": "raw", "session_id": sid, "type": t})
    return out


class ClaudeBridge:
    def __init__(self, hub):
        self.hub = hub
        self.proc: Optional[asyncio.subprocess.Process] = None
        self._task: Optional[asyncio.Task] = None
        self._stderr: List[str] = []
        self.state: Dict[str, Any] = self._idle_state()
        self._auto_task: Optional[asyncio.Task] = None
        self.auto_state: Dict[str, Any] = {"enabled": False, "last_check": None, "last_reason": None, "starts": 0, "last_start": None}

    @staticmethod
    def _idle_state() -> Dict[str, Any]:
        return {"running": False, "pid": None, "session_id": None, "started_at": None, "finished_at": None, "exit_code": None,
                "events": 0, "turns": 0, "last_event": None, "result": None, "error": None, "prompt": None, "resume_of": None, "cmd": [],
                "session_file": None, "stderr_tail": ""}

    # ------------------------------------------------------------------ dosyalar
    def sessions_dir(self) -> str:
        from . import claude_log as CL
        base = CL.project_path(self.hub) or REPO_ROOT
        d = os.path.join(os.path.abspath(base), SESSIONS_REL)
        os.makedirs(d, exist_ok=True)
        return d

    def session_file(self, session_id: str) -> str:
        safe = "".join(c for c in str(session_id) if c.isalnum() or c in "-_")[:80] or "session"
        return os.path.join(self.sessions_dir(), f"{safe}.jsonl")

    def list_sessions(self, limit: int = 30) -> List[Dict[str, Any]]:
        d = self.sessions_dir()
        rows = []
        for name in os.listdir(d):
            if not name.endswith(".jsonl"):
                continue
            p = os.path.join(d, name)
            try:
                st = os.stat(p)
            except OSError:
                continue
            rows.append({"session_id": name[:-6], "file": p, "size": st.st_size, "modified_at": datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).isoformat(),
                         "running": self.state.get("running") and self.state.get("session_id") == name[:-6]})
        rows.sort(key=lambda r: r["modified_at"], reverse=True)
        return rows[:limit]

    def read_session(self, session_id: str, limit: int = 500) -> List[Dict[str, Any]]:
        p = self.session_file(session_id)
        if not os.path.isfile(p):
            return []
        out: List[Dict[str, Any]] = []
        with open(p, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                try:
                    raw = json.loads(line)
                except Exception:
                    continue
                out.extend(_lite_event(raw))
        return out[-max(1, min(int(limit), 5000)):]

    # ------------------------------------------------------------------ yaşam döngüsü
    def status(self) -> Dict[str, Any]:
        c = cfg(self.hub)
        return {**self.state, "cli": cli_status(c["cli"]), "config": c, "runner_prompt": tx(RUNNER_PROMPT), "allowed_tools": ALLOWED_TOOLS,
                "auto_runner": {**self.auto_state, "enabled": bool(c["auto_runner"]), "interval_min": self._effective_interval_min(),
                                "running": bool(self._auto_task and not self._auto_task.done())}}

    # ------------------------------------------------------------------ otomatik runner (G3): Desktop zamanlanmış görevinin sunucu tarafı karşılığı
    def _effective_interval_min(self) -> int:
        try:
            from . import driver as DRV
            return DRV.check_interval_min(self.hub)
        except Exception:  # noqa: BLE001
            return int(cfg(self.hub)["auto_runner_interval_min"])

    def sync_auto_runner(self) -> Dict[str, Any]:
        """Ayar `claude.auto_runner` ile döngüyü başlatır/durdurur (sunucu açılışında ve ayar değişince)."""
        enabled = bool(cfg(self.hub)["auto_runner"])
        self.auto_state["enabled"] = enabled
        if enabled and (self._auto_task is None or self._auto_task.done()):
            self._auto_task = asyncio.create_task(self._auto_loop(), name="claude-auto-runner")
        elif not enabled and self._auto_task and not self._auto_task.done():
            self._auto_task.cancel()
        return self.status()["auto_runner"]

    async def auto_tick(self) -> Dict[str, Any]:
        """Tek yoklama: iş varsa ve CLI hazırsa başsız oturum başlatır; nedenini kaydeder (boş yere oturum açılmaz)."""
        from . import driver as DRV
        self.auto_state["last_check"] = _now()
        if not cfg(self.hub)["auto_runner"]:
            self.auto_state["last_reason"] = "DISABLED"
            return self.auto_state
        if self.state.get("running"):
            self.auto_state["last_reason"] = "SESSION_RUNNING"
            return self.auto_state
        st = cli_status(cfg(self.hub)["cli"])
        if not st["ok"]:
            self.auto_state["last_reason"] = f"CLI_UNAVAILABLE: {st.get('error')}"
            return self.auto_state
        cw = DRV.claimable_work(self.hub)
        if not cw["claimable"]:
            self.auto_state["last_reason"] = cw["reason"]
            return self.auto_state
        res = await self.start()
        self.auto_state["last_reason"] = f"STARTED ({cw['reason']})" if res.get("status") == "STARTED" else f"{res.get('status')}: {res.get('error') or ''}"
        if res.get("status") == "STARTED":
            self.auto_state["starts"] = int(self.auto_state.get("starts") or 0) + 1
            self.auto_state["last_start"] = _now()
        return self.auto_state

    async def _auto_loop(self) -> None:
        while True:
            try:
                from . import driver as DRV
                interval = max(AUTO_RUNNER_MIN_INTERVAL_S, float(DRV.check_interval_min(self.hub)) * 60.0)     # duraklatılmışsa daha seyrek (örn. 30 dk), değilse 10 dk
                self.auto_state["next_check_at"] = (datetime.now(timezone.utc) + timedelta(seconds=interval)).isoformat()
                await asyncio.sleep(interval)
                await self.auto_tick()
            except asyncio.CancelledError:
                return
            except Exception:  # noqa: BLE001
                continue

    async def start(self, prompt: Optional[str] = None, resume: Optional[str] = None, max_turns: Optional[int] = None) -> Dict[str, Any]:
        if self.state.get("running"):
            return {"status": "ALREADY_RUNNING", "state": self.status()}
        c = cfg(self.hub)
        st = cli_status(c["cli"], use_cache=False)
        if not st["ok"]:
            return {"status": "CLI_UNAVAILABLE", "state": self.status(), "error": st.get("error"), "install_hint": st.get("install_hint")}
        session_id = None if resume else str(uuid.uuid4())
        cmd = build_command(c["cli"], prompt or tx(RUNNER_PROMPT), mcp_config_path(self.hub), max_turns=int(max_turns or c["max_turns"]), model=c["model"],
                            session_id=session_id, resume=resume, extra_args=c["extra_args"])
        env = {**subscription_only_env(dict(os.environ)), "OBSERVER_PORT": str(SERVER_PORT), "OBSERVER_HOST": SERVER_HOST, "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1",
               "CLAUDE_CODE_DISABLE_AUTOUPDATE": "1"}
        try:
            self.proc = await asyncio.create_subprocess_exec(
                *cmd, cwd=REPO_ROOT, env=env, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, stdin=asyncio.subprocess.DEVNULL,
                **hidden(),
            )
        except Exception as e:  # noqa: BLE001
            return {"status": "START_FAILED", "error": str(e)[:300], "state": self.status()}
        self._stderr = []
        self.state = {**self._idle_state(), "running": True, "pid": self.proc.pid, "session_id": resume or session_id, "started_at": _now(),
                      "prompt": (prompt or tx(RUNNER_PROMPT))[:2000], "resume_of": resume, "cmd": [c if i != 2 else "<prompt>" for i, c in enumerate(cmd)],
                      "session_file": self.session_file(resume or session_id or "session")}
        self._task = asyncio.create_task(self._pump(), name="claude-bridge")
        await self._broadcast_status("STARTED")
        from . import claude_log as CL
        await CL.record(self.hub, direction="server", tool="claude_start", status="STARTED", session_id=self.state["session_id"],
                        args={"resume": resume, "max_turns": int(max_turns or c["max_turns"]), "cli": c["cli"]}, text=(prompt or tx(RUNNER_PROMPT))[:4000])
        return {"status": "STARTED", "state": self.status()}

    async def _broadcast_status(self, event: str) -> None:
        try:
            await self.hub.broadcast({"type": "CLAUDE_SESSION_STATUS", "event": event, "state": {k: v for k, v in self.state.items() if k != "cmd"}})
        except Exception:
            pass

    async def _pump(self) -> None:
        assert self.proc is not None
        proc = self.proc
        fh = None    # oturum dosyası CLI'nin bildirdiği oturum kimliğiyle açılır (init olayından sonra); o yüzden ilk satırda açılır
        try:
            async def read_err():
                assert proc.stderr is not None
                async for raw in proc.stderr:
                    line = raw.decode("utf-8", errors="replace").rstrip()
                    if line:
                        self._stderr.append(line[:500])
                        self._stderr = self._stderr[-60:]
            err_task = asyncio.create_task(read_err())
            assert proc.stdout is not None
            async for raw in proc.stdout:
                line = raw.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except Exception:
                    data = {"type": "stdout", "text": line[:2000]}
                if data.get("type") == "system" and data.get("session_id"):
                    self.state["session_id"] = data["session_id"]
                if fh is None:
                    path = self.session_file(self.state.get("session_id") or "session")
                    self.state["session_file"] = path
                    fh = open(path, "a", encoding="utf-8")
                fh.write(json.dumps(data, ensure_ascii=False) + "\n")
                fh.flush()
                await self._handle(data)
            await err_task
        finally:
            if fh is not None:
                fh.close()
            code = await proc.wait()
            self.state.update({"running": False, "finished_at": _now(), "exit_code": code, "stderr_tail": "\n".join(self._stderr)[-STDERR_TAIL:]})
            if code != 0 and not self.state.get("error"):
                self.state["error"] = tx("Claude süreci {code} koduyla bitti", code=code) + (f": {self._stderr[-1][:200]}" if self._stderr else "")
            await self._broadcast_status("FINISHED")
            from . import claude_log as CL
            await CL.record(self.hub, direction="server", tool="claude_finished", status="OK" if code == 0 else "ERROR", session_id=self.state.get("session_id"),
                            result={"exit_code": code, "events": self.state.get("events"), "turns": self.state.get("turns"), "result": self.state.get("result")},
                            error=self.state.get("error"))

    async def _handle(self, data: Dict[str, Any]) -> None:
        if data.get("type") == "system" and data.get("session_id"):
            self.state["session_id"] = data["session_id"]
        if data.get("type") == "result":
            self.state["result"] = {k: data.get(k) for k in ("subtype", "is_error", "num_turns", "duration_ms", "total_cost_usd")}
            self.state["turns"] = int(data.get("num_turns") or self.state.get("turns") or 0)
            if data.get("is_error"):
                self.state["error"] = str(data.get("result") or data.get("subtype") or tx("hata"))[:300]
        for ev in _lite_event(data):
            self.state["events"] = int(self.state.get("events") or 0) + 1
            if ev["kind"] == "assistant_text":
                self.state["turns"] = int(self.state.get("turns") or 0) + 1
            self.state["last_event"] = {"ts": ev["ts"], "kind": ev["kind"], "tool": ev.get("tool"), "text": str(ev.get("text") or "")[:200]}
            try:
                await self.hub.broadcast({"type": "CLAUDE_SESSION_EVENT", "session_id": self.state.get("session_id"), "event": ev})
            except Exception:
                pass
            if ev["kind"] in ("assistant_text", "thinking", "tool_use", "result"):
                try:
                    from . import claude_log as CL
                    await CL.record(self.hub, direction="client", tool=ev.get("tool") or ev["kind"], run_id=ev.get("run_id"), status=ev["kind"],
                                    text=ev.get("text") if ev["kind"] != "tool_use" else None, args=ev.get("input") if ev["kind"] == "tool_use" else None,
                                    session_id=self.state.get("session_id"))
                except Exception:
                    pass

    async def stop(self) -> Dict[str, Any]:
        proc = self.proc
        if proc is None or not self.state.get("running"):
            return {"status": "NOT_RUNNING", "state": self.status()}
        try:
            if sys.platform.startswith("win"):
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True, timeout=30, **hidden())
            else:
                proc.terminate()
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
        self.state["error"] = self.state.get("error") or tx("yönetici durdurdu")
        try:
            await asyncio.wait_for(proc.wait(), timeout=15)
        except Exception:
            pass
        return {"status": "STOPPED", "state": self.status()}


def bridge(hub) -> ClaudeBridge:
    b = getattr(hub, "_claude_bridge", None)
    if b is None:
        b = ClaudeBridge(hub)
        hub._claude_bridge = b
    return b
