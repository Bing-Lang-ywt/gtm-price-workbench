"use client";

import { useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Trash2, Bell } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Drawer } from "@/components/ui/drawer";
import { Toggle } from "@/components/ui/toggle";
import {
  createAlertRule,
  deleteAlertRule,
  getAlertRules,
  getChannels,
  getModels,
  getSkus,
  patchAlertRule,
} from "@/lib/api";
import { useToast } from "@/components/ui/toast";
import { useI18n } from "@/lib/i18n";
import {
  PRICE_TYPES,
  type AlertRule,
  type ConditionType,
  type ModelRow,
  type PriceType,
  type ScopeType,
} from "@/lib/types";

const COND_LABEL: Record<ConditionType, string> = {
  below: "低于",
  above: "高于",
  delta_pct: "价格变动超",
  new_entry: "新上架",
};

const SCOPE_LABEL: Record<ScopeType, string> = {
  model: "机型",
  sku: "SKU",
  channel: "渠道",
  segment: "价位段",
};

interface DraftRule {
  channel_id: string;
  model_id: string;
  sku_id: string;
  price_type: PriceType | "";
  condition_type: ConditionType;
  threshold: string;
  notify_target: string;
}

const EMPTY: DraftRule = {
  channel_id: "",
  model_id: "",
  sku_id: "",
  price_type: "",
  condition_type: "delta_pct",
  threshold: "3",
  notify_target: "",
};

const shortId = (id: string) => id.slice(0, 8);

export function RulesTab() {
  const { t } = useI18n();
  const qc = useQueryClient();
  const toast = useToast();
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState<DraftRule>(EMPTY);

  const { data, isLoading } = useQuery({
    queryKey: ["alert-rules"],
    queryFn: () => getAlertRules(),
  });

  // 用于下拉与列表展示的渠道 / 机型 / SKU 字典
  const { data: channels } = useQuery({
    queryKey: ["channels-all"],
    queryFn: () => getChannels(),
  });
  const { data: models } = useQuery({
    queryKey: ["models-all"],
    queryFn: () => getModels(),
  });
  const { data: skus } = useQuery({
    queryKey: ["skus-all"],
    queryFn: () => getSkus(),
  });

  const channelMap = useMemo(
    () => new Map((channels ?? []).map((c) => [c.id, c.name])),
    [channels],
  );
  const modelMap = useMemo(
    () => new Map((models ?? []).map((m) => [m.id, m as ModelRow])),
    [models],
  );

  // 规则接口已收敛到 /api/v1/alert-rules
  const rules = (data ?? []).filter((r) => !!r.id);

  const refresh = () => qc.invalidateQueries({ queryKey: ["alert-rules"] });

  const onToggle = async (r: AlertRule) => {
    try {
      await patchAlertRule(r.id, { is_active: !r.is_active });
      refresh();
    } catch (e) {
      toast.error(
        e instanceof Error ? e.message : t("切换启用状态失败，已刷新回滚"),
      );
      refresh();
    }
  };

  const onDelete = async (id: string) => {
    try {
      await deleteAlertRule(id);
      refresh();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : t("删除规则失败，已刷新回滚"));
      refresh();
    }
  };

  const onSubmit = async () => {
    try {
      await createAlertRule({
        channel_id: draft.channel_id || null,
        model_id: draft.model_id || null,
        sku_id: draft.sku_id || null,
        price_type: draft.price_type || null,
        condition_type: draft.condition_type,
        threshold: draft.threshold ? Number(draft.threshold) : null,
        notify_target: draft.notify_target || null,
        is_active: true,
      });
      setOpen(false);
      setDraft(EMPTY);
      refresh();
    } catch (e) {
      toast.error(
        e instanceof Error ? e.message : t("创建规则失败，请检查输入后重试"),
      );
    }
  };

  // 选中渠道 / 机型后，SKU 下拉只列出匹配的；切换渠道或机型时清空已选 SKU 避免错配。
  const skuOptions = useMemo(() => {
    return (skus ?? []).filter(
      (s) =>
        (!draft.channel_id || s.channel_id === draft.channel_id) &&
        (!draft.model_id || s.model_id === draft.model_id),
    );
  }, [skus, draft.channel_id, draft.model_id]);

  const bindingLabel = (r: AlertRule, t: (k: string) => string): { text: string; legacy: boolean } => {
    if (r.channel_id || r.model_id || r.sku_id) {
      const ch = r.channel_id
        ? channelMap.get(r.channel_id) ?? t("未知渠道")
        : t("全部渠道");
      const m = r.model_id
        ? modelMap.get(r.model_id)?.marketing_code ||
          modelMap.get(r.model_id)?.display_name ||
          t("未知机型")
        : t("全部机型");
      const parts = [ch, m];
      if (r.sku_id) parts.push(`SKU ${shortId(r.sku_id)}`);
      else parts.push(t("全部 SKU"));
      return { text: parts.join(" · "), legacy: false };
    }
    // 兼容旧规则（单一作用域 + 原始 scope_id）
    const st = (r.scope_type as ScopeType) || "all";
    return {
      text: `${t(SCOPE_LABEL[st] ?? st)} · ${r.scope_id ? shortId(r.scope_id) : t("全部")}`,
      legacy: true,
    };
  };

  return (
    <section className="rounded-lg border border-border bg-surface">
      <div className="flex items-center justify-between border-b border-border px-4 py-2.5">
        <h2 className="flex items-center gap-2 text-sm font-semibold text-fg">
          <Bell size={16} className="text-accent" />
          {t("告警规则")}
        </h2>
        <Button
          size="sm"
          variant="primary"
          icon={<Plus size={14} />}
          onClick={() => setOpen(true)}
        >
          {t("新建规则")}
        </Button>
      </div>

      {isLoading ? (
        <div className="px-4 py-10 text-center text-[13px] text-muted">
          {t("加载规则…")}
        </div>
      ) : rules.length === 0 ? (
        <div className="px-4 py-10 text-center text-[13px] text-muted">
          {t("暂无告警规则。新建一条以绑定具体渠道 / 机型 / SKU，并设置降价、反弹或价格变动阈值。")}
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[640px] border-collapse text-[13px]">
            <thead>
              <tr className="border-b border-border">
                <th className="th-caps bg-surface px-3 py-2 text-left">{t("绑定范围")}</th>
                <th className="th-caps bg-surface px-3 py-2 text-left">{t("档位")}</th>
                <th className="th-caps bg-surface px-3 py-2 text-left">{t("条件")}</th>
                <th className="th-caps bg-surface px-3 py-2 text-left">{t("阈值")}</th>
                <th className="th-caps bg-surface px-3 py-2 text-left">{t("启用")}</th>
                <th className="th-caps bg-surface px-3 py-2 text-right">{t("操作")}</th>
              </tr>
            </thead>
            <tbody>
              {rules.map((r) => {
                const b = bindingLabel(r, t);
                return (
                  <tr
                    key={r.id}
                    className="border-b border-border-soft transition-colors duration-fast ease-standard hover:bg-surface-warm"
                  >
                    <td className="px-3 py-2 text-fg-2">
                      {b.text}
                      {b.legacy && (
                        <span className="ml-1 text-[10px] text-meta">{t("旧")}</span>
                      )}
                    </td>
                    <td className="px-3 py-2 text-fg-2">
                      {r.price_type
                        ? PRICE_TYPES.includes(r.price_type)
                          ? r.price_type
                          : "—"
                        : t("全部")}
                    </td>
                    <td className="px-3 py-2 text-fg-2">
                      {t(COND_LABEL[r.condition_type] ?? r.condition_type)}
                    </td>
                    <td className="tabular px-3 py-2 text-fg-2">
                      {r.threshold != null
                        ? r.condition_type === "delta_pct"
                          ? `${r.threshold}%`
                          : `${r.threshold}`
                        : "—"}
                    </td>
                    <td className="px-3 py-2">
                      <Toggle
                        checked={!!r.is_active}
                        onChange={() => onToggle(r)}
                        label={t("启用")}
                      />
                    </td>
                    <td className="px-3 py-2 text-right">
                      <button
                        onClick={() => onDelete(r.id)}
                        aria-label={t("删除")}
                        className="inline-flex h-7 w-7 items-center justify-center rounded-md text-fg-2 hover:bg-surface"
                      >
                        <Trash2 size={15} />
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      <Drawer
        open={open}
        onClose={() => setOpen(false)}
        title={t("新建告警规则")}
        footer={
          <div className="flex justify-end gap-2">
            <Button variant="secondary" onClick={() => setOpen(false)}>
              {t("取消")}
            </Button>
            <Button variant="primary" onClick={onSubmit}>
              {t("创建")}
            </Button>
          </div>
        }
      >
        <div className="space-y-3">
          <p className="text-[12px] text-muted">
            {t("价格变动默认绑定到「渠道 + 机型 + SKU」三维。留空某维度即代表该维度不限（例如只选机型 = 该机型在所有渠道的价格变动都告警）。")}
          </p>
          <label className="block">
            <span className="mb-1 block text-[12px] font-medium text-fg-2">
              {t("渠道")}
            </span>
            <select
              value={draft.channel_id}
              onChange={(e) =>
                setDraft({ ...draft, channel_id: e.target.value, sku_id: "" })
              }
              className="h-9 w-full rounded-md border border-border bg-bg px-3 text-sm text-fg outline-none focus:border-accent"
            >
              <option value="">{t("全部渠道")}</option>
              {(channels ?? []).map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </select>
          </label>
          <label className="block">
            <span className="mb-1 block text-[12px] font-medium text-fg-2">
              {t("产品（机型）")}
            </span>
            <select
              value={draft.model_id}
              onChange={(e) =>
                setDraft({ ...draft, model_id: e.target.value, sku_id: "" })
              }
              className="h-9 w-full rounded-md border border-border bg-bg px-3 text-sm text-fg outline-none focus:border-accent"
            >
              <option value="">{t("全部机型")}</option>
              {(models ?? []).map((m) => (
                <option key={m.id} value={m.id}>
                  {m.marketing_code || m.display_name}
                </option>
              ))}
            </select>
          </label>
          <label className="block">
            <span className="mb-1 block text-[12px] font-medium text-fg-2">
              {t("SKU（具体规格 / 存储版本）")}
            </span>
            <select
              value={draft.sku_id}
              onChange={(e) =>
                setDraft({ ...draft, sku_id: e.target.value })
              }
              disabled={skuOptions.length === 0}
              className="h-9 w-full rounded-md border border-border bg-bg px-3 text-sm text-fg outline-none focus:border-accent disabled:opacity-50"
            >
              <option value="">{t("全部 SKU")}</option>
              {skuOptions.map((s) => (
                <option key={s.id} value={s.id}>
                  {channelMap.get(s.channel_id) ?? "?"} ·{" "}
                  {modelMap.get(s.model_id)?.marketing_code ?? "?"}
                </option>
              ))}
            </select>
          </label>
          <label className="block">
            <span className="mb-1 block text-[12px] font-medium text-fg-2">
              {t("价格档位")}
            </span>
            <select
              value={draft.price_type}
              onChange={(e) =>
                setDraft({
                  ...draft,
                  price_type: e.target.value as PriceType | "",
                })
              }
              className="h-9 w-full rounded-md border border-border bg-bg px-3 text-sm text-fg outline-none focus:border-accent"
            >
              <option value="">{t("全部档位")}</option>
              {PRICE_TYPES.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
          </label>
          <div className="flex gap-3">
            <label className="block flex-1">
              <span className="mb-1 block text-[12px] font-medium text-fg-2">
                {t("条件")}
              </span>
              <select
                value={draft.condition_type}
                onChange={(e) =>
                  setDraft({
                    ...draft,
                    condition_type: e.target.value as ConditionType,
                  })
                }
                className="h-9 w-full rounded-md border border-border bg-bg px-3 text-sm text-fg outline-none focus:border-accent"
              >
                {(["below", "above", "delta_pct", "new_entry"] as ConditionType[]).map(
                  (c) => (
                    <option key={c} value={c}>
                      {t(COND_LABEL[c])}
                    </option>
                  ),
                )}
              </select>
            </label>
            <label className="block w-28">
              <span className="mb-1 block text-[12px] font-medium text-fg-2">
                {draft.condition_type === "delta_pct" ? t("阈值 %") : t("阈值")}
              </span>
              <input
                type="number"
                value={draft.threshold}
                onChange={(e) =>
                  setDraft({ ...draft, threshold: e.target.value })
                }
                className="tabular h-9 w-full rounded-md border border-border bg-bg px-3 text-sm text-fg outline-none focus:border-accent"
              />
            </label>
          </div>
          <label className="block">
            <span className="mb-1 block text-[12px] font-medium text-fg-2">
              {t("通知目标（邮箱 / Slack webhook）")}
            </span>
            <input
              value={draft.notify_target}
              onChange={(e) =>
                setDraft({ ...draft, notify_target: e.target.value })
              }
              placeholder="analyst@example.com"
              className="h-9 w-full rounded-md border border-border bg-bg px-3 text-sm text-fg outline-none focus:border-accent"
            />
          </label>
        </div>
      </Drawer>
    </section>
  );
}
