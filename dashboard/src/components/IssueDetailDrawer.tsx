import React, { useEffect, useState } from 'react';
import { promptDialog } from '../lib/dialog';
import { X, Trash2, RotateCcw, MessageSquare, Link2, Paperclip, History, ShieldCheck, Save, FileText } from 'lucide-react';
import { openFile, openCommit } from '../lib/viewer';
import { useI18n } from '../i18n';
import {
  IssueEvidence, IssueTimeline, JiraApi, JiraAttachment, JiraIssue, JiraIssueStatus, JiraIssueType, JiraLinkType,
} from '../types/telemetry';

/**
 * G5 Jira+ madde detayı: alanlar (tip, durum, öncelik, sorumlu, tahmin, son tarih, sprint, etiket, bileşen, ebeveyn, izleyici),
 * yorumlar, bağlar, ekler, geçmiş ("neden bu durumda") ve kanıt (koşu/adım/commit/doğrulama/DoD/AC kapsama). Sunucu olayları
 * (JIRA_UPDATED) `issue` prop'unu tazeler; taslak alanlar (başlık/açıklama/kriter) Kaydet ile gönderilir.
 */
const TYPES: JiraIssueType[] = ['EPIC', 'STORY', 'FEATURE', 'TASK', 'BUG', 'IMPROVEMENT', 'REFACTOR', 'TEST_CASE', 'TEST_RUN', 'SPIKE'];
const STATUSES: JiraIssueStatus[] = ['BACKLOG', 'SELECTED_FOR_DEV', 'IN_PROGRESS', 'IN_REVIEW', 'DONE'];
const LINK_TYPES: JiraLinkType[] = ['blocks', 'is_blocked_by', 'relates', 'duplicates', 'tests', 'tested_by'];
const LINK_LABEL: Record<JiraLinkType, string> = {
  blocks: 'engelliyor', is_blocked_by: 'engelleniyor', relates: 'ilgili', duplicates: 'kopyası', tests: 'test ediyor', tested_by: 'test ediliyor',
};
const ESTIMATES = ['', 'XS', 'S', 'M', 'L', 'XL'];
export type Tab = 'detail' | 'comments' | 'links' | 'attachments' | 'history' | 'evidence' | 'work';

interface Props {
  issue: JiraIssue | null;
  issues: JiraIssue[];
  jira: JiraApi;
  sprints: { sprint_number: number; status: string }[];
  attachmentSources?: { name: string; path?: string; url?: string }[];
  onClose: () => void;
  onOpenIssue?: (id: string) => void;
  onInspectTask?: (order: number, issue: JiraIssue) => void;
  initialTab?: Tab;
}

const fmtWith = (lang: string, ts?: string | null) => {
  if (!ts) return '';
  const d = new Date(ts);
  return Number.isNaN(d.getTime()) ? ts : d.toLocaleString(lang);
};
const attName = (a: string | JiraAttachment) => (typeof a === 'string' ? a.split('/').pop() || a : a.name);
const attRef = (a: string | JiraAttachment) => (typeof a === 'string' ? a : a.url || a.path || '');
const attId = (a: string | JiraAttachment) => (typeof a === 'string' ? a : a.id);

const Chip: React.FC<{ text: string; onRemove?: () => void; tone?: string }> = ({ text, onRemove, tone = 'bg-sunk text-ink2 border-line' }) => {
  const { t } = useI18n();
  return (
  <span className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded border text-[10px] font-mono ${tone}`}>
    {text}
    {onRemove && <button type="button" onClick={onRemove} className="text-ink3 hover:text-err" title={t('board.issue.remove', undefined, 'Kaldır')}>×</button>}
  </span>
  );
};

export const IssueDetailDrawer: React.FC<Props> = ({ issue, issues, jira, sprints, attachmentSources = [], onClose, onOpenIssue, onInspectTask, initialTab }) => {
  const { t, lang } = useI18n();
  const fmt = (ts?: string | null) => fmtWith(lang, ts);
  const linkLabel = (k: JiraLinkType) => t(`board.issue.link.${k}`, undefined, LINK_LABEL[k] || k);
  const [tab, setTab] = useState<Tab>(initialTab || 'detail');
  const [err, setErr] = useState('');
  const [busy, setBusy] = useState(false);
  const [title, setTitle] = useState('');
  const [desc, setDesc] = useState('');
  const [criteria, setCriteria] = useState('');
  const [labelInput, setLabelInput] = useState('');
  const [compInput, setCompInput] = useState('');
  const [watcherInput, setWatcherInput] = useState('');
  const [comment, setComment] = useState('');
  const [linkType, setLinkType] = useState<JiraLinkType>('relates');
  const [linkTarget, setLinkTarget] = useState('');
  const [attNameInput, setAttNameInput] = useState('');
  const [attRefInput, setAttRefInput] = useState('');
  const [timeline, setTimeline] = useState<IssueTimeline | null>(null);
  const [evidence, setEvidence] = useState<IssueEvidence | null>(null);

  const issueId = issue?.id;
  const updatedAt = issue?.updated_at;
  useEffect(() => {
    if (issue) {
      setTitle(issue.title);
      setDesc(issue.description || '');
      setCriteria((issue.acceptance_criteria || []).join('\n'));
      setErr('');
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [issueId]);
  useEffect(() => {
    if (!issueId) return;
    if (tab === 'history') jira.timeline(issueId).then(setTimeline).catch(e => setErr((e as Error).message));
    if (tab === 'evidence' || tab === 'work') jira.evidence(issueId).then(setEvidence).catch(e => setErr((e as Error).message));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab, issueId, updatedAt]);

  const run = async (fn: () => Promise<unknown>) => {
    setBusy(true);
    setErr('');
    try {
      await fn();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  if (!issue) return null;
  const deleted = !!issue.deleted;
  const canPlan = issue.status === 'BACKLOG' && !issue.sprint;
  const labels = issue.labels || [];
  const components = issue.components || [];
  const watchers = issue.watchers || [];
  const links = issue.links || [];
  const comments = issue.comments || [];
  const attachments = issue.attachments || [];
  const byId = (id: string) => issues.find(i => i.id === id);
  const edit = (patch: Record<string, unknown>) => run(() => jira.edit(issue.id, patch));
  const assignees = Array.from(new Set(issues.map(i => i.assignee).concat(['PM', 'ARCHITECT', 'BACKEND_DEV', 'FRONTEND_DEV', 'DESIGNER', 'QA', 'E2E_TESTER', 'DEVOPS', 'DOCUMENTOR'])));
  const parents = issues.filter(i => i.id !== issue.id && (i.issue_type === 'EPIC' || i.issue_type === 'STORY' || i.issue_type === 'FEATURE'));
  const tabs: { id: Tab; label: string; icon: React.ReactNode; n?: number }[] = [
    { id: 'detail', label: t('board.issue.tabDetail', undefined, 'Detay'), icon: <FileText className="w-3 h-3" /> },
    { id: 'comments', label: t('board.issue.tabComments', undefined, 'Yorumlar'), icon: <MessageSquare className="w-3 h-3" />, n: comments.length },
    { id: 'links', label: t('board.issue.tabLinks', undefined, 'Bağlar'), icon: <Link2 className="w-3 h-3" />, n: links.length },
    { id: 'attachments', label: t('board.issue.tabAttachments', undefined, 'Ekler'), icon: <Paperclip className="w-3 h-3" />, n: attachments.length },
    { id: 'history', label: t('board.issue.tabHistory', undefined, 'Geçmiş'), icon: <History className="w-3 h-3" />, n: (issue.audit_trail?.length || 0) + (issue.history?.length || 0) },
    { id: 'work', label: t('board.issue.tabWork', undefined, 'İşlemler'), icon: <FileText className="w-3 h-3" />, n: evidence?.steps.reduce((a, st) => a + (st.artifacts?.length || 0), 0) },
    { id: 'evidence', label: t('board.issue.tabEvidence', undefined, 'Kanıt'), icon: <ShieldCheck className="w-3 h-3" /> },
  ];
  const field = 'bg-sunk border border-line rounded px-1.5 py-0.5 text-[11px] text-ink disabled:opacity-50';
  const sel = (s?: string) => `${field} ${s || ''}`;

  return (
    <div className="fixed inset-0 z-50 flex" onClick={onClose}>
      <div className="flex-1 bg-black/40" />
      <div className="w-[580px] max-w-full h-full bg-panel border-l border-line shadow-2xl flex flex-col" onClick={e => e.stopPropagation()}>
        {/* Başlık */}
        <div className="px-4 py-3 border-b border-line bg-panel2 flex items-start gap-3 shrink-0">
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2 text-[10px] font-mono text-ink3 flex-wrap">
              <span className="font-bold text-ac">{issue.key}</span>
              <span>#{issue.order}</span>
              <select value={issue.issue_type} disabled={busy || deleted} onChange={e => edit({ issue_type: e.target.value })} className={sel()} title={t('board.issue.typeTitle', undefined, 'Madde tipi')}>
                {TYPES.map(ty => <option key={ty} value={ty}>{ty}</option>)}
              </select>
              {issue.work_type && <span className="px-1.5 py-0.5 rounded border border-line bg-sunk">{issue.work_type}</span>}
              {issue.sprint ? <span className="px-1.5 py-0.5 rounded border border-info/40 bg-infod text-info">S{issue.sprint}</span>
                : issue.planned_sprint ? <span className="px-1.5 py-0.5 rounded border border-warn/40 bg-warnd text-warn">→ S{issue.planned_sprint}</span> : null}
              {deleted && <span className="px-1.5 py-0.5 rounded bg-errd text-err border border-err/40">{t('board.issue.deleted', { reason: issue.deleted?.reason || t('board.issue.noReason', undefined, 'neden yok') }, `SİLİNDİ · ${issue.deleted?.reason || 'neden yok'}`)}</span>}
            </div>
            <input
              value={title}
              disabled={deleted || busy}
              onChange={e => setTitle(e.target.value)}
              onBlur={() => { if (title.trim() && title !== issue.title) edit({ title }); }}
              className="mt-1 w-full bg-transparent text-sm font-bold text-ink border-b border-transparent focus:border-ac outline-none"
              title={t('board.issue.titleHint', undefined, 'Başlık (odak çıkınca kaydedilir)')}
            />
          </div>
          <button onClick={onClose} className="text-ink3 hover:text-ink shrink-0"><X className="w-4 h-4" /></button>
        </div>

        {/* Hızlı alanlar */}
        <div className="px-4 py-2 border-b border-line grid grid-cols-3 gap-2 text-[10px] text-ink3 shrink-0">
          <label>{t('board.issue.status', undefined, 'Durum')}
            <select value={issue.status} disabled={busy || deleted} onChange={e => run(() => jira.move(issue.id, e.target.value as JiraIssueStatus))} className={sel('w-full mt-0.5')} title={t('board.issue.moveTitle', undefined, 'Yönetici taşıması (DONE: DoD kanıtı olmadan, yönetici sorumluluğunda)')}>
              {STATUSES.map(s => <option key={s} value={s}>{s}</option>)}
            </select>
          </label>
          <label>{t('board.issue.priority', undefined, 'Öncelik')}
            <select value={issue.priority} disabled={busy || deleted} onChange={e => edit({ priority: e.target.value })} className={sel('w-full mt-0.5')}>
              {['P0', 'P1', 'P2'].map(p => <option key={p} value={p}>{p}</option>)}
            </select>
          </label>
          <label>{t('board.issue.assignee', undefined, 'Sorumlu')}
            <input list="jira-plus-assignees" defaultValue={issue.assignee} key={`${issue.id}-${issue.assignee}`} disabled={busy || deleted}
              onBlur={e => { const v = e.target.value.trim().toUpperCase(); if (v && v !== issue.assignee) edit({ assignee: v }); }} className={sel('w-full mt-0.5')} />
            <datalist id="jira-plus-assignees">{assignees.map(a => <option key={a} value={a} />)}</datalist>
          </label>
          <label>{t('board.issue.estimate', undefined, 'Tahmin')}
            <select value={issue.estimate ?? ''} disabled={busy || deleted} onChange={e => edit({ estimate: e.target.value || null })} className={sel('w-full mt-0.5')}>
              {ESTIMATES.map(x => <option key={x} value={x}>{x || '—'}</option>)}
              {typeof issue.estimate === 'number' && <option value={issue.estimate}>{t('board.issue.points', { n: issue.estimate }, `${issue.estimate} puan`)}</option>}
            </select>
          </label>
          <label>{t('board.issue.due', undefined, 'Son tarih')}
            <input type="date" value={issue.due || ''} disabled={busy || deleted} onChange={e => edit({ due: e.target.value || null })} className={sel('w-full mt-0.5')} />
          </label>
          <label title={canPlan ? t('board.issue.planTitle', undefined, 'Backlog işini bir sprinte sabitle') : t('board.issue.planLockedTitle', undefined, 'Sprinte alınmış ya da başlamış işin sprinti değişmez')}>Sprint
            <select value={issue.planned_sprint ?? ''} disabled={busy || deleted || !canPlan}
              onChange={e => run(() => jira.plan(issue.id, { planned_sprint: e.target.value ? Number(e.target.value) : null }))} className={sel('w-full mt-0.5')}>
              <option value="">{t('board.issue.backlog', undefined, 'Backlog')}</option>
              {Array.from({ length: Math.max(3, ...sprints.map(x => x.sprint_number + 1)) }, (_, k) => k + 1)
                .filter(n => !['CLOSED', 'IN_PROGRESS', 'IN_REVIEW', 'COMMITTED'].includes(sprints.find(x => x.sprint_number === n)?.status || ''))
                .map(n => <option key={n} value={n}>Sprint {n}</option>)}
            </select>
          </label>
        </div>

        {/* Etiket, bileşen, ebeveyn, izleyici */}
        <div className="px-4 py-2 border-b border-line space-y-1.5 text-[10px] text-ink3 shrink-0">
          <div className="flex items-center gap-1.5 flex-wrap">
            <span className="w-14">{t('board.issue.labels', undefined, 'Etiket')}</span>
            {labels.map(l => <Chip key={l} text={l} tone="bg-acd text-ac border-ac/40" onRemove={deleted ? undefined : () => edit({ labels: labels.filter(x => x !== l) })} />)}
            <input value={labelInput} disabled={deleted} onChange={e => setLabelInput(e.target.value)} placeholder={t('board.issue.addLabel', undefined, '+ etiket')} className={sel('w-24')}
              onKeyDown={e => { if (e.key === 'Enter' && labelInput.trim()) { edit({ labels: [...labels, labelInput.trim()] }); setLabelInput(''); } }} />
          </div>
          <div className="flex items-center gap-1.5 flex-wrap">
            <span className="w-14">{t('board.issue.components', undefined, 'Bileşen')}</span>
            {components.map(c => <Chip key={c} text={c} tone="bg-infod text-info border-info/40" onRemove={deleted ? undefined : () => edit({ components: components.filter(x => x !== c) })} />)}
            <input value={compInput} disabled={deleted} onChange={e => setCompInput(e.target.value)} placeholder={t('board.issue.addComponent', undefined, '+ bileşen')} className={sel('w-24')}
              onKeyDown={e => { if (e.key === 'Enter' && compInput.trim()) { edit({ components: [...components, compInput.trim()] }); setCompInput(''); } }} />
          </div>
          <div className="flex items-center gap-1.5 flex-wrap">
            <span className="w-14">{t('board.issue.parent', undefined, 'Ebeveyn')}</span>
            <select value={issue.parent_id || ''} disabled={busy || deleted} onChange={e => edit({ parent_id: e.target.value || null })} className={sel('max-w-[320px]')}>
              <option value="">{t('board.issue.none', undefined, '(yok)')}</option>
              {parents.map(p => <option key={p.id} value={p.id}>[{p.key}] {p.title.slice(0, 60)}</option>)}
            </select>
            <span className="w-14 ml-2">{t('board.issue.watchers', undefined, 'İzleyen')}</span>
            {watchers.map(w => <Chip key={w} text={w} onRemove={deleted ? undefined : () => edit({ watchers: watchers.filter(x => x !== w) })} />)}
            <input value={watcherInput} disabled={deleted} onChange={e => setWatcherInput(e.target.value)} placeholder={t('board.issue.addRole', undefined, '+ rol')} className={sel('w-20')}
              onKeyDown={e => { if (e.key === 'Enter' && watcherInput.trim()) { edit({ watchers: [...watchers, watcherInput.trim().toUpperCase()] }); setWatcherInput(''); } }} />
          </div>
        </div>

        {/* Sekmeler */}
        <div className="px-4 border-b border-line flex gap-1 text-[11px] shrink-0 overflow-x-auto">
          {tabs.map(tb => (
            <button key={tb.id} onClick={() => setTab(tb.id)} className={`px-2.5 py-2 flex items-center gap-1 border-b-2 -mb-px transition ${tab === tb.id ? 'border-ac text-ink font-semibold' : 'border-transparent text-ink3 hover:text-ink'}`}>
              {tb.icon}{tb.label}{typeof tb.n === 'number' && tb.n > 0 && <span className="font-mono text-[10px] opacity-70">({tb.n})</span>}
            </button>
          ))}
        </div>
        {err && <div className="px-4 py-1.5 text-[11px] text-err bg-errd/40 border-b border-err/30 shrink-0">{err}</div>}

        <div className="flex-1 overflow-y-auto p-4 text-xs space-y-3">
          {tab === 'detail' && (
            <>
              <label className="block text-[10px] text-ink3">{t('board.issue.description', undefined, 'Açıklama')}
                <textarea value={desc} disabled={deleted} onChange={e => setDesc(e.target.value)} rows={5} className="mt-0.5 w-full bg-sunk border border-line rounded-lg px-2.5 py-1.5 text-xs text-ink" />
              </label>
              <label className="block text-[10px] text-ink3">{t('board.issue.criteria', undefined, 'Kabul kriterleri (satır başına bir)')}
                <textarea value={criteria} disabled={deleted} onChange={e => setCriteria(e.target.value)} rows={4} className="mt-0.5 w-full bg-sunk border border-line rounded-lg px-2.5 py-1.5 text-xs text-ink font-mono" />
              </label>
              <div className="flex items-center justify-between">
                <div className="text-[10px] text-ink3 font-mono space-x-2">
                  {issue.ac_refs && issue.ac_refs.length > 0 && <span>AC: {issue.ac_refs.join(', ')}</span>}
                  {issue.depends_on && issue.depends_on.length > 0 && <span>{t('board.issue.dependsOn', undefined, 'bağımlı:')} {issue.depends_on.join(', ')}</span>}
                  {issue.carry_over?.count ? <span>{t('board.issue.carriedOver', { n: issue.carry_over.count, reason: issue.carry_over.reason }, `taşındı ×${issue.carry_over.count} (${issue.carry_over.reason})`)}</span> : null}
                  {issue.run_id && <span>{t('board.issue.run', undefined, 'koşu')} {issue.run_id}</span>}
                </div>
                <button type="button" disabled={busy || deleted} onClick={() => edit({ description: desc, acceptance_criteria: criteria.split('\n').map(s => s.trim()).filter(Boolean) })}
                  className="px-3 py-1.5 rounded-lg bg-ink text-bg text-[11px] font-semibold flex items-center gap-1 disabled:opacity-50"><Save className="w-3 h-3" /> {t('board.issue.save', undefined, 'Kaydet')}</button>
              </div>
            </>
          )}

          {tab === 'comments' && (
            <>
              {comments.length === 0 && <div className="text-ink3">{t('board.issue.noComments', undefined, 'Henüz yorum yok.')}</div>}
              {comments.map(c => (
                <div key={c.id} className="rounded-lg border border-line bg-sunk/60 p-2.5">
                  <div className="flex items-center justify-between text-[10px] font-mono text-ink3">
                    <span><span className={c.kind === 'agent' ? 'text-info' : 'text-ac'}>{c.author}</span> · {c.kind === 'agent' ? t('board.issue.agent', undefined, 'ajan') : t('board.issue.manager', undefined, 'yönetici')} · {fmt(c.created_at)}</span>
                    <button type="button" onClick={() => run(() => jira.deleteComment(issue.id, c.id))} className="text-ink3 hover:text-err" title={t('board.issue.deleteComment', undefined, 'Yorumu sil')}><Trash2 className="w-3 h-3" /></button>
                  </div>
                  <div className="mt-1 whitespace-pre-wrap text-ink">{c.text}</div>
                </div>
              ))}
              <div className="flex gap-2 items-start">
                <textarea value={comment} onChange={e => setComment(e.target.value)} rows={2} placeholder={t('board.issue.commentPh', undefined, 'Markdown yorum… (ajanlar bağlamda görür)')} className="flex-1 bg-sunk border border-line rounded-lg px-2.5 py-1.5 text-xs text-ink" />
                <button type="button" disabled={busy || !comment.trim()} onClick={() => run(async () => { await jira.comment(issue.id, comment.trim()); setComment(''); })}
                  className="px-3 py-1.5 rounded-lg bg-ink text-bg text-[11px] font-semibold disabled:opacity-50">{t('board.issue.add', undefined, 'Ekle')}</button>
              </div>
            </>
          )}

          {tab === 'links' && (
            <>
              {links.length === 0 && <div className="text-ink3">{t('board.issue.noLinks', undefined, 'Bağ yok.')}</div>}
              {links.map(l => {
                const other = byId(l.target);
                return (
                  <div key={`${l.type}-${l.target}`} className="flex items-center justify-between gap-2 rounded-lg border border-line bg-sunk/60 px-2.5 py-1.5">
                    <span className="min-w-0 truncate">
                      <span className="font-mono text-[10px] text-ink3 mr-2">{linkLabel(l.type)}</span>
                      <button type="button" onClick={() => onOpenIssue?.(l.target)} className="text-ac hover:underline">[{other?.key || l.target}]</button>{' '}
                      <span className="text-ink">{other?.title || ''}</span>
                      {other && <span className="ml-1 text-[10px] font-mono text-ink3">{other.status}</span>}
                    </span>
                    <button type="button" onClick={() => run(() => jira.unlink(issue.id, l.type, l.target))} className="text-ink3 hover:text-err" title={t('board.issue.removeLink', undefined, 'Bağı kaldır')}><Trash2 className="w-3 h-3" /></button>
                  </div>
                );
              })}
              <div className="flex gap-2 items-center flex-wrap">
                <select value={linkType} onChange={e => setLinkType(e.target.value as JiraLinkType)} className={sel()}>
                  {LINK_TYPES.map(lt => <option key={lt} value={lt}>{linkLabel(lt)} ({lt})</option>)}
                </select>
                <select value={linkTarget} onChange={e => setLinkTarget(e.target.value)} className={sel('max-w-[260px]')}>
                  <option value="">{t('board.issue.pickIssue', undefined, 'madde seç…')}</option>
                  {issues.filter(i => i.id !== issue.id && !i.deleted).map(i => <option key={i.id} value={i.id}>[{i.key}] {i.title.slice(0, 50)}</option>)}
                </select>
                <button type="button" disabled={busy || !linkTarget} onClick={() => run(async () => { await jira.link(issue.id, linkType, linkTarget); setLinkTarget(''); })}
                  className="px-3 py-1.5 rounded-lg bg-ink text-bg text-[11px] font-semibold disabled:opacity-50">{t('board.issue.link', undefined, 'Bağla')}</button>
              </div>
            </>
          )}

          {tab === 'attachments' && (
            <>
              {attachments.length === 0 && <div className="text-ink3">{t('board.issue.noAttachments', undefined, 'Ek yok.')}</div>}
              {attachments.map(a => (
                <div key={attId(a)} className="flex items-center justify-between gap-2 rounded-lg border border-line bg-sunk/60 px-2.5 py-1.5">
                  <span className="min-w-0 truncate">
                    <Paperclip className="w-3 h-3 inline mr-1 text-ink3" />
                    {typeof a !== 'string' && a.url ? <a href={a.url} target="_blank" rel="noreferrer" className="text-ac hover:underline">{attName(a)}</a> : <span className="text-ink">{attName(a)}</span>}
                    <span className="ml-2 text-[10px] font-mono text-ink3">{attRef(a)}</span>
                  </span>
                  {typeof a !== 'string' && <button type="button" onClick={() => run(() => jira.detach(issue.id, a.id))} className="text-ink3 hover:text-err" title={t('board.issue.removeAttachment', undefined, 'Eki kaldır')}><Trash2 className="w-3 h-3" /></button>}
                </div>
              ))}
              <div className="space-y-1.5">
                {attachmentSources.length > 0 && (
                  <select value="" onChange={e => { const s = attachmentSources[Number(e.target.value)]; if (s) { setAttNameInput(s.name); setAttRefInput(s.url || s.path || ''); } }} className={sel('w-full')}>
                    <option value="">{t('board.issue.pickSource', undefined, 'Kasa dosyası ya da E2E ekran görüntüsü seç…')}</option>
                    {attachmentSources.map((s, k) => <option key={k} value={k}>{s.name}</option>)}
                  </select>
                )}
                <div className="flex gap-2 items-center">
                  <input value={attNameInput} onChange={e => setAttNameInput(e.target.value)} placeholder={t('board.issue.attName', undefined, 'ad')} className={sel('w-36')} />
                  <input value={attRefInput} onChange={e => setAttRefInput(e.target.value)} placeholder={t('board.issue.attRef', undefined, 'yol ya da adres (proje içi yol ya da /api/… adresi)')} className={sel('flex-1')} />
                  <button type="button" disabled={busy || !attRefInput.trim()}
                    onClick={() => run(async () => {
                      const ref = attRefInput.trim();
                      await jira.attach(issue.id, /^(https?:)?\//.test(ref) ? { name: attNameInput, url: ref } : { name: attNameInput, path: ref });
                      setAttNameInput(''); setAttRefInput('');
                    })}
                    className="px-3 py-1.5 rounded-lg bg-ink text-bg text-[11px] font-semibold disabled:opacity-50">{t('board.issue.addAttachment', undefined, 'Ek ekle')}</button>
                </div>
              </div>
            </>
          )}

          {tab === 'history' && (
            <>
              <div className="rounded-lg border border-ac/40 bg-acd/40 px-3 py-2 text-[11px] text-ink"><span className="font-semibold">{t('board.issue.why', undefined, 'Neden bu durumda:')}</span> {timeline?.why || '…'}</div>
              {(timeline?.entries || []).slice().reverse().map((e, k) => (
                <div key={k} className="flex gap-2 text-[11px]">
                  <span className={`mt-1 w-2 h-2 rounded-full shrink-0 ${e.kind === 'step' ? (e.status === 'DONE' ? 'bg-ok' : e.status === 'FAILED' ? 'bg-err' : 'bg-warn') : e.kind === 'comment' ? 'bg-info' : e.kind === 'field' ? 'bg-ac' : 'bg-ink3'}`} />
                  <div className="min-w-0">
                    <div className="font-mono text-[10px] text-ink3">{fmt(e.ts)} · {e.by || '—'} · {e.kind === 'audit' ? e.action : e.kind === 'step' ? `${t('board.issue.stepN', { n: e.order }, `adım #${e.order}`)} ${e.step_kind}` : e.kind}
                      {e.verification && <span className={`ml-1 px-1 rounded border ${e.verification === 'PASSED' ? 'text-ok border-ok/40' : 'text-err border-err/40'}`}>{e.verification}</span>}
                      {e.commit && <span className="ml-1">⎇ {String(e.commit).slice(0, 7)}</span>}
                    </div>
                    <div className="text-ink whitespace-pre-wrap break-words">{e.text}</div>
                  </div>
                </div>
              ))}
              {timeline && timeline.entries.length === 0 && <div className="text-ink3">{t('board.issue.noEntries', undefined, 'Kayıt yok.')}</div>}
            </>
          )}

          {tab === 'work' && (
            <>
              {!evidence && <div className="text-ink3">{t('board.issue.loading', undefined, 'Yükleniyor…')}</div>}
              {evidence && evidence.steps.length === 0 && <div className="text-ink3">{t('board.issue.noWork', undefined, 'Bu görev için henüz işlem yok.')}</div>}
              {evidence && evidence.steps.map((st, i) => (
                <div key={`${st.run_id}-${st.order}-${i}`} className="rounded-lg border border-line bg-sunk/40 p-2.5 space-y-1.5">
                  <div className="flex items-center gap-2 flex-wrap text-[11px]">
                    <span className="font-semibold">{st.role}</span>
                    <span className="font-mono text-ink3">#{st.order} · {st.kind}{st.fix_round ? ` · ${t('board.issue.fixRound', { n: st.fix_round }, `düzeltme ${st.fix_round}`)}` : ''}</span>
                    <span className={`px-1.5 py-0.5 rounded border font-mono ${st.status === 'DONE' ? 'bg-okd text-ok border-ok/40' : st.status === 'FAILED' || st.status === 'REJECTED' ? 'bg-errd text-err border-err/40' : 'bg-sunk text-ink3 border-line'}`}>{st.status}</span>
                    {st.commit && <button type="button" onClick={() => openCommit(String(st.commit))} className="font-mono text-[10px] px-1.5 py-0.5 rounded border border-line text-ink3 hover:text-ink">⎇ {String(st.commit).slice(0, 7)}</button>}
                    {onInspectTask && <button type="button" onClick={() => onInspectTask(st.order, issue)} className="text-ac hover:underline ml-auto">{t('board.issue.inspectStep', undefined, 'Adımı incele')} →</button>}
                  </div>
                  {st.summary && <div className="text-ink2 text-[11px] whitespace-pre-wrap">{st.summary}</div>}
                  {st.verification && st.verification.status !== 'SKIPPED' && <div className="text-[11px] text-ink3">{t('board.issue.verification', undefined, 'Doğrulama')}: {st.verification.status} · {st.verification.summary}</div>}
                  {(st.artifacts || []).length > 0 ? (
                    <div className="flex flex-wrap gap-1.5">
                      {st.artifacts.map(f => (
                        <button type="button" key={f} onClick={() => openFile(f)} title={f}
                          className="font-mono text-[10px] px-1.5 py-0.5 rounded border border-ac/40 bg-acd text-ac hover:bg-ac/20 transition">{f}</button>
                      ))}
                    </div>
                  ) : <div className="text-[11px] italic text-ink3">{t('board.issue.noFiles', undefined, 'Bu adımda dosya yazılmadı.')}</div>}
                </div>
              ))}
            </>
          )}

          {tab === 'evidence' && (
            <>
              {!evidence && <div className="text-ink3">{t('board.issue.loading', undefined, 'Yükleniyor…')}</div>}
              {evidence && (
                <>
                  <div className="rounded-lg border border-line bg-sunk/60 p-2.5">
                    <div className="text-[10px] font-mono uppercase tracking-wider text-ink3 mb-1">{t('board.issue.whoStepCommit', undefined, 'Kim · hangi adım · hangi commit')}</div>
                    {evidence.last_step ? (
                      <div className="text-[11px] text-ink space-y-0.5">
                        <div><span className="font-semibold">{evidence.last_step.role}</span> · {t('board.issue.stepN', { n: evidence.last_step.order }, `adım #${evidence.last_step.order}`)} ({evidence.last_step.kind}{evidence.last_step.fix_round ? ` · ${t('board.issue.fixRound', { n: evidence.last_step.fix_round }, `düzeltme ${evidence.last_step.fix_round}`)}` : ''}) · {evidence.last_step.status} · {t('board.issue.run', undefined, 'koşu')} <span className="font-mono">{evidence.last_step.run_id}</span></div>
                        <div className="text-ink3">{evidence.last_step.summary}</div>
                        {onInspectTask && <button type="button" onClick={() => onInspectTask(evidence.last_step!.order, issue)} className="text-ac hover:underline text-[11px]">{t('board.issue.inspectStep', undefined, 'Adımı incele')} →</button>}
                      </div>
                    ) : <div className="text-ink3 text-[11px]">{t('board.issue.noRunStep', undefined, 'Bu madde için henüz bir koşu adımı yok.')}</div>}
                    {evidence.commits.length > 0 && (
                      <div className="mt-1 flex flex-wrap items-center gap-1.5 text-[10px] font-mono text-ink3">commit:
                        {evidence.commits.map(c => (
                          <button key={String(c.commit)} type="button" onClick={() => openCommit(String(c.commit))} title={t('board.issue.openCommit', undefined, 'Commit ayrıntısını aç')}
                            className="px-1.5 py-0.5 rounded border border-line hover:text-ink hover:border-line2 transition">{String(c.commit).slice(0, 7)}{c.order ? ` (#${c.order})` : ''}</button>
                        ))}
                      </div>
                    )}
                  </div>
                  <div className="rounded-lg border border-line bg-sunk/60 p-2.5">
                    <div className="text-[10px] font-mono uppercase tracking-wider text-ink3 mb-1">{t('board.issue.verification', undefined, 'Doğrulama')}</div>
                    {evidence.last_verification ? (
                      <div className="text-[11px]"><span className={`px-1.5 py-0.5 rounded border font-mono ${evidence.last_verification.status === 'PASSED' ? 'bg-okd text-ok border-ok/40' : evidence.last_verification.status === 'FAILED' ? 'bg-errd text-err border-err/40' : 'bg-sunk text-ink3 border-line'}`}>{evidence.last_verification.status}</span>
                        <span className="ml-2 text-ink">{evidence.last_verification.summary}</span></div>
                    ) : <div className="text-ink3 text-[11px]">{t('board.issue.noVerification', undefined, 'Doğrulama koşmadı.')}</div>}
                  </div>
                  <div className="rounded-lg border border-line bg-sunk/60 p-2.5">
                    <div className="text-[10px] font-mono uppercase tracking-wider text-ink3 mb-1">{t('board.issue.dodList', undefined, 'DoD kontrol listesi')}</div>
                    {evidence.dod ? evidence.dod.map(d => <div key={d.key} className="text-[11px] flex items-center gap-1.5"><span className={`w-2 h-2 rounded-full ${d.ok ? 'bg-ok' : 'bg-err'}`} />{d.text}</div>)
                      : <div className="text-ink3 text-[11px]">{t('board.issue.noDod', undefined, 'DoD değerlendirmesi yok (sıkı DoD kapalı ya da teslim yok).')}</div>}
                  </div>
                  <div className="rounded-lg border border-line bg-sunk/60 p-2.5">
                    <div className="text-[10px] font-mono uppercase tracking-wider text-ink3 mb-1">{t('board.issue.acCoverage', { covered: evidence.ac_coverage.covered, total: evidence.ac_coverage.total, basis: evidence.ac_coverage.basis === 'mentions' ? ` · ${t('board.issue.mentionsOnly', undefined, 'yalnızca anma, junit yok')}` : evidence.ac_coverage.basis === 'junit' ? ' · junit' : '' }, 'AC kapsama ({covered}/{total}{basis})')}</div>
                    <div className="h-1.5 bg-sunk rounded-full overflow-hidden border border-line mb-1.5">
                      <div className={`h-full ${evidence.ac_coverage.basis === 'junit' ? 'bg-ok' : 'bg-warn'}`} style={{ width: `${evidence.ac_coverage.total ? Math.round(100 * evidence.ac_coverage.covered / evidence.ac_coverage.total) : 0}%` }} />
                    </div>
                    {evidence.ac_coverage.items.map(it => (
                      <div key={it.ac} className="text-[11px] mb-2 last:mb-0">
                        <div className="flex items-center gap-1.5"><span className={`w-2 h-2 rounded-full ${it.evidence.length ? 'bg-ok' : 'bg-err'}`} /><span className="font-mono font-semibold">{it.ac}</span>
                          {it.ac_text && <span className="text-ink2">{it.ac_text}</span>}</div>
                        {it.evidence.length === 0 && <div className="pl-3.5 text-ink3">{t('board.issue.noEvidence', undefined, 'kanıt yok')}</div>}
                        {(it.files || []).map(f => (
                          <div key={f.path} className="pl-3.5 mt-1">
                            <button type="button" onClick={() => openFile(f.path)} title={t('board.issue.openScenarios', undefined, 'Senaryoları ve kodu aç')} className="font-mono text-[10px] px-1.5 py-0.5 rounded border border-ok/40 bg-okd text-ok hover:bg-ok/20">{f.path}</button>
                            {f.summary && <div className="text-ink3 italic mt-0.5">{f.summary}</div>}
                            <ul className="mt-0.5 space-y-0.5">
                              {f.scenarios.slice(0, 8).map(sc => <li key={`${sc.line}-${sc.name}`} className="flex gap-1.5"><span className="text-ok">✓</span><span>{sc.suite ? <span className="text-ink3">{sc.suite} › </span> : null}{sc.name}</span></li>)}
                            </ul>
                            {f.scenarios.length > 8 && <button type="button" onClick={() => openFile(f.path)} className="text-ac hover:underline">{t('board.issue.moreScenarios', { n: f.scenarios.length - 8 }, `+${f.scenarios.length - 8} senaryo daha…`)}</button>}
                          </div>
                        ))}
                        {(it.files || []).length === 0 && it.evidence.length > 0 && <div className="pl-3.5 text-ink3">{it.evidence.join(', ')}</div>}
                      </div>
                    ))}
                    {evidence.ac_coverage.total === 0 && <div className="text-ink3 text-[11px]">{t('board.issue.noAcRefs', { n: evidence.acceptance_criteria.length }, `Maddenin AC kimliği (ac_refs) yok; kriterler: ${evidence.acceptance_criteria.length}`)}</div>}
                  </div>
                </>
              )}
            </>
          )}
        </div>

        <div className="px-4 py-2 border-t border-line flex items-center justify-between text-[11px] shrink-0">
          {deleted ? (
            <button type="button" disabled={busy} onClick={() => run(() => jira.restore(issue.id))} className="flex items-center gap-1 text-ok hover:underline"><RotateCcw className="w-3 h-3" /> {t('board.issue.restore', undefined, 'Geri al')}</button>
          ) : (
            <button type="button" disabled={busy} onClick={async () => { const r = await promptDialog(t('board.issue.deleteReasonPrompt', undefined, 'Silme nedeni (isteğe bağlı):'), ''); if (r !== null) run(() => jira.remove(issue.id, r)); }} className="flex items-center gap-1 text-err hover:underline"><Trash2 className="w-3 h-3" /> {t('board.issue.deleteReversible', undefined, 'Sil (geri alınabilir)')}</button>
          )}
          <span className="text-ink3 font-mono text-[10px]">{t('board.issue.createdUpdated', { created: fmt(issue.created_at), updated: fmt(issue.updated_at) }, `oluşturuldu ${fmt(issue.created_at)} · güncellendi ${fmt(issue.updated_at)}`)}</span>
        </div>
      </div>
    </div>
  );
};
