import { createContext, useContext } from 'react';
import { Agent } from '../types/telemetry';

/**
 * Canlı ajan verisi ve seçim durumu, React Flow düğüm nesnelerine değil bu bağlama yazılır.
 * Böylece her telemetri olayında düğüm dizisi yeniden kurulmaz; React Flow'un ölçüm/handle içyapısı korunur.
 */
export interface AgentMeshContextValue {
  agentsById: Map<string, Agent>;
  selectedAgentId: string | null;
}

export const AgentMeshContext = createContext<AgentMeshContextValue>({
  agentsById: new Map(),
  selectedAgentId: null,
});

export const useAgentMeshContext = () => useContext(AgentMeshContext);
