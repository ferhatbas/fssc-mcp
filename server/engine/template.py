"""
TemplateEngine — süreç içi, çevrimdışı şablon motoru.

Her adım için işleyicinin hazır A2A zarfını üretir ve pipeline çekirdeğinden geçirir.
Onay gerektiren adımlarda onay kapısını (ApprovalGate) kendisi bekler.
"""

from __future__ import annotations

import asyncio
from typing import Dict, Optional

from ..approval import DEFAULT_STEP_APPROVAL_TIMEOUT_S
from ..runs import PipelineRun
from .. import pipeline as P
from ..tech_requirements import dry_run_enabled
from ..i18n import translate as tx, N_


class TemplateEngine:
    name = "template"

    def __init__(self, hub):
        self.hub = hub
        self._tasks: Dict[str, asyncio.Task] = {}

    async def start(self, run: PipelineRun) -> asyncio.Task:
        run.status = "ACTIVE"
        run.client_name = "template-engine"
        self.hub.active_run_id = run.run_id
        await P.publish_run(self.hub, run)
        task = asyncio.create_task(self._loop(run), name=f"template-run-{run.run_id}")
        self._tasks[run.run_id] = task
        return task

    async def _loop(self, run: PipelineRun):
        hub = self.hub
        try:
            while not run.is_terminal:
                while run.paused and not run.is_terminal:  # kullanıcı duraklattı
                    await asyncio.sleep(0.5)
                if run.is_terminal:
                    break
                record = run.current_step
                if record is None:
                    await P.finalize_run(hub, run, status="COMPLETED")
                    break
                # Teknoloji kapısı: yönetici onayı gelene dek döner. Yalnızca FSSC_DRY_RUN=1 ile (bu motorda) yönetici simüle edilir.
                while not run.is_terminal:
                    token = await P.ensure_decisions(hub, run, record)
                    if not token:
                        break
                    if dry_run_enabled():
                        await hub.dry_run_approve_tech()
                    # Karar bekleme öncesinde verildiyse (deneme bayrağı) gate.wait yeni bir Future açıp kararı kaybeder: önce bak
                    decision = hub.gate.peek(token) or await hub.gate.wait(token, timeout=DEFAULT_STEP_APPROVAL_TIMEOUT_S or None)
                    if decision is None:
                        decision = "TIMEOUT"
                        hub.gate.cancel(token)
                    await P.apply_approval_decision(hub, run, decision)
                if run.is_terminal:
                    break
                handler = P.handler_for(hub, record)
                if handler.server_side:
                    outcome = await P.run_server_step(hub, run)
                else:
                    await P.prepare_step(hub, run)
                    ctx = P.make_context(hub, run, record)
                    envelope = handler.template_output(ctx)
                    outcome = await P.finish_step(hub, run, envelope)

                if outcome.status == "WAITING_APPROVAL" and outcome.approval_token:
                    if dry_run_enabled() and (hub.pending_step_approval or {}).get("kind") == "questions":
                        # YALNIZCA deneme (FSSC_DRY_RUN=1 + şablon motoru): engelleyici sorulara yönetici yerine önerilen cevap verilir; kayıtta DRY_RUN görünür
                        from .. import meetings as M
                        for q in M.open_blocking(hub):
                            await M.answer_question(hub, q["id"], q["recommended"], by="DRY_RUN")
                    decision = hub.gate.peek(outcome.approval_token) or await hub.gate.wait(outcome.approval_token, timeout=DEFAULT_STEP_APPROVAL_TIMEOUT_S or None)
                    if decision is None:
                        decision = "TIMEOUT"
                        hub.gate.cancel(outcome.approval_token)
                    await P.apply_approval_decision(hub, run, decision)
                elif outcome.status == "RUN_COMPLETE":
                    break
        except asyncio.CancelledError:
            await P.cancel_run(hub, run, reason="task-cancelled")
            raise
        except Exception as e:  # noqa: BLE001
            record = run.current_step
            if record is not None:
                record.status = "FAILED"
                record.error = str(e)
            await hub.record_event(
                trace_id=run.run_id, from_agent="PM", to_agent="PM", action="PIPELINE_FAILED", status="FAILED",
                payload={"error": str(e), "order": record.order if record else None},
                friendly_dialogue=tx("Pipeline beklenmedik bir hatayla durdu: {error}", error=str(e)[:160]),
            )
            await P.finalize_run(hub, run, status="FAILED", reason=str(e)[:200])
        finally:
            self._tasks.pop(run.run_id, None)

    async def cancel(self, run: PipelineRun, reason: str = "user"):
        task = self._tasks.get(run.run_id)
        if task and not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        else:
            await P.cancel_run(self.hub, run, reason)
