import React, { useCallback, useEffect, useRef, useState } from 'react';
import { CheckCircle2, AlertTriangle, Info, X } from 'lucide-react';
import { DIALOG_EVENT, TOAST_EVENT, DialogDetail, ToastKind, setDialogHostMounted } from '../lib/dialog';
import { useI18n } from '../i18n';

interface Toast { id: number; message: string; kind: ToastKind }

/** Uygulama içi bildirimler (toast) ve onay / metin girişi kutuları: tarayıcı penceresi (alert, confirm, prompt) kullanılmaz. main.tsx bir kez bağlar. */
export const DialogHost: React.FC = () => {
  const { t } = useI18n();
  const [toasts, setToasts] = useState<Toast[]>([]);
  const [queue, setQueue] = useState<DialogDetail[]>([]);
  const [text, setText] = useState('');
  const seq = useRef(0);
  const inputRef = useRef<HTMLInputElement & HTMLTextAreaElement>(null);
  const okRef = useRef<HTMLButtonElement>(null);
  const dialog = queue[0] || null;

  useEffect(() => {
    setDialogHostMounted(true);
    const onToast = (e: Event) => {
      const d = (e as CustomEvent<{ message: string; kind: ToastKind }>).detail;
      const id = ++seq.current;
      setToasts(t => [...t.slice(-4), { id, message: d.message, kind: d.kind }]);
      window.setTimeout(() => setToasts(t => t.filter(x => x.id !== id)), d.kind === 'error' ? 10000 : 6000);
    };
    const onDialog = (e: Event) => setQueue(q => [...q, (e as CustomEvent<DialogDetail>).detail]);
    window.addEventListener(TOAST_EVENT, onToast);
    window.addEventListener(DIALOG_EVENT, onDialog);
    return () => { setDialogHostMounted(false); window.removeEventListener(TOAST_EVENT, onToast); window.removeEventListener(DIALOG_EVENT, onDialog); };
  }, []);

  useEffect(() => {
    if (!dialog) return;
    setText(dialog.defaultValue || '');
    window.setTimeout(() => (dialog.type === 'prompt' ? inputRef.current : okRef.current)?.focus(), 30);
  }, [dialog]);

  const close = useCallback((value: boolean | string | null) => {
    setQueue(q => { q[0]?.resolve(value); return q.slice(1); });
  }, []);

  useEffect(() => {
    if (!dialog) return undefined;
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') { e.preventDefault(); close(dialog.type === 'prompt' ? null : false); } };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [dialog, close]);

  const icon = (k: ToastKind) => k === 'error' ? <AlertTriangle className="w-4 h-4 text-err shrink-0 mt-0.5" /> : k === 'success' ? <CheckCircle2 className="w-4 h-4 text-ok shrink-0 mt-0.5" /> : <Info className="w-4 h-4 text-info shrink-0 mt-0.5" />;

  return (
    <>
      <div className="fixed bottom-4 right-4 z-[200] flex flex-col-reverse gap-2 w-[360px] max-w-[calc(100vw-24px)] pointer-events-none" aria-live="polite">
        {toasts.map(ts => (
          <div key={ts.id} role={ts.kind === 'error' ? 'alert' : 'status'}
            className={`pointer-events-auto flex gap-2 p-3 rounded-xl border shadow-xl bg-panel text-xs text-ink ${ts.kind === 'error' ? 'border-err/50' : ts.kind === 'success' ? 'border-ok/50' : 'border-line'}`}>
            {icon(ts.kind)}
            <div className="flex-1 whitespace-pre-line break-words">{ts.message}</div>
            <button type="button" aria-label={t('misc.dialog.close', undefined, 'Kapat')} onClick={() => setToasts(x => x.filter(y => y.id !== ts.id))} className="text-ink3 hover:text-ink"><X className="w-3.5 h-3.5" /></button>
          </div>
        ))}
      </div>

      {dialog && (
        <div className="fixed inset-0 z-[210] bg-black/40 flex items-center justify-center p-4" onMouseDown={e => { if (e.target === e.currentTarget) close(dialog.type === 'prompt' ? null : false); }}>
          <div role="dialog" aria-modal="true" className={`w-full ${dialog.type === 'prompt' && dialog.options?.multiline ? 'max-w-2xl' : 'max-w-md'} bg-panel border border-line rounded-2xl shadow-2xl p-5 space-y-3`}>
            {dialog.options?.title && <div className="text-sm font-bold text-ink">{dialog.options.title}</div>}
            <div className="text-[13px] text-ink2 whitespace-pre-line break-words">{dialog.message}</div>
            {dialog.type === 'prompt' && (dialog.options?.multiline ? (
              <textarea ref={inputRef} value={text} rows={9} placeholder={dialog.options?.placeholder} onChange={e => setText(e.target.value)} onKeyDown={e => { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) close(text); }}
                className="w-full bg-sunk border border-line2 rounded-lg px-3 py-2 text-sm text-ink leading-relaxed resize-y min-h-[8rem] max-h-[60vh] focus:outline-none focus:ring-2 focus:ring-ac/40 focus:border-ac" />
            ) : (
              <input ref={inputRef} value={text} onChange={e => setText(e.target.value)} onKeyDown={e => { if (e.key === 'Enter') close(text); }}
                className="w-full bg-sunk border border-line2 rounded-lg px-3 py-2 text-sm text-ink focus:outline-none focus:ring-2 focus:ring-ac/40 focus:border-ac" />
            ))}
            <div className="flex justify-end gap-2 pt-1">
              <button type="button" onClick={() => close(dialog.type === 'prompt' ? null : false)} className="px-3 py-1.5 rounded-lg border border-line text-xs text-ink2 hover:text-ink">{dialog.options?.cancelLabel || t('common.cancel')}</button>
              <button ref={okRef} type="button" onClick={() => close(dialog.type === 'prompt' ? text : true)}
                className={`px-3 py-1.5 rounded-lg text-xs font-semibold text-onac hover:opacity-90 ${dialog.options?.danger ? 'bg-err' : 'bg-ac'}`}>{dialog.options?.confirmLabel || t('common.ok')}</button>
            </div>
          </div>
        </div>
      )}
    </>
  );
};
