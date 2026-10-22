"""PO'nun UAT belgesi sunucu kanıt denetimiyle çelişmemeli: ret varsa "Karar: APPROVED" düzeltilir, sunucu bölümü belgeye yazılır (idempotent)."""
import os

from server import quality as Q
from server import sprint as SP
from server.paths import hub_docs_path
from server.runs import PipelineRun, StepRecord
from server.steps.base import StepEvent, StepResult

PO_DOC = """# Sprint 1 UAT Kabul Tablosu

Karar: APPROVED (puan 85/100). Kapsam: sekiz backend görevi.

## Kriter kararları
| Kriter | Karar | Kanıt |
|---|---|---|
| AC-1 18 yaş altı reddi | Kabul | auth/register.spec.ts |
| AC-2 reddedilen cihaz | Kabul | auth/register.spec.ts |
"""


async def _setup(hub, tmp_project):
    await hub.update_settings({"autonomy": {"strict_dod": True}})
    st = SP.ensure_state(hub)
    for n, (ac, iid) in enumerate((("AC-1", "JIRA-31"), ("AC-2", "JIRA-32")), 31):
        await hub.update_jira_issue(iid, {"order": n, "title": f"İş {ac}", "kind": "task", "status": "DONE", "assignee": "BACKEND_DEV", "ac_refs": [ac], "closed_in_sprint": 1})
        st["acs"][ac] = {"text": ac, "story": None}
    sp = SP.new_sprint(hub, 1, "Hedef")
    sp["committed_issue_ids"] = ["JIRA-31", "JIRA-32"]
    os.makedirs(os.path.join(tmp_project, "tests"), exist_ok=True)
    open(os.path.join(tmp_project, "tests", "test_one.py"), "w").write("# AC-1\ndef test_one():\n    pass\n")      # yalnızca AC-1'in kanıtı var
    rel = hub_docs_path(hub, "uat/acceptance_criteria.md", tmp_project)
    path = os.path.join(tmp_project, *rel.split("/"))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, "w", encoding="utf-8").write(PO_DOC)
    return path


async def _decide(hub, tmp_project):
    run = PipelineRun(project_id=hub.active_project_id)
    rec = StepRecord(order=9, issue_id="JIRA-9", role="PO", kind="phase", sprint=1)
    result = StepResult(summary="PO onayı", action="UAT_APPROVED", next_agent_id="DOCUMENTOR", events=[StepEvent(from_agent="PO", to_agent="DOCUMENTOR", action="UAT_APPROVED")])

    async def create(tasks):
        pass
    payload = {"criteria": [{"id": "AC-1", "decision": "ACCEPTED", "reason": "test"}, {"id": "AC-2", "decision": "ACCEPTED", "reason": "güveniyorum"}]}
    return await Q.apply_po_criteria(hub, run, rec, payload, result, tmp_project, create)


async def test_ret_varsa_belge_approved_demez_ve_sunucu_bolumu_yazilir(hub, tmp_project):
    path = await _setup(hub, tmp_project)
    out = await _decide(hub, tmp_project)
    assert [r["ac"] for r in out["rejected"]] == ["AC-2"]
    text = open(path, encoding="utf-8").read()
    assert "Karar: REJECTED (sunucu kanıt denetimi: 1 kriter" in text and "Karar: APPROVED" not in text
    assert "Sunucu kanıt denetimi — Sprint 1" in text and "**Sonuç: RET** — 1/2" in text
    assert "| AC-1 | Kabul | " in text and "| AC-2 | RET | " in text and "kanıtsız" in text
    assert text.index("Sunucu kanıt denetimi") < text.index("Kriter kararları")            # sunucu bölümü PO anlatımından önce


async def test_belge_guncellemesi_tekrarsiz(hub, tmp_project):
    path = await _setup(hub, tmp_project)
    await _decide(hub, tmp_project)
    await _decide(hub, tmp_project)
    assert open(path, encoding="utf-8").read().count(Q.UAT_BEGIN) == 1


async def test_belge_yoksa_dokunmaz(hub, tmp_project):
    path = await _setup(hub, tmp_project)
    os.remove(path)
    await _decide(hub, tmp_project)
    assert not os.path.exists(path)
