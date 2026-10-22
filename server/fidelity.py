"""Ekran uyumu denetimi (sunucu): onaylı mockup'ı çalışan uygulamadaki ekranla karşılaştırır.

Ajanın "mockup'a uydum" beyanına değil, gerçek tarayıcıya bakar (Playwright):
1. Mockup (`<docs>/design/screens/<id>.html`, file://) ve çalışan ekran (`client_url` + rota) aynı görünüm alanında (masaüstü 1280x800, mobil 390x844) çekilir.
2. Metin kapsaması: mockup'ta görünen kelimelerin uygulamada bulunma oranı (başlık, düğme, etiket, durum metinleri).
3. Görsel benzerlik: iki görüntü küçültülüp renk dağılımı ve yerleşim (ızgara parlaklığı) karşılaştırılır (Pillow).
4. Yönlendirme: uygulama başka bir yola yönlendirdiyse (örn. giriş) ekran gerçekten görülemedi, ayrıca işaretlenir.
Rapor `.fs-workspace/fidelity/report.json`; yan yana görüntüler `.fs-workspace/e2e/screenshots/fidelity_<id>_<görünüm>.png` (pano bunları zaten servis eder).
Eşik altı ekran için "Ekran uyumu" görevi açılır (pipeline.reopen_screen_tasks yerine neden belirtilerek).
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .i18n import translate as tx

VIEWPORTS = {"desktop": (1280, 800), "mobile": (390, 844)}
TEXT_MIN = 0.4           # mockup kelimelerinin en az bu oranı uygulamada görünmeli (mockup durum örneklerini de içerir, bu yüzden 1.0 beklenmez)
VISUAL_MIN = 0.55        # görsel benzerlik (0-1)
_WORD = re.compile(r"[\wçğıöşüÇĞİÖŞÜ]{3,}", re.UNICODE)
REPORT_REL = ".fs-workspace/fidelity/report.json"


def screens_of(hub) -> List[Dict[str, str]]:
    """Tasarım ekranları: Jira'da `design_screen` taşıyan (yenisi 'Ekran uyumu' değil, ilk ekran görevi) maddelerden {id, title, route, file}."""
    out: Dict[str, Dict[str, str]] = {}
    for i in sorted(hub.jira_issues.values(), key=lambda x: int(x.get("order", 0) or 0)):
        sid = str(i.get("design_screen") or "")
        if not sid or i.get("deleted") or sid in out:
            continue
        m = re.search(r"\((/[^)]*)\)\s*$", str(i.get("title") or ""))
        hints = [h for h in (i.get("files_hint") or []) if str(h).endswith(".html")]
        out[sid] = {"id": sid, "title": re.sub(r"^(Ekran uyumu|Ekran):\s*", "", str(i.get("title") or "")), "route": m.group(1) if m else "/",
                    "file": str(hints[0]) if hints else f"<docs>/design/screens/{sid}.html", "issue_id": i["id"]}
    return list(out.values())


def _route(route: str) -> str:
    return re.sub(r":\w+|\{[^}]*\}", "1", route or "/")


def _words(text: str) -> set:
    return {w.lower() for w in _WORD.findall(text or "")}


def visual_similarity(img_a, img_b) -> float:
    """0-1: 16x16 ızgara parlaklık farkı (yerleşim) ve 4 seviyeli renk dağılımı kesişimi (palet) ortalaması."""
    from PIL import Image
    def prep(im):
        return im.convert("RGB").resize((64, 64))
    a, b = prep(img_a), prep(img_b)
    ga, gb = a.convert("L").resize((16, 16)), b.convert("L").resize((16, 16))
    pa, pb = list(ga.getdata()), list(gb.getdata())
    layout = 1.0 - (sum(abs(x - y) for x, y in zip(pa, pb)) / len(pa)) / 255.0
    def hist(im):
        h: Dict[tuple, int] = {}
        for r, g, bl in im.getdata():
            k = (r // 64, g // 64, bl // 64)
            h[k] = h.get(k, 0) + 1
        n = float(sum(h.values()))
        return {k: v / n for k, v in h.items()}
    ha, hb = hist(a), hist(b)
    palette = sum(min(ha.get(k, 0.0), hb.get(k, 0.0)) for k in set(ha) | set(hb))
    return round((layout + palette) / 2.0, 3)


def _side_by_side(path_a: str, path_b: str, out: str) -> None:
    from PIL import Image, ImageDraw
    a, b = Image.open(path_a).convert("RGB"), Image.open(path_b).convert("RGB")
    h = min(1400, max(a.height, b.height))
    a, b = a.crop((0, 0, a.width, min(a.height, h))), b.crop((0, 0, b.width, min(b.height, h)))
    canvas = Image.new("RGB", (a.width + b.width + 30, h + 28), "white")
    canvas.paste(a, (0, 28)); canvas.paste(b, (a.width + 30, 28))
    d = ImageDraw.Draw(canvas)
    d.text((6, 6), "MOCKUP", fill=(30, 30, 30)); d.text((a.width + 36, 6), "UYGULAMA", fill=(30, 30, 30))
    canvas.save(out)


async def _shoot(page, url: str, path: str) -> Dict[str, Any]:
    resp = await page.goto(url, wait_until="networkidle", timeout=30000)
    await page.wait_for_timeout(400)
    await page.screenshot(path=path, full_page=True)
    text = await page.evaluate("document.body ? document.body.innerText : ''")
    return {"status": resp.status if resp else None, "final": page.url, "words": _words(text)}


async def compare(project_dir: str, docs_root: str, base_url: str, screens: List[Dict[str, str]], project_id: Optional[str] = None) -> Dict[str, Any]:
    """Her ekranı karşılaştırır; rapor sözlüğü döner (ve diske yazar)."""
    from playwright.async_api import async_playwright
    from PIL import Image
    shots = os.path.join(project_dir, ".fs-workspace", "e2e", "screenshots")
    os.makedirs(shots, exist_ok=True)
    rows: List[Dict[str, Any]] = []
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        try:
            for sc in screens:
                mock_rel = sc["file"].replace("<docs>", docs_root).replace("\\", "/").lstrip("/")
                mock_path = os.path.join(project_dir, *mock_rel.split("/"))
                row: Dict[str, Any] = {"id": sc["id"], "title": sc["title"], "route": sc["route"], "issue_id": sc.get("issue_id"), "views": {}, "problems": []}
                if not os.path.isfile(mock_path):
                    row["problems"].append(tx("Mockup dosyası yok: {path}", path=mock_rel)); row["ok"] = False; rows.append(row); continue
                for view, (w, h) in VIEWPORTS.items():
                    ctx = await browser.new_context(viewport={"width": w, "height": h})
                    page = await ctx.new_page()
                    stem = f"fidelity_{sc['id']}_{view}"
                    try:
                        mock = await _shoot(page, "file:///" + mock_path.replace("\\", "/"), os.path.join(shots, stem + "_mock.png"))
                        # Yönlendirici türü bilinmez: yol (`/giris`) ve karma (`/#/giris`) adresleri denenir, mockup'a daha çok benzeyen sayılır
                        best = None
                        for target in (base_url.rstrip("/") + _route(sc["route"]), base_url.rstrip("/") + "/#" + _route(sc["route"])):
                            cand = await _shoot(page, target, os.path.join(shots, stem + "_app_try.png"))
                            score = len(mock["words"] & cand["words"])
                            if best is None or score > best[0]:
                                best = (score, cand)
                                os.replace(os.path.join(shots, stem + "_app_try.png"), os.path.join(shots, stem + "_app.png"))
                        app = best[1]
                    except Exception as e:      # noqa: BLE001 — ulaşılamayan ekran da sonuçtur
                        row["views"][view] = {"error": str(e)[:200]}
                        row["problems"].append(tx("{view}: ekran açılamadı ({err})", view=view, err=str(e)[:120]))
                        await ctx.close(); continue
                    await ctx.close()
                    cover = round(len(mock["words"] & app["words"]) / max(1, len(mock["words"])), 3)
                    vis = visual_similarity(Image.open(os.path.join(shots, stem + "_mock.png")), Image.open(os.path.join(shots, stem + "_app.png")))
                    redirected = _route(sc["route"]).rstrip("/") not in app["final"] and _route(sc["route"]) != "/"
                    _side_by_side(os.path.join(shots, stem + "_mock.png"), os.path.join(shots, stem + "_app.png"), os.path.join(shots, stem + ".png"))
                    row["views"][view] = {"text_coverage": cover, "visual": vis, "redirected": redirected, "final_url": app["final"], "http": app["status"],
                                          "missing": sorted(mock["words"] - app["words"])[:60],
                                          "image": f"/api/projects/{project_id}/screenshots/{stem}.png" if project_id else stem + ".png"}
                    if redirected:
                        row["problems"].append(tx("{view}: uygulama başka sayfaya yönlendirdi ({url}); ekran görülemedi (oturum/rota gerekebilir)", view=view, url=app["final"]))
                    if cover < TEXT_MIN:
                        row["problems"].append(tx("{view}: mockup metinlerinin yalnızca %{pct}'i uygulamada var", view=view, pct=int(cover * 100)))
                    if vis < VISUAL_MIN:
                        row["problems"].append(tx("{view}: görsel benzerlik düşük (%{pct})", view=view, pct=int(vis * 100)))
                row["ok"] = bool(row["views"]) and not row["problems"]
                rows.append(row)
        finally:
            await browser.close()
    report = {"at": datetime.now(timezone.utc).isoformat(), "base_url": base_url, "text_min": TEXT_MIN, "visual_min": VISUAL_MIN,
              "passed": sum(1 for r in rows if r.get("ok")), "total": len(rows), "screens": rows}
    path = os.path.join(project_dir, *REPORT_REL.split("/"))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=1)
    return report


def load_report(project_dir: str) -> Optional[Dict[str, Any]]:
    try:
        with open(os.path.join(project_dir, *REPORT_REL.split("/")), "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


async def check_screen(hub, project_dir: str, docs_root: str, issue: Dict[str, Any]) -> Dict[str, Any]:
    """Tek ekran görevi için kabul kapısı: istemci kapalıysa `client_run` ile başlatılır, ekran mockup ile karşılaştırılır, istemci kapatılır.
    Dönüş: {'ran': bool, 'ok': bool|None, 'problems': [...], 'text': ajana giden ayrıntı, 'note': ran değilse neden}. Yönlendirme (oturum gerektiren ekran) doğrulanamaz sayılır, hata değildir."""
    import urllib.request
    from .app_runner import start_app
    ver = hub.get_settings().get("verification") or {}
    url = str(ver.get("client_url") or "").strip()
    if not url:
        return {"ran": False, "ok": None, "problems": [], "note": tx("verification.client_url tanımlı değil")}
    sid = str(issue.get("design_screen") or "")
    screens = [sc for sc in screens_of(hub) if sc["id"] == sid]
    if not screens:
        return {"ran": False, "ok": None, "problems": [], "note": tx("ekran tasarımı bulunamadı")}

    def up() -> bool:
        try:
            return urllib.request.urlopen(url, timeout=3).status < 500
        except Exception:
            return False
    import asyncio
    proc = None
    if not await asyncio.to_thread(up):
        if not ver.get("client_run"):
            return {"ran": False, "ok": None, "problems": [], "note": tx("istemci kapalı ve verification.client_run tanımlı değil")}
        started = await start_app(project_dir, ver["client_run"], url)
        if not started.get("ok"):
            return {"ran": False, "ok": None, "problems": [], "note": tx("istemci başlatılamadı: {err}", err=str(started.get("error"))[:120])}
        proc = started["app"]
    try:
        report = await compare(project_dir, docs_root, url, screens, hub.active_project_id)
    finally:
        if proc is not None:
            await proc.stop()
    row = report["screens"][0]
    views = row.get("views") or {}
    if views and all(v.get("redirected") for v in views.values() if "error" not in v):
        return {"ran": True, "ok": None, "problems": [], "note": tx("ekran oturum/rota gerektiriyor (yönlendirildi); doğrulanamadı"), "row": row}
    lines = list(row.get("problems") or [])
    for view, v in views.items():
        if v.get("missing"):
            lines.append(tx("{view}: mockup'ta olup uygulamada görünmeyen metinler: {words}", view=view, words=", ".join(v["missing"][:40])))
    lines.append(tx("Karşılaştırma görüntüleri: .fs-workspace/e2e/screenshots/fidelity_{id}_desktop.png (sol mockup, sağ uygulama)", id=sid))
    return {"ran": True, "ok": bool(row.get("ok")), "problems": row.get("problems") or [], "text": chr(10).join(lines), "row": row}
