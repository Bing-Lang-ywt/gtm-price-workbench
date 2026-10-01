import {
  PRICE_TYPES,
  type CountryCode,
  type PriceLatest,
  type PriceType,
} from "./types";

export interface TierVal {
  amount_eur?: number | null;
  amount?: number | null;
  currency?: string | null;
  delta_pct?: number | null;
  in_stock?: boolean;
}

export interface MatrixCell {
  byTier: Partial<Record<PriceType, TierVal>>;
}

export interface MatrixRow {
  model_id: string;
  model: string;
  marketing_code: string;
  brand?: string;
  is_target?: boolean;
  cells: Partial<Record<CountryCode, MatrixCell>>;
  /** 聚焦档位下，各国金额（EUR） */
  focusedVals: Partial<Record<CountryCode, number | null>>;
  /** 聚焦档位下，跨所选国家的 max−min */
  spread?: number | null;
}

function num(v?: number | null): number | null {
  if (v == null || Number.isNaN(v)) return null;
  return v;
}

/**
 * 把 /prices/latest 扁平记录透视成「行=机型，列=国家，单元格=三档价」。
 * 同一（机型×国家×档位）取最竞争价（amount_eur 最小）作为代表报价。
 * 价差列 = 聚焦档位跨所选国家的 max−min。
 */
export function buildMatrix(
  prices: PriceLatest[],
  countries: CountryCode[],
  focusedTier: PriceType,
): MatrixRow[] {
  const byModel = new Map<string, PriceLatest[]>();
  for (const p of prices) {
    const key = p.model_id ?? p.model ?? p.sku_id;
    if (!key) continue;
    if (!byModel.has(key)) byModel.set(key, []);
    byModel.get(key)!.push(p);
  }

  const rows: MatrixRow[] = [];
  for (const [key, recs] of byModel) {
    const first = recs[0];
    const cells: Partial<Record<CountryCode, MatrixCell>> = {};
    const focusedVals: Partial<Record<CountryCode, number | null>> = {};

    for (const c of countries) {
      const cell: MatrixCell = { byTier: {} };
      let has = false;
      for (const tier of PRICE_TYPES) {
        const tierRecs = recs.filter(
          (r) =>
            (r.country_code === c || r.country === c) &&
            r.price_type === tier,
        );
        if (tierRecs.length === 0) continue;
        // 取最竞争价（amount_eur 最小，回退 amount）
        const best = tierRecs.reduce((a, b) => {
          const av = num(a.amount_eur) ?? num(a.amount);
          const bv = num(b.amount_eur) ?? num(b.amount);
          if (av == null) return b;
          if (bv == null) return a;
          return bv < av ? b : a;
        });
        cell.byTier[tier] = {
          amount_eur: num(best.amount_eur),
          amount: num(best.amount),
          currency: best.currency ?? null,
          delta_pct: num(best.delta_pct),
          in_stock: best.in_stock,
        };
        has = true;
      }
      if (has) cells[c] = cell;
      const fv = cell.byTier[focusedTier]?.amount_eur ?? null;
      focusedVals[c] = fv;
    }

    // 价差
    const present = countries
      .map((c) => focusedVals[c])
      .filter((v): v is number => v != null);
    const spread = present.length >= 2 ? Math.max(...present) - Math.min(...present) : null;

    rows.push({
      model_id: key,
      model: first.model ?? first.model_marketing_code ?? key,
      marketing_code: first.model_marketing_code ?? "",
      brand: first.brand,
      is_target: first.is_target,
      cells,
      focusedVals,
      spread,
    });
  }

  // 本品牌优先，其次按名称
  rows.sort((a, b) => {
    if (!!a.is_target !== !!b.is_target) return a.is_target ? -1 : 1;
    return a.model.localeCompare(b.model);
  });

  return rows;
}
