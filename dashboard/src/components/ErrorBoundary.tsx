import React from 'react';
import { translate } from '../i18n';

/** Bir bileşen çökerse tüm panonun boşalmasını önler: hata gösterir, tek tıkla yeniden dener / sayfayı yeniler.
 *  Pano yeniden derlendiğinde açık sekmedeki eski paket, silinen parça dosyalarını (hash'li) bulamaz; bu da en sık nedendir. */
interface Props { children: React.ReactNode; label?: string; compact?: boolean }
interface State { error: Error | null }

export class ErrorBoundary extends React.Component<Props, State> {
  state: State = { error: null };
  static getDerivedStateFromError(error: Error): State { return { error }; }
  componentDidCatch(error: Error) { console.error('[ErrorBoundary]', this.props.label || '', error); }
  render() {
    if (!this.state.error) return this.props.children;
    const stale = /dynamically imported module|Importing a module script failed|ChunkLoadError/i.test(this.state.error.message);
    return (
      <div className={`${this.props.compact ? 'p-4' : 'p-8'} text-xs text-ink2 space-y-2`}>
        <div className="font-semibold text-err">{translate('misc.error.loadFailed', { label: this.props.label || translate('misc.error.thisSection', undefined, 'Bu bölüm') }, '{label} yüklenemedi.')}</div>
        <div className="text-ink3">{stale ? translate('misc.error.stale', undefined, 'Pano güncellendi; açık sekme eski sürümü kullanıyor. Sayfayı yenilemek yeterli.') : this.state.error.message}</div>
        <div className="flex gap-2">
          <button onClick={() => this.setState({ error: null })} className="px-2.5 py-1 rounded-lg border border-line hover:text-ink">{translate('misc.error.retry', undefined, 'Yeniden dene')}</button>
          <button onClick={() => window.location.reload()} className="px-2.5 py-1 rounded-lg border border-ac/40 text-ac bg-acd/40">{translate('misc.error.reload', undefined, 'Sayfayı yenile')}</button>
        </div>
      </div>
    );
  }
}

/** Dinamik içe aktarma başarısızsa (eski sekme, silinmiş parça) sayfayı bir kez yeniler; döngüye girmez. */
export function importWithReload<T>(load: () => Promise<T>): Promise<T> {
  return load().catch((err) => {
    let reloaded = false;
    try { reloaded = sessionStorage.getItem('fssc_chunk_reload') === '1'; sessionStorage.setItem('fssc_chunk_reload', '1'); } catch { /* yoksay */ }
    if (!reloaded) { window.location.reload(); return new Promise<T>(() => undefined); }
    try { sessionStorage.removeItem('fssc_chunk_reload'); } catch { /* yoksay */ }
    throw err;
  });
}
