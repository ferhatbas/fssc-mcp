/**
 * Tek API tabanı.
 * - Üretimde (dashboard/dist FastAPI tarafından servis edilir) same-origin: API_BASE = ''.
 * - Vite dev sunucusunda /api ve /ws proxy'lenir (vite.config.ts), yine same-origin çalışır.
 * - Farklı bir sunucuya bağlanmak için `VITE_API_BASE` (örn. http://127.0.0.1:8099) ve
 *   isteğe bağlı `VITE_WS_URL` tanımlanabilir (.env.local).
 */
const rawBase = (import.meta.env.VITE_API_BASE ?? '').trim();
export const API_BASE: string = rawBase.replace(/\/+$/, '');

/** Göreli bir yolu (örn. '/api/state' veya '/api/projects/p1/screenshots/x.png') tam URL'ye çevirir. */
export function api(path: string): string {
  if (/^https?:\/\//i.test(path)) return path;
  const normalized = path.startsWith('/') ? path : `/${path}`;
  return `${API_BASE}${normalized}`;
}

/** WebSocket telemetri adresi. */
export function wsUrl(): string {
  const explicit = (import.meta.env.VITE_WS_URL ?? '').trim();
  if (explicit) return explicit;
  if (API_BASE) {
    return API_BASE.replace(/^http/i, 'ws') + '/ws/telemetry';
  }
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  return `${protocol}//${window.location.host}/ws/telemetry`;
}

/** Playwright E2E için varsayılan hedef uygulama adresi (gözlemci sunucunun kendisi). */
export const DEFAULT_TARGET_URL: string = API_BASE || (typeof window !== 'undefined' ? window.location.origin : 'http://127.0.0.1:8099');

/** Bağlantı rozetinde gösterilecek host:port etiketi. */
export function wsHostLabel(): string {
  try {
    const u = new URL(wsUrl(), window.location.href);
    return u.port ? `${u.hostname}:${u.port}` : u.host;
  } catch {
    return window.location.host;
  }
}
