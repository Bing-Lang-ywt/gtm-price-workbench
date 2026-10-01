import type { Config } from "tailwindcss";

/**
 * 设计 Token 全部映射自 globals.css 的 CSS 变量（见 §2.1 / §2.3）。
 * 颜色使用 `rgb(var(--x-rgb) / <alpha-value>)` 通道写法，以支持 bg-success/10 等透明度修饰符；
 * 内联样式 / Recharts 仍用 `var(--x)` 的 hex 形式。
 * 禁止在组件中硬编码颜色——所有色值走 Tailwind token。唯一例外 #fff/#000（遮罩/纯白文字）。
 * 主色 Petrol Teal（纯色，无渐变）。语义色：价跌绿 / 价涨红 / 警告 / 信息蓝。
 */
const config: Config = {
  darkMode: "class",
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
    "./lib/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        bg: "rgb(var(--bg-rgb) / <alpha-value>)",
        surface: "rgb(var(--surface-rgb) / <alpha-value>)",
        "surface-warm": "rgb(var(--surface-warm-rgb) / <alpha-value>)",
        fg: "rgb(var(--fg-rgb) / <alpha-value>)",
        "fg-2": "rgb(var(--fg-2-rgb) / <alpha-value>)",
        muted: "rgb(var(--muted-rgb) / <alpha-value>)",
        meta: "rgb(var(--meta-rgb) / <alpha-value>)",
        border: "rgb(var(--border-rgb) / <alpha-value>)",
        "border-soft": "rgb(var(--border-soft-rgb) / <alpha-value>)",
        accent: {
          DEFAULT: "rgb(var(--accent-rgb) / <alpha-value>)",
          text: "rgb(var(--accent-text-rgb) / <alpha-value>)",
          on: "rgb(var(--accent-on-rgb) / <alpha-value>)",
          hover: "rgb(var(--accent-hover-rgb) / <alpha-value>)",
          active: "rgb(var(--accent-active-rgb) / <alpha-value>)",
          soft: "rgb(var(--accent-soft-rgb) / <alpha-value>)",
        },
        success: "rgb(var(--success-rgb) / <alpha-value>)",
        danger: "rgb(var(--danger-rgb) / <alpha-value>)",
        warn: "rgb(var(--warn-rgb) / <alpha-value>)",
        "warn-strong": "rgb(var(--warn-strong-rgb) / <alpha-value>)",
        info: "rgb(var(--info-rgb) / <alpha-value>)",
        "trend-down": "rgb(var(--trend-down-rgb) / <alpha-value>)",
        "trend-up": "rgb(var(--trend-up-rgb) / <alpha-value>)",
        "sev-critical": "rgb(var(--severity-critical-rgb) / <alpha-value>)",
        "sev-warning": "rgb(var(--severity-warning-rgb) / <alpha-value>)",
        "sev-info": "rgb(var(--severity-info-rgb) / <alpha-value>)",
      },
      fontFamily: {
        sans: ["var(--font-body)"],
        mono: ["var(--font-mono)"],
      },
      borderRadius: {
        sm: "6px",
        md: "8px",
        lg: "12px",
        pill: "9999px",
      },
      boxShadow: {
        flat: "none",
        ring: "0 0 0 1px var(--border)",
        raised:
          "0 1px 2px rgba(15,23,42,.06), 0 1px 3px rgba(15,23,42,.08)",
      },
      transitionTimingFunction: {
        // 禁用弹跳曲线 cubic-bezier(0.68,-0.55,0.265,1.55)
        standard: "cubic-bezier(0.2, 0, 0, 1)",
      },
      transitionDuration: {
        fast: "120ms",
        base: "160ms",
        slow: "240ms",
      },
      letterSpacing: {
        caps: "0.06em",
        h1: "-0.01em",
        kpi: "-0.02em",
      },
    },
  },
  plugins: [],
};

export default config;
