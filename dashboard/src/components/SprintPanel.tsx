import React, { useEffect, useState } from 'react';
import { confirmDialog } from '../lib/dialog';
import { JiraApi, SprintBoard } from '../types/telemetry';
import { BudgetSettings } from './BudgetSettings';
import { useI18n } from '../i18n';

/**
 * G5 sprint panosu: mevcut sprint (hedef düzenleme yalnızca PLANNING), taahhüt önerisi + onay/geri sayım, kapasite, engel çözme,
 * iptal, sonraki sprint, taşınanlar, burndown (iş sayısı), velocity, WIP uyarısı. Veri: GET /api/sprints/board.
 */
interface Props {
  jira: JiraApi;
  version: number;
  issuesVersion: number;
  onOpenIssue?: (id: string) => void;
}

const STATUS_CHIP: Record<string, string> = {
  PLANNING: 'bg-sunk text-ink2 border-line', COMMITTED: 'bg-infod text-info border-info/40', IN_PROGRESS: 'bg-warnd text-warn border-warn/40',
  IN_REVIEW: 'bg-acd text-ac border-ac/40', BLOCKED: 'bg-errd text-err border-err/40', CLOSED: 'bg-okd text-ok border-ok/40', CANCELLED: 'bg-sunk text-ink3 border-line',
};
const ISSUE_CHIP: Record<string, string> = {
  BACKLOG: 'bg-sunk text-ink3 border-line', SELECTED_FOR_DEV: 'bg-infod text-info border-info/40', IN_PROGRESS: 'bg-warnd text-warn border-warn/40',
  IN_REVIEW: 'bg-acd text-ac border-ac/40', DONE: 'bg-okd text-ok border-ok/40',
};
const fmt = (ts?: string | null) => {
  if (!ts) return '';
  const d = new Date(ts);
  return Number.isNaN(d.getTime()) ? ts : d.toLocaleString('tr-TR');
};
const hms = (s: number) => `${Math.floor(s / 3600)}:${String(Math.floor((s % 3600) / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`;

const Burndown: React.FC<{ points: { ts: string; remaining: number }[] }> = ({ points }) => {
  const { t } = useI18n();
  const W = 260;
  const H = 70;
  const max = Math.max(1, ...points.map(p => p.remaining));
  const n = Math.max(1, points.length - 1);
  const xy = points.map((p, i) => [8 + (i / n) * (W - 16), 6 + (1 - p.remaining / max) * (H - 16)] as const);
  const path = xy.map(([x, y], i) => `${i ? 'L' : 'M'}${x.toFixed(1)},${y.toFixed(1)}`).join(' ');
  return (
    <svg width={W} height={H} className="block">
      <line x1={8} y1={6} x2={W - 8} y2={H - 10} stroke="var(--line)" strokeDasharray="3 3" />
      <path d={path} fill="none" stroke="var(--ac)" strokeWidth={2} />
      {xy.map(([x, y], i) => <circle key={i} cx={x} cy={y} r={2.5} fill="var(--ac)" />)}
      <text x={8} y={H - 1} fontSize={8} fill="var(--ink3)">{t('sprint.panel.nIssues', { n: max }, '{n} iş')}</text>
      <text x={W - 8} y={H - 1} fontSize={8} fill="var(--ink3)" textAnchor="end">{t('sprint.panel.remaining', { n: points[points.length - 1]?.remaining ?? 0 }, 'kalan {n}')}</text>
    </svg>
  );
};

export const SprintPanel: React.FC<Props> = ({ jira, version, issuesVersion, onOpenIssue }) => {
  const { t } = useI18n();
  const [board, setBoard] = useState<SprintBoard | null>(null);
  const [err, setErr] = useState('');
  const [busy, setBusy] = useState(false);
  const [showBudget, setShowBudget] = useState(false);
  const [goal, setGoal] = useState('');
  const [editingGoal, setEditingGoal] = useState(false);
  const [now, setNow] = useState(Date.now());
  const load = async () => {
    try {
      const b = await jira.sprintBoard();
      setBoard(b);
      setErr('');
    } catch (e) {
      setErr((e as Error).message);
    }
  };
  useEffect(() => {
    load();
    const iv = setInterval(load, 20000);
    return () => clearInterval(iv);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [version, issuesVersion]);
  useEffect(() => {
    const iv = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(iv);
  }, []);
  const act = async (fn: () => Promise<unknown>) => {
    setBusy(true);
    try {
      await fn();
      await load();
      setErr('');
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  if (!board) return <div className="rounded-xl border border-line bg-panel p-3 text-xs text-ink3">{err || t('sprint.panel.loading', undefined, 'Sprint panosu yükleniyor…')}</div>;
  if (!board.enabled) return <div className="rounded-xl border border-line bg-panel p-3 text-xs text-ink3">{t('sprint.panel.disabled', undefined, 'Sprint kipi kapalı (ayar: sprint.enabled); sabit 1-10 akışı çalışır.')}</div>;
  const cur = board.current;
  const pc = board.pending_commit;
  const countdown = pc?.deadline ? Math.max(0, Math.round((new Date(pc.deadline).getTime() - now) / 1000)) : null;
  const btn = 'px-2.5 py-1 rounded-md border text-[11px] font-semibold transition disabled:opacity-50';

  return (
    <div className="rounded-xl border border-line bg-panel p-4 space-y-3">
      <div className="flex items-center justify-between gap-2 flex-wrap">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-[10px] font-mono font-bold uppercase tracking-wider text-ink3">{t('sprint.panel.title', undefined, 'Sprint panosu')}</span>
          {cur ? (
            <>
              <span className="text-sm font-bold text-ink">{t('sprint.panel.sprintN', { n: cur.sprint_number }, 'Sprint {n}')}</span>
              <span className={`text-[10px] font-mono px-1.5 py-0.5 rounded border ${STATUS_CHIP[cur.status] || STATUS_CHIP.PLANNING}`}>{cur.status}</span>
              {cur.git_tag && <span className="text-[10px] font-mono text-ink3">⎇ {cur.git_tag}</span>}
            </>
          ) : <span className="text-xs text-ink3">{t('sprint.panel.noSprint', undefined, 'Henüz sprint yok (şartname yükleyince planlama başlar)')}{board.project_status ? t('sprint.panel.projectStatus', { s: board.project_status }, ' · proje {s}') : ''}</span>}
        </div>
        <div className="flex items-center gap-1.5">
          {cur?.can.cancel && <button disabled={busy} onClick={async () => { if (await confirmDialog(t('sprint.panel.cancelConfirm', { n: cur.sprint_number }, "Sprint {n} iptal edilsin mi? Başlamamış işler backlog'a döner."))) act(() => jira.sprintCancel(cur.sprint_number)); }} className={`${btn} border-err/40 text-err bg-errd/40`}>{t('sprint.panel.cancel', undefined, 'İptal')}</button>}
          {board.can_plan_next && <button disabled={busy} onClick={() => act(() => jira.planNext())} className={`${btn} border-ac/40 text-ac bg-acd/40`} title={t('sprint.panel.planNextTip', undefined, 'auto_chain kapalıyken sıradaki sprinti planla')}>{t('sprint.panel.planNext', undefined, 'Sonraki sprinti planla')}</button>}
          <a href="/api/reports/pi.html" target="_blank" rel="noreferrer" className={`${btn} border-line text-ink2 whitespace-nowrap`} title={t('sprint.panel.piTip', undefined, 'PI planlama raporları: burndown, velocity, CFD, epik ilerlemesi, kalite, tahmin (yazdır / PDF)')}>📊 {t('sprint.panel.piReports', undefined, 'PI raporları')}</a>
          <button onClick={load} className="text-[10px] font-mono text-ink3 hover:text-ink">{t('sprint.panel.refresh', undefined, 'yenile')}</button>
        </div>
      </div>
      {err && <div className="text-[11px] text-err">{err}</div>}

      {cur && (
        <div className="flex items-start gap-2 text-xs">
          <span className="text-ink3 shrink-0">{t('sprint.panel.goal', undefined, 'Hedef:')}</span>
          {editingGoal ? (
            <span className="flex-1 flex gap-1.5">
              <input value={goal} onChange={e => setGoal(e.target.value)} className="flex-1 bg-sunk border border-line rounded px-2 py-0.5 text-xs text-ink" />
              <button disabled={busy} onClick={() => act(async () => { await jira.sprintGoal(cur.sprint_number, goal); setEditingGoal(false); })} className={`${btn} border-ok/40 text-ok bg-okd/40`}>{t('sprint.panel.save', undefined, 'Kaydet')}</button>
              <button onClick={() => setEditingGoal(false)} className={`${btn} border-line text-ink3`}>{t('sprint.panel.discard', undefined, 'Vazgeç')}</button>
            </span>
          ) : (
            <span className="flex-1 text-ink">{cur.goal || '—'}{cur.can.edit_goal && <button onClick={() => { setGoal(cur.goal || ''); setEditingGoal(true); }} className="ml-2 text-ac hover:underline text-[11px]">✎ {t('sprint.panel.edit', undefined, 'düzenle')}</button>}</span>
          )}
        </div>
      )}

      <div className="flex items-center gap-3 flex-wrap text-[11px] text-ink3">
        <span title={board.capacity_reason}>{t('sprint.panel.capacity', undefined, 'Kapasite')} <span className="font-mono text-ink">{board.capacity}</span> {t('sprint.panel.issueUnit', undefined, 'iş')}</span>
        {cur && <span>{t('sprint.panel.commitment', undefined, 'Taahhüt')} <span className="font-mono text-ink">{cur.done}/{cur.committed}</span> {t('sprint.panel.doneWord', undefined, 'bitti')}{cur.carried ? t('sprint.panel.carriedN', { n: cur.carried }, ' · {n} taşındı') : ''}{cur.scope_changes ? t('sprint.panel.scopeChangesN', { n: cur.scope_changes }, ' · {n} kapsam değişikliği') : ''}</span>}
        <span className={board.wip.over ? 'text-err font-semibold' : ''} title={board.wip.limit ? t('sprint.panel.wipLimit', { n: board.wip.limit }, 'WIP sınırı {n}') : t('sprint.panel.wipOff', undefined, 'WIP sınırı kapalı (sprint.wip_limit)')}>
          WIP <span className="font-mono">{board.wip.count}{board.wip.limit ? `/${board.wip.limit}` : ''}</span>{board.wip.over ? t('sprint.panel.wipOver', undefined, ' · sınır aşıldı!') : ''}
        </span>
        {cur?.commit_approval?.by && <span>{t('sprint.panel.commitBy', { by: cur.commit_approval.by }, 'taahhüt: {by}')}</span>}
      </div>

      {pc && (
        <div className="rounded-lg border border-warn/50 bg-warnd/40 p-3 space-y-1.5">
          <div className="flex items-center justify-between gap-2 flex-wrap">
            <span className="text-xs font-semibold text-ink">{t('sprint.panel.proposal', { sprint: pc.sprint, n: pc.proposed.length }, 'Taahhüt önerisi — Sprint {sprint}: {n} iş')}</span>
            <span className="flex items-center gap-2">
              {countdown !== null && <span className="text-[11px] font-mono text-warn" title={t('sprint.panel.deadlineTip', { d: fmt(pc.deadline) }, 'Süre dolunca sunucu taahhüt eder ({d})')}>⏱ {hms(countdown)}</span>}
              <button disabled={busy} onClick={() => act(() => jira.sprintCommit(pc.sprint))} className={`${btn} border-ok/40 text-ok bg-okd/60`}>{t('sprint.panel.commit', undefined, 'Taahhüt et')}</button>
            </span>
          </div>
          <ul className="text-[11px] text-ink space-y-0.5">
            {pc.proposed.map(p => <li key={p.issue_id}><button onClick={() => onOpenIssue?.(p.issue_id)} className="font-mono text-ac hover:underline">{p.issue_id}</button> {p.title || ''}</li>)}
          </ul>
          {pc.summary && <div className="text-[10px] text-ink3">{pc.summary}</div>}
        </div>
      )}

      {cur?.blocked && (
        <div className="rounded-lg border border-err/50 bg-errd/40 p-3 flex items-center justify-between gap-2 flex-wrap text-xs">
          <span className="text-err"><span className="font-semibold">{t('sprint.panel.blocker', undefined, 'Engel:')}</span> {cur.blocked.reason}{cur.blocked.detail ? ` · ${cur.blocked.detail}` : ''}{cur.blocked.since ? ` · ${fmt(cur.blocked.since)}` : ''}</span>
          <span className="flex items-center gap-1.5">
            {['BUDGET_EXCEEDED', 'STALLED'].includes(cur.blocked.reason) && <button onClick={() => setShowBudget(v => !v)} className={`${btn} border-warn/40 text-warn bg-warnd/40`} title={t('sprint.panel.budgetTip', undefined, 'Süre / token / adım sınırlarını düzenle')}>{showBudget ? t('sprint.panel.hideLimits', undefined, 'Sınırları gizle') : t('sprint.panel.editBudget', undefined, '⚙ Bütçe sınırlarını düzenle')}</button>}
            {cur.can.unblock && <button disabled={busy} onClick={() => act(() => jira.sprintUnblock(cur.sprint_number))} className={`${btn} border-ok/40 text-ok bg-okd/40`} title={t('sprint.panel.unblockTip', undefined, 'Sınırı artırdıysan ya da engel nedeni çözüldüyse sprinti sürdür')}>{t('sprint.panel.unblock', undefined, 'Engeli kaldır ve sürdür')}</button>}
          </span>
          {showBudget && <div className="basis-full rounded-lg border border-line bg-panel p-3"><BudgetSettings compact /></div>}
        </div>
      )}

      {cur && (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          <div className="md:col-span-2 space-y-1">
            <div className="text-[10px] font-mono uppercase tracking-wider text-ink3">{t('sprint.panel.committedItems', undefined, 'Taahhüt edilen işler')}</div>
            {cur.items.length === 0 && <div className="text-[11px] text-ink3">{t('sprint.panel.noCommitment', undefined, 'Taahhüt yok (planlama sürüyor).')}</div>}
            {cur.items.map(i => (
              <div key={i.id} className="flex items-center gap-2 text-[11px]">
                <span className={`px-1.5 py-0.5 rounded border font-mono text-[10px] ${ISSUE_CHIP[i.status] || ISSUE_CHIP.BACKLOG}`}>{i.status}</span>
                <button onClick={() => onOpenIssue?.(i.id)} className="font-mono text-ac hover:underline">{i.key}</button>
                <span className="text-ink truncate">{i.title}</span>
                <span className="text-ink3 font-mono ml-auto shrink-0">{i.assignee}{i.carry_over?.count ? ` · ×${i.carry_over.count}` : ''}</span>
              </div>
            ))}
            {cur.carried_items.length > 0 && (
              <div className="text-[10px] text-ink3 pt-1">{t('sprint.panel.carriedLabel', undefined, 'Taşınan:')} {cur.carried_items.map(c => `${c.key || c.id} (${c.reason || '?'})`).join(', ')}</div>
            )}
          </div>
          <div className="space-y-2">
            <div className="text-[10px] font-mono uppercase tracking-wider text-ink3">{t('sprint.panel.burndown', undefined, 'Burndown (iş)')}</div>
            <Burndown points={cur.burndown} />
            {board.velocity.length > 0 && (
              <div className="text-[10px] text-ink3">
                <div className="font-mono uppercase tracking-wider mb-0.5">Velocity</div>
                <div className="flex items-end gap-1 h-10">
                  {board.velocity.slice(-8).map(v => (
                    <div key={v.sprint} className="flex flex-col items-center gap-0.5" title={`Sprint ${v.sprint}: ${v.done}/${v.committed}`}>
                      <div className="w-5 bg-ok/70 rounded-sm" style={{ height: `${Math.max(4, (v.done / Math.max(1, ...board.velocity.map(x => x.committed))) * 32)}px` }} />
                      <span className="font-mono">S{v.sprint}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
};
