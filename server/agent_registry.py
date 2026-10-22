"""
G6 — ajan yönetimi: iki kapsam (şirket geneli + proje), yetenek eşlemesi, profil, sağlık, dışa/içe aktarma (plan §4.2).

Kapsamlar
- **Şirket geneli:** `agents/registry.json` (ortam değişkeni `FSSC_AGENT_REGISTRY` ile değişir). Tanım tek yerde durur; her projeye etkinleştirilince görünür.
- **Proje:** `hub.agents` (projenin kaydı). Global bir ajan projede `inherits: <id>` ile yaşar; projeye özgü farklar `overrides` içinde tutulur,
  kalan alanlar globalden gelir (globalde değişiklik, farkı olmayan alanlara yansır). Çekirdek roller (`DEFAULT_AGENTS`) globale taşınmaz.

Yetenek eşlemesi (§4.2.3): backlog görevinin rolü sabit liste yerine ajanın `capabilities` (iş türü) ve `focus` (anahtar sözcük) alanlarıyla eşleşir.
Özel ajan bir temel rolü (`role_base`) devralır: istem şablonu, görev ipuçları ve doğrulama yolu temel rolünkidir.
"""

from __future__ import annotations

import copy
import json
import os
import re
import threading
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

from .config import DEFAULT_AGENTS
from .i18n import translate as tx, N_

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
TEMPLATES_DIR = os.path.join(REPO_ROOT, "agents", "templates")

CORE_IDS = frozenset(a["id"] for a in DEFAULT_AGENTS)
# Görev alabilen çekirdek roller (E2E_TESTER ve SCM görev alamaz, A16)
BASE_ROLES = ("BACKEND_DEV", "FRONTEND_DEV", "DESIGNER", "DEVOPS", "QA", "ARCHITECT", "DOCUMENTOR")
TASK_WORK_TYPES = ("SCAFFOLD", "FEATURE", "DESIGN", "TEST", "E2E_SCENARIO", "DEVOPS", "DOCS", "BUG", "IMPROVEMENT", "REFACTOR", "TEST_DESIGN", "SECURITY_TEST", "PERF_SMOKE")
ALL_CAPABILITIES = TASK_WORK_TYPES + ("REVIEW",)
_DEV_CAPS = ("SCAFFOLD", "FEATURE", "BUG", "IMPROVEMENT", "REFACTOR")
BASE_CAPABILITIES: Dict[str, tuple] = {
    "BACKEND_DEV": _DEV_CAPS, "FRONTEND_DEV": _DEV_CAPS, "DESIGNER": ("DESIGN", "IMPROVEMENT"), "DEVOPS": ("DEVOPS", "BUG"), "QA": ("TEST", "E2E_SCENARIO", "BUG", "TEST_DESIGN", "SECURITY_TEST", "PERF_SMOKE"),
    "ARCHITECT": ("REVIEW", "REFACTOR"), "DOCUMENTOR": ("DOCS",),
}
EFFORTS = ("low", "medium", "high", "xhigh", "max")
LANGUAGES = ("tr", "en")
# Ajan tanımının (projeler arasında paylaşılan) alanları; çalışma zamanı alanları (durum, token, son görülme) tanımın parçası değildir
DEFINITION_FIELDS = ("name", "role", "role_base", "description", "capabilities", "focus", "profile", "active", "meeting_roles", "evaluates",
                     "prompt_addendum", "active_file")
PACKAGE_FORMAT = "fssc-agent/1"


class AgentError(ValueError):
    """Geçersiz ajan tanımı (HTTP 400)."""


# ---------------------------------------------------------------------------
# Tanım modeli
# ---------------------------------------------------------------------------
def clean_id(value: Any) -> str:
    raw = re.sub(r"[^A-Z0-9_]+", "_", str(value or "").upper().strip()).strip("_")
    return raw[:40]


def _str_list(value: Any, limit: int = 20, upper: bool = False, lower: bool = False) -> List[str]:
    if isinstance(value, str):
        value = [p for p in re.split(r"[,\n;]", value)]
    out: List[str] = []
    for item in value if isinstance(value, (list, tuple)) else []:
        s = str(item).strip()
        s = s.upper() if upper else (s.lower() if lower else s)
        if s and s not in out:
            out.append(s[:60])
    return out[:limit]


def normalize_profile(raw: Any) -> Dict[str, Any]:
    """`model`, `effort`, `max_tokens`, `tools_allow`, `language`, `budget` (sprint başına token); boş değerler atılır, geçersiz değer hata verir."""
    if raw in (None, ""):
        return {}
    if not isinstance(raw, dict):
        raise AgentError(tx("profile bir nesne olmalı (model, effort, max_tokens, tools_allow, language, budget)."))
    out: Dict[str, Any] = {}
    model = str(raw.get("model") or "").strip()
    if model:
        out["model"] = model[:80]
    effort = str(raw.get("effort") or "").strip().lower()
    if effort:
        if effort not in EFFORTS:
            raise AgentError(tx("Geçersiz çaba düzeyi '{effort}': {values}.", effort=effort, values=', '.join(EFFORTS)))
        out["effort"] = effort
    lang = str(raw.get("language") or "").strip().lower()
    if lang:
        if lang not in LANGUAGES:
            raise AgentError(tx("Geçersiz dil '{lang}': {values}.", lang=lang, values=', '.join(LANGUAGES)))
        out["language"] = lang
    for key, hi in (("max_tokens", 1_000_000), ("budget", 100_000_000)):
        val = raw.get(key)
        if val in (None, "", 0):
            continue
        try:
            num = int(val)
        except (TypeError, ValueError):
            raise AgentError(tx("{key} tamsayı olmalı.", key=key))
        if num < 1 or num > hi:
            raise AgentError(tx("{key} 1 ile {hi} arasında olmalı.", key=key, hi=hi))
        out[key] = num
    tools = _str_list(raw.get("tools_allow"), limit=30)
    if tools:
        out["tools_allow"] = tools
    return out


def normalize_definition(raw: Dict[str, Any], base: Optional[Dict[str, Any]] = None, partial: bool = False) -> Dict[str, Any]:
    """Ham girdiyi tanım alanlarına indirger. `partial=True`: yalnızca verilen alanlar döner (güncelleme / proje farkı); aksi halde eksikler varsayılan alır."""
    if not isinstance(raw, dict):
        raise AgentError(tx("Ajan tanımı bir nesne olmalı."))
    out: Dict[str, Any] = {}
    cur = base or {}

    def has(key: str) -> bool:
        return key in raw and raw[key] is not None

    if has("name"):
        out["name"] = str(raw["name"]).strip()[:80]
    if has("description"):
        out["description"] = str(raw["description"]).strip()[:400]
    if has("active_file"):
        out["active_file"] = str(raw["active_file"]).strip()[:200]
    if has("role"):
        out["role"] = str(raw["role"]).strip()[:60]
    if has("role_base"):
        rb = clean_id(raw["role_base"])
        if rb not in BASE_ROLES:
            raise AgentError(tx("Geçersiz temel rol '{role}': {values}.", role=raw['role_base'], values=', '.join(BASE_ROLES)))
        out["role_base"] = rb
    if has("capabilities"):
        caps = [c for c in _str_list(raw["capabilities"], limit=20, upper=True) if c in ALL_CAPABILITIES]
        out["capabilities"] = caps
    if has("focus"):
        out["focus"] = _str_list(raw["focus"], limit=20, lower=True)
    if has("profile"):
        out["profile"] = normalize_profile(raw["profile"])
    if has("active"):
        out["active"] = bool(raw["active"])
    if has("meeting_roles"):
        out["meeting_roles"] = _str_list(raw["meeting_roles"], limit=12, upper=True)
    if has("evaluates"):
        out["evaluates"] = _str_list(raw["evaluates"], limit=12, upper=True)
    if has("prompt_addendum"):
        out["prompt_addendum"] = str(raw["prompt_addendum"]).strip()[:4000]
    if has("auto_assign"):
        out["auto_assign"] = bool(raw["auto_assign"])          # yalnızca havuz kaydında anlamlı: true ise her projeye kendiliğinden eklenir
    if partial:
        return out
    out.setdefault("auto_assign", bool(cur.get("auto_assign")))
    # Tam tanım: varsayılanlar
    rb = out.get("role_base") or cur.get("role_base") or "BACKEND_DEV"
    out["role_base"] = rb
    out.setdefault("name", cur.get("name") or "")
    out.setdefault("role", cur.get("role") or "DEVELOPER")
    out.setdefault("description", cur.get("description") or "")
    caps = out.get("capabilities") if "capabilities" in out else cur.get("capabilities")
    out["capabilities"] = list(caps) if caps else list(BASE_CAPABILITIES.get(rb, ()))
    out.setdefault("focus", list(cur.get("focus") or []))
    out.setdefault("profile", dict(cur.get("profile") or {}))
    out.setdefault("active", bool(cur.get("active", True)))
    out.setdefault("meeting_roles", list(cur.get("meeting_roles") or []))
    out.setdefault("evaluates", list(cur.get("evaluates") or []))
    out.setdefault("prompt_addendum", cur.get("prompt_addendum") or "")
    out.setdefault("active_file", cur.get("active_file") or "")
    return out


def merged_definition(global_def: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    """Global tanım + projeye özgü fark (profil anahtar anahtar birleşir)."""
    out = {k: (dict(v) if isinstance(v, dict) else (list(v) if isinstance(v, list) else v)) for k, v in global_def.items() if k in DEFINITION_FIELDS}
    for key, val in (overrides or {}).items():
        if key not in DEFINITION_FIELDS:
            continue
        if key == "profile" and isinstance(val, dict):
            out["profile"] = {**(out.get("profile") or {}), **val}
        else:
            out[key] = val
    return out


# ---------------------------------------------------------------------------
# Çekirdek / özel ayrımı ve görev yönlendirme
# ---------------------------------------------------------------------------
def scope_of(agent: Dict[str, Any]) -> str:
    if agent.get("id") in CORE_IDS:
        return "core"
    return "global" if agent.get("inherits") else "project"


def base_role_of(agent: Dict[str, Any]) -> str:
    """İstem şablonu / ipucu / yetenek için temel rol: özel ajanda `role_base`, çekirdek ajanda kendi rolü."""
    rb = str(agent.get("role_base") or "").upper()
    if rb:
        return rb
    return str(agent.get("role") or agent.get("id") or "DEVELOPER").upper()


def capabilities_of(agent: Dict[str, Any]) -> List[str]:
    caps = agent.get("capabilities")
    if caps:
        return list(caps)
    return list(BASE_CAPABILITIES.get(base_role_of(agent), ()))


def is_active(agent: Dict[str, Any]) -> bool:
    return bool(agent.get("active", True))


def routing_roles(hub) -> Dict[str, Dict[str, Any]]:
    """Görev alabilen ÖZEL ajanlar: {id: {role_base, capabilities, focus, name, description}} (etkin, en az bir iş türü yeteneği olan)."""
    out: Dict[str, Dict[str, Any]] = {}
    for aid, a in (getattr(hub, "agents", None) or {}).items():
        if aid in CORE_IDS or not is_active(a):
            continue
        caps = [c for c in capabilities_of(a) if c in TASK_WORK_TYPES]
        if not caps:
            continue
        out[aid] = {"role_base": base_role_of(a) if base_role_of(a) in BASE_ROLES else "BACKEND_DEV", "capabilities": caps,
                    "focus": list(a.get("focus") or []), "name": a.get("name") or aid, "description": a.get("description") or ""}
    return out


def task_role_ids(hub) -> set:
    """Backlog görevi alabilen tüm roller: çekirdek roller + etkin özel ajanlar."""
    return set(BASE_ROLES) | set(routing_roles(hub))


def match_by_capability(roles: Dict[str, Dict[str, Any]], work_type: str, text: str) -> Optional[str]:
    """Rolü belirtilmemiş / bilinmeyen göreve özel ajan seçer: iş türünü yapabilen VE odak sözcüklerinden biri görev metninde geçen ajan.
    Odağı olmayan ajan kendiliğinden görev kapmaz (yanlışlıkla yönlendirme olmaz)."""
    low = str(text or "").lower()
    for aid, spec in roles.items():
        if work_type and work_type not in spec["capabilities"]:
            continue
        if any(k and k in low for k in spec["focus"]):
            return aid
    return None


def roles_prompt_section(hub) -> str:
    """Mimarın backlog yönergesine eklenen özel ajan listesi (boşsa boş metin)."""
    roles = routing_roles(hub)
    if not roles:
        return ""
    lines = [tx("- Özel ajanlar (bu projede görev alabilir; `role` alanına kimliğini yaz):")]
    for aid, spec in roles.items():
        focus = tx("; odak: {words}", words=', '.join(spec['focus'])) if spec["focus"] else ""
        desc = f" — {spec['description']}" if spec["description"] else ""
        lines.append(tx("  - `{aid}` ({name}{desc}); yetenekler: {caps}; temel rol: {base}{focus}", aid=aid, name=spec['name'], desc=desc,
                       caps=', '.join(spec['capabilities']), base=spec['role_base'], focus=focus))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Şirket geneli kayıt (agents/registry.json)
# ---------------------------------------------------------------------------
_LOCK = threading.RLock()
_CACHE: Dict[str, Any] = {"path": None, "mtime": None, "data": {}}


def registry_path() -> str:
    return os.environ.get("FSSC_AGENT_REGISTRY") or os.path.join(REPO_ROOT, "agents", "registry.json")


def load_global() -> Dict[str, Dict[str, Any]]:
    """{id: tanım}. Dosya yoksa/bozuksa boş."""
    path = registry_path()
    with _LOCK:
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            _CACHE.update(path=path, mtime=None, data={})
            return {}
        if _CACHE["path"] == path and _CACHE["mtime"] == mtime:
            return {k: dict(v) for k, v in _CACHE["data"].items()}
        try:
            with open(path, "r", encoding="utf-8") as fh:
                raw = json.load(fh)
            agents = raw.get("agents") if isinstance(raw, dict) else None
            data = {clean_id(k): v for k, v in (agents or {}).items() if isinstance(v, dict) and clean_id(k)}
        except (OSError, ValueError):
            data = {}
        _CACHE.update(path=path, mtime=mtime, data=data)
        return {k: dict(v) for k, v in data.items()}


def _save_global(data: Dict[str, Dict[str, Any]]) -> None:
    path = registry_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump({"version": 1, "updated_at": datetime.now(timezone.utc).isoformat(), "agents": data}, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, path)
    _CACHE.update(path=None, mtime=None)


def upsert_global(agent_id: str, definition: Dict[str, Any]) -> Dict[str, Any]:
    aid = clean_id(agent_id)
    if not aid:
        raise AgentError(tx("Ajan kimliği boş olamaz."))
    if aid in CORE_IDS:
        raise AgentError(tx("'{aid}' çekirdek bir roldür; şirket geneli ajan olarak tanımlanamaz.", aid=aid))
    with _LOCK:
        data = load_global()
        full = normalize_definition(definition, base=data.get(aid))
        full["id"] = aid
        full["updated_at"] = datetime.now(timezone.utc).isoformat()
        data[aid] = full
        _save_global(data)
    return full


def delete_global(agent_id: str) -> bool:
    aid = clean_id(agent_id)
    with _LOCK:
        data = load_global()
        if aid not in data:
            return False
        del data[aid]
        _save_global(data)
    return True


# ---------------------------------------------------------------------------
# Projeye uygulama
# ---------------------------------------------------------------------------
def _runtime_fields(agent_id: str, definition: Dict[str, Any]) -> Dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    return {"id": agent_id, "status": "IDLE", "tokens_in": 0, "tokens_out": 0, "total_tokens": 0, "last_action": "GLOBAL_AGENT_ASSIGNED",
            "last_seen": now, "active_file": definition.get("active_file", "")}


def apply_global_to_agent(agent: Dict[str, Any], global_def: Dict[str, Any]) -> Dict[str, Any]:
    """Projedeki kaydı globalden yenilemek: farkı (`overrides`) olmayan tanım alanları globalden gelir."""
    effective = merged_definition(global_def, agent.get("overrides") or {})
    for key in DEFINITION_FIELDS:
        if key in effective:
            agent[key] = effective[key]
    agent["inherits"] = agent.get("inherits") or clean_id(global_def.get("id"))
    agent["scope"] = "global"
    return agent


def sync_globals(agents: Dict[str, Dict[str, Any]]) -> List[str]:
    """Projenin ajan sözlüğünü şirket geneli kayıtla eşitler: kayıttaki her ajan projede görünür (yoksa eklenir), `inherits` olanlar yenilenir.
    Projede aynı kimlikle `inherits`siz bir ajan varsa o projeye özgüdür ve dokunulmaz. Dönüş: değişen kimlikler."""
    changed: List[str] = []
    glob = load_global()
    for aid, gdef in glob.items():
        cur = agents.get(aid)
        if cur is None:
            if not gdef.get("auto_assign"):                    # havuz kaydı: projeye yalnızca yönetici isteyince eklenir (add_from_pool)
                continue
            rec = _runtime_fields(aid, gdef)
            rec["overrides"] = {}
            agents[aid] = apply_global_to_agent(rec, gdef)
            changed.append(aid)
        elif cur.get("inherits") == aid:
            before = json.dumps({k: cur.get(k) for k in DEFINITION_FIELDS}, sort_keys=True, default=str)
            apply_global_to_agent(cur, gdef)
            if json.dumps({k: cur.get(k) for k in DEFINITION_FIELDS}, sort_keys=True, default=str) != before:
                changed.append(aid)
    # Globalden silinmiş ajanlar projede kalır ama proje sahipliğine geçer
    for aid, cur in agents.items():
        if cur.get("inherits") and cur["inherits"] not in glob:
            cur.pop("inherits", None)
            cur["scope"] = "project"
            changed.append(aid)
    return changed


def add_from_pool(agents: Dict[str, Dict[str, Any]], pool_id: str, mode: str = "linked", new_id: str = "") -> Dict[str, Any]:
    """Havuzdaki ajanı projeye ekler. `linked`: havuza bağlı (tanım havuzda değişince farksız alanlar güncellenir, projeye özgü fark `overrides`);
    `copy`: bağımsız kopya (havuzdan kopar, tamamen projeye ait)."""
    gid = clean_id(pool_id)
    gdef = load_global().get(gid)
    if gdef is None:
        raise AgentError(tx("Havuzda böyle bir ajan yok."))
    aid = clean_id(new_id) if (mode == "copy" and new_id) else gid
    if aid in agents:
        raise AgentError(tx("'{aid}' bu projede zaten var.", aid=aid))
    rec = _runtime_fields(aid, gdef)
    if mode == "copy":
        for key in DEFINITION_FIELDS:
            if key in gdef:
                rec[key] = copy.deepcopy(gdef[key])
        rec["id"], rec["scope"], rec["active"] = aid, "project", True
        rec["pool_origin"] = gid
    else:
        rec["overrides"] = {}
        apply_global_to_agent(rec, gdef)
        rec["active"] = True
    rec["last_action"] = "ADDED_FROM_POOL"
    agents[aid] = rec
    return rec


def with_scope(agent: Dict[str, Any]) -> Dict[str, Any]:
    return {**agent, "scope": scope_of(agent)}


# ---------------------------------------------------------------------------
# Dışa / içe aktarma ve şablon kütüphanesi
# ---------------------------------------------------------------------------
def definition_of(agent: Dict[str, Any]) -> Dict[str, Any]:
    """Bir proje ajanının paylaşılabilir tanımı (çalışma zamanı alanları olmadan)."""
    d = {k: agent.get(k) for k in DEFINITION_FIELDS if agent.get(k) not in (None,)}
    d["id"] = agent.get("id")
    d["role_base"] = d.get("role_base") or (base_role_of(agent) if base_role_of(agent) in BASE_ROLES else "BACKEND_DEV")
    d["capabilities"] = capabilities_of(agent)
    return d


def export_package(agent: Dict[str, Any], prompt_md: str = "") -> Dict[str, Any]:
    return {"format": PACKAGE_FORMAT, "exported_at": datetime.now(timezone.utc).isoformat(), "definition": definition_of(agent), "prompt_md": prompt_md or ""}


def parse_package(pkg: Any) -> Dict[str, Any]:
    if not isinstance(pkg, dict) or pkg.get("format") != PACKAGE_FORMAT or not isinstance(pkg.get("definition"), dict):
        raise AgentError(tx("Geçersiz ajan paketi (format '{fmt}' beklenir).", fmt=PACKAGE_FORMAT))
    d = dict(pkg["definition"])
    aid = clean_id(d.get("id") or d.get("name"))
    if not aid:
        raise AgentError(tx("Paketteki ajanın kimliği ya da adı yok."))
    if aid in CORE_IDS:
        raise AgentError(tx("'{aid}' çekirdek bir roldür; paketle değiştirilemez.", aid=aid))
    full = normalize_definition(d)
    full["id"] = aid
    return {"id": aid, "definition": full, "prompt_md": str(pkg.get("prompt_md") or "")}


def list_templates() -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    try:
        names = sorted(n for n in os.listdir(TEMPLATES_DIR) if n.endswith(".json"))
    except OSError:
        return out
    for n in names:
        try:
            with open(os.path.join(TEMPLATES_DIR, n), "r", encoding="utf-8") as fh:
                t = json.load(fh)
        except (OSError, ValueError):
            continue
        if isinstance(t, dict) and isinstance(t.get("agents"), list):
            out.append({"key": n[:-5], "name": t.get("name") or n[:-5], "description": t.get("description") or "",
                        "agents": [{"id": clean_id(a.get("id") or a.get("name")), "name": a.get("name"), "role_base": a.get("role_base"),
                                    "capabilities": a.get("capabilities"), "focus": a.get("focus")} for a in t["agents"] if isinstance(a, dict)]})
    return out


def template_definitions(key: str) -> List[Dict[str, Any]]:
    safe = re.sub(r"[^A-Za-z0-9_-]", "", str(key or ""))
    if not safe or safe != str(key):
        raise AgentError(tx("Geçersiz şablon anahtarı: {key}", key=key))
    path = os.path.join(TEMPLATES_DIR, f"{safe}.json")
    try:
        with open(path, "r", encoding="utf-8") as fh:
            t = json.load(fh)
    except (OSError, ValueError):
        raise AgentError(tx("Şablon bulunamadı: {key}", key=key))
    defs: List[Dict[str, Any]] = []
    for a in t.get("agents") or []:
        if not isinstance(a, dict):
            continue
        aid = clean_id(a.get("id") or a.get("name"))
        if not aid or aid in CORE_IDS:
            continue
        full = normalize_definition(a)
        full["id"] = aid
        defs.append(full)
    if not defs:
        raise AgentError(tx("Şablonda uygulanabilir ajan yok: {key}", key=key))
    return defs


# ---------------------------------------------------------------------------
# Sağlık (§4.2.5)
# ---------------------------------------------------------------------------
def health(hub, agent_id: str, prompt_versions: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """Rol başına başarı ölçütleri (aktif projenin koşularından): teslim, ilk seferde geçme, düzeltme turu, başarısız adım, token, prompt sürümleri.
    İlk seferde geçme: teslimi DONE olan ve aynı koşuda o madde için düzeltme turu açılmamış adımlar."""
    aid = clean_id(agent_id)
    delivered = first_pass = fix_rounds = failed = 0
    for run in hub.runs.values():
        if run.project_id != hub.active_project_id:
            continue
        mine = [s for s in run.steps if str(s.role).upper() == aid and not s.server_side]
        fixed_issues = {s.issue_id for s in mine if s.kind == "fix"}
        fix_rounds += sum(1 for s in mine if s.kind == "fix")
        for s in mine:
            if s.kind not in ("task", "phase"):
                continue
            if s.status == "DONE":
                delivered += 1
                first_pass += 0 if s.issue_id in fixed_issues else 1
            elif s.status == "FAILED":
                failed += 1
    agent = hub.agents.get(aid) or {}
    versions = prompt_versions or []
    return {
        "agent_id": aid, "scope": scope_of(agent) if agent else None, "delivered": delivered, "first_pass": first_pass,
        "first_pass_rate": round(first_pass / delivered, 2) if delivered else None, "fix_rounds": fix_rounds, "failed_steps": failed,
        "tokens_in": int(agent.get("tokens_in", 0) or 0), "tokens_out": int(agent.get("tokens_out", 0) or 0), "total_tokens": int(agent.get("total_tokens", 0) or 0),
        "budget": (agent.get("profile") or {}).get("budget"), "prompt_versions": len(versions),
        "last_prompt_change": versions[0].get("created_at") if versions else None,
    }
