"""
Ajanlar Arası İletişim Protokolü (A2A) ve Veri Şemaları
Pydantic v2 tabanlı tip güvenli veri yapıları.
"""

from enum import Enum
from typing import Any, Dict, List, Optional
from datetime import datetime, timezone
from pydantic import BaseModel, Field


class AgentRole(str, Enum):
    """10 adımlı pipeline'daki tüm ajan kimlikleri (server/config.py DEFAULT_AGENTS ile uyumlu)."""
    PM = "PM"
    PO = "PO"
    ARCHITECT = "ARCHITECT"
    DEVELOPER = "DEVELOPER"          # Geriye dönük uyumluluk (eski 5 rollük şema)
    BACKEND_DEV = "BACKEND_DEV"
    FRONTEND_DEV = "FRONTEND_DEV"
    QA = "QA"
    E2E_TESTER = "E2E_TESTER"
    DEVOPS = "DEVOPS"
    REPORTER = "REPORTER"
    DOCUMENTOR = "DOCUMENTOR"
    SCM = "SCM"
    ALL = "ALL"                      # Müzakere odası yayınları için hedef


class MessageIntent(str, Enum):
    """Ajanlar arası mesaj amaçları; runner.py'deki tüm aksiyonları kapsar."""
    TASK_DISPATCH = "TASK_DISPATCH"
    DISPATCH_PRD = "DISPATCH_PRD"
    DISPATCH_CONTRACT = "DISPATCH_CONTRACT"
    SUBMIT_CODE = "SUBMIT_CODE"
    BACKEND_API_EXPOSED = "BACKEND_API_EXPOSED"
    FRONTEND_COMPONENTS_READY = "FRONTEND_COMPONENTS_READY"
    A2A_CONTRACT_CONFIRM = "A2A_CONTRACT_CONFIRM"
    REPORT_BUG = "REPORT_BUG"
    APPROVE_BUILD = "APPROVE_BUILD"
    E2E_SCREENSHOT_CONFIRMED = "E2E_SCREENSHOT_CONFIRMED"
    E2E_TEST_FAILED = "E2E_TEST_FAILED"
    DEPLOY_CONFIRM = "DEPLOY_CONFIRM"
    UAT_APPROVED = "UAT_APPROVED"
    UAT_REJECTED = "UAT_REJECTED"
    MANUALS_PUBLISHED = "MANUALS_PUBLISHED"
    DELIBERATION_SPEECH = "DELIBERATION_SPEECH"
    STATUS_PING = "STATUS_PING"
    START_THINKING = "START_THINKING"
    COMPLETED = "COMPLETED"


class TaskStatus(str, Enum):
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"


class KanbanState(str, Enum):
    BACKLOG = "BACKLOG"
    ARCHITECTURE = "ARCHITECTURE"
    DEVELOPMENT = "DEVELOPMENT"
    QA_TESTING = "QA_TESTING"
    DEVOPS_DEPLOY = "DEVOPS_DEPLOY"
    RELEASED = "RELEASED"


class AgentMetadata(BaseModel):
    tokens_used: int = Field(default=0, description="Kullanılan yaklaşık token miktarı")
    current_file: Optional[str] = Field(default=None, description="Ajanın o an çalıştığı dosya yolu")
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="Mesajın oluşturulma zamanı (UTC ISO 8601)"
    )


class A2AMessage(BaseModel):
    trace_id: str = Field(..., description="Uçtan uca istek takip kimliği (UUID veya req-xyz)")
    from_agent: AgentRole = Field(..., description="Mesajı gönderen ajan rolü")
    to_agent: AgentRole = Field(..., description="Mesajı alacak hedef ajan rolü")
    intent: MessageIntent = Field(..., description="Mesajın amacı/eylemi")
    status: TaskStatus = Field(default=TaskStatus.SUCCESS, description="İşlem durumu")
    payload: Dict[str, Any] = Field(default_factory=dict, description="Yapılandırılmış görev veya hata yükü")
    metadata: AgentMetadata = Field(default_factory=AgentMetadata, description="İzlenebilirlik metrikleri")


class TaskStateUpdate(BaseModel):
    task_id: str = Field(..., description="Görev veya kart kimliği (örn. FEAT-01)")
    new_state: KanbanState = Field(..., description="Kanban tahtasındaki yeni durumu")
    title: Optional[str] = Field(default=None, description="Görev başlığı")
    assignee: Optional[AgentRole] = Field(default=None, description="Atanan sorumlu ajan")
    priority: str = Field(default="P1", description="Öncelik (P0, P1, P2)")
    details: Optional[str] = Field(default=None, description="Kısa durum açıklaması")
    updated_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


class AgentMetric(BaseModel):
    agent_name: AgentRole
    tokens_in: int = 0
    tokens_out: int = 0
    total_tokens: int = 0
    latency_ms: float = 0.0
    active_file: Optional[str] = None
    last_action: Optional[str] = None
    status: str = "IDLE"  # IDLE, WORKING, BUG_FIX, COMPLETED, ERROR
