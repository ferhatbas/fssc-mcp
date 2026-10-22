import React, { memo, useEffect, useState } from 'react';
import { Handle, Position } from '@xyflow/react';
import { 
  ClipboardList, 
  Palette,
  Layers, 
  Code2, 
  CheckCircle2, 
  Rocket, 
  FileCode2, 
  Sparkles, 
  Activity, 
  Server, 
  Layout, 
  CheckCheck, 
  MessageSquare, 
  BrainCircuit, 
  Zap,
  ShieldCheck,
  BarChart3,
  BookOpen,
  GitBranch,
  X
} from 'lucide-react';
import { Agent } from '../types/telemetry';
import { useAgentMeshContext } from './agentMeshContext';
import { useI18n } from '../i18n';

interface AgentNodeProps {
  data: {
    /** Bağlamdan (AgentMeshContext) canlı veri okunur; bu alan yalnızca yedek/başlangıç değeridir */
    agent: Agent;
    agentId?: string;
    isActive?: boolean;
    /** Uygulama seviyesinde seçili ajan (zaman çizelgesi çekmecesi açık) */
    isSelected?: boolean;
  };
  /** React Flow'un kendi seçim durumu (tıklama / lasso) */
  selected?: boolean;
}

export const ROLE_ICONS: Record<string, React.ReactNode> = {
  PM: <ClipboardList className="w-5 h-5 text-ac" />,
  ARCHITECT: <Layers className="w-5 h-5 text-info" />,
  DEVELOPER: <Code2 className="w-5 h-5 text-ok" />,
  BACKEND_DEV: <Server className="w-5 h-5 text-ok" />,
  FRONTEND_DEV: <Layout className="w-5 h-5 text-info" />,
  DESIGNER: <Palette className="w-5 h-5 text-ac" />,
  QA: <CheckCircle2 className="w-5 h-5 text-warn" />,
  E2E_TESTER: <CheckCheck className="w-5 h-5 text-warn" />,
  DEVOPS: <Rocket className="w-5 h-5 text-ac" />,
  PO: <ShieldCheck className="w-5 h-5 text-ac" />,
  REPORTER: <BarChart3 className="w-5 h-5 text-info" />,
  DOCUMENTOR: <BookOpen className="w-5 h-5 text-ok" />,
  SCM: <GitBranch className="w-5 h-5 text-warn" />,
};

export const STATUS_CONFIG: Record<string, { label: string; labelKey: string; color: string; border: string; bg: string; dot: string; ringStyle?: React.CSSProperties }> = {
  IDLE: { 
    label: 'BOŞTA (IDLE)', 
    labelKey: 'agents.status.idle',
    color: 'text-ink3', 
    border: 'border-line', 
    bg: 'bg-panel', 
    dot: 'bg-ink3' 
  },
  WORKING: { 
    label: 'ÇALIŞIYOR', 
    labelKey: 'agents.status.working',
    color: 'text-ok font-bold', 
    border: 'border-ok', 
    bg: 'bg-panel2', 
    dot: 'bg-ok',
    ringStyle: { boxShadow: '0 0 0 4px color-mix(in oklab, var(--ok) 16%, transparent)' } 
  },
  BUG_FIX: { 
    label: 'BUG FIXING', 
    labelKey: 'agents.status.bugFix',
    color: 'text-warn font-bold', 
    border: 'border-warn', 
    bg: 'bg-panel2', 
    dot: 'bg-warn',
    ringStyle: { boxShadow: '0 0 0 4px color-mix(in oklab, var(--warn) 16%, transparent)' } 
  },
  PENDING_ACTION: { 
    label: 'GÖREV BEKLİYOR', 
    labelKey: 'agents.status.pending',
    color: 'text-info font-bold', 
    border: 'border-info', 
    bg: 'bg-panel2', 
    dot: 'bg-info',
    ringStyle: { boxShadow: '0 0 0 4px color-mix(in oklab, var(--info) 14%, transparent)' } 
  },
  ERROR: { 
    label: 'HATA OLUŞTU', 
    labelKey: 'agents.status.error',
    color: 'text-err font-bold', 
    border: 'border-err', 
    bg: 'bg-panel2', 
    dot: 'bg-err',
    ringStyle: { boxShadow: '0 0 0 4px color-mix(in oklab, var(--err) 16%, transparent)' } 
  },
  COMPLETED: { 
    label: 'TAMAMLANDI', 
    labelKey: 'agents.status.completed',
    color: 'text-ok font-bold', 
    border: 'border-ok', 
    bg: 'bg-panel2', 
    dot: 'bg-ok' 
  },
};

/** Koşunun gerçek durumundan türetilen kart rolleri (Agent.live_role): son olaya bakan eski durumdan daha belirgin ve güvenilir. */
const LIVE_CONFIG: Record<'claude' | 'manager' | 'waiting', { label: string; labelKey: string; color: string; border: string; bg: string; dot: string; ringStyle: React.CSSProperties }> = {
  claude: {
    label: 'CLAUDE ÜRETİYOR', labelKey: 'agents.live.claude', color: 'text-ok font-bold', border: 'border-ok', bg: 'bg-okd', dot: 'bg-ok',
    ringStyle: { boxShadow: '0 0 0 6px color-mix(in oklab, var(--ok) 28%, transparent), 0 0 28px color-mix(in oklab, var(--ok) 40%, transparent)' },
  },
  manager: {
    label: 'SENDE — KARAR/ONAY', labelKey: 'agents.live.manager', color: 'text-warn font-bold', border: 'border-warn', bg: 'bg-warnd', dot: 'bg-warn',
    ringStyle: { boxShadow: '0 0 0 6px color-mix(in oklab, var(--warn) 28%, transparent), 0 0 28px color-mix(in oklab, var(--warn) 35%, transparent)' },
  },
  waiting: {
    label: 'CLAUDE BEKLENİYOR', labelKey: 'agents.live.waiting', color: 'text-info font-bold', border: 'border-info', bg: 'bg-infod', dot: 'bg-info',
    ringStyle: { boxShadow: '0 0 0 5px color-mix(in oklab, var(--info) 22%, transparent)' },
  },
};

export const AgentNode = memo(({ data, selected }: AgentNodeProps) => {
  const { t } = useI18n();
  const ctx = useAgentMeshContext();
  const agentId = data.agentId || data.agent.id;
  const agent = ctx.agentsById.get(agentId) || data.agent;
  const isActive = data.isActive ?? (agent.status === 'WORKING' || agent.status === 'BUG_FIX' || !!agent.live_role);
  const isSelected = !!data.isSelected || !!selected || ctx.selectedAgentId === agentId;
  const liveCfg = agent.live_role ? LIVE_CONFIG[agent.live_role] : undefined;
  const statusCfg = liveCfg || STATUS_CONFIG[agent.status] || STATUS_CONFIG.IDLE;
  const roleIcon = ROLE_ICONS[agent.role] || ROLE_ICONS[agent.id] || <Code2 className="w-5 h-5 text-ink3" />;

  // Konuşma paneli: kartın içinde, 💬 tuşuyla açılır; metne veya ×'e tıklayınca kapanır (kalabalık olmasın).
  // Kapatılan mesaj hatırlanır; aynı ajan yeni bir şey söyleyince gösterge yeniden yanar.
  const [dialogueOpen, setDialogueOpen] = useState(false);
  const [dismissed, setDismissed] = useState<string | null>(null);
  const dialogue = agent.current_dialogue && agent.current_dialogue !== dismissed ? agent.current_dialogue : null;
  useEffect(() => {
    if (!agent.current_dialogue) setDialogueOpen(false);
  }, [agent.current_dialogue]);
  const stop = (e: React.SyntheticEvent) => e.stopPropagation();
  const dismissDialogue = (e: React.SyntheticEvent) => {
    stop(e);
    setDismissed(agent.current_dialogue || null);
    setDialogueOpen(false);
  };

  return (
    <div 
      style={statusCfg.ringStyle}
      title={t('agents.node.clickTimeline', undefined, 'Zaman çizelgesi için tıkla')}
      className={`relative w-[280px] rounded-card border p-4 transition-all duration-300 cursor-pointer ${statusCfg.border} ${statusCfg.bg} ${
        isSelected ? 'ring-2 ring-ac shadow-panel scale-[1.03]' : isActive ? 'scale-105 ring-2 ring-ac/60 shadow-panel' : 'hover:border-line2 shadow-xs'
      }`}
    >
      {/* React Flow Handles */}
      <Handle 
        type="target" 
        position={Position.Left} 
        id="target-left"
        className="!w-3 !h-3 !bg-ac !border-2 !border-panel -left-1.5" 
      />
      <Handle 
        type="target" 
        position={Position.Bottom} 
        id="target-bottom"
        className="!w-3 !h-3 !bg-err !border-2 !border-panel -bottom-1.5" 
      />

      <Handle 
        type="source" 
        position={Position.Right} 
        id="source-right"
        className="!w-3 !h-3 !bg-ok !border-2 !border-panel -right-1.5" 
      />
      <Handle
        type="source"
        position={Position.Top}
        id="source-top"
        className="!w-3 !h-3 !bg-ac !border-2 !border-panel -top-1.5"
      />
      {/* Üst hedef ve alt kaynak tutamaçları (dikey akışlar: QA→E2E, BE→FE, DEVOPS→PO) */}
      <Handle
        type="target"
        position={Position.Top}
        id="target-top"
        className="!w-3 !h-3 !bg-info !border-2 !border-panel -top-1.5 !left-[35%]"
      />
      <Handle
        type="source"
        position={Position.Bottom}
        id="source-bottom"
        className="!w-3 !h-3 !bg-info !border-2 !border-panel -bottom-1.5 !left-[65%]"
      />

      {/* Header: Role Icon & Name */}
      <div className="flex items-center justify-between gap-3 mb-2.5">
        <div className="flex items-center gap-2.5">
          <div className="w-[32px] h-[32px] rounded-[9px] bg-sunk border border-line flex items-center justify-center shadow-xs">
            {roleIcon}
          </div>
          <div>
            <h3 className="text-sm font-bold text-ink tracking-tight font-sans">{agent.name}</h3>
            <span className="text-[10px] font-mono uppercase tracking-wider text-ink3 font-semibold">
              {agent.role}
            </span>
            {agent.live_role === 'claude' && (
              <span className="ml-1.5 text-[9px] font-mono font-bold px-1.5 py-0.5 rounded-full bg-ok text-onac align-middle" title={t('agents.node.claudeNow', undefined, 'Claude bu adımı şu an üretiyor')}>● CLAUDE</span>
            )}
          </div>
        </div>

        <div className="flex items-center gap-2">
          {agent.current_dialogue && (
            <button
              type="button"
              onClick={(e) => { stop(e); setDialogueOpen(o => !o); }}
              onMouseDown={stop}
              title={dialogue ? t('agents.node.toggleDialogue', undefined, 'Konuşmayı göster/gizle') : t('agents.node.dialogueClosed', undefined, 'Konuşma kapatıldı')}
              className={`nodrag nopan relative w-6 h-6 rounded-md border flex items-center justify-center transition ${
                dialogueOpen ? 'bg-acd border-ac/40 text-ac' : dialogue ? 'bg-panel border-line text-ac hover:bg-acd' : 'bg-panel border-line text-ink3'
              }`}
            >
              <MessageSquare className="w-3.5 h-3.5" />
              {dialogue && !dialogueOpen && <span className="absolute -top-1 -right-1 w-2 h-2 rounded-full bg-ac animate-pulse" />}
            </button>
          )}
        {/* Live status dot */}
        <span className="flex h-2.5 w-2.5 relative">
          {agent.status !== 'IDLE' && (
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-ac opacity-75"></span>
          )}
          <span className={`relative inline-flex rounded-full h-2.5 w-2.5 ${statusCfg.dot}`}></span>
        </span>
        </div>
      </div>

      {/* Konuşma paneli (kart içi, açılır-kapanır; tıklayınca kapanır) */}
      {dialogueOpen && dialogue && (
        <div
          role="button"
          onClick={dismissDialogue}
          onMouseDown={stop}
          title={t('agents.node.clickClose', undefined, 'Kapatmak için tıkla')}
          className="nodrag nopan mb-2 px-2.5 py-2 rounded-lg bg-panel border border-ac/40 text-[11px] text-ink font-sans leading-snug cursor-pointer hover:bg-acd/40 animate-fadeIn"
        >
          <div className="flex items-start gap-2">
            <MessageSquare className="w-3.5 h-3.5 text-ac shrink-0 mt-0.5" />
            <div className="flex-1 min-w-0">
              <span className="text-[9px] uppercase font-bold text-ac block mb-0.5">💬 {agent.name}</span>
              "{dialogue}"
            </div>
            <span className="text-ink3 hover:text-ink shrink-0" aria-label={t('common.close', undefined, 'Kapat')}><X className="w-3 h-3" /></span>
          </div>
        </div>
      )}

      {/* Status Pill */}
      <div className="flex items-center justify-between text-xs py-1 px-2.5 rounded-md bg-sunk border border-line mb-2">
        <span className="text-[11px] font-semibold text-ink3 flex items-center gap-1.5">
          <Activity className="w-3 h-3 text-ink3" />
          {t('agents.node.status', undefined, 'Durum')}
        </span>
        <span className={`text-[10px] font-mono tracking-wider ${statusCfg.color}`}>
          {t(statusCfg.labelKey, undefined, statusCfg.label)}
        </span>
      </div>

      {/* Live Thinking Block */}
      {agent.current_thinking && agent.status !== 'IDLE' && (
        <div className="mb-2 px-2.5 py-1.5 rounded-lg bg-acd/60 border border-ac/30 text-[11px] animate-fadeIn">
          <div className="flex items-center gap-1 font-bold text-ac text-[9px] uppercase tracking-wider mb-0.5">
            <BrainCircuit className="w-3 h-3 animate-pulse text-ac" />
            {t('agents.node.thinking', undefined, 'LLM Düşünüyor:')}
          </div>
          <p className="text-ink text-[10px] leading-tight line-clamp-2 italic font-sans">
            "{agent.current_thinking}"
          </p>
        </div>
      )}

      {/* Live Action (What Doing) Block */}
      {agent.current_what_doing && agent.status !== 'IDLE' && (
        <div className="mb-2 px-2.5 py-1 rounded-lg bg-okd/60 border border-ok/30 text-[10px]">
          <div className="flex items-center gap-1 font-bold text-ok text-[9px] uppercase tracking-wider">
            <Zap className="w-3 h-3 text-ok shrink-0" />
            <span className="truncate text-ink font-medium">{agent.current_what_doing}</span>
          </div>
        </div>
      )}

      {/* Active File Tracking */}
      {agent.active_file && (
        <div className="flex items-center gap-1.5 text-[10px] font-mono text-ink2 bg-sunk px-2 py-1 rounded border border-line mb-2 truncate" title={agent.active_file}>
          <FileCode2 className="w-3 h-3 text-ac shrink-0" />
          <span className="truncate text-ink">{agent.active_file.split('/').slice(-2).join('/')}</span>
        </div>
      )}

      {/* Footer Metrics: Tokens & Last Action */}
      <div className="flex items-center justify-between pt-2 border-t border-line text-[10px] font-mono text-ink3">
        <span className="flex items-center gap-1">
          <Sparkles className="w-3 h-3 text-warn" />
          {agent.total_tokens.toLocaleString()} tok
        </span>
        <span className="truncate max-w-[120px] text-right text-ink2 font-semibold" title={agent.last_action}>
          {agent.last_action}
        </span>
      </div>
    </div>
  );
});

AgentNode.displayName = 'AgentNode';
