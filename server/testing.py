"""
G7 — test ekibi (plan §4.3): test case belgeleri (`TC-n`), test run (`TEST_RUN`), test planı, izlenebilirlik matrisi, otomatik BUG, kararsız test takibi.

Akış
- QA sprint başında `TEST_DESIGN` görevini alır ve kabul kriterlerinden test case'leri **kendisi üretir** (`payload.testcases[]`); sunucu doğrular, `TC-n` kimliği verir,
  `<docs>/tests/TC-n.md` yazar ve Jira'da `TEST_CASE` maddesi açar (hikâyeye `tests` bağıyla bağlanır).
- QA (adım 6) ve E2E (adım 7) doğrulamalarından sonra sunucu bir `TEST_RUN` kaydeder: case başına sonuç (PASS/FAIL/BLOCKED/SKIP) junit, E2E senaryosu ya da sağlık-adresi
  gecikme ölçümünden gelir. Başarısız case otomatik `BUG` açar (yeniden üretim adımları case'ten); art arda farklı sonuç veren case `flaky` etiketi alır ve karantinaya girer.
- İzlenebilirlik matrisi: kabul kriteri ↔ case ↔ otomasyon ↔ sonuç; kapsama yüzdesi ve kanıtsız kriter listesi. PO kararı ve sprint kapanış DoD'u (regresyon kümesi geçti) buna dayanır.
Veri `sprint_state["testing"]` altında durur (proje durumuyla birlikte kalıcıdır); case belgeleri hedef projede, Jira maddeleri `hub.jira_issues` içindedir.
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.request
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from . import guard as G
from . import sprint as SP
from .i18n import translate as tx
from .paths import hub_docs_path

CASE_TYPES = ("unit", "integration", "e2e", "security", "performance", "exploratory")
CASE_STATUSES = ("DRAFT", "READY", "DEPRECATED")
RESULTS = ("PASS", "FAIL", "BLOCKED", "SKIP")
PRIORITIES = ("P0", "P1", "P2")
# Hangi kaynak (QA koşusu / E2E koşusu) hangi case türlerini yürütür; keşif (exploratory) case'leri elle çalışır
SOURCE_TYPES = {"QA": ("unit", "integration", "security"), "E2E_TESTER": ("e2e", "performance")}      # performans ölçümü uygulama ayaktayken (E2E adımı)
FLAKY_WINDOW = 6
FLAKY_FLIPS = 2
HISTORY_MAX = 12
CASE_ISSUE_STATUS = {"PASS": "DONE", "FAIL": "IN_PROGRESS"}
DEFAULT_CONFIG = {"coverage_target": 80, "perf_p95_ms": 1000, "perf_samples": 10, "design_task": True, "auto_regression": True}
_AC_RX = re.compile(r"^AC-(\d+)$")


class CaseError(ValueError):
    """Geçersiz test case / run girdisi (HTTP 400)."""


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Kayıt
# ---------------------------------------------------------------------------
def store(hub) -> Dict[str, Any]:
    st = SP.ensure_state(hub).setdefault("testing", {})
    st.setdefault("cases", {})
    st.setdefault("runs", {})
    st.setdefault("seq", {"case": 0, "run": 0})
    st.setdefault("config", {})
    return st


def config(hub) -> Dict[str, Any]:
    return {**DEFAULT_CONFIG, **(store(hub).get("config") or {})}


def set_config(hub, updates: Dict[str, Any]) -> Dict[str, Any]:
    cur = dict(store(hub).get("config") or {})
    for key, val in (updates or {}).items():
        if key not in DEFAULT_CONFIG:
            continue
        if isinstance(DEFAULT_CONFIG[key], bool):
            cur[key] = bool(val)
        else:
            try:
                num = int(val)
            except (TypeError, ValueError):
                raise CaseError(tx("{key} tamsayı olmalı.", key=key))
            if not (0 <= num <= (100 if key == "coverage_target" else 600000)):
                raise CaseError(tx("{key} aralık dışında.", key=key))
            cur[key] = num
    store(hub)["config"] = cur
    hub.mark_dirty()
    return config(hub)


def design_enabled(hub) -> bool:
    """Sunucu backlog'a QA `TEST_DESIGN` görevi ekler mi? Ayar açıkken ve sıkı DoD'da (üretim varsayılanı); sıkı DoD kapalıyken mevcut davranış aynen kalır."""
    try:
        from . import meetings as M
        from . import sprint as _SP
        if _SP.cfg(hub).get("no_tests"):
            return False                   # test yazımı geçici olarak durduruldu: QA TEST_DESIGN görevi eklenmez
        return bool(config(hub)["design_task"] and M.autonomy(hub)["strict_dod"])
    except Exception:
        return False


def has_ready(hub, case_type: str) -> bool:
    return any(c["status"] == "READY" and c["type"] == case_type for c in store(hub)["cases"].values())


def qa_context(hub) -> str:
    """QA adımının bağlamı: henüz otomasyon sonucu olmayan hazır case'ler (testin adına/yorumuna `TC-n` yazılırsa koşuda case'e bağlanır)."""
    todo = [c for c in store(hub)["cases"].values() if c["status"] == "READY" and c["type"] in SOURCE_TYPES["QA"]
            and (not c.get("last_result") or (c["last_result"] or {}).get("result") == "BLOCKED")]
    if not todo:
        return ""
    lines = [tx("## Test case'leri (TEST_DESIGN çıktısı)"), tx("Aşağıdaki case'ler için GERÇEK otomatik test yaz; testin adına ya da yorumuna `TC-n` kimliğini yaz (örn. `def test_tc3_giris(): # TC-3`). "
             "Sunucu junit sonucunu case'e bağlar; geçen case kabul kriterinin kanıtıdır, kalan case BUG açar.")]
    for c in sorted(todo, key=lambda c: _num(c["id"]))[:40]:
        lines.append(tx("- {id} · {type} · {priority} · {acs} · {title} · otomasyon: {automation}", id=c['id'], type=c['type'], priority=c['priority'],
                        acs=','.join(c['ac_refs']) or '-', title=c['title'], automation=c['automation']))
    return "\n".join(lines)


def _docs(hub) -> str:
    return hub_docs_path(hub, "").strip("/")


def _project_dir(hub) -> str:
    """Case belgelerinin yazıldığı proje klasörü: son koşunun klasörü (kuru koşuda hedef klasör etkin projeden farklı olabilir), yoksa etkin proje."""
    d = store(hub).get("project_dir")
    if d and os.path.isdir(d):
        return d
    return (hub.projects.get(hub.active_project_id) or {}).get("path") or ""


def remember_project_dir(hub, project_dir: Optional[str]) -> None:
    if project_dir and os.path.isdir(project_dir):
        store(hub)["project_dir"] = project_dir


def _next_order(hub) -> int:
    orders = [int(i.get("order", 0) or 0) for i in hub.jira_issues.values()]
    return (max(orders) if orders else 0) + 1


def _num(case_id: str) -> int:
    m = re.search(r"(\d+)$", str(case_id))
    return int(m.group(1)) if m else 0


# ---------------------------------------------------------------------------
# Case modeli
# ---------------------------------------------------------------------------
def _ac_list(value: Any) -> List[str]:
    out: List[str] = []
    for item in value if isinstance(value, (list, tuple)) else ([value] if value else []):
        s = re.sub(r"[_\s]+", "-", str(item).strip().upper())
        if _AC_RX.match(s) and s not in out:
            out.append(s)
    return out[:20]


def _steps(value: Any) -> List[str]:
    if isinstance(value, str):
        value = [re.sub(r"^\s*\d+[.)]\s*", "", ln) for ln in value.splitlines()]
    return [str(s).strip()[:400] for s in (value if isinstance(value, (list, tuple)) else []) if str(s).strip()][:30]


def _automation(value: Any) -> str:
    s = str(value or "MANUAL").strip()
    if s.upper() == "MANUAL" or not s:
        return "MANUAL"
    ref = s.split(":", 1)[1].strip() if ":" in s else s
    if s.upper().startswith("AUTOMATED") and ref and ref.upper() != "AUTOMATED":
        return f"AUTOMATED:{ref[:120]}"
    raise CaseError(tx("automation `MANUAL` ya da `AUTOMATED:<test adı / senaryo kimliği>` olmalı."))


def resolve_story(hub, ref: Any) -> Optional[str]:
    """`story_ref`: hikâye maddesinin kimliği (JIRA-n); bilinmiyorsa None."""
    s = str(ref or "").strip()
    issue = hub.jira_issues.get(s)
    return s if issue and str(issue.get("kind", "")).lower() == "story" and not issue.get("deleted") else None


def normalize_case(hub, raw: Dict[str, Any], base: Optional[Dict[str, Any]] = None, partial: bool = False,
                   default_status: str = "DRAFT") -> Dict[str, Any]:
    """Ham girdiyi case alanlarına indirger. `partial=True` (güncelleme): yalnızca verilen alanlar; aksi halde başlık, adımlar ve beklenen sonuç zorunlu."""
    if not isinstance(raw, dict):
        raise CaseError(tx("Test case bir nesne olmalı."))
    cur = base or {}
    out: Dict[str, Any] = {}

    def has(k: str) -> bool:
        return k in raw and raw[k] is not None

    if has("title"):
        out["title"] = str(raw["title"]).strip()[:160]
    if has("type"):
        t = str(raw["type"]).strip().lower()
        if t not in CASE_TYPES:
            raise CaseError(tx("Geçersiz case türü '{value}': {allowed}.", value=raw['type'], allowed=', '.join(CASE_TYPES)))
        out["type"] = t
    if has("priority"):
        p = str(raw["priority"]).strip().upper()
        if p not in PRIORITIES:
            raise CaseError(tx("Geçersiz öncelik '{value}': {allowed}.", value=raw['priority'], allowed=', '.join(PRIORITIES)))
        out["priority"] = p
    if has("status"):
        s = str(raw["status"]).strip().upper()
        if s not in CASE_STATUSES:
            raise CaseError(tx("Geçersiz durum '{value}': {allowed}.", value=raw['status'], allowed=', '.join(CASE_STATUSES)))
        out["status"] = s
    if has("ac_refs"):
        out["ac_refs"] = _ac_list(raw["ac_refs"])
    if has("story_ref"):
        out["story_ref"] = resolve_story(hub, raw["story_ref"]) or ""
    if has("steps"):
        out["steps"] = _steps(raw["steps"])
    if has("expected"):
        exp = raw["expected"]
        out["expected"] = ("\n".join(str(x) for x in exp) if isinstance(exp, (list, tuple)) else str(exp)).strip()[:1500]
    if has("precondition"):
        out["precondition"] = str(raw["precondition"]).strip()[:600]
    if has("data"):
        out["data"] = str(raw["data"]).strip()[:600]
    if has("automation"):
        out["automation"] = _automation(raw["automation"])
    if has("labels"):
        labels = raw["labels"].split(",") if isinstance(raw["labels"], str) else raw["labels"]
        out["labels"] = [str(x).strip().lower()[:30] for x in (labels if isinstance(labels, (list, tuple)) else []) if str(x).strip()][:10]
    if has("quarantined"):
        out["quarantined"] = bool(raw["quarantined"])
    if partial:
        if "steps" in out and not out["steps"]:
            raise CaseError(tx("steps boş olamaz."))
        return out
    full = {**{k: cur.get(k) for k in ("title", "type", "priority", "status", "ac_refs", "story_ref", "steps", "expected", "precondition", "data", "automation", "labels")}, **out}
    if not full.get("title"):
        raise CaseError(tx("Case başlığı zorunlu."))
    if not full.get("steps"):
        raise CaseError(tx("'{title}': adımlar (steps[]) zorunlu.", title=full['title'][:60]))
    if not str(full.get("expected") or "").strip():
        raise CaseError(tx("'{title}': beklenen sonuç (expected) zorunlu.", title=full['title'][:60]))
    story = full.get("story_ref") or ""
    acs = list(full.get("ac_refs") or [])
    if not acs and story:                                    # kriter verilmediyse hikâyenin kriterleri bağlanır
        acs = [a for a in ((hub.jira_issues.get(story) or {}).get("ac_refs") or []) if _AC_RX.match(str(a))]
    return {
        "title": full["title"], "type": full.get("type") or "integration", "priority": full.get("priority") or "P1",
        "status": full.get("status") or default_status, "ac_refs": acs, "story_ref": story, "steps": full["steps"], "expected": full["expected"],
        "precondition": full.get("precondition") or "", "data": full.get("data") or "", "automation": full.get("automation") or "MANUAL",
        "labels": list(full.get("labels") or []), "quarantined": bool(out.get("quarantined", cur.get("quarantined", False))),
    }


def case_markdown(case: Dict[str, Any]) -> str:
    steps = "\n".join(f"{i}. {s}" for i, s in enumerate(case["steps"], 1))
    lines = [f"# {case['id']} — {case['title']}", "",
             tx("- **Tür:** {type} · **Öncelik:** {priority} · **Durum:** {status}", type=case['type'], priority=case['priority'], status=case['status']),
             tx("- **Otomasyon:** {automation} · **Sahibi:** {owner}", automation=case['automation'], owner=case.get('owner') or 'QA'),
             tx("- **Kabul kriterleri:** {acs} · **Hikâye:** {story}", acs=', '.join(case['ac_refs']) or '-', story=case.get('story_ref') or '-')
             + (f" · **Jira:** {case['issue_id']}" if case.get("issue_id") else ""),
             tx("- **Etiketler:** {labels}", labels=', '.join(case['labels']) or '-') + (tx(" · **KARANTİNA (kararsız)**") if case.get("quarantined") else ""), ""]
    if case.get("precondition"):
        lines += [tx("## Ön koşul"), case["precondition"], ""]
    lines += [tx("## Adımlar"), steps, "", tx("## Beklenen sonuç"), case["expected"], ""]
    if case.get("data"):
        lines += [tx("## Veri"), case["data"], ""]
    lr = case.get("last_result")
    if lr:
        lines += [tx("## Son sonuç"), f"{lr['result']} ({lr.get('run')}, {lr.get('at', '')[:19]})" + (f" — {lr['message']}" if lr.get("message") else ""), ""]
    return "\n".join(lines)


def _write_case_file(hub, case: Dict[str, Any]) -> Optional[str]:
    pdir = _project_dir(hub)
    return SP._write(pdir, f"{_docs(hub)}/tests/{case['id']}.md", case_markdown(case), overwrite=True) if pdir else None


def _issue_data(hub, case: Dict[str, Any]) -> Dict[str, Any]:
    data: Dict[str, Any] = {
        "title": f"{case['id']}: {case['title']}"[:160], "description": case_markdown(case), "issue_type": "TEST_CASE", "kind": "testcase", "status": "BACKLOG",
        "priority": case["priority"], "assignee": "QA", "acceptance_criteria": [case["expected"][:300]], "ac_refs": list(case["ac_refs"]),
        "labels": list(case["labels"]), "origin": "TEST", "case_id": case["id"], "parent_id": case.get("story_ref") or None, "agent_id": "QA",
    }
    if case.get("file"):
        data["attachments"] = [case["file"]]
    return data


# ---------------------------------------------------------------------------
# Oluşturma / güncelleme
# ---------------------------------------------------------------------------
async def create_case(hub, raw: Dict[str, Any], *, sprint: Optional[int] = None, by: str = "QA", default_status: str = "READY") -> Dict[str, Any]:
    body = normalize_case(hub, raw, default_status=default_status)
    st = store(hub)
    st["seq"]["case"] = int(st["seq"].get("case", 0)) + 1
    cid = f"TC-{st['seq']['case']}"
    case = {"id": cid, **body, "owner": by, "created_at": now(), "updated_at": now(), "created_sprint": sprint, "last_result": None, "history": [],
            "open_bug": None, "flaky_issue": None, "issue_id": None, "file": None}
    case["file"] = _write_case_file(hub, case)
    issue_id = f"JIRA-{_next_order(hub)}"
    await hub.update_jira_issue(issue_id, {"order": _next_order(hub), **_issue_data(hub, case), "audit_action": "TEST_CASE_CREATED",
                                           "audit_notes": tx("{by} test case'i oluşturdu ({cid}, {type}, {automation})", by=by, cid=cid, type=case['type'], automation=case['automation'])})
    case["issue_id"] = issue_id
    if case["story_ref"]:
        _link(hub, issue_id, case["story_ref"], "tests")
    st["cases"][cid] = case
    hub.mark_dirty()
    return case


def _link(hub, a: str, b: str, kind: str) -> None:
    """a --kind--> b (ters bağ hedefte)."""
    from .jira_plus import LINK_INVERSE, ensure_fields
    ia, ib = hub.jira_issues.get(a), hub.jira_issues.get(b)
    if not ia or not ib or kind not in LINK_INVERSE:
        return
    for src, dst, k in ((ia, b, kind), (ib, a, LINK_INVERSE[kind])):
        ensure_fields(src)
        if not any(link.get("type") == k and link.get("target") == dst for link in src["links"]):
            src["links"].append({"type": k, "target": dst, "at": now()})


async def update_case(hub, case_id: str, updates: Dict[str, Any], by: str = "manager") -> Dict[str, Any]:
    st = store(hub)
    case = st["cases"].get(str(case_id).upper())
    if case is None:
        raise KeyError(case_id)
    fields = normalize_case(hub, updates, base=case, partial=True)
    if "quarantined" in fields and not fields["quarantined"]:
        case["flaky_since"] = None                           # elle serbest bırakma: kararsızlık sayacı sıfırlanır
        case["history"] = case["history"][-1:]
    case.update(fields)
    case["updated_at"] = now()
    case["file"] = _write_case_file(hub, case) or case.get("file")
    if case.get("issue_id") and case["issue_id"] in hub.jira_issues:
        data = _issue_data(hub, case)
        data.pop("status", None)
        await hub.update_jira_issue(case["issue_id"], {**data, "audit_action": "TEST_CASE_UPDATED", "audit_notes": f"{by}: {', '.join(sorted(fields))}"})
    hub.mark_dirty()
    await _announce(hub)
    return case


async def _announce(hub) -> None:
    await hub.broadcast({"type": "TESTING_UPDATED", "summary": summary(hub)})


# ---------------------------------------------------------------------------
# QA tasarım görevi (TEST_DESIGN)
# ---------------------------------------------------------------------------
def stories_needing_cases(hub) -> List[Dict[str, Any]]:
    """Henüz hiç case'i olmayan hikâyeler (silinmiş/kullanımdan kalkmış case'ler sayılmaz)."""
    covered = {c.get("story_ref") for c in store(hub)["cases"].values() if c["status"] != "DEPRECATED"}
    return [s for s in SP.existing_stories(hub) if s["id"] not in covered]


def design_context(hub) -> str:
    """TEST_DESIGN görevinin bağlamı: case'siz hikâyeler (kabul kriteriyle) + mevcut case'ler + teslim biçimi."""
    todo = stories_needing_cases(hub)
    lines = [tx("\n## Test tasarımı (TEST_DESIGN) — QA"), tx("Kabul kriterlerinden TEST CASE'leri sen üret; sunucu doğrular, `TC-n` kimliği verir, `tests/TC-n.md` belgesini yazar ve Jira'da `TEST_CASE` açar.")]
    if todo:
        lines.append(tx("\n### Case'i olmayan hikâyeler (her kabul kriteri en az bir case ile kapsanmalı)"))
        acs = SP.ensure_state(hub)["acs"]
        for s in todo[:30]:
            lines.append(f"- {s['id']} · {s.get('title')}")
            for ac in s.get("ac_refs") or []:
                lines.append(f"  - {ac}: {(acs.get(ac) or {}).get('text', '')}")
    else:
        lines.append(tx("\nTüm hikâyelerin case'i var; yeni kriter/hikâye yoksa mevcut case'leri tamamla."))
    existing = [c for c in store(hub)["cases"].values() if c["status"] != "DEPRECATED"]
    if existing:
        lines.append(tx("\n### Mevcut case'ler (tekrarlama)"))
        lines += [f"- {c['id']} · {c['title']} · {','.join(c['ac_refs'])} · {c['automation']}" for c in sorted(existing, key=lambda c: _num(c["id"]))[:60]]
    lines.append(tx(
        "\n### Teslim biçimi (`payload.testcases[]`)\n"
        '`{"title": "...", "type": "unit|integration|e2e|security|performance|exploratory", "priority": "P0|P1|P2", "ac_refs": ["AC-3"], "story_ref": "JIRA-7", '
        '"precondition": "...", "steps": ["adım 1", "adım 2"], "expected": "...", "data": "...", "automation": "MANUAL | AUTOMATED:<test adı ya da E2E senaryo kimliği>", '
        '"labels": ["regression", "smoke"]}`\n'
        "- `steps` ve `expected` zorunlu; ölçülebilir olsun. Güvenlik (yetki/girdi doğrulama) ve performans (sağlık ucu gecikmesi) case'leri `security`/`performance` türünde yaz.\n"
        "- Otomatik testi olan case'te `automation` alanına test adını ver; QA adımında testin adına ya da yorumuna `TC-n` kimliğini yazman da yeterlidir."))
    return "\n".join(lines)


def validate_design(hub, payload: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Teslimdeki `testcases[]` → geçerli case girdileri + uyarılar. Hiç geçerli case yoksa hata (CaseError)."""
    raw = payload.get("testcases")
    if not isinstance(raw, list) or not raw:
        raise CaseError(tx("TEST_DESIGN teslimi `payload.testcases[]` (en az bir test case) içermeli."))
    valid: List[Dict[str, Any]] = []
    warnings: List[str] = []
    errors: List[str] = []
    for i, item in enumerate(raw, 1):
        try:
            norm = normalize_case(hub, item if isinstance(item, dict) else {"title": str(item)}, default_status="READY")
            if not norm["ac_refs"] and norm["type"] != "exploratory":
                warnings.append(tx("#{i} '{title}': kabul kriteri bağlı değil (izlenebilirlikte 'bağsız' görünür).", i=i, title=norm['title'][:50]))
            valid.append({**item, **norm} if isinstance(item, dict) else norm)
        except CaseError as e:
            errors.append(f"#{i}: {e}")
    if not valid:
        raise CaseError(tx("Geçerli test case yok: {errors}", errors="; ".join(errors[:5])))
    return valid, warnings + errors


async def ingest_design(hub, run, record, payload: Dict[str, Any]) -> Dict[str, Any]:
    remember_project_dir(hub, getattr(run, "project_dir", "") or "")
    cases, warnings = validate_design(hub, payload)
    existing = {(c["title"].strip().lower(), tuple(c["ac_refs"])) for c in store(hub)["cases"].values() if c["status"] != "DEPRECATED"}
    created: List[str] = []
    skipped = 0
    for c in cases:
        key = (c["title"].strip().lower(), tuple(c["ac_refs"]))
        if key in existing:
            skipped += 1
            continue
        existing.add(key)
        made = await create_case(hub, c, sprint=getattr(record, "sprint", None), by="QA", default_status="READY")
        created.append(made["id"])
    n = int(getattr(record, "sprint", None) or (SP.ensure_state(hub).get("current_sprint") or 0))
    write_plan(hub, n)
    await hub.record_event(trace_id=run.run_id, from_agent="QA", to_agent="SCRUM_MASTER", action="TEST_DESIGN_DONE", status="SUCCESS",
                           payload={"cases": created, "skipped": skipped, "warnings": warnings[:5]},
                           friendly_dialogue=tx("{n} test case tasarladım: {ids}{more}", n=len(created), ids=", ".join(created[:8]), more="…" if len(created) > 8 else ""))
    await _announce(hub)
    return {"created": created, "skipped": skipped, "warnings": warnings}


def with_design_task(hub, tasks: List[Dict[str, Any]], story_keys: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """Mimarın backlog'una (sprint kipi) bir QA `TEST_DESIGN` görevi ekler: backlog'da yoksa, QA etkinse ve case'siz hikâye varsa. Sunucu ekler: LLM unutursa tasarım atlanmaz."""
    if not design_enabled(hub) or not tasks:
        return tasks
    if any(t.get("work_type") == "TEST_DESIGN" for t in tasks):
        return tasks
    if any(str(i.get("kind", "")).lower() == "task" and i.get("work_type") == "TEST_DESIGN" and i.get("status") != "DONE" and not i.get("deleted")
           for i in hub.jira_issues.values()):
        return tasks                                          # bekleyen bir tasarım görevi zaten var (aynı hikâyeleri kapsar)
    qa = hub.agents.get("QA") or {}
    if qa.get("active") is False or not stories_needing_cases(hub):
        return tasks
    return tasks + [{"task_key": "TD-1", "title": tx("Test tasarımı: kabul kriterlerinden test case'leri üret"), "role": "QA", "work_type": "TEST_DESIGN", "priority": "P1",
                     "description": tx("Hikâyelerin kabul kriterlerini kapsayan test case'leri (TC-n) yaz; sunucu belgeleri ve Jira maddelerini üretir."),
                     "acceptance_criteria": [tx("Her kabul kriteri en az bir test case ile kapsanır"), tx("Case'lerin adımları ve beklenen sonucu ölçülebilir")],
                     "ac_refs": [], "story_ref": "", "depends_on": [], "files_hint": []}]


def template_design(hub) -> List[Dict[str, Any]]:
    """Şablon motoru: case'siz her hikâyenin her kabul kriteri için bir case; ilk case şablon QA testine (`test_token_creation`) bağlı (kuru koşuda gerçek PASS)."""
    out: List[Dict[str, Any]] = []
    acs = SP.ensure_state(hub)["acs"]
    for s in stories_needing_cases(hub):
        for ac in (s.get("ac_refs") or []):
            text = str((acs.get(ac) or {}).get("text") or s.get("title") or ac)
            first = not out
            out.append({"title": f"{str(s.get('title') or s['id'])[:70]} — {ac}", "type": "integration" if first else "e2e", "priority": "P0" if first else "P1",
                        "ac_refs": [ac], "story_ref": s["id"], "precondition": tx("Uygulama çalışıyor"),
                        "steps": [tx("Uygulamayı başlat"), tx("Kabul kriterini uygula: {text}", text=text[:160])], "expected": text[:300],
                        "automation": "AUTOMATED:test_token_creation" if first else "MANUAL", "labels": ["smoke", "regression"] if first else ["regression"]})
    return out


# ---------------------------------------------------------------------------
# Otomasyon eşlemesi
# ---------------------------------------------------------------------------
def tc_mentions(project_dir: str) -> Dict[str, List[str]]:
    """Test dosyalarında anılan `TC-n` kimlikleri → dosyalar."""
    out: Dict[str, List[str]] = {}
    if not project_dir or not os.path.isdir(project_dir):
        return out
    rx = re.compile(r"TC[-_ ]?0*(\d+)(?!\d)", re.I)
    for cur, dirs, files in os.walk(project_dir):
        dirs[:] = [d for d in dirs if d not in G._SCAN_SKIP_DIRS and not d.startswith(".")]
        for name in files:
            rel = os.path.relpath(os.path.join(cur, name), project_dir).replace("\\", "/")
            if not G.is_test_path(rel) or os.path.splitext(name)[1].lower() in G._SCAN_SKIP_EXT:
                continue
            try:
                if os.path.getsize(os.path.join(cur, name)) > 400_000:
                    continue
                with open(os.path.join(cur, name), "r", encoding="utf-8", errors="ignore") as fh:
                    text = fh.read()
            except OSError:
                continue
            for m in rx.finditer(text):
                files_for = out.setdefault(f"TC-{int(m.group(1))}", [])
                if rel not in files_for:
                    files_for.append(rel)
    return out


def _junit_matches(case: Dict[str, Any], junit: Optional[Dict[str, Any]], mentions: Dict[str, List[str]]) -> List[Dict[str, Any]]:
    if not junit:
        return []
    num = _num(case["id"])
    name_rx = re.compile(rf"tc[-_ ]?0*{num}(?!\d)", re.I)
    ref = case["automation"].split(":", 1)[1].strip().lower() if case["automation"].startswith("AUTOMATED:") else ""
    files = set(mentions.get(case["id"], []))
    out = []
    for t in junit.get("cases", []):
        name, tid, f = str(t.get("name") or ""), str(t.get("id") or ""), str(t.get("file") or "")
        if name_rx.search(name) or name_rx.search(tid) or (ref and (ref in tid.lower() or ref in name.lower())) or (f and f in files):
            out.append(t)
    return out


def _verdict(statuses: List[str]) -> Optional[str]:
    if any(s in ("failed", "error", "FAILED") for s in statuses):
        return "FAIL"
    if any(s in ("passed", "PASSED") for s in statuses):
        return "PASS"
    return "SKIP" if statuses else None


def _evaluate(case: Dict[str, Any], source: str, junit, scenarios, perf, mentions) -> Optional[Tuple[str, Dict[str, Any]]]:
    """(sonuç, kanıt) ya da None (bu koşunun kapsamında değil / bu koşuda yürütülmedi)."""
    if case["type"] not in SOURCE_TYPES.get(source, ()):
        return None
    auto = case["automation"].startswith("AUTOMATED:")
    if case["type"] == "performance":
        if perf is None:
            return ("BLOCKED", {"message": tx("ölçüm yok: doğrulama ayarlarında sağlık adresi (health_url) tanımlı değil")}) if auto else None
        ok = perf.get("samples", 0) > 0 and not perf.get("errors") and perf.get("p95_ms", 10 ** 9) <= perf.get("threshold_ms", 1000)
        return ("PASS" if ok else "FAIL", {"perf": perf, "message": tx("p95 {p95} ms (eşik {threshold} ms), hata {errors}", p95=perf.get('p95_ms'), threshold=perf.get('threshold_ms'), errors=perf.get('errors'))})
    if case["type"] == "e2e":
        ref = case["automation"].split(":", 1)[1].strip().lower() if auto else ""
        hit = [s for s in (scenarios or []) if (ref and (ref == str(s.get("id", "")).lower() or ref in str(s.get("file", "")).lower()))
               or (not ref and set(s.get("ac_refs") or []) & set(case["ac_refs"]))]
        verdict = _verdict([s.get("status", "") for s in hit])
        if verdict is None:
            return ("BLOCKED", {"message": tx("E2E senaryosu bulunamadı")}) if auto else None
        return (verdict, {"scenarios": [s.get("id") for s in hit], "message": "; ".join(f"{s.get('id')}: {s.get('status')}" for s in hit)[:300]})
    hit = _junit_matches(case, junit, mentions)
    verdict = _verdict([t.get("status", "") for t in hit])
    if verdict is None:
        return ("BLOCKED", {"message": tx("otomasyon testi koşuda bulunamadı")}) if auto else None
    failed = [t for t in hit if t.get("status") in ("failed", "error")]
    return (verdict, {"tests": [t.get("id") for t in hit][:8], "message": str(failed[0].get("message") or "")[:300] if failed else ""})


# ---------------------------------------------------------------------------
# Test run
# ---------------------------------------------------------------------------
def perf_smoke(url: str, samples: int = 10, threshold_ms: int = 1000, timeout_s: float = 5.0) -> Dict[str, Any]:
    """Sağlık adresinin gecikmesi (p50/p95/max) ve hata sayısı. Yerel adres varsayımıyla ardışık GET'ler; kaynak yükü bilerek hafif tutulur."""
    times: List[float] = []
    errors = 0
    for _ in range(max(1, min(int(samples), 50))):
        t0 = time.perf_counter()
        try:
            with urllib.request.urlopen(url, timeout=timeout_s) as r:
                r.read(256)
                if r.status >= 500:
                    errors += 1
        except Exception:
            errors += 1
        times.append((time.perf_counter() - t0) * 1000.0)
    times.sort()
    pick = lambda q: round(times[min(len(times) - 1, int(q * len(times)))], 1)           # noqa: E731
    return {"url": url, "samples": len(times), "errors": errors, "p50_ms": pick(0.5), "p95_ms": pick(0.95), "max_ms": round(times[-1], 1), "threshold_ms": int(threshold_ms)}


def _flaky_check(case: Dict[str, Any]) -> bool:
    seq = [h["result"] for h in case["history"] if h["result"] in ("PASS", "FAIL")][-FLAKY_WINDOW:]
    flips = sum(1 for a, b in zip(seq, seq[1:]) if a != b)
    return "PASS" in seq and "FAIL" in seq and flips >= FLAKY_FLIPS


async def _file_bug(hub, case: Dict[str, Any], run_id: str, evidence: Dict[str, Any]) -> Optional[str]:
    """Başarısız case için BUG: yeniden üretim adımları case'ten; case başına tek açık BUG."""
    cur = hub.jira_issues.get(case.get("open_bug") or "")
    if cur and cur.get("status") != "DONE" and not cur.get("deleted"):
        return cur["id"]
    order = _next_order(hub)
    iid = f"JIRA-{order}"
    steps = "\n".join(f"{i}. {s}" for i, s in enumerate(case["steps"], 1))
    desc = tx("[{priority}] {id} başarısız ({run_id}).\n\n**Yeniden üretim adımları**\n{steps}\n\n**Beklenen**\n{expected}\n\n"
              "**Gerçekleşen / kanıt**\n{evidence}", priority=case['priority'], id=case['id'], run_id=run_id, steps=steps, expected=case['expected'],
              evidence=evidence.get('message') or json.dumps({k: v for k, v in evidence.items() if k != 'message'}, ensure_ascii=False)[:600])
    role = "FRONTEND_DEV" if case["type"] == "e2e" and (hub.agents.get("FRONTEND_DEV") or {}).get("active", True) else "BACKEND_DEV"
    await hub.update_jira_issue(iid, {
        "order": order, "title": tx("[{id}] {title} başarısız", id=case['id'], title=case['title'])[:160], "description": desc, "issue_type": "BUG", "status": "BACKLOG",
        "priority": case["priority"], "assignee": role, "acceptance_criteria": [tx("{id} geçer", id=case['id']), tx("Regresyon testi eklenir")], "kind": "task",
        "task_key": SP.next_key(hub, "BUG"), "parent_id": case.get("story_ref") or case.get("issue_id"), "depends_on": [], "files_hint": [], "work_type": "BUG",
        "ac_refs": list(case["ac_refs"]), "origin": "TEST", "agent_id": "QA", "audit_action": "TASK_CREATED", "audit_notes": tx("{id} başarısız oldu ({run_id})", id=case['id'], run_id=run_id)})
    if case.get("issue_id"):
        _link(hub, iid, case["issue_id"], "relates")
    case["open_bug"] = iid
    return iid


async def record_run(hub, *, sprint: Optional[int], source: str, project_dir: str = "", junit: Any = "load", scenarios: Optional[List[Dict[str, Any]]] = None,
                     perf: Optional[Dict[str, Any]] = None, title: str = "") -> Optional[Dict[str, Any]]:
    """Bir test run kaydeder: bu kaynağın kapsamındaki HAZIR case'lerin sonuçları. Yürütülmeyen case sonucu değiştirmez. Kapsamda case yoksa None."""
    st = store(hub)
    remember_project_dir(hub, project_dir)
    pdir = project_dir or _project_dir(hub)
    if junit == "load":
        try:
            from .verify import junit_path, junit_results
            junit = junit_results(junit_path(pdir)) if pdir else None
        except Exception:
            junit = None
    cases = [c for c in st["cases"].values() if c["status"] == "READY" and c["type"] in SOURCE_TYPES.get(source, ())]
    if not cases:
        return None
    mentions = tc_mentions(pdir)
    st["seq"]["run"] = int(st["seq"].get("run", 0)) + 1
    rid = f"RUN-{st['seq']['run']}"
    n = int(sprint or SP.ensure_state(hub).get("current_sprint") or 0)
    results: List[Dict[str, Any]] = []
    bugs: List[str] = []
    flaky: List[str] = []
    for c in sorted(cases, key=lambda c: _num(c["id"])):
        ev = _evaluate(c, source, junit, scenarios, perf, mentions)
        if ev is None:
            continue
        result, evidence = ev
        results.append({"case": c["id"], "result": result, "evidence": evidence, "title": c["title"], "quarantined": c.get("quarantined", False)})
        if result == "SKIP":
            continue
        c["last_result"] = {"result": result, "run": rid, "at": now(), "message": str(evidence.get("message") or "")[:300], "source": source}
        c["history"] = (c["history"] + [{"result": result, "run": rid, "at": now()}])[-HISTORY_MAX:]
        if not c.get("quarantined") and _flaky_check(c):
            c["quarantined"], c["flaky_since"] = True, now()
            c["labels"] = sorted(set(c["labels"]) | {"flaky"})
            flaky.append(c["id"])
        if result == "FAIL" and not c.get("quarantined"):
            bug = await _file_bug(hub, c, rid, evidence)
            if bug:
                bugs.append(bug)
        if result == "PASS" and c.get("open_bug"):
            c["open_bug"] = c["open_bug"] if (hub.jira_issues.get(c["open_bug"]) or {}).get("status") != "DONE" else None
        if c.get("issue_id") in hub.jira_issues and result in CASE_ISSUE_STATUS:
            await hub.update_jira_issue(c["issue_id"], {"status": CASE_ISSUE_STATUS[result], "audit_action": "TEST_RESULT", "audit_notes": f"{rid}: {result}"})
        c["file"] = _write_case_file(hub, c) or c.get("file")
    for cid in flaky:                                           # kararsız test: tek bir iyileştirme maddesi
        c = st["cases"][cid]
        if not c.get("flaky_issue"):
            order = _next_order(hub)
            iid = f"JIRA-{order}"
            await hub.update_jira_issue(iid, {
                "order": order, "title": tx("[Kararsız test] {cid}: {title}", cid=cid, title=c['title'])[:160],
                "description": tx("{cid} art arda farklı sonuç verdi (son sonuçlar: {results}). Karantinaya alındı; nedeni (zamanlama, veri, sıra bağımlılığı) giderilip karantina kaldırılmalı.",
                                  cid=cid, results=", ".join(h["result"] for h in c["history"][-FLAKY_WINDOW:])),
                "issue_type": "IMPROVEMENT", "status": "BACKLOG", "priority": "P2", "assignee": "QA", "kind": "task", "task_key": SP.next_key(hub, "FL"), "parent_id": c.get("issue_id"),
                "depends_on": [], "files_hint": [], "work_type": "TEST", "ac_refs": list(c["ac_refs"]), "acceptance_criteria": [tx("{cid} kararlı geçer", cid=cid)], "origin": "TEST",
                "agent_id": "QA", "audit_action": "TASK_CREATED", "audit_notes": tx("Kararsız test izlemesi")})
            c["flaky_issue"] = iid
    counts = {r: sum(1 for x in results if x["result"] == r) for r in RESULTS}
    run = {"id": rid, "title": title or f"Sprint {n} — {source}", "sprint": n, "source": source, "executed_by": "server", "started_at": now(), "finished_at": now(),
           "results": results, "summary": {"total": len(results), **{k.lower(): v for k, v in counts.items()}}, "perf": perf, "bugs": bugs, "flaky": flaky, "issue_id": None}
    order = _next_order(hub)
    iid = f"JIRA-{order}"
    table = "\n".join(f"- {r['case']} · {r['result']} · {r['title'][:60]}" for r in results[:40])
    await hub.update_jira_issue(iid, {
        "order": order, "title": f"{rid}: {run['title']} — {counts['PASS']} PASS / {counts['FAIL']} FAIL / {counts['BLOCKED']} BLOCKED"[:160],
        "description": table or tx("Sonuç yok"), "issue_type": "TEST_RUN", "kind": "testrun", "status": "DONE", "priority": "P1", "assignee": "QA", "origin": "TEST",
        "agent_id": source, "audit_action": "TEST_RUN_RECORDED", "audit_notes": tx("{rid} kaydedildi ({source})", rid=rid, source=source)})
    run["issue_id"] = iid
    st["runs"][rid] = run
    write_plan(hub, n)
    hub.mark_dirty()
    await hub.record_event(trace_id=rid, from_agent="QA" if source == "QA" else source, to_agent="SCRUM_MASTER", action="TEST_RUN_RECORDED",
                           status="FAILED" if counts["FAIL"] else "SUCCESS", payload={"run": rid, "sprint": n, **run["summary"], "bugs": bugs, "flaky": flaky},
                           friendly_dialogue=tx("{rid}: {passed} geçti, {failed} kaldı, {blocked} engelli", rid=rid, passed=counts['PASS'], failed=counts['FAIL'], blocked=counts['BLOCKED'])
                           + (tx("; BUG: {bugs}", bugs=', '.join(bugs)) if bugs else ""))
    await _announce(hub)
    return run


async def set_manual_result(hub, case_id: str, result: str, note: str = "", by: str = "manager", sprint: Optional[int] = None) -> Dict[str, Any]:
    """Elle yürütülen case'in sonucunu girer (kendi MANUAL run'ı). FAIL → BUG; sonuç case'e ve matrise işlenir."""
    result = str(result or "").upper()
    if result not in ("PASS", "FAIL", "BLOCKED"):
        raise CaseError(tx("Sonuç PASS, FAIL ya da BLOCKED olmalı."))
    st = store(hub)
    case = st["cases"].get(str(case_id).upper())
    if case is None:
        raise KeyError(case_id)
    if case["status"] != "READY":
        raise CaseError(tx("Yalnızca HAZIR (READY) case'in sonucu girilebilir."))
    st["seq"]["run"] = int(st["seq"].get("run", 0)) + 1
    rid = f"RUN-{st['seq']['run']}"
    n = int(sprint or SP.ensure_state(hub).get("current_sprint") or 0)
    evidence = {"message": str(note or "")[:300], "manual": True}
    case["last_result"] = {"result": result, "run": rid, "at": now(), "message": evidence["message"], "source": "MANUAL"}
    case["history"] = (case["history"] + [{"result": result, "run": rid, "at": now()}])[-HISTORY_MAX:]
    bugs: List[str] = []
    if result == "FAIL":
        bug = await _file_bug(hub, case, rid, evidence)
        bugs = [bug] if bug else []
    if case.get("issue_id") in hub.jira_issues and result in CASE_ISSUE_STATUS:
        await hub.update_jira_issue(case["issue_id"], {"status": CASE_ISSUE_STATUS[result], "audit_action": "TEST_RESULT", "audit_notes": f"{rid}: {result} ({by})"})
    case["file"] = _write_case_file(hub, case) or case.get("file")
    run = {"id": rid, "title": tx("Elle: {id}", id=case['id']), "sprint": n, "source": "MANUAL", "executed_by": by, "started_at": now(), "finished_at": now(),
           "results": [{"case": case["id"], "result": result, "evidence": evidence, "title": case["title"], "quarantined": case.get("quarantined", False)}],
           "summary": {"total": 1, **{r.lower(): int(r == result) for r in RESULTS}}, "perf": None, "bugs": bugs, "flaky": [], "issue_id": None}
    st["runs"][rid] = run
    write_plan(hub, n)
    hub.mark_dirty()
    await _announce(hub)
    return run


# ---------------------------------------------------------------------------
# İzlenebilirlik matrisi, kapsama, regresyon kapısı
# ---------------------------------------------------------------------------
def _ac_num(ac: str) -> int:
    m = _AC_RX.match(str(ac))
    return int(m.group(1)) if m else 10 ** 9


def matrix(hub, project_dir: str = "") -> Dict[str, Any]:
    """Kabul kriteri ↔ case ↔ otomasyon ↔ sonuç. Durum: COVERED (geçen case var, başarısız yok) · FAILING · UNTESTED (case var, sonuç yok) · NO_CASE."""
    acs = SP.ensure_state(hub)["acs"]
    cases = [c for c in store(hub)["cases"].values() if c["status"] != "DEPRECATED"]
    mentions = {}
    try:
        mentions = G.ac_mentions(project_dir or _project_dir(hub)) if (project_dir or _project_dir(hub)) else {}
    except Exception:
        mentions = {}
    rows: List[Dict[str, Any]] = []
    for ac in sorted(acs, key=_ac_num):
        linked = [c for c in cases if ac in c["ac_refs"]]
        counted = [c for c in linked if not c.get("quarantined")]
        res = lambda c: (c.get("last_result") or {}).get("result")                        # noqa: E731
        passing = [c for c in counted if res(c) == "PASS"]
        failing = [c for c in counted if res(c) == "FAIL"]
        state = "FAILING" if failing else "COVERED" if passing else "UNTESTED" if linked else "NO_CASE"
        rows.append({"ac": ac, "text": (acs[ac] or {}).get("text", ""), "story": (acs[ac] or {}).get("story"), "po_status": (acs[ac] or {}).get("status"), "state": state,
                     "cases": [{"id": c["id"], "title": c["title"], "type": c["type"], "automation": c["automation"], "result": res(c), "quarantined": bool(c.get("quarantined")),
                                "issue_id": c.get("issue_id")} for c in linked],
                     "tests_mentioned": mentions.get(ac, [])})
    covered = sum(1 for r in rows if r["state"] == "COVERED")
    target = config(hub)["coverage_target"]
    return {"rows": rows, "total": len(rows), "covered": covered, "coverage_pct": round(100 * covered / len(rows)) if rows else None, "target_pct": target,
            "no_case": [r["ac"] for r in rows if r["state"] == "NO_CASE"], "failing": [r["ac"] for r in rows if r["state"] == "FAILING"],
            "untested": [r["ac"] for r in rows if r["state"] == "UNTESTED"], "unlinked_cases": [c["id"] for c in cases if not c["ac_refs"]]}


def passing_cases_for(hub, ac: str) -> List[str]:
    """Kriteri kanıtlayan (son sonucu PASS, karantinada olmayan) case'ler: PO kanıtı (quality.evidence_for) bunlara da bakar."""
    return [c["id"] for c in store(hub)["cases"].values()
            if ac in c["ac_refs"] and c["status"] == "READY" and not c.get("quarantined") and (c.get("last_result") or {}).get("result") == "PASS"]


def regression_set(hub) -> List[Dict[str, Any]]:
    return [c for c in store(hub)["cases"].values() if c["status"] == "READY" and "regression" in c["labels"] and not c.get("quarantined")]


def regression_gate(hub) -> Dict[str, Any]:
    """Regresyon kümesi (etiketli, hazır, karantinada olmayan case'ler) geçti mi? Hiç yürütülmemiş (sonucu olmayan) case kapıyı geçirmez; küme boşsa kapı açık."""
    reg = regression_set(hub)
    failing = [c["id"] for c in reg if (c.get("last_result") or {}).get("result") in ("FAIL", "BLOCKED")]
    unexecuted = [c["id"] for c in reg if not c.get("last_result") and c["automation"].startswith("AUTOMATED:")]
    manual_pending = [c["id"] for c in reg if not c.get("last_result") and c["automation"] == "MANUAL"]          # kapıyı tutmaz: elle sonuç girilmeli
    return {"ok": not failing and not unexecuted, "size": len(reg), "failing": failing, "unexecuted": unexecuted, "manual_pending": manual_pending}


def promote_regression(hub) -> List[str]:
    """Sprint kapanışında son sonucu PASS olan hazır case'ler regresyon kümesine girer (etiket `regression`)."""
    if not config(hub)["auto_regression"]:
        return []
    out = []
    for c in store(hub)["cases"].values():
        if c["status"] == "READY" and not c.get("quarantined") and (c.get("last_result") or {}).get("result") == "PASS" and "regression" not in c["labels"]:
            c["labels"] = sorted(set(c["labels"]) | {"regression"})
            out.append(c["id"])
    if out:
        hub.mark_dirty()
    return out


def summary(hub) -> Dict[str, Any]:
    st = store(hub)
    cases = list(st["cases"].values())
    live = [c for c in cases if c["status"] != "DEPRECATED"]
    mx = matrix(hub)
    runs = sorted(st["runs"].values(), key=lambda r: _num(r["id"]), reverse=True)
    by = lambda key: {k: sum(1 for c in live if c.get(key) == k) for k in sorted({c.get(key) for c in live if c.get(key)})}          # noqa: E731
    results = {r: sum(1 for c in live if (c.get("last_result") or {}).get("result") == r) for r in RESULTS}
    return {"cases": len(live), "by_status": {s: sum(1 for c in cases if c["status"] == s) for s in CASE_STATUSES}, "by_type": by("type"),
            "automated": sum(1 for c in live if c["automation"].startswith("AUTOMATED:")), "manual": sum(1 for c in live if c["automation"] == "MANUAL"),
            "results": results, "never_run": sum(1 for c in live if c["status"] == "READY" and not c.get("last_result")), "flaky": sum(1 for c in live if c.get("quarantined")),
            "coverage_pct": mx["coverage_pct"], "target_pct": mx["target_pct"], "uncovered": mx["no_case"], "failing_acs": mx["failing"],
            "regression": regression_gate(hub), "runs": len(runs), "last_run": ({k: runs[0][k] for k in ("id", "title", "source", "sprint", "summary", "finished_at")} if runs else None),
            "open_bugs": sum(1 for c in live if c.get("open_bug") and (hub.jira_issues.get(c["open_bug"]) or {}).get("status") != "DONE")}


# ---------------------------------------------------------------------------
# Test planı
# ---------------------------------------------------------------------------
def plan_markdown(hub, n: int) -> str:
    st = store(hub)
    sp = SP.get_sprint(hub, n) or {}
    stories = {(hub.jira_issues.get(i) or {}).get("parent_id") for i in sp.get("committed_issue_ids", [])} - {None, ""}
    live = [c for c in st["cases"].values() if c["status"] != "DEPRECATED"]
    scope = [c for c in live if not stories or c.get("story_ref") in stories or c.get("created_sprint") in (n, None)]
    mx = matrix(hub)
    gate = regression_gate(hub)
    lines = [tx("# Test planı — Sprint {n}", n=n), "", tx("- **Hedef:** {goal}", goal=sp.get('goal') or '-'), tx("- **Durum:** {status}", status=sp.get('status') or '-'),
             tx("- **Case sayısı:** {total} (otomatik {auto}, elle {manual})", total=len(scope), auto=sum(1 for c in scope if c['automation'] != 'MANUAL'),
                manual=sum(1 for c in scope if c['automation'] == 'MANUAL')),
             tx("- **Kapsama:** {pct}% (hedef {target}%)", pct=mx['coverage_pct'] if mx['coverage_pct'] is not None else '-', target=mx['target_pct']), "", tx("## Kapsam (hikâye → case)")]
    by_story: Dict[str, List[Dict[str, Any]]] = {}
    for c in scope:
        by_story.setdefault(c.get("story_ref") or "-", []).append(c)
    for sid, cs in sorted(by_story.items()):
        title = (hub.jira_issues.get(sid) or {}).get("title", tx("hikâyesiz"))
        lines.append(f"- **{sid}** · {title}: " + ", ".join(f"{c['id']}[{(c.get('last_result') or {}).get('result', '—')}]" for c in sorted(cs, key=lambda c: _num(c["id"]))))
    risks = [tx("Kabul kriteri case'siz: {acs}", acs=', '.join(mx['no_case'])) if mx["no_case"] else "",
             tx("Kabul kriteri başarısız: {acs}", acs=', '.join(mx['failing'])) if mx["failing"] else "",
             tx("Otomasyonsuz (elle) case: {ids}", ids=", ".join(c["id"] for c in scope if c["automation"] == "MANUAL")[:300]) if any(c["automation"] == "MANUAL" for c in scope) else "",
             tx("Kararsız (karantinada): {ids}", ids=", ".join(c["id"] for c in live if c.get("quarantined"))) if any(c.get("quarantined") for c in live) else ""]
    lines += ["", tx("## Riskler")] + [f"- {r}" for r in risks if r] + ([tx("- (belirgin risk yok)")] if not any(risks) else [])
    lines += ["", tx("## Çıkış kriteri"), tx("- Kapsama ≥ %{target}", target=mx['target_pct']),
              tx("- Regresyon kümesi geçti") + (tx(" ({size} case)", size=gate['size']) if gate["size"] else tx(" (küme henüz boş)")),
              tx("- P0 case'lerde başarısız sonuç yok"), "", tx("## Regresyon / smoke kümesi"),
              ", ".join(c["id"] for c in live if "regression" in c["labels"]) or tx("(boş)"), "", ", ".join(c["id"] for c in live if "smoke" in c["labels"]) or tx("(smoke boş)")]
    runs = sorted((r for r in st["runs"].values() if r["sprint"] == n), key=lambda r: _num(r["id"]), reverse=True)[:5]
    if runs:
        lines += ["", "## Son test run'lar"] + [f"- {r['id']} · {r['source']} · {r['summary']['pass']} PASS / {r['summary']['fail']} FAIL / {r['summary']['blocked']} BLOCKED" for r in runs]
    return "\n".join(lines) + "\n"


def write_plan(hub, n: int) -> Optional[str]:
    pdir = _project_dir(hub)
    if not pdir or not n:
        return None
    return SP._write(pdir, f"{_docs(hub)}/tests/plan-sprint-{n}.md", plan_markdown(hub, n), overwrite=True)


# ---------------------------------------------------------------------------
# E2E senaryo editörü (§4.3-5): `e2e/scenarios/*.json`
# ---------------------------------------------------------------------------
_SCENARIO_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")


def scenario_path(project_dir: str, sid: str) -> str:
    if not _SCENARIO_ID.match(str(sid or "")):
        raise CaseError(tx("Senaryo kimliği harf/rakam/_/- içermeli (en çok 64)."))
    return os.path.join(project_dir, "e2e", "scenarios", f"{sid}.json")


def validate_scenario(data: Dict[str, Any]) -> Dict[str, Any]:
    from .e2e_scenarios import STEP_KEYS
    if not isinstance(data, dict):
        raise CaseError(tx("Senaryo bir nesne olmalı."))
    sid = str(data.get("id") or "").strip()
    steps = data.get("steps")
    if not isinstance(steps, list) or not steps:
        raise CaseError(tx("steps boş olamaz."))
    clean: List[Dict[str, Any]] = []
    for i, s in enumerate(steps, 1):
        if not isinstance(s, dict) or sum(1 for k in STEP_KEYS if k in s) != 1:
            raise CaseError(tx("Adım {i}: tam olarak bir eylem olmalı ({keys}).", i=i, keys=', '.join(STEP_KEYS)))
        key = next(k for k in STEP_KEYS if k in s)
        if key == "fill" and not (isinstance(s["fill"], list) and len(s["fill"]) == 2):
            raise CaseError(tx("Adım {i}: fill [seçici, değer] olmalı.", i=i))
        clean.append({key: s[key]})
    return {"id": sid, "title": str(data.get("title") or "")[:160], "ac_refs": _ac_list(data.get("ac_refs")), "steps": clean}


def list_scenarios(project_dir: str) -> List[Dict[str, Any]]:
    from .e2e_scenarios import load_scenarios
    return load_scenarios(project_dir) if project_dir and os.path.isdir(project_dir) else []


def save_scenario(project_dir: str, data: Dict[str, Any]) -> Dict[str, Any]:
    if not project_dir or not os.path.isdir(project_dir):
        raise CaseError(tx("Proje klasörü bulunamadı."))
    sc = validate_scenario(data)
    path = scenario_path(project_dir, sc["id"])
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(sc, fh, ensure_ascii=False, indent=2)
    return sc


def delete_scenario(project_dir: str, sid: str) -> bool:
    path = scenario_path(project_dir, sid)
    if os.path.isfile(path):
        os.remove(path)
        return True
    return False
