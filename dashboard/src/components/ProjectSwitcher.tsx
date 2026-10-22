import React, { useState, useEffect, useRef } from 'react';
import { FolderGit2, ChevronDown, Plus, Check, Trash2, FolderCheck, Layers, FolderSearch, AlertTriangle } from 'lucide-react';
import { ProjectInfo } from '../types/telemetry';
import { FolderBrowser } from './FolderBrowser';
import { useI18n } from '../i18n';

interface ProjectSwitcherProps {
  currentProject: ProjectInfo | null;
  projects: ProjectInfo[];
  onSwitchProject: (projectIdOrPath: string) => Promise<void>;
  onAddProject: (path: string, name?: string, layoutMode?: 'apps' | 'flat', projectLanguage?: 'tr' | 'en') => Promise<{ layout_note?: string } | void>;
  onDeleteProject: (projectId: string) => Promise<void>;
  onPurgeProject: (projectId: string, scope: 'data' | 'folder', confirmName: string) => Promise<string | null>;
}

/** Üst bardaki proje seçici: tema renklerini kullanır (açık/koyu), yeni proje klasörü sunucu tarafı gözatıcıyla seçilir. */
export const ProjectSwitcher: React.FC<ProjectSwitcherProps> = ({
  currentProject,
  projects,
  onSwitchProject,
  onAddProject,
  onDeleteProject,
  onPurgeProject
}) => {
  const { t } = useI18n();
  const [isOpen, setIsOpen] = useState(false);
  const [newPath, setNewPath] = useState('');
  const [newName, setNewName] = useState('');
  const [isAdding, setIsAdding] = useState(false);
  const [browsing, setBrowsing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [layoutMode, setLayoutMode] = useState<'apps' | 'flat'>('apps');
  const [projectLang, setProjectLang] = useState<'tr' | 'en'>('en');
  const [addNote, setAddNote] = useState('');
  const [purgeTarget, setPurgeTarget] = useState<ProjectInfo | null>(null);
  const [purgeStep, setPurgeStep] = useState<1 | 2>(1);
  const [purgeScope, setPurgeScope] = useState<'list' | 'data' | 'folder'>('list');
  const [purgeName, setPurgeName] = useState('');
  const [purgeError, setPurgeError] = useState('');
  const [purgeBusy, setPurgeBusy] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);

  // Dışarı tıklandığında menüyü kapat (gözatıcı açıkken kapatma)
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (browsing) return;
      if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
        setIsOpen(false);
        setIsAdding(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [browsing]);

  const handleAddSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newPath.trim() || busy) return;
    setBusy(true);
    try {
      const added = await onAddProject(newPath.trim(), newName.trim() || undefined, layoutMode, projectLang);
      setNewPath('');
      setNewName('');
      setIsAdding(false);
      if (added && added.layout_note) {
        setAddNote(added.layout_note);      // klasör düzeni dayatılmadıysa kullanıcı nedenini görsün (menü açık kalır)
      } else {
        setAddNote('');
        setIsOpen(false);
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="relative inline-block text-left" ref={dropdownRef}>
      {/* Tetikleyici */}
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="flex items-center gap-2 px-3 py-1.5 rounded-md bg-panel2 hover:bg-sunk border border-line text-ink transition font-mono text-xs"
        title={currentProject?.path || t('project.switcher.pick', undefined, 'Proje seçin')}
      >
        <FolderGit2 className="w-4 h-4 text-ac shrink-0" />
        <span className="font-bold text-ink truncate max-w-[160px]">{currentProject ? currentProject.name : t('project.switcher.pickCaps', undefined, 'Proje Seçin')}</span>
        <ChevronDown className={`w-3.5 h-3.5 text-ink3 transition-transform duration-200 ${isOpen ? 'rotate-180' : ''}`} />
      </button>

      {/* Açılır liste */}
      {isOpen && (
        <div className="absolute left-0 mt-2 w-[26rem] rounded-panel bg-panel border border-line shadow-panel z-50 overflow-hidden animate-fadeIn">
          <div className="px-3 py-2.5 border-b border-line flex items-center justify-between bg-panel2">
            <span className="text-[11px] font-mono font-bold text-ink2 uppercase tracking-wider flex items-center gap-1.5">
              <Layers className="w-3.5 h-3.5 text-ac" />
              {t('project.switcher.connected', { n: projects.length }, 'Bağlı Projeler ({n})')}
            </span>
            <button
              onClick={() => setIsAdding(!isAdding)}
              className={`text-[10px] font-mono flex items-center gap-1 font-bold px-2 py-1 rounded-md border transition ${isAdding ? 'bg-ac text-onac border-ac' : 'bg-panel text-ac border-ac/40 hover:bg-acd'}`}
            >
              <Plus className="w-3 h-3" />
              {t('project.switcher.addNew', undefined, 'Yeni Ekle')}
            </button>
          </div>

          {/* Yeni proje formu */}
          {isAdding && (
            <form onSubmit={handleAddSubmit} className="p-3 border-b border-line bg-panel flex flex-col gap-2 text-xs font-mono">
              <div className="flex items-center gap-2">
                <input
                  type="text"
                  value={newPath}
                  onChange={(e) => setNewPath(e.target.value)}
                  placeholder={t('project.switcher.pathPlaceholder', undefined, 'Dizin yolu (örn: D:\\Personal\\projects\\my_app)')}
                  className="flex-1 bg-sunk border border-line rounded-md px-2.5 py-1.5 text-ink placeholder-ink3 text-[11px] focus:outline-none focus:border-ac"
                  autoFocus
                />
                <button
                  type="button"
                  onClick={() => setBrowsing(true)}
                  className="px-2.5 py-1.5 rounded-md border border-line bg-panel2 text-ink2 hover:text-ink hover:border-line2 transition inline-flex items-center gap-1 text-[11px] shrink-0"
                  title={t('project.switcher.pickFolder', undefined, 'Klasör seç')}
                >
                  <FolderSearch className="w-3.5 h-3.5 text-ac" />
                  {t('config.browse', undefined, 'Gözat')}
                </button>
              </div>
              <div className="flex items-center gap-2">
                <input
                  type="text"
                  value={newName}
                  onChange={(e) => setNewName(e.target.value)}
                  placeholder={t('project.switcher.namePlaceholder', undefined, 'Proje adı (isteğe bağlı; yoksa klasör adı)')}
                  className="flex-1 bg-sunk border border-line rounded-md px-2.5 py-1.5 text-ink placeholder-ink3 text-[11px] focus:outline-none focus:border-ac"
                />
                <button
                  type="submit"
                  disabled={!newPath.trim() || busy}
                  className="px-3.5 py-1.5 bg-ink text-bg font-bold rounded-md text-[11px] transition shrink-0 shadow-panel hover:opacity-90 disabled:opacity-40"
                >
                  {busy ? t('project.switcher.binding', undefined, 'Bağlanıyor…') : t('project.switcher.bind', undefined, 'Bağla')}
                </button>
              </div>
              <div className="flex flex-col gap-1.5 pt-1">
                <div className="text-[11px] font-bold text-ink2">{t('project.switcher.projectLanguage', undefined, 'Proje dili')}</div>
                <div className="flex gap-2">
                  {(['en', 'tr'] as const).map(code => (
                    <label key={code} className={`flex items-center gap-2 px-3 py-1.5 rounded-md border cursor-pointer ${projectLang === code ? 'border-ac bg-acd/40' : 'border-line'}`}>
                      <input type="radio" name="project-language" checked={projectLang === code} onChange={() => setProjectLang(code)} />
                      <span className="text-ink">{code === 'en' ? 'English' : 'Türkçe'}</span>
                    </label>
                  ))}
                </div>
                <div className="text-[10px] text-ink3">{t('project.switcher.projectLanguageHint', undefined, 'Ajanların ürettiği belgeler, Jira metinleri ve toplantı notları bu dilde yazılır. Pano dilinden bağımsızdır; sonradan Proje ayarlarından değiştirilebilir.')}</div>
              </div>
              <div className="flex flex-col gap-1.5 pt-1">
                <div className="text-[11px] font-bold text-ink2">{t('project.switcher.layout', undefined, 'Klasör düzeni')}</div>
                <label className={`flex gap-2 p-2 rounded-md border cursor-pointer ${layoutMode === 'apps' ? 'border-ac bg-acd/40' : 'border-line'}`}>
                  <input type="radio" name="layout-mode" checked={layoutMode === 'apps'} onChange={() => setLayoutMode('apps')} />
                  <span>
                    <b className="text-ink">apps/ devops/ docs/ <span className="text-ac">({t('project.recommended', undefined, 'önerilir')})</span></b><br />
                    <span className="text-ink3">{t('project.switcher.appsDesc', undefined, 'Her uygulama apps/ altında ayrı klasörde (apps/backend, apps/web, apps/mobile…); Dockerfile ve CI devops/, belgeler docs/ altında. Kökte yalnızca README, CLAUDE.md gibi depo dosyaları kalır.')}</span>
                  </span>
                </label>
                <label className={`flex gap-2 p-2 rounded-md border cursor-pointer ${layoutMode === 'flat' ? 'border-ac bg-acd/40' : 'border-line'}`}>
                  <input type="radio" name="layout-mode" checked={layoutMode === 'flat'} onChange={() => setLayoutMode('flat')} />
                  <span>
                    <b className="text-ink">{t('project.flatLayout', undefined, 'Düz düzen')}</b><br />
                    <span className="text-ink3">{t('project.switcher.flatDesc', undefined, 'Ürün kodu proje kökünde (src/, package.json…). Mevcut projeler için uygundur.')}</span>
                  </span>
                </label>
              </div>
              <div className="text-[10px] text-ink3">{t('project.switcher.folderNote', undefined, 'Klasör yoksa oluşturulur; varsa içindeki kod "mevcut proje" olarak ele alınır. İçinde ürün dosyası olan klasörde apps düzeni dayatılmaz; sonradan göç planıyla geçilir.')}</div>
            </form>
          )}
          {addNote && (
            <div className="p-3 border-b border-line bg-warnd text-warn text-[11px] font-mono" role="status">{addNote}</div>
          )}

          {/* Proje kartları */}
          <div className="max-h-72 overflow-y-auto p-1.5 space-y-1 bg-panel">
            {projects.length === 0 ? (
              <div className="p-4 text-center text-xs font-mono text-ink3">{t('project.switcher.empty', undefined, 'Bağlı proje yok. "Yeni Ekle" ile bir klasör bağlayın.')}</div>
            ) : (
              projects.map((proj) => {
                const isActive = currentProject?.id === proj.id;
                return (
                  <div
                    key={proj.id}
                    className={`px-2.5 py-2 rounded-md border transition-all cursor-pointer flex items-center justify-between gap-2 text-xs ${
                      isActive ? 'bg-acd/60 border-ac/50' : 'bg-panel border-line hover:border-line2 hover:bg-panel2'
                    }`}
                    onClick={() => {
                      if (!isActive) {
                        onSwitchProject(proj.id);
                        setIsOpen(false);
                      }
                    }}
                    title={proj.path}
                  >
                    <div className="flex items-center gap-2.5 min-w-0 flex-1">
                      <div className={`p-1.5 rounded-md shrink-0 ${isActive ? 'bg-ac text-onac' : 'bg-sunk text-ink3'}`}>
                        <FolderCheck className="w-4 h-4" />
                      </div>
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-1.5 font-mono">
                          <span className="truncate text-ink font-bold">{proj.name}</span>
                          {isActive && <span className="px-1.5 py-0.5 rounded-full bg-okd text-ok text-[9px] font-semibold border border-ok/40 shrink-0">{t('project.switcher.active', undefined, 'Aktif')}</span>}
                        </div>
                        <div className="text-[10px] font-mono text-ink3 truncate">{proj.path}</div>
                        <div className="flex items-center gap-1.5 text-[9.5px] font-mono text-ink3 mt-0.5">
                          <span>{t('project.switcher.events', { n: proj.events_count || 0 }, '{n} olay')}</span>
                          <span>·</span>
                          <span>{t('project.switcher.items', { n: proj.jira_count ?? proj.tasks_count ?? 0 }, '{n} iş')}</span>
                          {proj.specs_count ? <><span>·</span><span>{t('project.switcher.specs', { n: proj.specs_count }, '{n} şartname')}</span></> : null}
                        </div>
                      </div>
                    </div>
                    <div className="flex items-center gap-1 shrink-0">
                      {isActive && <Check className="w-4 h-4 text-ac" />}
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          setPurgeTarget(proj);
                          setPurgeStep(1);
                          setPurgeScope('list');
                          setPurgeName('');
                          setPurgeError('');
                        }}
                        className="p-1 text-ink3 hover:text-err rounded-md transition"
                        title={t('project.switcher.removeTitle', undefined, 'Kaldır / verilerini sil')}
                      >
                        <Trash2 className="w-3.5 h-3.5" />
                      </button>
                    </div>
                  </div>
                );
              })
            )}
          </div>
        </div>
      )}

      {purgeTarget && (
        <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/50" onMouseDown={() => !purgeBusy && setPurgeTarget(null)}>
          <div className="w-[28rem] rounded-panel bg-panel border border-line shadow-panel p-4 font-mono text-xs space-y-3" onMouseDown={(e) => e.stopPropagation()}>
            <div className="flex items-center gap-2 text-err font-bold text-sm">
              <AlertTriangle className="w-4 h-4" /> {t('project.switcher.removeHeading', { name: purgeTarget.name }, "'{name}' projesini kaldır")}
              <span className="ml-auto text-[10px] text-ink3 font-normal">{t('project.switcher.step', { n: purgeStep }, 'Adım {n}/2')}</span>
            </div>
            {purgeStep === 1 ? (
              <>
                <div className="text-ink3 break-all">{purgeTarget.path}</div>
                {([
                  ['list', t('project.switcher.scopeListTitle', undefined, 'Yalnızca listeden kaldır'), t('project.switcher.scopeListDesc', undefined, 'Hiçbir dosya silinmez.')],
                  ['data', t('project.switcher.scopeDataTitle', undefined, 'Tüm FS-SC verilerini sil'), t('project.switcher.scopeDataDesc', undefined, '.fs-workspace (ayar, koşu, olay, şartname) ve belge klasörü silinir; kod ve .git kalır.')],
                  ['folder', t('project.switcher.scopeFolderTitle', undefined, 'Proje klasörünün tamamını sil'), t('project.switcher.scopeFolderDesc', undefined, 'Kod dahil klasördeki HER ŞEY silinir. Geri alınamaz.')]
                ] as const).map(([val, title, desc]) => (
                  <label key={val} className={`flex gap-2 p-2 rounded-md border cursor-pointer ${purgeScope === val ? 'border-ac bg-acd/40' : 'border-line'}`}>
                    <input type="radio" checked={purgeScope === val} onChange={() => setPurgeScope(val)} />
                    <span><b className={val === 'list' ? 'text-ink' : 'text-err'}>{title}</b><br /><span className="text-ink3">{desc}</span></span>
                  </label>
                ))}
                <div className="flex justify-end gap-2">
                  <button className="px-3 py-1.5 rounded-md border border-line text-ink2" onClick={() => setPurgeTarget(null)}>{t('common.cancel', undefined, 'Vazgeç')}</button>
                  <button className="px-3 py-1.5 rounded-md bg-err text-white font-bold" onClick={() => setPurgeStep(2)}>{t('project.switcher.next', undefined, 'Devam')}</button>
                </div>
              </>
            ) : (
              <>
                <div className="text-ink2">
                  {purgeScope === 'list' ? t('project.switcher.confirmList', undefined, 'Proje listeden kaldırılacak.') : purgeScope === 'data' ? t('project.switcher.confirmData', undefined, 'FS-SC verileri kalıcı olarak silinecek.') : t('project.switcher.confirmFolder', undefined, 'Klasörün tamamı kalıcı olarak silinecek.')}
                  {' '}{t('project.switcher.typeName', undefined, 'Onaylamak için proje adını yazın:')} <b className="text-ink">{purgeTarget.name}</b>
                </div>
                <input
                  autoFocus
                  value={purgeName}
                  onChange={(e) => setPurgeName(e.target.value)}
                  className="w-full bg-sunk border border-line rounded-md px-2.5 py-1.5 text-ink focus:outline-none focus:border-err"
                />
                {purgeError && <div className="text-err">{purgeError}</div>}
                <div className="flex justify-end gap-2">
                  <button className="px-3 py-1.5 rounded-md border border-line text-ink2" disabled={purgeBusy} onClick={() => setPurgeStep(1)}>{t('common.back', undefined, 'Geri')}</button>
                  <button
                    className="px-3 py-1.5 rounded-md bg-err text-white font-bold disabled:opacity-40"
                    disabled={purgeBusy || purgeName.trim() !== purgeTarget.name}
                    onClick={async () => {
                      setPurgeBusy(true);
                      setPurgeError('');
                      let err: string | null = null;
                      if (purgeScope === 'list') await onDeleteProject(purgeTarget.id);
                      else err = await onPurgeProject(purgeTarget.id, purgeScope, purgeName.trim());
                      setPurgeBusy(false);
                      if (err) setPurgeError(err);
                      else { setPurgeTarget(null); setIsOpen(false); }
                    }}
                  >
                    {purgeBusy ? t('project.switcher.deleting', undefined, 'Siliniyor…') : t('project.switcher.applyPermanent', undefined, 'Kalıcı olarak uygula')}
                  </button>
                </div>
              </>
            )}
          </div>
        </div>
      )}

      <FolderBrowser
        isOpen={browsing}
        initialPath={newPath || currentProject?.path || ''}
        onClose={() => setBrowsing(false)}
        onSelect={(p) => { setNewPath(p); setBrowsing(false); }}
      />
    </div>
  );
};
