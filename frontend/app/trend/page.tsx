"use client";

import { useEffect, useMemo, useState, Fragment } from "react";
import { useQueries, useQuery } from "@tanstack/react-query";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from "recharts";
import {
  LineChart as LineIcon,
  Search,
  Layers,
  GitBranch,
  X,
} from "lucide-react";
import { AppShell } from "@/components/layout/AppShell";
import { getModelTrend, getChannels, getModels } from "@/lib/api";
import {
  type ModelTrend,
  type ModelTrendChannel,
  type Channel,
  type ChannelType,
} from "@/lib/types";
import { formatEUR } from "@/lib/format";
import { cn } from "@/lib/cn";
import { useI18n } from "@/lib/i18n";

const MAX_MODELS = 4;
const PALETTE = [
  "#22a6b4",
  "#e0a93b",
  "#d9694e",
  "#7c9c3f",
  "#9b6bd6",
  "#4f8fd6",
  "#d667a8",
  "#5bb89a",
  "#c9772f",
  "#8892a0",
];

function fmtDate(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return `${d.getMonth() + 1}-${d.getDate()}`;
}

function median(vals: number[]): number {
  if (!vals.length) return NaN;
  const s = [...vals].sort((a, b) => a - b);
  const n = s.length;
  return n % 2 ? s[(n - 1) / 2] : (s[n / 2 - 1] + s[n / 2]) / 2;
}

function inRange(ts: number, now: number, rangeDays: number): boolean {
  if (!rangeDays) return true;
  return ts >= now - rangeDays * 86400000;
}

export default function TrendPage() {
  const { t } = useI18n();
  const [tab, setTab] = useState<"market" | "operator">("market");
  const [view, setView] = useState<"band" | "channels">("band");
  const [rangeDays, setRangeDays] = useState<number>(90);
  const [query, setQuery] = useState("");
  const [selectedModels, setSelectedModels] = useState<string[]>([]);
  const [selectedChannels, setSelectedChannels] = useState<string[]>([]);

  const priceType = tab === "market" ? "unlocked" : "subsidy_down_payment";

  const modelsQ = useQuery({
    queryKey: ["models-list"],
    queryFn: () => getModels({ limit: 1000 }),
  });
  const channelsQ = useQuery({
    queryKey: ["channels-list"],
    queryFn: () => getChannels({ limit: 1000 }),
  });

  // 渠道名 -> 类型 / 国家
  const channelMeta = useMemo(() => {
    const m = new Map<string, Channel>();
    (channelsQ.data ?? []).forEach((c) => m.set(c.name, c));
    return m;
  }, [channelsQ.data]);

  const modelMeta = useMemo(() => {
    const m = new Map<string, { name: string; brand?: string }>();
    (modelsQ.data ?? []).forEach((x) =>
      m.set(x.id, { name: x.display_name ?? x.id, brand: x.brand }),
    );
    return m;
  }, [modelsQ.data]);

  // 默认选中首个机型
  useEffect(() => {
    if (!modelsQ.data?.length) return;
    setSelectedModels((prev) => (prev.length ? prev : [modelsQ.data![0].id]));
  }, [modelsQ.data]);

  const trendQueries = useQueries({
    queries: selectedModels.map((mid) => ({
      queryKey: ["model-trend", mid, priceType] as const,
      queryFn: () => getModelTrend({ model_id: mid, price_type: priceType }),
      enabled: !!mid,
    })),
  });

  const trendByModel = useMemo(() => {
    const m = new Map<string, ModelTrend>();
    selectedModels.forEach((mid, i) => {
      const d = trendQueries[i]?.data;
      if (d) m.set(mid, d);
    });
    return m;
  }, [selectedModels, trendQueries]);

  const primaryModel = selectedModels[0];
  const primaryTrend = primaryModel ? trendByModel.get(primaryModel) : undefined;

  // 当前 tab 下、首机型有数据的渠道（用于叠加模式选择）
  const channelsForPrimary = useMemo(() => {
    if (!primaryTrend) return [] as ModelTrendChannel[];
    return primaryTrend.channels
      .filter((c) => channelMeta.get(c.channel)?.type === tab)
      .sort((a, b) => b.points.length - a.points.length);
  }, [primaryTrend, channelMeta, tab]);

  // 默认叠加渠道：最低价渠道 + 数据点最多的 2 个
  function defaultChannels(): string[] {
    if (!primaryTrend) return [];
    const typeChs = primaryTrend.channels.filter(
      (c) => channelMeta.get(c.channel)?.type === tab,
    );
    const now = Date.now();
    const latest = new Map<string, number>();
    for (const c of typeChs) {
      const pts = c.points
        .filter((p) => inRange(new Date(p.ts).getTime(), now, rangeDays))
        .sort(
          (a, b) =>
            new Date(b.ts).getTime() - new Date(a.ts).getTime(),
        );
      if (pts[0]) latest.set(c.channel, pts[0].amount_eur ?? pts[0].amount ?? Infinity);
    }
    const lowest = [...latest.entries()].sort((a, b) => a[1] - b[1])[0]?.[0];
    const byCount = [...typeChs]
      .sort((a, b) => b.points.length - a.points.length)
      .map((c) => c.channel)
      .slice(0, 2);
    return Array.from(new Set([lowest, ...byCount].filter(Boolean))).slice(0, 5);
  }

  // 切换机型 / tab 时重置叠加默认选择
  useEffect(() => {
    setSelectedChannels(defaultChannels());
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [primaryModel, tab]);

  // 构建图表数据
  const chartData = useMemo(() => {
    const now = Date.now();
    const rows = new Map<string, Record<string, number | string>>();
    const ensure = (date: string, ts: number) => {
      if (!rows.has(date)) rows.set(date, { date, ts });
      return rows.get(date)!;
    };

    // 价格带：每机型 最低/中位/最高
    if (view === "band") {
      selectedModels.forEach((mid) => {
        const t = trendByModel.get(mid);
        if (!t) return;
        const byDate = new Map<string, { ts: number; vals: number[] }>();
        for (const c of t.channels) {
          if (channelMeta.get(c.channel)?.type !== tab) continue;
          for (const p of c.points) {
            const v = p.amount_eur ?? p.amount;
            if (v == null) continue;
            const ts = new Date(p.ts).getTime();
            if (!inRange(ts, now, rangeDays)) continue;
            const d = p.date || fmtDate(p.ts);
            if (!byDate.has(d)) byDate.set(d, { ts, vals: [] });
            byDate.get(d)!.vals.push(v);
          }
        }
        for (const [d, o] of byDate) {
          const sorted = [...o.vals].sort((a, b) => a - b);
          const row = ensure(d, o.ts);
          row[`${mid}__min`] = sorted[0];
          row[`${mid}__med`] = median(sorted);
          row[`${mid}__max`] = sorted[sorted.length - 1];
        }
      });
    } else if (primaryTrend) {
      // 叠加：仅首机型的选中渠道
      for (const c of primaryTrend.channels) {
        if (channelMeta.get(c.channel)?.type !== tab) continue;
        if (!selectedChannels.includes(c.channel)) continue;
        for (const p of c.points) {
          const v = p.amount_eur ?? p.amount;
          if (v == null) continue;
          const ts = new Date(p.ts).getTime();
          if (!inRange(ts, now, rangeDays)) continue;
          const d = p.date || fmtDate(p.ts);
          ensure(d, ts)[c.channel] = v;
        }
      }
    }

    return Array.from(rows.values()).sort(
      (a, b) => (a.ts as number) - (b.ts as number),
    );
  }, [view, selectedModels, primaryTrend, trendByModel, channelMeta, tab, rangeDays, selectedChannels]);

  const isLoading = trendQueries.some((q) => q.isLoading);
  const isError = trendQueries.some((q) => q.isError);

  const filteredModels = useMemo(() => {
    const all = modelsQ.data ?? [];
    if (!query.trim()) return all;
    const q = query.toLowerCase();
    return all.filter((m) =>
      (m.display_name ?? "").toLowerCase().includes(q),
    );
  }, [modelsQ.data, query]);

  const tabLabel = tab === "market" ? t("公开市场") : t("运营商");
  const priceTypeLabel = tab === "market" ? t("裸机价") : t("设备融资总价");

  return (
    <AppShell>
      <div className="mx-auto max-w-[1200px] px-4 py-5">
        {/* 标题 */}
        <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
            <h1 className="flex items-center gap-2 text-lg font-semibold text-fg">
              <LineIcon size={18} className="text-accent" />
              {t('价格趋势')}
            </h1>
            <span className="text-[12px] text-muted">
              {t('渠道价走势 · {tab} · {pt}（EUR 归一）', { tab: tabLabel, pt: priceTypeLabel })}
            </span>
        </div>

        {/* 控制条 */}
        <div className="mb-4 flex flex-wrap items-center gap-2">
          {/* 分流 tab */}
          <div className="flex overflow-hidden rounded-md border border-border">
              {(["market", "operator"] as const).map((tabKey) => (
                <button
                  key={tabKey}
                  onClick={() => setTab(tabKey)}
                  className={cn(
                    "px-3 py-1.5 text-[13px] font-medium transition-colors duration-fast",
                    tab === tabKey
                      ? "bg-accent text-white"
                      : "bg-surface text-fg-2 hover:bg-surface-warm",
                  )}
                >
                  {tabKey === "market" ? t("公开市场") : t("运营商")}
                </button>
              ))}
          </div>

          {/* 视图模式 */}
          <div className="flex overflow-hidden rounded-md border border-border">
            {(
              [
                ["band", "价格带", Layers],
                ["channels", "单渠道对比", GitBranch],
              ] as const
            ).map(([v, lbl, Icon]) => (
              <button
                key={v}
                onClick={() => setView(v)}
                className={cn(
                  "flex items-center gap-1.5 px-3 py-1.5 text-[13px] font-medium transition-colors duration-fast",
                  view === v
                    ? "bg-accent-soft text-accent-text"
                    : "bg-surface text-fg-2 hover:bg-surface-warm",
                )}
              >
                <Icon size={14} />
                {t(lbl)}
              </button>
            ))}
          </div>

          {/* 时间区间 */}
          <div className="flex overflow-hidden rounded-md border border-border">
            {([30, 60, 90, 0] as const).map((r) => (
              <button
                key={r}
                onClick={() => setRangeDays(r)}
                className={cn(
                  "px-2.5 py-1.5 text-[12px] font-medium transition-colors duration-fast",
                  rangeDays === r
                    ? "bg-surface-warm text-accent-text"
                    : "bg-surface text-fg-2 hover:bg-surface-warm",
                )}
              >
                {r === 0 ? t("全部") : t("{n}天", { n: r })}
              </button>
            ))}
          </div>
        </div>

        {/* 机型选择 */}
        <div className="mb-3 rounded-lg border border-border bg-surface p-3">
          <div className="mb-2 flex items-center gap-2">
            <Search size={14} className="text-muted" />
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder={t('搜索机型…')}
              className="h-7 w-48 rounded-md border border-border bg-surface-warm pl-2 pr-2 text-[13px] text-fg outline-none focus:border-accent"
            />
            <span className="text-[11px] text-muted">
              {t('已选 {n}/{max}', { n: selectedModels.length, max: MAX_MODELS })}
            </span>
          </div>
          <div className="flex max-h-[92px] flex-wrap gap-1.5 overflow-y-auto">
            {filteredModels.map((m) => {
              const id = m.id;
              const sel = selectedModels.includes(id);
              const full = selectedModels.length >= MAX_MODELS && !sel;
              return (
                <button
                  key={id}
                  disabled={full}
                  onClick={() =>
                    setSelectedModels((prev) =>
                      sel
                        ? prev.filter((x) => x !== id)
                        : prev.length >= MAX_MODELS
                          ? prev
                          : [...prev, id],
                    )
                  }
                  className={cn(
                    "rounded-md border px-2.5 py-1 text-[12px] transition-colors duration-fast",
                    sel
                      ? "border-accent bg-accent-soft text-accent-text"
                      : full
                        ? "cursor-not-allowed border-border bg-surface-warm text-meta"
                        : "cursor-pointer border-border bg-surface text-fg-2 hover:bg-surface-warm",
                  )}
                >
                  {m.display_name ?? id}
                </button>
              );
            })}
          </div>
        </div>

        {/* 渠道多选（仅单渠道对比模式） */}
        {view === "channels" && (
          <div className="mb-3 rounded-lg border border-border bg-surface p-3">
            <div className="mb-2 flex items-center justify-between">
              <span className="text-[12px] font-medium text-fg-2">
                {t('叠加渠道（{tab} · 仅显示首机型「{name}」）', { tab: tabLabel, name: modelMeta.get(primaryModel ?? "")?.name ?? "—" })}
              </span>
              <button
                onClick={() => setSelectedChannels(defaultChannels())}
                className="text-[11px] text-accent hover:underline"
              >
                {t('重置为默认（最低价 + 主要渠道）')}
              </button>
            </div>
            <div className="flex flex-wrap gap-1.5">
              {channelsForPrimary.map((c) => {
                const sel = selectedChannels.includes(c.channel);
                return (
                  <button
                    key={c.channel}
                    onClick={() =>
                      setSelectedChannels((prev) =>
                        sel
                          ? prev.filter((x) => x !== c.channel)
                          : [...prev, c.channel],
                      )
                    }
                    className={cn(
                      "flex items-center gap-1 rounded-md border px-2 py-1 text-[12px] transition-colors duration-fast",
                      sel
                        ? "border-accent bg-accent-soft text-accent-text"
                        : "border-border bg-surface text-fg-2 hover:bg-surface-warm",
                    )}
                  >
                    {sel && <X size={12} />}
                    {c.channel}
                    <span className="text-[10px] text-meta">{c.points.length}</span>
                  </button>
                );
              })}
              {channelsForPrimary.length === 0 && (
                <span className="text-[12px] text-muted">{t('该机型在此渠道类型下暂无数据')}</span>
              )}
            </div>
          </div>
        )}

        {/* 图例 */}
        <div className="mb-2 flex flex-wrap gap-x-4 gap-y-1.5 px-1">
          {view === "band"
            ? selectedModels.map((mid, i) => {
                const color = PALETTE[i % PALETTE.length];
                const name = modelMeta.get(mid)?.name ?? mid;
                return (
                  <span key={mid} className="flex items-center gap-1.5 text-[11px] text-fg-2">
                    <span className="inline-block h-2.5 w-3 rounded-sm" style={{ background: color }} />
                    {name}
                    <span className="text-[10px] text-meta">{t('· 中位')}</span>
                  </span>
                );
              })
            : selectedChannels.map((ch, i) => (
                <span key={ch} className="flex items-center gap-1.5 text-[11px] text-fg-2">
                  <span
                    className="inline-block h-2.5 w-3 rounded-sm"
                    style={{ background: PALETTE[i % PALETTE.length] }}
                  />
                  {ch}
                </span>
              ))}
        </div>

        {/* 图表 */}
        <div className="rounded-lg border border-border bg-surface p-2">
          {selectedModels.length === 0 ? (
              <div className="flex h-[320px] items-center justify-center text-[13px] text-muted">
                {t('请选择至少一个机型')}
              </div>
          ) : isLoading ? (
              <div className="flex h-[320px] items-center justify-center text-[13px] text-muted">
                {t('加载价格历史…')}
              </div>
          ) : isError ? (
              <div className="flex h-[320px] items-center justify-center text-[13px] text-danger">
                {t('趋势数据获取失败，请稍后重试')}
              </div>
          ) : chartData.length === 0 ? (
              <div className="flex h-[320px] items-center justify-center text-[13px] text-muted">
                {t('所选机型在当前区间（{tab}）暂无历史价格点', { tab: tabLabel })}
              </div>
          ) : (
            <div style={{ height: 360 }}>
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={chartData} margin={{ top: 8, right: 14, bottom: 4, left: 4 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="var(--border-soft)" vertical={false} />
                  <XAxis
                    dataKey="date"
                    stroke="var(--border)"
                    tick={{ fill: "var(--muted)", fontSize: 11 }}
                    tickLine={false}
                    minTickGap={24}
                  />
                  <YAxis
                    stroke="var(--border)"
                    tick={{ fill: "var(--muted)", fontSize: 11 }}
                    tickLine={false}
                    width={52}
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
                    formatter={(value: number, name: string) => {
                      const m = name.match(/^(.+)__(min|med|max)$/);
                      if (m) {
                        const lbl = t(({ min: "最低", med: "中位", max: "最高" } as Record<string, string>)[m[2]]);
                        return [formatEUR(value), t("{name} · {lbl}", { name: modelMeta.get(m[1])?.name ?? m[1], lbl })];
                      }
                      return [formatEUR(value), name];
                    }}
                  />
                  {view === "band"
                    ? selectedModels.map((mid, i) => {
                        const color = PALETTE[i % PALETTE.length];
                        return (
                          <Fragment key={mid}>
                            <Line
                              type="monotone"
                              dataKey={`${mid}__min`}
                              stroke={color}
                              strokeOpacity={0.5}
                              strokeWidth={1}
                              strokeDasharray="4 2"
                              dot={false}
                              connectNulls
                              isAnimationActive={false}
                            />
                            <Line
                              type="monotone"
                              dataKey={`${mid}__med`}
                              stroke={color}
                              strokeWidth={2.5}
                              dot={false}
                              connectNulls
                              isAnimationActive={false}
                            />
                            <Line
                              type="monotone"
                              dataKey={`${mid}__max`}
                              stroke={color}
                              strokeOpacity={0.5}
                              strokeWidth={1}
                              strokeDasharray="4 2"
                              dot={false}
                              connectNulls
                              isAnimationActive={false}
                            />
                          </Fragment>
                        );
                      })
                    : selectedChannels.map((ch, i) => (
                        <Line
                          key={ch}
                          type="monotone"
                          dataKey={ch}
                          stroke={PALETTE[i % PALETTE.length]}
                          strokeWidth={2}
                          dot={false}
                          connectNulls
                          isAnimationActive={false}
                        />
                      ))}
                </LineChart>
              </ResponsiveContainer>
            </div>
          )}
        </div>

        {/* 说明 */}
        <p className="mt-3 text-[12px] leading-relaxed text-muted">
          {t('公开市场展示一次性裸机价、运营商展示设备融资总价，二者量纲不同故强制分流、不混比。')}
          {t('「价格带」模式用每机型的 最低/中位/最高 三条汇总线概括全部渠道走势，避免线条过密；')}
          {t('需要看具体渠道时切到「单渠道对比」并勾选渠道（默认已预选最低价渠道与主要渠道）。')}
        </p>
      </div>
    </AppShell>
  );
}
