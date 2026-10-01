"use client";

import { useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Store, Smartphone, Layers } from "lucide-react";
import { AppShell } from "@/components/layout/AppShell";
import { ChannelTable } from "@/components/config/ChannelTable";
import { ModelTable } from "@/components/config/ModelTable";
import { PriceBandEditor } from "@/components/config/PriceBandEditor";
import { Drawer } from "@/components/ui/drawer";
import { Button } from "@/components/ui/button";
import { Toggle } from "@/components/ui/toggle";
import { apiFetch, patchModel, getChannels, getModels, getPricesLatest, getSummary } from "@/lib/api";
import {
  type ModelRow,
  type PriceBand,
  type PriceLatest,
} from "@/lib/types";
import { relativeTime } from "@/lib/format";
import { cn } from "@/lib/cn";
import { useToast } from "@/components/ui/toast";
import { useI18n } from "@/lib/i18n";

type Tab = "channels" | "models" | "bands";

const BANDS: { value: PriceBand; label: string }[] = [
  { value: "entry", label: "入门" },
  { value: "mid", label: "中端" },
  { value: "upper_mid", label: "中高端" },
  { value: "flagship", label: "旗舰" },
  { value: "foldable", label: "折叠" },
];

export default function ConfigPage() {
  const { t } = useI18n();
  const qc = useQueryClient();
  const toast = useToast();
  const [tab, setTab] = useState<Tab>("channels");
  const [editing, setEditing] = useState<ModelRow | null>(null);

  const channelsQ = useQuery({ queryKey: ["channels"], queryFn: () => getChannels() });
  const modelsQ = useQuery({ queryKey: ["models"], queryFn: () => getModels() });
  const pricesQ = useQuery({ queryKey: ["prices-latest-cfg"], queryFn: () => getPricesLatest() });
  const summaryQ = useQuery({ queryKey: ["summary-cfg"], queryFn: () => getSummary() });

  const onTriggerChannel = async (id: string) => {
    try {
      await apiFetch(`/api/v1/channels/${id}/trigger-crawl`, {
        method: "POST",
      });
      toast.success(t("已触发该渠道抓取"));
    } catch (e) {
      toast.error(e instanceof Error ? e.message : t("触发抓取失败，请重试"));
    }
  };

  // 目标机型锚点价（unlocked，跨国取最小 EUR）
  const anchorByModel = useMemo(() => {
    const map: Record<string, number> = {};
    for (const p of (pricesQ.data ?? []) as PriceLatest[]) {
      if (p.price_type !== "unlocked" || !p.model_id) continue;
      const v = p.amount_eur;
      if (v == null) continue;
      if (map[p.model_id] == null || v < map[p.model_id]) map[p.model_id] = v;
    }
    return map;
  }, [pricesQ.data]);

  const targetModels = useMemo(
    () => (modelsQ.data ?? []).filter((m) => m.is_target),
    [modelsQ.data],
  );

  const activeChannels = (channelsQ.data ?? []).filter(
    (c) => c.is_active !== false,
  ).length;

  const tabs: { id: Tab; label: string; icon: typeof Store }[] = [
    { id: "channels", label: "渠道锚点", icon: Store },
    { id: "models", label: "机型锚点", icon: Smartphone },
    { id: "bands", label: "价位带", icon: Layers },
  ];

  return (
    <AppShell
      topRight={null}
    >
      {/* 全局状态条 */}
      <div className="flex flex-wrap items-center gap-x-6 gap-y-1 border-b border-border bg-surface px-5 py-2 text-[12px] text-muted">
        <span>
          {t('激活渠道')}{" "}
          <span className="tabular font-semibold text-fg-2">
            {activeChannels}
          </span>
          {" / "}
          {(channelsQ.data ?? []).length}
        </span>
        <span>
          {t('上次全量抓取')}{" "}
          <span className="text-fg-2">
            {relativeTime(summaryQ.data?.last_crawl_at)}
          </span>
        </span>
        <span>
          {t('FX 汇率日期')}{" "}
          <span className="text-fg-2">
            {summaryQ.data?.fx_date ?? "—"}
          </span>
        </span>
      </div>

      {/* Tabs */}
      <div className="flex items-center gap-1 border-b border-border bg-bg px-5 pt-3">
        {tabs.map((tb) => {
          const Icon = tb.icon;
          const active = tab === tb.id;
          return (
            <button
              key={tb.id}
              onClick={() => setTab(tb.id)}
              className={cn(
                "inline-flex items-center gap-1.5 border-b-2 px-3 pb-2 text-[13px] font-medium",
                "transition-colors duration-fast ease-standard",
                active
                  ? "border-accent text-accent-text"
                  : "border-transparent text-fg-2 hover:text-fg",
              )}
            >
              <Icon size={15} />
              {t(tb.label)}
            </button>
          );
        })}
      </div>

      <div className="space-y-4 p-5">
        {tab === "channels" && (
          <ChannelTable
            channels={channelsQ.data ?? []}
            loading={channelsQ.isLoading}
            onTrigger={onTriggerChannel}
          />
        )}
        {tab === "models" && (
          <ModelTable
            models={modelsQ.data ?? []}
            loading={modelsQ.isLoading}
            onEdit={setEditing}
          />
        )}
        {tab === "bands" && (
          <PriceBandEditor
            targetModels={targetModels}
            anchorByModel={anchorByModel}
            loading={pricesQ.isLoading}
          />
        )}
      </div>

      <ModelEditDrawer
        model={editing}
        onClose={() => setEditing(null)}
        onSaved={(msg) => {
          toast.success(msg);
          qc.invalidateQueries({ queryKey: ["models"] });
        }}
        onError={(msg) => toast.error(msg)}
      />
    </AppShell>
  );
}

/* ---------------- 机型编辑抽屉 ---------------- */

function ModelEditDrawer({
  model,
  onClose,
  onSaved,
  onError,
}: {
  model: ModelRow | null;
  onClose: () => void;
  onSaved: (msg: string) => void;
  onError: (msg: string) => void;
}) {
  const { t } = useI18n();
  const [name, setName] = useState("");
  const [band, setBand] = useState<PriceBand | "">("");
  const [isTarget, setIsTarget] = useState(false);
  const [aliases, setAliases] = useState("");
  const [saving, setSaving] = useState(false);

  // 同步 model → 表单
  useMemo(() => {
    if (model) {
      setName(model.display_name);
      setBand(model.price_band_anchor ?? model.price_band ?? "");
      setIsTarget(!!model.is_target);
      setAliases((model.aliases ?? []).map((a) => a.alias).join(", "));
    }
  }, [model]);

  const onSave = async () => {
    if (!model) return;
    setSaving(true);
    const body = {
      display_name: name,
      price_band_anchor: band || null,
      is_target: isTarget,
      aliases: aliases
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean)
        .map((a) => ({ alias: a })),
    };
    try {
      await patchModel(model.id, body);
      onSaved(t("已保存机型配置"));
      onClose();
    } catch (e) {
      onError(e instanceof Error ? e.message : t("保存失败，请重试"));
    } finally {
      setSaving(false);
    }
  };

  return (
    <Drawer
      open={!!model}
      onClose={onClose}
      title={t('编辑机型锚点')}
      footer={
        <div className="flex justify-end gap-2">
          <Button variant="secondary" onClick={onClose}>
            {t('取消')}
          </Button>
          <Button variant="primary" loading={saving} onClick={onSave}>
            {t('保存')}
          </Button>
        </div>
      }
    >
      {model && (
        <div className="space-y-4">
          <Field label={t('营销代号')}>
            <span className="font-mono text-[13px] text-fg-2">
              {model.marketing_code}
            </span>
          </Field>
          <label className="block">
            <span className="mb-1 block text-[12px] font-medium text-fg-2">
              {t('机型名')}
            </span>
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="h-9 w-full rounded-md border border-border bg-bg px-3 text-sm text-fg outline-none focus:border-accent"
            />
          </label>
          <label className="block">
            <span className="mb-1 block text-[12px] font-medium text-fg-2">
              {t('价位段')}
            </span>
            <select
              value={band}
              onChange={(e) => setBand(e.target.value as PriceBand)}
              className="h-9 w-full rounded-md border border-border bg-bg px-3 text-sm text-fg outline-none focus:border-accent"
            >
              <option value="">{t('未设定')}</option>
              {BANDS.map((b) => (
              <option key={b.value} value={b.value}>
                {t(b.label)}
              </option>
              ))}
            </select>
          </label>
          <div className="flex items-center justify-between">
            <span className="text-[12px] font-medium text-fg-2">
              {t('是否本品牌（荣耀）')}
            </span>
            <Toggle checked={isTarget} onChange={setIsTarget} label={t('是否本品牌')} />
          </div>
          <label className="block">
            <span className="mb-1 block text-[12px] font-medium text-fg-2">
              {t('别名映射（逗号分隔）')}
            </span>
            <input
              value={aliases}
              onChange={(e) => setAliases(e.target.value)}
              placeholder={t('如 H600, DemoBrand 600')}
              className="h-9 w-full rounded-md border border-border bg-bg px-3 text-sm text-fg outline-none focus:border-accent"
            />
          </label>
        </div>
      )}
    </Drawer>
  );
}

function Field({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <span className="mb-1 block text-[12px] font-medium text-fg-2">
        {label}
      </span>
      {children}
    </div>
  );
}
