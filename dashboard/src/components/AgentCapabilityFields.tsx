import React from 'react';
import { Agent } from '../types/telemetry';
import { useI18n } from '../i18n';

/** G6: ajanın yetenek / profil alanları (server/agent_registry.py). Form durumu ve sunucuya gidecek değişiklik farkı burada. */
export const BASE_ROLES = ['BACKEND_DEV', 'FRONTEND_DEV', 'DESIGNER', 'DEVOPS', 'QA', 'ARCHITECT', 'DOCUMENTOR'];
export const TASK_CAPABILITIES = ['SCAFFOLD', 'FEATURE', 'TEST', 'E2E_SCENARIO', 'DEVOPS', 'DOCS', 'BUG', 'IMPROVEMENT', 'REFACTOR', 'REVIEW'];
const EFFORTS = ['', 'low', 'medium', 'high', 'xhigh', 'max'];
const CORE_IDS = ['PM', 'ARCHITECT', 'BACKEND_DEV', 'FRONTEND_DEV', 'DESIGNER', 'QA', 'E2E_TESTER', 'DEVOPS', 'PO', 'REPORTER', 'DOCUMENTOR', 'SCM', 'SCRUM_MASTER'];

export interface CapabilityDraft {
  roleBase: string;
  capabilities: string[];
  focus: string;
  model: string;
  effort: string;
  language: string;
  maxTokens: string;
  budget: string;
  active: boolean;
  scope: 'project' | 'global';
  addendum: string;
}

export const emptyDraft = (): CapabilityDraft => ({
  roleBase: 'BACKEND_DEV', capabilities: [], focus: '', model: '', effort: '', language: '', maxTokens: '', budget: '', active: true, scope: 'project', addendum: '',
});

export const agentScope = (a: Pick<Agent, 'id' | 'scope' | 'inherits'>): 'core' | 'project' | 'global' =>
  a.scope ?? (CORE_IDS.includes(a.id) ? 'core' : a.inherits ? 'global' : 'project');

export const draftFromAgent = (a: Agent): CapabilityDraft => ({
  roleBase: a.role_base || (BASE_ROLES.includes(a.role) ? a.role : 'BACKEND_DEV'),
  capabilities: a.capabilities ? [...a.capabilities] : [],
  focus: (a.focus || []).join(', '),
  model: a.profile?.model || '',
  effort: a.profile?.effort || '',
  language: a.profile?.language || '',
  maxTokens: a.profile?.max_tokens ? String(a.profile.max_tokens) : '',
  budget: a.profile?.budget ? String(a.profile.budget) : '',
  active: a.active !== false,
  scope: agentScope(a) === 'global' ? 'global' : 'project',
  addendum: a.prompt_addendum || '',
});

const splitList = (s: string): string[] => s.split(/[,;\n]/).map(x => x.trim().toLowerCase()).filter(Boolean);

/** Sunucuya gidecek alanlar. Düzenlemede yalnızca DEĞİŞENLER gönderilir: global bir ajanda her alan projeye özgü fark (overrides) olmasın. */
export function draftToPayload(d: CapabilityDraft, original?: Agent): Record<string, unknown> {
  const profile: Record<string, unknown> = {};
  if (d.model.trim()) profile.model = d.model.trim();
  if (d.effort) profile.effort = d.effort;
  if (d.language) profile.language = d.language;
  if (d.maxTokens.trim()) profile.max_tokens = Number(d.maxTokens);
  if (d.budget.trim()) profile.budget = Number(d.budget);
  const full: Record<string, unknown> = {
    role_base: d.roleBase, capabilities: d.capabilities, focus: splitList(d.focus), profile, active: d.active, prompt_addendum: d.addendum.trim(),
  };
  if (!original) return { ...full, scope: d.scope };
  const before = draftFromAgent(original);
  const beforePayload = draftToPayload({ ...before, scope: 'project' });
  const out: Record<string, unknown> = {};
  for (const key of Object.keys(full)) {
    if (JSON.stringify(full[key]) !== JSON.stringify((beforePayload as Record<string, unknown>)[key])) out[key] = full[key];
  }
  return out;
}

interface Props {
  draft: CapabilityDraft;
  onChange: (next: CapabilityDraft) => void;
  /** Çekirdek rol: temel rol / yetenekler sabit, yalnızca profil ve etkinlik düzenlenir. */
  core: boolean;
  editing: boolean;
  /** Global ajan: değişiklikler bu projeye özgü fark olur. */
  inherited: boolean;
}

const input = 'w-full bg-panel border border-line2 rounded-lg px-2.5 py-1.5 text-xs text-ink placeholder-ink3 focus:border-ac focus:outline-none';
const label = 'block text-[11px] font-medium text-ink3 mb-1';

export const AgentCapabilityFields: React.FC<Props> = ({ draft, onChange, core, editing, inherited }) => {
  const { t } = useI18n();
  const set = <K extends keyof CapabilityDraft>(key: K, value: CapabilityDraft[K]) => onChange({ ...draft, [key]: value });
  const toggleCap = (cap: string) =>
    set('capabilities', draft.capabilities.includes(cap) ? draft.capabilities.filter(c => c !== cap) : [...draft.capabilities, cap]);

  return (
    <div className="space-y-3 rounded-xl border border-line bg-panel/60 p-3" data-testid="agent-capability-fields">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="text-[11px] font-bold text-ink uppercase tracking-wider">{t('agents.cap.title', undefined, 'Yetenekler ve profil')}</span>
        <label className="flex items-center gap-1.5 text-[11px] text-ink2 cursor-pointer">
          <input type="checkbox" checked={draft.active} onChange={e => set('active', e.target.checked)} />
          {t('agents.cap.active', undefined, 'Bu projede etkin (görev alır)')}
        </label>
      </div>
      {inherited && (
        <p className="text-[11px] text-warn">
          {t('agents.cap.inherited', undefined, 'Şirket geneli ajan: burada yaptığın değişiklik yalnızca bu projeye özgü fark olur; tanım globalde değişince farksız alanlar güncellenir.')}
        </p>
      )}

      {!core && (
        <>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <div>
              <label className={label}>{t('agents.cap.roleBase', undefined, 'Temel rol (istem şablonu, görev ipucu, doğrulama yolu)')}</label>
              <select value={draft.roleBase} onChange={e => set('roleBase', e.target.value)} className={`${input} font-mono cursor-pointer`}>
                {BASE_ROLES.map(r => <option key={r} value={r}>{r}</option>)}
              </select>
            </div>
            <div>
              <label className={label}>{t('agents.cap.focus', undefined, 'Odak sözcükleri (virgülle) — metninde geçen işler bu ajana düşer')}</label>
              <input type="text" value={draft.focus} placeholder={t('agents.cap.focusPh', undefined, 'mobil, android, ios, flutter')} onChange={e => set('focus', e.target.value)} className={input} />
            </div>
          </div>
          <div>
            <label className={label}>{t('agents.cap.capabilities', undefined, 'Yetenekler (hangi iş türlerini alır)')}</label>
            <div className="flex flex-wrap gap-1.5">
              {TASK_CAPABILITIES.map(cap => (
                <button
                  key={cap}
                  type="button"
                  onClick={() => toggleCap(cap)}
                  className={`px-2 py-0.5 rounded border text-[10px] font-mono transition ${
                    draft.capabilities.includes(cap) ? 'bg-acd text-ac border-ac/50' : 'bg-sunk text-ink3 border-line hover:text-ink'
                  }`}
                >
                  {cap}
                </button>
              ))}
            </div>
            <p className="text-[10px] text-ink3 mt-1">{t('agents.cap.capsHint', undefined, 'Boş bırakırsan temel rolün varsayılan yetenekleri geçerli olur.')}</p>
          </div>
        </>
      )}

      <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
        <div className="col-span-2">
          <label className={label}>{t('agents.cap.model', undefined, 'Model (ipucu)')}</label>
          <input type="text" value={draft.model} placeholder={t('agents.cap.modelPh', undefined, 'örn. claude-sonnet-5-5')} onChange={e => set('model', e.target.value)} className={`${input} font-mono`} />
        </div>
        <div>
          <label className={label}>{t('agents.cap.effort', undefined, 'Çaba')}</label>
          <select value={draft.effort} onChange={e => set('effort', e.target.value)} className={`${input} font-mono cursor-pointer`}>
            {EFFORTS.map(x => <option key={x} value={x}>{x || t('agents.cap.default', undefined, '(varsayılan)')}</option>)}
          </select>
        </div>
        <div>
          <label className={label}>{t('agents.cap.language', undefined, 'Dil')}</label>
          <select value={draft.language} onChange={e => set('language', e.target.value)} className={`${input} font-mono cursor-pointer`}>
            <option value="">{t('agents.cap.default', undefined, '(varsayılan)')}</option>
            <option value="tr">tr</option>
            <option value="en">en</option>
          </select>
        </div>
        <div>
          <label className={label}>{t('agents.cap.maxTokens', undefined, 'Maks. token')}</label>
          <input type="number" min={1} value={draft.maxTokens} onChange={e => set('maxTokens', e.target.value)} className={`${input} font-mono`} />
        </div>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
        <div>
          <label className={label}>{t('agents.cap.budget', undefined, 'Sprint başına token bütçesi')}</label>
          <input type="number" min={1} value={draft.budget} onChange={e => set('budget', e.target.value)} className={`${input} font-mono`} />
        </div>
        {!editing && !core && (
          <div className="md:col-span-2">
            <label className={label}>{t('agents.cap.scope', undefined, 'Kapsam')}</label>
            <div className="flex gap-4 text-[11px] text-ink2 pt-1.5">
              <label className="flex items-center gap-1.5 cursor-pointer">
                <input type="radio" name="agent-scope" checked={draft.scope === 'project'} onChange={() => set('scope', 'project')} /> {t('agents.cap.scopeProject', undefined, 'Yalnızca bu proje')}
              </label>
              <label className="flex items-center gap-1.5 cursor-pointer">
                <input type="radio" name="agent-scope" checked={draft.scope === 'global'} onChange={() => set('scope', 'global')} /> {t('agents.cap.scopeGlobal', undefined, 'Ajan havuzuna da ekle (başka projelere istenince eklenir)')}
              </label>
            </div>
          </div>
        )}
      </div>
      <div>
        <label className={label}>{t('agents.cap.addendum', undefined, 'Bu ajana özel ek yönerge (istem şablonunun sonuna eklenir)')}</label>
        <textarea
          value={draft.addendum}
          rows={2}
          placeholder={t('agents.cap.addendumPh', undefined, 'örn. Her ekran için küçük ekran (360px) davranışını da test et.')}
          onChange={e => set('addendum', e.target.value)}
          className={`${input} resize-y`}
        />
      </div>
    </div>
  );
};
