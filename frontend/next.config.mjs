import { execFileSync } from "node:child_process";

function resolveAppVersion() {
  if (process.env.APP_VERSION) return process.env.APP_VERSION;
  try {
    return execFileSync("git", ["describe", "--tags", "--always"], {
      encoding: "utf8",
      stdio: ["ignore", "pipe", "ignore"],
    }).trim();
  } catch {
    return "dev";
  }
}

// 远程开发时浏览器可能经代理域名访问 dev server（如 code-server 的
// code-<port>.elsworld.cn:7100），而 dev server 绑定在 localhost。
// Next.js 15.2+ 默认拦截这类跨域的 /_next/* 请求（返回 403）并拒绝
// HMR WebSocket，导致页面 chunk 加载失败、热更新失效。
// 这里把代理域名加入 allowedDevOrigins 白名单（仅需主机名，不含协议/端口）。
function resolveAllowedDevOrigins() {
  const origins = new Set(["code-3000.elsworld.cn"]);

  // 显式配置：逗号分隔的主机名列表
  if (process.env.ALLOWED_DEV_ORIGINS) {
    for (const item of process.env.ALLOWED_DEV_ORIGINS.split(",")) {
      const host = item.trim();
      if (host) origins.add(host);
    }
  }

  // 自动识别 Coder/code-server 的代理域名模板，如 https://code-{{port}}.elsworld.cn:7100/
  const proxyTemplate = process.env.VSCODE_PROXY_URI || process.env.CODE_PROXY_URI;
  if (proxyTemplate) {
    try {
      const url = new URL(proxyTemplate.replace("{{port}}", process.env.PORT || "3000"));
      if (url.hostname) origins.add(url.hostname);
    } catch {
      // 无效 URL 则忽略
    }
  }

  return [...origins];
}

/** @type {import('next').NextConfig} */
const nextConfig = {
  env: { NEXT_PUBLIC_APP_VERSION: resolveAppVersion() },
  reactStrictMode: true,
  output: "standalone",
  allowedDevOrigins: resolveAllowedDevOrigins(),
  async rewrites() {
    const backend = process.env.BACKEND_INTERNAL_URL || "http://127.0.0.1:8000";
    return [
      { source: "/api/:path*", destination: `${backend}/api/:path*` },
      { source: "/v1/:path*", destination: `${backend}/v1/:path*` },
    ];
  },
};

export default nextConfig;
