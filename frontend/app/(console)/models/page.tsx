"use client";

import { useCallback, useEffect, useState } from "react";
import { Download, Pencil, Plus, RefreshCw, Search, Trash2 } from "lucide-react";
import { api, asList, Model } from "@/lib/api";
import {
  Badge,
  Button,
  DataTable,
  Field,
  fmtTime,
  Input,
  Modal,
  PageHeader,
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

  const filtered = models.filter(
    (m) =>
      !q ||
      m.model_name.toLowerCase().includes(q.toLowerCase()) ||
      (m.display_name || "").toLowerCase().includes(q.toLowerCase())
  );

  async function sync() {
    setSyncing(true);
    try {
      const res = await api.post<{ created?: number; existing?: number; retired?: number }>(
        "/api/admin/models/sync", {},
      );
      const parts = [`新增 ${res.created ?? 0}`, `已存在 ${res.existing ?? 0}`];
      if (res.retired) parts.push(`已下架 ${res.retired}`);
      toast.success(`同步完成：${parts.join("，")}`);
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
    }
  }

  return (
    <div>
      <PageHeader
        title="模型"
        subtitle="只有启用的模型才会通过 OpenAI API 对外提供"
        actions={
          <>
            <Button onClick={sync} loading={syncing}>
              <Download size={14} /> 同步 NVIDIA 模型
            </Button>
            <Button variant="primary" onClick={() => setEdit({ model_name: "" })}>
              <Plus size={14} /> 添加模型
            </Button>
            <Button onClick={load} loading={loading}>
              <RefreshCw size={14} />
            </Button>
          </>
        }
      />

      <div className="relative mb-4 max-w-sm">
        <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-600" />
        <Input
          className="pl-9"
          placeholder="搜索模型名称…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
      </div>

      {error && <p className="mb-4 text-sm text-red-400">{error}</p>}

      <DataTable
        loading={loading}
        empty="暂无模型，点击“同步 NVIDIA 模型”拉取"
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
                disabled={busyId === m.id}
                onChange={(v) => setEnabled(m, v)}
              />
            </Td>
            <Td className="text-xs text-gray-500">{fmtTime(m.updated_at)}</Td>
            <Td>
              <div className="flex items-center gap-1">
                <button
                  onClick={() => setEdit(m)}
                  className="rounded p-1.5 text-gray-500 hover:bg-white/10 hover:text-gray-200"
                >
                  <Pencil size={14} />
                </button>
                <button
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

      <Modal open={!!edit} title={edit?.id ? "编辑模型" : "添加模型"} onClose={() => setEdit(null)}>
        <form onSubmit={save} className="space-y-3">
          <Field label="模型名称">
            <Input
              placeholder="meta/llama-3.3-70b-instruct"
              value={edit?.model_name ?? ""}
              onChange={(e) => setEdit((p) => ({ ...p, model_name: e.target.value }))}
              required
            />
          </Field>
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
            <Button type="button" onClick={() => setEdit(null)}>
              取消
            </Button>
            <Button variant="primary" type="submit">
              保存
            </Button>
          </div>
        </form>
      </Modal>
    </div>
  );
}
