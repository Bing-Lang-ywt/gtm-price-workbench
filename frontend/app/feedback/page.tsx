"use client";

import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { MessageSquare, Send, Trash2 } from "lucide-react";
import { AppShell } from "@/components/layout/AppShell";
import { createFeedback, deleteFeedback, getFeedbacks } from "@/lib/api";
import type { Feedback } from "@/lib/types";
import { useI18n } from "@/lib/i18n";

const DEFAULT_HINT = "如果需要加产品和加渠道，请在这里留言";

function fmtTime(iso: string): string {
  try {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return iso;
    return d.toLocaleString("zh-CN", {
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

export default function FeedbackPage() {
  const { t } = useI18n();
  const qc = useQueryClient();
  const [text, setText] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const q = useQuery({
    queryKey: ["feedbacks"],
    queryFn: () => getFeedbacks(),
  });

  const submit = async () => {
    const content = text.trim();
    if (!content) {
      setError(t("请输入留言内容"));
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      await createFeedback({ content });
      setText("");
      qc.invalidateQueries({ queryKey: ["feedbacks"] });
    } catch (e) {
      setError(e instanceof Error ? e.message : t("提交失败"));
    } finally {
      setSubmitting(false);
    }
  };

  const remove = async (id: string) => {
    try {
      await deleteFeedback(id);
      qc.invalidateQueries({ queryKey: ["feedbacks"] });
    } catch {
      /* 忽略删除失败 */
    }
  };

  const items: Feedback[] = q.data ?? [];
  const sorted = [...items].sort((a, b) =>
    (b.created_at ?? "").localeCompare(a.created_at ?? ""),
  );

  return (
    <AppShell>
      <div className="mx-auto max-w-3xl px-5 py-5">
        <div className="mb-4">
          <h1 className="text-base font-semibold text-fg">{t('我要反馈')}</h1>
          <p className="mt-1 text-[12px] text-muted">
            {t('如需新增产品、新增渠道或其他建议，请在此留言，运营同学会按时间统一查看。')}
          </p>
        </div>

        {/* 留言板 */}
        <section className="rounded-lg border border-border bg-surface p-4">
          <div className="mb-2 flex items-center gap-2 text-sm font-semibold text-fg">
            <MessageSquare size={16} className="text-accent" />
            {t('留言板')}
          </div>
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder={t(DEFAULT_HINT)}
            rows={3}
            className="w-full resize-y rounded border border-border bg-surface-warm px-3 py-2 text-[13px] text-fg outline-none transition-colors duration-fast ease-standard focus:border-accent"
          />
          {error && (
            <div className="mt-2 text-[12px] text-danger">{error}</div>
          )}
          <div className="mt-3 flex justify-end">
            <button
              type="button"
              onClick={submit}
              disabled={submitting}
              className="inline-flex items-center gap-1.5 rounded-md bg-accent px-3.5 py-1.5 text-[12px] font-medium text-white transition-colors duration-fast ease-standard hover:bg-accent-hover disabled:opacity-60"
            >
              <Send size={14} />
              {submitting ? t("提交中…") : t("提交留言")}
            </button>
          </div>
        </section>

        {/* 历史留言：按时间倒序展示 */}
        <section className="mt-5">
          <h2 className="mb-2 text-[13px] font-semibold text-fg-2">
            {t('历史留言（{n}）', { n: sorted.length })}
          </h2>
          {q.isLoading ? (
            <p className="text-[12px] text-muted">{t('加载中…')}</p>
          ) : sorted.length === 0 ? (
            <p className="rounded-lg border border-dashed border-border bg-surface-warm px-4 py-6 text-center text-[12px] text-muted">
              {t('暂无留言，来写下第一条吧。')}
            </p>
          ) : (
            <ul className="space-y-2">
              {sorted.map((f) => (
                <li
                  key={f.id}
                  className="flex items-start justify-between gap-3 rounded-lg border border-border bg-surface p-3"
                >
                  <div className="min-w-0">
                    <p className="whitespace-pre-wrap break-words text-[13px] leading-relaxed text-fg">
                      {f.content}
                    </p>
                    <p className="mt-1 text-[11px] text-meta">
                      {f.author || t("匿名")}
                      <span className="mx-1.5 text-border">·</span>
                      {fmtTime(f.created_at)}
                    </p>
                  </div>
                  <button
                    type="button"
                    onClick={() => remove(f.id)}
                    aria-label={t('删除留言')}
                    className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-muted transition-colors duration-fast ease-standard hover:bg-surface-warm hover:text-danger"
                  >
                    <Trash2 size={14} />
                  </button>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
    </AppShell>
  );
}
