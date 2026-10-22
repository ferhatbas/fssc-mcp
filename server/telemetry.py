"""
Canlı Telemetri Havuzu (TelemetryHub) ve Çoklu Proje Yönetimi (Multi-Project Registry).
Genişletilmiş Yazılım Şirketi (Senior Backend, Senior Frontend, Playwright E2E Tester, Jira Task Board, Müşteri Şartname/Dosya Kasası).
"""

import asyncio
import re
import copy
import json
import os
import shutil
import sys
import uuid
from collections import deque
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set
from fastapi import WebSocket
from .config import DEFAULT_AGENTS, MAX_HISTORY_EVENTS, OPTIONAL_AGENTS
from .doc_text import is_readable, read_text
from .i18n import translate as tx, N_
from . import i18n as I18N
from .approval import ApprovalGate, DEFAULT_STEP_APPROVAL_TIMEOUT_S
from .deliberation import DeliberationEngine
from .runs import PipelineRun
from .event_store import append_event, tail_events
from .fs_workspace import (
    ensure_fs_workspace,
    build_workspace_files,
    write_files_atomic,
    load_project_from_workspace,
    get_agent_markdown_info,
    save_agent_markdown,
    restore_agent_version,
    inherit_from_standard,
    promote_to_global,
    record_agent_learning
)

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
PROJECTS_REGISTRY_FILE = os.environ.get(
    "AGY_REGISTRY_PATH",
    os.path.join(REPO_ROOT, "history", "projects_registry.json")
)
# Hiç proje kayıtlı değilse bağlanacak varsayılan hedef klasör (depo kökünün yanındaki demo_project)
DEFAULT_PROJECT_PATH = os.environ.get(
    "AGY_DEFAULT_PROJECT",
    os.path.abspath(os.path.join(REPO_ROOT, "..", "demo_project"))
)


def _refuse_real_paths_under_pytest() -> None:
    """Veri kaybı önlemi: modül düzeyindeki `hub = TelemetryHub()` içe aktarılır aktarılmaz registry'yi ve varsayılan projeyi (../demo_project)
    DİSKE YAZAR. pytest altında bunlar gerçek yollarsa (tests/conftest.py ortamı yönlendirmediyse) kullanıcının gerçek verisi ezilebilir:
    sessizce devam etmek yerine içe aktarmayı reddet."""
    if "pytest" not in sys.modules:
        return
    real_registry = os.path.abspath(os.path.join(REPO_ROOT, "history", "projects_registry.json"))
    real_project = os.path.abspath(os.path.join(REPO_ROOT, "..", "demo_project"))
    if (os.path.normcase(os.path.abspath(PROJECTS_REGISTRY_FILE)) == os.path.normcase(real_registry)
            or os.path.normcase(os.path.abspath(DEFAULT_PROJECT_PATH)) == os.path.normcase(real_project)):
        raise RuntimeError("Test koşusu gerçek registry/projeye (history/projects_registry.json, ../demo_project) dokunamaz: "
                           "AGY_REGISTRY_PATH ve AGY_DEFAULT_PROJECT geçici yollara yönlendirilmeli (tests/conftest.py).")


_refuse_real_paths_under_pytest()
# Kalıcılık yazıcısının birleştirme gecikmesi (saniye)
REGISTRY_FLUSH_DELAY_S = float(os.environ.get("AGY_REGISTRY_FLUSH_DELAY_S", "0.5"))


DEFAULT_SETTINGS: Dict[str, Any] = {
    "execution_engine": "mcp_client",   # 'mcp_client' (Claude Desktop / Antigravity) | 'template' (çevrimdışı)
    "approval_mode": "every_step",      # 'auto' | 'critical_only' | 'every_step' | 'note_and_continue'
    "pacing": "natural",                # 'instant' | 'natural'
    # Tam yaşam döngüsü (bkz. server/pipeline.py, server/verify.py, server/scm.py)
    "auto_backlog": True,      # mimari adımının backlog'u koşuya görev adımları olarak eklenir
    "auto_verify": True,       # her teslimden sonra sözdizimi/kurulum/build/test komutları sunucuda koşar
    "auto_commit": True,       # doğrulaması geçen teslimler SCM ajanı tarafından git'e commit'lenir
    "agent_skills": {"enabled": True, "roles": {}, "max_chars": 5000},    # ajanlara ek skill rehberleri (aitmpl.com/skills); rol için liste yoksa katalog varsayılanı
    "claude_design_url": "",         # Claude Design (claude.ai Artifact "Design") tuvalinin bağlantısı: Designer buradan okur / buraya yazar
    "design_first": True,            # arayüz işi var, tasarım yoksa: DESIGNER görevi (tasarım sistemi + ilk ekranlar, yönetici onaylı) frontend'den önce açılır
    "skip_satisfied_tasks": True,    # görevin dosyaları commit'li ve doğrulama geçiyorsa (TEST/DEVOPS/DOCS) ajana iş verilmeden sunucuca kapatılır
    "verify_light": True,            # artımlı adımlarda build de atlanır (lint + değişen testler); build her 5. adımdaki tam doğrulamada koşar
    "verify_scope": "incremental",   # 'incremental': görev/düzeltme adımlarında yalnızca değişen dosyaların testleri (her 5. adımda ve faz adımlarında tam paket); 'full': hep tam paket
    "max_fix_rounds": 2,       # doğrulama başarısızsa görev başına açılacak en fazla düzeltme turu
    "max_backlog_tasks": 40,   # tek yapılandırma geçişinde mimarın üretebileceği en fazla görev (güvenlik tavanı; sprint kipinde kalan hikâyeler sonraki geçişe kalır)
    "max_uat_rounds": 1,       # PO reddi sonrası açılacak en fazla iyileştirme turu
    "docs_root": None,         # belge klasörü (göreli); boşsa otomatik: yeni projede FS-docs, eski düzende docs (server/paths.py)
    "sandbox": {},             # F6/G4: mode (host | container), command_policy (allowlist varsayılan | denylist), allowlist[], image (bkz. server/guard.py)
    "runner": {},              # F5: interval_min, max_steps_per_session, abandon_factor (bkz. server/driver.py)
    "display": {},             # F5: verbosity summary | full
    "autonomy": {},            # F4: level (L0-L3), question_timeout_s (bkz. server/meetings.py); F5'te genişler
    "sprint": {},              # F3 (varsayılan: açık, sprintler zincirlenir, commit otomatik; kapatmak için {"enabled": false}) sprint kipi (bkz. server/sprint.py): enabled, max_tasks, commit_approval, auto_chain, carry_over_limit, max_sprints
    "verification": {},        # {install, test, build, lint, run, health_url, app_url} — mimar/DevOps önerir, kullanıcı düzenleyebilir
    "python_isolation": "venv",  # G1: proje bağımlılıkları projenin sanal ortamına (.fs-workspace/venv) kurulur; 'host' = FS-SC yorumlayıcısı (eski davranış)
    "llm_fallback": False,     # G1: geçersiz LLM çıktısında şablon yedeği ÜRETİLMEZ (adım FAILED); True = eski davranış (yalnızca deneme için)
    "project_language": "tr",  # proje dili (tr | en): ajan çıktısı, sunucu metinleri, ajan istemleri (bkz. server/i18n.py); pano dili ayrı bir tercihtir
    "product_first": True,     # ürün önce modu: backlog tavanı (backlog_cap), hedef odaklı çalışma, ekran uyumu kabul kapısı (fidelity_gate)
    "backlog_cap": 25,         # ürün önce modunda açık backlog işi bu sayıya ulaşınca mimar/PO/karar bölümü yeni iş açmaz
    "fidelity_gate": True,     # tasarım ekranı görevi mockup ile karşılaştırılmadan bitmiş sayılmaz
    "product_statement": "",   # yönetici ürün tanımı (bağlayıcı): şartname/toplantı notlarındaki ÖRNEKLERİN üstündedir, her adımın bağlamına girer
    "claude": {},              # G2: cli, max_turns, model, extra_args, transcripts_dir, auto_watch (bkz. server/claude_bridge.py)
}
MAX_PERSISTED_RUNS = 200


def _default_settings() -> Dict[str, Any]:
    return dict(DEFAULT_SETTINGS)


DEFAULT_PROVIDER = "claude"
DEFAULT_MODEL_ID = "claude-sonnet-5-5"
_LEGACY_DEFAULT_MODEL = ("gemini", "gemini-2.5-pro")  # eski varsayılan: kullanıcı seçmediyse Claude'a taşınır


def _default_model_config() -> Dict[str, Any]:
    return {
        "provider": DEFAULT_PROVIDER,
        "model_id": DEFAULT_MODEL_ID,
        "temperature": 0.2,
        "max_tokens": 8192,
        "updated_at": datetime.now(timezone.utc).isoformat()
    }


def _normalize_model_config(cfg: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Boş ya da eski Gemini varsayılanında kalmış yapılandırmayı güncel Claude varsayılanına çevirir."""
    if not cfg or not isinstance(cfg, dict):
        return _default_model_config()
    if (str(cfg.get("provider", "")).lower(), str(cfg.get("model_id", ""))) == _LEGACY_DEFAULT_MODEL:
        return {**_default_model_config(), "temperature": cfg.get("temperature", 0.2), "max_tokens": cfg.get("max_tokens", 8192)}
    return cfg


def create_default_jira_issues(lang: Optional[str] = None) -> Dict[str, Dict[str, Any]]:
    """Uçtan uca yazılım ajansı pipeline'ı için standart Jira görev listesini (JIRA-1 .. JIRA-10) üretir."""
    if lang and I18N.normalize(lang) != I18N.current():       # `tx(..., lang=)` konumsal-yalnız parametre olduğundan dil bağlamla verilir
        with I18N.use_lang(lang):
            return create_default_jira_issues()
    now = datetime.now(timezone.utc).isoformat()
    return {
        "JIRA-1": {
            "id": "JIRA-1",
            "key": "DEV-1",
            "order": 1,
            "title": tx("Müşteri Görüşmeleri & PRD Gereksinim Analizi", lang=lang),
            "description": tx("Müşteri görüşme notlarını ve şartnamesini analiz et, iş gereksinimlerini ve kullanıcı kabul kriterlerini PRD dokümanına dök.", lang=lang),
            "issue_type": "EPIC",
            "status": "BACKLOG",
            "priority": "P0",
            "assignee": "PM",
            "acceptance_criteria": [
                tx("Müşteri görüşme notları ve yüklenen dosyalar incelendi", lang=lang),
                tx("docs/PRD.md iş gereksinimleri oluşturuldu", lang=lang),
                tx("Kullanıcı kabul kriterleri (Acceptance Criteria) tanımlandı", lang=lang)
            ],
            "attachments": [],
            "audit_trail": [],
            "created_at": now,
            "updated_at": now
        },
        "JIRA-2": {
            "id": "JIRA-2",
            "key": "DEV-2",
            "order": 2,
            "title": tx("Sistem Mimarisi, API Sözleşmesi & Veri Modelleri", lang=lang),
            "description": tx("Takım lideri / Architect değerlendirmesi: OpenAPI 3.0 şemaları, veri modelleri ve servis mimarisini tasarla.", lang=lang),
            "issue_type": "STORY",
            "status": "BACKLOG",
            "priority": "P0",
            "assignee": "ARCHITECT",
            "acceptance_criteria": [
                tx("OpenAPI JSON ve Pydantic veri modelleri oluşturuldu", lang=lang),
                tx("Frontend ve Backend geliştiriciler için API sözleşmesi donduruldu", lang=lang),
                tx("Hata kodları ve HTTP durum standartları belirlendi", lang=lang)
            ],
            "attachments": [],
            "audit_trail": [],
            "created_at": now,
            "updated_at": now
        },
        "JIRA-3": {
            "id": "JIRA-3",
            "key": "DEV-3",
            "order": 3,
            "title": tx("Senior Backend: Core Auth & REST Servisleri", lang=lang),
            "description": tx("Senior Backend Developer: Kimlik doğrulama, token yönetimi, veritabanı modelleri ve CRUD API uç noktalarını geliştir.", lang=lang),
            "issue_type": "TASK",
            "status": "BACKLOG",
            "priority": "P0",
            "assignee": "BACKEND_DEV",
            "acceptance_criteria": [
                tx("FastAPI REST servisleri ve auth middleware yazıldı", lang=lang),
                tx("JWT imzalama ve doğrulama mantığı entegre edildi", lang=lang),
                tx("İş mantığı exception handler ile korundu", lang=lang)
            ],
            "attachments": [],
            "audit_trail": [],
            "created_at": now,
            "updated_at": now
        },
        "JIRA-4": {
            "id": "JIRA-4",
            "key": "DEV-4",
            "order": 4,
            "title": tx("Senior Frontend: Responsive UI & API Client Entegrasyonu", lang=lang),
            "description": tx("Senior Frontend Developer: React / Tailwind / Vite kullanıcı arayüzü, state yönetimi ve API entegrasyonunu tamamla.", lang=lang),
            "issue_type": "TASK",
            "status": "BACKLOG",
            "priority": "P0",
            "assignee": "FRONTEND_DEV",
            "acceptance_criteria": [
                tx("Modern kullanıcı deneyimine sahip responsive bileşenler kodlandı", lang=lang),
                tx("Giriş ve veri yönetim formları bağlandı", lang=lang),
                tx("API istemcisi Backend sözleşmesiyle senkronize edildi", lang=lang)
            ],
            "attachments": [],
            "audit_trail": [],
            "created_at": now,
            "updated_at": now
        },
        "JIRA-5": {
            "id": "JIRA-5",
            "key": "DEV-5",
            "order": 5,
            "title": tx("Peer Review & Backend-Frontend API Handshake", lang=lang),
            "description": tx("Senior Backend ve Senior Frontend geliştiriciler arası doğrudan A2A iletişim: İstek/yanıt modelleri, CORS ve token senkronizasyonu.", lang=lang),
            "issue_type": "TASK",
            "status": "BACKLOG",
            "priority": "P1",
            "assignee": "BACKEND_DEV",
            "acceptance_criteria": [
                tx("Geliştiriciler karşılıklı API kontratını doğruladı", lang=lang),
                tx("CORS ve token header geçişleri teyit edildi", lang=lang),
                tx("Uçtan uca mock istekleriyle senkronizasyon sağlandı", lang=lang)
            ],
            "attachments": [],
            "audit_trail": [],
            "created_at": now,
            "updated_at": now
        },
        "JIRA-6": {
            "id": "JIRA-6",
            "key": "DEV-6",
            "order": 6,
            "title": tx("QA Kapsamlı Test & Bug Taraması", lang=lang),
            "description": tx("Lead QA Engineer: Birim testleri, regresyon testleri ve edge case taramaları koştur, bulunan bug'ları raporla ve doğrulama yap.", lang=lang),
            "issue_type": "TASK",
            "status": "BACKLOG",
            "priority": "P0",
            "assignee": "QA",
            "acceptance_criteria": [
                tx("Birim testler ve edge-case senaryoları çalıştırıldı", lang=lang),
                tx("Tespit edilen bug'lar Developer'a iletilip kapatıldı", lang=lang),
                tx("Tüm fonksiyonel gereksinimler doğrulandı", lang=lang)
            ],
            "attachments": [],
            "audit_trail": [],
            "created_at": now,
            "updated_at": now
        },
        "JIRA-7": {
            "id": "JIRA-7",
            "key": "DEV-7",
            "order": 7,
            "title": tx("Playwright E2E Otomasyonu (Tarayıcı Giriş & Akış Testi)", lang=lang),
            "description": tx("Playwright E2E Tester: Gerçek Chromium tarayıcısı açılır, uygulamaya login olunur, kritik akışlar test edilir ve ekran görüntüleri raporlanır.", lang=lang),
            "issue_type": "TASK",
            "status": "BACKLOG",
            "priority": "P0",
            "assignee": "E2E_TESTER",
            "acceptance_criteria": [
                tx("Playwright Chromium tarayıcısı canlı uygulamayı açtı", lang=lang),
                tx("Kullanıcı giriş ve form etkileşimi simüle edildi", lang=lang),
                tx("Rapor ve ekran görüntüleri sisteme kaydedildi", lang=lang)
            ],
            "attachments": [],
            "audit_trail": [],
            "created_at": now,
            "updated_at": now
        },
        "JIRA-8": {
            "id": "JIRA-8",
            "key": "DEV-8",
            "order": 8,
            "title": tx("DevOps Dağıtım & Docker/Health Kontrolü", lang=lang),
            "description": tx("DevOps & SRE: Dockerfile, Docker Compose yapılandırması, staging ortamı dağıtımı ve sağlık kontrolü (health check).", lang=lang),
            "issue_type": "TASK",
            "status": "BACKLOG",
            "priority": "P0",
            "assignee": "DEVOPS",
            "acceptance_criteria": [
                tx("Dockerfile ve docker-compose konfigürasyonu üretildi", lang=lang),
                tx("Healthcheck endpoint doğrulandı", lang=lang),
                tx("Team Lead ve PM'e release onayı iletildi", lang=lang)
            ],
            "attachments": [],
            "audit_trail": [],
            "created_at": now,
            "updated_at": now
        },
        "JIRA-9": {
            "id": "JIRA-9",
            "key": "DEV-9",
            "order": 9,
            "title": tx("Product Owner (PO) UAT & Nihai Müşteri Kabulü", lang=lang),
            "description": tx("Product Owner: Geliştirilen ekranları, API yanıtlarını ve PRD gereksinimlerini kontrol et, UAT testini onayla ve eksiklikleri tespit et.", lang=lang),
            "issue_type": "STORY",
            "status": "BACKLOG",
            "priority": "P0",
            "assignee": "PO",
            "acceptance_criteria": [
                tx("Kullanıcı kabul kriterleri PRD ile birebir doğrulandı", lang=lang),
                tx("Kullanıcı deneyimi (UX/UI) denetlendi ve UAT onayı verildi", lang=lang),
                tx("Eksik özellik veya iyileştirme açılmadıysa canlı sürüme onay verildi", lang=lang)
            ],
            "attachments": [],
            "audit_trail": [],
            "created_at": now,
            "updated_at": now
        },
        "JIRA-10": {
            "id": "JIRA-10",
            "key": "DEV-10",
            "order": 10,
            "title": tx("Documentor & Reporter: Kullanım Kılavuzu & Yönetici Özeti", lang=lang),
            "description": tx("Documentor Ajanı son kullanıcı kullanım kılavuzunu (docs/manuals/user_guide.md) üretir; Reporter Ajanı ise sprint özetini ve metriklerini yönetici raporuna (docs/reports/status_report.md) döker.", lang=lang),
            "issue_type": "TASK",
            "status": "BACKLOG",
            "priority": "P0",
            "assignee": "DOCUMENTOR",
            "acceptance_criteria": [
                tx("docs/manuals/user_guide.md kullanım kılavuzu oluşturuldu", lang=lang),
                tx("README.md ve API referansları güncellendi", lang=lang),
                tx("docs/reports/status_report.md yönetici durum özeti hazırlandı", lang=lang)
            ],
            "attachments": [],
            "audit_trail": [],
            "created_at": now,
            "updated_at": now
        }
    }


def create_default_test_profiles(lang: Optional[str] = None) -> List[Dict[str, Any]]:
    """Hazır test kullanıcısı şablonlarını (Admin, Standart, Editör, Finans, Negatif Test) üretir."""
    if lang and I18N.normalize(lang) != I18N.current():
        with I18N.use_lang(lang):
            return create_default_test_profiles()
    return [
        {
            "id": "preset-admin",
            "name": tx("Admin / Süper Yönetici", lang=lang),
            "target_url": "http://127.0.0.1:8099",
            "username": "admin@enterprise.local",
            "password": "AdminSuperSecure2026!",
            "role": "ADMIN",
            "description": tx("Tüm modüllere tam yetkili yönetici erişimi ve kritik panel testi", lang=lang),
            "is_preset": True
        },
        {
            "id": "preset-user",
            "name": tx("Standart Müşteri / Son Kullanıcı", lang=lang),
            "target_url": "http://127.0.0.1:8099",
            "username": "user@enterprise.local",
            "password": "StandardUserPass123!",
            "role": "USER",
            "description": tx("Temel kullanıcı kaydı, profil görüntüleme ve form akışları", lang=lang),
            "is_preset": True
        },
        {
            "id": "preset-editor",
            "name": tx("Mağaza & İçerik Editörü", lang=lang),
            "target_url": "http://127.0.0.1:8099",
            "username": "editor@enterprise.local",
            "password": "EditorSecure#2026",
            "role": "EDITOR",
            "description": tx("Katalog yönetimi, içerik güncelleme ve yayınlama yetkisi", lang=lang),
            "is_preset": True
        },
        {
            "id": "preset-finance",
            "name": tx("Finans & Muhasebe Sorumlusu", lang=lang),
            "target_url": "http://127.0.0.1:8099",
            "username": "finance@enterprise.local",
            "password": "FinanceVaultSecure$$",
            "role": "FINANCE",
            "description": tx("Ödeme, fatura ve sipariş mutabakat ekranları testi", lang=lang),
            "is_preset": True
        },
        {
            "id": "preset-negative",
            "name": tx("Güvenlik Saldırısı / Hatalı Giriş (Negatif Test)", lang=lang),
            "target_url": "http://127.0.0.1:8099",
            "username": "hacker@attack.test",
            "password": "invalid_wrong_pass",
            "role": "GUEST",
            "description": tx("401/403 yetkisiz erişim kontrolü ve form hata doğrulaması", lang=lang),
            "is_preset": True
        }
    ]


def retranslate_defaults(hub: Any, lang: Optional[str] = None) -> Dict[str, int]:
    """Proje dili değişince hub'ın başlangıçta ürettiği varsayılan nesneleri (JIRA-1..10 başlık/açıklama/kabul kriteri, varsayılan ajan açıklamaları,
    hazır test profilleri) yeni dile çevirir. YALNIZCA hâlâ herhangi bir dildeki varsayılan metni taşıyan alanlar çevrilir; kullanıcı/ajan düzenlediği alan,
    özel Jira maddesi ve özel ajan/profil olduğu gibi kalır. Ajan kimlikleri (PM, QA...) değişmez. Döner: {"jira": n, "agents": n, "profiles": n} (değişen alan sayıları)."""
    from .config import default_agent_descriptions
    lg = I18N.normalize(lang) if lang else I18N.project_lang(hub)
    counts = {"jira": 0, "agents": 0, "profiles": 0}

    def _all_langs(factory):
        return {l: factory(l) for l in I18N.SUPPORTED}

    # Jira: JIRA-1..10 (başlık, açıklama, kabul kriteri maddeleri tek tek)
    by_lang = _all_langs(create_default_jira_issues)
    fresh = by_lang[lg]
    for key, new in fresh.items():
        issue = (getattr(hub, "jira_issues", None) or {}).get(key)
        if not isinstance(issue, dict):
            continue
        for fld in ("title", "description"):
            if issue.get(fld) in {by_lang[l][key][fld] for l in by_lang} and issue.get(fld) != new[fld]:
                issue[fld] = new[fld]
                counts["jira"] += 1
        ac = issue.get("acceptance_criteria")
        if isinstance(ac, list):
            for i, item in enumerate(ac):
                if i < len(new["acceptance_criteria"]) and item in {by_lang[l][key]["acceptance_criteria"][i] for l in by_lang} and item != new["acceptance_criteria"][i]:
                    ac[i] = new["acceptance_criteria"][i]
                    counts["jira"] += 1

    # Varsayılan ajanlar: yalnızca açıklama (ad ve kimlik değişmez)
    for aid, src in default_agent_descriptions().items():
        agent = (getattr(hub, "agents", None) or {}).get(aid)
        if isinstance(agent, dict) and I18N.matches(agent.get("description", ""), src):
            new_desc = tx(src, lang=lg)
            if agent.get("description") != new_desc:
                agent["description"] = new_desc
                counts["agents"] += 1

    # Hazır test profilleri
    prof_by_lang = _all_langs(create_default_test_profiles)
    fresh_profiles = {p["id"]: p for p in prof_by_lang[lg]}
    for prof in getattr(hub, "test_profiles", None) or []:
        new = fresh_profiles.get(prof.get("id")) if isinstance(prof, dict) else None
        if not new:
            continue
        for fld in ("name", "description"):
            olds = {next(p for p in prof_by_lang[l] if p["id"] == prof["id"])[fld] for l in prof_by_lang}
            if prof.get(fld) in olds and prof.get(fld) != new[fld]:
                prof[fld] = new[fld]
                counts["profiles"] += 1
    return counts


class TelemetryHub:
    def __init__(
        self,
        registry_path: Optional[str] = None,
        default_project_path: Optional[str] = None,
        flush_delay_s: Optional[float] = None
    ):
        # Enjekte edilebilir kalıcılık yolları (testler izole hub oluşturabilir)
        self.registry_path: str = os.path.abspath(registry_path or PROJECTS_REGISTRY_FILE)
        self.default_project_path: str = os.path.abspath(default_project_path or DEFAULT_PROJECT_PATH)
        self.flush_delay_s: float = REGISTRY_FLUSH_DELAY_S if flush_delay_s is None else flush_delay_s

        self.active_connections: Set[WebSocket] = set()
        self.projects: Dict[str, Dict[str, Any]] = {}
        self.active_project_id: str = "demo_project"

        # Anlık aktif proje state referansları
        self.events: deque = deque(maxlen=MAX_HISTORY_EVENTS)
        self.tasks: Dict[str, Dict[str, Any]] = {}
        self.agents: Dict[str, Dict[str, Any]] = self._create_initial_agents()
        self.jira_issues: Dict[str, Dict[str, Any]] = create_default_jira_issues()
        self.uploaded_specs: List[Dict[str, Any]] = []
        self.sprint_state: Dict[str, Any] = {}   # F3: sprint durumu (bkz. server/sprint.py)
        self.question_store: Dict[str, Any] = {}  # F4: soru kuyruğu (.fs-workspace/questions.json, bkz. server/meetings.py)
        self.playwright_reports: List[Dict[str, Any]] = []
        self.test_profiles: List[Dict[str, Any]] = create_default_test_profiles()
        self.deliberation_engine = DeliberationEngine(self)

        # Olay kimliği sayacı (deque maxlen'den bağımsız, proje istatistiğinde kalıcı)
        self._event_seq: int = 0

        # Adım Adım İnceleme & Onay Durumu (Human-in-the-loop Step Approval)
        self.gate = ApprovalGate()
        self.pending_step_approval: Optional[Dict[str, Any]] = None
        self.approval_token: Optional[str] = None
        self.auto_proceed_all: bool = False
        self.auto_proceed_run_id: Optional[str] = None  # AUTO_ALL yalnızca bu koşu için geçerlidir
        self.step_by_step_mode: bool = True  # Varsayılan: Aksi seçilmedikçe ilerlemesin (onay şart)
        self.active_run_id: Optional[str] = None  # Aynı anda tek pipeline koşusu

        # Pipeline koşuları (tüm projeler), proje ayarları ve bağlı MCP istemcileri
        self.runs: Dict[str, PipelineRun] = {}
        self.settings: Dict[str, Any] = _default_settings()
        self.connected_clients: Dict[str, Dict[str, Any]] = {}
        # 'note_and_continue' modunda kaydedilen el kaldırmalar (kullanıcı sonradan inceler)
        self.raised_hands: List[Dict[str, Any]] = []
        from . import i18n as _i18n
        _i18n.set_resolver(lambda: (self.settings or {}).get("project_language"))      # `_()` bağlam kurulu değilken aktif projenin dilini kullanır

        self.stats = {
            "total_events": 0,
            "total_tokens": 0,
            "active_tasks_count": 0,
            "event_seq": 0,
            "start_time": datetime.now(timezone.utc).isoformat()
        }

        # Varsayılan LLM Model Konfigürasyonu (Gemini vs Claude)
        self.model_config: Dict[str, Any] = _default_model_config()

        # Kalıcılık yazıcısı (birleştirilmiş, event loop'u bloklamayan)
        self._dirty: bool = False
        self._flush_handle: Optional[asyncio.TimerHandle] = None
        self._flush_task: Optional["asyncio.Task[None]"] = None

        # Veri dayanıklılığı (server/durability.py): düzenli anlık görüntü ve bütünlük uyarıları
        self.data_warnings: Dict[str, List[Dict[str, Any]]] = {}
        self._last_snapshot_at: float = 0.0
        self.snapshot_interval_s: float = float(os.environ.get("AGY_SNAPSHOT_INTERVAL_S", "1800"))

        # Kayıtlı projeleri diskten oku
        self.load_registry()

    def _create_initial_agents(self, lang: Optional[str] = None) -> Dict[str, Dict[str, Any]]:
        return {
            a["id"]: {
                **a,
                "description": tx(a["description"], lang),      # proje diline çevrilmiş varsayılan açıklama (dil değişince retranslate_defaults)
                "tokens_in": 0,
                "tokens_out": 0,
                "total_tokens": 0,
                "last_action": "INITIALIZED",
                "last_seen": datetime.now(timezone.utc).isoformat()
            }
            for a in DEFAULT_AGENTS
        }

    def _ensure_default_agents(self):
        """Varsayılan rollerin (PO, SCM, Reporter, Documentor dahil) mevcut projede eksiksiz olduğunu doğrular."""
        for def_agent in DEFAULT_AGENTS:
            if def_agent["id"] not in self.agents:
                self.agents[def_agent["id"]] = {
                    **def_agent,
                    "description": tx(def_agent["description"]),
                    "tokens_in": 0,
                    "tokens_out": 0,
                    "total_tokens": 0,
                    "last_action": "INITIALIZED",
                    "last_seen": datetime.now(timezone.utc).isoformat()
                }

    def _ensure_optional_agents(self) -> None:
        """Varsayılan isteğe bağlı çekirdek ajanlar (Mobile Designer, Security, SEO, Code Reviewer): projede yoksa ve kullanıcı kaldırmadıysa eklenir."""
        removed = set((self.settings or {}).get("removed_default_agents") or [])
        for d in OPTIONAL_AGENTS:
            if d["id"] in self.agents or d["id"] in removed:
                continue
            self.agents[d["id"]] = {**copy.deepcopy(d), "description": tx(d["description"]), "active_file": "", "tokens_in": 0, "tokens_out": 0, "total_tokens": 0,
                                    "last_action": "INITIALIZED", "last_seen": datetime.now(timezone.utc).isoformat()}

    async def restore_default_agents(self) -> List[str]:
        """Kaldırılmış varsayılan isteğe bağlı ajanları geri getirir; eklenen kimlikleri döner."""
        before = set(self.agents)
        self.settings = {**(self.settings or {}), "removed_default_agents": []}
        self._ensure_optional_agents()
        added = sorted(set(self.agents) - before)
        if added:
            self.mark_dirty()
            await self.broadcast({"type": "AGENTS_UPDATED", "agents": list(self.agents.values())})
        return added

    def _pool_auto(self, pool_id: str) -> bool:
        try:
            from . import agent_registry as AR
            return bool((AR.load_global().get(pool_id) or {}).get("auto_assign"))
        except Exception:
            return False

    async def add_pool_agent(self, pool_id: str, mode: str = "linked", new_id: str = "") -> Dict[str, Any]:
        """Ajan havuzundan bu projeye ajan ekler (bağlı ya da bağımsız kopya)."""
        from . import agent_registry as AR
        rec = AR.add_from_pool(self.agents, pool_id, mode, new_id)
        self.mark_dirty()
        self.save_registry()
        return rec

    def _sync_global_agents(self) -> List[str]:
        """G6: şirket geneli ajan kaydı (agents/registry.json) bu projede görünür; farkı (`overrides`) olmayan alanlar globalden yenilenir."""
        try:
            from . import agent_registry as AR
            return AR.sync_globals(self.agents)
        except Exception:
            return []

    def _ensure_default_jira_issues(self):
        """Tüm standart 10 Jira görevinin (PO UAT ve Dokümantasyon dahil) eksiksiz olduğunu doğrular."""
        def_issues = create_default_jira_issues()
        for k, d_issue in def_issues.items():
            if k not in self.jira_issues:
                self.jira_issues[k] = copy.deepcopy(d_issue)
        for issue in self.jira_issues.values():
            if "audit_trail" not in issue:
                issue["audit_trail"] = []

    # -------------------------------------------------------------------------
    # Kalıcılık: birleştirilmiş, event loop'u bloklamayan yazıcı
    # -------------------------------------------------------------------------
    def _sync_active_to_projects(self):
        """Aktif projenin canlı durumunu `self.projects` sözlüğündeki kaydına kopyalar."""
        if self.active_project_id not in self.projects:
            return
        proj = self.projects[self.active_project_id]
        proj["events"] = list(self.events)
        proj["tasks"] = copy.deepcopy(self.tasks)
        proj["agents"] = copy.deepcopy(self.agents)
        proj["jira_issues"] = copy.deepcopy(self.jira_issues)
        proj["uploaded_specs"] = copy.deepcopy(self.uploaded_specs)
        proj["sprint_state"] = copy.deepcopy(self.sprint_state)
        proj["question_store"] = copy.deepcopy(self.question_store)
        proj["playwright_reports"] = copy.deepcopy(self.playwright_reports)
        proj["deliberation"] = copy.deepcopy(self.deliberation_engine.snapshot())
        proj["test_profiles"] = copy.deepcopy(self.test_profiles)
        proj["stats"] = copy.deepcopy(self.stats)
        proj["model_config"] = copy.deepcopy(self.model_config)
        proj["settings"] = copy.deepcopy(self.settings)
        proj["raised_hands"] = copy.deepcopy(self.raised_hands)
        proj["last_active"] = datetime.now(timezone.utc).isoformat()

    def _load_active_from_projects(self, proj: Dict[str, Any]):
        """`self.projects` kaydındaki veriyi canlı hub alanlarına yükler."""
        self.events = deque(copy.deepcopy(proj.get("events", [])), maxlen=MAX_HISTORY_EVENTS)
        rehydrated = False
        if not self.events and proj.get("path"):
            # Registry yeniden oluşmuş/boşalmış olabilir: canlı akış boş kalır ve olay kimlikleri evt-000001'den yeniden başlayıp dosyadakilerle çakışır.
            # Kalıcı olay deposundan (.fs-workspace/events.jsonl) son olayları belleğe geri yükle.
            try:
                self.events.extend(tail_events(proj["path"], MAX_HISTORY_EVENTS))
                rehydrated = bool(self.events)
            except Exception:
                pass
        self.tasks = copy.deepcopy(proj.get("tasks", {}))
        self.agents = copy.deepcopy(proj.get("agents") or self._create_initial_agents())
        self._ensure_default_agents()
        self._sync_global_agents()
        self.jira_issues = copy.deepcopy(proj.get("jira_issues") or create_default_jira_issues())
        self._ensure_default_jira_issues()
        self.uploaded_specs = copy.deepcopy(proj.get("uploaded_specs", []))
        self.sprint_state = copy.deepcopy(proj.get("sprint_state") or {})
        self.question_store = copy.deepcopy(proj.get("question_store") or {})
        self.playwright_reports = copy.deepcopy(proj.get("playwright_reports", []))
        self.deliberation_engine.restore(proj.get("deliberation"))
        self.test_profiles = copy.deepcopy(proj.get("test_profiles") or create_default_test_profiles())
        self.model_config = copy.deepcopy(_normalize_model_config(proj.get("model_config")))
        self.settings = {**_default_settings(), **(proj.get("settings") or {})}
        self._ensure_optional_agents()          # kaldırılmış varsayılanlar (removed_default_agents) bu projenin ayarından okunur
        self.raised_hands = copy.deepcopy(proj.get("raised_hands") or [])
        self.step_by_step_mode = self.settings.get("approval_mode", "every_step") != "auto"
        self.stats = copy.deepcopy(proj.get("stats") or {
            "total_events": len(self.events),
            "total_tokens": sum(e.get("tokens_used", 0) for e in self.events),
            "active_tasks_count": len(self.tasks),
            "start_time": datetime.now(timezone.utc).isoformat()
        })
        self.stats["active_tasks_count"] = len(self.tasks)
        if self.events:
            # Başlık sayaçları (toplam olay / token) ve ajan token toplamları sıfırlanmış olabilir (registry yeniden oluştu, sayaçlar 0 kaydedildi):
            # sayaçlar birikimlidir, bellekteki olaylardan türeyen değerin altına inemez.
            self.stats["total_events"] = max(int(self.stats.get("total_events", 0) or 0), len(self.events))
            self.stats["total_tokens"] = max(int(self.stats.get("total_tokens", 0) or 0), sum(e.get("tokens_used", 0) or 0 for e in self.events))
            per_agent: Dict[str, int] = {}
            for e in self.events:
                per_agent[e.get("from_agent")] = per_agent.get(e.get("from_agent"), 0) + int(e.get("tokens_used", 0) or 0)
            for aid, total in per_agent.items():
                a = self.agents.get(aid)
                if a is not None and not a.get("total_tokens"):
                    a["total_tokens"] = total
        self._event_seq = self._derive_event_seq()
        self.stats["event_seq"] = self._event_seq

    def _derive_event_seq(self) -> int:
        """Kaydedilmiş sayaç yoksa mevcut olay kimliklerinden en büyük sırayı türetir."""
        seq = int(self.stats.get("event_seq", 0) or 0)
        for e in self.events:
            eid = str(e.get("id", ""))
            if eid.startswith("evt-"):
                try:
                    seq = max(seq, int(eid[4:]))
                except ValueError:
                    continue
        return seq

    def _apply_workspace_overrides(self, proj: Dict[str, Any], ppath: str):
        """Hedef projenin .fs-workspace dizinindeki güncel verileri proje kaydına uygular."""
        if not ppath or not os.path.isdir(ppath):
            return
        ensure_fs_workspace(ppath)
        ws_data = load_project_from_workspace(ppath)
        if not ws_data:
            return
        if "jira_issues" in ws_data:
            proj["jira_issues"] = ws_data["jira_issues"]
        if "tasks" in ws_data:
            proj["tasks"] = ws_data["tasks"]
        if "uploaded_specs" in ws_data:
            proj["uploaded_specs"] = ws_data["uploaded_specs"]
        if ws_data.get("sprint_state"):
            proj["sprint_state"] = ws_data["sprint_state"]
        if ws_data.get("question_store"):
            proj["question_store"] = ws_data["question_store"]
        if ws_data.get("model_config"):
            proj["model_config"] = ws_data["model_config"]
        if ws_data.get("settings"):
            proj["settings"] = {**_default_settings(), **ws_data["settings"]}
        if isinstance(ws_data.get("verification"), dict) and ws_data["verification"]:
            cur = proj.setdefault("settings", {})
            if not cur.get("verification"):                 # ayar sıfırlanmışsa git'teki yedekten geri gelir; kullanıcının güncel ayarı ezilmez
                cur["verification"] = ws_data["verification"]
        if ws_data.get("playwright_reports"):
            proj["playwright_reports"] = ws_data["playwright_reports"]
        if ws_data.get("deliberation"):
            proj["deliberation"] = ws_data["deliberation"]
        self._merge_runs(ws_data.get("runs"))

    def _merge_runs(self, run_dicts) -> int:
        """Koşu geçmişini `.fs-workspace/runs.json`'dan geri yükler (registry boşalmış/yeniden oluşmuşsa); var olan koşular ezilmez.
        Süren görünenler ABANDONED sayılır (sunucu yeniden başladı)."""
        added = 0
        for rd in run_dicts or []:
            try:
                run = PipelineRun.from_dict(rd)
            except Exception:
                continue
            if run.run_id in self.runs:
                continue
            if not run.is_terminal:
                run.finish("ABANDONED", reason="server-restart")
            self.runs[run.run_id] = run
            added += 1
        return added

    async def restore_snapshot(self, name: str, files: Optional[List[str]] = None) -> List[str]:
        """Etkin projenin çalışma klasörünü seçilen anlık görüntüden geri yükler ve canlı durumu diskten yeniden okur."""
        from . import durability as DUR
        proj = self.projects.get(self.active_project_id) or {}
        path = proj.get("path")
        if not path:
            raise KeyError(self.active_project_id)
        restored = await asyncio.to_thread(DUR.restore_snapshot, path, name, files)
        self._cancel_flush_handle()
        self._apply_workspace_overrides(proj, path)
        self._load_active_from_projects(proj)
        self.data_warnings.pop(self.active_project_id, None)
        self.mark_dirty()
        return restored

    def _build_persist_payload(self) -> Dict[str, str]:
        """Diske yazılacak tüm dosyaları {yol: içerik} olarak event loop üzerinde serileştirir."""
        self._sync_active_to_projects()
        files: Dict[str, str] = {}
        runs_sorted = sorted(self.runs.values(), key=lambda r: r.created_at, reverse=True)[:MAX_PERSISTED_RUNS]
        data = {
            "active_project_id": self.active_project_id,
            "projects": self.projects,
            "runs": [r.to_dict() for r in runs_sorted],
            "saved_at": datetime.now(timezone.utc).isoformat()
        }
        files[self.registry_path] = json.dumps(data, ensure_ascii=False, indent=2)

        proj = self.projects.get(self.active_project_id)
        if proj:
            ppath = proj.get("path")
            if ppath and os.path.isdir(ppath):
                try:
                    project_runs = [r.to_dict() for r in runs_sorted if r.project_id == self.active_project_id]
                    files.update(build_workspace_files(ppath, {**proj, "runs": project_runs}))
                except Exception:
                    pass
        return files

    def _cancel_flush_handle(self):
        if self._flush_handle is not None:
            self._flush_handle.cancel()
            self._flush_handle = None

    def _live_flush_task(self) -> Optional["asyncio.Task[None]"]:
        """Bu event loop'a ait, hâlâ süren yazım görevi (farklı loop'takiler yok sayılır)."""
        task = self._flush_task
        if task is None or task.done():
            return None
        try:
            if task.get_loop() is not asyncio.get_running_loop():
                return None
        except RuntimeError:
            return None
        return task

    def flush_now(self):
        """Senkron, anında kalıcılık (başlangıç, kapanış ve loop dışı çağrılar için)."""
        self._dirty = False
        self._cancel_flush_handle()
        try:
            write_files_atomic(self._build_persist_payload(), backup={self.registry_path})
        except Exception:
            pass

    async def flush_async(self):
        """Bekleyen değişiklikleri hemen, ama event loop'u bloklamadan diske yazar."""
        self._cancel_flush_handle()
        running = self._live_flush_task()
        if running is not None and running is not asyncio.current_task():
            try:
                await running
            except Exception:
                pass
        self._dirty = False
        payload = self._build_persist_payload()
        try:
            await asyncio.to_thread(write_files_atomic, payload, {self.registry_path})
        except Exception:
            pass
        try:
            await asyncio.to_thread(self._maybe_snapshot, "auto")
        except Exception:
            pass

    def _start_flush_task(self):
        self._flush_handle = None
        if self._live_flush_task() is not None:
            # Yazım sürerken yeni değişiklik geldi; yazım bitince tekrar planlanır
            self._dirty = True
            return
        self._flush_task = asyncio.create_task(self._flush_and_reschedule())

    async def _flush_and_reschedule(self):
        await self.flush_async()
        if self._dirty:
            self.mark_dirty()

    def mark_dirty(self):
        """Durumun değiştiğini işaretler; yazım `flush_delay_s` içinde birleştirilerek yapılır."""
        self._dirty = True
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # Event loop yok (başlangıç / senkron bağlam): hemen yaz
            self.flush_now()
            return
        if self._flush_handle is not None:
            return
        if self.flush_delay_s <= 0:
            self._start_flush_task()
        else:
            self._flush_handle = loop.call_later(self.flush_delay_s, self._start_flush_task)

    async def aclose(self):
        """Kapanış: planlı yazımı iptal eder, süren yazımı bekler ve son durumu diske yazar."""
        self._cancel_flush_handle()
        running = self._live_flush_task()
        if running is not None:
            try:
                await running
            except Exception:
                pass
        await self.flush_async()

    def save_registry(self):
        """Geriye dönük uyumluluk: durumu kirli işaretler (birleştirilmiş asenkron yazım)."""
        self.mark_dirty()

    def _read_registry_file(self) -> Dict[str, Any]:
        """G3: kayıt dosyasını okur. Bozuksa `.corrupt-<zaman>` kopyası alınır ve son sağlam yazım (`.bak`) denenir; o da yoksa boş başlar.
        Sonuç `load_error` alanında (ve stderr'de) görünür; bozuk dosya sessizce ezilmez."""
        self.load_error = None
        try:
            with open(self.registry_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                raise ValueError("kök nesne sözlük değil")
            return data
        except Exception as e:  # noqa: BLE001
            stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
            corrupt = f"{self.registry_path}.corrupt-{stamp}"
            try:
                shutil.copyfile(self.registry_path, corrupt)
            except Exception:
                corrupt = None
            bak = self.registry_path + ".bak"
            try:
                with open(bak, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if not isinstance(data, dict):
                    raise ValueError("yedek bozuk")
                self.load_error = tx("Kayıt dosyası bozuktu ({err}); son sağlam yedekten yüklendi ({bak}). Bozuk kopya: {corrupt}", err=str(e)[:120], bak=os.path.basename(bak), corrupt=corrupt)
            except Exception:
                data = {}
                self.load_error = tx("Kayıt dosyası bozuk ({err}) ve sağlam yedek yok; boş başlatıldı. Bozuk kopya: {corrupt}", err=str(e)[:120], corrupt=corrupt)
            try:
                print(f"[!] {self.load_error}", file=sys.stderr)
            except Exception:
                pass
            return data

    def _protect_data_before_first_write(self) -> None:
        """Hiçbir şey yazılmadan ÖNCE: registry yedeği ve her projenin çalışma klasörü için anlık görüntü; küçülme uyarıları (data_warnings)."""
        from . import durability as DUR
        DUR.backup_registry(self.registry_path)
        paths: Dict[str, str] = {}
        try:
            if os.path.isfile(self.registry_path):
                with open(self.registry_path, "r", encoding="utf-8") as f:
                    for pid, p in ((json.load(f) or {}).get("projects") or {}).items():
                        if isinstance(p, dict) and p.get("path"):
                            paths[pid] = p["path"]
        except Exception:
            pass
        paths.setdefault("(varsayılan)", self.default_project_path)
        for pid, path in paths.items():
            if not path or not os.path.isdir(path):
                continue
            found = DUR.integrity_warnings(path)         # önce karşılaştır (mevcut hasarlı durum zirveyi ezmeden)
            DUR.snapshot_workspace(path, "startup")
            if found:
                self.data_warnings[pid] = found

    def _maybe_snapshot(self, reason: str = "auto", force: bool = False) -> None:
        """Etkin projenin çalışma klasörü anlık görüntüsü; `snapshot_interval_s` aralığıyla sınırlı (force ile atlanır)."""
        import time as _time
        now = _time.monotonic()
        if not force and now - self._last_snapshot_at < self.snapshot_interval_s:
            return
        proj = self.projects.get(self.active_project_id) or {}
        path = proj.get("path")
        if path and os.path.isdir(path):
            from . import durability as DUR
            self._last_snapshot_at = now
            DUR.snapshot_workspace(path, reason)

    def load_registry(self):
        """Kalıcı proje havuzunu diskten yükler."""
        try:
            self._protect_data_before_first_write()
        except Exception:
            pass
        try:
            if os.path.isfile(self.registry_path):
                data = self._read_registry_file()
                if True:
                    self.projects = data.get("projects", {})
                    for rd in data.get("runs", []) or []:
                        try:
                            run = PipelineRun.from_dict(rd)
                        except Exception:
                            continue
                        # Sunucu yeniden başladı: süren koşular terk edilmiş sayılır (istemci devam ettirebilir)
                        if not run.is_terminal:
                            run.finish("ABANDONED", reason="server-restart")
                        self.runs[run.run_id] = run
                    saved_active = data.get("active_project_id", "demo_project")
                    if saved_active in self.projects:
                        self.active_project_id = saved_active
                    elif self.projects:
                        self.active_project_id = list(self.projects.keys())[0]

            # Kayıt dosyası hiç yoksa (ilk kurulum) varsayılan projeyi ekle; kullanıcı tüm projeleri sildiyse boş kalır
            if not self.projects and not os.path.isfile(self.registry_path):
                default_proj = self.register_project(
                    self.default_project_path,
                    name=os.path.basename(self.default_project_path) or "demo_project"
                )
                self.active_project_id = default_proj["id"]

            # Aktif projenin verilerini yükle
            if self.active_project_id in self.projects:
                proj = self.projects[self.active_project_id]
                self._apply_workspace_overrides(proj, proj.get("path"))
                self._load_active_from_projects(proj)
            # Yeniden başlatmada süren koşular ABANDONED olduğundan hiçbir ajan "çalışıyor" görünmemeli
            for a in self.agents.values():
                if a.get("status") in ("WORKING", "PENDING_ACTION", "BUG_FIX"):
                    a["status"] = "IDLE"
        except Exception:
            pass

    def register_project(self, path: str, name: Optional[str] = None, lang: Optional[str] = None) -> Dict[str, Any]:
        """Yeni bir hedef proje klasörünü sisteme bağlar ve kaydeder."""
        normalized_path = os.path.abspath(path.strip().replace("\\", "/"))
        os.makedirs(normalized_path, exist_ok=True)
        ensure_fs_workspace(normalized_path)
        ws_data = load_project_from_workspace(normalized_path) or {}

        dir_name = os.path.basename(normalized_path) or "project"
        proj_name = name or dir_name
        proj_id = dir_name.lower().replace(" ", "-")

        if proj_id not in self.projects:
            self.projects[proj_id] = {
                "id": proj_id,
                "name": proj_name,
                "path": normalized_path,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "last_active": datetime.now(timezone.utc).isoformat(),
                "events": [],
                "tasks": copy.deepcopy(ws_data.get("tasks", {})),
                "agents": self._create_initial_agents(lang),
                "jira_issues": copy.deepcopy(ws_data.get("jira_issues") or create_default_jira_issues(lang)),
                "uploaded_specs": copy.deepcopy(ws_data.get("uploaded_specs", [])),
                "playwright_reports": [],
                "test_profiles": copy.deepcopy(create_default_test_profiles()),
                "stats": {
                    "total_events": 0,
                    "total_tokens": 0,
                    "active_tasks_count": 0,
                    "start_time": datetime.now(timezone.utc).isoformat()
                }
            }
        else:
            self.projects[proj_id]["path"] = normalized_path
            if name:
                self.projects[proj_id]["name"] = name
            self.projects[proj_id]["last_active"] = datetime.now(timezone.utc).isoformat()
            if "agents" not in self.projects[proj_id]:
                self.projects[proj_id]["agents"] = self._create_initial_agents(lang)
            if "jira_issues" not in self.projects[proj_id]:
                self.projects[proj_id]["jira_issues"] = copy.deepcopy(create_default_jira_issues(lang))
            if "uploaded_specs" not in self.projects[proj_id]:
                self.projects[proj_id]["uploaded_specs"] = []
            if "playwright_reports" not in self.projects[proj_id]:
                self.projects[proj_id]["playwright_reports"] = []
            if "test_profiles" not in self.projects[proj_id]:
                self.projects[proj_id]["test_profiles"] = copy.deepcopy(create_default_test_profiles())

        self.mark_dirty()
        return self.projects[proj_id]

    async def switch_project(self, project_id_or_path: str) -> Dict[str, Any]:
        """Aktif projeyi değiştirir ve tüm bağlı arayüzlere yeni proje görüntüsünü yayınlar."""
        target_id = None
        if project_id_or_path in self.projects:
            target_id = project_id_or_path
        else:
            normalized = os.path.abspath(project_id_or_path.strip().replace("\\", "/"))
            for pid, pdata in self.projects.items():
                if os.path.abspath(pdata["path"]) == normalized:
                    target_id = pid
                    break

        if not target_id:
            new_proj = self.register_project(project_id_or_path)
            target_id = new_proj["id"]

        # Mevcut aktif projenin verilerini kaydet
        self._sync_active_to_projects()

        # Yeni projeye geç: önce .fs-workspace üzerindeki güncel veriyi uygula, sonra canlı alanlara yükle
        self.active_project_id = target_id
        target_proj = self.projects[target_id]
        target_proj["last_active"] = datetime.now(timezone.utc).isoformat()
        self._apply_workspace_overrides(target_proj, target_proj.get("path"))
        self._load_active_from_projects(target_proj)

        # Proje geçişinde bekleyen onay ve koşu bağlamı yeni projeye ait değildir
        self.pending_step_approval = None

        self.mark_dirty()

        await self.broadcast(self._project_switched_payload(self.project_summary(target_id)))
        return target_proj

    async def clear_active_project(self) -> None:
        """Hiç proje kalmadığında: canlı durumu temizler ve istemcilere 'proje yok' yayınlar."""
        self.active_project_id = ""
        self.pending_step_approval = None
        self._load_active_from_projects({})
        self.mark_dirty()
        await self.broadcast(self._project_switched_payload(None))

    def _project_switched_payload(self, active_project: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """Tüm WebSocket istemcilerine proje değişim bildirimi (tek kaynaktan tam durum)."""
        return {
            "type": "PROJECT_SWITCHED",
            "active_project": active_project,
            "test_profiles": self.public_profiles(),
            "model_config": self.model_config,
            "agents": list(self.agents.values()),
            "tasks": list(self.tasks.values()),
            "jira_issues": list(self.jira_issues.values()),
            "uploaded_specs": self.uploaded_specs,
            "playwright_reports": self.playwright_reports,
            "events": list(self.events),
            "stats": self.stats,
            "pending_step_approval": self.pending_step_approval,
            "step_by_step_mode": self.step_by_step_mode,
            "active_run_id": self.active_run_id,
            "active_run": self.active_run_summary(),
            "runs": self.recent_runs(),
            "settings": self.settings,
            "connected_clients": list(self.connected_clients.values()),
            "raised_hands": self.raised_hands,
            "active_deliberation": self.deliberation_engine.get_latest_session()
        }

    def project_summary(self, pid: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """İstemciye giden proje özeti (tam kayıt değil: olaylar, ajanlar ve şifreler dahil edilmez)."""
        pid = pid or self.active_project_id
        if not pid and not self.projects:
            return None      # hiç proje yok (kullanıcı hepsini sildi)
        pdata = self.projects.get(pid, {"id": pid, "name": pid, "path": self.default_project_path})
        return {
            "id": pdata.get("id", pid),
            "name": pdata.get("name", pid),
            "path": pdata.get("path", ""),
            "is_active": pid == self.active_project_id,
            "created_at": pdata.get("created_at"),
            "last_active": pdata.get("last_active", ""),
            "events_count": len(self.events) if pid == self.active_project_id else len(pdata.get("events", [])),
            "tasks_count": len(self.tasks) if pid == self.active_project_id else len(pdata.get("tasks", {})),
            "jira_count": len(self.jira_issues) if pid == self.active_project_id else len(pdata.get("jira_issues", {})),
            "specs_count": len(self.uploaded_specs) if pid == self.active_project_id else len(pdata.get("uploaded_specs", [])),
        }

    def get_projects_summary(self) -> List[Dict[str, Any]]:
        """Kayıtlı tüm projelerin özet listesini döner."""
        summary = []
        for pid, pdata in self.projects.items():
            summary.append({
                "id": pid,
                "name": pdata.get("name", pid),
                "path": pdata.get("path", ""),
                "is_active": (pid == self.active_project_id),
                "events_count": len(pdata.get("events", [])) if pid != self.active_project_id else len(self.events),
                "tasks_count": len(pdata.get("tasks", {})) if pid != self.active_project_id else len(self.tasks),
                "jira_count": len(pdata.get("jira_issues", {})) if pid != self.active_project_id else len(self.jira_issues),
                "specs_count": len(pdata.get("uploaded_specs", [])) if pid != self.active_project_id else len(self.uploaded_specs),
                "last_active": pdata.get("last_active", "")
            })
        return summary

    def _prompt_role(self, agent_id: str) -> str:
        """İstem şablonunun seçildiği rol: özel ajanda devraldığı temel rol (`role_base`), çekirdek ajanda kendi rolü."""
        agent = self.agents.get(agent_id, {})
        if agent.get("role_base"):
            from . import agent_registry as AR
            return AR.base_role_of(agent)
        return agent.get("role", agent_id)

    def get_agent_prompt_details(self, agent_id: str, project_id: Optional[str] = None) -> Dict[str, Any]:
        """Ajanın .fs-workspace altındaki güncel Markdown içeriğini ve Git-tree versiyonlarını döner."""
        proj_id = project_id or self.active_project_id
        proj = self.projects.get(proj_id, {})
        proj_path = proj.get("path", os.path.abspath("."))
        role = self._prompt_role(agent_id)
        return get_agent_markdown_info(proj_path, agent_id, role)

    def save_agent_prompt_content(
        self,
        agent_id: str,
        content: str,
        commit_message: str,
        author: str = "User",
        project_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Ajanın Markdown dosyasını günceller ve Git-tree mantığıyla yeni versiyon kaydeder."""
        proj_id = project_id or self.active_project_id
        proj = self.projects.get(proj_id, {})
        proj_path = proj.get("path", os.path.abspath("."))
        role = self._prompt_role(agent_id)
        return save_agent_markdown(proj_path, agent_id, role, content, commit_message, author)

    def restore_agent_prompt_version(
        self,
        agent_id: str,
        version_id: str,
        author: str = "User",
        project_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Ajanın Markdown dosyasını geçmiş bir versiyona geri döndürür (Rollback)."""
        proj_id = project_id or self.active_project_id
        proj = self.projects.get(proj_id, {})
        proj_path = proj.get("path", os.path.abspath("."))
        role = self._prompt_role(agent_id)
        return restore_agent_version(proj_path, agent_id, role, version_id, author)

    def inherit_agent_prompt_standard(
        self,
        agent_id: str,
        author: str = "User",
        project_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Ajanı global standart şablonla yeniden kalıtır / eşitler."""
        proj_id = project_id or self.active_project_id
        proj = self.projects.get(proj_id, {})
        proj_path = proj.get("path", os.path.abspath("."))
        role = self._prompt_role(agent_id)
        return inherit_from_standard(proj_path, agent_id, role, author)

    def promote_agent_prompt_global(
        self,
        agent_id: str,
        project_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Projede olgunlaşan ajan kural ve promptunu şirketin global standardına terfi ettirir."""
        proj_id = project_id or self.active_project_id
        proj = self.projects.get(proj_id, {})
        proj_path = proj.get("path", os.path.abspath("."))
        role = self._prompt_role(agent_id)
        return promote_to_global(proj_path, agent_id, role)

    async def connect(self, ws: WebSocket):
        """Yeni bir WebSocket istemcisini bağlar ve mevcut tüm durumu gönderir."""
        await ws.accept()
        self.active_connections.add(ws)

        initial_payload = {
            "type": "INITIAL_STATE",
            "active_project": self.project_summary(),
            "projects": self.get_projects_summary(),
            "agents": list(self.agents.values()),
            "tasks": list(self.tasks.values()),
            "jira_issues": list(self.jira_issues.values()),
            "uploaded_specs": self.uploaded_specs,
            "playwright_reports": self.playwright_reports,
            "events": list(self.events),
            "stats": self.stats,
            "model_config": self.model_config,
            "pending_step_approval": self.pending_step_approval,
            "step_by_step_mode": self.step_by_step_mode,
            "active_run_id": self.active_run_id,
            "active_run": self.active_run_summary(),
            "runs": self.recent_runs(),
            "settings": self.settings,
            "connected_clients": list(self.connected_clients.values()),
            "raised_hands": self.raised_hands,
            "active_deliberation": self.deliberation_engine.get_latest_session()
        }
        try:
            await ws.send_text(json.dumps(initial_payload))
        except Exception:
            self.disconnect(ws)

    def disconnect(self, ws: WebSocket):
        self.active_connections.discard(ws)

    def get_model_config(self, project_id: Optional[str] = None) -> Dict[str, Any]:
        """Aktif veya belirtilen projenin model konfigürasyonunu döner."""
        pid = project_id or self.active_project_id
        if pid in self.projects and "model_config" in self.projects[pid]:
            return _normalize_model_config(self.projects[pid]["model_config"])
        return _normalize_model_config(self.model_config)

    async def update_model_config(self, new_config: Dict[str, Any], project_id: Optional[str] = None) -> Dict[str, Any]:
        """Model sağlayıcı ve parametrelerini günceller, kaydeder ve WebSocket ile duyurur."""
        pid = project_id or self.active_project_id
        provider = str(new_config.get("provider", DEFAULT_PROVIDER)).lower()
        model_id = str(new_config.get("model_id", DEFAULT_MODEL_ID))
        
        cfg = {
            "provider": provider,
            "model_id": model_id,
            "temperature": float(new_config.get("temperature", 0.2)),
            "max_tokens": int(new_config.get("max_tokens", 8192)),
            "updated_at": datetime.now(timezone.utc).isoformat()
        }
        if pid == self.active_project_id:
            self.model_config = cfg
        if pid in self.projects:
            self.projects[pid]["model_config"] = cfg
            self.save_registry()

        await self.broadcast({
            "type": "MODEL_CONFIG_UPDATED",
            "project_id": pid,
            "model_config": cfg
        })
        return cfg

    async def broadcast(self, data: Dict[str, Any]):
        """Tüm bağlı istemcilere olay paketini yayınlar; ölü bağlantılar yayından sonra temizlenir."""
        if not self.active_connections:
            return
        payload = json.dumps(data, ensure_ascii=False, default=str)
        connections = list(self.active_connections)
        results = await asyncio.gather(
            *(ws.send_text(payload) for ws in connections),
            return_exceptions=True
        )
        for ws, result in zip(connections, results):
            if isinstance(result, BaseException):
                self.active_connections.discard(ws)

    async def record_event(
        self,
        trace_id: str,
        from_agent: str,
        to_agent: str,
        action: str,
        status: str,
        payload: Any,
        current_file: Optional[str] = None,
        tokens_used: int = 0,
        thinking: Optional[str] = None,
        what_doing: Optional[str] = None,
        what_next: Optional[str] = None,
        friendly_dialogue: Optional[str] = None,
        from_project: Optional[str] = None,
        to_project: Optional[str] = None
    ) -> Dict[str, Any]:
        """Ajan etkileşim olayını kaydeder ve WebSocket ile yayınlar (projeler arası mesajlarda from/to_project dolar)."""
        timestamp = datetime.now(timezone.utc).isoformat()
        from_agent = from_agent.upper()
        to_agent = to_agent.upper()

        # Samimi, insansı, teknik olmayan diyalog ve düşünce akışı üretimi
        dialogues = {
            ("PM", "ARCHITECT"): N_("Selam Mimar! Müşterimizin şartnamesini ve toplantı notlarını analiz ettim. Harika ve hızlı bir sistem istiyorlar. Hadi sağlam bir mimari kuralım!"),
            ("ARCHITECT", "DEVELOPER"): N_("Selam Takım! API kontratlarını, veri modellerini ve güvenliği planladım. Kodlamaya başlayabilirsiniz, kolay gelsin!"),
            ("ARCHITECT", "BACKEND_DEV"): N_("Selam Backend! REST API kontratı ve Pydantic veri modelleri hazır. Endpoint'leri kodlamaya başlayabilirsin!"),
            ("ARCHITECT", "FRONTEND_DEV"): N_("Selam Frontend! Arayüz bileşen şemasını ve veri kontratını çıkardım. Sayfaları tasarlamaya başlayabilirsin!"),
            ("BACKEND_DEV", "FRONTEND_DEV"): N_("Selam Frontend! Giriş ve veri yönetim API'larını tamamladım, port 8080'de yayında. Arayüze bağlayabilirsin!"),
            ("FRONTEND_DEV", "BACKEND_DEV"): N_("Harika, API bağlantılarını ve veri akışını teyit ettim. Karşılıklı el sıkıştık!"),
            ("DEVELOPER", "QA"): N_("Selam QA Ekibi! İstenen özellikleri ve birim testlerini tamamladım. İncelemeniz ve test etmeniz için hazır!"),
            ("BACKEND_DEV", "QA"): N_("Backend servislerini ve middleware'i kodladım. Birim testler için hazır, inceleyebilirsin!"),
            ("FRONTEND_DEV", "E2E_TESTER"): N_("Kullanıcı arayüzünü ve formları bitirdim. Sayfa çok akıcı ve şık oldu. Canlı tarayıcıda Playwright ile test edebilir misin?"),
            ("QA", "DEVELOPER"): N_("Birim testlerini koşturdum, birkaç küçük hata yakaladım. Hemen düzeltip tekrar iletebilir misin?"),
            ("QA", "BACKEND_DEV"): N_("Test koşusu sırasında beklenmeyen bir hata oluştu, logları inceleyip düzeltebilir misin?"),
            ("QA", "DEVOPS"): N_("Birim testleri ve güvenlik kontrolleri 0 hatayla geçti! Dağıtım ve canlıya çıkış için onay veriyorum."),
            ("QA", "E2E_TESTER"): N_("Birim ve API testleri başarıyla onaylandı. Canlı tarayıcı testlerine geçebilirsin!"),
            ("E2E_TESTER", "ARCHITECT"): N_("Canlı Chromium tarayıcısında uçtan uca senaryoları çalıştırdım, ekran görüntülerini kaydettim. Her şey kusursuz!"),
            ("DEVOPS", "PM"): N_("Konteyner ve deployment yapılandırması tamamlandı! Sistemimiz canlıda aktif, müşteriye gururla sunabiliriz."),
        }

        _canned = dialogues.get((from_agent, to_agent))
        dialogue = friendly_dialogue or (tx(_canned) if _canned else tx("{from_agent}: '{action}' adımını tamamladım, {to_agent} ile el sıkışıyoruz.", from_agent=from_agent, action=action, to_agent=to_agent))

        # Sabit "düşünce" cümleleri ÜRETİLMEZ: panoda yalnızca modelin kendi notu (report_thinking / zarftaki thinking) görünür; yoksa alan boş kalır.

        self._event_seq += 1
        self.stats["event_seq"] = self._event_seq
        event = {
            "id": f"evt-{self._event_seq:06d}",
            "type": "AGENT_INTERACTION",
            "trace_id": trace_id,
            "from_agent": from_agent,
            "to_agent": to_agent,
            "action": action,
            "status": status.upper(),
            "payload": payload,
            "current_file": current_file,
            "tokens_used": tokens_used,
            "timestamp": timestamp,
            "friendly_dialogue": dialogue,
            "thinking": thinking,
            "what_doing": what_doing,
            "what_next": what_next
        }
        if from_project or to_project:
            event["from_project"] = from_project or self.active_project_id
            event["to_project"] = to_project or self.active_project_id

        self.events.append(event)
        self.stats["total_events"] += 1
        self.stats["total_tokens"] += tokens_used

        # Kalıcı olay deposu (.fs-workspace/events.jsonl) — zaman çizelgesi 500 olay sınırına takılmasın
        proj_path = self.projects.get(self.active_project_id, {}).get("path")
        if proj_path and os.path.isdir(proj_path):
            append_event(proj_path, event)

        # Ajanların anlık durumlarını güncelle
        if from_agent in self.agents:
            agent = self.agents[from_agent]
            agent["last_action"] = action
            # Yalnızca açıkça başarısız olan olay ajanı ERROR yapar; 'IN_PROGRESS' (ör. soru açıldı) hata değildir
            agent["status"] = "ERROR" if str(status).upper() in ("FAILED", "ERROR") else "WORKING"
            agent["total_tokens"] += tokens_used
            agent["last_seen"] = timestamp
            agent["current_dialogue"] = dialogue
            agent["current_thinking"] = thinking
            agent["current_what_doing"] = what_doing
            if current_file:
                agent["active_file"] = current_file

        if to_agent in self.agents and to_agent != from_agent:
            target_agent = self.agents[to_agent]
            target_agent["status"] = "BUG_FIX" if action == "REPORT_BUG" else "PENDING_ACTION"
            target_agent["last_seen"] = timestamp

        await self.broadcast(event)
        self.save_registry()
        return event

    async def emit_event(self, *args, **kwargs):
        """record_event için kolaylaştırıcı eşanlamlı metod."""
        return await self.record_event(*args, **kwargs)

    async def update_task(
        self,
        task_id: str,
        new_state: str,
        title: Optional[str] = None,
        assignee: Optional[str] = None,
        priority: str = "P1",
        details: Optional[str] = None
    ) -> Dict[str, Any]:
        """Kanban tahtasındaki görevin durumunu günceller."""
        timestamp = datetime.now(timezone.utc).isoformat()
        existing = self.tasks.get(task_id, {})

        task = {
            "id": task_id,
            "title": title or existing.get("title", f"Task {task_id}"),
            "state": new_state.upper(),
            "assignee": (assignee.upper() if assignee else existing.get("assignee", "PM")),
            "priority": priority or existing.get("priority", "P1"),
            "details": details or existing.get("details", ""),
            "updated_at": timestamp
        }
        self.tasks[task_id] = task
        self.stats["active_tasks_count"] = len(self.tasks)

        event = {
            "type": "TASK_UPDATED",
            "task": task
        }
        await self.broadcast(event)
        self.save_registry()
        return task

    # -------------------------------------------------------------------------
    # Jira Issue Yönetimi
    # -------------------------------------------------------------------------
    async def update_jira_issue(self, issue_id: str, updates: Dict[str, Any]) -> Dict[str, Any]:
        """Jira görevini günceller ve panoya anında yayınlar."""
        timestamp = datetime.now(timezone.utc).isoformat()
        if issue_id not in self.jira_issues:
            # Yeni oluştur
            order = updates.get("order", len(self.jira_issues) + 1)
            self.jira_issues[issue_id] = {
                "id": issue_id,
                "key": f"DEV-{order}",
                "order": order,
                "title": updates.get("title", f"Issue {issue_id}"),
                "description": updates.get("description", ""),
                "issue_type": updates.get("issue_type", "TASK"),
                "status": updates.get("status", "BACKLOG"),
                "priority": updates.get("priority", "P1"),
                "assignee": updates.get("assignee", "BACKEND_DEV"),
                "acceptance_criteria": updates.get("acceptance_criteria", []),
                "attachments": updates.get("attachments", []),
                "audit_trail": [],
                "created_at": timestamp,
                "updated_at": timestamp
            }
            # Tam yaşam döngüsü alanları (backlog görevleri): tür, anahtar, ebeveyn, bağımlılık, dosya ipuçları
            for extra in ("kind", "task_key", "parent_id", "depends_on", "files_hint", "run_id", "work_type", "sprint", "ac_refs",
                          "origin", "carry_over", "related_to", "supersedes", "needs_rescope", "story_ref", "closed_in_sprint", "structured",
                          "fix_limit_sprint", "rescoped_at", "local_id", "planned_sprint", "expedite", "redesign", "design_round", "design_brief", "design_screen", "redo_of",
                          # G5 Jira+ alanları
                          "labels", "components", "estimate", "due", "links", "comments", "watchers", "history", "board_rank"):
                if updates.get(extra) is not None:
                    self.jira_issues[issue_id][extra] = updates[extra]
        else:
            current = self.jira_issues[issue_id]
            from .sprint import is_frozen
            changes = [k for k in ("title", "description", "acceptance_criteria", "priority", "assignee", "work_type")
                       if k in updates and updates[k] != current.get(k)]
            if changes and is_frozen(self, current):
                # Kapatılmış sprintin maddesi değişmez (karar 19c): değişiklik yeni madde olarak eklenmelidir
                updates = {k: v for k, v in updates.items() if k not in changes}
                updates["audit_action"] = "CHANGE_REJECTED_CLOSED_SPRINT"
                updates["audit_notes"] = tx("Kapatılmış sprintin maddesi değiştirilemez; değişiklik yeni madde olarak ve 'related_to' ile eklenir: ") + ", ".join(changes)
            elif changes and "audit_action" not in updates:
                # Maddenin sonradan değişmesi izlenir (karar 19d)
                updates = {**updates, "audit_action": "FIELD_CHANGED",
                           "audit_notes": "; ".join(f"{k}: {str(current.get(k))[:60]!r} → {str(updates[k])[:60]!r}" for k in changes)}
            current.update(updates)
            current["updated_at"] = timestamp

        issue = self.jira_issues[issue_id]
        if "audit_trail" not in issue:
            issue["audit_trail"] = []

        # Audit denetim kaydı oluştur
        agent_id = updates.get("agent_id") or updates.get("assignee") or issue.get("assignee") or "SYSTEM"
        action = updates.get("audit_action") or f"STATUS_{issue.get('status', 'UPDATED')}"
        notes = updates.get("audit_notes") or updates.get("notes") or updates.get("details") or ""
        
        audit_entry = {
            "id": f"aud-{uuid.uuid4().hex[:8]}",
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
            "agent_id": agent_id,
            "action": action,
            "status": issue.get("status"),
            "notes": notes,
            "files_affected": updates.get("files_affected") or []
        }
        issue["audit_trail"].append(audit_entry)

        await self.broadcast({
            "type": "JIRA_UPDATED",
            "issue": issue,
            "all_issues": list(self.jira_issues.values())
        })
        self.save_registry()
        return issue

    async def record_task_audit(
        self,
        issue_id: str,
        agent_id: str,
        action: str,
        notes: str = "",
        files_affected: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """Göreve bağımsız bir audit notu veya işlem izi ekler."""
        if issue_id in self.jira_issues:
            issue = self.jira_issues[issue_id]
            if "audit_trail" not in issue:
                issue["audit_trail"] = []
            audit_entry = {
                "id": f"aud-{uuid.uuid4().hex[:8]}",
                "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
                "agent_id": agent_id,
                "action": action,
                "status": issue.get("status"),
                "notes": notes,
                "files_affected": files_affected or []
            }
            issue["audit_trail"].append(audit_entry)
            issue["updated_at"] = datetime.now(timezone.utc).isoformat()
            await self.broadcast({
                "type": "JIRA_UPDATED",
                "issue": issue,
                "all_issues": list(self.jira_issues.values())
            })
            self.save_registry()
            return audit_entry
        return {}

    def find_recent_duplicate(self, data: Dict[str, Any], window_s: float = 120.0) -> Optional[Dict[str, Any]]:
        """Çift gönderim koruması: aynı başlık + tür + sorumlu ile `window_s` saniye içinde açılmış, bitmemiş bir iş varsa o döner (çift tıklama ikinci iş açmaz)."""
        title = " ".join(str(data.get("title") or "").lower().split())
        if not title:
            return None
        now = datetime.now(timezone.utc)
        for i in self.jira_issues.values():
            if i.get("deleted") or i.get("status") == "DONE" or " ".join(str(i.get("title") or "").lower().split()) != title:
                continue
            if i.get("issue_type") != (data.get("issue_type") or "TASK") or i.get("assignee") != (data.get("assignee") or "BACKEND_DEV"):
                continue
            try:
                age = (now - datetime.fromisoformat(str(i.get("created_at")))).total_seconds()
            except (TypeError, ValueError):
                continue
            if 0 <= age <= window_s:
                return i
        return None

    async def add_jira_issue(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Yeni bir Jira görevi ekler."""
        order = len(self.jira_issues) + 1
        issue_id = data.get("id") or f"JIRA-{order}"
        data = dict(data)
        if str(data.get("issue_type") or "TASK").upper() in ("TASK", "BUG") and not data.get("kind"):
            # Panodan/elle eklenen iş sprint planlayıcısının görebileceği bir görevdir (kind yoksa aday sayılmaz ve hiç planlanmazdı)
            data["kind"] = "task"
            data.setdefault("origin", "MANAGER")
            data.setdefault("work_type", "BUG" if str(data.get("issue_type")).upper() == "BUG" else "FEATURE")
        return await self.update_jira_issue(issue_id, {**data, "order": order})

    def get_jira_issues(self) -> List[Dict[str, Any]]:
        return sorted(list(self.jira_issues.values()), key=lambda x: x.get("order", 999))

    # -------------------------------------------------------------------------
    # Müşteri Şartname ve Dosya Kasası (Vault)
    # -------------------------------------------------------------------------
    async def add_uploaded_spec(self, spec_data: Dict[str, Any]) -> Dict[str, Any]:
        """Müşteri görüşme notu ve yüklenen dosyaları kaydeder."""
        spec_id = f"SPEC-{len(self.uploaded_specs) + 1:03d}"
        spec_record = {
            "id": spec_id,
            "title": spec_data.get("title", tx("Müşteri Görüşme Notu")),
            "client_name": spec_data.get("client_name", tx("Müşteri")),
            "meeting_notes": spec_data.get("meeting_notes", ""),
            "files": spec_data.get("files", []),
            "created_at": datetime.now(timezone.utc).isoformat()
        }
        self.uploaded_specs.append(spec_record)
        await self.broadcast({
            "type": "SPEC_ADDED",
            "spec": spec_record,
            "all_specs": self.uploaded_specs
        })
        self.save_registry()
        return spec_record

    def _remove_upload_file(self, saved_path: Optional[str]) -> bool:
        """Yüklenen dosyayı diskten siler; yalnızca uploads/ kökü altındaysa (kök dışı yollar dokunulmaz)."""
        if not saved_path:
            return False
        try:
            from pathlib import Path
            # Silinebilir yerler: her projenin kendi yükleme klasörü ve eski (F1 öncesi) FS-SC kökü `uploads/`
            roots = [Path(os.environ.get("AGY_DATA_DIR") or REPO_ROOT).resolve() / "uploads"]
            for info in self.projects.values():
                if isinstance(info, dict) and info.get("path"):
                    roots.append(Path(info["path"]).resolve() / ".fs-workspace" / "specs" / "uploads")
            target = Path(saved_path).resolve()
            for root in roots:
                try:
                    target.relative_to(root)
                except ValueError:
                    continue
                if target.is_file():
                    target.unlink()
                    return True
                return False
        except Exception:
            return False
        return False

    async def delete_uploaded_spec(self, spec_id: str) -> bool:
        """Kayıtlı şartnameyi kasadan, listeden ve dosyalarını diskten siler."""
        initial_len = len(self.uploaded_specs)
        removed = [s for s in self.uploaded_specs if s.get("id") == spec_id]
        for spec in removed:
            for f in spec.get("files", []) or []:
                self._remove_upload_file(f.get("saved_path") if isinstance(f, dict) else None)
        self.uploaded_specs = [s for s in self.uploaded_specs if s.get("id") != spec_id]
        if len(self.uploaded_specs) < initial_len:
            self.save_registry()
            await self.broadcast({
                "type": "SPEC_DELETED",
                "spec_id": spec_id,
                "all_specs": self.uploaded_specs
            })
            return True
        return False

    async def delete_spec_file(self, spec_id: str, filename: str) -> bool:
        """Şartnameye eklenmiş belirli bir dosyayı siler/çıkarır."""
        for spec in self.uploaded_specs:
            if spec.get("id") == spec_id:
                files = spec.get("files", [])
                initial_len = len(files)
                for f in files:
                    if isinstance(f, dict) and f.get("filename") == filename:
                        self._remove_upload_file(f.get("saved_path"))
                spec["files"] = [f for f in files if (f.get("filename") if isinstance(f, dict) else f) != filename]
                if len(spec["files"]) < initial_len:
                    self.save_registry()
                    await self.broadcast({
                        "type": "SPEC_UPDATED",
                        "spec": spec,
                        "all_specs": self.uploaded_specs
                    })
                    return True
        return False

    async def update_uploaded_spec(self, spec_id: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Şartname başlığını, müşteri adını veya görüşme notlarını günceller."""
        for spec in self.uploaded_specs:
            if spec.get("id") == spec_id:
                if "title" in updates:
                    spec["title"] = updates["title"]
                if "client_name" in updates:
                    spec["client_name"] = updates["client_name"]
                if "meeting_notes" in updates:
                    spec["meeting_notes"] = updates["meeting_notes"]
                if "files" in updates:
                    spec["files"] = updates["files"]
                self.save_registry()
                await self.broadcast({
                    "type": "SPEC_UPDATED",
                    "spec": spec,
                    "all_specs": self.uploaded_specs
                })
                return spec
        return None

    async def generate_jira_tasks_from_spec(self, spec_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Müşteri görüşme notlarını ve şartname dosyalarını analiz eder;
        Jira Agile tahtasındaki görevleri (1-8 maddelerini) müşterinin
        spesifik talebine göre dinamik olarak baştan üretir ve günceller.
        """
        title = spec_data.get("title", tx("Müşteri Keşif ve Gereksinim Projesi"))
        client = spec_data.get("client_name", tx("Kurumsal Müşteri"))
        notes = spec_data.get("meeting_notes", "").strip()
        files = [f.get("filename") for f in spec_data.get("files", []) if isinstance(f, dict)]

        # Eğer notlar kısaysa veya yüklenmiş dosya varsa dosya içeriğini diskten oku
        for f in spec_data.get("files", []):
            if isinstance(f, dict) and f.get("saved_path"):
                spath = f["saved_path"]
                if os.path.isfile(spath) and is_readable(spath):
                    try:
                        file_txt = read_text(spath).strip()
                        if file_txt and (len(notes) < 50 or file_txt not in notes):
                            notes += f"\n\n---\n{file_txt}"
                    except Exception:
                        pass

        # Başlık jenerik ise ilk markdown başlığını çek
        if any(title in I18N.variants(g) for g in ("Ön plan toplantısı", "Müşteri Keşif ve Gereksinim Projesi", "Müşteri Keşif ve Gereksinim Notu", "Müşteri")):
            for line in notes.splitlines():
                ls = line.strip()
                if ls.startswith("#"):
                    parsed_t = ls.lstrip("#").strip()
                    if parsed_t:
                        title = parsed_t
                        break

        # Müşteri notlarındaki satırları, modülleri ve kabul kriterlerini ayrıştır
        bullet_points = [
            line.strip("- *•0123456789.) ").strip()
            for line in notes.split("\n")
            if line.strip() and len(line.strip()) > 3 and not line.strip().startswith("#")
        ]

        now = datetime.now(timezone.utc).isoformat()
        
        custom_issues = {
            "JIRA-1": {
                "id": "JIRA-1",
                "key": "DEV-1",
                "order": 1,
                "title": tx("Müşteri Keşif & PRD: {title}", title=title),
                "description": tx("Müşteri: {client}\nTalep: {title}\nÖzet: {summary}...\nBelgeler: {docs}", client=client, title=title, summary=notes[:300],
                                  docs=(', '.join(files) if files else tx("Metin notları"))),
                "issue_type": "EPIC",
                "status": "BACKLOG",
                "priority": "P0",
                "assignee": "PM",
                "acceptance_criteria": [
                    tx("Müşteri ({client}) şartname belgeleri ve isterleri analiz edildi", client=client),
                    tx("docs/PRD.md iş kuralları ve kullanıcı hikayeleri donduruldu"),
                    *(bullet_points[:3] if bullet_points else [tx("Temel fonksiyonel isterler netleştirildi")])
                ],
                "attachments": files,
                "created_at": now,
                "updated_at": now
            },
            "JIRA-2": {
                "id": "JIRA-2",
                "key": "DEV-2",
                "order": 2,
                "title": tx("Sistem Mimarisi & API Kontratı ({title})", title=title),
                "description": tx("Team Lead / Architect: {client} için mikroservis şemaları, OpenAPI 3.0 sözleşmesi ve veri modelleri.", client=client),
                "issue_type": "STORY",
                "status": "BACKLOG",
                "priority": "P0",
                "assignee": "ARCHITECT",
                "acceptance_criteria": [
                    tx("OpenAPI JSON spesifikasyonu donduruldu"),
                    tx("{title} için Pydantic ve veri modelleri çıkarıldı", title=title),
                    tx("Hata ve yetkilendirme sözleşmesi hazırlandı")
                ],
                "attachments": [],
                "created_at": now,
                "updated_at": now
            },
            "JIRA-3": {
                "id": "JIRA-3",
                "key": "DEV-3",
                "order": 3,
                "title": tx("Senior Backend: REST API & Servisleri ({title})", title=title),
                "description": tx("Senior Backend Dev: {title} kapsamında JWT auth, CRUD operasyonları ve iş mantığını kodla.", title=title),
                "issue_type": "TASK",
                "status": "BACKLOG",
                "priority": "P0",
                "assignee": "BACKEND_DEV",
                "acceptance_criteria": [
                    tx("FastAPI servisleri ve middleware kodlandı"),
                    tx("Veritabanı ve session mantığı entegre edildi"),
                    tx("Girdi doğrulama ve hata yakalayıcılar eklendi")
                ],
                "attachments": [],
                "created_at": now,
                "updated_at": now
            },
            "JIRA-4": {
                "id": "JIRA-4",
                "key": "DEV-4",
                "order": 4,
                "title": tx("Senior Frontend: Responsive UI & Formlar ({title})", title=title),
                "description": tx("Senior Frontend Dev: {client} talebine uygun React / Tailwind kullanıcı deneyimi ve API istemcisi.", client=client),
                "issue_type": "TASK",
                "status": "BACKLOG",
                "priority": "P0",
                "assignee": "FRONTEND_DEV",
                "acceptance_criteria": [
                    tx("{title} için modern responsive sayfalar kodlandı", title=title),
                    tx("Backend API istemcisi senkronize edildi"),
                    tx("Giriş ve etkileşim formları bağlandı")
                ],
                "attachments": [],
                "created_at": now,
                "updated_at": now
            },
            "JIRA-5": {
                "id": "JIRA-5",
                "key": "DEV-5",
                "order": 5,
                "title": tx("Peer Review & Backend-Frontend API Handshake"),
                "description": tx("Geliştiriciler arası doğrudan A2A mutabakatı: {title} veri akışı, CORS ve Bearer token header senkronizasyonu.", title=title),
                "issue_type": "TASK",
                "status": "BACKLOG",
                "priority": "P1",
                "assignee": "BACKEND_DEV",
                "acceptance_criteria": [
                    tx("Geliştiriciler veri modellerini karşılıklı doğruladı"),
                    tx("CORS ve token header geçişleri onaylandı"),
                    tx("Uçtan uca mock testleriyle uyum sağlandı")
                ],
                "attachments": [],
                "created_at": now,
                "updated_at": now
            },
            "JIRA-6": {
                "id": "JIRA-6",
                "key": "DEV-6",
                "order": 6,
                "title": tx("Lead QA: Birim ve Fonksiyonel Doğrulama ({title})", title=title),
                "description": tx("Lead QA: {title} test senaryolarını çalıştır, edge case'leri doğrula ve QA raporunu yayınla.", title=title),
                "issue_type": "TASK",
                "status": "BACKLOG",
                "priority": "P0",
                "assignee": "QA",
                "acceptance_criteria": [
                    tx("Birim testler 4/4 başarıyla geçti"),
                    tx("{client} gereksinimlerine göre testler yapıldı", client=client),
                    tx("docs/QA_REPORT.md onaylandı")
                ],
                "attachments": [],
                "created_at": now,
                "updated_at": now
            },
            "JIRA-7": {
                "id": "JIRA-7",
                "key": "DEV-7",
                "order": 7,
                "title": tx("Playwright E2E: Canlı Tarayıcı Doğrulama ({title})", title=title),
                "description": tx("Playwright E2E Tester: Canlı Chromium tarayıcısında {title} arayüzünü test et ve ekran görüntüleri yakala.", title=title),
                "issue_type": "TASK",
                "status": "BACKLOG",
                "priority": "P0",
                "assignee": "E2E_TESTER",
                "acceptance_criteria": [
                    tx("Chromium tarayıcısında butonlar ve formlar denendi"),
                    tx("Kanıt ekran görüntüleri .fs-workspace/e2e/screenshots altında toplandı"),
                    tx("Sayfa yüklenme ve DOM doğrulaması sağlandı")
                ],
                "attachments": [],
                "created_at": now,
                "updated_at": now
            },
            "JIRA-8": {
                "id": "JIRA-8",
                "key": "DEV-8",
                "order": 8,
                "title": tx("DevOps Dağıtım & Docker Yayını ({title})", title=title),
                "description": tx("DevOps Mühendisi: {title} uygulamasını Dockerfile ve docker-compose ile üretime hazırla.", title=title),
                "issue_type": "TASK",
                "status": "BACKLOG",
                "priority": "P0",
                "assignee": "DEVOPS",
                "acceptance_criteria": [
                    tx("Dockerfile ve docker-compose.yml hazırlandı"),
                    tx("README.md proje dokümanı oluşturuldu"),
                    tx("Konteyner ortamı doğrulandı")
                ],
                "attachments": [],
                "audit_trail": [],
                "created_at": now,
                "updated_at": now
            },
            "JIRA-9": {
                "id": "JIRA-9",
                "key": "DEV-9",
                "order": 9,
                "title": tx("Product Owner (PO) UAT & Kabul Onayı ({title})", title=title),
                "description": tx("Product Owner (PO): {title} teslimatını müşteri kabul kriterlerine göre denetle ve UAT onayı ver.", title=title),
                "issue_type": "STORY",
                "status": "BACKLOG",
                "priority": "P0",
                "assignee": "PO",
                "acceptance_criteria": [
                    tx("Müşteri toplantı notları ve şartname maddeleri birebir doğrulandı"),
                    tx("Kullanıcı kabul testi (UAT) başarıyla geçti"),
                    tx("Eksik özellikler varsa yeni geliştirme talebine dönüştürüldü")
                ],
                "attachments": [],
                "audit_trail": [],
                "created_at": now,
                "updated_at": now
            },
            "JIRA-10": {
                "id": "JIRA-10",
                "key": "DEV-10",
                "order": 10,
                "title": tx("Documentor & Reporter: Kullanım Kılavuzu & Yönetici Raporu ({title})", title=title),
                "description": tx("Documentor Ajanı son kullanıcı kullanım kılavuzunu üretir; Reporter Ajanı ise sprint özetini ve metriklerini yönetici raporuna döker."),
                "issue_type": "TASK",
                "status": "BACKLOG",
                "priority": "P0",
                "assignee": "DOCUMENTOR",
                "acceptance_criteria": [
                    tx("docs/manuals/user_guide.md son kullanıcı kılavuzu tamamlandı"),
                    tx("README.md ve mimari API referansları güncellendi"),
                    tx("docs/reports/status_report.md yönetici durum özeti hazırlandı")
                ],
                "attachments": [],
                "audit_trail": [],
                "created_at": now,
                "updated_at": now
            }
        }

        # Tüm oluşturulan özel kartlara audit_trail alanını garanti et
        for c_iss in custom_issues.values():
            if "audit_trail" not in c_iss:
                c_iss["audit_trail"] = []

        # Karar 17/19: yükleme mevcut Jira kayıtlarını ve geçmişi SİLMEZ. Henüz başlamamış (BACKLOG) faz maddelerinin tanımı yerinde
        # güncellenir (değişiklikler denetim izine yazılır); başlamış/bitmiş maddelere dokunulmaz; olmayanlar eklenir.
        from .sprint import is_frozen
        for key, fresh in custom_issues.items():
            current = self.jira_issues.get(key)
            if current is None:
                self.jira_issues[key] = fresh
            elif current.get("status") in (None, "BACKLOG") and not is_frozen(self, current):
                await self.update_jira_issue(key, {f: fresh[f] for f in ("title", "description", "acceptance_criteria", "attachments") if f in fresh}
                                                 | {"audit_action": "SPEC_UPDATED", "audit_notes": tx("Yeni yükleme: {title}", title=title)})
            else:
                await self.record_task_audit(key, "PM", "SPEC_UPDATE_SKIPPED",
                                             notes=tx("Madde '{status}' durumunda; yeni yükleme tanımını değiştirmedi ({title}).", status=current.get('status'), title=title))
        self.save_registry()

        # WebSocket üzerinden tüm istemcilere bildir
        issues_list = list(self.jira_issues.values())
        await self.broadcast({
            "type": "JIRA_UPDATED",
            "issue": issues_list[0] if issues_list else None,
            "jira_issues": issues_list,
            "all_issues": issues_list,
            "tasks": issues_list,
            "source": "SPEC_ANALYSIS",
            "spec_title": title
        })

        return list(self.jira_issues.values())


    # -------------------------------------------------------------------------
    # Sprint kipi: yüklemeyle başlayan değerlendirme kuyruğu (A19)
    # -------------------------------------------------------------------------
    async def queue_intake(self, spec_id: str) -> Dict[str, Any]:
        """Yükleme sonrası değerlendirmeyi kuyruğa alır; bekleyen bir değerlendirme varsa yeni yükleme ona eklenir (ikinci açılmaz)."""
        from .sprint import ensure_state, now
        st = ensure_state(self)
        pending = st.get("pending_intake") or {"spec_ids": [], "queued_at": now()}
        merged = spec_id in pending["spec_ids"]
        if not merged:
            pending["spec_ids"].append(spec_id)
        st["pending_intake"] = pending
        self.mark_dirty()
        await self.broadcast({"type": "SPEC_UPLOADED", "spec_id": spec_id, "pending_intake": pending, "merged_into_pending": len(pending["spec_ids"]) > 1})
        return pending

    # -------------------------------------------------------------------------
    # Playwright E2E Raporları
    # -------------------------------------------------------------------------
    async def add_playwright_report(self, report_data: Dict[str, Any]) -> Dict[str, Any]:
        """Playwright tarayıcı test sonucunu kaydeder."""
        report_id = f"E2E-{len(self.playwright_reports) + 1:03d}"
        report_record = {
            "id": report_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            **report_data
        }
        self.playwright_reports.insert(0, report_record)  # En yeni en başta
        if len(self.playwright_reports) > 50:
            self.playwright_reports.pop()

        await self.broadcast({
            "type": "PLAYWRIGHT_REPORT_ADDED",
            "report": report_record,
            "all_reports": self.playwright_reports
        })
        self.save_registry()
        return report_record

    # -------------------------------------------------------------------------
    # Test Kullanıcı Şablonları & Profilleri
    # -------------------------------------------------------------------------
    def get_test_profiles(self) -> List[Dict[str, Any]]:
        """Aktif projenin hazır ve özel test kullanıcı profillerini döner (şifreler dahil — yalnızca sunucu içi)."""
        return self.test_profiles

    def public_profiles(self) -> List[Dict[str, Any]]:
        """İstemciye giden profil listesi: düz metin şifre yerine has_password bayrağı."""
        out = []
        for p in self.test_profiles:
            q = {k: v for k, v in p.items() if k != "password"}
            q["has_password"] = bool(p.get("password"))
            out.append(q)
        return out

    def resolve_credentials(self, credentials: Optional[Dict[str, Any]], profile_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """İstemciden gelen kimlik bilgisini profil kaydıyla tamamlar (şifre istemciye hiç gitmez)."""
        cred = dict(credentials or {})
        pid = profile_id or cred.get("profile_id")
        if pid:
            profile = next((p for p in self.test_profiles if p.get("id") == pid), None)
            if profile:
                cred.setdefault("username", profile.get("username"))
                cred.setdefault("role", profile.get("role"))
                if not cred.get("password"):
                    cred["password"] = profile.get("password", "")
                cred.setdefault("target_url", profile.get("target_url"))
        cred.pop("profile_id", None)
        return cred or None

    async def add_or_update_test_profile(self, profile_data: Dict[str, Any]) -> Dict[str, Any]:
        """Yeni test kullanıcısı/şablonu ekler veya mevcut olanı günceller."""
        p_id = profile_data.get("id") or f"profile-{int(datetime.now(timezone.utc).timestamp())}"
        now = datetime.now(timezone.utc).isoformat()

        record = {
            "id": p_id,
            "name": profile_data.get("name", tx("Özel Test Kullanıcısı")),
            "target_url": profile_data.get("target_url", "http://127.0.0.1:8099"),
            "username": profile_data.get("username", "testuser@company.local"),
            "password": profile_data.get("password", "TestPass123!"),
            "role": profile_data.get("role", "USER"),
            "description": profile_data.get("description", tx("Kullanıcı tanımlı test profili")),
            "is_preset": profile_data.get("is_preset", False),
            "updated_at": now
        }

        idx = next((i for i, p in enumerate(self.test_profiles) if p["id"] == p_id), -1)
        if idx >= 0:
            self.test_profiles[idx] = record
        else:
            self.test_profiles.append(record)

        await self.broadcast({
            "type": "TEST_PROFILES_UPDATED",
            "profiles": self.public_profiles(),
            "profile": {k: v for k, v in record.items() if k != "password"}
        })
        self.save_registry()
        return record

    async def delete_test_profile(self, profile_id: str) -> bool:
        """Test profilini kaldırır."""
        orig_len = len(self.test_profiles)
        self.test_profiles = [p for p in self.test_profiles if p["id"] != profile_id]
        if len(self.test_profiles) != orig_len:
            await self.broadcast({
                "type": "TEST_PROFILES_UPDATED",
                "profiles": self.public_profiles()
            })
            self.save_registry()
            return True
        return False

    # -------------------------------------------------------------------------
    # Özel Ajan Tanımlama ve Mevcut Ajanları Güncelleme / Düzenleme
    # -------------------------------------------------------------------------
    async def register_custom_agent(self, agent_data: Dict[str, Any]) -> Dict[str, Any]:
        """Arayüzden yeni bir kıdemli geliştirici veya özel rol ekler / günceller.
        G6 (bkz. server/agent_registry.py): `role_base` (devralınan temel rol), `capabilities` (iş türleri), `focus`, `profile`, `active`, `meeting_roles`, `evaluates`,
        `prompt_addendum`; `scope: "global"` ajanı şirket geneli kayda da yazar (her projede görünür)."""
        from . import agent_registry as AR
        agent_id = AR.clean_id(agent_data.get("id", "")) or f"DEV_{len(self.agents) + 1}"

        if agent_id in self.agents:
            return await self.update_agent(agent_id, agent_data)

        data = {**agent_data}
        if not str(data.get("role_base") or "").strip():
            guess = AR.clean_id(data.get("role"))
            data["role_base"] = guess if guess in AR.BASE_ROLES else "BACKEND_DEV"
        full = AR.normalize_definition({**data, "name": str(data.get("name") or agent_id), "role": str(data.get("role") or "DEVELOPER")})
        now = datetime.now(timezone.utc).isoformat()
        agent = {
            "id": agent_id,
            "status": "IDLE",
            "tokens_in": 0,
            "tokens_out": 0,
            "total_tokens": 0,
            "last_action": "CUSTOM_AGENT_ADDED",
            "last_seen": now,
            **{k: v for k, v in full.items() if k in AR.DEFINITION_FIELDS},
            "scope": "project",
        }
        if str(agent_data.get("scope") or "").lower() == "global" and agent_id not in AR.CORE_IDS:
            gdef = AR.upsert_global(agent_id, {k: agent[k] for k in AR.DEFINITION_FIELDS if k in agent})
            agent["overrides"] = {}
            AR.apply_global_to_agent(agent, gdef)
        self.agents[agent_id] = agent
        await self.broadcast({
            "type": "AGENT_ADDED",
            "agent": agent,
            "agents": list(self.agents.values())
        })
        self.save_registry()
        return agent

    async def update_agent(self, agent_id: str, updates: Dict[str, Any]) -> Dict[str, Any]:
        """Mevcut bir ajanın (örn. E2E_TESTER, QA, BACKEND_DEV) bilgilerini günceller."""
        agent_id = agent_id.upper().strip().replace(" ", "_")
        if agent_id not in self.agents:
            return await self.register_custom_agent({**updates, "id": agent_id})

        agent = self.agents[agent_id]
        if "status" in updates:
            agent["status"] = updates["status"]
        self._apply_agent_definition(agent, updates)

        agent["last_seen"] = datetime.now(timezone.utc).isoformat()
        agent["last_action"] = "AGENT_UPDATED"

        self.save_registry()
        await self.broadcast({
            "type": "AGENT_UPDATED",
            "agent": agent,
            "agents": list(self.agents.values())
        })
        return agent

    def _apply_agent_definition(self, agent: Dict[str, Any], updates: Dict[str, Any]) -> None:
        """Tanım alanlarını (ad, rol, açıklama, yetenek, profil ...) uygular. Global bir ajanda değişiklik projeye özgü FARK (`overrides`) olur;
        `reset_overrides: [anahtar]` farkı geri alır. `scope: "global"` projedeki ajanı şirket geneli kayda terfi ettirir."""
        from . import agent_registry as AR
        fields = AR.normalize_definition(updates, partial=True)
        for blank in ("name", "role"):
            if not fields.get(blank):
                fields.pop(blank, None)                       # boş ad/rol eskisini silmez
        aid = agent["id"]
        if agent.get("inherits"):
            ov = agent.setdefault("overrides", {})
            for key, val in fields.items():
                if key == "profile" and isinstance(ov.get("profile"), dict):
                    ov["profile"] = {**ov["profile"], **val}
                else:
                    ov[key] = val
            for key in AR._str_list(updates.get("reset_overrides"), limit=20):
                ov.pop(key, None)
            gdef = AR.load_global().get(agent["inherits"])
            if gdef:
                AR.apply_global_to_agent(agent, gdef)
            else:
                agent.pop("inherits", None)
                agent["scope"] = "project"
        else:
            agent.update(fields)
            agent["scope"] = "core" if aid in AR.CORE_IDS else "project"
            if str(updates.get("scope") or "").lower() == "global" and aid not in AR.CORE_IDS:
                gdef = AR.upsert_global(aid, AR.definition_of(agent))
                agent["overrides"] = {}
                AR.apply_global_to_agent(agent, gdef)

    async def delete_agent(self, agent_id: str) -> bool:
        """Özel eklenen bir ajanı kaldırır veya Core ajanları varsayılana döndürür."""
        agent_id = agent_id.upper().strip().replace(" ", "_")
        core_ids = {a["id"] for a in DEFAULT_AGENTS}

        if agent_id in core_ids:
            default_match = next((a for a in DEFAULT_AGENTS if a["id"] == agent_id), None)
            if default_match:
                self.agents[agent_id].update({
                    **default_match,
                    "tokens_in": 0,
                    "tokens_out": 0,
                    "total_tokens": 0,
                    "status": "IDLE",
                    "last_action": "RESET_TO_DEFAULT",
                    "last_seen": datetime.now(timezone.utc).isoformat()
                })
        elif agent_id in self.agents and self.agents[agent_id].get("inherits") and self._pool_auto(self.agents[agent_id]["inherits"]):
            # Her projeye otomatik atanan havuz ajanı projeden silinemez (yeniden görünür); bu projede pasifleştirilir
            ag = self.agents[agent_id]
            ag.setdefault("overrides", {})["active"] = False
            ag["active"] = False
            ag["last_action"] = "DEACTIVATED_IN_PROJECT"
        elif agent_id in self.agents:
            if self.agents[agent_id].get("default_optional"):
                removed = set((self.settings or {}).get("removed_default_agents") or [])
                removed.add(agent_id)                                  # kaldırılan varsayılan ajan yeniden yüklemede geri gelmez
                self.settings = {**(self.settings or {}), "removed_default_agents": sorted(removed)}
            del self.agents[agent_id]
        else:
            return False

        self.save_registry()
        await self.broadcast({
            "type": "AGENT_DELETED",
            "agent_id": agent_id,
            "agents": list(self.agents.values())
        })
        return True

    async def update_agent_metric(
        self,
        agent_name: str,
        tokens_in: int = 0,
        tokens_out: int = 0,
        active_file: Optional[str] = None,
        latency_ms: float = 0.0,
        status: str = "WORKING"
    ) -> Dict[str, Any]:
        """Ajan telemetri ve tüketim verilerini günceller."""
        agent_id = agent_name.upper()
        if agent_id not in self.agents:
            self.agents[agent_id] = {
                "id": agent_id,
                "name": agent_name,
                "role": agent_id,
                "status": status,
                "active_file": active_file or "",
                "tokens_in": 0,
                "tokens_out": 0,
                "total_tokens": 0,
                "last_action": "METRIC_UPDATE",
                "last_seen": datetime.now(timezone.utc).isoformat()
            }

        agent = self.agents[agent_id]
        agent["tokens_in"] += tokens_in
        agent["tokens_out"] += tokens_out
        agent["total_tokens"] += (tokens_in + tokens_out)
        agent["status"] = status
        if active_file:
            agent["active_file"] = active_file
        agent["last_seen"] = datetime.now(timezone.utc).isoformat()

        self.stats["total_tokens"] += (tokens_in + tokens_out)

        event = {
            "type": "AGENT_METRIC_UPDATED",
            "agent": agent,
            "latency_ms": latency_ms
        }
        await self.broadcast(event)
        self.save_registry()
        return agent

    async def set_agent_status(self, agent_id: str, status: str, what_doing: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Ajan kartının durumunu değiştirir ve yayınlar (WORKING yalnızca adımı gerçekten süren ajanda kalır)."""
        agent = self.agents.get((agent_id or "").upper())
        if not agent:
            return None
        agent["status"] = status
        if what_doing is not None:
            agent["current_what_doing"] = what_doing
        if status == "IDLE":
            agent.pop("current_thinking", None)
            agent.pop("current_what_doing", None)
        agent["last_seen"] = datetime.now(timezone.utc).isoformat()
        await self.broadcast({"type": "AGENT_METRIC_UPDATED", "agent": agent, "latency_ms": 0})
        self.mark_dirty()
        return agent

    async def settle_agents_after_run(self, completed: bool) -> None:
        """Koşu bitince: çalışan/bekleyen ajanlar sakinleşir (COMPLETED veya IDLE), 'yeşil çalışıyor' izlenimi kalmaz."""
        for aid, a in list(self.agents.items()):
            st = a.get("status")
            if st == "WORKING":
                await self.set_agent_status(aid, "COMPLETED" if completed else "IDLE")
            elif st in ("PENDING_ACTION", "BUG_FIX"):
                await self.set_agent_status(aid, "IDLE")

    async def reset(self):
        """Aktif projenin telemetri tahtasını sıfırlar."""
        try:
            await asyncio.to_thread(self._maybe_snapshot, "pre-reset", True)
        except Exception:
            pass
        self.events.clear()
        self.tasks.clear()
        if not self.jira_issues:
            self.jira_issues = create_default_jira_issues()
        else:
            # G0: sıfırlama telemetriyi temizler, iş planını SİLMEZ. Yalnızca o anda süren maddeler (koşu iptal edildiği için) backlog'a döner.
            for issue in self.jira_issues.values():
                if issue.get("status") in ("IN_PROGRESS", "IN_REVIEW"):
                    issue["status"] = "BACKLOG"
        for a in self.agents.values():
            a["status"] = "IDLE"
            a["tokens_in"] = 0
            a["tokens_out"] = 0
            a["total_tokens"] = 0
            a["last_action"] = "RESET"
            a["active_file"] = ""
            # Konuşma baloncukları / düşünce metinleri de sıfırlanır (aksi hâlde STATE_RESET ile geri gelirler)
            for key in ("current_dialogue", "current_thinking", "current_what_doing", "current_what_next"):
                a.pop(key, None)
        self.stats["total_events"] = 0
        self.stats["total_tokens"] = 0
        self.stats["active_tasks_count"] = 0
        self._event_seq = 0
        self.stats["event_seq"] = 0

        # Onay sürecini sıfırla: bekleyen tüm adımlar iptal edilir, koşu kendini sonlandırır
        self.pending_step_approval = None
        self.auto_proceed_all = False
        self.auto_proceed_run_id = None
        self.gate.resolve_all("CANCELLED")
        self.approval_token = None

        event = {
            "type": "STATE_RESET",
            "agents": list(self.agents.values()),
            "tasks": [],
            "jira_issues": list(self.jira_issues.values()),
            "events": [],
            "pending_step_approval": None,
            "step_by_step_mode": self.step_by_step_mode
        }
        await self.broadcast(event)
        self.save_registry()

    # -------------------------------------------------------------------------
    # Adım Adım İnceleme & Devam Onayı (Human-in-the-Loop Step Approval)
    # -------------------------------------------------------------------------
    def open_step_approval(self, step_info: Dict[str, Any]) -> str:
        """
        Adımı onaya sunar ve token'ını döner; beklemez. Yoklama (poll) tabanlı istemciler
        (MCP aracı) bu token ile `poll_step_approval` çağırır.
        """
        token = self.gate.mint()
        info = {**step_info, "approval_token": token}
        self.pending_step_approval = info
        self.approval_token = token
        self.gate.register(token, info)
        return token

    async def poll_step_approval(self, token: str, timeout_s: float) -> Optional[str]:
        """Token için en fazla `timeout_s` bekler; karar yoksa None döner (bekleme sürer)."""
        return await self.gate.wait(token, timeout=timeout_s)

    async def close_step_approval(self, token: str, decision: str, step_info: Optional[Dict[str, Any]] = None):
        """Onay sürecini kapatır ve sonucu yayınlar."""
        info = step_info or self.gate.info(token) or self.pending_step_approval or {}
        self.gate.forget(token)
        if self.approval_token == token:
            self.approval_token = None
            self.pending_step_approval = None
        await self.broadcast({
            "type": "STEP_APPROVED",
            "step_info": info,
            "decision": decision
        })

    async def wait_for_step_approval(self, step_info: Dict[str, Any], timeout_s: Optional[float] = None) -> str:
        """
        Ajanın icra ettiği adımın çıktısını incelemeye sunar ve kullanıcı onay verene kadar bekler.
        Kullanıcı 'Kalanları Otomatik Tamamla' seçmişse beklemeden devam eder.
        Süre dolarsa "TIMEOUT", reset ile iptal edilirse "CANCELLED" döner; çağıran koşuyu durdurmalıdır.
        """
        if self.auto_proceed_all:
            return "AUTO_ALL"

        token = self.open_step_approval(step_info)
        info = self.pending_step_approval or {**step_info, "approval_token": token}

        # Tüm bağlı WebSocket arayüzlerine modalı açma sinyali gönder
        await self.broadcast({
            "type": "STEP_WAITING_APPROVAL",
            "step_info": info
        })

        timeout = DEFAULT_STEP_APPROVAL_TIMEOUT_S if timeout_s is None else timeout_s
        decision = await self.gate.wait(token, timeout=timeout if timeout > 0 else None)
        if decision is None:
            decision = "TIMEOUT"
            self.gate.cancel(token)

        await self.close_step_approval(token, decision, info)
        return decision

    async def approve_step(self, decision: str = "PROCEED", token: Optional[str] = None, comment: str = "") -> Dict[str, Any]:
        """Kullanıcının adıma verdiği onayı çözer ve akışı bir sonraki adıma geçirir.
        `REVISE`: adımı `comment` geri bildirimiyle aynı sıra numarasıyla yeniden ürettirir (gerekçe zorunlu)."""
        target = token or self.approval_token
        if decision == "REVISE":
            from . import pipeline as P
            run = next((r for r in self.runs.values() if r.approval_token and r.approval_token == target), None)
            if run is None:
                return {"status": "NO_PENDING_STEP", "decision": decision, "token": target, "auto_proceed_all": self.auto_proceed_all}
            reason = P.can_revise(self, run, run.current_step)
            if reason is None and not str(comment or "").strip():
                reason = tx("Revize için geri bildirim (ne düzeltilsin?) yazın.")
            if reason:
                return {"status": "INVALID", "decision": decision, "token": target, "error": reason, "auto_proceed_all": self.auto_proceed_all}
            await P.add_manager_note(self, run, comment, kind="revise")
        if decision == "AUTO_ALL":
            self.auto_proceed_all = True
        resolved = self.gate.resolve(target, decision)
        return {
            "status": "APPROVED" if resolved else "NO_PENDING_STEP",
            "decision": decision,
            "token": target,
            "auto_proceed_all": self.auto_proceed_all
        }

    async def set_step_mode(self, enabled: bool) -> bool:
        """İkili adım-adım anahtarı (uyumluluk): açık → 'every_step', kapalı → 'auto' onay modu."""
        self.step_by_step_mode = enabled
        if not enabled:
            self.auto_proceed_all = False
            if self.approval_token:
                self.gate.resolve(self.approval_token, "AUTO_ALL")
        target_mode = "every_step" if enabled else "auto"
        current = self.get_settings().get("approval_mode", "every_step")
        if (current == "auto") != (target_mode == "auto"):
            await self.update_settings({"approval_mode": target_mode})  # STEP_MODE_CHANGED yayınlar
        else:
            await self.broadcast({
                "type": "STEP_MODE_CHANGED",
                "step_by_step_mode": self.step_by_step_mode,
                "approval_mode": current
            })
        return self.step_by_step_mode

    # -------------------------------------------------------------------------
    # Pipeline Koşuları, Proje Ayarları ve MCP İstemcileri
    # -------------------------------------------------------------------------
    def register_run(self, run: PipelineRun) -> PipelineRun:
        self.runs[run.run_id] = run
        self.mark_dirty()
        return run

    def get_run(self, run_id: str) -> Optional[PipelineRun]:
        return self.runs.get(run_id)

    def active_run_for(self, project_id: Optional[str] = None) -> Optional[PipelineRun]:
        """Proje için sonlanmamış (QUEUED/ACTIVE/WAITING_APPROVAL) koşuyu döner."""
        pid = project_id or self.active_project_id
        candidates = [r for r in self.runs.values() if r.project_id == pid and not r.is_terminal]
        candidates.sort(key=lambda r: r.created_at, reverse=True)
        return candidates[0] if candidates else None

    def active_run_summary(self) -> Optional[Dict[str, Any]]:
        run = self.active_run_for(self.active_project_id)
        return run.to_dict() if run else None

    def recent_runs(self, limit: int = 20) -> List[Dict[str, Any]]:
        runs = [r for r in self.runs.values() if r.project_id == self.active_project_id]
        runs.sort(key=lambda r: r.created_at, reverse=True)
        return [r.to_dict() for r in runs[:limit]]

    def get_settings(self) -> Dict[str, Any]:
        from .sprint import sanitize_sprint_settings
        merged = {**_default_settings(), **(self.settings or {})}
        # Sprint kipi anahtarları her zaman tam döner: pano `sprint.enabled` değerini kesin görür (varsayılanlar server/sprint.py'de,
        # DEFAULT_SETTINGS'teki boş sözlük "tanımsız" demek değildir)
        merged["sprint"] = sanitize_sprint_settings(merged.get("sprint"))
        return merged

    # ---- Teknoloji kararları (bkz. server/decisions.py) ----
    def tech_questions(self) -> List[Dict[str, Any]]:
        from .decisions import merge_questions
        return merge_questions((self.settings or {}).get("tech_questions") or [])

    def tech_decisions(self) -> Optional[Dict[str, Any]]:
        return (self.settings or {}).get("tech_decisions") or None

    async def add_spec_questions(self, raw_questions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """PM adımının şartnameden çıkardığı açık soruları soru setine ekler (id çakışırsa günceller)."""
        from .decisions import normalize_question
        existing = list((self.settings or {}).get("tech_questions") or [])
        by_id = {q.get("id"): q for q in existing if isinstance(q, dict)}
        for raw in raw_questions or []:
            q = normalize_question(raw)
            if q:
                by_id[q["id"]] = q
        await self.update_settings({"tech_questions": list(by_id.values())})
        return self.tech_questions()

    # ---- Teknoloji gereksinimleri (F2; bkz. server/tech_requirements.py) ----
    def tech_requirements(self) -> Optional[Dict[str, Any]]:
        return (self.settings or {}).get("tech_requirements") or None

    def tech_requirements_approved(self) -> bool:
        """Teknoloji kapısının tek ölçütü: tüm kalemler ONAYLANDI ve açık engelleyici soru yok."""
        from .tech_requirements import is_approved
        return is_approved(self.tech_requirements())

    def _tech_project_dir(self, req: Optional[Dict[str, Any]] = None, project_dir: Optional[str] = None) -> str:
        return project_dir or (req or {}).get("project_dir") or (self.projects.get(self.active_project_id) or {}).get("path") or self.default_project_path

    async def _store_tech(self, req: Dict[str, Any], adr_title: Optional[str] = None, adr_items: Optional[List[Dict[str, Any]]] = None,
                          adr_context: str = "", by: str = "MANAGER", notes: str = "", source: Optional[str] = None) -> Dict[str, Any]:
        """Kaydı saklar, TECH_REQUIREMENTS.md (+ADR) yazar, onaylı kalemleri tech_decisions'a eşler, yayınlar; tamamsa kapıyı çözer."""
        from .decisions import make_decisions
        from .paths import hub_docs_path
        from .tech_requirements import ONAYLANDI, is_approved, write_documents
        project_dir = self._tech_project_dir(req)
        req["project_dir"] = project_dir
        proj_name = (self.projects.get(self.active_project_id) or {}).get("name") or os.path.basename(project_dir) or "Proje"
        written = []
        if os.path.isdir(project_dir):
            written = write_documents(req, project_dir, hub_docs_path(self, "", project_dir), proj_name, adr_title, adr_items, adr_context, by)
            from .doc_sync import sync_architecture   # teknoloji kararı değişti: mimar belgesinin güncel karar durumu bölümü yenilenir
            sync_architecture(self, project_dir)
        req["files"] = written
        approved_answers = {it["category"]: it["value"] for it in req["items"] if it["status"] == ONAYLANDI and it.get("value")}
        updates: Dict[str, Any] = {"tech_requirements": req}
        if approved_answers:
            prev = self.tech_decisions() or {}
            updates["tech_decisions"] = make_decisions(self.tech_questions(), approved_answers, notes or prev.get("notes", ""), source or prev.get("source") or "user")
        await self.update_settings(updates)
        await self.broadcast({"type": "TECH_REQUIREMENTS_UPDATED", "tech_requirements": req})
        if "tech_decisions" in updates:
            await self.broadcast({"type": "DECISIONS_SAVED", "tech_decisions": updates["tech_decisions"], "tech_questions": self.tech_questions()})
        pending = self.pending_step_approval or {}
        if is_approved(req) and pending.get("kind") == "decisions" and self.approval_token:
            self.gate.resolve(self.approval_token, "PROCEED")
        return req

    async def ensure_tech_requirements(self, project_dir: Optional[str] = None) -> Dict[str, Any]:
        """Notlardan kalem listesini kurar (ya da yeni notla farkı işler); onayları KORUR ama onay vermez."""
        from .pipeline import collect_spec_text
        from .tech_requirements import _spec_hash, build_requirements
        existing = self.tech_requirements()
        if existing and await self._reconcile_dependency_questions(existing):
            existing = self.tech_requirements()
        if existing and not existing.get("first_approved_at") and not any(it.get("status") == "ONAYLANDI" for it in existing.get("items", [])):
            # Kayıt var ama hiç onaylı kalem yok (durum sıfırdan kurulmuş): onaylı TECH_REQUIREMENTS.md belgesi varsa kararlar oradan geri kurulur
            before = sum(1 for it in existing["items"] if it.get("status") == "ONAYLANDI")
            existing = self._restore_tech_from_document(existing)
            if sum(1 for it in existing["items"] if it.get("status") == "ONAYLANDI") > before:
                existing = await self._store_tech(existing)
        spec_text = collect_spec_text(self)
        questions = self.tech_questions()
        known = {it["category"] for it in (existing or {}).get("items", [])}
        if existing and existing.get("spec_hash") == _spec_hash(spec_text) and known == {q["id"] for q in questions}:
            if project_dir and os.path.abspath(project_dir) != os.path.abspath(existing.get("project_dir") or ""):
                existing["project_dir"] = project_dir  # koşu başka bir hedef klasöre yazıyor: dosyalar oraya da yazılır
                return await self._store_tech(existing)
            return existing
        title = ""
        if getattr(self, "uploaded_specs", None):
            latest = self.uploaded_specs[-1]
            title = f"{latest.get('client_name', tx('Müşteri'))} — {latest.get('title', tx('Şartname'))}"
        prior = ((self.tech_decisions() or {}).get("answers") if not existing else None) or None
        req = build_requirements(questions, spec_text, title, self._tech_project_dir(existing, project_dir),
                                 hints=(self.settings or {}).get("tech_extraction_hints") or [], prior_answers=prior, existing=existing)
        if not existing:
            # Durum kaydı yok (ayarlar sıfırlandı): projedeki onaylı TECH_REQUIREMENTS.md varsa kararlar oradan geri kurulur, yeniden sorulmaz
            req = self._restore_tech_from_document(req)
        return await self._store_tech(req)

    def _restore_tech_from_document(self, req: Dict[str, Any]) -> Dict[str, Any]:
        from .paths import hub_docs_path
        from .tech_requirements import parse_approved_markdown, restore_approvals
        project_dir = req.get("project_dir") or self._tech_project_dir(None)
        try:
            rel = hub_docs_path(self, "TECH_REQUIREMENTS.md", project_dir)
            with open(os.path.join(project_dir, *rel.split("/")), "r", encoding="utf-8") as f:
                approved = parse_approved_markdown(f.read())
            if approved and restore_approvals(req, approved):
                self.data_warnings.setdefault(self.active_project_id, []).append(
                    {"file": "tech_requirements", "message": tx("Teknoloji kararları TECH_REQUIREMENTS.md belgesinden geri kuruldu ({n} kalem).", n=len(approved))})
        except OSError:
            pass
        return req

    async def approve_tech_requirements(self, answers: Optional[Dict[str, Any]] = None, approve_stated: bool = False,
                                        accept_recommended: bool = False, by: str = "MANAGER", notes: str = "",
                                        source: str = "user") -> Dict[str, Any]:
        from .tech_requirements import ONAYLANDI, apply_approval, is_approved
        req = await self.ensure_tech_requirements()
        before = {it["id"]: it["status"] for it in req["items"]}
        first_time = not req.get("first_approved_at")
        changed = apply_approval(req, answers=answers, approve_stated=approve_stated, accept_recommended=accept_recommended, by=by)
        adr_title, adr_items, ctx = None, None, ""
        if changed and is_approved(req):
            now = datetime.now(timezone.utc).isoformat()
            if first_time:
                req["first_approved_at"] = now
                adr_title, adr_items = tx("Teknoloji yığınının kuruluş onayı"), list(req["items"])
                ctx = tx("Proje kuruluşunda notlardan çıkarılan ve yönetici tarafından cevaplanan teknoloji kalemleri ({n} kalem) tek kararla onaylandı.", n=len(adr_items))
            else:
                adr_items = [it for it in req["items"] if it["id"] in changed and before.get(it["id"]) == ONAYLANDI] or None
                if adr_items:
                    adr_title, ctx = tx("Teknoloji değişikliği"), tx("Onaylı bir teknoloji kalemi yönetici kararıyla değiştirildi ya da yeni notla yeniden onaylandı.")
        return await self._store_tech(req, adr_title, adr_items, ctx, by, notes, source)

    async def dry_run_approve_tech(self) -> Dict[str, Any]:
        """YALNIZCA deneme: FSSC_DRY_RUN=1 ve şablon motoru. Gerçek koşuda çağrı reddedilir."""
        from .tech_requirements import dry_run_enabled
        if not dry_run_enabled():
            raise PermissionError(tx("Deneme bayrağı (FSSC_DRY_RUN=1) kapalı; teknoloji kapısı yalnızca yönetici onayıyla geçilir."))
        return await self.approve_tech_requirements(approve_stated=True, accept_recommended=True, by="DRY_RUN", source="dry_run")

    async def answer_tech_question(self, question_id: str, answer: str) -> Dict[str, Any]:
        from .tech_requirements import apply_approval, refresh_status
        req = await self.ensure_tech_requirements()
        q = next((x for x in req.get("questions", []) if x["id"] == question_id), None)
        if q is None:
            raise KeyError(question_id)
        answer = str(answer or "").strip()
        if not answer:
            raise ValueError("answer boş olamaz")
        if q.get("kind") == "dependency":
            q["answer"], q["status"] = answer, "CEVAPLANDI"
            if answer.lower().startswith(("onay", "evet", "izin", "approve", "yes", "allow")):
                await self.register_libraries([{"name": q["dependency"], "purpose": tx("yönetici onaylı ek bağımlılık"), "technology": q.get("file", "")}], save=False, req=req)
                refresh_status(req)
                item = {"id": q["id"], "label": tx("Ek bağımlılık: {dep}", dep=q['dependency']), "value": tx("eklenmesine izin verildi"), "extracted_status": "YÖNETİCİ"}
                return await self._store_tech(req, tx("Teknoloji değişikliği: ek bağımlılık"), [item], tx("{dep} ({file}) onaylı teknolojilerde yoktu; yönetici ekleme kararı verdi.", dep=q['dependency'], file=q.get('file', '')))
            req.setdefault("rejected", []).append({"name": q["dependency"], "decision": "Reddedildi", "basis": q["id"]})
            refresh_status(req)
            return await self._store_tech(req)
        if q.get("item_id"):
            return await self.approve_tech_requirements(answers={q["item_id"]: answer})
        refresh_status(req)
        return await self._store_tech(req)

    async def register_libraries(self, libs: List[Dict[str, Any]], save: bool = True, req: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        """Mimarın kütüphane kararı (onaylı yığın içinde). Dört yönetici-onayı koşulu için sunucu ayrıca denetlemez; mimar sorumludur."""
        req = req or self.tech_requirements()
        if not req:
            return None
        from .tech_requirements import _norm
        have = {_norm(l.get("name", "")) for l in req.get("libraries", [])}
        for raw in libs or []:
            if not isinstance(raw, dict):
                continue
            name = str(raw.get("name") or "").strip()[:80]
            if name and _norm(name) not in have:
                req.setdefault("libraries", []).append({"name": name, "purpose": str(raw.get("purpose") or "")[:160], "technology": str(raw.get("technology") or "")[:80]})
                have.add(_norm(name))
        return await self._store_tech(req) if save else req

    def _decided_dependency(self, name: str) -> Optional[str]:
        """Yönetici bir toplantı/soru kararında bu bağımlılığı adıyla seçtiyse (ör. Q-11 → "@nestjs/swagger") o kararın kimliği; yoksa None."""
        from .sprint import ensure_state
        n = str(name or "").strip().lower()
        if not n:
            return None
        for d in ensure_state(self).get("decisions") or []:
            if d.get("human_approved") and n in str(d.get("text") or "").lower():
                return str(d.get("id"))
        return None

    async def _reconcile_dependency_questions(self, req: Dict[str, Any]) -> bool:
        """Açık bağımlılık sorusu, yöneticinin zaten onayladığı bir karardaki kütüphaneyse otomatik cevaplanır ve kütüphane kaydına işlenir (aynı şey iki kez sorulmaz)."""
        from .tech_requirements import refresh_status
        changed = False
        for q in req.get("questions", []):
            if q.get("kind") == "dependency" and q.get("status") == "AÇIK":
                did = self._decided_dependency(q.get("dependency", ""))
                if did:
                    q["answer"], q["status"] = tx("Onaylandı (yönetici kararı {did})", did=did), "CEVAPLANDI"
                    await self.register_libraries([{"name": q["dependency"], "purpose": tx("yönetici kararıyla onaylı ({did})", did=did), "technology": q.get("file", "")}], save=False, req=req)
                    changed = True
        if changed:
            refresh_status(req)
            await self._store_tech(req)
        return changed

    async def request_tech_addition(self, violations: List[Dict[str, str]]) -> None:
        """Kayıtsız bağımlılık için engelleyici TECHNOLOGY sorusu açar (aynı bağımlılık için tekrar açmaz; yönetici zaten onayladıysa hiç sormaz)."""
        from .tech_requirements import refresh_status
        req = self.tech_requirements()
        if not req:
            return
        qs = req.setdefault("questions", [])
        for v in violations:
            did = self._decided_dependency(v["dependency"])
            if did:
                await self.register_libraries([{"name": v["dependency"], "purpose": tx("yönetici kararıyla onaylı ({did})", did=did), "technology": v.get("file", "")}], save=False, req=req)
                continue
            if any(q.get("kind") == "dependency" and q.get("dependency") == v["dependency"] and q.get("status") == "AÇIK" for q in qs):
                continue
            qs.append({"id": f"D-{sum(1 for x in qs if x.get('kind') == 'dependency') + 1}", "item_id": None, "category": "TECHNOLOGY", "blocking": True, "kind": "dependency",   # D-n: toplantı soru kuyruğunun Q-n numaralarıyla çakışmaz
                       
                       "dependency": v["dependency"], "file": v["file"], "status": "AÇIK", "answer": None,
                       "question": tx("'{dep}' ({file}) onaylı teknolojilerde ve kütüphane kaydında yok. Eklenmesine izin verilsin mi?", dep=v['dependency'], file=v['file']),
                       "options": [{"value": tx("Onayla ve kütüphane olarak kaydet"), "pros": tx("İş devam eder"), "cons": tx("Yeni bağımlılık")},
                                   {"value": tx("Reddet"), "pros": tx("Yığın sade kalır"), "cons": tx("Ajan başka çözüm bulmak zorunda")}],
                       "recommended": tx("Reddet"), "why": tx("Teknoloji ya da kütüphane seçimi yöneticiye aittir (§3.2).")})
        refresh_status(req)
        await self._store_tech(req)

    async def save_tech_decisions(self, answers: Dict[str, Any], notes: str = "", source: str = "user") -> Dict[str, Any]:
        """Yönetici cevaplarını kalem onayı olarak işler. Tüm kalemler onaylanmadıkça bekleyen kapı AÇIK kalır."""
        await self.approve_tech_requirements(answers=answers or {}, by="MANAGER" if source == "user" else source.upper(), notes=notes, source=source)
        return self.tech_decisions() or {"answers": {}, "notes": notes, "source": source, "answered_at": datetime.now(timezone.utc).isoformat()}

    async def clear_tech_decisions(self) -> None:
        await self.update_settings({"tech_decisions": None, "tech_requirements": None})
        await self.broadcast({"type": "DECISIONS_SAVED", "tech_decisions": None, "tech_questions": self.tech_questions()})

    async def update_settings(self, updates: Dict[str, Any]) -> Dict[str, Any]:
        """Motor / onay modu / hız ayarlarını günceller, kaydeder ve yayınlar."""
        allowed = {
            "execution_engine": {"mcp_client", "template"},
            "approval_mode": {"auto", "critical_only", "every_step", "note_and_continue"},
            "pacing": {"instant", "natural"},
            "verify_scope": {"incremental", "full"},
        }
        merged = self.get_settings()
        for key, value in (updates or {}).items():
            if key in allowed:
                if value in allowed[key]:
                    merged[key] = value
            elif key in ("e2e_target_url",) and isinstance(value, str):
                merged[key] = value
            elif key == "agent_skills":
                from .skills import sanitize_settings as _skill_cfg
                merged[key] = _skill_cfg(value)
            elif key == "claude_design_url" and isinstance(value, str):
                v = value.strip()
                if v == "" or re.match(r"^https://claude\.ai/[A-Za-z0-9_./?=&%#-]{4,300}$", v):
                    merged[key] = v                           # yalnızca claude.ai bağlantısı (ya da boş: kaldır)
            elif key in ("auto_backlog", "auto_verify", "auto_commit", "llm_fallback", "verify_light", "design_first", "skip_satisfied_tasks"):
                merged[key] = bool(value)
            elif key in ("product_first", "fidelity_gate"):
                merged[key] = bool(value)
            elif key == "backlog_cap":
                try:
                    merged[key] = max(5, min(int(value), 500))
                except (TypeError, ValueError):
                    pass
            elif key == "product_statement" and isinstance(value, str):
                merged[key] = " ".join(value.split())[:1500]
            elif key == "project_language":
                from .i18n import SUPPORTED as _LANGS
                if str(value or "").strip().lower() in _LANGS:
                    merged[key] = str(value).strip().lower()
            elif key == "python_isolation":
                if value in ("venv", "host"):
                    merged[key] = value
            elif key in ("max_fix_rounds", "max_backlog_tasks", "max_uat_rounds"):
                try:
                    merged[key] = max(0, min(int(value), 50))
                except (TypeError, ValueError):
                    pass
            elif key == "docs_root":
                from .paths import sanitize_docs_root
                merged[key] = sanitize_docs_root(value)  # geçersiz/boş değer otomatik algılamaya döner
            elif key == "verification" and isinstance(value, dict):
                from .verify import sanitize_verification
                merged[key] = sanitize_verification(value)
            elif key == "tech_questions" and isinstance(value, list):
                merged[key] = value
            elif key in ("tech_decisions", "tech_requirements") and (value is None or isinstance(value, dict)):
                merged[key] = value
            elif key == "tech_extraction_hints" and isinstance(value, list):
                merged[key] = value
            elif key == "sandbox" and isinstance(value, dict):
                from .guard import sanitize_sandbox
                merged[key] = sanitize_sandbox(value, fallback=sanitize_sandbox(merged.get("sandbox")))
            elif key == "runner" and isinstance(value, dict):
                from .driver import sanitize_runner
                merged[key] = sanitize_runner(value, fallback=sanitize_runner(merged.get("runner")))
            elif key == "display" and isinstance(value, dict):
                from .driver import sanitize_display
                merged[key] = sanitize_display(value, fallback=sanitize_display(merged.get("display")))
            elif key == "autonomy" and isinstance(value, dict):
                from .meetings import sanitize_autonomy
                merged[key] = sanitize_autonomy(value, fallback=sanitize_autonomy(merged.get("autonomy")))
            elif key == "sprint" and isinstance(value, dict):
                from .sprint import sanitize_sprint_settings
                merged[key] = sanitize_sprint_settings(value, fallback=sanitize_sprint_settings(merged.get("sprint")))
            elif key == "claude" and isinstance(value, dict):
                from .claude_bridge import sanitize_claude
                merged[key] = sanitize_claude(value, fallback=sanitize_claude(merged.get("claude")))
            elif key == "jira_filters" and isinstance(value, list):
                # G5: kayıtlı Jira süzgeçleri (ad + JQL benzeri sorgu)
                merged[key] = [{"name": str(f.get("name", "")).strip()[:60], "q": str(f.get("q", ""))[:500], "created_at": str(f.get("created_at", ""))}
                               for f in value if isinstance(f, dict) and str(f.get("name", "")).strip()][:50]
            elif key == "project_layout" and isinstance(value, dict):
                # Proje klasör düzeni (apps/devops/docs); adlar ve rol eşlemesi buradan tanımlanır
                from .layout import sanitize_layout
                merged[key] = sanitize_layout(value, fallback=sanitize_layout(merged.get("project_layout")) if isinstance(merged.get("project_layout"), dict) else None)
            elif key == "teams" and isinstance(value, list):
                merged[key] = value
        mode_changed = merged.get("approval_mode") != (self.settings or {}).get("approval_mode")
        lang_changed = (merged.get("project_language") or "tr") != ((self.settings or {}).get("project_language") or "tr")
        self.settings = merged
        if self.active_project_id in self.projects:
            self.projects[self.active_project_id]["settings"] = copy.deepcopy(merged)
        # Geriye dönük uyumluluk: ikili adım-adım bayrağı onay modundan türetilir
        self.step_by_step_mode = merged.get("approval_mode", "every_step") != "auto"
        if lang_changed:
            try:                # CLAUDE.md / GEMINI.md içindeki FS-SC kural bloğu da yeni dilde yeniden yazılır
                from . import i18n as _i18n
                from .project_bootstrap import bootstrap_project
                proj = self.projects.get(self.active_project_id) or {}
                if proj.get("path") and os.path.isdir(proj["path"]):
                    with _i18n.use_lang(merged.get("project_language")):
                        bootstrap_project(proj["path"], self.active_project_id)
            except Exception:
                pass
            # Proje dili değişti: hâlâ varsayılan metni taşıyan varsayılan Jira maddeleri / ajan açıklamaları / test profilleri yeni dile çevrilir (düzenlenenlere dokunulmaz)
            if any(retranslate_defaults(self, merged.get("project_language")).values()):
                await self.broadcast({"type": "AGENTS_UPDATED", "agents": list(self.agents.values())})
                await self.broadcast({"type": "JIRA_UPDATED", "issue": None, "jira_issues": self.get_jira_issues(), "all_issues": self.get_jira_issues(),
                                      "tasks": self.get_jira_issues(), "source": "LANGUAGE_CHANGED"})
        self.mark_dirty()
        await self.broadcast({"type": "SETTINGS_UPDATED", "settings": merged, "project_id": self.active_project_id})
        if mode_changed:
            await self.broadcast({"type": "STEP_MODE_CHANGED", "step_by_step_mode": self.step_by_step_mode, "approval_mode": merged.get("approval_mode")})
        return merged

    async def raise_hand(self, step_info: Dict[str, Any], note: str = "") -> Dict[str, Any]:
        """'Not al ve devam et' modunda adımı listeye ekler; kullanıcı sonradan inceleyebilir."""
        entry = {
            "id": f"hand-{uuid.uuid4().hex[:8]}",
            "raised_at": datetime.now(timezone.utc).isoformat(),
            "reviewed": False,
            "note": note,
            "run_id": step_info.get("run_id"),
            "order": step_info.get("order"),
            "issue_id": step_info.get("issue_id"),
            "title": step_info.get("title"),
            "agent_id": step_info.get("agent_id"),
            "agent_name": step_info.get("agent_name"),
            "action": step_info.get("action"),
            "summary": step_info.get("summary"),
            "critical": bool(step_info.get("critical")),
            "step_info": step_info,
        }
        self.raised_hands.insert(0, entry)
        self.raised_hands = self.raised_hands[:100]
        self.mark_dirty()
        await self.broadcast({"type": "HAND_RAISED", "hand": entry, "raised_hands": self.raised_hands})
        return entry

    async def resolve_hand(self, hand_id: str, reviewed: bool = True) -> Optional[Dict[str, Any]]:
        for h in self.raised_hands:
            if h.get("id") == hand_id:
                h["reviewed"] = reviewed
                h["reviewed_at"] = datetime.now(timezone.utc).isoformat() if reviewed else None
                self.mark_dirty()
                await self.broadcast({"type": "HAND_RAISED", "hand": h, "raised_hands": self.raised_hands})
                return h
        return None

    async def send_cross_project_message(self, target_project_id: str, from_agent: str, to_agent: str, message: str,
                                         from_project: Optional[str] = None) -> Dict[str, Any]:
        """
        Bir projedeki ekipten başka bir projedeki ekibe mesaj (örn. Web ekibi ↔ Mobil ekibi).
        Hedef aktif projeyse canlı olay olarak kaydedilir; değilse hedef projenin olay listesine eklenir.
        """
        source = from_project or self.active_project_id
        if target_project_id not in self.projects:
            raise ValueError(tx("Hedef proje bulunamadı: {pid}", pid=target_project_id))
        payload = {"message": message, "from_project": source, "to_project": target_project_id}
        if target_project_id == self.active_project_id:
            event = await self.record_event(
                trace_id=f"xproj-{uuid.uuid4().hex[:8]}", from_agent=from_agent, to_agent=to_agent,
                action="CROSS_PROJECT_MESSAGE", status="SUCCESS", payload=payload,
                friendly_dialogue=message[:160], from_project=source, to_project=target_project_id,
            )
        else:
            proj = self.projects[target_project_id]
            proj.setdefault("events", [])
            seq = len(proj["events"]) + 1
            event = {
                "id": f"evt-x{seq:06d}",
                "type": "AGENT_INTERACTION",
                "trace_id": f"xproj-{uuid.uuid4().hex[:8]}",
                "from_agent": from_agent.upper(), "to_agent": to_agent.upper(),
                "action": "CROSS_PROJECT_MESSAGE", "status": "SUCCESS", "payload": payload,
                "current_file": None, "tokens_used": 0,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "friendly_dialogue": message[:160], "thinking": None, "what_doing": None, "what_next": None,
                "from_project": source, "to_project": target_project_id,
            }
            proj["events"].append(event)
            ppath = proj.get("path")
            if ppath and os.path.isdir(ppath):
                append_event(ppath, event)
            self.mark_dirty()
        await self.broadcast({"type": "CROSS_PROJECT_MESSAGE", "event": event, "target_project_id": target_project_id})
        return event

    async def mark_client_seen(self, name: str, version: str = ""):
        """MCP istemcisinin (Claude Desktop, Antigravity...) görüldüğünü kaydeder ve yayınlar."""
        now = datetime.now(timezone.utc).isoformat()
        entry = self.connected_clients.get(name) or {"name": name, "first_seen": now, "calls": 0}
        entry.update({"version": version or entry.get("version", ""), "last_seen": now, "calls": entry.get("calls", 0) + 1})
        self.connected_clients[name] = entry
        await self.broadcast({"type": "MCP_CLIENT_SEEN", "client": entry, "clients": list(self.connected_clients.values())})

    async def broadcast_thinking(self, run_id: str, agent_id: str, text: str, what_doing: str = "", what_next: str = "",
                                 order: Optional[int] = None):
        """İstemcinin ara düşünce metnini canlı akışa ve ajan kartına yansıtır (kalıcı olay üretmez)."""
        agent_id = agent_id.upper()
        if agent_id in self.agents:
            a = self.agents[agent_id]
            a["current_thinking"] = text
            if what_doing:
                a["current_what_doing"] = what_doing
            a["status"] = "WORKING"
            a["last_seen"] = datetime.now(timezone.utc).isoformat()
        await self.broadcast({
            "type": "AGENT_THINKING_DELTA",
            "run_id": run_id,
            "agent_id": agent_id,
            "order": order,
            "text": text,
            "what_doing": what_doing,
            "what_next": what_next,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    def get_snapshot(self) -> Dict[str, Any]:
        return {
            "load_error": getattr(self, "load_error", None),
            "active_project": self.project_summary(),
            "projects": self.get_projects_summary(),
            "agents": list(self.agents.values()),
            "tasks": list(self.tasks.values()),
            "jira_issues": list(self.jira_issues.values()),
            "uploaded_specs": self.uploaded_specs,
            "playwright_reports": self.playwright_reports,
            "test_profiles": self.public_profiles(),
            "events": list(self.events),
            "stats": self.stats,
            "pending_step_approval": self.pending_step_approval,
            "step_by_step_mode": self.step_by_step_mode,
            "active_run_id": self.active_run_id,
            "active_run": self.active_run_summary(),
            "runs": self.recent_runs(),
            "settings": self.settings,
            "connected_clients": list(self.connected_clients.values()),
            "raised_hands": self.raised_hands
        }


# Global telemetri havuz örneği
hub = TelemetryHub()
