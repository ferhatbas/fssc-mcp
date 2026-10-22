import { Edge, MarkerType, Node } from '@xyflow/react';
import { Agent, TelemetryEvent } from '../types/telemetry';
import { PIPELINE_EDGES } from '../components/AgentMesh';

/**
 * Petek (honeycomb) yerleşimi.
 * Düz-üst (flat-top) altıgenler, eksenel (axial) koordinatlar: q, r.
 * Bir takım altıgeni → ortada toplantı altıgeni, çevresinde departman altıgenleri (daire üzerinde eşit açıyla)
 * → içinde ajan altıgenleri (merkezden dışa spiral). Tüm iç altıgenler kapsayanın iç yarıçapı içinde kalır.
 */

export interface TeamDepartment {
  id: string;
  label: string;
  color: 'ac' | 'ok' | 'warn' | 'info' | 'err' | string;
  agent_ids: string[];
}

export interface Team {
  id: string;
  name: string;
  project_id: string;
  partners: string[];
  departments: TeamDepartment[];
  meeting_room?: { label: string };
  read_only?: boolean;
}

export interface Gathering {
  active: boolean;
  participants: string[];
  reason?: string;
}

export interface HoneycombOptions {
  /** Ajan altıgeni yarıçapı (px) */
  size: number;
  gathering: Gathering;
  /** Son olaylardan türetilecek ek kenarlar */
  recentEvents?: TelemetryEvent[];
  /** Kenar etiketini çevirir (isteğe bağlı) */
  edgeLabel?: (label: string) => string;
}

const SQRT3 = Math.sqrt(3);
/** Düz-üst altıgende iç yarıçap / dış yarıçap oranı */
const INRADIUS = SQRT3 / 2;

/** Eksenel → piksel (düz-üst altıgen) */
export function axialToPixel(q: number, r: number, size: number): { x: number; y: number } {
  return { x: size * 1.5 * q, y: size * SQRT3 * (r + q / 2) };
}

/** n hücreyi merkezden dışa doğru halkalar hâlinde döşer (spiral). Her halka (0, -halka) köşesinden başlar. */
export function spiralRing(n: number): { q: number; r: number }[] {
  const out: { q: number; r: number }[] = [];
  if (n <= 0) return out;
  out.push({ q: 0, r: 0 });
  const dirs = [[1, 0], [0, 1], [-1, 1], [-1, 0], [0, -1], [1, -1]];
  let ring = 1;
  while (out.length < n) {
    let q = 0, r = -ring; // halkanın başlangıç köşesi (dirs[4] yönünde)
    for (let side = 0; side < 6 && out.length < n; side++) {
      for (let step = 0; step < ring && out.length < n; step++) {
        out.push({ q, r });
        q += dirs[side][0];
        r += dirs[side][1];
      }
    }
    ring += 1;
  }
  return out;
}

export const HEX_CLIP = 'polygon(25% 0, 75% 0, 100% 50%, 75% 100%, 25% 100%, 0 50%)';

/** Düz-üst altıgen düğümü: merkez (cx, cy) ve dış yarıçap R → React Flow konum/boyut */
function hexBox(cx: number, cy: number, R: number) {
  // width/height üst düzeyde: kontrolsüz düğümlerde React Flow ölçümü kullanıcı nesnesine yazmaz; MiniMap bunlara bakar
  return { position: { x: cx - R, y: cy - R * INRADIUS }, width: R * 2, height: R * SQRT3, style: { width: R * 2, height: R * SQRT3 } };
}

/**
 * Takımlardan React Flow düğüm/kenar listesini üretir.
 * Düğüm türleri: teamHex (grup), deptHex (dekoratif grup, takımın çocuğu), meetingHex (takımın çocuğu),
 * agentHex (takımın çocuğu; departman konumu + hücre konumu; toplanma sırasında toplantı altıgenine kayar).
 */
export function buildHoneycomb(teams: Team[], agents: Agent[], opts: HoneycombOptions): { nodes: Node[]; edges: Edge[] } {
  const { size, gathering } = opts;
  const agentsById = new Map(agents.map(a => [a.id, a]));
  const nodes: Node[] = [];
  const agentNodeIds = new Set<string>();
  const teamGap = size * 2;
  const cellPitch = size * 1.12; // ajan altıgenleri arasında ince boşluk (kenarlıklar üst üste binmesin)
  const meetingR = size * 2.8;  // 5 katılımcıya kadar koltuk rahat sığar
  const labelRoom = size * 0.6; // departman etiketi için üstte pay
  let teamX = 0;

  for (const team of teams) {
    const depts = team.departments.filter(d => d.agent_ids.length > 0 || !team.read_only);

    // Departman kümeleri: hücreler spiral, küme merkezi = hücrelerin ağırlık merkezi;
    // departman yarıçapı tüm ajan altıgenlerini (etiket payıyla) iç yarıçap içinde tutar.
    const clusters = depts.map(d => {
      const n = Math.max(1, d.agent_ids.length);
      const raw = spiralRing(n).map(c => axialToPixel(c.q, c.r, cellPitch));
      const cx = raw.reduce((s, p) => s + p.x, 0) / raw.length, cy = raw.reduce((s, p) => s + p.y, 0) / raw.length;
      const pts = raw.map(p => ({ x: p.x - cx, y: p.y - cy }));
      const reach = Math.max(...pts.map(p => Math.hypot(p.x, p.y)));
      const R = Math.max(size * 2.1, (reach + size * 1.02) / INRADIUS + labelRoom);
      return { dept: d, pts, R };
    });
    const maxDeptR = clusters.length ? Math.max(...clusters.map(c => c.R)) : size * 2;

    // Departmanlar toplantı altıgeni etrafında dairede; komşular ve toplantı odası çakışmaz
    const n = clusters.length;
    const gap = size * 0.7;
    const minByNeighbors = n > 1 ? (2 * maxDeptR + gap) / (2 * Math.sin(Math.PI / n)) : 0;
    const orbit = Math.max(meetingR + maxDeptR + gap, minByNeighbors);
    const centers = clusters.map((_, i) => {
      const ang = (i / Math.max(1, n)) * Math.PI * 2 - Math.PI / 2; // ilk departman üstte
      return { x: Math.cos(ang) * orbit, y: Math.sin(ang) * orbit };
    });

    // Takım sınırları (takım-yerel koordinat: toplantı odası merkezde)
    const extent = n ? orbit + maxDeptR : meetingR;
    const pad = size * 1.3; // takım etiketi + kesik köşeler için pay
    const half = extent + pad;
    const teamW = half * 2, teamH = half * 2;
    const off = half; // yerel (0,0) → takım kutusunun merkezi

    nodes.push({
      id: team.id,
      type: 'teamHex',
      position: { x: teamX, y: 0 },
      data: { label: team.name, readOnly: !!team.read_only, projectId: team.project_id },
      width: teamW,
      height: teamH,
      style: { width: teamW, height: teamH },
      selectable: false,
      draggable: false,
      zIndex: 0,
    });

    // Toplantı altıgeni
    nodes.push({
      id: `${team.id}:meeting`,
      type: 'meetingHex',
      parentId: team.id,
      ...hexBox(off, off, meetingR),
      data: { label: team.meeting_room?.label || '', active: gathering.active, reason: gathering.reason },
      selectable: false,
      draggable: false,
      zIndex: 1,
    });

    // Departman altıgenleri + ajanlar
    clusters.forEach((c, i) => {
      const center = { x: centers[i].x + off, y: centers[i].y + off };
      nodes.push({
        id: `${team.id}:${c.dept.id}`,
        type: 'deptHex',
        parentId: team.id,
        ...hexBox(center.x, center.y, c.R),
        data: { label: c.dept.label, deptId: c.dept.id, color: c.dept.color, count: c.dept.agent_ids.length },
        selectable: false,
        draggable: false,
        zIndex: 1,
      });

      c.dept.agent_ids.forEach((aid, k) => {
        const p = c.pts[k] || c.pts[0];
        const agent = agentsById.get(aid);
        const nodeId = team.read_only ? `${team.id}:${aid}` : aid;
        agentNodeIds.add(nodeId);
        // Etiket üstte olduğundan ajan kümesini bir miktar aşağı kaydır
        let cx = center.x + p.x, cy = center.y + p.y + labelRoom * 0.5;
        const gathered = gathering.active && !team.read_only && gathering.participants.includes(aid);
        if (gathered) {
          // Toplantı altıgeninde koltuk düzeni (katılımcı sırasına göre daire, iç yarıçap içinde)
          const idx = gathering.participants.indexOf(aid);
          const m = Math.max(1, gathering.participants.length);
          const ang = (idx / m) * Math.PI * 2 - Math.PI / 2;
          const rr = m === 1 ? 0 : Math.min(size * 1.75, meetingR * INRADIUS - size * 1.05);
          cx = off + Math.cos(ang) * rr;
          cy = off + Math.sin(ang) * rr;
        }
        nodes.push({
          id: nodeId,
          type: 'agentHex',
          parentId: team.id,
          extent: 'parent',
          ...hexBox(cx, cy, size),
          data: { agentId: aid, agent, color: c.dept.color, readOnly: !!team.read_only, gathered },
          draggable: !team.read_only,
          zIndex: 2,
        });
      });
    });

    teamX += teamW + teamGap;
  }

  // Kenarlar: sabit pipeline kenarları (etiketli) + son olaylardan türetilen kenarlar (etiketsiz, ince)
  const edges: Edge[] = [];
  const edgeKeys = new Set<string>();
  const addEdge = (id: string, source: string, target: string, label: string, opts2: { color?: string; dashed?: boolean; animated?: boolean; thin?: boolean } = {}) => {
    if (!agentNodeIds.has(source) || !agentNodeIds.has(target) || source === target) return;
    const key = `${source}->${target}`;
    if (edgeKeys.has(key)) return;
    edgeKeys.add(key);
    const stroke = opts2.color ? `var(--${opts2.color})` : 'var(--line2)';
    edges.push({
      id,
      source,
      target,
      sourceHandle: 's',
      targetHandle: 't',
      label: label || undefined,
      type: 'straight',
      animated: !!opts2.animated,
      style: { stroke, strokeWidth: opts2.animated ? 2.5 : opts2.thin ? 1 : 1.5, opacity: opts2.thin ? 0.6 : 1, ...(opts2.dashed ? { strokeDasharray: '4,4' } : {}) },
      labelStyle: { fill: 'var(--ink3)', fontSize: 8, fontFamily: 'monospace' },
      labelBgStyle: { fill: 'var(--panel)', fillOpacity: 0.9 },
      labelBgPadding: [3, 2],
      markerEnd: { type: MarkerType.ArrowClosed, color: stroke, width: 12, height: 12 },
      zIndex: 3,
    });
  };
  for (const spec of PIPELINE_EDGES) {
    addEdge(`hex-${spec.id}`, spec.source, spec.target, (opts.edgeLabel || ((l: string) => l))(spec.label.replace(/^\d+[ab]?\.\s*/, '')), { color: spec.color, dashed: spec.dashed, animated: spec.alwaysAnimated });
  }
  for (const evt of (opts.recentEvents || []).slice(0, 30)) {
    if (!evt.from_agent || !evt.to_agent || evt.to_agent === 'ALL') continue;
    addEdge(`hex-evt-${evt.from_agent}-${evt.to_agent}`, evt.from_agent, evt.to_agent, '', { dashed: true, thin: true });
  }
  return { nodes, edges };
}
