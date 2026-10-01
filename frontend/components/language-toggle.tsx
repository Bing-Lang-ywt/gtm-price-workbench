"use client";

import { Globe } from "lucide-react";
import { useI18n } from "@/lib/i18n";

/** 中 / EN 语言切换：默认中文，选择持久化到 localStorage('pm-lang')。 */
export function LanguageToggle() {
  const { lang, toggleLang, t } = useI18n();
  const isZh = lang === "zh";
  return (
    <button
      type="button"
      onClick={toggleLang}
      aria-label={t("切换语言")}
      title={t("切换语言")}
      className="inline-flex h-8 min-w-8 items-center justify-center gap-1 rounded-md px-1.5 text-[12px] font-medium text-fg-2 transition-colors duration-fast ease-standard hover:bg-surface-warm"
    >
      <Globe size={16} />
      <span>{isZh ? "中" : "EN"}</span>
    </button>
  );
}
