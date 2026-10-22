import { useEffect, useState } from 'react';
import { api } from '../config';

export interface ServerInfo {
  pid: number;
  mode: string;
  host: string;
  port: number;
  started_at: string;
  uptime_s: number;
  git_head: string;
  code_stale: boolean;
  changed_files: string[];
  hosted_in_claude_session: boolean;
}

/** Çalışan sunucunun kimliği (süreç, kip, kod güncel mi). Dakikada bir yoklanır; sunucu yoksa null kalır. */
export function useServerInfo(intervalMs = 60000): ServerInfo | null {
  const [info, setInfo] = useState<ServerInfo | null>(null);
  useEffect(() => {
    let stop = false;
    const load = async () => {
      try {
        const res = await fetch(api('/api/server/info'));
        if (res.ok && !stop) setInfo(await res.json());
      } catch {
        /* sunucu geçici olarak yanıt vermiyor olabilir; sonraki yoklamada yeniden denenir */
      }
    };
    load();
    const t = setInterval(load, intervalMs);
    return () => { stop = true; clearInterval(t); };
  }, [intervalMs]);
  return info;
}
