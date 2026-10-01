"use client";

import { useEffect, useMemo, useState } from "react";
import { Layers, Check } from "lucide-react";
import { type ModelRow, type PriceBand } from "@/lib/types";
import { formatEUR } from "@/lib/format";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/cn";
import { useI18n } from "@/lib/i18n";

interface Band {
  band: PriceBand;
  label: string;
  min: number;
  max: number;
}

const DEFAULTS: Band[] = [
  { band: "entry", label: "入门", min: 0, max: 299 },
  { band: "mid", label: "中端", min: 300, max: 499 },
  { band: "upper_mid", label: "中高端", min: 500, max: 699 },
  { band: "flagship", label: "旗舰", min: 700, max: 999 },
  { band: "foldable", label: "折叠", min: 1000, max: 2000 },
];

/** 本地持久化键（与认证态 pm_jwt 同前缀） */
const STORAGE_KEY = "pm_price_bands";

/**
 * 价位带编辑器：以目标机型 unlocked 价（EUR）为锚，定义各价位段 EUR 区间。
 * 区间用于同价位段竞品发现（P1）。MVP 阶段区间配置仅存于本机浏览器（localStorage），
 * 不写后端；刷新后保留，但仅对当前浏览器生效。
 */
export function PriceBandEditor({
  targetModels,
  anchorByModel,
  loading,
}: {
  targetModels: ModelRow[];
  anchorByModel: Record<string, number>;
  loading?: boolean;
}) {
  const { t } = useI18n();
  const [bands, setBands] = useState<Band[]>(DEFAULTS);
  const [saved, setSaved] = useState(false);

  // 客户端挂载后再读取本地配置：避免 SSR 与首屏 CSR 水合不一致。
  useEffect(() => {
    try {
      const raw = window.localStorage.getItem(STORAGE_KEY);
      if (!raw) return;
      const parsed = JSON.parse(raw) as Band[];
      if (!Array.isArray(parsed) || parsed.length !== DEFAULTS.length) return;
      const byBand = new Map(parsed.map((b) => [b.band, b]));
      const merged = DEFAULTS.map((d) => {
        const stored = byBand.get(d.band);
        if (!stored) return d;
        const n = Number(stored.min);
        const m = Number(stored.max);
        return {
          ...d,
          min: Number.isFinite(n) ? n : d.min,
          max: Number.isFinite(m) ? m : d.max,
        };
      });
      setBands(merged);
    } catch {
      /* 本地配置损坏则回退默认，不阻断编辑 */
    }
  }, []);

  const counts = useMemo(() => {
    const c: Record<string, number> = {};
    for (const m of targetModels) {
      const a = anchorByModel[m.id];
      if (a == null) continue;
      const hit = bands.find((b) => a >= b.min && a <= b.max);
      if (hit) c[hit.band] = (c[hit.band] ?? 0) + 1;
    }
    return c;
  }, [targetModels, anchorByModel, bands]);

  const update = (i: number, key: "min" | "max", v: number) => {
    setSaved(false);
    setBands((prev) =>
      prev.map((b, idx) => (idx === i ? { ...b, [key]: v } : b)),
    );
  };

  const onSave = () => {
    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(bands));
      setSaved(true);
    } catch {
      setSaved(false);
    }
  };

  return (
    <section className="rounded-lg border border-border bg-surface">
      <div className="flex items-center justify-between border-b border-border px-4 py-2.5">
        <h2 className="flex items-center gap-2 text-sm font-semibold text-fg">
          <Layers size={16} className="text-accent" />
          {t("价位带编辑器")}
        </h2>
        <div className="flex items-center gap-2">
          {saved && (
            <span className="inline-flex items-center gap-1 text-[12px] text-success">
              <Check size={13} /> {t("已保存（本地）")}
            </span>
          )}
          <Button
            size="sm"
            variant="primary"
            onClick={onSave}
          >
            {t("保存价位带")}
          </Button>
        </div>
      </div>

      <div className="px-4 py-3">
        <p className="mb-3 text-[12px] text-muted">
          {t("以目标机型裸机价（EUR）为锚，定义各价位段区间，用于同价位段竞品自动分桶。当前共 {n} 款目标机型参与分桶。区间仅保存在本机浏览器，刷新后保留。", { n: targetModels.length })}
        </p>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[480px] border-collapse text-[13px]">
            <thead>
              <tr className="border-b border-border">
                <th className="th-caps px-3 py-2 text-left">{t("价位段")}</th>
                <th className="th-caps px-3 py-2 text-left">{t("下限 (EUR)")}</th>
                <th className="th-caps px-3 py-2 text-left">{t("上限 (EUR)")}</th>
                <th className="th-caps px-3 py-2 text-right">{t("命中机型")}</th>
              </tr>
            </thead>
            <tbody>
              {bands.map((b, i) => {
                const invalid = b.min > b.max;
                return (
                  <tr
                    key={b.band}
                    className="border-b border-border-soft transition-colors duration-fast ease-standard hover:bg-surface-warm"
                  >
                    <td className="px-3 py-2 font-medium text-fg">
                      {t(b.label)}
                    </td>
                    <td className="px-3 py-2">
                      <input
                        type="number"
                        value={b.min}
                        min={0}
                        onChange={(e) =>
                          update(i, "min", Number(e.target.value))
                        }
                        className={cn(
                          "tabular h-8 w-24 rounded-md border bg-bg px-2 text-sm text-fg outline-none transition-colors duration-fast ease-standard focus:border-accent",
                          invalid ? "border-danger" : "border-border",
                        )}
                      />
                    </td>
                    <td className="px-3 py-2">
                      <input
                        type="number"
                        value={b.max}
                        min={0}
                        onChange={(e) =>
                          update(i, "max", Number(e.target.value))
                        }
                        className={cn(
                          "tabular h-8 w-24 rounded-md border bg-bg px-2 text-sm text-fg outline-none transition-colors duration-fast ease-standard focus:border-accent",
                          invalid ? "border-danger" : "border-border",
                        )}
                      />
                    </td>
                    <td className="px-3 py-2 text-right">
                      <span className="tabular text-fg-2">
                        {counts[b.band] ?? 0}
                      </span>
                      <span className="ml-1 text-[11px] text-meta">{t("款")}</span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        {loading && (
          <p className="mt-2 text-[12px] text-muted">{t("正在加载锚点价…")}</p>
        )}
      </div>
    </section>
  );
}
