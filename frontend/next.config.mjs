/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // 容器部署：只产出运行时必需文件（.next/standalone），镜像无需携带完整 node_modules
  output: "standalone",
};

export default nextConfig;
