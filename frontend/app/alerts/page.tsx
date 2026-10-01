"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Bell, ListFilter, RefreshCw } from "lucide-react";
import { AppShell } from "@/components/layout/AppShell";
import {
  AlertFilter,
  DEFAULT_ALERT_FILTER,
  type AlertFilterState,
} from "@/components/alerts/AlertFilter";
import { AlertStream } from "@/components/alerts/AlertStream";
import { AlertDrawer } from "@/components/alerts/AlertDrawer";
import { RulesTab } from "@/components/alerts/RulesTab";
import { Button } from "@/components/ui/button";
import { useToast } from "@/components/ui/toast";
import { apiFetch, getAlerts, getModels, getSkus } from "@/lib/api";
import {
  type AlertEvent,
  type AlertSeverity,
  type CountryCode,
} from "@/lib/types";
import { cn } from "@/lib/cn";
import { useI18n } from "@/lib/i18n";

const SEV_RANK: Record<AlertSeverity, number> = {
  critical: 0,
  warning: 1,
  info: 2,
};

export default function AlertsPage() {
  const { t } = useI18n();
  const router = useRouter();
  const qc = useQueryClient();
  const toast = useToast();
  const [tab, setTab] = useState<"stream" | "rules">("stream");
  const [filter, setFilter] = useState<AlertFilterState>(DEFAULT_ALERT_FILTER);
  const [selected, setSelected] = useState<AlertEvent | null>(null);

  const alertsQ = useQuery({ queryKey: ["alerts"], queryFn: () => getAlerts() });
  const modelsQ = useQuery({ queryKey: ["models-alerts"], queryFn: () => getModels() });
  const skusQ = useQuery({ queryKey: ["skus-alerts"], queryFn: () => getSkus() });

  const [items, setItems] = useState<AlertEvent[]>([]);
  useEffect(() => {
    if (alertsQ.data) setItems(alertsQ.data);
  }, [alertsQ.data]);

  // 用 skus 表构建 PDP（商品页）链接映射：优先 sku_id 精确匹配，
  // 退而用 (model_id@channel_id) 兜底，让告警能直开对应机型×渠道的商品页核对价格。
  const productUrlBySku = useMemo(() => {
    const m: Record<string, string> = {};
    for (const s of skusQ.data ?? []) if (s.id && s.product_url) m[s.id] = s.product_url;
    return m;
  }, [skusQ.data]);
  const productUrlByMc = useMemo(() => {
    const m: Record<string, string> = {};
    for (const s of skusQ.data ?? [])
      if (s.model_id && s.channel_id && s.product_url)
        m[`${s.model_id}@${s.channel_id}`] = s.product_url;
    return m;
  }, [skusQ.data]);

  const productUrlFor = (a: AlertEvent | null): string | null => {
    if (!a) return null;
    if (a.sku_id && productUrlBySku[a.sku_id]) return productUrlBySku[a.sku_id];
    if (a.model_id && a.channel_id)
      return productUrlByMc[`${a.model_id}@${a.channel_id}`] ?? null;
    return null;
  };

  // 跳转看板时携带 model/country，定位到该告警对应的产品状态
  const buildJumpUrl = (a: AlertEvent | null): string => {
    if (!a) return "/";
    const params = new URLSearchParams();
    if (a.model_id) params.set("model", a.model_id);
    if (a.country_code) params.set("country", String(a.country_code));
    const qs = params.toString();
    return qs ? `/?${qs}` : "/";
  };

  const modelNameById = useMemo(() => {
    const m: Record<string, string> = {};
    for (const x of modelsQ.data ?? []) m[x.id] = x.display_name;
    return m;
  }, [modelsQ.data]);

  const visible = useMemo(() => {
    let list = items;
    if (filter.severities.length)
      list = list.filter((a) =>
        filter.severities.includes((a.severity ?? "info") as AlertSeverity),
      );
    if (filter.types.length)
      list = list.filter((a) => filter.types.includes(a.type));
    if (filter.countries.length)
      list = list.filter(
        (a) =>
          a.country_code &&
          filter.countries.includes(a.country_code as CountryCode),
      );
    if (filter.modelId !== "all")
      list = list.filter(
        (a) =>
          a.model_id === filter.modelId ||
          a.model === modelNameById[filter.modelId],
      );
    if (filter.status !== "all")
      list = list.filter((a) => (a.status ?? "unread") === filter.status);
    if (filter.timeRange !== "all") {
      const days =
        filter.timeRange === "7d" ? 7 : filter.timeRange === "90d" ? 90 : 30;
      const cutoff = Date.now() - days * 86400000;
      list = list.filter(
        (a) => a.triggered_at && new Date(a.triggered_at).getTime() >= cutoff,
      );
    }
    return [...list].sort((a, b) => {
      const r =
        SEV_RANK[a.severity ?? "info"] - SEV_RANK[b.severity ?? "info"];
      if (r !== 0) return r;
      return (
        new Date(b.triggered_at ?? 0).getTime() -
        new Date(a.triggered_at ?? 0).getTime()
      );
    });
  }, [items, filter, modelNameById]);

  const unread = items.filter((a) => (a.status ?? "unread") === "unread").length;

  const resolve = async (a: AlertEvent) => {
    const snapshot = items;
    setItems((prev) =>
      prev.map((x) => (x.id === a.id ? { ...x, status: "resolved" } : x)),
    );
    setSelected(null);
    try {
      await apiFetch(`/api/v1/alerts/${a.id}`, {
        method: "PATCH",
        body: { status: "resolved" },
      });
    } catch (e) {
      setItems(snapshot);
      toast.error(
        e instanceof Error ? e.message : t("标记为已处理失败，已回滚"),
      );
    }
  };

  const ignore = async (a: AlertEvent) => {
    const snapshot = items;
    setItems((prev) => prev.filter((x) => x.id !== a.id));
    setSelected(null);
    try {
      await apiFetch(`/api/v1/alerts/${a.id}`, {
        method: "PATCH",
        body: { status: "ignored" },
      });
    } catch (e) {
      setItems(snapshot);
      toast.error(e instanceof Error ? e.message : t("忽略失败，已回滚"));
    }
  };

  const topRight = (
    <Button
      size="sm"
      variant="secondary"
      icon={<RefreshCw size={14} />}
      onClick={() => qc.invalidateQueries({ queryKey: ["alerts"] })}
    >
      {t('刷新')}
    </Button>
  );

  return (
    <AppShell topRight={topRight}>
      <div className="flex min-h-[calc(100vh-3.5rem)]">
        <AlertFilter
          value={filter}
          onChange={setFilter}
          models={modelsQ.data ?? []}
        />

        <div className="flex min-w-0 flex-1 flex-col">
          {/* Tab 头 */}
          <div className="flex items-center gap-1 border-b border-border bg-bg px-5 pt-3">
            <button
              onClick={() => setTab("stream")}
              className={cn(
                "inline-flex items-center gap-1.5 border-b-2 px-3 pb-2 text-[13px] font-medium transition-colors duration-fast ease-standard",
                tab === "stream"
                  ? "border-accent text-accent-text"
                  : "border-transparent text-fg-2 hover:text-fg",
              )}
            >
              <ListFilter size={15} />
              {t('告警流')}
              {unread > 0 && (
                <span className="tabular rounded-pill bg-danger px-1.5 text-[10px] font-semibold text-white">
                  {unread}
                </span>
              )}
            </button>
            <button
              onClick={() => setTab("rules")}
              className={cn(
                "inline-flex items-center gap-1.5 border-b-2 px-3 pb-2 text-[13px] font-medium transition-colors duration-fast ease-standard",
                tab === "rules"
                  ? "border-accent text-accent-text"
                  : "border-transparent text-fg-2 hover:text-fg",
              )}
            >
              <Bell size={15} />
              {t('告警规则')}
            </button>
          </div>

          <div className="flex-1 p-5">
            {tab === "stream" ? (
              <section className="rounded-lg border border-border bg-surface">
                <div className="flex items-center justify-between border-b border-border px-4 py-2.5">
                  <h2 className="text-sm font-semibold text-fg">
                    {t('告警流')}
                    <span className="ml-2 text-[11px] font-normal text-muted">
                      {t('{n} 条 · 严重度置顶', { n: visible.length })}
                    </span>
                  </h2>
                </div>
                <AlertStream
                  alerts={visible}
                  onSelect={setSelected}
                  onResolve={resolve}
                  onIgnore={ignore}
                />
              </section>
            ) : (
              <RulesTab />
            )}
          </div>
        </div>
      </div>

      <AlertDrawer
        alert={selected}
        onClose={() => setSelected(null)}
        onResolve={resolve}
        onIgnore={ignore}
        onJump={() => router.push(buildJumpUrl(selected))}
        productUrl={productUrlFor(selected)}
      />
    </AppShell>
  );
}
