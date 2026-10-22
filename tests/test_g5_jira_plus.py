"""G5 — Jira+: madde modeli (tip/etiket/bileşen/tahmin/son tarih), alan geçmişi, yumuşak silme/geri alma, yorum, bağ (ters bağ), ek,
Kanban taşıma (durum + sütun sırası), toplu işlem, JQL benzeri sorgu, kayıtlı süzgeçler, zaman çizelgesi ("neden bu durumda"), kanıt, sprint panosu;
sunucu tarafı planlama silinmiş maddeyi görmez."""

import os

import pytest

from server import driver as DRV
from server import jira_plus as JP
from server import sprint as SP
from server.runs import PipelineRun, StepRecord


async def _task(hub, title="İş", **kw):
    n = len(hub.jira_issues) + 1
    return await hub.add_jira_issue({"id": f"JIRA-{n}", "title": title, "issue_type": "TASK", "kind": "task", "status": "BACKLOG",
                                     "assignee": "BACKEND_DEV", "priority": "P1", "work_type": "FEATURE", **kw})


# ---------------------------------------------------------------------------
# Düzenleme ve alan geçmişi
# ---------------------------------------------------------------------------
async def test_edit_issue_validates_fields_and_records_history(client, hub):
    t = await _task(hub, "Ödeme API")
    res = client.patch(f"/api/jira/issues/{t['id']}", json={"labels": "api, auth, api", "components": ["backend"], "estimate": "m", "due": "2026-11-01",
                                                            "priority": "P0", "issue_type": "IMPROVEMENT", "watchers": ["PM"], "unknown": 1})
    assert res.status_code == 200, res.text
    i = res.json()["issue"]
    assert i["labels"] == ["api", "auth"] and i["components"] == ["backend"] and i["estimate"] == "M" and i["due"] == "2026-11-01"
    assert i["priority"] == "P0" and i["issue_type"] == "IMPROVEMENT" and i["kind"] == "task" and i["watchers"] == ["PM"]
    fields = [h["field"] for h in i["history"]]
    assert {"labels", "components", "estimate", "due", "priority", "issue_type", "watchers"} <= set(fields)
    assert any(a["action"] == "FIELD_CHANGED" and "priority" in a["notes"] for a in i["audit_trail"])
    # doğrulama hataları
    assert client.patch(f"/api/jira/issues/{t['id']}", json={"due": "1 Kasım"}).status_code == 400
    assert client.patch(f"/api/jira/issues/{t['id']}", json={"issue_type": "WISH"}).status_code == 400
    assert client.patch(f"/api/jira/issues/{t['id']}", json={"estimate": "XXL"}).status_code == 400
    assert client.patch(f"/api/jira/issues/{t['id']}", json={"parent_id": t["id"]}).status_code == 400
    assert client.patch("/api/jira/issues/JIRA-999", json={"title": "x"}).status_code == 404
    # ebeveyn döngüsü: A'nın ebeveyni B ise B'nin ebeveyni A olamaz
    u = await _task(hub, "Alt iş")
    assert client.patch(f"/api/jira/issues/{u['id']}", json={"parent_id": t["id"]}).status_code == 200
    assert client.patch(f"/api/jira/issues/{t['id']}", json={"parent_id": u["id"]}).status_code == 400
    # değişiklik yoksa geçmiş büyümez
    before = len(hub.jira_issues[t["id"]]["history"])
    assert client.patch(f"/api/jira/issues/{t['id']}", json={"priority": "P0"}).status_code == 200
    assert len(hub.jira_issues[t["id"]]["history"]) == before
    # tip değişince kind eşlenir (sunucu planlaması)
    client.patch(f"/api/jira/issues/{t['id']}", json={"issue_type": "STORY"})
    assert hub.jira_issues[t["id"]]["kind"] == "story"


async def test_soft_delete_restore_and_server_consumers_ignore_deleted(client, hub):
    t = await _task(hub, "Silinecek")
    assert DRV._open_work(hub) is True and any(i["id"] == t["id"] for i in SP.candidates(hub))
    res = client.delete(f"/api/jira/issues/{t['id']}?reason=yanlış%20açıldı")
    assert res.status_code == 200 and res.json()["issue"]["deleted"]["reason"] == "yanlış açıldı"
    assert DRV._open_work(hub) is False and not any(i["id"] == t["id"] for i in SP.candidates(hub))
    assert t["id"] not in {i["id"] for i in JP.query(hub, "type = TASK")}
    assert t["id"] in {i["id"] for i in JP.query(hub, "deleted = true")}
    assert t["id"] in {i["id"] for i in JP.query(hub, "type = TASK", include_deleted=True)}
    assert client.patch(f"/api/jira/issues/{t['id']}", json={"title": "x"}).status_code == 409        # silinmiş madde düzenlenemez
    assert client.post(f"/api/jira/issues/{t['id']}/move", json={"status": "DONE"}).status_code == 409
    assert client.post(f"/api/jira/issues/{t['id']}/restore").status_code == 200
    assert hub.jira_issues[t["id"]]["deleted"] is None and DRV._open_work(hub) is True
    assert [a["action"] for a in hub.jira_issues[t["id"]]["audit_trail"][-2:]] == ["DELETED", "RESTORED"]
    # başlamış iş silinemez
    hub.jira_issues[t["id"]]["status"] = "IN_PROGRESS"
    assert client.delete(f"/api/jira/issues/{t['id']}").status_code == 409
    # süren sprintin taahhüdündeki iş silinemez
    hub.jira_issues[t["id"]]["status"] = "BACKLOG"
    hub.jira_issues[t["id"]]["sprint"] = 1
    sp = SP.new_sprint(hub, 1, "Hedef")
    SP.set_sprint_status(hub, sp, "IN_PROGRESS")
    assert client.delete(f"/api/jira/issues/{t['id']}").status_code == 409


# ---------------------------------------------------------------------------
# Yorum, bağ, ek
# ---------------------------------------------------------------------------
async def test_comments_links_and_attachments(client, hub):
    a = await _task(hub, "A")
    b = await _task(hub, "B")
    c = client.post(f"/api/jira/issues/{a['id']}/comments", json={"text": "**Not:** önce şema"}).json()["comment"]
    assert c["author"] == "MANAGER" and c["kind"] == "manager" and hub.jira_issues[a["id"]]["comments"][0]["id"] == c["id"]
    assert client.post(f"/api/jira/issues/{a['id']}/comments", json={"text": "  "}).status_code == 400
    ag = client.post(f"/api/jira/issues/{a['id']}/comments", json={"text": "bitti", "author": "QA", "kind": "agent"}).json()["comment"]
    assert ag["kind"] == "agent" and ag["author"] == "QA"
    assert client.delete(f"/api/jira/issues/{a['id']}/comments/{c['id']}").status_code == 200
    assert [x["id"] for x in hub.jira_issues[a["id"]]["comments"]] == [ag["id"]]
    assert client.delete(f"/api/jira/issues/{a['id']}/comments/cm-yok").status_code == 404
    # bağ: A blocks B → B is_blocked_by A
    res = client.post(f"/api/jira/issues/{a['id']}/links", json={"type": "blocks", "target": b["id"]})
    assert res.status_code == 200 and res.json()["link"]["type"] == "blocks"
    assert [(x["type"], x["target"]) for x in hub.jira_issues[b["id"]]["links"]] == [("is_blocked_by", a["id"])]
    assert client.post(f"/api/jira/issues/{a['id']}/links", json={"type": "blocks", "target": b["id"]}).status_code == 200    # tekrar eklenmez
    assert len(hub.jira_issues[a["id"]]["links"]) == 1
    assert client.post(f"/api/jira/issues/{a['id']}/links", json={"type": "blocks", "target": a["id"]}).status_code == 400
    assert client.post(f"/api/jira/issues/{a['id']}/links", json={"type": "loves", "target": b["id"]}).status_code == 400
    assert client.post(f"/api/jira/issues/{a['id']}/links", json={"type": "relates", "target": "JIRA-999"}).status_code == 404
    assert client.delete(f"/api/jira/issues/{a['id']}/links/blocks/{b['id']}").status_code == 200
    assert hub.jira_issues[a["id"]]["links"] == [] and hub.jira_issues[b["id"]]["links"] == []
    # ek
    att = client.post(f"/api/jira/issues/{a['id']}/attachments", json={"path": ".fs-workspace/e2e/screenshots/login.png"}).json()["attachment"]
    assert att["name"] == "login.png" and att["id"].startswith("att-")
    assert client.post(f"/api/jira/issues/{a['id']}/attachments", json={"path": "../../etc/passwd"}).status_code == 400
    assert client.post(f"/api/jira/issues/{a['id']}/attachments", json={}).status_code == 400
    assert client.delete(f"/api/jira/issues/{a['id']}/attachments/{att['id']}").status_code == 200
    assert hub.jira_issues[a["id"]]["attachments"] == []
    # eski dize ekler sözlüğe çevrilir
    hub.jira_issues[a["id"]]["attachments"] = ["docs/x.md"]
    assert JP.get(hub, a["id"])["attachments"][0]["name"] == "x.md"


# ---------------------------------------------------------------------------
# Kanban taşıma ve toplu işlem
# ---------------------------------------------------------------------------
async def test_kanban_move_sets_status_and_column_rank(client, hub):
    a = await _task(hub, "A")
    b = await _task(hub, "B")
    c = await _task(hub, "C")
    res = client.post(f"/api/jira/issues/{b['id']}/move", json={"status": "IN_PROGRESS", "index": 0})
    assert res.status_code == 200 and res.json()["issue"]["status"] == "IN_PROGRESS" and res.json()["issue"]["board_rank"] == 0
    client.post(f"/api/jira/issues/{c['id']}/move", json={"status": "IN_PROGRESS", "index": 0})
    assert (hub.jira_issues[c["id"]]["board_rank"], hub.jira_issues[b["id"]]["board_rank"]) == (0, 1)
    client.post(f"/api/jira/issues/{a['id']}/move", json={"status": "IN_PROGRESS"})                       # index yok → sona
    assert hub.jira_issues[a["id"]]["board_rank"] == 2
    client.post(f"/api/jira/issues/{a['id']}/move", json={"status": "IN_PROGRESS", "index": 0})           # aynı sütunda yeniden sıralama
    assert [hub.jira_issues[i]["board_rank"] for i in (a["id"], c["id"], b["id"])] == [0, 1, 2]
    assert hub.jira_issues[a["id"]]["audit_trail"][-1]["action"] == "REORDERED"
    assert any(a_["action"] == "MANUAL_STATUS" for a_ in hub.jira_issues[b["id"]]["audit_trail"])
    assert hub.jira_issues[b["id"]]["history"][-1]["field"] == "status" and hub.jira_issues[b["id"]]["history"][-1]["to"] == "IN_PROGRESS"
    done = client.post(f"/api/jira/issues/{b['id']}/move", json={"status": "DONE"}).json()["issue"]
    assert done["status"] == "DONE" and done["audit_trail"][-1]["action"] == "STATUS_OVERRIDE"
    assert client.post(f"/api/jira/issues/{b['id']}/move", json={"status": "SOMEWHERE"}).status_code == 400
    # kapatılmış sprintin maddesi taşınamaz
    sp = SP.new_sprint(hub, 1, "Hedef")
    SP.set_sprint_status(hub, sp, "CLOSED")
    hub.jira_issues[c["id"]]["closed_in_sprint"] = 1
    assert client.post(f"/api/jira/issues/{c['id']}/move", json={"status": "DONE"}).status_code == 409


async def test_bulk_actions_report_per_item_results(client, hub):
    a = await _task(hub, "A")
    b = await _task(hub, "B")
    res = client.post("/api/jira/bulk", json={"ids": [a["id"], b["id"], "JIRA-999"], "action": "labels_add", "value": "sprint-1"}).json()
    assert res["ok"] == 2 and res["failed"] == 1 and res["results"][2]["error"] == "bulunamadı"
    assert hub.jira_issues[a["id"]]["labels"] == ["sprint-1"] and hub.jira_issues[b["id"]]["labels"] == ["sprint-1"]
    res = client.post("/api/jira/bulk", json={"ids": [a["id"], b["id"]], "action": "status", "value": "SELECTED_FOR_DEV"}).json()
    assert res["ok"] == 2 and {hub.jira_issues[a["id"]]["status"], hub.jira_issues[b["id"]]["status"]} == {"SELECTED_FOR_DEV"}
    res = client.post("/api/jira/bulk", json={"ids": [a["id"]], "action": "priority", "value": "P9"}).json()
    assert res["failed"] == 1 and "Öncelik" in res["results"][0]["error"]
    res = client.post("/api/jira/bulk", json={"ids": [a["id"], b["id"]], "action": "delete", "value": "temizlik"}).json()
    assert res["ok"] == 2 and hub.jira_issues[a["id"]]["deleted"]["reason"] == "temizlik"
    assert client.post("/api/jira/bulk", json={"ids": [a["id"]], "action": "explode"}).status_code == 400
    res = client.post("/api/jira/bulk", json={"ids": [a["id"]], "action": "restore"}).json()
    assert res["ok"] == 1 and hub.jira_issues[a["id"]]["deleted"] is None
    res = client.post("/api/jira/bulk", json={"ids": [a["id"]], "action": "labels_remove", "value": "sprint-1"}).json()
    assert res["ok"] == 1 and hub.jira_issues[a["id"]]["labels"] == []


# ---------------------------------------------------------------------------
# JQL benzeri sorgu ve kayıtlı süzgeçler
# ---------------------------------------------------------------------------
def test_query_language_parses_matches_and_sorts():
    issues = [
        {"id": "A", "key": "DEV-1", "order": 1, "title": "Ödeme API", "description": "", "status": "BACKLOG", "issue_type": "TASK", "assignee": "BACKEND_DEV", "priority": "P1", "labels": ["api"], "sprint": 1},
        {"id": "B", "key": "DEV-2", "order": 2, "title": "Giriş ekranı", "description": "oturum", "status": "DONE", "issue_type": "TASK", "assignee": "FRONTEND_DEV", "priority": "P0", "labels": [], "planned_sprint": 2},
        {"id": "C", "key": "DEV-3", "order": 3, "title": "Test planı", "description": "", "status": "BACKLOG", "issue_type": "TEST_CASE", "assignee": "QA", "priority": "P2", "labels": ["api", "test"], "due": "2026-10-01"},
        {"id": "D", "key": "DEV-4", "order": 4, "title": "Hata", "description": "", "status": "IN_PROGRESS", "issue_type": "BUG", "assignee": "QA", "priority": "P0", "labels": []},
    ]

    def ids(q):
        ast, order = JP.parse_query(q)
        out = [i for i in issues if JP.match(i, ast)]
        if order:
            out.sort(key=lambda i: str(JP.FIELDS[order[0]](i) or ""), reverse=order[1])
        return [i["id"] for i in out]
    assert ids("status in (BACKLOG, DONE) and assignee = QA") == ["C"]
    assert ids("label = api") == ["A", "C"]
    assert ids("label != api") == ["B", "D"]
    assert ids('text ~ "ödeme" or text ~ oturum') == ["A", "B"]
    assert ids("type != BUG and not (priority = P2)") == ["A", "B"]
    assert ids("sprint = 1 or planned_sprint = 2") == ["A", "B"]
    assert ids("due < 2026-11-01") == ["C"] and ids("due is empty") == ["A", "B", "D"] and ids("due is not empty") == ["C"]
    assert ids("status not in (DONE) and type in (TASK, TEST_CASE)") == ["A", "C"]
    assert ids("priority = P0 order by order desc") == ["D", "B"]
    assert ids("order > 2") == ["C", "D"]
    assert JP.parse_query("") == (None, None) and JP.parse_query("order by priority desc") == (None, ("priority", True))
    for bad in ("colour = red", "status = ", "(status = DONE", "status in BACKLOG", "status like DONE", "order by colour"):
        with pytest.raises(ValueError):
            JP.parse_query(bad)


async def test_query_endpoint_and_saved_filters(client, hub):
    a = await _task(hub, "Ödeme API", labels=["api"])
    await _task(hub, "Giriş", assignee="FRONTEND_DEV")
    res = client.get("/api/jira/query", params={"q": "label = api and assignee = BACKEND_DEV"}).json()
    assert res["count"] == 1 and res["issues"][0]["id"] == a["id"]
    assert client.get("/api/jira/query", params={"q": "colour = red"}).status_code == 400
    assert client.get("/api/jira/query", params={"q": ""}).json()["count"] == len(hub.jira_issues)
    assert client.post("/api/jira/filters", json={"name": "API işleri", "q": "label = api"}).status_code == 200
    assert client.post("/api/jira/filters", json={"name": "Bozuk", "q": "colour = red"}).status_code == 400
    assert client.post("/api/jira/filters", json={"name": "", "q": "label = api"}).status_code == 400
    client.post("/api/jira/filters", json={"name": "API işleri", "q": "label = api order by priority"})                      # aynı ad: üzerine yazar
    lst = client.get("/api/jira/filters").json()
    assert [f["name"] for f in lst["filters"]] == ["API işleri"] and lst["filters"][0]["q"].endswith("order by priority") and "label" in lst["fields"]
    assert hub.get_settings()["jira_filters"][0]["name"] == "API işleri"                                                      # ayarlarda kalıcı
    assert client.delete("/api/jira/filters/API%20i%C5%9Fleri").status_code == 200 and client.get("/api/jira/filters").json()["filters"] == []
    assert client.delete("/api/jira/filters/yok").status_code == 404


# ---------------------------------------------------------------------------
# Zaman çizelgesi, kanıt
# ---------------------------------------------------------------------------
async def test_timeline_and_evidence_merge_history_audit_comments_and_steps(client, hub, tmp_project):
    t = await _task(hub, "Ödeme API", ac_refs=["AC-1", "AC-2"], acceptance_criteria=["Ödeme alınır", "Hata döner"])
    run = PipelineRun(project_id=hub.active_project_id, project_dir=tmp_project, engine="mcp_client",
                      steps=[StepRecord(order=11, issue_id=t["id"], role="BACKEND_DEV", kind="task", status="DONE", started_at="2026-10-12T10:00:00+00:00",
                                        finished_at="2026-10-12T10:05:00+00:00", summary="Ödeme ucu yazıldı", commit="abc1234", commit_status="COMMITTED",
                                        verification={"status": "PASSED", "summary": "Doğrulama PASSED: test:✓ (3 geçti)", "tests": {"total": 3, "passed": 3, "failed": 0, "errors": 0, "skipped": 0}},
                                        dod=[{"key": "verification_passed", "ok": True, "text": "Doğrulama PASSED"}, {"key": "committed", "ok": True, "text": "Commit"}])])
    hub.register_run(run)
    run.status = "COMPLETED"
    client.post(f"/api/jira/issues/{t['id']}/comments", json={"text": "gözden geçirildi"})
    client.patch(f"/api/jira/issues/{t['id']}", json={"priority": "P0"})
    await hub.update_jira_issue(t["id"], {"status": "DONE", "agent_id": "PM", "audit_action": "APPROVED", "audit_notes": "Yönetici onayladı"})
    tl = client.get(f"/api/jira/issues/{t['id']}/timeline").json()
    kinds = {e["kind"] for e in tl["entries"]}
    assert {"field", "audit", "comment", "step"} <= kinds and tl["status"] == "DONE"
    assert tl["entries"] == sorted(tl["entries"], key=lambda e: e["ts"])
    assert tl["why"].startswith("DONE: APPROVED") and "Yönetici onayladı" in tl["why"] and "PM" in tl["why"]
    step = next(e for e in tl["entries"] if e["kind"] == "step")
    assert step["commit"] == "abc1234" and step["verification"] == "PASSED" and step["run_id"] == run.run_id
    # kanıt: adım/commit/doğrulama/DoD/AC kapsama (test dosyası AC-1'i anar; junit yok → anma temelli)
    os.makedirs(os.path.join(tmp_project, "tests"), exist_ok=True)
    open(os.path.join(tmp_project, "tests", "test_payment.py"), "w", encoding="utf-8").write("# AC-1\ndef test_ac1_payment():\n    assert True\n")
    ev = client.get(f"/api/jira/issues/{t['id']}/evidence").json()
    assert ev["commits"][0]["commit"] == "abc1234" and ev["last_verification"]["status"] == "PASSED" and ev["dod"][0]["ok"] is True
    assert ev["steps"][0]["order"] == 11 and ev["last_step"]["role"] == "BACKEND_DEV"
    assert ev["ac_coverage"]["total"] == 2 and ev["ac_coverage"]["covered"] == 1 and ev["ac_coverage"]["basis"] == "mentions"
    assert {k: ev["ac_coverage"]["items"][0][k] for k in ("ac", "evidence")} == {"ac": "AC-1", "evidence": ["tests/test_payment.py"]} and ev["ac_coverage"]["items"][1]["evidence"] == []
    assert client.get("/api/jira/issues/JIRA-999/timeline").status_code == 404
    # yönetici panoda taşıdıysa "neden" alan geçmişinden gelir
    u = await _task(hub, "B")
    client.post(f"/api/jira/issues/{u['id']}/move", json={"status": "IN_PROGRESS"})
    why = client.get(f"/api/jira/issues/{u['id']}/timeline").json()["why"]
    assert why.startswith("IN_PROGRESS: MANUAL_STATUS") or why.startswith("IN_PROGRESS: yönetici")


# ---------------------------------------------------------------------------
# Sprint panosu
# ---------------------------------------------------------------------------
async def test_sprint_board_reports_commitment_burndown_velocity_wip_and_goal_edit(client, hub):
    await hub.update_settings({"sprint": {"enabled": True, "wip_limit": 1}})
    a = await _task(hub, "A")
    b = await _task(hub, "B")
    c = await _task(hub, "C")
    closed = SP.new_sprint(hub, 1, "Eski hedef")
    closed["committed_issue_ids"] = [c["id"]]
    closed["completed_issue_ids"] = [c["id"]]
    closed["metrics"] = {"committed": 1, "completed": 1, "first_pass_rate": 1.0, "fix_rounds": 0}
    SP.set_sprint_status(hub, closed, "CLOSED", closed_at="2026-10-10T10:00:00+00:00")
    sp = SP.new_sprint(hub, 2, "Ödeme akışı")
    sp["committed_issue_ids"] = [a["id"], b["id"]]
    sp["proposed_issue_ids"] = [a["id"], b["id"]]
    for i in (a["id"], b["id"]):
        hub.jira_issues[i]["sprint"] = 2
    await hub.update_jira_issue(a["id"], {"status": "DONE", "agent_id": "PM", "audit_action": "APPROVED"})
    board = client.get("/api/sprints/board").json()
    assert board["enabled"] is True and board["settings"]["wip_limit"] == 1 and board["capacity"] >= 1
    cur = board["current"]
    assert cur["sprint_number"] == 2 and cur["status"] == "PLANNING" and cur["committed"] == 2 and cur["done"] == 1 and cur["goal"] == "Ödeme akışı"
    assert [p["remaining"] for p in cur["burndown"]] == [2, 1, 1] and cur["can"]["edit_goal"] is True and cur["can"]["cancel"] is True
    assert [i["id"] for i in cur["items"]] == [a["id"], b["id"]] and cur["proposed"][0]["id"] == a["id"]
    assert board["velocity"] == [{"sprint": 1, "committed": 1, "done": 1}] and board["sprints"][0]["status"] == "CLOSED"
    assert board["pending_commit"] is None and board["wip"] == {"limit": 1, "count": 0, "over": False, "items": []}
    # hedef düzenleme yalnızca PLANNING
    assert client.patch("/api/sprints/2", json={"goal": "Ödeme ve iade"}).status_code == 200 and SP.get_sprint(hub, 2)["goal"] == "Ödeme ve iade"
    assert client.patch("/api/sprints/2", json={"goal": " "}).status_code == 400 and client.patch("/api/sprints/9", json={"goal": "x"}).status_code == 404
    SP.set_sprint_status(hub, sp, "IN_PROGRESS", started_at="2026-10-12T09:00:00+00:00")
    assert client.patch("/api/sprints/2", json={"goal": "geç"}).status_code == 409
    # WIP uyarısı: limit 1, iki iş IN_PROGRESS
    client.post(f"/api/jira/issues/{b['id']}/move", json={"status": "IN_PROGRESS"})
    client.post(f"/api/jira/issues/{c['id']}/move", json={"status": "IN_PROGRESS"})
    board = client.get("/api/sprints/board").json()
    assert board["wip"]["count"] == 2 and board["wip"]["over"] is True and board["current"]["can"]["edit_goal"] is False
    # bekleyen taahhüt önerisi ve son tarih
    hub.pending_step_approval = {"kind": "sprint_commit", "issue_id": "SPRINT-2", "proposed": [{"issue_id": b["id"], "title": "B"}], "summary": "s", "timestamp": "t"}
    sp["commit_deadline"] = "2026-10-12T12:00:00+00:00"
    board = client.get("/api/sprints/board").json()
    assert board["pending_commit"]["sprint"] == 2 and board["pending_commit"]["proposed"][0]["issue_id"] == b["id"]
    assert board["pending_commit"]["deadline"] == "2026-10-12T12:00:00+00:00" and board["current"]["can"]["commit"] is True
    hub.pending_step_approval = None
    # engelli sprint
    SP.set_sprint_status(hub, sp, "BLOCKED", blocked={"reason": "BLOCKING_QUESTION", "since": "t", "previous_status": "IN_PROGRESS"})
    board = client.get("/api/sprints/board").json()
    assert board["current"]["can"]["unblock"] is True and board["current"]["blocked"]["reason"] == "BLOCKING_QUESTION"


async def test_yanlis_sorumlu_degisikligi_denetim_kaydindan_geri_alinir_dondurulmus_maddede_de(hub, tmp_project):
    from server import jira_plus as JP
    await hub.update_jira_issue("JIRA-61", {"order": 61, "title": "İş", "kind": "task", "issue_type": "TASK", "status": "DONE", "assignee": "BACKEND_DEV"})
    await hub.update_jira_issue("JIRA-61", {"assignee": "FRONTEND_DEV", "audit_action": "FIELD_CHANGED", "audit_notes": "assignee: 'BACKEND_DEV' → 'FRONTEND_DEV'"})
    out = await JP.correct_assignee(hub, "JIRA-61")
    assert out["assignee"] == "BACKEND_DEV" and hub.jira_issues["JIRA-61"]["audit_trail"][-1]["action"] == "ASSIGNEE_CORRECTED"
    with pytest.raises(ValueError):
        await JP.correct_assignee(hub, "JIRA-61")                       # son kayıt artık düzeltilmiş: tekrar geri alınmaz
