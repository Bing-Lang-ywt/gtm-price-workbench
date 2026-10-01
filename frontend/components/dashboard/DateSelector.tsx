"use client";

import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { CalendarDays, X } from "lucide-react";
import { PriceCalendar } from "./PriceCalendar";
import { getPriceDates } from "@/lib/api";
import type { PriceDateCount } from "@/lib/types";
import { cn } from "@/lib/cn";
import { useI18n } from "@/lib/i18n";

interface Props {
  /** 当前选中日期 YYYY-MM-DD；null 表示「最新」 */
  selectedDate: string | null;
  /** 选择日期；传 null 回到「最新」 */
  onSelect: (date: string | null) => void;
}

export function DateSelector({ selectedDate, onSelect }: Props) {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  const datesQ = useQuery({
    queryKey: ["price-dates"],
    queryFn: () => getPriceDates(),
  });
  const dateCounts: PriceDateCount[] = datesQ.data ?? [];

  // 点击弹层外部关闭
  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [open]);

  // 移动端按返回键关闭弹层
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open]);

  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className={cn(
          "inline-flex h-8 items-center gap-1.5 rounded-md border px-2.5 text-[12px] font-medium transition-colors",
          selectedDate
            ? "border-accent bg-accent text-white"
            : "border-border bg-surface text-fg-2 hover:bg-surface-warm",
        )}
        aria-haspopup="dialog"
        aria-expanded={open}
      >
        <CalendarDays size={14} />
        <span className="tabular">{selectedDate ?? t('日期')}</span>
      </button>

      {open && (
        <div
          role="dialog"
          className="absolute right-0 z-50 mt-2 w-[300px] max-w-[88vw] rounded-lg border border-border bg-surface p-3 shadow-lg"
        >
          <div className="mb-2 flex items-center justify-between">
            <span className="text-[12px] font-semibold text-fg">{t('选择日期')}</span>
            <button
              type="button"
              onClick={() => {
                onSelect(null);
                setOpen(false);
              }}
              className={cn(
                "inline-flex items-center gap-1 rounded-md border px-2 py-1 text-[11px] transition-colors",
                !selectedDate
                  ? "border-accent bg-accent text-white"
                  : "border-border text-fg-2 hover:bg-surface-warm",
              )}
            >
              <X size={12} /> {t('回到最新')}
            </button>
          </div>
          <PriceCalendar
            compact
            dateCounts={dateCounts}
            selected={selectedDate}
            onSelect={(d) => {
              onSelect(d);
              setOpen(false);
            }}
          />
        </div>
      )}
    </div>
  );
}
