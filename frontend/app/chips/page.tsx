"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { BarChart3, Cpu, AlertTriangle } from "lucide-react";
import { AppShell } from "@/components/layout/AppShell";
import { Chip } from "@/components/ui/chip";
import { Badge, type Tone } from "@/components/ui/badge";
import { getParamChips } from "@/lib/api";
import type { ParamChip } from "@/lib/types";
import { useI18n } from "@/lib/i18n";

const TIER_TONE: Record<string, Tone> = {
  旗舰天花板: "accent",
  次旗舰: "accent",
  高端: "info",
  中高端: "info",
  中端: "warn",
  "中端(基准)": "warn",
  低端: "neutral",
  入门: "neutral",
};

export default function ChipsPage() {
  const { t } = useI18n();
  const [vendors, setVendors] = useState<Set<string>>(new Set());
  const [tiers, setTiers] = useState<Set<string>>(new Set());
  const [onlyInUse, setOnlyInUse] = useState(false);

  const q = useQuery({
    queryKey: ["param-chips"],
    queryFn: () => getParamChips(),
  });

  const all: ParamChip[] = q.data?.items ?? [];
  const source = q.data?.source ?? null;

  const maxScore = useMemo(
    () => all.reduce((m, c) => Math.max(m, c.score ?? 0), 0),
    [all],
  );

  const vendorList = useMemo(
    () => Array.from(new Set(all.map((c) => c.vendor).filter(Boolean))) as string[],
    [all],
  );
  const tierList = useMemo(
    () => Array.from(new Set(all.map((c) => c.tier).filter(Boolean))) as string[],
    [all],
  );

  const filtered = useMemo(() => {
    return all.filter((c) => {
      if (vendors.size && (!c.vendor || !vendors.has(c.vendor))) return false;
      if (tiers.size && (!c.tier || !tiers.has(c.tier))) return false;
      if (onlyInUse && !c.in_use) return false;
      return true;
    });
  }, [all, vendors, tiers, onlyInUse]);

  const toggleSet =
    (setter: typeof setVendors) => (val: string) =>
      setter((prev) => {
        const next = new Set(prev);
        if (next.has(val)) next.delete(val);
        else next.add(val);
        return next;
      });

  const toggleVendor = toggleSet(setVendors);
  const toggleTier = toggleSet(setTiers);

  return (
    <AppShell>
      <div className="mx-auto max-w-5xl px-5 py-5">
        <div className="mb-4">
            <h1 className="flex items-center gap-2 text-base font-semibold text-fg">
              <BarChart3 size={18} className="text-accent" />
              {t('芯片天梯图')}
            </h1>
          <p className="mt-1 text-[12px] text-muted">
            {t('按极客湾综合性能分数排序（高者居首），数据以桌面参数表 Excel 为准')}
            {source && (
              <>
                <span className="mx-1.5 text-border">·</span>
                <span className="text-meta">{t('源文件：{source}', { source })}</span>
              </>
            )}
          </p>
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
        <div className="mb-4 space-y-2">
          <div className="flex flex-wrap items-center gap-2">
            <span className="w-12 shrink-0 text-[11px] text-muted">{t('厂商')}</span>
            <Chip
              active={vendors.size === 0}
              onClick={() => setVendors(new Set())}
            >
              {t('全部')}
            </Chip>
            {vendorList.map((v) => (
              <Chip key={v} active={vendors.has(v)} onClick={() => toggleVendor(v)}>
                {v}
              </Chip>
            ))}
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <span className="w-12 shrink-0 text-[11px] text-muted">{t('梯队')}</span>
            <Chip active={tiers.size === 0} onClick={() => setTiers(new Set())}>
              {t('全部')}
            </Chip>
            {tierList.map((tier) => (
              <Chip key={tier} active={tiers.has(tier)} onClick={() => toggleTier(tier)}>
                {t(tier)}
              </Chip>
            ))}
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Chip active={onlyInUse} onClick={() => setOnlyInUse((v) => !v)}>
              {t('仅看本表使用')}
            </Chip>
            <span className="text-[11px] text-meta">
              {t('共 {n} 颗芯片', { n: filtered.length })}
            </span>
          </div>
        </div>

        {/* 天梯图 */}
        {q.isLoading ? (
          <p className="py-8 text-center text-[12px] text-muted">{t('加载中…')}</p>
        ) : filtered.length === 0 ? (
          <div className="rounded-lg border border-dashed border-border bg-surface-warm px-4 py-10 text-center text-[13px] text-muted">
            {t('无匹配芯片。')}
          </div>
        ) : (
          <div className="space-y-1.5">
            {filtered.map((c) => {
              const pct = maxScore > 0 ? ((c.score ?? 0) / maxScore) * 100 : 0;
              return (
                <div
                  key={`${c.rank}-${c.chip_name}`}
                  className="rounded-lg border border-border bg-surface px-3 py-2.5"
                >
                  {/* 顶部：排名 + 名称 + 徽标 + 分数 */}
                  <div className="mb-1.5 flex items-center gap-2">
                    <span className="w-7 shrink-0 text-center text-[13px] font-bold tabular text-meta">
                      {c.rank ?? "—"}
                    </span>
                    <Cpu
                      size={15}
                      className={c.in_use ? "shrink-0 text-accent" : "shrink-0 text-meta"}
                    />
                    <span className="min-w-0 flex-1 truncate text-[13px] font-semibold text-fg">
                      {c.chip_name}
                    </span>
                    {c.tier && (
                      <Badge tone={TIER_TONE[c.tier] ?? "neutral"}>{t(c.tier)}</Badge>
                    )}
                    {c.in_use && (
                    <Badge tone="accent" className="hidden sm:inline-flex">
                      {t('本表使用')}
                    </Badge>
                    )}
                    <span className="w-16 shrink-0 text-right text-[13px] font-semibold tabular text-accent-text">
                      {c.score != null ? c.score.toFixed(1) : "—"}
                    </span>
                  </div>
                  {/* 分数条 */}
                  <div className="flex items-center gap-2">
                    <span className="w-7 shrink-0" />
                    <div className="h-2 flex-1 overflow-hidden rounded-full bg-surface-warm">
                      <div
                        className="h-full rounded-full"
                        style={{
                          width: `${pct}%`,
                          background: c.in_use
                            ? "var(--accent)"
                            : "var(--muted)",
                          opacity: c.in_use ? 1 : 0.5,
                        }}
                      />
                    </div>
                    <span className="w-16 shrink-0 text-right text-[11px] text-meta">
                      {c.vendor ?? ""}
                    </span>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </AppShell>
  );
}
