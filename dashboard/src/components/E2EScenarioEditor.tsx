import React, { useState } from 'react';
import { confirmDialog } from '../lib/dialog';
import { api } from '../config';
import { E2EScenario } from '../types/telemetry';
import { useI18n } from '../i18n';

/** G7: E2E senaryo editörü (`e2e/scenarios/*.json`). Senaryo kod değildir; sıralı adımlardır ve sunucunun E2E_TESTER'ı aynı dosyayı koşar. */
interface Props {
  scenarios: E2EScenario[];
  onChanged: () => void;
}

const ACTIONS = ['goto', 'click', 'fill', 'expect_text', 'expect_selector', 'expect_url_contains'] as const;
type Action = typeof ACTIONS[number];
interface StepDraft { action: Action; a: string; b: string }
interface Draft { id: string; title: string; acRefs: string; steps: StepDraft[] }

const inputCls = 'bg-panel border border-line2 rounded-lg px-2 py-1 text-xs text-ink placeholder-ink3 focus:border-ac focus:outline-none';
const HINT_TR: Record<Action, string> = {
  goto: 'yol ya da adres (/giris)', click: 'seçici (#giris)', fill: 'seçici', expect_text: 'sayfada görünmesi gereken metin',
  expect_selector: 'bulunması gereken seçici', expect_url_contains: 'adres şunu içermeli',
};

const toDraft = (s: E2EScenario): Draft => ({
  id: s.id, title: s.title || '', acRefs: (s.ac_refs || []).join(', '),
  steps: (s.steps || []).map(st => {
    const action = (ACTIONS.find(a => a in st) || 'goto') as Action;
    const v = st[action];
    return action === 'fill' && Array.isArray(v) ? { action, a: String(v[0] ?? ''), b: String(v[1] ?? '') } : { action, a: String(v ?? ''), b: '' };
  }),
});

const toScenario = (d: Draft) => ({
  id: d.id.trim(), title: d.title.trim(), ac_refs: d.acRefs.split(/[,\s]+/).filter(Boolean),
  steps: d.steps.map(s => (s.action === 'fill' ? { fill: [s.a, s.b] } : { [s.action]: s.a })),
});

export const E2EScenarioEditor: React.FC<Props> = ({ scenarios, onChanged }) => {
  const { t } = useI18n();
  const [draft, setDraft] = useState<Draft | null>(null);
  const [isNew, setIsNew] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  const call = async (fn: () => Promise<string>) => {
    setMsg(null);
    try {
      setMsg({ ok: true, text: await fn() });
      onChanged();
    } catch (e: any) {
      setMsg({ ok: false, text: e?.message || t('run.e2e.opFailed', undefined, 'İşlem başarısız.') });
    }
  };

  const save = () => draft && call(async () => {
    const sc = toScenario(draft);
    const res = await fetch(api(`/api/testing/scenarios/${encodeURIComponent(sc.id)}`), { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(sc) });
    const j = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(j.error || `HTTP ${res.status}`);
    setDraft(null);
    return t('run.e2e.saved', { id: sc.id }, `✓ ${sc.id} kaydedildi (e2e/scenarios/${sc.id}.json). Sunucunun E2E adımı bunu koşar.`);
  });

  const remove = async (id: string) => await confirmDialog(t('run.e2e.confirmDelete', { id }, `${id} senaryosu silinsin mi?`)) && call(async () => {
    const res = await fetch(api(`/api/testing/scenarios/${encodeURIComponent(id)}`), { method: 'DELETE' });
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).error || `HTTP ${res.status}`);
    if (draft?.id === id) setDraft(null);
    return t('run.e2e.deleted', { id }, `✓ ${id} silindi.`);
  });

  const setStep = (i: number, patch: Partial<StepDraft>) => draft && setDraft({ ...draft, steps: draft.steps.map((s, k) => (k === i ? { ...s, ...patch } : s)) });

  return (
    <div className="space-y-3" data-testid="e2e-scenario-editor">
      <div className="flex items-center justify-between">
        <p className="text-[11px] text-ink3">{t('run.e2e.intro', undefined, 'Senaryolar kabul kriterine bağlanır; geçen senaryo kriterin kanıtıdır. Seçici sözleşmesi: kararlı')} <code className="font-mono">data-testid</code> {t('run.e2e.introUse', undefined, 'kullan.')}</p>
        <button type="button" onClick={() => { setDraft({ id: '', title: '', acRefs: '', steps: [{ action: 'goto', a: '/', b: '' }] }); setIsNew(true); }}
          className="px-2.5 py-1 rounded-lg border border-ac/40 bg-acd text-ac text-[11px] font-medium hover:opacity-90">{t('run.e2e.newScenario', undefined, '+ Yeni senaryo')}</button>
      </div>
      {msg && <p className={`text-[11px] ${msg.ok ? 'text-ok' : 'text-err'}`}>{msg.text}</p>}

      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
        <div className="space-y-1.5">
          {scenarios.length === 0 && <p className="text-xs text-ink3 border border-dashed border-line rounded-lg p-3">{t('run.e2e.empty', undefined, 'Senaryo yok. QA kabul kriterlerinden yazar ya da buradan ekleyebilirsin.')}</p>}
          {scenarios.map(s => (
            <div key={s.id} className={`rounded-lg border p-2 text-xs ${draft?.id === s.id && !isNew ? 'border-ac/60 bg-acd/30' : 'border-line bg-sunk/40'}`}>
              <div className="flex items-center justify-between gap-2">
                <button type="button" className="font-mono font-bold text-ink text-left truncate" onClick={() => { setDraft(toDraft(s)); setIsNew(false); }}>{s.id}</button>
                <button type="button" onClick={() => remove(s.id)} className="text-[10px] text-err hover:underline">{t('run.e2e.del', undefined, 'sil')}</button>
              </div>
              <p className="text-ink3 truncate">{s.title || '—'}</p>
              <p className="font-mono text-[10px] text-ink3">{(s.ac_refs || []).join(' ') || t('run.e2e.noCriteria', undefined, 'kriter yok')} · {t('run.e2e.stepsN', { n: (s.steps || []).length }, `${(s.steps || []).length} adım`)}</p>
              {s.invalid && <p className="text-[10px] text-err">{t('run.e2e.invalid', undefined, 'geçersiz:')} {s.invalid}</p>}
            </div>
          ))}
        </div>

        <div className="md:col-span-2">
          {draft ? (
            <div className="rounded-xl border border-line bg-panel/60 p-3 space-y-2">
              <div className="grid grid-cols-1 md:grid-cols-3 gap-2">
                <input className={`${inputCls} font-mono`} placeholder={t('run.e2e.phId', undefined, 'Kimlik (E2E-AC1-giris)')} value={draft.id} disabled={!isNew} onChange={e => setDraft({ ...draft, id: e.target.value })} />
                <input className={inputCls} placeholder={t('run.e2e.phTitle', undefined, 'Başlık')} value={draft.title} onChange={e => setDraft({ ...draft, title: e.target.value })} />
                <input className={`${inputCls} font-mono`} placeholder={t('run.e2e.phCriteria', undefined, 'Kriterler: AC-1, AC-2')} value={draft.acRefs} onChange={e => setDraft({ ...draft, acRefs: e.target.value })} />
              </div>
              <div className="space-y-1.5">
                {draft.steps.map((s, i) => (
                  <div key={i} className="flex items-center gap-1.5">
                    <span className="w-5 text-right text-[10px] text-ink3 font-mono">{i + 1}</span>
                    <select className={`${inputCls} font-mono`} value={s.action} onChange={e => setStep(i, { action: e.target.value as Action })}>{ACTIONS.map(a => <option key={a} value={a}>{a}</option>)}</select>
                    <input className={`${inputCls} flex-1 font-mono`} placeholder={t(`run.e2e.hint.${s.action}`, undefined, HINT_TR[s.action])} value={s.a} onChange={e => setStep(i, { a: e.target.value })} />
                    {s.action === 'fill' && <input className={`${inputCls} w-40 font-mono`} placeholder={t('run.e2e.phValue', undefined, 'değer')} value={s.b} onChange={e => setStep(i, { b: e.target.value })} />}
                    <button type="button" className="text-[11px] text-ink3 hover:text-err" onClick={() => setDraft({ ...draft, steps: draft.steps.filter((_, k) => k !== i) })}>✕</button>
                  </div>
                ))}
                <button type="button" className="text-[11px] text-ac hover:underline" onClick={() => setDraft({ ...draft, steps: [...draft.steps, { action: 'click', a: '', b: '' }] })}>{t('run.e2e.addStep', undefined, '+ adım ekle')}</button>
              </div>
              <div className="flex gap-2 pt-1">
                <button type="button" onClick={save} className="px-3 py-1.5 rounded-lg bg-ac text-onac text-xs font-semibold hover:opacity-90">{t('run.e2e.save', undefined, 'Kaydet')}</button>
                <button type="button" onClick={() => setDraft(null)} className="px-3 py-1.5 rounded-lg border border-line text-ink3 text-xs">{t('run.e2e.close', undefined, 'Kapat')}</button>
              </div>
            </div>
          ) : <p className="text-xs text-ink3 p-3">{t('run.e2e.pick', undefined, 'Soldan bir senaryo seç ya da yeni bir tane oluştur.')}</p>}
        </div>
      </div>
    </div>
  );
};
