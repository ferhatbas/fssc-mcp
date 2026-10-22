import React, { useMemo, useState } from 'react';
import { api } from '../config';
import { TestCase, TestResultValue } from '../types/telemetry';
import { useI18n } from '../i18n';

/** G7: test case listesi, süzgeçler, ayrıntı (adımlar, beklenen sonuç, geçmiş), elle sonuç girişi, durum/karantina ve yeni case formu. */
interface Props {
  cases: TestCase[];
  onChanged: () => void;
}

export const RESULT_STYLE: Record<string, string> = {
  PASS: 'bg-okd text-ok border-ok/40',
  FAIL: 'bg-errd text-err border-err/40',
  BLOCKED: 'bg-sunk text-warn border-warn/40',
  SKIP: 'bg-sunk text-ink3 border-line',
};

const inputCls = 'bg-panel border border-line2 rounded-lg px-2 py-1 text-xs text-ink placeholder-ink3 focus:border-ac focus:outline-none';
const CASE_TYPES = ['unit', 'integration', 'e2e', 'security', 'performance', 'exploratory'];

export const ResultBadge: React.FC<{ result?: string | null }> = ({ result }) => (
  <span className={`px-1.5 py-0.5 rounded border text-[10px] font-mono ${RESULT_STYLE[result || 'SKIP'] || RESULT_STYLE.SKIP}`}>{result || '—'}</span>
);

async function send(method: string, path: string, body?: unknown): Promise<any> {
  const res = await fetch(api(path), { method, headers: { 'Content-Type': 'application/json' }, body: body === undefined ? undefined : JSON.stringify(body) });
  const j = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(j.error || `HTTP ${res.status}`);
  return j;
}

const emptyForm = { title: '', type: 'integration', priority: 'P1', ac_refs: '', steps: '', expected: '', automation: 'MANUAL', labels: '' };

export const TestCasesPanel: React.FC<Props> = ({ cases, onChanged }) => {
  const { t } = useI18n();
  const [q, setQ] = useState('');
  const [status, setStatus] = useState('');
  const [type, setType] = useState('');
  const [result, setResult] = useState('');
  const [open, setOpen] = useState<string | null>(null);
  const [note, setNote] = useState('');
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [showNew, setShowNew] = useState(false);
  const [form, setForm] = useState(emptyForm);

  const shown = useMemo(() => cases.filter(c =>
    (!q || `${c.id} ${c.title}`.toLowerCase().includes(q.toLowerCase())) && (!status || c.status === status) && (!type || c.type === type) &&
    (!result || (c.last_result?.result || 'NONE') === result)), [cases, q, status, type, result]);

  const act = async (fn: () => Promise<string>) => {
    setMsg(null);
    try {
      setMsg({ ok: true, text: await fn() });
      onChanged();
    } catch (e: any) {
      setMsg({ ok: false, text: e?.message || t('sprint.cases.actionFailed', undefined, 'İşlem başarısız.') });
    }
  };

  const setResultFor = (c: TestCase, value: TestResultValue) => act(async () => {
    const j = await send('POST', `/api/testing/cases/${c.id}/result`, { result: value, note });
    setNote('');
    return `✓ ${c.id}: ${value}` + (j.run?.bugs?.length ? t('sprint.cases.bugOpened', { bugs: j.run.bugs.join(', ') }, ' · BUG açıldı: {bugs}') : '');
  });

  const patch = (c: TestCase, body: Record<string, unknown>, text: string) => act(async () => { await send('PATCH', `/api/testing/cases/${c.id}`, body); return `✓ ${c.id}: ${text}`; });

  const create = () => act(async () => {
    const j = await send('POST', '/api/testing/cases', {
      title: form.title, type: form.type, priority: form.priority, ac_refs: form.ac_refs.split(/[,\s]+/).filter(Boolean), steps: form.steps, expected: form.expected,
      automation: form.automation.trim() || 'MANUAL', labels: form.labels,
    });
    setForm(emptyForm);
    setShowNew(false);
    return t('sprint.cases.created', { id: j.case.id }, '✓ {id} oluşturuldu (taslak; hazır yapınca koşulara girer).');
  });

  return (
    <div className="space-y-3" data-testid="test-cases-panel">
      <div className="flex flex-wrap items-center gap-2">
        <input value={q} onChange={e => setQ(e.target.value)} placeholder={t('sprint.cases.search', undefined, 'Ara (TC-3, başlık)…')} className={`${inputCls} w-44`} />
        <select value={status} onChange={e => setStatus(e.target.value)} className={`${inputCls} font-mono`}>
          <option value="">{t('sprint.cases.statusAll', undefined, 'durum: hepsi')}</option><option value="DRAFT">DRAFT</option><option value="READY">READY</option><option value="DEPRECATED">DEPRECATED</option>
        </select>
        <select value={type} onChange={e => setType(e.target.value)} className={`${inputCls} font-mono`}>
          <option value="">{t('sprint.cases.typeAll', undefined, 'tür: hepsi')}</option>{CASE_TYPES.map(ct => <option key={ct} value={ct}>{ct}</option>)}
        </select>
        <select value={result} onChange={e => setResult(e.target.value)} className={`${inputCls} font-mono`}>
          <option value="">{t('sprint.cases.resultAll', undefined, 'sonuç: hepsi')}</option><option value="PASS">PASS</option><option value="FAIL">FAIL</option><option value="BLOCKED">BLOCKED</option><option value="NONE">{t('sprint.cases.notRun', undefined, 'koşmadı')}</option>
        </select>
        <span className="text-[11px] text-ink3">{t('sprint.cases.count', { shown: shown.length, total: cases.length }, '{shown}/{total} case')}</span>
        <button type="button" onClick={() => setShowNew(v => !v)} className="ml-auto px-2.5 py-1 rounded-lg border border-ac/40 bg-acd text-ac text-[11px] font-medium hover:opacity-90">
          {showNew ? t('sprint.cases.discard', undefined, 'Vazgeç') : t('sprint.cases.newCase', undefined, '+ Yeni case')}
        </button>
      </div>

      {showNew && (
        <div className="rounded-xl border border-line bg-panel/60 p-3 space-y-2">
          <div className="grid grid-cols-1 md:grid-cols-4 gap-2">
            <input className={`${inputCls} md:col-span-2`} placeholder={t('sprint.cases.titlePh', undefined, 'Başlık')} value={form.title} onChange={e => setForm({ ...form, title: e.target.value })} />
            <select className={`${inputCls} font-mono`} value={form.type} onChange={e => setForm({ ...form, type: e.target.value })}>{CASE_TYPES.map(ct => <option key={ct} value={ct}>{ct}</option>)}</select>
            <select className={`${inputCls} font-mono`} value={form.priority} onChange={e => setForm({ ...form, priority: e.target.value })}><option>P0</option><option>P1</option><option>P2</option></select>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-2">
            <input className={`${inputCls} font-mono`} placeholder={t('sprint.cases.acPh', undefined, 'Kabul kriterleri: AC-1, AC-2')} value={form.ac_refs} onChange={e => setForm({ ...form, ac_refs: e.target.value })} />
            <input className={`${inputCls} font-mono`} placeholder={t('sprint.cases.automationPh', undefined, 'MANUAL | AUTOMATED:test_adı')} value={form.automation} onChange={e => setForm({ ...form, automation: e.target.value })} />
            <input className={`${inputCls} font-mono`} placeholder={t('sprint.cases.labelsPh', undefined, 'Etiketler: regression, smoke')} value={form.labels} onChange={e => setForm({ ...form, labels: e.target.value })} />
          </div>
          <textarea className={`${inputCls} w-full`} rows={3} placeholder={t('sprint.cases.stepsPh', undefined, 'Adımlar (her satır bir adım)')} value={form.steps} onChange={e => setForm({ ...form, steps: e.target.value })} />
          <textarea className={`${inputCls} w-full`} rows={2} placeholder={t('sprint.cases.expectedPh', undefined, 'Beklenen sonuç')} value={form.expected} onChange={e => setForm({ ...form, expected: e.target.value })} />
          <button type="button" onClick={create} className="px-3 py-1.5 rounded-lg bg-ac text-onac text-xs font-semibold hover:opacity-90">{t('sprint.cases.create', undefined, "Case'i oluştur")}</button>
        </div>
      )}

      {msg && <p className={`text-[11px] ${msg.ok ? 'text-ok' : 'text-err'}`}>{msg.text}</p>}

      <div className="rounded-xl border border-line overflow-hidden">
        <table className="w-full text-xs">
          <thead className="bg-sunk text-ink3 text-[10px] uppercase tracking-wider">
            <tr><th className="text-left px-2 py-1.5">Case</th><th className="text-left px-2">{t('sprint.cases.colType', undefined, 'Tür')}</th><th className="text-left px-2">{t('sprint.cases.colPriority', undefined, 'Öncelik')}</th><th className="text-left px-2">{t('sprint.cases.colAutomation', undefined, 'Otomasyon')}</th>
              <th className="text-left px-2">{t('sprint.cases.colStatus', undefined, 'Durum')}</th><th className="text-left px-2">{t('sprint.cases.colCriterion', undefined, 'Kriter')}</th><th className="text-left px-2">{t('sprint.cases.colResult', undefined, 'Sonuç')}</th></tr>
          </thead>
          <tbody>
            {shown.length === 0 && <tr><td colSpan={7} className="px-3 py-6 text-center text-ink3">{t('sprint.cases.empty', undefined, 'Test case yok. QA sprint başında kabul kriterlerinden üretir; ya da elle ekleyebilirsin.')}</td></tr>}
            {shown.map(c => (
              <React.Fragment key={c.id}>
                <tr className={`border-t border-line cursor-pointer hover:bg-sunk/60 ${open === c.id ? 'bg-sunk/60' : ''}`} onClick={() => setOpen(open === c.id ? null : c.id)}>
                  <td className="px-2 py-1.5"><span className="font-mono font-bold text-ink">{c.id}</span> <span className="text-ink2">{c.title}</span>
                    {c.quarantined && <span className="ml-1.5 text-[9px] px-1 rounded border border-warn/40 text-warn">{t('sprint.cases.quarantine', undefined, 'karantina')}</span>}
                    {c.open_bug && <span className="ml-1.5 text-[9px] px-1 rounded border border-err/40 text-err">{c.open_bug}</span>}</td>
                  <td className="px-2 font-mono text-ink3">{c.type}</td><td className="px-2 font-mono text-ink3">{c.priority}</td>
                  <td className="px-2 font-mono text-ink3 truncate max-w-[10rem]" title={c.automation}>{c.automation === 'MANUAL' ? t('sprint.cases.manual', undefined, 'elle') : c.automation.replace('AUTOMATED:', '⚙ ')}</td>
                  <td className="px-2 font-mono text-ink3">{c.status}</td><td className="px-2 font-mono text-ink3">{c.ac_refs.join(' ') || '—'}</td>
                  <td className="px-2"><ResultBadge result={c.last_result?.result} /></td>
                </tr>
                {open === c.id && (
                  <tr className="border-t border-line bg-sunk/40">
                    <td colSpan={7} className="px-4 py-3 space-y-2">
                      {c.precondition && <p className="text-ink3"><b className="text-ink2">{t('sprint.cases.precondition', undefined, 'Ön koşul:')}</b> {c.precondition}</p>}
                      <ol className="list-decimal pl-5 text-ink2 space-y-0.5">{c.steps.map((s, i) => <li key={i}>{s}</li>)}</ol>
                      <p className="text-ink2"><b>{t('sprint.cases.expected', undefined, 'Beklenen:')}</b> {c.expected}</p>
                      {c.file && <p className="text-[10px] font-mono text-ink3">{c.file}{c.issue_id ? ` · ${c.issue_id}` : ''}</p>}
                      {c.last_result?.message && <p className="text-[11px] text-ink3">{t('sprint.cases.lastResult', { run: c.last_result.run, msg: c.last_result.message }, 'Son sonuç ({run}): {msg}')}</p>}
                      {(c.history || []).length > 0 && (
                        <div className="flex items-center gap-1" title={t('sprint.cases.recentResults', undefined, 'son sonuçlar')}>{(c.history || []).map((h, i) => <ResultBadge key={i} result={h.result} />)}</div>
                      )}
                      <div className="flex flex-wrap items-center gap-2 pt-1">
                        <input value={note} onChange={e => setNote(e.target.value)} placeholder={t('sprint.cases.notePh', undefined, 'Sonuç notu')} className={`${inputCls} w-44`} />
                        {c.status === 'READY' && (['PASS', 'FAIL', 'BLOCKED'] as TestResultValue[]).map(r => (
                          <button key={r} type="button" onClick={() => setResultFor(c, r)} className={`px-2 py-1 rounded border text-[11px] font-mono hover:opacity-90 ${RESULT_STYLE[r]}`}>{r}</button>
                        ))}
                        {c.status === 'DRAFT' && <button type="button" onClick={() => patch(c, { status: 'READY' }, t('sprint.cases.msgReady', undefined, 'hazır'))} className="px-2 py-1 rounded border border-ac/40 bg-acd text-ac text-[11px]">{t('sprint.cases.makeReady', undefined, 'Hazır yap')}</button>}
                        {c.status !== 'DEPRECATED' && <button type="button" onClick={() => patch(c, { status: 'DEPRECATED' }, t('sprint.cases.msgDeprecated', undefined, 'kullanımdan kaldırıldı'))} className="px-2 py-1 rounded border border-line text-ink3 text-[11px]">{t('sprint.cases.deprecate', undefined, 'Kullanımdan kaldır')}</button>}
                        {c.quarantined && <button type="button" onClick={() => patch(c, { quarantined: false }, t('sprint.cases.msgUnquarantined', undefined, 'karantinadan çıktı'))} className="px-2 py-1 rounded border border-warn/40 text-warn text-[11px]">{t('sprint.cases.unquarantine', undefined, 'Karantinayı kaldır')}</button>}
                        <button type="button" onClick={() => patch(c, { labels: c.labels.includes('regression') ? c.labels.filter(l => l !== 'regression') : [...c.labels, 'regression'] }, t('sprint.cases.msgRegressionLabel', undefined, 'regresyon etiketi değişti'))}
                          className="px-2 py-1 rounded border border-line text-ink3 text-[11px]">{c.labels.includes('regression') ? t('sprint.cases.removeRegression', undefined, 'Regresyondan çıkar') : t('sprint.cases.addRegression', undefined, 'Regresyona al')}</button>
                      </div>
                    </td>
                  </tr>
                )}
              </React.Fragment>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
};
