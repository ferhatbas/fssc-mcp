"""
Çoklu Ajan Şirket Simülasyon Senaryosu (Orchestrator Demo Runner).
PM -> Architect -> Developer -> QA (Bug Tespiti) -> Developer (Düzeltme) -> QA (Onay) -> DevOps (Dağıtım)
uçtan uca yaşam döngüsünü görsel MCP sunucusuna iletir.
"""

import argparse
import asyncio
import json
import sys
import time
import urllib.request
import urllib.error

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

API_BASE = "http://127.0.0.1:8099/api"

SIMULATION_STEPS = [
    {
        "step_name": "1. Product Manager Gereksinimleri Çıkardı",
        "task_state": {
            "task_id": "FEAT-101",
            "new_state": "ARCHITECTURE",
            "title": "JWT Tabanlı Kimlik Doğrulama Servisi",
            "assignee": "ARCHITECT",
            "priority": "P0",
            "details": "PRD tamamlandı. User story ve kabul kriterleri mimariye sevk edildi."
        },
        "event": {
            "trace_id": "trace-req-101",
            "from_agent": "PM",
            "to_agent": "ARCHITECT",
            "action": "TASK_DISPATCH",
            "status": "SUCCESS",
            "current_file": "docs/prd/auth_service_v1.md",
            "tokens_used": 140,
            "payload": {
                "task_id": "FEAT-101",
                "title": "JWT Auth Microservice",
                "acceptance_criteria": [
                    "JWT Access/Refresh token desteği",
                    "3 hatalı denemede 5 dakika rate limiting",
                    "Bcrypt şifreleme"
                ]
            }
        },
        "metric": {
            "agent_name": "PM",
            "tokens_in": 350,
            "tokens_out": 220,
            "active_file": "docs/prd/auth_service_v1.md",
            "latency_ms": 120.5,
            "status": "COMPLETED"
        },
        "delay": 2.5
    },
    {
        "step_name": "2. Architect / Tech Lead API ve Veritabanı Şemasını Belirledi",
        "task_state": {
            "task_id": "FEAT-101",
            "new_state": "DEVELOPMENT",
            "title": "JWT Tabanlı Kimlik Doğrulama Servisi",
            "assignee": "DEVELOPER",
            "priority": "P0",
            "details": "OpenAPI kontratları (/login, /refresh) ve Clean Architecture yapısı hazırlandı."
        },
        "event": {
            "trace_id": "trace-req-101",
            "from_agent": "ARCHITECT",
            "to_agent": "DEVELOPER",
            "action": "TASK_DISPATCH",
            "status": "SUCCESS",
            "current_file": "docs/arch/openapi_auth.json",
            "tokens_used": 210,
            "payload": {
                "tech_stack": "FastAPI + SQLAlchemy + PostgreSQL",
                "endpoints": ["POST /api/v1/login", "POST /api/v1/refresh"],
                "target_branch": "feature/auth-core"
            }
        },
        "metric": {
            "agent_name": "ARCHITECT",
            "tokens_in": 420,
            "tokens_out": 380,
            "active_file": "docs/arch/openapi_auth.json",
            "latency_ms": 185.0,
            "status": "COMPLETED"
        },
        "delay": 2.5
    },
    {
        "step_name": "3. Developer Kodu ve Unit Testleri Yazıp QA'e Teslim Etti",
        "task_state": {
            "task_id": "FEAT-101",
            "new_state": "QA_TESTING",
            "title": "JWT Tabanlı Kimlik Doğrulama Servisi",
            "assignee": "QA",
            "priority": "P0",
            "details": "FastAPI router, JWT middleware ve 8 birim test tamamlandı. QA testine sevk edildi."
        },
        "event": {
            "trace_id": "trace-req-101",
            "from_agent": "DEVELOPER",
            "to_agent": "QA",
            "action": "SUBMIT_CODE",
            "status": "SUCCESS",
            "current_file": "src/auth/service.py",
            "tokens_used": 450,
            "payload": {
                "commit_hash": "c8f92a1",
                "files_changed": ["src/auth/service.py", "tests/test_auth.py"],
                "unit_test_passed": "8/8"
            }
        },
        "metric": {
            "agent_name": "DEVELOPER",
            "tokens_in": 890,
            "tokens_out": 620,
            "active_file": "src/auth/service.py",
            "latency_ms": 310.2,
            "status": "COMPLETED"
        },
        "delay": 2.5
    },
    {
        "step_name": "4. QA Testi Koştu ve KRİTİK HATA Buldu (Developer'a Geri Dönüş Döngüsü)",
        "task_state": {
            "task_id": "FEAT-101",
            "new_state": "DEVELOPMENT",
            "title": "JWT Tabanlı Kimlik Doğrulama Servisi",
            "assignee": "DEVELOPER",
            "priority": "P0",
            "details": "HATA: Token süresi dolduğunda 401 yerine HTTP 500 dönüyor. Developer'a iade edildi!"
        },
        "event": {
            "trace_id": "trace-req-101",
            "from_agent": "QA",
            "to_agent": "DEVELOPER",
            "action": "REPORT_BUG",
            "status": "FAILED",
            "current_file": "tests/e2e/test_jwt_edge_cases.py",
            "tokens_used": 280,
            "payload": {
                "bug_id": "BUG-01",
                "severity": "CRITICAL",
                "title": "ExpiredSignatureError unhandled - HTTP 500 instead of 401",
                "expected": "HTTP 401 Unauthorized with {'error': 'TOKEN_EXPIRED'}",
                "actual": "HTTP 500 Internal Server Error",
                "traceback": "jwt.exceptions.ExpiredSignatureError in middleware.py:42"
            }
        },
        "metric": {
            "agent_name": "QA",
            "tokens_in": 650,
            "tokens_out": 310,
            "active_file": "tests/e2e/test_jwt_edge_cases.py",
            "latency_ms": 220.0,
            "status": "BUG_FIX"
        },
        "delay": 3.0
    },
    {
        "step_name": "5. Developer Hatayı Çözdü ve Bugfix Patch'ini QA'e Sundu",
        "task_state": {
            "task_id": "FEAT-101",
            "new_state": "QA_TESTING",
            "title": "JWT Tabanlı Kimlik Doğrulama Servisi",
            "assignee": "QA",
            "priority": "P0",
            "details": "ExpiredSignatureError yakalandı, 401 handler eklendi. Test için QA'e iade edildi."
        },
        "event": {
            "trace_id": "trace-req-101",
            "from_agent": "DEVELOPER",
            "to_agent": "QA",
            "action": "SUBMIT_CODE",
            "status": "SUCCESS",
            "current_file": "src/auth/middleware.py",
            "tokens_used": 290,
            "payload": {
                "is_bugfix": True,
                "fixed_bug_id": "BUG-01",
                "solution": "FastAPI exception handler içine ExpiredSignatureError eklendi ve test edildi."
            }
        },
        "metric": {
            "agent_name": "DEVELOPER",
            "tokens_in": 410,
            "tokens_out": 290,
            "active_file": "src/auth/middleware.py",
            "latency_ms": 195.4,
            "status": "COMPLETED"
        },
        "delay": 2.5
    },
    {
        "step_name": "6. QA Testleri Tekrar Koştu ve Onayladı (APPROVE_BUILD)",
        "task_state": {
            "task_id": "FEAT-101",
            "new_state": "DEVOPS_DEPLOY",
            "title": "JWT Tabanlı Kimlik Doğrulama Servisi",
            "assignee": "DEVOPS",
            "priority": "P0",
            "details": "Tüm 24 entegrasyon ve edge-case testleri geçti. DevOps dağıtımına sevk edildi."
        },
        "event": {
            "trace_id": "trace-req-101",
            "from_agent": "QA",
            "to_agent": "DEVOPS",
            "action": "APPROVE_BUILD",
            "status": "SUCCESS",
            "current_file": "reports/qa/test_report_pass.json",
            "tokens_used": 190,
            "payload": {
                "total_tests": 24,
                "passed": 24,
                "failed": 0,
                "verdict": "PRODUCTION_READY"
            }
        },
        "metric": {
            "agent_name": "QA",
            "tokens_in": 520,
            "tokens_out": 190,
            "active_file": "reports/qa/test_report_pass.json",
            "latency_ms": 140.0,
            "status": "COMPLETED"
        },
        "delay": 2.5
    },
    {
        "step_name": "7. DevOps Dağıtımı Yaptı ve Canlı Yayını Onayladı (DEPLOY_CONFIRM)",
        "task_state": {
            "task_id": "FEAT-101",
            "new_state": "RELEASED",
            "title": "JWT Tabanlı Kimlik Doğrulama Servisi",
            "assignee": "PM",
            "priority": "P0",
            "details": "Docker imajı build edildi, staging ortamına deploy edildi. Healthcheck: 200 OK."
        },
        "event": {
            "trace_id": "trace-req-101",
            "from_agent": "DEVOPS",
            "to_agent": "PM",
            "action": "DEPLOY_CONFIRM",
            "status": "SUCCESS",
            "current_file": "deploy/docker-compose.staging.yml",
            "tokens_used": 180,
            "payload": {
                "image": "registry.company.internal/auth-svc:v1.0.0",
                "healthcheck": "PASS (200 OK, latency: 18ms)",
                "environment": "staging",
                "status": "LIVE"
            }
        },
        "metric": {
            "agent_name": "DEVOPS",
            "tokens_in": 380,
            "tokens_out": 180,
            "active_file": "deploy/docker-compose.staging.yml",
            "latency_ms": 160.0,
            "status": "COMPLETED"
        },
        "delay": 1.0
    }
]


def post_http(endpoint: str, data: dict):
    """Standart kütüphane ile JSON POST isteği atar."""
    url = f"{API_BASE}/{endpoint}"
    req = urllib.request.Request(
        url,
        data=json.dumps(data).encode("utf-8"),
        headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


async def run_simulation():
    print("=" * 65)
    print("🚀 Çoklu Ajan Şirket Simülasyon Koşucusu Başlatılıyor")
    print(f"📡 Hedef API: {API_BASE}")
    print("=" * 65 + "\n")

    # 1. Önceki durumu sıfırla
    try:
        post_http("reset", {})
        print("🔄 Telemetri panosu sıfırlandı.\n")
    except Exception as e:
        print(f"⚠️ Sunucuya bağlanılamadı ({e}).")
        print("👉 Lütfen önce sunucuyu başlatın: python -m server.main --mode web")
        return

    # 2. Adımları sırayla işlet
    for idx, step in enumerate(SIMULATION_STEPS, 1):
        print(f"[{idx}/{len(SIMULATION_STEPS)}] {step['step_name']}")
        
        # Görev durumu güncelle
        post_http("tasks", step["task_state"])
        print(f"   📋 Kanban Güncellendi -> {step['task_state']['new_state']} (Sorumlu: {step['task_state']['assignee']})")

        # Olay kaydı
        post_http("events", step["event"])
        status_symbol = "❌ [BUG DETECTED]" if step["event"]["status"] == "FAILED" else "✅ [OK]"
        print(f"   💬 Mesaj: {step['event']['from_agent']} ➔ {step['event']['to_agent']} ({step['event']['action']}) {status_symbol}")

        # Gecikme
        await asyncio.sleep(step["delay"])

    print("\n" + "=" * 65)
    print("🎉 Simülasyon başarıyla tamamlandı! Dağıtım yayında.")
    print("📊 Dashboard: http://localhost:5173 veya http://localhost:8099")
    print("=" * 65)


if __name__ == "__main__":
    asyncio.run(run_simulation())
