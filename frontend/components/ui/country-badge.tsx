"use client";

import { cn } from "@/lib/cn";
import { COUNTRY_BY_CODE } from "@/lib/types";
import { useI18n } from "@/lib/i18n";

/**
 * 国家表示：2 字母 ISO 码徽标（RS/HR/HU/RO）+ 国名文字。
 * 严禁 emoji 国旗（P0-1）。Lucide 无国旗图标，故用文字码。
 */
export function CountryBadge({
  code,
  showName = false,
  className,
}: {
  code?: string | null;
  showName?: boolean;
  className?: string;
}) {
  const { t } = useI18n();
  const meta = code ? COUNTRY_BY_CODE[code] : undefined;
  const label = meta?.code ?? code ?? "—";
  const name = meta?.name ?? code ?? t("未知");
  return (
    <span className={cn("inline-flex items-center gap-1.5", className)}>
      <span
        className={cn(
          "inline-flex h-5 min-w-[22px] items-center justify-center rounded-sm border border-border",
          "bg-surface-warm px-1 font-mono text-[11px] font-semibold tracking-wide text-fg-2",
        )}
        aria-hidden
      >
        {label}
      </span>
      {showName && (
        <span className="text-[13px] text-fg-2">{name}</span>
      )}
    </span>
  );
}
