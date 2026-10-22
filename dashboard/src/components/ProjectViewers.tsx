import { ErrorBoundary, importWithReload } from './ErrorBoundary';
import React, { Suspense, lazy, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { X, FileText, GitCommitHorizontal, FlaskConical, BookOpen, Search, ListChecks, Code2, Folder, FolderOpen, ChevronRight, ChevronDown } from 'lucide-react';
import { isMarkdown } from '../lib/highlight';
import { MarkdownView } from '../lib/markdown';
import { useI18n } from '../i18n';
import { VIEWER_EVENT, ViewerRequest, ProjectFileDoc, CommitDetail, DocsListing, DocEntry, TreeEntry, TreeListing, openFile } from '../lib/viewer';

async function getJson<T>(url: string): Promise<T> {
  const r = await fetch(url);
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error((j as { error?: string }).error || `HTTP ${r.status}`);
  return j as T;
}

/** Görüntüleyici yazı ölçeği (A−/A+): tarayıcı yakınlaştırması büyükse küçültülebilir; seçim saklanır. */
const SCALE_KEY = 'fssc_viewer_scale';
const SCALE_EVT = 'fssc:viewer-scale';
const SCALES = [0.6, 0.7, 0.8, 0.9, 1, 1.15, 1.3];
const readScale = (): number => {
  try { const v = Number(localStorage.getItem(SCALE_KEY)); if (SCALES.includes(v)) return v; } catch { /* depolama yok */ }
  return 0.8;
};
const useScale = (): [number, (dir: -1 | 1) => void] => {
  const [scale, setScale] = useState(readScale);
  useEffect(() => {
    const on = () => setScale(readScale());
    window.addEventListener(SCALE_EVT, on);
    return () => window.removeEventListener(SCALE_EVT, on);
  }, []);
  const step = (dir: -1 | 1) => {
    const i = Math.max(0, Math.min(SCALES.length - 1, SCALES.indexOf(scale) + dir));
    try { localStorage.setItem(SCALE_KEY, String(SCALES[i])); } catch { /* yoksay */ }
    window.dispatchEvent(new Event(SCALE_EVT));
  };
  return [scale, step];
};

const CodeEditor = lazy(() => importWithReload(() => import('./CodeEditor')));

const Overlay: React.FC<{ onClose: () => void; wide?: boolean; children: React.ReactNode }> = ({ onClose, wide, children }) => {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);
  return (
    <div className="fixed inset-0 z-[90] flex items-center justify-center bg-black/55 p-4" onClick={onClose} role="dialog" aria-modal="true">
      <div className={`bg-panel border border-line rounded-2xl shadow-2xl w-full ${wide ? 'max-w-6xl' : 'max-w-5xl'} h-[86vh] flex flex-col overflow-hidden`} onClick={e => e.stopPropagation()}>
        <div className="flex flex-col flex-1 min-h-0" style={{ zoom: useScale()[0] }}>{children}</div>
      </div>
    </div>
  );
};

const ScaleControl: React.FC = () => {
  const { t } = useI18n();
  const [scale, step] = useScale();
  const b = 'px-1.5 py-0.5 rounded-md border border-line bg-panel2 text-ink2 hover:text-ink font-mono text-[11px] font-bold disabled:opacity-40';
  return (
    <div className="flex items-center gap-1 mr-1" title={t('project.viewer.fontSize', undefined, 'Yazı boyutu')}>
      <button onClick={() => step(-1)} disabled={scale <= SCALES[0]} className={b} aria-label={t('project.viewer.fontSmaller', undefined, 'Yazıyı küçült')}>A−</button>
      <span className="w-9 text-center text-[10px] font-mono text-ink3">{Math.round(scale * 100)}%</span>
      <button onClick={() => step(1)} disabled={scale >= SCALES[SCALES.length - 1]} className={b} aria-label={t('project.viewer.fontLarger', undefined, 'Yazıyı büyüt')}>A+</button>
    </div>
  );
};

const Header: React.FC<{ icon: React.ReactNode; title: React.ReactNode; sub?: React.ReactNode; onClose: () => void }> = ({ icon, title, sub, onClose }) => {
  const { t } = useI18n();
  return (
  <div className="flex items-start justify-between gap-3 px-5 py-3 border-b border-line bg-panel2/60 shrink-0">
    <div className="min-w-0">
      <div className="flex items-center gap-2 text-sm font-bold text-ink">{icon}<span className="truncate">{title}</span></div>
      {sub && <div className="mt-0.5 text-[11px] text-ink3 font-mono">{sub}</div>}
    </div>
    <div className="flex items-center gap-1 shrink-0">
      <ScaleControl />
      <button onClick={onClose} aria-label={t('common.close', undefined, 'Kapat')} className="p-1.5 rounded-lg text-ink2 hover:text-ink hover:bg-sunk border border-transparent hover:border-line"><X className="w-4 h-4" /></button>
    </div>
  </div>
  );
};

/** Dosya içeriği: test dosyalarında önce sözel senaryo listesi (kod okumadan ne denendiği), ayrıca ham içerik. */
export const FileContent: React.FC<{ path: string; line?: number }> = ({ path, line }) => {
  const { t } = useI18n();
  const [doc, setDoc] = useState<ProjectFileDoc | null>(null);
  const [err, setErr] = useState('');
  const [tab, setTab] = useState<'scenarios' | 'code' | 'view'>('code');
  const [jump, setJump] = useState<number | undefined>(line);

  useEffect(() => {
    let alive = true;
    setDoc(null); setErr('');
    getJson<ProjectFileDoc>(`/api/project/file?path=${encodeURIComponent(path)}`)
      .then(d => { if (alive) { setDoc(d); setTab(d.is_test && d.scenarios.length ? 'scenarios' : isMarkdown(d.path) ? 'view' : 'code'); } })
      .catch(e => { if (alive) setErr((e as Error).message); });
    return () => { alive = false; };
  }, [path]);


  if (err) return <div className="p-5 text-xs text-err">{err}</div>;
  if (!doc) return <div className="p-5 text-xs text-ink3">{t('common.loading', undefined, 'Yükleniyor…')}</div>;

  const grouped = doc.scenarios.reduce<Record<string, typeof doc.scenarios>>((acc, s) => { (acc[s.suite || '—'] ||= []).push(s); return acc; }, {});
  return (
    <div className="flex-1 min-h-0 flex flex-col">
      <div className="flex items-center gap-2 px-5 py-2 border-b border-line text-[11px] shrink-0 flex-wrap">
        {doc.is_test && (
          <button onClick={() => setTab('scenarios')} className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-md border font-semibold ${tab === 'scenarios' ? 'bg-acd text-ac border-ac/40' : 'bg-panel2 text-ink2 border-line'}`}>
            <ListChecks className="w-3.5 h-3.5" />{t('project.viewer.scenarios', { n: doc.scenarios.length }, 'Senaryolar ({n})')}
          </button>
        )}
        {isMarkdown(doc.path) && (
          <button onClick={() => setTab('view')} className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-md border font-semibold ${tab === 'view' ? 'bg-acd text-ac border-ac/40' : 'bg-panel2 text-ink2 border-line'}`}>
            <BookOpen className="w-3.5 h-3.5" />{t('project.viewer.view', undefined, 'Görünüm')}
          </button>
        )}
        <button onClick={() => setTab('code')} className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-md border font-semibold ${tab === 'code' ? 'bg-acd text-ac border-ac/40' : 'bg-panel2 text-ink2 border-line'}`}>
          <Code2 className="w-3.5 h-3.5" />{doc.is_test || isMarkdown(doc.path) ? t('project.viewer.code', undefined, 'Kod') : t('project.viewer.content', undefined, 'İçerik')}
        </button>
        <span className="text-ink3 font-mono ml-auto">{t('project.viewer.linesSize', { lines: doc.lines, kb: (doc.size / 1024).toFixed(1) }, '{lines} satır · {kb} KB')}{doc.truncated ? ` · ${t('project.viewer.truncated', undefined, 'kısaltıldı')}` : ''}</span>
        {doc.ac_refs.map(a => <span key={a} className="px-1.5 py-0.5 rounded border border-ok/40 bg-okd text-ok font-mono">{a}</span>)}
      </div>
      {tab === 'scenarios' ? (
        <div className="flex-1 overflow-y-auto p-5 space-y-4 text-xs">
          {doc.summary && <div className="rounded-lg border border-line bg-sunk/60 p-3 text-ink2 italic">{doc.summary}</div>}
          {doc.scenarios.length === 0 && <div className="text-ink3">{t('project.viewer.noScenarios', undefined, 'Bu dosyada senaryo başlığı bulunamadı.')}</div>}
          {Object.entries(grouped).map(([suite, items]) => (
            <div key={suite}>
              <div className="text-[10px] font-mono font-bold uppercase tracking-wider text-ink3 mb-1">{suite}</div>
              <ul className="space-y-1">
                {items.map(s => (
                  <li key={`${s.line}-${s.name}`}>
                    <button onClick={() => { setJump(s.line); setTab('code'); }}
                      className="w-full text-left flex gap-2 px-2.5 py-1.5 rounded-md hover:bg-sunk border border-transparent hover:border-line" title={t('project.viewer.goToCode', undefined, 'Koda git')}>
                      <span className="text-ok shrink-0">✓</span><span className="text-ink">{s.name}</span><span className="ml-auto text-[10px] font-mono text-ink3 shrink-0">{t('project.viewer.line', { n: s.line }, 'satır {n}')}</span>
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      ) : tab === 'view' ? (
        <div className="flex-1 overflow-y-auto px-8 py-5 text-[13.5px]"><div className="max-w-4xl mx-auto"><MarkdownView text={doc.content} /></div></div>
      ) : (
        <ErrorBoundary label={t('project.viewer.editor', undefined, 'Kod editörü')} compact><Suspense fallback={<div className="p-5 text-xs text-ink3">{t('project.viewer.editorLoading', undefined, 'Editör yükleniyor…')}</div>}><CodeEditor text={doc.content} path={doc.path} line={jump} /></Suspense></ErrorBoundary>
      )}
    </div>
  );
};

const FileViewer: React.FC<{ path: string; line?: number; onClose: () => void }> = ({ path, line, onClose }) => (
  <Overlay onClose={onClose}>
    <Header icon={<FlaskConical className="w-4 h-4 text-ac" />} title={path.split('/').pop() || path} sub={path} onClose={onClose} />
    <FileContent path={path} line={line} />
  </Overlay>
);

const patchLine = (ln: string): string =>
  ln.startsWith('+++') || ln.startsWith('---') || ln.startsWith('diff ') || ln.startsWith('index ') ? 'text-ink3'
    : ln.startsWith('@@') ? 'text-info bg-infod/40'
      : ln.startsWith('+') ? 'text-ok bg-okd/50'
        : ln.startsWith('-') ? 'text-err bg-errd/40' : 'text-ink2';

const CommitViewer: React.FC<{ sha: string; onClose: () => void }> = ({ sha, onClose }) => {
  const { t, lang } = useI18n();
  const [c, setC] = useState<CommitDetail | null>(null);
  const [err, setErr] = useState('');
  useEffect(() => {
    let alive = true;
    setC(null); setErr('');
    getJson<CommitDetail>(`/api/project/commit/${encodeURIComponent(sha)}`).then(d => { if (alive) setC(d); }).catch(e => { if (alive) setErr((e as Error).message); });
    return () => { alive = false; };
  }, [sha]);
  return (
    <Overlay onClose={onClose} wide>
      <Header icon={<GitCommitHorizontal className="w-4 h-4 text-ac" />} title={c ? c.subject : t('project.viewer.commit', { sha: sha.slice(0, 7) }, 'Commit {sha}')}
        sub={c ? `${c.short} · ${c.author} · ${new Date(c.date).toLocaleString(lang)}${c.issue ? ` · ${c.issue}` : ''}` : undefined} onClose={onClose} />
      {err && <div className="p-5 text-xs text-err">{err}</div>}
      {!c && !err && <div className="p-5 text-xs text-ink3">{t('common.loading', undefined, 'Yükleniyor…')}</div>}
      {c && (
        <div className="flex-1 min-h-0 flex">
          <div className="w-80 shrink-0 border-r border-line overflow-y-auto p-3 space-y-3 text-xs">
            {c.body && <div className="rounded-lg border border-line bg-sunk/60 p-2.5 text-ink2 whitespace-pre-wrap">{c.body}</div>}
            <div className="font-mono text-[11px] text-ink3">{t('project.viewer.filesCount', { n: c.files.length }, '{n} dosya')} · <span className="text-ok">+{c.added}</span> <span className="text-err">−{c.deleted}</span></div>
            <ul className="space-y-1">
              {c.files.map(f => (
                <li key={f.path}>
                  <button onClick={() => { onClose(); setTimeout(() => openFile(f.path), 0); }} title={t('project.viewer.openFile', undefined, 'Dosyayı aç')}
                    className="w-full text-left px-2 py-1 rounded-md hover:bg-sunk border border-transparent hover:border-line flex items-center gap-2">
                    <FileText className="w-3 h-3 text-ink3 shrink-0" /><span className="font-mono text-[11px] text-ink break-all">{f.path}</span>
                    <span className="ml-auto font-mono text-[10px] shrink-0"><span className="text-ok">+{f.added ?? '·'}</span> <span className="text-err">−{f.deleted ?? '·'}</span></span>
                  </button>
                </li>
              ))}
            </ul>
          </div>
          <pre className="flex-1 overflow-auto m-0 p-0 text-[11.5px] leading-[17px] font-mono bg-sunk/40">
            {c.patch.split('\n').map((ln, i) => <div key={i} className={`px-3 whitespace-pre ${patchLine(ln)}`}>{ln || ' '}</div>)}
            {c.truncated && <div className="px-3 py-2 text-warn">{t('project.viewer.patchTruncated', undefined, '… yama kısaltıldı (çok büyük)')}</div>}
          </pre>
        </div>
      )}
    </Overlay>
  );
};

const fmtSize = (n: number) => (n < 1024 ? `${n} B` : `${(n / 1024).toFixed(1)} KB`);

const DocsBrowser: React.FC<{ onClose: () => void }> = ({ onClose }) => {
  const { t } = useI18n();
  const [list, setList] = useState<DocsListing | null>(null);
  const [err, setErr] = useState('');
  const [q, setQ] = useState('');
  const [sel, setSel] = useState<string>('');
  useEffect(() => {
    getJson<DocsListing>('/api/project/docs').then(d => { setList(d); const first = d.root[0] || d.docs[0] || d.tests[0]; if (first) setSel(first.path); }).catch(e => setErr((e as Error).message));
  }, []);
  const groups = useMemo(() => {
    if (!list) return [] as { title: string; items: DocEntry[] }[];
    const f = (a: DocEntry[]) => (q.trim() ? a.filter(e => e.path.toLowerCase().includes(q.trim().toLowerCase())) : a);
    const cats: Record<string, DocEntry[]> = {};
    f(list.docs).forEach(e => { (cats[e.category] ||= []).push(e); });
    return [
      { title: t('project.viewer.rootGroup', undefined, 'Proje kökü'), items: f(list.root) },
      ...Object.entries(cats).map(([title, items]) => ({ title: `${t('project.viewer.docsGroup', undefined, 'Dökümanlar')} · ${title}`, items })),
      { title: t('project.viewer.testsGroup', undefined, 'Test dosyaları (senaryolu)'), items: f(list.tests) },
    ].filter(g => g.items.length);
  }, [list, q, t]);
  const onKey = useCallback((e: React.KeyboardEvent) => { if (e.key === 'Escape') onClose(); }, [onClose]);
  return (
    <Overlay onClose={onClose} wide>
      <Header icon={<BookOpen className="w-4 h-4 text-ac" />} title={t('project.viewer.docsTitle', undefined, 'Proje dökümanları ve test senaryoları')} sub={list?.project_dir} onClose={onClose} />
      {err && <div className="p-5 text-xs text-err">{err}</div>}
      <div className="flex-1 min-h-0 flex" onKeyDown={onKey}>
        <div className="w-80 shrink-0 border-r border-line flex flex-col min-h-0">
          <div className="p-2 border-b border-line relative">
            <Search className="w-3.5 h-3.5 text-ink3 absolute left-4 top-1/2 -translate-y-1/2" />
            <input value={q} onChange={e => setQ(e.target.value)} placeholder={t('project.viewer.searchFile', undefined, 'Dosya ara…')} autoFocus className="w-full pl-7 pr-2 py-1 text-xs bg-sunk border border-line rounded-md text-ink placeholder-ink3 focus:outline-none focus:border-ac" />
          </div>
          <div className="flex-1 overflow-y-auto text-xs">
            {!list && !err && <div className="p-3 text-ink3">{t('common.loading', undefined, 'Yükleniyor…')}</div>}
            {groups.map(g => (
              <div key={g.title}>
                <div className="px-3 pt-3 pb-1 mt-1 border-t border-line/60 first:border-t-0 text-[10px] font-mono font-bold uppercase tracking-wider text-ink3 sticky top-0 bg-panel z-10">{g.title} · {g.items.length}</div>
                {g.items.map(e => {
                  const slash = e.path.lastIndexOf('/');
                  const name = e.path.slice(slash + 1);
                  const dir = slash >= 0 ? e.path.slice(0, slash) : '';
                  return (
                    <button key={e.path} onClick={() => setSel(e.path)} title={e.path}
                      className={`w-full text-left pl-7 pr-3 py-1 flex items-center gap-2 hover:bg-sunk border-l-2 ${sel === e.path ? 'bg-acd/50 text-ac border-ac' : 'text-ink border-transparent'}`}>
                      <FileText className="w-3 h-3 shrink-0 text-ink3" />
                      <span className="min-w-0 flex-1">
                        <span className="block truncate font-mono text-[11.5px]">{name}</span>
                        {dir && <span className="block truncate font-mono text-[9.5px] text-ink3">{dir}</span>}
                      </span>
                      <span className="text-[9px] text-ink3 font-mono shrink-0">{fmtSize(e.size)}</span>
                    </button>
                  );
                })}
              </div>
            ))}
            {list && groups.length === 0 && <div className="p-3 text-ink3 italic">{t('project.viewer.noMatch', undefined, 'Eşleşen dosya yok.')}</div>}
          </div>
        </div>
        {sel ? <div className="flex-1 min-w-0 flex flex-col"><div className="px-5 py-2 border-b border-line text-[11px] font-mono text-ink3 truncate">{sel}</div><FileContent path={sel} /></div>
          : <div className="flex-1 flex items-center justify-center text-xs text-ink3">{t('project.viewer.selectFile', undefined, 'Bir dosya seçin.')}</div>}
      </div>
    </Overlay>
  );
};

/** App'te bir kez bağlanır: `openFile / openCommit / openDocs` olaylarını dinleyip ilgili pencereyi açar. */
/** Dosya gezgini: sol tarafta tembel açılan klasör ağacı, sağda seçilen dosyanın içeriği (salt okunur). */
const TreeNode: React.FC<{ entry: TreeEntry; depth: number; sel: string; onSelect: (p: string) => void }> = ({ entry, depth, sel, onSelect }) => {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  const [kids, setKids] = useState<TreeEntry[] | null>(null);
  const [err, setErr] = useState('');
  const toggle = () => {
    if (!open && kids === null) {
      getJson<TreeListing>(`/api/project/tree?path=${encodeURIComponent(entry.path)}`).then(d => setKids(d.entries)).catch(e => { setErr((e as Error).message); setKids([]); });
    }
    setOpen(o => !o);
  };
  const pad = { paddingLeft: 8 + depth * 14 };
  if (entry.type === 'file') {
    return (
      <button onClick={() => onSelect(entry.path)} style={pad} title={entry.path}
        className={`w-full text-left flex items-center gap-1.5 py-1 pr-2 rounded-md text-[12px] font-mono ${sel === entry.path ? 'bg-acd text-ac' : 'text-ink2 hover:bg-sunk'}`}>
        <FileText className="w-3 h-3 shrink-0 text-ink3" /><span className="truncate">{entry.name}</span>
        <span className="ml-auto text-[10px] text-ink3 shrink-0">{fmtSize(entry.size || 0)}</span>
      </button>
    );
  }
  return (
    <div>
      <button onClick={toggle} style={pad} className="w-full text-left flex items-center gap-1 py-1 pr-2 rounded-md text-[12px] font-mono text-ink hover:bg-sunk">
        {open ? <ChevronDown className="w-3 h-3 shrink-0" /> : <ChevronRight className="w-3 h-3 shrink-0" />}
        {open ? <FolderOpen className="w-3.5 h-3.5 shrink-0 text-ac" /> : <Folder className="w-3.5 h-3.5 shrink-0 text-ac" />}
        <span className="truncate">{entry.name}</span>
      </button>
      {open && (
        <div>
          {err && <div className="text-[11px] text-err" style={{ paddingLeft: 8 + (depth + 1) * 14 }}>{err}</div>}
          {kids === null && <div className="text-[11px] text-ink3" style={{ paddingLeft: 8 + (depth + 1) * 14 }}>{t('common.loading', undefined, 'Yükleniyor…')}</div>}
          {kids?.length === 0 && !err && <div className="text-[11px] text-ink3 italic" style={{ paddingLeft: 8 + (depth + 1) * 14 }}>{t('project.viewer.emptyDir', undefined, 'boş')}</div>}
          {kids?.map(k => <TreeNode key={k.path} entry={k} depth={depth + 1} sel={sel} onSelect={onSelect} />)}
        </div>
      )}
    </div>
  );
};

const FilesBrowser: React.FC<{ onClose: () => void }> = ({ onClose }) => {
  const { t } = useI18n();
  const [root, setRoot] = useState<TreeListing | null>(null);
  const [err, setErr] = useState('');
  const [sel, setSel] = useState('');
  const [dock, setDock] = useState<{ moves: { from: string; to: string }[]; conflicts: { from: string; to: string; reason: string }[] } | null>(null);
  const [dockBusy, setDockBusy] = useState(false);
  const [dockMsg, setDockMsg] = useState('');
  const loadTree = () => getJson<TreeListing>('/api/project/tree').then(setRoot).catch(e => setErr((e as Error).message));
  const loadDock = () => fetch('/api/project/relocate-docker', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' })
    .then(r => r.json()).then(j => setDock({ moves: j.moves || [], conflicts: j.conflicts || [] })).catch(() => setDock(null));
  useEffect(() => { loadTree(); loadDock(); }, []);
  const applyDock = async () => {
    setDockBusy(true);
    setDockMsg('');
    try {
      const r = await fetch('/api/project/relocate-docker', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ apply: true }) });
      const j = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error((j as { error?: string }).error || t('project.viewer.httpError', { n: r.status }, `Hata ${r.status}`));
      setDockMsg(`${t('project.viewer.dockMoved', { n: (j.moved || []).length }, '{n} dosya taşındı')}${j.updated?.length ? `, ${t('project.viewer.dockUpdated', { n: j.updated.length }, '{n} belge/spec başvurusu güncellendi')}` : ''}${j.followup_task ? `; ${t('project.viewer.dockFollowup', { key: j.followup_task.key }, 'çevrilemeyen başvurular için {key} işi açıldı')}` : ''}.`);
      await Promise.all([loadTree(), loadDock()]);
    } catch (e) { setDockMsg((e as Error).message); } finally { setDockBusy(false); }
  };
  return (
    <Overlay onClose={onClose} wide>
      <Header icon={<FolderOpen className="w-4 h-4 text-ac" />} title={t('project.viewer.filesTitle', undefined, 'Proje dosyaları')} sub={root?.project_dir} onClose={onClose} />
      {err && <div className="p-5 text-xs text-err">{err}</div>}
      {((dock && dock.moves.length > 0) || dockMsg) && (
        <div className="px-5 py-2 border-b border-line bg-warnd/40 text-xs flex items-center gap-3 flex-wrap">
          {dock && dock.moves.length > 0 && (
            <>
              <span className="font-bold text-warn">{t('project.viewer.dockOutside', { n: dock.moves.length }, 'Docker dosyaları devops/ dışında ({n}):')}</span>
              <span className="font-mono text-ink2 truncate max-w-[55%]" title={dock.moves.map(m => `${m.from} → ${m.to}`).join(' | ')}>{dock.moves.map(m => m.from).join(', ')}</span>
              <button onClick={applyDock} disabled={dockBusy} className="ml-auto px-3 py-1 rounded-lg bg-ink text-bg font-bold hover:opacity-90 disabled:opacity-50">{dockBusy ? t('project.viewer.dockMoving', undefined, 'Taşınıyor…') : t('project.viewer.dockMove', undefined, 'devops/ altına taşı')}</button>
            </>
          )}
          {dockMsg && <span className="text-ink2">{dockMsg}</span>}
          {dock && dock.conflicts.length > 0 && <span className="text-err w-full">{t('project.viewer.dockConflict', undefined, 'Çakışma (taşınmadı):')} {dock.conflicts.map(c => `${c.from} → ${c.to}`).join(', ')}</span>}
        </div>
      )}
      <div className="flex-1 min-h-0 flex">
        <div className="w-80 shrink-0 border-r border-line overflow-y-auto p-2">
          {!root && !err && <div className="p-3 text-xs text-ink3">{t('common.loading', undefined, 'Yükleniyor…')}</div>}
          {root?.entries.map(e => <TreeNode key={e.path} entry={e} depth={0} sel={sel} onSelect={setSel} />)}
          {root && root.entries.length === 0 && <div className="p-3 text-xs text-ink3">{t('project.viewer.emptyProject', undefined, 'Proje klasörü boş.')}</div>}
        </div>
        <div className="flex-1 min-w-0 min-h-0 flex flex-col">
          {sel ? <FileContent path={sel} /> : <div className="p-6 text-xs text-ink3">{t('project.viewer.selectLeft', undefined, 'Soldan bir dosya seçin.')}</div>}
        </div>
      </div>
    </Overlay>
  );
};

export const ProjectViewers: React.FC = () => {
  const [req, setReq] = useState<ViewerRequest | null>(null);
  useEffect(() => {
    const on = (e: Event) => setReq((e as CustomEvent<ViewerRequest>).detail);
    window.addEventListener(VIEWER_EVENT, on);
    return () => window.removeEventListener(VIEWER_EVENT, on);
  }, []);
  const close = useCallback(() => setReq(null), []);
  if (!req) return null;
  if (req.kind === 'file') return <FileViewer path={req.path} line={req.line} onClose={close} />;
  if (req.kind === 'files') return <FilesBrowser onClose={close} />;
  if (req.kind === 'commit') return <CommitViewer sha={req.sha} onClose={close} />;
  return <DocsBrowser onClose={close} />;
};
