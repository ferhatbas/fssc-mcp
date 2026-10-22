import React, { memo } from 'react';
import { Handle, NodeProps, Position } from '@xyflow/react';
import { Users, Building2, Code2 } from 'lucide-react';
import { Agent } from '../types/telemetry';
import { ROLE_ICONS, STATUS_CONFIG } from './AgentNode';
import { useAgentMeshContext } from './agentMeshContext';
import { HEX_CLIP } from '../topology/hexLayout';
import { useI18n } from '../i18n';

/** Altıgen zemin + kenarlık: clip-path CSS kenarlığı kestiği için SVG çokgen kullanılır */
const HexShape: React.FC<{ fill: string; stroke: string; strokeWidth?: number; dashed?: boolean; className?: string }> = ({ fill, stroke, strokeWidth = 1.5, dashed, className }) => (
  <svg className={`absolute inset-0 w-full h-full ${className || ''}`} viewBox="0 0 100 86.6" preserveAspectRatio="none" aria-hidden>
    <polygon
      points="25,0 75,0 100,43.3 75,86.6 25,86.6 0,43.3"
      fill={fill}
      stroke={stroke}
      strokeWidth={strokeWidth}
      strokeDasharray={dashed ? '6 4' : undefined}
      vectorEffect="non-scaling-stroke"
      strokeLinejoin="round"
    />
  </svg>
);

const SHORT: Record<string, string> = {
  PM: 'PM', PO: 'PO', ARCHITECT: 'AR', BACKEND_DEV: 'BE', FRONTEND_DEV: 'FE', DESIGNER: 'DS', QA: 'QA',
  E2E_TESTER: 'E2E', DEVOPS: 'DO', REPORTER: 'RP', DOCUMENTOR: 'DC', SCM: 'SCM',
};

/** Takım altıgeni (grup): dış çerçeve + ad etiketi */
export const TeamHexNode = memo(({ data }: NodeProps) => {
  const { t } = useI18n();
  const d = data as { label: string; readOnly?: boolean; projectId?: string };
  return (
    <div className="w-full h-full relative pointer-events-none">
      <HexShape
        fill={d.readOnly ? 'color-mix(in oklab, var(--sunk) 55%, transparent)' : 'color-mix(in oklab, var(--panel2) 55%, transparent)'}
        stroke="var(--line2)"
        strokeWidth={2}
        dashed={!!d.readOnly}
      />
      <div className="absolute top-2 left-1/2 -translate-x-1/2 flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-panel border border-line shadow-panel text-[11px] font-bold text-ink font-mono whitespace-nowrap">
        <Building2 className="w-3.5 h-3.5 text-ac" />
        {d.label}
        {d.readOnly && <span className="text-[9px] font-normal text-ink3">• {t('agents.hex.partner', undefined, 'partner')} ({d.projectId})</span>}
      </div>
    </div>
  );
});
TeamHexNode.displayName = 'TeamHexNode';

/** Departman altıgeni (dekoratif grup): renkli zemin + etiket */
export const DeptHexNode = memo(({ data }: NodeProps) => {
  const { t } = useI18n();
  const d = data as { label: string; color: string; count: number; deptId?: string };
  return (
    <div className="w-full h-full relative pointer-events-none">
      <HexShape fill={`color-mix(in oklab, var(--${d.color}) 12%, var(--panel))`} stroke={`color-mix(in oklab, var(--${d.color}) 70%, transparent)`} strokeWidth={1.5} />
      <div className="absolute top-1.5 left-1/2 -translate-x-1/2 text-[9px] font-mono font-bold uppercase tracking-wider whitespace-nowrap px-1.5 py-0.5 rounded bg-panel/90 border border-line" style={{ color: `var(--${d.color})` }}>
        {d.deptId ? t(`agents.dept.${d.deptId}`, undefined, d.label) : d.label} • {d.count}
      </div>
    </div>
  );
});
DeptHexNode.displayName = 'DeptHexNode';

/** Toplantı odası altıgeni: müzakere / onay sırasında yanıp söner */
export const MeetingHexNode = memo(({ data }: NodeProps) => {
  const { t } = useI18n();
  const d = data as { label: string; active?: boolean; reason?: string };
  return (
    <div className="w-full h-full relative pointer-events-none">
      <HexShape
        className={d.active ? 'animate-pulse' : ''}
        fill={d.active ? 'color-mix(in oklab, var(--ac) 18%, var(--panel))' : 'var(--sunk)'}
        stroke={d.active ? 'var(--ac)' : 'var(--line2)'}
        strokeWidth={2}
        dashed={!d.active}
      />
      <div className="absolute inset-0 flex flex-col items-center justify-center text-center">
        <Users className={`w-5 h-5 ${d.active ? 'text-ac' : 'text-ink3'}`} />
        <span className="text-[10px] font-mono font-bold text-ink mt-1">{!d.label || d.label === 'Toplantı Odası' ? t('agents.hex.meetingRoom', undefined, 'Toplantı Odası') : d.label}</span>
        {d.active && <span className="text-[9px] font-mono text-ac">{d.reason || t('agents.hex.meetingOn', undefined, 'toplantı sürüyor')}</span>}
      </div>
    </div>
  );
});
MeetingHexNode.displayName = 'MeetingHexNode';

/** Ajan altıgeni: kompakt (ikon, kısa ad, durum noktası, token) — canlı veri AgentMeshContext'ten */
export const HexAgentNode = memo(({ data, selected }: NodeProps) => {
  const { t } = useI18n();
  const d = data as { agentId: string; agent?: Agent; color: string; readOnly?: boolean; gathered?: boolean };
  const ctx = useAgentMeshContext();
  const agent = (!d.readOnly && ctx.agentsById.get(d.agentId)) || d.agent;
  const status = agent?.status || 'IDLE';
  const cfg = STATUS_CONFIG[status] || STATUS_CONFIG.IDLE;
  const isSelected = !!selected || ctx.selectedAgentId === d.agentId;
  const active = status === 'WORKING' || status === 'BUG_FIX';
  const icon = ROLE_ICONS[agent?.role || d.agentId] || ROLE_ICONS[d.agentId] || <Code2 className="w-5 h-5 text-ink3" />;

  return (
    <div className="w-full h-full relative cursor-pointer group" title={`${agent?.name || d.agentId} • ${t(cfg.labelKey, undefined, cfg.label)}`}>
      <div
        className="absolute inset-0 transition-all"
        style={{
          clipPath: HEX_CLIP,
          background: isSelected ? 'color-mix(in oklab, var(--ac) 22%, var(--panel))' : active ? 'color-mix(in oklab, var(--ok) 14%, var(--panel))' : 'var(--panel)',
        }}
      />
      {/* Kenarlık: clip-path border'ı kestiği için ikinci bir katman */}
      <div
        className="absolute inset-0"
        style={{
          clipPath: HEX_CLIP,
          background: isSelected ? 'var(--ac)' : active ? 'var(--ok)' : `var(--${d.color})`,
          opacity: isSelected ? 0.9 : 0.55,
          WebkitMaskImage: 'linear-gradient(#000,#000)',
          zIndex: -1,
          transform: 'scale(1.06)',
        }}
      />
      <div className="absolute inset-0 flex flex-col items-center justify-center gap-0.5">
        <div className="relative">
          {icon}
          <span className={`absolute -top-1 -right-2 w-2 h-2 rounded-full ${cfg.dot} ${status !== 'IDLE' ? 'animate-pulse' : ''}`} />
        </div>
        <span className="text-[10px] font-mono font-bold text-ink leading-none">{SHORT[d.agentId] || d.agentId.slice(0, 3)}</span>
        <span className="text-[8px] font-mono text-ink3 leading-none">{(agent?.total_tokens || 0).toLocaleString('tr-TR')}</span>
      </div>
      {d.gathered && <span className="absolute -top-1 left-1/2 -translate-x-1/2 text-[8px] font-mono px-1 rounded bg-acd text-ac border border-ac/40">{t('agents.hex.atTable', undefined, 'masada')}</span>}
      {agent?.current_dialogue && active && (
        <div className="absolute -top-9 left-1/2 -translate-x-1/2 max-w-[180px] truncate text-[9px] font-sans px-2 py-1 rounded-lg bg-panel border border-ac/40 text-ink shadow-panel opacity-0 group-hover:opacity-100 transition pointer-events-none">
          "{agent.current_dialogue}"
        </div>
      )}
      <Handle type="target" position={Position.Left} id="t" className="!w-1.5 !h-1.5 !bg-line2 !border-0 !opacity-0" />
      <Handle type="source" position={Position.Right} id="s" className="!w-1.5 !h-1.5 !bg-line2 !border-0 !opacity-0" />
    </div>
  );
});
HexAgentNode.displayName = 'HexAgentNode';
