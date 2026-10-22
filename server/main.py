"""
FS-SC Görsel MCP Sunucusu (FastMCP / MCPServer 2.x + FastAPI + WebSocket).
Genişletilmiş Yazılım Şirketi API'si:
- Jira Görev Tahtası (1-8 Maddelik Toplu Yürütme)
- Müşteri Görüşmeleri & Şartname/Dosya Kasası (Uploads)
- Playwright E2E Gerçek Tarayıcı Test Motoru & Screenshot Dağıtımı
- Özel Ajan & Kıdemli Geliştirici Yönetimi
"""

import argparse
import asyncio
import functools
from contextlib import asynccontextmanager
from datetime import datetime, timezone
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

if __name__ == "__main__":
    # Çalışan web sunucusu varken `--mode stdio`: hub/FastAPI yüklemeden hafif proxy (başlangıç ~14 sn → saniyeler; Claude MCP bağlantı sınırı 30 sn)
    from . import stdio_proxy as _stdio_proxy
    if _stdio_proxy.should_use(sys.argv):
        _stdio_proxy.run()
        raise SystemExit(0)

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, File, UploadFile, Form, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
import uvicorn

from .config import CORS_ORIGINS, SERVER_HOST, SERVER_PORT
from .telemetry import hub
from .paths import hub_docs_path
from .proc import CREATE_BREAKAWAY_FROM_JOB, CREATE_NEW_PROCESS_GROUP, CREATE_NO_WINDOW
from .doc_text import is_readable, read_text
from .runner import execute_tests_only_pipeline
from .playwright_tester import run_playwright_e2e_tests, SCREENSHOTS_REL
from .engine.api import LocalRunsApi, RunsApiError
from .mcp_models import ApprovalStatus, ClaimResult, DeliberationInfo, NextStep, RunInfo, RunList, SubmitResult, compact_run
from .i18n import translate as tx, N_
from . import claude_log as CL
from . import claude_bridge as CB
from . import claude_transcripts as CT

# 1. MCP Sunucu Nesnesi (MCP 2.x standardı)
mcp = MCPServer("fssc-visual-observer")

from .mcp_common import (_LOG_ARG_KEYS, _PULL_LOOP_TOOLS, _client_info, _outcome_of, _plain_result, _tool_error,  # noqa: F401
                         run_software_company_prompt)


async def _record_mcp_tool_call(name: str, kwargs: Dict[str, Any], outcome: str, result: Any = None) -> None:
    """Her MCP araç çağrısını Claude iletişim günlüğüne (özet + G2 tam etkileşim günlüğü) yazar. Hata araç çağrısını asla bozmaz."""
    try:
        client = _client_info(kwargs.get("ctx"), str(kwargs.get("client_name") or ""))
        args = " ".join(f"{k}={kwargs[k]}" for k in _LOG_ARG_KEYS if kwargs.get(k) not in (None, "", []))
        full_args = {k: v for k, v in kwargs.items() if k != "ctx"}
        payload = {"tool": name, "result": outcome, "title": args[:120], "client": client, "run_id": kwargs.get("run_id") or None,
                   "args": full_args, "result_full": _plain_result(result)}
        if _PROXY_BASE_URL:
            await runs_api()._call("POST", "/api/mcp/log", json=payload)     # stdio süreci: kayıt web sunucusunun hub'ına gider
            return
        from . import mcp_activity as MA
        h = get_hub()
        if client.get("name"):
            await h.mark_client_seen(client["name"], client.get("version", ""))
        await MA.log_call(h, name, None, client, result=outcome, title=payload["title"], run_id=payload["run_id"])
        await CL.record(h, direction="to_server", tool=name, run_id=payload["run_id"], client=client, status=outcome, args=full_args, result=payload["result_full"])
    except Exception:  # noqa: BLE001
        pass


_original_tool = mcp.tool


def _logged_tool(*tool_args, **tool_kwargs):
    """`@mcp.tool()` yerine geçer: aynı aracı kaydeder, ama her çağrıyı günlüğe de yazar."""
    register = _original_tool(*tool_args, **tool_kwargs)

    def apply(fn):
        import functools
        import inspect
        name = tool_kwargs.get("name") or fn.__name__
        if name in _PULL_LOOP_TOOLS or not inspect.iscoroutinefunction(fn):
            return register(fn)

        @functools.wraps(fn)
        async def wrapper(*args, **kwargs):
            outcome = "OK"
            result = None
            try:
                result = await fn(*args, **kwargs)
                outcome = _outcome_of(result)
                return result
            except Exception as e:  # noqa: BLE001
                outcome = f"ERROR: {str(e)[:70]}"
                raise
            finally:
                await _record_mcp_tool_call(name, kwargs, outcome, result)

        return register(wrapper)

    return apply


mcp.tool = _logged_tool


def get_hub():
    """Aktif TelemetryHub örneği (testler `server.main.hub`'ı izole bir örnekle değiştirebilir)."""
    return hub


# Koşu API'si: yerel (aynı süreçteki hub) ya da proxy (stdio modunda ayrı çalışan web sunucusuna httpx)
_PROXY_BASE_URL: Optional[str] = None
_proxy_api = None


def runs_api():
    """MCP araçları ve REST uçlarının kullandığı koşu API'si (hub'a bağlı, test dostu)."""
    global _proxy_api
    if _PROXY_BASE_URL:
        if _proxy_api is None:
            from .engine.proxy import ProxyRunsApi
            _proxy_api = ProxyRunsApi(_PROXY_BASE_URL)
        return _proxy_api
    h = get_hub()
    api = getattr(h, "_runs_api", None)
    if api is None or api.hub is not h:
        api = LocalRunsApi(h)
        setattr(h, "_runs_api", api)
    return api


@asynccontextmanager
async def lifespan(_app: FastAPI):
    api = runs_api()
    if isinstance(api, LocalRunsApi):
        api.mcp.start_sweeper()
        try:
            CB.bridge(hub).sync_auto_runner()     # G3: ayar açıksa otomatik runner döngüsü
        except Exception:
            pass
    yield
    if isinstance(api, LocalRunsApi):
        await api.mcp.stop_sweeper()
    try:
        await CT.watcher(hub).stop()
        b = CB.bridge(hub)
        if b._auto_task and not b._auto_task.done():
            b._auto_task.cancel()
        if b.state.get("running"):
            await b.stop()
    except Exception:
        pass
    # Kapanışta bekleyen kalıcılık yazımlarını tamamla
    try:
        await hub.flush_async()
    except Exception:
        pass


# 2. FastAPI Web ve WebSocket Sunucusu
app = FastAPI(
    title="FS-SC Visual MCP Observer & Software Agency OS",
    description="Multi-Agent Software Company Telemetry, Jira Board, and E2E Browser Testing",
    version="2.0.0",
    lifespan=lifespan
)

# CORS Yapılandırması (React Vite Dashboard için)
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Statik Klasörler (Screenshots & Uploads) — AGY_DATA_DIR ile yeniden konumlandırılabilir
_DATA_DIR = os.environ.get("AGY_DATA_DIR") or os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
# Eski (F1 öncesi) FS-SC kökündeki klasörler: yalnızca VARSA ve yalnızca okuma için servis edilir; yeni dosya buraya yazılmaz.
LEGACY_SCREENSHOTS_DIR = os.path.abspath(os.path.join(_DATA_DIR, "reports", "screenshots"))
LEGACY_UPLOADS_DIR = os.path.abspath(os.path.join(_DATA_DIR, "uploads"))
UPLOADS_REL = ".fs-workspace/specs/uploads"

_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]")


def safe_name(value: str, max_len: int = 120) -> str:
    """Kullanıcı girdisinden güvenli dosya/klasör adı üretir (yol ayraçları ve özel karakterler temizlenir)."""
    base = os.path.basename(str(value or "").replace("\\", "/")).strip()
    cleaned = _SAFE_NAME_RE.sub("_", base).strip("._")
    return (cleaned or "item")[:max_len]


def resolve_inside(base_dir: str, *parts: str) -> Optional[str]:
    """Yolu `base_dir` altında çözer; dışarı çıkıyorsa None döner."""
    base = Path(base_dir).resolve()
    candidate = base.joinpath(*parts).resolve()
    try:
        candidate.relative_to(base)
    except ValueError:
        return None
    return str(candidate)

if os.path.isdir(LEGACY_SCREENSHOTS_DIR):
    app.mount("/reports/screenshots", StaticFiles(directory=LEGACY_SCREENSHOTS_DIR), name="screenshots")
if os.path.isdir(LEGACY_UPLOADS_DIR):
    app.mount("/uploads", StaticFiles(directory=LEGACY_UPLOADS_DIR), name="uploads")


def project_path_for(project_id: Optional[str]) -> Optional[str]:
    """Kayıtlı projenin kök klasörü (yoksa None)."""
    info = hub.projects.get(project_id or hub.active_project_id) or {}
    return info.get("path") or None


def project_file_dir(project_id: Optional[str], rel: str) -> Optional[str]:
    root = project_path_for(project_id)
    return resolve_inside(root, *rel.split("/")) if root else None


def _serve_project_file(project_id: str, rel: str, filename: str):
    base = project_file_dir(project_id, rel)
    target = resolve_inside(base, safe_name(filename)) if base else None
    if not target or not os.path.isfile(target):
        return JSONResponse(status_code=404, content={"error": tx("Dosya bulunamadı.")})
    return FileResponse(target)


@app.get("/api/projects/{project_id}/screenshots/{filename}")
async def project_screenshot(project_id: str, filename: str):
    """E2E ekran görüntüsü: hedef projenin `.fs-workspace/e2e/screenshots/` klasöründen."""
    return _serve_project_file(project_id, SCREENSHOTS_REL, filename)


@app.get("/api/projects/{project_id}/uploads/{filename}")
async def project_upload(project_id: str, filename: str):
    """Yüklenen şartname dosyası: hedef projenin `.fs-workspace/specs/uploads/` klasöründen."""
    return _serve_project_file(project_id, UPLOADS_REL, filename)


# ---------------------------------------------------------------------------
# WebSocket Endpoint
# ---------------------------------------------------------------------------
@app.websocket("/ws/telemetry")
async def websocket_telemetry_endpoint(websocket: WebSocket):
    """React Flow panosunun gerçek zamanlı bağlandığı telemetri kanalı."""
    await hub.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            try:
                msg = json.loads(data)
                if msg.get("action") == "PING":
                    await websocket.send_text(json.dumps({"type": "PONG"}))
            except Exception:
                pass
    except WebSocketDisconnect:
        hub.disconnect(websocket)
    except Exception:
        hub.disconnect(websocket)


# ---------------------------------------------------------------------------
# REST API Endpoints (Temel Durum ve Telemetri)
# ---------------------------------------------------------------------------
@app.get("/api/state")
async def get_state():
    """Tüm ajan durumlarını, görevleri, Jira maddelerini ve geçmişi döner."""
    return JSONResponse(content=hub.get_snapshot())


@app.post("/api/events")
async def post_event(body: Dict[str, Any]):
    """HTTP üzerinden olay tetikleme."""
    event = await hub.record_event(
        trace_id=body.get("trace_id", "test-trace"),
        from_agent=body.get("from_agent", "PM"),
        to_agent=body.get("to_agent", "ARCHITECT"),
        action=body.get("action", "ACTION"),
        status=body.get("status", "SUCCESS"),
        payload=body.get("payload", {}),
        current_file=body.get("current_file"),
        tokens_used=body.get("tokens_used", 0),
        thinking=body.get("thinking"),
        what_doing=body.get("what_doing"),
        what_next=body.get("what_next"),
        friendly_dialogue=body.get("friendly_dialogue"),
    )
    return JSONResponse(content={"status": "OK", "event": event})


@app.post("/api/tasks")
async def post_task(body: Dict[str, Any]):
    """HTTP üzerinden görev durumu güncelleme."""
    task = await hub.update_task(
        task_id=body.get("task_id", "FEAT-01"),
        new_state=body.get("new_state", "BACKLOG"),
        title=body.get("title"),
        assignee=body.get("assignee"),
        priority=body.get("priority", "P1"),
        details=body.get("details")
    )
    return JSONResponse(content={"status": "OK", "task": task})


# ---------------------------------------------------------------------------
# Jira İş / Görev Yönetimi & 1-8 Toplu İcra Endpointleri
# ---------------------------------------------------------------------------
@app.get("/api/jira/issues")
async def get_jira_issues():
    """Mevcut projenin Jira görev listesini sıralı olarak döner."""
    return JSONResponse(content={
        "project_id": hub.active_project_id,
        "issues": hub.get_jira_issues()
    })


@app.post("/api/jira/issues")
async def create_or_update_jira_issue(body: Dict[str, Any]):
    """Yeni bir Jira görevi ekler veya mevcut olanı günceller."""
    issue_id = body.get("id")
    if issue_id and issue_id in hub.jira_issues:
        issue = await hub.update_jira_issue(issue_id, body)
    else:
        dup = hub.find_recent_duplicate(body)
        if dup is not None:
            return JSONResponse(content={"status": "OK", "issue": dup, "duplicate": True})       # çift tıklama: aynı iş ikinci kez açılmaz
        issue = await (hub.update_jira_issue(issue_id, body) if issue_id else hub.add_jira_issue(body))
    return JSONResponse(content={"status": "OK", "issue": issue})


def _jp_errors(fn):
    """G5 Jira+ uçları için ortak hata eşlemesi: KeyError → 404, ValueError → 400, PermissionError → 409."""
    @functools.wraps(fn)
    async def wrapper(*args, **kwargs):
        try:
            return await fn(*args, **kwargs)
        except KeyError as e:
            return JSONResponse(status_code=404, content={"error": tx("Bulunamadı: {key}", key=e.args[0] if e.args else '')})
        except ValueError as e:
            return JSONResponse(status_code=400, content={"error": str(e)})
        except PermissionError as e:
            return JSONResponse(status_code=409, content={"error": str(e)})
    return wrapper


@app.post("/api/jira/issues/{issue_id}/plan")
@_jp_errors
async def plan_jira_issue(issue_id: str, body: Dict[str, Any]):
    """Yönetici müdahalesi: görevi düzenle, bir sprinte sabitle (`planned_sprint`) ya da backlog sırasında taşı (`move`: up|down).
    Başlamış/bitmiş ya da kapanmış sprintte kalan işin sprinti ve sırası değişmez (409). Mantık: server/jira_plus.py (G5)."""
    from . import jira_plus as JP
    from . import sprint_flow as SPF
    body = body or {}
    expedite = await SPF.expedite_issue(hub, issue_id, body.get("expedite")) if "expedite" in body else None       # "Önce yap" / "sıradaki sprintin başı"
    issue = await JP.plan_issue(hub, issue_id, {k: v for k, v in body.items() if k != "expedite"})
    return JSONResponse(content={"status": "OK", "issue": issue, **({"expedite": expedite} if expedite is not None else {})})


# ---------------------------------------------------------------------------
# G5 Jira+: düzenleme, yumuşak silme, yorum, bağ, ek, Kanban taşıma, toplu işlem, sorgu, süzgeç, zaman çizelgesi, kanıt
# ---------------------------------------------------------------------------
@app.patch("/api/jira/issues/{issue_id}")
@_jp_errors
async def patch_jira_issue(issue_id: str, body: Dict[str, Any] = {}):
    from . import jira_plus as JP
    issue = await JP.edit_issue(hub, issue_id, body or {}, by=str((body or {}).get("by") or "MANAGER"))
    return JSONResponse(content={"status": "OK", "issue": issue})


@app.delete("/api/jira/issues/{issue_id}")
@_jp_errors
async def delete_jira_issue(issue_id: str, reason: Optional[str] = None):
    from . import jira_plus as JP
    issue = await JP.delete_issue(hub, issue_id, "MANAGER", reason or "")
    return JSONResponse(content={"status": "OK", "issue": issue})


@app.post("/api/jira/issues/{issue_id}/restore")
@_jp_errors
async def restore_jira_issue(issue_id: str):
    from . import jira_plus as JP
    return JSONResponse(content={"status": "OK", "issue": await JP.restore_issue(hub, issue_id)})


@app.post("/api/jira/issues/{issue_id}/correct-assignee")
@_jp_errors
async def correct_issue_assignee(issue_id: str):
    """Yanlışlıkla değişen sorumluyu denetim kaydındaki önceki değere döndürür (dondurulmuş maddede de; denetime işlenir)."""
    from . import jira_plus as JP
    return JSONResponse(content={"status": "OK", "issue": await JP.correct_assignee(hub, issue_id)})


@app.post("/api/jira/issues/{issue_id}/comments")
@_jp_errors
async def add_issue_comment(issue_id: str, body: Dict[str, Any] = {}):
    from . import jira_plus as JP
    c = await JP.add_comment(hub, issue_id, str((body or {}).get("text") or ""), author=str((body or {}).get("author") or "MANAGER"),
                             kind=str((body or {}).get("kind") or "manager"))
    return JSONResponse(content={"status": "OK", "comment": c, "issue": hub.jira_issues[issue_id]})


@app.delete("/api/jira/issues/{issue_id}/comments/{comment_id}")
@_jp_errors
async def delete_issue_comment(issue_id: str, comment_id: str):
    from . import jira_plus as JP
    await JP.delete_comment(hub, issue_id, comment_id)
    return JSONResponse(content={"status": "OK", "issue": hub.jira_issues[issue_id]})


@app.post("/api/jira/issues/{issue_id}/links")
@_jp_errors
async def add_issue_link(issue_id: str, body: Dict[str, Any] = {}):
    from . import jira_plus as JP
    link = await JP.add_link(hub, issue_id, str((body or {}).get("type") or ""), str((body or {}).get("target") or ""))
    return JSONResponse(content={"status": "OK", "link": link, "issue": hub.jira_issues[issue_id]})


@app.delete("/api/jira/issues/{issue_id}/links/{link_type}/{target}")
@_jp_errors
async def delete_issue_link(issue_id: str, link_type: str, target: str):
    from . import jira_plus as JP
    await JP.remove_link(hub, issue_id, link_type, target)
    return JSONResponse(content={"status": "OK", "issue": hub.jira_issues[issue_id]})


@app.post("/api/jira/issues/{issue_id}/attachments")
@_jp_errors
async def add_issue_attachment(issue_id: str, body: Dict[str, Any] = {}):
    from . import jira_plus as JP
    b = body or {}
    a = await JP.add_attachment(hub, issue_id, name=str(b.get("name") or ""), path=str(b.get("path") or ""), url=str(b.get("url") or ""))
    return JSONResponse(content={"status": "OK", "attachment": a, "issue": hub.jira_issues[issue_id]})


@app.delete("/api/jira/issues/{issue_id}/attachments/{attachment_id}")
@_jp_errors
async def delete_issue_attachment(issue_id: str, attachment_id: str):
    from . import jira_plus as JP
    await JP.remove_attachment(hub, issue_id, attachment_id)
    return JSONResponse(content={"status": "OK", "issue": hub.jira_issues[issue_id]})


@app.post("/api/jira/issues/{issue_id}/move")
@_jp_errors
async def move_jira_issue(issue_id: str, body: Dict[str, Any] = {}):
    """Kanban sürükle-bırak: hedef durum + sütun içi sıra (`index`)."""
    from . import jira_plus as JP
    b = body or {}
    idx = b.get("index")
    issue = await JP.move_issue(hub, issue_id, str(b.get("status") or ""), int(idx) if isinstance(idx, int) and not isinstance(idx, bool) else None)
    return JSONResponse(content={"status": "OK", "issue": issue})


@app.get("/api/jira/issues/{issue_id}/timeline")
@_jp_errors
async def jira_issue_timeline(issue_id: str):
    from . import jira_plus as JP
    return JSONResponse(content={"status": "OK", **JP.timeline(hub, issue_id)})


@app.get("/api/jira/issues/{issue_id}/evidence")
@_jp_errors
async def jira_issue_evidence(issue_id: str):
    from . import jira_plus as JP
    return JSONResponse(content={"status": "OK", **JP.evidence(hub, issue_id)})


@app.post("/api/jira/bulk")
@_jp_errors
async def jira_bulk(body: Dict[str, Any] = {}):
    from . import jira_plus as JP
    b = body or {}
    ids = b.get("ids") if isinstance(b.get("ids"), list) else []
    return JSONResponse(content={"status": "OK", **await JP.bulk(hub, ids, str(b.get("action") or ""), b.get("value"), str(b.get("by") or "MANAGER"))})


@app.get("/api/jira/query")
@_jp_errors
async def jira_query(q: str = "", include_deleted: bool = False):
    """JQL benzeri sorgu: `status in (BACKLOG, DONE) and assignee = QA and label = api order by priority desc`."""
    from . import jira_plus as JP
    issues = JP.query(hub, q, include_deleted=include_deleted)
    return JSONResponse(content={"status": "OK", "q": q, "count": len(issues), "issues": issues})


@app.get("/api/jira/filters")
async def jira_filters_list():
    from . import jira_plus as JP
    return JSONResponse(content={"status": "OK", "filters": JP.saved_filters(hub), "fields": sorted(JP.FIELDS)})


@app.post("/api/jira/filters")
@_jp_errors
async def jira_filters_save(body: Dict[str, Any] = {}):
    from . import jira_plus as JP
    f = await JP.save_filter(hub, str((body or {}).get("name") or ""), str((body or {}).get("q") or ""))
    return JSONResponse(content={"status": "OK", "filter": f, "filters": JP.saved_filters(hub)})


@app.delete("/api/jira/filters/{name}")
@_jp_errors
async def jira_filters_delete(name: str):
    from . import jira_plus as JP
    await JP.delete_filter(hub, name)
    return JSONResponse(content={"status": "OK", "filters": JP.saved_filters(hub)})


# ---------------------------------------------------------------------------
# LLM Model & Provider Ayarları (Gemini vs Claude)
# ---------------------------------------------------------------------------
@app.get("/api/settings/model")
async def get_model_settings(project_id: Optional[str] = None):
    """Aktif projenin veya belirtilen projenin LLM model ayarlarını döner."""
    cfg = hub.get_model_config(project_id)
    return JSONResponse(content={"status": "OK", "model_config": cfg})


@app.post("/api/settings/model")
async def update_model_settings(body: Dict[str, Any]):
    """LLM sağlayıcı ve modelini günceller, .fs-workspace'e kaydeder ve WebSocket ile duyurur."""
    project_id = body.get("project_id")
    updated = await hub.update_model_config(body, project_id)
    return JSONResponse(content={
        "status": "OK",
        "message": tx("Aktif model başarıyla güncellendi: {provider} / {model}", provider=updated.get('provider').upper(), model=updated.get('model_id')),
        "model_config": updated
    })


@app.post("/api/jira/execute-batch")
async def execute_jira_batch_endpoint(body: Dict[str, Any]):
    """Kullanıcının belirlediği görevleri (örn: 1..10 veya seçili maddeler) sırayla otonom icra eder."""
    selected_issues = body.get("selected_issues") or list(range(1, 11))
    prompt = body.get("prompt", tx("Kurumsal Çok Katmanlı Servis ve Modern Arayüz"))
    custom_dir = body.get("project_dir")
    step_by_step = body.get("step_by_step", True)

    existing = hub.active_run_for(hub.active_project_id)
    if hub.active_run_id or existing is not None:
        return JSONResponse(status_code=409, content={
            "error": tx("Zaten aktif bir pipeline koşusu var. Bitmesini bekleyin veya panoyu sıfırlayın."),
            "active_run_id": hub.active_run_id or (existing.run_id if existing else None)
        })

    if step_by_step:
        await hub.set_step_mode(True)
        hub.auto_proceed_all = False

    engine = str(body.get("engine") or "template").lower()
    try:
        result = await runs_api().start_run(
            project_id=hub.active_project_id,
            steps=selected_issues,
            engine=engine,
            custom_prompt=prompt,
            step_by_step=step_by_step,
            project_dir=custom_dir,
        )
    except RunsApiError as e:
        return JSONResponse(status_code=e.status_code, content=e.to_dict())

    run = result.get("run", {})
    return JSONResponse(content={
        "status": "STARTED",
        "message": tx("Seçilen {n} görev için otonom şirket döngüsü başlatıldı.", n=len(selected_issues)),
        "target_dir": run.get("project_dir"),
        "selected_issues": selected_issues,
        "step_by_step": step_by_step,
        "engine": run.get("engine", engine),
        "run_id": run.get("run_id"),
        "run": run,
    })


# ---------------------------------------------------------------------------
# Müşteri Görüşmeleri & Şartname/Dosya Kasası (Vault)
# ---------------------------------------------------------------------------
@app.get("/api/specs")
async def get_specs():
    """Kayıtlı müşteri görüşme notları ve yüklenen dosyaları listeler."""
    return JSONResponse(content={
        "project_id": hub.active_project_id,
        "specs": hub.uploaded_specs
    })


@app.post("/api/specs/upload")
async def upload_client_spec(
    title: str = Form("Müşteri Keşif ve Gereksinim Notu"),
    client_name: str = Form("Müşteri"),
    meeting_notes: str = Form(""),
    auto_generate_tasks: bool = Form(True),
    start_run: bool = Form(True),
    project_id: Optional[str] = Form(None),
    files: List[UploadFile] = File(default=[])
):
    """Müşteri toplantı notunu ve şartname/tasarım dosyalarını kalıcı olarak projeye ekler ve Jira görevlerini türetir."""
    target_project_id = safe_name(project_id or hub.active_project_id)
    project_uploads_dir = project_file_dir(target_project_id, UPLOADS_REL)
    if not project_uploads_dir:
        return JSONResponse(status_code=400, content={"error": tx("Geçersiz ya da kayıtsız proje kimliği.")})
    os.makedirs(project_uploads_dir, exist_ok=True)

    saved_files = []
    extracted_text_content = ""
    for file in files:
        if file.filename:
            filename = safe_name(file.filename)
            file_path = resolve_inside(project_uploads_dir, filename)
            if not file_path:
                return JSONResponse(status_code=400, content={"error": tx("Geçersiz dosya adı: {name}", name=file.filename)})
            content = await file.read()
            with open(file_path, "wb") as f:
                f.write(content)

            file_url = f"/api/projects/{target_project_id}/uploads/{filename}"
            saved_files.append({
                "filename": filename,
                "saved_path": file_path,
                "file_url": file_url,
                "size": len(content),
                "content_type": file.content_type
            })

            # Eğer dosya metin/markdown ise içeriğini otomatik oku
            if is_readable(file.filename):
                try:
                    decoded = read_text(content, file.filename).strip()
                    if decoded:
                        extracted_text_content += tx("\n\n---\n### Belge: {name}\n{decoded}", name=file.filename, decoded=decoded)
                        # Başlık jenerik ise ilk başlığı veya dosya adını al
                        if title in ["Müşteri Keşif ve Gereksinim Notu", "Ön plan toplantısı", "Müşteri"]:
                            for line in decoded.splitlines():
                                line_s = line.strip()
                                if line_s.startswith("#"):
                                    parsed_t = line_s.lstrip("#").strip()
                                    if parsed_t:
                                        title = parsed_t
                                        break
                            if title in ["Müşteri Keşif ve Gereksinim Notu", "Ön plan toplantısı", "Müşteri"]:
                                title = file.filename.rsplit(".", 1)[0].replace("-", " ").replace("_", " ")
                except Exception:
                    pass

    # Eğer formdan gelen not boşsa veya sadece dosya yüklendiyse, dosya içeriğini not olarak ata
    effective_notes = (meeting_notes.strip() + extracted_text_content).strip() if extracted_text_content else meeting_notes.strip()
    if not effective_notes and saved_files:
        effective_notes = tx("Yüklenen belgeler incelendi: {files}", files=', '.join(f['filename'] for f in saved_files))

    spec_data = {
        "title": title,
        "client_name": client_name,
        "meeting_notes": effective_notes,
        "files": saved_files
    }
    record = await hub.add_uploaded_spec(spec_data)

    # Sprint kipi (F3): yükleme değerlendirmeyi kendiliğinden kuyruğa alır ve koşuyu başlatır; sabit liste/düğme kullanılmaz.
    from . import sprint as SP
    if SP.enabled(hub):
        pending = await hub.queue_intake(record["id"])
        if not start_run:
            return JSONResponse(content={"status": "OK", "message": tx("Yükleme kasaya eklendi; değerlendirme kuyrukta."), "spec": record, "tasks": [],
                                         "intake": {"pending": pending, "run_status": "QUEUED_ONLY", "run_id": None}})
        started = await runs_api().start_sprint_run(project_id=target_project_id, client=None)
        return JSONResponse(content={
            "status": "OK", "message": tx("Yükleme kasaya eklendi; değerlendirme kuyruğa alındı."), "spec": record, "tasks": [],
            "intake": {"pending": pending, "run_status": started.get("status"), "run_id": (started.get("run") or {}).get("run_id")},
        })

    generated_tasks = []
    if auto_generate_tasks:
        generated_tasks = await hub.generate_jira_tasks_from_spec(spec_data)
        await hub.record_event(
            trace_id=f"spec-analysis-{int(datetime.now(timezone.utc).timestamp())}",
            from_agent="PM",
            to_agent="ARCHITECT",
            action="SPEC_ANALYZED_AND_TASKS_GENERATED",
            status="SUCCESS",
            payload={
                "spec_title": title,
                "client_name": client_name,
                "tasks_count": len(generated_tasks),
                "files_count": len(saved_files)
            },
            current_file=hub_docs_path(hub, "PRD.md"),
            tokens_used=240
        )
    else:
        # PM ajanının ilk görevine müşteri şartnamesini ekle
        await hub.update_jira_issue("JIRA-1", {
            "description": tx("Müşteri: {client}\nNotlar: {notes}...", client=client_name, notes=meeting_notes[:200]),
            "attachments": [f["filename"] for f in saved_files]
        })

    return JSONResponse(content={
        "status": "OK",
        "message": tx("Şartname ve dosyalar kasaya eklendi; Jira görevleri analiz edilip oluşturuldu.") if auto_generate_tasks else tx("Şartname ve dosyalar başarıyla kasaya eklendi."),
        "spec": record,
        "tasks": generated_tasks
    })


@app.post("/api/specs/analyze-and-generate-tasks")
async def analyze_spec_and_generate_tasks(body: Dict[str, Any] = {}):
    """
    Kayıtlı bir şartnameyi analiz ederek Jira tahtasındaki görevleri (1-8)
    müşterinin gereksinimlerine göre baştan üretir ve tahtaya yansıtır.
    """
    spec_id = body.get("spec_id")
    target_spec = None
    if spec_id:
        target_spec = next((s for s in hub.uploaded_specs if s["id"] == spec_id), None)
    if not target_spec and hub.uploaded_specs:
        target_spec = hub.uploaded_specs[-1]

    if not target_spec:
        target_spec = {
            "title": body.get("title", "Müşteri Keşif ve İhtiyaç Analizi"),
            "client_name": body.get("client_name", "Müşteri"),
            "meeting_notes": body.get("meeting_notes", body.get("prompt", "Kurumsal Çok Katmanlı Servis")),
            "files": []
        }

    tasks = await hub.generate_jira_tasks_from_spec(target_spec)

    await hub.record_event(
        trace_id=f"spec-analysis-{int(datetime.now(timezone.utc).timestamp())}",
        from_agent="PM",
        to_agent="ARCHITECT",
        action="SPEC_ANALYZED_AND_TASKS_GENERATED",
        status="SUCCESS",
        payload={
            "spec_title": target_spec.get("title"),
            "client_name": target_spec.get("client_name"),
            "tasks_count": len(tasks)
        },
        current_file=hub_docs_path(hub, "PRD.md"),
        tokens_used=240
    )

    return JSONResponse(content={
        "status": "OK",
        "message": tx("'{title}' analiz edildi ve {n} adet Jira görevi oluşturuldu.", title=target_spec.get('title'), n=len(tasks)),
        "tasks": tasks
    })


@app.delete("/api/specs/{spec_id}")
async def delete_spec_endpoint(spec_id: str):
    """Kayıtlı şartnameyi ve dosyalarını kasadan siler."""
    success = await hub.delete_uploaded_spec(spec_id)
    if success:
        return JSONResponse(content={"status": "DELETED", "spec_id": spec_id})
    return JSONResponse(status_code=404, content={"error": tx("Şartname bulunamadı.")})


@app.delete("/api/specs/{spec_id}/files/{filename}")
async def delete_spec_file_endpoint(spec_id: str, filename: str):
    """Şartnameye bağlı belirli bir dosyayı siler."""
    success = await hub.delete_spec_file(spec_id, filename)
    if success:
        return JSONResponse(content={"status": "FILE_DELETED", "filename": filename})
    return JSONResponse(status_code=404, content={"error": tx("Dosya bulunamadı.")})


@app.put("/api/specs/{spec_id}")
async def update_spec_endpoint(spec_id: str, body: Dict[str, Any]):
    """Şartname başlığını ve görüşme notlarını günceller."""
    spec = await hub.update_uploaded_spec(spec_id, body)
    if spec:
        return JSONResponse(content={"status": "UPDATED", "spec": spec})
    return JSONResponse(status_code=404, content={"error": tx("Şartname bulunamadı.")})


# ---------------------------------------------------------------------------
# Playwright E2E Tarayıcı Test Raporları
# ---------------------------------------------------------------------------
@app.get("/api/tester/reports")
async def get_tester_reports():
    """Geçmiş Playwright E2E test koşularını ve ekran görüntülerini döner."""
    return JSONResponse(content={
        "project_id": hub.active_project_id,
        "reports": hub.playwright_reports
    })


@app.get("/api/tester/profiles")
async def get_tester_profiles():
    """Kayıtlı ve hazır test kullanıcı şablonlarını döner."""
    return JSONResponse(content={
        "project_id": hub.active_project_id,
        "profiles": hub.public_profiles()
    })


@app.post("/api/tester/profiles")
async def save_tester_profile(body: Dict[str, Any]):
    """Yeni bir test kullanıcısı/şablonu ekler veya mevcut olanı günceller."""
    profile = await hub.add_or_update_test_profile(body)
    return JSONResponse(content={"status": "OK", "profile": {k: v for k, v in profile.items() if k != "password"}})


@app.delete("/api/tester/profiles/{profile_id}")
async def delete_tester_profile(profile_id: str):
    """Test kullanıcısı şablonunu siler."""
    success = await hub.delete_test_profile(profile_id)
    if success:
        return JSONResponse(content={"status": "DELETED", "profile_id": profile_id})
    return JSONResponse(status_code=404, content={"error": tx("Test profili bulunamadı.")})


@app.post("/api/tester/run-playwright")
async def run_playwright_test_endpoint(body: Dict[str, Any] = {}):
    """Canlı web uygulaması üzerinde Playwright ile test açar ve ekran görüntülerini yakalar."""
    target_url = body.get("target_url", "http://127.0.0.1:8099")
    scenario = body.get("scenario", "Kullanıcı Giriş & Arayüz Doğrulama")
    credentials = hub.resolve_credentials(body.get("credentials"), body.get("profile_id"))

    result = await run_playwright_e2e_tests(
        target_url=target_url,
        test_scenario=scenario,
        credentials=credentials,
        project_dir=project_path_for(None), project_id=hub.active_project_id,
    )
    saved_report = await hub.add_playwright_report(result)

    # Telemetriye de yansıt
    await hub.record_event(
        trace_id=f"e2e-{int(asyncio.get_event_loop().time())}",
        from_agent="E2E_TESTER",
        to_agent="ARCHITECT",
        action="E2E_BROWSER_RUN_COMPLETED",
        status="SUCCESS" if result.get("status") == "PASSED" else "FAILED",   # sonuç uydurulmaz: olay durumu gerçek test sonucudur
        payload={
            "report_id": saved_report["id"],
            "screenshots": result.get("screenshots", []),
            "status": result.get("status", "PASSED"),
            "target_url": target_url,
            "test_user": result.get("test_user"),
            "role": result.get("role")
        },
        current_file=".fs-workspace/e2e/screenshots",
        tokens_used=280
    )

    return JSONResponse(content={
        "status": "OK",
        "report": saved_report
    })


@app.post("/api/tester/run-qa-suite")
async def run_qa_suite_endpoint(body: Dict[str, Any] = {}):
    """Geliştirme ajanlarını çalıştırmadan SADECE test süitini (QA Lead + Playwright E2E) koşturur."""
    active_proj = hub.projects.get(hub.active_project_id, {})
    custom_dir = body.get("project_dir")
    target_dir = os.path.abspath(custom_dir) if custom_dir else active_proj.get("path", hub.default_project_path)
    target_url = body.get("target_url", "http://127.0.0.1:8099")
    credentials = hub.resolve_credentials(body.get("credentials"), body.get("profile_id"))
    scenario = body.get("scenario", "Bağımsız QA & Playwright Tarayıcı Doğrulama Süiti")

    # Arka planda test pipeline'ını başlat
    asyncio.create_task(execute_tests_only_pipeline(
        project_dir=target_dir,
        target_url=target_url,
        credentials=credentials,
        scenario=scenario,
        hub=hub
    ))

    return JSONResponse(content={
        "status": "STARTED",
        "message": tx("Bağımsız QA ve Playwright E2E test süiti başlatıldı."),
        "project_dir": target_dir,
        "target_url": target_url,
        "test_user": credentials.get("username") if credentials else "Standart"
    })


# ---------------------------------------------------------------------------
# Dinamik Proje Klasörü & Çoklu Proje Yönetim Endpointleri
# ---------------------------------------------------------------------------
@app.get("/api/projects")
async def get_projects_list():
    """Bağlı tüm projelerin özet listesini döner."""
    return JSONResponse(content={
        "active_project_id": hub.active_project_id,
        "projects": hub.get_projects_summary()
    })


@app.get("/api/fs/browse")
async def browse_folders(path: str = "", show_hidden: int = 0):
    """Dashboard 'Gözat': yerel klasörleri listeler (yalnızca dizin adları; proje bağlamak için)."""
    from .fs_browse import BrowseError, browse
    try:
        return JSONResponse(content=browse(path, show_hidden=bool(show_hidden)))
    except BrowseError as e:
        return JSONResponse(status_code=e.status_code, content={"error": str(e)})


@app.post("/api/projects/add")
async def add_project(body: Dict[str, Any]):
    """Yeni bir proje klasörünü sisteme tanıtır."""
    path = body.get("path")
    name = body.get("name")
    if not path:
        return JSONResponse(status_code=400, content={"error": tx("Klasör yolu zorunludur.")})
    # Yeni (boş) klasör apps/devops/docs düzeniyle başlar; ürün dosyası ya da FS-SC durumu olan klasör düz kalır (göçle geçilir).
    # Klasör kayıttan ÖNCE incelenir: kayıt `.fs-workspace` açar ve boş klasör de "dolu" görünürdü.
    from . import layout as LAY
    default_before = LAY.default_layout_for(os.path.abspath(str(path).strip().replace("\\", "/")))
    legacy_folder = os.path.isdir(os.path.join(os.path.abspath(str(path).strip()), ".fs-workspace"))     # önceden FS-SC projesi olan klasörün dili değişmez
    from . import i18n as _i18n
    asked_lang = str(body.get("project_language") or "").strip().lower()
    proj = hub.register_project(path, name, lang=asked_lang if asked_lang in ("tr", "en") else ("tr" if legacy_folder else "en"))     # ilk görev listesi proje dilinde kurulur
    pid = proj["id"]
    saved_lang = ((hub.projects.get(pid) or {}).get("settings") or {}).get("project_language")
    # Yeni proje varsayılanı İngilizce; formda seçilirse o. Daha önce FS-SC'ye bağlı klasör mevcut dilini korur (yoksa Türkçe).
    project_lang = _i18n.normalize(saved_lang) if saved_lang else (_i18n.normalize(asked_lang) if asked_lang in ("tr", "en") else ("tr" if legacy_folder else "en"))
    if not saved_lang and (asked_lang in ("tr", "en") or not legacy_folder):
        if pid == hub.active_project_id:
            await hub.update_settings({"project_language": project_lang})
        else:
            hub.projects[pid].setdefault("settings", {})["project_language"] = project_lang
            hub.mark_dirty()
    # Claude bu klasörden açılıp pipeline'ı çalıştırabilsin: her bağlanışta .mcp.json + CLAUDE.md bloğu yeniden yazılır (yol taşınmasına dayanıklı).
    from .project_bootstrap import bootstrap_project
    try:
        with _i18n.use_lang(project_lang):
            claude_files = bootstrap_project(proj["path"], pid)["changed"]
    except OSError as e:
        claude_files = []
        __import__("logging").getLogger(__name__).warning("Claude bootstrap yazılamadı: %s", e)
    proj_settings = (hub.projects.get(pid) or {}).get("settings") or {}
    layout_note = ""
    if "project_layout" not in proj_settings:
        default = default_before
        # Kullanıcı formda seçtiyse (`layout_mode`: "apps" önerilen | "flat") seçim geçerlidir; yalnızca içinde ürün dosyası olan klasörde
        # apps seçimi dayatılmaz (mevcut dosyalar taşınmadan ajanlar apps/ altına yazarsa kod ikiye bölünür): düz kalır, göç önerilir.
        chosen = (body.get("layout_mode") or "").strip().lower()
        if chosen == "flat":
            default = LAY.flat_layout()
        elif chosen == "apps":
            if LAY.is_apps(default):
                pass
            else:
                layout_note = tx("Klasörde mevcut ürün dosyaları var; apps/devops/docs düzeni dayatılmadı (düz kaldı). "
                                  "Düzene geçmek için projenin klasör düzeni ayarından göç planını çalıştırın.")
        if pid == hub.active_project_id:
            await hub.update_settings({"project_layout": default})
        else:
            hub.projects[pid].setdefault("settings", {})["project_layout"] = default
            hub.mark_dirty()
    return JSONResponse(content={"status": "OK", "project": hub.project_summary(proj["id"]),
                                 "layout": LAY.layout_of((hub.projects.get(pid) or {}).get("settings") or {}), "layout_note": layout_note,
                                 "claude_files": claude_files})


@app.post("/api/projects/switch")
async def switch_project(body: Dict[str, Any]):
    """Aktif projeyi değiştirir ve panoyu o projenin verilerine geçirir."""
    target = body.get("project_id") or body.get("path")
    if not target:
        return JSONResponse(status_code=400, content={"error": tx("project_id veya path gereklidir.")})
    proj = await hub.switch_project(target)
    # Tam durum PROJECT_SWITCHED WebSocket mesajıyla tek kaynaktan uygulanır
    return JSONResponse(content={
        "status": "OK",
        "active_project": {"id": proj.get("id"), "name": proj.get("name"), "path": proj.get("path")}
    })


@app.post("/api/projects/{project_id}/message")
async def post_cross_project_message(project_id: str, body: Dict[str, Any]):
    """Projeler arası ekip mesajı (Web ↔ Mobil gibi)."""
    try:
        event = await hub.send_cross_project_message(
            project_id, body.get("from_agent", "PM"), body.get("to_agent", "PM"), body.get("message", ""), body.get("from_project")
        )
    except ValueError as e:
        return JSONResponse(status_code=404, content={"error": str(e), "known_projects": list(hub.projects.keys())})
    return JSONResponse(content={"status": "OK", "event": event})


@app.post("/api/projects/{project_id}/migrate-docs")
async def migrate_project_docs(project_id: str, body: Dict[str, Any] = {}):
    """Belge klasörü göçü (eski docs → FS-docs). Varsayılan kuru önizleme; `{"apply": true}` ile uygular (yalnızca FS-SC'nin bilinen dosyaları)."""
    from .migrate_docs import migrate_docs
    path = project_path_for(project_id) if project_id in hub.projects else None
    if not path or not os.path.isdir(path):
        return JSONResponse(status_code=404, content={"error": tx("Proje ya da proje klasörü bulunamadı.")})
    apply = bool((body or {}).get("apply"))
    result = await asyncio.to_thread(migrate_docs, path, apply)
    if apply:
        if project_id == hub.active_project_id:
            await hub.update_settings({"docs_root": result["target"]})
        else:
            proj_settings = hub.projects[project_id].setdefault("settings", {})
            proj_settings["docs_root"] = result["target"]
            hub.mark_dirty()
    return JSONResponse(content={"project_id": project_id, **result})


@app.get("/api/projects/{project_id}/layout")
async def get_project_layout(project_id: str):
    """Projenin klasör düzeni (apps/devops/docs ya da düz), kökteki girdilerin düzene uyumu ve (düz düzende) taşıma önizlemesi."""
    from . import layout as LAY
    proj = hub.projects.get(project_id)
    if not proj:
        return JSONResponse(status_code=404, content={"error": tx("Proje bulunamadı.")})
    settings = hub.get_settings() if project_id == hub.active_project_id else (proj.get("settings") or {})
    lay = LAY.layout_of(settings)
    info = await asyncio.to_thread(LAY.describe, lay, proj.get("path") or "")
    return JSONResponse(content={"project_id": project_id, "default": LAY.sanitize_layout({}), **info})


@app.post("/api/projects/{project_id}/layout")
async def set_project_layout(project_id: str, body: Dict[str, Any]):
    """Klasör düzenini ayarlar (mode apps|flat, apps_dir, devops_dir, docs_dir, roles, enforce). Mevcut dosyalar taşınmaz; taşıma için migrate-layout."""
    from . import layout as LAY
    if project_id != hub.active_project_id:
        return JSONResponse(status_code=409, content={"error": tx("Düzen yalnızca etkin proje için ayarlanır; önce projeyi seçin.")})
    raw = body.get("layout") if isinstance(body.get("layout"), dict) else body
    merged = await hub.update_settings({"project_layout": raw if isinstance(raw, dict) else {}})
    return JSONResponse(content={"status": "OK", "layout": LAY.layout_of(merged)})


@app.post("/api/projects/{project_id}/migrate-layout")
async def migrate_project_layout(project_id: str, body: Dict[str, Any] = {}):
    """Düz düzendeki projeyi apps/devops/docs düzenine taşır. Varsayılan kuru plan; `{"apply": true}` ile uygular (süren adım yokken)."""
    from .migrate_layout import MigrationError, migrate_layout
    try:
        result = await migrate_layout(hub, project_id, apply=bool((body or {}).get("apply")), layout_override=(body or {}).get("layout"))
    except MigrationError as e:
        return JSONResponse(status_code=e.status_code, content=e.to_dict())
    return JSONResponse(content=result)


@app.post("/api/project/relocate-docker")
async def relocate_active_project_docker(body: Dict[str, Any] = {}):
    """Etkin proje için `relocate-docker` (panodaki dosya gezgini bunu kullanır)."""
    return await relocate_project_docker(hub.active_project_id, body)


@app.post("/api/projects/{project_id}/relocate-docker")
async def relocate_project_docker(project_id: str, body: Dict[str, Any] = {}):
    """Kökte/uygulama klasöründe kalmış Docker dosyalarını `devops/` altına taşır (kalıcı kural). Varsayılan kuru plan; `{"apply": true}` uygular (süren adım yokken).
    Çevrilemeyen başvurular (spec/belge) için DEVOPS'a otomatik bir düzeltme işi açılır."""
    from . import docker_relocate as DR
    from . import layout as LAY
    from . import sprint_flow as SPF
    if project_id != hub.active_project_id:
        return JSONResponse(status_code=409, content={"error": tx("Yalnızca etkin proje için çalışır; önce projeyi seçin.")})
    project_dir = (hub.projects.get(project_id) or {}).get("path") or hub.default_project_path
    layout = LAY.layout_of(hub)
    if not bool((body or {}).get("apply")):
        return JSONResponse(content={"status": "PLAN", "applied": False, **DR.plan(project_dir, layout)})
    run = hub.active_run_for(project_id)
    if run is not None and run.current_step is not None and run.current_step.status == "ACTIVE":
        return JSONResponse(status_code=409, content={"error": tx("Süren adım var (#{order}); adım bitince ya da koşu duraklayınca tekrar deneyin.", order=run.current_step.order)})
    res = await asyncio.to_thread(DR.apply, project_dir, layout)
    task = None
    if res["remaining_refs"]:
        files = ", ".join(res["remaining_refs"][:6])
        task = await SPF.create_manager_task(hub, tx("Docker dosyaları devops/ altına taşındı ({moved}). Eski yollara başvuran dosyaları yeni yollara göre güncelle: {files}.", moved=', '.join(m['to'] for m in res['moved'])[:160], files=files), None, urgent=False)
    return JSONResponse(content={"status": "APPLIED", "applied": True, "followup_task": task, **res})


@app.delete("/api/projects/{project_id}")
async def delete_project(project_id: str):
    """Projeyi listeden kaldırır."""
    if project_id in hub.projects:
        del hub.projects[project_id]
        if hub.active_project_id == project_id and hub.projects:
            hub.active_project_id = list(hub.projects.keys())[0]
        hub.save_registry()
        return JSONResponse(content={"status": "DELETED", "project_id": project_id})
    return JSONResponse(status_code=404, content={"error": tx("Proje bulunamadı.")})


@app.post("/api/projects/{project_id}/purge")
async def purge_project_endpoint(project_id: str, body: Dict[str, Any]):
    """Projeyi kaldırır ve verilerini siler. `{"scope": "data"|"folder", "confirm_name": "<proje adı>"}`; ikinci onay adı yazmaktır."""
    from .purge import PurgeError, purge_project
    try:
        return JSONResponse(content=await purge_project(hub, project_id, body.get("scope", ""), body.get("confirm_name", "")))
    except PurgeError as e:
        return JSONResponse(status_code=e.status_code, content={"error": str(e)})


@app.get("/api/agents")
async def get_agents():
    """Mevcut kayıtlı tüm ajanları döner (kapsam: core | project | global; G6)."""
    from . import agent_registry as AR
    return JSONResponse(content={
        "project_id": hub.active_project_id,
        "agents": [AR.with_scope(a) for a in hub.agents.values()],
        "global_ids": sorted(AR.load_global()),
        "base_roles": list(AR.BASE_ROLES),
        "work_types": list(AR.ALL_CAPABILITIES),
    })


def _agent_error(e: Exception) -> JSONResponse:
    return JSONResponse(status_code=400, content={"error": str(e)})


@app.get("/api/agents/{agent_id}/timeline")
async def get_agent_timeline(
    agent_id: str,
    project_id: Optional[str] = None,
    since: Optional[str] = None,
    until: Optional[str] = None,
    limit: int = 500,
):
    """Ajanın zaman çizelgesi: olaylar (JSONL + bellek), denetim notları, müzakere konuşmaları, etkileşim özeti."""
    from .event_store import query_events, summarize_interactions

    aid = agent_id.upper()
    pid = project_id or hub.active_project_id
    proj = hub.projects.get(pid, {})
    proj_path = proj.get("path", "")
    fallback = list(hub.events) if pid == hub.active_project_id else proj.get("events", [])
    events = await asyncio.to_thread(query_events, proj_path, aid, since, until, limit, fallback)

    issues = hub.jira_issues.values() if pid == hub.active_project_id else (proj.get("jira_issues") or {}).values()
    audits: List[Dict[str, Any]] = []
    for issue in issues:
        for a in issue.get("audit_trail", []) or []:
            if str(a.get("agent_id", "")).upper() == aid:
                audits.append({**a, "issue_id": issue.get("id"), "issue_title": issue.get("title")})
    audits.sort(key=lambda a: a.get("timestamp", ""), reverse=True)

    deliberation = [e for e in events if e.get("action") == "DELIBERATION_SPEECH"]
    runs = [r.to_dict() for r in hub.runs.values() if r.project_id == pid and any(s.role.upper() == aid for s in r.steps)]
    runs.sort(key=lambda r: r["created_at"], reverse=True)

    return JSONResponse(content={
        "agent_id": aid,
        "agent": hub.agents.get(aid) if pid == hub.active_project_id else (proj.get("agents") or {}).get(aid),
        "project_id": pid,
        "events": events,
        "audits": audits[:200],
        "deliberation": deliberation,
        "interactions": summarize_interactions(aid, events),
        "runs": runs[:20],
        "total_events": len(events),
    })


@app.post("/api/agents/add")
async def add_custom_agent(body: Dict[str, Any]):
    """Kullanıcının arayüzden yeni bir kıdemli geliştirici eklemesini sağlar (G6: temel rol, yetenekler, profil, `scope: global`)."""
    from . import agent_registry as AR
    try:
        agent = await hub.register_custom_agent(body)
    except AR.AgentError as e:
        return _agent_error(e)
    return JSONResponse(content={"status": "OK", "agent": AR.with_scope(agent)})


@app.put("/api/agents/{agent_id}")
async def update_agent_endpoint(agent_id: str, body: Dict[str, Any]):
    """Mevcut bir ajanın (örn: E2E_TESTER, QA) bilgilerini günceller. Global ajanda değişiklik bu projeye özgü fark olur (`overrides`)."""
    from . import agent_registry as AR
    try:
        agent = await hub.update_agent(agent_id, body)
    except AR.AgentError as e:
        return _agent_error(e)
    return JSONResponse(content={"status": "OK", "agent": AR.with_scope(agent)})


@app.delete("/api/agents/{agent_id}")
async def delete_agent_endpoint(agent_id: str):
    """Özel ajanı siler veya core ajanı varsayılana döndürür."""
    success = await hub.delete_agent(agent_id)
    if success:
        return JSONResponse(content={"status": "DELETED", "agent_id": agent_id})
    return JSONResponse(status_code=404, content={"error": tx("Ajan bulunamadı.")})


# ---------------------------------------------------------------------------
# G6: şirket geneli ajanlar, sağlık, dışa/içe aktarma, şablon kütüphanesi
# ---------------------------------------------------------------------------
async def _broadcast_agents() -> None:
    """Pano `AGENT_UPDATED` olayında `agents` listesini olduğu gibi yükler (toplu değişikliklerde de aynı olay)."""
    from . import agent_registry as AR
    await hub.broadcast({"type": "AGENT_UPDATED", "agents": [AR.with_scope(a) for a in hub.agents.values()]})
    hub.save_registry()


@app.get("/api/agents/global")
async def list_global_agents():
    """Şirket geneli ajan tanımları (agents/registry.json) ve hangi projelerde etkin oldukları."""
    from . import agent_registry as AR
    glob = AR.load_global()
    holders: Dict[str, List[str]] = {aid: [] for aid in glob}
    for pid, proj in hub.projects.items():
        agents = hub.agents if pid == hub.active_project_id else (proj.get("agents") or {})
        for aid in glob:
            if aid in agents and not (agents[aid] or {}).get("overrides", {}).get("active") is False:
                holders[aid].append(pid)
    return JSONResponse(content={"agents": [{**d, "projects": holders.get(aid, []), "in_project": aid in hub.agents} for aid, d in glob.items()]})


@app.post("/api/agents/pool/{agent_id}/add")
async def add_pool_agent(agent_id: str, body: Dict[str, Any] = None):
    """Ajan havuzundan projeye ekler: {mode: 'linked' | 'copy', id?: yeni kimlik (yalnızca copy)}."""
    from . import agent_registry as AR
    b = body or {}
    try:
        rec = await hub.add_pool_agent(agent_id, "copy" if str(b.get("mode")) == "copy" else "linked", str(b.get("id") or ""))
    except AR.AgentError as e:
        return _agent_error(e)
    await _broadcast_agents()
    return JSONResponse(content={"status": "OK", "agent": AR.with_scope(rec)})


@app.post("/api/agents/global")
async def upsert_global_agent(body: Dict[str, Any]):
    """Şirket geneli ajan tanımını oluşturur / günceller; aktif projeye de yansır (diğer projeler yüklenince eşitlenir)."""
    from . import agent_registry as AR
    try:
        aid = AR.clean_id((body or {}).get("id") or (body or {}).get("name"))
        data = {**(body or {})}
        if not str(data.get("role_base") or "").strip():
            guess = AR.clean_id(data.get("role"))
            data["role_base"] = guess if guess in AR.BASE_ROLES else "BACKEND_DEV"
        AR.upsert_global(aid, {**data, "name": str(data.get("name") or aid)})
    except AR.AgentError as e:
        return _agent_error(e)
    hub._sync_global_agents()
    await _broadcast_agents()
    return JSONResponse(content={"status": "OK", "agent": AR.with_scope(hub.agents[aid]) if aid in hub.agents else None, "global_ids": sorted(AR.load_global())})


@app.delete("/api/agents/global/{agent_id}")
async def delete_global_agent(agent_id: str):
    """Şirket geneli tanımı siler; projelerdeki kopyalar proje sahipliğine geçer (kayıp olmaz)."""
    from . import agent_registry as AR
    if not AR.delete_global(agent_id):
        return JSONResponse(status_code=404, content={"error": tx("Şirket geneli ajan bulunamadı.")})
    hub._sync_global_agents()
    await _broadcast_agents()
    return JSONResponse(content={"status": "DELETED", "agent_id": AR.clean_id(agent_id)})


@app.post("/api/agents/{agent_id}/promote-definition")
async def promote_agent_definition(agent_id: str):
    """Projedeki özel ajanın TANIMINI (yetenek, profil, ek yönerge) şirket geneline terfi ettirir; istem terfisi ayrı uçtur (promote-to-global)."""
    from . import agent_registry as AR
    aid = AR.clean_id(agent_id)
    agent = hub.agents.get(aid)
    if agent is None:
        return JSONResponse(status_code=404, content={"error": tx("Ajan bulunamadı.")})
    if aid in AR.CORE_IDS:
        return JSONResponse(status_code=400, content={"error": tx("'{aid}' çekirdek bir roldür; şirket geneli ajan olarak tanımlanamaz.", aid=aid)})
    try:
        hub._apply_agent_definition(agent, {"scope": "global"})
    except AR.AgentError as e:
        return _agent_error(e)
    await _broadcast_agents()
    return JSONResponse(content={"status": "OK", "agent": AR.with_scope(agent)})


@app.get("/api/agents/{agent_id}/health")
async def agent_health(agent_id: str):
    """Ajan sağlığı: teslim, ilk seferde geçme oranı, düzeltme turu, token ve istem sürümleri (geri alma için `/restore`)."""
    from . import agent_registry as AR
    aid = AR.clean_id(agent_id)
    if aid not in hub.agents:
        return JSONResponse(status_code=404, content={"error": tx("Ajan bulunamadı.")})
    try:
        versions = hub.get_agent_prompt_details(aid).get("versions") or []
    except Exception:
        versions = []
    return JSONResponse(content={"status": "OK", "health": AR.health(hub, aid, versions)})


@app.get("/api/agents/{agent_id}/export")
async def export_agent(agent_id: str):
    """Ajan paketi: tanım + güncel istem (Markdown). Başka projede ya da başka kurulumda içe aktarılabilir."""
    from . import agent_registry as AR
    aid = AR.clean_id(agent_id)
    agent = hub.agents.get(aid)
    if agent is None:
        return JSONResponse(status_code=404, content={"error": tx("Ajan bulunamadı.")})
    try:
        prompt = hub.get_agent_prompt_details(aid).get("active_content") or ""
    except Exception:
        prompt = ""
    return JSONResponse(content={"status": "OK", "package": AR.export_package(agent, prompt)})


@app.post("/api/agents/import")
async def import_agent(body: Dict[str, Any]):
    """Ajan paketini içe aktarır (`scope`: project | global). Aynı kimlik varsa `replace: true` gerekir."""
    from . import agent_registry as AR
    try:
        parsed = AR.parse_package((body or {}).get("package"))
        aid = parsed["id"]
        if aid in hub.agents and not (body or {}).get("replace"):
            return JSONResponse(status_code=409, content={"error": tx("'{aid}' zaten var; üzerine yazmak için replace=true gönderin.", aid=aid)})
        scope = "global" if str((body or {}).get("scope") or "").lower() == "global" else "project"
        agent = await hub.register_custom_agent({**parsed["definition"], "id": aid, "scope": scope})
    except AR.AgentError as e:
        return _agent_error(e)
    if parsed["prompt_md"].strip():
        try:
            hub.save_agent_prompt_content(agent_id=aid, content=parsed["prompt_md"], commit_message=tx("Ajan paketinden içe aktarıldı"), author="Import")
        except Exception:
            pass
    return JSONResponse(content={"status": "OK", "agent": AR.with_scope(hub.agents.get(aid, agent))})


@app.get("/api/agent-templates")
async def list_agent_templates():
    """Hazır ajan takımları (şablon kütüphanesi): agents/templates/*.json."""
    from . import agent_registry as AR
    return JSONResponse(content={"templates": AR.list_templates()})


@app.post("/api/agent-templates/{key}/apply")
async def apply_agent_template(key: str, body: Dict[str, Any] = {}):
    """Şablondaki ajanları projeye (ya da `scope: global` ile şirket geneline) ekler; var olanlara dokunmaz."""
    from . import agent_registry as AR
    try:
        defs = AR.template_definitions(key)
    except AR.AgentError as e:
        return JSONResponse(status_code=404, content={"error": str(e)})
    scope = "global" if str((body or {}).get("scope") or "").lower() == "global" else "project"
    added: List[str] = []
    skipped: List[str] = []
    for d in defs:
        if d["id"] in hub.agents:
            skipped.append(d["id"])
            continue
        await hub.register_custom_agent({**d, "scope": scope})
        added.append(d["id"])
    return JSONResponse(content={"status": "OK", "added": added, "skipped": skipped, "agents": [AR.with_scope(a) for a in hub.agents.values()]})


# ---------------------------------------------------------------------------
# G7: test ekibi — test case'leri, test run'lar, izlenebilirlik matrisi, plan, E2E senaryo editörü
# ---------------------------------------------------------------------------
def _testing_error(e: Exception) -> JSONResponse:
    if isinstance(e, KeyError):
        return JSONResponse(status_code=404, content={"error": tx("Bulunamadı: {key}", key=e.args[0] if e.args else '')})
    return JSONResponse(status_code=400, content={"error": str(e)})


def _active_project_dir() -> str:
    """Test belgelerinin ve E2E senaryolarının yazıldığı klasör: son koşunun klasörü (kuru koşuda hedef klasör), yoksa etkin proje."""
    from . import testing as TST
    return TST._project_dir(hub)


@app.get("/api/testing/cases")
async def testing_cases(ac: Optional[str] = None, story: Optional[str] = None, status: Optional[str] = None, type: Optional[str] = None,
                        label: Optional[str] = None, result: Optional[str] = None, q: Optional[str] = None):
    """Test case listesi (süzgeçler: kabul kriteri, hikâye, durum, tür, etiket, son sonuç, metin) + özet."""
    from . import testing as TST
    out = []
    for c in sorted(TST.store(hub)["cases"].values(), key=lambda c: TST._num(c["id"])):
        if ac and ac.upper() not in c["ac_refs"]:
            continue
        if story and c.get("story_ref") != story:
            continue
        if status and c["status"] != status.upper():
            continue
        if type and c["type"] != type.lower():
            continue
        if label and label.lower() not in c["labels"]:
            continue
        if result and ((c.get("last_result") or {}).get("result") or "NONE") != result.upper():
            continue
        if q and q.lower() not in (c["title"] + " " + c["id"]).lower():
            continue
        out.append(c)
    return JSONResponse(content={"cases": out, "summary": TST.summary(hub)})


@app.post("/api/testing/cases")
async def testing_create_case(body: Dict[str, Any]):
    """Elle test case ekler (QA'nın TEST_DESIGN çıktısıyla aynı model; varsayılan durum DRAFT)."""
    from . import testing as TST
    try:
        case = await TST.create_case(hub, body or {}, sprint=(_current_sprint()), by="manager", default_status="DRAFT")
    except TST.CaseError as e:
        return _testing_error(e)
    await TST._announce(hub)
    return JSONResponse(content={"status": "OK", "case": case})


def _current_sprint() -> Optional[int]:
    from . import sprint as SP
    return SP.ensure_state(hub).get("current_sprint")


@app.get("/api/testing/cases/{case_id}")
async def testing_case(case_id: str):
    from . import testing as TST
    case = TST.store(hub)["cases"].get(case_id.upper())
    if case is None:
        return JSONResponse(status_code=404, content={"error": tx("Test case bulunamadı.")})
    return JSONResponse(content={"case": case})


@app.patch("/api/testing/cases/{case_id}")
async def testing_update_case(case_id: str, body: Dict[str, Any]):
    """Case'i düzenler (başlık, adımlar, beklenen sonuç, otomasyon, durum, etiket, karantina)."""
    from . import testing as TST
    try:
        case = await TST.update_case(hub, case_id, body or {})
    except (TST.CaseError, KeyError) as e:
        return _testing_error(e)
    return JSONResponse(content={"status": "OK", "case": case})


@app.post("/api/testing/cases/{case_id}/result")
async def testing_manual_result(case_id: str, body: Dict[str, Any]):
    """Elle yürütülen case'in sonucunu girer (PASS | FAIL | BLOCKED); FAIL otomatik BUG açar."""
    from . import testing as TST
    try:
        run = await TST.set_manual_result(hub, case_id, (body or {}).get("result"), (body or {}).get("note", ""), by=str((body or {}).get("by") or "manager"))
    except (TST.CaseError, KeyError) as e:
        return _testing_error(e)
    return JSONResponse(content={"status": "OK", "run": run})


@app.get("/api/testing/runs")
async def testing_runs(limit: int = 50):
    from . import testing as TST
    runs = sorted(TST.store(hub)["runs"].values(), key=lambda r: TST._num(r["id"]), reverse=True)[:max(1, min(limit, 200))]
    return JSONResponse(content={"runs": runs})


@app.get("/api/testing/runs/{run_id}")
async def testing_run(run_id: str):
    from . import testing as TST
    run = TST.store(hub)["runs"].get(run_id.upper())
    if run is None:
        return JSONResponse(status_code=404, content={"error": tx("Test run bulunamadı.")})
    return JSONResponse(content={"run": run})


@app.get("/api/testing/matrix")
async def testing_matrix():
    """İzlenebilirlik matrisi: kabul kriteri ↔ case ↔ otomasyon ↔ sonuç; kapsama yüzdesi."""
    from . import testing as TST
    return JSONResponse(content={"matrix": TST.matrix(hub, _active_project_dir())})


@app.get("/api/testing/summary")
async def testing_summary():
    from . import testing as TST
    return JSONResponse(content={"summary": TST.summary(hub)})


@app.get("/api/testing/plan/{n}")
async def testing_plan(n: int):
    from . import testing as TST
    return JSONResponse(content={"sprint": n, "markdown": TST.plan_markdown(hub, n), "file": f"{TST._docs(hub)}/tests/plan-sprint-{n}.md"})


@app.post("/api/testing/plan/{n}/write")
async def testing_write_plan(n: int):
    from . import testing as TST
    return JSONResponse(content={"status": "OK", "file": TST.write_plan(hub, n)})


@app.get("/api/testing/config")
async def testing_get_config():
    from . import testing as TST
    return JSONResponse(content={"config": TST.config(hub)})


@app.post("/api/testing/config")
async def testing_set_config(body: Dict[str, Any]):
    from . import testing as TST
    try:
        cfg = TST.set_config(hub, body or {})
    except TST.CaseError as e:
        return _testing_error(e)
    return JSONResponse(content={"status": "OK", "config": cfg})


@app.get("/api/testing/scenarios")
async def testing_scenarios():
    """Projenin E2E senaryoları (`e2e/scenarios/*.json`); bozuk dosya `invalid` ile gelir."""
    from . import testing as TST
    return JSONResponse(content={"scenarios": TST.list_scenarios(_active_project_dir())})


@app.put("/api/testing/scenarios/{sid}")
async def testing_save_scenario(sid: str, body: Dict[str, Any]):
    """Senaryoyu doğrulayıp kaydeder (kimliği yol belirler). Sunucunun E2E koşucusu aynı dosyayı koşar."""
    from . import testing as TST
    try:
        sc = TST.save_scenario(_active_project_dir(), {**(body or {}), "id": sid})
    except TST.CaseError as e:
        return _testing_error(e)
    return JSONResponse(content={"status": "OK", "scenario": sc})


@app.delete("/api/testing/scenarios/{sid}")
async def testing_delete_scenario(sid: str):
    from . import testing as TST
    try:
        removed = TST.delete_scenario(_active_project_dir(), sid)
    except TST.CaseError as e:
        return _testing_error(e)
    if not removed:
        return JSONResponse(status_code=404, content={"error": tx("Senaryo bulunamadı.")})
    return JSONResponse(content={"status": "DELETED", "id": sid})


# ---------------------------------------------------------------------------
# Proje Bazlı Ajan Promptu (.md), Git-Tree Versiyonlama & Global Terfi
# ---------------------------------------------------------------------------
@app.get("/api/agents/{agent_id}/prompt")
async def get_agent_prompt(agent_id: str, project_id: Optional[str] = None):
    """Ajanın .fs-workspace altındaki Markdown içeriğini ve versiyon ağacını getirir."""
    try:
        details = hub.get_agent_prompt_details(agent_id, project_id)
        return JSONResponse(content={"status": "OK", "prompt_info": details})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.post("/api/agents/{agent_id}/prompt")
async def save_agent_prompt(agent_id: str, body: Dict[str, Any]):
    """Ajanın Markdown dosyasını günceller ve yeni bir versiyon commit'ler."""
    content = body.get("content", "")
    commit_message = body.get("commit_message", tx("Ajan kuralları güncellendi"))
    author = body.get("author", "User")
    project_id = body.get("project_id")

    try:
        updated_info = hub.save_agent_prompt_content(
            agent_id=agent_id,
            content=content,
            commit_message=commit_message,
            author=author,
            project_id=project_id
        )
        return JSONResponse(content={"status": "OK", "prompt_info": updated_info})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.post("/api/agents/{agent_id}/restore")
async def restore_agent_prompt(agent_id: str, body: Dict[str, Any]):
    """Ajanın geçmiş bir versiyonunu aktif hale getirir (Rollback)."""
    version_id = body.get("version_id")
    author = body.get("author", "User")
    project_id = body.get("project_id")
    if not version_id:
        return JSONResponse(status_code=400, content={"error": tx("version_id gereklidir.")})

    try:
        restored = hub.restore_agent_prompt_version(
            agent_id=agent_id,
            version_id=version_id,
            author=author,
            project_id=project_id
        )
        return JSONResponse(content={"status": "OK", "prompt_info": restored})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.post("/api/agents/{agent_id}/inherit")
async def inherit_agent_prompt(agent_id: str, body: Dict[str, Any] = {}):
    """Ajanı global standart şablonla yeniden kalıtır / eşitler."""
    author = body.get("author", "User")
    project_id = body.get("project_id")

    try:
        inherited = hub.inherit_agent_prompt_standard(
            agent_id=agent_id,
            author=author,
            project_id=project_id
        )
        return JSONResponse(content={"status": "OK", "prompt_info": inherited})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.post("/api/agents/{agent_id}/promote-to-global")
async def promote_agent_prompt(agent_id: str, body: Dict[str, Any] = {}):
    """Projedeki ajanın Markdown kural ve birikimini şirketin genel standardına terfi ettirir."""
    project_id = body.get("project_id")

    try:
        promoted = hub.promote_agent_prompt_global(
            agent_id=agent_id,
            project_id=project_id
        )
        return JSONResponse(content={"status": "OK", "promotion": promoted})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


# ---------------------------------------------------------------------------
# Adım Adım İnceleme & Kullanıcı Devam Onayı (Human-in-the-Loop Pipeline)
# ---------------------------------------------------------------------------
@app.get("/api/pipeline/pending-step")
async def get_pending_step():
    """Şu an onay bekleyen ajan adımının detaylarını döner."""
    return JSONResponse(content={
        "pending_step": hub.pending_step_approval,
        "step_by_step_mode": hub.step_by_step_mode,
        "active_run_id": hub.active_run_id
    })


@app.post("/api/pipeline/approve-step")
async def approve_step_endpoint(body: Dict[str, Any] = {}):
    """Kullanıcının adıma verdiği onayı (PROCEED, AUTO_ALL veya REJECTED) çözer."""
    decision = body.get("decision", "PROCEED")
    token = body.get("token") or body.get("approval_token")
    result = await hub.approve_step(decision, token=token, comment=str(body.get("comment") or ""))
    status = result.get("status")
    await CL.record(hub, direction="manager", tool="approve_step", run_id=hub.active_run_id, status=status,
                    args={"decision": decision, "comment": str(body.get("comment") or "")[:2000]}, result=result)
    status_code = 200 if status == "APPROVED" else (400 if status == "INVALID" else 409)
    return JSONResponse(status_code=status_code, content=result)


@app.get("/api/pipeline/decisions")
async def get_tech_decisions():
    """Teknoloji kararları: soru seti, kayıtlı cevaplar ve bekleyen karar kapısı."""
    pending = hub.pending_step_approval or {}
    return JSONResponse(content={
        "questions": hub.tech_questions(),
        "tech_decisions": hub.tech_decisions(),
        "pending": pending.get("kind") == "decisions",
        "approval_token": hub.approval_token if pending.get("kind") == "decisions" else None,
    })


@app.post("/api/pipeline/decisions")
async def save_tech_decisions(body: Dict[str, Any] = {}):
    """Kullanıcının teknoloji kararlarını kaydeder; bekleyen karar kapısı varsa koşuyu sürdürür."""
    answers = body.get("answers") or {}
    if not isinstance(answers, dict):
        return JSONResponse(status_code=400, content={"error": tx("answers bir nesne olmalı")})
    decisions = await hub.save_tech_decisions(answers, str(body.get("notes") or ""), source="user")
    await CL.record(hub, direction="manager", tool="save_tech_decisions", run_id=hub.active_run_id, status="SAVED", args={"answers": answers, "notes": str(body.get("notes") or "")[:1000]})
    return JSONResponse(content={"status": "SAVED", "tech_decisions": decisions, "questions": hub.tech_questions(),
                                 "approved": hub.tech_requirements_approved()})


@app.get("/api/tech-requirements")
async def get_tech_requirements():
    """Teknoloji gereksinimleri (TR kalemleri, açık sorular, kütüphaneler) ve kapı durumu."""
    from .tech_requirements import dry_run_enabled
    req = await hub.ensure_tech_requirements()
    pending = hub.pending_step_approval or {}
    return JSONResponse(content={"tech_requirements": req, "approved": hub.tech_requirements_approved(),
                                 "gate_open": pending.get("kind") == "decisions", "dry_run_enabled": dry_run_enabled()})


@app.post("/api/tech-requirements/approve")
async def approve_tech_requirements(body: Dict[str, Any] = {}):
    """Yönetici onayı: `approve_stated` BELİRTİLMİŞ kalemleri topluca onaylar; `answers` {TR-n | kategori: değer} kalemleri tek tek cevaplar.
    EKSİK / ÇELİŞKİLİ kalem yalnızca açık cevapla onaylanır."""
    answers = body.get("answers") or {}
    if not isinstance(answers, dict):
        return JSONResponse(status_code=400, content={"error": tx("answers bir nesne olmalı")})
    req = await hub.approve_tech_requirements(answers=answers, approve_stated=bool(body.get("approve_stated")), notes=str(body.get("notes") or ""))
    await CL.record(hub, direction="manager", tool="approve_tech_requirements", run_id=hub.active_run_id,
                    status="APPROVED" if hub.tech_requirements_approved() else "PENDING", args={"answers": answers, "approve_stated": bool(body.get("approve_stated"))})
    return JSONResponse(content={"status": "APPROVED" if hub.tech_requirements_approved() else "PENDING", "tech_requirements": req})


@app.post("/api/tech-requirements/questions/{question_id}/answer")
async def answer_tech_question(question_id: str, body: Dict[str, Any] = {}):
    try:
        req = await hub.answer_tech_question(question_id, str(body.get("answer") or ""))
    except KeyError:
        return JSONResponse(status_code=404, content={"error": tx("soru bulunamadı")})
    except ValueError as e:
        return JSONResponse(status_code=400, content={"error": str(e)})
    return JSONResponse(content={"status": "APPROVED" if hub.tech_requirements_approved() else "PENDING", "tech_requirements": req})


@app.delete("/api/pipeline/decisions")
async def reset_tech_decisions():
    await hub.clear_tech_decisions()
    return JSONResponse(content={"status": "CLEARED", "questions": hub.tech_questions()})


@app.post("/api/pipeline/approval-mode")
async def set_approval_mode(body: Dict[str, Any]):
    """El kaldırma modu: auto | critical_only | every_step | note_and_continue."""
    mode = str((body or {}).get("approval_mode") or "").lower()
    if mode not in ("auto", "critical_only", "every_step", "note_and_continue"):
        return JSONResponse(status_code=400, content={"error": tx("approval_mode geçersiz"), "allowed": ["auto", "critical_only", "every_step", "note_and_continue"]})
    settings = await hub.update_settings({"approval_mode": mode})
    return JSONResponse(content={"status": "OK", "approval_mode": settings["approval_mode"], "step_by_step_mode": hub.step_by_step_mode})


@app.get("/api/pipeline/raised-hands")
async def get_raised_hands(include_reviewed: int = 1):
    hands = hub.raised_hands if include_reviewed else [h for h in hub.raised_hands if not h.get("reviewed")]
    return JSONResponse(content={"raised_hands": hands, "unreviewed": sum(1 for h in hub.raised_hands if not h.get("reviewed"))})


@app.post("/api/pipeline/raised-hands/{hand_id}/resolve")
async def resolve_raised_hand(hand_id: str, body: Dict[str, Any] = {}):
    hand = await hub.resolve_hand(hand_id, reviewed=bool((body or {}).get("reviewed", True)))
    if hand is None:
        return JSONResponse(status_code=404, content={"error": tx("Kayıt bulunamadı")})
    return JSONResponse(content={"status": "OK", "hand": hand})


@app.post("/api/pipeline/set-step-mode")
async def set_step_mode_endpoint(body: Dict[str, Any]):
    """Adım adım onaylı mod özelliğini dinamik olarak açar veya kapatır."""
    enabled = body.get("step_by_step", True)
    mode = await hub.set_step_mode(enabled)
    return JSONResponse(content={"status": "OK", "step_by_step_mode": mode})


# ---------------------------------------------------------------------------
# Pipeline Koşuları (REST ikizleri — MCP araçlarıyla aynı işlemler; proxy modu da bunları kullanır)
# ---------------------------------------------------------------------------
def _api_error(e: RunsApiError) -> JSONResponse:
    return JSONResponse(status_code=e.status_code, content=e.to_dict())


@app.post("/api/runs")
async def create_run(body: Dict[str, Any] = {}):
    """Yeni pipeline koşusu oluşturur (engine: mcp_client → kuyruğa alır, template → hemen koşar)."""
    try:
        result = await runs_api().start_run(
            project_id=body.get("project_id"),
            steps=body.get("steps") or body.get("selected_issues"),
            engine=body.get("engine"),
            custom_prompt=body.get("prompt") or body.get("custom_prompt") or "",
            step_by_step=body.get("step_by_step"),
            client=body.get("client"),
            force_new=bool(body.get("force_new", False)),
            project_dir=body.get("project_dir"),
        )
    except RunsApiError as e:
        return _api_error(e)
    status_code = 200 if result.get("status") in ("STARTED", "RESUMED") else 409
    return JSONResponse(status_code=status_code, content=result)


@app.post("/api/runs/{run_id}/restart-fresh")
async def restart_run_fresh(run_id: str, body: Dict[str, Any] = {}):
    """"Baştan başlat": ilerlemiş koşuyu bırakıp yenisini kurar. Proje silmedeki gibi iki aşamalı: pano proje adını yazdırır, sunucu `confirm_name`i doğrular."""
    try:
        result = await runs_api().restart_fresh(run_id, str((body or {}).get("confirm_name") or ""))
    except RunsApiError as e:
        return _api_error(e)
    return JSONResponse(content=result)


@app.get("/api/runs")
async def list_runs(project_id: Optional[str] = None, limit: int = 50):
    return JSONResponse(content=await runs_api().list_runs(project_id, limit))


@app.get("/api/runs/{run_id}")
async def get_run(run_id: str):
    try:
        return JSONResponse(content=await runs_api().get_run(run_id))
    except RunsApiError as e:
        return _api_error(e)


@app.post("/api/runs/{run_id}/next-step")
@app.get("/api/runs/{run_id}/next-step")
async def run_next_step(run_id: str, body: Dict[str, Any] = {}):
    try:
        return JSONResponse(content=await runs_api().next_step(run_id, client=(body or {}).get("client")))
    except RunsApiError as e:
        return _api_error(e)


@app.post("/api/runs/{run_id}/steps/{order}/result")
async def run_submit_result(run_id: str, order: int, body: Dict[str, Any]):
    raw = body.get("result_json")
    if raw is None:
        raw = body.get("result")
    try:
        return JSONResponse(content=await runs_api().submit_result(
            run_id, order, raw, int(body.get("tokens_in") or 0), int(body.get("tokens_out") or 0), client=body.get("client")
        ))
    except RunsApiError as e:
        return _api_error(e)


@app.post("/api/runs/{run_id}/pause")
async def run_pause(run_id: str, body: Dict[str, Any] = {}):
    try:
        return JSONResponse(content=await runs_api().pause_run(run_id, str(body.get("reason") or "user")))
    except RunsApiError as e:
        return _api_error(e)


@app.post("/api/runs/{run_id}/steps/{order}/skip")
async def run_skip_step(run_id: str, order: int, body: Dict[str, Any] = {}):
    """Yönetici: teslim edilmemiş bir adımı atlar (Jira maddesi BACKLOG'a döner)."""
    try:
        return JSONResponse(content=await runs_api().skip_step(run_id, order, str((body or {}).get("reason") or "")))
    except RunsApiError as e:
        return _api_error(e)


@app.post("/api/runs/{run_id}/resume")
async def run_resume(run_id: str):
    try:
        return JSONResponse(content=await runs_api().resume_run(run_id))
    except RunsApiError as e:
        return _api_error(e)


@app.post("/api/runs/{run_id}/approval")
@app.get("/api/runs/{run_id}/approval")
async def run_wait_approval(run_id: str, body: Dict[str, Any] = {}, timeout_s: Optional[float] = None):
    timeout = float((body or {}).get("timeout_s") or timeout_s or 30)
    try:
        return JSONResponse(content=await runs_api().wait_approval(run_id, timeout, client=(body or {}).get("client")))
    except RunsApiError as e:
        return _api_error(e)


@app.post("/api/runs/{run_id}/thinking")
async def run_report_thinking(run_id: str, body: Dict[str, Any]):
    try:
        return JSONResponse(content=await runs_api().report_thinking(
            run_id, body.get("agent_id", ""), body.get("text", ""), body.get("what_doing", ""), body.get("what_next", ""),
            client=body.get("client"),
        ))
    except RunsApiError as e:
        return _api_error(e)


@app.get("/api/runs/{run_id}/notes")
async def run_notes(run_id: str):
    run = hub.runs.get(run_id)
    if run is None:
        return JSONResponse(status_code=404, content={"error": tx("Koşu bulunamadı: {run_id}", run_id=run_id)})
    return JSONResponse(content={"run_id": run_id, "notes": run.manager_notes})


@app.post("/api/runs/{run_id}/notes")
async def run_add_note(run_id: str, body: Dict[str, Any] = {}):
    """Yönetici müdahalesi: not bir sonraki adımın bağlamına 'Yönetici notları' olarak girer; `urgent` koşuyu duraklatır."""
    from . import pipeline as P
    run = hub.runs.get(run_id)
    if run is None:
        return JSONResponse(status_code=404, content={"error": tx("Koşu bulunamadı: {run_id}", run_id=run_id)})
    try:
        note = await P.add_manager_note(hub, run, str((body or {}).get("text") or ""), urgent=bool((body or {}).get("urgent")))
    except ValueError as e:
        return JSONResponse(status_code=400, content={"error": str(e)})
    await CL.record(hub, direction="manager", tool="manager_note", run_id=run_id, status="URGENT" if run.paused else "OK",
                    text=str((body or {}).get("text") or ""), result=note)
    return JSONResponse(content={"status": "OK", "note": note, "paused": run.paused})


@app.post("/api/runs/{run_id}/cancel")
async def run_cancel(run_id: str, body: Dict[str, Any] = {}):
    try:
        return JSONResponse(content=await runs_api().cancel_run(run_id, (body or {}).get("reason") or "user"))
    except RunsApiError as e:
        return _api_error(e)


@app.get("/api/teams")
async def get_teams(include_partners: int = 1):
    """Petek topolojisi: aktif projenin takımı (departman kümeleri) + partner projelerin takımları."""
    from .teams import DEPARTMENTS, teams_for_hub
    return JSONResponse(content={
        "project_id": hub.active_project_id,
        "teams": teams_for_hub(hub, include_partners=bool(include_partners)),
        "departments": DEPARTMENTS,
    })


@app.post("/api/teams")
async def upsert_team(body: Dict[str, Any]):
    """Aktif projenin takım/departman tanımını kaydeder (settings.teams)."""
    from .teams import normalize_team, teams_for_hub
    team = normalize_team({**(body or {}), "project_id": hub.active_project_id}, hub.agents)
    settings = hub.get_settings()
    others = [t for t in (settings.get("teams") or []) if t.get("project_id") not in (hub.active_project_id, None)]
    hub.settings = {**settings, "teams": others + [team]}
    if hub.active_project_id in hub.projects:
        hub.projects[hub.active_project_id]["settings"] = dict(hub.settings)
    hub.mark_dirty()
    await hub.broadcast({"type": "TEAMS_UPDATED", "teams": teams_for_hub(hub, include_partners=True)})
    return JSONResponse(content={"status": "OK", "team": team})


@app.get("/api/settings/engine")
async def get_engine_settings():
    return JSONResponse(content={"status": "OK", "settings": hub.get_settings(), "connected_clients": list(hub.connected_clients.values())})


@app.post("/api/settings/engine")
async def update_engine_settings(body: Dict[str, Any]):
    settings = await hub.update_settings(body or {})
    return JSONResponse(content={"status": "OK", "settings": settings})


@app.get("/api/settings/sprint")
async def get_sprint_settings():
    from . import sprint as SP
    return JSONResponse(content={"status": "OK", "sprint": SP.cfg(hub)})


@app.post("/api/settings/sprint")
async def update_sprint_settings(body: Dict[str, Any] = {}):
    from . import sprint as SP
    await hub.update_settings({"sprint": body or {}})
    return JSONResponse(content={"status": "OK", "sprint": SP.cfg(hub)})


@app.post("/api/runner/claim")
async def runner_claim(body: Dict[str, Any] = {}):
    return JSONResponse(content=await runs_api().claim_work((body or {}).get("client")))


@app.get("/api/runner/status")
async def runner_status_endpoint():
    from . import driver as DRV
    return JSONResponse(content=DRV.runner_status(hub))


@app.get("/api/activity")
async def activity_endpoint(limit: int = 30):
    return JSONResponse(content=await runs_api().get_activity(limit))


@app.post("/api/manager-input")
async def manager_input(body: Dict[str, Any] = {}):
    try:
        res = await runs_api().add_manager_input(str(body.get("text") or ""), str(body.get("title") or tx("Yönetici girdisi")), str(body.get("client_name") or tx("Yönetici")),
                                                 bool(body.get("urgent", False)), client=body.get("client"))
    except RunsApiError as e:
        return _api_error(e)
    return JSONResponse(content=res)


@app.get("/api/sprints/state")
async def sprint_state_endpoint():
    return JSONResponse(content=await runs_api().get_sprint_state())


@app.get("/budget")
async def budget_page():
    """Panodan bağımsız tek sayfa: sprint bütçesini düzenle + engeli kaldır."""
    from .budget_page import PAGE
    return HTMLResponse(content=PAGE)


@app.get("/api/reports/pi")
async def pi_report_data(sprint: Optional[int] = None):
    """PI planlama raporlarının ham verisi (burndown, velocity, CFD, epik ilerlemesi, kalite, tahmin). `sprint`: tek sprintin ayrıntısı."""
    from . import reports as RP
    return JSONResponse(content=RP.pi_data(hub, sprint))


@app.get("/api/reports/pi.html")
async def pi_report_html(sprint: Optional[int] = None, embed: int = 0, theme: Optional[str] = None):
    """Tek dosyalık, yazdırılabilir (PDF) PI planlama raporu; SVG grafikler sunucuda çizilir. `sprint`: seçili sprint, `embed=1`: panoya gömülü kip."""
    from . import reports as RP
    return HTMLResponse(content=RP.render_html(RP.pi_data(hub, sprint), embed=bool(embed), theme=theme))


@app.get("/api/sprints/board")
async def sprint_board_endpoint():
    """G5 sprint panosu: mevcut sprint, taahhüt önerisi/sayaç, kapasite, engel, taşınanlar, burndown, velocity, WIP uyarısı.
    (`/api/sprints/{n}` rotasından ÖNCE tanımlı olmalı.)"""
    from . import jira_plus as JP
    return JSONResponse(content={"status": "OK", **JP.sprint_board(hub)})


@app.post("/api/sprints/{n}/unblock")
async def unblock_sprint_endpoint(n: int):
    from . import driver as DRV
    try:
        sp = await DRV.unblock_sprint(hub, n)
    except ValueError as e:
        return JSONResponse(status_code=409, content={"error": str(e)})
    return JSONResponse(content={"status": "OK", "sprint": sp})


@app.post("/api/sprints/{n}/plan-review")
async def plan_review_endpoint(n: int):
    """Mimar gözden geçirmesi eksik (PRECONDITION_LOST) engelli sprint için ARCHITECT adımını koşuya ekler; bitince sprint kapanır."""
    from . import sprint_flow as SPF
    try:
        res = await SPF.plan_review_for_blocked(hub, n)
    except ValueError as e:
        return JSONResponse(status_code=409, content={"error": str(e)})
    return JSONResponse(content={"status": "OK", **res})


@app.post("/api/sprints/{n}/cancel")
async def cancel_sprint_endpoint(n: int):
    from . import driver as DRV
    try:
        sp = await DRV.cancel_sprint(hub, n)
    except ValueError as e:
        return JSONResponse(status_code=409, content={"error": str(e)})
    return JSONResponse(content={"status": "OK", "sprint": sp})


@app.post("/api/autonomy/stop")
async def autonomy_stop():
    from . import driver as DRV
    return JSONResponse(content=await DRV.stop_autonomy(hub))


@app.get("/api/autonomy/l3-preconditions")
async def autonomy_l3_preconditions():
    from . import driver as DRV
    checks = await DRV.l3_preconditions(hub)
    return JSONResponse(content={"ok": all(c["ok"] for c in checks), "checks": checks})


@app.get("/api/autonomy/overview")
async def autonomy_overview():
    """G4: pano kartı için tek uç — seviye, otonomi anahtarları, yalıtım ayarı, Docker ve L3 ön koşulları (düzeltme ipuçlarıyla)."""
    from . import driver as DRV
    from . import guard as G
    from . import meetings as M
    checks = await DRV.l3_preconditions(hub)
    return JSONResponse(content={"level": M.current_level(hub), "autonomy": M.autonomy(hub), "sandbox": G.sandbox(hub),
                                 "docker_available": G.docker_available(), "checks": checks, "l3_ok": all(c["ok"] for c in checks),
                                 "levels": M.PRESETS, "default_allow_prefixes": list(G.DEFAULT_ALLOW_PREFIXES)})


@app.post("/api/autonomy/preset")
async def autonomy_preset(body: Dict[str, Any] = {}):
    """Seviye ön ayarı (§3.1): düğme anahtarları topluca yazar. L3, ön koşullar eksikse reddedilir."""
    from . import driver as DRV
    try:
        return JSONResponse(content={"status": "OK", **await DRV.apply_preset(hub, str((body or {}).get("level") or ""))})
    except PermissionError as e:
        return JSONResponse(status_code=409, content={"error": str(e), "checks": await DRV.l3_preconditions(hub)})
    except ValueError as e:
        return JSONResponse(status_code=400, content={"error": str(e)})


@app.get("/api/settings/autonomy")
async def get_autonomy_settings():
    from . import meetings as M
    return JSONResponse(content={"status": "OK", "autonomy": M.autonomy(hub)})


@app.post("/api/settings/autonomy")
async def update_autonomy_settings(body: Dict[str, Any] = {}):
    from . import driver as DRV
    from . import meetings as M
    body = dict(body or {})
    level = body.pop("level", None)
    if level:
        try:
            await DRV.apply_preset(hub, str(level))
        except PermissionError as e:
            return JSONResponse(status_code=409, content={"error": str(e), "checks": await DRV.l3_preconditions(hub)})
        except ValueError as e:
            return JSONResponse(status_code=400, content={"error": str(e)})
    if body:
        await hub.update_settings({"autonomy": body})
        from . import sprint_flow as SPF
        await SPF.resume_if_budget_allows(hub)        # sprint bütçesi yüzünden duran proje, bütçe artınca kaldığı yerden sürer
    return JSONResponse(content={"status": "OK", "autonomy": M.autonomy(hub)})


@app.get("/api/learning")
async def learning_endpoint():
    """Öğrenme döngüsü: sprint eğilimi (ilk seferde geçme oranı, düzeltme turu, reddedilen teslim), retro aksiyonları ve uygulanma oranı, prompt değişiklikleri."""
    from . import learning as L
    return JSONResponse(content=L.learning_report(hub))


@app.post("/api/learning/prompt-changes/{change_id}/rollback")
async def rollback_prompt_change_endpoint(change_id: str):
    from . import learning as L
    try:
        return JSONResponse(content={"status": "OK", "change": await L.rollback_prompt_change(hub, change_id)})
    except KeyError:
        return JSONResponse(status_code=404, content={"error": tx("Değişiklik bulunamadı: {id}", id=change_id)})
    except ValueError as e:
        return JSONResponse(status_code=409, content={"error": str(e)})


@app.get("/api/settings/sandbox")
async def get_sandbox_settings():
    from . import guard as G
    return JSONResponse(content={"sandbox": G.sandbox(hub), "docker_available": G.docker_available(), "default_allow_prefixes": list(G.DEFAULT_ALLOW_PREFIXES)})


@app.post("/api/settings/sandbox")
async def update_sandbox_settings(body: Dict[str, Any] = {}):
    """Komut yalıtımı (§12 madde 1). `mode=container` Docker gerektirir; Docker yokken reddedilir (host'a sessizce düşülmez)."""
    from . import guard as G
    want = (body or {}).get("mode")
    if want == "container" and not G.docker_available_fresh():
        return JSONResponse(status_code=409, content={"error": tx("sandbox.mode=container için Docker kullanılabilir olmalı (docker info sunucuya ulaşamıyor).")})
    await hub.update_settings({"sandbox": body or {}})
    return JSONResponse(content={"sandbox": G.sandbox(hub), "docker_available": G.docker_available()})


@app.get("/api/settings/runner")
async def get_runner_settings():
    from . import driver as DRV
    return JSONResponse(content={"runner": DRV.runner_cfg(hub), "display": DRV.display_cfg(hub)})


@app.post("/api/settings/runner")
async def update_runner_settings(body: Dict[str, Any] = {}):
    from . import driver as DRV
    patch = {k: v for k, v in (body or {}).items() if k in ("runner", "display") and isinstance(v, dict)}
    if not patch and body:      # düz gövde: runner anahtarları
        patch = {"runner": {k: v for k, v in body.items() if k in DRV.DEFAULT_RUNNER}, "display": {k: v for k, v in body.items() if k in DRV.DEFAULT_DISPLAY}}
    await hub.update_settings({k: v for k, v in patch.items() if v})
    return JSONResponse(content={"runner": DRV.runner_cfg(hub), "display": DRV.display_cfg(hub)})


@app.post("/api/mcp/log")
async def mcp_log(body: Dict[str, Any] = {}):
    """stdio (proxy) sürecinin MCP araç çağrılarını web sunucusunun Claude iletişim günlüğüne yazması için."""
    from . import mcp_activity as MA
    tool = str((body or {}).get("tool") or "").strip()[:60]
    if not tool:
        return JSONResponse(status_code=400, content={"error": tx("tool gerekli")})
    client = (body or {}).get("client") or {}
    if isinstance(client, dict) and client.get("name"):
        await hub.mark_client_seen(str(client["name"]), str(client.get("version", "")))
    await MA.log_call(hub, tool, None, client if isinstance(client, dict) else None,
                      result=str((body or {}).get("result") or "")[:120], title=str((body or {}).get("title") or "")[:120],
                      run_id=(body or {}).get("run_id") or None)
    if "args" in (body or {}) or "result_full" in (body or {}):
        await CL.record(hub, direction="to_server", tool=tool, run_id=(body or {}).get("run_id") or None, client=client if isinstance(client, dict) else None,
                        status=str((body or {}).get("result") or "")[:60], args=(body or {}).get("args"), result=(body or {}).get("result_full"))
    return JSONResponse(content={"status": "OK"})


@app.get("/api/mcp/activity")
async def mcp_activity():
    """Claude (MCP istemcisi) ile iletişim: şimdi sıra kimde, istemci bağlantısı ve son araç çağrıları."""
    from . import mcp_activity as MA
    return JSONResponse(content=MA.snapshot(hub))


@app.get("/api/questions")
async def list_questions(status: Optional[str] = None):
    """Soru kuyruğu (§10.4): toplantı soruları + teknoloji gereksinimi soruları. Süresi dolan teknoloji dışı sorular listelenirken varsayılana çevrilir."""
    from . import meetings as M
    await M.expire_questions(hub)
    qs = [{k: v for k, v in q.items() if k != "adr_draft"} for q in M.all_questions(hub)]
    if status:
        qs = [q for q in qs if q.get("status") == status.upper()]
    return JSONResponse(content={"questions": qs, "open_blocking": [q["id"] for q in M.open_blocking(hub)]})


@app.post("/api/questions/{question_id}/answer")
async def answer_question_endpoint(question_id: str, body: Dict[str, Any] = {}):
    """Yönetici cevabı (seçenek anahtarı). DEFAULTED soruya farklı cevap → OVERRIDDEN; teknoloji gereksinimi sorusunda cevap seçenek metnidir."""
    from . import meetings as M
    answer = str((body or {}).get("answer") or "").strip()
    custom = str((body or {}).get("custom_text") or "").strip()     # serbest metin cevap ('Diğer')
    if not answer and not custom:
        return JSONResponse(status_code=400, content={"error": tx("answer ya da custom_text gerekli")})
    if (body or {}).get("restrict_blocking"):
        try:
            await runs_api().answer_question(question_id, answer)    # MCP yolu: engelleyici soru reddedilir
        except RunsApiError as e:
            return _api_error(e)
        return JSONResponse(content={"status": "OK"})
    try:
        q = await M.answer_question(hub, question_id, answer, by="MANAGER", custom_text=custom or None)
        await CL.record(hub, direction="manager", tool="answer_question", run_id=hub.active_run_id, status=q.get("status"),
                        args={"question_id": question_id, "answer": answer, "custom_text": custom})
        return JSONResponse(content={"status": "OK", "question": {k: v for k, v in q.items() if k != "adr_draft"}})
    except KeyError:
        pass
    except ValueError as e:
        return JSONResponse(status_code=400, content={"error": str(e)})
    tech = next((q for q in M.all_questions(hub) if q["id"] == question_id and q.get("source") == "tech_requirements"), None)
    if tech is None:
        return JSONResponse(status_code=404, content={"error": tx("Soru bulunamadı: {id}", id=question_id)})
    value = custom or next((o["label"] for o in tech["options"] if o["key"] == answer), answer)
    req = await hub.answer_tech_question(question_id, value)
    return JSONResponse(content={"status": "APPROVED" if hub.tech_requirements_approved() else "PENDING", "tech_requirements": req})


@app.get("/api/meetings")
async def list_meetings():
    from . import sprint as SP
    return JSONResponse(content={"meetings": [{k: v for k, v in m.items() if k not in ("discussion", "inputs", "project_dir")}
                                              for m in SP.ensure_state(hub)["meetings"]]})


@app.get("/api/meetings/{meeting_id}")
async def get_meeting(meeting_id: str):
    from . import meetings as M
    from . import sprint as SP
    m = next((x for x in SP.ensure_state(hub)["meetings"] if x["id"] == meeting_id), None)
    if m is None:
        return JSONResponse(status_code=404, content={"error": tx("Toplantı bulunamadı: {id}", id=meeting_id)})
    return JSONResponse(content={"meeting": {k: v for k, v in m.items() if k != "project_dir"}, "minutes_md": M.render_minutes(hub, m)})


@app.get("/api/adr")
async def list_adr():
    from . import adr as ADR
    from . import sprint as SP
    # Etkin projenin klasörü + toplantıların yazıldığı hedef klasörler (koşu başka bir klasöre yazıyorsa)
    dirs = [(hub.projects.get(hub.active_project_id) or {}).get("path") or hub.default_project_path]
    dirs += [m.get("project_dir") for m in SP.ensure_state(hub)["meetings"] if m.get("project_dir")]
    seen, out = set(), []
    for d in dict.fromkeys(dirs):
        for a in ADR.list_adrs(d, hub_docs_path(hub, "", d)):
            if a["file"] not in seen or a["number"] not in {x["number"] for x in out}:
                seen.add(a["file"])
                out.append({**a, "project_dir": d})
    return JSONResponse(content={"adr": out})


@app.get("/api/sprints")
async def list_sprints():
    """Sprint durumu (`sprint_state.json`): proje durumu, mevcut sprint, sprintler, bekleyen değerlendirme."""
    from . import sprint as SP
    from .tech_requirements import dry_run_enabled
    st = SP.ensure_state(hub)
    return JSONResponse(content={"status": "OK", "settings": SP.cfg(hub), "state": {k: v for k, v in st.items() if k not in ("acs", "meetings", "meeting_commitments", "decisions")},
                                 "dry_run": {"enabled": dry_run_enabled(), "fail_task": os.environ.get("FSSC_DRY_RUN_FAIL_TASK") == "1"}})


@app.get("/api/sprints/{n}")
async def get_sprint_detail(n: int):
    from . import sprint as SP
    sp = SP.get_sprint(hub, n)
    if sp is None:
        return JSONResponse(status_code=404, content={"error": tx("Sprint {n} bulunamadı.", n=n)})
    items = [hub.jira_issues[i] for i in sp.get("committed_issue_ids", []) if i in hub.jira_issues]
    return JSONResponse(content={"status": "OK", "sprint": sp, "items": items})


@app.patch("/api/sprints/{n}")
@_jp_errors
async def patch_sprint(n: int, body: Dict[str, Any] = {}):
    """Sprint hedefi yalnızca PLANNING durumunda düzenlenir."""
    from . import jira_plus as JP
    sp = await JP.set_sprint_goal(hub, n, str((body or {}).get("goal") or ""))
    return JSONResponse(content={"status": "OK", "sprint": sp})


@app.post("/api/sprints/{n}/commit")
async def commit_sprint(n: int):
    """Manuel taahhüt onayı: bekleyen sprint taahhüt kapısını çözer."""
    pending = hub.pending_step_approval or {}
    if pending.get("kind") != "sprint_commit" or int(str(pending.get("issue_id", "SPRINT-0")).split("-")[-1] or 0) != int(n):
        return JSONResponse(status_code=409, content={"error": tx("Sprint {n} için bekleyen taahhüt onayı yok.", n=n)})
    return JSONResponse(content=await hub.approve_step("PROCEED"))


@app.post("/api/sprints/plan-next")
async def plan_next_sprint(body: Dict[str, Any] = {}):
    """auto_chain kapalıyken yönetici sıradaki sprinti başlatır (yeni yükleme olmadan)."""
    from . import sprint as SP
    if not SP.enabled(hub):
        return JSONResponse(status_code=409, content={"error": tx("sprint.enabled kapalı.")})
    try:
        res = await runs_api().start_sprint_run(project_id=(body or {}).get("project_id"), with_intake=False)
    except RunsApiError as e:
        return JSONResponse(status_code=e.status_code, content=e.to_dict())
    return JSONResponse(content=res)


@app.get("/api/plan")
async def get_plan():
    """İş planı ağacı: epik ▸ hikâye ▸ görev (sprint ataması ve taşıma bilgisiyle)."""
    def node(i: Dict[str, Any]) -> Dict[str, Any]:
        return {k: i.get(k) for k in ("id", "task_key", "title", "kind", "status", "assignee", "work_type", "sprint", "priority", "ac_refs",
                                      "depends_on", "carry_over", "needs_rescope", "origin", "supersedes", "related_to")}
    issues = list(hub.jira_issues.values())
    kids: Dict[str, List[Dict[str, Any]]] = {}
    for i in issues:
        if i.get("parent_id"):
            kids.setdefault(i["parent_id"], []).append(i)
    def build(i: Dict[str, Any]) -> Dict[str, Any]:
        n = node(i)
        n["children"] = [build(c) for c in sorted(kids.get(i["id"], []), key=lambda x: int(x.get("order", 0) or 0))]
        return n
    epics = [i for i in issues if str(i.get("kind", "")).lower() == "epic"]
    orphans = [i for i in issues if str(i.get("kind", "")).lower() in ("story", "task") and (not i.get("parent_id") or i.get("parent_id") not in hub.jira_issues)]
    return JSONResponse(content={"epics": [build(e) for e in sorted(epics, key=lambda x: int(x.get("order", 0) or 0))],
                                 "unparented": [build(o) for o in orphans]})


@app.get("/api/mcp/clients")
async def get_mcp_clients():
    return JSONResponse(content={"clients": list(hub.connected_clients.values())})


@app.post("/api/mcp/clients/seen")
async def post_mcp_client_seen(body: Dict[str, Any] = {}):
    client = (body or {}).get("client") or {}
    if client.get("name"):
        await hub.mark_client_seen(client["name"], client.get("version", ""))
    return JSONResponse(content={"status": "OK"})


@app.post("/api/deliberation/open")
async def deliberation_open(body: Dict[str, Any] = {}):
    try:
        return JSONResponse(content=await runs_api().open_deliberation((body or {}).get("spec_id", ""), (body or {}).get("title", ""), client=(body or {}).get("client")))
    except RunsApiError as e:
        return _api_error(e)


@app.post("/api/deliberation/turn")
async def deliberation_turn(body: Dict[str, Any]):
    try:
        return JSONResponse(content=await runs_api().deliberation_turn(
            body.get("session_id", ""), body.get("agent_id", "PM"), body.get("message", ""), body.get("sentiment", "AGREE"),
            client=body.get("client"), proposals=body.get("proposals"),
        ))
    except (RunsApiError, ValueError) as e:
        status = getattr(e, "status_code", 404)
        return JSONResponse(status_code=status, content={"error": str(e)})


@app.post("/api/deliberation/choose-plan")
async def deliberation_choose_plan(body: Dict[str, Any]):
    """Kullanıcı alternatif mimari planlardan birini seçer; bekleyen MCP istemcisi serbest kalır."""
    try:
        return JSONResponse(content=await runs_api().choose_plan(body.get("session_id", ""), body.get("plan_id", ""), body.get("chosen_by", "USER")))
    except RunsApiError as e:
        return _api_error(e)


@app.post("/api/deliberation/approve")
async def deliberation_approve(body: Dict[str, Any]):
    """NİHAİ karar: yönetici ajanların konsensüs önerisini (ya da seçtiği başka planı) onaylar; kayıt resmî karar (DEC-n) olur."""
    try:
        return JSONResponse(content=await runs_api().choose_plan(body.get("session_id", ""), body.get("plan_id", ""), body.get("chosen_by", "USER"), body.get("apply", "now")))
    except RunsApiError as e:
        return _api_error(e)


@app.post("/api/jira/link-orphans")
async def link_orphans_endpoint(apply: bool = False):
    """Bir epiğe/hikâyeye bağlı olmayan işleri en uygun hikâye/epiğe bağlar. Varsayılan kuru plan; `?apply=true` uygular (dondurulmuş maddede de; denetime işlenir)."""
    from . import hierarchy as H
    return JSONResponse(content={"status": "OK", **await H.link_orphans(hub, apply=apply)})


@app.get("/api/skills")
async def skills_overview():
    """Skill kütüphanesi: katalog, rol başına etkin seçim, önbellek durumu (aitmpl.com/skills · davila7/claude-code-templates)."""
    from . import skills as SKL
    return JSONResponse(content=SKL.overview(hub))


@app.post("/api/skills/config")
async def skills_config(body: Dict[str, Any]):
    """Skill ayarı: {enabled, roles: {ROL: [skill kimlikleri]}, max_chars}; seçilen skill'ler arka planda indirilir."""
    from . import skills as SKL
    await hub.update_settings({"agent_skills": body or {}})
    cfg = SKL.settings(hub)
    SKL.prefetch([i for ids in cfg["roles"].values() for i in ids])
    return JSONResponse(content={"status": "OK", **SKL.overview(hub)})


@app.post("/api/skills/refresh")
async def skills_refresh():
    """Etkin tüm skill'leri yeniden indirir (kaynaktaki güncel sürüm); sonuç: indirilen/başarısız sayıları."""
    import asyncio
    from . import skills as SKL
    ids = sorted({i for a in hub.agents for i in SKL.skills_for_role(hub, a)})
    ok = await asyncio.to_thread(lambda: [SKL.fetch(i) for i in ids])
    return JSONResponse(content={"status": "OK", "downloaded": sum(1 for x in ok if x), "failed": sum(1 for x in ok if not x), "total": len(ids)})


@app.post("/api/agents/restore-defaults")
async def restore_default_agents():
    """Kaldırılmış varsayılan isteğe bağlı ajanları (Mobile Designer, Security, SEO, Code Reviewer) geri getirir."""
    added = await hub.restore_default_agents()
    return JSONResponse(content={"status": "OK", "restored": added})


@app.post("/api/design/start")
async def design_start(request: Request):
    """Yönetici: tasarım çalışması (tasarım sistemi + ilk ekranlar, HTML mockup) hemen başlasın; geçerli adımdan sonra çalışır, tamamlanınca onayını bekler."""
    from . import sprint_flow as SPF
    try:
        try:
            body = await request.json()
        except Exception:
            body = {}
        return JSONResponse(content={"status": "OK", **await SPF.start_design_now(hub, str((body or {}).get("brief") or ""))})
    except (ValueError, PermissionError, KeyError) as e:
        return JSONResponse(status_code=409, content={"error": str(e)})


@app.post("/api/design/reimplement")
async def design_reimplement():
    """Yönetici: mockup'ı uygulamadan (yalnızca sözleşme yazarak) kapanmış ekran görevleri için "Ekran uyumu" görevleri açılır ve sprint kuyruğunda öne alınır."""
    from . import pipeline as P
    return JSONResponse(content={"status": "OK", "created": await P.reopen_screen_tasks(hub)})


@app.get("/api/design/fidelity")
async def design_fidelity_get():
    """Son ekran uyumu raporu (yoksa null)."""
    from . import fidelity as FID
    from . import pipeline as P
    pd = (hub.projects.get(hub.active_project_id) or {}).get("path") or hub.default_project_path
    return JSONResponse(content={"report": FID.load_report(pd)})


@app.post("/api/scope/correct")
async def scope_correct(request: Request):
    """Yönetici kapsam düzeltmesi: ürün tanımını yazar, kapsam dışı başlamamış işleri siler, PRD'yi yenileyecek acil mimar görevi açar (`dry_run` ile önce önizleme)."""
    from . import scope_change as SC
    try:
        body = await request.json()
    except Exception:
        body = {}
    try:
        res = await SC.correct(hub, str(body.get("statement") or ""), body.get("terms"), bool(body.get("dry_run")), api=runs_api())
        return JSONResponse(content={"status": "OK", **res})
    except (ValueError, PermissionError, KeyError) as e:
        return JSONResponse(status_code=409, content={"error": str(e)})


@app.get("/api/goals")
async def goals_list():
    """Yönetici hedefleri ve ilerleme (ekran hedefi için son ekran uyumu raporu)."""
    from . import fidelity as FID
    from . import goals as GL
    from . import sprint as SPR
    pd = (hub.projects.get(hub.active_project_id) or {}).get("path") or hub.default_project_path
    report = FID.load_report(pd)
    return JSONResponse(content={"goals": [{**g, "progress": GL.progress(hub, g, report)} for g in SPR.ensure_state(hub).get("goals", [])]})


@app.post("/api/goals")
async def goals_add(request: Request):
    from . import goals as GL
    try:
        body = await request.json()
        return JSONResponse(content={"status": "OK", "goal": GL.add(hub, str(body.get("text") or ""), str(body.get("kind") or "free"))})
    except (ValueError, KeyError) as e:
        return JSONResponse(status_code=409, content={"error": str(e)})


@app.post("/api/goals/{goal_id}/status")
async def goals_status(goal_id: str, request: Request):
    from . import goals as GL
    try:
        body = await request.json()
        return JSONResponse(content={"status": "OK", "goal": GL.set_status(hub, goal_id, str(body.get("status") or ""))})
    except KeyError:
        return JSONResponse(status_code=404, content={"error": "Hedef yok"})
    except ValueError as e:
        return JSONResponse(status_code=409, content={"error": str(e)})


@app.post("/api/design/fidelity")
async def design_fidelity_run(request: Request):
    """Yönetici/sunucu: onaylı mockup'ları çalışan uygulamadaki ekranlarla karşılaştırır (Playwright). Eşik altı ekran için Ekran uyumu görevi açılır (`open_tasks`, varsayılan true).
    İstemci adresi `verification.client_url`; kapalıysa `verification.client_run` ile geçici başlatılır."""
    from . import fidelity as FID
    from . import pipeline as P
    from .app_runner import start_app
    from .paths import hub_docs_path
    try:
        body = await request.json()
    except Exception:
        body = {}
    pd = (hub.projects.get(hub.active_project_id) or {}).get("path") or hub.default_project_path
    ver = hub.get_settings().get("verification") or {}
    url = str((body or {}).get("url") or ver.get("client_url") or "").strip()
    if not url:
        return JSONResponse(status_code=409, content={"error": "verification.client_url tanımlı değil"})
    screens = FID.screens_of(hub)
    if not screens:
        return JSONResponse(status_code=409, content={"error": "Tasarımdan açılmış ekran görevi yok"})
    app_proc = None
    import urllib.request
    def _up() -> bool:
        try:
            return urllib.request.urlopen(url, timeout=3).status < 500
        except Exception:
            return False
    if not await asyncio.to_thread(_up):
        if not ver.get("client_run"):
            return JSONResponse(status_code=409, content={"error": f"İstemciye ulaşılamıyor ({url}) ve verification.client_run tanımlı değil"})
        started = await start_app(pd, ver["client_run"], url)
        if not started.get("ok"):
            return JSONResponse(status_code=409, content={"error": "İstemci başlatılamadı: " + str(started.get("error"))})
        app_proc = started["app"]
    try:
        report = await FID.compare(pd, hub_docs_path(hub, "").rstrip("/"), url, screens, hub.active_project_id)
    finally:
        if app_proc is not None:
            await app_proc.stop()
    made = await P.open_fidelity_tasks(hub, report) if (body or {}).get("open_tasks", True) else []
    from . import goals as GL
    GL.on_fidelity(hub, report)
    return JSONResponse(content={"status": "OK", "passed": report["passed"], "total": report["total"], "created_tasks": made,
                                 "screens": [{"id": r["id"], "ok": r.get("ok"), "problems": r.get("problems")} for r in report["screens"]]})


@app.post("/api/deliberation/split")
async def deliberation_split(body: Dict[str, Any]):
    """Onaylı kararı rol bazlı görevlere bölecek mimar görevini açar (karar önceliklidir)."""
    try:
        return JSONResponse(content=await runs_api().split_decision(body.get("session_id", ""), body.get("apply", "now")))
    except RunsApiError as e:
        return _api_error(e)


@app.post("/api/deliberation/revise")
async def deliberation_revise(body: Dict[str, Any]):
    """Yönetici öneriyi kabul etmez: geri bildirimle oturum yeni tura girer (geçmişte görünür)."""
    try:
        return JSONResponse(content=await runs_api().revise_deliberation(body.get("session_id", ""), body.get("feedback", ""), body.get("by", "USER")))
    except RunsApiError as e:
        return _api_error(e)


@app.get("/api/deliberation/history")
async def deliberation_history():
    """Müzakere geçmişi (yeniden eskiye): nihai kararlar, yarım kalanlar, güncel oturum."""
    return JSONResponse(content={"sessions": hub.deliberation_engine.history_list()})


@app.get("/api/deliberation/session/{session_id}")
async def deliberation_session(session_id: str):
    s = hub.deliberation_engine.get_session_dict(session_id)
    if s is None:
        return JSONResponse(status_code=404, content={"error": tx("Oturum bulunamadı.")})
    return JSONResponse(content={"session": s})


@app.post("/api/deliberation/close")
async def deliberation_close(body: Dict[str, Any]):
    try:
        return JSONResponse(content=await runs_api().close_deliberation(body.get("session_id", ""), body.get("consensus") or {}, client=body.get("client")))
    except (RunsApiError, ValueError) as e:
        status = getattr(e, "status_code", 404)
        return JSONResponse(status_code=status, content={"error": str(e)})


@app.post("/api/reset")
async def post_reset():
    """Telemetri geçmişini ve görev panosunu sıfırlar."""
    await hub.reset()
    return JSONResponse(content={"status": "RESET_COMPLETED"})


@app.post("/api/deliberation/run")
async def post_run_deliberation(request: Request):
    """Ajanlar arası müzakere oturumunu başlatır."""
    try:
        data = await request.json()
    except Exception:
        data = {}

    spec_data = data.get("spec")
    if not spec_data:
        specs = getattr(hub, "uploaded_specs", [])
        latest_spec = specs[0] if specs else {}
        title = data.get("title") or latest_spec.get("title") or tx("Müşteri Müzakere Toplantısı")
        notes = data.get("prompt") or latest_spec.get("meeting_notes") or ""
        spec_data = {
            "title": title,
            "meeting_notes": notes,
            "key_requirements": latest_spec.get("key_requirements", [])
        }

    proj_path = hub.projects.get(hub.active_project_id, {}).get("path")
    session = await hub.deliberation_engine.run_deliberation(spec_data, proj_path, delay_between_messages=0.4)
    return JSONResponse(content={"session": session})


@app.get("/api/deliberation/latest")
async def get_latest_deliberation():
    """En son yapılan müzakere oturumunu döner."""
    session = hub.deliberation_engine.get_latest_session()
    return JSONResponse(content={"session": session})


@app.post("/api/jira/issues/{issue_id}/audit")
async def post_issue_audit(issue_id: str, request: Request):
    """Jira görevine bağımsız denetim notu (audit trail) ekler."""
    data = await request.json()
    entry = await hub.record_task_audit(
        issue_id=issue_id,
        agent_id=data.get("agent_id", "USER"),
        action=data.get("action", "USER_NOTE"),
        notes=data.get("notes", ""),
        files_affected=data.get("files_affected")
    )
    return JSONResponse(content={"audit_entry": entry})


# ---------------------------------------------------------------------------
# G2: Claude köprüsü — tam etkileşim günlüğü (K2), başsız oturum (K1), transkript aynası ve kancalar (K3)
# ---------------------------------------------------------------------------
@app.get("/api/claude/log")
async def claude_log_query(run_id: Optional[str] = None, tool: Optional[str] = None, direction: Optional[str] = None, since: Optional[str] = None,
                           q: Optional[str] = None, limit: int = 200, offset: int = 0):
    """İki yönlü etkileşim günlüğü (yeniden eskiye, gövdeler kırpılmış). Tam gövde: /api/claude/log/{id}."""
    return JSONResponse(content=CL.query(hub, run_id=run_id, tool=tool, direction=direction, since=since, q=q, limit=limit, offset=offset, lite=True))


@app.get("/api/claude/log/export")
async def claude_log_export(run_id: Optional[str] = None, limit: int = 2000):
    rows = CL.query(hub, run_id=run_id, limit=limit, lite=False)["entries"]
    return PlainTextResponse(CL.export_markdown(rows), media_type="text/markdown; charset=utf-8")


@app.get("/api/claude/log/{entry_id}")
async def claude_log_entry(entry_id: str):
    e = CL.get_entry(hub, entry_id)
    if e is None:
        return JSONResponse(status_code=404, content={"error": tx("Kayıt bulunamadı: {id}", id=entry_id)})
    return JSONResponse(content=e)


def _transcript_roots() -> List[Dict[str, str]]:
    """Transkript aranacak çalışma klasörleri: FS-SC deposu (MCP oturumları burada açılır) + etkin proje klasörü."""
    roots = [{"scope": "fssc", "path": CB.REPO_ROOT}]
    ppath = project_path_for(None)
    if ppath and os.path.abspath(ppath) != CB.REPO_ROOT:
        roots.append({"scope": "project", "path": os.path.abspath(ppath)})
    return roots


def _transcript_sessions() -> List[Dict[str, Any]]:
    override = (CB.cfg(hub).get("transcripts_dir") or None)
    rows: List[Dict[str, Any]] = []
    for r in _transcript_roots():
        for s in CT.list_sessions(r["path"], override):
            rows.append({**s, "scope": r["scope"]})
    rows.sort(key=lambda s: s["modified_at"], reverse=True)
    return rows


@app.get("/api/claude/status")
async def claude_status():
    override = (CB.cfg(hub).get("transcripts_dir") or None)
    return JSONResponse(content={"bridge": CB.bridge(hub).status(), "transcripts": CT.watcher(hub).status(),
                                 "transcript_dirs": [{**r, "transcripts_dir": CT.project_transcript_dir(r["path"], override)} for r in _transcript_roots()],
                                 "log_file": CL.log_path(CL.project_path(hub)) if CL.project_path(hub) else None})


@app.post("/api/claude/start")
async def claude_start(body: Dict[str, Any] = {}):
    """Başsız Claude Code oturumu başlatır (`claude -p`); `resume` verilirse aynı oturumu sürdürür."""
    res = await CB.bridge(hub).start(prompt=(body or {}).get("prompt") or None, resume=(body or {}).get("resume") or None, max_turns=(body or {}).get("max_turns"))
    code = {"STARTED": 200, "ALREADY_RUNNING": 409, "CLI_UNAVAILABLE": 503, "START_FAILED": 500}.get(res.get("status"), 200)
    return JSONResponse(status_code=code, content=res)


@app.post("/api/claude/stop")
async def claude_stop():
    return JSONResponse(content=await CB.bridge(hub).stop())


@app.get("/api/claude/sessions")
async def claude_sessions():
    return JSONResponse(content={"sessions": CB.bridge(hub).list_sessions()})


@app.get("/api/claude/sessions/{session_id}/events")
async def claude_session_events(session_id: str, limit: int = 500):
    return JSONResponse(content={"session_id": session_id, "events": CB.bridge(hub).read_session(session_id, limit)})


@app.get("/api/claude/transcripts")
async def claude_transcripts():
    return JSONResponse(content={"sessions": _transcript_sessions(), "watching": CT.watcher(hub).status()})


@app.get("/api/claude/transcripts/{session_id}/events")
async def claude_transcript_events(session_id: str, limit: int = 400, kinds: Optional[str] = None):
    s = next((x for x in _transcript_sessions() if x["session_id"] == session_id), None)
    if s is None:
        return JSONResponse(status_code=404, content={"error": tx("Transkript bulunamadı: {id}", id=session_id)})
    kind_list = [k.strip() for k in kinds.split(",") if k.strip()] if kinds else None
    return JSONResponse(content={"session": s, **CT.session_events(s["file"], limit=limit, kinds=kind_list)})


@app.post("/api/claude/transcripts/watch")
async def claude_transcript_watch(body: Dict[str, Any] = {}):
    sid, path = (body or {}).get("session_id"), (body or {}).get("path")
    if sid and not path:
        s = next((x for x in _transcript_sessions() if x["session_id"] == sid), None)
        path = s["file"] if s else None
    if not path or not os.path.isfile(path):
        return JSONResponse(status_code=404, content={"error": tx("Transkript dosyası bulunamadı.")})
    CT.watcher(hub).watch(path, from_start=bool((body or {}).get("from_start")))
    return JSONResponse(content={"status": "WATCHING", **CT.watcher(hub).status()})


@app.post("/api/claude/transcripts/unwatch")
async def claude_transcript_unwatch(body: Dict[str, Any] = {}):
    path = (body or {}).get("path")
    if path:
        CT.watcher(hub).unwatch(path)
    return JSONResponse(content={"status": "OK", **CT.watcher(hub).status()})


@app.post("/api/claude/hook")
async def claude_hook(body: Dict[str, Any] = {}):
    """Claude Code kancaları (SessionStart/PreToolUse/PostToolUse/Stop → scripts/claude_hook.py). Olay günlüğe yazılır, transkript izlenir."""
    body = body or {}
    event = str(body.get("hook_event_name") or body.get("event") or "hook")
    tool = str(body.get("tool_name") or event)
    tin = body.get("tool_input") if isinstance(body.get("tool_input"), dict) else None
    await CL.record(hub, direction="client", tool=tool, run_id=(tin or {}).get("run_id"), status=event, session_id=body.get("session_id"),
                    args=tin, result=body.get("tool_response"), text=body.get("prompt") or body.get("last_assistant_message"))
    tp = body.get("transcript_path")
    if tp and os.path.isfile(str(tp)) and CB.cfg(hub).get("auto_watch", True):
        CT.watcher(hub).watch(str(tp))
    return JSONResponse(content={"status": "OK", "event": event, "watching": CT.watcher(hub).status()["watching"]})


@app.get("/api/settings/claude")
async def get_claude_settings():
    return JSONResponse(content={"claude": CB.cfg(hub), "cli": CB.cli_status(CB.cfg(hub)["cli"])})


@app.post("/api/settings/claude")
async def update_claude_settings(body: Dict[str, Any] = {}):
    await hub.update_settings({"claude": body or {}})
    auto = CB.bridge(hub).sync_auto_runner()
    return JSONResponse(content={"claude": CB.cfg(hub), "cli": CB.cli_status(CB.cfg(hub)["cli"], use_cache=False), "auto_runner": auto})


def _desktop_registration() -> Dict[str, Any]:
    """Claude Desktop yapılandırmasında FS-SC MCP kaydı var mı? (salt okunur)"""
    path = os.path.join(os.environ.get("APPDATA", ""), "Claude", "claude_desktop_config.json")
    out: Dict[str, Any] = {"config_path": path, "exists": os.path.isfile(path), "registered": False, "port": None}
    try:
        with open(path, "r", encoding="utf-8") as f:
            entry = (json.load(f).get("mcpServers") or {}).get("fssc-visual-observer")
        if entry:
            out["registered"] = True
            out["port"] = (entry.get("env") or {}).get("OBSERVER_PORT")
    except Exception:
        pass
    return out


@app.get("/api/server/info")
async def server_info():
    """Çalışan sunucunun kimliği: süreç, kip (web | stdio-embedded ...), başlangıç, git HEAD ve kodun başlangıçtan sonra değişip değişmediği."""
    return JSONResponse(content=await asyncio.to_thread(_server_info))


@app.get("/api/data/health")
async def data_health():
    """Veri dayanıklılığı: bütünlük uyarıları (bir koleksiyon anlık görüntü zirvesinin yarısından fazla küçüldüyse) ve etkin projenin anlık görüntüleri."""
    from . import durability as DUR
    path = (hub.projects.get(hub.active_project_id) or {}).get("path") or ""
    live = await asyncio.to_thread(DUR.integrity_warnings, path) if path else []
    snaps = await asyncio.to_thread(DUR.list_snapshots, path) if path else []
    return JSONResponse(content={"project_id": hub.active_project_id, "warnings": live, "startup_warnings": hub.data_warnings,
                                 "snapshots": [{k: s.get(k) for k in ("name", "reason", "created_at", "counts")} for s in snaps[:50]]})


@app.post("/api/data/snapshots")
async def data_snapshot_create(body: Dict[str, Any] = {}):
    """Etkin projenin durum dosyalarının anlık görüntüsünü şimdi alır (içerik son görüntüyle aynıysa yeni görüntü yazılmaz)."""
    path = (hub.projects.get(hub.active_project_id) or {}).get("path") or ""
    if not path:
        return JSONResponse(status_code=400, content={"error": tx("Etkin proje klasörü yok.")})
    from . import durability as DUR
    name = await asyncio.to_thread(DUR.snapshot_workspace, path, str((body or {}).get("reason") or "manual"))
    return JSONResponse(content={"status": "OK", "snapshot": name, "unchanged": name is None})


@app.post("/api/data/snapshots/{name}/restore")
async def data_snapshot_restore(name: str, body: Dict[str, Any] = {}):
    """Anlık görüntüyü geri yükler (önce 'pre-restore' görüntüsü alınır); `files` verilirse yalnızca onlar. Süren koşu varsa reddedilir."""
    if hub.active_run_id:
        return JSONResponse(status_code=409, content={"error": tx("Süren bir koşu var; geri yüklemeden önce koşuyu bitirin ya da iptal edin.")})
    files = (body or {}).get("files")
    try:
        restored = await hub.restore_snapshot(name, files if isinstance(files, list) else None)
    except KeyError:
        return JSONResponse(status_code=404, content={"error": tx("Anlık görüntü bulunamadı: {name}", name=name)})
    return JSONResponse(content={"status": "OK", "restored": restored})


@app.post("/api/runner/check-now")
async def runner_check_now():
    """Bekçinin yoklamasını şimdi çalıştırır (otomatik runner açıksa iş varsa başsız oturum başlatır); sonucu ve takvimi döner."""
    from . import driver as DRV
    state = await CB.bridge(hub).auto_tick()
    return JSONResponse(content={"auto_state": state, "schedule": DRV.runner_schedule(hub)}, media_type="application/json")


def _file_error(e) -> JSONResponse:
    return JSONResponse(status_code=getattr(e, "status_code", 400), content={"error": str(e)})


@app.get("/api/usage/tokens")
async def usage_tokens():
    """Gerçek token kullanımı (Claude transkriptlerindeki `usage`) ve panodaki tahminle karşılaştırması; ajan ve koşu kırılımı."""
    from . import token_usage as TU
    return JSONResponse(content=await asyncio.to_thread(TU.summarize, hub))


@app.get("/api/project/docs")
async def project_docs():
    """Etkin projenin dökümanları (docs), kök belgeleri ve test dosyaları (salt okunur liste)."""
    from . import project_files as PF
    return JSONResponse(content=await asyncio.to_thread(PF.list_documents, hub))


@app.get("/api/project/file")
async def project_file(path: str = ""):
    """Proje içindeki bir döküman/test dosyasının içeriği; test dosyalarında sözel senaryo listesi ve kabul kriteri anmaları da gelir."""
    from . import project_files as PF
    try:
        return JSONResponse(content=await asyncio.to_thread(PF.read_document, hub, path))
    except PF.FileAccessError as e:
        return _file_error(e)


@app.post("/api/project/resume")
async def project_resume():
    """Sprint bütçesi yüzünden duran projeyi sürdürür (bütçe yeni sprinte izin veriyorsa). Hâlâ doluysa 409: önce max_sprints bütçesi artırılmalı."""
    from . import meetings as M
    from . import sprint as SP
    from . import sprint_flow as SPF
    st = SP.ensure_state(hub)
    limit = min(SP.cfg(hub)["max_sprints"], M.autonomy(hub)["budget"]["max_sprints"])
    if st.get("project_status") != "PAUSED":
        return JSONResponse(content={"status": "OK", "resumed": False, "project_status": st.get("project_status"), "sprints": len(st["sprints"]), "limit": limit})
    if await SPF.resume_if_budget_allows(hub):
        return JSONResponse(content={"status": "OK", "resumed": True, "project_status": "ACTIVE", "sprints": len(st["sprints"]), "limit": limit})
    return JSONResponse(status_code=409, content={"error": tx("Sprint bütçesi dolu ({used}/{limit}); önce max_sprints bütçesini artırın.", used=len(st['sprints']), limit=limit), "sprints": len(st["sprints"]), "limit": limit})


@app.post("/api/backlog/dedupe")
async def backlog_dedupe(apply: bool = False):
    """Aynı bulgudan çıkan kopya backlog maddeleri: `apply=false` yalnızca listeler, `apply=true` kopyaları ana maddede birleştirir."""
    from . import sprint as SP
    merged = SP.merge_duplicates(hub, apply=apply)
    if apply and merged:
        await hub.broadcast({"type": "JIRA_UPDATED"})
    return {"status": "OK", "applied": apply, "duplicates": merged}


@app.get("/api/acceptance-criteria")
async def acceptance_criteria_endpoint(ids: str = ""):
    """Kabul kriteri kimliklerinin metni (ajanlar kullanıcıya sormadan buradan alır). `ids` virgüllü; boşsa geçerli adımın kriterleri."""
    from . import sprint as SP
    return JSONResponse(content={"criteria": SP.ac_lookup(hub, [x for x in ids.split(",") if x.strip()])})


@app.get("/api/project/tree")
async def project_tree(path: str = ""):
    """Dosya gezgini: proje klasöründe tek düzey listeleme (salt okunur)."""
    from . import project_files as PF
    try:
        return JSONResponse(content=await asyncio.to_thread(PF.list_dir, hub, path))
    except PF.FileAccessError as e:
        return _file_error(e)


@app.get("/api/project/commit/{sha}")
async def project_commit(sha: str):
    """Commit ayrıntısı: mesaj, yazar, değişen dosyalar (+/−) ve yama."""
    from . import project_files as PF
    try:
        return JSONResponse(content=await asyncio.to_thread(PF.commit_detail, hub, sha))
    except (PF.FileAccessError, subprocess.TimeoutExpired) as e:
        return _file_error(e) if isinstance(e, PF.FileAccessError) else JSONResponse(status_code=504, content={"error": tx("git zaman aşımı")})


@app.get("/api/runner/schedule")
async def runner_schedule_endpoint():
    """Koşu bekçisi takvimi: aralıklar (etkin / duraklatılmış), izlenen iş, sonraki yoklama. Ayarlar: POST /api/settings/runner."""
    from . import driver as DRV
    return JSONResponse(content=DRV.runner_schedule(hub))


@app.get("/api/runner/setup")
async def runner_setup():
    """G3: sürücü kurulum durumu — Desktop kaydı, CLI, otomatik runner, runner son görülme ve ne yapılacağı."""
    from . import driver as DRV
    b = CB.bridge(hub)
    st = b.status()
    reg = _desktop_registration()
    cw = DRV.claimable_work(hub)
    info = await asyncio.to_thread(_server_info)
    steps = [
        {"key": "server", "ok": True, "text": tx("FS-SC sunucusu çalışıyor (port {port}, pid {pid})", port=SERVER_PORT, pid=info['pid'])},
        {"key": "server_host", "ok": not info["hosted_in_claude_session"],
         "text": tx("Sunucu bağımsız süreçte (Claude oturumu kapanınca koşu düşmez)") if not info["hosted_in_claude_session"]
         else tx("Sunucu bir Claude oturumunun içinde çalışıyor: o oturum kapanırsa pano ve koşu kesilir"),
         "fix": "powershell -ExecutionPolicy Bypass -File scripts\\fssc.ps1 start -Background -NoBrowser"},
        {"key": "code_fresh", "ok": not info["code_stale"],
         "text": tx("Sunucu güncel kodla çalışıyor") if not info["code_stale"] else tx("Sunucu ESKİ kodla çalışıyor ({n}+ dosya başlangıçtan sonra değişti)", n=len(info['changed_files'])),
         "fix": "powershell -ExecutionPolicy Bypass -File scripts\\fssc.ps1 stop; powershell -ExecutionPolicy Bypass -File scripts\\fssc.ps1 start -Background -NoBrowser"},
        {"key": "desktop", "ok": reg["registered"] and str(reg.get("port")) == str(SERVER_PORT),
         "text": tx("Claude Desktop'a MCP kaydı (Chat ve Code sekmeleri bu sunucuyu görür)"),
         "fix": "powershell -ExecutionPolicy Bypass -File scripts\\fssc.ps1 register-desktop -Restart"},
        {"key": "cli", "ok": bool(st["cli"]["ok"]), "text": tx("Claude Code CLI (panodan başsız başlatma ve otomatik runner için)"),
         "fix": st["cli"].get("install_hint")},
        {"key": "auto_runner", "ok": bool(st["auto_runner"]["enabled"]), "text": tx("Otomatik runner: iş varken sunucu kendisi Claude oturumu açar"),
         "fix": tx("Başlat & Bağlan sekmesinde 'Otomatik runner' anahtarını aç (CLI gerekir)")},
        {"key": "scheduled_task", "ok": None, "text": tx("Alternatif: Claude Desktop Code sekmesinde yerel zamanlanmış görev (10 dk)"),
         "fix": "powershell -ExecutionPolicy Bypass -File scripts\\fssc.ps1 runner prompt"},
    ]
    return JSONResponse(content={"desktop": reg, "cli": st["cli"], "auto_runner": st["auto_runner"], "bridge_running": bool(st["running"]),
                                 "runner": DRV.runner_status(hub), "claimable": cw, "steps": steps, "server_port": SERVER_PORT})


# ---------------------------------------------------------------------------
# Claude / Antigravity Tarafından Çağrılan MCP Araçları (Tools)
# ---------------------------------------------------------------------------
@mcp.tool()
async def emit_agent_event(
    trace_id: str,
    from_agent: str,
    to_agent: str,
    action: str,
    status: str = "SUCCESS",
    payload: str = "{}",
    current_file: str = "",
    tokens_used: int = 0
) -> str:
    """Publishes data transfer between agents, error reports and approvals to the dashboard."""
    try:
        parsed_payload = json.loads(payload) if isinstance(payload, str) and payload.startswith(("{", "[")) else {"raw": payload}
    except Exception:
        parsed_payload = {"raw": payload}

    await hub.record_event(
        trace_id=trace_id,
        from_agent=from_agent,
        to_agent=to_agent,
        action=action,
        status=status,
        payload=parsed_payload,
        current_file=current_file if current_file else None,
        tokens_used=tokens_used
    )
    return f"OK: Event '{action}' from {from_agent} to {to_agent} recorded (Status: {status})."


@mcp.tool()
async def update_task_state(
    task_id: str,
    new_state: str,
    title: str = "",
    assignee: str = "",
    priority: str = "P1",
    details: str = ""
) -> str:
    """Updates the state and assignee of a task on the Kanban / Jira board."""
    task = await hub.update_task(
        task_id=task_id,
        new_state=new_state,
        title=title if title else None,
        assignee=assignee if assignee else None,
        priority=priority,
        details=details if details else None
    )
    return f"OK: Task {task_id} moved to {task['state']} (Assignee: {task['assignee']})."


async def _run_playwright_tool(target_url: str, scenario: str, username: str, password: str, role: str) -> Dict[str, Any]:
    """`run_playwright_e2e` aracının işi (MCP aracı ve hafif stdio proxy'nin REST ikizi `/api/mcp/playwright` ortak kullanır)."""
    credentials = {"username": username, "password": password, "role": role} if username else None
    result = await run_playwright_e2e_tests(target_url=target_url, test_scenario=scenario, credentials=credentials,
                                             project_dir=project_path_for(None), project_id=hub.active_project_id)
    await hub.add_playwright_report(result)
    return result


@app.post("/api/mcp/playwright")
async def mcp_playwright(body: Dict[str, Any] = {}):
    """Hafif stdio proxy'nin `run_playwright_e2e` aracı için: testi bekleyerek koşar, özetini döner."""
    b = body or {}
    result = await _run_playwright_tool(b.get("target_url") or "http://127.0.0.1:8099", b.get("scenario") or "Canlı Kullanıcı E2E Akış Testi",
                                        b.get("username") or "", b.get("password") or "", b.get("role") or "USER")
    return JSONResponse(content={"status": result.get("status"), "screenshots": result.get("screenshots", [])})


@app.post("/api/agents/metric")
async def post_agent_metric(body: Dict[str, Any] = {}):
    """Hafif stdio proxy'nin `report_agent_metric` aracı için ajan telemetrisi güncelleme."""
    b = body or {}
    if not b.get("agent_name"):
        return JSONResponse(status_code=400, content={"error": tx("agent_name gerekli")})
    await hub.update_agent_metric(agent_name=b["agent_name"], tokens_in=int(b.get("tokens_in") or 0), tokens_out=int(b.get("tokens_out") or 0),
                                  active_file=b.get("active_file") or None, latency_ms=float(b.get("latency_ms") or 0.0), status=b.get("status") or "WORKING")
    return JSONResponse(content={"status": "OK"})


@mcp.tool()
async def run_playwright_e2e(
    target_url: str = "http://127.0.0.1:8099",
    scenario: str = "Canlı Kullanıcı E2E Akış Testi",
    username: str = "",
    password: str = "",
    role: str = "USER"
) -> str:
    """Tests the application in a real Chromium browser with Playwright and saves the screenshots to the dashboard."""
    result = await _run_playwright_tool(target_url, scenario, username, password, role)
    return f"OK: Playwright E2E test completed (Status: {result['status']}, Screenshots: {len(result['screenshots'])}, User: {username or 'Guest'})."


@mcp.tool()
async def report_agent_metric(
    agent_name: str,
    tokens_in: int = 0,
    tokens_out: int = 0,
    active_file: str = "",
    latency_ms: float = 0.0,
    status: str = "WORKING"
) -> str:
    """Reports the agent's live status, token usage and active file to the telemetry panel."""
    await hub.update_agent_metric(
        agent_name=agent_name,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        active_file=active_file if active_file else None,
        latency_ms=latency_ms,
        status=status
    )
    return f"OK: Telemetry metric recorded for {agent_name}."


@mcp.tool()
async def get_mesh_topology() -> str:
    """Returns the live state of the agent network, the active tasks and a metric summary."""
    snapshot = hub.get_snapshot()
    return json.dumps(snapshot, indent=2)


@mcp.tool()
async def reset_mesh_state() -> str:
    """Resets the telemetry board and its history."""
    await hub.reset()
    return "OK: Visual mesh state and event history reset."


# ---------------------------------------------------------------------------
# MCP Araçları — Çekme (pull) modeli: Claude Desktop / Antigravity adımları kendi modeliyle üretir
# ---------------------------------------------------------------------------
@mcp.tool()
async def start_pipeline_run(
    project_id: str = "",
    steps: Optional[List[int]] = None,
    custom_prompt: str = "",
    client_name: str = "",
    force_new: bool = False,
    ctx: Context = None,
) -> RunInfo:
    """Starts a software-company pipeline run (idempotent: returns the active run if there is one). Empty steps = all of 1-10.
    If project_id is empty the active project of the dashboard is used. Then enter the loop with get_next_step(run_id)."""
    try:
        result = await runs_api().start_run(
            project_id=project_id or None,
            steps=steps or [],
            engine="mcp_client",
            custom_prompt=custom_prompt,
            client=_client_info(ctx, client_name),
            force_new=force_new,
        )
    except RunsApiError as e:
        raise _tool_error(e)
    return RunInfo(**{**result, "run": compact_run(result.get("run") or {})})


@mcp.tool()
async def claim_work(client_name: str = "", ctx: Context = None) -> ClaimResult:
    """First call of a runner (scheduled task). If work is waiting it returns the run and the lease (status CLAIMED -> get_next_step);
    if there is no work it returns IDLE, and BLOCKED if the sprint/run waits for a manager decision: in both cases write the reason in one line and end the session (no wasted spend)."""
    try:
        return ClaimResult(**await runs_api().claim_work(_client_info(ctx, client_name)))
    except RunsApiError as e:
        raise _tool_error(e)


@mcp.tool()
async def get_activity_feed(limit: int = 30) -> str:
    """Returns the team's recent activity as readable text: project/sprint state, spend, open questions, runner state and recent events
    (steps, messages between agents, verification results). The answer to 'what is going on in FS-SC?'."""
    return (await runs_api().get_activity(limit)).get("markdown", "")


@mcp.tool()
async def get_runner_schedule() -> str:
    """Run-watchdog schedule (the single source for creating/updating a scheduled task): `interval_minutes` is the polling interval that applies now (paused_interval_min if the app is paused, otherwise active_interval_min), `suggested_cron` is its cron equivalent, `job` is the watched run (state, idle time, stalled or not), `enabled` tells whether the server's own automatic runner is on. If you have scheduled-task tools (create_scheduled_task / update_scheduled_task) set the task's interval to this value."""
    return json.dumps(await runs_api().get_runner_schedule(), ensure_ascii=False, indent=2, default=str)


@mcp.tool()
async def get_acceptance_criteria(ac_ids: str = "") -> str:
    """Returns the TEXT of acceptance-criterion ids from the server (e.g. "AC-42,AC-43"; if empty, the criteria of the current step). Do NOT ask the user for the criterion text; take it from here."""
    from . import sprint as SP
    return json.dumps({"criteria": SP.ac_lookup(hub, [x for x in str(ac_ids).split(",") if x.strip()])}, ensure_ascii=False, indent=2, default=str)


@mcp.tool()
async def get_sprint_state() -> str:
    """Summary of the active sprint: state, goal, spend and budget, carried-over items, blocking reason, pending review, runner state (JSON)."""
    return json.dumps(await runs_api().get_sprint_state(), ensure_ascii=False, indent=2, default=str)


@mcp.tool()
async def list_questions(status: str = "") -> str:
    """Lists the question queue (OPEN | ANSWERED | DEFAULTED | OVERRIDDEN). Each question has a category, options, a recommended answer and whether it is blocking."""
    return json.dumps(await runs_api().list_questions(status or None), ensure_ascii=False, indent=2, default=str)


@mcp.tool()
async def answer_question(question_id: str, answer: str) -> str:
    """Answers a non-technology (NOT blocking) question on behalf of the manager; answer is the option key (e.g. A). A different answer to a DEFAULTED question overrides it.
    TECHNOLOGY and EXTERNAL_ACTION questions cannot be answered with this tool: the manager answers them in the dashboard."""
    try:
        res = await runs_api().answer_question(question_id, answer)
    except RunsApiError as e:
        raise _tool_error(e)
    return f"OK: {question_id} → {res.get('question', {}).get('status', res.get('status'))}"


@mcp.tool()
async def get_tech_requirements() -> str:
    """Technology requirements: items (SPECIFIED/MISSING/CONTRADICTORY), source quotes, approval state. Approval is not given with this tool (only the manager, in the dashboard)."""
    return json.dumps(await runs_api().get_tech_requirements(), ensure_ascii=False, indent=2, default=str)


@mcp.tool()
async def add_manager_input(text: str, title: str = "Yönetici girdisi", urgent: bool = False, ctx: Context = None) -> str:
    """Lets the manager leave a note in the vault from the chat: it counts as an upload, queues the review and (in sprint mode) starts the work."""
    try:
        res = await runs_api().add_manager_input(text, title, tx("Yönetici"), urgent, client=_client_info(ctx))
    except RunsApiError as e:
        raise _tool_error(e)
    return f"{res.get('status')}: {res.get('message', '')}"


@mcp.tool()
async def get_next_step(run_id: str, ctx: Context = None) -> NextStep:
    """Returns the next step of the run and its prompt: status STEP -> produce with system_prompt/user_context/output_contract;
    WAITING_APPROVAL -> call wait_for_approval; RUN_COMPLETE -> finish. The same step is returned again until a submit succeeds."""
    try:
        result = await runs_api().next_step(run_id, client=_client_info(ctx))
    except RunsApiError as e:
        raise _tool_error(e)
    return NextStep(**result)


@mcp.tool()
async def submit_step_result(
    run_id: str,
    order: int,
    result_json: str,
    tokens_in: int = 0,
    tokens_out: int = 0,
    ctx: Context = None,
) -> SubmitResult:
    """Submits the output of the step (only the output_contract JSON envelope). The server writes the files and publishes the events.
    status NEXT -> get_next_step; WAITING_APPROVAL -> wait_for_approval; REJECTED -> fix according to validation_errors and send again."""
    try:
        result = await runs_api().submit_result(run_id, order, result_json, tokens_in, tokens_out, client=_client_info(ctx))
    except RunsApiError as e:
        raise _tool_error(e)
    return SubmitResult(**result)


@mcp.tool()
async def wait_for_approval(run_id: str, timeout_s: int = 30, ctx: Context = None) -> ApprovalStatus:
    """Waits up to timeout_s (<=45) seconds for the user to approve the step in the dashboard.
    If STILL_WAITING is returned call again; if APPROVED is returned continue with get_next_step."""
    try:
        result = await runs_api().wait_approval(run_id, float(timeout_s), client=_client_info(ctx))
    except RunsApiError as e:
        raise _tool_error(e)
    return ApprovalStatus(**result)


@mcp.tool()
async def report_thinking(run_id: str, agent_id: str, text: str, what_doing: str = "", what_next: str = "", ctx: Context = None) -> str:
    """Before starting a step, publishes to the live stream a short 1-2 sentence plan note describing what the agent will do in this step."""
    try:
        result = await runs_api().report_thinking(run_id, agent_id, text, what_doing, what_next, client=_client_info(ctx))
    except RunsApiError as e:
        raise _tool_error(e)
    return f"OK: thinking recorded for {result.get('agent_id')}"


@mcp.tool()
async def cancel_pipeline_run(run_id: str, reason: str = "") -> str:
    """Cancels the running run."""
    try:
        result = await runs_api().cancel_run(run_id, reason or "mcp-client")
    except RunsApiError as e:
        raise _tool_error(e)
    return f"OK: run {run_id} → {result.get('status')}"


@mcp.tool()
async def list_runs(project_id: str = "") -> RunList:
    """Lists the run history (state, steps, engine)."""
    res = await runs_api().list_runs(project_id or None)
    return RunList(**{**res, "runs": [compact_run(r) for r in (res.get("runs") or [])]})


@mcp.tool()
async def open_deliberation(spec_id: str = "", title: str = "", ctx: Context = None) -> DeliberationInfo:
    """Opens a deliberation-room session between agents; returns the participants, their prompts and the turn order."""
    try:
        return DeliberationInfo(**await runs_api().open_deliberation(spec_id, title, client=_client_info(ctx)))
    except RunsApiError as e:
        raise _tool_error(e)


@mcp.tool()
async def deliberation_turn(session_id: str, agent_id: str, message: str, sentiment: str = "AGREE", proposals_json: str = "", ctx: Context = None) -> str:
    """Records an agent's statement at the deliberation table (sentiment: PROPOSAL | CRITIQUE | AGREE | CONSENSUS).
    In the ARCHITECT turn give 2-3 alternative plans with proposals_json: [{"id":"A","title":..,"summary":..,"stack":[..],"pros":[..],"cons":[..],"risk":"LOW|MEDIUM|HIGH","recommended":true}].
    If plans were given, close_deliberation waits for the user's choice (wait_for_approval(run_id=session_id))."""
    proposals = None
    if proposals_json:
        try:
            proposals = json.loads(proposals_json)
        except Exception:
            raise ToolError(tx("proposals_json geçerli bir JSON listesi olmalı."))
    try:
        await runs_api().deliberation_turn(session_id, agent_id, message, sentiment, client=_client_info(ctx), proposals=proposals)
    except (RunsApiError, ValueError) as e:
        raise ToolError(str(e))
    return f"OK: {agent_id} spoke ({sentiment})" + (f" with {len(proposals)} plan(s)" if proposals else "")


@mcp.tool()
async def close_deliberation(session_id: str, consensus_json: str = "{}", ctx: Context = None) -> str:
    """Closes the deliberation with a consensus. consensus_json: {"chosen_plan": str, "decision": str, "agreed_stack": [..]}."""
    try:
        consensus = json.loads(consensus_json) if consensus_json else {}
    except Exception:
        consensus = {"chosen_plan": consensus_json}
    try:
        result = await runs_api().close_deliberation(session_id, consensus, client=_client_info(ctx))
    except (RunsApiError, ValueError) as e:
        raise ToolError(str(e))
    if result.get("status") in ("AWAITING_PLAN_CHOICE", "AWAITING_APPROVAL"):
        return tx("{status}: öneri yöneticiye sunuldu, nihai karar yöneticinin. wait_for_approval(run_id=\"{sid}\") çağır; "
                  "REVISE gelirse geri bildirimle yeni turlar ekleyip yeniden kapat, APPROVED gelirse onaylanan planla devam et.", status=result['status'], sid=session_id)
    return f"OK: deliberation {session_id} closed with consensus"


@mcp.tool()
async def send_cross_project_message(target_project_id: str, from_agent: str, to_agent: str, message: str) -> str:
    """Sends a message to the team of another project (e.g. Web team -> Mobile team); visible on both dashboards."""
    try:
        event = await hub.send_cross_project_message(target_project_id, from_agent, to_agent, message)
    except ValueError as e:
        raise ToolError(str(e))
    return tx("OK: {fa}@{fp} → {ta}@{tp} iletildi.", fa=event['from_agent'], fp=event['from_project'], ta=event['to_agent'], tp=event['to_project'])


@mcp.prompt()
def run_software_company(project_id: str = "", steps: str = "1-10") -> str:
    """Runs the full software-company development loop (PM -> Architect+backlog -> skeleton -> tasks (verification/fix/commit) -> QA -> E2E -> DevOps -> PO -> Docs) in this client."""
    return run_software_company_prompt(project_id, steps)


# ---------------------------------------------------------------------------
# Frontend Statik Dosyaları Sunma (Derlenmiş Dashboard)
# ---------------------------------------------------------------------------
dashboard_dist_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "dashboard", "dist"))
if os.path.isdir(dashboard_dist_dir):
    app.mount("/", StaticFiles(directory=dashboard_dist_dir, html=True), name="static")


_STARTED_AT = time.time()
_SERVER_MODE = "web"           # web | stdio-proxy | stdio-embedded | all


def _code_changed_since_start() -> List[str]:
    """Sunucu başladıktan sonra değişen kaynak dosyalar (server/**/*.py, agents/prompts/**/*.md): süreç eski kodla çalışıyor demektir."""
    root = Path(__file__).resolve().parent
    changed: List[str] = []
    try:
        for p in [*root.rglob("*.py"), *(root.parent / "agents" / "prompts").rglob("*.md")]:
            if "__pycache__" in p.parts:
                continue
            if p.stat().st_mtime > _STARTED_AT + 1:
                changed.append(str(p.relative_to(root.parent)).replace("\\", "/"))
    except OSError:
        pass
    return sorted(changed)


def _git_head() -> str:
    """Deponun HEAD kısa kimliği (7 hane). `git` ÇALIŞTIRMADAN `.git/HEAD` ve ref dosyalarından okunur: pano bunu dakikada bir yoklar ve her `git`
    süreci, konsolsuz çalışan sunucuda bir konsol penceresi açıp kapatırdı (saha: "birçok cmd ekranı açılıp kapanıyor"). Okunamazsa boş döner."""
    try:
        root = Path(__file__).resolve().parent.parent
        git_dir = root / ".git"
        if git_dir.is_file():                                              # çalışma ağacı: .git dosyası "gitdir: <yol>" der
            text = git_dir.read_text(encoding="utf-8", errors="ignore").strip()
            git_dir = (root / text.split(":", 1)[1].strip()).resolve() if text.startswith("gitdir:") else git_dir
        head = (git_dir / "HEAD").read_text(encoding="utf-8", errors="ignore").strip()
        if not head.startswith("ref:"):
            return head[:7]                                                # ayrık HEAD: içerik doğrudan commit kimliği
        ref = head.split(":", 1)[1].strip()
        common = git_dir
        if (git_dir / "commondir").is_file():                              # çalışma ağacında dallar ortak dizinde durur
            common = (git_dir / (git_dir / "commondir").read_text(encoding="utf-8", errors="ignore").strip()).resolve()
        for base in (git_dir, common):
            f = base / ref
            if f.is_file():
                return f.read_text(encoding="utf-8", errors="ignore").strip()[:7]
        packed = common / "packed-refs"
        if packed.is_file():
            for line in packed.read_text(encoding="utf-8", errors="ignore").splitlines():
                if line.endswith(" " + ref) and not line.startswith(("#", "^")):
                    return line.split(" ", 1)[0][:7]
    except (OSError, ValueError, IndexError):
        pass
    return ""


def _server_info() -> Dict[str, Any]:
    """Çalışan sunucunun kimliği: süreç, kip, başlangıç, kod güncel mi? `hosted_in_claude_session`: hub bir Claude oturumunun MCP sürecinin içinde
    (oturum kapanınca koşu düşer; saha: submit_step_result "Error executing tool")."""
    changed = _code_changed_since_start()
    return {"pid": os.getpid(), "mode": _SERVER_MODE, "host": SERVER_HOST, "port": SERVER_PORT,
            "started_at": datetime.fromtimestamp(_STARTED_AT, tz=timezone.utc).isoformat(), "uptime_s": int(time.time() - _STARTED_AT),
            "git_head": _git_head(), "code_stale": bool(changed), "changed_files": changed[:8], "hosted_in_claude_session": _SERVER_MODE == "stdio-embedded",
            "data_warnings": sum(len(v) for v in hub.data_warnings.values())}


def _state_ok(timeout: float = 1.5) -> bool:
    import urllib.request
    try:
        with urllib.request.urlopen(f"http://{SERVER_HOST}:{SERVER_PORT}/api/state", timeout=timeout) as r:
            return r.status == 200
    except Exception:
        return False


def _spawn_detached_web_server(wait_s: float = 25.0, log_path: Optional[Path] = None) -> bool:
    """MCP stdio sürecinden BAĞIMSIZ bir `--mode web` sunucusu başlatır; hazır olunca True. Hub'ı bir Claude oturumunun içinde barındırmak, oturum kapanınca
    koşuyu düşürür; bağımsız süreç oturumlardan ve uygulama yeniden başlamalarından etkilenmez. Günlük: history/server.log. Başarısızlıkta çağıran gömülü kipe düşer."""
    import subprocess
    root = Path(__file__).resolve().parent.parent
    log_path = log_path or (root / "history" / "server.log")
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        logfh = open(log_path, "ab")
    except OSError:
        return False
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1", "OBSERVER_PORT": str(SERVER_PORT)}
    base: Dict[str, Any] = dict(cwd=str(root), env=env, stdin=subprocess.DEVNULL, stdout=logfh, stderr=subprocess.STDOUT, close_fds=True)
    if sys.platform.startswith("win"):
        # DETACHED_PROCESS KULLANILMAZ: konsolsuz süreç, açtığı her konsol uygulaması (git, cmd, npm ...) için yeni bir pencere açtırır.
        # CREATE_NO_WINDOW sunucuya kendi GİZLİ konsolunu verir; alt süreçleri onu devralır (pencere yok), Claude oturumundan yine bağımsızdır.
        attempts: List[Dict[str, Any]] = [{"creationflags": CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW | CREATE_BREAKAWAY_FROM_JOB},   # iş nesnesinden kopar
                                          {"creationflags": CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW}]                            # iş nesnesi kopmaya izin vermiyorsa
    else:
        attempts = [{"start_new_session": True}]
    started = False
    for extra in attempts:
        try:
            subprocess.Popen([sys.executable, "-m", "server.main", "--mode", "web"], **base, **extra)
            started = True
            break
        except OSError:
            continue
    try:
        logfh.close()
    except OSError:
        pass
    if not started:
        return False
    deadline = time.time() + wait_s
    while time.time() < deadline:
        if _state_ok():
            return True
        time.sleep(0.4)
    return False


def is_port_in_use(port: int, host: str = "127.0.0.1") -> bool:
    """Belirtilen portun başka bir süreç (örn: çalışan web panosu) tarafından kullanılıp kullanılmadığını kontrol eder."""
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.4)
        return s.connect_ex((host, port)) == 0


# ---------------------------------------------------------------------------
# Sunucu Başlatma Yordamı
# ---------------------------------------------------------------------------
async def run_unified_server(mode: str = "all"):
    """FastAPI Web/WebSocket sunucusunu ve MCP Stdio sunucusunu eşzamanlı çalıştırır."""
    global _SERVER_MODE
    port_busy = is_port_in_use(SERVER_PORT, SERVER_HOST)
    _SERVER_MODE = mode

    if mode == "web":
        if port_busy:
            print(f"[!] Port {SERVER_PORT} zaten kullanımda. Web panosu arka planda çalışıyor: http://{SERVER_HOST}:{SERVER_PORT}")
            return
        config = uvicorn.Config(
            app=app,
            host=SERVER_HOST,
            port=SERVER_PORT,
            log_level="info",
            access_log=True
        )
        server = uvicorn.Server(config)
        print(f"[*] Visual Dashboard & API Server başlatıldı: http://{SERVER_HOST}:{SERVER_PORT}")
        print(f"[*] WebSocket Telemetri Endpoint: ws://{SERVER_HOST}:{SERVER_PORT}/ws/telemetry")
        await server.serve()

    elif mode == "stdio":
        global _PROXY_BASE_URL
        server_task = None
        if not port_busy and os.environ.get("FSSC_EMBEDDED_HUB") != "1":
            # Web sunucusu yok: hub'ı bu Claude oturumunun içinde barındırma (oturum kapanınca koşu düşer); bağımsız bir sunucu başlat ve ona köprüle.
            # Olmazsa (ya da FSSC_EMBEDDED_HUB=1) eski gömülü kip kullanılır.
            if await asyncio.to_thread(_spawn_detached_web_server):
                port_busy = True
                print(f"[*] MCP stdio: bağımsız web sunucusu başlatıldı (günlük: history/server.log)", file=sys.stderr)
        if port_busy:
            # Dashboard başka bir süreçte çalışıyor: araç çağrılarını oraya köprüle (tek hub)
            _SERVER_MODE = "stdio-proxy"
            _PROXY_BASE_URL = f"http://{SERVER_HOST}:{SERVER_PORT}"
            print(f"[*] MCP stdio: web sunucusu zaten çalışıyor, proxy modu → {_PROXY_BASE_URL}", file=sys.stderr)
        else:
            _SERVER_MODE = "stdio-embedded"
            # Bu stdio oturumu arka planda web sunucusunu da başlatsın (dashboard bu süreçten servis edilir)
            config = uvicorn.Config(
                app=app,
                host=SERVER_HOST,
                port=SERVER_PORT,
                log_level="warning",
                access_log=False
            )
            server = uvicorn.Server(config)
            server_task = asyncio.create_task(server.serve())
            print(f"[*] MCP stdio: dashboard bu süreçten servis ediliyor → http://{SERVER_HOST}:{SERVER_PORT}", file=sys.stderr)

        try:
            await mcp.run_stdio_async()
        finally:
            if _proxy_api is not None:
                try:
                    await _proxy_api.aclose()
                except Exception:
                    pass
            if server_task:
                server.should_exit = True
                await server_task

    else:  # mode == "all"
        server_task = None
        if not port_busy:
            config = uvicorn.Config(
                app=app,
                host=SERVER_HOST,
                port=SERVER_PORT,
                log_level="info",
                access_log=True
            )
            server = uvicorn.Server(config)
            server_task = asyncio.create_task(server.serve())

        try:
            await mcp.run_stdio_async()
        except (KeyboardInterrupt, SystemExit):
            pass
        finally:
            if server_task:
                server.should_exit = True
                await server_task


def main():
    parser = argparse.ArgumentParser(description="FS-SC Visual MCP Server")
    parser.add_argument(
        "--mode",
        choices=["all", "stdio", "web"],
        default="all",
        help="Sunucu çalışma modu: 'web' (yalnızca API/Dashboard), 'stdio' (MCP stdio + arka plan WS), 'all' (varsayılan)"
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        help="Geliştirme: yalnızca 'web' modunda server/ altındaki .py değişince sunucuyu otomatik yeniden başlatır. "
             "Süren koşu yeniden başlamada ABANDONED görünür, istemcinin sonraki çağrısında kaldığı yerden sürer."
    )
    args = parser.parse_args()
    if args.reload:
        if args.mode != "web":
            parser.error("--reload yalnızca --mode web ile kullanılabilir")
        # uvicorn yeniden yükleme: uygulama içe aktarma yoluyla verilmeli (süreç değişiklikte yeniden doğar)
        print(f"[*] Geliştirme modu: server/ altındaki değişiklikler sunucuyu otomatik yeniden başlatır (http://{SERVER_HOST}:{SERVER_PORT})")
        # Windows'ta uvicorn reload kipi SelectorEventLoop kurar; o döngü asyncio alt süreçlerini (npm, dotnet, git... doğrulama
        # komutları) başlatamaz (NotImplementedError). loop="none" varsayılan Proactor döngüsünü korur.
        loop_impl = "none" if sys.platform.startswith("win") else "auto"
        uvicorn.run("server.main:app", host=SERVER_HOST, port=SERVER_PORT, reload=True, loop=loop_impl,
                    reload_dirs=[str(Path(__file__).resolve().parent)], log_level="info",
                    timeout_graceful_shutdown=2)   # açık WebSocket'ler yeniden yüklemeyi bekletmesin
        return
    asyncio.run(run_unified_server(mode=args.mode))


if __name__ == "__main__":
    main()
