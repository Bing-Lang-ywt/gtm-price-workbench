"use client";

import { QueryClient } from "@tanstack/react-query";

let client: QueryClient | null = null;

/** 单例 QueryClient（浏览器侧） */
export function getQueryClient(): QueryClient {
  if (!client) {
    client = new QueryClient({
      defaultOptions: {
        queries: {
          staleTime: 30_000,
          refetchOnWindowFocus: false,
          retry: 1,
        },
      },
    });
  }
  return client;
}
