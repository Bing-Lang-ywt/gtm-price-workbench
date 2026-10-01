"use client";

import { useEffect, type ReactNode } from "react";
import { X } from "lucide-react";
import { cn } from "@/lib/cn";
import { useI18n } from "@/lib/i18n";

/**
 * 右侧抽屉（告警详情）。右滑进入，120ms→240ms 收敛，禁用弹跳曲线。
 * 遮罩点击 / ESC 关闭。
 */
export function Drawer({
  open,
  onClose,
  title,
  children,
  footer,
  width = "max-w-md",
}: {
  open: boolean;
  onClose: () => void;
  title?: ReactNode;
  children: ReactNode;
  footer?: ReactNode;
  width?: string;
}) {
  const { t } = useI18n();
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = "";
    };
  }, [open, onClose]);

  return (
    <div
      className={cn(
        "fixed inset-0 z-40",
        open ? "pointer-events-auto" : "pointer-events-none",
      )}
      aria-hidden={!open}
    >
      {/* 遮罩 */}
      <div
        onClick={onClose}
        className={cn(
          "absolute inset-0 bg-black/30 transition-opacity duration-base ease-standard",
          open ? "opacity-100" : "opacity-0",
        )}
      />
      {/* 面板 */}
      <aside
        role="dialog"
        aria-modal="true"
        className={cn(
          "absolute right-0 top-0 flex h-full w-full flex-col border-l border-border bg-surface shadow-raised",
          width,
          "transition-transform duration-base ease-standard",
          open ? "translate-x-0" : "translate-x-full",
        )}
      >
        <header className="flex items-center justify-between border-b border-border px-4 h-14 shrink-0">
          <div className="min-w-0 text-sm font-semibold text-fg truncate">
            {title}
          </div>
          <button
            onClick={onClose}
            aria-label={t("关闭")}
            className="ml-3 flex h-8 w-8 items-center justify-center rounded-md text-fg-2 hover:bg-surface-warm transition-colors duration-fast ease-standard"
          >
            <X size={18} />
          </button>
        </header>
        <div className="flex-1 overflow-y-auto px-4 py-4">{children}</div>
        {footer && (
          <footer className="border-t border-border px-4 py-3 shrink-0">
            {footer}
          </footer>
        )}
      </aside>
    </div>
  );
}
