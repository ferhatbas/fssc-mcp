import React, { useEffect, useMemo, useState } from 'react';
import { createPortal } from 'react-dom';
import {
  Activity, ArrowRight, Check, Copy, Download, ExternalLink, Eye, FileText, Play, Plug, RefreshCw, RotateCcw, Search, Square, User, X, Zap,
} from 'lucide-react';
import {
  ClaudeBridgeSessionFile, ClaudeLogEntry, ClaudeLogDirection, ClaudePanelData, ClaudeSessionEvent, McpActivity, McpCall, RunnerSetup, TranscriptEvent,
  TranscriptSession,
} from '../types/telemetry';
import { api } from '../config';
import { useI18n } from '../i18n';

type TFn = (key: string, params?: Record<string, string | number>, fallback?: string) => string;

const TOOL_LABEL: Record<string, string> = {
  get_next_step: 'iş çekti',
  submit_step_result: 'teslim etti',
  wait_for_approval: 'onay yokladı',
  report_thinking: 'düşüncesini bildirdi',
  list_runs: 'koşuları listeledi',
  start_pipeline_run: 'koşu başlattı',
  cancel_pipeline_run: 'koşuyu iptal etti',
  claim_work: 'iş üstlendi',
  answer_question: 'soru cevapladı',
  list_questions: 'soruları okudu',
  add_manager_input: 'yönetici notu ekledi',
  get_activity_feed: 'etkinlik akışını okudu',
  get_sprint_state: 'sprint durumunu okudu',
  get_tech_requirements: 'teknoloji gereksinimlerini okudu',
  get_mesh_topology: 'ajan ağını okudu',
  emit_agent_event: 'olay gönderdi',
  report_agent_metric: 'ajan metriği bildirdi',
};

const TURN_STYLE: Record<string, { cls: string; icon: React.ReactNode; badge: string }> = {
  claude: { cls: 'border-ok bg-okd text-ok', icon: <Zap className="w-6 h-6 animate-pulse" />, badge: 'SIRA CLAUDE\'DA' },
  claude_wait: { cls: 'border-info bg-infod text-info', icon: <Plug className="w-6 h-6" />, badge: 'CLAUDE BEKLENİYOR' },
  manager: { cls: 'border-warn bg-warnd text-warn', icon: <User className="w-6 h-6 animate-pulse" />, badge: 'SIRA SENDE' },
  server: { cls: 'border-ac bg-acd text-ac', icon: <Activity className="w-6 h-6" />, badge: 'SUNUCU' },
  idle: { cls: 'border-line bg-sunk text-ink3', icon: <Activity className="w-6 h-6" />, badge: 'BOŞTA' },
};

const STATE_META: Record<string, { label: string; dot: string }> = {
  connected: { label: 'Bağlı (az önce çağrı yaptı)', dot: 'bg-ok' },
  waiting: { label: 'Çağrı yok: Claude düşünüyor/üretiyor olabilir', dot: 'bg-warn' },
  away: { label: 'Uzakta (uzun süredir çağrı yok)', dot: 'bg-err' },
  none: { label: 'Hiç bağlanmadı', dot: 'bg-ink3' },
};

const DIRECTION_META: Record<ClaudeLogDirection | string, { label: string; cls: string }> = {
  to_claude: { label: 'FS-SC → Claude', cls: 'bg-acd text-ac border-ac/40' },
  to_server: { label: 'Claude → FS-SC', cls: 'bg-okd text-ok border-ok/40' },
  manager: { label: 'Yönetici', cls: 'bg-warnd text-warn border-warn/40' },
  client: { label: 'Claude oturumu', cls: 'bg-infod text-info border-info/40' },
  server: { label: 'FS-SC', cls: 'bg-sunk text-ink3 border-line' },
};

const EVENT_KIND_META: Record<string, { label: string; cls: string }> = {
  thinking: { label: 'düşünce', cls: 'text-ink3 italic' },
  assistant_text: { label: 'Claude', cls: 'text-ink' },
  user_text: { label: 'istem', cls: 'text-warn' },
  queued_prompt: { label: 'kuyruk', cls: 'text-warn' },
  tool_use: { label: 'araç çağrısı', cls: 'text-ac font-mono' },
  tool_result: { label: 'araç sonucu', cls: 'text-ink2 font-mono' },
  system: { label: 'oturum', cls: 'text-ink3' },
  result: { label: 'sonuç', cls: 'text-ok' },
  raw: { label: 'ham', cls: 'text-ink3' },
};

function ago(t: TFn, iso: string | null | undefined, nowMs: number): string {
  if (!iso) return '—';
  const sec = Math.max(0, Math.round((nowMs - new Date(iso).getTime()) / 1000));
  if (sec < 5) return t('run.cp.agoNow', undefined, 'az önce');
  if (sec < 60) return t('run.cp.agoSec', { s: sec }, `${sec} sn önce`);
  if (sec < 3600) return t('run.cp.agoMinSec', { m: Math.floor(sec / 60), s: sec % 60 }, `${Math.floor(sec / 60)} dk ${sec % 60} sn önce`);
  return t('run.cp.agoHourMin', { h: Math.floor(sec / 3600), m: Math.floor((sec % 3600) / 60) }, `${Math.floor(sec / 3600)} sa ${Math.floor((sec % 3600) / 60)} dk önce`);
}

/** Etiket sözlükleri Türkçe yedektir; görünen metin run.cp.<grup>.<kod> anahtarıyla çevrilir. */
const toolLabel = (t: TFn, tool: string): string => (TOOL_LABEL[tool] ? t(`run.cp.tool.${tool}`, undefined, TOOL_LABEL[tool]) : '');
const kindLabel = (t: TFn, kind: string): string => {
  const k = EVENT_KIND_META[kind] ? kind : 'raw';
  return t(`run.cp.kind.${k}`, undefined, EVENT_KIND_META[k].label);
};
const dirLabel = (t: TFn, dir: string): string => {
  const k = DIRECTION_META[dir] ? dir : 'server';
  return t(`run.cp.dir.${k}`, undefined, DIRECTION_META[k].label);
};

const hhmmss = (iso?: string | null) => (iso ? new Date(iso).toLocaleTimeString('tr-TR', { hour: '2-digit', minute: '2-digit', second: '2-digit' }) : '—');

const resultCls = (r?: string | null) =>
  r === 'STEP' || r === 'NEXT' || r === 'APPROVED' || r === 'OK' || r === 'STARTED' ? 'text-ok'
    : r === 'WAITING_APPROVAL' || r === 'STILL_WAITING' || r === 'PAUSED' ? 'text-warn'
      : r === 'REJECTED' || r === 'CANCELLED' || r === 'REVISE' || r === 'ERROR' || r === 'FAILED' ? 'text-err' : 'text-ink2';

const pretty = (v: unknown): string => {
  if (v === null || v === undefined) return '';
  if (typeof v === 'string') return v;
  try {
    return JSON.stringify(v, null, 1);
  } catch {
    return String(v);
  }
};

type Tab = 'durum' | 'baslat' | 'gunluk' | 'oturum';

interface ClaudePanelProps {
  activity: McpActivity | null;
  projectName?: string;
  /** Ayrı sekmede açma düğmesi (sayfa modunda gösterilmez). */
  onOpenNewTab?: () => void;
  /** G2: köprü/günlük/transkript verileri ve eylemleri (useTelemetryWS.claudePanelData) */
  claude?: ClaudePanelData;
}

// ---------------------------------------------------------------------------
// Sekme: Durum (şimdi sıra kimde, bağlantı, prompt, son çağrılar)
// ---------------------------------------------------------------------------
const StatusTab: React.FC<{ activity: McpActivity; projectName?: string; nowMs: number }> = ({ activity, projectName, nowMs }) => {
  const { t } = useI18n();
  const [copied, setCopied] = useState(false);
  const { client, client_state: state, calls } = activity;
  const meta = STATE_META[state] || STATE_META.none;
  const prompt = t('run.cp.prompt', { p: projectName || 'demo_project' }, `${projectName || 'demo_project'} projesi için pipeline'ı çalıştır`);
  const copyPrompt = async () => {
    try {
      await navigator.clipboard.writeText(prompt);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* panoya erişim engellenmiş olabilir */
    }
  };
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div className="rounded-xl border border-line bg-panel p-4 space-y-2">
          <div className="text-[10px] font-mono font-bold uppercase tracking-wider text-ink3">{t('run.cp.connection', undefined, 'Claude bağlantısı')}</div>
          <div className="flex items-center gap-2 text-sm text-ink">
            <span className={`w-2.5 h-2.5 rounded-full ${meta.dot} ${state === 'connected' ? 'animate-pulse' : ''}`} />
            {t(`run.cp.state.${state}`, undefined, meta.label)}
          </div>
          {client ? (
            <dl className="text-xs text-ink2 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1">
              <dt className="text-ink3">{t('run.cp.client', undefined, 'İstemci')}</dt><dd className="font-mono text-ink">{client.name}{client.version ? ` v${client.version}` : ''}</dd>
              <dt className="text-ink3">{t('run.cp.lastCall', undefined, 'Son çağrı')}</dt><dd>{ago(t, client.last_seen, nowMs)}</dd>
              <dt className="text-ink3">{t('run.cp.firstSeen', undefined, 'İlk görülme')}</dt><dd>{client.first_seen ? hhmmss(client.first_seen) : '—'}</dd>
              <dt className="text-ink3">{t('run.cp.totalCalls', undefined, 'Toplam çağrı')}</dt><dd className="font-mono">{client.calls ?? 0}</dd>
            </dl>
          ) : (
            <div className="text-xs text-ink3">{t('run.cp.noClient', undefined, 'Henüz hiçbir istemci araç çağırmadı.')}</div>
          )}
        </div>
        <div className="rounded-xl border border-line bg-panel p-4 space-y-2">
          <div className="text-[10px] font-mono font-bold uppercase tracking-wider text-ink3">{t('run.cp.howTitle', undefined, 'Nasıl iletişim kuruluyor?')}</div>
          <ol className="text-xs text-ink2 space-y-1.5 list-decimal pl-4">
            <li>{t('run.cp.how1', undefined, 'FS-SC hiçbir şey itmez; Claude, MCP aracı get_next_step ile sunucudan iş çeker.')}</li>
            <li>{t('run.cp.how2a', undefined, 'Claude rolü üstlenir, çıktıyı üretir ve')} <code className="font-mono">submit_step_result</code> {t('run.cp.how2b', undefined, 'ile teslim eder.')}</li>
            <li>{t('run.cp.how3', undefined, 'Sunucu dosyaları yazar, testleri koşar, commit atar; onay gerekiyorsa sıra sana geçer.')}</li>
            <li>{t('run.cp.how4', undefined, "Her iki yöndeki tam içerik Etkileşim günlüğü sekmesinde; Claude'un kendi oturumu Oturum aynası sekmesinde.")}</li>
          </ol>
          <div className="text-[11px] text-ink3 flex items-center gap-1 flex-wrap">
            Claude <ArrowRight className="w-3 h-3" /> {t('run.cp.flowStdio', undefined, 'stdio MCP süreci')} <ArrowRight className="w-3 h-3" /> {t('run.cp.flowWeb', undefined, 'web sunucusu')} <ArrowRight className="w-3 h-3" /> {t('run.cp.flowPanel', undefined, 'bu pano')}
          </div>
        </div>
      </div>
      <div className="rounded-xl border border-line bg-panel p-4 space-y-2">
        <div className="text-[10px] font-mono font-bold uppercase tracking-wider text-ink3">{t('run.cp.manualTitle', undefined, 'Elle sürmek için (Claude Desktop / Claude Code)')}</div>
        <div className="text-xs text-ink2">
          {t('run.cp.manualText', undefined, 'Claude\'un panoya "eklenmesi" gerekmez: kendi oturumunda bu MCP sunucusunu kullanır. Elle sürmek için o oturuma şunu yaz; panodan başlatmak için Başlat & Bağlan sekmesini kullan.')}
        </div>
        <div className="flex items-center gap-2">
          <code className="flex-1 truncate text-[11px] font-mono bg-sunk border border-line rounded-md px-2 py-1.5 text-ink select-all">{prompt}</code>
          <button onClick={copyPrompt} className="inline-flex items-center gap-1 text-[11px] font-semibold px-2.5 py-1.5 rounded-md bg-ink text-bg hover:opacity-90 transition">
            {copied ? <Check className="w-3.5 h-3.5" /> : <Copy className="w-3.5 h-3.5" />}
            {copied ? t('run.cp.copied', undefined, 'Kopyalandı') : t('run.cp.copy', undefined, 'Kopyala')}
          </button>
        </div>
      </div>
      <div className="rounded-xl border border-line bg-panel overflow-hidden">
        <div className="px-4 py-2 border-b border-line text-[10px] font-mono font-bold uppercase tracking-wider text-ink3 flex items-center justify-between">
          <span>{t('run.cp.recentCalls', undefined, 'Son araç çağrıları (özet, canlı)')}</span>
          <span className="normal-case text-ink3 font-sans font-normal">{t('run.cp.recordsN', { n: calls.length }, `${calls.length} kayıt`)}</span>
        </div>
        {calls.length === 0 ? (
          <div className="p-6 text-center text-xs text-ink3 italic">{t('run.cp.noCallsA', undefined, 'Henüz çağrı yok. Claude')} <code className="font-mono">get_next_step</code> {t('run.cp.noCallsB', undefined, 'çağırınca burada görünür.')}</div>
        ) : (
          <ul className="divide-y divide-line max-h-80 overflow-y-auto">
            {calls.map((c: McpCall, i: number) => (
              <li key={`${c.ts}-${i}`} className="px-4 py-1.5 text-[11px] flex items-start gap-3">
                <span className="font-mono text-ink3 shrink-0 w-[62px]">{hhmmss(c.ts)}</span>
                <span className="font-mono font-semibold text-ink shrink-0 w-[150px]">{c.tool}</span>
                <span className={`font-mono shrink-0 w-[130px] ${resultCls(c.result)}`}>{c.result || '—'}{c.count > 1 ? ` ×${c.count}` : ''}</span>
                <span className="text-ink2 min-w-0 truncate" title={c.title}>
                  {toolLabel(t, c.tool)}{c.order != null ? ` · ${t('run.cp.stepNo', { n: c.order }, `adım #${c.order}`)}` : ''}{c.agent_id ? ` · ${c.agent_id}` : ''}{c.title ? ` · ${c.title}` : ''}
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
};

// ---------------------------------------------------------------------------
// Sekme: Başlat & Bağlan (başsız Claude Code köprüsü)
// ---------------------------------------------------------------------------
const SessionEventRow: React.FC<{ e: ClaudeSessionEvent | TranscriptEvent }> = ({ e }) => {
  const { t } = useI18n();
  const meta = EVENT_KIND_META[e.kind] || EVENT_KIND_META.raw;
  const [open, setOpen] = useState(false);
  const body = e.kind === 'tool_use' ? pretty((e as ClaudeSessionEvent).input) : (e.text || '');
  const isEmptyThinking = e.kind === 'thinking' && (e as ClaudeSessionEvent).empty;
  return (
    <li className="px-3 py-1.5 text-[11px] border-b border-line last:border-0">
      <div className="flex items-start gap-2">
        <span className="font-mono text-ink3 shrink-0 w-[62px]">{hhmmss(e.ts || null)}</span>
        <span className={`shrink-0 w-[92px] font-semibold ${meta.cls}`}>{kindLabel(t, e.kind)}</span>
        <div className="min-w-0 flex-1">
          {e.kind === 'tool_use' && <span className="font-mono text-ac">{e.tool}{e.run_id ? ` · ${e.run_id}` : ''}</span>}
          {e.kind === 'result' && (
            <span className="text-ok">{(e as ClaudeSessionEvent).subtype || t('run.cp.finished', undefined, 'bitti')} · {(e as ClaudeSessionEvent).num_turns ?? '?'} {t('run.cp.turns', undefined, 'tur')}{(e as ClaudeSessionEvent).total_cost_usd != null ? ` · ${t('run.cp.costNote', { cost: Number((e as ClaudeSessionEvent).total_cost_usd).toFixed(3) }, `ücret kesilmez, abonelik payından düşer · API olsaydı tahmini $${Number((e as ClaudeSessionEvent).total_cost_usd).toFixed(3)}`)}` : ''}</span>
          )}
          {isEmptyThinking ? (
            <span className="text-ink3 italic">{t('run.cp.thinkingNotStored', undefined, 'düşünce metni istemci tarafından saklanmamış (yalnızca imza)')}</span>
          ) : (
            body && (
              <pre className={`whitespace-pre-wrap font-sans text-[11px] ${meta.cls} ${open ? '' : 'max-h-[3.2em] overflow-hidden'}`}>{body}</pre>
            )
          )}
          {(e as ClaudeSessionEvent).is_error && <span className="text-err"> {t('run.cp.errorParen', undefined, '(hata)')}</span>}
        </div>
        {body && body.length > 160 && (
          <button onClick={() => setOpen(o => !o)} className="shrink-0 text-ink3 hover:text-ink" title={open ? t('run.cp.collapse', undefined, 'Daralt') : t('run.cp.showAll', undefined, 'Tamamını göster')}>
            <Eye className="w-3.5 h-3.5" />
          </button>
        )}
      </div>
    </li>
  );
};

// ---------------------------------------------------------------------------
// Runner kurulum kartı (G3): Desktop kaydı, CLI, otomatik runner, zamanlanmış görev
// ---------------------------------------------------------------------------
const RunnerCard: React.FC<{ claude: ClaudePanelData; nowMs: number }> = ({ claude, nowMs }) => {
  const { t } = useI18n();
  const [setup, setSetup] = useState<RunnerSetup | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [interval, setIntervalMin] = useState<number>(2);
  const load = async () => {
    try {
      const s = await claude.fetchRunnerSetup();
      setSetup(s);
      setIntervalMin(s.auto_runner.interval_min);
      setError('');
    } catch (e) {
      setError(e instanceof Error ? e.message : t('run.cp.setupReadErr', undefined, 'Kurulum durumu okunamadı'));
    }
  };
  useEffect(() => { load(); const iv = setInterval(load, 15000); return () => clearInterval(iv); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, []);
  const toggle = async (enabled: boolean) => {
    setBusy(true);
    try {
      await claude.updateClaudeSettings({ auto_runner: enabled, auto_runner_interval_min: interval });
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : t('run.cp.settingSaveErr', undefined, 'Ayar kaydedilemedi'));
    } finally {
      setBusy(false);
    }
  };
  const auto = setup?.auto_runner;
  return (
    <div className="rounded-xl border border-line bg-panel p-4 space-y-2">
      <div className="text-[10px] font-mono font-bold uppercase tracking-wider text-ink3 flex items-center justify-between">
        <span>{t('run.cp.driverSetup', undefined, 'Sürücü kurulumu (kimse prompt yazmadan çalışması için)')}</span>
        <button onClick={load} className="text-ink3 hover:text-ink"><RefreshCw className="w-3.5 h-3.5" /></button>
      </div>
      {error && <div className="text-err text-xs">{error}</div>}
      {!setup ? <div className="text-xs text-ink3">{t('run.cp.loading', undefined, 'Yükleniyor…')}</div> : (
        <ul className="text-xs space-y-1.5">
          {setup.steps.map(s => (
            <li key={s.key} className="flex items-start gap-2">
              <span className={`mt-1 w-2.5 h-2.5 rounded-full shrink-0 ${s.ok === true ? 'bg-ok' : s.ok === false ? 'bg-err' : 'bg-ink3'}`} />
              <div className="min-w-0">
                <div className="text-ink">{s.text}</div>
                {s.ok !== true && s.fix && <code className="text-[10.5px] font-mono text-ink3 break-all">{s.fix}</code>}
              </div>
            </li>
          ))}
        </ul>
      )}
      {setup && (
        <div className="flex items-center gap-3 flex-wrap pt-1 border-t border-line text-xs">
          <label className="inline-flex items-center gap-1.5 text-ink">
            <input type="checkbox" checked={!!auto?.enabled} disabled={busy || !setup.cli.ok} onChange={e => toggle(e.target.checked)} />
            {t('run.cp.autoRunner', undefined, 'Otomatik runner')}
          </label>
          <span className="text-ink3" title={t('run.cp.intervalsTitle', undefined, 'Aralıklar yukarıdaki Koşu bekçisi ekranından ayarlanır')}>{t('run.cp.everyMin', { n: auto?.interval_min ?? '—' }, `her ${auto?.interval_min ?? '—'} dk`)}</span>
          <span className="text-ink3">
            {auto?.running ? t('run.cp.loopRunning', undefined, 'döngü çalışıyor') : t('run.cp.loopOff', undefined, 'döngü kapalı')} · {t('run.cp.lastPoll', undefined, 'son yoklama')} {ago(t, auto?.last_check, nowMs)} · {auto?.last_reason || '—'} · {t('run.cp.startsN', { n: auto?.starts ?? 0 }, `${auto?.starts ?? 0} başlatma`)}
          </span>
          <span className="text-ink3 ml-auto">{t('run.cp.job', undefined, 'İş:')} {setup.claimable.claimable ? t('run.cp.claimable', { reason: setup.claimable.reason }, `üstlenilebilir (${setup.claimable.reason})`) : setup.claimable.reason} · {t('run.cp.runnerLastSeen', undefined, 'runner son görülme')} {ago(t, setup.runner.last_seen, nowMs)}</span>
        </div>
      )}
    </div>
  );
};

// ---------------------------------------------------------------------------
// Koşu bekçisi ayarları: kopan koşuyu belirli aralıkla yoklayıp ilerletme (aralıklar yapay zekâ talimatlarınca get_runner_schedule ile okunur)
// ---------------------------------------------------------------------------
interface RunnerSchedule {
  enabled: boolean; paused: boolean; interval_minutes: number; active_interval_min: number; paused_interval_min: number; abandon_after_min: number; suggested_cron: string;
  job: { run_id: string; status: string; mode: string; paused: boolean; idle_min: number | null; stalled: boolean; done_steps: number; total_steps: number } | null;
  claimable: { claimable: boolean; reason: string }; last_check?: string | null; next_check_at?: string | null; last_reason?: string | null;
}

const WatchdogCard: React.FC<{ nowMs: number }> = ({ nowMs }) => {
  const { t } = useI18n();
  const [sch, setSch] = useState<RunnerSchedule | null>(null);
  const [active, setActive] = useState(10);
  const [paused, setPaused] = useState(30);
  const [factor, setFactor] = useState(3);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState('');
  const [dirty, setDirty] = useState(false);
  const load = async (keepDraft = false) => {
    try {
      const r = await fetch('/api/runner/schedule');
      const j: RunnerSchedule = await r.json();
      setSch(j);
      if (!keepDraft) {
        setActive(j.active_interval_min); setPaused(j.paused_interval_min);
        setFactor(Math.max(1, Math.round(j.abandon_after_min / Math.max(1, j.active_interval_min))));
        setDirty(false);
      }
    } catch { setMsg(t('run.cp.scheduleReadErr', undefined, 'Takvim okunamadı')); }
  };
  useEffect(() => { load(); const iv = setInterval(() => load(true), 15000); return () => clearInterval(iv); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, []);
  const save = async () => {
    setBusy(true); setMsg('');
    try {
      const r = await fetch('/api/settings/runner', { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ interval_min: active, interval_paused_min: paused, abandon_factor: factor }) });
      if (!r.ok) throw new Error(t('run.cp.notSaved', undefined, 'Kaydedilemedi'));
      setMsg(t('run.cp.savedMsg', undefined, 'Kaydedildi. Yapay zekâ bu değerleri get_runner_schedule ile okuyup zamanlanmış görevini ayarlar.'));
      await load();
    } catch (e) { setMsg(e instanceof Error ? e.message : t('run.cp.notSaved', undefined, 'Kaydedilemedi')); } finally { setBusy(false); }
  };
  const checkNow = async () => {
    setBusy(true); setMsg('');
    try {
      const r = await fetch('/api/runner/check-now', { method: 'POST' });
      const j = await r.json();
      setMsg(t('run.cp.pollMsg', { reason: j?.auto_state?.last_reason || '—' }, `Yoklama: ${j?.auto_state?.last_reason || '—'}`));
      await load(true);
    } catch { setMsg(t('run.cp.pollFailed', undefined, 'Yoklama başarısız')); } finally { setBusy(false); }
  };
  const num = (v: number, set: (n: number) => void) => (e: React.ChangeEvent<HTMLInputElement>) => { set(Math.max(1, Number(e.target.value) || 1)); setDirty(true); };
  const input = 'w-16 mx-1 text-[11px] font-mono bg-sunk border border-line rounded-md px-1 py-0.5 text-ink';
  const job = sch?.job;
  return (
    <div className="rounded-xl border border-line bg-panel p-4 space-y-2">
      <div className="text-[10px] font-mono font-bold uppercase tracking-wider text-ink3 flex items-center justify-between">
        <span>{t('run.cp.watchdog', undefined, 'Koşu bekçisi (koşu kopunca otomatik ilerletme)')}</span>
        <button onClick={() => load()} className="text-ink3 hover:text-ink" title={t('run.cp.refresh', undefined, 'Yenile')}><RefreshCw className="w-3.5 h-3.5" /></button>
      </div>
      <div className="text-[11px] text-ink3">
        {t('run.cp.watchdogHelp', undefined, 'İlk talimatı siz yazarsınız. Koşu belirli süre ilerlemezse (terk edilirse) bekçi periyodik yoklar ve kaldığı yerden sürdürür. Duraklatılmış uygulamada daha seyrek yoklar; duraklatılmış koşuyu ilerletmez. Zamanlanmış görev kuran yapay zekâ aralığı get_runner_schedule aracından okur.')}
      </div>
      <div className="flex items-center gap-x-4 gap-y-2 flex-wrap text-xs text-ink">
        <label>{t('run.cp.whileRunningEvery', undefined, 'Çalışırken her')}<input type="number" min={1} max={1440} value={active} onChange={num(active, setActive)} className={input} />{t('run.cp.minShort', undefined, 'dk')}</label>
        <label>{t('run.cp.whilePausedEvery', undefined, 'Duraklatılmışken her')}<input type="number" min={1} max={1440} value={paused} onChange={num(paused, setPaused)} className={input} />{t('run.cp.minShort', undefined, 'dk')}</label>
        <label title={t('run.cp.abandonTitle', undefined, 'Terk eşiği = çarpan × çalışırken aralığı')}>{t('run.cp.abandonFactor', undefined, 'Terk çarpanı')}<input type="number" min={1} max={20} value={factor} onChange={num(factor, setFactor)} className={input} />×</label>
        <button onClick={save} disabled={busy || !dirty} className="text-[11px] font-semibold px-3 py-1 rounded-md bg-ink text-bg hover:opacity-90 disabled:opacity-50">{t('common.save', undefined, 'Kaydet')}</button>
        <button onClick={checkNow} disabled={busy} className="text-[11px] px-3 py-1 rounded-md border border-line2 text-ink2 hover:bg-sunk disabled:opacity-50">{t('run.cp.checkNow', undefined, 'Şimdi kontrol et')}</button>
      </div>
      {msg && <div className="text-[11px] text-ink2">{msg}</div>}
      {sch && (
        <div className="text-[11px] text-ink3 border-t border-line pt-2 space-y-0.5">
          <div>{t('run.cp.currentInterval', undefined, 'Şu an geçerli aralık:')} <strong className="text-ink">{sch.interval_minutes} {t('run.cp.minShort', undefined, 'dk')}</strong> ({sch.paused ? t('run.cp.pausedLc', undefined, 'duraklatılmış') : t('run.cp.runningLc', undefined, 'çalışıyor')}) · cron: <code>{sch.suggested_cron}</code> · {t('run.cp.abandonThreshold', undefined, 'terk eşiği')} {sch.abandon_after_min} {t('run.cp.minShort', undefined, 'dk')}</div>
          <div>
            {t('run.cp.watchedJob', undefined, 'İzlenen iş:')} {job ? <><span className="font-mono text-ink2">{job.run_id}</span> · {job.status}{job.paused ? ` ${t('run.cp.pausedParen', undefined, '(duraklatıldı)')}` : ''} · {job.done_steps}/{job.total_steps} {t('run.cp.stepWord', undefined, 'adım')} · {t('run.cp.idle', undefined, 'boşta')} {job.idle_min ?? '—'} {t('run.cp.minShort', undefined, 'dk')}{job.stalled ? <span className="text-warn"> · {t('run.cp.stalled', undefined, 'takılı, bekçi sürdürecek')}</span> : ''}</> : t('run.cp.noJob', undefined, 'yok (koşu yok ya da bitti)')}
          </div>
          <div>{t('run.cp.serverAutoRunner', undefined, 'Sunucu otomatik runner:')} {sch.enabled ? t('run.cp.on', undefined, 'açık') : t('run.cp.offHint', undefined, 'kapalı (aşağıdaki anahtarla açın)')} · {t('run.cp.lastPoll', undefined, 'son yoklama')} {ago(t, sch.last_check, nowMs)} · {sch.last_reason || '—'}{sch.next_check_at ? ` · ${t('run.cp.next', undefined, 'sonraki')} ${new Date(sch.next_check_at).toLocaleTimeString()}` : ''} · {t('run.cp.jobLc', undefined, 'iş:')} {sch.claimable.claimable ? t('run.cp.claimable', { reason: sch.claimable.reason }, `üstlenilebilir (${sch.claimable.reason})`) : sch.claimable.reason}</div>
        </div>
      )}
    </div>
  );
};

const BridgeTab: React.FC<{ claude: ClaudePanelData; nowMs: number }> = ({ claude, nowMs }) => {
  const { t } = useI18n();
  const st = claude.claudeSession.state;
  const [prompt, setPrompt] = useState<string>('');
  const [maxTurns, setMaxTurns] = useState<number>(80);
  const [resumeId, setResumeId] = useState<string>('');
  const [sessions, setSessions] = useState<ClaudeBridgeSessionFile[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [cliInput, setCliInput] = useState('');

  const refresh = async () => {
    try {
      const s = await claude.fetchClaudeStatus();
      if (!prompt && s.bridge.runner_prompt) setPrompt(s.bridge.runner_prompt);
      if (s.bridge.config?.max_turns) setMaxTurns(s.bridge.config.max_turns);
      if (!cliInput && s.bridge.config?.cli) setCliInput(s.bridge.config.cli);
      setSessions(await claude.fetchClaudeSessions());
    } catch (e) {
      setError(e instanceof Error ? e.message : t('run.cp.statusReadErr', undefined, 'Durum okunamadı'));
    }
  };
  useEffect(() => { refresh(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, []);
  useEffect(() => { if (st && !st.running) claude.fetchClaudeSessions().then(setSessions).catch(() => undefined); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [st?.running]);

  const act = async (fn: () => Promise<unknown>) => {
    setBusy(true);
    setError('');
    try {
      await fn();
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : t('run.cp.opFailed', undefined, 'İşlem başarısız'));
    } finally {
      setBusy(false);
    }
  };
  const cli = st?.cli;
  const lastSession = st?.session_id || sessions[0]?.session_id || '';
  return (
    <div className="space-y-4">
      {error && <div className="rounded-lg border border-err/40 bg-errd/40 text-err text-xs px-3 py-2">{error}</div>}
      <WatchdogCard nowMs={nowMs} />
      <RunnerCard claude={claude} nowMs={nowMs} />
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div className="rounded-xl border border-line bg-panel p-4 space-y-2">
          <div className="text-[10px] font-mono font-bold uppercase tracking-wider text-ink3">Claude Code CLI</div>
          {cli ? (
            <div className="text-xs text-ink2 space-y-1">
              <div className="flex items-center gap-2"><span className={`w-2.5 h-2.5 rounded-full ${cli.ok ? 'bg-ok' : 'bg-err'}`} />{cli.ok ? t('run.cp.ready', { v: cli.version || cli.path }, `Hazır: ${cli.version || cli.path}`) : t('run.cp.notInstalled', { err: cli.error }, `Kurulu değil: ${cli.error}`)}</div>
              {!cli.ok && <div className="text-ink3">{cli.install_hint}</div>}
              <div className="flex items-center gap-2">
                <input value={cliInput} onChange={e => setCliInput(e.target.value)} placeholder={t('run.cp.cliPh', undefined, 'claude ya da tam yol')} className="flex-1 text-[11px] font-mono bg-sunk border border-line rounded-md px-2 py-1 text-ink" />
                <button disabled={busy} onClick={() => act(() => claude.updateClaudeSettings({ cli: cliInput }))} className="text-[11px] font-semibold px-2.5 py-1 rounded-md bg-panel2 border border-line text-ink2 hover:text-ink">{t('common.save', undefined, 'Kaydet')}</button>
              </div>
              <div className="text-[10px] text-ink3">{t('run.cp.allowedTools', undefined, 'İzinli araçlar:')} <code className="font-mono">{st?.allowed_tools}</code> {t('run.cp.allowedToolsNote', undefined, '(dosya yazma/komut koşma yok). Üretim senin aboneliğinle, API anahtarı yok.')}</div>
            </div>
          ) : <div className="text-xs text-ink3">{t('run.cp.statusLoading', undefined, 'Durum yükleniyor…')}</div>}
        </div>
        <div className="rounded-xl border border-line bg-panel p-4 space-y-2">
          <div className="text-[10px] font-mono font-bold uppercase tracking-wider text-ink3">{t('run.cp.session', undefined, 'Oturum')}</div>
          {st ? (
            <dl className="text-xs text-ink2 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1">
              <dt className="text-ink3">{t('run.cp.state', undefined, 'Durum')}</dt><dd className={st.running ? 'text-ok font-semibold' : 'text-ink'}>{st.running ? t('run.cp.runningLc', undefined, 'çalışıyor') : (st.finished_at ? t('run.cp.finishedExit', { code: st.exit_code }, `bitti (çıkış ${st.exit_code})`) : t('run.cp.notStarted', undefined, 'başlatılmadı'))}</dd>
              <dt className="text-ink3">{t('run.cp.sessionId', undefined, 'Oturum kimliği')}</dt><dd className="font-mono break-all">{st.session_id || '—'}{st.resume_of ? ` ${t('run.cp.resumedParen', undefined, '(sürdürüldü)')}` : ''}</dd>
              <dt className="text-ink3">{t('run.cp.startedAt', undefined, 'Başladı')}</dt><dd>{st.started_at ? `${hhmmss(st.started_at)} · ${ago(t, st.started_at, nowMs)}` : '—'}</dd>
              <dt className="text-ink3">{t('run.cp.eventsTurns', undefined, 'Olay / tur')}</dt><dd className="font-mono">{st.events} / {st.turns}</dd>
              <dt className="text-ink3">{t('run.cp.lastEvent', undefined, 'Son olay')}</dt><dd className="truncate" title={st.last_event?.text}>{st.last_event ? `${st.last_event.kind}${st.last_event.tool ? ` ${st.last_event.tool}` : ''} · ${hhmmss(st.last_event.ts)}` : '—'}</dd>
              {st.result && <><dt className="text-ink3">{t('run.cp.result', undefined, 'Sonuç')}</dt><dd>{st.result.subtype} · {st.result.num_turns} {t('run.cp.turns', undefined, 'tur')}{st.result.total_cost_usd != null ? ` · ${t('run.cp.costNote', { cost: Number(st.result.total_cost_usd).toFixed(3) }, `ücret kesilmez, abonelik payından düşer · API olsaydı tahmini $${Number(st.result.total_cost_usd).toFixed(3)}`)}` : ''}</dd></>}
              {st.error && <><dt className="text-ink3">{t('run.cp.error', undefined, 'Hata')}</dt><dd className="text-err">{st.error}</dd></>}
            </dl>
          ) : <div className="text-xs text-ink3">—</div>}
          {st?.stderr_tail && <details className="text-[10px] text-ink3"><summary className="cursor-pointer">stderr</summary><pre className="whitespace-pre-wrap">{st.stderr_tail}</pre></details>}
        </div>
      </div>
      <div className="rounded-xl border border-line bg-panel p-4 space-y-2">
        <div className="text-[10px] font-mono font-bold uppercase tracking-wider text-ink3">{t('run.cp.runnerPrompt', undefined, "Runner istemi (sunucu bunu Claude'a verir)")}</div>
        <textarea value={prompt} onChange={e => setPrompt(e.target.value)} rows={6} className="w-full text-[11px] font-mono bg-sunk border border-line rounded-md px-2 py-1.5 text-ink" />
        <div className="flex items-center gap-2 flex-wrap">
          <label className="text-[11px] text-ink3">{t('run.cp.maxTurns', undefined, 'En çok tur')} <input type="number" min={1} max={500} value={maxTurns} onChange={e => setMaxTurns(Number(e.target.value) || 80)} className="w-16 ml-1 text-[11px] font-mono bg-sunk border border-line rounded-md px-1 py-0.5 text-ink" /></label>
          <button disabled={busy || !!st?.running || !cli?.ok} onClick={() => act(() => claude.claudeStart({ prompt, max_turns: maxTurns }))}
                  className="inline-flex items-center gap-1 text-[11px] font-semibold px-3 py-1.5 rounded-md bg-ok text-bg hover:opacity-90 disabled:opacity-40">
            <Play className="w-3.5 h-3.5" /> {t('run.cp.startClaude', undefined, "Claude'u başlat")}
          </button>
          <input value={resumeId} onChange={e => setResumeId(e.target.value)} placeholder={lastSession ? t('run.cp.sessionPh', { id: lastSession.slice(0, 12) }, `oturum: ${lastSession.slice(0, 12)}…`) : t('run.cp.sessionIdPh', undefined, 'oturum kimliği')} className="w-56 text-[11px] font-mono bg-sunk border border-line rounded-md px-2 py-1 text-ink" />
          <button disabled={busy || !!st?.running || !cli?.ok || !(resumeId || lastSession)} onClick={() => act(() => claude.claudeStart({ prompt, resume: resumeId || lastSession, max_turns: maxTurns }))}
                  className="inline-flex items-center gap-1 text-[11px] font-semibold px-3 py-1.5 rounded-md bg-panel2 border border-line text-ink hover:bg-sunk disabled:opacity-40" title={t('run.cp.reconnectTitle', undefined, 'Aynı oturumu --resume ile sürdürür')}>
            <RotateCcw className="w-3.5 h-3.5" /> {t('run.cp.reconnect', undefined, 'Yeniden bağlan')}
          </button>
          <button disabled={busy || !st?.running} onClick={() => act(() => claude.claudeStop())} className="inline-flex items-center gap-1 text-[11px] font-semibold px-3 py-1.5 rounded-md bg-errd text-err border border-err/40 disabled:opacity-40">
            <Square className="w-3.5 h-3.5" /> {t('run.cp.stop', undefined, 'Durdur')}
          </button>
          <button disabled={busy} onClick={() => act(async () => undefined)} className="inline-flex items-center gap-1 text-[11px] px-2 py-1.5 rounded-md text-ink3 hover:text-ink"><RefreshCw className="w-3.5 h-3.5" /></button>
        </div>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-[260px_1fr] gap-4">
        <div className="rounded-xl border border-line bg-panel overflow-hidden">
          <div className="px-3 py-2 border-b border-line text-[10px] font-mono font-bold uppercase tracking-wider text-ink3">{t('run.cp.savedSessions', undefined, 'Kayıtlı oturumlar')}</div>
          <ul className="divide-y divide-line max-h-72 overflow-y-auto">
            {sessions.length === 0 && <li className="p-3 text-[11px] text-ink3 italic">{t('run.cp.noHeadless', undefined, 'Henüz başsız oturum yok.')}</li>}
            {sessions.map(s => (
              <li key={s.session_id} className="px-3 py-1.5 text-[11px] flex items-center gap-2">
                <span className="font-mono truncate flex-1" title={s.session_id}>{s.session_id.slice(0, 14)}…{s.running ? ' ●' : ''}</span>
                <span className="text-ink3 shrink-0">{hhmmss(s.modified_at)}</span>
                <button onClick={() => setResumeId(s.session_id)} className="text-ink3 hover:text-ink shrink-0" title={t('run.cp.pickReconnect', undefined, 'Yeniden bağlanmak için seç')}><RotateCcw className="w-3 h-3" /></button>
              </li>
            ))}
          </ul>
        </div>
        <div className="rounded-xl border border-line bg-panel overflow-hidden">
          <div className="px-3 py-2 border-b border-line text-[10px] font-mono font-bold uppercase tracking-wider text-ink3 flex items-center justify-between">
            <span>{t('run.cp.liveStream', undefined, "Canlı oturum akışı (Claude'un yazdıkları, düşünceleri, araç çağrıları)")}</span>
            <span className="normal-case font-sans font-normal">{t('run.cp.eventsN', { n: claude.claudeSession.events.length }, `${claude.claudeSession.events.length} olay`)}</span>
          </div>
          <ul className="max-h-96 overflow-y-auto">
            {claude.claudeSession.events.length === 0 && <li className="p-4 text-[11px] text-ink3 italic">{t('run.cp.streamEmpty', undefined, 'Oturum başlayınca olaylar burada akar; önceki oturumlar için yukarıdan oturumu seçip "Yeniden bağlan" ya da Oturum aynası.')}</li>}
            {claude.claudeSession.events.map((e, i) => <SessionEventRow key={`${e.ts}-${i}`} e={e} />)}
          </ul>
        </div>
      </div>
    </div>
  );
};

// ---------------------------------------------------------------------------
// Sekme: Etkileşim günlüğü (iki yönlü, tam)
// ---------------------------------------------------------------------------
const LogRow: React.FC<{ e: ClaudeLogEntry; fetchFull: (id: string) => Promise<ClaudeLogEntry> }> = ({ e, fetchFull }) => {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  const [full, setFull] = useState<ClaudeLogEntry | null>(null);
  const [loading, setLoading] = useState(false);
  const dir = DIRECTION_META[e.direction] || DIRECTION_META.server;
  const toggle = async () => {
    const next = !open;
    setOpen(next);
    if (next && !full && (e.args_truncated || e.result_truncated || e.text_truncated)) {
      setLoading(true);
      try {
        setFull(await fetchFull(e.id));
      } catch {
        /* tam gövde okunamadı; kırpılmış hâli gösterilir */
      } finally {
        setLoading(false);
      }
    }
  };
  const shown = full || e;
  const title = `${toolLabel(t, e.tool)}${e.order != null ? ` · ${t('run.cp.stepNo', { n: e.order }, `adım #${e.order}`)}` : ''}${e.agent_id ? ` · ${e.agent_id}` : ''}${e.kind ? ` · ${e.kind}` : ''}`;
  return (
    <li className="border-b border-line last:border-0">
      <button onClick={toggle} className="w-full text-left px-3 py-1.5 text-[11px] flex items-center gap-2 hover:bg-sunk/60">
        <span className="font-mono text-ink3 shrink-0 w-[62px]">{hhmmss(e.ts)}</span>
        <span className={`shrink-0 text-[10px] font-mono px-1.5 py-0.5 rounded border ${dir.cls}`}>{dirLabel(t, e.direction)}</span>
        <span className="font-mono font-semibold text-ink shrink-0 w-[170px] truncate" title={e.tool}>{e.tool}</span>
        <span className={`font-mono shrink-0 w-[120px] truncate ${resultCls(e.status)}`}>{e.status || '—'}{(e.count || 1) > 1 ? ` ×${e.count}` : ''}</span>
        <span className="text-ink2 min-w-0 truncate flex-1" title={title}>{title}{e.duration_ms != null ? ` · ${(e.duration_ms / 1000).toFixed(1)} ${t('run.cp.secShort', undefined, 'sn')}` : ''}</span>
        {e.run_id && <span className="font-mono text-ink3 shrink-0">{e.run_id.slice(-6)}</span>}
      </button>
      {open && (
        <div className="px-3 pb-3 space-y-2 bg-sunk/40">
          {loading && <div className="text-[11px] text-ink3">{t('run.cp.loadingFull', undefined, 'tam gövde yükleniyor…')}</div>}
          {shown.text && <div><div className="text-[10px] font-mono text-ink3 uppercase">{t('run.cp.text', undefined, 'metin')}</div><pre className="whitespace-pre-wrap text-[11px] font-sans text-ink max-h-64 overflow-auto bg-panel border border-line rounded-md p-2">{shown.text}</pre></div>}
          {shown.args !== undefined && shown.args !== null && <div><div className="text-[10px] font-mono text-ink3 uppercase">{t('run.cp.args', undefined, 'argümanlar')}</div><pre className="whitespace-pre-wrap text-[11px] font-mono text-ink2 max-h-72 overflow-auto bg-panel border border-line rounded-md p-2">{pretty(shown.args)}</pre></div>}
          {shown.result !== undefined && shown.result !== null && <div><div className="text-[10px] font-mono text-ink3 uppercase">{t('run.cp.resultLc', undefined, 'sonuç')}</div><pre className="whitespace-pre-wrap text-[11px] font-mono text-ink2 max-h-96 overflow-auto bg-panel border border-line rounded-md p-2">{pretty(shown.result)}</pre></div>}
          {shown.error && <div className="text-err text-[11px]">{shown.error}</div>}
          <div className="text-[10px] text-ink3 font-mono">{e.id}{e.client ? ` · ${t('run.cp.clientLc', undefined, 'istemci')} ${e.client}` : ''}{e.session_id ? ` · ${t('run.cp.sessionLc', undefined, 'oturum')} ${e.session_id}` : ''}</div>
        </div>
      )}
    </li>
  );
};

const LogTab: React.FC<{ claude: ClaudePanelData }> = ({ claude }) => {
  const { t } = useI18n();
  const [direction, setDirection] = useState<ClaudeLogDirection | ''>('');
  const [tool, setTool] = useState('');
  const [runId, setRunId] = useState('');
  const [q, setQ] = useState('');
  const [page, setPage] = useState<{ total: number; entries: ClaudeLogEntry[]; tools: string[]; runs: string[] } | null>(null);
  const [error, setError] = useState('');
  const filtered = !!(direction || tool || runId || q);
  const load = async () => {
    setError('');
    try {
      setPage(await claude.fetchClaudeLog({ direction, tool, run_id: runId, q, limit: 300 }));
    } catch (e) {
      setError(e instanceof Error ? e.message : t('run.cp.logReadErr', undefined, 'Günlük okunamadı'));
    }
  };
  useEffect(() => { load(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [direction, tool, runId]);
  const entries = filtered ? (page?.entries || []) : claude.claudeLog;
  const tools = useMemo(() => Array.from(new Set([...(page?.tools || []), ...claude.claudeLog.map(e => e.tool)])).sort(), [page, claude.claudeLog]);
  const runs = useMemo(() => Array.from(new Set([...(page?.runs || []), ...claude.claudeLog.map(e => e.run_id).filter((x): x is string => !!x)])).sort(), [page, claude.claudeLog]);
  const exportHref = api(`/api/claude/log/export${runId ? `?run_id=${encodeURIComponent(runId)}` : ''}`);
  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2 flex-wrap text-[11px]">
        <select value={direction} onChange={e => setDirection(e.target.value as ClaudeLogDirection | '')} className="bg-sunk border border-line rounded-md px-2 py-1 text-ink">
          <option value="">{t('run.cp.allDirections', undefined, 'Tüm yönler')}</option>
          {Object.keys(DIRECTION_META).map(k => <option key={k} value={k}>{dirLabel(t, k)}</option>)}
        </select>
        <select value={tool} onChange={e => setTool(e.target.value)} className="bg-sunk border border-line rounded-md px-2 py-1 text-ink font-mono">
          <option value="">{t('run.cp.allTools', undefined, 'Tüm araçlar')}</option>
          {tools.map(tn => <option key={tn} value={tn}>{tn}</option>)}
        </select>
        <select value={runId} onChange={e => setRunId(e.target.value)} className="bg-sunk border border-line rounded-md px-2 py-1 text-ink font-mono">
          <option value="">{t('run.cp.allRuns', undefined, 'Tüm koşular')}</option>
          {runs.map(r => <option key={r} value={r}>{r}</option>)}
        </select>
        <div className="flex items-center gap-1 bg-sunk border border-line rounded-md px-2 py-1">
          <Search className="w-3.5 h-3.5 text-ink3" />
          <input value={q} onChange={e => setQ(e.target.value)} onKeyDown={e => { if (e.key === 'Enter') load(); }} placeholder={t('run.cp.searchPh', undefined, 'metinde ara (Enter)')} className="bg-transparent text-ink outline-none w-44" />
        </div>
        <button onClick={load} className="inline-flex items-center gap-1 px-2 py-1 rounded-md border border-line text-ink2 hover:text-ink"><RefreshCw className="w-3.5 h-3.5" /> {t('run.cp.refresh', undefined, 'Yenile')}</button>
        <a href={exportHref} target="_blank" rel="noopener" className="inline-flex items-center gap-1 px-2 py-1 rounded-md border border-line text-ink2 hover:text-ink"><Download className="w-3.5 h-3.5" /> {t('run.cp.exportMd', undefined, 'Markdown dışa aktar')}</a>
        <span className="text-ink3 ml-auto">{filtered ? t('run.cp.matchesN', { n: page?.total ?? 0 }, `${page?.total ?? 0} eşleşme`) : t('run.cp.recordsLive', { n: claude.claudeLog.length }, `${claude.claudeLog.length} kayıt (canlı)`)}</span>
      </div>
      {error && <div className="rounded-lg border border-err/40 bg-errd/40 text-err text-xs px-3 py-2">{error}</div>}
      <div className="rounded-xl border border-line bg-panel overflow-hidden">
        {entries.length === 0 ? (
          <div className="p-6 text-center text-xs text-ink3 italic">{t('run.cp.noLog', undefined, 'Kayıt yok. Claude bir araç çağırınca ya da sen panodan bir şey onaylayınca burada iki yönlü, tam içerikle görünür.')}</div>
        ) : (
          <ul className="max-h-[32rem] overflow-y-auto">{entries.map(e => <LogRow key={e.id} e={e} fetchFull={claude.fetchClaudeLogEntry} />)}</ul>
        )}
      </div>
    </div>
  );
};

// ---------------------------------------------------------------------------
// Sekme: Oturum aynası (Claude Code transkriptleri)
// ---------------------------------------------------------------------------
const MirrorTab: React.FC<{ claude: ClaudePanelData }> = ({ claude }) => {
  const { t } = useI18n();
  const [sessions, setSessions] = useState<TranscriptSession[]>([]);
  const [watching, setWatching] = useState<string[]>([]);
  const [selected, setSelected] = useState<TranscriptSession | null>(null);
  const [events, setEvents] = useState<TranscriptEvent[]>([]);
  const [note, setNote] = useState<string | null>(null);
  const [error, setError] = useState('');
  const [kindFilter, setKindFilter] = useState<string>('');
  const load = async () => {
    setError('');
    try {
      const r = await claude.fetchTranscripts();
      setSessions(r.sessions);
      setWatching(r.watching?.watching || []);
    } catch (e) {
      setError(e instanceof Error ? e.message : t('run.cp.transcriptsReadErr', undefined, 'Transkriptler okunamadı'));
    }
  };
  useEffect(() => { load(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, []);
  const show = async (s: TranscriptSession) => {
    setSelected(s);
    setError('');
    try {
      const r = await claude.fetchTranscriptEvents(s.session_id, 400);
      setEvents(r.events);
      setNote(r.thinking?.note || null);
    } catch (e) {
      setError(e instanceof Error ? e.message : t('run.cp.transcriptReadErr', undefined, 'Transkript okunamadı'));
    }
  };
  const watch = async (s: TranscriptSession) => {
    try {
      const r = await claude.watchTranscript(s.session_id);
      setWatching(r.watching);
    } catch (e) {
      setError(e instanceof Error ? e.message : t('run.cp.watchErr', undefined, 'İzleme başlatılamadı'));
    }
  };
  const live = claude.transcriptEvents.filter(e => !selected || e.file === selected.file || e.session_id === selected.session_id);
  const merged = useMemo(() => {
    const seen = new Set(events.map(e => e.uuid).filter(Boolean));
    return [...events, ...live.filter(e => !e.uuid || !seen.has(e.uuid))].filter(e => !kindFilter || e.kind === kindFilter);
  }, [events, live, kindFilter]);
  return (
    <div className="space-y-3">
      <div className="text-xs text-ink2">
        {t('run.cp.mirrorHelpA', undefined, 'Claude Code / Code sekmesi oturumları diskte')} <code className="font-mono">~/.claude/projects</code> {t('run.cp.mirrorHelpB', undefined, "altında durur; burada Claude'un yazdıkları, düşünce blokları ve tüm araç çağrıları okunur. Düşünce metni istemci tarafından saklanmamışsa bu açıkça söylenir. Claude Desktop Chat sekmesi oturumlarının transkripti yoktur.")}
      </div>
      {error && <div className="rounded-lg border border-err/40 bg-errd/40 text-err text-xs px-3 py-2">{error}</div>}
      <div className="grid grid-cols-1 md:grid-cols-[320px_1fr] gap-4">
        <div className="rounded-xl border border-line bg-panel overflow-hidden">
          <div className="px-3 py-2 border-b border-line text-[10px] font-mono font-bold uppercase tracking-wider text-ink3 flex items-center justify-between">
            <span>{t('run.cp.sessions', undefined, 'Oturumlar')}</span>
            <button onClick={load} className="text-ink3 hover:text-ink"><RefreshCw className="w-3.5 h-3.5" /></button>
          </div>
          <ul className="divide-y divide-line max-h-[28rem] overflow-y-auto">
            {sessions.length === 0 && <li className="p-3 text-[11px] text-ink3 italic">{t('run.cp.noTranscripts', undefined, 'Transkript bulunamadı (Claude Code bu klasörde hiç çalışmadı ya da transkript dizini farklı: ayar claude.transcripts_dir).')}</li>}
            {sessions.map(s => (
              <li key={s.file} className={`px-3 py-2 text-[11px] space-y-0.5 ${selected?.file === s.file ? 'bg-acd/40' : ''}`}>
                <div className="flex items-center gap-2">
                  <span className="font-semibold text-ink truncate flex-1" title={s.first_prompt || s.session_id}>{s.title || s.first_prompt || s.session_id}</span>
                  <span className="text-[10px] font-mono px-1 rounded bg-sunk border border-line text-ink3">{s.scope}</span>
                </div>
                <div className="text-ink3 font-mono truncate">{s.session_id.slice(0, 8)}… · {hhmmss(s.modified_at)} · {(s.size / 1024).toFixed(0)} KB{s.entrypoint ? ` · ${s.entrypoint}` : ''}</div>
                <div className="flex items-center gap-2">
                  <button onClick={() => show(s)} className="inline-flex items-center gap-1 px-2 py-0.5 rounded border border-line text-ink2 hover:text-ink"><FileText className="w-3 h-3" /> {t('run.cp.show', undefined, 'Göster')}</button>
                  <button onClick={() => watch(s)} disabled={watching.includes(s.file)} className="inline-flex items-center gap-1 px-2 py-0.5 rounded border border-line text-ink2 hover:text-ink disabled:opacity-40"><Eye className="w-3 h-3" /> {watching.includes(s.file) ? t('run.cp.watching', undefined, 'İzleniyor') : t('run.cp.watchLive', undefined, 'Canlı izle')}</button>
                </div>
              </li>
            ))}
          </ul>
        </div>
        <div className="rounded-xl border border-line bg-panel overflow-hidden">
          <div className="px-3 py-2 border-b border-line text-[10px] font-mono font-bold uppercase tracking-wider text-ink3 flex items-center gap-2">
            <span className="flex-1 truncate">{selected ? (selected.title || selected.session_id) : t('run.cp.pickSession', undefined, 'Bir oturum seçin')}</span>
            <select value={kindFilter} onChange={e => setKindFilter(e.target.value)} className="normal-case font-sans font-normal bg-sunk border border-line rounded-md px-1 py-0.5 text-ink text-[11px]">
              <option value="">{t('run.cp.all', undefined, 'tümü')}</option>
              {Object.keys(EVENT_KIND_META).filter(k => k !== 'raw' && k !== 'system' && k !== 'result').map(k => <option key={k} value={k}>{kindLabel(t, k)}</option>)}
            </select>
            <span className="normal-case font-sans font-normal">{t('run.cp.eventsN', { n: merged.length }, `${merged.length} olay`)}</span>
          </div>
          {note && <div className="px-3 py-1.5 text-[11px] text-warn bg-warnd/40 border-b border-line">{note}</div>}
          <ul className="max-h-[28rem] overflow-y-auto">
            {merged.length === 0 && <li className="p-4 text-[11px] text-ink3 italic">{t('run.cp.noEvents', undefined, 'Olay yok.')}</li>}
            {merged.map((e, i) => <SessionEventRow key={`${e.uuid || e.ts}-${i}`} e={e} />)}
          </ul>
        </div>
      </div>
    </div>
  );
};

// ---------------------------------------------------------------------------
// Panel
// ---------------------------------------------------------------------------
export const ClaudePanel: React.FC<ClaudePanelProps> = ({ activity, projectName, onOpenNewTab, claude }) => {
  const { t } = useI18n();
  const [nowMs, setNowMs] = useState(Date.now());
  const [tab, setTab] = useState<Tab>('durum');
  useEffect(() => {
    const iv = setInterval(() => setNowMs(Date.now()), 1000);
    return () => clearInterval(iv);
  }, []);

  if (!activity) {
    return <div className="p-8 text-center text-ink3 text-sm italic">{t('run.cp.loadingInfo', undefined, 'Claude iletişim bilgisi yükleniyor…')}</div>;
  }
  const { turn } = activity;
  const style = TURN_STYLE[turn.who] || TURN_STYLE.idle;
  const bridgeRunning = !!claude?.claudeSession.state?.running;
  const tabs: { id: Tab; label: string; badge?: string }[] = [
    { id: 'durum', label: t('run.cp.tab.durum', undefined, 'Durum') },
    { id: 'baslat', label: t('run.cp.tab.baslat', undefined, 'Başlat & Bağlan'), badge: bridgeRunning ? '●' : undefined },
    { id: 'gunluk', label: t('run.cp.tab.gunluk', undefined, 'Etkileşim günlüğü'), badge: claude ? String(claude.claudeLog.length) : undefined },
    { id: 'oturum', label: t('run.cp.tab.oturum', undefined, 'Oturum aynası'), badge: claude && claude.transcriptEvents.length > 0 ? String(claude.transcriptEvents.length) : undefined },
  ];

  return (
    <div className="space-y-4">
      <div className={`rounded-2xl border-2 p-4 flex items-start gap-3 ${style.cls}`}>
        <div className="shrink-0 mt-0.5">{style.icon}</div>
        <div className="min-w-0 flex-1">
          <div className="text-[10px] font-mono font-bold tracking-wider">{t(`run.cp.turn.${turn.who in TURN_STYLE ? turn.who : 'idle'}`, undefined, style.badge)}</div>
          <div className="text-base font-bold text-ink">{turn.label}</div>
          {turn.title && <div className="text-xs text-ink2 truncate" title={turn.title}>{turn.title}</div>}
          {turn.detail && <div className="text-xs text-ink2 mt-1">{turn.detail}</div>}
          {turn.who === 'claude' && turn.since && (
            <div className="text-[11px] font-mono text-ink3 mt-1">{t('run.cp.stepStarted', undefined, 'adım başladı:')} {ago(t, turn.since, nowMs)}</div>
          )}
        </div>
        {onOpenNewTab && (
          <button
            onClick={onOpenNewTab}
            className="shrink-0 inline-flex items-center gap-1 text-[11px] font-semibold px-2.5 py-1 rounded-md bg-panel border border-line text-ink2 hover:text-ink transition"
            title={t('run.cp.openTabTitle', undefined, 'Bu görünümü ayrı bir tarayıcı sekmesinde aç (canlı güncellenir)')}
          >
            <ExternalLink className="w-3.5 h-3.5" /> {t('run.cp.openTab', undefined, 'Ayrı sekmede aç')}
          </button>
        )}
      </div>

      <div className="flex items-center gap-1 border-b border-line text-[11px]">
        {tabs.map(tb => (
          <button key={tb.id} onClick={() => setTab(tb.id)} className={`px-3 py-1.5 -mb-px border-b-2 font-semibold transition ${tab === tb.id ? 'border-ac text-ink' : 'border-transparent text-ink3 hover:text-ink'}`}>
            {tb.label}{tb.badge ? <span className="ml-1 text-[10px] font-mono text-ink3">{tb.badge}</span> : null}
          </button>
        ))}
      </div>

      {tab === 'durum' && <StatusTab activity={activity} projectName={projectName} nowMs={nowMs} />}
      {tab === 'baslat' && (claude ? <BridgeTab claude={claude} nowMs={nowMs} /> : <div className="text-xs text-ink3">{t('run.cp.noBridge', undefined, 'Köprü verisi yok.')}</div>)}
      {tab === 'gunluk' && (claude ? <LogTab claude={claude} /> : <div className="text-xs text-ink3">{t('run.cp.noLogData', undefined, 'Günlük verisi yok.')}</div>)}
      {tab === 'oturum' && (claude ? <MirrorTab claude={claude} /> : <div className="text-xs text-ink3">{t('run.cp.noTranscriptData', undefined, 'Transkript verisi yok.')}</div>)}
    </div>
  );
};

interface ClaudeModalProps {
  isOpen: boolean;
  onClose: () => void;
  activity: McpActivity | null;
  projectName?: string;
  claude?: ClaudePanelData;
}

export const ClaudeModal: React.FC<ClaudeModalProps> = ({ isOpen, onClose, activity, projectName, claude }) => {
  const { t } = useI18n();
  useEffect(() => {
    if (!isOpen) return undefined;
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [isOpen, onClose]);

  if (!isOpen) return null;
  return createPortal(
    <div className="fixed inset-0 z-[100] bg-black/60 backdrop-blur-sm flex items-center justify-center p-4 sm:p-8" onClick={onClose} role="dialog" aria-modal="true" aria-label={t('run.cp.modalTitle', undefined, 'Claude iletişimi')}>
      <div className="w-full max-w-5xl max-h-[92vh] bg-sunk border border-line2/80 rounded-2xl shadow-2xl flex flex-col overflow-hidden" onClick={(e) => e.stopPropagation()}>
        <div className="px-5 py-3 bg-panel2 border-b border-line flex items-center justify-between shrink-0">
          <div className="text-sm font-bold text-ink flex items-center gap-2"><Plug className="w-4 h-4 text-ac" /> {t('run.cp.modalTitle', undefined, 'Claude iletişimi')}</div>
          <button onClick={onClose} aria-label={t('common.close', undefined, 'Kapat')} className="p-1.5 rounded-lg text-ink2 hover:text-ink hover:bg-panel transition"><X className="w-4 h-4" /></button>
        </div>
        <div className="p-5 overflow-y-auto">
          <ClaudePanel activity={activity} projectName={projectName} claude={claude} onOpenNewTab={() => window.open('/#claude', '_blank', 'noopener')} />
        </div>
      </div>
    </div>,
    document.body,
  );
};
