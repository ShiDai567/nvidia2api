"use client";

import { useEffect, useState } from "react";
import {
  Activity,
  Boxes,
  Coins,
  Gauge,
  Globe2,
  KeyRound,
  RefreshCw,
  Timer,
  TrendingUp,
} from "lucide-react";
import { api, DashboardStats, TokenUsageDay } from "@/lib/api";
import { Badge, Button, Card, PageHeader } from "@/components/ui";

function StatCard({
  icon: Icon,
  label,
  value,
  sub,
}: {
  icon: React.ComponentType<{ size?: number | string; className?: string }>;
  label: string;
  value: React.ReactNode;
  sub?: string;
}) {
  return (
    <Card className="p-4">
      <div className="flex items-center justify-between">
        <span className="text-xs text-gray-500">{label}</span>
        <Icon size={16} className="text-gray-600" />
      </div>
      <div className="mt-2 text-2xl font-semibold text-gray-100">{value}</div>
      {sub && <div className="mt-1 text-xs text-gray-500">{sub}</div>}
    </Card>
  );
}

function StatusBreakdown({
  title,
  data,
}: {
  title: string;
  data?: Record<string, number>;
}) {
  const entries = Object.entries(data || {});
  return (
    <Card>
      <h3 className="mb-3 text-sm font-medium text-gray-300">{title}</h3>
      {entries.length === 0 ? (
        <p className="text-sm text-gray-600">暂无数据</p>
      ) : (
        <div className="flex flex-wrap gap-2">
          {entries.map(([status, count]) => (
            <span key={status} className="flex items-center gap-1.5">
              <Badge status={status} />
              <span className="text-sm text-gray-400">{count}</span>
            </span>
          ))}
        </div>
      )}
    </Card>
  );
}

export default function DashboardPage() {
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [usage, setUsage] = useState<TokenUsageDay[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function load() {
    setLoading(true);
    setError("");
    try {
      const [s, u] = await Promise.all([
        api.get<DashboardStats>("/api/admin/dashboard"),
        api.get<{ days: TokenUsageDay[] }>("/api/admin/dashboard/usage?days=7"),
      ]);
      setStats(s);
      setUsage(u?.days ?? []);
    } catch (e) {
      setError(e instanceof Error ? e.message : "加载失败");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
    // 每 15 秒自动刷新一次，保持"实时并发"等指标更新
    const timer = setInterval(load, 15000);
    return () => clearInterval(timer);
  }, []);

  return (
    <div>
      <PageHeader
        title="仪表盘"
        subtitle="平台运行状态总览"
        actions={
          <Button onClick={load} loading={loading}>
            <RefreshCw size={14} /> 刷新
          </Button>
        }
      />

      {error && <p className="mb-4 text-sm text-red-400">{error}</p>}

      <div className="grid grid-cols-2 gap-4 md:grid-cols-3 xl:grid-cols-5">
        <StatCard
          icon={KeyRound}
          label="NVIDIA Keys"
          value={stats ? `${stats.enabled_keys} / ${stats.nvidia_keys}` : "—"}
          sub="启用 / 总数"
        />
        <StatCard
          icon={Globe2}
          label="已启用代理"
          value={stats ? `${stats.enabled_proxies} / ${stats.max_enabled_proxies ?? stats.max_proxies ?? 0}` : "—"}
          sub={`共 ${stats?.proxies ?? 0} 个代理`}
        />
        <StatCard
          icon={Boxes}
          label="模型"
          value={stats ? `${stats.enabled_models} / ${stats.models}` : "—"}
          sub="启用 / 总数"
        />
        <StatCard
          icon={TrendingUp}
          label="今日请求"
          value={stats ? stats.requests_today.toLocaleString() : "—"}
        />
        <StatCard
          icon={Activity}
          label="实时并发"
          value={stats ? (stats.active_requests ?? "—") : "—"}
          sub="当前进行中的请求数"
        />
        <StatCard
          icon={Gauge}
          label="成功率"
          value={stats ? `${Number(stats.success_rate ?? 0).toFixed(1)}%` : "—"}
        />
        <StatCard
          icon={Timer}
          label="平均延迟"
          value={stats ? `${Number(stats.avg_latency_s ?? stats.avg_latency ?? 0).toFixed(2)}s` : "—"}
        />
        <StatCard
          icon={Coins}
          label="今日 Tokens"
          value={stats ? fmtNum(stats.tokens_today ?? 0) : "—"}
          sub="输入 + 输出"
        />
      </div>

      <TokenUsageChart days={usage} />

      <div className="mt-6 grid gap-4 md:grid-cols-2">
        <StatusBreakdown title="NVIDIA Key 状态" data={stats?.key_status} />
        <StatusBreakdown title="Proxy 状态" data={stats?.proxy_status} />
      </div>
    </div>
  );
}

function fmtNum(n: number) {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
  return String(n);
}

function TokenUsageChart({ days }: { days: TokenUsageDay[] }) {
  const max = Math.max(1, ...days.map((d) => d.total_tokens || 0));
  return (
    <Card className="mt-6">
      <h3 className="mb-4 text-sm font-medium text-gray-300">Token 使用情况（近 7 天）</h3>
      {days.length === 0 ? (
        <p className="text-sm text-gray-600">暂无数据</p>
      ) : (
        <div className="flex items-end gap-2" style={{ height: 132 }}>
          {days.map((d) => {
            const p = Math.min(100, ((d.prompt_tokens || 0) / max) * 100);
            const c = Math.min(100, ((d.completion_tokens || 0) / max) * 100);
            return (
              <div key={d.date} className="group relative flex-1">
                <div className="pointer-events-none absolute -top-9 left-1/2 z-10 hidden -translate-x-1/2 whitespace-nowrap rounded-md border border-white/10 bg-[#14141d] px-2 py-1 text-[11px] text-gray-300 shadow-xl group-hover:block">
                  总计 {d.total_tokens.toLocaleString()} · 请求 {d.requests}
                </div>
                <div className="flex h-full flex-col justify-end overflow-hidden rounded-md">
                  <div style={{ height: `${c}%` }} className="w-full bg-sky-400/80" />
                  <div style={{ height: `${p}%` }} className="w-full bg-accent/80" />
                </div>
              </div>
            );
          })}
        </div>
      )}
      <div className="mt-2 flex justify-between text-[11px] text-gray-600">
        {days.map((d) => (
          <span key={d.date} className="flex-1 text-center">{d.date.slice(5)}</span>
        ))}
      </div>
      <div className="mt-3 flex items-center gap-4 text-[11px] text-gray-500">
        <span className="flex items-center gap-1.5"><span className="h-2 w-2 rounded-sm bg-accent/80" /> 输入 tokens</span>
        <span className="flex items-center gap-1.5"><span className="h-2 w-2 rounded-sm bg-sky-400/80" /> 输出 tokens</span>
        <span className="ml-auto">峰值 {fmtNum(max)}</span>
      </div>
    </Card>
  );
}
