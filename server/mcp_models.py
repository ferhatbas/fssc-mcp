"""
MCP araçlarının yapılandırılmış dönüş modelleri (Pydantic → structured_content).
Alanlar `LocalRunsApi` / `ProxyRunsApi` sözlükleriyle birebir uyumludur; fazladan anahtarlar korunur.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field
from .i18n import translate as tx


class _Loose(BaseModel):
    model_config = ConfigDict(extra="allow")


class RunInfo(_Loose):
    status: str = Field(description="STARTED | EXISTING | CANCELLED | ...")
    run: Dict[str, Any] = Field(default_factory=dict)
    message: str = ""


PENDING_STEPS_SHOWN = 12


def compact_run(run: Dict[str, Any]) -> Dict[str, Any]:
    """MCP istemcisine giden koşu özeti. Tam koşu kaydı (her adımın doğrulama çıktısı, özeti, DoD'u) yüzlerce KB olur ve istemcinin bağlamını doldurur;
    istemciye yalnızca koşunun kimliği, durumu, ilerlemesi ve sıradaki birkaç adım lazım (ayrıntı `get_next_step` ile gelir, tam kayıt panoda/REST'te)."""
    if not isinstance(run, dict):
        return {}
    out = {k: v for k, v in run.items() if k != "steps" and not isinstance(v, (list, dict))}
    for k in ("progress", "manager_notes"):
        if k in run:
            out[k] = run[k] if k == "progress" else [{"text": str(n.get("text", ""))[:300], "urgent": n.get("urgent")} for n in (run[k] or [])[-5:] if isinstance(n, dict)]
    steps = [s for s in (run.get("steps") or []) if isinstance(s, dict)]
    pending = [s for s in steps if s.get("status") not in ("DONE", "SKIPPED")]
    out["steps_total"] = len(steps)
    out["steps_done"] = sum(1 for s in steps if s.get("status") == "DONE")
    out["next_steps"] = [{"order": s.get("order"), "role": s.get("role"), "status": s.get("status"), "kind": s.get("kind"), "title": str(s.get("title") or "")[:80]}
                         for s in pending[:PENDING_STEPS_SHOWN]]
    out["note"] = tx("Özet görünüm: ayrıntı için get_next_step(run_id); tam koşu kaydı panoda ya da GET /api/runs/<run_id>.")
    return out


class NextStep(_Loose):
    status: str = Field(description="STEP | WAITING_APPROVAL | RUN_COMPLETE | CANCELLED | PAUSED | BLOCKED | SESSION_BOUNDARY")
    run_id: str
    order: Optional[int] = None
    issue_id: Optional[str] = None
    agent_id: Optional[str] = None
    agent_name: Optional[str] = None
    agent_profile: Optional[Dict[str, Any]] = Field(default=None, description="Ajan profili ipuçları: model, effort, language, max_tokens, tools_allow (G6)")
    next_agent_id: Optional[str] = None
    action: Optional[str] = None
    title: Optional[str] = None
    critical: Optional[bool] = None
    system_prompt: Optional[str] = None
    user_context: Optional[str] = None
    output_contract: Optional[str] = None
    approval_mode: Optional[str] = None
    pacing: Optional[str] = None
    attempt: Optional[int] = None
    approval_token: Optional[str] = None
    progress: Optional[str] = None
    todo_title: Optional[str] = None
    instructions: Optional[str] = None
    kind: Optional[str] = Field(default=None, description="phase | task | fix")
    fix_round: Optional[int] = None
    task_key: Optional[str] = None
    total_steps: Optional[int] = None
    message: str = ""


class SubmitResult(_Loose):
    status: str = Field(description="NEXT | WAITING_APPROVAL | RUN_COMPLETE | REJECTED | SESSION_BOUNDARY | BLOCKED")
    run_id: str
    order: Optional[int] = None
    next_order: Optional[int] = None
    next_kind: Optional[str] = None
    approval_token: Optional[str] = None
    validation_errors: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    attempt: Optional[int] = None
    verification: Optional[Dict[str, Any]] = Field(default=None, description="Sunucu doğrulaması özeti (status, summary, results)")
    commit: Optional[str] = None
    fix_requested: bool = False
    inserted_steps: int = Field(default=0, description="Bu teslimden sonra koşuya eklenen adım sayısı (backlog/düzeltme/iyileştirme)")
    total_steps: Optional[int] = None
    message: str = ""


class ApprovalStatus(_Loose):
    status: str = Field(description="APPROVED | STILL_WAITING | REJECTED | CANCELLED | REVISE (yönetici revize istedi: aynı adımı get_next_step ile yeniden al)")
    run_id: str
    order: Optional[int] = None
    next: Optional[str] = None
    next_order: Optional[int] = None
    run_status: Optional[str] = None
    message: str = ""


class ClaimResult(_Loose):
    status: str = Field(description="CLAIMED | IDLE | BLOCKED")
    reason: Optional[str] = None
    run_id: Optional[str] = None
    message: str = ""
    display_md: Optional[str] = None


class RunList(_Loose):
    runs: List[Dict[str, Any]] = Field(default_factory=list)
    active_run_id: Optional[str] = None


class DeliberationInfo(_Loose):
    status: str
    session: Dict[str, Any] = Field(default_factory=dict)
    participants: List[Dict[str, Any]] = Field(default_factory=list)
    turn_order: List[str] = Field(default_factory=list)
    instructions: str = ""
