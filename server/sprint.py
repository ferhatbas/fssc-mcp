"""Sprint kipi (F3, belge §7.2, §7.5-§7.9, §10.1-§10.3): durum, kapasite, seçim, taahhüt, taşıma, metrik.

Bu modül hub durumu üzerinde çalışan mantıktır; koşu adımlarını yürüten kod `server/sprint_flow.py`'dedir.
`sprint.enabled=false` iken hiçbir kod yolu buraya girmez (sabit 1-10 akışı aynen çalışır).
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from .i18n import translate as tx, N_, variants

WORK_TYPES = ("SCAFFOLD", "FEATURE", "DESIGN", "TEST", "E2E_SCENARIO", "DEVOPS", "DOCS", "BUG", "IMPROVEMENT", "REFACTOR", "TEST_DESIGN", "SECURITY_TEST", "PERF_SMOKE")
DEFAULT_SPRINT: Dict[str, Any] = {"enabled": True, "max_tasks": 8, "commit_approval": "auto", "auto_chain": True,
                                  "carry_over_limit": 2, "max_sprints": 20, "wip_limit": 0,      # wip_limit 0 = uyarı kapalı (G5)
                                  "test_share_pct": 50, "ac_test_batch": 4, "feature_share_pct": 50,
                                  "min_tasks": 0, "ui_min_tasks": 2, "no_tests": False}      # min_tasks: sprint kapasitesinin tabanı (hız ortalaması düşse de altına inmez; 0 = kapalı)      # test işlerinin sprint kapasitesindeki azami payı (%); PO ret görevlerinin AC gruplama boyutu
COMMIT_MODES = ("manual", "timeout_default", "auto")
PLAN_BASE = 1000                      # akış adımlarının (plan/kapanış) sanal sırası; Jira maddesi sırası değildir
TASK_ROLES = {"BACKEND_DEV", "FRONTEND_DEV", "DESIGNER", "DEVOPS", "QA", "ARCHITECT", "DOCUMENTOR"}   # E2E_TESTER ve SCM görev alamaz (A16)
DEFAULT_ROLE = {"SCAFFOLD": "BACKEND_DEV", "FEATURE": "BACKEND_DEV", "TEST": "QA", "E2E_SCENARIO": "QA", "DEVOPS": "DEVOPS",
                "DOCS": "DOCUMENTOR", "DESIGN": "DESIGNER", "BUG": "BACKEND_DEV", "IMPROVEMENT": "BACKEND_DEV", "REFACTOR": "BACKEND_DEV",
                "TEST_DESIGN": "QA", "SECURITY_TEST": "QA", "PERF_SMOKE": "QA"}
CARRY_REASONS = ("FIX_LIMIT", "UAT_OVERFLOW", "NOT_STARTED", "TOKEN_LIMIT", "E2E")
RESCOPE_REASONS = ("FIX_LIMIT", "TOKEN_LIMIT")
PRIORITY_RANK = {"P0": 0, "P1": 1, "P2": 2}


def plan_order(n: int) -> int:
    return PLAN_BASE + 6 * int(n)


def close_order(n: int) -> int:
    return PLAN_BASE + 6 * int(n) + 1


def meeting_order(n: int, mtype: str) -> int:
    """Toplantı adımlarının sanal sırası: planlama/kickoff +2, review-retro +3, arch-review/adhoc +5."""
    return PLAN_BASE + 6 * int(n) + {"review-retro": 3, "arch-review": 5, "adhoc": 5}.get(mtype, 2)


def review_order(n: int) -> int:
    """ARCHITECT kod ve mimari gözden geçirme adımı (F6)."""
    return PLAN_BASE + 6 * int(n) + 4


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sanitize_sprint_settings(raw: Any, fallback: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Geçersiz değer `fallback`te (yoksa varsayılanda) kalan değeri korur; bilinmeyen anahtarlar atılır."""
    raw = raw if isinstance(raw, dict) else {}
    out = {**DEFAULT_SPRINT, **{k: v for k, v in (fallback or {}).items() if k in DEFAULT_SPRINT}}

    def num(key: str, lo: int, hi: int):
        try:
            out[key] = max(lo, min(int(raw.get(key, out[key])), hi))
        except (TypeError, ValueError):
            pass

    out["enabled"] = bool(raw.get("enabled", out["enabled"]))
    out["auto_chain"] = bool(raw.get("auto_chain", out["auto_chain"]))
    out["no_tests"] = bool(raw.get("no_tests", out.get("no_tests", False)))          # geçici: test yazımı/test işi durur (yalnızca mevcut testler koşar)
    if raw.get("commit_approval") in COMMIT_MODES:
        out["commit_approval"] = raw["commit_approval"]
    num("max_tasks", 1, 50)
    num("carry_over_limit", 0, 10)
    num("max_sprints", 1, 100)
    num("wip_limit", 0, 20)
    num("test_share_pct", 10, 100)
    num("ac_test_batch", 1, 10)
    num("feature_share_pct", 0, 100)
    num("min_tasks", 0, 50)
    num("ui_min_tasks", 0, 20)
    out["min_tasks"] = min(out["min_tasks"], out["max_tasks"])          # taban tavanı aşamaz
    return out


def cfg(hub) -> Dict[str, Any]:
    return sanitize_sprint_settings((hub.get_settings() or {}).get("sprint"))


def enabled(hub) -> bool:
    return bool(cfg(hub)["enabled"])


# ---------------------------------------------------------------------------
# Durum (`.fs-workspace/sprint_state.json`)
# ---------------------------------------------------------------------------
def ensure_state(hub) -> Dict[str, Any]:
    st = getattr(hub, "sprint_state", None)
    if not isinstance(st, dict) or not st:
        st = {}
    st.setdefault("schema_version", 1)
    st.setdefault("project_status", "ACTIVE")
    st.setdefault("current_sprint", None)
    st.setdefault("sprints", [])
    st.setdefault("pending_intake", None)
    st.setdefault("ac_seq", 0)
    st.setdefault("acs", {})
    st.setdefault("meeting_seq", {})        # F4: gün başına toplantı sayacı (M-YYYYMMDD-n)
    st.setdefault("dec_seq", 0)             # F4: DEC-n
    st.setdefault("meetings", [])           # F4: toplantı kayıtları (tutanak bunlardan üretilir)
    st.setdefault("meeting_commitments", {})
    st.setdefault("decisions", [])
    hub.sprint_state = st
    _heal_acs(hub, st)
    _close_superseded(hub, st)
    return st


def _norm_goal(goal: Any) -> str:
    import re as _re
    return _re.sub(r"\d+", "#", " ".join(str(goal or "").lower().split()))


def repeat_check(hub, n: int, window: int = 3) -> Optional[str]:
    """Devre kesici: son `window` sprint aynı (rakamları yok sayılmış) hedefle, her biri en çok 2 işle kapandıysa (ya da son N sprintte aynı E2E hatası sürdüyse)
    sistem aynı işi tekrar tekrar planlıyor demektir. Açıklama metnini döner (yoksa None)."""
    sprints = [s for s in ensure_state(hub).get("sprints", []) if s.get("sprint_number", 0) <= n]
    last = sorted(sprints, key=lambda x: x["sprint_number"])[-window:]
    if len(last) < window:
        return None
    if len({_norm_goal(x.get("goal")) for x in last}) == 1 and all(len(x.get("committed_issue_ids") or []) <= 2 for x in last):
        return f"Sprint {last[0]['sprint_number']}-{last[-1]['sprint_number']}: aynı hedef ({str(last[-1].get('goal') or '')[:100]}) {window} sprint boyunca tekrarlandı"
    if all(((x.get("dod") or {}).get("e2e") or {}).get("status") == "FAILED" for x in last):
        return f"Sprint {last[0]['sprint_number']}-{last[-1]['sprint_number']}: E2E {window} sprint art arda kaldı"
    return None


def _close_superseded(hub, st: Dict[str, Any]) -> None:
    """Daha yeni bir sprint çalışırken (IN_PROGRESS) eskide takılı kalan sprintler (IN_REVIEW / BLOCKED / COMMITTED) kapatılır:
    bitmeyen işleri zaten yeni sprint taşıdı; açık kalan eski sprint "güncel sprint" gösterimini ve süzgeçleri yanıltıyordu."""
    sprints = st.get("sprints") or []
    running = [s["sprint_number"] for s in sprints if s.get("status") == "IN_PROGRESS"]
    if not running:
        return
    newest = max(running)
    issues = getattr(hub, "jira_issues", {}) or {}
    for sp in sprints:
        if sp.get("sprint_number", 0) >= newest or sp.get("status") not in ("IN_REVIEW", "BLOCKED", "COMMITTED", "REVIEW"):
            continue
        left = [i for i in sp.get("committed_issue_ids") or [] if (issues.get(i) or {}).get("status") != "DONE" and (issues.get(i) or {}).get("sprint") == sp["sprint_number"]]
        for iid in left:                                   # hâlâ bu sprint'e bağlı bitmemiş iş backlog'a döner (başka sprint'te olanlara dokunulmaz)
            issues[iid]["sprint"] = None
            if issues[iid].get("status") in ("SELECTED_FOR_DEV", "IN_PROGRESS"):
                issues[iid]["status"] = "BACKLOG"
        sp["status"] = "CLOSED"
        sp["closed_at"] = sp.get("closed_at") or now()
        sp["close_reason"] = "SUPERSEDED"
        sp["superseded_by"] = newest
        sp["carried_back"] = left
        sp.pop("blocked", None)
        hub.mark_dirty()


def _heal_acs(hub, st: Dict[str, Any]) -> None:
    """Kabul kriteri sicili (`acs`) boşalmış/eksikse (durum kaybı, eski sürüm) kriter metinleri hikâyelerden geri kurulur: hikâyenin `ac_refs` listesi `acceptance_criteria`
    listesiyle SONDAN hizalanır (hikâye güncellenince yeni kriterler listenin sonuna eklenir). Ajan ve PO kriter kimliğini metniyle görür; kullanıcıdan metin istenmez."""
    issues = getattr(hub, "jira_issues", None) or {}
    stamp = (len(issues), sum(len(i.get("ac_refs") or []) for i in issues.values() if str(i.get("kind", "")).lower() == "story"))
    if st.get("_acs_stamp") == list(stamp):
        return
    acs = st.setdefault("acs", {})
    for i in issues.values():
        if str(i.get("kind", "")).lower() != "story" or i.get("deleted"):
            continue
        refs, texts = list(i.get("ac_refs") or []), [str(t) for t in (i.get("acceptance_criteria") or [])]
        if not refs or not texts or len(texts) > len(refs):
            continue
        for ref, text in zip(refs[-len(texts):], texts):
            cur = acs.get(ref)
            if not cur or not cur.get("text"):
                acs[ref] = {**(cur or {}), "text": text, "story": i.get("id")}
    st["_acs_stamp"] = list(stamp)


def ac_lookup(hub, ids: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """Kabul kriterlerinin kimlik → metin dökümü (hikâye bilgisiyle). `ids` boşsa etkin koşunun geçerli adımındaki işin kriterleri, o da yoksa sicilin tamamı."""
    st = ensure_state(hub)
    acs = st.get("acs") or {}
    wanted = [str(a).strip().upper() for a in (ids or []) if str(a).strip()]
    if not wanted:
        run = hub.active_run_for(hub.active_project_id) if hasattr(hub, "active_run_for") else None
        cur = run.current_step if run is not None else None
        issue = (hub.jira_issues.get(cur.issue_id) if cur is not None else None) or {}
        wanted = [str(a) for a in (issue.get("ac_refs") or [])] or sorted(acs, key=lambda a: int(re.sub(r"\D", "", a) or 0))
    out = []
    for ac in wanted:
        e = acs.get(ac) or {}
        story = hub.jira_issues.get(e.get("story") or "") or {}
        out.append({"ac": ac, "text": e.get("text") or "", "status": e.get("status"), "story": story.get("key") or e.get("story"), "story_title": story.get("title")})
    return out


def ac_text(hub, ac_id: str) -> str:
    """Bir kabul kriterinin metni (sicilden; yoksa hikâyelerden geri kurulur); bulunamazsa ''."""
    return str(((ensure_state(hub).get("acs") or {}).get(str(ac_id)) or {}).get("text") or "")


def get_sprint(hub, n: int) -> Optional[Dict[str, Any]]:
    return next((s for s in ensure_state(hub)["sprints"] if s["sprint_number"] == int(n)), None)


def last_sprint_number(hub) -> int:
    return max([s["sprint_number"] for s in ensure_state(hub)["sprints"]] or [0])


def new_sprint(hub, n: int, goal: str) -> Dict[str, Any]:
    sp = {
        "sprint_number": n, "status": "PLANNING", "goal": goal, "planned_at": now(), "committed_at": None, "started_at": None,
        "review_started_at": None, "closed_at": None, "commitment_ref": None,
        "commit_approval": {"mode": cfg(hub)["commit_approval"], "by": None}, "commit_approved": False,
        "run_ids": [], "committed_issue_ids": [], "completed_issue_ids": [], "carried_over": [], "scope_changes": [],
        "metrics": None, "meetings": {"planning": None, "review_retro": None}, "git_tag": None, "blocked": None,
    }
    ensure_state(hub)["sprints"].append(sp)
    ensure_state(hub)["current_sprint"] = n
    return sp


def set_sprint_status(hub, sp: Dict[str, Any], status: str, **fields: Any) -> None:
    sp["status"] = status
    sp.update(fields)
    ensure_state(hub)["current_sprint"] = sp["sprint_number"]
    hub.mark_dirty()


# ---------------------------------------------------------------------------
# Kimlikler (A3): task_key / UAT-nn proje genelinde artar
# ---------------------------------------------------------------------------
def next_key(hub, prefix: str) -> str:
    n = 0
    rx = re.compile(rf"^{re.escape(prefix)}-(\d+)$")
    for i in hub.jira_issues.values():
        m = rx.match(str(i.get("task_key") or ""))
        if m:
            n = max(n, int(m.group(1)))
    return f"{prefix}-{n + 1:02d}"


def next_ac_id(hub) -> str:
    st = ensure_state(hub)
    st["ac_seq"] = int(st.get("ac_seq", 0)) + 1
    return f"AC-{st['ac_seq']}"


# ---------------------------------------------------------------------------
# Kapasite ve seçim (§7.6)
# ---------------------------------------------------------------------------
def capacity(hub) -> Tuple[int, str]:
    c = cfg(hub)
    closed = [s for s in ensure_state(hub)["sprints"] if s["status"] == "CLOSED" and s.get("metrics")]
    if not closed:
        return c["max_tasks"], tx("İlk sprint: sprint.max_tasks = {max_tasks}", max_tasks=c["max_tasks"])
    last = closed[-3:]
    avg = sum(len(s["completed_issue_ids"]) for s in last) / len(last)
    cap = max(1, min(c["max_tasks"], int(avg) + 1))
    if c["min_tasks"] and cap < c["min_tasks"]:
        return c["min_tasks"], tx("Son {n} sprintte tamamlanan ortalama {avg:.1f} (hız kapasitesi {cap}); sprint.min_tasks tabanı = {min_tasks}", n=len(last), avg=avg, cap=cap, min_tasks=c["min_tasks"])
    return cap, tx("Son {n} sprintte tamamlanan ortalama {avg:.1f}; min({max_tasks}, {avg_int} + 1) = {cap}", n=len(last), avg=avg, max_tasks=c["max_tasks"], avg_int=int(avg), cap=cap)


def is_frozen(hub, issue: Dict[str, Any]) -> bool:
    """Kapatılmış sprintin maddesi yeni yüklemeyle değişmez (karar 19c)."""
    n = issue.get("closed_in_sprint")
    return bool(n and (get_sprint(hub, n) or {}).get("status") == "CLOSED")


def _eligible(hub, i: Dict[str, Any]) -> bool:
    return (str(i.get("kind", "")).lower() == "task" and i.get("status") == "BACKLOG" and not i.get("sprint")
            and not i.get("needs_rescope") and not i.get("deleted"))


def candidates(hub, sprint_number: Optional[int] = None) -> List[Dict[str, Any]]:
    """Seçilebilir backlog işleri. Yöneticinin bir sprinte sabitlediği iş (`planned_sprint`) yalnızca o sprintte aday olur."""
    out = []
    no_tests = bool(cfg(hub).get("no_tests"))
    for i in hub.jira_issues.values():
        if not _eligible(hub, i):
            continue
        if no_tests and is_test_work(i):
            continue                       # test yazımı geçici olarak durduruldu: test işleri sprinte alınmaz
        pin = i.get("planned_sprint")
        if pin and pin != sprint_number:
            continue
        from . import goals as GL
        if not GL.in_scope(hub, i):
            continue                       # açık yönetici hedefi var: hedef dışı iş sprinte alınmaz
        out.append(i)
    return out


def _rank(i: Dict[str, Any]) -> Tuple[int, int, int, int]:
    """Sıra anahtarı: sabitlenmiş işler önce, sonra taşınanlar/hatalar/iyileştirmeler/backlog; aynı grupta yönetici sırası (`manual_rank`) önce gelir."""
    manual = i.get("manual_rank")
    manual_key = int(manual) if isinstance(manual, int) else 10**9
    pinned = bool(i.get("planned_sprint"))
    carried = int((i.get("carry_over") or {}).get("count", 0) or 0) > 0
    if i.get("expedite") == "next_sprint":
        group = -2                       # yönetici "sıradaki sprintin başı" dedi: sabitlenmişlerden de önce
    elif pinned:
        group = -1
    elif carried:
        group = 0
    elif i.get("work_type") == "BUG" and i.get("priority") == "P0":
        group = 1
    elif i.get("origin") in ("UAT", "PO") or i.get("work_type") == "IMPROVEMENT":
        group = 2
    else:
        group = 3
    return (group, manual_key, PRIORITY_RANK.get(str(i.get("priority") or "P1"), 1), int(i.get("order", 0) or 0))


def execution_order(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Sprint içi YÜRÜTME sırası: yönetici önceliği (öne alınan, sabitlenen), taşınanlar, P0 hatalar... `_rank` sırasıyla; bağımlı iş bağımlılığından sonra gelir.
    (Seçim ile sıra ayrıdır: toplantı kararı ya da seçim sırası, öne alınan işi sprintin sonuna atmamalı.)"""
    ranked = sorted(items, key=_rank)
    by_id = {i["id"]: i for i in ranked}
    out: List[Dict[str, Any]] = []
    placed: set = set()

    def place(i: Dict[str, Any]) -> None:
        if i["id"] in placed:
            return
        placed.add(i["id"])
        for d in i.get("depends_on") or []:
            if d in by_id:
                place(by_id[d])
        out.append(i)
    for i in ranked:
        place(i)
    return out


TEST_TYPES = ("TEST", "E2E_SCENARIO", "TEST_DESIGN", "SECURITY_TEST", "PERF_SMOKE")


def is_test_work(i: Dict[str, Any]) -> bool:
    return i.get("work_type") in TEST_TYPES


QUALITY_TYPES = ("REFACTOR", "IMPROVEMENT", *TEST_TYPES)


def is_quality_work(i: Dict[str, Any]) -> bool:
    """Ürün özelliği olmayan kalite/süreç işi (test, refactor, iyileştirme, P0 olmayan hata). Yöneticinin öne aldığı/sabitlediği iş sayılmaz (yönetici kararı)."""
    if i.get("expedite") or i.get("planned_sprint"):
        return False
    wt = i.get("work_type")
    if wt == "BUG":
        return i.get("priority") != "P0"
    return wt in QUALITY_TYPES


def is_feature_work(i: Dict[str, Any]) -> bool:
    return i.get("work_type") in ("FEATURE", "SCAFFOLD", "DESIGN", "DEVOPS", "DOCS", None, "")


def quality_limit(hub, cap: int) -> int:
    """Kalite/süreç işlerine ayrılabilecek azami madde sayısı: kapasitenin `feature_share_pct` payı özellik işine ayrılır (en az 1 yer özellik için)."""
    share = cfg(hub)["feature_share_pct"]
    return max(0, cap - (cap * share + 99) // 100) if share else cap


def test_cap(hub, cap: int) -> int:
    """Bir sprintte test işlerine ayrılabilecek azami madde sayısı (özellik işi için yer kalsın; en az 1)."""
    return max(1, cap * cfg(hub)["test_share_pct"] // 100)


def _is_ui(i: Dict[str, Any]) -> bool:
    return str(i.get("assignee") or "").upper() == "FRONTEND_DEV"


def _ensure_ui_work(hub, pool: List[Dict[str, Any]], chosen: List[Dict[str, Any]], chosen_ids: set, done: set, cap: int) -> None:
    """Backend işleri sprintleri doldurup arayüz işini sonsuza dek bekletmesin: backlog'da hazır frontend işi varsa sprintte en az `ui_min_tasks` tane yer alır.
    Eksik kalan yer, sıralamada en arkadaki frontend olmayan ve P0 olmayan işin yerine geçer (taşınan/P0 iş çıkarılmaz)."""
    want = int(cfg(hub).get("ui_min_tasks") or 0)
    have = sum(1 for c in chosen if _is_ui(c))
    if want <= have:
        return
    ready = [i for i in pool if _is_ui(i) and i["id"] not in chosen_ids and all(d in done or d in chosen_ids for d in (i.get("depends_on") or []))]
    for cand in ready[:want - have]:
        victim = next((c for c in reversed(chosen) if not _is_ui(c) and c.get("priority") != "P0" and not c.get("carry_over")), None)
        if victim is None and len(chosen) >= cap:
            break                                          # kapasite dolu ve çıkarılabilir iş yok: sprint kapasiteyi aşmaz
        if victim is not None:
            chosen.remove(victim)
            chosen_ids.discard(victim["id"])
        chosen.append(cand)
        chosen_ids.add(cand["id"])


def select_items(hub, cap: int, sprint_number: Optional[int] = None) -> Tuple[List[Dict[str, Any]], List[Dict[str, str]]]:
    """§7.6 seçim sırası: taşınanlar, yüksek öncelikli hatalar, UAT iyileştirmeleri, bağımlılığı bozmadan kalan backlog.
    Test işleri kapasitenin `test_share_pct` payını aşmaz (özellik hikâyeleri test işlerinin arkasında kalmasın); özellik adayı kalmadıysa boş yer testle dolar."""
    pool = sorted(candidates(hub, sprint_number), key=_rank)
    done = {k for k, v in hub.jira_issues.items() if v.get("status") == "DONE"}
    chosen: List[Dict[str, Any]] = []
    chosen_ids: set = set()
    limit = test_cap(hub, cap)
    qlimit = quality_limit(hub, cap)

    def fill(respect_limit: bool) -> None:
        progress = True
        while progress and len(chosen) < cap:
            progress = False
            for i in pool:
                if i["id"] in chosen_ids:
                    continue
                if respect_limit and is_test_work(i) and sum(1 for c in chosen if is_test_work(c)) >= limit:
                    continue
                if respect_limit and is_quality_work(i):
                    feats = sum(1 for c in chosen if is_feature_work(c))
                    reserved = max(0, (cap - qlimit) - feats)         # özellik için ayrılmış ama henüz dolmamış yer
                    if sum(1 for c in chosen if is_quality_work(c)) >= qlimit or len(chosen) >= cap - reserved:
                        continue              # özellik hikâyeleri test/refactor/iyileştirme yığınının arkasında kalmasın
                if all(d in done or d in chosen_ids for d in (i.get("depends_on") or [])):
                    chosen.append(i)
                    chosen_ids.add(i["id"])
                    progress = True
                    break

    fill(True)
    fill(False)
    _ensure_ui_work(hub, pool, chosen, chosen_ids, done, cap)
    chosen = execution_order(chosen)
    out = []
    for i in pool:
        if i["id"] not in chosen_ids:
            blocked = [d for d in (i.get("depends_on") or []) if d not in done and d not in chosen_ids]
            out.append({"issue_id": i["id"], "reason": ("BAĞIMLILIK: " + ", ".join(blocked)) if blocked else "KAPASİTE"})
    return chosen, out


def reorder_backlog(hub, issue_id: str, direction: str, sprint_number: Optional[int] = None) -> bool:
    """Backlog sırasında maddeyi bir yukarı/aşağı taşır: tüm adayların `manual_rank` değerini güncel sıraya göre yeniden yazar."""
    pool = sorted(candidates(hub, sprint_number), key=_rank)
    ids = [i["id"] for i in pool]
    if issue_id not in ids or direction not in ("up", "down"):
        return False
    k = ids.index(issue_id)
    j = k - 1 if direction == "up" else k + 1
    if j < 0 or j >= len(ids):
        return False
    ids[k], ids[j] = ids[j], ids[k]
    for rank, iid in enumerate(ids):
        hub.jira_issues[iid]["manual_rank"] = rank
    return True


def goal_for(hub, items: List[Dict[str, Any]], n: int) -> str:
    titles: List[str] = []
    for i in items:
        parent = hub.jira_issues.get(i.get("parent_id") or "") or {}
        t = parent.get("title") if str(parent.get("kind", "")).lower() == "story" else None
        t = t or i.get("title")
        if t and t not in titles:
            titles.append(str(t))
    return tx("Sprint {n}: ", n=n) + "; ".join(titles[:3]) + ("…" if len(titles) > 3 else "")


# ---------------------------------------------------------------------------
# Belgeler
# ---------------------------------------------------------------------------
def _write(project_dir: str, rel: str, content: str, overwrite: bool = True) -> Optional[str]:
    if not project_dir or not os.path.isdir(project_dir):
        return None
    path = os.path.join(project_dir, *rel.split("/"))
    if os.path.exists(path) and not overwrite:
        return rel
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(content)
    return rel


def commitment_document(hub, sp: Dict[str, Any], items: List[Dict[str, Any]], out_of_scope: List[Dict[str, str]],
                        cap: int, basis: str) -> Dict[str, Any]:
    c = cfg(hub)
    return {
        "schema_version": 1, "sprint_number": sp["sprint_number"], "goal": sp["goal"], "committed_at": sp["committed_at"],
        "meeting_ref": sp["meetings"].get("planning"), "capacity": {"max_tasks": cap, "basis": basis},
        "items": [{
            "issue_id": i["id"], "task_key": i.get("task_key"), "work_type": i.get("work_type") or "FEATURE", "title": i.get("title"),
            "role": i.get("assignee"), "priority": i.get("priority"), "depends_on": list(i.get("depends_on") or []),
            "ac_refs": list(i.get("ac_refs") or []), "carried_from": (i.get("carry_over") or {}).get("from_sprint"),
        } for i in items],
        "out_of_scope": out_of_scope, "assumptions": [],
        "budget": {"max_active_min": 300, "max_tokens": 3000000, "carry_over_limit": c["carry_over_limit"]},
    }


def write_commitment(hub, project_dir: str, docs_rel: str, sp: Dict[str, Any], doc: Dict[str, Any]) -> Optional[str]:
    """`sprint-N.json` taahhüt anında bir kez yazılır; sonra değişmez (varsa üzerine yazılmaz)."""
    rel = f"{docs_rel}/sprints/sprint-{sp['sprint_number']}.json"
    return _write(project_dir, rel, json.dumps(doc, ensure_ascii=False, indent=2), overwrite=False)


def retro_markdown(sp: Dict[str, Any], issues: Dict[str, Dict[str, Any]]) -> str:
    m = sp.get("metrics") or {}
    title = lambda iid: (issues.get(iid) or {}).get("title", iid)
    lines = [tx("# Sprint {n} değerlendirme ve retrospektif (review-retro)", n=sp["sprint_number"]), "",
             "- **" + tx("Hedef") + f":** {sp['goal']}", "- **" + tx("Durum") + f":** {sp['status']}", "- **" + tx("Kapanış") + f":** {sp.get('closed_at') or '-'}", "",
             "## " + tx("Metrikler"),
             tx("- Taahhüt: {committed} · Tamamlanan: {completed} · İlk geçişte: {first_pass}", committed=m.get("committed"), completed=m.get("completed"), first_pass=m.get("first_pass")),
             tx("- Düzeltme turu: {fix_rounds} · UAT reddi: {uat_rejections} · E2E: {e2e}", fix_rounds=m.get("fix_rounds"), uat_rejections=m.get("uat_rejections"), e2e=m.get("e2e")),
             tx("- Etkin süre: {active_min} dk · Token: {tokens}", active_min=m.get("active_min"), tokens=m.get("tokens")), "", "## " + tx("Tamamlananlar")]
    lines += [f"- {i} · {title(i)}" for i in sp["completed_issue_ids"]] or [tx("Yok.")]
    lines += ["", "## " + tx("Taşınanlar")]
    lines += [f"- {c['issue_id']} · {title(c['issue_id'])} — " + tx("neden: {reason} (kez: {count})", reason=c["reason"], count=c["count"]) for c in sp["carried_over"]] or [tx("Yok.")]
    if sp.get("blocked"):
        lines += ["", "## " + tx("Engel"), f"- {sp['blocked']['reason']}: {sp['blocked'].get('detail', '')}"]
    lines += ["", tx("_Bu tutanak F3'te sunucu tarafından üretilir; F4'te SCRUM_MASTER toplantı adımı yerini alır._")]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Sprint kipi için yardımcılar: şablon motoru (LLM'siz) çıktıları ve ajan bağlamı
# ---------------------------------------------------------------------------
def _norm_title(t: str) -> str:
    return re.sub(r"[^a-z0-9ğüşıöç]+", " ", str(t).lower()).strip()


def existing_stories(hub) -> List[Dict[str, Any]]:
    return [i for i in hub.jira_issues.values() if str(i.get("kind", "")).lower() == "story" and not i.get("deleted")]


def derive_stories_from_notes(text: str, existing_titles: List[str], limit: int = 4) -> List[Dict[str, Any]]:
    """Şablon motoru için: notlardaki cümlelerden kullanıcı hikâyeleri (var olanlar tekrarlanmaz)."""
    seen = {_norm_title(t) for t in existing_titles}
    out: List[Dict[str, Any]] = []
    body = re.sub(r"^\(.*?\)\n", "", text or "", count=1)
    for raw in re.split(r"(?<=[.!?])\s+|\n+", body):
        sent = raw.strip(" -*•#\t")
        if len(sent) < 20 or len(sent) > 220 or sent.lower().startswith(("müşteri toplantısı", "---")):
            continue
        key = _norm_title(sent)
        if not key or key in seen:
            continue
        seen.add(key)
        title = sent.rstrip(".!?")[:90]
        out.append({"id": f"S-{len(out) + 1}", "title": title, "as_a": tx("Kullanıcı"), "i_want": title, "so_that": tx("ihtiyaç karşılansın"),
                    "acceptance_criteria": [tx("{title} gereksinimi karşılanır ve testle doğrulanır", title=title)]})
        if len(out) >= limit:
            break
    return out


def stories_without_tasks(hub) -> List[Dict[str, Any]]:
    """Henüz hiç görev kırılımı olmayan hikâyeler (ARCHITECT'in bir sonraki yapılandırma adımının girdisi)."""
    # İskele, dağıtım ve doküman görevleri bir hikâyenin kırılımı sayılmaz (hikâyeden değil projeden doğarlar)
    with_tasks = {i.get("parent_id") for i in hub.jira_issues.values()
                  if str(i.get("kind", "")).lower() == "task" and i.get("work_type") not in ("SCAFFOLD", "DEVOPS", "DOCS") and not i.get("deleted")}
    return [st for st in existing_stories(hub) if st["id"] not in with_tasks and not st.get("structured")]


def sprint_template_backlog(hub, stories: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Şablon motoru: hikâye başına bir FEATURE görevi; gerekiyorsa SCAFFOLD, DEVOPS, DOCS (bir kez)."""
    tasks: List[Dict[str, Any]] = []
    issues = [i for i in hub.jira_issues.values() if not i.get("deleted")]

    def has(work_type: str, role: Optional[str] = None) -> bool:
        return any(str(i.get("kind", "")).lower() == "task" and i.get("work_type") == work_type and (role is None or i.get("assignee") == role)
                   for i in issues)

    scaffold_keys: Dict[str, str] = {}
    if not has("SCAFFOLD", "BACKEND_DEV"):
        scaffold_keys["BACKEND_DEV"] = "K-1"
        tasks.append({"id": "K-1", "title": tx("Backend iskeleti (REST servisleri ve kimlik doğrulama)"), "role": "BACKEND_DEV", "work_type": "SCAFFOLD",
                      "description": tx("Onaylı teknoloji yığınıyla çalışan sunucu iskeleti, sağlık ucu ve ilk testler."),
                      "acceptance_criteria": [tx("Sunucu başlar"), tx("Sağlık ucu 200 döner"), tx("Testler yeşil")], "priority": "P0", "files": ["src/main.py"]})
    if not has("SCAFFOLD", "FRONTEND_DEV"):
        scaffold_keys["FRONTEND_DEV"] = "K-2"
        tasks.append({"id": "K-2", "title": tx("Arayüz iskeleti"), "role": "FRONTEND_DEV", "work_type": "SCAFFOLD",
                      "description": tx("Onaylı istemci teknolojisiyle çalışan arayüz iskeleti ve API istemcisi."),
                      "acceptance_criteria": [tx("Arayüz derlenir"), tx("API istemcisi bağlıdır")], "priority": "P0",
                      "depends_on": [scaffold_keys["BACKEND_DEV"]] if "BACKEND_DEV" in scaffold_keys else []})
    feature_keys: List[str] = []
    from . import agent_registry as AR
    custom = AR.routing_roles(hub)
    for n, st in enumerate(stories):
        role = "BACKEND_DEV" if n % 2 == 0 else "FRONTEND_DEV"
        # G6: odak sözcüğü hikâye metninde geçen özel ajan (örn. "Mobil Geliştirici") işi alır; iskelet bağımlılığı temel rolününkidir
        story_text = " ".join([str(st.get("title") or ""), str(st.get("i_want") or ""), " ".join(st.get("acceptance_criteria") or [])])
        pick = AR.match_by_capability(custom, "FEATURE", story_text)
        scaffold_role = custom[pick]["role_base"] if pick else role
        role = pick or role
        key = f"F-{n + 1}"
        feature_keys.append(key)
        tasks.append({"id": key, "title": f"{st.get('title', tx('Hikâye'))[:100]}", "role": role, "work_type": "FEATURE", "story_ref": st["id"],
                      "description": tx("Hikâye {id} için özellik: {title}", id=st["id"], title=st.get("title", "")),
                      "acceptance_criteria": list(st.get("acceptance_criteria") or [tx("Kabul kriteri karşılanır")])[:3],
                      "ac_refs": list(st.get("ac_refs") or []), "priority": "P1",
                      "depends_on": [scaffold_keys[scaffold_role]] if scaffold_role in scaffold_keys else []})
    if stories and not has("DEVOPS"):
        tasks.append({"id": "D-1", "title": tx("Dağıtım: Dockerfile ve docker-compose"), "role": "DEVOPS", "work_type": "DEVOPS",
                      "description": tx("Uygulamayı konteynerde çalıştıracak yapılandırma."), "acceptance_criteria": [tx("Konteyner build edilir")],
                      "priority": "P2", "depends_on": feature_keys[:1]})
    if stories and not has("DOCS"):
        tasks.append({"id": "M-1", "title": tx("Kullanıcı kılavuzu ve durum raporu"), "role": "DOCUMENTOR", "work_type": "DOCS",
                      "description": tx("Son kullanıcı kılavuzu ve yönetici özeti."), "acceptance_criteria": [tx("Kılavuz yayınlandı")], "priority": "P2",
                      "depends_on": feature_keys[:1]})
    return tasks


def _minutes_between(a: Optional[str], b: Optional[str]) -> float:
    try:
        return max(0.0, (datetime.fromisoformat(b) - datetime.fromisoformat(a)).total_seconds() / 60.0)
    except Exception:
        return 0.0


def summarize(hub, run, n: int) -> Dict[str, Any]:
    """Sprint sonu özeti (yan etkisiz): tamamlanan/taşınan işler ve sunucu metrikleri. Retro toplantısının girdisi ve kapanışın kaynağıdır."""
    sp = get_sprint(hub, n) or {}
    completed: List[str] = []
    carried: List[Dict[str, Any]] = []
    for iid in sp.get("committed_issue_ids", []):
        issue = hub.jira_issues.get(iid) or {}
        if issue.get("status") == "DONE":
            completed.append(iid)
            continue
        started = any(s.issue_id == iid and s.sprint == n and s.status in ("DONE", "FAILED", "ACTIVE", "WAITING_APPROVAL") for s in run.steps)
        reason = ("TOKEN_LIMIT" if issue.get("token_limit_sprint") == n else "FIX_LIMIT" if issue.get("fix_limit_sprint") == n
                  else ("NOT_STARTED" if not started else "FIX_LIMIT"))
        carried.append({"issue_id": iid, "reason": reason, "count": int((issue.get("carry_over") or {}).get("count", 0) or 0) + 1})
    steps = [s for s in run.steps if s.sprint == n]
    fixes = [s for s in steps if s.kind == "fix"]
    fixed = {s.issue_id for s in fixes}
    e2e = hub.playwright_reports[0].get("status") if (any(s.order == 7 for s in steps) and hub.playwright_reports) else None
    metrics = {
        "committed": len(sp.get("committed_issue_ids", [])), "completed": len(completed), "first_pass": sum(1 for i in completed if i not in fixed),
        "fix_rounds": len(fixes), "uat_rejections": int(sp.get("uat_rejections", 0)), "e2e": e2e,
        "active_min": int(round(sum(_minutes_between(s.started_at, s.finished_at) for s in steps))),
        "tokens": sum((s.tokens_in or 0) + (s.tokens_out or 0) for s in steps),
        # F7: retro ölçütleri
        "rejected_deliveries": sum(int(s.attempts or 0) for s in steps),
    }
    metrics["first_pass_rate"] = round(metrics["first_pass"] / metrics["committed"], 4) if metrics["committed"] else None
    roles: Dict[str, Dict[str, int]] = {}
    for s in steps:
        if s.kind in ("task", "phase") and s.role and s.status in ("DONE", "FAILED") and not s.server_side:
            r = roles.setdefault(s.role, {"delivered": 0, "first_pass": 0, "fix_rounds": 0})
            r["delivered"] += 1
            if s.issue_id not in fixed and (s.verification or {}).get("status") != "FAILED":
                r["first_pass"] += 1
        elif s.kind == "fix" and s.role:
            roles.setdefault(s.role, {"delivered": 0, "first_pass": 0, "fix_rounds": 0})["fix_rounds"] += 1
    metrics["roles"] = roles
    return {"completed": completed, "carried": carried, "metrics": metrics}


# ---------------------------------------------------------------------------
# Kopya maddeler: aynı bulgudan çıkan birden çok backlog maddesi tek maddede birleşir
# ---------------------------------------------------------------------------
_SYNONYMS = {"login": "giriş", "signin": "giriş", "endpoint": "uç", "ucu": "uç", "uçları": "uç"}
_STOP = {"için", "ve", "ile", "bir", "bu", "da", "de", "qa", "bug"}


def _title_tokens(title: str) -> set:
    t = re.sub(r"\[[^\]]*\]|\bbug-[a-z]*-?\d+\s*:?", " ", str(title or "").lower())
    toks = [_SYNONYMS.get(w, w) for w in re.findall(r"[\wçğıöşü]+", t)]
    return {w for w in toks if w not in _STOP}


def find_duplicates(hub) -> List[Tuple[str, str]]:
    """(kalan madde, kopya) çiftleri. Aynı AC kümesi + benzer başlık (Jaccard ≥ 0.8, en az 4 sözcük); koşuda adımı olan ya da sprinte alınmış madde dokunulmaz."""
    in_run = {s.issue_id for r in hub.runs.values() for s in r.steps}
    pool = sorted((i for i in hub.jira_issues.values() if _eligible(hub, i) and i["id"] not in in_run and not i.get("planned_sprint")),
                  key=lambda i: int(i.get("order", 0) or 0))
    pairs: List[Tuple[str, str]] = []
    gone: set = set()
    for a_i, a in enumerate(pool):
        if a["id"] in gone:
            continue
        ta = _title_tokens(a.get("title"))
        if len(ta) < 4:
            continue
        for b in pool[a_i + 1:]:
            if b["id"] in gone or set(a.get("ac_refs") or []) != set(b.get("ac_refs") or []):
                continue
            tb = _title_tokens(b.get("title"))
            if len(tb) >= 4 and len(ta & tb) / len(ta | tb) >= 0.8:
                pairs.append((a["id"], b["id"]))
                gone.add(b["id"])
    return pairs


def _dup_note_rx():
    """Kopya notunu her dildeki biçimiyle bulan regex (not üretilip sonra aranıyor: eşleştirme tuzağı)."""
    pats = []
    for v in variants("Kopya: {merged} bu maddede birleştirildi.", merged="\x00"):
        a, _, b = v.partition("\x00")
        pats.append(re.escape(a) + ".*?" + re.escape(b))
    return re.compile("|".join(pats))


def merge_duplicates(hub, apply: bool = True) -> List[Dict[str, str]]:
    """Kopyaları işaretler (silinmiş + `duplicate_of`); kalan maddeye kopyaların anahtarları ve kabul kriterleri eklenir. `apply=False` yalnızca raporlar."""
    out: List[Dict[str, str]] = []
    for keep_id, dup_id in find_duplicates(hub):
        keep, dup = hub.jira_issues[keep_id], hub.jira_issues[dup_id]
        out.append({"keep": keep.get("key") or keep_id, "duplicate": dup.get("key") or dup_id, "title": str(dup.get("title") or "")[:100]})
        if not apply:
            continue
        dup["deleted"] = True
        dup["duplicate_of"] = keep_id
        merged = list(keep.get("merged_from") or []) + [dup.get("key") or dup_id]
        keep["merged_from"] = merged
        crit = list(keep.get("acceptance_criteria") or [])
        for c in dup.get("acceptance_criteria") or []:
            if c not in crit:
                crit.append(c)
        keep["acceptance_criteria"] = crit
        note = tx("Kopya: {merged} bu maddede birleştirildi.", merged=", ".join(merged))
        if not _dup_note_rx().search(str(keep.get("description") or "")):
            keep["description"] = f"{keep.get('description') or ''}\n\n{note}".strip()
        else:
            keep["description"] = _dup_note_rx().sub(lambda _m: note, keep["description"])
    if apply and out:
        hub.mark_dirty()
    return out


# ---------------------------------------------------------------------------
# Elle girilen işler: planlayıcının göremediği ya da ince (kabul kriterisiz) maddeler
# ---------------------------------------------------------------------------
BACKBONE_MAX_ORDER = 10        # 1-10: sabit faz omurgası (faz adımları); bunlar sprint görevi değildir


ROLE_WORK_TYPE = {"DESIGNER": "DESIGN", "QA": "TEST", "DEVOPS": "DEVOPS", "DOCUMENTOR": "DOCS"}      # elle açılan işte rolden iş türü (Jira, müdahale ve müzakere aynı kuralı kullanır)


def default_work_type(issue: Dict[str, Any]) -> str:
    """Elle açılan işin iş türü: bug ise BUG, rolü özel türü olan role (tasarımcı, QA, DevOps, belge) ise o türü, aksi halde FEATURE."""
    if issue.get("issue_type") == "BUG":
        return "BUG"
    return ROLE_WORK_TYPE.get(str(issue.get("assignee") or "").upper(), "FEATURE")


def adopt_manual_tasks(hub) -> List[str]:
    """`kind` alanı olmayan, omurga dışı TASK/BUG maddeleri (eski sürümde panodan elle eklenenler) sprint görevi olarak sahiplenilir: kind=task, origin=MANAGER.
    Kabul kriteri olmayan ya da açıklaması yalnızca başlığın tekrarı olan madde `needs_grooming` ile işaretlenir ve geliştirmenin yönlenebilmesi için
    taslak kriter/açıklama alır (planlama toplantısı bunu netleştirmesi gereken iş olarak görür). Döner: dokunulan madde kimlikleri."""
    touched: List[str] = []
    for i in hub.jira_issues.values():
        if i.get("deleted") or i.get("status") != "BACKLOG" or i.get("sprint") or i.get("run_id"):
            continue
        manual_legacy = (not i.get("kind") and i.get("issue_type") in ("TASK", "BUG") and int(i.get("order", 0) or 0) > BACKBONE_MAX_ORDER)
        if not (manual_legacy or str(i.get("kind", "")).lower() == "task"):
            continue
        changed = False
        if manual_legacy:
            i["kind"] = "task"
            i.setdefault("origin", "MANAGER")
            i["work_type"] = i.get("work_type") or default_work_type(i)
            changed = True
        title = str(i.get("title") or "").strip()
        desc = str(i.get("description") or "").strip()
        thin = not (i.get("acceptance_criteria") or []) or re.sub(r"^(task|bug)\s*:\s*", "", desc, flags=re.I).strip().lower() in ("", title.lower())
        if thin and i.get("origin") in ("MANAGER", None, "") and not i.get("needs_grooming") and not i.get("groomed"):
            if not (i.get("acceptance_criteria") or []):
                i["acceptance_criteria"] = [tx("{title} beklenen davranışı sağlar", title=title[:120]), tx("Davranışı doğrulayan en az bir test eklenir (kabul kriteri kimliği anılır)")]
            if re.sub(r"^(task|bug)\s*:\s*", "", desc, flags=re.I).strip().lower() in ("", title.lower()):
                i["description"] = (tx("Yönetici isteği: {title}. Kapsam açıkça tanımlanmadı; taslak kabul kriterleri eklendi. ", title=title)
                                    + tx("Belirsiz kalan noktaları teslimde soru olarak belirt (questions), varsayım yaparsan ADR/özet notuna yaz."))
            i["needs_grooming"] = True
            changed = True
        if changed:
            touched.append(i["id"])
    if touched:
        hub.mark_dirty()
    return touched
