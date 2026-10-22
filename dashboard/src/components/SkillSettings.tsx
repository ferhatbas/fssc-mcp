import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { api } from '../config';
import { notify } from '../lib/dialog';
import { useI18n } from '../i18n';

interface SkillItem { id: string; category: string; title: string; summary: string; roles: string[]; default_roles: string[]; cached: boolean; source: string }
interface RoleItem { id: string; name: string; selected: string[]; custom: boolean }
interface Overview { enabled: boolean; max_chars: number; roles: RoleItem[]; skills: SkillItem[]; source: { site?: string; repo?: string; note?: string } }

const MAX_PER_ROLE = 4;

/** Ajan yetenekleri: ajanın kendi tanımına EK skill rehberleri (aitmpl.com/skills). Rol başına en çok 4; seçim yoksa katalog varsayılanı. */
export const SkillSettings: React.FC<{ inputCls: string; fixedRole?: string }> = ({ inputCls, fixedRole }) => {
  const { t } = useI18n();
  const [ov, setOv] = useState<Overview | null>(null);
  const [role, setRole] = useState('');
  const [sel, setSel] = useState<Record<string, string[]>>({});
  const [custom, setCustom] = useState<Record<string, boolean>>({});
  const [enabled, setEnabled] = useState(true);
  const [q, setQ] = useState('');
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const j: Overview = await fetch(api('/api/skills')).then(r => r.json());
      setOv(j);
      setEnabled(j.enabled);
      setSel(Object.fromEntries(j.roles.map(r => [r.id, r.selected])));
      setCustom(Object.fromEntries(j.roles.map(r => [r.id, r.custom])));
      setRole(prev => fixedRole || prev || j.roles[0]?.id || '');
    } catch { notify(t('agents.skill.listFailed', undefined, 'Skill listesi okunamadı')); }
  }, [fixedRole]);
  useEffect(() => { void load(); }, [load]);

  const visible = useMemo(() => {
    if (!ov) return [];
    const needle = q.trim().toLowerCase();
    return ov.skills
      .filter(s => !needle || `${s.title} ${s.id} ${s.category} ${s.summary}`.toLowerCase().includes(needle))
      .sort((a, b) => Number((sel[role] || []).includes(b.id)) - Number((sel[role] || []).includes(a.id)) || Number(b.roles.includes(role)) - Number(a.roles.includes(role)) || a.title.localeCompare(b.title));
  }, [ov, q, sel, role]);

  const toggle = (id: string) => {
    const cur = sel[role] || [];
    if (!cur.includes(id) && cur.length >= MAX_PER_ROLE) { notify(t('agents.skill.maxPerRole', { n: MAX_PER_ROLE }, 'Bir ajana en çok {n} skill verilir (istem boyutu ve odak için).')); return; }
    setSel({ ...sel, [role]: cur.includes(id) ? cur.filter(x => x !== id) : [...cur, id] });
    setCustom({ ...custom, [role]: true });
  };
  const post = async (path: string, body?: unknown) => {
    const r = await fetch(api(path), { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body ?? {}) });
    if (!r.ok) throw new Error((await r.json().catch(() => ({})))?.error || t('agents.skill.requestFailed', undefined, 'İstek başarısız'));
    return r.json();
  };
  const save = async (skipRole?: string) => {
    setBusy(true);
    try {
      const roles = Object.fromEntries(Object.entries(sel).filter(([k]) => custom[k] && k !== skipRole));
      await post('/api/skills/config', { enabled, roles });
      notify(t('agents.skill.saved', undefined, 'Skill ayarları kaydedildi; seçilen skill\'ler arka planda indiriliyor.'), 'success');
      await load();
    } catch (e) { notify((e as Error).message); } finally { setBusy(false); }
  };
  const refresh = async () => {
    setBusy(true);
    try {
      const j = await post('/api/skills/refresh');
      notify(`${t('agents.skill.downloaded', { done: j.downloaded, total: j.total }, '{done}/{total} skill indirildi')}${j.failed ? t('agents.skill.failedPart', { n: j.failed }, ', {n} indirilemedi (ağ?)') : ''}.`, j.failed ? 'info' : 'success');
      await load();
    } catch (e) { notify((e as Error).message); } finally { setBusy(false); }
  };
  const reset = () => { setCustom({ ...custom, [role]: false }); void save(role); };

  if (!ov) return <div className="text-ink3 text-xs">{t('common.loading', undefined, 'Yükleniyor…')}</div>;
  const cur = sel[role] || [];
  return (
    <div className="space-y-2">
      {!fixedRole && <label className="flex items-center gap-2 text-[11px] text-ink2" title={t('agents.skill.enabledTitle', undefined, 'Kapalıysa ajanlara skill rehberi verilmez')}>
        <input type="checkbox" checked={enabled} onChange={e => setEnabled(e.target.checked)} /> {t('agents.skill.enabled', undefined, 'Ajanlara ek skill rehberleri ver (rolün kendi tanımı ve görevin kabul kriterleri her zaman önceliklidir)')}
      </label>}
      <div className="flex flex-wrap items-center gap-2">
        {!fixedRole && <label className="text-[11px] text-ink2 flex items-center gap-1.5">{t('agents.skill.agent', undefined, 'Ajan')}
          <select value={role} onChange={e => setRole(e.target.value)} className={`${inputCls} border-line2 !w-auto`}>
            {ov.roles.map(r => <option key={r.id} value={r.id}>{r.name} ({r.id}){custom[r.id] ? ` · ${t('agents.skill.customSel', undefined, 'özel seçim')}` : ''}</option>)}
          </select>
        </label>}
        <input value={q} onChange={e => setQ(e.target.value)} placeholder={t('agents.skill.search', undefined, 'Skill ara…')} aria-label={t('agents.skill.searchAria', undefined, 'Skill ara')} className={`${inputCls} border-line2 flex-1 min-w-[160px]`} />
        <span className="text-[11px] text-ink3">{t('agents.skill.selected', { cur: cur.length, max: MAX_PER_ROLE }, '{cur}/{max} seçili')}</span>
        {!fixedRole && <button type="button" onClick={() => window.dispatchEvent(new Event('fssc:open-agents'))} className="px-2.5 py-1 rounded-lg border border-line text-ink2 hover:text-ink text-xs ml-auto" title={t('agents.skill.editAgentsTitle', undefined, 'Bu projenin ajanlarını ekle, düzenle, çıkar; ajan havuzundan al')}>{t('agents.skill.editAgents', undefined, 'Ajanları düzenle / ekle / çıkar')}</button>}
      </div>
      <div className="max-h-64 overflow-y-auto rounded-lg border border-line2 bg-panel divide-y divide-line/60">
        {visible.map(s => {
          const on = cur.includes(s.id);
          return (
            <label key={s.id} className={`flex items-start gap-2 px-2.5 py-1.5 cursor-pointer hover:bg-sunk ${on ? 'bg-acd/30' : ''}`}>
              <input type="checkbox" checked={on} onChange={() => toggle(s.id)} className="mt-1" />
              <span className="min-w-0 flex-1">
                <span className="flex items-center gap-1.5 flex-wrap">
                  <b className="text-[12px] text-ink">{s.title}</b>
                  <span className="text-[10px] font-mono px-1.5 rounded bg-sunk text-ink3 border border-line">{s.category}</span>
                  {s.default_roles.includes(role) && <span className="text-[10px] px-1.5 rounded bg-okd text-ok border border-ok/30">{t('agents.skill.default', undefined, 'varsayılan')}</span>}
                  {!s.cached && <span className="text-[10px] px-1.5 rounded bg-warnd text-warn border border-warn/30" title={t('agents.skill.notCachedTitle', undefined, 'Henüz indirilmedi: seçilince arka planda indirilir')}>{t('agents.skill.notCached', undefined, 'indirilmedi')}</span>}
                </span>
                <span className="block text-[11px] text-ink3">{s.summary}</span>
              </span>
              <a href={s.source} target="_blank" rel="noreferrer" onClick={e => e.stopPropagation()} className="text-[11px] text-ac hover:underline whitespace-nowrap">{t('agents.skill.source', undefined, 'kaynak')} ↗</a>
            </label>
          );
        })}
        {visible.length === 0 && <div className="px-3 py-4 text-center text-[11px] text-ink3">{t('agents.skill.noMatch', undefined, 'Eşleşen skill yok.')}</div>}
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <button type="button" disabled={busy} onClick={() => save()} className="px-3 py-1 rounded-lg border border-ok/40 text-ok bg-okd/40 disabled:opacity-50 text-xs">{t('agents.skill.save', undefined, 'Skill ayarlarını kaydet')}</button>
        <button type="button" disabled={busy || !custom[role]} onClick={reset} className="px-3 py-1 rounded-lg border border-line text-ink2 hover:text-ink disabled:opacity-50 text-xs" title={t('agents.skill.resetTitle', undefined, 'Bu ajan için katalog varsayılanına dön')}>{t('agents.skill.reset', undefined, 'Bu ajan için varsayılana dön')}</button>
        <button type="button" disabled={busy} onClick={refresh} className="px-3 py-1 rounded-lg border border-line text-ink2 hover:text-ink disabled:opacity-50 text-xs" title={t('agents.skill.refreshTitle', undefined, "Etkin skill'leri kaynaktan yeniden indir")}>{t('agents.skill.refresh', undefined, "Skill'leri indir / güncelle")}</button>
      </div>
      <div className="text-[10px] text-ink3">{t('agents.skill.sourceLabel', undefined, 'Kaynak')}: <a href={ov.source.site} target="_blank" rel="noreferrer" className="text-ac hover:underline">aitmpl.com/skills</a> · {ov.source.note}</div>
    </div>
  );
};
