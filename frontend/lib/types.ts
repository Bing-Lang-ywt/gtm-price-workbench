/**
 * 后端契约类型（基于 openapi.yaml + SPEC §6 表结构）。
 * 响应统一 { code, data, message }。字段尽量 optional 以增强对真实后端的容错。
 */

export type PriceType =
  | "unlocked"
  | "contract_monthly"
  | "subsidy_down_payment";

export const PRICE_TYPES: PriceType[] = [
  "unlocked",
  "contract_monthly",
  "subsidy_down_payment",
];

export type CountryName =
  | "Serbia"
  | "Croatia"
  | "Hungary"
  | "Romania"
  | "Bulgaria"
  | "Poland"
  | "Finland"
  | "Czech Republic";

export type CountryCode = "RS" | "HR" | "HU" | "RO" | "BG" | "PL" | "FI" | "CZ";

export interface CountryMeta {
  code: CountryCode;
  name: CountryName;
  /** 本地货币 */
  currency: "RSD" | "EUR" | "HUF" | "RON" | "BGN" | "PLN" | "CZK";
}

/** 覆盖国家（SPEC §5 / §10） */
export const COUNTRIES: CountryMeta[] = [
  { code: "RS", name: "Serbia", currency: "RSD" },
  { code: "HR", name: "Croatia", currency: "EUR" },
  { code: "HU", name: "Hungary", currency: "HUF" },
  { code: "RO", name: "Romania", currency: "RON" },
  { code: "BG", name: "Bulgaria", currency: "BGN" },
  { code: "PL", name: "Poland", currency: "PLN" },
  { code: "FI", name: "Finland", currency: "EUR" },
  { code: "CZ", name: "Czech Republic", currency: "CZK" },
];

export const COUNTRY_BY_CODE: Record<string, CountryMeta> = Object.fromEntries(
  COUNTRIES.map((c) => [c.code, c]),
);

/** 统一响应信封 */
export interface ApiResponse<T> {
  code: number;
  data: T;
  message?: string;
}

export interface PriceValue {
  amount?: number | null;
  currency?: string | null;
  amount_eur?: number | null;
}

export type CrawlMode = "static" | "list";
export type ChannelType = "market" | "operator";
export type HealthStatus = "healthy" | "degraded" | "down" | "unknown";

export interface Channel {
  id: string;
  country: CountryName | string;
  country_code?: CountryCode | string;
  name: string;
  type: ChannelType;
  base_url?: string;
  crawl_mode?: CrawlMode;
  health?: HealthStatus;
  is_active?: boolean;
  last_crawl_at?: string | null;
  /** 该渠道最近一次抓取运行的状态：success | partial | failed | null(从未抓取)。来自 crawl_runs，与价格是否变化无关。 */
  last_crawl_status?: string | null;
}

export interface CrawlRun {
  id: string;
  channel_id: string;
  started_at: string;
  status: "running" | "success" | "partial" | "failed" | string;
  items?: number | null;
  error?: string | null;
}

export type PriceBand =
  | "entry"
  | "mid"
  | "upper_mid"
  | "flagship"
  | "foldable";

export interface ModelAlias {
  id?: string;
  alias: string;
}

export interface ModelRow {
  id: string;
  marketing_code: string;
  display_name: string;
  price_band_anchor?: PriceBand | null;
  price_band?: PriceBand | null;
  is_target?: boolean;
  aliases?: ModelAlias[];
  brand?: string;
  /** 厂商官方产品详情页（看板顶部「官网」按钮用） */
  official_url?: string | null;
}

/** 单个对位竞品引用（来自后端 model-mappings 的一行） */
export interface CompetitorRef {
  id: string;
  marketing_code: string;
  display_name: string;
  brand: string;
  /** 排序位次，0 = 主对位竞品（用于竞争力列） */
  position: number;
  /** 厂商官方产品详情页（官网按钮用；缺失时前端回落品牌首页） */
  officialUrl?: string | null;
}

/** 后端 model-mappings 返回的一行：DemoBrand 机型 → 某个竞品 */
export interface ModelCompetitorMapping {
  id: string;
  model_id: string;
  model_marketing_code?: string;
  model_display_name?: string;
  competitor_id: string;
  competitor_marketing_code?: string;
  competitor_display_name?: string;
  competitor_brand?: string;
  position: number;
}

export interface Sku {
  id: string;
  model_id: string;
  channel_id: string;
  slug?: string;
  product_url?: string;
  in_stock?: boolean;
  /** 入库备注，如「未上架(Excel)」「待补(Excel)」——用于 UI 标注未上架 */
  note?: string;
  model?: ModelRow;
  channel?: Channel;
  country?: CountryName | string;
  country_code?: CountryCode | string;
}

/** 最新价格快照（看板主源 /prices/latest），后端可能做富化 */
export interface PriceLatest {
  id?: string;
  sku_id: string;
  model_id?: string;
  model?: string;
  model_marketing_code?: string;
  brand?: string;
  is_target?: boolean;
  channel_id?: string;
  channel?: string;
  country?: CountryName | string;
  country_code?: CountryCode | string;
  channel_type?: ChannelType;
  price_type: PriceType;
  amount?: number | null;
  currency?: string | null;
  amount_eur?: number | null;
  previous_amount_eur?: number | null;
  delta_pct?: number | null;
  captured_at?: string;
  in_stock?: boolean;
  /** 精确机型商品页(PDP)链接，空串表示该渠道未售卖此机型对应商品页 */
  product_url?: string | null;
  /** 渠道商品列表/搜索页链接，作为 PDP 缺失时的回退 */
  listing_url?: string | null;
  /** 渠道官网兜底链接（来自 Channel.base_url） */
  channel_base_url?: string | null;
  /** 划线价（原价/促销前价），用于展示优惠力度；无则为 null */
  original_price?: number | null;
  /** 划线价的 EUR 折算值；用于 EUR 模式下正确展示划线价/折扣（避免把 HUF 等本地数值当 EUR 渲染） */
  original_price_eur?: number | null;
  /** 实体赠品文案（如「送耳机」）；无则为 null */
  gift?: string | null;
  /** 爬后核对标记（actual_gt_original / product_mismatch / out_of_band / unverified_no_pdp）；无则为 null */
  flag?: string | null;
  /**
   * 套餐月费（本地货币，如 Yettel HU「Havonta fizetendő 26 609 Ft/hó」）。
   * 注意：这**不是**设备分期——全机型同值（0 Ft 的机器和 710 990 Ft 的 Z Fold8 Ultra 都是 26 609），
   * 所以它不进 contract_monthly、不参与跨渠道比较，只在单元格里作「设备费 + X/月」注解展示。
   */
  monthly_payable?: number | null;
  /** 套餐月费的 EUR 折算值；EUR 模式必须用它，否则 26 609 HUF 会被当 26 609 € 渲染 */
  monthly_payable_eur?: number | null;
  /**
   * 合约设备实付价（本地货币）。Telekom HU「Kedvezményes készülékár」/ Yettel HU「Teljes ár」。
   * 主价格列统一存裸机标价 listaár 以保证跨渠道可比（两家混存曾造成 77% 的假价差），
   * 补贴力度靠这个注解字段体现。**0 是有效值**（签约赠机），判空必须用 != null。
   */
  contract_device_price?: number | null;
  /** 合约设备实付价的 EUR 折算值 */
  contract_device_price_eur?: number | null;
  /**
   * 设备分期明细（本地货币）：{ monthly, periods, total }。
   * Telekom HU「22 × 32 478 Ft」免息分期控件——月付 × 期数 = 总价。
   * 注意 total 取页面权威折后总额（非 monthly×periods，后者因月付四舍五入会差几 Ft）。
   * 仅作单元格注解（一次性付清 vs 分期对照），不参与跨渠道比较/排名。
   */
  installment?: { monthly: number; periods: number; total: number } | null;
  /** 设备分期明细的 EUR 折算值；EUR 模式必须用它，否则 HUF 数值会被当 EUR 渲染 */
  installment_eur?: { monthly: number; periods: number; total: number } | null;
}

export interface DashboardSummary {
  monitored_skus?: number;
  active_channels?: number;
  last_night_changes?: number;
  max_regional_spread?: number;
  spread_model?: string;
  spread_country_max?: CountryCode | string;
  spread_country_min?: CountryCode | string;
  last_crawl_at?: string | null;
  fx_date?: string | null;
  [key: string]: unknown;
}

export type AlertType =
  | "price_drop"
  | "price_up"
  | "new_sku"
  | "stock_out";

export type AlertStatus = "unread" | "resolved" | "ignored" | "active";

export type AlertSeverity = "critical" | "warning" | "info";

export interface AlertEvent {
  id: string;
  sku_id?: string;
  type: AlertType;
  before?: number | null;
  after?: number | null;
  before_raw?: PriceValue;
  after_raw?: PriceValue;
  triggered_at?: string;
  status?: AlertStatus;
  severity?: AlertSeverity;
  model?: string;
  model_id?: string;
  channel?: string;
  channel_id?: string;
  country?: CountryName | string;
  country_code?: CountryCode | string;
  price_type?: PriceType;
  title?: string;
  message?: string;
}

export type ScopeType = "model" | "sku" | "channel" | "segment";
export type ConditionType = "below" | "above" | "delta_pct" | "new_entry";

export interface AlertRule {
  id: string;
  // 复合作用域（精确绑定）：任一为空代表「该维度不限」
  channel_id?: string | null;
  model_id?: string | null;
  sku_id?: string | null;
  // 兼容旧规则
  scope_type?: ScopeType;
  scope_id?: string;
  price_type?: PriceType | null;
  condition_type: ConditionType;
  threshold?: number | null;
  notify_target?: string | null;
  is_active?: boolean;
  name?: string;
}

export interface PriceHistoryPoint {
  captured_at: string;
  amount_eur?: number | null;
  amount?: number | null;
  currency?: string | null;
  price_type?: PriceType;
}

export interface PriceHistoryResponse {
  sku_id?: string;
  data?: PriceHistoryPoint[];
}

/** 日历用：有抓取数据的日期及其条数 */
export interface PriceDateCount {
  date: string; // YYYY-MM-DD
  count: number;
}

/** 促销起点事件（/prices/promotions） */
export interface PromotionEvent {
  sku_id: string;
  model_id?: string;
  model?: string;
  model_marketing_code?: string;
  brand?: string;
  channel?: string;
  channel_id?: string;
  country_code?: CountryCode | string;
  price_type?: PriceType;
  /** 促销起点日期 YYYY-MM-DD */
  date: string;
  captured_at?: string;
  prev_amount_eur?: number | null;
  new_amount_eur?: number | null;
  /** 降幅百分比（正数表示降价幅度），如 16.7 表示降 16.7% */
  drop_pct?: number | null;
  currency?: string | null;
  amount?: number | null;
  product_url?: string | null;
}

/** 单品生命周期走势（/prices/trend） */
export interface ModelTrendPoint {
  date: string;
  ts: string;
  amount_eur?: number | null;
  amount?: number | null;
  currency?: string | null;
}

export interface ModelTrendChannel {
  channel: string;
  country_code?: CountryCode | string;
  points: ModelTrendPoint[];
}

export interface ModelTrend {
  model_id?: string;
  model?: string;
  model_marketing_code?: string;
  channels: ModelTrendChannel[];
}

/** 登录响应（data 内含 token） */
export interface LoginData {
  access_token: string;
  token?: string;
  token_type?: string;
  expires_in_hours?: number;
  user?: {
    id?: string;
    email?: string;
    name?: string;
    role?: string;
    sub?: string;
  };
}

/** 用户反馈留言（我要反馈留言板） */
export interface Feedback {
  id: string;
  author: string;
  email: string;
  content: string;
  created_at: string;
  status: string;
}

/* ---------------- 参数表（桌面 Excel 真源） ---------------- */

/** 参数对比：东北欧产品参数表单行（19 列） */
export interface ParamProduct {
  brand?: string | null;
  product?: string | null;
  category?: string | null;
  release_time?: string | null;
  price_rmb?: string | null;
  price_eur?: string | null;
  screen?: string | null;
  chip?: string | null;
  /** 芯片名（chip 字段首行，去细分规格/跑分） */
  chip_name?: string | null;
  front_camera?: string | null;
  rear_camera?: string | null;
  battery?: string | null;
  wired_charging_w?: string | null;
  wireless_charging_w?: string | null;
  dimensions?: string | null;
  ip_rating?: string | null;
  colors?: string | null;
  top_selling_point?: string | null;
  official_url?: string | null;
}

/** 芯片天梯图单行 */
export interface ParamChip {
  rank?: number | null;
  chip_name?: string | null;
  /** 极客湾综合性能分数 */
  score?: number | null;
  vendor?: string | null;
  /** 性能梯队（旗舰天花板/次旗舰/高端/中高端/中端/中端(基准)/低端/入门） */
  tier?: string | null;
  source?: string | null;
  /** 是否在本表中使用（"是" → true） */
  in_use?: boolean;
}

/** 参数表接口信封（含数据来源文件名与条数） */
export interface ParamTable<T> {
  items: T[];
  source?: string | null;
  count?: number;
  /** 真源（桌面 Excel）不可读、被迫使用项目内兜底副本时为 true，数据可能非最新 */
  stale?: boolean;
}
