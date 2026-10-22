"""Generates every screenshot used by docs/USER_MANUAL.md (English UI) into docs/images/manual/.

Usage:  python scripts/capture_manual.py [--url http://127.0.0.1:8123] [--out docs/images/manual]
Prerequisite: a server with a finished demo project (see docs/USER_MANUAL.md, "Reproducing the screenshots"):
FSSC_DRY_RUN=1 + template engine, project language English. Playwright Chromium must be installed.
Each step is independent: a failing step is reported and skipped so the rest still runs.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import re

ICON_ONLY = {"Configuration", "Show/hide conversation", "Select Language", "Close", "Cancel"}


def btn(page, label, exact=True):
    """Button by visible text; icon-only buttons (tooltip names) and regex labels fall back to the accessible name."""
    if isinstance(label, re.Pattern):
        return page.locator("button").filter(has_text=label).or_(page.get_by_role("button", name=label))
    if label in ICON_ONLY:
        return page.get_by_role("button", name=label, exact=exact)
    pat = re.compile(r"^\s*" + re.escape(label) + r"\s*$" if exact else re.escape(label))
    return page.locator("button").filter(has_text=pat)


ONLY: list = []


class Shooter:
    def __init__(self, page, out, url):
        self.p, self.out, self.url, self.ok, self.failed = page, out, url, [], []

    async def shot(self, name, wait=700):
        await self.p.wait_for_timeout(wait)
        await self.p.screenshot(path=os.path.join(self.out, name + ".png"))
        self.ok.append(name)
        print("wrote", name, flush=True)

    async def close_all(self):
        for _ in range(4):
            await self.p.keyboard.press("Escape")
            for label in ("Close", "Cancel"):
                b = btn(self.p, label)
                if await b.count():
                    try:
                        await b.first.click(timeout=1500)
                    except Exception:
                        pass
            await self.p.wait_for_timeout(250)
        # click an empty spot so popovers/menus close
        try:
            await self.p.mouse.click(1300, 990)
        except Exception:
            pass

    async def click(self, label, exact=True, nth=0, role="button"):
        loc = btn(self.p, label, exact)
        await loc.nth(nth).click(timeout=4000)
        await self.p.wait_for_timeout(900)

    async def step(self, name, fn):
        if ONLY and not any(o in name for o in ONLY):
            return
        try:
            await self.p.goto(self.url, wait_until="domcontentloaded", timeout=30000)      # every step starts from a clean page
            await self.p.wait_for_timeout(3000)
            await asyncio.wait_for(fn(), timeout=90)
        except Exception as e:  # keep going; report at the end
            self.failed.append(name)
            try:
                await self.p.screenshot(path=os.path.join(os.environ.get("TEMP", "."), "fail-" + re.sub(r"[^a-z0-9]+", "-", name.lower()) + ".png"))
            except Exception:
                pass
            print("FAILED", name, "->", " ".join(str(e).split())[:300], flush=True)


async def main(url: str, out: str) -> None:
    from playwright.async_api import async_playwright
    os.makedirs(out, exist_ok=True)
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        ctx = await browser.new_context(viewport={"width": 1600, "height": 1000}, device_scale_factor=1)
        await ctx.add_init_script("try { localStorage.setItem('ag_lang', 'en'); } catch (e) {}")
        page = await ctx.new_page()
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(3500)
        page.set_default_timeout(5000)
        S = Shooter(page, out, url)

        # ---- 1. First look -------------------------------------------------------------------------------
        await S.step("overview", lambda: S.shot("01-overview"))

        # ---- 2. Board ------------------------------------------------------------------------------------
        async def board_views():
            await S.click("Board", nth=0)
            await S.shot("02-board-tree")
            for label, name in (("Order", "03-board-order"), ("Sprint", "04-board-sprint"), ("Kanban", "05-board-kanban"), ("Tree", None)):
                await btn(page, label).first.click()
                await page.wait_for_timeout(900)
                if name:
                    await S.shot(name)
        await S.step("board views", board_views)

        async def board_expand():
            await S.click("Board", nth=0)
            await btn(page, "Tree").first.click()
            await page.wait_for_timeout(600)
            for row in await page.locator("text=Platform, infrastructure and documents").all():
                await row.click()
            await page.wait_for_timeout(600)
            await S.shot("06-board-epic-expanded")
        await S.step("board expand", board_expand)

        async def board_filters():
            await S.click("Filters", exact=False)
            await S.shot("07-board-filters")
        await S.step("filters", board_filters)

        async def board_selection():
            await S.click("Selection", exact=False)
            await S.shot("08-board-selection-menu")
        await S.step("selection", board_selection)

        async def board_more():
            await S.click("More", exact=False)
            await S.shot("09-board-more-menu")
        await S.step("more", board_more)

        async def new_issue():
            await S.click("New Issue", exact=False)
            await S.shot("10-new-issue")
        await S.step("new issue", new_issue)

        async def status_pills():
            await S.click("Done", exact=False)
            await S.shot("11-board-done-filter")
        await S.step("done filter", status_pills)

        async def issue_drawer():
            await btn(page, "Board").first.click()
            await page.wait_for_timeout(800)
            await btn(page, re.compile(r"^\s*Done\s")).first.click()      # the Done filter expands the finished stories and tasks
            await page.wait_for_timeout(1200)
            await page.locator("text=#19").first.click()
            await S.shot("12-issue-drawer")
            for tab in ("Comments", "Links", "Attachments", "History", "Work", "Evidence"):
                try:
                    await page.locator("button").filter(has_text=re.compile(tab)).last.click(timeout=2500)
                    await S.shot(f"13-issue-drawer-{tab.lower()}", wait=1000)
                except Exception as e:
                    print("  tab skipped:", tab, " ".join(str(e).split())[:120])
            await page.mouse.click(1579, 18)          # drawer close (X)
        await S.step("issue drawer", issue_drawer)

        async def task_actions():
            await btn(page, "Board").first.click()
            await page.wait_for_timeout(800)
            await btn(page, re.compile(r"^\s*Done\s")).first.click()
            await page.wait_for_timeout(1200)
            await page.locator("button").filter(has_text=re.compile("Inspect")).first.click()
            await S.shot("14-step-inspector", wait=1500)
            await page.keyboard.press("Escape")
            await btn(page, "Close").first.click(timeout=1500) if await btn(page, "Close").count() else None
        await S.step("task inspect", task_actions)

        async def task_history():
            await btn(page, "Board").first.click()
            await page.wait_for_timeout(800)
            await btn(page, re.compile(r"^\s*Done\s")).first.click()
            await page.wait_for_timeout(1200)
            await page.locator("button").filter(has_text=re.compile(r"History \(")).first.click()
            await S.shot("15-task-audit-history", wait=1500)
        await S.step("task history", task_history)

        # ---- 3. Agent mesh -------------------------------------------------------------------------------
        async def mesh():
            await S.click("Agent Mesh", nth=0)
            await S.shot("20-agent-mesh", wait=2500)
            await btn(page, "Show/hide conversation").first.click()
            await S.shot("21-agent-mesh-conversation")
        await S.step("mesh", mesh)

        async def agent_timeline():
            await S.click("Agent Mesh", nth=0)
            await page.wait_for_timeout(1500)
            await page.get_by_text("Senior Backend Developer").first.click()
            await S.shot("23-agent-timeline-drawer", wait=1500)
        await S.step("agent timeline", agent_timeline)

        # ---- 4. Files / Docs -----------------------------------------------------------------------------
        async def files():
            await S.click("Files", nth=0)
            await S.shot("30-files")
            await page.get_by_text("docs", exact=True).first.click()
            await page.wait_for_timeout(600)
            await S.shot("31-files-tree-open")
        await S.step("files", files)

        async def docs():
            await S.click("Docs", nth=0)
            await S.shot("32-docs")
            await page.get_by_text("PRD.md", exact=True).first.click(force=True)
            await S.shot("33-docs-prd")
            await btn(page, "Code").first.click()
            await S.shot("34-docs-code-view")
        await S.step("docs", docs)

        # ---- 5. Deliberation / Questions -----------------------------------------------------------------
        async def delib():
            await S.click("Deliberation", nth=0)
            await S.shot("40-deliberation")
            await btn(page, re.compile("History")).first.click()
            await S.shot("41-deliberation-history")
        await S.step("deliberation", delib)

        async def questions():
            await S.click("Questions", nth=0)
            await S.shot("42-questions")
            await btn(page, re.compile(r"^All")).first.click()
            await S.shot("43-questions-all")
        await S.step("questions", questions)

        # ---- 6. Tests ------------------------------------------------------------------------------------
        async def tests_menu():
            await S.click("Tests", nth=0)
            await S.shot("50-tests-menu")
        await S.step("tests menu", tests_menu)

        async def pw_e2e():
            await S.click("Tests", nth=0)
            await page.get_by_text("Playwright E2E").first.click()
            await S.shot("51-playwright-e2e", wait=1500)
        await S.step("playwright", pw_e2e)

        async def test_mgmt():
            await S.click("Tests", nth=0)
            await page.get_by_text("Test Management").first.click()
            await S.shot("52-test-management", wait=1500)
            for tab in ("Cases", "Runs", "Traceability", "E2E scenarios", "Test plan"):
                try:
                    await page.locator("button").filter(has_text=re.compile(rf"^\s*{tab}\s*$")).first.click(timeout=2500)
                    await S.shot("53-test-management-" + re.sub(r"[^a-z0-9]+", "-", tab.lower()), wait=1000)
                except Exception as e:
                    print("  tab skipped:", tab, " ".join(str(e).split())[:100])
        await S.step("test management", test_mgmt)

        # ---- 7. Reports ----------------------------------------------------------------------------------
        async def reports():
            await S.click("Reports", nth=0)
            await S.shot("60-reports", wait=1500)
            await page.mouse.wheel(0, 900)
            await S.shot("61-reports-scrolled")
            await btn(page, "Sprint").last.click()
            await S.shot("62-reports-sprint")
        await S.step("reports", reports)

        # ---- 8. Settings menu and dialogs ----------------------------------------------------------------
        async def settings_menu():
            await S.click("Settings", nth=0)
            await S.shot("70-settings-menu")
        await S.step("settings menu", settings_menu)

        async def dialog_from_settings(item, name, wait=1500, extra=None):
            async def run():
                await S.click("Settings", nth=0)
                await page.get_by_text(item, exact=False).first.click()
                await S.shot(name, wait=wait)
                if extra:
                    await extra()
            return run

        for item, name in (
            ("Project settings", "71-project-settings"),
            ("Client Vault", "72-client-vault"),
            ("Decisions", "73-decisions"),
            ("Runs", "74-runs"),
            ("Add Agent", "75-add-agent"),
            ("Management Center", "76-management-center"),
            ("Model:", "77-model-switcher"),
            ("Claude Bridge", "78-claude-bridge"),
            ("Live Telemetry", "79-live-telemetry"),
        ):
            await S.step(name, await dialog_from_settings(item, name))

        # ---- 9. Top bar ----------------------------------------------------------------------------------
        async def project_switcher():
            await page.locator("header button, button").filter(has_text="inventory-app").first.click()
            await S.shot("80-project-switcher")
        await S.step("project switcher", project_switcher)

        async def approval():
            await btn(page, re.compile("Automatic")).first.click()
            await S.shot("81-approval-mode")
        await S.step("approval", approval)

        async def notifications():
            await btn(page, re.compile("Notification")).first.click()
            await S.shot("82-notification-center")
        await S.step("notifications", notifications)

        async def language():
            await page.locator('button[title="Select Language"]').first.click()
            await S.shot("83-language-switcher")
        await S.step("language", language)

        async def search():
            await page.get_by_placeholder(re.compile("Search issue")).fill("login")
            await S.shot("84-search", wait=1200)
            await page.get_by_placeholder(re.compile("Search issue")).fill("")
        await S.step("search", search)

        async def config_menu():
            await btn(page, "Configuration").first.click()
            await S.shot("85-configuration-menu")
        await S.step("configuration", config_menu)

        # ---- 10. Bottom dock -----------------------------------------------------------------------------
        async def dock():
            await btn(page, re.compile("Timeline")).first.click()
            await S.shot("90-dock-timeline", wait=1200)
            await btn(page, re.compile("Timeline")).first.click()
            await btn(page, re.compile("Live Sprint")).first.click()
            await S.shot("91-dock-live-sprint", wait=1200)
        await S.step("dock", dock)

        # ---- 11. Extra detail shots ----------------------------------------------------------------------
        async def settings_item(item):
            await btn(page, "Settings").first.click()
            await page.wait_for_timeout(500)
            await page.get_by_text(item, exact=False).first.click()
            await page.wait_for_timeout(1500)

        async def tabs_in_dialog(item, prefix, tabs):
            await settings_item(item)
            for tab in tabs:
                try:
                    await page.locator("button").filter(has_text=re.compile(rf"^\s*{tab}")).first.click(timeout=2500)
                    await S.shot(f"{prefix}-{re.sub(r'[^a-z0-9]+', '-', tab.lower()).strip('-')}", wait=1200)
                except Exception as e:
                    print("  tab skipped:", tab, " ".join(str(e).split())[:100])

        async def mgmt_tabs():
            await tabs_in_dialog("Management Center", "76-management-center", ("Work plan", "Learning", "Claude activity"))
        await S.step("management tabs", mgmt_tabs)

        async def bridge_tabs():
            await tabs_in_dialog("Claude Bridge", "78-claude-bridge", ("Start & Connect", "Interaction log"))
        await S.step("bridge tabs", bridge_tabs)

        async def scrolled(item, name, amounts=(700,)):
            await settings_item(item)
            await page.mouse.move(800, 500)
            for i, amount in enumerate(amounts):
                await page.mouse.wheel(0, amount)
                await S.shot(name + ("" if i == 0 else f"-{i + 1}"))

        await S.step("settings scrolled", lambda: scrolled("Project settings", "71-project-settings-scrolled", (700, 900)))
        await S.step("model scrolled", lambda: scrolled("Model:", "77-model-switcher-scrolled", (900,)))

        async def budget_page():
            await page.goto(url.rstrip("/") + "/budget", wait_until="domcontentloaded", timeout=30000)
            await S.shot("86-budget-page", wait=1200)
        await S.step("budget page", budget_page)

        async def add_project():
            await page.locator("button").filter(has_text="inventory-app").first.click()
            await page.wait_for_timeout(500)
            await btn(page, re.compile(r"Add New")).first.click()
            await S.shot("87-add-project", wait=1200)
        await S.step("add project", add_project)

        async def add_goal():
            await btn(page, re.compile("Add goal")).first.click()
            await S.shot("88-add-goal")
        await S.step("add goal", add_goal)

        async def agent_interactions():
            await btn(page, "Agent Mesh").first.click()
            await page.wait_for_timeout(1500)
            await page.get_by_text("Senior Backend Developer").first.click()
            await page.wait_for_timeout(1200)
            await btn(page, re.compile(r"Interactions")).first.click()
            await S.shot("24-agent-timeline-interactions", wait=1000)
        await S.step("agent interactions", agent_interactions)

        async def sprint_expanded():
            await btn(page, "Board").first.click()
            await btn(page, "Sprint").first.click()
            await page.wait_for_timeout(800)
            await page.get_by_text("Sprint 4 · CLOSED").first.click()
            await S.shot("04b-board-sprint-expanded", wait=1000)
        await S.step("sprint expanded", sprint_expanded)

        await browser.close()
        print(f"\n{len(S.ok)} screenshots, {len(S.failed)} failed steps: {S.failed}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8123")
    ap.add_argument("--out", default=os.path.join(os.path.dirname(__file__), "..", "docs", "images", "manual"))
    ap.add_argument("--only", default="", help="comma-separated step-name fragments to (re)capture")
    a = ap.parse_args()
    ONLY[:] = [x for x in a.only.split(",") if x]
    asyncio.run(main(a.url, os.path.abspath(a.out)))
