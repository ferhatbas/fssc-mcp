import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  Node,
  Edge,
  MarkerType,
  BackgroundVariant,
  useNodesState,
  useUpdateNodeInternals,
  NodeMouseHandler
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';

import { AgentNode } from './AgentNode';
import { Agent, TelemetryEvent } from '../types/telemetry';
import { MessageSquare } from 'lucide-react';
import { useTheme } from '../hooks/useTheme';
import { AgentMeshContext } from './agentMeshContext';
import { useI18n, SupportedLanguage } from '../i18n';

interface AgentMeshProps {
  agents: Agent[];
  activeEdgeId: string | null;
  edgeStatus: 'SUCCESS' | 'FAILED';
  activeDialogue?: string | null;
  activeFromAgent?: string | null;
  activeToAgent?: string | null;
  /** Konuşmayı üreten olayın zamanı (ISO); balonda saat olarak gösterilir */
  activeTimestamp?: string | null;
  /** Seçili ajan (kart tıklaması → zaman çizelgesi çekmecesi) */
  selectedAgentId?: string | null;
  onSelectAgent?: (agentId: string | null) => void;
  /** Özel ajanlar için son olaylardan kenar türetmek üzere (isteğe bağlı) */
  recentEvents?: TelemetryEvent[];
}

const nodeTypes = {
  agentNode: AgentNode,
};

/**
 * Konuşma metnini sıkıştırır: sarmalayan tırnaklar atılır; metin uzunsa ilk ayraçta (" · ", " — ", ": ", ". ") ya da kelime sınırında
 * bölünür. `head` tek satırlık özet, `note` geri kalan ayrıntıdır (tam metin balonun ipucunda durur).
 */
export function compactDialogue(raw: string, max = 56): { head: string; note: string } {
  const text = String(raw || '').replace(/\s+/g, ' ').trim().replace(/^["“”']+|["“”']+$/g, '').trim();
  if (text.length <= max) return { head: text, note: '' };
  for (const sep of [' · ', ' — ', ': ', '. ']) {
    const i = text.indexOf(sep);
    if (i >= 8 && i <= max) return { head: text.slice(0, i + (sep === ': ' || sep === '. ' ? 1 : 0)).trim(), note: text.slice(i + sep.length).trim() };
  }
  const cut = text.lastIndexOf(' ', max);
  const at = cut >= Math.floor(max / 2) ? cut : max;
  return { head: `${text.slice(0, at).trim()}…`, note: text.slice(at).trim() };
}

/** Olay zamanını yerel saat (SS:DD:SS) ve tam tarih olarak biçimler; geçersizse null. */
export function stampOf(ts?: string | null, locale = 'tr-TR'): { clock: string; full: string } | null {
  if (!ts) return null;
  const d = new Date(ts);
  if (Number.isNaN(d.getTime())) return null;
  return { clock: d.toLocaleTimeString(locale, { hour12: false }), full: d.toLocaleString(locale) };
}

/**
 * Gizli sekmede (document.hidden) tarayıcı ResizeObserver tetiklemez; React Flow düğümleri ölçemez ve kenarları çizemez.
 * Sekme görünür olunca tüm düğümleri yeniden ölçtürür (arka planda açılan dashboard için güvenlik ağı).
 */
const RemeasureOnVisible: React.FC<{ nodeIds: string[] }> = ({ nodeIds }) => {
  const updateNodeInternals = useUpdateNodeInternals();
  useEffect(() => {
    const handler = () => {
      if (document.visibilityState === 'visible') updateNodeInternals(nodeIds);
    };
    document.addEventListener('visibilitychange', handler);
    return () => document.removeEventListener('visibilitychange', handler);
  }, [nodeIds, updateNodeInternals]);
  return null;
};

/** Bilinen rollerin sabit yerleşimi: PM → ARCHITECT → [BE/FE] → [QA/E2E] → DEVOPS, altta PO/REPORTER/DOCUMENTOR/SCM */
export const PIPELINE_LAYOUT: Record<string, { x: number; y: number }> = {
  // Kart 280px genişlik / ~340px yükseklik (genişlemiş). Sütun aralığı 340, aynı sütunda satır aralığı 480
  // (kart + üstündeki konuşma baloncuğu için ~140px boşluk). Aşağıdaki koridor (820-960) uzun kenarlar içindir.
  PM: { x: 0, y: 240 },
  ARCHITECT: { x: 340, y: 240 },
  BACKEND_DEV: { x: 680, y: 0 },
  FRONTEND_DEV: { x: 680, y: 480 },
  DESIGNER: { x: 340, y: 480 },
  QA: { x: 1020, y: 0 },
  E2E_TESTER: { x: 1020, y: 480 },
  DEVOPS: { x: 1360, y: 480 },
  SCM: { x: 340, y: 960 },
  REPORTER: { x: 680, y: 960 },
  PO: { x: 1020, y: 960 },
  DOCUMENTOR: { x: 1360, y: 960 },
};

/** Özel (kayıtlı olmayan) ajanlar: sabit yerleşimin altında 4'lü satırlar */
export const CUSTOM_AGENT_ORIGIN = { x: 0, y: 1440, colPitch: 340, rowPitch: 480, perRow: 5 };

const DEFAULT_NAMES: Record<string, string> = {
  BACKEND_DEV: 'Senior Backend Dev',
  FRONTEND_DEV: 'Senior Frontend Dev',
  DESIGNER: 'UI/UX Designer',
  E2E_TESTER: 'Playwright E2E Tester',
  PO: 'Product Owner',
  SCM: 'SCM Manager',
  REPORTER: 'Project Reporter',
  DOCUMENTOR: 'Documentation Lead',
};

interface PipelineEdgeSpec {
  id: string;
  source: string;
  target: string;
  label: string;
  sourceHandle: string;
  targetHandle: string;
  type: 'smoothstep' | 'straight';
  color?: 'ac' | 'err' | 'ok';
  dashed?: boolean;
  alwaysAnimated?: boolean;
}

/** Pano diline göre tarih/saat yerel kodu */
export const LOCALE_OF: Record<SupportedLanguage, string> = { tr: 'tr-TR', en: 'en-US', es: 'es-ES', de: 'de-DE' };

/** Kenar etiketindeki çevrilebilir kısım ('onaylı'); teknik adlar olduğu gibi kalır. */
export function pipelineEdgeLabel(label: string, t: (key: string, params?: Record<string, string | number>, fallback?: string) => string): string {
  return label.replace('(onaylı)', `(${t('agents.mesh.approved', undefined, 'onaylı')})`);
}

/** Sabit pipeline kenarları (topoloji ve petek görünümleri paylaşır) */
export const PIPELINE_EDGES: PipelineEdgeSpec[] = [
  { id: 'edge-PM-ARCHITECT', source: 'PM', target: 'ARCHITECT', label: '1. PRD_DISPATCH', sourceHandle: 'source-right', targetHandle: 'target-left', type: 'smoothstep' },
  { id: 'edge-ARCHITECT-BACKEND_DEV', source: 'ARCHITECT', target: 'BACKEND_DEV', label: '2a. API_CONTRACT', sourceHandle: 'source-right', targetHandle: 'target-left', type: 'smoothstep' },
  { id: 'edge-ARCHITECT-DESIGNER', source: 'ARCHITECT', target: 'DESIGNER', label: '2b. DESIGN_BRIEF', sourceHandle: 'source-bottom', targetHandle: 'target-top', type: 'straight' },
  { id: 'edge-DESIGNER-FRONTEND_DEV', source: 'DESIGNER', target: 'FRONTEND_DEV', label: '2c. DESIGN_SYSTEM (onaylı)', sourceHandle: 'source-right', targetHandle: 'target-left', type: 'smoothstep', color: 'ac' },
  { id: 'edge-ARCHITECT-FRONTEND_DEV', source: 'ARCHITECT', target: 'FRONTEND_DEV', label: '2d. UI_SCHEMA', sourceHandle: 'source-right', targetHandle: 'target-left', type: 'smoothstep' },
  { id: 'edge-BACKEND_DEV-FRONTEND_DEV', source: 'BACKEND_DEV', target: 'FRONTEND_DEV', label: '⇄ A2A PEER HANDSHAKE', sourceHandle: 'source-bottom', targetHandle: 'target-top', type: 'straight', color: 'ac', dashed: true, alwaysAnimated: true },
  { id: 'edge-BACKEND_DEV-QA', source: 'BACKEND_DEV', target: 'QA', label: '3. SUBMIT_BACKEND', sourceHandle: 'source-right', targetHandle: 'target-left', type: 'smoothstep' },
  { id: 'edge-FRONTEND_DEV-E2E_TESTER', source: 'FRONTEND_DEV', target: 'E2E_TESTER', label: '4. SUBMIT_UI', sourceHandle: 'source-right', targetHandle: 'target-left', type: 'smoothstep' },
  { id: 'edge-QA-BACKEND_DEV', source: 'QA', target: 'BACKEND_DEV', label: 'BUG_REPORT', sourceHandle: 'source-top', targetHandle: 'target-top', type: 'smoothstep', color: 'err', dashed: true },
  { id: 'edge-QA-E2E_TESTER', source: 'QA', target: 'E2E_TESTER', label: 'UNIT_APPROVED', sourceHandle: 'source-bottom', targetHandle: 'target-top', type: 'straight' },
  { id: 'edge-E2E_TESTER-ARCHITECT', source: 'E2E_TESTER', target: 'ARCHITECT', label: 'SCREENSHOT_CONFIRMED', sourceHandle: 'source-bottom', targetHandle: 'target-bottom', type: 'smoothstep' },
  { id: 'edge-QA-DEVOPS', source: 'QA', target: 'DEVOPS', label: 'APPROVE_BUILD', sourceHandle: 'source-right', targetHandle: 'target-left', type: 'smoothstep' },
  { id: 'edge-DEVOPS-PM', source: 'DEVOPS', target: 'PM', label: 'DEPLOY_CONFIRM (LIVE)', sourceHandle: 'source-bottom', targetHandle: 'target-bottom', type: 'smoothstep', color: 'ok' },
  { id: 'edge-DEVOPS-PO', source: 'DEVOPS', target: 'PO', label: '9. UAT', sourceHandle: 'source-bottom', targetHandle: 'target-top', type: 'smoothstep' },
  { id: 'edge-PO-DOCUMENTOR', source: 'PO', target: 'DOCUMENTOR', label: '10. MANUALS', sourceHandle: 'source-right', targetHandle: 'target-left', type: 'smoothstep' },
];

function placeholderAgent(id: string): Agent {
  return {
    id,
    name: DEFAULT_NAMES[id] || id,
    role: id,
    status: 'IDLE',
    tokens_in: 0,
    tokens_out: 0,
    total_tokens: 0,
    last_action: 'READY',
    last_seen: ''
  };
}

/**
 * Ajan kimliklerinden STATİK düğümleri üretir (konum + kimlik). Canlı veri (durum, token, diyalog)
 * AgentMeshContext üzerinden okunur; böylece telemetri olayları düğüm dizisini değiştirmez.
 * Bilinmeyen (özel) ajanlar alt satıra dizilir.
 */
function buildNodes(agents: Agent[]): Node[] {
  const byId = new Map(agents.map(a => [a.id, a]));
  const nodes: Node[] = [];

  for (const [id, pos] of Object.entries(PIPELINE_LAYOUT)) {
    nodes.push({
      id,
      type: 'agentNode',
      position: pos,
      data: { agentId: id, agent: byId.get(id) || placeholderAgent(id) },
    });
  }

  let col = 0;
  for (const agent of agents) {
    if (PIPELINE_LAYOUT[agent.id]) continue;
    nodes.push({
      id: agent.id,
      type: 'agentNode',
      position: { x: CUSTOM_AGENT_ORIGIN.x + (col % CUSTOM_AGENT_ORIGIN.perRow) * CUSTOM_AGENT_ORIGIN.colPitch, y: CUSTOM_AGENT_ORIGIN.y + Math.floor(col / CUSTOM_AGENT_ORIGIN.perRow) * CUSTOM_AGENT_ORIGIN.rowPitch },
      data: { agentId: agent.id, agent },
    });
    col += 1;
  }
  return nodes;
}

export const AgentMesh: React.FC<AgentMeshProps> = ({
  agents,
  activeEdgeId,
  edgeStatus,
  activeDialogue,
  activeFromAgent,
  activeToAgent,
  activeTimestamp,
  selectedAgentId,
  onSelectAgent,
  recentEvents = []
}) => {
  const { theme } = useTheme();
  const { t, lang } = useI18n();
  // Alt "Canlı Ekip Konuşması" kutusu: tıklayınca kapanır, yeni konuşma gelince yeniden görünür
  // Anahtar zamanı da içerir: aynı metin yeni olayla gelirse balon yeniden görünür
  const [dismissedDialogue, setDismissedDialogue] = useState<string | null>(null);
  const dialogueKey = activeDialogue ? `${activeTimestamp || ''}|${activeDialogue}` : null;
  const shownDialogue = activeDialogue && dialogueKey !== dismissedDialogue ? activeDialogue : null;
  const compact = shownDialogue ? compactDialogue(shownDialogue) : null;
  const stamp = stampOf(activeTimestamp, LOCALE_OF[lang]);

  // Düğümler kontrollü state'te (seçim/sürükleme uygulanabilsin diye) ama yalnızca ajan KİMLİK KÜMESİ değişince
  // yeniden kurulur (eski hata: her olayda düğümler yeniden yaratılıp konumlar ve React Flow ölçümleri sıfırlanıyordu).
  const initialNodes = useMemo(() => buildNodes(agents), []); // eslint-disable-line react-hooks/exhaustive-deps
  const [nodes, setNodes, onNodesChange] = useNodesState<Node>(initialNodes);
  const agentIdsKey = useMemo(() => agents.map(a => a.id).sort().join('|'), [agents]);

  useEffect(() => {
    const fresh = buildNodes(agents);
    setNodes(prev => {
      const prevIds = new Set(prev.map(n => n.id));
      const freshIds = new Set(fresh.map(n => n.id));
      const same = prev.length === fresh.length && [...prevIds].every(id => freshIds.has(id));
      if (same) return prev; // aynı küme: hiçbir düğüm nesnesine dokunma
      const prevById = new Map(prev.map(n => [n.id, n]));
      return fresh.map(n => prevById.get(n.id) || n);
    });
  }, [agentIdsKey, setNodes]); // eslint-disable-line react-hooks/exhaustive-deps

  const contextValue = useMemo(() => ({
    agentsById: new Map(agents.map(a => [a.id, a])),
    selectedAgentId: selectedAgentId ?? null,
  }), [agents, selectedAgentId]);

  const nodeIds = useMemo(() => new Set(nodes.map(n => n.id)), [nodes]);

  // Ajanlar arası bağlantı hatları: sabit pipeline kenarları + özel ajanlar için son olaylardan türetilen kenarlar
  const edges: Edge[] = useMemo(() => {
    const isAct = (key: string) => activeEdgeId === key;
    const activeColor = edgeStatus === 'FAILED' ? 'var(--err)' : 'var(--ac)';
    const defaultColor = 'var(--line2)';
    const labelStyle = { fill: 'var(--ink2)', fontSize: 10, fontWeight: 600, fontFamily: 'monospace' };
    const labelBgStyle = { fill: 'var(--panel)', fillOpacity: 0.95 };

    const staticEdges: Edge[] = PIPELINE_EDGES
      .filter(spec => nodeIds.has(spec.source) && nodeIds.has(spec.target))
      .map(spec => {
        const fixed = spec.color ? `var(--${spec.color})` : null;
        const active = isAct(spec.id);
        const stroke = fixed && (spec.color !== 'ok' || active) ? fixed : active ? activeColor : defaultColor;
        return {
          id: spec.id,
          source: spec.source,
          target: spec.target,
          sourceHandle: spec.sourceHandle,
          targetHandle: spec.targetHandle,
          label: pipelineEdgeLabel(spec.label, t),
          type: spec.type,
          animated: spec.alwaysAnimated || active,
          style: {
            stroke,
            strokeWidth: active ? 3.5 : spec.dashed ? 2 : 2,
            ...(spec.dashed ? { strokeDasharray: '5,5' } : {}),
          },
          labelStyle: { ...labelStyle, ...(fixed ? { fill: fixed, fontWeight: 700 } : {}) },
          labelBgStyle,
          markerEnd: { type: MarkerType.ArrowClosed, color: stroke },
        } as Edge;
      });

    // Son olaylardan türetilen kenarlar (yalnızca sabit listede olmayan çiftler; özel ajanlar böylece bağlanır)
    const known = new Set(PIPELINE_EDGES.map(e => `${e.source}->${e.target}`));
    const derived = new Map<string, Edge>();
    for (const evt of recentEvents.slice(0, 30)) {
      if (!evt.from_agent || !evt.to_agent || evt.from_agent === evt.to_agent) continue;
      if (evt.to_agent === 'ALL') continue;
      if (!nodeIds.has(evt.from_agent) || !nodeIds.has(evt.to_agent)) continue;
      const key = `${evt.from_agent}->${evt.to_agent}`;
      if (known.has(key) || derived.has(key)) continue;
      const id = `edge-${evt.from_agent}-${evt.to_agent}`;
      const active = isAct(id);
      derived.set(key, {
        id,
        source: evt.from_agent,
        target: evt.to_agent,
        sourceHandle: 'source-right',
        targetHandle: 'target-left',
        label: evt.action,
        type: 'smoothstep',
        animated: active,
        style: { stroke: active ? activeColor : defaultColor, strokeWidth: active ? 3 : 1.5, strokeDasharray: '3,4' },
        labelStyle,
        labelBgStyle,
        markerEnd: { type: MarkerType.ArrowClosed, color: active ? activeColor : defaultColor },
      });
    }
    return [...staticEdges, ...derived.values()];
  }, [activeEdgeId, edgeStatus, theme, nodeIds, recentEvents, t]);

  const handleNodeClick: NodeMouseHandler = useCallback((_evt, node) => {
    onSelectAgent?.(node.id);
  }, [onSelectAgent]);

  const handlePaneClick = useCallback(() => {
    onSelectAgent?.(null);
  }, [onSelectAgent]);

  return (
    <AgentMeshContext.Provider value={contextValue}>
    <div className="w-full h-full bg-panel relative overflow-hidden rounded-panel border border-line">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        onNodesChange={onNodesChange}
        onNodeClick={handleNodeClick}
        onPaneClick={handlePaneClick}
        nodesDraggable
        elementsSelectable
        nodesConnectable={false}
        selectNodesOnDrag={false}
        fitView
        minZoom={0.2}
        maxZoom={1.5}
        defaultViewport={{ x: 0, y: 0, zoom: 0.85 }}
        attributionPosition="bottom-right"
      >
        <RemeasureOnVisible nodeIds={nodes.map(n => n.id)} />
        <Background
          color="var(--grid)"
          gap={24}
          size={1.5}
          variant={BackgroundVariant.Dots}
          className="opacity-70"
        />
        <Controls className="bg-panel border border-line fill-ink text-ink shadow-panel rounded-lg overflow-hidden" />
        <MiniMap
          nodeStrokeWidth={3}
          nodeColor={(node) => {
            if (node.id === 'PM' || node.id === 'DEVOPS' || node.id === 'PO') return 'var(--ac)';
            if (node.id === 'ARCHITECT' || node.id === 'FRONTEND_DEV') return 'var(--info)';
            if (node.id === 'BACKEND_DEV') return 'var(--ok)';
            if (node.id === 'QA' || node.id === 'E2E_TESTER') return 'var(--warn)';
            return 'var(--ink3)';
          }}
          maskColor="color-mix(in oklab, var(--bg) 75%, transparent)"
          className="bg-panel border border-line rounded-lg overflow-hidden shadow-panel"
        />
      </ReactFlow>

      {/* Ağ Açıklama Rozeti */}
      <div className="absolute top-4 left-4 z-10 flex items-center gap-2 bg-panel/90 backdrop-blur-md px-3 py-1.5 rounded-lg border border-line text-xs text-ink3 font-mono pointer-events-none shadow-panel">
        <span className="w-2 h-2 rounded-full bg-ac animate-ping" />
        <span className="text-ink font-medium">{t('agents.mesh.title', undefined, 'Yazılım Şirketi Topolojisi • karta tıkla: zaman çizelgesi')}</span>
      </div>

      {/* Canlı İnsansı Ajan Diyaloğu Popup'ı (Non-Technical Speech Bubble) */}
      {shownDialogue && compact && (
        <div
          role="button"
          onClick={() => setDismissedDialogue(dialogueKey)}
          title={`${shownDialogue}${stamp ? `\n${stamp.full}` : ''}\n${t('agents.mesh.clickClose', undefined, '(kapatmak için tıkla)')}`}
          className="absolute bottom-5 left-1/2 -translate-x-1/2 z-20 max-w-md w-[88%] bg-panel border-2 border-ac rounded-xl px-3 py-2 shadow-panel backdrop-blur-xl cursor-pointer hover:border-ac/70"
        >
          <div className="flex items-start gap-2.5">
            <div className="w-7 h-7 rounded-lg bg-acd border border-ac/30 flex items-center justify-center shrink-0 text-ac">
              <MessageSquare className="w-4 h-4" />
            </div>
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-1.5 text-[10px] text-ink3 font-mono">
                <span className="font-bold px-1.5 py-0.5 rounded bg-acd text-ac border border-ac/30 truncate">
                  💬 {activeFromAgent || t('agents.mesh.agent', undefined, 'Ajan')} → {activeToAgent || t('agents.mesh.team', undefined, 'Ekip')}
                </span>
                <span className="whitespace-nowrap">{t('agents.mesh.liveTalk', undefined, 'Canlı Ekip Konuşması')}</span>
                {stamp && (
                  <time dateTime={activeTimestamp || undefined} title={stamp.full} className="ml-auto shrink-0 text-ink2 tabular-nums">{stamp.clock}</time>
                )}
              </div>
              <p className="mt-1 text-xs text-ink font-medium leading-snug truncate">{compact.head}</p>
              {compact.note && <p className="text-[10.5px] text-ink3 leading-snug line-clamp-2">{compact.note}</p>}
            </div>
          </div>
        </div>
      )}
    </div>
    </AgentMeshContext.Provider>
  );
};
