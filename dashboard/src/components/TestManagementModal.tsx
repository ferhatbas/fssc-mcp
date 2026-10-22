import React, { useCallback, useEffect, useState } from 'react';
import { X, FlaskConical, RefreshCw } from 'lucide-react';
import { api } from '../config';
import { E2EScenario, TestCase, TestMatrix, TestRun, TestingConfig, TestingSummary } from '../types/telemetry';
import { ResultBadge, TestCasesPanel } from './TestCasesPanel';
import { E2EScenarioEditor } from './E2EScenarioEditor';
import { useI18n } from '../i18n';

/** G7: Test Yönetimi — özet/kapsama, case'ler, test run'lar, izlenebilirlik matrisi, E2E senaryo editörü, test planı (server/testing.py). */
interface Props {
  isOpen: boolean;
  onClose: () => void;
  /** `TESTING_UPDATED` olayında artar: ekran yeniden yüklenir. */
  version?: number;
}

type Tab = 'SUMMARY' | 'CASES' | 'RUNS' | 'MATRIX' | 'SCENARIOS' | 'PLAN';
// yedek metinler; çeviri sprint.test.tab.<ANAHTAR>
const TABS: { key: Tab; label: string }[] = [
  { key: 'SUMMARY', label: 'Özet' }, { key: 'CASES', label: "Case'ler" }, { key: 'RUNS', label: 'Çalıştırmalar' },
  { key: 'MATRIX', label: 'İzlenebilirlik' }, { key: 'SCENARIOS', label: 'E2E senaryoları' }, { key: 'PLAN', label: 'Test planı' },
];
const STATE_STYLE: Record<string, string> = {
  COVERED: 'bg-okd text-ok border-ok/40', FAILING: 'bg-errd text-err border-err/40', UNTESTED: 'bg-sunk text-warn border-warn/40', NO_CASE: 'bg-sunk text-ink3 border-line',
};
// yedek metinler; çeviri sprint.test.state.<KOD>
const STATE_LABEL: Record<string, string> = { COVERED: 'kapsandı', FAILING: 'başarısız', UNTESTED: 'koşmadı', NO_CASE: 'case yok' };

const getJson = async <T,>(path: string): Promise<T | null> => {
  try {
    const res = await fetch(api(path));
    return res.ok ? ((await res.json()) as T) : null;
  } catch {
    return null;
  }
};

const Card: React.FC<{ title: string; value: React.ReactNode; hint?: string; tone?: string }> = ({ title, value, hint, tone }) => (
  <div className="rounded-xl border border-line bg-sunk/60 p-3">
    <p className="text-[10px] uppercase tracking-wider text-ink3">{title}</p>
    <p className={`text-xl font-bold ${tone || 'text-ink'}`}>{value}</p>
    {hint && <p className="text-[10px] text-ink3 mt-0.5">{hint}</p>}
  </div>
);

export const TestManagementModal: React.FC<Props> = ({ isOpen, onClose, version }) => {
  const { t } = useI18n();
  const [tab, setTab] = useState<Tab>('SUMMARY');
  const [summary, setSummary] = useState<TestingSummary | null>(null);
  const [cases, setCases] = useState<TestCase[]>([]);
  const [runs, setRuns] = useState<TestRun[]>([]);
  const [matrix, setMatrix] = useState<TestMatrix | null>(null);
  const [scenarios, setScenarios] = useState<E2EScenario[]>([]);
  const [config, setConfig] = useState<TestingConfig | null>(null);
  const [plan, setPlan] = useState<{ sprint: number; markdown: string; file: string } | null>(null);
  const [planN, setPlanN] = useState(1);
  const [openRun, setOpenRun] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [available, setAvailable] = useState(true);
  const [msg, setMsg] = useState('');

  const reload = useCallback(async () => {
    setLoading(true);
    const [s, c, r, m, sc, cfg] = await Promise.all([
      getJson<{ summary: TestingSummary }>('/api/testing/summary'), getJson<{ cases: TestCase[] }>('/api/testing/cases'), getJson<{ runs: TestRun[] }>('/api/testing/runs'),
      getJson<{ matrix: TestMatrix }>('/api/testing/matrix'), getJson<{ scenarios: E2EScenario[] }>('/api/testing/scenarios'), getJson<{ config: TestingConfig }>('/api/testing/config'),
    ]);
    setAvailable(!!s);                                   // eski sunucuda uçlar yoktur
    setSummary(s?.summary ?? null);
    setCases(c?.cases ?? []);
    setRuns(r?.runs ?? []);
    setMatrix(m?.matrix ?? null);
    setScenarios(sc?.scenarios ?? []);
    setConfig(cfg?.config ?? null);
    setLoading(false);
  }, []);

  useEffect(() => { if (isOpen) reload(); }, [isOpen, reload, version]);

  const loadPlan = useCallback(async (n: number) => {
    const p = await getJson<{ sprint: number; markdown: string; file: string }>(`/api/testing/plan/${n}`);
    setPlan(p);
  }, []);
  useEffect(() => { if (isOpen && tab === 'PLAN') loadPlan(planN); }, [isOpen, tab, planN, loadPlan]);

  if (!isOpen) return null;

  const saveConfig = async (patch: Partial<TestingConfig>) => {
    const res = await fetch(api('/api/testing/config'), { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(patch) });
    const j = await res.json().catch(() => ({}));
    setMsg(res.ok ? t('sprint.test.settingSaved', undefined, '✓ Ayar kaydedildi.') : j.error || t('sprint.test.settingFailed', undefined, 'Ayar kaydedilemedi.'));
    if (res.ok) { setConfig(j.config); reload(); }
  };

  const writePlan = async () => {
    const res = await fetch(api(`/api/testing/plan/${planN}/write`), { method: 'POST' });
    setMsg(res.ok ? t('sprint.test.planWritten', { file: (await res.json()).file }, '✓ Plan yazıldı: {file}') : t('sprint.test.planWriteFailed', undefined, 'Plan yazılamadı (proje klasörü yok mu?).'));
  };

  const gate = summary?.regression;
  const cov = summary?.coverage_pct;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-md">
      <div className="bg-panel border border-line2 rounded-2xl w-full max-w-5xl max-h-[94vh] flex flex-col shadow-2xl overflow-hidden" data-testid="test-management-modal">
        <div className="px-6 py-3 bg-sunk border-b border-line flex items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-xl bg-acd border border-ac/40 flex items-center justify-center"><FlaskConical className="w-5 h-5 text-ac" /></div>
            <div>
              <h3 className="text-base font-bold text-ink">{t('sprint.test.title', undefined, 'Test Yönetimi')}</h3>
              <p className="text-xs text-ink3">{t('sprint.test.subtitle', undefined, "Test case'leri, çalıştırmalar, izlenebilirlik matrisi ve E2E senaryoları (QA'nın ürettiği ve sunucunun koştuğu gerçek kanıt)")}</p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            {summary && (
              <>
                <span className={`px-2 py-0.5 rounded-full border text-[11px] font-mono ${cov !== null && cov !== undefined && cov >= summary.target_pct ? 'border-ok/40 text-ok' : 'border-warn/40 text-warn'}`}
                  title={t('sprint.test.targetPct', { n: summary.target_pct }, 'hedef %{n}')}>{t('sprint.test.coverage', undefined, 'kapsama')} {cov === null || cov === undefined ? '—' : `%${cov}`}</span>
                <span className={`px-2 py-0.5 rounded-full border text-[11px] font-mono ${gate?.ok ? 'border-ok/40 text-ok' : 'border-err/40 text-err'}`} title={t('sprint.test.regressionTip', undefined, 'regresyon kümesi geçti mi')}>
                  {t('sprint.test.regression', undefined, 'regresyon')} {gate?.ok ? t('sprint.test.passed', undefined, 'geçti') : t('sprint.test.failedCaps', undefined, 'KALDI')}
                </span>
              </>
            )}
            <button type="button" onClick={reload} className="p-1.5 rounded-lg border border-line text-ink3 hover:text-ink" title={t('sprint.test.refresh', undefined, 'Yenile')}><RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} /></button>
            <button type="button" onClick={onClose} className="p-1.5 rounded-lg text-ink3 hover:text-ink" aria-label={t('sprint.test.close', undefined, 'Kapat')}><X className="w-5 h-5" /></button>
          </div>
        </div>

        <div className="px-6 pt-3 flex flex-wrap gap-1 border-b border-line">
          {TABS.map(tb => (
            <button key={tb.key} type="button" onClick={() => setTab(tb.key)}
              className={`px-3 py-1.5 text-xs font-medium rounded-t-lg border border-b-0 transition ${tab === tb.key ? 'bg-panel text-ac border-line' : 'bg-sunk/60 text-ink3 border-transparent hover:text-ink'}`}>{t(`sprint.test.tab.${tb.key}`, undefined, tb.label)}</button>
          ))}
        </div>

        <div className="flex-1 overflow-y-auto p-6 space-y-4">
          {!available && (
            <p className="text-xs text-warn border border-warn/40 rounded-lg p-3">{t('sprint.test.unavailable', undefined, 'Sunucu test yönetimi uçlarını sunmuyor (eski kodla çalışıyor olabilir). Sunucuyu yeniden başlatınca bu ekran dolar.')}</p>
          )}
          {msg && <p className="text-[11px] text-ink2">{msg}</p>}

          {tab === 'SUMMARY' && summary && (
            <div className="space-y-4">
              <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                <Card title={t('sprint.test.acCoverage', undefined, 'Kabul kriteri kapsama')} value={cov === null || cov === undefined ? '—' : `%${cov}`} hint={t('sprint.test.targetPct', { n: summary.target_pct }, 'hedef %{n}')} tone={cov !== null && cov !== undefined && cov >= summary.target_pct ? 'text-ok' : 'text-warn'} />
                <Card title={t('sprint.test.testCase', undefined, 'Test case')} value={summary.cases} hint={t('sprint.test.caseBreakdown', { auto: summary.automated, manual: summary.manual, never: summary.never_run }, '{auto} otomatik · {manual} elle · {never} hiç koşmadı')} />
                <Card title={t('sprint.test.lastResults', undefined, 'Son sonuçlar')} value={<span className="text-sm font-mono"><span className="text-ok">{summary.results.PASS || 0}</span> / <span className="text-err">{summary.results.FAIL || 0}</span> / <span className="text-warn">{summary.results.BLOCKED || 0}</span></span>} hint="PASS / FAIL / BLOCKED" />
                <Card title={t('sprint.test.openBugsFlaky', undefined, 'Açık hata · kararsız')} value={`${summary.open_bugs} · ${summary.flaky}`} hint={t('sprint.test.bugsQuarantine', undefined, "case'ten açılan BUG · karantinadaki case")} tone={summary.open_bugs ? 'text-err' : 'text-ink'} />
              </div>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                <div className="rounded-xl border border-line p-3 space-y-1 text-xs">
                  <p className="font-bold text-ink uppercase tracking-wider text-[11px]">{t('sprint.test.regressionGate', undefined, 'Regresyon kapısı')}</p>
                  <p className={gate?.ok ? 'text-ok' : 'text-err'}>{gate?.ok ? t('sprint.test.gatePassed', undefined, 'Geçti') : t('sprint.test.gateFailed', undefined, 'Geçmedi')} · {t('sprint.test.setSize', { n: gate?.size ?? 0 }, 'küme {n} case')}</p>
                  {!!gate?.failing.length && <p className="text-err">{t('sprint.test.failing', undefined, 'Başarısız:')} {gate.failing.join(', ')}</p>}
                  {!!gate?.unexecuted.length && <p className="text-warn">{t('sprint.test.neverRunAuto', undefined, 'Hiç koşmayan otomatik:')} {gate.unexecuted.join(', ')}</p>}
                  {!!gate?.manual_pending?.length && <p className="text-ink3">{t('sprint.test.manualPending', undefined, 'Elle sonuç bekleyen:')} {gate.manual_pending.join(', ')}</p>}
                </div>
                <div className="rounded-xl border border-line p-3 space-y-1 text-xs">
                  <p className="font-bold text-ink uppercase tracking-wider text-[11px]">{t('sprint.test.uncoveredCriteria', undefined, 'Kapsanmayan kriterler')}</p>
                  <p className="text-ink2">{t('sprint.test.noCase', undefined, 'Case yok:')} {summary.uncovered.join(', ') || '—'}</p>
                  <p className="text-ink2">{t('sprint.test.failing', undefined, 'Başarısız:')} {summary.failing_acs.join(', ') || '—'}</p>
                  {summary.last_run && <p className="text-ink3 pt-1">{t('sprint.test.lastRun', { id: summary.last_run.id, source: summary.last_run.source, pass: summary.last_run.summary.pass, fail: summary.last_run.summary.fail }, 'Son run: {id} · {source} · {pass} PASS / {fail} FAIL')}</p>}
                </div>
              </div>
              {config && (
                <div className="rounded-xl border border-line p-3 text-xs space-y-2">
                  <p className="font-bold text-ink uppercase tracking-wider text-[11px]">{t('sprint.test.settings', undefined, 'Ayarlar')}</p>
                  <div className="flex flex-wrap items-center gap-4 text-ink2">
                    <label className="flex items-center gap-1.5">{t('sprint.test.coverageTarget', undefined, 'Kapsama hedefi %')}
                      <input type="number" min={0} max={100} defaultValue={config.coverage_target} onBlur={e => Number(e.target.value) !== config.coverage_target && saveConfig({ coverage_target: Number(e.target.value) })}
                        className="w-16 bg-panel border border-line2 rounded px-1.5 py-0.5 font-mono text-ink" /></label>
                    <label className="flex items-center gap-1.5">{t('sprint.test.perfThreshold', undefined, 'Performans p95 eşiği (ms)')}
                      <input type="number" min={1} defaultValue={config.perf_p95_ms} onBlur={e => Number(e.target.value) !== config.perf_p95_ms && saveConfig({ perf_p95_ms: Number(e.target.value) })}
                        className="w-20 bg-panel border border-line2 rounded px-1.5 py-0.5 font-mono text-ink" /></label>
                    <label className="flex items-center gap-1.5 cursor-pointer"><input type="checkbox" checked={config.design_task} onChange={e => saveConfig({ design_task: e.target.checked })} /> {t('sprint.test.designTask', undefined, 'QA test tasarım görevini sunucu ekler (sıkı DoD)')}</label>
                    <label className="flex items-center gap-1.5 cursor-pointer"><input type="checkbox" checked={config.auto_regression} onChange={e => saveConfig({ auto_regression: e.target.checked })} /> {t('sprint.test.autoRegression', undefined, "Geçen case'ler kapanışta regresyona girer")}</label>
                  </div>
                </div>
              )}
            </div>
          )}

          {tab === 'CASES' && <TestCasesPanel cases={cases} onChanged={reload} />}

          {tab === 'RUNS' && (
            <div className="space-y-2" data-testid="test-runs">
              {runs.length === 0 && <p className="text-xs text-ink3 border border-dashed border-line rounded-lg p-4">{t('sprint.test.noRuns', undefined, 'Henüz test run yok. QA ve E2E adımları doğrulamadan sonra run kaydeder.')}</p>}
              {runs.map(r => (
                <div key={r.id} className="rounded-xl border border-line bg-sunk/40">
                  <button type="button" onClick={() => setOpenRun(openRun === r.id ? null : r.id)} className="w-full flex flex-wrap items-center gap-3 px-3 py-2 text-xs text-left">
                    <span className="font-mono font-bold text-ink">{r.id}</span><span className="text-ink2">{r.title}</span>
                    <span className="font-mono text-ink3">{r.source}</span>
                    <span className="ml-auto font-mono"><span className="text-ok">{r.summary.pass}</span> / <span className="text-err">{r.summary.fail}</span> / <span className="text-warn">{r.summary.blocked}</span></span>
                    {r.bugs.length > 0 && <span className="text-[10px] px-1 rounded border border-err/40 text-err">BUG {r.bugs.join(', ')}</span>}
                  </button>
                  {openRun === r.id && (
                    <div className="border-t border-line px-3 py-2 space-y-1 text-xs">
                      {r.results.map(x => (
                        <div key={x.case} className="flex items-center gap-2"><ResultBadge result={x.result} /><span className="font-mono text-ink">{x.case}</span><span className="text-ink2 truncate">{x.title}</span>
                          {typeof x.evidence?.message === 'string' && x.evidence.message && <span className="text-ink3 truncate">— {x.evidence.message}</span>}</div>
                      ))}
                      {r.perf && <p className="text-[10px] font-mono text-ink3">{t('sprint.test.perfLine', { p50: String(r.perf.p50_ms), p95: String(r.perf.p95_ms), err: String(r.perf.errors) }, 'performans: p50 {p50} ms · p95 {p95} ms · hata {err}')}</p>}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}

          {tab === 'MATRIX' && matrix && (
            <div className="space-y-2" data-testid="traceability-matrix">
              <p className="text-xs text-ink3">{t('sprint.test.matrixSummary', { covered: matrix.covered, total: matrix.total, pct: matrix.coverage_pct ?? 0, target: matrix.target_pct }, "{covered}/{total} kabul kriteri kapsandı (%{pct}, hedef %{target}). Karantinadaki case'ler kapsamaya sayılmaz.")}</p>
              <div className="rounded-xl border border-line overflow-hidden">
                <table className="w-full text-xs">
                  <thead className="bg-sunk text-ink3 text-[10px] uppercase tracking-wider"><tr><th className="text-left px-2 py-1.5">{t('sprint.test.colCriterion', undefined, 'Kriter')}</th><th className="text-left px-2">{t('sprint.test.colStatus', undefined, 'Durum')}</th><th className="text-left px-2">{t('sprint.test.colCases', undefined, "Case'ler")}</th><th className="text-left px-2">{t('sprint.test.colMentioned', undefined, 'Anılan testler')}</th></tr></thead>
                  <tbody>
                    {matrix.rows.length === 0 && <tr><td colSpan={4} className="px-3 py-6 text-center text-ink3">{t('sprint.test.noCriteria', undefined, 'Kabul kriteri yok (PM şartnameden üretince dolar).')}</td></tr>}
                    {matrix.rows.map(row => (
                      <tr key={row.ac} className="border-t border-line align-top">
                        <td className="px-2 py-1.5"><span className="font-mono font-bold text-ink">{row.ac}</span><p className="text-ink3">{row.text}</p></td>
                        <td className="px-2 py-1.5"><span className={`px-1.5 py-0.5 rounded border text-[10px] font-mono ${STATE_STYLE[row.state]}`}>{STATE_LABEL[row.state] ? t(`sprint.test.state.${row.state}`, undefined, STATE_LABEL[row.state]) : row.state}</span></td>
                        <td className="px-2 py-1.5 space-y-0.5">{row.cases.length === 0 ? <span className="text-ink3">—</span> : row.cases.map(c => (
                          <div key={c.id} className="flex items-center gap-1.5"><ResultBadge result={c.result} /><span className="font-mono">{c.id}</span><span className="text-ink3 truncate">{c.title}</span>
                            {c.quarantined && <span className="text-[9px] text-warn">{t('sprint.test.quarantine', undefined, 'karantina')}</span>}</div>))}</td>
                        <td className="px-2 py-1.5 font-mono text-[10px] text-ink3">{row.tests_mentioned.join(', ') || '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {matrix.unlinked_cases.length > 0 && <p className="text-xs text-warn">{t('sprint.test.unlinked', undefined, "Kriter bağlantısı olmayan case'ler:")} {matrix.unlinked_cases.join(', ')}</p>}
            </div>
          )}

          {tab === 'SCENARIOS' && <E2EScenarioEditor scenarios={scenarios} onChanged={reload} />}

          {tab === 'PLAN' && (
            <div className="space-y-2" data-testid="test-plan">
              <div className="flex items-center gap-2 text-xs">
                <label className="text-ink3">Sprint</label>
                <input type="number" min={1} value={planN} onChange={e => setPlanN(Math.max(1, Number(e.target.value) || 1))} className="w-16 bg-panel border border-line2 rounded px-1.5 py-0.5 font-mono text-ink" />
                <button type="button" onClick={writePlan} className="px-2.5 py-1 rounded-lg border border-ac/40 bg-acd text-ac text-[11px]">{t('sprint.test.writeFile', undefined, 'Dosyaya yaz')}</button>
                {plan && <span className="font-mono text-[10px] text-ink3">{plan.file}</span>}
              </div>
              <pre className="rounded-xl border border-line bg-sunk/60 p-3 text-xs text-ink2 whitespace-pre-wrap font-mono">{plan?.markdown || t('sprint.test.planLoadFailed', undefined, 'Plan yüklenemedi.')}</pre>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
