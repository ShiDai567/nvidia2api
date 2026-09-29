"use client";

import { useCallback, useEffect, useState } from "react";
import { Copy, Pencil, Plus, RefreshCw, Trash2 } from "lucide-react";
import { api, asList, Model, UserApiKey } from "@/lib/api";
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

async function copyText(text: string): Promise<boolean> {
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch {
    // fall through to legacy path
  }
  try {
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.style.position = "fixed";
    ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.focus();
    ta.select();
    const ok = document.execCommand("copy");
    document.body.removeChild(ta);
    return ok;
  } catch {
    return false;
  }
}

export default function ApiKeysPage() {
  const [keys, setKeys] = useState<UserApiKey[]>([]);
  const [models, setModels] = useState<Model[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [create, setCreate] = useState<{ name: string; rate_limit: number } | null>(null);
  const [createdKey, setCreatedKey] = useState<string | null>(null);
  const [editItem, setEditItem] = useState<(UserApiKey & { _allModels?: boolean }) | null>(null);
  const [busyId, setBusyId] = useState<number | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      setKeys(asList<UserApiKey>(await api.get("/api/admin/api-keys")));
    } catch (e) {
      setError(e instanceof Error ? e.message : "加载失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
    api
      .get("/api/admin/models")
      .then((d) => setModels(asList<Model>(d)))
      .catch(() => {});
  }, [load]);

  async function doCreate(e: React.FormEvent) {
    e.preventDefault();
    if (!create) return;
    try {
      const res = await api.post<{ key?: string }>("/api/admin/api-keys", create);
      setCreate(null);
      if (res.key) setCreatedKey(res.key);
      load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "创建失败");
    }
  }

  async function setEnabled(k: UserApiKey, enabled: boolean) {
    setBusyId(k.id);
    try {
      await api.patch(`/api/admin/api-keys/${k.id}`, { enabled });
      await load();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "操作失败");
    } finally {
      setBusyId(null);
    }
  }

  function openEdit(k: UserApiKey) {
    setEditItem({ ...k, _allModels: !k.allowed_models || k.allowed_models.length === 0 });
  }

  async function saveEdit(e: React.FormEvent) {
    e.preventDefault();
    if (!editItem) return;
    try {
      const allowed = editItem._allModels
        ? []
        : (editItem.allowed_models ?? []);
      await api.patch(`/api/admin/api-keys/${editItem.id}`, {
        name: editItem.name,
        rate_limit: editItem.rate_limit,
        allowed_models: allowed,
      });
      toast.success("已保存");
      setEditItem(null);
      load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "保存失败");
    }
  }

  async function remove(k: UserApiKey) {
    if (!confirm(`确认删除 API Key「${k.name}」？该 Key 将立即失效。`)) return;
    try {
      await api.del(`/api/admin/api-keys/${k.id}`);
      load();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "删除失败");
    }
  }

  return (
    <div>
      <PageHeader
        title="用户 API Keys"
        subtitle="通过 Bearer Token 访问 OpenAI 兼容接口"
        actions={
          <>
            <Button variant="primary" onClick={() => setCreate({ name: "", rate_limit: 0 })}>
              <Plus size={14} /> 创建 API Key
            </Button>
            <Button onClick={load} loading={loading}>
              <RefreshCw size={14} />
            </Button>
          </>
        }
      />

      {error && <p className="mb-4 text-sm text-red-400">{error}</p>}

      <DataTable
        loading={loading}
        empty="暂无 API Key"
        head={
          <>
            <Th>名称</Th>
            <Th>Key</Th>
            <Th>状态</Th>
            <Th>限流 (RPM)</Th>
            <Th>允许模型</Th>
            <Th>总请求</Th>
            <Th>成功 / 失败</Th>
            <Th>最后使用</Th>
            <Th>启用</Th>
            <Th>操作</Th>
          </>
        }
      >
        {keys.map((k) => (
          <tr key={k.id} className="hover:bg-white/[0.02]">
            <Td className="font-medium text-gray-200">{k.name}</Td>
            <Td>
              <code className="font-mono text-xs text-gray-500">{k.key_prefix}…</code>
            </Td>
            <Td>
              <Badge status={k.enabled ? "enabled" : "disabled"} />
            </Td>
            <Td className="text-gray-400">{k.rate_limit > 0 ? `${k.rate_limit}/分钟` : "不限"}</Td>
            <Td className="max-w-[180px] truncate text-xs text-gray-400" title={(k.allowed_models ?? []).join(", ")}>
              {!k.allowed_models || k.allowed_models.length === 0 ? "全部模型" : `${k.allowed_models.length} 个`}
            </Td>
            <Td>{k.total_requests}</Td>
            <Td>
              <span className="text-accent">{k.success_requests}</span>
              <span className="text-gray-600"> / </span>
              <span className="text-red-400/80">{k.failed_requests}</span>
            </Td>
            <Td className="text-xs text-gray-500">{fmtTime(k.last_used_at)}</Td>
            <Td>
              <Toggle
                checked={k.enabled}
                disabled={busyId === k.id}
                onChange={(v) => setEnabled(k, v)}
              />
            </Td>
            <Td>
              <div className="flex items-center gap-1">
                <button
                  title="编辑"
                  onClick={() => openEdit(k)}
                  className="rounded p-1.5 text-gray-500 hover:bg-white/10 hover:text-gray-200"
                >
                  <Pencil size={14} />
                </button>
                <button
                  title="删除"
                  onClick={() => remove(k)}
                  className="rounded p-1.5 text-gray-500 hover:bg-red-500/15 hover:text-red-400"
                >
                  <Trash2 size={14} />
                </button>
              </div>
            </Td>
          </tr>
        ))}
      </DataTable>

      <Modal open={!!create} title="创建 API Key" onClose={() => setCreate(null)}>
        <form onSubmit={doCreate} className="space-y-3">
          <Field label="名称">
            <Input
              value={create?.name ?? ""}
              onChange={(e) => setCreate((p) => p && { ...p, name: e.target.value })}
              required
            />
          </Field>
          <Field label="每分钟限流（0 表示不限）">
            <Input
              type="number"
              min={0}
              value={create?.rate_limit ?? 0}
              onChange={(e) =>
                setCreate((p) => p && { ...p, rate_limit: Number(e.target.value) })
              }
            />
          </Field>
          <div className="flex justify-end gap-2 pt-2">
            <Button type="button" onClick={() => setCreate(null)}>
              取消
            </Button>
            <Button variant="primary" type="submit">
              创建
            </Button>
          </div>
        </form>
      </Modal>

      <Modal open={!!editItem} title="编辑 API Key" onClose={() => setEditItem(null)}>
        <form onSubmit={saveEdit} className="space-y-3">
          <Field label="名称">
            <Input
              value={editItem?.name ?? ""}
              onChange={(e) => setEditItem((p) => p && { ...p, name: e.target.value })}
              required
            />
          </Field>
          <Field label="每分钟限流（0 表示不限）">
            <Input
              type="number"
              min={0}
              value={editItem?.rate_limit ?? 0}
              onChange={(e) =>
                setEditItem((p) => p && { ...p, rate_limit: Number(e.target.value) })
              }
            />
          </Field>
          <Field label="允许调用的模型">
            <label className="mb-1.5 flex items-center gap-2 text-xs text-gray-400">
              <input
                type="checkbox"
                checked={editItem?._allModels ?? true}
                onChange={(e) =>
                  setEditItem((p) => p && ({ ...p, _allModels: e.target.checked } as typeof p))
                }
                className="accent-[var(--accent,#76B900)]"
              />
              允许全部已启用模型
            </label>
            {!editItem?._allModels && (
              <div className="max-h-44 space-y-1 overflow-y-auto rounded-lg border border-white/10 p-2">
                {models.filter((m) => m.enabled).map((m) => {
                  const checked = (editItem?.allowed_models ?? []).includes(m.model_name);
                  return (
                    <label key={m.id} className="flex items-center gap-2 text-xs text-gray-300">
                      <input
                        type="checkbox"
                        checked={checked}
                        onChange={(e) =>
                          setEditItem((p) => {
                            if (!p) return p;
                            const cur = new Set(p.allowed_models ?? []);
                            if (e.target.checked) cur.add(m.model_name);
                            else cur.delete(m.model_name);
                            return { ...p, allowed_models: [...cur] };
                          })
                        }
                        className="accent-[var(--accent,#76B900)]"
                      />
                      <span className="font-mono">{m.model_name}</span>
                    </label>
                  );
                })}
                {models.filter((m) => m.enabled).length === 0 && (
                  <p className="text-xs text-gray-600">暂无已启用模型</p>
                )}
              </div>
            )}
          </Field>
          <div className="flex justify-end gap-2 pt-2">
            <Button type="button" onClick={() => setEditItem(null)}>
              取消
            </Button>
            <Button variant="primary" type="submit">
              保存
            </Button>
          </div>
        </form>
      </Modal>

      <Modal open={!!createdKey} title="API Key 创建成功" onClose={() => setCreatedKey(null)}>
        <p className="mb-3 text-sm text-amber-400">
          完整 Key 只会显示这一次，请立即复制保存：
        </p>
        <div className="flex items-center gap-2 rounded-lg border border-white/10 bg-black/40 p-3">
          <code className="flex-1 break-all font-mono text-sm text-accent">{createdKey}</code>
          <button
            onClick={async () => {
              if (!createdKey) return;
              const ok = await copyText(createdKey);
              if (ok) toast.success("已复制到剪贴板");
              else toast.error("复制失败，请手动选中文本复制");
            }}
            className="shrink-0 rounded p-1.5 text-gray-400 hover:bg-white/10 hover:text-gray-100"
            title="复制"
          >
            <Copy size={15} />
          </button>
        </div>
        <p className="mt-2 text-[11px] text-gray-600">
          若浏览器阻止剪贴板访问，请手动选中 Key 复制。
        </p>
        <Button variant="primary" className="mt-4" onClick={() => setCreatedKey(null)}>
          我已保存
        </Button>
      </Modal>
    </div>
  );
}
