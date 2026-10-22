"""G7 — test ekibi (plan §4.3): test case belgeleri, TEST_RUN, otomatik BUG, kararsız test, izlenebilirlik matrisi, regresyon kapısı, E2E senaryo editörü.

Kabul (plan §5): QA sprint başında `<docs>/tests/TC-*.md` üretir ve Jira'da görünür; test run sonuçları case bazında; başarısız case BUG açar; PO kararı matrise dayanır;
kapsama yüzdesi panoda.
"""

import json
import os
import time
from types import SimpleNamespace

import pytest

from server import quality as Q
from server import sprint as SP
from server import testing as TST

STORY_A, STORY_B = "JIRA-101", "JIRA-102"


async def _seed_stories(hub):
    """İki hikâye ve üç kabul kriteri (AC-1, AC-2 → A; AC-3 → B)."""
    acs = SP.ensure_state(hub)["acs"]
    acs["AC-1"] = {"text": "Kullanıcı giriş yapabilir", "story": STORY_A}
    acs["AC-2"] = {"text": "Hatalı parola reddedilir", "story": STORY_A}
    acs["AC-3"] = {"text": "Yönetici kayıtları listeler", "story": STORY_B}
    await hub.update_jira_issue(STORY_A, {"order": 101, "title": "Giriş", "kind": "story", "issue_type": "STORY", "status": "BACKLOG", "ac_refs": ["AC-1", "AC-2"],
                                          "acceptance_criteria": ["Kullanıcı giriş yapabilir", "Hatalı parola reddedilir"]})
    await hub.update_jira_issue(STORY_B, {"order": 102, "title": "Kayıt listesi", "kind": "story", "issue_type": "STORY", "status": "BACKLOG", "ac_refs": ["AC-3"],
                                          "acceptance_criteria": ["Yönetici kayıtları listeler"]})


def _case(title="Giriş başarılı", **kw):
    return {"title": title, "type": "integration", "priority": "P1", "ac_refs": ["AC-1"], "story_ref": STORY_A, "steps": ["Giriş sayfasını aç", "Geçerli bilgiyi gir"],
            "expected": "Panoya yönlenir", "automation": "MANUAL", **kw}


# ---------------------------------------------------------------------------
# Model ve doğrulama
# ---------------------------------------------------------------------------
async def test_case_input_is_normalized_and_invalid_input_rejected(hub):
    await _seed_stories(hub)
    c = TST.normalize_case(hub, {"title": " Giriş ", "steps": "1. aç\n2) gir", "expected": ["a", "b"], "ac_refs": ["ac_1", "AC-2", "geçersiz"], "story_ref": STORY_B,
                                "labels": "Regression, SMOKE", "automation": "automated: test_login"})
    assert c["title"] == "Giriş" and c["steps"] == ["aç", "gir"] and c["expected"] == "a\nb" and c["ac_refs"] == ["AC-1", "AC-2"]
    assert c["story_ref"] == STORY_B and c["labels"] == ["regression", "smoke"] and c["automation"] == "AUTOMATED:test_login"
    assert c["type"] == "integration" and c["priority"] == "P1" and c["status"] == "DRAFT"                        # varsayılanlar
    assert TST.normalize_case(hub, {"title": "x", "steps": ["a"], "expected": "b", "story_ref": STORY_A})["ac_refs"] == ["AC-1", "AC-2"]       # kriter verilmedi: hikâyenin kriterleri
    assert TST.normalize_case(hub, {"title": "x", "steps": ["a"], "expected": "b", "story_ref": "YOK"})["story_ref"] == ""
    for bad in ({}, {"title": "x"}, {"title": "x", "steps": ["a"]}, {"title": "x", "steps": [], "expected": "b"}, {"title": "x", "steps": ["a"], "expected": "b", "type": "manual"},
                {"title": "x", "steps": ["a"], "expected": "b", "priority": "P9"}, {"title": "x", "steps": ["a"], "expected": "b", "automation": "belki"},
                {"title": "x", "steps": ["a"], "expected": "b", "status": "OLUR"}, "metin"):
        with pytest.raises(TST.CaseError):
            TST.normalize_case(hub, bad)
    assert TST.normalize_case(hub, {"priority": "p0"}, partial=True) == {"priority": "P0"}                              # kısmi güncelleme


async def test_create_case_writes_the_markdown_document_and_a_linked_jira_test_case(hub, tmp_project):
    await _seed_stories(hub)
    case = await TST.create_case(hub, _case(automation="AUTOMATED:test_login", labels=["smoke"]), sprint=1)
    assert case["id"] == "TC-1" and case["status"] == "READY" and case["file"] == f"{TST._docs(hub)}/tests/TC-1.md"
    text = open(os.path.join(tmp_project, *case["file"].split("/")), encoding="utf-8").read()
    assert "# TC-1 — Giriş başarılı" in text and "1. Giriş sayfasını aç" in text and "Panoya yönlenir" in text and "AUTOMATED:test_login" in text and "AC-1" in text
    issue = hub.jira_issues[case["issue_id"]]
    assert issue["issue_type"] == "TEST_CASE" and issue["kind"] == "testcase" and issue["assignee"] == "QA" and issue["ac_refs"] == ["AC-1"] and issue["parent_id"] == STORY_A
    assert any(l["type"] == "tests" and l["target"] == STORY_A for l in issue["links"])                           # test case --tests--> hikâye
    assert any(l["type"] == "tested_by" and l["target"] == case["issue_id"] for l in hub.jira_issues[STORY_A]["links"])
    assert SP.candidates(hub) == []                                                                                # test case sprint görevi değildir
    second = await TST.create_case(hub, _case("İkinci"), sprint=1)
    assert second["id"] == "TC-2" and TST.store(hub)["seq"]["case"] == 2


# ---------------------------------------------------------------------------
# QA test tasarımı
# ---------------------------------------------------------------------------
async def test_design_task_is_added_only_when_enabled_and_stories_lack_cases(hub, monkeypatch):
    await _seed_stories(hub)
    base = [{"task_key": "T-1", "title": "x", "role": "BACKEND_DEV", "work_type": "FEATURE"}]
    assert TST.with_design_task(hub, base) == base                                                                # sıkı DoD kapalı: davranış değişmez
    monkeypatch.setattr(TST, "design_enabled", lambda h: True)
    out = TST.with_design_task(hub, base)
    assert len(out) == 2 and out[1]["work_type"] == "TEST_DESIGN" and out[1]["role"] == "QA" and out[1]["depends_on"] == []
    assert TST.with_design_task(hub, out) == out                                                                   # zaten var
    await hub.update_jira_issue("JIRA-300", {"order": 300, "kind": "task", "work_type": "TEST_DESIGN", "status": "BACKLOG", "assignee": "QA", "title": "bekleyen"})
    assert TST.with_design_task(hub, base) == base                                                                 # bekleyen tasarım görevi var
    del hub.jira_issues["JIRA-300"]
    hub.agents["QA"]["active"] = False
    assert TST.with_design_task(hub, base) == base                                                                 # QA pasif
    hub.agents["QA"]["active"] = True
    await TST.create_case(hub, _case(), sprint=1)
    await TST.create_case(hub, _case("B", ac_refs=["AC-3"], story_ref=STORY_B), sprint=1)
    assert TST.with_design_task(hub, base) == base                                                                 # tüm hikâyelerin case'i var
    assert TST.with_design_task(hub, []) == []


async def test_design_delivery_creates_cases_skips_duplicates_and_rejects_empty_or_invalid(hub, tmp_project):
    await _seed_stories(hub)
    run, record = SimpleNamespace(run_id="run-t"), SimpleNamespace(sprint=1)
    payload = {"testcases": [_case(), _case("Hatalı parola", ac_refs=["AC-2"], type="security", steps=["Yanlış parola gir"], expected="Reddedilir"),
                             {"title": "adımsız", "expected": "x"}, _case()]}
    res = await TST.ingest_design(hub, run, record, payload)
    assert res["created"] == ["TC-1", "TC-2"] and res["skipped"] == 1 and any("adımlar" in w for w in res["warnings"])
    assert all(TST.store(hub)["cases"][i]["status"] == "READY" for i in res["created"])
    assert os.path.isfile(os.path.join(tmp_project, TST._docs(hub), "tests", "plan-sprint-1.md"))                  # plan da yazıldı
    for bad in ({}, {"testcases": []}, {"testcases": [{"title": "x"}]}, {"testcases": "metin"}):
        with pytest.raises(TST.CaseError):
            TST.validate_design(hub, bad)
    ctx = TST.design_context(hub)
    assert "Kayıt listesi" in ctx and "AC-3" in ctx and "TC-1" in ctx and "payload.testcases[]" in ctx           # case'siz hikâye + mevcut case'ler + biçim


async def test_template_engine_run_designs_cases_runs_them_and_the_matrix_follows(client, hub, tmp_project, monkeypatch):
    """Kuru koşu: sıkı DoD'da QA sprint başında TC-n belgelerini üretir, Jira'da görünür; QA adımı TEST_RUN kaydeder; junit gelince matris kapsama yüzdesi verir."""
    monkeypatch.setattr(TST, "design_enabled", lambda h: True)
    client.post("/api/settings/sprint", json={"enabled": True, "commit_approval": "auto", "auto_chain": True, "max_tasks": 50})
    client.post("/api/settings/engine", json={"execution_engine": "template", "approval_mode": "auto", "pacing": "instant", "auto_verify": False, "auto_commit": False})
    hub.step_by_step_mode = False
    notes = "Kullanıcı sisteme giriş yapabilmelidir. Yönetici kayıtları listeleyebilmelidir. Her işlem için denetim kaydı tutulmalıdır."
    rid = client.post("/api/specs/upload", data={"title": "Notlar", "client_name": "Acme", "meeting_notes": notes}).json()["intake"]["run_id"]
    end = time.time() + 150
    run = None
    while time.time() < end:
        run = client.get(f"/api/runs/{rid}").json()["run"]
        if run["is_terminal"]:
            break
        time.sleep(0.2)
    assert run["status"] == "COMPLETED", run["status"]
    design = [i for i in hub.jira_issues.values() if i.get("work_type") == "TEST_DESIGN"]
    assert len(design) == 1 and design[0]["assignee"] == "QA" and design[0]["status"] == "DONE"                   # sunucu QA tasarım görevini ekledi, QA teslim etti
    cases = TST.store(hub)["cases"]
    assert len(cases) == 3 and all(c["status"] == "READY" for c in cases.values())                                # her kabul kriterine bir case
    for c in cases.values():
        assert os.path.isfile(os.path.join(tmp_project, *c["file"].split("/"))) and hub.jira_issues[c["issue_id"]]["issue_type"] == "TEST_CASE"
    assert os.path.isfile(os.path.join(tmp_project, TST._docs(hub), "tests", "plan-sprint-1.md"))
    first = cases["TC-1"]
    assert first["automation"] == "AUTOMATED:test_token_creation" and first["type"] == "integration"
    runs = TST.store(hub)["runs"]
    assert runs and runs["RUN-1"]["source"] == "QA" and runs["RUN-1"]["results"][0]["case"] == "TC-1"             # QA adımı TEST_RUN kaydetti
    assert runs["RUN-1"]["results"][0]["result"] == "BLOCKED"                                                      # auto_verify kapalı: junit yok → otomasyon bulunamadı
    assert hub.jira_issues[runs["RUN-1"]["issue_id"]]["issue_type"] == "TEST_RUN"
    mx = TST.matrix(hub, tmp_project)
    assert mx["total"] == 3 and mx["coverage_pct"] == 0 and len(mx["untested"]) == 3
    # junit gelince (QA testleri koştuğunda) case PASS olur, kapsama yüzdesi ve PO kanıtı oluşur
    junit = {"cases": [{"id": "tests/test_app.py::test_token_creation", "file": "tests/test_app.py", "name": "test_token_creation", "status": "passed", "message": ""}]}
    out = await TST.record_run(hub, sprint=1, source="QA", project_dir=tmp_project, junit=junit)
    assert out["results"] == [{"case": "TC-1", "result": "PASS", "evidence": {"tests": ["tests/test_app.py::test_token_creation"], "message": ""},
                               "title": first["title"], "quarantined": False}]
    assert hub.jira_issues[first["issue_id"]]["status"] == "DONE"
    mx = TST.matrix(hub, tmp_project)
    assert mx["covered"] == 1 and mx["coverage_pct"] == 33 and len(mx["no_case"]) == 0
    ac = first["ac_refs"][0]
    assert Q.evidence_for(hub, 1, tmp_project)[ac]["cases"] == ["TC-1"] and Q.evidence_for(hub, 1, tmp_project)[ac]["ok"] is True      # PO kanıtı matrise dayanır


# ---------------------------------------------------------------------------
# Test run: junit / senaryo / performans → case sonucu
# ---------------------------------------------------------------------------
async def _mixed_cases(hub):
    await _seed_stories(hub)
    ids = {}
    for key, raw in {
        "named": _case("Ada göre", automation="AUTOMATED:test_login_ok"),
        "mention": _case("Anmayla", ac_refs=["AC-2"], type="security"),
        "missing": _case("Otomasyonu yok", ac_refs=["AC-3"], automation="AUTOMATED:test_olmayan"),
        "manual": _case("Elle", ac_refs=["AC-3"]),
        "e2e": _case("Senaryo", type="e2e", automation="AUTOMATED:E2E-AC1-giris"),
        "perf": _case("Gecikme", type="performance", automation="AUTOMATED:health"),
        "explore": _case("Keşif", type="exploratory"),
    }.items():
        ids[key] = (await TST.create_case(hub, raw, sprint=1))["id"]
    return ids


async def test_run_maps_junit_names_mentions_and_missing_automation(hub, tmp_project):
    ids = await _mixed_cases(hub)
    os.makedirs(os.path.join(tmp_project, "tests"), exist_ok=True)
    mention_id = ids["mention"]
    open(os.path.join(tmp_project, "tests", "test_security.py"), "w", encoding="utf-8").write(f"# {mention_id}\ndef test_sql():\n    pass\n")
    junit = {"cases": [
        {"id": "tests/test_app.py::test_login_ok", "file": "tests/test_app.py", "name": "test_login_ok", "status": "passed", "message": ""},
        {"id": "tests/test_security.py::test_sql", "file": "tests/test_security.py", "name": "test_sql", "status": "failed", "message": "AssertionError: enjeksiyon geçti"},
        {"id": "tests/test_other.py::test_x", "file": "tests/test_other.py", "name": "test_x", "status": "passed", "message": ""}]}
    run = await TST.record_run(hub, sprint=1, source="QA", project_dir=tmp_project, junit=junit)
    got = {r["case"]: r["result"] for r in run["results"]}
    assert got == {ids["named"]: "PASS", ids["mention"]: "FAIL", ids["missing"]: "BLOCKED"}                       # manuel/e2e/perf/keşif bu run'da yok
    cases = TST.store(hub)["cases"]
    assert cases[ids["named"]]["last_result"]["result"] == "PASS" and cases[ids["manual"]]["last_result"] is None
    assert hub.jira_issues[cases[ids["named"]]["issue_id"]]["status"] == "DONE"
    assert hub.jira_issues[cases[ids["mention"]]["issue_id"]]["status"] == "IN_PROGRESS"                           # başarısız case ilerlemede
    assert run["summary"] == {"total": 3, "pass": 1, "fail": 1, "blocked": 1, "skip": 0} and run["sprint"] == 1
    assert hub.jira_issues[run["issue_id"]]["title"].startswith("RUN-1:") and "1 PASS / 1 FAIL / 1 BLOCKED" in hub.jira_issues[run["issue_id"]]["title"]
    assert "Son sonuç" in open(os.path.join(tmp_project, *cases[ids["named"]]["file"].split("/")), encoding="utf-8").read()      # belge sonucu yansıtır


async def test_e2e_and_performance_cases_run_on_the_e2e_source(hub, tmp_project):
    ids = await _mixed_cases(hub)
    scenarios = [{"id": "E2E-AC1-giris", "file": "e2e/scenarios/E2E-AC1-giris.json", "ac_refs": ["AC-1"], "status": "PASSED"}]
    perf = {"url": "http://x/health", "samples": 10, "errors": 0, "p50_ms": 12.0, "p95_ms": 40.0, "max_ms": 55.0, "threshold_ms": 1000}
    run = await TST.record_run(hub, sprint=1, source="E2E_TESTER", project_dir=tmp_project, scenarios=scenarios, perf=perf)
    assert {r["case"]: r["result"] for r in run["results"]} == {ids["e2e"]: "PASS", ids["perf"]: "PASS"}
    slow = await TST.record_run(hub, sprint=1, source="E2E_TESTER", project_dir=tmp_project, scenarios=[{**scenarios[0], "status": "FAILED"}],
                                perf={**perf, "p95_ms": 2400.0})
    assert {r["case"]: r["result"] for r in slow["results"]} == {ids["e2e"]: "FAIL", ids["perf"]: "FAIL"}
    assert "p95 2400.0 ms" in [r for r in slow["results"] if r["case"] == ids["perf"]][0]["evidence"]["message"]
    nolink = await TST.record_run(hub, sprint=1, source="E2E_TESTER", project_dir=tmp_project, scenarios=[], perf=None)
    assert {r["case"]: r["result"] for r in nolink["results"]} == {ids["e2e"]: "BLOCKED", ids["perf"]: "BLOCKED"}  # otomasyon var ama kanıt yok
    assert await TST.record_run(hub, sprint=1, source="MANUAL", project_dir=tmp_project) is None                  # bilinmeyen kaynakta case yok
    stats = TST.perf_smoke("http://127.0.0.1:1/health", samples=2, threshold_ms=500, timeout_s=0.3)              # kapalı port: hata sayılır, çökmez
    assert stats["samples"] == 2 and stats["errors"] == 2 and stats["threshold_ms"] == 500


async def test_failed_case_opens_one_bug_with_reproduction_steps_and_a_link(hub, tmp_project):
    await _seed_stories(hub)
    case = await TST.create_case(hub, _case(priority="P0", automation="AUTOMATED:test_login_ok"), sprint=1)
    fail = {"cases": [{"id": "t::test_login_ok", "file": "t.py", "name": "test_login_ok", "status": "failed", "message": "AssertionError: 401"}]}
    run = await TST.record_run(hub, sprint=1, source="QA", project_dir=tmp_project, junit=fail)
    bug_id = run["bugs"][0]
    bug = hub.jira_issues[bug_id]
    assert bug["issue_type"] == "BUG" and bug["kind"] == "task" and bug["status"] == "BACKLOG" and bug["priority"] == "P0" and bug["work_type"] == "BUG" and bug["origin"] == "TEST"
    assert "1. Giriş sayfasını aç" in bug["description"] and "Panoya yönlenir" in bug["description"] and "AssertionError: 401" in bug["description"]
    assert bug["ac_refs"] == ["AC-1"] and bug["task_key"].startswith("BUG-")
    assert any(l["type"] == "relates" and l["target"] == case["issue_id"] for l in bug["links"])
    assert SP.candidates(hub) and bug_id in [i["id"] for i in SP.candidates(hub)]                                   # sprint planı hatayı alır
    again = await TST.record_run(hub, sprint=1, source="QA", project_dir=tmp_project, junit=fail)
    assert again["bugs"] == [bug_id]                                                                                # case başına tek açık BUG
    assert TST.store(hub)["cases"][case["id"]]["open_bug"] == bug_id and TST.summary(hub)["open_bugs"] == 1
    hub.jira_issues[bug_id]["status"] = "DONE"
    third = await TST.record_run(hub, sprint=1, source="QA", project_dir=tmp_project, junit=fail)
    assert third["bugs"] and third["bugs"][0] != bug_id                                                             # düzeltildi ama yine kaldı: yeni BUG


async def test_flaky_case_is_quarantined_and_files_one_improvement(hub, tmp_project):
    await _seed_stories(hub)
    case = await TST.create_case(hub, _case(automation="AUTOMATED:test_login_ok"), sprint=1)
    cid = case["id"]

    def junit(status):
        return {"cases": [{"id": "t::test_login_ok", "file": "t.py", "name": "test_login_ok", "status": status, "message": "x"}]}

    for status in ("passed", "failed", "passed"):
        await TST.record_run(hub, sprint=1, source="QA", project_dir=tmp_project, junit=junit(status))
    live = TST.store(hub)["cases"][cid]
    assert live["quarantined"] is True and "flaky" in live["labels"] and live["flaky_since"]                        # PASS→FAIL→PASS: 2 geçiş
    flaky = hub.jira_issues[live["flaky_issue"]]
    assert flaky["title"].startswith("[Kararsız test] TC-1") and flaky["priority"] == "P2" and flaky["assignee"] == "QA"
    bugs_before = [i for i in hub.jira_issues.values() if i.get("issue_type") == "BUG"]
    await TST.record_run(hub, sprint=1, source="QA", project_dir=tmp_project, junit=junit("failed"))
    assert [i for i in hub.jira_issues.values() if i.get("issue_type") == "BUG"] == bugs_before                    # karantinadaki case BUG açmaz
    mx = TST.matrix(hub, tmp_project)
    assert mx["covered"] == 0 and [r for r in mx["rows"] if r["ac"] == "AC-1"][0]["cases"][0]["quarantined"] is True   # karantina kapsamaya sayılmaz
    assert TST.summary(hub)["flaky"] == 1 and TST.regression_gate(hub)["size"] == 0
    released = await TST.update_case(hub, cid, {"quarantined": False})
    assert released["quarantined"] is False and released["flaky_since"] is None                                      # elle serbest bırakma


# ---------------------------------------------------------------------------
# Matris, regresyon kapısı, elle sonuç
# ---------------------------------------------------------------------------
async def test_matrix_states_coverage_and_regression_gate(hub, tmp_project):
    await _seed_stories(hub)
    c1 = await TST.create_case(hub, _case(automation="AUTOMATED:test_login_ok", labels=["regression"]), sprint=1)             # AC-1
    c2 = await TST.create_case(hub, _case("B", ac_refs=["AC-2"], automation="AUTOMATED:test_bad_password", labels=["regression"]), sprint=1)
    mx = TST.matrix(hub, tmp_project)
    states = {r["ac"]: r["state"] for r in mx["rows"]}
    assert states == {"AC-1": "UNTESTED", "AC-2": "UNTESTED", "AC-3": "NO_CASE"} and mx["coverage_pct"] == 0 and mx["no_case"] == ["AC-3"]
    gate = TST.regression_gate(hub)
    assert gate["ok"] is False and sorted(gate["unexecuted"]) == [c1["id"], c2["id"]]                              # otomatik ama hiç koşmamış
    junit = {"cases": [{"id": "t::test_login_ok", "file": "t.py", "name": "test_login_ok", "status": "passed", "message": ""},
                       {"id": "t::test_bad_password", "file": "t.py", "name": "test_bad_password", "status": "failed", "message": "boom"}]}
    await TST.record_run(hub, sprint=1, source="QA", project_dir=tmp_project, junit=junit)
    mx = TST.matrix(hub, tmp_project)
    assert {r["ac"]: r["state"] for r in mx["rows"]} == {"AC-1": "COVERED", "AC-2": "FAILING", "AC-3": "NO_CASE"}
    assert mx["coverage_pct"] == 33 and mx["failing"] == ["AC-2"] and mx["target_pct"] == 80
    gate = TST.regression_gate(hub)
    assert gate["ok"] is False and gate["failing"] == [c2["id"]]
    summary = TST.summary(hub)
    assert summary["cases"] == 2 and summary["results"]["PASS"] == 1 and summary["results"]["FAIL"] == 1 and summary["coverage_pct"] == 33 and summary["last_run"]["id"] == "RUN-1"
    # düzeltme sonrası geçer; kapanışta geçen case'ler regresyon kümesine girer
    junit["cases"][1]["status"] = "passed"
    await TST.record_run(hub, sprint=1, source="QA", project_dir=tmp_project, junit=junit)
    assert TST.regression_gate(hub) == {"ok": True, "size": 2, "failing": [], "unexecuted": [], "manual_pending": []}
    c3 = await TST.create_case(hub, _case("C", ac_refs=["AC-3"], story_ref=STORY_B, automation="AUTOMATED:test_list"), sprint=1)
    junit["cases"].append({"id": "t::test_list", "file": "t.py", "name": "test_list", "status": "passed", "message": ""})
    await TST.record_run(hub, sprint=1, source="QA", project_dir=tmp_project, junit=junit)
    assert TST.promote_regression(hub) == [c3["id"]] and "regression" in TST.store(hub)["cases"][c3["id"]]["labels"] and TST.promote_regression(hub) == []
    assert TST.matrix(hub, tmp_project)["coverage_pct"] == 100


async def test_close_report_blocks_on_a_failing_regression_case_and_writes_the_test_plan(hub, tmp_project):
    await _seed_stories(hub)
    sp = SP.new_sprint(hub, 1, "Hedef")
    SP.ensure_state(hub)["sprints"].append(sp)
    case = await TST.create_case(hub, _case(automation="AUTOMATED:test_login_ok", labels=["regression"]), sprint=1)
    fail = {"cases": [{"id": "t::test_login_ok", "file": "t.py", "name": "test_login_ok", "status": "failed", "message": "x"}]}
    await TST.record_run(hub, sprint=1, source="QA", project_dir=tmp_project, junit=fail)
    run = SimpleNamespace(steps=[])

    async def create(tasks):
        return None

    rep = await Q.close_report(hub, run, sp, tmp_project, create)
    assert rep["tests"]["regression"]["failing"] == [case["id"]] and rep["ok"] is False
    assert any("Regresyon kümesi geçmedi: TC-1" in m for m in rep["missing"])
    plan = open(os.path.join(tmp_project, TST._docs(hub), "tests", "plan-sprint-1.md"), encoding="utf-8").read()
    assert "# Test planı — Sprint 1" in plan and "Kapsam (hikâye → case)" in plan and "Çıkış kriteri" in plan and "TC-1[FAIL]" in plan and "Regresyon kümesi geçti" in plan
    ok = {"cases": [{"id": "t::test_login_ok", "file": "t.py", "name": "test_login_ok", "status": "passed", "message": ""}]}
    await TST.record_run(hub, sprint=1, source="QA", project_dir=tmp_project, junit=ok)
    rep2 = await Q.close_report(hub, run, sp, tmp_project, create)
    assert not any("Regresyon" in m for m in rep2["missing"])


async def test_manual_result_files_a_bug_and_updates_the_matrix(hub, tmp_project):
    await _seed_stories(hub)
    case = await TST.create_case(hub, _case(), sprint=1)
    run = await TST.set_manual_result(hub, case["id"], "fail", "Buton görünmüyor", by="Ayşe")
    assert run["source"] == "MANUAL" and run["executed_by"] == "Ayşe" and run["bugs"] and TST.store(hub)["cases"][case["id"]]["last_result"]["result"] == "FAIL"
    assert "Buton görünmüyor" in hub.jira_issues[run["bugs"][0]]["description"]
    await TST.set_manual_result(hub, case["id"], "PASS", "düzeltildi")
    assert TST.matrix(hub, tmp_project)["rows"][0]["state"] == "COVERED"
    with pytest.raises(TST.CaseError):
        await TST.set_manual_result(hub, case["id"], "BELKI")
    with pytest.raises(KeyError):
        await TST.set_manual_result(hub, "TC-99", "PASS")
    await TST.update_case(hub, case["id"], {"status": "DEPRECATED"})
    with pytest.raises(TST.CaseError):
        await TST.set_manual_result(hub, case["id"], "PASS")                                                        # kullanımdan kalkmış case'e sonuç girilmez
    assert TST.matrix(hub, tmp_project)["rows"][0]["state"] == "NO_CASE"                                              # matris onu saymaz


# ---------------------------------------------------------------------------
# HTTP uçları
# ---------------------------------------------------------------------------
async def test_testing_endpoints_cases_runs_matrix_plan_config_and_errors(client, hub, tmp_project):
    await _seed_stories(hub)
    res = client.post("/api/testing/cases", json=_case(labels=["smoke"], status="READY"))
    assert res.status_code == 200, res.text
    case = res.json()["case"]
    assert case["id"] == "TC-1" and case["status"] == "READY" and case["owner"] == "manager"
    assert client.post("/api/testing/cases", json={"title": "x"}).status_code == 400
    assert client.post("/api/testing/cases", json=_case(type="manual")).status_code == 400
    listed = client.get("/api/testing/cases").json()
    assert [c["id"] for c in listed["cases"]] == ["TC-1"] and listed["summary"]["cases"] == 1
    assert client.get("/api/testing/cases?ac=AC-3").json()["cases"] == [] and len(client.get("/api/testing/cases?label=smoke").json()["cases"]) == 1
    assert client.get("/api/testing/cases/TC-1").json()["case"]["title"] == "Giriş başarılı" and client.get("/api/testing/cases/TC-9").status_code == 404
    upd = client.patch("/api/testing/cases/TC-1", json={"priority": "P0", "automation": "AUTOMATED:test_login"})
    assert upd.status_code == 200 and upd.json()["case"]["priority"] == "P0" and upd.json()["case"]["automation"] == "AUTOMATED:test_login"
    assert client.patch("/api/testing/cases/TC-1", json={"priority": "P7"}).status_code == 400 and client.patch("/api/testing/cases/TC-9", json={}).status_code == 404
    out = client.post("/api/testing/cases/TC-1/result", json={"result": "FAIL", "note": "kırık"})
    assert out.status_code == 200 and out.json()["run"]["bugs"]
    assert client.post("/api/testing/cases/TC-1/result", json={"result": "x"}).status_code == 400 and client.post("/api/testing/cases/TC-9/result", json={"result": "PASS"}).status_code == 404
    runs = client.get("/api/testing/runs").json()["runs"]
    assert [r["id"] for r in runs] == ["RUN-1"] and client.get("/api/testing/runs/RUN-1").json()["run"]["results"][0]["result"] == "FAIL"
    assert client.get("/api/testing/runs/RUN-9").status_code == 404
    mx = client.get("/api/testing/matrix").json()["matrix"]
    assert mx["total"] == 3 and {r["ac"]: r["state"] for r in mx["rows"]}["AC-1"] == "FAILING"
    summary = client.get("/api/testing/summary").json()["summary"]
    assert summary["cases"] == 1 and summary["results"]["FAIL"] == 1 and summary["coverage_pct"] == 0
    assert client.get("/api/testing/plan/1").json()["markdown"].startswith("# Test planı — Sprint 1")
    assert client.post("/api/testing/plan/1/write").json()["file"].endswith("plan-sprint-1.md")
    assert client.get("/api/testing/config").json()["config"]["coverage_target"] == 80
    cfg = client.post("/api/testing/config", json={"coverage_target": 90, "design_task": False, "bilinmeyen": 1}).json()["config"]
    assert cfg["coverage_target"] == 90 and cfg["design_task"] is False and "bilinmeyen" not in cfg
    assert client.post("/api/testing/config", json={"coverage_target": 250}).status_code == 400 and client.post("/api/testing/config", json={"perf_samples": "çok"}).status_code == 400


async def test_e2e_scenario_editor_validates_and_never_escapes_the_project(client, hub, tmp_project):
    ok = {"id": "E2E-AC1-giris", "title": "Giriş", "ac_refs": ["ac_1"], "steps": [{"goto": "/"}, {"fill": ["#user", "ali"]}, {"click": "#login"}, {"expect_text": "Hoş geldin"}]}
    res = client.put("/api/testing/scenarios/E2E-AC1-giris", json=ok)
    assert res.status_code == 200, res.text
    assert res.json()["scenario"]["ac_refs"] == ["AC-1"]
    path = os.path.join(tmp_project, "e2e", "scenarios", "E2E-AC1-giris.json")
    assert json.load(open(path, encoding="utf-8"))["steps"][1] == {"fill": ["#user", "ali"]}
    listed = client.get("/api/testing/scenarios").json()["scenarios"]
    assert [s["id"] for s in listed] == ["E2E-AC1-giris"] and not listed[0].get("invalid")                           # sunucunun E2E koşucusu aynı dosyayı geçerli sayar
    for bad in ({**ok, "steps": []}, {**ok, "steps": [{"goto": "/", "click": "#x"}]}, {**ok, "steps": [{"bilinmeyen": 1}]}, {**ok, "steps": [{"fill": ["yalnız-seçici"]}]}):
        assert client.put("/api/testing/scenarios/E2E-AC1-giris", json=bad).status_code == 400
    assert client.put("/api/testing/scenarios/..%2Fescape", json=ok).status_code in (400, 404, 405)
    assert client.put("/api/testing/scenarios/a b", json={**ok, "id": "a b"}).status_code == 400                       # kimlik kuralı
    assert client.put("/api/testing/scenarios/E2E-OTHER", json={**ok, "id": "E2E-AC1-giris"}).json()["scenario"]["id"] == "E2E-OTHER"   # yolun kimliği kazanır
    assert client.delete("/api/testing/scenarios/E2E-OTHER").status_code == 200 and client.delete("/api/testing/scenarios/E2E-OTHER").status_code == 404
    assert not os.path.exists(os.path.join(tmp_project, "e2e", "scenarios", "E2E-OTHER.json"))
