import React, { useEffect, useRef, useState } from 'react';
import { confirmDialog } from '../lib/dialog';
import { Settings, Sun, Moon, FolderSearch, CheckCircle2, RotateCcw } from 'lucide-react';
import { useTheme } from '../hooks/useTheme';
import { useI18n } from '../i18n';
import { LanguageSwitcher } from './LanguageSwitcher';

interface ConfigMenuProps {
  projectName?: string;
  projectDir: string;
  onProjectDirChange: (v: string) => void;
  onBrowse: () => void;
  onBind: () => void;
  onReset: () => void;
  onOpenSettings?: () => void;
}

/** Üst çubuk yapılandırma menüsü: tema, dil, vurgu rengi, proje klasörü ve telemetri sıfırlama. */
export const ConfigMenu: React.FC<ConfigMenuProps> = ({ projectName, projectDir, onProjectDirChange, onBrowse, onBind, onReset, onOpenSettings }) => {
  const { theme, setTheme, accent, setAccent } = useTheme();
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const [fontPx, setFontPx] = useState<number>(() => {
    try { return Number(localStorage.getItem('fssc_font_px')) || 14; } catch { return 14; }
  });
  const applyFont = (px: number) => {
    setFontPx(px);
    document.documentElement.style.fontSize = `${px}px`;
    try { localStorage.setItem('fssc_font_px', String(px)); } catch { /* yoksay */ }
  };

  useEffect(() => {
    if (!open) return undefined;
    const onDown = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false); };
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false); };
    document.addEventListener('mousedown', onDown);
    window.addEventListener('keydown', onKey);
    return () => { document.removeEventListener('mousedown', onDown); window.removeEventListener('keydown', onKey); };
  }, [open]);

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen(o => !o)}
        title={t('config.title')}
        aria-label={t('config.title')}
        aria-expanded={open}
        className={`p-2 rounded-card border transition ${open ? 'bg-acd border-ac/40 text-ac' : 'bg-panel2 border-line text-ink2 hover:text-ink hover:bg-sunk'}`}
      >
        <Settings className="w-4 h-4" />
      </button>

      {open && (
        <div className="absolute right-0 top-full mt-2 z-[70] w-[380px] bg-panel border border-line rounded-panel shadow-xl p-4 space-y-4 text-xs">
          {onOpenSettings && (
            <button type="button" onClick={() => { setOpen(false); onOpenSettings(); }} className="w-full text-left px-3 py-2 rounded-lg border border-ac/40 text-ac bg-acd/40 font-medium hover:bg-acd" title={t('menu.projectSettingsTitle')}>
              {t('config.projectSettingsBtn')} <span className="text-ink3 font-normal">{t('config.projectSettingsSub')}</span>
            </button>
          )}

          <div>
            <div className="text-[10px] font-mono font-bold uppercase tracking-wider text-ink3 mb-1.5">{t('common.language')}</div>
            <LanguageSwitcher variant="inline" />
          </div>

          <div>
            <div className="text-[10px] font-mono font-bold uppercase tracking-wider text-ink3 mb-1.5">{t('config.appearance')}</div>
            <div className="flex items-center gap-3 flex-wrap">
              <div className="flex items-center bg-sunk p-0.5 rounded-card border border-line">
                <button type="button" onClick={() => setTheme('light')}
                  className={`flex items-center gap-1.5 px-3 py-1 rounded-[9px] font-medium transition ${theme === 'light' ? 'bg-panel text-ink shadow-panel border border-line/60' : 'text-ink3 hover:text-ink'}`}>
                  <Sun className="w-3.5 h-3.5 text-warn" />{t('config.themeLight')}
                </button>
                <button type="button" onClick={() => setTheme('dark')}
                  className={`flex items-center gap-1.5 px-3 py-1 rounded-[9px] font-medium transition ${theme === 'dark' ? 'bg-panel text-ink shadow-panel border border-line/60' : 'text-ink3 hover:text-ink'}`}>
                  <Moon className="w-3.5 h-3.5 text-ac" />{t('config.themeDark')}
                </button>
              </div>
              <div className="flex items-center bg-sunk p-0.5 rounded-card border border-line" title={t('config.fontScaleTitle')}>
                {([[12, 'XS'], [13, 'S'], [14, 'M'], [15, 'L'], [16, 'XL']] as const).map(([px, l]) => (
                  <button key={px} type="button" onClick={() => applyFont(px)}
                    className={`px-2 py-0.5 rounded-[9px] font-mono text-[10px] transition ${fontPx === px ? 'bg-panel text-ink shadow-panel border border-line/60 font-bold' : 'text-ink3 hover:text-ink'}`}>{l}</button>
                ))}
              </div>
              <div className="flex items-center gap-1 bg-sunk p-1 rounded-card border border-line" title={t('config.accentColorTitle')}>
                {([['indigo', '#3a48cc'], ['teal', '#0f6f67'], ['magenta', '#98266a']] as const).map(([id, color]) => (
                  <button key={id} type="button" onClick={() => setAccent(id)} title={id}
                    className={`w-4 h-4 rounded-full border-2 transition ${accent === id ? 'border-ink scale-110' : 'border-transparent opacity-70 hover:opacity-100'}`}
                    style={{ background: color }} />
                ))}
              </div>
            </div>
          </div>

          <div>
            <div className="text-[10px] font-mono font-bold uppercase tracking-wider text-ink3 mb-1.5">{t('config.projectFolder')}{projectName ? ` · ${projectName}` : ''}</div>
            <input
              type="text"
              value={projectDir}
              onChange={(e) => onProjectDirChange(e.target.value)}
              placeholder={t('config.projectFolderPlaceholder')}
              className="w-full bg-sunk border border-line rounded-md px-2.5 py-1.5 text-ink placeholder-ink3 focus:outline-none focus:border-ac font-mono text-[11px]"
            />
            <div className="flex items-center gap-2 mt-2">
              <button type="button" onClick={onBrowse} className="px-2.5 py-1 bg-panel2 hover:bg-sunk text-ink rounded-md border border-line flex items-center gap-1 font-medium" title={t('config.browse')}>
                <FolderSearch className="w-3 h-3 text-ac" />{t('config.browse')}
              </button>
              <button type="button" onClick={() => { onBind(); setOpen(false); }} disabled={!projectDir.trim()}
                className="px-2.5 py-1 bg-panel2 hover:bg-sunk text-ink rounded-md border border-line flex items-center gap-1 font-medium disabled:opacity-40" title={t('config.bind')}>
                <CheckCircle2 className="w-3 h-3 text-ok" />{t('config.bind')}
              </button>
            </div>
          </div>

          <div className="pt-2 border-t border-line">
            <div className="text-[10px] font-mono font-bold uppercase tracking-wider text-ink3 mb-1.5">{t('config.telemetry')}</div>
            <button
              type="button"
              onClick={async () => {
                if (await confirmDialog(t('config.resetConfirm'))) {
                  setOpen(false);
                  onReset();
                }
              }}
              className="flex items-center gap-1 px-3 py-1.5 bg-panel2 hover:bg-errd text-err rounded-card border border-line font-medium"
              title={t('config.resetTelemetry')}
            >
              <RotateCcw className="w-3.5 h-3.5" />{t('config.resetTelemetry')}
            </button>
          </div>
        </div>
      )}
    </div>
  );
};
