import type { Config } from 'tailwindcss'

export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        background: '#0B0B0E',
        surface: '#141419',
        border: '#26262E',
        accent: '#F97316',
        healthy: '#22C55E',
        degraded: '#F59E0B',
        failed: '#EF4444',
        // Not specified in doc 08's palette — added for basic
        // readability against the dark background/surface tokens.
        text: '#E5E7EB',
        'text-muted': '#9CA3AF',
      },
      fontFamily: {
        heading: ['Mohave', 'system-ui', 'sans-serif'],
        body: ['Inter', 'system-ui', 'sans-serif'],
      },
    },
  },
  plugins: [],
} satisfies Config
