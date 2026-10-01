import { formatEurInt } from "./format";
import type { TierVal } from "./rival-matrix";

/** 主价格格式化：EUR 模式仅显示 €，raw 模式仅显示原始币种，不再双币并列 */
export function formatPrice(
  v: TierVal | undefined,
  currency: "EUR" | "raw",
): string {
  if (!v) return "—";
  if (currency === "EUR") {
    if (v.amount_eur == null) return "—";
    return `€${formatEurInt(v.amount_eur)}`;
  }
  if (v.amount == null) return "—";
  return `${formatEurInt(v.amount)} ${v.currency ?? ""}`;
}

/** 月付格式化：€29 × 24期 / 13290 HUF × 24期；无数据时返回「—」 */
export function formatMonthly(
  v: TierVal | undefined,
  currency: "EUR" | "raw",
  installments = 24,
): string {
  if (!v) return "—";
  if (currency === "EUR" && v.amount_eur == null) return "—";
  if (currency !== "EUR" && v.amount == null) return "—";
  const price = formatPrice(v, currency);
  return `${price} × ${installments}期`;
}
