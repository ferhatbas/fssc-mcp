"""
Server package initialization.

`app`, `mcp`, `hub` ve `TelemetryHub` tembel (lazy) dışa aktarılır: `python -m server.main` ile başlatıldığında paketin
`server.main`'i erkenden içe aktarması modülün iki kez çalışmasına (iki FastAPI/MCP örneği, RuntimeWarning) yol açıyordu;
hub'ı erkenden yüklemek de hafif stdio proxy'nin (`server.stdio_proxy`) başlangıcını ~6 sn geciktiriyordu.
"""

__all__ = ["TelemetryHub", "hub", "app", "mcp"]


def __getattr__(name):
    if name in ("app", "mcp"):
        from . import main as _main
        return getattr(_main, name)
    if name in ("TelemetryHub", "hub"):
        from . import telemetry as _telemetry
        return getattr(_telemetry, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
