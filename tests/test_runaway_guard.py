"""Kaçak sprint döngüsü korumaları: devre kesici, açık/tekrar eden iş tekrarını önleme, karma (#) yönlendiricide E2E adresi."""
import asyncio

from server import pipeline as P
from server import sprint as SP
from server.e2e_scenarios import _PlaywrightDriver


class _Hub:
    def __init__(self, sprints, issues=None):
        self.sprint_state = {"sprints": sprints}
        self.jira_issues = issues or {}

    def mark_dirty(self):
        pass


def _sprint(n, goal, items, status="CLOSED", e2e=None):
    return {"sprint_number": n, "status": status, "goal": goal, "committed_issue_ids": items, "dod": {"e2e": {"status": e2e}} if e2e else {}}


def test_repeat_check_flags_same_goal_small_sprints():
    hub = _Hub([_sprint(1, "E2E hatasını çöz (JIRA-10)", ["a"]), _sprint(2, "E2E hatasını çöz (JIRA-12)", ["b"]), _sprint(3, "E2E hatasını çöz (JIRA-14)", ["c"])])
    assert SP.repeat_check(hub, 3)


def test_repeat_check_ignores_normal_progress():
    hub = _Hub([_sprint(1, "kimlik", ["a", "b", "c"]), _sprint(2, "keşif", ["d", "e"]), _sprint(3, "katılım", ["f"])])
    assert SP.repeat_check(hub, 3) is None


def test_repeat_check_flags_three_failed_e2e():
    hub = _Hub([_sprint(1, "a", ["1", "2", "3"], e2e="FAILED"), _sprint(2, "b", ["4", "5", "6"], e2e="FAILED"), _sprint(3, "c", ["7", "8", "9"], e2e="FAILED")])
    assert "E2E" in SP.repeat_check(hub, 3)


def _issue(i, title, status):
    return {"id": f"JIRA-{i}", "order": i, "title": title, "status": status, "kind": "task"}


def test_open_duplicate_matches_same_finding_across_sprints():
    hub = _Hub([], {"JIRA-1": _issue(1, "E2E kaldı (sprint 44): SCENARIO_FAILED", "BACKLOG")})
    dup = P._open_duplicate(hub, {"title": "E2E kaldı (sprint 45): SCENARIO_FAILED"}, "ARCHITECT")
    assert dup and dup["id"] == "JIRA-1"


def test_repeatedly_closed_finding_is_not_reopened():
    hub = _Hub([], {"JIRA-1": _issue(1, "E2E kaldı (sprint 44): SCENARIO_FAILED", "DONE"), "JIRA-2": _issue(2, "E2E kaldı (sprint 45): SCENARIO_FAILED", "DONE")})
    assert P._open_duplicate(hub, {"title": "E2E kaldı (sprint 46): SCENARIO_FAILED"}, "ARCHITECT")


def test_manager_and_designer_work_is_exempt():
    hub = _Hub([], {"JIRA-1": _issue(1, "Ekran uyumu: Giriş Yap (/giris)", "BACKLOG")})
    assert P._open_duplicate(hub, {"title": "Ekran uyumu: Giriş Yap (/giris)"}, "MANAGER") is None
    assert P._open_duplicate(hub, {"title": "Ekran uyumu: Giriş Yap (/giris)"}, "DESIGNER") is None


def test_different_acceptance_criteria_are_not_merged():
    hub = _Hub([], {"JIRA-1": _issue(1, "AC-04 için test/E2E senaryosu yaz", "BACKLOG")})
    assert P._open_duplicate(hub, {"title": "AC-05 için test/E2E senaryosu yaz"}, "ARCHITECT") is None


class _FakePage:
    def __init__(self):
        self.visited = []

    async def goto(self, url, **kw):
        self.visited.append(url)


def test_hash_router_turns_path_into_fragment():
    page = _FakePage()
    drv = _PlaywrightDriver(page)
    drv.hash_router = True
    asyncio.run(drv.goto("http://127.0.0.1:5173/giris"))
    asyncio.run(drv.goto("http://127.0.0.1:5173/"))
    assert page.visited == ["http://127.0.0.1:5173/#/giris", "http://127.0.0.1:5173/"]


def test_path_router_is_left_alone():
    page = _FakePage()
    drv = _PlaywrightDriver(page)
    asyncio.run(drv.goto("http://127.0.0.1:5173/giris"))
    assert page.visited == ["http://127.0.0.1:5173/giris"]
