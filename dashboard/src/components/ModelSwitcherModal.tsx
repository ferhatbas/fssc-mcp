import { BudgetSettings } from './BudgetSettings';
import { notify } from '../lib/dialog';
import React, { useState, useEffect } from 'react';
import {
  LLMModelConfig, ProjectInfo, EngineSettings, McpClientInfo, ExecutionEngine, VerificationCommands, AutonomyOverview, AutonomyLevel, SandboxSettings,
} from '../types/telemetry';
import { api } from '../config';
import { ProjectLayoutCard } from './ProjectLayoutCard';
import { useI18n } from '../i18n';

type TFn = (key: string, params?: Record<string, string | number>, fallback?: string) => string;

const VERIFICATION_FIELDS: { key: keyof VerificationCommands; label: string; placeholder: string }[] = [
  { key: 'install', label: 'Kurulum', placeholder: 'python -m pip install -r requirements.txt' },
  { key: 'test', label: 'Test', placeholder: 'python -m pytest -q' },
  { key: 'build', label: 'Build', placeholder: 'npm run build' },
  { key: 'lint', label: 'Lint', placeholder: 'npm run lint' },
  { key: 'run', label: 'Çalıştır (E2E için)', placeholder: 'python -m uvicorn src.main:app --port 8000' },
  { key: 'health_url', label: 'Sağlık adresi', placeholder: 'http://127.0.0.1:8000/health' },
];

const LIFECYCLE_TOGGLES: { key: 'auto_backlog' | 'auto_verify' | 'auto_commit'; label: string; hint: string }[] = [
  { key: 'auto_backlog', label: 'Backlog → görev adımları', hint: 'Mimarın çıkardığı görevler koşuya otomatik eklenir ve sırayla geliştirilir' },
  { key: 'auto_verify', label: 'Sunucu doğrulaması', hint: 'Her teslimden sonra sözdizimi, kurulum, build ve test komutları bu makinede koşar; kalırsa düzeltme turu açılır' },
  { key: 'auto_commit', label: 'SCM commit', hint: 'Doğrulaması geçen teslimler proje klasöründe git ile commit\'lenir (depo yoksa açılır)' },
];
import { 
  X, 
  Sparkles, 
  Cpu, 
  CheckCircle2, 
  Layers, 
  Zap, 
  Sliders, 
  BookOpen, 
  HelpCircle,
  ExternalLink
} from 'lucide-react';

interface ModelSwitcherModalProps {
  isOpen: boolean;
  onClose: () => void;
  currentProject: ProjectInfo | null;
  modelConfig: LLMModelConfig | null;
  onUpdateModelConfig: (newConfig: Partial<LLMModelConfig>, projectId?: string) => Promise<any>;
  onOpenDocs?: () => void;
  /** Faz B: yürütme motoru ayarları ve bağlı MCP istemcileri */
  settings?: EngineSettings;
  connectedClients?: McpClientInfo[];
  onUpdateSettings?: (updates: Partial<EngineSettings>) => Promise<any>;
}

const ENGINE_OPTIONS: { id: ExecutionEngine; label: string; hint: string }[] = [
  { id: 'mcp_client', label: 'MCP İstemcisi', hint: 'Claude Desktop / Antigravity adımları kendi modeliyle üretir (API anahtarı gerekmez)' },
  { id: 'template', label: 'Şablon (Çevrimdışı)', hint: 'Sunucu hazır şablon çıktılarıyla demo koşusu yapar' },
];

// Etiketler/ipuçları Türkçe yedektir; görünen metin run.ms.* anahtarlarıyla çevrilir.
// G4: otonomi seviyeleri (sunucudaki PRESETS ile aynı anlam)
const LEVELS: { id: AutonomyLevel; label: string; hint: string }[] = [
  { id: 'L0', label: 'Gözetimli', hint: 'Her adım onay bekler; taahhüt elle; sorular süresiz bekler' },
  { id: 'L1', label: 'Kritik kapılar', hint: 'Yalnızca kritik adımlarda onay; taahhüt elle' },
  { id: 'L2', label: 'Not ve devam', hint: 'Adımlar notla sürer; taahhüt 30 dk sonra sunucuda; sıkı DoD açık' },
  { id: 'L3', label: 'Tam otonom', hint: 'Onay yok, taahhüt otomatik, sprintler zincirlenir, sorular önerilenle cevaplanır; ön koşullar şart' },
];

function timeAgo(t: TFn, iso?: string): string {
  if (!iso) return '';
  const diff = Math.max(0, Date.now() - new Date(iso).getTime());
  const s = Math.floor(diff / 1000);
  if (s < 60) return t('run.ms.agoSec', { n: s }, `${s} sn önce`);
  const m = Math.floor(s / 60);
  if (m < 60) return t('run.ms.agoMin', { n: m }, `${m} dk önce`);
  const h = Math.floor(m / 60);
  return t('run.ms.agoHour', { n: h }, `${h} sa önce`);
}

interface ProviderOption {
  id: 'gemini' | 'claude';
  name: string;
  tagline: string;
  iconBg: string;
  badgeBg: string;
  borderColor: string;
  models: {
    id: string;
    label: string;
    badge: string;
    description: string;
    contextWindow: string;
  }[];
}

const PROVIDER_DEFS: ProviderOption[] = [
  {
    id: 'gemini',
    name: 'Google Gemini',
    tagline: 'Google DeepMind • Çok Modlu Muhakeme & Kodlama',
    iconBg: 'from-ac to-ac',
    badgeBg: 'bg-infod text-info border-info/30',
    borderColor: 'border-info/40',
    models: [
      {
        id: 'gemini-2.5-pro',
        label: 'Gemini 2.5 Pro',
        badge: 'Önerilen (Kodlama & Mimari)',
        description: 'En gelişmiş mantıksal çıkarım, derin kod refactoring ve mimari tasarım yeteneği.',
        contextWindow: '2M Token'
      },
      {
        id: 'gemini-2.5-flash',
        label: 'Gemini 2.5 Flash',
        badge: 'Dengeli & Ekonomik',
        description: 'Hafif ve ekonomik görevler, hızlı birim test denetimleri için ideal.',
        contextWindow: '1M Token'
      },
      {
        id: 'gemini-2.0-flash-thinking-exp',
        label: 'Gemini 2.0 Flash Thinking',
        badge: 'Canlı Düşünce Akışı',
        description: 'Ajanların adım adım iç düşünce sürecini (Chain-of-Thought) üretir ve yayınlar.',
        contextWindow: '1M Token'
      },
      {
        id: 'gemini-3.8-flash-high',
        label: 'Gemini 3.8 Flash High',
        badge: 'Yüksek Hız',
        description: 'Çok hızlı yanıt süresi, telemetri ve anlık mesaj akışları için optimize edilmiş.',
        contextWindow: '1M Token'
      },
      {
        id: 'gemini-1.5-pro',
        label: 'Gemini 1.5 Pro',
        badge: 'Uzun Bağlam',
        description: '2 Milyon token devasa bağlam penceresi ile büyük depoları tek seferde analiz eder.',
        contextWindow: '2M Token'
      }
    ]
  },
  {
    id: 'claude',
    name: 'Anthropic Claude',
    tagline: 'Anthropic • Düşünce Tabanlı Kod Üretimi & MCP',
    iconBg: 'from-warn to-warn',
    badgeBg: 'bg-warnd text-warn border-warn/30',
    borderColor: 'border-warn/40',
    models: [
      {
        id: 'claude-sonnet-5-5',
        label: 'Claude Sonnet 5.5',
        badge: 'Önerilen (Varsayılan)',
        description: 'Kodlama hızı ve muhakeme dengesi; pipeline adımlarının çoğu için en iyi maliyet/performans.',
        contextWindow: '200k+ Token'
      },
      {
        id: 'claude-fable-5-1',
        label: 'Claude Fable 5.1',
        badge: 'En Gelişmiş',
        description: 'Mythos sınıfı; en karmaşık mimari, çok adımlı ajan koşuları ve zor düzeltme turları için.',
        contextWindow: '200k+ Token'
      },
      {
        id: 'claude-opus-5-5',
        label: 'Claude Opus 5.5',
        badge: 'Derin Akıl Yürütme',
        description: 'Büyük şartnameler, mimari kararlar ve kapsamlı kod incelemeleri için.',
        contextWindow: '200k+ Token'
      },
      {
        id: 'claude-haiku-5-5',
        label: 'Claude Haiku 5.5',
        badge: 'Hızlı & Ekonomik',
        description: 'Dokümantasyon, rapor ve küçük görevler; düşük gecikme.',
        contextWindow: '200k+ Token'
      }
    ]
  }
];

// Varsayılan sağlayıcı Claude: kartlarda ilk sırada gösterilir
const PROVIDERS: ProviderOption[] = [...PROVIDER_DEFS].sort((a, b) => (a.id === 'claude' ? -1 : b.id === 'claude' ? 1 : 0));

export const ModelSwitcherModal: React.FC<ModelSwitcherModalProps> = ({
  isOpen,
  onClose,
  currentProject,
  modelConfig,
  onUpdateModelConfig,
  onOpenDocs,
  settings,
  connectedClients = [],
  onUpdateSettings
}) => {
  const { t } = useI18n();
  const [engine, setEngine] = useState<ExecutionEngine>(settings?.execution_engine || 'mcp_client');
  const [engineSaving, setEngineSaving] = useState<boolean>(false);
  useEffect(() => {
    if (settings?.execution_engine) setEngine(settings.execution_engine);
  }, [settings?.execution_engine, isOpen]);

  const handleEngineChange = async (next: ExecutionEngine) => {
    setEngine(next);
    if (!onUpdateSettings) return;
    setEngineSaving(true);
    try {
      await onUpdateSettings({ execution_engine: next });
    } catch (err) {
      console.error(err);
    } finally {
      setEngineSaving(false);
    }
  };
  const lastClient = connectedClients.slice().sort((a, b) => (a.last_seen < b.last_seen ? 1 : -1))[0];
  const isMcpEngine = engine === 'mcp_client';

  // Tam yaşam döngüsü ayarları (limitler ve doğrulama komutları yerel taslakta tutulur, Kaydet ile gönderilir)
  const [limits, setLimits] = useState({ max_fix_rounds: 2, max_backlog_tasks: 12, max_uat_rounds: 1 });
  const [verification, setVerification] = useState<VerificationCommands>({});
  const [lifecycleSaving, setLifecycleSaving] = useState(false);
  const [lifecycleMsg, setLifecycleMsg] = useState('');
  useEffect(() => {
    setLimits({
      max_fix_rounds: settings?.max_fix_rounds ?? 2,
      max_backlog_tasks: settings?.max_backlog_tasks ?? 12,
      max_uat_rounds: settings?.max_uat_rounds ?? 1,
    });
    setVerification({ ...(settings?.verification || {}) });
  }, [settings?.max_fix_rounds, settings?.max_backlog_tasks, settings?.max_uat_rounds, settings?.verification, isOpen]);

  const saveLifecycle = async () => {
    if (!onUpdateSettings) return;
    setLifecycleSaving(true);
    setLifecycleMsg('');
    try {
      const cleaned: VerificationCommands = {};
      (Object.keys(verification) as (keyof VerificationCommands)[]).forEach(k => {
        const v = (verification[k] || '').trim();
        if (v) cleaned[k] = v;
      });
      await onUpdateSettings({ ...limits, verification: cleaned });
      setLifecycleMsg(t('run.ms.lifecycleSaved', undefined, '✓ Döngü ayarları kaydedildi'));
      setTimeout(() => setLifecycleMsg(''), 1800);
    } catch (err) {
      console.error(err);
      setLifecycleMsg(t('run.ms.notSaved', undefined, '⚠ Kaydedilemedi'));
    } finally {
      setLifecycleSaving(false);
    }
  };

  const [selectedProvider, setSelectedProvider] = useState<'gemini' | 'claude'>('claude');
  const [selectedModel, setSelectedModel] = useState<string>('claude-sonnet-5-5');
  const [temperature, setTemperature] = useState<number>(0.2);
  const [maxTokens, setMaxTokens] = useState<number>(8192);
  const [isSaving, setIsSaving] = useState<boolean>(false);
  const [statusMsg, setStatusMsg] = useState<string>('');

  // G4: otonomi seviyesi, L3 ön koşulları ve komut yalıtımı
  const [auto, setAuto] = useState<AutonomyOverview | null>(null);
  const [autoMsg, setAutoMsg] = useState<string>('');
  const [autoBusy, setAutoBusy] = useState<boolean>(false);
  const loadAutonomy = async () => {
    try {
      const res = await fetch(api('/api/autonomy/overview'));
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setAuto(await res.json());
    } catch (err) {
      console.error(err);
      setAutoMsg(t('run.ms.autonomyReadErr', undefined, '⚠ Otonomi durumu okunamadı'));
    }
  };
  useEffect(() => {
    if (isOpen) {
      setAutoMsg('');
      loadAutonomy();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isOpen]);
  const applyLevel = async (level: AutonomyLevel) => {
    setAutoBusy(true);
    setAutoMsg('');
    try {
      const res = await fetch(api('/api/autonomy/preset'), { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ level }) });
      const data = await res.json().catch(() => ({}));
      setAutoMsg(res.ok ? t('run.ms.levelApplied', { level }, `✓ Seviye ${level} uygulandı`) : `⚠ ${data.error || `HTTP ${res.status}`}`);
      await loadAutonomy();
    } catch (err) {
      console.error(err);
      setAutoMsg(t('run.ms.levelErr', undefined, '⚠ Seviye uygulanamadı'));
    } finally {
      setAutoBusy(false);
    }
  };
  const updateSandbox = async (patch: Partial<SandboxSettings>) => {
    setAutoBusy(true);
    setAutoMsg('');
    try {
      const res = await fetch(api('/api/settings/sandbox'), { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(patch) });
      const data = await res.json().catch(() => ({}));
      setAutoMsg(res.ok ? t('run.ms.sandboxSaved', undefined, '✓ Yalıtım ayarı kaydedildi') : `⚠ ${data.error || `HTTP ${res.status}`}`);
      await loadAutonomy();
    } catch (err) {
      console.error(err);
      setAutoMsg(t('run.ms.sandboxErr', undefined, '⚠ Yalıtım ayarı kaydedilemedi'));
    } finally {
      setAutoBusy(false);
    }
  };

  useEffect(() => {
    if (modelConfig) {
      const p = (modelConfig.provider === 'gemini' ? 'gemini' : 'claude') as 'gemini' | 'claude';
      setSelectedProvider(p);
      setSelectedModel(modelConfig.model_id || (p === 'claude' ? 'claude-sonnet-5-5' : 'gemini-2.5-pro'));
      if (modelConfig.temperature !== undefined) setTemperature(modelConfig.temperature);
      if (modelConfig.max_tokens !== undefined) setMaxTokens(modelConfig.max_tokens);
    }
  }, [modelConfig, isOpen]);

  if (!isOpen) return null;

  const handleProviderSelect = (providerId: 'gemini' | 'claude') => {
    setSelectedProvider(providerId);
    if (providerId === 'claude') {
      setSelectedModel('claude-sonnet-5-5');
    } else {
      setSelectedModel('gemini-2.5-pro');
    }
  };

  const handleSave = async () => {
    setIsSaving(true);
    setStatusMsg('');
    try {
      await onUpdateModelConfig({
        provider: selectedProvider,
        model_id: selectedModel,
        temperature,
        max_tokens: maxTokens
      }, currentProject?.id);

      setStatusMsg(t('run.ms.modelUpdated', { m: `${selectedProvider.toUpperCase()} / ${selectedModel}` }, `✓ Model başarıyla güncellendi: ${selectedProvider.toUpperCase()} / ${selectedModel}`));
      setTimeout(() => {
        setStatusMsg('');
        onClose();
      }, 1200);
    } catch (err: any) {
      console.error(err);
      notify(t('run.ms.modelSaveErr', undefined, 'Model ayarı kaydedilirken hata oluştu.'));
    } finally {
      setIsSaving(false);
    }
  };

  const activeProviderMeta = PROVIDERS.find(p => p.id === selectedProvider) || PROVIDERS[0];

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm animate-fadeIn">
      <div className="bg-panel border border-line rounded-panel w-full max-w-2xl max-h-[92vh] flex flex-col shadow-panel overflow-hidden">
        
        {/* Üst Başlık */}
        <div className="px-6 py-4 bg-panel2 border-b border-line flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className={`w-10 h-10 rounded-xl bg-gradient-to-br ${activeProviderMeta.iconBg} p-0.5 flex items-center justify-center shadow-sm`}>
              <Cpu className="w-5 h-5 text-ink" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h3 className="text-base font-bold text-ink tracking-wide font-sans">
                  {t('run.ms.title', undefined, 'LLM Model & Sağlayıcı Değiştir')}
                </h3>
                {currentProject && (
                  <span className="text-[10px] bg-acd text-ac border border-ac/30 px-2 py-0.5 rounded-full font-mono flex items-center gap-1 font-semibold">
                    <Layers className="w-3 h-3 text-ac" />
                    {currentProject.name} (.fs-workspace)
                  </span>
                )}
              </div>
              <p className="text-xs text-ink3">
                {t('run.ms.subtitle', undefined, 'Şirket ajanlarının ve orkestratörün çalışacağı büyük dil modelini anlık olarak belirleyin')}
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="text-ink3 hover:text-ink p-1.5 rounded-lg hover:bg-sunk transition"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Gövde */}
        <div className="flex-1 overflow-y-auto p-6 space-y-6">
          {statusMsg && (
            <div className="p-3 bg-okd border border-ok/40 rounded-lg text-ok text-xs flex items-center gap-2 font-medium animate-fadeIn">
              <CheckCircle2 className="w-4 h-4 text-ok shrink-0" />
              <span>{statusMsg}</span>
            </div>
          )}

          {/* 0. Yürütme Motoru (Faz B) */}
          <div>
            <label className="block text-[11px] font-bold text-ink uppercase tracking-wider mb-2.5 font-mono">
              {t('run.ms.engineHead', undefined, '0. Yürütme Motoru')}
            </label>
            <div className="flex items-center bg-sunk p-0.5 rounded-lg border border-line text-xs font-mono w-fit">
              {ENGINE_OPTIONS.map(opt => (
                <button
                  key={opt.id}
                  type="button"
                  onClick={() => handleEngineChange(opt.id)}
                  disabled={engineSaving}
                  title={t(`run.ms.engine.${opt.id}.hint`, undefined, opt.hint)}
                  className={`px-3 py-1.5 rounded-md transition font-medium ${
                    engine === opt.id ? 'bg-ac text-onac shadow-panel font-bold' : 'text-ink3 hover:text-ink'
                  }`}
                >
                  {t(`run.ms.engine.${opt.id}.label`, undefined, opt.label)}
                </button>
              ))}
            </div>
            <p className="text-[11px] text-ink3 mt-2">
              {t(`run.ms.engine.${engine}.hint`, undefined, ENGINE_OPTIONS.find(o => o.id === engine)?.hint)}
            </p>
            {isMcpEngine && (
              <div className="mt-2 text-[11px] font-mono flex items-center gap-2 flex-wrap">
                <span className="text-ink2">{t('run.ms.connectedClient', undefined, 'Bağlı istemci:')}</span>
                {lastClient ? (
                  <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-md bg-okd text-ok border border-ok/30">
                    <span className="w-1.5 h-1.5 rounded-full bg-ok" />
                    {lastClient.name}{lastClient.version ? ` v${lastClient.version}` : ''} • {timeAgo(t, lastClient.last_seen)} • {t('run.ms.callsN', { n: lastClient.calls }, `${lastClient.calls} çağrı`)}
                  </span>
                ) : (
                  <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-md bg-warnd text-warn border border-warn/30">
                    {t('run.ms.notSeen', undefined, "henüz görülmedi — Claude Desktop'ta MCP sunucusunu bağlayıp pipeline promptunu yazın")}
                  </span>
                )}
              </div>
            )}
          </div>

          {/* C5: Akış hızı (şablon motorunda olaylar arası doğal bekleme) */}
          <div>
            <label className="block text-[11px] font-bold text-ink uppercase tracking-wider mb-2.5 font-mono">
              {t('run.ms.paceHead', undefined, '0b. Akış Hızı')}
            </label>
            <div className="flex items-center bg-sunk p-0.5 rounded-lg border border-line text-xs font-mono w-fit">
              {([['natural', 'Doğal'], ['instant', 'Anında']] as const).map(([id, label]) => (
                <button
                  key={id}
                  type="button"
                  onClick={() => onUpdateSettings?.({ pacing: id })}
                  className={`px-3 py-1.5 rounded-md transition font-medium ${
                    (settings?.pacing || 'natural') === id ? 'bg-ac text-onac shadow-panel font-bold' : 'text-ink3 hover:text-ink'
                  }`}
                >
                  {t(`run.ms.pace.${id}`, undefined, label)}
                </button>
              ))}
            </div>
            <p className="text-[11px] text-ink3 mt-2">
              {t('run.ms.paceHelp', undefined, 'Doğal: ajan diyalogları insan hızında, olaylar arasında kısa beklemelerle akar (yalnızca şablon motoru). Anında: bekleme yok. MCP istemcisinde hız zaten modelin üretim süresince doğaldır.')}
            </p>
          </div>

          {/* 0c. Tam otomatik geliştirme döngüsü */}
          <div className="bg-panel2 border border-line rounded-xl p-4 space-y-3 shadow-xs">
            <div className="flex items-center justify-between gap-2 flex-wrap">
              <label className="text-[11px] font-bold text-ink uppercase tracking-wider font-mono">
                {t('run.ms.lifecycleHead', undefined, '0c. Otomatik Geliştirme Döngüsü')}
              </label>
              {lifecycleMsg && <span className="text-[11px] font-mono text-ok">{lifecycleMsg}</span>}
            </div>
            <p className="text-[11px] text-ink3">
              {t('run.ms.lifecycleHelp', undefined, 'Mimar (adım 2) şartnameyi görevlere böler; her görev teslim edildikçe sunucu test/build koşar, kalırsa aynı görev için düzeltme turu açar, geçerse SCM commit atar. E2E adımı (7) uygulamayı Çalıştır komutuyla gerçekten başlatır. PO (adım 9) reddederse eksikler yeni görev olarak açılır, QA ve UAT yeniden koşar.')}
            </p>
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
              {LIFECYCLE_TOGGLES.map(lt => {
                const on = settings?.[lt.key] !== false;
                return (
                  <button
                    key={lt.key}
                    type="button"
                    onClick={() => onUpdateSettings?.({ [lt.key]: !on } as Partial<EngineSettings>)}
                    title={t(`run.ms.lc.${lt.key}.hint`, undefined, lt.hint)}
                    className={`text-left p-2.5 rounded-lg border transition ${on ? 'bg-okd/60 border-ok/50' : 'bg-sunk border-line hover:border-line2'}`}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-xs font-semibold text-ink">{t(`run.ms.lc.${lt.key}.label`, undefined, lt.label)}</span>
                      <span className={`text-[10px] font-mono px-1.5 py-0.5 rounded border ${on ? 'bg-ok text-onac border-ok' : 'bg-panel2 text-ink3 border-line'}`}>{on ? t('run.ms.on', undefined, 'AÇIK') : t('run.ms.off', undefined, 'KAPALI')}</span>
                    </div>
                    <div className="text-[10px] text-ink3 mt-1 leading-snug">{t(`run.ms.lc.${lt.key}.hint`, undefined, lt.hint)}</div>
                  </button>
                );
              })}
            </div>
            <div className="grid grid-cols-3 gap-3">
              {([['max_fix_rounds', 'Düzeltme turu / görev'], ['max_backlog_tasks', 'En fazla görev'], ['max_uat_rounds', 'UAT iyileştirme turu']] as const).map(([key, label]) => (
                <label key={key} className="text-[11px] text-ink2 font-medium">
                  {t(`run.ms.limit.${key}`, undefined, label)}
                  <input
                    type="number" min={0} max={50}
                    value={limits[key]}
                    onChange={e => setLimits(prev => ({ ...prev, [key]: Math.max(0, Math.min(50, parseInt(e.target.value || '0', 10))) }))}
                    className="mt-1 w-full bg-sunk border border-line rounded-lg px-2.5 py-1.5 text-xs text-ink font-mono focus:border-ac focus:outline-none"
                  />
                </label>
              ))}
            </div>
            <div>
              <div className="text-[11px] text-ink2 font-medium mb-1.5">
                {t('run.ms.verifyCmds', undefined, 'Doğrulama / çalıştırma komutları')} <span className="text-ink3">{t('run.ms.verifyCmdsHint', undefined, "(proje kökünde koşar; boş bırakılan alan requirements.txt / package.json / composer.json / go.mod'dan çıkarsanır)")}</span>
              </div>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                {VERIFICATION_FIELDS.map(f => (
                  <label key={f.key} className="text-[10px] text-ink3 font-mono">
                    {t(`run.ms.ver.${f.key}`, undefined, f.label)}
                    <input
                      type="text"
                      value={verification[f.key] || ''}
                      onChange={e => setVerification(prev => ({ ...prev, [f.key]: e.target.value }))}
                      placeholder={f.placeholder}
                      className="mt-0.5 w-full bg-sunk border border-line rounded-lg px-2.5 py-1.5 text-xs text-ink font-mono focus:border-ac focus:outline-none"
                    />
                  </label>
                ))}
              </div>
            </div>
            <div className="flex items-center justify-between gap-2 flex-wrap">
              <span className="text-[10px] text-ink3">{t('run.ms.cmdsNote', undefined, 'Komutlar bu makinede çalışır; mimarın önerdiği komutlar yasaklı kalıplardan (rm -rf /, curl | sh …) geçirilerek buraya yazılır.')}</span>
              <button
                type="button"
                onClick={saveLifecycle}
                disabled={lifecycleSaving || !onUpdateSettings}
                className="px-3.5 py-1.5 bg-ink text-bg font-bold rounded-lg text-xs shadow-panel hover:opacity-90 transition disabled:opacity-50"
              >
                {lifecycleSaving ? t('run.ms.saving', undefined, 'Kaydediliyor…') : t('run.ms.saveLifecycle', undefined, 'Döngü Ayarlarını Kaydet')}
              </button>
            </div>
          </div>

          {/* 0d. Otonomi seviyesi ve komut yalıtımı (G4) */}
          <div className="bg-panel2 border border-line rounded-xl p-4 space-y-3 shadow-xs">
            <div className="flex items-center justify-between gap-2 flex-wrap">
              <label className="text-[11px] font-bold text-ink uppercase tracking-wider font-mono">
                {t('run.ms.autonomyHead', undefined, '0d. Otonomi Seviyesi ve Komut Yalıtımı')}
              </label>
              <div className="flex items-center gap-2">
                {autoMsg && <span className={`text-[11px] font-mono ${autoMsg.startsWith('⚠') ? 'text-err' : 'text-ok'}`}>{autoMsg}</span>}
                <button type="button" onClick={loadAutonomy} className="text-[10px] font-mono text-ink3 hover:text-ink">{t('run.ms.refresh', undefined, 'yenile')}</button>
              </div>
            </div>
            <p className="text-[11px] text-ink3">
              {t('run.ms.autonomyHelp', undefined, 'L0 her adımda onay bekler; L1 yalnızca kritik kapılarda; L2 not düşer ve sürer (taahhüt zaman aşımıyla sunucuda); L3 tam otonom. L3 yalnızca aşağıdaki ön koşullar sağlanınca açılır; teknoloji kararları kapısı hiçbir seviyede atlanmaz.')}
            </p>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
              {LEVELS.map(l => {
                const on = auto?.level === l.id;
                return (
                  <button
                    key={l.id}
                    type="button"
                    disabled={autoBusy || !auto}
                    onClick={() => applyLevel(l.id)}
                    title={t(`run.ms.lvl.${l.id}.hint`, undefined, l.hint)}
                    className={`text-left p-2.5 rounded-lg border transition disabled:opacity-60 ${on ? 'bg-okd/60 border-ok/50' : 'bg-sunk border-line hover:border-line2'}`}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-xs font-semibold text-ink">{l.id} · {t(`run.ms.lvl.${l.id}.label`, undefined, l.label)}</span>
                      {on && <span className="text-[10px] font-mono px-1.5 py-0.5 rounded border bg-ok text-onac border-ok">{t('run.ms.active', undefined, 'AKTİF')}</span>}
                    </div>
                    <div className="text-[10px] text-ink3 mt-1 leading-snug">{t(`run.ms.lvl.${l.id}.hint`, undefined, l.hint)}</div>
                  </button>
                );
              })}
            </div>
            {auto?.level === 'CUSTOM' && (
              <div className="text-[10px] font-mono text-warn">
                {t('run.ms.customNote', { mode: settings?.approval_mode || '—', timeout: auto.autonomy.question_timeout_s ?? t('run.ms.indefinite', undefined, 'süresiz'), dod: auto.autonomy.strict_dod ? t('run.ms.openLc', undefined, 'açık') : t('run.ms.closedLc', undefined, 'kapalı') }, `Anahtarlar bir ön ayara uymuyor (CUSTOM): onay modu ${settings?.approval_mode || '—'}, soru zaman aşımı ${auto.autonomy.question_timeout_s ?? 'süresiz'} sn, sıkı DoD ${auto.autonomy.strict_dod ? 'açık' : 'kapalı'}.`)}
              </div>
            )}
            <div className="p-2.5 rounded-lg border border-line bg-sunk">
              <div className="text-[10px] font-mono uppercase tracking-wider text-ink3 mb-1.5">{t('run.ms.sprintBudget', undefined, 'Sprint bütçesi (autonomy.budget)')}</div>
              <div className="text-[10px] text-ink3 mb-2">{t('run.ms.budgetHelp', undefined, 'Sprint bu sınırlardan birine ulaşınca durur (BUDGET_EXCEEDED); sınırı artırınca sprint panosundan "Engeli kaldır ve sürdür" ile devam edilir.')}</div>
              <BudgetSettings />
            </div>
            <div>
              <div className="text-[11px] text-ink2 font-medium mb-1.5">
                {t('run.ms.l3Prereq', undefined, 'L3 ön koşulları')}{' '}
                {auto && (auto.l3_ok
                  ? <span className="text-ok">· {t('run.ms.allMet', undefined, 'hepsi sağlandı')}</span>
                  : <span className="text-ink3">· {t('run.ms.missingN', { n: auto.checks.filter(c => !c.ok).length }, `${auto.checks.filter(c => !c.ok).length} eksik`)}</span>)}
              </div>
              <ul className="text-xs space-y-1.5">
                {(auto?.checks || []).map(c => (
                  <li key={c.key} className="flex items-start gap-2">
                    <span className={`mt-1 w-2.5 h-2.5 rounded-full shrink-0 ${c.ok ? 'bg-ok' : 'bg-err'}`} />
                    <div className="min-w-0">
                      <div className="text-ink">{c.text}</div>
                      {!c.ok && c.fix && <div className="text-[10.5px] text-ink3">{c.fix}</div>}
                    </div>
                  </li>
                ))}
                {!auto && <li className="text-ink3">{t('run.ms.loading', undefined, 'Yükleniyor…')}</li>}
              </ul>
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
              <div className="p-2.5 rounded-lg border border-line bg-sunk">
                <div className="text-[10px] font-mono uppercase tracking-wider text-ink3 mb-1.5">{t('run.ms.isolation', undefined, 'Komut yalıtımı (sandbox.mode)')}</div>
                <div className="flex gap-1.5 flex-wrap">
                  {(['host', 'container'] as const).map(m => (
                    <button
                      key={m}
                      type="button"
                      disabled={autoBusy || !auto || (m === 'container' && !auto.docker_available)}
                      onClick={() => updateSandbox({ mode: m })}
                      className={`px-2.5 py-1 rounded-md border text-[11px] font-mono transition disabled:opacity-50 ${auto?.sandbox.mode === m ? 'bg-ink text-bg border-ink' : 'bg-panel2 text-ink2 border-line hover:border-line2'}`}
                    >
                      {m === 'host' ? t('run.ms.modeHost', undefined, 'host (bu makine)') : t('run.ms.modeContainer', undefined, 'container (Docker)')}
                    </button>
                  ))}
                </div>
                <div className="text-[10px] text-ink3 mt-1.5">
                  Docker: {auto ? (auto.docker_available ? t('run.ms.dockerAvail', undefined, 'kullanılabilir') : t('run.ms.dockerNone', undefined, 'yok ya da çalışmıyor (container kipi seçilemez)')) : '…'} · {t('run.ms.containerNote', undefined, "container kipinde kurulum, lint, build ve test tek konteynerde koşar (proje /work; pip/npm önbelleği hacimde; Docker yoksa host'a düşülmez).")}
                </div>
              </div>
              <div className="p-2.5 rounded-lg border border-line bg-sunk">
                <div className="text-[10px] font-mono uppercase tracking-wider text-ink3 mb-1.5">{t('run.ms.policy', undefined, 'Komut politikası (sandbox.command_policy)')}</div>
                <div className="flex gap-1.5 flex-wrap">
                  {(['allowlist', 'denylist'] as const).map(p => (
                    <button
                      key={p}
                      type="button"
                      disabled={autoBusy || !auto}
                      onClick={() => updateSandbox({ command_policy: p })}
                      className={`px-2.5 py-1 rounded-md border text-[11px] font-mono transition disabled:opacity-50 ${auto?.sandbox.command_policy === p ? 'bg-ink text-bg border-ink' : 'bg-panel2 text-ink2 border-line hover:border-line2'}`}
                    >
                      {p === 'allowlist' ? t('run.ms.allowlist', undefined, 'izin listesi (varsayılan)') : t('run.ms.denylist', undefined, 'yasak listesi')}
                    </button>
                  ))}
                </div>
                <div className="text-[10px] text-ink3 mt-1.5">
                  {t('run.ms.policyNote', undefined, 'İzin listesinde yalnızca bilinen araçlar (python, pytest, npm, npx, node, go, dotnet, docker …) ve yönetici onaylı önekler koşar; liste dışı komut soruya dönüşür.')} {auto?.sandbox.allowlist?.length ? t('run.ms.extraPrefixes', { list: auto.sandbox.allowlist.join(', ') }, `Ek önekler: ${auto.sandbox.allowlist.join(', ')}`) : t('run.ms.noExtraPrefix', undefined, 'Ek önek yok.')}
                </div>
              </div>
            </div>
          </div>

          {/* 0e. Proje klasör düzeni (apps/devops/docs) ve göç */}
          <ProjectLayoutCard projectId={currentProject?.id} projectName={currentProject?.name} />

          {isMcpEngine && (
            <div className="bg-infod/40 border border-info/30 rounded-xl p-3 text-xs text-ink flex items-start gap-2.5">
              <HelpCircle className="w-4 h-4 text-info shrink-0 mt-0.5" />
              <p>
                <strong>{t('run.ms.mcpModelHead', undefined, 'Model Claude Desktop içinde seçilir.')}</strong> {t('run.ms.mcpModelText', undefined, "MCP istemcisi modunda aşağıdaki sağlayıcı/model seçimi yalnızca bilgilendiricidir; gerçek üretim, Claude Desktop'ta (veya Antigravity'de) seçili modelle, sizin aboneliğinizle yapılır.")}
              </p>
            </div>
          )}

          {/* 1. Sağlayıcı Seçimi Kartları (Gemini vs Claude) */}
          <div>
            <label className="block text-[11px] font-bold text-ink uppercase tracking-wider mb-2.5 font-mono">
              {t('run.ms.providerHead', undefined, '1. LLM Sağlayıcısını Seçin')}{isMcpEngine ? ` ${t('run.ms.informational', undefined, '(bilgilendirici)')}` : ''}
            </label>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              {PROVIDERS.map(p => {
                const isSelected = selectedProvider === p.id;
                return (
                  <button
                    key={p.id}
                    type="button"
                    onClick={() => handleProviderSelect(p.id)}
                    className={`p-4 rounded-xl border text-left transition relative flex flex-col justify-between ${
                      isSelected
                        ? p.id === 'claude'
                          ? 'bg-warnd/60 border-warn ring-2 ring-warn/30 shadow-sm'
                          : 'bg-infod/60 border-info ring-2 ring-info/30 shadow-sm'
                        : 'bg-panel2 border-line hover:border-line2'
                    }`}
                  >
                    <div className="flex items-start justify-between mb-2">
                      <div className="flex items-center gap-2.5">
                        <div className={`w-8 h-8 rounded-lg bg-gradient-to-br ${p.iconBg} flex items-center justify-center text-ink shadow`}>
                          {p.id === 'claude' ? <Zap className="w-4 h-4" /> : <Sparkles className="w-4 h-4" />}
                        </div>
                        <div>
                          <h4 className="text-sm font-bold text-ink font-sans">{p.name}</h4>
                          <span className="text-[10px] text-ink3 font-sans">{t(`run.ms.prov.${p.id}.tagline`, undefined, p.tagline)}</span>
                        </div>
                      </div>
                      {isSelected && (
                        <div className={`w-5 h-5 rounded-full ${p.id === 'claude' ? 'bg-warn text-onac' : 'bg-info text-onac'} flex items-center justify-center`}>
                          <CheckCircle2 className="w-3.5 h-3.5" />
                        </div>
                      )}
                    </div>
                  </button>
                );
              })}
            </div>
          </div>

          {/* 2. Seçili Sağlayıcının Modelini Belirleyin */}
          <div>
            <div className="flex items-center justify-between mb-2.5">
              <label className="text-[11px] font-bold text-ink uppercase tracking-wider font-mono">
                {t('run.ms.modelHead', undefined, '2. Aktif Modeli Seçin')} ({activeProviderMeta.name})
              </label>
              <span className="text-[10px] text-ink3 font-mono">
                {t('run.ms.modelsReady', { n: activeProviderMeta.models.length }, `${activeProviderMeta.models.length} Model Hazır`)}
              </span>
            </div>

            <div className="space-y-2.5">
              {activeProviderMeta.models.map(m => {
                const isSelected = selectedModel === m.id;
                return (
                  <div
                    key={m.id}
                    onClick={() => setSelectedModel(m.id)}
                    className={`p-3.5 rounded-xl border cursor-pointer transition flex items-center justify-between gap-3 ${
                      isSelected
                        ? selectedProvider === 'claude'
                          ? 'bg-warnd/50 border-warn shadow-xs'
                          : 'bg-infod/50 border-info shadow-xs'
                        : 'bg-panel2 border-line hover:border-line2'
                    }`}
                  >
                    <div className="space-y-1">
                      <div className="flex items-center gap-2">
                        <span className="text-xs font-bold text-ink font-mono">{m.label}</span>
                        <span className={`text-[10px] px-2 py-0.2 rounded-full font-mono border font-semibold ${
                          isSelected
                            ? selectedProvider === 'claude'
                              ? 'bg-warnd text-warn border-warn/40'
                              : 'bg-infod text-info border-info/40'
                            : 'bg-sunk text-ink3 border-line'
                        }`}>
                          {t(`run.ms.model.${m.id}.badge`, undefined, m.badge)}
                        </span>
                        <span className="text-[10px] text-ink3 font-mono">
                          {m.contextWindow}
                        </span>
                      </div>
                      <p className="text-[11px] text-ink2 leading-relaxed">
                        {t(`run.ms.model.${m.id}.desc`, undefined, m.description)}
                      </p>
                    </div>

                    <div className="shrink-0">
                      <input
                        type="radio"
                        checked={isSelected}
                        onChange={() => setSelectedModel(m.id)}
                        className="w-4 h-4 text-ac focus:ring-ac cursor-pointer"
                      />
                    </div>
                  </div>
                );
              })}
            </div>

            {/* Özel Model ID Girişi (Claude Desktop veya Custom Model) */}
            <div className="mt-3 p-3 rounded-xl border border-line bg-panel2 flex flex-col gap-2 shadow-xs">
              <div className="flex items-center justify-between">
                <span className="text-xs font-bold text-ink font-mono flex items-center gap-1.5">
                  <Sliders className="w-3.5 h-3.5 text-ac" />
                  {t('run.ms.customModelId', undefined, 'Özel Model ID (Custom / Claude Desktop)')}
                </span>
                <span className="text-[10px] text-ink3 font-mono">
                  {t('run.ms.customModelHint', undefined, 'İstediğiniz model kodunu doğrudan belirleyebilirsiniz')}
                </span>
              </div>
              <div className="flex items-center gap-2">
                <input
                  type="text"
                  value={selectedModel}
                  onChange={e => setSelectedModel(e.target.value)}
                  placeholder={t('run.ms.customModelPh', undefined, 'Örn: claude-sonnet-5-5, claude-fable-5-1, claude-opus-5-5, claude-haiku-5-5')}
                  className="flex-1 bg-sunk border border-line rounded-lg px-3 py-1.5 text-xs text-ink font-mono focus:border-ac focus:outline-none transition"
                />
              </div>
            </div>
          </div>

          {/* 3. İnce Ayar Parametreleri (Temperature & Max Tokens) */}
          <div className="bg-panel2 border border-line rounded-xl p-4 space-y-3 shadow-xs">
            <h5 className="text-[11px] font-bold text-ink uppercase tracking-wider flex items-center gap-1.5 font-mono">
              <Sliders className="w-3.5 h-3.5 text-ac" />
              {t('run.ms.advanced', undefined, 'Gelişmiş Parametreler')}
            </h5>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div>
                <div className="flex items-center justify-between mb-1">
                  <label className="text-[11px] text-ink2 font-medium">{t('run.ms.temperature', undefined, 'Sıcaklık (Temperature)')}</label>
                  <span className="text-[11px] font-mono text-ac font-bold">{temperature}</span>
                </div>
                <input
                  type="range"
                  min="0.0"
                  max="1.0"
                  step="0.05"
                  value={temperature}
                  onChange={e => setTemperature(parseFloat(e.target.value))}
                  className="w-full accent-ac cursor-pointer"
                />
                <p className="text-[10px] text-ink3 mt-0.5">
                  {t('run.ms.temperatureHelp', undefined, 'Düşük (0.0-0.3): Deterministik, hatasız kodlama. Yüksek: Yaratıcı çözümler.')}
                </p>
              </div>

              <div>
                <div className="flex items-center justify-between mb-1">
                  <label className="text-[11px] text-ink2 font-medium">{t('run.ms.maxTokens', undefined, 'Maksimum Token')}</label>
                  <span className="text-[11px] font-mono text-ok font-bold">{maxTokens}</span>
                </div>
                <select
                  value={maxTokens}
                  onChange={e => setMaxTokens(parseInt(e.target.value))}
                  className="w-full bg-sunk border border-line rounded-lg px-3 py-1.5 text-xs text-ink focus:border-ac focus:outline-none cursor-pointer font-mono"
                >
                  <option value={4096}>{t('run.ms.tok4k', undefined, '4,096 Token (Standart Fonksiyonlar)')}</option>
                  <option value={8192}>{t('run.ms.tok8k', undefined, '8,192 Token (Önerilen - Kapsamlı Kod Üretimi)')}</option>
                  <option value={16384}>{t('run.ms.tok16k', undefined, '16,384 Token (Büyük Dosya / Mimari Çıktılar)')}</option>
                </select>
              </div>
            </div>
          </div>

          {/* Bilgi Kutusu & Kılavuz Bağlantısı */}
          <div className="bg-acd/40 border border-ac/30 rounded-xl p-3 flex items-start gap-2.5 text-xs text-ink">
            <HelpCircle className="w-4 h-4 text-ac shrink-0 mt-0.5" />
            <div className="space-y-1">
              <p>
                <strong>{t('run.ms.howHead', undefined, 'Nasıl Çalışır?')}</strong> {t('run.ms.howA', undefined, 'Model seçimi projenin')} <code className="text-ac font-bold font-mono">.fs-workspace/settings.json</code> {t('run.ms.howB', undefined, 'dosyasına yazılır ve şimdilik bilgi amaçlıdır: üretimi bağlı MCP istemcisi (Claude Desktop / Claude Code) kendi oturumunun modeliyle yapar; bu ayar onu değiştirmez. Ajan başına model/çaba seçimi ajan profilleriyle (plan G6) gelecek.')}
              </p>
              {onOpenDocs && (
                <button
                  type="button"
                  onClick={onOpenDocs}
                  className="text-ac hover:underline inline-flex items-center gap-1 font-mono text-[11px]"
                >
                  <BookOpen className="w-3 h-3" />
                  {t('run.ms.guideLink', undefined, 'docs/GEMINI_AND_CLAUDE_SETUP_GUIDE.md rehberini incele')}
                  <ExternalLink className="w-2.5 h-2.5" />
                </button>
              )}
            </div>
          </div>
        </div>

        {/* Alt Eylem Barı */}
        <div className="px-6 py-3 bg-panel2 border-t border-line flex items-center justify-between">
          <div className="text-[11px] text-ink3 font-mono flex items-center gap-1.5">
            <span>{t('run.ms.activeColon', undefined, 'Aktif:')}</span>
            <span className="text-ink font-bold">{selectedProvider.toUpperCase()} / {selectedModel}</span>
          </div>

          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={onClose}
              className="px-3.5 py-1.5 bg-sunk hover:bg-line text-ink rounded-lg text-xs font-medium transition border border-line"
            >
              {t('common.close', undefined, 'Kapat')}
            </button>
            <button
              type="button"
              onClick={handleSave}
              disabled={isSaving}
              className="px-4 py-1.5 bg-ink text-bg font-bold rounded-lg text-xs shadow-panel hover:opacity-90 transition flex items-center gap-1.5"
            >
              {isSaving ? (
                <>{t('run.ms.saving2', undefined, 'Kaydediliyor...')}</>
              ) : (
                <>
                  <CheckCircle2 className="w-3.5 h-3.5 text-ok" />
                  {t('run.ms.applySave', undefined, 'Modeli Uygula & Kaydet')}
                </>
              )}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};
