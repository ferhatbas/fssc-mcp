"""Teknoloji gereksinimleri (F2, belge §3.2, §3.3, §7.4, §10.7).

Notlardan teknoloji ifadeleri çıkarılır (kural tabanlı; LLM'siz), her kategori için `BELİRTİLMİŞ` / `EKSİK` / `ÇELİŞKİLİ`
durumu belirlenir ve `<docs>/TECH_REQUIREMENTS.md` üretilir. Tüm kalemler `ONAYLANDI` olmadan teknoloji kapısı kapanmaz;
kapı hiçbir onay modunda atlanmaz. Kaynak kayıt `settings.tech_requirements` alanıdır.

Bu modül saf mantıktır (hub'a yalnızca ince bir yardımcıyla dokunur); durum geçişleri `TelemetryHub` içindedir.
"""
from __future__ import annotations

import json
import os
import re
import tomllib
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from . import i18n as I18N
from .decisions import DEFAULT_TECH_QUESTIONS
from .i18n import translate as tx, N_

BELIRTILMIS, EKSIK, CELISKILI = "BELİRTİLMİŞ", "EKSİK", "ÇELİŞKİLİ"
ONAY_BEKLIYOR, ONAYLANDI = "ONAY_BEKLİYOR", "ONAYLANDI"

# ---------------------------------------------------------------------------
# Çıkarma tabloları: kategori → [(aile, etiket, özgül_mü, regex)]. Farklı aileler birbiriyle çelişir.
# ---------------------------------------------------------------------------
_E = re.IGNORECASE
_PATTERNS: Dict[str, List[Tuple[str, str, bool, "re.Pattern[str]"]]] = {
    "backend": [
        ("python", "Python / FastAPI", True, re.compile(r"\bfastapi\b", _E)),
        ("python", "Python / Django", True, re.compile(r"\bdjango\b", _E)),
        ("python", "Python / Flask", True, re.compile(r"\bflask\b", _E)),
        ("python", "Python", False, re.compile(r"\bpython\b", _E)),
        ("node", "Node.js / NestJS", True, re.compile(r"\bnest\.?js\b", _E)),
        ("node", "Node.js / Express", True, re.compile(r"\bexpress(?:\.js)?\b", _E)),
        ("node", "Node.js", False, re.compile(r"\bnode(?:\.js|js)?\b", _E)),
        ("php", "PHP 8 / Symfony", True, re.compile(r"\bsymfony\b", _E)),
        ("php", "PHP / Laravel", True, re.compile(r"\blaravel\b", _E)),
        ("php", "PHP", False, re.compile(r"\bphp\b", _E)),
        ("go", "Go / Gin", True, re.compile(r"\bgin\b(?=.{0,20}\b(?:go|golang)\b)|\b(?:go|golang)\b.{0,20}\bgin\b", _E)),
        ("go", "Go", False, re.compile(r"\bgolang\b|\bgo (?:ile|dili|backend)\b", _E)),
        ("java", "Java / Spring Boot", True, re.compile(r"\bspring(?: boot)?\b", _E)),
        ("java", "Java", False, re.compile(r"\bjava\b(?!script)", _E)),
        ("dotnet", ".NET 8 / ASP.NET Core", True, re.compile(r"\basp\.?net\b", _E)),
        ("dotnet", ".NET", False, re.compile(r"(?<![\w])\.net\b|\bc#", _E)),
    ],
    "database": [
        ("postgres", "PostgreSQL", False, re.compile(r"\bpostgres(?:ql)?\b", _E)),
        ("mysql", "MySQL / MariaDB", False, re.compile(r"\bmysql\b|\bmariadb\b", _E)),
        ("mssql", "SQL Server", False, re.compile(r"\bsql server\b|\bmssql\b", _E)),
        ("mongo", "MongoDB", False, re.compile(r"\bmongo(?:db)?\b", _E)),
        ("sqlite", "SQLite", False, re.compile(r"\bsqlite\b", _E)),
    ],
    "client": [
        ("rn", "React Native", False, re.compile(r"\breact native\b", _E)),
        ("flutter", "Flutter", False, re.compile(r"\bflutter\b", _E)),
        ("nextjs", "Next.js (web)", False, re.compile(r"\bnext\.?js\b", _E)),
        ("react", "React (web SPA)", False, re.compile(r"\breact\b(?! native)", _E)),
        ("vue", "Vue", False, re.compile(r"\bvue(?:\.js)?\b", _E)),
        ("native", "Native Swift + Kotlin", False, re.compile(r"\bswift\b|\bkotlin\b", _E)),
    ],
    "auth": [
        ("token", "OAuth2", False, re.compile(r"\boauth2?\b|\boidc\b", _E)),
        ("token", "JWT", False, re.compile(r"\bjwt\b", _E)),
        ("token", "OTP", False, re.compile(r"\botp\b", _E)),
        ("ldap", "LDAP", False, re.compile(r"\bldap\b|\bactive directory\b", _E)),
        ("saml", "SAML", False, re.compile(r"\bsaml\b", _E)),
        ("firebase", "Firebase Auth", False, re.compile(r"\bfirebase\b", _E)),
        ("supabase", "Supabase Auth", False, re.compile(r"\bsupabase\b", _E)),
    ],
    "hosting": [
        ("docker", "Docker", False, re.compile(r"\bdocker\b", _E)),
        ("k8s", "Kubernetes", False, re.compile(r"\bkubernetes\b|\bk8s\b", _E)),
        ("paas", "PaaS (Render, Fly.io, Railway)", False, re.compile(r"\brender\.com\b|\bfly\.io\b|\brailway\b|\bheroku\b", _E)),
        ("serverless", "Serverless", False, re.compile(r"\bserverless\b|\blambda\b|\bcloud run\b", _E)),
        ("onprem", "On-premises", False, re.compile(r"\bon-?prem(?:ise)?\b|\byerinde\b", _E)),
    ],
    "realtime": [
        ("ws", "WebSocket", False, re.compile(r"\bweb ?sockets?\b", _E)),
        ("managed", "Managed service (Pusher, Ably)", False, re.compile(r"\bpusher\b|\bably\b|\bcentrifugo\b", _E)),
        ("sse", "Server-Sent Events", False, re.compile(r"\bserver-sent events\b|\bsse\b", _E)),
    ],
    "testing": [
        ("pytest", "pytest", False, re.compile(r"\bpytest\b", _E)),
        ("jest", "Jest", False, re.compile(r"\bjest\b", _E)),
        ("phpunit", "PHPUnit", False, re.compile(r"\bphpunit\b", _E)),
        ("xunit", "xUnit", False, re.compile(r"\bxunit\b", _E)),
        ("pw", "Playwright", False, re.compile(r"\bplaywright\b", _E)),
    ],
}
# Aynı kategoride birlikte kullanılabilen aileler (çelişki sayılmaz)
_COMPATIBLE = {"testing": True}

# Önerilen alternatiflerin artı/eksileri (karar 16: tek öneri değil, 2-3 alternatif)
_NOTES: Dict[str, Tuple[str, str]] = {
    "Python / FastAPI": (N_("Hızlı geliştirme, otomatik OpenAPI, ajanlar için en güvenilir iskelet"), N_("Çok çekirdekli CPU işinde sınırlı; async disiplini ister")),
    "Node.js / NestJS": (N_("TypeScript ile istemciyle tek dil, büyük ekosistem"), N_("Daha fazla kurulum ve boilerplate")),
    "PHP 8 / Symfony": (N_("Olgun çatı, kurumsal hosting kolaylığı"), N_("Ekip PHP bilmiyorsa öğrenme yükü")),
    "PostgreSQL (+PostGIS)": (N_("Güçlü ilişkisel model, konum sorguları, yönetilen seçenekleri ucuz"), N_("Kurulum ve yönetim SQLite'tan ağır")),
    "MySQL / MariaDB": (N_("Yaygın, hosting desteği geniş"), N_("Gelişmiş sorgu ve JSON desteği daha zayıf")),
    "SQL Server": (N_("Kurumsal araç desteği"), N_("Lisans maliyeti, Linux'ta ek yük")),
    "React Native (iOS + Android)": (N_("Tek kod tabanı, iki platform"), N_("Yerel özelliklerde köprü kodu gerekir")),
    "Flutter": (N_("Tek kod tabanı, tutarlı arayüz"), N_("Dart öğrenme yükü")),
    "React (web SPA)": (N_("Basit dağıtım, geniş ekosistem"), N_("Mobil mağaza uygulaması değildir")),
    "Own JWT + OTP": (N_("Tam kontrol, dış bağımlılık yok"), N_("Güvenlik sorumluluğu ekipte")),
    "OAuth2 / OIDC provider (Auth0, Keycloak)": (N_("Hazır, denetlenmiş akışlar"), N_("Dış servis ya da ek altyapı")),
    "Firebase Auth": (N_("Hızlı kurulum, yönetilen"), N_("Satıcıya bağımlılık, veri dışarıda")),
    "Docker + single VPS": (N_("En düşük işletme yükü"), N_("Yatay ölçek elle yapılır")),
    "Kubernetes": (N_("Ölçek ve dayanıklılık"), N_("Küçük ekip için ağır işletme yükü")),
    "PaaS (Render, Fly.io, Railway)": (N_("Dağıtım kolay"), N_("Maliyet büyür, satıcıya bağımlılık")),
    "WebSocket (self-hosted)": (N_("Aynı süreçte çalışır, ek servis yok"), N_("Ölçeklenince yük dengeleme gerekir")),
    "Managed service (Pusher, Ably, Centrifugo)": (N_("Ölçek hazır"), N_("Ücretli, veri dışarıya gider")),
    "Not needed": (N_("Sadelik"), N_("Sohbet/bildirim gerekirse sonradan eklenir")),
    "pytest + Playwright": (N_("Backend seçimiyle uyumlu birim testi + gerçek tarayıcı E2E"), N_("İki araç öğrenme yükü")),
    "Jest + Playwright": (N_("JS/TS projeleriyle uyumlu"), N_("Python backend ile uyumsuz")),
    "PHPUnit + Playwright": (N_("PHP projeleriyle uyumlu"), N_("Python backend ile uyumsuz")),
}


def _note(option: str) -> Tuple[str, str]:
    """Seçeneğin artı/eksi notu (çağrı anında aktif dile çevrilir)."""
    pros, cons = _NOTES.get(option, ("", ""))
    return (tx(pros) if pros else "", tx(cons) if cons else "")


CATEGORY_LABELS = {"backend": N_("Backend dili ve çatısı"), "database": N_("Veritabanı"), "client": N_("İstemci türü / arayüz"),
                   "auth": N_("Kimlik doğrulama"), "hosting": N_("Barındırma / konteyner"), "realtime": N_("Gerçek zamanlı katman"),
                   "testing": N_("Test araç zinciri")}


def dry_run_enabled() -> bool:
    """Deneme bayrağı: yalnızca ortam değişkeniyle ve şablon motoru döngüsünde kullanılır (karar 16)."""
    return os.environ.get("FSSC_DRY_RUN") == "1"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _spec_hash(text: str) -> str:
    import hashlib
    return hashlib.sha1((text or "").encode("utf-8", errors="ignore")).hexdigest()[:12]


def _same_value(a: Any, b: Any) -> bool:
    """'PostgreSQL' ile 'PostgreSQL (+PostGIS)' aynı karar sayılır: sözcük kümelerinden biri diğerinin altkümesi."""
    ta = {t for t in re.split(r"[^a-z0-9.#]+", str(a or "").lower()) if t}
    tb = {t for t in re.split(r"[^a-z0-9.#]+", str(b or "").lower()) if t}
    return bool(ta and tb and (ta <= tb or tb <= ta))


def _quote_around(text: str, start: int, end: int, width: int = 90) -> str:
    left = max(text.rfind("\n", 0, start), text.rfind(".", 0, start)) + 1
    right_candidates = [i for i in (text.find("\n", end), text.find(".", end)) if i != -1]
    right = min(right_candidates) if right_candidates else len(text)
    quote = text[left:right].strip()
    if len(quote) > width * 2:
        quote = text[max(0, start - width):end + width].strip()
    return re.sub(r"\s+", " ", quote)[:240]


# ---------------------------------------------------------------------------
# Çıkarma
# ---------------------------------------------------------------------------
def _alternatives(question: Dict[str, Any], exclude: Iterable[str] = ()) -> List[Dict[str, str]]:
    """Önerilen + sıradaki iki seçenek, artı/eksi notlarıyla (en fazla 3)."""
    skip = set(exclude)
    opts = [question.get("recommended")] + list(question.get("options") or [])
    seen: List[str] = []
    for o in opts:
        if o and o not in seen and o not in skip:
            seen.append(o)
    out = []
    for o in seen[:3]:
        pros, cons = _note(o) if o in _NOTES else (question.get("why") if o == question.get("recommended") else "", "")
        out.append({"value": o, "pros": pros or "", "cons": cons or ""})
    return out


def _extract_one(qid: str, question: Dict[str, Any], text: str, hints: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Tek kategori için {status, value, quote, options}. Hiçbir şey uydurmaz."""
    found: Dict[str, List[Tuple[str, bool, int, int]]] = {}
    for family, label, specific, rx in _PATTERNS.get(qid, []):
        m = rx.search(text)
        if m:
            found.setdefault(family, []).append((label, specific, m.start(), m.end()))
    # Aile içinde özgül etiket varsa o; yoksa genel etiket
    chosen: List[Tuple[str, str, int, int]] = []
    for family, entries in found.items():
        specifics = [e for e in entries if e[1]]
        pick = specifics or entries
        chosen.append((family, " + ".join(dict.fromkeys(e[0] for e in pick)), min(e[2] for e in pick), min(e[3] for e in pick)))
    if not chosen:
        # Özel (PM'in eklediği) sorular: seçenek adı notlarda aynen geçiyorsa belirtilmiş sayılır
        if qid not in _PATTERNS:
            hits = [(o, text.lower().find(o.lower())) for o in (question.get("options") or []) if o and len(o) > 2]
            hits = [(o, i) for o, i in hits if i >= 0]
            if len(hits) == 1:
                o, i = hits[0]
                return {"status": BELIRTILMIS, "value": o, "quote": _quote_around(text, i, i + len(o))}
            if len(hits) > 1:
                return {"status": CELISKILI, "value": None, "quote": " | ".join(_quote_around(text, i, i + len(o)) for o, i in hits)[:300],
                        "conflict": [o for o, _ in hits]}
        # LLM'in PM çıktısındaki ipucu: yalnızca alıntı notlarda gerçekten geçiyorsa kabul edilir
        for h in hints:
            if h.get("category") == qid and h.get("value") and h.get("quote") and re.sub(r"\s+", " ", str(h["quote"])).lower() in re.sub(r"\s+", " ", text).lower():
                return {"status": BELIRTILMIS, "value": str(h["value"])[:200], "quote": str(h["quote"])[:240]}
        return {"status": EKSIK, "value": None, "quote": None}
    if len(chosen) == 1 or _COMPATIBLE.get(qid):
        labels = " + ".join(c[1] for c in sorted(chosen, key=lambda c: c[2]))
        first = min(chosen, key=lambda c: c[2])
        return {"status": BELIRTILMIS, "value": labels, "quote": _quote_around(text, first[2], first[3])}
    chosen.sort(key=lambda c: c[2])
    return {"status": CELISKILI, "value": None, "conflict": [c[1] for c in chosen],
            "quote": " | ".join(dict.fromkeys(_quote_around(text, c[2], c[3]) for c in chosen))[:300]}


def extract_requirements(questions: List[Dict[str, Any]], spec_text: str, source_title: str = "",
                         hints: Optional[List[Dict[str, Any]]] = None,
                         prior_answers: Optional[Dict[str, str]] = None) -> List[Dict[str, Any]]:
    """Soru setinin her kalemi için TR-n kaydı üretir (kalem durumu `ONAY_BEKLİYOR`)."""
    items: List[Dict[str, Any]] = []
    for n, q in enumerate(questions, start=1):
        qid = q["id"]
        ex = _extract_one(qid, q, spec_text or "", hints or [])
        value = ex.get("value")
        if ex["status"] != BELIRTILMIS and (prior_answers or {}).get(qid):
            value = prior_answers[qid]  # eski karar yalnızca öneri olarak gösterilir, onaylı sayılmaz (A4)
        alts = _alternatives(q, exclude=[]) if ex["status"] != BELIRTILMIS else []
        if ex["status"] == CELISKILI:
            alts = [{"value": c, "pros": _note(c)[0], "cons": _note(c)[1]} for c in ex.get("conflict", [])][:3] or alts
        items.append({
            "id": f"TR-{n}", "category": qid, "label": q.get("question") or (tx(CATEGORY_LABELS[qid]) if qid in CATEGORY_LABELS else qid),
            "value": value, "extracted_status": ex["status"],
            "source": source_title or None if ex["status"] in (BELIRTILMIS, CELISKILI) else None,
            "quote": ex.get("quote"), "question_id": None, "status": ONAY_BEKLIYOR,
            "options": alts, "recommended": q.get("recommended") or "", "why": q.get("why") or "",
            "approved_by": None, "approved_at": None, "adr": None,
        })
    return items


def build_requirements(questions: List[Dict[str, Any]], spec_text: str, source_title: str, project_dir: str,
                       hints: Optional[List[Dict[str, Any]]] = None, prior_answers: Optional[Dict[str, str]] = None,
                       existing: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Yeni kayıt kurar; `existing` varsa onaylı kalemler korunur, yeni notla çelişenler yeniden sorulur (§7.4 madde 9)."""
    fresh = extract_requirements(questions, spec_text, source_title, hints, prior_answers)
    h = _spec_hash(spec_text)
    if existing and existing.get("items"):
        old = {it["category"]: it for it in existing["items"]}
        merged = []
        for it in fresh:
            prev = old.get(it["category"])
            if prev and prev.get("status") == ONAYLANDI:
                if it["extracted_status"] == EKSIK or (it["extracted_status"] == BELIRTILMIS and _same_value(it["value"], prev.get("value"))):
                    merged.append({**prev, "id": prev["id"]})
                    continue
                it = {**it, "extracted_status": CELISKILI,
                      "quote": tx("Onaylı: {old} | Yeni nota göre: {new}", old=prev.get("value"), new=it.get("value") or it.get("quote"))[:300],
                      "value": prev.get("value")}
            elif prev:
                it["id"] = prev["id"]
            merged.append(it)
        items = merged
    else:
        items = fresh
    req = {"status": ONAY_BEKLIYOR, "project_dir": project_dir, "spec_hash": h, "spec_title": source_title,
           "built_at": _now(), "items": items, "questions": (existing or {}).get("questions", []),
           "libraries": (existing or {}).get("libraries", []), "adr_numbers": (existing or {}).get("adr_numbers", []),
           "first_approved_at": (existing or {}).get("first_approved_at"), "changes": (existing or {}).get("changes", [])}
    open_questions(req)
    refresh_status(req)
    return req


def open_questions(req: Dict[str, Any]) -> None:
    """EKSİK / ÇELİŞKİLİ onaysız her kalem için engelleyici TECHNOLOGY sorusu açar (süre ve varsayılan yok)."""
    qs: List[Dict[str, Any]] = req.setdefault("questions", [])
    by_item = {q.get("item_id"): q for q in qs if q.get("item_id")}
    for it in req["items"]:
        needs = it["extracted_status"] in (EKSIK, CELISKILI) and it["status"] != ONAYLANDI
        q = by_item.get(it["id"])
        if needs and (q is None or q.get("status") != "AÇIK"):
            if q is None:
                q = {"id": f"Q-{len(qs) + 1}", "item_id": it["id"], "category": "TECHNOLOGY", "blocking": True}
                qs.append(q)
            q.update({"status": "AÇIK", "question": (tx("{label}: notlarda belirtilmemiş. Hangisi?", label=it["label"]) if it["extracted_status"] == EKSIK
                                                     else tx("{label}: notlarda çelişkili ifadeler var. Hangisi?", label=it["label"])),
                      "options": it["options"], "recommended": it["recommended"] if it["extracted_status"] == EKSIK else (it["options"][0]["value"] if it["options"] else ""),
                      "why": it["why"], "answer": None})
            it["question_id"] = q["id"]
        elif not needs and q is not None and q.get("status") == "AÇIK":
            q["status"] = "CEVAPLANDI"


def refresh_status(req: Dict[str, Any]) -> bool:
    ok = bool(req["items"]) and all(it["status"] == ONAYLANDI for it in req["items"]) \
        and not any(q.get("status") == "AÇIK" and q.get("blocking") for q in req.get("questions", []))
    req["status"] = ONAYLANDI if ok else ONAY_BEKLIYOR
    return ok


def is_approved(req: Optional[Dict[str, Any]]) -> bool:
    return bool(req and req.get("status") == ONAYLANDI and req.get("items"))


def apply_approval(req: Dict[str, Any], *, answers: Optional[Dict[str, Any]] = None, approve_stated: bool = False,
                   accept_recommended: bool = False, by: str = "MANAGER") -> List[str]:
    """Yönetici onayını uygular. `answers`: {kalem id ya da kategori: değer}. Dönen: bu çağrıda onaylanan kalem id'leri.

    `approve_stated`: BELİRTİLMİŞ kalemleri topluca onaylar. EKSİK / ÇELİŞKİLİ kalem yalnızca açık cevapla (ya da
    deneme bayrağında `accept_recommended`) onaylanır.
    """
    answers = answers or {}
    changed: List[str] = []
    now = _now()
    for it in req["items"]:
        if it["status"] == ONAYLANDI and it["id"] not in answers and it["category"] not in answers:
            continue
        val = answers.get(it["id"], answers.get(it["category"]))
        if val is not None and str(val).strip():
            it["value"] = str(val).strip()[:200]
        elif it["extracted_status"] == BELIRTILMIS and approve_stated and it.get("value"):
            pass
        elif accept_recommended and (it.get("value") or it.get("recommended")):
            it["value"] = it.get("value") or it["recommended"]
        else:
            continue
        it["status"], it["approved_by"], it["approved_at"] = ONAYLANDI, by, now
        changed.append(it["id"])
    open_questions(req)
    refresh_status(req)
    return changed


def parse_approved_markdown(text: str) -> Dict[str, Dict[str, Any]]:
    """`TECH_REQUIREMENTS.md` (durum ONAYLANDI) → {TR-n: {value, by, at, adr}}. Belge git'tedir; durum kaydı (settings) kaybolursa onaylı kararlar
    buradan geri kurulur (saha 2026-10-14: ayar dosyası sıfırlanınca kapı yedi onaylı soruyu yeniden açtı). Onaylı değilse boş döner.
    Alıntı hücresi `|` içerebildiğinden satır baştan (id, etiket, karar) ve sondan (onay, ADR) okunur."""
    if not any(v in (text or "") for v in I18N.variants("**Durum:** ONAYLANDI")):
        return {}
    out: Dict[str, Dict[str, Any]] = {}
    for line in text.splitlines():
        if not re.match(r"^\|\s*TR-\d+\s*\|", line):
            continue
        cells = [c.strip() for c in re.split(r"\s\|\s", line.strip().strip("|").strip())]
        if len(cells) < 7:
            continue
        value, onay, adr = cells[2], cells[-2], cells[-1]
        if value in ("", "-") or onay in ("", "—", "-"):
            continue
        by, _, day = onay.partition(",")
        out[cells[0]] = {"value": value, "by": by.strip() or "MANAGER", "at": (day.strip() or None), "adr": None if adr in ("", "-") else adr}
    return out


def restore_approvals(req: Dict[str, Any], approved: Dict[str, Dict[str, Any]]) -> List[str]:
    """`parse_approved_markdown` çıktısını kayda uygular (kalem onaylı, soru kapalı, ilk onay tarihi ve ADR numaraları). Döner: geri kurulan kalem id'leri."""
    changed: List[str] = []
    for it in req.get("items", []):
        a = approved.get(it["id"])
        if not a:
            continue
        it["value"], it["status"], it["approved_by"], it["approved_at"], it["adr"] = a["value"], ONAYLANDI, a["by"], a["at"], a["adr"]
        changed.append(it["id"])
    if changed:
        days = sorted(a["at"] for a in approved.values() if a.get("at"))
        if days and not req.get("first_approved_at"):
            req["first_approved_at"] = f"{days[0]}T00:00:00+00:00"
        nums = sorted({a["adr"] for a in approved.values() if a.get("adr")})
        req["adr_numbers"] = sorted(set(req.get("adr_numbers", [])) | set(nums))
        open_questions(req)
        refresh_status(req)
    return changed


def tech_tokens(req: Dict[str, Any]) -> Set[str]:
    """Onaylı değerlerdeki ve kayıtlı kütüphanelerdeki adlar (bağımlılık denetimi için)."""
    toks: Set[str] = set()
    for it in req.get("items", []):
        if it.get("status") == ONAYLANDI and it.get("value"):
            toks |= {t for t in re.split(r"[^a-z0-9.#@/_-]+", str(it["value"]).lower()) if len(t) >= 2}
    for lib in req.get("libraries", []):
        name = _norm(lib.get("name", ""))
        if name:
            toks.add(name)
    return toks


# ---------------------------------------------------------------------------
# Dosya üretimi (§10.7) ve ADR
# ---------------------------------------------------------------------------
def render_markdown(req: Dict[str, Any], project_name: str, adr_ref: Optional[str] = None) -> str:
    items = req["items"]
    approved = req.get("status") == ONAYLANDI
    first = req.get("first_approved_at") or ""
    last_by = next((it["approved_by"] for it in items if it.get("approved_by")), "-")
    lines = [tx("# Teknoloji gereksinimleri: {project}", project=project_name), "",
             tx("- **Durum:** {status} · **İlk onay:** {day}, {by}", status=ONAYLANDI if approved else tx("ONAY BEKLİYOR"),
                day=first[:10] or '-', by=last_by if first else '-'),
             tx("- **Kaynaklar:** {sources}", sources=req.get('spec_title') or tx("şartname kasası (kaynak yok)")), "",
             tx("## 1. Teknolojiler"),
             tx("| # | Kategori | Karar | Notlardaki durum | Kaynak ve alıntı | Onay | ADR |"), "|---|---|---|---|---|---|---|"]
    cell = lambda s: str(s if s not in (None, "") else "-").replace("|", "/").replace("\n", " ")
    for it in items:
        status = it["extracted_status"] + (f" → {it['question_id']}" if it.get("question_id") and it["extracted_status"] != BELIRTILMIS else "")
        quote = f"{it['source'] + ': ' if it.get('source') else ''}\"{it['quote']}\"" if it.get("quote") else tx("Notlarda yok")
        onay = f"{it['approved_by']}, {it['approved_at'][:10]}" if it.get("approved_by") else "—"
        lines.append(f"| {it['id']} | {cell(it['label'])} | {cell(it.get('value'))} | {cell(status)} | {cell(quote)} | {cell(onay)} | {cell(it.get('adr'))} |")
    pending = [it for it in items if it["status"] != ONAYLANDI]
    lines += ["", tx("## 2. Onay bekleyenler")]
    if not pending:
        lines.append(tx("Yok."))
    for it in pending:
        qid = it.get("question_id")
        lines += ["", f"### {it['id']} · {it['label']} ({it['extracted_status']})" + (f" → {qid}" if qid else "")]
        if it.get("value") and it["extracted_status"] == BELIRTILMIS:
            lines.append(tx("- Notlardan çıkan: **{value}** — onayın bekleniyor", value=it["value"]))
        for a in it.get("options", []):
            rec = tx(" _(önerilen)_") if a["value"] == it.get("recommended") else ""
            lines.append(tx("- **{value}**{rec}: artı — {pros}; eksi — {cons}", value=a["value"], rec=rec, pros=a.get('pros') or '-', cons=a.get('cons') or '-'))
    rej = req.get("rejected", [])
    lines += ["", tx("## 3. Reddedilen ya da ertelenenler")]
    if not rej:
        lines.append(tx("Yok."))
    else:
        lines += [tx("| Teknoloji | Karar | Dayanak |"), "|---|---|---|"] + [f"| {cell(r.get('name'))} | {cell(r.get('decision'))} | {cell(r.get('basis'))} |" for r in rej]
    lines += ["", tx("## 4. Kütüphaneler (mimar kararı; bilgi amaçlı)")]
    libs = req.get("libraries", [])
    if not libs:
        lines.append(tx("Henüz kayıtlı kütüphane yok."))
    else:
        lines += [tx("| Kütüphane | Ne için | Hangi teknolojinin altında |"), "|---|---|---|"] + \
                 [f"| {cell(l.get('name'))} | {cell(l.get('purpose'))} | {cell(l.get('technology'))} |" for l in libs]
    oq = [q for q in req.get("questions", []) if q.get("status") == "AÇIK"]
    if oq:
        lines += ["", tx("## 5. Açık sorular (engelleyici)")] + [f"- **{q['id']}** [{q['category']}] {q['question']}" for q in oq]
    return "\n".join(lines) + "\n"


def next_adr_number(adr_dir: str) -> str:
    nums = []
    if os.path.isdir(adr_dir):
        for f in os.listdir(adr_dir):
            m = re.match(r"^(\d{4})-", f)
            if m:
                nums.append(int(m.group(1)))
    return f"{(max(nums) + 1) if nums else 1:04d}"


def render_adr(number: str, title: str, items: List[Dict[str, Any]], context: str, by: str = "MANAGER") -> str:
    lines = [f"# ADR {number}: {title}", "", tx("- **Durum:** KABUL EDİLDİ"), tx("- **Tarih:** {day}", day=_now()[:10]), tx("- **Karar veren:** {by}", by=by), "",
             tx("## Bağlam"), context, "", tx("## Karar")]
    lines += [f"- {it['id']} · {it['label']}: **{it.get('value')}** ({it['extracted_status']})" for it in items]
    lines += ["", tx("## Sonuçlar"),
              tx("- Olumlu: Teknoloji seçimi yönetici onaylıdır; ekip bunlara uyar, alternatif önermez."),
              tx("- Olumsuz: Değişiklik yeni bir `TECHNOLOGY` sorusu ve yönetici onayı gerektirir.")]
    return "\n".join(lines) + "\n"


def write_documents(req: Dict[str, Any], project_dir: str, docs_rel: str, project_name: str,
                    adr_title: Optional[str] = None, adr_items: Optional[List[Dict[str, Any]]] = None,
                    adr_context: str = "", by: str = "MANAGER") -> List[str]:
    """TECH_REQUIREMENTS.md'yi (ve gerekirse ADR'yi) proje klasörüne yazar; yazılan göreli yolları döner."""
    written = []
    base = os.path.abspath(project_dir)
    if adr_title and adr_items:
        adr_dir = os.path.join(base, *docs_rel.split("/"), "adr")
        number = next_adr_number(adr_dir)
        os.makedirs(adr_dir, exist_ok=True)
        slug = re.sub(r"[^a-z0-9]+", "-", adr_title.lower().replace("ı", "i").replace("ş", "s").replace("ğ", "g").replace("ü", "u").replace("ö", "o").replace("ç", "c")).strip("-")[:40] or "teknoloji"
        rel = f"{docs_rel}/adr/{number}-{slug}.md"
        with open(os.path.join(base, *rel.split("/")), "w", encoding="utf-8", newline="\n") as fh:
            fh.write(render_adr(number, adr_title, adr_items, adr_context, by))
        for it in adr_items:
            it["adr"] = number
        req.setdefault("adr_numbers", []).append(number)
        written.append(rel)
    rel = f"{docs_rel}/TECH_REQUIREMENTS.md"
    os.makedirs(os.path.join(base, *docs_rel.split("/")), exist_ok=True)
    with open(os.path.join(base, *rel.split("/")), "w", encoding="utf-8", newline="\n") as fh:
        fh.write(render_markdown(req, project_name))
    written.append(rel)
    return written


# ---------------------------------------------------------------------------
# Bağımlılık denetimi (§7.4 madde 8)
# ---------------------------------------------------------------------------
_MANIFEST_RX = re.compile(r"(^|/)(requirements[^/]*\.txt|pyproject\.toml|package\.json|composer\.json|go\.mod|dockerfile[^/]*|docker-compose[^/]*\.ya?ml|compose[^/]*\.ya?ml)$", re.IGNORECASE)
_IGNORED = {"python", "php", "pip", "setuptools", "wheel", "npm", "node", "go", "ext-json", "ext-mbstring", "scratch", "alpine"}


def _norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", str(name).strip().lower())


def is_manifest(rel: str) -> bool:
    return bool(_MANIFEST_RX.search(rel.replace("\\", "/")))


def parse_dependencies(rel: str, content: str) -> Set[str]:
    """Manifestten bağımlılık / imaj adlarını çıkarır (dış kütüphane kullanmaz)."""
    r = rel.replace("\\", "/").lower()
    base = r.rsplit("/", 1)[-1]
    out: Set[str] = set()
    try:
        if base.startswith("requirements"):
            for line in content.splitlines():
                line = line.split("#", 1)[0].strip()
                if not line or line.startswith(("-", "git+", "http")):
                    continue
                m = re.match(r"([A-Za-z0-9][A-Za-z0-9._-]*)", line)
                if m:
                    out.add(_norm(m.group(1)))
        elif base == "pyproject.toml":
            data = tomllib.loads(content)
            deps = list((data.get("project") or {}).get("dependencies") or [])
            for group in ((data.get("project") or {}).get("optional-dependencies") or {}).values():
                deps += list(group)
            for d in deps:
                m = re.match(r"([A-Za-z0-9][A-Za-z0-9._-]*)", str(d))
                if m:
                    out.add(_norm(m.group(1)))
            for name in ((data.get("tool") or {}).get("poetry") or {}).get("dependencies", {}) or {}:
                out.add(_norm(name))
        elif base == "package.json":
            data = json.loads(content)
            for key in ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies"):
                out |= {_norm(k) for k in (data.get(key) or {})}
        elif base == "composer.json":
            data = json.loads(content)
            for key in ("require", "require-dev"):
                out |= {_norm(k) for k in (data.get(key) or {}) if not k.lower().startswith("ext-")}
        elif base == "go.mod":
            for line in content.splitlines():
                m = re.match(r"^\s*(?:require\s+)?([A-Za-z0-9][\w./~-]*\.[\w./~-]+)\s+v[\w.+-]+", line)
                if m:
                    out.add(_norm(m.group(1)))
        elif base.startswith("dockerfile"):
            for m in re.finditer(r"^\s*FROM\s+(?:--platform=\S+\s+)?([^\s:@]+)", content, re.IGNORECASE | re.MULTILINE):
                out.add(_norm(m.group(1).rsplit("/", 1)[-1]))
        elif "compose" in base:
            # Servis blokları (2 boşluk girintili anahtarlar): `build:` olan servisin `image:` adı yerelde derlenen imajın etiketidir, dış bağımlılık değildir
            blocks = re.split(r"(?m)^(?=  [A-Za-z0-9_.-]+:\s*$)", content)
            for b in (blocks if len(blocks) > 1 else [content]):
                if len(blocks) > 1 and re.search(r"(?m)^\s+build:", b):
                    continue
                for m in re.finditer(r"^\s*image:\s*['\"]?([^\s:@'\"]+)", b, re.IGNORECASE | re.MULTILINE):
                    out.add(_norm(m.group(1).rsplit("/", 1)[-1]))
    except Exception:
        return out
    return {d for d in out if d and d not in _IGNORED}


def _allowed(name: str, tokens: Set[str]) -> bool:
    n = _norm(name)
    if n in tokens or n.lstrip("@") in tokens:
        return True
    plain = {_norm(t) for t in tokens}
    if n in plain:
        return True
    if len(n) >= 4:
        for t in plain:
            if len(t) >= 4 and (t.startswith(n) or n.startswith(t)):
                return True
    return False


def audit_dependencies(req: Optional[Dict[str, Any]], project_dir: str, files: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    """Teslimde yeni eklenen ama onaylı teknolojilerde / kayıtlı kütüphanelerde olmayan bağımlılıklar.

    Kayıt yoksa (eski proje, kapı hiç kurulmadı) denetim atlanır. Önceden diskte olan bağımlılıklar yeni sayılmaz.
    """
    if not req or not is_approved(req):
        return []
    tokens = tech_tokens(req)
    violations: List[Dict[str, str]] = []
    for f in files:
        rel = str(f.get("path", "")).replace("\\", "/").lstrip("/")
        if not is_manifest(rel):
            continue
        new = parse_dependencies(rel, str(f.get("content", "")))
        old: Set[str] = set()
        path = os.path.join(project_dir, *rel.split("/"))
        if os.path.isfile(path):
            try:
                with open(path, "r", encoding="utf-8", errors="ignore") as fh:
                    old = parse_dependencies(rel, fh.read())
            except Exception:
                old = set()
        for dep in sorted(new - old):
            if not _allowed(dep, tokens):
                violations.append({"dependency": dep, "file": rel})
    return violations
