"""
Görsel MCP Sunucusu Yapılandırması.
Genişletilmiş Yazılım Şirketi Ajan Takımı.
"""
import os

from .i18n import N_, translate as tx

SERVER_HOST = os.getenv("OBSERVER_HOST", "127.0.0.1")
SERVER_PORT = int(os.getenv("OBSERVER_PORT", "8099"))
# Yalnızca yerel geliştirme kökenleri; "*" + allow_credentials birlikte kullanılamaz (tarayıcı reddeder, güvenlik açığı)
_PORT = os.getenv("OBSERVER_PORT", "8099")
CORS_ORIGINS = sorted({
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:5174",
    "http://127.0.0.1:5174",
    f"http://localhost:{_PORT}",
    f"http://127.0.0.1:{_PORT}",
    "http://localhost:8099",
    "http://127.0.0.1:8099",
} | {o.strip() for o in os.getenv("OBSERVER_EXTRA_ORIGINS", "").split(",") if o.strip()})

# Bellekte tutulacak maksimum olay sayısı
MAX_HISTORY_EVENTS = 500

DEFAULT_AGENTS = [
    {
        "id": "PM",
        "name": "Product Manager",
        "role": "PM",
        "status": "IDLE",
        "active_file": "docs/prd/auth_spec.md",
        "description": N_("Müşteri görüşmeleri, gereksinim analizi ve PRD dokümantasyonu")
    },
    {
        "id": "ARCHITECT",
        "name": "Tech Lead / Architect",
        "role": "ARCHITECT",
        "status": "IDLE",
        "active_file": "docs/arch/contracts.json",
        "description": N_("Sistem mimarisi, OpenAPI 3.0 sözleşmeleri ve modül sınırları")
    },
    {
        "id": "BACKEND_DEV",
        "name": "Senior Backend Developer",
        "role": "BACKEND_DEV",
        "status": "IDLE",
        "active_file": "src/api/service.py",
        "description": N_("FastAPI REST servisleri, JWT auth ve veritabanı iş mantığı")
    },
    {
        "id": "FRONTEND_DEV",
        "name": "Senior Frontend Developer",
        "role": "FRONTEND_DEV",
        "status": "IDLE",
        "active_file": "frontend/src/App.tsx",
        "description": N_("React responsive kullanıcı arayüzü, formlar ve API client entegrasyonu")
    },
    {
        "id": "DESIGNER",
        "name": "UI/UX Designer",
        "role": "DESIGNER",
        "status": "IDLE",
        "active_file": "docs/design/design-system.html",
        "description": N_("Tasarım sistemi (renk, tipografi, bileşenler) ve ilk ekranların HTML mockup'ları; frontend onaylı tasarıma uyar")
    },
    {
        "id": "QA",
        "name": "Lead QA Engineer",
        "role": "QA",
        "status": "IDLE",
        "active_file": "tests/test_auth.py",
        "description": N_("Birim testler, regresyon kontrolleri ve hata (bug) raporlama")
    },
    {
        "id": "E2E_TESTER",
        "name": "Playwright E2E Tester",
        "role": "E2E_TESTER",
        "status": "IDLE",
        "active_file": "tests/e2e/login.spec.ts",
        "description": N_("Gerçek Chromium tarayıcısı açarak canlı login, form doldurma ve UI ekran görüntüsü testi")
    },
    {
        "id": "DEVOPS",
        "name": "DevOps & SRE",
        "role": "DEVOPS",
        "status": "IDLE",
        "active_file": "deploy/docker-compose.yml",
        "description": N_("Dockerfile, docker-compose, staging dağıtımı ve sağlık kontrolü")
    },
    {
        "id": "PO",
        "name": "Product Owner",
        "role": "PO",
        "status": "IDLE",
        "active_file": "docs/uat/acceptance_criteria.md",
        "description": N_("Ürün kabulü (UAT), iş değeri ve kullanıcı beklentisi doğrulaması")
    },
    {
        "id": "REPORTER",
        "name": "Project Reporter",
        "role": "REPORTER",
        "status": "IDLE",
        "active_file": "docs/reports/status_report.md",
        "description": N_("Yönetici durum özetleri, token ve sprint metrikleri raporlaması")
    },
    {
        "id": "DOCUMENTOR",
        "name": "Documentation Lead",
        "role": "DOCUMENTOR",
        "status": "IDLE",
        "active_file": "docs/manuals/user_guide.md",
        "description": N_("Kullanıcı kılavuzları, kurulum rehberleri ve API referans dokümantasyonu")
    },
    {
        "id": "SCM",
        "name": "SCM Manager",
        "role": "SCM",
        "status": "IDLE",
        "active_file": "CHANGELOG.md",
        "description": N_("Git versiyonlama, branching stratejisi ve merge çakışma çözümü")
    },
    {
        "id": "SCRUM_MASTER",
        "name": "Scrum Master",
        "role": "SCRUM_MASTER",
        "status": "IDLE",
        "active_file": "FS-docs/sprints/sprint-1.json",
        "description": N_("Sprint planı, kapasite, taahhüt, taşıma ve sprint kapanışı")
    }
]


# Varsayılan ama isteğe bağlı çekirdek ajanlar: her projede hazır gelir (etkin), projeden kaldırılabilir/pasifleştirilebilir ve "varsayılanları geri yükle" ile döner.
# Özel ajan mekanizmasıyla çalışırlar: `role_base` temel rolün istemini/ipucunu verir, `focus` sözcükleri rolü belirtilmemiş görevi bu ajana yönlendirir.
OPTIONAL_AGENTS = [
    {
        "id": "MOBILE_DESIGNER", "name": "Mobile UI/UX Designer", "role": "Mobile Designer", "role_base": "DESIGNER", "status": "IDLE", "active": True, "default_optional": True,
        "description": N_("Mobil (iOS/Android) tasarım sistemi ve ekran mockup'ları: dokunma hedefleri, gezinme kalıpları, küçük ekran düzeni"),
        "capabilities": ["DESIGN", "IMPROVEMENT"],
        "focus": ["mobil tasarım", "mobile design", "mobil mockup", "mobil ekran tasarım", "ios tasarım", "android tasarım"],
    },
    {
        "id": "SECURITY_REVIEWER", "name": "Security Engineer", "role": "Security Reviewer", "role_base": "QA", "status": "IDLE", "active": True, "default_optional": True,
        "description": N_("Güvenlik incelemesi ve testi: OWASP zafiyetleri, yetkilendirme, gizli bilgi, bağımlılık riskleri; bulguları hata olarak bildirir"),
        "capabilities": ["SECURITY_TEST", "BUG", "REFACTOR"],
        "focus": ["owasp", "zafiyet", "güvenlik açığı", "güvenlik testi", "penetrasyon", "tehdit modeli", "security review"],
    },
    {
        "id": "SEO_OPTIMIZER", "name": "SEO Optimizer", "role": "SEO Optimizer", "role_base": "FRONTEND_DEV", "status": "IDLE", "active": True, "default_optional": True,
        "description": N_("Teknik SEO ve web performansı: meta etiketler, sitemap, yapılandırılmış veri, Core Web Vitals"),
        "capabilities": ["IMPROVEMENT", "FEATURE"],
        "focus": ["seo", "arama motoru", "meta etiket", "sitemap", "open graph", "schema.org", "robots.txt"],
    },
    {
        "id": "CODE_REVIEWER", "name": "Code Reviewer", "role": "Code Reviewer", "role_base": "ARCHITECT", "status": "IDLE", "active": True, "default_optional": True,
        "description": N_("Kod inceleme ve kalite: okunabilirlik, doğruluk, performans, teknik borç; küçük, gerekçeli iyileştirme görevleri açar"),
        "capabilities": ["REFACTOR", "IMPROVEMENT"],
        "focus": ["kod incelemesi", "code review", "kod kalitesi", "teknik borç"],
    },
]


def localized_description(description: str, lang=None) -> str:
    """Varsayılan (çekirdek/isteğe bağlı) ajan açıklamasını verilen (ya da aktif) proje diline çevirir; katalogda olmayan metin olduğu gibi döner."""
    return tx(description, lang=lang)


def default_agent_descriptions() -> dict:
    """{ajan kimliği: Türkçe kaynak açıklama} (çekirdek ve isteğe bağlı varsayılan ajanlar): dil değişiminde 'hâlâ varsayılan mı' denetimi için."""
    return {a["id"]: a["description"] for a in list(DEFAULT_AGENTS) + list(OPTIONAL_AGENTS)}
