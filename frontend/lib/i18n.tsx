"use client";

import {
  createContext,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";
import { EN_PAGES } from "./i18n/en.pages";
import { EN_DASHBOARD } from "./i18n/en.dashboard";
import { EN_MISC } from "./i18n/en.misc";

export type Lang = "zh" | "en";

/**
 * English translations, keyed by the *original Chinese UI string*.
 *
 * Design rationale (Chinese-as-key):
 * - The default language is Chinese, so `t('价格看板')` returns the Chinese
 *   string verbatim when lang === 'zh'.
 * - When lang === 'en', `t(key)` looks the key up here; if missing it falls
 *   back to the Chinese key itself — so an untranslated string still renders
 *   (in Chinese) instead of breaking the UI.
 * - This keeps replacements mechanical: every user-facing Chinese literal
 *   becomes `t('那串中文')`, and we only ever grow this map.
 * - The map is split across en.pages.ts / en.dashboard.ts / en.misc.ts so
 *   parallel edits don't collide; they're merged here.
 *
 * For interpolated strings use `{name}` placeholders, e.g.
 *   t('共 {n} 条', { n: 12 })  // EN: 'Total {n} records'
 */
export const EN: Record<string, string> = {
  ...EN_PAGES,
  ...EN_DASHBOARD,
  ...EN_MISC,
};

type Vars = Record<string, string | number>;

interface I18nCtx {
  lang: Lang;
  setLang: (l: Lang) => void;
  toggleLang: () => void;
  t: (key: string, vars?: Vars) => string;
}

const Ctx = createContext<I18nCtx | null>(null);
const STORAGE_KEY = "pm-lang";

const TITLE: Record<Lang, string> = {
  zh: "GTM 价格监控工作台平台",
  en: "NE Europe Phone Price Monitor",
};

export function LanguageProvider({ children }: { children: ReactNode }) {
  const [lang, setLangState] = useState<Lang>("zh");

  // Restore persisted choice on mount.
  useEffect(() => {
    try {
      const saved = localStorage.getItem(STORAGE_KEY);
      if (saved === "en" || saved === "zh") setLangState(saved);
    } catch {
      /* ignore */
    }
  }, []);

  // Reflect language on <html> and document title.
  useEffect(() => {
    document.documentElement.lang = lang === "en" ? "en" : "zh-CN";
    document.title = TITLE[lang];
  }, [lang]);

  const setLang = (l: Lang) => {
    setLangState(l);
    try {
      localStorage.setItem(STORAGE_KEY, l);
    } catch {
      /* ignore */
    }
  };

  const toggleLang = () => setLang(lang === "zh" ? "en" : "zh");

  const t = (key: string, vars?: Vars): string => {
    let s: string;
    if (lang === "en") {
      s = EN[key] ?? key;
    } else {
      s = key;
    }
    if (vars) {
      for (const [k, v] of Object.entries(vars)) {
        s = s.replace(new RegExp(`\\{${k}\\}`, "g"), String(v));
      }
    }
    return s;
  };

  return (
    <Ctx.Provider value={{ lang, setLang, toggleLang, t }}>
      {children}
    </Ctx.Provider>
  );
}

export function useI18n(): I18nCtx {
  const ctx = useContext(Ctx);
  if (!ctx) {
    throw new Error("useI18n must be used within <LanguageProvider>");
  }
  return ctx;
}
