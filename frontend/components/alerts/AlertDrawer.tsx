"use client";

import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
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
  Check,
  Ban,
  ExternalLink,
  LayoutDashboard,
  CircleAlert,
  TriangleAlert,
  Info,
  type LucideIcon,
} from "lucide-react";
import { Drawer } from "@/components/ui/drawer";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { CountryBadge } from "@/components/ui/country-badge";
import { getPriceHistory } from "@/lib/api";
import {
  type AlertEvent,
  type AlertSeverity,
  type PriceType,
} from "@/lib/types";
import {
  ALERT_TYPE_LABEL,
  PRICE_TYPE_LABEL,
  STATUS_LABEL,
  formatEUR,
  absoluteTime,
  relativeTime,
} from "@/lib/format";
import { useI18n } from "@/lib/i18n";

const SEV_ICON: Record<AlertSeverity, LucideIcon> = {
  critical: CircleAlert,
  warning: TriangleAlert,
  info: Info,
};
const SEV_TONE: Record<AlertSeverity, "danger" | "warn" | "info"> = {
  critical: "danger",
  warning: "warn",
  info: "info",
};

function fmtDate(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return `${d.getMonth() + 1}-${d.getDate()}`;
}

function MiniTrend({ skuId }: { skuId?: string }) {
  const { t } = useI18n();
  const { data, isLoading } = useQuery({
    queryKey: ["alert-history", skuId],
    queryFn: () => getPriceHistory({ sku_id: skuId! }),
    enabled: !!skuId,
  });
  const series = useMemo(() => {
    if (!data) return [];
    const arr = Array.isArray(data)
      ? (data as Array<{ captured_at: string; amount_eur?: number | null }>)
      : ((data as { data?: unknown }).data as Array<{
          captured_at: string;
          amount_eur?: number | null;
        }>) ?? [];
    return arr
      .filter((p) => p.captured_at && p.amount_eur != null)
      .map((p) => ({ date: fmtDate(p.captured_at), v: p.amount_eur as number }))
      .sort((a, b) => a.date.localeCompare(b.date));
  }, [data]);

  if (isLoading)
    return (
      <div className="h-[160px] flex items-center justify-center text-[12px] text-muted">
        {t("加载价格历史…")}
      </div>
    );
  if (series.length === 0)
    return (
      <div className="h-[160px] flex items-center justify-center text-[12px] text-muted">
        {t("该 SKU 暂无历史")}
      </div>
    );
  return (
    <div style={{ height: 160 }}>
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={series} margin={{ top: 8, right: 8, bottom: 4, left: 4 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--border-soft)" vertical={false} />
          <XAxis dataKey="date" stroke="var(--border)" tick={{ fill: "var(--muted)", fontSize: 10 }} tickLine={false} />
          <YAxis stroke="var(--border)" tick={{ fill: "var(--muted)", fontSize: 10 }} tickLine={false} width={42} tickFormatter={(v: number) => `€${Math.round(v)}`} />
          <Tooltip
            contentStyle={{
              background: "var(--surface)",
              border: "1px solid var(--border)",
              borderRadius: 8,
              fontSize: 12,
              color: "var(--fg)",
            }}
            formatter={(v: number) => [formatEUR(v), "EUR"]}
          />
          <Line type="monotone" dataKey="v" stroke="var(--accent)" strokeWidth={2} dot={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

export function AlertDrawer({
  alert,
  onClose,
  onResolve,
  onIgnore,
  onJump,
  productUrl,
}: {
  alert: AlertEvent | null;
  onClose: () => void;
  onResolve: (a: AlertEvent) => void;
  onIgnore: (a: AlertEvent) => void;
  onJump: () => void;
  /** 该告警对应机型×渠道的真实商品页(PDP)链接，用于直开核对价格 */
  productUrl?: string | null;
}) {
  const { t } = useI18n();
  const sev = (alert?.severity ?? "info") as AlertSeverity;
  const SevIcon = SEV_ICON[sev];
  const delta =
    alert && alert.before != null && alert.after != null && alert.before !== 0
      ? ((alert.after - alert.before) / Math.abs(alert.before)) * 100
      : null;
  const up = (delta ?? 0) > 0;

  return (
    <Drawer
      open={!!alert}
      onClose={onClose}
      title={
        alert ? (
          <span className="flex items-center gap-1.5">
            <SevIcon size={16} className={sev === "critical" ? "text-danger" : sev === "warning" ? "text-warn-strong" : "text-info"} />
            {ALERT_TYPE_LABEL[alert.type] ? t(ALERT_TYPE_LABEL[alert.type]) + t("详情") : t("告警详情")}
          </span>
        ) : (
          t("告警详情")
        )
      }
      footer={
        alert && (
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex gap-2">
              <Button variant="ghost" icon={<LayoutDashboard size={15} />} onClick={onJump}>
                {t("跳看板")}
              </Button>
              {productUrl && (
                <Button
                  variant="ghost"
                  icon={<ExternalLink size={15} />}
                  onClick={() => window.open(productUrl, "_blank", "noopener,noreferrer")}
                >
                  {t("查看商品页")}
                </Button>
              )}
            </div>
            <div className="flex gap-2">
              <Button variant="secondary" icon={<Ban size={15} />} onClick={() => onIgnore(alert)}>
                {t("忽略")}
              </Button>
              <Button variant="primary" icon={<Check size={15} />} onClick={() => onResolve(alert)}>
                {t("标记已处理")}
              </Button>
            </div>
          </div>
        )
      }
    >
      {alert && (
        <div className="space-y-4">
          <div>
            <div className="flex items-center gap-2">
              <Badge tone={SEV_TONE[sev]}>
                {sev === "critical" ? t("严重") : sev === "warning" ? t("警告") : t("提示")}
              </Badge>
              <Badge tone="neutral">{t(ALERT_TYPE_LABEL[alert.type])}</Badge>
              {alert.status && <Badge tone="neutral">{t(STATUS_LABEL[alert.status])}</Badge>}
            </div>
            <h3 className="mt-2 text-[15px] font-semibold text-fg">
              {alert.title ??
                `${alert.model ?? t("机型")} ${alert.price_type ? t(PRICE_TYPE_LABEL[alert.price_type as PriceType]) : ""} ${t("异动")}`}
            </h3>
          </div>

          {/* before → after */}
          <div className="rounded-md border border-border bg-surface-warm px-3 py-2">
            <div className="flex items-center justify-between">
              <span className="text-[12px] text-muted">{t("变化（EUR）")}</span>
              {delta != null && (
                <span
                  className={
                    "tabular text-[12px] font-semibold " +
                    (up ? "text-trend-up" : "text-trend-down")
                  }
                >
                  {up ? "▲" : "▼"} {Math.abs(delta).toFixed(1)}%
                </span>
              )}
            </div>
            <div className="mt-1 flex items-baseline gap-2">
              <span className="tabular text-[13px] text-muted">
                {formatEUR(alert.before)}
              </span>
              <span className="text-meta">→</span>
              <span className="tabular text-lg font-semibold text-fg">
                {formatEUR(alert.after)}
              </span>
            </div>
          </div>

          {/* 上下文 */}
          <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-[12px]">
            <Ctx label={t("机型")} value={alert.model ?? "—"} />
            <Ctx label={t("渠道")} value={alert.channel ?? "—"} />
            <Ctx
              label={t("国家")}
              value={alert.country_code ? <CountryBadge code={alert.country_code} showName /> : "—"}
            />
            <Ctx
              label={t("档位")}
              value={alert.price_type ? t(PRICE_TYPE_LABEL[alert.price_type]) : "—"}
            />
            <Ctx label={t("触发时间")} value={absoluteTime(alert.triggered_at)} />
            <Ctx label={t("相对")} value={relativeTime(alert.triggered_at)} />
          </dl>

          {/* 触发规则 */}
          <div className="rounded-md border border-border bg-surface-warm px-3 py-2">
            <p className="text-[12px] font-semibold text-fg-2">{t("触发规则")}</p>
            <p className="mt-0.5 text-[12px] text-muted">
              {alert.type === "price_drop" || alert.type === "price_up"
                ? t("价格变动幅度超过阈值 3%（默认）")
                : alert.type === "stock_out"
                  ? t("库存状态由有货变为缺货")
                  : t("同价位段发现新 SKU")}
            </p>
          </div>

          {/* mini 价史 */}
          <div>
            <p className="mb-1 text-[12px] font-semibold text-fg-2">
              {t("近期价格历史")}
            </p>
            <div className="rounded-md border border-border">
              <MiniTrend skuId={alert.sku_id} />
            </div>
          </div>
        </div>
      )}
    </Drawer>
  );
}

function Ctx({
  label,
  value,
}: {
  label: string;
  value: React.ReactNode;
}) {
  return (
    <div>
      <dt className="text-[11px] text-muted">{label}</dt>
      <dd className="text-fg-2">{value}</dd>
    </div>
  );
}
