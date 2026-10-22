import React, { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { Check, ChevronDown } from 'lucide-react';

interface DropdownProps {
  /** Tetikleyici içeriği (simge + kısa ad) */
  label: React.ReactNode;
  title?: string;
  /** Tetikleyicinin sağında küçük rozet (sayı/durum) */
  badge?: React.ReactNode;
  /** Vurgu: etkin süzgeç, seçili öğe... */
  active?: boolean;
  align?: 'left' | 'right';
  /** Panel genişliği (Tailwind sınıfı) */
  panelClass?: string;
  disabled?: boolean;
  children: (close: () => void) => React.ReactNode;
}

/**
 * Tetikleyici + açılır panel. Panel gövdeye (portal) `position: fixed` olarak basılır: kartların `overflow-hidden` kırpmasına ve
 * `backdrop-filter`/`transform` taşıyan atalarına (sabit konumu bozarlar) takılmaz; dışarı tıklama, Esc, yeniden boyutlanma ve kaydırma ele alınır.
 */
export const Dropdown: React.FC<DropdownProps> = ({ label, title, badge, active, align = 'left', panelClass = 'w-64', disabled, children }) => {
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState<{ top: number; left?: number; right?: number }>({ top: 0 });
  const btnRef = useRef<HTMLButtonElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);

  const place = () => {
    const r = btnRef.current?.getBoundingClientRect();
    if (!r) return;
    setPos(align === 'right'
      ? { top: r.bottom + 4, right: Math.max(8, window.innerWidth - r.right) }
      : { top: r.bottom + 4, left: Math.max(8, r.left) });
  };

  useLayoutEffect(() => {
    if (open) place();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      const t = e.target as Node;
      if (btnRef.current?.contains(t) || panelRef.current?.contains(t)) return;
      setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false); };
    const onMove = () => place();
    document.addEventListener('mousedown', onDown);
    document.addEventListener('keydown', onKey);
    window.addEventListener('resize', onMove);
    window.addEventListener('scroll', onMove, true);
    return () => {
      document.removeEventListener('mousedown', onDown);
      document.removeEventListener('keydown', onKey);
      window.removeEventListener('resize', onMove);
      window.removeEventListener('scroll', onMove, true);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  return (
    <>
      <button
        ref={btnRef}
        type="button"
        disabled={disabled}
        onClick={() => setOpen(o => !o)}
        aria-haspopup="menu"
        aria-expanded={open}
        title={title}
        className={`px-2.5 py-1.5 rounded-lg border text-xs font-semibold whitespace-nowrap transition flex items-center gap-1.5 disabled:opacity-50 ${
          active ? 'bg-acd text-ac border-ac/60' : 'bg-sunk text-ink2 border-line hover:border-line2 hover:text-ink'
        }`}
      >
        {label}
        {badge}
        <ChevronDown className={`w-3 h-3 transition-transform ${open ? 'rotate-180' : ''}`} />
      </button>
      {open && createPortal(
        <div
          ref={panelRef}
          role="menu"
          style={{ position: 'fixed', top: pos.top, left: pos.left, right: pos.right }}
          className={`z-50 ${panelClass} max-w-[92vw] bg-panel border border-line rounded-xl shadow-xl p-1.5 text-ink`}
        >
          {children(() => setOpen(false))}
        </div>,
        document.body
      )}
    </>
  );
};

interface DropdownItemProps {
  icon?: React.ReactNode;
  label: React.ReactNode;
  hint?: string;
  active?: boolean;
  disabled?: boolean;
  danger?: boolean;
  onClick: () => void;
}

/** Açılır panelde tek seçenek: seçili olan işaretlenir. */
export const DropdownItem: React.FC<DropdownItemProps> = ({ icon, label, hint, active, disabled, danger, onClick }) => (
  <button
    type="button"
    role="menuitem"
    disabled={disabled}
    title={hint}
    onClick={onClick}
    className={`w-full flex items-center gap-2 px-2.5 py-1.5 rounded-lg text-[11px] text-left transition disabled:opacity-50 ${
      danger ? 'text-err hover:bg-errd/40' : active ? 'bg-acd text-ac' : 'text-ink hover:bg-sunk'
    }`}
  >
    {icon}
    <span className="flex-1 min-w-0">
      <span className="block truncate">{label}</span>
      {hint && <span className="block text-[10px] text-ink3 truncate">{hint}</span>}
    </span>
    {active && <Check className="w-3.5 h-3.5 shrink-0" />}
  </button>
);
