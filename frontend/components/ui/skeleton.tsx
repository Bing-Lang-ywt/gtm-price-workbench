"use client";

import { type ReactNode } from "react";
import { cn } from "@/lib/cn";

export function Skeleton({
  className,
  height,
}: {
  className?: string;
  height?: number | string;
}) {
  return (
    <div
      className={cn("animate-pulse rounded-sm bg-surface-warm", className)}
      style={height ? { height } : undefined}
      aria-hidden
    />
  );
}

export function EmptyState({
  icon,
  title,
  description,
  action,
}: {
  icon?: ReactNode;
  title: string;
  description?: string;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 px-6 py-12 text-center">
      {icon && (
        <div className="flex h-10 w-10 items-center justify-center rounded-full bg-surface-warm text-muted">
          {icon}
        </div>
      )}
      <div className="space-y-1">
        <p className="text-sm font-semibold text-fg">{title}</p>
        {description && (
          <p className="max-w-sm text-[13px] text-muted">{description}</p>
        )}
      </div>
      {action}
    </div>
  );
}
