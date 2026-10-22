# FS-SC User Manual

This manual explains every screen of the FS-SC dashboard, what each control does, and how the screens fit together into one working day with an autonomous software team. Every section has screenshots taken from a real, finished demo project (an *inventory-app* built by the offline template engine), so what you see here is what you will see on your own machine.

> **How the screenshots were made.** They were produced by `scripts/capture_manual.py` against a demo project generated with the model-free **Template** engine, so the text the "agents" wrote is placeholder text. The structure, buttons and flows are identical to a real run driven by Claude. See [Reproducing the screenshots](#19-reproducing-the-screenshots).

---

## Contents

1. [What FS-SC is and how to think about it](#1-what-fs-sc-is-and-how-to-think-about-it)
2. [Getting started in five minutes](#2-getting-started-in-five-minutes)
3. [Anatomy of the dashboard](#3-anatomy-of-the-dashboard)
4. [The top bar](#4-the-top-bar)
5. [Goals and the sprint KPI strip](#5-goals-and-the-sprint-kpi-strip)
6. [Board — planning and tracking work](#6-board--planning-and-tracking-work)
7. [Agent Mesh — watching the team think](#7-agent-mesh--watching-the-team-think)
8. [Files and Docs — what the team produced](#8-files-and-docs--what-the-team-produced)
9. [Deliberation and Questions — decisions with the team](#9-deliberation-and-questions--decisions-with-the-team)
10. [Tests — E2E center and test management](#10-tests--e2e-center-and-test-management)
11. [Reports — metrics for the manager](#11-reports--metrics-for-the-manager)
12. [Settings menu and its dialogs](#12-settings-menu-and-its-dialogs)
13. [The bottom dock](#13-the-bottom-dock)
14. [A complete run, step by step](#14-a-complete-run-step-by-step)
15. [Sprint mode, the definition of done and verification](#15-sprint-mode-the-definition-of-done-and-verification)
16. [What FS-SC writes into your project](#16-what-fs-sc-writes-into-your-project)
17. [Safety and control](#17-safety-and-control)
18. [Troubleshooting and FAQ](#18-troubleshooting-and-faq)
19. [Reproducing the screenshots](#19-reproducing-the-screenshots)
20. [Glossary](#20-glossary)

---

## 1. What FS-SC is and how to think about it

FS-SC simulates a small software company. Twelve role-playing agents — **PM, PO, Architect, Backend, Frontend, QA, E2E Tester, DevOps, Reporter, Documentor, SCM and Scrum Master** — plan, build, verify and ship an application. Four optional specialists (Mobile UI/UX Designer, Security Engineer, SEO Optimizer, Code Reviewer) can be enabled, and you can define your own agents.

**There is no API key.** The server never calls a model. Your AI client (Claude Desktop, Claude Code or Google Antigravity) *is* the engine: it asks the server for the next step, produces it with its own model and your own subscription, and hands the result back. The server is the coordinator, the referee and the book-keeper; the dashboard is the window onto everything.

```
 AI client (Claude / Antigravity)           FS-SC server                           Dashboard
 ────────────────────────────────           ────────────────────────────           ───────────────────
 get_next_step      ───────────────▶        prepares role prompt + context
 produces one JSON envelope                  
 submit_step_result ───────────────▶        validates, writes files into your
                                            project, runs tests, commits,         shows board, agents,
                                            updates Jira board, picks next step   evidence, reports (live)
```

### Key ideas you will meet on every screen

| Idea | Meaning |
|---|---|
| **Project** | A folder on your machine. FS-SC writes the product into it and keeps its own state in a hidden `.fs-workspace/` folder inside it. You can connect many projects and switch between them. |
| **Run** | One execution of the pipeline for a project. A run is a numbered list of **steps**; the server may insert more steps while it runs (backlog tasks, fix rounds, sprint ceremonies). |
| **Step** | One piece of work by one agent (for example "Architect designs the system", "Backend implements task T-04"). Every step produces files, a summary and hand-off notes. |
| **Issue** | A card on the built-in Jira-style board: **epic → story → task** (and **bug**). Tasks carry acceptance criteria (`AC-1`, `AC-2` …). |
| **Sprint** | A time-boxed batch of tasks with a goal, a capacity and a commitment. Sprint mode is the recommended way of working. |
| **Definition of done (DoD)** | The evidence the server demands before a task counts as finished: files that exist, tests that ran, criteria mapped to tests. |
| **Decision** | A technology choice (language, database, hosting …) that **you** make. Agents never decide these silently. |
| **Manager note** | A free-text instruction from you that becomes the agents' top-priority input on the next step. |

---

## 2. Getting started in five minutes

The full installation instructions are in the [README](../README.md); the short version:

1. **Install and start the server**

   ```powershell
   powershell -ExecutionPolicy Bypass -File scripts\fssc.ps1 install
   powershell -ExecutionPolicy Bypass -File scripts\fssc.ps1 build
   powershell -ExecutionPolicy Bypass -File scripts\fssc.ps1 start -Background
   ```

   Open <http://127.0.0.1:8099>. Keep the server in its own process — if it lives inside a client session, closing that session drops the run.

2. **Connect an AI client** — Claude Code (open the folder; `.mcp.json` registers the server), Claude Desktop (`python scripts\register_claude_desktop.py --restart`) or Antigravity (project `.agents/mcp_config.json`). The *Claude Bridge* dialog ([§12.8](#128-claude-bridge)) shows whether a client is connected and gives you the exact prompt to type.

3. **Add a project** — project switcher → **Add New** ([§4.1](#41-project-switcher)). Choose an empty folder, the project language and the folder layout.

4. **Give it a specification** — *Client Vault* ([§12.2](#122-client-vault)). Paste meeting notes or upload documents.

5. **Start the run** — in your AI client, with the project folder open, type:

   ```
   Run the pipeline for the inventory-app project
   ```

   Answer the **technology decisions** when the dashboard asks, then watch the board fill.

No client at hand? Choose the **Template** engine in the *Model* dialog ([§12.7](#127-model--engine)) and the server simulates all roles itself — a free, instant rehearsal of the complete loop.

---

## 3. Anatomy of the dashboard

![The dashboard on first load — Agent Mesh view](images/manual/01-overview.png)

The window has five regions:

| Region | Where | What it holds |
|---|---|---|
| **Navigation rail** | far left | Board, Agent Mesh, Files, Docs, Deliberation, Questions, Tests, Reports and, at the bottom, Settings. Items that open a dialog (Files, Docs, Deliberation, Questions) are overlays; the others change the main view. |
| **Top bar** | top | Project switcher, sprint chip, search, connection and token indicators, approval mode, notifications, language and configuration. |
| **Strips** | under the top bar | The *Goals* strip and the sprint KPI strip. Banners (project paused, decisions pending, step approval, questions) appear here when something needs you. |
| **Work area** | centre | The view selected in the rail — the board, the agent topology or the reports. |
| **Bottom dock** | bottom | *Timeline* (replay of everything that happened) and *Live Sprint & Kanban* (a compact live board). |

Colour and badge conventions used throughout: **green** = done / passed / connected, **amber** = in progress or needs attention, **red** = failed / blocked, **blue** = information or a role label. Role names appear as small chips (for example `Senior Backend`, `QA`). Mono-spaced text is an identifier, a file path or a command.

---

## 4. The top bar

### 4.1 Project switcher

![Project switcher listing connected projects](images/manual/80-project-switcher.png)

Click the project name (top-left) to see every connected project with its event count, issue count and number of specifications. The active project carries an **Active** badge; the check mark switches to a project and the bin icon disconnects it (files on disk stay untouched).

![Adding a new project](images/manual/87-add-project.png)

**Add New** opens the connect form:

- **Directory path** — type a path or press **Browse**. A missing folder is created.
- **Project name** — optional; defaults to the folder name.
- **Project language** — English or Türkçe. It controls the language of the documents, Jira texts, meeting minutes and prompts the agents write. It is independent of the dashboard language.
- **Folder layout** — *apps/ devops/ docs/* (recommended for new projects: each application under `apps/<role>`, Dockerfiles and compose files under `devops/`, documents under `docs/`) or *Flat layout* (product code in the project root; used for existing codebases).

**Connect** registers the folder, creates `.fs-workspace/`, writes `.mcp.json` and the `CLAUDE.md` / `GEMINI.md` instruction blocks, and initialises git when missing.

### 4.2 Sprint chip and search

The chip next to the project name (**Sprint 4**) shows the sprint currently shown in the KPI strip. The search box filters the board by issue key, title, description or acceptance criterion; press `/` anywhere to focus it.

![Searching the board](images/manual/84-search.png)

Results keep their epic and story context, so you can see *where* a match lives in the hierarchy.

### 4.3 Connection, tokens and approval mode

- The **green dot** means the dashboard is connected to the server over WebSocket.
- The **token counter** (for example `142k token`) is the running total of tokens reported by the agents for the project.
- The **approval mode** button controls how much the team may do without asking you:

![Approval mode menu](images/manual/81-approval-mode.png)

| Mode | Behaviour |
|---|---|
| **Every step** | The run waits for your approval after every step (default for cautious work). |
| **Critical** | Stops only at critical steps: architecture (2), QA decision (6), deployment (8), UAT (9) and failed steps. |
| **Note only** | The agent raises a hand, a note is recorded and the run continues; it waits only on a failed step. |
| **Automatic** | Never stops. Technology decisions still need you. |

The **Raised hands** line lists notes agents have raised that you have not reviewed yet.

### 4.4 Notification center

![Notification center](images/manual/82-notification-center.png)

The bell collects sprint blockers, budget warnings, pending questions, autonomy events and similar items, with **mark read** and **clear** actions.

### 4.5 Language switcher

![Language switcher](images/manual/83-language-switcher.png)

Switches the **dashboard** between English, Türkçe, Español and Deutsch. This changes only the interface; agent output follows the *project* language ([§4.1](#41-project-switcher)).

### 4.6 Configuration menu (gear)

![Configuration menu](images/manual/85-configuration-menu.png)

- **Project settings** shortcut (sprint, budget, autonomy).
- **Language** selector.
- **Appearance** — *Light* / *Dark*, a font-size scale (XS to XL) and the accent colour.
- **Project folder** — the active project's path with **Browse** and **Bind** to point the dashboard at another folder.
- **Reset telemetry** — clears the stored event log and counters of the active project (the board and files are not affected).

---

## 5. Goals and the sprint KPI strip

![Goals dialog](images/manual/88-add-goal.png)

The **Goals** strip states what the team is working towards. With *no open goal* the system runs the whole backlog. Press **Add goal** and write one — for example "Implement the approved screens to match the mockups; do not write tests" — and from then on only goal-linked work is done. Goals are the quickest way to focus a run without editing the backlog.

The four KPI tiles under it summarise the current or last sprint:

| Tile | Meaning |
|---|---|
| **Sprint N · status** `x / y tasks` | Tasks completed versus committed in the sprint. Click it to jump to the sprint view. |
| **Velocity (last 3 sprints)** | Average number of tasks completed per sprint. |
| **Open bugs** | Bugs not yet in a done state. |
| **Predictability** | Completed ÷ committed across closed sprints. |

---

## 6. Board — planning and tracking work

The board is a full Jira-style tracker. It is the source of truth for what the team will do and what it has done.

### 6.1 Tree view

![Board, tree view](images/manual/02-board-tree.png)

The default view groups issues as **epic → story → task**. Click the chevron to expand a row; the badge on the right shows the sub-item count, the assignee role and the status (*Backlog*, *In progress*, *Completed* …). A grey system epic called *Other items (not linked to an epic)* gathers legacy or orphan items; new items are linked automatically.

![An epic expanded](images/manual/06-board-epic-expanded.png)

### 6.2 The toolbar

From left to right: the four view buttons (**Tree, Order, Sprint, Kanban**), then **Filters**, **Selection**, **More** and **New Issue**. Under it, the **status pills** (All, Backlog, Selected for Dev, In Progress, In Review / QA Handshake, Done) with live counts, a progress bar showing finished items, and filters for **Sprint**, **role** and **work type**. **Hide done** collapses finished work and **This run** limits the list to items touched by the current run.

![Done filter applied](images/manual/11-board-done-filter.png)

Applying the *Done* pill expands finished epics so you can audit what was delivered. Each task row shows:

- the key and `#id`, the type chip (TASK, BUG …) and the linked step (`T-04`);
- a **verification** chip and the **commit** hash once the server verified and committed the delivery;
- the sprint (`S2`), the assigned role and the status;
- row actions — **Only this step** (run just this item as a single-step run), **Inspect**, **History (n)** and **Edit**.

### 6.3 Order view

![Board, order view](images/manual/03-board-order.png)

A flat, numbered list in execution order with checkboxes. Use it to choose exactly which items a run executes and in which order; drag the order or use the priority fields in the item.

### 6.4 Sprint view

![Board, sprint view](images/manual/04-board-sprint.png)

The sprint view shows the **sprint board** of the selected sprint — goal, capacity, commitment, who committed (the server in automatic mode), committed items with their status, and a burndown chart — followed by a card for every sprint (`Sprint 1 · CLOSED  3/3`) and the **Backlog (not assigned to a sprint)**.

![A sprint expanded](images/manual/04b-board-sprint-expanded.png)

Buttons on the sprint header: **Plan next sprint** (asks the server to plan the next sprint now), **PI reports** (opens [Reports](#11-reports--metrics-for-the-manager)) and **refresh**. Each closed sprint keeps its metrics, retrospective and carry-over list.

### 6.5 Kanban view

![Board, Kanban view](images/manual/05-board-kanban.png)

Five columns — **Backlog**, **Selected for Dev**, **In Progress (agent execution)**, **In Review / QA Handshake** and **Done (completed)**. Cards show the type, priority, title, description, assigned role and the *Only this step*, *Inspect* and *History* shortcuts. Change a card's status in its drawer or through the bulk actions panel.

### 6.6 Filters, saved filters and deleted items

![Filters menu](images/manual/07-board-filters.png)

The **Filters** menu lists your *saved filters* (type a query in the search box and save it with a name) and a **Show deleted** switch. Deleting an issue is reversible: it moves to the deleted list and can be restored from its drawer.

### 6.7 Selection and bulk actions

![Selection menu](images/manual/08-board-selection-menu.png)

The **Selection** menu decides what a run executes and what a bulk action touches:

- **Select all** / **Clear selection**
- **Main items (1-10)** — the ten fixed phase items
- **Tests only** — only the QA and E2E items
- **Bulk actions panel…** — change the status, sprint, priority, assignee or labels of every selected item at once (you are asked to confirm; a warning appears when *all* items are selected).

### 6.8 The *More* menu

![More menu](images/manual/09-board-more-menu.png)

- **Upload specification** — opens the [Client Vault](#122-client-vault).
- **Documents** — opens the project [documents](#8-files-and-docs--what-the-team-produced).
- **Approval mode** — the same four modes as in the top bar, with a short explanation of each.
- **Show deleted** — include deleted items.

### 6.9 Creating an issue

![New issue dialog](images/manual/10-new-issue.png)

**New Issue** adds a task or bug by hand: title, **record type**, **responsible agent**, **priority** (P0–P3), **parent task** (or automatic), **priority lane** (*Normal*, *Do first*, *Next sprint start*), an instruction/description for the agents and **acceptance criteria** (one per line). *Do first* inserts the work as the very next step of the running run; *Next sprint start* puts it at the front of the next sprint. Only one run executes at a time and nothing runs in parallel.

### 6.10 The issue drawer

Click the `#id` chip of any item to open its drawer. The header shows key, type and title; below are editable **Status, Priority, Assignee, Estimate, Due date, Sprint, Labels, Components, Parent** and **Watchers** fields, then seven tabs.

![Issue drawer — details](images/manual/12-issue-drawer.png)

**Details** — description and acceptance criteria. Edit and press **Save**. *Delete (reversible)* is at the bottom together with the created/updated timestamps.

![Issue drawer — comments](images/manual/13-issue-drawer-comments.png)

**Comments** — Markdown comments. Agents read these as context, so a comment is a precise way to give a task-specific instruction.

![Issue drawer — links](images/manual/13-issue-drawer-links.png)

**Links** — relationships to other items (*relates to*, *blocks*, *is blocked by*, *duplicates* …).

![Issue drawer — attachments](images/manual/13-issue-drawer-attachments.png)

**Attachments** — reference a file by name and project path or URL.

![Issue drawer — history](images/manual/13-issue-drawer-history.png)

**History** — a field-level change log plus a *Why in this state* explanation of the last status transition.

![Issue drawer — work](images/manual/13-issue-drawer-work.png)

**Work** — what each step did for this item: which agent, which step, the commit, the verification result and the files, with a link to inspect the step.

![Issue drawer — evidence](images/manual/13-issue-drawer-evidence.png)

**Evidence** — the proof the server collected, split into four boxes: **Who · which step · which commit**, **Verification** (the actual test run), **DoD checklist** (strict definition of done) and **AC coverage** (each acceptance criterion and the test or evidence that covers it, with *no evidence* flagged in red).

### 6.11 Inspecting a step

![Step inspector](images/manual/14-step-inspector.png)

**Inspect** on a task row opens the step inspector: the step number, task, status (for example *Completed & Verified*), the agent and the output kind, tokens used, a plain-language statement of *what the agent did*, every **generated file** with its content, the **server verification** (the exact command, its result and duration) and the **verification status** summary. For a step still awaiting approval this window also offers *Approve*, *Approve all remaining automatically* and *Revise with feedback*.

### 6.12 Task audit trail

![Task audit trail](images/manual/15-task-audit-history.png)

**History (n)** on a task row opens its chronological audit trail — created by the architect, committed to a sprint, step started, verification passed, committed by SCM, step done — with timestamps and the actor. Use the box at the bottom to *Add Note*: a progress comment for the audit trail.

---

## 7. Agent Mesh — watching the team think

![Agent mesh](images/manual/20-agent-mesh.png)

The mesh is a live map of the company. Each card is an agent with its role, current status (*IDLE*, *WORKING*, *COMPLETED*), the file it is touching, the tokens it has used and its latest message type. Lines between cards are the messages agents exchange — contract confirmations, code submissions, bug reports, UAT approvals, sprint-closed notices. Use the controls at the lower left to zoom, fit the view or lock it; the mini-map is at the lower right.

![Live team conversation](images/manual/21-agent-mesh-conversation.png)

The **conversation toggle** on each card shows the agent's latest speech bubble, and a banner at the bottom shows the *Live Team Conversation* — for example the Scrum Master telling the PM that a sprint closed.

![Agent timeline drawer](images/manual/23-agent-timeline-drawer.png)

Click a card to open the **agent timeline**: counters for *Events*, *Decisions*, *Notes* and estimated *Tokens*, then a day-by-day list of everything the agent did — status changes, submitted code, bug reports, hand-offs — each with its thought, action and output.

![Agent interactions](images/manual/24-agent-timeline-interactions.png)

The **Interactions** tab lists the other agents it talked to, with counts of messages sent and received and the last message type.

---

## 8. Files and Docs — what the team produced

### 8.1 Files

![Project files](images/manual/30-files.png)

A read-only explorer for the project folder. Use **A−** / **A+** to change the viewer font size. Folders expand in place; click a file to read it with syntax highlighting.

![Folder expanded](images/manual/31-files-tree-open.png)

In a new project you will see `apps/`, `devops/` and `docs/`, plus `.gitignore`, `.mcp.json`, `CLAUDE.md`, `GEMINI.md` and `README.md` in the root. The FS-SC internal state in `.fs-workspace/` is hidden here.

### 8.2 Docs

![Project documents](images/manual/32-docs.png)

A document browser grouped by category: **Project root**, **Documents** (PRD, QA report, TECH_REQUIREMENTS, OpenAPI spec, handshake sync, user guide, task cards), **ADR** (architecture decision records), **Meeting** (minutes), plus tests and scenarios. A search box filters by file name. Choose **View** for rendered Markdown or **Code** for the raw source.

![A task card rendered](images/manual/33-docs-prd.png)

![The same file as code](images/manual/34-docs-code-view.png)

The documents are real files in the project's `docs/` folder — commit them, review them or hand them to a customer.

---

## 9. Deliberation and Questions — decisions with the team

### 9.1 Deliberation room

![Deliberation room](images/manual/40-deliberation.png)

A place where agents from different disciplines discuss a topic and reach a consensus before tasks are created. **Current** shows the active session; the **Start Deliberation** field starts one on a custom topic (leave it empty to discuss the current specification). The Architect puts two or three alternative plans on the table and the others react.

![Deliberation history](images/manual/41-deliberation-history.png)

**History** lists every past session — sprint kick-off, planning and review/retro meetings — with its summary, number of rounds and messages. Opening one shows the full minutes.

### 9.2 Questions

![Open questions](images/manual/42-questions.png)

Agents raise questions in their deliveries. **Open** shows the ones waiting for an answer and, while any are blocking, a banner warns that the sprint is halted. Answer in the dialog or leave them: after the configured question timeout, non-technology questions are answered with the agent's recommended option and recorded as an assumption.

![All questions](images/manual/43-questions-all.png)

**All** is the full log: category (*Design*, *Technology* …), who raised it, the question, the answer and who or what answered (*SERVER* default, you, or a dry run). **Technology** questions can **never** be answered by an agent — only by you, from the dashboard.

---

## 10. Tests — E2E center and test management

![Tests menu](images/manual/50-tests-menu.png)

The **Tests** rail item opens a menu: *Playwright E2E* (with the count of stored runs), *Test Management* and *Run Tests Only*.

### 10.1 Playwright E2E test center

![Playwright E2E center](images/manual/51-playwright-e2e.png)

Run a real browser test against any web address:

1. **Ready-made test user templates** — one-click role presets (admin, standard user, editor, finance, negative test). Save your own.
2. **Target web address and credentials** — URL, user name / e-mail, password and the **role / permission level**.
3. **Test scenario** — a short description ("User login & UI verification").
4. **Run Playwright E2E Test** or **Run Only the Test Suite (QA Lead + E2E)**.

Below you will find the latest result with screenshots, the Playwright engine console log and the history of past runs (`E2E-001` …). In a pipeline run, step 7 starts the real application and drives it automatically; this screen is for manual runs and investigation.

### 10.2 Test management

![Test management summary](images/manual/52-test-management.png)

Real evidence produced by QA and executed by the server. The header shows coverage and the regression gate. **Summary** tiles: *Acceptance criteria coverage* against the target (80 % by default), *Test cases*, *Latest results*, *Open bugs / flaky*, the **regression gate** and *uncovered criteria*. The **Settings** block sets the coverage target, the performance p95 threshold and whether the server automatically adds the QA test-design task in strict DoD.

![Test cases](images/manual/53-test-management-cases.png)

**Cases** — test cases `TC-n` derived by QA from acceptance criteria, filterable by status, type and result, with *New case* for manual ones. A case is linked to automation by an `AUTOMATED:<test name>` note or by naming `TC-n` in the test name or file.

![Runs](images/manual/53-test-management-runs.png)

**Runs** — every verification, QA and E2E execution. A failing case automatically opens a bug; a case that alternates between pass and fail is quarantined as flaky.

![Traceability](images/manual/53-test-management-traceability.png)

**Traceability** — the matrix criterion → test cases → mentioned tests, with each criterion's status (*no case*, *covered*, *failing*).

![E2E scenarios](images/manual/53-test-management-e2e-scenarios.png)

**E2E scenarios** — browser scenarios linked to criteria. A passing scenario is the evidence for its criterion. Tests locate elements through a stable `data-testid` contract.

![Test plan](images/manual/53-test-management-test-plan.png)

**Test plan** — a generated plan per sprint: goal, scope, risks, exit criteria and the regression set. **Write to file** saves it as `docs/tests/plan-sprint-N.md`.

---

## 11. Reports — metrics for the manager

![PI planning reports](images/manual/60-reports.png)

Reports are generated from Jira tasks and sprint records. Switch between **Whole project** and **Sprint** (with a sprint picker), **Refresh**, or **Print / PDF** to export.

Headline tiles: **done / total tasks**, **closed sprints**, **predictability**, **open bugs**, **velocity**, **remaining work**, **estimated finish** at the current velocity and **average cycle time**. Charts: **Sprint burndown** (work left versus the ideal line), **Velocity — committed and completed**, **Burnup — scope and done** and **Cumulative flow (CFD)**; a widening in-progress band signals a bottleneck.

![Scrolled reports](images/manual/61-reports-scrolled.png)

![Sprint report](images/manual/62-reports-sprint.png)

The **Sprint** scope adds the sprint's own numbers: *done / committed*, carried over, scope changes, first-pass rate, fix rounds, UAT rejections and active time, with the burndown of that sprint.

---

## 12. Settings menu and its dialogs

![Settings menu](images/manual/70-settings-menu.png)

The **Settings** entry at the bottom of the rail lists everything you configure rarely. Items with a badge (Client Vault, Runs) show a count.

### 12.1 Project settings

![Project settings](images/manual/71-project-settings.png)

**Sprint planning (`sprint.*`)** — changes take effect at the next sprint planning:

| Setting | Meaning |
|---|---|
| Sprint mode | Off = the fixed 1-10 flow runs. On = sprint ceremonies and backlog sprints. |
| Chain sprints automatically | When a sprint closes, the next one is planned immediately. |
| Commitment approval | *Automatic* (server commits), *Manual* (you approve) or *timeout default*. |
| Max / min tasks per sprint | Capacity ceiling and floor. |
| Min frontend tasks, feature share, max test work share | Mix rules so UI work, features and test work stay balanced. |
| Criteria test batch size | Acceptance criteria without evidence are grouped into one test task of this size. |
| Carry-over limit | How many sprints the same item may be carried over. |
| WIP limit | Warning threshold for simultaneous in-progress work (0 = off). |
| Max sprint count | The project pauses when reached (the smaller of this and the budget limit applies). |
| **Pause test writing temporarily** | While on, no test work is taken into sprints, agents are told not to write tests and the DoD test condition is waived. |

**Server verification** — the *scope* (incremental: only tests of changed files, or full) and *light verification* (only lint + changed tests in incremental steps; build only in full verification).

![Project settings, scrolled](images/manual/71-project-settings-scrolled.png)

**Design (Designer)** — optional link to a design canvas the Designer reads. **Project language** — output language for the agents (save to apply). **Agent skills** — per agent, choose extra skill guides from the catalog (backend guidelines, API design, accessibility, security …); the guides are advisory and the task's acceptance criteria always take priority. Skills are only *referenced* by link and cached locally.

![Budget and autonomy switches](images/manual/71-project-settings-scrolled-2.png)

**Budget limits (autonomy.budget)** — sprint active time, steps per sprint, sprint and task token limits, consecutive failed steps, steps without progress, the number of sprints in the project and a warning threshold (%). When a limit is reached the sprint pauses until you raise it. **Autonomy switches** — *Strict definition of done* (deliveries without tests are not accepted) and the *question timeout* in seconds (empty waits indefinitely, `0` answers immediately with the recommendation).

### 12.2 Client Vault

![Customer meetings and specification vault](images/manual/72-client-vault.png)

The vault is where requirements enter the system. Each entry has a **customer / organisation name**, a **meeting title**, **meeting notes** (Markdown) and optional **specification / design / mockup files** (Word, TXT, MD, JSON are read; PNG/JPG are stored but not read). With **Automatically analyse uploaded documents and generate Jira tasks** ticked, **Save, Analyse & Generate Jira Tasks** stores the entry and queues a run; the PM and Architect analyse it and shape the backlog. Below, **Saved customer specifications** lists every upload with its upload time, run status (*COMPLETED*), edit and delete icons and **Extract Jira Tasks** to analyse an entry again. Everything is stored permanently inside the project folder.

### 12.3 Decisions

![Technology and architecture decisions](images/manual/73-decisions.png)

Before the architect designs anything, FS-SC asks you to choose: **backend language and framework**, **database**, **client / UI**, **authentication**, **hosting and deployment**, **real-time layer** and **test tools**. Each option shows a *recommended* badge and a one-line reason; pick one or write your own under *Other…*. Add *extra notes / constraints* at the bottom. **Reset** restores the recommendations; **Save** applies the answers to every following step. You can reopen this dialog any time — changes apply from the next step. A new library that is not on the approved list opens a fresh decision instead of being used silently.

### 12.4 Runs

![Run history](images/manual/74-runs.png)

Every run with its status (*COMPLETED*, *ACTIVE*, *CANCELLED* …), engine (`template-engine`, `mcp-client`), the step chips that were executed (`#1 PM`, `#2 ARCHITECT` …), progress (`46/46 steps`) and duration. **Run again** restarts the same step selection. Each step status can be tested on its own.

### 12.5 Add agent — the Company Agents & Expert Management Center

![Add agent](images/manual/75-add-agent.png)

Define a new expert for the company team:

- **Agent name**, **role & responsibility** (the base role whose prompt template and permissions it inherits — for example `BACKEND_DEV`) and the **working file** it is responsible for.
- **Capabilities and profile** — the work types it takes (`SCAFFOLD, FEATURE, TEST, E2E_SCENARIO, DEVOPS, DOCS, BUG, IMPROVEMENT, REFACTOR, REVIEW`), **focus keywords** (tasks mentioning them are routed to this agent), a model hint, effort, language, token limits, scope (*this project only* or *also add to the agent pool*) and an *extra instruction* appended to the prompt template.
- **Team templates** — add a whole team in one click (for example a Mobile team or a Data team); existing agents are skipped. You can also *Import agent package*.

Below the form, **Registered company agents** lists every agent with its status, token usage, **.md Memory** (the Markdown guide with version history that you can edit; every change is a versioned snapshot you can roll back) and **Edit**.

### 12.6 Management Center

![Management Center — meetings and ADR](images/manual/76-management-center.png)

**Meetings & ADR** — the list of meetings (kick-off, planning, review/retro per sprint) on the left, **decision records** on the right (ADR 0001 *Technology stack setup*, error-response schema per sprint …). Select a meeting to read its minutes.

![Work plan](images/manual/76-management-center-work-plan.png)

**Work plan** — the full hierarchy epic → story → task with status, assignee, work type and sprint.

![Learning loop](images/manual/76-management-center-learning.png)

**Learning** — the sprint trend table (committed / done, first-pass rate, fix rounds, rejected deliveries, carried over), **retro actions** (each applied action, for example a prompt change or a new backlog item) and **prompt changes** with a **Roll back** button. This is how the team improves its own prompts from sprint to sprint.

![Claude activity](images/manual/76-management-center-claude-activity.png)

**Claude activity** — the *runner* status (is a client pulling work?), connected **MCP clients**, a summary and the recent events.

### 12.7 Model / engine

![Model and engine](images/manual/77-model-switcher.png)

- **0. Execution engine** — **MCP Client** (Claude / Antigravity produce every step through the server) or **Template (Offline)** (the server simulates all roles with ready-made outputs: a free, deterministic rehearsal).
- **0B. Flow speed** — *Natural* (human-paced pauses; template engine only) or *Instant*.
- **0C. Automatic development loop** — three switches: **Backlog → task steps** (the architect's tasks are added to the run), **Server verification** (syntax, install, lint, build, test after every delivery; a failure opens a fix round) and **SCM commit** (a verified delivery is committed). Plus **Fix rounds / task**, **Max tasks**, **UAT improvement rounds** and the **verification / run commands** (install, test, build, lint, run-for-E2E, health URL). Empty fields are inferred from `requirements.txt`, `package.json`, `composer.json` or `go.mod`. Commands run on *your* machine; suggestions from agents pass a deny-list first.

![Autonomy levels and isolation](images/manual/77-model-switcher-scrolled.png)

Further down: the **autonomy levels** (*L0 Supervised* — every step waits for approval; *L1 Critical* — approval only on critical steps; *L2 Note and continue*; *L3 Fully autonomous* — no approval, questions answered after a timeout), the **sprint budget**, the **L3 prerequisites checklist** (verification test defined, runner reachable, command isolation on, budgets defined, repository present) and **command isolation / policy** (run commands in a container with an allow-list). **Apply & Save Model** stores the engine for the active project.

### 12.8 Claude Bridge

![Claude Bridge — status](images/manual/78-claude-bridge.png)

Whose turn is it? The header shows *IDLE / No active run* or the current step, with **Open in a separate tab**. **Status** explains the pull model (FS-SC never pushes; Claude pulls the work), shows the connection (*Never connected* until a client calls a tool), and gives the prompt to type: `Run the pipeline for project <id>` with a **Copy** button. *Recent tool calls* streams the summary of calls in real time.

![Start and connect](images/manual/78-claude-bridge-start-connect.png)

**Start & Connect** — the **run watchdog** (when a run drops because the client closed or the server restarted, the watchdog advances it automatically: polling interval while running, a longer interval while paused, abandon threshold), a **driver setup checklist** (server reachable, independent server process, MCP registration, Claude Code CLI, auto-runner, scheduled task) and the **Claude Code CLI** command and session information.

![Interaction log](images/manual/78-claude-bridge-interaction-log.png)

**Interaction log** — a two-way log of every tool call between Claude and FS-SC (direction, tool, run filters, text search, *Export as Markdown*). A *Session mirror* tab can show the client's own session transcript when Claude Code's session files are available on the same machine.

### 12.9 Live Telemetry

![Live telemetry](images/manual/79-live-telemetry.png)

A searchable stream of every event the server emits, with filters **All / Errors / Bugs / Successful**. Each entry shows the agents involved (`PO → DOCUMENTOR`), the event type (`HANDOFF`, `UAT_APPROVED`, `START_THINKING` …), the status, the time and the token count. Use it to understand *exactly* what happened when the board does not show what you expect.

### 12.10 Start design now, link orphans, restore agents

- **Start design now (mockup)** — queues a Designer task right after the current step: a design system plus first screens as HTML mockups. After you approve it, every screen becomes a frontend task.
- **Link orphan issues to epic** — shows a plan of which orphan items would be attached to which story or epic and, after confirmation, applies it (recorded in the audit trail).
- **Restore default agents** — brings back default agents you removed (Mobile Designer, Security, SEO Optimizer, Code Reviewer).

### 12.11 Budget page

![Sprint budget page](images/manual/86-budget-page.png)

A standalone page (opens in a new tab, also reachable from the banner *Raise budget by 10 and continue*) to edit the sprint budget and resume a blocked project: active time, max steps, sprint and task token limits, consecutive failed steps, stalled steps, project sprint count and warning threshold. **1) Save** stores the new limits and **2) Unblock and resume** restarts the paused sprint. The language buttons at the top switch the page language.

---

## 13. The bottom dock

![Timeline dock](images/manual/90-dock-timeline.png)

**Timeline · live** is a replay bar for everything that happened in the project. Press **Play timeline** to watch events stream in order, pick a speed (1×, 2×, 4×), step back and forward, or drag the slider. *LIVE BROADCAST (LIVE)* means you are following the present.

![Live sprint and Kanban dock](images/manual/91-dock-live-sprint.png)

**Live Sprint & Kanban** shows a compact status board with the number of tasks per stage (Backlog (PM), Architecture, In Development, QA & Edge Cases, DevOps & Deploy, Released / Live). The counters in the collapsed bar (`Backlog 0 · Arch 0 · Dev 0 · QA 17 · DevOps 0 · Live 1`) stay visible at all times.

---

## 14. A complete run, step by step

This is the life of one project from an empty folder to a delivered product.

1. **Connect the project** (§4.1) and choose language and layout.
2. **Describe the product** in the Client Vault (§12.2). Good notes name users, the main functions, constraints and the delivery form.
3. **Queue the run.** With *Analyse & Generate Jira Tasks* the run waits in the queue; the banner says *Run queued*.
4. **Start your AI client** in the project folder and type `Run the pipeline for the <project> project`. The run becomes **ACTIVE** on the first `get_next_step` call.
5. **PM step (1).** The PM turns your notes into a PRD and lists open technology questions.
6. **Technology decisions gate.** The *Decisions* dialog opens (§12.3). Choose; the answers cascade to every later step.
7. **Architect step (2).** Architecture, OpenAPI contract, data models, the **backlog** (tasks with role, acceptance criteria and dependencies) and the **verification commands** are produced. An optional deliberation (§9.1) precedes it.
8. **Skeletons (3, 4).** Backend and client skeletons are written into `apps/…`.
9. **Backlog tasks.** For each task: the assigned agent delivers code **and tests** → the server runs the checks (syntax, install, lint, build, tests) → on failure a **fix round** is opened for the same task (`max_fix_rounds`, default 2) → on success **SCM commits** (`feat(JIRA-x)` / `fix(JIRA-x)`).
10. **Handshake (5).** Backend and Frontend confirm the API contract against each other — runs on the server.
11. **QA (6).** QA derives test cases from acceptance criteria and the server runs the suite.
12. **E2E (7).** The server starts the real application and Playwright drives Chromium through the scenarios.
13. **DevOps (8).** Dockerfile and compose files are written under `devops/`.
14. **PO UAT (9).** The Product Owner decides **per acceptance criterion**, with evidence. A rejection turns `improvements[]` into new tasks; QA and UAT run again (`max_uat_rounds`).
15. **Docs (10).** The Documentor writes the user guide and the Reporter the status report and changelog.
16. **Sprint close.** The architect reviews the diff, the retro and the next plan are written, and the project is tagged.

**While it runs you can:**

- add a **manager note** (it becomes the top-priority instruction for the next step; an *urgent* note pauses the run);
- **pause / resume / cancel** from the run controls in the banner;
- **approve, approve everything that remains, or revise** a step that waits for approval — *Revise* regenerates the same step from scratch with your feedback (available for phase, structure, task and fix steps);
- **answer questions** (§9.2) and **raise the budget** if a sprint pauses;
- **change the order** or add *Do first* work from the board (§6.9).

If the client closes or the server restarts, the run becomes *abandoned*; typing the same prompt **resumes it from the step where it stopped**. Starting over from scratch needs an explicit confirmation on the dashboard.

---

## 15. Sprint mode, the definition of done and verification

### Sprint mode (recommended)

Work runs sprint by sprint:

1. **Planning** — the Scrum Master proposes a goal and a commitment within the capacity rules (§12.1).
2. **Daily steps** — tasks run in priority order; test work, feature work and UI work are balanced by the share settings.
3. **Architect review** — at sprint end the architect reviews the actual diff and the evidence (`kind: review`) and files findings.
4. **Review / retro** — results, carry-overs and retro actions are recorded; prompt improvements can be proposed.
5. **Re-scoping** — the next sprint is planned (automatically when *Chain sprints* is on).

With sprint mode **off**, the fixed ten-phase flow runs unchanged.

### Definition of done (strict DoD)

A task counts as finished only when:

- the delivery **comes with tests**; deliveries without tests, or with skipped verification, are not accepted;
- every acceptance criterion is **mapped to evidence** (a test that mentions `AC-n`, or an E2E scenario);
- verification **passed** on this machine and a **commit** exists;
- no secret (key, password) is in the delivery — the server refuses to commit when one is found.

At sprint close the DoD additionally asks for an executed **regression set**, an architect review and PO decisions per criterion. The *Evidence* tab (§6.10) shows each part for each task.

### Verification, fix rounds and commits

After every code delivery the server runs: **syntax → install → lint → build → test**. If one fails, a **fix step** (`kind: fix`) is inserted with the failing output as context; weakening or deleting tests is forbidden. After `max_fix_rounds` failures the task is marked failed and reported. Passing deliveries are committed by the SCM agent with a conventional message and the Jira key.

---

## 16. What FS-SC writes into your project

```
<project>/
├─ apps/<role>/…                  product code, one folder per application (backend, web, mobile …)
├─ devops/                        Dockerfile*, docker-compose*, CI — always here, never in the root
├─ docs/                          PRD, architecture, OpenAPI spec, ADRs, meeting minutes, task cards,
│                                 test plans, user guide, reports
├─ .fs-workspace/                 FS-SC state: settings.json, jira_issues.json, specs, tmp/ …  (git-ignored)
├─ .mcp.json  .agents/            client connection files (machine specific)
├─ CLAUDE.md  GEMINI.md           the FS-SC rule block for the clients (rewritten at every connect)
└─ README.md
```

In a *flat* project the product code stays in the root; documents go to `docs/` (or `FS-docs/` in older layouts). Agents write only inside the project and can never write into `.git` or `.fs-workspace`. Scratch files an agent leaves in the root (`submit_*.js`, `step_*.json`) are moved to `.fs-workspace/tmp/` and kept out of git.

Project settings live in `.fs-workspace/settings.json`; nothing about a target project is stored in the FS-SC repository itself (the project registry is runtime data under `history/`, not committed).

---

## 17. Safety and control

- **Local only.** The server binds to `127.0.0.1`. Do not expose it to a network without your own access control.
- **No secrets in git.** Deliveries containing keys or passwords are rejected before writing, and a second scan runs before every commit.
- **Commands run on your machine**, in the project folder. Verification and run commands proposed by an agent pass a deny-list and are visible in the settings; review them before enabling *Server verification* on a project you do not trust, or enable command isolation (§12.7).
- **New libraries need your approval** on the dashboard (a Decisions item). Approval given in the chat is not recorded.
- **You can always stop.** Pause, cancel, revise, skip, or switch to *Every step* approval at any moment.
- **Deleting is reversible** for issues; disconnecting a project never deletes files.

---

## 18. Troubleshooting and FAQ

| Symptom | Cause and fix |
|---|---|
| A **!** badge on the top bar | The server code changed after it started. Restart: `scripts\fssc.ps1 stop`, then `start -Background`. |
| The run shows *abandoned* | The client disconnected or the server restarted. Type the same "run the pipeline" prompt or press *Resume*. |
| The client cannot see the tools | Restart the client; check `.mcp.json` / `.agents/mcp_config.json` point at this checkout and port 8099. |
| *Run queued* but nothing happens | A queued run only becomes active when the client calls `get_next_step`. Open the *Claude Bridge* and copy the prompt. |
| *Project paused — sprint budget is used up* | A budget limit was reached. Use *Raise budget by 10 and continue* or the Budget page (§12.11). |
| The sprint is halted by a question | Open *Questions* (§9.2) and answer, or wait for the timeout. |
| A task keeps failing verification | Open the step inspector (§6.11) for the exact command and output; fix the verification command in *Model / engine* if the command itself is wrong. |
| E2E reports `APP_NOT_CONFIGURED` | Set `verification.run` and `health_url` (and `client_run` / `client_url` for a web client) in *Model / engine*. |
| Port 8099 is busy | `scripts\fssc.ps1 set-port -Port <n>`, then reconnect the clients. |
| Texts are in the wrong language | The project language (agents) and the dashboard language are separate settings (§4.1, §4.5). |

**Can I use more than one AI client on the same project?** Yes — the run lives in the server, not in the client. Close Claude, open Antigravity, type the same prompt.

**Does it cost anything besides my subscription?** No. The Template engine is free; the MCP client mode uses your subscription.

**Can I change the plan during a run?** Yes: edit or add issues on the board, add a manager note, set a goal, or use *Do first*.

**Where are my project's files if I remove it from the switcher?** Exactly where they were; disconnecting only removes the registry entry.

---

## 19. Reproducing the screenshots

All images in this manual are generated, not drawn by hand:

```bash
# 1. Start an isolated server with a throw-away registry (never use your real one)
set AGY_REGISTRY_PATH=%TEMP%\fssc-demo\registry.json
set AGY_DEFAULT_PROJECT=%TEMP%\fssc-demo\default
set FSSC_DRY_RUN=1
set OBSERVER_PORT=8123
python -m server.main --mode web

# 2. In the dashboard: add a project (language: English), choose the Template engine,
#    enable sprint mode, upload a short specification and run the pipeline to completion.

# 3. Capture
python scripts/capture_manual.py --url http://127.0.0.1:8123
```

`--only "<step-name-fragment>,…"` re-captures a subset. Output goes to `docs/images/manual/`.

---

## 20. Glossary

| Term | Definition |
|---|---|
| **AC** | Acceptance criterion; identified as `AC-n`, referenced by tests as evidence. |
| **ADR** | Architecture decision record under `docs/adr/`. |
| **Backlog** | The ordered list of tasks produced by the architect and by later improvements. |
| **Carry-over** | A task moved into the next sprint because it was not finished. |
| **DoD** | Definition of done (see §15). |
| **Envelope** | The single JSON object an agent returns for a step: files, summary, hand-off notes, questions. |
| **Fix round** | An extra step that repairs a failed verification for the same task. |
| **MCP** | Model Context Protocol, the way AI clients call the FS-SC server's tools. |
| **Pull model** | The client asks the server for work; the server never pushes. |
| **Run** | One execution of the pipeline; a list of steps with a status. |
| **SCM agent** | The agent that commits verified deliveries to git. |
| **Step** | One unit of work by one agent. |
| **UAT** | User acceptance test by the Product Owner, decided per acceptance criterion. |
| **WIP** | Work in progress. |
