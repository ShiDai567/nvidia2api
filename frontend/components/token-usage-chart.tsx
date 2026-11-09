import { Card } from "./ui";
import type { TokenUsageDay } from "../lib/api";

function fmtNum(n: number) {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
  return String(n);
}

export function TokenUsageChart({ days }: { days: TokenUsageDay[] }) {
  const max = Math.max(1, ...days.map((d) => d.total_tokens || 0));
  const hasData = days.some((d) => (d.total_tokens || 0) > 0 || (d.requests || 0) > 0);
  return (
    <Card className="mt-6">
      <h3 className="mb-4 text-sm font-medium text-gray-300">Token 使用情况（近 7 天）</h3>
      {days.length === 0 ? (
        <p className="text-sm text-gray-600">暂无数据</p>
      ) : !hasData ? (
        <p className="py-8 text-center text-sm text-gray-600">
          近 7 天没有请求记录 — 发起一次对话后这里会显示每日 Token 消耗
        </p>
      ) : (
        <div className="flex items-end gap-2" style={{ height: 132 }}>
          {days.map((d) => {
            const p = Math.min(100, ((d.prompt_tokens || 0) / max) * 100);
            const c = Math.min(100, ((d.completion_tokens || 0) / max) * 100);
            return (
              <div key={d.date} className="group relative h-full flex-1">
                <div className="pointer-events-none absolute -top-9 left-1/2 z-10 hidden -translate-x-1/2 whitespace-nowrap rounded-md border border-white/10 bg-[#14141d] px-2 py-1 text-[11px] text-gray-300 shadow-xl group-hover:block">
                  总计 {d.total_tokens.toLocaleString()} · 请求 {d.requests}
                </div>
                <div className="flex h-full flex-col justify-end overflow-hidden rounded-md border-b border-white/10">
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
          <span key={d.date} className="flex-1 text-center">
            {d.date.slice(5)}
          </span>
        ))}
      </div>
      <div className="mt-3 flex items-center gap-4 text-[11px] text-gray-500">
        <span className="flex items-center gap-1.5">
          <span className="h-2 w-2 rounded-sm bg-accent/80" /> 输入 tokens
        </span>
        <span className="flex items-center gap-1.5">
          <span className="h-2 w-2 rounded-sm bg-sky-400/80" /> 输出 tokens
        </span>
        <span className="ml-auto">峰值 {fmtNum(max)}</span>
      </div>
    </Card>
  );
}
