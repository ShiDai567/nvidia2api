"use client";

import { useCallback, useEffect, useState } from "react";
import { RefreshCw, RotateCcw, Save } from "lucide-react";
import { api, RuntimeParam } from "@/lib/api";
import { Button, Card, Input, PageHeader } from "@/components/ui";
import { toast } from "@/components/toaster";

const PARAM_DISPLAY: Record<string, { group: string; label: string; unit: string; min?: number }> =
  {
    default_nvidia_rpm: { group: "请求与路由", label: "Key 默认请求限额", unit: "次 / 分钟" },
    max_routes_per_request: {
      group: "请求与路由",
      label: "单次请求最大线路数",
      unit: "条",
      min: 1,
    },
    direct_routes_per_request: {
      group: "请求与路由",
      label: "单次请求并行直连数",
      unit: "条",
      min: 1,
    },
    proxy_timeout: { group: "连接与超时", label: "代理测速超时", unit: "秒" },
    upstream_connect_timeout: { group: "连接与超时", label: "上游连接超时", unit: "秒" },
    upstream_read_timeout: { group: "连接与超时", label: "上游读取超时", unit: "秒" },
    max_concurrent_requests: { group: "并发与排队", label: "对话并发上限", unit: "个", min: 1 },
    max_queued_requests: { group: "并发与排队", label: "最大排队对话数", unit: "个", min: 1 },
    request_queue_timeout: { group: "并发与排队", label: "排队等待超时", unit: "秒", min: 0.01 },
    proxy_failure_cooldown_seconds: { group: "故障恢复", label: "代理失败冷却时间", unit: "秒" },
    proxy_unhealthy_threshold: { group: "故障恢复", label: "代理连续失败阈值", unit: "次" },
    key_cooldown_seconds: { group: "故障恢复", label: "Key 失败冷却时间", unit: "秒" },
  };

export default function SettingsPage() {
  const [params, setParams] = useState<RuntimeParam[]>([]);
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const data = await api.get<RuntimeParam[]>("/api/admin/settings");
      const list = Array.isArray(data) ? data : [];
      setParams(list);
      setDraft(Object.fromEntries(list.map((p) => [p.key, String(p.value)])));
    } catch (e) {
      setError(e instanceof Error ? e.message : "加载失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function save() {
    setSaving(true);
    try {
      const settings: Record<string, string | number> = {};
      for (const p of params) {
        const raw = draft[p.key] ?? String(p.value);
        settings[p.key] = p.type === "int" || p.type === "float" ? Number(raw) : raw;
      }
      const updated = await api.patch<RuntimeParam[]>("/api/admin/settings", { settings });
      const list = Array.isArray(updated) ? updated : [];
      setParams(list);
      setDraft(Object.fromEntries(list.map((p) => [p.key, String(p.value)])));
      toast.success("设置已保存");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "保存失败");
    } finally {
      setSaving(false);
    }
  }

  const groups = new Map<string, RuntimeParam[]>();
  for (const param of params) {
    const name = PARAM_DISPLAY[param.key]?.group ?? "其他参数";
    const group = groups.get(name);
    if (group) group.push(param);
    else groups.set(name, [param]);
  }

  return (
    <div>
      <PageHeader
        title="设置"
        subtitle="系统运行参数，保存后立即生效"
        actions={
          <>
            <Button onClick={load} loading={loading} disabled={saving}>
              <RefreshCw size={14} /> 刷新
            </Button>
            <Button
              variant="primary"
              onClick={save}
              loading={saving}
              disabled={loading || !params.length}
            >
              <Save size={14} /> 保存设置
            </Button>
          </>
        }
      />

      {error && <p className="mb-4 text-sm text-red-400">{error}</p>}

      <div className="space-y-4">
        {params.length === 0 ? (
          <Card>
            <p role="status" className="py-6 text-center text-sm text-gray-500">
              {loading ? "正在加载运行参数…" : "暂无参数"}
            </p>
          </Card>
        ) : (
          Array.from(groups, ([name, items]) => (
            <Card key={name}>
              <div className="grid items-baseline gap-4 border-b border-white/10 pb-3 lg:grid-cols-[minmax(0,1fr)_11rem_10rem]">
                <h2 className="text-sm font-medium text-gray-200">{name}</h2>
                <span className="hidden text-xs text-gray-500 lg:block">当前值</span>
                <span className="hidden text-xs text-gray-500 lg:block">默认值</span>
              </div>
              <div className="divide-y divide-white/5">
                {items.map((p) => {
                  const display = PARAM_DISPLAY[p.key];
                  const label = display?.label ?? p.key;
                  return (
                    <div
                      key={p.key}
                      className="grid min-w-0 gap-3 py-3 last:pb-0 sm:grid-cols-[minmax(0,1fr)_10rem] sm:items-center lg:grid-cols-[minmax(0,1fr)_11rem_10rem] lg:gap-4"
                    >
                      <div className="min-w-0 break-words sm:col-span-2 lg:col-span-1">
                        <label htmlFor={p.key} className="text-sm font-medium text-gray-200">
                          {label}
                        </label>
                        <p
                          id={`${p.key}-description`}
                          className="mt-1 text-xs leading-5 text-gray-500"
                        >
                          {p.description}
                        </p>
                      </div>
                      <div className="flex min-w-0 items-center gap-3">
                        <Input
                          id={p.key}
                          type="number"
                          step={p.type === "float" ? "any" : "1"}
                          min={display?.min}
                          aria-describedby={`${p.key}-description`}
                          value={draft[p.key] ?? ""}
                          disabled={loading || saving}
                          onChange={(e) => {
                            const value = e.currentTarget.value;
                            setDraft((d) => ({ ...d, [p.key]: value }));
                          }}
                          className="max-w-24 tabular-nums disabled:opacity-50"
                        />
                        <span className="shrink-0 text-xs text-gray-400">{display?.unit}</span>
                      </div>
                      <div className="flex items-center justify-between gap-2">
                        <span className="text-xs tabular-nums text-gray-400">
                          <span className="lg:hidden">默认 </span>
                          {String(p.default)}
                          {display?.unit ? ` ${display.unit}` : ""}
                        </span>
                        <Button
                          type="button"
                          variant="outline"
                          onClick={() => setDraft((d) => ({ ...d, [p.key]: String(p.default) }))}
                          disabled={loading || saving || draft[p.key] === String(p.default)}
                          title="恢复默认值，保存后生效"
                          aria-label={`恢复${label}的默认值`}
                        >
                          <RotateCcw size={14} />
                        </Button>
                      </div>
                    </div>
                  );
                })}
              </div>
            </Card>
          ))
        )}
      </div>
    </div>
  );
}
