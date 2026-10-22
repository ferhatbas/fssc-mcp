"""Teknoloji kararları kapısı: tasarım adımından önce kullanıcıya sorulur, cevaplar bağlama enjekte edilir."""

import json

from server.decisions import DEFAULT_TECH_QUESTIONS, merge_questions, auto_answers, decisions_context, make_decisions


def test_merge_and_context():
    qs = merge_questions([{"id": "backend", "question": "PHP mi Node mu? (K-17)", "options": ["PHP 8 / Symfony", "Node.js / NestJS"], "recommended": "PHP 8 / Symfony", "why": "ekip uzmanlığı"},
                          {"id": "maps", "question": "Harita sağlayıcı", "options": ["Google Maps", "MapLibre"], "recommended": "MapLibre"}])
    ids = [q["id"] for q in qs]
    assert ids[:len(DEFAULT_TECH_QUESTIONS)] == [q["id"] for q in DEFAULT_TECH_QUESTIONS] and "maps" in ids
    backend = next(q for q in qs if q["id"] == "backend")
    assert backend["question"].startswith("PHP mi") and backend["recommended"] == "PHP 8 / Symfony" and backend["source"] == "spec"
    d = make_decisions(qs, {"backend": "PHP 8 / Symfony", "maps": "MapLibre", "bogus": "x"}, notes="Redis yok")
    assert d["answers"] == {"backend": "PHP 8 / Symfony", "maps": "MapLibre"}
    ctx = decisions_context(qs, d)
    assert "PHP 8 / Symfony" in ctx and "Redis yok" in ctx and "bunlara UY" in ctx
    assert auto_answers(qs)["backend"] == "PHP 8 / Symfony"


def test_decisions_gate_blocks_design_step_until_answered(client, hub):
    hub.step_by_step_mode = False  # onay modu değil, karar kapısı test ediliyor
    client.delete("/api/pipeline/decisions")
    run = client.post("/api/runs", json={"steps": [2], "engine": "mcp_client", "client": {"name": "curl", "version": "1"}}).json()["run"]
    rid = run["run_id"]
    nxt = client.post(f"/api/runs/{rid}/next-step", json={"client": {"name": "curl"}}).json()
    assert nxt["status"] == "WAITING_APPROVAL" and nxt["kind"] == "decisions"
    pend = client.get("/api/pipeline/decisions").json()
    assert pend["pending"] is True and len(pend["questions"]) >= len(DEFAULT_TECH_QUESTIONS)
    assert client.get("/api/pipeline/pending-step").json()["pending_step"]["kind"] == "decisions"
    # istemci bekler
    assert client.post(f"/api/runs/{rid}/approval", json={"timeout_s": 1}).json()["status"] == "STILL_WAITING"
    # F2: kısmi cevap kapıyı AÇIK tutar (tüm kalemler onaylanmadan geçilmez)
    partial = client.post("/api/pipeline/decisions", json={"answers": {"backend": "PHP 8 / Symfony"}, "notes": "Docker zorunlu"}).json()
    assert partial["status"] == "SAVED" and partial["approved"] is False
    assert client.post(f"/api/runs/{rid}/approval", json={"timeout_s": 1}).json()["status"] == "STILL_WAITING"
    # yönetici hepsini cevaplar → kapı çözülür, adım ilerlemez (adım 2 hâlâ sırada)
    full = {q["id"]: q["recommended"] for q in DEFAULT_TECH_QUESTIONS}
    full.update({"backend": "PHP 8 / Symfony", "database": "MySQL / MariaDB"})
    saved = client.post("/api/pipeline/decisions", json={"answers": full, "notes": "Docker zorunlu"}).json()
    assert saved["status"] == "SAVED" and saved["approved"] is True and saved["tech_decisions"]["source"] == "user"
    waited = client.post(f"/api/runs/{rid}/approval", json={"timeout_s": 5}).json()
    assert waited["status"] == "APPROVED"
    nxt = client.post(f"/api/runs/{rid}/next-step", json={"client": {"name": "curl"}}).json()
    assert nxt["status"] == "STEP" and nxt["order"] == 2
    assert "PHP 8 / Symfony" in nxt["user_context"] and "Docker zorunlu" in nxt["user_context"]
    assert "teknoloji kararlarına uygun dosya adları" in nxt["output_contract"]
    assert client.get("/api/pipeline/decisions").json()["pending"] is False
    client.post(f"/api/runs/{rid}/cancel", json={"reason": "cleanup"})


def test_auto_mode_no_longer_skips_the_technology_gate(client, hub):
    """A4: approval_mode=auto kapıyı önerilenlerle kapatıyordu; artık yönetici onayı olmadan geçilmez."""
    client.delete("/api/pipeline/decisions")
    client.post("/api/pipeline/approval-mode", json={"approval_mode": "auto"})
    run = client.post("/api/runs", json={"steps": [2], "engine": "mcp_client", "client": {"name": "curl", "version": "1"}}).json()["run"]
    nxt = client.post(f"/api/runs/{run['run_id']}/next-step", json={"client": {"name": "curl"}}).json()
    assert nxt["status"] == "WAITING_APPROVAL" and nxt["kind"] == "decisions"
    assert hub.tech_decisions() is None or hub.tech_decisions().get("source") != "auto"
    client.post(f"/api/runs/{run['run_id']}/cancel", json={"reason": "cleanup"})


def test_pm_step_adds_spec_questions_and_step1_needs_no_gate(client, hub):
    hub.step_by_step_mode = False
    run = client.post("/api/runs", json={"steps": [1], "engine": "mcp_client", "client": {"name": "curl", "version": "1"}}).json()["run"]
    nxt = client.post(f"/api/runs/{run['run_id']}/next-step", json={"client": {"name": "curl"}}).json()
    assert nxt["status"] == "STEP" and nxt["order"] == 1 and "decisions_needed" in nxt["output_contract"]
    env = {"from_agent": "PM", "to_agent": "ARCHITECT", "intent": "TASK_DISPATCH", "status": "SUCCESS",
           "payload": {"summary": "ok", "files": [{"path": "docs/PRD.md", "content": "# PRD"}],
                       "decisions_needed": [{"id": "payments", "question": "Ödeme sağlayıcı", "options": ["iyzico", "Stripe"], "recommended": "iyzico", "why": "TR"}]},
           "metadata": {"tokens_used": 10}}
    sub = client.post(f"/api/runs/{run['run_id']}/steps/1/result", json={"result_json": json.dumps(envelope := env)}).json()
    assert sub["status"] == "RUN_COMPLETE"
    qs = client.get("/api/pipeline/decisions").json()["questions"]
    assert any(q["id"] == "payments" and q["source"] == "spec" for q in qs)
    # sıfırlama
    assert client.delete("/api/pipeline/decisions").json()["status"] == "CLEARED"
