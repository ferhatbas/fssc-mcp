import React, { useCallback, useEffect, useState } from 'react';
import { confirmDialog } from '../lib/dialog';
import { X, ClipboardList, RefreshCw } from 'lucide-react';
import { api } from '../config';
import { useI18n } from '../i18n';

/**
 * G8: Yönetim Merkezi — sunucudaki hazır verilerin ekranları: toplantılar ve karar kayıtları (ADR), iş planı ağacı (epik ▸ hikâye ▸ görev),
 * öğrenme döngüsü (sprint eğilimi, retro aksiyonları, istem değişiklikleri + geri alma), Claude etkinliği ve runner durumu.
 * Sunucu olayları (MEETING_CLOSED, ADR_RECORDED, PLAN_GENERATED, PROMPT_CHANGED ...) `versions` ile ekranı tazeler.
 */
interface Props {
  isOpen: boolean;
  onClose: () => void;
  versions: { plan: number; meetings: number; learning: number };
}

type Tab = 'MEETINGS' | 'PLAN' | 'LEARNING' | 'ACTIVITY';
// yedek metinler; çeviri sprint.mgmt.tab.<ANAHTAR>
const TABS: { key: Tab; label: string }[] = [
  { key: 'MEETINGS', label: 'Toplantılar & ADR' }, { key: 'PLAN', label: 'İş planı' }, { key: 'LEARNING', label: 'Öğrenme' }, { key: 'ACTIVITY', label: 'Claude etkinliği' },
];

interface Meeting { id: string; type: string; sprint: number; date: string; summary?: string; participants?: string[]; decision_ids?: string[]; question_ids?: string[] }
interface Adr { number: string; file: string; title: string; status: string }
interface PlanNode { id: string; task_key?: string | null; title: string; kind: string; status: string; assignee?: string; work_type?: string | null; sprint?: number | null; priority?: string; carry_over?: { count?: number } | null; needs_rescope?: boolean | null; children?: PlanNode[] }
interface Learning {
  trend: { sprint: number; status: string; committed: number | null; completed: number | null; first_pass_rate: number | null; fix_rounds: number | null; rejected_deliveries: number | null; carried: number }[];
  retro_actions: { id: string; sprint: number; type: string; status: string; detail?: string }[];
  applied_ratio: number | null;
  prompt_changes: { id: string; agent: string; prev_version: string; new_version: string; status: string; baseline_first_pass_rate?: number | null; current_first_pass_rate?: number | null }[];
}
interface Runner { last_seen?: string | null; age_s?: number | null; fresh?: boolean; client?: { name?: string; version?: string } | null; claims?: number; lease?: unknown; interval_min?: number; waiting_for_client?: boolean }
interface Activity { summary: string[]; events: string[] }
interface McpClient { name: string; version?: string; calls?: number; first_seen?: string; last_seen?: string }

const getJson = async <T,>(path: string): Promise<T | null> => {
  try {
    const res = await fetch(api(path));
    return res.ok ? ((await res.json()) as T) : null;
  } catch {
    return null;
  }
};

const STATUS_TONE: Record<string, string> = {
  DONE: 'text-ok', IN_PROGRESS: 'text-warn', IN_REVIEW: 'text-info', BACKLOG: 'text-ink3', SELECTED_FOR_DEV: 'text-ac',
};
const pct = (v: number | null | undefined) => (v === null || v === undefined ? '—' : `%${Math.round(v * 100)}`);

const Tree: React.FC<{ nodes: PlanNode[]; depth?: number }> = ({ nodes, depth = 0 }) => {
  const { t } = useI18n();
  return (
  <ul className={depth ? 'ml-4 border-l border-line pl-3 space-y-0.5' : 'space-y-1'}>
    {nodes.map(n => (
      <li key={n.id}>
        <div className="flex flex-wrap items-center gap-2 text-xs py-0.5">
          <span className="font-mono text-[10px] text-ink3 w-14 shrink-0">{n.id}</span>
          <span className={`text-[10px] uppercase px-1 rounded border border-line ${n.kind === 'epic' ? 'text-ac' : n.kind === 'story' ? 'text-info' : 'text-ink3'}`}>{n.kind}</span>
          <span className={n.kind === 'epic' ? 'font-bold text-ink' : 'text-ink2'}>{n.title}</span>
          <span className={`font-mono text-[10px] ${STATUS_TONE[n.status] || 'text-ink3'}`}>{n.status}</span>
          {n.assignee && <span className="font-mono text-[10px] text-ink3">{n.assignee}</span>}
          {n.work_type && <span className="font-mono text-[10px] text-ink3">{n.work_type}</span>}
          {n.sprint ? <span className="font-mono text-[10px] px-1 rounded bg-acd text-ac border border-ac/30">S{n.sprint}</span> : null}
          {(n.carry_over?.count ?? 0) > 0 && <span className="text-[10px] text-warn">{t('sprint.mgmt.carriedTimes', { n: n.carry_over?.count }, 'taşındı ×{n}')}</span>}
          {n.needs_rescope && <span className="text-[10px] text-err">{t('sprint.mgmt.rescope', undefined, 'yeniden kapsam')}</span>}
        </div>
        {n.children && n.children.length > 0 && <Tree nodes={n.children} depth={depth + 1} />}
      </li>
    ))}
  </ul>
  );
};

export const ManagementCenterModal: React.FC<Props> = ({ isOpen, onClose, versions }) => {
  const { t } = useI18n();
  const [tab, setTab] = useState<Tab>('MEETINGS');
  const [meetings, setMeetings] = useState<Meeting[]>([]);
  const [adrs, setAdrs] = useState<Adr[]>([]);
  const [minutes, setMinutes] = useState<{ id: string; md: string } | null>(null);
  const [plan, setPlan] = useState<{ epics: PlanNode[]; unparented: PlanNode[] } | null>(null);
  const [learning, setLearning] = useState<Learning | null>(null);
  const [runner, setRunner] = useState<Runner | null>(null);
  const [clients, setClients] = useState<McpClient[]>([]);
  const [activity, setActivity] = useState<Activity | null>(null);
  const [msg, setMsg] = useState('');
  const [loading, setLoading] = useState(false);

  const reload = useCallback(async (which: Tab) => {
    setLoading(true);
    if (which === 'MEETINGS') {
      const [m, a] = await Promise.all([getJson<{ meetings: Meeting[] }>('/api/meetings'), getJson<{ adr: Adr[] }>('/api/adr')]);
      setMeetings((m?.meetings ?? []).slice().reverse());
      setAdrs(a?.adr ?? []);
    } else if (which === 'PLAN') {
      setPlan(await getJson('/api/plan'));
    } else if (which === 'LEARNING') {
      setLearning(await getJson('/api/learning'));
    } else {
      const [r, c, a] = await Promise.all([getJson<Runner>('/api/runner/status'), getJson<{ clients: McpClient[] }>('/api/mcp/clients'), getJson<Activity>('/api/activity?limit=12')]);
      setRunner(r);
      setClients(c?.clients ?? []);
      setActivity(a);
    }
    setLoading(false);
  }, []);

  useEffect(() => { if (isOpen) reload(tab); }, [isOpen, tab, reload, versions.plan, versions.meetings, versions.learning]);

  const openMinutes = async (id: string) => {
    const j = await getJson<{ minutes_md: string }>(`/api/meetings/${id}`);
    setMinutes({ id, md: j?.minutes_md ?? t('sprint.mgmt.minutesUnreadable', undefined, 'Tutanak okunamadı.') });
  };

  const rollback = async (id: string) => {
    if (!await confirmDialog(t('sprint.mgmt.rollbackConfirm', { id }, '{id} istem değişikliği geri alınsın mı?'))) return;
    const res = await fetch(api(`/api/learning/prompt-changes/${id}/rollback`), { method: 'POST' });
    const j = await res.json().catch(() => ({}));
    setMsg(res.ok ? t('sprint.mgmt.rolledBack', { id }, '✓ {id} geri alındı.') : j.error || t('sprint.mgmt.rollbackFailed', undefined, 'Geri alınamadı.'));
    reload('LEARNING');
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-md">
      <div className="bg-panel border border-line2 rounded-2xl w-full max-w-5xl max-h-[94vh] flex flex-col shadow-2xl overflow-hidden" data-testid="management-center">
        <div className="px-6 py-3 bg-sunk border-b border-line flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-xl bg-acd border border-ac/40 flex items-center justify-center"><ClipboardList className="w-5 h-5 text-ac" /></div>
            <div>
              <h3 className="text-base font-bold text-ink">{t('sprint.mgmt.title', undefined, 'Yönetim Merkezi')}</h3>
              <p className="text-xs text-ink3">{t('sprint.mgmt.subtitle', undefined, 'Toplantı tutanakları ve kararlar, iş planı, öğrenme döngüsü ve Claude etkinliği')}</p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <button type="button" onClick={() => reload(tab)} className="p-1.5 rounded-lg border border-line text-ink3 hover:text-ink" title={t('sprint.mgmt.refresh', undefined, 'Yenile')}><RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} /></button>
            <button type="button" onClick={onClose} className="p-1.5 rounded-lg text-ink3 hover:text-ink" aria-label={t('sprint.mgmt.close', undefined, 'Kapat')}><X className="w-5 h-5" /></button>
          </div>
        </div>
        <div className="px-6 pt-3 flex flex-wrap gap-1 border-b border-line">
          {TABS.map(tb => (
            <button key={tb.key} type="button" onClick={() => setTab(tb.key)}
              className={`px-3 py-1.5 text-xs font-medium rounded-t-lg border border-b-0 transition ${tab === tb.key ? 'bg-panel text-ac border-line' : 'bg-sunk/60 text-ink3 border-transparent hover:text-ink'}`}>{t(`sprint.mgmt.tab.${tb.key}`, undefined, tb.label)}</button>
          ))}
        </div>

        <div className="flex-1 overflow-y-auto p-6 space-y-4">
          {msg && <p className="text-[11px] text-ink2">{msg}</p>}

          {tab === 'MEETINGS' && (
            <div className="grid grid-cols-1 md:grid-cols-5 gap-4" data-testid="meetings-panel">
              <div className="md:col-span-2 space-y-4">
                <div>
                  <p className="text-[11px] font-bold text-ink uppercase tracking-wider mb-1.5">{t('sprint.mgmt.meetings', { n: meetings.length }, 'Toplantılar ({n})')}</p>
                  {meetings.length === 0 && <p className="text-xs text-ink3 border border-dashed border-line rounded-lg p-3">{t('sprint.mgmt.noMeetings', undefined, 'Henüz toplantı yok; sprint kipinde SCRUM_MASTER açar.')}</p>}
                  <div className="space-y-1">
                    {meetings.map(m => (
                      <button key={m.id} type="button" onClick={() => openMinutes(m.id)}
                        className={`w-full text-left rounded-lg border px-2.5 py-1.5 text-xs transition ${minutes?.id === m.id ? 'border-ac/60 bg-acd/30' : 'border-line bg-sunk/40 hover:border-line2'}`}>
                        <span className="font-mono font-bold text-ink">{m.id}</span> <span className="text-ink2">{m.type}</span> <span className="font-mono text-[10px] text-ink3">S{m.sprint} · {m.date}</span>
                        <p className="text-[10px] text-ink3">{t('sprint.mgmt.decisionsQuestions', { d: (m.decision_ids || []).length, q: (m.question_ids || []).length }, '{d} karar · {q} soru')}</p>
                        {m.summary && <p className="text-ink3 truncate">{m.summary}</p>}
                      </button>
                    ))}
                  </div>
                </div>
                <div>
                  <p className="text-[11px] font-bold text-ink uppercase tracking-wider mb-1.5">{t('sprint.mgmt.adrTitle', { n: adrs.length }, 'Karar kayıtları — ADR ({n})')}</p>
                  {adrs.length === 0 && <p className="text-xs text-ink3 border border-dashed border-line rounded-lg p-3">{t('sprint.mgmt.noAdr', undefined, 'Henüz ADR yok.')}</p>}
                  <div className="space-y-1">
                    {adrs.map(a => (
                      <div key={a.file} className="rounded-lg border border-line bg-sunk/40 px-2.5 py-1.5 text-xs">
                        <span className="font-mono font-bold text-ink">ADR {a.number}</span> <span className="text-ink2">{a.title}</span>
                        <p className="text-[10px] font-mono text-ink3">{a.status} · {a.file}</p>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
              <div className="md:col-span-3">
                <p className="text-[11px] font-bold text-ink uppercase tracking-wider mb-1.5">{t('sprint.mgmt.minutes', undefined, 'Tutanak')} {minutes ? `— ${minutes.id}` : ''}</p>
                <pre className="rounded-xl border border-line bg-sunk/60 p-3 text-xs text-ink2 whitespace-pre-wrap font-mono min-h-[12rem]">{minutes?.md || t('sprint.mgmt.pickMeeting', undefined, 'Soldan bir toplantı seç.')}</pre>
              </div>
            </div>
          )}

          {tab === 'PLAN' && (
            <div className="space-y-3" data-testid="plan-panel">
              {!plan && <p className="text-xs text-ink3">{t('sprint.mgmt.planLoadFailed', undefined, 'İş planı yüklenemedi (sunucu eski kodla çalışıyor olabilir).')}</p>}
              {plan && plan.epics.length === 0 && plan.unparented.length === 0 && <p className="text-xs text-ink3 border border-dashed border-line rounded-lg p-4">{t('sprint.mgmt.noEpics', undefined, 'Henüz epik/hikâye yok; şartname yüklenince PM üretir.')}</p>}
              {plan && <Tree nodes={plan.epics} />}
              {plan && plan.unparented.length > 0 && (
                <div>
                  <p className="text-[11px] font-bold text-warn uppercase tracking-wider mb-1">{t('sprint.mgmt.unparented', { n: plan.unparented.length }, 'Üst maddesiz ({n})')}</p>
                  <Tree nodes={plan.unparented} />
                </div>
              )}
            </div>
          )}

          {tab === 'LEARNING' && learning && (
            <div className="space-y-5" data-testid="learning-panel">
              <div>
                <p className="text-[11px] font-bold text-ink uppercase tracking-wider mb-1.5">{t('sprint.mgmt.trend', undefined, 'Sprint eğilimi')}</p>
                <div className="rounded-xl border border-line overflow-hidden">
                  <table className="w-full text-xs">
                    <thead className="bg-sunk text-ink3 text-[10px] uppercase tracking-wider"><tr><th className="text-left px-2 py-1.5">Sprint</th><th className="text-left px-2">{t('sprint.mgmt.colStatus', undefined, 'Durum')}</th><th className="text-left px-2">{t('sprint.mgmt.colCommitDone', undefined, 'Taahhüt / biten')}</th><th className="text-left px-2">{t('sprint.mgmt.colFirstPass', undefined, 'İlk seferde geçme')}</th><th className="text-left px-2">{t('sprint.mgmt.colFix', undefined, 'Düzeltme')}</th><th className="text-left px-2">{t('sprint.mgmt.colRejected', undefined, 'Reddedilen')}</th><th className="text-left px-2">{t('sprint.mgmt.colCarried', undefined, 'Taşınan')}</th></tr></thead>
                    <tbody>
                      {learning.trend.length === 0 && <tr><td colSpan={7} className="px-3 py-5 text-center text-ink3">{t('sprint.mgmt.noClosedSprint', undefined, 'Kapanmış sprint yok.')}</td></tr>}
                      {learning.trend.map(tr => (
                        <tr key={tr.sprint} className="border-t border-line"><td className="px-2 py-1.5 font-mono font-bold">S{tr.sprint}</td><td className="px-2 font-mono text-ink3">{tr.status}</td><td className="px-2 font-mono">{tr.committed ?? '—'} / {tr.completed ?? '—'}</td>
                          <td className="px-2 font-mono">{pct(tr.first_pass_rate)}</td><td className="px-2 font-mono">{tr.fix_rounds ?? '—'}</td><td className="px-2 font-mono">{tr.rejected_deliveries ?? '—'}</td><td className="px-2 font-mono">{tr.carried}</td></tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div>
                  <p className="text-[11px] font-bold text-ink uppercase tracking-wider mb-1.5">{t('sprint.mgmt.retroActions', { pct: pct(learning.applied_ratio) }, 'Retro aksiyonları · uygulanma {pct}')}</p>
                  <div className="space-y-1">
                    {learning.retro_actions.length === 0 && <p className="text-xs text-ink3">{t('sprint.mgmt.noActions', undefined, 'Aksiyon yok.')}</p>}
                    {learning.retro_actions.map(a => (
                      <div key={a.id} className="rounded-lg border border-line bg-sunk/40 px-2.5 py-1.5 text-xs">
                        <span className="font-mono font-bold">{a.id}</span> <span className="text-ink3 font-mono text-[10px]">S{a.sprint} · {a.type}</span> <span className={`font-mono text-[10px] ${a.status === 'APPLIED' ? 'text-ok' : 'text-warn'}`}>{a.status}</span>
                        {a.detail && <p className="text-ink3">{a.detail}</p>}
                      </div>
                    ))}
                  </div>
                </div>
                <div>
                  <p className="text-[11px] font-bold text-ink uppercase tracking-wider mb-1.5">{t('sprint.mgmt.promptChanges', undefined, 'İstem değişiklikleri')}</p>
                  <div className="space-y-1">
                    {learning.prompt_changes.length === 0 && <p className="text-xs text-ink3">{t('sprint.mgmt.noPromptChanges', undefined, 'İzlenen istem değişikliği yok.')}</p>}
                    {learning.prompt_changes.map(c => (
                      <div key={c.id} className="rounded-lg border border-line bg-sunk/40 px-2.5 py-1.5 text-xs flex items-center justify-between gap-2">
                        <div><span className="font-mono font-bold">{c.id}</span> <span className="text-ink2">{c.agent}</span> <span className="font-mono text-[10px] text-ink3">{c.prev_version} → {c.new_version}</span>
                          <p className="text-[10px] text-ink3">{t('sprint.mgmt.baselineNow', { base: pct(c.baseline_first_pass_rate), now: pct(c.current_first_pass_rate) }, 'taban {base} · şimdi {now}')} · <span className="font-mono">{c.status}</span></p></div>
                        {c.status !== 'ROLLED_BACK' && <button type="button" onClick={() => rollback(c.id)} className="px-2 py-1 rounded border border-warn/40 text-warn text-[11px] hover:opacity-90">{t('sprint.mgmt.rollback', undefined, 'Geri al')}</button>}
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            </div>
          )}
          {tab === 'LEARNING' && !learning && <p className="text-xs text-ink3">{t('sprint.mgmt.learningFailed', undefined, 'Öğrenme raporu yüklenemedi.')}</p>}

          {tab === 'ACTIVITY' && (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4" data-testid="activity-panel">
              <div className="space-y-3">
                <div className="rounded-xl border border-line p-3 text-xs space-y-1">
                  <p className="text-[11px] font-bold text-ink uppercase tracking-wider">Runner</p>
                  {runner ? (
                    <>
                      <p className={runner.fresh ? 'text-ok' : 'text-warn'}>{runner.fresh ? t('sprint.mgmt.claudeConnected', undefined, 'Claude bağlı') : runner.waiting_for_client ? t('sprint.mgmt.claudeWaiting', undefined, 'Claude bekleniyor') : t('sprint.mgmt.claudeAway', undefined, 'Claude uzun süredir görünmedi')}</p>
                      <p className="text-ink3">{t('sprint.mgmt.lastSeen', undefined, 'Son görülme:')} {runner.last_seen ? new Date(runner.last_seen).toLocaleString('tr-TR') : '—'}{runner.age_s !== null && runner.age_s !== undefined ? t('sprint.mgmt.minAgo', { n: Math.round(runner.age_s / 60) }, ' ({n} dk önce)') : ''}</p>
                      <p className="text-ink3">{t('sprint.mgmt.clientInfo', { name: runner.client?.name || '—', version: runner.client?.version || '', interval: runner.interval_min ?? '—', lease: runner.lease ? t('sprint.mgmt.yes', undefined, 'var') : t('sprint.mgmt.no', undefined, 'yok') }, 'İstemci: {name} {version} · çağrı aralığı {interval} dk · kira: {lease}')}</p>
                    </>
                  ) : <p className="text-ink3">{t('sprint.mgmt.runnerFailed', undefined, 'Runner durumu okunamadı.')}</p>}
                </div>
                <div className="rounded-xl border border-line p-3 text-xs space-y-1">
                  <p className="text-[11px] font-bold text-ink uppercase tracking-wider">{t('sprint.mgmt.mcpClients', { n: clients.length }, 'MCP istemcileri ({n})')}</p>
                  {clients.length === 0 && <p className="text-ink3">{t('sprint.mgmt.noClients', undefined, 'Bağlı istemci yok.')}</p>}
                  {clients.map(c => (
                    <p key={`${c.name}-${c.first_seen}`} className="text-ink2"><span className="font-mono font-bold">{c.name}</span> <span className="text-ink3 font-mono">{c.version}</span> · {t('sprint.mgmt.callsLast', { calls: c.calls ?? 0, last: c.last_seen ? new Date(c.last_seen).toLocaleTimeString('tr-TR') : '—' }, '{calls} çağrı · son {last}')}</p>
                  ))}
                </div>
              </div>
              <div className="rounded-xl border border-line p-3 text-xs space-y-2">
                <p className="text-[11px] font-bold text-ink uppercase tracking-wider">{t('sprint.mgmt.summary', undefined, 'Özet')}</p>
                {(activity?.summary || []).map((s, i) => <p key={i} className="text-ink2">{s}</p>)}
                <p className="text-[11px] font-bold text-ink uppercase tracking-wider pt-1">{t('sprint.mgmt.recentEvents', undefined, 'Son olaylar')}</p>
                {(activity?.events || []).map((e, i) => <p key={i} className="font-mono text-[10px] text-ink3 break-words">{e}</p>)}
                {!activity && <p className="text-ink3">{t('sprint.mgmt.activityFailed', undefined, 'Etkinlik okunamadı.')}</p>}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
