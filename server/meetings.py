"""Toplantılar, soru kuyruğu ve karar kayıtları (F4, belge §3.3, §8, §10.4-§10.6).

Toplantı, koşuya sunucunun eklediği `kind: meeting` adımıdır; istemci rollerin konuşma turlarını ve yapılandırılmış sonucu teslim eder
(§10.5). Sunucu sonucu doğrular, kimlikleri (M-, DEC-, Q-, ADR) atar ve tutanağı, ADR'leri, soruları kendisi yazar — tutanağı LLM yazmaz.
Turlar mevcut müzakere odası mekanizmasıyla (`server/deliberation.py`) yayınlanır; paralel bir toplantı motoru yoktur (A5).
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from . import adr as ADR
from . import sprint as SP
from .i18n import translate as tx, N_
from .llm.parsing import StepOutputError
from .paths import hub_docs_path

MEETING_TYPES = ("kickoff", "planning", "review-retro", "arch-review", "adhoc")
QUESTION_CATEGORIES = ("TECHNOLOGY", "EXTERNAL_ACTION", "SCOPE", "DESIGN")
BLOCKING_CATEGORIES = {"TECHNOLOGY", "EXTERNAL_ACTION"}      # ajan başka bir soruyu engelleyici yapamaz; sunucu kategoriden türetir
LEVELS = ("L0", "L1", "L2", "L3")
# §3.5 bütçeleri; `question_timeout_s`: None = yöneticiyi bekler (L0-L1), N sn = süre dolunca varsayılan (L2), 0 = anında varsayılan (L3)
DEFAULT_BUDGET: Dict[str, int] = {"max_active_min_per_sprint": 900, "max_tokens_per_sprint": 8000000, "max_tokens_per_task": 400000,
                                  "max_steps_per_sprint": 100, "max_sprints": 20, "max_consecutive_failed_steps": 5, "stall_steps": 6, "warn_at_percent": 80}
# G1: sıkı bitmişlik tanımı VARSAYILAN olarak açık (SKIPPED doğrulama ya da testsiz teslim bitmiş sayılmaz); L0/L1 ön ayarları bilinçli olarak kapatır
DEFAULT_AUTONOMY: Dict[str, Any] = {"question_timeout_s": None, "strict_dod": True, "budget": dict(DEFAULT_BUDGET),
                                    "retro": {"max_prompt_changes_per_sprint": 1}}
PARTICIPANTS = ["SCRUM_MASTER", "PM", "ARCHITECT", "BACKEND_DEV", "FRONTEND_DEV", "QA", "DEVOPS", "PO"]
RETRO_ACTION_TYPES = ("PROCESS", "PROMPT", "BACKLOG")
# Seviye ön ayarları (§3.1): düğme anahtarları topluca yazar; doğruluk kaynağı anahtarların kendisidir
PRESETS: Dict[str, Dict[str, Any]] = {
    "L0": {"approval_mode": "every_step", "commit_approval": "manual", "auto_chain": False, "question_timeout_s": None, "strict_dod": False},
    "L1": {"approval_mode": "critical_only", "commit_approval": "manual", "auto_chain": False, "question_timeout_s": None, "strict_dod": False},
    "L2": {"approval_mode": "note_and_continue", "commit_approval": "timeout_default", "auto_chain": False, "question_timeout_s": 1800, "strict_dod": True},
    "L3": {"approval_mode": "auto", "commit_approval": "auto", "auto_chain": True, "question_timeout_s": 0, "strict_dod": True},
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Otonomi ayarı ve soru deposu
# ---------------------------------------------------------------------------
def sanitize_autonomy(raw: Any, fallback: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Geçersiz değer `fallback`te (yoksa varsayılanda) kalan değeri korur. `level` saklanmaz (ön ayar anahtarları yazar)."""
    raw = raw if isinstance(raw, dict) else {}
    base = fallback if isinstance(fallback, dict) else {}
    out: Dict[str, Any] = {
        "question_timeout_s": base.get("question_timeout_s", DEFAULT_AUTONOMY["question_timeout_s"]),
        "strict_dod": bool(base.get("strict_dod", DEFAULT_AUTONOMY["strict_dod"])),
        "budget": {**DEFAULT_BUDGET, **{k: v for k, v in (base.get("budget") or {}).items() if k in DEFAULT_BUDGET}},
        "retro": {**DEFAULT_AUTONOMY["retro"], **(base.get("retro") or {})},
    }
    if "question_timeout_s" in raw:
        v = raw["question_timeout_s"]
        if v is None:
            out["question_timeout_s"] = None
        else:
            try:
                out["question_timeout_s"] = max(0, min(int(v), 86400))
            except (TypeError, ValueError):
                pass
    if "strict_dod" in raw:
        out["strict_dod"] = bool(raw["strict_dod"])
    for k, v in (raw.get("budget") or {}).items() if isinstance(raw.get("budget"), dict) else []:
        if k in DEFAULT_BUDGET:
            try:
                out["budget"][k] = max(1, min(int(v), 1_000_000_000 if k != "warn_at_percent" else 100))
            except (TypeError, ValueError):
                pass
    if isinstance(raw.get("retro"), dict) and "max_prompt_changes_per_sprint" in raw["retro"]:
        try:
            out["retro"]["max_prompt_changes_per_sprint"] = max(0, min(int(raw["retro"]["max_prompt_changes_per_sprint"]), 5))
        except (TypeError, ValueError):
            pass
    return out


def autonomy(hub) -> Dict[str, Any]:
    a = sanitize_autonomy((hub.get_settings() or {}).get("autonomy"))
    a["level"] = current_level(hub)
    return a


def current_level(hub) -> str:
    """Anahtarlardan türetilen seviye (L0-L3); ön ayara uymuyorsa CUSTOM."""
    st = hub.get_settings() or {}
    a = sanitize_autonomy(st.get("autonomy"))
    sp = SP.cfg(hub)
    for lvl, p in PRESETS.items():
        if (st.get("approval_mode", "every_step") == p["approval_mode"] and sp["commit_approval"] == p["commit_approval"] and sp["auto_chain"] == p["auto_chain"]
                and a["question_timeout_s"] == p["question_timeout_s"] and a["strict_dod"] == p["strict_dod"]):
            return lvl
    return "CUSTOM"


def preset_updates(level: str) -> Dict[str, Any]:
    """`update_settings` sözlüğü: seviye ön ayarının yazacağı anahtarlar."""
    p = PRESETS[level]
    return {"approval_mode": p["approval_mode"], "sprint": {"commit_approval": p["commit_approval"], "auto_chain": p["auto_chain"]},
            "autonomy": {"question_timeout_s": p["question_timeout_s"], "strict_dod": p["strict_dod"]}}


def store(hub) -> Dict[str, Any]:
    st = getattr(hub, "question_store", None)
    if not isinstance(st, dict) or not st:
        st = {}
    st.setdefault("schema_version", 1)
    st.setdefault("questions", [])
    hub.question_store = st
    return st


def all_questions(hub) -> List[Dict[str, Any]]:
    """Toplantı soruları + teknoloji gereksinimlerinin soruları (F2) tek listede; Q kimlikleri proje genelinde tekildir."""
    out = list(store(hub)["questions"])
    req = hub.tech_requirements() if hasattr(hub, "tech_requirements") else None
    items = {it["id"]: it for it in (req or {}).get("items", [])}
    for q in (req or {}).get("questions", []):
        item = items.get(q.get("item_id") or "")
        out.append({"id": q["id"], "category": q.get("category", "TECHNOLOGY"), "raised_by": "PM", "text": q.get("question"),
                    "options": [{"key": str(i + 1), "label": o.get("value")} for i, o in enumerate(q.get("options") or [])],
                    "recommended": q.get("recommended"), "blocking": True,
                    "status": "OPEN" if q.get("status") == "AÇIK" else "ANSWERED",
                    "answer": q.get("answer") or (item or {}).get("value"), "answered_by": (item or {}).get("approved_by"), "source": "tech_requirements"})
    return out


def next_question_id(hub) -> str:
    nums = [int(m.group(1)) for q in all_questions(hub) for m in [re.match(r"^Q-(\d+)$", str(q.get("id")))] if m]
    return f"Q-{(max(nums) + 1) if nums else 1}"


def next_meeting_id(hub) -> str:
    day = datetime.now(timezone.utc).strftime("%Y%m%d")
    seq = SP.ensure_state(hub)["meeting_seq"]
    seq[day] = int(seq.get(day, 0)) + 1
    return f"M-{day}-{seq[day]}"


def next_decision_id(hub) -> str:
    st = SP.ensure_state(hub)
    st["dec_seq"] = int(st.get("dec_seq", 0)) + 1
    return f"DEC-{st['dec_seq']}"


def deadline_for(hub, category: str, raised_at: str) -> Optional[str]:
    """§3.3 madde 3-4: teknoloji/dış eylem sorusunda süre yoktur; diğerlerinde `question_timeout_s` None ise süresiz, N sn sonra, 0 hemen."""
    if category in BLOCKING_CATEGORIES:
        return None
    timeout = autonomy(hub)["question_timeout_s"]
    if timeout is None:
        return None
    return (datetime.fromisoformat(raised_at) + timedelta(seconds=int(timeout))).isoformat()


# ---------------------------------------------------------------------------
# Teslim zarfının doğrulanması (§10.5)
# ---------------------------------------------------------------------------
def normalize_payload(payload: Dict[str, Any], mtype: str, known_agents: List[str]) -> Dict[str, Any]:
    errors: List[str] = []
    if mtype not in MEETING_TYPES:
        raise StepOutputError(tx("Bilinmeyen toplantı tipi: {type}", type=mtype), [tx("toplantı tipi {type}", type=mtype)])
    meeting = payload.get("meeting") if isinstance(payload.get("meeting"), dict) else {}
    summary = str(meeting.get("summary") or payload.get("summary") or "").strip()
    discussion = []
    for t in payload.get("discussion") or []:
        if not isinstance(t, dict):
            continue
        frm = str(t.get("from") or "").upper().strip()
        msg = str(t.get("message") or "").strip()
        if frm not in known_agents or not msg:
            errors.append(tx("discussion: geçersiz tur (from={frm!r}); bilinen ajan ve boş olmayan mesaj gerekir", frm=t.get("from")))
            continue
        discussion.append({"from": frm, "to": str(t.get("to") or "ALL").upper(), "topic": str(t.get("topic") or "")[:120], "message": msg[:1200]})
    if not discussion and not errors:
        errors.append(tx("discussion boş olamaz: toplantı en az bir konuşma turu içermeli"))
    decisions = []
    for d in payload.get("decisions") or []:
        text = str((d.get("text") if isinstance(d, dict) else d) or "").strip()
        if text:
            decisions.append({"text": text[:400]})
    questions = []
    for q in payload.get("questions") or []:
        if not isinstance(q, dict):
            continue
        cat = str(q.get("category") or "").upper().strip()
        text = str(q.get("text") or "").strip()
        opts = [{"key": str(o.get("key") or chr(65 + i)).strip()[:4], "label": str(o.get("label") or "").strip()[:200]}
                for i, o in enumerate(q.get("options") or []) if isinstance(o, dict) and str(o.get("label") or "").strip()]
        rec = str(q.get("recommended") or "").strip()
        why = str(q.get("rationale") or "").strip()
        if cat not in QUESTION_CATEGORIES:
            errors.append(tx("soru kategorisi geçersiz: {cat!r} ({cats})", cat=q.get("category"), cats=", ".join(QUESTION_CATEGORIES)))
        elif not text or len(opts) < 2:
            errors.append(tx("soru metni ve en az iki seçenek gerekir"))
        elif not rec or rec not in {o["key"] for o in opts}:
            errors.append(tx("soru önerilen cevap olmadan reddedilir (önerisi olmayan soru kabul edilmez): {text}", text=text[:60]))
        elif not why:
            errors.append(tx("soru gerekçe (rationale) olmadan reddedilir: {text}", text=text[:60]))
        else:
            draft = q.get("adr") if isinstance(q.get("adr"), dict) else None
            questions.append({"category": cat, "raised_by": str(q.get("raised_by") or "SCRUM_MASTER").upper(), "text": text[:400], "options": opts,
                              "recommended": rec, "rationale": why[:600], "adr": draft})
    commitment = payload.get("commitment") if isinstance(payload.get("commitment"), dict) else None
    retro = payload.get("retro") if isinstance(payload.get("retro"), dict) else None
    if mtype in ("kickoff", "planning") and not commitment:
        errors.append(tx("kickoff/planning toplantısı `commitment` (hedef ve iş listesi) teslim etmeli"))
    if mtype == "review-retro":
        if not retro:
            errors.append(tx("review-retro toplantısı `retro` teslim etmeli"))
        else:
            actions = []
            for a in retro.get("action_items") or []:
                if isinstance(a, dict) and str(a.get("type", "")).upper() in RETRO_ACTION_TYPES:
                    t = str(a["type"]).upper()
                    if t in ("PROCESS", "PROMPT") and not (str(a.get("target") or "").strip() and a.get("value") not in (None, "")):
                        errors.append(tx("retro {type} aksiyonu `target` ve `value` gerektirir", type=t))
                    elif t == "BACKLOG" and not str(a.get("value") or a.get("target") or "").strip():
                        errors.append(tx("retro BACKLOG aksiyonu bir başlık (`value`) gerektirir"))
                    else:
                        actions.append({**a, "type": t})
                elif isinstance(a, dict):
                    errors.append(tx("retro aksiyon tipi geçersiz: {type!r} ({types})", type=a.get("type"), types=", ".join(RETRO_ACTION_TYPES)))
            retro = {"went_well": [str(x) for x in retro.get("went_well") or []][:10], "problems": [str(x) for x in retro.get("problems") or []][:10],
                     "action_items": actions[:10]}
    if errors:
        raise StepOutputError(tx("Toplantı çıktısı doğrulanamadı: ") + errors[0], errors[:6])
    return {"type": mtype, "summary": summary, "discussion": discussion, "decisions": decisions, "questions": questions,
            "commitment": commitment, "retro": retro, "scope_change": payload.get("scope_change") if isinstance(payload.get("scope_change"), dict) else None}


# ---------------------------------------------------------------------------
# Teslim: tutanak, sorular, kararlar
# ---------------------------------------------------------------------------
def meeting_inputs(hub, mtype: str, n: int) -> List[str]:
    lines: List[str] = []
    if mtype in ("kickoff", "planning"):
        cap, basis = SP.capacity(hub)
        for i in sorted((x for x in hub.jira_issues.values() if not x.get("deleted")), key=lambda x: int(x.get("order", 0) or 0)):
            co = i.get("carry_over") or {}
            if str(i.get("kind", "")).lower() == "task" and co.get("count") and i.get("status") == "BACKLOG":
                lines.append(tx("Taşınan iş: {id} ({reason}, {count}. taşıma)", id=i["id"], reason=co.get("last_reason"), count=co.get("count")) + (" — " + tx("yeniden kapsamlandı") if i.get("rescoped_at") else ""))
        pending = (SP.ensure_state(hub).get("pending_intake") or {}).get("spec_ids")
        for spec in hub.uploaded_specs[-3:]:
            lines.append(tx("Kasa kaydı: {id} · {title}", id=spec.get("id"), title=spec.get("title")))
        lines.append(tx("Kapasite: {cap} görev ({basis})", cap=cap, basis=basis))
        from . import learning as L
        lines += L.planning_inputs(hub, n)
    else:
        sp = SP.get_sprint(hub, n) or {}
        lines.append(tx("Taahhüt: {count} iş · hedef: {goal}", count=len(sp.get("committed_issue_ids", [])), goal=sp.get("goal")))
    for q in store(hub)["questions"]:
        if q["status"] == "OPEN":
            lines.append(tx("Açık soru: {id} ({category}) {text}", id=q["id"], category=q["category"], text=q["text"][:80]))
    return lines


async def deliver(hub, run, record, payload: Dict[str, Any], project_dir: str) -> Dict[str, Any]:
    """Doğrulanmış toplantı çıktısını işler: oturum turları, sorular, kararlar, tutanak. Toplantı kaydını döner."""
    mtype = record.work_type or "planning"
    n = int(record.sprint or SP.last_sprint_number(hub) or 1)
    data = normalize_payload(payload, mtype, list(hub.agents.keys()))
    mid = next_meeting_id(hub)
    engine = hub.deliberation_engine
    engine.open({"session_id": mid, "kind": "meeting", "title": tx("Sprint {n} · {type}", n=n, type=mtype), "meeting_notes": data["summary"]})
    for t in data["discussion"]:
        await engine.add_turn(mid, t["from"], f"[{t['topic']}] {t['message']}" if t["topic"] else t["message"], "PROPOSAL" if t["to"] == "ALL" else "AGREE")
    await engine.close(mid, {"decision": "MEETING_CLOSED", "chosen_plan": data["summary"][:120] or tx("{type} toplantısı", type=mtype)})

    m: Dict[str, Any] = {
        "id": mid, "type": mtype, "sprint": n, "date": _now()[:10], "opened_at": _now(), "run_id": run.run_id, "project_dir": project_dir,
        "participants": PARTICIPANTS, "summary": data["summary"], "discussion": data["discussion"], "decision_ids": [], "question_ids": [],
        "inputs": meeting_inputs(hub, mtype, n), "commitment": data["commitment"], "retro": data["retro"], "file": None,
    }
    for d in data["decisions"]:
        dec = {"id": next_decision_id(hub), "text": d["text"], "meeting": mid, "sprint": n, "adr": None, "question": None}
        SP.ensure_state(hub)["decisions"].append(dec)
        m["decision_ids"].append(dec["id"])
    for q in data["questions"]:
        raised = _now()
        rec = {"id": next_question_id(hub), "sprint": n, "meeting_id": mid, "category": q["category"], "raised_by": q["raised_by"], "text": q["text"],
               "options": q["options"], "recommended": q["recommended"], "rationale": q["rationale"], "blocking": q["category"] in BLOCKING_CATEGORIES,
               "raised_at": raised, "deadline": deadline_for(hub, q["category"], raised), "status": "OPEN", "answer": None, "answered_by": None,
               "answered_at": None, "decision_ref": None, "adr_ref": None, "adr_draft": q["adr"]}
        store(hub)["questions"].append(rec)
        m["question_ids"].append(rec["id"])
        await hub.record_event(trace_id=run.run_id, from_agent=q["raised_by"] if q["raised_by"] in hub.agents else "SCRUM_MASTER", to_agent="MANAGER",
                               action="QUESTION_RAISED", status="IN_PROGRESS", payload={"question": rec["id"], "category": rec["category"], "blocking": rec["blocking"]},
                               friendly_dialogue=tx("Soru açıldı ({id}, {category}): {text}", id=rec["id"], category=rec["category"], text=rec["text"][:100]))
        await hub.broadcast({"type": "QUESTION_RAISED", "question": {k: v for k, v in rec.items() if k != "adr_draft"}})
    SP.ensure_state(hub)["meetings"].append(m)
    if data["commitment"]:
        SP.ensure_state(hub)["meeting_commitments"][str(n)] = data["commitment"]
    sp = SP.get_sprint(hub, n)
    if data["retro"] and sp is not None:
        sp["retro"] = data["retro"]
    if sp is not None:
        sp["meetings"]["review_retro" if mtype == "review-retro" else "planning"] = None
    await write_minutes(hub, m)
    _dump_jsonl(project_dir, m)
    if sp is not None:
        sp["meetings"]["review_retro" if mtype == "review-retro" else "planning"] = m["file"]
    hub.mark_dirty()
    await hub.broadcast({"type": "MEETING_CLOSED", "meeting": {k: v for k, v in m.items() if k not in ("discussion", "inputs")}})
    return m


def _dump_jsonl(project_dir: str, m: Dict[str, Any]) -> None:
    """`.fs-workspace/meetings/<id>.jsonl`: tur dökümü (git dışı, §5.4)."""
    try:
        base = os.path.join(project_dir, ".fs-workspace", "meetings")
        os.makedirs(base, exist_ok=True)
        with open(os.path.join(base, f"{m['id']}.jsonl"), "w", encoding="utf-8", newline="\n") as fh:
            for t in m["discussion"]:
                fh.write(json.dumps({"meeting": m["id"], **t}, ensure_ascii=False) + "\n")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Tutanak (§10.5)
# ---------------------------------------------------------------------------
def render_minutes(hub, m: Dict[str, Any]) -> str:
    docs_rel = hub_docs_path(hub, "", m.get("project_dir"))
    a = autonomy(hub)
    qs = {q["id"]: q for q in store(hub)["questions"]}
    decs = {d["id"]: d for d in SP.ensure_state(hub)["decisions"]}
    label = tx({"kickoff": N_("kickoff"), "planning": N_("planlama"), "review-retro": N_("değerlendirme ve retrospektif"), "arch-review": N_("mimari gözden geçirme"), "adhoc": N_("acil girdi")}[m["type"]])
    lines = [tx("# Toplantı tutanağı: Sprint {n} {label}", n=m["sprint"], label=label), "",
             tx("- **Kimlik:** {id} · **Tip:** {type} · **Sprint:** {n} · **Tarih:** {date}", id=m["id"], type=m["type"], n=m["sprint"], date=m["date"]),
             tx("- **Katılımcılar:** SCRUM_MASTER (moderatör), {others}; MANAGER (soru yoluyla)", others=", ".join(p for p in m["participants"] if p != "SCRUM_MASTER")),
             tx("- **Otonomi:** {level} · taahhüt onayı: {approval}", level=a["level"], approval=SP.cfg(hub)["commit_approval"]), "", tx("## 1. Girdiler")]
    lines += [f"- {x}" for x in m["inputs"]] or [tx("- Yok.")]
    lines += ["", tx("## 2. Tartışma")]
    lines += [f"- **{t['from']} → {t['to']} — {t['topic'] or tx('genel')}:** {t['message']}" for t in m["discussion"]] or [tx("- Yok.")]
    lines += ["", tx("## 3. Kararlar")]
    rows = []
    for did in m["decision_ids"]:
        rows.append(f"- **{did}** {decs[did]['text']}")
    for qid in m["question_ids"]:
        q = qs.get(qid)
        if q and q.get("decision_ref"):
            d = decs.get(q["decision_ref"], {})
            link = f" → [ADR {os.path.basename(q['adr_ref'])[:4]}](../adr/{os.path.basename(q['adr_ref'])})" if q.get("adr_ref") else ""
            who = tx("yönetici onayı") if q["status"] in ("ANSWERED", "OVERRIDDEN") else tx("**VARSAYIM**: süre doldu")
            rows.append(f"- **{q['decision_ref']}** {d.get('text', q['text'])}{link} ({q['id']}, {who})")
    lines += rows or [tx("- Yok.")]
    lines += ["", tx("## 4. Sorular")]
    if m["question_ids"]:
        lines += [tx("| Soru | Kategori | Öneri | Sonuç |"), "|---|---|---|---|"]
        for qid in m["question_ids"]:
            q = qs[qid]
            outcome = {"OPEN": tx("Açık") + (" " + tx("(engelleyici)") if q["blocking"] else ""), "ANSWERED": tx("Yönetici: {answer}", answer=q["answer"]),
                       "DEFAULTED": tx("Süre doldu, varsayılan: {answer}", answer=q["answer"]), "OVERRIDDEN": tx("Yönetici değiştirdi: {answer}", answer=q["answer"])}[q["status"]]
            lines.append(f"| {q['id']} {q['text'][:60]} | {q['category']}{' ' + tx('(engelleyici)') if q['blocking'] else ''} | {q['recommended']} | {outcome} |")
    else:
        lines.append(tx("Yok."))
    if m["commitment"]:
        c = m["commitment"]
        lines += ["", tx("## 5. Sprint {n} taahhüdü", n=m["sprint"]), tx("**Hedef:** {goal}", goal=c.get("goal", "-")), ""]
        items = [hub.jira_issues.get(i) for i in c.get("items", [])]
        if any(items):
            lines += [tx("| İş | Tür | Başlık | Rol | Öncelik | Bağımlılık | Kabul kriteri |"), "|---|---|---|---|---|---|---|"]
            for i in items:
                if i:
                    lines.append(f"| {i['id']} | {i.get('work_type') or '-'} | {str(i.get('title'))[:70]} | {i.get('assignee')} | {i.get('priority')} | "
                                 f"{', '.join(i.get('depends_on') or []) or '—'} | {', '.join(i.get('ac_refs') or []) or '—'} |")
        if c.get("out_of_scope"):
            lines += ["", tx("**Kapsam dışı:** ") + "; ".join(f"{o.get('issue_id')} ({o.get('reason')})" for o in c["out_of_scope"])]
    if m["retro"]:
        r = m["retro"]
        sp = SP.get_sprint(hub, m["sprint"]) or {}
        met = sp.get("metrics") or {}
        lines += ["", tx("## 5. Kabul özeti ve metrikler")]
        if met:
            lines.append(tx("- Taahhüt {committed} · tamamlanan {completed} · ilk seferde {first_pass} · düzeltme turu {fix_rounds} · "
                            "UAT reddi {uat_rejections} · E2E {e2e} · etkin süre {active_min} dk · token {tokens}", committed=met.get("committed"), completed=met.get("completed"),
                            first_pass=met.get("first_pass"), fix_rounds=met.get("fix_rounds"), uat_rejections=met.get("uat_rejections"), e2e=met.get("e2e"),
                            active_min=met.get("active_min"), tokens=met.get("tokens")))
        dod = sp.get("dod")
        if dod:
            lines.append(tx("- Sıkı DoD: E2E {e2e}{bug} · konteyner {container} · mimar gözden geçirmesi {arch} · PO kriter kararları {po}", e2e=dod["e2e"]["status"],
                            bug=" " + tx("(hata maddesi açıldı)") if dod["e2e"].get("bug_opened") else "", container=dod["container"]["status"],
                            arch=tx("yapıldı") if dod["arch_review"]["done"] else tx("YAPILMADI"), po=tx("verildi") if dod["po"]["decided"] else tx("EKSİK")))
        lines += ["", tx("### İyi giden")] + ([f"- {x}" for x in r["went_well"]] or [tx("- Yok.")])
        lines += ["", tx("### Sorunlar")] + ([f"- {x}" for x in r["problems"]] or [tx("- Yok.")])
        done = {a["id"]: a for a in SP.ensure_state(hub).get("retro_actions", []) if a["sprint"] == m["sprint"]}
        acts = []
        for i, x in enumerate(r["action_items"], 1):
            res = done.get(f"RA-{m['sprint']}-{i}")
            acts.append(f"- `{x['type']}` {x.get('target', '')} → {x.get('value', '')} — {x.get('reason', '')}" + (f" **[{res['status']}]** {res['detail']}" if res else ""))
        lines += ["", tx("### Retro aksiyonları")] + (acts or [tx("- Yok.")])
    lines += ["", f"## {6 if not m['retro'] else 6}. " + tx("Sonraki adım"),
              tx("Taahhüt kesinleşince görev adımları sunucu tarafından kuyruğa alınır.") if m["commitment"] else tx("Sprint kapanışı sunucu tarafından yapılır; taşınan işler sonraki planlamaya girer."),
              "", tx("_Bu tutanak sunucu tarafından yapılandırılmış sonuçtan üretildi ({docs})._", docs=docs_rel)]
    from . import guard as G
    return G.redact("\n".join(lines)) + "\n"      # şartnamedeki/konuşmadaki gizli değerler tutanağa kopyalanmaz (§12 madde 4)


async def write_minutes(hub, m: Dict[str, Any]) -> None:
    project_dir = m.get("project_dir") or ""
    docs_rel = hub_docs_path(hub, "", project_dir)
    sprint_part = f"sprint-{m['sprint']}-{'kickoff' if m['type'] == 'kickoff' else m['type']}"
    rel = f"{docs_rel}/meetings/{m['date']}_{sprint_part}.md"
    m["file"] = SP._write(project_dir, rel, render_minutes(hub, m)) or rel


# ---------------------------------------------------------------------------
# Soru yaşam döngüsü: cevap, varsayılan, değiştirme (§3.3)
# ---------------------------------------------------------------------------
def open_blocking(hub) -> List[Dict[str, Any]]:
    return [q for q in store(hub)["questions"] if q["status"] == "OPEN" and q["blocking"]]


def _find(hub, qid: str) -> Dict[str, Any]:
    q = next((x for x in store(hub)["questions"] if x["id"] == qid), None)
    if q is None:
        raise KeyError(qid)
    return q


async def open_system_question(hub, *, category: str, raised_by: str, text: str, options: List[Dict[str, str]], recommended: str, rationale: str,
                               action: Optional[Dict[str, Any]] = None, sprint: Optional[int] = None, adr: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """Toplantı dışında sunucunun açtığı soru (ör. izin listesi dışı komut, §12 madde 1). Aynı eylem için açık soru varsa yenisini açmaz."""
    if action and any(q["status"] == "OPEN" and q.get("action") == action for q in store(hub)["questions"]):
        return None
    raised = _now()
    rec = {"id": next_question_id(hub), "sprint": sprint, "meeting_id": None, "category": category, "raised_by": raised_by, "text": text[:400], "options": options,
           "recommended": recommended, "rationale": rationale, "blocking": category in BLOCKING_CATEGORIES, "raised_at": raised,
           "deadline": deadline_for(hub, category, raised), "status": "OPEN", "answer": None, "answered_by": None, "answered_at": None,
           "decision_ref": None, "adr_ref": None, "adr_draft": adr, "action": action}
    store(hub)["questions"].append(rec)
    await hub.record_event(trace_id=f"question-{rec['id']}", from_agent=raised_by if raised_by in hub.agents else "SCRUM_MASTER", to_agent="MANAGER",
                           action="QUESTION_RAISED", status="IN_PROGRESS", payload={"question": rec["id"], "category": category, "blocking": rec["blocking"]},
                           friendly_dialogue=tx("Soru açıldı ({id}, {category}): {text}", id=rec["id"], category=category, text=text[:100]))
    await hub.broadcast({"type": "QUESTION_RAISED", "question": {k: v for k, v in rec.items() if k != "adr_draft"}})
    hub.mark_dirty()
    return rec


async def _apply_action(hub, q: Dict[str, Any]) -> None:
    """Cevaba bağlı sunucu eylemi: `allow_command` A → komut öneki izin listesine eklenir ve doğrulama komutu ayarlara yazılır."""
    act = q.get("action") or {}
    if act.get("type") == "allow_command" and q.get("answer") == "A":
        from . import guard as G
        cur = G.sandbox(hub)
        await hub.update_settings({"sandbox": {"allowlist": [*cur["allowlist"], act["prefix"]]}})
        if act.get("key"):
            from .verify import sanitize_verification
            ver = {**(hub.get_settings().get("verification") or {}), **sanitize_verification({act["key"]: act["cmd"]})}
            await hub.update_settings({"verification": ver})


async def _decide(hub, q: Dict[str, Any], key: str, by: str, status: str) -> None:
    """Kararı ve ADR'yi üretir. TECHNOLOGY ADR'si hiçbir zaman VARSAYIM olmaz."""
    opt = next(o for o in q["options"] if o["key"] == key)
    dec = {"id": next_decision_id(hub), "text": f"{q['text']} → {opt['label']}", "meeting": q["meeting_id"], "sprint": q["sprint"], "adr": None, "question": q["id"],
           # §12 madde 9: insan onayı olmadan verilen her karar neden ve alternatifleriyle kaydedilir
           "decided_by": by, "basis": q["rationale"], "alternatives": [o["label"] for o in q["options"] if o["key"] != key],
           "human_approved": status in ("ANSWERED", "OVERRIDDEN")}
    SP.ensure_state(hub)["decisions"].append(dec)
    q["decision_ref"] = dec["id"]
    meeting = next((m for m in SP.ensure_state(hub)["meetings"] if m["id"] == q["meeting_id"]), None)
    project_dir = (meeting or {}).get("project_dir") or hub.projects.get(hub.active_project_id, {}).get("path") or hub.default_project_path
    draft = q.get("adr_draft")
    if draft and os.path.isdir(project_dir):
        manager = status in ("ANSWERED", "OVERRIDDEN")
        res = ADR.write_adr(
            project_dir, hub_docs_path(hub, "", project_dir), title=str(draft.get("title") or q["text"][:60]), status="KABUL EDİLDİ" if manager else "VARSAYIM",
            context=str(draft.get("context") or q["text"]), options=[o["label"] for o in q["options"]], chosen=opt["label"], rationale=q["rationale"],
            consequences={"positive": list((draft.get("consequences") or {}).get("positive", [])), "negative": list((draft.get("consequences") or {}).get("negative", []))},
            sprint=q["sprint"], decision_ref=dec["id"], question_ref=q["id"],
            decider=tx("Yönetici") if manager else tx("{who} önerisi (yönetici süresi içinde cevaplamadı)", who=q["raised_by"]),
            reversible=bool(draft.get("reversible", True)), technology=q["category"] == "TECHNOLOGY")
        q["adr_ref"] = res["file"]
        dec["adr"] = res["file"]
        await hub.broadcast({"type": "ADR_RECORDED", "adr": res, "decision": dec["id"], "question": q["id"]})
    if meeting is not None:
        await write_minutes(hub, meeting)
    hub.mark_dirty()


CUSTOM_KEY = "CUSTOM"
CUSTOM_MAX_CHARS = 500


async def answer_question(hub, qid: str, key: str, by: str = "MANAGER", custom_text: Optional[str] = None) -> Dict[str, Any]:
    """Yönetici cevabı. `DEFAULTED` bir soruya farklı cevap → OVERRIDDEN: eski ADR YERİNİ ALDI, değişiklik görevi açılır; aynı cevap VARSAYIM'ı onaylar.
    `custom_text`: seçeneklerin dışında serbest metin cevap; 'Diğer' (key CUSTOM) seçeneği olarak kaydedilir ve karar/ADR'de metin aynen görünür."""
    q = _find(hub, qid)
    if custom_text is not None:
        text = str(custom_text).strip()
        if not text:
            raise ValueError(tx("Serbest metin cevap boş olamaz."))
        text = text[:CUSTOM_MAX_CHARS]
        existing = next((o for o in q["options"] if o["key"] == CUSTOM_KEY), None)
        if existing is None:
            q["options"].append({"key": CUSTOM_KEY, "label": text, "custom": True})
        else:
            existing["label"] = text
        key = CUSTOM_KEY
    key = str(key).strip()
    if key not in {o["key"] for o in q["options"]}:
        raise ValueError(tx("Geçersiz seçenek: {key!r}; geçerli: {valid}", key=key, valid=", ".join(o["key"] for o in q["options"])))
    if q["status"] in ("ANSWERED", "OVERRIDDEN"):
        raise ValueError(tx("{qid} zaten cevaplandı.", qid=qid))
    now = _now()
    if q["status"] == "OPEN":
        q.update({"status": "ANSWERED", "answer": key, "answered_by": by, "answered_at": now})
        await _decide(hub, q, key, by, "ANSWERED")
        await _apply_action(hub, q)
        action = "QUESTION_ANSWERED"
    else:   # DEFAULTED
        old_adr, old_key = q.get("adr_ref"), q["answer"]
        if key == old_key:
            q.update({"status": "ANSWERED", "answered_by": by, "answered_at": now})
            if old_adr:
                project_dir = next((m for m in SP.ensure_state(hub)["meetings"] if m["id"] == q["meeting_id"]), {}).get("project_dir") or hub.default_project_path
                ADR.set_status(project_dir, old_adr, "KABUL EDİLDİ", tx("yönetici onayladı"))
            action = "QUESTION_ANSWERED"
        else:
            q.update({"status": "OVERRIDDEN", "answer": key, "answered_by": by, "answered_at": now})
            await _decide(hub, q, key, by, "OVERRIDDEN")
            if old_adr:
                project_dir = next((m for m in SP.ensure_state(hub)["meetings"] if m["id"] == q["meeting_id"]), {}).get("project_dir") or hub.default_project_path
                ADR.set_status(project_dir, old_adr, "YERİNİ ALDI", tx("yeni karar: {num}", num=os.path.basename(q["adr_ref"] or "")[:4]))
            order = max([int(i.get("order", 0) or 0) for i in hub.jira_issues.values()] or [0]) + 1
            label = next(o["label"] for o in q["options"] if o["key"] == key)
            await hub.update_jira_issue(f"JIRA-{order}", {
                "order": order, "title": tx("Karar değişikliğini uygula ({id}): {label}", id=q["id"], label=label)[:160], "description": tx("Yönetici varsayılan kararı değiştirdi: {text}", text=q["text"]),
                "issue_type": "TASK", "status": "BACKLOG", "priority": "P1", "assignee": "BACKEND_DEV", "kind": "task", "work_type": "REFACTOR",
                "task_key": SP.next_key(hub, "T"), "origin": "MANAGER", "agent_id": "SCRUM_MASTER", "audit_action": "TASK_CREATED",
                "audit_notes": tx("{id} varsayılan karar yönetici tarafından değiştirildi.", id=q["id"])})
            action = "QUESTION_OVERRIDDEN"
    await hub.record_event(trace_id=f"question-{qid}", from_agent="PM", to_agent="SCRUM_MASTER", action=action, status="SUCCESS",
                           payload={"question": qid, "answer": q["answer"], "by": by}, friendly_dialogue=tx("{qid} cevaplandı: {answer} ({by}).", qid=qid, answer=q["answer"], by=by))
    await hub.broadcast({"type": action, "question": {k: v for k, v in q.items() if k != "adr_draft"}})
    await _release_gate_if_clear(hub)
    return q


async def expire_questions(hub) -> List[str]:
    """Süresi dolan teknoloji dışı soruları önerilen cevapla `DEFAULTED` yapar (VARSAYIM ADR'si). Teknoloji sorusu hiçbir zaman süreyle geçilmez."""
    out: List[str] = []
    now = datetime.now(timezone.utc)
    for q in store(hub)["questions"]:
        if q["status"] != "OPEN" or q["blocking"] or not q.get("deadline"):
            continue
        if datetime.fromisoformat(q["deadline"]) <= now:
            by = "SERVER" if autonomy(hub)["question_timeout_s"] == 0 else "TIMEOUT"
            q.update({"status": "DEFAULTED", "answer": q["recommended"], "answered_by": by, "answered_at": _now()})
            await _decide(hub, q, q["recommended"], by, "DEFAULTED")
            await hub.record_event(trace_id=f"question-{q['id']}", from_agent="SCRUM_MASTER", to_agent="MANAGER", action="QUESTION_DEFAULTED", status="SUCCESS",
                                   payload={"question": q["id"], "answer": q["answer"], "by": by},
                                   friendly_dialogue=tx("{id} için süre doldu; önerilen cevapla devam ({answer}).", id=q["id"], answer=q["answer"]))
            await hub.broadcast({"type": "QUESTION_DEFAULTED", "question": {k: v for k, v in q.items() if k != "adr_draft"}})
            out.append(q["id"])
    return out


async def _release_gate_if_clear(hub) -> None:
    """Engelleyici soru kalmadıysa bekleyen 'questions' kapısını çöz."""
    pending = hub.pending_step_approval or {}
    if pending.get("kind") == "questions" and hub.approval_token and not open_blocking(hub):
        hub.gate.resolve(hub.approval_token, "PROCEED")
    if not open_blocking(hub):
        # Sprint ortasında açılan engelleyici soru (koşu duraklatılmıştı): cevaplanınca sprint kendiliğinden sürer
        from . import driver as DRV
        for sp in SP.ensure_state(hub)["sprints"]:
            if sp["status"] == "BLOCKED" and (sp.get("blocked") or {}).get("reason") == "BLOCKING_QUESTION":
                run = next((r for r in hub.runs.values() if not r.is_terminal and r.paused and str(r.pause_reason).startswith("BLOCKED:BLOCKING_QUESTION")), None)
                if run is not None:
                    await DRV.unblock_sprint(hub, sp["sprint_number"])
