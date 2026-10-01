import {
  COUNTRY_BY_CODE,
  type ChannelType,
  type CountryCode,
  type PriceLatest,
  type PriceType,
} from "./types";
import type { CompetitorRef } from "./types";

/** 单个价格值（裸机 / 合约月租 / 补贴首付） */
export interface TierVal {
  amount_eur?: number | null;
  amount?: number | null;
  currency?: string | null;
  in_stock?: boolean;
  /** 精确机型商品页(PDP)链接 */
  product_url?: string | null;
  /** 渠道商品列表/搜索页链接（PDP 缺失时回退） */
  listing_url?: string | null;
  /** 该(渠道×产品)在 sku 层标记为未上架/待补，无价格记录 */
  unavailable?: boolean;
  /** 未上架态文案：「未上架」或「待补」 */
  unavailableLabel?: string;
  /** sku 入库备注（如「未上架(Excel)」），便于核对 */
  note?: string;
  /** 无价原因：未上架 / 待补 / 有链接未抓到价 / 无链接 / 未录入 */
  reason?: string | null;
  /** 是否可人工补录价格（存在 sku 即有补录入口） */
  canManualFill?: boolean;
  /** 关联的 sku id，供人工补录价格使用 */
  sku_id?: string | null;
  /** 无链接态：抑制渠道兜底官网/渠道页链接，仅展示「未上架」 */
  noLink?: boolean;
  /** 划线价（原价/促销前价），用于展示优惠力度；无则为 null */
  original_price?: number | null;
  /** 划线价 EUR 折算值（来自后端 original_price_eur）；EUR 模式展示划线/折扣用，避免 HUF 等本地值被当 EUR 渲染 */
  original_price_eur?: number | null;
  /** 实体赠品文案（如「送耳机」）；无则为 null */
  gift?: string | null;
  /** 爬后核对标记；无则为 null */
  flag?: string | null;
  /** 套餐月费（本地货币）；非设备分期、不参与比较，仅作「设备费 + X/月」注解 */
  monthly_payable?: number | null;
  /** 套餐月费 EUR 折算值；EUR 模式必须用它，否则本地数值会被当 EUR 渲染 */
  monthly_payable_eur?: number | null;
  /** 合约设备实付价（本地货币）；仅注解，0=签约赠机是有效值，判空须用 != null */
  contract_device_price?: number | null;
  /** 合约设备实付价 EUR 折算值 */
  contract_device_price_eur?: number | null;
  /** 设备分期明细（本地货币）：{ monthly, periods, total }；月付 × 期数 = 总价，
   *  仅注解展示（一次性付清 vs 分期对比），不参与跨渠道比较/排名 */
  installment?: { monthly: number; periods: number; total: number } | null;
  /** 设备分期明细 EUR 折算值；EUR 模式必须用它，否则本地数值会被当 EUR 渲染 */
  installment_eur?: { monthly: number; periods: number; total: number } | null;
}

/** 前端从 /skus 构建的 (渠道×产品) → sku 快照，用于富化矩阵单元格 */
export interface SkuSnapshot {
  sku_id?: string | null;
  product_url?: string | null;
  in_stock?: boolean | null;
  note?: string | null;
}

/** 一个产品在一个渠道下的完整呈现单元（价格 / 月付 / 赠品 / 链接） */
export interface ProductCell {
  /** 主价格（market=unlocked；operator=由档位决定 subsidy_down_payment/contract_monthly） */
  price?: TierVal;
  /** 运营商合约月租（仅 operator，用于「月付」行） */
  monthly?: TierVal;
  /** 赠品文案；null/undefined 表示无数据，前端显示「—」 */
  gift?: string | null;
  /** 精确商品页链接（用于「链接」行） */
  product_url?: string | null;
  /** 渠道列表页链接（PDP 缺失时回退） */
  listing_url?: string | null;
  /** 是否可人工补录 */
  canManualFill?: boolean;
  /** 关联 sku id */
  sku_id?: string | null;
  /** 无链接态：抑制渠道兜底官网/渠道页链接，仅展示「未上架」 */
  noLink?: boolean;
}

/** 一个竞品列（含其对应单元格） */
export interface CompetitorColumn {
  ref: CompetitorRef;
  cell: ProductCell;
}

export interface RivalRow {
  countryCode: CountryCode;
  countryName: string;
  channelId: string;
  channelName: string;
  channelType: ChannelType;
  demobrand?: ProductCell;
  competitors: CompetitorColumn[];
  /** 荣耀对比主对位竞品（position=0）的竞争力评估 */
  competitiveness?: {
    diffEur: number;
    pct: number | null;
    label: string;
    tone: "positive" | "negative" | "neutral";
    rivalBrand: string;
    rivalCode: string;
  } | null;
  /** 渠道官网兜底链接（无 SKU 产品页时使用） */
  channelBaseUrl?: string | null;
  /** 渠道商品列表/搜索页链接（PDP 缺失时回退） */
  channelListingUrl?: string | null;
}

function num(v?: number | null): number | null {
  if (v == null || Number.isNaN(v)) return null;
  return v;
}

function bestPrice(
  prices: PriceLatest[],
  countryCode: CountryCode,
  channelId: string,
  modelId: string | undefined | null,
  priceType: PriceType,
  skuMap?: Map<string, SkuSnapshot>,
): TierVal | undefined {
  if (!modelId) return undefined;
  const recs = prices.filter(
    (p) =>
      (p.country_code === countryCode || p.country === countryCode) &&
      p.channel_id === channelId &&
      p.model_id === modelId &&
      p.price_type === priceType,
  );
  if (recs.length === 0) {
    // 无价格记录：按「是否有链接」区分三种单元格状态
    if (skuMap) {
      const sku = skuMap.get(`${channelId}|${modelId}`);
      if (sku) {
        const hasLink = !!sku.product_url;
        return {
          amount_eur: null,
          amount: null,
          currency: null,
          in_stock: sku.in_stock ?? undefined,
          product_url: sku.product_url ?? null,
          listing_url: null,
          unavailable: true,
          unavailableLabel: hasLink ? "有链接无法获取价格" : "未上架",
          note: sku.note ?? "",
          reason: hasLink ? "有链接无法获取价格" : "未上架",
          canManualFill: hasLink,
          sku_id: sku.sku_id ?? null,
          noLink: !hasLink,
        };
      }
    }
    // 无 sku、无价格记录：该渠道×机型尚未收录进系统
    return {
      amount_eur: null,
      amount: null,
      currency: null,
      unavailable: true,
      unavailableLabel: "未上架",
      reason: "未上架",
      canManualFill: false,
      sku_id: null,
      noLink: true,
    };
  }
  const best = recs.reduce((a, b) => {
    const av = num(a.amount_eur) ?? num(a.amount);
    const bv = num(b.amount_eur) ?? num(b.amount);
    if (av == null) return b;
    if (bv == null) return a;
    return bv < av ? b : a;
  });
  return {
    amount_eur: num(best.amount_eur),
    amount: num(best.amount),
    currency: best.currency ?? null,
    in_stock: best.in_stock,
    product_url: best.product_url ?? null,
    listing_url: best.listing_url ?? null,
    sku_id: best.sku_id ?? null,
    original_price: num(best.original_price),
    original_price_eur: num(best.original_price_eur),
    gift: best.gift ?? null,
    flag: best.flag ?? null,
    monthly_payable: num(best.monthly_payable),
    monthly_payable_eur: num(best.monthly_payable_eur),
    contract_device_price: num(best.contract_device_price),
    contract_device_price_eur: num(best.contract_device_price_eur),
    installment: best.installment ?? null,
    installment_eur: best.installment_eur ?? null,
  };
}

function buildProductCell(
  prices: PriceLatest[],
  countryCode: CountryCode,
  channelId: string,
  modelId: string | undefined | null,
  mainType: PriceType,
  channelType: ChannelType,
  skuMap?: Map<string, SkuSnapshot>,
): ProductCell {
  const price = bestPrice(prices, countryCode, channelId, modelId, mainType, skuMap);
  const monthly =
    channelType === "operator"
      ? bestPrice(prices, countryCode, channelId, modelId, "contract_monthly", skuMap)
      : undefined;
  return {
    price,
    monthly,
    gift: price?.gift ?? null,
    product_url: price?.product_url ?? null,
    listing_url: price?.listing_url ?? null,
    canManualFill: price?.canManualFill ?? false,
    sku_id: price?.sku_id ?? null,
    noLink: price?.noLink ?? false,
  };
}

export function buildRivalRows(
  prices: PriceLatest[],
  competitors: CompetitorRef[],
  demobrandModelId: string,
  countries: CountryCode[],
  skuMap?: Map<string, SkuSnapshot>,
  opts?: {
    channelsById?: Map<
      string,
      {
        name: string;
        type: ChannelType;
        countryCode: CountryCode;
        baseUrl: string | null;
        listingUrl: string | null;
      }
    >;
    /** 顶部「档位」选择器：all=三档并列；其余=单档位主显（裸机价/合约月租/补贴首付） */
    priceMode?: "all" | PriceType;
  },
): RivalRow[] {
  // Channel 类型优先用后端补出的 channel_type，否则按已知运营商名推断。
  const isOperatorName = (name: string) =>
    /yettel|mts|telemach|telekom|one|orange|vodafone/i.test(name);

  const channelMap = new Map<
    string,
    {
      id: string;
      name: string;
      type: ChannelType;
      countryCode: CountryCode;
      baseUrl: string | null;
      listingUrl: string | null;
    }
  >();
  for (const p of prices) {
    const cc = (p.country_code ?? p.country) as CountryCode | undefined;
    if (!cc || !countries.includes(cc)) continue;
    if (!p.channel_id || !p.channel) continue;
    const key = `${cc}|${p.channel_id}`;
    if (!channelMap.has(key)) {
      const type: ChannelType =
        (p.channel_type as ChannelType) ||
        (isOperatorName(p.channel) ? "operator" : "market");
      channelMap.set(key, {
        id: p.channel_id,
        name: p.channel,
        type,
        countryCode: cc,
        baseUrl: p.channel_base_url || null,
        listingUrl: p.listing_url || null,
      });
    }
  }

  // 从 skuMap 补充渠道：让有 SKU 但无价格的渠道也出现在矩阵里
  const relevantModels = new Set<string>([demobrandModelId, ...competitors.map((c) => c.id)]);
  if (skuMap && opts?.channelsById) {
    for (const [key, _sku] of skuMap) {
      const sep = key.indexOf("|");
      const channelId = key.slice(0, sep);
      const modelId = key.slice(sep + 1);
      if (!relevantModels.has(modelId)) continue;
      const meta = opts.channelsById.get(channelId);
      if (!meta) continue;
      const cc = meta.countryCode;
      if (!countries.includes(cc)) continue;
      const k = `${cc}|${channelId}`;
      if (channelMap.has(k)) continue;
      channelMap.set(k, {
        id: channelId,
        name: meta.name,
        type: meta.type,
        countryCode: cc,
        baseUrl: meta.baseUrl,
        listingUrl: meta.listingUrl,
      });
    }
  }

  const rows: RivalRow[] = [];
  for (const [, ch] of channelMap) {
    const chType: ChannelType = ch.type;
    const defaultType: PriceType =
      chType === "operator" ? "subsidy_down_payment" : "unlocked";

    // 档位选择器：单档位模式下，主显价格直接取该档位；三档并列(all)沿用默认逻辑。
    const mode = opts?.priceMode ?? "all";
    const tierSupported = (pt: PriceType): boolean =>
      chType === "operator"
        ? pt === "subsidy_down_payment" || pt === "contract_monthly"
        : pt === "unlocked";

    const hasPriceType = (modelId: string | undefined | null, pt: PriceType): boolean =>
      prices.some(
        (p) =>
          (p.country_code === ch.countryCode || p.country === ch.countryCode) &&
          p.channel_id === ch.id &&
          p.model_id === modelId &&
          p.price_type === pt,
      );

    const mainType = (modelId: string | undefined | null): PriceType =>
      mode !== "all"
        ? (mode as PriceType)
        : chType === "operator" && !hasPriceType(modelId, "subsidy_down_payment")
          ? "contract_monthly"
          : defaultType;

    const demobrandCell = buildProductCell(
      prices,
      ch.countryCode,
      ch.id,
      demobrandModelId,
      mainType(demobrandModelId),
      chType,
      skuMap,
    );

    // 单档位模式下，本渠道类型不提供该档位 → 中性「不适用」
    if (
      mode !== "all" &&
      demobrandCell.price?.unavailable &&
      !tierSupported(mode as PriceType)
    ) {
      demobrandCell.price.unavailableLabel = "不适用";
      demobrandCell.price.reason = "不适用";
      demobrandCell.price.canManualFill = false;
      demobrandCell.canManualFill = false;
    }

    const competitorCols: CompetitorColumn[] = competitors.map((ref) => {
      const cell = buildProductCell(
        prices,
        ch.countryCode,
        ch.id,
        ref.id,
        mainType(ref.id),
        chType,
        skuMap,
      );
      if (
        mode !== "all" &&
        cell.price?.unavailable &&
        !tierSupported(mode as PriceType)
      ) {
        cell.price.unavailableLabel = "不适用";
        cell.price.reason = "不适用";
        cell.price.canManualFill = false;
        cell.canManualFill = false;
      }
      return { ref, cell };
    });

    // 竞争力：荣耀 vs 主对位竞品（position=0）
    let competitiveness: RivalRow["competitiveness"] | undefined;
    const primary = competitorCols[0];
    if (
      primary &&
      demobrandCell.price?.amount_eur != null &&
      primary.cell.price?.amount_eur != null &&
      primary.cell.price.amount_eur > 0
    ) {
      const diff = demobrandCell.price.amount_eur - primary.cell.price.amount_eur;
      const pct = diff / primary.cell.price.amount_eur;
      const label = pct < -0.05 ? "较强" : pct > 0.05 ? "较弱" : "持平";
      competitiveness = {
        diffEur: diff,
        pct,
        label,
        tone: pct < 0 ? "positive" : pct > 0 ? "negative" : "neutral",
        rivalBrand: primary.ref.brand,
        rivalCode: primary.ref.marketing_code,
      };
    }

    rows.push({
      countryCode: ch.countryCode,
      countryName: COUNTRY_BY_CODE[ch.countryCode]?.name ?? ch.countryCode,
      channelId: ch.id,
      channelName: ch.name,
      channelType: chType,
      demobrand: demobrandCell,
      competitors: competitorCols,
      competitiveness,
      channelBaseUrl: ch.baseUrl,
      channelListingUrl: ch.listingUrl,
    });
  }

  // 排序：国家 → 渠道类型（公开市场在前）→ 渠道名
  rows.sort((a, b) => {
    if (a.countryCode !== b.countryCode) {
      return countries.indexOf(a.countryCode) - countries.indexOf(b.countryCode);
    }
    if (a.channelType !== b.channelType) {
      return a.channelType === "market" ? -1 : 1;
    }
    return a.channelName.localeCompare(b.channelName);
  });

  return rows;
}
