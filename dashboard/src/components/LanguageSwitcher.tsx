import React, { useState, useRef, useEffect } from 'react';
import { useI18n, SupportedLanguage } from '../i18n';
import { ChevronDown, Check, Globe } from 'lucide-react';

interface LanguageSwitcherProps {
  /** 'compact' (üst çubuk dropdown), 'inline' (ConfigMenu içinde yatay butonlar) */
  variant?: 'compact' | 'inline';
  className?: string;
}

export const LanguageSwitcher: React.FC<LanguageSwitcherProps> = ({ variant = 'compact', className = '' }) => {
  const { lang, setLang, languages, currentLanguageOption, t } = useI18n();
  const [isOpen, setIsOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!isOpen) return undefined;
    const handleOutsideClick = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setIsOpen(false);
      }
    };
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setIsOpen(false);
    };
    document.addEventListener('mousedown', handleOutsideClick);
    window.addEventListener('keydown', handleKeyDown);
    return () => {
      document.removeEventListener('mousedown', handleOutsideClick);
      window.removeEventListener('keydown', handleKeyDown);
    };
  }, [isOpen]);

  if (variant === 'inline') {
    return (
      <div className={`flex items-center gap-1 bg-sunk p-0.5 rounded-card border border-line ${className}`}>
        {languages.map((l) => {
          const isActive = l.code === lang;
          return (
            <button
              key={l.code}
              type="button"
              onClick={() => setLang(l.code as SupportedLanguage)}
              title={`${l.nativeLabel} (${l.label})`}
              className={`flex items-center gap-1.5 px-2.5 py-1 rounded-[8px] font-mono text-[11px] font-medium transition ${
                isActive
                  ? 'bg-panel text-ink shadow-panel border border-line/60 font-bold'
                  : 'text-ink3 hover:text-ink hover:bg-panel2/50'
              }`}
            >
              <span className="text-sm leading-none">{l.flag}</span>
              <span>{l.code.toUpperCase()}</span>
            </button>
          );
        })}
      </div>
    );
  }

  return (
    <div ref={containerRef} className={`relative ${className}`}>
      <button
        type="button"
        onClick={() => setIsOpen((prev) => !prev)}
        aria-expanded={isOpen}
        aria-haspopup="listbox"
        title={t('common.selectLanguage', undefined, 'Dil Seçin / Select Language')}
        className={`h-[28px] px-2 rounded-card border transition flex items-center gap-1.5 text-[11.5px] font-medium select-none ${
          isOpen
            ? 'bg-acd border-ac/40 text-ac'
            : 'bg-panel2 border-line text-ink2 hover:text-ink hover:bg-sunk'
        }`}
      >
        <span className="text-[13px] leading-none" role="img" aria-label={currentLanguageOption.label}>
          {currentLanguageOption.flag}
        </span>
        <span className="font-mono uppercase font-bold tracking-wider text-[11px]">
          {currentLanguageOption.code}
        </span>
        <ChevronDown className={`w-3 h-3 transition-transform duration-200 text-ink3 ${isOpen ? 'rotate-180' : ''}`} />
      </button>

      {isOpen && (
        <div
          role="listbox"
          aria-label={t('common.language')}
          className="absolute right-0 top-full mt-1.5 z-[80] w-[180px] bg-panel border border-line rounded-panel shadow-2xl p-1.5 space-y-0.5 animate-in fade-in slide-in-from-top-1 duration-150"
        >
          <div className="px-2 py-1 text-[10px] font-mono font-bold uppercase tracking-wider text-ink3 flex items-center gap-1 border-b border-line mb-1">
            <Globe className="w-3 h-3 text-ac" />
            {t('common.language')}
          </div>
          {languages.map((l) => {
            const isSelected = l.code === lang;
            return (
              <button
                key={l.code}
                role="option"
                aria-selected={isSelected}
                type="button"
                onClick={() => {
                  setLang(l.code as SupportedLanguage);
                  setIsOpen(false);
                }}
                className={`w-full flex items-center justify-between px-2.5 py-1.5 rounded-card text-xs transition ${
                  isSelected
                    ? 'bg-acd text-ac font-bold border border-ac/30'
                    : 'text-ink hover:bg-sunk'
                }`}
              >
                <div className="flex items-center gap-2">
                  <span className="text-base leading-none" role="img" aria-hidden="true">
                    {l.flag}
                  </span>
                  <div className="text-left">
                    <div className="leading-snug">{l.nativeLabel}</div>
                    <div className="text-[10px] text-ink3 font-normal">{l.label}</div>
                  </div>
                </div>
                {isSelected && <Check className="w-3.5 h-3.5 text-ac stroke-[2.5]" />}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
};
