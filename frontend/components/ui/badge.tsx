"use client";

import { type ReactNode } from "react";
import { cn } from "@/lib/cn";
import { useI18n } from "@/lib/i18n";

export type Tone =
  | "neutral"
  | "accent"
  | "success"
  | "danger"
  | "warn"
  | "info";

const toneClass: Record<Tone, string> = {
  neutral: "bg-surface-warm text-fg-2 border-border",
  accent: "bg-accent-soft text-accent-text border-accent/30",
  success: "bg-success/10 text-success border-success/20",
  danger: "bg-danger/10 text-danger border-danger/20",
  warn: "bg-warn/10 text-warn-strong border-warn/20",
  info: "bg-info/10 text-info border-info/20",
};

export function Badge({
  tone = "neutral",
  children,
  className,
}: {
  tone?: Tone;
  children: ReactNode;
  className?: string;
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-pill border px-2 py-0.5 text-[11px] font-semibold",
        toneClass[tone],
        className,
      )}
    >
      {children}
    </span>
  );
}

/* ---------------- 状态点（健康度红绿灯） ---------------- */

export function StatusDot({
  status,
  className,
}: {
  status: "healthy" | "degraded" | "down" | "unknown" | "running" | string;
  className?: string;
}) {
  const color =
    status === "healthy" || status === "running"
      ? "bg-success"
      : status === "degraded"
        ? "bg-warn"
        : status === "down" || status === "failed"
          ? "bg-danger"
          : "bg-meta";
  return (
    <span className={cn("inline-block h-2 w-2 rounded-full", color, className)} />
  );
}

/* ---------------- Delta 徽标（价涨/跌） ---------------- */

import { TrendingUp, TrendingDown } from "lucide-react";
import { formatPct } from "@/lib/format";

export function Delta({
  pct,
  className,
}: {
  pct?: number | null;
  className?: string;
}) {
  const { t } = useI18n();
  if (pct == null || Number.isNaN(pct)) {
    return <span className={cn("text-meta", className)}>—</span>;
  }
  const up = pct > 0; // 价涨 = 红
  const Icon = up ? TrendingUp : TrendingDown;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-0.5 text-[12px] font-semibold tabular",
        up ? "text-trend-up" : "text-trend-down",
        className,
      )}
      title={up ? t("价格上涨") : t("价格下降")}
    >
      <Icon size={14} strokeWidth={2.5} />
      {formatPct(pct)}
    </span>
  );
}
