import { createPortal } from 'react-dom';
import { notify, confirmDialog, promptDialog } from './lib/dialog';
import React, { useState, useEffect, useMemo } from 'react';
import { useI18n } from './i18n';
import { ToolbarMenu } from './components/ToolbarMenu';
import { useTelemetryWS } from './hooks/useTelemetryWS';
import { AgentMesh } from './components/AgentMesh';
import { BottomDock } from './components/BottomDock';
import { TelemetryDock } from './components/TelemetryDock';
import { ConfigMenu } from './components/ConfigMenu';
import { ProjectViewers } from './components/ProjectViewers';
import { openDocs, openFiles } from './lib/viewer';
import { TelemetryMetrics } from './components/TelemetryMetrics';
import { ProjectSwitcher } from './components/ProjectSwitcher';
import { FolderBrowser } from './components/FolderBrowser';
import { JiraBoard } from './components/JiraBoard';
import { SpecUploadModal } from './components/SpecUploadModal';
import { PlaywrightReportDrawer } from './components/PlaywrightReportDrawer';
import { AgentManagerModal } from './components/AgentManagerModal';
import { TestManagementModal } from './components/TestManagementModal';
import { ManagementCenterModal } from './components/ManagementCenterModal';
import { NotificationCenter } from './components/NotificationCenter';
import { StepInspectorModal } from './components/StepInspectorModal';
import { LiveThinkingStream } from './components/LiveThinkingStream';
import { ModelSwitcherModal } from './components/ModelSwitcherModal';
import { QueuedRunBanner } from './components/QueuedRunBanner';
import { ProjectPausedBanner } from './components/ProjectPausedBanner';
import { SprintBlockedBanner } from './components/SprintBlockedBanner';
import { GoalsStrip } from './components/GoalsStrip';
import { ProjectSettingsModal } from './components/ProjectSettingsModal';
import { SprintKpiStrip } from './components/SprintKpiStrip';
import { ReportsView } from './components/ReportsView';
import { usePersistedState } from './hooks/usePersistedState';
import { useServerInfo } from './hooks/useServerInfo';
import { AgentTimelineDrawer } from './components/AgentTimelineDrawer';
import { RunHistoryDrawer } from './components/RunHistoryDrawer';
import { HoneycombTopology } from './components/HoneycombTopology';
import { ApprovalModeSegment } from './components/ApprovalModeSegment';
import { TechDecisionsModal } from './components/TechDecisionsModal';
import { QuestionsModal } from './components/QuestionsModal';
import { ClaudeModal, ClaudePanel } from './components/ClaudePanel';
import { AgentOffice } from './components/AgentOffice';
import { DeliberationModal } from './components/DeliberationModal';
import { TaskAuditModal } from './components/TaskAuditModal';
import { 
  Settings2,
  FolderGit2, 
  Play, 
  Sparkles, 
  CheckCircle2,
  FolderSearch, 
  Send, 
  Layers, 
  FolderUp, 
  MonitorCheck, 
  UserPlus, 
  FlaskConical,
  ClipboardList,
  Network,
  Clock,
  ExternalLink,
  Zap,
  Cpu,
  Users,
  History,
  HelpCircle,
  Plug,
  BookOpenText,
  FolderTree,
  BarChart3,
  Terminal,
  Palette,
} from 'lucide-react';
import { Agent, KanbanState, KanbanTask, JiraIssueStatus, StepApprovalInfo, JiraIssue, PipelineRun, StepRecord } from './types/telemetry';
import { DEFAULT_TARGET_URL } from './config';

type ActiveView = 'MESH_VIEW' | 'JIRA_VIEW' | 'REPORTS_VIEW';

/** Pixel-art "Ofis" görünümü şimdilik gizli; açmak için true yapın (bileşen ve kod yerinde duruyor). */
const SHOW_PIXEL_OFFICE = false;
// Petek topolojisi şimdilik gizli (ileride geliştirilecek); kod duruyor. Daha önce seçilmişse topolojiye düşer.
const SHOW_HONEYCOMB = false;

/** Araç çubuğunu üst başlıktaki #toolbar-slot yuvasına taşır (başlık + araç çubuğu tek satır); yuva yoksa hiçbir şey çizmez. */
const ToolbarPortal: React.FC<{ children: React.ReactNode; slotId?: string; column?: boolean; cls?: string }> = ({ children, slotId = 'toolbar-slot', column, cls: clsProp }) => {
  const [slot, setSlot] = useState<HTMLElement | null>(null);
  useEffect(() => { setSlot(document.getElementById(slotId)); }, [slotId]);
  const cls = clsProp || (column ? 'flex flex-col items-center gap-0.5 flex-1 min-h-0 w-full' : 'flex items-center min-w-0');
  return slot ? createPortal(<div className={cls}>{children}</div>, slot) : null;
};

/** Projedeki güncel sprint (üst çubukta proje seçicinin yanında) */
const CurrentSprintPill: React.FC = () => {
  const [n, setN] = useState<string>('');
  useEffect(() => {
    const load = () => fetch('/api/sprints/board').then(r => r.json()).then(j => setN(j?.current ? `Sprint ${j.current.sprint_number}` : '')).catch(() => undefined);
    load();
    const t = setInterval(load, 30000);
    return () => clearInterval(t);
  }, []);
  return n ? <span className="inline-flex items-center h-[22px] px-2.5 rounded-full bg-acd text-ac border border-ac/30 text-[11.5px] font-medium whitespace-nowrap">{n}</span> : null;
};

/** Sol ray düğmesi: dikey simge + kısa etiket */
const RailButton: React.FC<{ label: string; icon: React.ReactNode; active?: boolean; alert?: boolean; onClick?: () => void; title?: string; badge?: React.ReactNode }> = ({ label, icon, active, alert, onClick, title, badge }) => (
  <button
    type="button"
    onClick={onClick}
    title={title}
    aria-label={label}
    aria-current={active ? 'page' : undefined}
    className={`relative w-14 py-1.5 rounded-[10px] transition flex flex-col items-center gap-0.5 text-[10px] font-medium ${active ? 'bg-[#2B3040] text-white before:content-[""] before:absolute before:-left-2 before:top-2.5 before:bottom-2.5 before:w-[3px] before:rounded-sm before:bg-[#8C97F5]' : alert ? 'text-[#F5B454] bg-[#3A2F1B]' : 'text-[#9AA1B2] hover:text-white hover:bg-[#262B38]'}`}
  >
    <span className="[&>svg]:w-5 [&>svg]:h-5">{icon}</span>
    {label}
    {badge}
  </button>
);

export function App() {
  const { t, lang } = useI18n();
  const {
    isConnected,
    projects,
    currentProject,
    agents,
    tasks,
    jiraIssues,
    uploadedSpecs,
    playwrightReports,
    testProfiles,
    events,
    stats,
    activeEdgeId,
    edgeStatus,
    switchProject,
    addProject,
    deleteProject,
    purgeProject,
    executeJiraBatch,
    uploadSpec,
    runPlaywrightTest,
    runTestsOnlySuite,
    saveTestProfile,
    deleteTestProfile,
    addCustomAgent,
    updateAgent,
    deleteAgent,
    updateJiraIssue,
    jiraApi,
    sprintVersion,
    serverVersions,
    notifications,
    markNotificationsRead,
    clearNotifications,
    resetState,
    pendingApproval,
    stepByStepMode,
    approveStep,
    toggleStepMode,
    analyzeSpecAndGenerateTasks,
    deleteSpec,
    deleteSpecFile,
    updateSpec,
    fetchAgentPrompt,
    saveAgentPrompt,
    restoreAgentVersion,
    inheritAgentStandard,
    promoteAgentToGlobal,
    modelConfig,
    updateModelConfig,
    activeDeliberation,
    runDeliberation,
    recordTaskAudit,
    isExecuting,
    lastRunStatus,
    activeRun,
    settings,
    connectedClients,
    liveThinking,
    startRun,
    cancelRun,
    pauseRun,
    sendRunNote,
    resumeRun,
    updateSettings,
    runs,
    teamsVersion,
    raisedHands,
    setApprovalMode,
    resolveHand,
    techQuestions,
    queueQuestions,
    answerQuestion,
    mcpActivity,
    claudePanelData,
    techDecisions,
    decisionsPending,
    loadDecisions,
    saveDecisions,
    resetDecisions,
    choosePlan
  } = useTelemetryWS();
  const serverInfo = useServerInfo();
  const [isRunHistoryOpen, setIsRunHistoryOpen] = useState<boolean>(false);

  // Görünüm Tabı (Topoloji Ağı veya Jira Tahtası)
  const [activeView, setActiveView] = usePersistedState<ActiveView>('ag_active_view', 'MESH_VIEW', ['MESH_VIEW', 'JIRA_VIEW', 'REPORTS_VIEW'] as const);
  // Ağ Görünümü İçi Segment (Ofis vs Topoloji)
  const [meshViewSaved, setMeshView] = usePersistedState<'ofis' | 'topoloji' | 'petek'>('ag_mesh_view', 'topoloji', ['ofis', 'topoloji', 'petek'] as const);
  // Pixel-art ofis görünümü şimdilik gizli (SHOW_PIXEL_OFFICE); daha önce seçilmişse topolojiye düşer
  const meshView = (!SHOW_PIXEL_OFFICE && meshViewSaved === 'ofis') || (!SHOW_HONEYCOMB && meshViewSaved === 'petek') ? 'topoloji' : meshViewSaved;

  // D2: toplantı odasına toplanma (müzakere sürüyor ya da bir adım onay bekliyor)
  const gathering = useMemo(() => {
    if (activeDeliberation?.status === 'ACTIVE') {
      const participants = [...new Set(activeDeliberation.messages.map(m => m.agent_id))];
      return { active: true, participants: participants.length ? participants : ['PM'], reason: t('board.app.reasonDeliberation', undefined, 'müzakere') };
    }
    if (pendingApproval) {
      const participants = [pendingApproval.agent_id, pendingApproval.next_agent_id].filter((x): x is string => !!x);
      return { active: true, participants, reason: t('board.app.reasonApproval', { order: pendingApproval.order }, `adım #${pendingApproval.order} onayı`) };
    }
    return { active: false, participants: [] as string[] };
  }, [activeDeliberation, pendingApproval, t]);
  // Seçili ajan (topoloji kartı / ofis avatarı tıklaması → zaman çizelgesi)
  const [selectedAgentId, setSelectedAgentId] = useState<string | null>(null);

  // Modal Durumları
  const [isSpecModalOpen, setIsSpecModalOpen] = useState<boolean>(false);
  const [isDecisionsModalOpen, setIsDecisionsModalOpen] = useState<boolean>(false);
  const [isQuestionsModalOpen, setIsQuestionsModalOpen] = useState<boolean>(false);
  // Claude iletişim görünümü: modal ya da ayrı sekmede tam sayfa (#claude)
  const [isClaudeModalOpen, setIsClaudeModalOpen] = useState<boolean>(false);
  const [isClaudePage, setIsClaudePage] = useState<boolean>(() => window.location.hash === '#claude');
  useEffect(() => {
    const onHash = () => setIsClaudePage(window.location.hash === '#claude');
    window.addEventListener('hashchange', onHash);
    return () => window.removeEventListener('hashchange', onHash);
  }, []);
  const openQuestions = queueQuestions.filter(q => q.status === 'OPEN');
  const openBlocking = openQuestions.filter(q => q.blocking).length;
  // Karar kapısı açılınca modalı otomatik göster; ilk yüklemede kayıtlı kararları çek
  useEffect(() => { loadDecisions().catch(() => undefined); }, [currentProject?.id]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (decisionsPending) setIsDecisionsModalOpen(true); }, [decisionsPending]);
  const [isTesterModalOpen, setIsTesterModalOpen] = useState<boolean>(false);
  const [isAgentModalOpen, setIsAgentModalOpen] = useState<boolean>(false);
  const [isTestingOpen, setIsTestingOpen] = useState<boolean>(false);
  const [isManagementOpen, setIsManagementOpen] = useState<boolean>(false);
  const [isModelModalOpen, setIsModelModalOpen] = useState<boolean>(false);
  const [isDeliberationModalOpen, setIsDeliberationModalOpen] = useState<boolean>(false);
  const [selectedStepInfo, setSelectedStepInfo] = useState<StepApprovalInfo | null>(null);
  const [isStepModalOpen, setIsStepModalOpen] = useState<boolean>(false);

  // Eğer yeni bir adım onay beklemeye başlarsa bilgiyi güncelle (Modal otomatik açılmaz, kullanıcı üst bardan veya karttan açar)
  useEffect(() => {
    if (pendingApproval) {
      setSelectedStepInfo(pendingApproval);
      // Modal kullanıcı isteği üzerine otomatik açılmaz, bildirim çubuğundan veya Jira kartından açılır.
    }
  }, [pendingApproval]);

  // Dinamik Proje Klasörü ve Görev Durumları
  const [projectDir, setProjectDir] = useState<string>('');
  const [isFolderBrowserOpen, setIsFolderBrowserOpen] = useState<boolean>(false);
  const [showProjectSettings, setShowProjectSettings] = useState<boolean>(false);
  useEffect(() => {
    const h = () => { setShowProjectSettings(false); setIsAgentModalOpen(true); };
    window.addEventListener('fssc:open-agents', h);
    return () => window.removeEventListener('fssc:open-agents', h);
  }, []);
  const [globalQuery, setGlobalQuery] = useState<string>('');
  const [taskPrompt, setTaskPrompt] = useState<string>(() => t('board.app.defaultTask', undefined, 'FastAPI ve React tabanlı Çok Katmanlı Servis & CRUD Panosu'));
  const [isFolderBound, setIsFolderBound] = useState<boolean>(false);
  const [statusMessage, setStatusMessage] = useState<string>('');
  // Durum mesajı kalıcı değildir: 12 sn sonra (ya da elle kapatılınca) kaybolur; yeni mesaj sayacı yeniler
  useEffect(() => {
    if (!statusMessage) return undefined;
    const t = setTimeout(() => setStatusMessage(''), 12000);
    return () => clearTimeout(t);
  }, [statusMessage]);

  // Koşu bitiş bildirimi (JIRA_BATCH_COMPLETED / TEST_SUITE_COMPLETED WS mesajlarından)
  useEffect(() => {
    if (!lastRunStatus) return;
    const label = lastRunStatus.type === 'TEST_SUITE_COMPLETED' ? t('banners.testSuite') : t('banners.pipelineRun');
    const ok = ['COMPLETED', 'PASSED'].includes(lastRunStatus.status);
    setStatusMessage(`${ok ? '✓' : '⚠'} ${t('banners.runCompleted', { type: label, status: lastRunStatus.status })}`);
  }, [lastRunStatus, t]);

  // Zaman Tüneli (Historical Replay) Durumları
  const [isReplayMode, setIsReplayMode] = useState<boolean>(false);
  const [replayIndex, setReplayIndex] = useState<number>(0);

  // Aktif proje değiştiğinde hedef klasör yolunu güncelle
  useEffect(() => {
    if (currentProject && currentProject.path) {
      setProjectDir(currentProject.path);
      setIsFolderBound(true);
    }
  }, [currentProject]);

  // Kronolojik sıralı olaylar (en eskiden en yeniye)
  const sortedEvents = useMemo(() => {
    return [...events].sort((a, b) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime());
  }, [events]);

  // En son gerçekleşen ajan etkileşimi ve insansı diyalog
  const latestInteraction = useMemo(() => {
    return sortedEvents.length > 0 ? sortedEvents[sortedEvents.length - 1] : null;
  }, [sortedEvents]);

  // Yeni olay geldiğinde eğer Replay modunda değilsek en sona odaklan
  useEffect(() => {
    if (!isReplayMode && sortedEvents.length > 0) {
      setReplayIndex(sortedEvents.length - 1);
    }
  }, [sortedEvents.length, isReplayMode]);

  // Proje klasörünü dinamik olarak bağlama
  const handleBindFolder = async () => {
    try {
      await addProject(projectDir);
      setIsFolderBound(true);
      setStatusMessage(`✓ ${t('board.app.projectBound', { dir: projectDir }, `Proje bağlandı ve seçildi: ${projectDir}`)}`);
      setTimeout(() => setStatusMessage(''), 4000);
    } catch (err) {
      console.error(err);
      const message = err instanceof Error ? err.message : t('board.app.serverUnreachableCheck', undefined, 'Sunucuya bağlanılamadı (sunucu portunu ve çalışıp çalışmadığını kontrol edin)');
      setIsFolderBound(false);
      setStatusMessage(`⚠ ${t('board.app.bindFailed', { message }, `Proje bağlanamadı: ${message}`)}`);
      notify(t('board.app.bindFailed', { message }, `Proje bağlanamadı: ${message}`));
    }
  };

  // Task Audit Trail Modalı Seçili Görev
  const [auditIssue, setAuditIssue] = useState<JiraIssue | null>(null);
  // G5: madde eklerine kaynak — kasa dosyaları ve E2E ekran görüntüleri
  const attachmentSources = useMemo(() => [
    ...uploadedSpecs.flatMap(s => (s.files || []).map(f => ({ name: `${s.id} · ${f.filename}`, path: f.saved_path, url: f.file_url }))),
    ...playwrightReports.flatMap(r => (r.screenshots || []).map(p => ({ name: `E2E ${r.id} · ${p.split('/').pop()}`, path: p }))),
  ], [uploadedSpecs, playwrightReports]);

  // Sunucu yeniden başlayınca ya da istemci kopunca koşu "terk edilmiş" olur; etkin koşu yoksa en çok ilerleyeni sürdürülebilir olarak gösterilir
  const resumableRun = useMemo(() => {
    if (activeRun) return null;
    const cands = runs.filter(r => r.project_id === currentProject?.id && r.status === 'ABANDONED' && r.engine === 'mcp_client');
    cands.sort((a, b) => (b.progress?.done ?? 0) - (a.progress?.done ?? 0) || (a.created_at < b.created_at ? 1 : -1));
    return cands[0] || null;
  }, [activeRun, runs, currentProject?.id]);

  const handleResumeAbandoned = async (runId: string) => {
    const res = await resumeRun(runId);
    setStatusMessage(`↻ ${res?.message || t('board.app.runRevived', undefined, 'Koşu canlandırıldı: adımları bir Claude oturumu çekene kadar ilerlemez.')}`);
    return res;
  };

  // "Baştan başlat": ilerlemiş koşuyu çöpe atar; sunucu proje adını doğrular (panodaki iki aşamalı onayın ikinci adımı)
  const handleRestartFresh = async (runId: string, confirmName: string) => {
    const r = await fetch(`/api/runs/${encodeURIComponent(runId)}/restart-fresh`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ confirm_name: confirmName }),
    });
    const res = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(res.error || t('board.app.errorStatus', { status: r.status }, `Hata ${r.status}`));
    setStatusMessage(`✓ ${t('board.app.freshRunCreated', { id: res?.run?.run_id || '' }, `Yeni koşu kuruldu (${res?.run?.run_id || ''}); önceki koşu bırakıldı.`)}`);
    return res;
  };

  // 1-10 Jira Maddelerini Toplu Çalıştırma
  const handleExecuteJiraBatch = async (selectedOrders: (number | string)[], stepByStep?: boolean) => {
    setIsReplayMode(false);
    const engine = settings.execution_engine;
    setStatusMessage(engine === 'mcp_client'
      ? `🧠 ${t('board.app.queueingMcp', { n: selectedOrders.length }, `${selectedOrders.length} madde MCP istemcisi (Claude Desktop) için kuyruğa alınıyor...`)}`
      : `🚀 ${t('board.app.batchRunning', { n: selectedOrders.length }, `Jira Batch Runner devrede: ${selectedOrders.length} madde sırayla icra ediliyor...`)}`);

    try {
      const res = await startRun(selectedOrders, engine, taskPrompt, projectDir, stepByStep);
      if (res.status === 'EXISTING') {
        setStatusMessage(`ℹ ${t('board.app.runExists', { id: res.run?.run_id }, `Zaten bekleyen/aktif bir koşu var (${res.run?.run_id}). Önce onu tamamlayın veya iptal edin.`)}`);
      } else if (res.status === 'RESUMED') {
        setStatusMessage(`↻ ${res.message || t('board.app.abandonedResumed', undefined, 'Terk edilmiş koşu kaldığı adımdan sürdürüldü.')}`);
      } else if (engine === 'mcp_client') {
        setStatusMessage(`✓ ${t('board.app.runQueued', undefined, "Koşu kuyruğa alındı. Claude Desktop'ta pipeline promptunu yazın; ilk get_next_step çağrısıyla aktifleşir.")}`);
      } else {
        setStatusMessage(`✓ ${t('board.app.loopStarted', { name: currentProject?.name || t('board.app.projectWord', undefined, 'Proje') }, `[${currentProject?.name || 'Proje'}] Jira görevleri için otonom döngü başlatıldı.`)}`);
      }
    } catch (err) {
      console.error(err);
      const message = err instanceof Error ? err.message : t('board.app.serverError', undefined, 'Sunucu hatası');
      setStatusMessage(`⚠ ${t('board.app.runStartFailed', { message }, `Koşu başlatılamadı: ${message}`)}`);
      notify(t('board.app.jiraRunFailed', { message }, `Jira görevleri çalıştırılamadı: ${message}`));
    }
  };

  // Adım Onayı İletme
  // REVISE: yorumla birlikte gider; sunucu reddederse (INVALID) cevap modala döner ve hata orada gösterilir
  const handleApproveStep = async (decision: 'PROCEED' | 'AUTO_ALL' | 'REVISE', comment?: string) => {
    try {
      const data = await approveStep(decision, comment);
      if (decision === 'AUTO_ALL' || (decision === 'REVISE' && data?.status === 'APPROVED')) {
        setIsStepModalOpen(false);
      }
      return data;
    } catch (err) {
      console.error(err);
      return { status: 'INVALID', error: t('board.app.serverUnreachable', undefined, 'Sunucuya ulaşılamadı.') };
    }
  };

  // Herhangi bir Jira görevini ve çıktılarını detaylı modalda inceleme.
  // G0: yalnızca sunucudaki GERÇEK adım kaydı gösterilir (uydurma dosya/token/rozet yok); kayıt yoksa bunu açıkça söyler.
  const handleInspectTask = (order: number, issue: JiraIssue) => {
    if (pendingApproval && pendingApproval.order === order) {
      setSelectedStepInfo(pendingApproval);
      setIsStepModalOpen(true);
      return;
    }
    // Aktif koşu öncelikli olmak üzere en yeni koşudan bu maddeye ait son (PENDING olmayan) adım kaydı
    const candidates: PipelineRun[] = [activeRun, ...runs].filter((r): r is PipelineRun => !!r);
    let found: { run: PipelineRun; step: StepRecord } | null = null;
    for (const r of candidates) {
      const steps = (r.steps || []).filter(s => s.issue_id === issue.id && s.status !== 'PENDING');
      if (steps.length > 0) {
        found = { run: r, step: steps[steps.length - 1] };
        break;
      }
    }
    const agentId = found?.step.role || issue.assignee;
    const agentName = agents.find(a => a.id === agentId)?.name || agentId;
    const artifactsFromRecord = (found?.step.artifacts || []).map((p: string) => ({
      name: p.split(/[\\/]/).pop() || p,
      path: p,
      type: (p.split('.').pop() || 'text').toLowerCase(),
      content: t('board.app.contentNotStored', { path: p }, `// İçerik koşu kaydında saklanmaz; dosya proje klasöründe: ${p}`),
    }));
    setSelectedStepInfo({
      order: found?.step.order ?? issue.order,
      issue_id: issue.id,
      title: found?.step.title || issue.title,
      agent_id: agentId,
      agent_name: agentName,
      agent_role: agentId,
      next_agent_id: null,
      next_agent_name: null,
      action: found ? (found.step.action || found.step.status) : 'NO_RECORD',
      summary: found
        ? (found.step.summary || t('board.app.noStepSummary', undefined, 'Adım özeti kaydedilmemiş.'))
        : t('board.app.noStepRecord', undefined, 'Bu madde için henüz bir adım kaydı yok. Koşu bu adımı işleyince sunucunun kaydı (özet, dosyalar, doğrulama, commit) burada görünür.'),
      artifacts: artifactsFromRecord,
      screenshots: found?.step.order === 7 && playwrightReports.length > 0 ? playwrightReports[0].screenshots : [],
      tokens_used: found ? (found.step.tokens_in || 0) + (found.step.tokens_out || 0) : 0,
      timestamp: found?.step.finished_at || found?.step.started_at || issue.updated_at || new Date().toISOString(),
      is_last_step: false,
      run_id: found?.run.run_id,
      kind: found?.step.kind,
      fix_round: found?.step.fix_round,
      verification: found?.step.verification || null,
      commit: found?.step.commit || null,
    });
    setIsStepModalOpen(true);
  };

  // Gerçek projeye kod üreten otonom şirket döngüsünü başlatma
  const handleExecuteRealProject = async () => {
    if (!taskPrompt.trim()) {
      notify(t('board.app.enterTask', undefined, 'Lütfen geliştirilecek görevi/özelliği yazın.'));
      return;
    }
    // Tüm 1-10 maddelerini çalıştır
    await handleExecuteJiraBatch([1, 2, 3, 4, 5, 6, 7, 8, 9, 10]);
  };

  // Geliştirme ajanları çalışmadan YALNIZCA Test kısmını (Madde 6 & 7) çalıştırma
  const handleRunTestsOnly = async () => {
    setStatusMessage(`🧪 ${t('board.app.testsOnlyStarting', undefined, 'Geliştirme ajanları çalışmadan yalnızca Test Süiti (QA Lead + Playwright E2E) başlatılıyor...')}`);
    try {
      const activeProfile = testProfiles[0];
      await runTestsOnlySuite(
        activeProfile?.target_url || DEFAULT_TARGET_URL,
        activeProfile ? { username: activeProfile.username, role: activeProfile.role, profile_id: activeProfile.id } : undefined,
        t('board.app.standaloneSuiteName', undefined, 'Bağımsız QA ve Canlı Tarayıcı E2E Test Koşusu'),
        projectDir
      );
      setStatusMessage(`✓ ${t('board.app.suiteStarted', undefined, 'Test süiti başarıyla başlatıldı. Canlı telemetri ve ekran görüntüleri izleniyor.')}`);
    } catch (err) {
      console.error(err);
      const message = err instanceof Error ? err.message : t('board.app.serverError', undefined, 'Sunucu hatası');
      setStatusMessage(`⚠ ${t('board.app.suiteStartFailed', { message }, `Test süiti başlatılamadı: ${message}`)}`);
      notify(t('board.app.suiteStartFailed', { message }, `Test süiti başlatılamadı: ${message}`));
    }
  };

  // Replay Modu Hesaplamaları
  const historicalEvent = sortedEvents[replayIndex];

  const displayAgents = useMemo<Agent[]>(() => {
    if (!isReplayMode || !historicalEvent) {
      // Kartların durumu son olaya bakar ve eski kalabilir; MCP koşusunda GERÇEK durum koşudan türetilir:
      // yalnızca sırası gelen ajan çalışıyor/bekliyor görünür, eski olaylardan kalan çalışıyor/bekliyor durumları sönük (boşta) gösterilir.
      const turn = mcpActivity?.turn;
      if (turn && (turn.who === 'idle' || turn.engine === 'mcp_client')) {
        return agents.map((a): Agent => {
          if (turn.agent_id && a.id === turn.agent_id) {
            if (turn.who === 'claude') return { ...a, status: 'WORKING', live_role: 'claude' };
            if (turn.who === 'manager') return { ...a, status: 'PENDING_ACTION', live_role: 'manager' };
            if (turn.who === 'claude_wait') return { ...a, status: 'PENDING_ACTION', live_role: 'waiting' };
            if (turn.who === 'server') return { ...a, status: 'WORKING' };
          }
          return a.status === 'WORKING' || a.status === 'PENDING_ACTION' ? { ...a, status: 'IDLE', live_role: undefined } : a;
        });
      }
      return agents;
    }

    const slice = sortedEvents.slice(0, replayIndex + 1);

    return agents.map(agent => {
      if (agent.id === historicalEvent.from_agent) {
        return {
          ...agent,
          status: ['FAILED', 'ERROR'].includes(String(historicalEvent.status).toUpperCase()) ? 'ERROR' : 'WORKING',
          last_action: historicalEvent.action,
          active_file: historicalEvent.current_file || agent.active_file,
        };
      }
      if (agent.id === historicalEvent.to_agent && historicalEvent.to_agent !== historicalEvent.from_agent) {
        return {
          ...agent,
          status: historicalEvent.action === 'REPORT_BUG' ? 'BUG_FIX' : 'PENDING_ACTION',
          last_action: historicalEvent.action,
        };
      }
      const wasInvolved = slice.some(e => e.from_agent === agent.id || e.to_agent === agent.id);
      return {
        ...agent,
        status: wasInvolved ? 'COMPLETED' : 'IDLE',
      };
    });
  }, [isReplayMode, historicalEvent, agents, sortedEvents, replayIndex, mcpActivity]);

  const displayActiveEdgeId = useMemo(() => {
    if (!isReplayMode || !historicalEvent) return activeEdgeId;
    return `edge-${historicalEvent.from_agent}-${historicalEvent.to_agent}`;
  }, [isReplayMode, historicalEvent, activeEdgeId]);

  const displayEdgeStatus = useMemo(() => {
    if (!isReplayMode || !historicalEvent) return edgeStatus;
    return historicalEvent.status === 'FAILED' ? 'FAILED' : 'SUCCESS';
  }, [isReplayMode, historicalEvent, edgeStatus]);

  const displayTasks = useMemo<KanbanTask[]>(() => {
    if (!isReplayMode || !historicalEvent) return tasks;

    let state: KanbanState = 'BACKLOG';
    let assignee = historicalEvent.to_agent;

    if (historicalEvent.action === 'TASK_DISPATCH' && historicalEvent.from_agent === 'PM') {
      state = 'ARCHITECTURE';
      assignee = 'ARCHITECT';
    } else if (historicalEvent.action === 'TASK_DISPATCH' && historicalEvent.from_agent === 'ARCHITECT') {
      state = 'DEVELOPMENT';
      assignee = 'BACKEND_DEV';
    } else if (historicalEvent.action === 'SUBMIT_CODE' || historicalEvent.action === 'BACKEND_API_EXPOSED') {
      state = 'QA_TESTING';
      assignee = 'QA';
    } else if (historicalEvent.action === 'REPORT_BUG') {
      state = 'DEVELOPMENT';
      assignee = 'BACKEND_DEV';
    } else if (historicalEvent.action === 'APPROVE_BUILD' || historicalEvent.action === 'E2E_SCREENSHOT_CONFIRMED') {
      state = 'DEVOPS_DEPLOY';
      assignee = 'DEVOPS';
    } else if (historicalEvent.action === 'DEPLOY_CONFIRM') {
      state = 'RELEASED';
      assignee = 'PM';
    }

    return [
      {
        id: 'TASK-TIMELINE',
        title: (historicalEvent.payload && historicalEvent.payload.title) || taskPrompt,
        state,
        assignee,
        priority: 'P0',
        details: `[${t('board.app.stepN', { n: replayIndex + 1 }, `Adım ${replayIndex + 1}`)}] ${historicalEvent.action}: ${historicalEvent.current_file || ''}`,
        updated_at: historicalEvent.timestamp
      }
    ];
  }, [isReplayMode, historicalEvent, tasks, taskPrompt, replayIndex, t]);

  // Ayrı sekme: /#claude → yalnızca Claude iletişim görünümü (canlı güncellenir; WebSocket bu sekmede de bağlı)
  if (isClaudePage) {
    return (
      <div className="w-full min-h-screen p-4 sm:p-8 bg-bg text-ink font-sans">
        <div className="max-w-5xl mx-auto space-y-4">
          <div className="flex items-center justify-between gap-3">
            <h1 className="text-lg font-bold flex items-center gap-2"><Plug className="w-5 h-5 text-ac" /> {t('board.app.claudeComm', undefined, 'Claude iletişimi')}{currentProject?.name ? ` · ${currentProject.name}` : ''}</h1>
            <a href="#" onClick={() => setIsClaudePage(false)} className="text-xs font-semibold px-3 py-1.5 rounded-md bg-panel2 border border-line text-ink2 hover:text-ink transition">← {t('board.app.backToBoard', undefined, 'Panoya dön')}</a>
          </div>
          <ClaudePanel activity={mcpActivity} projectName={currentProject?.name} claude={claudePanelData} />
        </div>
      </div>
    );
  }

  return (
    <div className="w-full min-w-[1200px] h-screen flex bg-bg text-ink font-sans">
      {/* Sol ray: modüller tek yerde */}
      <nav id="rail-slot" aria-label={t('board.app.modules', undefined, 'Modüller')} className="w-[68px] shrink-0 bg-[#1B1E27] border-r border-[#262B38] py-3 flex flex-col items-center">
        <div aria-hidden="true" className="w-9 h-9 rounded-[10px] bg-[#3A48CC] text-white flex items-center justify-center font-semibold text-[13px] mb-3 shrink-0">FS</div>
      </nav>
      <div className="flex-1 min-w-0 p-3 flex flex-col gap-2.5 overflow-hidden">
      {/* 1. Üst Telemetri & Sistem Metrikleri Barı (Panel Kartı) */}
      <TelemetryMetrics
        isConnected={isConnected}
        stats={stats}
        serverInfo={serverInfo}
        configSlot={
          <ConfigMenu
            projectName={currentProject?.name}
            projectDir={projectDir}
            onProjectDirChange={setProjectDir}
            onBrowse={() => setIsFolderBrowserOpen(true)}
            onBind={handleBindFolder}
            onReset={resetState}
            onOpenSettings={() => setShowProjectSettings(true)}
          />
        }
      />

      {/* 2. Dinamik Proje Klasörü, Çoklu Proje Seçici & Modül Butonları (Panel Kartı) */}
      <ToolbarPortal>
        <div className="flex items-center gap-2.5 w-full min-w-0">
          <ProjectSwitcher
            currentProject={currentProject}
            projects={projects}
            onSwitchProject={switchProject}
            onAddProject={addProject}
            onDeleteProject={deleteProject}
            onPurgeProject={purgeProject}
          />
          <CurrentSprintPill />
          <FolderBrowser
            isOpen={isFolderBrowserOpen}
            initialPath={projectDir || currentProject?.path || ''}
            onClose={() => setIsFolderBrowserOpen(false)}
            onSelect={(p) => { setProjectDir(p); setIsFolderBrowserOpen(false); }}
          />
          <label className="flex-1 max-w-[520px] min-w-[160px] block">
            <span className="sr-only">{t('common.search')}</span>
            <input
              type="search"
              value={globalQuery}
              onChange={(e) => { const v = e.target.value; setGlobalQuery(v); (window as unknown as { __fsscQuery?: string }).__fsscQuery = v; setActiveView('JIRA_VIEW'); window.dispatchEvent(new CustomEvent('fssc:query', { detail: v })); }}
              placeholder={t('topbar.searchPlaceholder')}
              title={t('topbar.searchTitle')}
              className="w-full h-[34px] bg-sunk border border-line rounded-[9px] px-3 text-[13px] text-ink placeholder:text-ink3 focus:outline-none focus:border-ac"
            />
          </label>
        </div>
      </ToolbarPortal>

      <ToolbarPortal slotId="toolbar-right-slot" cls="contents">
          <ApprovalModeSegment
            mode={settings.approval_mode}
            raisedHands={raisedHands}
            onChangeMode={setApprovalMode}
            onResolveHand={resolveHand}
            onInspectHand={(hand) => {
              setSelectedStepInfo(hand.step_info);
              setIsStepModalOpen(true);
            }}
          />
          <NotificationCenter notifications={notifications} onMarkRead={markNotificationsRead} onClear={clearNotifications} />
          {(settings as { sprint?: { enabled?: boolean } }).sprint?.enabled ? (
            null
          ) : (
          <button
            onClick={handleExecuteRealProject}
            disabled={isExecuting}
            className="px-3.5 py-1 bg-ink text-bg hover:opacity-90 font-bold rounded-md shadow-panel transition flex items-center gap-1.5 text-[11px]"
          >
            <Send className="w-3 h-3" />
            {isExecuting ? t('topbar.executing') : t('topbar.executeBatch')}
          </button>
          )}
      </ToolbarPortal>


      <ToolbarPortal slotId="rail-slot" column>
        <RailButton label={t('rail.board')} active={activeView === 'JIRA_VIEW'} onClick={() => setActiveView('JIRA_VIEW')} title={t('rail.boardTitle')} icon={<Layers />} />
        <RailButton label={t('rail.agentMesh')} active={activeView === 'MESH_VIEW'} onClick={() => setActiveView('MESH_VIEW')} title={t('rail.agentMeshTitle')} icon={<Network />} />
        <RailButton label={t('rail.files')} onClick={() => openFiles()} title={t('rail.filesTitle')} icon={<FolderTree />} />
        <RailButton label={t('rail.docs')} onClick={() => openDocs()} title={t('rail.docsTitle')} icon={<BookOpenText />} />
        <RailButton label={t('rail.deliberation')} onClick={() => setIsDeliberationModalOpen(true)} title={t('rail.deliberationTitle')}
          alert={activeDeliberation?.status === 'AWAITING_APPROVAL' || activeDeliberation?.status === 'AWAITING_PLAN_CHOICE'} icon={<Users />} />
        <RailButton label={t('rail.questions')} onClick={() => setIsQuestionsModalOpen(true)} title={t('rail.questionsTitle')}
          alert={!!openBlocking} badge={openQuestions.length > 0 ? <span className="absolute top-0.5 right-1 text-[9px] font-mono px-1 rounded-full bg-[#262B38] text-[#C5CAD8]">{openQuestions.length}</span> : undefined} icon={<HelpCircle />} />
        <ToolbarMenu
          rail
          label={t('rail.tests')}
          icon={<MonitorCheck />}
          title={t('rail.testsTitle')}
          items={[
            { key: 'e2e', label: t('menu.playwrightE2e'), icon: <MonitorCheck className="w-3.5 h-3.5 text-info" />, title: t('menu.playwrightE2eTitle'),
              badge: playwrightReports.length > 0 ? <span className="bg-infod text-info border border-info/30 text-[9px] px-1.5 rounded-full font-mono font-bold">{playwrightReports.length}</span> : undefined,
              onClick: () => setIsTesterModalOpen(true) },
            { key: 'testing', label: t('menu.testManagement'), icon: <FlaskConical className="w-3.5 h-3.5 text-ac" />, title: t('menu.testManagementTitle'), onClick: () => setIsTestingOpen(true) },
            { key: 'tests-only', label: isExecuting ? t('menu.testingInProgress') : t('menu.runTestsOnly'), icon: <Play className="w-3 h-3 fill-current text-warn" />,
              title: t('menu.runTestsOnlyTitle'), disabled: isExecuting, onClick: handleRunTestsOnly },
          ]}
        />
        <RailButton label={t('rail.reports')} active={activeView === 'REPORTS_VIEW'} onClick={() => setActiveView('REPORTS_VIEW')} title={t('rail.reportsTitle')} icon={<BarChart3 />} />
        <div className="flex-1" />
        <ToolbarMenu
          rail
          label={t('rail.settings')}
          icon={<Settings2 />}
          title={t('rail.settingsTitle')}
          items={[
            { key: 'project-settings', label: t('menu.projectSettings'), icon: <Settings2 className="w-3.5 h-3.5 text-warn" />, title: t('menu.projectSettingsTitle'), onClick: () => setShowProjectSettings(true) },
            { key: 'specs', label: t('menu.specs'), icon: <FolderUp className="w-3.5 h-3.5 text-ac" />, title: t('menu.specsTitle'), onClick: () => setIsSpecModalOpen(true),
              badge: uploadedSpecs.length > 0 ? <span className="bg-ac text-onac text-[9px] px-1.5 rounded-full font-mono font-bold">{uploadedSpecs.length}</span> : undefined },
            { key: 'decisions', label: t('menu.decisions'), icon: <Settings2 className="w-3.5 h-3.5 text-ac" />, alert: !!decisionsPending, title: t('menu.decisionsTitle'), onClick: () => setIsDecisionsModalOpen(true),
              badge: decisionsPending ? <span className="text-[9px] font-mono font-bold">{t('menu.pendingBadge')}</span> : undefined },
            { key: 'runs', label: t('menu.runs'), icon: <History className="w-3.5 h-3.5 text-ac" />, title: t('menu.runsTitle'),
              badge: runs.length > 0 ? <span className="text-[9px] font-mono px-1 rounded bg-acd text-ac border border-ac/30">{runs.length}</span> : undefined, onClick: () => setIsRunHistoryOpen(true) },
            { key: 'add-agent', label: t('menu.addAgent'), icon: <UserPlus className="w-3.5 h-3.5 text-ac" />, title: t('menu.addAgentTitle'), onClick: () => setIsAgentModalOpen(true) },
            { key: 'management', label: t('menu.management'), icon: <ClipboardList className="w-3.5 h-3.5 text-ac" />, title: t('menu.managementTitle'), onClick: () => setIsManagementOpen(true) },
            { key: 'model', label: `${t('menu.model')}: ${modelConfig?.model_id?.replace('claude-', '')?.replace('gemini-', '') || '2.5-pro'}`, icon: <Zap className="w-3.5 h-3.5 text-warn" />, title: t('menu.modelTitle'), onClick: () => setIsModelModalOpen(true) },
            { key: 'claude', label: t('menu.claude'), icon: <Plug className="w-3.5 h-3.5 text-ac" />, title: t('menu.claudeTitle'), onClick: () => setIsClaudeModalOpen(true) },
            { key: 'telemetry', label: t('menu.telemetry'), icon: <Terminal className="w-3.5 h-3.5 text-ac" />, title: t('menu.telemetryTitle'), onClick: () => { window.dispatchEvent(new Event('fssc:open-telemetry')); } },
            { key: 'design-start', label: t('menu.designStart'), icon: <Palette className="w-3.5 h-3.5 text-ac" />, title: t('menu.designStartTitle'),
              onClick: async () => { try { const brief = await promptDialog(t('banners.designBriefPrompt', undefined, 'Tasarımdan ne bekliyorsun? (örn. tüm ekranlar için profesyonel mockup ve ekran akışları). Boş bırakırsan genel yenileme istenir.'), '', { title: t('menu.designStart'), multiline: true }); if (brief === null) return; const r = await fetch('/api/design/start', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ brief }) }); const j = await r.json(); notify(r.ok ? t('banners.designQueued', { key: j.key || j.issue_id }) : (j.error || 'Error')); } catch { notify(t('banners.serverUnreachable')); } } },
            { key: 'link-orphans', label: t('menu.linkOrphans'), icon: <FolderTree className="w-3.5 h-3.5 text-ac" />, title: t('menu.linkOrphansTitle'),
              onClick: async () => {
                try {
                  const plan = await fetch('/api/jira/link-orphans', { method: 'POST' }).then(r => r.json());
                  if (!plan.total) { notify(t('banners.noOrphans'), 'success'); return; }
                  const ok = await confirmDialog(t('banners.linkConfirmPrompt', { total: plan.total, linked: plan.linked, unresolved: plan.unresolved }), { title: t('menu.linkOrphans'), confirmLabel: t('common.apply') });
                  if (!ok) return;
                  const res = await fetch('/api/jira/link-orphans?apply=true', { method: 'POST' }).then(r => r.json());
                  notify(t('banners.linkSuccess', { linked: res.linked, unresolved: res.unresolved }), 'success');
                } catch { notify(t('banners.serverUnreachable')); }
              } },
            { key: 'restore-agents', label: t('menu.restoreAgents'), icon: <Users className="w-3.5 h-3.5 text-ac" />, title: t('menu.restoreAgentsTitle'),
              onClick: async () => { try { const j = await fetch('/api/agents/restore-defaults', { method: 'POST' }).then(r => r.json()); notify(j.restored?.length ? t('banners.agentsRestored', { names: j.restored.join(', ') }) : t('banners.noAgentsToRestore'), j.restored?.length ? 'success' : 'info'); } catch { notify(t('banners.serverUnreachable')); } } },
            { key: 'budget-page', label: t('menu.budgetPage'), icon: <Settings2 className="w-3.5 h-3.5 text-warn" />, title: t('menu.budgetPageTitle'), onClick: () => { window.open('/budget', '_blank', 'noopener'); } },
          ]}
        />
      </ToolbarPortal>

      {/* Durum Bildirim Satırı (varsa) */}
      {statusMessage && (
        <div className="bg-okd border border-ok/40 rounded-card px-4 py-1.5 text-[11px] font-mono text-ok flex items-center gap-2 shadow-xs shrink-0">
          <Sparkles className="w-3.5 h-3.5 text-ok animate-pulse shrink-0" />
          <span className="flex-1">{statusMessage}</span>
          <button type="button" aria-label={t('board.app.closeMessage', undefined, 'Mesajı kapat')} onClick={() => setStatusMessage('')} className="text-ok/70 hover:text-ok shrink-0">✕</button>
        </div>
      )}

      {/* Proje seviyesinde duraklatma (sprint bütçesi doldu) */}
      <ProjectPausedBanner />
      <SprintBlockedBanner />
      <GoalsStrip />
      {showProjectSettings && <ProjectSettingsModal onClose={() => setShowProjectSettings(false)} />}

      {/* Faz B: Kuyruktaki / aktif koşu şeridi (MCP istemcisi promptu, durum, iptal) */}
      {activeRun && (
        <QueuedRunBanner
          run={activeRun}
          projectName={currentProject?.name}
          connectedClients={connectedClients}
          onCancel={cancelRun}
          onPause={pauseRun}
          onResume={resumeRun}
          onSendNote={sendRunNote}
          liveThinking={liveThinking}
        />
      )}

      {!activeRun && resumableRun && (
        <QueuedRunBanner
          run={resumableRun}
          projectName={currentProject?.name}
          connectedClients={connectedClients}
          onCancel={cancelRun}
          onResumeAbandoned={handleResumeAbandoned}
          onRestartFresh={handleRestartFresh}
          liveThinking={liveThinking}
        />
      )}

      <SprintKpiStrip />

      {/* Engelleyici soru şeridi: cevaplanana kadar sprint ilerlemez */}
      {openBlocking > 0 && (
        <div className="bg-warnd border border-warn/50 rounded-card px-4 py-2 flex items-center justify-between gap-3 shadow-xs shrink-0" role="alert">
          <div className="flex items-center gap-3 min-w-0">
            <HelpCircle className="w-4 h-4 text-warn shrink-0 animate-pulse" />
            <span className="text-xs text-ink truncate">
              <strong className="text-warn">{t('banners.answerRequired')}</strong>{' '}
              {t('banners.blockingQuestionsCount', { count: openBlocking, ids: openQuestions.filter(q => q.blocking).map(q => q.id).join(', ') })}
            </span>
          </div>
          <button
            onClick={() => setIsQuestionsModalOpen(true)}
            className="px-3 py-1 rounded-lg bg-warn text-onac font-bold text-xs shrink-0"
          >
            {t('banners.answerQuestionsBtn')}
          </button>
        </div>
      )}

      {/* Devam Onayı Bekleyen Adım Bildirim Şeridi */}
      {pendingApproval && (
        <div className="bg-warnd border border-warn/40 rounded-card px-4 py-2 flex items-center justify-between shadow-xs shrink-0">
          <div className="flex items-center space-x-3">
            <div className="w-2.5 h-2.5 rounded-full bg-warn animate-ping"></div>
            <span className="text-xs font-mono font-bold text-warn">
              {pendingApproval.kind === 'decisions' ? t('banners.techDecisionsPending') : t('banners.stepApprovalPending')}
            </span>
            <span className="text-xs text-ink font-medium">
              {pendingApproval.kind === 'decisions'
                ? t('banners.techDecisionsDesc', { order: pendingApproval.order, agent: pendingApproval.next_agent_name || pendingApproval.next_agent_id || '' })
                : t('banners.stepApprovalDesc', { order: pendingApproval.order, agent: pendingApproval.agent_name, title: pendingApproval.title })}
            </span>
          </div>
          {pendingApproval.kind === 'decisions' ? (
            <div className="flex items-center space-x-2">
              <button
                onClick={() => setIsDecisionsModalOpen(true)}
                className="px-3.5 py-1.5 bg-ink text-bg font-bold text-xs rounded-md transition shadow-panel flex items-center gap-1 hover:opacity-90"
              >
                {t('banners.makeDecisions')}
              </button>
              <button
                onClick={() => handleApproveStep('PROCEED')}
                className="px-3.5 py-1.5 bg-panel border border-line text-ink font-bold text-xs rounded-md transition shadow-xs hover:border-line2"
                title={t('banners.continueRecommended')}
              >
                {t('banners.continueRecommended')}
              </button>
            </div>
          ) : (
          <div className="flex items-center space-x-2">
            <button
              onClick={() => {
                setSelectedStepInfo(pendingApproval);
                setIsStepModalOpen(true);
              }}
              className="px-3.5 py-1.5 bg-panel border border-line text-ink font-bold text-xs rounded-md transition shadow-xs hover:border-line2 flex items-center space-x-1.5"
            >
              <span>🔍 {t('banners.reviewAndApprove')}</span>
              <ExternalLink className="w-3.5 h-3.5" />
            </button>
            <button
              onClick={() => handleApproveStep('PROCEED')}
              className="px-3.5 py-1.5 bg-ink text-bg font-bold text-xs rounded-md transition shadow-panel flex items-center gap-1 hover:opacity-90"
            >
              ✓ {t('common.proceed')}
            </button>
          </div>
          )}
        </div>
      )}

      <ClaudeModal
        isOpen={isClaudeModalOpen}
        onClose={() => setIsClaudeModalOpen(false)}
        activity={mcpActivity}
        projectName={currentProject?.name}
        claude={claudePanelData}
      />

      <QuestionsModal
        isOpen={isQuestionsModalOpen}
        onClose={() => setIsQuestionsModalOpen(false)}
        questions={queueQuestions}
        onAnswer={answerQuestion}
      />

      <TechDecisionsModal
        isOpen={isDecisionsModalOpen}
        onClose={() => setIsDecisionsModalOpen(false)}
        questions={techQuestions}
        decisions={techDecisions}
        pending={decisionsPending}
        onSave={saveDecisions}
        onReset={resetDecisions}
      />

      {/* 3. Canlı LLM Düşünce & İşlem Akışı (Thinking Stream & Non-Technical Chat) */}
      {/* Koşu yokken (terk edilmiş/bitmiş) eski düşünce satırı yer kaplamaz; olaylar alttaki telemetri çekmecesinde */}
      {(activeRun || isExecuting) && (
        <div className="bg-panel border border-line rounded-panel shadow-panel px-3 py-1.5 shrink-0 overflow-hidden">
          <LiveThinkingStream events={events} isExecuting={isExecuting} liveThinking={liveThinking} agents={agents} />
        </div>
      )}

      {/* 4. Ana Çalışma Alanı */}
      <div className="flex-1 flex overflow-hidden gap-3.5 min-h-0">
        {activeView === 'REPORTS_VIEW' ? (
          <ReportsView />
        ) : activeView === 'MESH_VIEW' ? (
          /* Görünüm 1: Ajan Ağı / Ofis + Kanban + Olay Akışı */
          <div className="flex-1 flex overflow-hidden gap-3.5 min-h-0">
            {/* Sol: Görsel Ajan Ağı (60%) + Kanban (40%) */}
            <div className="flex-1 flex flex-col overflow-hidden gap-3.5 min-h-0">
              {/* React Flow / Pixel-Art Office Canvas Panel Card */}
              <div className="flex-1 min-h-0 bg-panel border border-line rounded-panel shadow-panel flex flex-col overflow-hidden">
                {/* Panel Başlığı & Segment Değiştirici */}
                <div className="px-4 py-2 border-b border-line flex items-center justify-between bg-panel2/60 shrink-0 select-none">
                  <div className="flex items-center gap-2">
                    <span className="w-2 h-2 rounded-full bg-ac animate-pulse" />
                    <h2 className="text-xs font-bold text-ink font-mono uppercase tracking-wider">
                      {meshView === 'ofis' ? t('board.app.titleOffice', undefined, 'Ajan Ofisi • Pixel-Art Simülasyonu') : meshView === 'petek' ? t('board.app.titleHoneycomb', undefined, 'Petek Topolojisi • Takımlar & Toplantı Odası') : t('board.app.titleMesh', undefined, 'Ajan İletişim Ağı & Topoloji')}
                    </h2>
                  </div>
                  {/* Topoloji / Ofis Segment Düğmesi */}
                  <div className="flex items-center bg-sunk p-0.5 rounded-lg border border-line text-xs font-mono">
                    <button
                      onClick={() => setMeshView('topoloji')}
                      className={`px-3 py-1 rounded-md transition font-medium ${
                        meshView === 'topoloji'
                          ? 'bg-panel text-ink shadow-panel font-bold'
                          : 'text-ink3 hover:text-ink'
                      }`}
                    >
                      {t('views.topology')}
                    </button>
                    {SHOW_HONEYCOMB && (
                      <button
                        onClick={() => setMeshView('petek')}
                        className={`px-3 py-1 rounded-md transition font-medium ${
                          meshView === 'petek'
                            ? 'bg-panel text-ink shadow-panel font-bold'
                            : 'text-ink3 hover:text-ink'
                        }`}
                      >
                        {t('views.honeycomb')}
                      </button>
                    )}
                    {SHOW_PIXEL_OFFICE && (
                      <button
                        onClick={() => setMeshView('ofis')}
                        className={`px-3 py-1 rounded-md transition font-medium ${
                          meshView === 'ofis'
                            ? 'bg-panel text-ink shadow-panel font-bold'
                            : 'text-ink3 hover:text-ink'
                        }`}
                      >
                        {t('views.office')}
                      </button>
                    )}
                  </div>
                </div>

                {/* Tuval Gövdesi */}
                <div className={`flex-1 min-h-0 relative p-1 ${meshView === 'ofis' ? 'overflow-auto flex items-center justify-center' : 'overflow-hidden'}`}>
                  {meshView === 'petek' ? (
                    <HoneycombTopology
                      agents={displayAgents}
                      recentEvents={events}
                      gathering={gathering}
                      selectedAgentId={selectedAgentId}
                      onSelectAgent={setSelectedAgentId}
                      refreshKey={`${currentProject?.id || ''}:${teamsVersion}`}
                    />
                  ) : meshView === 'ofis' ? (
                    <AgentOffice
                      agents={displayAgents}
                      activeEdgeId={displayActiveEdgeId}
                      edgeStatus={displayEdgeStatus}
                      onSelectAgent={setSelectedAgentId}
                      selectedAgentId={selectedAgentId}
                      gathering={gathering}
                    />
                  ) : (
                    <AgentMesh 
                      agents={displayAgents} 
                      activeEdgeId={displayActiveEdgeId} 
                      edgeStatus={displayEdgeStatus} 
                      activeDialogue={latestInteraction?.friendly_dialogue}
                      activeFromAgent={latestInteraction?.from_agent}
                      activeToAgent={latestInteraction?.to_agent}
                      activeTimestamp={latestInteraction?.timestamp}
                      selectedAgentId={selectedAgentId}
                      onSelectAgent={setSelectedAgentId}
                      recentEvents={events}
                    />
                  )}
                </div>
              </div>

            </div>
          </div>
        ) : (
          /* Görünüm 2: Jira Agile Board (tek kart: ek sarmalayıcı yok) */
          <div className="flex-1 min-h-0 overflow-hidden flex flex-col">
            <JiraBoard
              key={currentProject?.id || 'no-project'}
              issues={jiraIssues}
              onExecuteBatch={handleExecuteJiraBatch}
              onUpdateStatus={async (id, status) => {
                await updateJiraIssue(id, { status });
              }}
              onAddIssue={async (issue) => {
                await updateJiraIssue(issue.id!, issue);
              }}
              isExecuting={isExecuting}
              stepByStepMode={stepByStepMode}
              onToggleStepMode={toggleStepMode}
              onInspectTask={handleInspectTask}
              onInspectAudit={(issue) => setAuditIssue(issue)}
              pendingStepOrder={pendingApproval?.order}
              onOpenSpecVault={() => setIsSpecModalOpen(true)}
              projectName={currentProject?.name}
              projectPath={currentProject?.path}
              onRunSingle={(order) => handleExecuteJiraBatch([order])}
              runs={runs}
              jira={jiraApi}
              sprintVersion={sprintVersion}
              sprintMode={!!(settings as { sprint?: { enabled?: boolean } }).sprint?.enabled}
              attachmentSources={attachmentSources}
            />
          </div>
        )}
      </div>

      {/* 5. Alta sabit çubuk: Timeline (kapalı başlar) + Canlı Sprint & Kanban (kapalı başlar) */}
      <BottomDock
        tasks={displayTasks}
        issues={jiraIssues}
        onAddAuditNote={(id, n) => recordTaskAudit(id, 'USER', 'USER_NOTE', n)}
        events={events}
        isReplayMode={isReplayMode}
        replayIndex={replayIndex}
        onToggleReplayMode={(mode) => setIsReplayMode(mode)}
        onSeek={(idx) => setReplayIndex(idx)}
      />
      {/* Sağa sabit, açılır/kapanır canlı telemetri günlüğü (yeni olayda 20 sn bildirim) */}
      <TelemetryDock events={events} currentProjectId={currentProject?.id} />
      {/* Dosya / commit / döküman görüntüleyicileri (kanıt chip'leri ve Dökümanlar düğmesi açar) */}
      <ProjectViewers />

      {/* 5. Modaller */}
      <SpecUploadModal
        isOpen={isSpecModalOpen}
        onClose={() => setIsSpecModalOpen(false)}
        specs={uploadedSpecs}
        runs={runs}
        onUpload={uploadSpec}
        onAnalyzeSpec={analyzeSpecAndGenerateTasks}
        onDeleteSpec={deleteSpec}
        onDeleteSpecFile={deleteSpecFile}
        onUpdateSpec={updateSpec}
        projectName={currentProject?.name || 'demo_project'}
      />

      <PlaywrightReportDrawer
        isOpen={isTesterModalOpen}
        onClose={() => setIsTesterModalOpen(false)}
        reports={playwrightReports}
        testProfiles={testProfiles}
        onRunTest={runPlaywrightTest}
        onRunQaSuite={runTestsOnlySuite}
        onSaveProfile={saveTestProfile}
        onDeleteProfile={deleteTestProfile}
      />

      <TestManagementModal isOpen={isTestingOpen} onClose={() => setIsTestingOpen(false)} version={serverVersions.testing} />
      <ManagementCenterModal isOpen={isManagementOpen} onClose={() => setIsManagementOpen(false)} versions={serverVersions} />

      <AgentManagerModal
        isOpen={isAgentModalOpen}
        onClose={() => setIsAgentModalOpen(false)}
        agents={agents}
        currentProject={currentProject}
        onAddAgent={addCustomAgent}
        onUpdateAgent={updateAgent}
        onDeleteAgent={deleteAgent}
        fetchAgentPrompt={fetchAgentPrompt}
        saveAgentPrompt={saveAgentPrompt}
        restoreAgentVersion={restoreAgentVersion}
        inheritAgentStandard={inheritAgentStandard}
        promoteAgentToGlobal={promoteAgentToGlobal}
      />

      <StepInspectorModal
        isOpen={isStepModalOpen}
        onClose={() => setIsStepModalOpen(false)}
        stepInfo={selectedStepInfo}
        onApprove={handleApproveStep}
        isPendingApproval={!!pendingApproval && pendingApproval.order === selectedStepInfo?.order}
        onOpenQuestions={() => { setIsStepModalOpen(false); setIsQuestionsModalOpen(true); }}
      />

      {/* D1: Ajan zaman çizelgesi çekmecesi (topoloji kartı / ofis avatarı tıklaması) */}
      <AgentTimelineDrawer
        agentId={selectedAgentId}
        agents={agents}
        liveEvents={events}
        projectId={currentProject?.id}
        onClose={() => setSelectedAgentId(null)}
        onSelectAgent={setSelectedAgentId}
      />

      {/* D5: Koşu geçmişi çekmecesi */}
      <RunHistoryDrawer
        isOpen={isRunHistoryOpen}
        runs={runs}
        onClose={() => setIsRunHistoryOpen(false)}
        onRerun={(orders) => handleExecuteJiraBatch(orders)}
        onCancel={cancelRun}
      />

      <ModelSwitcherModal
        isOpen={isModelModalOpen}
        onClose={() => setIsModelModalOpen(false)}
        currentProject={currentProject}
        modelConfig={modelConfig}
        onUpdateModelConfig={updateModelConfig}
        settings={settings}
        connectedClients={connectedClients}
        onUpdateSettings={updateSettings}
      />

      <DeliberationModal
        isOpen={isDeliberationModalOpen}
        onClose={() => setIsDeliberationModalOpen(false)}
        session={activeDeliberation}
        onStartDeliberation={runDeliberation}
        onChoosePlan={choosePlan}
      />

      <TaskAuditModal
        isOpen={!!auditIssue}
        onClose={() => setAuditIssue(null)}
        issue={auditIssue}
        onAddAuditNote={(id, n) => recordTaskAudit(id, 'USER', 'USER_NOTE', n)}
      />
      </div>
    </div>
  );
}

export default App;
