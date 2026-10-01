import type { Metadata } from "next";
import "./globals.css";
import { Providers } from "@/components/Providers";

// 自托管字体：字体文件随包分发、构建后由 Caddy 同源分发，运行时零外部请求。
// 避免 Google Fonts 在无法访问 Google 的网络（如中国大陆）下被墙，
// 导致渲染阻塞样式表一直 pending、整页白屏"一直在加载"。
import "@fontsource/inter/400.css";
import "@fontsource/inter/500.css";
import "@fontsource/inter/600.css";
import "@fontsource/inter/700.css";
import "@fontsource/jetbrains-mono/400.css";
import "@fontsource/jetbrains-mono/500.css";
import "@fontsource/jetbrains-mono/600.css";
import "@fontsource/noto-sans-sc/400.css";
import "@fontsource/noto-sans-sc/500.css";
import "@fontsource/noto-sans-sc/700.css";

export const metadata: Metadata = {
  title: "GTM 价格监控工作台平台",
  description:
    "演示价格情报 · 产品对比与异动告警工作台",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="zh-CN">
      <head>
        {/* 关键：iPhone Safari 没有这一行会假定页面宽 980px 整页缩放，
            Tailwind md: 断点和 window.matchMedia 永远不命中 → 全部挤成一团。 */}
        <meta
          name="viewport"
          content="width=device-width, initial-scale=1, viewport-fit=cover"
        />
        {/* 无闪烁主题：在首屏绘制前根据 localStorage 决定浅/深，默认深色（科技风）。 */}
        <script
          dangerouslySetInnerHTML={{
            __html:
              "(function(){try{var t=localStorage.getItem('pm-theme');var d=t!=='light';document.documentElement.classList.toggle('dark',d);}catch(e){document.documentElement.classList.add('dark');}})();",
          }}
        />
      </head>
      <body>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
