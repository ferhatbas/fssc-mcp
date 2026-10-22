import React, { useCallback, useEffect, useState } from 'react';
import { api } from '../config';
import { useI18n } from '../i18n';

/** Sprint bütçe sınırları (autonomy.budget): etkin süre, token, adım, art arda başarısızlık, sprint sayısı. Sınır dolunca sprint BLOCKED olur; buradan artırılır. */
// label/unit/hint alanları çeviri anahtarıdır (render sırasında t() ile çözülür)
const FIELDS: { key: string; label: string; unit: string; min: number; max: number; hint: string }[] = [
  { key: 'max_active_min_per_sprint', label: 'project.budget.max_active_min_per_sprint', unit: 'project.budget.unit.min', min: 30, max: 5000, hint: 'project.budget.max_active_min_per_sprint.hint' },
  { key: 'max_steps_per_sprint', label: 'project.budget.max_steps_per_sprint', unit: 'project.budget.unit.step', min: 10, max: 500, hint: 'project.budget.max_steps_per_sprint.hint' },
  { key: 'max_tokens_per_sprint', label: 'project.budget.max_tokens_per_sprint', unit: 'project.budget.unit.token', min: 100000, max: 50000000, hint: 'project.budget.max_tokens_per_sprint.hint' },
  { key: 'max_tokens_per_task', label: 'project.budget.max_tokens_per_task', unit: 'project.budget.unit.token', min: 50000, max: 5000000, hint: 'project.budget.max_tokens_per_task.hint' },
  { key: 'max_consecutive_failed_steps', label: 'project.budget.max_consecutive_failed_steps', unit: 'project.budget.unit.step', min: 1, max: 30, hint: 'project.budget.max_consecutive_failed_steps.hint' },
  { key: 'stall_steps', label: 'project.budget.stall_steps', unit: 'project.budget.unit.step', min: 2, max: 50, hint: 'project.budget.stall_steps.hint' },
  { key: 'max_sprints', label: 'project.budget.max_sprints', unit: 'project.budget.unit.sprint', min: 1, max: 100, hint: 'project.budget.max_sprints.hint' },
  { key: 'warn_at_percent', label: 'project.budget.warn_at_percent', unit: 'project.budget.unit.percent', min: 10, max: 100, hint: 'project.budget.warn_at_percent.hint' },
];

export const BudgetSettings: React.FC<{ compact?: boolean; onSaved?: () => void; thenResume?: () => Promise<void>; layout?: 'grid' | 'drawer' }> = ({ compact, onSaved, thenResume, layout }) => {
  const { t } = useI18n();
  const [vals, setVals] = useState<Record<string, number> | null>(null);
  const [orig, setOrig] = useState<Record<string, number>>({});
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState('');

  const load = useCallback(async () => {
    try {
      const j = await fetch(api('/api/settings/autonomy')).then(r => r.json());
      const b = (j?.autonomy?.budget || {}) as Record<string, number>;
      setVals({ ...b });
      setOrig({ ...b });
    } catch { setMsg('⚠ ' + t('project.budget.loadFailed', undefined, 'Bütçe okunamadı')); }
  }, []);
  useEffect(() => { void load(); }, [load]);

  if (!vals) return <div className="text-xs text-ink3">{msg || t('project.budget.loading', undefined, 'Bütçe yükleniyor…')}</div>;
  const dirty = FIELDS.filter(f => Number(vals[f.key]) !== Number(orig[f.key]));
  const save = async () => {
    setBusy(true);
    try {
      const body: Record<string, number> = {};
      dirty.forEach(f => { body[f.key] = Math.min(f.max, Math.max(f.min, Number(vals[f.key]) || f.min)); });
      const r = await fetch(api('/api/settings/autonomy'), { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ budget: body }) });
      if (!r.ok) throw new Error((await r.json().catch(() => ({})))?.error || t('project.saveFailed', undefined, 'Kaydedilemedi'));
      setMsg(t('project.saved', undefined, 'Kaydedildi.'));
      await load();
      if (thenResume) await thenResume();
      onSaved?.();
    } catch (e) { setMsg(`⚠ ${(e as Error).message}`); } finally { setBusy(false); }
  };

  return (
    <div className="space-y-2">
      <div className={`grid gap-2 ${compact ? 'grid-cols-2' : 'grid-cols-1 sm:grid-cols-2'}`}>
        {FIELDS.map(f => (
          <label key={f.key} className="text-[11px] text-ink2" title={t(f.hint)}>
            <span className="block mb-0.5">{t(f.label)} <span className="text-ink3">({t(f.unit)})</span></span>
            <input
              type="number" min={f.min} max={f.max} value={vals[f.key] ?? ''}
              onChange={e => setVals({ ...vals, [f.key]: Number(e.target.value) })}
              className={`w-full bg-panel border rounded-lg px-2 py-1.5 text-ink font-mono shadow-xs focus:outline-none focus:ring-2 focus:ring-ac/40 focus:border-ac ${Number(vals[f.key]) !== Number(orig[f.key]) ? 'border-warn' : 'border-line2'}`}
            />
          </label>
        ))}
      </div>
      <div className="flex items-center gap-2">
        <button disabled={busy || (!dirty.length && !thenResume)} onClick={save} className="px-3 py-1 rounded-lg border border-ok/40 text-ok bg-okd/40 text-xs disabled:opacity-50 whitespace-nowrap">{thenResume ? t('project.budget.saveResume', undefined, 'Kaydet ve sürdür') : t('common.save', undefined, 'Kaydet')}</button>
        <span className="text-[10px] text-ink3">{dirty.length ? t('project.budget.changes', { n: dirty.length }, '{n} değişiklik') : t('project.budget.noChanges', undefined, 'Değişiklik yok')}</span>
        {msg && <span className={`text-[10px] font-mono ${msg.startsWith('⚠') ? 'text-err' : 'text-ink3'}`}>{msg}</span>}
      </div>
    </div>
  );
};
