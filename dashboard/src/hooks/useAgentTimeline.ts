import { useEffect, useMemo, useState } from 'react';
import { api } from '../config';
import { translate } from '../i18n';
import { Agent, PipelineRun, TaskAuditEntry, TelemetryEvent } from '../types/telemetry';

export interface TimelineAudit extends TaskAuditEntry {
  issue_id?: string;
  issue_title?: string;
}

export interface InteractionSummary {
  sent: number;
  received: number;
  last_at: string | null;
  last_action: string | null;
}

export interface AgentTimelineData {
  agent_id: string;
  agent: Agent | null;
  project_id: string;
  events: TelemetryEvent[];
  audits: TimelineAudit[];
  deliberation: TelemetryEvent[];
  interactions: Record<string, InteractionSummary>;
  runs: PipelineRun[];
  total_events: number;
}

/**
 * Seçili ajanın zaman çizelgesini sunucudan (JSONL + bellek) çeker ve canlı olaylarla birleştirir.
 * `liveEvents` hook'un yeniden eskiye sıralı olay dizisidir.
 */
export function useAgentTimeline(agentId: string | null, liveEvents: TelemetryEvent[], projectId?: string) {
  const [data, setData] = useState<AgentTimelineData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);

  useEffect(() => {
    if (!agentId) {
      setData(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    const q = new URLSearchParams({ limit: '500' });
    if (projectId) q.set('project_id', projectId);
    fetch(api(`/api/agents/${encodeURIComponent(agentId)}/timeline?${q.toString()}`))
      .then(async res => {
        const body = await res.json();
        if (!res.ok) throw new Error(body.error || translate('misc.serverError', { status: res.status }, `Sunucu hatası (${res.status})`));
        if (!cancelled) setData(body);
      })
      .catch(err => {
        if (!cancelled) setError(err instanceof Error ? err.message : translate('misc.timeline.fetchFailed', undefined, 'Zaman çizelgesi alınamadı'));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [agentId, projectId, refreshKey]);

  // Canlı olaylar: sunucudan gelen listeyle kimliğe göre tekilleştir (yeniden eskiye)
  const events = useMemo(() => {
    if (!agentId) return [] as TelemetryEvent[];
    const aid = agentId.toUpperCase();
    const seen = new Set<string>();
    const merged: TelemetryEvent[] = [];
    const push = (e: TelemetryEvent) => {
      if (!e || seen.has(e.id)) return;
      if (e.from_agent?.toUpperCase() !== aid && e.to_agent?.toUpperCase() !== aid) return;
      seen.add(e.id);
      merged.push(e);
    };
    liveEvents.forEach(push);
    (data?.events || []).forEach(push);
    merged.sort((a, b) => (a.timestamp < b.timestamp ? 1 : -1));
    return merged;
  }, [agentId, liveEvents, data]);

  return { data, events, loading, error, refresh: () => setRefreshKey(k => k + 1) };
}
