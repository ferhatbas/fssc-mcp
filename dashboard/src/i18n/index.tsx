import React, { createContext, useContext, useEffect, useState, useMemo, useCallback } from 'react';
import { SupportedLanguage, SUPPORTED_LANGUAGES, LanguageOption, Translations } from './types';
import { tr } from './locales/tr';
import { en } from './locales/en';
import { es } from './locales/es';
import { de } from './locales/de';
import { EXTRA } from './locales/extra';

export * from './types';

const DICTIONARIES: Record<SupportedLanguage, Translations> = {
  tr,
  en,
  es,
  de,
};

const STORAGE_KEY = 'ag_lang';
export const LANG_CHANGE_EVENT = 'fssc:language-change';

/** Tarayıcı varsayılanı veya yerel depolamadaki dili okur */
export function getSavedLanguage(): SupportedLanguage {
  try {
    const saved = localStorage.getItem(STORAGE_KEY) as SupportedLanguage;
    if (saved && ['tr', 'en', 'es', 'de'].includes(saved)) {
      return saved;
    }
  } catch {
    /* depolama erişimi yok */
  }

  // Tarayıcı dil sezgisi
  try {
    const nav = (navigator.language || '').toLowerCase();
    if (nav.startsWith('tr')) return 'tr';
    if (nav.startsWith('es')) return 'es';
    if (nav.startsWith('de')) return 'de';
    if (nav.startsWith('en')) return 'en';
  } catch {
    /* navigator yok */
  }

  return 'en'; // Varsayılan İngilizce
}

export function saveLanguage(lang: SupportedLanguage): void {
  try {
    localStorage.setItem(STORAGE_KEY, lang);
  } catch {
    /* depolama erişimi yok */
  }
  try {
    document.documentElement.lang = lang;
  } catch {
    /* dom yok */
  }
  window.dispatchEvent(new CustomEvent(LANG_CHANGE_EVENT, { detail: { lang } }));
}

type NestedKeyOf<ObjectType extends object> = {
  [Key in keyof ObjectType & (string | number)]: ObjectType[Key] extends object
    ? `${Key}.${NestedKeyOf<ObjectType[Key]>}`
    : `${Key}`;
}[keyof ObjectType & (string | number)];

export type TranslationKey = NestedKeyOf<Translations>;

export type TranslationParams = Record<string, string | number | boolean | null | undefined>;

export interface I18nContextType {
  lang: SupportedLanguage;
  setLang: (lang: SupportedLanguage) => void;
  languages: LanguageOption[];
  currentLanguageOption: LanguageOption;
  t: (key: string, params?: TranslationParams, fallback?: string) => string;
}

const I18nContext = createContext<I18nContextType | null>(null);

function resolvePath(obj: unknown, path: string): string | undefined {
  if (!obj || typeof obj !== 'object') return undefined;
  const parts = path.split('.');
  let current: unknown = obj;
  for (const part of parts) {
    if (current && typeof current === 'object' && part in current) {
      current = (current as Record<string, unknown>)[part];
    } else {
      return undefined;
    }
  }
  return typeof current === 'string' ? current : undefined;
}

export function formatString(template: string, params?: TranslationParams): string {
  if (!params) return template;
  return template.replace(/\{(\w+)\}/g, (_, k) => (k in params && params[k] != null ? String(params[k]) : `{${k}}`));
}

/** Bileşen/hook dışında (sınıf bileşeni, lib, olay işleyici) çeviri: kayıtlı dili okur, `t` ile aynı çözümü yapar. */
export function translate(key: string, params?: TranslationParams, fallback?: string): string {
  const l = getSavedLanguage();
  const found = EXTRA[l][key] ?? resolvePath(DICTIONARIES[l], key) ?? EXTRA.en[key] ?? resolvePath(DICTIONARIES.en, key) ?? fallback ?? key;
  return formatString(found, params);
}

export const I18nProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [lang, setLangState] = useState<SupportedLanguage>(getSavedLanguage);

  const setLang = useCallback((newLang: SupportedLanguage) => {
    setLangState(newLang);
    saveLanguage(newLang);
  }, []);

  useEffect(() => {
    // Sayfa açılışında html lang etiketini güncelle
    try {
      document.documentElement.lang = lang;
    } catch {
      /* dom yok */
    }
  }, [lang]);

  const currentLanguageOption = useMemo(
    () => SUPPORTED_LANGUAGES.find((l) => l.code === lang) || SUPPORTED_LANGUAGES[0],
    [lang]
  );

  const t = useCallback(
    (key: string, params?: TranslationParams, fallback?: string): string => {
      const activeDict = DICTIONARIES[lang];
      const fallbackDict = DICTIONARIES.en;

      const found = EXTRA[lang][key] ?? resolvePath(activeDict, key) ?? EXTRA.en[key] ?? resolvePath(fallbackDict, key) ?? fallback ?? key;
      return formatString(found, params);
    },
    [lang]
  );

  const value = useMemo(
    () => ({
      lang,
      setLang,
      languages: SUPPORTED_LANGUAGES,
      currentLanguageOption,
      t,
    }),
    [lang, setLang, currentLanguageOption, t]
  );

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
};

export function useI18n(): I18nContextType {
  const ctx = useContext(I18nContext);
  if (!ctx) {
    // Context dışında çağrılırsa güvenli yedek
    const currentLang = getSavedLanguage();
    return {
      lang: currentLang,
      setLang: saveLanguage,
      languages: SUPPORTED_LANGUAGES,
      currentLanguageOption: SUPPORTED_LANGUAGES.find((l) => l.code === currentLang) || SUPPORTED_LANGUAGES[0],
      t: (key: string, params?: TranslationParams, fallback?: string) => {
        const found =
          EXTRA[currentLang][key] ??
          resolvePath(DICTIONARIES[currentLang], key) ??
          EXTRA.en[key] ??
          resolvePath(DICTIONARIES.en, key) ??
          fallback ??
          key;
        return formatString(found, params);
      },
    };
  }
  return ctx;
}
