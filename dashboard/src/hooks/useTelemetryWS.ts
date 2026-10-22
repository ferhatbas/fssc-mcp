import { useState, useEffect, useRef, useCallback } from 'react';
import { api, wsUrl, DEFAULT_TARGET_URL } from '../config';
import { translate } from '../i18n';
import {
  Agent,
  TechQuestion,
  QueueQuestion,
  McpActivity,
  TechDecisions,
  KanbanTask,
  TelemetryEvent,
  TelemetryStats,
  ProjectInfo,
  JiraIssue,
  UploadedSpec,
  PlaywrightReport,
  TestUserProfile,
  StepApprovalInfo,
  AgentPromptInfo,
  LLMModelConfig,
  DeliberationSession,
  PipelineRun,
  EngineSettings,
  McpClientInfo,
  LiveThinking,
  ExecutionEngine,
  RaisedHand,
  ClaudeLogEntry,
  ClaudeLogQuery,
  ClaudeLogPage,
  ClaudeBridgeState,
  ClaudeBridgeConfig,
  ClaudeBridgeSessionFile,
  ClaudeSessionEvent,
  ClaudeStatus,
  ClaudePanelData,
  TranscriptEvent,
  TranscriptEventsPage,
  RunnerSetup,
  JiraApi,
  JiraIssueStatus,
  JiraLinkType
} from '../types/telemetry';

/** Bu WebSocket mesajları Claude iletişim / "sıra kimde" görünümünü yeniler. */
import { AppNotification, describeEvent, eventGroup } from '../lib/serverEvents';

const MCP_REFRESH_TYPES = new Set(['MCP_CALL', 'MCP_CLIENT_SEEN', 'RUN_UPDATED', 'STEP_WAITING_APPROVAL', 'STEP_APPROVED', 'RUN_PAUSED', 'RUN_RESUMED']);

const DEFAULT_AGENTS: Agent[] = [
  { id: 'PM', name: 'Product Manager', role: 'PM', status: 'IDLE', tokens_in: 0, tokens_out: 0, total_tokens: 0, last_action: 'READY', last_seen: '' },
  { id: 'ARCHITECT', name: 'Tech Lead / Architect', role: 'ARCHITECT', status: 'IDLE', tokens_in: 0, tokens_out: 0, total_tokens: 0, last_action: 'READY', last_seen: '' },
  { id: 'BACKEND_DEV', name: 'Senior Backend Developer', role: 'BACKEND_DEV', status: 'IDLE', tokens_in: 0, tokens_out: 0, total_tokens: 0, last_action: 'READY', last_seen: '' },
  { id: 'DESIGNER', name: 'UI/UX Designer', role: 'DESIGNER', status: 'IDLE', tokens_in: 0, tokens_out: 0, total_tokens: 0, last_action: 'READY', last_seen: '' },
  { id: 'FRONTEND_DEV', name: 'Senior Frontend Developer', role: 'FRONTEND_DEV', status: 'IDLE', tokens_in: 0, tokens_out: 0, total_tokens: 0, last_action: 'READY', last_seen: '' },
  { id: 'QA', name: 'Lead QA Engineer', role: 'QA', status: 'IDLE', tokens_in: 0, tokens_out: 0, total_tokens: 0, last_action: 'READY', last_seen: '' },
  { id: 'E2E_TESTER', name: 'Playwright E2E Tester', role: 'E2E_TESTER', status: 'IDLE', tokens_in: 0, tokens_out: 0, total_tokens: 0, last_action: 'READY', last_seen: '' },
  { id: 'DEVOPS', name: 'DevOps & SRE', role: 'DEVOPS', status: 'IDLE', tokens_in: 0, tokens_out: 0, total_tokens: 0, last_action: 'READY', last_seen: '' },
  { id: 'PO', name: 'Product Owner', role: 'PO', status: 'IDLE', tokens_in: 0, tokens_out: 0, total_tokens: 0, last_action: 'READY', last_seen: '' },
  { id: 'REPORTER', name: 'Project Reporter', role: 'REPORTER', status: 'IDLE', tokens_in: 0, tokens_out: 0, total_tokens: 0, last_action: 'READY', last_seen: '' },
  { id: 'DOCUMENTOR', name: 'Documentation Lead', role: 'DOCUMENTOR', status: 'IDLE', tokens_in: 0, tokens_out: 0, total_tokens: 0, last_action: 'READY', last_seen: '' },
  { id: 'SCM', name: 'SCM Manager', role: 'SCM', status: 'IDLE', tokens_in: 0, tokens_out: 0, total_tokens: 0, last_action: 'READY', last_seen: '' },
];

export function useTelemetryWS() {
  const [isConnected, setIsConnected] = useState<boolean>(false);
  const [projects, setProjects] = useState<ProjectInfo[]>([]);
  const [currentProject, setCurrentProject] = useState<ProjectInfo | null>(null);
  const [agents, setAgents] = useState<Agent[]>(DEFAULT_AGENTS);
  const [tasks, setTasks] = useState<KanbanTask[]>([]);
  const [jiraIssues, setJiraIssues] = useState<JiraIssue[]>([]);
  const [serverVersions, setServerVersions] = useState<{ plan: number; meetings: number; learning: number; testing: number }>({ plan: 0, meetings: 0, learning: 0, testing: 0 });   // G8: olay → ekran tazeleme sayaçları
  const [notifications, setNotifications] = useState<AppNotification[]>([]);                                                                                                   // G8: bildirim merkezi
  const [sprintVersion, setSprintVersion] = useState<number>(0);   // G5: SPRINT_* olaylarında artar (sprint panosu yeniler)
  const [uploadedSpecs, setUploadedSpecs] = useState<UploadedSpec[]>([]);
  const [playwrightReports, setPlaywrightReports] = useState<PlaywrightReport[]>([]);
  const [testProfiles, setTestProfiles] = useState<TestUserProfile[]>([]);
  const [events, setEvents] = useState<TelemetryEvent[]>([]);
  const [stats, setStats] = useState<TelemetryStats>({
    total_events: 0,
    total_tokens: 0,
    active_tasks_count: 0,
    start_time: new Date().toISOString()
  });
  const [activeEdgeId, setActiveEdgeId] = useState<string | null>(null);
  const [edgeStatus, setEdgeStatus] = useState<'SUCCESS' | 'FAILED'>('SUCCESS');

  // Aktif LLM Model & Sağlayıcı (Gemini vs Claude)
  const [modelConfig, setModelConfig] = useState<LLMModelConfig>({
    provider: 'claude',
    model_id: 'claude-sonnet-5-5',
    temperature: 0.2,
    max_tokens: 8192
  });

  // Adım Adım İnceleme & Devam Onayı Durumları (Aksi seçilmedikçe ilerlemesin)
  const [pendingApproval, setPendingApproval] = useState<StepApprovalInfo | null>(null);
  const [stepByStepMode, setStepByStepMode] = useState<boolean>(true);

  // Ajanlar Arası Müzakere (Deliberation Engine)
  const [activeDeliberation, setActiveDeliberation] = useState<DeliberationSession | null>(null);

  // Sunucu tarafında bir pipeline / test süiti koşusu sürüyor mu? (JIRA_BATCH_COMPLETED / TEST_SUITE_COMPLETED ile kapanır)
  const [isExecuting, setIsExecuting] = useState<boolean>(false);
  const [activeRunId, setActiveRunId] = useState<string | null>(null);
  const [lastRunStatus, setLastRunStatus] = useState<{ type: string; status: string; at: string } | null>(null);

  // Faz B: koşu kayıtları, motor ayarları, bağlı MCP istemcileri ve canlı düşünce akışı
  const [runs, setRuns] = useState<PipelineRun[]>([]);
  const [activeRun, setActiveRun] = useState<PipelineRun | null>(null);
  const [settings, setSettings] = useState<EngineSettings>({ execution_engine: 'mcp_client', approval_mode: 'every_step', pacing: 'natural' });
  const [techQuestions, setTechQuestions] = useState<TechQuestion[]>([]);
  // Claude (MCP istemcisi) iletişimi: şimdi sıra kimde, bağlantı durumu, son araç çağrıları
  const [mcpActivity, setMcpActivity] = useState<McpActivity | null>(null);
  // G2: Claude köprüsü — iki yönlü etkileşim günlüğü (canlı), başsız oturum durumu/olayları, transkript aynası olayları
  const [claudeLog, setClaudeLog] = useState<ClaudeLogEntry[]>([]);
  const [claudeSession, setClaudeSession] = useState<{ state: ClaudeBridgeState | null; events: ClaudeSessionEvent[] }>({ state: null, events: [] });
  const [transcriptEvents, setTranscriptEvents] = useState<TranscriptEvent[]>([]);
  // Soru kuyruğu (sprint toplantı soruları + teknoloji gereksinimi soruları): yönetici cevaplar
  const [queueQuestions, setQueueQuestions] = useState<QueueQuestion[]>([]);
  const [techDecisions, setTechDecisions] = useState<TechDecisions | null>(null);
  const [decisionsPending, setDecisionsPending] = useState<boolean>(false);
  const [connectedClients, setConnectedClients] = useState<McpClientInfo[]>([]);
  const [liveThinking, setLiveThinking] = useState<LiveThinking | null>(null);
  const [teamsVersion, setTeamsVersion] = useState<number>(0);
  const [raisedHands, setRaisedHands] = useState<RaisedHand[]>([]);

  const applyRunUpdate = (run: PipelineRun) => {
    setRuns(prev => {
      const idx = prev.findIndex(r => r.run_id === run.run_id);
      const next = idx >= 0 ? prev.map(r => (r.run_id === run.run_id ? run : r)) : [run, ...prev];
      return next.sort((a, b) => (a.created_at < b.created_at ? 1 : -1)).slice(0, 50);
    });
    setActiveRun(prev => {
      if (!run.is_terminal) return run;
      return prev && prev.run_id === run.run_id ? null : prev;
    });
  };

  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const activeTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const reconnectAttemptRef = useRef<number>(0);
  const isUnmountingRef = useRef<boolean>(false);

  /** Sunucu olayları eskiden yeniye gönderir; istemci dizisi daima YENİDEN ESKİYE tutulur. */
  const normalizeEvents = (list: TelemetryEvent[] | undefined | null): TelemetryEvent[] =>
    Array.isArray(list) ? [...list].reverse() : [];

  const refreshProjects = useCallback(async () => {
    try {
      const res = await fetch(api('/api/projects'));
      if (res.ok) {
        const data = await res.json();
        setProjects(data.projects || []);
        if (data.active_project_id && data.projects) {
          const found = data.projects.find((p: ProjectInfo) => p.id === data.active_project_id);
          if (found) setCurrentProject(found);
        }
      }
    } catch (e) {
      console.error('Error fetching projects:', e);
    }
  }, []);

  const connect = useCallback(() => {
    if (isUnmountingRef.current) return;

    try {
      const ws = new WebSocket(wsUrl());
      wsRef.current = ws;

      ws.onopen = () => {
        reconnectAttemptRef.current = 0;
        setIsConnected(true);
        refreshProjects();
      };

      ws.onmessage = (messageEvent) => {
        try {
          const data = JSON.parse(messageEvent.data);

          // Claude bir araç çağırdı ya da koşu/onay durumu değişti: "sıra kimde" bilgisini yenile (diğer işleyicilere dokunmadan)
          if (MCP_REFRESH_TYPES.has(String(data.type))) refreshMcpActivity();

          // G8: sunucu olayı → ilgili ekranı tazele ve (önemliyse) bildirim merkezine düşür
          const group = eventGroup(String(data.type));
          if (group) setServerVersions(v => ({ ...v, [group]: v[group] + 1 }));
          const note = describeEvent(data);
          if (note) setNotifications(prev => [{ ...note, id: `${Date.now()}-${prev.length}`, at: new Date().toISOString(), read: false }, ...prev].slice(0, 100));
          if (data.type === 'LAYOUT_MIGRATED') refreshProjects();
          if (data.type === 'TECH_REQUIREMENTS_UPDATED') refreshQuestions();

          if (data.type === 'INITIAL_STATE') {
            if (data.projects) setProjects(data.projects);
            setCurrentProject(data.active_project || null);
            if (data.agents && data.agents.length > 0) setAgents(data.agents);
            if (data.tasks) setTasks(data.tasks);
            if (data.jira_issues) setJiraIssues(data.jira_issues);
            if (data.uploaded_specs) setUploadedSpecs(data.uploaded_specs);
            if (data.playwright_reports) setPlaywrightReports(data.playwright_reports);
            if (data.test_profiles) setTestProfiles(data.test_profiles);
            if (data.events) setEvents(normalizeEvents(data.events));
            if (data.stats) setStats(data.stats);
            if (data.model_config) setModelConfig(data.model_config);
            if (data.pending_step_approval !== undefined) setPendingApproval(data.pending_step_approval);
            if (data.step_by_step_mode !== undefined) setStepByStepMode(data.step_by_step_mode);
            if (data.active_deliberation) setActiveDeliberation(data.active_deliberation);
            if (data.settings) setSettings(prev => ({ ...prev, ...data.settings }));
            if (data.runs) setRuns(data.runs);
            setActiveRun(data.active_run || null);
            if (data.connected_clients) setConnectedClients(data.connected_clients);
            if (data.raised_hands) setRaisedHands(data.raised_hands);
            // Sayfa yenileme sonrası kurtarma: sunucuda koşu sürüyorsa 'çalışıyor' durumunu geri yükle
            const runId: string | null = data.active_run_id || (data.active_run ? data.active_run.run_id : null);
            setActiveRunId(runId);
            setIsExecuting(!!runId || !!data.pending_step_approval);
          } else if (data.type === 'PROJECT_SWITCHED') {
            setCurrentProject(data.active_project || null);
            if (data.agents) setAgents(data.agents);
            setTasks(data.tasks || []);
            setJiraIssues(data.jira_issues || []);
            setUploadedSpecs(data.uploaded_specs || []);
            setPlaywrightReports(data.playwright_reports || []);
            if (data.test_profiles) setTestProfiles(data.test_profiles);
            setEvents(normalizeEvents(data.events));
            if (data.stats) setStats(data.stats);
            if (data.model_config) setModelConfig(data.model_config);
            if (data.pending_step_approval !== undefined) setPendingApproval(data.pending_step_approval);
            if (data.step_by_step_mode !== undefined) setStepByStepMode(data.step_by_step_mode);
            if (data.active_deliberation) setActiveDeliberation(data.active_deliberation);
            else setActiveDeliberation(null);
            setActiveEdgeId(null);
            if (data.settings) setSettings(prev => ({ ...prev, ...data.settings }));
            setRuns(data.runs || []);
            setActiveRun(data.active_run || null);
            setRaisedHands(data.raised_hands || []);
            setLiveThinking(null);
            const runId: string | null = data.active_run_id || (data.active_run ? data.active_run.run_id : null);
            setActiveRunId(runId);
            setIsExecuting(!!runId || !!data.pending_step_approval);
            refreshProjects();
          } else if (data.type === 'JIRA_BATCH_COMPLETED' || data.type === 'TEST_SUITE_COMPLETED') {
            setIsExecuting(false);
            setActiveRunId(null);
            setLiveThinking(null);
            setLastRunStatus({ type: data.type, status: data.status || 'COMPLETED', at: new Date().toISOString() });
          } else if (data.type === 'RUN_UPDATED') {
            if (data.run) {
              const run: PipelineRun = data.run;
              applyRunUpdate(run);
              if (!run.is_terminal) {
                setActiveRunId(run.run_id);
                if (run.status !== 'QUEUED') setIsExecuting(true);
              }
            }
          } else if (data.type === 'VERIFICATION_STARTED') {
            // QA kartında ve canlı akışta sunucu doğrulamasının koştuğu görünsün
            const cmds = data.commands ? Object.entries(data.commands as Record<string, string>).map(([k, v]) => `${k}: ${v}`).join(' · ') : '';
            setLiveThinking({
              run_id: data.run_id, agent_id: 'QA', order: data.order,
              text: translate('misc.live.verifyRunning', { order: data.order, scope: data.scope === 'incremental' ? translate('misc.live.incremental', undefined, 'artımlı') : translate('misc.live.full', undefined, 'tam') }, 'Sunucu doğrulaması koşuyor (adım #{order}, {scope})')
                + (cmds ? ` — ${cmds}` : translate('misc.live.noCommands', undefined, ' — çalıştırılacak komut yok (sözdizimi denetimi)')),
              what_doing: translate('misc.live.runningTests', undefined, 'Test / build komutlarını koşturuyor'), what_next: translate('misc.live.nextCommit', undefined, 'Geçerse SCM commit, kalırsa düzeltme turu'),
              timestamp: new Date().toISOString(),
            });
          } else if (data.type === 'VERIFICATION_DONE') {
            const v = data.verification;
            if (v) {
              setLiveThinking({
                run_id: data.run_id, agent_id: 'QA', order: data.order,
                text: v.summary || translate('misc.live.verifyStatus', { status: v.status }, 'Doğrulama {status}'),
                what_doing: v.status === 'FAILED' ? translate('misc.live.reportToDev', undefined, 'Hata raporu geliştiriciye iletiliyor') : translate('misc.live.savedResult', undefined, 'Sonucu kaydetti'),
                timestamp: new Date().toISOString(),
              });
            }
          } else if (data.type === 'SETTINGS_UPDATED') {
            if (data.settings) setSettings(prev => ({ ...prev, ...data.settings }));
            if (data.settings && 'tech_decisions' in data.settings) setTechDecisions(data.settings.tech_decisions || null);
          } else if (data.type === 'DECISIONS_REQUESTED') {
            if (Array.isArray(data.questions)) setTechQuestions(data.questions);
            setDecisionsPending(true);
          } else if (data.type === 'DECISIONS_SAVED') {
            if (Array.isArray(data.tech_questions)) setTechQuestions(data.tech_questions);
            setTechDecisions(data.tech_decisions || null);
            setDecisionsPending(false);
          } else if (data.type === 'CROSS_PROJECT_MESSAGE') {
            // Aktif projeye gelen mesaj zaten AGENT_INTERACTION olarak akar; hedef başka projeyse yalnızca bildir
            if (data.event && data.target_project_id && data.event.from_project !== data.target_project_id) {
              setEvents(prev => (prev.some(e => e.id === data.event.id) ? prev : [data.event, ...prev.slice(0, 499)]));
            }
          } else if (data.type === 'TEAMS_UPDATED') {
            setTeamsVersion(v => v + 1);
          } else if (data.type === 'MCP_CLIENT_SEEN') {
            if (data.clients) setConnectedClients(data.clients);
          } else if (data.type === 'AGENT_THINKING_DELTA') {
            setLiveThinking({
              run_id: data.run_id, agent_id: data.agent_id, order: data.order, text: data.text,
              what_doing: data.what_doing, what_next: data.what_next, timestamp: data.timestamp
            });
            setAgents(prev => prev.map(a => a.id === data.agent_id
              ? { ...a, status: 'WORKING', current_thinking: data.text, current_what_doing: data.what_doing || a.current_what_doing }
              : a));
          } else if (data.type === 'CLAUDE_LOG') {
            const entry = data.entry as ClaudeLogEntry;
            setClaudeLog(prev => {
              const idx = prev.findIndex(x => x.id === entry.id);
              const next = idx >= 0 ? prev.map(x => (x.id === entry.id ? entry : x)) : [entry, ...prev];
              return next.slice(0, 300);
            });
          } else if (data.type === 'CLAUDE_SESSION_STATUS') {
            setClaudeSession(prev => ({ state: data.state as ClaudeBridgeState, events: data.event === 'STARTED' ? [] : prev.events }));
          } else if (data.type === 'CLAUDE_SESSION_EVENT') {
            setClaudeSession(prev => ({ ...prev, events: [...prev.events, data.event as ClaudeSessionEvent].slice(-400) }));
          } else if (data.type === 'CLAUDE_TRANSCRIPT_EVENT') {
            setTranscriptEvents(prev => [...prev, { ...(data.event as TranscriptEvent), file: data.file }].slice(-400));
          } else if (data.type === 'AGENT_METRIC_UPDATED') {
            if (data.agent && data.agent.id) {
              setAgents(prev => {
                const idx = prev.findIndex(a => a && a.id === data.agent.id);
                if (idx >= 0) {
                  const next = [...prev];
                  next[idx] = { ...next[idx], ...data.agent };
                  return next;
                }
                return [...prev, data.agent];
              });
            }
          } else if (data.type === 'MODEL_CONFIG_UPDATED') {
            if (data.model_config) setModelConfig(data.model_config);
          } else if (data.type === 'DELIBERATION_MESSAGE') {
            setActiveDeliberation(prev => {
              if (!prev) {
                return {
                  session_id: data.session_id || 'DELIB-NEW',
                  title: translate('misc.live.deliberationTitle', undefined, 'Ajan Müzakere Masası'),
                  spec_summary: '',
                  status: 'ACTIVE',
                  messages: [data.message],
                  created_at: new Date().toISOString(),
                  updated_at: new Date().toISOString()
                };
              }
              return {
                ...prev,
                messages: [...prev.messages, data.message]
              };
            });
          } else if (data.type === 'DELIBERATION_COMPLETED' || data.type === 'DELIBERATION_PLANS_PROPOSED' || data.type === 'DELIBERATION_OPENED' || data.type === 'DELIBERATION_AWAITING_APPROVAL' || data.type === 'DELIBERATION_REVISION_REQUESTED') {
            if (data.session) setActiveDeliberation(data.session);
          } else if (data.type === 'STEP_WAITING_APPROVAL') {
            setPendingApproval(data.step_info);
            if (data.step_info?.kind === 'decisions') { setDecisionsPending(true); if (Array.isArray(data.step_info.questions)) setTechQuestions(data.step_info.questions); }
            setIsExecuting(true);
            if (data.step_info?.run_id) setActiveRunId(data.step_info.run_id);
          } else if (data.type === 'STEP_APPROVED') {
            setPendingApproval(null);
            setDecisionsPending(false);
          } else if (data.type === 'STEP_MODE_CHANGED') {
            setStepByStepMode(!!data.step_by_step_mode);
            if (data.approval_mode) setSettings(prev => ({ ...prev, approval_mode: data.approval_mode }));
          } else if (data.type === 'HAND_RAISED') {
            if (data.raised_hands) setRaisedHands(data.raised_hands);
          } else if (data.type === 'AGENT_INTERACTION') {
            const newEvent: TelemetryEvent = data;
            setEvents(prev => [newEvent, ...prev.slice(0, 499)]);

            setStats(prev => ({
              ...prev,
              total_events: prev.total_events + 1,
              total_tokens: prev.total_tokens + (newEvent.tokens_used || 0)
            }));

            // Update agents visual state
            setAgents(prev => prev.map(a => {
              if (a.id === newEvent.from_agent) {
                return {
                  ...a,
                  // Yalnızca açıkça başarısız olay hata sayılır ('IN_PROGRESS' = soru açıldı gibi olaylar hata değildir)
                  status: ['FAILED', 'ERROR'].includes(String(newEvent.status).toUpperCase()) ? 'ERROR' : 'WORKING',
                  last_action: newEvent.action,
                  total_tokens: a.total_tokens + (newEvent.tokens_used || 0),
                  active_file: newEvent.current_file || a.active_file,
                  last_seen: newEvent.timestamp,
                  current_dialogue: newEvent.friendly_dialogue || a.current_dialogue,
                  current_thinking: newEvent.thinking || a.current_thinking,
                  current_what_doing: newEvent.what_doing || a.current_what_doing
                };
              }
              if (a.id === newEvent.to_agent && newEvent.to_agent !== newEvent.from_agent) {
                return {
                  ...a,
                  status: newEvent.action === 'REPORT_BUG' ? 'BUG_FIX' : 'PENDING_ACTION',
                  last_seen: newEvent.timestamp,
                  current_what_doing: newEvent.what_next || a.current_what_doing
                };
              }
              return a;
            }));

            // Trigger active edge animation
            const edgeKey = `edge-${newEvent.from_agent}-${newEvent.to_agent}`;
            setActiveEdgeId(edgeKey);
            setEdgeStatus(newEvent.status === 'FAILED' ? 'FAILED' : 'SUCCESS');

            if (activeTimerRef.current) clearTimeout(activeTimerRef.current);
            activeTimerRef.current = setTimeout(() => {
              setActiveEdgeId(null);
            }, 3000);

          } else if (data.type === 'TASK_UPDATED') {
            if (data.tasks) {
              setTasks(data.tasks);
            } else if (data.task && data.task.id) {
              const updatedTask: KanbanTask = data.task;
              setTasks(prev => {
                const existingIdx = prev.findIndex(t => t && t.id === updatedTask.id);
                if (existingIdx >= 0) {
                  const next = [...prev];
                  next[existingIdx] = updatedTask;
                  return next;
                }
                return [...prev, updatedTask];
              });
            }
          } else if (typeof data.type === 'string' && (data.type.startsWith('QUESTION_') || data.type.startsWith('SPRINT_'))) {
            // Soru açıldı/varsayılana döndü ya da sprint durumu değişti: kuyruğu ve sıra bilgisini yenile
            refreshQuestions();
            refreshMcpActivity();
            if (String(data.type).startsWith('SPRINT_')) setSprintVersion(v => v + 1);
          } else if (data.type === 'JIRA_UPDATED' || data.type === 'JIRA_ISSUES_UPDATED') {
            if (data.jira_issues) {
              setJiraIssues(data.jira_issues);
            } else if (data.issues) {
              setJiraIssues(data.issues);
            } else if (data.all_issues) {
              setJiraIssues(data.all_issues);
            } else if (data.tasks) {
              setJiraIssues(data.tasks);
            } else if (data.issue && data.issue.id) {
              const updatedIssue: JiraIssue = data.issue;
              setJiraIssues(prev => {
                const existingIdx = prev.findIndex(i => i && i.id === updatedIssue.id);
                if (existingIdx >= 0) {
                  const next = [...prev];
                  next[existingIdx] = updatedIssue;
                  return next;
                }
                return [...prev, updatedIssue];
              });
            }
          } else if (data.type === 'SPEC_ADDED') {
            if (data.all_specs) setUploadedSpecs(data.all_specs);
            else if (data.spec) setUploadedSpecs(prev => [data.spec, ...prev.filter(s => s && s.id !== data.spec.id)]);
          } else if (data.type === 'SPEC_UPDATED') {
            if (data.all_specs) setUploadedSpecs(data.all_specs);
            else if (data.spec) setUploadedSpecs(prev => prev.map(s => (s && s.id === data.spec.id) ? data.spec : s));
          } else if (data.type === 'SPEC_DELETED') {
            if (data.all_specs) setUploadedSpecs(data.all_specs);
            else if (data.spec_id) setUploadedSpecs(prev => prev.filter(s => s && s.id !== data.spec_id));
          } else if (data.type === 'PLAYWRIGHT_REPORT_ADDED') {
            const report: PlaywrightReport = data.report;
            if (report) setPlaywrightReports(prev => [report, ...prev]);
          } else if (data.type === 'TEST_PROFILES_UPDATED') {
            if (data.profiles) setTestProfiles(data.profiles);
          } else if (data.type === 'AGENT_ADDED' || data.type === 'AGENT_UPDATED' || data.type === 'AGENT_DELETED') {
            if (data.agents) setAgents(data.agents);
            else if (data.agent && data.agent.id) {
              setAgents(prev => {
                const idx = prev.findIndex(a => a && a.id === data.agent.id);
                if (idx >= 0) {
                  const next = [...prev];
                  next[idx] = data.agent;
                  return next;
                }
                return [...prev, data.agent];
              });
            }
          } else if (data.type === 'STATE_RESET') {
            setEvents([]);
            setTasks([]);
            if (data.jira_issues) setJiraIssues(data.jira_issues);
            // Sıfırlamada baloncuk/düşünce alanları temizlenir (sunucu da temizler; burada güvenlik ağı)
            const cleared = (data.agents && data.agents.length > 0 ? data.agents : DEFAULT_AGENTS).map((a: Agent) => ({
              ...a, current_dialogue: undefined, current_thinking: undefined, current_what_doing: undefined, active_file: '',
            }));
            setAgents(cleared);
            setPendingApproval(null);
            setIsExecuting(false);
            setActiveRunId(null);
            setStats({
              total_events: 0,
              total_tokens: 0,
              active_tasks_count: 0,
              start_time: new Date().toISOString()
            });
            setActiveEdgeId(null);
          }
        } catch (err) {
          console.error('WS parse error:', err);
        }
      };

      const scheduleReconnect = () => {
        if (isUnmountingRef.current) return;
        if (reconnectTimeoutRef.current) clearTimeout(reconnectTimeoutRef.current);
        // Üstel geri çekilme: 1s, 2s, 4s ... en fazla 30s (+ 0-500ms jitter)
        const attempt = reconnectAttemptRef.current++;
        const delay = Math.min(30000, 1000 * 2 ** attempt) + Math.random() * 500;
        reconnectTimeoutRef.current = setTimeout(connect, delay);
      };

      ws.onclose = () => {
        setIsConnected(false);
        if (wsRef.current === ws) wsRef.current = null;
        scheduleReconnect();
      };

      ws.onerror = () => {
        ws.close();
      };
    } catch (err) {
      setIsConnected(false);
      if (!isUnmountingRef.current) {
        const attempt = reconnectAttemptRef.current++;
        reconnectTimeoutRef.current = setTimeout(connect, Math.min(30000, 1000 * 2 ** attempt));
      }
    }
  }, [refreshProjects]);

  useEffect(() => {
    isUnmountingRef.current = false;
    connect();
    return () => {
      // Önce bayrak: onclose tetiklense bile yeniden bağlanma planlanmaz
      isUnmountingRef.current = true;
      if (reconnectTimeoutRef.current) clearTimeout(reconnectTimeoutRef.current);
      if (activeTimerRef.current) clearTimeout(activeTimerRef.current);
      if (wsRef.current) {
        wsRef.current.close();
        wsRef.current = null;
      }
    };
  }, [connect]);

  /** Proje geçişi yalnızca sunucuya iletilir; yeni durum tek kaynaktan (PROJECT_SWITCHED WS mesajı) uygulanır. */
  const switchProject = async (projectIdOrPath: string) => {
    try {
      const res = await fetch(api('/api/projects/switch'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ project_id: projectIdOrPath })
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        console.error('Error switching project:', err);
      }
    } catch (e) {
      console.error('Error switching project:', e);
    }
  };

  /** layoutMode: 'apps' (önerilen: apps/ devops/ docs/) | 'flat' (düz); verilmezse sunucunun varsayılanı. */
  const addProject = async (path: string, name?: string, layoutMode?: 'apps' | 'flat', projectLanguage?: 'tr' | 'en') => {
    // Hata yutulmaz: çağıran gerçek sonucu görür (yanlış "bağlandı" mesajı çıkmaz)
    const res = await fetch(api('/api/projects/add'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path, name, layout_mode: layoutMode, project_language: projectLanguage })
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      throw new Error(data?.error || translate('misc.err.addProject', { status: res.status }, `Proje eklenemedi (HTTP ${res.status})`));
    }
    await switchProject(data.project.id);
    return { ...data.project, layout_note: data.layout_note || '' };
  };

  const deleteProject = async (projectId: string) => {
    try {
      const res = await fetch(api(`/api/projects/${projectId}`), {
        method: 'DELETE'
      });
      if (res.ok) {
        await refreshProjects();
      }
    } catch (e) {
      console.error('Error deleting project:', e);
    }
  };

  /** Projeyi kaldırır ve verilerini siler (scope: data = .fs-workspace + belgeler, folder = tüm klasör). Hata iletisini döner, başarıda null. */
  const purgeProject = async (projectId: string, scope: 'data' | 'folder', confirmName: string): Promise<string | null> => {
    try {
      const res = await fetch(api(`/api/projects/${projectId}/purge`), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ scope, confirm_name: confirmName })
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        return data.error || `Silinemedi (${res.status})`;
      }
      await refreshProjects();
      return null;
    } catch (e) {
      return String(e);
    }
  };

  // Jira Batch Runner (1'den 10'a kadar maddeleri koştur)
  const executeJiraBatch = async (
    selectedIssues: (number | string)[],
    prompt?: string,
    projectDir?: string,
    stepByStep?: boolean
  ) => {
    try {
      const res = await fetch(api('/api/jira/execute-batch'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          selected_issues: selectedIssues,
          prompt: prompt || 'Kurumsal Çok Katmanlı Servis ve Modern Arayüz',
          project_dir: projectDir,
          step_by_step: stepByStep !== undefined ? stepByStep : stepByStepMode
        })
      });
      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.error || translate('misc.serverError', { status: res.status }, `Sunucu hatası (${res.status})`));
      }
      // Koşu 'JIRA_BATCH_COMPLETED' WS mesajı gelene kadar sürer
      setIsExecuting(true);
      return data;
    } catch (e) {
      console.error('Error executing Jira batch:', e);
      throw e;
    }
  };

  // Adım Onayı Gönder (PROCEED, AUTO_ALL veya REJECTED) — bekleyen adımın token'ı ile
  // REVISE: adımı `comment` geri bildirimiyle aynı sıra numarasıyla yeniden ürettirir (gerekçe zorunlu; sunucu 400 INVALID dönebilir)
  const approveStep = async (decision: 'PROCEED' | 'AUTO_ALL' | 'REJECTED' | 'REVISE' = 'PROCEED', comment?: string) => {
    try {
      const res = await fetch(api('/api/pipeline/approve-step'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ decision, token: pendingApproval?.approval_token, comment })
      });
      const data = await res.json();
      if (!res.ok) {
        console.warn('Approve step rejected by server:', data);
      }
      return data;
    } catch (e) {
      console.error('Error approving step:', e);
      throw e;
    }
  };

  // Adım Adım Modu Aç/Kapat
  const toggleStepMode = async (enabled: boolean) => {
    try {
      setStepByStepMode(enabled);
      const res = await fetch(api('/api/pipeline/set-step-mode'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ step_by_step: enabled })
      });
      return await res.json();
    } catch (e) {
      console.error('Error setting step mode:', e);
    }
  };

  // Müşteri Görüşme ve Dosya Yükleme
  const uploadSpec = async (formData: FormData) => {
    try {
      if (currentProject && !formData.has('project_id')) {
        formData.append('project_id', currentProject.id);
      }
      const res = await fetch(api('/api/specs/upload'), {
        method: 'POST',
        body: formData
      });
      const data = await res.json();
      if (data.spec) {
        setUploadedSpecs(prev => [data.spec, ...prev.filter(s => s.id !== data.spec.id)]);
      }
      if (Array.isArray(data.tasks) && data.tasks.length > 0) {
        // Boş liste (sprint kipi ya da otomatik üretim kapalı) panoyu silmez; sunucu JIRA_UPDATED/INTAKE olaylarıyla günceller
        setJiraIssues(data.tasks);
      }
      return data;
    } catch (e) {
      console.error('Error uploading spec:', e);
      throw e;
    }
  };

  // Şartnameyi Analiz Et ve Jira Görevlerini Otomatik Çıkar
  const analyzeSpecAndGenerateTasks = async (specId?: string) => {
    try {
      const res = await fetch(api('/api/specs/analyze-and-generate-tasks'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ spec_id: specId })
      });
      const data = await res.json();
      if (Array.isArray(data.tasks) && data.tasks.length > 0) {
        // Boş liste (sprint kipi ya da otomatik üretim kapalı) panoyu silmez; sunucu JIRA_UPDATED/INTAKE olaylarıyla günceller
        setJiraIssues(data.tasks);
      }
      return data;
    } catch (e) {
      console.error('Error analyzing spec and generating tasks:', e);
      throw e;
    }
  };

  // Şartnameyi Kasadan Sil
  const deleteSpec = async (specId: string) => {
    try {
      const res = await fetch(api(`/api/specs/${specId}`), {
        method: 'DELETE'
      });
      if (res.ok) {
        setUploadedSpecs(prev => prev.filter(s => s && s.id !== specId));
      }
      return await res.json();
    } catch (e) {
      console.error('Error deleting spec:', e);
      throw e;
    }
  };

  // Şartnameden Tek Bir Dosyayı Çıkar/Sil
  const deleteSpecFile = async (specId: string, filename: string) => {
    try {
      const res = await fetch(api(`/api/specs/${specId}/files/${encodeURIComponent(filename)}`), {
        method: 'DELETE'
      });
      if (res.ok) {
        setUploadedSpecs(prev => prev.map(s => {
          if (s && s.id === specId) {
            return {
              ...s,
              files: (s.files || []).filter(f => f.filename !== filename)
            };
          }
          return s;
        }));
      }
      return await res.json();
    } catch (e) {
      console.error('Error deleting spec file:', e);
      throw e;
    }
  };

  // Şartname Başlık veya Notlarını Güncelle
  const updateSpec = async (specId: string, updates: { title?: string; client_name?: string; meeting_notes?: string }) => {
    try {
      const res = await fetch(api(`/api/specs/${specId}`), {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(updates)
      });
      const data = await res.json();
      if (data.spec) {
        setUploadedSpecs(prev => prev.map(s => (s && s.id === specId) ? data.spec : s));
      }
      return data;
    } catch (e) {
      console.error('Error updating spec:', e);
      throw e;
    }
  };

  // Playwright Canlı E2E Test Koşusu
  const runPlaywrightTest = async (targetUrl?: string, scenario?: string, credentials?: any) => {
    try {
      const res = await fetch(api('/api/tester/run-playwright'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          target_url: targetUrl || DEFAULT_TARGET_URL,
          scenario: scenario || 'Kullanıcı Giriş & Arayüz Doğrulama',
          credentials
        })
      });
      return await res.json();
    } catch (e) {
      console.error('Error running Playwright test:', e);
      throw e;
    }
  };

  // Yalnızca Test Süitini Koştur (QA Lead + Playwright E2E)
  const runTestsOnlySuite = async (targetUrl?: string, credentials?: any, scenario?: string, projectDir?: string) => {
    try {
      const res = await fetch(api('/api/tester/run-qa-suite'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          target_url: targetUrl || DEFAULT_TARGET_URL,
          credentials,
          scenario: scenario || 'Bağımsız QA & Playwright Tarayıcı Doğrulama Süiti',
          project_dir: projectDir
        })
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || translate('misc.serverError', { status: res.status }, `Sunucu hatası (${res.status})`));
      // 'TEST_SUITE_COMPLETED' WS mesajı gelene kadar sürer
      setIsExecuting(true);
      return data;
    } catch (e) {
      console.error('Error running QA suite:', e);
      throw e;
    }
  };

  // Test Profili / Şablonu Kaydet veya Güncelle
  const saveTestProfile = async (profile: Partial<TestUserProfile>) => {
    try {
      const res = await fetch(api('/api/tester/profiles'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(profile)
      });
      return await res.json();
    } catch (e) {
      console.error('Error saving test profile:', e);
      throw e;
    }
  };

  // Test Profilini Sil
  const deleteTestProfile = async (profileId: string) => {
    try {
      const res = await fetch(api(`/api/tester/profiles/${profileId}`), {
        method: 'DELETE'
      });
      return await res.json();
    } catch (e) {
      console.error('Error deleting test profile:', e);
      throw e;
    }
  };

  // Özel Kıdemli Geliştirici Ajanı Ekle
  const addCustomAgent = async (agentData: { id?: string; name: string; role: string; active_file?: string; description?: string }) => {
    try {
      const res = await fetch(api('/api/agents/add'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(agentData)
      });
      return await res.json();
    } catch (e) {
      console.error('Error adding custom agent:', e);
      throw e;
    }
  };

  // Mevcut Ajanı Güncelle / Düzenle (örn: Tester, QA, Backend Dev)
  const updateAgent = async (agentId: string, updates: Partial<Agent>) => {
    try {
      const res = await fetch(api(`/api/agents/${agentId}`), {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(updates)
      });
      return await res.json();
    } catch (e) {
      console.error('Error updating agent:', e);
      throw e;
    }
  };

  // Ajanı Kaldır veya Varsayılana Sıfırla
  const deleteAgent = async (agentId: string) => {
    try {
      const res = await fetch(api(`/api/agents/${agentId}`), {
        method: 'DELETE'
      });
      return await res.json();
    } catch (e) {
      console.error('Error deleting agent:', e);
      throw e;
    }
  };

  const updateJiraIssue = async (issueId: string, updates: Partial<JiraIssue>) => {
    try {
      const res = await fetch(api('/api/jira/issues'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id: issueId, ...updates })
      });
      return await res.json();
    } catch (e) {
      console.error('Error updating Jira issue:', e);
      throw e;
    }
  };

  const resetState = async () => {
    try {
      await fetch(api('/api/reset'), { method: 'POST' });
    } catch (e) {
      console.error('Reset error:', e);
    }
  };

  // -------------------------------------------------------------------------
  // Proje Bazlı Ajan Promptu (.md) & Git-Tree Versiyonlama
  // -------------------------------------------------------------------------
  const fetchAgentPrompt = async (agentId: string, projectId?: string): Promise<AgentPromptInfo> => {
    try {
      const targetProjId = projectId || (currentProject ? currentProject.id : undefined);
      const query = targetProjId ? `?project_id=${encodeURIComponent(targetProjId)}` : '';
      const res = await fetch(api(`/api/agents/${agentId}/prompt${query}`));
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || translate('misc.err.e1', undefined, 'Ajan promptu alınamadı'));
      return data.prompt_info;
    } catch (e) {
      console.error('Error fetching agent prompt:', e);
      throw e;
    }
  };

  const saveAgentPrompt = async (
    agentId: string,
    content: string,
    commitMessage: string,
    author: string = 'User',
    projectId?: string
  ): Promise<AgentPromptInfo> => {
    try {
      const targetProjId = projectId || (currentProject ? currentProject.id : undefined);
      const res = await fetch(api(`/api/agents/${agentId}/prompt`), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          content,
          commit_message: commitMessage,
          author,
          project_id: targetProjId
        })
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || translate('misc.err.e2', undefined, 'Ajan versiyonu kaydedilemedi'));
      return data.prompt_info;
    } catch (e) {
      console.error('Error saving agent prompt:', e);
      throw e;
    }
  };

  const restoreAgentVersion = async (
    agentId: string,
    versionId: string,
    author: string = 'User',
    projectId?: string
  ): Promise<AgentPromptInfo> => {
    try {
      const targetProjId = projectId || (currentProject ? currentProject.id : undefined);
      const res = await fetch(api(`/api/agents/${agentId}/restore`), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          version_id: versionId,
          author,
          project_id: targetProjId
        })
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || translate('misc.err.e3', undefined, 'Versiyon geri yüklenemedi'));
      return data.prompt_info;
    } catch (e) {
      console.error('Error restoring agent version:', e);
      throw e;
    }
  };

  const inheritAgentStandard = async (
    agentId: string,
    author: string = 'User',
    projectId?: string
  ): Promise<AgentPromptInfo> => {
    try {
      const targetProjId = projectId || (currentProject ? currentProject.id : undefined);
      const res = await fetch(api(`/api/agents/${agentId}/inherit`), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          author,
          project_id: targetProjId
        })
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || translate('misc.err.e4', undefined, 'Standart şablondan kalıtılamadı'));
      return data.prompt_info;
    } catch (e) {
      console.error('Error inheriting agent standard:', e);
      throw e;
    }
  };

  const promoteAgentToGlobal = async (agentId: string, projectId?: string) => {
    try {
      const targetProjId = projectId || (currentProject ? currentProject.id : undefined);
      const res = await fetch(api(`/api/agents/${agentId}/promote-to-global`), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ project_id: targetProjId })
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || translate('misc.err.e5', undefined, 'Global şablona terfi ettirilemedi'));
      return data.promotion;
    } catch (e) {
      console.error('Error promoting agent to global:', e);
      throw e;
    }
  };

  // LLM Model & Sağlayıcı Güncelle (Gemini vs Claude)
  const updateModelConfig = async (newConfig: Partial<LLMModelConfig>, projectId?: string) => {
    try {
      const targetProjId = projectId || (currentProject ? currentProject.id : undefined);
      const res = await fetch(api('/api/settings/model'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          project_id: targetProjId,
          ...newConfig
        })
      });
      const data = await res.json();
      if (data.model_config) {
        setModelConfig(data.model_config);
      }
      return data;
    } catch (e) {
      console.error('Error updating model config:', e);
      throw e;
    }
  };

  // Ajan Müzakeresi Başlat
  const runDeliberation = async (title?: string, prompt?: string) => {
    try {
      const res = await fetch(api('/api/deliberation/run'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title, prompt })
      });
      const data = await res.json();
      if (data.session) setActiveDeliberation(data.session);
      return data;
    } catch (e) {
      console.error('Error running deliberation:', e);
      throw e;
    }
  };

  // Göreve Audit Trail Notu Ekle
  // Faz B: koşu başlat (mcp_client → kuyruğa alınır ve Claude Desktop çeker; template → sunucu koşar)
  const startRun = async (steps: (number | string)[], engine?: ExecutionEngine, prompt?: string, projectDir?: string, stepByStep?: boolean, forceNew?: boolean) => {
    const res = await fetch(api('/api/runs'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        steps,
        engine: engine || settings.execution_engine,
        prompt,
        project_dir: projectDir,
        step_by_step: stepByStep !== undefined ? stepByStep : stepByStepMode,
        force_new: forceNew ? true : undefined
      })
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || data.message || translate('misc.serverError', { status: res.status }, `Sunucu hatası (${res.status})`));
    if (data.run) applyRunUpdate(data.run);
    if (data.run && data.run.engine === 'template') setIsExecuting(true);
    return data;
  };

  const pauseRun = async (runId: string) => {
    const res = await fetch(api(`/api/runs/${runId}/pause`), { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ reason: 'user' }) });
    const body = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(body.error || translate('misc.err.e6', undefined, 'Duraklatılamadı'));
    return body;
  };

  // Çok sık olay (art arda MCP çağrıları) tek istekte toplanır
  const mcpRefreshTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const refreshMcpActivity = () => {
    if (mcpRefreshTimer.current) return;
    mcpRefreshTimer.current = setTimeout(async () => {
      mcpRefreshTimer.current = null;
      try {
        const res = await fetch(api('/api/mcp/activity'));
        if (res.ok) setMcpActivity(await res.json());
      } catch {
        /* sunucu geçici olarak yanıt vermiyor olabilir; bir sonraki olayda/yoklamada yeniden denenir */
      }
    }, 300);
  };

  // ---- G2: Claude köprüsü veri/eylemleri ----
  const jsonOrThrow = async (res: Response, fallback: string) => {
    const body = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(body.error || body.install_hint || body.status || fallback);
    return body;
  };
  const fetchClaudeLog = async (params: ClaudeLogQuery = {}): Promise<ClaudeLogPage> => {
    const qs = new URLSearchParams();
    Object.entries(params).forEach(([k, v]) => { if (v !== undefined && v !== null && v !== '') qs.set(k, String(v)); });
    const body = await jsonOrThrow(await fetch(api(`/api/claude/log?${qs.toString()}`)), translate('misc.err.e7', undefined, 'Günlük okunamadı'));
    const unfiltered = !params.run_id && !params.tool && !params.direction && !params.q && !params.offset;
    if (unfiltered && Array.isArray(body.entries)) setClaudeLog(body.entries.slice(0, 300));
    return body as ClaudeLogPage;
  };
  const fetchClaudeLogEntry = async (id: string): Promise<ClaudeLogEntry> => jsonOrThrow(await fetch(api(`/api/claude/log/${id}`)), translate('misc.err.e8', undefined, 'Kayıt okunamadı'));
  const fetchClaudeStatus = async (): Promise<ClaudeStatus> => {
    const body = await jsonOrThrow(await fetch(api('/api/claude/status')), translate('misc.err.e9', undefined, 'Durum okunamadı'));
    setClaudeSession(prev => ({ ...prev, state: body.bridge as ClaudeBridgeState }));
    return body as ClaudeStatus;
  };
  const claudeStart = async (opts: { prompt?: string; resume?: string; max_turns?: number } = {}) =>
    jsonOrThrow(await fetch(api('/api/claude/start'), { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(opts) }), translate('misc.err.e10', undefined, 'Claude başlatılamadı'));
  const claudeStop = async () => jsonOrThrow(await fetch(api('/api/claude/stop'), { method: 'POST' }), translate('misc.err.e11', undefined, 'Durdurulamadı'));
  const fetchClaudeSessions = async (): Promise<ClaudeBridgeSessionFile[]> => (await jsonOrThrow(await fetch(api('/api/claude/sessions')), translate('misc.err.e12', undefined, 'Oturumlar okunamadı'))).sessions;
  const fetchClaudeSessionEvents = async (sessionId: string): Promise<ClaudeSessionEvent[]> =>
    (await jsonOrThrow(await fetch(api(`/api/claude/sessions/${encodeURIComponent(sessionId)}/events`)), translate('misc.err.e13', undefined, 'Oturum okunamadı'))).events;
  const fetchTranscripts = async () => jsonOrThrow(await fetch(api('/api/claude/transcripts')), translate('misc.err.e14', undefined, 'Transkriptler okunamadı'));
  const fetchTranscriptEvents = async (sessionId: string, limit = 300): Promise<TranscriptEventsPage> =>
    jsonOrThrow(await fetch(api(`/api/claude/transcripts/${encodeURIComponent(sessionId)}/events?limit=${limit}`)), translate('misc.err.e15', undefined, 'Transkript okunamadı'));
  const watchTranscript = async (sessionId: string, fromStart = false) =>
    jsonOrThrow(await fetch(api('/api/claude/transcripts/watch'), { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ session_id: sessionId, from_start: fromStart }) }), translate('misc.err.e16', undefined, 'İzleme başlatılamadı'));
  const updateClaudeSettings = async (patch: Partial<ClaudeBridgeConfig>) =>
    jsonOrThrow(await fetch(api('/api/settings/claude'), { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(patch) }), translate('misc.err.e17', undefined, 'Ayar kaydedilemedi'));
  const fetchRunnerSetup = async (): Promise<RunnerSetup> => jsonOrThrow(await fetch(api('/api/runner/setup')), translate('misc.err.e18', undefined, 'Kurulum durumu okunamadı'));
  const claudePanelData: ClaudePanelData = {
    claudeLog, claudeSession, transcriptEvents, fetchClaudeLog, fetchClaudeLogEntry, fetchClaudeStatus, claudeStart, claudeStop,
    fetchClaudeSessions, fetchClaudeSessionEvents, fetchTranscripts, fetchTranscriptEvents, watchTranscript, updateClaudeSettings, fetchRunnerSetup,
  };

  const refreshQuestions = async () => {
    try {
      const res = await fetch(api('/api/questions'));
      if (!res.ok) return;
      const body = await res.json();
      if (Array.isArray(body.questions)) setQueueQuestions(body.questions);
    } catch {
      /* sunucu geçici olarak yanıt vermiyor olabilir; bir sonraki yoklamada yeniden denenir */
    }
  };

  // Soruyu yönetici adına cevaplar (answer = seçenek anahtarı; customText verilirse serbest metin 'Diğer' cevabı).
  // Hata iletisini fırlatır; başarıda kuyruğu yeniler.
  const answerQuestion = async (questionId: string, answer: string, customText?: string) => {
    const res = await fetch(api(`/api/questions/${questionId}/answer`), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(customText && customText.trim() ? { custom_text: customText.trim() } : { answer })
    });
    const body = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(body.error || translate('misc.err.saveAnswer', { status: res.status }, `Cevap kaydedilemedi (${res.status})`));
    await refreshQuestions();
    return body;
  };

  // Yönetici müdahalesi: not bir sonraki adımın bağlamına girer; urgent=true koşuyu duraklatır
  const sendRunNote = async (runId: string, text: string, urgent = false) => {
    const res = await fetch(api(`/api/runs/${runId}/notes`), { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text, urgent }) });
    const body = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(body.error || translate('misc.err.e19', undefined, 'Not gönderilemedi'));
    return body;
  };

  const resumeRun = async (runId: string) => {
    const res = await fetch(api(`/api/runs/${runId}/resume`), { method: 'POST' });
    const body = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(body.error || translate('misc.err.e20', undefined, 'Devam ettirilemedi'));
    return body;
  };

  const cancelRun = async (runId: string, reason?: string) => {
    const res = await fetch(api(`/api/runs/${runId}/cancel`), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ reason: reason || 'user' })
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || translate('misc.serverError', { status: res.status }, `Sunucu hatası (${res.status})`));
    if (data.run) applyRunUpdate(data.run);
    return data;
  };

  const choosePlan = async (sessionId: string, planId: string) => {
    const res = await fetch(api('/api/deliberation/choose-plan'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: sessionId, plan_id: planId, chosen_by: 'USER' })
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || translate('misc.serverError', { status: res.status }, `Sunucu hatası (${res.status})`));
    if (data.session) setActiveDeliberation(data.session);
    return data;
  };

  const setApprovalMode = async (approval_mode: EngineSettings['approval_mode']) => {
    const res = await fetch(api('/api/pipeline/approval-mode'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ approval_mode })
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || translate('misc.serverError', { status: res.status }, `Sunucu hatası (${res.status})`));
    setSettings(prev => ({ ...prev, approval_mode: data.approval_mode }));
    setStepByStepMode(!!data.step_by_step_mode);
    return data;
  };

  const loadDecisions = async () => {
    const res = await fetch(api('/api/pipeline/decisions'));
    if (!res.ok) return null;
    const body = await res.json();
    setTechQuestions(body.questions || []);
    setTechDecisions(body.tech_decisions || null);
    setDecisionsPending(!!body.pending);
    return body;
  };

  const saveDecisions = async (answers: Record<string, string>, notes: string) => {
    const res = await fetch(api('/api/pipeline/decisions'), { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ answers, notes }) });
    const body = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(body.error || translate('misc.err.e21', undefined, 'Kararlar kaydedilemedi'));
    setTechDecisions(body.tech_decisions || null);
    if (Array.isArray(body.questions)) setTechQuestions(body.questions);
    setDecisionsPending(false);
    return body;
  };

  const resetDecisions = async () => {
    const res = await fetch(api('/api/pipeline/decisions'), { method: 'DELETE' });
    const body = await res.json().catch(() => ({}));
    setTechDecisions(null);
    if (Array.isArray(body.questions)) setTechQuestions(body.questions);
    return body;
  };

  const resolveHand = async (handId: string) => {
    const res = await fetch(api(`/api/pipeline/raised-hands/${handId}/resolve`), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ reviewed: true })
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || translate('misc.serverError', { status: res.status }, `Sunucu hatası (${res.status})`));
    return data;
  };

  const updateSettings = async (updates: Partial<EngineSettings>) => {
    const res = await fetch(api('/api/settings/engine'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(updates)
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || translate('misc.serverError', { status: res.status }, `Sunucu hatası (${res.status})`));
    if (data.settings) setSettings(prev => ({ ...prev, ...data.settings }));
    return data.settings as EngineSettings;
  };

  // G5 Jira+ istemci API'si (server/jira_plus.py uçları); hata gövdesindeki `error` metni fırlatılır
  const jreq = (path: string, method = 'GET', body?: unknown) => fetch(api(path), {
    method,
    headers: body !== undefined ? { 'Content-Type': 'application/json' } : undefined,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  const jid = (id: string) => `/api/jira/issues/${encodeURIComponent(id)}`;
  const jiraApi: JiraApi = {
    edit: async (id, patch) => (await jsonOrThrow(await jreq(jid(id), 'PATCH', patch), translate('misc.err.e22', undefined, 'Madde güncellenemedi'))).issue,
    remove: async (id, reason) => (await jsonOrThrow(await jreq(`${jid(id)}${reason ? `?reason=${encodeURIComponent(reason)}` : ''}`, 'DELETE'), translate('misc.err.e23', undefined, 'Madde silinemedi'))).issue,
    restore: async (id) => (await jsonOrThrow(await jreq(`${jid(id)}/restore`, 'POST', {}), translate('misc.err.e24', undefined, 'Madde geri alınamadı'))).issue,
    comment: async (id, text) => (await jsonOrThrow(await jreq(`${jid(id)}/comments`, 'POST', { text }), translate('misc.err.e25', undefined, 'Yorum eklenemedi'))).comment,
    deleteComment: async (id, cid) => { await jsonOrThrow(await jreq(`${jid(id)}/comments/${encodeURIComponent(cid)}`, 'DELETE'), translate('misc.err.e26', undefined, 'Yorum silinemedi')); },
    link: async (id, type: JiraLinkType, target) => { await jsonOrThrow(await jreq(`${jid(id)}/links`, 'POST', { type, target }), translate('misc.err.e27', undefined, 'Bağ eklenemedi')); },
    unlink: async (id, type: JiraLinkType, target) => { await jsonOrThrow(await jreq(`${jid(id)}/links/${type}/${encodeURIComponent(target)}`, 'DELETE'), translate('misc.err.e28', undefined, 'Bağ kaldırılamadı')); },
    attach: async (id, a) => (await jsonOrThrow(await jreq(`${jid(id)}/attachments`, 'POST', a), translate('misc.err.e29', undefined, 'Ek eklenemedi'))).attachment,
    detach: async (id, aid) => { await jsonOrThrow(await jreq(`${jid(id)}/attachments/${encodeURIComponent(aid)}`, 'DELETE'), translate('misc.err.e30', undefined, 'Ek kaldırılamadı')); },
    move: async (id, status: JiraIssueStatus, index) => (await jsonOrThrow(await jreq(`${jid(id)}/move`, 'POST', { status, index }), translate('misc.err.e31', undefined, 'Madde taşınamadı'))).issue,
    plan: async (id, body) => (await jsonOrThrow(await jreq(`${jid(id)}/plan`, 'POST', body), translate('misc.err.e32', undefined, 'Planlama kaydedilemedi'))).issue,
    bulk: async (ids, action, value) => jsonOrThrow(await jreq('/api/jira/bulk', 'POST', { ids, action, value }), translate('misc.err.e33', undefined, 'Toplu işlem başarısız')),
    query: async (q, includeDeleted) => (await jsonOrThrow(await jreq(`/api/jira/query?q=${encodeURIComponent(q)}${includeDeleted ? '&include_deleted=true' : ''}`), translate('misc.err.e34', undefined, 'Sorgu çalışmadı'))).issues,
    filters: async () => jsonOrThrow(await jreq('/api/jira/filters'), translate('misc.err.e35', undefined, 'Süzgeçler okunamadı')),
    saveFilter: async (name, q) => (await jsonOrThrow(await jreq('/api/jira/filters', 'POST', { name, q }), translate('misc.err.e36', undefined, 'Süzgeç kaydedilemedi'))).filters,
    deleteFilter: async (name) => (await jsonOrThrow(await jreq(`/api/jira/filters/${encodeURIComponent(name)}`, 'DELETE'), translate('misc.err.e37', undefined, 'Süzgeç silinemedi'))).filters,
    timeline: async (id) => jsonOrThrow(await jreq(`${jid(id)}/timeline`), translate('misc.err.e38', undefined, 'Geçmiş okunamadı')),
    evidence: async (id) => jsonOrThrow(await jreq(`${jid(id)}/evidence`), translate('misc.err.e39', undefined, 'Kanıt okunamadı')),
    sprintBoard: async () => jsonOrThrow(await jreq('/api/sprints/board'), translate('misc.err.e40', undefined, 'Sprint panosu okunamadı')),
    sprintGoal: async (n, goal) => { await jsonOrThrow(await jreq(`/api/sprints/${n}`, 'PATCH', { goal }), translate('misc.err.e41', undefined, 'Hedef kaydedilemedi')); },
    sprintCommit: async (n) => { await jsonOrThrow(await jreq(`/api/sprints/${n}/commit`, 'POST', {}), translate('misc.err.e42', undefined, 'Taahhüt verilemedi')); },
    sprintUnblock: async (n) => { await jsonOrThrow(await jreq(`/api/sprints/${n}/unblock`, 'POST', {}), translate('misc.err.e43', undefined, 'Engel kaldırılamadı')); },
    sprintCancel: async (n) => { await jsonOrThrow(await jreq(`/api/sprints/${n}/cancel`, 'POST', {}), translate('misc.err.e44', undefined, 'Sprint iptal edilemedi')); },
    planNext: async () => { await jsonOrThrow(await jreq('/api/sprints/plan-next', 'POST', {}), translate('misc.err.e45', undefined, 'Sonraki sprint planlanamadı')); },
  };

  const recordTaskAudit = async (issueId: string, agentId: string, action: string, notes?: string, filesAffected?: string[]) => {
    try {
      const res = await fetch(api(`/api/jira/issues/${issueId}/audit`), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          agent_id: agentId,
          action,
          notes,
          files_affected: filesAffected
        })
      });
      return await res.json();
    } catch (e) {
      console.error('Error recording task audit:', e);
      throw e;
    }
  };

  // Soru kuyruğu ve Claude iletişimi: açılışta, proje değişince ve düzenli aralıkla yenilenir (olaylar ayrıca anında yeniler)
  useEffect(() => {
    refreshQuestions();
    refreshMcpActivity();
    fetchClaudeLog().catch(() => { /* sunucu geçici olarak yanıt vermiyor olabilir */ });
    fetchClaudeStatus().catch(() => { /* aynı */ });
    const timer = setInterval(refreshQuestions, 20000);
    const mcpTimer = setInterval(refreshMcpActivity, 5000);
    return () => { clearInterval(timer); clearInterval(mcpTimer); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentProject?.id]);

  const markNotificationsRead = () => setNotifications(prev => prev.map(n => (n.read ? n : { ...n, read: true })));
  const clearNotifications = () => setNotifications([]);

  return {
    isConnected,
    serverVersions,
    notifications,
    markNotificationsRead,
    clearNotifications,
    queueQuestions,
    answerQuestion,
    refreshQuestions,
    mcpActivity,
    refreshMcpActivity,
    claudePanelData,
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
    modelConfig,
    activeEdgeId,
    edgeStatus,
    activeDeliberation,
    switchProject,
    addProject,
    deleteProject,
    purgeProject,
    refreshProjects,
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
    resetState,
    pendingApproval,
    stepByStepMode,
    isExecuting,
    activeRunId,
    lastRunStatus,
    runs,
    activeRun,
    settings,
    connectedClients,
    liveThinking,
    teamsVersion,
    raisedHands,
    choosePlan,
    setApprovalMode,
    resolveHand,
    techQuestions,
    techDecisions,
    decisionsPending,
    loadDecisions,
    saveDecisions,
    resetDecisions,
    startRun,
    cancelRun,
    pauseRun,
    sendRunNote,
    resumeRun,
    updateSettings,
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
    updateModelConfig,
    runDeliberation,
    recordTaskAudit
  };
}
