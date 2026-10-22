"""PI planlama raporları: burndown, burnup, kümülatif akış (CFD), velocity/öngörülebilirlik, epik ilerlemesi, kalite, çevrim süresi ve tahmin.

`pi_data(hub)` Jira + sprint durumundan ham sayıları üretir; `render_html(data)` bunları tek dosyalık, bağımsız (JS'siz, SVG) ve yazdırılabilir bir sayfaya çevirir
(PI planlama sunumuna eklenir; tarayıcıdan "PDF olarak yazdır"). Hiçbir veri uydurulmaz: sprint ya da iş yoksa ilgili grafik "veri yok" der.
"""
from __future__ import annotations

import html
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from . import i18n as I18N
from . import sprint as SP
from .i18n import translate as tx, N_


def _dt(v: Any) -> Optional[datetime]:
    if not v:
        return None
    s = str(v).replace("Z", "+00:00")
    for f in (None, "%Y-%m-%d %H:%M:%S"):
        try:
            d = datetime.fromisoformat(s) if f is None else datetime.strptime(s[:19], f)
            return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _first(issue: Dict[str, Any], status: str) -> Optional[datetime]:
    for a in issue.get("audit_trail") or []:
        if a.get("status") == status:
            return _dt(a.get("timestamp"))
    return None


def _last(issue: Dict[str, Any], status: str) -> Optional[datetime]:
    for a in reversed(issue.get("audit_trail") or []):
        if a.get("status") == status:
            return _dt(a.get("timestamp"))
    return None


def _tasks(hub) -> List[Dict[str, Any]]:
    return [i for i in hub.jira_issues.values()
            if str(i.get("kind", "")).lower() == "task" and not i.get("deleted") and i.get("issue_type") in ("TASK", "BUG", "FEATURE")]


def _task_times(i: Dict[str, Any]) -> Tuple[Optional[datetime], Optional[datetime], Optional[datetime]]:
    created = _dt(i.get("created_at"))
    started = _first(i, "IN_PROGRESS")
    done = _last(i, "DONE") if i.get("status") == "DONE" else None
    return created, started, done


def flow_series(hub) -> Dict[str, Any]:
    """Günlük kümülatif akış: kapsam (oluşturulan), devam eden, biten. CFD ve burnup bu seriden çizilir."""
    rows = [(i, *_task_times(i)) for i in _tasks(hub)]
    rows = [r for r in rows if r[1] is not None]
    if not rows:
        return {"days": []}
    start = min(r[1] for r in rows).date()
    end = max(datetime.now(timezone.utc).date(), start)
    days: List[Dict[str, Any]] = []
    d = start
    while d <= end:
        edge = datetime(d.year, d.month, d.day, 23, 59, 59, tzinfo=timezone.utc)
        scope = sum(1 for _, c, _, _ in rows if c <= edge)
        done = sum(1 for _, _, _, dn in rows if dn is not None and dn <= edge)
        prog = sum(1 for _, c, st, dn in rows if c <= edge and st is not None and st <= edge and (dn is None or dn > edge))
        days.append({"day": d.isoformat(), "scope": scope, "done": done, "in_progress": prog, "backlog": max(0, scope - done - prog)})
        d += timedelta(days=1)
    return {"days": days}


def sprint_rows(hub) -> List[Dict[str, Any]]:
    from . import jira_plus as JP
    out: List[Dict[str, Any]] = []
    for sp in SP.ensure_state(hub).get("sprints") or []:
        ids = [i for i in (sp.get("committed_issue_ids") or []) if i in hub.jira_issues]
        items = [hub.jira_issues[i] for i in ids]
        m = sp.get("metrics") or {}
        done = sum(1 for i in items if i.get("status") == "DONE")
        types: Dict[str, int] = {}
        for i in items:
            types[i.get("work_type") or tx("DİĞER")] = types.get(i.get("work_type") or tx("DİĞER"), 0) + 1
        start, end = _dt(sp.get("started_at") or sp.get("committed_at")), _dt(sp.get("closed_at"))
        out.append({"n": sp.get("sprint_number"), "status": sp.get("status"), "goal": sp.get("goal") or "", "committed": len(ids), "done": done,
                    "carried": len(sp.get("carried_over") or []), "scope_changes": len(sp.get("scope_changes") or []),
                    "first_pass": m.get("first_pass_rate"), "fix_rounds": m.get("fix_rounds"), "uat_rejections": m.get("uat_rejections"),
                    "active_min": m.get("active_min"), "wall_h": round((end - start).total_seconds() / 3600, 1) if start and end else None,
                    "bugs": sum(1 for i in items if i.get("issue_type") == "BUG"), "work_types": types,
                    "burndown": [{"ts": p["ts"], "remaining": p["remaining"]} for p in JP._burndown(sp, items)]})
    return out


def epic_rows(hub) -> List[Dict[str, Any]]:
    by = hub.jira_issues
    rows: Dict[str, Dict[str, Any]] = {i["id"]: {"id": i["id"], "key": i.get("key") or i["id"], "title": i.get("title", ""), "total": 0, "done": 0}
                                       for i in by.values() if i.get("issue_type") == "EPIC" and not i.get("deleted")}
    for t in _tasks(hub):
        story = by.get(t.get("parent_id") or "")
        epic_id = (story or {}).get("parent_id") if story and story.get("issue_type") == "STORY" else (t.get("parent_id") if (story or {}).get("issue_type") == "EPIC" else None)
        if epic_id in rows:
            rows[epic_id]["total"] += 1
            rows[epic_id]["done"] += 1 if t.get("status") == "DONE" else 0
    return [r for r in rows.values() if r["total"]]


def cycle_times(hub) -> Dict[str, Any]:
    leads: List[float] = []
    cycles: List[float] = []
    per_sprint: Dict[int, List[float]] = {}
    for t in _tasks(hub):
        c, s, d = _task_times(t)
        if d is None or c is None:
            continue
        lead = (d - c).total_seconds() / 3600
        leads.append(lead)
        if s is not None and d >= s:
            cyc = (d - s).total_seconds() / 3600
            cycles.append(cyc)
            if t.get("closed_in_sprint") or t.get("sprint"):
                per_sprint.setdefault(int(t.get("closed_in_sprint") or t.get("sprint")), []).append(cyc)
    avg = lambda xs: round(sum(xs) / len(xs), 1) if xs else None  # noqa: E731
    return {"avg_lead_h": avg(leads), "avg_cycle_h": avg(cycles), "samples": len(leads),
            "per_sprint": [{"n": n, "avg_cycle_h": avg(v), "count": len(v)} for n, v in sorted(per_sprint.items())]}


UI_ROLES = ("FRONTEND_DEV", "DESIGNER")


def role_activity(hub) -> Dict[str, Any]:
    """Rol bazlı çalışma: biten görev/düzeltme adımları (rol, sprint, süre, commit). Frontend/Designer teslimleri ayrıca listelenir: 'frontend ne zaman, nerede çalıştı' sorusunun cevabı."""
    by_role: Dict[str, Dict[str, Any]] = {}
    by_sprint: Dict[int, Dict[str, int]] = {}
    ui: List[Dict[str, Any]] = []
    seen = set()
    for run in hub.runs.values():
        for st in run.steps:
            if st.status != "DONE" or st.kind not in ("task", "fix") or not st.started_at:
                continue
            key = (run.run_id, st.order, st.kind, st.fix_round, st.started_at)
            if key in seen:
                continue
            seen.add(key)
            a, b = _dt(st.started_at), _dt(st.finished_at)
            mins = round((b - a).total_seconds() / 60, 1) if a and b and b >= a else 0.0
            r = by_role.setdefault(st.role, {"role": st.role, "steps": 0, "minutes": 0.0, "last": ""})
            r["steps"] += 1
            r["minutes"] = round(r["minutes"] + mins, 1)
            r["last"] = max(r["last"], st.finished_at or "")
            if st.sprint:
                by_sprint.setdefault(int(st.sprint), {})[st.role] = by_sprint.get(int(st.sprint), {}).get(st.role, 0) + 1
            if st.role in UI_ROLES:
                ui.append({"order": st.order, "kind": st.kind, "role": st.role, "title": st.title, "sprint": st.sprint, "started_at": st.started_at, "finished_at": st.finished_at,
                           "minutes": mins, "commit": st.commit, "verification": (st.verification or {}).get("status") if isinstance(st.verification, dict) else None})
    ui.sort(key=lambda x: x["started_at"])
    return {"roles": sorted(by_role.values(), key=lambda r: -r["steps"]), "by_sprint": {str(k): v for k, v in sorted(by_sprint.items())}, "ui_work": ui}


def forecast(hub, sprints: List[Dict[str, Any]]) -> Dict[str, Any]:
    tasks = _tasks(hub)
    remaining = sum(1 for t in tasks if t.get("status") != "DONE")
    closed = [s for s in sprints if s["status"] == "CLOSED" and s["done"] is not None]
    last = closed[-3:]
    vel = round(sum(s["done"] for s in last) / len(last), 1) if last else None
    dur = [s["wall_h"] for s in closed[-3:] if s["wall_h"]]
    out: Dict[str, Any] = {"remaining": remaining, "velocity_avg3": vel, "sprint_wall_h": round(sum(dur) / len(dur), 1) if dur else None}
    cap, _ = SP.capacity(hub)
    out["capacity_next"] = cap
    if vel:
        n = -(-remaining // max(vel, 0.1))
        out["sprints_needed"] = int(n)
        if out["sprint_wall_h"]:
            out["eta"] = (datetime.now(timezone.utc) + timedelta(hours=out["sprint_wall_h"] * n)).date().isoformat()
    return out


def sprint_detail(hub, n: int, rows: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Seçili sprintin görev listesi ve ölçümleri (rapor 'Sprint N detayı' bölümü)."""
    sp = SP.get_sprint(hub, n)
    row = next((r for r in rows if r["n"] == n), None)
    if sp is None or row is None:
        return None
    items: List[Dict[str, Any]] = []
    for iid in sp.get("committed_issue_ids") or []:
        i = hub.jira_issues.get(iid)
        if not i:
            continue
        _, started, done = _task_times(i)
        items.append({"key": i.get("key") or i["id"], "title": i.get("title", ""), "assignee": i.get("assignee") or "", "status": i.get("status") or "",
                      "work_type": i.get("work_type") or "", "type": i.get("issue_type") or "",
                      "cycle_h": round((done - started).total_seconds() / 3600, 1) if done and started and done >= started else None})
    return {"n": n, "status": row["status"], "goal": row["goal"], "items": items, "row": row}


def pi_data(hub, sprint: Optional[int] = None) -> Dict[str, Any]:
    sprints = sprint_rows(hub)
    tasks = _tasks(hub)
    closed = [s for s in sprints if s["status"] == "CLOSED"]
    committed, done = sum(s["committed"] for s in closed), sum(s["done"] for s in closed)
    return {"generated_at": datetime.now(timezone.utc).isoformat(), "project": getattr(hub, "active_project_id", ""),
            "summary": {"tasks_total": len(tasks), "tasks_done": sum(1 for t in tasks if t.get("status") == "DONE"),
                        "open_bugs": sum(1 for t in tasks if t.get("issue_type") == "BUG" and t.get("status") != "DONE"),
                        "sprints_closed": len(closed), "predictability": round(done / committed * 100) if committed else None},
            "sprints": sprints, "flow": flow_series(hub)["days"], "roles": role_activity(hub), "epics": epic_rows(hub), "cycle": cycle_times(hub), "forecast": forecast(hub, sprints),
            "selected": sprint, "sprint_options": [{"n": r["n"], "status": r["status"]} for r in sprints],
            "sprint_detail": sprint_detail(hub, sprint, sprints) if sprint else None}


# ---------------------------------------------------------------------------
# SVG
# ---------------------------------------------------------------------------
W, H, PAD_L, PAD_R, PAD_T, PAD_B = 640, 260, 44, 14, 14, 34
COLORS = ["#4f7cff", "#16a34a", "#f59e0b", "#e11d48", "#8b5cf6", "#0ea5e9", "#64748b"]


def _muted(msg: str) -> str:
    return '<p class="muted">' + msg + "</p>"


def _esc(x: Any) -> str:
    return html.escape(str(x))


def _scale(vals: List[float], lo: float = 0.0) -> Tuple[float, float]:
    hi = max(vals) if vals else 1
    return lo, (hi if hi > lo else lo + 1)


def _axes(ymax: float, xlabels: List[Tuple[float, str]]) -> str:
    out = []
    for k in range(5):
        v = ymax * k / 4
        y = H - PAD_B - (H - PAD_T - PAD_B) * k / 4
        out.append(f'<line x1="{PAD_L}" x2="{W - PAD_R}" y1="{y:.1f}" y2="{y:.1f}" class="grid"/><text x="{PAD_L - 6}" y="{y + 4:.1f}" class="tick" text-anchor="end">{v:.0f}</text>')
    for x, lab in xlabels:
        out.append(f'<text x="{x:.1f}" y="{H - PAD_B + 16}" class="tick" text-anchor="middle">{_esc(lab)}</text>')
    return "".join(out)


def _legend(names: List[str]) -> str:
    return '<div class="legend">' + "".join(f'<span><i style="background:{COLORS[i % len(COLORS)]}"></i>{_esc(n)}</span>' for i, n in enumerate(names)) + "</div>"


def line_chart(series: List[Tuple[str, List[Tuple[float, float]]]], xlabels: List[Tuple[float, str]], xmin: float, xmax: float, ymax: float,
               dashed: Tuple[str, ...] = (), step: bool = False) -> str:
    if not any(pts for _, pts in series):
        return _muted(tx("Veri yok."))
    ymax = ymax if ymax > 0 else 1
    px = lambda x: PAD_L + (W - PAD_L - PAD_R) * ((x - xmin) / ((xmax - xmin) or 1))  # noqa: E731
    py = lambda y: H - PAD_B - (H - PAD_T - PAD_B) * (y / ymax)  # noqa: E731
    body = [_axes(ymax, [(px(x), l) for x, l in xlabels])]
    for idx, (name, pts) in enumerate(series):
        if not pts:
            continue
        coords: List[str] = []
        prev: Optional[Tuple[float, float]] = None
        for x, y in pts:
            if step and prev is not None:
                coords.append(f"{px(x):.1f},{py(prev[1]):.1f}")
            coords.append(f"{px(x):.1f},{py(y):.1f}")
            prev = (x, y)
        dash = ' stroke-dasharray="6 4"' if name in dashed else ""
        body.append(f'<polyline fill="none" stroke="{COLORS[idx % len(COLORS)]}" stroke-width="2.2"{dash} points="{" ".join(coords)}"/>')
    return f'<svg viewBox="0 0 {W} {H}" role="img">{"".join(body)}</svg>' + _legend([n for n, _ in series])


def bar_chart(groups: List[str], series: List[Tuple[str, List[float]]], stacked: bool = False, hi: Optional[int] = None) -> str:
    if not groups:
        return _muted(tx("Veri yok."))
    ymax = max((sum(v[g] for _, v in series) if stacked else max(v[g] for _, v in series)) for g in range(len(groups))) or 1
    gw = (W - PAD_L - PAD_R) / len(groups)
    body = [_axes(ymax, [(PAD_L + gw * (g + .5), groups[g]) for g in range(len(groups))])]
    ph = H - PAD_T - PAD_B
    for g in range(len(groups)):
        n = 1 if stacked else len(series)
        bw = min(34.0, gw * .8 / n)
        base = 0.0
        for k, (name, vals) in enumerate(series):
            v = vals[g]
            h = ph * v / ymax
            x = PAD_L + gw * g + (gw - bw * n) / 2 + (0 if stacked else bw * k)
            y = H - PAD_B - h - (ph * base / ymax if stacked else 0)
            body.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bw:.1f}" height="{max(h, 0):.1f}" fill="{COLORS[k % len(COLORS)]}" fill-opacity="{1 if hi is None or g == hi else .3}"><title>{_esc(name)}: {v:g}</title></rect>')
            if stacked:
                base += v
    return f'<svg viewBox="0 0 {W} {H}" role="img">{"".join(body)}</svg>' + _legend([n for n, _ in series])


def area_chart(days: List[Dict[str, Any]], keys: List[Tuple[str, str]]) -> str:
    if len(days) < 2:
        return _muted(tx("Veri yok."))
    ymax = max(d["scope"] for d in days) or 1
    px = lambda i: PAD_L + (W - PAD_L - PAD_R) * i / (len(days) - 1)  # noqa: E731
    py = lambda y: H - PAD_B - (H - PAD_T - PAD_B) * (y / ymax)  # noqa: E731
    step = max(1, len(days) // 6)
    body = [_axes(ymax, [(px(i), days[i]["day"][5:]) for i in range(0, len(days), step)])]
    lower = [0.0] * len(days)
    for k, (key, _) in enumerate(keys):
        upper = [lower[i] + days[i][key] for i in range(len(days))]
        top = " ".join(f"{px(i):.1f},{py(upper[i]):.1f}" for i in range(len(days)))
        bot = " ".join(f"{px(i):.1f},{py(lower[i]):.1f}" for i in reversed(range(len(days))))
        body.append(f'<polygon points="{top} {bot}" fill="{COLORS[k % len(COLORS)]}" fill-opacity=".75"/>')
        lower = upper
    return f'<svg viewBox="0 0 {W} {H}" role="img">{"".join(body)}</svg>' + _legend([lab for _, lab in keys])


def _hbars(rows: List[Dict[str, Any]]) -> str:
    if not rows:
        return _muted(tx("Epik ya da bağlı görev yok."))
    out = []
    for r in sorted(rows, key=lambda r: r["done"] / r["total"]):
        pct = round(r["done"] / r["total"] * 100)
        out.append(f'<div class="hb"><span class="hl" title="{_esc(r["title"])}">{_esc(r["key"])} · {_esc(r["title"][:46])}</span>'
                   f'<span class="bar"><b style="width:{pct}%"></b></span><span class="hv">{r["done"]}/{r["total"]} · %{pct}</span></div>')
    return "".join(out)


def _ts(v: str, t0: datetime, t1: datetime) -> float:
    d = _dt(v)
    return ((d - t0).total_seconds() / 3600) if d else 0.0


def _ths(*names: str) -> str:
    return "".join(f"<th>{tx(n)}</th>" for n in names)


def render_html(d: Dict[str, Any], embed: bool = False, theme: Optional[str] = None) -> str:
    sp, s, fc, cy = d["sprints"], d["summary"], d["forecast"], d["cycle"]
    sel = d.get("selected")
    closed = [x for x in sp if x["status"] == "CLOSED"]
    cur = next((x for x in sp if x["n"] == sel), None) if sel else next((x for x in sp if x["status"] not in ("CLOSED", "CANCELLED")), None)
    labels = [f"S{x['n']}" for x in closed]
    hi = next((i for i, x in enumerate(closed) if x["n"] == sel), None) if sel else None
    no_data = _muted(tx("Veri yok."))
    fmt_h, fmt_min = tx("{v} sa"), tx("{v} dk")

    vel = bar_chart(labels, [(tx("Taahhüt"), [x["committed"] for x in closed]), (tx("Tamamlanan"), [x["done"] for x in closed])], hi=hi)
    pred = line_chart([(tx("Öngörülebilirlik %"), [(i, (x["done"] / x["committed"] * 100) if x["committed"] else 0) for i, x in enumerate(closed)])],
                      [(i, labels[i]) for i in range(len(labels))], 0, max(len(closed) - 1, 1), 100) if closed else _muted(tx("Kapanmış sprint yok."))
    burn = _muted(tx("Çalışan sprint yok."))
    if cur and cur["burndown"]:
        t0 = _dt(cur["burndown"][0]["ts"]) or datetime.now(timezone.utc)
        t1 = _dt(cur["burndown"][-1]["ts"]) or datetime.now(timezone.utc)
        span = max((t1 - t0).total_seconds() / 3600, 0.1)
        real = [(_ts(p["ts"], t0, t1), p["remaining"]) for p in cur["burndown"]]
        ideal = [(0.0, cur["committed"]), (span, 0)]
        ideal_name = tx("İdeal")
        burn = line_chart([(tx("Gerçek"), real), (ideal_name, ideal)], [(0, tx("başlangıç")), (span, fmt_h.format(v=f"{span:.0f}"))], 0, span, cur["committed"], dashed=(ideal_name,), step=True)
    flow = d["flow"]
    cfd = area_chart(flow, [("done", tx("Bitti")), ("in_progress", tx("Devam")), ("backlog", tx("Bekliyor"))])
    bup = no_data
    if len(flow) > 1:
        step = max(1, len(flow) // 6)
        bup = line_chart([(tx("Kapsam"), [(i, f["scope"]) for i, f in enumerate(flow)]), (tx("Biten"), [(i, f["done"]) for i, f in enumerate(flow)])],
                         [(i, flow[i]["day"][5:]) for i in range(0, len(flow), step)], 0, len(flow) - 1, max(f["scope"] for f in flow))
    kinds = sorted({k for x in closed for k in x["work_types"]})
    mix = bar_chart(labels, [(k, [x["work_types"].get(k, 0) for x in closed]) for k in kinds], stacked=True, hi=hi) if closed else no_data
    quality = bar_chart(labels, [(tx("Düzeltme turu"), [x["fix_rounds"] or 0 for x in closed]), (tx("UAT reddi"), [x["uat_rejections"] or 0 for x in closed]),
                                 (tx("Hata (bug)"), [x["bugs"] for x in closed])], hi=hi) if closed else no_data
    fpr = line_chart([(tx("İlk geçiş oranı %"), [(i, (x["first_pass"] or 0) * 100) for i, x in enumerate(closed)])],
                     [(i, labels[i]) for i in range(len(labels))], 0, max(len(closed) - 1, 1), 100) if closed else no_data
    cyc = bar_chart([f"S{x['n']}" for x in cy["per_sprint"]], [(tx("Ort. çevrim süresi (sa)"), [x["avg_cycle_h"] or 0 for x in cy["per_sprint"]])]) if cy["per_sprint"] else no_data

    def card(label: str, val: Any, hint: str = "") -> str:
        return f'<div class="kpi"><b>{_esc(val if val is not None else "—")}</b><span>{_esc(label)}</span><small>{_esc(hint)}</small></div>'

    ra = d.get("roles") or {"roles": [], "by_sprint": {}, "ui_work": []}
    rl_names = {"BACKEND_DEV": "Backend", "FRONTEND_DEV": "Frontend", "DESIGNER": "Designer", "QA": "QA", "DEVOPS": "DevOps", "ARCHITECT": "Architect", "DOCUMENTOR": "Docs", "PO": "PO", "E2E_TESTER": "E2E", "SCRUM_MASTER": "Scrum", "PM": "PM"}
    role_keys = [r["role"] for r in ra["roles"]]
    sp_keys = sorted(ra["by_sprint"], key=lambda k: int(k))
    mix_chart = bar_chart([f"S{k}" for k in sp_keys], [(rl_names.get(rk, rk), [ra["by_sprint"][k].get(rk, 0) for k in sp_keys]) for rk in role_keys], stacked=True) if sp_keys else no_data
    role_rows = "".join(f"<tr><td>{_esc(rl_names.get(r['role'], r['role']))}</td><td>{r['steps']}</td><td>{fmt_h.format(v=round(r['minutes'] / 60, 1))}</td><td>{_esc(str(r['last'])[:16].replace('T', ' '))}</td></tr>" for r in ra["roles"])
    fix_sfx = tx(" (düzeltme)")
    ui_rows = "".join(f"<tr><td>{_esc(str(u['started_at'])[:16].replace('T', ' '))}</td><td>{_esc(rl_names.get(u['role'], u['role']))}</td><td>#{u['order']}{fix_sfx if u['kind'] == 'fix' else ''}</td><td>{_esc(u['title'][:80])}</td>"
                      f"<td>S{u['sprint'] or '-'}</td><td>{fmt_min.format(v=u['minutes'])}</td><td class=\"mono\">{_esc(u['commit'] or '')}</td><td>{_esc(u['verification'] or '')}</td></tr>" for u in ra["ui_work"])
    roles_html = (f'<section style="grid-column:1/-1"><h2>{tx("Rol bazlı çalışma")}</h2><p class="note">{tx("Biten görev ve düzeltme adımları: hangi rol, hangi sprintte, ne kadar çalıştı.")}</p>'
                  f'<div class="grid2"><div>{mix_chart}</div><table><thead><tr>{_ths(N_("Rol"), N_("Biten adım"), N_("Toplam süre"), N_("Son çalışma (UTC)"))}</tr></thead><tbody>{role_rows}</tbody></table></div></section>'
                  f'<section style="grid-column:1/-1"><h2>{tx("Frontend / Designer teslimleri")}</h2><p class="note">{tx("Arayüz işinin ne zaman ve hangi commit ile teslim edildiği.")}</p>'
                  + (f'<table><thead><tr>{_ths(N_("Başladı (UTC)"), N_("Rol"), N_("Adım"), N_("İş"), N_("Sprint"), N_("Süre"), N_("Commit"), N_("Doğrulama"))}</tr></thead><tbody>{ui_rows}</tbody></table>' if ui_rows else _muted(tx("Henüz frontend ya da designer teslimi yok.")))
                  + '</section>')
    det = d.get("sprint_detail")
    if det:
        r = det["row"]
        kpi_list = [card(f"Sprint {det['n']} · {det['status']}", f"{r['done']}/{r['committed']}", tx("biten / taahhüt")), card(tx("Taşınan"), r["carried"]), card(tx("Kapsam değişikliği"), r["scope_changes"]),
                    card(tx("İlk geçiş"), f"%{round(r['first_pass'] * 100)}" if r["first_pass"] is not None else None), card(tx("Düzeltme turu"), r["fix_rounds"]),
                    card(tx("UAT reddi"), r["uat_rejections"]), card(tx("Aktif süre"), fmt_min.format(v=r['active_min']) if r["active_min"] is not None else None),
                    card(tx("Duvar saati"), fmt_h.format(v=r['wall_h']) if r["wall_h"] is not None else None)]
        kpis = "".join(kpi_list)
        trs = "".join(f"<tr><td>{_esc(i['key'])}</td><td>{_esc(i['title'][:90])}</td><td>{_esc(i['type'])}</td><td>{_esc(i['work_type'])}</td><td>{_esc(i['assignee'])}</td>"
                      f"<td>{_esc(i['status'])}</td><td>{'' if i['cycle_h'] is None else fmt_h.format(v=i['cycle_h'])}</td></tr>" for i in det["items"])
        detail_html = (f'<section style="margin-top:12px"><h2>{tx("Sprint {n} görevleri", n=det["n"])}</h2><p class="note">{_esc(det["goal"])}</p>'
                       f'<table><thead><tr>{_ths(N_("Anahtar"), N_("Başlık"), N_("Tür"), N_("İş türü"), N_("Rol"), N_("Durum"), N_("Çevrim"))}</tr></thead><tbody>{trs}</tbody></table></section>')
    else:
        detail_html = ""
    kpis = kpis if det else "".join([
        card(tx("Biten / toplam görev"), f"{s['tasks_done']}/{s['tasks_total']}"), card(tx("Kapanan sprint"), s["sprints_closed"]),
        card(tx("Öngörülebilirlik"), f"%{s['predictability']}" if s["predictability"] is not None else None, tx("biten ÷ taahhüt")),
        card(tx("Açık hata"), s["open_bugs"]), card(tx("Hız (son 3 ort.)"), fc.get("velocity_avg3"), tx("görev/sprint")),
        card(tx("Kalan iş"), fc["remaining"], f"≈ {fc['sprints_needed']} sprint" if fc.get("sprints_needed") else ""),
        card(tx("Tahmini bitiş"), fc.get("eta"), tx("mevcut hızla")), card(tx("Ort. çevrim süresi"), fmt_h.format(v=cy['avg_cycle_h']) if cy["avg_cycle_h"] is not None else None, tx("lead {v} sa", v=cy['avg_lead_h'])),
    ])
    rows = "".join(f"<tr><td>S{x['n']}</td><td>{_esc(x['status'])}</td><td>{x['committed']}</td><td>{x['done']}</td><td>{x['carried']}</td><td>{x['scope_changes']}</td>"
                   f"<td>{'' if x['first_pass'] is None else str(round(x['first_pass'] * 100)) + '%'}</td><td>{x['fix_rounds'] if x['fix_rounds'] is not None else ''}</td>"
                   f"<td>{x['active_min'] if x['active_min'] is not None else ''}</td><td class=\"goal\">{_esc(x['goal'][:140])}</td></tr>" for x in sp)
    print_btn = "" if embed else '<button onclick="window.print()">' + tx("Yazdır / PDF") + '</button>'
    sub = tx("Proje: {project} · üretim: {generated} UTC · kaynak: Jira görevleri ve sprint kayıtları", project=_esc(d['project']), generated=_esc(d['generated_at'][:16].replace('T', ' ')))
    forecast_note = tx("Tahmin: kalan {remaining} görev ÷ son 3 sprintin ortalama hızı; kapasite tabanı ve kapsam artışı hesaba katılmaz. Bitiş tarihi bir taahhüt değil, mevcut hızın uzantısıdır.", remaining=fc['remaining'])
    return f"""<!doctype html><html lang="{I18N.current()}"{(" data-theme=" + chr(34) + theme + chr(34)) if theme in ("light", "dark") else ""}><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{tx('PI Planlama Raporları')}</title><style>
:root{{--bg:#f6f7fb;--card:#fff;--ink:#14171f;--mut:#667085;--line:#e3e6ee;--ac:#4f7cff}}
@media (prefers-color-scheme:dark){{:root:not([data-theme=light]){{--bg:#0f1218;--card:#181c25;--ink:#e8ebf2;--mut:#98a2b3;--line:#2a3040}}}}
:root[data-theme=dark]{{--bg:#0f1218;--card:#181c25;--ink:#e8ebf2;--mut:#98a2b3;--line:#2a3040}}
body{{margin:0;background:var(--bg);color:var(--ink);font:14px/1.5 system-ui,Segoe UI,sans-serif}}
main{{max-width:1180px;margin:0 auto;padding:20px 16px 40px}}
h1{{font-size:22px;margin:0}}h2{{font-size:15px;margin:0 0 8px}}.sub{{color:var(--mut);margin:2px 0 16px}}
.kpis{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin-bottom:16px}}
.kpi{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:10px 12px;display:flex;flex-direction:column}}
.kpi b{{font-size:22px}}.kpi span{{color:var(--mut);font-size:12px}}.kpi small{{color:var(--mut);font-size:11px;min-height:14px}}
.grid2{{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,440px),1fr));gap:12px}}
section{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px 14px;break-inside:avoid}}
section p.note{{color:var(--mut);font-size:12px;margin:0 0 6px}}
svg{{width:100%;height:auto}}.grid{{stroke:var(--line)}}.tick{{fill:var(--mut);font-size:10px}}
.legend{{display:flex;flex-wrap:wrap;gap:10px;font-size:12px;color:var(--mut)}}.legend i{{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:4px}}
.muted{{color:var(--mut)}}table{{width:100%;border-collapse:collapse;font-size:12px}}th,td{{padding:5px 6px;border-bottom:1px solid var(--line);text-align:left}}
td.goal{{color:var(--mut);max-width:340px}}.hb{{display:grid;grid-template-columns:minmax(120px,1.2fr) 2fr auto;gap:8px;align-items:center;margin:5px 0;font-size:12px}}
.hl{{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}.bar{{height:10px;background:var(--line);border-radius:6px;overflow:hidden}}.bar b{{display:block;height:100%;background:var(--ac)}}
.hv{{color:var(--mut);white-space:nowrap}}button{{float:right;border:1px solid var(--line);background:var(--card);color:var(--ink);padding:6px 12px;border-radius:8px;cursor:pointer}}
@media print{{body{{background:#fff}}button{{display:none}}section{{break-inside:avoid}}}}
</style></head><body><main>
{print_btn}
<h1>{tx('PI Planlama Raporları')}{(' · Sprint ' + str(sel)) if sel else ''}</h1>
<p class="sub">{sub}</p>
<div class="kpis">{kpis}</div>
<div class="grid2">
<section><h2>Sprint burndown {('(Sprint ' + str(cur['n']) + ')') if cur else ''}</h2><p class="note">{tx('Sprint taahhüdündeki işin kalanı; kesikli çizgi ideal gidiş.')}</p>{burn}</section>
<section><h2>{tx('Velocity: taahhüt ve tamamlanan')}</h2><p class="note">{tx('Kapanan sprintlerde taahhüt edilen ve biten görev sayısı.')}</p>{vel}</section>
<section><h2>{tx('Burnup: kapsam ve biten')}</h2><p class="note">{tx('Toplam kapsamın (oluşturulan görev) zamanla büyümesi ve biten iş.')}</p>{bup}</section>
<section><h2>{tx('Kümülatif akış (CFD)')}</h2><p class="note">{tx('Bekleyen / devam eden / biten iş; devam eden bandın genişlemesi darboğaz işaretidir.')}</p>{cfd}</section>
<section><h2>{tx('Öngörülebilirlik')}</h2><p class="note">{tx('Sprint başına biten ÷ taahhüt (%100 hedef).')}</p>{pred}</section>
<section><h2>{tx('İş türü dağılımı')}</h2><p class="note">{tx('Sprint taahhüdünün iş türüne göre kırılımı (özellik / test / refactor / hata).')}</p>{mix}</section>
<section><h2>{tx('Kalite')}</h2><p class="note">{tx('Düzeltme turu, UAT reddi ve hata sayısı (sprint başına).')}</p>{quality}</section>
<section><h2>{tx('İlk geçiş oranı')}</h2><p class="note">{tx('Doğrulamayı ilk teslimde geçen görev oranı.')}</p>{fpr}</section>
<section><h2>{tx('Çevrim süresi')}</h2><p class="note">{tx('İş başladıktan bitene kadar geçen ortalama saat.')}</p>{cyc}</section>
{roles_html}
<section><h2>{tx('Epik ilerlemesi (yol haritası)')}</h2><p class="note">{tx('Epik altındaki görevlerin tamamlanma oranı.')}</p>{_hbars(d['epics'])}</section>
</div>
{detail_html}
<section style="margin-top:12px"><h2>{tx('Sprint özeti')}</h2><table><thead><tr>{_ths(N_("Sprint"), N_("Durum"), N_("Taahhüt"), N_("Biten"), N_("Taşınan"), N_("Kapsam değ."), N_("İlk geçiş"), N_("Düz. turu"), N_("Aktif dk"), N_("Hedef"))}</tr></thead><tbody>{rows}</tbody></table></section>
<p class="muted" style="margin-top:12px">{forecast_note}</p>
</main></body></html>"""
