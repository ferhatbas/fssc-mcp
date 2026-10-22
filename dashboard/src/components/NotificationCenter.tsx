import React, { useEffect, useRef, useState } from 'react';
import { Bell, Check, Trash2 } from 'lucide-react';
import { AppNotification, Severity } from '../lib/serverEvents';
import { useI18n } from '../i18n';

/** G8: bildirim merkezi — sunucunun yayınladığı önemli olaylar (sprint engeli, bütçe, soru, otonomi durdu ...) tek yerde, okundu/temizle ile. */
interface Props {
  notifications: AppNotification[];
  onMarkRead: () => void;
  onClear: () => void;
}

const DOT: Record<Severity, string> = { info: 'bg-info', success: 'bg-ok', warn: 'bg-warn', error: 'bg-err' };

const ago = (iso: string, t: (k: string, p?: Record<string, string | number>, f?: string) => string): string => {
  const s = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 1000));
  if (s < 60) return t('misc.notif.sec', { n: s }, '{n} sn');
  if (s < 3600) return t('misc.notif.min', { n: Math.round(s / 60) }, '{n} dk');
  return t('misc.notif.hour', { n: Math.round(s / 3600) }, '{n} sa');
};

export const NotificationCenter: React.FC<Props> = ({ notifications, onMarkRead, onClear }) => {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  const [alignLeft, setAlignLeft] = useState(false);   // düğme ekranın sol yarısındaysa panel sağa doğru açılır (aksi halde ekran dışına taşar)
  const ref = useRef<HTMLDivElement>(null);
  const unread = notifications.filter(n => !n.read).length;
  const worst = notifications.some(n => !n.read && n.severity === 'error') ? 'err' : notifications.some(n => !n.read && n.severity === 'warn') ? 'warn' : 'ac';

  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false); };
    document.addEventListener('mousedown', close);
    return () => document.removeEventListener('mousedown', close);
  }, [open]);

  return (
    <div className="relative" ref={ref} data-testid="notification-center">
      <button
        type="button"
        onClick={e => { setAlignLeft(e.currentTarget.getBoundingClientRect().left < window.innerWidth / 2); setOpen(o => !o); if (!open && unread) onMarkRead(); }}
        className="relative p-1.5 rounded-md border border-line bg-panel text-ink2 hover:text-ink transition"
        title={t('misc.notif.tip', undefined, 'Bildirim merkezi: sprint engeli, bütçe, soru, otonomi ve daha fazlası')}
        aria-label={t('misc.notif.label', undefined, 'Bildirimler')}
      >
        <Bell className="w-3.5 h-3.5" />
        {unread > 0 && (
          <span className={`absolute -top-1.5 -right-1.5 min-w-[16px] h-4 px-1 rounded-full text-[9px] font-mono font-bold flex items-center justify-center text-onac ${worst === 'err' ? 'bg-err' : worst === 'warn' ? 'bg-warn' : 'bg-ac'}`}>
            {unread > 99 ? '99+' : unread}
          </span>
        )}
      </button>
      {open && (
        <div className={`absolute ${alignLeft ? 'left-0' : 'right-0'} top-full mt-1.5 w-80 max-w-[calc(100vw-1.5rem)] max-h-96 overflow-y-auto rounded-xl border border-line2 bg-panel shadow-2xl z-50`}>
          <div className="flex items-center justify-between px-3 py-2 border-b border-line sticky top-0 bg-panel">
            <span className="text-[11px] font-bold text-ink uppercase tracking-wider">{t('misc.notif.heading', { n: notifications.length }, 'Bildirimler ({n})')}</span>
            <span className="flex items-center gap-2">
              <button type="button" onClick={onMarkRead} className="text-[10px] text-ink3 hover:text-ink flex items-center gap-1"><Check className="w-3 h-3" />{t('misc.notif.read', undefined, 'okundu')}</button>
              <button type="button" onClick={onClear} className="text-[10px] text-ink3 hover:text-err flex items-center gap-1"><Trash2 className="w-3 h-3" />{t('misc.notif.clear', undefined, 'temizle')}</button>
            </span>
          </div>
          {notifications.length === 0 && <p className="p-4 text-xs text-ink3 text-center">{t('misc.notif.empty', undefined, 'Henüz bildirim yok.')}</p>}
          {notifications.map(n => (
            <div key={n.id} className={`px-3 py-2 border-b border-line text-xs ${n.read ? 'opacity-70' : ''}`}>
              <div className="flex items-start gap-2">
                <span className={`mt-1 w-2 h-2 rounded-full shrink-0 ${DOT[n.severity]}`} />
                <div className="min-w-0 flex-1">
                  <p className="font-semibold text-ink">{n.title}</p>
                  {n.detail && <p className="text-ink3 break-words">{n.detail}</p>}
                  <p className="text-[10px] text-ink3 font-mono">{n.type} · {t('misc.notif.ago', { t: ago(n.at, t) }, '{t} önce')}</p>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};
