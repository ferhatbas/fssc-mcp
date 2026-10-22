"""Jira hiyerarşisi: her iş (hikâye, görev, hata) oluşturulurken en uygun hikâyeye ya da epiğe bağlanır; hiçbir iş "ortada" kalmaz.

Çözüm sırası (`resolve_parent`): 1) zaten geçerli bir hikâye/epik ebeveyni varsa dokunma; 2) kabul kriteri kimliği (`ac_refs`) bir hikâyede geçiyorsa o hikâye (hikâyenin kendisi için o hikâyenin epiği);
3) bağımlı olduğu işin hikâyesi/epiği; 4) metinde anılan iş anahtarı (JIRA-n / DEV-n) ve onun ebeveyni; 5) başlık/açıklama benzerliği (en benzer hikâye, yoksa epik);
6) hiçbiri tutmazsa iş türüne göre sistem epiği: altyapı/belge/karar işleri "Platform, altyapı ve belgeler", hata/iyileştirme/test işleri "Kalite, hata ve iyileştirmeler".
Eşleşme bulunamayan özellik işi bağsız kalır (uydurma bağ kurulmaz). Eski işler yalnızca `link_orphans(apply=True)` ile (önce kuru plan) bağlanır;
yeni oluşan işler (kesim zamanından sonra) her adımın sonunda `link_recent_orphans` ile kendiliğinden bağlanır.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from . import sprint as SP
from . import i18n as I18N
from .i18n import translate as tx, N_

SYSTEM_EPICS = {
    "PLATFORM": (N_("Platform, altyapı ve belgeler"), N_("İskelet, DevOps, belge, karar uygulama ve refactor işleri: belirli bir kullanıcı hikâyesine ait olmayan teknik zemin.")),
    "QUALITY": (N_("Kalite, hata ve iyileştirmeler"), N_("QA/UAT/retro kaynaklı hata, iyileştirme ve test işleri.")),
}
PLATFORM_TYPES = {"SCAFFOLD", "DEVOPS", "DOCS", "REFACTOR", "DESIGN"}
QUALITY_TYPES = {"BUG", "IMPROVEMENT", "TEST", "E2E_SCENARIO", "TEST_DESIGN", "SECURITY_TEST", "PERF_SMOKE"}
SIMILARITY_MIN = 0.22
_KEY_RX = re.compile(r"\b(?:JIRA|DEV)-(\d+)\b", re.I)


def _live(hub) -> List[Dict[str, Any]]:
    return [i for i in hub.jira_issues.values() if not i.get("deleted")]


def _kind(i: Dict[str, Any]) -> str:
    t = str(i.get("issue_type") or "")
    if t == "EPIC":
        return "epic"
    if t in ("STORY", "FEATURE") and str(i.get("kind", "")).lower() != "task":
        return "story"
    return "task"


def _is_orphan(hub, i: Dict[str, Any]) -> bool:
    k = _kind(i)
    if k == "epic":
        return False
    parent = hub.jira_issues.get(i.get("parent_id") or "")
    if parent is None or parent.get("deleted"):
        return True
    pk = _kind(parent)
    return (pk != "epic") if k == "story" else (pk not in ("epic", "story"))


def _epic_of(hub, i: Optional[Dict[str, Any]]) -> Optional[str]:
    if i is None:
        return None
    k = _kind(i)
    if k == "epic":
        return i["id"]
    p = hub.jira_issues.get(i.get("parent_id") or "")
    if p is None:
        return None
    return p["id"] if _kind(p) == "epic" else (_epic_of(hub, p) if _kind(p) == "story" else None)


def _text(i: Dict[str, Any]) -> str:
    return " ".join(str(i.get(k) or "") for k in ("title", "description"))


def resolve_parent(hub, issue: Dict[str, Any]) -> Dict[str, Any]:
    """Önerilen ebeveyn: {parent_id, reason} ya da {system: 'PLATFORM'|'QUALITY', reason}; bulunamazsa {parent_id: None}. Hiçbir şeyi değiştirmez."""
    kind = _kind(issue)
    live = _live(hub)
    stories = [i for i in live if _kind(i) == "story" and i["id"] != issue["id"]]
    epics = [i for i in live if _kind(i) == "epic"]

    def attach(target: Optional[Dict[str, Any]], reason: str) -> Optional[Dict[str, Any]]:
        if target is None or _kind(target) not in ("story", "epic"):
            return None
        if kind == "story":                                    # hikâyenin ebeveyni epiktir
            eid = _epic_of(hub, target)
            return {"parent_id": eid, "reason": reason} if eid else None
        return {"parent_id": target["id"], "reason": reason}

    # 2) kabul kriteri kimliği
    refs = {str(a).upper() for a in (issue.get("ac_refs") or [])}
    if refs:
        def shared(st: Dict[str, Any]) -> set:
            return refs & {str(a).upper() for a in (st.get("ac_refs") or [])}
        hit = next((st for st in stories if st.get("origin") != "UAT" and shared(st)), None) or next((st for st in stories if shared(st)), None)
        r = attach(hit, tx("kabul kriteri {ids}", ids=', '.join(sorted(shared(hit))))) if hit else None
        if r:
            return r
    # 3) bağımlı olduğu iş
    for d in issue.get("depends_on") or []:
        dep = hub.jira_issues.get(d)
        if dep is not None:
            tgt = hub.jira_issues.get(dep.get("parent_id") or "") if kind != "story" else dep
            r = attach(tgt if tgt is not None and _kind(tgt) in ("story", "epic") else None, tx("bağımlı olduğu iş {key}", key=dep.get('key') or d))
            if r:
                return r
    # 4) metinde anılan iş anahtarı
    for m in _KEY_RX.finditer(_text(issue)):
        ref = hub.jira_issues.get(f"JIRA-{m.group(1)}")
        if ref is not None and ref["id"] != issue["id"]:
            tgt = ref if _kind(ref) in ("story", "epic") else hub.jira_issues.get(ref.get("parent_id") or "")
            r = attach(tgt if tgt is not None and _kind(tgt) in ("story", "epic") else None, tx("metinde anılan {key}", key=ref.get('key') or ref['id']))
            if r:
                return r
    # 5) benzerlik
    toks = SP._title_tokens(_text(issue))
    if len(toks) >= 3:
        def score(c: Dict[str, Any]) -> float:
            ct = SP._title_tokens(_text(c))
            return len(toks & ct) / max(1, len(toks | ct)) if ct else 0.0
        pool = epics if kind == "story" else (stories + epics)
        best = max(pool, key=score, default=None)
        if best is not None and score(best) >= SIMILARITY_MIN:
            r = attach(best, tx("başlık/açıklama benzerliği ({key})", key=best.get('key') or best['id']))
            if r:
                return r
    # 6) sistem epiği
    wt = str(issue.get("work_type") or "").upper()
    origin = str(issue.get("origin") or "").upper()
    if kind != "story":
        if wt in PLATFORM_TYPES or origin == "DECISION":
            return {"system": "PLATFORM", "reason": tx("teknik zemin işi")}
        if wt in QUALITY_TYPES or origin in ("RETRO", "QA", "UAT", "PO"):
            return {"system": "QUALITY", "reason": tx("kalite/hata/iyileştirme işi")}
    elif origin in ("UAT", "PO"):
        return {"system": "QUALITY", "reason": tx("UAT kaynaklı hikâye")}
    return {"parent_id": None, "reason": tx("eşleşen epik/hikâye bulunamadı")}


async def ensure_system_epic(hub, key: str) -> str:
    """Sistem epiğini (yoksa) açar ve kimliğini döner."""
    src_title, src_desc = SYSTEM_EPICS[key]
    title, desc = tx(src_title), tx(src_desc)
    for i in _live(hub):
        if i.get("issue_type") == "EPIC" and I18N.matches(i.get("title"), src_title):      # eşleştirme dilden bağımsız: proje dili değişse de aynı sistem epiği bulunur
            return i["id"]
    order = max([int(i.get("order", 0) or 0) for i in hub.jira_issues.values()] or [0]) + 1
    iid = f"JIRA-{order}"
    await hub.update_jira_issue(iid, {"order": order, "title": title, "description": desc, "issue_type": "EPIC", "kind": "epic", "status": "IN_PROGRESS", "priority": "P1",
                                      "assignee": "PM", "origin": "SYSTEM", "acceptance_criteria": [], "audit_action": "EPIC_CREATED",
                                      "audit_notes": tx("Sistem epiği: bir epiğe bağlanamayan işlerin ortak çatısı.")})
    return iid


async def _set_parent(hub, issue: Dict[str, Any], parent_id: str, reason: str, by: str = "SYSTEM") -> None:
    """Yalnızca hiyerarşi bağını kurar (dondurulmuş maddede de; denetime işlenir)."""
    from . import jira_plus as JP
    issue.setdefault("history", [])
    old = issue.get("parent_id")
    issue["parent_id"] = parent_id
    issue["parent_linked"] = True
    JP._hist(issue, by, "parent_id", old, parent_id)
    await JP._touch(hub, issue, by, "PARENT_LINKED", tx("ebeveyn: {old} → {parent_id} ({reason})", old=old or '—', parent_id=parent_id, reason=reason))


async def link_issue(hub, issue_id: str, apply: bool = True) -> Optional[Dict[str, Any]]:
    issue = hub.jira_issues.get(issue_id)
    if issue is None or issue.get("deleted") or not _is_orphan(hub, issue):
        return None
    res = resolve_parent(hub, issue)
    pid = res.get("parent_id")
    if res.get("system") and apply:
        pid = await ensure_system_epic(hub, res["system"])
    elif res.get("system"):
        pid = tx("(sistem epiği: {title})", title=tx(SYSTEM_EPICS[res['system']][0]))
    out = {"id": issue_id, "key": issue.get("key"), "title": str(issue.get("title") or "")[:80], "parent_id": pid, "reason": res.get("reason")}
    if pid and apply:
        await _set_parent(hub, issue, pid, res.get("reason") or "")
    elif apply:
        issue["parent_linked"] = True                                    # bulunamadı: aynı iş tekrar tekrar denenmez
    return out


async def link_orphans(hub, apply: bool = False) -> Dict[str, Any]:
    """Tüm bağsız işler için plan (kuru) ya da uygulama. Eşleşme bulunamayanlar `unresolved` sayılır."""
    plan: List[Dict[str, Any]] = []
    for i in sorted(_live(hub), key=lambda x: int(x.get("order", 0) or 0)):
        if _kind(i) != "epic" and _is_orphan(hub, i):
            row = await link_issue(hub, i["id"], apply=apply)
            if row:
                plan.append(row)
    linked = [p for p in plan if p["parent_id"]]
    if apply:
        hub.mark_dirty()
    return {"applied": apply, "total": len(plan), "linked": len(linked), "unresolved": len(plan) - len(linked), "plan": plan}


def cutoff(hub) -> str:
    st = SP.ensure_state(hub)
    if not st.get("hierarchy_cutoff"):
        st["hierarchy_cutoff"] = datetime.now(timezone.utc).isoformat()
        hub.mark_dirty()
    return st["hierarchy_cutoff"]


async def link_recent_orphans(hub, limit: int = 30) -> int:
    """Kesim zamanından sonra oluşan, henüz denenmemiş bağsız işleri bağlar (her adımın sonunda). Eski işlere dokunmaz."""
    cut = cutoff(hub)
    n = 0
    for i in _live(hub):
        if n >= limit:
            break
        if i.get("parent_linked") or str(i.get("created_at") or "") < cut or _kind(i) == "epic" or not _is_orphan(hub, i):
            continue
        if await link_issue(hub, i["id"], apply=True):
            n += 1
    return n
