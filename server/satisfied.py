"""“Zaten karşılanıyor” kontrolü: görevin istediği dosyalar projede hazırsa ve doğrulama geçiyorsa ajana boşuna iş verilmez.

Sorun (saha): kararlardan açılan iskelet/test/dağıtım görevleri, çoğu şey zaten yapılmış bir projeye de açılıyordu; ajan 50 KB bağlam okuyup var olan dosyaları yeniden teslim ediyordu.
İki katman vardır (ikisi de LLM kullanmaz, sunucu kanıtına dayanır):
1. **Kapatma** (`try_close`): yalnızca varlığı yeterli kanıt sayılan iş türlerinde (TEST, DEVOPS, DOCS) ve aşağıdakilerin HEPSİ doğruysa görev sunucuca bitirilir:
   görevin `files_hint` listesi dolu · listedeki her dosya var, boş değil, git'te izli ve değişmemiş (commit'li) · onay modu durmayı gerektirmiyor ·
   sunucu doğrulaması (artımlı) PASSED ve en az bir test gerçekten koştu. Özellik/hata/iyileştirme/iskelet işleri ASLA kapatılmaz: dosyanın var olması davranışın doğru olduğunu göstermez.
2. **Bağlam kanıtı** (`context_section`): kapatılamayan görevde ajana hangi dosyaların zaten var olduğu ve hangilerinin eksik olduğu söylenir; var olanı yeniden yazmaz, eksiği tamamlar.
Ayar: `skip_satisfied_tasks` (varsayılan açık). Kapatma denetim kaydına (`ALREADY_SATISFIED`) ve olay akışına yazılır, Jira'da DONE olur.
"""
from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .i18n import translate as tx

SATISFIABLE_TYPES = {"TEST", "DEVOPS", "DOCS"}


def _hints(issue: Dict[str, Any]) -> List[str]:
    out: List[str] = []
    for p in issue.get("files_hint") or []:
        p = str(p or "").strip().replace("\\", "/").lstrip("/")
        if p and ".." not in p.split("/") and p not in out:
            out.append(p)
    return out


def existence(project_dir: str, hints: List[str]) -> List[Dict[str, Any]]:
    """Her ipucu dosyası için {path, exists, size}."""
    rows = []
    for rel in hints:
        full = os.path.join(project_dir, *rel.split("/"))
        ok = os.path.isfile(full)
        rows.append({"path": rel, "exists": ok, "size": os.path.getsize(full) if ok else 0})
    return rows


_IDENT = re.compile(r"\b[A-Z][a-z0-9]+(?:[A-Z][a-z0-9]+)+\b")
_SRC_EXT = (".ts", ".tsx", ".js", ".jsx", ".py")
_SKIP = {"node_modules", ".git", "dist", "build", ".venv", "venv", "__pycache__", ".fs-workspace", "coverage"}


def identifier_hits(project_dir: str, issue: Dict[str, Any], limit: int = 8) -> Dict[str, List[str]]:
    """Görev metnindeki CamelCase tanımlayıcılarından (sınıf/servis adı) kodda geçenler: {ad: [dosya...]}. LLM'siz, yalnızca bilgi (kapatma kararı vermez)."""
    text = " ".join([str(issue.get("title") or ""), str(issue.get("description") or "")] + [str(c) for c in issue.get("acceptance_criteria") or []])
    names = list(dict.fromkeys(_IDENT.findall(text)))[:limit]
    hits: Dict[str, List[str]] = {}
    if not names:
        return hits
    seen = 0
    for dp, dns, fns in os.walk(project_dir):
        dns[:] = [d for d in dns if d not in _SKIP]
        for fn in fns:
            if not fn.endswith(_SRC_EXT) or dp == project_dir:       # kök dosyaları (ajanın geçici betikleri) kaynak sayılmaz
                continue
            seen += 1
            if seen > 3000:
                return hits
            fp = os.path.join(dp, fn)
            try:
                if os.path.getsize(fp) > 400_000:
                    continue
                body = open(fp, "r", encoding="utf-8", errors="ignore").read()
            except OSError:
                continue
            rel = os.path.relpath(fp, project_dir).replace("\\", "/")
            for n in names:
                if n in body and len(hits.setdefault(n, [])) < 3 and rel not in hits[n]:
                    hits[n].append(rel)
    return {k: v for k, v in hits.items() if v}


def context_section(project_dir: str, issue: Dict[str, Any]) -> str:
    """Ajan bağlamına girecek kısa kanıt bölümü (ipucu dosyası yoksa ya da hiçbiri yoksa boş)."""
    rows = existence(project_dir, _hints(issue))
    if not rows or not any(r["exists"] for r in rows):
        hits = identifier_hits(project_dir, issue)
        if not hits:
            return ""
        lines = [f"- `{n}` → " + ", ".join(fs) for n, fs in hits.items()]
        return (tx("\n\n## Kodda zaten bulunanlar (sunucu taraması)\n") + "\n".join(lines) + "\n"
                + tx("Bu öğeler projede VAR: önce bunları oku ve kabul kriterlerini mevcut koda karşı doğrula. Hepsi karşılanıyorsa dosya yeniden yazma; "
                     "`payload.already_satisfied` ile her kriter için commit'li bir test kanıtı göster. Yalnızca gerçek bir eksik varsa o dosyaları değiştir."))
    lines = [f"- {tx('VAR ') if r['exists'] and r['size'] else (tx('BOŞ ') if r['exists'] else tx('YOK '))} {r['path']}" + (tx(" ({size} bayt)", size=r["size"]) if r["exists"] else "") for r in rows]
    missing = [r["path"] for r in rows if not (r["exists"] and r["size"])]
    return (tx("\n\n## Mevcut durum kanıtı (sunucu denetimi)\n") + "\n".join(lines) + "\n"
            + (tx("Var olan dosyaları YENİDEN YAZMA (gerekmedikçe dokunma); görevin kabul kriterlerine göre yalnızca eksiği ve eksik testi teslim et: ") + ", ".join(missing) + "."
               if missing else
               tx("Görevin tüm dosyaları zaten var: kabul kriterlerini mevcut koda karşı doğrula; yalnızca gerçek bir eksik varsa değiştir, değiştirdiğin dosyanın tamamını ver.")))


def _gate_free(hub, run) -> bool:
    """Onay kapısı olmayan koşu: sunucunun kendi başına kapattığı görev yöneticinin onay modunu atlamış olmaz."""
    auto_run = getattr(hub, "auto_proceed_run_id", None)
    if hub.auto_proceed_all and (auto_run is None or auto_run == run.run_id):
        return True
    if not run.step_by_step:
        return True
    return hub.get_settings().get("approval_mode", "every_step") == "auto"


async def _tracked_and_clean(project_dir: str, hints: List[str]) -> bool:
    from . import scm
    ls = await scm._git(["ls-files", "--", *hints], project_dir)
    if ls["code"] != 0 or {x.strip() for x in ls["out"].splitlines() if x.strip()} != set(hints):
        return False
    st = await scm._git(["status", "--porcelain", "--", *hints], project_dir)
    return st["code"] == 0 and not st["out"].strip()


def validate_claim(ctx, claim: Dict[str, Any]) -> List[str]:
    """Ajanın "bu görev mevcut kodla karşılanıyor" iddiasının kanıtını denetler; test dosyası yollarını döner (sunucu bunları koşar).
    Her kabul kriteri için en az bir kanıt, her kanıt var olan bir test dosyası olmalı; aksi halde StepOutputError (ajan düzeltip yeniden gönderir)."""
    import re
    import subprocess
    from .proc import hidden
    from .guard import _TEST_FILE_RX
    from .llm.parsing import StepOutputError
    ev = [e for e in (claim.get("evidence") or []) if isinstance(e, dict)]
    criteria = [str(c) for c in (ctx.issue.get("acceptance_criteria") or [])]
    errors: List[str] = []
    if not ev:
        errors.append(tx("already_satisfied.evidence boş: her kabul kriteri için {criterion, test} ver."))
    if criteria and len(ev) < len(criteria):
        errors.append(tx("{n_criteria} kabul kriteri var ama yalnızca {n_evidence} kanıt verildi; her kriter için bir kanıt testi gerekir.", n_criteria=len(criteria), n_evidence=len(ev)))
    tests: List[str] = []
    for e in ev:
        rel = str(e.get("test") or "").strip().replace("\\", "/").lstrip("/")
        full = os.path.join(ctx.project_dir, *rel.split("/")) if rel else ""
        if not rel or ".." in rel.split("/") or not os.path.isfile(full):
            errors.append(tx("Kanıt test dosyası yok: '{path}'.", path=rel or '?'))
        elif not _TEST_FILE_RX.search(rel):
            errors.append(tx("'{path}' bir test dosyası değil (spec/test).", path=rel))
        elif rel not in tests:
            tests.append(rel)
    if tests and not errors:
        try:
            ls = subprocess.run(["git", "ls-files", "--", *tests], cwd=ctx.project_dir, capture_output=True, text=True, timeout=20, **hidden())
            tracked = {x.strip() for x in ls.stdout.splitlines() if x.strip()}
            dirty = subprocess.run(["git", "status", "--porcelain", "--", *tests], cwd=ctx.project_dir, capture_output=True, text=True, timeout=20, **hidden()).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            tracked, dirty = set(tests), ""
        for t in tests:
            if t not in tracked:
                errors.append(tx("Kanıt testi '{path}' git'te izli değil (commit'li bir test olmalı).", path=t))
        if dirty:
            errors.append(tx("Kanıt test dosyaları commit'lenmemiş değişiklik içeriyor."))
    if errors:
        raise StepOutputError(errors[0], errors[:6])
    return tests


async def try_close(hub, run, record) -> bool:
    """Görev zaten karşılanıyorsa sunucuca bitirir (True). Kanıt yetersizse hiçbir iz bırakmadan False (ajan normal yoldan çalışır)."""
    from . import guard as G
    from . import pipeline as P
    try:
        if not hub.get_settings().get("skip_satisfied_tasks", True):
            return False
        if run.engine != "mcp_client" or record.kind != "task" or record.fix_round or record.status != "PENDING" or not _gate_free(hub, run):
            return False
        issue = hub.jira_issues.get(record.issue_id) or {}
        if str(issue.get("work_type") or record.work_type or "") not in SATISFIABLE_TYPES:
            return False
        hints = _hints(issue)
        project_dir = P.project_dir_for(hub, run)
        rows = existence(project_dir, hints)
        if not hints or not all(r["exists"] and r["size"] for r in rows) or not await _tracked_and_clean(project_dir, hints):
            return False
        handler = P.handler_for(hub, record)
        ctx = P.make_context(hub, run, record)
        await P.begin_step(hub, run, record, handler, ctx)
        verification = await P.verify_step(hub, run, record, handler, ctx, hints)
        dod = G.task_dod(verification, "NOTHING", False, auto_commit=bool(hub.get_settings().get("auto_commit", True)))
        unmet = [c["text"] for c in dod if not c["ok"]]
        if unmet:                                              # kanıt yetmedi: adımı geri al, ajan çalışsın
            record.status, record.verification, record.started_at = "PENDING", None, None
            await hub.record_task_audit(record.issue_id, "SYSTEM", "SATISFIED_CHECK_FAILED", notes=(tx("Zaten karşılanıyor kanıtı yetmedi: ") + "; ".join(unmet))[:280])
            return False
        summary = (tx("Zaten karşılanıyor: görevin {n} dosyası projede var ve commit'li; sunucu doğrulaması geçti ({summary}). ", n=len(hints), summary=verification.get('summary'))
                   + tx("Ajana iş verilmedi, yeni dosya yazılmadı."))
        record.status, record.action, record.summary = "DONE", "ALREADY_SATISFIED", summary
        record.finished_at = datetime.now(timezone.utc).isoformat()
        record.commit_status, record.commit_note, record.dod = "NOTHING", tx("zaten karşılanıyor: değişiklik yok"), dod
        run.touch()
        await hub.update_jira_issue(record.issue_id, {"status": "DONE", "agent_id": handler.agent_id, "audit_action": "ALREADY_SATISFIED",
                                                      "audit_notes": summary[:280], "files_affected": hints})
        await hub.update_task(task_id=record.issue_id, new_state="QA_TESTING", title=ctx.title, assignee=handler.agent_id,
                              priority=issue.get("priority", "P0"), details=tx("Zaten karşılanıyor: {title}", title=ctx.title))
        await hub.record_event(trace_id=run.run_id, from_agent=handler.agent_id, to_agent=handler.next_agent_id or "QA", action="TASK_ALREADY_SATISFIED", status="SUCCESS",
                               payload={"order": record.order, "task_id": record.issue_id, "files": hints, "verification": record.verification}, tokens_used=0,
                               friendly_dialogue=tx("'{title}' zaten karşılanıyor: dosyalar projede, testler geçiyor. Yeniden yazmadım.", title=ctx.title))
        await hub.set_agent_status(handler.agent_id, "IDLE")
        await P.advance_run(hub, run)
        return True
    except Exception:                                          # kontrol hiçbir zaman adımı düşürmez: ajan normal yoldan çalışır
        if record.status == "ACTIVE" and not record.summary:
            record.status = "PENDING"
        return False
