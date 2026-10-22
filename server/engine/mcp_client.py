"""
McpClientEngine — çekme (pull) modeli.

Döngü yoktur: MCP istemcisi (Claude Desktop / Antigravity) `next_step` ile adımı ve promptu alır,
adımı kendi modeliyle üretir, `submit` ile JSON zarfını geri verir. Onay gerektiğinde dashboard'dan
verilen karar anında uygulanır; istemci `poll_approval` ile kısa yoklamalarla bekler.
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from ..llm.parsing import StepOutputError
from ..llm.template_provider import template_provider
from ..runs import PipelineRun
from .. import display as DISP
from .. import driver as DRV
from .. import pipeline as P
from ..i18n import translate as tx, N_

RUN_HEARTBEAT_TIMEOUT_S = float(os.environ.get("RUN_HEARTBEAT_TIMEOUT_S", "600"))
MAX_STEP_ATTEMPTS = int(os.environ.get("MAX_STEP_ATTEMPTS", "3"))

TMP_NOTE = N_("GEÇİCİ DOSYA: zarf, teslim betiği ya da ara JSON gibi geçici dosya gerekirse yalnızca `<proje>/.fs-workspace/tmp/` altına yaz; proje köküne asla (submit_*.js, step_*.json vb.). Sunucu köke bırakılanları oraya taşır ve git'e almaz.")
CLIENT_INSTRUCTIONS = N_(
    "Bu adımda `system_prompt` içindeki rolü üstlen, `user_context`'i oku ve YALNIZCA `output_contract`'ta "
    "tanımlanan JSON zarfını üret. Ardından `submit_step_result(run_id, order, result_json)` çağır. "
    "Sonuç 'WAITING_APPROVAL' ise kullanıcı dashboard'dan onaylayana kadar `wait_for_approval(run_id)` ile "
    "(gerekirse tekrar tekrar) bekle; 'NEXT' ise `get_next_step(run_id)` ile devam et; 'RUN_COMPLETE' ise bitir. "
    "Adıma başlamadan önce ne yapacağını anlatan 1-2 cümlelik kısa plan notunu `report_thinking(run_id, agent_id, text)` ile gönder. Dosyaları kendin yazma. "
    "'PAUSED' gelirse kullanıcı duraklatmıştır: `wait_for_approval(run_id)` ile bekle, 'RESUMED' gelince `get_next_step` çağır. "
    "Koşu dinamiktir: mimari adımından sonra sunucu backlog görevlerini (kind='task'), doğrulama (test/build) kalınca düzeltme "
    "adımlarını (kind='fix', aynı order) ve PO reddinde iyileştirme turunu koşuya ekler; `submit_step_result` yanıtındaki "
    "`verification` ve `inserted_steps` alanlarına bak, toplam adım sayısı (`total_steps`) artabilir. "
    "Görev listesi: bir görev/todo aracın varsa (Claude Code: TodoWrite) koşunun her adımı için `todo_title` ile birer madde tut "
    "(yeni eklenen adımlar için de madde aç); bu adımı in_progress, submit sonrası completed işaretle — kullanıcı ilerlemeyi soldaki iş listesinden izler. "
    "Yönetici müdahalesi: `user_context` sonundaki 'Yönetici notları' bölümü öncelikli talimattır, ona uy. "
    "`wait_for_approval` 'REVISE' dönerse yönetici revize istemiştir: aynı adımı `get_next_step` ile yeniden al ve geri bildirime göre yeniden üret. "
    "KULLANICIYA SORU SORMA: sohbette 'devam edeyim mi / sürdüreyim mi / onaylıyor musun / böyle mi yapayım' diye sorma ve onay bekleme; belirsizlikte en makul varsayımla ilerle, "
    "varsayımı ve açık noktayı teslimdeki `summary` / `questions` alanına yaz (yönetici soruyu panodan cevaplar). Bir iş zaten yapılmış görünüyorsa bile adımı yine teslim et "
    "(kısa bir özetle) ve `get_next_step` ile devam et. Yalnızca `RUN_COMPLETE`, `CANCELLED`, `BLOCKED`, `WAITING_APPROVAL`, `SESSION_BOUNDARY` ya da kullanıcı duraklatması döngüyü bitirir. "
    "KRİTER METNİ: bir kabul kriterinin (AC-n) metni bağlamda yoksa kullanıcıdan isteme ve kapsam dışı bırakmayı önermeden önce `get_acceptance_criteria(ac_ids)` aracıyla sunucudan al "
    "(sunucu hikâyelerden geri kurar); araç da yoksa `get_next_step(run_id)` ile adımı yeniden çek: bağlam güncellenmiş olabilir. "
    "YENİ KÜTÜPHANE/TEKNOLOJİ: onaylı listede olmayan bir kütüphane gerekiyorsa adımı kendin durdurma ve sohbette onay isteme; işi yap ve manifesti teslime koy: sunucu bağımlılığı denetler, "
    "gerekirse yöneticiye panodan teknoloji sorusu (D-n) açar ve onay gelene kadar bekletir (sohbetteki onay FS-SC'ye işlemez, yalnızca pano onayı geçerlidir)."
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class McpClientEngine:
    name = "mcp_client"

    def __init__(self, hub):
        self.hub = hub
        self._sweeper: Optional[asyncio.Task] = None

    # ------------------------------------------------------------------
    # Yaşam döngüsü
    # ------------------------------------------------------------------
    def _touch(self, run: PipelineRun, client: Optional[Dict[str, str]] = None):
        run.touch()
        if client:
            if client.get("name"):
                run.client_name = client["name"]
            if client.get("version"):
                run.client_version = client["version"]

    def _revive_if_abandoned(self, run: PipelineRun):
        """Terk edilmiş koşuyu kaldığı adımdan canlandırır. Terk anında imleçten sonrasındaki adımlar SKIPPED yapılmıştı; geri alınır.
        İmleçteki adım teslim edilmiş (finished_at) ve yönetici onayı beklerken sunucu yeniden başlamışsa yeniden ÇALIŞTIRILMAZ:
        onay bekler halde döner (kapıyı `reopen_gate` açar). İmleçten önceki SKIPPED adımlar gerçekten atlanmıştı (ör. token sınırı); dokunulmaz."""
        if run.status == "ABANDONED":
            run.status = "ACTIVE"
            run.finished_at = None
            run.cancel_reason = ""
            for idx, s in enumerate(run.steps):
                if s.status != "SKIPPED" or idx < run.cursor:
                    continue
                if idx == run.cursor and s.finished_at and s.kind not in ("plan", "close", "meeting"):
                    s.status = "WAITING_APPROVAL"
                    run.status, run.gate_kind, run.approval_token = "WAITING_APPROVAL", "step", None
                else:
                    s.status = "PENDING"
            self.hub.active_run_id = run.run_id

    async def reopen_gate(self, run: PipelineRun) -> None:
        """Onay bekleyen adımın kapısı (bellekteki token) sunucu yeniden başlayınca kaybolur: aynı adım yeniden onaya sunulur (dashboard kartı geri gelir)."""
        hub = self.hub
        if run.status != "WAITING_APPROVAL" or run.gate_kind not in ("", "step") or hub.gate.is_pending(run.approval_token):
            return
        record = run.current_step
        if record is None:
            return
        pending = hub.pending_step_approval or {}
        info = dict(pending) if (pending.get("run_id") == run.run_id and pending.get("order") == record.order) else P.step_info_from_record(hub, run, record)
        token = hub.open_step_approval(info)
        run.approval_token = token
        run.gate_kind = "step"
        await hub.broadcast({"type": "STEP_WAITING_APPROVAL", "step_info": hub.pending_step_approval})
        self._attach_decision_callback(run, token)
        await P.publish_run(hub, run)

    def _attach_decision_callback(self, run: PipelineRun, token: str):
        """Dashboard onayı gelir gelmez (istemci yoklamasa bile) kararı koşuya uygular."""
        fut = self.hub.gate.register(token)

        def _on_done(f: "asyncio.Future[str]"):
            if f.cancelled():
                return
            try:
                decision = f.result()
            except Exception:
                return
            if run.approval_token == token and run.status == "WAITING_APPROVAL":
                asyncio.create_task(P.apply_approval_decision(self.hub, run, decision))

        fut.add_done_callback(_on_done)

    # ------------------------------------------------------------------
    # Araç uygulamaları
    # ------------------------------------------------------------------
    async def next_step(self, run: PipelineRun, client: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        res = await self._next_step(run, client)
        if not res.get("display_md"):
            # Her yanıtta sunucunun hazır anlatımı bulunur (§9.5): bekleme, bitiş, duraklatma ve iptal durumları da
            label = {"RUN_COMPLETE": N_("koşu tamamlandı"), "WAITING_APPROVAL": N_("yönetici onayı/cevabı bekleniyor"), "PAUSED": N_("koşu duraklatıldı"),
                     "CANCELLED": N_("koşu iptal edildi")}.get(res.get("status"))
            label = tx(label) if label else str(res.get("status"))
            res["display_md"] = DISP.stop_md(self.hub, run, label, str(res.get("message") or ""))
        DRV.renew_lease(self.hub, run)
        if res.get("status") in ("RUN_COMPLETE", "WAITING_APPROVAL", "CANCELLED"):
            DRV.release_lease(self.hub, run.run_id)
        return res

    async def _next_step(self, run: PipelineRun, client: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        hub = self.hub
        self._revive_if_abandoned(run)
        self._touch(run, client)

        DRV.seen(hub, client)
        DRV.renew_lease(hub, run)
        if run.mode == "sprint" and run.paused and str(run.pause_reason).startswith("BLOCKED:"):
            sp_blocked = next((x for x in DRV.SP.ensure_state(hub)["sprints"] if x["status"] == "BLOCKED"), None) or {}
            b = sp_blocked.get("blocked") or {}
            return {"status": "BLOCKED", "run_id": run.run_id, "reason": b.get("reason"), "detail": b.get("detail"),
                    "message": tx("Sprint durdu ({reason}): {detail}. Yönetici çözene kadar iş yok; oturumu bitir.", reason=b.get('reason'), detail=b.get('detail')),
                    "display_md": DISP.stop_md(hub, run, str(b.get("reason")), str(b.get("detail") or ""), tx("dashboard'dan sınırı artırıp sprinti sürdürmek ya da kapatmak"))}
        if run.mode == "sprint" and run.runner_claimed and run.session_boundary and not run.is_terminal and DRV.runner_cfg(hub).get("session_boundaries"):
            return {"status": "SESSION_BOUNDARY", "run_id": run.run_id, "message": tx("Oturum sınırı: bu oturumu bitir; sonraki zamanlanmış çalıştırma claim_work ile taze oturumda sürdürür."),
                    "display_md": DISP.stop_md(hub, run, tx("oturum sınırı"), tx("bağımsız değerlendirme / oturum adım sınırı"), tx("bir şey yapmana gerek yok; sonraki çalıştırma sürdürür"))}
        if run.status == "CANCELLED":
            return {"status": "CANCELLED", "run_id": run.run_id, "message": tx("Koşu iptal edildi ({reason}).", reason=run.cancel_reason or tx('kullanıcı'))}
        if run.status in ("COMPLETED", "FAILED"):
            return {"status": "RUN_COMPLETE", "run_id": run.run_id, "run_status": run.status, "message": tx("Koşu tamamlandı.")}
        if run.status == "WAITING_APPROVAL":
            # Sunucu yeniden başladıysa token kaybolmuş olabilir: yeniden onaya sun
            await self.reopen_gate(run)
            return {
                "status": "WAITING_APPROVAL", "run_id": run.run_id, "order": run.current_step.order if run.current_step else None,
                "approval_token": run.approval_token,
                "message": tx("Adım kullanıcı onayı bekliyor. `wait_for_approval(run_id)` çağır."),
            }

        # Sunucu tarafı adımları (handshake, gerçek Playwright) burada koşup geçilir
        while not run.is_terminal:
            record = run.current_step
            if record is None:
                await P.finalize_run(hub, run, status="COMPLETED")
                return {"status": "RUN_COMPLETE", "run_id": run.run_id, "run_status": run.status, "message": tx("Koşu tamamlandı.")}
            handler = P.handler_for(hub, record)
            if handler.server_side and record.status not in ("DONE",):
                outcome = await P.run_server_step(hub, run)
                if outcome.status == "WAITING_APPROVAL" and outcome.approval_token:
                    self._attach_decision_callback(run, outcome.approval_token)
                    return {
                        "status": "WAITING_APPROVAL", "run_id": run.run_id, "order": record.order,
                        "approval_token": outcome.approval_token,
                        "message": tx("Sunucu adımı #{n} tamamlandı; kullanıcı onayı bekleniyor.", n=record.order),
                    }
                if outcome.status == "RUN_COMPLETE":
                    return {"status": "RUN_COMPLETE", "run_id": run.run_id, "run_status": run.status, "message": tx("Koşu tamamlandı.")}
                continue

            if run.paused:
                return self._paused_response(run)
            if record.kind == "task" and record.status == "PENDING":
                from .. import satisfied as SAT
                if await SAT.try_close(hub, run, record):      # görev zaten karşılanıyor (dosyalar commit'li + doğrulama geçti): ajana iş verilmez
                    continue
            token = await P.ensure_decisions(hub, run, record)
            if token:
                self._attach_decision_callback(run, token)
                return {"status": "WAITING_APPROVAL", "kind": "decisions", "run_id": run.run_id, "order": record.order, "approval_token": token,
                        "message": tx("Kullanıcının teknoloji kararları bekleniyor; `wait_for_approval(run_id)` ile bekle, APPROVED gelince `get_next_step` çağır.")}
            prompt = await P.prepare_step(hub, run)
            run.last_decision = ""
            settings = hub.get_settings()
            fix_suffix = tx(" (düzeltme {n})", n=record.fix_round) if record.kind == "fix" else ""
            issue = hub.jira_issues.get(record.issue_id) or {}
            return {
                "status": "STEP",
                "run_id": run.run_id,
                **prompt.meta,
                "system_prompt": prompt.system_prompt,
                "user_context": prompt.user_context,
                "output_contract": prompt.output_contract,
                "approval_mode": settings.get("approval_mode", "every_step"),
                "pacing": settings.get("pacing", "natural"),
                "attempt": record.attempts + 1,
                "progress": f"{run.cursor + 1}/{len(run.steps)}",
                "kind": record.kind,
                "fix_round": record.fix_round,
                "task_key": issue.get("task_key"),
                "total_steps": len(run.steps),
                "todo_title": tx("Adım {n}{suffix}: {agent} — {title}", n=record.order, suffix=fix_suffix,
                                 agent=prompt.meta.get('agent_name') or prompt.meta.get('agent_id'), title=prompt.meta.get('title') or prompt.meta.get('action')),
                "instructions": tx(CLIENT_INSTRUCTIONS) + " " + tx(TMP_NOTE),
                "sprint": record.sprint, "work_type": record.work_type or issue.get("work_type"), "meeting_type": record.work_type if record.kind == "meeting" else None,
                "display_md": DISP.step_start_md(hub, run, record, prompt.meta.get("agent_id") or record.role),
            }
        return {"status": "RUN_COMPLETE", "run_id": run.run_id, "run_status": run.status, "message": tx("Koşu tamamlandı.")}

    async def submit(self, run: PipelineRun, order: int, result_json: Any, tokens_in: int = 0, tokens_out: int = 0,
                     client: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        hub = self.hub
        self._revive_if_abandoned(run)
        self._touch(run, client)
        record = run.current_step
        if run.is_terminal or record is None:
            return {"status": "RUN_COMPLETE", "run_id": run.run_id, "run_status": run.status, "message": tx("Koşu zaten sonlandı.")}
        if run.status == "WAITING_APPROVAL":
            return {"status": "WAITING_APPROVAL", "run_id": run.run_id, "order": record.order, "approval_token": run.approval_token,
                    "message": tx("Önce bekleyen onay çözülmeli (`wait_for_approval`).")}
        if int(order) != record.order:
            return {"status": "REJECTED", "run_id": run.run_id, "order": record.order,
                    "validation_errors": [tx("Beklenen adım #{n}, gönderilen #{got}.", n=record.order, got=order)],
                    "message": tx("Sıra uyuşmuyor: şu an #{n} bekleniyor.", n=record.order)}
        if record.status == "PENDING":
            await P.prepare_step(hub, run)

        try:
            envelope = P.parse_envelope(hub, run, record, result_json)
        except StepOutputError as e:
            record.attempts += 1
            record.validation_errors = list(e.errors)[:5]
            hub.mark_dirty()
            if record.attempts >= MAX_STEP_ATTEMPTS and hub.get_settings().get("llm_fallback"):
                # Deneme kipi (llm_fallback=true): şablon çıktısıyla ilerle, denetim kaydı düş
                ctx = P.make_context(hub, run, record)
                handler = P.handler_for(hub, record)
                envelope = await template_provider.complete(ctx, handler)
                await hub.record_task_audit(
                    record.issue_id, "SYSTEM", "LLM_FALLBACK",
                    notes=tx("{n} denemede geçerli JSON alınamadı; şablon çıktısı kullanıldı. Son hata: {error}", n=record.attempts, error=e.errors[0] if e.errors else e),
                )
            elif record.attempts >= MAX_STEP_ATTEMPTS:
                # G1: ürün koşusunda yer tutucu ÜRETİLMEZ; adım FAILED olur, koşu sonraki adımla sürer
                outcome = await P.fail_step_without_output(hub, run, record, list(e.errors))
                nxt = run.current_step if (run.current_step and not run.is_terminal) else None
                DRV.renew_lease(hub, run)
                if outcome.status == "RUN_COMPLETE":
                    DRV.release_lease(hub, run.run_id)
                return {
                    "status": outcome.status, "run_id": run.run_id, "order": record.order, "attempt": record.attempts, "step_failed": True,
                    "validation_errors": record.validation_errors, "next_order": nxt.order if nxt else None, "next_kind": nxt.kind if nxt else None,
                    "total_steps": len(run.steps), "verification": None, "commit": None, "fix_requested": False, "inserted_steps": 0,
                    "message": f"{outcome.message} | " + tx("Adım #{n} FAILED: {a} denemede geçerli JSON alınamadı; yer tutucu üretilmedi.", n=record.order, a=record.attempts),
                    "display_md": DISP.stop_md(hub, run, tx("adım #{n} FAILED", n=record.order), tx("geçerli çıktı alınamadı"),
                                               tx("bir şey yapmana gerek yok; koşu sonraki adımla sürer, iş sprint kapanışında taşınır")),
                }
            else:
                return {
                    "status": "REJECTED", "run_id": run.run_id, "order": record.order, "attempt": record.attempts,
                    "validation_errors": record.validation_errors,
                    "message": tx("Çıktı doğrulanamadı; yalnızca tek bir ```json bloğu ile tekrar gönder."),
                }

        try:
            outcome = await P.finish_step(hub, run, envelope, tokens_in=tokens_in, tokens_out=tokens_out)
        except StepOutputError as e:
            record.attempts += 1
            record.validation_errors = list(e.errors)[:5]
            return {"status": "REJECTED", "run_id": run.run_id, "order": record.order, "attempt": record.attempts,
                    "validation_errors": record.validation_errors, "message": str(e)}

        if outcome.status == "WAITING_APPROVAL" and outcome.approval_token:
            self._attach_decision_callback(run, outcome.approval_token)
        extra = (outcome.result.extra if outcome.result else {}) or {}
        message = outcome.message
        if record.verification:
            message = f"{message} | {record.verification.get('summary', '')}"
        if extra.get("fix_requested"):
            message = f"{message} | " + tx("Düzeltme adımı eklendi: aynı order ile get_next_step çağır.")
        elif outcome.result is not None and outcome.result.status == "FAILED":
            message = f"{message} | " + tx("Adım FAILED: {summary}", summary=(outcome.result.summary or '')[-220:])
        elif extra.get("inserted_steps"):
            message = f"{message} | " + tx("Koşuya {n} yeni adım eklendi (toplam {total}).", n=extra['inserted_steps'], total=len(run.steps))
        nxt = run.current_step if (run.current_step and not run.is_terminal) else None
        status = outcome.status
        DRV.renew_lease(hub, run)
        if run.mode == "sprint" and run.paused and str(run.pause_reason).startswith("BLOCKED:"):
            status = "BLOCKED"
            message = f"{message} | " + tx("Sprint durdu ({reason}); yönetici çözene kadar iş yok.", reason=run.pause_reason[8:])
        elif status == "NEXT" and run.mode == "sprint":
            run.session_steps += 1
            reason = self._boundary_reason(run, record) if run.runner_claimed else None
            if reason:
                status = "SESSION_BOUNDARY"
                run.session_boundary = True
                DRV.release_lease(hub, run.run_id)
                message = f"{message} | " + tx("Oturum sınırı ({reason}): bu oturumu bitir; sonraki çalıştırma taze oturumla sürdürür.", reason=reason)
        elif status in ("WAITING_APPROVAL", "RUN_COMPLETE"):
            DRV.release_lease(hub, run.run_id)
        if status == "NEXT" and nxt is not None:
            # İstemci modeli çıktı kesik/uzun diye turu kendiliğinden bitirmesin: koşu sunucuda sürüyor
            message = f"{message} | " + tx("Koşu SÜRÜYOR (sıradaki adım #{n}): kullanıcıya sormadan ve durum özeti beklemeden hemen get_next_step çağır.", n=nxt.order)
        written = list(extra.get("files_written") or [])
        display = DISP.step_end_md(hub, run, record, record.role, summary=record.summary, written=written, verification=record.verification,
                                   commit=record.commit, extra=extra)
        if extra.get("meeting_id"):
            meeting = next((m for m in DRV.SP.ensure_state(hub)["meetings"] if m["id"] == extra["meeting_id"]), None)
            if meeting:
                display = DISP.meeting_md(hub, meeting) + "\n" + display
        if status in ("BLOCKED", "SESSION_BOUNDARY"):
            display += "\n" + DISP.stop_md(hub, run, tx("oturum sınırı") if status == "SESSION_BOUNDARY" else str(run.pause_reason[8:]), "",
                                            tx("bir şey yapmana gerek yok") if status == "SESSION_BOUNDARY" else tx("sınırı artırıp sprinti sürdür ya da kapat"))
        return {
            "status": status,
            "display_md": display,
            "run_id": run.run_id,
            "order": record.order,
            "approval_token": outcome.approval_token,
            "message": message,
            "warnings": envelope.get("_warnings", []),
            "next_order": nxt.order if nxt else None,
            "next_kind": nxt.kind if nxt else None,
            "verification": record.verification,
            "commit": record.commit,
            "fix_requested": bool(extra.get("fix_requested")),
            "inserted_steps": int(extra.get("inserted_steps") or 0),
            "total_steps": len(run.steps),
        }

    def _boundary_reason(self, run: PipelineRun, record) -> Optional[str]:
        """§9.4: geliştirmeden değerlendirmeye geçerken ya da oturum adım sınırı dolunca oturum biter (bağımsız değerlendirme, §6.6)."""
        if not DRV.runner_cfg(self.hub).get("session_boundaries"):
            return None          # oturum sınırları kapalı (varsayılan): ajan koşu bitene ya da bloke olana kadar sürer
        nxt = next((s for s in run.steps[run.cursor:] if not s.server_side and s.kind not in ("plan", "close")), None)
        dev = record.role in DRV.DEV_ROLES or record.kind in ("task", "fix")
        if dev and nxt is not None and (nxt.kind == "meeting" or nxt.role in DRV.EVAL_ROLES or (nxt.kind == "phase" and nxt.order in (6, 9))):
            return "EVALUATION"
        if run.session_steps >= DRV.runner_cfg(self.hub)["max_steps_per_session"]:
            return "MAX_STEPS"
        return None

    def _paused_response(self, run: PipelineRun) -> Dict[str, Any]:
        return {"status": "PAUSED", "run_id": run.run_id, "order": run.current_step.order if run.current_step else None,
                "message": tx("Koşu kullanıcı tarafından duraklatıldı; `wait_for_approval(run_id)` ile devam edilmesini bekle, RESUMED gelince `get_next_step` çağır.")}

    async def poll_approval(self, run: PipelineRun, timeout_s: float = 30.0, client: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        self._touch(run, client)
        timeout = max(1.0, min(float(timeout_s or 30.0), 45.0))
        deadline = asyncio.get_running_loop().time() + timeout
        # Duraklatılmış koşu: devam (resume) veya iptal gelene kadar bekle
        if run.paused and run.status != "WAITING_APPROVAL":
            while run.paused and not run.is_terminal:
                if asyncio.get_running_loop().time() >= deadline:
                    return self._paused_response(run)
                await asyncio.sleep(0.5)
                self._touch(run)
            if run.is_terminal:
                return {"status": "CANCELLED" if run.status == "CANCELLED" else "APPROVED", "run_id": run.run_id, "run_status": run.status,
                        "next": "RUN_COMPLETE", "message": tx("Koşu sonlandı.")}
            return {"status": "RESUMED", "run_id": run.run_id, "run_status": run.status, "next": "STEP",
                    "next_order": run.current_step.order if run.current_step else None, "message": tx("Devam edildi; `get_next_step` ile sürdür.")}
        while run.status == "WAITING_APPROVAL":
            if asyncio.get_running_loop().time() >= deadline:
                return {"status": "STILL_WAITING", "run_id": run.run_id, "order": run.current_step.order if run.current_step else None,
                        "message": tx("Onay henüz verilmedi; tekrar `wait_for_approval` çağır.")}
            await asyncio.sleep(0.5)
            self._touch(run)
        if run.last_decision == "REVISE" and run.status == "ACTIVE":
            run.last_decision = ""
            return {"status": "REVISE", "run_id": run.run_id, "run_status": run.status, "next": "STEP",
                    "next_order": run.current_step.order if run.current_step else None,
                    "message": tx("Yönetici revize istedi: aynı adımı `get_next_step` ile yeniden al ve 'Yönetici notları' bölümündeki geri bildirime göre yeniden üret.")}
        if run.status == "CANCELLED":
            return {"status": "CANCELLED", "run_id": run.run_id, "message": tx("Koşu iptal edildi.")}
        if run.status in ("COMPLETED",):
            return {"status": "APPROVED", "run_id": run.run_id, "run_status": run.status, "next": "RUN_COMPLETE", "message": tx("Onaylandı; koşu tamamlandı.")}
        if run.status == "FAILED":
            return {"status": "REJECTED", "run_id": run.run_id, "run_status": run.status, "message": tx("Onay alınamadı; koşu durdu.")}
        return {"status": "APPROVED", "run_id": run.run_id, "run_status": run.status, "next": "STEP",
                "next_order": run.current_step.order if run.current_step else None, "message": tx("Onaylandı; `get_next_step` ile devam et.")}

    async def cancel(self, run: PipelineRun, reason: str = "user"):
        await P.cancel_run(self.hub, run, reason)

    # ------------------------------------------------------------------
    # Terk edilmiş koşu süpürücüsü
    # ------------------------------------------------------------------
    def start_sweeper(self, interval_s: float = 60.0):
        if self._sweeper is None or self._sweeper.done():
            self._sweeper = asyncio.create_task(self._sweep_loop(interval_s), name="run-abandon-sweeper")

    async def stop_sweeper(self):
        if self._sweeper and not self._sweeper.done():
            self._sweeper.cancel()
            try:
                await self._sweeper
            except (asyncio.CancelledError, Exception):
                pass

    async def _sweep_loop(self, interval_s: float):
        while True:
            await asyncio.sleep(interval_s)
            try:
                await self.sweep_once()
            except Exception:
                continue

    async def sweep_once(self, now: Optional[datetime] = None) -> int:
        now = now or datetime.now(timezone.utc)
        count = 0
        for run in list(self.hub.runs.values()):
            if run.engine != "mcp_client" or run.status not in ("ACTIVE", "WAITING_APPROVAL"):
                continue
            try:
                last = datetime.fromisoformat(run.last_seen)
            except Exception:
                continue
            timeout = max(RUN_HEARTBEAT_TIMEOUT_S, DRV.abandon_after_s(self.hub)) if run.mode == "sprint" else RUN_HEARTBEAT_TIMEOUT_S
            if (now - last).total_seconds() > timeout:
                if run.approval_token and run.status == "WAITING_APPROVAL":
                    # Onay bekleyen koşu terk edilmiş sayılmaz; kullanıcı hâlâ onaylayabilir
                    continue
                run.finish("ABANDONED", reason="heartbeat-timeout")
                DRV.release_lease(self.hub, run.run_id)
                if self.hub.active_run_id == run.run_id:
                    self.hub.active_run_id = None
                await P.publish_run(self.hub, run)
                count += 1
        return count
