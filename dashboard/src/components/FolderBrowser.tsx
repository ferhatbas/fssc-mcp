import React, { useCallback, useEffect, useState } from 'react';
import { ArrowUp, Folder, FolderGit2, FolderCheck, HardDrive, Home, RefreshCw, Search, X, Check } from 'lucide-react';
import { api } from '../config';
import { useI18n } from '../i18n';

/** Sunucu tarafı klasör gözatıcısı: tarayıcı yerel tam yolu veremediği için dizinler /api/fs/browse ile listelenir. */
interface BrowseDir { name: string; path: string; has_workspace?: boolean; is_git?: boolean }
interface BrowseResult {
  path: string;
  parent: string | null;
  dirs: BrowseDir[];
  roots: { name: string; path: string }[];
  suggestions: { name: string; path: string }[];
  is_root_list: boolean;
  has_workspace?: boolean;
  is_git?: boolean;
  truncated?: boolean;
}

interface FolderBrowserProps {
  isOpen: boolean;
  initialPath?: string;
  onClose: () => void;
  onSelect: (path: string) => void;
}

export const FolderBrowser: React.FC<FolderBrowserProps> = ({ isOpen, initialPath, onClose, onSelect }) => {
  const { t } = useI18n();
  const [data, setData] = useState<BrowseResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [filter, setFilter] = useState('');
  const [manual, setManual] = useState('');

  const load = useCallback(async (path: string) => {
    setLoading(true);
    setError('');
    try {
      const res = await fetch(api(`/api/fs/browse?path=${encodeURIComponent(path || '')}`));
      const body = await res.json();
      if (!res.ok) {
        setError(body.error || `HTTP ${res.status}`);
        return;
      }
      setData(body);
      setManual(body.path || '');
      setFilter('');
    } catch (e: any) {
      setError(String(e?.message || e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (isOpen) load(initialPath || '');
  }, [isOpen, initialPath, load]);

  if (!isOpen) return null;

  const dirs = (data?.dirs || []).filter(d => !filter || d.name.toLowerCase().includes(filter.toLowerCase()));
  const canSelect = !!data && !data.is_root_list && !!data.path;

  return (
    <div className="fixed inset-0 z-[70] flex items-center justify-center p-4 bg-black/55 backdrop-blur-sm animate-fadeIn" onMouseDown={onClose}>
      <div className="bg-panel border border-line rounded-panel shadow-panel w-full max-w-xl max-h-[85vh] flex flex-col overflow-hidden" onMouseDown={e => e.stopPropagation()}>
        {/* Başlık */}
        <div className="px-4 py-3 bg-panel2 border-b border-line flex items-center justify-between gap-2">
          <div className="flex items-center gap-2 text-xs font-bold text-ink font-mono uppercase tracking-wider">
            <Folder className="w-4 h-4 text-ac" />
            {t('project.folder.title', undefined, 'Klasör Seç')}
          </div>
          <button onClick={onClose} className="text-ink3 hover:text-ink p-1 rounded-md hover:bg-sunk transition"><X className="w-4 h-4" /></button>
        </div>

        {/* Yol satırı */}
        <div className="px-4 py-2 border-b border-line flex items-center gap-2">
          <button
            onClick={() => data?.parent ? load(data.parent) : load('')}
            disabled={loading || (!data?.parent && data?.is_root_list)}
            className="p-1.5 rounded-md border border-line bg-panel2 text-ink2 hover:text-ink hover:border-line2 transition disabled:opacity-40"
            title={t('project.folder.up', undefined, 'Üst klasör')}
          >
            <ArrowUp className="w-3.5 h-3.5" />
          </button>
          <form className="flex-1 flex items-center gap-2" onSubmit={e => { e.preventDefault(); load(manual); }}>
            <input
              type="text"
              value={manual}
              onChange={e => setManual(e.target.value)}
              placeholder={t('project.folder.pathPlaceholder', undefined, "Yol yazıp Enter'a basın (örn: D:\\Personal\\projects)")}
              className="flex-1 bg-sunk border border-line rounded-md px-2.5 py-1.5 text-[11px] font-mono text-ink placeholder-ink3 focus:outline-none focus:border-ac"
            />
            <button type="submit" className="p-1.5 rounded-md border border-line bg-panel2 text-ink2 hover:text-ink transition" title={t('project.folder.go', undefined, 'Git / yenile')}>
              <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
            </button>
          </form>
        </div>

        {/* Kısayollar: sürücüler + öneriler */}
        <div className="px-4 py-2 border-b border-line flex flex-wrap items-center gap-1.5">
          {(data?.roots || []).map(r => (
            <button key={r.path} onClick={() => load(r.path)} className="inline-flex items-center gap-1 text-[10px] font-mono px-2 py-0.5 rounded-md bg-sunk border border-line text-ink2 hover:text-ink hover:border-line2 transition">
              <HardDrive className="w-3 h-3 text-ac" />{r.name}
            </button>
          ))}
          {(data?.suggestions || []).map(s => (
            <button key={s.path} onClick={() => load(s.path)} title={s.path} className="inline-flex items-center gap-1 text-[10px] font-mono px-2 py-0.5 rounded-md bg-sunk border border-line text-ink2 hover:text-ink hover:border-line2 transition">
              <Home className="w-3 h-3 text-info" />{s.name}
            </button>
          ))}
          <div className="ml-auto relative">
            <Search className="w-3 h-3 text-ink3 absolute left-2 top-1/2 -translate-y-1/2" />
            <input
              type="text"
              value={filter}
              onChange={e => setFilter(e.target.value)}
              placeholder={t('project.folder.filter', undefined, 'Süz…')}
              className="w-32 bg-sunk border border-line rounded-md pl-6 pr-2 py-0.5 text-[10px] font-mono text-ink placeholder-ink3 focus:outline-none focus:border-ac"
            />
          </div>
        </div>

        {/* Klasör listesi */}
        <div className="flex-1 overflow-y-auto p-2 min-h-[220px]">
          {error && <div className="m-2 p-2 rounded-md bg-errd border border-err/40 text-err text-[11px] font-mono">{error}</div>}
          {!error && data && dirs.length === 0 && !loading && (
            <div className="p-6 text-center text-[11px] text-ink3 font-mono">{data.is_root_list ? t('project.folder.pickRoot', undefined, 'Bir sürücü ya da kısayol seçin.') : t('project.folder.noSub', undefined, 'Alt klasör yok (bu klasörü seçebilirsiniz).')}</div>
          )}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-1">
            {dirs.map(d => (
              <button
                key={d.path}
                onClick={() => load(d.path)}
                onDoubleClick={() => onSelect(d.path)}
                title={`${d.path}\n${t('project.folder.dirHint', undefined, 'Tek tık: içine gir · Çift tık: seç')}`}
                className="flex items-center gap-2 px-2.5 py-1.5 rounded-md border border-transparent hover:border-line hover:bg-panel2 text-left transition min-w-0"
              >
                {d.has_workspace ? <FolderCheck className="w-4 h-4 text-ok shrink-0" /> : d.is_git ? <FolderGit2 className="w-4 h-4 text-info shrink-0" /> : <Folder className="w-4 h-4 text-ink3 shrink-0" />}
                <span className="text-[11px] font-mono text-ink truncate">{d.name}</span>
                {d.has_workspace && <span className="ml-auto text-[9px] font-mono px-1 rounded bg-okd text-ok border border-ok/40 shrink-0">FS-SC</span>}
                {!d.has_workspace && d.is_git && <span className="ml-auto text-[9px] font-mono px-1 rounded bg-infod text-info border border-info/40 shrink-0">git</span>}
              </button>
            ))}
          </div>
          {data?.truncated && <div className="p-2 text-[10px] text-ink3 font-mono">{t('project.folder.truncated', undefined, 'Liste kısaltıldı; süzgeci kullanın.')}</div>}
        </div>

        {/* Alt bar */}
        <div className="px-4 py-3 bg-panel2 border-t border-line flex items-center justify-between gap-3">
          <div className="min-w-0 text-[11px] font-mono text-ink2 truncate" title={data?.path || ''}>
            {canSelect ? (<><span className="text-ink3">{t('project.folder.selected', undefined, 'Seçili:')} </span><span className="text-ink">{data?.path}</span>{data?.has_workspace ? <span className="ml-1 text-ok">· {t('project.folder.fsscProject', undefined, 'FS-SC projesi')}</span> : data?.is_git ? <span className="ml-1 text-info">· {t('project.folder.gitRepo', undefined, 'git deposu')}</span> : null}</>) : t('project.folder.none', undefined, 'Henüz klasör seçilmedi')}
          </div>
          <div className="flex items-center gap-2 shrink-0">
            <button onClick={onClose} className="px-3 py-1.5 rounded-md border border-line bg-panel text-ink text-xs font-medium hover:border-line2 transition">{t('common.cancel', undefined, 'Vazgeç')}</button>
            <button
              onClick={() => data?.path && onSelect(data.path)}
              disabled={!canSelect}
              className="px-3.5 py-1.5 rounded-md bg-ink text-bg text-xs font-bold shadow-panel hover:opacity-90 transition disabled:opacity-40 inline-flex items-center gap-1.5"
            >
              <Check className="w-3.5 h-3.5" />
              {t('project.folder.selectThis', undefined, 'Bu Klasörü Seç')}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};
