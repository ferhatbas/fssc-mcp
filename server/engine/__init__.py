"""Pipeline yürütme motorları: süreç içi şablon motoru ve MCP istemcisi (Claude Desktop / Antigravity) çekme motoru.

Dışa aktarımlar tembeldir: hafif stdio proxy (`server.stdio_proxy`) yalnızca `engine.proxy`/`engine.errors` ister;
şablon motoru ve koşu API'sinin ağır bağımlılıkları (hub, pipeline) onun başlangıcını yavaşlatmasın.
"""

__all__ = ["TemplateEngine", "McpClientEngine", "LocalRunsApi"]


def __getattr__(name):
    if name == "TemplateEngine":
        from .template import TemplateEngine
        return TemplateEngine
    if name == "McpClientEngine":
        from .mcp_client import McpClientEngine
        return McpClientEngine
    if name == "LocalRunsApi":
        from .api import LocalRunsApi
        return LocalRunsApi
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
