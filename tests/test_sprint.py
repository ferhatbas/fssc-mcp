"""F3 — Dinamik iş planı ve sprint: yüklemeyle başlama, epik/hikâye/görev, kapasite, taahhüt, taşıma, geriye uyum."""

import json
import os
import sys
import time

import pytest

from server import sprint as SP
from server.steps.tasks import normalize_backlog

PY = f'"{sys.executable}"' if " " in sys.executable else sys.executable
PASS_CMD = f'{PY} -c "print(\'ok\')"'

NOTES = ("Kullanıcılar sisteme kayıt olup giriş yapabilmeli. Yöneticiler kayıtları listeleyip filtreleyebilmeli. "
         "Her işlem için denetim kaydı tutulmalı.")
NOTES_MORE = ("Kullanıcılar sisteme kayıt olup giriş yapabilmeli. Raporlar PDF olarak dışa aktarılabilmeli. "
              "Bildirimler e-posta ile gönderilmeli.")


def _wait(client, rid, pred, timeout=150.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        run = client.get(f"/api/runs/{rid}").json()["run"]
        if pred(run):
            return run
        time.sleep(0.2)
    run = client.get(f"/api/runs/{rid}").json()["run"]
    raise AssertionError(f"timeout status={run['status']} steps={[(s['order'], s['kind'], s['status'], s.get('error')) for s in run['steps']]}")


def _sprint_settings(client, **kw):
    base = {"enabled": True, "commit_approval": "auto", "auto_chain": True, "max_tasks": 3}
    client.post("/api/settings/sprint", json={**base, **kw})
    client.post("/api/settings/engine", json={"execution_engine": "template", "approval_mode": "auto", "pacing": "instant",
                                              "auto_verify": False, "auto_commit": False})


def _upload(client, notes=NOTES, title="Notlar"):
    return client.post("/api/specs/upload", data={"title": title, "client_name": "Acme", "meeting_notes": notes}).json()


def _tasks(hub):
    return [i for i in hub.jira_issues.values() if i.get("kind") == "task"]


# ---------------------------------------------------------------------------
# Geriye uyum: sprint.enabled=false
# ---------------------------------------------------------------------------
def test_sprint_disabled_by_default_keeps_legacy_flow(client, hub):
    assert SP.cfg(hub)["enabled"] is False
    res = _upload(client)
    assert "intake" not in res and hub.active_run_for(hub.active_project_id) is None
    assert SP.ensure_state(hub)["sprints"] == []
    # sabit liste hâlâ 10 faz; boş steps = 1-10 tamamı (eski davranış)
    run = client.post("/api/runs", json={"engine": "mcp_client", "client": {"name": "t"}}).json()["run"]
    assert run["mode"] == "legacy" and [s["order"] for s in run["steps"]] == list(range(1, 11))


async def test_upload_never_deletes_existing_jira_items_in_either_mode(client, hub):
    """Karar 17/19: yükleme mevcut Jira kayıtlarını ve geçmişi silmez (eski yıkıcı yeniden yazım kalktı)."""
    await hub.update_jira_issue("JIRA-50", {"order": 50, "title": "Eski görev", "kind": "task", "status": "DONE", "assignee": "BACKEND_DEV"})
    await hub.update_jira_issue("JIRA-3", {"status": "DONE"})
    before_trail = len(hub.jira_issues["JIRA-3"]["audit_trail"])
    _upload(client)
    assert "JIRA-50" in hub.jira_issues and hub.jira_issues["JIRA-50"]["title"] == "Eski görev"
    assert hub.jira_issues["JIRA-3"]["status"] == "DONE"               # başlamış/bitmiş madde yeniden yazılmadı
    assert len(hub.jira_issues["JIRA-3"]["audit_trail"]) > before_trail  # geçmiş korundu (SPEC_UPDATE_SKIPPED eklendi)
    assert hub.jira_issues["JIRA-1"]["title"].startswith("Müşteri Keşif & PRD")  # BACKLOG fazlar yerinde güncellendi
    assert any(a["action"] == "SPEC_UPDATED" for a in hub.jira_issues["JIRA-1"]["audit_trail"])
    # kodlu senaryolu müzakere yüklemede otomatik çalışmaz
    assert hub.deliberation_engine.active_session is None


# ---------------------------------------------------------------------------
# Yüklemeyle başlama ve dinamik plan
# ---------------------------------------------------------------------------
def test_upload_starts_sprint_run_without_button_or_fixed_steps(client, hub, tmp_project):
    _sprint_settings(client)
    res = _upload(client)
    rid = res["intake"]["run_id"]
    run = client.get(f"/api/runs/{rid}").json()["run"]
    assert run["mode"] == "sprint" and run["engine"] == "template" and run["intake_spec_ids"] == ["SPEC-001"]
    done = _wait(client, rid, lambda r: r["is_terminal"])
    assert done["status"] == "COMPLETED"
    kinds = [(s["order"], s["kind"]) for s in done["steps"]]
    assert kinds[:4] == [(1, "phase"), (2, "phase"), (SP.meeting_order(1, "kickoff"), "meeting"), (SP.plan_order(1), "plan")]
    # epik ▸ hikâye ▸ görev ağacı notlardan üretildi; sabit 1-10 faz listesi koşmadı (tek sprintte 5,6,7,9 inceleme kapıları var)
    kinds_all = {i["kind"] for i in hub.jira_issues.values() if i.get("kind")}
    assert {"epic", "story", "task"} <= kinds_all
    stories = SP.existing_stories(hub)
    assert len(stories) == 3 and all(s["ac_refs"] and s["parent_id"] for s in stories)
    work_types = {i["work_type"] for i in _tasks(hub)}
    assert {"SCAFFOLD", "FEATURE", "DEVOPS", "DOCS"} <= work_types
    assert 4 not in [s["order"] for s in done["steps"]] and 10 not in [s["order"] for s in done["steps"]]  # iskelet/dokümantasyon artık iş türü
    # bekleyen değerlendirme tüketildi
    assert SP.ensure_state(hub)["pending_intake"] is None


def test_two_consecutive_sprints_with_capacity_commitment_and_closure(client, hub, tmp_project):
    _sprint_settings(client, max_tasks=3)
    rid = _upload(client)["intake"]["run_id"]
    done = _wait(client, rid, lambda r: r["is_terminal"])
    assert done["status"] == "COMPLETED"
    sprints = SP.ensure_state(hub)["sprints"]
    assert len(sprints) >= 2 and [s["sprint_number"] for s in sprints][:2] == [1, 2]
    s1, s2 = sprints[0], sprints[1]
    assert s1["status"] == "CLOSED" and s2["status"] == "CLOSED" and s1["closed_at"] and s2["committed_at"] > s1["closed_at"]
    assert len(s1["committed_issue_ids"]) == 3 and s1["commit_approval"]["by"] == "SERVER"
    # kapasite: ilk sprintte max_tasks; sonrasında min(max_tasks, ortalama + 1)
    assert s1["capacity"]["max_tasks"] == 3 and "İlk sprint" in s1["capacity"]["basis"]
    assert s2["capacity"]["max_tasks"] == min(3, len(s1["completed_issue_ids"]) + 1)
    assert s1["metrics"]["committed"] == 3 and s1["metrics"]["completed"] == 3 and s1["metrics"]["first_pass"] == 3
    # taahhüt dosyası yazıldı ve değişmez
    path = os.path.join(tmp_project, "FS-docs", "sprints", "sprint-1.json")
    doc = json.load(open(path, encoding="utf-8"))
    assert doc["sprint_number"] == 1 and [i["issue_id"] for i in doc["items"]] == s1["committed_issue_ids"] and doc["capacity"]["max_tasks"] == 3
    SP.write_commitment(hub, tmp_project, "FS-docs", s1, {"tampered": True})
    assert json.load(open(path, encoding="utf-8")) == doc
    # review-retro tutanağı ve kalıcı sprint durumu
    assert os.path.isfile(os.path.join(tmp_project, s1["meetings"]["review_retro"]))
    hub.flush_now()
    saved = json.load(open(os.path.join(tmp_project, ".fs-workspace", "sprint_state.json"), encoding="utf-8"))
    assert saved["sprints"][0]["sprint_number"] == 1 and saved["schema_version"] == 1
    # tamamlanan görevler kapatılan sprinte dondurulur; bütün görevleri biten hikâye DONE olur
    assert all(hub.jira_issues[i]["closed_in_sprint"] == 1 for i in s1["completed_issue_ids"])
    # ürün bitince proje DONE
    assert SP.ensure_state(hub)["project_status"] == "DONE"


def test_manual_commit_waits_for_manager_then_proceeds(client, hub):
    _sprint_settings(client, commit_approval="manual", max_tasks=50, auto_chain=False)
    rid = _upload(client)["intake"]["run_id"]
    waiting = _wait(client, rid, lambda r: r["status"] == "WAITING_APPROVAL")
    assert waiting["gate_kind"] == "sprint" and (hub.pending_step_approval or {}).get("kind") == "sprint_commit"
    sp = SP.get_sprint(hub, 1)
    assert sp["status"] == "PLANNING" and sp["committed_at"] is None and hub.jira_issues[sp["proposed_issue_ids"][0]].get("sprint") is None
    assert client.post("/api/sprints/2/commit").status_code == 409
    assert client.post("/api/sprints/1/commit").json()["status"] == "APPROVED"
    done = _wait(client, rid, lambda r: r["is_terminal"])
    assert done["status"] == "COMPLETED"
    sp = SP.get_sprint(hub, 1)
    assert sp["commit_approval"]["by"] == "MANAGER" and sp["status"] == "CLOSED"


# ---------------------------------------------------------------------------
# Taşıma: bilerek başarısız görev sprint 2'ye taşınır ve yeniden kapsamlanır
# ---------------------------------------------------------------------------
def test_failed_task_is_carried_over_rescoped_and_committed_in_sprint_2(client, hub, tmp_project, monkeypatch):
    monkeypatch.setenv("FSSC_DRY_RUN_FAIL_TASK", "1")
    _sprint_settings(client, max_tasks=3)
    client.post("/api/settings/engine", json={"auto_verify": True, "max_fix_rounds": 1,
                                              "verification": {"install": PASS_CMD, "test": PASS_CMD}})
    rid = _upload(client)["intake"]["run_id"]
    done = _wait(client, rid, lambda r: r["is_terminal"], timeout=240)
    assert done["status"] == "COMPLETED", done["cancel_reason"]
    s1, s2 = SP.ensure_state(hub)["sprints"][:2]
    assert len(s1["carried_over"]) == 1
    carried = s1["carried_over"][0]
    assert carried["reason"] == "FIX_LIMIT" and carried["count"] == 1 and carried["issue_id"] in s1["committed_issue_ids"]
    assert carried["issue_id"] not in s1["completed_issue_ids"] and s1["metrics"]["fix_rounds"] == 1
    # yeniden kapsamlama adımı sprint 2 taahhüdünden önce koştu; iş aynı tanımla taahhüt edilmedi
    orders = [(s["kind"], s["order"], s["sprint"]) for s in done["steps"]]
    assert orders.index(("rescope", hub.jira_issues[carried["issue_id"]]["order"], None)) < orders.index(("plan", SP.plan_order(2), 2))
    issue = hub.jira_issues[carried["issue_id"]]
    assert issue["title"].endswith("(yeniden kapsamlandı)") and issue["needs_rescope"] is False and issue["rescoped_at"]
    assert any(a["action"] == "RESCOPED" for a in issue["audit_trail"]) and any(a["action"] == "CARRY_OVER" for a in issue["audit_trail"])
    # sprint 2 taahhüdünde ilk sırada, taşınan olarak
    doc2 = json.load(open(os.path.join(tmp_project, "FS-docs", "sprints", "sprint-2.json"), encoding="utf-8"))
    assert doc2["items"][0]["issue_id"] == carried["issue_id"] and doc2["items"][0]["carried_from"] == 1
    assert carried["issue_id"] in s2["completed_issue_ids"] and issue["status"] == "DONE" and issue["sprint"] == 2
    assert issue["carry_over"]["count"] == 1


def test_carry_over_limit_blocks_sprint(client, hub, monkeypatch):
    monkeypatch.setenv("FSSC_DRY_RUN_FAIL_TASK", "1")
    _sprint_settings(client, max_tasks=3, carry_over_limit=0)
    client.post("/api/settings/engine", json={"auto_verify": True, "max_fix_rounds": 0, "verification": {"install": PASS_CMD, "test": PASS_CMD}})
    rid = _upload(client)["intake"]["run_id"]
    done = _wait(client, rid, lambda r: r["is_terminal"], timeout=200)
    assert done["status"] == "FAILED" and "CARRY_OVER_LIMIT" in done["cancel_reason"]
    s1 = SP.get_sprint(hub, 1)
    assert s1["status"] == "BLOCKED" and s1["blocked"]["reason"] == "CARRY_OVER_LIMIT" and s1["blocked"]["previous_status"] == "IN_REVIEW"
    assert SP.get_sprint(hub, 2) is None   # bloke sprintten sonra yeni sprint açılmaz


# ---------------------------------------------------------------------------
# Yükleme kuyruğu, hikâye hikâye yapılandırma, kimlikler, roller
# ---------------------------------------------------------------------------
def test_second_upload_merges_into_pending_intake_and_does_not_open_second_run(client, hub):
    _sprint_settings(client)
    client.post("/api/settings/engine", json={"execution_engine": "mcp_client"})
    r1 = _upload(client)
    assert r1["intake"]["run_status"] == "STARTED"
    r2 = _upload(client, NOTES_MORE, title="Ek notlar")
    assert r2["intake"]["run_status"] == "EXISTING" and r2["intake"]["run_id"] == r1["intake"]["run_id"]
    assert SP.ensure_state(hub)["pending_intake"]["spec_ids"] == ["SPEC-001", "SPEC-002"]
    assert len([r for r in hub.runs.values() if not r.is_terminal]) == 1
    rid = r1["intake"]["run_id"]
    nxt = client.post(f"/api/runs/{rid}/next-step", json={"client": {"name": "t"}}).json()
    assert nxt["status"] == "STEP" and nxt["order"] == 1
    assert "PDF" in nxt["user_context"] and "denetim kaydı" in nxt["user_context"]   # iki yüklemenin metni de PM'e verildi
    assert hub.runs[rid].intake_spec_ids == ["SPEC-001", "SPEC-002"]


def test_followup_intake_starts_one_run_after_finish_and_diff_adds_only_new_stories(client, hub):
    _sprint_settings(client, max_tasks=50)
    rid = _upload(client)["intake"]["run_id"]
    _wait(client, rid, lambda r: r["is_terminal"])
    before = {s["id"] for s in SP.existing_stories(hub)}
    assert len(before) == 3
    res = _upload(client, NOTES_MORE, title="Ek notlar")
    rid2 = res["intake"]["run_id"]
    assert rid2 and rid2 != rid
    _wait(client, rid2, lambda r: r["is_terminal"])
    after = SP.existing_stories(hub)
    new = [s for s in after if s["id"] not in before]
    assert len(new) == 2   # "kayıt olup giriş yapabilmeli" tekrarlanmadı: yalnızca fark
    assert len(SP.ensure_state(hub)["sprints"]) >= 2 and SP.get_sprint(hub, 1)["status"] == "CLOSED"
    assert all(hub.jira_issues[i]["status"] == "DONE" for i in SP.get_sprint(hub, 1)["committed_issue_ids"])   # eski sprint değişmedi


def test_structuring_continues_story_by_story_with_no_total_cap(client, hub):
    long_notes = " ".join(f"{name} için ayrı bir kullanıcı akışı sunulmalıdır." for name in ("Siparişler", "Faturalar", "Raporlar", "Bildirimler"))
    _sprint_settings(client, max_tasks=50)
    client.post("/api/settings/engine", json={"max_backlog_tasks": 2})
    rid = _upload(client, long_notes)["intake"]["run_id"]
    done = _wait(client, rid, lambda r: r["is_terminal"])
    assert done["status"] == "COMPLETED"
    structure = [s for s in done["steps"] if s["kind"] == "structure"]
    assert structure, "tek ARCHITECT adımı sığmadığında devam adımı eklenmeli"
    stories = SP.existing_stories(hub)
    assert len(stories) == 4 and SP.stories_without_tasks(hub) == []   # toplam madde sınırı yok: her hikâye görev aldı
    feats = [i for i in _tasks(hub) if i["work_type"] == "FEATURE"]
    assert len(feats) == 4


async def test_task_keys_are_project_wide_and_roles_follow_work_types(hub):
    from server import pipeline as P
    from server.runs import PipelineRun
    run = PipelineRun(project_id=hub.active_project_id)
    t1 = normalize_backlog([{"id": "a", "title": "Bir", "role": "BACKEND_DEV"}, {"id": "b", "title": "İki", "role": "E2E_TESTER"}])
    r1 = await P._create_task_issues(hub, run, t1, parent_id="JIRA-2", origin="ARCHITECT")
    t2 = normalize_backlog([{"id": "a", "title": "Üç"}])   # LLM yine "a" der; anahtarı sunucu verir
    r2 = await P._create_task_issues(hub, run, t2, parent_id="JIRA-2", origin="ARCHITECT")
    keys = [hub.jira_issues[r.issue_id]["task_key"] for r in r1 + r2]
    assert keys == ["T-01", "T-02", "T-03"]
    assert hub.jira_issues[r1[1].issue_id]["assignee"] == "QA" and hub.jira_issues[r1[1].issue_id]["work_type"] == "TEST"   # E2E_TESTER sessizce geliştiriciye düşmez
    up = await P._create_task_issues(hub, run, normalize_backlog([{"title": "UAT eksik"}]), parent_id="JIRA-9", origin="PO")
    assert hub.jira_issues[up[0].issue_id]["task_key"] == "UAT-01" and hub.jira_issues[up[0].issue_id]["origin"] == "UAT"


# ---------------------------------------------------------------------------
# Birim: kapasite, seçim sırası, dondurma ve değişiklik izi
# ---------------------------------------------------------------------------
async def test_capacity_formula_and_selection_order(hub):
    await hub.update_settings({"sprint": {"enabled": True, "max_tasks": 5}})
    assert SP.capacity(hub)[0] == 5
    st = SP.ensure_state(hub)
    for n, done in ((1, 2), (2, 3), (3, 4)):
        st["sprints"].append({"sprint_number": n, "status": "CLOSED", "metrics": {"completed": done}, "completed_issue_ids": ["x"] * done})
    cap, basis = SP.capacity(hub)
    assert cap == 4 and "min(5, 3 + 1)" in basis   # son üç sprint ortalaması 3 → 3 + 1
    await hub.update_settings({"sprint": {"max_tasks": 2}})
    assert SP.capacity(hub)[0] == 2

    def mk(iid, order, **kw):
        base = {"order": order, "title": iid, "kind": "task", "status": "BACKLOG", "priority": "P1", "assignee": "BACKEND_DEV", "work_type": "FEATURE"}
        return hub.update_jira_issue(iid, {**base, **kw})
    await mk("JIRA-61", 61)
    await mk("JIRA-62", 62, origin="UAT")
    await mk("JIRA-63", 63, work_type="BUG", priority="P0")
    await mk("JIRA-64", 64, carry_over={"count": 1, "last_reason": "NOT_STARTED"})
    await mk("JIRA-65", 65, depends_on=["JIRA-66"])
    await mk("JIRA-66", 66, priority="P2")
    await mk("JIRA-67", 67, needs_rescope=True)
    items, out = SP.select_items(hub, 10)
    ids = [i["id"] for i in items]
    assert ids[:3] == ["JIRA-64", "JIRA-63", "JIRA-62"]                # taşınan, yüksek öncelikli hata, UAT iyileştirmesi
    assert ids.index("JIRA-66") < ids.index("JIRA-65")                  # bağımlılık sırası bozulmaz
    assert "JIRA-67" not in ids                                         # yeniden kapsamlanmamış iş taahhüt edilmez
    small, rest = SP.select_items(hub, 2)
    assert len(small) == 2 and all(r["reason"] in ("KAPASİTE",) or r["reason"].startswith("BAĞIMLILIK") for r in rest)


async def test_closed_sprint_items_are_frozen_and_changes_are_tracked(hub):
    st = SP.ensure_state(hub)
    st["sprints"].append({"sprint_number": 1, "status": "CLOSED", "metrics": {}, "completed_issue_ids": []})
    await hub.update_jira_issue("JIRA-70", {"order": 70, "title": "Kapalı iş", "kind": "task", "status": "DONE", "closed_in_sprint": 1})
    await hub.update_jira_issue("JIRA-70", {"title": "Başka başlık"})
    issue = hub.jira_issues["JIRA-70"]
    assert issue["title"] == "Kapalı iş" and issue["audit_trail"][-1]["action"] == "CHANGE_REJECTED_CLOSED_SPRINT"
    # açık madde değişirse denetim izine yazılır (karar 19d)
    await hub.update_jira_issue("JIRA-71", {"order": 71, "title": "Açık iş", "kind": "task", "status": "BACKLOG"})
    await hub.update_jira_issue("JIRA-71", {"title": "Güncel başlık"})
    last = hub.jira_issues["JIRA-71"]["audit_trail"][-1]
    assert last["action"] == "FIELD_CHANGED" and "Açık iş" in last["notes"] and "Güncel başlık" in last["notes"]


def test_changed_story_after_closed_sprint_becomes_new_item_with_reference(client, hub):
    _sprint_settings(client, max_tasks=50)
    rid = _upload(client)["intake"]["run_id"]
    _wait(client, rid, lambda r: r["is_terminal"])
    old = next(s for s in SP.existing_stories(hub) if "kayıt olup giriş" in s["title"])
    assert old["status"] == "DONE" and old["closed_in_sprint"] == 1
    # aynı hikâye yeni kabul kriteriyle gelir (PM çıktısı): kapatılmış madde değişmez, yeni madde supersedes ile eklenir
    import asyncio
    from server import pipeline as P
    from server.runs import PipelineRun, StepRecord
    run = PipelineRun(project_id=hub.active_project_id, mode="sprint")
    rec = StepRecord(order=1, issue_id="JIRA-1", role="PM")
    created = asyncio.run(P.expand_intake(hub, run, rec, {"stories": [{"id": "S-9", "title": old["title"], "acceptance_criteria": ["Yeni: iki faktörlü giriş zorunlu"]}]}))
    assert created == 1
    new = [s for s in SP.existing_stories(hub) if s.get("supersedes") == old["id"]]
    assert len(new) == 1 and new[0]["related_to"] == old["id"] and new[0]["acceptance_criteria"] == ["Yeni: iki faktörlü giriş zorunlu"]
    assert old["acceptance_criteria"] != new[0]["acceptance_criteria"]


def test_sprint_rest_endpoints(client, hub):
    _sprint_settings(client, max_tasks=50)
    rid = _upload(client)["intake"]["run_id"]
    _wait(client, rid, lambda r: r["is_terminal"])
    state = client.get("/api/sprints").json()
    assert state["settings"]["enabled"] is True and state["state"]["sprints"][0]["sprint_number"] == 1
    detail = client.get("/api/sprints/1").json()
    assert detail["sprint"]["status"] == "CLOSED" and detail["items"] and client.get("/api/sprints/99").status_code == 404
    plan = client.get("/api/plan").json()
    assert plan["epics"] and plan["epics"][0]["children"][0]["children"]   # epik ▸ hikâye ▸ görev
    assert client.post("/api/settings/sprint", json={"max_tasks": 999, "commit_approval": "bogus"}).json()["sprint"]["max_tasks"] == 50
    assert client.get("/api/settings/sprint").json()["sprint"]["commit_approval"] == "auto"
