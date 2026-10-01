"use client";

import {
  Smartphone,
  Coins,
} from "lucide-react";
import { Chip, SegmentedControl } from "@/components/ui/chip";
import { CountrySelect } from "@/components/ui/country-select";
import { PRICE_TYPES, type CountryCode, type ModelRow, type PriceType } from "@/lib/types";
import { PRICE_TYPE_LABEL } from "@/lib/format";
import { useI18n } from "@/lib/i18n";

export type PriceMode = "all" | PriceType;
// 保留 TimeRange 类型供 TrendDrill 内部使用（默认 90 天窗口），顶栏不再暴露该切换。
export type TimeRange = "7d" | "30d" | "90d";

interface FilterBarProps {
  countries: CountryCode[];
  onSetCountries: (next: CountryCode[]) => void;
  models: ModelRow[];
  modelFilter: string; // 'all' | model_id
  onModelChange: (v: string) => void;
  currency: "EUR" | "raw";
  onCurrency: (v: "EUR" | "raw") => void;
}

export function FilterBar(props: FilterBarProps) {
  const { t } = useI18n();
  const {
    countries,
    onSetCountries,
    models,
    modelFilter,
    onModelChange,
    currency,
    onCurrency,
  } = props;

  return (
    <div className="border-b border-border bg-surface">
      <div className="overflow-x-auto px-5 py-3">
        <div className="flex min-w-max items-center gap-x-6 gap-y-3 sm:flex-wrap sm:min-w-0">
        {/* 国家下拉选择器 */}
        <CountrySelect selected={countries} onChange={onSetCountries} />

        {/* 机型 */}
        <div className="flex items-center gap-2">
          <span className="flex items-center gap-1 text-[12px] font-medium text-muted">
            <Smartphone size={14} /> {t('机型')}
          </span>
          <select
            value={modelFilter}
            onChange={(e) => onModelChange(e.target.value)}
            className="h-8 rounded-md border border-border bg-surface px-2 text-[13px] text-fg outline-none transition-colors duration-fast ease-standard focus:border-accent"
          >
            <option value="all">{t('全部机型')}</option>
            {models.map((m) => (
              <option key={m.id} value={m.id}>
                {m.display_name}
                {m.is_target ? " · " + t('本品牌') : ""}
              </option>
            ))}
          </select>
        </div>

        {/* 币种 */}
        <div className="flex items-center gap-2">
          <span className="flex items-center gap-1 text-[12px] font-medium text-muted">
            <Coins size={14} /> {t('币种')}
          </span>
          <SegmentedControl
            value={currency}
            options={[
              { value: "EUR", label: "EUR" },
              { value: "raw", label: t('原始') },
            ]}
            onChange={onCurrency}
            size="sm"
          />
        </div>
      </div>
    </div>
  </div>
);
}
