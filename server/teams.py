"""
Takımlar ve departmanlar (Petek topolojisi ve ofis odaları için ortak model).

Bir takım = bir projenin ajan grubu; departmanlar (Analiz / Yazılım / Test / Destek) altıgen kümelerdir.
Varsayılanlar DEPARTMENTS sabitinden türetilir; kullanıcı `POST /api/teams` ile üzerine yazabilir
(proje ayarlarında `settings["teams"]` olarak saklanır).
"""

from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional

from .i18n import translate as tx, N_

DEPARTMENTS: List[Dict[str, Any]] = [
    {"id": "ANALIZ", "label": N_("Analiz Ekibi"), "roles": ["PM", "PO", "ARCHITECT"], "color": "ac"},
    {"id": "YAZILIM", "label": N_("Yazılım Ekibi"), "roles": ["BACKEND_DEV", "FRONTEND_DEV", "DESIGNER", "SCM", "DEVOPS"], "color": "ok"},
    {"id": "TEST", "label": N_("Test Ekibi"), "roles": ["QA", "E2E_TESTER"], "color": "warn"},
    {"id": "DESTEK", "label": N_("Destek Ekibi"), "roles": ["REPORTER", "DOCUMENTOR"], "color": "info"},
]
FALLBACK_DEPARTMENT = "YAZILIM"


def default_team(project_id: str, project_name: str, agents: Dict[str, Dict[str, Any]], partners: Optional[List[str]] = None) -> Dict[str, Any]:
    """Projenin ajanlarını departmanlara dağıtarak varsayılan takımı üretir (bilinmeyen roller → YAZILIM)."""
    assigned = set()
    departments = []
    for dept in DEPARTMENTS:
        ids = []
        for role in dept["roles"]:
            for aid, agent in agents.items():
                if aid in assigned:
                    continue
                if aid == role or str(agent.get("role", "")).upper() == role:
                    ids.append(aid)
                    assigned.add(aid)
        departments.append({"id": dept["id"], "label": tx(dept["label"]), "color": dept["color"], "agent_ids": ids})
    leftovers = [aid for aid in agents if aid not in assigned]
    if leftovers:
        for d in departments:
            if d["id"] == FALLBACK_DEPARTMENT:
                d["agent_ids"].extend(leftovers)
    return {
        "id": f"team-{project_id}",
        "name": tx("{project_name} Ekibi", project_name=project_name),
        "project_id": project_id,
        "partners": list(partners or []),
        "departments": departments,
        "meeting_room": {"label": tx("Toplantı Odası")},
    }


def normalize_team(team: Dict[str, Any], agents: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """Kullanıcı tanımlı takımı doğrular: bilinmeyen departmanlar atılır, atanmamış ajanlar YAZILIM'a eklenir."""
    known = {d["id"]: d for d in DEPARTMENTS}
    out = copy.deepcopy(team)
    depts = []
    assigned = set()
    for d in out.get("departments", []) or []:
        did = str(d.get("id", "")).upper()
        if did not in known:
            continue
        ids = [str(a).upper() for a in d.get("agent_ids", []) if str(a).upper() in agents and str(a).upper() not in assigned]
        assigned.update(ids)
        depts.append({"id": did, "label": d.get("label") or tx(known[did]["label"]), "color": known[did]["color"], "agent_ids": ids})
    present = {d["id"] for d in depts}
    for d in DEPARTMENTS:
        if d["id"] not in present:
            depts.append({"id": d["id"], "label": tx(d["label"]), "color": d["color"], "agent_ids": []})
    leftovers = [aid for aid in agents if aid not in assigned]
    for d in depts:
        if d["id"] == FALLBACK_DEPARTMENT:
            d["agent_ids"].extend(leftovers)
    out["departments"] = depts
    out.setdefault("partners", [])
    out.setdefault("meeting_room", {"label": tx("Toplantı Odası")})
    return out


def teams_for_hub(hub, include_partners: bool = True) -> List[Dict[str, Any]]:
    """Aktif projenin takımı (ayarlardaki özel tanım veya varsayılan) + isteğe bağlı partner projelerin takımları."""
    pid = hub.active_project_id
    proj = hub.projects.get(pid, {})
    custom = (hub.get_settings().get("teams") or [])
    own = None
    for t in custom:
        if t.get("project_id") in (pid, None):
            own = normalize_team({**t, "project_id": pid}, hub.agents)
            break
    if own is None:
        own = default_team(pid, proj.get("name", pid), hub.agents, partners=[p for p in hub.projects if p != pid])
    teams = [own]
    if include_partners:
        for other_id, other in hub.projects.items():
            if other_id == pid:
                continue
            other_agents = other.get("agents") or {}
            partner = default_team(other_id, other.get("name", other_id), other_agents, partners=[pid])
            partner["read_only"] = True
            teams.append(partner)
    return teams
