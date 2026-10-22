"""Teknoloji / mimari kararları kapısı.

Pipeline, tasarım (adım 2) ve kod üretimi adımlarına geçmeden önce kullanıcıya teknoloji seçimlerini sorar:
dil/çatı, veritabanı, istemci, kimlik doğrulama, barındırma, gerçek zamanlı katman, test araçları + serbest notlar.
PM adımı (LLM) şartnameye özgü açık soruları `payload.decisions_needed` ile ekleyebilir. Cevaplar projenin
`.fs-workspace/settings.json` dosyasında (`tech_decisions`) saklanır ve sonraki tüm adımların bağlamına enjekte edilir.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .i18n import translate as tx, N_

DEFAULT_TECH_QUESTIONS: List[Dict[str, Any]] = [
    {"id": "backend", "question": N_("Backend dili ve çatısı"),
     "options": ["Python / FastAPI", "Node.js / NestJS", "PHP 8 / Symfony", "Go / Gin", ".NET 8 / ASP.NET Core", "Java / Spring Boot"],
     "recommended": "Python / FastAPI", "why": N_("Şirketin geliştirme ajanları Python/FastAPI iskeletini en güvenilir üretir; ekip uzmanlığınız farklıysa onu seçin.")},
    {"id": "database", "question": N_("Veritabanı"),
     "options": ["PostgreSQL (+PostGIS)", "MySQL / MariaDB", "SQL Server", "MongoDB", "SQLite (development only)"],
     "recommended": "PostgreSQL (+PostGIS)", "why": N_("Konum sorguları ve ilişkisel model için en uygun, yönetilen seçenekleri ucuz.")},
    {"id": "client", "question": N_("İstemci / arayüz"),
     "options": ["React Native (iOS + Android)", "Flutter", "React (web SPA)", "Next.js (web)", "Native Swift + Kotlin", "Web + mobile (both)"],
     "recommended": "React Native (iOS + Android)", "why": N_("Tek kod tabanıyla iki platform; JS/TS bilgisi doğrudan taşınır.")},
    {"id": "auth", "question": N_("Kimlik doğrulama"),
     "options": ["Own JWT + OTP", "OAuth2 / OIDC provider (Auth0, Keycloak)", "Firebase Auth", "Supabase Auth"],
     "recommended": "Own JWT + OTP", "why": N_("Telefon/e-posta OTP akışı üzerinde tam kontrol; dış bağımlılık yok.")},
    {"id": "hosting", "question": N_("Barındırma / dağıtım"),
     "options": ["Docker + single VPS", "Kubernetes", "PaaS (Render, Fly.io, Railway)", "Serverless (Lambda, Cloud Run)", "On-premises"],
     "recommended": "Docker + single VPS", "why": N_("Küçük ekip ve orta ölçek için en düşük işletme yükü.")},
    {"id": "realtime", "question": N_("Gerçek zamanlı katman (sohbet, bildirim)"),
     "options": ["WebSocket (self-hosted)", "Managed service (Pusher, Ably, Centrifugo)", "Not needed"],
     "recommended": "WebSocket (self-hosted)", "why": N_("Modüler monolitte aynı süreçte çalışır; ölçek gerektiğinde yönetilen servise geçilebilir.")},
    {"id": "testing", "question": N_("Test araçları"),
     "options": ["pytest + Playwright", "Jest + Playwright", "PHPUnit + Playwright", "Go test + Playwright", "xUnit + Playwright"],
     "recommended": "pytest + Playwright", "why": N_("Backend seçimiyle uyumlu birim testleri + gerçek tarayıcı E2E.")},
]

FREE_TEXT_ID = "notes"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_question(q: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """LLM'den gelen serbest biçimli soruyu şemaya oturtur; geçersizse None."""
    if not isinstance(q, dict):
        return None
    qid = str(q.get("id") or q.get("key") or "").strip().lower().replace(" ", "_")
    question = str(q.get("question") or q.get("title") or "").strip()
    if not qid or not question:
        return None
    options = [str(o).strip() for o in (q.get("options") or []) if str(o).strip()]
    rec = str(q.get("recommended") or "").strip()
    if rec and rec not in options:
        options.append(rec)
    return {"id": qid[:40], "question": question[:200], "options": options[:8], "recommended": rec or (options[0] if options else ""),
            "why": str(q.get("why") or q.get("reason") or "").strip()[:400], "source": "spec"}


def merge_questions(spec_questions: Optional[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    """Varsayılan soru seti + şartnameye özgü sorular (aynı id varsa şartnamedeki kazanır)."""
    merged: Dict[str, Dict[str, Any]] = {q["id"]: {**q, "question": tx(q["question"]), "why": tx(q["why"]), "source": "default"} for q in DEFAULT_TECH_QUESTIONS}
    for raw in spec_questions or []:
        q = normalize_question(raw)
        if q:
            base = merged.get(q["id"], {})
            merged[q["id"]] = {**base, **{k: v for k, v in q.items() if v}}
    return list(merged.values())


def auto_answers(questions: List[Dict[str, Any]]) -> Dict[str, str]:
    return {q["id"]: q.get("recommended") or (q.get("options") or [""])[0] for q in questions}


def make_decisions(questions: List[Dict[str, Any]], answers: Dict[str, Any], notes: str = "", source: str = "user") -> Dict[str, Any]:
    clean: Dict[str, str] = {}
    for q in questions:
        val = answers.get(q["id"])
        if val is None or str(val).strip() == "":
            continue
        clean[q["id"]] = str(val).strip()[:200]
    return {"answers": clean, "notes": str(notes or "").strip()[:2000], "source": source, "answered_at": _now()}


def is_answered(decisions: Optional[Dict[str, Any]]) -> bool:
    return bool(decisions and isinstance(decisions.get("answers"), dict) and decisions["answers"])


def decisions_context(questions: List[Dict[str, Any]], decisions: Optional[Dict[str, Any]]) -> str:
    """Adım promptlarına eklenecek Markdown bölümü."""
    if not is_answered(decisions):
        return ""
    label = {q["id"]: q["question"] for q in questions}
    lines = [tx("## Teknoloji ve mimari kararları (kullanıcı onaylı — bunlara UY, alternatif önerme)")]
    for qid, val in decisions["answers"].items():
        lines.append(f"- {label.get(qid, qid)}: **{val}**")
    if decisions.get("notes"):
        lines.append(tx("- Ek notlar / kısıtlar: {notes}", notes=decisions['notes']))
    src = {"user": tx("yönetici onayı"), "dry_run": tx("deneme bayrağıyla simüle edilen onay")}.get(decisions.get("source"), tx("önerilen değerler otomatik uygulandı"))
    lines.append(tx("_(Kaynak: {src}, {at})_", src=src, at=decisions.get('answered_at', '')[:19]))
    return "\n".join(lines)
