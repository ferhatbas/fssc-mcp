"""Soru kuyruğunda serbest metin ('Diğer') cevap: seçenek dışı karar, karar kaydı ve doğrulamalar."""

from server import meetings as M
from server import sprint as SP


async def _open(hub, text="Dağıtım için Docker kullanılsın mı?"):
    return await M.open_system_question(
        hub, category="TECHNOLOGY", raised_by="DEVOPS", text=text,
        options=[{"key": "A", "label": "Evet: Docker"}, {"key": "B", "label": "Hayır"}],
        recommended="A", rationale="Ortamları eşitler.")


async def test_free_text_answer_is_recorded_as_custom_option(client, hub):
    q = await _open(hub)
    assert q["status"] == "OPEN" and q["blocking"] is True

    res = client.post(f"/api/questions/{q['id']}/answer", json={"custom_text": "  Docker yerine Podman kullanılsın.  "})
    assert res.status_code == 200 and res.json()["status"] == "OK"
    got = res.json()["question"]
    assert got["status"] == "ANSWERED" and got["answer"] == "CUSTOM" and got["answered_by"] == "MANAGER"
    custom = next(o for o in got["options"] if o["key"] == "CUSTOM")
    assert custom["label"] == "Docker yerine Podman kullanılsın." and custom["custom"] is True
    # karar kaydı serbest metni aynen taşır; diğer seçenekler alternatif olarak yazılır
    dec = next(d for d in SP.ensure_state(hub)["decisions"] if d["question"] == q["id"])
    assert "Docker yerine Podman kullanılsın." in dec["text"] and dec["human_approved"] is True
    assert set(dec["alternatives"]) == {"Evet: Docker", "Hayır"}
    # engelleyici soru kalmadı
    assert q["id"] not in [x["id"] for x in M.open_blocking(hub)]


async def test_free_text_validation_and_option_answers_still_work(client, hub):
    q = await _open(hub)
    assert client.post(f"/api/questions/{q['id']}/answer", json={"custom_text": "   "}).status_code == 400
    assert client.post(f"/api/questions/{q['id']}/answer", json={}).status_code == 400
    assert client.post(f"/api/questions/{q['id']}/answer", json={"answer": "Z"}).status_code == 400      # geçersiz anahtar hâlâ reddedilir
    ok = client.post(f"/api/questions/{q['id']}/answer", json={"answer": "B"}).json()
    assert ok["question"]["answer"] == "B" and not any(o["key"] == "CUSTOM" for o in ok["question"]["options"])
    # cevaplanmış soru tekrar cevaplanamaz (serbest metinle de)
    assert client.post(f"/api/questions/{q['id']}/answer", json={"custom_text": "geç kaldı"}).status_code == 400


async def test_free_text_is_trimmed_to_limit(client, hub):
    q = await _open(hub, "Uzun cevap sorusu?")
    res = client.post(f"/api/questions/{q['id']}/answer", json={"custom_text": "x" * 900}).json()
    custom = next(o for o in res["question"]["options"] if o["key"] == "CUSTOM")
    assert len(custom["label"]) == M.CUSTOM_MAX_CHARS
