"""
E2E adımı (7) için uygulama başlatıcı.

Mimarın/DevOps'un verdiği `run` komutuyla uygulamayı proje klasöründe başlatır, `health_url` (yoksa `app_url`)
yanıt verene kadar bekler, Playwright testi bittikten sonra süreç ağacını kapatır. Komut yoksa hiçbir şey
başlatılmaz ve çağıran taraf mevcut `e2e_target_url` ayarına düşer.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import time
import urllib.request
from typing import Any, Dict, Optional

from .i18n import translate as tx
from .proc import hidden

APP_START_TIMEOUT_S = float(os.environ.get("APP_START_TIMEOUT_S", "90"))


class RunningApp:
    def __init__(self, proc: asyncio.subprocess.Process, cmd: str, url: str, log_path: str):
        self.proc = proc
        self.cmd = cmd
        self.url = url
        self.log_path = log_path
        self.started_at = time.time()

    @property
    def alive(self) -> bool:
        return self.proc.returncode is None

    async def stop(self) -> None:
        if not self.alive:
            return
        try:
            if sys.platform.startswith("win"):
                # Süreç ağacını kapat (npm → node, uvicorn → worker ...)
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(self.proc.pid)], capture_output=True, timeout=30, **hidden())
            else:
                import signal
                os.killpg(os.getpgid(self.proc.pid), signal.SIGTERM)
        except Exception:
            try:
                self.proc.kill()
            except Exception:
                pass
        try:
            await asyncio.wait_for(self.proc.wait(), timeout=15)
        except Exception:
            pass

    def tail(self, limit: int = 3000) -> str:
        try:
            with open(self.log_path, "r", encoding="utf-8", errors="replace") as f:
                data = f.read()
            return data[-limit:]
        except OSError:
            return ""


def _probe(url: str, timeout: float = 3.0) -> Optional[int]:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "fssc-app-runner"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (yerel adres)
            return resp.status
    except urllib.error.HTTPError as e:  # sunucu ayakta ama 4xx/5xx döndü
        return e.code
    except Exception:
        return None


def _healthy(status: Optional[int]) -> bool:
    """G1: sağlık adresi 2xx/3xx dönmeli; 401/403 'ayakta ama korumalı' sayılır. 404 (yanlış adres) ve 5xx (çöküyor) ayakta DEĞİLDİR."""
    return status is not None and (status < 400 or status in (401, 403))


async def wait_until_up_detail(url: str, timeout_s: float) -> Dict[str, Any]:
    """{'status': sağlıklı kod | None, 'last': son görülen kod | None}"""
    deadline = time.time() + timeout_s
    loop = asyncio.get_running_loop()
    last: Optional[int] = None
    while time.time() < deadline:
        status = await loop.run_in_executor(None, _probe, url)
        if _healthy(status):
            return {"status": status, "last": status}
        if status is not None:
            last = status
        await asyncio.sleep(1.0)
    return {"status": None, "last": last}


async def wait_until_up(url: str, timeout_s: float) -> Optional[int]:
    return (await wait_until_up_detail(url, timeout_s))["status"]


async def start_app(project_dir: str, run_cmd: str, health_url: str, log_dir: Optional[str] = None,
                    timeout_s: float = APP_START_TIMEOUT_S) -> Dict[str, Any]:
    """
    Uygulamayı başlatır ve sağlık adresini bekler.
    Dönüş: {'ok': bool, 'app': RunningApp|None, 'status': int|None, 'error': str|None, 'log': str}
    """
    log_dir = log_dir or os.path.join(project_dir, ".fs-workspace")
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, "app_run.log")
    from .verify import subprocess_env
    env = {**subprocess_env(), "BROWSER": "none"}
    try:
        log_fh = open(log_path, "wb")
        kwargs: Dict[str, Any] = hidden()                  # Windows: pencere açma (uygulamanın alt süreçleri gizli konsolu devralır)
        if not sys.platform.startswith("win"):
            kwargs["start_new_session"] = True
        proc = await asyncio.create_subprocess_shell(
            run_cmd, cwd=project_dir, env=env, stdout=log_fh, stderr=asyncio.subprocess.STDOUT,
            stdin=asyncio.subprocess.DEVNULL, **kwargs,
        )
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "app": None, "status": None, "error": tx("Uygulama başlatılamadı: {error}", error=e), "log": ""}
    app = RunningApp(proc, run_cmd, health_url, log_path)
    detail = await wait_until_up_detail(health_url, timeout_s)
    status = detail["status"]
    if status is None:
        err = (tx("Uygulama {secs} sn içinde {url} adresinde sağlıklı yanıt vermedi", secs=int(timeout_s), url=health_url)
               + (tx(" (son yanıt HTTP {code}: 404 yanlış adres, 5xx çöküyor demektir)", code=detail['last']) if detail.get("last") is not None else ""))
        if not app.alive:
            err += tx(" (süreç çıkış kodu {code})", code=proc.returncode)
        log = app.tail()
        await app.stop()
        try:
            log_fh.close()
        except Exception:
            pass
        return {"ok": False, "app": None, "status": None, "error": err, "log": log}
    return {"ok": True, "app": app, "status": status, "error": None, "log": app.tail(800)}
