import React, { useCallback, useEffect, useState } from 'react';
import { confirmDialog } from '../lib/dialog';
import { Download, Upload, Globe, Undo2, HeartPulse, Layers } from 'lucide-react';
import { api } from '../config';
import { Agent, AgentHealth, AgentTemplateInfo } from '../types/telemetry';
import { agentScope } from './AgentCapabilityFields';
import { useI18n } from '../i18n';

/** G6: şablon kütüphanesi, ajan paketi içe/dışa aktarma, şirket geneline terfi, proje farkını geri alma ve ajan sağlığı. */
interface Props {
  /** Düzenlenen ajan (yeni ajan eklenirken yok). */
  agent?: Agent | null;
  /** Sunucuda değişiklik yapıldı (liste WebSocket olayıyla da yenilenir; bu, ek bir güvence). */
  onChanged?: () => void;
}

const btn = 'px-2.5 py-1 rounded-lg border text-[11px] font-medium flex items-center gap-1.5 transition disabled:opacity-50';

async function errorText(res: Response): Promise<string> {
  try {
    const j = await res.json();
    return j.error || `HTTP ${res.status}`;
  } catch {
    return `HTTP ${res.status}`;
  }
}

export const AgentToolsBar: React.FC<Props> = ({ agent, onChanged }) => {
  const { t } = useI18n();
  const [templates, setTemplates] = useState<AgentTemplateInfo[]>([]);
  const [templateKey, setTemplateKey] = useState('');
  const [templateGlobal, setTemplateGlobal] = useState(false);
  const [health, setHealth] = useState<AgentHealth | null>(null);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let stop = false;
    fetch(api('/api/agent-templates'))
      .then(r => (r.ok ? r.json() : { templates: [] }))
      .then(j => { if (!stop) setTemplates(j.templates || []); })
      .catch(() => undefined);
    return () => { stop = true; };
  }, []);

  const loadHealth = useCallback(async () => {
    if (!agent) { setHealth(null); return; }
    try {
      const r = await fetch(api(`/api/agents/${agent.id}/health`));
      setHealth(r.ok ? (await r.json()).health : null);
    } catch {
      setHealth(null);
    }
  }, [agent?.id]);

  useEffect(() => { loadHealth(); }, [loadHealth]);

  const run = async (fn: () => Promise<string>) => {
    setBusy(true);
    setMsg(null);
    try {
      setMsg({ ok: true, text: await fn() });
      onChanged?.();
    } catch (e: any) {
      setMsg({ ok: false, text: e?.message || t('agents.tools.failed', undefined, 'İşlem başarısız.') });
    } finally {
      setBusy(false);
    }
  };

  const applyTemplate = () => run(async () => {
    const res = await fetch(api(`/api/agent-templates/${templateKey}/apply`), {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ scope: templateGlobal ? 'global' : 'project' }),
    });
    if (!res.ok) throw new Error(await errorText(res));
    const j = await res.json();
    return `✓ ${t('agents.tools.added', undefined, 'Eklendi')}: ${j.added.join(', ') || t('agents.tools.none', undefined, '(yok)')}${j.skipped.length ? ` · ${t('agents.tools.alreadyExisted', undefined, 'zaten vardı')}: ${j.skipped.join(', ')}` : ''}`;
  });

  const exportAgent = () => run(async () => {
    const res = await fetch(api(`/api/agents/${agent!.id}/export`));
    if (!res.ok) throw new Error(await errorText(res));
    const blob = new Blob([JSON.stringify((await res.json()).package, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `ajan-${agent!.id.toLowerCase()}.json`;
    a.click();
    URL.revokeObjectURL(url);
    return t('agents.tools.exported', { id: agent!.id }, '✓ Ajan paketi indirildi ({id}).');
  });

  const importFile = (file: File | undefined) => {
    if (!file) return;
    run(async () => {
      const pkg = JSON.parse(await file.text());
      let res = await fetch(api('/api/agents/import'), { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ package: pkg }) });
      if (res.status === 409 && await confirmDialog(`${(await errorText(res))}\n\n${t('agents.tools.overwrite', undefined, 'Üzerine yazılsın mı?')}`)) {
        res = await fetch(api('/api/agents/import'), { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ package: pkg, replace: true }) });
      }
      if (!res.ok) throw new Error(await errorText(res));
      return `✓ ${t('agents.tools.imported', undefined, 'İçe aktarıldı')}: ${(await res.json()).agent?.id}`;
    });
  };

  const promote = () => run(async () => {
    const res = await fetch(api(`/api/agents/${agent!.id}/promote-definition`), { method: 'POST' });
    if (!res.ok) throw new Error(await errorText(res));
    return t('agents.tools.promoted', { id: agent!.id }, '✓ {id} şirket geneli ajan oldu; diğer projelerde de görünür.');
  });

  const resetOverrides = () => run(async () => {
    const keys = Object.keys(agent?.overrides || {});
    const res = await fetch(api(`/api/agents/${agent!.id}`), {
      method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ reset_overrides: keys }),
    });
    if (!res.ok) throw new Error(await errorText(res));
    return t('agents.tools.resetDone', { keys: keys.join(', ') }, '✓ Projeye özgü fark geri alındı ({keys}).');
  });

  const scope = agent ? agentScope(agent) : null;
  const overrideKeys = Object.keys(agent?.overrides || {});

  return (
    <div className="space-y-2 rounded-xl border border-line bg-panel/60 p-3" data-testid="agent-tools-bar">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-[11px] font-bold text-ink uppercase tracking-wider flex items-center gap-1.5"><Layers className="w-3.5 h-3.5 text-ac" /> {t('agents.tools.templates', undefined, 'Takım şablonları')}</span>
        <select value={templateKey} onChange={e => setTemplateKey(e.target.value)} className="bg-panel border border-line2 rounded-lg px-2 py-1 text-xs text-ink font-mono cursor-pointer">
          <option value="">{t('agents.tools.pickTemplate', undefined, 'Şablon seç…')}</option>
          {templates.map(tp => <option key={tp.key} value={tp.key}>{tp.name} ({t('agents.tools.agentCount', { n: tp.agents.length }, '{n} ajan')})</option>)}
        </select>
        <label className="flex items-center gap-1 text-[11px] text-ink2 cursor-pointer">
          <input type="checkbox" checked={templateGlobal} onChange={e => setTemplateGlobal(e.target.checked)} /> {t('agents.tools.companyWide', undefined, 'şirket geneli')}
        </label>
        <button type="button" disabled={!templateKey || busy} onClick={applyTemplate} className={`${btn} bg-acd text-ac border-ac/40 hover:opacity-90`}>{t('agents.tools.addTeam', undefined, 'Takımı ekle')}</button>
        <label className={`${btn} bg-sunk text-ink2 border-line hover:text-ink cursor-pointer`}>
          <Upload className="w-3.5 h-3.5" /> {t('agents.tools.import', undefined, 'Ajan paketi içe aktar')}
          <input type="file" accept="application/json,.json" className="hidden" onChange={e => { importFile(e.target.files?.[0]); e.target.value = ''; }} />
        </label>
      </div>
      {templateKey && (
        <p className="text-[10px] text-ink3">{templates.find(tp => tp.key === templateKey)?.description}</p>
      )}

      {agent && (
        <div className="flex flex-wrap items-center gap-2 border-t border-line pt-2">
          <span className="text-[11px] text-ink3">
            {t('agents.tools.scope', undefined, 'Kapsam')}: <b className="text-ink">{scope === 'core' ? t('agents.tools.scopeCore', undefined, 'çekirdek rol') : scope === 'global' ? t('agents.tools.companyWide', undefined, 'şirket geneli') : t('agents.tools.scopeProject', undefined, 'yalnızca bu proje')}</b>
          </span>
          <button type="button" disabled={busy} onClick={exportAgent} className={`${btn} bg-sunk text-ink2 border-line hover:text-ink`}>
            <Download className="w-3.5 h-3.5" /> {t('agents.tools.export', undefined, 'Dışa aktar')}
          </button>
          {scope === 'project' && (
            <button type="button" disabled={busy} onClick={promote} className={`${btn} bg-sunk text-ink2 border-line hover:text-ink`}>
              <Globe className="w-3.5 h-3.5" /> {t('agents.tools.promote', undefined, 'Şirket geneline terfi ettir')}
            </button>
          )}
          {scope === 'global' && overrideKeys.length > 0 && (
            <button type="button" disabled={busy} onClick={resetOverrides} className={`${btn} bg-sunk text-warn border-warn/40 hover:opacity-90`}>
              <Undo2 className="w-3.5 h-3.5" /> {t('agents.tools.resetBtn', undefined, 'Projeye özgü farkı geri al')} ({overrideKeys.join(', ')})
            </button>
          )}
        </div>
      )}

      {agent && health && (
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-line pt-2 text-[11px] text-ink2" data-testid="agent-health">
          <span className="flex items-center gap-1.5 font-bold text-ink uppercase tracking-wider text-[10px]"><HeartPulse className="w-3.5 h-3.5 text-ok" /> {t('agents.tools.health', undefined, 'Sağlık')}</span>
          <span>{t('agents.tools.hDelivered', undefined, 'teslim')} <b className="text-ink">{health.delivered}</b></span>
          <span>{t('agents.tools.hFirstPass', undefined, 'ilk seferde geçme')} <b className="text-ink">{health.first_pass_rate === null ? '—' : `%${Math.round(health.first_pass_rate * 100)}`}</b></span>
          <span>{t('agents.tools.hFixRounds', undefined, 'düzeltme turu')} <b className="text-ink">{health.fix_rounds}</b></span>
          <span>{t('agents.tools.hFailed', undefined, 'başarısız adım')} <b className="text-ink">{health.failed_steps}</b></span>
          <span>{t('agents.tools.hToken', undefined, 'token')} <b className="text-ink">{health.total_tokens.toLocaleString('tr-TR')}</b>{health.budget ? ` / ${health.budget.toLocaleString('tr-TR')}` : ''}</span>
          <span>{t('agents.tools.hPromptVer', undefined, 'istem sürümü')} <b className="text-ink">{health.prompt_versions}</b></span>
        </div>
      )}

      {msg && <p className={`text-[11px] ${msg.ok ? 'text-ok' : 'text-err'}`}>{msg.text}</p>}
    </div>
  );
};
