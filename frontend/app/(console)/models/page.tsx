"use client";

import { useCallback, useEffect, useState } from "react";
import { AlertTriangle, Download, Pencil, Plus, RefreshCw, Search, Trash2 } from "lucide-react";
import { api, asList, Model, ModelSyncResult } from "@/lib/api";
import {
  Badge,
  Button,
  DataTable,
  Field,
  fmtTime,
  Input,
  Modal,
  PageHeader,
  Select,
  Td,
  Th,
  Toggle,
} from "@/components/ui";
import { toast } from "@/components/toaster";

export default function ModelsPage() {
  const [models, setModels] = useState<Model[]>([]);
  const [q, setQ] = useState("");
  const [loading, setLoading] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [syncResult, setSyncResult] = useState<ModelSyncResult | null>(null);
  const [statusFilter, setStatusFilter] = useState("all");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [edit, setEdit] = useState<Partial<Model> | null>(null);
  const [busyId, setBusyId] = useState<number | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      setModels(asList<Model>(await api.get("/api/admin/models")));
    } catch (e) {
      setError(e instanceof Error ? e.message : "加载失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const retiredModels = models.filter((m) => m.status === "retired");
  const filtered = models.filter((m) => {
    const matchesName =
      !q ||
      m.model_name.toLowerCase().includes(q.toLowerCase()) ||
      (m.display_name || "").toLowerCase().includes(q.toLowerCase());
    const matchesStatus =
      statusFilter === "all" ||
      (statusFilter === "retired"
        ? m.status === "retired"
        : m.status !== "retired" && (statusFilter === "enabled" ? m.enabled : !m.enabled));
    return matchesName && matchesStatus;
  });

  async function sync() {
    setSyncing(true);
    setSyncResult(null);
    try {
      const res = await api.post<ModelSyncResult>("/api/admin/models/sync", {});
      setSyncResult(res);
      if (res.conflicts.length)
        toast.info(`同步发现 ${res.conflicts.length} 个原已启用模型被官方移除，请查看下方明细`);
      else
        toast.success(`同步完成：新增 ${res.created}，下架 ${res.retired}，恢复 ${res.restored}`);
      await load();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "同步失败");
    } finally {
      setSyncing(false);
    }
  }

  async function setEnabled(m: Model, enabled: boolean) {
    setBusyId(m.id);
    try {
      await api.patch(`/api/admin/models/${m.id}`, { enabled });
      await load();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "操作失败");
    } finally {
      setBusyId(null);
    }
  }

  async function remove(m: Model) {
    if (!confirm(`确认删除模型 ${m.model_name}？`)) return;
    try {
      await api.del(`/api/admin/models/${m.id}`);
      load();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "删除失败");
    }
  }

  async function save(e: React.FormEvent) {
    e.preventDefault();
    if (!edit) return;
    setSaving(true);
    try {
      const body = {
        model_name: edit.model_name,
        display_name: edit.display_name ?? "",
        description: edit.description ?? "",
      };
      if (edit.id) await api.patch(`/api/admin/models/${edit.id}`, body);
      else await api.post("/api/admin/models", body);
      setEdit(null);
      load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "保存失败");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div>
      <PageHeader
        title="模型"
        subtitle="只有启用的模型才会通过 OpenAI API 对外提供"
        actions={
          <>
            <Button
              onClick={sync}
              loading={syncing}
              disabled={loading || busyId !== null || saving}
            >
              <Download size={14} /> 同步 NVIDIA 模型
            </Button>
            <Button variant="primary" onClick={() => setEdit({ model_name: "" })}>
              <Plus size={14} /> 添加模型
            </Button>
            <Button onClick={load} loading={loading} disabled={syncing} aria-label="刷新模型列表">
              <RefreshCw size={14} />
            </Button>
          </>
        }
      />

      {syncResult && (
        <section aria-label="本次同步结果" aria-live="polite" className="glass mb-4 p-4 text-sm">
          <h2 className="font-medium text-gray-200">同步完成</h2>
          <p className="mt-1 text-gray-400">
            官方模型 {syncResult.total} 个 · 新增 {syncResult.created} 个 · 已存在{" "}
            {syncResult.existing} 个 · 下架 {syncResult.retired} 个 · 恢复 {syncResult.restored} 个
          </p>
          <p className="mt-1 text-xs text-gray-500">新增和恢复的模型默认关闭，需要手动启用。</p>
          {syncResult.conflicts.length > 0 && (
            <div
              role="alert"
              className="mt-3 rounded-lg border border-amber-500/30 bg-amber-500/10 p-3 text-amber-300"
            >
              <p className="flex items-center gap-2 font-medium">
                <AlertTriangle size={16} />
                {syncResult.conflicts.length} 个原已启用模型已从官方列表移除，现已自动禁用
              </p>
              <p className="mt-1 text-xs">
                调用这些模型的客户端需要切换模型；如用户 API Key 设置了模型白名单，请同步调整。
              </p>
              <ul className="mt-2 max-h-48 space-y-1 overflow-y-auto font-mono text-xs">
                {syncResult.conflicts.map((m) => (
                  <li key={m.id} className="break-all">
                    {m.model_name}
                  </li>
                ))}
              </ul>
            </div>
          )}
          {syncResult.retired_models.length > 0 && (
            <details className="mt-3 text-gray-400">
              <summary className="cursor-pointer">
                查看本次全部下架模型（{syncResult.retired}）
              </summary>
              <ul className="mt-2 max-h-48 space-y-1 overflow-y-auto font-mono text-xs">
                {syncResult.retired_models.map((m) => (
                  <li key={m.id} className="break-all">
                    {m.model_name} · {m.was_enabled ? "原已启用，现已禁用" : "原已关闭"}
                  </li>
                ))}
              </ul>
            </details>
          )}
          {syncResult.restored_models.length > 0 && (
            <details className="mt-3 text-gray-400">
              <summary className="cursor-pointer">
                查看官方已恢复模型（{syncResult.restored}），可重新启用
              </summary>
              <ul className="mt-2 max-h-48 space-y-1 overflow-y-auto font-mono text-xs">
                {syncResult.restored_models.map((m) => (
                  <li key={m.id} className="break-all">
                    {m.model_name}
                  </li>
                ))}
              </ul>
            </details>
          )}
        </section>
      )}

      {retiredModels.length > 0 && (
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-amber-500/25 bg-amber-500/5 p-4 text-sm text-amber-300">
          <div>
            <p className="font-medium">本地保留了 {retiredModels.length} 个官方已下架模型</p>
            <p className="mt-1 text-xs text-gray-400">
              已下架模型不可启用；重新同步确认官方恢复后，可手动启用。
            </p>
          </div>
          <Button
            onClick={() => {
              setStatusFilter("retired");
              setQ("");
            }}
          >
            查看下架模型
          </Button>
        </div>
      )}

      <div className="mb-4 flex flex-wrap items-center gap-3">
        <div className="relative w-full max-w-sm">
          <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-600" />
          <Input
            className="pl-9"
            placeholder="搜索模型名称…"
            aria-label="搜索模型名称"
            value={q}
            onChange={(e) => setQ(e.target.value)}
          />
        </div>
        <Select
          aria-label="按模型状态筛选"
          className="w-auto"
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
        >
          <option value="all">全部状态</option>
          <option value="enabled">已启用</option>
          <option value="disabled">已关闭</option>
          <option value="retired">官方已下架</option>
        </Select>
        <span className="text-xs text-gray-500">
          显示 {filtered.length} / {models.length} 个模型
        </span>
      </div>

      {error && <p className="mb-4 text-sm text-red-400">{error}</p>}

      <DataTable
        loading={loading}
        empty={
          models.length
            ? "没有符合条件的模型，请调整搜索或状态筛选"
            : "暂无模型，点击“同步 NVIDIA 模型”拉取"
        }
        head={
          <>
            <Th>模型名称</Th>
            <Th>显示名称</Th>
            <Th>Provider</Th>
            <Th>状态</Th>
            <Th>启用</Th>
            <Th>更新时间</Th>
            <Th>操作</Th>
          </>
        }
      >
        {filtered.map((m) => (
          <tr key={m.id} className="hover:bg-white/[0.02]">
            <Td className="font-mono text-xs text-gray-200">{m.model_name}</Td>
            <Td className="text-gray-400">{m.display_name || "—"}</Td>
            <Td className="text-gray-400">{m.provider || "nvidia"}</Td>
            <Td>
              {m.status === "retired" ? (
                <Badge status="retired" />
              ) : (
                <Badge status={m.enabled ? "enabled" : "disabled"} />
              )}
            </Td>
            <Td>
              <Toggle
                checked={m.enabled}
                disabled={
                  busyId !== null || syncing || loading || (m.status === "retired" && !m.enabled)
                }
                label={`${m.enabled ? "关闭" : "启用"}模型 ${m.model_name}${m.status === "retired" ? "（官方已下架，无法启用）" : ""}`}
                onChange={(v) => setEnabled(m, v)}
              />
            </Td>
            <Td className="text-xs text-gray-500">{fmtTime(m.updated_at)}</Td>
            <Td>
              <div className="flex items-center gap-1">
                <button
                  aria-label={`编辑模型 ${m.model_name}`}
                  onClick={() => setEdit(m)}
                  className="rounded p-1.5 text-gray-500 hover:bg-white/10 hover:text-gray-200"
                >
                  <Pencil size={14} />
                </button>
                <button
                  aria-label={`删除模型 ${m.model_name}`}
                  disabled={syncing}
                  onClick={() => remove(m)}
                  className="rounded p-1.5 text-gray-500 hover:bg-red-500/15 hover:text-red-400"
                >
                  <Trash2 size={14} />
                </button>
              </div>
            </Td>
          </tr>
        ))}
      </DataTable>

      <Modal
        open={!!edit}
        title={edit?.id ? "编辑模型" : "添加模型"}
        onClose={() => {
          if (!saving) setEdit(null);
        }}
      >
        <form onSubmit={save} className="space-y-3">
          <Field label="模型名称">
            <Input
              placeholder="meta/llama-3.3-70b-instruct"
              value={edit?.model_name ?? ""}
              onChange={(e) => setEdit((p) => ({ ...p, model_name: e.target.value }))}
              required
              disabled={!!edit?.id || saving}
            />
          </Field>
          {edit?.id && (
            <p className="text-xs text-gray-500">模型名称是调用标识，创建后不可修改。</p>
          )}
          <Field label="显示名称">
            <Input
              value={edit?.display_name ?? ""}
              onChange={(e) => setEdit((p) => ({ ...p, display_name: e.target.value }))}
            />
          </Field>
          <Field label="描述">
            <Input
              value={edit?.description ?? ""}
              onChange={(e) => setEdit((p) => ({ ...p, description: e.target.value }))}
            />
          </Field>
          <div className="flex justify-end gap-2 pt-2">
            <Button type="button" disabled={saving} onClick={() => setEdit(null)}>
              取消
            </Button>
            <Button variant="primary" type="submit" loading={saving}>
              保存
            </Button>
          </div>
        </form>
      </Modal>
    </div>
  );
}
