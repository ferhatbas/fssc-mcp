import React, { useEffect, useRef, useState } from 'react';
import { ChevronDown } from 'lucide-react';

export interface ToolbarMenuItem {
  key: string;
  label: string;
  icon?: React.ReactNode;
  /** Sağda küçük sayı/etiket */
  badge?: React.ReactNode;
  /** Dikkat gerektiriyor (cevap bekleyen soru, bekleyen karar...) */
  alert?: boolean;
  disabled?: boolean;
  title?: string;
  onClick: () => void;
}

interface ToolbarMenuProps {
  label: string;
  icon?: React.ReactNode;
  items: ToolbarMenuItem[];
  title?: string;
  /** Sol ray düğmesi: dikey simge+etiket, menü sağa açılır */
  rail?: boolean;
}

/** Üst araç çubuğunda ilişkili düğmeleri tek açılır menüde toplar; menüdeki bir öğe dikkat istiyorsa tetikleyici de işaretlenir. */
export const ToolbarMenu: React.FC<ToolbarMenuProps> = ({ label, icon, items, title, rail }) => {
  const [open, setOpen] = useState(false);
  const [up, setUp] = useState(false);           // ray menüsü ekranın alt yarısındaysa yukarı açılır (taşmaz)
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false); };
    document.addEventListener('mousedown', onDown);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onDown);
      document.removeEventListener('keydown', onKey);
    };
  }, [open]);

  const alerts = items.filter(i => i.alert).length;

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => { setUp(!!rail && (ref.current?.getBoundingClientRect().top ?? 0) > window.innerHeight / 2); setOpen(o => !o); }}
        aria-haspopup="menu"
        aria-expanded={open}
        title={title}
        className={rail
          ? `relative w-14 py-1.5 rounded-[10px] transition flex flex-col items-center gap-0.5 text-[10px] font-medium ${open ? 'bg-[#2B3040] text-white' : alerts ? 'text-[#F5B454] bg-[#3A2F1B]' : 'text-[#9AA1B2] hover:text-white hover:bg-[#262B38]'}`
          : `px-2 py-0.5 rounded-md border transition flex items-center gap-1 text-[11px] font-medium whitespace-nowrap ${alerts ? 'bg-warnd border-warn/50 text-warn' : 'bg-panel2 hover:bg-sunk text-ink border-line'}`}
      >
        {rail ? <span className="[&>svg]:w-5 [&>svg]:h-5">{icon}</span> : icon}
        {label}
        {alerts > 0 && (
          <span className={`text-[9px] px-1.5 rounded-full font-mono font-bold bg-warn text-onac animate-pulse ${rail ? 'absolute top-0.5 right-1' : ''}`}>{alerts}</span>
        )}
        {!rail && <ChevronDown className={`w-3 h-3 transition-transform ${open ? 'rotate-180' : ''}`} />}
      </button>
      {open && (
        <div role="menu" className={`absolute z-50 min-w-[220px] bg-panel border border-line rounded-xl shadow-xl p-1 ${rail ? `left-full ml-2 ${up ? 'bottom-0' : 'top-0'} max-h-[calc(100vh-24px)] overflow-y-auto` : 'right-0 top-full mt-1'}`}>
          {items.map(it => (
            <button
              key={it.key}
              role="menuitem"
              type="button"
              disabled={it.disabled}
              title={it.title}
              onClick={() => { setOpen(false); it.onClick(); }}
              className={`w-full flex items-center gap-2 px-2.5 py-1.5 rounded-lg text-[11px] text-left transition disabled:opacity-50 ${
                it.alert ? 'text-warn bg-warnd/50 hover:bg-warnd' : 'text-ink hover:bg-sunk'
              }`}
            >
              {it.icon}
              <span className="flex-1">{it.label}</span>
              {it.badge}
            </button>
          ))}
        </div>
      )}
    </div>
  );
};
