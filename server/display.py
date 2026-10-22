"""Claude Desktop oturumunda görünürlük (F5, belge §9.5): `display_md` metinleri ve etkinlik akışı.

`get_next_step` ve `submit_step_result` yanıtlarındaki `display_md`, istemcinin oturuma AYNEN yazdığı hazır metindir.
Ajanlar arası mesajlar (devir notları) hem alıcıya hem yöneticiye bu metinle görünür. İçerik sunucu verisinden gelir; istemci yorum katmaz.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from . import driver as DRV
from . import sprint as SP
from .i18n import translate as tx


def _k(n: float) -> str:
    return tx("{v:.1f} milyon", v=n / 1_000_000) if n >= 1_000_000 else (tx("{v} bin", v=int(round(n / 1000))) if n >= 1000 else str(int(n)))


def spend_line(hub, run, sprint: Optional[int]) -> str:
    """"Harcama: sprint 41 dk / 300 dk · 380 bin / 3 milyon token" (sunucu verisi; rakamları istemci değiştirmez)."""
    if not sprint:
        return ""
    b = DRV.budget(hub)
    u = DRV.sprint_usage(hub, run, sprint)
    return tx("Harcama: sprint {used:.0f} dk / {max_min} dk · {tok} / {max_tok} token", used=u['active_min'], max_min=b['max_active_min_per_sprint'],
              tok=_k(u['tokens']), max_tok=_k(b['max_tokens_per_sprint']))


def _incoming(run, agent_id: str, limit: int = 3) -> List[str]:
    return [tx("  Gelen mesaj — {frm} → {to}: {msg}", frm=h['from'], to=h['to'], msg=h['message'])
            for h in run.handoffs[-12:] if h.get("to") in (agent_id, "ALL")][-limit:]


def _label(hub, record) -> str:
    issue = hub.jira_issues.get(record.issue_id) or {}
    wt = record.work_type or issue.get("work_type")
    base = record.issue_id if str(record.issue_id).startswith("JIRA-") else tx("sprint {n}", n=record.sprint)
    title = record.title or issue.get("title") or ""
    return f"{base}{f' ({wt})' if wt else ''} {title}".strip()


def step_start_md(hub, run, record, agent_id: str) -> str:
    """Adım başında: sprint ve adım sırası, ajan, iş maddesi ve türü; bu ajana gelen mesajlar."""
    pos = tx("adım {a}/{b}", a=run.cursor + 1, b=len(run.steps))
    sprint = tx("Sprint {n} · ", n=record.sprint) if record.sprint else ""
    kind = {"fix": tx(" (düzeltme {n})", n=record.fix_round), "meeting": tx(" (toplantı)"), "rescope": tx(" (yeniden kapsamlama)"), "structure": tx(" (görev kırılımı)")}.get(record.kind, "")
    lines = [f"▶ {sprint}{pos} · {agent_id}{kind} · {_label(hub, record)}"]
    lines += _incoming(run, agent_id)
    return "\n".join(lines)


def step_end_md(hub, run, record, agent_id: str, summary: str = "", written: Optional[List[str]] = None, verification: Optional[Dict[str, Any]] = None,
                commit: Optional[str] = None, extra: Optional[Dict[str, Any]] = None) -> str:
    """Adım sonunda: yapılanın özeti, yazılan dosyalar, doğrulama sonucu, commit, çıkan mesajlar, harcama ve sıradaki adım."""
    verbosity = DRV.display_cfg(hub)["verbosity"]
    written = written or []
    lines = [tx("✔ {agent} teslim etti", agent=agent_id) + (tx(": {n} dosya", n=len(written)) if written else "")]
    if summary and (verbosity == "full" or not written):
        lines.append(f"  {summary[:300]}")
    if verbosity == "full" and written:
        lines += [f"  - {w}" for w in written[:12]]
    if verification:
        lines.append(tx("  Doğrulama: {body}", body=verification.get('summary') or verification.get('status')))
    if commit:
        lines.append(tx("  Commit: {commit}", commit=commit))
    if extra and extra.get("meeting_id"):
        lines.append(tx("  Toplantı kaydı: {id}", id=extra['meeting_id']))
    out = [h for h in run.handoffs if h.get("order") == record.order and h.get("from") == agent_id][-2:]
    lines += [tx("  Giden mesaj — {frm} → {to}: {msg}", frm=h['from'], to=h['to'], msg=h['message']) for h in out]
    sp = spend_line(hub, run, record.sprint)
    if sp:
        lines.append(f"  {sp}")
    nxt = run.current_step if not run.is_terminal else None
    if nxt is not None:
        lines.append(tx("  Sıradaki: adım {n} · {role} · {label}", n=run.cursor + 1, role=nxt.role, label=_label(hub, nxt)))
    return "\n".join(lines)


def meeting_md(hub, meeting: Dict[str, Any]) -> str:
    lines = [tx("🗣 Toplantı {id} · {type} · sprint {n}", id=meeting['id'], type=meeting['type'], n=meeting['sprint'])]
    lines += [f"  {t['from']} → {t['to']}: {t['message']}" for t in meeting["discussion"]]
    qs = {q["id"]: q for q in __import__("server.meetings", fromlist=["store"]).store(hub)["questions"]}
    for did in meeting.get("decision_ids", []):
        d = next((x for x in SP.ensure_state(hub)["decisions"] if x["id"] == did), None)
        if d:
            lines.append(tx("  Karar {id}: {body}", id=did, body=d['text']))
    for qid in meeting.get("question_ids", []):
        q = qs.get(qid)
        if q:
            lines.append(tx("  ❓ Soru {id} ({cat}{blocking}): {body} — öneri {rec}", id=qid, cat=q['category'], blocking=tx(', engelleyici') if q['blocking'] else '',
                            body=q["text"], rec=q['recommended']))
    return "\n".join(lines)


def stop_md(hub, run, reason: str, detail: str = "", todo: str = "") -> str:
    """Sınır ya da durma: neden, harcanan süre ve token, yöneticinin ne yapması gerektiği."""
    sprint = (run.current_step.sprint if run.current_step else None) or next((s.sprint for s in reversed(run.steps) if s.sprint), None)
    lines = [tx("⏸ Durdu: {reason}", reason=reason) + (f" — {detail}" if detail else "")]
    sp = spend_line(hub, run, sprint)
    if sp:
        lines.append(f"  {sp}")
    if todo:
        lines.append(tx("  Yönetici: {todo}", todo=todo))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Etkinlik akışı (get_activity_feed)
# ---------------------------------------------------------------------------
def activity_feed(hub, limit: int = 30) -> Dict[str, Any]:
    st = SP.ensure_state(hub)
    run = hub.active_run_for(hub.active_project_id)
    last_run = run or next(iter(sorted(hub.runs.values(), key=lambda r: r.created_at, reverse=True)), None)
    sprint = st.get("current_sprint")
    sp = SP.get_sprint(hub, sprint) if sprint else None
    from . import meetings as M
    blockers = M.open_blocking(hub)
    head = [tx("FS-SC · proje {project} · durum {status}", project=hub.active_project_id, status=st['project_status'])
            + (tx(" · sprint {n} {status}", n=sprint, status=sp['status']) if sp else "")
            + (tx(" · koşu {run} {status}", run=run.run_id, status=run.status) if run else tx(" · etkin koşu yok"))]
    if sp and sp.get("blocked"):
        head.append(tx("⏸ Sprint BLOCKED: {reason} — {detail}", reason=sp['blocked']['reason'], detail=sp['blocked'].get('detail')))
    if last_run is not None and sprint:
        head.append(spend_line(hub, last_run, sprint))
    openq = [q for q in M.all_questions(hub) if q.get("status") == "OPEN"]
    if openq:
        head.append(tx("❓ Açık soru: {n} (engelleyici: {b}) — ", n=len(openq), b=len(blockers)) + ", ".join(q["id"] for q in openq[:6]))
    r = DRV.runner_status(hub)
    head.append(tx("Runner: son görülme {seen} · ", seen=r['last_seen'] or tx('hiç')) + (tx("güncel") if r["fresh"] else tx("istemci bekleniyor")))
    events = list(hub.events)[-max(1, min(int(limit), 200)):]
    lines = []
    for e in reversed(events):
        when = str(e.get("timestamp", ""))[11:19]
        who = f"{e.get('from_agent')} → {e.get('to_agent')}"
        text = (e.get("friendly_dialogue") or e.get("what_doing") or "")[:170]
        lines.append(f"[{when}] {who} · {e.get('action')}" + (f" — {text}" if text else ""))
    return {"summary": head, "events": lines, "markdown": "\n".join(head + ["", tx("Son etkinlik:")] + (["- " + l for l in lines] or [tx("- Yok.")])),
            "open_questions": [q["id"] for q in openq], "blocking_questions": [q["id"] for q in blockers]}
