"""Hedefler (yönetici niyeti): FS-SC'nin "ne istediğimi yap" sözleşmesi.

Sorun (saha): sistem "Jira görevi kapandı mı?" diye ölçüyor, yöneticinin istediği şeyin gerçekten yapılıp yapılmadığını değil; sprint kuyruğunu eski backlog ve
mimarın yeniden açtığı işler dolduruyordu. Hedef modu:
1. Yönetici kısa hedefler yazar (`sprint_state["goals"]`); açık hedef varsa **kapsam dışı iş sprinte alınmaz** (`in_scope`).
2. Açık hedef varken mimar/PO/karar bölümü **yeni iş açmaz** (`pipeline._create_task_issues`); yönetici, tasarımcı (ekran/uyum) ve acil işler geçer.
3. Hedefin ölçülebilir bitişi vardır: `screens` hedefi için ekran uyumu denetimi (tüm ekranlar eşiği geçince biter); `free` hedefi yönetici kapatır.
4. İlerleme panoda görünür (`progress`).
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from . import sprint as SP

KINDS = ("screens", "free")
PASS_ORIGINS = {"MANAGER", "DESIGNER", "HUMAN"}         # hedef açıkken de iş açabilenler (yönetici elle, tasarım/uyum görevleri)


def _goals(hub) -> List[Dict[str, Any]]:
    return SP.ensure_state(hub).setdefault("goals", [])


def open_goals(hub) -> List[Dict[str, Any]]:
    return [g for g in _goals(hub) if g.get("status") == "OPEN"]


def add(hub, text: str, kind: str = "free") -> Dict[str, Any]:
    text = " ".join(str(text or "").split())
    if len(text) < 3:
        raise ValueError("Hedef metni boş olamaz.")
    if kind not in KINDS:
        raise ValueError(f"kind {KINDS} içinden olmalı.")
    goals = _goals(hub)
    n = 1 + max([int(re.sub(r"\D", "", g["id"]) or 0) for g in goals] or [0])
    g = {"id": f"G-{n}", "text": text[:500], "kind": kind, "status": "OPEN", "created_at": datetime.now(timezone.utc).isoformat(), "closed_at": None}
    goals.append(g)
    hub.mark_dirty()
    return g


def set_status(hub, goal_id: str, status: str) -> Dict[str, Any]:
    if status not in ("OPEN", "DONE", "DROPPED"):
        raise ValueError("status OPEN, DONE ya da DROPPED olmalı.")
    for g in _goals(hub):
        if g["id"] == goal_id:
            g["status"] = status
            g["closed_at"] = None if status == "OPEN" else datetime.now(timezone.utc).isoformat()
            hub.mark_dirty()
            return g
    raise KeyError(goal_id)


def in_scope(hub, issue: Dict[str, Any]) -> bool:
    """Açık hedef yoksa her iş uygundur. Varsa: ekran hedefi için tasarım ekranı/uyum işleri, yönetici işi, öne alınmış iş ya da hedefe etiketli iş."""
    goals = open_goals(hub)
    if not goals:
        return True
    if issue.get("expedite") or str(issue.get("origin") or "").upper() in PASS_ORIGINS:
        return True
    if issue.get("goal_id") in {g["id"] for g in goals}:
        return True
    return bool(issue.get("design_screen")) and any(g["kind"] == "screens" for g in goals)


def blocks_new_work(hub, origin: str) -> bool:
    """Açık hedef varken ya da ürün önce modunda açık backlog tavanı (`backlog_cap`) dolunca mimar/PO/karar bölümünün yeni iş açması engellenir."""
    if str(origin or "").upper() in PASS_ORIGINS:
        return False
    if open_goals(hub):
        return True
    st = hub.get_settings()
    if st.get("product_first"):
        cap = int(st.get("backlog_cap") or 25)
        open_backlog = sum(1 for i in hub.jira_issues.values() if str(i.get("kind", "")).lower() == "task" and i.get("status") == "BACKLOG" and not i.get("deleted"))
        return open_backlog >= cap
    return False


def progress(hub, goal: Dict[str, Any], report: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """{done, total, label}: screens → ekran uyumu denetimi (son rapor); free → yönetici kapatır."""
    if goal.get("kind") == "screens":
        screens = {str(i.get("design_screen")) for i in hub.jira_issues.values() if i.get("design_screen") and not i.get("deleted")}
        total = len(screens)
        passed = int((report or {}).get("passed") or 0) if report else 0
        open_tasks = sum(1 for i in hub.jira_issues.values() if i.get("design_screen") and not i.get("deleted") and i.get("status") != "DONE")
        return {"done": passed, "total": total, "open_tasks": open_tasks, "checked": bool(report)}
    return {"done": 1 if goal.get("status") == "DONE" else 0, "total": 1, "open_tasks": 0, "checked": True}


def on_fidelity(hub, report: Dict[str, Any]) -> List[str]:
    """Ekran uyumu denetimi sonrası: tüm ekranlar geçtiyse açık `screens` hedefleri kapanır."""
    closed: List[str] = []
    if report and report.get("total") and report.get("passed") == report.get("total"):
        for g in open_goals(hub):
            if g["kind"] == "screens":
                set_status(hub, g["id"], "DONE")
                closed.append(g["id"])
    return closed
