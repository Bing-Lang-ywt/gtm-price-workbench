"use client";

import { getToken } from "./auth";
import type {
  AlertEvent,
  AlertRule,
  ApiResponse,
  Channel,
  CrawlRun,
  DashboardSummary,
  LoginData,
  Feedback,
  ModelCompetitorMapping,
  ModelRow,
  PriceType,
  PriceBand,
  PriceHistoryPoint,
  PriceLatest,
  Sku,
  PriceDateCount,
  PromotionEvent,
  ModelTrend,
  ParamProduct,
  ParamChip,
  ParamTable,
} from "./types";

const RAW_API_URL = process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, "");

/**
 * 同域部署（反向代理把 /api/* 转发到后端）时设 NEXT_PUBLIC_API_URL=same-origin：
 * 请求走浏览器当前 origin，既不触发 CORS，也不用在构建期固化域名——换域名无需重新构建。
 * 其余情况维持原行为：显式地址优先，未设置则回落到本地后端。
 */
const SAME_ORIGIN = RAW_API_URL === "same-origin";
const API_URL = SAME_ORIGIN ? "" : RAW_API_URL || "http://localhost:8000";

export class ApiError extends Error {
  status: number;
  code: number;
  constructor(message: string, status: number, code: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
}

interface FetchOpts {
  method?: "GET" | "POST" | "PATCH" | "DELETE" | "PUT";
  body?: unknown;
  params?: Record<string, string | number | boolean | undefined | null>;
  auth?: boolean;
}

function buildUrl(
  path: string,
  params?: FetchOpts["params"],
): string {
  // API_URL 为空 = 同域模式，用当前页面 origin 作基址（SSR 阶段无 window，回落本地）
  const base =
    API_URL ||
    (typeof window !== "undefined"
      ? window.location.origin
      : "http://localhost:3000");
  const url = new URL(
    path.startsWith("/") ? path : `/${path}`,
    base,
  );
  if (params) {
    for (const [k, v] of Object.entries(params)) {
      if (v === undefined || v === null || v === "") continue;
      url.searchParams.set(k, String(v));
    }
  }
  return url.toString();
}

/**
 * 统一请求封装：
 * - 拼 NEXT_PUBLIC_API_URL
 * - 附加 Bearer JWT（auth 默认 true）
 * - 解析 { code, data, message } 信封
 * - 非 2xx 或 code !== 0 → 抛 ApiError（401 清 token）
 */
// 502/503/504 与网络层错误（连接被代理复用等情况）偶发，自动重试可自愈，
// 避免用户在「改价/抓取」等低频写操作上因一次瞬断而失败。
const MAX_RETRY = 2;
const retryDelayMs = (attempt: number) => 400 * (attempt + 1); // 400ms, 800ms

export async function apiFetch<T>(
  path: string,
  opts: FetchOpts = {},
): Promise<T> {
  const { method = "GET", body, params, auth = true } = opts;
  const headers: Record<string, string> = {
    Accept: "application/json",
  };
  if (body !== undefined) {
    headers["Content-Type"] = "application/json";
  }
  if (auth) {
    const token = getToken();
    if (token) headers["Authorization"] = `Bearer ${token}`;
  }

  const url = buildUrl(path, params);

  let lastRes: Response | null = null;
  let lastErr: unknown = null;

  for (let attempt = 0; attempt <= MAX_RETRY; attempt++) {
    try {
      const res = await fetch(url, {
        method,
        headers,
        body: body !== undefined ? JSON.stringify(body) : undefined,
        cache: "no-store",
      });
      lastRes = res;
      lastErr = null;

      if (res.ok) {
        const text = await res.text();
        let payload: ApiResponse<T> | null = null;
        if (text) {
          try {
            payload = JSON.parse(text) as ApiResponse<T>;
          } catch {
            payload = null;
          }
        }
        if (payload && typeof payload.code === "number" && payload.code !== 0) {
          throw new ApiError(payload.message || "业务错误", res.status, payload.code);
        }
        return (payload?.data ?? (null as unknown as T)) as T;
      }

      // 非 2xx：仅 5xx（含 502 Bad Gateway）值得重试；4xx（401/422/429 等）
      // 是确定性错误，重试无意义，直接抛出。
      if (attempt < MAX_RETRY && res.status >= 500) {
        await new Promise((r) => setTimeout(r, retryDelayMs(attempt)));
        continue;
      }
      const text = await res.text();
      // Cloudflare 拦截特征：403/429 + 页面含 cloudflare / "just a moment" / "checking your browser" 等字样。
      // 这是公司网络出口 IP 被 WAF / Bot Fight Mode / 速率限制拦截，并非平台故障——给出可操作提示。
      const lower = text.toLowerCase();
      const looksLikeCfBlock =
        (res.status === 403 || res.status === 429) &&
        (lower.includes("cloudflare") ||
          lower.includes("just a moment") ||
          lower.includes("checking your browser") ||
          lower.includes("blocked"));
      if (looksLikeCfBlock) {
        throw new ApiError(
          "访问被 Cloudflare 拦截（公司网络出口 IP 被识别为风险 / 触发 Bot 挑战）。可尝试：刷新页面、切换网络，或在 Cloudflare 将你的出口 IP 加入白名单 / 关闭 Bot Fight Mode。",
          res.status,
          -1,
        );
      }
      let payload: ApiResponse<T> | null = null;
      if (text) {
        try {
          payload = JSON.parse(text) as ApiResponse<T>;
        } catch {
          payload = null;
        }
      }
      if (res.status === 401 && typeof window !== "undefined") {
        // token 失效/过期：清掉本地态并跳登录页
        window.localStorage.removeItem("pm_jwt");
        window.localStorage.removeItem("pm_user");
        if (window.location.pathname !== "/login") {
          window.location.assign("/login");
        }
      }
      const msg = payload?.message || `请求失败（${res.status}）`;
      throw new ApiError(msg, res.status, payload?.code ?? -1);
    } catch (e) {
      lastErr = e;
      // 网络层错误（fetch 抛异常，如连接被代理复用导致的 502/reset）也重试。
      if (attempt < MAX_RETRY) {
        await new Promise((r) => setTimeout(r, retryDelayMs(attempt)));
        continue;
      }
      if (e instanceof ApiError) throw e;
      throw new ApiError(e instanceof Error ? e.message : "网络错误", 0, -1);
    }
  }

  // 不应到达；兜底
  throw lastErr instanceof ApiError
    ? lastErr
    : new ApiError("请求失败", lastRes?.status ?? 0, -1);
}

/**
 * 后端列表接口统一返回 { items, meta } 分页信封，但前端各列表 getter 期望拿到纯数组。
 * 这里统一解开；若已是数组则原样返回，若两者皆非则回退空数组（避免 .filter / .map 在对象上崩溃）。
 * 注意：仅作用于列表接口，login / summary / trigger 等返回对象（无 items）的接口不受影响。
 */
function unwrapItems<T>(data: unknown): T[] {
  if (Array.isArray(data)) return data as T[];
  if (
    data &&
    typeof data === "object" &&
    Array.isArray((data as { items?: unknown }).items)
  ) {
    return (data as { items: T[] }).items;
  }
  return [];
}

/* ---------------- 认证 ---------------- */

export async function login(
  email: string,
  password: string,
): Promise<LoginData> {
  return apiFetch<LoginData>("/api/v1/auth/login", {
    method: "POST",
    body: { email, password },
    auth: false,
  });
}

/* ---------------- 看板 ---------------- */

export function getSummary(): Promise<DashboardSummary> {
  return apiFetch<DashboardSummary>("/api/v1/dashboard/summary");
}

export function getPricesLatest(params?: FetchOpts["params"]): Promise<
  PriceLatest[]
> {
  return apiFetch<PriceLatest[]>("/api/v1/prices/latest", {
    params: { limit: 1000, ...params },
  }).then((d) => unwrapItems<PriceLatest>(d));
}

export function getComparison(params?: FetchOpts["params"]): Promise<unknown> {
  return apiFetch<unknown>("/api/v1/comparison", { params });
}

/** 手动触发一次全量抓取（SPEC §5 POST /api/v1/crawl/trigger）
 *  in-flight 守卫：防止按钮连点 / 前端重试层造成的重复触发（audit C12）。
 *  同一时刻只允许一个 trigger 在途；若已在进行中，直接解析为 skipped。 */
let _crawlInFlight = false;
export function triggerCrawl(): Promise<
  { triggered?: boolean; skipped?: string } | unknown
> {
  if (_crawlInFlight) {
    return Promise.resolve({ triggered: false, skipped: "in-flight" });
  }
  _crawlInFlight = true;
  return apiFetch<{ triggered?: boolean }>("/api/v1/crawl/trigger", {
    method: "POST",
  }).finally(() => {
    _crawlInFlight = false;
  });
}

/** 获取最近一次成功抓取完成时间，用于前端判断是否“本日已抓取” */
export function getLastCrawl(): Promise<{ last_finished_at: string | null }> {
  return apiFetch<{ last_finished_at: string | null }>("/api/v1/crawl/last-run");
}

export function getPriceHistory(params?: FetchOpts["params"]): Promise<
  PriceHistoryPoint[]
> {
  return apiFetch<PriceHistoryPoint[]>("/api/v1/prices", { params }).then(
    (d) => unwrapItems<PriceHistoryPoint>(d),
  );
}

/* ---------------- 价格历史 / 日历 / 促销 / 生命周期 ---------------- */

/** 日历：所有有抓取数据的日期及条数（升序） */
export function getPriceDates(): Promise<PriceDateCount[]> {
  return apiFetch<PriceDateCount[]>("/api/v1/prices/dates").then((d) =>
    unwrapItems<PriceDateCount>(d),
  );
}

/** 按日快照：锚定到某日期的当日价格（PriceLatest[]，复用看板主源行结构） */
export function getPriceSnapshotByDate(
  params?: FetchOpts["params"],
): Promise<PriceLatest[]> {
  return apiFetch<PriceLatest[]>("/api/v1/prices/by-date", {
    params: { limit: 2000, ...params },
  }).then((d) => unwrapItems<PriceLatest>(d));
}

/** 促销起点事件流 */
export function getPromotions(
  params?: FetchOpts["params"],
): Promise<PromotionEvent[]> {
  return apiFetch<PromotionEvent[]>("/api/v1/prices/promotions", {
    params,
  }).then((d) => unwrapItems<PromotionEvent>(d));
}

/** 单品生命周期走势（按渠道分组时间序列） */
export function getModelTrend(
  params?: FetchOpts["params"],
): Promise<ModelTrend> {
  return apiFetch<ModelTrend>("/api/v1/prices/trend", { params });
}

/* ---------------- 配置 ---------------- */

export function getChannels(params?: FetchOpts["params"]): Promise<
  Channel[]
> {
  return apiFetch<Channel[]>("/api/v1/channels", {
    params: { limit: 1000, ...params },
  }).then((d) => unwrapItems<Channel>(d));
}

export function getModels(params?: FetchOpts["params"]): Promise<ModelRow[]> {
  return apiFetch<ModelRow[]>("/api/v1/models", {
    params: { limit: 1000, ...params },
  }).then((d) => unwrapItems<ModelRow>(d));
}

export function getModelMappings(
  params?: FetchOpts["params"],
): Promise<ModelCompetitorMapping[]> {
  return apiFetch<ModelCompetitorMapping[]>("/api/v1/model-mappings", {
    params: { limit: 1000, ...params },
  }).then((d) => unwrapItems<ModelCompetitorMapping>(d));
}

export function getSkus(params?: FetchOpts["params"]): Promise<Sku[]> {
  return apiFetch<Sku[]>("/api/v1/skus", {
    params: { limit: 1000, ...params },
  }).then((d) => unwrapItems<Sku>(d));
}

export function getCrawlRuns(
  channelId: string,
  params?: FetchOpts["params"],
): Promise<CrawlRun[]> {
  return apiFetch<CrawlRun[]>(
    `/api/v1/channels/${channelId}/crawl-runs`,
    { params: { limit: 1000, ...params } },
  ).then((d) => unwrapItems<CrawlRun>(d));
}

/* ---------------- 告警事件流（状态变更仍走 /api/v1/alerts） ---------------- */

export function getAlerts(params?: FetchOpts["params"]): Promise<
  AlertEvent[]
> {
  return apiFetch<AlertEvent[]>("/api/v1/alerts", {
    params: { limit: 1000, ...params },
  }).then((d) => unwrapItems<AlertEvent>(d));
}

/* ---------------- 告警规则（独立资源 /api/v1/alert-rules） ---------------- */

export function getAlertRules(params?: FetchOpts["params"]): Promise<
  AlertRule[]
> {
  return apiFetch<AlertRule[]>("/api/v1/alert-rules", {
    params: { limit: 1000, ...params },
  }).then((d) => unwrapItems<AlertRule>(d));
}

export function createAlertRule(
  body: Partial<AlertRule>,
): Promise<AlertRule> {
  return apiFetch<AlertRule>("/api/v1/alert-rules", { method: "POST", body });
}

/* ---------------- 人工补录价格（POST /api/v1/prices/manual） ---------------- */

export interface ManualPriceBody {
  sku_id: string;
  channel_id: string;
  price_type: PriceType;
  price: number;
  currency: string;
  in_stock?: boolean;
}

export function createManualPrice(
  body: ManualPriceBody,
): Promise<unknown> {
  return apiFetch<unknown>("/api/v1/prices/manual", { method: "POST", body });
}

export function patchAlertRule(
  id: string,
  body: Partial<AlertRule>,
): Promise<AlertRule> {
  return apiFetch<AlertRule>(`/api/v1/alert-rules/${id}`, {
    method: "PATCH",
    body,
  });
}

export function deleteAlertRule(id: string): Promise<void> {
  return apiFetch<void>(`/api/v1/alert-rules/${id}`, { method: "DELETE" });
}

/* ---------------- 我要反馈留言板（/api/v1/feedbacks） ---------------- */

export function getFeedbacks(
  params?: FetchOpts["params"],
): Promise<Feedback[]> {
  return apiFetch<Feedback[]>("/api/v1/feedbacks", {
    params: { limit: 1000, ...params },
  }).then((d) => unwrapItems<Feedback>(d));
}

export function createFeedback(body: {
  content: string;
  author?: string;
}): Promise<Feedback> {
  return apiFetch<Feedback>("/api/v1/feedbacks", { method: "POST", body });
}

export function deleteFeedback(id: string): Promise<void> {
  return apiFetch<void>(`/api/v1/feedbacks/${id}`, { method: "DELETE" });
}

/* ---------------- 机型锚点编辑（PATCH /api/v1/models/{id}） ---------------- */

export interface PatchModelBody {
  display_name?: string;
  price_band_anchor?: PriceBand | null;
  is_target?: boolean;
  aliases?: { alias: string }[];
}

export function patchModel(id: string, body: PatchModelBody): Promise<ModelRow> {
  return apiFetch<ModelRow>(`/api/v1/models/${id}`, { method: "PATCH", body });
}

/* ---------------- 参数表（桌面 Excel 真源）：参数对比 & 芯片天梯图 ---------------- */

export function getParamProducts(): Promise<ParamTable<ParamProduct>> {
  return apiFetch<ParamTable<ParamProduct>>("/api/v1/params/products");
}

export function getParamChips(): Promise<ParamTable<ParamChip>> {
  return apiFetch<ParamTable<ParamChip>>("/api/v1/params/chips");
}
