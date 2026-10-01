"use client";

import { useEffect, useMemo, useState } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { cn } from "@/lib/cn";
import { useI18n } from "@/lib/i18n";
import type { PriceDateCount } from "@/lib/types";

interface Props {
  /** 有抓取数据的日期及条数（升序） */
  dateCounts: PriceDateCount[];
  /** 当前选中日期 YYYY-MM-DD */
  selected: string | null;
  onSelect: (date: string) => void;
  /** 紧凑模式：隐藏底部说明文案（用于顶部弹层复用） */
  compact?: boolean;
}

function pad(n: number): string {
  return n < 10 ? `0${n}` : String(n);
}
function iso(y: number, m: number, d: number): string {
  return `${y}-${pad(m + 1)}-${pad(d)}`;
}
const WEEKDAYS = ["一", "二", "三", "四", "五", "六", "日"];

export function PriceCalendar({
  dateCounts,
  selected,
  onSelect,
  compact = false,
}: Props) {
  const { t } = useI18n();
  const avail = useMemo(() => {
    const map = new Map<string, number>();
    let min = "",
      max = "";
    for (const d of dateCounts) {
      map.set(d.date, d.count);
      if (!min || d.date < min) min = d.date;
      if (!max || d.date > max) max = d.date;
    }
    return { map, min, max };
  }, [dateCounts]);

  const initial = useMemo(() => {
    const s = selected || avail.max;
    if (!s) return { y: new Date().getFullYear(), m: new Date().getMonth() };
    const [y, m] = s.split("-").map(Number);
    return { y, m: m - 1 };
  }, [selected, avail.max]);

  const [view, setView] = useState(initial);

  // 选中日期变化时，把视图月同步到选中日所在月（仅在用户未手动导航时由这里驱动）
  useEffect(() => {
    if (selected && avail.map.has(selected)) {
      const [y, m] = selected.split("-").map(Number);
      setView({ y, m: m - 1 });
    }
  }, [selected, avail.map]);

  const year = view.y;
  const month = view.m;

  const firstDow = useMemo(() => {
    // 周一为一周起点：JS getDay() 日=0…六=6 → 转周一起点偏移
    const js = new Date(year, month, 1).getDay();
    return (js + 6) % 7;
  }, [year, month]);
  const daysInMonth = new Date(year, month + 1, 0).getDate();

  const cells: (number | null)[] = [];
  for (let i = 0; i < firstDow; i++) cells.push(null);
  for (let d = 1; d <= daysInMonth; d++) cells.push(d);

  const viewKey = `${year}-${pad(month)}`;
  const minKey = avail.min ? avail.min.slice(0, 7) : "0000-00";
  const maxKey = avail.max ? avail.max.slice(0, 7) : "9999-99";
  const canPrev = viewKey > minKey;
  const canNext = viewKey < maxKey;

  const goPrev = () => {
    if (!canPrev) return;
    setView(month === 0 ? { y: year - 1, m: 11 } : { y: year, m: month - 1 });
  };
  const goNext = () => {
    if (!canNext) return;
    setView(month === 11 ? { y: year + 1, m: 0 } : { y: year, m: month + 1 });
  };

  return (
    <div className="w-full">
      <div className="mb-2 flex items-center justify-between">
        <button
          onClick={goPrev}
          disabled={!canPrev}
          className={cn(
            "flex h-7 w-7 items-center justify-center rounded-md border border-border transition-colors",
            canPrev
              ? "text-fg-2 hover:bg-surface"
              : "cursor-not-allowed opacity-30",
          )}
          aria-label={t('上个月')}
        >
          <ChevronLeft size={16} />
        </button>
        <div className="text-[13px] font-semibold text-fg">
          {t('{y} 年 {m} 月', { y: year, m: month + 1 })}
        </div>
        <button
          onClick={goNext}
          disabled={!canNext}
          className={cn(
            "flex h-7 w-7 items-center justify-center rounded-md border border-border transition-colors",
            canNext
              ? "text-fg-2 hover:bg-surface"
              : "cursor-not-allowed opacity-30",
          )}
          aria-label={t('下个月')}
        >
          <ChevronRight size={16} />
        </button>
      </div>

      <div className="mb-1 grid grid-cols-7 gap-1 text-center text-[11px] text-muted">
        {WEEKDAYS.map((w) => (
          <div key={w} className="py-1">
            {t(w)}
          </div>
        ))}
      </div>

      <div className="grid grid-cols-7 gap-1">
        {cells.map((d, i) => {
          if (d === null) return <div key={`e${i}`} />;
          const key = iso(year, month, d);
          const has = avail.map.has(key);
          const cnt = avail.map.get(key) ?? 0;
          const isSel = selected === key;
          const inRange =
            !avail.min || !avail.max || (key >= avail.min && key <= avail.max);
          return (
            <button
              key={key}
              disabled={!has}
              onClick={() => has && onSelect(key)}
              title={has ? t('{k} · {n} 条价格', { k: key, n: cnt }) : undefined}
              className={cn(
                "relative flex h-9 flex-col items-center justify-center rounded-md text-[12px] transition-colors",
                !has && "cursor-default text-muted/40",
                has && !isSel && "border border-border text-fg-2 hover:bg-surface",
                isSel && "bg-accent text-white",
              )}
            >
              <span>{d}</span>
              {has && (
                <span
                  className={cn(
                    "mt-0.5 h-1 w-1 rounded-full",
                    isSel ? "bg-white/80" : "bg-accent",
                  )}
                />
              )}
            </button>
          );
        })}
      </div>

      {!compact && (
        <p className="mt-2 text-[11px] text-muted">
          {avail.map.size
            ? t('共 {n} 个抓取日（圆点=有数据），点击查看当日价格', { n: avail.map.size })
            : t('暂无抓取数据')}
        </p>
      )}
    </div>
  );
}
