"""Hiyerarşi: bağsız iş en uygun hikâye/epiğe bağlanır; eşleşme yoksa uydurma bağ kurulmaz; eski işe yalnızca açık eylemle dokunulur."""
from server import hierarchy as H


async def _base(hub):
    await hub.update_jira_issue("JIRA-1", {"order": 1, "title": "Kimlik ve doğrulama", "issue_type": "EPIC", "kind": "epic", "status": "IN_PROGRESS"})
    await hub.update_jira_issue("JIRA-2", {"order": 2, "title": "Kayıt ve OTP girişi", "issue_type": "STORY", "kind": "story", "status": "BACKLOG", "parent_id": "JIRA-1", "ac_refs": ["AC-1", "AC-2"], "origin": "PM"})


async def test_ac_refs_gorevi_hikayeye_uat_hikayesini_epige_baglar(hub, tmp_project):
    await _base(hub)
    await hub.update_jira_issue("JIRA-3", {"order": 3, "title": "OTP sayacı", "issue_type": "TASK", "kind": "task", "status": "BACKLOG", "ac_refs": ["AC-2"]})
    await hub.update_jira_issue("JIRA-4", {"order": 4, "title": "AC-1 için test yaz", "issue_type": "STORY", "kind": "story", "status": "BACKLOG", "ac_refs": ["AC-1"], "origin": "UAT"})
    plan = await H.link_orphans(hub, apply=True)
    assert hub.jira_issues["JIRA-3"]["parent_id"] == "JIRA-2"                       # görev → AC'yi taşıyan hikâye
    assert hub.jira_issues["JIRA-4"]["parent_id"] == "JIRA-1"                       # UAT hikâyesi → o hikâyenin epiği
    assert plan["linked"] == 2 and hub.jira_issues["JIRA-3"]["audit_trail"][-1]["action"] == "PARENT_LINKED"


async def test_eslesme_yoksa_sistem_epigine_ya_da_bagsiz_kalir(hub, tmp_project):
    await _base(hub)
    await hub.update_jira_issue("JIRA-5", {"order": 5, "title": "[QA] BUG-QA-01: kuyruk dolu", "issue_type": "BUG", "kind": "task", "status": "BACKLOG", "origin": "QA", "work_type": "BUG"})
    await hub.update_jira_issue("JIRA-6", {"order": 6, "title": "Docker katmanı", "issue_type": "TASK", "kind": "task", "status": "BACKLOG", "origin": "DECISION", "work_type": "DEVOPS"})
    await hub.update_jira_issue("JIRA-7", {"order": 7, "title": "Tamamen alakasız yeni özellik xyzzy", "issue_type": "TASK", "kind": "task", "status": "BACKLOG", "work_type": "FEATURE", "origin": "ARCHITECT"})
    out = await H.link_orphans(hub, apply=True)
    q = hub.jira_issues["JIRA-5"]["parent_id"]; p = hub.jira_issues["JIRA-6"]["parent_id"]
    assert hub.jira_issues[q]["title"] == H.SYSTEM_EPICS["QUALITY"][0] and hub.jira_issues[p]["title"] == H.SYSTEM_EPICS["PLATFORM"][0] and q != p
    assert not hub.jira_issues["JIRA-7"].get("parent_id") and any(r["id"] == "JIRA-7" and r["parent_id"] is None for r in out["plan"])          # uydurma bağ yok


async def test_kuru_plan_degistirmez_ve_yeni_isler_kesimden_sonra_kendiliginden_baglanir(hub, tmp_project):
    await _base(hub)
    await hub.update_jira_issue("JIRA-3", {"order": 3, "title": "Eski görev", "issue_type": "TASK", "kind": "task", "status": "BACKLOG", "ac_refs": ["AC-2"], "created_at": "2020-01-01T00:00:00+00:00"})
    dry = await H.link_orphans(hub, apply=False)
    assert dry["applied"] is False and not hub.jira_issues["JIRA-3"].get("parent_id")           # kuru plan dokunmaz
    H.cutoff(hub)                                                                                 # kesim: şimdi
    assert await H.link_recent_orphans(hub) == 0 and not hub.jira_issues["JIRA-3"].get("parent_id")      # eski iş otomatik bağlanmaz
    await hub.update_jira_issue("JIRA-8", {"order": 8, "title": "Yeni OTP işi", "issue_type": "TASK", "kind": "task", "status": "BACKLOG", "ac_refs": ["AC-1"], "created_at": "2999-01-01T00:00:00+00:00"})
    assert await H.link_recent_orphans(hub) == 1 and hub.jira_issues["JIRA-8"]["parent_id"] == "JIRA-2"
    assert await H.link_recent_orphans(hub) == 0                                                  # bir kez denenir
