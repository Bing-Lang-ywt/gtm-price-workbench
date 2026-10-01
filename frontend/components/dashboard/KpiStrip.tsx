"use client";

import {
  Database,
  Radio,
  Activity,
  TrendingUp,
  type LucideIcon,
} from "lucide-react";
import { type DashboardSummary } from "@/lib/types";
import { formatEUR, countryName } from "@/lib/format";
import { useI18n } from "@/lib/i18n";

interface StatCardProps {
  icon: LucideIcon;
  label: string;
  value: string;
  sub?: string;
  accent?: boolean;
}

function StatCard({ icon: Icon, label, value, sub, accent }: StatCardProps) {
  return (
    <div className="flex items-center gap-3 border border-border bg-surface px-4 py-3">
      <span
        className={
          "flex h-9 w-9 shrink-0 items-center justify-center rounded-md " +
          (accent
            ? "bg-accent-soft text-accent-text"
            : "bg-surface-warm text-fg-2")
        }
      >
        <Icon size={18} />
      </span>
      <div className="min-w-0 flex-1">
        <p className="truncate text-[11px] font-semibold uppercase tracking-caps text-muted">
          {label}
        </p>
        <p className="tabular whitespace-nowrap text-xl font-semibold leading-tight text-fg sm:text-2xl">
          {value}
        </p>
        {sub && <p className="truncate text-[11px] text-muted">{sub}</p>}
      </div>
    </div>
  );
}

export function KpiStrip({
  summary,
  countryCount,
  channelCount,
}: {
  summary?: DashboardSummary | null;
  countryCount?: number;
  channelCount?: number;
}) {
  const { t } = useI18n();
  const spread =
    summary?.max_regional_spread != null
      ? formatEUR(summary.max_regional_spread)
      : "—";
  const spreadSub =
    summary?.spread_model || summary?.spread_country_max
      ? `${summary.spread_model ?? "—"} · ${
          summary.spread_country_max ?? ""
        }→${summary.spread_country_min ?? ""}`
      : t('所选机型跨四国 max−min');

  return (
    <div className="grid grid-cols-1 gap-px bg-border sm:grid-cols-2 lg:grid-cols-4">
      <StatCard
        icon={Database}
        label={t('监控 SKU')}
        value={String(summary?.monitored_skus ?? "—")}
        sub={
          countryCount != null && channelCount != null
            ? t('跨 {c} 国 {ch} 渠道', { c: countryCount, ch: channelCount })
            : t('跨多国多渠道')
        }
      />
      <StatCard
        icon={Radio}
        label={t('活跃渠道')}
        value={String(summary?.active_channels ?? "—")}
        sub={t('运营商 + 公开市场')}
      />
      <StatCard
        icon={Activity}
        label={t('昨夜异动')}
        value={String(summary?.last_night_changes ?? "—")}
        sub={t('降价/反弹/缺货/上新')}
        accent
      />
      <StatCard
        icon={TrendingUp}
        label={t('最大区域价差')}
        value={spread}
        sub={spreadSub}
      />
    </div>
  );
}
