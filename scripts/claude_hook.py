"""
Claude Code kancası (G2 / K3): Claude Code'un hook olayını (stdin'deki JSON) FS-SC sunucusuna iletir.

Kurulum: `configs/claude_code_hooks.example.json` içeriğini depo kökündeki `.claude/settings.json` (ya da kullanıcı ayarına) ekleyin.
Olaylar: SessionStart (transcript_path → sunucu transkripti izlemeye başlar), PreToolUse/PostToolUse (FS-SC araçları), Stop.
Asla başarısız olmaz (çıkış 0): sunucu kapalıysa olay sessizce düşer; Claude oturumu etkilenmez.
"""
import json
import os
import sys
import urllib.request


def _port() -> str:
    env = os.environ.get("OBSERVER_PORT")
    if env:
        return env
    try:
        here = os.path.dirname(os.path.abspath(__file__))
        cfg = json.load(open(os.path.join(here, "..", ".mcp.json"), encoding="utf-8"))
        return str(cfg["mcpServers"]["fssc-visual-observer"]["env"]["OBSERVER_PORT"])
    except Exception:
        return "8099"


def main() -> int:
    raw = sys.stdin.read()
    try:
        data = json.loads(raw) if raw.strip() else {}
    except Exception:
        data = {"raw": raw[:4000]}
    data.setdefault("hook_event_name", os.environ.get("CLAUDE_HOOK_EVENT") or "hook")
    body = json.dumps(data, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(f"http://127.0.0.1:{_port()}/api/claude/hook", data=body, headers={"Content-Type": "application/json"}, method="POST")
    try:
        urllib.request.urlopen(req, timeout=3).read()
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
