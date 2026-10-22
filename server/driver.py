"""Claude Desktop sürücüsü (F5, belge §9, §3.5): `claim_work`, kira, oturum sınırı, bütçe / takılma denetimi, otonomiyi durdurma.

Sunucu istemciye iş yollayamaz (çekme modeli); runner (Claude Desktop yerel zamanlanmış görevi) her çalıştırmada taze bir oturumla
`claim_work` çağırır. Hangi işin ne zaman yapılacağına sunucu karar verir (§9.6): runner yalnızca üretir.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from . import meetings as M
from . import sprint as SP
from .i18n import translate as tx, N_

DEFAULT_RUNNER: Dict[str, Any] = {"interval_min": 10, "interval_paused_min": 30, "max_steps_per_session": 8, "abandon_factor": 3,
                                  "session_boundaries": False}     # False: oturum sınırı (SESSION_BOUNDARY) yok; ajan koşu bitene/bloke olana kadar sürer
DEFAULT_DISPLAY: Dict[str, Any] = {"verbosity": "summary"}
DEV_ROLES = {"BACKEND_DEV", "FRONTEND_DEV", "DEVOPS"}
EVAL_ROLES = {"QA", "PO", "ARCHITECT_REVIEW"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso() -> str:
    return _now().isoformat()


# ---------------------------------------------------------------------------
# Ayarlar
# ---------------------------------------------------------------------------
def sanitize_runner(raw: Any, fallback: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    raw = raw if isinstance(raw, dict) else {}
    out = {**DEFAULT_RUNNER, **{k: v for k, v in (fallback or {}).items() if k in DEFAULT_RUNNER}}
    bounds = {"interval_min": (1, 1440), "interval_paused_min": (1, 1440), "max_steps_per_session": (1, 100), "abandon_factor": (1, 20)}
    for k, (lo, hi) in bounds.items():
        if k in raw:
            try:
                out[k] = max(lo, min(int(raw[k]), hi))
            except (TypeError, ValueError):
                pass
    if "session_boundaries" in raw:
        out["session_boundaries"] = bool(raw["session_boundaries"])
    return out


def sanitize_display(raw: Any, fallback: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    raw = raw if isinstance(raw, dict) else {}
    out = {**DEFAULT_DISPLAY, **{k: v for k, v in (fallback or {}).items() if k in DEFAULT_DISPLAY}}
    if raw.get("verbosity") in ("summary", "full"):
        out["verbosity"] = raw["verbosity"]
    return out


def runner_cfg(hub) -> Dict[str, Any]:
    return sanitize_runner((hub.get_settings() or {}).get("runner"))


def display_cfg(hub) -> Dict[str, Any]:
    return sanitize_display((hub.get_settings() or {}).get("display"))


def abandon_after_s(hub) -> float:
    """Sprint koşularında terk süresi runner aralığının en az üç katıdır (§9.3 madde 5)."""
    c = runner_cfg(hub)
    return float(c["abandon_factor"] * c["interval_min"] * 60)


def lease_ttl_s(hub) -> float:
    """Kira ömrü: runner aralığının 1,5 katı; her araç çağrısında yenilenir. Ölen oturum en çok bu kadar bekletir."""
    return max(90.0, 1.5 * runner_cfg(hub)["interval_min"] * 60)


# ---------------------------------------------------------------------------
# Runner durumu ve kira (§9.3 madde 4: proje başına tek etkin oturum)
# ---------------------------------------------------------------------------
def runner_state(hub) -> Dict[str, Any]:
    st = getattr(hub, "runner", None)
    if not isinstance(st, dict):
        st = {}
    st.setdefault("last_seen", None)
    st.setdefault("client", None)
    st.setdefault("claims", 0)
    st.setdefault("last_result", None)
    st.setdefault("lease", None)
    hub.runner = st
    return st


def seen(hub, client: Optional[Dict[str, str]] = None) -> None:
    st = runner_state(hub)
    st["last_seen"] = _iso()
    if client and client.get("name"):
        st["client"] = client


def lease_valid(hub) -> Optional[Dict[str, Any]]:
    lease = runner_state(hub).get("lease")
    if not lease:
        return None
    run = hub.runs.get(lease["run_id"])
    if run is None or run.is_terminal or datetime.fromisoformat(lease["expires_at"]) <= _now():
        runner_state(hub)["lease"] = None
        return None
    return lease


def grant_lease(hub, run) -> Dict[str, Any]:
    lease = {"run_id": run.run_id, "granted_at": _iso(), "expires_at": (_now() + timedelta(seconds=lease_ttl_s(hub))).isoformat()}
    runner_state(hub)["lease"] = lease
    run.runner_claimed = True
    return lease


def renew_lease(hub, run) -> None:
    lease = runner_state(hub).get("lease")
    if lease and lease["run_id"] == run.run_id:
        lease["expires_at"] = (_now() + timedelta(seconds=lease_ttl_s(hub))).isoformat()


def release_lease(hub, run_id: Optional[str] = None) -> None:
    lease = runner_state(hub).get("lease")
    if lease and (run_id is None or lease["run_id"] == run_id):
        runner_state(hub)["lease"] = None


def runner_status(hub) -> Dict[str, Any]:
    st = runner_state(hub)
    c = runner_cfg(hub)
    last = st.get("last_seen")
    age = (_now() - datetime.fromisoformat(last)).total_seconds() if last else None
    fresh = age is not None and age <= 3 * c["interval_min"] * 60
    return {"last_seen": last, "age_s": age, "fresh": fresh, "client": st.get("client"), "claims": st.get("claims"), "last_result": st.get("last_result"),
            "lease": lease_valid(hub), "interval_min": c["interval_min"], "waiting_for_client": bool(hub.active_run_for(hub.active_project_id)) and not fresh}


# ---------------------------------------------------------------------------
# Koşu bekçisi: koşu kopunca (istemci oturumu sustu) belirli aralıkla yoklar ve ilerletir
# ---------------------------------------------------------------------------
def job_run(hub):
    """Bekçinin izlediği "iş": yöneticinin başlattığı etkin koşu; yoksa en ilerlemiş terk edilmiş MCP koşusu."""
    pid = hub.active_project_id
    run = hub.active_run_for(pid)
    if run is not None:
        return run
    return next(iter(abandoned_runs(hub, pid)), None)


def schedule_hint(hub) -> Optional[Dict[str, Any]]:
    """Koşu başlatma yanıtına eklenen kısa ipucu: izlenen iş var ve zamanlanmış görev çalışmıyor görünüyorsa yapay zekâ göreve talimatlardan bakıp görevi kurar."""
    try:
        s = runner_schedule(hub)
    except Exception:  # noqa: BLE001
        return None
    if s["action"] != "create_or_update_scheduled_task":
        return None
    return {"action": s["action"], "interval_minutes": s["interval_minutes"], "suggested_cron": s["suggested_cron"], "task_name": s["task_name"],
            "message": tx("Koşu kopunca ilerletecek zamanlanmış görev görünmüyor: get_runner_schedule çağır; zamanlanmış görev araçların varsa task_prompt metniyle "
                          "`{task}` görevini {minutes} dk aralıkla (cron {cron}) kur.", task=s['task_name'], minutes=s['interval_minutes'], cron=s['suggested_cron'])}


def is_paused(hub) -> bool:
    """Uygulama (proje) ya da izlenen koşu duraklatıldı mı? Duraklatılmışken bekçi daha seyrek yoklar."""
    if SP.ensure_state(hub).get("project_status") == "PAUSED":
        return True
    run = job_run(hub)
    return bool(run is not None and run.paused)


def check_interval_min(hub) -> int:
    """Bekçinin yoklama aralığı (dk): duraklatılmışsa `interval_paused_min` (örn. 30), değilse `interval_min` (örn. 10)."""
    c = runner_cfg(hub)
    return int(c["interval_paused_min"] if is_paused(hub) else c["interval_min"])


def _suggested_cron(minutes: int) -> str:
    if minutes < 60:
        return f"*/{minutes} * * * *"
    hours = max(1, round(minutes / 60))
    return f"0 */{hours} * * *" if hours < 24 else "0 0 * * *"


def runner_schedule(hub) -> Dict[str, Any]:
    """Zamanlanmış görev kurmak/güncellemek için tek kaynak (MCP aracı `get_runner_schedule`, pano ekranı): aralıklar, duraklatma, izlenen iş, sonraki yoklama."""
    from . import claude_bridge as CB
    c = runner_cfg(hub)
    paused = is_paused(hub)
    minutes = c["interval_paused_min"] if paused else c["interval_min"]
    run = job_run(hub)
    job = None
    if run is not None:
        idle_min = round(_minutes(run.last_seen, _iso()), 1) if run.last_seen else None
        job = {"run_id": run.run_id, "status": run.status, "mode": run.mode, "paused": bool(run.paused), "last_seen": run.last_seen, "idle_min": idle_min,
               "stalled": run.status == "ABANDONED" or (idle_min is not None and run.status in ("ACTIVE", "QUEUED") and idle_min >= c["abandon_factor"] * c["interval_min"]),
               "done_steps": _done_steps(run), "total_steps": len(run.steps)}
    bridge = CB.bridge(hub)
    rs = runner_status(hub)
    proj = hub.projects.get(hub.active_project_id) or {}
    # Zamanlanmış görev (Claude Desktop) sunucudan görülemez; claim_work çağrılarının tazeliği "görev var ve çalışıyor" göstergesidir
    need_task = bool(job) and not rs["fresh"] and not paused
    return {"runner_fresh": bool(rs["fresh"]), "runner_last_seen": rs["last_seen"], "task_name": f"FS-SC koşu bekçisi · {proj.get('name') or hub.active_project_id}",
            "task_prompt": CB.scheduled_task_prompt(),
            "action": "create_or_update_scheduled_task" if need_task else ("update_interval_if_different" if job else "none_or_delete_if_exists"),
            "enabled": bool(CB.cfg(hub)["auto_runner"]), "paused": paused, "interval_minutes": minutes, "active_interval_min": c["interval_min"],
            "paused_interval_min": c["interval_paused_min"], "abandon_after_min": c["abandon_factor"] * c["interval_min"], "suggested_cron": _suggested_cron(minutes),
            "job": job, "claimable": claimable_work(hub), "last_check": bridge.auto_state.get("last_check"), "next_check_at": bridge.auto_state.get("next_check_at"),
            "last_reason": bridge.auto_state.get("last_reason")}


# ---------------------------------------------------------------------------
# Bütçe ve takılma (§3.5)
# ---------------------------------------------------------------------------
def budget(hub) -> Dict[str, int]:
    return M.autonomy(hub)["budget"]


def _minutes(a: Optional[str], b: Optional[str]) -> float:
    try:
        return max(0.0, (datetime.fromisoformat(b) - datetime.fromisoformat(a)).total_seconds() / 60.0)
    except Exception:
        return 0.0


def sprint_usage(hub, run, n: int) -> Dict[str, Any]:
    """Sprintin harcaması. Etkin süre: adım üretilirken ya da doğrulanırken geçen süre; onay/soru beklemesi sayılmaz (§3.5)."""
    steps = [s for s in run.steps if s.sprint == n]
    active = sum(_minutes(s.started_at, s.finished_at) for s in steps if s.finished_at)
    now = _iso()
    active += sum(_minutes(s.started_at, now) for s in steps if s.status == "ACTIVE" and s.started_at and not s.finished_at and s.kind != "plan")
    return {"active_min": round(active, 1), "tokens": sum((s.tokens_in or 0) + (s.tokens_out or 0) for s in steps),
            "steps": sum(1 for s in steps if s.status in ("DONE", "FAILED")), "task_tokens": {}}


def task_tokens(run, issue_id: str, sprint: Optional[int]) -> int:
    return sum((s.tokens_in or 0) + (s.tokens_out or 0) for s in run.steps if s.issue_id == issue_id and s.sprint == sprint)


async def check_task_tokens(hub, run, record) -> bool:
    """Görev kendi token sınırını aştıysa durdurulur ve yeniden kapsamlanmak üzere taşınır (TOKEN_LIMIT, §7.8)."""
    if run.mode != "sprint" or not record.sprint or record.kind not in ("task", "fix"):
        return False
    limit = budget(hub)["max_tokens_per_task"]
    used = task_tokens(run, record.issue_id, record.sprint)
    if used <= limit:
        return False
    for s in run.steps:     # bekleyen düzeltme turları iptal
        if s.issue_id == record.issue_id and s.kind == "fix" and s.status == "PENDING":
            s.status = "SKIPPED"
    await hub.update_jira_issue(record.issue_id, {"token_limit_sprint": record.sprint, "audit_action": "TOKEN_LIMIT_REACHED",
                                                  "audit_notes": tx("Görev {used} token harcadı (sınır {limit}); sprint kapanışında TOKEN_LIMIT ile yeniden kapsamlanmak üzere taşınacak.", used=used, limit=limit)})
    return True


async def block_sprint(hub, run, sp: Dict[str, Any], reason: str, detail: str) -> None:
    """Sprint BLOCKED: o projede başka hiçbir adım ilerlemez; neden ve harcama yönetici özetinde görünür (§3.4)."""
    prev = sp["status"]
    SP.set_sprint_status(hub, sp, "BLOCKED", blocked={"reason": reason, "since": _iso(), "previous_status": prev, "detail": detail})
    run.paused, run.pause_reason = True, f"BLOCKED:{reason}"
    release_lease(hub, run.run_id)
    usage = sprint_usage(hub, run, sp["sprint_number"])
    await hub.record_event(trace_id=run.run_id, from_agent="SCRUM_MASTER", to_agent="MANAGER", action="SPRINT_BLOCKED", status="FAILED",
                           payload={"sprint": sp["sprint_number"], "reason": reason, "detail": detail, "usage": usage},
                           friendly_dialogue=tx("Sprint {n} durdu ({reason}): {detail}", n=sp['sprint_number'], reason=reason, detail=detail))
    await hub.broadcast({"type": "SPRINT_BLOCKED", "sprint": sp["sprint_number"], "reason": reason, "detail": detail})
    await hub.broadcast({"type": "STALLED" if reason == "STALLED" else "BUDGET_EXCEEDED", "sprint": sp["sprint_number"], "detail": detail, "usage": usage})
    from . import pipeline as P
    await P.publish_run(hub, run)


async def enforce_budgets(hub, run, record, progress: bool, failed: bool) -> Optional[str]:
    """Her LLM/sunucu adımından sonra: sayaçları günceller, uyarır, sınır aşılırsa sprinti BLOCKED yapar. Dönüş: neden kodu ya da None."""
    if run.mode != "sprint" or not record.sprint:
        return None
    sp = SP.get_sprint(hub, record.sprint)
    if sp is None or sp["status"] == "BLOCKED":
        return None
    sp["no_progress_steps"] = 0 if progress else int(sp.get("no_progress_steps", 0)) + 1
    sp["failed_steps_in_row"] = int(sp.get("failed_steps_in_row", 0)) + 1 if failed else 0
    b = budget(hub)
    u = sprint_usage(hub, run, record.sprint)
    warned: List[str] = sp.setdefault("warned", [])
    pct = b["warn_at_percent"]
    for key, used, limit in (("tokens", u["tokens"], b["max_tokens_per_sprint"]), ("active_min", u["active_min"], b["max_active_min_per_sprint"]),
                             ("steps", u["steps"], b["max_steps_per_sprint"])):
        if limit and used * 100 >= pct * limit and key not in warned and used < limit:
            warned.append(key)
            await hub.broadcast({"type": "BUDGET_WARNING", "sprint": record.sprint, "metric": key, "used": used, "limit": limit})
            await hub.record_event(trace_id=run.run_id, from_agent="SCRUM_MASTER", to_agent="MANAGER", action="BUDGET_WARNING", status="IN_PROGRESS",
                                   payload={"metric": key, "used": used, "limit": limit},
                                   friendly_dialogue=tx("Bütçe uyarısı: {key} {used}/{limit} (%{pct}). İş sürüyor.", key=key, used=used, limit=limit, pct=pct))
    reason = detail = None
    if u["tokens"] >= b["max_tokens_per_sprint"]:
        reason, detail = "BUDGET_EXCEEDED", tx("token {used}/{limit}", used=u['tokens'], limit=b['max_tokens_per_sprint'])
    elif u["active_min"] >= b["max_active_min_per_sprint"]:
        reason, detail = "BUDGET_EXCEEDED", tx("etkin süre {used}/{limit} dk", used=u['active_min'], limit=b['max_active_min_per_sprint'])
    elif u["steps"] >= b["max_steps_per_sprint"]:
        reason, detail = "BUDGET_EXCEEDED", tx("adım {used}/{limit}", used=u['steps'], limit=b['max_steps_per_sprint'])
    elif sp["failed_steps_in_row"] >= b["max_consecutive_failed_steps"]:
        reason, detail = "BUDGET_EXCEEDED", tx("art arda başarısız adım {used}/{limit}", used=sp['failed_steps_in_row'], limit=b['max_consecutive_failed_steps'])
    elif sp["no_progress_steps"] >= b["stall_steps"]:
        reason, detail = "STALLED", tx("art arda {n} adımda ilerleme yok (sınır {limit})", n=sp['no_progress_steps'], limit=b['stall_steps'])
    if reason:
        await block_sprint(hub, run, sp, reason, detail)
    return reason


async def unblock_sprint(hub, n: int) -> Dict[str, Any]:
    """Yönetici sınırı artırdıktan (ya da kararını verdikten) sonra sprinti sürdürür. Sınır hâlâ aşılıyorsa reddedilir."""
    sp = SP.get_sprint(hub, n)
    if sp is None or sp["status"] != "BLOCKED" or not sp.get("blocked"):
        raise ValueError(tx("Sprint {n} BLOCKED değil.", n=n))
    reason = sp["blocked"]["reason"]
    if reason == "BLOCKING_QUESTION" and M.open_blocking(hub):
        raise ValueError(tx("Engelleyici soru açık: önce soruyu cevaplayın (POST /api/questions/{id}/answer)."))
    run = next((r for r in hub.runs.values() if sp["sprint_number"] in {s.sprint for s in r.steps if s.sprint} and not r.is_terminal), None)
    if run is not None and reason == "BUDGET_EXCEEDED":
        b, u = budget(hub), sprint_usage(hub, run, n)
        if u["tokens"] >= b["max_tokens_per_sprint"] or u["active_min"] >= b["max_active_min_per_sprint"] or u["steps"] >= b["max_steps_per_sprint"] \
                or int(sp.get("failed_steps_in_row", 0)) >= b["max_consecutive_failed_steps"]:
            raise ValueError(tx("Sınır hâlâ aşılıyor: önce autonomy.budget değerini artırın."))
    prev = sp["blocked"].get("previous_status") or "IN_PROGRESS"
    sp["no_progress_steps"], sp["failed_steps_in_row"], sp["warned"] = 0, 0, []
    SP.set_sprint_status(hub, sp, prev, blocked=None)
    if run is not None:
        run.paused, run.pause_reason = False, ""
        from . import pipeline as P
        await P.publish_run(hub, run)
    await hub.broadcast({"type": "SPRINT_UNBLOCKED", "sprint": n})
    return sp


async def cancel_sprint(hub, n: int) -> Dict[str, Any]:
    """Sprinti olduğu yerde kapatır: bitmeyen işler `NOT_STARTED` ile backlog'a döner, koşu iptal edilir."""
    sp = SP.get_sprint(hub, n)
    if sp is None:
        raise ValueError(tx("Sprint {n} bulunamadı.", n=n))
    if sp["status"] in ("CLOSED", "CANCELLED"):
        raise ValueError(tx("Sprint {n} zaten {status}.", n=n, status=sp['status']))
    for iid in sp.get("committed_issue_ids", []):
        issue = hub.jira_issues.get(iid) or {}
        if issue.get("status") != "DONE":
            count = int((issue.get("carry_over") or {}).get("count", 0) or 0) + 1
            await hub.update_jira_issue(iid, {"sprint": None, "status": "BACKLOG", "carry_over": {"count": count, "last_reason": "NOT_STARTED", "from_sprint": n},
                                              "audit_action": "CARRY_OVER", "audit_notes": tx("Sprint {n} yönetici tarafından kapatıldı.", n=n)})
    SP.set_sprint_status(hub, sp, "CANCELLED", closed_at=_iso(), blocked=None)
    for r in list(hub.runs.values()):
        if not r.is_terminal and any(s.sprint == n for s in r.steps):
            from . import pipeline as P
            await P.cancel_run(hub, r, reason="sprint_cancelled")
    release_lease(hub)
    await hub.broadcast({"type": "SPRINT_CLOSED", "sprint": n, "cancelled": True})
    return sp


async def stop_autonomy(hub) -> Dict[str, Any]:
    """"Otonomiyi durdur" düğmesi: L0 ön ayarını yazar ve etkin koşuyu duraklatır; hiçbir şey silinmez."""
    await hub.update_settings(M.preset_updates("L0"))
    run = hub.active_run_for(hub.active_project_id)
    if run is not None:
        run.paused, run.pause_reason = True, "autonomy_stopped"
        release_lease(hub, run.run_id)
        from . import pipeline as P
        await P.publish_run(hub, run)
    await hub.broadcast({"type": "AUTONOMY_STOPPED"})
    return {"status": "STOPPED", "level": M.current_level(hub), "paused_run": run.run_id if run else None}


# ---------------------------------------------------------------------------
# L3 ön koşulları (§3.1)
# ---------------------------------------------------------------------------
async def l3_preconditions(hub) -> List[Dict[str, Any]]:
    from . import scm as SCM
    from .verify import infer_commands
    project_dir = (hub.projects.get(hub.active_project_id) or {}).get("path") or hub.default_project_path
    ver = (hub.get_settings().get("verification") or {})
    has_test = bool(ver.get("test") or infer_commands(project_dir).get("test"))
    r = runner_status(hub)
    st = await SCM.repo_state(project_dir) if SCM.git_available() else {"repo": False, "nested": False}
    own_repo = bool(st.get("repo") and not st.get("nested"))
    from . import claude_bridge as CB
    from . import guard as G
    sb = G.sandbox(hub)
    ccfg = CB.sanitize_claude((hub.get_settings() or {}).get("claude"))
    auto_ok = bool(ccfg.get("auto_runner")) and bool(CB.cli_status(ccfg.get("cli") or "claude").get("ok"))      # G3 otomatik runner
    docker_ok = G.docker_available()
    return [
        {"key": "verification_test", "ok": has_test, "text": tx("`verification.test` tanımlı (yoksa doğrulama SKIPPED olur ve hiçbir şey denetlenmez)"),
         "fix": tx("Model penceresi 0c → Doğrulama komutları → Test (ya da mimar adım 2'de önerir)")},
        {"key": "runner_installed", "ok": bool(r["fresh"]) or auto_ok,
         "text": tx("Sürücü hazır: Claude Desktop runner görevi güncel (§9.3) ya da otomatik runner açık ve Claude Code CLI kurulu (G3)"),
         "fix": tx("Claude paneli → Başlat & Bağlan → Otomatik runner (CLI gerekir) ya da Desktop zamanlanmış görevi (scripts\\fssc.ps1 runner prompt)")},
        {"key": "command_isolation", "ok": sb["mode"] == "container" and sb["command_policy"] == "allowlist" and docker_ok,
         "text": tx("Komut yalıtımı açık: sandbox.mode=container, sandbox.command_policy=allowlist ve Docker kullanılabilir (§12 madde 1)"),
         "fix": (tx("Docker Desktop'ı başlat; ") if not docker_ok else "") + tx("Model penceresi 0d → kip = container, politika = izin listesi")},
        {"key": "budgets_defined", "ok": all(v > 0 for v in budget(hub).values()), "text": tx("Bütçeler tanımlı (§3.5)"),
         "fix": tx("POST /api/settings/autonomy {budget: {max_sprints, max_tokens_per_sprint, ...}} (hepsi > 0)")},
        {"key": "own_git_repo", "ok": own_repo, "text": tx("Hedef proje kendi git deposunda, başka bir deponun altında değil"),
         "fix": tx("Proje klasöründe `git init` (SCM ajanı ilk commit'te kendisi açar); üst klasörlerde başka bir .git olmamalı")},
    ]


async def apply_preset(hub, level: str) -> Dict[str, Any]:
    level = str(level or "").upper()
    if level not in M.PRESETS:
        raise ValueError(tx("Bilinmeyen seviye: {level}", level=level))
    if level == "L3":
        missing = [c for c in await l3_preconditions(hub) if not c["ok"]]
        if missing:
            raise PermissionError(tx("L3 reddedildi; eksik ön koşullar: ") + "; ".join(c["text"] for c in missing))
    await hub.update_settings(M.preset_updates(level))
    return {"level": M.current_level(hub), "autonomy": M.autonomy(hub), "sprint": SP.cfg(hub), "approval_mode": hub.get_settings().get("approval_mode")}


# ---------------------------------------------------------------------------
# claim_work (§9.3): runner'ın ilk çağrısı
# ---------------------------------------------------------------------------
def _blocked_sprint(hub) -> Optional[Dict[str, Any]]:
    """Yönetici kararı bekleyen engelli sprint. Eksik mimar gözden geçirmesi koşuya zaten planlandıysa (review_planned) yönetici beklenmez: iş sürer."""
    def needs_manager(s: Dict[str, Any]) -> bool:
        b = s.get("blocked") or {}
        return not (b.get("reason") == "PRECONDITION_LOST" and b.get("review_planned"))
    return next((s for s in SP.ensure_state(hub)["sprints"] if s["status"] == "BLOCKED" and needs_manager(s)), None)


def _open_work(hub) -> bool:
    return any(str(i.get("kind", "")).lower() == "task" and i.get("status") != "DONE" and not i.get("deleted") for i in hub.jira_issues.values())


def claimable_work(hub) -> Dict[str, Any]:
    """G3: `claim_work` ön koşullarının yan etkisiz kopyası (otomatik runner bunu yoklar): üstlenilebilir iş var mı, yoksa neden?"""
    pid = hub.active_project_id
    state = SP.ensure_state(hub)
    if state["project_status"] in ("DONE", "PAUSED"):
        return {"claimable": False, "reason": f"PROJECT_{state['project_status']}"}
    if _blocked_sprint(hub) is not None:
        return {"claimable": False, "reason": "BLOCKED"}
    run = hub.active_run_for(pid)
    if run is None:
        if any(r.project_id == pid and r.status == "ABANDONED" and r.engine == "mcp_client" for r in hub.runs.values()):
            return {"claimable": True, "reason": "ABANDONED_RUN"}
        if SP.enabled(hub) and (state.get("pending_intake") or (_open_work(hub) and state["project_status"] == "ACTIVE" and SP.cfg(hub)["auto_chain"])):
            return {"claimable": True, "reason": "PENDING_WORK"}
        return {"claimable": False, "reason": "NO_WORK"}
    if run.engine != "mcp_client":
        return {"claimable": False, "reason": "TEMPLATE_ENGINE", "run_id": run.run_id}
    if run.paused:
        return {"claimable": False, "reason": "PAUSED", "run_id": run.run_id}
    if run.status == "WAITING_APPROVAL":
        return {"claimable": False, "reason": "AWAITING_MANAGER", "run_id": run.run_id}
    lease = lease_valid(hub)
    if lease and lease["run_id"] == run.run_id:
        return {"claimable": False, "reason": "LEASED", "run_id": run.run_id}
    return {"claimable": True, "reason": f"RUN_{run.status}", "run_id": run.run_id}


def _done_steps(run) -> int:
    return sum(1 for s in run.steps if s.status == "DONE")


def abandoned_runs(hub, pid: Optional[str] = None, mode: Optional[str] = None) -> List[Any]:
    """Terk edilmiş (sunucu yeniden başladı / istemci koptu) MCP koşuları: en çok ilerlemiş önce, eşitlikte en yeni.
    Taze ama boş bir koşu, ilerlemiş eskisinin önüne geçmez (aksi halde iş "baştan başlıyor")."""
    pid = pid or hub.active_project_id
    runs = [r for r in hub.runs.values()
            if r.project_id == pid and r.status == "ABANDONED" and r.engine == "mcp_client" and (mode is None or r.mode == mode)]
    return sorted(runs, key=lambda r: (_done_steps(r), r.created_at), reverse=True)


async def resume_abandoned(hub, api, pid: Optional[str] = None, mode: Optional[str] = None, client: Optional[Dict[str, str]] = None,
                           prefer: Optional[Any] = None, accept: Optional[Any] = None) -> Optional[Any]:
    """Terk edilmiş koşuyu kaldığı adımdan sürdürür (yeni koşu kurmaz) [A10]. `prefer`: açıkça seçilen koşu; `accept`: aday süzgeci.
    Tek koşu kuralı: aynı proje ve kipteki diğer terk edilmiş koşular iptal edilir; yoksa biri sonradan canlandırılınca iki koşu birden etkin olur."""
    from . import pipeline as P
    cands = [r for r in abandoned_runs(hub, pid, mode) if accept is None or accept(r)]
    if prefer is not None:
        cands = [prefer] + [r for r in cands if r is not prefer]
    if not cands:
        return None
    run, others = cands[0], cands[1:]
    for old in others:
        old.finish("CANCELLED", reason=f"superseded:{run.run_id}")
        await P.publish_run(hub, old)
    api.mcp._revive_if_abandoned(run)
    run.touch()
    if client and client.get("name"):
        run.client_name = client.get("name", "")
        run.client_version = client.get("version", "")
    await api.mcp.reopen_gate(run)            # onay beklerken terk edilen adım onay bekler halde döner (yeniden çalışmaz)
    await P.publish_run(hub, run)
    return run


async def claim_work(hub, api, client: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Bekleyen iş varsa koşuyu ve kirayı verir; yoksa `IDLE`, sprint/koşu durmuşsa `BLOCKED` döner. Boş ya da bloke çalıştırma tek çağrıyla biter."""
    seen(hub, client)
    st = runner_state(hub)
    st["claims"] = int(st.get("claims", 0)) + 1
    pid = hub.active_project_id

    def done(res: Dict[str, Any]) -> Dict[str, Any]:
        st["last_result"] = {"status": res["status"], "reason": res.get("reason"), "at": _iso()}
        return res

    state = SP.ensure_state(hub)
    if state["project_status"] == "DONE":
        return done({"status": "IDLE", "reason": "PROJECT_DONE", "message": tx("Ürün tamamlandı; yapılacak iş yok."),
                     "suggestion": tx("Zamanlanmış görevi duraklatabilirsin; kasaya yeni not yüklenirse proje yeniden başlar.")})
    if state["project_status"] == "PAUSED":
        return done({"status": "IDLE", "reason": "PROJECT_PAUSED", "message": tx("Proje bütçe sınırı nedeniyle duraklatıldı (özet rapor hazır)."),
                     "suggestion": tx("Yönetici sınırı artırıp projeyi sürdürene kadar zamanlanmış görevi duraklatabilirsin.")})
    blocked = _blocked_sprint(hub)
    if blocked is not None:
        b = blocked["blocked"] or {}
        return done({"status": "BLOCKED", "reason": b.get("reason"), "detail": b.get("detail"), "sprint": blocked["sprint_number"],
                     "message": tx("Sprint {n} durdu ({reason}): {detail}", n=blocked['sprint_number'], reason=b.get('reason'), detail=b.get('detail')),
                     "what_to_do": tx("Yönetici dashboard'dan çözmeli (soruyu cevaplamak, sınırı artırıp sprinti sürdürmek ya da sprinti kapatmak)."),
                     "usage": None})
    run = hub.active_run_for(pid)
    if run is None:
        # Terk edilmiş koşu kaldığı adımdan sürer [A10]; birden çoksa en çok ilerleyeni (taze ama boş koşu öne geçmez)
        run = await resume_abandoned(hub, api, pid)
        if run is None and SP.enabled(hub) and (state.get("pending_intake") or (_open_work(hub) and state["project_status"] == "ACTIVE" and SP.cfg(hub)["auto_chain"])):
            started = await api.start_sprint_run(project_id=pid, engine="mcp_client", with_intake=bool(state.get("pending_intake")), client=client)
            run = hub.runs.get((started.get("run") or {}).get("run_id"))
        if run is None:
            return done({"status": "IDLE", "reason": "NO_WORK", "message": tx("Bekleyen iş yok."),
                         "suggestion": tx("Kasaya not yüklenince ya da yönetici sıradaki sprinti başlatınca iş oluşur.")})
    if run.engine != "mcp_client":
        return done({"status": "IDLE", "reason": "TEMPLATE_ENGINE", "message": tx("Etkin koşu ({id}) şablon motoruyla yürüyor; çekilemez.", id=run.run_id)})
    if run.paused:
        return done({"status": "BLOCKED", "reason": "PAUSED", "detail": run.pause_reason, "run_id": run.run_id,
                     "message": tx("Koşu duraklatıldı ({reason}).", reason=run.pause_reason), "what_to_do": tx("Dashboard'dan devam ettir.")})
    if run.status == "WAITING_APPROVAL":
        gate = (hub.pending_step_approval or {}).get("kind") or run.gate_kind or "step"
        return done({"status": "BLOCKED", "reason": "AWAITING_MANAGER", "detail": gate, "run_id": run.run_id,
                     "message": tx("Yönetici onayı/cevabı bekleniyor ({gate}).", gate=gate), "what_to_do": tx("Dashboard'dan onayla ya da soruyu cevapla.")})
    lease = lease_valid(hub)
    if lease and lease["run_id"] == run.run_id:
        return done({"status": "IDLE", "reason": "LEASED", "message": tx("Bu proje için başka bir runner oturumu çalışıyor (kira geçerli)."),
                     "lease_expires_at": lease["expires_at"]})
    run.session_boundary = False
    run.session_steps = 0
    lease = grant_lease(hub, run)
    run.touch()
    if client and client.get("name"):
        run.client_name = client["name"]
    cur = run.current_step
    return done({"status": "CLAIMED", "run_id": run.run_id, "run_status": run.status, "mode": run.mode, "sprint": cur.sprint if cur else None,
                 "next": "get_next_step", "progress": f"{run.cursor + 1}/{len(run.steps)}",
                 "max_steps_per_session": runner_cfg(hub)["max_steps_per_session"], "lease_expires_at": lease["expires_at"],
                 "message": tx("Koşu {id} üstlenildi; get_next_step ile sürdür.", id=run.run_id)})
