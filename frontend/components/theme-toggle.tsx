"use client";

import { useEffect, useState } from "react";
import { Moon, Sun } from "lucide-react";

/** 浅/深主题切换：默认深色（科技风），选择持久化到 localStorage('pm-theme')。 */
export function ThemeToggle() {
  const [dark, setDark] = useState(true);

  useEffect(() => {
    setDark(document.documentElement.classList.contains("dark"));
  }, []);

  const toggle = () => {
    const next = !dark;
    document.documentElement.classList.toggle("dark", next);
    try {
      localStorage.setItem("pm-theme", next ? "dark" : "light");
    } catch {
      /* ignore */
    }
    setDark(next);
  };

  return (
    <button
      type="button"
      onClick={toggle}
      aria-label="切换浅色 / 深色主题"
      title={dark ? "切换到浅色" : "切换到深色"}
      className="inline-flex h-8 w-8 items-center justify-center rounded-md text-fg-2 transition-colors duration-fast ease-standard hover:bg-surface-warm"
    >
      {dark ? <Sun size={16} /> : <Moon size={16} />}
    </button>
  );
}
