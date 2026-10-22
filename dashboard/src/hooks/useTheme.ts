import { useEffect, useState } from 'react';

export type Theme = 'light' | 'dark';
export type Accent = 'indigo' | 'teal' | 'magenta';
export const ACCENTS: Accent[] = ['indigo', 'teal', 'magenta'];

function readAccent(): Accent {
  try {
    const saved = localStorage.getItem('ag_accent') as Accent;
    return ACCENTS.includes(saved) ? saved : 'indigo';
  } catch {
    return 'indigo';
  }
}

export function useTheme() {
  const [theme, setTheme] = useState<Theme>(() => {
    try {
      const saved = localStorage.getItem('ag_theme') as Theme;
      return saved === 'dark' || saved === 'light' ? saved : 'light';
    } catch {
      return 'light';
    }
  });
  const [accent, setAccent] = useState<Accent>(readAccent);

  useEffect(() => {
    if (accent === 'indigo') document.documentElement.removeAttribute('data-accent');
    else document.documentElement.setAttribute('data-accent', accent);
    try {
      localStorage.setItem('ag_accent', accent);
    } catch {
      /* depolama yok */
    }
  }, [accent]);

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme);
    if (theme === 'dark') {
      document.documentElement.classList.add('dark');
    } else {
      document.documentElement.classList.remove('dark');
    }
    try {
      localStorage.setItem('ag_theme', theme);
    } catch {
      /* depolama yok */
    }
  }, [theme]);

  const toggleTheme = () => {
    setTheme(prev => (prev === 'light' ? 'dark' : 'light'));
  };

  return { theme, setTheme, toggleTheme, accent, setAccent };
}
