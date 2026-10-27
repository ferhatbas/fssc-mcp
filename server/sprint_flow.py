"""Sprint kipi akış adımları (F3): sprint planı/taahhüdü, kapanış (review-retro), yeniden kapsamlama ve koşu kurulumu.

`pipeline.run_server_step` plan ve kapanış kayıtlarını buraya yönlendirir. Bu adımların Jira maddesi yoktur (`issue_id=SPRINT-n`);
durumları `hub.sprint_state` (kalıcı: `.fs-workspace/sprint_state.json`) ve `FS-docs/sprints/sprint-n.json` içindedir.
"""
from __future__ import annotations

import asyncio

NL = chr(10)
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

from . import learning as L
from .i18n import translate as tx, N_
from . import meetings as M
from . import pipeline as P
from . import quality as Q
from . import scm as SCM
from . import sprint as SP
from .paths import hub_docs_path
from .runs import PipelineRun, StepRecord
from .steps import SERVER_SIDE_ORDERS

REVIEW_GATES = (5, 6, 7, 9)   # sözleşme uyumu, QA, E2E, PO kabulü (§7.3); ARCHITECT gözden geçirmesi F6'da eklenir


def _iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _minutes(a: Optional[str], b: Optional[str]) -> float:
    try:
        return max(0.0, (datetime.fromisoformat(b) - datetime.fromisoformat(a)).total_seconds() / 60.0)
    except Exception:
        return 0.0


def new_plan_record(n: Optional[int]) -> StepRecord:
    order = SP.plan_order(n) if n else SP.PLAN_BASE
    return StepRecord(order=order, issue_id=f"SPRINT-{n or 0}", role="SCRUM_MASTER", kind="plan", server_side=True,
                      title=tx("Sprint planı ve taahhüdü"), sprint=n)


def new_review_record(n: int) -> StepRecord:
    return StepRecord(order=SP.review_order(n), issue_id=f"SPRINT-{n}", role="ARCHITECT", kind="review", title=tx("Sprint {n}: kod ve mimari gözden geçirme", n=n), sprint=n)


def _queued_step(hub, issue_id: str, statuses=("PENDING",)):
    """İşin etkin (ya da sürdürülebilir) koşuda BAŞLAMAMIŞ görev adımı varsa (run, step); yoksa None."""
    from . import driver as DRV
    pid = hub.active_project_id
    run = hub.active_run_for(pid) or next(iter(DRV.abandoned_runs(hub, pid)), None)
    if run is None or run.mode != "sprint":
        return None
    step = next((s for s in run.steps if s.issue_id == issue_id and s.kind in ("task", "fix") and s.status in statuses), None)
    return (run, step) if step is not None else None


async def _move_queued_step(hub, issue: Dict[str, Any], run: PipelineRun, step: StepRecord) -> Dict[str, Any]:
    """Planlanmış sprintin kuyruğundaki işi geçerli adımın hemen arkasına taşır ("Önce yap"): kapsam değişmez, yalnızca sıra değişir."""
    idx = run.steps.index(step)
    cur = run.cursor
    if idx <= cur + 1:
        await hub.update_jira_issue(issue["id"], {"expedite": "now", "audit_action": "EXPEDITED", "audit_notes": tx("Yönetici işi önce yapılacak olarak işaretledi (zaten sıradaki adım).")})
        return {"mode": "now", "moved": False, "run_id": run.run_id, "order": step.order, "message": tx("İş zaten sıradaki adım.")}
    run.steps.pop(idx)
    run.steps.insert(min(cur + 1, len(run.steps)), step)
    await hub.update_jira_issue(issue["id"], {"expedite": "now", "audit_action": "EXPEDITED",
                                              "audit_notes": tx("Yönetici işi önce yapılacak olarak kuyruğun başına aldı (adım #{order}, sıra {from_pos} → {to_pos}).", order=step.order, from_pos=idx + 1, to_pos=min(cur + 1, len(run.steps)) + 1)})
    await hub.record_event(trace_id=run.run_id, from_agent="MANAGER", to_agent=step.role, action="QUEUE_REORDERED", status="SUCCESS",
                           payload={"issue": issue["id"], "order": step.order, "from": idx + 1},
                           friendly_dialogue=tx("Yönetici {id} işini kuyruğun başına aldı: geçerli adımdan hemen sonra yapılacak.", id=issue["id"]))
    run.touch()
    await P.publish_run(hub, run)
    hub.mark_dirty()
    return {"mode": "now", "moved": True, "run_id": run.run_id, "order": step.order, "from_position": idx + 1, "warnings": []}


async def expedite_issue(hub, issue_id: str, mode: Optional[str]) -> Dict[str, Any]:
    """Yöneticinin işi öne alması. `mode`:
    - `next_sprint`: sıradaki sprintin başına (planlamada her şeyden önce seçilir; kapasite sınırı yine geçerlidir);
    - `now` ("önce yap"): çalışan (ya da sürdürülebilir) sprint koşusunda geçerli adımdan HEMEN sonra bu iş yapılır; sprint kapsamına eklenir ve `scope_changes`e yazılır
      (kapasiteyi aşarsa uyarı döner, engellemez: yönetici kararıdır). Çalışan sprint koşusu yoksa `next_sprint`e düşer (`fallback`);
    - boş/`none`: bayrak kaldırılır.
    Yalnızca backlog'daki, henüz bir sprinte alınmamış iş öne alınabilir. Gerçek eşzamanlı (paralel) koşu yoktur: tek koşu sırayla yürür."""
    issue = hub.jira_issues.get(issue_id)
    if issue is None:
        raise KeyError(issue_id)
    mode = (mode or "").strip().lower()
    mode = None if mode in ("", "none", "normal") else mode
    if mode not in (None, "now", "next_sprint"):
        raise ValueError(tx("expedite 'now', 'next_sprint' ya da boş olmalı."))
    queued = _queued_step(hub, issue_id)
    if queued is not None and mode == "now":
        return await _move_queued_step(hub, issue, *queued)
    if queued is not None and mode == "next_sprint":
        raise PermissionError(tx("Bu iş zaten planlanmış bir sprintin kuyruğunda; sıranın başına almak için 'Önce yap' (şimdi) seçin."))
    if issue.get("status") != "BACKLOG" or issue.get("sprint") or issue.get("deleted"):
        raise PermissionError(tx("Yalnızca backlog'daki ve henüz bir sprinte alınmamış iş öne alınabilir."))

    if str(issue.get("kind", "")).lower() != "task":
        if issue.get("issue_type") in ("TASK", "BUG"):
            await hub.update_jira_issue(issue_id, {"kind": "task", **({} if issue.get("work_type") else {"work_type": SP.default_work_type(issue)})})       # panodan elle girilen iş de sprint adımı olabilsin
        else:
            raise ValueError(tx("Yalnızca görev (task) ve hata (bug) işleri öne alınabilir; epik/hikâye değil."))
    if mode is None:
        await hub.update_jira_issue(issue_id, {"expedite": None, "audit_action": "EXPEDITE_CLEARED", "audit_notes": tx("Yönetici öncelik şeridini kaldırdı.")})
        return {"mode": None}
    if mode == "next_sprint":
        await hub.update_jira_issue(issue_id, {"expedite": "next_sprint", "audit_action": "EXPEDITE_NEXT_SPRINT",
                                               "audit_notes": tx("Yönetici işi sıradaki sprintin başına aldı.")})
        return {"mode": "next_sprint", "fallback": False}
    # mode == "now"
    from . import driver as DRV
    pid = hub.active_project_id
    run = hub.active_run_for(pid) or next(iter(DRV.abandoned_runs(hub, pid)), None)
    cur = run.current_step if run is not None else None
    n = int(cur.sprint or 0) if cur is not None and cur.sprint else int((open_sprint(hub) or {}).get("sprint_number") or 0)
    sp = SP.get_sprint(hub, n) if n else None
    if run is None or run.mode != "sprint" or sp is None or (run.is_terminal and run.status != "ABANDONED"):
        await hub.update_jira_issue(issue_id, {"expedite": "next_sprint", "audit_action": "EXPEDITE_NEXT_SPRINT",
                                               "audit_notes": tx("Çalışan sprint koşusu yok: iş sıradaki sprintin başına alındı.")})
        return {"mode": "next_sprint", "fallback": True, "reason": tx("Çalışan sprint koşusu yok; iş sıradaki sprintin başına alındı.")}
    if run.has_order(int(issue["order"])):
        raise ValueError(tx("Bu iş koşuda zaten bir adım olarak var."))
    rec = StepRecord(order=int(issue["order"]), issue_id=issue["id"], role=issue.get("assignee") or "BACKEND_DEV", kind="task",
                     title=issue.get("title", ""), round=n, work_type=issue.get("work_type") or "", sprint=n)
    run.insert_before_order([rec], 5)
    sp.setdefault("committed_issue_ids", []).append(issue["id"])
    warnings: List[str] = []
    cap = int(SP.cfg(hub).get("max_tasks") or 0)
    if cap and len(sp["committed_issue_ids"]) > cap:
        warnings.append(tx("Sprint {n} kapasitesi ({cap}) aşıldı: yönetici kararıyla eklendi.", n=n, cap=cap))
    done = {k for k, v in hub.jira_issues.items() if v.get("status") == "DONE"}
    unmet = [d for d in (issue.get("depends_on") or []) if d not in done and d not in sp["committed_issue_ids"]]
    if unmet:
        warnings.append(tx("Tamamlanmamış bağımlılık: ") + ", ".join(unmet))
    sp.setdefault("scope_changes", []).append({"at": _iso(), "source": "expedite", "removed": [], "added": [issue["id"]]})
    await hub.update_jira_issue(issue_id, {"sprint": n, "expedite": "now", "audit_action": "EXPEDITED",
                                           "audit_notes": tx("Yönetici işi önce yapılacak olarak Sprint {n} koşusuna ekledi (adım #{order}, geçerli adımdan hemen sonra).", n=n, order=rec.order)})
    await hub.record_event(trace_id=run.run_id, from_agent="MANAGER", to_agent=rec.role, action="SCOPE_CHANGED", status="SUCCESS",
                           payload={"sprint": n, "added": [issue["id"]], "removed": [], "expedite": True},
                           friendly_dialogue=tx("Yönetici {id} işini öne aldı: Sprint {n} koşusunda geçerli adımdan hemen sonra yapılacak.", id=issue["id"], n=n))
    await hub.broadcast({"type": "SCOPE_CHANGED", "sprint": n, "added": [issue["id"]], "removed": []})
    run.touch()
    await P.publish_run(hub, run)
    hub.mark_dirty()
    return {"mode": "now", "fallback": False, "run_id": run.run_id, "sprint": n, "order": rec.order, "warnings": warnings}


_ROLE_HINTS = (
    ("DEVOPS", r"docker|compose|container|konteyner|dağıtım|deploy|ci/cd|pipeline kur|yayın ortam"),
    ("QA", r"\btest\b|senaryo|e2e|kapsam testi|regresyon"),
    ("DESIGNER", r"tasarım sistemi|mockup|wireframe|prototip|ux\b|görsel tasarım"),
    ("FRONTEND_DEV", r"arayüz|\bui\b|ekran|react|frontend|tasarım|responsive"),
    ("DOCUMENTOR", r"belge|döküman|dokuman|kılavuz|readme"),
)
INTAKE_TASK_MAX_CHARS = 600        # bundan uzun yönetici girdisi şartname sayılır (PM değerlendirir); kısası doğrudan iş olur


def _guess_role(text: str) -> str:
    import re
    low = text.lower()
    for role, rx in _ROLE_HINTS:
        if re.search(rx, low):
            return role
    return "BACKEND_DEV"


async def create_manager_task(hub, text: str, spec_id: Optional[str] = None, urgent: bool = False, *, role: Optional[str] = None, work_type: Optional[str] = None,
                              title: Optional[str] = None, description: Optional[str] = None, criteria: Optional[List[str]] = None) -> Optional[Dict[str, Any]]:
    """Kısa bir yönetici girdisinden doğrudan backlog işi açar (kind=task, origin=MANAGER) ve panoda hemen görünür olur.
    Rol metinden tahmin edilir; açıklama ve kabul kriteri `adopt_manual_tasks` ile taslak olarak doldurulur (needs_grooming). `urgent` ise iş
    çalışan sprint koşusunda geçerli adımdan hemen sonra yapılacak şekilde öne alınır (yoksa sıradaki sprintin başına). Zaten benzer açık iş varsa yenisi açılmaz."""
    import re
    text = " ".join(str(text or "").split())
    if not text or len(text) > INTAKE_TASK_MAX_CHARS or not SP.enabled(hub):
        return None
    title = (title or re.split(r"(?<=[.!?;])\s", text, maxsplit=1)[0].strip(" .;"))[:160] or text[:100]
    toks = SP._title_tokens(title)
    for i in hub.jira_issues.values():
        if str(i.get("kind", "")).lower() == "task" and not i.get("deleted") and i.get("status") != "DONE" and len(toks) >= 3 and len(toks & SP._title_tokens(i.get("title"))) / max(1, len(toks | SP._title_tokens(i.get("title")))) >= 0.8:
            return {"issue_id": i["id"], "key": i.get("key"), "existing": True, "title": i.get("title")}
    role = role or _guess_role(text)
    bug = not work_type and bool(re.search(r"\bhata\b|\bbug\b|çöküyor|düzelt", text.lower()))
    order = max([int(i.get("order", 0) or 0) for i in hub.jira_issues.values()] or [0]) + 1
    iid = f"JIRA-{order}"
    await hub.update_jira_issue(iid, {
        "order": order, "title": title, "description": description or tx("Yönetici girdisi{spec}: {text}", spec=f" ({spec_id})" if spec_id else "", text=text), "issue_type": "BUG" if bug else "TASK",
        "status": "BACKLOG", "priority": "P0" if urgent else "P1", "assignee": role, "kind": "task", "origin": "MANAGER",
        "work_type": work_type or ("BUG" if bug else SP.ROLE_WORK_TYPE.get(role, "FEATURE")),
        **({"acceptance_criteria": list(criteria)} if criteria else {}),
        "task_key": SP.next_key(hub, "T"), "audit_action": "TASK_CREATED", "audit_notes": tx("Yönetici girdisinden otomatik iş açıldı.")})
    SP.adopt_manual_tasks(hub)
    out: Dict[str, Any] = {"issue_id": iid, "key": hub.jira_issues[iid].get("key"), "title": title, "role": role, "existing": False}
    try:
        out["expedite"] = await expedite_issue(hub, iid, "now" if urgent else "next_sprint")
    except (ValueError, PermissionError, KeyError) as e:
        out["expedite"] = {"mode": None, "error": str(e)}
    return out


async def plan_review_for_blocked(hub, n: int) -> Dict[str, Any]:
    """PRECONDITION_LOST (mimar gözden geçirmesi yok) ile BLOCKED sprint için ARCHITECT gözden geçirmesini bir koşuya ekler: etkin koşu ya da en ilerlemiş
    terk edilmiş MCP koşusu (imleçten sonra). Adım bitince sprint kendiliğinden kapanır (quality.settle_blocked_sprint)."""
    sp = SP.get_sprint(hub, n)
    if sp is None or sp.get("status") != "BLOCKED" or (sp.get("blocked") or {}).get("reason") != "PRECONDITION_LOST":
        raise ValueError(tx("Sprint {n} mimar gözden geçirmesi yüzünden engelli değil.", n=n))
    if (sp.get("arch_review") or {}).get("done"):
        raise ValueError(tx("Gözden geçirme zaten yapılmış; 'Engeli kaldır' ile sprinti sürdürün."))
    from . import driver as DRV
    pid = hub.active_project_id
    run = hub.active_run_for(pid) or next(iter(DRV.abandoned_runs(hub, pid)), None)
    if run is None or (run.is_terminal and run.status != "ABANDONED"):      # terk edilmiş koşu sürdürülünce eklenen adımı çalıştırır
        raise ValueError(tx("Gözden geçirmeyi ekleyecek koşu yok: önce koşuyu başlatın ya da sürdürün, sonra tekrar deneyin."))
    existing = next((s for s in run.steps if s.kind == "review" and s.sprint == n), None)
    if existing is not None and existing.status in ("PENDING", "ACTIVE", "WAITING_APPROVAL"):
        return {"run_id": run.run_id, "order": existing.order, "already_planned": True}
    rec = new_review_record(n)
    if existing is not None:                          # aynı koşuda bu sprintin gözden geçirmesi zaten çalışmış ama sprint hâlâ engelli: yeni koşu gerekir
        raise ValueError(tx("Bu koşuda sprint {n} gözden geçirmesi zaten çalıştı ({status}); sonuç sprinti kapatmadı. Yeni bir koşu başlatıp tekrar deneyin.", n=n, status=existing.status))
    run.insert_after_cursor([rec])
    sp["blocked"]["review_planned"] = {"run_id": run.run_id, "order": rec.order, "at": _iso()}
    await hub.record_event(trace_id=run.run_id, from_agent="SCRUM_MASTER", to_agent="ARCHITECT", action="ARCH_REVIEW_PLANNED", status="IN_PROGRESS",
                           payload={"sprint": n, "order": rec.order}, friendly_dialogue=tx("Sprint {n} için eksik mimar gözden geçirmesini koşuya ekledim (adım #{order}).", n=n, order=rec.order))
    run.touch()
    await P.publish_run(hub, run)
    hub.mark_dirty()
    return {"run_id": run.run_id, "order": rec.order, "already_planned": False}


def new_close_record(n: int) -> StepRecord:
    return StepRecord(order=SP.close_order(n), issue_id=f"SPRINT-{n}", role="SCRUM_MASTER", kind="close", server_side=True,
                      title=tx("Sprint {n} kapanışı (review-retro)", n=n), sprint=n)


def new_meeting_record(n: int, mtype: str) -> StepRecord:
    titles = {"kickoff": N_("Kickoff toplantısı"), "planning": N_("Sprint planlama toplantısı"), "review-retro": N_("Değerlendirme ve retrospektif")}
    return StepRecord(order=SP.meeting_order(n, mtype), issue_id=f"SPRINT-{n}", role="SCRUM_MASTER", kind="meeting", work_type=mtype,
                      title=tx("Sprint {n}: {title}", n=n, title=tx(titles[mtype]) if mtype in titles else mtype), sprint=n)


def planning_meeting_type(hub) -> str:
    """Sprint 1 öncesi `kickoff`, sonrası `planning` (§8.1)."""
    return "kickoff" if not any(s["status"] in ("CLOSED", "BLOCKED") for s in SP.ensure_state(hub)["sprints"]) else "planning"


def rescope_records(hub) -> List[StepRecord]:
    """FIX_LIMIT / TOKEN_LIMIT ile taşınan işler için ARCHITECT yeniden kapsamlama adımları (taahhütten önce zorunlu)."""
    out = []
    for i in sorted(hub.jira_issues.values(), key=lambda x: int(x.get("order", 0) or 0)):
        if str(i.get("kind", "")).lower() == "task" and i.get("needs_rescope") and i.get("status") == "BACKLOG":
            out.append(StepRecord(order=int(i["order"]), issue_id=i["id"], role="ARCHITECT", kind="rescope",
                                  title=tx("Yeniden kapsamlama: {title}", title=i.get("title", ""))[:140], work_type=i.get("work_type") or ""))
    return out


def sprint_step_records(hub, n: int, items: List[Dict[str, Any]]) -> List[StepRecord]:
    """Bir sprintin görev adımları + inceleme kapıları + review-retro toplantısı + kapanış (taahhütte ve sürdürmede aynı liste)."""
    records: List[StepRecord] = []
    for i in items:
        records.append(StepRecord(order=int(i["order"]), issue_id=i["id"], role=i.get("assignee") or "BACKEND_DEV", kind="task",
                                  title=i.get("title", ""), round=n, work_type=i.get("work_type") or "", sprint=n))
    for order in REVIEW_GATES:
        if order == 9 and Q.strict(hub):
            records.append(new_review_record(n))     # sıkı DoD: ARCHITECT gözden geçirmesi PO kabulünden önce (§7.3, §7.7)
        gate_issue = hub.jira_issues.get(f"JIRA-{order}")
        if gate_issue:
            records.append(StepRecord(order=order, issue_id=gate_issue["id"], role=gate_issue.get("assignee", "QA"), kind="phase",
                                      title=gate_issue.get("title", ""), round=n, sprint=n, server_side=order in SERVER_SIDE_ORDERS))
    records.append(new_meeting_record(n, "review-retro"))
    records.append(new_close_record(n))
    return records


def open_sprint(hub) -> Optional[Dict[str, Any]]:
    """Taahhüt edilmiş ama kapanmamış sprint: koşusu kalmadıysa (iptal/yitik) yenisi planlanmaz, bu sprint sürdürülür."""
    open_ones = [s for s in SP.ensure_state(hub)["sprints"] if s["status"] in ("COMMITTED", "IN_PROGRESS", "REVIEW")]
    return max(open_ones, key=lambda s: s["sprint_number"]) if open_ones else None


def resume_records(hub, sp: Dict[str, Any]) -> List[StepRecord]:
    """Açık sprintin kalan adımları: taahhüt edilen işlerden bitmemiş olanlar + kapılar + retro + kapanış (kickoff/plan tekrarlanmaz)."""
    items = []
    for iid in sp.get("committed_issue_ids") or []:
        issue = hub.jira_issues.get(iid)
        if issue and issue.get("status") != "DONE" and not issue.get("deleted"):
            items.append(issue)
    return sprint_step_records(hub, int(sp["sprint_number"]), items)


def build_sprint_run(hub, project_id: str, project_dir: str, engine: str, step_by_step: bool, with_intake: bool = True,
                     spec_ids: Optional[List[str]] = None, custom_prompt: str = "") -> PipelineRun:
    """Yükleme sonrası değerlendirmeyle başlayan dinamik koşu: PM → ARCHITECT → (yeniden kapsamlama) → sprint planı.
    Açık (taahhütlü, kapanmamış) sprint varsa plan yerine o sprintin kalan adımları gelir: iş baştan başlamaz, sprint N+1 planlanmaz."""
    steps: List[StepRecord] = []
    if with_intake:
        steps.append(StepRecord(order=1, issue_id="JIRA-1", role="PM", kind="phase", title=(hub.jira_issues.get("JIRA-1") or {}).get("title", tx("Değerlendirme"))))
        steps.append(StepRecord(order=2, issue_id="JIRA-2", role="ARCHITECT", kind="phase", title=(hub.jira_issues.get("JIRA-2") or {}).get("title", tx("Yapılandırma"))))
    steps += rescope_records(hub)
    sp_open = open_sprint(hub)
    if sp_open is not None:
        steps += resume_records(hub, sp_open)
    else:
        n = SP.last_sprint_number(hub) + 1
        steps.append(new_meeting_record(n, planning_meeting_type(hub)))
        steps.append(new_plan_record(n))
    run = PipelineRun(project_id=project_id, project_dir=project_dir, engine=engine, steps=steps, step_by_step=step_by_step,
                      mode="sprint", intake_spec_ids=list(spec_ids or []), custom_prompt=custom_prompt or "")
    if sp_open is not None and run.run_id not in sp_open["run_ids"]:
        sp_open["run_ids"].append(run.run_id)
    return run


# ---------------------------------------------------------------------------
# Sprint planı / taahhüt
# ---------------------------------------------------------------------------
async def run_plan_step(hub, run: PipelineRun, record: StepRecord) -> "P.StepOutcome":
    project_dir = P.project_dir_for(hub, run)
    c = SP.cfg(hub)
    n = record.sprint or (SP.last_sprint_number(hub) + 1)
    record.sprint = n
    record.order = SP.plan_order(n)
    record.issue_id = f"SPRINT-{n}"
    sp = SP.get_sprint(hub, n)
    now = _iso()
    if record.status != "WAITING_APPROVAL" and not record.started_at:
        record.started_at = now
    record.status = "ACTIVE"
    run.status = "ACTIVE"
    hub.active_run_id = run.run_id

    await M.expire_questions(hub)    # süresi dolan teknoloji dışı sorular önerilen cevapla DEFAULTED olur (§3.3)
    await ensure_design_task(hub)    # arayüz işi var ama tasarım yoksa: frontend'den ÖNCE tasarım görevi (yönetici onaylı)

    if sp is None:
        cap, basis = SP.capacity(hub)
        items, out = _proposal(hub, n, cap)
        if not items:
            return await _no_work(hub, run, record, n)
        for old in SP.ensure_state(hub)["sprints"]:
            if old["status"] == "PLANNING":
                old["status"] = "CANCELLED"     # yarım kalmış önceki planlama
        goal = (SP.ensure_state(hub)["meeting_commitments"].get(str(n)) or {}).get("goal") or SP.goal_for(hub, items, n)
        sp = SP.new_sprint(hub, n, str(goal)[:300])
        sp["meetings"]["planning"] = next((m["file"] for m in reversed(SP.ensure_state(hub)["meetings"])
                                           if m["sprint"] == n and m["type"] in ("kickoff", "planning")), None)
        sp["proposed_issue_ids"] = [i["id"] for i in items]
        sp["out_of_scope"] = out
        sp["capacity"] = {"max_tasks": cap, "basis": basis}
        sp["run_ids"].append(run.run_id)
        await hub.set_agent_status("SCRUM_MASTER", "WORKING", what_doing=tx("Sprint {n} planlanıyor", n=n))
        await hub.record_event(
            trace_id=run.run_id, from_agent="SCRUM_MASTER", to_agent="PM", action="SPRINT_PLANNED", status="SUCCESS",
            payload={"sprint": n, "goal": sp["goal"], "items": sp["proposed_issue_ids"], "capacity": sp["capacity"], "out_of_scope": out},
            friendly_dialogue=tx("Sprint {n} taslağı hazır: {count} iş. Kapasite: {basis}", n=n, count=len(items), basis=basis),
            what_doing=tx("Sprint kapsamını seçti"), what_next=tx("Taahhüt onayı"))
        await hub.broadcast({"type": "SPRINT_PLANNED", "sprint": n, "goal": sp["goal"], "items": sp["proposed_issue_ids"]})
    elif run.run_id not in sp["run_ids"]:
        sp["run_ids"].append(run.run_id)

    # Engelleyici soru açıksa sprint BLOCKED (BLOCKING_QUESTION); yönetici cevaplayana kadar hiçbir adım ilerlemez (§3.4)
    blockers = M.open_blocking(hub)
    if blockers:
        SP.set_sprint_status(hub, sp, "BLOCKED", blocked={"reason": "BLOCKING_QUESTION", "since": now, "previous_status": "PLANNING",
                                                          "detail": ", ".join(b["id"] for b in blockers)})
        info = {"kind": "questions", "run_id": run.run_id, "order": record.order, "issue_id": record.issue_id, "title": tx("Engelleyici sorular"),
                "agent_id": "SCRUM_MASTER", "agent_name": "Scrum Master", "agent_role": "SCRUM_MASTER", "next_agent_id": "BACKEND_DEV", "next_agent_name": "",
                "action": "BLOCKING_QUESTION", "summary": tx("Sprint {n} engelleyici soru(lar) nedeniyle bekliyor: ", n=n) + ", ".join(b["id"] for b in blockers),
                "artifacts": [], "screenshots": [], "tokens_used": 0, "timestamp": now, "is_last_step": False, "engine": run.engine, "status": "SUCCESS",
                "questions": [{k: v for k, v in b.items() if k != "adr_draft"} for b in blockers]}
        token = hub.open_step_approval(info)
        run.approval_token, run.gate_kind, run.status, record.status = token, "questions", "WAITING_APPROVAL", "WAITING_APPROVAL"
        await hub.broadcast({"type": "SPRINT_BLOCKED", "sprint": n, "reason": "BLOCKING_QUESTION", "questions": [b["id"] for b in blockers]})
        await hub.broadcast({"type": "STEP_WAITING_APPROVAL", "step_info": hub.pending_step_approval})
        await P.publish_run(hub, run)
        return P.StepOutcome(status="WAITING_APPROVAL", approval_token=token, message=tx("Sprint {n} engelleyici soru bekliyor.", n=n))
    if sp.get("blocked") and sp["blocked"].get("reason") == "BLOCKING_QUESTION":
        SP.set_sprint_status(hub, sp, sp["blocked"].get("previous_status") or "PLANNING", blocked=None)
        await hub.broadcast({"type": "SPRINT_UNBLOCKED", "sprint": n})

    # Taahhüt onayı: manual yönetici onayı bekler; timeout_default süre dolunca (autonomy.question_timeout_s) sunucu taahhüt eder (by: TIMEOUT), süre 0 ise anında (G3)
    commit_timeout = M.autonomy(hub)["question_timeout_s"] if c["commit_approval"] == "timeout_default" else None
    waits_manager = c["commit_approval"] == "manual" or (c["commit_approval"] == "timeout_default" and commit_timeout != 0)
    if c["commit_approval"] == "timeout_default" and commit_timeout == 0 and not sp.get("commit_approved"):
        sp["commit_approval"] = {**(sp.get("commit_approval") or {}), "by": "TIMEOUT"}     # süre 0: beklemeden kesinleşir (L3)
    if waits_manager and not sp.get("commit_approved"):
        info = {
            "kind": "sprint_commit", "run_id": run.run_id, "order": record.order, "issue_id": record.issue_id,
            "title": tx("Sprint {n} taahhüdü", n=n), "agent_id": "SCRUM_MASTER", "agent_name": "Scrum Master", "agent_role": "SCRUM_MASTER",
            "next_agent_id": "BACKEND_DEV", "next_agent_name": "", "action": "SPRINT_COMMIT_REQUESTED",
            "summary": tx("{goal} — {count} iş taahhüt edilecek.", goal=sp["goal"], count=len(sp["proposed_issue_ids"])), "artifacts": [], "screenshots": [],
            "tokens_used": 0, "timestamp": now, "is_last_step": False, "engine": run.engine, "status": "SUCCESS",
            "proposed": [{"issue_id": i, "title": (hub.jira_issues.get(i) or {}).get("title")} for i in sp["proposed_issue_ids"]],
        }
        token = hub.open_step_approval(info)
        run.approval_token = token
        run.gate_kind = "sprint"
        run.status = "WAITING_APPROVAL"
        record.status = "WAITING_APPROVAL"
        await hub.broadcast({"type": "STEP_WAITING_APPROVAL", "step_info": hub.pending_step_approval})
        await P.publish_run(hub, run)
        if c["commit_approval"] == "timeout_default" and commit_timeout:
            sp["commit_deadline"] = _deadline(float(commit_timeout))          # G5: panoda geri sayım
            asyncio.create_task(_commit_timeout(hub, run, sp, token, float(commit_timeout)), name=f"sprint-commit-timeout-{n}")
        return P.StepOutcome(status="WAITING_APPROVAL", approval_token=token, message=tx("Sprint {n} taahhüdü yönetici onayı bekliyor", n=n)
                             + (" " + tx("(süre: {sec} sn; dolunca kendiliğinden kesinleşir).", sec=int(commit_timeout)) if commit_timeout else "."))

    # Taahhüt
    items = [hub.jira_issues[i] for i in sp["proposed_issue_ids"] if i in hub.jira_issues and SP._eligible(hub, hub.jira_issues[i])]
    if not items:
        return await _no_work(hub, run, record, n)
    sp["committed_at"] = now
    sp["commit_approval"] = {"mode": c["commit_approval"], "by": sp["commit_approval"].get("by") or ("SERVER" if c["commit_approval"] == "auto" else "MANAGER")}
    sp["committed_issue_ids"] = [i["id"] for i in items]
    docs_rel = hub_docs_path(hub, "", project_dir)
    cap = sp["capacity"]["max_tasks"]
    doc = SP.commitment_document(hub, sp, items, sp.get("out_of_scope", []), cap, sp["capacity"]["basis"])
    sp["commitment_ref"] = SP.write_commitment(hub, project_dir, docs_rel, sp, doc)
    SP.set_sprint_status(hub, sp, "COMMITTED")
    for i in items:
        await hub.update_jira_issue(i["id"], {"sprint": n, "audit_action": "SPRINT_COMMITTED", "audit_notes": tx("Sprint {n} taahhüdüne alındı.", n=n)})
    await hub.record_event(
        trace_id=run.run_id, from_agent="SCRUM_MASTER", to_agent="BACKEND_DEV", action="SPRINT_COMMITTED", status="SUCCESS",
        payload={"sprint": n, "goal": sp["goal"], "items": sp["committed_issue_ids"], "commitment_ref": sp["commitment_ref"]},
        current_file=sp["commitment_ref"], friendly_dialogue=tx("Sprint {n} taahhüt edildi: {goal}", n=n, goal=sp["goal"]))
    await hub.broadcast({"type": "SPRINT_COMMITTED", "sprint": n, "items": sp["committed_issue_ids"]})
    SP.set_sprint_status(hub, sp, "IN_PROGRESS", started_at=_iso())
    await hub.broadcast({"type": "SPRINT_STARTED", "sprint": n})

    run.insert_after_cursor(sprint_step_records(hub, n, items))

    record.status = "DONE"
    record.finished_at = _iso()
    record.summary = tx("Sprint {n} taahhüt edildi: {count} iş, hedef: {goal}", n=n, count=len(items), goal=sp["goal"])
    record.action = "SPRINT_COMMITTED"
    await hub.set_agent_status("SCRUM_MASTER", "COMPLETED")
    await P.advance_run(hub, run)
    return P.StepOutcome(status="NEXT", message=record.summary)


async def _no_work(hub, run: PipelineRun, record: StepRecord, n: int) -> "P.StepOutcome":
    """Taahhüt edilecek iş yok: ürün bitmişse proje DONE, değilse koşu sonlanır (yeni yükleme bekler)."""
    st = SP.ensure_state(hub)
    open_tasks = [i for i in hub.jira_issues.values() if str(i.get("kind", "")).lower() == "task" and i.get("status") != "DONE" and not i.get("deleted")]
    if not open_tasks and SP.existing_stories(hub):
        st["project_status"] = "DONE"
        await hub.broadcast({"type": "PROJECT_DONE"})
    record.status = "DONE"
    record.finished_at = _iso()
    record.summary = tx("Taahhüt edilecek iş yok.")
    record.action = "SPRINT_SKIPPED"
    await hub.set_agent_status("SCRUM_MASTER", "COMPLETED")
    await P.advance_run(hub, run)
    return P.StepOutcome(status="RUN_COMPLETE" if run.is_terminal else "NEXT", message=record.summary)


# ---------------------------------------------------------------------------
# Sprint kapanışı: taşıma, metrik, review-retro, etiket
# ---------------------------------------------------------------------------
async def run_close_step(hub, run: PipelineRun, record: StepRecord) -> "P.StepOutcome":
    project_dir = P.project_dir_for(hub, run)
    c = SP.cfg(hub)
    n = int(record.sprint or 0)
    sp = SP.get_sprint(hub, n)
    now = _iso()
    record.status = "ACTIVE"
    record.started_at = now
    run.status = "ACTIVE"
    if sp is None:
        record.status = "DONE"
        await P.advance_run(hub, run)
        return P.StepOutcome(status="RUN_COMPLETE" if run.is_terminal else "NEXT", message=tx("Sprint kaydı yok."))
    if Q.strict(hub) and not (sp.get("arch_review") or {}).get("done") and not any(s.kind == "review" and s.sprint == n for s in run.steps):
        # Sıkı DoD kapanışı mimar gözden geçirmesi ister ama bu koşuda planlanmamış (eski koşu / eksik plan): sprinti BLOCKED'a düşürmek yerine
        # gözden geçirmeyi kapanıştan hemen önce ekle; kapanış, gözden geçirme bitince yeniden denenir.
        record.status, record.started_at = "PENDING", None
        run.steps.insert(run.cursor, new_review_record(n))
        await hub.record_event(trace_id=run.run_id, from_agent="SCRUM_MASTER", to_agent="ARCHITECT", action="ARCH_REVIEW_PLANNED", status="IN_PROGRESS",
                               payload={"sprint": n}, friendly_dialogue=tx("Sprint {n} kapanışı mimar gözden geçirmesi ister; kapanıştan önce ARCHITECT adımını ekledim.", n=n))
        run.touch()
        return P.StepOutcome(status="NEXT", message=tx("Sprint {n}: kapanıştan önce ARCHITECT gözden geçirmesi planlandı.", n=n))
    review_steps = [s for s in run.steps if s.sprint == n and s.kind == "phase" and s.order in REVIEW_GATES]
    SP.set_sprint_status(hub, sp, "IN_REVIEW", review_started_at=(review_steps[0].started_at if review_steps and review_steps[0].started_at else now))
    await hub.broadcast({"type": "SPRINT_REVIEW_STARTED", "sprint": n})
    await hub.set_agent_status("SCRUM_MASTER", "WORKING", what_doing=tx("Sprint {n} kapanıyor", n=n))

    summary = SP.summarize(hub, run, n)
    completed, carried = summary["completed"], summary["carried"]

    for cinfo in carried:
        await hub.update_jira_issue(cinfo["issue_id"], {
            "sprint": None, "status": "BACKLOG", "fix_limit_sprint": None,
            "carry_over": {"count": cinfo["count"], "last_reason": cinfo["reason"], "from_sprint": n},
            "needs_rescope": cinfo["reason"] in SP.RESCOPE_REASONS,
            "audit_action": "CARRY_OVER", "audit_notes": tx("Sprint {n} sonunda taşındı: {reason} ({count}. kez)", n=n, reason=cinfo["reason"], count=cinfo["count"])})
        await hub.record_event(trace_id=run.run_id, from_agent="SCRUM_MASTER", to_agent="ARCHITECT", action="CARRY_OVER", status="FAILED",
                               payload={"sprint": n, **cinfo},
                               friendly_dialogue=tx("{id} bitmedi ve sonraki sprinte taşındı ({reason}).", id=cinfo["issue_id"], reason=cinfo["reason"]))
        await hub.broadcast({"type": "CARRY_OVER", "sprint": n, **cinfo})
    for iid in completed:
        await hub.update_jira_issue(iid, {"closed_in_sprint": n})
    await _roll_up_parents(hub, completed, n)

    metrics = summary["metrics"]
    sp.update({"completed_issue_ids": completed, "carried_over": carried, "metrics": metrics, "closed_at": now})

    # Öğrenme döngüsü (§8.5): önce önceki sprintte yazılan prompt değişikliklerini bu sprintin ölçümüyle sına (düşüş → geri al), sonra bu retronun aksiyonlarını uygula
    await L.evaluate_prompt_changes(hub, run, sp)

    async def _create_retro(tasks):
        from .steps.tasks import normalize_backlog
        await P._create_task_issues(hub, run, P.backlog_for(hub, tasks, 20), parent_id=record.issue_id, origin="RETRO", issue_type="TASK")
    await L.apply_retro_actions(hub, run, sp, project_dir, _create_retro)

    blocked = [x for x in carried if x["count"] >= c["carry_over_limit"]]   # §3.4: aynı iş carry_over_limit kez taşındı → BLOCKED
    precondition = None
    if Q.strict(hub):
        async def _create(tasks):
            from .steps.tasks import normalize_backlog
            await P._create_task_issues(hub, run, P.backlog_for(hub, tasks, 50), parent_id=record.issue_id, origin="ARCHITECT", issue_type="TASK")
        sp["dod"] = await Q.close_report(hub, run, sp, project_dir, _create)
        if not sp["dod"]["ok"]:
            precondition = "; ".join(sp["dod"]["missing"])
    if blocked:
        sp["blocked"] = {"reason": "CARRY_OVER_LIMIT", "since": now, "previous_status": "IN_REVIEW",
                         "detail": ", ".join(tx("{id} ({count}. taşıma)", id=b["issue_id"], count=b["count"]) for b in blocked)}
        SP.set_sprint_status(hub, sp, "BLOCKED")
    elif precondition:
        sp["blocked"] = {"reason": "PRECONDITION_LOST", "since": now, "previous_status": "IN_REVIEW", "detail": tx("Sıkı DoD kapanış koşulu eksik: ") + precondition}
        blocked = [{"issue_id": "DoD", "count": 0}]
        SP.set_sprint_status(hub, sp, "BLOCKED")
    else:
        SP.set_sprint_status(hub, sp, "CLOSED")

    docs_rel = hub_docs_path(hub, "", project_dir)
    date = now[:10]
    retro_meeting = next((m for m in reversed(SP.ensure_state(hub)["meetings"]) if m["sprint"] == n and m["type"] == "review-retro"), None)
    if retro_meeting is not None:
        await M.write_minutes(hub, retro_meeting)       # metrikler artık sprint kaydında: tutanak kesin rakamlarla yeniden üretilir
        sp["meetings"]["review_retro"] = retro_meeting["file"]
    else:
        retro_rel = f"{docs_rel}/meetings/{date}_sprint-{n}-review-retro.md"
        sp["meetings"]["review_retro"] = SP._write(project_dir, retro_rel, SP.retro_markdown(sp, hub.jira_issues))
    if hub.get_settings().get("auto_commit", True):
        await SCM.commit_all(project_dir, tx("chore(sprint-{n}): sprint {n} kapanışı ve review-retro", n=n))
        tag = await SCM.tag(project_dir, f"fssc/sprint-{n}", sp["goal"])
        if tag.get("status") == "TAGGED":
            sp["git_tag"] = tag["tag"]
    await hub.record_event(
        trace_id=run.run_id, from_agent="SCRUM_MASTER", to_agent="PM", action="SPRINT_BLOCKED" if blocked else "SPRINT_CLOSED",
        status="FAILED" if blocked else "SUCCESS", payload={"sprint": n, "metrics": metrics, "carried_over": carried, "retro": sp["meetings"]["review_retro"]},
        current_file=sp["meetings"]["review_retro"],
        friendly_dialogue=tx("Sprint {n} ENGELLENDİ: taşıma limiti aşıldı: {done}/{total} iş tamamlandı." if blocked else "Sprint {n} kapandı: {done}/{total} iş tamamlandı.", n=n, done=len(completed), total=len(sp["committed_issue_ids"])))
    await hub.broadcast({"type": "SPRINT_BLOCKED" if blocked else "SPRINT_CLOSED", "sprint": n, "metrics": metrics})

    record.status = "DONE"
    record.finished_at = _iso()
    record.summary = tx("Sprint {n}: {done}/{total} tamamlandı, {carried} taşındı", n=n, done=len(completed), total=len(sp["committed_issue_ids"]), carried=len(carried)) + (" " + tx("(ENGELLENDİ)") if blocked else "")
    record.action = "SPRINT_BLOCKED" if blocked else "SPRINT_CLOSED"
    await hub.set_agent_status("SCRUM_MASTER", "COMPLETED")

    st = SP.ensure_state(hub)
    open_tasks = [i for i in hub.jira_issues.values() if str(i.get("kind", "")).lower() == "task" and i.get("status") != "DONE" and not i.get("deleted")]
    if blocked:
        await P.finalize_run(hub, run, status="FAILED", reason="sprint_blocked:" + str((sp.get("blocked") or {}).get("reason") or "CARRY_OVER_LIMIT"))
        return P.StepOutcome(status="RUN_COMPLETE", message=record.summary)
    all_ac_accepted = all(a.get("status") == "ACCEPTED" for a in st["acs"].values()) if Q.strict(hub) else True   # §7.9: PRD'deki her kriter PO tarafından kabul
    if not open_tasks and not carried and metrics["uat_rejections"] == 0 and all_ac_accepted:
        st["project_status"] = "DONE"
        await hub.broadcast({"type": "PROJECT_DONE"})
        await P.advance_run(hub, run)
        return P.StepOutcome(status="RUN_COMPLETE" if run.is_terminal else "NEXT", message=record.summary + " " + tx("Ürün tamamlandı."))
    repeat = SP.repeat_check(hub, n)
    if repeat:                                       # devre kesici: aynı iş sprint sprint tekrarlanıyor; zincir durur, yönetici nedeni çözüp devam eder
        st["project_status"] = "PAUSED"
        st["pause_reason"] = {"code": "REPEATING_SPRINTS", "detail": repeat, "since": _iso()}
        await hub.broadcast({"type": "SPRINTS_REPEATING", "detail": repeat})
    elif len(st["sprints"]) >= min(c["max_sprints"], M.autonomy(hub)["budget"]["max_sprints"]):
        st["project_status"] = "PAUSED"
        await hub.broadcast({"type": "BUDGET_EXCEEDED", "limit": "max_sprints"})
    elif c["auto_chain"]:
        run.insert_after_cursor(rescope_records(hub) + [new_meeting_record(n + 1, "planning"), new_plan_record(n + 1)])
    hub.mark_dirty()
    await P.advance_run(hub, run)
    return P.StepOutcome(status="RUN_COMPLETE" if run.is_terminal else "NEXT", message=record.summary)


async def resume_if_budget_allows(hub, acknowledge: bool = False) -> bool:
    """Proje `max_sprints` bütçesi yüzünden PAUSED idiyse ve bütçe artık yeni sprinte izin veriyorsa ACTIVE'e döner (yönetici bütçeyi artırdığında ya da yeni koşu başlattığında)."""
    st = SP.ensure_state(hub)
    if st.get("project_status") != "PAUSED":
        return False
    if len(st["sprints"]) >= min(SP.cfg(hub)["max_sprints"], M.autonomy(hub)["budget"]["max_sprints"]):
        return False
    if st.get("pause_reason") and not acknowledge:      # devre kesici: yönetici nedeni gördüğünü onaylamadan sürmez
        return False
    st["pause_reason"] = None
    st["project_status"] = "ACTIVE"
    hub.mark_dirty()
    await hub.broadcast({"type": "PROJECT_RESUMED", "reason": tx("max_sprints bütçesi artırıldı")})
    return True


async def _roll_up_parents(hub, completed: List[str], n: int) -> None:
    """Bütün görevleri biten hikâye (ve bütün hikâyeleri biten epik) DONE olur; kapanan sprintle dondurulur."""
    parents = {(hub.jira_issues.get(i) or {}).get("parent_id") for i in completed}
    for pid in [p for p in parents if p and p in hub.jira_issues]:
        story = hub.jira_issues[pid]
        if str(story.get("kind", "")).lower() != "story":
            continue
        kids = [i for i in hub.jira_issues.values() if i.get("parent_id") == pid and str(i.get("kind", "")).lower() == "task"]
        if kids and all(k.get("status") == "DONE" for k in kids):
            await hub.update_jira_issue(pid, {"status": "DONE", "closed_in_sprint": n, "audit_action": "STORY_DONE", "audit_notes": tx("Sprint {n}: tüm görevleri bitti.", n=n)})
            epic = hub.jira_issues.get(story.get("parent_id") or "")
            if epic and str(epic.get("kind", "")).lower() == "epic":
                stories = [s for s in hub.jira_issues.values() if s.get("parent_id") == epic["id"] and str(s.get("kind", "")).lower() == "story"]
                if stories and all(s.get("status") == "DONE" for s in stories):
                    await hub.update_jira_issue(epic["id"], {"status": "DONE", "closed_in_sprint": n, "audit_action": "EPIC_DONE"})


# ---------------------------------------------------------------------------
# Yeniden kapsamlama
# ---------------------------------------------------------------------------
async def apply_rescope(hub, run: PipelineRun, record: StepRecord, payload: Dict[str, Any]) -> None:
    from .steps.tasks import normalize_backlog
    first = (payload.get("rescoped") or [{}])[0]
    issue = hub.jira_issues.get(record.issue_id) or {}
    updates: Dict[str, Any] = {"needs_rescope": False, "rescoped_at": _iso(), "status": "BACKLOG",
                               "audit_action": "RESCOPED", "audit_notes": tx("Yeniden kapsamlandı: {title}", title=str(first.get("title") or "")[:160])}
    for f in ("title", "description", "acceptance_criteria"):
        if first.get(f):
            updates[f] = first[f]
    await hub.update_jira_issue(record.issue_id, updates)
    split = P.backlog_for(hub, first.get("split"), 20)
    if split:
        for t in split:
            t["story_ref"] = issue.get("parent_id") or ""
        await P._create_task_issues(hub, run, split, parent_id=issue.get("parent_id") or record.issue_id, origin="ARCHITECT")
    await hub.broadcast({"type": "TASK_RESCOPED", "issue_id": record.issue_id, "split": len(split)})


def design_exists(hub) -> bool:
    """Onaylanmış ya da teslim edilmiş tasarım sistemi dosyası projede var mı?"""
    import os
    from .paths import hub_docs_path
    pdir = (hub.projects.get(hub.active_project_id) or {}).get("path") or ""
    rel = hub_docs_path(hub, "design/design-system.html", pdir)
    return bool(pdir) and os.path.isfile(os.path.join(pdir, *str(rel).replace("\\", "/").split("/")))


async def ensure_design_task(hub, force: bool = False, brief: str = "") -> Optional[Dict[str, Any]]:
    """DESIGNER çekirdek ajandır: bekleyen frontend işi varken tasarım sistemi + ilk ekranlar yoksa tek bir DESIGN görevi açılır (P0) ve açık frontend işleri
    ona bağlanır (frontend, onaylı tasarımdan önce başlamaz). Zaten bir DESIGN işi (bitmiş dahil) ya da tasarım dosyası varsa hiçbir şey yapmaz."""
    if not SP.enabled(hub) or (not force and not hub.get_settings().get("design_first", True)):
        return None
    agent = (getattr(hub, "agents", None) or {}).get("DESIGNER")
    if agent is None or agent.get("active") is False:
        return None
    issues = [i for i in hub.jira_issues.values() if str(i.get("kind", "")).lower() == "task" and not i.get("deleted")]
    designs = [i for i in issues if i.get("work_type") == "DESIGN"]
    existing = next((i for i in designs if i.get("status") != "DONE"), None) or (designs[0] if designs else None)
    if existing is not None and existing.get("status") != "DONE":
        return {"issue_id": existing["id"], "key": existing.get("key"), "existing": True, "status": existing.get("status")} if force else None
    redesign = existing is not None and force            # yönetici tasarım istedi ama tasarım zaten tamamlanmış: yenileme turu (v2, v3...) açılır
    if design_exists(hub) and not force:
        return None
    open_fe = [i for i in issues if i.get("assignee") == "FRONTEND_DEV" and i.get("status") != "DONE" and not i.get("sprint")]
    if not open_fe and not force:
        return None
    order = max([int(i.get("order", 0) or 0) for i in hub.jira_issues.values()] or [0]) + 1
    iid = f"JIRA-{order}"
    if redesign:
        n = len(designs) + 1
        await hub.update_jira_issue(iid, {
            "order": order, "title": tx("Tasarım yenileme v{n}: tüm ekranlar ve ekran akışları (profesyonel HTML mockup)", n=n), "issue_type": "TASK", "status": "BACKLOG", "priority": "P0",
            "assignee": "DESIGNER", "kind": "task", "origin": "MANAGER", "work_type": "DESIGN", "task_key": SP.next_key(hub, "T"), "redesign": True, "design_round": n,
            "design_brief": (brief or "").strip()[:4000],
            "description": tx("Yönetici isteği: mevcut tasarım yetersiz; tasarım sistemini yenile, uygulamadaki TÜM ekranlar için profesyonel mockup'ları üret ve ekranlar arası akışı çıkar.")
                           + ((NL * 2 + tx("Yönetici notu:") + NL + brief.strip()[:4000]) if (brief or "").strip() else ""),
            "acceptance_criteria": [tx("Tasarım sistemi yenilendi (design-system.html)"), tx("PRD ve uygulamadaki her ekran için mockup var (screens/*.html), boş/hata/yükleniyor/dolu durumlarıyla"),
                                    tx("Ekran akış haritası hazır (flows.md ve flows.html): ekran kimlikleri, geçişler, kullanıcı yolculukları"), tx("Yönetici onayı alındı")],
            "depends_on": [], "audit_action": "TASK_CREATED", "audit_notes": tx("Yönetici tasarım yenilemesi istedi (tur {n}).", n=n)})
        SP.adopt_manual_tasks(hub)
        return {"issue_id": iid, "redesign": True, "round": n}
    await hub.update_jira_issue(iid, {
        "order": order, "title": tx("Tasarım sistemi ve ilk ekranlar (HTML mockup)"), "issue_type": "TASK", "status": "BACKLOG", "priority": "P0",
        "assignee": "DESIGNER", "kind": "task", "origin": "ARCHITECT", "work_type": "DESIGN", "task_key": SP.next_key(hub, "T"),
        "description": tx("Onaylı teknoloji kararlarına ve şartnameye göre tasarım sistemini (renk, tipografi, boşluk, bileşenler) ve ilk ekranları HTML mockup olarak hazırla; "
                          "yönetici onaylamadan frontend başlamaz."),
        "acceptance_criteria": [tx("Tasarım sistemi sayfası hazır (design-system.html)"), tx("İlk ekranların mockup'ları hazır (screens/*.html)"), tx("Yönetici onayı alındı")],
        "depends_on": [], "audit_action": "TASK_CREATED", "audit_notes": tx("Arayüz işi var, tasarım yok: tasarım görevi otomatik açıldı.")})
    for i in open_fe:
        deps = list(i.get("depends_on") or [])
        if iid not in deps:
            await hub.update_jira_issue(i["id"], {"depends_on": deps + [iid], "audit_action": "DEPENDENCY_ADDED", "audit_notes": tx("Onaylı tasarımdan önce başlamaz ({iid}).", iid=iid)})
    SP.adopt_manual_tasks(hub)
    return {"issue_id": iid, "frontend_linked": len(open_fe)}


async def start_design_now(hub, brief: str = "") -> Dict[str, Any]:
    """Yönetici: tasarım (DESIGNER) çalışması hemen başlasın — tasarım görevi açılır (varsa kullanılır) ve geçerli adımdan hemen sonra çalışacak şekilde öne alınır."""
    out = await ensure_design_task(hub, force=True, brief=brief)
    if out is None:
        raise ValueError(tx("Tasarım görevi açılamadı: tasarım zaten tamamlanmış ya da DESIGNER ajanı/sprint kipi kapalı."))
    iid = out["issue_id"]
    out["expedite"] = await expedite_issue(hub, iid, "now")
    return out


def _proposal(hub, n: int, cap: int):
    """Taahhüt önerisi: toplantının `commitment` çıktısı geçerliyse o (uygun, bağımlılığı sağlanan, kapasiteyi aşmayan işlerle), değilse sunucu seçimi."""
    SP.adopt_manual_tasks(hub)                     # elle girilen işler planlayıcıya görünür olur (kind yoksa hiç seçilmezdi)
    SP.merge_duplicates(hub)                       # aynı bulgudan çıkan kopya maddeler taahhütten önce tek maddede birleşir
    mc = SP.ensure_state(hub)["meeting_commitments"].get(str(n))
    if mc:
        eligible = {i["id"]: i for i in SP.candidates(hub, n)}
        done = {k for k, v in hub.jira_issues.items() if v.get("status") == "DONE"}
        chosen: List[Dict[str, Any]] = []
        out: List[Dict[str, str]] = [o for o in (mc.get("out_of_scope") or []) if isinstance(o, dict) and o.get("issue_id")]
        for iid in mc.get("items") or []:
            issue = eligible.get(iid)
            if issue is None:
                out.append({"issue_id": str(iid), "reason": tx("TAAHHÜT DIŞI: uygun değil (yok, bitmiş, taahhütte ya da yeniden kapsamlanmamış)")})
            elif len(chosen) >= cap:
                out.append({"issue_id": iid, "reason": "KAPASİTE"})
            elif all(d in done or d in {c["id"] for c in chosen} for d in (issue.get("depends_on") or [])):
                chosen.append(issue)
            else:
                out.append({"issue_id": iid, "reason": "BAĞIMLILIK"})
        chosen = SP.execution_order(chosen) if chosen else chosen          # yürütme sırası toplantı listesine değil yönetici önceliğine göre
        if chosen and sum(1 for c in chosen if SP.is_test_work(c)) <= SP.test_cap(hub, cap) and sum(1 for c in chosen if SP.is_quality_work(c)) <= SP.quality_limit(hub, cap):
            if len(chosen) < min(cap, max(1, cap // 2, SP.cfg(hub)["min_tasks"])) and not hub.get_settings().get("product_first"):      # ürün önce: toplantının dar taahhüdü başka işlerle doldurulmaz
                # Toplantı kapasitenin yarısından azını taahhüt etti: sunucunun dengeli seçimiyle (bağımlılığı sağlanan) işlerle tamamlanır (sprint tek işle kalmasın)
                have = {c["id"] for c in chosen}
                done = {k for k, v in hub.jira_issues.items() if v.get("status") == "DONE"}
                for extra in SP.select_items(hub, cap, n)[0]:
                    if len(chosen) >= cap:
                        break
                    if extra["id"] not in have and all(d in done or d in have for d in (extra.get("depends_on") or [])):
                        chosen.append(extra)
                        have.add(extra["id"])
            return chosen, out
        # test/kalite payı aşıldıysa sunucunun dengeli seçimine düşülür (özellik hikâyeleri test ve refactor işlerinin arkasında kalmasın)
    return SP.select_items(hub, cap, n)

# ---------------------------------------------------------------------------
# G3: zaman aşımıyla taahhüt (§7.5) ve acil girdi toplantısı (§8.4)
# ---------------------------------------------------------------------------
def _deadline(seconds: float) -> str:
    from datetime import datetime, timedelta, timezone
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat()


async def _commit_timeout(hub, run: PipelineRun, sp: Dict[str, Any], token: str, timeout_s: float) -> None:
    """`commit_approval=timeout_default`: yönetici süre içinde cevaplamazsa taahhüt kendiliğinden kesinleşir (`by: TIMEOUT`)."""
    try:
        await asyncio.sleep(timeout_s)
    except asyncio.CancelledError:
        return
    if not hub.gate.is_pending(token) or run.approval_token != token:
        return
    sp["commit_approval"] = {**(sp.get("commit_approval") or {}), "by": "TIMEOUT"}
    await hub.record_event(trace_id=run.run_id, from_agent="SCRUM_MASTER", to_agent="MANAGER", action="SPRINT_COMMIT_DEFAULTED", status="SUCCESS",
                           payload={"sprint": sp["sprint_number"], "timeout_s": timeout_s},
                           friendly_dialogue=tx("Sprint {n} taahhüdü süre dolunca kesinleşti (yönetici cevaplamadı).", n=sp["sprint_number"]))
    await hub.broadcast({"type": "SPRINT_COMMIT_DEFAULTED", "sprint": sp["sprint_number"], "timeout_s": timeout_s})
    await hub.approve_step("PROCEED", token=token)


async def schedule_adhoc(hub, text: str, spec_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Acil yönetici girdisi (§8.4): süren sprint koşusuna, geçerli adımdan hemen sonra bir `adhoc` toplantı adımı ekler ve notu geçerli
    adımın bağlamına yazar. Toplantı, başlamamış taahhüt işlerini yer değiştirebilir (`apply_adhoc`). Sprint koşusu yoksa None."""
    run = hub.active_run_for(hub.active_project_id)
    if run is None or run.is_terminal or run.mode != "sprint":
        return None
    cur = run.current_step
    n = int((cur.sprint if cur else None) or SP.ensure_state(hub).get("current_sprint") or 0)
    sp = SP.get_sprint(hub, n) if n else None
    if sp is None or sp["status"] not in ("COMMITTED", "IN_PROGRESS", "IN_REVIEW"):
        return None
    already = any(s.kind == "meeting" and s.work_type == "adhoc" and s.sprint == n and s.status == "PENDING" for s in run.steps)
    if not already:
        run.insert_after_cursor([new_meeting_record(n, "adhoc")])
    sp.setdefault("scope_changes", []).append({"at": _iso(), "source": "urgent_input", "spec_id": spec_id, "text": str(text)[:400], "meeting": "adhoc"})
    try:
        await P.add_manager_note(hub, run, tx("ACİL GİRDİ: {text}", text=text), urgent=False)
    except ValueError:
        pass
    await hub.record_event(trace_id=run.run_id, from_agent="MANAGER", to_agent="SCRUM_MASTER", action="URGENT_INPUT", status="IN_PROGRESS",
                           payload={"sprint": n, "spec_id": spec_id, "text": str(text)[:600]},
                           friendly_dialogue=tx("Acil girdi geldi; adhoc toplantı açılıyor, başlamamış işler yer değiştirebilir."))
    await hub.broadcast({"type": "ADHOC_SCHEDULED", "sprint": n, "run_id": run.run_id})
    await P.publish_run(hub, run)
    return {"sprint": n, "run_id": run.run_id, "inserted": not already}


def started_issue_ids(run: PipelineRun, n: int) -> Set[str]:
    return {s.issue_id for s in run.steps if s.sprint == n and s.kind in ("task", "fix") and s.status != "PENDING"}


async def apply_adhoc(hub, run: PipelineRun, record: StepRecord, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Adhoc toplantının `commitment` çıktısını uygular: `out_of_scope` ile BAŞLAMAMIŞ taahhüt işleri kapsam dışına (backlog, NOT_STARTED),
    `items` ile boşalan sayı kadar uygun backlog işi taahhüde alınır (kapasite aşılmaz). Her değişiklik `scope_changes` ve denetim izine yazılır."""
    n = int(record.sprint or 0)
    sp = SP.get_sprint(hub, n) if n else None
    out: Dict[str, Any] = {"removed": [], "added": []}
    if sp is None:
        return out
    commitment = payload.get("commitment") or {}
    if not isinstance(commitment, dict):
        return out
    started = started_issue_ids(run, n)
    for o in commitment.get("out_of_scope") or []:
        iid = str(o.get("issue_id") or "") if isinstance(o, dict) else ""
        reason = str((o or {}).get("reason") or tx("acil girdi")) if isinstance(o, dict) else tx("acil girdi")
        if iid not in sp.get("committed_issue_ids", []) or iid in started:
            continue
        run.steps[:] = [s for s in run.steps if not (s.issue_id == iid and s.sprint == n and s.kind in ("task", "fix") and s.status == "PENDING")]
        sp["committed_issue_ids"].remove(iid)
        prev = int(((hub.jira_issues.get(iid) or {}).get("carry_over") or {}).get("count", 0) or 0)
        await hub.update_jira_issue(iid, {"sprint": None, "status": "BACKLOG", "carry_over": {"count": prev + 1, "last_reason": "NOT_STARTED", "from_sprint": n},
                                          "audit_action": "SCOPE_CHANGE", "audit_notes": tx("Sprint {n}: acil girdi toplantısında kapsam dışına alındı ({reason}).", n=n, reason=reason[:160])})
        out["removed"].append(iid)
    free = len(out["removed"])
    eligible = {i["id"]: i for i in SP.candidates(hub, n)}
    for iid in commitment.get("items") or []:
        if free <= 0:
            break
        issue = eligible.get(str(iid))
        if issue is None or str(iid) in sp.get("committed_issue_ids", []):
            continue
        rec = StepRecord(order=int(issue["order"]), issue_id=issue["id"], role=issue.get("assignee") or "BACKEND_DEV", kind="task",
                         title=issue.get("title", ""), round=n, work_type=issue.get("work_type") or "", sprint=n)
        run.insert_before_order([rec], 5)
        sp["committed_issue_ids"].append(issue["id"])
        await hub.update_jira_issue(issue["id"], {"sprint": n, "audit_action": "SPRINT_COMMITTED", "audit_notes": tx("Sprint {n}: acil girdi toplantısında taahhüde alındı.", n=n)})
        out["added"].append(issue["id"])
        free -= 1
    sp.setdefault("scope_changes", []).append({"at": _iso(), "source": "adhoc", "meeting": record.issue_id, **out})
    if out["removed"] or out["added"]:
        await hub.record_event(trace_id=run.run_id, from_agent="SCRUM_MASTER", to_agent="MANAGER", action="SCOPE_CHANGED", status="SUCCESS",
                               payload={"sprint": n, **out},
                               friendly_dialogue=tx("Sprint {n} kapsamı değişti: çıkan {removed}; giren {added}.", n=n, removed=", ".join(out["removed"]) or "-", added=", ".join(out["added"]) or "-"))
        await hub.broadcast({"type": "SCOPE_CHANGED", "sprint": n, **out})
        hub.mark_dirty()
    return out
