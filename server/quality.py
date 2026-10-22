"""Kalite kapıları (F6, belge §6.3 PO/ARCHITECT, §7.3, §7.7): kriter bazında kabul ve kanıt, mimar gözden geçirme bulguları, sprint kapanış DoD raporu.

Hepsi `autonomy.strict_dod` açıkken çalışır (L2 ve L3 ön ayarları açar); kapalıyken mevcut davranış aynen kalır.
"""
from __future__ import annotations

import asyncio
import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from . import guard as G
from . import i18n as I18N
from . import meetings as M
from . import sprint as SP
from .i18n import translate as tx, N_

DOCKER_FILES = ("dockerfile", "docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml")
SEVERITY_PRIORITY = {"CRITICAL": "P0", "HIGH": "P0", "MEDIUM": "P1", "LOW": "P2"}


def _iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def strict(hub) -> bool:
    return bool(M.autonomy(hub)["strict_dod"])


# ---------------------------------------------------------------------------
# Kabul kriteri kapsamı ve kanıtı
# ---------------------------------------------------------------------------
def sprint_acs(hub, n: int) -> List[str]:
    """Sprintin tamamlanan işlerinin kapsadığı kabul kriterleri (PO bunların her biri için karar verir)."""
    sp = SP.get_sprint(hub, n) or {}
    out: List[str] = []
    for iid in sp.get("committed_issue_ids", []):
        issue = hub.jira_issues.get(iid) or {}
        if issue.get("status") != "DONE" and not (issue.get("closed_in_sprint") == n):
            continue
        for ac in issue.get("ac_refs") or []:
            if ac not in out:
                out.append(ac)
    return out


def evidence_for(hub, n: int, project_dir: str, last_verification_ok: bool = True) -> Dict[str, Dict[str, Any]]:
    """AC → kanıt: test dosyalarında anılan kimlikler (proje testleri geçtiyse) ve geçen E2E senaryoları. Kanıtsız kriter kabul edilemez (§6.3 PO)."""
    from . import testing as TST
    files = G.ac_evidence(project_dir)
    e2e = (SP.ensure_state(hub).get("e2e_evidence") or {}).get(str(n), {})
    ev: Dict[str, Dict[str, Any]] = {}
    case_acs = {ac for c in TST.store(hub)["cases"].values() for ac in c.get("ac_refs", [])}
    for ac in set(files) | set(e2e) | case_acs:
        tests = files.get(ac, []) if last_verification_ok else []
        passed = (e2e.get(ac) or {}).get("passed", [])
        cases = TST.passing_cases_for(hub, ac)                       # G7: son sonucu PASS olan test case'ler de kanıttır
        ev[ac] = {"tests": tests, "e2e": passed, "cases": cases, "ok": bool(tests or passed or cases)}
    return ev


# ---------------------------------------------------------------------------
# UAT belgesi: sunucu kararı geçerlidir (saha: PO belgesi "APPROVED, tüm kriterler Kabul" yazarken sunucu 24/24 kriteri kanıtsız reddetmişti)
# ---------------------------------------------------------------------------
UAT_BEGIN, UAT_END = "<!-- fssc:uat-verdict:begin -->", "<!-- fssc:uat-verdict:end -->"
_UAT_BLOCK_RX = re.compile(re.escape(UAT_BEGIN) + r".*?" + re.escape(UAT_END) + r"\n*", re.DOTALL)
_UAT_DECISION_RX = re.compile(r"(?im)^(\s*(?:[-*]\s*)?(?:\*\*)?\s*(?:Karar|Decision)\s*:?\s*(?:\*\*)?\s*:?\s*)APPROVED\b[^\n]*$")


def render_uat_verdict(n: int, required: List[str], acs: Dict[str, Any], ev: Dict[str, Dict[str, Any]]) -> str:
    """Sunucunun kriter denetimi: kriter, karar, kanıt (test dosyası / E2E / case) ya da ret gerekçesi."""
    rows = []
    accepted = 0
    for ac in required:
        entry = acs.get(ac) or {}
        ok = entry.get("status") == "ACCEPTED"
        accepted += 1 if ok else 0
        e = ev.get(ac) or {}
        proof = ", ".join([*(e.get("tests") or []), *(e.get("e2e") or []), *(e.get("cases") or [])])[:140]
        rows.append(f"| {ac} | {tx('Kabul') if ok else tx('RET')} | {proof or '-'}{'' if ok else ' · ' + str(entry.get('reason') or '')[:120]} |")
    verdict = tx("KABUL") if required and accepted == len(required) else (tx("RET") if required else tx("KAPSAM YOK"))
    return "\n".join([
        UAT_BEGIN,
        tx("## Sunucu kanıt denetimi — Sprint {n} (otomatik, geçerli karar)", n=n),
        tx("**Sonuç: {verdict}** — {accepted}/{total} kriter kanıtla kabul edildi. Bir kriter ancak geçen test, E2E senaryosu ya da test case ile kabul edilir; "
           "aşağıdaki PO anlatımı bu bölümle çelişirse **bu bölüm geçerlidir**.", verdict=verdict, accepted=accepted, total=len(required)),
        "",
        tx("| Kriter | Karar | Kanıt / gerekçe |"),
        "|---|---|---|",
        *rows,
        UAT_END, "",
    ])


def sync_uat_document(hub, project_dir: str, n: int, required: List[str], acs: Dict[str, Any], ev: Dict[str, Dict[str, Any]], rejected: int) -> Optional[str]:
    """PO'nun UAT belgesine sunucu denetimi bölümünü yazar/günceller (belge yoksa dokunmaz); ret varsa belgedeki "Karar: APPROVED" satırını düzeltir."""
    try:
        from .paths import hub_docs_path
        rel = hub_docs_path(hub, "uat/acceptance_criteria.md", project_dir)
        path = os.path.join(project_dir, *rel.split("/"))
        if not os.path.isfile(path):
            return None
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
        text = _UAT_BLOCK_RX.sub("", text)
        if rejected:
            text = _UAT_DECISION_RX.sub(lambda m: m.group(1) + tx("REJECTED (sunucu kanıt denetimi: {rejected} kriter kanıtsız/reddedildi; PO'nun ilk kararı geçersiz)", rejected=rejected), text)
        block = render_uat_verdict(n, required, acs, ev)
        lines = text.splitlines(keepends=True)
        at = next((i + 1 for i, ln in enumerate(lines) if ln.startswith("# ")), 0)          # ilk başlıktan hemen sonra
        text = "".join(lines[:at]) + ("\n" if at else "") + block + "".join(lines[at:])
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        return rel
    except OSError:
        return None


# ---------------------------------------------------------------------------
# PO: kriter bazında karar (§6.3)
# ---------------------------------------------------------------------------
async def apply_po_criteria(hub, run, record, payload: Dict[str, Any], result, project_dir: str, create_tasks) -> Dict[str, Any]:
    """PO'nun `criteria[]` kararlarını sunucu kanıtıyla denetler. Kanıtsız ya da kararsız kriter REDDEDİLİR; reddedilenler iyileştirme maddesi olur.
    `create_tasks(tasks)`: pipeline'ın görev oluşturucusu. Sonuç `result` üzerinde UAT_REJECTED'a çevrilir."""
    n = int(record.sprint or 0)
    required = sprint_acs(hub, n)
    last = next((s for s in reversed(run.steps) if s.sprint == n and s.verification), None)
    ok_verif = not last or (last.verification or {}).get("status") != "FAILED"
    ev = evidence_for(hub, n, project_dir, ok_verif)
    decisions = {str(c.get("id")).upper().replace("_", "-"): c for c in (payload.get("criteria") or []) if isinstance(c, dict) and c.get("id")}
    acs = SP.ensure_state(hub)["acs"]
    accepted: List[str] = []
    rejected: List[Dict[str, str]] = []
    for ac in required:
        d = decisions.get(ac)
        verdict = str((d or {}).get("decision") or "").upper()
        reason = str((d or {}).get("reason") or "")
        if d is None:
            verdict, reason = "REJECTED", tx("PO bu kriter için karar vermedi")
        elif verdict == "ACCEPTED" and not ev.get(ac, {}).get("ok"):
            verdict, reason = "REJECTED", tx("kanıtsız: bu kritere bağlı geçen test ya da E2E senaryosu yok")
        elif verdict != "ACCEPTED":
            verdict = "REJECTED"
        entry = acs.setdefault(ac, {"text": "", "story": None})
        entry.update({"status": verdict, "decided_by": "PO", "decided_at": _iso(), "sprint": n, "reason": reason, "evidence": ev.get(ac, {"tests": [], "e2e": [], "ok": False})})
        (accepted if verdict == "ACCEPTED" else rejected).append(ac if verdict == "ACCEPTED" else {"ac": ac, "reason": reason})
    po_summary = {"required": required, "accepted": accepted, "rejected": rejected}
    SP.ensure_state(hub).setdefault("po_decisions", {})[str(n)] = po_summary
    sync_uat_document(hub, project_dir, n, required, acs, ev, len(rejected))
    if rejected:
        tasks = []
        batch = SP.cfg(hub)["ac_test_batch"]
        no_ev = [r for r in rejected if any(v in r["reason"] for v in I18N.variants("kanıtsız"))]
        for r in rejected:
            if r in no_ev:
                continue
            story = next((i for i in hub.jira_issues.values() if r["ac"] in (i.get("ac_refs") or []) and str(i.get("kind", "")).lower() == "story"), None)
            text = SP.ac_text(hub, r["ac"])
            tasks.append({"task_key": r["ac"], "title": tx("{ac} sağlanmadı: {reason}", ac=r["ac"], reason=r["reason"])[:160],
                          "role": "BACKEND_DEV", "work_type": "IMPROVEMENT", "priority": "P0",
                          "description": (f"{r['ac']} — {text}\n" if text else "") + r["reason"],
                          "acceptance_criteria": [(f"{r['ac']}: {text} — " if text else f"{r['ac']} ") + tx("PO tarafından kanıtla kabul edilir")], "ac_refs": [r["ac"]],
                          "story_ref": story["id"] if story else "", "depends_on": [], "files_hint": []})
        # Kanıtsız kriterler (yalnızca test eksik) ekip gibi gruplanır: kriter başına değil, `ac_test_batch` kriter başına tek QA görevi
        for k in range(0, len(no_ev), batch):
            grp = no_ev[k:k + batch]
            acs_ = [g["ac"] for g in grp]
            story = next((i for i in hub.jira_issues.values() if acs_[0] in (i.get("ac_refs") or []) and str(i.get("kind", "")).lower() == "story"), None)
            tasks.append({"task_key": acs_[0], "title": (tx("{acs} için test/E2E senaryolarını yaz", acs=', '.join(acs_)) if len(acs_) > 1 else tx("{ac} için test/E2E senaryosu yaz", ac=acs_[0]))[:160],
                          "role": "QA", "work_type": "TEST", "priority": "P0",
                          "description": tx("Kanıtsız kriterler: bu kriterlere bağlı geçen test ya da E2E senaryosu yok. Her kriter için kriter kimliğini anan en az bir test yaz."),
                          "acceptance_criteria": [(f"{a}: {SP.ac_text(hub, a)} — " if SP.ac_text(hub, a) else f"{a} ") + tx("PO tarafından kanıtla kabul edilir") for a in acs_], "ac_refs": acs_,
                          "story_ref": story["id"] if story else "", "depends_on": [], "files_hint": []})
        await create_tasks(tasks)
        sp = SP.get_sprint(hub, n)
        if sp is not None:
            sp["uat_rejections"] = int(sp.get("uat_rejections", 0)) + 1
        result.status = "FAILED"
        result.action = "UAT_REJECTED"
        if result.events:
            result.events[-1].action, result.events[-1].status, result.events[-1].to_agent = "UAT_REJECTED", "FAILED", "PM"
        result.summary = tx("{summary} ✗ PO {count} kriteri reddetti: {acs}", summary=result.summary, count=len(rejected), acs=", ".join(r["ac"] for r in rejected))
    elif required:
        result.summary = tx("{summary} ✓ PO {count} kriteri kanıtla kabul etti.", summary=result.summary, count=len(accepted))
    await hub.record_event(trace_id=run.run_id, from_agent="PO", to_agent="SCRUM_MASTER", action="PO_CRITERIA_DECIDED", status="SUCCESS" if not rejected else "FAILED",
                           payload={"sprint": n, **po_summary}, friendly_dialogue=tx("PO kriter kararları: {accepted} kabul, {rejected} ret.", accepted=len(accepted), rejected=len(rejected)))
    return po_summary


# ---------------------------------------------------------------------------
# ARCHITECT gözden geçirmesi: bulgular iş maddesi olur (§7.3)
# ---------------------------------------------------------------------------
def normalize_findings(raw: Any, roles: Optional[set] = None) -> List[Dict[str, Any]]:
    out = []
    for f in raw if isinstance(raw, list) else []:
        if not isinstance(f, dict) or not str(f.get("title") or "").strip():
            continue
        sev = str(f.get("severity") or "MEDIUM").upper()
        if sev not in SEVERITY_PRIORITY:
            sev = "MEDIUM"
        role = str(f.get("role") or "BACKEND_DEV").upper()
        out.append({"title": str(f["title"]).strip()[:160], "severity": sev, "description": str(f.get("description") or "")[:1500],
                    "files": [str(x) for x in (f.get("files") or [])][:10], "role": role if role in SP.TASK_ROLES or role in (roles or ()) else "BACKEND_DEV"})
    return out[:20]


async def expand_review_findings(hub, run, record, payload: Dict[str, Any], create_tasks) -> int:
    from . import agent_registry as AR
    findings = normalize_findings(payload.get("findings"), roles=set(AR.routing_roles(hub)))
    tasks = [{"task_key": f"RV-{i + 1}", "title": f["title"], "role": f["role"], "work_type": "BUG" if f["severity"] in ("CRITICAL", "HIGH") else "REFACTOR",
              "priority": SEVERITY_PRIORITY[f["severity"]], "description": f"[{f['severity']}] {f['description']}", "acceptance_criteria": [tx("Bulgu giderilir ve testle doğrulanır")],
              "files_hint": f["files"], "depends_on": [], "ac_refs": [], "story_ref": ""} for i, f in enumerate(findings)]
    if tasks:
        await create_tasks(tasks)
    sp = SP.get_sprint(hub, int(record.sprint or 0))
    if sp is not None:
        sp["arch_review"] = {"done": True, "findings": len(findings), "at": _iso()}
        await settle_blocked_sprint(hub, sp)
    return len(findings)


ARCH_MISSING = N_("ARCHITECT kod ve mimari gözden geçirmesi yapılmadı")


async def settle_blocked_sprint(hub, sp: Dict[str, Any]) -> bool:
    """Sıkı DoD kapanışında yalnızca mimar gözden geçirmesi eksik olduğu için BLOCKED (PRECONDITION_LOST) kalan sprint, gözden geçirme bitince kapanır.
    Başka eksik kalıyorsa engel nedeni güncellenir. `current_sprint` değişmez (eski sprint kapanırken güncel sprint geriye dönmesin)."""
    blocked = sp.get("blocked") or {}
    if sp.get("status") != "BLOCKED" or blocked.get("reason") != "PRECONDITION_LOST":
        return False
    dod = sp.setdefault("dod", {})
    left = [m for m in (dod.get("missing") or []) if not any(v in m for v in I18N.variants(ARCH_MISSING))]
    dod["arch_review"] = {"done": True}
    dod["missing"] = left
    if left:
        blocked["detail"] = tx("Sıkı DoD kapanış koşulu eksik: ") + "; ".join(left)
        blocked.pop("review_planned", None)
        hub.mark_dirty()
        return False
    dod["ok"] = True
    sp["status"], sp["blocked"] = "CLOSED", None
    hub.mark_dirty()
    n = sp["sprint_number"]
    await hub.record_event(trace_id=f"sprint-{n}", from_agent="ARCHITECT", to_agent="SCRUM_MASTER", action="SPRINT_CLOSED_AFTER_REVIEW", status="SUCCESS",
                           payload={"sprint": n}, friendly_dialogue=tx("Sprint {n}: eksik mimar gözden geçirmesi tamamlandı, kapanış koşulları sağlandı; sprint kapandı.", n=n))
    await hub.broadcast({"type": "SPRINT_UNBLOCKED", "sprint": n})
    return True


# ---------------------------------------------------------------------------
# Sprint kapanışı: DoD raporu (§7.7)
# ---------------------------------------------------------------------------
def _sprint_artifacts(run, n: int) -> List[str]:
    return [a for s in run.steps if s.sprint == n for a in (s.artifacts or [])]


async def close_report(hub, run, sp: Dict[str, Any], project_dir: str, create_tasks) -> Dict[str, Any]:
    """Kapanış koşulları: E2E geçti ya da hata maddesi açıldı; DevOps değiştiyse konteyner build; PO her kriter için karar verdi; mimar gözden geçirmesi; retro."""
    n = sp["sprint_number"]
    rep: Dict[str, Any] = {"strict": True, "checked_at": _iso()}
    bugs: List[Dict[str, Any]] = []

    last_e2e = hub.playwright_reports[0] if hub.playwright_reports else None
    scen_fail = [ac for ac, v in ((SP.ensure_state(hub).get("e2e_evidence") or {}).get(str(n), {})).items() if v.get("failed")]
    if last_e2e and (last_e2e.get("status") == "FAILED" or scen_fail):
        config_issue = last_e2e.get("verdict") in ("APP_NOT_CONFIGURED", "APP_START_FAILED")     # kod hatası değil: çalıştırma komutu/sağlık adresi eksik ya da uygulama kalkmadı
        bugs.append({"task_key": "E2E",
                     "title": (tx("E2E için uygulama çalıştırma ayarı eksik/hatalı (sprint {n}): {verdict}", n=n, verdict=last_e2e.get('verdict')) if config_issue
                               else tx("E2E kaldı (sprint {n}): {verdict}", n=n, verdict=last_e2e.get('verdict') or tx('senaryo hatası')))[:160],
                     "role": "DEVOPS" if config_issue else "BACKEND_DEV", "work_type": "BUG", "priority": "P0",
                     "description": (str(last_e2e.get("engine_error") or tx("E2E uygulaması başlatılamadı; verification.run ve health_url tanımlanmalı.")) if config_issue else tx("E2E sonucu başarısız; ayrıntı raporda.")),
                     "acceptance_criteria": ([tx("verification.run ve health_url tanımlı; uygulama başlar ve sağlık adresi 200 döner")] if config_issue else [tx("E2E yeşile döner")]),
                     "ac_refs": scen_fail, "depends_on": [], "story_ref": "", "files_hint": []})
        rep["e2e"] = {"status": "FAILED", "bug_opened": True}
    else:
        rep["e2e"] = {"status": (last_e2e or {}).get("status", "YOK"), "bug_opened": False}

    changed = [a for a in _sprint_artifacts(run, n) if os.path.basename(a).lower() in DOCKER_FILES]
    if changed:
        res = await asyncio.to_thread(G.container_verify, project_dir, "")
        rep["container"] = {**res, "files": sorted(set(changed))}
        if res["status"] == "FAILED":
            bugs.append({"task_key": "CNT", "title": tx("Konteyner build/sağlık kaldı (sprint {n})", n=n), "role": "DEVOPS", "work_type": "BUG", "priority": "P0",
                         "description": f"{res.get('reason')}: {str(res.get('output') or '')[:600]}", "acceptance_criteria": [tx("Konteyner build edilir ve sağlık adresi yanıt verir")],
                         "ac_refs": [], "depends_on": [], "story_ref": "", "files_hint": sorted(set(changed))})
            rep["container"]["bug_opened"] = True
    else:
        rep["container"] = {"status": "NOT_APPLICABLE", "reason": tx("DevOps dosyaları değişmedi")}

    required = sprint_acs(hub, n)
    po = (SP.ensure_state(hub).get("po_decisions") or {}).get(str(n))
    rep["po"] = {"required": required, "decided": bool(po) or not required}
    from . import testing as TST                      # G7: regresyon kümesi geçti; geçen case'ler bir sonraki sprint için kümeye girer
    gate = TST.regression_gate(hub)
    rep["tests"] = {"coverage_pct": TST.matrix(hub, project_dir)["coverage_pct"], "regression": gate, "promoted": TST.promote_regression(hub)}
    TST.write_plan(hub, n)
    rep["arch_review"] = {"done": bool((sp.get("arch_review") or {}).get("done"))}
    rep["retro"] = {"file": bool(sp["meetings"].get("review_retro"))}
    if bugs:
        await create_tasks(bugs)
    missing = []
    if required and not po:
        missing.append(tx("PO kriter kararları verilmedi"))
    if not rep["arch_review"]["done"]:
        missing.append(tx(ARCH_MISSING))
    if not gate["ok"]:
        missing.append(tx("Regresyon kümesi geçmedi: ") + ", ".join(gate["failing"] + gate["unexecuted"]))
    rep["ok"] = not missing
    rep["missing"] = missing
    return rep
