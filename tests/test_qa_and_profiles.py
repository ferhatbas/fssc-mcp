"""
Test profilleri CRUD ve yalnızca-test pipeline'ı (Playwright stub'lanır; CI'da Chromium yok).
"""

import pytest

import server.runner as runner_module


async def test_profiles_crud(hub):
    profiles = hub.get_test_profiles()
    assert len(profiles) >= 5

    saved = await hub.add_or_update_test_profile({
        "id": "test-custom-tester",
        "name": "Acme Custom Test User",
        "target_url": "http://127.0.0.1:8099/test-login",
        "username": "custom@acme.test",
        "password": "CustomSecretPass#2026",
        "role": "TESTER",
        "description": "Birim testler için özel kullanıcı profili",
    })
    assert saved["id"] == "test-custom-tester"
    assert any(p["id"] == "test-custom-tester" for p in hub.get_test_profiles())

    updated = await hub.add_or_update_test_profile({**saved, "name": "Renamed"})
    assert updated["name"] == "Renamed"
    assert sum(1 for p in hub.get_test_profiles() if p["id"] == "test-custom-tester") == 1

    assert await hub.delete_test_profile("test-custom-tester") is True
    assert await hub.delete_test_profile("test-custom-tester") is False


def _write_passing_pytest_project(project_dir: str) -> None:
    """Gerçek bir pytest projesi: boş requirements.txt + geçen bir test (doğrulama paketi bunu GERÇEKTEN koşar)."""
    import os
    os.makedirs(os.path.join(project_dir, "tests"), exist_ok=True)
    with open(os.path.join(project_dir, "requirements.txt"), "w", encoding="utf-8") as f:
        f.write("")
    with open(os.path.join(project_dir, "tests", "test_ok.py"), "w", encoding="utf-8") as f:
        f.write("def test_ok():\n    assert 1 + 1 == 2\n")


@pytest.mark.parametrize("pw_status,with_tests,expected_jira7,expected_jira6,expected_task_state,expected_verification", [
    # QA doğrulama paketi gerçekten geçti + E2E geçti → süit RELEASED
    ("PASSED", True, "DONE", "DONE", "RELEASED", "PASSED"),
    # Doğrulama komutu yok → QA SKIPPED (hiçbir şey denetlenmedi): E2E geçse de süit RELEASED olmaz, JIRA-6 DONE sayılmaz (G0: sahte yeşil yok)
    ("PASSED", False, "DONE", "IN_PROGRESS", "QA_TESTING", "SKIPPED"),
    # E2E kaldı → JIRA-7 kapanmaz
    ("FAILED", True, "IN_PROGRESS", "DONE", "QA_TESTING", "PASSED"),
])
async def test_tests_only_pipeline_runs_real_verification_and_propagates_status(
    hub, tmp_project, monkeypatch, pw_status, with_tests, expected_jira7, expected_jira6, expected_task_state, expected_verification
):
    """B3 + G0: QA kısmı projenin doğrulama paketini gerçekten koşar; Playwright başarısızsa JIRA-7 DONE olmamalı ve olay FAILED yayınlanmalı."""
    if with_tests:
        _write_passing_pytest_project(tmp_project)

    async def fake_playwright(target_url, test_scenario, credentials=None, **kwargs):
        return {
            "status": pw_status,
            "scenario": test_scenario,
            "target_url": target_url,
            "screenshots": ["/api/projects/p/screenshots/fake.png"],
            "logs": [],
            "verdict": "VERIFIED_FOR_PRODUCTION" if pw_status == "PASSED" else "ENGINE_UNAVAILABLE",
            "engine_error": None if pw_status == "PASSED" else "chromium missing",
            "notes_for_team_lead": "",
        }

    monkeypatch.setattr(runner_module, "run_playwright_e2e_tests", fake_playwright)

    report = await runner_module.execute_tests_only_pipeline(
        project_dir=tmp_project,
        target_url="http://127.0.0.1:8099",
        credentials={"username": "user@enterprise.local", "password": "x", "role": "USER"},
        hub=hub,
    )

    assert report["status"] == pw_status
    assert report["verification"]["status"] == expected_verification
    assert hub.jira_issues["JIRA-7"]["status"] == expected_jira7
    assert hub.jira_issues["JIRA-6"]["status"] == expected_jira6
    assert hub.tasks["TEST-SUITE-RUN"]["state"] == expected_task_state

    # QA raporu gerçek sonuçtan yazılır; sabit "6/6 BAŞARILI" metni yoktur
    import os
    from server.paths import hub_docs_path
    report_path = os.path.join(tmp_project, *hub_docs_path(hub, "QA_REPORT.md", tmp_project).split("/"))
    text = open(report_path, encoding="utf-8").read()
    assert "6/6" not in text and expected_verification in text
    if with_tests:
        assert "pytest" in text   # koşan komut raporda

    qa_events = [e for e in hub.events if e["from_agent"] == "QA" and e["action"] != "START_STANDALONE_QA_RUN"]
    assert qa_events and qa_events[-1]["status"] == ("SUCCESS" if expected_verification == "PASSED" else "IN_PROGRESS")
    e2e_events = [e for e in hub.events if e["from_agent"] == "E2E_TESTER"]
    assert e2e_events, "E2E olayı kaydedilmeli"
    assert e2e_events[-1]["status"] == ("SUCCESS" if pw_status == "PASSED" else "FAILED")


async def test_playwright_runner_reports_failure_when_engine_unavailable(monkeypatch, tmp_path):
    """Gerçek Playwright motoru: import başarısızsa SKIPPED, çalışma hatası FAILED olmalı (asla PASSED değil)."""
    import builtins
    import server.playwright_tester as pw


    real_import = builtins.__import__

    def failing_import(name, *args, **kwargs):
        if name.startswith("playwright"):
            raise ImportError("playwright not installed")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", failing_import)

    result = await pw.run_playwright_e2e_tests(target_url="http://127.0.0.1:1", test_scenario="x", project_dir=str(tmp_path), project_id="p")
    assert result["status"] == "SKIPPED"
    assert result["verdict"] == "ENGINE_UNAVAILABLE"
    assert result["simulated"] is True
    assert result["passed_steps"] == 0
