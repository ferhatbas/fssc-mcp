"""Claude Desktop'a FS-SC `fssc-visual-observer` MCP sunucusunu kaydeder (Windows).

Claude Desktop, %APPDATA%\\Claude\\claude_desktop_config.json dosyasını bellekte tutar ve tercih
değişikliklerinde TAMAMINI yeniden yazar; uygulama açıkken elle eklenen `mcpServers` girdisi kaybolur.
Bu betik girdiyi güvenli sırayla yazar: (Claude Desktop'ı kapat) -> yedekle -> yaz -> (yeniden başlat).

Kullanım:
  python scripts/register_claude_desktop.py            # Claude Desktop kapalıysa yazar; açıksa uyarıp çıkar
  python scripts/register_claude_desktop.py --restart  # Claude Desktop'ı kapatır, yazar, yeniden başlatır
  python scripts/register_claude_desktop.py --print    # yazılacak JSON parçasını gösterir
  python scripts/register_claude_desktop.py --force    # açıkken de yazar (kaybolabilir; önerilmez)

--restart, işi ayrı (bağımsız) bir sürece devreder; Claude Desktop içindeki terminalden
çalıştırılsa bile uygulama kapanırken iş yarım kalmaz. Kayıt: scripts/.register_claude_desktop.log
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import shutil
import subprocess
import sys
import time

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SERVER_NAME = "fssc-visual-observer"
LEGACY_NAMES = ("antigravity-visual-observer",)  # eski ad: yazarken kaldırılır
CONFIG_PATH = os.path.join(os.environ.get("APPDATA", ""), "Claude", "claude_desktop_config.json")
LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".register_claude_desktop.log")


def log(msg: str) -> None:
    line = f"[{dt.datetime.now():%H:%M:%S}] {msg}"
    print(line, flush=True)
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:
        pass


def server_entry() -> dict:
    return {
        "command": sys.executable,
        "args": ["-m", "server.main", "--mode", "stdio"],
        "cwd": ROOT,
        "env": {
            "PYTHONUNBUFFERED": "1",
            "PYTHONIOENCODING": "utf-8",
            "PYTHONPATH": ROOT,
            "OBSERVER_PORT": os.environ.get("OBSERVER_PORT", "8099"),
        },
    }


# Claude Code CLI süreçleri de "claude.exe" adını taşır; masaüstü uygulaması yolundan ayırt edilir
_APP_FILTER = r"$_.Path -and $_.Path -notlike '*\claude-code\*'"


def _ps(cmd: str) -> str:
    return subprocess.run(["powershell", "-NoProfile", "-Command", cmd], capture_output=True, text=True).stdout.strip()


def claude_running() -> bool:
    if os.name != "nt":
        return False
    out = _ps(f"Get-Process claude -ErrorAction SilentlyContinue | Where-Object {{ {_APP_FILTER} }} | Select-Object -ExpandProperty Id")
    return bool(out)


def stop_claude() -> None:
    log("Claude Desktop kapatılıyor (Claude Code CLI süreçlerine dokunulmaz)...")
    _ps(f"Get-Process claude -ErrorAction SilentlyContinue | Where-Object {{ {_APP_FILTER} }} | ForEach-Object {{ $null = $_.CloseMainWindow() }}")
    for _ in range(20):
        if not claude_running():
            break
        time.sleep(0.5)
    if claude_running():
        log("Nazik kapatma yetmedi, zorla kapatılıyor.")
        _ps(f"Get-Process claude -ErrorAction SilentlyContinue | Where-Object {{ {_APP_FILTER} }} | Stop-Process -Force")
        time.sleep(1.5)


def start_claude() -> None:
    # Microsoft Store (MSIX) kurulumu: paket aile adı üzerinden başlat
    pfn = _ps("(Get-AppxPackage -Name Claude).PackageFamilyName")
    if pfn:
        log(f"Claude Desktop başlatılıyor (Store paketi {pfn}).")
        subprocess.Popen(["explorer.exe", f"shell:AppsFolder\\{pfn}!Claude"])
        return
    for exe in (
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "AnthropicClaude", "claude.exe"),
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Claude", "Claude.exe"),
    ):
        if os.path.isfile(exe):
            log(f"Claude Desktop başlatılıyor ({exe}).")
            subprocess.Popen([exe], creationflags=getattr(subprocess, "DETACHED_PROCESS", 0))
            return
    log("Claude Desktop yürütülebilir dosyası bulunamadı; lütfen elle başlatın.")


def write_config() -> str:
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    data: dict = {}
    if os.path.isfile(CONFIG_PATH):
        backup = f"{CONFIG_PATH}.bak-{dt.datetime.now():%Y%m%d-%H%M%S}"
        shutil.copy2(CONFIG_PATH, backup)
        log(f"Yedek: {backup}")
        with open(CONFIG_PATH, encoding="utf-8") as fh:
            data = json.load(fh)
    servers = data.setdefault("mcpServers", {})
    for legacy in LEGACY_NAMES:
        servers.pop(legacy, None)
    servers[SERVER_NAME] = server_entry()
    tmp = CONFIG_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
    os.replace(tmp, CONFIG_PATH)
    with open(CONFIG_PATH, encoding="utf-8") as fh:
        assert SERVER_NAME in json.load(fh).get("mcpServers", {})
    log(f"Yazıldı: {CONFIG_PATH} -> mcpServers.{SERVER_NAME}")
    return CONFIG_PATH


def spawn_detached_worker() -> None:
    """Kendini bağımsız bir süreç olarak yeniden çağırır (Claude Desktop kapanınca ölmesin diye)."""
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    subprocess.Popen(
        [sys.executable, os.path.abspath(__file__), "--restart-worker"],
        creationflags=flags, close_fds=True,
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--restart", action="store_true", help="Claude Desktop'ı kapat, yaz, yeniden başlat (ayrı süreçte)")
    ap.add_argument("--force", action="store_true", help="Claude Desktop açıkken de yaz")
    ap.add_argument("--print", dest="show", action="store_true", help="Yazılacak JSON parçasını göster")
    ap.add_argument("--restart-worker", action="store_true", help=argparse.SUPPRESS)
    args = ap.parse_args()

    if args.show:
        print(json.dumps({"mcpServers": {SERVER_NAME: server_entry()}}, indent=2, ensure_ascii=False))
        return 0

    if args.restart_worker:
        time.sleep(1.0)  # çağıran terminal kapanabilsin
        stop_claude()
        write_config()
        start_claude()
        log("Tamam. Claude Desktop yeni sohbette araçlar simgesini göstermeli.")
        return 0

    if args.restart:
        log("Bağımsız süreç başlatılıyor: Claude Desktop kapatılacak, kayıt yazılacak, uygulama yeniden açılacak.")
        log(f"İlerleme: {LOG_PATH}")
        spawn_detached_worker()
        return 0

    if claude_running() and not args.force:
        log("Claude Desktop açık. Uygulama açıkken yazılan girdi, uygulama dosyayı yeniden yazınca silinir.")
        log("Seçenekler: Claude Desktop'ı tamamen kapatıp bu komutu tekrar çalıştırın, ya da: --restart")
        return 2

    write_config()
    if not claude_running():
        log("Claude Desktop'ı başlatın; araçlar simgesinde 'fssc-visual-observer' görünmeli.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
