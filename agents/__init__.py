"""
Agents package initialization.
Pydantic A2A şemaları (AgentRole, MessageIntent, A2AMessage ...) — pipeline çıktı sözleşmesinin temeli.
"""
from .schemas import (
    AgentRole,
    MessageIntent,
    TaskStatus,
    KanbanState,
    AgentMetadata,
    A2AMessage,
    TaskStateUpdate,
    AgentMetric,
)

__all__ = [
    "AgentRole",
    "MessageIntent",
    "TaskStatus",
    "KanbanState",
    "AgentMetadata",
    "A2AMessage",
    "TaskStateUpdate",
    "AgentMetric",
]
