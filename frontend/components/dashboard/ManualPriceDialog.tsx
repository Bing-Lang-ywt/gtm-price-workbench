"use client";

import { useEffect, useState } from "react";
import { X } from "lucide-react";
import type { PriceType } from "@/lib/types";
import { PRICE_TYPES } from "@/lib/types";
import type { ManualPriceBody } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

export interface ManualFillContext {
  skuId: string;
  channelId: string;
  priceType: PriceType;
  currency: string;
  channelName: string;
  modelName: string;
  /** 当前已存在价格（用于「修改」时预填，未录入时为 undefined） */
  currentAmount?: number;
  /** 当前价格的币种（用于预填币种下拉） */
  currentCurrency?: string;
}

export function ManualPriceDialog({
  ctx,
  onClose,
  onSave,
}: {
  ctx: ManualFillContext | null;
  onClose: () => void;
  onSave: (body: ManualPriceBody) => Promise<void>;
}) {
  const { t } = useI18n();
  const [priceStr, setPriceStr] = useState("");
  const [priceType, setPriceType] = useState<PriceType>(
    ctx?.priceType ?? "unlocked",
  );
  const [currency, setCurrency] = useState<string>(ctx?.currency ?? "EUR");
  const [inStock, setInStock] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // 每次打开（ctx 变化）都把表单同步成该单元格的当前值，便于「修改」而非从零「补录」。
  useEffect(() => {
    if (!ctx) return;
    setPriceStr(ctx.currentAmount != null ? String(ctx.currentAmount) : "");
    setPriceType(ctx.priceType ?? "unlocked");
    setCurrency(ctx.currentCurrency ?? ctx.currency ?? "EUR");
    setInStock(true);
    setError(null);
  }, [ctx]);

  if (!ctx) return null;

  const isEditing = ctx.currentAmount != null;

  const handleSave = async () => {
    const price = parseFloat(priceStr);
    if (!Number.isFinite(price) || price < 0) {
      setError(t('请输入有效价格（不小于 0）'));
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      await onSave({
        sku_id: ctx.skuId,
        channel_id: ctx.channelId,
        price_type: priceType,
        price,
        currency,
        in_stock: inStock,
      });
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : t('保存失败'));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      onClick={onClose}
    >
      <div
        className="w-full max-w-sm rounded-lg border border-border bg-surface p-4 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-3 flex items-center justify-between">
          <h3 className="text-sm font-semibold text-fg">
            {isEditing ? t('修改价格') : t('补录价格')}
          </h3>
          <button
            type="button"
            onClick={onClose}
            className="rounded p-1 text-muted transition-colors duration-fast ease-standard hover:bg-surface-warm hover:text-fg"
            aria-label={t('关闭')}
          >
            <X size={16} />
          </button>
        </div>

        <div className="mb-3 space-y-1 text-[12px] text-muted">
          <div>
            {t('机型')}：<span className="text-fg">{ctx.modelName}</span>
          </div>
          <div>
            {t('渠道')}：<span className="text-fg">{ctx.channelName}</span>
          </div>
        </div>

        <div className="space-y-3">
          <label className="block">
              <span className="mb-1 block text-[12px] font-medium text-fg-2">
                {t('价格')}
              </span>
            <input
              type="number"
              inputMode="decimal"
              step="0.01"
              value={priceStr}
              onChange={(e) => setPriceStr(e.target.value)}
              placeholder="0.00"
              className="w-full rounded border border-border bg-surface-warm px-2.5 py-1.5 text-[13px] text-fg outline-none transition-colors duration-fast ease-standard focus:border-accent"
              autoFocus
            />
          </label>

          <div className="grid grid-cols-2 gap-3">
            <label className="block">
              <span className="mb-1 block text-[12px] font-medium text-fg-2">
                {t('价格类型')}
              </span>
              <select
                value={priceType}
                onChange={(e) => setPriceType(e.target.value as PriceType)}
                className="w-full rounded border border-border bg-surface-warm px-2 py-1.5 text-[13px] text-fg outline-none transition-colors duration-fast ease-standard focus:border-accent"
              >
                {PRICE_TYPES.map((pt) => (
                  <option key={pt} value={pt}>
                    {pt === "unlocked"
                      ? t("裸机价")
                      : pt === "subsidy_down_payment"
                        ? t("设备费(首付)")
                        : t("月供")}
                  </option>
                ))}
              </select>
            </label>

            <label className="block">
              <span className="mb-1 block text-[12px] font-medium text-fg-2">
                {t('币种')}
              </span>
              <select
                value={currency}
                onChange={(e) => setCurrency(e.target.value)}
                className="w-full rounded border border-border bg-surface-warm px-2 py-1.5 text-[13px] text-fg outline-none transition-colors duration-fast ease-standard focus:border-accent"
              >
                {["EUR", "RSD", "HUF", "RON", "BGN", "PLN", "CZK"].map((c) => (
                  <option key={c} value={c}>
                    {c}
                  </option>
                ))}
              </select>
            </label>
          </div>

          <label className="flex items-center gap-2 text-[12px] text-fg-2">
            <input
              type="checkbox"
              checked={inStock}
              onChange={(e) => setInStock(e.target.checked)}
              className="h-3.5 w-3.5 accent-accent"
            />
            {t('有货（in stock）')}
          </label>
        </div>

        {error && (
          <div className="mt-3 rounded border border-danger/20 bg-danger/10 px-2.5 py-1.5 text-[12px] text-danger">
            {error}
          </div>
        )}

        <div className="mt-4 flex justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            className="rounded-md border border-border px-3 py-1.5 text-[12px] font-medium text-fg-2 transition-colors duration-fast ease-standard hover:bg-surface-warm"
          >
            {t('取消')}
          </button>
          <button
            type="button"
            onClick={handleSave}
            disabled={submitting}
            className="rounded-md bg-accent px-3 py-1.5 text-[12px] font-medium text-white transition-colors duration-fast ease-standard hover:bg-accent-hover disabled:opacity-60"
          >
            {submitting ? t('保存中…') : t('保存')}
          </button>
        </div>
      </div>
    </div>
  );
}
