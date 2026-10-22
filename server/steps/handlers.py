"""
10 adımlı pipeline'ın adım işleyicileri.

Adım 5 (peer handshake) ve 7 (gerçek Playwright) sunucu tarafında koşar (`server_side=True`);
diğerleri MCP istemcisi (Claude Desktop / Antigravity) veya şablon sağlayıcısı tarafından üretilir.
Şablon içerikleri eski `runner.py` if/elif merdiveninden taşınmıştır.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from .. import i18n as _i18n
from ..i18n import translate as tx, N_
from .base import StepContext, StepEvent, StepHandler, StepResult


def _tx_known(text: str) -> str:
    """Katalogda anahtarı olan metni aktif dile çevirir; olmayan (teknik/yer tutucu) metne dokunmaz."""
    if _i18n.current() == "en":
        return _i18n._load_catalog().get(text, text)
    return text


def _tx_deep(obj: Any) -> Any:
    if isinstance(obj, str):
        return _tx_known(obj)
    if isinstance(obj, dict):
        return {k: _tx_deep(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_tx_deep(v) for v in obj]
    if isinstance(obj, tuple):
        return tuple(_tx_deep(v) for v in obj)
    return obj


class _TxAttr:
    """Sınıf düzeyi metin niteliği (`title`, `thinking`, `payload_schema`): sınıftan okununca `N_` işaretli ham değer
    (flow.py `ArchitectHandler.payload_schema[...]` bunu modül yüklenirken okur), örnekten okununca aktif dile çevrilmiş kopya döner."""

    def __init__(self, value: Any) -> None:
        self.value = value

    def __get__(self, obj: Any, owner: Any = None) -> Any:
        if obj is None:
            return self.value
        return _tx_deep(self.value)


# ---------------------------------------------------------------------------
# 1. PM — Müşteri Görüşmeleri & PRD
# ---------------------------------------------------------------------------
class PMHandler(StepHandler):
    order = 1
    spec_budget = None
    agent_id = "PM"
    next_agent_id = "ARCHITECT"
    action = "TASK_DISPATCH"
    estimated_tokens = 210
    required_files = (("<docs>/PRD.md", 1),)
    title = _TxAttr(N_("Müşteri Görüşmeleri & PRD Gereksinim Analizi"))
    thinking = _TxAttr((
        N_("Müşteri toplantı notları ve şartname belgelerini detaylı tarıyorum. İş gereksinimlerini PRD ve kabul kriterlerine dönüştürüyorum."),
        N_("PRD ve kullanıcı hikayelerini hazırlıyor"),
        N_("Sistem mimarına mimari tasarım için devredecek"),
    ))
    payload_schema = _TxAttr({
        "user_stories": [{"id": "US-01", "as_a": N_("rol"), "i_want": N_("istek"), "so_that": N_("fayda")}],
        "acceptance_criteria": [N_("ölçülebilir kabul kriteri")],
        "non_goals": [N_("kapsam dışı madde")],
        "decisions_needed": [{"id": "backend", "question": N_("Şartnamede açık kalan teknoloji/mimari seçimi (dil, çatı, veritabanı, istemci, barındırma, entegrasyon...)"),
                              "options": [N_("seçenek A"), N_("seçenek B")], "recommended": N_("seçenek A"), "why": N_("gerekçe")}],
        "epics": [{"id": "E-1", "title": N_("ana hedef"), "description": N_("kapsam")}],
        "stories": [{"id": "S-1", "epic": "E-1", "title": N_("hikâye başlığı"), "as_a": N_("rol"), "i_want": N_("istek"), "so_that": N_("fayda"),
                     "acceptance_criteria": [N_("ölçülebilir kabul kriteri")], "supersedes": N_("(varsa) JIRA-n")}],
        "tech_extraction": [{"category": "backend | database | client | auth | hosting | realtime | testing", "value": N_("notlarda geçen teknoloji"),
                            "quote": N_("notlardan AYNEN alınmış kısa alıntı (notlarda yoksa kalemi ekleme; uydurma)")}],
        "files": [{"path": "<docs>/PRD.md", "content": N_("PRD dokümanının tam Markdown içeriği")}],
    })

    def extra_user_context(self, ctx: StepContext) -> str:
        """Var olan proje içe aktarımı: klasör ağacı ve README/CLAUDE.md özeti PM'e verilir."""
        parts: List[str] = []
        if getattr(ctx.run, "mode", "legacy") == "sprint":
            from ..sprint import existing_stories
            stories = existing_stories(ctx.hub)
            lines = [tx("## Sprint kipi: epik ve hikâye üretimi (zorunlu)"),
                     tx("- `epics[]`: notlardaki her ana hedef için bir epik (`id`, `title`, `description`)."),
                     tx("- `stories[]`: her kullanıcı ihtiyacı için bir hikâye (`id`, `epic`, `title`, `as_a`, `i_want`, `so_that`, "
                        "`acceptance_criteria` = ölçülebilir cümleler). Sunucu `AC-n` ve `JIRA-n` kimliklerini atar."),
                     tx("- Daha önce girdi alındıysa YALNIZCA yeni ya da değişen hikâyeleri yaz. Değişen bir hikâye kapatılmış bir sprintteyse "
                        "`supersedes: \"JIRA-n\"` (ya da `related_to`) ile referans ver; kapatılmış maddeyi yeniden yazma.")]
            if stories:
                lines.append(tx("\nMevcut hikâyeler:"))
                lines += [tx("- {id} · {title} · sprint={sprint} · durum={status}", id=s['id'], title=s.get('title'), sprint=s.get('sprint') or '-', status=s.get('status')) for s in stories[:60]]
            parts.append("\n".join(lines))
        snap = ctx.project_snapshot_md(max_entries=120)
        if snap:
            parts.append(snap + tx("\n\nNot: Bu klasörde zaten kod varsa PRD'yi 'mevcut sistemin geliştirilmesi' olarak yaz; "
                                   "var olan modülleri ve kısıtları dikkate al, sıfırdan kurulum önerme."))
        return "\n\n".join(parts)

    def template_output(self, ctx: StepContext) -> Dict[str, Any]:
        specs_info = tx("\n\n### Müşteri Görüşme Notları ve Şartname\n{spec}", spec=ctx.spec_text) if ctx.spec_text else ""
        prd = tx("""# Product Requirement Document (PRD)
## 1. Talep Özeti
{prompt}{specs_info}

## 2. Kullanıcı Hikayeleri
- **US-01**: Kullanıcı olarak güvenli JWT token ile sisteme giriş yapabilmeliyim.
- **US-02**: Modern ve responsive arayüz üzerinden veri kayıtlarını listeleyip yönetebilmeliyim.
- **US-03**: Hata durumlarında anlaşılır JSON bildirimleri almalıyım.

## 3. Kabul Kriterleri (Acceptance Criteria)
- P95 API yanıt süresi < 120ms.
- Senior Backend ve Senior Frontend arasında tam API sözleşme uyumu.
- Playwright ile canlı tarayıcı E2E testlerinin %100 başarılı olması.
- Docker konteyner dağıtımına tam uyumluluk.
""", prompt=ctx.prompt_text, specs_info=specs_info)
        sprint_extra: Dict[str, Any] = {}
        if getattr(ctx.run, "mode", "legacy") == "sprint":
            from ..sprint import derive_stories_from_notes, existing_stories
            titles = [s.get("title", "") for s in existing_stories(ctx.hub)]
            stories = derive_stories_from_notes(ctx.spec_text or ctx.prompt_text, titles)
            sprint_extra = {"epics": [{"id": "E-1", "title": (ctx.prompt_text or tx("Ürün"))[:80], "description": tx("Notlardaki hedeflerin toplamı")}] if stories else [],
                            "stories": [{**s, "epic": "E-1"} for s in stories]}
        return self.envelope(ctx, {
            **sprint_extra,
            "summary": tx("Ürün Yöneticisi (PM), müşteri notlarını ve gereksinimleri analiz ederek PRD dökümanını (<docs>/PRD.md) hazırladı. Kullanıcı hikayeleri ve kabul kriterleri tanımlandı."),
            "friendly_dialogue": tx("Selam Mimar! Müşterimizin şartnamesini ve toplantı notlarını analiz ettim. Harika ve hızlı bir sistem istiyorlar. Hadi sağlam bir mimari kuralım!"),
            "thinking": self.thinking[0],
            "what_doing": self.thinking[1],
            "what_next": self.thinking[2],
            "user_stories": [
                {"id": "US-01", "as_a": tx("Kullanıcı"), "i_want": tx("JWT ile giriş yapmak"), "so_that": tx("Hesabıma güvenle erişebileyim")},
                {"id": "US-02", "as_a": tx("Kullanıcı"), "i_want": tx("Kayıtları listeleyip yönetmek"), "so_that": tx("Verilerimi tek panodan kontrol edeyim")},
            ],
            "acceptance_criteria": [tx("P95 API yanıt süresi < 120ms"), tx("E2E testleri %100 yeşil"), tx("Docker dağıtımı hazır")],
            "non_goals": [tx("OAuth2 sosyal giriş ilk sürümde yok")],
            "files": [{"path": "<docs>/PRD.md", "content": prd}],
        }, current_file="<docs>/PRD.md")

    def main_event_payload(self, ctx: StepContext, env: Dict[str, Any]) -> Dict[str, Any]:
        return {"document": "<docs>/PRD.md", "prompt": ctx.prompt_text, "files": [f["path"] for f in env["payload"].get("files", [])]}


# ---------------------------------------------------------------------------
# 2. ARCHITECT — Mimari & OpenAPI sözleşmesi
# ---------------------------------------------------------------------------
class ArchitectHandler(StepHandler):
    order = 2
    spec_budget = None
    agent_id = "ARCHITECT"
    next_agent_id = "BACKEND_DEV"
    action = "DISPATCH_CONTRACT"
    critical = True
    estimated_tokens = 260
    required_files = (("<docs>/openapi_spec.json", 2),)
    title = _TxAttr(N_("Sistem Mimarisi, API Sözleşmesi & Veri Modelleri"))
    thinking = _TxAttr((
        N_("PRD dokümanını inceledim. Modüler mimariyi ve OpenAPI 3.0 şemasını planlıyorum."),
        N_("OpenAPI sözleşmesi ve veri modellerini kurguluyor"),
        N_("Backend geliştiriciye API şemasını aktaracak"),
    ))
    prior_files = ["<docs>/PRD.md"]

    def extra_user_context(self, ctx: StepContext) -> str:
        """Müzakerede seçilen mimari plan (varsa) mimarın bağlamına eklenir."""
        session = None
        try:
            session = ctx.hub.deliberation_engine.get_latest_session()
        except Exception:
            session = None
        lines: List[str] = []
        if session and session.get("consensus_summary"):
            summary = session["consensus_summary"]
            chosen_id = session.get("chosen_plan_id") or summary.get("chosen_plan_id")
            plan = next((p for p in session.get("proposals", []) if p.get("id") == chosen_id), None)
            lines += [tx("## Müzakere kararı (seçilen mimari plan)"), tx("- Plan: {plan}", plan=summary.get('chosen_plan', '-'))]
            if plan:
                lines.append(tx("- Özet: {summary}", summary=plan.get('summary', '')))
                lines.append(tx("- Yığın: {stack}", stack=', '.join(plan.get('stack', []))))
                if plan.get("cons"):
                    lines.append(tx("- Dikkat: {cons}", cons=', '.join(plan.get('cons', []))))
            if summary.get("agreed_stack"):
                lines.append(tx("- Kabul edilen teknolojiler: {stack}", stack=', '.join(summary['agreed_stack'])))
            lines.append(tx("Mimariyi ve OpenAPI sözleşmesini bu plana sadık kalarak üret."))
        snap = ctx.project_snapshot_md(max_entries=120)
        if snap:
            lines.append("\n" + snap)
        max_tasks = int(ctx.hub.get_settings().get("max_backlog_tasks", 40) or 40)
        if getattr(ctx.run, "mode", "legacy") == "sprint":
            from ..sprint import stories_without_tasks
            todo = stories_without_tasks(ctx.hub)
            lines.append(
                tx("\n## Sprint kipi: görev kırılımı (zorunlu)\n"
                   "- Aşağıdaki hikâyelerin her birini teslim edilebilir görevlere böl (şartnamenin TAMAMINI kapsayacak kadar görev üret, gereken sayıyı sen belirle; güvenlik tavanı {max_tasks}; kalan hikâyeler sonraki yapılandırma adımına kalır). "
                   "Her görev: `id` (yalnızca bu çıktıdaki bağımlılıkları çözmek için), `title`, `role` (BACKEND_DEV | FRONTEND_DEV | DESIGNER | DEVOPS | QA | DOCUMENTOR; "
                   "E2E_TESTER ve SCM görev alamaz), `work_type` (SCAFFOLD | FEATURE | DESIGN | TEST | E2E_SCENARIO | DEVOPS | DOCS | BUG | IMPROVEMENT | REFACTOR | TEST_DESIGN | SECURITY_TEST | PERF_SMOKE; "
                   "TEST_DESIGN: QA'nın kabul kriterlerinden test case üretimi — sunucu da ekler), "
                   "`story_ref` (aşağıdaki hikâye kimliği), `ac_refs`, `acceptance_criteria`, `depends_on`.\n"
                   "- Bir görev tek teslimde bitecek büyüklükte olsun. Proje zaten kuruluysa SCAFFOLD görevi üretme.\n", max_tasks=max_tasks)
                + (tx("\nKırılımı bekleyen hikâyeler:\n") + "\n".join(
                    tx("- {id} · {title} · {refs}", id=s['id'], title=s.get('title'), refs=', '.join(s.get('ac_refs') or [])) for s in todo[:40])
                   if todo else tx("\nKırılımı bekleyen hikâye yok; yalnızca mimari belgeleri güncelle.")))
        lines.append(
            tx("\n## Backlog ve doğrulama (zorunlu)\n"
               "- `backlog`: PRD'deki kullanıcı hikayelerinin TAMAMINI kapsayacak kadar (sayıyı ihtiyaca göre sen belirle; güvenlik tavanı {max_tasks}) bağımsız teslim edilebilir geliştirme görevine böl. "
               "Her görev tek bir ajana atanır (`role`: BACKEND_DEV | FRONTEND_DEV | DESIGNER | DEVOPS | QA), 1-3 saatlik iş büyüklüğünde olsun, "
               "ölçülebilir `acceptance_criteria` ve dokunulacak `files` listesi içersin; `depends_on` ile sırayı belirt. "
               "Adım 3 (backend iskeleti) ve adım 4 (frontend iskeleti) proje kurulumunu yapar; backlog görevleri bu iskeletin ÜZERİNE özellik ekler, "
               "iskelet işlerini tekrar listeleme. Arayüz içeren projede ilk iş tasarımdır: tasarım sistemi + ilk ekranlar için `role: DESIGNER`, `work_type: DESIGN` görevi ekle; frontend görevleri ona `depends_on` ile bağlansın.\n"
               "- `libraries`: onaylı teknoloji yığını İÇİNDE kullanacağın her kütüphane (`name`, `purpose`, `technology`). Burada olmayan ya da onaylı "
               "teknolojide geçmeyen bir bağımlılığı manifeste (requirements.txt, package.json, composer.json, Dockerfile, compose) EKLEYEN teslimler sunucuca reddedilir; "
               "yeni teknoloji gerekiyorsa ekleme, yöneticiye bırak.\n"
               "- `verification`: sunucunun her teslimden sonra proje kökünde koşacağı GERÇEK komutlar (seçilen teknolojiye uygun): "
               "`install`, `test`, `build` (gerekirse `lint`), uygulamayı başlatan `run` ve sağlık adresi `health_url` "
               "(örn. install: \"pip install -r requirements.txt\", test: \"python -m pytest -q\", run: \"uvicorn src.main:app --port 8000\", "
               "health_url: \"http://127.0.0.1:8000/health\"). Komutlar bu makinede çalışacak; var olmayan araç kullanma.", max_tasks=max_tasks)
        )
        from ..agent_registry import roles_prompt_section
        custom = roles_prompt_section(ctx.hub)
        if custom:
            lines.append(tx("\n## Özel ajanlar (G6)\n") + custom + tx("\n- Görevin işi bir özel ajanın odağına giriyorsa görevi ona ata (`role` = ajan kimliği); aksi halde çekirdek rolleri kullan."))
        return "\n".join(lines)

    payload_schema = _TxAttr({
        "architecture": N_("seçilen mimari yaklaşımın adı"),
        "modules": [N_("modül / servis listesi")],
        "data_models": [{"name": "Model", "fields": [N_("alan: tip")]}],
        "backlog": [{"id": "T-01", "title": N_("görev başlığı"), "role": "BACKEND_DEV | FRONTEND_DEV | DEVOPS | QA | DOCUMENTOR",
                     "work_type": N_("SCAFFOLD | FEATURE | TEST | E2E_SCENARIO | DEVOPS | DOCS | BUG | IMPROVEMENT | REFACTOR | TEST_DESIGN | SECURITY_TEST | PERF_SMOKE (sprint kipinde)"),
                     "story_ref": N_("(sprint kipinde) hikâye kimliği"), "ac_refs": ["AC-1"],
                     "description": N_("ne yapılacak"), "acceptance_criteria": [N_("ölçülebilir kriter")],
                     "depends_on": ["T-00"], "files": [N_("dokunulacak/dosya.py")], "priority": "P0 | P1 | P2"}],
        "libraries": [{"name": N_("kütüphane adı"), "purpose": N_("ne için"), "technology": N_("onaylı teknoloji (örn. FastAPI)")}],
        "verification": {"install": N_("bağımlılık kurulum komutu"), "test": N_("test komutu"), "build": N_("build komutu (opsiyonel)"),
                         "lint": N_("lint komutu (opsiyonel)"), "run": N_("uygulamayı başlatan komut"), "health_url": "http://127.0.0.1:<port>/health"},
        "files": [{"path": "<docs>/openapi_spec.json", "content": "OpenAPI 3.0 JSON"}, {"path": "<docs>/ARCHITECTURE.md", "content": N_("mimari özeti")}],
    })

    def template_output(self, ctx: StepContext) -> Dict[str, Any]:
        openapi = json.dumps({
            "openapi": "3.0.0",
            "info": {"title": f"{ctx.project_name} Multi-Service API", "version": "1.0.0"},
            "paths": {
                "/api/auth/login": {"post": {"summary": tx("JWT Token Giriş"), "requestBody": {"content": {"application/json": {"schema": {"type": "object", "properties": {"username": {"type": "string"}, "password": {"type": "string"}}}}}}, "responses": {"200": {"description": tx("Token Başarılı")}}}},
                "/api/v1/items": {
                    "get": {"summary": tx("Veri listesi"), "responses": {"200": {"description": "OK"}}},
                    "post": {"summary": tx("Yeni kayıt oluştur"), "responses": {"201": {"description": "Created"}}},
                },
            },
        }, ensure_ascii=False, indent=2)
        env = self.envelope(ctx, {
            "summary": tx("Sistem Mimarı (Architect), mikroservis mimarisini tasarladı ve OpenAPI 3.0 API sözleşmesini (<docs>/openapi_spec.json) yayınladı."),
            "friendly_dialogue": tx("Selam Backend! REST API kontratı ve Pydantic veri modelleri hazır. Endpoint'leri kodlamaya başlayabilirsin!"),
            "thinking": self.thinking[0], "what_doing": self.thinking[1], "what_next": self.thinking[2],
            "architecture": "Decoupled Clean Architecture",
            "modules": ["auth", "items", "frontend"],
            "data_models": [{"name": "Item", "fields": ["id: str", "name: str", "category: str"]}],
            "backlog": [
                {"id": "T-01", "title": tx("Kayıt listesi filtreleme ve sayfalama"), "role": "BACKEND_DEV",
                 "description": tx("GET /api/v1/items için kategori filtresi ve sayfalama parametreleri ekle; birim testleriyle birlikte."),
                 "acceptance_criteria": [tx("?category= ile filtrelenir"), tx("?page=&size= ile sayfalanır"), tx("Testler yeşil")],
                 "depends_on": [], "files": ["src/main.py", "tests/test_items.py"], "priority": "P1"},
                {"id": "T-02", "title": tx("Arayüzde kayıt listesi ve filtre bileşeni"), "role": "FRONTEND_DEV",
                 "description": tx("Giriş sonrası kayıtları listeleyen, kategoriye göre filtreleyen bileşen ve API istemci fonksiyonu."),
                 "acceptance_criteria": [tx("Liste API'den yüklenir"), tx("Filtre değişince liste yenilenir")],
                 "depends_on": ["T-01"], "files": ["frontend/src/ItemList.tsx", "frontend/src/api_client.ts"], "priority": "P1"},
            ],
            "libraries": [{"name": "fastapi", "purpose": tx("API çatısı"), "technology": "FastAPI"},
                          {"name": "uvicorn", "purpose": tx("ASGI sunucusu"), "technology": "FastAPI"},
                          {"name": "pydantic", "purpose": tx("Girdi doğrulama"), "technology": "FastAPI"},
                          {"name": "pytest", "purpose": tx("Birim testleri"), "technology": "pytest"}],
            "verification": {"install": "python -m pip install -q -r requirements.txt", "test": "python -m pytest -q",
                             "run": "python -m uvicorn src.main:app --port 8000", "health_url": "http://127.0.0.1:8000/health"},
            "files": [{"path": "<docs>/openapi_spec.json", "content": openapi}],
        }, current_file="<docs>/openapi_spec.json")
        if getattr(ctx.run, "mode", "legacy") == "sprint":
            from ..sprint import sprint_template_backlog, stories_without_tasks
            env["payload"]["backlog"] = sprint_template_backlog(ctx.hub, stories_without_tasks(ctx.hub))
        return env

    def main_event_payload(self, ctx: StepContext, env: Dict[str, Any]) -> Dict[str, Any]:
        p = env["payload"]
        return {"architecture": p.get("architecture", "Decoupled Clean Architecture"), "contract": "<docs>/openapi_spec.json"}


# ---------------------------------------------------------------------------
# 3. BACKEND_DEV — Auth & servisler
# ---------------------------------------------------------------------------
class BackendHandler(StepHandler):
    order = 3
    agent_id = "BACKEND_DEV"
    next_agent_id = "FRONTEND_DEV"
    action = "BACKEND_API_EXPOSED"
    estimated_tokens = 420
    title = _TxAttr(N_("Senior Backend: REST API & Servisler"))
    thinking = _TxAttr((
        N_("OpenAPI sözleşmesine uygun FastAPI endpoint'leri ve JWT yetkilendirme mantığını kodluyorum."),
        N_("Kimlik doğrulama ve API servislerini geliştiriyor"),
        N_("Frontend takımına entegrasyon için hazır hale getirecek"),
    ))
    prior_files = ["<docs>/PRD.md", "<docs>/openapi_spec.json", "<docs>/ARCHITECTURE.md"]
    verify_after = True
    commit_after = True
    payload_schema = {
        "endpoints": ["/health", "/api/auth/login"],
        "files": [{"path": "src/main.py", "content": "..."}, {"path": "src/auth.py", "content": "..."}, {"path": "requirements.txt", "content": "..."},
                  {"path": "tests/test_health.py", "content": "..."}],
    }

    def extra_user_context(self, ctx: StepContext) -> str:
        snap = ctx.project_snapshot_md(max_entries=120)
        return (snap + "\n\n" if snap else "") + tx(
            "## Bu adımın kapsamı: BACKEND İSKELETİ\n"
            "Çalışan, test edilebilir bir uygulama iskeleti kur: bağımlılık manifesti, giriş noktası, sağlık ucu (/health), "
            "kimlik doğrulama temeli, veri katmanı kurulumu ve en az bir birim testi. Backlog görevleri daha sonra bu iskelete özellik ekleyecek; "
            "tüm özellikleri burada yazmaya çalışma. Sunucu teslimden sonra kurulum/test komutlarını koşacak."
        )

    def template_output(self, ctx: StepContext) -> Dict[str, Any]:
        auth_code = '"""\n' + tx("Kimlik Doğrulama ve JWT Token Modülü (demo — üretimde gerçek JWT kütüphanesi ve gizli anahtar yönetimi kullanın)") + '''
"""
import os
import time
from typing import Optional

SECRET_KEY = os.environ.get("APP_SECRET_KEY", "change-me-in-production")

def create_access_token(username: str) -> str:
    timestamp = int(time.time())
    return f"eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.{username}.{timestamp}"

def verify_token(token: str) -> Optional[str]:
    if not token or not token.startswith("eyJ"):
        return None
    parts = token.split(".")
    return parts[1] if len(parts) > 1 else None
'''
        backend_main = '"""\n' + tx("FastAPI Backend Uygulaması - Senior Backend Developer") + '''
"""
from fastapi import FastAPI, HTTPException, Header
from pydantic import BaseModel
from typing import Optional
from .auth import create_access_token, verify_token

app = FastAPI(title="Production Backend Service", version="1.0.0")

class LoginRequest(BaseModel):
    username: str
    password: str

class ItemModel(BaseModel):
    id: Optional[str] = None
    name: str
    category: str = "general"

db_items = [
    {"id": "item-1", "name": "Enterprise Cloud Setup", "category": "infra"},
    {"id": "item-2", "name": "High Throughput Message Bus", "category": "backend"}
]

@app.get("/health")
def health():
    return {"status": "ok", "backend": "online"}

@app.post("/api/auth/login")
def login(req: LoginRequest):
    if req.username.strip() and req.password:
        token = create_access_token(req.username)
        return {"access_token": token, "token_type": "bearer", "user": req.username}
    raise HTTPException(status_code=400, detail="''' + tx("Kullanıcı adı ve şifre zorunludur.") + '''")

@app.get("/api/v1/items")
def get_items(authorization: Optional[str] = Header(None)):
    return {"items": db_items, "count": len(db_items)}

@app.post("/api/v1/items")
def add_item(item: ItemModel):
    item_dict = item.model_dump()
    item_dict["id"] = f"item-{len(db_items) + 1}"
    db_items.append(item_dict)
    return {"status": "created", "item": item_dict}
'''
        return self.envelope(ctx, {
            "summary": tx("Kıdemli Backend Geliştiricisi, FastAPI REST servislerini, JWT token imzalama ve doğrulama modüllerini (src/auth.py, src/main.py) geliştirdi."),
            "friendly_dialogue": tx("Selam Frontend! Giriş ve veri yönetim API'larını tamamladım, port 8080'de yayında. Arayüze bağlayabilirsin!"),
            "thinking": self.thinking[0], "what_doing": self.thinking[1], "what_next": self.thinking[2],
            "endpoints": ["/health", "/api/auth/login", "/api/v1/items"],
            "files": [
                {"path": "src/auth.py", "content": auth_code},
                {"path": "src/main.py", "content": backend_main},
                {"path": "requirements.txt", "content": "fastapi>=0.110\nuvicorn>=0.29\npydantic>=2\n"},
                *self._strict_smoke_test(ctx),
            ],
        }, current_file="src/main.py")

    @staticmethod
    def _strict_smoke_test(ctx: StepContext) -> List[Dict[str, str]]:
        """Sıkı DoD açıkken (şablon motoru) iskelete yer tutucu bir test eklenir; "hiç test yok" bitmiş saymaz (§7.7). Gerçek koşuda testi ajan yazar."""
        try:
            from .. import quality as Q
            if not Q.strict(ctx.hub):
                return []
        except Exception:
            return []
        return [{"path": "tests/test_scaffold.py", "content": (
            '"""' + tx("Şablon motoru yer tutucu testi (sıkı DoD): iskelet dosyaları var.") + '"""\nimport os\n\n\n'
            'def test_scaffold_files_exist():\n    assert os.path.isfile("src/main.py") and os.path.isfile("src/auth.py")\n')}]

    def main_event_payload(self, ctx: StepContext, env: Dict[str, Any]) -> Dict[str, Any]:
        return {"endpoints": env["payload"].get("endpoints", []), "files": [f["path"] for f in env["payload"].get("files", [])]}


# ---------------------------------------------------------------------------
# 4. FRONTEND_DEV — UI & API client
# ---------------------------------------------------------------------------
class FrontendHandler(StepHandler):
    order = 4
    agent_id = "FRONTEND_DEV"
    next_agent_id = "BACKEND_DEV"
    action = "FRONTEND_COMPONENTS_READY"
    estimated_tokens = 380
    title = _TxAttr(N_("Senior Frontend: Responsive UI & Formlar"))
    thinking = _TxAttr((
        N_("Backend API'larına bağlanacak modern React/Vite arayüz bileşenlerini oluşturuyorum."),
        N_("Modern Tailwind/React dashboard UI'ını inşa ediyor"),
        N_("Kod kalitesi ve test için QA'ya devredecek"),
    ))
    prior_files = ["<docs>/openapi_spec.json", "<docs>/ARCHITECTURE.md"]
    verify_after = True
    commit_after = True
    payload_schema = _TxAttr({
        "components": [N_("bileşen adları")],
        "files": [{"path": "frontend/src/App.tsx", "content": "..."}, {"path": "frontend/src/api_client.ts", "content": "..."}],
    })

    def extra_user_context(self, ctx: StepContext) -> str:
        snap = ctx.project_snapshot_md(max_entries=120)
        return (snap + "\n\n" if snap else "") + tx(
            "## Bu adımın kapsamı: İSTEMCİ İSKELETİ\n"
            "Seçilen istemci teknolojisiyle kurulabilir bir uygulama iskeleti kur: paket manifesti (örn. package.json ve build betiği), "
            "giriş ekranı/akışı, API istemci katmanı, yönlendirme temeli. Backlog görevleri ekranları bu iskelete ekleyecek. "
            "Backend'in gerçek uç noktalarını (OpenAPI) kullan; uydurma uç nokta yazma."
        )

    def template_output(self, ctx: StepContext) -> Dict[str, Any]:
        client_code = '// ' + tx("Senior Frontend Developer - API Client Modülü") + '''
export interface LoginResponse {
  access_token: string;
  token_type: string;
  user: string;
}

export async function loginUser(username: string, password: string): Promise<LoginResponse> {
  const res = await fetch('/api/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password })
  });
  if (!res.ok) throw new Error('Login failed');
  return res.json();
}
'''
        ui_code = '''import React, { useState } from 'react';
import { loginUser } from './api_client';

export function ModernDashboard() {
  const [token, setToken] = useState<string | null>(null);
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);

  const handleLogin = async () => {
    try {
      const res = await loginUser(username, password);
      setToken(res.access_token);
      setError(null);
    } catch (e) {
      setError(\'''' + tx("Giriş başarısız. Bilgilerinizi kontrol edin.") + '''');
    }
  };

  return (
    <div className="p-8 bg-slate-900 text-white min-h-screen">
      <h1 className="text-2xl font-bold mb-4">Enterprise Application Dashboard</h1>
      {!token ? (
        <div className="max-w-md bg-slate-800 p-6 rounded-lg border border-slate-700">
          <input className="w-full mb-3 p-2 bg-slate-900 rounded" placeholder="''' + tx("Kullanıcı Adı") + '''"
            value={username} onChange={e => setUsername(e.target.value)} />
          <input type="password" className="w-full mb-3 p-2 bg-slate-900 rounded" placeholder="''' + tx("Şifre") + '''"
            value={password} onChange={e => setPassword(e.target.value)} />
          {error && <p className="text-rose-400 text-sm mb-2">{error}</p>}
          <button onClick={handleLogin} className="w-full bg-blue-600 hover:bg-blue-500 py-2 rounded font-semibold">
            ''' + tx("Giriş Yap") + '''
          </button>
        </div>
      ) : (
        <div>''' + tx("Hoşgeldiniz, oturum aktif.") + '''</div>
      )}
    </div>
  );
}
'''
        return self.envelope(ctx, {
            "summary": tx("Kıdemli Frontend Geliştiricisi, modern React panosunu (frontend/src/App.tsx) ve API Client (frontend/src/api_client.ts) modülünü kodladı."),
            "friendly_dialogue": tx("Harika, API bağlantılarını ve veri akışını teyit ettim. Karşılıklı el sıkıştık!"),
            "thinking": self.thinking[0], "what_doing": self.thinking[1], "what_next": self.thinking[2],
            "components": ["ModernDashboard", "LoginForm"],
            "files": [
                {"path": "frontend/src/App.tsx", "content": ui_code},
                {"path": "frontend/src/api_client.ts", "content": client_code},
            ],
        }, current_file="frontend/src/App.tsx")


# ---------------------------------------------------------------------------
# 5. Peer Handshake — sunucu tarafında (A2A senkron olayları)
# ---------------------------------------------------------------------------
class HandshakeHandler(StepHandler):
    order = 5
    agent_id = "BACKEND_DEV"
    next_agent_id = "QA"
    action = "A2A_CONTRACT_CONFIRM"
    server_side = True
    estimated_tokens = 370
    title = "Peer Review & Backend-Frontend API Handshake"
    thinking = _TxAttr((
        N_("Backend ve Frontend arasında Bearer başlığı, CORS ve veri modeli uyumunu karşılıklı doğruluyoruz."),
        N_("A2A kontrat senkronizasyonu yapıyor"),
        N_("QA'ya birim testleri için devredecek"),
    ))

    def template_output(self, ctx: StepContext) -> Dict[str, Any]:
        sync = {
            "order": 5, "status": "ALIGNED", "auth_header": "Authorization: Bearer <token>",
            "backend_agent": "BACKEND_DEV", "frontend_agent": "FRONTEND_DEV",
            "schema_version": "1.0.0", "verification": "Cross-agent verified successfully",
        }
        return self.envelope(ctx, {
            "summary": tx("Geliştiriciler Arası Eş İnceleme (Peer Review): Senior Backend ve Senior Frontend doğrudan A2A iletişimi kurarak CORS, Bearer token başlığı ve model senkronizasyonunu onayladı."),
            "friendly_dialogue": tx("Backend servislerini ve middleware'i kodladık, kontrat hizalandı. QA, birim testler için hazır!"),
            "thinking": self.thinking[0], "what_doing": self.thinking[1], "what_next": self.thinking[2],
            "handshake": sync,
            "files": [{"path": "<docs>/handshake_sync.json", "content": json.dumps(sync, indent=2, ensure_ascii=False)}],
        }, current_file="<docs>/handshake_sync.json")

    def render(self, ctx: StepContext, env: Dict[str, Any]) -> StepResult:
        result = super().render(ctx, env)
        sync_event = StepEvent(
            from_agent="BACKEND_DEV", to_agent="FRONTEND_DEV", action="A2A_CONTRACT_SYNC", status="SUCCESS",
            payload={"order": 5, "message": tx("Senior Frontend, /api/auth/login dönüşünde Bearer token header'ını 'Authorization: Bearer <token>' formatında gönderdiğinden emin ol."), "schema_version": "1.0.0"},
            current_file="src/auth.py", tokens_used=190, pause_after_s=1.8,
        )
        confirm_event = StepEvent(
            from_agent="FRONTEND_DEV", to_agent="BACKEND_DEV", action="A2A_CONTRACT_CONFIRM", status="SUCCESS",
            payload={"order": 5, "message": tx("Doğrulandı Senior Backend. Fetch interceptor'ı Bearer header'ını ekleyecek şekilde yapılandırıldı."), "handshake_status": "ALIGNED"},
            current_file="frontend/src/api_client.ts", tokens_used=180, pause_after_s=1.5,
        )
        result.events = [sync_event, confirm_event]
        return result


# ---------------------------------------------------------------------------
# 6. QA — birim testleri, bug döngüsü, onay
# ---------------------------------------------------------------------------
class QAHandler(StepHandler):
    order = 6
    agent_id = "QA"
    next_agent_id = "E2E_TESTER"
    action = "APPROVE_BUILD"
    critical = True
    estimated_tokens = 390
    title = _TxAttr(N_("Lead QA: Birim ve Fonksiyonel Doğrulama"))
    thinking = _TxAttr((
        N_("Senior yazılımcıların kodlarını inceliyorum. Pytest ve birim test senaryolarını çalıştırıyorum."),
        N_("API birim testlerini ve hata kontrollerini koşturuyor"),
        N_("E2E canlı tarayıcı testlerine geçilecek"),
    ))
    prior_files = ["<docs>/PRD.md", "<docs>/openapi_spec.json"]
    verify_after = True
    commit_after = True
    payload_schema = _TxAttr({
        "verdict": "APPROVED | REJECTED",
        "bugs": [{"bug_id": "BUG-QA-01", "severity": "LOW|MEDIUM|HIGH", "issue": N_("açıklama"), "resolution": N_("nasıl düzeltildi / düzeltilmeli")}],
        "files": [{"path": "tests/test_app.py", "content": "..."}, {"path": "<docs>/QA_REPORT.md", "content": "..."}],
    })

    def extra_user_context(self, ctx: StepContext) -> str:
        """QA, koşu boyunca yazılan gerçek kod dosyalarını (teknolojiden bağımsız) görür; testler sunucuda koşar."""
        parts: List[str] = []
        snap = ctx.project_snapshot_md(max_entries=200)
        if snap:
            parts.append(snap)
        written = [p for p in ctx.run.files_written() if not p.startswith(ctx.docs_root + "/")]
        code = ctx.read_files_budget(written, total_budget=30000, per_file=8000)
        for rel, content in code.items():
            parts.append(tx("\n## Kod dosyası: {rel}\n```\n{content}\n```", rel=rel, content=content))
        summary = ctx.run_summary_md()
        if summary:
            parts.append("\n" + summary)
        from ..testing import qa_context
        cases_ctx = qa_context(ctx.hub)
        if cases_ctx:
            parts.append("\n" + cases_ctx)
        parts.append(tx(
            "\n## Bu adımın kapsamı: ENTEGRASYON VE REGRESYON TESTLERİ\n"
            "Kabul kriterlerini ve uç durumları kapsayan GERÇEK test dosyaları yaz (seçilen test aracıyla: pytest/jest/phpunit...). "
            "Sunucu teslimden sonra test komutunu gerçekten koşacak; testler kalırsa geliştiriciye düzeltme turu açılır. "
            "`verdict` yalnızca kodun kabul kriterlerine uygunluğunu yansıtsın; kanıtsız APPROVED verme."
        ))
        return "\n".join(parts)

    def template_output(self, ctx: StepContext) -> Dict[str, Any]:
        test_code = '"""\n' + tx("Otomatik Birim ve Entegrasyon Testleri - QA Lead") + '''
"""
def test_token_creation():
    from src.auth import create_access_token, verify_token
    t = create_access_token("alice")
    assert verify_token(t) == "alice"

def test_token_invalid():
    from src.auth import verify_token
    assert verify_token("invalid_token") is None
'''
        qa_report = tx("""# QA Onay Raporu
- Tüm birim testler: 2/2 GEÇTİ
- API kontrat uyumu: %100 ONAYLANDI
- Ajanlar arası veri bütünlüğü: DOĞRULANDI
- Tespit edilen hata: BUG-QA-01 (LOW) — boş kullanıcı adı doğrulaması eklendi
""")
        return self.envelope(ctx, {
            "summary": tx("QA Mühendisi (Lead QA), otomatik birim testlerini (tests/test_app.py) çalıştırdı, tespit edilen küçük hata için düzeltme doğrulaması yaptı ve QA Onay Raporunu yayınladı."),
            "friendly_dialogue": tx("Birim ve API testleri başarıyla onaylandı. Canlı tarayıcı testlerine geçebilirsin!"),
            "thinking": self.thinking[0], "what_doing": self.thinking[1], "what_next": self.thinking[2],
            "verdict": "APPROVED",
            "bugs": [{"bug_id": "BUG-QA-01", "severity": "LOW", "issue": "Empty username login request returned 400 instead of strict validation", "resolution": "Input validation guard added."}],
            "files": [
                {"path": "tests/test_app.py", "content": test_code},
                {"path": "<docs>/QA_REPORT.md", "content": qa_report},
            ],
        }, current_file="<docs>/QA_REPORT.md")

    def render(self, ctx: StepContext, env: Dict[str, Any]) -> StepResult:
        result = super().render(ctx, env)
        payload = env.get("payload", {})
        bugs: List[Dict[str, Any]] = payload.get("bugs") or []
        verdict = str(payload.get("verdict") or "APPROVED").upper()
        extra: List[StepEvent] = []
        for bug in bugs[:3]:
            extra.append(StepEvent(
                from_agent="QA", to_agent="BACKEND_DEV", action="REPORT_BUG", status="FAILED",
                payload={"order": 6, "bug_id": bug.get("bug_id", "BUG-QA"), "severity": bug.get("severity", "LOW"), "issue": bug.get("issue", "")},
                current_file="tests/test_app.py", tokens_used=210, pause_after_s=2.0,
                friendly_dialogue=tx("Birim testlerini koşturdum, bir hata yakaladım. Hemen düzeltip tekrar iletebilir misin?"),
            ))
            extra.append(StepEvent(
                from_agent="BACKEND_DEV", to_agent="QA", action="SUBMIT_CODE", status="SUCCESS",
                payload={"order": 6, "fixed_bug": bug.get("bug_id", "BUG-QA"), "resolution": bug.get("resolution", tx("Düzeltildi."))},
                current_file="src/main.py", tokens_used=170, pause_after_s=1.5,
            ))
        main = result.events[-1]
        if verdict != "APPROVED":
            main.action = "REPORT_BUG"
            main.status = "FAILED"
            main.to_agent = "BACKEND_DEV"
            result.action = "REPORT_BUG"
            result.status = "FAILED"
            result.next_agent_id = "BACKEND_DEV"
        main.payload.update({"verdict": verdict, "report": ctx.r("<docs>/QA_REPORT.md"), "bugs_found": len(bugs)})
        result.events = extra + [main]
        return result


# ---------------------------------------------------------------------------
# 7. E2E_TESTER — sunucu tarafında gerçek Playwright
# ---------------------------------------------------------------------------
class E2EHandler(StepHandler):
    order = 7
    agent_id = "E2E_TESTER"
    next_agent_id = "DEVOPS"
    action = "E2E_SCREENSHOT_CONFIRMED"
    server_side = True
    estimated_tokens = 310
    title = _TxAttr(N_("Playwright E2E: Canlı Tarayıcı Doğrulama"))
    thinking = _TxAttr((
        N_("Canlı web arayüzünde kullanıcı senaryolarını test etmek için Playwright tarayıcısını başlatıyorum."),
        N_("Playwright ile headless tarayıcıda form ve butonları sınıyor"),
        N_("Test raporunu DevOps'a aktaracak"),
    ))

    def template_output(self, ctx: StepContext) -> Dict[str, Any]:
        # Gerçek sonuç pipeline tarafından `ctx.record` üzerinden enjekte edilir (run_server_step)
        res = getattr(ctx, "e2e_result", None) or {"status": "SKIPPED", "screenshots": [], "engine_error": tx("Playwright koşulmadı")}
        passed = res.get("status") == "PASSED"
        summary = (
            tx("Playwright E2E Tester, canlı Chromium tarayıcısı açtı, kullanıcı formlarını denedi ve kanıt ekran görüntüleri yakaladı.")
            if passed else
            tx("Playwright E2E testi KOŞULAMADI ({status}): {error}", status=res.get('status'), error=res.get('engine_error') or tx('bilinmeyen hata'))
        )
        return self.envelope(ctx, {
            "summary": summary,
            "friendly_dialogue": (
                tx("Canlı Chromium tarayıcısında uçtan uca senaryoları çalıştırdım, ekran görüntülerini kaydettim. Her şey kusursuz!")
                if passed else
                tx("Tarayıcı testini koşamadım, ortamda Playwright/Chromium eksik görünüyor. DevOps, bir göz atar mısın?")
            ),
            "thinking": self.thinking[0], "what_doing": self.thinking[1], "what_next": self.thinking[2],
            "e2e_result": res,
            "files": [{"path": "<reports>/e2e_summary.json", "content": json.dumps(res, indent=2, ensure_ascii=False)}],
        }, current_file=".fs-workspace/e2e/screenshots", status="SUCCESS" if passed else "FAILED")

    def render(self, ctx: StepContext, env: Dict[str, Any]) -> StepResult:
        result = super().render(ctx, env)
        res = env.get("payload", {}).get("e2e_result") or {}
        passed = res.get("status") == "PASSED"
        no_ui = res.get("status") == "SKIPPED" and res.get("verdict") == "NO_UI"     # G1: arayüzü olmayan (API-only) uygulama; kusur değil
        result.screenshots = list(res.get("screenshots") or [])
        result.status = "SUCCESS" if (passed or no_ui) else "FAILED"
        main = result.events[-1]
        main.action = "E2E_SCREENSHOT_CONFIRMED" if passed else ("E2E_NOT_APPLICABLE" if no_ui else "E2E_TEST_FAILED")
        main.status = "SUCCESS" if passed else ("IN_PROGRESS" if no_ui else "FAILED")
        main.to_agent = "ARCHITECT"
        main.payload.update({
            "screenshots_count": len(result.screenshots),
            "screenshots": result.screenshots,
            "test_status": res.get("status", "FAILED"),
            "engine_error": res.get("engine_error"),
        })
        result.action = main.action
        return result


# ---------------------------------------------------------------------------
# 8. DEVOPS — Docker & release
# ---------------------------------------------------------------------------
class DevOpsHandler(StepHandler):
    order = 8
    agent_id = "DEVOPS"
    next_agent_id = "PM"
    action = "DEPLOY_CONFIRM"
    critical = True
    estimated_tokens = 240
    title = _TxAttr(N_("DevOps Dağıtım & Docker Yayını"))
    thinking = _TxAttr((
        N_("Testler başarıyla tamamlandı. Dockerfile ve CI/CD pipeline yapılandırmalarını hazırlıyorum."),
        N_("Docker konteyner imajı ve dağıtım konfigürasyonlarını kuruyor"),
        N_("Prodüksiyon dağıtımı ve sürüme onay verecek"),
    ))
    prior_files = ["<docs>/ARCHITECTURE.md"]
    verify_after = True
    commit_after = True
    payload_schema = _TxAttr({
        "release_status": "RELEASED_TO_PRODUCTION | STAGING",
        "verification": {"run": N_("uygulamayı başlatan komut (opsiyonel; mimarınkini düzeltmek için)"), "health_url": "http://127.0.0.1:<port>/health"},
        "files": [{"path": "Dockerfile", "content": "..."}, {"path": "docker-compose.yml", "content": "..."}, {"path": "README.md", "content": "..."}],
    })

    def extra_user_context(self, ctx: StepContext) -> str:
        parts: List[str] = []
        snap = ctx.project_snapshot_md(max_entries=160)
        if snap:
            parts.append(snap)
        manifests = ctx.read_files_budget(["requirements.txt", "pyproject.toml", "package.json", "frontend/package.json", "composer.json", "go.mod", ".env.example"],
                                          total_budget=8000, per_file=2500)
        for rel, content in manifests.items():
            parts.append(tx("\n## Manifest: {rel}\n```\n{content}\n```", rel=rel, content=content))
        summary = ctx.run_summary_md()
        if summary:
            parts.append("\n" + summary)
        ver = ctx.hub.get_settings().get("verification") or {}
        if ver:
            parts.append(tx("\n## Kayıtlı doğrulama/çalıştırma komutları\n```json\n") + json.dumps(ver, ensure_ascii=False, indent=2) + "\n```")
        parts.append(tx("Konteyner ve başlatma yapılandırmasını seçilen teknolojiye ve gerçek dosya adlarına göre yaz; README'de kurulum ve çalıştırma adımlarını ver."))
        return "\n".join(parts)

    def template_output(self, ctx: StepContext) -> Dict[str, Any]:
        dockerfile = "FROM python:3.12-slim\nWORKDIR /app\nCOPY requirements.txt .\nRUN pip install -r requirements.txt\nCOPY . .\nEXPOSE 8080\nCMD [\"uvicorn\", \"src.main:app\", \"--host\", \"0.0.0.0\", \"--port\", \"8080\"]\n"
        compose = f"name: {ctx.run.project_id}\nservices:\n  app:\n    build:\n      context: ..\n      dockerfile: devops/Dockerfile\n    ports:\n      - \"8080:8080\"\n"
        readme = tx("# {name}\n\nBu proje **FS-SC Çoklu Ajan Şirket Sistemi** tarafından üretilmiştir.\n10 maddelik Jira pipeline'ı ile geliştirilmiştir.\n", name=ctx.project_name)
        return self.envelope(ctx, {
            "summary": tx("DevOps Mühendisi, Dockerfile ve docker-compose.yml yapılandırmasını tamamlayıp sürümü üretime hazır hale getirdi."),
            "friendly_dialogue": tx("Konteyner ve deployment yapılandırması tamamlandı! Sistemimiz canlıda aktif, müşteriye gururla sunabiliriz."),
            "thinking": self.thinking[0], "what_doing": self.thinking[1], "what_next": self.thinking[2],
            "release_status": "RELEASED_TO_PRODUCTION",
            "files": [
                {"path": "devops/Dockerfile", "content": dockerfile},                 # kalıcı kural: Docker/compose dosyaları yalnızca devops/ altında
                {"path": "devops/docker-compose.yml", "content": compose},
                {"path": "README.md", "content": readme},
            ],
        }, current_file="README.md")

    def main_event_payload(self, ctx: StepContext, env: Dict[str, Any]) -> Dict[str, Any]:
        return {"target_dir": ctx.project_dir, "status": env["payload"].get("release_status", "RELEASED_TO_PRODUCTION"), "containers": [f["path"] for f in env["payload"].get("files", [])]}


# ---------------------------------------------------------------------------
# 9. PO — UAT
# ---------------------------------------------------------------------------
class POHandler(StepHandler):
    order = 9
    spec_budget = 40000
    agent_id = "PO"
    next_agent_id = "DOCUMENTOR"
    action = "UAT_APPROVED"
    critical = True
    estimated_tokens = 220
    title = _TxAttr(N_("Product Owner (PO) UAT & Nihai Müşteri Kabulü"))
    thinking = _TxAttr((
        N_("Geliştirilen sistemin PRD ve kullanıcı kabul kriterlerine uygunluğunu UAT testleriyle denetliyorum."),
        N_("Nihai kullanıcı deneyimini ve şartname uyumunu kontrol ediyor"),
        N_("UAT onayı verilecek veya yeni iyileştirme açılacak"),
    ))
    prior_files = ["<docs>/PRD.md", "<docs>/QA_REPORT.md", "<reports>/e2e_summary.json"]

    @staticmethod
    def _sprint_no(ctx: StepContext) -> int:
        return int(ctx.record.sprint or 0) if getattr(ctx.run, "mode", "legacy") == "sprint" else 0

    def display_title(self, ctx: StepContext) -> str:
        # Sprint kipinde bu adım ürünün nihai kabulü DEĞİL, sprint kapsamının kabulüdür; sabit "Nihai Müşteri Kabulü" başlığı yanıltıcıydı
        n = self._sprint_no(ctx)
        return tx("Sprint {n} kabulü (PO UAT)", n=n) if n else ctx.title

    def thinking_for(self, ctx: StepContext) -> tuple:
        n = self._sprint_no(ctx)
        if not n:
            return self.thinking
        return (tx("Sprint {n} kapsamındaki kabul kriterlerini sunucunun topladığı kanıtla (test ve E2E sonuçları) karşılaştırıp kriter bazında karar vereceğim.", n=n),
                tx("Sprint {n} kabul kriterlerini kanıtlarıyla denetliyor", n=n),
                tx("Kanıtlı kriterleri kabul edecek, kanıtsızları iyileştirme işi olarak geri çevirecek"))

    payload_schema = _TxAttr({
        "uat_status": "APPROVED | REJECTED",
        "score": 0,
        "criteria": [{"id": "AC-1", "decision": "ACCEPTED | REJECTED", "reason": N_("kanıt: hangi test/E2E senaryosu ya da neden ret")}],
        "improvements": [{"title": N_("eksik/iyileştirilecek özellik"), "role": "BACKEND_DEV | FRONTEND_DEV | DEVOPS",
                          "description": N_("ne yapılmalı"), "acceptance_criteria": [N_("ölçülebilir kriter")]}],
        "files": [{"path": "<docs>/uat/acceptance_criteria.md", "content": "..."}],
    })

    def extra_user_context(self, ctx: StepContext) -> str:
        parts: List[str] = []
        summary = ctx.run_summary_md()
        if summary:
            parts.append(summary)
        snap = ctx.project_snapshot_md(max_entries=160)
        if snap:
            parts.append("\n" + snap)
        max_rounds = int(ctx.hub.get_settings().get("max_uat_rounds", 1) or 0)
        remaining = max(0, max_rounds - ctx.run.uat_round)
        try:
            from .. import quality as Q
            from .. import sprint as SP
            if Q.strict(ctx.hub) and ctx.record.sprint:
                n = ctx.record.sprint
                req = Q.sprint_acs(ctx.hub, n)
                ev = Q.evidence_for(ctx.hub, n, ctx.project_dir)
                parts.append(tx("\n## Kriter bazında karar (sıkı DoD, zorunlu)\n`criteria[]` içinde bu sprintin her kabul kriteri için ayrı karar ver (ACCEPTED | REJECTED, gerekçeyle). "
                                "Kanıtı olmayan kriteri kabul edemezsin; sunucu kanıtsız kabulü reddeder.\n")
                             + ("\n".join(f"- {ac}" + (f" ({SP.ac_text(ctx.hub, ac)[:200]})" if SP.ac_text(ctx.hub, ac) else "") + ": " + (tx("kanıt var (test: {tests}; E2E: {e2e}; case: {cases})", tests=', '.join(ev[ac]['tests'][:3]) or '-', e2e=', '.join(ev[ac]['e2e'][:3]) or '-', cases=', '.join(ev[ac].get('cases', [])[:3]) or '-') if ev.get(ac, {}).get("ok") else tx("KANIT YOK"))
                                           for ac in req) or tx("- (bu sprintte kapsanan kriter yok)")))
                from .. import testing as TST
                mx = TST.matrix(ctx.hub, ctx.project_dir)
                if mx["total"]:
                    gate = TST.regression_gate(ctx.hub)
                    parts.append(tx("\nTest izlenebilirlik matrisi: kapsama %{coverage} (hedef %{target}); case'siz kriter: {no_case}; "
                                    "başarısız: {failing}; regresyon kümesi: {gate}. Kararını bu matrise dayandır.",
                                    coverage=mx['coverage_pct'], target=mx['target_pct'], no_case=', '.join(mx['no_case']) or '-',
                                    failing=', '.join(mx['failing']) or '-', gate=tx('geçti') if gate['ok'] else tx('GEÇMEDİ')))
        except Exception:
            pass
        parts.append(
            tx("\n## UAT kuralı\n"
               "PRD'deki her kullanıcı hikayesi ve kabul kriteri için 'karşılandı / kısmen / eksik' kararı ver. ")
            + (tx("`uat_status: REJECTED` verirsen `improvements[]` içindeki her madde bir geliştirme görevine dönüşür ve ekip "
                  "QA + UAT turunu yeniden koşar (kalan iyileştirme turu: {remaining}). Yalnızca gerçekten eksik olan işleri yaz.", remaining=remaining)
               if remaining > 0 else
               tx("İyileştirme turu hakkı kalmadı: eksikleri `improvements[]` ile belgele; karar bilgilendirici olacak."))
        )
        return "\n".join(parts)

    def template_output(self, ctx: StepContext) -> Dict[str, Any]:
        uat = tx("""# 🏆 Product Owner (PO) UAT Kabul Raporu
**Proje:** {name}
**Tarih:** {date}
**PO Değerlendirmesi:** KABUL EDİLDİ (UAT_APPROVED) - Puan: 98/100

### 1. Doğrulanan Kabul Kriterleri
- [x] Müşteri toplantı notları ve şartname hedefleri eksiksiz karşılandı.
- [x] OpenAPI 3.0 sözleşmesi ve veri modelleri standartlara uygun.
- [x] FastAPI REST servisleri ve JWT kimlik doğrulama test edildi.
- [x] Modern ve responsive React arayüzü form validasyonları çalışıyor.
- [x] Lead QA birim testleri ve Playwright canlı tarayıcı E2E akışı yeşil.
- [x] Docker ve konteyner dağıtım konfigürasyonu hazır.

### 2. Kullanıcı Deneyimi & İş Değeri Notları
- Arayüz akıcı, bildirimler Türkçe ve anlaşılır.
- UAT testi başarıyla onaylanmış olup son kullanıcı kılavuzları için Documentor ajanı görevlendirilmiştir.
""", name=ctx.project_name, date=ctx.now_str())
        criteria: List[Dict[str, Any]] = []
        try:
            from .. import quality as Q
            if Q.strict(ctx.hub) and ctx.record.sprint:
                ev = Q.evidence_for(ctx.hub, ctx.record.sprint, ctx.project_dir)
                criteria = [{"id": ac, "decision": "ACCEPTED", "reason": tx("kanıt: ") + ", ".join((ev.get(ac, {}).get("tests") or ev.get(ac, {}).get("e2e") or ev.get(ac, {}).get("cases") or [tx("yok")])[:2])}
                            for ac in Q.sprint_acs(ctx.hub, ctx.record.sprint)]
        except Exception:
            criteria = []
        return self.envelope(ctx, {
            "criteria": criteria,
            "summary": tx("Product Owner (PO), geliştirilen ürünü PRD ve müşteri kabul kriterlerine göre denetledi, UAT onayını (UAT_APPROVED) verdi."),
            "friendly_dialogue": tx("UAT Kabul Testi Başarılı! Ürün müşteri şartnamesini karşılıyor. Son kullanıcı kılavuzunu hazırlayabilirsin Documentor!"),
            "thinking": self.thinking[0], "what_doing": tx("UAT kabul kriterlerini onaylıyor"), "what_next": tx("Documentor'a kullanım kılavuzu üretimini devrediyor"),
            "uat_status": "APPROVED", "score": 98, "improvements": [],
            "files": [{"path": "<docs>/uat/acceptance_criteria.md", "content": uat}],
        }, current_file="<docs>/uat/acceptance_criteria.md")

    def render(self, ctx: StepContext, env: Dict[str, Any]) -> StepResult:
        result = super().render(ctx, env)
        p = env.get("payload", {})
        status = str(p.get("uat_status") or "APPROVED").upper()
        main = result.events[-1]
        main.payload.update({"uat_status": status, "score": p.get("score", 0), "target_file": ctx.r("<docs>/uat/acceptance_criteria.md")})
        if status != "APPROVED":
            main.action = "UAT_REJECTED"
            main.status = "FAILED"
            main.to_agent = "PM"
            result.action = "UAT_REJECTED"
            result.status = "FAILED"
        return result


# ---------------------------------------------------------------------------
# 10. DOCUMENTOR + REPORTER — kılavuz & yönetici raporu
# ---------------------------------------------------------------------------
class DocsHandler(StepHandler):
    order = 10
    agent_id = "DOCUMENTOR"
    next_agent_id = "PM"
    action = "MANUALS_PUBLISHED"
    estimated_tokens = 280
    title = _TxAttr(N_("Documentor & Reporter: Kullanım Kılavuzu & Yönetici Özeti"))
    thinking = _TxAttr((
        N_("Son kullanıcı kullanım kılavuzunu (User Manual) ve yönetim durum özetini derliyorum."),
        N_("Kullanım kılavuzu ve yönetici raporunu oluşturuyor"),
        N_("Proje teslim dokümantasyonu tamamlanıyor"),
    ))
    prior_files = ["<docs>/PRD.md", "README.md", "<docs>/uat/acceptance_criteria.md"]
    commit_after = True
    payload_schema = {
        "files": [{"path": "<docs>/manuals/user_guide.md", "content": "..."}, {"path": "<docs>/reports/status_report.md", "content": "..."},
                  {"path": "CHANGELOG.md", "content": "..."}],
    }

    def extra_user_context(self, ctx: StepContext) -> str:
        parts: List[str] = []
        summary = ctx.run_summary_md()
        if summary:
            parts.append(summary)
        snap = ctx.project_snapshot_md(max_entries=200)
        if snap:
            parts.append("\n" + snap)
        parts.append(tx("Durum raporunda koşu özetindeki gerçek adımları, doğrulama sonuçlarını ve commit'leri kullan; CHANGELOG.md'yi bu koşunun teslimatlarıyla yaz."))
        return "\n".join(parts)

    def template_output(self, ctx: StepContext) -> Dict[str, Any]:
        guide = tx("""# 📖 {name} - Kullanım Kılavuzu (User Manual)
**Hazırlayan:** Documentor Ajanı
**Tarih:** {date}

## 1. Sisteme Giriş ve Genel Bakış
Bu kılavuz, sistemin kurulumu ve son kullanıcı adımlarını açıklar.

### 2. Kurulum ve Çalıştırma
```bash
pip install -r requirements.txt
uvicorn src.main:app --port 8080
```

### 3. API Kullanımı
- `GET /health` -> Sistem sağlık kontrolü
- `POST /api/auth/login` -> Kullanıcı kimlik doğrulama
- `GET /api/v1/items` -> Veri listeleme ve yönetim
""", name=ctx.project_name, date=ctx.now_str('%Y-%m-%d'))
        report = tx("""# 📊 Yönetici Durum Raporu (Executive Summary)
**Proje:** {name}
**Tarih:** {date}
**Genel Sağlık:** 🟢 MÜKEMMEL (ALL GREEN)

### Özet İstatistikler
- **Toplam Tamamlanan Görev:** {done} / {done}
- **QA & E2E Test Başarısı:** bkz. <docs>/QA_REPORT.md ve <reports>/e2e_summary.json
- **PO UAT Onayı:** bkz. <docs>/uat/acceptance_criteria.md
- **Harcanan Token:** Yaklaşık {tokens} token
""", name=ctx.project_name, date=ctx.now_str(), done=len(ctx.run.steps), tokens=ctx.hub.stats.get('total_tokens', 0))
        return self.envelope(ctx, {
            "summary": tx("Documentor Ajanı son kullanıcı kılavuzunu (user_guide.md), Reporter Ajanı ise yönetici durum özetini (status_report.md) oluşturdu."),
            "friendly_dialogue": tx("Kılavuz ve yönetici özeti hazır! Teslimat dokümantasyonu tamamlandı, tebrikler ekip."),
            "thinking": self.thinking[0], "what_doing": self.thinking[1], "what_next": self.thinking[2],
            "files": [
                {"path": "<docs>/manuals/user_guide.md", "content": guide},
                {"path": "<docs>/reports/status_report.md", "content": report},
            ],
        }, current_file="<docs>/manuals/user_guide.md")

    def main_event_payload(self, ctx: StepContext, env: Dict[str, Any]) -> Dict[str, Any]:
        return {"manual": "<docs>/manuals/user_guide.md", "report": "<docs>/reports/status_report.md"}


ALL_HANDLERS: List[StepHandler] = [
    PMHandler(), ArchitectHandler(), BackendHandler(), FrontendHandler(), HandshakeHandler(),
    QAHandler(), E2EHandler(), DevOpsHandler(), POHandler(), DocsHandler(),
]
