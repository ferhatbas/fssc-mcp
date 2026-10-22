"""
Koşu API'si (LocalRunsApi) — REST uçları ve MCP araçlarının ortak, motor bağımsız cephesi.

Tüm metodlar JSON'a çevrilebilir sözlükler döner; hata durumunda `RunsApiError` fırlatır
(REST katmanı HTTP koduna, MCP katmanı ToolError'a çevirir).
"""

from __future__ import annotations

import asyncio
import os
import time
from typing import Any, Dict, List, Optional

from ..runs import PipelineRun, build_run, ENGINES
from ..steps import SERVER_SIDE_ORDERS
from .. import pipeline as P
from .. import mcp_activity as MA
from .. import claude_log as CL
from ..i18n import translate as tx, N_
from .mcp_client import McpClientEngine
from .template import TemplateEngine
from .errors import RunsApiError  # noqa: F401  (geriye dönük: `from .api import RunsApiError`)


class LocalRunsApi:
    def __init__(self, hub):
        self.hub = hub
        self.template = TemplateEngine(hub)
        self.mcp = McpClientEngine(hub)

    # ------------------------------------------------------------------
    # Yardımcılar
    # ------------------------------------------------------------------
    def _run(self, run_id: str) -> PipelineRun:
        run = self.hub.runs.get(run_id)
        if run is None:
            raise RunsApiError(tx("Koşu bulunamadı: {id}", id=run_id), 404)
        return run

    def _lock(self, run_id: str) -> asyncio.Lock:
        """G3: aynı koşuya eşzamanlı next_step/submit çağrıları sıralanır (çift teslim yarışı olmaz; ikinci teslim 'sıra uyuşmuyor' alır)."""
        locks = self.__dict__.setdefault("_locks", {})
        lock = locks.get(run_id)
        if lock is None:
            lock = asyncio.Lock()
            locks[run_id] = lock
        return lock

    def _resolve_project(self, project_id: Optional[str]) -> Dict[str, Any]:
        pid = project_id or self.hub.active_project_id
        proj = self.hub.projects.get(pid)
        if proj is None:
            # Ad ile de eşleştir (kullanıcı 'demo-app projesi' der)
            for p in self.hub.projects.values():
                if str(p.get("name", "")).lower() == str(pid).lower():
                    proj = p
                    break
        if proj is None:
            raise RunsApiError(tx("Proje bulunamadı: {id}", id=pid), 404, known_projects=list(self.hub.projects.keys()))
        return proj

    async def client_seen(self, client: Optional[Dict[str, str]]):
        if client and client.get("name"):
            await self.hub.mark_client_seen(client["name"], client.get("version", ""))

    # ------------------------------------------------------------------
    # Koşu yaşam döngüsü
    # ------------------------------------------------------------------
    async def start_run(
        self,
        project_id: Optional[str] = None,
        steps: Optional[List[Any]] = None,
        engine: Optional[str] = None,
        custom_prompt: str = "",
        step_by_step: Optional[bool] = None,
        client: Optional[Dict[str, str]] = None,
        force_new: bool = False,
        project_dir: Optional[str] = None,
        _discard_confirmed: bool = False,
    ) -> Dict[str, Any]:
        hub = self.hub
        await self.client_seen(client)
        proj = self._resolve_project(project_id)
        pid = proj["id"]

        # Koşu, aktif proje bağlamında çalışır (Jira/olaylar aktif projeye yazılır)
        if pid != hub.active_project_id:
            await hub.switch_project(pid)

        # Sprint kipi: sabit adım listesi yoktur; seçim verilmediyse yükleme tabanlı dinamik koşu başlar (F3)
        from .. import sprint as SP
        if not steps and SP.enabled(hub):
            return await self.start_sprint_run(project_id=pid, engine=engine, custom_prompt=custom_prompt, step_by_step=step_by_step,
                                               client=client, force_new=force_new, project_dir=project_dir, _discard_confirmed=_discard_confirmed)

        if force_new:
            self._guard_discard(pid, "legacy", _discard_confirmed)

        existing = hub.active_run_for(pid)
        if existing is not None:
            if force_new:
                await self.cancel_run(existing.run_id, reason="force_new")
            else:
                existing.touch()
                return {"status": "EXISTING", "run": existing.to_dict(),
                        "message": tx("Bu proje için zaten bekleyen/aktif bir koşu var; aynı koşu döndürüldü.")}

        engine = (engine or hub.get_settings().get("execution_engine") or "mcp_client").lower()
        if engine not in ENGINES:
            raise RunsApiError(tx("Bilinmeyen motor: {engine}", engine=engine), 400, engines=list(ENGINES))
        # Açıkça verilmediyse hub'ın adım-adım bayrağı (onay modundan türetilir; AUTO_ALL bunu artık değiştirmez)
        sbs = hub.step_by_step_mode if step_by_step is None else bool(step_by_step)
        if sbs:
            hub.step_by_step_mode = True
            hub.auto_proceed_all = False
            hub.auto_proceed_run_id = None

        run = build_run(
            project_id=pid,
            project_dir=os.path.abspath(project_dir) if project_dir else proj.get("path", hub.default_project_path),
            issues=hub.get_jira_issues(),
            selected=steps or [],
            engine=engine,
            custom_prompt=custom_prompt or "",
            step_by_step=sbs,
            server_side_orders=SERVER_SIDE_ORDERS,
        )
        if not run.steps:
            raise RunsApiError(tx("Seçime uyan Jira maddesi bulunamadı."), 400)
        if engine == "mcp_client":
            from .. import driver as DRV
            if force_new:
                for old in DRV.abandoned_runs(hub, pid, mode="legacy"):
                    old.finish("CANCELLED", reason="force_new")
                    await P.publish_run(hub, old)
            else:
                want = {s.order for s in run.steps if s.kind == "phase"}
                resumed = await DRV.resume_abandoned(hub, self, pid, mode="legacy", client=client,
                                                     accept=lambda r: want <= {s.order for s in r.steps if s.kind == "phase"})
                if resumed is not None:
                    return {"status": "RESUMED", "run": resumed.to_dict(), "message": self._resumed_message(resumed)}
        if client:
            run.client_name = client.get("name", "")
            run.client_version = client.get("version", "")
        hub.register_run(run)

        if engine == "template":
            await self.template.start(run)
            message = tx("Şablon motoru koşuyu başlattı.")
        else:
            run.status = "QUEUED"
            hub.active_run_id = run.run_id
            await P.publish_run(hub, run)
            message = tx("Koşu kuyruğa alındı; MCP istemcisi (Claude Desktop) `get_next_step` çağırınca başlar.")
        if SP.enabled(hub):
            # Sprint kipi açıkken sabit adım listesi yalnızca API ile (kuru koşu, tek madde) kullanılabilir; pano düğmesi gizlidir
            message = f"{message} | " + tx("UYARI: sprint kipi açık; sabit adım listesiyle başlatılan bu koşu sprint akışını (yükleme → plan → taahhüt) atlar.")
        return {"status": "STARTED", "run": run.to_dict(), "message": message}

    async def start_sprint_run(
        self,
        project_id: Optional[str] = None,
        engine: Optional[str] = None,
        custom_prompt: str = "",
        step_by_step: Optional[bool] = None,
        client: Optional[Dict[str, str]] = None,
        force_new: bool = False,
        project_dir: Optional[str] = None,
        with_intake: Optional[bool] = None,
        _discard_confirmed: bool = False,
    ) -> Dict[str, Any]:
        """Sprint kipi koşusu: bekleyen yüklemeleri değerlendirir (PM → ARCHITECT) ve sprint planıyla sürer. Tek koşu kuralı geçerlidir.
        Terk edilmiş koşu varsa yenisi kurulmaz, o kaldığı adımdan sürer (`force_new` ile baştan başlanır). `with_intake` verilmezse
        değerlendirme yalnızca bekleyen yükleme varken ya da iş planı henüz yokken eklenir."""
        from .. import sprint as SP
        from .. import sprint_flow as SPF
        hub = self.hub
        await self.client_seen(client)
        proj = self._resolve_project(project_id)
        pid = proj["id"]
        if pid != hub.active_project_id:
            await hub.switch_project(pid)
        await SPF.resume_if_budget_allows(hub)       # bütçe artırıldıysa PAUSED proje yeni koşuyla sürer
        if force_new:
            self._guard_discard(pid, "sprint", _discard_confirmed)
        existing = hub.active_run_for(pid)
        if existing is not None:
            if force_new:
                await self.cancel_run(existing.run_id, reason="force_new")
            else:
                existing.touch()
                return {"status": "EXISTING", "run": existing.to_dict(),
                        "message": tx("Bu proje için zaten bekleyen/aktif bir koşu var; yeni yükleme bekleyen değerlendirmeye eklendi.")}
        engine = (engine or hub.get_settings().get("execution_engine") or "mcp_client").lower()
        if engine not in ENGINES:
            raise RunsApiError(tx("Bilinmeyen motor: {engine}", engine=engine), 400, engines=list(ENGINES))
        sbs = hub.step_by_step_mode if step_by_step is None else bool(step_by_step)
        if sbs:
            hub.step_by_step_mode = True
            hub.auto_proceed_all = False
            hub.auto_proceed_run_id = None
        if engine == "mcp_client":
            from .. import driver as DRV
            if force_new:
                for old in DRV.abandoned_runs(hub, pid, mode="sprint"):      # "baştan başlat": terk edilmişler de bırakılır
                    old.finish("CANCELLED", reason="force_new")
                    await P.publish_run(hub, old)
            else:
                resumed = await DRV.resume_abandoned(hub, self, pid, mode="sprint", client=client)
                if resumed is not None:
                    return {"status": "RESUMED", "run": resumed.to_dict(), "message": self._resumed_message(resumed)}
        pending = SP.ensure_state(hub).get("pending_intake") or {}
        if with_intake is None:
            with_intake = bool(pending) or not SP.existing_stories(hub)
        run = SPF.build_sprint_run(hub, pid, os.path.abspath(project_dir) if project_dir else proj.get("path", hub.default_project_path), engine, sbs,
                                   with_intake=with_intake, spec_ids=pending.get("spec_ids", []), custom_prompt=custom_prompt)
        if client:
            run.client_name = client.get("name", "")
            run.client_version = client.get("version", "")
        hub.register_run(run)
        await hub.broadcast({"type": "INTAKE_STARTED", "run_id": run.run_id, "spec_ids": run.intake_spec_ids, "with_intake": with_intake})
        if engine == "template":
            await self.template.start(run)
            message = tx("Şablon motoru sprint koşusunu başlattı.")
        else:
            run.status = "QUEUED"
            hub.active_run_id = run.run_id
            await P.publish_run(hub, run)
            message = tx("Sprint koşusu kuyruğa alındı; MCP istemcisi `get_next_step` çağırınca başlar.")
        return {"status": "STARTED", "run": run.to_dict(), "message": message}

    # ------------------------------------------------------------------
    # Claude Desktop sürücüsü (F5): runner araçları
    # ------------------------------------------------------------------
    async def claim_work(self, client: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        from .. import driver as DRV
        await self.client_seen(client)
        return await DRV.claim_work(self.hub, self, client)

    async def get_activity(self, limit: int = 30) -> Dict[str, Any]:
        from .. import display as DISP
        return DISP.activity_feed(self.hub, limit)

    async def get_runner_schedule(self) -> Dict[str, Any]:
        from .. import driver as DRV
        return DRV.runner_schedule(self.hub)

    async def get_sprint_state(self) -> Dict[str, Any]:
        from .. import driver as DRV, meetings as M, sprint as SP
        st = SP.ensure_state(self.hub)
        cur = SP.get_sprint(self.hub, st.get("current_sprint")) if st.get("current_sprint") else None
        run = self.hub.active_run_for(self.hub.active_project_id)
        usage = DRV.sprint_usage(self.hub, run, cur["sprint_number"]) if (cur and run) else None
        return {"project_status": st["project_status"], "current_sprint": cur, "usage": usage, "budget": DRV.budget(self.hub), "level": M.current_level(self.hub),
                "sprints": [{k: s.get(k) for k in ("sprint_number", "status", "goal", "metrics", "carried_over", "blocked")} for s in st["sprints"]],
                "pending_intake": st.get("pending_intake"), "runner": DRV.runner_status(self.hub)}

    async def list_questions(self, status: Optional[str] = None) -> Dict[str, Any]:
        from .. import meetings as M
        await M.expire_questions(self.hub)
        qs = [{k: v for k, v in q.items() if k != "adr_draft"} for q in M.all_questions(self.hub)]
        if status:
            qs = [q for q in qs if q.get("status") == status.upper()]
        return {"questions": qs, "open_blocking": [q["id"] for q in M.open_blocking(self.hub)]}

    async def answer_question(self, question_id: str, answer: str) -> Dict[str, Any]:
        """Yönetici cevabı (yalnızca engelleyici OLMAYAN sorular). Teknoloji/dış eylem sorusu dashboard'dan cevaplanır: bir ajan yöneticinin yerine geçemez."""
        from .. import meetings as M
        q = next((x for x in M.all_questions(self.hub) if x["id"] == question_id), None)
        if q is None:
            raise RunsApiError(tx("Soru bulunamadı: {id}", id=question_id), 404)
        if q.get("blocking") or q.get("category") in M.BLOCKING_CATEGORIES:
            raise RunsApiError(tx("Engelleyici soru (TECHNOLOGY/EXTERNAL_ACTION) MCP aracıyla cevaplanamaz; yönetici dashboard'dan cevaplar."), 403)
        try:
            res = await M.answer_question(self.hub, question_id, answer, by="MANAGER")
        except (ValueError, KeyError) as e:
            raise RunsApiError(str(e), 400)
        return {"status": "OK", "question": {k: v for k, v in res.items() if k != "adr_draft"}}

    async def get_tech_requirements(self) -> Dict[str, Any]:
        req = await self.hub.ensure_tech_requirements()
        return {"tech_requirements": req, "approved": self.hub.tech_requirements_approved()}

    async def add_manager_input(self, text: str, title: str = "Yönetici girdisi", client_name: str = "Yönetici", urgent: bool = False,
                                client: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        """Yöneticinin sohbetten kasaya not bırakması: yükleme sayılır, değerlendirmeyi kuyruğa alır ve işi başlatır (§11.2)."""
        from .. import sprint as SP
        await self.client_seen(client)
        text = str(text or "").strip()
        if not text:
            raise RunsApiError(tx("Not boş olamaz."), 400)
        title = tx("Yönetici girdisi") if title == "Yönetici girdisi" else title       # çağıranlar Türkçe varsayılanı geçer: proje diline çevrilir
        client_name = tx("Yönetici") if client_name == "Yönetici" else client_name
        spec = await self.hub.add_uploaded_spec({"title": title or tx("Yönetici girdisi"), "client_name": client_name or tx("Yönetici"), "meeting_notes": text, "files": []})
        if not SP.enabled(self.hub):
            return {"status": "STORED", "spec": spec, "message": tx("Not kasaya eklendi (sprint kipi kapalı: iş otomatik başlamaz).")}
        pending = await self.hub.queue_intake(spec["id"])
        from .. import sprint_flow as SPF
        task = await SPF.create_manager_task(self.hub, text, spec["id"], urgent=bool(urgent))        # kısa girdi doğrudan iş olur (panoda hemen görünür)
        started = await self.start_sprint_run(project_id=self.hub.active_project_id, client=client)
        adhoc = None
        if urgent:
            from .. import sprint_flow as SPF
            adhoc = await SPF.schedule_adhoc(self.hub, text, spec["id"])     # G3 (§8.4): süren sprintte acil girdi toplantısı
        return {"status": "QUEUED", "spec": spec, "pending_intake": pending, "task": task, "run_status": started.get("status"),
                "run_id": (started.get("run") or {}).get("run_id"), "urgent": bool(urgent), "adhoc": adhoc,
                "message": ((tx("Not kasaya eklendi; süren sprintte acil girdi (adhoc) toplantısı açıldı: başlamamış işler yer değiştirebilir.")
                             if adhoc else tx("Not kasaya eklendi; değerlendirme kuyruğa alındı."))
                            + (tx(" Backlog'a iş açıldı: {key} ({title}) → {mode}.", key=task['key'], title=task['title'],
                                  mode=(task.get('expedite') or {}).get('mode') or tx('sıradaki planlama')) if task and not task.get("existing")
                               else (tx(" Benzer açık iş zaten var: {key}.", key=task['key']) if task else "")))}

    async def next_step(self, run_id: str, client: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        async with self._lock(run_id):
            return await self._next_step_unlocked(run_id, client)

    async def _next_step_unlocked(self, run_id: str, client: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        run = self._run(run_id)
        await self.client_seen(client)
        if run.engine != "mcp_client":
            raise RunsApiError(tx("Bu koşu şablon motoru tarafından yürütülüyor; adım çekilemez."), 409)
        if run.project_id != self.hub.active_project_id:
            await self.hub.switch_project(run.project_id)
        res = await self.mcp.next_step(run, client)
        await MA.log_call(self.hub, "get_next_step", run, client, result=res.get("status"), order=res.get("order"),
                          agent_id=res.get("agent_id"), title=(res.get("title") or res.get("message") or "")[:120])
        # G2: sunucunun Claude'a verdiği TAM yanıt (rol promptu, bağlam, sözleşme, display_md) günlüğe
        await CL.record(self.hub, direction="to_claude", tool="get_next_step", run_id=run.run_id, order=res.get("order"), agent_id=res.get("agent_id"),
                        kind=res.get("kind"), client=client, status=res.get("status"), result=res,
                        collapse=res.get("status") in ("WAITING_APPROVAL", "PAUSED", "BLOCKED", "SESSION_BOUNDARY"))
        return res

    async def submit_result(self, run_id: str, order: int, result_json: Any, tokens_in: int = 0, tokens_out: int = 0,
                            client: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        async with self._lock(run_id):
            return await self._submit_result_unlocked(run_id, order, result_json, tokens_in, tokens_out, client)

    async def _submit_result_unlocked(self, run_id: str, order: int, result_json: Any, tokens_in: int = 0, tokens_out: int = 0,
                                      client: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        run = self._run(run_id)
        await self.client_seen(client)
        if run.engine != "mcp_client":
            raise RunsApiError(tx("Bu koşu şablon motoru tarafından yürütülüyor."), 409)
        if run.project_id != self.hub.active_project_id:
            await self.hub.switch_project(run.project_id)
        t0 = time.time()
        res = await self.mcp.submit(run, int(order), result_json, tokens_in, tokens_out, client)
        verification = (res.get("verification") or {}).get("status")
        await MA.log_call(self.hub, "submit_step_result", run, client, result=res.get("status"), order=int(order),
                          title=" · ".join(x for x in (tx("doğrulama {v}", v=verification) if verification else "", str(res.get("message") or "")[:100]) if x))
        # G2: Claude'un gönderdiği HAM teslim ve sunucunun tam yanıtı günlüğe
        step = run.current_step
        await CL.record(self.hub, direction="to_server", tool="submit_step_result", run_id=run.run_id, order=int(order),
                        agent_id=(step.role if step else None), kind=(step.kind if step else None), client=client, status=res.get("status"),
                        duration_ms=int((time.time() - t0) * 1000),
                        args={"order": int(order), "tokens_in": tokens_in, "tokens_out": tokens_out, "result_json": result_json}, result=res)
        return res

    async def wait_approval(self, run_id: str, timeout_s: float = 30.0, client: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        await self.client_seen(client)
        if str(run_id).upper().startswith("DELIB-"):
            return await self._wait_plan_choice(run_id, timeout_s)
        run = self._run(run_id)
        if run.engine == "template":
            # Şablon motoru onayı kendisi bekler; istemciye yalnızca durum bildir
            return {"status": run.status, "run_id": run.run_id, "message": tx("Şablon motoru koşusu.")}
        res = await self.mcp.poll_approval(run, timeout_s, client)
        await MA.log_call(self.hub, "wait_for_approval", run, client, result=res.get("status"), order=res.get("order") or res.get("next_order"))
        await CL.record(self.hub, direction="to_server", tool="wait_for_approval", run_id=run.run_id, order=res.get("order") or res.get("next_order"),
                        client=client, status=res.get("status"), args={"timeout_s": timeout_s}, result=res, collapse=True)
        return res

    async def _wait_plan_choice(self, session_id: str, timeout_s: float) -> Dict[str, Any]:
        engine = self.hub.deliberation_engine
        session = engine.active_session
        if session is None or session.session_id != session_id:
            raise RunsApiError(tx("Müzakere oturumu bulunamadı: {id}", id=session_id), 404)
        if session.status == "CONSENSUS_REACHED":
            return {"status": "APPROVED", "run_id": session_id, "next": "PLAN_CHOSEN", "plan_id": session.chosen_plan_id,
                    "message": tx("Yönetici onayladı: {plan}. Adım 2'de bu planı kullan.", plan=(session.consensus_summary or {}).get('chosen_plan'))}
        if session.status == "ACTIVE" and session.round > 1:
            return {"status": "REVISE", "run_id": session_id, "round": session.round, "feedback": (session.rounds[-1] or {}).get("feedback"),
                    "message": tx("Yönetici revize istedi: geri bildirimi oku, aynı oturumda `deliberation_turn` ile yeni turlar ekle ve `close_deliberation` ile yeniden öneri sun.")}
        if session.status not in ("AWAITING_APPROVAL", "AWAITING_PLAN_CHOICE") or not session.approval_token:
            return {"status": "STILL_WAITING", "run_id": session_id, "message": tx("Müzakere henüz kapatılmadı.")}
        decision = await self.hub.gate.wait(session.approval_token, timeout=max(1.0, min(float(timeout_s or 30), 45.0)))
        if decision is None:
            return {"status": "STILL_WAITING", "run_id": session_id, "message": tx("Yönetici henüz karar vermedi (onay / revize); tekrar `wait_for_approval` çağır.")}
        if decision == "REVISE":
            return {"status": "REVISE", "run_id": session_id, "round": session.round, "feedback": (session.rounds[-1] or {}).get("feedback"),
                    "message": tx("Yönetici revize istedi: geri bildirimi oku, aynı oturumda `deliberation_turn` ile yeni turlar ekle ve `close_deliberation` ile yeniden öneri sun.")}
        return {"status": "APPROVED", "run_id": session_id, "next": "PLAN_CHOSEN", "plan_id": decision,
                "message": tx("Yönetici onayladı: {plan}. Adım 2'de bu planı kullan.", plan=decision)}

    async def report_thinking(self, run_id: str, agent_id: str, text: str, what_doing: str = "", what_next: str = "",
                              client: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        run = self._run(run_id)
        await self.client_seen(client)
        run.touch()
        agent_id = (agent_id or (run.current_step.role if run.current_step else "PM")).upper()
        await self.hub.broadcast_thinking(run.run_id, agent_id, text, what_doing, what_next,
                                          order=run.current_step.order if run.current_step else None)
        await MA.log_call(self.hub, "report_thinking", run, client, result="OK", agent_id=agent_id,
                          order=run.current_step.order if run.current_step else None, title=str(text)[:120],
                          text=str(text)[:4000], what_doing=str(what_doing or "")[:500] or None, what_next=str(what_next or "")[:500] or None)
        await CL.record(self.hub, direction="to_server", tool="report_thinking", run_id=run.run_id, order=run.current_step.order if run.current_step else None,
                        agent_id=agent_id, kind=(run.current_step.kind if run.current_step else None), client=client, status="OK",
                        text=str(text), args={"what_doing": what_doing, "what_next": what_next})
        return {"status": "OK", "run_id": run.run_id, "agent_id": agent_id}

    async def pause_run(self, run_id: str, reason: str = "user") -> Dict[str, Any]:
        """Koşuyu duraklatır: istemciye yeni adım verilmez; süren adımın teslimi kabul edilir, sonra bekler."""
        run = self._run(run_id)
        if run.is_terminal:
            raise RunsApiError(tx("Koşu zaten sonlanmış: {status}", status=run.status), 409)
        run.paused, run.pause_reason = True, reason
        run.touch()
        await P.publish_run(self.hub, run)
        await self.hub.broadcast({"type": "RUN_PAUSED", "run_id": run.run_id, "reason": reason})
        self.hub.mark_dirty()
        return {"status": "PAUSED", "run": run.to_dict()}

    async def skip_step(self, run_id: str, order: int, reason: str = "") -> Dict[str, Any]:
        """Yönetici müdahalesi: henüz teslim edilmemiş bir adımı (bekleyen ya da süren) atlar. Jira maddesi BACKLOG'a döner (silinmez);
        adım süren adımsa imleç sonraki adıma geçer. Teslim edilmiş (DONE) adım atlanamaz."""
        run = self._run(run_id)
        if run.is_terminal:
            raise RunsApiError(tx("Koşu zaten sonlanmış: {status}", status=run.status), 409)
        rec = next((x for x in run.steps if x.order == int(order) and x.status in ("PENDING", "ACTIVE", "WAITING_APPROVAL")), None)
        if rec is None:
            raise RunsApiError(tx("Atlanacak adım bulunamadı (yok ya da zaten teslim edilmiş): #{order}", order=order), 404)
        was_current = run.current_step is rec
        rec.status = "SKIPPED"
        rec.summary = tx("Yönetici adımı atladı.") + (f" {reason}" if reason else "")
        if rec.issue_id in self.hub.jira_issues and rec.kind not in ("plan", "close", "meeting", "review"):
            await self.hub.update_jira_issue(rec.issue_id, {"status": "BACKLOG", "audit_action": "STEP_SKIPPED", "audit_notes": rec.summary[:280]})
        if was_current:
            run.advance()
        run.touch()
        await P.publish_run(self.hub, run)
        self.hub.mark_dirty()
        return {"status": "SKIPPED", "order": rec.order, "next_order": run.current_step.order if run.current_step else None, "run": run.to_dict()}

    @staticmethod
    def _resumed_message(run: PipelineRun) -> str:
        prog = run.to_dict()["progress"]
        return (tx("Koşu {run} canlandırıldı (adım {done}/{total}); yeni koşu kurulmadı. Sunucu iş itmez: adımları bir Claude oturumu çekene kadar ilerlemez. ",
                   run=run.run_id, done=prog['done'], total=prog['total'])
                + tx("Claude'a şunu yaz: \"{p} projesi için pipeline'ı çalıştır (kaldığı yerden: {r})\". Baştan başlamak için force_new=true.")
                ).replace("{p}", str(run.project_id)).replace("{r}", run.run_id)

    async def resume_run(self, run_id: str) -> Dict[str, Any]:
        run = self._run(run_id)
        if run.status == "ABANDONED":
            # Terk edilmiş koşu (sunucu yeniden başladı / istemci koptu): kaldığı adımdan canlanır; diğer terk edilmişler iptal olur
            from .. import driver as DRV
            await DRV.resume_abandoned(self.hub, self, run.project_id, mode=run.mode, prefer=run)
            return {"status": "RESUMED", "run": run.to_dict(), "message": self._resumed_message(run)}
        if run.is_terminal:
            raise RunsApiError(tx("Koşu zaten sonlanmış: {status}", status=run.status), 409)
        run.paused, run.pause_reason = False, ""
        run.touch()
        await P.publish_run(self.hub, run)
        await self.hub.broadcast({"type": "RUN_RESUMED", "run_id": run.run_id})
        self.hub.mark_dirty()
        return {"status": "RESUMED", "run": run.to_dict()}

    def _guard_discard(self, pid: str, mode: str, confirmed: bool) -> None:
        """`force_new` ilerlemiş (en az bir adımı biten) koşuyu çöpe atar. Uzun süre önce başlamış bir koşunun yanlışlıkla/yapay zekâ tarafından silinmesini önlemek için
        bu yalnızca panodaki iki aşamalı onayla (proje adını yazma → `restart_fresh`) yapılır; MCP aracı ve düz REST çağrısı reddedilir (409)."""
        if confirmed:
            return
        from .. import driver as DRV
        victims = [r for r in [self.hub.active_run_for(pid), *DRV.abandoned_runs(self.hub, pid, mode=mode)] if r is not None]
        worst = max(victims, key=lambda r: DRV._done_steps(r), default=None)
        if worst is not None and DRV._done_steps(worst) > 0:
            raise RunsApiError(
                tx("Baştan başlatma {run} koşusunun ilerlemesini ({done}/{total} adım) çöpe atar. Bu yalnızca panoda, proje adı yazılarak "
                   "onaylanır; kaldığı yerden sürdürmek için force_new kullanmayın.", run=worst.run_id, done=DRV._done_steps(worst), total=len(worst.steps)), 409, code="FORCE_NEW_NEEDS_CONFIRMATION", run_id=worst.run_id,
                done_steps=DRV._done_steps(worst), total_steps=len(worst.steps))

    async def restart_fresh(self, run_id: str, confirm_name: str) -> Dict[str, Any]:
        """Panodaki iki aşamalı onaydan sonra: koşuyu bırakır ve yenisini kurar. `confirm_name` koşunun projesinin adıyla birebir eşleşmelidir."""
        run = self._run(run_id)
        proj = self.hub.projects.get(run.project_id) or {}
        name = str(proj.get("name") or run.project_id)
        if str(confirm_name or "").strip() != name:
            raise RunsApiError(tx("Onay için proje adını aynen yazın."), 400, code="CONFIRM_NAME_MISMATCH")
        if run.status == "ABANDONED" or not run.is_terminal:
            await self.cancel_run(run_id, reason="restart-fresh")
        return await self.start_run(project_id=run.project_id, steps=[], engine=run.engine, force_new=True, _discard_confirmed=True)

    async def cancel_run(self, run_id: str, reason: str = "user") -> Dict[str, Any]:
        run = self._run(run_id)
        if run.status == "ABANDONED":
            # Terk edilmiş koşu açıkça bırakılır: bir daha canlandırılamaz (get_next_step / claim_work onu seçmez)
            await P.finalize_run(self.hub, run, status="CANCELLED", reason=reason)
            return {"status": "CANCELLED", "run": run.to_dict()}
        if run.is_terminal:
            return {"status": run.status, "run": run.to_dict(), "message": tx("Koşu zaten sonlanmış.")}
        if run.engine == "template":
            await self.template.cancel(run, reason)
        else:
            await self.mcp.cancel(run, reason)
        return {"status": "CANCELLED", "run": run.to_dict()}

    async def list_runs(self, project_id: Optional[str] = None, limit: int = 50) -> Dict[str, Any]:
        runs = [r for r in self.hub.runs.values() if not project_id or r.project_id == project_id]
        runs.sort(key=lambda r: r.created_at, reverse=True)
        return {"runs": [r.to_dict() for r in runs[:limit]], "active_run_id": self.hub.active_run_id}

    async def get_run(self, run_id: str) -> Dict[str, Any]:
        return {"run": self._run(run_id).to_dict()}

    # ------------------------------------------------------------------
    # Müzakere (Deliberation) — MCP istemcisi turları kendisi üretir
    # ------------------------------------------------------------------
    async def open_deliberation(self, spec_id: str = "", title: str = "", client: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        await self.client_seen(client)
        spec = None
        if spec_id:
            spec = next((s for s in self.hub.uploaded_specs if s.get("id") == spec_id), None)
        elif self.hub.uploaded_specs:
            spec = self.hub.uploaded_specs[-1]
        spec_data = {
            "title": title or (spec or {}).get("title") or tx("Yeni Proje Müzakeresi"),
            "meeting_notes": P.collect_spec_text(self.hub) if spec else "",
        }
        session = self.hub.deliberation_engine.open(spec_data)
        await self.hub.broadcast({"type": "DELIBERATION_OPENED", "session": session})
        participants = []
        for aid in ["PM", "ARCHITECT", "BACKEND_DEV", "FRONTEND_DEV", "QA", "PO", "SCM", "DEVOPS"]:
            agent = self.hub.agents.get(aid, {})
            role = agent.get("role", aid)
            from ..fs_workspace import get_standard_prompt_content
            participants.append({"agent_id": aid, "name": agent.get("name", aid), "role": role,
                                 "system_prompt": get_standard_prompt_content(role)})
        return {
            "status": "OPENED",
            "session": session,
            "participants": participants,
            "turn_order": [p["agent_id"] for p in participants] + ["PM"],
            "instructions": tx(
                "Her katılımcı için sırayla `deliberation_turn(session_id, agent_id, message, sentiment)` çağır "
                "(sentiment: PROPOSAL | CRITIQUE | AGREE | CONSENSUS). ARCHITECT turunda 2-3 alternatif mimari planı "
                "kısaca karşılaştır. Son PM turunda konsensüsü açıkla ve `close_deliberation(session_id, consensus_json)` çağır; "
                "consensus_json: {\"chosen_plan\": str, \"decision\": \"APPROVED_BY_CONSENSUS\", \"agreed_stack\": [..]}."
            ),
        }

    async def deliberation_turn(self, session_id: str, agent_id: str, message: str, sentiment: str = "AGREE",
                                client: Optional[Dict[str, str]] = None, proposals: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        await self.client_seen(client)
        msg = await self.hub.deliberation_engine.add_turn(session_id, agent_id, message, sentiment, proposals=proposals)
        return {"status": "OK", "message": msg, "proposals": self.hub.deliberation_engine.active_session.proposals if self.hub.deliberation_engine.active_session else []}

    async def choose_plan(self, session_id: str, plan_id: str, chosen_by: str = "USER", apply: str = "now") -> Dict[str, Any]:
        """Yönetici onayı = nihai karar. `apply`: 'now' (varsayılan: karar işi çalışan sprinte hemen alınır, geçerli adımdan sonra), 'next' (sıradaki planlamaya girer), 'none' (yalnızca karar kaydı)."""
        try:
            session = await self.hub.deliberation_engine.approve(session_id, plan_id, chosen_by)
        except ValueError as e:
            raise RunsApiError(str(e), 404)
        task = None
        if str(apply or "now").lower() != "none":
            task = await self._decision_task(session, apply)
            if task:
                session = self.hub.deliberation_engine.get_session_dict(session_id) or session
        return {"status": "CONSENSUS_REACHED", "session": session, "task": task}

    async def _decision_task(self, session: Dict[str, Any], apply: str = "now") -> Optional[Dict[str, Any]]:
        """Onaylı kararı rol bazlı görevlere bölecek ARCHITECT görevini açar (karar önceliklidir: `apply=now` ise geçerli adımdan hemen sonra çalışır)."""
        from .. import sprint_flow as SPF
        session_id = session.get("session_id") or ""
        cs = session.get("consensus_summary") or {}
        stack = ", ".join(cs.get("agreed_stack") or [])
        ref = cs.get("decision_ref") or session_id
        plan = next((p for p in (session.get("proposals") or []) if p.get("id") == (session.get("chosen_plan_id") or cs.get("proposed_plan_id"))), None) or {}
        title = tx("Kararı rol bazlı görevlere böl ({ref}): {plan}", ref=ref, plan=cs.get('chosen_plan') or session.get('title'))[:160]
        desc = (tx("Yönetici onaylı karar {ref}: {plan}.", ref=ref, plan=cs.get('chosen_plan') or session.get('title')) + (tx(" Yığın: {stack}.", stack=stack) if stack else "")
                + (tx(" Özet: {summary}", summary=plan.get('summary')) if plan.get("summary") else "")
                + tx(" Bu kararı uygulanabilir backlog görevlerine böl: her görev tek bir role (BACKEND_DEV, FRONTEND_DEV, DEVOPS, QA) ait, kabul kriterli ve bağımlılığı belirtilmiş olsun;"
                     " arayüz gerektiren her iş FRONTEND_DEV'e verilsin. Yığına ve onaylı teknoloji kararlarına uy, yeni kütüphane önerme. Tutanak: müzakere belgeleri."))
        task = await SPF.create_manager_task(
            self.hub, title, session_id, urgent=str(apply).lower() == "now", role="ARCHITECT", work_type="DECISION_PLAN", title=title, description=desc,
            criteria=[tx("Karar, rol bazlı backlog görevlerine bölünür (backend, frontend, devops, test)"), tx("Her görevin rolü, kabul kriterleri ve bağımlılığı vardır"),
                      tx("Görevler onaylı yığına uygundur")])
        if task:
            self.hub.deliberation_engine.set_implementation_task(session_id, task)
        return task

    async def split_decision(self, session_id: str, apply: str = "now") -> Dict[str, Any]:
        """Onaylanmış (CONSENSUS_REACHED) bir kararı, eski tek görevli uygulama yerine rol bazlı görevlere bölen mimar adımıyla yeniden uygular."""
        session = self.hub.deliberation_engine.get_session_dict(session_id)
        if session is None:
            raise RunsApiError(tx("Oturum bulunamadı."), 404)
        if session.get("status") != "CONSENSUS_REACHED":
            raise RunsApiError(tx("Yalnızca yönetici onaylı karar bölünebilir."), 409)
        task = await self._decision_task(session, apply)
        if not task:
            raise RunsApiError(tx("Görev açılamadı (sprint kipi kapalı ya da metin geçersiz)."), 409)
        return {"status": "OK", "task": task}

    async def revise_deliberation(self, session_id: str, feedback: str, by: str = "USER") -> Dict[str, Any]:
        try:
            session = await self.hub.deliberation_engine.request_revision(session_id, feedback, by)
        except ValueError as e:
            raise RunsApiError(str(e), 400)
        return {"status": "REVISION_REQUESTED", "session": session}

    async def close_deliberation(self, session_id: str, consensus: Dict[str, Any], client: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        await self.client_seen(client)
        session = await self.hub.deliberation_engine.close(session_id, consensus)
        if session.get("status") in ("AWAITING_PLAN_CHOICE", "AWAITING_APPROVAL"):
            return {"status": session["status"], "session": session,
                    "message": tx("Öneri yöneticiye sunuldu: nihai karar yöneticinindir. `wait_for_approval(run_id=<session_id>)` ile bekle; "
                                  "'REVISE' gelirse geri bildirimle yeni turlar ekleyip yeniden kapat, 'APPROVED' gelirse onaylanan planla devam et.")}
        return {"status": "CONSENSUS_REACHED", "session": session}


def _with_schedule_hint(fn):
    """`start_run` yanıtına (başarılıysa) koşu bekçisi ipucu ekler: yapay zekâ ilk yanıtta zamanlanmış görevi kurması gerektiğini görür."""
    import functools

    @functools.wraps(fn)
    async def wrapper(self, *args, **kwargs):
        result = await fn(self, *args, **kwargs)
        if isinstance(result, dict) and result.get("status") in ("STARTED", "RESUMED", "EXISTING"):
            from .. import driver as DRV
            hint = DRV.schedule_hint(self.hub)
            if hint:
                result["schedule_hint"] = hint
        return result
    return wrapper


LocalRunsApi.start_run = _with_schedule_hint(LocalRunsApi.start_run)
