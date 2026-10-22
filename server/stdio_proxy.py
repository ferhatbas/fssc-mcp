"""Hafif MCP stdio proxy: web sunucusu zaten çalışırken `python -m server.main --mode stdio` bunu kullanır.

Neden: `server.main` hub, FastAPI ve tüm panoyu yükler (~14 sn); Claude'un MCP bağlantı sınırı 30 sn olduğundan yük altında `CONNECT_TIMEOUT`
oluşuyordu. Proxy modunda araçlar zaten çalışan sunucuya HTTP ile iletilir, bu yüzden burada yalnızca `mcp`, `httpx` ve pydantic modelleri yüklenir.

Araç imzaları `server.main` ile BİREBİR aynı olmalıdır (tests/test_stdio_proxy.py bunu denetler). Web sunucusu yoksa ya da
`FSSC_EMBEDDED_HUB=1` ise bu yol kullanılmaz; `server.main` tam yoldan devam eder.
"""

import functools
import inspect
import json
import os
import sys
import urllib.request
from typing import Any, Dict, List, Optional

from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from .config import SERVER_HOST, SERVER_PORT
from .i18n import translate as tx, N_
from .engine.errors import RunsApiError
from .engine.proxy import ProxyRunsApi
from .mcp_common import (_LOG_ARG_KEYS, _PULL_LOOP_TOOLS, _client_info, _outcome_of, _plain_result, _tool_error,
                         run_software_company_prompt)
from .mcp_models import ApprovalStatus, ClaimResult, DeliberationInfo, NextStep, RunInfo, RunList, SubmitResult, compact_run

BASE_URL = f"http://{SERVER_HOST}:{SERVER_PORT}"


def web_server_up(timeout: float = 1.5) -> bool:
    try:
        with urllib.request.urlopen(f"{BASE_URL}/api/state", timeout=timeout) as r:
            return r.status == 200
    except Exception:
        return False


def should_use(argv: List[str]) -> bool:
    """`--mode stdio` ve çalışan bir web sunucusu varsa hafif yol; aksi halde (başlatma/gömülü kip) tam `server.main`."""
    if os.environ.get("FSSC_EMBEDDED_HUB") == "1":
        return False
    try:
        if argv[argv.index("--mode") + 1] != "stdio":
            return False
    except (ValueError, IndexError):
        return False
    return web_server_up()


mcp = MCPServer("fssc-visual-observer")
_api: Optional[ProxyRunsApi] = None


def runs_api() -> ProxyRunsApi:
    global _api
    if _api is None:
        _api = ProxyRunsApi(BASE_URL)
    return _api


async def _record_call(name: str, kwargs: Dict[str, Any], outcome: str, result: Any = None) -> None:
    """Araç çağrısını web sunucusunun Claude iletişim günlüğüne yazar (`server.main._record_mcp_tool_call` proxy yolunun ikizi)."""
    try:
        client = _client_info(kwargs.get("ctx"), str(kwargs.get("client_name") or ""))
        args = " ".join(f"{k}={kwargs[k]}" for k in _LOG_ARG_KEYS if kwargs.get(k) not in (None, "", []))
        full_args = {k: v for k, v in kwargs.items() if k != "ctx"}
        await runs_api()._call("POST", "/api/mcp/log", json={
            "tool": name, "result": outcome, "title": args[:120], "client": client, "run_id": kwargs.get("run_id") or None,
            "args": full_args, "result_full": _plain_result(result)})
    except Exception:  # noqa: BLE001
        pass


def _tool(*tool_args, **tool_kwargs):
    """`server.main._logged_tool` ikizi: aracı kaydeder, çift kayıt olmasın diye iş döngüsü araçları hariç her çağrıyı günlüğe yazar."""
    register = mcp.tool(*tool_args, **tool_kwargs)

    def apply(fn):
        name = tool_kwargs.get("name") or fn.__name__
        if name in _PULL_LOOP_TOOLS or not inspect.iscoroutinefunction(fn):
            return register(fn)

        @functools.wraps(fn)
        async def wrapper(*args, **kwargs):
            outcome, result = "OK", None
            try:
                result = await fn(*args, **kwargs)
                outcome = _outcome_of(result)
                return result
            except Exception as e:  # noqa: BLE001
                outcome = f"ERROR: {str(e)[:70]}"
                raise
            finally:
                await _record_call(name, kwargs, outcome, result)

        return register(wrapper)

    return apply


async def _rest(method: str, path: str, json_body: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    try:
        return await runs_api()._call(method, path, json=json_body)
    except RunsApiError as e:
        raise ToolError(e.message)


# ---------------------------------------------------------------------------
# Telemetri / pano araçları (web sunucusunun REST uçlarına iletilir)
# ---------------------------------------------------------------------------
@_tool()
async def emit_agent_event(
    trace_id: str,
    from_agent: str,
    to_agent: str,
    action: str,
    status: str = "SUCCESS",
    payload: str = "{}",
    current_file: str = "",
    tokens_used: int = 0
) -> str:
    """Publishes data transfer between agents, error reports and approvals to the dashboard."""
    try:
        parsed_payload = json.loads(payload) if isinstance(payload, str) and payload.startswith(("{", "[")) else {"raw": payload}
    except Exception:
        parsed_payload = {"raw": payload}
    await _rest("POST", "/api/events", {
        "trace_id": trace_id, "from_agent": from_agent, "to_agent": to_agent, "action": action, "status": status,
        "payload": parsed_payload, "current_file": current_file or None, "tokens_used": tokens_used})
    return f"OK: Event '{action}' from {from_agent} to {to_agent} recorded (Status: {status})."


@_tool()
async def update_task_state(
    task_id: str,
    new_state: str,
    title: str = "",
    assignee: str = "",
    priority: str = "P1",
    details: str = ""
) -> str:
    """Updates the state and assignee of a task on the Kanban / Jira board."""
    res = await _rest("POST", "/api/tasks", {
        "task_id": task_id, "new_state": new_state, "title": title or None, "assignee": assignee or None,
        "priority": priority, "details": details or None})
    task = res.get("task") or {}
    return f"OK: Task {task_id} moved to {task.get('state')} (Assignee: {task.get('assignee')})."


@_tool()
async def run_playwright_e2e(
    target_url: str = "http://127.0.0.1:8099",
    scenario: str = "Canlı Kullanıcı E2E Akış Testi",
    username: str = "",
    password: str = "",
    role: str = "USER"
) -> str:
    """Tests the application in a real Chromium browser with Playwright and saves the screenshots to the dashboard."""
    result = await _rest("POST", "/api/mcp/playwright", {"target_url": target_url, "scenario": scenario, "username": username,
                                                          "password": password, "role": role})
    return (f"OK: Playwright E2E test completed (Status: {result.get('status')}, "
            f"Screenshots: {len(result.get('screenshots') or [])}, User: {username or 'Guest'}).")


@_tool()
async def report_agent_metric(
    agent_name: str,
    tokens_in: int = 0,
    tokens_out: int = 0,
    active_file: str = "",
    latency_ms: float = 0.0,
    status: str = "WORKING"
) -> str:
    """Reports the agent's live status, token usage and active file to the telemetry panel."""
    await _rest("POST", "/api/agents/metric", {
        "agent_name": agent_name, "tokens_in": tokens_in, "tokens_out": tokens_out, "active_file": active_file or None,
        "latency_ms": latency_ms, "status": status})
    return f"OK: Telemetry metric recorded for {agent_name}."


@_tool()
async def get_mesh_topology() -> str:
    """Returns the live state of the agent network, the active tasks and a metric summary."""
    return json.dumps(await _rest("GET", "/api/state"), indent=2)


@_tool()
async def reset_mesh_state() -> str:
    """Resets the telemetry board and its history."""
    await _rest("POST", "/api/reset", {})
    return "OK: Visual mesh state and event history reset."


# ---------------------------------------------------------------------------
# Çekme (pull) modeli araçları
# ---------------------------------------------------------------------------
@_tool()
async def start_pipeline_run(
    project_id: str = "",
    steps: Optional[List[int]] = None,
    custom_prompt: str = "",
    client_name: str = "",
    force_new: bool = False,
    ctx: Context = None,
) -> RunInfo:
    """Starts a software-company pipeline run (idempotent: returns the active run if there is one). Empty steps = all of 1-10.
    If project_id is empty the active project of the dashboard is used. Then enter the loop with get_next_step(run_id)."""
    try:
        result = await runs_api().start_run(
            project_id=project_id or None,
            steps=steps or [],
            engine="mcp_client",
            custom_prompt=custom_prompt,
            client=_client_info(ctx, client_name),
            force_new=force_new,
        )
    except RunsApiError as e:
        raise _tool_error(e)
    return RunInfo(**{**result, "run": compact_run(result.get("run") or {})})


@_tool()
async def claim_work(client_name: str = "", ctx: Context = None) -> ClaimResult:
    """First call of a runner (scheduled task). If work is waiting it returns the run and the lease (status CLAIMED -> get_next_step);
    if there is no work it returns IDLE, and BLOCKED if the sprint/run waits for a manager decision: in both cases write the reason in one line and end the session (no wasted spend)."""
    try:
        return ClaimResult(**await runs_api().claim_work(_client_info(ctx, client_name)))
    except RunsApiError as e:
        raise _tool_error(e)


@_tool()
async def get_activity_feed(limit: int = 30) -> str:
    """Returns the team's recent activity as readable text: project/sprint state, spend, open questions, runner state and recent events
    (steps, messages between agents, verification results). The answer to 'what is going on in FS-SC?'."""
    return (await runs_api().get_activity(limit)).get("markdown", "")


@_tool()
async def get_runner_schedule() -> str:
    """Run-watchdog schedule (the single source for creating/updating a scheduled task): `interval_minutes` is the polling interval that applies now (paused_interval_min if the app is paused, otherwise active_interval_min), `suggested_cron` is its cron equivalent, `job` is the watched run (state, idle time, stalled or not), `enabled` tells whether the server's own automatic runner is on. If you have scheduled-task tools (create_scheduled_task / update_scheduled_task) set the task's interval to this value."""
    return json.dumps(await runs_api().get_runner_schedule(), ensure_ascii=False, indent=2, default=str)


@_tool()
async def get_acceptance_criteria(ac_ids: str = "") -> str:
    """Returns the TEXT of acceptance-criterion ids from the server (e.g. "AC-42,AC-43"; if empty, the criteria of the current step). Do NOT ask the user for the criterion text; take it from here."""
    from urllib.parse import quote
    res = await _rest("GET", f"/api/acceptance-criteria?ids={quote(str(ac_ids))}")
    return json.dumps(res, ensure_ascii=False, indent=2, default=str)


@_tool()
async def get_sprint_state() -> str:
    """Summary of the active sprint: state, goal, spend and budget, carried-over items, blocking reason, pending review, runner state (JSON)."""
    return json.dumps(await runs_api().get_sprint_state(), ensure_ascii=False, indent=2, default=str)


@_tool()
async def list_questions(status: str = "") -> str:
    """Lists the question queue (OPEN | ANSWERED | DEFAULTED | OVERRIDDEN). Each question has a category, options, a recommended answer and whether it is blocking."""
    return json.dumps(await runs_api().list_questions(status or None), ensure_ascii=False, indent=2, default=str)


@_tool()
async def answer_question(question_id: str, answer: str) -> str:
    """Answers a non-technology (NOT blocking) question on behalf of the manager; answer is the option key (e.g. A). A different answer to a DEFAULTED question overrides it.
    TECHNOLOGY and EXTERNAL_ACTION questions cannot be answered with this tool: the manager answers them in the dashboard."""
    try:
        res = await runs_api().answer_question(question_id, answer)
    except RunsApiError as e:
        raise _tool_error(e)
    return f"OK: {question_id} → {res.get('question', {}).get('status', res.get('status'))}"


@_tool()
async def get_tech_requirements() -> str:
    """Technology requirements: items (SPECIFIED/MISSING/CONTRADICTORY), source quotes, approval state. Approval is not given with this tool (only the manager, in the dashboard)."""
    return json.dumps(await runs_api().get_tech_requirements(), ensure_ascii=False, indent=2, default=str)


@_tool()
async def add_manager_input(text: str, title: str = "Yönetici girdisi", urgent: bool = False, ctx: Context = None) -> str:
    """Lets the manager leave a note in the vault from the chat: it counts as an upload, queues the review and (in sprint mode) starts the work."""
    try:
        res = await runs_api().add_manager_input(text, title, tx("Yönetici"), urgent, client=_client_info(ctx))
    except RunsApiError as e:
        raise _tool_error(e)
    return f"{res.get('status')}: {res.get('message', '')}"


@_tool()
async def get_next_step(run_id: str, ctx: Context = None) -> NextStep:
    """Returns the next step of the run and its prompt: status STEP -> produce with system_prompt/user_context/output_contract;
    WAITING_APPROVAL -> call wait_for_approval; RUN_COMPLETE -> finish. The same step is returned again until a submit succeeds."""
    try:
        result = await runs_api().next_step(run_id, client=_client_info(ctx))
    except RunsApiError as e:
        raise _tool_error(e)
    return NextStep(**result)


@_tool()
async def submit_step_result(
    run_id: str,
    order: int,
    result_json: str,
    tokens_in: int = 0,
    tokens_out: int = 0,
    ctx: Context = None,
) -> SubmitResult:
    """Submits the output of the step (only the output_contract JSON envelope). The server writes the files and publishes the events.
    status NEXT -> get_next_step; WAITING_APPROVAL -> wait_for_approval; REJECTED -> fix according to validation_errors and send again."""
    try:
        result = await runs_api().submit_result(run_id, order, result_json, tokens_in, tokens_out, client=_client_info(ctx))
    except RunsApiError as e:
        raise _tool_error(e)
    return SubmitResult(**result)


@_tool()
async def wait_for_approval(run_id: str, timeout_s: int = 30, ctx: Context = None) -> ApprovalStatus:
    """Waits up to timeout_s (<=45) seconds for the user to approve the step in the dashboard.
    If STILL_WAITING is returned call again; if APPROVED is returned continue with get_next_step."""
    try:
        result = await runs_api().wait_approval(run_id, float(timeout_s), client=_client_info(ctx))
    except RunsApiError as e:
        raise _tool_error(e)
    return ApprovalStatus(**result)


@_tool()
async def report_thinking(run_id: str, agent_id: str, text: str, what_doing: str = "", what_next: str = "", ctx: Context = None) -> str:
    """Before starting a step, publishes to the live stream a short 1-2 sentence plan note describing what the agent will do in this step."""
    try:
        result = await runs_api().report_thinking(run_id, agent_id, text, what_doing, what_next, client=_client_info(ctx))
    except RunsApiError as e:
        raise _tool_error(e)
    return f"OK: thinking recorded for {result.get('agent_id')}"


@_tool()
async def cancel_pipeline_run(run_id: str, reason: str = "") -> str:
    """Cancels the running run."""
    try:
        result = await runs_api().cancel_run(run_id, reason or "mcp-client")
    except RunsApiError as e:
        raise _tool_error(e)
    return f"OK: run {run_id} → {result.get('status')}"


@_tool()
async def list_runs(project_id: str = "") -> RunList:
    """Lists the run history (state, steps, engine)."""
    res = await runs_api().list_runs(project_id or None)
    return RunList(**{**res, "runs": [compact_run(r) for r in (res.get("runs") or [])]})


@_tool()
async def open_deliberation(spec_id: str = "", title: str = "", ctx: Context = None) -> DeliberationInfo:
    """Opens a deliberation-room session between agents; returns the participants, their prompts and the turn order."""
    try:
        return DeliberationInfo(**await runs_api().open_deliberation(spec_id, title, client=_client_info(ctx)))
    except RunsApiError as e:
        raise _tool_error(e)


@_tool()
async def deliberation_turn(session_id: str, agent_id: str, message: str, sentiment: str = "AGREE", proposals_json: str = "", ctx: Context = None) -> str:
    """Records an agent's statement at the deliberation table (sentiment: PROPOSAL | CRITIQUE | AGREE | CONSENSUS).
    In the ARCHITECT turn give 2-3 alternative plans with proposals_json: [{"id":"A","title":..,"summary":..,"stack":[..],"pros":[..],"cons":[..],"risk":"LOW|MEDIUM|HIGH","recommended":true}].
    If plans were given, close_deliberation waits for the user's choice (wait_for_approval(run_id=session_id))."""
    proposals = None
    if proposals_json:
        try:
            proposals = json.loads(proposals_json)
        except Exception:
            raise ToolError(tx("proposals_json geçerli bir JSON listesi olmalı."))
    try:
        await runs_api().deliberation_turn(session_id, agent_id, message, sentiment, client=_client_info(ctx), proposals=proposals)
    except (RunsApiError, ValueError) as e:
        raise ToolError(str(e))
    return f"OK: {agent_id} spoke ({sentiment})" + (f" with {len(proposals)} plan(s)" if proposals else "")


@_tool()
async def close_deliberation(session_id: str, consensus_json: str = "{}", ctx: Context = None) -> str:
    """Closes the deliberation with a consensus. consensus_json: {"chosen_plan": str, "decision": str, "agreed_stack": [..]}."""
    try:
        consensus = json.loads(consensus_json) if consensus_json else {}
    except Exception:
        consensus = {"chosen_plan": consensus_json}
    try:
        result = await runs_api().close_deliberation(session_id, consensus, client=_client_info(ctx))
    except (RunsApiError, ValueError) as e:
        raise ToolError(str(e))
    if result.get("status") in ("AWAITING_PLAN_CHOICE", "AWAITING_APPROVAL"):
        return tx("{status}: öneri yöneticiye sunuldu, nihai karar yöneticinin. wait_for_approval(run_id=\"{sid}\") çağır; "
                  "REVISE gelirse geri bildirimle yeni turlar ekleyip yeniden kapat, APPROVED gelirse onaylanan planla devam et.", status=result['status'], sid=session_id)
    return f"OK: deliberation {session_id} closed with consensus"


@_tool()
async def send_cross_project_message(target_project_id: str, from_agent: str, to_agent: str, message: str) -> str:
    """Sends a message to the team of another project (e.g. Web team -> Mobile team); visible on both dashboards."""
    res = await _rest("POST", f"/api/projects/{target_project_id}/message",
                      {"from_agent": from_agent, "to_agent": to_agent, "message": message})
    event = res.get("event") or {}
    return tx("OK: {fa}@{fp} → {ta}@{tp} iletildi.", fa=event.get('from_agent'), fp=event.get('from_project'), ta=event.get('to_agent'), tp=event.get('to_project'))


@mcp.prompt()
def run_software_company(project_id: str = "", steps: str = "1-10") -> str:
    """Runs the full software-company development loop (PM -> Architect+backlog -> skeleton -> tasks (verification/fix/commit) -> QA -> E2E -> DevOps -> PO -> Docs) in this client."""
    return run_software_company_prompt(project_id, steps)


def run() -> None:
    import asyncio
    print(f"[*] MCP stdio (hafif proxy) → {BASE_URL}", file=sys.stderr)

    async def _main():
        try:
            await mcp.run_stdio_async()
        finally:
            if _api is not None:
                try:
                    await _api.aclose()
                except Exception:
                    pass

    asyncio.run(_main())
