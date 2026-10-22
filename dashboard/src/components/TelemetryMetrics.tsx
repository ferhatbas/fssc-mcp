import React from 'react';
import { TelemetryStats } from '../types/telemetry';
import { wsHostLabel } from '../config';
import type { ServerInfo } from '../hooks/useServerInfo';
import { useRealUsage, usageTitle, fmtTok } from '../hooks/useRealUsage';
import { useI18n } from '../i18n';
import { LanguageSwitcher } from './LanguageSwitcher';

interface TelemetryMetricsProps {
  isConnected: boolean;
  stats: TelemetryStats;
  onReset?: () => void;
  /** Sağ uçtaki yapılandırma menüsü (tema, proje klasörü, sıfırlama) */
  configSlot?: React.ReactNode;
  /** Çalışan sunucunun kimliği: eski kod ya da Claude oturumu içinde barındırma uyarısı */
  serverInfo?: ServerInfo | null;
}

/** Üst çubuk (tasarımla aynı): solda proje seçici + arama (#toolbar-slot), sağda sunucu/token hapları, onay modu + bildirim (#toolbar-right-slot) ve yapılandırma. */
export const TelemetryMetrics: React.FC<TelemetryMetricsProps> = ({ isConnected, stats, serverInfo = null, configSlot }) => {
  const { t, lang } = useI18n();
  const real = useRealUsage(30000, stats.total_events);       // gerçek token (Claude transkripti); yoksa sunucunun tahmini
  const tokenShort = (() => { const n = real?.available ? real.total.output : stats.total_tokens; return n >= 1e6 ? `${(n / 1e6).toFixed(1)}M` : n >= 1e3 ? `${(n / 1e3).toFixed(0)}k` : String(n); })();

  return (
    <header className="bg-panel border-b border-line -mx-3 -mt-3 px-5 py-2.5 flex flex-wrap items-center gap-x-2 gap-y-1.5 select-none">
      <div id="toolbar-slot" className="flex-1 min-w-fit" />

      {serverInfo && (serverInfo.code_stale || serverInfo.hosted_in_claude_session) && (
        <span
          className="shrink-0 inline-flex items-center justify-center w-[22px] h-[22px] rounded-full border border-warn/40 bg-warnd text-warn text-[12px] font-bold cursor-help"
          title={[
            serverInfo.code_stale ? t('topbar.staleCode') : t('topbar.serverInClaude'),
            t('misc.metrics.serverInfo', { pid: serverInfo.pid, mode: serverInfo.mode, started: new Date(serverInfo.started_at).toLocaleString(lang === 'tr' ? 'tr-TR' : lang === 'es' ? 'es-ES' : lang === 'de' ? 'de-DE' : 'en-US'), git: serverInfo.git_head || '?' }, 'Sunucu pid {pid} · kip {mode} · başlangıç {started} · git {git}'),
            serverInfo.code_stale ? t('misc.metrics.staleFiles', { files: serverInfo.changed_files.join(', ') }, 'Başlangıçtan sonra değişen dosyalar: {files}. Yeni kod için: scripts\\fssc.ps1 stop; scripts\\fssc.ps1 start -Background') : '',
            serverInfo.hosted_in_claude_session ? t('misc.metrics.hostedInClaude', undefined, 'Sunucu bir Claude oturumunun içinde çalışıyor: o oturum kapanırsa pano ve koşu kesilir. Ayrı süreç için: scripts\\fssc.ps1 start -Background') : '',
          ].filter(Boolean).join('\n')}
        >
          <span aria-label={serverInfo.code_stale ? t('topbar.staleCode') : t('topbar.serverInClaude')}>!</span>
        </span>
      )}

      <span
        role="status"
        className={`shrink-0 inline-flex items-center justify-center w-[22px] h-[22px] rounded-full border cursor-help ${isConnected ? 'bg-okd border-ok/30' : 'bg-errd border-err/30'}`}
        title={isConnected ? `${t('topbar.serverConnected')}: ${wsHostLabel()}` : `${t('topbar.waitingConnection')}: ${wsHostLabel()}`}
        aria-label={isConnected ? t('topbar.serverConnected') : t('topbar.waitingConnection')}
      >
        <span aria-hidden="true" className={`w-[8px] h-[8px] rounded-full ${isConnected ? 'bg-ok' : 'bg-err animate-pulse'}`} />
      </span>
      <span
        className="shrink-0 inline-flex items-center h-[22px] px-2 rounded-full bg-sunk text-ink2 border border-line text-[11px] font-mono whitespace-nowrap cursor-help"
        title={`${real?.available ? usageTitle(real.total, real.estimated.total_tokens) : t('topbar.tokenUsageEst')}
${stats.total_tokens.toLocaleString()} ${t('common.token')}`}
      >
        {tokenShort} {t('common.token')}
      </span>

      {/* Koşu eylemleri (Müdahale / Duraklat / İptal): QueuedRunBanner buraya yerleştirir */}
      <div id="run-actions-slot" className="flex items-center gap-1.5 empty:hidden" />

      <div id="toolbar-right-slot" className="flex items-center gap-2" />
      <LanguageSwitcher variant="compact" />
      {configSlot}
    </header>
  );
};
