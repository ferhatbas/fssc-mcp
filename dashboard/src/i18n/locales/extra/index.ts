/**
 * Bileşen bazlı ek çeviriler: her bölüm kendi dosyasında (`locales/extra/<alan>.ts`) düz anahtarlarla (`alan.anahtar`) dört dil verir.
 * Dosyalar otomatik birleşir (Vite glob); böylece ana sözlüklere dokunmadan yeni metin eklenir. Anahtar yoksa etkin dil → en → bileşendeki Türkçe yedek metin.
 */
import type { SupportedLanguage } from '../../types';

export type ExtraPart = Partial<Record<SupportedLanguage, Record<string, string>>>;

const parts = import.meta.glob('./*.ts', { eager: true }) as Record<string, { default?: ExtraPart }>;

export const EXTRA: Record<SupportedLanguage, Record<string, string>> = { tr: {}, en: {}, es: {}, de: {} };

for (const [file, mod] of Object.entries(parts)) {
  if (file === './index.ts' || !mod.default) continue;
  for (const lang of Object.keys(EXTRA) as SupportedLanguage[]) {
    Object.assign(EXTRA[lang], mod.default[lang] || {});
  }
}
