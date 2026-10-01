"use client";

import { useState, type ReactNode } from "react";

/**
 * 轻量虚拟滚动（无额外依赖）：固定行高 + 视口切片。
 * 用于告警流等可能上千条的列表，避免一次性渲染全部 DOM。
 */
export function VirtualList<T>({
  items,
  rowHeight,
  height,
  renderRow,
  overscan = 6,
}: {
  items: T[];
  rowHeight: number;
  height: number;
  renderRow: (item: T, index: number) => ReactNode;
  overscan?: number;
}) {
  const [scrollTop, setScrollTop] = useState(0);
  const total = items.length * rowHeight;
  const start = Math.max(0, Math.floor(scrollTop / rowHeight) - overscan);
  const end = Math.min(
    items.length,
    Math.ceil((scrollTop + height) / rowHeight) + overscan,
  );
  const visible = items.slice(start, end);

  return (
    <div
      style={{ height, overflowY: "auto" }}
      onScroll={(e) => setScrollTop(e.currentTarget.scrollTop)}
    >
      <div style={{ height: total, position: "relative" }}>
        <div style={{ transform: `translateY(${start * rowHeight}px)` }}>
          {visible.map((it, i) => (
            <div key={start + i} style={{ height: rowHeight }}>
              {renderRow(it, start + i)}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
