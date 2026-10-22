"""F2 — Teknoloji gereksinimleri: çıkarma, TECH_REQUIREMENTS.md, atlanamayan kapı, bağımlılık denetimi."""

import json
import os
import time

import pytest

from server import tech_requirements as TR
from server.decisions import DEFAULT_TECH_QUESTIONS

NOTES_MIXED = (
    "Müşteri toplantısı. API tarafı Python ile yazılsın, FastAPI olabilir. Veritabanı tercihen PostgreSQL. "
    "Teslim Docker ile yapılacak. Girişte hem LDAP ile giriş hem OAuth2 isteniyor. Otomatik test zorunlu, pytest ve Playwright."
)


def _spec(hub, notes):
    hub.uploaded_specs = [{"client_name": "Müşteri", "title": "Toplantı notları", "meeting_notes": notes, "files": []}]


async def _clear_gate_state(hub):
    await hub.update_settings({"tech_requirements": None, "tech_decisions": None})


def _wait_for(client, run_id, predicate, timeout=20.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        run = client.get(f"/api/runs/{run_id}").json()["run"]
        if predicate(run):
            return run
        time.sleep(0.1)
    last = client.get(f"/api/runs/{run_id}").json()["run"]
    raise AssertionError(f"timeout waiting for run {run_id}: status={last['status']} cancel={last.get('cancel_reason')} steps={[(x['order'], x['status'], x.get('error')) for x in last['steps']]}")


def _by_cat(req):
    return {it["category"]: it for it in req["items"]}


# ---------------------------------------------------------------------------
# Çıkarma (saf mantık)
# ---------------------------------------------------------------------------
def test_extraction_statuses_value_quote_and_missing():
    items = _by_cat({"items": TR.extract_requirements(DEFAULT_TECH_QUESTIONS, NOTES_MIXED, "Toplantı")})
    assert items["backend"]["extracted_status"] == TR.BELIRTILMIS and items["backend"]["value"] == "Python / FastAPI"
    assert "Python" in items["backend"]["quote"] and items["backend"]["source"] == "Toplantı"
    assert items["database"]["extracted_status"] == TR.BELIRTILMIS and items["database"]["value"] == "PostgreSQL"
    assert items["hosting"]["value"] == "Docker"
    assert items["testing"]["value"] == "pytest + Playwright"
    assert items["auth"]["extracted_status"] == TR.CELISKILI and items["auth"]["value"] is None
    assert "LDAP" in items["auth"]["quote"] and "OAuth2" in items["auth"]["quote"]
    # notlarda hiç geçmeyen kalem EKSİK: değer, kaynak ve alıntı UYDURULMAZ
    assert items["client"]["extracted_status"] == TR.EKSIK
    assert items["client"]["value"] is None and items["client"]["quote"] is None and items["client"]["source"] is None
    assert items["realtime"]["extracted_status"] == TR.EKSIK
    # EKSİK ve ÇELİŞKİLİ kalem için 2-3 alternatif, artı/eksi ve önerilen var (karar 16)
    for cat in ("client", "realtime", "auth"):
        assert 2 <= len(items[cat]["options"]) <= 3
        assert all(o["pros"] and o["cons"] for o in items[cat]["options"] if o["value"] in TR._NOTES)


def test_no_technology_text_makes_every_item_missing():
    items = TR.extract_requirements(DEFAULT_TECH_QUESTIONS, "Kullanıcılar randevu alabilmeli.", "Not")
    assert [it["extracted_status"] for it in items] == [TR.EKSIK] * len(DEFAULT_TECH_QUESTIONS)


def test_llm_hint_is_accepted_only_when_quote_is_in_the_notes():
    hints = [{"category": "client", "value": "Web", "quote": "tarayıcıdan kullanılacak"},
             {"category": "realtime", "value": "WebSocket", "quote": "bu cümle notlarda yok"}]
    items = _by_cat({"items": TR.extract_requirements(DEFAULT_TECH_QUESTIONS, "Sistem tarayıcıdan kullanılacak.", "Not", hints)})
    assert items["client"]["extracted_status"] == TR.BELIRTILMIS and items["client"]["value"] == "Web"
    assert items["realtime"]["extracted_status"] == TR.EKSIK


# ---------------------------------------------------------------------------
# Dosya üretimi
# ---------------------------------------------------------------------------
async def test_tech_requirements_md_is_generated_with_template_sections(hub, tmp_project):
    await _clear_gate_state(hub)
    _spec(hub, NOTES_MIXED)
    req = await hub.ensure_tech_requirements(tmp_project)
    path = os.path.join(tmp_project, "FS-docs", "TECH_REQUIREMENTS.md")
    assert os.path.isfile(path)
    md = open(path, encoding="utf-8").read()
    for part in ("# Teknoloji gereksinimleri:", "## 1. Teknolojiler", "| TR-1 |", "BELİRTİLMİŞ", "EKSİK → Q-", "ÇELİŞKİLİ → Q-",
                 "## 2. Onay bekleyenler", "## 3. Reddedilen ya da ertelenenler", "## 4. Kütüphaneler", "artı —", "eksi —"):
        assert part in md, part
    assert req["status"] == TR.ONAY_BEKLIYOR and not hub.tech_requirements_approved()


async def test_no_technology_in_notes_still_produces_file_and_asks_everything(hub, tmp_project):
    await _clear_gate_state(hub)
    _spec(hub, "Randevu uygulaması istiyoruz.")
    req = await hub.ensure_tech_requirements(tmp_project)
    assert os.path.isfile(os.path.join(tmp_project, "FS-docs", "TECH_REQUIREMENTS.md"))
    assert all(it["extracted_status"] == TR.EKSIK for it in req["items"])
    assert len([q for q in req["questions"] if q["status"] == "AÇIK" and q["blocking"]]) == len(req["items"])


# ---------------------------------------------------------------------------
# Onay: EKSİK → soru, onaylanmadan geçmez
# ---------------------------------------------------------------------------
async def test_missing_item_opens_blocking_technology_question_and_needs_explicit_answer(hub, tmp_project):
    await _clear_gate_state(hub)
    _spec(hub, NOTES_MIXED)
    req = await hub.ensure_tech_requirements(tmp_project)
    client_item = _by_cat(req)["client"]
    q = next(x for x in req["questions"] if x["id"] == client_item["question_id"])
    assert q["category"] == "TECHNOLOGY" and q["blocking"] is True and q["status"] == "AÇIK" and q["recommended"] and q["why"]
    # toplu onay yalnızca BELİRTİLMİŞ kalemleri onaylar
    req = await hub.approve_tech_requirements(approve_stated=True)
    cats = _by_cat(req)
    assert cats["backend"]["status"] == TR.ONAYLANDI and cats["database"]["status"] == TR.ONAYLANDI
    assert cats["client"]["status"] == TR.ONAY_BEKLIYOR and cats["auth"]["status"] == TR.ONAY_BEKLIYOR
    assert not hub.tech_requirements_approved()
    # kalan EKSİK / ÇELİŞKİLİ kalemler tek tek cevaplanır; sorular cevaplanınca kapanır
    for cat, val in (("client", "React (web SPA)"), ("realtime", "Not needed"), ("auth", "OAuth2 / OIDC provider (Auth0, Keycloak)")):
        req = await hub.answer_tech_question(_by_cat(req)[cat]["question_id"], val)
    assert hub.tech_requirements_approved() and req["first_approved_at"]
    assert all(it["approved_by"] == "MANAGER" for it in req["items"])
    # onay tech_decisions'a yazıldı, kuruluş ADR'si açıldı ve dosya yeniden üretildi
    assert hub.tech_decisions()["answers"]["client"] == "React (web SPA)" and hub.tech_decisions()["source"] == "user"
    adr = os.path.join(tmp_project, "FS-docs", "adr")
    assert [f for f in os.listdir(adr) if f.startswith("0001-")]
    assert "KABUL EDİLDİ" in open(os.path.join(adr, os.listdir(adr)[0]), encoding="utf-8").read()
    md = open(os.path.join(tmp_project, "FS-docs", "TECH_REQUIREMENTS.md"), encoding="utf-8").read()
    assert "ONAYLANDI" in md and "Yok." in md and "0001" in md


async def test_prefilled_tech_decisions_do_not_open_the_gate_silently(hub, tmp_project):
    """A4: önceden dolu tech_decisions eskiden kapıyı hiç açtırmıyordu; şimdi kalemler 'onay bekliyor' gösterilir."""
    await hub.update_settings({"tech_requirements": None})  # fixture'da tech_decisions dolu
    assert hub.tech_decisions() and not hub.tech_requirements_approved()
    _spec(hub, "Randevu uygulaması.")
    req = await hub.ensure_tech_requirements(tmp_project)
    backend = _by_cat(req)["backend"]
    assert backend["status"] == TR.ONAY_BEKLIYOR and backend["value"] == "Python / FastAPI"  # eski karar yalnızca öneri
    assert backend["extracted_status"] == TR.EKSIK


async def test_new_note_contradicting_an_approved_item_is_asked_again(hub, tmp_project):
    assert hub.tech_requirements_approved()  # fixture: Python / FastAPI onaylı
    _spec(hub, "Backend artık PHP ve Symfony ile yazılacak.")
    req = await hub.ensure_tech_requirements(tmp_project)
    backend = _by_cat(req)["backend"]
    assert backend["extracted_status"] == TR.CELISKILI and backend["status"] == TR.ONAY_BEKLIYOR
    assert not hub.tech_requirements_approved()
    # çelişmeyen onaylı kalemler korunur
    assert _by_cat(req)["database"]["status"] == TR.ONAYLANDI


# ---------------------------------------------------------------------------
# Kapı: hiçbir modda atlanmaz
# ---------------------------------------------------------------------------
def test_template_engine_stays_blocked_in_auto_mode_without_dry_run_flag(client, hub, tmp_project, monkeypatch):
    monkeypatch.delenv("FSSC_DRY_RUN", raising=False)
    hub.step_by_step_mode = False
    client.delete("/api/pipeline/decisions")
    client.post("/api/pipeline/approval-mode", json={"approval_mode": "auto"})
    run = client.post("/api/runs", json={"steps": [2], "engine": "template", "step_by_step": False}).json()["run"]
    waiting = _wait_for(client, run["run_id"], lambda r: r["status"] == "WAITING_APPROVAL")
    assert waiting["gate_kind"] == "decisions" if "gate_kind" in waiting else True
    time.sleep(1.0)
    assert client.get(f"/api/runs/{run['run_id']}").json()["run"]["status"] == "WAITING_APPROVAL"
    assert not hub.tech_requirements_approved() and not os.path.isfile(os.path.join(tmp_project, "FS-docs", "openapi_spec.json"))
    # AUTO_ALL / PROCEED da kalemleri onaylamaz: kapı yeniden açılır
    tok = hub.approval_token
    client.post("/api/pipeline/approve-step", json={"decision": "AUTO_ALL", "token": tok})
    time.sleep(1.0)
    assert client.get(f"/api/runs/{run['run_id']}").json()["run"]["status"] == "WAITING_APPROVAL"
    assert not hub.tech_requirements_approved() and not os.path.isfile(os.path.join(tmp_project, "FS-docs", "openapi_spec.json"))
    # yönetici onaylayınca koşu sürer
    full = {q["id"]: q["recommended"] for q in hub.tech_questions()}
    assert client.post("/api/pipeline/decisions", json={"answers": full}).json()["approved"] is True
    done = _wait_for(client, run["run_id"], lambda r: r["is_terminal"])
    assert done["status"] == "COMPLETED"


def test_mcp_client_run_in_auto_mode_is_blocked_even_with_dry_run_flag(client, hub, monkeypatch):
    """Deneme bayrağı yalnızca şablon motorunda etkilidir; gerçek (MCP istemcisi) koşuda etkisizdir."""
    monkeypatch.setenv("FSSC_DRY_RUN", "1")
    client.delete("/api/pipeline/decisions")
    client.post("/api/pipeline/approval-mode", json={"approval_mode": "auto"})
    run = client.post("/api/runs", json={"steps": [2], "engine": "mcp_client", "client": {"name": "curl", "version": "1"}}).json()["run"]
    rid = run["run_id"]
    first = client.post(f"/api/runs/{rid}/next-step", json={"client": {"name": "curl"}}).json()
    assert first["status"] == "WAITING_APPROVAL" and first["kind"] == "decisions"
    assert client.post(f"/api/runs/{rid}/next-step", json={"client": {"name": "curl"}}).json()["status"] == "WAITING_APPROVAL"  # tekrar sorulsa da geçmez
    assert not hub.tech_requirements_approved()
    client.post(f"/api/runs/{rid}/cancel", json={"reason": "cleanup"})


async def test_dry_run_approve_refuses_without_flag(hub, monkeypatch):
    monkeypatch.delenv("FSSC_DRY_RUN", raising=False)
    await hub.update_settings({"tech_requirements": None})
    with pytest.raises(PermissionError):
        await hub.dry_run_approve_tech()
    assert not hub.tech_requirements_approved()


def test_dry_run_flag_drives_template_run_and_produces_tech_requirements(client, hub, tmp_project, monkeypatch):
    """Kabul: kuru koşuda TECH_REQUIREMENTS.md üretiliyor; kapıyı yalnızca deneme bayrağı simüle ediyor ve kayıtta görünür."""
    monkeypatch.setenv("FSSC_DRY_RUN", "1")
    hub.step_by_step_mode = False
    client.delete("/api/pipeline/decisions")
    hub.uploaded_specs = [{"client_name": "Müşteri", "title": "Notlar", "meeting_notes": NOTES_MIXED, "files": []}]
    client.post("/api/pipeline/approval-mode", json={"approval_mode": "auto"})
    run = client.post("/api/runs", json={"steps": [1, 2, 3, 5], "engine": "template", "step_by_step": False}).json()["run"]
    done = _wait_for(client, run["run_id"], lambda r: r["is_terminal"], timeout=40)
    assert done["status"] == "COMPLETED", done
    md = open(os.path.join(tmp_project, "FS-docs", "TECH_REQUIREMENTS.md"), encoding="utf-8").read()
    assert "Python / FastAPI" in md and "DRY_RUN" in md and "ONAYLANDI" in md
    req = hub.tech_requirements()
    assert req["status"] == TR.ONAYLANDI and {it["approved_by"] for it in req["items"]} == {"DRY_RUN"}
    assert hub.tech_decisions()["source"] == "dry_run"
    assert [f for f in os.listdir(os.path.join(tmp_project, "FS-docs", "adr")) if f.startswith("0001-")]
    # mimarın kütüphane kaydı (şablon çıktısı) kayıt dosyasına işlendi
    assert {l["name"] for l in req["libraries"]} >= {"fastapi", "uvicorn", "pydantic"}
    assert os.path.isfile(os.path.join(tmp_project, "src", "main.py")) and os.path.isfile(os.path.join(tmp_project, "requirements.txt"))


# ---------------------------------------------------------------------------
# Bağımlılık denetimi
# ---------------------------------------------------------------------------
def _approved(libs=()):
    req = TR.build_requirements(DEFAULT_TECH_QUESTIONS, "", "", "/tmp/x")
    TR.apply_approval(req, accept_recommended=True, by="TEST")
    req["libraries"] = list(libs)
    return req


def test_audit_parsers_and_rules(tmp_path):
    req = _approved([{"name": "sqlalchemy", "purpose": "ORM", "technology": "PostgreSQL"}, {"name": "uvicorn", "purpose": "sunucu", "technology": "FastAPI"}])
    files = [
        {"path": "requirements.txt", "content": "fastapi>=0.110\nuvicorn\nSQLAlchemy==2.0\nrequests==2.31  # yeni\n"},
        {"path": "package.json", "content": json.dumps({"dependencies": {"react": "18", "left-pad": "1"}, "devDependencies": {"jest": "29"}})},
        {"path": "docker-compose.yml", "content": "services:\n  db:\n    image: postgres:16\n  cache:\n    image: redis:7\n"},
        {"path": "Dockerfile", "content": "FROM python:3.12-slim\n"},
        {"path": "src/main.py", "content": "import anything\n"},
    ]
    bad = {(v["dependency"], v["file"]) for v in TR.audit_dependencies(req, str(tmp_path), files)}
    # react (client önerisi React Native içinde geçer) ve postgres/python imajları onaylı teknolojiden; jest ise onaylı değil (pytest seçili)
    assert bad == {("requests", "requirements.txt"), ("left-pad", "package.json"), ("jest", "package.json"), ("redis", "docker-compose.yml")}


def test_audit_ignores_deps_already_on_disk_and_skips_when_not_approved(tmp_path):
    (tmp_path / "requirements.txt").write_text("legacy-lib\n", encoding="utf-8")
    req = _approved()
    new = [{"path": "requirements.txt", "content": "legacy-lib\nfastapi\n"}]
    assert TR.audit_dependencies(req, str(tmp_path), new) == []  # legacy-lib önceden vardı → yeni sayılmaz
    pending = TR.build_requirements(DEFAULT_TECH_QUESTIONS, "", "", str(tmp_path))
    assert TR.audit_dependencies(pending, str(tmp_path), [{"path": "requirements.txt", "content": "requests\n"}]) == []


async def test_delivery_with_unregistered_dependency_is_rejected_and_asks_manager(client, hub, tmp_project):
    await hub.update_settings({"approval_mode": "auto"})
    run = client.post("/api/runs", json={"steps": [3], "engine": "mcp_client", "client": {"name": "curl"}}).json()["run"]
    rid = run["run_id"]
    client.post(f"/api/runs/{rid}/next-step", json={"client": {"name": "curl"}})

    def env(reqs):
        return json.dumps({"from_agent": "BACKEND_DEV", "to_agent": "FRONTEND_DEV", "intent": "BACKEND_API_EXPOSED", "status": "SUCCESS",
                           "payload": {"summary": "s", "files": [{"path": "requirements.txt", "content": reqs}, {"path": "src/main.py", "content": "app = 1\n"}]},
                           "metadata": {"tokens_used": 5}})

    res = client.post(f"/api/runs/{rid}/steps/3/result", json={"result_json": env("fastapi\nrequests\n")}).json()
    assert res["status"] == "REJECTED" and any("requests" in e and "Kayıtsız bağımlılık" in e for e in res["validation_errors"])
    assert not os.path.exists(os.path.join(tmp_project, "requirements.txt")) and not os.path.exists(os.path.join(tmp_project, "src", "main.py"))
    # engelleyici TECHNOLOGY sorusu açıldı; kapı yeniden kapandı
    q = next(x for x in hub.tech_requirements()["questions"] if x.get("dependency") == "requests")
    assert q["category"] == "TECHNOLOGY" and q["blocking"] and q["status"] == "AÇIK"
    assert not hub.tech_requirements_approved()
    # yönetici onaylar → kütüphane kaydedilir, yeni ADR açılır, teslim geçer
    await hub.answer_tech_question(q["id"], "Onayla ve kütüphane olarak kaydet")
    assert hub.tech_requirements_approved() and any(l["name"] == "requests" for l in hub.tech_requirements()["libraries"])
    ok = client.post(f"/api/runs/{rid}/steps/3/result", json={"result_json": env("fastapi\nrequests\n")}).json()
    assert ok["status"] in ("NEXT", "RUN_COMPLETE")
    assert os.path.isfile(os.path.join(tmp_project, "requirements.txt"))
    assert [f for f in os.listdir(os.path.join(tmp_project, "FS-docs", "adr")) if f.startswith("0001-")]


async def test_registered_library_and_approved_technology_pass(client, hub, tmp_project):
    hub.step_by_step_mode = False
    await hub.register_libraries([{"name": n, "purpose": "x", "technology": "FastAPI"} for n in ("httpx", "uvicorn", "pydantic")])
    await hub.update_settings({"approval_mode": "auto"})
    run = client.post("/api/runs", json={"steps": [3], "engine": "mcp_client", "client": {"name": "curl"}}).json()["run"]
    rid = run["run_id"]
    client.post(f"/api/runs/{rid}/next-step", json={"client": {"name": "curl"}})
    env = json.dumps({"from_agent": "BACKEND_DEV", "to_agent": "FRONTEND_DEV", "intent": "BACKEND_API_EXPOSED", "status": "SUCCESS",
                      "payload": {"summary": "s", "files": [{"path": "requirements.txt", "content": "fastapi\nuvicorn\npydantic\nhttpx\npytest\n"}]},
                      "metadata": {"tokens_used": 5}})
    res = client.post(f"/api/runs/{rid}/steps/3/result", json={"result_json": env}).json()
    assert res["status"] in ("NEXT", "RUN_COMPLETE"), res
    assert os.path.isfile(os.path.join(tmp_project, "requirements.txt"))


def _dep_env(reqs):
    return json.dumps({"from_agent": "BACKEND_DEV", "to_agent": "FRONTEND_DEV", "intent": "BACKEND_API_EXPOSED", "status": "SUCCESS",
                       "payload": {"summary": "s", "files": [{"path": "requirements.txt", "content": reqs}, {"path": "src/main.py", "content": "app = 1\n"}]},
                       "metadata": {"tokens_used": 5}})


async def test_library_named_in_manager_decision_is_not_asked_again(client, hub, tmp_project):
    """Yönetici bir soru kararında kütüphaneyi adıyla seçtiyse (ör. Q-11 → @nestjs/swagger) bağımlılık kapısı aynı şeyi yeniden sormaz."""
    from server import sprint as SP
    SP.ensure_state(hub)["decisions"].append({"id": "DEC-9", "text": "HTTP istemcisi → requests (resmi paket)", "human_approved": True})
    await hub.update_settings({"approval_mode": "auto"})
    rid = client.post("/api/runs", json={"steps": [3], "engine": "mcp_client", "client": {"name": "curl"}}).json()["run"]["run_id"]
    client.post(f"/api/runs/{rid}/next-step", json={"client": {"name": "curl"}})
    res = client.post(f"/api/runs/{rid}/steps/3/result", json={"result_json": _dep_env("fastapi\nrequests\n")}).json()
    assert res["status"] in ("NEXT", "RUN_COMPLETE"), res
    assert not [q for q in hub.tech_requirements().get("questions", []) if q.get("kind") == "dependency"]
    lib = next(l for l in hub.tech_requirements()["libraries"] if l["name"] == "requests")
    assert "DEC-9" in lib["purpose"] and hub.tech_requirements_approved()


async def test_open_dependency_question_is_reconciled_and_id_does_not_collide(client, hub, tmp_project):
    from server import sprint as SP
    await hub.update_settings({"approval_mode": "auto"})
    rid = client.post("/api/runs", json={"steps": [3], "engine": "mcp_client", "client": {"name": "curl"}}).json()["run"]["run_id"]
    client.post(f"/api/runs/{rid}/next-step", json={"client": {"name": "curl"}})
    client.post(f"/api/runs/{rid}/steps/3/result", json={"result_json": _dep_env("fastapi\nrequests\n")})
    q = next(x for x in hub.tech_requirements()["questions"] if x.get("dependency") == "requests")
    assert q["id"].startswith("D-") and q["status"] == "AÇIK" and not hub.tech_requirements_approved()      # Q-n numaralarıyla çakışmaz
    SP.ensure_state(hub)["decisions"].append({"id": "DEC-3", "text": "İstemci → requests", "human_approved": True})
    await hub.ensure_tech_requirements()                                                                      # sonradan gelen karar açık soruyu kapatır
    assert hub.tech_requirements_approved()
    assert next(x for x in hub.tech_requirements()["questions"] if x["id"] == q["id"])["status"] == "CEVAPLANDI"


def test_compose_yerelde_derlenen_servisin_imaj_adi_bagimlilik_sayilmaz():
    compose = ("name: demo_project\nservices:\n  backend:\n    build:\n      context: ..\n    image: demo-project-backend\n"
               "  db:\n    image: postgis/postgis:16-3.4\n  cache:\n    image: redis:7\n")
    deps = TR.parse_dependencies("devops/docker-compose.yml", compose)
    assert "demo-project-backend" not in deps and {"postgis", "redis"} <= deps                    # dış imajlar kalır, yerel derleme etiketi çıkar
    assert TR.parse_dependencies("docker-compose.yml", "services:\n  db:\n    image: postgres:16\n") == {"postgres"}
