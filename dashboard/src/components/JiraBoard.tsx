import React, { useState, useMemo } from 'react';
import { notify, confirmDialog, promptDialog } from '../lib/dialog';
import { useI18n } from '../i18n';
import { JiraIssue, JiraIssueStatus, JiraIssueType, AgentRole, PipelineRun, JiraApi, SavedFilter, IssueEvidence } from '../types/telemetry';
import { IssueDetailDrawer } from './IssueDetailDrawer';
import { openFile, openCommit, openDocs } from '../lib/viewer';
import { SprintPanel } from './SprintPanel';
import { Dropdown, DropdownItem } from './Dropdown';
import { 
  CheckSquare, 
  Square, 
  Play, 
  CheckCircle2, 
  Clock, 
  AlertCircle, 
  Layers, 
  Sparkles, 
  User, 
  FileText,
  Bookmark,
  Bug,
  ListTodo,
  FolderPlus,
  FolderTree,
  Kanban,
  PlusCircle,
  ChevronDown,
  ChevronRight,
  ShieldAlert,
  Tag,
  X,
  FolderGit2,
  History,
  ListChecks,
  BookOpen
} from 'lucide-react';

interface JiraBoardProps {
  issues: JiraIssue[];
  onExecuteBatch: (selectedOrders: (number | string)[], stepByStep?: boolean) => Promise<void>;
  onUpdateStatus: (issueId: string, status: JiraIssueStatus) => Promise<void>;
  onAddIssue?: (issue: Partial<JiraIssue>) => Promise<void>;
  isExecuting?: boolean;
  stepByStepMode?: boolean;
  onToggleStepMode?: (enabled: boolean) => void;
  onInspectTask?: (order: number, issue: JiraIssue) => void;
  onInspectAudit?: (issue: JiraIssue) => void;
  pendingStepOrder?: number | null;
  onOpenSpecVault?: () => void;
  projectName?: string;
  projectPath?: string;
  /** D5: yalnızca bu adımı koş (tek adımlık koşu) */
  onRunSingle?: (order: number) => void;
  /** D5: son koşu durumu çipi için koşu geçmişi */
  runs?: PipelineRun[];
  /** G5 Jira+: madde işlemleri, sorgu, sprint panosu */
  jira?: JiraApi;
  sprintVersion?: number;
  attachmentSources?: { name: string; path?: string; url?: string }[];
  /** Sprint kipi: koşuyu Claude oturumu çeker; sabit adım listesiyle koşu düğmeleri gizlenir */
  sprintMode?: boolean;
}

const VIEW_META = {
  TREE: { icon: <FolderTree className="w-3.5 h-3.5 text-ac" />, label: 'Ağaç', full: 'Hiyerarşik Ağaç', hint: 'Epic → Story → Task / Bug' },
  LIST: { icon: <ListChecks className="w-3.5 h-3.5 text-ac" />, label: 'Sıra', full: 'Düz Liste', hint: 'Görev sıra numarasına göre, hiyerarşisiz' },
  SPRINT: { icon: <Layers className="w-3.5 h-3.5 text-ac" />, label: 'Sprint', full: 'Sprint Hiyerarşisi', hint: 'Sprintlere göre gruplu' },
  KANBAN: { icon: <Kanban className="w-3.5 h-3.5 text-ac" />, label: 'Kanban', full: 'Kanban Panosu', hint: 'Durum sütunları; sürükle-bırak' },
} as const;

const STEP_CHIP: Record<string, string> = {
  DONE: 'bg-okd text-ok border-ok/40',
  ACTIVE: 'bg-okd text-ok border-ok/40 animate-pulse',
  WAITING_APPROVAL: 'bg-infod text-info border-info/40',
  REJECTED: 'bg-errd text-err border-err/40',
  FAILED: 'bg-errd text-err border-err/40',
  SKIPPED: 'bg-sunk text-ink3 border-line',
  PENDING: 'bg-sunk text-ink3 border-line',
};

const STEP_LABEL: Record<string, string> = {
  DONE: 'Tamamlandı', ACTIVE: 'Çalışıyor', WAITING_APPROVAL: 'Onay bekliyor', REJECTED: 'Reddedildi',
  FAILED: 'Başarısız', SKIPPED: 'Atlandı', PENDING: 'Sırada',
};

/** Verilen adımı içeren en son koşunun adım kaydını döner. */
function lastStepRecord(runs: PipelineRun[] | undefined, order: number) {
  if (!runs) return null;
  // Aktif (bitmemiş) koşu önce, sonra en yeni koşu: iptal edilmiş eski koşunun SKIPPED adımı güncel durumu gölgelemesin
  const ordered = [...runs].sort((a, b) =>
    Number(!!a.is_terminal) - Number(!!b.is_terminal) || String(b.created_at || '').localeCompare(String(a.created_at || '')));
  for (const run of ordered) {
    // Aynı order birden çok kez geçebilir (düzeltme turları, UAT yeniden koşusu): sonuncusu geçerli
    const matches = run.steps.filter(s => s.order === order);
    const step = matches[matches.length - 1];
    if (step) return { run, step };
  }
  return null;
}

const COLUMNS: { key: JiraIssueStatus; title: string; color: string }[] = [
  { key: 'BACKLOG', title: 'Backlog', color: 'border-line2' },
  { key: 'SELECTED_FOR_DEV', title: 'Selected for Dev', color: 'border-ac/40' },
  { key: 'IN_PROGRESS', title: 'In Progress (Ajan İcrası)', color: 'border-warn/60' },
  { key: 'IN_REVIEW', title: 'In Review / QA Handshake', color: 'border-ac/60' },
  { key: 'DONE', title: 'Done (Tamamlandı)', color: 'border-ok/60' }
];

/** Sprint engel nedeni → okunur başlık ve ne yapılacağı (sunucu `blocked.reason` kodunu verir; kullanıcı kodu çözemiyordu). */
const BLOCK_INFO: Record<string, { title: string; hint: string }> = {
  PRECONDITION_LOST: { title: 'Kapanış koşulu eksik', hint: 'İşler bitti ama sıkı DoD kapanış koşulu sağlanmadı (örn. mimar gözden geçirmesi yapılmadı). Eksik adım tamamlanınca sprint kapanır; yeni sprintlerde sunucu bu adımı kapanıştan önce kendisi planlar.' },
  CARRY_OVER_LIMIT: { title: 'Taşıma sınırı aşıldı', hint: 'Aynı iş sprintten sprinte çok kez taşındı. İşi bölün/yeniden kapsamlayın ya da sınırı artırın.' },
  BUDGET_EXCEEDED: { title: 'Bütçe aşıldı', hint: 'Sprint token/süre/adım sınırına ulaştı. autonomy.budget değerini artırıp engeli kaldırın.' },
  BLOCKING_QUESTION: { title: 'Engelleyici soru açık', hint: 'Sorular penceresinde bekleyen soruyu cevaplayın.' },
  NO_PROGRESS: { title: 'İlerleme yok', hint: 'Art arda adımlar ilerleme kaydetmedi; nedeni inceleyip engeli kaldırın.' },
};

/** Alt görevi olmayan hikâye (örn. PO ret sonrası "AC-n için test yaz" işi): işin kendisi hikâyedir; kabul kriteri kanıtını (test dosyaları, commit) gösterir. */
// Kanıt, madde değişmedikçe (durum/güncelleme zamanı aynı) yeniden istenmez; aynı madde için eşzamanlı tek istek.
const evidenceCache = new Map<string, { key: string; ev: IssueEvidence }>();
const evidenceInflight = new Map<string, Promise<IssueEvidence>>();

const StoryEvidence: React.FC<{ story: JiraIssue; done: boolean; jira?: JiraApi }> = ({ story, done, jira }) => {
  const { t } = useI18n();
  const cacheKey = `${story.status}|${story.updated_at || ''}`;
  const [ev, setEv] = useState<IssueEvidence | null>(() => {
    const hit = evidenceCache.get(story.id);
    return hit && hit.key === cacheKey ? hit.ev : null;
  });
  const [failed, setFailed] = useState(false);
  const jiraRef = React.useRef(jira);
  jiraRef.current = jira;                                   // `jira` nesnesinin kimliği her güncellemede değişebilir: efekt buna bağlanmaz
  React.useEffect(() => {
    let alive = true;
    const api = jiraRef.current;
    if (!api || !done || !(story.ac_refs || []).length) return;   // tamamlanmamış hikâye kanıt göstermez: istek atma
    const hit = evidenceCache.get(story.id);
    if (hit && hit.key === cacheKey) { setEv(hit.ev); return; }
    let req = evidenceInflight.get(story.id);
    if (!req) {
      req = api.evidence(story.id).finally(() => evidenceInflight.delete(story.id));
      evidenceInflight.set(story.id, req);
    }
    req.then(e => { evidenceCache.set(story.id, { key: cacheKey, ev: e }); if (alive) setEv(e); }).catch(() => { if (alive) setFailed(true); });
    return () => { alive = false; };
  }, [story.id, cacheKey, done]);
  const files = Array.from(new Set((ev?.ac_coverage.items || []).flatMap(i => i.evidence)));
  const commits = (ev?.commits || []).map(c => c.commit.slice(0, 7));
  const acItems = ev?.ac_coverage.items || [];
  if (!done) {
    return (
      <div className="text-xs py-2 pl-6 text-ink3">
        {t('board.jira.evQueuedPrefix', undefined, 'Sırada:')} <span className="font-semibold text-ink2">{story.assignee || 'QA'}</span> {t('board.jira.evQueuedSuffix', { refs: (story.ac_refs || []).join(', ') }, 'bu kriter ({refs}) için test/E2E senaryosu yazacak; henüz başlanmadı.')}
      </div>
    );
  }
  return (
    <div className="text-xs py-2 pl-6 space-y-1">
      <div className="text-ink3">{t('board.jira.evTitle', { refs: (story.ac_refs || []).join(', ') }, 'Kanıt ({refs}):')}</div>
      {files.length > 0 ? (
        <>
          {acItems.filter(i => i.ac_text).map(i => <div key={i.ac} className="text-ink2"><span className="font-mono text-ink3">{i.ac}</span> · {i.ac_text}</div>)}
          <div className="flex flex-wrap gap-1.5">
            {files.map(f => (
              <button type="button" key={f} onClick={() => openFile(f)} title={t('board.jira.evOpenFile', { f }, '{f} — senaryoları ve kodu aç')}
                className="font-mono text-[10px] px-1.5 py-0.5 rounded border border-ok/40 bg-okd text-ok hover:bg-ok/20 transition">{f.split('/').pop()}</button>
            ))}
            {commits.map(c => (
              <button type="button" key={c} onClick={() => openCommit(c)} title={t('board.issue.openCommit', undefined, 'Commit ayrıntısını aç')}
                className="font-mono text-[10px] px-1.5 py-0.5 rounded border border-line text-ink3 hover:text-ink hover:border-line2 transition">commit {c}</button>
            ))}
          </div>
          {acItems.flatMap(i => i.files || []).filter(f => f.scenarios.length).slice(0, 3).map(f => (
            <div key={f.path} className="rounded-md border border-line bg-sunk/50 px-2.5 py-1.5">
              <div className="text-[10px] font-mono uppercase tracking-wider text-ink3 mb-0.5">{t('board.jira.scenarios', { name: f.path.split('/').pop() }, 'Senaryolar · {name}')}</div>
              <ul className="space-y-0.5">
                {f.scenarios.slice(0, 4).map(sc => <li key={`${sc.line}-${sc.name}`} className="flex gap-1.5"><span className="text-ok">✓</span><span>{sc.suite ? <span className="text-ink3">{sc.suite} › </span> : null}{sc.name}</span></li>)}
              </ul>
              {f.scenarios.length > 4 && <button type="button" onClick={() => openFile(f.path)} className="mt-0.5 text-ac hover:underline">{t('board.issue.moreScenarios', { n: f.scenarios.length - 4 }, '+{n} senaryo daha…')}</button>}
            </div>
          ))}
        </>
      ) : (
        <div className="text-ink3 italic">{failed ? t('board.jira.evFailed', undefined, 'Kanıt okunamadı.') : ev ? t('board.jira.evDelivered', undefined, 'Teslim edildi; kriteri anan test dosyası bulunamadı.') : t('board.issue.loading', undefined, 'Yükleniyor…')}</div>
      )}
    </div>
  );
};

export const JiraBoard: React.FC<JiraBoardProps> = ({
  issues: allIssues,
  onExecuteBatch,
  onUpdateStatus,
  onAddIssue,
  isExecuting = false,
  stepByStepMode = true,
  onToggleStepMode,
  onInspectTask,
  onInspectAudit,
  pendingStepOrder = null,
  onOpenSpecVault,
  projectName,
  projectPath,
  onRunSingle,
  runs,
  jira,
  sprintVersion = 0,
  attachmentSources = [],
  sprintMode = false
}) => {
  const { t } = useI18n();
  const colTitle = (key: JiraIssueStatus) => t(`board.jira.col.${key}`, undefined, COLUMNS.find(c => c.key === key)?.title || key);
  const colShort = (key: JiraIssueStatus) => colTitle(key).split(' (')[0];
  // G5: silinmiş maddeler varsayılan gizli; detay çekmecesi; JQL sorgu sonuçları; kayıtlı süzgeçler; toplu işlem; sürükle-bırak
  const [showDeleted, setShowDeleted] = useState(false);
  const issues = useMemo(() => allIssues.filter(i => showDeleted || !i.deleted), [allIssues, showDeleted]);
  const deletedCount = allIssues.filter(i => !!i.deleted).length;
  const [detailId, setDetailIdRaw] = useState<string | null>(null);
  const [detailTab, setDetailTab] = useState<'detail' | 'work'>('detail');
  const setDetailId = (id: string | null, tab: 'detail' | 'work' = 'detail') => { setDetailTab(tab); setDetailIdRaw(id); };
  const [queryIds, setQueryIds] = useState<Set<string> | null>(null);
  const [queryErr, setQueryErr] = useState('');
  const [savedFilters, setSavedFilters] = useState<SavedFilter[]>([]);
  const [bulkMsg, setBulkMsg] = useState('');
  const [bulkLabel, setBulkLabel] = useState('');
  const [bulkOpen, setBulkOpen] = useState(false);
  const [dragId, setDragId] = useState<string | null>(null);
  const dropOn = async (e: React.DragEvent, status: JiraIssueStatus, index?: number) => {
    e.preventDefault();
    e.stopPropagation();
    const id = e.dataTransfer.getData('text/plain') || dragId;
    setDragId(null);
    if (!id || !jira) return;
    try { await jira.move(id, status, index); } catch (err) { notify((err as Error).message); }
  };
  // Epik/hikâye anahtarı: tıklayınca sağ çekmece açılır (satırın aç/kapa tıklamasını tetiklemez); sanal epiklerde düz metin
  const keyLink = (it: JiraIssue, cls: string) => {
    const real = !!jira && !(it as { virtual?: boolean }).virtual && it.id !== 'EPIC-ROOT' && allIssues.some(i => i.id === it.id);
    const label = it.key || it.id;
    return real ? (
      <span role="button" tabIndex={0} onClick={e => { e.stopPropagation(); setDetailId(it.id); }} onKeyDown={e => { if (e.key === 'Enter') { e.stopPropagation(); setDetailId(it.id); } }}
        className={`${cls} cursor-pointer hover:underline`} title={t('board.jira.detailTitle', undefined, 'Madde detayı: alanlar, yorumlar, bağlar, ekler, geçmiş, kanıt')}>{label}</span>
    ) : <span className={cls}>{label}</span>;
  };
  // #ID rozeti: tıklayınca sağda çekmece açılır; koşu adımı çalışmış görevde doğrudan "İşlemler" sekmesi (yapılanlar + dosyalar), yoksa Detay sekmesi
  const idBadge = (task: JiraIssue) => (
    <button type="button" onClick={() => jira && setDetailId(task.id, lastStepRecord(runs, task.order) ? 'work' : 'detail')} disabled={!jira}
      className="text-[10px] bg-acd text-ac border border-ac/40 font-bold px-1.5 py-0.5 rounded shrink-0 hover:bg-ac/20 hover:underline"
      title={t('board.jira.detailTitle', undefined, 'Madde detayı: alanlar, yorumlar, bağlar, ekler, geçmiş, kanıt')}>#{task.order}</button>
  );
  const renderRunControls = (order: number, compact = false) => {
    const last = lastStepRecord(runs, order);
    const sz = compact ? 'text-[9px]' : 'text-[10px]';
    const chip = `${sz} font-mono px-1.5 py-0.5 rounded border`;
    const all = last ? last.run.steps.filter(x => x.order === order) : [];
    const fixes = all.filter(x => x.kind === 'fix' && x.status !== 'PENDING').length;
    const v = last?.step.verification;
    const commit = [...all].reverse().find(x => x.commit)?.commit;
    return (
      <>
        {last && (
          <span className="inline-flex flex-wrap items-center gap-1">
            <span
              title={`${t('board.jira.lastRun', { id: last.run.run_id, engine: last.run.engine === 'mcp_client' ? t('board.jira.engineMcp', undefined, 'MCP İstemcisi') : t('board.jira.engineTemplate', undefined, 'Şablon'), status: last.step.status }, 'Son koşu {id} ({engine}) • {status}')}${last.step.summary ? `\n${last.step.summary}` : ''}${last.step.error ? `\n${t('board.jira.errorPrefix', undefined, 'Hata:')} ${last.step.error}` : ''}`}
              className={`${chip} ${STEP_CHIP[last.step.status] || STEP_CHIP.PENDING}`}
            >
              {t(`board.jira.step.${last.step.status}`, undefined, STEP_LABEL[last.step.status] || last.step.status)}
            </span>
            {last.step.kind === 'fix' && last.step.status !== 'DONE' && (
              <span className={`${chip} bg-warnd text-warn border-warn/40`} title={t('board.jira.fixInProgress', undefined, 'Düzeltme turu sürüyor')}>{t('board.jira.fixRoundChip', { n: last.step.fix_round || 1 }, 'düzeltme {n}. tur')}</span>
            )}
            {v && v.status !== 'SKIPPED' && (
              <span
                title={`${v.summary || ''}${v.failed_step ? `\n${t('board.jira.failedStage', { stage: v.failed_step }, 'Başarısız aşama: {stage}')}` : ''}`}
                className={`${chip} ${v.status === 'PASSED' ? 'bg-okd text-ok border-ok/40' : 'bg-errd text-err border-err/40'}`}
              >
                {v.status === 'PASSED' ? `✔ ${t('board.jira.verifyWord', undefined, 'doğrulama')}` : `✖ ${v.failed_step || t('board.jira.verifyWord', undefined, 'doğrulama')}`}
              </span>
            )}
            {fixes > 0 && last.step.kind !== 'fix' && (
              <span className={`${chip} bg-sunk text-ink2 border-line`} title={t('board.jira.fixesTitle', undefined, 'Bu görev için yapılan düzeltme turu sayısı')}>{t('board.jira.fixesCount', { n: fixes }, '↻ {n} düzeltme')}</span>
            )}
            {last.step.attempts > 1 && (
              <span className={`${chip} bg-sunk text-ink3 border-line`} title={t('board.jira.attemptsTitle', undefined, 'Sunucunun reddettiği ve yeniden istenen teslim sayısı')}>{t('board.jira.attempts', { n: last.step.attempts }, '{n} deneme')}</span>
            )}
            {commit && (
              <span className={`${chip} bg-sunk text-ink2 border-line`} title={`SCM commit ${commit}`}>⎇ {String(commit).slice(0, 7)}</span>
            )}
          </span>
        )}
        {onRunSingle && (
          <button
            type="button"
            disabled={isExecuting}
            onClick={() => onRunSingle(order)}
            className={`${compact ? 'text-[10px]' : 'text-[11px]'} text-ok hover:text-ok flex items-center gap-0.5 hover:underline disabled:opacity-40 disabled:no-underline`}
            title={t('board.jira.runSingleTitle', undefined, 'Sadece bu adımı çalıştır (tek adımlık koşu)')}
          >
            <Play className="w-3 h-3 fill-current" />
            <span>{t('board.jira.runSingle', undefined, 'Sadece bu adım')}</span>
          </button>
        )}
      </>
    );
  };
  // Görünüm Seçimi: Ağaç Hiyerarşisi (Tree) vs Kanban Sütunları
  const [viewMode, setViewMode] = useState<'TREE' | 'LIST' | 'SPRINT' | 'KANBAN'>('TREE');

  // Görev seçimleri: 'dışlananlar' tutulur (boş küme = tüm görevler seçili),
  // böylece WS'ten sonradan gelen veya proje değişiminde yenilenen görevler otomatik seçili olur
  const [excludedIds, setExcludedIds] = useState<Set<string>>(new Set());
  const selectedIds = useMemo(
    () => new Set(issues.filter(i => !excludedIds.has(i.id)).map(i => i.id)),
    [issues, excludedIds]
  );
  /** Yalnızca verilen kimlikler seçili kalsın. */
  const selectOnly = (ids: string[]) => {
    const keep = new Set(ids);
    setExcludedIds(new Set(issues.filter(i => !keep.has(i.id)).map(i => i.id)));
  };
  const [filterAssignee, setFilterAssignee] = useState<string>('ALL');
  const [stepByStep, setStepByStep] = useState<boolean>(stepByStepMode);

  // Ağaç/sprint düğümleri İLK AÇILIŞTA KAPALIDIR. Kullanıcı açarsa açık kalır (yenilemede de); elle kapatırsa kapalı kalır.
  // Filtre/arama etkinken varsayılan "açık"tır (sonuçlar görünsün), elle kapatma yine geçerlidir.
  const treeKey = `fssc_jira_tree:${projectName || 'default'}`;
  const [treeState, setTreeState] = useState<{ open: string[]; shut: string[] }>(() => {
    try {
      const raw = JSON.parse(localStorage.getItem(treeKey) || 'null');
      if (raw && Array.isArray(raw.open) && Array.isArray(raw.shut)) return { open: raw.open, shut: raw.shut };
    } catch { /* depolama yoksa boş başla */ }
    return { open: [], shut: [] };
  });

  // Yeni Görev / Bug Ekleme Modalı
  const [isAddModalOpen, setIsAddModalOpen] = useState<boolean>(false);
  const [newTitle, setNewTitle] = useState('');
  const [newType, setNewType] = useState<JiraIssueType>('TASK');
  const [newAssignee, setNewAssignee] = useState<AgentRole>('BACKEND_DEV');
  const [newPriority, setNewPriority] = useState<'P0' | 'P1' | 'P2'>('P1');
  const [newExpedite, setNewExpedite] = useState<'' | 'next_sprint' | 'now'>('');
  const [newDesc, setNewDesc] = useState('');
  const [newCriteria, setNewCriteria] = useState('');
  const [newParentId, setNewParentId] = useState<string>('');

  React.useEffect(() => {
    setStepByStep(stepByStepMode);
  }, [stepByStepMode]);

  const toggleSelect = (id: string) => {
    setExcludedIds(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const handleSelectAll = () => {
    setExcludedIds(new Set());
  };

  const handleDeselectAll = () => {
    setExcludedIds(new Set(issues.map(i => i.id)));
  };

  const handleSelect1To10 = () => {
    const items1to10 = issues.filter(i => i.order >= 1 && i.order <= 10).map(i => i.id);
    selectOnly(items1to10);
  };

  const handleSelectTestsOnly = () => {
    const testItems = issues.filter(i => i.order === 6 || i.order === 7).map(i => i.id);
    selectOnly(testItems);
  };

  const handleRunSelected = async () => {
    if (selectedIds.size === 0) {
      notify(t('board.jira.selectOne', undefined, 'Lütfen çalıştırılacak en az bir Jira görevi seçin.'));
      return;
    }
    const selectedOrders = issues
      .filter(i => selectedIds.has(i.id))
      .map(i => i.order);
    await onExecuteBatch(selectedOrders, stepByStep);
  };

  const handleRunTestsOnly = async () => {
    await onExecuteBatch([6, 7], stepByStep);
  };

  // `collapsedNodes.has(id)`: düğüm kapalı mı? (eski kullanım yerleri aynen çalışır)
  const collapsedNodes = {
    has: (id: string): boolean => {
      if (treeState.open.includes(id)) return false;
      if (treeState.shut.includes(id)) return true;
      return !filterActive;
    },
  };
  const toggleCollapse = (nodeId: string) => {
    const wasCollapsed = collapsedNodes.has(nodeId);
    const next = {
      open: wasCollapsed ? [...treeState.open.filter(x => x !== nodeId), nodeId] : treeState.open.filter(x => x !== nodeId),
      shut: wasCollapsed ? treeState.shut.filter(x => x !== nodeId) : [...treeState.shut.filter(x => x !== nodeId), nodeId],
    };
    setTreeState(next);
    try { localStorage.setItem(treeKey, JSON.stringify(next)); } catch { /* yoksay */ }
  };

  // Yeni Görev veya Bug Ekleme İşleyicisi
  const [creating, setCreating] = useState(false);
  const handleCreateIssue = async (e: React.FormEvent) => {
    e.preventDefault();
    if (creating) return;                       // çift tıklama/Enter ikinci iş açmasın
    if (!newTitle.trim()) {
      notify(t('board.jira.enterTitle', undefined, 'Lütfen görev başlığı girin.'));
      return;
    }
    setCreating(true);

    const newOrder = issues.length > 0 ? Math.max(...issues.map(i => i.order || 0)) + 1 : 1;
    const newId = `JIRA-${newOrder}`;
    const newKey = newType === 'BUG' ? `BUG-${newOrder}` : `DEV-${newOrder}`;

    const newIssue: Partial<JiraIssue> = {
      id: newId,
      key: newKey,
      order: newOrder,
      title: newTitle,
      description: newDesc || `${newType}: ${newTitle}`,
      issue_type: newType,
      status: 'BACKLOG',
      priority: newPriority,
      assignee: newAssignee,
      parent_id: newParentId || undefined,
      acceptance_criteria: newCriteria.split('\n').map(s => s.trim()).filter(Boolean),
      attachments: [],
      // Panodan girilen iş sprint kipinde de yapılabilsin (sunucu yalnızca kind=task işleri sprint adımına çevirir)
      ...(newType === 'BUG' || newType === 'TASK' ? { kind: 'task', origin: 'MANAGER', ...(newType === 'BUG' ? { work_type: 'BUG' } : {}) } : {}),
    } as Partial<JiraIssue>;

    try {
    if (onAddIssue) {
      await onAddIssue(newIssue);
    } else {
      // Fallback updateStatus ile tetikle
      await onUpdateStatus(newId, 'BACKLOG');
    }
    // Pencere hemen kapanır (öncelik şeridi uygulanırken ya da uyarı beklenirken açık kalıp tekrar gönderilmesin)
    const expedite = newExpedite;
    setExcludedIds(prev => { const next = new Set(prev); next.delete(newId); return next; });
    setNewTitle('');
    setNewDesc('');
    setNewCriteria('');
    setNewExpedite('');
    setIsAddModalOpen(false);
    if (expedite) {
      try {
        const j = await postPlan(newId, { expedite });
        const x = j.expedite || {};
        notify(x.mode === 'now' ? `${t('board.jira.expediteAdded', { order: x.order }, 'Önce yap: iş çalışan koşuya eklendi (adım #{order}); geçerli adımdan hemen sonra yapılacak.')}${(x.warnings || []).length ? '\n' + x.warnings.join('\n') : ''}`
          : (x.fallback ? `${x.reason || t('board.jira.noSprintRun', undefined, 'Çalışan sprint koşusu yok.')}` : t('board.jira.movedToNextSprint', undefined, 'İş sıradaki sprintin başına alındı.')));
      } catch (err) { notify(t('board.jira.expediteFailed', { message: (err as Error).message }, 'Öncelik şeridi uygulanamadı: {message}')); }
    }
    } finally {
      setCreating(false);
    }
  };

  const [filterSprint, setFilterSprint] = useState<'ALL' | 'BACKLOG' | number>('ALL');
  const [filterStatus, setFilterStatus] = useState<JiraIssueStatus | 'ALL'>('ALL');
  // Bitenleri gizle / iş türü (Tasarım, Frontend...) / yalnızca çalışan koşudaki işler; tercih proje başına saklanır
  const prefKey = `fssc_jira_pref:${projectName || 'default'}`;
  const [prefs, setPrefs] = useState<{ hideDone: boolean; inRun: boolean; desc: boolean }>(() => {
    try { return { hideDone: false, inRun: false, desc: false, ...JSON.parse(localStorage.getItem(prefKey) || '{}') }; } catch { return { hideDone: false, inRun: false, desc: false }; }
  });
  const setPref = (p: Partial<typeof prefs>) => setPrefs(prev => {
    const next = { ...prev, ...p };
    try { localStorage.setItem(prefKey, JSON.stringify(next)); } catch { /* yoksay */ }
    return next;
  });
  const [filterWork, setFilterWork] = useState<string>('ALL');
  const runIssueIds = useMemo(() => {
    const run = [...(runs || [])].filter(r => !r.is_terminal).sort((a, b) => String(b.created_at || '').localeCompare(String(a.created_at || '')))[0];
    return run ? new Set(run.steps.map(st => st.issue_id)) : new Set<string>();
  }, [runs]);
  const [filterQuery, setFilterQuery] = useState<string>(() => (window as unknown as { __fsscQuery?: string }).__fsscQuery || '');
  React.useEffect(() => {
    const h = (e: Event) => setFilterQuery(String((e as CustomEvent).detail ?? ''));
    window.addEventListener('fssc:query', h);
    return () => window.removeEventListener('fssc:query', h);
  }, []);
  const selVis = selectedIds.size < issues.length ? '' : 'opacity-0 group-hover:opacity-100 focus-visible:opacity-100 transition-opacity';
  const filterActive = filterSprint !== 'ALL' || filterAssignee !== 'ALL' || filterStatus !== 'ALL' || filterQuery.trim() !== '' || filterWork !== 'ALL' || prefs.hideDone || prefs.inRun;
  // G5: operatör içeren metin JQL benzeri sorgudur (sunucuda çalışır); düz metin anahtar/başlık/etiket araması
  const isJql = (q: string) => /(=|!=|~|\sin\s|\border by\b|\sand\s|\sor\s|\bis (not )?empty\b)/i.test(q);
  React.useEffect(() => {
    if (!jira || !isJql(filterQuery)) { setQueryIds(null); setQueryErr(''); return; }
    const t = setTimeout(async () => {
      try {
        const res = await jira.query(filterQuery, showDeleted);
        setQueryIds(new Set(res.map(i => i.id)));
        setQueryErr('');
      } catch (e) { setQueryErr((e as Error).message); }
    }, 350);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filterQuery, showDeleted, allIssues]);
  React.useEffect(() => {
    if (jira) jira.filters().then(r => setSavedFilters(r.filters)).catch(() => undefined);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  const runBulk = async (action: string, value?: unknown) => {
    if (!jira) return;
    const ids = Array.from(selectedIds);
    // Toplu değişiklik seçim menüsünden tek tıkla uygulanıyordu: tüm maddeler seçiliyken yanlışlıkla seçilen bir değer herkesi değiştirir
    if (ids.length > 5 && !await confirmDialog(`${t('board.jira.bulkConfirm', { n: ids.length, action, value: value === null || value === undefined ? t('board.jira.empty', undefined, 'boş') : String(value) }, '{n} madde için "{action}" = {value} uygulanacak. Emin misin?')}${ids.length === issues.length ? `\n\n${t('board.jira.bulkAllWarn', undefined, 'UYARI: tüm maddeler seçili.')}` : ''}`)) return;
    try {
      const r = await jira.bulk(ids, action, value);
      setBulkMsg(`${t('board.jira.bulkDone', { action, ok: r.ok }, '{action}: {ok} tamam')}${r.failed ? t('board.jira.bulkFailed', { n: r.failed, errors: r.results.filter(x => !x.ok).map(x => `${x.id}: ${x.error}`).join('; ') }, ', {n} kaldı ({errors})') : ''}`);
    } catch (err) { setBulkMsg(`⚠ ${(err as Error).message}`); }
  };
  const matchesFilter = (issue: JiraIssue) => {
    if (filterAssignee !== 'ALL' && issue.assignee !== filterAssignee) return false;
    if (filterStatus !== 'ALL' && issue.status !== filterStatus) return false;
    if (filterWork !== 'ALL' && (issue.work_type || '') !== filterWork) return false;
    if (prefs.inRun && !runIssueIds.has(issue.id)) return false;
    if (prefs.hideDone && (issue.status === 'DONE' || lastStepRecord(runs, issue.order)?.step.status === 'DONE')) return false;
    if (filterSprint === 'BACKLOG' && (issue.sprint || issue.planned_sprint)) return false;
    if (typeof filterSprint === 'number' && issue.sprint !== filterSprint && issue.planned_sprint !== filterSprint) return false;
    if (queryIds) return queryIds.has(issue.id);
    const q = filterQuery.trim().toLowerCase();
    if (q && !`${issue.key} ${issue.id} ${issue.title} ${(issue.labels || []).join(' ')} ${issue.description || ''} ${(issue.acceptance_criteria || []).join(' ')} ${(issue.ac_refs || []).join(' ')}`.toLowerCase().includes(q)) return false;
    return true;
  };
  const filteredIssues = issues.filter(matchesFilter);

  // İlerleme: yalnızca iş maddeleri (TASK/BUG) sayılır; Epic/Story bunların kapsayıcısıdır
  const workItems = issues.filter(i => i.issue_type === 'TASK' || i.issue_type === 'BUG');
  const statusCounts = useMemo(() => {
    const c: Record<string, number> = {};
    workItems.forEach(i => { c[i.status] = (c[i.status] || 0) + 1; });
    return c;
  }, [issues]);
  const isDone = (i: JiraIssue) => i.status === 'DONE' || lastStepRecord(runs, i.order)?.step.status === 'DONE';
  // Durum tonu: tamamlananlar pasif (soluk, üzerine gelince açılır), süren işler aktif (sıcak renk vurgusu)
  const isActive = (i: JiraIssue) => i.status === 'IN_PROGRESS' && !isDone(i);
  const passiveCls = (i: JiraIssue) => (isDone(i) ? 'opacity-70 saturate-75 hover:opacity-90' : '');
  const doneCount = workItems.filter(isDone).length;
  const donePct = workItems.length ? Math.round((doneCount / workItems.length) * 100) : 0;

  // Hiyerarşik Ağaç Yapısı (Epic -> Story/Feature -> Tasks & Bugs)
  const hierarchicalTree = useMemo(() => {
    // 1. Epics
    const epics = issues.filter(i => i.issue_type === 'EPIC');
    // Eğer hiç Epic yoksa sanal bir Epic oluştur
    const primaryEpic = epics[0] || {
      id: 'EPIC-ROOT',
      key: 'EPIC-1',
      order: 1,
      title: t('board.jira.rootEpicTitle', undefined, 'Ana Proje Epici: Çekirdek Sistem & Müşteri Şartnamesi'),
      description: t('board.jira.rootEpicDesc', undefined, 'Müşteri isterleri ve uçtan uca mimari geliştirme epici.'),
      issue_type: 'EPIC' as const,
      status: 'IN_PROGRESS' as const,
      priority: 'P0' as const,
      assignee: 'PM' as const,
      acceptance_criteria: [],
      attachments: [],
      created_at: '',
      updated_at: ''
    };

    const actualEpics = epics.length > 0 ? epics : [primaryEpic];

    // 2. Stories / Features
    const stories = issues.filter(i => i.issue_type === 'STORY' || i.issue_type === 'FEATURE');
    // 3. Tasks & Bugs
    const tasksAndBugs = issues.filter(i => (i.issue_type === 'TASK' || i.issue_type === 'BUG') && matchesFilter(i));

    // Her madde ağaçta TEK yere konur: hikâyesi olan hikâyenin altına, epik'e bağlı olan epik'in,
    // hiçbir ebeveyni olmayan ise ilk epik'in "Genel Proje Görevleri" altına.
    const epicIds = new Set(actualEpics.map(e => e.id));
    const storyIds = new Set(stories.map(st => st.id));
    const hasRealEpics = epics.length > 0;
    const firstEpicId = actualEpics[0].id;
    // Gerçek epik varsa epiğe bağlı olmayan iş ilk epiğe DEĞİL ayrı 'Genel' bölüme girer (aksi halde ilgisiz yüzlerce iş yanlış epiğin altında görünürdü)
    const NONE = '__GENERAL__';
    const epicOfStory = (st: JiraIssue) => (st.parent_id && epicIds.has(st.parent_id) ? st.parent_id : (hasRealEpics ? NONE : firstEpicId));
    const storyOfTask = (t: JiraIssue): string | null => {
      if (t.parent_id && storyIds.has(t.parent_id)) return t.parent_id;
      // Fallback mantık: 3,4,5 -> JIRA-2, 6,7,8 -> JIRA-1
      if (!t.parent_id && storyIds.has('JIRA-2') && [3, 4, 5].includes(t.order)) return 'JIRA-2';
      if (!t.parent_id && storyIds.has('JIRA-1') && [6, 7, 8].includes(t.order)) return 'JIRA-1';
      return null;
    };
    const epicOfOrphan = (t: JiraIssue) => (t.parent_id && epicIds.has(t.parent_id) ? t.parent_id : (hasRealEpics ? NONE : firstEpicId));

    const build = (epic: JiraIssue, key: string) => {
      const storiesWithChildren = stories
        .filter(st => epicOfStory(st) === key)
        .map(story => ({ story, children: tasksAndBugs.filter(t => storyOfTask(t) === story.id) }))
        .filter(sc => !filterActive || sc.children.length > 0);
      const orphanTasks = tasksAndBugs.filter(t => storyOfTask(t) === null && epicOfOrphan(t) === key);
      return { epic, stories: storiesWithChildren, orphanTasks };
    };
    const rows = actualEpics.map(epic => build(epic, epic.id));
    if (hasRealEpics) {
      const general = {
        id: 'EPIC-GENERAL', key: 'GENEL', order: 0, title: t('board.jira.generalEpicTitle', undefined, 'Diğer işler (bir epiğe bağlı değil)'),
        description: t('board.jira.generalEpicDesc', undefined, 'Epiğe/hikâyeye bağlanamayan iş ve hikâyeler (çoğu eski kayıt). Yeni işler oluşurken FS-SC tarafından otomatik bağlanır.'),
        issue_type: 'EPIC' as const, status: 'IN_PROGRESS' as const, priority: 'P1' as const, assignee: 'PM' as const,
        acceptance_criteria: [], attachments: [], created_at: '', updated_at: '', virtual: true,
      } as unknown as JiraIssue;
      const g = build(general, NONE);
      if (g.stories.length > 0 || g.orphanTasks.length > 0) rows.push(g);
    }
    return rows;
  }, [issues, filterAssignee, filterStatus, filterQuery, filterSprint, filterWork, prefs, runIssueIds, runs, queryIds, t]);

  // ŞİMDİ / SIRADA: koşunun çalışan adımı ve sıradaki adımları. Ağaçta rozetle işaretlenir; üstteki şeritten ilgili maddeye gidilir.
  const queueInfo = useMemo(() => {
    const run = [...(runs || [])].filter(r => !r.is_terminal).sort((a, b) => String(b.created_at || '').localeCompare(String(a.created_at || '')))[0];
    if (!run) return null;
    const cur = run.steps.find(st => st.status === 'ACTIVE' || st.status === 'WAITING_APPROVAL') || null;
    const idx = cur ? run.steps.indexOf(cur) : -1;
    const upcoming = run.steps.slice(idx + 1).filter(st => st.status === 'PENDING').slice(0, 4);
    const find = (id: string) => issues.find(i => i.id === id);
    return { cur, upcoming, curIssue: cur ? find(cur.issue_id) : undefined, upIssues: upcoming.map(st => find(st.issue_id)) };
  }, [runs, issues]);
  const nowId = queueInfo?.cur?.issue_id;
  const holdsNow = (ids: string[]) => !!nowId && ids.includes(nowId);
  const queueBadge = (id: string) => {
    if (!queueInfo) return null;
    if (queueInfo.cur?.issue_id === id) return <span className="shrink-0 px-1.5 py-0.5 rounded border border-warn/60 bg-warnd text-warn text-[9px] font-bold animate-pulse whitespace-nowrap">▶ {t('board.jira.nowBadge', undefined, 'ŞİMDİ')}</span>;
    const i = queueInfo.upcoming.findIndex(st => st.issue_id === id);
    return i >= 0 ? <span className="shrink-0 px-1.5 py-0.5 rounded border border-info/50 bg-infod text-info text-[9px] font-bold whitespace-nowrap">{t('board.jira.nextBadge', undefined, 'SIRADA')} {i + 1}</span> : null;
  };
  const holdsBadge = (ids: string[]) => (holdsNow(ids)
    ? <span className="shrink-0 px-1.5 py-0.5 rounded border border-warn/60 bg-warnd text-warn text-[9px] font-bold whitespace-nowrap" title={t('board.jira.runningInsideTitle', undefined, 'Şu an bu başlığın altındaki iş çalışıyor')}>● {t('board.jira.runningInside', undefined, 'içinde çalışıyor')}</span> : null);
  // Şerit/rozet tıklaması: ağaçta ilgili maddeyi bul (süzgeç gizliyorsa süzgeçleri temizle), kaydır ve kısa süre vurgula
  const [revealTarget, setRevealTarget] = useState<string | null>(null);
  const revealIssue = (issueId: string) => {
    if (!filteredIssues.some(i => i.id === issueId)) {
      setFilterStatus('ALL'); setFilterAssignee('ALL'); setFilterQuery(''); setFilterSprint('ALL'); setFilterWork('ALL'); setPref({ hideDone: false, inRun: false });
    }
    setRevealTarget(issueId);
  };
  React.useEffect(() => {
    if (!revealTarget) return;
    const open: string[] = [];
    let found = false;
    for (const t of hierarchicalTree) {
      for (const sc of t.stories) if (sc.story.id === revealTarget || sc.children.some(c => c.id === revealTarget)) { open.push(t.epic.id, sc.story.id); found = true; }
      if (t.epic.id === revealTarget || t.orphanTasks.some(o => o.id === revealTarget)) { open.push(t.epic.id); found = true; }
    }
    if (!found) return;                                    // süzgeç temizlenip ağaç yenilenince tekrar denenir
    setViewMode('TREE');
    if (open.length) {
      const next = { open: Array.from(new Set([...treeState.open, ...open])), shut: treeState.shut.filter(x => !open.includes(x)) };
      setTreeState(next);
      try { localStorage.setItem(treeKey, JSON.stringify(next)); } catch { /* yoksay */ }
    }
    const id = revealTarget;
    setRevealTarget(null);
    let tries = 0;
    const timer = setInterval(() => {
      const el = document.querySelector(`[data-issue-id="${id}"]`);
      if (el || ++tries > 12) {
        clearInterval(timer);
        if (el) {
          el.scrollIntoView({ block: 'center', behavior: 'smooth' });
          el.classList.remove('fssc-flash');
          void (el as HTMLElement).offsetWidth;            // animasyonu yeniden başlat
          el.classList.add('fssc-flash');
          setTimeout(() => el.classList.remove('fssc-flash'), 2600);
        }
      }
    }, 80);
  }, [revealTarget, hierarchicalTree]);

  // --- Sprint görünümü ve yönetici düzenlemesi ---
  type SprintInfo = { sprint_number: number; status: string; goal?: string; committed_issue_ids?: string[]; completed_issue_ids?: string[]; blocked?: { reason: string; since?: string; detail?: string } | null };
  const [sprints, setSprints] = useState<SprintInfo[]>([]);
  const [editing, setEditing] = useState<JiraIssue | null>(null);
  const [editErr, setEditErr] = useState('');
  const loadSprints = async () => {
    try {
      const r = await fetch('/api/sprints');
      const j = await r.json();
      setSprints(j?.state?.sprints || []);
    } catch { /* sprint kipi kapalı olabilir */ }
  };
  React.useEffect(() => { loadSprints(); }, [issues]);
  const sprintOf = (i: JiraIssue): number | null => i.sprint || null;
  const postPlan = async (id: string, body: Record<string, unknown>) => {
    const r = await fetch(`/api/jira/issues/${encodeURIComponent(id)}/plan`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
    });
    const j = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(j.error || t('board.jira.errorStatus', { status: r.status }, 'Hata {status}'));
    return j;
  };
  const move = async (task: JiraIssue, dir: 'up' | 'down') => {
    try { await postPlan(task.id, { move: dir }); } catch (e) { notify((e as Error).message); }
  };
  const canPlan = (t: JiraIssue) => t.status === 'BACKLOG' && !t.sprint;
  // Sprinte alınmış ama başlamamış iş de öne alınabilir ("Önce yap": kuyrukta geçerli adımın arkasına taşınır)
  const canExpedite = (t: JiraIssue) => t.status === 'BACKLOG' && !t.deleted && t.expedite !== 'now';
  const expediteNow = async (tk: JiraIssue) => {
    try {
      const j = await postPlan(tk.id, { expedite: 'now' });
      const x = j.expedite || {};
      notify(x.moved === false ? (x.message || t('board.jira.alreadyNext', undefined, 'İş zaten sıradaki adım.')) : x.mode === 'now' ? `${t('board.jira.expediteNow', { key: tk.key || tk.id }, 'Önce yap: {key} geçerli adımdan hemen sonra yapılacak.')}${(x.warnings || []).length ? '\n' + x.warnings.join('\n') : ''}` : (x.reason || t('board.jira.movedToNextSprint', undefined, 'İş sıradaki sprintin başına alındı.')));
    } catch (e) { notify((e as Error).message); }
  };
  const renderPlanBadge = (task: JiraIssue) => (
    <span className="inline-flex items-center gap-1 shrink-0">
      {sprintOf(task) ? (
        <span className="text-[10px] font-mono px-1.5 py-0.5 rounded border bg-infod text-info border-info/40" title={t('board.jira.inSprintTitle', undefined, 'Bu iş sprinte alındı')}>S{sprintOf(task)}</span>
      ) : task.planned_sprint ? (
        <span className="text-[10px] font-mono px-1.5 py-0.5 rounded border bg-warnd text-warn border-warn/40" title={t('board.jira.pinnedTitle', undefined, 'Yönetici bu işi bu sprinte sabitledi')}>→ S{task.planned_sprint}</span>
      ) : (
        <span className="text-[10px] font-mono px-1.5 py-0.5 rounded border bg-sunk text-ink3 border-line" title={t('board.jira.unassignedTitle', undefined, 'Henüz bir sprinte atanmadı')}>{t('board.jira.backlogChip', undefined, 'backlog')}</span>
      )}
      {task.expedite && (
        <span className="text-[10px] font-mono px-1.5 py-0.5 rounded border bg-warnd text-warn border-warn/50"
          title={task.expedite === 'now' ? t('board.jira.expNowTitle', undefined, 'Yönetici önce yap dedi: çalışan koşunun hemen sonraki adımı') : t('board.jira.expNextTitle', undefined, 'Yönetici sıradaki sprintin başına aldı')}>
          ⚡ {task.expedite === 'now' ? t('board.jira.expNowLabel', undefined, 'önce yap') : t('board.jira.expNextLabel', undefined, 'sprint başı')}
        </span>
      )}
    </span>
  );
  const renderPlanActions = (task: JiraIssue) => (
    <span className="inline-flex items-center gap-1 shrink-0">
      {canPlan(task) && (
        <>
          <button type="button" onClick={() => move(task, 'up')} className="text-ink3 hover:text-ink text-xs px-0.5" title={t('board.jira.moveUp', undefined, 'Backlog sırasında yukarı al')}>▲</button>
          <button type="button" onClick={() => move(task, 'down')} className="text-ink3 hover:text-ink text-xs px-0.5" title={t('board.jira.moveDown', undefined, 'Backlog sırasında aşağı al')}>▼</button>
        </>
      )}
      {sprintOf(task) && canExpedite(task) && (
        <button type="button" onClick={() => expediteNow(task)} className="text-[11px] text-warn hover:underline whitespace-nowrap" title={t('board.jira.expediteBtnTitle', undefined, 'Sprint kuyruğunda beklemesin: geçerli adımdan hemen sonra yapılsın')}>⚡ {t('board.jira.expediteBtn', undefined, 'Önce yap')}</button>
      )}
      <button type="button" onClick={() => { setEditErr(''); setEditing(task); }} className="text-[11px] text-ac hover:underline" title={t('board.jira.editTitle', undefined, 'Görevi düzenle / sprint ata')}>✎ {t('board.jira.editBtn', undefined, 'Düzenle')}</button>
    </span>
  );
  const renderPlanControls = (task: JiraIssue) => (
    <span className="inline-flex items-center gap-1 shrink-0">{renderPlanBadge(task)}{renderPlanActions(task)}</span>
  );

  // --- Sprint hiyerarşisi: Sprint -> Hikâye (epik yolu) -> Görev ---
  const renderSprintRow = (task: JiraIssue) => (
    <div key={task.id} data-issue-id={task.id} className={`flex items-center justify-between gap-3 p-1.5 rounded transition ${isActive(task) ? 'bg-warnd/60 border border-warn/60 ring-1 ring-warn/30' : 'hover:bg-panel/80'} ${passiveCls(task)}`}>
      <div className="flex items-center gap-2 min-w-0">
        <button onClick={() => toggleSelect(task.id)}>
          {selectedIds.has(task.id) ? <CheckSquare className="w-4 h-4 text-ac" /> : <Square className="w-4 h-4 text-ink3" />}
        </button>
        {idBadge(task)}
        <span className="text-xs font-mono font-bold text-ink2 shrink-0" title={t('board.jira.uniqueId', { id: task.id }, 'Benzersiz kimlik: {id}')}>{task.key || task.id}</span>
        {task.task_key && <span className="text-[9px] font-mono px-1 py-0.5 rounded bg-acd text-ac border border-ac/40 shrink-0">⚙ {task.task_key}</span>}
        <span className="text-xs text-ink truncate" title={task.title}>{task.title}</span>{queueBadge(task.id)}
      </div>
      <div className="flex items-center gap-2 shrink-0">
        {renderRunControls(task.order, true)}
        {onInspectTask && (
          <button onClick={() => onInspectTask(task.order, task)} className="text-[11px] text-ac hover:underline flex items-center gap-1">
            <FileText className="w-3 h-3" /><span>{t('board.jira.inspect', undefined, 'İncele')}</span>
          </button>
        )}
        {renderPlanControls(task)}
        {getAssigneeBadge(task.assignee)}
        {renderStatusSelect(task)}
      </div>
    </div>
  );

  const renderSprintGroup = (key: string, title: string, subtitle: string, tone: string, items: JiraIssue[], showProgress: boolean, blocked?: { reason: string; since?: string; detail?: string } | null, sprintNo?: number) => {
    const byId = new Map(issues.map(i => [i.id, i] as [string, JiraIssue]));
    const done = items.filter(isDone).length;
    const pct = items.length ? Math.round((done / items.length) * 100) : 0;
    const collapsed = collapsedNodes.has(key);
    // Görevleri hikâyelerine göre kümele; epik yolu başlıkta
    const groups = new Map<string, JiraIssue[]>();
    items.forEach(t => {
      const story = t.parent_id ? byId.get(t.parent_id) : undefined;
      const k = story ? story.id : '__none__';
      groups.set(k, [...(groups.get(k) || []), t]);
    });
    return (
      <div key={key} className={`border ${tone} bg-panel/70 rounded-2xl overflow-hidden shadow-xl`}>
        <button onClick={() => toggleCollapse(key)} className="w-full p-4 flex items-center gap-3 text-left bg-sunk/40 border-b border-line">
          {collapsed ? <ChevronRight className="w-5 h-5 text-ac" /> : <ChevronDown className="w-5 h-5 text-ac" />}
          <div className="min-w-0 flex-1">
            <div className="text-sm font-bold text-ink">{title}</div>
            {subtitle && <div className="text-xs text-ink3 truncate" title={subtitle}>{subtitle}</div>}
          </div>
          {showProgress && (
            <div className="flex items-center gap-2 text-[11px] font-mono text-ink2 shrink-0">
              <div className="w-32 h-2 bg-sunk rounded-full overflow-hidden border border-line"><div className="h-full bg-ok" style={{ width: `${pct}%` }} /></div>
              {done}/{items.length}
            </div>
          )}
          {!showProgress && <span className="text-[11px] font-mono text-ink2 shrink-0">{t('board.jira.itemsCount', { n: items.length }, '{n} iş')}</span>}
        </button>
        {blocked && (() => {
          const bi = BLOCK_INFO[blocked.reason]
            ? { title: t(`board.jira.block.${blocked.reason}.title`, undefined, BLOCK_INFO[blocked.reason].title), hint: t(`board.jira.block.${blocked.reason}.hint`, undefined, BLOCK_INFO[blocked.reason].hint) }
            : { title: blocked.reason, hint: '' };
          return (
            <div className="px-4 py-2.5 border-b border-err/40 bg-errd/40 text-xs flex items-start justify-between gap-3 flex-wrap">
              <div className="min-w-0 space-y-0.5">
                <div className="text-err"><span className="font-semibold">{t('board.jira.blockedPrefix', undefined, 'Engel:')} {bi.title}</span>{blocked.since ? <span className="text-ink3"> · {new Date(blocked.since).toLocaleString()}</span> : null}</div>
                {blocked.detail && <div className="text-ink2">{blocked.detail}</div>}
                {bi.hint && <div className="text-ink3">{bi.hint}</div>}
              </div>
              {jira && sprintNo ? (
                <div className="shrink-0 flex items-center gap-2">
                  {blocked.reason === 'PRECONDITION_LOST' && (
                    <button type="button" disabled={!!(blocked as { review_planned?: unknown }).review_planned}
                      onClick={async () => {
                        const r = await fetch(`/api/sprints/${sprintNo}/plan-review`, { method: 'POST' });
                        const j = await r.json().catch(() => ({}));
                        notify(r.ok ? t('board.jira.planReviewDone', { order: j.order }, 'Mimar gözden geçirmesi koşuya eklendi (adım #{order}). Koşu sürünce çalışır, bitince sprint kapanır.') : (j.error || t('board.jira.couldNotAdd', undefined, 'Eklenemedi')));
                      }}
                      className="px-2 py-1 rounded border border-ac/40 text-ac bg-acd/40 hover:bg-acd/70 disabled:opacity-50"
                      title={t('board.jira.reviewPlannedTitle', undefined, 'Eksik ARCHITECT gözden geçirmesini koşuya ekler; adım bitince sprint kendiliğinden kapanır')}>
                      {(blocked as { review_planned?: unknown }).review_planned ? t('board.jira.reviewPlanned', undefined, 'Gözden geçirme planlandı') : t('board.jira.planReview', undefined, 'Mimar gözden geçirmesini planla')}
                    </button>
                  )}
                  <button type="button" onClick={async () => { if (await confirmDialog(t('board.jira.unblockConfirm', { n: sprintNo }, 'Sprint {n} engeli kaldırılsın mı? Engel nedeni çözülmediyse sprint yeniden engellenir.'))) jira.sprintUnblock(sprintNo); }}
                    className="px-2 py-1 rounded border border-ok/40 text-ok bg-okd/40 hover:bg-okd/70" title={t('board.jira.unblockTitle', undefined, 'Engel nedeni çözüldüyse sprinti sürdür')}>{t('board.jira.unblock', undefined, 'Engeli kaldır')}</button>
                </div>
              ) : null}
            </div>
          );
        })()}
        {!collapsed && (
          <div className="p-3 space-y-3">
            {items.length === 0 && <div className="text-xs italic text-ink3 px-2">{t('board.jira.emptyGroup', undefined, 'Bu grupta (filtreye uyan) iş yok.')}</div>}
            {Array.from(groups.entries()).map(([sid, tasks]) => {
              const story = byId.get(sid);
              const epic = story?.parent_id ? byId.get(story.parent_id) : undefined;
              return (
                <div key={sid} className="border border-line rounded-xl p-2">
                  <div className="text-[11px] font-semibold text-ink2 mb-1 flex items-center gap-1.5 flex-wrap">
                    {epic && <>{keyLink(epic, "font-mono text-ac")}<span className="text-ink3">{epic.title}</span><span className="text-ink3">›</span></>}
                    {story ? <>{keyLink(story, "font-mono text-ok")}<span>{story.title}</span></> : <span>{t('board.jira.generalTasks', undefined, 'Genel proje görevleri')}</span>}
                  </div>
                  {tasks.sort((a, b) => a.order - b.order).map(renderSprintRow)}
                </div>
              );
            })}
          </div>
        )}
      </div>
    );
  };

  const renderSprintView = () => {
    const work = filteredIssues.filter(i => i.issue_type === 'TASK' || i.issue_type === 'BUG');
    const sprintNumbers = Array.from(new Set([...sprints.map(x => x.sprint_number), ...work.map(i => i.planned_sprint || 0).filter(Boolean) as number[]])).sort((a, b) => a - b);
    const blocks = sprintNumbers.map(n => {
      const info = sprints.find(x => x.sprint_number === n);
      const inSprint = work.filter(i => i.sprint === n);
      const pinned = work.filter(i => !i.sprint && i.planned_sprint === n);
      const items = [...inSprint, ...pinned];
      const title = `Sprint ${n}${info ? ` · ${info.status}` : ` · ${t('board.jira.planning', undefined, 'planlanıyor')}`}`;
      return renderSprintGroup(`sprint:${n}`, title, info?.goal || (pinned.length ? t('board.jira.pinnedGoal', undefined, 'Yöneticinin bu sprinte sabitlediği işler') : ''), info?.status === 'BLOCKED' ? 'border-err/50' : info?.status === 'IN_PROGRESS' ? 'border-warn/60' : 'border-ac/40', items, true, info?.status === 'BLOCKED' ? info?.blocked : null, n);
    });
    const backlog = work.filter(i => !i.sprint && !i.planned_sprint).sort((a, b) => (a.manual_rank ?? 1e9) - (b.manual_rank ?? 1e9) || a.order - b.order);
    return (
      <div className="flex-1 p-5 overflow-y-auto space-y-4">
        {jira && <SprintPanel jira={jira} version={sprintVersion} issuesVersion={allIssues.length * 7 + allIssues.filter(i => i.status === 'DONE').length} onOpenIssue={setDetailId} />}
        {blocks}
        {renderSprintGroup('sprint:backlog', t('board.jira.backlogGroup', undefined, 'Backlog (sprinte atanmamış)'), t('board.jira.backlogGroupSub', undefined, 'Sıra: yönetici sırası, sonra öncelik. ▲▼ ile sırayı değiştir; ✎ Düzenle ile sprinte sabitle.'), 'border-line2', backlog, false)}
      </div>
    );
  };

  const STATUS_PILL: Record<string, { label: string; cls: string }> = {
    BACKLOG: { label: 'Backlog', cls: 'bg-sunk text-ink3 border-line' },
    SELECTED_FOR_DEV: { label: t('board.jira.pill.SELECTED_FOR_DEV', undefined, 'Hazır'), cls: 'bg-infod text-info border-info/40' },
    IN_PROGRESS: { label: t('board.jira.pill.IN_PROGRESS', undefined, 'Devam ediyor'), cls: 'bg-warnd text-warn border-warn/40' },
    IN_REVIEW: { label: t('board.jira.pill.IN_REVIEW', undefined, 'İncelemede'), cls: 'bg-acd text-ac border-ac/40' },
    DONE: { label: t('board.jira.pill.DONE', undefined, 'Tamamlandı'), cls: 'bg-okd text-ok border-ok/40' },
  };
  /** Durum: renkli hap görünümlü seçici (sabit genişlik: satırlarda aynı hizada) */
  const renderStatusSelect = (item: JiraIssue) => (
    <select
      value={item.status}
      onChange={(e) => onUpdateStatus(item.id, e.target.value as JiraIssueStatus)}
      aria-label={t('board.jira.statusOf', { key: item.key || item.id }, '{key} durumu')}
      title={t('board.jira.changeStatus', undefined, 'Durumu değiştir')}
      className={`w-[124px] shrink-0 appearance-none text-center text-[11px] font-medium rounded-full border px-2 py-0.5 outline-none cursor-pointer ${(STATUS_PILL[item.status] || STATUS_PILL.BACKLOG).cls}`}
    >
      {COLUMNS.map(col => <option key={col.key} value={col.key}>{STATUS_PILL[col.key]?.label || colTitle(col.key)}</option>)}
    </select>
  );

  const getAssigneeBadge = (assignee: string) => <span className="w-[112px] shrink-0 inline-flex justify-start">{assigneeBadgeRaw(assignee)}</span>;
  const assigneeBadgeRaw = (assignee: string) => {
    switch (assignee) {
      case 'PM':
        return <span className="bg-acd text-ac border border-ac/40 text-[10px] font-mono px-2 py-0.5 rounded-full">PM Lead</span>;
      case 'ARCHITECT':
        return <span className="bg-acd text-ac border border-ac/40 text-[10px] font-mono px-2 py-0.5 rounded-full">Architect</span>;
      case 'BACKEND_DEV':
        return <span className="bg-acd text-ac border border-ac/40 text-[10px] font-mono px-2 py-0.5 rounded-full">Senior Backend</span>;
      case 'DESIGNER':
        return <span className="bg-acd text-ac border border-ac/40 text-[10px] font-mono px-2 py-0.5 rounded-full">Designer</span>;
      case 'FRONTEND_DEV':
        return <span className="bg-infod text-info border border-info/40 text-[10px] font-mono px-2 py-0.5 rounded-full">Senior Frontend</span>;
      case 'QA':
        return <span className="bg-warnd text-warn border border-warn/40 text-[10px] font-mono px-2 py-0.5 rounded-full">Lead QA</span>;
      case 'E2E_TESTER':
        return <span className="bg-infod text-info border border-info/40 text-[10px] font-mono px-2 py-0.5 rounded-full">Playwright E2E</span>;
      case 'DEVOPS':
        return <span className="bg-okd text-ok border border-ok/40 text-[10px] font-mono px-2 py-0.5 rounded-full">DevOps SRE</span>;
      default:
        return <span className="bg-panel2 text-ink2 border border-line2 text-[10px] font-mono px-2 py-0.5 rounded-full">{assignee}</span>;
    }
  };

  const getTypeBadge = (type: string) => {
    const base = 'inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-medium whitespace-nowrap shrink-0 ';
    switch (type) {
      case 'EPIC': return <span className={base + 'bg-acd text-ac'}>EPIC</span>;
      case 'STORY':
      case 'FEATURE': return <span className={base + 'bg-okd text-ok'}>STORY</span>;
      case 'BUG': return <span className={base + 'bg-errd text-err'}>BUG</span>;
      default: return <span className={base + 'bg-sunk text-ink2'}>TASK</span>;
    }
  };

  return (
    <div className="flex flex-col flex-1 min-h-0 bg-panel text-ink rounded-xl border border-line overflow-hidden">
      {/* Üst Yönetim Çubuğu: başlık, görünüm sekmeleri, arama ve tek birincil eylem */}
      <div className="px-4 py-2.5 bg-panel/90 border-b border-line flex flex-wrap items-center gap-x-3 gap-y-2">
        <div className="flex items-center gap-2 min-w-0">
          <h2 className="text-sm font-bold text-ink whitespace-nowrap">Jira Board</h2>
          <span className="text-[10px] bg-sunk text-ink2 border border-line px-2 py-0.5 rounded-full font-mono whitespace-nowrap" title={t('board.jira.totalItems', undefined, 'Toplam iş sayısı')}>{t('board.jira.itemsCount', { n: issues.length }, '{n} iş')}</span>
          {projectName && <span className="hidden xl:inline text-[10px] font-mono text-ink3 whitespace-nowrap" title={t('board.jira.projectTitle', undefined, 'Proje')}>{projectName}</span>}
        </div>

        <div className="flex items-center bg-sunk p-0.5 rounded-lg border border-line" role="tablist" aria-label={t('board.jira.viewLabel', undefined, 'Görünüm')}>
          {(['TREE', 'LIST', 'SPRINT', 'KANBAN'] as const).map(m => (
            <button
              key={m}
              role="tab"
              aria-selected={viewMode === m}
              onClick={() => setViewMode(m)}
              title={`${t(`board.jira.view.${m}.full`, undefined, VIEW_META[m].full)}: ${t(`board.jira.view.${m}.hint`, undefined, VIEW_META[m].hint)}`}
              className={`flex items-center gap-1.5 px-2.5 py-1 rounded-md text-[11px] font-semibold whitespace-nowrap transition ${viewMode === m ? 'bg-panel text-ink shadow-panel border border-line/60' : 'text-ink3 hover:text-ink'}`}
            >
              {VIEW_META[m].icon}<span>{t(`board.jira.view.${m}.label`, undefined, VIEW_META[m].label)}</span>
            </button>
          ))}
        </div>

        {queryErr && <span className="text-err text-[11px]" title={queryErr}>{t('board.jira.queryError', undefined, 'sorgu hatası:')} {queryErr.slice(0, 50)}</span>}

        <div className="flex flex-wrap items-center gap-1.5 ml-auto">
          {jira && (
            <Dropdown
              label={<><Bookmark className="w-3.5 h-3.5" /><span>{t('board.jira.filters', undefined, 'Süzgeçler')}</span></>}
              badge={savedFilters.length > 0 ? <span className="font-mono text-[10px] opacity-80">{savedFilters.length}</span> : undefined}
              active={showDeleted || savedFilters.some(f => f.q === filterQuery)}
              align="right"
              panelClass="w-72"
              title={t('board.jira.filtersTitle', undefined, 'Kayıtlı süzgeçler ve silinmiş maddeler')}
            >
              {(close) => (
                <div className="space-y-1 text-[11px]">
                  <div className="px-2 pt-1 text-[10px] font-mono uppercase tracking-wider text-ink3">{t('board.jira.savedFilters', undefined, 'Kayıtlı süzgeçler')}</div>
                  {savedFilters.length === 0 && <div className="px-2 py-1 text-ink3">{t('board.jira.noSavedFilters', undefined, 'Kayıtlı süzgeç yok. Bir sorgu yazıp kaydedin.')}</div>}
                  {savedFilters.map(f => (
                    <div key={f.name} className="flex items-center gap-1">
                      <button className="flex-1 min-w-0 text-left px-2 py-1 rounded hover:bg-sunk truncate" title={f.q} onClick={() => { setFilterQuery(f.q); close(); }}>{f.name}</button>
                      <button
                        className="px-1.5 py-1 text-ink3 hover:text-err"
                        title={t('board.jira.deleteFilter', undefined, 'Süzgeci sil')}
                        onClick={async () => { if (jira && await confirmDialog(t('board.jira.deleteFilterConfirm', { name: f.name }, '"{name}" silinsin mi?'))) setSavedFilters(await jira.deleteFilter(f.name)); }}
                      ><X className="w-3 h-3" /></button>
                    </div>
                  ))}
                  {isJql(filterQuery) && !queryErr && (
                    <button
                      className="w-full text-left px-2 py-1 rounded text-ac hover:bg-sunk"
                      onClick={async () => { const name = await promptDialog(t('board.jira.filterName', undefined, 'Süzgeç adı:'), ''); if (name && jira) { try { setSavedFilters(await jira.saveFilter(name, filterQuery)); } catch (e) { notify((e as Error).message); } } }}
                    >{t('board.jira.saveQuery', undefined, '+ Mevcut sorguyu kaydet')}</button>
                  )}
                  <div className="border-t border-line mt-1 pt-1">
                    <label className="flex items-center gap-2 px-2 py-1 cursor-pointer text-ink2" title={t('board.jira.softDeleted', undefined, 'Yumuşak silinmiş maddeler (geri alınabilir)')}>
                      <input type="checkbox" checked={showDeleted} onChange={e => setShowDeleted(e.target.checked)} /> {t('board.jira.showDeleted', { n: deletedCount }, 'Silinenleri göster ({n})')}
                    </label>
                  </div>
                </div>
              )}
            </Dropdown>
          )}
          <Dropdown
            label={<><CheckSquare className="w-3.5 h-3.5" /><span>{t('board.jira.selection', undefined, 'Seçim')}</span></>}
            badge={<span className="font-mono text-[10px] opacity-80">{selectedIds.size}/{issues.length}</span>}
            active={bulkOpen}
            align="right"
            panelClass="w-60"
            title={t('board.jira.selectionTitle', undefined, 'Çalıştırılacak ve toplu işlem yapılacak maddelerin seçimi')}
          >
            {(close) => (
              <>
                <DropdownItem label={t('board.jira.selectAll', undefined, 'Tümünü seç')} onClick={() => { handleSelectAll(); close(); }} />
                <DropdownItem label={t('board.jira.clearSelection', undefined, 'Seçimi temizle')} onClick={() => { handleDeselectAll(); close(); }} />
                <DropdownItem label={t('board.jira.main110', undefined, 'Ana maddeler (1-10)')} hint={t('board.jira.main110Hint', undefined, "1'den 10'a kadar tüm ana maddeler")} onClick={() => { handleSelect1To10(); close(); }} />
                <DropdownItem label={t('board.jira.testsOnly', undefined, 'Yalnızca testler')} hint={t('board.jira.testsOnlyHint', undefined, 'Madde 6 (QA) ve Madde 7 (Playwright)')} onClick={() => { handleSelectTestsOnly(); close(); }} />
                {jira && <DropdownItem label={bulkOpen ? t('board.jira.bulkHide', undefined, 'Toplu işlem panelini gizle') : t('board.jira.bulkShow', undefined, 'Toplu işlem paneli…')} hint={t('board.jira.bulkHint', undefined, 'Seçili maddelerin durumunu, sprintini, önceliğini, sorumlusunu ya da etiketini topluca değiştir')} active={bulkOpen} onClick={() => { setBulkOpen(v => !v); close(); }} />}
              </>
            )}
          </Dropdown>

          <Dropdown
            label={<span>{t('board.jira.more', undefined, 'Daha fazla ⋯')}</span>}
            align="right"
            panelClass="w-64"
            title={t('board.jira.moreTitle', undefined, 'Şartname, dökümanlar ve onay modu')}
          >
            {(close) => (
              <>
                {onOpenSpecVault && <DropdownItem icon={<FolderPlus className="w-3.5 h-3.5 text-ac" />} label={t('board.jira.uploadSpec', undefined, 'Şartname yükle')} hint={t('board.jira.uploadSpecHint', undefined, 'Müşteri şartnamesi ve dosyalarını yükleyip otomatik Jira görevlerine dönüştür')} onClick={() => { onOpenSpecVault(); close(); }} />}
                <DropdownItem icon={<BookOpen className="w-3.5 h-3.5 text-ac" />} label={t('board.jira.docs', undefined, 'Dökümanlar')} hint={t('board.jira.docsHint', undefined, 'Projenin dökümanları, test dosyaları ve senaryoları')} onClick={() => { openDocs(); close(); }} />
                <div className="my-1 border-t border-line" />
                <div className="px-2.5 pt-1 text-[10px] font-mono uppercase tracking-wider text-ink3">{t('board.jira.approvalMode', undefined, 'Onay modu')}</div>
                <DropdownItem label={t('board.jira.approvalOn', undefined, 'Onaylı mod')} hint={t('board.jira.approvalOnHint', undefined, 'Her adım yönetici onayını bekler')} active={stepByStep}
                  onClick={() => { setStepByStep(true); if (onToggleStepMode) onToggleStepMode(true); close(); }} />
                <DropdownItem label={t('board.jira.auto', undefined, 'Otomatik')} hint={t('board.jira.autoHint', undefined, 'Hiç durma')} active={!stepByStep}
                  onClick={() => { setStepByStep(false); if (onToggleStepMode) onToggleStepMode(false); close(); }} />
                {jira && (
                  <>
                    <div className="my-1 border-t border-line" />
                    <label className="flex items-center gap-2 px-2.5 py-1.5 cursor-pointer text-[11px] text-ink2" title={t('board.jira.softDeleted', undefined, 'Yumuşak silinmiş maddeler (geri alınabilir)')}>
                      <input type="checkbox" checked={showDeleted} onChange={e => setShowDeleted(e.target.checked)} /> {t('board.jira.showDeleted', { n: deletedCount }, 'Silinenleri göster ({n})')}
                    </label>
                  </>
                )}
              </>
            )}
          </Dropdown>

          {sprintMode ? (
            <span
              className="hidden min-[1900px]:inline-block px-2.5 py-1.5 rounded-lg border border-line bg-sunk text-ink3 text-[11px] whitespace-nowrap"
              title={t('board.jira.sprintModeTitle', undefined, 'Sprint kipinde koşu bir not yüklemesiyle başlar ve Claude oturumu adımları çeker; sabit adım listesiyle koşu başlatılmaz')}
            >
              {t('board.jira.sprintModeText', undefined, 'Sprint kipi · koşuyu Claude çeker')}
            </span>
          ) : (
            <>
              <button
                onClick={handleRunTestsOnly}
                disabled={isExecuting}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold shadow-panel transition-all bg-ac hover:opacity-90 text-onac border border-ac/30 whitespace-nowrap disabled:opacity-50"
              >
                <Play className="w-3 h-3 fill-current" />
                {t('menu.runTestsOnly')}
              </button>
              <button
                onClick={handleRunSelected}
                disabled={isExecuting || selectedIds.size === 0}
                className={`flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-semibold shadow-lg transition-all whitespace-nowrap ${
                  isExecuting
                    ? 'bg-warn/50 text-warn cursor-not-allowed border border-warn/50 animate-pulse'
                    : 'bg-ac hover:opacity-90 text-onac border border-ac/30'
                }`}
              >
                <Play className={`w-3.5 h-3.5 ${isExecuting ? 'animate-spin' : 'fill-current'}`} />
                {isExecuting ? t('topbar.executing') : `${t('jira.batchRun')} (${selectedIds.size})`}
              </button>
            </>
          )}

          <button
            onClick={() => setIsAddModalOpen(true)}
            className="px-3 py-1.5 bg-ac text-onac border border-ac/30 rounded-lg text-xs font-semibold transition flex items-center gap-1.5 whitespace-nowrap hover:opacity-90"
            title={t('jira.newIssue')}
          >
            <PlusCircle className="w-3.5 h-3.5" />
            <span>{t('jira.newIssue')}</span>
          </button>
        </div>
      </div>

      {/* Toplu işlem çubuğu: yalnızca seçim daraltılınca ya da panel açılınca görünür */}
      {jira && (bulkOpen || (selectedIds.size > 0 && selectedIds.size < issues.length)) && (
        <div className="px-4 py-2 border-b border-line bg-acd/30 flex flex-wrap items-center gap-2">
          <span className="text-[11px] font-semibold text-ac whitespace-nowrap">{t('board.jira.bulk', undefined, 'Toplu işlem')}</span>
                <div className="flex flex-wrap items-center gap-2 text-[11px]">
                  <div className={selectedIds.size === issues.length ? 'text-warn' : 'text-ink2'}>
                    {selectedIds.size === 0
                      ? t('board.jira.noneSelected', undefined, 'Madde seçili değil; Seçim menüsünden seçin.')
                      : selectedIds.size === issues.length
                        ? t('board.jira.allSelected', { n: selectedIds.size }, 'Tüm maddeler seçili ({n}). Önce Seçim menüsünden ya da satırlardan daraltın.')
                        : t('board.jira.nSelected', { n: selectedIds.size }, '{n} madde seçili.')}
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    <select value="" onChange={e => { if (e.target.value) runBulk('status', e.target.value); }} className="bg-sunk border border-line rounded-lg px-2 py-1 text-ink2" title={t('board.jira.bulkStatusTitle', undefined, 'Durumu topluca değiştir')}>
                      <option value="">{t('board.jira.statusEllipsis', undefined, 'Durum…')}</option>
                      {COLUMNS.map(c => <option key={c.key} value={c.key}>{colShort(c.key)}</option>)}
                    </select>
                    <select value="" onChange={e => { if (e.target.value) runBulk('sprint', e.target.value === 'backlog' ? null : Number(e.target.value)); }} className="bg-sunk border border-line rounded-lg px-2 py-1 text-ink2" title={t('board.jira.pinTitle', undefined, 'Sprinte sabitle (yalnızca backlog işleri)')}>
                      <option value="">{t('board.jira.sprintEllipsis', undefined, 'Sprint…')}</option>
                      <option value="backlog">Backlog</option>
                      {Array.from({ length: Math.max(3, ...sprints.map(x => x.sprint_number + 1)) }, (_, k) => k + 1).map(n => <option key={n} value={n}>Sprint {n}</option>)}
                    </select>
                    <select value="" onChange={e => { if (e.target.value) runBulk('priority', e.target.value); }} className="bg-sunk border border-line rounded-lg px-2 py-1 text-ink2">
                      <option value="">{t('board.jira.priorityEllipsis', undefined, 'Öncelik…')}</option>
                      {['P0', 'P1', 'P2'].map(p => <option key={p} value={p}>{p}</option>)}
                    </select>
                    <select value="" onChange={e => { if (e.target.value) runBulk('assignee', e.target.value); }} className="bg-sunk border border-line rounded-lg px-2 py-1 text-ink2">
                      <option value="">{t('board.jira.assigneeEllipsis', undefined, 'Sorumlu…')}</option>
                      {Array.from(new Set(allIssues.map(i => i.assignee))).map(a => <option key={a} value={a}>{a}</option>)}
                    </select>
                  </div>
                  <div className="flex items-center gap-1">
                    <input value={bulkLabel} onChange={e => setBulkLabel(e.target.value)} placeholder={t('board.jira.labelPh', undefined, 'etiket')} className="bg-sunk border border-line rounded-lg px-2 py-1 text-ink flex-1 min-w-0" />
                    <button disabled={!bulkLabel.trim()} onClick={() => runBulk('labels_add', bulkLabel.trim())} className="px-2 py-1 rounded border border-line text-ink2 hover:text-ink disabled:opacity-50 whitespace-nowrap">{t('board.jira.addLabel', undefined, '+ etiket')}</button>
                    <button disabled={!bulkLabel.trim()} onClick={() => runBulk('labels_remove', bulkLabel.trim())} className="px-2 py-1 rounded border border-line text-ink2 hover:text-ink disabled:opacity-50 whitespace-nowrap">{t('board.jira.removeLabel', undefined, '− etiket')}</button>
                  </div>
                  <div className="flex items-center gap-2">
                    <button
                      onClick={async () => {
                        if (selectedIds.size === issues.length && !await confirmDialog(t('board.jira.deleteAllConfirm', { n: selectedIds.size }, 'TÜM maddeler ({n}) silinecek. Emin misiniz?'))) return;
                        const r = await promptDialog(t('board.jira.deleteNPrompt', { n: selectedIds.size }, '{n} madde silinsin mi? Neden (isteğe bağlı):'), '');
                        if (r !== null) runBulk('delete', r);
                      }}
                      className="px-2 py-1 rounded border border-err/40 text-err hover:bg-errd/40"
                    >{t('board.jira.delete', undefined, 'Sil')}</button>
                    <button onClick={() => runBulk('restore')} className="px-2 py-1 rounded border border-line text-ink2 hover:text-ink">{t('board.issue.restore', undefined, 'Geri al')}</button>
                  </div>
                  {bulkMsg && <div className={`font-mono ${bulkMsg.startsWith('⚠') ? 'text-err' : 'text-ink3'}`}>{bulkMsg}</div>}
                </div>
          <button onClick={() => { handleDeselectAll(); setBulkOpen(false); }} className="ml-auto text-[11px] text-ink3 hover:text-ink whitespace-nowrap">{t('board.jira.clearAndClose', undefined, 'Seçimi temizle ve kapat')}</button>
        </div>
      )}

      {/* İLERLEME + FİLTRE ÇUBUĞU */}
      <div className="px-4 py-2 border-b border-line bg-panel/60 flex items-center gap-2 text-[11px] overflow-x-auto whitespace-nowrap">
        <div className="flex items-center gap-2 shrink-0" title={t('board.jira.progressTitle', { done: doneCount, total: workItems.length, pct: donePct }, 'İlerleme: {done}/{total} iş tamamlandı (%{pct})')}>
          <div className="w-20 h-1.5 bg-sunk rounded-full overflow-hidden border border-line">
            <div className="h-full bg-ok transition-all" style={{ width: `${donePct}%` }} />
          </div>
          <span className="font-mono text-ink2">{doneCount}/{workItems.length} · %{donePct}</span>
        </div>
        {([['ALL', t('board.jira.all', undefined, 'Tümü'), workItems.length], ...COLUMNS.map(c => [c.key, colShort(c.key), statusCounts[c.key] || 0])] as [string, string, number][]).map(([key, label, n]) => (
          <button
            key={key}
            onClick={() => setFilterStatus(key as JiraIssueStatus | 'ALL')}
            aria-pressed={filterStatus === key}
            className={`px-2.5 py-1 rounded-full border transition whitespace-nowrap ${filterStatus === key ? 'bg-ink text-bg border-ink' : 'bg-panel text-ink2 border-line hover:border-line2'}`}
          >
            {label} <span className="font-mono opacity-80">{n}</span>
          </button>
        ))}
        <span className="flex-1" />
        <label className="flex items-center gap-1.5 shrink-0">
          <span className="font-semibold text-ink">Sprint</span>
          <select
            value={String(filterSprint)}
            onChange={(e) => { const v = e.target.value; setFilterSprint(v === 'ALL' || v === 'BACKLOG' ? v : Number(v)); }}
            className="bg-panel border border-line rounded-lg px-2 py-1 text-ink2 max-w-[200px]"
            title={t('board.jira.sprintFilterTitle', undefined, 'Sprint süzgeci')}
          >
            <option value="ALL">{t('board.jira.all', undefined, 'Tümü')}</option>
            <option value="BACKLOG">{t('board.jira.backlogUnassigned', undefined, 'Backlog (atanmamış)')}</option>
            {sprints.map(sp => (
              <option key={sp.sprint_number} value={String(sp.sprint_number)}>
                Sprint {sp.sprint_number} · {sp.status} {sp.completed_issue_ids?.length || 0}/{sp.committed_issue_ids?.length || 0}
              </option>
            ))}
          </select>
        </label>
        <select
          value={filterAssignee}
          onChange={(e) => setFilterAssignee(e.target.value)}
          className="bg-panel border border-line rounded-lg px-2 py-1 text-ink2 shrink-0"
          title={t('board.jira.roleFilterTitle', undefined, 'Role göre filtrele')}
          aria-label={t('board.jira.roleFilterAria', undefined, 'Rol süzgeci')}
        >
          <option value="ALL">{t('board.jira.allRoles', undefined, 'Tüm roller')}</option>
          {Array.from(new Set(issues.map(i => i.assignee))).map(a => <option key={a} value={a}>{a}</option>)}
        </select>
        <select
          value={filterWork}
          onChange={(e) => setFilterWork(e.target.value)}
          className="bg-panel border border-line rounded-lg px-2 py-1 text-ink2 shrink-0"
          title={t('board.jira.workFilterTitle', undefined, 'İş türüne göre filtrele (Tasarım, Frontend, Backend...)')}
          aria-label={t('board.jira.workFilterAria', undefined, 'İş türü süzgeci')}
        >
          <option value="ALL">{t('board.jira.allWork', undefined, 'Tüm iş türleri')}</option>
          {Array.from(new Set(issues.map(i => i.work_type).filter(Boolean) as string[])).sort().map(w => <option key={w} value={w}>{w}</option>)}
        </select>
        <button type="button" onClick={() => setPref({ hideDone: !prefs.hideDone })} aria-pressed={prefs.hideDone}
          title={t('board.jira.hideDoneTitle', undefined, 'Tamamlanan işleri listeden gizle')}
          className={`px-2.5 py-1 rounded-full border shrink-0 transition ${prefs.hideDone ? 'bg-ink text-bg border-ink' : 'bg-panel text-ink2 border-line hover:border-line2'}`}>
          {t('board.jira.hideDone', undefined, 'Bitenleri gizle')}
        </button>
        <button type="button" onClick={() => setPref({ inRun: !prefs.inRun })} aria-pressed={prefs.inRun} disabled={runIssueIds.size === 0}
          title={t('board.jira.inRunTitle', undefined, 'Yalnızca çalışan koşunun adımlarındaki işler')}
          className={`px-2.5 py-1 rounded-full border shrink-0 transition disabled:opacity-40 ${prefs.inRun ? 'bg-ink text-bg border-ink' : 'bg-panel text-ink2 border-line hover:border-line2'}`}>
          {t('board.jira.inRun', undefined, 'Bu koşu')}
        </button>
        {filterActive && (
          <button
            onClick={() => { setFilterStatus('ALL'); setFilterAssignee('ALL'); setFilterQuery(''); setFilterSprint('ALL'); setFilterWork('ALL'); setPref({ hideDone: false, inRun: false }); }}
            className="px-2 py-1 rounded text-ink3 hover:text-ink flex items-center gap-1 whitespace-nowrap shrink-0"
          >
            <X className="w-3 h-3" /> {t('board.jira.clear', undefined, 'Temizle')}
          </button>
        )}
      </div>

      {/* ŞİMDİ / SIRADA şeridi: hangi iş çalışıyor, sırada hangileri var; tıklayınca ağaçta açılır */}
      {queueInfo && (queueInfo.cur || queueInfo.upcoming.length > 0) && (
        <div className="shrink-0 px-5 py-2 border-b border-line bg-panel2/50 flex items-center gap-3 text-[11px] min-w-0 whitespace-nowrap">
          {queueInfo.cur && (
            <button onClick={() => queueInfo.curIssue && revealIssue(queueInfo.curIssue.id)} title={t('board.jira.revealTitle', undefined, 'Ağaçta göster')}
              className="shrink-0 max-w-[50%] flex items-center gap-1.5 px-2.5 py-1 rounded-lg border border-warn/60 bg-warnd/60 text-ink min-w-0 hover:bg-warnd">
              <span className="w-2 h-2 rounded-full bg-warn animate-pulse shrink-0" />
              <span className="font-bold text-warn shrink-0">{t('board.jira.nowBadge', undefined, 'ŞİMDİ')}</span>
              <span className="font-mono shrink-0">#{queueInfo.cur.order}</span>
              <span className="truncate">{queueInfo.curIssue?.key ? `${queueInfo.curIssue.key} · ` : ''}{queueInfo.cur.title || queueInfo.curIssue?.title}</span>
              <span className="text-ink3 shrink-0">· {queueInfo.cur.role}</span>
            </button>
          )}
          {queueInfo.upcoming.length > 0 && <span className="shrink-0 font-bold text-ink3">{t('board.jira.nextBadge', undefined, 'SIRADA')}</span>}
          <div className="flex items-center gap-1.5 min-w-0 overflow-hidden">
            {queueInfo.upcoming.map((st, i) => (
              <button key={`${st.order}-${i}`} onClick={() => queueInfo.upIssues[i] && revealIssue(queueInfo.upIssues[i]!.id)} title={st.title || queueInfo.upIssues[i]?.title}
                className="shrink-0 truncate max-w-[230px] px-2 py-1 rounded-lg border border-line bg-panel text-ink2 hover:text-ink hover:border-line2">
                {i + 1}. <span className="font-mono">#{st.order}</span> {st.title || queueInfo.upIssues[i]?.title || st.issue_id}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* İÇERİK ALANI: 1. Hiyerarşik Ağaç (Tree) VEYA 2. Kanban Sütunları */}
      {viewMode === 'LIST' ? (
        <div className="flex-1 px-4 py-3 overflow-y-auto space-y-1">
          <div className="flex items-center justify-between text-[11px] text-ink3 pb-1">
            <span>{t('board.jira.listCount', { n: filteredIssues.filter(i => i.issue_type === 'TASK' || i.issue_type === 'BUG').length }, '{n} iş')}</span>
            <button type="button" onClick={() => setPref({ desc: !prefs.desc })} className="hover:text-ink">
              {prefs.desc ? t('board.jira.orderDesc', undefined, '↓ Sıra no: yeniden eskiye') : t('board.jira.orderAsc', undefined, '↑ Sıra no: eskiden yeniye')}
            </button>
          </div>
          {filteredIssues.filter(i => i.issue_type === 'TASK' || i.issue_type === 'BUG')
            .sort((a, b) => (prefs.desc ? b.order - a.order : a.order - b.order)).map(renderSprintRow)}
        </div>
      ) : viewMode === 'SPRINT' ? renderSprintView() : viewMode === 'TREE' ? (
        /* =========================================================================
           1. JIRA HİYERARŞİK AĞAÇ GÖRÜNÜMÜ (EPIC -> STORY -> TASK / BUG)
           ========================================================================= */
        <div className="flex-1 px-4 py-3 overflow-y-auto space-y-2">
          {hierarchicalTree.filter(t => !filterActive || t.stories.length > 0 || t.orphanTasks.length > 0).map(({ epic, stories, orphanTasks }) => {
            const isEpicCollapsed = collapsedNodes.has(epic.id);
            const isVirtual = (epic as unknown as { virtual?: boolean }).virtual === true;
            const totalChildrenCount = stories.reduce((acc, s) => acc + s.children.length + 1, 0) + orphanTasks.length;

            return (
              <div key={epic.id} data-issue-id={epic.id} className={`border-b border-line transition-colors ${isActive(epic) ? 'bg-warnd/30' : ''}`}>
                {/* EPIC BAŞLIK ÇUBUĞU */}
                <div className={`group px-4 py-2 flex items-center justify-between gap-3 ${isActive(epic) ? 'bg-warnd/70' : ''} ${passiveCls(epic)}`}>
                  <div className="flex items-center gap-3">
                    <button
                      onClick={() => toggleCollapse(epic.id)}
                      className="p-1 rounded text-ink3 opacity-60 hover:opacity-100 hover:text-ink transition"
                    >
                      {isEpicCollapsed ? <ChevronRight className="w-5 h-5" /> : <ChevronDown className="w-5 h-5" />}
                    </button>

                    {!isVirtual && <button
                      onClick={() => toggleSelect(epic.id)}
                      className={`text-ink3 hover:text-ink ${selVis}`}
                    >
                      {selectedIds.has(epic.id) ? (
                        <CheckSquare className="w-4 h-4 text-ac" />
                      ) : (
                        <Square className="w-4 h-4 text-ink3" />
                      )}
                    </button>}

                    {getTypeBadge(epic.issue_type)}

                    <div>
                      <div className="flex items-center gap-2">
                        {keyLink(epic, "text-xs font-mono font-bold text-ac")}
                        <h3 className="text-[13px] font-semibold text-ink">{epic.title}</h3>
                        {holdsBadge([epic.id, ...stories.flatMap(sc => [sc.story.id, ...sc.children.map(c => c.id)]), ...orphanTasks.map(o => o.id)])}
                      </div>
                      <p className="text-xs text-ink3 mt-0.5">{epic.description}</p>
                    </div>
                  </div>

                  <div className="flex items-center gap-3">
                    <span className="text-xs text-ink3 font-mono bg-acd/40 px-2 py-0.5 rounded border border-ac/40">
                      {t('board.jira.childCount', { n: totalChildrenCount }, '{n} Alt Öğe')}
                    </span>
                    {!isVirtual && getAssigneeBadge(epic.assignee)}
                    {!isVirtual && renderStatusSelect(epic)}
                  </div>
                </div>

                {/* EPIC İÇERİĞİ (STORIES & TASKS) */}
                {!isEpicCollapsed && (
                  <div className="divide-y divide-line/50 border-t border-line/50">
                    {/* Story / Feature'lar */}
                    {stories.map(({ story, children }) => {
                      const isStoryCollapsed = collapsedNodes.has(story.id);

                      return (
                        <div key={story.id} data-issue-id={story.id} className={`ml-8 transition-colors ${isActive(story) ? 'bg-warnd/40' : ''}`}>
                          {/* STORY BAŞLIK ÇUBUĞU */}
                          <div className={`group px-2.5 py-1.5 flex items-center justify-between gap-3 ${passiveCls(story)}`}>
                            <div className="flex items-center gap-2.5">
                              <button
                                onClick={() => toggleCollapse(story.id)}
                                className="p-0.5 rounded text-ink3 opacity-60 hover:opacity-100 hover:text-ink transition"
                              >
                                {isStoryCollapsed ? <ChevronRight className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
                              </button>

                              <button
                                onClick={() => toggleSelect(story.id)}
                                className={`text-ink3 hover:text-ink ${selVis}`}
                              >
                                {selectedIds.has(story.id) ? (
                                  <CheckSquare className="w-4 h-4 text-ok" />
                                ) : (
                                  <Square className="w-4 h-4 text-ink3" />
                                )}
                              </button>

                              {getTypeBadge(story.issue_type)}

                              <div>
                                <div className="flex items-center gap-2">
                                  {keyLink(story, "text-xs font-mono font-bold text-ok")}
                                  <h4 className="text-xs font-semibold text-ink">{story.title}</h4>
                                  {queueBadge(story.id) || holdsBadge([story.id, ...children.map(c => c.id)])}
                                </div>
                                <span className="text-[11px] text-ink3">{/^kanıtsız/i.test(story.description || '') ? t('board.jira.uatRejected', { desc: story.description }, "İlk UAT'de PO reddetmişti — {desc}") : story.description}</span>
                              </div>
                            </div>

                            <div className="flex items-center gap-2">
                              {getAssigneeBadge(story.assignee)}
                              {renderStatusSelect(story)}
                            </div>
                          </div>

                          {/* STORY ALTINDAKİ TASK VE BUGLAR */}
                          {!isStoryCollapsed && (
                            <div className="pl-8 divide-y divide-line/40">
                              {children.length === 0 ? (
                                (story.ac_refs || []).length > 0 ? (
                                  <StoryEvidence story={story} done={isDone(story)} jira={jira} />
                                ) : (
                                  (() => {
                                    const ph = lastStepRecord(runs, story.order)?.step;
                                    return ph && ph.kind === 'phase' ? (
                                      <div className="text-ink3 text-xs py-2 pl-6">
                                        {t('board.jira.phaseA', undefined, 'Bu bir')} <b className="text-ink2">{t('board.jira.phaseB', undefined, 'faz adımıdır')}</b>{t('board.jira.phaseC', undefined, '; alt görevi yoktur, işi doğrudan')} <span className="font-mono text-ink2">{ph.role}</span> {t('board.jira.phaseD', undefined, 'ajanı bu adımda yapar')}
                                        {' '}({t('board.issue.stepN', { n: ph.order }, 'adım #{n}')}, {t('board.jira.statusLabel', undefined, 'durum:')} <span className="font-mono text-ink2">{ph.status}</span>
                                        {ph.status === 'PENDING' && isDone(story) ? ` — ${t('board.jira.phasePending', undefined, 'önceki turda bitti, yeni sprint/UAT turu için yeniden koşacak')}` : ''}).
                                      </div>
                                    ) : (
                                      <div className="text-ink3 text-xs py-2 italic pl-6">
                                        {t('board.jira.noSubtasks', undefined, 'Bu hikaye altına atanmış alt görev henüz bulunmuyor.')}
                                      </div>
                                    );
                                  })()
                                )
                              ) : (
                                children.map(task => (
                                  <div 
                                    key={task.id} 
                                    data-issue-id={task.id}
                                    className={`group flex items-center justify-between gap-3 px-2 py-1.5 rounded-md transition ${
                                      task.issue_type === 'BUG' 
                                        ? 'bg-errd/40 border border-err/30' 
                                        : isActive(task)
                                          ? 'bg-warnd/60 border border-warn/60 ring-1 ring-warn/30'
                                          : 'hover:bg-panel/60'
                                    } ${passiveCls(task)}`}
                                  >
                                    <div className="flex items-center gap-3 min-w-0 flex-1">
                                      <button
                                        onClick={() => toggleSelect(task.id)}
                                        className={`text-ink3 hover:text-ink shrink-0 ${selVis}`}
                                      >
                                        {selectedIds.has(task.id) ? (
                                          <CheckSquare className="w-4 h-4 text-ac" />
                                        ) : (
                                          <Square className="w-4 h-4 text-ink3" />
                                        )}
                                      </button>

                                      {idBadge(task)}

                                      {getTypeBadge(task.issue_type)}

                                      <div className="min-w-0 flex-1">
                                        <div className="flex items-center gap-2">
                                          <span className="text-xs font-mono text-ink3">{task.key}</span>
                                          {task.kind === 'task' && (
                                            <span className="text-[9px] font-mono px-1 py-0.5 rounded bg-acd text-ac border border-ac/40 shrink-0" title={`${t('board.jira.fromArchitect', { key: task.task_key || '' }, "Mimarın backlog'undan: {key}")}${task.depends_on?.length ? ` · ${t('board.issue.dependsOn', undefined, 'bağımlı:')} ${task.depends_on.join(', ')}` : ''}`}>
                                              ⚙ {task.task_key || 'backlog'}
                                            </span>
                                          )}
                                          <span className="text-xs font-semibold text-ink truncate">
                                            {task.title}
                                          </span>
                                          {queueBadge(task.id)}
                                        </div>

                                        {task.acceptance_criteria && task.acceptance_criteria.length > 0 && (
                                          <div className="flex items-center gap-2 text-[10px] text-ink3 mt-0.5">
                                            <CheckCircle2 className="w-3 h-3 text-ok shrink-0" />
                                            {(() => {
                                              const q = filterQuery.trim().toLowerCase();
                                              const hit = q && !queryIds ? task.acceptance_criteria.filter(c => c.toLowerCase().includes(q)) : [];
                                              const refHit = q && !queryIds ? (task.ac_refs || []).filter(r => r.toLowerCase().includes(q)) : [];
                                              if (hit.length === 0 && refHit.length > 0) {
                                                return <span className="flex flex-wrap items-center gap-1 min-w-0" title={t('board.jira.meetsCriteria', undefined, 'Bu görev şu kabul kriterlerini karşılıyor (PRD/UAT kimlikleri)')}>
                                                  {(task.ac_refs || []).map(r => <span key={r} className={`font-mono px-1 rounded border ${refHit.includes(r) ? 'bg-warnd/70 border-warn/60 text-ink font-bold' : 'border-line'}`}>{r}</span>)}
                                                  <span className="truncate">· {task.acceptance_criteria[0]}</span>
                                                  {task.acceptance_criteria.length > 1 && <span>{t('board.jira.moreCriteria', { n: task.acceptance_criteria.length - 1 }, '+{n} kriter')}</span>}
                                                </span>;
                                              }
                                              return hit.length > 0
                                                ? <span className="flex flex-col gap-0.5 min-w-0">{hit.map(c => <span key={c} className="text-ink2 bg-warnd/50 rounded px-1 truncate" title={c}>{c}</span>)}</span>
                                                : <><span className="truncate">{task.acceptance_criteria[0]}</span>
                                                  {task.acceptance_criteria.length > 1 && (
                                                    <span className="text-ink3">{t('board.jira.moreCriteria', { n: task.acceptance_criteria.length - 1 }, '+{n} kriter')}</span>
                                                  )}</>;
                                            })()}
                                          </div>
                                        )}
                                      </div>
                                    </div>

                                    {/* Sağ Eylemler: Onay, Sorumlu, İncele, Durum */}
                                    <div className="flex items-center gap-2 shrink-0">
                                      {pendingStepOrder === task.order && (
                                        <span className="px-2 py-0.5 bg-warnd text-warn border border-warn/50 rounded text-[10px] font-bold animate-pulse flex items-center gap-1">
                                          <Clock className="w-3 h-3" />
                                          {t('board.jira.awaitingApproval', undefined, 'Onay Bekliyor')}
                                        </span>
                                      )}

                                      
                                      {renderPlanBadge(task)}
                                      <span className="inline-flex items-center gap-2 opacity-0 group-hover:opacity-100 focus-within:opacity-100 transition-opacity">
                                      {renderRunControls(task.order)}

                                      {onInspectTask && (
                                        <button
                                          onClick={() => onInspectTask(task.order, task)}
                                          className="text-[11px] text-ac hover:text-ac flex items-center gap-1 hover:underline"
                                        >
                                          <FileText className="w-3 h-3" />
                                          <span>{t('board.jira.inspect', undefined, 'İncele')}</span>
                                        </button>
                                      )}

                                      {onInspectAudit && (
                                        <button
                                          type="button"
                                          onClick={() => onInspectAudit(task)}
                                          className="text-[11px] text-warn hover:text-warn flex items-center gap-1 hover:underline"
                                          title={t('board.jira.auditTitle', undefined, 'Denetim Tarihçesi')}
                                        >
                                          <History className="w-3 h-3" />
                                          <span>{t('board.jira.history', { n: task.audit_trail?.length || 0 }, 'Tarihçe ({n})')}</span>
                                        </button>
                                      )}

                                      {renderPlanActions(task)}
                                      </span>
                                      {getAssigneeBadge(task.assignee)}

                                      {renderStatusSelect(task)}
                                    </div>
                                  </div>
                                ))
                              )}
                            </div>
                          )}
                        </div>
                      );
                    })}

                    {/* Doğrudan Epic Altındaki Görevler */}
                    {orphanTasks.length > 0 && (
                      <div className={isVirtual ? '' : 'ml-4 p-3 bg-panel/60 rounded-xl border border-line space-y-2'}>
                        {!isVirtual && (                        <button
                          type="button"
                          onClick={() => toggleCollapse(`orphans:${epic.id}`)}
                          aria-expanded={!collapsedNodes.has(`orphans:${epic.id}`)}
                          className="w-full flex items-center gap-1.5 text-xs font-bold text-ink3 hover:text-ink uppercase tracking-wider mb-2 text-left transition"
                          title={collapsedNodes.has(`orphans:${epic.id}`) ? t('board.jira.expand', undefined, 'Genişlet') : t('board.jira.collapse', undefined, 'Daralt')}
                        >
                          {collapsedNodes.has(`orphans:${epic.id}`) ? <ChevronRight className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
                          {t('board.jira.generalProjectTasks', { n: orphanTasks.length }, 'Genel Proje Görevleri ({n})')}
                        </button>)}
                        {(isVirtual || !collapsedNodes.has(`orphans:${epic.id}`)) && orphanTasks.map(task => (
                          <div key={task.id} data-issue-id={task.id} className={`flex items-center justify-between gap-3 p-1.5 rounded transition ${isActive(task) ? 'bg-warnd/60 border border-warn/60 ring-1 ring-warn/30' : 'hover:bg-panel/80'} ${passiveCls(task)}`}>
                            <div className="flex items-center gap-2 min-w-0">
                              <button onClick={() => toggleSelect(task.id)}>
                                {selectedIds.has(task.id) ? (
                                  <CheckSquare className="w-4 h-4 text-ac" />
                                ) : (
                                  <Square className="w-4 h-4 text-ink3" />
                                )}
                              </button>
                              {idBadge(task)}
                              {getTypeBadge(task.issue_type)}
                              <span className="text-xs font-mono font-bold text-ink2 shrink-0" title={t('board.jira.uniqueId', { id: task.id }, 'Benzersiz kimlik: {id}')}>{task.key || task.id}</span>
                              {task.kind === 'task' && (
                                <span className="text-[9px] font-mono px-1 py-0.5 rounded bg-acd text-ac border border-ac/40 shrink-0" title={t('board.jira.fromBacklogPo', undefined, "Mimarın backlog'undan / PO iyileştirmesinden gelen görev")}>⚙ {task.task_key || 'backlog'}</span>
                              )}
                              <span className="text-xs text-ink truncate">{task.title}</span>{queueBadge(task.id)}
                            </div>
                            <div className="flex items-center gap-2">
                              
                              {renderPlanControls(task)}
                              {getAssigneeBadge(task.assignee)}
                              {renderStatusSelect(task)}
                            </div>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      ) : (
        /* =========================================================================
           2. KLASİK JIRA KANBAN SÜTUNLARI GÖRÜNÜMÜ
           ========================================================================= */
        <div className="flex-1 p-4 grid grid-cols-1 md:grid-cols-5 gap-3.5 overflow-x-auto overflow-y-hidden">
          {COLUMNS.map(col => {
            const colIssues = filteredIssues.filter(i => i.status === col.key)
              .sort((a, b) => ((a.board_rank ?? 1e6) - (b.board_rank ?? 1e6)) || a.order - b.order);

            return (
              <div
                key={col.key}
                className={`flex flex-col bg-panel/60 rounded-lg border ${col.color} overflow-hidden shadow-inner ${dragId ? 'ring-1 ring-ac/40' : ''}`}
                onDragOver={e => { if (jira) e.preventDefault(); }}
                onDrop={e => dropOn(e, col.key)}
              >
                {/* Sütun Başlığı */}
                <div className="px-3 py-2 bg-panel/90 border-b border-line/80 flex items-center justify-between">
                  <span className="text-xs font-semibold text-ink2 tracking-wide uppercase">
                    {colTitle(col.key)}
                  </span>
                  <span className="text-[10px] bg-panel2 text-ink3 font-mono px-2 py-0.5 rounded-full border border-line2">
                    {colIssues.length}
                  </span>
                </div>

                {/* Sütun İçi Kart Listesi */}
                <div className="flex-1 p-2.5 overflow-y-auto space-y-2.5">
                  {colIssues.length === 0 ? (
                    <div className="h-24 flex items-center justify-center border border-dashed border-line/60 rounded-lg text-ink3 text-xs italic">
                      {t('board.jira.noIssues', undefined, 'İş yok')}
                    </div>
                  ) : (
                    colIssues.map((issue, idx) => {
                      const isChecked = selectedIds.has(issue.id);

                      return (
                        <div
                          key={issue.id}
                          draggable={!!jira && !issue.deleted}
                          onDragStart={e => { e.dataTransfer.setData('text/plain', issue.id); e.dataTransfer.effectAllowed = 'move'; setDragId(issue.id); }}
                          onDragEnd={() => setDragId(null)}
                          onDragOver={e => { if (jira) e.preventDefault(); }}
                          onDrop={e => dropOn(e, col.key, idx)}
                          title={jira ? t('board.jira.dragTitle', undefined, 'Sürükleyip başka sütuna ya da sıraya bırak') : undefined}
                          className={`p-3 rounded-lg border transition-all duration-200 ${jira ? 'cursor-grab active:cursor-grabbing' : ''} ${issue.deleted ? 'opacity-50 line-through' : ''} ${
                            isChecked
                              ? 'bg-panel/90 border-ac/70 shadow-md'
                              : 'bg-sunk/70 border-line/90 hover:border-line2'
                          }`}
                        >
                          <div className="flex items-center justify-between mb-2">
                            <div className="flex items-center gap-2">
                              <button
                                onClick={() => toggleSelect(issue.id)}
                                className="text-ink3 hover:text-ink"
                              >
                                {isChecked ? (
                                  <CheckSquare className="w-4 h-4 text-ac fill-onac" />
                                ) : (
                                  <Square className="w-4 h-4 text-ink3" />
                                )}
                              </button>
                              {idBadge(issue)}
                              {getTypeBadge(issue.issue_type)}
                            </div>

                            <span className={`text-[9px] font-bold px-1.5 py-0.5 rounded ${
                              issue.priority === 'P0' 
                                ? 'bg-errd text-err border border-err/40' 
                                : 'bg-warnd text-warn border border-warn/40'
                            }`}>
                              {issue.priority}
                            </span>
                          </div>

                          <h4 className="text-xs font-semibold text-ink leading-snug mb-1.5 line-clamp-2">
                            {issue.title}
                          </h4>

                          {issue.description && (
                            <p className="text-[11px] text-ink3 mb-2 line-clamp-2 leading-relaxed">
                              {issue.description}
                            </p>
                          )}

                          {pendingStepOrder === issue.order && (
                            <div className="mb-2 py-1 px-2 rounded bg-warnd border border-warn/50 text-warn text-[10px] font-bold flex items-center justify-between animate-pulse">
                              <span className="flex items-center gap-1">
                                <Clock className="w-3 h-3" />
                                {t('board.jira.awaitingContinue', undefined, 'Devam Onayı Bekleniyor')}
                              </span>
                              {onInspectTask && (
                                <button
                                  onClick={() => onInspectTask(issue.order, issue)}
                                  className="underline hover:text-ink"
                                >
                                  {t('board.jira.reviewApprove', undefined, 'İncele & Onayla →')}
                                </button>
                              )}
                            </div>
                          )}

                          <div className="pt-2 border-t border-line/80 flex items-center justify-between gap-1">
                            <div className="flex items-center gap-1.5">
                              {getAssigneeBadge(issue.assignee)}
                              {renderRunControls(issue.order, true)}
                              {onInspectTask && (
                                <button
                                  type="button"
                                  onClick={() => onInspectTask(issue.order, issue)}
                                  className="text-[10px] text-ac hover:text-ac flex items-center gap-0.5 hover:underline"
                                >
                                  <FileText className="w-2.5 h-2.5" />
                                  <span>{t('board.jira.inspect', undefined, 'İncele')}</span>
                                </button>
                              )}
                              {onInspectAudit && (
                                <button
                                  type="button"
                                  onClick={() => onInspectAudit(issue)}
                                  className="text-[10px] text-warn hover:text-warn flex items-center gap-0.5 hover:underline"
                                  title={t('board.jira.auditTitle', undefined, 'Denetim Tarihçesi')}
                                >
                                  <History className="w-2.5 h-2.5" />
                                  <span>{t('board.jira.history', { n: issue.audit_trail?.length || 0 }, 'Tarihçe ({n})')}</span>
                                </button>
                              )}
                            </div>

                            {renderStatusSelect(issue)}
                          </div>
                        </div>
                      );
                    })
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* YENİ GÖREV / BUG EKLEME MODALI */}
      {isAddModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-md">
          <div className="bg-panel border border-line2 rounded-2xl w-full max-w-lg p-6 shadow-2xl space-y-4 animate-in fade-in zoom-in duration-200">
            <div className="flex items-center justify-between border-b border-line pb-3">
              <div className="flex items-center gap-2">
                <PlusCircle className="w-5 h-5 text-ok" />
                <h3 className="text-base font-bold text-ink">{t('board.jira.newIssueTitle', undefined, 'Yeni Jira Görevi / Bug Ekle')}</h3>
              </div>
              <button onClick={() => setIsAddModalOpen(false)} className="text-ink3 hover:text-ink">
                <X className="w-5 h-5" />
              </button>
            </div>

            <form onSubmit={handleCreateIssue} className="space-y-3">
              <div>
                <label className="block text-xs text-ink3 mb-1">{t('board.jira.fTitle', undefined, 'Görev / Hata Başlığı')}</label>
                <input
                  type="text"
                  required
                  placeholder={t('board.jira.titlePh', undefined, 'Örn: ExpiredSignatureError hatasının 401 olarak ele alınması')}
                  value={newTitle}
                  onChange={e => setNewTitle(e.target.value)}
                  className="w-full bg-sunk border border-line2 rounded-lg px-3 py-2 text-xs text-ink placeholder-ink3 focus:border-ok focus:outline-none"
                />
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs text-ink3 mb-1">{t('board.jira.fType', undefined, 'Kayıt Türü')}</label>
                  <select
                    value={newType}
                    onChange={e => setNewType(e.target.value as JiraIssueType)}
                    className="w-full bg-sunk border border-line2 rounded-lg px-3 py-2 text-xs text-ink"
                  >
                    <option value="TASK">{t('board.jira.typeTask', undefined, 'TASK (Görev)')}</option>
                    <option value="BUG">{t('board.jira.typeBug', undefined, 'BUG (Hata / Bugfix)')}</option>
                    <option value="STORY">{t('board.jira.typeStory', undefined, 'STORY (Kullanıcı Hikayesi)')}</option>
                    <option value="FEATURE">{t('board.jira.typeFeature', undefined, 'FEATURE (Yeni Özellik)')}</option>
                  </select>
                </div>

                <div>
                  <label className="block text-xs text-ink3 mb-1">{t('board.jira.fAssignee', undefined, 'Sorumlu Ajan')}</label>
                  <select
                    value={newAssignee}
                    onChange={e => setNewAssignee(e.target.value as AgentRole)}
                    className="w-full bg-sunk border border-line2 rounded-lg px-3 py-2 text-xs text-ink"
                  >
                    <option value="BACKEND_DEV">Senior Backend Dev</option>
                    <option value="FRONTEND_DEV">Senior Frontend Dev</option>
                    <option value="DESIGNER">UI/UX Designer</option>
                    <option value="QA">Lead QA Engineer</option>
                    <option value="E2E_TESTER">Playwright E2E Tester</option>
                    <option value="ARCHITECT">System Architect</option>
                    <option value="DEVOPS">DevOps Engineer</option>
                    <option value="PM">Product Manager</option>
                  </select>
                </div>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs text-ink3 mb-1">{t('board.issue.priority', undefined, 'Öncelik')}</label>
                  <select
                    value={newPriority}
                    onChange={e => setNewPriority(e.target.value as 'P0' | 'P1' | 'P2')}
                    className="w-full bg-sunk border border-line2 rounded-lg px-3 py-2 text-xs text-ink"
                  >
                    <option value="P0">{t('board.jira.p0', undefined, 'P0 (Kritik / Blocker)')}</option>
                    <option value="P1">{t('board.jira.p1', undefined, 'P1 (Yüksek)')}</option>
                    <option value="P2">{t('board.jira.p2', undefined, 'P2 (Normal)')}</option>
                  </select>
                  <label className="block text-xs text-ink3 mt-2 mb-1" title={t('board.jira.laneTitle', undefined, "Aynı anda tek koşu yürür; paralel çalışmaz. 'Önce yap' işi çalışan koşunun hemen sonraki adımı yapar.")}>{t('board.jira.laneLabel', undefined, 'Öncelik şeridi')}</label>
                  <select
                    value={newExpedite}
                    onChange={e => setNewExpedite(e.target.value as '' | 'next_sprint' | 'now')}
                    className="w-full bg-sunk border border-line2 rounded-lg px-3 py-2 text-xs text-ink"
                  >
                    <option value="">{t('board.jira.laneNormal', undefined, 'Normal (sıra ve önceliğe göre)')}</option>
                    <option value="next_sprint">{t('board.jira.laneNext', undefined, 'Sıradaki sprintin başı')}</option>
                    <option value="now">{t('board.jira.laneNow', undefined, 'Önce yap (çalışan koşuda hemen; koşu yoksa sprint başı)')}</option>
                  </select>
                </div>

                <div>
                  <label className="block text-xs text-ink3 mb-1">{t('board.jira.fParent', undefined, 'Bağlı Olduğu Üst Görev (Parent)')}</label>
                  <select
                    value={newParentId}
                    onChange={e => setNewParentId(e.target.value)}
                    className="w-full bg-sunk border border-line2 rounded-lg px-3 py-2 text-xs text-ink"
                  >
                    <option value="">{t('board.jira.parentAuto', undefined, '(Otomatik veya Ana Epic)')}</option>
                    {issues.filter(i => i.issue_type === 'EPIC' || i.issue_type === 'STORY').map(i => (
                      <option key={i.id} value={i.id}>[{i.key}] {i.title}</option>
                    ))}
                  </select>
                </div>
              </div>

              <div>
                <label className="block text-xs text-ink3 mb-1">{t('board.jira.fInstr', undefined, 'Talimatlar / Açıklama')}</label>
                <textarea
                  rows={2}
                  placeholder={t('board.jira.instrPh', undefined, 'Ajanların ne yapması gerektiğini veya hatanın detaylarını yazın...')}
                  value={newDesc}
                  onChange={e => setNewDesc(e.target.value)}
                  className="w-full bg-sunk border border-line2 rounded-lg p-2.5 text-xs text-ink placeholder-ink3 focus:border-ok focus:outline-none"
                />
              </div>

              <div>
                <label className="block text-xs text-ink3 mb-1">{t('board.jira.fCriteria', undefined, 'Kabul Kriterleri (Her satıra bir tane)')}</label>
                <textarea
                  rows={2}
                  placeholder={t('board.jira.criteriaPh', undefined, "Örn: HTTP 401 ve {'error': 'TOKEN_EXPIRED'} dönmeli")}
                  value={newCriteria}
                  onChange={e => setNewCriteria(e.target.value)}
                  className="w-full bg-sunk border border-line2 rounded-lg p-2.5 text-xs text-ink placeholder-ink3 focus:border-ok focus:outline-none"
                />
              </div>

              <div className="flex justify-end gap-2 pt-2 border-t border-line">
                <button
                  type="button"
                  onClick={() => setIsAddModalOpen(false)}
                  className="px-4 py-2 bg-panel2 hover:bg-sunk text-ink2 rounded-lg text-xs"
                >
                  {t('board.jira.cancel', undefined, 'Vazgeç')}
                </button>
                <button
                  type="submit"
                  disabled={creating}
                  className="px-4 py-2 bg-ok hover:bg-ok text-onac font-bold rounded-lg text-xs shadow-lg transition disabled:opacity-60"
                >
                  {creating ? t('board.jira.adding', undefined, 'Ekleniyor…') : `✓ ${t('board.jira.addIssue', undefined, 'Görevi Ekle')}`}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {editing && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4" onClick={() => setEditing(null)}>
          <div className="bg-panel border border-line rounded-2xl shadow-xl w-full max-w-lg p-5 space-y-3" onClick={e => e.stopPropagation()}>
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-bold text-ink">{t('board.jira.editIssue', { key: editing.key }, '{key} · Görevi düzenle')}</h3>
              <button onClick={() => setEditing(null)} className="text-ink3 hover:text-ink"><X className="w-4 h-4" /></button>
            </div>
            <label className="block text-xs text-ink2">{t('board.jira.fieldTitle', undefined, 'Başlık')}
              <input value={editing.title} onChange={e => setEditing({ ...editing, title: e.target.value })} className="mt-1 w-full bg-sunk border border-line rounded-lg px-2.5 py-1.5 text-ink" />
            </label>
            <label className="block text-xs text-ink2">{t('board.issue.description', undefined, 'Açıklama')}
              <textarea value={editing.description || ''} onChange={e => setEditing({ ...editing, description: e.target.value })} rows={3} className="mt-1 w-full bg-sunk border border-line rounded-lg px-2.5 py-1.5 text-ink" />
            </label>
            <div className="grid grid-cols-3 gap-3">
              <label className="block text-xs text-ink2">{t('board.issue.priority', undefined, 'Öncelik')}
                <select value={editing.priority} onChange={e => setEditing({ ...editing, priority: e.target.value as JiraIssue['priority'] })} className="mt-1 w-full bg-sunk border border-line rounded-lg px-2 py-1.5 text-ink">
                  {['P0', 'P1', 'P2'].map(p => <option key={p} value={p}>{p}</option>)}
                </select>
              </label>
              <label className="block text-xs text-ink2">{t('board.issue.assignee', undefined, 'Sorumlu')}
                <select value={editing.assignee} onChange={e => setEditing({ ...editing, assignee: e.target.value as AgentRole })} className="mt-1 w-full bg-sunk border border-line rounded-lg px-2 py-1.5 text-ink">
                  {Array.from(new Set([...issues.map(i => i.assignee), editing.assignee])).map(a => <option key={a} value={a}>{a}</option>)}
                </select>
              </label>
              <label className="block text-xs text-ink2">Sprint
                <select
                  value={editing.planned_sprint ?? ''}
                  disabled={!canPlan(editing)}
                  onChange={e => setEditing({ ...editing, planned_sprint: e.target.value ? Number(e.target.value) : null })}
                  className="mt-1 w-full bg-sunk border border-line rounded-lg px-2 py-1.5 text-ink disabled:opacity-50"
                  title={canPlan(editing) ? '' : t('board.issue.planLockedTitle', undefined, 'Sprinte alınmış ya da başlamış işin sprinti değişmez')}
                >
                  <option value="">Backlog</option>
                  {Array.from({ length: Math.max(3, ...sprints.map(x => x.sprint_number + 1)) }, (_, k) => k + 1)
                    .filter(n => !['CLOSED', 'IN_PROGRESS', 'IN_REVIEW', 'COMMITTED'].includes(sprints.find(x => x.sprint_number === n)?.status || ''))
                    .map(n => <option key={n} value={n}>Sprint {n}</option>)}
                </select>
              </label>
            </div>
            {(canPlan(editing) || canExpedite(editing)) && (
              <label className="block text-xs text-ink2" title={t('board.jira.laneTitle', undefined, "Aynı anda tek koşu yürür; paralel çalışmaz. 'Önce yap' işi çalışan koşunun hemen sonraki adımı yapar.")}>{t('board.jira.laneLabel', undefined, 'Öncelik şeridi')}
                <select
                  value={editing.expedite ?? ''}
                  onChange={e => setEditing({ ...editing, expedite: (e.target.value || null) as JiraIssue['expedite'] })}
                  className="mt-1 w-full bg-sunk border border-line rounded-lg px-2 py-1.5 text-ink"
                >
                  <option value="">{t('board.jira.laneNormal', undefined, 'Normal (sıra ve önceliğe göre)')}</option>
                  <option value="next_sprint">{t('board.jira.laneNext', undefined, 'Sıradaki sprintin başı')}</option>
                  <option value="now">{t('board.jira.laneNow', undefined, 'Önce yap (çalışan koşuda hemen; koşu yoksa sprint başı)')}</option>
                </select>
              </label>
            )}
            {editErr && <div className="text-xs text-err">{editErr}</div>}
            <div className="flex justify-end gap-2 pt-1">
              <button onClick={() => setEditing(null)} className="px-3 py-1.5 text-xs rounded-lg border border-line text-ink2 hover:text-ink">{t('board.jira.cancel', undefined, 'Vazgeç')}</button>
              <button
                onClick={async () => {
                  try {
                    const body: Record<string, unknown> = { title: editing.title, description: editing.description, priority: editing.priority, assignee: editing.assignee };
                    if (canPlan(editing)) body.planned_sprint = editing.planned_sprint ?? null;
                    const before = issues.find(i => i.id === editing.id)?.expedite ?? null;
                    if ((canPlan(editing) || canExpedite(editing)) && (editing.expedite ?? null) !== before) body.expedite = editing.expedite ?? '';
                    const j = await postPlan(editing.id, body);
                    const x = j.expedite;
                    if (x && x.mode === 'now') notify(`${t('board.jira.expediteAddedShort', { order: x.order }, 'Önce yap: iş çalışan koşuya eklendi (adım #{order}).')}${(x.warnings || []).length ? '\n' + x.warnings.join('\n') : ''}`);
                    else if (x && x.fallback) notify(x.reason || t('board.jira.noSprintRunMoved', undefined, 'Çalışan sprint koşusu yok: iş sıradaki sprintin başına alındı.'));
                    setEditing(null);
                  } catch (e) { setEditErr((e as Error).message); }
                }}
                className="px-3 py-1.5 text-xs rounded-lg bg-ac text-onac font-semibold"
              >{t('board.issue.save', undefined, 'Kaydet')}</button>
            </div>
          </div>
        </div>
      )}

      {/* G5: madde detayı çekmecesi */}
      {jira && detailId && (
        <IssueDetailDrawer
          issue={allIssues.find(i => i.id === detailId) || null}
          issues={allIssues}
          jira={jira}
          sprints={sprints}
          attachmentSources={attachmentSources}
          onClose={() => setDetailId(null)}
          onOpenIssue={setDetailId}
          onInspectTask={onInspectTask}
          initialTab={detailTab}
        />
      )}
    </div>
  );
};
