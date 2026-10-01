"use client";

import {
  CircleAlert,
  TriangleAlert,
  Info,
  TrendingDown,
  TrendingUp,
  Plus,
  PackageX,
  Eye,
  Check,
  type LucideIcon,
} from "lucide-react";
import { VirtualList } from "@/components/ui/virtual-list";
import { CountryBadge } from "@/components/ui/country-badge";
import { type AlertEvent, type AlertSeverity, type AlertType } from "@/lib/types";
import {
  ALERT_TYPE_LABEL,
  PRICE_TYPE_LABEL,
  formatEUR,
  relativeTime,
  absoluteTime,
} from "@/lib/format";
import { cn } from "@/lib/cn";
import { useI18n } from "@/lib/i18n";

const SEV_ICON: Record<AlertSeverity, LucideIcon> = {
  critical: CircleAlert,
  warning: TriangleAlert,
  info: Info,
};
const SEV_BAR: Record<AlertSeverity, string> = {
  critical: "border-l-danger",
  warning: "border-l-warn",
  info: "border-l-info",
};
const SEV_TEXT: Record<AlertSeverity, string> = {
  critical: "text-danger",
  warning: "text-warn-strong",
  info: "text-info",
};

const TYPE_ICON: Record<AlertType, LucideIcon> = {
  price_drop: TrendingDown,
  price_up: TrendingUp,
  new_sku: Plus,
  stock_out: PackageX,
};

function Row({
  a,
  onSelect,
  onResolve,
  onIgnore,
}: {
  a: AlertEvent;
  onSelect: (a: AlertEvent) => void;
  onResolve: (a: AlertEvent) => void;
  onIgnore: (a: AlertEvent) => void;
}) {
  const { t } = useI18n();
  const sev = (a.severity ?? "info") as AlertSeverity;
  const SevIcon = SEV_ICON[sev];
  const TypeIcon = TYPE_ICON[a.type] ?? Info;
  const delta =
    a.before != null && a.after != null && a.before !== 0
      ? ((a.after - a.before) / Math.abs(a.before)) * 100
      : null;
  const up = (delta ?? 0) > 0;

  return (
    <div
      className={cn(
        "group flex h-full cursor-pointer items-stretch border-b border-border-soft border-l-2 transition-colors duration-fast ease-standard hover:bg-surface-warm",
        SEV_BAR[sev],
      )}
      onClick={() => onSelect(a)}
    >
      <div className="flex w-full items-center gap-3 px-3">
        <SevIcon size={18} className={cn("shrink-0", SEV_TEXT[sev])} />
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5">
            <TypeIcon size={13} className="shrink-0 text-muted" />
            <span className="truncate text-[13px] font-medium text-fg">
              {a.title ??
                `${a.model ?? t("机型")} · ${
                  a.price_type ? t(PRICE_TYPE_LABEL[a.price_type]) : ""
                } ${ALERT_TYPE_LABEL[a.type] ? t(ALERT_TYPE_LABEL[a.type]) : ""}`}
            </span>
          </div>
          <div className="mt-0.5 flex items-center gap-2 text-[11px] text-muted">
            <span className="truncate">
              {a.channel ?? t("渠道")}
              {a.country_code ? " · " : ""}
            </span>
            {a.country_code && <CountryBadge code={a.country_code} />}
            <span
              className="tabular"
              title={absoluteTime(a.triggered_at)}
            >
              {relativeTime(a.triggered_at)}
            </span>
          </div>
        </div>

        {/* before → after */}
        <div className="shrink-0 text-right">
          {a.before != null && a.after != null ? (
            <div className="tabular text-[12px] text-fg-2">
              <span className="text-muted">{formatEUR(a.before)}</span>
              <span className="mx-1 text-meta">→</span>
              <span className="font-semibold text-fg">
                {formatEUR(a.after)}
              </span>
            </div>
          ) : null}
          {delta != null && (
            <div
              className={cn(
                "tabular text-[11px] font-semibold",
                up ? "text-trend-up" : "text-trend-down",
              )}
            >
              {up ? "▲" : "▼"} {Math.abs(delta).toFixed(1)}%
            </div>
          )}
        </div>

        {/* 操作 */}
        <div className="ml-2 flex shrink-0 items-center gap-1 opacity-0 transition-opacity duration-fast ease-standard group-hover:opacity-100">
          <button
            onClick={(e) => {
              e.stopPropagation();
              onSelect(a);
            }}
            aria-label={t("查看")}
            className="flex h-7 w-7 items-center justify-center rounded-md text-fg-2 hover:bg-surface"
          >
            <Eye size={15} />
          </button>
          <button
            onClick={(e) => {
              e.stopPropagation();
              onResolve(a);
            }}
            aria-label={t("处理")}
            className="flex h-7 w-7 items-center justify-center rounded-md text-success hover:bg-surface"
          >
            <Check size={15} />
          </button>
        </div>
      </div>
    </div>
  );
}

export function AlertStream({
  alerts,
  onSelect,
  onResolve,
  onIgnore,
}: {
  alerts: AlertEvent[];
  onSelect: (a: AlertEvent) => void;
  onResolve: (a: AlertEvent) => void;
  onIgnore: (a: AlertEvent) => void;
}) {
  const { t } = useI18n();
  if (alerts.length === 0) {
    return (
      <div className="flex h-[60vh] items-center justify-center text-[13px] text-muted">
        {t("暂无匹配告警")}
      </div>
    );
  }
  return (
    <VirtualList
      items={alerts}
      rowHeight={72}
      height={560}
      renderRow={(a) => (
        <Row a={a} onSelect={onSelect} onResolve={onResolve} onIgnore={onIgnore} />
      )}
    />
  );
}
