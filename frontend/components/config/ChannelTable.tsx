"use client";

import { useMemo } from "react";
import { type ColumnDef } from "@tanstack/react-table";
import { Store, Radio, RefreshCw, SlidersHorizontal } from "lucide-react";
import { DataTable } from "@/components/ui/data-table";
import { CountryBadge } from "@/components/ui/country-badge";
import { Badge, StatusDot } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { type Channel } from "@/lib/types";
import { relativeTime } from "@/lib/format";
import { useI18n } from "@/lib/i18n";

const HEALTH_LABEL: Record<string, string> = {
  healthy: "正常",
  degraded: "降级",
  down: "失效",
  unknown: "未知",
};

export function ChannelTable({
  channels,
  loading,
  onTrigger,
}: {
  channels: Channel[];
  loading?: boolean;
  onTrigger: (id: string) => void;
}) {
  const { t } = useI18n();
  const columns = useMemo<ColumnDef<Channel, unknown>[]>(
    () => [
      {
        id: "country",
        header: () => t("国家"),
        cell: ({ row }) => (
          <CountryBadge
            code={row.original.country_code ?? row.original.country}
            showName
          />
        ),
      },
      {
        id: "channel",
        header: () => t("渠道"),
        cell: ({ row }) => (
          <div className="min-w-0">
            <div className="font-medium text-fg">{row.original.name}</div>
            {row.original.base_url && (
              <div className="truncate font-mono text-[11px] text-meta max-w-[200px]">
                {row.original.base_url}
              </div>
            )}
          </div>
        ),
      },
      {
        id: "type",
        header: () => t("类型"),
        cell: ({ row }) => {
          const ty = row.original.type;
          return (
            <Badge tone={ty === "operator" ? "info" : "neutral"}>
              {ty === "operator" ? (
                <>
                  <Radio size={12} /> {t("运营商")}
                </>
              ) : (
                <>
                  <Store size={12} /> {t("公开市场")}
                </>
              )}
            </Badge>
          );
        },
      },
      {
        id: "crawl_mode",
        header: () => t("抓取模式"),
        cell: ({ row }) => (
          <span className="text-fg-2">
            {row.original.crawl_mode === "list" ? t("列表兜底") : t("静态直抓")}
          </span>
        ),
      },
      {
        id: "health",
        header: () => t("健康度"),
        cell: ({ row }) => (
          <span className="inline-flex items-center gap-1.5">
            <StatusDot status={row.original.health ?? "unknown"} />
            <span className="text-fg-2">
              {t(HEALTH_LABEL[row.original.health ?? "unknown"])}
            </span>
          </span>
        ),
      },
      {
        id: "last_crawl",
        header: () => t("最近抓取"),
        cell: ({ row }) => (
          <span className="text-fg-2">
            {relativeTime(row.original.last_crawl_at)}
          </span>
        ),
      },
      {
        id: "actions",
        header: () => t("操作"),
        cell: ({ row }) => (
          <Button
            size="sm"
            variant="ghost"
            icon={<RefreshCw size={13} />}
            onClick={() => onTrigger(row.original.id)}
          >
            {t("触发")}
          </Button>
        ),
      },
    ],
    [onTrigger, t],
  );

  return (
    <section className="rounded-lg border border-border bg-surface">
      <div className="flex items-center gap-2 border-b border-border px-4 py-2.5">
        <SlidersHorizontal size={16} className="text-accent" />
        <h2 className="text-sm font-semibold text-fg">{t("渠道锚点")}</h2>
        <span className="text-[11px] text-muted">
          {t("{n} 个渠道 · 按四国分组", { n: channels.length })}
        </span>
      </div>
      {loading ? (
        <div className="px-4 py-10 text-center text-[13px] text-muted">
          {t("加载渠道配置…")}
        </div>
      ) : (
        <DataTable columns={columns} data={channels} empty={t("暂无渠道，点击新增")} />
      )}
    </section>
  );
}
