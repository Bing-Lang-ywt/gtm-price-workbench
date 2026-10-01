"use client";

import { useMemo } from "react";
import { type ColumnDef } from "@tanstack/react-table";
import { Tag, Pencil, Smartphone } from "lucide-react";
import { DataTable } from "@/components/ui/data-table";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { type ModelRow, type PriceBand } from "@/lib/types";
import { useI18n } from "@/lib/i18n";

const BAND_LABEL: Record<PriceBand, string> = {
  entry: "入门",
  mid: "中端",
  upper_mid: "中高端",
  flagship: "旗舰",
  foldable: "折叠",
};

const BAND_TONE: Record<PriceBand, "neutral" | "info" | "accent" | "warn" | "success"> = {
  entry: "neutral",
  mid: "info",
  upper_mid: "accent",
  flagship: "warn",
  foldable: "success",
};

export function ModelTable({
  models,
  loading,
  onEdit,
}: {
  models: ModelRow[];
  loading?: boolean;
  onEdit: (m: ModelRow) => void;
}) {
  const { t } = useI18n();
  const columns = useMemo<ColumnDef<ModelRow, unknown>[]>(
    () => [
      {
        id: "brand",
        header: () => t("品牌"),
        cell: ({ row }) => (
          <span className="text-fg-2">{row.original.brand ?? "—"}</span>
        ),
      },
      {
        id: "model",
        header: () => t("机型"),
        cell: ({ row }) => (
          <div className="flex items-center gap-1.5">
            <Smartphone size={15} className="text-muted" />
            <span className="font-medium text-fg">
              {row.original.display_name}
            </span>
          </div>
        ),
      },
      {
        id: "marketing_code",
        header: () => t("营销代号"),
        cell: ({ row }) => (
          <span className="inline-flex items-center gap-1 font-mono text-[12px] text-fg-2">
            <Tag size={12} className="text-meta" />
            {row.original.marketing_code}
          </span>
        ),
      },
      {
        id: "price_band",
        header: () => t("价位段"),
        cell: ({ row }) => {
          const b = (row.original.price_band_anchor ??
            row.original.price_band) as PriceBand | undefined;
          if (!b) return <span className="text-meta">—</span>;
          return <Badge tone={BAND_TONE[b]}>{t(BAND_LABEL[b])}</Badge>;
        },
      },
      {
        id: "is_target",
        header: () => t("是否本品牌"),
        cell: ({ row }) =>
          row.original.is_target ? (
            <Badge tone="accent">{t("本品牌")}</Badge>
          ) : (
            <Badge tone="neutral">{t("竞品参照")}</Badge>
          ),
      },
      {
        id: "aliases",
        header: () => t("别名映射"),
        cell: ({ row }) => {
          const aliases = row.original.aliases?.map((a) => a.alias) ?? [];
          return (
            <span className="font-mono text-[11px] text-meta">
              {aliases.length ? aliases.join(", ") : "—"}
            </span>
          );
        },
      },
      {
        id: "actions",
        header: () => t("操作"),
        cell: ({ row }) => (
          <Button
            size="sm"
            variant="ghost"
            icon={<Pencil size={13} />}
            onClick={() => onEdit(row.original)}
          >
            {t("编辑")}
          </Button>
        ),
      },
    ],
    [onEdit, t],
  );

  return (
    <section className="rounded-lg border border-border bg-surface">
      <div className="flex items-center gap-2 border-b border-border px-4 py-2.5">
        <Smartphone size={16} className="text-accent" />
        <h2 className="text-sm font-semibold text-fg">{t("机型锚点")}</h2>
        <span className="text-[11px] text-muted">
          {t("{n} 个监控机型 · 含荣耀 600 系列与竞品参照", { n: models.length })}
        </span>
      </div>
      {loading ? (
        <div className="px-4 py-10 text-center text-[13px] text-muted">
          {t("加载机型配置…")}
        </div>
      ) : (
        <DataTable columns={columns} data={models} empty={t("暂无机型，点击新增")} />
      )}
    </section>
  );
}
