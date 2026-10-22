import React, { useEffect, useRef, useState } from 'react';
import { Terminal, X, ArrowRight } from 'lucide-react';
import { TelemetryEvent } from '../types/telemetry';
import { EventLog } from './EventLog';
import { useI18n } from '../i18n';

interface TelemetryDockProps {
  events: TelemetryEvent[];
  currentProjectId?: string;
}

const TOAST_MS = 20000;

/** Sağa sabit, açılır/kapanır CANLI TELEMETRİ günlüğü. Kapalıyken yeni olay gelince 20 sn'lik bir bildirim çıkar; tıklanınca günlük açılır (en güncel konum). */
export const TelemetryDock: React.FC<TelemetryDockProps> = ({ events, currentProjectId }) => {
  const { t, lang } = useI18n();
  const [open, setOpen] = useState(false);
  const [toast, setToast] = useState<TelemetryEvent | null>(null);
  const [unseen, setUnseen] = useState(0);
  const lastId = useRef<string | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const latest = events.length > 0 ? events[0] : null;       // events yeniden eskiye sıralıdır

  useEffect(() => {
    const id = latest ? `${latest.id}|${latest.timestamp}|${latest.action}` : null;
    if (lastId.current === null) { lastId.current = id; return; }    // ilk yükleme: bildirim çıkarma
    if (id === lastId.current || !latest) return;
    lastId.current = id;
    if (open) return;
    setUnseen(n => n + 1);
    setToast(latest);
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => setToast(null), TOAST_MS);
  }, [latest, open]);

  useEffect(() => () => { if (timer.current) clearTimeout(timer.current); }, []);

  useEffect(() => {
    if (!open) return undefined;
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open]);

  const openDock = () => { setOpen(true); setToast(null); setUnseen(0); if (timer.current) clearTimeout(timer.current); };
  useEffect(() => {
    const h = () => { setOpen(true); setToast(null); setUnseen(0); };
    window.addEventListener('fssc:open-telemetry', h);
    return () => window.removeEventListener('fssc:open-telemetry', h);
  }, []);

  return (
    <>
      {/* Açma düğmesi sol raydaki 'Telemetri' (fssc:open-telemetry olayı); yüzen sağ sekme kaldırıldı: board içeriğini örtüyordu */}

      {/* Yeni olay bildirimi (20 sn) */}
      {!open && toast && (
        <div className="fixed right-3 top-24 z-50 w-80 animate-in slide-in-from-right-4 duration-200">
        <button
          type="button"
          onClick={openDock}
          className="w-full text-left bg-panel border border-ac/40 rounded-xl shadow-xl p-3 hover:border-ac transition"
          title={t('misc.dock.openTip', undefined, 'Tıklayın: canlı telemetriyi aç')}
        >
          <div className="flex items-center justify-between gap-2 text-[11px] font-mono">
            <span className="flex items-center gap-1 text-ac font-bold truncate">{toast.from_agent}<ArrowRight className="w-3 h-3" />{toast.to_agent}</span>
            <span className={`mr-2 px-1.5 py-0.5 rounded border text-[10px] ${toast.status === 'FAILED' ? 'bg-errd text-err border-err/40' : 'bg-okd text-ok border-ok/40'}`}>{toast.status}</span>
          </div>
          <div className="mt-1 text-xs font-semibold text-ink truncate">{toast.action}</div>
          {(toast.friendly_dialogue || toast.thinking) && (
            <div className="mt-1 text-[11px] text-ink3 line-clamp-2 italic">{toast.friendly_dialogue || toast.thinking}</div>
          )}
          <div className="mt-1.5 text-[10px] font-mono text-ink3">{new Date(toast.timestamp).toLocaleTimeString(lang === 'tr' ? 'tr-TR' : lang === 'es' ? 'es-ES' : lang === 'de' ? 'de-DE' : 'en-US')} · {t('misc.dock.clickToOpen', undefined, 'açmak için tıklayın')}</div>
          <div className="mt-2 h-0.5 bg-line rounded overflow-hidden"><div className="h-full bg-ac origin-left" style={{ animation: `fssc-toast-shrink ${TOAST_MS}ms linear forwards` }} /></div>
        </button>
        <button type="button" onClick={() => { setToast(null); if (timer.current) clearTimeout(timer.current); }} title={t('misc.dock.close', undefined, 'Kapat')} aria-label={t('misc.dock.closeToast', undefined, 'Bildirimi kapat')}
          className="absolute -right-2 -top-2 p-1 rounded-full bg-panel2 border border-line text-ink3 hover:text-ink shadow"><X className="w-3 h-3" /></button>
        </div>
      )}

      {/* Açık çekmece */}
      {open && (
        <div className="fixed right-3 top-3 bottom-12 z-50 w-[400px] bg-panel border border-line rounded-panel shadow-2xl overflow-hidden flex flex-col animate-in slide-in-from-right-4 duration-200">
          <button type="button" onClick={() => setOpen(false)} title={t('misc.dock.closeEsc', undefined, 'Kapat (Esc)')} aria-label={t('misc.dock.closeDock', undefined, 'Telemetriyi kapat')}
            className="absolute right-2 top-2 z-10 p-1 rounded-md bg-panel2 border border-line text-ink3 hover:text-ink"><X className="w-3.5 h-3.5" /></button>
          <div className="flex-1 min-h-0">
            <EventLog events={events} currentProjectId={currentProjectId} />
          </div>
        </div>
      )}
      <style>{'@keyframes fssc-toast-shrink { from { transform: scaleX(1); } to { transform: scaleX(0); } }'}</style>
    </>
  );
};
