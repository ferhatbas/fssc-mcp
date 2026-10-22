import React, { useCallback, useEffect, useState } from 'react';
import { api } from '../config';
import { useI18n } from '../i18n';

const STATUS_TR: Record<string, string> = { PLANNING: 'planlanıyor', COMMITTED: 'taahhüt edildi', IN_PROGRESS: 'sürüyor', IN_REVIEW: 'gözden geçirmede', BLOCKED: 'DURDU', CLOSED: 'kapandı', CANCELLED: 'iptal' }; // yedek metin; çeviri sprint.status.<KOD>

interface Kpi { label: string; value: string; hint: string; pct?: number; tone?: 'ok' | 'warn' | 'err' }

/** Sprint ve takım durumu bir bakışta: sprint ilerlemesi, hız, açık hata, öngörülebilirlik. Veri: /api/sprints/board + /api/reports/pi (30 sn'de bir). */
export const SprintKpiStrip: React.FC = () => {
  const { t } = useI18n();
  const [kpis, setKpis] = useState<Kpi[] | null>(null);

  const load = useCallback(async () => {
    try {
      const [b, p] = await Promise.all([fetch(api('/api/sprints/board')).then(r => r.json()), fetch(api('/api/reports/pi')).then(r => r.json())]);
      const cur = b?.current;
      const s = p?.summary || {};
      const f = p?.forecast || {};
      const list: Kpi[] = [];
      if (cur) {
        const pct = cur.committed ? Math.round((cur.done / cur.committed) * 100) : 0;
        list.push({ label: `Sprint ${cur.sprint_number} · ${STATUS_TR[cur.status] ? t(`sprint.status.${cur.status}`, undefined, STATUS_TR[cur.status]) : cur.status}`, value: t('sprint.kpi.tasksOf', { done: cur.done, total: cur.committed }, '{done} / {total} görev'), hint: t('sprint.kpi.pctDone', { pct }, '%{pct} tamamlandı'), pct, tone: cur.status === 'BLOCKED' ? 'err' : undefined });
      } else {
        list.push({ label: 'Sprint', value: '—', hint: t('sprint.kpi.noSprint', undefined, 'Henüz sprint yok') });
      }
      list.push({ label: t('sprint.kpi.velocity', undefined, 'Hız (son 3 sprint)'), value: f.velocity_avg3 != null ? String(f.velocity_avg3) : '—', hint: f.remaining != null ? t('sprint.kpi.perSprintRemaining', { n: f.remaining }, 'görev/sprint · {n} iş kaldı') : t('sprint.kpi.perSprint', undefined, 'görev/sprint') });
      list.push({ label: t('sprint.kpi.openBugs', undefined, 'Açık hata'), value: String(s.open_bugs ?? 0), hint: t('sprint.kpi.tasksDone', { done: s.tasks_done ?? 0, total: s.tasks_total ?? 0 }, '{done}/{total} görev bitti'), tone: (s.open_bugs ?? 0) > 20 ? 'warn' : undefined });
      list.push({ label: t('sprint.kpi.predictability', undefined, 'Öngörülebilirlik'), value: s.predictability != null ? `%${s.predictability}` : '—', hint: t('sprint.kpi.predictabilityHint', { n: s.sprints_closed ?? 0 }, 'biten ÷ taahhüt · {n} sprint') });
      setKpis(list);
    } catch { /* sunucu yoksa şerit gösterilmez */ }
  }, [t]);
  useEffect(() => {
    void load();
    const iv = setInterval(load, 30000);
    return () => clearInterval(iv);
  }, [load]);

  if (!kpis) return null;
  const tone = (x?: string) => (x === 'err' ? 'text-err' : x === 'warn' ? 'text-warn' : 'text-ink');
  return (
    <section aria-label={t('sprint.kpi.summary', undefined, 'Özet')} className="grid grid-cols-4 gap-2 shrink-0">
      {kpis.map(k => (
        <div key={k.label} className="relative bg-panel border border-line rounded-lg shadow-panel px-2.5 py-1 min-w-0 flex items-baseline gap-2 overflow-hidden" title={k.hint}>
          <span className="text-[10.5px] text-ink3 truncate">{k.label}</span>
          <span className={`text-[13px] font-semibold leading-tight whitespace-nowrap ${tone(k.tone)}`}>{k.value}</span>
          <span className="text-[10px] text-ink3 truncate hidden min-[1700px]:inline">{k.hint}</span>
          {k.pct != null && (
            <div className="absolute left-0 right-0 bottom-0 h-0.5 bg-sunk" role="img" aria-label={t('sprint.kpi.progressAria', { pct: k.pct }, 'Sprint ilerlemesi yüzde {pct}')}>
              <div className={`h-full ${k.tone === 'err' ? 'bg-err' : 'bg-ac'}`} style={{ width: `${k.pct}%` }} />
            </div>
          )}
        </div>
      ))}
    </section>
  );
};
