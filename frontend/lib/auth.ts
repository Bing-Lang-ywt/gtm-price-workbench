"use client";

import type { LoginData } from "./types";

const TOKEN_KEY = "pm_jwt";
const USER_KEY = "pm_user";

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(TOKEN_KEY);
}

export function setToken(data: LoginData): void {
  if (typeof window === "undefined") return;
  const token = data.access_token || data.token;
  if (token) {
    window.localStorage.setItem(TOKEN_KEY, token);
  }
  if (data.user) {
    window.localStorage.setItem(USER_KEY, JSON.stringify(data.user));
  }
}

export function clearAuth(): void {
  if (typeof window === "undefined") return;
  window.localStorage.removeItem(TOKEN_KEY);
  window.localStorage.removeItem(USER_KEY);
}

export function isAuthed(): boolean {
  return !!getToken();
}

export function getStoredUser(): LoginData["user"] | null {
  if (typeof window === "undefined") return null;
  const raw = window.localStorage.getItem(USER_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw);
  } catch {
    return null;
  }
}
