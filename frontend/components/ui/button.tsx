"use client";

import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from "react";
import { Loader2 } from "lucide-react";
import { cn } from "@/lib/cn";

type Variant = "primary" | "secondary" | "ghost" | "danger";
type Size = "sm" | "md" | "icon";

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
  loading?: boolean;
  icon?: ReactNode;
}

const variantClass: Record<Variant, string> = {
  primary:
    "bg-accent text-accent-on hover:bg-accent-hover active:bg-accent-active border border-transparent",
  secondary:
    "bg-surface text-fg border border-border hover:bg-surface-warm",
  ghost: "bg-transparent text-fg-2 hover:bg-surface-warm border border-transparent",
  danger: "bg-danger text-white hover:opacity-90 active:opacity-100 border border-transparent",
};

const sizeClass: Record<Size, string> = {
  sm: "h-8 px-3 text-[13px] gap-1.5",
  md: "h-9 px-4 text-sm gap-2",
  icon: "h-9 w-9 justify-center",
};

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  function Button(
    {
      variant = "secondary",
      size = "md",
      loading = false,
      icon,
      className,
      children,
      disabled,
      ...rest
    },
    ref,
  ) {
    return (
      <button
        ref={ref}
        disabled={disabled || loading}
        className={cn(
          "inline-flex items-center rounded-md font-medium select-none",
          "transition-colors duration-fast ease-standard",
          "disabled:opacity-50 disabled:pointer-events-none",
          variantClass[variant],
          sizeClass[size],
          className,
        )}
        {...rest}
      >
        {loading ? (
          <Loader2 size={size === "sm" ? 14 : 16} className="animate-spin" />
        ) : (
          icon
        )}
        {children}
      </button>
    );
  },
);
