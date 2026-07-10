/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        cyber: {
          bg: '#0b0b0c',
          surface: '#120F17',
          mute: '#171939',
          green: '#A7EF9E',
          violet: '#7C3AED',
          accent: '#0891B2',
          paper: '#E8DCC8',
          'paper-dark': '#3D3226',
          ink: '#2C1810',
        },
      },
      fontFamily: {
        mono: ['JetBrains Mono', 'monospace'],
        display: ['Orbitron', 'sans-serif'],
        character: ['Noto Sans SC', 'Microsoft YaHei', 'PingFang SC', 'system-ui', 'sans-serif'],
      },
    },
  },
  plugins: [],
};
