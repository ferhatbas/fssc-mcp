/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  darkMode: ['class', '[data-theme="dark"]'],
  theme: {
    extend: {
      colors: {
        bg: 'var(--bg)',
        panel: 'var(--panel)',
        panel2: 'var(--panel2)',
        sunk: 'var(--sunk)',
        line: 'var(--line)',
        line2: 'var(--line2)',
        ink: 'var(--ink)',
        ink2: 'var(--ink2)',
        ink3: 'var(--ink3)',
        ok: 'var(--ok)',
        okd: 'var(--okd)',
        warn: 'var(--warn)',
        warnd: 'var(--warnd)',
        err: 'var(--err)',
        errd: 'var(--errd)',
        info: 'var(--info)',
        infod: 'var(--infod)',
        ac: 'var(--ac)',
        acd: 'var(--acd)',
        onac: 'var(--onac)',
      },
      fontFamily: {
        sans: ['Space Grotesk', 'system-ui', 'sans-serif'],
        mono: ['JetBrains Mono', 'monospace'],
      },
      borderRadius: {
        panel: '18px',
        card: '12px',
      },
      boxShadow: {
        panel: 'var(--shadow)',
      },
      animation: {
        'pulse-slow': 'pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite',
        'glow-pulse': 'glow 2s ease-in-out infinite alternate',
      },
      keyframes: {
        glow: {
          '0%': { boxShadow: '0 0 5px rgba(56, 189, 248, 0.2)' },
          '100%': { boxShadow: '0 0 20px rgba(56, 189, 248, 0.6)' },
        }
      }
    },
  },
  plugins: [],
}
