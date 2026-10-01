"use client";

import { memo } from "react";
import { ExternalLink, Pencil, AlertTriangle } from "lucide-react";
import { cn } from "@/lib/cn";
import { formatAmount, formatEUR, formatEurInt } from "@/lib/format";
import { formatPrice } from "@/lib/matrix-format";
import type { TierVal } from "@/lib/rival-matrix";
import type { RivalRow } from "@/lib/rival-matrix";
import { Badge } from "@/components/ui/badge";
import type { ManualFillContext } from "./ManualPriceDialog";
import { useI18n } from "@/lib/i18n";

/** 官网未公布分期方案时按几期折算：取 24 期（≈2 年），与运营商主流合约期一致。 */
const FALLBACK_PERIODS = 24;

function pickVal(
  currency: "EUR" | "raw",
  raw: number | null | undefined,
  eur: number | null | undefined,
): number | null {
  if (currency === "EUR") {
    if (eur != null) return eur;
    return raw ?? null;
  }
  return raw ?? eur ?? null;
}

/** 爬后核对标记 → 中文标签 + 色调（danger=红，warn=琥珀）。 */
const FLAG_LABEL: Record<string, { label: string; tone: "danger" | "warn" }> = {
  product_mismatch: { label: "机型不符", tone: "danger" },
  actual_gt_original: { label: "价>划线价", tone: "danger" },
  out_of_band: { label: "价格异常", tone: "danger" },
  cross_channel_outlier: { label: "跨渠道离群", tone: "danger" },
  missing_original_with_badge: { label: "缺划线价", tone: "warn" },
  bundle_only: { label: "仅合约机", tone: "warn" },
  unverified_no_pdp: { label: "未验证", tone: "warn" },
};

/** 把划线价格式化成与主价格一致的字符串（复用 formatPrice 逻辑）。
 * EUR 模式用已折算的 original_price_eur；raw 模式用本地 original_price。 */
function formatOriginal(v: TierVal, currency: "EUR" | "raw"): string {
  const oe = currency === "EUR" && v.original_price_eur != null
    ? v.original_price_eur
    : v.original_price;
  return formatPrice(
    {
      amount_eur: oe ?? undefined,
      amount: v.original_price ?? undefined,
      currency: v.currency,
    } as TierVal,
    currency,
  );
}

/**
 * 从产品页 URL 的 slug 解析运存+存储，统一渲染为「6+128」或存储-only「256GB」形式。
 * 覆盖本项目全部 slug 格式：
 *   - 显式 "8gb 256gb" / "8-256gb" / "8~256-gb" / "12gb-512gb"
 *   - 段式 "-8-256-" / "_12_512_" / "~16~512"（模型数字在前的如 zfold-8-12-512 也能正确取到 12+512）
 *   - 拼接式 "8256-gb" / "12512gb" / "8256gb"（前 1-2 位=运存，后 3 位=存储）
 *   - 存储-only "256gb" / "_256GB" / "1tb"
 * 关键：先把 1tb 规整为 1024，再切分全部数字 token，对相邻 token 两两配对——
 * 这样能正确跳过模型数字（zfold-8-12-512 → 跳过 8，取 12+512），避免「首个命中吃掉 RAM 数字」的重叠匹配 bug。
 */
export function parseVariant(url?: string | null): string | null {
  if (!url) return null;
  let u = url.toLowerCase();
  u = u.replace(/%2f/gi, "/"); // URL 编码的 "/" 解码（如 6%2F128gb → 6/128gb，否则运存被吞）
  u = u.replace(/\b5g\b/g, " "); // 去掉网络制式 "5g"，避免被当成运存
  u = u.replace(/v\d+/g, " "); // 去掉机型版本号 "v6"/"v8"，避免被当成运存
  u = u.replace(/fold\d+/g, " "); // 去掉 "fold8" 等折叠屏型号数字，避免被当成运存
  u = u.replace(/magic\d+/g, " "); // 去掉机型数字 "magic8" 等，避免被当成运存（magic8pro → 8 误当运存）
  u = u.replace(/1[\s_-]?tb/gi, "1024"); // 1tb / 1-tb / 1_tb 规整为 1024
  const RAM = new Set([4, 6, 8, 12, 16, 24]);
  const STORAGE = new Set([64, 128, 256, 512, 1024]);
  const fmtS = (s: number): string => (s === 1024 ? "1TB" : `${s}GB`);
  const tryPair = (a: number, b: number): string | null => {
    if (RAM.has(a) && STORAGE.has(b)) return `${a}+${fmtS(b)}`;
    if (RAM.has(b) && STORAGE.has(a)) return `${b}+${fmtS(a)}`;
    return null;
  };
  // 1) 显式 "8gb 256gb" / "8-256gb" / "8~256-gb"（数字与 gb 之间允许 -/_）
  const m = u.match(/(\d{1,2})\s*(?:gb|g)\s*[-~]?\s*(\d{2,4})\s*[-_]?\s*(?:gb|g)/);
  if (m) {
    const r = tryPair(Number(m[1]), Number(m[2]));
    if (r) return r;
  }
  // 2) 只取「被分隔符/边界包围」的独立数字 token（排除 fold8 / v6 / a57 等嵌在词里的数字），
  //    相邻两两配对 → 自动跳过模型数字，正确取到 ram+storage（如 zfold-8-12-512 → 12+512）
  const tokens = (u.split(/[^0-9]+/).filter((p) => /^\d+$/.test(p)) || []).map(Number);
  for (let i = 0; i < tokens.length - 1; i++) {
    const r = tryPair(tokens[i], tokens[i + 1]);
    if (r) return r;
  }
  if (tokens.includes(1024)) return "1TB"; // 仅 1TB 存储（slug 无运存 token）
  // 3) 拼接式 "8256" / "12512"（前 1-2 位=运存，后 3 位=存储）
  for (const mm of u.matchAll(/(\d{1,2})(128|256|512|064)(?:gb|g)?/g)) {
    const r = tryPair(Number(mm[1]), Number(mm[2]));
    if (r) return r;
  }
  // 4) 存储-only 降级："256gb" / "256-gb" / "256 gb"
  const so = u.match(/(\d{2,4})\s*[-_]?\s*(?:gb|g)\b/);
  if (so) {
    const s = Number(so[1]);
    if (STORAGE.has(s)) return fmtS(s);
  }
  return null;
}

/** 价格下方跳转按钮：精确商品页(PDP) > 渠道商品列表/搜索 > 渠道官网兜底。 */
export const ProductLinkButton = memo(function ProductLinkButton({
  productUrl,
  listingUrl,
  fallback,
  variants,
}: {
  productUrl?: string | null;
  listingUrl?: string | null;
  fallback?: string | null;
  variants?: string[] | null;
}) {
  const { t } = useI18n();
  const target = productUrl || listingUrl || fallback || "";
  if (!target) return null;
  const isProduct = !!productUrl;
  const isListing = !productUrl && !!listingUrl;
  const label = isProduct ? t("产品页") : isListing ? t("渠道页") : t("官网");
  const title = isProduct
    ? t("查看产品页")
    : isListing
      ? t("前往渠道商品列表")
      : t("前往渠道官网");
  return (
    <a
      href={target}
      target="_blank"
      rel="noopener noreferrer"
      title={title}
      className="inline-flex items-center gap-1 rounded border border-accent/40 bg-accent/10 px-1.5 py-0.5 text-[10px] font-medium text-accent transition-colors duration-fast ease-standard hover:bg-accent/20"
    >
      <ExternalLink size={11} />
      {label}
      {variants && variants.length > 0 && (
        <span className="ml-0.5 rounded bg-surface px-1 text-[9px] font-semibold text-muted">
          {variants.join(" / ")}
        </span>
      )}
    </a>
  );
});

/** 常驻于每个价格旁的「修改/校正价格」图标按钮（SVG 描边图标，非 emoji）。 */
export function EditPriceButton({
  ctx,
  onFill,
  title,
}: {
  ctx?: ManualFillContext | null;
  onFill?: (c: ManualFillContext) => void;
  title?: string;
}) {
  const { t } = useI18n();
  if (!ctx?.skuId) return null;
  return (
    <button
      type="button"
      onClick={() => onFill?.(ctx)}
      title={title ?? t("修改 / 校正价格")}
      aria-label={title ?? t("修改价格")}
      className="inline-flex h-5 w-5 shrink-0 items-center justify-center rounded text-meta transition-colors duration-fast ease-standard hover:bg-accent/10 hover:text-accent"
    >
      <Pencil size={11} />
    </button>
  );
}

export const PriceCell = memo(function PriceCell({
  v,
  currency,
  fillContext,
  onFill,
  outright = false,
}: {
  v?: TierVal;
  currency: "EUR" | "raw";
  fillContext?: ManualFillContext | null;
  onFill?: (ctx: ManualFillContext) => void;
  /** 运营商「直接购买」行：隐藏与一次性付清价重复的「合约价」注解（分期另起一行） */
  outright?: boolean;
}) {
  const { t } = useI18n();
  // 只要有可编辑的 (sku + 渠道) 上下文就常驻显示编辑图标：
  // 已抓到价、缺价、未上架但有待补链接 三类单元格都允许改价。
  const fillable = !!fillContext?.skuId;

  if (v?.unavailable) {
    return (
      <div className="leading-tight">
        <span className="inline-flex items-center rounded border border-border bg-surface-warm px-1.5 py-0.5 text-[11px] font-medium text-muted">
          {v.unavailableLabel ?? t('未上架')}
        </span>
        {fillable && (
          <button
            type="button"
            onClick={() => onFill?.(fillContext!)}
            className="mt-1 inline-flex items-center gap-1 rounded border border-dashed border-accent/50 bg-accent/5 px-1.5 py-0.5 text-[10px] font-medium text-accent transition-colors duration-fast ease-standard hover:bg-accent/15"
          >
            <Pencil size={10} /> {t('填价')}
          </button>
        )}
      </div>
    );
  }

  // 机型不符 / 未验证：价格来自错误机型或根本无 PDP。按"错价不如不填"原则，
  // 不展示错误数字，仅以核对徽标提示需人工复核（其余审计标记仍展示真实价 + 红标）。
  if (v?.flag === "product_mismatch" || v?.flag === "unverified_no_pdp") {
    const info = FLAG_LABEL[v.flag];
    return (
      <div className="leading-tight">
        <span
          className={cn(
            "inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-[10px] font-medium",
            v.flag === "unverified_no_pdp"
              ? "border-warn/30 bg-warn/10 text-warn-strong"
              : "border-danger/40 bg-danger/10 text-danger",
          )}
          title={`${t('核对异常：')}${t(info?.label ?? v.flag)}`}
        >
          <AlertTriangle size={10} /> {t(info?.label ?? v.flag)}
        </span>
      </div>
    );
  }

  if (!v || (v.amount_eur == null && v.amount == null)) {
    const reason = v?.reason ?? t('未录入');
    return (
      <div className="leading-tight">
        <span className="text-[10px] text-meta">{reason}</span>
        {fillable && (
          <button
            type="button"
            onClick={() => onFill?.(fillContext!)}
            className="mt-1 inline-flex items-center gap-1 rounded border border-dashed border-accent/50 bg-accent/5 px-1.5 py-0.5 text-[10px] font-medium text-accent transition-colors duration-fast ease-standard hover:bg-accent/15"
          >
            <Pencil size={10} /> {t('填价')}
          </button>
        )}
      </div>
    );
  }

  // 爬后核对标记：光标悬停/常驻红色（或琥珀）徽标，提示该价格需人工复核。
  const flagInfo = v?.flag ? FLAG_LABEL[v.flag] ?? { label: v.flag, tone: "danger" } : null;
  // 划线价（原价）→ 仅当划线价高于实际价时才有意义，展示「划线价 + 省X€ 优惠」。
  // EUR 模式必须用 original_price_eur（已折算），否则会把 HUF 等本地数值当 EUR，
  // 出现"省 25 万 €"这类荒谬数字（如 Yettel HU DemoBrand 600 划线 251 990 Ft 被误渲为 251 990 €）。
  const actualVal = currency === "EUR" ? v?.amount_eur : v?.amount;
  const origForCompare =
    currency === "EUR" && v?.original_price_eur != null
      ? v.original_price_eur
      : v?.original_price;
  const hasOriginal =
    origForCompare != null && actualVal != null && (origForCompare as number) > (actualVal as number);
  const discount = hasOriginal
    ? ((origForCompare as number) - (actualVal as number))
    : null;
  // 运营商合约注解。大字号价格统一是「裸机标价」（跨渠道可比），这一行补上
  // 签约后的真实成本结构：合约设备实付价 + 含资费的整单月付。
  // 二者都只作注解——月付含资费、全机型同值，绝不能进「月付」行参与跨渠道比较；
  // 合约价基准各家不同，进主列曾造成 Yettel/Telekom 之间 77% 的假价差。
  // EUR 模式必须用已折算的 *_eur 字段，否则 26 609 HUF 会被当 26 609 € 渲染。
  const unit = currency === "EUR" ? " €" : ` ${v?.currency ?? ""}`;
  const contractDev =
    currency === "EUR" ? v?.contract_device_price_eur : v?.contract_device_price;
  const monthlyRaw =
    currency === "EUR" ? v?.monthly_payable_eur : v?.monthly_payable;
  const notes: string[] = [];
  // 直接购买行本身就是一次性付清的设备价 →「合约价」注解纯属重复，隐藏；
  // 分期明细已独立成「分期购买」行，也不再塞进这里。
  // 0 是有效值（签约赠机），所以判空必须用 != null 而不是 truthy。
  if (!outright && contractDev != null) {
    notes.push(
      contractDev === 0
        ? t('签约赠机 0')
        : t('合约价 {amt}', { amt: `${formatEurInt(contractDev)}${unit}` }),
    );
  }
  // 套餐月费是含资费的整单账单，与设备分期无关；仅作注解，绝不参与比较。
  if (monthlyRaw != null && monthlyRaw > 0) {
    notes.push(t('套餐 {amt}/月', { amt: `${formatEurInt(monthlyRaw)}${unit}` }));
  }
  const noteText = notes.length ? notes.join(" · ") : null;

  return (
    <div className="leading-tight">
      {flagInfo && (
        <div
          className={cn(
            "mb-0.5 inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-[10px] font-medium",
            flagInfo.tone === "danger"
              ? "border-danger/40 bg-danger/10 text-danger"
              : "border-warn/30 bg-warn/10 text-warn-strong",
          )}
          title={`${t('核对异常：')}${t(flagInfo.label)}`}
        >
          <AlertTriangle size={10} /> {t(flagInfo.label)}
        </div>
      )}
      <div className="flex items-center gap-1.5">
        <span className="tabular text-[13px] font-semibold text-fg">
          {formatPrice(v, currency)}
        </span>
        {fillable && (
          <EditPriceButton ctx={fillContext} onFill={onFill} title={t('修改 / 校正价格')} />
        )}
      </div>
      {hasOriginal && discount != null && (
        <div className="mt-0.5 flex items-center gap-1.5 text-[10px]">
          <span className="text-meta line-through tabular">
            {formatOriginal(v!, currency)}
          </span>
            <span className="font-medium text-success tabular">
              {t('省')} {formatEurInt(discount)}
            {currency === "EUR" ? " €" : ` ${v?.currency ?? ""}`}
          </span>
        </div>
      )}
      {noteText && (
        <div
          className="mt-0.5 text-[10px] text-meta"
          title={t('签约后的成本结构：合约设备实付价 + 含资费套餐的整单月付（非设备分期，全机型同值）。仅供参考，不参与跨渠道比较与最低价排名——上方大字号价格才是可比的裸机标价。')}
        >
          {noteText}
        </div>
      )}
      {v.in_stock === false && (
        <div className="text-[10px] text-danger">{t('缺货')}</div>
      )}
    </div>
  );
});

/**
 * 运营商「分期购买」单元格：`月付 × 期数 = 总价`。
 *
 * 期数优先取官网方案（meta.installment，爬取自页面的 "22 × 32 478 Ft" / "22 havi" 等
 * 真实表述，且已按「最接近 24 期」筛过）。抓不到官网期数时，才用设备总价 ÷ 月付反推，
 * 并标上「按 24 期折算」的提示，绝不冒充官网数字——用户明确要求期数以官网为准。
 */
export const InstallmentCell = memo(function InstallmentCell({
  device,
  monthly,
  currency,
  fillContext,
  onFill,
}: {
  device?: TierVal;
  monthly?: TierVal;
  currency: "EUR" | "raw";
  fillContext?: ManualFillContext | null;
  onFill?: (ctx: ManualFillContext) => void;
}) {
  const { t } = useI18n();
  const unit = currency === "EUR" ? " €" : ` ${device?.currency ?? monthly?.currency ?? ""}`;
  const inst = currency === "EUR" ? device?.installment_eur : device?.installment;
  const deviceTotal = pickVal(currency, device?.amount, device?.amount_eur);

  let periods: number | null = null;
  let perMonth: number | null = null;
  let estimated = false;

  if (inst && inst.periods && inst.monthly != null) {
    // 官网方案：月付与期数都来自页面真实表述（"22 × 8 708 Ft" / "12 rat" …）
    periods = inst.periods;
    perMonth = inst.monthly;
  } else if (deviceTotal != null && deviceTotal > 0) {
    // 抓不到官网期数：按 24 期（≈2 年）把设备总价摊平。
    // 不拿 contract_monthly 反推期数——那会算出 20.5 期这种畸形值。
    periods = FALLBACK_PERIODS;
    perMonth = deviceTotal / FALLBACK_PERIODS;
    estimated = true;
  }

  if (periods == null || perMonth == null) {
    return (
      <div className="flex items-center gap-1.5">
        <span className="text-[10px] text-meta">{t('无分期数据')}</span>
        {fillContext?.skuId && onFill ? (
          <EditPriceButton ctx={fillContext} onFill={onFill} title={t('修改 / 校正分期')} />
        ) : null}
      </div>
    );
  }

  // 展示的「总价」= 月付 × 期数（与页面等式自洽；站点月付本身是四舍五入值，
  // 与一次性付清价可能差几 Ft，属正常）。
  const total = perMonth * periods;

  return (
    <div className="leading-tight">
      <div className="flex items-center gap-1.5">
        <span className="tabular text-[13px] font-semibold text-fg">
          {formatAmount(perMonth)}
          {unit} × {periods}
          {t('期')} = {formatEurInt(total)}
          {unit}
        </span>
        {fillContext?.skuId && onFill ? (
          <EditPriceButton ctx={fillContext} onFill={onFill} title={t('修改 / 校正分期')} />
        ) : null}
      </div>
      <div className="mt-0.5 text-[10px] text-meta">
        {estimated
          ? t('官网未公布期数 · 按 {n} 期折算', { n: FALLBACK_PERIODS })
          : t('官网分期方案')}
      </div>
    </div>
  );
});

export const CompetitiveCell = memo(function CompetitiveCell({
  c,
}: {
  c: RivalRow["competitiveness"];
}) {
  if (!c) return <span className="text-meta">—</span>;
  const pctAbs = Math.abs((c.pct ?? 0) * 100);
  const pctText = c.pct == null ? "" : `${pctAbs.toFixed(0)}%`;
  return (
    <div className="leading-tight">
      <Badge
        tone={
          c.tone === "positive"
            ? "success"
            : c.tone === "negative"
              ? "danger"
              : "neutral"
        }
      >
        {c.label}
      </Badge>
      <div
        className={cn(
          "mt-0.5 text-[11px] font-medium",
          c.tone === "positive" && "text-success",
          c.tone === "negative" && "text-danger",
          c.tone === "neutral" && "text-meta",
        )}
      >
        {c.diffEur >= 0 ? "+" : ""}
        {formatEUR(c.diffEur)}
      </div>
      {pctText && <div className="text-[10px] text-meta">{pctText}</div>}
    </div>
  );
});
