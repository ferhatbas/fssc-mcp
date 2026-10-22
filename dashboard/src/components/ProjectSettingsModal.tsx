import React, { useCallback, useEffect, useState } from 'react';
import { X } from 'lucide-react';
import { api } from '../config';
import { BudgetSettings } from './BudgetSettings';
import { SkillSettings } from './SkillSettings';
import { useI18n } from '../i18n';

type Field = { key: string; label: string; hint: string; kind: 'num' | 'bool' | 'select'; min?: number; max?: number; options?: [string, string][] };
type Auto = { strict_dod: boolean; question_timeout_s: number | null };

/** Proje ayarları: sprint planlama parametreleri (sprint.*), otonomi anahtarları ve bütçe sınırları (autonomy.budget) tek yerde. */
// label/hint/options etiketleri çeviri anahtarıdır (render sırasında t() ile çözülür)
const SPRINT_FIELDS: Field[] = [
  { key: 'enabled', label: 'project.sprint.enabled', hint: 'project.sprint.enabled.hint', kind: 'bool' },
  { key: 'auto_chain', label: 'project.sprint.auto_chain', hint: 'project.sprint.auto_chain.hint', kind: 'bool' },
  { key: 'commit_approval', label: 'project.sprint.commit_approval', hint: 'project.sprint.commit_approval.hint', kind: 'select',
    options: [['auto', 'project.sprint.commit.auto'], ['manual', 'project.sprint.commit.manual'], ['timeout_default', 'project.sprint.commit.timeout_default']] },
  { key: 'max_tasks', label: 'project.sprint.max_tasks', hint: 'project.sprint.max_tasks.hint', kind: 'num', min: 1, max: 50 },
  { key: 'min_tasks', label: 'project.sprint.min_tasks', hint: 'project.sprint.min_tasks.hint', kind: 'num', min: 0, max: 50 },
  { key: 'no_tests', label: 'project.sprint.no_tests', hint: 'project.sprint.no_tests.hint', kind: 'bool' },
  { key: 'ui_min_tasks', label: 'project.sprint.ui_min_tasks', hint: 'project.sprint.ui_min_tasks.hint', kind: 'num', min: 0, max: 20 },
  { key: 'feature_share_pct', label: 'project.sprint.feature_share_pct', hint: 'project.sprint.feature_share_pct.hint', kind: 'num', min: 0, max: 100 },
  { key: 'test_share_pct', label: 'project.sprint.test_share_pct', hint: 'project.sprint.test_share_pct.hint', kind: 'num', min: 10, max: 100 },
  { key: 'ac_test_batch', label: 'project.sprint.ac_test_batch', hint: 'project.sprint.ac_test_batch.hint', kind: 'num', min: 1, max: 10 },
  { key: 'carry_over_limit', label: 'project.sprint.carry_over_limit', hint: 'project.sprint.carry_over_limit.hint', kind: 'num', min: 0, max: 10 },
  { key: 'wip_limit', label: 'project.sprint.wip_limit', hint: 'project.sprint.wip_limit.hint', kind: 'num', min: 0, max: 20 },
  { key: 'max_sprints', label: 'project.sprint.max_sprints', hint: 'project.sprint.max_sprints.hint', kind: 'num', min: 1, max: 100 },
];

const Section: React.FC<{ title: string; hint?: string; children: React.ReactNode }> = ({ title, hint, children }) => (
  <section className="rounded-xl border border-line bg-sunk p-3 space-y-2">
    <div>
      <div className="text-[11px] font-mono font-bold uppercase tracking-wider text-ink3">{title}</div>
      {hint && <div className="text-[10px] text-ink3 mt-0.5">{hint}</div>}
    </div>
    {children}
  </section>
);

export const ProjectSettingsModal: React.FC<{ onClose: () => void }> = ({ onClose }) => {
  const { t } = useI18n();
  const [sprint, setSprint] = useState<Record<string, unknown> | null>(null);
  const [sOrig, setSOrig] = useState<Record<string, unknown>>({});
  const [auto, setAuto] = useState<Auto | null>(null);
  const [aOrig, setAOrig] = useState<Auto | null>(null);
  const [ver, setVer] = useState<{ verify_scope: string; verify_light: boolean } | null>(null);
  const [vOrig, setVOrig] = useState<{ verify_scope: string; verify_light: boolean } | null>(null);
  const [cdUrl, setCdUrl] = useState('');
  const [cdOrig, setCdOrig] = useState('');
  const [projLang, setProjLang] = useState('tr');
  const [projLangOrig, setProjLangOrig] = useState('tr');
  const [msg, setMsg] = useState('');
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const [s, a] = await Promise.all([fetch(api('/api/settings/sprint')).then(r => r.json()), fetch(api('/api/settings/autonomy')).then(r => r.json())]);
      setSprint({ ...s.sprint });
      setSOrig({ ...s.sprint });
      const e = await fetch(api('/api/settings/engine')).then(r => r.json());
      const v = { verify_scope: String(e.settings?.verify_scope || 'incremental'), verify_light: e.settings?.verify_light !== false };
      setVer(v);
      setVOrig(v);
      const cd = String(e.settings?.claude_design_url || '');
      setCdUrl(cd);
      setCdOrig(cd);
      const pl = String(e.settings?.project_language || 'tr');
      setProjLang(pl);
      setProjLangOrig(pl);
      const au: Auto = { strict_dod: !!a.autonomy.strict_dod, question_timeout_s: a.autonomy.question_timeout_s ?? null };
      setAuto(au);
      setAOrig(au);
    } catch { setMsg('⚠ ' + t('project.settings.loadFailed', undefined, 'Ayarlar okunamadı')); }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { void load(); }, [load]);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  const post = async (path: string, body: unknown, ok: string) => {
    setBusy(true);
    try {
      const r = await fetch(api(path), { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
      if (!r.ok) throw new Error((await r.json().catch(() => ({})))?.error || t('project.saveFailed', undefined, 'Kaydedilemedi'));
      setMsg(ok);
      await load();
    } catch (e) { setMsg(`⚠ ${(e as Error).message}`); } finally { setBusy(false); }
  };
  const sDirty = sprint ? SPRINT_FIELDS.filter(f => sprint[f.key] !== sOrig[f.key]) : [];
  const vDirty = !!(ver && vOrig && (ver.verify_scope !== vOrig.verify_scope || ver.verify_light !== vOrig.verify_light));
  const cdDirty = cdUrl.trim() !== cdOrig;
  const plDirty = projLang !== projLangOrig;
  const aDirty = !!(auto && aOrig && (auto.strict_dod !== aOrig.strict_dod || auto.question_timeout_s !== aOrig.question_timeout_s));
  const inp = 'w-full bg-panel border rounded-lg px-2 py-1.5 text-ink font-mono shadow-xs focus:outline-none focus:ring-2 focus:ring-ac/40 focus:border-ac';

  return (
    <div className="fixed inset-0 z-[90] bg-black/50 flex items-start justify-center p-4 overflow-y-auto" onMouseDown={e => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="w-full max-w-3xl bg-panel border border-line rounded-panel shadow-xl my-6">
        <div className="flex items-center justify-between px-4 py-3 border-b border-line">
          <div className="text-sm font-bold text-ink">{t('project.settings.title', undefined, 'Proje ayarları')}</div>
          <button onClick={onClose} aria-label={t('common.close', undefined, 'Kapat')} className="p-1 text-ink3 hover:text-ink"><X className="w-4 h-4" /></button>
        </div>
        <div className="p-4 space-y-3 text-xs">
          <Section title={t('project.settings.sprintTitle', undefined, 'Sprint planlama (sprint.*)')} hint={t('project.settings.sprintHint', undefined, 'Kapasite, iş karışımı ve taşıma kuralları. Değişiklik bir sonraki sprint planlamasında geçerli olur.')}>
            {!sprint ? <div className="text-ink3">{t('common.loading', undefined, 'Yükleniyor…')}</div> : (
              <>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                  {SPRINT_FIELDS.map(f => (
                    <label key={f.key} className="text-[11px] text-ink2" title={t(f.hint)}>
                      <span className="block mb-0.5">{t(f.label)}</span>
                      {f.kind === 'num' && <input type="number" min={f.min} max={f.max} value={Number(sprint[f.key] ?? 0)} onChange={e => setSprint({ ...sprint, [f.key]: Number(e.target.value) })} className={`${inp} ${sprint[f.key] !== sOrig[f.key] ? 'border-warn' : 'border-line2'}`} />}
                      {f.kind === 'bool' && <input type="checkbox" checked={!!sprint[f.key]} onChange={e => setSprint({ ...sprint, [f.key]: e.target.checked })} />}
                      {f.kind === 'select' && (
                        <select value={String(sprint[f.key])} onChange={e => setSprint({ ...sprint, [f.key]: e.target.value })} className={`${inp} ${sprint[f.key] !== sOrig[f.key] ? 'border-warn' : 'border-line2'}`}>
                          {f.options!.map(([v, l]) => <option key={v} value={v}>{t(l)}</option>)}
                        </select>
                      )}
                      <span className="block text-[10px] text-ink3 mt-0.5">{t(f.hint)}</span>
                    </label>
                  ))}
                </div>
                <button disabled={busy || !sDirty.length} onClick={() => post('/api/settings/sprint', Object.fromEntries(sDirty.map(f => [f.key, sprint[f.key]])), t('project.settings.sprintSaved', undefined, 'Sprint ayarları kaydedildi.'))}
                  className="px-3 py-1 rounded-lg border border-ok/40 text-ok bg-okd/40 disabled:opacity-50">{t('project.settings.sprintSave', undefined, 'Sprint ayarlarını kaydet')}{sDirty.length ? ` (${sDirty.length})` : ''}</button>
              </>
            )}
          </Section>

          <Section title={t('project.settings.verifyTitle', undefined, 'Sunucu doğrulaması')} hint={t('project.settings.verifyHint', undefined, 'Her teslimden sonra koşan lint / build / test. Kurulum (npm install) bağımlılıklar değişmedikçe tekrarlanmaz.')}>
            {!ver ? <div className="text-ink3">{t('common.loading', undefined, 'Yükleniyor…')}</div> : (
              <>
                <label className="block text-[11px] text-ink2">
                  <span className="block mb-0.5">{t('project.settings.scope', undefined, 'Kapsam')}</span>
                  <select value={ver.verify_scope} onChange={e => setVer({ ...ver, verify_scope: e.target.value })} className={`${inp} border-line2 max-w-xs`}>
                    <option value="incremental">{t('project.settings.scopeIncremental', undefined, 'Artımlı: yalnızca değişen dosyaların testleri (her 5. adımda tam paket)')}</option>
                    <option value="full">{t('project.settings.scopeFull', undefined, 'Tam: her adımda tüm testler')}</option>
                  </select>
                </label>
                <label className="flex items-center gap-2 text-[11px] text-ink2" title={t('project.settings.lightTitle', undefined, 'Artımlı adımlarda build atlanır; build her 5. adımdaki tam doğrulamada ve sprint kapanışında koşar.')}>
                  <input type="checkbox" checked={ver.verify_light} onChange={e => setVer({ ...ver, verify_light: e.target.checked })} /> {t('project.settings.light', undefined, 'Hafif doğrulama: artımlı adımlarda yalnızca lint + değişen testler (build tam doğrulamada)')}
                </label>
                <button disabled={busy || !vDirty} onClick={() => post('/api/settings/engine', ver, t('project.settings.verifySaved', undefined, 'Doğrulama ayarları kaydedildi.'))} className="px-3 py-1 rounded-lg border border-ok/40 text-ok bg-okd/40 disabled:opacity-50">{t('project.settings.verifySave', undefined, 'Doğrulama ayarlarını kaydet')}</button>
              </>
            )}
          </Section>

          <Section title={t('project.settings.designTitle', undefined, 'Tasarım (Designer)')} hint={t('project.settings.designHint', undefined, "Designer, Claude Design'ı (claude.ai Artifact 'Design') kullanabilir: bağlantıyı yazarsan tasarım adımı o tuvali okur; yazmazsan Designer kendi tasarlar ve ürettiği bağlantıyı buraya kaydeder. Sunucu claude.ai'a bağlanmaz; okuma/yazma adımı yürüten Claude oturumunun Artifact aracıyla yapılır.")}>
            <label className="block text-[11px] text-ink2">
              <span className="block mb-0.5">{t('project.settings.designLink', undefined, 'Claude Design bağlantısı (https://claude.ai/…)')}</span>
              <div className="flex items-center gap-2">
                <input value={cdUrl} onChange={e => setCdUrl(e.target.value)} placeholder="https://claude.ai/artifact/…" className={`${inp} border-line2 flex-1`} />
                {cdOrig && <a href={cdOrig} target="_blank" rel="noreferrer" className="px-2 py-1.5 rounded-lg border border-line text-ink2 hover:text-ink whitespace-nowrap">{t('project.settings.open', undefined, 'Aç ↗')}</a>}
              </div>
            </label>
            <button disabled={busy || !cdDirty} onClick={() => post('/api/settings/engine', { claude_design_url: cdUrl.trim() }, t('project.settings.designSaved', undefined, 'Tasarım kaynağı kaydedildi.'))} className="px-3 py-1 rounded-lg border border-ok/40 text-ok bg-okd/40 disabled:opacity-50">{t('project.settings.designSave', undefined, 'Tasarım kaynağını kaydet')}</button>
          </Section>

          <Section title={t('project.settings.langTitle', undefined, 'Proje dili')} hint={t('project.settings.langHint', undefined, 'Proje dili; ajanların ürettiği belgeleri, Jira metinlerini, toplantı notlarını ve sunucu metinlerini belirler. Pano dilinden bağımsızdır (pano dili ayrı: dil seçici). Değişiklik sonraki adımlardan itibaren geçerlidir; mevcut belgeler çevrilmez.')}>
            <label className="block text-[11px] text-ink2">
              <span className="block mb-0.5">{t('project.settings.langLabel', undefined, 'Proje dili')}</span>
              <select value={projLang} onChange={e => setProjLang(e.target.value)} className={`${inp} ${plDirty ? 'border-warn' : 'border-line2'} max-w-xs`}>
                <option value="tr">Türkçe</option>
                <option value="en">English</option>
              </select>
            </label>
            <button disabled={busy || !plDirty} onClick={() => post('/api/settings/engine', { project_language: projLang }, t('project.settings.langSaved', undefined, 'Proje dili kaydedildi.'))} className="px-3 py-1 rounded-lg border border-ok/40 text-ok bg-okd/40 disabled:opacity-50">{t('project.settings.langSave', undefined, 'Proje dilini kaydet')}</button>
          </Section>

          <Section title={t('project.settings.skillsTitle', undefined, 'Ajan yetenekleri (skill rehberleri)')} hint={t('project.settings.skillsHint', undefined, "Her ajan kendi tanımıyla çalışır; buradaki skill'ler (aitmpl.com/skills) ona EK bilgi olarak verilir. Seçim yoksa çekirdek varsayılanlar kullanılır. Skill'ler üçüncü taraf içeriğidir: tavsiye niteliğinde verilir, görev ve kabul kriterleri önceliklidir.")}>
            <SkillSettings inputCls={inp} />
          </Section>

          <Section title={t('project.settings.budgetTitle', undefined, 'Bütçe sınırları (autonomy.budget)')} hint={t('project.settings.budgetHint', undefined, 'Sprint bu sınırlardan birine ulaşınca durur; artırınca üstteki şeritten ya da sprint panosundan sürdürülür.')}>
            <BudgetSettings />
          </Section>

          <Section title={t('project.settings.autoTitle', undefined, 'Otonomi anahtarları')}>
            {!auto ? <div className="text-ink3">{t('common.loading', undefined, 'Yükleniyor…')}</div> : (
              <>
                <label className="flex items-center gap-2 text-[11px] text-ink2" title={t('project.settings.strictTitle', undefined, 'Testsiz ya da doğrulaması atlanmış teslim bitmiş sayılmaz.')}>
                  <input type="checkbox" checked={auto.strict_dod} onChange={e => setAuto({ ...auto, strict_dod: e.target.checked })} /> {t('project.settings.strict', undefined, 'Sıkı bitmişlik tanımı (testsiz teslim kabul edilmez)')}
                </label>
                <label className="block text-[11px] text-ink2" title={t('project.settings.timeoutTitle', undefined, 'Boş = yönetici cevaplayana kadar bekler; 0 = anında varsayılan; N = N sn sonra varsayılan.')}>
                  <span className="block mb-0.5">{t('project.settings.timeout', undefined, 'Soru zaman aşımı (sn; boş = süresiz bekler)')}</span>
                  <input type="number" min={0} value={auto.question_timeout_s ?? ''} onChange={e => setAuto({ ...auto, question_timeout_s: e.target.value === '' ? null : Number(e.target.value) })} className={`${inp} border-line2 max-w-xs`} />
                </label>
                <button disabled={busy || !aDirty} onClick={() => post('/api/settings/autonomy', auto, t('project.settings.autoSaved', undefined, 'Otonomi anahtarları kaydedildi.'))} className="px-3 py-1 rounded-lg border border-ok/40 text-ok bg-okd/40 disabled:opacity-50">{t('project.settings.autoSave', undefined, 'Anahtarları kaydet')}</button>
              </>
            )}
          </Section>
          {msg && <div className={`font-mono ${msg.startsWith('⚠') ? 'text-err' : 'text-ink3'}`}>{msg}</div>}
        </div>
      </div>
    </div>
  );
};
