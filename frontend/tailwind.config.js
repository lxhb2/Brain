/** @type {import('tailwindcss').Config} */

export default {
  darkMode: "class",
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    container: {
      center: true,
    },
    extend: {
      colors: {
        // 深空墨蓝背景层
        void: {
          DEFAULT: "#0B1020",
          50: "#1A2240",
          100: "#161C36",
          200: "#121831",
          300: "#0F1426",
          400: "#0C1120",
          500: "#0B1020",
          600: "#080C18",
          700: "#060912",
          800: "#04060C",
          900: "#020308",
        },
        // 星光暖白（主文字/默认节点）
        starlight: "#F5F0E1",
        // 青蓝高亮节点
        azure: "#6EA8FE",
        // 琥珀选中节点
        amber: {
          DEFAULT: "#F5A623",
          glow: "#FFC45E",
        },
        // 强链接 cyan
        flux: "#22D3EE",
        // 👎 反馈玫红
        rose: "#F472B6",
        // 次要文字 slate
        dust: "#8B93A7",
        // 玻璃面板
        glass: "rgba(18, 24, 49, 0.55)",
      },
      fontFamily: {
        // 衬线展示体（编辑/知识感）
        display: ['Fraunces', 'ui-serif', 'Georgia', 'serif'],
        // 正文无衬线
        sans: ['"Hanken Grotesk"', 'ui-sans-serif', 'system-ui', 'sans-serif'],
        // 等宽（元数据/OCR 档案感）
        mono: ['"JetBrains Mono"', 'ui-monospace', 'monospace'],
      },
      boxShadow: {
        glow: "0 0 24px rgba(110, 168, 254, 0.25)",
        "glow-amber": "0 0 28px rgba(245, 166, 35, 0.35)",
        "glow-flux": "0 0 18px rgba(34, 211, 238, 0.45)",
        panel: "0 8px 40px rgba(0, 0, 0, 0.45)",
      },
      backgroundImage: {
        'starfield':
          "radial-gradient(ellipse at 50% 0%, rgba(34,211,238,0.06), transparent 55%), radial-gradient(ellipse at 80% 100%, rgba(245,166,35,0.05), transparent 50%), radial-gradient(circle at 0% 60%, rgba(110,168,254,0.05), transparent 45%)",
      },
      animation: {
        'fade-in': 'fadeIn 0.5s ease-out both',
        'fade-up': 'fadeUp 0.5s ease-out both',
        'twinkle': 'twinkle 4s ease-in-out infinite',
        'pulse-slow': 'pulseSlow 3s ease-in-out infinite',
      },
      keyframes: {
        fadeIn: {
          '0%': { opacity: '0' },
          '100%': { opacity: '1' },
        },
        fadeUp: {
          '0%': { opacity: '0', transform: 'translateY(12px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
        twinkle: {
          '0%, 100%': { opacity: '0.55' },
          '50%': { opacity: '1' },
        },
        pulseSlow: {
          '0%, 100%': { opacity: '0.4' },
          '50%': { opacity: '0.9' },
        },
      },
    },
  },
  plugins: [],
};
