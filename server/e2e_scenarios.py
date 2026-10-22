"""Kabul kriterine bağlı E2E senaryoları (F6, belge §6.3 QA/E2E_TESTER, §7.7).

QA, kabul kriterlerinden bildirimsel senaryo dosyaları yazar (`e2e/scenarios/*.json`); E2E_TESTER (sunucu) bunları çalışan uygulamaya karşı koşar ve sonucu
kabul kriteri bazında raporlar. Senaryo kod değildir: yalnızca sıralı adımlardır, bu yüzden E2E_TESTER "kod yazmaz, senaryo yazmaz, yorumlamaz" kuralı korunur.

```json
{"id": "E2E-AC13-giris", "title": "Giriş", "ac_refs": ["AC-13"],
 "steps": [{"goto": "/"}, {"fill": ["#user", "ali"]}, {"click": "#login"}, {"expect_text": "Hoş geldin"}, {"expect_selector": "#profile"}]}
```
Adımlar: `goto` (yol ya da tam adres), `click`, `fill` [seçici, değer], `expect_text`, `expect_selector`, `expect_url_contains`.
"""
from __future__ import annotations

import glob
import json
import os
import re
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import urljoin

from .i18n import translate as tx

SCENARIO_GLOB = os.path.join("e2e", "scenarios", "*.json")
STEP_KEYS = ("goto", "click", "fill", "expect_text", "expect_selector", "expect_url_contains", "screenshot")


def load_scenarios(project_dir: str) -> List[Dict[str, Any]]:
    """Geçerli senaryoları döner; bozuk dosya `invalid` olarak raporlanır (sessizce atlanmaz)."""
    out: List[Dict[str, Any]] = []
    for path in sorted(glob.glob(os.path.join(project_dir, SCENARIO_GLOB))):
        rel = os.path.relpath(path, project_dir).replace("\\", "/")
        try:
            data = json.load(open(path, encoding="utf-8"))
            steps = data.get("steps")
            if not isinstance(steps, list) or not steps or not all(isinstance(s, dict) and any(k in s for k in STEP_KEYS) for s in steps):
                raise ValueError("steps boş ya da bilinmeyen adım")
            out.append({"id": str(data.get("id") or os.path.splitext(os.path.basename(path))[0]), "title": str(data.get("title") or ""), "file": rel,
                        "ac_refs": [str(a).upper().replace("_", "-") for a in (data.get("ac_refs") or [])], "steps": steps})
        except Exception as e:  # noqa: BLE001
            out.append({"id": os.path.basename(path), "file": rel, "ac_refs": [], "steps": [], "invalid": str(e)})
    from .ui_screens import to_scenarios          # Frontend'in bildirdiği ekranlar (e2e/screens/*.json) da senaryo olur
    return out + to_scenarios(project_dir)


async def run_scenario(driver: Any, base_url: str, sc: Dict[str, Any]) -> Dict[str, Any]:
    """Tek senaryoyu `driver` (goto/click/fill/text/has/url) üzerinde koşar."""
    if sc.get("invalid"):
        return {"id": sc["id"], "file": sc["file"], "ac_refs": [], "status": "FAILED", "failed_step": 0, "log": [tx("geçersiz senaryo: {error}", error=sc['invalid'])]}
    log: List[str] = []
    shots: List[str] = []
    for i, step in enumerate(sc["steps"], 1):
        try:
            if "goto" in step:
                target = str(step["goto"])
                await driver.goto(target if target.startswith("http") else urljoin(base_url.rstrip("/") + "/", target.lstrip("/")))
                log.append(f"{i}. goto {target} ✓")
            elif "click" in step:
                await driver.click(str(step["click"]))
                log.append(f"{i}. click {step['click']} ✓")
            elif "fill" in step:
                sel, val = step["fill"]
                await driver.fill(str(sel), str(val))
                log.append(f"{i}. fill {sel} ✓")
            elif "expect_text" in step:
                body = await driver.text()
                if str(step["expect_text"]) not in body:
                    raise AssertionError(tx("metin bulunamadı: {text}", text=repr(step['expect_text'])))
                log.append(f"{i}. expect_text {step['expect_text']!r} ✓")
            elif "expect_selector" in step:
                if not await driver.has(str(step["expect_selector"])):
                    raise AssertionError(tx("seçici bulunamadı: {selector}", selector=step['expect_selector']))
                log.append(f"{i}. expect_selector {step['expect_selector']} ✓")
            elif "screenshot" in step:
                shot = await driver.screenshot(str(step["screenshot"])) if hasattr(driver, "screenshot") else None
                if shot:
                    shots.append(shot)
                log.append(f"{i}. screenshot {step['screenshot']} {'✓' if shot else tx('(sürücü desteklemiyor)')}")
            elif "expect_url_contains" in step:
                if str(step["expect_url_contains"]) not in await driver.url():
                    raise AssertionError(tx("adres {url} içermiyor", url=repr(step['expect_url_contains'])))
                log.append(f"{i}. expect_url_contains ✓")
        except Exception as e:  # noqa: BLE001
            log.append(f"{i}. ✗ {type(e).__name__}: {str(e)[:200]}")
            if hasattr(driver, "screenshot"):          # başarısız durumun görüntüsü de kanıttır
                try:
                    bad = await driver.screenshot(f"{sc['id']}--FAILED")
                    if bad:
                        shots.append(bad)
                except Exception:  # noqa: BLE001
                    pass
            return {"id": sc["id"], "file": sc["file"], "ac_refs": sc["ac_refs"], "status": "FAILED", "failed_step": i, "log": log, "screenshots": shots}
    return {"id": sc["id"], "file": sc["file"], "ac_refs": sc["ac_refs"], "status": "PASSED", "failed_step": None, "log": log, "screenshots": shots}


class _PlaywrightDriver:
    def __init__(self, page: Any, project_dir: Optional[str] = None, project_id: Optional[str] = None):
        self.page = page
        self.project_dir, self.project_id = project_dir, project_id

    async def screenshot(self, name: str) -> Optional[str]:
        from .playwright_tester import screenshot_url, screenshots_dir_for
        fn = f"{re.sub(r'[^A-Za-z0-9_.-]+', '_', name)[:80]}_{datetime.now().strftime('%H%M%S')}.png"
        await self.page.screenshot(path=os.path.join(screenshots_dir_for(self.project_dir), fn), full_page=True)
        return screenshot_url(self.project_id, fn)

    async def goto(self, url: str):
        await self.page.goto(url, wait_until="domcontentloaded", timeout=20000)

    async def click(self, sel: str):
        await self.page.click(sel, timeout=8000)

    async def fill(self, sel: str, val: str):
        await self.page.fill(sel, val, timeout=8000)

    async def text(self) -> str:
        return await self.page.inner_text("body", timeout=8000)

    async def has(self, sel: str) -> bool:
        return await self.page.locator(sel).count() > 0

    async def url(self) -> str:
        return self.page.url


async def run_scenarios(project_dir: str, base_url: str, driver_factory: Optional[Callable[[], Any]] = None, project_id: Optional[str] = None) -> Dict[str, Any]:
    """Projenin tüm senaryolarını koşar. `driver_factory`: testler için sahte sürücü; yoksa Playwright (Chromium) kullanılır.
    Dönüş: {status, scenarios[], ac_evidence{AC-n: {passed[], failed[]}}, executed_at}. Senaryo yoksa status `NONE`."""
    scenarios = load_scenarios(project_dir)
    res: Dict[str, Any] = {"status": "NONE", "scenarios": [], "ac_evidence": {}, "executed_at": datetime.now(timezone.utc).isoformat()}
    if not scenarios:
        return res
    results: List[Dict[str, Any]] = []
    if driver_factory is not None:
        for sc in scenarios:
            results.append(await run_scenario(driver_factory(), base_url, sc))
    else:
        try:
            from playwright.async_api import async_playwright
            async with async_playwright() as pw:
                browser = await pw.chromium.launch(headless=True)
                try:
                    for sc in scenarios:
                        ctx = await browser.new_context()
                        page = await ctx.new_page()
                        try:
                            results.append(await run_scenario(_PlaywrightDriver(page, project_dir, project_id), base_url, sc))
                        finally:
                            await ctx.close()
                finally:
                    await browser.close()
        except Exception as e:  # noqa: BLE001
            results = [{"id": sc["id"], "file": sc["file"], "ac_refs": sc["ac_refs"], "status": "FAILED", "failed_step": 0,
                        "log": [tx("Tarayıcı başlatılamadı: {error}", error=str(e)[:200])]} for sc in scenarios]
    ev: Dict[str, Dict[str, List[str]]] = {}
    for r in results:
        for ac in r["ac_refs"]:
            slot = ev.setdefault(ac, {"passed": [], "failed": []})
            slot["passed" if r["status"] == "PASSED" else "failed"].append(r["id"])
    res.update({"status": "PASSED" if all(r["status"] == "PASSED" for r in results) else "FAILED", "scenarios": results, "ac_evidence": ev,
                "screenshots": [u for r in results for u in (r.get("screenshots") or [])]})
    return res
