export type SupportedLanguage = 'tr' | 'en' | 'es' | 'de';

export interface LanguageOption {
  code: SupportedLanguage;
  label: string;
  nativeLabel: string;
  flag: string;
}

export const SUPPORTED_LANGUAGES: LanguageOption[] = [
  { code: 'en', label: 'English', nativeLabel: 'English', flag: '🇬🇧' },
  { code: 'tr', label: 'Turkish', nativeLabel: 'Türkçe', flag: '🇹🇷' },
  { code: 'es', label: 'Spanish', nativeLabel: 'Español', flag: '🇪🇸' },
  { code: 'de', label: 'German', nativeLabel: 'Deutsch', flag: '🇩🇪' },
];

export interface Translations {
  common: {
    save: string;
    cancel: string;
    close: string;
    apply: string;
    delete: string;
    edit: string;
    add: string;
    reset: string;
    loading: string;
    success: string;
    error: string;
    warning: string;
    info: string;
    ok: string;
    yes: string;
    no: string;
    retry: string;
    search: string;
    filter: string;
    all: string;
    none: string;
    actions: string;
    copy: string;
    copied: string;
    token: string;
    tokens: string;
    duration: string;
    status: string;
    language: string;
    selectLanguage: string;
    details: string;
    back: string;
    proceed: string;
    refresh: string;
    confirm: string;
  };
  topbar: {
    serverConnected: string;
    waitingConnection: string;
    staleCode: string;
    serverInClaude: string;
    searchPlaceholder: string;
    searchTitle: string;
    executeBatch: string;
    executing: string;
    tokenUsageEst: string;
  };
  rail: {
    board: string;
    boardTitle: string;
    agentMesh: string;
    agentMeshTitle: string;
    files: string;
    filesTitle: string;
    docs: string;
    docsTitle: string;
    deliberation: string;
    deliberationTitle: string;
    questions: string;
    questionsTitle: string;
    tests: string;
    testsTitle: string;
    reports: string;
    reportsTitle: string;
    settings: string;
    settingsTitle: string;
  };
  menu: {
    playwrightE2e: string;
    playwrightE2eTitle: string;
    testManagement: string;
    testManagementTitle: string;
    runTestsOnly: string;
    runTestsOnlyTitle: string;
    testingInProgress: string;
    projectSettings: string;
    projectSettingsTitle: string;
    specs: string;
    specsTitle: string;
    decisions: string;
    decisionsTitle: string;
    pendingBadge: string;
    runs: string;
    runsTitle: string;
    addAgent: string;
    addAgentTitle: string;
    management: string;
    managementTitle: string;
    model: string;
    modelTitle: string;
    claude: string;
    claudeTitle: string;
    telemetry: string;
    telemetryTitle: string;
    designStart: string;
    designStartTitle: string;
    linkOrphans: string;
    linkOrphansTitle: string;
    restoreAgents: string;
    restoreAgentsTitle: string;
    budgetPage: string;
    budgetPageTitle: string;
  };
  banners: {
    answerRequired: string;
    blockingQuestionsCount: string;
    answerQuestionsBtn: string;
    techDecisionsPending: string;
    stepApprovalPending: string;
    techDecisionsDesc: string;
    stepApprovalDesc: string;
    makeDecisions: string;
    continueRecommended: string;
    reviewAndApprove: string;
    runCompleted: string;
    testSuite: string;
    pipelineRun: string;
    resumed: string;
    paused: string;
    cancelled: string;
    linkSuccess: string;
    noOrphans: string;
    agentsRestored: string;
    noAgentsToRestore: string;
    serverUnreachable: string;
    designQueued: string;
    linkConfirmPrompt: string;
  };
  config: {
    title: string;
    appearance: string;
    themeLight: string;
    themeDark: string;
    fontScaleTitle: string;
    accentColorTitle: string;
    languageTitle: string;
    projectFolder: string;
    projectFolderPlaceholder: string;
    browse: string;
    bind: string;
    telemetry: string;
    resetTelemetry: string;
    resetConfirm: string;
    projectSettingsBtn: string;
    projectSettingsSub: string;
  };
  views: {
    topology: string;
    office: string;
    honeycomb: string;
    gatheringMeeting: string;
    gatheringRoom: string;
    backToLive: string;
    timeTravel: string;
    step: string;
    event: string;
  };
  jira: {
    boardTitle: string;
    backlog: string;
    todo: string;
    inProgress: string;
    review: string;
    done: string;
    batchRun: string;
    newIssue: string;
    startSprint: string;
    completeSprint: string;
    filters: string;
    clearFilters: string;
    expandAll: string;
    collapseAll: string;
    noIssues: string;
    assignee: string;
    priority: string;
    storyPoints: string;
    epic: string;
    story: string;
    task: string;
    bug: string;
    subtask: string;
  };
  agents: {
    stateIdle: string;
    stateThinking: string;
    stateWorking: string;
    stateAwaiting: string;
    stateCompleted: string;
    stateError: string;
  };
  modals: {
    clientVault: string;
    uploadFile: string;
    dragDrop: string;
    techDecisionsTitle: string;
    questionsTitle: string;
    agentManagerTitle: string;
    testManagementTitle: string;
    modelSwitcherTitle: string;
    runHistoryTitle: string;
    stepInspectorTitle: string;
  };
}
