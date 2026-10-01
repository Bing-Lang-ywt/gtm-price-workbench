import { COUNTRY_BY_CODE, type CountryCode } from "./types";

/** 数值格式化工具 —— 金额统一走等宽字体（tabular）由组件 class 控制 */

const EUR = new Intl.NumberFormat("en-IE", {
  maximumFractionDigits: 0,
});

const eur0 = (n: number) => `${EUR.format(Math.round(n))} €`;

/** 金额（EUR）展示：整数 + € */
export function formatEUR(amount?: number | null): string {
  if (amount == null || Number.isNaN(amount)) return "—";
  return eur0(amount);
}

/** 千分位整数（EUR 语境，逗号分组），供矩阵主价格/明细行复用，保证视觉一致 */
export function formatEurInt(amount?: number | null): string {
  if (amount == null || Number.isNaN(amount)) return "—";
  return EUR.format(Math.round(amount));
}

/** 分期月付：金额较小且常带小数（11.00 € / 179.15 zł），整数走千分位、
 *  非整数保留 2 位小数；总价仍用 formatEurInt 取整。 */
export function formatAmount(
  amount?: number | null,
  decimals: number = 2,
): string {
  if (amount == null || Number.isNaN(amount)) return "—";
  const fixed = Number(amount.toFixed(decimals));
  if (Number.isInteger(fixed)) return EUR.format(fixed);
  return fixed.toLocaleString("en-IE", {
    minimumFractionDigits: 2,
    maximumFractionDigits: decimals,
  });
}

/** 原始币种金额展示：整数 + 币种代码 */
export function formatRaw(
  amount?: number | null,
  currency?: string | null,
): string {
  if (amount == null || Number.isNaN(amount)) return "—";
  const cur = currency ?? "";
  return `${EUR.format(Math.round(amount))}${cur ? ` ${cur}` : ""}`;
}

/** 百分比（带符号，1 位小数） */
export function formatPct(pct?: number | null): string {
  if (pct == null || Number.isNaN(pct)) return "—";
  const sign = pct > 0 ? "+" : "";
  return `${sign}${pct.toFixed(1)}%`;
}

/** 相对时间（中文，近似） */
export function relativeTime(iso?: string | null): string {
  if (!iso) return "—";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "—";
  const diff = Date.now() - then;
  const min = Math.floor(diff / 60000);
  if (min < 1) return "刚刚";
  if (min < 60) return `${min} 分钟前`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return `${hr} 小时前`;
  const day = Math.floor(hr / 24);
  if (day < 30) return `${day} 天前`;
  const mo = Math.floor(day / 30);
  return `${mo} 个月前`;
}

/** 绝对时间（短） */
export function absoluteTime(iso?: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleString("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** 国家码 → 国家名 */
export function countryName(code?: string | null): string {
  if (!code) return "—";
  return COUNTRY_BY_CODE[code]?.name ?? code;
}

/** 国家码 → 货币 */
export function countryCurrency(code?: string | null): string {
  if (!code) return "EUR";
  return COUNTRY_BY_CODE[code]?.currency ?? "EUR";
}

export const PRICE_TYPE_LABEL: Record<string, string> = {
  unlocked: "裸机价",
  contract_monthly: "合约月租",
  subsidy_down_payment: "补贴首付",
};

export const PRICE_TYPE_SHORT: Record<string, string> = {
  unlocked: "裸机",
  contract_monthly: "月租",
  subsidy_down_payment: "首付",
};

export const ALERT_TYPE_LABEL: Record<string, string> = {
  price_drop: "降价",
  price_up: "反弹",
  new_sku: "上新",
  stock_out: "缺货",
};

export const SEVERITY_LABEL: Record<string, string> = {
  critical: "严重",
  warning: "警告",
  info: "提示",
};

export const STATUS_LABEL: Record<string, string> = {
  unread: "未读",
  resolved: "已处理",
  ignored: "已忽略",
  active: "活跃",
};
