"""F4 — Toplantılar, SCRUM_MASTER, soru kuyruğu, ADR ve devir notları."""

import json
import os
import time

import pytest

from server import adr as ADR
from server import meetings as M
from server import sprint as SP
from server import sprint_flow as SPF
from server.llm.parsing import StepOutputError
from server.runs import PipelineRun, StepRecord

NOTES = ("Kullanıcılar sisteme kayıt olup giriş yapabilmeli. Yöneticiler kayıtları listeleyip filtreleyebilmeli. "
         "Her işlem için denetim kaydı tutulmalı.")
AGENTS = ["SCRUM_MASTER", "PM", "ARCHITECT", "BACKEND_DEV", "FRONTEND_DEV", "QA", "DEVOPS", "PO"]


def _wait(client, rid, pred, timeout=150.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        run = client.get(f"/api/runs/{rid}").json()["run"]
        if pred(run):
            return run
        time.sleep(0.2)
    run = client.get(f"/api/runs/{rid}").json()["run"]
    raise AssertionError(f"timeout status={run['status']} steps={[(s['order'], s['kind'], s['status']) for s in run['steps']]}")


def _setup(client, **sprint):
    client.post("/api/settings/sprint", json={"enabled": True, "commit_approval": "auto", "auto_chain": True, "max_tasks": 3, **sprint})
    client.post("/api/settings/engine", json={"execution_engine": "template", "approval_mode": "auto", "pacing": "instant",
                                              "auto_verify": False, "auto_commit": False})


def _upload(client, notes=NOTES):
    return client.post("/api/specs/upload", data={"title": "Notlar", "client_name": "Acme", "meeting_notes": notes}).json()


def _q(**kw):
    base = {"category": "DESIGN", "raised_by": "PM", "text": "Oturum yenileme nasıl olsun?", "options": [{"key": "A", "label": "Sessiz yenileme"}, {"key": "B", "label": "Yeniden giriş"}],
            "recommended": "A", "rationale": "Kesinti olmasın.", "adr": {"title": "Oturum yenileme politikası", "context": "Notlarda açık değil.",
                                                                          "consequences": {"positive": ["Kesinti yok"], "negative": ["Belirteç saklama"]}, "reversible": True}}
    return {**base, **kw}


def _payload(mtype="planning", **kw):
    base = {"meeting": {"type": mtype, "sprint": 1, "summary": "Tamam."},
            "discussion": [{"from": "ARCHITECT", "to": "BACKEND_DEV", "topic": "Kırılım", "message": "Görev ikiye bölünmeli."}],
            "decisions": [{"text": "Kapsam daraltıldı."}], "questions": [], "commitment": {"goal": "Hedef", "items": [], "out_of_scope": []}}
    if mtype == "review-retro":
        base.pop("commitment")
        base["retro"] = {"went_well": ["iyi"], "problems": [], "action_items": []}
    return {**base, **kw}


# ---------------------------------------------------------------------------
# Soru protokolü ve zarf doğrulaması (§3.3, §10.5)
# ---------------------------------------------------------------------------
def test_question_without_recommended_answer_or_rationale_is_rejected():
    ok = M.normalize_payload(_payload(questions=[_q()]), "planning", AGENTS)
    assert ok["questions"][0]["category"] == "DESIGN"
    for bad, needle in ((_q(recommended=""), "önerilen cevap"), (_q(recommended="Z"), "önerilen cevap"), (_q(rationale=""), "gerekçe"),
                        (_q(category="URGENT"), "kategori"), (_q(options=[{"key": "A", "label": "tek"}]), "iki seçenek")):
        with pytest.raises(StepOutputError) as e:
            M.normalize_payload(_payload(questions=[bad]), "planning", AGENTS)
        assert needle in " ".join(e.value.errors)


def test_blocking_is_derived_by_server_and_empty_or_foreign_turns_rejected():
    out = M.normalize_payload(_payload(questions=[_q(category="TECHNOLOGY", blocking=False)]), "planning", AGENTS)
    assert "blocking" not in out["questions"][0] and out["questions"][0]["category"] in M.BLOCKING_CATEGORIES
    with pytest.raises(StepOutputError):
        M.normalize_payload(_payload(discussion=[]), "planning", AGENTS)
    with pytest.raises(StepOutputError):
        M.normalize_payload(_payload(discussion=[{"from": "NOBODY", "message": "x"}]), "planning", AGENTS)
    with pytest.raises(StepOutputError):
        M.normalize_payload(_payload(commitment=None), "kickoff", AGENTS)
    bad_retro = _payload("review-retro")
    bad_retro["retro"]["action_items"] = [{"type": "MAGIC", "target": "x"}]
    with pytest.raises(StepOutputError):
        M.normalize_payload(bad_retro, "review-retro", AGENTS)


def test_deadline_rules_follow_category_and_timeout_key(hub):
    now = "2026-10-11T10:00:00+00:00"
    assert M.deadline_for(hub, "TECHNOLOGY", now) is None and M.deadline_for(hub, "EXTERNAL_ACTION", now) is None   # teknoloji: süre yok
    assert M.deadline_for(hub, "DESIGN", now) is None                                                              # varsayılan (L1): yöneticiyi bekler
    hub.settings["autonomy"] = {"question_timeout_s": 1800}
    assert M.deadline_for(hub, "DESIGN", now) == "2026-10-11T10:30:00+00:00"
    hub.settings["autonomy"] = {"question_timeout_s": 0}
    assert M.deadline_for(hub, "DESIGN", now) == now and M.deadline_for(hub, "TECHNOLOGY", now) is None
    san = M.sanitize_autonomy({"level": "L9", "question_timeout_s": -5})
    assert san["question_timeout_s"] == 0 and "level" not in san                                                   # seviye saklanmaz (§3.1)


def test_adr_rules(tmp_path):
    d = str(tmp_path)
    a = ADR.write_adr(d, "FS-docs", title="Oturum yenileme politikası", status="VARSAYIM", context="c", options=["A", "B"], chosen="A", rationale="r",
                      sprint=2, decision_ref="DEC-7", question_ref="Q-5", decider="PM önerisi")
    b = ADR.write_adr(d, "FS-docs", title="İkinci karar", status="KABUL EDİLDİ", context="c")
    assert (a["number"], b["number"]) == ("0001", "0002") and a["file"].endswith("0001-oturum-yenileme-politikasi.md")
    with pytest.raises(ValueError):
        ADR.write_adr(d, "FS-docs", title="Teknoloji", status="VARSAYIM", context="c", technology=True)   # teknoloji ADR'si VARSAYIM olamaz
    assert ADR.set_status(d, a["file"], "YERİNİ ALDI", "0002") and [x["status"] for x in ADR.list_adrs(d, "FS-docs")] == ["YERİNİ ALDI", "KABUL EDİLDİ"]
    text = open(os.path.join(d, a["file"]), encoding="utf-8").read()
    assert "## Bağlam" in text and "## Seçenekler" in text and "1. A (seçilen)" in text and "**Soru:** Q-5" in text


# ---------------------------------------------------------------------------
# Kuru koşu: üç tutanak, ADR, DEFAULTED soru, devir notları
# ---------------------------------------------------------------------------
def test_dry_run_produces_minutes_adr_defaulted_question_and_handoffs(client, hub, tmp_project):
    _setup(client)
    client.post("/api/settings/autonomy", json={"question_timeout_s": 0})
    rid = _upload(client)["intake"]["run_id"]
    done = _wait(client, rid, lambda r: r["is_terminal"])
    assert done["status"] == "COMPLETED"
    meetings_dir = os.path.join(tmp_project, "FS-docs", "meetings")
    names = sorted(os.listdir(meetings_dir))
    assert len(names) >= 3 and any("kickoff" in n for n in names) and any("planning" in n for n in names) and any("review-retro" in n for n in names)
    kick = open(os.path.join(meetings_dir, next(n for n in names if "kickoff" in n)), encoding="utf-8").read()
    for part in ("# Toplantı tutanağı: Sprint 1 kickoff", "**Kimlik:** M-", "SCRUM_MASTER (moderatör)", "## 1. Girdiler", "## 2. Tartışma", "## 3. Kararlar",
                 "## 4. Sorular", "## 5. Sprint 1 taahhüdü", "**Hedef:**", "## 6. Sonraki adım"):
        assert part in kick, part
    retro = open(os.path.join(meetings_dir, next(n for n in names if "sprint-1-review-retro" in n)), encoding="utf-8").read()
    assert "Taahhüt 3 · tamamlanan 3" in retro and "### Retro aksiyonları" in retro
    # soru kuyruğu: süre doldu → önerilen cevapla DEFAULTED, VARSAYIM ADR'si
    qs = M.store(hub)["questions"]
    assert qs and any(q["status"] == "DEFAULTED" for q in qs)
    dq = next(q for q in qs if q["status"] == "DEFAULTED")
    assert dq["answer"] == dq["recommended"] and dq["answered_by"] in ("TIMEOUT", "SERVER") and dq["decision_ref"].startswith("DEC-") and dq["blocking"] is False
    adr_files = os.listdir(os.path.join(tmp_project, "FS-docs", "adr"))
    assert adr_files and any(f.startswith("0001-") for f in adr_files)
    adr_text = open(os.path.join(tmp_project, dq["adr_ref"]), encoding="utf-8").read()
    assert "- **Durum:** VARSAYIM" in adr_text and dq["id"] in adr_text
    mt = open(os.path.join(tmp_project, next(m for m in SP.ensure_state(hub)["meetings"] if dq["id"] in m["question_ids"])["file"]), encoding="utf-8").read()
    assert "**VARSAYIM**: süre doldu" in mt and "Süre doldu, varsayılan" in mt
    # sprint kaydı toplantılara bağlanır; tutanağın kimliği benzersiz
    sp1 = SP.get_sprint(hub, 1)
    assert sp1["meetings"]["planning"] and sp1["meetings"]["review_retro"] and os.path.isfile(os.path.join(tmp_project, sp1["meetings"]["review_retro"]))
    ids = [m["id"] for m in SP.ensure_state(hub)["meetings"]]
    assert len(ids) == len(set(ids)) and all(i.startswith("M-") for i in ids)
    decs = [d["id"] for d in SP.ensure_state(hub)["decisions"]]
    assert len(decs) == len(set(decs))
    # toplantı turları müzakere odasında ve olay günlüğünde görünür; mimar bağlamındaki "son oturum" ezilmez
    assert any(e["action"] == "DELIBERATION_SPEECH" for e in hub.events) and hub.deliberation_engine.get_latest_session() is None
    assert any(s["session_id"] == ids[0] for s in hub.deliberation_engine.history)
    # devir notları olay günlüğünde
    handoffs = [e for e in hub.events if e["action"] == "HANDOFF"]
    assert handoffs and all(e["payload"]["message"] for e in handoffs)


def test_default_level_l1_keeps_design_question_open_without_deadline(client, hub, tmp_project):
    _setup(client, max_tasks=50)
    rid = _upload(client)["intake"]["run_id"]
    _wait(client, rid, lambda r: r["is_terminal"])
    qs = M.store(hub)["questions"]
    assert qs and all(q["status"] == "OPEN" and q["deadline"] is None for q in qs)   # L1: süresiz; taahhüt önerilen cevapla kurulur
    assert SP.get_sprint(hub, 1)["status"] == "CLOSED"


# ---------------------------------------------------------------------------
# Engelleyici soru: sprint BLOCKED, süreyle geçilmez, yönetici cevaplar
# ---------------------------------------------------------------------------
async def _manual_meeting_run(hub, tmp_project, mtype="planning"):
    from server import pipeline as P
    from server.steps.tasks import normalize_backlog
    hub.settings["sprint"] = {"enabled": True, "commit_approval": "auto", "max_tasks": 5}
    hub.settings["approval_mode"] = "auto"
    dummy = PipelineRun(project_id=hub.active_project_id)
    await P._create_task_issues(hub, dummy, normalize_backlog([{"id": "a", "title": "Giriş ucu", "role": "BACKEND_DEV", "work_type": "FEATURE"}]), parent_id="JIRA-2", origin="ARCHITECT")
    run = PipelineRun(project_id=hub.active_project_id, project_dir=tmp_project, engine="mcp_client", step_by_step=False, mode="sprint",
                      steps=[SPF.new_meeting_record(1, mtype), SPF.new_plan_record(1)])
    hub.register_run(run)
    run.status = "QUEUED"
    hub.active_run_id = run.run_id
    return run


async def test_blocking_technology_question_blocks_sprint_until_manager_answers(client, hub, tmp_project):
    run = await _manual_meeting_run(hub, tmp_project)
    hub.step_by_step_mode = False
    rid = run.run_id
    nxt = client.post(f"/api/runs/{rid}/next-step", json={"client": {"name": "t"}}).json()
    assert nxt["status"] == "STEP" and nxt["kind"] == "meeting" and nxt["agent_id"] == "SCRUM_MASTER" and "Taahhüt adayları" in nxt["user_context"]
    tech = _q(category="TECHNOLOGY", raised_by="DEVOPS", text="Sırlar nasıl yönetilsin?", options=[{"key": "A", "label": "Ortam değişkeni"}, {"key": "B", "label": "Vault"}],
              adr={"title": "Sır yönetimi", "context": "c", "consequences": {"positive": ["sade"], "negative": ["elle döndürme"]}, "reversible": True})
    cand = [i["id"] for i in SP.candidates(hub)]
    env = {"from_agent": "SCRUM_MASTER", "to_agent": "PM", "intent": "MEETING_CLOSED", "status": "SUCCESS",
           "payload": {**_payload("planning", questions=[tech], commitment={"goal": "Giriş", "items": cand, "out_of_scope": []}), "summary": "ok"}, "metadata": {"tokens_used": 5}}
    res = client.post(f"/api/runs/{rid}/steps/{nxt['order']}/result", json={"result_json": json.dumps(env)}).json()
    assert res["status"] == "NEXT", res
    q = M.store(hub)["questions"][0]
    assert q["category"] == "TECHNOLOGY" and q["blocking"] is True and q["deadline"] is None and q["status"] == "OPEN"
    # plan adımı: BLOCKING_QUESTION → sprint BLOCKED, kapı açık
    nxt = client.post(f"/api/runs/{rid}/next-step", json={"client": {"name": "t"}}).json()
    assert nxt["status"] == "WAITING_APPROVAL"
    sp = SP.get_sprint(hub, 1)
    assert sp["status"] == "BLOCKED" and sp["blocked"]["reason"] == "BLOCKING_QUESTION" and q["id"] in sp["blocked"]["detail"]
    assert (hub.pending_step_approval or {}).get("kind") == "questions"
    # süre/zamanlayıcı teknoloji sorusunu geçemez
    hub.settings["autonomy"] = {"question_timeout_s": 0}
    assert await M.expire_questions(hub) == [] and q["status"] == "OPEN"
    # cevapsız onay kapıyı kapatmaz
    client.post("/api/pipeline/approve-step", json={"decision": "PROCEED"})
    time.sleep(0.5)
    nxt = client.post(f"/api/runs/{rid}/next-step", json={"client": {"name": "t"}}).json()
    assert nxt["status"] == "WAITING_APPROVAL" and SP.get_sprint(hub, 1)["status"] == "BLOCKED"
    # yönetici cevaplar → ADR KABUL EDİLDİ (VARSAYIM değil), sprint çözülür ve taahhüt edilir
    bad = client.post(f"/api/questions/{q['id']}/answer", json={"answer": "Z"})
    assert bad.status_code == 400 and client.post("/api/questions/Q-99/answer", json={"answer": "A"}).status_code == 404
    ok = client.post(f"/api/questions/{q['id']}/answer", json={"answer": "A"}).json()
    assert ok["question"]["status"] == "ANSWERED" and ok["question"]["answered_by"] == "MANAGER"
    adr_text = open(os.path.join(tmp_project, q["adr_ref"]), encoding="utf-8").read()
    assert "- **Durum:** KABUL EDİLDİ" in adr_text and "VARSAYIM" not in adr_text.split("## Bağlam")[0]
    time.sleep(0.5)
    nxt = client.post(f"/api/runs/{rid}/next-step", json={"client": {"name": "t"}}).json()
    assert nxt["status"] in ("STEP", "RUN_COMPLETE"), nxt
    sp = SP.get_sprint(hub, 1)
    assert sp["blocked"] is None and sp["status"] == "IN_PROGRESS" and sp["committed_issue_ids"] == cand
    assert open(os.path.join(tmp_project, sp["commitment_ref"]), encoding="utf-8").read().count("meeting_ref") == 1


async def test_meeting_commitment_is_validated_against_eligibility_and_capacity(client, hub, tmp_project):
    run = await _manual_meeting_run(hub, tmp_project)
    hub.settings["sprint"]["max_tasks"] = 1
    hub.step_by_step_mode = False
    rid = run.run_id
    nxt = client.post(f"/api/runs/{rid}/next-step", json={"client": {"name": "t"}}).json()
    cand = [i["id"] for i in SP.candidates(hub)]
    env = {"from_agent": "SCRUM_MASTER", "to_agent": "PM", "intent": "MEETING_CLOSED", "status": "SUCCESS",
           "payload": {**_payload("planning", commitment={"goal": "Benim hedefim", "items": [cand[0], "JIRA-999", cand[0]], "out_of_scope": []}), "summary": "ok"}}
    client.post(f"/api/runs/{rid}/steps/{nxt['order']}/result", json={"result_json": json.dumps(env)})
    client.post(f"/api/runs/{rid}/next-step", json={"client": {"name": "t"}})
    sp = SP.get_sprint(hub, 1)
    assert sp["goal"] == "Benim hedefim" and sp["committed_issue_ids"] == [cand[0]]          # toplantının hedefi korunur; uygunsuz/tekrar iş taahhüde girmez
    assert any(o["issue_id"] == "JIRA-999" for o in sp["out_of_scope"])


# ---------------------------------------------------------------------------
# Varsayılan kararın yönetici tarafından onaylanması / değiştirilmesi (§3.3 madde 6)
# ---------------------------------------------------------------------------
def test_manager_can_confirm_or_override_a_defaulted_decision(client, hub, tmp_project):
    _setup(client, max_tasks=50)
    client.post("/api/settings/autonomy", json={"question_timeout_s": 0})
    rid = _upload(client)["intake"]["run_id"]
    _wait(client, rid, lambda r: r["is_terminal"])
    defaulted = [q for q in M.store(hub)["questions"] if q["status"] == "DEFAULTED"]
    assert defaulted
    q = defaulted[0]
    old_adr = q["adr_ref"]
    # farklı cevap → OVERRIDDEN: eski ADR "yerini aldı", yeni ADR KABUL EDİLDİ, değişiklik görevi açılır
    jira_before = len(hub.jira_issues)
    res = client.post(f"/api/questions/{q['id']}/answer", json={"answer": "B"}).json()
    assert res["question"]["status"] == "OVERRIDDEN" and res["question"]["answer"] == "B"
    assert "YERİNİ ALDI" in open(os.path.join(tmp_project, old_adr), encoding="utf-8").read().split("## Bağlam")[0]
    assert "KABUL EDİLDİ" in open(os.path.join(tmp_project, res["question"]["adr_ref"]), encoding="utf-8").read().split("## Bağlam")[0]
    assert len(hub.jira_issues) == jira_before + 1
    change = max(hub.jira_issues.values(), key=lambda i: int(i["order"]))
    assert change["origin"] == "MANAGER" and change["work_type"] == "REFACTOR" and change["status"] == "BACKLOG" and q["id"] in change["title"]
    assert client.post(f"/api/questions/{q['id']}/answer", json={"answer": "A"}).status_code == 400   # sonuçlanmış soru tekrar cevaplanmaz
    # aynı cevap VARSAYIM'ı onaylar
    if len(defaulted) > 1:
        q2 = defaulted[1]
        client.post(f"/api/questions/{q2['id']}/answer", json={"answer": q2["answer"]})
        assert q2["status"] == "ANSWERED"
        assert "KABUL EDİLDİ" in open(os.path.join(tmp_project, q2["adr_ref"]), encoding="utf-8").read().split("## Bağlam")[0]
    listing = client.get("/api/questions").json()
    assert {x["id"] for x in listing["questions"]} >= {q["id"]} and "adr_draft" not in listing["questions"][0]


async def test_question_ids_do_not_collide_with_technology_questions(hub, tmp_project):
    from server.tech_requirements import apply_approval
    await hub.update_settings({"tech_requirements": None})
    hub.uploaded_specs = [{"id": "SPEC-001", "client_name": "A", "title": "N", "meeting_notes": "Randevu uygulaması.", "files": []}]
    req = await hub.ensure_tech_requirements(tmp_project)
    assert [q["id"] for q in req["questions"]][:2] == ["Q-1", "Q-2"]
    assert M.next_question_id(hub) == f"Q-{len(req['questions']) + 1}"


# ---------------------------------------------------------------------------
# Devir notları (§10.8)
# ---------------------------------------------------------------------------
async def test_handoff_is_logged_and_given_to_the_recipient(client, hub, tmp_project):
    hub.step_by_step_mode = False
    run = client.post("/api/runs", json={"steps": [3, 4], "engine": "mcp_client", "client": {"name": "t"}}).json()["run"]
    rid = run["run_id"]
    client.post(f"/api/runs/{rid}/next-step", json={"client": {"name": "t"}})
    env = {"from_agent": "BACKEND_DEV", "to_agent": "FRONTEND_DEV", "intent": "BACKEND_API_EXPOSED", "status": "SUCCESS",
           "payload": {"files": [{"path": "src/main.py", "content": "app = 1\n"}]}, "summary": "JWT üretimi eklendi.",
           "handoff": [{"to": "FRONTEND_DEV", "message": "Giriş ucu /auth/login; 401 gelirse yenileme ucunu çağır."}], "metadata": {"tokens_used": 5}}
    res = client.post(f"/api/runs/{rid}/steps/3/result", json={"result_json": json.dumps(env)}).json()
    assert res["status"] in ("NEXT", "RUN_COMPLETE") and "JWT üretimi eklendi" in hub.runs[rid].steps[0].summary
    ev = [e for e in hub.events if e["action"] == "HANDOFF"]
    assert len(ev) == 1 and ev[0]["from_agent"] == "BACKEND_DEV" and ev[0]["to_agent"] == "FRONTEND_DEV" and "/auth/login" in ev[0]["payload"]["message"]
    nxt = client.post(f"/api/runs/{rid}/next-step", json={"client": {"name": "t"}}).json()
    assert nxt["order"] == 4 and "Önceki rollerden devir notları" in nxt["user_context"] and "/auth/login" in nxt["user_context"]


# ---------------------------------------------------------------------------
# Rol promptları: §6.3 "yapamaz" kuralları (tr ve en)
# ---------------------------------------------------------------------------
ROLE_RULES = {
    "pm.md": ("Notlarda olmayan gereksinim ekleyemez", "Cannot add requirements that are not in the notes"),
    "architect.md": ("Kabul kriterini değiştiremez", "Cannot change acceptance criteria"),
    "developer.md": ("Kayıtsız bağımlılık ekleyemez", "Cannot add unregistered dependencies"),
    "qa.md": ("yalnızca test kodu yazar", "writes test code only"),
    "e2e_tester.md": ("Kod yazmaz, senaryo yazmaz", "Writes no code, writes no scenarios"),
    "devops.md": ("Dağıtım yapamaz", "Cannot deploy"),
    "po.md": ("Kanıtı olmayan kriteri kabul edemez", "Cannot accept a criterion without evidence"),
    "documentor.md": ("Kabul edilmemiş ya da çalışmayan özelliği belgeleyemez", "Cannot document a feature that is not accepted"),
    "reporter.md": ("Metrik üretemez ya da yuvarlayamaz", "Cannot produce or round metrics"),
    "scm.md": ("geçmişi yeniden yazamaz", "rewrite history"),
    "scrum_master.md": ("Kapasiteyi aşan taahhüt veremez", "Cannot commit beyond capacity"),
}


@pytest.mark.parametrize("lang,idx", [("tr", 0), ("en", 1)])
def test_every_role_prompt_carries_its_cannot_rules_and_shared_rules(lang, idx):
    from server.fs_workspace import GLOBAL_PROMPTS_DIR, ROLE_TO_PROMPT_MAP
    marker = ("## Görev sınırları ve ortak kurallar (FS-SC otonomi §6)", "## Role boundaries and shared rules (FS-SC autonomy §6)")[idx]
    shared = ("Kendi işini kabul edemezsin", "You cannot accept your own work")[idx]
    for fname, phrases in ROLE_RULES.items():
        text = open(os.path.join(GLOBAL_PROMPTS_DIR, lang, fname), encoding="utf-8").read()
        assert marker in text and shared in text and phrases[idx] in text, (lang, fname)
    assert ROLE_TO_PROMPT_MAP["SCRUM_MASTER"] == "scrum_master.md" and ROLE_TO_PROMPT_MAP["E2E_TESTER"] == "e2e_tester.md"
    assert os.path.isfile(os.path.join(GLOBAL_PROMPTS_DIR, lang, "scrum_master.md"))


def test_scrum_master_agent_exists_and_meeting_endpoints(client, hub, tmp_project):
    assert "SCRUM_MASTER" in hub.agents
    _setup(client, max_tasks=50)
    rid = _upload(client)["intake"]["run_id"]
    _wait(client, rid, lambda r: r["is_terminal"])
    listing = client.get("/api/meetings").json()["meetings"]
    assert listing and {m["type"] for m in listing} >= {"kickoff", "review-retro"}
    detail = client.get(f"/api/meetings/{listing[0]['id']}").json()
    assert detail["meeting"]["id"] == listing[0]["id"] and "# Toplantı tutanağı" in detail["minutes_md"]
    assert client.get("/api/meetings/M-0-0").status_code == 404
    assert client.get("/api/adr").json()["adr"] == [] or all("number" in a for a in client.get("/api/adr").json()["adr"])
    auto = client.get("/api/settings/autonomy").json()["autonomy"]
    assert auto["question_timeout_s"] is None and auto["budget"]["max_sprints"] == M.DEFAULT_BUDGET["max_sprints"] and auto["budget"]["stall_steps"] == 6
