"use client";

import {
  createContext,
  useCallback,
  useContext,
  useState,
  type ReactNode,
} from "react";
import { CircleCheck, TriangleAlert, Info, X } from "lucide-react";
import { cn } from "@/lib/cn";
import { useI18n } from "@/lib/i18n";

/**
 * 统一通知（toast）组件：info / success / error 三态。
 * 纯 React + Tailwind，无新增依赖；颜色走设计 Token，图标走 lucide-react。
 * 错误提示统一由此承载，杜绝 catch 静默。
 */

type ToastKind = "info" | "success" | "error";

interface ToastItem {
  id: number;
  kind: ToastKind;
  msg: string;
}

interface ToastApi {
  show: (msg: string, kind?: ToastKind) => void;
  info: (msg: string) => void;
  success: (msg: string) => void;
  error: (msg: string) => void;
}

const ToastCtx = createContext<ToastApi | null>(null);

export function useToast(): ToastApi {
  const ctx = useContext(ToastCtx);
  if (!ctx) throw new Error("useToast 必须在 <ToastProvider> 内使用");
  return ctx;
}

const KIND_STYLE: Record<
  ToastKind,
  { icon: typeof Info; color: string; label: string }
> = {
  info: { icon: Info, color: "text-accent-text", label: "提示" },
  success: { icon: CircleCheck, color: "text-success", label: "成功" },
  error: { icon: TriangleAlert, color: "text-danger", label: "错误" },
};

export function ToastProvider({ children }: { children: ReactNode }) {
  const { t } = useI18n();
  const [items, setItems] = useState<ToastItem[]>([]);

  const remove = useCallback((id: number) => {
    setItems((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const show = useCallback(
    (msg: string, kind: ToastKind = "info") => {
      const id = Date.now() + Math.random();
      setItems((prev) => [...prev, { id, kind, msg }]);
      window.setTimeout(() => remove(id), 4000);
    },
    [remove],
  );

  const api: ToastApi = {
    show,
    info: (m) => show(m, "info"),
    success: (m) => show(m, "success"),
    error: (m) => show(m, "error"),
  };

  return (
    <ToastCtx.Provider value={api}>
      {children}
      <div
        className="pointer-events-none fixed bottom-4 right-4 z-50 flex w-[min(92vw,360px)] flex-col gap-2"
        role="region"
        aria-live="polite"
        aria-label={t("通知")}
      >
        {items.map((item) => {
          const { icon: Icon, color, label } = KIND_STYLE[item.kind];
          return (
            <div
              key={item.id}
              role="status"
              className={cn(
                "toast-enter pointer-events-auto flex items-start gap-2 rounded-md border border-border bg-surface px-3 py-2.5 shadow-raised",
              )}
            >
              <Icon size={16} className={cn("mt-0.5 shrink-0", color)} />
              <p className="min-w-0 flex-1 text-[13px] leading-snug text-fg">
                <span className="sr-only">{t(label)}：</span>
                {item.msg}
              </p>
              <button
                onClick={() => remove(item.id)}
                aria-label={t("关闭通知")}
                className="shrink-0 text-meta transition-colors duration-fast ease-standard hover:text-fg-2"
              >
                <X size={14} />
              </button>
            </div>
          );
        })}
      </div>
    </ToastCtx.Provider>
  );
}
