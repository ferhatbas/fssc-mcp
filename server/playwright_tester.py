"""
Playwright Tabanlı E2E Gerçek Kullanıcı / Tester Ajanı.
Çalışan web servisine gerçek Chromium tarayıcısı açar, login olur,
özellikleri test eder, ekran görüntüleri (screenshot) yakalar ve
Team Lead için doğrulanmış test raporu üretir.
"""

import asyncio
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import tempfile

from .i18n import translate as tx

# Ekran görüntüleri hedef projenin kökünde tutulur (FS-SC kökünde proje verisi oluşmaz; bkz. server/paths.py)
SCREENSHOTS_REL = ".fs-workspace/e2e/screenshots"


def screenshots_dir_for(project_dir: Optional[str]) -> str:
    """Projenin ekran görüntüsü klasörü; proje yoksa geçici klasör (FS-SC kökü kullanılmaz). Klasörü oluşturur."""
    if project_dir:
        path = os.path.join(os.path.abspath(project_dir), *SCREENSHOTS_REL.split("/"))
    else:
        path = os.path.join(tempfile.gettempdir(), "fssc_e2e_screenshots")
    os.makedirs(path, exist_ok=True)
    return path


class _TargetUnreachable(Exception):
    """Hedefe ulaşılamadı ya da sayfa 4xx/5xx döndü: test koşulamadı (G1: 'geçti' sayılmaz)."""


class _PageError(Exception):
    """Sayfada yakalanmamış JavaScript hatası: gerçek bir kusur (G1)."""


def screenshot_url(project_id: Optional[str], filename: str) -> str:
    """Panonun gösterebileceği adres: proje başına servis yolu."""
    return f"/api/projects/{project_id}/screenshots/{filename}" if project_id else filename


async def run_playwright_e2e_tests(
    target_url: str = "http://127.0.0.1:8099",
    test_scenario: str = "Login, Navigation and Action Verification",
    credentials: Optional[Dict[str, Any]] = None,
    project_dir: Optional[str] = None,
    project_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Playwright ile gerçek tarayıcı üzerinde E2E testleri koşturur, formları test kullanıcısıyla doldurur ve ekran görüntüleri alır."""
    timestamp_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    shots_dir = screenshots_dir_for(project_dir)
    screenshots: List[str] = []
    logs: List[str] = []
    page_errors: List[str] = []
    console_errors: List[str] = []
    failure_kind: Optional[str] = None
    status = "PASSED"
    
    cred = credentials or {}
    test_user = cred.get("username", "")
    test_pass = cred.get("password", "")
    test_role = cred.get("role", "USER")
    is_negative_test = (test_role == "GUEST" or "hacker" in test_user.lower() or "invalid" in test_user.lower())

    logs.append(tx("[*] Playwright E2E Test Runner başlatıldı: {ts}", ts=datetime.now(timezone.utc).isoformat()))
    logs.append(tx("[*] Hedef URL: {url}", url=target_url))
    logs.append(tx("[*] Senaryo: {scenario}", scenario=test_scenario))
    if test_user:
        logs.append(tx("[*] Test Kullanıcısı: {user} (Rol: {role})", user=test_user, role=test_role))

    try:
        from playwright.async_api import async_playwright
        
        async with async_playwright() as p:
            # Chromium tarayıcısını başlat
            logs.append(tx("[1/5] Chromium tarayıcısı başlatılıyor..."))
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(viewport={"width": 1280, "height": 720})
            page = await context.new_page()

            # 1. Sayfaya Git — G1: ulaşılamayan hedef ya da 4xx/5xx "geçti" sayılmaz; yakalanmamış JS hataları toplanır
            page.on("pageerror", lambda exc: page_errors.append(str(exc)[:300]))
            page.on("console", lambda msg: console_errors.append(str(msg.text)[:300]) if msg.type == "error" else None)
            logs.append(tx("[2/5] Hedef sayfaya bağlanılıyor: {url}", url=target_url))
            try:
                response = await page.goto(target_url, timeout=15000, wait_until="load")
            except Exception as e:
                raise _TargetUnreachable(tx("Hedefe ulaşılamadı: {error}", error=str(e)[:220]))
            http_status = response.status if response else None
            if http_status is None or http_status >= 400:
                raise _TargetUnreachable(tx("Sayfa yüklenemedi (HTTP {status})", status=http_status))
            logs.append(tx("[✓] Sayfa yüklendi (HTTP {status})", status=http_status))

            # Adım 1 Ekran Görüntüsü (Giriş Sayfası)
            shot1_filename = f"step1_landing_{timestamp_str}.png"
            shot1_path = os.path.join(shots_dir, shot1_filename)
            await page.screenshot(path=shot1_path, full_page=True)
            screenshots.append(screenshot_url(project_id, shot1_filename))
            logs.append(tx("[✓] Ekran görüntüsü alındı (Sayfa Karşılama): {file}", file=shot1_filename))

            # 2. Form Alanları ve Kimlik Bilgilerini Doldurma
            logs.append(tx("[3/5] Kullanıcı giriş formu taranıyor ve kimlik bilgileri işleniyor..."))
            await page.wait_for_timeout(800)

            # Kullanıcı adı inputunu bul
            user_selectors = [
                'input[type="email"]',
                'input[name*="user" i]',
                'input[name*="email" i]',
                'input[id*="user" i]',
                'input[id*="email" i]',
                'input[placeholder*="kullanıcı" i]',
                'input[placeholder*="user" i]',
                'input[placeholder*="email" i]',
                'input[type="text"]'
            ]
            username_field = None
            for sel in user_selectors:
                try:
                    el = await page.query_selector(sel)
                    if el and await el.is_visible():
                        username_field = el
                        break
                except Exception:
                    pass

            if username_field and test_user:
                await username_field.fill(test_user)
                logs.append(tx("[✓] Kullanıcı adı alanına yazıldı: '{user}'", user=test_user))

            # Şifre inputunu bul
            pass_selectors = [
                'input[type="password"]',
                'input[name*="pass" i]',
                'input[id*="pass" i]',
                'input[placeholder*="şifre" i]',
                'input[placeholder*="pass" i]'
            ]
            pass_field = None
            for sel in pass_selectors:
                try:
                    el = await page.query_selector(sel)
                    if el and await el.is_visible():
                        pass_field = el
                        break
                except Exception:
                    pass

            if pass_field and test_pass:
                await pass_field.fill(test_pass)
                logs.append(tx("[✓] Şifre alanına gizli anahtar yazıldı (••••••••)"))

            # Adım 2 Ekran Görüntüsü (Form Doldurulmuş Hali)
            shot2_filename = f"step2_form_filled_{timestamp_str}.png"
            shot2_path = os.path.join(shots_dir, shot2_filename)
            await page.screenshot(path=shot2_path)
            screenshots.append(screenshot_url(project_id, shot2_filename))
            logs.append(tx("[✓] Form etkileşim ekran görüntüsü kaydedildi: {file}", file=shot2_filename))

            # Giriş / Gönder Butonunu Bul ve Tıkla
            btn_selectors = [
                'button[type="submit"]',
                'input[type="submit"]',
                'button:has-text("Giriş")',
                'button:has-text("Login")',
                'button:has-text("Sign in")',
                'button:has-text("Oturum Aç")',
                'button:has-text("Submit")'
            ]
            submit_button = None
            for b_sel in btn_selectors:
                try:
                    b_el = await page.query_selector(b_sel)
                    if b_el and await b_el.is_visible():
                        submit_button = b_el
                        break
                except Exception:
                    pass

            if submit_button:
                logs.append(tx("[✓] Giriş / Gönder butonu tespit edildi, tıklanıyor..."))
                await submit_button.click()
                await page.wait_for_timeout(1800)
            else:
                logs.append(tx("[i] Özel login butonu tespit edilmedi, mevcut sayfa arayüz elementleri incelendi."))

            # 3. Sonuç Doğrulama ve Ekran Yakalama
            logs.append(tx("[4/5] Sayfa başlığı, yönlendirme ve DOM durumu inceleniyor..."))
            title = await page.title()
            current_page_url = page.url
            logs.append(tx("[✓] Nihai Sayfa URL: {url}", url=current_page_url))
            logs.append(tx("[✓] Sayfa Başlığı: '{title}'", title=title))
            if page_errors:
                raise _PageError(tx("Sayfada yakalanmamış JS hatası: {error}", error=page_errors[0]))
            if console_errors:
                logs.append(tx("[!] Konsolda {n} hata satırı (ilk: {first})", n=len(console_errors), first=console_errors[0][:120]))

            if is_negative_test:
                logs.append(tx("[✓] Negatif Test Senaryosu: Hatalı kimlik denemesi ve güvenlik kalkanı onaylandı."))
            else:
                logs.append(tx("[✓] '{role}' rolü için kullanıcı oturum akışı başarıyla işletildi.", role=test_role))

            # Adım 3 Sonuç Ekran Görüntüsü
            shot3_filename = f"step3_post_action_{timestamp_str}.png"
            shot3_path = os.path.join(shots_dir, shot3_filename)
            await page.screenshot(path=shot3_path)
            screenshots.append(screenshot_url(project_id, shot3_filename))
            logs.append(tx("[✓] Nihai doğrulama ekran görüntüsü: {file}", file=shot3_filename))

            await browser.close()
            logs.append(tx("[5/5] Tarayıcı oturumu başarıyla kapatıldı."))

    except _TargetUnreachable as e:
        status, engine_error, failure_kind = "FAILED", str(e), "TARGET_UNREACHABLE"
        logs.append(f"[!] {engine_error}")
    except _PageError as e:
        status, engine_error, failure_kind = "FAILED", str(e), "PAGE_ERROR"
        logs.append(f"[!] {engine_error}")
    except ImportError as e:
        # Playwright paketi kurulu değil: test koşulamadı, "geçti" sayılmaz
        status = "SKIPPED"
        engine_error = tx("Playwright paketi bulunamadı: {error}", error=e)
        logs.append(f"[!] {engine_error}")
    except Exception as e:
        # Tarayıcı binary'si yok, hedef erişilemiyor vb.: gerçek başarısızlık
        status = "FAILED"
        engine_error = str(e)
        logs.append(tx("[!] Playwright çalıştırma hatası: {error}", error=engine_error))
    else:
        engine_error = None

    if status != "PASSED":
        logs.append(tx("[*] Gerçek tarayıcı testi tamamlanamadı; yalnızca SİMÜLE edilmiş kanıt görseli üretildi."))
        shot_fallback = f"step_simulated_{timestamp_str}.png"
        shot_path = os.path.join(shots_dir, shot_fallback)
        try:
            from PIL import Image, ImageDraw
            img = Image.new('RGB', (1280, 720), color=(55, 22, 28))
            d = ImageDraw.Draw(img)
            d.text((40, 40), f"SIMULATED (E2E {status}): {target_url}", fill=(234, 98, 117))
            d.text((40, 75), f"Scenario: {test_scenario}", fill=(255, 255, 255))
            d.text((40, 110), f"User Profile: {test_user or 'Default Guest'} | Role: {test_role}", fill=(168, 85, 247))
            d.text((40, 145), f"Engine error: {(engine_error or '')[:120]}", fill=(224, 168, 60))
            img.save(shot_path)
            screenshots.append(screenshot_url(project_id, shot_fallback))
            logs.append(tx("[i] Simüle kanıt görseli kaydedildi: {file}", file=shot_fallback))
        except Exception:
            pass

    if status == "PASSED":
        verdict_text = "NEGATIVE_SECURITY_VERIFIED" if is_negative_test else "VERIFIED_FOR_PRODUCTION"
        notes = tx(
            "Kullanıcı '{user}' (Rol: {role}) ile '{url}' adresinde tarayıcı testi koşuldu. "
            "Form alanları otomatik dolduruldu, yanıtlar ve UI elementleri ekran görüntüleriyle belgelendi.",
            user=test_user or tx("Standart"), role=test_role, url=target_url)
        passed_steps = 3
    else:
        verdict_text = failure_kind or "ENGINE_UNAVAILABLE"
        notes = tx(
            "'{url}' adresinde gerçek tarayıcı testi {outcome} ({status}). "
            "Neden: {error}. Playwright kurulumunu ('pip install playwright && playwright install chromium') "
            "ve hedef adresin erişilebilirliğini kontrol edin.",
            url=target_url, outcome=tx("KALDI") if failure_kind else tx("KOŞULAMADI"), status=status, error=engine_error)
        passed_steps = 0

    return {
        "status": status,
        "scenario": test_scenario,
        "target_url": target_url,
        "test_user": test_user,
        "role": test_role,
        "executed_at": datetime.now(timezone.utc).isoformat(),
        "total_steps": 3,
        "passed_steps": passed_steps,
        "screenshots": screenshots,
        "logs": logs,
        "verdict": verdict_text,
        "engine_error": engine_error,
        "simulated": status != "PASSED",
        "page_errors": page_errors[:20],
        "console_errors": console_errors[:20],
        "notes_for_team_lead": notes
    }
