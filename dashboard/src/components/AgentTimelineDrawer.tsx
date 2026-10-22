import React, { useEffect, useMemo, useState } from 'react';
import {
  X, Clock, ChevronDown, ChevronRight, ArrowRight, ArrowLeft, FileCode2, Brain, Zap,
  MessageSquare, Gavel, History, Users, RefreshCw, Activity, Sparkles
} from 'lucide-react';
import { Agent, TelemetryEvent } from '../types/telemetry';
import { ROLE_ICONS, STATUS_CONFIG } from './AgentNode';
import { useAgentTimeline, TimelineAudit } from '../hooks/useAgentTimeline';
import { useRealUsage, usageTitle, fmtTok } from '../hooks/useRealUsage';
import { useI18n } from '../i18n';
import { LOCALE_OF } from './AgentMesh';

interface AgentTimelineDrawerProps {
  agentId: string | null;
  agents: Agent[];
  liveEvents: TelemetryEvent[];
  projectId?: string;
  onClose: () => void;
  onSelectAgent?: (agentId: string) => void;
}

/** Kararı temsil eden aksiyonlar ("Karar" rozeti) */
const DECISION_ACTIONS = new Set(['REPORT_BUG', 'APPROVE_BUILD', 'UAT_APPROVED', 'UAT_REJECTED', 'DEPLOY_CONFIRM', 'DELIBERATION_SPEECH', 'E2E_TEST_FAILED',
  'VERIFICATION_PASSED', 'VERIFICATION_FAILED', 'COMMITTED', 'BACKLOG_PUBLISHED', 'REQUEST_ENHANCEMENT', 'APP_START_FAILED']);

type Entry =
  | { kind: 'event'; ts: string; event: TelemetryEvent }
  | { kind: 'audit'; ts: string; audit: TimelineAudit };

function toIso(ts: string): string {
  // Denetim kayıtları "YYYY-MM-DD HH:MM:SS" (UTC) biçimindedir; olaylar ISO
  if (/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$/.test(ts)) return ts.replace(' ', 'T') + '+00:00';
  return ts;
}

function dayKey(iso: string, loc: string, unknownDay: string): string {
  const d = new Date(iso);
  return isNaN(d.getTime()) ? unknownDay : d.toLocaleDateString(loc, { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric' });
}

function hourKey(iso: string): string {
  const d = new Date(iso);
  return isNaN(d.getTime()) ? '--:00' : `${String(d.getHours()).padStart(2, '0')}:00`;
}

function timeLabel(iso: string, loc: string): string {
  const d = new Date(iso);
  return isNaN(d.getTime()) ? iso : d.toLocaleTimeString(loc, { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

export const AgentTimelineDrawer: React.FC<AgentTimelineDrawerProps> = ({ agentId, agents, liveEvents, projectId, onClose, onSelectAgent }) => {
  const { t, lang } = useI18n();
  const loc = LOCALE_OF[lang];
  const realUsage = useRealUsage(30000, liveEvents.length);
  const { data, events, loading, error, refresh } = useAgentTimeline(agentId, liveEvents, projectId);
  const [tab, setTab] = useState<'timeline' | 'interactions'>('timeline');
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());

  useEffect(() => {
    if (!agentId) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [agentId, onClose]);

  const agent = useMemo(() => agents.find(a => a.id === agentId) || data?.agent || null, [agents, agentId, data]);

  // Gün → saat gruplama (yeniden eskiye)
  const groups = useMemo(() => {
    if (!agentId) return [] as { day: string; hours: { hour: string; entries: Entry[] }[] }[];
    const entries: Entry[] = [
      ...events.map(e => ({ kind: 'event' as const, ts: e.timestamp, event: e })),
      ...(data?.audits || []).map(a => ({ kind: 'audit' as const, ts: toIso(a.timestamp), audit: a })),
    ];
    entries.sort((a, b) => (a.ts < b.ts ? 1 : -1));
    const days = new Map<string, Map<string, Entry[]>>();
    for (const en of entries) {
      const d = dayKey(en.ts, loc, t('agents.drawer.unknownDay', undefined, 'Bilinmeyen gün'));
      const h = hourKey(en.ts);
      if (!days.has(d)) days.set(d, new Map());
      const hours = days.get(d)!;
      if (!hours.has(h)) hours.set(h, []);
      hours.get(h)!.push(en);
    }
    return [...days.entries()].map(([day, hours]) => ({
      day,
      hours: [...hours.entries()].map(([hour, list]) => ({ hour, entries: list })),
    }));
  }, [events, data, agentId, loc, t]);

  if (!agentId) return null;

  const toggle = (key: string) => {
    setCollapsed(prev => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  const statusCfg = STATUS_CONFIG[agent?.status || 'IDLE'] || STATUS_CONFIG.IDLE;
  const interactions = Object.entries(data?.interactions || {}).sort((a, b) => (b[1].sent + b[1].received) - (a[1].sent + a[1].received));
  const decisionCount = events.filter(e => DECISION_ACTIONS.has(e.action)).length;

  return (
    <aside className="fixed top-0 right-0 h-full w-[440px] max-w-[95vw] z-40 bg-panel border-l border-line shadow-panel flex flex-col animate-in slide-in-from-right duration-200">
      {/* Başlık */}
      <div className="px-4 py-3 border-b border-line bg-panel2 flex items-start justify-between gap-3">
        <div className="flex items-center gap-3 min-w-0">
          <div className="w-10 h-10 rounded-[10px] bg-sunk border border-line flex items-center justify-center shrink-0">
            {ROLE_ICONS[agent?.role || agentId] || <Users className="w-5 h-5 text-ink3" />}
          </div>
          <div className="min-w-0">
            <h3 className="text-sm font-bold text-ink truncate">{agent?.name || agentId}</h3>
            <div className="flex items-center gap-2 mt-0.5">
              <span className="text-[10px] font-mono uppercase tracking-wider text-ink3">{agent?.role || agentId}</span>
              <span className={`text-[10px] font-mono px-1.5 py-0.5 rounded border ${statusCfg.border} ${statusCfg.color} bg-sunk`}>{t(statusCfg.labelKey, undefined, statusCfg.label)}</span>
            </div>
          </div>
        </div>
        <div className="flex items-center gap-1 shrink-0">
          <button onClick={refresh} className="p-1.5 rounded-md text-ink3 hover:text-ink hover:bg-sunk transition" title={t('agents.drawer.refresh', undefined, 'Yenile')}>
            <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
          </button>
          <button onClick={onClose} className="p-1.5 rounded-md text-ink3 hover:text-ink hover:bg-sunk transition" title={t('agents.drawer.closeEsc', undefined, 'Kapat (Esc)')}>
            <X className="w-4 h-4" />
          </button>
        </div>
      </div>

      {/* Özet çipleri */}
      <div className="px-4 py-2 border-b border-line grid grid-cols-4 gap-2 text-center">
        {[
          { label: t('agents.drawer.events', undefined, 'Olay'), value: events.length, icon: <Activity className="w-3 h-3" /> },
          { label: t('agents.drawer.decisions', undefined, 'Karar'), value: decisionCount, icon: <Gavel className="w-3 h-3" /> },
          { label: t('agents.drawer.notes', undefined, 'Not'), value: data?.audits.length || 0, icon: <History className="w-3 h-3" /> },
          realUsage?.available && agentId && realUsage.by_agent[agentId]
            ? { label: t('agents.drawer.tokReal', undefined, 'Token (gerçek)'), value: fmtTok(realUsage.by_agent[agentId].output), icon: <Sparkles className="w-3 h-3" />, title: usageTitle(realUsage.by_agent[agentId]) }
            : { label: t('agents.drawer.tokEst', undefined, 'Token (tahmini)'), value: (agent?.total_tokens || 0).toLocaleString(loc), icon: <Sparkles className="w-3 h-3" />, title: t('agents.drawer.tokEstTitle', undefined, 'Tahmin: bu ajan için gerçek kullanım eşleşmedi') },
        ].map(c => (
          <div key={c.label} className="bg-sunk border border-line rounded-card px-2 py-1.5" title={(c as { title?: string }).title}>
            <div className="text-[9px] uppercase tracking-wider text-ink3 flex items-center justify-center gap-1">{c.icon}{c.label}</div>
            <div className="text-sm font-mono font-bold text-ink">{c.value}</div>
          </div>
        ))}
      </div>

      {/* Sekmeler */}
      <div className="px-4 pt-2 flex items-center gap-1 text-xs font-mono">
        <div className="flex items-center bg-sunk p-0.5 rounded-lg border border-line">
          <button onClick={() => setTab('timeline')} className={`px-3 py-1 rounded-md transition ${tab === 'timeline' ? 'bg-ac text-onac font-bold' : 'text-ink3 hover:text-ink'}`}>
            {t('agents.drawer.timeline', undefined, 'Zaman Çizelgesi')}
          </button>
          <button onClick={() => setTab('interactions')} className={`px-3 py-1 rounded-md transition ${tab === 'interactions' ? 'bg-ac text-onac font-bold' : 'text-ink3 hover:text-ink'}`}>
            {t('agents.drawer.interactions', undefined, 'Etkileşimler')} ({interactions.length})
          </button>
        </div>
        {error && <span className="ml-auto text-[10px] text-err truncate">{error}</span>}
      </div>

      {/* İçerik */}
      <div className="flex-1 overflow-y-auto px-4 py-3 space-y-3">
        {tab === 'timeline' && groups.length === 0 && (
          <div className="text-center text-ink3 text-xs italic py-8">
            {loading ? t('agents.drawer.loading', undefined, 'Zaman çizelgesi yükleniyor…') : t('agents.drawer.empty', undefined, 'Bu ajan için henüz olay kaydı yok.')}
          </div>
        )}

        {tab === 'timeline' && groups.map(group => {
          const dayCollapsed = collapsed.has(group.day);
          const dayCount = group.hours.reduce((n, h) => n + h.entries.length, 0);
          return (
            <div key={group.day} className="space-y-2">
              <button onClick={() => toggle(group.day)} className="w-full flex items-center gap-2 text-left text-[11px] font-bold text-ink uppercase tracking-wider font-mono">
                {dayCollapsed ? <ChevronRight className="w-3.5 h-3.5 text-ink3" /> : <ChevronDown className="w-3.5 h-3.5 text-ink3" />}
                <span>{group.day}</span>
                <span className="ml-auto text-[10px] font-normal text-ink3">{t('agents.drawer.records', { n: dayCount }, '{n} kayıt')}</span>
              </button>
              {!dayCollapsed && group.hours.map(h => {
                const hourKeyId = `${group.day}|${h.hour}`;
                const hourCollapsed = collapsed.has(hourKeyId);
                return (
                  <div key={hourKeyId} className="pl-2 border-l-2 border-line ml-1.5 space-y-1.5">
                    <button onClick={() => toggle(hourKeyId)} className="flex items-center gap-1.5 text-[10px] font-mono text-ink2 hover:text-ink">
                      <Clock className="w-3 h-3 text-ac" />
                      <span className="font-semibold">{h.hour}</span>
                      <span className="text-ink3">• {h.entries.length}</span>
                      {hourCollapsed ? <ChevronRight className="w-3 h-3 text-ink3" /> : <ChevronDown className="w-3 h-3 text-ink3" />}
                    </button>
                    {!hourCollapsed && h.entries.map((en, idx) =>
                      en.kind === 'event'
                        ? <EventEntry key={`${en.event.id}-${idx}`} event={en.event} agentId={agentId} onSelectAgent={onSelectAgent} />
                        : <AuditEntry key={`${en.audit.id}-${idx}`} audit={en.audit} />
                    )}
                  </div>
                );
              })}
            </div>
          );
        })}

        {tab === 'interactions' && (
          <div className="space-y-2">
            {interactions.length === 0 && <div className="text-center text-ink3 text-xs italic py-8">{t('agents.drawer.noInteractions', undefined, 'Etkileşim kaydı yok.')}</div>}
            {interactions.map(([other, s]) => {
              const otherAgent = agents.find(a => a.id === other);
              return (
                <button
                  key={other}
                  onClick={() => onSelectAgent?.(other)}
                  className="w-full text-left bg-panel2 border border-line rounded-card px-3 py-2 hover:border-ac transition flex items-center gap-3"
                >
                  <div className="w-8 h-8 rounded-lg bg-sunk border border-line flex items-center justify-center shrink-0">
                    {ROLE_ICONS[otherAgent?.role || other] || <Users className="w-4 h-4 text-ink3" />}
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="text-xs font-bold text-ink truncate">{otherAgent?.name || other}</div>
                    <div className="text-[10px] font-mono text-ink3 truncate">{t('agents.drawer.last', undefined, 'son')}: {s.last_action || '-'} • {s.last_at ? timeLabel(s.last_at, loc) : '-'}</div>
                  </div>
                  <div className="text-[10px] font-mono text-right shrink-0">
                    <div className="text-ok">→ {t('agents.drawer.sent', { n: s.sent }, '{n} gönderdi')}</div>
                    <div className="text-info">← {t('agents.drawer.received', { n: s.received }, '{n} aldı')}</div>
                  </div>
                </button>
              );
            })}
          </div>
        )}
      </div>
    </aside>
  );
};

const EventEntry: React.FC<{ event: TelemetryEvent; agentId: string; onSelectAgent?: (id: string) => void }> = ({ event, agentId, onSelectAgent }) => {
  const { t, lang } = useI18n();
  const loc = LOCALE_OF[lang];
  const outgoing = event.from_agent?.toUpperCase() === agentId.toUpperCase();
  const counterpart = outgoing ? event.to_agent : event.from_agent;
  const isDecision = DECISION_ACTIONS.has(event.action);
  const failed = event.status === 'FAILED';
  const sentiment = event.payload?.sentiment as string | undefined;
  const files: string[] = Array.isArray(event.payload?.files) ? event.payload.files : [];
  const [open, setOpen] = useState(false);

  return (
    <div className={`rounded-card border px-2.5 py-2 text-[11px] ${failed ? 'bg-errd/50 border-err/40' : isDecision ? 'bg-warnd/40 border-warn/40' : 'bg-panel2 border-line'}`}>
      <div className="flex items-center gap-2 flex-wrap">
        <span className="font-mono text-[10px] text-ink3">{timeLabel(event.timestamp, loc)}</span>
        <span className={`font-mono font-bold px-1.5 py-0.5 rounded border ${failed ? 'text-err border-err/40 bg-errd' : 'text-ac border-ac/30 bg-acd'}`}>{event.action}</span>
        {isDecision && (
          <span className="inline-flex items-center gap-1 text-[9px] font-bold uppercase px-1.5 py-0.5 rounded bg-warnd text-warn border border-warn/40">
            <Gavel className="w-3 h-3" /> {t('agents.drawer.decisions', undefined, 'Karar')}{sentiment ? ` • ${sentiment}` : ''}
          </span>
        )}
        <button onClick={() => counterpart && counterpart !== 'ALL' && onSelectAgent?.(counterpart)} className="ml-auto inline-flex items-center gap-1 font-mono text-[10px] text-ink2 hover:text-ac">
          {outgoing ? <ArrowRight className="w-3 h-3 text-ok" /> : <ArrowLeft className="w-3 h-3 text-info" />}
          {counterpart}
        </button>
      </div>
      {event.friendly_dialogue && (
        <p className="mt-1 text-ink italic flex items-start gap-1.5"><MessageSquare className="w-3 h-3 text-ac shrink-0 mt-0.5" /><span>"{event.friendly_dialogue}"</span></p>
      )}
      {(event.thinking || event.what_doing || event.what_next || event.current_file || files.length > 0 || event.payload) && (
        <button onClick={() => setOpen(o => !o)} className="mt-1 text-[10px] text-ink3 hover:text-ink font-mono">
          {open ? t('agents.drawer.hideDetail', undefined, '▾ detayı gizle') : t('agents.drawer.showDetail', undefined, '▸ düşünce, aksiyon ve çıktılar')}
        </button>
      )}
      {open && (
        <div className="mt-1.5 space-y-1 text-[10px]">
          {event.thinking && <div className="flex items-start gap-1.5 text-ink2"><Brain className="w-3 h-3 text-ac shrink-0 mt-0.5" /><span>{event.thinking}</span></div>}
          {event.what_doing && <div className="flex items-start gap-1.5 text-ink2"><Zap className="w-3 h-3 text-ok shrink-0 mt-0.5" /><span>{event.what_doing}</span></div>}
          {event.what_next && <div className="flex items-start gap-1.5 text-ink2"><ArrowRight className="w-3 h-3 text-info shrink-0 mt-0.5" /><span>{event.what_next}</span></div>}
          {event.current_file && <div className="flex items-center gap-1.5 font-mono text-ink2"><FileCode2 className="w-3 h-3 text-ac shrink-0" />{event.current_file}</div>}
          {files.length > 0 && (
            <div className="flex flex-wrap gap-1">
              {files.map(f => <span key={f} className="font-mono px-1.5 py-0.5 rounded bg-sunk border border-line text-ink2">{f}</span>)}
            </div>
          )}
          {event.payload?.task_id && <div className="font-mono text-ink3">{t('agents.drawer.task', undefined, 'görev')}: {event.payload.task_id}</div>}
          {event.tokens_used ? <div className="font-mono text-ink3">{event.tokens_used} {t('agents.drawer.token', undefined, 'token')}</div> : null}
        </div>
      )}
    </div>
  );
};

const AuditEntry: React.FC<{ audit: TimelineAudit }> = ({ audit }) => {
  const { lang } = useI18n();
  const loc = LOCALE_OF[lang];
  return (
  <div className="rounded-card border border-line bg-sunk px-2.5 py-2 text-[11px]">
    <div className="flex items-center gap-2 flex-wrap">
      <span className="font-mono text-[10px] text-ink3">{timeLabel(toIso(audit.timestamp), loc)}</span>
      <span className="inline-flex items-center gap-1 font-mono font-bold px-1.5 py-0.5 rounded border text-warn border-warn/40 bg-warnd"><History className="w-3 h-3" />{audit.action}</span>
      {audit.issue_id && <span className="font-mono text-[10px] text-ac">{audit.issue_id}</span>}
      {audit.status && <span className="ml-auto font-mono text-[10px] text-ink3">{audit.status}</span>}
    </div>
    {audit.notes && <p className="mt-1 text-ink2">{audit.notes}</p>}
    {audit.files_affected && audit.files_affected.length > 0 && (
      <div className="mt-1 flex flex-wrap gap-1">
        {audit.files_affected.map(f => <span key={f} className="font-mono text-[10px] px-1.5 py-0.5 rounded bg-panel border border-line text-ink2">{f}</span>)}
      </div>
    )}
  </div>
  );
};
