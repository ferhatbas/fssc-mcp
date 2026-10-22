export type AgentRole = 
  | 'PM' 
  | 'ARCHITECT' 
  | 'DEVELOPER' 
  | 'BACKEND_DEV' 
  | 'FRONTEND_DEV' 
  | 'DESIGNER'
  | 'QA' 
  | 'E2E_TESTER' 
  | 'DEVOPS' 
  | 'PO'
  | 'REPORTER'
  | 'DOCUMENTOR'
  | 'SCM'
  | string;

export type AgentStatus = 'IDLE' | 'WORKING' | 'BUG_FIX' | 'COMPLETED' | 'ERROR' | 'PENDING_ACTION';

/** Koşunun gerçek durumundan türetilen "şimdi sıra kimde" (GET /api/mcp/activity). */
export interface McpTurn {
  who: 'claude' | 'claude_wait' | 'manager' | 'server' | 'idle';
  label: string;
  detail?: string;
  run_id: string | null;
  run_status?: string;
  engine?: string;
  order?: number | null;
  agent_id?: string | null;
  title?: string;
  kind?: string | null;
  since?: string | null;
}

export interface McpCall {
  ts: string;
  tool: string;
  run_id?: string | null;
  client?: string;
  count: number;
  result?: string;
  order?: number | null;
  agent_id?: string | null;
  title?: string;
}

export interface McpActivity {
  turn: McpTurn;
  client: { name: string; version?: string; first_seen?: string; last_seen?: string; calls?: number; age_s?: number | null } | null;
  client_state: 'connected' | 'waiting' | 'away' | 'none';
  calls: McpCall[];
  server_time: string;
}

export interface Agent {
  id: string;
  name: string;
  role: AgentRole;
  status: AgentStatus;
  active_file?: string;
  description?: string;
  tokens_in: number;
  tokens_out: number;
  total_tokens: number;
  last_action: string;
  last_seen: string;
  current_dialogue?: string;
  current_thinking?: string;
  current_what_doing?: string;
  /** Yalnızca arayüzde: koşunun gerçek durumuna göre kartın rolü (claude = Claude şu an üretiyor, manager = sıra yöneticide, waiting = Claude'dan çağrı bekleniyor). */
  live_role?: 'claude' | 'manager' | 'waiting';
  /** G6 ajan tanımı (server/agent_registry.py): devralınan temel rol, görev yetenekleri (iş türleri), odak sözcükleri, profil, projede etkin mi. */
  role_base?: string;
  capabilities?: string[];
  focus?: string[];
  profile?: AgentProfile;
  active?: boolean;
  /** core = çekirdek rol, project = yalnızca bu proje, global = şirket geneli tanımdan gelir (`overrides` projeye özgü fark). */
  scope?: 'core' | 'project' | 'global';
  inherits?: string;
  overrides?: Record<string, unknown>;
  prompt_addendum?: string;
  meeting_roles?: string[];
  evaluates?: string[];
}

export interface AgentProfile {
  model?: string;
  effort?: string;
  language?: string;
  max_tokens?: number;
  budget?: number;
  tools_allow?: string[];
}

/** GET /api/agents/{id}/health */
export interface AgentHealth {
  agent_id: string;
  scope?: string | null;
  delivered: number;
  first_pass: number;
  first_pass_rate: number | null;
  fix_rounds: number;
  failed_steps: number;
  total_tokens: number;
  budget?: number | null;
  prompt_versions: number;
  last_prompt_change?: string | null;
}

/** GET /api/agent-templates */
export interface AgentTemplateInfo {
  key: string;
  name: string;
  description: string;
  agents: { id: string; name?: string; role_base?: string; capabilities?: string[]; focus?: string[] }[];
}

export type KanbanState =
  | 'BACKLOG' 
  | 'ARCHITECTURE' 
  | 'DEVELOPMENT' 
  | 'QA_TESTING' 
  | 'DEVOPS_DEPLOY' 
  | 'RELEASED';

export interface KanbanTask {
  id: string;
  title: string;
  state: KanbanState;
  assignee: AgentRole;
  priority: 'P0' | 'P1' | 'P2';
  details?: string;
  updated_at: string;
}

export type JiraIssueStatus = 'BACKLOG' | 'SELECTED_FOR_DEV' | 'IN_PROGRESS' | 'IN_REVIEW' | 'DONE';
export type JiraIssueType = 'EPIC' | 'STORY' | 'TASK' | 'BUG' | 'FEATURE' | 'IMPROVEMENT' | 'REFACTOR' | 'TEST_CASE' | 'TEST_RUN' | 'SPIKE';

export interface TaskAuditEntry {
  id: string;
  timestamp: string;
  agent_id: string;
  action: string;
  status?: string;
  notes?: string;
  files_affected?: string[];
}

export interface DeliberationMessage {
  agent_id: string;
  role: string;
  message: string;
  sentiment: 'PROPOSAL' | 'CRITIQUE' | 'AGREE' | 'CONSENSUS' | string;
  timestamp: string;
}

export interface ArchitecturePlan {
  id: string;
  title: string;
  summary: string;
  stack: string[];
  pros: string[];
  cons: string[];
  risk: 'LOW' | 'MEDIUM' | 'HIGH' | string;
  recommended?: boolean;
}

export interface DeliberationSession {
  session_id: string;
  title: string;
  spec_summary: string;
  status: 'ACTIVE' | 'AWAITING_APPROVAL' | 'AWAITING_PLAN_CHOICE' | 'CONSENSUS_REACHED' | 'SUPERSEDED';
  messages: DeliberationMessage[];
  round?: number;
  rounds?: { round: number; started_at: string; feedback: string | null }[];
  decision_ref?: string | null;
  proposals?: ArchitecturePlan[];
  chosen_plan_id?: string | null;
  consensus_summary?: {
    chosen_plan: string;
    chosen_plan_id?: string;
    proposed_plan_id?: string;
    decision: string;
    agreed_stack: string[];
    total_participants: number;
    completed_at: string;
    decision_ref?: string;
    revision_feedback?: string;
    implementation_task?: { issue_id?: string; key?: string; title?: string; when?: string };
  };
  created_at: string;
  updated_at: string;
}

export interface JiraIssue {
  id: string;
  key: string;
  order: number;
  title: string;
  description: string;
  issue_type: JiraIssueType;
  status: JiraIssueStatus;
  priority: 'P0' | 'P1' | 'P2';
  assignee: AgentRole;
  parent_id?: string;
  acceptance_criteria: string[];
  attachments: (string | JiraAttachment)[];
  audit_trail?: TaskAuditEntry[];
  created_at: string;
  updated_at: string;
  /** Mimarın backlog'undan / PO iyileştirmesinden türeyen görev */
  kind?: 'task' | string;
  task_key?: string;
  depends_on?: string[];
  files_hint?: string[];
  run_id?: string;
  /** Sprint kipi: maddenin alındığı sprint, yöneticinin sabitlediği sprint ve backlog sırası */
  sprint?: number | null;
  planned_sprint?: number | null;
  /** Yönetici öncelik şeridi: 'now' = önce yap (çalışan koşuda hemen), 'next_sprint' = sıradaki sprintin başı */
  expedite?: 'now' | 'next_sprint' | null;
  manual_rank?: number | null;
  /** G5 Jira+ */
  labels?: string[];
  components?: string[];
  estimate?: string | number | null;
  due?: string | null;
  links?: JiraLink[];
  comments?: JiraComment[];
  watchers?: string[];
  history?: JiraHistoryEntry[];
  deleted?: JiraDeleted | null;
  board_rank?: number | null;
  ac_refs?: string[];
  work_type?: string;
  carry_over?: { count?: number; reason?: string } | null;
}

export interface SpecFile {
  filename: string;
  saved_path: string;
  file_url: string;
  size: number;
  content_type?: string;
}

export interface UploadedSpec {
  id: string;
  title: string;
  client_name: string;
  meeting_notes: string;
  files: SpecFile[];
  created_at: string;
}

export interface PlaywrightReport {
  id: string;
  timestamp: string;
  status: 'PASSED' | 'FAILED';
  target_url: string;
  scenario: string;
  screenshots: string[];
  logs: string[];
  duration_ms: number;
}

export interface TelemetryEvent {
  id: string;
  type: string;
  trace_id: string;
  from_agent: AgentRole;
  to_agent: AgentRole;
  action: string;
  status: 'SUCCESS' | 'FAILED' | 'IN_PROGRESS' | 'BLOCKED';
  payload: any;
  current_file?: string;
  tokens_used: number;
  timestamp: string;
  friendly_dialogue?: string;
  thinking?: string;
  what_doing?: string;
  what_next?: string;
  /** Projeler arası mesajlarda dolar */
  from_project?: string;
  to_project?: string;
}

export interface TelemetryStats {
  total_events: number;
  total_tokens: number;
  active_tasks_count: number;
  start_time: string;
}

export interface ProjectInfo {
  id: string;
  name: string;
  path: string;
  is_active: boolean;
  events_count: number;
  tasks_count: number;
  jira_count?: number;
  specs_count?: number;
  last_active: string;
}

export interface TestUserProfile {
  id: string;
  name: string;
  target_url: string;
  username: string;
  /** Sunucu düz metin şifreyi göndermez; yalnızca kaydederken doldurulur */
  password?: string;
  has_password?: boolean;
  role: string;
  description?: string;
  is_preset?: boolean;
  updated_at?: string;
}

export interface StepArtifact {
  name: string;
  path: string;
  type: 'markdown' | 'json' | 'python' | 'typescript' | 'dockerfile' | 'yaml' | string;
  content: string;
}

export interface StepApprovalInfo {
  order: number;
  issue_id: string;
  title: string;
  agent_id: string;
  agent_name: string;
  agent_role: string;
  next_agent_id?: string | null;
  next_agent_name?: string | null;
  action: string;
  summary: string;
  artifacts: StepArtifact[];
  screenshots?: string[];
  tokens_used: number;
  timestamp: string;
  is_last_step?: boolean;
  /** Sunucunun bu adım için ürettiği onay token'ı (approve-step isteğinde geri gönderilir). */
  approval_token?: string;
  /** Adımın ait olduğu pipeline koşusu. */
  run_id?: string;
  /** 'decisions' ise bu bir teknoloji kararları kapısıdır (adım çıktısı değil); 'task'/'fix' dinamik adımlardır */
  kind?: 'step' | 'decisions' | 'phase' | 'task' | 'fix';
  questions?: TechQuestion[];
  fix_round?: number;
  step_index?: number;
  total_steps?: number;
  verification?: VerificationSummary | null;
  commit?: string | null;
  fix_requested?: boolean;
  inserted_steps?: number;
}

export interface AgentVersion {
  version_id: string;
  order: number;
  created_at: string;
  author: string;
  commit_message: string;
  file_name: string;
  hash: string;
}

export interface AgentPromptInfo {
  agent_id: string;
  role: string;
  current_version: string;
  active_content: string;
  versions: AgentVersion[];
  file_path: string;
  parent_standard: string;
  total_versions: number;
}

export interface LLMModelConfig {
  provider: 'gemini' | 'claude' | string;
  model_id: string;
  temperature?: number;
  max_tokens?: number;
  updated_at?: string;
}



// ---------------------------------------------------------------------------
// Pipeline Koşuları (Faz B) — motor bağımsız koşu kaydı
// ---------------------------------------------------------------------------
export type ExecutionEngine = 'mcp_client' | 'template';
export type RunStatus = 'QUEUED' | 'ACTIVE' | 'WAITING_APPROVAL' | 'COMPLETED' | 'CANCELLED' | 'ABANDONED' | 'FAILED';
export type StepRecordStatus = 'PENDING' | 'ACTIVE' | 'WAITING_APPROVAL' | 'DONE' | 'REJECTED' | 'FAILED' | 'SKIPPED';

/** Adım türü: 1-10 fazı, mimarın backlog görevi ya da doğrulama sonrası düzeltme turu */
export type StepKind = 'phase' | 'task' | 'fix';

export interface VerificationResult {
  name: string;
  status: 'PASSED' | 'FAILED' | 'SKIPPED' | string;
  exit_code?: number | null;
  duration_ms?: number;
  cmd?: string;
  output?: string;
  /** Komutun TAM çıktısı (proje köküne göreli dosya yolu; bellekteki `output` kırpılmış olabilir) */
  log_file?: string | null;
  tests?: TestCounts | null;
}

export interface TestCounts {
  total: number;
  passed: number;
  failed: number;
  errors: number;
  skipped: number;
}

/** Sunucu tarafı doğrulama özeti (sözdizimi → kurulum → lint → build → test) */
export interface VerificationSummary {
  status: 'PASSED' | 'FAILED' | 'SKIPPED' | string;
  summary: string;
  failed_step?: string | null;
  results: VerificationResult[];
  /** junit sayıları (test komutu koştuysa) */
  tests?: TestCounts | null;
  /** junit'ten ad ad başarısız testler */
  failed_tests?: { id: string; message?: string }[];
  isolation?: 'venv' | 'host' | string;
}

export interface StepRecord {
  order: number;
  issue_id: string;
  role: string;
  status: StepRecordStatus;
  attempts: number;
  tokens_in: number;
  tokens_out: number;
  started_at?: string | null;
  finished_at?: string | null;
  artifacts: string[];
  summary: string;
  action: string;
  error?: string | null;
  server_side: boolean;
  validation_errors: string[];
  kind?: StepKind;
  title?: string;
  fix_round?: number;
  round?: number;
  verification?: VerificationSummary | null;
  commit?: string | null;
}

/** Sprint/toplantı ve teknoloji gereksinimi soru kuyruğundaki bir soru (GET /api/questions). */
export interface QueueQuestion {
  id: string;
  category: 'TECHNOLOGY' | 'EXTERNAL_ACTION' | 'SCOPE' | 'DESIGN' | string;
  raised_by?: string;
  text: string;
  options: { key: string; label: string }[];
  recommended?: string | null;
  rationale?: string;
  blocking: boolean;
  status: 'OPEN' | 'ANSWERED' | 'DEFAULTED' | 'OVERRIDDEN' | string;
  answer?: string | null;
  answered_by?: string | null;
  raised_at?: string;
  deadline?: string | null;
  sprint?: number | null;
  source?: string;
}

/** Yöneticinin dashboard'dan bıraktığı not ya da revize isteği (bir sonraki adımın bağlamına girer). */
export interface ManagerNote {
  id: string;
  kind: 'note' | 'revise';
  text: string;
  urgent: boolean;
  created_at: string;
  for_step?: number | null;
  /** Notun iletildiği adım; null ise henüz hiçbir adıma verilmedi. */
  delivered_step?: number | null;
  delivered_at?: string | null;
  /** Ajanın nota cevabı (`payload.manager_replies`). */
  reply?: { answer: string; by: string; step: number; at: string } | null;
  /** İletildiği adımda cevap verilmedi. */
  unanswered?: boolean;
}

export type RunOutcome = 'success' | 'with_failures';

export interface PipelineRun {
  /** G1: COMPLETED koşuda hatalı (FAILED) adım sayısı ve sonuç (`with_failures` = tamamlandı ama kanıtsız/başarısız adımlar var) */
  failed_steps?: number;
  outcome?: RunOutcome | null;
  run_id: string;
  manager_notes?: ManagerNote[];
  project_id: string;
  paused?: boolean;
  pause_reason?: string;
  engine: ExecutionEngine;
  steps: StepRecord[];
  cursor: number;
  status: RunStatus;
  custom_prompt: string;
  client_name: string;
  client_version: string;
  created_at: string;
  started_at?: string | null;
  finished_at?: string | null;
  last_seen: string;
  approval_token?: string | null;
  cancel_reason: string;
  step_by_step: boolean;
  project_dir: string;
  is_terminal: boolean;
  backlog_expanded?: boolean;
  intake_spec_ids?: string[];
  uat_round?: number;
  fix_rounds_total?: number;
  progress: { done: number; total: number; current_order: number | null; current_index?: number | null; tasks?: number; fixes?: number };
}

/** Doğrulama / çalıştırma komutları (mimar ve DevOps önerir, kullanıcı düzenler) */
export interface VerificationCommands {
  install?: string;
  test?: string;
  build?: string;
  lint?: string;
  run?: string;
  health_url?: string;
  app_url?: string;
}

export interface EngineSettings {
  execution_engine: ExecutionEngine;
  approval_mode: 'auto' | 'critical_only' | 'every_step' | 'note_and_continue';
  pacing: 'instant' | 'natural';
  e2e_target_url?: string;
  tech_decisions?: TechDecisions | null;
  /** Tam yaşam döngüsü ayarları */
  auto_backlog?: boolean;
  auto_verify?: boolean;
  auto_commit?: boolean;
  max_fix_rounds?: number;
  max_backlog_tasks?: number;
  max_uat_rounds?: number;
  verification?: VerificationCommands;
}

/** Teknoloji kararları kapısı (server/decisions.py) */
export interface TechQuestion {
  id: string;
  question: string;
  options: string[];
  recommended?: string;
  why?: string;
  source?: 'default' | 'spec';
}

export interface TechDecisions {
  answers: Record<string, string>;
  notes: string;
  source: 'user' | 'auto';
  answered_at: string;
}

export interface McpClientInfo {
  name: string;
  version: string;
  first_seen: string;
  last_seen: string;
  calls: number;
}

export interface RaisedHand {
  id: string;
  raised_at: string;
  reviewed: boolean;
  reviewed_at?: string | null;
  note: string;
  run_id?: string;
  order: number;
  issue_id: string;
  title: string;
  agent_id: string;
  agent_name?: string;
  action: string;
  summary: string;
  critical: boolean;
  step_info: StepApprovalInfo;
}

export interface LiveThinking {
  run_id: string;
  agent_id: string;
  order?: number | null;
  text: string;
  what_doing?: string;
  what_next?: string;
  timestamp: string;
}

// ---------------------------------------------------------------------------
// G2: Claude köprüsü — tam etkileşim günlüğü, başsız oturum, transkript aynası
// ---------------------------------------------------------------------------
export type ClaudeLogDirection = 'to_claude' | 'to_server' | 'manager' | 'client' | 'server';

/** İki yönlü etkileşim kaydı (liste görünümünde gövdeler kırpılmıştır; tam gövde /api/claude/log/{id}) */
export interface ClaudeLogEntry {
  id: string;
  ts: string;
  direction: ClaudeLogDirection;
  tool: string;
  run_id?: string | null;
  order?: number | null;
  agent_id?: string | null;
  kind?: string | null;
  client?: string | null;
  status?: string | null;
  duration_ms?: number | null;
  count?: number;
  session_id?: string | null;
  args?: unknown;
  result?: unknown;
  text?: string | null;
  error?: string | null;
  args_truncated?: boolean;
  result_truncated?: boolean;
  text_truncated?: boolean;
  project_id?: string | null;
}

export interface ClaudeLogQuery {
  run_id?: string;
  tool?: string;
  direction?: ClaudeLogDirection | '';
  q?: string;
  since?: string;
  limit?: number;
  offset?: number;
}

export interface ClaudeLogPage {
  total: number;
  entries: ClaudeLogEntry[];
  tools: string[];
  runs: string[];
}

export interface ClaudeCliStatus {
  ok: boolean;
  cli: string;
  path?: string | null;
  version?: string | null;
  error?: string | null;
  install_hint?: string;
}

export interface ClaudeBridgeConfig {
  cli: string;
  max_turns: number;
  model: string;
  extra_args: string;
  transcripts_dir: string;
  auto_watch: boolean;
  /** G3: iş varken sunucu kendisi başsız Claude oturumu açar (Desktop zamanlanmış görevinin sunucu tarafı karşılığı) */
  auto_runner: boolean;
  auto_runner_interval_min: number;
}

export interface AutoRunnerState {
  enabled: boolean;
  interval_min: number;
  running: boolean;
  last_check?: string | null;
  last_reason?: string | null;
  starts: number;
  last_start?: string | null;
}

export interface RunnerSetupStep {
  key: string;
  ok: boolean | null;
  text: string;
  fix?: string | null;
}

export interface RunnerSetup {
  desktop: { config_path: string; exists: boolean; registered: boolean; port?: string | null };
  cli: ClaudeCliStatus;
  auto_runner: AutoRunnerState;
  bridge_running: boolean;
  runner: { last_seen?: string | null; age_s?: number | null; fresh: boolean; client?: { name: string } | null; claims?: number; lease?: unknown; interval_min: number; waiting_for_client: boolean };
  claimable: { claimable: boolean; reason: string; run_id?: string };
  steps: RunnerSetupStep[];
  server_port: number;
}

export interface ClaudeBridgeState {
  running: boolean;
  pid?: number | null;
  session_id?: string | null;
  started_at?: string | null;
  finished_at?: string | null;
  exit_code?: number | null;
  events: number;
  turns: number;
  last_event?: { ts: string; kind: string; tool?: string | null; text?: string } | null;
  result?: { subtype?: string; is_error?: boolean; num_turns?: number; duration_ms?: number; total_cost_usd?: number } | null;
  error?: string | null;
  prompt?: string | null;
  resume_of?: string | null;
  session_file?: string | null;
  stderr_tail?: string;
  cli?: ClaudeCliStatus;
  config?: ClaudeBridgeConfig;
  runner_prompt?: string;
  allowed_tools?: string;
  auto_runner?: AutoRunnerState;
}

export interface ClaudeSessionEvent {
  ts: string;
  kind: 'system' | 'assistant_text' | 'thinking' | 'tool_use' | 'tool_result' | 'result' | 'raw' | string;
  session_id?: string | null;
  text?: string;
  tool?: string | null;
  tool_use_id?: string | null;
  run_id?: string | null;
  input?: unknown;
  is_error?: boolean;
  empty?: boolean;
  subtype?: string;
  num_turns?: number;
  duration_ms?: number;
  total_cost_usd?: number;
  model?: string | null;
}

export interface ClaudeBridgeSessionFile {
  session_id: string;
  file: string;
  size: number;
  modified_at: string;
  running?: boolean;
}

export interface TranscriptSession {
  session_id: string;
  file: string;
  size: number;
  modified_at: string;
  title?: string | null;
  first_prompt?: string | null;
  entrypoint?: string | null;
  version?: string | null;
  git_branch?: string | null;
  cwd?: string | null;
  scope?: 'fssc' | 'project' | string;
}

export interface TranscriptEvent {
  ts?: string | null;
  session_id?: string | null;
  uuid?: string | null;
  parent_uuid?: string | null;
  kind: 'user_text' | 'assistant_text' | 'thinking' | 'tool_use' | 'tool_result' | 'queued_prompt' | string;
  text?: string;
  tool?: string;
  tool_use_id?: string | null;
  fssc?: boolean;
  run_id?: string | null;
  input?: unknown;
  is_error?: boolean;
  empty?: boolean;
  duration_ms?: number | null;
  model?: string | null;
  file?: string;
}

export interface TranscriptEventsPage {
  session: TranscriptSession;
  events: TranscriptEvent[];
  offset: number;
  size: number;
  thinking: { total: number; empty: number; note?: string | null };
}

export interface ClaudeStatus {
  bridge: ClaudeBridgeState;
  transcripts: { watching: string[]; running: boolean; events_seen: number; last_event_at?: string | null };
  transcript_dirs: { scope: string; path: string; transcripts_dir: string }[];
  log_file?: string | null;
}

/** Claude panelinin veri/eylem paketi (useTelemetryWS → ClaudePanel) */
export interface ClaudePanelData {
  claudeLog: ClaudeLogEntry[];
  claudeSession: { state: ClaudeBridgeState | null; events: ClaudeSessionEvent[] };
  transcriptEvents: TranscriptEvent[];
  fetchClaudeLog: (params?: ClaudeLogQuery) => Promise<ClaudeLogPage>;
  fetchClaudeLogEntry: (id: string) => Promise<ClaudeLogEntry>;
  fetchClaudeStatus: () => Promise<ClaudeStatus>;
  claudeStart: (opts?: { prompt?: string; resume?: string; max_turns?: number }) => Promise<{ status: string; state?: ClaudeBridgeState; error?: string; install_hint?: string }>;
  claudeStop: () => Promise<{ status: string }>;
  fetchClaudeSessions: () => Promise<ClaudeBridgeSessionFile[]>;
  fetchClaudeSessionEvents: (sessionId: string) => Promise<ClaudeSessionEvent[]>;
  fetchTranscripts: () => Promise<{ sessions: TranscriptSession[]; watching: { watching: string[] } }>;
  fetchTranscriptEvents: (sessionId: string, limit?: number) => Promise<TranscriptEventsPage>;
  watchTranscript: (sessionId: string, fromStart?: boolean) => Promise<{ status: string; watching: string[] }>;
  updateClaudeSettings: (patch: Partial<ClaudeBridgeConfig>) => Promise<{ claude: ClaudeBridgeConfig; cli: ClaudeCliStatus; auto_runner?: AutoRunnerState }>;
  fetchRunnerSetup: () => Promise<RunnerSetup>;
}

// ---------------------------------------------------------------------------
// G4: otonomi seviyesi, L3 ön koşulları ve komut yalıtımı (/api/autonomy/overview)
// ---------------------------------------------------------------------------
export type AutonomyLevel = 'L0' | 'L1' | 'L2' | 'L3';

export interface AutonomyCheck {
  key: string;
  ok: boolean;
  text: string;
  fix?: string | null;
}

export interface SandboxSettings {
  mode: 'host' | 'container';
  command_policy: 'allowlist' | 'denylist';
  allowlist: string[];
  image: string;
}

export interface AutonomyOverview {
  level: AutonomyLevel | 'CUSTOM';
  autonomy: { question_timeout_s: number | null; strict_dod: boolean; level?: string; budget?: Record<string, number> };
  sandbox: SandboxSettings;
  docker_available: boolean;
  checks: AutonomyCheck[];
  l3_ok: boolean;
  default_allow_prefixes?: string[];
}

// ---------------------------------------------------------------------------
// G5 Jira+: yorum, bağ, ek, geçmiş, zaman çizelgesi, kanıt, sprint panosu, kayıtlı süzgeç, istemci API'si
// ---------------------------------------------------------------------------
export type JiraLinkType = 'blocks' | 'is_blocked_by' | 'relates' | 'duplicates' | 'tests' | 'tested_by';

export interface JiraComment { id: string; author: string; kind: 'agent' | 'manager'; text: string; created_at: string }
export interface JiraLink { type: JiraLinkType; target: string; by?: string; created_at?: string }
export interface JiraAttachment { id: string; name: string; path?: string; url?: string; by?: string; added_at?: string }
export interface JiraHistoryEntry { ts: string; by: string; field: string; from: unknown; to: unknown }
export interface JiraDeleted { at: string; by: string; reason: string }

export interface IssueTimelineEntry {
  ts: string;
  kind: 'field' | 'audit' | 'comment' | 'step';
  by?: string | null;
  text: string;
  action?: string;
  status?: string | null;
  field?: string;
  from?: unknown;
  to?: unknown;
  run_id?: string;
  order?: number;
  step_kind?: string;
  verification?: string | null;
  commit?: string | null;
  comment_id?: string;
  files?: string[];
}
export interface IssueTimeline { issue_id: string; status: string; entries: IssueTimelineEntry[]; why: string }

export interface DodCheck { key: string; ok: boolean; text: string }
export interface IssueEvidenceStep {
  run_id: string; run_status: string; engine: string; order: number; kind: string; fix_round: number; role: string; status: string;
  started_at?: string | null; finished_at?: string | null; summary: string; verification?: VerificationSummary | null; commit?: string | null;
  commit_status?: string; dod?: DodCheck[] | null; artifacts: string[]; attempts: number; error?: string | null;
}
export interface IssueEvidence {
  issue_id: string;
  steps: IssueEvidenceStep[];
  last_step: IssueEvidenceStep | null;
  last_verification: VerificationSummary | null;
  commits: { commit: string; run_id: string; order: number; at?: string | null; role: string }[];
  dod: DodCheck[] | null;
  ac_coverage: { total: number; covered: number; basis: string; items: { ac: string; evidence: string[]; ac_text?: string; files?: { path: string; summary: string; scenarios: { suite: string; name: string; line: number }[] }[] }[] };
  acceptance_criteria: string[];
}

export interface SprintSummary {
  sprint_number: number; status: string; goal?: string | null; committed: number; done: number; completed: number; carried: number;
  blocked?: { reason: string; since?: string; detail?: string; previous_status?: string } | null;
  planned_at?: string | null; committed_at?: string | null; started_at?: string | null; closed_at?: string | null; git_tag?: string | null;
  commit_approval?: { mode: string; by: string | null } | null; commit_deadline?: string | null; scope_changes: number; metrics: Record<string, unknown>;
}
export interface SprintBoardItem {
  id: string; key: string; order: number; title: string; status: JiraIssueStatus; priority: string; assignee: string; issue_type: string; work_type?: string;
  estimate?: string | number | null; carry_over?: { count?: number; reason?: string } | null; sprint?: number | null; planned_sprint?: number | null;
  deleted?: JiraDeleted | null; reason?: string; count?: number;
}
export interface SprintBoard {
  enabled: boolean;
  settings: Record<string, unknown>;
  project_status?: string | null;
  capacity: number;
  capacity_reason: string;
  wip: { limit: number; count: number; over: boolean; items: SprintBoardItem[] };
  pending_commit: { sprint: number; proposed: { issue_id: string; title?: string | null }[]; summary?: string | null; since?: string | null; deadline?: string | null } | null;
  current: (SprintSummary & { items: SprintBoardItem[]; proposed: SprintBoardItem[]; carried_items: SprintBoardItem[]; burndown: { ts: string; remaining: number }[];
    can: { commit: boolean; unblock: boolean; cancel: boolean; edit_goal: boolean } }) | null;
  velocity: { sprint: number; committed: number; done: number }[];
  sprints: SprintSummary[];
  can_plan_next: boolean;
}
export interface SavedFilter { name: string; q: string; created_at?: string }

export interface JiraApi {
  edit: (id: string, patch: Record<string, unknown>) => Promise<JiraIssue>;
  remove: (id: string, reason?: string) => Promise<JiraIssue>;
  restore: (id: string) => Promise<JiraIssue>;
  comment: (id: string, text: string) => Promise<JiraComment>;
  deleteComment: (id: string, commentId: string) => Promise<void>;
  link: (id: string, type: JiraLinkType, target: string) => Promise<void>;
  unlink: (id: string, type: JiraLinkType, target: string) => Promise<void>;
  attach: (id: string, a: { name?: string; path?: string; url?: string }) => Promise<JiraAttachment>;
  detach: (id: string, attachmentId: string) => Promise<void>;
  move: (id: string, status: JiraIssueStatus, index?: number) => Promise<JiraIssue>;
  plan: (id: string, body: Record<string, unknown>) => Promise<JiraIssue>;
  bulk: (ids: string[], action: string, value?: unknown) => Promise<{ ok: number; failed: number; results: { id: string; ok: boolean; error?: string }[] }>;
  query: (q: string, includeDeleted?: boolean) => Promise<JiraIssue[]>;
  filters: () => Promise<{ filters: SavedFilter[]; fields: string[] }>;
  saveFilter: (name: string, q: string) => Promise<SavedFilter[]>;
  deleteFilter: (name: string) => Promise<SavedFilter[]>;
  timeline: (id: string) => Promise<IssueTimeline>;
  evidence: (id: string) => Promise<IssueEvidence>;
  sprintBoard: () => Promise<SprintBoard>;
  sprintGoal: (n: number, goal: string) => Promise<void>;
  sprintCommit: (n: number) => Promise<void>;
  sprintUnblock: (n: number) => Promise<void>;
  sprintCancel: (n: number) => Promise<void>;
  planNext: () => Promise<void>;
}

// ---------------------------------------------------------------------------
// G7: test ekibi (server/testing.py)
// ---------------------------------------------------------------------------
export type TestResultValue = 'PASS' | 'FAIL' | 'BLOCKED' | 'SKIP';

export interface TestCaseResult {
  result: TestResultValue;
  run?: string;
  at?: string;
  message?: string;
  source?: string;
}

export interface TestCase {
  id: string;
  title: string;
  type: string;
  priority: string;
  status: 'DRAFT' | 'READY' | 'DEPRECATED';
  ac_refs: string[];
  story_ref?: string;
  steps: string[];
  expected: string;
  precondition?: string;
  data?: string;
  automation: string;
  labels: string[];
  quarantined?: boolean;
  owner?: string;
  issue_id?: string | null;
  file?: string | null;
  last_result?: TestCaseResult | null;
  open_bug?: string | null;
  history?: { result: string; run: string; at: string }[];
}

export interface TestRunResultRow {
  case: string;
  result: TestResultValue;
  title: string;
  evidence?: Record<string, unknown>;
  quarantined?: boolean;
}

export interface TestRun {
  id: string;
  title: string;
  sprint: number;
  source: string;
  executed_by: string;
  finished_at: string;
  results: TestRunResultRow[];
  summary: { total: number; pass: number; fail: number; blocked: number; skip: number };
  bugs: string[];
  flaky: string[];
  issue_id?: string | null;
  perf?: Record<string, unknown> | null;
}

export interface TestMatrixRow {
  ac: string;
  text: string;
  story?: string | null;
  po_status?: string | null;
  state: 'COVERED' | 'FAILING' | 'UNTESTED' | 'NO_CASE';
  cases: { id: string; title: string; type: string; automation: string; result?: TestResultValue | null; quarantined: boolean; issue_id?: string | null }[];
  tests_mentioned: string[];
}

export interface TestMatrix {
  rows: TestMatrixRow[];
  total: number;
  covered: number;
  coverage_pct: number | null;
  target_pct: number;
  no_case: string[];
  failing: string[];
  untested: string[];
  unlinked_cases: string[];
}

export interface TestingSummary {
  cases: number;
  by_status: Record<string, number>;
  by_type: Record<string, number>;
  automated: number;
  manual: number;
  results: Record<string, number>;
  never_run: number;
  flaky: number;
  coverage_pct: number | null;
  target_pct: number;
  uncovered: string[];
  failing_acs: string[];
  regression: { ok: boolean; size: number; failing: string[]; unexecuted: string[]; manual_pending?: string[] };
  runs: number;
  last_run: { id: string; title: string; source: string; sprint: number; summary: TestRun['summary']; finished_at: string } | null;
  open_bugs: number;
}

export interface TestingConfig {
  coverage_target: number;
  perf_p95_ms: number;
  perf_samples: number;
  design_task: boolean;
  auto_regression: boolean;
}

export interface E2EScenario {
  id: string;
  title?: string;
  file?: string;
  ac_refs: string[];
  steps: Record<string, unknown>[];
  invalid?: string;
}
