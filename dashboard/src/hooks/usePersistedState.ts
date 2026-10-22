import { useEffect, useState } from 'react';

/**
 * localStorage'a yazılan küçük UI tercihleri (aktif sekme, görünüm segmenti, accent).
 * Depolama erişimi kısıtlıysa (gizli pencere vb.) sessizce bellek içi çalışır.
 */
export function usePersistedState<T extends string>(key: string, initial: T, allowed?: readonly T[]) {
  const [value, setValue] = useState<T>(() => {
    try {
      const raw = localStorage.getItem(key);
      if (raw !== null && (!allowed || (allowed as readonly string[]).includes(raw))) return raw as T;
    } catch {
      /* depolama yok */
    }
    return initial;
  });

  useEffect(() => {
    try {
      localStorage.setItem(key, value);
    } catch {
      /* depolama yok */
    }
  }, [key, value]);

  return [value, setValue] as const;
}
