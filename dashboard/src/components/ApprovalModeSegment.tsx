import React, { useEffect, useRef, useState } from 'react';
import { Check, Eye, ChevronDown } from 'lucide-react';
import { EngineSettings, RaisedHand } from '../types/telemetry';
import { useI18n } from '../i18n';

interface ApprovalModeSegmentProps {
  mode: EngineSettings['approval_mode'];
  raisedHands: RaisedHand[];
  onChangeMode: (mode: EngineSettings['approval_mode']) => Promise<any>;
  onInspectHand: (hand: RaisedHand) => void;
  onResolveHand: (handId: string) => Promise<any>;
}

// label/hint alanları çeviri anahtarıdır (render sırasında t() ile çözülür)
const MODES: { id: EngineSettings['approval_mode']; label: string; hint: string }[] = [
  { id: 'every_step', label: 'project.approval.every_step', hint: 'project.approval.every_step.hint' },
  { id: 'critical_only', label: 'project.approval.critical_only', hint: 'project.approval.critical_only.hint' },
  { id: 'note_and_continue', label: 'project.approval.note_and_continue', hint: 'project.approval.note_and_continue.hint' },
  { id: 'auto', label: 'project.approval.auto', hint: 'project.approval.auto.hint' },
];

/** Onay modu (tasarımdaki gibi tek düğme: "Onay: Otomatik ▾"); açılır menüde dört mod ve kaldırılan eller. */
export const ApprovalModeSegment: React.FC<ApprovalModeSegmentProps> = ({ mode, raisedHands, onChangeMode, onInspectHand, onResolveHand }) => {
  const { t, lang } = useI18n();
  const [open, setOpen] = useState(false);
  const [handsOpen, setHandsOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const unreviewed = raisedHands.filter(h => !h.reviewed);
  const current = MODES.find(m => m.id === mode) || MODES[0];

  useEffect(() => {
    if (!open) return undefined;
    const onDoc = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) { setOpen(false); setHandsOpen(false); } };
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') { setOpen(false); setHandsOpen(false); } };
    document.addEventListener('mousedown', onDoc);
    document.addEventListener('keydown', onKey);
    return () => { document.removeEventListener('mousedown', onDoc); document.removeEventListener('keydown', onKey); };
  }, [open]);

  const change = async (next: EngineSettings['approval_mode']) => {
    if (next === mode) { setOpen(false); return; }
    setSaving(true);
    try { await onChangeMode(next); setOpen(false); } catch (err) { console.error(err); } finally { setSaving(false); }
  };

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen(o => !o)}
        aria-haspopup="menu"
        aria-expanded={open}
        title={t('project.approval.title', undefined, 'Her adımdan sonra yönetici onayı beklensin mi? Ajanların kaldırdığı eller de burada.')}
        className="inline-flex items-center gap-1.5 h-[30px] px-3 rounded-lg border border-line bg-panel text-[12.5px] font-medium text-ink hover:bg-sunk whitespace-nowrap"
      >
        <b className="font-semibold">{t(current.label)}</b>
        {unreviewed.length > 0 && <span className="text-[10px] font-mono px-1.5 rounded-full bg-warn text-onac">{unreviewed.length} el</span>}
        <ChevronDown className="w-3 h-3" />
      </button>

      {open && (
        <div role="menu" className="absolute right-0 top-full mt-1.5 z-40 w-[380px] max-h-[460px] overflow-y-auto bg-panel border border-line rounded-xl shadow-xl p-1.5 space-y-1">
          {MODES.map(m => (
            <button
              key={m.id}
              role="menuitemradio"
              aria-checked={mode === m.id}
              type="button"
              disabled={saving}
              onClick={() => change(m.id)}
              title={t(m.hint)}
              className={`w-full text-left px-2.5 py-1.5 rounded-lg text-[12px] transition ${mode === m.id ? 'bg-acd text-ac' : 'text-ink hover:bg-sunk'}`}
            >
              <div className="font-medium">{t(m.label)}</div>
              <div className="text-[10.5px] text-ink3 leading-snug">{t(m.hint)}</div>
            </button>
          ))}
          <div className="border-t border-line pt-1">
            <button type="button" onClick={() => setHandsOpen(h => !h)} className="w-full flex items-center justify-between px-2.5 py-1.5 rounded-lg text-[12px] text-ink hover:bg-sunk">
              <span>{t('project.approval.hands', { n: raisedHands.length }, 'Kaldırılan eller ({n})')}</span>
              <span className="text-[10.5px] text-ink3">{t('project.approval.unreviewed', { n: unreviewed.length }, '{n} incelenmedi')}</span>
            </button>
            {handsOpen && (
              <div className="space-y-1.5 p-1">
                {raisedHands.length === 0 && <div className="text-[11px] text-ink3 italic px-1 py-3 text-center">{t('project.approval.noHands', undefined, 'Henüz el kaldıran adım yok. "Not al" modunda adımlar burada birikir.')}</div>}
                {raisedHands.map(h => (
                  <div key={h.id} className={`rounded-lg border px-2.5 py-2 ${h.reviewed ? 'bg-sunk border-line opacity-70' : h.critical ? 'bg-warnd/50 border-warn/40' : 'bg-panel2 border-line'}`}>
                    <div className="flex items-center gap-2 text-[10px] font-mono">
                      <span className="font-bold text-ink">#{h.order}</span>
                      <span className="text-ac">{h.agent_name || h.agent_id}</span>
                      {h.critical && <span className="px-1 rounded bg-warnd text-warn border border-warn/40">{t('project.approval.critical', undefined, 'kritik')}</span>}
                      <span className="ml-auto text-ink3">{new Date(h.raised_at).toLocaleTimeString(lang, { hour: '2-digit', minute: '2-digit' })}</span>
                    </div>
                    <div className="text-[11px] text-ink truncate mt-0.5" title={h.title}>{h.title}</div>
                    {h.note && <div className="text-[10px] text-ink2 line-clamp-2 mt-0.5">{h.note}</div>}
                    <div className="flex items-center gap-1.5 mt-1.5">
                      <button onClick={() => { onInspectHand(h); setOpen(false); }} className="inline-flex items-center gap-1 text-[10px] px-2 py-0.5 rounded-md bg-ac text-onac hover:opacity-90"><Eye className="w-3 h-3" /> {t('project.approval.inspect', undefined, 'İncele')}</button>
                      {!h.reviewed && <button onClick={() => onResolveHand(h.id)} className="inline-flex items-center gap-1 text-[10px] px-2 py-0.5 rounded-md bg-panel border border-line text-ink2 hover:text-ok"><Check className="w-3 h-3" /> {t('project.approval.seen', undefined, 'Gördüm')}</button>}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
};
