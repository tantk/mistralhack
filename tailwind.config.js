/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        'bg-primary': '#0a1a1b',
        'bg-surface': '#0f2223',
        'bg-elevated': '#132d2e',
        'bg-card': 'rgba(15, 34, 35, 0.85)',
        accent: '#06f1f9',
        'accent-muted': 'rgba(6, 241, 249, 0.15)',
        'accent-subtle': 'rgba(6, 241, 249, 0.08)',
        border: 'rgba(6, 241, 249, 0.12)',
        'border-strong': 'rgba(6, 241, 249, 0.25)',
        danger: '#FF003C',
        warning: '#FFD600',
        success: '#22c55e',
        // Legacy aliases for untouched components
        'neon-cyan': '#06f1f9',
        'neon-magenta': '#FF003C',
        'neon-yellow': '#FFD600',
        surface: 'rgba(15, 34, 35, 0.85)',
        'glass-border': 'rgba(6, 241, 249, 0.12)',
        void: '#0a1a1b',
      },
      fontFamily: {
        display: ['Space Grotesk', 'system-ui', 'sans-serif'],
        hud: ['Space Grotesk', 'system-ui', 'sans-serif'],
        code: ['Fira Code', 'Courier New', 'monospace'],
        mono: ['Fira Code', 'Courier New', 'monospace'],
      },
      boxShadow: {
        'glow-cyan': '0 4px 24px rgba(6,241,249,0.12), 0 0 48px rgba(6,241,249,0.06)',
        'glow-magenta': '0 4px 24px rgba(255,0,60,0.12), 0 0 48px rgba(255,0,60,0.06)',
        'glow-yellow': '0 4px 24px rgba(255,214,0,0.12), 0 0 48px rgba(255,214,0,0.06)',
      },
      animation: {
        blink: 'blink 1s step-end infinite',
        'pulse-soft': 'pulse-soft 2.5s ease-in-out infinite',
        'glow-pulse': 'glow-pulse 2.5s ease-in-out infinite',
      },
      keyframes: {
        blink: {
          '0%, 100%': { opacity: '1' },
          '50%': { opacity: '0' },
        },
        'pulse-soft': {
          '0%, 100%': { opacity: '0.6' },
          '50%': { opacity: '1' },
        },
        'glow-pulse': {
          '0%, 100%': { boxShadow: '0 0 0 0 rgba(6,241,249,0)' },
          '50%': { boxShadow: '0 0 8px 3px rgba(6,241,249,0.15)' },
        },
      },
    },
  },
  plugins: [],
}
