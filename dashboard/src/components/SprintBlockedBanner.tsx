import React, { useCallback, useEffect, useState } from 'react';
import { X } from 'lucide-react';
import { api } from '../config';
import { BudgetSettings } from './BudgetSettings';
import { useI18n } from '../i18n';

interface Blocked { sprint: number; reason: string; detail?: string }

// yedek metinler; çeviri sprint.blocked.title.<KOD>
const TITLES: Record<string, string> = {
  BUDGET_EXCEEDED: 'Sprint bütçesi aşıldı', STALLED: 'Sprint ilerlemiyor', BLOCKING_QUESTION: 'Engelleyici soru açık',
  PRECONDITION_LOST: 'Kapanış koşulu eksik', CARRY_OVER_LIMIT: 'Taşıma sınırı aşıldı', NO_PROGRESS: 'İlerleme yok',
};

/** Pano genelinde engel kartı: ne oldu, ne kadar, ne yapılır. Bütçe aşıldıysa sağdan açılan çekmecede sınırlar düzenlenir ve sprint sürdürülür. */
export const SprintBlockedBanner: React.FC = () => {
  const { t } = useI18n();
  const [b, setB] = useState<Blocked | null>(null);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');

  const load = useCallback(async () => {
    try {
      const j = await fetch(api('/api/sprints/board')).then(r => r.json());
      const c = j?.current;
      setB(c && c.status === 'BLOCKED' && c.blocked ? { sprint: c.sprint_number, reason: c.blocked.reason, detail: c.blocked.detail } : null);
    } catch { /* sunucu yoksa kart gösterilmez */ }
  }, []);
  useEffect(() => {
    void load();
    const iv = setInterval(load, 15000);
    return () => clearInterval(iv);
  }, [load]);
  useEffect(() => {
    if (!open) return undefined;
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open]);

  if (!b) return null;
  const budget = b.reason === 'BUDGET_EXCEEDED' || b.reason === 'STALLED';
  const unblock = async () => {
    const r = await fetch(api(`/api/sprints/${b.sprint}/unblock`), { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' });
    if (!r.ok) throw new Error((await r.json().catch(() => ({})))?.error || t('sprint.blocked.unblockFailed', undefined, 'Engel kaldırılamadı'));
  };
  const unblockClick = async () => {
    setBusy(true);
    setErr('');
    try { await unblock(); await load(); } catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  };

  return (
    <>
      <section role="alert" className="shrink-0 bg-panel border border-line border-l-4 border-l-err rounded-panel shadow-panel px-4 py-2.5 flex flex-wrap items-center gap-x-6 gap-y-2">
        <div className="flex-1 min-w-[300px] space-y-1">
          <div className="flex items-center gap-2.5">
            <span className="text-[11px] font-medium px-2 py-0.5 rounded-full border bg-errd text-err border-err/40 whitespace-nowrap">{budget ? t('sprint.blocked.budgetExceeded', undefined, 'Bütçe aşıldı') : t('sprint.blocked.stopped', undefined, 'Sprint durdu')}</span>
            <span className="text-sm font-semibold text-ink">Sprint {b.sprint}: {TITLES[b.reason] ? t(`sprint.blocked.title.${b.reason}`, undefined, TITLES[b.reason]) : b.reason}</span>
          </div>
          {b.detail && <div className="font-mono text-[11px] text-ink3">{b.detail}</div>}
          {budget && <div className="h-1 rounded-full bg-errd overflow-hidden" role="img" aria-label={t('sprint.blocked.limitReached', undefined, 'Sınıra ulaşıldı')}><div className="h-full bg-err w-full" /></div>}
          {err && <div className="text-[11px] text-err">{err}</div>}
        </div>
        <div className="flex items-center gap-2">
          {budget && <button onClick={() => setOpen(true)} className="px-3 py-1.5 rounded-lg border border-line bg-panel2 text-xs font-medium text-ink hover:bg-sunk whitespace-nowrap">{t('sprint.blocked.editLimits', undefined, 'Sınırları düzenle')}</button>}
          <button disabled={busy} onClick={unblockClick} className="px-3 py-1.5 rounded-lg bg-ok text-onac text-xs font-semibold hover:opacity-90 disabled:opacity-50 whitespace-nowrap" title={t('sprint.blocked.unblockTip', undefined, 'Sınırı artırdıysan ya da nedeni çözdüysen sprinti sürdür')}>{t('sprint.blocked.unblock', undefined, 'Engeli kaldır ve sürdür')}</button>
        </div>
      </section>

      {open && (
        <div className="fixed inset-0 z-[80] bg-black/30" onMouseDown={e => { if (e.target === e.currentTarget) setOpen(false); }}>
          <aside aria-label={t('sprint.blocked.budgetLimits', undefined, 'Bütçe sınırları')} className="absolute top-0 right-0 bottom-0 w-[440px] max-w-full bg-panel border-l border-line shadow-2xl flex flex-col">
            <div className="flex items-center justify-between px-5 py-4 border-b border-line">
              <div>
                <div className="text-[15px] font-semibold text-ink">{t('sprint.blocked.budgetLimits', undefined, 'Bütçe sınırları')}</div>
                <div className="text-xs text-ink3 mt-0.5">{t('sprint.blocked.drawerHint', undefined, 'Proje ayarları · Sprint durunca burada artırılır')}</div>
              </div>
              <button onClick={() => setOpen(false)} aria-label={t('sprint.blocked.close', undefined, 'Kapat')} className="p-1.5 rounded-lg border border-line text-ink3 hover:text-ink"><X className="w-4 h-4" /></button>
            </div>
            <div className="flex-1 overflow-y-auto p-5">
              <BudgetSettings compact thenResume={unblock} onSaved={() => { setOpen(false); void load(); }} />
            </div>
          </aside>
        </div>
      )}
    </>
  );
};
