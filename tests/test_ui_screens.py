"""Ekran sözleşmesi: Frontend teslimi `screens[]` ile Tester'a neler yapılabileceğini bildirir → senaryo + ekran görüntüsü."""
import json
import os

from server import ui_screens as UIS
from server.e2e_scenarios import load_scenarios, run_scenarios

RAW = [{"id": "Login", "title": "Giriş", "route": "/login", "ready_selector": "#login-form", "ac_refs": ["ac_13"],
        "actions": [{"name": "Geçerli Giriş", "steps": [{"fill": ["#email", "a@b.com"]}, {"click": "#submit"}, {"expect_text": "Hoş geldin"}, {"bilinmeyen": 1}]},
                    {"name": "boş", "steps": []}]},
       {"id": "", "route": "/x"}, {"id": "rota-yok"}, "bozuk"]


class FakeDriver:
    def __init__(self):
        self.visited, self.shots = [], []

    async def goto(self, url): self.visited.append(url)
    async def click(self, sel): pass
    async def fill(self, sel, val): pass
    async def text(self): return "Hoş geldin"
    async def has(self, sel): return True
    async def url(self): return self.visited[-1] if self.visited else ""
    async def screenshot(self, name):
        self.shots.append(name)
        return f"/shots/{name}.png"


def test_normalize_gecersizleri_atar_adimlari_suzer():
    out = UIS.normalize(RAW)
    assert [s["id"] for s in out] == ["login"] and out[0]["ac_refs"] == ["AC-13"]
    assert [a["name"] for a in out[0]["actions"]] == ["ge-erli-giri"] or len(out[0]["actions"]) == 1      # boş adımlı eylem atılır
    assert all(list(st)[0] in UIS.STEP_KEYS for st in out[0]["actions"][0]["steps"]) and len(out[0]["actions"][0]["steps"]) == 3


def test_ekranlar_projeye_yazilir_ve_senaryoya_donusur(tmp_path):
    saved = UIS.ingest(str(tmp_path), RAW)
    assert saved == ["e2e/screens/login.json"] and json.load(open(tmp_path / "e2e" / "screens" / "login.json", encoding="utf-8"))["route"] == "/login"
    sc = {s["id"]: s for s in load_scenarios(str(tmp_path))}
    assert set(sc) == {"SCR-login", f"SCR-login--{UIS.normalize(RAW)[0]['actions'][0]['name']}"}
    assert sc["SCR-login"]["steps"][-1] == {"screenshot": "login"} and sc["SCR-login"]["steps"][1] == {"expect_selector": "#login-form"}


async def test_ekran_senaryosu_kosulur_ve_goruntu_alir(tmp_path):
    UIS.ingest(str(tmp_path), RAW)
    drv = FakeDriver()
    res = await run_scenarios(str(tmp_path), "http://127.0.0.1:3000", driver_factory=lambda: drv)
    assert res["status"] == "PASSED" and len(res["screenshots"]) == 2 and drv.shots[0] == "login"
    assert res["ac_evidence"]["AC-13"]["failed"] == []


def test_devir_notu_tester_ve_qaya_gider():
    notes = UIS.handoff_notes(UIS.normalize(RAW))
    assert {n["to"] for n in notes} == {"E2E_TESTER", "QA"} and "/login" in notes[0]["message"] and UIS.handoff_notes([]) == []
