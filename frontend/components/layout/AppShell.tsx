"use client";

import { useEffect, useState, type ReactNode } from "react";
import { usePathname, useRouter } from "next/navigation";
import {
  LayoutDashboard,
  SlidersHorizontal,
  Bell,
  MessageSquare,
  LogOut,
  Activity,
  Columns3,
  BarChart3,
  LineChart as LineChartIcon,
  type LucideIcon,
  Home,
  FileDown,
} from "lucide-react";
import { clearAuth, getStoredUser, isAuthed } from "@/lib/auth";
import { cn } from "@/lib/cn";
import { ThemeToggle } from "@/components/theme-toggle";
import { LanguageToggle } from "@/components/language-toggle";
import { useI18n } from "@/lib/i18n";

interface NavItem {
  href: string;
  label: string;
  icon: LucideIcon;
}

const NAV: NavItem[] = [
  { href: "/", label: "工作台", icon: Home },
  { href: "/monitor", label: "价格监控", icon: LayoutDashboard },
  { href: "/trend", label: "价格趋势", icon: LineChartIcon },
  { href: "/alerts", label: "变动告警", icon: Bell },
  { href: "/compare", label: "参数对比", icon: Columns3 },
  { href: "/chips", label: "芯片天梯图", icon: BarChart3 },
  { href: "/energy-label-pack", label: "能源标签", icon: FileDown },
  { href: "/feedback", label: "我要反馈", icon: MessageSquare },
  { href: "/config", label: "配置", icon: SlidersHorizontal },
];

export function AppShell({
  children,
  topRight,
}: {
  children: ReactNode;
  topRight?: ReactNode;
}) {
  const router = useRouter();
  const pathname = usePathname();
  const { t } = useI18n();
  const [mounted, setMounted] = useState(false);

  // 视图模式：跟随设备宽度自动切换（matchMedia 检测，依赖 layout.tsx 的
  // viewport meta 生效）。按用户要求已彻底移除手动切换按钮（原三态「档位」按钮）。
  const [autoMobile, setAutoMobile] = useState(false);

  useEffect(() => {
    setMounted(true);
    if (!isAuthed()) {
      router.replace("/login");
    }
    const mq = window.matchMedia("(max-width: 768px)");
    const update = () => setAutoMobile(mq.matches);
    update();
    mq.addEventListener("change", update);
    return () => mq.removeEventListener("change", update);
  }, [router]);

  const isMobile = autoMobile;

  const user = mounted ? getStoredUser() : null;

  const handleLogout = () => {
    clearAuth();
    router.replace("/login");
  };

  const renderNav = (compact: boolean) =>
    NAV.map((item) => {
      const active =
        item.href === "/"
          ? pathname === "/"
          : pathname.startsWith(item.href);
      const Icon = item.icon;
      return (
        <a
          key={item.href}
          href={item.href}
          className={cn(
            active ? "nav-link-active" : "nav-link",
            compact ? "shrink-0 px-2.5 py-1.5" : "",
          )}
        >
          <Icon size={18} />
          {compact ? (
            <span className="ml-1 text-[12px]">{t(item.label)}</span>
          ) : (
            t(item.label)
          )}
        </a>
      );
    });

  return (
    <div className="flex min-h-screen bg-bg text-fg">
      {/* 桌面端：左侧固定栏 */}
      {!isMobile && (
        <aside className="flex w-52 shrink-0 flex-col border-r border-border bg-surface">
          <div className="flex h-14 items-center gap-2 border-b border-border px-4">
            <span className="flex h-7 w-7 items-center justify-center rounded-md bg-accent text-accent-on accent-glow">
              <Activity size={18} />
            </span>
            <div className="leading-tight">
              <p className="text-[13px] font-semibold text-fg">{t("价格监控")}</p>
              <p className="text-[10px] text-muted tracking-caps">
                {t("NE EU · 8国23渠道")}
              </p>
            </div>
          </div>
          <nav className="flex flex-col gap-1 p-2">{renderNav(false)}</nav>
          <div className="mt-auto border-t border-border p-2">
            <div className="flex items-center justify-between px-2 py-2">
              <div className="min-w-0">
                <p className="truncate text-[12px] text-fg-2">
                  {user?.email ?? "analyst@example.com"}
                </p>
                <p className="text-[10px] text-meta">{t("竞争情报分析师")}</p>
              </div>
              <button
                onClick={handleLogout}
                aria-label={t("退出登录")}
                title={t("退出登录")}
                className="flex h-8 w-8 items-center justify-center rounded-md text-fg-2 hover:bg-surface-warm transition-colors duration-fast ease-standard"
              >
                <LogOut size={16} />
              </button>
            </div>
          </div>
        </aside>
      )}

      {/* 主区 */}
      <div className="flex min-w-0 flex-1 flex-col">
        {/* 移动端：顶部栏（Logo + 横向导航 + 主题/退出） */}
        {isMobile ? (
          <header className="sticky top-0 z-30 border-b border-border bg-surface">
            <div className="flex h-12 items-center gap-2 px-3">
              <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-accent text-accent-on accent-glow">
                <Activity size={16} />
              </span>
              <span className="shrink-0 text-[13px] font-semibold text-fg">
                {t("价格监控")}
              </span>
              <nav className="flex flex-1 items-center gap-1 overflow-x-auto">
                {renderNav(true)}
              </nav>
              <div className="flex shrink-0 items-center gap-1.5">
                <LanguageToggle />
                <ThemeToggle />
                <button
                  onClick={handleLogout}
                  aria-label={t("退出登录")}
                  title={t("退出登录")}
                  className="flex h-8 w-8 items-center justify-center rounded-md text-fg-2 hover:bg-surface-warm transition-colors duration-fast ease-standard"
                >
                  <LogOut size={16} />
                </button>
              </div>
            </div>
            {topRight && (
              <div className="flex flex-wrap items-center gap-2 border-t border-border px-3 py-1.5">
                {topRight}
              </div>
            )}
          </header>
        ) : (
          <header className="flex h-14 shrink-0 items-center justify-between border-b border-border bg-surface px-5">
            <div className="text-[13px] text-muted">
              {t(
                NAV.find((n) =>
                  n.href === "/"
                    ? pathname === "/"
                    : pathname.startsWith(n.href),
                )?.label ?? "工作台",
              )}
              <span className="mx-2 text-border">/</span>
              <span className="text-fg-2">{t("东北欧四国")}</span>
            </div>
            <div className="flex items-center gap-3">
              <LanguageToggle />
              <ThemeToggle />
              {topRight}
            </div>
          </header>
        )}
        <main className="min-w-0 flex-1 overflow-x-hidden">{children}</main>
      </div>
    </div>
  );
}
