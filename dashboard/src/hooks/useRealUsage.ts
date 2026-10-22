import { useEffect, useState } from 'react';
import { translate, getSavedLanguage } from '../i18n';

export interface UsageBucket { input: number; output: number; cache_write: number; cache_read: number; messages: number }
export interface RealUsage {
  available: boolean;
  source: string;
  estimated: { total_tokens: number; total_events: number };
  total: UsageBucket;
  by_agent: Record<string, UsageBucket>;
  by_run: Record<string, UsageBucket>;
  unattributed: UsageBucket;
  sessions: number;
  first?: string;
  last?: string;
}

/** Gerçek token kullanımı (Claude transkriptlerinden): sunucudaki tahmin sayaçları yerine gerçek değeri göstermek için. */
export function useRealUsage(pollMs = 30000, refreshKey: unknown = null): RealUsage | null {
  const [usage, setUsage] = useState<RealUsage | null>(null);
  useEffect(() => {
    let alive = true;
    const load = async () => {
      try {
        const r = await fetch('/api/usage/tokens');
        if (r.ok && alive) setUsage(await r.json());
      } catch { /* sunucu yoksa tahmine düş */ }
    };
    load();
    const t = setInterval(load, pollMs);
    return () => { alive = false; clearInterval(t); };
  }, [pollMs, refreshKey]);
  return usage;
}

const LOCALES = { tr: 'tr-TR', es: 'es-ES', de: 'de-DE', en: 'en-US' } as const;
export const fmtTok = (n: number): string => n.toLocaleString(LOCALES[getSavedLanguage()]);

export const usageTitle = (u: UsageBucket, estimated?: number): string =>
  translate('misc.usage.title', { output: fmtTok(u.output), input: fmtTok(u.input), cw: fmtTok(u.cache_write), cr: fmtTok(u.cache_read), msgs: u.messages },
    'Gerçek kullanım (Claude transkripti)\nÇıktı: {output}\nYeni giriş: {input}\nÖnbellek yazma: {cw}\nÖnbellek okuma: {cr} (her turda bağlamın yeniden okunması)\nAsistan mesajı: {msgs}')
  + (estimated != null ? translate('misc.usage.estimate', { n: fmtTok(estimated) }, '\n\nSunucunun eski tahmini: {n} (gerçek değil)') : '');
