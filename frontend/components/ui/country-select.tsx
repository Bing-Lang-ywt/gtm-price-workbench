"use client";

import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { MapPin, ChevronDown, Check } from "lucide-react";
import { cn } from "@/lib/cn";
import { COUNTRIES, type CountryCode, type CountryMeta } from "@/lib/types";
import { useI18n } from "@/lib/i18n";

interface CountrySelectProps {
  selected: CountryCode[];
  onChange: (next: CountryCode[]) => void;
  options?: CountryMeta[];
}

interface Anchor {
  top: number;
  left: number;
  width: number;
}

export function CountrySelect({
  selected,
  onChange,
  options = COUNTRIES,
}: CountrySelectProps) {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  const [mounted, setMounted] = useState(false);
  const [anchor, setAnchor] = useState<Anchor | null>(null);
  const btnRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => setMounted(true), []);

  // 定位：无论如何都基于按钮视口坐标，浮层脱离 overflow-x-auto 裁剪上下文
  const reposition = () => {
    const el = btnRef.current;
    if (!el) return;
    const r = el.getBoundingClientRect();
    setAnchor({ top: r.bottom + 4, left: r.left, width: r.width });
  };

  useLayoutEffect(() => {
    if (!open) return;
    reposition();
    const onScroll = () => reposition();
    const onResize = () => reposition();
    window.addEventListener("scroll", onScroll, true);
    window.addEventListener("resize", onResize);
    return () => {
      window.removeEventListener("scroll", onScroll, true);
      window.removeEventListener("resize", onResize);
    };
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      const t = e.target as Node;
      if (
        btnRef.current?.contains(t) ||
        menuRef.current?.contains(t)
      )
        return;
      setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const all = options.map((o) => o.code);
  const allSelected = selected.length === all.length;
  const noneSelected = selected.length === 0;
  const label = noneSelected
    ? t("未选")
    : allSelected
      ? t("全部")
      : selected.length === 1
        ? (options.find((o) => o.code === selected[0])?.name ?? selected[0])
        : t("{n} 国", { n: selected.length });

  const toggle = (c: CountryCode) => {
    onChange(
      selected.includes(c)
        ? selected.filter((x) => x !== c)
        : [...selected, c],
    );
  };
  const selectAll = () => onChange(all);
  const clear = () => onChange([]);

  const menu = open && anchor && (
    <div
      ref={menuRef}
      role="listbox"
      style={{
        position: "fixed",
        top: anchor.top,
        left: anchor.left,
        width: Math.max(anchor.width, 240),
        zIndex: 2147483647,
      }}
      className="rounded-md border border-border bg-surface shadow-2xl"
    >
      <div className="flex items-center justify-between border-b border-border px-2.5 py-1.5">
        <button
          type="button"
          onClick={selectAll}
          disabled={allSelected}
          className="text-[11px] font-medium text-accent hover:underline disabled:opacity-40"
        >
          {t("全选")}
        </button>
        <span className="text-[11px] text-muted">
          {selected.length}/{all.length}
        </span>
        <button
          type="button"
          onClick={clear}
          disabled={noneSelected}
          className="text-[11px] font-medium text-muted hover:underline disabled:opacity-40"
        >
          {t("清空")}
        </button>
      </div>
      <div className="max-h-72 overflow-auto py-1">
        {options.map((o) => {
          const on = selected.includes(o.code);
          return (
            <button
              key={o.code}
              type="button"
              role="option"
              aria-selected={on}
              onClick={() => toggle(o.code)}
              className="flex w-full items-center gap-2 px-2.5 py-1.5 text-[13px] transition-colors hover:bg-surface-warm"
            >
              <span
                className={cn(
                  "flex h-4 w-4 shrink-0 items-center justify-center rounded border",
                  on
                    ? "border-accent bg-accent text-accent-on"
                    : "border-border bg-surface",
                )}
              >
                {on && <Check size={11} />}
              </span>
              <span className="font-mono text-[11px] font-semibold text-fg">
                {o.code}
              </span>
              <span className="text-fg-2">{o.name}</span>
              <span className="ml-auto text-[10px] text-muted">
                {o.currency}
              </span>
            </button>
          );
        })}
      </div>
    </div>
  );

  return (
    <>
      <div className="relative">
        <button
          ref={btnRef}
          type="button"
          onClick={() => setOpen((o) => !o)}
          aria-haspopup="listbox"
          aria-expanded={open}
          className={cn(
            "inline-flex items-center gap-1.5 rounded-md border px-2.5 h-8 text-[13px]",
            "transition-colors duration-fast ease-standard",
            open
              ? "border-accent bg-surface-warm"
              : "border-border bg-surface hover:bg-surface-warm",
          )}
        >
          <MapPin size={14} className="text-accent" />
          <span className="font-medium text-fg">{t("国家")}</span>
          <span className="text-muted">·</span>
          <span className="min-w-[2.5rem] text-left text-fg-2">{label}</span>
          <ChevronDown
            size={14}
            className={cn(
              "text-muted transition-transform duration-fast",
              open && "rotate-180",
            )}
          />
        </button>
      </div>

      {mounted && menu
        ? createPortal(menu, document.body)
        : null}
    </>
  );
}
