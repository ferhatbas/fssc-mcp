import React, { useEffect, useState } from 'react';
import { notify } from '../lib/dialog';
import { X, Cpu, RotateCcw, XCircle, Clock, CheckCircle2, AlertTriangle, PauseCircle, Activity } from 'lucide-react';
import { PipelineRun, StepRecord } from '../types/telemetry';
import { useI18n } from '../i18n';

interface RunHistoryDrawerProps {
  isOpen: boolean;
  runs: PipelineRun[];
  onClose: () => void;
  onRerun: (orders: number[]) => Promise<any>;
  onCancel: (runId: string) => Promise<any>;
}

const RUN_STATUS_CLS: Record<string, string> = {
  QUEUED: 'bg-warnd text-warn border-warn/40',
  ACTIVE: 'bg-okd text-ok border-ok/40',
  WAITING_APPROVAL: 'bg-infod text-info border-info/40',
  COMPLETED: 'bg-okd text-ok border-ok/40',
  CANCELLED: 'bg-sunk text-ink3 border-line',
  ABANDONED: 'bg-errd text-err border-err/40',
  FAILED: 'bg-errd text-err border-err/40',
};

const STEP_CLS: Record<string, string> = {
  PENDING: 'bg-sunk text-ink3 border-line',
  ACTIVE: 'bg-okd text-ok border-ok/40 animate-pulse',
  WAITING_APPROVAL: 'bg-infod text-info border-info/40',
  DONE: 'bg-okd text-ok border-ok/40',
  REJECTED: 'bg-errd text-err border-err/40',
  FAILED: 'bg-errd text-err border-err/40',
  SKIPPED: 'bg-sunk text-ink3 border-line line-through',
};

const RUN_ICON: Record<string, React.ReactNode> = {
  QUEUED: <Clock className="w-3.5 h-3.5" />,
  ACTIVE: <Activity className="w-3.5 h-3.5 animate-pulse" />,
  WAITING_APPROVAL: <PauseCircle className="w-3.5 h-3.5" />,
  COMPLETED: <CheckCircle2 className="w-3.5 h-3.5" />,
  CANCELLED: <XCircle className="w-3.5 h-3.5" />,
  ABANDONED: <AlertTriangle className="w-3.5 h-3.5" />,
  FAILED: <AlertTriangle className="w-3.5 h-3.5" />,
};

function fmt(iso?: string | null): string {
  if (!iso) return '-';
  const d = new Date(iso);
  return isNaN(d.getTime()) ? iso : d.toLocaleString('tr-TR', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' });
}

function duration(run: PipelineRun, t: (k: string, p?: Record<string, string | number>, f?: string) => string): string {
  const start = run.started_at || run.created_at;
  const end = run.finished_at || run.last_seen;
  if (!start || !end) return '-';
  const ms = new Date(end).getTime() - new Date(start).getTime();
  if (!isFinite(ms) || ms < 0) return '-';
  const s = Math.round(ms / 1000);
  if (s < 60) return t('run.hist.durSec', { s }, `${s} sn`);
  const m = Math.floor(s / 60);
  return t('run.hist.durMinSec', { m, s: s % 60 }, `${m} dk ${s % 60} sn`);
}

export const RunHistoryDrawer: React.FC<RunHistoryDrawerProps> = ({ isOpen, runs, onClose, onRerun, onCancel }) => {
  const { t } = useI18n();
  const [busy, setBusy] = useState<string | null>(null);

  useEffect(() => {
    if (!isOpen) return;
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose();
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  const act = async (key: string, fn: () => Promise<any>) => {
    setBusy(key);
    try {
      await fn();
    } catch (err) {
      console.error(err);
      notify(err instanceof Error ? err.message : t('run.hist.opFailed', undefined, 'İşlem başarısız'));
    } finally {
      setBusy(null);
    }
  };

  return (
    <aside className="fixed top-0 right-0 h-full w-[520px] max-w-[95vw] z-40 bg-panel border-l border-line shadow-panel flex flex-col">
      <div className="px-4 py-3 border-b border-line bg-panel2 flex items-center justify-between">
        <div>
          <h3 className="text-sm font-bold text-ink flex items-center gap-2"><Cpu className="w-4 h-4 text-ac" /> {t('run.hist.title', undefined, 'Koşu Geçmişi')}</h3>
          <p className="text-[11px] text-ink3">{t('run.hist.subtitle', undefined, 'Her adım tek tek test edilebilir; bir koşuyu aynı adımlarla yeniden başlatın.')}</p>
        </div>
        <button onClick={onClose} className="p-1.5 rounded-md text-ink3 hover:text-ink hover:bg-sunk transition" title={t('run.hist.closeEsc', undefined, 'Kapat (Esc)')}>
          <X className="w-4 h-4" />
        </button>
      </div>

      <div className="flex-1 overflow-y-auto p-4 space-y-3">
        {runs.length === 0 && <div className="text-center text-ink3 text-xs italic py-10">{t('run.hist.empty', undefined, 'Henüz koşu yok. Jira satırındaki ▶ ile tek bir adımı deneyin.')}</div>}
        {runs.map(run => (
          <div key={run.run_id} className="bg-panel2 border border-line rounded-card p-3 space-y-2">
            <div className="flex items-center gap-2 flex-wrap">
              <span className={`inline-flex items-center gap-1 text-[10px] font-mono font-bold px-2 py-0.5 rounded border ${RUN_STATUS_CLS[run.status] || RUN_STATUS_CLS.QUEUED}`}>
                {RUN_ICON[run.status]}{run.status}
              </span>
              <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-sunk border border-line text-ink2">
                {run.engine === 'mcp_client' ? t('run.hist.engineMcp', undefined, 'MCP İstemcisi') : t('run.hist.engineTemplate', undefined, 'Şablon')}
              </span>
              <span className="text-[10px] font-mono text-ink3">{run.run_id}</span>
              {run.client_name && <span className="text-[10px] font-mono text-ink3">• {run.client_name}</span>}
              <span className="ml-auto text-[10px] font-mono text-ink3">{fmt(run.created_at)} • {duration(run, t)}</span>
            </div>

            <div className="flex flex-wrap gap-1">
              {run.steps.map((s: StepRecord) => (
                <span
                  key={s.order}
                  title={`${s.issue_id} • ${s.role} • ${s.status}${s.tokens_in || s.tokens_out ? ` • ${s.tokens_in}/${s.tokens_out} ${t('run.hist.tok', undefined, 'tok')}` : ''}${s.summary ? `\n${s.summary}` : ''}${s.error ? `\n${s.error}` : ''}`}
                  className={`text-[10px] font-mono px-1.5 py-0.5 rounded border ${STEP_CLS[s.status] || STEP_CLS.PENDING}`}
                >
                  #{s.order} {s.role}
                </span>
              ))}
            </div>

            {run.custom_prompt && <p className="text-[11px] text-ink2 truncate" title={run.custom_prompt}>{run.custom_prompt}</p>}

            <div className="flex items-center gap-2 pt-1">
              <span className="text-[10px] font-mono text-ink3">{run.progress.done}/{run.progress.total} {t('run.hist.stepWord', undefined, 'adım')}</span>
              <div className="ml-auto flex items-center gap-1.5">
                {!run.is_terminal && (
                  <button
                    disabled={busy === run.run_id}
                    onClick={() => act(run.run_id, () => onCancel(run.run_id))}
                    className="inline-flex items-center gap-1 text-[11px] px-2 py-1 rounded-md border border-line bg-panel text-err hover:bg-errd transition disabled:opacity-50"
                  >
                    <XCircle className="w-3 h-3" /> {t('run.hist.cancel', undefined, 'İptal')}
                  </button>
                )}
                <button
                  disabled={busy === run.run_id + ':rerun'}
                  onClick={() => act(run.run_id + ':rerun', () => onRerun(run.steps.map(s => s.order)))}
                  className="inline-flex items-center gap-1 text-[11px] px-2 py-1 rounded-md bg-ac text-onac hover:opacity-90 transition disabled:opacity-50"
                >
                  <RotateCcw className="w-3 h-3" /> {t('run.hist.rerun', undefined, 'Tekrar çalıştır')}
                </button>
              </div>
            </div>
          </div>
        ))}
      </div>
    </aside>
  );
};
