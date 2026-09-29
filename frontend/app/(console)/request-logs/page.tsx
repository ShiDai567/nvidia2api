"use client";

import { Fragment, useCallback, useEffect, useState } from "react";
import { ChevronDown, ChevronRight, RefreshCw, Search } from "lucide-react";
import { api, RequestLog } from "@/lib/api";
import {
  Badge,
  Button,
  DataTable,
  fmtLatency,
  fmtTime,
  Input,
  PageHeader,
  Select,
  Td,
  Th,
} from "@/components/ui";

interface LogPage {
  results: RequestLog[];
  total: number;
  limit: number;
  offset: number;
  next_offset: number | null;
}

const PAGE_SIZE = 100;

export default function RequestLogsPage() {
  const [logs, setLogs] = useState<RequestLog[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [nextOffset, setNextOffset] = useState<number | null>(null);
  const [model, setModel] = useState("");
  const [status, setStatus] = useState("");
  const [since, setSince] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [expanded, setExpanded] = useState<string | null>(null);

  const load = useCallback(async (off = 0) => {
    setLoading(true);
    setError("");
    try {
      const params = new URLSearchParams();
      if (model) params.set("model", model);
      if (status) params.set("status", status);
      if (since) {
        // date input gives local midnight; send ISO with timezone
        const d = new Date(`${since}T00:00:00`);
        if (!Number.isNaN(d.getTime())) params.set("since", d.toISOString());
      }
      params.set("limit", String(PAGE_SIZE));
      params.set("offset", String(off));
      const res = await api.get<LogPage>(`/api/admin/logs?${params.toString()}`);
      const page: LogPage = Array.isArray(res)
        ? { results: res as unknown as RequestLog[], total: res.length, limit: PAGE_SIZE, offset: 0, next_offset: null }
        : res;
      setLogs(page.results ?? []);
      setTotal(page.total ?? page.results?.length ?? 0);
      setOffset(page.offset ?? 0);
      setNextOffset(page.next_offset ?? null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "加载失败");
    } finally {
      setLoading(false);
    }
  }, [model, status, since]);

  useEffect(() => {
    load(0);
  }, [load]);

  return (
    <div>
      <PageHeader
        title="请求日志"
        subtitle="用户请求与线路竞速记录"
        actions={
          <Button onClick={() => load(offset)} loading={loading}>
            <RefreshCw size={14} /> 刷新
          </Button>
        }
      />

      <div className="mb-4 flex flex-wrap items-center gap-3">
        <div className="relative max-w-xs flex-1">
          <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-600" />
          <Input
            className="pl-9"
            placeholder="按模型筛选…"
            value={model}
            onChange={(e) => setModel(e.target.value)}
          />
        </div>
        <div className="w-36">
          <Select value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="">全部状态</option>
            <option value="success">成功</option>
            <option value="error">失败</option>
          </Select>
        </div>
        <div>
          <Input
            type="date"
            value={since}
            onChange={(e) => setSince(e.target.value)}
            title="起始日期"
          />
        </div>
        {(model || status || since) && (
          <Button
            variant="ghost"
            onClick={() => {
              setModel("");
              setStatus("");
              setSince("");
            }}
          >
            清除筛选
          </Button>
        )}
        <span className="ml-auto text-xs text-gray-500">
          共 {total.toLocaleString()} 条
        </span>
      </div>

      {error && <p className="mb-4 text-sm text-red-400">{error}</p>}

      <DataTable
        loading={loading}
        empty="暂无日志"
        head={
          <>
            <Th></Th>
            <Th>Request ID</Th>
            <Th>时间</Th>
            <Th>模型</Th>
            <Th>总耗时</Th>
            <Th>首字</Th>
            <Th>胜出线路 (Winner)</Th>
            <Th>Stream</Th>
            <Th>状态</Th>
            <Th>Tokens</Th>
          </>
        }
      >
        {logs.map((l) => {
          const open = expanded === l.request_id;
          return (
            <Fragment key={l.id ?? l.request_id}>
              <tr
                onClick={() => setExpanded(open ? null : l.request_id)}
                className="cursor-pointer hover:bg-white/[0.02]"
              >
                <Td className="w-6 text-gray-600">
                  {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                </Td>
                <Td className="font-mono text-xs text-gray-400">{l.request_id}</Td>
                <Td className="text-xs text-gray-500">{fmtTime(l.created_at)}</Td>
                <Td className="max-w-[220px] truncate font-mono text-xs text-gray-300" title={l.model}>
                  {l.model}
                </Td>
                <Td>{fmtLatency(l.duration_ms)}</Td>
                <Td>{l.first_token_ms != null ? fmtLatency(l.first_token_ms) : "—"}</Td>
                <Td className="text-xs text-gray-400">
                  <span className="font-mono">{l.winner_proxy_name || l.winner_key_name ? `${l.winner_proxy_name || "直连"} + ${l.winner_key_name}` : "—"}</span>
                </Td>
                <Td className="text-xs text-gray-500">{l.is_stream ? "是" : "否"}</Td>
                <Td>
                  <Badge status={l.status} />
                </Td>
                <Td className="text-xs leading-snug">
                  {l.total_tokens != null && l.total_tokens > 0 ? (
                    <>
                      <span className="text-gray-300">{l.prompt_tokens ?? 0}</span>
                      <span className="text-gray-600">/</span>
                      <span className="text-gray-300">{l.completion_tokens ?? 0}</span>
                      {(l.cached_tokens ?? 0) > 0 && (
                        <div className="text-[11px] text-gray-600">缓存↓{l.cached_tokens}</div>
                      )}
                    </>
                  ) : (
                    <span className="text-gray-600">—</span>
                  )}
                </Td>
              </tr>
              {open && (
                <tr className="bg-white/[0.02]">
                  <Td colSpan={10} className="!py-3">
                    <div className="space-y-1.5">
                      <div className="mb-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-gray-400">
                        <span className="font-medium text-gray-300">请求明细</span>
                        <span>耗时 {l.duration_ms ?? 0}ms</span>
                        <span>首字 {l.first_token_ms ?? "—"}ms</span>
                        <span>输入 {l.prompt_tokens ?? 0}</span>
                        <span>输出 {l.completion_tokens ?? 0}</span>
                        <span>缓存 {l.cached_tokens ?? 0}</span>
                        <span>合计 {l.total_tokens ?? 0}</span>
                        {l.proxy_public_ip && <span>代理出口 IP {l.proxy_public_ip}</span>}
                        {l.error_type && <span className="text-red-400">错误 {l.error_type}</span>}
                      </div>
                      <div className="mb-2 text-xs font-medium text-gray-400">线路竞速明细</div>
                      {(l.routes ?? []).length === 0 ? (
                        <p className="text-xs text-gray-600">该请求未记录线路明细（早期日志）</p>
                      ) : (
                        l.routes!.map((r, i) => (
                          <div key={i} className="flex items-center gap-2.5 text-xs">
                            <span
                              className={
                                r.status === "winner"
                                  ? "text-emerald-400"
                                  : r.status === "failed"
                                    ? "text-red-400"
                                    : "text-gray-600"
                              }
                            >
                              {r.status === "winner" ? "●" : r.status === "failed" ? "✕" : "○"}
                            </span>
                            <span className="w-28 text-gray-300">
                              {r.kind === "direct" ? "直连" : r.proxy_name}
                            </span>
                            <span className="w-36 font-mono text-gray-500">{r.key_name}</span>
                            <span className="text-gray-500">
                              {r.status === "winner"
                                ? `${r.latency_ms}ms · 胜出`
                                : r.status === "cancelled"
                                  ? "已取消"
                                  : `${r.error}${r.http_status ? ` (${r.http_status})` : ""}`}
                            </span>
                          </div>
                        ))
                      )}
                    </div>
                  </Td>
                </tr>
              )}
            </Fragment>
          );
        })}
      </DataTable>

      <div className="mt-4 flex items-center justify-between text-xs text-gray-500">
        <span>
          第 {offset + 1}-{Math.min(offset + PAGE_SIZE, total)} 条 / 共 {total.toLocaleString()} 条
        </span>
        <div className="flex gap-2">
          <Button
            variant="ghost"
            disabled={offset === 0 || loading}
            onClick={() => load(Math.max(offset - PAGE_SIZE, 0))}
          >
            上一页
          </Button>
          <Button
            variant="ghost"
            disabled={nextOffset == null || loading}
            onClick={() => nextOffset != null && load(nextOffset)}
          >
            下一页
          </Button>
        </div>
      </div>
    </div>
  );
}
