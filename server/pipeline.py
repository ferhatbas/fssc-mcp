"""
Motor bağımsız pipeline çekirdeği.

Hem süreç içi şablon motoru (TemplateEngine) hem de MCP istemcisinin çektiği adımlar
(McpClientEngine) burada tanımlı iki işlemi kullanır:

- `prepare_step(hub, run)`  → adımı ACTIVE yapar, START_THINKING olayını yayınlar ve istemciye
                               verilecek StepPrompt'u (sistem promptu, bağlam, çıktı sözleşmesi) üretir.
- `finish_step(hub, run, envelope)` → doğrulanmış A2A zarfını yorumlar, dosyaları yazar, olayları
                               yayınlar, Jira/Kanban'ı günceller ve onay kapısını değerlendirir.

Onay kararı geldiğinde `apply_approval_decision(hub, run, decision)` imleci ilerletir veya koşuyu bitirir.
"""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .fs_workspace import get_agent_markdown_info, get_standard_prompt_content
from .llm.parsing import StepOutputError, extract_json_block, normalize_a2a
from . import agent_registry as AR
from . import testing as TST
from . import layout as LAY
from .paths import hub_docs_path, is_protected_path, resolve_tokens
from .runs import PipelineRun, StepRecord
from .decisions import decisions_context, is_answered
from .tech_requirements import audit_dependencies
from .steps import StepContext, StepHandler, StepPrompt, StepResult, get_handler
from .steps.base import StepEvent
from .steps.tasks import normalize_backlog, normalize_improvements
from . import driver as DRV
from .doc_text import read_text
from . import guard as G
from . import i18n as I18N
from .i18n import translate as tx, N_
from . import langcheck as LANGCHECK
from . import meetings as M
from . import quality as Q
from . import scm as SCM
from . import sprint as SP
from .verify import VERIFY_DIR, effective_commands, failure_excerpt, infer_commands, planned_commands, public_summary, run_verification, sanitize_verification

NL = chr(10)
FIELD_RULES = I18N.N_(
    "\n## Saha Kuralları (sahadan öğrenildi)\n"
    "- Geçici dosya (zarf, betik, ara JSON) yalnızca `.fs-workspace/tmp/` altına; proje köküne asla.\n"
    "- Ekran/arayüz görevinde onaylı mockup'ı aç, çalışan ekranla karşılaştır ve arayüz kaynağını (.tsx/.css) mockup'a uyduracak şekilde değiştir; aynı dosyayı değiştirmeden yeniden vermek ya da yalnızca ekran sözleşmesi yazmak görevi kapatmaz.\n"
    "- Bir iş yapmadan/önermeden önce adı geçen sınıf, servis ve dosyaların projede zaten var olup olmadığına bak; var olanı yeniden açma, yeniden yazma.\n"
    "- Örnek metinleri (ürün adı, sektör, kullanıcı türü) kısıt sanma: yönetici örnek verdiyse onu genelle, örnekteki varsayımları zorunlu kılma.\n"
    "- Yöneticinin açık hedefi (Hedefler) dışında iş önerme ya da başlatma; belirsizse yönetici hedefini izle.\n"
)


PROMPT_ADDENDUM = I18N.N_(
    "\n\n---\n## Çıktı Kuralı (FS-SC Pipeline)\n"
    "Bu adımın sonucunu yalnızca istenen JSON zarfı olarak ver. Dosyaları kendin yazma; "
    "içeriklerini `payload.files` içinde ver, sunucu proje klasörüne yazar. Blok dışında açıklama yazma."
)


@dataclass
class StepOutcome:
    status: str  # 'NEXT' | 'WAITING_APPROVAL' | 'RUN_COMPLETE' | 'FAILED'
    approval_token: Optional[str] = None
    message: str = ""
    result: Optional[StepResult] = None


# ---------------------------------------------------------------------------
# Yardımcılar
# ---------------------------------------------------------------------------
def collect_spec_text(hub, max_chars: int = 120000) -> str:
    """Yüklü son şartnamenin toplantı notlarını (yoksa dosya içeriklerini) döner."""
    if not getattr(hub, "uploaded_specs", None):
        return ""
    latest = hub.uploaded_specs[-1]
    notes = (latest.get("meeting_notes") or "").strip()
    if not notes:
        for f in latest.get("files", []):
            spath = f.get("saved_path") if isinstance(f, dict) else None
            if spath and os.path.isfile(spath):
                try:
                    notes += f"\n\n---\n{read_text(spath)}"
                except Exception:
                    continue
    header = f"({latest.get('client_name', tx('Müşteri'))} — {latest.get('title', tx('Şartname'))})\n"
    text = header + notes
    return text[:max_chars] + (tx("\n... (kısaltıldı)") if len(text) > max_chars else "")


def _intake_spec_text(hub, run: PipelineRun, max_chars: int = 120000) -> str:
    """Sprint kipi: bu koşunun değerlendirdiği (bekleyen) yüklemelerin tamamı; yoksa boş (son şartname okunur)."""
    ids = list(getattr(run, "intake_spec_ids", []) or [])
    if run.mode != "sprint" or not ids:
        return ""
    chunks = []
    for spec in getattr(hub, "uploaded_specs", []) or []:
        if spec.get("id") not in ids:
            continue
        text = (spec.get("meeting_notes") or "").strip()
        if not text:
            for f in spec.get("files", []):
                sp = f.get("saved_path") if isinstance(f, dict) else None
                if sp and os.path.isfile(sp):
                    try:
                        text += "\n" + read_text(sp)
                    except Exception:
                        continue
        chunks.append(f"({spec.get('client_name', tx('Müşteri'))} — {spec.get('title', tx('Şartname'))})\n{text}")
    joined = "\n\n---\n".join(chunks)
    return joined[:max_chars] + (tx("\n... (kısaltıldı)") if len(joined) > max_chars else "")


def project_dir_for(hub, run: PipelineRun) -> str:
    if run.project_dir:
        return run.project_dir
    proj = hub.projects.get(run.project_id, {})
    return proj.get("path") or hub.default_project_path


def make_context(hub, run: PipelineRun, record: StepRecord, e2e_result: Optional[Dict[str, Any]] = None) -> StepContext:
    issue = hub.jira_issues.get(record.issue_id) or {"id": record.issue_id, "order": record.order, "title": record.title or f"Task {record.order}"}
    ctx = StepContext(
        hub=hub,
        run=run,
        record=record,
        issue=issue,
        project_dir=project_dir_for(hub, run),
        trace_id=run.run_id,
        prompt_text=run.custom_prompt or tx("Kurumsal Çok Katmanlı Servis ve Modern Arayüz Çözümü"),
        spec_text=_intake_spec_text(hub, run) or collect_spec_text(hub),
        lang=I18N.project_lang(hub),
    )
    if e2e_result is not None:
        setattr(ctx, "e2e_result", e2e_result)
    if record.kind == "fix":
        # Düzeltme adımı: aynı Jira maddesinin son başarısız doğrulamasını bağlama ekle
        prev = next((s for s in reversed(run.steps[:run.cursor]) if s.issue_id == record.issue_id and s.verification), None)
        setattr(ctx, "verification", prev.verification if prev else None)
    return ctx


def backlog_for(hub, raw: Any, max_tasks: int) -> List[Dict[str, Any]]:
    """Backlog normalizasyonu + etkin özel ajanlar (G6): `role` özel ajan kimliği olabilir, rolü bilinmeyen görev yeteneğe/odağa göre eşleşir."""
    return normalize_backlog(raw, max_tasks=max_tasks, custom_roles=AR.routing_roles(hub))


def handler_for(hub, record: StepRecord) -> StepHandler:
    issue = hub.jira_issues.get(record.issue_id) or {}
    return get_handler(record.order, issue, record)


def system_prompt_for(hub, run: PipelineRun, handler: StepHandler) -> str:
    """Projeye özel (.fs-workspace) ajan promptunu, yoksa şirket standardını döner."""
    project_dir = project_dir_for(hub, run)
    agent = hub.agents.get(handler.agent_id, {})
    role = AR.base_role_of(agent) if agent.get("role_base") else agent.get("role", handler.agent_id)       # G6: özel ajan temel rolünün istemini devralır
    lang = I18N.project_lang(hub)
    content = ""
    try:
        if project_dir and os.path.isdir(project_dir):
            info = get_agent_markdown_info(project_dir, handler.agent_id, role)
            content = (info or {}).get("active_content") or ""
            if lang != I18N.DEFAULT_LANG and int((info or {}).get("total_versions") or 0) <= 1:
                content = ""        # kullanıcı düzenlemediyse proje kopyası Türkçe standarttan kalıtılmıştır: proje dilindeki şirket standardı kullanılır
    except Exception:
        content = ""
    if not content.strip():
        content = get_standard_prompt_content(role, lang=lang)
    extra = str(agent.get("prompt_addendum") or "").strip()
    if extra:
        content = content.rstrip() + f"\n\n## {I18N.translate('Bu ajana özel ek yönerge', lang)} ({handler.agent_id})\n{extra}\n"
    return resolve_tokens(content.rstrip() + I18N.translate(PROMPT_ADDENDUM, lang) + I18N.translate(FIELD_RULES, lang), hub_docs_path(hub, "", project_dir))


def write_files(project_dir: str, files: List[Dict[str, str]], scan_secrets: bool = True) -> List[str]:
    """`payload.files` listesini proje köküne yazar; kök dışına çıkan yollar reddedilir.
    G4 (§12 madde 4): yüksek güvenli sır kalıpları (özel anahtar, AWS/GitHub/Slack/API anahtarı) diske yazılmadan ÖNCE reddedilir —
    teslim REJECTED olur, ajan aynı order'ı düzeltir; commit öncesi tarama ikinci ağdır (atanmış parola/secret)."""
    base = Path(project_dir).resolve()
    if scan_secrets:
        findings = G.scan_delivery(files)
        if findings:
            errs = [tx("Sır bulundu, hiçbir dosya yazılmadı: {file}:{line} {kind} ({preview}). "
                       "Değeri ortam değişkeninden oku (os.environ / process.env); koda, belgeye ya da .env'e gerçek değer yazma.",
                       file=f['file'], line=f['line'], kind=f['kind'], preview=f['preview']) for f in findings[:5]]
            exc = StepOutputError(tx("Teslimde sır (anahtar/parola) var; dosya yazılmadı: ")
                                  + "; ".join(f"{f['file']}:{f['line']} {f['kind']}" for f in findings[:5]), errs)
            exc.secret_findings = findings       # finish_step olay + denetim izi + sprint güvenlik ihlali kaydeder
            raise exc
    written: List[str] = []
    for f in files:
        rel = str(f.get("path", "")).strip().replace("\\", "/").lstrip("/")
        if not rel or rel.startswith("..") or "/../" in f"/{rel}/":
            raise StepOutputError(tx("Geçersiz dosya yolu: {path}", path=f.get('path')), [tx("Geçersiz dosya yolu: {path}", path=f.get('path'))])
        if is_protected_path(rel):
            raise StepOutputError(tx("Korunan yola yazım reddedildi: {rel}", rel=rel), [tx("Korunan yol (.fs-workspace/.git yazılamaz): {rel}", rel=rel)])
        target = (base / rel).resolve()
        try:
            resolved_rel = target.relative_to(base).as_posix()
        except ValueError:
            raise StepOutputError(tx("Proje kökü dışına yazım reddedildi: {rel}", rel=rel), [tx("Kök dışı yol: {rel}", rel=rel)])
        if is_protected_path(resolved_rel):  # sembolik bağ / kısa ad ile korunan yola dolanma
            raise StepOutputError(tx("Korunan yola yazım reddedildi: {rel}", rel=rel), [tx("Korunan yol (.fs-workspace/.git yazılamaz): {rel}", rel=rel)])
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(f.get("content", ""))
        written.append(rel)
    return written


DELETE_LIMIT = 80
_NO_DELETE = ("package.json", "package-lock.json", "tsconfig.json", ".gitignore", "README.md", "LICENSE", "CLAUDE.md", "GEMINI.md")


def delete_files(project_dir: str, rels: Any) -> List[str]:
    """Teslimdeki `payload.delete[]` yollarını siler (yalnızca var olan dosyalar; klasör, korunan yol, kök dışı ve yönetim dosyaları reddedilir). Silinen yolları döner."""
    if not rels:
        return []
    if not isinstance(rels, list):
        raise StepOutputError(tx("payload.delete bir yol listesi olmalı."), [tx("payload.delete bir yol listesi olmalı.")])
    base = Path(project_dir).resolve()
    deleted: List[str] = []
    for raw in rels:
        rel = str(raw or "").strip().replace("\\", "/").lstrip("/")
        if len(deleted) >= DELETE_LIMIT:
            raise StepOutputError(tx("En çok {n} dosya silinebilir.", n=DELETE_LIMIT), [tx("En çok {n} dosya silinebilir.", n=DELETE_LIMIT)])
        if not rel or rel.startswith("..") or "/../" in f"/{rel}/" or is_protected_path(rel):
            raise StepOutputError(tx("Silinemez yol: {rel}", rel=rel or raw), [tx("Silinemez yol: {rel}", rel=rel or raw)])
        if rel in _NO_DELETE or rel.rsplit("/", 1)[-1] in ("package.json", "tsconfig.json"):
            raise StepOutputError(tx("Yönetim dosyası silinemez: {rel}", rel=rel), [tx("Yönetim dosyası silinemez: {rel}", rel=rel)])
        target = (base / rel).resolve()
        try:
            target.relative_to(base)
        except ValueError:
            raise StepOutputError(tx("Proje kökü dışı yol: {rel}", rel=rel), [tx("Kök dışı yol: {rel}", rel=rel)])
        if not target.is_file():
            raise StepOutputError(tx("Silinecek dosya yok (ya da klasör): {rel}", rel=rel), [tx("Silinecek dosya yok (ya da klasör): {rel}", rel=rel)])
        target.unlink()
        deleted.append(rel)
    return deleted


async def pace(hub, run: PipelineRun, seconds: float):
    """Doğal akış hızı: yalnızca şablon motorunda ve 'natural' ayarında uyur."""
    if run.engine != "template" or seconds <= 0:
        return
    if hub.get_settings().get("pacing", "natural") == "instant":
        return
    await asyncio.sleep(min(seconds, 3.0))


async def publish_run(hub, run: PipelineRun):
    await hub.broadcast({"type": "RUN_UPDATED", "run": run.to_dict()})
    hub.mark_dirty()


# ---------------------------------------------------------------------------
# Adım başlangıcı
# ---------------------------------------------------------------------------
async def begin_step(hub, run: PipelineRun, record: StepRecord, handler: StepHandler, ctx: StepContext):
    """Adımı ACTIVE yapar; Jira IN_PROGRESS, Kanban DEVELOPMENT ve START_THINKING olayı (idempotent)."""
    if record.status in ("ACTIVE", "WAITING_APPROVAL"):
        return
    record.status = "ACTIVE"
    record.started_at = datetime.now(timezone.utc).isoformat()
    record.attempts = 0
    try:                                       # ajanın önceki adımdan köke bıraktığı geçici betik/zarf dosyaları .fs-workspace/tmp/ altına
        from .project_bootstrap import sweep_stray_root_files
        await asyncio.to_thread(sweep_stray_root_files, ctx.project_dir)
    except Exception:
        pass
    run.status = "ACTIVE"
    if not run.started_at:
        run.started_at = record.started_at
    hub.active_run_id = run.run_id
    label = tx("Adım #{n}", n=record.order) + (tx(" (düzeltme {n})", n=record.fix_round) if record.kind == "fix" else "") + f": {ctx.title}"
    await hub.set_agent_status(handler.agent_id, "BUG_FIX" if record.kind == "fix" else "WORKING", what_doing=label)

    if record.kind not in ("plan", "close", "meeting", "review"):    # sprint akış adımlarının Jira maddesi yoktur (issue_id=SPRINT-n)
        await hub.update_jira_issue(record.issue_id, {
            "status": "IN_PROGRESS", "agent_id": handler.agent_id,
            "audit_action": "FIX_STARTED" if record.kind == "fix" else "STEP_STARTED",
            "audit_notes": label,
        })
        await hub.update_task(
            task_id=record.issue_id,
            new_state="DEVELOPMENT",
            title=ctx.title,
            assignee=handler.agent_id,
            priority=ctx.issue.get("priority", "P0"),
            details=tx("Otonom ajan çalışmaya başladı: {label}", label=label),
        )
    thinking, doing, nxt = handler.thinking_for(ctx)
    shown_title = handler.display_title(ctx)
    await hub.record_event(
        trace_id=run.run_id,
        from_agent=handler.agent_id,
        to_agent=handler.next_agent_id or "PM",
        action="START_THINKING",
        status="SUCCESS",
        payload={"task_id": record.issue_id, "title": shown_title, "phase": "ANALYSIS_AND_THINKING", "order": record.order, "engine": run.engine},
        current_file=f"task_{record.order}",
        tokens_used=60,
        friendly_dialogue=tx("Selamlar! '{title}' görevi üzerinde çalışmaya başladım. {thinking}", title=shown_title, thinking=thinking),
        thinking=thinking,
        what_doing=doing,
        what_next=nxt,
    )
    await publish_run(hub, run)
    await pace(hub, run, 1.0)


async def prepare_step(hub, run: PipelineRun) -> StepPrompt:
    """Geçerli adım için istemciye verilecek promptu üretir (adım ACTIVE değilse başlatır). Metinler projenin dilinde üretilir (server/i18n.py)."""
    with I18N.use_lang(I18N.project_lang(hub)):
        return await _prepare_step(hub, run)


async def _prepare_step(hub, run: PipelineRun) -> StepPrompt:
    record = run.current_step
    if record is None:
        raise ValueError("Koşuda işlenecek adım kalmadı.")
    if run.mode == "sprint" and record.kind == "phase" and record.order == 1 and record.status == "PENDING":
        # Değerlendirme başlamadan önce kuyruğa düşen yüklemeler de bu değerlendirmeye eklenir (ikinci değerlendirme açılmaz, A19)
        pending = (SP.ensure_state(hub).get("pending_intake") or {}).get("spec_ids", [])
        run.intake_spec_ids = list(dict.fromkeys([*run.intake_spec_ids, *pending]))
    handler = handler_for(hub, record)
    ctx = make_context(hub, run, record)
    if record.kind == "review":
        setattr(ctx, "git_diff", await SCM.diff_text(ctx.project_dir))     # ARCHITECT gözden geçirmesinin girdisi: son etiketten bu yana fark
    await begin_step(hub, run, record, handler, ctx)
    user_context = handler.build_user_prompt(ctx)
    if record.kind not in ("meeting", "plan", "close"):
        layout_block = LAY.prompt_section(LAY.layout_of(hub), ctx.docs_root)       # apps/devops/docs düzeni (rol promptundaki örnek yolların önüne geçer)
        if layout_block:
            user_context += "\n\n" + layout_block
        user_context += "\n\n" + LAY.devops_rule_section(LAY.layout_of(hub), run.project_id)       # kalıcı kural: Docker dosyaları devops/ altında (her kipte)
    if record.kind == "task":
        try:
            from . import satisfied as SAT
            user_context += SAT.context_section(ctx.project_dir, ctx.issue)       # görevin dosyalarından hangisi zaten var / eksik
        except Exception:
            pass
    if record.kind in ("task", "fix", "phase", "review") and not handler.server_side:
        try:
            from . import skills as SKL
            skill_block = SKL.prompt_section(hub, handler.agent_id)
            if skill_block:
                user_context += skill_block                      # ajanın tanımına EK skill rehberleri (tavsiye; görev ve kabul kriterleri önceliklidir)
        except Exception:                                        # skill bölümü adımı asla düşürmez
            pass
    notes = [h for h in run.handoffs[-12:] if h.get("to") in (handler.agent_id, "ALL")]
    if notes:
        user_context += tx("\n\n## Önceki rollerden devir notları\n") + "\n".join(tx("- {frm} (adım #{n}): {message}", frm=h['from'], n=h['order'], message=h['message']) for h in notes)
    pending_before = sum(1 for n in run.manager_notes if n.get("delivered_step") is None)
    manager_block = deliver_manager_notes(run, record)
    if manager_block:
        user_context += manager_block
        if pending_before:
            await publish_run(hub, run)     # dashboard'da notların 'iletildi' durumu güncellenir
    contract = handler.output_contract(ctx)
    statement = str(hub.get_settings().get("product_statement") or "").strip()
    if statement:                                      # yönetici ürün tanımı bağlayıcıdır; şartnamedeki örnekler (ürün adı, sektör, kullanıcı türü) onu kısıtlayamaz
        user_context = (I18N.translate("## Ürün tanımı (yönetici, bağlayıcı)", None) + "\n" + statement + "\n"
                        + I18N.translate("Şartname ve notlardaki örnekler bu tanımı daraltmaz; çelişirse bu tanım geçerlidir.", None) + "\n\n" + user_context)
    user_context = I18N.directive() + "\n\n" + user_context      # çıktı dili yönergesi: bağlamdaki başlıklar başka dilde olsa da ajan proje dilinde yazar
    contract += "\n\n" + I18N.directive()
    record.prompt_chars = len(user_context) + len(contract)
    return StepPrompt(
        system_prompt=system_prompt_for(hub, run, handler),
        user_context=user_context,
        output_contract=contract,
        meta={
            "run_id": run.run_id,
            "order": record.order,
            "issue_id": record.issue_id,
            "agent_id": handler.agent_id,
            "agent_name": hub.agents.get(handler.agent_id, {}).get("name", handler.agent_id),
            "agent_profile": dict(hub.agents.get(handler.agent_id, {}).get("profile") or {}),     # G6: model / çaba / dil / araç izni ipuçları (istemci uygular)
            "next_agent_id": handler.next_agent_id,
            "action": handler.action,
            "critical": handler.critical,
            "server_side": handler.server_side,
            "title": ctx.title,
            "project_dir": ctx.project_dir,
        },
    )


# ---------------------------------------------------------------------------
# Adım bitişi
# ---------------------------------------------------------------------------
def parse_envelope(hub, run: PipelineRun, record: StepRecord, raw: Any) -> Dict[str, Any]:
    """Ham çıktıyı (metin/dict) toleranslı ayrıştırıp normalize A2A zarfı döner (hata → StepOutputError)."""
    handler = handler_for(hub, record)
    obj, _ = extract_json_block(raw)
    env, warnings = normalize_a2a(
        obj,
        default_from=handler.agent_id,
        default_to=handler.next_agent_id,
        default_intent=handler.action,
        trace_id=run.run_id,
    )
    env.setdefault("_warnings", warnings)
    return env


async def _emit_events(hub, run: PipelineRun, events: List[StepEvent]):
    for ev in events:
        await hub.record_event(
            trace_id=run.run_id,
            from_agent=ev.from_agent,
            to_agent=ev.to_agent,
            action=ev.action,
            status=ev.status,
            payload=ev.payload,
            current_file=ev.current_file,
            tokens_used=ev.tokens_used,
            friendly_dialogue=ev.friendly_dialogue,
            thinking=ev.thinking,
            what_doing=ev.what_doing,
            what_next=ev.what_next,
        )
        await pace(hub, run, ev.pause_after_s or 1.5)


def _step_info(hub, run: PipelineRun, record: StepRecord, handler: StepHandler, result: StepResult, ctx: StepContext) -> Dict[str, Any]:
    agent = hub.agents.get(handler.agent_id, {})
    nxt = result.next_agent_id
    return {
        "run_id": run.run_id,
        "order": record.order,
        "issue_id": record.issue_id,
        "title": ctx.title,
        "agent_id": handler.agent_id,
        "agent_name": agent.get("name", handler.agent_id),
        "agent_role": agent.get("role", "Specialist"),
        "next_agent_id": nxt,
        "next_agent_name": hub.agents.get(nxt, {}).get("name", nxt) if nxt else tx("Pipeline Tamamlandı"),
        "action": result.action,
        "summary": result.summary,
        "artifacts": result.artifacts,
        "screenshots": result.screenshots,
        "tokens_used": result.tokens,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "is_last_step": run.cursor >= len(run.steps) - 1,
        "engine": run.engine,
        "status": result.status,
        "kind": record.kind,
        "fix_round": record.fix_round,
        "step_index": run.cursor + 1,
        "total_steps": len(run.steps),
        "verification": record.verification,
        "commit": record.commit,
        "fix_requested": bool(result.extra.get("fix_requested")),
        "inserted_steps": int(result.extra.get("inserted_steps") or 0),
    }


def _restored_artifacts(project_dir: str, paths: List[Any], limit_files: int = 12, limit_chars: int = 20000) -> List[Dict[str, Any]]:
    """Adım kaydındaki dosya yollarından onay kartı artefaktları ({name, path, type, content}); içerik diskten (sınırlı) okunur."""
    out: List[Dict[str, Any]] = []
    for item in paths[:limit_files]:
        if isinstance(item, dict):
            out.append(item)
            continue
        rel = str(item)
        content = ""
        try:
            fp = os.path.join(project_dir or "", rel)
            if os.path.isfile(fp):
                with open(fp, "r", encoding="utf-8", errors="replace") as fh:
                    content = fh.read(limit_chars)
        except Exception:
            content = ""
        out.append(StepHandler.artifact_from_file({"path": rel, "content": content}))
    return out


def step_info_from_record(hub, run: PipelineRun, record: StepRecord) -> Dict[str, Any]:
    """Teslim edilmiş adımın onay kartı bilgisi, adım kaydından: sunucu yeniden başlayınca onay kapısı bellekten kaybolur, yeniden açılırken kullanılır."""
    agent = hub.agents.get(record.role, {})
    return {
        "run_id": run.run_id, "order": record.order, "issue_id": record.issue_id, "title": record.title or record.issue_id,
        "agent_id": record.role, "agent_name": agent.get("name", record.role), "agent_role": agent.get("role", "Specialist"),
        "next_agent_id": None, "next_agent_name": "", "action": record.action, "summary": record.summary,
        "artifacts": _restored_artifacts(project_dir_for(hub, run), list(record.artifacts or [])), "screenshots": [],
        "tokens_used": int(record.tokens_in or 0) + int(record.tokens_out or 0),
        "timestamp": datetime.now(timezone.utc).isoformat(), "is_last_step": run.cursor >= len(run.steps) - 1, "engine": run.engine,
        "status": "FAILED" if record.error else "SUCCESS", "kind": record.kind, "fix_round": record.fix_round,
        "step_index": run.cursor + 1, "total_steps": len(run.steps), "verification": record.verification, "commit": record.commit,
        "fix_requested": False, "inserted_steps": 0,
    }


def should_wait(hub, run: PipelineRun, handler: StepHandler, result: StepResult) -> str:
    """
    Onay kararı: 'WAIT' (kullanıcı onayı bekle), 'NOTE' (el kaldır, not al ve devam et), 'SKIP' (durma).
    - auto: hiç durma
    - critical_only: kritik adımlar (mimari, QA kararı, dağıtım, UAT) ve başarısız adımlar
    - every_step: her adım
    - note_and_continue: durmadan her adımı 'kaldırılan eller' listesine yaz; başarısız adımda yine bekle
    """
    if getattr(handler, "force_approval", False) and result.status != "FAILED" and run.engine != "template":
        return "WAIT"                    # tasarım sistemi + ilk ekranlar: otomatik kipte de yönetici onayı (frontend onaysız başlamaz)
    # AUTO_ALL kararı koşuya özeldir: başka bir koşu (veya sonraki koşu) onay modundan etkilenmez
    auto_run = getattr(hub, "auto_proceed_run_id", None)
    if hub.auto_proceed_all and (auto_run is None or auto_run == run.run_id):
        return "SKIP"
    # Koşu kendi bayrağını taşır (start_run: açıkça verilmediyse hub.step_by_step_mode'dan alınır)
    if not run.step_by_step:
        return "SKIP"
    mode = hub.get_settings().get("approval_mode", "every_step")
    failed = result.status == "FAILED"
    if mode == "auto":
        return "SKIP"
    if mode == "critical_only":
        return "WAIT" if (handler.critical or failed) else "SKIP"
    if mode == "note_and_continue":
        return "WAIT" if failed else "NOTE"
    return "WAIT"


def _needs_approval(hub, run: PipelineRun, handler: StepHandler, result: StepResult) -> bool:
    return should_wait(hub, run, handler, result) == "WAIT"


def _apply_layout(hub, run: PipelineRun, record: StepRecord, handler: StepHandler, ctx: StepContext, envelope: Dict[str, Any]) -> Dict[str, Any]:
    """Proje klasör düzeni (apps/devops/docs): LLM teslimi DOĞRULANIR (uymayan yol REJECTED, öneri yolla); şablon motoru, sunucu tarafı adımlar ve
    `enforce` kapalıyken teslim düzene TAŞINIR. Düz düzende (varsayılan) hiçbir şey değişmez."""
    lay = LAY.layout_of(hub)
    if record.kind != "meeting" and run.engine != "template" and not handler.server_side:
        # Kalıcı kural: Docker/compose dosyaları her düzen kipinde yalnızca devops/ altında (LLM teslimi reddedilir, öneri yolla)
        pl = envelope.get("payload") if isinstance(envelope.get("payload"), dict) else {}
        bad_docker = LAY.docker_violations(lay, [ctx.r(f["path"]) for f in (pl.get("files") or []) if isinstance(f, dict) and f.get("path")])
        if bad_docker:
            raise StepOutputError(tx("Docker/compose dosyası devops/ dışında: ") + bad_docker[0], bad_docker[:8])
    if not LAY.is_apps(lay) or record.kind == "meeting":
        return envelope
    payload = envelope.get("payload") if isinstance(envelope.get("payload"), dict) else {}
    relocating = run.engine == "template" or handler.server_side or not lay.get("enforce")
    if relocating and record.kind == "phase" and record.order == 2 and isinstance(payload.get("verification"), dict):
        # Şablonun kökte yazdığı doğrulama komutları ana uygulamanın klasöründe koşar (`cd apps/backend && ...`); LLM teslimine dokunulmaz:
        # onun kökte yazdığı komutlar kullanım anında verify.adapt_saved_commands ile uyarlanır
        payload["verification"] = LAY.prefix_verification(payload["verification"], LAY.app_folder(lay, "backend"))
    files = [f for f in (payload.get("files") or []) if isinstance(f, dict) and f.get("path")]
    if not files:
        return envelope
    docs_root = ctx.docs_root
    if relocating:
        LAY.relocate_envelope(lay, envelope, handler.agent_id, docs_root, resolve=ctx.r)
        return envelope
    bad = LAY.violations(lay, [ctx.r(f["path"]) for f in files], docs_root, handler.agent_id)
    if bad:
        raise StepOutputError(tx("Teslim proje klasör düzenine uymuyor: ") + bad[0], bad[:8])
    return envelope


async def finish_step(hub, run: PipelineRun, envelope: Dict[str, Any], tokens_in: int = 0, tokens_out: int = 0) -> StepOutcome:
    """Zarfı yorumlar, dosyaları yazar, olayları yayınlar, Jira DONE yapar ve onay kapısını değerlendirir."""
    record = run.current_step
    if record is None:
        return StepOutcome(status="RUN_COMPLETE", message=tx("Koşu zaten tamamlandı."))
    handler = handler_for(hub, record)
    ctx = make_context(hub, run, record)

    envelope = _apply_layout(hub, run, record, handler, ctx, envelope)
    result = handler.render(ctx, envelope)

    # Bağımlılık denetimi (§7.4 madde 8): onaylı teknoloji / kayıtlı kütüphane dışı ekleme içeren teslim yazılmadan reddedilir
    violations = audit_dependencies(hub.tech_requirements(), ctx.project_dir, result.files)
    if violations:
        await hub.request_tech_addition(violations)       # yönetici kararıyla zaten onaylı olanlar kütüphane kaydına işlenir (sorulmaz), kalanlar için soru açılır
        violations = [v for v in violations if not hub._decided_dependency(v["dependency"])]
    if violations:
        errs = [tx("Kayıtsız bağımlılık: '{dep}' ({file}) onaylı teknolojilerde ve mimarın kütüphane kaydında yok. "
                   "Kullanma ya da yöneticiden onay iste (TECHNOLOGY sorusu açıldı).", dep=v['dependency'], file=v['file']) for v in violations][:8]
        raise StepOutputError(errs[0], errs)
    try:
        written = write_files(ctx.project_dir, result.files)
    except StepOutputError as e:
        if getattr(e, "secret_findings", None):
            await _record_delivery_secret(hub, run, record, handler, e.secret_findings)     # G4: yazım anı sır bulgusu
        raise
    result.extra["files_written"] = written
    if record.kind in ("task", "fix") and (envelope.get("payload") or {}).get("delete"):
        deleted = delete_files(ctx.project_dir, (envelope.get("payload") or {}).get("delete"))
        result.extra["files_deleted"] = deleted
        result.summary = f"{result.summary} " + tx("[{n} dosya silindi]", n=len(deleted))
        await hub.record_task_audit(record.issue_id, handler.agent_id, "FILES_DELETED", notes=(tx("Silinen dosyalar: ") + ", ".join(deleted))[:280])
    lang_findings = LANGCHECK.check_files(ctx.lang, result.files) + LANGCHECK.check_texts(ctx.lang, {"summary": result.summary})
    if lang_findings:                                                   # karışık dil: yalnızca uyarı (teslim reddedilmez)
        result.extra["language_warnings"] = lang_findings
        msg = LANGCHECK.warning_text(lang_findings)
        try:
            await hub.record_event(trace_id=run.run_id, from_agent="SERVER", to_agent=handler.agent_id, action="LANGUAGE_WARNING", status="WARNING",
                                   payload={"order": record.order, "language": ctx.lang, "findings": lang_findings[:8]}, current_file="", tokens_used=0,
                                   friendly_dialogue=msg, thinking="", what_doing=msg, what_next="")
        except Exception:
            pass
    if record.kind == "meeting":
        from . import meetings as MEET
        meeting = await MEET.deliver(hub, run, record, envelope.get("payload") or {}, ctx.project_dir)
        if record.work_type == "adhoc":
            from . import sprint_flow as SPF
            await SPF.apply_adhoc(hub, run, record, envelope.get("payload") or {})     # G3 (§8.4): başlamamış işlerle yer değiştirme
        result.extra["meeting_id"] = meeting["id"]
        result.summary = f"{result.summary} " + tx("[{id} · {n} karar, {m} soru]", id=meeting['id'], n=len(meeting['decision_ids']), m=len(meeting['question_ids']))
        if meeting.get("file"):
            result.artifacts.append({"name": os.path.basename(meeting["file"]), "path": meeting["file"], "type": "markdown", "content": ""})
    if record.kind == "meeting" or any(os.path.basename(str(w)).lower() == "architecture.md" for w in written):
        from .doc_sync import sync_architecture       # mimar belgesi yazıldı ya da yeni karar/ADR çıkabilir: güncel karar durumu bölümünü yenile
        sync_architecture(hub, ctx.project_dir)
    payload = envelope.get("payload") or {}
    settings = hub.get_settings()

    # Şartnameye özgü açık kararlar (PM adımı): soru setine eklenir; kapı bir sonraki LLM adımında açılır
    asked = payload.get("decisions_needed")
    if isinstance(asked, list) and asked:
        try:
            await hub.add_spec_questions(asked)
        except Exception:
            pass

    # PM'in notlardan çıkardığı teknoloji ipuçları (alıntısı notlarda doğrulanırsa kullanılır) ve mimarın kütüphane kaydı
    if record.kind == "phase" and record.order == 1 and isinstance(payload.get("tech_extraction"), list):
        await hub.update_settings({"tech_extraction_hints": [h for h in payload["tech_extraction"] if isinstance(h, dict)][:30]})
    if record.kind == "phase" and record.order == 2 and isinstance(payload.get("libraries"), list):
        await hub.register_libraries(payload["libraries"])

    # Mimar / DevOps doğrulama ve çalıştırma komutları önerir → proje ayarlarında saklanır (güvenli alt küme)
    proposed = sanitize_verification(payload.get("verification"))
    if proposed and G.sandbox(hub)["command_policy"] == "allowlist":
        proposed = await _gate_proposed_commands(hub, run, record, proposed)     # liste dışı komut bir sorudur (§12 madde 1)
    if proposed and record.kind == "phase" and record.order in (2, 8):
        merged = {**(settings.get("verification") or {}), **proposed}
        await hub.update_settings({"verification": merged})
        settings = hub.get_settings()

    await _emit_events(hub, run, result.events)
    result.extra["manager_replies"] = await record_manager_replies(hub, run, record, handler, payload)
    handoff = list(payload.get("handoff") or envelope.get("handoff") or [])
    if isinstance(payload.get("screens"), list) and payload["screens"]:
        # Frontend ekran sözleşmesi: ekranlar projeye yazılır, Tester'a "neler yapılabilir" devir notu bırakılır (E2E adımı Playwright + görüntü koşar)
        from . import ui_screens as UIS
        saved = UIS.ingest(ctx.project_dir, payload["screens"])
        if saved:
            handoff += UIS.handoff_notes(UIS.normalize(payload["screens"]))
            result.extra["screens"] = saved
    await _record_handoffs(hub, run, record, handler, {**payload, "handoff": handoff}, result)
    if handler.agent_id == "QA" and isinstance(payload.get("bugs"), list) and payload.get("bugs"):
        # G1: QA bulguları olay değil Jira'da BUG maddesi olur (sprint planı P0 hataları öne alır)
        result.extra["bug_issues"] = await _create_bug_issues(hub, run, record, payload["bugs"])

    # G7: QA'nın TEST_DESIGN teslimi → TC-n kimliği, <docs>/tests/TC-n.md, Jira TEST_CASE; belgeler commit'e girer
    if record.kind == "task" and str(ctx.issue.get("work_type") or "") == "TEST_DESIGN" and result.status != "FAILED":
        design = await TST.ingest_design(hub, run, record, payload)
        result.extra["test_design"] = design
        made = [TST.store(hub)["cases"][i] for i in design["created"]]
        written = list(written) + [c["file"] for c in made if c.get("file")]
        result.extra["files_written"] = written
        result.summary = f"{result.summary} " + tx("✓ {n} test case: {ids}{more}.", n=len(design['created']), ids=', '.join(design['created'][:6]),
                                                   more='…' if len(design['created']) > 6 else '')

    # Token muhasebesi (istemci tahmini yoksa metin uzunluğundan)
    t_in = int(tokens_in or 0) or max(0, getattr(record, "prompt_chars", 0) // 4)
    t_out = int(tokens_out or 0) or result.tokens
    if run.engine == "mcp_client" and not int(tokens_out or 0):
        t_out = max(1, len(json.dumps(payload, ensure_ascii=False)) // 4)   # bildirilmediyse teslim edilen yükün boyutundan (≈4 karakter/token)
    record.tokens_in, record.tokens_out = t_in, t_out
    if await DRV.check_task_tokens(hub, run, record):
        result.extra["token_limit"] = True

    record.artifacts = [a["path"] for a in result.artifacts]

    # --- Sunucu tarafı doğrulama (sözdizimi → kurulum → lint → build → test) ve düzeltme döngüsü ---
    inserted = 0
    verification: Optional[Dict[str, Any]] = None
    # Kanıtla kapanış (`payload.already_satisfied`): dosya teslimi yok; kanıt gösterilen testler sunucuca koşar (gerçek test + commit'li test dosyası)
    satisfied_tests = list(result.extra.get("satisfied_tests") or [])
    verify_paths = written or satisfied_tests
    if satisfied_tests and not written:
        record.commit_status, record.commit_note = "NOTHING", tx("zaten karşılanıyor: yeni dosya yok, kanıt testleri koştu")
        await hub.record_task_audit(record.issue_id, handler.agent_id, "SATISFIED_BY_EVIDENCE",
                                    notes=(tx("Ajan görevi mevcut kodla karşılanmış saydı; kanıt testleri: ") + ", ".join(satisfied_tests))[:280])
    if handler.verify_after and settings.get("auto_verify", True) and not record.server_side and verify_paths:
        verification = await verify_step(hub, run, record, handler, ctx, verify_paths)
        record.error_sig = G.error_signature(verification)
        if verification.get("status") == "FAILED":
            fix = await request_fix(hub, run, record, handler, ctx, verification)
            if fix is not None:
                inserted += 1
                result.extra["fix_requested"] = True
                result.summary = f"{result.summary} " + tx("⚠ Doğrulama başarısız ({step}); düzeltme turu {n} açıldı.", step=verification.get('failed_step'), n=fix.fix_round)
            else:
                result.status = "FAILED"
                result.summary = f"{result.summary} " + tx("✗ Doğrulama {step} adımında kaldı; düzeltme hakkı bitti.", step=verification.get('failed_step'))
        elif verification.get("status") == "PASSED" and record.kind in ("task", "fix"):
            # Doğrulama geçti: aynı görevin bekleyen düzeltme adımları (önceki başarısız denemelerden, ör. altyapı hatasından kalan) gereksiz
            stale = [s for s in run.steps[run.cursor + 1:] if s.kind == "fix" and s.issue_id == record.issue_id and s.status == "PENDING"]
            if stale:
                run.steps[:] = [s for s in run.steps if not any(s is x for x in stale)]
                result.extra["dropped_fix_steps"] = len(stale)
                result.summary = f"{result.summary} " + tx("✓ Doğrulama geçti; {n} bekleyen düzeltme adımı kaldırıldı.", n=len(stale))
                await hub.record_task_audit(record.issue_id, "SYSTEM", "STALE_FIX_DROPPED",
                                            notes=tx("Doğrulama geçti; {n} bekleyen düzeltme adımı kaldırıldı.", n=len(stale)))

    # --- SCM commit (doğrulama geçtiyse ya da doğrulama yoksa) ---
    if (handler.commit_after and settings.get("auto_commit", True) and written
            and (verification is None or verification.get("status") != "FAILED")):
        await commit_step(hub, run, record, handler, ctx)

    # --- Tasarım teslimi tamlık denetimi: dosyalara bakılır (viewport/duyarlılık, durum bölümleri, uç kapsamı, akış haritası); eksik varsa düzeltme turu açılır ---
    if (record.kind in ("task", "fix") and str(ctx.issue.get("work_type") or "") == "DESIGN" and not record.server_side
            and result.status != "FAILED" and not result.extra.get("fix_requested") and run.engine != "template"):
        from . import design_check as DCK
        d_issues = DCK.check(ctx.project_dir, ctx.docs_root, payload.get("design") if isinstance(payload.get("design"), dict) else None, redesign=bool(ctx.issue.get("redesign")))
        if d_issues:
            text = tx("Tasarım teslimi eksik: ") + " | ".join(d_issues[:12])
            synthetic = {"status": "FAILED", "failed_step": "design_check", "ran_install": False, "summary": text,
                         "results": [{"name": "design_check", "cmd": "design_check", "exit_code": 1, "status": "FAILED", "duration_ms": 0, "output": NL.join(d_issues)}]}
            record.verification = public_summary(synthetic)
            record.error_sig = G.error_signature(synthetic)
            fix = await request_fix(hub, run, record, handler, ctx, synthetic)
            if fix is not None:
                inserted += 1
                result.extra["fix_requested"] = True
                result.summary = f"{result.summary} " + tx("⚠ {reason}; düzeltme turu {n} açıldı.", reason=text[:200], n=fix.fix_round)
            else:
                result.summary = f"{result.summary} " + tx("⚠ Tasarım teslimi eksik kaldı; düzeltme hakkı bitti: ") + " | ".join(d_issues[:6])
    # --- Ekran uyumu kabul kapısı: tasarımdan açılan ekran görevi, onaylı mockup ile çalışan ekran karşılaştırılmadan bitmiş sayılmaz (ajan beyanına değil tarayıcıya bakılır) ---
    if (record.kind in ("task", "fix") and ctx.issue.get("design_screen") and not record.server_side and written and result.status != "FAILED"
            and not result.extra.get("fix_requested") and run.engine != "template" and settings.get("fidelity_gate", True)):
        from . import fidelity as FID
        try:
            gate = await FID.check_screen(hub, ctx.project_dir, ctx.docs_root, ctx.issue)
        except Exception as e:                       # noqa: BLE001 — denetim altyapısı çökerse görev düşmez, not düşülür
            gate = {"ran": False, "ok": None, "problems": [], "note": str(e)[:160]}
        if gate.get("ran") and gate.get("ok") is False:
            text = tx("Ekran uyumu kabul kapısı geçilmedi: ") + " | ".join(gate["problems"][:6])
            synthetic = {"status": "FAILED", "failed_step": "fidelity", "ran_install": False, "summary": text,
                         "results": [{"name": "fidelity", "cmd": "fidelity", "exit_code": 1, "status": "FAILED", "duration_ms": 0, "output": gate.get("text") or text}]}
            record.verification = public_summary(synthetic)
            record.error_sig = G.error_signature(synthetic)
            fix = await request_fix(hub, run, record, handler, ctx, synthetic)
            if fix is not None:
                inserted += 1
                result.extra["fix_requested"] = True
                result.summary = f"{result.summary} " + tx("⚠ {reason}; düzeltme turu {n} açıldı.", reason=text[:200], n=fix.fix_round)
            else:
                result.status = "FAILED"
                result.summary = f"{result.summary} " + tx("✗ Ekran mockup ile uyuşmuyor; düzeltme hakkı bitti, görev bitmiş sayılmaz: ") + " | ".join(gate["problems"][:4])
        elif gate.get("note"):
            result.summary = f"{result.summary} " + tx("(ekran uyumu denetlenemedi: {note})", note=gate["note"])
    # --- Sır bulgusu ve sıkı DoD (§12 madde 4, §7.7): commit sonrası; ihlal düzeltme turu doğurur ---
    if handler.verify_after and not record.server_side and verify_paths and result.status != "FAILED" and not result.extra.get("fix_requested"):
        violation = None
        if record.commit_status == "SECRET":
            violation = ("secret_scan", tx("Sır taraması commit'i durdurdu: ") + str(record.commit_note))
        elif Q.strict(hub):
            if verification is None:
                result.status = "FAILED"
                result.summary = f"{result.summary} " + tx("✗ Sıkı DoD: doğrulama kapalı/çalışmadı (auto_verify); iş bitmiş sayılamaz.")
            else:
                record.dod = G.task_dod(verification, record.commit_status, pending_fix=False, auto_commit=bool(settings.get("auto_commit", True)), written=written,
                                        waive_tests=bool(SP.cfg(hub).get("no_tests")))
                unmet = [c for c in record.dod if not c["ok"]]
                if unmet:
                    violation = ("dod", tx("Sıkı DoD ihlali: ") + "; ".join(c["text"] for c in unmet))
        if violation:
            synthetic = {**(verification or {"results": [], "ran_install": False}), "status": "FAILED", "failed_step": violation[0],
                         "results": [*(verification or {}).get("results", []), {"name": violation[0], "cmd": violation[0], "exit_code": 1, "status": "FAILED",
                                                                                  "duration_ms": 0, "output": violation[1]}],
                         "summary": violation[1]}
            record.verification = public_summary(synthetic)
            record.error_sig = G.error_signature(synthetic)
            verification = synthetic
            if violation[0] == "secret_scan" and record.sprint:
                sp_ = SP.get_sprint(hub, record.sprint)
                if sp_ is not None:
                    sp_["security_violations"] = int(sp_.get("security_violations", 0)) + 1
                    if sp_["security_violations"] >= 2 and sp_["status"] != "BLOCKED":
                        await DRV.block_sprint(hub, run, sp_, "SECURITY_VIOLATION", tx("sır bulgusu {n}. kez tekrarlandı", n=sp_['security_violations']))
            fix = await request_fix(hub, run, record, handler, ctx, synthetic)
            if fix is not None:
                inserted += 1
                result.extra["fix_requested"] = True
                result.summary = f"{result.summary} " + tx("⚠ {reason}; düzeltme turu {n} açıldı.", reason=violation[1][:160], n=fix.fix_round)
            else:
                result.status = "FAILED"
                result.summary = f"{result.summary} " + tx("✗ {reason}; düzeltme hakkı bitti.", reason=violation[1][:160])

    # --- G7: QA adımının doğrulaması (junit) bir TEST_RUN kaydeder: case başına sonuç, başarısız case → BUG ---
    if record.kind == "phase" and record.order == 6 and result.status != "FAILED" and not result.extra.get("fix_requested"):
        try:
            test_run = await TST.record_run(hub, sprint=record.sprint, source="QA", project_dir=ctx.project_dir)
        except Exception:                                  # test yönetimi QA adımını düşürmez
            test_run = None
        if test_run:
            result.extra["test_run"] = test_run["id"]
            s = test_run["summary"]
            result.summary = f"{result.summary} ✓ {test_run['id']}: {s['pass']} PASS / {s['fail']} FAIL / {s['blocked']} BLOCKED."
    agent_status = "ERROR" if result.status == "FAILED" else ("BUG_FIX" if result.extra.get("fix_requested") else "COMPLETED")
    await hub.update_agent_metric(handler.agent_id, tokens_in=t_in, tokens_out=t_out, active_file=result.files[0]["path"] if result.files else None,
                                  status=agent_status)
    if result.extra.get("fix_requested"):
        # Düzeltmeyi üstlenecek ajan (QA testleri kalınca geliştirici) kartta 'BUG_FIX' görünsün
        fix_rec = run.steps[run.cursor + 1] if run.cursor + 1 < len(run.steps) else None
        if fix_rec is not None and fix_rec.kind == "fix":
            await hub.set_agent_status(fix_rec.role, "BUG_FIX", what_doing=tx("Düzeltme bekliyor: #{n} {title}", n=record.order, title=ctx.title))

    record.status = "FAILED" if result.status == "FAILED" else "DONE"     # G1: başarısız adım kayıtta da FAILED görünür (koşu sürer)
    record.finished_at = datetime.now(timezone.utc).isoformat()
    record.summary = result.summary
    record.action = result.action
    run.touch()

    last_order = max(o for o in run.orders if o <= 10) if any(o <= 10 for o in run.orders) else record.order
    issue_status = "IN_PROGRESS" if result.extra.get("fix_requested") else "DONE"
    if run.mode == "sprint" and result.status == "FAILED" and not result.extra.get("fix_requested") and record.kind in ("task", "fix"):
        issue_status = "IN_PROGRESS"   # sprint kapanışı FIX_LIMIT ile taşır; Jira'da DONE görünmez (A3)
    if record.kind == "rescope":
        issue_status = "BACKLOG"
    if record.kind not in ("plan", "close", "meeting", "review"):
        await hub.update_jira_issue(record.issue_id, {
            "status": issue_status, "agent_id": handler.agent_id,
            "audit_action": f"STEP_DONE_{result.action}", "audit_notes": result.summary[:280],
            "files_affected": written,
        })
        if record.kind in ("task", "fix"):
            kanban_state = "DEVELOPMENT" if result.extra.get("fix_requested") else ("QA_TESTING" if result.status != "FAILED" else "DEVELOPMENT")
        else:
            kanban_state = "RELEASED" if record.order >= max(last_order, 8) else "QA_TESTING"
        await hub.update_task(
            task_id=record.issue_id,
            new_state=kanban_state,
            title=ctx.title, assignee=handler.agent_id, priority=ctx.issue.get("priority", "P0"),
            details=tx("Tamamlandı: {title}", title=ctx.title) if issue_status == "DONE" else tx("Düzeltme bekliyor: {title}", title=ctx.title),
        )

    # --- Backlog genişletme (mimari adımı) ve UAT iyileştirme turu (PO adımı) ---
    if run.mode == "sprint" and record.kind == "phase" and record.order == 1:
        result.extra["intake_created"] = await expand_intake(hub, run, record, payload)
    if record.kind in ("phase", "structure") and record.order == 2:
        inserted += await expand_backlog(hub, run, record, payload)
    if record.kind == "rescope":
        await _apply_rescope(hub, run, record, payload)
    if record.kind == "task" and (record.work_type == "DESIGN" or str(ctx.issue.get("work_type") or "") == "DESIGN") and isinstance(payload.get("design"), dict):
        src_url = str(payload["design"].get("source_url") or "").strip()
        if src_url:
            await hub.update_settings({"claude_design_url": src_url})        # geçerli bir claude.ai bağlantısıysa kaydolur (update_settings süzer)
            if hub.get_settings().get("claude_design_url") == src_url:
                result.extra["claude_design_url"] = src_url
    if record.kind == "task" and str(ctx.issue.get("work_type") or "") == "DESIGN" and result.status != "FAILED" and isinstance(payload.get("design"), dict):
        result.extra["design_screen_tasks"] = await expand_design_screens(hub, ctx.issue, payload["design"])      # tasarımdaki her ekran için frontend görevi
    if record.kind == "task" and (record.work_type == "DECISION_PLAN" or str(ctx.issue.get("work_type") or "") == "DECISION_PLAN") and result.status != "FAILED":
        inserted += await expand_decision_plan(hub, run, record, payload)
    if record.kind == "phase" and record.order == 9 and run.mode == "sprint" and record.sprint and Q.strict(hub):
        async def _create(tasks):
            await _create_task_issues(hub, run, backlog_for(hub, tasks, 50),
                                      parent_id=record.issue_id, origin="PO", issue_type="FEATURE")
        await Q.apply_po_criteria(hub, run, record, payload, result, ctx.project_dir, _create)
    elif record.kind == "phase" and record.order == 9 and result.status == "FAILED":
        inserted += await expand_improvements(hub, run, record, payload)
    if record.kind == "phase" and record.order == 9 and result.status == "FAILED":
        # PO UAT'yi reddetti (kendi kararı ya da sunucunun kanıt denetimi): kabul edilmeyen teslim Jira'da DONE kalamaz ve yönetici onayında DONE'a çevrilemez
        issue_status = "IN_PROGRESS"
        record.action, record.summary = result.action, result.summary
        await hub.update_jira_issue(record.issue_id, {"status": "IN_PROGRESS", "audit_action": "UAT_REJECTED", "audit_notes": result.summary[:280]})
        await hub.update_task(task_id=record.issue_id, new_state="DEVELOPMENT", title=ctx.title, assignee=handler.agent_id,
                              priority=ctx.issue.get("priority", "P0"), details=tx("UAT reddedildi: {title}", title=ctx.title))
    if record.kind == "review":
        async def _create_review(tasks):
            await _create_task_issues(hub, run, backlog_for(hub, tasks, 50), parent_id=record.issue_id, origin="ARCHITECT", issue_type="TASK")
        result.extra["review_findings"] = await Q.expand_review_findings(hub, run, record, payload, _create_review)
    result.extra["inserted_steps"] = inserted
    if inserted:
        hub.mark_dirty()
    if run.mode == "sprint":
        # Dinamik tasarım işi: arayüz işi belirdiği anda (bu adımın sonunda) tasarım yoksa Jira'ya DESIGN görevi düşer; yönetici "Önce yap" ile hemen çalıştırabilir
        try:
            from . import sprint_flow as _SPF
            design = await _SPF.ensure_design_task(hub)
            if design:
                result.extra["design_task"] = design["issue_id"]
            from . import hierarchy as _H
            await _H.link_recent_orphans(hub)               # yeni oluşan bağsız işler en uygun hikâye/epiğe bağlanır
        except Exception:                                  # tasarım görevi açılamaması adımı düşürmez
            pass

    if run.mode == "sprint" and record.sprint:
        failed_step = result.status == "FAILED" or bool(record.verification and record.verification.get("status") == "FAILED")
        progress = not failed_step and not result.extra.get("fix_requested")
        blocked_reason = await DRV.enforce_budgets(hub, run, record, progress=progress, failed=failed_step)
        if blocked_reason:
            result.extra["blocked"] = blocked_reason
    decision = should_wait(hub, run, handler, result)
    if decision == "NOTE":
        info = {**_step_info(hub, run, record, handler, result, ctx), "critical": handler.critical}
        await hub.record_task_audit(
            record.issue_id, handler.agent_id, "HAND_RAISED",
            notes=tx("Adım #{n} el kaldırdı ('not al ve devam et' modu): {summary}", n=record.order, summary=result.summary[:200]),
        )
        await hub.raise_hand(info, note=result.summary[:200])
    if decision == "WAIT":
        info = _step_info(hub, run, record, handler, result, ctx)
        token = hub.open_step_approval(info)
        run.approval_token = token
        run.gate_kind = "step"
        run.status = "WAITING_APPROVAL"
        record.status = "WAITING_APPROVAL"
        if issue_status == "DONE" and record.kind not in _NO_ISSUE_KINDS:
            # Teslim bitti ama yönetici onayı bekliyor: Jira'da "In Review" (onayda DONE olur)
            await hub.update_jira_issue(record.issue_id, {"status": "IN_REVIEW", "audit_action": "AWAITING_APPROVAL",
                                                          "audit_notes": tx("Adım #{n} yönetici onayı bekliyor.", n=record.order)})
        await hub.broadcast({"type": "STEP_WAITING_APPROVAL", "step_info": hub.pending_step_approval})
        await publish_run(hub, run)
        return StepOutcome(status="WAITING_APPROVAL", approval_token=token, message=tx("Kullanıcı onayı bekleniyor."), result=result)

    await advance_run(hub, run)
    return StepOutcome(status="RUN_COMPLETE" if run.is_terminal else "NEXT", result=result,
                       message=tx("Koşu tamamlandı.") if run.is_terminal else tx("Sonraki adım: #{n}", n=run.current_step.order))


async def run_server_step(hub, run: PipelineRun) -> StepOutcome:
    """Sunucu tarafında koşan adımlar (5 handshake, 7 gerçek Playwright): şablon çıktısı + finish_step."""
    record = run.current_step
    if record.kind in ("plan", "close"):
        from . import sprint_flow as SPF   # sprint planı / kapanışı: Jira maddesi olmayan sunucu akış adımları
        return await (SPF.run_plan_step if record.kind == "plan" else SPF.run_close_step)(hub, run, record)
    handler = handler_for(hub, record)
    e2e_result = None
    if record.order == 7:
        e2e_result = await run_e2e_step(hub, run, record)
        await hub.add_playwright_report(e2e_result)
    ctx = make_context(hub, run, record, e2e_result=e2e_result)
    await begin_step(hub, run, record, handler, ctx)
    envelope = handler.template_output(ctx)
    return await finish_step(hub, run, envelope)


def detect_run_candidates(project_dir: str) -> List[str]:
    """Projedeki package.json `start` betiklerinden olası çalıştırma komutları (E2E yapılandırması eksikken kullanıcıya öneri)."""
    out: List[str] = []
    base = Path(project_dir)
    try:
        for pkg in [base / "package.json", *sorted(base.glob("apps/*/package.json"))]:
            scripts = (json.loads(pkg.read_text(encoding="utf-8")).get("scripts") or {}) if pkg.is_file() else {}
            if "start" in scripts:
                rel = pkg.parent.relative_to(base).as_posix()
                out.append("npm start" if rel in ("", ".") else f"cd {rel} && npm start")
    except (OSError, ValueError):
        pass
    return out


async def open_fidelity_tasks(hub, report: Dict[str, Any]) -> List[str]:
    """Ekran uyumu denetiminde eşik altı kalan ekranlar için (açık uyum görevi yoksa) "Ekran uyumu" görevi açar ve sprint kuyruğunda öne alır."""
    ordered = sorted([i for i in hub.jira_issues.values() if i.get("design_screen") and not i.get("deleted")], key=lambda x: int(x.get("order", 0) or 0))
    by_sid: Dict[str, Dict[str, Any]] = {}
    for i in ordered:                              # ekranın ilk (asıl) görevi; sonrakiler uyum görevleridir
        by_sid.setdefault(str(i["design_screen"]), i)
    open_redo = {str(i["design_screen"]) for i in ordered if by_sid[str(i["design_screen"])]["id"] != i["id"] and i.get("status") != "DONE"}
    made: List[str] = []
    for row in report.get("screens") or []:
        sid = str(row.get("id") or "")
        src = by_sid.get(sid)
        if row.get("ok") or not src or sid in open_redo:
            continue
        order = max([int(i.get("order", 0) or 0) for i in hub.jira_issues.values()] or [0]) + 1
        iid = f"JIRA-{order}"
        problems = "; ".join(row.get("problems") or [])
        await hub.update_jira_issue(iid, {
            "order": order, "title": tx("Ekran uyumu: {title}", title=str(src.get("title") or "").replace("Ekran: ", "", 1).replace("Ekran uyumu: ", "", 1)),
            "issue_type": "TASK", "status": "BACKLOG", "priority": "P1", "assignee": "FRONTEND_DEV", "kind": "task", "origin": "DESIGNER", "work_type": "FEATURE",
            "task_key": SP.next_key(hub, "T"), "design_screen": sid, "redo_of": src["id"],
            "description": str(src.get("description") or "") + NL + tx("Sunucunun ekran uyumu denetimi sonucu: {problems}", problems=problems),
            "acceptance_criteria": list(src.get("acceptance_criteria") or []), "files_hint": list(src.get("files_hint") or []),
            "audit_action": "TASK_CREATED", "audit_notes": tx("Ekran uyumu denetimi eşik altı kaldı: {problems}", problems=problems)[:280]})
        made.append(iid)
    if made:
        SP.adopt_manual_tasks(hub)
        try:
            from . import sprint_flow as SPF
            for iid in reversed(made):
                await SPF.expedite_issue(hub, iid, "now")
        except Exception:
            pass
    return made


def _commit_files(hub, issue_id: str) -> List[str]:
    """Maddenin commit'lerinde gerçekten değişen dosya yolları (git); commit yoksa boş."""
    import subprocess
    from .proc import hidden
    from .scm import commits_by_issue
    pd = (hub.projects.get(hub.active_project_id) or {}).get("path") or hub.default_project_path
    out: List[str] = []
    for c in commits_by_issue(pd).get(str(issue_id).upper(), []):
        try:
            r = subprocess.run(["git", "show", "--name-only", "--format=", c["commit"]], cwd=pd, capture_output=True, text=True, timeout=20, **hidden())
            out += [x.strip() for x in r.stdout.splitlines() if x.strip()]
        except (OSError, subprocess.SubprocessError):
            continue
    return out


async def reopen_screen_tasks(hub) -> List[str]:
    """Bitmiş ama arayüz kaynağı (tsx/css) teslim etmemiş ekran görevleri için "Ekran uyumu" takip görevi açar ve çalışan sprinte öne alır
    (bitmiş kaydın sprinti/durumu bozulmaz; eski saha hatası: ekran görevi yalnızca sözleşme yazıp mockup'ı uygulamadan kapanıyordu)."""
    from . import jira_plus as JPL
    ui_ext = (".tsx", ".jsx", ".vue", ".svelte", ".css", ".scss")
    firsts: Dict[str, str] = {}
    for i in sorted([x for x in hub.jira_issues.values() if x.get("design_screen") and not x.get("deleted")], key=lambda x: int(x.get("order", 0) or 0)):
        firsts.setdefault(str(i["design_screen"]), i["id"])
    redone = {fid for sid, fid in firsts.items() if any(str(x.get("design_screen")) == sid and x["id"] != fid and not x.get("deleted") for x in hub.jira_issues.values())}
    made: List[str] = []
    for src in sorted([i for i in hub.jira_issues.values() if i.get("design_screen") and i["id"] in firsts.values() and not i.get("deleted")], key=lambda x: int(x.get("order", 0) or 0)):
        if src.get("status") != "DONE" or src["id"] in redone:
            continue
        if any(str(a).lower().endswith(ui_ext) for a in _commit_files(hub, src["id"])):      # gerçekten değişen dosyalar (aynı içeriği yeniden yazmak değişiklik sayılmaz)
            continue
        order = max([int(i.get("order", 0) or 0) for i in hub.jira_issues.values()] or [0]) + 1
        iid = f"JIRA-{order}"
        await hub.update_jira_issue(iid, {
            "order": order, "title": tx("Ekran uyumu: {title}", title=str(src.get("title") or "").replace("Ekran: ", "", 1)), "issue_type": "TASK", "status": "BACKLOG",
            "priority": "P1", "assignee": "FRONTEND_DEV", "kind": "task", "origin": "DESIGNER", "work_type": "FEATURE", "task_key": SP.next_key(hub, "T"),
            "design_screen": src.get("design_screen"), "redo_of": src["id"], "description": str(src.get("description") or ""),
            "acceptance_criteria": list(src.get("acceptance_criteria") or []), "files_hint": list(src.get("files_hint") or []),
            "audit_action": "TASK_CREATED", "audit_notes": tx("{id} yalnızca ekran sözleşmesi yazıp mockup'ı uygulamadı; uyum görevi açıldı.", id=src["id"])})
        made.append(iid)
    if made:
        SP.adopt_manual_tasks(hub)
        try:
            from . import sprint_flow as SPF
            for iid in reversed(made):
                await SPF.expedite_issue(hub, iid, "now")
        except Exception:
            pass
    return made


async def expand_design_screens(hub, design_issue: Dict[str, Any], design: Dict[str, Any]) -> List[str]:
    """Teslim edilen tasarımdaki her ekran (`design.screens[]`) için bir FRONTEND_DEV görevi açar: mockup'a uygun uygulama + ekran sözleşmesi.
    Aynı ekran için görev varsa tekrar açılmaz. Görevler tasarım işine bağlıdır (onaylı tasarımdan önce başlamaz); akış haritası (`flows.md`) görev açıklamasına girer."""
    existing = {str(i.get("design_screen") or "") for i in hub.jira_issues.values() if i.get("design_screen")}
    flows = [f for f in (design.get("flows") or []) if isinstance(f, dict)]
    made: List[str] = []
    for sc in design.get("screens") or []:
        if not isinstance(sc, dict):
            continue
        sid = str(sc.get("id") or "").strip()
        if not sid or sid in existing:
            continue
        title, route, mock = str(sc.get("title") or sid), str(sc.get("route") or ""), str(sc.get("file") or f"<docs>/design/screens/{sid}.html")
        in_flows = [str(f.get("title") or f.get("id")) for f in flows if sid in [str(x) for x in (f.get("steps") or [])]]
        order = max([int(i.get("order", 0) or 0) for i in hub.jira_issues.values()] or [0]) + 1
        iid = f"JIRA-{order}"
        await hub.update_jira_issue(iid, {
            "order": order, "title": tx("Ekran: {title} ({route})", title=title, route=route or sid), "issue_type": "TASK", "status": "BACKLOG", "priority": "P1",
            "assignee": "FRONTEND_DEV", "kind": "task", "origin": "DESIGNER", "work_type": "FEATURE", "task_key": SP.next_key(hub, "T"), "design_screen": sid,
            "description": tx("Onaylı tasarımdaki '{title}' ekranını ({mock}) uygulamada gerçekle: tasarım sistemine ve mockup'a birebir uy; boş, hata, yükleniyor ve dolu durumlarını da yap.",
                              title=title, mock=mock) + ((NL + tx("Akışlar: {flows}", flows=", ".join(in_flows))) if in_flows else ""),
            "acceptance_criteria": [tx("Ekran '{route}' adresinde açılır ve mockup'taki yerleşim, renk ve bileşenlerle eşleşir", route=route or sid),
                                    tx("Boş, hata, yükleniyor ve dolu durumları gösterilir"), tx("Ekran sözleşmesi (screens[]) bildirilir; çalışan uygulamada ekran görüntüsü alınabilir")],
            "files_hint": [mock], "depends_on": [design_issue["id"]], "audit_action": "TASK_CREATED",
            "audit_notes": tx("Tasarım ekranından otomatik açıldı ({id}).", id=design_issue["id"])})
        made.append(iid)
        existing.add(sid)
    if made:
        SP.adopt_manual_tasks(hub)
        try:                    # onaylanan tasarım = uygulama emri: ekran görevleri çalışan sprinte, geçerli adımdan hemen sonra (ilk ekran en önde) alınır
            from . import sprint_flow as SPF
            for iid in reversed(made):
                await SPF.expedite_issue(hub, iid, "now")
        except Exception:
            pass
    return made


async def run_e2e_step(hub, run: PipelineRun, record: StepRecord) -> Dict[str, Any]:
    """
    Adım 7: `verification.run` + `health_url` varsa uygulamayı gerçekten başlatır, sağlık adresini bekler,
    Playwright'ı o uygulamaya karşı koşar ve süreci kapatır. Yoksa `e2e_target_url` ayarına (o da yoksa panoya) düşer.
    """
    from urllib.parse import urlsplit
    from .playwright_tester import run_playwright_e2e_tests
    from .app_runner import start_app

    settings = hub.get_settings()
    ver = settings.get("verification") or {}
    run_cmd, health = ver.get("run"), ver.get("health_url") or ver.get("app_url")
    scenario = tx("Jira Task #{n} - Canlı Tarayıcı Doğrulama ve Ekran Yakalama", n=record.order)
    launch_info: Dict[str, Any] = {"launched": False}
    app = None
    explicit_target = str(settings.get("e2e_target_url") or "").strip()
    can_launch = bool(run_cmd and health and settings.get("auto_verify", True))
    if not can_launch and not explicit_target:
        # G1: hedef uygulama yoksa E2E panoyu (ya da başka bir şeyi) test edip "geçti" demez: FAILED (APP_NOT_CONFIGURED)
        why = (tx("auto_verify kapalı: uygulama sunucu tarafından başlatılamaz") if (run_cmd and health) else
               tx("verification.run ve health_url tanımlı değil (mimar/DevOps teslimi ya da model penceresi 0c)"))
        hints = detect_run_candidates(project_dir_for(hub, run))
        if hints and not (run_cmd and health):
            why += tx(". Projede bulunan olası çalıştırma komutları: {hints} (model penceresi 0c → Doğrulama: run + health_url)", hints='; '.join(hints[:3]))
        await hub.record_event(
            trace_id=run.run_id, from_agent="E2E_TESTER", to_agent="DEVOPS", action="APP_NOT_CONFIGURED", status="FAILED",
            payload={"order": record.order, "reason": why},
            friendly_dialogue=tx("E2E koşamadım: {why}. Hedef uygulama tanımlanmadan 'geçti' demem.", why=why),
        )
        return {
            "status": "FAILED", "scenario": scenario, "target_url": None, "executed_at": datetime.now(timezone.utc).isoformat(),
            "total_steps": 3, "passed_steps": 0, "screenshots": [], "logs": [f"[!] {why}"], "verdict": "APP_NOT_CONFIGURED",
            "engine_error": why, "simulated": True,
            "notes_for_team_lead": tx("Çalıştırma komutu ve sağlık adresi tanımlanmalı (verification.run / health_url); E2E hedefsiz koşmaz."),
            "app_launch": launch_info,
        }
    target = explicit_target or f"http://127.0.0.1:{os.environ.get('OBSERVER_PORT', '8099')}"
    if can_launch:
        await hub.record_event(
            trace_id=run.run_id, from_agent="DEVOPS", to_agent="E2E_TESTER", action="APP_STARTING", status="IN_PROGRESS",
            payload={"order": 7, "run": run_cmd, "health_url": health},
            friendly_dialogue=tx("Uygulamayı başlatıyorum: `{run}` — sağlık adresi {health}", run=run_cmd, health=health),
        )
        launch = await start_app(project_dir_for(hub, run), run_cmd, health)
        launch_info = {"launched": launch["ok"], "run": run_cmd, "health_url": health, "error": launch.get("error"),
                       "health_status": launch.get("status"), "log_tail": (launch.get("log") or "")[-1500:]}
        if launch["ok"]:
            app = launch["app"]
            parts = urlsplit(ver.get("app_url") or health)
            target = ver.get("app_url") or f"{parts.scheme}://{parts.netloc}/"
        else:
            await hub.record_event(
                trace_id=run.run_id, from_agent="E2E_TESTER", to_agent="DEVOPS", action="APP_START_FAILED", status="FAILED",
                payload={"order": 7, "error": launch.get("error"), "log_tail": (launch.get("log") or "")[-800:]},
                friendly_dialogue=tx("Uygulama ayağa kalkmadı: {error}", error=str(launch.get('error'))[:140]),
            )
            return {
                "status": "FAILED", "scenario": scenario, "target_url": health, "executed_at": datetime.now(timezone.utc).isoformat(),
                "total_steps": 3, "passed_steps": 0, "screenshots": [], "logs": [f"[!] {launch.get('error')}", (launch.get("log") or "")[-1500:]],
                "verdict": "APP_START_FAILED", "engine_error": launch.get("error"), "simulated": True,
                "notes_for_team_lead": tx("Uygulama başlatılamadı; DevOps çalıştırma komutunu ve sağlık ucunu kontrol etmeli."),
                "app_launch": launch_info,
            }
    client_app = None
    client_run, client_url = ver.get("client_run"), ver.get("client_url")
    if client_run and client_url and settings.get("auto_verify", True):
        # Web arayüzü ayrı bir süreçse (örn. Vite): backend ayaktayken arayüz de başlatılır ve ekran görüntüleri arayüz adresine alınır
        await hub.record_event(
            trace_id=run.run_id, from_agent="DEVOPS", to_agent="E2E_TESTER", action="CLIENT_STARTING", status="IN_PROGRESS",
            payload={"order": 7, "run": client_run, "client_url": client_url},
            friendly_dialogue=tx("Web arayüzünü başlatıyorum: `{run}` — adres {url}", run=client_run, url=client_url))
        cl = await start_app(project_dir_for(hub, run), client_run, client_url)
        launch_info["client"] = {"launched": cl["ok"], "run": client_run, "client_url": client_url, "error": cl.get("error")}
        if cl["ok"]:
            client_app, target = cl["app"], client_url
    try:
        ui_probe: Optional[int] = None
        if app is not None and not ver.get("app_url") and client_app is None:
            # G1: uygulamanın kökünde arayüz var mı? (API-only iskelette kök 404 döner; bu bir kusur değil, UI duman testi uygulanamaz)
            from .app_runner import _probe
            ui_probe = await asyncio.get_running_loop().run_in_executor(None, _probe, target)
        if ui_probe == 404:
            e2e_result = {
                "status": "SKIPPED", "scenario": scenario, "target_url": target, "executed_at": datetime.now(timezone.utc).isoformat(),
                "total_steps": 0, "passed_steps": 0, "screenshots": [], "verdict": "NO_UI", "engine_error": None, "simulated": True,
                "logs": [tx("[i] {target} kökü 404 döndü, sağlık adresi sağlıklı: arayüz yok (API-only). Genel UI duman testi uygulanamaz.", target=target)],
                "notes_for_team_lead": tx("Uygulamanın kökünde arayüz yok; API kanıtı QA testleridir. Arayüz varsa verification.app_url verin ya da QA e2e/scenarios yazsın."),
            }
        else:
            e2e_result = await run_playwright_e2e_tests(target_url=target, test_scenario=scenario,
                                                        project_dir=project_dir_for(hub, run), project_id=run.project_id)
        from .e2e_scenarios import run_scenarios      # QA'nın kabul kriterlerinden yazdığı senaryolar (varsa) aynı çalışan uygulamaya karşı koşar
        sc = await run_scenarios(project_dir_for(hub, run), target, project_id=run.project_id)
        if sc["status"] != "NONE":
            e2e_result["scenarios"] = sc
            e2e_result["screenshots"] = list(e2e_result.get("screenshots") or []) + list(sc.get("screenshots") or [])
            if sc["status"] == "FAILED":
                e2e_result["status"] = "FAILED"
                e2e_result["verdict"] = "SCENARIO_FAILED" if e2e_result.get("verdict") in (None, "NO_UI", "VERIFIED_FOR_PRODUCTION") else e2e_result.get("verdict")
            elif e2e_result.get("status") == "SKIPPED" and e2e_result.get("verdict") == "NO_UI":
                e2e_result["status"], e2e_result["verdict"] = "PASSED", "SCENARIOS_PASSED"     # UI yok ama QA senaryoları geçti: gerçek kanıt
            if record.sprint:
                SP.ensure_state(hub).setdefault("e2e_evidence", {})[str(record.sprint)] = sc["ac_evidence"]
        try:
            perf = None
            if health and app is not None and TST.has_ready(hub, "performance"):
                cfg = TST.config(hub)
                perf = await asyncio.to_thread(TST.perf_smoke, health, cfg["perf_samples"], cfg["perf_p95_ms"])
            await TST.record_run(hub, sprint=record.sprint, source="E2E_TESTER", project_dir=project_dir_for(hub, run),
                                 scenarios=(sc["scenarios"] if sc["status"] != "NONE" else []), perf=perf)
        except Exception:                                  # test yönetimi E2E sonucunu bozmasın
            pass
    finally:
        if client_app is not None:
            await client_app.stop()
        if app is not None:
            await app.stop()
    e2e_result["app_launch"] = launch_info
    return e2e_result


# ---------------------------------------------------------------------------
# Tam yaşam döngüsü: doğrulama, düzeltme turu, SCM commit, backlog ve UAT iyileştirme
# ---------------------------------------------------------------------------
VERIFY_HEARTBEAT_S = float(os.environ.get("VERIFY_HEARTBEAT_S", "20"))


async def _heartbeat(run: PipelineRun, interval_s: float) -> None:
    """Doğrulama/kurulum sürerken koşuya düzenli dokunur: süpürücü uzun bir test koşusunu 'terk edilmiş' saymaz."""
    try:
        while True:
            await asyncio.sleep(interval_s)
            run.touch()
    except asyncio.CancelledError:
        pass


def python_isolation(hub) -> str:
    """G1: proje bağımlılıkları nereye kurulur? 'venv' (projenin .fs-workspace/venv sanal ortamı, varsayılan) | 'host' (FS-SC yorumlayıcısı)."""
    v = (hub.get_settings() or {}).get("python_isolation")
    return v if v in ("venv", "host") else "venv"


def verification_commands(hub, project_dir: str) -> Dict[str, str]:
    """Kayıtlı (mimar/DevOps/kullanıcı) komutlar + proje dosyalarından çıkarsananlar (kayıtlı olan kazanır).
    Kayıtlı komut kökte koşacak biçimdeyse ama manifestler `apps/<uygulama>` altındaysa sunucunun çıkarsadığı `cd`'li komut kullanılır."""
    return effective_commands(project_dir, python_isolation(hub), hub.get_settings().get("verification") or {}, LAY.app_roots(LAY.layout_of(hub)))


def _fix_count(run: PipelineRun, issue_id: str, sprint: Optional[int] = None) -> int:
    """Aynı maddenin düzeltme turu sayısı; sprint kipinde yalnızca aynı sprintin turları sayılır (taşınan iş yeni hak kazanır)."""
    return sum(1 for s in run.steps if s.issue_id == issue_id and s.kind == "fix" and s.sprint == sprint)


FULL_VERIFY_EVERY = 5      # artımlı doğrulamada her bu kadar adımda bir tam paket (regresyon ağı)


def use_incremental_verify(hub, run: PipelineRun, record: StepRecord, written: List[str]) -> bool:
    """Artımlı (yalnızca değişen dosyaların testleri) doğrulama kullanılsın mı? Faz adımları, ilk doğrulama ve her 5. adım tam paket koşar."""
    if str(hub.get_settings().get("verify_scope", "incremental")) != "incremental":
        return False
    if record.kind not in ("task", "fix") or not written:
        return False
    prior = [s for s in run.steps if s is not record and s.verification and (s.verification or {}).get("status") == "PASSED"]
    if not prior:
        return False                                                       # ilk geçen doğrulama tam paket olsun (taban çizgisi)
    streak = 0
    for s in reversed(prior):
        if (s.verification or {}).get("scope") == "incremental":
            streak += 1
        else:
            break
    return streak < FULL_VERIFY_EVERY - 1


async def verify_step(hub, run: PipelineRun, record: StepRecord, handler: StepHandler, ctx: StepContext,
                      written: List[str]) -> Dict[str, Any]:
    """Teslim sonrası doğrulamayı koşar, kaydı ve panoyu günceller."""
    commands = verification_commands(hub, ctx.project_dir)
    changed_only = use_incremental_verify(hub, run, record, written)
    light = bool(hub.get_settings().get("verify_light", True))          # artımlı adımlarda build yok (her 5. adımda tam doğrulama koşar)
    manifests = {"requirements.txt", "pyproject.toml", "package.json", "composer.json", "go.mod"}
    touched_manifest = any(os.path.basename(p) in manifests for p in written)
    do_install = bool(commands.get("install")) and (not run.install_done or touched_manifest)
    await hub.set_agent_status("QA", "WORKING", what_doing=tx("Doğrulama koşuyor: #{n} {title}", n=record.order, title=ctx.title))
    await hub.broadcast({"type": "VERIFICATION_STARTED", "run_id": run.run_id, "order": record.order, "issue_id": record.issue_id,
                         "commands": planned_commands(ctx.project_dir, commands, do_install, changed_only, written, light),
                         "scope": "incremental" if changed_only else "full", "files": written})
    sb = G.sandbox(hub)
    hb = asyncio.create_task(_heartbeat(run, VERIFY_HEARTBEAT_S))     # G3: uzun doğrulama kalp atışını aşmasın (koşu ABANDONED olmaz)
    try:
        verification = await run_verification(ctx.project_dir, commands, files_written=written, do_install=do_install,
                                              sandbox=sb if sb["mode"] == "container" else None,
                                              command_filter=(lambda c: G.command_allowed(hub, c)) if sb["command_policy"] == "allowlist" else None,
                                              isolation=python_isolation(hub), log_dir=os.path.join(ctx.project_dir, VERIFY_DIR),
                                              tag=f"{run.run_id[-6:]}-{record.order}-f{record.fix_round}", changed_only=changed_only, light=light)
    finally:
        hb.cancel()
    for r in verification.get("results", []):
        # Eşleştirme tuzağı: verify.py çıktısı proje dilinde olabilir; dilden bağımsız ölçüt = SKIPPED + komut izin listesi dışında
        if r.get("status") == "SKIPPED" and (str(r.get("output", "")).startswith("İzin listesi dışı") or not G.command_allowed(hub, str(r.get("cmd") or ""))[0]):
            await _ask_allow_command(hub, run, record, r["name"], r["cmd"], r["output"])
    if verification.get("ran_install"):
        run.install_done = True
    record.verification = public_summary(verification)
    passed = verification.get("status") == "PASSED"
    skipped = verification.get("status") == "SKIPPED"
    action = "VERIFICATION_PASSED" if passed else ("VERIFICATION_SKIPPED" if skipped else "VERIFICATION_FAILED")
    await hub.record_event(
        trace_id=run.run_id, from_agent="QA", to_agent=handler.agent_id, action=action,
        status="SUCCESS" if passed or skipped else "FAILED",
        payload={"order": record.order, "task_id": record.issue_id, "kind": record.kind, "fix_round": record.fix_round,
                 "verification": record.verification},
        current_file=written[0] if written else None, tokens_used=0,
        friendly_dialogue=(
            tx("Doğrulama geçti: {summary}", summary=verification.get('summary')) if passed else
            (tx("Koşacak test/build komutu bulunamadı; yalnızca sözdizimi denetlendi.") if skipped else
             tx("Doğrulama kaldı ({step}). Çıktıyı inceleyip düzeltir misin?", step=verification.get('failed_step')))
        ),
        what_doing=tx("Test/build komutlarını koşturdu"), what_next=tx("Geçtiyse SCM commit, kaldıysa düzeltme turu"),
    )
    await hub.record_task_audit(record.issue_id, "QA", action,
                                notes=(verification.get("summary") or "")[:280] + (("\n" + failure_excerpt(verification, 900)) if not passed and not skipped else ""),
                                files_affected=written)
    await hub.broadcast({"type": "VERIFICATION_DONE", "run_id": run.run_id, "order": record.order, "issue_id": record.issue_id,
                         "verification": record.verification})
    await hub.set_agent_status("QA", "COMPLETED" if passed or skipped else "ERROR")
    return verification


async def request_fix(hub, run: PipelineRun, record: StepRecord, handler: StepHandler, ctx: StepContext,
                      verification: Dict[str, Any]) -> Optional[StepRecord]:
    """Doğrulama başarısızsa aynı Jira maddesi için bir düzeltme adımı ekler (tur sınırı dolmadıysa)."""
    max_rounds = int(hub.get_settings().get("max_fix_rounds", 2) or 0)
    if record.sprint and (hub.jira_issues.get(record.issue_id) or {}).get("token_limit_sprint") == record.sprint:
        return None      # görev kendi token sınırını aştı: durdurulur, sprint kapanışında yeniden kapsamlanmak üzere taşınır
    if run.mode == "sprint" and record.sprint and record.error_sig:
        prev = next((s for s in reversed(run.steps[:run.cursor]) if s.issue_id == record.issue_id and s.sprint == record.sprint and s.error_sig), None)
        if prev is not None and prev.error_sig == record.error_sig:
            # §12 madde 6: aynı hata imzası art arda iki turda görüldü → kalan turlar harcanmaz, iş mimara döner (yeniden kapsamlama)
            await hub.record_task_audit(record.issue_id, "SYSTEM", "SAME_ERROR_LOOP",
                                        notes=tx("Aynı hata imzası ({sig}) art arda iki turda görüldü; kalan düzeltme turları harcanmadı, iş yeniden kapsamlanmak üzere taşınacak.", sig=record.error_sig))
            await hub.update_jira_issue(record.issue_id, {"fix_limit_sprint": record.sprint, "audit_action": "CARRY_CANDIDATE",
                                                          "audit_notes": tx("Sprint {n}: döngü kırıcı; sprint kapanışında FIX_LIMIT ile taşınacak.", n=record.sprint)})
            return None
    done_rounds = _fix_count(run, record.issue_id, record.sprint)
    if done_rounds >= max_rounds:
        await hub.record_task_audit(record.issue_id, "SYSTEM", "FIX_LIMIT_REACHED",
                                    notes=tx("{n} düzeltme turu sonrasında doğrulama hâlâ başarısız; görev FAILED olarak işaretlendi.", n=done_rounds))
        if record.sprint:
            await hub.update_jira_issue(record.issue_id, {"fix_limit_sprint": record.sprint, "audit_action": "CARRY_CANDIDATE",
                                                          "audit_notes": tx("Sprint {n}: düzeltme limiti doldu; sprint kapanışında FIX_LIMIT ile taşınacak.", n=record.sprint)})
        await hub.set_agent_status(handler.agent_id, "ERROR")
        return None
    role = handler.agent_id
    if role not in ("BACKEND_DEV", "FRONTEND_DEV", "DEVOPS"):
        # QA/doküman adımlarının testleri kalınca düzeltme geliştiriciye gider
        lay = LAY.layout_of(hub)
        fe_dirs = ("frontend/", "web/", "client/", "app/") + (tuple(f"{lay['apps_dir']}/{v}/" for k, v in lay["roles"].items() if k != "backend") if LAY.is_apps(lay) else ())
        fe = any(p.startswith(fe_dirs) for p in ctx.run.files_written())
        be = any(not p.startswith(fe_dirs + (ctx.docs_root + "/", "tests/")) for p in ctx.run.files_written())
        role = "FRONTEND_DEV" if fe and not be else "BACKEND_DEV"
    fix = StepRecord(order=record.order, issue_id=record.issue_id, role=role, kind="fix", fix_round=done_rounds + 1,
                     title=ctx.title, round=record.round, work_type=record.work_type, sprint=record.sprint)
    run.insert_after_cursor([fix])
    run.fix_rounds_total += 1
    await hub.update_jira_issue(record.issue_id, {
        "status": "IN_PROGRESS", "agent_id": "QA", "audit_action": "FIX_REQUESTED",
        "audit_notes": tx("Düzeltme turu {n}/{max} → {role}: {summary}", n=fix.fix_round, max=max_rounds, role=role, summary=verification.get('summary', '')[:200]),
    })
    await hub.record_event(
        trace_id=run.run_id, from_agent="QA", to_agent=role, action="REPORT_BUG", status="FAILED",
        payload={"order": record.order, "task_id": record.issue_id, "fix_round": fix.fix_round, "failed_step": verification.get("failed_step"),
                 "excerpt": failure_excerpt(verification, 1200)},
        current_file=(ctx.run.files_written() or [None])[-1],
        friendly_dialogue=tx("Testler/build kaldı ({step}). Düzeltme turu {n} senin, kök nedeni çöz lütfen.", step=verification.get('failed_step'), n=fix.fix_round),
    )
    await hub.set_agent_status(role, "BUG_FIX", what_doing=tx("Düzeltme bekliyor: #{n} {title}", n=record.order, title=ctx.title))
    return fix


async def commit_step(hub, run: PipelineRun, record: StepRecord, handler: StepHandler, ctx: StepContext) -> Optional[str]:
    """SCM ajanı: teslimi git'e commit'ler; sonucu kayda, denetim izine ve panoya yazar."""
    message = SCM.commit_message(record.kind, record.issue_id, ctx.title, record.fix_round)
    res = await SCM.commit_all(ctx.project_dir, message)
    record.commit_status = res["status"]
    record.commit_note = str(res.get("reason") or "")[:300]
    if res["status"] == "SECRET":
        await hub.record_event(trace_id=run.run_id, from_agent="SCM", to_agent=handler.agent_id, action="COMMIT_BLOCKED_SECRET", status="FAILED",
                               payload={"order": record.order, "task_id": record.issue_id, "findings": res.get("findings", [])[:5]},
                               friendly_dialogue=tx("Commit durduruldu: sır bulgusu ({note}). Değeri ortam değişkenine taşıyıp tekrar gönder.", note=record.commit_note[:140]))
        await hub.record_task_audit(record.issue_id, "SCM", "COMMIT_BLOCKED_SECRET", notes=record.commit_note)
        return None
    if res["status"] == "COMMITTED":
        record.commit = res.get("hash")
        await hub.record_event(
            trace_id=run.run_id, from_agent="SCM", to_agent=handler.agent_id, action="COMMITTED", status="SUCCESS",
            payload={"order": record.order, "task_id": record.issue_id, "hash": res.get("hash"), "branch": res.get("branch"), "message": message,
                     "created_repo": res.get("created_repo")},
            current_file=".git", tokens_used=0,
            friendly_dialogue=tx("Commit atıldı: {hash} · {message}", hash=res.get('hash'), message=message[:90]) + (tx(" (yeni depo açıldı)") if res.get("created_repo") else ""),
            what_doing=tx("Değişiklikleri sürümledi"), what_next=tx("Sonraki teslimi bekliyor"),
        )
        await hub.record_task_audit(record.issue_id, "SCM", "COMMITTED", notes=f"{res.get('hash')} {message}", files_affected=record.artifacts)
        return res.get("hash")
    if res["status"] in ("SKIPPED", "FAILED"):
        await hub.record_task_audit(record.issue_id, "SCM", f"COMMIT_{res['status']}", notes=str(res.get("reason") or "")[:280])
    return None


def _next_jira_order(hub) -> int:
    orders = [int(i.get("order", 0) or 0) for i in hub.jira_issues.values()]
    return (max(orders) if orders else 0) + 1


def _norm_title(title: Any) -> str:
    """Başlık karşılaştırma anahtarı: küçük harf, boşluklar tek, 'sprint N' → 'sprint #' (her sprintte yeniden açılan aynı bulgu aynı anahtara düşer)."""
    import re as _re
    return _re.sub(r"(?i)sprint\s*\d+", "sprint #", " ".join(str(title or "").lower().split()))


def _open_duplicate(hub, task: Dict[str, Any], origin: str) -> Optional[Dict[str, Any]]:
    """Aynı (normalize) başlıkla AÇIK bir iş varsa onu; ya da aynı başlıkla ikiden fazla kez BİTMİŞ iş varsa (kapanıp yeniden açılan bulgu: sonsuz döngü işareti) en yenisini döner.
    Yönetici, tasarımcı ve elle açılan işler muaftır."""
    if str(origin or "").upper() in ("MANAGER", "DESIGNER", "HUMAN"):
        return None
    key = _norm_title(task.get("title"))
    if len(key) < 12:
        return None
    same = [i for i in hub.jira_issues.values() if not i.get("deleted") and str(i.get("kind", "")).lower() == "task" and _norm_title(i.get("title")) == key]
    open_ones = [i for i in same if i.get("status") != "DONE"]
    if open_ones:
        return open_ones[0]
    done = [i for i in same if i.get("status") == "DONE"]
    if len(done) >= 2:
        return sorted(done, key=lambda x: int(x.get("order", 0) or 0))[-1]
    return None


def _done_duplicate(hub, task: Dict[str, Any], origin: str) -> Optional[Dict[str, Any]]:
    """Mimar/karar bölümü yeni görev önerir ama aynı başlıklı iş zaten DONE ise o kaydı döner (benzerlik >= 0.88; yalnızca TASK, silinmemiş, ARCHITECT/DECISION kaynağı)."""
    if origin not in ("ARCHITECT", "DECISION") or str(task.get("work_type") or "") in ("DESIGN", "BUG"):
        return None
    import difflib
    title = " ".join(str(task.get("title") or "").lower().split())
    if len(title) < 12:
        return None
    for i in hub.jira_issues.values():
        if i.get("deleted") or i.get("status") != "DONE" or i.get("issue_type") != "TASK" or i.get("kind") != "task":
            continue
        other = " ".join(str(i.get("title") or "").lower().split())
        if other and difflib.SequenceMatcher(None, title, other).ratio() >= 0.88:
            return i
    return None


async def _create_task_issues(hub, run: PipelineRun, tasks: List[Dict[str, Any]], parent_id: str, origin: str,
                              issue_type: str = "TASK") -> List[StepRecord]:
    """Backlog görevlerini Jira'ya yazar ve koşuya eklenecek adım kayıtlarını üretir."""
    from . import goals as GL
    if GL.blocks_new_work(hub, origin):             # açık yönetici hedefi varken mimar/PO/karar bölümü yeni iş açmaz
        await hub.record_task_audit(parent_id, origin, "GOAL_BLOCKED_NEW_WORK",
                                    notes=tx("Açık hedef varken {n} yeni görev açılmadı: {titles}", n=len(tasks), titles="; ".join(str(t.get("title")) for t in tasks)[:200]))
        return []
    records: List[StepRecord] = []
    key_to_issue: Dict[str, str] = {}
    order = _next_jira_order(hub)
    lay, docs_root = LAY.layout_of(hub), hub_docs_path(hub, "")
    for t in tasks:
        dup = _done_duplicate(hub, t, origin) or _open_duplicate(hub, t, origin)
        if dup:                                      # aynı işin açık ya da bitmiş kaydı var: yeni görev/adım açılmaz (bağımlılıklar mevcut kayda çözülür)
            key_to_issue[t["task_key"]] = dup["id"]
            await hub.record_task_audit(dup["id"], origin, "DUPLICATE_SKIPPED",
                                        notes=tx("Aynı işi tarif eden yeni görev açılmadı: {title}", title=str(t.get("title"))[:160]))
            continue
        issue_id = f"JIRA-{order}"
        deps = [key_to_issue.get(d, d) for d in t.get("depends_on", [])]
        # A3: görev anahtarını LLM değil sunucu verir ve proje genelinde artar (LLM'in numarası yalnızca bağımlılık çözmek içindir)
        task_key = SP.next_key(hub, "UAT" if origin == "PO" else "T")
        story = hub.jira_issues.get(t.get("story_ref") or "")
        parent = story["id"] if story and str(story.get("kind", "")).lower() == "story" else parent_id
        await hub.update_jira_issue(issue_id, {
            "order": order, "title": t["title"], "description": t.get("description", ""), "issue_type": issue_type,
            "status": "BACKLOG", "priority": t.get("priority", "P1"), "assignee": t["role"],
            "acceptance_criteria": t.get("acceptance_criteria", []), "kind": "task", "task_key": task_key,
            "parent_id": parent, "depends_on": deps, "files_hint": LAY.relocate_hints(lay, t.get("files_hint", []), t["role"], docs_root), "run_id": run.run_id,
            "work_type": t.get("work_type") or ("IMPROVEMENT" if origin == "PO" else "FEATURE"), "ac_refs": t.get("ac_refs", []),
            "origin": "UAT" if origin == "PO" else origin,
            "agent_id": origin, "audit_action": "TASK_CREATED", "audit_notes": tx("{origin} tarafından oluşturuldu ({key})", origin=origin, key=task_key),
        })
        key_to_issue[t["task_key"]] = issue_id
        records.append(StepRecord(order=order, issue_id=issue_id, role=t["role"], kind="task", title=t["title"], round=run.uat_round + 1,
                                  work_type=t.get("work_type") or ""))
        order += 1
    return records


_BUG_PRIORITY = {"CRITICAL": "P0", "HIGH": "P0", "MEDIUM": "P1", "LOW": "P2"}


async def _create_bug_issues(hub, run: PipelineRun, record: StepRecord, bugs: List[Any]) -> List[str]:
    """G1: QA'nın `bugs[]` bulgularını Jira BUG maddesine çevirir (önem → öncelik, origin QA, yeniden üretim/çözüm notu). Aynı başlık tekrar açılmaz."""
    existing = {str(i.get("title") or "").strip().lower() for i in hub.jira_issues.values()}
    tasks: List[Dict[str, Any]] = []
    for b in bugs[:20]:
        if not isinstance(b, dict):
            continue
        issue = str(b.get("issue") or b.get("title") or "").strip()
        if not issue:
            continue
        sev = str(b.get("severity") or "MEDIUM").upper()
        title = f"[QA] {b.get('bug_id') or 'BUG'}: {issue}"[:160]
        if title.strip().lower() in existing:
            continue
        existing.add(title.strip().lower())
        tasks.append({
            "task_key": str(b.get("bug_id") or f"BUG-{len(tasks) + 1}"), "title": title, "role": "BACKEND_DEV", "work_type": "BUG",
            "priority": _BUG_PRIORITY.get(sev, "P1"),
            "description": f"[{sev}] {issue}\n\n" + tx("QA notu / önerilen çözüm: {resolution}", resolution=b.get('resolution') or '-'),
            "acceptance_criteria": [tx("Hata giderilir ve regresyon testi eklenir")], "ac_refs": [], "story_ref": "", "depends_on": [], "files_hint": [],
        })
    if not tasks:
        return []
    recs = await _create_task_issues(hub, run, tasks, parent_id=record.issue_id, origin="QA", issue_type="BUG")
    ids = [r.issue_id for r in recs]
    await hub.record_event(
        trace_id=run.run_id, from_agent="QA", to_agent="SCRUM_MASTER", action="BUGS_FILED",
        status="FAILED" if any(t["priority"] == "P0" for t in tasks) else "IN_PROGRESS",
        payload={"order": record.order, "issues": ids, "titles": [t["title"] for t in tasks]},
        friendly_dialogue=tx("{n} hata maddesi açtım: ", n=len(ids)) + ", ".join(ids),
        what_doing=tx("Bulguları Jira'ya yazdı"), what_next=tx("Hatalar sprint planında öncelik alır"),
    )
    return ids


async def fail_step_without_output(hub, run: PipelineRun, record: StepRecord, errors: List[str]) -> StepOutcome:
    """G1: geçerli çıktı alınamadı ve şablon yedeği kapalı: yer tutucu ÜRETİLMEZ; adım FAILED olur, koşu sonraki adımla sürer
    (sprint kipinde iş kapanışta FIX_LIMIT ile taşınır ve yeniden kapsamlanır)."""
    record.status = "FAILED"
    record.finished_at = datetime.now(timezone.utc).isoformat()
    record.action = "LLM_OUTPUT_FAILED"
    record.summary = tx("Geçerli çıktı alınamadı ({n} deneme); adım FAILED. Son hata: {error}", n=record.attempts, error=str((errors or ['?'])[0])[:200])
    await hub.record_task_audit(record.issue_id, "SYSTEM", "LLM_OUTPUT_FAILED", notes=record.summary[:280])
    if record.kind not in _NO_ISSUE_KINDS:
        updates: Dict[str, Any] = {"status": "IN_PROGRESS", "audit_action": "STEP_FAILED", "audit_notes": record.summary[:280]}
        if run.mode == "sprint" and record.sprint and record.kind in ("task", "fix"):
            updates["fix_limit_sprint"] = record.sprint
        await hub.update_jira_issue(record.issue_id, updates)
    await hub.record_event(
        trace_id=run.run_id, from_agent=record.role, to_agent="SCRUM_MASTER", action="LLM_OUTPUT_FAILED", status="FAILED",
        payload={"order": record.order, "task_id": record.issue_id, "attempts": record.attempts, "errors": list(errors or [])[:5]},
        friendly_dialogue=tx("Adım #{n} için geçerli bir teslim üretilemedi; yer tutucu yazmadım, adımı FAILED bıraktım.", n=record.order),
    )
    await hub.set_agent_status(record.role, "ERROR")
    run.touch()
    await advance_run(hub, run)
    return StepOutcome(status="RUN_COMPLETE" if run.is_terminal else "NEXT",
                       message=tx("Koşu tamamlandı.") if run.is_terminal else tx("Sonraki adım: #{n}", n=run.current_step.order))


async def expand_backlog(hub, run: PipelineRun, record: StepRecord, payload: Dict[str, Any]) -> int:
    """Mimarın backlog'unu Jira görevlerine çevirir; koşu devam ediyorsa görev adımlarını el sıkışma (5) adımından önce ekler."""
    if run.mode == "sprint":
        return await expand_backlog_sprint(hub, run, record, payload)
    settings = hub.get_settings()
    tasks = backlog_for(hub, payload.get("backlog"), int(settings.get("max_backlog_tasks", 40) or 40))
    if not tasks or run.backlog_expanded:
        return 0
    records = await _create_task_issues(hub, run, tasks, parent_id=record.issue_id, origin="ARCHITECT")
    continues = any(s.order > 2 and s.kind == "phase" for s in run.steps[run.cursor + 1:])
    inserted = 0
    if settings.get("auto_backlog", True) and continues:
        run.insert_before_order(records, 5)
        run.backlog_expanded = True
        inserted = len(records)
    await hub.record_event(
        trace_id=run.run_id, from_agent="ARCHITECT", to_agent="PM", action="BACKLOG_PUBLISHED", status="SUCCESS",
        payload={"order": record.order, "tasks": [{"issue_id": r.issue_id, "title": r.title, "role": r.role} for r in records],
                 "inserted_into_run": inserted > 0},
        current_file=hub_docs_path(hub, "ARCHITECTURE.md", project_dir_for(hub, run)), tokens_used=0,
        friendly_dialogue=tx("{n} geliştirme görevi çıkardım", n=len(records)) + (tx(", koşuya eklendi; iskeletten sonra sırayla işlenecek.") if inserted else tx(" (Jira backlog'una yazıldı).")),
        what_doing=tx("Backlog'u Jira'ya yazdı"), what_next=tx("Geliştiriciler iskeleti kurup görevleri alacak"),
    )
    await hub.record_task_audit(record.issue_id, "ARCHITECT", "BACKLOG_EXPANDED",
                                notes=tx("{n} görev: ", n=len(records)) + ", ".join(f"{r.issue_id} {r.title[:40]} ({r.role})" for r in records)[:600])
    await hub.broadcast({"type": "BACKLOG_EXPANDED", "run_id": run.run_id, "count": len(records), "inserted": inserted})
    return inserted


async def expand_improvements(hub, run: PipelineRun, record: StepRecord, payload: Dict[str, Any]) -> int:
    """PO reddi: `improvements[]` görevleri + QA (6) ve PO (9) adımlarının yeni turu koşuya eklenir (tur sınırı dahilinde)."""
    settings = hub.get_settings()
    max_rounds = int(settings.get("max_uat_rounds", 1) or 0)
    tasks = normalize_improvements(payload.get("improvements"), custom_roles=AR.routing_roles(hub))
    if not tasks:
        return 0
    if run.mode == "sprint":
        # Sprint kapsamı taahhütten sonra değişmez: iyileştirmeler backlog'a (origin=UAT) yazılır, sonraki sprintin adayıdır (§7.6 sıra 3)
        await _create_task_issues(hub, run, tasks, parent_id=record.issue_id, origin="PO", issue_type="FEATURE")
        sp = SP.get_sprint(hub, record.sprint) if record.sprint else None
        if sp is not None:
            sp["uat_rejections"] = int(sp.get("uat_rejections", 0)) + 1
        await hub.record_task_audit(record.issue_id, "PO", "UAT_IMPROVEMENTS_QUEUED",
                                    notes=tx("{n} iyileştirme sonraki sprintin adayı olarak backlog'a yazıldı.", n=len(tasks)))
        return 0
    if run.uat_round >= max_rounds:
        await hub.record_task_audit(record.issue_id, "SYSTEM", "UAT_LIMIT_REACHED",
                                    notes=tx("PO {n} iyileştirme istedi ama iyileştirme turu hakkı doldu ({max}); liste Jira'ya yazıldı.", n=len(tasks), max=max_rounds))
        await _create_task_issues(hub, run, tasks, parent_id=record.issue_id, origin="PO", issue_type="FEATURE")
        return 0
    run.uat_round += 1
    records = await _create_task_issues(hub, run, tasks, parent_id=record.issue_id, origin="PO", issue_type="FEATURE")
    new_round = run.uat_round + 1
    for order in (6, 9):
        if run.has_order(order):
            issue = hub.jira_issues.get(f"JIRA-{order}") or {}
            records.append(StepRecord(order=order, issue_id=f"JIRA-{order}", role=issue.get("assignee", "QA" if order == 6 else "PO"),
                                      kind="phase", title=issue.get("title", ""), round=new_round))
    run.insert_after_cursor(records)
    await hub.record_event(
        trace_id=run.run_id, from_agent="PO", to_agent="PM", action="REQUEST_ENHANCEMENT", status="FAILED",
        payload={"order": record.order, "uat_round": run.uat_round, "tasks": [{"issue_id": r.issue_id, "title": r.title, "role": r.role} for r in records if r.kind == "task"]},
        current_file=hub_docs_path(hub, "uat/acceptance_criteria.md", project_dir_for(hub, run)), tokens_used=0,
        friendly_dialogue=tx("UAT'de {n} eksik buldum; iyileştirme turu {round} açıldı, ardından QA ve UAT yeniden koşacak.", n=len(tasks), round=run.uat_round),
        what_doing=tx("İyileştirme görevlerini açtı"), what_next=tx("Geliştiriciler eksikleri tamamlayacak"),
    )
    await hub.record_task_audit(record.issue_id, "PO", "IMPROVEMENT_ROUND_OPENED",
                                notes=tx("Tur {n}/{max}: ", n=run.uat_round, max=max_rounds) + ", ".join(f"{r.issue_id} {r.title[:40]}" for r in records if r.kind == "task")[:600])
    await hub.broadcast({"type": "IMPROVEMENT_ROUND", "run_id": run.run_id, "round": run.uat_round, "count": len(tasks)})
    return len(records)


# ---------------------------------------------------------------------------
# İlerleme ve onay kararları
# ---------------------------------------------------------------------------
async def advance_run(hub, run: PipelineRun):
    run.approval_token = None
    run.advance()
    if run.is_terminal:
        await finalize_run(hub, run)
    else:
        await publish_run(hub, run)


def needs_decisions(hub, run: PipelineRun, record: StepRecord) -> bool:
    """Tasarım/kod adımlarına (order >= 2, LLM) geçmeden teknoloji kararları alınmış olmalı."""
    if record is None or record.order < 2:
        return False
    try:
        if handler_for(hub, record).server_side:
            return False
    except Exception:
        return False
    # F2 (§7.4): kapı yalnızca yönetici onayıyla kapanır; onay modu, AUTO_ALL ve önceden dolu tech_decisions kapıyı geçirmez
    return not hub.tech_requirements_approved()


async def ensure_decisions(hub, run: PipelineRun, record: StepRecord) -> Optional[str]:
    """Gerekirse teknoloji kapısını açar ve token döner. Hiçbir onay modunda atlanmaz."""
    if record is None or record.order < 2:
        return None
    try:
        if handler_for(hub, record).server_side:
            return None
    except Exception:
        return None
    # Yeni not / yeni soru geldiyse farkı işle (§7.4 madde 9): onaylı kalem yeni notla çelişirse yeniden sorulur
    requirements = await hub.ensure_tech_requirements(project_dir_for(hub, run))
    if hub.tech_requirements_approved():
        return None
    questions = hub.tech_questions()
    open_q = [q for q in requirements.get("questions", []) if q.get("status") == "AÇIK"]
    info = {
        "kind": "decisions",
        "run_id": run.run_id,
        "order": record.order,
        "issue_id": record.issue_id,
        "title": tx("Teknoloji ve mimari kararları"),
        "agent_id": "ARCHITECT",
        "agent_name": tx("Sistem (karar kapısı)"),
        "agent_role": tx("Karar"),
        "next_agent_id": handler_for(hub, record).agent_id,
        "next_agent_name": hub.agents.get(handler_for(hub, record).agent_id, {}).get("name", ""),
        "action": "DECISIONS_REQUESTED",
        "summary": tx("Adım #{n} başlamadan önce yönetici onayı gerekiyor: {items} teknoloji kalemi "
                      "({pending} onay bekliyor, {open} açık engelleyici soru). "
                      "Dosya: {file}", n=record.order, items=len(requirements['items']),
                      pending=sum(1 for i in requirements['items'] if i['status'] != 'ONAYLANDI'), open=len(open_q),
                      file=(requirements.get('files') or ['TECH_REQUIREMENTS.md'])[-1]),
        "artifacts": [],
        "screenshots": [],
        "tokens_used": 0,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "is_last_step": False,
        "engine": run.engine,
        "status": "SUCCESS",
        "questions": questions,
        "requirements": requirements,
    }
    token = hub.open_step_approval(info)
    run.approval_token = token
    run.gate_kind = "decisions"
    run.status = "WAITING_APPROVAL"
    await hub.broadcast({"type": "STEP_WAITING_APPROVAL", "step_info": hub.pending_step_approval})
    await hub.broadcast({"type": "DECISIONS_REQUESTED", "run_id": run.run_id, "questions": questions, "approval_token": token})
    await publish_run(hub, run)
    return token


async def finalize_run(hub, run: PipelineRun, status: Optional[str] = None, reason: str = ""):
    if status:
        run.finish(status, reason)
    if hub.active_run_id == run.run_id:
        hub.active_run_id = None
    if getattr(hub, "auto_proceed_run_id", None) == run.run_id:
        hub.auto_proceed_all = False
        hub.auto_proceed_run_id = None
    await hub.settle_agents_after_run(completed=(run.status == "COMPLETED"))
    await publish_run(hub, run)
    await hub.broadcast({
        "type": "JIRA_BATCH_COMPLETED",
        "run_id": run.run_id,
        "status": run.status,
        "engine": run.engine,
        "processed_count": sum(1 for s in run.steps if s.status == "DONE"),
        "target_path": project_dir_for(hub, run),
    })
    if run.mode == "sprint" and run.status == "COMPLETED":
        pending = (SP.ensure_state(hub).get("pending_intake") or {}).get("spec_ids")
        if pending and SP.enabled(hub):
            asyncio.create_task(_start_followup(hub, run.project_id))


async def _start_followup(hub, project_id: str) -> None:
    """Koşu sürerken kuyruğa giren yüklemeler için tek bir ardıl değerlendirme koşusu başlatır."""
    from .engine.api import LocalRunsApi
    try:
        api = getattr(hub, "_runs_api", None) or LocalRunsApi(hub)
        await api.start_sprint_run(project_id=project_id)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Yönetici müdahalesi: notlar ve revize isteği
# ---------------------------------------------------------------------------
MANAGER_NOTE_LIMIT = 100
MANAGER_NOTE_MAX_CHARS = 2000
REVISABLE_KINDS = ("phase", "structure", "task", "fix")


def _next_note_id(run: PipelineRun) -> str:
    nums = [int(str(n.get("id", "N-0"))[2:]) for n in run.manager_notes if str(n.get("id", "")).startswith("N-") and str(n["id"])[2:].isdigit()]
    return f"N-{(max(nums) if nums else 0) + 1}"


async def add_manager_note(hub, run: PipelineRun, text: str, urgent: bool = False, kind: str = "note") -> Dict[str, Any]:
    """Yöneticinin notunu (ya da revize gerekçesini) koşuya yazar; sonraki `get_next_step` bağlamına 'Yönetici notları' olarak girer.
    `urgent` ise koşu duraklatılır (istemci yeni adım almaz) ve yönetici devam ettirene kadar bekler."""
    text = str(text or "").strip()
    if not text:
        raise ValueError(tx("Not boş olamaz."))
    if run.is_terminal:
        raise ValueError(tx("Koşu sonlanmış ({status}); not eklenemez.", status=run.status))
    kind = kind if kind in ("note", "revise") else "note"
    record = run.current_step
    note = {
        "id": _next_note_id(run), "kind": kind, "text": text[:MANAGER_NOTE_MAX_CHARS], "urgent": bool(urgent) and kind == "note",
        "author": "MANAGER", "created_at": datetime.now(timezone.utc).isoformat(),
        "for_step": record.order if record else None, "delivered_step": None, "delivered_at": None,
    }
    run.manager_notes.append(note)
    del run.manager_notes[:-MANAGER_NOTE_LIMIT]
    run.touch()
    target = (record.role if record else None) or "ALL"
    action = "REVISE_REQUESTED" if kind == "revise" else "MANAGER_NOTE"
    await hub.record_event(
        trace_id=run.run_id, from_agent="MANAGER", to_agent=target, action=action, status="SUCCESS",
        payload={"note_id": note["id"], "order": note["for_step"], "urgent": note["urgent"], "text": note["text"][:600]},
        friendly_dialogue=note["text"][:200],
        what_doing=tx("Yönetici revize istedi") if kind == "revise" else tx("Yönetici müdahale etti"),
        what_next=tx("Not bir sonraki adımın bağlamına eklenecek") if kind == "note" else tx("Aynı adım geri bildirimle yeniden üretilecek"),
    )
    if note["urgent"] and not run.paused:
        run.paused, run.pause_reason = True, "manager-note"
        await hub.broadcast({"type": "RUN_PAUSED", "run_id": run.run_id, "reason": "manager-note"})
    await publish_run(hub, run)
    return note


def deliver_manager_notes(run: PipelineRun, record: StepRecord) -> str:
    """Bu adımın bağlamına eklenecek yönetici notları. Bir not ilk teslim edildiği adıma bağlanır:
    aynı adım tekrar istenirse (submit başarılı olana dek) yine görünür, sonraki adımlara taşınmaz."""
    lines: List[str] = []
    for n in run.manager_notes:
        if n.get("delivered_step") not in (None, record.order):
            continue
        if n.get("delivered_step") is None:
            n["delivered_step"], n["delivered_at"] = record.order, datetime.now(timezone.utc).isoformat()
        label = tx("REVİZE İSTEĞİ") if n.get("kind") == "revise" else tx("NOT")
        lines.append(f"- [{n['id']} · {label}] {n['text']}")
    if not lines:
        return ""
    head = tx("\n\n## Yönetici notları (öncelikli — bunlara uy)\n")
    if any(n.get("kind") == "revise" and n.get("delivered_step") == record.order for n in run.manager_notes):
        head += tx("Bu adımın önceki teslimi yönetici tarafından revize için geri çevrildi. Aşağıdaki geri bildirime göre adımı yeniden üret; "
                   "değişen dosyaların TAMAMINI ver.\n")
    tail = ""
    if any(n.get("kind") != "revise" and n.get("delivered_step") == record.order for n in run.manager_notes):
        ids = ", ".join(n["id"] for n in run.manager_notes if n.get("kind") != "revise" and n.get("delivered_step") == record.order)
        tail = (tx("\n\n**Cevap zorunlu ({ids}):** teslim zarfının `payload.manager_replies` listesine her NOT için ", ids=ids) +
                tx("`{\"note_id\": \"N-1\", \"answer\": \"...\"}` ekle. Not bir soruysa doğrudan ve somut cevapla (bilmiyorsan ya da yapamıyorsan bunu açıkça yaz; "
                   "uydurma). Talimatsa nasıl uyguladığını ya da neden uygulamadığını bir-iki cümleyle yaz. Cevap yöneticiye panoda notun altında gösterilir."))
    return head + "\n".join(lines) + tail


def can_revise(hub, run: PipelineRun, record: Optional[StepRecord]) -> Optional[str]:
    """Revize istenebilir mi? Hayırsa kullanıcıya gösterilecek neden döner."""
    if record is None:
        return tx("Revize edilecek adım yok.")
    if run.engine != "mcp_client":
        return tx("Revize yalnızca MCP istemcisi (Claude) koşularında vardır; şablon motoru içeriği yeniden üretmez.")
    if run.status != "WAITING_APPROVAL" or run.gate_kind not in ("", "step"):
        return tx("Revize yalnızca bir adım teslimi onay beklerken istenebilir.")
    if record.kind not in REVISABLE_KINDS:
        return tx("'{kind}' adımları için revize desteklenmiyor; bir not bırakın ya da soruları cevaplayın.", kind=record.kind)
    try:
        if handler_for(hub, record).server_side:
            return tx("Sunucu tarafı adımlar için revize yoktur (içeriği ajan üretmedi).")
    except Exception:
        pass
    return None


async def _revert_step_outputs(hub, run: PipelineRun, record: StepRecord) -> int:
    """Yeniden üretilecek adımın yinelenme riski taşıyan yan etkilerini geri alır (mimar adımının backlog görevleri)."""
    if not (record.kind in ("phase", "structure") and record.order == 2):
        return 0
    doomed = {i["id"] for i in hub.jira_issues.values()
              if str(i.get("kind", "")).lower() == "task" and i.get("origin") == "ARCHITECT" and i.get("run_id") == run.run_id
              and i.get("status") == "BACKLOG" and not i.get("sprint") and not i.get("closed_in_sprint")}
    if not doomed:
        return 0
    for iid in doomed:
        hub.jira_issues.pop(iid, None)
    tail = run.steps[run.cursor + 1:]
    kept = [s for s in tail if not (s.issue_id in doomed or (s.kind == "structure" and s.issue_id == record.issue_id and s.status == "PENDING"))]
    run.steps[run.cursor + 1:] = kept
    run.backlog_expanded = False
    await hub.broadcast({"type": "JIRA_UPDATED", "jira_issues": list(hub.jira_issues.values())})
    hub.mark_dirty()
    return len(doomed)


async def revise_current_step(hub, run: PipelineRun, record: StepRecord) -> None:
    """Teslim edilmiş adımı yönetici geri bildirimiyle yeniden üretilmek üzere açar (aynı sıra numarası; istemci `get_next_step` ile alır)."""
    removed = await _revert_step_outputs(hub, run, record)
    record.status, record.finished_at, record.attempts = "PENDING", None, 0
    run.status, run.approval_token, run.gate_kind, run.last_decision = "ACTIVE", None, "", "REVISE"
    if record.kind not in ("plan", "close", "meeting", "review"):
        await hub.update_jira_issue(record.issue_id, {
            "status": "IN_PROGRESS", "audit_action": "REVISE_REQUESTED",
            "audit_notes": tx("Yönetici revize istedi (adım #{n})", n=record.order) + (tx("; {n} backlog görevi geri alındı", n=removed) if removed else ""),
        })
    await publish_run(hub, run)


_NO_ISSUE_KINDS = ("plan", "close", "meeting", "review")


async def _settle_issue_after_approval(hub, run: PipelineRun, record) -> None:
    """Onaydan sonra Jira durumu: IN_REVIEW'daki madde, bekleyen düzeltmesi/başarısız doğrulaması yoksa DONE olur."""
    if record.kind in _NO_ISSUE_KINDS or record.kind == "rescope":
        return
    issue = hub.jira_issues.get(record.issue_id) or {}
    if issue.get("status") != "IN_REVIEW":
        return
    pending_fix = any(s.kind == "fix" and s.issue_id == record.issue_id and s.status in ("PENDING", "ACTIVE") for s in run.steps)
    failed = bool(record.verification and record.verification.get("status") == "FAILED")
    await hub.update_jira_issue(record.issue_id, {
        "status": "IN_PROGRESS" if (pending_fix or failed) else "DONE",
        "audit_action": "APPROVED", "audit_notes": tx("Adım #{n} yönetici tarafından onaylandı.", n=record.order),
    })


async def apply_approval_decision(hub, run: PipelineRun, decision: str) -> str:
    """Onay kararını koşuya uygular: PROCEED/AUTO_ALL ilerletir; REVISE aynı adımı yeniden açar; REJECTED/TIMEOUT/CANCELLED koşuyu durdurur."""
    token = run.approval_token
    record = run.current_step
    if token:
        await hub.close_step_approval(token, decision)
    if run.gate_kind == "sprint":
        # Sprint taahhüt onayı (sprint.commit_approval=manual): onay = taahhüt; adım henüz bitmedi, plan yeniden koşar
        run.gate_kind, run.approval_token = "", None
        if decision in ("PROCEED", "AUTO_ALL"):
            sp = SP.get_sprint(hub, record.sprint) if record is not None and record.sprint else None
            if sp is not None:
                sp["commit_approved"] = True
                # G3: zaman aşımıyla kesinleşen taahhüt (by: TIMEOUT) yönetici onayı gibi görünmez
                sp["commit_approval"] = {"mode": sp["commit_approval"].get("mode", "manual"),
                                         "by": "TIMEOUT" if sp["commit_approval"].get("by") == "TIMEOUT" else "MANAGER"}
            run.status = "ACTIVE"
            if record is not None:
                record.status = "PENDING"
            await publish_run(hub, run)
            return decision
        status = "CANCELLED" if decision in ("CANCELLED", "REJECTED") else "FAILED"
        await finalize_run(hub, run, status=status, reason=f"sprint-commit:{decision}")
        return decision
    if run.gate_kind == "questions":
        # Engelleyici soru kapısı: onay = sorular cevaplandı. Cevapsız PROCEED/AUTO_ALL kapıyı kapatmaz; plan adımı yeniden koşup kapıyı yeniden açar.
        run.gate_kind, run.approval_token = "", None
        if decision in ("PROCEED", "AUTO_ALL"):
            run.status = "ACTIVE"
            if record is not None:
                record.status = "PENDING"
            await publish_run(hub, run)
            return decision
        status = "CANCELLED" if decision in ("CANCELLED", "REJECTED") else "FAILED"
        await finalize_run(hub, run, status=status, reason=f"questions:{decision}")
        return decision
    if run.gate_kind == "decisions":
        # Teknoloji kapısı: adım henüz başlamadı. PROCEED/AUTO_ALL kalemleri onaylamaz; onay eksikse sıradaki
        # ensure_decisions kapıyı yeniden açar (F2, A4).
        run.gate_kind, run.approval_token = "", None
        if decision in ("PROCEED", "AUTO_ALL"):
            run.status = "ACTIVE"
            await publish_run(hub, run)
            return decision
        status = "CANCELLED" if decision in ("CANCELLED", "REJECTED") else "FAILED"
        await finalize_run(hub, run, status=status, reason=f"decisions:{decision}")
        return decision
    if decision == "REVISE":
        if record is not None and can_revise(hub, run, record) is None:
            await revise_current_step(hub, run, record)
            return decision
        decision = "REJECTED"     # güvenlik ağı: destek dışı adımda sessizce ilerlemek yerine koşuyu durdurur (kapı hub.approve_step'te kontrol edilir)
    if decision == "AUTO_ALL":
        # Yalnızca bu koşunun kalan adımları onaysız ilerler; hub'ın onay modu (settings) değişmez
        run.step_by_step = False
        hub.auto_proceed_all = True
        hub.auto_proceed_run_id = run.run_id
    if decision in ("PROCEED", "AUTO_ALL"):
        if record is not None:
            record.status = "DONE"
            await _settle_issue_after_approval(hub, run, record)
        await advance_run(hub, run)
        return decision

    if record is not None:
        record.status = "REJECTED" if decision == "REJECTED" else record.status
        await hub.record_task_audit(
            record.issue_id, "SYSTEM", f"APPROVAL_{decision}",
            notes=tx("Adım #{n} için kullanıcı onayı alınamadı ({decision}); koşu durduruldu.", n=record.order, decision=decision),
        )
    status = "CANCELLED" if decision in ("CANCELLED", "REJECTED") else "FAILED"
    await finalize_run(hub, run, status=status, reason=f"approval:{decision}")
    return decision


async def cancel_run(hub, run: PipelineRun, reason: str = "user"):
    if run.is_terminal:
        return
    if run.approval_token:
        hub.gate.resolve(run.approval_token, "CANCELLED")
        await hub.close_step_approval(run.approval_token, "CANCELLED")
        run.approval_token = None
    await finalize_run(hub, run, status="CANCELLED", reason=reason)


# ---------------------------------------------------------------------------
# Sprint kipi (F3): epik/hikâye üretimi, görev kırılımı, UAT iyileştirmeleri
# ---------------------------------------------------------------------------
def _ac_list(raw: Any) -> List[str]:
    out = []
    for a in raw or []:
        text = a.get("text") if isinstance(a, dict) else a
        text = str(text or "").strip()
        if text:
            out.append(text[:300])
    return out[:12]


async def expand_intake(hub, run: PipelineRun, record: StepRecord, payload: Dict[str, Any]) -> int:
    """PM çıktısından epik ve hikâye maddeleri üretir. Mevcut maddeleri SİLMEZ (karar 17/19): değişiklik yerinde izlenir ya da yeni madde olur."""
    st = SP.ensure_state(hub)
    created = 0
    epics_by_local: Dict[str, str] = {}
    by_title = {SP._norm_title(i.get("title", "")): i for i in hub.jira_issues.values() if str(i.get("kind", "")).lower() in ("epic", "story")}
    order = _next_jira_order(hub)

    for e in payload.get("epics") or []:
        if not isinstance(e, dict) or not str(e.get("title") or "").strip():
            continue
        found = by_title.get(SP._norm_title(e["title"]))
        if found and str(found.get("kind", "")).lower() == "epic":
            epics_by_local[str(e.get("id") or "")] = found["id"]
            continue
        iid = f"JIRA-{order}"
        await hub.update_jira_issue(iid, {"order": order, "title": str(e["title"])[:160], "description": str(e.get("description") or "")[:1500],
                                          "issue_type": "EPIC", "status": "BACKLOG", "priority": "P1", "assignee": "PM", "kind": "epic",
                                          "origin": "PM", "agent_id": "PM", "audit_action": "EPIC_CREATED", "audit_notes": tx("PM notlardan üretti")})
        epics_by_local[str(e.get("id") or "")] = iid
        order += 1
        created += 1

    default_epic = next(iter(epics_by_local.values()), None) or next((i["id"] for i in hub.jira_issues.values() if str(i.get("kind", "")).lower() == "epic"), None)
    for s in payload.get("stories") or payload.get("user_stories") or []:
        if not isinstance(s, dict):
            continue
        title = str(s.get("title") or s.get("i_want") or "").strip()[:160]
        if not title:
            continue
        acs = _ac_list(s.get("acceptance_criteria"))
        found = by_title.get(SP._norm_title(title))
        explicit = hub.jira_issues.get(str(s.get("supersedes") or s.get("related_to") or ""))
        parent = epics_by_local.get(str(s.get("epic") or ""), default_epic)
        if found and found.get("kind") == "story" and not SP.is_frozen(hub, found):
            if acs and _ac_list(found.get("acceptance_criteria")) != acs:
                refs = list(found.get("ac_refs") or [])
                for text in acs:
                    ac_id = SP.next_ac_id(hub)
                    st["acs"][ac_id] = {"text": text, "story": found["id"]}
                    refs.append(ac_id)
                await hub.update_jira_issue(found["id"], {"acceptance_criteria": acs, "ac_refs": refs})
            continue
        link = found if (found and found.get("kind") == "story") else explicit
        iid = f"JIRA-{order}"
        refs = []
        for text in acs:
            ac_id = SP.next_ac_id(hub)
            st["acs"][ac_id] = {"text": text, "story": iid}
            refs.append(ac_id)
        data: Dict[str, Any] = {
            "order": order, "title": title, "description": tx("{as_a} olarak {i_want} — {so_that}", as_a=s.get('as_a', tx('Kullanıcı')), i_want=s.get('i_want', title), so_that=s.get('so_that', ''))[:1500],
            "issue_type": "STORY", "status": "BACKLOG", "priority": "P1", "assignee": "PM", "kind": "story", "parent_id": parent,
            "acceptance_criteria": acs, "ac_refs": refs, "origin": "PM", "agent_id": "PM", "story_ref": None,
            "audit_action": "STORY_CREATED", "audit_notes": tx("PM notlardan üretti") + (tx(" ({id} yerini alır)", id=link['id']) if link else ""),
        }
        if link:
            data["supersedes"] = link["id"]
            data["related_to"] = link["id"]
        await hub.update_jira_issue(iid, data)
        hub.jira_issues[iid]["local_id"] = str(s.get("id") or "")
        order += 1
        created += 1
    pending = st.get("pending_intake") or {}
    left = [i for i in pending.get("spec_ids", []) if i not in run.intake_spec_ids]
    st["pending_intake"] = {**pending, "spec_ids": left} if left else None
    hub.mark_dirty()
    await hub.record_event(trace_id=run.run_id, from_agent="PM", to_agent="ARCHITECT", action="INTAKE_EVALUATED", status="SUCCESS",
                           payload={"created": created, "stories": len(SP.existing_stories(hub))},
                           friendly_dialogue=tx("Notları değerlendirdim: {n} yeni epik/hikâye maddesi açıldı.", n=created))
    await hub.broadcast({"type": "INTAKE_EVALUATED", "run_id": run.run_id, "created": created})
    return created


def _resolve_story(hub, ref: str, todo: List[Dict[str, Any]]) -> Optional[str]:
    ref = str(ref or "").strip()
    issue = hub.jira_issues.get(ref)
    if issue and str(issue.get("kind", "")).lower() == "story":
        return issue["id"]
    for s in SP.existing_stories(hub):
        if ref and (s.get("local_id") == ref or s.get("task_key") == ref):
            return s["id"]
    return todo[0]["id"] if todo else None


async def expand_backlog_sprint(hub, run: PipelineRun, record: StepRecord, payload: Dict[str, Any]) -> int:
    """Sprint kipi: görevler Jira'ya yazılır ama koşuya EKLENMEZ (sprint planı seçer). Kalan hikâyeler için yapılandırma devam adımı eklenir."""
    cap = int(hub.get_settings().get("max_backlog_tasks", 40) or 40)
    tasks = TST.with_design_task(hub, backlog_for(hub, payload.get("backlog"), cap))      # G7: QA test tasarım görevi (sıkı DoD)
    todo_before = SP.stories_without_tasks(hub)
    for t in tasks:
        if not t.get("story_ref") and t.get("work_type") in ("SCAFFOLD", "DEVOPS", "DOCS", "REFACTOR"):
            t["story_ref"] = ""      # proje düzeyi iş: mimari maddesinin altında kalır, hiçbir hikâyenin kırılımı sayılmaz
        else:
            t["story_ref"] = _resolve_story(hub, t.get("story_ref"), todo_before) or ""
    records = await _create_task_issues(hub, run, tasks, parent_id=record.issue_id, origin="ARCHITECT") if tasks else []
    remaining = SP.stories_without_tasks(hub)
    covered = {s["id"] for s in todo_before} - {s["id"] for s in remaining}
    inserted = 0
    structure_steps = sum(1 for x in run.steps if x.kind == "structure")
    if remaining and (covered or records) and structure_steps < 50:
        run.insert_after_cursor([StepRecord(order=record.order, issue_id=record.issue_id, role="ARCHITECT", kind="structure",
                                            title=tx("Görev kırılımı (devam: {n} hikâye kaldı)", n=len(remaining)))])
        inserted = 1
    elif remaining and todo_before:
        # Bu adım ilerleme sağlamadı (görev üretmedi): sonsuz döngüyü önlemek için kalanlar işaretlenir ve denetim izine yazılır
        for s in remaining:
            await hub.update_jira_issue(s["id"], {"structured": True, "audit_action": "STRUCTURE_SKIPPED", "audit_notes": tx("ARCHITECT bu hikâye için görev üretmedi.")})
    await hub.record_event(
        trace_id=run.run_id, from_agent="ARCHITECT", to_agent="SCRUM_MASTER", action="BACKLOG_PUBLISHED", status="SUCCESS",
        payload={"order": record.order, "tasks": [{"issue_id": r.issue_id, "title": r.title, "role": r.role, "work_type": r.work_type} for r in records],
                 "stories_remaining": len(remaining)},
        friendly_dialogue=tx("{n} görev çıkardım", n=len(records)) + (tx("; {n} hikâye sonraki adıma kaldı.", n=len(remaining)) if remaining else tx("; tüm hikâyeler görevlere bölündü.")),
    )
    await hub.broadcast({"type": "PLAN_GENERATED", "run_id": run.run_id, "tasks": len(records), "stories_remaining": len(remaining)})
    return inserted


async def expand_decision_plan(hub, run: PipelineRun, record: StepRecord, payload: Dict[str, Any]) -> int:
    """Yönetici kararını bölen mimar adımının görevlerini Jira'ya yazar ve koşuda GEÇERLİ ADIMDAN HEMEN SONRA çalışacak şekilde ekler (karar önceliklidir):
    sprint kapsamına girer, `expedite=now` işaretlenir, kapsam değişikliği kaydedilir. Görev üretmediyse (boş backlog) hiçbir şey eklenmez."""
    tasks = backlog_for(hub, payload.get("backlog"), 12)
    if not tasks:
        return 0
    records = await _create_task_issues(hub, run, tasks, parent_id=record.issue_id, origin="DECISION")
    n = int(record.sprint or 0)
    sp = SP.get_sprint(hub, n) if n else None
    for r in records:
        r.sprint = n or r.sprint
    run.insert_after_cursor(records)
    for r in records:
        await hub.update_jira_issue(r.issue_id, {"sprint": n or None, "expedite": "now", "audit_action": "EXPEDITED",
                                                 "audit_notes": tx("Yönetici kararından türeyen görev: geçerli adımdan sonra çalışır.")})
        if sp is not None:
            sp.setdefault("committed_issue_ids", []).append(r.issue_id)
    if sp is not None:
        sp.setdefault("scope_changes", []).append({"at": datetime.now(timezone.utc).isoformat(), "source": "decision_plan", "removed": [], "added": [r.issue_id for r in records]})
    await hub.record_event(trace_id=run.run_id, from_agent="ARCHITECT", to_agent="MANAGER", action="DECISION_PLANNED", status="SUCCESS",
                           payload={"order": record.order, "tasks": [{"issue_id": r.issue_id, "role": r.role, "title": r.title} for r in records]},
                           friendly_dialogue=tx("Yönetici kararını {n} göreve böldüm; geçerli adımdan sonra sırayla çalışacak.", n=len(records)))
    return len(records)


async def _apply_rescope(hub, run: PipelineRun, record: StepRecord, payload: Dict[str, Any]) -> None:
    from . import sprint_flow as SPF
    await SPF.apply_rescope(hub, run, record, payload)


MANAGER_REPLY_MAX_CHARS = 1500


async def record_manager_replies(hub, run: PipelineRun, record: StepRecord, handler: StepHandler, payload: Dict[str, Any]) -> Dict[str, List[str]]:
    """Ajanın `payload.manager_replies` cevaplarını bu adıma iletilen yönetici notlarına bağlar (MANAGER_REPLY olayı, notta `reply`);
    cevapsız kalan not için MANAGER_NOTE_UNANSWERED uyarısı yazılır. Yalnızca LLM (mcp_client) koşularında; şablon motoru notları yorumlayamaz."""
    out: Dict[str, List[str]] = {"answered": [], "unanswered": []}
    if run.engine == "template":
        return out
    delivered = {n["id"].upper(): n for n in run.manager_notes if n.get("kind") != "revise" and n.get("delivered_step") == record.order}
    if not delivered:
        return out
    raw = payload.get("manager_replies")
    now = datetime.now(timezone.utc).isoformat()
    for r in raw if isinstance(raw, list) else []:
        if not isinstance(r, dict):
            continue
        note = delivered.get(str(r.get("note_id") or "").strip().upper())
        answer = str(r.get("answer") or "").strip()
        if note is None or not answer:
            continue
        note["reply"] = {"answer": answer[:MANAGER_REPLY_MAX_CHARS], "by": handler.agent_id, "step": record.order, "at": now}
        note.pop("unanswered", None)
        out["answered"].append(note["id"])
        await hub.record_event(trace_id=run.run_id, from_agent=handler.agent_id, to_agent="MANAGER", action="MANAGER_REPLY", status="SUCCESS",
                               payload={"note_id": note["id"], "order": record.order, "answer": answer[:600]}, friendly_dialogue=answer[:200],
                               what_doing=tx("{id} notuna cevap verdi", id=note['id']), what_next=tx("Cevap panoda notun altında görünür"))
    pending = [n for k, n in delivered.items() if not n.get("reply")]
    for n in pending:
        n["unanswered"] = True
        out["unanswered"].append(n["id"])
    if pending:
        await hub.record_event(trace_id=run.run_id, from_agent=handler.agent_id, to_agent="MANAGER", action="MANAGER_NOTE_UNANSWERED", status="IN_PROGRESS",
                               payload={"note_ids": out["unanswered"], "order": record.order},
                               friendly_dialogue=tx("{ids} notuna adım #{n} içinde cevap verilmedi.", ids=', '.join(out['unanswered']), n=record.order))
    if out["answered"] or pending:
        run.touch()
        await publish_run(hub, run)
    return out


async def _record_handoffs(hub, run: PipelineRun, record: StepRecord, handler: StepHandler, payload: Dict[str, Any], result: StepResult) -> None:
    """Devir notları (§10.8): `payload.handoff[]` AGENT_INTERACTION olayı olarak saklanır ve alıcının sonraki adım bağlamına konur.
    Şablon motoru gerçek bir not üretmediği için bir önceki adımın dostça özetini sonraki role bırakır."""
    if record.kind in ("plan", "close"):
        return
    raw = payload.get("handoff")
    notes: List[Dict[str, str]] = []
    for h in raw if isinstance(raw, list) else []:
        if isinstance(h, dict) and str(h.get("message") or "").strip():
            notes.append({"to": str(h.get("to") or "ALL").upper(), "message": str(h["message"]).strip()[:600]})
    if not notes and run.engine == "template" and result.next_agent_id and record.kind in ("phase", "task", "fix"):
        text = str(payload.get("friendly_dialogue") or result.summary or "").strip()
        if text:
            notes.append({"to": str(result.next_agent_id).upper(), "message": text[:600]})
    for h in notes[:5]:
        target = h["to"] if (h["to"] in hub.agents or h["to"] == "ALL") else "ALL"
        run.handoffs.append({"from": handler.agent_id, "to": target, "order": record.order, "message": h["message"]})
        await hub.record_event(
            trace_id=run.run_id, from_agent=handler.agent_id, to_agent=target, action="HANDOFF", status="SUCCESS",
            payload={"order": record.order, "task_id": record.issue_id, "message": h["message"], "summary": str(payload.get("summary") or result.summary)[:300]},
            friendly_dialogue=h["message"][:200], what_doing=tx("Devir notu bıraktı"), what_next=tx("{target} sonraki adımda notu okuyacak", target=target))
    del run.handoffs[:-60]


async def _ask_allow_command(hub, run: PipelineRun, record: StepRecord, key: str, cmd: str, why: str) -> None:
    """İzin listesi dışı komut: engelleyici EXTERNAL_ACTION sorusu (A: izin ver ve önek listeye eklensin, B: reddet). Sprint ortasındaysa sprint BLOCKED olur."""
    parts = G._strip_cd(cmd)
    prefix = " ".join((parts[-1] if parts else cmd).split()[:2])
    q = await M.open_system_question(
        hub, category="EXTERNAL_ACTION", raised_by=record.role if record.role in hub.agents else "ARCHITECT", sprint=record.sprint,
        text=tx("`{key}` komutu izin listesinde değil: `{cmd}`. Çalıştırılmasına izin verilsin mi?", key=key, cmd=cmd[:160]),
        options=[{"key": "A", "label": tx("İzin ver; '{prefix}' önekini izin listesine ekle", prefix=prefix)}, {"key": "B", "label": tx("Reddet; komut koşmasın")}],
        recommended="B", rationale=tx("Komut yalıtımı izin listesiyle çalışır (§12 madde 1); liste dışı komut yönetici kararı gerektirir. ") + why[:160],
        action={"type": "allow_command", "key": key, "cmd": cmd[:400], "prefix": prefix})
    if q is not None and run.mode == "sprint" and record.sprint:
        sp = SP.get_sprint(hub, record.sprint)
        if sp is not None and sp["status"] not in ("BLOCKED", "CLOSED", "CANCELLED"):
            await DRV.block_sprint(hub, run, sp, "BLOCKING_QUESTION", tx("{id}: izin listesi dışı komut ({key})", id=q['id'], key=key))


async def _record_delivery_secret(hub, run: PipelineRun, record: StepRecord, handler: StepHandler, findings: List[Dict[str, Any]]) -> None:
    """G4 (§12 madde 4): teslimde yüksek güvenli sır → diske yazılmadan reddedildi. Olay + denetim izi; sprintte güvenlik ihlali sayılır
    (ikinci tekrarda sprint BLOCKED — commit öncesi taramayla aynı kural)."""
    note = "; ".join(f"{f['file']}:{f['line']} {f['kind']} ({f['preview']})" for f in findings[:5])
    await hub.record_event(trace_id=run.run_id, from_agent="SYSTEM", to_agent=handler.agent_id, action="DELIVERY_BLOCKED_SECRET", status="FAILED",
                           payload={"order": record.order, "task_id": record.issue_id, "findings": findings[:5]},
                           friendly_dialogue=tx("Teslim reddedildi: sır bulgusu ({note}). Dosya yazılmadı; değeri ortam değişkenine taşıyıp aynı adımı tekrar gönder.", note=note[:140]))
    if record.issue_id:
        await hub.record_task_audit(record.issue_id, "SYSTEM", "DELIVERY_BLOCKED_SECRET", notes=note[:300])
    if record.sprint:
        sp_ = SP.get_sprint(hub, record.sprint)
        if sp_ is not None:
            sp_["security_violations"] = int(sp_.get("security_violations", 0)) + 1
            if sp_["security_violations"] >= 2 and sp_["status"] != "BLOCKED":
                await DRV.block_sprint(hub, run, sp_, "SECURITY_VIOLATION", tx("sır bulgusu {n}. kez tekrarlandı", n=sp_['security_violations']))
    hub.mark_dirty()


async def _gate_proposed_commands(hub, run: PipelineRun, record: StepRecord, proposed: Dict[str, str]) -> Dict[str, str]:
    """İzin listesi politikasında LLM'in önerdiği komutlar: izinli olanlar geçer, olmayanlar soruya dönüşür (ayarlara yazılmaz)."""
    kept: Dict[str, str] = {}
    for key, cmd in proposed.items():
        if key in ("health_url", "app_url"):
            kept[key] = cmd
            continue
        ok, bad = G.command_allowed(hub, cmd)
        if ok:
            kept[key] = cmd
        else:
            await _ask_allow_command(hub, run, record, key, cmd, tx("Önerilen parça: ") + "; ".join(bad)[:160])
    return kept
