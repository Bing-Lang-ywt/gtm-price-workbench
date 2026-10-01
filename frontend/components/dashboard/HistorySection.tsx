"use client";

import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  CalendarDays,
  TrendingDown,
  LineChart as LineIcon,
  Tag,
} from "lucide-react";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Legend,
} from "recharts";
import { CountryBadge } from "@/components/ui/country-badge";
import { EmptyState } from "@/components/ui/skeleton";
import { cn } from "@/lib/cn";
import { formatEUR, formatRaw } from "@/lib/format";
import { getPromotions, getModelTrend } from "@/lib/api";
import type {
  ModelRow,
  PriceLatest,
  PromotionEvent,
  ModelTrend,
  PriceType,
} from "@/lib/types";
import type { PriceMode } from "./FilterBar";
import { useI18n } from "@/lib/i18n";

interface Props {
  models: ModelRow[];
  priceMode: PriceMode;
  currency: "EUR" | "raw";
  /** 顶部选中的日期（null = 最新）；整张看板跟随它 */
  selectedDate: string | null;
  /** 由顶部日期选择器驱动；促销事件点击也可跳到对应日 */
  onSelectDate: (date: string | null) => void;
  /** 当日价格快照行（来自看板主数据源，已按 14 天窗口去重） */
  snapshotRows: PriceLatest[];
  /** 快照是否仍在加载 */
  snapshotLoading?: boolean;
}

const PROMO_THRESHOLDS = [
  { v: 0.03, label: "≥3%" },
  { v: 0.05, label: "≥5%" },
  { v: 0.1, label: "≥10%" },
];

export function HistorySection({
  models,
  priceMode,
  currency,
  selectedDate,
  onSelectDate,
  snapshotRows,
  snapshotLoading = false,
}: Props) {
  const { t } = useI18n();
  const focusTier: PriceType = priceMode === "all" ? "unlocked" : priceMode;

  const [promoThreshold, setPromoThreshold] = useState(0.03);

  const snapRows: PriceLatest[] = snapshotRows;

  // 促销事件
  const promoQ = useQuery({
    queryKey: ["promotions", promoThreshold],
    queryFn: () => getPromotions({ threshold: promoThreshold }),
  });
  const promos: PromotionEvent[] = promoQ.data ?? [];

  // 生命周期走势（单品）
  const [trendModelId, setTrendModelId] = useState<string | null>(null);
  useEffect(() => {
    if (!trendModelId && models.length) {
      const demobrand = models.find((m) => m.is_target);
      setTrendModelId((demobrand ?? models[0]).id);
    }
  }, [trendModelId, models]);

  const trendQ = useQuery({
    queryKey: ["model-trend", trendModelId, focusTier],
    queryFn: () =>
      getModelTrend({ model_id: trendModelId!, price_type: focusTier }),
    enabled: !!trendModelId,
  });
  const trend: ModelTrend | undefined = trendQ.data;

  const chartData = useMemo(() => {
    const byDate = new Map<string, Record<string, number | string>>();
    for (const ch of trend?.channels ?? []) {
      for (const p of ch.points) {
        if (p.amount_eur == null) continue;
        if (!byDate.has(p.date)) byDate.set(p.date, { date: p.date, ts: p.ts });
        byDate.get(p.date)![ch.channel] = p.amount_eur;
      }
    }
    return Array.from(byDate.values()).sort((a, b) =>
      (a.ts as string).localeCompare(b.ts as string),
    );
  }, [trend]);

  const plotChannels = useMemo(() => {
    const cs = (trend?.channels ?? [])
      .filter((c) => c.points.length >= 2)
      .sort((a, b) => b.points.length - a.points.length)
      .slice(0, 10)
      .map((c) => c.channel);
    return cs;
  }, [trend]);

  return (
    <section className="space-y-4">
      {/* 当日价格快照（跟随顶部日期；日历已在顶部作为日期选项，不再常驻） */}
      <div className="rounded-lg border border-border bg-surface">
        <div className="flex items-center justify-between border-b border-border px-4 py-2.5">
          <h2 className="flex items-center gap-2 text-sm font-semibold text-fg">
            <CalendarDays size={16} className="text-accent" />
            {t('当日价格快照')}
            <span className="text-[12px] font-normal text-muted">
              {selectedDate ? t('{date}（窗口内最新价）', { date: selectedDate }) : t('最新（窗口内最新价）')}
            </span>
          </h2>
          <span className="text-[12px] text-muted">
            {snapshotLoading ? t('加载中…') : t('{n} 条', { n: snapRows.length })}
          </span>
        </div>
        <div className="max-h-[420px] overflow-auto">
          {snapshotLoading ? (
            <div className="p-6 text-center text-[13px] text-muted">
              {t('加载价格…')}
            </div>
          ) : snapRows.length === 0 ? (
            <EmptyState
              icon={<CalendarDays size={18} />}
              title={t('该日暂无价格')}
              description={t('所选日期前后 14 天窗口内没有可展示的价格记录，请换一个有数据的日期或点「回到最新」。')}
            />
          ) : (
              <table className="w-full text-[12px]">
                <thead className="sticky top-0 bg-surface text-muted">
                  <tr className="border-b border-border text-left">
                    <th className="px-3 py-2 font-medium">{t('机型')}</th>
                    <th className="px-3 py-2 font-medium">{t('渠道')}</th>
                    <th className="px-3 py-2 font-medium">{t('国家')}</th>
                    <th className="px-3 py-2 font-medium">{t('类型')}</th>
                    <th className="px-3 py-2 text-right font-medium">EUR</th>
                    <th className="px-3 py-2 text-right font-medium">{t('本地价')}</th>
                    <th className="px-3 py-2 text-center font-medium">{t('库存')}</th>
                  </tr>
                </thead>
                <tbody>
                  {snapRows.map((r, i) => (
                    <tr
                      key={`${r.sku_id}-${r.price_type}-${i}`}
                      className="border-b border-border/60 hover:bg-surface-warm"
                    >
                      <td className="px-3 py-1.5 text-fg-2">
                        {r.model_marketing_code || r.model || "—"}
                      </td>
                      <td className="px-3 py-1.5 text-fg-2">{r.channel}</td>
                      <td className="px-3 py-1.5">
                        {r.country_code ? (
                          <CountryBadge code={r.country_code} />
                        ) : (
                          "—"
                        )}
                      </td>
                      <td className="px-3 py-1.5 text-muted">{r.price_type}</td>
                      <td className="px-3 py-1.5 text-right font-medium text-fg">
                        {formatEUR(r.amount_eur)}
                      </td>
                      <td className="px-3 py-1.5 text-right text-muted">
                        {formatRaw(r.amount, r.currency)}
                      </td>
                      <td className="px-3 py-1.5 text-center">
                        {r.in_stock ? (
                          <span className="text-accent-text">{t('有货')}</span>
                        ) : (
                          <span className="text-danger">{t('缺货')}</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>

      {/* 第二行：促销活动时间线 */}
      <div className="rounded-lg border border-border bg-surface">
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border px-4 py-2.5">
          <h2 className="flex items-center gap-2 text-sm font-semibold text-fg">
            <Tag size={16} className="text-accent" />
            {t('促销活动时间线')}
            <span className="text-[12px] font-normal text-muted">
              {t('（各机型×渠道首次显著降价）')}
            </span>
          </h2>
          <div className="flex items-center gap-1.5">
            <span className="text-[11px] text-muted">{t('降幅阈值')}</span>
            {PROMO_THRESHOLDS.map((t) => (
              <button
                key={t.v}
                onClick={() => setPromoThreshold(t.v)}
                className={cn(
                  "rounded-md border px-2 py-1 text-[11px] transition-colors",
                  promoThreshold === t.v
                    ? "border-accent bg-accent text-white"
                    : "border-border text-fg-2 hover:bg-surface",
                )}
              >
                {t.label}
              </button>
            ))}
          </div>
        </div>
        <div className="max-h-[360px] overflow-auto p-2">
          {promoQ.isLoading ? (
            <div className="p-6 text-center text-[13px] text-muted">{t('加载中…')}</div>
          ) : promos.length === 0 ? (
            <EmptyState
              icon={<TrendingDown size={18} />}
              title={t('无促销事件')}
              description={t('当前阈值下未检测到显著降价。可下调阈值，或等本项目持续抓取积累更多数据。')}
            />
          ) : (
            <ul className="divide-y divide-border/60">
              {promos.map((e, i) => (
                <li key={`${e.sku_id}-${e.date}-${i}`}>
                  <button
                    onClick={() => e.date && onSelectDate(e.date)}
                    className="flex w-full items-center gap-3 px-3 py-2 text-left transition-colors hover:bg-surface-warm"
                  >
                    <span className="w-20 shrink-0 font-mono text-[12px] text-muted">
                      {e.date}
                    </span>
                    <span className="w-40 shrink-0 truncate text-[13px] text-fg-2">
                      {e.brand ? `${e.brand} ` : ""}
                      {e.model_marketing_code || e.model}
                    </span>
                    <span className="w-28 shrink-0 truncate text-[12px] text-muted">
                      {e.channel}
                    </span>
                    <span className="flex shrink-0 items-center gap-1 text-[12px] text-fg-2">
                      {formatEUR(e.prev_amount_eur)}
                      <TrendingDown size={13} className="text-accent" />
                      {formatEUR(e.new_amount_eur)}
                    </span>
                    <span className="ml-auto shrink-0 rounded-md bg-accent-soft px-2 py-0.5 text-[11px] font-medium text-accent-text">
                      省 {t('省 {pct}', { pct: e.drop_pct != null ? `${e.drop_pct.toFixed(1)}%` : "—" })}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>

      {/* 第三行：单品生命周期走势 */}
      <div className="rounded-lg border border-border bg-surface">
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border px-4 py-2.5">
          <h2 className="flex items-center gap-2 text-sm font-semibold text-fg">
            <LineIcon size={16} className="text-accent" />
            {t('产品生命周期价格走势')}
            <span className="text-[12px] font-normal text-muted">
              （{t(PRICE_TYPE_LABEL[focusTier])} · {t('跨渠道')} EUR）
            </span>
          </h2>
          <select
            value={trendModelId ?? ""}
            onChange={(ev) => setTrendModelId(ev.target.value)}
            className="rounded-md border border-border bg-surface px-2 py-1 text-[12px] text-fg-2 outline-none"
          >
            {models.map((m) => (
              <option key={m.id} value={m.id}>
                {m.brand ? `${m.brand} ` : ""}
                {m.marketing_code}
              </option>
            ))}
          </select>
        </div>
        <div className="p-3">
          {trendQ.isLoading ? (
            <div className="flex h-[280px] items-center justify-center text-[13px] text-muted">
              {t('加载走势…')}
            </div>
          ) : chartData.length === 0 ? (
            <EmptyState
              icon={<LineIcon size={18} />}
              title={t('暂无走势数据')}
              description={t('该机型在当前价格类型下尚未抓到足够的历史价格点（需 ≥2 个日期）。')}
            />
          ) : (
            <div style={{ height: 300 }}>
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
                    tickFormatter={(v: number) => `€${Math.round(v)}`}
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
                      formatEUR(value),
                      name,
                    ]}
                  />
                  <Legend
                    wrapperStyle={{ fontSize: 11, color: "var(--muted)" }}
                  />
                  {plotChannels.map((ch, idx) => (
                    <Line
                      key={ch}
                      type="monotone"
                      dataKey={ch}
                      name={ch}
                      stroke={CHART_COLORS[idx % CHART_COLORS.length]}
                      strokeWidth={1.8}
                      dot={false}
                      activeDot={{ r: 3 }}
                      connectNulls
                      isAnimationActive={false}
                    />
                  ))}
                </LineChart>
              </ResponsiveContainer>
            </div>
          )}
        </div>
      </div>
    </section>
  );
}

const PRICE_TYPE_LABEL: Record<PriceType, string> = {
  unlocked: "裸机价",
  contract_monthly: "合约月费",
  subsidy_down_payment: "补贴首付",
};

// 深浅主题均可见的折线调色板
const CHART_COLORS = [
  "#2f9e6e",
  "#e0792b",
  "#3b82f6",
  "#a855f7",
  "#ef4444",
  "#14b8a6",
  "#eab308",
  "#ec4899",
  "#6366f1",
  "#64748b",
];
