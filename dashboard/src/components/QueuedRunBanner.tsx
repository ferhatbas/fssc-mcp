import React, { useEffect, useState } from 'react';
import { createPortal } from 'react-dom';
import { Copy, Check, XCircle, Cpu, Clock, Activity, PauseCircle, CheckCircle2, AlertTriangle, ChevronDown, ChevronUp, BrainCircuit, FileCode2, Pause, Play, GitCommitHorizontal, Wrench, ListTodo, FlaskConical, MessageSquarePlus, Send, RotateCcw } from 'lucide-react';
import { PipelineRun, McpClientInfo, LiveThinking, StepRecord } from '../types/telemetry';
import { useI18n } from '../i18n';

type TFn = (key: string, params?: Record<string, string | number>, fallback?: string) => string;

/** Adım türü rozeti: backlog görevi / düzeltme turu (fazlar rozetsiz) */
const KindBadge: React.FC<{ step: StepRecord }> = ({ step }) => {
  const { t } = useI18n();
  if (step.kind === 'fix') {
    return <span className="inline-flex items-center gap-0.5 text-[9px] font-mono px-1 rounded bg-warnd text-warn border border-warn/40" title={t('run.qb.fixTitle', undefined, 'Doğrulama başarısız olduğu için açılan düzeltme turu')}><Wrench className="w-2.5 h-2.5" />{t('run.qb.fix', undefined, 'düzeltme')} {step.fix_round}</span>;
  }
  if (step.kind === 'task') {
    return <span className="inline-flex items-center gap-0.5 text-[9px] font-mono px-1 rounded bg-acd text-ac border border-ac/40" title={t('run.qb.taskTitle', undefined, "Mimarın backlog'undan gelen geliştirme görevi")}><ListTodo className="w-2.5 h-2.5" />{t('run.qb.task', undefined, 'görev')}</span>;
  }
  if ((step.round || 1) > 1) {
    return <span className="text-[9px] font-mono px-1 rounded bg-sunk text-ink3 border border-line" title={t('run.qb.roundTitle', undefined, 'PO iyileştirme turu sonrası yeniden koşuyor')}>{t('run.qb.round', undefined, 'tur')} {step.round}</span>;
  }
  return null;
};

/** Doğrulama (test/build) ve commit rozetleri */
const VerifyBadge: React.FC<{ step: StepRecord }> = ({ step }) => {
  const { t } = useI18n();
  const v = step.verification;
  return (
    <>
      {v && (
        <span
          className={`inline-flex items-center gap-0.5 text-[9px] font-mono px-1 rounded border ${v.status === 'PASSED' ? 'bg-okd text-ok border-ok/40' : v.status === 'FAILED' ? 'bg-errd text-err border-err/40' : 'bg-sunk text-ink3 border-line'}`}
          title={v.summary}
        >
          <FlaskConical className="w-2.5 h-2.5" />{v.status === 'PASSED' ? 'test ✓' : v.status === 'FAILED' ? `${v.failed_step || 'test'} ✗` : 'test −'}
        </span>
      )}
      {step.commit && (
        <span className="inline-flex items-center gap-0.5 text-[9px] font-mono px-1 rounded bg-sunk text-ink2 border border-line" title={t('run.qb.commitTitle', undefined, 'SCM ajanı commit attı')}>
          <GitCommitHorizontal className="w-2.5 h-2.5 text-ac" />{step.commit}
        </span>
      )}
    </>
  );
};

interface QueuedRunBannerProps {
  run: PipelineRun;
  projectName?: string;
  connectedClients: McpClientInfo[];
  onCancel: (runId: string) => Promise<any>;
  onPause?: (runId: string) => Promise<any>;
  onResume?: (runId: string) => Promise<any>;
  /** Terk edilmiş koşu (sunucu yeniden başladı / istemci koptu): kaldığı adımdan sürdür ya da baştan başlat */
  onResumeAbandoned?: (runId: string) => Promise<any>;
  onRestartFresh?: (runId: string, confirmName: string) => Promise<any>;
  /** Yönetici müdahalesi: not bir sonraki adımın bağlamına girer; urgent koşuyu duraklatır */
  onSendNote?: (runId: string, text: string, urgent: boolean) => Promise<any>;
  /** İstemcinin son report_thinking metni (ayrıntı panelinde gösterilir) */
  liveThinking?: LiveThinking | null;
}

const STEP_STATUS_CLS: Record<string, string> = {
  PENDING: 'bg-sunk text-ink3 border-line',
  ACTIVE: 'bg-okd text-ok border-ok/40',
  WAITING_APPROVAL: 'bg-infod text-info border-info/40',
  DONE: 'bg-okd text-ok border-ok/30',
  REJECTED: 'bg-warnd text-warn border-warn/40',
  FAILED: 'bg-errd text-err border-err/40',
  SKIPPED: 'bg-sunk text-ink3 border-line',
};

const hhmm = (iso?: string | null) => (iso ? new Date(iso).toLocaleTimeString('tr-TR', { hour: '2-digit', minute: '2-digit', second: '2-digit' }) : '—');
const elapsed = (t: TFn, from?: string | null, to?: string | null) => {
  if (!from) return '';
  const ms = (to ? new Date(to).getTime() : Date.now()) - new Date(from).getTime();
  const sec = Math.max(0, Math.round(ms / 1000));
  return sec < 60 ? t('run.qb.sec', { s: sec }, `${sec} sn`) : t('run.qb.minSec', { m: Math.floor(sec / 60), s: sec % 60 }, `${Math.floor(sec / 60)} dk ${sec % 60} sn`);
};

// label = Türkçe yedek; görünen metin run.qb.status.<KOD>
const STATUS_META: Record<string, { label: string; cls: string; icon: React.ReactNode }> = {
  QUEUED: { label: 'KUYRUKTA — yapay zekâ istemcisi bekleniyor', cls: 'bg-warnd text-warn border-warn/40', icon: <Clock className="w-3.5 h-3.5" /> },
  ACTIVE: { label: 'AKTİF — istemci adımları üretiyor', cls: 'bg-okd text-ok border-ok/40', icon: <Activity className="w-3.5 h-3.5 animate-pulse" /> },
  WAITING_APPROVAL: { label: 'ONAY BEKLİYOR', cls: 'bg-infod text-info border-info/40', icon: <PauseCircle className="w-3.5 h-3.5" /> },
  COMPLETED: { label: 'TAMAMLANDI', cls: 'bg-okd text-ok border-ok/40', icon: <CheckCircle2 className="w-3.5 h-3.5" /> },
  ABANDONED: { label: 'TERK EDİLDİ — kaldığı adımdan sürdürülebilir', cls: 'bg-errd text-err border-err/40', icon: <AlertTriangle className="w-3.5 h-3.5" /> },
  CANCELLED: { label: 'İPTAL EDİLDİ', cls: 'bg-sunk text-ink3 border-line', icon: <XCircle className="w-3.5 h-3.5" /> },
  FAILED: { label: 'HATA', cls: 'bg-errd text-err border-err/40', icon: <AlertTriangle className="w-3.5 h-3.5" /> },
  PAUSED: { label: 'DURAKLATILDI — devam edilince sürer', cls: 'bg-warnd text-warn border-warn/40', icon: <Pause className="w-3.5 h-3.5" /> },
};

function stepsLabel(run: PipelineRun): string {
  const orders = run.steps.map(s => s.order);
  if (orders.length === 0) return '';
  const min = Math.min(...orders);
  const max = Math.max(...orders);
  const contiguous = orders.length === max - min + 1;
  return contiguous ? (min === max ? `${min}` : `${min}-${max}`) : orders.join(',');
}

export const QueuedRunBanner: React.FC<QueuedRunBannerProps> = ({ run, projectName, connectedClients, onCancel, onPause, onResume, onResumeAbandoned, onRestartFresh, onSendNote, liveThinking }) => {
  const { t } = useI18n();
  const [busy, setBusy] = useState(false);
  const [noteOpen, setNoteOpen] = useState(false);
  const [noteText, setNoteText] = useState('');
  const [noteUrgent, setNoteUrgent] = useState(false);
  const [noteError, setNoteError] = useState('');
  const [noteSending, setNoteSending] = useState(false);
  const notes = (run.manager_notes || []).slice(-5).reverse();

  const submitNote = async () => {
    const text = noteText.trim();
    if (!text || !onSendNote) return;
    setNoteSending(true);
    setNoteError('');
    try {
      await onSendNote(run.run_id, text, noteUrgent);
      setNoteText('');
      setNoteUrgent(false);
    } catch (e) {
      setNoteError(e instanceof Error ? e.message : t('run.qb.noteFailed', undefined, 'Not gönderilemedi'));
    } finally {
      setNoteSending(false);
    }
  };
  const [copied, setCopied] = useState(false);
  const [open, setOpen] = useState(false); // ayrıntı paneli
  const idx = run.progress.current_index;
  const current = (typeof idx === 'number' && run.steps[idx])
    || run.steps.find(s => s.status === 'ACTIVE' || s.status === 'WAITING_APPROVAL')
    || run.steps.find(s => s.order === run.progress.current_order)
    || null;
  const dynamicNote = [
    run.progress.tasks ? t('run.qb.tasksN', { n: run.progress.tasks }, `${run.progress.tasks} görev`) : '',
    run.progress.fixes ? t('run.qb.fixesN', { n: run.progress.fixes }, `${run.progress.fixes} düzeltme`) : '',
    run.uat_round ? t('run.qb.uatRound', { n: run.uat_round }, `UAT turu ${run.uat_round}`) : '',
  ].filter(Boolean).join(' · ');
  const thinking = liveThinking && liveThinking.run_id === run.run_id ? liveThinking : null;
  const [cancelling, setCancelling] = useState(false);
  const [armed, setArmed] = useState(false); // iki tıkla iptal (native confirm yerine)
  // "Baştan başlat" iki aşamalıdır (proje silmedeki gibi): 1) ne kaybedileceği, 2) proje adını yazarak onay
  const [restartStep, setRestartStep] = useState<0 | 1 | 2>(0);
  const [restartName, setRestartName] = useState('');
  const [resumeError, setResumeError] = useState('');

  // Sunucu iş itemez (çekme modeli): koşu AKTİF olsa da sıradaki adımı çeken bir Claude oturumu yoksa ilerlemez
  const [nowMs, setNowMs] = useState(() => Date.now());
  useEffect(() => {
    const t = setInterval(() => setNowMs(Date.now()), 15000);
    return () => clearInterval(t);
  }, []);
  const idleSec = run.last_seen ? Math.max(0, Math.round((nowMs - new Date(run.last_seen).getTime()) / 1000)) : 0;
  const waitingClient = run.engine === 'mcp_client' && run.status === 'ACTIVE' && !run.paused && !run.is_terminal && idleSec > 90
    && (!current || current.status === 'PENDING');
  const meta = (waitingClient
    ? { label: t('run.qb.waitingClient', { ago: idleSec < 3600 ? t('run.qb.agoMin', { n: Math.round(idleSec / 60) }, `${Math.round(idleSec / 60)} dk`) : t('run.qb.agoHour', { n: Math.round(idleSec / 3600) }, `${Math.round(idleSec / 3600)} sa`) }, `CLAUDE BEKLENİYOR — adımı çeken oturum yok (son temas ${idleSec < 3600 ? `${Math.round(idleSec / 60)} dk` : `${Math.round(idleSec / 3600)} sa`} önce)`),
        cls: 'bg-warnd text-warn border-warn/40', icon: <Clock className="w-3.5 h-3.5" /> }
    : (() => {
        const code = run.paused && !run.is_terminal ? 'PAUSED' : run.status;
        const m = STATUS_META[code];
        return m ? { ...m, label: t(`run.qb.status.${code}`, undefined, m.label) } : undefined;
      })()) || { ...STATUS_META.QUEUED, label: t('run.qb.status.QUEUED', undefined, STATUS_META.QUEUED.label) };
  const isMcp = run.engine === 'mcp_client';
  const prompt = (run.status === 'ABANDONED' || waitingClient)
    ? t('run.qb.promptResume', { p: projectName || run.project_id, id: run.run_id }, `${projectName || run.project_id} projesi için pipeline'ı çalıştır (kaldığı yerden: ${run.run_id})`)
    : t('run.qb.promptSteps', { p: projectName || run.project_id, steps: stepsLabel(run) }, `${projectName || run.project_id} projesi için pipeline'ı çalıştır (adımlar: ${stepsLabel(run)})`);
  const lastClient = connectedClients
    .slice()
    .sort((a, b) => (a.last_seen < b.last_seen ? 1 : -1))[0];

  const copyPrompt = async () => {
    try {
      await navigator.clipboard.writeText(prompt);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard engellenmiş olabilir */
    }
  };

  const handleResumeAbandoned = async () => {
    if (!onResumeAbandoned) return;
    setBusy(true);
    setResumeError('');
    try {
      await onResumeAbandoned(run.run_id);
    } catch (e) {
      setResumeError(e instanceof Error ? e.message : t('run.qb.resumeFailed', undefined, 'Koşu sürdürülemedi'));
    } finally {
      setBusy(false);
    }
  };

  const doneSteps = run.steps.filter(s => s.status === 'DONE').length;
  const handleRestartFresh = async () => {
    if (!onRestartFresh) return;
    setBusy(true);
    setResumeError('');
    try {
      await onRestartFresh(run.run_id, restartName.trim());
      setRestartStep(0);
      setRestartName('');
    } catch (e) {
      setResumeError(e instanceof Error ? e.message : t('run.qb.restartFailed', undefined, 'Baştan başlatılamadı'));
    } finally {
      setBusy(false);
    }
  };

  const handleCancel = async () => {
    if (!armed) {
      setArmed(true);
      setTimeout(() => setArmed(false), 4000);
      return;
    }
    setArmed(false);
    setCancelling(true);
    try {
      await onCancel(run.run_id);
    } finally {
      setCancelling(false);
    }
  };

  // Eylem düğmeleri üst çubuktaki sayaçların altındaki yuvaya (#run-actions-slot) taşınır; yuva yoksa satırın sonunda kalır
  const [slot, setSlot] = useState<HTMLElement | null>(null);
  useEffect(() => { setSlot(document.getElementById('run-actions-slot')); }, []);
  const actionButtons = (
    <>
      {!run.is_terminal && onSendNote && (
        <button
          onClick={() => setNoteOpen(o => !o)}
          className={`inline-flex items-center gap-1 whitespace-nowrap shrink-0 text-[11px] font-semibold px-2.5 py-1 rounded-md border transition ${noteOpen ? 'bg-acd border-ac/40 text-ac' : 'bg-panel2 border-line text-ink2 hover:text-ink hover:border-line2'}`}
          title={t('run.qb.noteBtnTitle', undefined, 'Çalışan ekibe not bırak: bir sonraki adımın bağlamına girer')}
        >
          <MessageSquarePlus className="w-3.5 h-3.5" />
          {t('run.qb.intervene', undefined, 'Müdahale')}{(run.manager_notes || []).some(n => n.delivered_step == null) ? ' •' : ''}
        </button>
      )}

      {!run.is_terminal && (onPause || onResume) && (
        <button
          onClick={async () => { setBusy(true); try { await (run.paused ? onResume?.(run.run_id) : onPause?.(run.run_id)); } finally { setBusy(false); } }}
          disabled={busy}
          className={`inline-flex items-center gap-1 whitespace-nowrap shrink-0 text-[11px] font-semibold px-2.5 py-1 rounded-md border transition disabled:opacity-50 ${run.paused ? 'bg-okd border-ok/40 text-ok hover:bg-ok/20' : 'bg-panel2 border-line text-warn hover:bg-warnd'}`}
          title={run.paused ? t('run.qb.resumeTitle', undefined, 'İstemci bir sonraki adımı almaya devam eder') : t('run.qb.pauseTitle', undefined, 'Süren adım tamamlanır; istemciye yeni adım verilmez')}
        >
          {run.paused ? <Play className="w-3.5 h-3.5" /> : <Pause className="w-3.5 h-3.5" />}
          {run.paused ? t('run.qb.resume', undefined, 'Devam') : t('run.qb.pause', undefined, 'Duraklat')}
        </button>
      )}

      {!run.is_terminal && (
        <button
          onClick={handleCancel}
          disabled={cancelling}
          className="inline-flex items-center gap-1 whitespace-nowrap shrink-0 text-[11px] font-semibold px-2.5 py-1 rounded-md bg-panel2 border border-line text-err hover:bg-errd transition disabled:opacity-50"
        >
          <XCircle className="w-3.5 h-3.5" />
          {cancelling ? t('run.qb.cancelling', undefined, 'İptal ediliyor…') : armed ? t('run.qb.cancelConfirm', undefined, 'Emin misiniz? Tekrar tıklayın') : t('run.qb.cancel', undefined, 'İptal')}
        </button>
      )}
    </>
  );

  return (
    <div className={`bg-panel border border-line border-l-4 ${run.status === 'ABANDONED' || run.status === 'FAILED' ? 'border-l-err' : waitingClient || run.paused || run.status === 'WAITING_APPROVAL' || run.status === 'QUEUED' ? 'border-l-warn' : run.status === 'ACTIVE' ? 'border-l-ok' : 'border-l-line'} rounded-panel shadow-panel px-4 py-2 shrink-0 flex flex-col gap-1.5`}>
    {run.progress.total > 0 && (
      <div className="h-1 rounded-full bg-sunk overflow-hidden" role="img" aria-label={t('run.qb.progressAria', { done: run.progress.done, total: run.progress.total }, `Koşu ilerlemesi ${run.progress.done}/${run.progress.total}`)}>
        <div className="h-full bg-ac transition-all" style={{ width: `${Math.min(100, Math.round((run.progress.done / run.progress.total) * 100))}%` }} />
      </div>
    )}
    <div className="flex items-center gap-x-3 gap-y-1.5 flex-wrap min-w-0">
      <div className="min-w-[300px] flex-1 basis-[340px] flex flex-col gap-0.5">
        <div className="flex items-center gap-2 min-w-0">
          <span className={`shrink-0 whitespace-nowrap inline-flex items-center gap-1.5 text-[11px] font-medium px-2 py-0.5 rounded-full border ${meta.cls}`}>
            {meta.icon}
            {meta.label.split(' — ')[0]}
            {run.status === 'COMPLETED' && run.outcome === 'with_failures' ? ` · ${t('run.qb.failedSteps', { n: run.failed_steps ?? 0 }, `${run.failed_steps ?? 0} adım hatalı`)}` : ''}
          </span>
          {meta.label.includes(' — ') && <span className="text-[13px] font-semibold text-ink truncate">{meta.label.split(' — ').slice(1).join(' — ').replace(/^./, ch => ch.toUpperCase())}</span>}
        </div>
        <span className="truncate whitespace-nowrap text-[11px] font-mono text-ink3">
          {run.run_id} · {t('run.qb.step', undefined, 'adım')} {run.progress.done}/{run.progress.total}
          {run.progress.current_order ? ` · #${run.progress.current_order}${current?.kind === 'fix' ? ` ${t('run.qb.fix', undefined, 'düzeltme')} ${current.fix_round}` : ''}` : ''}
          {dynamicNote ? ` · ${dynamicNote}` : ''}
        </span>
      </div>

      {run.status === 'ABANDONED' && (onResumeAbandoned || onRestartFresh) && (
        <div className="flex items-center gap-2">
          {onResumeAbandoned && (
            <button
              onClick={handleResumeAbandoned}
              disabled={busy}
              className="inline-flex items-center gap-1 whitespace-nowrap shrink-0 text-[11px] font-semibold px-2.5 py-1 rounded-md bg-ink text-bg hover:opacity-90 transition disabled:opacity-50"
              title={t('run.qb.resumeAbTitle', undefined, 'Koşu kaldığı adımdan sürer; biten adımlar tekrarlanmaz, onay bekleyen adım onay bekler halde döner')}
            >
              <Play className="w-3.5 h-3.5" />
              {t('run.qb.resumeAb', undefined, 'Kaldığı yerden sürdür')}
            </button>
          )}
          {onRestartFresh && (
            <button
              onClick={() => { setResumeError(''); setRestartName(''); setRestartStep(1); }}
              disabled={busy}
              className="inline-flex items-center gap-1 whitespace-nowrap shrink-0 text-[11px] font-semibold px-2.5 py-1 rounded-md bg-panel2 border border-line text-err hover:bg-errd transition disabled:opacity-50"
              title={t('run.qb.restartTitle', undefined, 'Tehlikeli: bu koşunun ilerlemesi bırakılır. İki aşamalı onay ister (proje adını yazarsınız).')}
            >
              <RotateCcw className="w-3.5 h-3.5" />
              {t('run.qb.restart', undefined, 'Baştan başlat…')}
            </button>
          )}
          {resumeError && restartStep === 0 && <span className="text-[11px] text-err">{resumeError}</span>}
        </div>
      )}

      {restartStep > 0 && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4" onClick={() => !busy && setRestartStep(0)}>
          <div className="bg-panel border border-err/50 rounded-2xl shadow-xl w-full max-w-md p-5 space-y-3 text-xs" onClick={e => e.stopPropagation()}>
            <div className="text-sm font-bold text-err">{t('run.qb.restartHead', undefined, 'Koşuyu baştan başlat')}</div>
            {restartStep === 1 ? (
              <>
                <div className="text-ink2 space-y-1.5">
                  <p>{t('run.qb.rs1a', { id: run.run_id }, `${run.run_id} koşusu bırakılacak ve yenisi kurulacak.`)}</p>
                  <p className="text-err">{t('run.qb.rs1b', { done: doneSteps, total: run.steps.length }, `Bu koşuda tamamlanan ${doneSteps}/${run.steps.length} adımın ilerlemesi çöpe gider; koşu geri getirilemez.`)}</p>
                  <p className="text-ink3">{t('run.qb.rs1c', undefined, 'Jira maddeleri, kod ve belgeler silinmez. Yalnızca kaldığı yerden sürdürmek istemiyorsanız gerekir; çoğu zaman "Kaldığı yerden sürdür" doğrusudur.')}</p>
                </div>
                <div className="flex justify-end gap-2">
                  <button className="px-3 py-1.5 rounded-md border border-line text-ink2" onClick={() => setRestartStep(0)}>{t('run.qb.giveUp', undefined, 'Vazgeç')}</button>
                  <button className="px-3 py-1.5 rounded-md bg-err text-white font-bold" onClick={() => setRestartStep(2)}>{t('run.qb.resume', undefined, 'Devam')}</button>
                </div>
              </>
            ) : (
              <>
                <div className="text-ink2">{t('run.qb.typeName', undefined, 'Onaylamak için proje adını yazın:')} <b className="text-ink">{projectName}</b></div>
                <input autoFocus value={restartName} onChange={e => setRestartName(e.target.value)} disabled={busy}
                  className="w-full bg-sunk border border-line rounded-md px-2.5 py-1.5 text-ink focus:outline-none focus:border-err" />
                {resumeError && <div className="text-err">{resumeError}</div>}
                <div className="flex justify-end gap-2">
                  <button className="px-3 py-1.5 rounded-md border border-line text-ink2" disabled={busy} onClick={() => setRestartStep(1)}>{t('run.qb.back', undefined, 'Geri')}</button>
                  <button className="px-3 py-1.5 rounded-md bg-err text-white font-bold disabled:opacity-40" disabled={busy || restartName.trim() !== (projectName || '')} onClick={handleRestartFresh}>
                    {busy ? t('run.qb.starting', undefined, 'Başlatılıyor…') : t('run.qb.abandonRestart', undefined, 'Koşuyu bırak ve baştan başlat')}
                  </button>
                </div>
              </>
            )}
          </div>
        </div>
      )}

      {isMcp && (run.status === 'QUEUED' || run.status === 'ABANDONED' || waitingClient) && (
        <div className="flex flex-col gap-0.5 flex-1 min-w-[320px]">
          <span className="text-[11px] text-ink3 whitespace-nowrap">{t('run.qb.writeToClaude', undefined, 'Claude oturumuna yaz')}</span>
          <div className="flex items-center gap-2">
          <code className="flex-1 truncate text-[11px] font-mono bg-panel2 border border-line rounded-lg px-2.5 py-1.5 text-ink select-all">
            {prompt}
          </code>
          <button
            onClick={copyPrompt}
            className="inline-flex items-center gap-1 whitespace-nowrap shrink-0 text-[11px] font-semibold px-2.5 py-1 rounded-md bg-ink text-bg hover:opacity-90 transition"
            title={t('run.qb.copyPrompt', undefined, 'Promptu panoya kopyala')}
          >
            {copied ? <Check className="w-3.5 h-3.5" /> : <Copy className="w-3.5 h-3.5" />}
            {copied ? t('run.qb.copied', undefined, 'Kopyalandı') : t('run.qb.copy', undefined, 'Kopyala')}
          </button>
          </div>
        </div>
      )}

      {isMcp && run.status !== 'QUEUED' && run.status !== 'ABANDONED' && (run.client_name || lastClient) && (
        <span className="shrink-0 whitespace-nowrap text-[11px] font-mono text-ink3">
          {t('run.qb.connectedClient', undefined, 'Bağlı istemci:')} <span className="text-ink font-semibold">{run.client_name || lastClient?.name}</span>
          {(run.client_version || lastClient?.version) ? ` v${run.client_version || lastClient?.version}` : ''}
        </span>
      )}

      {current && run.status !== 'QUEUED' && run.status !== 'ABANDONED' && (
        <span className="text-[11px] text-ink2 truncate min-w-0 flex-1 inline-flex items-center gap-1" title={`${current.role} · ${current.issue_id}${current.title ? ` · ${current.title}` : ''}`}>
          <span className="font-mono font-bold text-ink">{current.role}</span> · {t('run.qb.step', undefined, 'adım')} #{current.order} <KindBadge step={current} /> · {current.status === 'ACTIVE' ? t('run.qb.running', { time: elapsed(t, current.started_at) }, `çalışıyor ${elapsed(t, current.started_at)}`) : current.status === 'WAITING_APPROVAL' ? t('run.qb.waitingApproval', undefined, 'onay bekliyor') : current.status.toLowerCase()}
          {current.attempts > 1 ? ` · ${t('run.qb.attemptN', { n: current.attempts }, `${current.attempts}. deneme`)}` : ''}
          {current.title && current.kind !== 'phase' ? <span className="text-ink3 truncate"> · {current.title}</span> : null}
        </span>
      )}

      <button
      onClick={() => setOpen(o => !o)}
      className="ml-auto shrink-0 whitespace-nowrap inline-flex items-center gap-1 whitespace-nowrap shrink-0 text-[11px] font-semibold px-2.5 py-1 rounded-md bg-panel2 border border-line text-ink2 hover:text-ink hover:border-line2 transition"
      title={t('run.qb.toggleDetail', undefined, 'Adım ayrıntılarını göster/gizle')}
    >
      {open ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
      {t('run.qb.detail', undefined, 'Detay')}
    </button>

      {slot ? createPortal(<div className="flex items-center gap-1.5">{actionButtons}</div>, slot) : actionButtons}
    </div>

    {noteOpen && !run.is_terminal && onSendNote && (
      <div className="border-t border-line pt-2 space-y-2">
        <div className="text-[10px] font-mono font-bold uppercase tracking-wider text-ink3">{t('run.qb.noteHead', undefined, 'Yöneticiden ekibe not')}</div>
        <div className="text-[11px] text-ink3">
          {t('run.qb.noteHelp', undefined, 'Ajanlar sunucudan adım çekerek çalışır; notunuz bir sonraki adımın bağlamına "Yönetici notları" olarak girer (süren adımı kesmez). Hemen durdurmak istiyorsanız "Acil" işaretleyin: koşu duraklar, siz devam ettirene kadar yeni adım verilmez.')}
        </div>
        <textarea
          value={noteText}
          onChange={(e) => setNoteText(e.target.value)}
          rows={2}
          maxLength={2000}
          placeholder={t('run.qb.notePh', undefined, "Örn. Docker kullanılsın. / Önce kayıt ucunu bitir, OTP'yi sonraya bırak.")}
          className="w-full text-xs rounded-lg border border-line2 bg-sunk text-ink p-2 focus:outline-none focus:border-ac"
        />
        {noteError && <div role="alert" className="text-[11px] text-err">{noteError}</div>}
        <div className="flex items-center gap-3 flex-wrap">
          <label className="inline-flex items-center gap-1.5 text-[11px] text-warn cursor-pointer select-none">
            <input type="checkbox" checked={noteUrgent} onChange={(e) => setNoteUrgent(e.target.checked)} />
            {t('run.qb.urgent', undefined, 'Acil (koşuyu duraklat)')}
          </label>
          <button
            onClick={submitNote}
            disabled={noteSending || !noteText.trim()}
            className="ml-auto inline-flex items-center gap-1 whitespace-nowrap shrink-0 text-[11px] font-semibold px-3 py-1 rounded-md bg-ink text-bg hover:opacity-90 transition disabled:opacity-50"
          >
            <Send className="w-3.5 h-3.5" />
            {noteSending ? t('run.qb.sending', undefined, 'Gönderiliyor…') : t('run.qb.send', undefined, 'Gönder')}
          </button>
        </div>
        {notes.length > 0 && (
          <div className="space-y-1">
            {notes.map(n => (
              <div key={n.id} className="flex items-start gap-2 text-[11px]">
                <span className={`shrink-0 px-1.5 py-0.5 rounded border text-[10px] font-mono ${n.delivered_step != null ? 'bg-okd text-ok border-ok/40' : 'bg-warnd text-warn border-warn/40'}`}>
                  {n.id} · {n.kind === 'revise' ? t('run.qb.revise', undefined, 'revize') : t('run.qb.note', undefined, 'not')}{n.urgent ? ` · ${t('run.qb.urgentLc', undefined, 'acil')}` : ''} · {n.delivered_step != null ? t('run.qb.deliveredTo', { n: n.delivered_step }, `adım #${n.delivered_step}'e iletildi`) : t('run.qb.queued', undefined, 'sırada')}
                </span>
                <span className="text-ink2 min-w-0 break-words">
                  {n.text}
                  {n.reply && (
                    <span className="block mt-1 pl-2 border-l-2 border-ok/50 text-ink">
                      <span className="font-mono text-[10px] text-ok">↳ {n.reply.by} · {t('run.qb.step', undefined, 'adım')} #{n.reply.step}</span> {n.reply.answer}
                    </span>
                  )}
                  {!n.reply && n.unanswered && (
                    <span className="block mt-1 text-warn">{t('run.qb.unanswered', { n: n.delivered_step }, `⚠ Cevap verilmedi (adım #${n.delivered_step}); ajan notu yalnızca uyguladı ya da yok saydı.`)}</span>
                  )}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>
    )}

    {open && (
      <div className="grid grid-cols-1 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)] gap-3 border-t border-line pt-2">
        {/* Şu anki adım + canlı düşünce */}
        <div className="space-y-2 min-w-0">
          <div className="text-[10px] font-mono font-bold uppercase tracking-wider text-ink3">{t('run.qb.currentStep', undefined, 'Şu anki adım')}</div>
          {current ? (
            <div className="text-[11px] text-ink space-y-1">
              <div className="flex items-center gap-1 flex-wrap"><span className="font-mono font-bold">#{current.order} {current.role}</span> · {current.issue_id} · <span className={`px-1.5 py-0.5 rounded border text-[10px] font-mono ${STEP_STATUS_CLS[current.status] || STEP_STATUS_CLS.PENDING}`}>{current.status}</span>{current.server_side ? ` · ${t('run.qb.serverSide', undefined, 'sunucu tarafı')}` : ' · LLM'} <KindBadge step={current} /><VerifyBadge step={current} /></div>
              {current.title && <div className="text-ink font-semibold truncate" title={current.title}>{current.title}</div>}
              <div className="text-ink2 font-mono text-[10.5px]">{t('run.qb.started', undefined, 'başladı')} {hhmm(current.started_at)}{current.finished_at ? ` · ${t('run.qb.finished', undefined, 'bitti')} ${hhmm(current.finished_at)}` : current.started_at ? ` · ${elapsed(t, current.started_at)}` : ''} · {t('run.qb.attempt', undefined, 'deneme')} {Math.max(1, current.attempts)} · {current.tokens_in + current.tokens_out > 0 ? `${(current.tokens_in + current.tokens_out).toLocaleString('tr-TR')} tok` : t('run.qb.tokenWaiting', undefined, 'token bekleniyor')}</div>
              {current.summary && <div className="text-ink2">{current.summary}</div>}
              {current.validation_errors?.length > 0 && <div className="text-warn font-mono text-[10.5px]">{t('run.qb.validation', undefined, 'Doğrulama:')} {current.validation_errors.join(' · ')}</div>}
              {current.error && <div className="text-err font-mono text-[10.5px]">{current.error}</div>}
            </div>
          ) : <div className="text-[11px] text-ink3">{t('run.qb.noStepInfo', undefined, 'Adım bilgisi yok.')}</div>}
          {thinking ? (
            <div className="rounded-lg bg-acd/50 border border-ac/30 px-2.5 py-1.5 text-[11px]">
              <div className="flex items-center gap-1 text-[9px] font-mono font-bold uppercase tracking-wider text-ac mb-0.5"><BrainCircuit className="w-3 h-3" /> {thinking.agent_id} {t('run.qb.thinking', undefined, 'düşünüyor')} · {hhmm(thinking.timestamp)}</div>
              <div className="text-ink italic">"{thinking.text}"</div>
              {(thinking.what_doing || thinking.what_next) && (
                <div className="text-ink2 text-[10.5px] mt-0.5">{thinking.what_doing ? `${t('run.qb.whatDoing', undefined, 'Ne yapıyor:')} ${thinking.what_doing}` : ''}{thinking.what_doing && thinking.what_next ? ' · ' : ''}{thinking.what_next ? `${t('run.qb.whatNext', undefined, 'Sırada:')} ${thinking.what_next}` : ''}</div>
              )}
            </div>
          ) : run.status === 'ACTIVE' ? (
            <div className="text-[11px] text-ink3">{t('run.qb.noThinking', undefined, 'İstemci henüz düşünce bildirmedi (report_thinking). Üretim istemci tarafında sürüyor; sonuç geldiğinde adım özeti ve dosyalar burada görünür.')}</div>
          ) : null}
        </div>

        {/* Adım listesi */}
        <div className="min-w-0">
          <div className="text-[10px] font-mono font-bold uppercase tracking-wider text-ink3 mb-1">{t('run.qb.steps', undefined, 'Adımlar')} ({run.progress.done}/{run.progress.total})</div>
          <div className="space-y-1 max-h-48 overflow-auto pr-1">
            {run.steps.map((s, i) => (
              <div key={`${i}-${s.order}-${s.kind || 'phase'}-${s.fix_round || 0}`} className={`flex items-start gap-2 text-[11px] ${i === idx ? 'bg-acd/30 rounded px-1 -mx-1' : ''}`}>
                <span className={`shrink-0 px-1.5 py-0.5 rounded border text-[10px] font-mono ${STEP_STATUS_CLS[s.status] || STEP_STATUS_CLS.PENDING}`}>#{s.order} {s.status}</span>
                <div className="min-w-0 flex-1">
                  <span className="font-mono font-semibold text-ink">{s.role}</span>
                  <span className="inline-flex items-center gap-1 ml-1 align-middle"><KindBadge step={s} /><VerifyBadge step={s} /></span>
                  {s.title && s.kind !== 'phase' && <span className="text-ink2"> · {s.title}</span>}
                  {s.action && <span className="text-ink3"> · {s.action}</span>}
                  {s.tokens_in + s.tokens_out > 0 && <span className="text-ink3"> · {(s.tokens_in + s.tokens_out).toLocaleString('tr-TR')} tok</span>}
                  {s.summary && <div className="text-ink2 truncate" title={s.summary}>{s.summary}</div>}
                  {s.artifacts?.length > 0 && (
                    <div className="flex flex-wrap gap-1 mt-0.5">
                      {s.artifacts.map(a => <span key={a} className="inline-flex items-center gap-0.5 text-[10px] font-mono px-1 rounded bg-sunk border border-line text-ink2"><FileCode2 className="w-2.5 h-2.5 text-ac" />{a}</span>)}
                    </div>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    )}
    </div>
  );
};
