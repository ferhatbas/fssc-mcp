"""Öğrenme döngüsü (F7, belge §8.5): retro aksiyonlarının uygulanması ve prompt değişikliğinin ölçüme bağlı geri alınması.

Retro, izlenime değil sunucunun ölçtüğü metriklere dayanır (`sprint.summarize`). Her aksiyon üç tipten biridir:
- `PROCESS`: proje ayarına yazılır — korkuluk ve bütçe ayarları (`autonomy.*`, `sandbox.*`, `sprint.*`) HARİÇ (§3.2).
- `PROMPT`: projenin kendi ajan promptu kopyasına yeni **sürüm** olarak yazılır. Sprint başına en çok `autonomy.retro.max_prompt_changes_per_sprint`
  değişiklik; izleyen sprintte ilk seferde geçme oranı düşerse değişiklik kendiliğinden geri alınır. Global standarda terfi yalnızca yöneticidir.
- `BACKLOG`: yeni iş maddesi.
"""
from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from . import fs_workspace as FW
from .i18n import translate as tx, N_
from . import guard as G
from . import meetings as M
from . import sprint as SP

SECTION = "## Retro Kuralları (otomatik, SCRUM_MASTER)"   # ajan prompt dosyasında aranan başlık: dilden bağımsız sabit (mantık metni)
LLM_AGENTS = ("PM", "ARCHITECT", "BACKEND_DEV", "FRONTEND_DEV", "DESIGNER", "QA", "DEVOPS", "PO", "DOCUMENTOR", "REPORTER", "SCRUM_MASTER")
PROCESS_KEYS = {"settings.max_fix_rounds": (1, 6), "settings.max_backlog_tasks": (1, 50), "settings.max_uat_rounds": (0, 5)}
VERIFY_KEYS = ("install", "lint", "build", "test")
# Korkulukları gevşeten prompt kuralı girişimi (çok kaba; kural eklemek serbest, gevşetmek değil)
_LOOSEN = re.compile(r"(?i)(yoksay|görmezden\s+gel|ignore\s+(all|previous|the)|testleri?\s+(sil|atla|kapat)\b|doğrulamayı\s+kapat|onay(ı)?\s+(alma|atla|bekleme)|onay\s*istemeden|"
                     r"teknoloji(yi)?\s+(kendin\s+)?seç|disable\s+(tests?|verification)|skip\s+(tests?|verification)|promote|global(e)?\s+terfi)")


def _iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def state(hub) -> Dict[str, Any]:
    st = SP.ensure_state(hub)
    st.setdefault("prompt_changes", [])
    st.setdefault("retro_actions", [])
    return st


def first_pass_rate(metrics: Optional[Dict[str, Any]]) -> Optional[float]:
    """İlk seferde geçen / taahhüt edilen (taşınan iş geçmiş sayılmaz)."""
    m = metrics or {}
    return round(m["first_pass"] / m["committed"], 4) if m.get("committed") else None


# ---------------------------------------------------------------------------
# Aksiyonların doğrulanması ve uygulanması
# ---------------------------------------------------------------------------
async def apply_retro_actions(hub, run, sp: Dict[str, Any], project_dir: str, create_task) -> List[Dict[str, Any]]:
    n = sp["sprint_number"]
    st = state(hub)
    actions = list((sp.get("retro") or {}).get("action_items") or [])
    limit = M.autonomy(hub)["retro"]["max_prompt_changes_per_sprint"]
    prompt_changes = 0
    out: List[Dict[str, Any]] = []
    for i, a in enumerate(actions, 1):
        rec: Dict[str, Any] = {"id": f"RA-{n}-{i}", "sprint": n, "type": a["type"], "target": str(a.get("target") or ""), "value": a.get("value"),
                               "reason": str(a.get("reason") or "")[:300], "status": "REJECTED", "detail": "", "applied_at": None}
        try:
            if a["type"] == "PROCESS":
                rec.update(await _apply_process(hub, rec))
            elif a["type"] == "PROMPT":
                if prompt_changes >= limit:
                    rec["detail"] = tx("sprint başına en çok {limit} prompt değişikliği (autonomy.retro.max_prompt_changes_per_sprint)", limit=limit)
                else:
                    res = await _apply_prompt(hub, run, sp, rec, project_dir)
                    rec.update(res)
                    if res["status"] == "APPLIED":
                        prompt_changes += 1
            elif a["type"] == "BACKLOG":
                rec.update(await _apply_backlog(hub, rec, create_task))
        except Exception as e:  # noqa: BLE001 — bir aksiyon başarısız olsa da retro kapanır
            rec["status"], rec["detail"] = "REJECTED", tx("uygulanamadı: {err}", err=str(e)[:160])
        out.append(rec)
        st["retro_actions"].append(rec)
        await hub.record_event(trace_id=run.run_id, from_agent="SCRUM_MASTER", to_agent="ALL", action="RETRO_ACTION_" + rec["status"], status="SUCCESS" if rec["status"] == "APPLIED" else "FAILED",
                               payload={k: rec[k] for k in ("id", "type", "target", "status", "detail")},
                               friendly_dialogue=tx("Retro aksiyonu {id} ({type}): {status}", id=rec["id"], type=rec["type"], status=rec["status"]) + (f" — {rec['detail']}" if rec["detail"] else ""))
    sp["retro_actions"] = [r["id"] for r in out]
    hub.mark_dirty()
    return out


async def _apply_process(hub, rec: Dict[str, Any]) -> Dict[str, Any]:
    target = rec["target"]
    if target in PROCESS_KEYS:
        lo, hi = PROCESS_KEYS[target]
        try:
            val = int(rec["value"])
        except (TypeError, ValueError):
            return {"status": "REJECTED", "detail": tx("değer tamsayı olmalı")}
        if not lo <= val <= hi:
            return {"status": "REJECTED", "detail": tx("değer {lo}-{hi} aralığında olmalı", lo=lo, hi=hi)}
        key = target.split(".", 1)[1]
        before = hub.get_settings().get(key)
        await hub.update_settings({key: val})
        return {"status": "APPLIED", "detail": f"{target}: {before} → {val}", "before": before, "after": val, "applied_at": _iso()}
    m = re.match(r"^settings\.verification\.(install|lint|build|test)$", target)
    if m:
        from .verify import sanitize_verification
        cmd = str(rec["value"] or "")
        ok, bad = G.command_allowed(hub, cmd)
        if not ok:
            return {"status": "REJECTED", "detail": tx("komut izin listesi dışında: ") + "; ".join(bad)[:120]}
        clean = sanitize_verification({m.group(1): cmd})
        if not clean:
            return {"status": "REJECTED", "detail": tx("komut güvenli değil")}
        ver = hub.get_settings().get("verification") or {}
        await hub.update_settings({"verification": {**ver, **clean}})
        return {"status": "APPLIED", "detail": tx("verification.{key} güncellendi", key=m.group(1)), "before": ver.get(m.group(1)), "after": clean[m.group(1)], "applied_at": _iso()}
    if re.match(r"^(settings\.)?(autonomy|sandbox|sprint|runner)\b", target) or "budget" in target:
        return {"status": "REJECTED", "detail": tx("korkuluk/bütçe/otonomi ayarı retro ile değiştirilemez (yalnızca yönetici, §3.2)")}
    return {"status": "REJECTED", "detail": tx("bilinmeyen ya da izinli olmayan hedef: {target}", target=target or "-")}


async def _apply_backlog(hub, rec: Dict[str, Any], create_task) -> Dict[str, Any]:
    title = str(rec["value"] or rec["target"] or "").strip()
    if re.fullmatch(r"[A-Za-z]{1,5}[-_ ]?\d{1,4}", title) or len(title) < 8:
        # "N-2" gibi yalnızca bir kimlik/çok kısa ad: başlık gerekçenin ilk cümlesinden türetilir (panoda anlamsız başlık kalmasın)
        first = re.split(r"(?<=[.!?;:])\s", " ".join(str(rec.get("reason") or "").split()), maxsplit=1)[0].strip(" .;:")
        title = (first[:100] or title)
    if not title:
        return {"status": "REJECTED", "detail": tx("başlık boş")}
    await create_task([{"task_key": "RETRO", "title": title[:160], "role": "BACKEND_DEV", "work_type": "IMPROVEMENT", "priority": "P2",
                        "description": tx("Retro aksiyonu {id}: {reason}", id=rec["id"], reason=rec["reason"]), "acceptance_criteria": [tx("Retro aksiyonu uygulanır ve doğrulanır")],
                        "depends_on": [], "ac_refs": [], "story_ref": "", "files_hint": []}])
    return {"status": "APPLIED", "detail": tx("backlog maddesi açıldı"), "applied_at": _iso()}


async def _apply_prompt(hub, run, sp: Dict[str, Any], rec: Dict[str, Any], project_dir: str) -> Dict[str, Any]:
    agent = rec["target"].upper()
    rule = " ".join(str(rec["value"] or "").split())[:400]
    if agent not in LLM_AGENTS or agent not in hub.agents:
        return {"status": "REJECTED", "detail": tx("prompt değişikliği yalnızca LLM rolleri için: {agent}", agent=agent or "-")}
    if not rule:
        return {"status": "REJECTED", "detail": tx("kural metni boş")}
    if _LOOSEN.search(rule):
        return {"status": "REJECTED", "detail": tx("korkuluğu gevşeten kural eklenemez (yalnızca kural eklenebilir, gevşetilemez)")}
    role = hub.agents[agent].get("role", agent)
    info = FW.get_agent_markdown_info(project_dir, agent, role)
    prev_version = info["current_version"]
    content = info["active_content"]
    line = "- [" + tx("Sprint {n} · {id}", n=sp["sprint_number"], id=rec["id"]) + f"] {rule}"
    if SECTION in content:
        head, _, tail = content.partition(SECTION)
        content = head + SECTION + "\n" + line + "\n" + tail.lstrip("\n")
    else:
        content = content.rstrip("\n") + f"\n\n{SECTION}\n{line}\n"
    new = FW.save_agent_markdown(project_dir, agent, role, content, tx("Retro aksiyonu {id}: {rule}", id=rec["id"], rule=rule[:120]), author="SCRUM_MASTER (retro)")
    baseline = first_pass_rate(sp.get("metrics"))
    change = {"id": f"PC-{len(state(hub)['prompt_changes']) + 1}", "agent": agent, "role": role, "action": rec["id"], "sprint": sp["sprint_number"],
              "evaluate_sprint": sp["sprint_number"] + 1, "prev_version": prev_version, "new_version": new["current_version"], "rule": rule,
              "baseline_first_pass_rate": baseline, "status": "WATCHING", "created_at": _iso(), "evaluated": None, "project_dir": project_dir}
    state(hub)["prompt_changes"].append(change)
    await hub.broadcast({"type": "PROMPT_CHANGED", "change": {k: v for k, v in change.items() if k != "project_dir"}})
    return {"status": "APPLIED", "detail": tx("{agent} promptu {prev} → {new}", agent=agent, prev=prev_version, new=new["current_version"]), "version": new["current_version"], "prompt_change": change["id"], "applied_at": _iso()}


# ---------------------------------------------------------------------------
# Ölçüme bağlı geri alma (§8.5)
# ---------------------------------------------------------------------------
async def evaluate_prompt_changes(hub, run, sp: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Önceki sprintte yazılan prompt değişikliklerini bu sprintin ölçümüyle karşılaştırır: ilk seferde geçme oranı düşmüşse sürüm geri alınır."""
    n = sp["sprint_number"]
    now_rate = first_pass_rate(sp.get("metrics"))
    results: List[Dict[str, Any]] = []
    for ch in state(hub)["prompt_changes"]:
        if ch["status"] != "WATCHING" or ch["evaluate_sprint"] > n:
            continue
        base = ch["baseline_first_pass_rate"]
        if now_rate is None or base is None:
            ch["evaluate_sprint"] = n + 1               # örneklem yok: bir sonraki sprinte ertelenir
            continue
        ev = {"sprint": n, "first_pass_rate": now_rate, "baseline": base, "at": _iso()}
        if now_rate < base:
            try:
                restored = FW.restore_agent_version(ch["project_dir"], ch["agent"], ch["role"], ch["prev_version"], author="SCRUM_MASTER (otomatik geri alma)")
                ch["status"], ch["rolled_back_to"], ch["restored_version"] = "ROLLED_BACK", ch["prev_version"], restored["current_version"]
            except Exception as e:  # noqa: BLE001
                ch["status"], ev["error"] = "ROLLBACK_FAILED", str(e)[:160]
        else:
            ch["status"] = "CONFIRMED"
        ch["evaluated"] = ev
        await hub.record_event(
            trace_id=run.run_id, from_agent="SCRUM_MASTER", to_agent=ch["agent"], action="PROMPT_" + ch["status"], status="FAILED" if ch["status"] != "CONFIRMED" else "SUCCESS",
            payload={"change": ch["id"], **ev}, friendly_dialogue=(
                tx("{agent} prompt değişikliği ({id}) geri alındı: ilk seferde geçme oranı %{base:.0f} → %{now:.0f}.", agent=ch["agent"], id=ch["id"], base=base * 100, now=now_rate * 100) if ch["status"] == "ROLLED_BACK"
                else tx("{agent} prompt değişikliği ({id}) doğrulandı: oran %{base:.0f} → %{now:.0f}.", agent=ch["agent"], id=ch["id"], base=base * 100, now=now_rate * 100)))
        await hub.broadcast({"type": "PROMPT_" + ch["status"], "change": {k: v for k, v in ch.items() if k != "project_dir"}})
        results.append(ch)
    hub.mark_dirty()
    return results


async def rollback_prompt_change(hub, change_id: str, author: str = "MANAGER") -> Dict[str, Any]:
    """Yönetici elle geri alır (aynı mekanizma)."""
    ch = next((c for c in state(hub)["prompt_changes"] if c["id"] == change_id), None)
    if ch is None:
        raise KeyError(change_id)
    if ch["status"] in ("ROLLED_BACK",):
        raise ValueError(tx("Bu değişiklik zaten geri alındı."))
    restored = FW.restore_agent_version(ch["project_dir"], ch["agent"], ch["role"], ch["prev_version"], author=f"{author} (geri alma)")
    ch.update({"status": "ROLLED_BACK", "rolled_back_to": ch["prev_version"], "restored_version": restored["current_version"], "rolled_back_by": author})
    await hub.broadcast({"type": "PROMPT_ROLLED_BACK", "change": {k: v for k, v in ch.items() if k != "project_dir"}})
    hub.mark_dirty()
    return ch


# ---------------------------------------------------------------------------
# Rapor: eğilim ve uygulanma oranı (SCRUM_MASTER başarı ölçütü, §6.3)
# ---------------------------------------------------------------------------
def learning_report(hub) -> Dict[str, Any]:
    st = state(hub)
    trend = [{"sprint": s["sprint_number"], "status": s["status"], "committed": (s.get("metrics") or {}).get("committed"),
              "completed": (s.get("metrics") or {}).get("completed"), "first_pass_rate": first_pass_rate(s.get("metrics")),
              "fix_rounds": (s.get("metrics") or {}).get("fix_rounds"), "rejected_deliveries": (s.get("metrics") or {}).get("rejected_deliveries"),
              "carried": len(s.get("carried_over") or []), "roles": (s.get("metrics") or {}).get("roles")}
             for s in st["sprints"] if s.get("metrics")]
    actions = st["retro_actions"]
    applied = [a for a in actions if a["status"] == "APPLIED"]
    return {"trend": trend, "retro_actions": actions, "applied_ratio": round(len(applied) / len(actions), 3) if actions else None,
            "prompt_changes": [{k: v for k, v in c.items() if k != "project_dir"} for c in st["prompt_changes"]]}


def planning_inputs(hub, n: int) -> List[str]:
    """Planlama toplantısının girdisi: önceki retro aksiyonlarının uygulanma durumu ve izlenen prompt değişiklikleri (SCRUM_MASTER doğrular)."""
    st = state(hub)
    lines = [tx("Retro aksiyonu (Sprint {sprint}) {id} [{type}]: {status}", sprint=a["sprint"], id=a["id"], type=a["type"], status=a["status"]) + (f" — {a['detail']}" if a.get("detail") else "")
             for a in st["retro_actions"] if a["sprint"] == n - 1]
    lines += [tx("Prompt değişikliği {id} ({agent} {prev}→{new}) izleniyor; taban ilk-seferde-geçme %{base:.0f}", id=c["id"], agent=c["agent"], prev=c["prev_version"], new=c["new_version"], base=(c["baseline_first_pass_rate"] or 0) * 100)
              for c in st["prompt_changes"] if c["status"] == "WATCHING"]
    return lines
