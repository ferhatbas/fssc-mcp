"""
ProxyRunsApi — stdio MCP süreci ile ayrı çalışan web sunucusu arasında köprü.

`python -m server.main --mode stdio` başlatıldığında port zaten bir `--mode web` süreci tarafından
kullanılıyorsa, bu süreçte ikinci bir TelemetryHub oluşur ve dashboard koşuyu göremez. Bu sınıf,
MCP araç çağrılarını REST ikizlerine (httpx) yönlendirerek tek bir hub üzerinde çalışılmasını sağlar.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .errors import RunsApiError


class ProxyRunsApi:
    def __init__(self, base_url: str, timeout_s: float = 900.0):
        import httpx  # lazy: yalnızca proxy modunda gerekli

        # G3: teslim doğrulaması (kurulum/test) 300-600 sn sürebilir; okuma zaman aşımı bunun üstünde, bağlantı 10 sn
        self.base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(base_url=self.base_url, timeout=httpx.Timeout(timeout_s, connect=10.0))

    async def _call(self, method: str, path: str, json: Optional[Dict[str, Any]] = None, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        resp = await self._client.request(method, path, json=json, params=params)
        try:
            data = resp.json()
        except Exception:
            data = {"error": resp.text}
        if not isinstance(data, dict):
            data = {"result": data}
        # İdempotent başlatma: sunucu 409 + mevcut koşu döndürür; bu bir hata değil, aynı koşudur
        if resp.status_code == 409 and data.get("run"):
            return data
        if resp.status_code >= 400:
            extra = {k: v for k, v in data.items() if k not in ("error", "message")}
            raise RunsApiError(data.get("error") or data.get("message") or f"HTTP {resp.status_code}", resp.status_code, **extra)
        return data

    @staticmethod
    def _client_params(client: Optional[Dict[str, str]]) -> Dict[str, Any]:
        return {"client": client} if client else {}

    async def client_seen(self, client: Optional[Dict[str, str]]):
        if client and client.get("name"):
            await self._call("POST", "/api/mcp/clients/seen", json={"client": client})

    async def start_run(self, project_id=None, steps=None, engine=None, custom_prompt="", step_by_step=None,
                        client=None, force_new=False, project_dir=None) -> Dict[str, Any]:
        return await self._call("POST", "/api/runs", json={
            "project_id": project_id, "steps": steps, "engine": engine, "prompt": custom_prompt,
            "step_by_step": step_by_step, "force_new": force_new, "project_dir": project_dir, **self._client_params(client),
        })

    async def next_step(self, run_id: str, client=None) -> Dict[str, Any]:
        return await self._call("POST", f"/api/runs/{run_id}/next-step", json=self._client_params(client))

    async def submit_result(self, run_id: str, order: int, result_json: Any, tokens_in: int = 0, tokens_out: int = 0, client=None) -> Dict[str, Any]:
        return await self._call("POST", f"/api/runs/{run_id}/steps/{order}/result", json={
            "result_json": result_json, "tokens_in": tokens_in, "tokens_out": tokens_out, **self._client_params(client),
        })

    async def wait_approval(self, run_id: str, timeout_s: float = 30.0, client=None) -> Dict[str, Any]:
        return await self._call("POST", f"/api/runs/{run_id}/approval", json={"timeout_s": timeout_s, **self._client_params(client)})

    async def report_thinking(self, run_id: str, agent_id: str, text: str, what_doing: str = "", what_next: str = "", client=None) -> Dict[str, Any]:
        return await self._call("POST", f"/api/runs/{run_id}/thinking", json={
            "agent_id": agent_id, "text": text, "what_doing": what_doing, "what_next": what_next, **self._client_params(client),
        })

    async def restart_fresh(self, run_id: str, confirm_name: str) -> Dict[str, Any]:
        return await self._call("POST", f"/api/runs/{run_id}/restart-fresh", json={"confirm_name": confirm_name})

    async def pause_run(self, run_id: str, reason: str = "user") -> Dict[str, Any]:
        return await self._call("POST", f"/api/runs/{run_id}/pause", json={"reason": reason})

    async def resume_run(self, run_id: str) -> Dict[str, Any]:
        return await self._call("POST", f"/api/runs/{run_id}/resume", json={})

    async def cancel_run(self, run_id: str, reason: str = "user") -> Dict[str, Any]:
        return await self._call("POST", f"/api/runs/{run_id}/cancel", json={"reason": reason})

    async def list_runs(self, project_id: Optional[str] = None, limit: int = 50) -> Dict[str, Any]:
        return await self._call("GET", "/api/runs", params={k: v for k, v in {"project_id": project_id, "limit": limit}.items() if v})

    async def get_run(self, run_id: str) -> Dict[str, Any]:
        return await self._call("GET", f"/api/runs/{run_id}")

    async def claim_work(self, client=None) -> Dict[str, Any]:
        return await self._call("POST", "/api/runner/claim", json=self._client_params(client))

    async def get_activity(self, limit: int = 30) -> Dict[str, Any]:
        return await self._call("GET", "/api/activity", params={"limit": limit})

    async def get_runner_schedule(self) -> Dict[str, Any]:
        return await self._call("GET", "/api/runner/schedule")

    async def get_sprint_state(self) -> Dict[str, Any]:
        return await self._call("GET", "/api/sprints/state")

    async def list_questions(self, status=None) -> Dict[str, Any]:
        return await self._call("GET", "/api/questions", params={"status": status} if status else None)

    async def answer_question(self, question_id: str, answer: str) -> Dict[str, Any]:
        return await self._call("POST", f"/api/questions/{question_id}/answer", json={"answer": answer, "restrict_blocking": True})

    async def get_tech_requirements(self) -> Dict[str, Any]:
        return await self._call("GET", "/api/tech-requirements")

    async def add_manager_input(self, text: str, title: str = "Yönetici girdisi", client_name: str = "Yönetici", urgent: bool = False, client=None) -> Dict[str, Any]:
        return await self._call("POST", "/api/manager-input", json={"text": text, "title": title, "client_name": client_name, "urgent": urgent, **self._client_params(client)})

    async def open_deliberation(self, spec_id: str = "", title: str = "", client=None) -> Dict[str, Any]:
        return await self._call("POST", "/api/deliberation/open", json={"spec_id": spec_id, "title": title, **self._client_params(client)})

    async def deliberation_turn(self, session_id: str, agent_id: str, message: str, sentiment: str = "AGREE", client=None, proposals=None) -> Dict[str, Any]:
        return await self._call("POST", "/api/deliberation/turn", json={
            "session_id": session_id, "agent_id": agent_id, "message": message, "sentiment": sentiment, "proposals": proposals, **self._client_params(client),
        })

    async def choose_plan(self, session_id: str, plan_id: str, chosen_by: str = "USER", apply: str = "now") -> Dict[str, Any]:
        return await self._call("POST", "/api/deliberation/choose-plan", json={"session_id": session_id, "plan_id": plan_id, "chosen_by": chosen_by, "apply": apply})

    async def revise_deliberation(self, session_id: str, feedback: str, by: str = "USER") -> Dict[str, Any]:
        return await self._call("POST", "/api/deliberation/revise", json={"session_id": session_id, "feedback": feedback, "by": by})

    async def close_deliberation(self, session_id: str, consensus: Dict[str, Any], client=None) -> Dict[str, Any]:
        return await self._call("POST", "/api/deliberation/close", json={"session_id": session_id, "consensus": consensus, **self._client_params(client)})

    async def aclose(self):
        await self._client.aclose()
