import React, { useLayoutEffect, useMemo, useRef, useState } from 'react';
import { Agent, AgentRole } from '../types/telemetry';
import { DEPARTMENTS, departmentOf, DepartmentDef } from '../office/departments';
import type { Gathering } from '../topology/hexLayout';
import { useI18n } from '../i18n';

interface AgentOfficeProps {
  agents: Agent[];
  activeEdgeId?: string | null;
  edgeStatus?: 'SUCCESS' | 'FAILED';
  /** Avatara tıklayınca ajan zaman çizelgesi (D1) */
  onSelectAgent?: (agentId: string) => void;
  selectedAgentId?: string | null;
  /** C1: toplantı masasına toplanma (müzakere / onay) */
  gathering?: Gathering;
}

/* ------------------------------------------------------------------------------------------------
 * Yerleşim: departman odaları raflar (satırlar) hâlinde dizilir, odalar içinde masalar 4'erli sıralarla
 * sarılır, toplantı odası ayrı bir odadır. Temel tuval BASE_W genişliğinde tasarlanır ve kapsayıcıya
 * sığacak şekilde ölçeklenir (taşma/yatay kaydırma yok).
 * ---------------------------------------------------------------------------------------------- */
const BASE_W = 1320;
const WALL_H = 74;
const MARGIN = 24;
const ROOM_GAP = 28;
const SHELF_GAP = 26;
const DESK_W = 132;
const SLOT_W = 190;      // masa aralığı (masa 132 + boşluk)
const ROW_PITCH = 150;   // aynı odada ikinci masa sırası
const ROOM_PAD_X = 16;
const ROOM_TOP = 82;     // oda üst kenarı → masa üstü (etiket + baloncuk + karakter)
const ROOM_BOTTOM = 76;  // masa üstü → oda alt kenarı (masa + isim rozeti)
const MAX_PER_ROW = 4;
const MEETING_ROOM = { w: 200, h: 200, r: 34 };
const ROOM_ORDER: (DepartmentDef['id'] | 'MEETING')[] = ['ANALIZ', 'TEST', 'MEETING', 'YAZILIM', 'DESTEK'];

interface DeskSlot {
  key: string;
  desk: [number, number];
  char: [number, number];
  shelf: number;
}
interface Room {
  id: string;
  label: string;
  color: string;
  kind: 'dept' | 'meeting';
  x: number;
  y: number;
  w: number;
  h: number;
  count: number;
}
interface OfficeLayout {
  rooms: Room[];
  slots: Map<string, DeskSlot>;
  meeting: { x: number; y: number; r: number };
  shelves: { top: number; bottom: number }[];
  width: number;
  height: number;
}

function computeLayout(entries: { key: string; deptId: DepartmentDef['id'] }[]): OfficeLayout {
  const byDept = new Map<string, string[]>();
  for (const e of entries) byDept.set(e.deptId, [...(byDept.get(e.deptId) || []), e.key]);

  const specs = ROOM_ORDER.map(id => {
    if (id === 'MEETING') return { id, label: 'Toplantı Odası', color: 'warn', kind: 'meeting' as const, keys: [] as string[], w: MEETING_ROOM.w, h: MEETING_ROOM.h };
    const dept = DEPARTMENTS.find(d => d.id === id)!;
    const keys = byDept.get(id) || [];
    if (keys.length === 0) return null;
    const cols = Math.min(keys.length, MAX_PER_ROW);
    const rows = Math.ceil(keys.length / MAX_PER_ROW);
    return { id, label: dept.label, color: dept.color, kind: 'dept' as const, keys, w: cols * SLOT_W - (SLOT_W - DESK_W) + ROOM_PAD_X * 2, h: ROOM_TOP + (rows - 1) * ROW_PITCH + ROOM_BOTTOM };
  }).filter((s): s is NonNullable<typeof s> => !!s);

  // Raf paketleme: sığmayan oda bir sonraki rafa geçer
  const rooms: Room[] = [];
  const slots = new Map<string, DeskSlot>();
  const shelves: { top: number; bottom: number }[] = [];
  let meeting = { x: 0, y: 0, r: MEETING_ROOM.r };
  let x = MARGIN, shelfTop = WALL_H + 16, shelfH = 0, shelfIdx = 0;
  const closeShelf = () => {
    shelves.push({ top: shelfTop, bottom: shelfTop + shelfH });
    shelfTop += shelfH + SHELF_GAP;
    shelfH = 0;
    x = MARGIN;
    shelfIdx += 1;
  };
  for (const s of specs) {
    if (x + s.w > BASE_W - MARGIN && x > MARGIN) closeShelf();
    const room: Room = { id: s.id, label: s.label, color: s.color, kind: s.kind, x, y: shelfTop, w: s.w, h: s.h, count: s.keys.length };
    rooms.push(room);
    if (s.kind === 'meeting') {
      meeting = { x: room.x + room.w / 2, y: room.y + room.h / 2 + 8, r: MEETING_ROOM.r };
    } else {
      s.keys.forEach((key, i) => {
        const col = i % MAX_PER_ROW, row = Math.floor(i / MAX_PER_ROW);
        const dx = room.x + ROOM_PAD_X + col * SLOT_W, dy = room.y + ROOM_TOP + row * ROW_PITCH;
        slots.set(key, { key, desk: [dx, dy], char: [dx + 56, dy - 24], shelf: shelfIdx });
      });
    }
    shelfH = Math.max(shelfH, s.h);
    x += s.w + ROOM_GAP;
  }
  if (shelfH > 0) closeShelf();
  const height = (shelves.length ? shelves[shelves.length - 1].bottom : WALL_H) + MARGIN;
  return { rooms, slots, meeting, shelves, width: BASE_W, height };
}

/** Sabit akış hatları (10 adımlı pipeline'ın ana yolu) */
const FLOWS: [string, string, string][] = [
  ['PM', 'ARCHITECT', 'ac'],
  ['ARCHITECT', 'BACKEND_DEV', 'ac'],
  ['ARCHITECT', 'DESIGNER', 'ac'],
  ['DESIGNER', 'FRONTEND_DEV', 'info'],
  ['BACKEND_DEV', 'FRONTEND_DEV', 'ok'],
  ['FRONTEND_DEV', 'E2E_TESTER', 'warn'],
  ['QA', 'BACKEND_DEV', 'err'],
  ['E2E_TESTER', 'DEVOPS', 'ok'],
  ['DEVOPS', 'PO', 'ac'],
  ['PO', 'DOCUMENTOR', 'info'],
];

/** Masa altından koridora inen, koridor boyunca giden, hedefe çıkan dirsekli hat */
function connectorPath(a: DeskSlot, b: DeskSlot, layout: OfficeLayout): string {
  const ax = a.desk[0] + DESK_W / 2, bx = b.desk[0] + DESK_W / 2;
  const bottomOf = (s: DeskSlot) => s.desk[1] + 40;
  const topOf = (s: DeskSlot) => s.desk[1] - 30;
  const corridor = (i: number) => layout.shelves[i].bottom + SHELF_GAP / 2;
  if (a.shelf === b.shelf) {
    const cy = corridor(a.shelf);
    return `M ${ax} ${bottomOf(a)} L ${ax} ${cy} L ${bx} ${cy} L ${bx} ${bottomOf(b)}`;
  }
  const upper = a.shelf < b.shelf ? a : b, lower = a.shelf < b.shelf ? b : a;
  const cy = corridor(upper.shelf);
  const ux = upper.desk[0] + DESK_W / 2, lx = lower.desk[0] + DESK_W / 2;
  return `M ${ux} ${bottomOf(upper)} L ${ux} ${cy} L ${lx} ${cy} L ${lx} ${topOf(lower)}`;
}

const CUSTOM_PALETTE = ['#5b6ee0', '#2f9b92', '#d2705f', '#8a6bd1', '#7f9a45', '#d3a03f', '#556274'];

function hashCode(str: string): number {
  let h = 0;
  for (let i = 0; i < str.length; i++) h = (h * 31 + str.charCodeAt(i)) | 0;
  return Math.abs(h);
}

/** Kayıtlı olmayan ajan için görünüm üretir (renk kimlikten türetilir) */
function customConf(agent: Agent): RoleLook {
  const color = CUSTOM_PALETTE[hashCode(agent.id) % CUSTOM_PALETTE.length];
  return {
    look: { skin: '#e9c0a3', hair: '#2b2620', shirt: color, shirt2: color, pants: '#2b3445' },
    bars: [[30, color], [22, '#eef1f7'], [18, color]],
    roleColor: color,
    label: agent.id.slice(0, 12),
  };
}

function RoomBox({ room }: { room: Room }) {
  const { t } = useI18n();
  const roomLabel = room.kind === 'meeting' ? t('agents.hex.meetingRoom', undefined, room.label) : t(`agents.dept.${room.id}`, undefined, room.label);
  return (
    <div style={{ position: 'absolute', left: room.x, top: room.y, width: room.w, height: room.h, zIndex: 5, pointerEvents: 'none' }}>
      <div
        className="absolute inset-0 rounded-lg"
        style={{
          background: `color-mix(in oklab, var(--${room.color}) ${room.kind === 'meeting' ? 8 : 10}%, transparent)`,
          border: `1px ${room.kind === 'meeting' ? 'solid' : 'dashed'} color-mix(in oklab, var(--${room.color}) 45%, transparent)`,
        }}
      />
      <span
        className="absolute top-1.5 left-2 text-[8.5px] font-mono font-bold uppercase tracking-wider px-1.5 py-0.5 rounded bg-panel border border-line whitespace-nowrap"
        style={{ color: `var(--${room.color})` }}
      >
        {roomLabel}{room.kind === 'dept' ? ` • ${room.count}` : ''}
      </span>
    </div>
  );
}

function MeetingTable({ x, y, r, active, reason, count }: { x: number; y: number; r: number; active: boolean; reason?: string; count: number }) {
  const { t } = useI18n();
  return (
    <div style={{ position: 'absolute', left: x - r, top: y - r, width: r * 2, height: r * 2, zIndex: 8, pointerEvents: 'none' }}>
      <div className={`absolute inset-0 rounded-full ${active ? 'animate-pulse' : ''}`} style={{ background: 'var(--desk2)', boxShadow: active ? '0 0 0 6px color-mix(in oklab, var(--ac) 25%, transparent)' : '0 2px 0 var(--desk2)' }} />
      <div className="absolute rounded-full" style={{ inset: 4, background: 'var(--desk)' }} />
      <div className="absolute inset-0 flex flex-col items-center justify-center text-center">
        <span className="text-[8px] font-mono font-bold text-ink leading-none">{t('agents.office.meeting', undefined, 'TOPLANTI')}</span>
        {active && <span className="text-[7.5px] font-mono text-ac leading-none mt-0.5">{t('agents.office.people', { n: count }, '{n} kişi')} • {reason || t('agents.honey.deliberation', undefined, 'müzakere')}</span>}
      </div>
    </div>
  );
}

const P = (x: number, y: number, w: number, h: number, c: string, extra: React.CSSProperties = {}) => (
  <div style={{ position: 'absolute', left: x, top: y, width: w, height: h, background: c, ...extra }} />
);

type Look = {
  skin: string;
  hair: string;
  shirt: string;
  shirt2: string;
  pants: string;
  acc?: 'clipboard' | 'glasses' | 'headset' | 'lens' | 'hood' | 'hat';
};

type RoleLook = { look: Look; bars: [number, string][]; roleColor: string; label: string };

function Person({ x, y, look, opacity = 1 }: { x: number; y: number; look: Look; opacity?: number }) {
  const { skin, hair, shirt, shirt2, pants, acc } = look;
  return (
    <div style={{ position: 'absolute', left: x, top: y, width: 36, height: 51, opacity, transition: 'opacity 0.3s, left 0.7s ease-in-out, top 0.7s ease-in-out' }}>
      {/* Gölge */}
      <div style={{ position: 'absolute', left: 1, top: 45, width: 28, height: 6, borderRadius: '50%', background: 'rgba(0,0,0,.18)' }} />

      {/* Şapka veya Saç */}
      {acc === 'hat' ? (
        <>
          {P(4, 0, 22, 7, '#e0b34d')}
          {P(1, 6, 28, 3, '#c99a34')}
        </>
      ) : (
        <>
          {P(6, 2, 18, 7, hair)}
          {P(4, 6, 3, 7, hair)}
          {P(23, 6, 3, 7, hair)}
        </>
      )}

      {/* Yüz ve Gözler */}
      {P(7, 9, 16, 10, skin)}
      {P(10, 13, 3, 3, '#242830')}
      {P(17, 13, 3, 3, '#242830')}

      {/* Gövde ve Giysi */}
      {P(5, 19, 20, 14, shirt)}
      {P(11, 19, 8, 5, shirt2)}

      {/* Kollar ve Eller */}
      {P(1, 20, 4, 12, shirt)}
      {P(25, 20, 4, 12, shirt)}
      {P(1, 31, 4, 4, skin)}
      {P(25, 31, 4, 4, skin)}

      {/* Pantolon ve Ayakkabılar */}
      {P(7, 33, 7, 9, pants)}
      {P(16, 33, 7, 9, pants)}
      {P(6, 42, 8, 3, '#20242c')}
      {P(16, 42, 8, 3, '#20242c')}

      {/* Özel Aksesuarlar */}
      {acc === 'hood' && P(4, 16, 22, 5, shirt2)}
      {acc === 'glasses' && (
        <>
          {P(9, 12, 5, 4, '#e7ebf1')}
          {P(16, 12, 5, 4, '#e7ebf1')}
          {P(14, 13, 2, 2, '#e7ebf1')}
        </>
      )}
      {acc === 'headset' && (
        <>
          {P(5, 0, 20, 3, '#39414f')}
          {P(2, 3, 4, 7, '#39414f')}
          {P(24, 3, 4, 7, '#39414f')}
        </>
      )}
      {acc === 'clipboard' && (
        <>
          {P(24, 22, 10, 13, '#f2f3f5', { border: '1px solid #aab2bf' })}
          {P(26, 25, 6, 2, '#aab2bf')}
          {P(26, 29, 6, 2, '#aab2bf')}
        </>
      )}
      {acc === 'lens' && (
        <>
          <div
            style={{
              position: 'absolute',
              left: 24,
              top: 21,
              width: 11,
              height: 11,
              border: '2px solid #d6dbe3',
              borderRadius: '50%',
              background: 'rgba(150,180,215,.32)',
            }}
          />
          {P(33, 31, 3, 5, '#d6dbe3')}
        </>
      )}
    </div>
  );
}

function Desk({ x, y, bars }: { x: number; y: number; bars: [number, string][] }) {
  return (
    <div style={{ position: 'absolute', left: x, top: y, width: DESK_W, height: 40 }}>
      {/* Koltuk Arkalığı */}
      {P(50, -16, 40, 22, 'var(--chair)', { borderRadius: '7px 7px 0 0' })}
      {/* Masa Yüzeyi ve Kenarı */}
      {P(0, 26, DESK_W, 12, 'var(--desk2)')}
      {P(0, 18, DESK_W, 9, 'var(--desk)')}
      {P(0, 18, DESK_W, 2, 'rgba(255,255,255,.22)')}
      {/* Monitör ve Ekran */}
      {P(0, -2, 46, 17, 'var(--bez)', { borderRadius: 3 })}
      {P(3, 1, 40, 11, 'var(--scr)')}
      {bars.map(([w, c], i) => (
        <React.Fragment key={i}>{P(5, 3 + i * 3, w, 2, c)}</React.Fragment>
      ))}
      {/* Monitör Ayağı, Klavye ve Kahve Kupası */}
      {P(19, 15, 8, 3, 'var(--bez)')}
      {P(54, 20, 34, 5, 'var(--kbd)', { borderRadius: 2 })}
      {P(100, 17, 9, 8, '#8f9aa8')}
      {P(109, 19, 3, 4, '#8f9aa8')}
    </div>
  );
}

/** PM'in yuvarlak köşeli toplantı tipi masası */
function PmDesk({ x, y }: { x: number; y: number }) {
  return (
    <div style={{ position: 'absolute', left: x, top: y, width: DESK_W, height: 40 }}>
      {P(50, -16, 40, 22, 'var(--chair)', { borderRadius: '7px 7px 0 0' })}
      {P(0, 16, DESK_W, 22, 'var(--desk)', { borderRadius: '12px' })}
      {P(0, 26, DESK_W, 12, 'var(--desk2)', { borderRadius: '0 0 12px 12px' })}
      {P(20, 10, 30, 2, '#fff')}
      {P(100, 17, 9, 8, '#8f9aa8')}
      {P(109, 19, 3, 4, '#8f9aa8')}
    </div>
  );
}

const ROLE_LOOKS: Record<string, RoleLook> = {
  PM: {
    look: { skin: '#f1c5a7', hair: '#382b24', shirt: '#556274', shirt2: '#3f4957', pants: '#283040', acc: 'clipboard' },
    bars: [],
    roleColor: '#556274',
    label: 'PM',
  },
  PO: {
    look: { skin: '#eec2a0', hair: '#3a2416', shirt: '#a855f7', shirt2: '#7e22ce', pants: '#241a38', acc: 'glasses' },
    bars: [[32, '#a855f7'], [26, '#4fbe89'], [20, '#e0a83c']],
    roleColor: '#a855f7',
    label: 'PO',
  },
  ARCHITECT: {
    look: { skin: '#e2ab83', hair: '#3a2d24', shirt: '#2f9b92', shirt2: '#206e67', pants: '#2b3445', acc: 'glasses' },
    bars: [[32, '#4cc9bc'], [26, '#eef1f7'], [20, '#4cc9bc']],
    roleColor: '#2f9b92',
    label: 'ARCHITECT',
  },
  BACKEND_DEV: {
    look: { skin: '#f4cbb0', hair: '#1c1f26', shirt: '#5b6ee0', shirt2: '#4150b0', pants: '#1a1f2b', acc: 'hood' },
    bars: [[34, '#8e9bfb'], [28, '#4fbe89'], [22, '#ea6275']],
    roleColor: '#5b6ee0',
    label: 'BACKEND_DEV',
  },
  DESIGNER: {
    look: { skin: '#f0c4a4', hair: '#7a2f5a', shirt: '#b45bd6', shirt2: '#8a3fad', pants: '#2a2236', acc: 'glasses' },
    bars: [[34, '#b45bd6'], [26, '#59a9e8'], [30, '#e0a83c']],
    roleColor: '#b45bd6',
    label: 'DESIGNER',
  },
  FRONTEND_DEV: {
    look: { skin: '#e9b593', hair: '#5b3e2b', shirt: '#d2705f', shirt2: '#a44d3f', pants: '#293241', acc: 'hood' },
    bars: [[36, '#ea6275'], [24, '#e0a83c'], [30, '#8e9bfb']],
    roleColor: '#d2705f',
    label: 'FRONTEND_DEV',
  },
  SCM: {
    look: { skin: '#e5b694', hair: '#1e293b', shirt: '#ec4899', shirt2: '#be185d', pants: '#1e1b2e', acc: 'hood' },
    bars: [[28, '#ec4899'], [32, '#59a9e8'], [18, '#4fbe89']],
    roleColor: '#ec4899',
    label: 'SCM',
  },
  DEVOPS: {
    look: { skin: '#e7b695', hair: '#20242e', shirt: '#d3a03f', shirt2: '#a67b28', pants: '#1b2230', acc: 'hat' },
    bars: [[30, '#59a9e8'], [22, '#4fbe89'], [28, '#e0a83c']],
    roleColor: '#d3a03f',
    label: 'DEVOPS',
  },
  QA: {
    look: { skin: '#f2c8a9', hair: '#2a221f', shirt: '#8a6bd1', shirt2: '#684ca8', pants: '#232936', acc: 'lens' },
    bars: [[28, '#4fbe89'], [30, '#4fbe89'], [18, '#ea6275']],
    roleColor: '#8a6bd1',
    label: 'QA',
  },
  E2E_TESTER: {
    look: { skin: '#e6b998', hair: '#40322c', shirt: '#7f9a45', shirt2: '#5f7530', pants: '#2b3342', acc: 'headset' },
    bars: [[32, '#e0a83c'], [26, '#4fbe89'], [22, '#59a9e8']],
    roleColor: '#7f9a45',
    label: 'E2E_TESTER',
  },
  REPORTER: {
    look: { skin: '#eec19e', hair: '#172554', shirt: '#10b981', shirt2: '#047857', pants: '#0f172a', acc: 'clipboard' },
    bars: [[34, '#10b981'], [28, '#59a9e8'], [22, '#e0a83c']],
    roleColor: '#10b981',
    label: 'REPORTER',
  },
  DOCUMENTOR: {
    look: { skin: '#f3c7a8', hair: '#451a03', shirt: '#f59e0b', shirt2: '#b45309', pants: '#292524', acc: 'glasses' },
    bars: [[30, '#f59e0b'], [24, '#4fbe89'], [28, '#8e9bfb']],
    roleColor: '#f59e0b',
    label: 'DOCUMENTOR',
  },
};

/** Kapsayıcıya sığdırmak için ölçek (genişlik ve yükseklik) */
function useFitScale(baseW: number, baseH: number) {
  const ref = useRef<HTMLDivElement>(null);
  const [scale, setScale] = useState(1);
  useLayoutEffect(() => {
    const el = ref.current?.parentElement;
    if (!el) return;
    const update = () => {
      const w = el.clientWidth - 8, h = el.clientHeight - 8;
      const s = Math.min(1, w > 0 ? w / baseW : 1, h > 0 ? h / baseH : 1);
      setScale(Number.isFinite(s) && s > 0 ? s : 1);
    };
    update();
    const ro = new ResizeObserver(update);
    ro.observe(el);
    return () => ro.disconnect();
  }, [baseW, baseH]);
  return { ref, scale };
}

export const AgentOffice: React.FC<AgentOfficeProps> = ({ agents, onSelectAgent, selectedAgentId, gathering }) => {
  const { t } = useI18n();
  // Kayıtlı roller (sabit sırada) + özel ajanlar; her biri departmanına göre odaya yerleşir
  const entries = useMemo(() => {
    const known = Object.keys(ROLE_LOOKS);
    const knownSet = new Set(known);
    const custom = agents.filter(a => !knownSet.has(a.id) && !knownSet.has(a.role));
    const list: { key: string; conf: RoleLook; deptId: DepartmentDef['id'] }[] = [
      ...known.map(k => ({ key: k, conf: ROLE_LOOKS[k], deptId: departmentOf(k).id })),
      ...custom.map(a => ({ key: a.id, conf: customConf(a), deptId: departmentOf(a.role || a.id).id })),
    ];
    return list;
  }, [agents]);

  const layout = useMemo(() => computeLayout(entries.map(e => ({ key: e.key, deptId: e.deptId }))), [entries]);
  // Tıklanan baloncuk kapanır; aynı ajan yeni bir şey söyleyince yeniden görünür
  const [dismissed, setDismissed] = useState<Record<string, string>>({});
  const { ref, scale } = useFitScale(layout.width, layout.height);

  const participants = gathering?.active ? gathering.participants : [];
  const seatFor = (id: string): [number, number] | null => {
    const idx = participants.indexOf(id);
    if (idx < 0) return null;
    const ang = (idx / Math.max(1, participants.length)) * Math.PI * 2 - Math.PI / 2;
    const rr = layout.meeting.r + 24;
    return [Math.round(layout.meeting.x + Math.cos(ang) * rr - 18), Math.round(layout.meeting.y + Math.sin(ang) * rr - 34)];
  };
  const agentMap = useMemo(() => {
    const map = new Map<string, Agent>();
    agents.forEach(a => {
      map.set(a.id, a);
      if (a.role) map.set(a.role, a);
    });
    return map;
  }, [agents]);

  return (
    <div ref={ref} className="select-none" style={{ width: layout.width * scale, height: layout.height * scale }}>
      <div
        className="relative rounded-card overflow-hidden border border-line shadow-panel"
        style={{
          width: layout.width,
          height: layout.height,
          transform: `scale(${scale})`,
          transformOrigin: 'top left',
          background: 'repeating-linear-gradient(45deg, var(--flr) 0, var(--flr) 46px, var(--flr2) 46px, var(--flr2) 48px)',
        }}
      >
        {/* Üst Duvar (Wall) */}
        <div
          className="absolute left-0 top-0 w-full border-b border-line2 flex items-center px-4"
          style={{ height: WALL_H, background: 'var(--wall)' }}
        >
          {/* Beyaz Tahta (Whiteboard) */}
          <div
            className="absolute top-3 rounded-sm border shadow-sm flex flex-col justify-between p-2"
            style={{ left: 36, width: 140, height: 50, background: 'var(--board)', borderColor: 'var(--frame)' }}
          >
            <div className="flex items-center gap-1">
              <span className="w-2 h-2 rounded-full bg-ac" />
              <span className="w-2 h-2 rounded-full bg-ok" />
              <span className="w-2 h-2 rounded-full bg-warn" />
            </div>
            <div className="space-y-1">
              <div className="h-1 bg-line dark:bg-line2 rounded w-4/5" />
              <div className="h-1 bg-ac rounded w-1/2" />
            </div>
          </div>

          {/* Ofis Penceresi (Window) */}
          <div
            className="absolute top-2 rounded-md border-2 border-line2 shadow-inner overflow-hidden flex"
            style={{ left: 240, width: 100, height: 54, background: '#84c5f4' }}
          >
            <div className="w-1/2 h-full border-r border-line/50 relative">
              <div className="absolute top-2 left-2 w-8 h-4 rounded-full bg-panel/70 filter blur-[1px]" />
            </div>
            <div className="w-1/2 h-full relative">
              <div className="absolute top-4 left-3 w-6 h-3 rounded-full bg-panel/70 filter blur-[1px]" />
            </div>
          </div>

          {/* Büyük Kod Ekranı (Big Code Screen) */}
          <div
            className="absolute top-3 rounded border border-line2 shadow-md p-2 flex flex-col justify-between font-mono text-[8px]"
            style={{ left: 420, width: 130, height: 48, background: '#12161f' }}
          >
            <div className="text-ok font-bold flex items-center justify-between">
              <span>A2A_MESH.v2</span>
              <span className="w-1.5 h-1.5 rounded-full bg-ok animate-pulse" />
            </div>
            <div className="space-y-0.5 text-ink3">
              <p className="truncate text-ac">const pipeline = new Orchestrator();</p>
              <p className="truncate text-warn">await pipeline.deliberate();</p>
            </div>
          </div>

          {/* Ofis Saati (Clock) */}
          <div
            className="absolute top-4 w-9 h-9 rounded-full border-2 border-line2 flex items-center justify-center shadow-sm"
            style={{ left: 630, background: 'var(--board)' }}
          >
            <div className="w-0.5 h-3 bg-sunk rounded-full" />
            <div className="w-2.5 h-0.5 bg-line2 rounded-full absolute" style={{ transform: 'translateX(3px)' }} />
            <div className="w-1.5 h-1.5 rounded-full bg-err absolute" />
          </div>

          {/* Sunucu Kabini (Server Rack) */}
          <div
            className="absolute top-2 rounded border border-line2 shadow-md p-1.5 flex flex-col justify-between"
            style={{ left: 740, width: 90, height: 54, background: '#171c26' }}
          >
            {[1, 2, 3].map(i => (
              <div key={i} className="flex items-center justify-between bg-panel px-1 py-0.5 rounded text-[7px] font-mono">
                <span className="text-ink3">NODE_{i}</span>
                <div className="flex gap-1">
                  <span className="w-1 h-1 rounded-full bg-ok animate-ping" />
                  <span className="w-1 h-1 rounded-full bg-ac" />
                </div>
              </div>
            ))}
          </div>

          {/* Sprint / Sticky Board */}
          <div
            className="absolute top-3 rounded border shadow-sm p-1.5 flex flex-wrap gap-1 content-start"
            style={{ left: 910, width: 140, height: 50, background: 'var(--board)', borderColor: 'var(--frame)' }}
          >
            <div className="w-6 h-6 rounded-sm bg-warnd dark:bg-warnd/60 border border-warn/50 shadow-xs" />
            <div className="w-6 h-6 rounded-sm bg-infod dark:bg-infod/60 border border-info/50 shadow-xs" />
            <div className="w-6 h-6 rounded-sm bg-acd dark:bg-acd/60 border border-ac/50 shadow-xs" />
            <div className="w-6 h-6 rounded-sm bg-okd dark:bg-okd/60 border border-ok/50 shadow-xs" />
          </div>

          {/* Kat planı rozeti */}
          <div className="absolute top-5 right-4 text-[9px] font-mono px-2 py-1 rounded bg-panel border border-line text-ink3">
            {t('agents.office.rooms', { n: layout.rooms.filter(r => r.kind === 'dept').length }, '{n} oda')} • {t('agents.office.desks', { n: layout.slots.size }, '{n} masa')}
          </div>
        </div>

        {/* Departman odaları ve toplantı odası */}
        {layout.rooms.map(room => <RoomBox key={room.id} room={room} />)}

        {/* Canlı Akış Çizgileri (SVG Flow Connectors) — masa konumlarından türetilir */}
        <svg className="absolute inset-0 w-full h-full pointer-events-none" style={{ zIndex: 10 }}>
          <defs>
            <style>
              {`
                @keyframes dash { to { stroke-dashoffset: -30; } }
                .flow-line { stroke-dasharray: 6, 6; animation: dash 1.2s linear infinite; }
              `}
            </style>
          </defs>
          {FLOWS.map(([from, to, color]) => {
            const a = layout.slots.get(from), b = layout.slots.get(to);
            if (!a || !b) return null;
            return <path key={`${from}-${to}`} d={connectorPath(a, b, layout)} fill="none" stroke={`var(--${color})`} strokeWidth="2.5" strokeOpacity={0.85} className="flow-line" />;
          })}
        </svg>

        {/* Yuvarlak toplantı masası */}
        <MeetingTable x={layout.meeting.x} y={layout.meeting.y} r={layout.meeting.r} active={!!gathering?.active} reason={gathering?.reason} count={participants.length} />

        {/* Masalar ve Karakterler */}
        {entries.map(({ key: roleKey, conf }) => {
          const slot = layout.slots.get(roleKey);
          if (!slot) return null;
          const agent = agentMap.get(roleKey) || {
            id: roleKey,
            name: conf.label,
            role: roleKey as AgentRole,
            status: 'IDLE',
            active_file: '',
            tokens_in: 0,
            tokens_out: 0,
            total_tokens: 0,
            last_action: 'READY',
            last_seen: ''
          };

          const isWorking = agent.status === 'WORKING';
          const isBugFix = agent.status === 'BUG_FIX';
          const isError = agent.status === 'ERROR';
          const isIdle = agent.status === 'IDLE';
          const seat = seatFor(agent.id) || seatFor(roleKey);
          const pos: [number, number] = seat || slot.char;
          const bubbleText = isBugFix
            ? `REPORT_BUG: ${t('agents.office.reviewing', undefined, 'İncelemede')}`
            : isWorking && agent.current_dialogue
            ? `“${agent.current_dialogue.slice(0, 48)}${agent.current_dialogue.length > 48 ? '…' : ''}”`
            : agent.active_file
            ? agent.active_file.split('/').pop() || agent.active_file
            : isWorking
            ? t('agents.office.processing', undefined, 'İşleniyor...')
            : t('agents.office.ready', undefined, 'Hazır');

          return (
            <div key={roleKey} className="absolute" style={{ left: 0, top: 0, zIndex: 20 }}>
              {roleKey === 'PM' ? <PmDesk x={slot.desk[0]} y={slot.desk[1]} /> : <Desk x={slot.desk[0]} y={slot.desk[1]} bars={conf.bars} />}

              {/* Karakter (tıkla → zaman çizelgesi); toplantıda masaya yürür */}
              <div
                role="button"
                title={`${conf.label}: ${t('agents.office.openTimeline', undefined, 'zaman çizelgesini aç')}`}
                onClick={() => onSelectAgent?.(agent.id || roleKey)}
                style={{
                  position: 'absolute', left: pos[0] - 4, top: pos[1] - 4, width: 44, height: 59,
                  cursor: 'pointer', zIndex: 25, borderRadius: 8, transition: 'left 0.7s ease-in-out, top 0.7s ease-in-out',
                  boxShadow: selectedAgentId === (agent.id || roleKey) ? '0 0 0 2px var(--ac), 0 0 0 5px color-mix(in oklab, var(--ac) 25%, transparent)' : 'none',
                }}
              />
              <Person x={pos[0]} y={pos[1]} look={conf.look} opacity={isIdle && !seat ? 0.82 : 1} />

              {/* Ajan İsim Rozeti (masanın altında, ortalı) */}
              <div
                style={{ position: 'absolute', left: slot.desk[0] + DESK_W / 2, top: slot.desk[1] + 44, transform: 'translateX(-50%)' }}
                className="flex items-center gap-1.5 px-2 py-0.5 rounded-full bg-[#1c222c] border border-line2 shadow-sm font-mono text-[9.5px] text-[#f3f5f8] whitespace-nowrap z-30"
              >
                <span className="w-1.5 h-1.5 rounded-xs shrink-0" style={{ background: conf.roleColor }} />
                <span className="font-bold tracking-wide">{conf.label}</span>
                {isWorking && <span className="w-1.5 h-1.5 rounded-full bg-ok animate-ping shrink-0" />}
                {isBugFix && <span className="w-1.5 h-1.5 rounded-full bg-err animate-ping shrink-0" />}
              </div>

              {/* Canlı Konuşma / Dosya Baloncuğu — karakterin üstünde ortalı, masa hücresini aşmaz */}
              {(isWorking || isBugFix || isError || agent.active_file) && dismissed[roleKey] !== bubbleText && (
                <div
                  role="button"
                  onClick={() => setDismissed(prev => ({ ...prev, [roleKey]: bubbleText }))}
                  style={{
                    position: 'absolute',
                    left: pos[0] + 18,
                    top: pos[1] - 30,
                    transform: 'translateX(-50%)',
                    maxWidth: 150,
                    transition: 'left 0.7s ease-in-out, top 0.7s ease-in-out',
                  }}
                  className="flex items-center gap-1.5 px-2 py-0.5 rounded-card bg-panel border border-line shadow-panel font-mono text-[8.5px] text-ink z-40 whitespace-nowrap cursor-pointer hover:border-ac/50"
                  title={`${agent.current_dialogue || agent.active_file || ''} — ${t('agents.office.clickClose', undefined, 'kapatmak için tıkla')}`}
                >
                  <span
                    className={`w-1.5 h-1.5 rounded-full shrink-0 ${
                      isWorking ? 'bg-ok animate-pulse' : isBugFix ? 'bg-err animate-pulse' : isError ? 'bg-err' : 'bg-ac'
                    }`}
                  />
                  <span className="font-semibold truncate">{bubbleText}</span>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
};
