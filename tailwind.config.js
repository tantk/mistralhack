/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        void: '#050505',
        'neon-cyan': '#06f1f9',
        'neon-magenta': '#FF003C',
        'neon-yellow': '#FFD600',
        surface: 'rgba(20,25,30,0.65)',
        'glass-border': 'rgba(255,255,255,0.1)',
      },
      fontFamily: {
        display: ['Space Grotesk', 'system-ui', 'sans-serif'],
        hud: ['Rajdhani', 'system-ui', 'sans-serif'],
        code: ['Fira Code', 'Courier New', 'monospace'],
      },
      boxShadow: {
        'glow-cyan': '0 0 20px rgba(6,241,249,0.35), 0 0 60px rgba(6,241,249,0.15)',
        'glow-magenta': '0 0 20px rgba(255,0,60,0.35), 0 0 60px rgba(255,0,60,0.15)',
        'glow-yellow': '0 0 20px rgba(255,214,0,0.35), 0 0 60px rgba(255,214,0,0.15)',
      },
      animation: {
        blink: 'blink 1s step-end infinite',
        'glow-pulse': 'glow-pulse 2.5s ease-in-out infinite',
        scanline: 'scanline 8s linear infinite',
      },
      keyframes: {
        blink: {
          '0%, 100%': { opacity: '1' },
          '50%': { opacity: '0' },
        },
        'glow-pulse': {
          '0%, 100%': { boxShadow: '0 0 0 0 rgba(255,0,60,0)' },
          '50%': { boxShadow: '0 0 8px 3px rgba(255,0,60,0.3)' },
        },
        scanline: {
          '0%': { transform: 'translateY(-100%)' },
          '100%': { transform: 'translateY(100%)' },
        },
      },
    },
  },
  plugins: [],
}
