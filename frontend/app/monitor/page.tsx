"use client";

import { useEffect, useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  RefreshCw,
  Activity,
  AlertCircle,
  RotateCcw,
  Smartphone,
  Download,
} from "lucide-react";
import { AppShell } from "@/components/layout/AppShell";
import { FilterBar, type PriceMode } from "@/components/dashboard/FilterBar";
import { KpiStrip } from "@/components/dashboard/KpiStrip";
import { ComparisonMatrix } from "@/components/dashboard/ComparisonMatrix";
import { TrendDrill } from "@/components/dashboard/TrendDrill";
import { HistorySection } from "@/components/dashboard/HistorySection";
import { DateSelector } from "@/components/dashboard/DateSelector";
import { Button } from "@/components/ui/button";
import { Skeleton, EmptyState } from "@/components/ui/skeleton";
import {
  getPricesLatest,
  getSummary,
  getModels,
  getModelMappings,
  getSkus,
  getChannels,
  triggerCrawl,
  getLastCrawl,
  createManualPrice,
  getPriceSnapshotByDate,
  type ManualPriceBody,
} from "@/lib/api";
import { getToken } from "@/lib/auth";
import { useI18n } from "@/lib/i18n";
import { buildMatrix } from "@/lib/matrix";
import { buildRivalRows } from "@/lib/rival-matrix";
import { useDebouncedCommit } from "@/lib/use-debounced";
import type { CompetitorRef, ModelRow } from "@/lib/types";
import {
  COUNTRIES,
  type ChannelType,
  type CountryCode,
  type PriceType,
} from "@/lib/types";

const ALL_COUNTRIES = COUNTRIES.map((c) => c.code) as CountryCode[];

// 渠道表只存国家全名（"Romania"/"Czech Republic"），没有 ISO code 列；
// 反查成 CountryCode，否则 countries.includes(全名) 恒为 false，导致这些渠道被注入逻辑跳过。
const COUNTRY_NAME_TO_CODE: Record<string, CountryCode> = Object.fromEntries(
  COUNTRIES.map((c) => [c.name, c.code]),
) as Record<string, CountryCode>;

export default function DashboardPage() {
  const { t } = useI18n();
  const qc = useQueryClient();
  const [countriesInput, countries, setCountries] =
    useDebouncedCommit<CountryCode[]>(ALL_COUNTRIES);
  // 国家清空时回落「全部国家」，避免 countries=[] 导致看板全空（抽风）
  const countriesForQuery = countries.length ? countries : ALL_COUNTRIES;
  const [modelFilterInput, modelFilter, setModelFilter] =
    useDebouncedCommit<string>("all");
  const [priceMode, setPriceMode] = useState<PriceMode>("all");
  // 默认展示渠道原始币种（HUF/RSD/RON/PLN…）：跨市场比较时本地价才是官网口径，
  // EUR 折算仅作换算参考，由用户主动切换。
  const [currency, setCurrency] = useState<"EUR" | "raw">("raw");
  const [selectedModelId, setSelectedModelId] = useState<string | null>(null);
  const [triggerMsg, setTriggerMsg] = useState<string | null>(null);
  const [targetOnly, setTargetOnly] = useState(false);

  // 顶部日期选项：null = 最新（默认跟随最近爬取日）；选中具体日期则整张看板回放该日
  const [selectedDate, setSelectedDate] = useState<string | null>(null);

  // 从告警中心跳转携带 ?model=<id>&country=<code>：自动选中对应产品 + 聚焦该国家，
  // 让看板直接落到该告警对应的产品状态（无需 useSearchParams，避免 Suspense 边界要求）。
  useEffect(() => {
    const sp = new URLSearchParams(window.location.search);
    const m = sp.get("model");
    const c = sp.get("country");
    if (m) setSelectedModelId(m);
    if (c && COUNTRIES.some((x) => x.code === c)) {
      setCountries([c as CountryCode]);
    }
    // 仅首屏读取一次，不随后续 query 变化重跑
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const pricesQ = useQuery({
    queryKey: ["prices-latest"],
    queryFn: () => getPricesLatest(),
  });

  // 选日期回放：锚定某日的「窗口内最新价」快照（复用后端 /prices/by-date，已按
  // 每 (渠道,机型,价格类型) 取 [date-14d, date 23:59:59] 窗口内最新一行，口径与看板一致）。
  const isByDate = !!selectedDate;
  const byDateQ = useQuery({
    queryKey: ["dashboard-by-date", selectedDate],
    queryFn: () => getPriceSnapshotByDate({ date: selectedDate!, limit: 2000, window_days: 60 }),
    enabled: isByDate,
  });
  const summaryQ = useQuery({ queryKey: ["summary"], queryFn: () => getSummary() });
  const modelsQ = useQuery({ queryKey: ["models"], queryFn: () => getModels() });
  const mappingsQ = useQuery({
    queryKey: ["model-mappings"],
    queryFn: () => getModelMappings(),
  });
  const skusQ = useQuery({ queryKey: ["skus"], queryFn: () => getSkus() });
  const channelsQ = useQuery({
    queryKey: ["channels"],
    queryFn: () => getChannels(),
  });

  const filteredPrices = useMemo(() => {
    const all = Array.isArray(pricesQ.data) ? pricesQ.data : [];
    return all.filter((p) => {
      const cc = (p.country_code ?? p.country) as string;
      if (!countriesForQuery.includes(cc as CountryCode)) return false;
      if (modelFilter !== "all" && (p.model_id ?? p.model) !== modelFilter)
        return false;
      return true;
    });
  }, [pricesQ.data, countriesForQuery, modelFilter]);

  const focusTier: PriceType = priceMode === "all" ? "unlocked" : priceMode;
  const rows = useMemo(
    () => buildMatrix(filteredPrices, countries, focusTier),
    [filteredPrices, countries, focusTier],
  );

  // 看板快捷筛选：只看本品牌（DemoBrand）机型
  const visibleRows = useMemo(
    () => (targetOnly ? rows.filter((r) => r.is_target) : rows),
    [rows, targetOnly],
  );

  // 本品牌产品选择器：默认第一个有对位关系的荣耀机型；H600 作为主打SKU置顶。
  const demobrandModels = useMemo(() => {
    const codes = ["H600", "H600Smart", "H600L", "H600P", "MagicV6", "Magic8Lite", "Magic8Pro"];
    const mapped = (modelsQ.data ?? []).filter(
      (m) => m.is_target && (mappingsQ.data ?? []).find((x) => x.model_id === m.id),
    );
    return mapped.sort(
      (a, b) => codes.indexOf(a.marketing_code) - codes.indexOf(b.marketing_code),
    );
  }, [modelsQ.data, mappingsQ.data]);

  // 品牌官方首页（官网按钮在无具体产品页时回落）
  const BRAND_HOME: Record<string, string> = {
    DemoBrand: "https://www.demobrand.com/",
    Samsung: "https://www.samsung.com/",
    Xiaomi: "https://www.mi.com/global/",
  };

  // 机型 id → 机型行，便于取竞品的官方产品页 URL
  const modelsById = useMemo(() => {
    const m = new Map<string, ModelRow>();
    for (const x of modelsQ.data ?? []) m.set(x.id, x);
    return m;
  }, [modelsQ.data]);

  // 选中机型对应的对位竞品（按 position 排序，position=0 为主对位）
  // 对位竞品列：荣耀机型取其竞品；竞品机型反向取其对位荣耀机型作为对比列
  const activeCompetitors: CompetitorRef[] = useMemo(() => {
    if (!selectedModelId) return [];
    const isDemoBrand = demobrandModels.some((m) => m.id === selectedModelId);
    if (isDemoBrand) {
      return (mappingsQ.data ?? [])
        .filter((m) => m.model_id === selectedModelId)
        .sort((a, b) => a.position - b.position)
        .map((m) => {
          const comp = modelsById.get(m.competitor_id);
          const official = comp?.official_url?.trim();
          const brand = comp?.brand ?? "";
          const officialUrl = official || (brand ? BRAND_HOME[brand] ?? null : null);
          return {
            id: m.competitor_id,
            marketing_code: m.competitor_marketing_code ?? "",
            display_name: m.competitor_display_name ?? "",
            brand: m.competitor_brand ?? "",
            position: m.position,
            officialUrl,
          };
        });
    }
    // 非荣耀机型（或荣耀机型但尚未建立对位关系）→ 单品模式：
    // 只看这一个产品在各渠道的价格，不再拼荣耀对比列、也不显示「荣耀 vs X」竞争力列。
    // （旧逻辑会反向拉荣耀机型当对比列，用户明确要求不再出现。）
    return [];
  }, [mappingsQ.data, selectedModelId, modelsById, demobrandModels]);

  const demobrandCode = useMemo(
    () =>
      demobrandModels.find((m) => m.id === selectedModelId)?.marketing_code ?? "",
    [demobrandModels, selectedModelId],
  );

  // 焦点机型是不是荣耀（本品牌）：决定走「对位竞品矩阵」还是「单品看价」
  const isDemoBrandFocus = useMemo(
    () => demobrandModels.some((m) => m.id === selectedModelId),
    [demobrandModels, selectedModelId],
  );

  // 焦点机型表头文案：荣耀机型显示「荣耀 {code}」，竞品机型显示「{brand} {code}」
  const focusModel = modelsById.get(selectedModelId ?? "");
  const focusCode = focusModel?.marketing_code ?? "";
  const demobrandLabel = focusModel
    ? focusModel.is_target
      ? `荣耀 ${focusCode}`
      : `${focusModel.brand ?? ""} ${focusCode}`.trim()
    : "荣耀";

  // 看板主数据源：默认用「最近爬取日」全量价格池；选日期回放时切换到按日快照。
  // 两种来源都已对齐 14 天窗口口径，下游（KPI 覆盖数 / 14 天去重 / 矩阵）无需分支。
  const basePool = isByDate ? (byDateQ.data ?? []) : pricesQ.data;
  const allPrices = Array.isArray(basePool) ? basePool : [];

  // 仅采用「最近一次爬取日」的价格喂给对比矩阵，不继承历史老价——
  // 否则促销前的旧价（如 DNA Magic8 Lite 原价 399）会一直挂着误导。
  // 基准日 = 价格池里 captured_at 的最大日期（即最近一次成功爬取的运行日）。
  const latestCrawlDate = useMemo(() => {
    let max: string | null = null;
    for (const p of allPrices) {
      const d = p.captured_at ? p.captured_at.slice(0, 10) : null;
      if (d && (!max || d > max)) max = d;
    }
    return max;
  }, [allPrices]);

  // 不再只取「全局最大爬取日」当天的价格——那会让运营商的 subsidy 与 monthly
  // 因异日抓取互相挤掉成「—」（当月供是 08-11 派生、裸机价是 08-09 爬取时，严格
  // 同日过滤会丢掉裸机价）。改为：对每个 (渠道, 机型, 价格类型) 独立取
  // [latestCrawlDate-14d, latestCrawlDate] 窗口内最新一行——与后端
  // app/services/price_excel.py:_price_on_day 的 14 天口径一致。这样既保证
  // 运营商两条腿（裸机价 + 月供）同屏稳定，又保留「>14 天未抓不展示」的意图。
  const CRAWL_WINDOW_DAYS = 60;
  const crawlDayPrices = useMemo(() => {
    if (!latestCrawlDate) return allPrices;
    const maxTs = new Date(latestCrawlDate + "T00:00:00Z").getTime();
    const windowMs = CRAWL_WINDOW_DAYS * 86400000;
    const best = new Map<string, (typeof allPrices)[number]>();
    for (const p of allPrices) {
      const d = p.captured_at ? p.captured_at.slice(0, 10) : null;
      if (!d) continue;
      const rowTs = new Date(d + "T00:00:00Z").getTime();
      const age = maxTs - rowTs;
      if (age < 0 || age > windowMs) continue; // 未来或超出 14 天窗口
      const key = `${p.channel_id}|${p.model_id}|${p.price_type}`;
      const prev = best.get(key);
      if (!prev || (p.captured_at ?? "") > (prev.captured_at ?? "")) {
        best.set(key, p);
      }
    }
    return Array.from(best.values());
  }, [allPrices, latestCrawlDate]);

  // 从全量 skus 构建 (渠道×产品) → 快照，供矩阵富化链接与未上架标记
  const skuMap = useMemo(() => {
    const m = new Map<
      string,
      { sku_id?: string | null; product_url?: string | null; in_stock?: boolean | null; note?: string | null }
    >();
    for (const s of skusQ.data ?? []) {
      if (!s.channel_id || !s.model_id) continue;
      m.set(`${s.channel_id}|${s.model_id}`, {
        sku_id: s.id ?? null,
        product_url: s.product_url ?? null,
        in_stock: s.in_stock ?? null,
        note: s.note ?? null,
      });
    }
    return m;
  }, [skusQ.data]);

  // 渠道 id → 元数据，供矩阵在无价时也带入 skuMap 渠道（Vodafone RO / Datart 等）
  const channelsById = useMemo(() => {
    const m = new Map<
      string,
      {
        name: string;
        type: ChannelType;
        countryCode: CountryCode;
        baseUrl: string | null;
        listingUrl: string | null;
      }
    >();
    for (const c of channelsQ.data ?? []) {
      m.set(c.id, {
        name: c.name,
        type: (c.type === "operator" ? "operator" : "market") as ChannelType,
        countryCode:
          ((c.country_code as CountryCode) ||
            COUNTRY_NAME_TO_CODE[c.country as string] ||
            ("RS" as CountryCode)),
        baseUrl: c.base_url || null,
        listingUrl: null,
      });
    }
    return m;
  }, [channelsQ.data]);

  // 选中机型（用于取官方产品页 URL）
  const selectedModel = useMemo(
    () => (modelsQ.data ?? []).find((m) => m.id === selectedModelId) ?? null,
    [modelsQ.data, selectedModelId],
  );
  // 顶部「官网」按钮：优先厂商官方产品详情页；缺失时回落品牌首页
  const demobrandOfficialUrl = useMemo(() => {
    if (!selectedModel) return null;
    const official = selectedModel.official_url?.trim();
    if (official) return official;
    const brand = selectedModel.brand ?? "";
    return BRAND_HOME[brand] ?? null;
  }, [selectedModel]);

  // 人工补录价格：写回后端后失效价格/概览查询，触发矩阵刷新
  const onManualSave = async (body: ManualPriceBody) => {
    await createManualPrice(body);
    qc.invalidateQueries({ queryKey: ["prices-latest"] });
    qc.invalidateQueries({ queryKey: ["summary"] });
    qc.invalidateQueries({ queryKey: ["dashboard-by-date", selectedDate] });
  };

  // 看板 KPI 动态口径：从实际价格池派生覆盖国家数 / 渠道数，避免写死文案。
  const countryCount = useMemo(
    () =>
      new Set(
        allPrices
          .map((p) => p.country_code ?? p.country)
          .filter((v): v is string => !!v),
      ).size,
    [allPrices],
  );
  const channelCount = useMemo(
    () =>
      new Set(
        allPrices.map((p) => p.channel_id).filter((v): v is string => !!v),
      ).size,
    [allPrices],
  );
  const rivalRows = useMemo(() => {
    // 单品模式（activeCompetitors 为空）也要建行——否则选了竞品机型就一片空白。
    if (!selectedModelId) return [];
    // 只用「最近爬取日」的价格池，避免展示继承的历史老价（可能已过期/促销前）。
    return buildRivalRows(
      crawlDayPrices,
      activeCompetitors,
      selectedModelId,
      countriesForQuery,
      skuMap,
      { channelsById, priceMode },
    );
  }, [
    crawlDayPrices,
    activeCompetitors,
    selectedModelId,
    countriesForQuery,
    skuMap,
    channelsById,
    priceMode,
  ]);

  // 仅在确实未选中时自动选首个可见机型；绝不把已选机型重置为 null（避免清空国家/切机型时抽风）
  useEffect(() => {
    if (!selectedModelId && visibleRows.length > 0) {
      const first =
        visibleRows.find((r) => demobrandModels.some((m) => m.id === r.model_id)) ||
        visibleRows[0];
      setSelectedModelId(first.model_id);
    }
  }, [visibleRows, selectedModelId]);

  // 对位关系加载后，仅在尚未选中时默认落到首个荣耀机型；已选（含竞品焦点）绝不回弹
  useEffect(() => {
    if (mappingsQ.data && demobrandModels.length > 0 && !selectedModelId) {
      setSelectedModelId(demobrandModels[0].id);
      setModelFilter(demobrandModels[0].id);
    }
  }, [mappingsQ.data, demobrandModels, selectedModelId]);

  const onTrigger = async () => {
    setTriggerMsg(null);
    try {
      // 「本日已抓取」守卫：若最近一次成功抓取完成于今天（本地日期），则不再触发。
      try {
        const last = await getLastCrawl();
        if (
          last?.last_finished_at &&
          new Date(last.last_finished_at).toDateString() ===
            new Date().toDateString()
        ) {
          setTriggerMsg(t("本日已抓取"));
          return;
        }
      } catch {
        // 检查失败（如网络错误）时不阻断抓取，继续触发。
      }
      await triggerCrawl();
      setTriggerMsg(t("已触发全量抓取"));
      qc.invalidateQueries({ queryKey: ["prices-latest"] });
      qc.invalidateQueries({ queryKey: ["summary"] });
      qc.invalidateQueries({ queryKey: ["model-mappings"] });
      qc.invalidateQueries({ queryKey: ["dashboard-by-date", selectedDate] });
    } catch (e) {
      setTriggerMsg(e instanceof Error ? e.message : t("触发失败"));
    }
    setTimeout(() => setTriggerMsg(null), 4000);
  };

  const onDownload = async () => {
    setTriggerMsg(null);
    try {
      const token = getToken();
      const base =
        process.env.NEXT_PUBLIC_API_URL === "same-origin"
          ? ""
          : process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
      const res = await fetch(
        `${base}/api/v1/export/price-excel`,
        token ? { headers: { Authorization: `Bearer ${token}` } } : {},
      );
      if (!res.ok) {
        let msg = t("下载失败");
        try {
          const j = await res.json();
          msg = (j && (j.message || j.detail)) || msg;
        } catch {
          /* ignore */
        }
        setTriggerMsg(msg);
        setTimeout(() => setTriggerMsg(null), 4000);
        return;
      }
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "竞品价格表.xlsx";
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
      setTriggerMsg(t("已开始下载"));
    } catch (e) {
      setTriggerMsg(e instanceof Error ? e.message : t("下载失败"));
    }
    setTimeout(() => setTriggerMsg(null), 4000);
  };

  const reload = () => {
    pricesQ.refetch();
    summaryQ.refetch();
    modelsQ.refetch();
    mappingsQ.refetch();
    skusQ.refetch();
    channelsQ.refetch();
    byDateQ.refetch();
  };

  const resetFilters = () => {
    setCountries(ALL_COUNTRIES);
    setModelFilter("all");
    setTargetOnly(false);
  };

  const topRight = (
    <>
      {/* 顶部日期选项：点开弹出日历，选完整张看板回放该日（不常驻日历） */}
      <DateSelector selectedDate={selectedDate} onSelect={setSelectedDate} />
      {triggerMsg && (
        <span className="hidden items-center gap-1 text-[12px] text-accent-text sm:inline-flex">
          <Activity size={14} /> {triggerMsg}
        </span>
      )}
      <Button
        variant="secondary"
        size="sm"
        icon={<RefreshCw size={14} />}
        onClick={() => {
          qc.invalidateQueries({ queryKey: ["prices-latest"] });
          qc.invalidateQueries({ queryKey: ["summary"] });
          qc.invalidateQueries({ queryKey: ["model-mappings"] });
          qc.invalidateQueries({ queryKey: ["dashboard-by-date", selectedDate] });
        }}
      >
        {t('刷新')}
      </Button>
      <Button
        variant="primary"
        size="sm"
        icon={<RefreshCw size={14} />}
        onClick={onTrigger}
      >
        {t('立即抓取')}
      </Button>
      <Button
        variant="secondary"
        size="sm"
        icon={<Download size={14} />}
        onClick={onDownload}
      >
        {t('下载数据')}
      </Button>
    </>
  );

  return (
    <AppShell topRight={topRight}>
      {/* 本品牌产品选择器 */}
      <div className="border-b border-border bg-surface px-5 py-3">
        <div className="flex flex-wrap items-center gap-3">
          <span className="flex items-center gap-1.5 text-[13px] font-medium text-fg">
              <Smartphone size={15} className="text-accent" />
              {t('本品牌产品')}
            </span>
          {mappingsQ.isLoading ? (
            <Skeleton height={32} className="w-60" />
          ) : (
            <div className="flex flex-wrap gap-2">
              {demobrandModels.map((m) => (
                <button
                  key={m.id}
                  onClick={() => {
                    setSelectedModelId(m.id);
                    setModelFilter(m.id);
                  }}
                  className={`
                    rounded-md border px-3 py-1.5 text-[12px] font-medium transition-colors
                    ${
                      selectedModelId === m.id
                        ? "border-accent bg-accent text-white"
                        : "border-border bg-surface-warm text-fg-2 hover:bg-surface"
                    }
                  `}
                >
                  {m.marketing_code}
                </button>
              ))}
            </div>
          )}
          {activeCompetitors.length > 0 ? (
              <span className="text-[11px] text-muted">
              {t('对位：')}
              {activeCompetitors
                .map((c) => `${c.brand} ${c.marketing_code}`)
                .join(" / ")}
            </span>
          ) : selectedModelId && !isDemoBrandFocus ? (
            <span className="text-[11px] text-muted">
              {t('单品模式：仅看该机型各渠道价格，不做荣耀对比')}
            </span>
          ) : null}
        </div>
      </div>

      <FilterBar
        countries={countriesInput}
        onSetCountries={setCountries}
        models={modelsQ.data ?? []}
        modelFilter={modelFilterInput}
        onModelChange={(v: string) => {
          setModelFilter(v);
          // 机型下拉与焦点机型联动：选具体机型（含竞品）即聚焦该机型；选「全部」回落首个荣耀机型
          if (v === "all") {
            if (demobrandModels[0]) setSelectedModelId(demobrandModels[0].id);
          } else {
            setSelectedModelId(v);
          }
        }}
        currency={currency}
        onCurrency={setCurrency}
      />

      <div className="space-y-4 p-5">
        {pricesQ.isError || (isByDate && byDateQ.isError) ? (
          <div className="flex flex-col gap-3 rounded-md border border-danger/20 bg-danger/10 px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
            <div className="flex items-start gap-2">
              <AlertCircle size={16} className="mt-0.5 shrink-0 text-danger" />
              <span className="text-[13px] text-danger">
                {t('数据加载失败，请刷新重试。')}
              </span>
            </div>
            <Button
              variant="secondary"
              size="sm"
              icon={<RefreshCw size={14} />}
              onClick={reload}
            >
              {t('重新加载')}
            </Button>
          </div>
        ) : null}

        {/* KPI 条 */}
        {summaryQ.isLoading || (isByDate && byDateQ.isLoading) ? (
          <div className="grid grid-cols-2 gap-px bg-border lg:grid-cols-4">
            {[0, 1, 2, 3].map((i) => (
              <Skeleton key={i} height={64} />
            ))}
          </div>
        ) : (
          <KpiStrip
            summary={summaryQ.data}
            countryCount={countryCount}
            channelCount={channelCount}
          />
        )}

        {/* 对比矩阵 */}
        {pricesQ.isLoading || (isByDate && byDateQ.isLoading) ? (
          <div className="rounded-lg border border-border bg-surface p-4">
            <Skeleton height={28} className="mb-3 w-48" />
            <Skeleton height={320} />
          </div>
        ) : !selectedModelId ? (
          <EmptyState
            icon={<AlertCircle size={18} />}
            title={t('未选择产品')}
            description={t('请在上方选择一款机型查看其各渠道价格。')}
          />
        ) : rivalRows.length === 0 ? (
          <EmptyState
            icon={<AlertCircle size={18} />}
            title={t('暂无对位数据')}
            description={t('当前选择的产品在筛选国家下暂无渠道价格。请调整国家筛选或点击「立即抓取」。')}
            action={
              <Button
                variant="secondary"
                size="sm"
                icon={<RotateCcw size={14} />}
                onClick={resetFilters}
              >
                {t('重置筛选')}
              </Button>
            }
          />
        ) : (
          <ComparisonMatrix
            rows={rivalRows}
            competitors={activeCompetitors}
            demobrandCode={demobrandCode}
            demobrandModelId={selectedModelId ?? null}
            demobrandLabel={demobrandLabel}
            currency={currency}
            demobrandOfficialUrl={demobrandOfficialUrl}
            onManualSave={onManualSave}
          />
        )}

        {/* 趋势下钻 */}
        <TrendDrill
          prices={filteredPrices}
          rows={visibleRows}
          modelId={selectedModelId}
          countries={countriesForQuery}
          priceMode={priceMode}
          currency={currency}
        />

        {/* 价格历史 / 日历 / 促销 / 生命周期（跟随顶部日期） */}
        <HistorySection
          models={modelsQ.data ?? []}
          priceMode={priceMode}
          currency={currency}
          selectedDate={selectedDate}
          onSelectDate={setSelectedDate}
          snapshotRows={crawlDayPrices}
          snapshotLoading={isByDate ? byDateQ.isLoading : pricesQ.isLoading}
        />
      </div>
    </AppShell>
  );
}
