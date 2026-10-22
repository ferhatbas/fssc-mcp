import React, { useCallback, useEffect, useState } from 'react';
import { api } from '../config';
import { useI18n } from '../i18n';

export interface ProjectLayout {
  mode: 'apps' | 'flat';
  apps_dir: string;
  devops_dir: string;
  docs_dir: string;
  roles: Record<string, string>;
  enforce: boolean;
}

interface LayoutInfo {
  project_id: string;
  layout: ProjectLayout;
  default: ProjectLayout;
  docs_root: string | null;
  compliant: boolean | null;
  root_extra?: string[];
  migration_preview?: { moves: { from: string; to: string; kind: string; empty?: boolean }[]; conflicts: string[]; root_role: string };
}

interface MigrationResult {
  status: 'PLAN' | 'APPLIED';
  plan: { moves: { from: string; to: string; kind: string; empty?: boolean }[]; conflicts: string[]; skipped: string[]; root_role: string };
  moved?: { from: string; to: string; method: string }[];
  rewritten?: Record<string, number>;
  commit?: { status: string; hash?: string | null; reason?: string };
}

interface Props {
  projectId?: string;
  projectName?: string;
}

// değer çeviri anahtarıdır (render sırasında t() ile çözülür)
const MODE_LABEL: Record<string, string> = { apps: 'project.layout.modeApps', flat: 'project.layout.modeFlat' };

/** Proje klasör düzeni (talimat: meta-repo-setup.md): adlar ve rol eşlemesi ayarlardan tanımlanır; düz projeyi apps düzenine taşıma planı ve uygulaması. */
export const ProjectLayoutCard: React.FC<Props> = ({ projectId, projectName }) => {
  const { t } = useI18n();
  const [info, setInfo] = useState<LayoutInfo | null>(null);
  const [draft, setDraft] = useState<ProjectLayout | null>(null);
  const [msg, setMsg] = useState('');
  const [busy, setBusy] = useState(false);
  const [plan, setPlan] = useState<MigrationResult | null>(null);
  const [armed, setArmed] = useState(false);

  const load = useCallback(async () => {
    if (!projectId) return;
    try {
      const res = await fetch(api(`/api/projects/${encodeURIComponent(projectId)}/layout`));
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data: LayoutInfo = await res.json();
      setInfo(data);
      setDraft(data.layout);
    } catch (err) {
      console.error(err);
      setMsg('⚠ ' + t('project.layout.loadFailed', undefined, 'Klasör düzeni okunamadı'));
    }
  }, [projectId]);

  useEffect(() => {
    setPlan(null);
    setArmed(false);
    setMsg('');
    load();
  }, [load]);

  const save = async () => {
    if (!draft || !projectId) return;
    setBusy(true);
    setMsg('');
    try {
      const res = await fetch(api(`/api/projects/${encodeURIComponent(projectId)}/layout`), {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ layout: draft }),
      });
      const data = await res.json().catch(() => ({}));
      setMsg(res.ok ? '✓ ' + t('project.layout.saved', undefined, 'Klasör düzeni kaydedildi') : `⚠ ${data.error || `HTTP ${res.status}`}`);
      await load();
    } catch (err) {
      console.error(err);
      setMsg('⚠ ' + t('project.saveFailed', undefined, 'Kaydedilemedi'));
    } finally {
      setBusy(false);
    }
  };

  const migrate = async (apply: boolean) => {
    if (!draft || !projectId) return;
    setBusy(true);
    setMsg('');
    try {
      const res = await fetch(api(`/api/projects/${encodeURIComponent(projectId)}/migrate-layout`), {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ apply, layout: draft }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        setMsg(`⚠ ${data.error || `HTTP ${res.status}`}`);
        return;
      }
      setPlan(data as MigrationResult);
      if (apply) {
        const r = data as MigrationResult;
        setMsg(`✓ ${t('project.layout.moved', { n: r.moved?.length ?? 0 }, 'Taşındı: {n} girdi')}${r.commit?.hash ? ` · commit ${r.commit.hash}` : ''}`);
        setArmed(false);
        await load();
      }
    } catch (err) {
      console.error(err);
      setMsg('⚠ ' + t('project.layout.moveFailed', undefined, 'Taşıma isteği başarısız'));
    } finally {
      setBusy(false);
    }
  };

  if (!projectId) {
    return null;
  }
  const dirty = !!(info && draft && JSON.stringify(info.layout) !== JSON.stringify(draft));
  const isApps = draft?.mode === 'apps';
  const roleRows = draft ? Object.entries(draft.roles) : [];
  const setField = (patch: Partial<ProjectLayout>) => draft && setDraft({ ...draft, ...patch });
  const setRole = (oldKey: string, key: string, folder: string) => {
    if (!draft) return;
    const next: Record<string, string> = {};
    Object.entries(draft.roles).forEach(([k, v]) => { if (k === oldKey) next[key] = folder; else next[k] = v; });
    setDraft({ ...draft, roles: next });
  };
  const input = 'bg-sunk border border-line rounded-lg px-2 py-1 text-ink font-mono text-[11px] w-full';
  const migrationSource = plan?.plan || (info?.migration_preview ? { ...info.migration_preview, skipped: [] } : null);

  return (
    <div className="bg-panel2 border border-line rounded-xl p-4 space-y-3 shadow-xs">
      <div className="flex items-center justify-between gap-2 flex-wrap">
        <label className="text-[11px] font-bold text-ink uppercase tracking-wider font-mono">
          {t('project.layout.heading', undefined, '0e. Proje Klasör Düzeni')}{projectName ? ` · ${projectName}` : ''}
        </label>
        <div className="flex items-center gap-2">
          {msg && <span className={`text-[11px] font-mono ${msg.startsWith('⚠') ? 'text-err' : 'text-ok'}`}>{msg}</span>}
          {info && (
            <span className={`text-[10px] font-mono px-2 py-0.5 rounded border ${info.layout.mode === 'apps' ? 'bg-okd text-ok border-ok/40' : 'bg-warnd text-warn border-warn/40'}`}>
              {t(MODE_LABEL[info.layout.mode])}
            </span>
          )}
          <button type="button" onClick={load} className="text-[10px] font-mono text-ink3 hover:text-ink">{t('project.layout.refresh', undefined, 'yenile')}</button>
        </div>
      </div>
      <p className="text-[11px] text-ink3">
        {t('project.layout.intro', undefined, 'Önerilen düzen tek git deposudur: uygulamalar apps/<rol>/, Dockerfile ve CI devops/, belgeler docs/ altındadır; kökte yalnızca README gibi depo dosyaları kalır. Adlar ve rol eşlemesi buradan tanımlanır; ajan teslimleri bu düzene göre denetlenir ve ajan istemlerine yazılır.')}
      </p>

      {draft && (
        <>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
            {(['apps', 'flat'] as const).map(m => (
              <label key={m} className={`flex gap-2 p-2 rounded-md border cursor-pointer text-[11px] ${draft.mode === m ? 'border-ac bg-acd/40' : 'border-line'}`}>
                <input type="radio" name="layout-mode-card" checked={draft.mode === m} onChange={() => setField({ mode: m })} />
                <span>
                  <b className="text-ink">{m === 'apps' ? `apps/ devops/ docs/ (${t('project.recommended', undefined, 'önerilir')})` : t('project.flatLayout', undefined, 'Düz düzen')}</b><br />
                  <span className="text-ink3">{m === 'apps' ? t('project.layout.appsDesc', undefined, 'Her uygulama ayrı klasörde; belgeler ve altyapı ayrı.') : t('project.layout.flatDesc', undefined, 'Ürün kodu proje kökünde; belge klasörü docs_root ayarına göre.')}</span>
                </span>
              </label>
            ))}
          </div>

          {isApps && (
            <>
              <div className="grid grid-cols-3 gap-2 text-[11px]">
                <label className="space-y-1"><span className="text-ink3">{t('project.layout.appsDir', undefined, 'Uygulamalar klasörü')}</span>
                  <input className={input} value={draft.apps_dir} onChange={e => setField({ apps_dir: e.target.value })} /></label>
                <label className="space-y-1"><span className="text-ink3">{t('project.layout.devopsDir', undefined, 'DevOps klasörü')}</span>
                  <input className={input} value={draft.devops_dir} onChange={e => setField({ devops_dir: e.target.value })} /></label>
                <label className="space-y-1"><span className="text-ink3">{t('project.layout.docsDir', undefined, 'Belgeler klasörü')}</span>
                  <input className={input} value={draft.docs_dir} onChange={e => setField({ docs_dir: e.target.value })} /></label>
              </div>
              <div className="space-y-1">
                <div className="text-[10px] font-mono uppercase tracking-wider text-ink3">{t('project.layout.roles', { dir: draft.apps_dir }, 'Roller → uygulama klasörü ({dir}/…)')}</div>
                {roleRows.map(([k, v]) => (
                  <div key={k} className="grid grid-cols-[1fr_1fr_auto] gap-2 items-center">
                    <input className={input} value={k} onChange={e => setRole(k, e.target.value.toLowerCase(), v)} title={t('project.layout.roleTitle', undefined, 'Mantıksal rol (backend, web, mobile ...)')} />
                    <input className={input} value={v} onChange={e => setRole(k, k, e.target.value)} title={t('project.layout.folderName', undefined, 'Klasör adı')} />
                    <button type="button" className="px-2 text-ink3 hover:text-err" title={t('project.layout.removeRole', undefined, 'Rolü kaldır')}
                      onClick={() => { const next = { ...draft.roles }; delete next[k]; setField({ roles: next }); }}>×</button>
                  </div>
                ))}
                <button type="button" className="text-[11px] text-ac hover:underline"
                  onClick={() => { let n = 1; while (draft.roles[`uygulama${n}`]) n += 1; setField({ roles: { ...draft.roles, [`uygulama${n}`]: `uygulama${n}` } }); }}>{t('project.layout.addRole', undefined, '+ rol ekle')}</button>
              </div>
              <label className="flex items-center gap-2 text-[11px] text-ink2 cursor-pointer">
                <input type="checkbox" checked={draft.enforce} onChange={e => setField({ enforce: e.target.checked })} />
                {t('project.layout.enforce', undefined, 'Düzene uymayan ajan teslimini reddet (kapalıysa sunucu dosyaları düzene taşır)')}
              </label>
            </>
          )}

          <div className="flex items-center gap-2 flex-wrap">
            <button type="button" disabled={busy || !dirty} onClick={save}
              className="px-3.5 py-1.5 bg-ink text-bg font-bold rounded-lg text-xs shadow-panel hover:opacity-90 transition disabled:opacity-50">
              {busy ? t('project.layout.saving', undefined, 'Kaydediliyor…') : t('project.layout.save', undefined, 'Düzeni Kaydet')}
            </button>
            <button type="button" disabled={busy} onClick={() => info && setDraft({ ...info.default })}
              className="px-3 py-1.5 border border-line rounded-lg text-xs text-ink2 hover:text-ink disabled:opacity-50">{t('project.layout.resetDefault', undefined, 'Önerilene dön')}</button>
            {dirty && <span className="text-[11px] text-warn font-mono">{t('project.layout.unsaved', undefined, 'kaydedilmemiş değişiklik')}</span>}
          </div>

          {/* Göç: düz düzendeki proje ya da düzene uymayan kök girdileri */}
          {(info?.layout.mode === 'flat' || (info?.root_extra && info.root_extra.length > 0)) && (
            <div className="border-t border-line pt-3 space-y-2">
              <div className="text-[11px] font-bold text-ink">{t('project.layout.moveTitle', undefined, 'Mevcut dosyaları düzene taşı')}</div>
              <p className="text-[11px] text-ink3">
                {t('project.layout.moveIntro', undefined, 'Ajanlar dosya yazar ama taşıyamaz; taşıma bir sunucu eylemidir: izlenen girdiler git mv ile (geçmiş korunur), kayıtlı yollar (Jira ipuçları, belge bağlantıları, doğrulama komutları) güncellenir ve tek commit atılır. Adım üretilirken yapılamaz; onay beklerken yapılabilir. Geri almak için git revert.')}
                {info?.root_extra && info.root_extra.length > 0 && <> {t('project.layout.rootExtra', undefined, 'Düzene uymayan kök girdiler:')} <code>{info.root_extra.join(', ')}</code>.</>}
              </p>
              <div className="flex items-center gap-2">
                <button type="button" disabled={busy || !isApps} onClick={() => migrate(false)}
                  className="px-3 py-1.5 border border-line rounded-lg text-xs text-ink2 hover:text-ink disabled:opacity-50"
                  title={isApps ? t('project.layout.planTitle', undefined, 'Hiçbir şeyi değiştirmeden planı göster') : t('project.layout.planNeedApps', undefined, 'Önce apps düzenini seçin')}>{t('project.layout.showPlan', undefined, 'Taşıma planını göster')}</button>
                {plan?.plan && plan.plan.conflicts.length === 0 && plan.status === 'PLAN' && plan.plan.moves.length > 0 && (
                  <button type="button" disabled={busy}
                    onClick={() => { if (!armed) { setArmed(true); setTimeout(() => setArmed(false), 5000); } else { migrate(true); } }}
                    className="px-3 py-1.5 bg-warn text-onac font-bold rounded-lg text-xs hover:opacity-90 disabled:opacity-50">
                    {armed ? t('project.layout.sure', undefined, 'Emin misiniz? Tekrar tıklayın') : t('project.layout.moveBtn', { n: plan.plan.moves.length }, 'Taşı ({n} girdi)')}
                  </button>
                )}
              </div>
              {migrationSource && (
                <div className="bg-sunk border border-line rounded-lg p-2 max-h-48 overflow-y-auto text-[11px] font-mono space-y-0.5">
                  {migrationSource.moves.length === 0 && <div className="text-ink3">{t('project.layout.nothingToMove', undefined, 'Taşınacak girdi yok.')}</div>}
                  {migrationSource.moves.map(m => (
                    <div key={m.from}><span className="text-ink2">{m.from}</span> <span className="text-ink3">→</span> <span className="text-ac">{m.to}</span> <span className="text-ink3">({m.kind}{m.empty ? `, ${t('project.layout.empty', undefined, 'boş')}` : ''})</span></div>
                  ))}
                  {migrationSource.conflicts.map(c => <div key={c} className="text-err">⚠ {c}</div>)}
                </div>
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
};
