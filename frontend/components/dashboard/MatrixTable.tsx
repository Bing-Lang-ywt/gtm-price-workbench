"use client";

import { useMemo } from "react";
import { Smartphone, ExternalLink } from "lucide-react";
import { cn } from "@/lib/cn";
import type { CompetitorRef, PriceType } from "@/lib/types";
import { COUNTRY_BY_CODE } from "@/lib/types";
import type { RivalRow } from "@/lib/rival-matrix";
import { CountryBadge } from "@/components/ui/country-badge";
import {
  PriceCell,
  InstallmentCell,
  ProductLinkButton,
  CompetitiveCell,
  parseVariant,
} from "./ProductCells";
import type { ManualFillContext } from "./ManualPriceDialog";
import { useI18n } from "@/lib/i18n";

interface Props {
  rows: RivalRow[];
  competitors: CompetitorRef[];
  currency: "EUR" | "raw";
  demobrandCode: string;
  demobrandLabel?: string;
  demobrandOfficialUrl?: string | null;
  demobrandModelId?: string | null;
  onFill: (ctx: ManualFillContext) => void;
}

/** 运营商渠道的付款方式：一次性付清 / 分期月付。
 *  （原「价格 + 月付」口径已废弃——月付列曾混入含资费的整单账单，
 *    造成 Yettel/Telekom 之间 77% 的假价差。） */
type ContentType = "outright" | "installment" | "price" | "gift" | "link";

interface ContentLine {
  type: ContentType;
  label: string;
}

interface DisplayRow {
  countryCode: string;
  countryName: string;
  channelId: string;
  channelName: string;
  channelType: "market" | "operator";
  contentType: ContentType;
  contentLabel: string;
  demobrand?: RivalRow["demobrand"];
  competitors: RivalRow["competitors"];
  competitiveness?: RivalRow["competitiveness"];
  channelBaseUrl?: string | null;
  channelListingUrl?: string | null;
  isFirstInChannel: boolean;
  channelSpan: number;
  isFirstInCountry: boolean;
  countrySpan: number;
}

const MARKET_LINES: ContentLine[] = [
  { type: "price", label: "价格" },
  { type: "gift", label: "赠品" },
  { type: "link", label: "链接" },
];

/** 运营商：两行付款方式（直接购买 / 分期购买）+ 赠品 + 链接。
 *  分期行显示「月付 × 期数 = 总价」，期数取官网方案中最接近 24 期的那个。 */
const OPERATOR_LINES: ContentLine[] = [
  { type: "outright", label: "直接购买" },
  { type: "installment", label: "分期购买" },
  { type: "gift", label: "赠品" },
  { type: "link", label: "链接" },
];

function channelTypeLabel(t: "market" | "operator"): string {
  return t === "market" ? "公开市场" : "运营商";
}

export function MatrixTable({
  rows,
  competitors,
  currency,
  demobrandCode,
  demobrandLabel,
  demobrandOfficialUrl,
  demobrandModelId,
  onFill,
}: Props) {
  const { t } = useI18n();
  const fills = useMemo(() => {
    const map = new Map<string, ManualFillContext>();
    const countryCurrency = (cc: string) =>
      COUNTRY_BY_CODE[cc]?.currency ?? "EUR";
    const push = (
      key: string,
      skuId: string | undefined | null,
      channelId: string,
      channelType: "market" | "operator",
      countryCode: string,
      channelName: string,
      modelName: string,
      priceType: PriceType,
      currentAmount?: number,
      currentCurrency?: string,
    ) => {
      if (!skuId) return;
      map.set(key, {
        skuId,
        channelId,
        priceType,
        currency: currentCurrency ?? countryCurrency(countryCode),
        channelName,
        modelName,
        currentAmount,
        currentCurrency,
      });
    };
    for (const r of rows) {
      const demobrandPrice = r.demobrand?.price;
      const demobrandMonthly = r.demobrand?.monthly;
      const demobrandSku = demobrandPrice?.sku_id ?? demobrandMonthly?.sku_id ?? null;
      push(
        `${r.countryCode}|${r.channelId}|demobrand`,
        demobrandSku,
        r.channelId,
        r.channelType,
        r.countryCode,
        r.channelName,
        demobrandCode,
        r.channelType === "operator" ? "subsidy_down_payment" : "unlocked",
        demobrandPrice?.amount ?? undefined,
        demobrandPrice?.currency ?? undefined,
      );
      if (r.channelType === "operator" && demobrandMonthly?.sku_id) {
        push(
          `${r.countryCode}|${r.channelId}|demobrand|monthly`,
          demobrandMonthly.sku_id,
          r.channelId,
          r.channelType,
          r.countryCode,
          r.channelName,
          demobrandCode,
          "contract_monthly",
          demobrandMonthly.amount ?? undefined,
          demobrandMonthly.currency ?? undefined,
        );
      }
      for (const col of r.competitors) {
        const pc = col.cell?.price;
        const mc = col.cell?.monthly;
        const sku = pc?.sku_id ?? mc?.sku_id ?? null;
        push(
          `${r.countryCode}|${r.channelId}|${col.ref.id}`,
          sku,
          r.channelId,
          r.channelType,
          r.countryCode,
          r.channelName,
          col.ref.display_name || col.ref.marketing_code,
          r.channelType === "operator" ? "subsidy_down_payment" : "unlocked",
          pc?.amount ?? undefined,
          pc?.currency ?? undefined,
        );
        if (r.channelType === "operator" && mc?.sku_id) {
          push(
            `${r.countryCode}|${r.channelId}|${col.ref.id}|monthly`,
            mc.sku_id,
            r.channelId,
            r.channelType,
            r.countryCode,
            r.channelName,
            col.ref.display_name || col.ref.marketing_code,
            "contract_monthly",
            mc.amount ?? undefined,
            mc.currency ?? undefined,
          );
        }
      }
    }
    return map;
  }, [rows, demobrandCode]);

  const modelVariantMap = useMemo(() => {
    const counts = new Map<string, Map<string, number>>();
    const bump = (mid: string | undefined | null, url?: string | null) => {
      if (!mid) return;
      const v = parseVariant(url);
      if (!v) return;
      if (!counts.has(mid)) counts.set(mid, new Map());
      const m = counts.get(mid)!;
      m.set(v, (m.get(v) ?? 0) + 1);
    };
    for (const r of rows) {
      bump(demobrandModelId, r.demobrand?.product_url);
      for (const col of r.competitors) bump(col.ref.id, col.cell?.product_url);
    }
    const out = new Map<string, string>();
    for (const [mid, m] of counts) {
      if (m.size === 0) continue;
      let best: string | null = null;
      let bestC = -1;
      for (const [v, c] of m) {
        if (c > bestC) {
          bestC = c;
          best = v;
        }
      }
      if (best) out.set(mid, best);
    }
    return out;
  }, [rows, demobrandModelId]);

  const displayRows = useMemo<DisplayRow[]>(() => {
    const out: DisplayRow[] = [];
    for (const r of rows) {
      const lines =
        r.channelType === "operator" ? OPERATOR_LINES : MARKET_LINES;
      for (const line of lines) {
        out.push({
          countryCode: r.countryCode,
          countryName: r.countryName,
          channelId: r.channelId,
          channelName: r.channelName,
          channelType: r.channelType,
          contentType: line.type,
          contentLabel: line.label,
          demobrand: r.demobrand,
          competitors: r.competitors,
          competitiveness: r.competitiveness,
          channelBaseUrl: r.channelBaseUrl,
          channelListingUrl: r.channelListingUrl,
          isFirstInChannel: false,
          channelSpan: lines.length,
          isFirstInCountry: false,
          countrySpan: 0,
        });
      }
    }
    for (let i = 0; i < out.length; i++) {
      const isFirst =
        i === 0 ||
        out[i - 1].channelId !== out[i].channelId ||
        out[i - 1].countryCode !== out[i].countryCode;
      out[i].isFirstInChannel = isFirst;
    }
    let i = 0;
    while (i < out.length) {
      const cc = out[i].countryCode;
      let j = i;
      while (j < out.length && out[j].countryCode === cc) j++;
      const span = j - i;
      out[i].isFirstInCountry = true;
      out[i].countrySpan = span;
      i = j;
    }
    return out;
  }, [rows]);

  // 一次性渲染全部行（不再分页）——102 条数据一屏内滚动即可看完，
  // 分页反而让「同渠道多行」被切断，无法横向对比。
  const pageRows = displayRows;

  const primary = competitors[0];

  const renderProductCell = (
    cell: RivalRow["demobrand"],
    contentType: ContentType,
    fillKey: string,
    fallbackUrl: string | null,
    variantModelId?: string | null,
  ) => {
    if (!cell) return <span className="text-meta">—</span>;
    const fillContext = fills.get(fillKey) ?? null;
    switch (contentType) {
      case "price":
      case "outright":
        return (
          <PriceCell
            v={cell.price}
            currency={currency}
            fillContext={fillContext}
            onFill={onFill}
            outright={contentType === "outright"}
          />
        );
      case "installment":
        return (
          <InstallmentCell
            device={cell.price}
            monthly={cell.monthly}
            currency={currency}
            fillContext={fills.get(`${fillKey}|monthly`) ?? null}
            onFill={onFill}
          />
        );
      case "gift":
        return (
          <span className="text-[12px] text-fg-2">{cell.gift ?? "—"}</span>
        );
      case "link": {
        const self = cell.product_url ? parseVariant(cell.product_url) : null;
        const rep = variantModelId
          ? (modelVariantMap.get(variantModelId) ?? null)
          : null;
        const variants = (self ?? rep) ? [self ?? rep!] : null;
        return (
          <ProductLinkButton
            productUrl={cell.product_url}
            listingUrl={cell.listing_url}
            fallback={fallbackUrl}
            variants={variants}
          />
        );
      }
    }
  };

  return (
    <>
    {/* 不再限高：102 行全部铺开，纵向滚动交给页面本身，横向滚动留在这里 */}
    <div className="overflow-x-auto">
      <table className="w-full min-w-[960px] table-fixed border-collapse text-[12px]">
        <thead>
          <tr className="sticky top-0 z-20 border-b border-border bg-surface">
            <th className="th-caps bg-surface px-3 py-2 text-center w-[88px]">
              {t('国家')}
            </th>
            <th className="th-caps bg-surface px-3 py-2 text-center w-[120px]">
              {t('渠道')}
            </th>
            <th className="th-caps bg-surface px-3 py-2 text-center w-[92px]">
              {t('渠道类型')}
            </th>
            <th className="th-caps border-l border-border bg-surface px-3 py-2 text-left w-[64px]">
              {t('内容')}
            </th>
            <th className="th-caps border-l border-border bg-surface px-3 py-2 text-center w-[150px]">
              <div className="flex flex-col items-center gap-1">
                <div className="flex items-center justify-center gap-1.5">
                  <Smartphone size={13} className="text-accent" />
                  {demobrandLabel ?? `荣耀 ${demobrandCode}`}
                </div>
                {demobrandOfficialUrl ? (
                  <a
                    href={demobrandOfficialUrl}
                    target="_blank"
                    rel="noopener noreferrer"
                    title={t('前往厂商官方产品详情页')}
                    className="mt-1 inline-flex items-center gap-1 rounded bg-accent px-1.5 py-0.5 text-[10px] font-medium text-white transition-colors duration-fast ease-standard hover:bg-accent-hover"
                  >
                    <ExternalLink size={11} /> {t('官网')}
                  </a>
                ) : null}
              </div>
            </th>
            {competitors.map((c) => (
              <th
                key={c.id}
                className="th-caps border-l border-border bg-surface px-3 py-2 text-center w-[150px]"
              >
                <div className="flex flex-col items-center gap-1">
                  <span>{c.brand}</span>
                  <span className="text-[10px] text-meta">
                    {c.marketing_code}
                  </span>
                  {c.officialUrl ? (
                    <a
                      href={c.officialUrl}
                      target="_blank"
                      rel="noopener noreferrer"
                      title={t('前往厂商官方产品详情页')}
                      className="inline-flex items-center gap-1 rounded bg-accent px-1.5 py-0.5 text-[10px] font-medium text-white transition-colors duration-fast ease-standard hover:bg-accent-hover"
                    >
                      <ExternalLink size={11} /> {t('官网')}
                    </a>
                  ) : null}
                </div>
              </th>
            ))}
            {/* 单品模式（机型下拉里选了竞品）：无对位竞品列 → 也不显示「荣耀对比」列 */}
            {primary ? (
              <th className="th-caps border-l border-border bg-surface px-3 py-2 text-center w-[120px]">
                荣耀{t('对比')}{primary.brand}
              </th>
            ) : null}
          </tr>
        </thead>
        <tbody>
          {pageRows.map((row, idx) => (
            <tr
              key={`${row.countryCode}-${row.channelId}-${row.contentType}`}
              className={cn(
                "border-b border-border-soft transition-colors duration-fast ease-standard hover:bg-accent-soft/50",
                idx % 2 === 1 && "bg-surface-warm/40",
              )}
            >
              {row.isFirstInCountry && (
                <td
                  rowSpan={row.countrySpan}
                  className="bg-surface-warm px-3 py-2.5 align-top text-center font-medium text-fg"
                >
                  <CountryBadge
                    code={row.countryCode}
                    showName
                    className="font-medium"
                  />
                </td>
              )}
              {row.isFirstInChannel && (
                <td
                  rowSpan={row.channelSpan}
                  className="px-3 py-2.5 align-top text-center text-fg"
                >
                  {row.channelName}
                </td>
              )}
              {row.isFirstInChannel && (
                <td
                  rowSpan={row.channelSpan}
                  className="px-3 py-2.5 align-top text-center text-fg-2"
                >
                  {t(channelTypeLabel(row.channelType))}
                </td>
              )}
              <td className="border-l border-border-soft px-3 py-2.5 align-top text-fg-2">
                {t(row.contentLabel)}
              </td>
              <td className="border-l border-border-soft px-3 py-2.5 align-top">
                {renderProductCell(
                  row.demobrand,
                  row.contentType,
                  `${row.countryCode}|${row.channelId}|demobrand`,
                  row.demobrand?.noLink
                    ? null
                    : (row.channelListingUrl || row.channelBaseUrl) ?? null,
                  demobrandModelId,
                )}
              </td>
              {row.competitors.map((col) => (
                <td
                  key={col.ref.id}
                  className="border-l border-border-soft px-3 py-2.5 align-top"
                >
                  {renderProductCell(
                    col.cell,
                    row.contentType,
                    `${row.countryCode}|${row.channelId}|${col.ref.id}`,
                    col.cell?.noLink
                      ? null
                      : (row.channelListingUrl || row.channelBaseUrl) ?? null,
                    col.ref.id,
                  )}
                </td>
              ))}
              {row.isFirstInChannel && primary ? (
                <td
                  rowSpan={row.channelSpan}
                  className="border-l border-border-soft px-3 py-2.5 align-top"
                >
                  <CompetitiveCell c={row.competitiveness} />
                </td>
              ) : null}
            </tr>
          ))}
        </tbody>
      </table>
    </div>

    {displayRows.length > 0 && (
      <div className="flex items-center justify-between gap-3 border-t border-border bg-surface-warm px-4 py-2 text-[12px] text-muted">
        <span className="tabular">
          {t('共 {n} 行（全部展开）', { n: displayRows.length })}
        </span>
        <span className="hidden text-[11px] sm:inline">
          {t('运营商渠道分「直接购买 / 分期购买」两行；分期 = 月付 × 官网期数')}
        </span>
      </div>
    )}
  </>
  );
}
