"""
Yardımcı pipeline koşucuları.

- `execute_jira_batch`: geriye dönük uyumlu sarmalayıcı; seçilen Jira maddelerini süreç içi ŞABLON motoruyla koşar
  (asıl yürütme `server/engine/template.py` + `server/pipeline.py` + `server/steps/`).
- `execute_tests_only_pipeline`: geliştirme ajanlarını çalıştırmadan yalnızca QA (madde 6) ve Playwright E2E (madde 7).
  G0: QA kısmı projenin doğrulama paketini (kurulum/lint/build/test) GERÇEKTEN koşar ve raporu sonuçtan yazar;
  hiçbir sonuç uydurulmaz. Komut yoksa doğrulama SKIPPED olarak raporlanır ve madde DONE sayılmaz.
"""

import asyncio
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .paths import hub_docs_path
from .i18n import translate as tx, N_
from .telemetry import TelemetryHub
from .playwright_tester import run_playwright_e2e_tests


async def execute_jira_batch(
    project_dir: str,
    selected_issue_keys_or_orders: List[Any],
    hub: TelemetryHub,
    custom_prompt: Optional[str] = None,
    step_by_step: bool = True
) -> Dict[str, Any]:
    """Seçilen Jira maddelerini şablon motoruyla başlatır ve koşu bitene kadar bekler (uyumluluk sarmalayıcısı)."""
    from .engine.api import LocalRunsApi

    api = getattr(hub, "_runs_api", None)
    if api is None or api.hub is not hub:
        api = LocalRunsApi(hub)
        setattr(hub, "_runs_api", api)
    result = await api.start_run(
        project_id=hub.active_project_id,
        steps=selected_issue_keys_or_orders,
        engine="template",
        custom_prompt=custom_prompt or "",
        step_by_step=step_by_step,
        project_dir=project_dir,
    )
    run_id = result.get("run", {}).get("run_id")
    task = api.template._tasks.get(run_id)
    if task is not None:
        try:
            await task
        except Exception:
            pass
    run = hub.runs.get(run_id)
    return run.to_dict() if run else result


def _qa_report_md(target_url: str, test_user: str, role: str, verification: Dict[str, Any]) -> str:
    """QA raporu yalnızca sunucunun gerçekten koştuğu komutların sonucundan yazılır."""
    from .verify import failure_excerpt

    results = verification.get("results") or []
    lines = [
        tx("# QA Standalone Test Raporu"),
        tx("- **Tarih**: {date}", date=datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')),
        tx("- **Hedef URL**: {url}", url=target_url),
        tx("- **Test Profili**: {user} (Rol: {role})", user=test_user, role=role),
        tx("- **Doğrulama paketi**: {status} — {summary}", status=verification.get('status'), summary=verification.get('summary') or '').rstrip(" —"),
        "",
        tx("| Adım | Komut | Durum | Çıkış kodu | Süre |"),
        "|---|---|---|---|---|",
    ]
    for r in results:
        dur = int((r.get("duration_ms") or 0) / 1000)
        lines.append(tx("| {name} | `{cmd}` | {status} | {code} | {dur} sn |", name=r.get('name'), cmd=r.get('cmd'), status=r.get('status'), code=r.get('exit_code'), dur=dur))
    if not results:
        lines.append(tx("| — | (doğrulama komutu tanımlı değil; model penceresi 0c'den girin) | SKIPPED | — | — |"))
    failed = verification.get("failed_step")
    if failed:
        lines += ["", tx("## Başarısız adım: {step}", step=failed), "```", failure_excerpt(verification, limit=3000), "```"]
    lines += ["", tx("- **E2E Durumu**: Playwright Chromium testine devredildi (sonuç ayrı raporda, uydurulmaz)")]
    return "\n".join(lines) + "\n"


async def execute_tests_only_pipeline(
    project_dir: str,
    target_url: str = "http://127.0.0.1:8099",
    credentials: Optional[Dict[str, Any]] = None,
    scenario: str = "Bağımsız QA ve Canlı Tarayıcı E2E Test Koşusu",
    hub: Optional[TelemetryHub] = None
) -> Dict[str, Any]:
    """
    Geliştirme ajanlarını (PM, Architect, Backend, Frontend, DevOps) çalıştırmadan
    SADECE test kısmını (Lead QA doğrulama paketi ve Playwright E2E Tester) icra eder.
    """
    from .telemetry import hub as default_hub
    from . import guard as G
    from . import layout as LAY
    from .verify import effective_commands, public_summary, run_verification

    active_hub = hub or default_hub

    target_path = os.path.abspath(project_dir)
    os.makedirs(target_path, exist_ok=True)
    docs_rel = hub_docs_path(active_hub, "", target_path)
    docs_dir = os.path.join(target_path, *docs_rel.split("/"))
    os.makedirs(docs_dir, exist_ok=True)

    trace_id = f"test-only-{int(datetime.now(timezone.utc).timestamp())}"
    cred = credentials or {}
    test_user = cred.get("username", tx("Standart Kullanıcı"))
    if scenario == "Bağımsız QA ve Canlı Tarayıcı E2E Test Koşusu":
        scenario = tx("Bağımsız QA ve Canlı Tarayıcı E2E Test Koşusu")       # varsayılan Türkçe imza: proje diline çevrilir
    role = cred.get("role", "USER")

    async def _issue(issue_id: str, updates: Dict[str, Any]) -> None:
        # Sprint kipinde JIRA-6/7 faz maddeleri olmayabilir; olmayan maddeyi uydurma
        if issue_id in active_hub.jira_issues:
            await active_hub.update_jira_issue(issue_id, updates)

    # 1. Kanban ve Jira tahtasını 'QA_TESTING' durumuna al
    await _issue("JIRA-6", {"status": "IN_PROGRESS"})
    await _issue("JIRA-7", {"status": "IN_PROGRESS"})
    await active_hub.update_task(
        task_id="TEST-SUITE-RUN",
        new_state="QA_TESTING",
        title=tx("Test Süiti Koşusu: {user} ({role})", user=test_user, role=role),
        assignee="QA",
        priority="P0",
        details=tx("Hedef: {url} | Senaryo: {scenario}", url=target_url, scenario=scenario)
    )

    # -------------------------------------------------------------------------
    # ADIM 1: Lead QA — projenin doğrulama paketi gerçekten koşar (Madde 6)
    # -------------------------------------------------------------------------
    settings = active_hub.get_settings()
    isolation = settings.get("python_isolation") if settings.get("python_isolation") in ("venv", "host") else "venv"
    commands = effective_commands(target_path, isolation, settings.get("verification"), LAY.app_roots(LAY.layout_of(settings)))
    await active_hub.record_event(
        trace_id=trace_id,
        from_agent="QA",
        to_agent="E2E_TESTER",
        action="START_STANDALONE_QA_RUN",
        status="IN_PROGRESS",
        payload={"mode": "TESTS_ONLY", "target_url": target_url, "test_user": test_user, "role": role, "scenario": scenario,
                 "commands": commands},
        current_file="tests/",
        tokens_used=0
    )
    sb = G.sandbox(active_hub)
    verification = await run_verification(
        target_path, commands, files_written=[], do_install=True, isolation=isolation, tag="qa-suite",
        sandbox=sb if sb.get("mode") == "container" else None,
        command_filter=(lambda c: G.command_allowed(active_hub, c)) if sb.get("command_policy") == "allowlist" else None,
    )
    v_status = verification.get("status")
    qa_passed = v_status == "PASSED"

    qa_report_md = os.path.join(docs_dir, "QA_REPORT.md")
    with open(qa_report_md, "w", encoding="utf-8") as f:
        f.write(_qa_report_md(target_url, test_user, role, verification))

    await active_hub.record_event(
        trace_id=trace_id,
        from_agent="QA",
        to_agent="E2E_TESTER",
        action="APPROVE_BUILD" if qa_passed else ("QA_VERIFICATION_SKIPPED" if v_status == "SKIPPED" else "QA_VERIFICATION_FAILED"),
        status="SUCCESS" if qa_passed else ("IN_PROGRESS" if v_status == "SKIPPED" else "FAILED"),
        payload={
            "verdict": "QA_UNIT_PASSED" if qa_passed else f"QA_{v_status}",
            "verification": public_summary(verification),
            "report": f"{docs_rel}/QA_REPORT.md",
            "message": (
                tx("Lead QA doğrulama paketi geçti ({summary}). Gerçek tarayıcı testi başlatılıyor ({user}).", summary=verification.get('summary'), user=test_user)
                if qa_passed else
                tx("Lead QA doğrulama paketi {status}: {summary}. E2E yine koşar; madde DONE sayılmaz.", status=v_status, summary=verification.get('summary'))
            ),
        },
        current_file=f"{docs_rel}/QA_REPORT.md",
        tokens_used=0
    )
    await _issue("JIRA-6", {"status": "DONE" if qa_passed else "IN_PROGRESS",
                            "audit_action": "QA_SUITE_" + str(v_status), "audit_notes": str(verification.get("summary") or "")[:300]})

    # -------------------------------------------------------------------------
    # ADIM 2: Playwright E2E gerçek tarayıcı testi (Madde 7)
    # -------------------------------------------------------------------------
    playwright_result = await run_playwright_e2e_tests(
        target_url=target_url,
        test_scenario=f"{scenario} - [{test_user} / {role}]",
        credentials=cred,
        project_dir=target_path, project_id=active_hub.active_project_id,
    )
    saved_report = await active_hub.add_playwright_report(playwright_result)
    e2e_passed = playwright_result.get("status") == "PASSED"

    await active_hub.record_event(
        trace_id=trace_id,
        from_agent="E2E_TESTER",
        to_agent="ARCHITECT",
        action="E2E_SCREENSHOT_CONFIRMED" if e2e_passed else "E2E_TEST_FAILED",
        status="SUCCESS" if e2e_passed else "FAILED",
        payload={
            "report_id": saved_report["id"],
            "target_url": target_url,
            "test_user": test_user,
            "role": role,
            "screenshots_count": len(playwright_result.get("screenshots", [])),
            "screenshots": playwright_result.get("screenshots", []),
            "test_status": playwright_result.get("status", "FAILED"),
            "engine_error": playwright_result.get("engine_error"),
            "verdict": playwright_result.get("verdict", "ENGINE_UNAVAILABLE"),
            "notes": playwright_result.get("notes_for_team_lead", "")
        },
        current_file=".fs-workspace/e2e/screenshots",
        tokens_used=0
    )

    # Jira ve Kanban güncelle: yalnızca iki kanıt da geçerse "RELEASED"
    await _issue("JIRA-7", {"status": "DONE" if e2e_passed else "IN_PROGRESS"})
    all_passed = qa_passed and e2e_passed
    await active_hub.update_task(
        task_id="TEST-SUITE-RUN",
        new_state="RELEASED" if all_passed else "QA_TESTING",
        title=tx("Test Süiti Tamamlandı: {user}", user=test_user) if all_passed else tx("Test Süiti Başarısız: {user}", user=test_user),
        assignee="E2E_TESTER",
        priority="P0",
        details=(
            tx("QA doğrulama paketi ve E2E tarayıcı testi geçti. Rapor: {id}", id=saved_report['id'])
            if all_passed else
            tx("QA doğrulama: {qa} · E2E: {e2e}. Rapor: {id}", qa=v_status, e2e=playwright_result.get('status'), id=saved_report['id'])
        )
    )

    await active_hub.broadcast({
        "type": "TEST_SUITE_COMPLETED",
        "report_id": saved_report["id"],
        "target_url": target_url,
        "test_user": test_user,
        "status": playwright_result.get("status", "FAILED"),
        "verification": public_summary(verification),
    })

    return {**saved_report, "verification": public_summary(verification)}
