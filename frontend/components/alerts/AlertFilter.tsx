"use client";

import { Filter, RotateCcw } from "lucide-react";
import { Chip, SegmentedControl } from "@/components/ui/chip";
import {
  COUNTRIES,
  type AlertSeverity,
  type AlertStatus,
  type AlertType,
  type CountryCode,
  type ModelRow,
} from "@/lib/types";
import { ALERT_TYPE_LABEL, SEVERITY_LABEL } from "@/lib/format";
import { Button } from "@/components/ui/button";
import { useI18n } from "@/lib/i18n";

export interface AlertFilterState {
  severities: AlertSeverity[];
  types: AlertType[];
  countries: CountryCode[];
  modelId: string;
  status: AlertStatus | "all";
  timeRange: "7d" | "30d" | "90d" | "all";
}

export const DEFAULT_ALERT_FILTER: AlertFilterState = {
  severities: [],
  types: [],
  countries: [],
  modelId: "all",
  status: "all",
  timeRange: "30d",
};

function toggle<T>(arr: T[], v: T): T[] {
  return arr.includes(v) ? arr.filter((x) => x !== v) : [...arr, v];
}

const SEVS: AlertSeverity[] = ["critical", "warning", "info"];
const TYPES: AlertType[] = ["price_drop", "price_up", "new_sku", "stock_out"];
const STATUSES: { value: AlertStatus | "all"; label: string }[] = [
  { value: "all", label: "全部" },
  { value: "unread", label: "未读" },
  { value: "resolved", label: "已处理" },
  { value: "ignored", label: "已忽略" },
];

export function AlertFilter({
  value,
  onChange,
  models,
}: {
  value: AlertFilterState;
  onChange: (s: AlertFilterState) => void;
  models: ModelRow[];
}) {
  const { t } = useI18n();
  const set = (patch: Partial<AlertFilterState>) =>
    onChange({ ...value, ...patch });

  return (
    <aside className="w-56 shrink-0 border-r border-border bg-surface p-3">
      <div className="mb-3 flex items-center justify-between">
        <span className="flex items-center gap-1.5 text-[12px] font-semibold text-fg-2">
          <Filter size={14} /> {t("筛选")}
        </span>
        <button
          onClick={() => onChange(DEFAULT_ALERT_FILTER)}
          className="inline-flex items-center gap-1 text-[11px] text-muted hover:text-fg"
        >
          <RotateCcw size={12} /> {t("重置")}
        </button>
      </div>

      <Section label={t("严重度")}>
        <div className="flex flex-wrap gap-1.5">
          {SEVS.map((s) => (
            <Chip
              key={s}
              active={value.severities.includes(s)}
              onClick={() => set({ severities: toggle(value.severities, s) })}
            >
              {t(SEVERITY_LABEL[s])}
            </Chip>
          ))}
        </div>
      </Section>

      <Section label={t("类型")}>
        <div className="flex flex-wrap gap-1.5">
          {TYPES.map((ty) => (
            <Chip
              key={ty}
              active={value.types.includes(ty)}
              onClick={() => set({ types: toggle(value.types, ty) })}
            >
              {t(ALERT_TYPE_LABEL[ty])}
            </Chip>
          ))}
        </div>
      </Section>

      <Section label={t("国家")}>
        <div className="flex flex-wrap gap-1.5">
          {COUNTRIES.map((c) => (
            <Chip
              key={c.code}
              active={value.countries.includes(c.code)}
              onClick={() => set({ countries: toggle(value.countries, c.code) })}
            >
              <span className="font-mono text-[11px] font-semibold">
                {c.code}
              </span>
            </Chip>
          ))}
        </div>
      </Section>

      <Section label={t("机型")}>
        <select
          value={value.modelId}
          onChange={(e) => set({ modelId: e.target.value })}
          className="h-8 w-full rounded-md border border-border bg-bg px-2 text-[12px] text-fg outline-none focus:border-accent"
        >
          <option value="all">{t("全部机型")}</option>
          {models.map((m) => (
            <option key={m.id} value={m.id}>
              {m.display_name}
            </option>
          ))}
        </select>
      </Section>

      <Section label={t("状态")}>
        <select
          value={value.status}
          onChange={(e) =>
            set({ status: e.target.value as AlertStatus | "all" })
          }
          className="h-8 w-full rounded-md border border-border bg-bg px-2 text-[12px] text-fg outline-none focus:border-accent"
        >
          {STATUSES.map((s) => (
            <option key={s.value} value={s.value}>
              {t(s.label)}
            </option>
          ))}
        </select>
      </Section>

      <Section label={t("时间")}>
        <SegmentedControl
          size="sm"
          value={value.timeRange}
          options={[
            { value: "7d", label: t("7天") },
            { value: "30d", label: t("30天") },
            { value: "90d", label: t("90天") },
          ]}
          onChange={(v) => set({ timeRange: v })}
        />
      </Section>
    </aside>
  );
}

function Section({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="mb-3">
      <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-caps text-muted">
        {label}
      </p>
      {children}
    </div>
  );
}
