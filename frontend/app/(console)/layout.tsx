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
      <aside className="fixed inset-x-0 top-0 z-40 flex h-14 items-center border-b border-white/5 bg-[#0c0c12]/95 md:inset-y-0 md:right-auto md:h-auto md:w-56 md:flex-col md:border-b-0 md:border-r md:backdrop-blur-xl">
        <div className="hidden items-center gap-2.5 border-b border-white/5 px-5 py-5 md:flex">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-[#76B900]/10">
            <NvidiaLogo size={20} />
          </div>
          <div>
            <div className="text-sm font-semibold tracking-wide text-gray-100">NVIDIA2API</div>
            <div className="text-[10px] text-gray-500">AI API Infrastructure</div>
          </div>
        </div>

        <nav className="flex flex-1 gap-1 overflow-x-auto px-2 md:block md:w-full md:space-y-0.5 md:overflow-y-auto md:px-3 md:py-4">
          {NAV.map((item) => {
            const active = pathname.startsWith(item.href);
            const Icon = item.icon;
            return (
              <Link
                key={item.href}
                href={item.href}
                className={cx(
                  "flex shrink-0 items-center gap-2.5 rounded-lg px-3 py-2 text-sm transition-colors",
                  active
                    ? "bg-accent/10 text-accent"
                    : "text-gray-400 hover:bg-white/5 hover:text-gray-200",
                )}
              >
                <Icon size={16} />
                <span className="whitespace-nowrap">{item.label}</span>
              </Link>
            );
          })}
        </nav>

        <div className="border-l border-white/5 px-2 md:w-full md:border-l-0 md:border-t md:p-3">
          <button
            onClick={() => {
              clearToken();
              router.replace("/login");
            }}
            className="flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-sm text-gray-400 transition-colors hover:bg-red-500/10 hover:text-red-400"
          >
            <LogOut size={16} />
            <span className="hidden md:inline">退出登录</span>
          </button>
        </div>
      </aside>

      <main className="min-w-0 flex-1 px-4 pb-6 pt-20 md:ml-56 md:px-6 md:py-6 lg:px-10">
        {children}
      </main>
    </div>
  );
}
