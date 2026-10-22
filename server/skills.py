"""Skill kütüphanesi: ajanlara tanımlarına EK olarak verilen bilgi/yöntem rehberleri (aitmpl.com/skills · davila7/claude-code-templates).

Skill ajan değildir: kimlik, sorumluluk ve çıktı sözleşmesi FS-SC'nin kendi ajan tanımındadır; skill yalnızca "nasıl yapılır" bilgisini ekler.
- Katalog `agents/skills/catalog.json` (seçilmiş, doğrulanmış referanslar: kimlik, kategori, rol eşlemesi, kaynak). Çekirdek varsayılanlar katalogdaki `default_roles`'tür.
- İçerik GitHub'dan indirilip yerel önbelleğe (`history/skills_cache/`) alınır; adım istemine rol başına en çok N skill ve toplam bütçe kadar ÖZET girer.
- Skill metni üçüncü taraf içeriğidir: istemde "tavsiye niteliğinde, görev ve kabul kriterleri önceliklidir, yeni kütüphane önerme" notuyla verilir.
- Ayar (`agent_skills`): {enabled, roles: {ROL: [skill kimlikleri]}, max_chars}; rol için liste yoksa katalog varsayılanı kullanılır.
"""
from __future__ import annotations

import json
import os
import re
import threading
import urllib.request
from typing import Any, Dict, List, Optional

from .i18n import translate as tx

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
CATALOG_PATH = os.path.join(REPO_ROOT, "agents", "skills", "catalog.json")
DEFAULT_MAX_CHARS = 5000
PROMPT_CAP_CHARS = 6000          # ayar ne olursa olsun adım istemine en çok bu kadar skill metni girer (istemci araç yanıtı sınırı)
MAX_PER_ROLE = 4
PER_SKILL_CHARS = 3000
FETCH_TIMEOUT_S = 15.0

_CATALOG: Dict[str, Any] = {"mtime": None, "data": {"source": {}, "skills": []}}
_LOCK = threading.RLock()
_INFLIGHT: set = set()


def cache_dir() -> str:
    d = os.environ.get("FSSC_SKILLS_CACHE") or os.path.join(REPO_ROOT, "history", "skills_cache")
    os.makedirs(d, exist_ok=True)
    return d


def catalog() -> Dict[str, Any]:
    with _LOCK:
        try:
            m = os.path.getmtime(CATALOG_PATH)
        except OSError:
            return _CATALOG["data"]
        if _CATALOG["mtime"] != m:
            with open(CATALOG_PATH, encoding="utf-8") as f:
                _CATALOG["data"] = json.load(f)
            _CATALOG["mtime"] = m
        return _CATALOG["data"]


def by_id() -> Dict[str, Dict[str, Any]]:
    return {s["id"]: s for s in catalog().get("skills", [])}


def source_url(skill: Dict[str, Any]) -> str:
    repo = catalog().get("source", {}).get("repo", "")
    return f"{repo}/tree/main/cli-tool/components/skills/{skill['category']}/{skill['id']}"


def raw_url(skill: Dict[str, Any]) -> str:
    return f"{catalog().get('source', {}).get('raw_base', '')}{skill['category']}/{skill['id']}/SKILL.md"


def settings(hub) -> Dict[str, Any]:
    raw = (hub.get_settings() or {}).get("agent_skills")
    raw = raw if isinstance(raw, dict) else {}
    return {"enabled": bool(raw.get("enabled", True)), "roles": raw.get("roles") if isinstance(raw.get("roles"), dict) else {},
            "max_chars": min(int(raw.get("max_chars") or DEFAULT_MAX_CHARS), PROMPT_CAP_CHARS)}


def sanitize_settings(value: Any) -> Dict[str, Any]:
    """Ayar doğrulaması: yalnızca katalogdaki kimlikler, rol başına en çok MAX_PER_ROLE, bütçe 2000-20000."""
    known = by_id()
    v = value if isinstance(value, dict) else {}
    roles: Dict[str, List[str]] = {}
    for role, ids in (v.get("roles") or {}).items() if isinstance(v.get("roles"), dict) else []:
        r = re.sub(r"[^A-Z0-9_]", "", str(role).upper())[:40]
        if r and isinstance(ids, list):
            roles[r] = [i for i in dict.fromkeys(str(x) for x in ids) if i in known][:MAX_PER_ROLE]
    try:
        mc = max(2000, min(20000, int(v.get("max_chars") or DEFAULT_MAX_CHARS)))
    except (TypeError, ValueError):
        mc = DEFAULT_MAX_CHARS
    return {"enabled": bool(v.get("enabled", True)), "roles": roles, "max_chars": mc}


def base_role(hub, agent_id: str) -> str:
    a = (getattr(hub, "agents", None) or {}).get(agent_id) or {}
    rb = str(a.get("role_base") or "").upper()
    return rb or str(a.get("role") or agent_id).upper()


def skills_for_role(hub, agent_id: str) -> List[str]:
    """Rolün etkin skill kimlikleri: kullanıcı seçimi (agent_id ya da temel rol için) yoksa katalog varsayılanı (agent_id, sonra temel rol)."""
    st = settings(hub)
    known = by_id()
    roles = st["roles"]
    for key in (agent_id, base_role(hub, agent_id)):
        if key in roles:
            return [i for i in roles[key] if i in known][:MAX_PER_ROLE]
    out: List[str] = []
    for key in (agent_id, base_role(hub, agent_id)):
        for s in catalog().get("skills", []):
            if key in (s.get("default_roles") or []) and s["id"] not in out:
                out.append(s["id"])
        if out:
            break
    return out[:MAX_PER_ROLE]


# ---------------------------------------------------------------------------
# İçerik: indirme + önbellek
# ---------------------------------------------------------------------------
def cache_path(skill_id: str) -> str:
    return os.path.join(cache_dir(), re.sub(r"[^A-Za-z0-9._-]", "_", skill_id) + ".md")


def cached(skill_id: str) -> bool:
    return os.path.isfile(cache_path(skill_id))


def fetch(skill_id: str, timeout: float = FETCH_TIMEOUT_S) -> bool:
    """Skill dosyasını indirip önbelleğe yazar (çevrimdışı/hata → False; çağıran sessizce atlar)."""
    sk = by_id().get(skill_id)
    if sk is None:
        return False
    try:
        req = urllib.request.Request(raw_url(sk), headers={"User-Agent": "fssc-skills"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            text = r.read(400_000).decode("utf-8", "replace")
    except Exception:  # noqa: BLE001
        return False
    if not text.strip():
        return False
    with open(cache_path(skill_id), "w", encoding="utf-8") as f:
        f.write(text)
    return True


def prefetch(skill_ids: List[str]) -> None:
    """Eksik skill'leri arka planda indirir (adımı bekletmez); aynı kimlik iki kez denenmez."""
    todo = [i for i in skill_ids if not cached(i) and i not in _INFLIGHT]
    if not todo:
        return
    _INFLIGHT.update(todo)

    def run() -> None:
        try:
            for i in todo:
                fetch(i)
        finally:
            _INFLIGHT.difference_update(todo)

    threading.Thread(target=run, daemon=True, name="fssc-skill-prefetch").start()


def _excerpt(text: str, limit: int) -> str:
    body = re.sub(r"\A---\n.*?\n---\n", "", text, count=1, flags=re.S)
    body = re.sub(r"\n{3,}", "\n\n", body).strip()
    return body if len(body) <= limit else body[:limit].rsplit("\n", 1)[0] + tx("\n…(kısaltıldı)")


def prompt_section(hub, agent_id: str) -> str:
    """Adım istemine eklenecek skill bölümü (boşsa boş metin). Önbellekte olmayan skill arka planda indirilir ve bu adımda atlanır."""
    st = settings(hub)
    if not st["enabled"]:
        return ""
    ids = skills_for_role(hub, agent_id)
    if not ids:
        return ""
    prefetch(ids)
    known = by_id()
    parts: List[str] = []
    used = 0
    per = max(800, min(PER_SKILL_CHARS, st["max_chars"] // max(1, len(ids))))
    for sid in ids:
        if not cached(sid):
            continue
        try:
            with open(cache_path(sid), encoding="utf-8") as f:
                text = _excerpt(f.read(), per)
        except OSError:
            continue
        if used + len(text) > st["max_chars"]:
            break
        used += len(text)
        parts.append(f"### Skill: {known[sid]['title']} (`{sid}`)\n{text}")
    if not parts:
        return ""
    return (tx("\n\n## Ek yetenekler (skill rehberleri)\n"
               "Aşağıdakiler rolünün tanımına EK, üçüncü taraf bilgi rehberleridir: tavsiye niteliğindedir. Görevin kabul kriterleri, rol tanımın, proje klasör düzeni ve onaylı teknoloji yığını "
               "ÖNCELİKLİDİR; çelişirse onlara uy. Rehberlerin önerdiği yeni kütüphaneyi ekleme (teknoloji kapısı geçerli).\n\n") + "\n\n".join(parts))


def overview(hub) -> Dict[str, Any]:
    """Arayüz için: katalog, rol başına etkin seçim ve önbellek durumu."""
    st = settings(hub)
    agents = getattr(hub, "agents", None) or {}
    roles = []
    for aid, a in agents.items():
        if str(a.get("role") or "").upper() in ("SCM", "REPORTER", "SCRUM_MASTER", "E2E_TESTER", "PO", "PM"):
            continue
        roles.append({"id": aid, "name": a.get("name") or aid, "selected": skills_for_role(hub, aid), "custom": aid in st["roles"] or base_role(hub, aid) in st["roles"]})
    skills = [{**s, "cached": cached(s["id"]), "source": source_url(s)} for s in catalog().get("skills", [])]
    return {"enabled": st["enabled"], "max_chars": st["max_chars"], "roles": roles, "skills": skills, "source": catalog().get("source", {})}
