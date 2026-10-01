"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Columns3, ExternalLink, X, Search, AlertTriangle } from "lucide-react";
import { AppShell } from "@/components/layout/AppShell";
import { Chip } from "@/components/ui/chip";
import { getParamProducts } from "@/lib/api";
import type { ParamProduct } from "@/lib/types";
import { useI18n } from "@/lib/i18n";
import { toEnglishSpec } from "@/lib/spec-en";

const MAX_SELECT = 6;

/** 参与对比的参数行（顺序即展示顺序） */
const PARAM_FIELDS: { key: keyof ParamProduct; label: string }[] = [
  { key: "brand", label: "品牌" },
  { key: "category", label: "分类" },
  { key: "release_time", label: "上市时间" },
  { key: "price_rmb", label: "RMB价格" },
  { key: "price_eur", label: "EUR价格" },
  { key: "screen", label: "屏幕" },
  { key: "chip", label: "芯片" },
  { key: "front_camera", label: "前置" },
  { key: "rear_camera", label: "后置" },
  { key: "battery", label: "电池" },
  { key: "wired_charging_w", label: "有线充电(W)" },
  { key: "wireless_charging_w", label: "无线充电(W)" },
  { key: "dimensions", label: "机身尺寸" },
  { key: "ip_rating", label: "防尘防水" },
  { key: "colors", label: "颜色" },
  { key: "top_selling_point", label: "Top卖点" },
];

function prodKey(p: ParamProduct): string {
  return `${p.brand ?? ""}::${p.product ?? ""}`;
}

function renderVal(v: unknown): string {
  if (v == null) return "—";
  return String(v);
}

export default function ComparePage() {
  const { t, lang } = useI18n();
  const [selected, setSelected] = useState<string[]>([]);
  const [brand, setBrand] = useState<string>("all");
  const [query, setQuery] = useState("");

  /** 规格值展示：英文模式下把 Excel 里的中文标注（单位/分类/摄像头/日期等）转成英文 */
  const specVal = (p: ParamProduct, key: keyof ParamProduct): string => {
    const raw = renderVal(p[key]);
    return lang === "en" ? toEnglishSpec(raw) : raw;
  };

  const q = useQuery({
    queryKey: ["param-products"],
    queryFn: () => getParamProducts(),
  });

  const all: ParamProduct[] = q.data?.items ?? [];
  const source = q.data?.source ?? null;

  const brands = useMemo(
    () => Array.from(new Set(all.map((p) => p.brand).filter(Boolean))) as string[],
    [all],
  );

  const filtered = useMemo(() => {
    const kw = query.trim().toLowerCase();
    return all.filter((p) => {
      if (brand !== "all" && p.brand !== brand) return false;
      if (kw) {
        const hay = `${p.brand ?? ""} ${p.product ?? ""} ${p.chip_name ?? ""}`.toLowerCase();
        if (!hay.includes(kw)) return false;
      }
      return true;
    });
  }, [all, brand, query]);

  const selectedProducts = useMemo(
    () => all.filter((p) => selected.includes(prodKey(p))),
    [all, selected],
  );

  const toggle = (key: string) => {
    setSelected((prev) => {
      if (prev.includes(key)) return prev.filter((k) => k !== key);
      if (prev.length >= MAX_SELECT) return prev;
      return [...prev, key];
    });
  };

  const allValues = (key: keyof ParamProduct) =>
    selectedProducts.map((p) => renderVal(p[key]).trim());

  const isDiff = (key: keyof ParamProduct) => {
    const vals = allValues(key).filter((v) => v !== "—" && v !== "");
    return vals.length > 1 && new Set(vals).size > 1;
  };

  return (
    <AppShell>
      <div className="mx-auto max-w-6xl px-5 py-5">
        <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
          <div>
            <h1 className="flex items-center gap-2 text-base font-semibold text-fg">
              <Columns3 size={18} className="text-accent" />
              {t('参数对比')}
            </h1>
            <p className="mt-1 text-[12px] text-muted">
              {t('多机型参数横向对比，数据以桌面参数表 Excel 为准')}
              {source && (
                <>
                  <span className="mx-1.5 text-border">·</span>
                  <span className="text-meta">{t('源文件：{source}', { source })}</span>
                </>
              )}
            </p>
          </div>
          {selected.length > 0 && (
            <button
              type="button"
              onClick={() => setSelected([])}
              className="inline-flex items-center gap-1 rounded-md border border-border bg-surface px-2.5 py-1.5 text-[12px] font-medium text-fg-2 transition-colors duration-fast ease-standard hover:bg-surface-warm"
            >
              <X size={13} />
              {t('清空对比（{n}）', { n: selected.length })}
            </button>
          )}
        </div>

        {source === null && (
          <div className="mb-4 flex items-start gap-2 rounded-md border border-border bg-surface-warm px-3 py-2.5 text-[12px] text-danger">
            <AlertTriangle size={15} className="mt-0.5 shrink-0" />
            <span>
              {t('未找到参数表 Excel（桌面文件与 backend/data 副本均缺失）。请确认')}
              <code className="mx-1 rounded bg-surface px-1">PARAMS_XLSX_PATH</code>
              {t('存在；部署环境请将副本拷贝到 backend/data/。')}
            </span>
          </div>
        )}

        {source && q.data?.stale && (
          <div className="mb-4 flex items-start gap-2 rounded-md border border-amber-500/40 bg-amber-500/10 px-3 py-2.5 text-[12px] text-amber-300">
            <AlertTriangle size={15} className="mt-0.5 shrink-0" />
            <span>
              {t('数据可能非最新：当前使用项目内备份副本（桌面参数表暂时不可读，可能已被移动或重命名）。 请确认')}
              <code className="mx-1 rounded bg-surface px-1">PARAMS_XLSX_PATH</code>
              {t('存在，或重新运行')}
              <code className="mx-1 rounded bg-surface px-1">scripts/sync_param_excel.sh</code>
              {t('同步兜底副本。')}
            </span>
          </div>
        )}

        {/* 筛选条 */}
        <div className="mb-4 flex flex-wrap items-center gap-2">
          <div className="relative">
            <Search
              size={14}
              className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-meta"
            />
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder={t('搜索机型 / 芯片')}
              className="h-8 w-44 rounded-md border border-border bg-surface pl-8 pr-2.5 text-[13px] text-fg outline-none transition-colors duration-fast ease-standard focus:border-accent"
            />
          </div>
          <Chip active={brand === "all"} onClick={() => setBrand("all")}>
            {t('全部品牌')}
          </Chip>
          {brands.map((b) => (
            <Chip key={b} active={brand === b} onClick={() => setBrand(b)}>
              {b}
            </Chip>
          ))}
        </div>

        {/* 产品选择（可点选加入对比） */}
        <section className="mb-5 rounded-lg border border-border bg-surface p-3">
          <div className="mb-2 flex items-center justify-between">
            <span className="text-[12px] font-semibold text-fg-2">
              {t('选择对比机型（最多 {max} 款，已选 {n}）', { max: MAX_SELECT, n: selected.length })}
            </span>
            <span className="text-[11px] text-meta">
              {t('共 {n} 款可对比', { n: filtered.length })}
            </span>
          </div>
          {q.isLoading ? (
            <p className="py-4 text-[12px] text-muted">{t('加载中…')}</p>
          ) : (
            <div className="flex flex-wrap gap-2">
              {filtered.map((p) => {
                const key = prodKey(p);
                const on = selected.includes(key);
                const disabled = !on && selected.length >= MAX_SELECT;
                return (
                  <button
                    key={key}
                    type="button"
                    disabled={disabled}
                    onClick={() => toggle(key)}
                    className={
                      "inline-flex items-center gap-1.5 rounded-pill border px-2.5 h-7 text-[12px] font-medium transition-colors duration-fast ease-standard " +
                      (on
                        ? "bg-accent-soft border-accent text-accent-text"
                        : disabled
                          ? "cursor-not-allowed border-border bg-surface-warm text-meta"
                          : "cursor-pointer border-border bg-surface text-fg-2 hover:bg-surface-warm")
                    }
                  >
                    {on && <X size={12} />}
                    <span className="text-meta">{p.brand}</span>
                    {p.product}
                  </button>
                );
              })}
              {filtered.length === 0 && (
                <p className="text-[12px] text-muted">{t('无匹配机型')}</p>
              )}
            </div>
          )}
        </section>

        {/* 对比区 */}
        {selectedProducts.length === 0 ? (
          <div className="rounded-lg border border-dashed border-border bg-surface-warm px-4 py-10 text-center text-[13px] text-muted">
            {t('请从上方选择至少 1 款机型开始对比。')}
          </div>
        ) : (
          <>
            {/* 宽屏：参数矩阵（参数行 × 产品列），差异行高亮 */}
            <div className="hidden overflow-x-auto rounded-lg border border-border bg-surface md:block">
              <table className="w-full border-collapse text-[13px]">
                <thead>
                  <tr className="border-b border-border">
                    <th className="sticky left-0 z-10 w-32 bg-surface px-3 py-2.5 text-left align-bottom text-[11px] font-semibold uppercase tracking-caps text-muted"                      >
                        {t('参数')}
                      </th>
                    {selectedProducts.map((p) => (
                      <th
                        key={prodKey(p)}
                        className="min-w-[180px] px-3 py-2.5 text-left align-bottom"
                      >
                        <div className="flex items-start justify-between gap-2">
                          <div className="min-w-0">
                            <p className="truncate text-[12px] font-medium text-meta">
                              {p.brand}
                            </p>
                            <p className="text-[13px] font-semibold text-fg">
                              {p.product}
                            </p>
                          </div>
                          <button
                            type="button"
                            onClick={() => toggle(prodKey(p))}
                            aria-label={t('移除')}
                            className="flex h-6 w-6 shrink-0 items-center justify-center rounded text-meta transition-colors duration-fast ease-standard hover:bg-surface-warm hover:text-danger"
                          >
                            <X size={13} />
                          </button>
                        </div>
                        {p.official_url && (
                          <a
                            href={p.official_url}
                            target="_blank"
                            rel="noreferrer"
                            className="mt-1 inline-flex items-center gap-1 text-[11px] text-accent transition-colors duration-fast ease-standard hover:text-accent-hover"
                          >
                            {t('官网')}
                            <ExternalLink size={11} />
                          </a>
                        )}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {PARAM_FIELDS.map((f) => {
                    const diff = isDiff(f.key);
                    return (
                      <tr
                        key={f.key}
                        className="border-b border-border-soft align-top"
                      >
                        <td
                          className={
                            "sticky left-0 z-10 bg-surface px-3 py-2.5 text-[12px] font-medium " +
                            (diff ? "text-accent-text" : "text-muted")
                          }
                        >
                          {t(f.label)}
                          {diff && (
                            <span className="ml-1 text-[10px] text-accent">
                              ●
                            </span>
                          )}
                        </td>
                        {selectedProducts.map((p) => (
                          <td
                            key={prodKey(p)}
                            className="px-3 py-2.5 align-top text-fg-2"
                          >
                            <span className="whitespace-pre-wrap break-words">
                              {specVal(p, f.key)}
                            </span>
                          </td>
                        ))}
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>

            {/* 窄屏：每款机型一张卡片，自标签不依赖表头 */}
            <div className="space-y-3 md:hidden">
              {selectedProducts.map((p) => (
                <div
                  key={prodKey(p)}
                  className="rounded-lg border border-border bg-surface p-3"
                >
                  <div className="mb-2 flex items-start justify-between gap-2 border-b border-border-soft pb-2">
                    <div>
                      <p className="text-[12px] text-meta">{p.brand}</p>
                      <p className="text-[14px] font-semibold text-fg">
                        {p.product}
                      </p>
                    </div>
                    <button
                      type="button"
                      onClick={() => toggle(prodKey(p))}
                      aria-label={t('移除')}
                      className="flex h-6 w-6 shrink-0 items-center justify-center rounded text-meta hover:bg-surface-warm hover:text-danger"
                    >
                      <X size={13} />
                    </button>
                  </div>
                  <dl className="space-y-1.5">
                    {PARAM_FIELDS.map((f) => (
                      <div key={f.key} className="flex gap-2 text-[12px]">
                        <dt className="w-20 shrink-0 text-muted">{t(f.label)}</dt>
                        <dd className="min-w-0 flex-1 whitespace-pre-wrap break-words text-fg-2">
                          {specVal(p, f.key)}
                        </dd>
                      </div>
                    ))}
                  </dl>
                </div>
              ))}
            </div>

            <p className="mt-3 text-[11px] text-meta">
              {t('标注 ')}<span className="text-accent">●</span>{t(' 的参数表示所选机型取值不同。')}
            </p>
          </>
        )}
      </div>
    </AppShell>
  );
}
