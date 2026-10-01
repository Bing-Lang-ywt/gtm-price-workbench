"use client";

import { useCallback, useState } from "react";
import { Layers, MoveHorizontal } from "lucide-react";
import type { CompetitorRef } from "@/lib/types";
import type { ManualPriceBody } from "@/lib/api";
import type { RivalRow } from "@/lib/rival-matrix";
import { MatrixTable } from "./MatrixTable";
import {
  ManualPriceDialog,
  type ManualFillContext,
} from "./ManualPriceDialog";
import { useI18n } from "@/lib/i18n";

interface Props {
  rows: RivalRow[];
  competitors: CompetitorRef[];
  demobrandCode: string;
  demobrandModelId?: string | null;
  currency: "EUR" | "raw";
  demobrandLabel?: string;
  demobrandOfficialUrl?: string | null;
  onManualSave: (body: ManualPriceBody) => Promise<void>;
}

export function ComparisonMatrix({
  rows,
  competitors,
  demobrandCode,
  demobrandModelId,
  demobrandLabel,
  currency,
  demobrandOfficialUrl,
  onManualSave,
}: Props) {
  const { t } = useI18n();
  const [manualCtx, setManualCtx] = useState<ManualFillContext | null>(null);

  const openManual = useCallback(
    (ctx: ManualFillContext) => setManualCtx(ctx),
    [],
  );

  return (
    <section className="overflow-hidden rounded-lg border border-border bg-surface">
      <div className="flex items-center justify-between gap-3 border-b border-border px-4 py-2.5">
        <h2 className="flex items-center gap-2 text-sm font-semibold text-fg">
          <Layers size={16} className="text-accent" />
          {t('竞品对位对比矩阵')}
          {rows.length > 0 && (
            <span className="rounded-pill bg-surface-warm px-2 py-0.5 text-[11px] font-medium text-muted tabular">
              {rows.length} {t('渠道')}
            </span>
          )}
        </h2>
        <p className="hidden text-[11px] text-muted lg:block">
          {t('最上方选择本品牌产品，系统自动带出对位机型')}
        </p>
      </div>

      <div className="flex items-center gap-1.5 border-b border-border bg-surface-warm px-4 py-1.5 text-[11px] text-muted xl:hidden">
        <MoveHorizontal size={13} />
        {t('左右滑动查看完整对比矩阵')}
      </div>

      <MatrixTable
        rows={rows}
        competitors={competitors}
        currency={currency}
        demobrandCode={demobrandCode}
        demobrandLabel={demobrandLabel}
        demobrandOfficialUrl={demobrandOfficialUrl}
        demobrandModelId={demobrandModelId}
        onFill={openManual}
      />

      <ManualPriceDialog
        key={manualCtx?.skuId ?? "closed"}
        ctx={manualCtx}
        onClose={() => setManualCtx(null)}
        onSave={onManualSave}
      />
    </section>
  );
}
