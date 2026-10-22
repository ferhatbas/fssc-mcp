import React, { useEffect, useRef, useState } from 'react';
import { api } from '../config';
import { useI18n } from '../i18n';

interface SprintOpt { n: number; status: string }

const STATUS_KEYS = ['PLANNING', 'COMMITTED', 'IN_PROGRESS', 'IN_REVIEW', 'BLOCKED', 'CLOSED', 'CANCELLED'];
const STATUS_FALLBACK: Record<string, string> = { PLANNING: 'planlanıyor', COMMITTED: 'taahhüt edildi', IN_PROGRESS: 'sürüyor', IN_REVIEW: 'gözden geçirmede', BLOCKED: 'durdu', CLOSED: 'kapandı', CANCELLED: 'iptal' };

/** PI planlama raporları ana ekranda: sprint seçilebilir (tüm proje ya da tek sprintin burndown'ı, görev listesi ve ölçümleri). Rapor sunucuda çizilir, gömülü kipte açılır. */
export const ReportsView: React.FC = () => {
  const { t } = useI18n();
  const statusLabel = (s: string) => (STATUS_KEYS.includes(s) ? t(`misc.reports.status.${s}`, undefined, STATUS_FALLBACK[s]) : s);
  const [sprints, setSprints] = useState<SprintOpt[]>([]);
  const [sel, setSel] = useState<string>('all');
  const [stamp, setStamp] = useState(() => Date.now());
  const frame = useRef<HTMLIFrameElement>(null);
  const theme = document.documentElement.getAttribute('data-theme') === 'dark' ? 'dark' : 'light';

  useEffect(() => {
    fetch(api('/api/reports/pi')).then(r => r.json()).then(j => setSprints((j?.sprint_options || []) as SprintOpt[])).catch(() => undefined);
  }, [stamp]);

  const src = api(`/api/reports/pi.html?embed=1&theme=${theme}${sel === 'all' ? '' : `&sprint=${sel}`}&t=${stamp}`);
  const idx = sprints.findIndex(s => String(s.n) === sel);

  return (
    <div className="flex-1 min-h-0 bg-panel border border-line rounded-panel shadow-panel flex flex-col overflow-hidden">
      <div className="flex flex-wrap items-center gap-2 px-4 py-2.5 border-b border-line">
        <h2 className="text-sm font-bold text-ink">{t('misc.reports.title', undefined, 'PI planlama raporları')}</h2>
        <div className="flex items-center bg-sunk p-0.5 rounded-lg border border-line" role="group" aria-label={t('misc.reports.scope', undefined, 'Kapsam')}>
          <button onClick={() => setSel('all')} aria-pressed={sel === 'all'} className={`px-2.5 py-1 rounded-md text-[11px] font-semibold ${sel === 'all' ? 'bg-panel text-ink shadow-panel border border-line/60' : 'text-ink3 hover:text-ink'}`}>{t('misc.reports.allProject', undefined, 'Tüm proje')}</button>
          <button onClick={() => sprints.length && setSel(sel === 'all' ? String(sprints[sprints.length - 1].n) : sel)} aria-pressed={sel !== 'all'} className={`px-2.5 py-1 rounded-md text-[11px] font-semibold ${sel !== 'all' ? 'bg-panel text-ink shadow-panel border border-line/60' : 'text-ink3 hover:text-ink'}`}>{t('misc.reports.sprint', undefined, 'Sprint')}</button>
        </div>
        <button disabled={idx <= 0} onClick={() => setSel(String(sprints[idx - 1].n))} aria-label={t('misc.reports.prevSprint', undefined, 'Önceki sprint')} className="px-2 py-1 rounded-lg border border-line text-ink2 text-xs disabled:opacity-40">‹</button>
        <select
          value={sel}
          onChange={e => setSel(e.target.value)}
          aria-label={t('misc.reports.pickSprint', undefined, 'Sprint seç')}
          className="bg-panel border border-line rounded-lg px-2 py-1 text-xs text-ink"
        >
          <option value="all">{t('misc.reports.allSprints', undefined, 'Tüm sprintler')}</option>
          {sprints.slice().reverse().map(s => <option key={s.n} value={String(s.n)}>{t('misc.reports.sprint', undefined, 'Sprint')} {s.n} · {statusLabel(s.status)}</option>)}
        </select>
        <button disabled={idx < 0 || idx >= sprints.length - 1} onClick={() => setSel(String(sprints[idx + 1].n))} aria-label={t('misc.reports.nextSprint', undefined, 'Sonraki sprint')} className="px-2 py-1 rounded-lg border border-line text-ink2 text-xs disabled:opacity-40">›</button>
        <span className="flex-1" />
        <button onClick={() => setStamp(Date.now())} className="px-2.5 py-1 rounded-lg border border-line text-ink2 text-xs hover:text-ink" title={t('misc.reports.refreshTip', undefined, 'Raporu güncel veriyle yeniden çiz')}>{t('misc.reports.refresh', undefined, 'Yenile')}</button>
        <button onClick={() => { try { frame.current?.contentWindow?.print(); } catch { /* yoksay */ } }} className="px-2.5 py-1 rounded-lg border border-line text-ink2 text-xs hover:text-ink" title={t('misc.reports.printTip', undefined, 'Yazdır ya da PDF olarak kaydet')}>{t('misc.reports.print', undefined, 'Yazdır / PDF')}</button>
      </div>
      <iframe ref={frame} key={src} src={src} title={t('misc.reports.frameTitle', undefined, 'PI planlama raporu')} className="flex-1 w-full border-0 bg-transparent" />
    </div>
  );
};
