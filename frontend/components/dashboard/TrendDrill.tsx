"use client";

import { useMemo } from "react";
import { useQueries } from "@tanstack/react-query";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from "recharts";
import { LineChart as LineIcon, TrendingUp } from "lucide-react";
import { getPriceHistory } from "@/lib/api";
import {
  type CountryCode,
  type PriceLatest,
  type PriceType,
} from "@/lib/types";
import { formatEUR, PRICE_TYPE_LABEL } from "@/lib/format";
import { CountryBadge } from "@/components/ui/country-badge";
import { EmptyState } from "@/components/ui/skeleton";
import { cn } from "@/lib/cn";
import { useI18n } from "@/lib/i18n";
import type { MatrixRow } from "@/lib/matrix";
import type { PriceMode } from "./FilterBar";

interface Props {
  prices: PriceLatest[];
  rows: MatrixRow[];
  modelId: string | null;
  countries: CountryCode[];
  priceMode: PriceMode;
  currency: "EUR" | "raw";
}

function daysAgoISO(d: number): string {
  const t = new Date();
  t.setDate(t.getDate() - d);
  return t.toISOString();
}

function fmtDate(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return `${d.getMonth() + 1}-${d.getDate()}`;
}

type HistoryPoint = {
  captured_at: string;
  amount_eur?: number | null;
  amount?: number | null;
  price_type?: PriceType;
};

function normalizeHistory(data: unknown): HistoryPoint[] {
  if (!data) return [];
  const arr = Array.isArray(data)
    ? data
    : ((data as { data?: unknown }).data ?? []);
  return (arr as HistoryPoint[]) ?? [];
}

export function TrendDrill({
  prices,
  rows,
  modelId,
  countries,
  priceMode,
  currency,
}: Props) {
  const { t } = useI18n();
  const focusTier: PriceType = priceMode === "all" ? "unlocked" : priceMode;
  const country = countries[0];

  // 每个可见机型挑一个代表 SKU（所选首国、优先聚焦档位），用于叠加同档折线
  const modelSkus = useMemo(() => {
    const map = new Map<string, string>();
    for (const row of rows) {
      const mid = row.model_id;
      if (!mid || map.has(mid)) continue;
      const recs = prices.filter((p) => (p.model_id ?? p.model) === mid);
      if (recs.length === 0) continue;
      const inCountry = recs.filter(
        (p) => p.country_code === country || p.country === country,
      );
      const pool = inCountry.length ? inCountry : recs;
      const tiered = pool.filter((p) => p.price_type === focusTier);
      const rep = tiered[0] ?? pool[0];
      const sku = rep?.sku_id;
      if (sku) map.set(mid, sku);
    }
    return map;
  }, [rows, prices, country, focusTier]);

  const modelNames = useMemo(() => {
    const m = new Map<string, string>();
    for (const p of prices) {
      const mid = p.model_id ?? p.model;
      if (mid && !m.has(mid)) m.set(mid, p.model ?? mid);
    }
    return m;
  }, [prices]);

  // 顶栏「区间」切换已移除；趋势图固定取近 90 天价格历史窗口。
  const from = useMemo(() => daysAgoISO(90), []);

  const queries = useQueries({
    queries: Array.from(modelSkus.entries()).map(([mid, sku]) => ({
      queryKey: ["price-history", sku, from] as const,
      queryFn: () => getPriceHistory({ sku_id: sku, from }),
    })),
  });

  const series = useMemo(
    () =>
      Array.from(modelSkus.entries()).map(([mid, sku], i) => ({
        mid,
        sku,
        history: normalizeHistory(queries[i]?.data),
      })),
    [modelSkus, queries],
  );

  const chartData = useMemo(() => {
    const byDate = new Map<string, Record<string, number | string | undefined>>();
    for (const { mid, history } of series) {
      for (const p of history) {
        if (!p.captured_at) continue;
        const key = fmtDate(p.captured_at);
        if (!byDate.has(key)) {
          byDate.set(key, {
            date: key,
            ts: new Date(p.captured_at).getTime(),
          });
        }
        const v = p.amount_eur ?? p.amount ?? undefined;
        if (v != null) byDate.get(key)![mid] = v;
      }
    }
    return Array.from(byDate.values()).sort(
      (a, b) => (a.ts as number) - (b.ts as number),
    );
  }, [series]);

  // 图例与折线顺序：当前选中机型置顶
  const legendModels = useMemo(
    () =>
      Array.from(modelSkus.keys()).sort((a) => (a === modelId ? -1 : 1)),
    [modelSkus, modelId],
  );

  const isLoading = queries.some((q) => q.isLoading);
  const isError = queries.some((q) => q.isError);

  return (
    <section className="rounded-lg border border-border bg-surface">
      <div className="flex items-center justify-between border-b border-border px-4 py-2.5">
        <h2 className="flex items-center gap-2 text-sm font-semibold text-fg">
          <LineIcon size={16} className="text-accent" />
          {t('价格趋势下钻')}
        </h2>
        <div className="flex items-center gap-2 text-[12px] text-muted">
          <span className="font-medium text-fg-2">
            {t(PRICE_TYPE_LABEL[focusTier])}
          </span>
          {country && <CountryBadge code={country} />}
        </div>
      </div>

      {!modelId ? (
        <EmptyState
          icon={<TrendingUp size={18} />}
          title={t('选择机型查看趋势')}
          description={t('在对比矩阵中点击任意机型行，展开该机型与同档竞品的价格走势对比。')}
        />
      ) : isLoading ? (
          <div className="flex h-[260px] items-center justify-center text-[13px] text-muted">
            {t('加载价格历史…')}
          </div>
      ) : isError ? (
        <EmptyState
            icon={<TrendingUp size={18} />}
            title={t('趋势数据获取失败')}
            description={t('部分机型价格历史暂不可达，请稍后重试。')}
        />
      ) : chartData.length === 0 ? (
        <EmptyState
            icon={<TrendingUp size={18} />}
            title={t('暂无价格历史')}
            description={t('所选机型在当前区间尚未抓取到历史价格点。')}
        />
      ) : (
        <div className="px-2 py-3">
          <div className="mb-2 flex flex-wrap gap-x-4 gap-y-1.5 px-2">
            {legendModels.map((mid) => {
              const selected = mid === modelId;
              return (
                <span
                  key={mid}
                  className={cn(
                    "flex items-center gap-1.5 text-[11px]",
                    selected ? "font-semibold text-accent-text" : "text-fg-2",
                  )}
                >
                  <span
                    className="inline-block h-2 w-3 rounded-sm"
                    style={{
                      background: selected ? "var(--accent)" : "var(--muted)",
                      opacity: selected ? 1 : 0.6,
                    }}
                  />
                  {modelNames.get(mid) ?? mid}
                  {selected && (
                    <span className="text-[10px] text-muted">· {t('当前')}</span>
                  )}
                </span>
              );
            })}
          </div>
          <div style={{ height: 260 }}>
            <ResponsiveContainer width="100%" height="100%">
              <LineChart
                data={chartData}
                margin={{ top: 8, right: 12, bottom: 4, left: 4 }}
              >
                <CartesianGrid
                  strokeDasharray="3 3"
                  stroke="var(--border-soft)"
                  vertical={false}
                />
                <XAxis
                  dataKey="date"
                  stroke="var(--border)"
                  tick={{ fill: "var(--muted)", fontSize: 11 }}
                  tickLine={false}
                />
                <YAxis
                  stroke="var(--border)"
                  tick={{ fill: "var(--muted)", fontSize: 11 }}
                  tickLine={false}
                  width={48}
                  tickFormatter={(v: number) =>
                    currency === "EUR"
                      ? `€${Math.round(v)}`
                      : String(Math.round(v))
                  }
                />
                <Tooltip
                  contentStyle={{
                    background: "var(--surface)",
                    border: "1px solid var(--border)",
                    borderRadius: 8,
                    fontSize: 12,
                    color: "var(--fg)",
                  }}
                  labelStyle={{ color: "var(--muted)" }}
                  formatter={(value: number, name: string) => [
                    currency === "EUR"
                      ? formatEUR(value)
                      : String(Math.round(value)),
                    modelNames.get(name) ?? name,
                  ]}
                />
                {legendModels.map((mid) => {
                  const selected = mid === modelId;
                  const has = chartData.some((d) => d[mid] != null);
                  if (!has) return null;
                  return (
                    <Line
                      key={mid}
                      type="monotone"
                      dataKey={mid}
                      name={mid}
                      stroke={selected ? "var(--accent)" : "var(--muted)"}
                      strokeOpacity={selected ? 1 : 0.6}
                      strokeWidth={selected ? 2.5 : 1.5}
                      dot={false}
                      activeDot={selected ? { r: 3 } : false}
                      connectNulls
                      isAnimationActive={false}
                    />
                  );
                })}
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}
    </section>
  );
}
