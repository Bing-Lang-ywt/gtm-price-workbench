"use client";

import { FileDown, FileText, Smartphone, Tablet, Archive } from "lucide-react";
import { AppShell } from "@/components/layout/AppShell";
import { useI18n } from "@/lib/i18n";

/** 两张 EPREL 合并标签 PDF（backend 入库存放的源文件，经 /api/v1 公开分发） */
const PACKS = [
  {
    key: "phone",
    title: "DemoBrand 手机能源标签合集",
    desc: "涵盖在售手机机型的欧盟能效标签（EU Energy Label · EPREL 注册库）",
    file: "DemoBrand 手机能源标签合集.pdf",
    icon: Smartphone,
    inline: "/api/v1/energy-label-pack/phone/inline",
    download: "/api/v1/energy-label-pack/phone/download",
  },
  {
    key: "tablet",
    title: "DemoBrand 平板能源标签合集",
    desc: "涵盖在售平板机型的欧盟能效标签（EU Energy Label · EPREL 注册库）",
    file: "DemoBrand 平板能源标签合集.pdf",
    icon: Tablet,
    inline: "/api/v1/energy-label-pack/tablet/inline",
    download: "/api/v1/energy-label-pack/tablet/download",
  },
];

export default function EnergyLabelPackPage() {
  const { t } = useI18n();
  return (
    <AppShell>
      <div className="mx-auto max-w-5xl px-5 py-5">
        <div className="mb-4">
          <h1 className="flex items-center gap-2 text-base font-semibold text-fg">
            <FileDown size={18} className="text-accent" />
            {t("能源标签")}
          </h1>
          <p className="mt-1 text-[12px] text-muted">
            {t(
              "欧盟能效标签（EPREL）下载 · 单个机型标签可打包成 ZIP 一次性下载，也支持按设备类别合并 PDF 预览",
            )}
          </p>
        </div>

        {/* 全部机型：打包成 ZIP 一次下载 */}
        <section className="mb-4 rounded-lg border border-accent/40 bg-accent-soft/40 p-4">
          <div className="mb-3 flex items-center gap-2.5">
            <span className="flex h-9 w-9 items-center justify-center rounded-md bg-accent text-accent-on">
              <Archive size={18} />
            </span>
            <div className="min-w-0">
              <p className="text-[13px] font-semibold text-fg">
                {t("全部机型能效标签（ZIP）")}
              </p>
              <p className="text-[11px] text-meta">
                {t("DemoBrand 能源标签合集（单品）.zip")}
              </p>
            </div>
          </div>
          <p className="mb-4 text-[12px] leading-relaxed text-muted">
            {t(
              "将每一个机型的独立能效标签 PDF 整合为一个压缩包，方便批量归档与转发。",
            )}
          </p>
          <a
            href="/api/v1/energy-label-pack/zip"
            download="DemoBrand 能源标签合集（单品）.zip"
            className="inline-flex items-center gap-1.5 rounded-md bg-accent px-3.5 py-2 text-[12px] font-semibold text-accent-on transition-colors duration-fast ease-standard hover:bg-accent-hover"
          >
            <Archive size={14} />
            {t("下载全部（ZIP）")}
          </a>
        </section>

        {/* 按设备类别合并的 PDF（次要下载） */}
        <div className="grid gap-3 sm:grid-cols-2">
          {PACKS.map((p) => {
            const Icon = p.icon;
            return (
              <section
                key={p.key}
                className="rounded-lg border border-border bg-surface p-4"
              >
                <div className="mb-3 flex items-center gap-2.5">
                  <span className="flex h-9 w-9 items-center justify-center rounded-md bg-accent-soft text-accent">
                    <Icon size={18} />
                  </span>
                  <div className="min-w-0">
                    <p className="truncate text-[13px] font-semibold text-fg">
                      {p.title}
                    </p>
                    <p className="text-[11px] text-meta">{p.file}</p>
                  </div>
                </div>
                <p className="mb-4 text-[12px] leading-relaxed text-muted">
                  {p.desc}
                </p>
                <div className="flex items-center gap-2">
                  <a
                    href={p.inline}
                    target="_blank"
                    rel="noreferrer"
                    className="inline-flex items-center gap-1.5 rounded-md border border-border bg-surface-warm px-3 py-1.5 text-[12px] font-medium text-fg-2 transition-colors duration-fast ease-standard hover:bg-surface"
                  >
                    <FileText size={14} />
                    {t("预览")}
                  </a>
                  <a
                    href={p.download}
                    download={p.file}
                    className="inline-flex items-center gap-1.5 rounded-md bg-accent px-3 py-1.5 text-[12px] font-semibold text-accent-on transition-colors duration-fast ease-standard hover:bg-accent-hover"
                  >
                    <FileDown size={14} />
                    {t("下载 PDF")}
                  </a>
                </div>
              </section>
            );
          })}
        </div>

        <p className="mt-4 text-[11px] text-meta">
          {t(
            "数据来源：欧盟 EPREL 能源标签注册库（eprel.ec.europa.eu）。标签图由系统定期抓取入库，仅作展示参考。",
          )}
        </p>
      </div>
    </AppShell>
  );
}
