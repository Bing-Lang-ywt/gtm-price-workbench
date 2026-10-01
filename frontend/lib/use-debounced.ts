"use client";

import { useEffect, useRef, useState } from "react";

/**
 * 受控筛选的防抖提交：组件内部维护「即时值」（控件立即反馈），
 * 经 delay 后提交为「生效值」（驱动重计算 / 取数）。
 * 避免连续切换国家 / 机型时反复触发昂贵的矩阵重建与不必要的查询失效。
 */
export function useDebouncedCommit<T>(
  initial: T,
  delay = 220,
): [T, T, (next: T) => void] {
  const [live, setLive] = useState<T>(initial);
  const [committed, setCommitted] = useState<T>(initial);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    return () => {
      if (timer.current) clearTimeout(timer.current);
    };
  }, []);

  const set = (next: T) => {
    setLive(next);
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => setCommitted(next), delay);
  };

  return [live, committed, set];
}
