"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Activity, LogIn, AlertCircle } from "lucide-react";
import { login } from "@/lib/api";
import { setToken, isAuthed } from "@/lib/auth";
import { Button } from "@/components/ui/button";
import { useI18n } from "@/lib/i18n";

export default function LoginPage() {
  const { t } = useI18n();
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (isAuthed()) router.replace("/");
  }, [router]);

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      const data = await login(email, password);
      setToken(data);
      router.replace("/");
    } catch (err) {
      setError(err instanceof Error ? err.message : t("登录失败"));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-bg px-4">
      <div className="w-full max-w-sm">
        <div className="mb-6 flex items-center gap-3">
          <span className="flex h-10 w-10 items-center justify-center rounded-md bg-accent text-accent-on">
            <Activity size={22} />
          </span>
          <div>
            <h1 className="text-lg font-semibold text-fg">{t('GTM 价格监控工作台')}</h1>
            <p className="text-[12px] text-muted tracking-caps">
              GTM PRICE INTELLIGENCE
            </p>
          </div>
        </div>

        <form
          onSubmit={onSubmit}
          className="rounded-lg border border-border bg-surface p-5 shadow-raised"
        >
          <h2 className="mb-1 text-sm font-semibold text-fg">分析师登录</h2>
          <p className="mb-4 text-[12px] text-muted">
            {t('登录以查看演示价格对比与异动告警。')}
          </p>

          <label className="mb-3 block">
            <span className="mb-1 block text-[12px] font-medium text-fg-2">
              {t('邮箱')}
            </span>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              autoComplete="username"
              className="h-9 w-full rounded-md border border-border bg-bg px-3 text-sm text-fg outline-none transition-colors duration-fast ease-standard focus:border-accent"
            />
          </label>

          <label className="mb-4 block">
            <span className="mb-1 block text-[12px] font-medium text-fg-2">
              {t('密码')}
            </span>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="current-password"
              className="h-9 w-full rounded-md border border-border bg-bg px-3 text-sm text-fg outline-none transition-colors duration-fast ease-standard focus:border-accent"
            />
          </label>

          {error && (
            <div className="mb-4 flex items-start gap-2 rounded-md border border-danger/20 bg-danger/10 px-3 py-2 text-[12px] text-danger">
              <AlertCircle size={15} className="mt-0.5 shrink-0" />
              <span>{error}</span>
            </div>
          )}

          <Button
            type="submit"
            variant="primary"
            loading={loading}
            icon={<LogIn size={16} />}
            className="w-full justify-center"
          >
            {t('登录看板')}
          </Button>
        </form>
      </div>
    </div>
  );
}
