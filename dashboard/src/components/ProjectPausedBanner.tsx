import React, { useCallback, useEffect, useState } from 'react';
import { PauseCircle, Play, TrendingUp } from 'lucide-react';
import { api } from '../config';
import { useI18n } from '../i18n';

interface PausedInfo { status: string; sprints: number; limit: number; budget: number; reason?: { code: string; detail: string } | null }

/** Proje seviyesinde duraklatma göstergesi: sprint bütçesi (`max_sprints`) dolunca proje PAUSED olur ve yeni sprint planlanmaz; bu şerit nedenini söyler ve tek tıkla sürdürür. */
export const ProjectPausedBanner: React.FC = () => {
  const { t } = useI18n();
  const [info, setInfo] = useState<PausedInfo | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');

  const load = useCallback(async () => {
    try {
      const [s, a] = await Promise.all([fetch(api('/api/sprints')).then(r => r.json()), fetch(api('/api/settings/autonomy')).then(r => r.json())]);
      const budget = Number(a?.autonomy?.budget?.max_sprints) || 0;
      const cfg = Number(s?.settings?.max_sprints) || 0;
      setInfo({ reason: s?.state?.pause_reason || null, status: String(s?.state?.project_status || ''), sprints: (s?.state?.sprints || []).length, limit: Math.min(cfg || budget, budget || cfg), budget });
    } catch { /* sunucu yoksa şerit gösterilmez */ }
  }, []);

  useEffect(() => {
    load();
    const t = setInterval(load, 15000);
    return () => clearInterval(t);
  }, [load]);

  if (!info || info.status !== 'PAUSED') return null;

  const post = async (url: string, body?: unknown) => {
    setBusy(true);
    setErr('');
    try {
      const r = await fetch(api(url), { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: body ? JSON.stringify(body) : undefined });
      const j = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error((j as { error?: string }).error || t('project.paused.httpError', { n: r.status }, `Hata ${r.status}`));
      await load();
    } catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  };

  const full = info.sprints >= info.limit;
  if (info.reason?.code === 'REPEATING_SPRINTS') {
    return (
      <div className="bg-warnd/60 border border-warn/60 rounded-panel px-4 py-2.5 shrink-0 flex items-center gap-3 flex-wrap text-xs text-ink">
        <PauseCircle className="w-4 h-4 text-warn shrink-0" />
        <span className="font-bold text-warn">{t('project.paused.repeatTitle', undefined, 'Sprint zinciri durduruldu: aynı iş tekrarlanıyor')}</span>
        <span className="text-ink2 truncate" title={info.reason.detail}>{info.reason.detail}</span>
        <span className="ml-auto flex items-center gap-2">
          {err && <span className="text-err">{err}</span>}
          <button disabled={busy} onClick={() => post('/api/project/resume', { acknowledge: true })}
            className="inline-flex items-center gap-1 px-3 py-1.5 rounded-lg bg-ink text-bg font-bold hover:opacity-90 disabled:opacity-50" title={t('project.paused.repeatTitleHint', undefined, 'Nedeni çözdükten sonra zinciri yeniden başlatır')}>
            <Play className="w-3.5 h-3.5" />{t('project.paused.repeatResume', undefined, 'Nedeni gördüm, devam et')}
          </button>
        </span>
      </div>
    );
  }
  return (
    <div className="bg-warnd/60 border border-warn/60 rounded-panel px-4 py-2.5 shrink-0 flex items-center gap-3 flex-wrap text-xs text-ink">
      <PauseCircle className="w-4 h-4 text-warn shrink-0" />
      <span className="font-bold text-warn">{t('project.paused.title', undefined, 'Proje duraklatıldı')}</span>
      <span className="text-ink2">{t('project.paused.body', { done: info.sprints, limit: info.limit }, 'Sprint bütçesi doldu ({done}/{limit}); yeni sprint planlanmıyor, ürün ilerlemiyor.')}</span>
      <span className="ml-auto flex items-center gap-2">
        {err && <span className="text-err">{err}</span>}
        {full ? (
          <button disabled={busy} onClick={async () => {
            // Sınır iki yerde durur: sprint ayarı (max_sprints) ve özerklik bütçesi; ikisi de artırılır, sonra proje sürdürülür
            const next = Math.min(Math.max(info.limit, info.sprints) + 10, 100);
            await post('/api/settings/sprint', { max_sprints: next });
            if (info.budget < next) await post('/api/settings/autonomy', { budget: { max_sprints: next } });
            await post('/api/project/resume');
          }}
            className="inline-flex items-center gap-1 px-3 py-1.5 rounded-lg bg-ink text-bg font-bold hover:opacity-90 disabled:opacity-50" title={t('project.paused.raiseTitle', undefined, 'Bütçeyi 10 sprint artırır ve projeyi sürdürür')}>
            <TrendingUp className="w-3.5 h-3.5" />{t('project.paused.raise', undefined, 'Bütçeyi +10 artır ve devam et')}
          </button>
        ) : (
          <button disabled={busy} onClick={() => post('/api/project/resume')}
            className="inline-flex items-center gap-1 px-3 py-1.5 rounded-lg bg-ink text-bg font-bold hover:opacity-90 disabled:opacity-50"><Play className="w-3.5 h-3.5" />{t('project.paused.resume', undefined, 'Devam et')}</button>
        )}
      </span>
    </div>
  );
};
