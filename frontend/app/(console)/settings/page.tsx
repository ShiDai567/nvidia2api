"use client";

import { useCallback, useEffect, useState } from "react";
import { RefreshCw, RotateCcw, Save } from "lucide-react";
import { api, RuntimeParam } from "@/lib/api";
import { Button, Card, Input, PageHeader } from "@/components/ui";
import { toast } from "@/components/toaster";

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

  function reset(key: string) {
    const p = params.find((x) => x.key === key);
    if (p) setDraft((d) => ({ ...d, [key]: String(p.default) }));
  }

  return (
    <div>
      <PageHeader
        title="设置"
        subtitle="系统运行参数（立即生效，标注需重启的除外）"
        actions={
          <>
            <Button onClick={load} loading={loading}>
              <RefreshCw size={14} />
            </Button>
            <Button variant="primary" onClick={save} loading={saving} disabled={!params.length}>
              <Save size={14} /> 保存
            </Button>
          </>
        }
      />

      {error && <p className="mb-4 text-sm text-red-400">{error}</p>}

      <Card>
        {params.length === 0 && !loading ? (
          <p className="text-sm text-gray-500">暂无参数</p>
        ) : (
          <div className="divide-y divide-white/5">
            {params.map((p) => (
              <div key={p.key} className="flex items-center gap-4 py-3.5 first:pt-0 last:pb-0">
                <div className="w-72 shrink-0">
                  <code className="text-xs text-accent/90">
                    {p.key === "direct_routes_per_request" ? "每次请求并行直连数" : p.key}
                  </code>
                  <p className="mt-0.5 text-xs text-gray-500">{p.description}</p>
                </div>
                <div className="flex flex-1 items-center gap-2">
                  <Input
                    type="number"
                    step={p.type === "float" ? "0.1" : "1"}
                    min={p.key === "direct_routes_per_request" ? 1 : undefined}
                    aria-label={
                      p.key === "direct_routes_per_request" ? "每次请求并行直连数" : p.key
                    }
                    value={draft[p.key] ?? ""}
                    onChange={(e) => setDraft((d) => ({ ...d, [p.key]: e.target.value }))}
                    className="w-40"
                  />
                  <span className="text-xs text-gray-600">默认 {String(p.default)}</span>
                  <button
                    onClick={() => reset(p.key)}
                    title="恢复默认"
                    className="rounded p-1.5 text-gray-600 hover:bg-white/5 hover:text-gray-300"
                  >
                    <RotateCcw size={13} />
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </Card>
    </div>
  );
}
