# FS-SC developer guide

This document is for people who change FS-SC itself. For installing and using it, read the [README](README.md).

> Terminology: the **hub** is the single in-memory state owner (`TelemetryHub`); the **target project** is the folder FS-SC develops
> (never this repository); a **run** is one pipeline execution; a **step** is one unit of work handed to the AI client.

## Contents

1. [Architecture](#architecture)
2. [Repository map](#repository-map)
3. [The pull loop in detail](#the-pull-loop-in-detail)
4. [Data and state](#data-and-state)
5. [Sprint mode](#sprint-mode)
6. [Verification, evidence and gates](#verification-evidence-and-gates)
7. [Design pipeline](#design-pipeline)
8. [Target-project layout rules](#target-project-layout-rules)
9. [Conventions you must follow](#conventions-you-must-follow)
10. [Internationalization](#internationalization)
11. [Dashboard](#dashboard)
12. [Testing](#testing)
13. [Recipes](#recipes)
14. [Operations on a dev machine](#operations-on-a-dev-machine)
15. [Release checklist](#release-checklist)

---

## Architecture

```
AI client (Claude / Antigravity)
   │  MCP (stdio)                         ┌──────────────────────────────────────────────┐
   ▼                                      │ server.main                                   │
stdio process ──proxy──▶ web process ───▶│  FastAPI REST + WebSocket + MCP tools         │
                                          │  TelemetryHub  (state, settings, events)      │
                                          │  pipeline / steps / sprint_flow  (the engine) │
                                          │  verify / scm / app_runner / playwright       │
                                          └────────────────┬─────────────────────────────┘
                                                           │ writes files, runs commands
                                                           ▼
                                             target project (.fs-workspace/, apps/, docs/ ...)
```

- There is **one state**. If a web server (`--mode web`) is running, a stdio MCP process becomes a thin proxy to it (`stdio_proxy.py`).
  If none is running the stdio process starts a detached web server (hidden console, log in `history/server.log`).
- The server is **model-free**. All generation is done by the connected client; the server validates, writes, verifies and decides.
- A hub can be embedded in the MCP process (`FSSC_EMBEDDED_HUB=1`) but then the run dies with that client session. Avoid it outside tests.

## Repository map

| Path | What lives there |
|---|---|
| `server/main.py` | FastAPI app, REST routes, MCP tool registration (27 tools), WebSocket |
| `server/telemetry.py` | `TelemetryHub`: projects, settings, Jira store, events, persistence, project language |
| `server/pipeline.py` | Engine core: begin/finish step, file writing, verification, fix rounds, commits, backlog/UAT/design expansion, gates |
| `server/steps/` | Step handlers: `handlers.py` (phases), `tasks.py` (backlog task / fix / design task), `flow.py` (sprint flow steps), `registry.py` |
| `server/engine/` | Execution engines: `mcp_client.py` (pull model, session boundaries), `template.py` (offline), `api.py` (run control: skip, revise, resume) |
| `server/sprint.py`, `sprint_flow.py` | Sprint state, capacity, selection, commitment, close, re-scope, superseded-sprint healing |
| `server/jira_plus.py`, `hierarchy.py` | Issue store operations: bulk edit, plan/expedite, evidence, boards, hierarchy |
| `server/verify.py` | Syntax → install → lint → build → test runner, command inference, deny-list |
| `server/guard.py`, `satisfied.py`, `design_check.py`, `fidelity.py`, `quality.py` | Definition-of-done and evidence gates (see below) |
| `server/scm.py`, `project_bootstrap.py` | Git operations, `.gitignore` lines, `CLAUDE.md` / `GEMINI.md` blocks, `.mcp.json`, scratch-file sweep |
| `server/layout.py`, `paths.py`, `migrate_*.py` | Target-project folder layout and docs root |
| `server/testing.py`, `e2e_scenarios.py`, `playwright_tester.py`, `app_runner.py`, `ui_screens.py` | QA team, test cases, E2E, app launcher |
| `server/i18n.py`, `langcheck.py`, `locales/` | Server-side translation and mixed-language check |
| `agents/` | Role prompts (`prompts/<lang>/`), team templates, skills catalog |
| `dashboard/` | React 18 + Vite + Tailwind dashboard; `src/i18n/` has the UI translations |
| `scripts/` | `fssc.ps1` (operations), `register_claude_desktop.py`, `i18n_check.py`, `capture_manual.py` |
| `tests/` | pytest suite (isolated hub, never touches the real registry) |
| `docs/` | User manual (`USER_MANUAL.md`) and its screenshots (`images/manual/`) |

## The pull loop in detail

1. `start_pipeline_run(project_id, steps)` creates (or resumes) a run. Idempotent: an active run is returned; an abandoned run resumes (`RESUMED`).
2. `get_next_step(run_id)` returns `STEP` with `system_prompt`, `user_context`, `output_contract`, `instructions`. Other statuses:
   `WAITING_APPROVAL`, `PAUSED`, `BLOCKED`, `SESSION_BOUNDARY`, `RUN_COMPLETE`, `CANCELLED`.
3. The client answers with exactly one JSON envelope via `submit_step_result(run_id, order, result_json)`.
4. The server validates the envelope (`llm/parsing.py`), runs the handler's `render`, writes files (`pipeline.write_files`), then
   `finish_step` runs verification, fix-round creation, SCM commit and backlog/UAT/design expansion.
5. Responses are `NEXT`, `WAITING_APPROVAL`, `REJECTED` (with `validation_errors`; the same `order` must be resubmitted) or the terminal statuses.

Things worth knowing:

- A run is **dynamic**: `inserted_steps` can grow `total_steps` (backlog tasks, fix rounds, design screens, expedited work).
- **Fix rounds** reuse the same `order` with `kind: "fix"`; the limit is `max_fix_rounds`.
- **Server-side steps** (handshake, real Playwright E2E) are executed by the server; `get_next_step` skips them.
- **`already_satisfied`** lets a task close with evidence instead of files (see `satisfied.py`); it is refused for design-derived screen tasks.
- **Manager notes** (`POST /api/runs/{id}/notes`) are appended to the next step's context as top-priority instructions; an "urgent" note pauses the run.
- **Heartbeat**: no client call for `RUN_HEARTBEAT_TIMEOUT_S` → the run is `ABANDONED` (restarting the server also abandons active runs; resume with `POST /api/runs/{id}/resume`).

## Data and state

- Hub state is held in memory and persisted. Per-project data lives **in the target project** under `.fs-workspace/`
  (`settings.json`, `jira_issues.json`, `tasks.json`, `sprint_state.json`, `runs.json`, `questions.json`, `deliberations.json`,
  `events.jsonl`, `e2e/screenshots/`, `fidelity/report.json`, `tmp/`). The FS-SC repo itself only keeps `history/` runtime data (git-ignored).
- Settings are layered: defaults in code → project `settings.json` → registry. `hub.get_settings()` is the accessor.
- `.fs-workspace/` is protected: agent deliveries cannot write there or into `.git` (`pipeline.is_protected_path`).
- Files that must **not** enter the target project's git (machine-specific config, logs, screenshots, scratch files) are listed in `scm.FSSC_IGNORE_LINES`.

## Sprint mode

Enabled by `sprint.enabled`. Key modules: `sprint.py` (state, `select_items`, `candidates`, capacity, `_close_superseded`) and `sprint_flow.py`
(plan, commitment, daily flow, close, re-scope, design task helpers, `expedite_issue`).

- A sprint goes `PLANNED/COMMITTED → IN_PROGRESS → IN_REVIEW → CLOSED` (or `BLOCKED` / `CANCELLED`). A sprint left open while a newer sprint runs is closed automatically (superseded).
- **Selection** respects capacity, quality/test shares (`test_share_pct`, `feature_share_pct`), `ui_min_tasks`, dependencies and carry-over (`carry_over_limit`).
- **`no_tests`** pauses test work: test items are not selected, agents are told not to write tests, and the DoD test condition is waived.
- **Expedite** (`POST /api/jira/issues/{id}/plan {"expedite": "now"}`) inserts a backlog item right after the current step of the running run.
- **Duplicate guard:** when the architect proposes a task whose title is ≥88% similar to an existing DONE task it is not created (`pipeline._done_duplicate`).

## Verification, evidence and gates

| Gate | Module | Purpose |
|---|---|---|
| Server verification | `verify.py` | syntax → install → lint → build → test; failing = fix round |
| Strict DoD | `guard.py` (`task_dod`) | code needs tests, no skipped verification, secrets block the commit |
| Evidence closure | `satisfied.py` | close a task from tests that actually ran; `identifier_hits` tells the agent which named classes already exist |
| AC coverage | `quality.py`, `jira_plus.evidence` | acceptance criterion → test evidence mapping |
| Design completeness | `design_check.py` | mockups responsive, stateful, endpoint-complete, flows present |
| Screen task gate | `steps/tasks.py` | a design-derived screen task must change UI source (unchanged rewrites do not count) |
| Design fidelity | `fidelity.py` | Chromium screenshot of mockup vs running app, text coverage + visual similarity, fix task on drift |

A rule of thumb for new gates: **trust files, git and processes — not the agent's summary.**

## Design pipeline

1. A `DESIGN` work item (from the board's design button or sprint flow) is handled by the designer; `api_surface.py` scans backend endpoints and feeds them into the task context.
2. Delivery: `<docs>/design/` design system, `screens/*.html`, `coverage.md` (endpoint → screen), `flows.md`/`flows.html`, plus a `screens[]` envelope.
3. `design_check.check` validates the delivery; failures create a fix round.
4. After approval `pipeline.expand_design_screens` opens one `FRONTEND_DEV` task per screen (field `design_screen`) and expedites them into the running sprint.
5. `POST /api/design/fidelity` compares mockups with the running web client (`verification.client_url`, started with `client_run` when down) and
   `pipeline.open_fidelity_tasks` creates *Screen fidelity* tasks. `POST /api/design/reimplement` reopens screens that were closed without any UI change.

## Target-project layout rules

- New projects use a single repo with `apps/<role>/`, `devops/`, `docs/` (or `FS-docs/`); legacy projects keep the flat layout. Never hard-code `src/`, `tests/`, `docs/`, `Dockerfile` paths: use `server/layout.py` and `server/paths.py` (`docs_root`, the `<docs>` and `<reports>` placeholders resolved by `StepContext.r()`).
- **Docker files always live under `devops/`**; deliveries that put them elsewhere are rejected (`layout.docker_violations`).
- Agent scratch files go under `.fs-workspace/tmp/`; `project_bootstrap.sweep_stray_root_files` moves strays at step start, commit and project connect.

## Conventions you must follow

- **No browser dialogs in the dashboard.** Never use `alert`/`confirm`/`prompt`; use `notify`, `await confirmDialog`, `await promptDialog` from `dashboard/src/lib/dialog.ts`.
- **Every subprocess is started with `**hidden()`** (`server/proc.py`) so a console-less server never flashes terminal windows on Windows (`tests/test_no_console_windows.py` enforces it).
- **Do not poll with processes.** Dashboard polling must not spawn processes (`_git_head` reads files).
- **Windows quirks:** write files with `newline="\n"`; use `PYTHONIOENCODING=utf-8` for console output; paths use forward slashes in stored data.
- **Prompts and generated text** go through `tx()` / `N_()` (see below); never concatenate translated fragments into sentences.
- **Tests with every behaviour change.** Add a pytest case and, where it makes sense, prove it with the offline template engine run.
- **Do not hand-edit target projects** to "fix" a run. Fix the generator, the gate or the prompt in FS-SC so the pipeline does it.
- **Small, reversible decisions**; record deviations in the commit message or pull request description.
- Keep `sprint.enabled=false` behaviour working: the fixed 1–10 flow must still pass its tests.

## Internationalization

Server (`server/i18n.py`):

- Source strings in code are Turkish (the original language); `tx("…", name=value)` / `translate(text, lang=None, /, **kw)` translate at runtime, `N_("…")` marks a string for later translation.
- English catalogs: `server/locales/en_*.py` (`{turkish_source: english}`). `tests/test_i18n.py` fails when a marked string has no English entry.
- `use_lang(lang)` sets the project language for the current step; `variants/matches` support comparing across languages.
- `server/langcheck.py` warns (never blocks) when an agent delivery is in the wrong language.
- Rules: every user-visible server string is written in Turkish at the call site (`tx(...)`, `N_(...)`) and gets an English entry in `server/locales/en_*.py`; run `python scripts/i18n_check.py` to find gaps.

Dashboard (`dashboard/src/i18n/`):

- `t(key, params, fallback)`; the fallback is the Turkish source. Extra parts live in `locales/extra/*.ts` and are merged automatically.
- Languages: `tr`, `en`, `es`, `de`. Rules: add every key to all four dictionaries in `dashboard/src/i18n/locales/`; run `python scripts/i18n_check.py`.

Check tooling: `python scripts/i18n_check.py`, `python -m pytest -q tests/test_i18n.py`.

Adding a language: add the code to the supported list, a prompt folder `agents/prompts/<lang>/`, server catalog entries, dashboard locale parts, and the language selector entries.

## Dashboard

- Stack: React 18, Vite, Tailwind, React Flow, CodeMirror. Source in `dashboard/src` (`App.tsx`, `components/`, `hooks/`, `types/telemetry.ts`).
- Build: `cd dashboard && npm run build` (runs `tsc` first). The server serves `dashboard/dist`. Dev server: `npm run dev` (proxies `/api` and `/ws`).
- The WebSocket (`/ws/telemetry`) pushes hub events; `hooks/useTelemetryWS.ts` is the entry point.
- Manual screenshots: `python scripts/capture_manual.py` (needs a running server with a finished demo project; see the manual).

## Testing

```bash
python -m pytest -q                              # everything
python -m pytest -q tests/test_sprint.py         # focused
python -m pytest -q tests/test_i18n.py           # translation completeness
scripts\fssc.ps1 dry-run                         # model-free full loop
cd dashboard && npm run build                    # type-check the dashboard
```

Tests run against an **isolated hub** and temporary folders; they never use the real project registry or machine projects. Some suites are slow (sprint flow);
run the ones related to your change while iterating and the full suite before a release.

## Recipes

**Add a step handler.** Subclass `StepHandler` in `server/steps/`, register it in `registry.py`, give it a thinking trio, an output contract and a `render`
that returns files/events/summary; put validation errors in `StepOutputError`. Add a template-engine output so the offline run covers it.

**Add a gate.** Put the check in a small module that takes the project directory and returns problems. Call it from `pipeline.finish_step` (or the
handler's `render` for pre-write checks), turn problems into a fix round, and add the strings to the i18n catalog.

**Add an agent.** Core roles are `config.DEFAULT_AGENTS`. Custom agents come from `agents/registry.json` with `role_base`, `capabilities` and `focus`
(`server/agent_registry.py`). Route tasks with `pipeline.backlog_for(...)`, not a fixed role list.

**Add a setting.** Add the default and sanitiser (`sprint.py` for sprint settings, `telemetry.py` otherwise), expose it in
`ProjectSettingsModal.tsx`, add UI strings in `locales/extra/*.ts`, and test the behaviour.

**Add an MCP tool.** Register it in `server/main.py`, document it in the README tool list, keep input models in `mcp_models.py`.

## Operations on a dev machine

```powershell
scripts\fssc.ps1 start -Background -NoBrowser   # detached server on 8099
scripts\fssc.ps1 status                          # server / project / run summary
scripts\fssc.ps1 stop                            # stop (only FS-SC processes on that port)
scripts\fssc.ps1 build                           # rebuild dashboard
```

A running server does not reload code. After changing Python code restart it (the top bar shows a **!** badge when files changed after start).
Restarting abandons an active run; resume it with `POST /api/runs/{id}/resume` or by repeating the client prompt.

## Release checklist

1. `python -m pytest -q` passes; `npm run build` passes; `python scripts/i18n_check.py` is clean.
2. No secrets, machine paths or runtime data in the tree (`history/`, `.env*`, `.fs-workspace/` are ignored).
3. Manual screenshots are current (`scripts/capture_manual.py`).
4. `LICENSE` and third-party notes are present; the skills catalog stays reference-only.
5. Fast-forward `main`, tag (`vMAJOR.MINOR.PATCH`), push, then create the release notes from the phase reports.
