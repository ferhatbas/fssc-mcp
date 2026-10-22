"""Ekran sözleşmesi: Frontend ekran geliştirince Tester'a "bu ekranda neler yapılabilir" bilgisini teslimiyle bildirir (`screens[]`).

Sunucu bunu projede `e2e/screens/<id>.json` olarak saklar, E2E_TESTER/QA'ya devir notu bırakır ve E2E adımında her ekran + eylem için Playwright
senaryosu üretip koşar; her ekranın ekran görüntüsü alınır (`screenshot` adımı). Senaryo kod değildir; FE yalnızca bildirir, Tester yorumlamadan koşar.

```json
{"id": "login", "title": "Giriş", "route": "/login", "ready_selector": "#login-form", "ac_refs": ["AC-13"],
 "actions": [{"name": "gecerli-giris", "steps": [{"fill": ["#email", "ali@x.com"]}, {"fill": ["#pass", "Parola1!"]}, {"click": "#submit"}, {"expect_text": "Hoş geldin"}]}]}
```
"""
from __future__ import annotations

import glob
import json
import os
import re
from typing import Any, Dict, List

from .i18n import translate as tx, N_

SCREENS_REL = "e2e/screens"
STEP_KEYS = ("goto", "click", "fill", "expect_text", "expect_selector", "expect_url_contains", "screenshot")
UI_EXT = (".tsx", ".jsx", ".vue", ".svelte", ".html")

CONTRACT_HINT = N_(
    "\n**Ekran sözleşmesi (ekran/sayfa/bileşen eklediysen ZORUNLU):** `payload.screens[]` ile Tester'a bu ekranda neler yapılabileceğini bildir; "
    "sunucu bunu Playwright senaryosuna çevirir ve ekran görüntüsü alır. Biçim: "
    "`{\"id\":\"login\",\"title\":\"Giriş\",\"route\":\"/login\",\"ready_selector\":\"#login-form\",\"ac_refs\":[\"AC-13\"],"
    "\"actions\":[{\"name\":\"gecerli-giris\",\"steps\":[{\"fill\":[\"#email\",\"a@b.com\"]},{\"click\":\"#submit\"},{\"expect_text\":\"Hoş geldin\"}]}]}`. "
    "Adımlar: goto, click, fill [seçici,değer], expect_text, expect_selector, expect_url_contains. Seçiciler kodundaki gerçek id/data-testid olsun; "
    "ekranın görünür durumlarını (boş, hata, dolu) ayrı eylem olarak yaz. Ekran yoksa `screens: []`."
)     # kullanımda çevrilir: tx(CONTRACT_HINT) (steps/tasks.py)


def slug(text: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(text or "").lower()).strip("-")[:60]


def _steps(raw: Any) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for s in raw if isinstance(raw, list) else []:
        if not isinstance(s, dict):
            continue
        k = next((k for k in STEP_KEYS if k in s), None)
        if k is None:
            continue
        if k == "fill" and not (isinstance(s["fill"], (list, tuple)) and len(s["fill"]) == 2):
            continue
        out.append({k: s[k]})
    return out


def normalize(raw: Any) -> List[Dict[str, Any]]:
    """Geçerli ekran kayıtlarını döner (kimlik ve rota zorunlu; bozuk kayıt sessizce atlanır, `invalid_screens` ile sayılır)."""
    out: List[Dict[str, Any]] = []
    for r in raw if isinstance(raw, list) else []:
        if not isinstance(r, dict):
            continue
        sid, route = slug(r.get("id") or r.get("title")), str(r.get("route") or "").strip()
        if not sid or not route:
            continue
        actions = []
        for a in r.get("actions") or []:
            if isinstance(a, dict) and slug(a.get("name")):
                st = _steps(a.get("steps"))
                if st:
                    actions.append({"name": slug(a["name"]), "steps": st})
        out.append({"id": sid, "title": str(r.get("title") or sid)[:120], "route": route, "ready_selector": str(r.get("ready_selector") or "").strip(),
                    "ac_refs": [str(x).upper().replace("_", "-") for x in (r.get("ac_refs") or [])], "actions": actions})
    return out


def ingest(project_dir: str, raw: Any) -> List[str]:
    """Ekranları `e2e/screens/<id>.json` olarak yazar (aynı kimlik güncellenir). Yazılan göreli yolları döner."""
    written: List[str] = []
    screens = normalize(raw)
    if not screens or not project_dir or not os.path.isdir(project_dir):
        return written
    base = os.path.join(project_dir, *SCREENS_REL.split("/"))
    os.makedirs(base, exist_ok=True)
    for sc in screens:
        with open(os.path.join(base, f"{sc['id']}.json"), "w", encoding="utf-8") as f:
            json.dump(sc, f, ensure_ascii=False, indent=2)
        written.append(f"{SCREENS_REL}/{sc['id']}.json")
    return written


def load(project_dir: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for path in sorted(glob.glob(os.path.join(project_dir, SCREENS_REL, "*.json"))):
        try:
            out += normalize([json.load(open(path, encoding="utf-8"))])
        except Exception:  # noqa: BLE001
            continue
    return out


def to_scenarios(project_dir: str) -> List[Dict[str, Any]]:
    """Her ekran için 'ekran açılır + görüntü' senaryosu, her eylem için ayrı senaryo (eylem sonrası görüntüsüyle) üretir."""
    out: List[Dict[str, Any]] = []
    for sc in load(project_dir):
        head: List[Dict[str, Any]] = [{"goto": sc["route"]}]
        if sc["ready_selector"]:
            head.append({"expect_selector": sc["ready_selector"]})
        file = f"{SCREENS_REL}/{sc['id']}.json"
        out.append({"id": f"SCR-{sc['id']}", "title": tx("Ekran: {title}", title=sc['title']), "file": file, "ac_refs": sc["ac_refs"],
                    "steps": head + [{"screenshot": sc["id"]}]})
        for a in sc["actions"]:
            out.append({"id": f"SCR-{sc['id']}--{a['name']}", "title": f"{sc['title']}: {a['name']}", "file": file, "ac_refs": sc["ac_refs"],
                        "steps": head + a["steps"] + [{"screenshot": f"{sc['id']}--{a['name']}"}]})
    return out


def handoff_notes(screens: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    """Tester'a (E2E_TESTER) ve QA'ya gidecek devir notları."""
    if not screens:
        return []
    lines = []
    for s in screens[:12]:
        acts = ", ".join(a["name"] for a in s["actions"]) or tx("yalnızca açılış")
        lines.append(f"{s['title']} ({s['route']}): {acts}")
    msg = tx("Test edilecek ekranlar: ") + "; ".join(lines) + tx(". Senaryolar e2e/screens/ altında; E2E adımı her ekranı Playwright ile açıp ekran görüntüsü alır.")
    return [{"to": "E2E_TESTER", "message": msg[:600]}, {"to": "QA", "message": msg[:600]}]


def wrote_ui(paths: List[str]) -> bool:
    return any(str(p).lower().endswith(UI_EXT) for p in paths)
