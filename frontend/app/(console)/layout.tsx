"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import {
  Activity,
  MessageSquareText,
  Boxes,
  FileClock,
  Globe2,
  KeyRound,
  LayoutDashboard,
  LogOut,
  Settings,
} from "lucide-react";
import { clearToken, getToken } from "@/lib/api";
import { cx, NvidiaLogo } from "@/components/ui";

const NAV = [
  { href: "/dashboard", label: "仪表盘", icon: LayoutDashboard },
  { href: "/chat", label: "对话", icon: MessageSquareText },
  { href: "/nvidia-keys", label: "NVIDIA Keys", icon: KeyRound },
  { href: "/proxies", label: "代理池", icon: Globe2 },
  { href: "/models", label: "模型", icon: Boxes },
  { href: "/api-keys", label: "API Keys", icon: Activity },
  { href: "/request-logs", label: "请求日志", icon: FileClock },
  { href: "/settings", label: "设置", icon: Settings },
];

export default function ConsoleLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const [ready, setReady] = useState(false);

  useEffect(() => {
    if (!getToken()) {
      router.replace("/login");
    } else {
      setReady(true);
    }
  }, [router]);

  if (!ready) return null;

  return (
    <div className="flex min-h-screen">
      <aside className="fixed inset-y-0 left-0 z-40 flex w-56 flex-col border-r border-white/5 bg-[#0c0c12]/90 backdrop-blur-xl">
        <div className="flex items-center gap-2.5 border-b border-white/5 px-5 py-5">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-[#76B900]/10">
            <NvidiaLogo size={20} />
          </div>
          <div>
            <div className="text-sm font-semibold tracking-wide text-gray-100">NVIDIA2API</div>
            <div className="text-[10px] text-gray-500">AI API Infrastructure</div>
          </div>
        </div>

        <nav className="flex-1 space-y-0.5 overflow-y-auto px-3 py-4">
          {NAV.map((item) => {
            const active = pathname.startsWith(item.href);
            const Icon = item.icon;
            return (
              <Link
                key={item.href}
                href={item.href}
                className={cx(
                  "flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm transition-colors",
                  active
                    ? "bg-accent/10 text-accent"
                    : "text-gray-400 hover:bg-white/5 hover:text-gray-200"
                )}
              >
                <Icon size={16} />
                {item.label}
              </Link>
            );
          })}
        </nav>

        <div className="border-t border-white/5 p-3">
          <button
            onClick={() => {
              clearToken();
              router.replace("/login");
            }}
            className="flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-sm text-gray-400 transition-colors hover:bg-red-500/10 hover:text-red-400"
          >
            <LogOut size={16} />
            退出登录
          </button>
        </div>
      </aside>

      <main className="ml-56 flex-1 px-6 py-6 lg:px-10">{children}</main>
    </div>
  );
}
