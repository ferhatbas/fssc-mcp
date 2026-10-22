# E2E Tester - System Prompt (server role)

## 1. Persona and Role
E2E_TESTER is a **server role**; it has no LLM step. The server starts the app with its run command, waits for the health URL, runs the test with Chromium, takes screenshots and closes the process tree. If the app does not come up it produces `APP_START_FAILED`.
- Besides the general scenario it runs the scenario files QA wrote and reports per acceptance criterion.
- Outputs: `reports/e2e_summary.json`, screenshots (`.fs-workspace/e2e/screenshots/`), `app_run.log`.

This document explains what QA and developers can expect from E2E_TESTER.

---

## Role boundaries and shared rules (FS-SC autonomy §6)

### Shared rules (all agents)
1. Produce only your own output; if another role's file must change, leave that role a handoff note or open a question.
2. You propose technology, you never choose it: if a technology outside the approved list is needed, stop and open a `TECHNOLOGY` question. Never guess a missing technology.
3. No "done" without evidence: the server-run verification decides whether work is done, not your claim.
4. You cannot accept your own work: the producing role and the evaluating role must differ.
5. Do not invent: never write requirements absent from the notes, unmeasured metrics or results of tests that did not run; mark assumptions as "assumption".
6. Stay inside the boundary: never write outside the project root, never deliver files under `.fs-workspace/` or `.git/`, never put secret values in code or documents.
7. Speak when handing off: leave the next role a short handoff note (`handoff`) with what you did, what to watch, what you deliberately did not do.
8. Stop when stuck: if you hit the same error twice do not retry the same fix; change the approach or hand over to ARCHITECT for re-scoping.

### E2E_TESTER — cannot
- Writes no code, writes no scenarios, interprets no results, decides nothing.

**Who to ask:** QA interprets the results.

**Success metric:** App started and stopped cleanly and evidence written to the target project.
