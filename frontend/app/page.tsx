"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import {
  Home,
  LayoutDashboard,
  Columns3,
  BarChart3,
  LineChart as LineChartIcon,
  Bell,
  SlidersHorizontal,
  MessageSquare,
  RefreshCw,
  ArrowRight,
  Activity,
  TrendingUp,
  TrendingDown,
  AlertTriangle,
  Heart,
  Plus,
  X,
  Scale,
  type LucideIcon,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { AppShell } from "@/components/layout/AppShell";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { getSummary, getChannels, getAlerts, getLastCrawl, getPricesLatest, getModelMappings, triggerCrawl } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import type { DashboardSummary, Channel, AlertEvent, PriceLatest, ModelCompetitorMapping } from "@/lib/types";

interface ModuleEntry {
  href: string;
  label: string;
  desc: string;
  icon: LucideIcon;
  accent: string;
}

const MODULES: ModuleEntry[] = [
  { href: "/monitor", label: "价格监控", desc: "实时竞品价格矩阵与渠道覆盖", icon: LayoutDashboard, accent: "bg-accent/15 text-accent" },
  { href: "/compare", label: "参数对比", desc: "机型规格逐条对照", icon: Columns3, accent: "bg-sky-500/15 text-sky-400" },
  { href: "/chips", label: "芯片天梯图", desc: "SoC 性能梯队", icon: BarChart3, accent: "bg-violet-500/15 text-violet-400" },
  { href: "/trend", label: "价格趋势", desc: "历史走势与促销回溯", icon: LineChartIcon, accent: "bg-emerald-500/15 text-emerald-400" },
  { href: "/alerts", label: "告警中心", desc: "价格异动与阈值提醒", icon: Bell, accent: "bg-amber-500/15 text-amber-400" },
  { href: "/config", label: "配置", desc: "渠道、机型与抓取任务", icon: SlidersHorizontal, accent: "bg-slate-500/15 text-slate-300" },
  { href: "/feedback", label: "我要反馈", desc: "问题上报与需求建议", icon: MessageSquare, accent: "bg-rose-500/15 text-rose-400" },
];

function fmtDateTime(s?: string | null) {
  if (!s) return "—";
  const d = new Date(s);
  if (isNaN(d.getTime())) return s;
  return d.toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
}

function KpiCard({ label, value, sub, tone }: { label: string; value: string; sub?: string; tone?: "up" | "down" }) {
  return (
    <div className="rounded-xl border border-border bg-surface p-4">
      <p className="text-[11px] text-meta tracking-caps">{label}</p>
      <p className="mt-1.5 text-2xl font-semibold text-fg whitespace-nowrap">{value}</p>
      {sub && (
        <p className={cnTone(tone)}>{sub}</p>
      )}
    </div>
  );
}

function cnTone(tone?: "up" | "down") {
  if (tone === "up") return "mt-1 text-[11px] text-rose-400";
  if (tone === "down") return "mt-1 text-[11px] text-emerald-400";
  return "mt-1 text-[11px] text-meta";
}

function fmtEur(v?: number | null) {
  if (v == null || isNaN(v)) return "—";
  return "€" + Math.round(v).toLocaleString("en-US");
}

function freshness(
  t: (s: string) => string,
  lastCrawlAt?: string | null,
  status?: string | null,
  health?: string | null,
) {
  const hrs = lastCrawlAt
    ? (Date.now() - new Date(lastCrawlAt).getTime()) / 3.6e6
    : Infinity;
  // 后端按「真实抓取结果 + 价格方差」算出的渠道健康优先于运行态：
  // degraded = 同渠道多机型价格完全相同（静默假阳性，如 Vodafone RO 2600 类）；
  // down = 最近一次抓取失败；unknown = 从未抓取。这三态直接判异常。
  if (health === "down") return { text: "抓取失败", tone: "bad" as const, hrs };
  if (health === "degraded") return { text: "数据异常", tone: "bad" as const, hrs };
  if (health === "unknown") return { text: "未知", tone: "bad" as const, hrs };
  // 无抓取记录：若已知最近一次运行失败，则标「抓取失败」，否则「从未」。
  if (!lastCrawlAt) {
    if (status === "failed") return { text: t("抓取失败"), tone: "bad" as const, hrs: Infinity };
    return { text: t("从未"), tone: "bad" as const, hrs: Infinity };
  }
  // 抓取运行本身的状态优先于按时间推算的新鲜度：
  // failed = 最近一次跑挂了；partial = 部分 SKU 失败；二者都直接反映爬虫健康。
  if (status === "failed") return { text: t("抓取失败"), tone: "bad" as const, hrs };
  if (status === "partial") return { text: t("部分失败"), tone: "warn" as const, hrs };
  if (hrs > 72) return { text: t("停滞"), tone: "bad" as const, hrs };
  if (hrs > 24) return { text: t("偏旧"), tone: "warn" as const, hrs };
  return { text: t("正常"), tone: "ok" as const, hrs };
}

const TONE_DOT: Record<string, string> = {
  ok: "bg-emerald-400",
  warn: "bg-amber-400",
  bad: "bg-rose-400",
};
const TONE_TXT: Record<string, string> = {
  ok: "text-emerald-400",
  warn: "text-amber-400",
  bad: "text-rose-400",
};

function ago(t: (s: string) => string, hrs: number) {
  if (!isFinite(hrs)) return t("从未抓取");
  if (hrs < 1) return Math.round(hrs * 60) + " 分钟前";
  if (hrs < 48) return Math.round(hrs) + " 小时前";
  return Math.round(hrs / 24) + " 天前";
}

export default function WorkbenchPage() {
  const { t } = useI18n();
  const qc = useQueryClient();

  const summaryQ = useQuery<DashboardSummary>({ queryKey: ["workbench", "summary"], queryFn: getSummary });
  const channelsQ = useQuery<Channel[]>({ queryKey: ["workbench", "channels"], queryFn: () => getChannels() });
  const alertsQ = useQuery<AlertEvent[]>({ queryKey: ["workbench", "alerts"], queryFn: () => getAlerts({ limit: 5 }) });
  const lastCrawlQ = useQuery({ queryKey: ["workbench", "lastcrawl"], queryFn: getLastCrawl });

  const pricesQ = useQuery<PriceLatest[]>({ queryKey: ["workbench", "prices"], queryFn: () => getPricesLatest() });
  const mappingsQ = useQuery<ModelCompetitorMapping[]>({ queryKey: ["workbench", "mappings"], queryFn: () => getModelMappings() });

  // ---- 个人关注清单（localStorage，纯前端） ----
  const WATCH_KEY = "pm-watchlist";
  const [watch, setWatch] = useState<string[]>([]);
  useEffect(() => {
    try {
      const raw = localStorage.getItem(WATCH_KEY);
      if (raw) setWatch(JSON.parse(raw));
    } catch { /* ignore */ }
  }, []);
  const toggleWatch = (name: string) => {
    setWatch((prev) => {
      const next = prev.includes(name) ? prev.filter((n) => n !== name) : [...prev, name];
      try { localStorage.setItem(WATCH_KEY, JSON.stringify(next)); } catch { /* ignore */ }
      return next;
    });
  };

  const demobrandModels = useMemo(() => {
    const set = new Set<string>();
    (pricesQ.data ?? []).forEach((p) => { if (p.is_target && p.model) set.add(p.model); });
    return Array.from(set).sort();
  }, [pricesQ.data]);

  const watchRows = useMemo(() => {
    const best = new Map<string, PriceLatest>();
    (pricesQ.data ?? []).forEach((p) => {
      if (!watch.includes(p.model ?? "")) return;
      if (p.amount_eur == null) return;
      const cur = best.get(p.model!);
      if (!cur || cur.amount_eur == null || p.amount_eur < cur.amount_eur) best.set(p.model!, p);
    });
    return watch.map((name) => ({ name, row: best.get(name) }));
  }, [pricesQ.data, watch]);

  // ---- 渠道抓取健康 ----
  const health = useMemo(() => {
    const items = (channelsQ.data ?? []).map((c) => {
      const f = freshness(t, c.last_crawl_at, c.last_crawl_status, c.health);
      return { id: c.id, name: c.name, country: c.country, type: c.type, f };
    });
    const bad = items.filter((i) => i.f.tone === "bad").length;
    const warn = items.filter((i) => i.f.tone === "warn").length;
    return { items, bad, warn, total: items.length };
  }, [channelsQ.data, t]);

  // ---- 对标价差（DemoBrand vs 竞品主对位） ----
  const spreadRows = useMemo(() => {
    const ms = (mappingsQ.data ?? []).filter(
      (m) => m.position === 0 && m.model_display_name && m.competitor_display_name,
    );
    const out: { demobrand: string; comp: string; hMin: number; cMin: number; diff: number }[] = [];
    for (const m of ms.slice(0, 6)) {
      const hVals = (pricesQ.data ?? []).filter((p) => p.model === m.model_display_name).map((p) => p.amount_eur ?? Infinity);
      const cVals = (pricesQ.data ?? []).filter((p) => p.model === m.competitor_display_name).map((p) => p.amount_eur ?? Infinity);
      const hMin = Math.min(...hVals);
      const cMin = Math.min(...cVals);
      if (!isFinite(hMin) || !isFinite(cMin)) continue;
      out.push({
        demobrand: m.model_display_name!,
        comp: `${m.competitor_brand ?? ""} ${m.competitor_display_name}`.trim(),
        hMin, cMin, diff: cMin - hMin,
      });
    }
    return out;
  }, [pricesQ.data, mappingsQ.data]);

  const onTrigger = async () => {
    try {
      await triggerCrawl();
      qc.invalidateQueries({ queryKey: ["workbench"] });
    } catch {
      /* 后端会返回错误信息，这里静默避免噪音 */
    }
  };

  const s = summaryQ.data;
  const operatorCount = channelsQ.data?.filter((c) => c.type === "operator").length ?? 0;
  const marketCount = channelsQ.data?.filter((c) => c.type === "market").length ?? 0;

  return (
    <AppShell>
      <div className="mx-auto max-w-6xl px-4 py-6 sm:px-6">
        {/* 顶部问候 + 快捷操作 */}
        <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <h1 className="text-xl font-semibold text-fg">{t("工作台")}</h1>
            <p className="mt-1 text-[12px] text-meta">
              {t("东北欧四国竞品价格中枢")} · {t("最近抓取")} {fmtDateTime(lastCrawlQ.data?.last_finished_at ?? s?.last_crawl_at)}
            </p>
          </div>
          <Button onClick={onTrigger} className="self-start sm:self-auto">
            <RefreshCw size={15} className="mr-1.5" />
            {t("立即抓取")}
          </Button>
        </div>

        {/* KPI 卡片 */}
        <div className="mt-5 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {summaryQ.isLoading ? (
            Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-[88px] rounded-xl" />)
          ) : (
            <>
              <KpiCard label={t("监控 SKU")} value={String(s?.monitored_skus ?? 0)} sub={t("覆盖渠道") + ` ${channelsQ.data?.length ?? 0}`} />
              <KpiCard label={t("活跃渠道")} value={String(s?.active_channels ?? 0)} sub={`${t("运营商")} ${operatorCount} · ${t("公开市场")} ${marketCount}`} />
              <KpiCard label={t("昨夜价格变动")} value={String(s?.last_night_changes ?? 0)} sub={t("较前一抓取周期")} />
              <KpiCard
                label={t("最大区域价差")}
                value={(s?.max_regional_spread != null ? s.max_regional_spread.toFixed(1) : "0") + "%"}
                sub={s?.spread_model ? `${s.spread_model} · ${s.spread_country_max ?? ""}` : t("暂无数据")}
                tone={s && s.max_regional_spread != null && s.max_regional_spread > 8 ? "up" : undefined}
              />
            </>
          )}
        </div>

        {/* 模块入口网格 */}
        <h2 className="mt-7 text-[13px] font-semibold text-fg-2">{t("功能模块")}</h2>
        <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {MODULES.map((m) => {
            const Icon = m.icon;
            return (
              <Link
                key={m.href}
                href={m.href}
                className="group flex items-start gap-3 rounded-xl border border-border bg-surface p-4 transition-colors duration-fast hover:border-accent/40"
              >
                <span className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-lg ${m.accent}`}>
                  <Icon size={20} />
                </span>
                <div className="min-w-0 flex-1">
                  <p className="flex items-center justify-between text-[14px] font-medium text-fg">
                    {t(m.label)}
                    <ArrowRight size={15} className="text-meta transition-transform duration-fast group-hover:translate-x-0.5 group-hover:text-accent" />
                  </p>
                  <p className="mt-0.5 text-[12px] text-meta">{t(m.desc)}</p>
                </div>
              </Link>
            );
          })}
        </div>

        {/* 渠道抓取健康 */}
        <div className="mt-7 flex items-center justify-between">
          <h2 className="text-[13px] font-semibold text-fg-2">{t("渠道抓取健康")}</h2>
          <span className={`text-[12px] ${health.bad > 0 ? "text-rose-400" : health.warn > 0 ? "text-amber-400" : "text-emerald-400"}`}>
            {health.bad > 0
              ? `${health.bad} / ${health.total} ${t("渠道异常")}`
              : health.warn > 0
                ? `${health.warn} / ${health.total} ${t("渠道偏旧")}`
                : `${health.total} ${t("渠道正常")}`}
          </span>
        </div>
        <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-4">
          {health.items.map((c) => (
            <div key={c.id} className="flex items-center gap-2 rounded-lg border border-border bg-surface px-3 py-2">
              <span className={`h-2 w-2 shrink-0 rounded-full ${TONE_DOT[c.f.tone]}`} />
              <div className="min-w-0 flex-1">
                <p className="truncate text-[12px] text-fg">{c.name}</p>
                <p className={`text-[10px] ${TONE_TXT[c.f.tone]}`}>{c.f.text} · {ago(t, c.f.hrs)}</p>
              </div>
            </div>
          ))}
        </div>

        {/* 我的关注 */}
        <div className="mt-7 flex items-center justify-between">
          <h2 className="text-[13px] font-semibold text-fg-2">{t("我的关注")}</h2>
          <select
            value=""
            onChange={(e) => e.target.value && toggleWatch(e.target.value)}
            className="max-w-[180px] rounded-md border border-border bg-surface-2 px-2 py-1 text-[12px] text-fg"
          >
            <option value="">+ {t("添加关注机型")}</option>
            {demobrandModels.filter((m) => !watch.includes(m)).map((m) => (
              <option key={m} value={m}>{m}</option>
            ))}
          </select>
        </div>
        <div className="mt-3 rounded-xl border border-border bg-surface">
          {watchRows.length === 0 ? (
            <p className="px-4 py-6 text-[13px] text-meta">{t("暂无关注，添加你负责的机型")}</p>
          ) : (
            <ul className="divide-y divide-border">
              {watchRows.map(({ name, row }) => (
                <li key={name} className="flex items-center gap-3 px-4 py-3">
                  <Heart size={16} className="shrink-0 text-accent" />
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-[13px] text-fg">{name}</p>
                    <p className="text-[11px] text-meta">
                      {row?.channel ?? "—"}
                      {row?.delta_pct != null ? (
                        <span className={row.delta_pct <= 0 ? " text-emerald-400" : " text-rose-400"}>
                        {" · "}{row.delta_pct > 0 ? "+" : ""}{row.delta_pct.toFixed(1)}%
                        </span>
                      ) : null}
                    </p>
                  </div>
                  <span className="shrink-0 text-[14px] font-semibold text-fg whitespace-nowrap">{fmtEur(row?.amount_eur)}</span>
                  <button
                    onClick={() => toggleWatch(name)}
                    aria-label={t("取消")}
                    className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-meta hover:bg-surface-warm hover:text-fg"
                  >
                    <X size={14} />
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>

        {/* 对标价差 */}
        <div className="mt-7 flex items-center justify-between">
          <h2 className="text-[13px] font-semibold text-fg-2">{t("对标价差")}</h2>
          <Link href="/compare" className="text-[12px] text-accent hover:underline">{t("查看完整对标")}</Link>
        </div>
        <div className="mt-3 rounded-xl border border-border bg-surface">
          {spreadRows.length === 0 ? (
            <p className="px-4 py-6 text-[13px] text-meta">{t("暂无对标数据")}</p>
          ) : (
            <ul className="divide-y divide-border">
              {spreadRows.map((r) => {
                const cheaper = r.diff > 0;
                const pct = r.cMin ? (r.diff / r.cMin) * 100 : 0;
                return (
                  <li key={r.demobrand} className="flex items-center gap-3 px-4 py-3">
                    <Scale size={16} className="shrink-0 text-violet-400" />
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-[13px] text-fg">{r.demobrand}</p>
                      <p className="text-[11px] text-meta">vs {r.comp}</p>
                    </div>
                    <div className="shrink-0 text-right">
                      <p className="text-[13px] font-semibold text-fg whitespace-nowrap">{fmtEur(r.hMin)}</p>
                      <p className={`text-[11px] whitespace-nowrap ${cheaper ? "text-emerald-400" : "text-rose-400"}`}>
                        {cheaper ? t("低于竞品") : t("高于竞品")} {fmtEur(Math.abs(r.diff))} ({pct > 0 ? "+" : ""}{pct.toFixed(0)}%)
                      </p>
                    </div>
                  </li>
                );
              })}
            </ul>
          )}
        </div>

        {/* 最近告警 */}
        <div className="mt-7 flex items-center justify-between">
          <h2 className="text-[13px] font-semibold text-fg-2">{t("最近告警")}</h2>
          <Link href="/alerts" className="text-[12px] text-accent hover:underline">{t("查看全部")}</Link>
        </div>
        <div className="mt-3 rounded-xl border border-border bg-surface">
          {alertsQ.isLoading ? (
            <div className="p-4"><Skeleton className="h-16 rounded-lg" /></div>
          ) : alertsQ.data && alertsQ.data.length > 0 ? (
            <ul className="divide-y divide-border">
              {alertsQ.data.map((a) => (
                <li key={a.id} className="flex items-center gap-3 px-4 py-3">
                  <span className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-lg ${a.severity === "critical" ? "bg-rose-500/15 text-rose-400" : "bg-amber-500/15 text-amber-400"}`}>
                    <AlertTriangle size={16} />
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-[13px] text-fg">{a.message ?? a.model}</p>
                    <p className="text-[11px] text-meta">{a.model} · {a.country ?? ""} · {a.channel ?? ""}</p>
                  </div>
                  <span className="shrink-0 text-[11px] text-meta">{fmtDateTime(a.triggered_at)}</span>
                </li>
              ))}
            </ul>
          ) : (
            <div className="flex items-center gap-2 px-4 py-6 text-[13px] text-meta">
              <Activity size={16} /> {t("暂无告警")}
            </div>
          )}
        </div>

        <p className="mt-8 text-center text-[11px] text-meta">
          {t("竞品价格监控平台")} · DemoBrand 600 系列 & V6 · NE EU
        </p>
      </div>
    </AppShell>
  );
}
