import React, { useCallback, useEffect, useState } from 'react';
import { Target, Plus, Check, X } from 'lucide-react';
import { useI18n } from '../i18n';
import { notify, promptDialog } from '../lib/dialog';

interface Goal {
  id: string; text: string; kind: 'screens' | 'free'; status: 'OPEN' | 'DONE' | 'DROPPED';
  progress: { done: number; total: number; open_tasks: number; checked: boolean };
}

/** Yönetici hedefleri: açık hedef varken kapsam dışı iş sprinte alınmaz ve mimar yeni iş açmaz; ilerleme ölçülür (ekran hedefi: ekran uyumu denetimi). */
export const GoalsStrip: React.FC = () => {
  const { t } = useI18n();
  const [goals, setGoals] = useState<Goal[]>([]);
  const load = useCallback(() => {
    fetch('/api/goals').then(r => r.json()).then(j => setGoals(j?.goals || [])).catch(() => undefined);
  }, []);
  useEffect(() => { load(); const i = setInterval(load, 15000); return () => clearInterval(i); }, [load]);

  const post = async (url: string, body: unknown) => {
    const r = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    const j = await r.json().catch(() => ({}));
    if (!r.ok) notify(j.error || t('goals.failed', undefined, 'İşlem yapılamadı'));
    load();
  };
  const add = async () => {
    const text = await promptDialog(t('goals.prompt', undefined, 'Hedefin nedir? (örn. Onaylı 13 ekran mockup\'a uygun uygulansın; test yazılmasın)'), '', { multiline: true });
    if (!text || !text.trim()) return;
    const screens = /ekran|screen/i.test(text);
    await post('/api/goals', { text: text.trim(), kind: screens ? 'screens' : 'free' });
  };
  const open = goals.filter(g => g.status === 'OPEN');
  const closed = goals.filter(g => g.status !== 'OPEN').slice(-2);

  return (
    <div className="mx-0 mb-2 rounded-xl border border-line bg-panel px-3 py-2 flex flex-wrap items-center gap-2 text-[12px]" role="region" aria-label={t('goals.title', undefined, 'Hedefler')}>
      <span className="inline-flex items-center gap-1.5 font-semibold text-ink"><Target className="w-3.5 h-3.5 text-ac" />{t('goals.title', undefined, 'Hedefler')}</span>
      {open.length === 0 && <span className="text-ink3">{t('goals.none', undefined, 'Açık hedef yok: sistem tüm backlog\'u çalıştırır. Hedef yazarsan yalnızca hedefe bağlı iş yapılır.')}</span>}
      {open.map(g => {
        const pct = g.progress.total ? Math.round((100 * g.progress.done) / g.progress.total) : 0;
        return (
          <span key={g.id} className="inline-flex items-center gap-2 rounded-lg border border-ac/30 bg-acd/40 px-2 py-1 max-w-[560px]">
            <span className="font-mono text-ink3">{g.id}</span>
            <span className="truncate text-ink" title={g.text}>{g.text}</span>
            {g.kind === 'screens' && (
              <span className="inline-flex items-center gap-1.5 shrink-0" title={t('goals.screensTitle', { done: g.progress.done, total: g.progress.total, open: g.progress.open_tasks }, '{done}/{total} ekran mockup\'a uygun (son denetim); {open} açık ekran görevi')}>
                <span className="w-16 h-1.5 bg-sunk rounded-full overflow-hidden border border-line"><span className="block h-full bg-ok" style={{ width: `${pct}%` }} /></span>
                <span className="font-mono text-ink2">{g.progress.checked ? `${g.progress.done}/${g.progress.total}` : t('goals.notChecked', undefined, 'denetlenmedi')}</span>
              </span>
            )}
            <button type="button" onClick={() => post(`/api/goals/${g.id}/status`, { status: 'DONE' })} className="text-ok hover:opacity-80" title={t('goals.done', undefined, 'Tamamlandı say')} aria-label={t('goals.done', undefined, 'Tamamlandı say')}><Check className="w-3.5 h-3.5" /></button>
            <button type="button" onClick={() => post(`/api/goals/${g.id}/status`, { status: 'DROPPED' })} className="text-ink3 hover:text-err" title={t('goals.drop', undefined, 'Vazgeç')} aria-label={t('goals.drop', undefined, 'Vazgeç')}><X className="w-3.5 h-3.5" /></button>
          </span>
        );
      })}
      {closed.map(g => <span key={g.id} className="text-ink3 line-through truncate max-w-[220px]" title={g.text}>{g.id} · {g.text}</span>)}
      <button type="button" onClick={add} className="ml-auto inline-flex items-center gap-1 px-2 py-1 rounded-lg border border-line text-ink2 hover:text-ink hover:border-line2">
        <Plus className="w-3.5 h-3.5" />{t('goals.add', undefined, 'Hedef ekle')}
      </button>
    </div>
  );
};
