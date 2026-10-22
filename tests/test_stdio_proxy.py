"""Hafif stdio proxy: araç imzaları tam `server.main` ile aynı kalmalı; başlangıçta ağır modüller yüklenmemeli (Claude MCP bağlantı sınırı 30 sn)."""
import subprocess
import sys

from mcp import Client
from mcp.types import Implementation

from server import stdio_proxy as SP


async def _surface(server):
    async with Client(server, client_info=Implementation(name="pytest", version="0")) as c:
        tools = {t.name: (t.description, t.input_schema if hasattr(t, "input_schema") else t.inputSchema, getattr(t, "output_schema", None) or getattr(t, "outputSchema", None))
                 for t in (await c.list_tools()).tools}
        prompts = {p.name: p.description for p in (await c.list_prompts()).prompts}
        text = (await c.get_prompt("run_software_company", {"project_id": "x", "steps": "1-3"})).messages[0].content.text
    return tools, prompts, text


async def test_proxy_main_ile_ayni_arac_ve_istem_yuzeyi():
    from server.main import mcp as full
    full_tools, full_prompts, full_text = await _surface(full)
    px_tools, px_prompts, px_text = await _surface(SP.mcp)
    assert set(px_tools) == set(full_tools)
    for name in full_tools:
        assert px_tools[name] == full_tools[name], f"{name}: imza/şema/açıklama ayrıştı"
    assert px_prompts == full_prompts and px_text == full_text


def test_proxy_agir_modulleri_yuklemez():
    code = ("import sys, server.stdio_proxy; bad=[m for m in ('server.telemetry','fastapi','server.pipeline','server.main') if m in sys.modules]; "
            "print(bad); sys.exit(1 if bad else 0)")
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=SP.__file__.rsplit("server", 1)[0])
    assert r.returncode == 0, r.stdout + r.stderr


def test_should_use_kosullari(monkeypatch):
    monkeypatch.setattr(SP, "web_server_up", lambda timeout=1.5: True)
    assert SP.should_use(["x", "--mode", "stdio"]) is True
    assert SP.should_use(["x", "--mode", "web"]) is False
    assert SP.should_use(["x"]) is False
    monkeypatch.setenv("FSSC_EMBEDDED_HUB", "1")
    assert SP.should_use(["x", "--mode", "stdio"]) is False
    monkeypatch.delenv("FSSC_EMBEDDED_HUB")
    monkeypatch.setattr(SP, "web_server_up", lambda timeout=1.5: False)
    assert SP.should_use(["x", "--mode", "stdio"]) is False
