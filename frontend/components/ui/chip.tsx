"use client";

import { type ReactNode } from "react";
import { cn } from "@/lib/cn";

/* ---------------- Chip（筛选 chips / 标签） ---------------- */

interface ChipProps {
  active?: boolean;
  onClick?: () => void;
  children: ReactNode;
  className?: string;
  title?: string;
}

export function Chip({ active, onClick, children, className, title }: ChipProps) {
  const interactive = !!onClick;
  return (
    <button
      type="button"
      title={title}
      onClick={onClick}
      disabled={!interactive}
      className={cn(
        "inline-flex items-center gap-1.5 rounded-pill border px-2.5 h-7 text-[13px] font-medium",
        "transition-colors duration-fast ease-standard",
        active
          ? "bg-accent-soft border-accent text-accent-text"
          : "bg-surface border-border text-fg-2 hover:bg-surface-warm",
        interactive ? "cursor-pointer" : "cursor-default",
        className,
      )}
    >
      {children}
    </button>
  );
}

/* ---------------- SegmentedControl（price_type 分段） ---------------- */

interface SegOption<T extends string> {
  value: T;
  label: string;
  icon?: ReactNode;
}

interface SegmentedProps<T extends string> {
  value: T;
  options: SegOption<T>[];
  onChange: (v: T) => void;
  size?: "sm" | "md";
}

export function SegmentedControl<T extends string>({
  value,
  options,
  onChange,
  size = "md",
}: SegmentedProps<T>) {
  return (
    <div
      role="tablist"
      className="inline-flex items-center rounded-md border border-border bg-surface p-0.5"
    >
      {options.map((opt) => {
        const active = opt.value === value;
        return (
          <button
            key={opt.value}
            role="tab"
            aria-selected={active}
            onClick={() => onChange(opt.value)}
            className={cn(
              "inline-flex items-center gap-1.5 rounded-[5px] font-medium",
              "transition-colors duration-fast ease-standard",
              size === "sm" ? "h-7 px-2.5 text-[12px]" : "h-8 px-3 text-[13px]",
              active
                ? "bg-accent text-accent-on"
                : "text-fg-2 hover:bg-surface-warm",
            )}
          >
            {opt.icon}
            {opt.label}
          </button>
        );
      })}
    </div>
  );
}
