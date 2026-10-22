"""
Pipeline Koşu Modeli (PipelineRun / StepRecord).

Bir koşu; seçilen Jira adımlarının sıralı listesi, imleç (cursor) ve durum makinesidir.
Motor bağımsızdır: hem süreç içi şablon motoru hem de Claude Desktop / Antigravity gibi
MCP istemcilerinin çektiği (pull) adımlar aynı kaydı günceller.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

RUN_STATUSES = ("QUEUED", "ACTIVE", "WAITING_APPROVAL", "COMPLETED", "CANCELLED", "ABANDONED", "FAILED")
STEP_STATUSES = ("PENDING", "ACTIVE", "WAITING_APPROVAL", "DONE", "REJECTED", "FAILED", "SKIPPED")
TERMINAL_RUN_STATUSES = {"COMPLETED", "CANCELLED", "ABANDONED", "FAILED"}
ENGINES = ("template", "mcp_client")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class StepRecord:
    order: int
    issue_id: str
    role: str
    status: str = "PENDING"
    attempts: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    artifacts: List[str] = field(default_factory=list)
    summary: str = ""
    action: str = ""
    error: Optional[str] = None
    server_side: bool = False
    validation_errors: List[str] = field(default_factory=list)
    prompt_chars: int = 0
    # Tam yaşam döngüsü alanları
    kind: str = "phase"              # 'phase' (1-10 fazı) | 'task' (backlog görevi) | 'fix' (doğrulama sonrası düzeltme)
    title: str = ""                  # görev/adım başlığı (dinamik adımlarda Jira başlığı)
    fix_round: int = 0               # bu adım kaçıncı düzeltme turu (0 = asıl uygulama)
    round: int = 1                   # faz adımı kaçıncı kez koşuyor (PO reddi sonrası 2. tur gibi)
    verification: Optional[Dict[str, Any]] = None  # sunucu tarafı doğrulama özeti (test/build/lint)
    commit: Optional[str] = None     # SCM commit kısa hash'i
    # Sprint kipi (F3): iş türü ve ait olduğu sprint. kind: 'plan' | 'close' | 'rescope' | 'structure' sunucu/akış adımlarıdır
    work_type: str = ""
    sprint: Optional[int] = None
    # F6: kalite kapıları
    commit_status: str = ""          # COMMITTED | NOTHING | SKIPPED | FAILED | SECRET
    dod: Optional[List[Dict[str, Any]]] = None   # sıkı DoD koşulları (autonomy.strict_dod)
    error_sig: str = ""              # başarısız doğrulamanın hata imzası (döngü kırıcı)
    commit_note: str = ""            # commit durdu/atlandıysa nedeni (ör. sır bulgusu)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "StepRecord":
        known = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
        return cls(**known)


@dataclass
class PipelineRun:
    project_id: str
    engine: str = "mcp_client"
    steps: List[StepRecord] = field(default_factory=list)
    run_id: str = field(default_factory=lambda: f"run-{uuid.uuid4().hex[:10]}")
    cursor: int = 0
    status: str = "QUEUED"
    custom_prompt: str = ""
    client_name: str = ""
    client_version: str = ""
    created_at: str = field(default_factory=_now)
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    last_seen: str = field(default_factory=_now)
    approval_token: Optional[str] = None
    cancel_reason: str = ""
    step_by_step: bool = True
    project_dir: str = ""
    paused: bool = False  # kullanıcı duraklattı: istemciye yeni adım verilmez
    pause_reason: str = ""
    gate_kind: str = ""  # açık onay kapısının türü: 'step' | 'decisions'
    # Tam yaşam döngüsü durumu
    backlog_expanded: bool = False   # mimari adımından sonra backlog görevleri koşuya eklendi mi
    install_done: bool = False       # bağımlılık kurulumu bu koşuda bir kez yapıldı mı
    uat_round: int = 0               # PO reddi sonrası açılan iyileştirme turu sayısı
    fix_rounds_total: int = 0        # koşu boyunca açılan toplam düzeltme adımı
    # Sprint kipi (F3)
    mode: str = "legacy"             # 'legacy' (sabit 1-10 + backlog) | 'sprint' (yükleme ile başlayan dinamik plan)
    intake_spec_ids: List[str] = field(default_factory=list)  # bu koşunun değerlendirdiği yüklemeler
    handoffs: List[Dict[str, Any]] = field(default_factory=list)  # F4: roller arası devir notları (son 60)
    # Claude Desktop sürücüsü (F5)
    runner_claimed: bool = False     # claim_work ile üstlenildi (oturum sınırı yalnızca bu koşularda zorunludur)
    session_steps: int = 0           # bu oturumda tamamlanan adım sayısı
    session_boundary: bool = False   # oturum sınırı kondu: taze oturum (claim_work) gerekir
    # Yönetici müdahalesi: dashboard'dan bırakılan notlar ve revize istekleri (bir sonraki adımın bağlamına konur)
    manager_notes: List[Dict[str, Any]] = field(default_factory=list)
    last_decision: str = ""          # son onay kararı ('REVISE' ise istemci aynı adımı yeniden alır)

    # ------------------------------------------------------------------
    # Yardımcılar
    # ------------------------------------------------------------------
    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL_RUN_STATUSES

    @property
    def current_step(self) -> Optional[StepRecord]:
        if 0 <= self.cursor < len(self.steps):
            return self.steps[self.cursor]
        return None

    @property
    def orders(self) -> List[int]:
        return [s.order for s in self.steps]

    def step_for_order(self, order: int) -> Optional[StepRecord]:
        return next((s for s in self.steps if s.order == order), None)

    def has_order(self, order: int) -> bool:
        return any(s.order == order for s in self.steps)

    def insert_after_cursor(self, records: List["StepRecord"]) -> int:
        """Yeni adımları geçerli adımın hemen arkasına ekler; ekleme konumunu döner."""
        idx = min(self.cursor + 1, len(self.steps))
        self.steps[idx:idx] = list(records)
        return idx

    def insert_before_order(self, records: List["StepRecord"], order: int) -> int:
        """Yeni adımları, imleçten sonra gelen ilk `order` adımından önce (yoksa sona) ekler."""
        idx = len(self.steps)
        for i in range(self.cursor + 1, len(self.steps)):
            if self.steps[i].order >= order:
                idx = i
                break
        self.steps[idx:idx] = list(records)
        return idx

    def files_written(self) -> List[str]:
        """Koşu boyunca yazılan dosya yolları (sıralı, tekrarsız)."""
        seen: List[str] = []
        for s in self.steps:
            for a in s.artifacts or []:
                if a not in seen:
                    seen.append(a)
        return seen

    def touch(self) -> None:
        self.last_seen = _now()

    def advance(self) -> None:
        """İmleci bir sonraki (SKIPPED olmayan) adıma taşır; adım kalmadıysa koşuyu tamamlar."""
        self.cursor += 1
        while self.cursor < len(self.steps) and self.steps[self.cursor].status == "SKIPPED":
            self.cursor += 1      # G3: atlanmış adımlar (ör. token sınırı iptali) yeniden istemciye verilmez
        if self.cursor >= len(self.steps):
            self.finish("COMPLETED")
        else:
            self.status = "ACTIVE"

    def finish(self, status: str, reason: str = "") -> None:
        self.status = status
        self.finished_at = _now()
        if reason:
            self.cancel_reason = reason
        # Bekleyen adımlar dokunulmadan kalır (SKIPPED işaretlenir)
        for s in self.steps[self.cursor:]:
            if s.status in ("PENDING", "ACTIVE", "WAITING_APPROVAL") and status != "COMPLETED":
                s.status = "SKIPPED" if status in ("CANCELLED", "ABANDONED") else s.status

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["steps"] = [s.to_dict() for s in self.steps]
        d["is_terminal"] = self.is_terminal
        failed = sum(1 for s in self.steps if s.status == "FAILED")
        d["failed_steps"] = failed
        # G1: koşu "bitti" ile "hatasız bitti" ayrılır (E2E/UAT/çıktı hatası olan adımlar FAILED kalır)
        d["outcome"] = (("with_failures" if failed else "success") if self.status == "COMPLETED" else None)
        d["progress"] = {
            "done": sum(1 for s in self.steps if s.status == "DONE"),
            "total": len(self.steps),
            "current_order": self.current_step.order if self.current_step else None,
            "current_index": self.cursor if self.current_step else None,
            "tasks": sum(1 for s in self.steps if s.kind == "task"),
            "fixes": sum(1 for s in self.steps if s.kind == "fix"),
        }
        return d

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "PipelineRun":
        steps = [StepRecord.from_dict(s) for s in d.get("steps", [])]
        known = {k: v for k, v in d.items() if k in cls.__dataclass_fields__ and k != "steps"}
        run = cls(steps=steps, **known)
        return run


def build_run(
    project_id: str,
    project_dir: str,
    issues: List[Dict[str, Any]],
    selected: List[Any],
    engine: str = "mcp_client",
    custom_prompt: str = "",
    step_by_step: bool = True,
    server_side_orders: Optional[set] = None,
) -> PipelineRun:
    """Seçilen Jira maddelerinden (order/JIRA-x) sıralı bir koşu kaydı üretir."""
    normalized = {str(k).upper().replace("JIRA-", "") for k in (selected or [])}
    chosen: List[Dict[str, Any]] = []
    for issue in issues:
        if str(issue.get("kind", "")).lower() in ("epic", "story"):
            continue   # epik/hikâye maddeleri (sprint kipi) çalıştırılabilir iş değildir
        order_str = str(issue.get("order", ""))
        issue_key = str(issue.get("id", "")).upper().replace("JIRA-", "")
        if not normalized or order_str in normalized or issue_key in normalized:
            chosen.append(issue)
    chosen.sort(key=lambda i: i.get("order", 999))

    server_side = server_side_orders or set()
    steps = [
        StepRecord(
            order=int(i.get("order", 0)),
            issue_id=i.get("id", f"JIRA-{i.get('order')}"),
            role=i.get("assignee", "PM"),
            server_side=int(i.get("order", 0)) in server_side,
            kind="task" if str(i.get("kind", "")).lower() == "task" else "phase",
            title=str(i.get("title", "") or ""),
        )
        for i in chosen
    ]
    return PipelineRun(
        project_id=project_id,
        project_dir=project_dir,
        engine=engine if engine in ENGINES else "mcp_client",
        steps=steps,
        custom_prompt=custom_prompt or "",
        step_by_step=step_by_step,
    )
