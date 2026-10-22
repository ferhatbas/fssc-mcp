"""StepHandler kayıt defteri: adım sırası (order) → işleyici."""

from __future__ import annotations

from typing import Dict, Optional, Set

from ..i18n import translate as tx
from .base import StepHandler
from .handlers import ALL_HANDLERS
from .tasks import TaskHandler
from .flow import MeetingHandler, ReviewHandler, RescopeHandler, SprintCloseHandler, SprintPlanHandler, StructureHandler

STEP_HANDLERS: Dict[int, StepHandler] = {h.order: h for h in ALL_HANDLERS}
SERVER_SIDE_ORDERS: Set[int] = {h.order for h in ALL_HANDLERS if h.server_side}
CRITICAL_ORDERS: Set[int] = {h.order for h in ALL_HANDLERS if h.critical}


# (iş türü, rol) -> yeniden kullanılan faz işleyicisinin sırası (§7.2 tablosu)
PHASE_TEMPLATE_FOR = {("SCAFFOLD", "BACKEND_DEV"): 3, ("SCAFFOLD", "FRONTEND_DEV"): 4, ("DEVOPS", "*"): 8, ("DOCS", "*"): 10}


class GenericHandler(StepHandler):
    """Kayıtlı olmayan (kullanıcı tanımlı) Jira maddeleri için genel işleyici."""

    def __init__(self, order: int, agent_id: str, title: str):
        self.order = order
        self.agent_id = agent_id or "BACKEND_DEV"
        self.next_agent_id = "QA"
        self.action = "SUBMIT_CODE"
        self.title = title
        self.estimated_tokens = 250
        self.thinking = (
            tx("'{title}' görevi için teknik gereksinimleri ve dosya yapısını analiz ediyorum.", title=title),
            tx("'{title}' üzerinde çalışıyor", title=title),
            tx("Test ve doğrulama aşamasına geçilecek"),
        )
        self.payload_schema = {"files": [{"path": tx("göreli/dosya/yolu"), "content": "..."}]}

    def template_output(self, ctx):
        note = f"# {self.title}\n\n" + tx("Bu görev şablon motoruyla işaretlendi; gerçek içerik MCP istemcisi (Claude Desktop) tarafından üretilmelidir.") + "\n"
        return self.envelope(ctx, {
            "summary": tx("'{title}' görevi şablon motoruyla tamamlandı (yer tutucu çıktı).", title=self.title),
            "friendly_dialogue": tx("'{title}' görevini bitirdim, QA inceleyebilir.", title=self.title),
            "thinking": self.thinking[0], "what_doing": self.thinking[1], "what_next": self.thinking[2],
            "files": [{"path": f"<docs>/tasks/task_{self.order}.md", "content": note}],
        })


def get_handler(order: int, issue: Optional[dict] = None, record: Optional[object] = None) -> StepHandler:
    """
    Adım işleyicisini döner:
    - kayıt (StepRecord) 'task'/'fix' türündeyse veya Jira maddesi backlog görevi ise → TaskHandler (dinamik),
    - aksi halde order için kayıtlı faz işleyicisi (1-10), o da yoksa Jira maddesinden türetilen genel işleyici.
    """
    issue = issue or {}
    kind = str(getattr(record, "kind", "") or "").lower()
    # Sprint kipi akış adımları (F3)
    if kind == "plan":
        return SprintPlanHandler(int(order))
    if kind == "close":
        return SprintCloseHandler(int(order))
    if kind == "rescope":
        return RescopeHandler(int(order), issue)
    if kind == "review":
        return ReviewHandler(int(order), int(getattr(record, "sprint", 1) or 1))
    if kind == "meeting":
        return MeetingHandler(int(order), str(getattr(record, "work_type", "") or "planning"))
    if kind == "structure":
        return StructureHandler(int(order))
    # Faz işleyicileri iş türü şablonu olarak yeniden kullanılır (SCAFFOLD, DEVOPS, DOCS); düzeltme turları her zaman TaskHandler
    if kind == "task":
        wt = str(getattr(record, "work_type", "") or issue.get("work_type") or "").upper()
        role = str(issue.get("assignee") or "").upper()
        phase = PHASE_TEMPLATE_FOR.get((wt, role)) or PHASE_TEMPLATE_FOR.get((wt, "*"))
        if phase and phase in STEP_HANDLERS:
            return STEP_HANDLERS[phase]
    if kind in ("task", "fix") or str(issue.get("kind", "")).lower() == "task":
        return TaskHandler(int(order), issue, kind=kind or "task", fix_round=int(getattr(record, "fix_round", 0) or 0),
                           role=(getattr(record, "role", None) if kind == "fix" else None))
    h = STEP_HANDLERS.get(int(order))
    if h is not None:
        return h
    return GenericHandler(int(order), str(issue.get("assignee", "BACKEND_DEV")).upper(), issue.get("title", f"Task {order}"))
