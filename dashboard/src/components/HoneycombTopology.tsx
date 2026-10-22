import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { ReactFlow, Background, Controls, MiniMap, BackgroundVariant, NodeMouseHandler, Node, useReactFlow } from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { Hexagon, RefreshCw } from 'lucide-react';
import { api } from '../config';
import { Agent, TelemetryEvent } from '../types/telemetry';
import { AgentMeshContext } from './agentMeshContext';
import { DeptHexNode, HexAgentNode, MeetingHexNode, TeamHexNode } from './HexNodes';
import { buildHoneycomb, Gathering, Team } from '../topology/hexLayout';
import { pipelineEdgeLabel } from './AgentMesh';
import { useI18n } from '../i18n';

interface HoneycombTopologyProps {
  agents: Agent[];
  recentEvents: TelemetryEvent[];
  gathering: Gathering;
  selectedAgentId?: string | null;
  onSelectAgent?: (agentId: string | null) => void;
  /** TEAMS_UPDATED / proje değişimi gibi durumlarda yeniden çekmek için değiştirin */
  refreshKey?: string | number;
}

const nodeTypes = { teamHex: TeamHexNode, deptHex: DeptHexNode, meetingHex: MeetingHexNode, agentHex: HexAgentNode };

/** Takımlar asenkron geldiği için ilk fitView boş tuvale uygulanır; düğüm kümesi değişince yeniden sığdır. */
const FitOnNodes: React.FC<{ layoutKey: string }> = ({ layoutKey }) => {
  const { fitView } = useReactFlow();
  useEffect(() => {
    if (!layoutKey) return;
    const t = window.setTimeout(() => fitView({ padding: 0.12, duration: 300 }), 50);
    return () => window.clearTimeout(t);
  }, [layoutKey, fitView]);
  return null;
};

export const HoneycombTopology: React.FC<HoneycombTopologyProps> = ({ agents, recentEvents, gathering, selectedAgentId, onSelectAgent, refreshKey }) => {
  const { t } = useI18n();
  const [teams, setTeams] = useState<Team[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    fetch(api('/api/teams?include_partners=1'))
      .then(async res => {
        const body = await res.json();
        if (!res.ok) throw new Error(body.error || t('agents.honey.serverError', { status: res.status }, 'Sunucu hatası ({status})'));
        if (!cancelled) {
          setTeams(body.teams || []);
          setError(null);
        }
      })
      .catch(err => !cancelled && setError(err instanceof Error ? err.message : t('agents.honey.teamsFailed', undefined, 'Takımlar alınamadı')))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [refreshKey, tick]);

  // Ajan kimlik kümesi değişince (özel ajan eklendi) partnerler değil, aktif takım güncellenmeli → yeniden çek
  const agentIdsKey = useMemo(() => agents.map(a => a.id).sort().join('|'), [agents]);
  useEffect(() => {
    setTick(n => n + 1);
  }, [agentIdsKey]);

  const layoutKey = useMemo(() => teams.map(tm => `${tm.id}:${tm.departments.map(d => d.agent_ids.length).join(',')}`).join('|'), [teams]);
  const { nodes, edges } = useMemo(
    () => buildHoneycomb(teams, agents, { size: 44, gathering, recentEvents, edgeLabel: (l: string) => pipelineEdgeLabel(l, t) }),
    // agents yalnızca yer tutucu veri için; canlı veri bağlamdan gelir → düğümler her olayda yeniden kurulmaz
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [teams, agentIdsKey, gathering.active, gathering.participants.join('|'), recentEvents.length, t]
  );

  const contextValue = useMemo(() => ({
    agentsById: new Map(agents.map(a => [a.id, a])),
    selectedAgentId: selectedAgentId ?? null,
  }), [agents, selectedAgentId]);

  const handleNodeClick: NodeMouseHandler = useCallback((_e, node: Node) => {
    if (node.type === 'agentHex' && !(node.data as { readOnly?: boolean }).readOnly) {
      onSelectAgent?.((node.data as { agentId: string }).agentId);
    }
  }, [onSelectAgent]);

  return (
    <AgentMeshContext.Provider value={contextValue}>
      <div className="w-full h-full bg-panel relative overflow-hidden rounded-panel border border-line">
        <ReactFlow
          nodes={nodes}
          edges={edges}
          nodeTypes={nodeTypes}
          onNodeClick={handleNodeClick}
          onPaneClick={() => onSelectAgent?.(null)}
          nodesConnectable={false}
          elementsSelectable
          fitView
          fitViewOptions={{ padding: 0.15 }}
          minZoom={0.2}
          maxZoom={2}
          attributionPosition="bottom-right"
        >
          <FitOnNodes layoutKey={layoutKey} />
          <Background color="var(--grid)" gap={26} size={1.4} variant={BackgroundVariant.Dots} className="opacity-70" />
          <Controls className="bg-panel border border-line fill-ink text-ink shadow-panel rounded-lg overflow-hidden" />
          <MiniMap
            pannable
            zoomable
            nodeStrokeWidth={2}
            nodeColor={(n) => (n.type === 'agentHex' ? 'var(--ac)' : n.type === 'meetingHex' ? 'var(--warn)' : n.type === 'deptHex' ? 'var(--line)' : 'transparent')}
            nodeStrokeColor={(n) => (n.type === 'teamHex' ? 'var(--line2)' : 'transparent')}
            maskColor="color-mix(in oklab, var(--bg) 75%, transparent)"
            className="bg-panel border border-line rounded-lg overflow-hidden shadow-panel"
          />
        </ReactFlow>

        <div className="absolute top-4 left-4 z-10 flex items-center gap-2 bg-panel/90 backdrop-blur-md px-3 py-1.5 rounded-lg border border-line text-xs text-ink3 font-mono shadow-panel">
          <Hexagon className="w-3.5 h-3.5 text-ac" />
          <span className="text-ink font-medium">{t('agents.honey.title', undefined, 'Petek Topolojisi • takım ▸ departman ▸ ajan • toplantı odası ortada')}</span>
          <button onClick={() => setTick(n => n + 1)} className="ml-1 text-ink3 hover:text-ink pointer-events-auto" title={t('agents.honey.refresh', undefined, 'Takımları yenile')}>
            <RefreshCw className={`w-3 h-3 ${loading ? 'animate-spin' : ''}`} />
          </button>
          {error && <span className="text-err">{error}</span>}
        </div>
        {gathering.active && (
          <div className="absolute top-4 right-4 z-10 text-[11px] font-mono px-2.5 py-1 rounded-lg bg-acd text-ac border border-ac/40 shadow-panel">
            🪑 {t('agents.honey.inMeeting', { n: gathering.participants.length, reason: gathering.reason || t('agents.honey.deliberation', undefined, 'müzakere') }, '{n} ajan toplantı odasında — {reason}')}
          </div>
        )}
      </div>
    </AgentMeshContext.Provider>
  );
};
