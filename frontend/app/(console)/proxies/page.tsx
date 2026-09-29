"use client";

import { useCallback, useEffect, useState } from "react";
import { Activity, Globe, Pencil, Plus, RefreshCw, Trash2, Upload } from "lucide-react";
import { api, asList, NvidiaKey, Proxy, ProxyGroup } from "@/lib/api";
import {
  Badge,
  Button,
  DataTable,
  Field,
  fmtLatency,
  fmtTime,
  Input,
  Modal,
  PageHeader,
  Select,
  Td,
  Textarea,
  Th,
  Toggle,
} from "@/components/ui";
import { toast } from "@/components/toaster";

export default function ProxiesPage() {
  const [proxies, setProxies] = useState<Proxy[]>([]);
  const [groups, setGroups] = useState<ProxyGroup[]>([]);
  const [keyCount, setKeyCount] = useState(0);
  const [enabledCount, setEnabledCount] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [importOpen, setImportOpen] = useState(false);
  const [importText, setImportText] = useState("");
  const [editItem, setEditItem] = useState<(Partial<Proxy> & { _clearPassword?: boolean }) | null>(null);
  const [busyId, setBusyId] = useState<number | null>(null);
  const [checkingAll, setCheckingAll] = useState(false);
  const [selected, setSelected] = useState<Set<number>>(new Set());

  const maxProxies = Math.max(keyCount - 1, 0);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [p, g, k] = await Promise.all([
        api.get("/api/admin/proxies"),
        api.get("/api/admin/proxy-groups"),
        api.get("/api/admin/nvidia-keys"),
      ]);
      const proxyList = asList<Proxy>(p);
      setProxies(proxyList);
      setEnabledCount(proxyList.filter((x) => x.enabled).length);
      setGroups(asList<ProxyGroup>(g));
      setKeyCount(asList<NvidiaKey>(k).length);
      setSelected(new Set());
    } catch (e) {
      setError(e instanceof Error ? e.message : "加载失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  function toggleSelect(id: number) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  const allSelected = proxies.length > 0 && selected.size === proxies.length;

  async function bulk(action: "enable" | "disable" | "delete" | "check") {
    const ids = [...selected];
    if (!ids.length) return;
    if (action === "delete" && !confirm(`确认删除选中的 ${ids.length} 个代理？`)) return;
    try {
      const res = await api.post<{ updated?: number; skipped?: number; deleted?: number }>(
        "/api/admin/proxies/bulk",
        { action, ids },
      );
      if (action === "enable" && res.skipped) {
        toast.info(`已启用 ${res.updated} 个，${res.skipped} 个超出 Key 数量限制被跳过`);
      } else if (action === "enable") {
        toast.success(`已启用 ${res.updated ?? ids.length} 个代理`);
      } else if (action === "disable") {
        toast.success(`已禁用 ${res.updated ?? ids.length} 个代理`);
      } else if (action === "delete") {
        toast.success(`已删除 ${res.deleted ?? ids.length} 个代理`);
      }
      await load();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "操作失败");
    }
  }

  async function setEnabled(p: Proxy, enabled: boolean) {
    setBusyId(p.id);
    try {
      await api.patch(`/api/admin/proxies/${p.id}`, { enabled });
      await load();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "操作失败");
    } finally {
      setBusyId(null);
    }
  }

  async function fetchIp(p: Proxy) {
    setBusyId(p.id);
    try {
      const res = await api.post<{ ok?: boolean; rate_limited?: boolean; error?: string }>(
        `/api/admin/proxies/${p.id}/fetch-ip`,
        {},
      );
      if (res.rate_limited) toast.error("探测源触发风控，代理状态未变更，请稍后重试");
      else if (!res.ok && res.error) toast.error(res.error);
      await load();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "获取 IP 失败");
    } finally {
      setBusyId(null);
    }
  }

  async function checkAll() {
    setCheckingAll(true);
    try {
      const res = await api.post<{ total?: number; ok?: number; failed?: number; rate_limited?: number }>(
        "/api/admin/proxies/check-all",
        {},
      );
      const total = res.total ?? 0;
      const ok = res.ok ?? 0;
      const rl = res.rate_limited ?? 0;
      const failed = res.failed ?? 0;
      const parts = [`正常 ${ok}`];
      if (rl) parts.push(`风控 ${rl}`);
      if (failed) parts.push(`失败 ${failed}`);
      const msg = `一键检测完成（${total} 个启用代理）：${parts.join("，")}`;
      if (failed) toast.error(msg);
      else if (rl) toast.info(msg);
      else toast.success(msg);
      await load();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "检测失败");
    } finally {
      setCheckingAll(false);
    }
  }

  async function remove(p: Proxy) {
    if (!confirm(`确认删除代理 ${p.name}？`)) return;
    try {
      await api.del(`/api/admin/proxies/${p.id}`);
      load();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "删除失败");
    }
  }

  async function doImport() {
    try {
      const res = await api.post<Record<string, number>>("/api/admin/proxies/import", {
        text: importText,
      });
      toast.success(`导入完成：成功 ${res.success ?? 0}，重复 ${res.duplicate ?? 0}，无效 ${res.invalid ?? 0}`);
      setImportOpen(false);
      setImportText("");
      load();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "导入失败");
    }
  }

  async function save(e: React.FormEvent) {
    e.preventDefault();
    if (!editItem) return;
    try {
      const body: Record<string, unknown> = {
        name: editItem.name,
        protocol: editItem.protocol,
        host: editItem.host,
        port: editItem.port,
        group: editItem.group ?? null,
        username: editItem.username ?? "",
      };
      // Only send password when the user actually typed one (mask = unchanged).
      if (editItem.password && editItem.password !== "••••••") {
        body.password = editItem.password;
      } else if (editItem._clearPassword === true) {
        body.password = ""; // explicit clear
      }
      if (editItem.id) await api.patch(`/api/admin/proxies/${editItem.id}`, body);
      else await api.post("/api/admin/proxies", body);
      setEditItem(null);
      load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "保存失败");
    }
  }

  return (
    <div>
      <PageHeader
        title="代理池"
        subtitle="SOCKS5 / HTTP / HTTPS 代理线路管理"
        actions={
          <>
            <Button onClick={() => setImportOpen(true)}>
              <Upload size={14} /> 批量导入
            </Button>
            <Button onClick={checkAll} loading={checkingAll}>
              <Activity size={14} /> 一键检测
            </Button>

            <Button
              variant="primary"
              onClick={() => setEditItem({ protocol: "socks5", port: 0 })}
            >
              <Plus size={14} /> 添加代理
            </Button>
            <Button onClick={load} loading={loading}>
              <RefreshCw size={14} />
            </Button>
          </>
        }
      />

      <div className="glass mb-5 flex flex-wrap items-center gap-x-6 gap-y-2 px-4 py-3 text-sm">
        <span className="text-gray-400">
          NVIDIA Key：<b className="text-gray-100">{keyCount}</b>
        </span>
        <span className="text-gray-400">
          启用代理：
          <b className={enabledCount > maxProxies ? "text-red-400" : "text-accent"}>{enabledCount}</b>
          <span className="text-gray-600"> / {maxProxies}（最多）</span>
        </span>
        <span className="text-gray-400">直连线路：1</span>
        <span className="text-gray-400">
          当前总线路：<b className="text-gray-100">{Math.min(enabledCount, maxProxies) + 1}</b>
        </span>
        {enabledCount > maxProxies && (
          <span className="text-xs text-red-400">
            已超出上限（Key 可能被删除过），多余代理不会被调度，请禁用 {enabledCount - maxProxies} 个
          </span>
        )}
        {enabledCount === maxProxies && maxProxies > 0 && (
          <span className="text-xs text-amber-400">已达启用上限</span>
        )}
      </div>

      {selected.size > 0 && (
        <div className="glass mb-4 flex flex-wrap items-center gap-2 px-4 py-2.5 text-sm">
          <span className="text-gray-400">已选 {selected.size} 项：</span>
          <Button variant="ghost" onClick={() => bulk("enable")}>批量启用</Button>
          <Button variant="ghost" onClick={() => bulk("disable")}>批量禁用</Button>
          <Button variant="ghost" onClick={() => bulk("check")}>批量测速</Button>
          <Button variant="danger" onClick={() => bulk("delete")}>批量删除</Button>
          <Button variant="ghost" onClick={() => setSelected(new Set())}>取消选择</Button>
        </div>
      )}

      {error && <p className="mb-4 text-sm text-red-400">{error}</p>}

      <DataTable
        loading={loading}
        empty="暂无代理"
        head={
          <>
            <Th className="w-8">
              <input
                type="checkbox"
                checked={allSelected}
                onChange={(e) =>
                  setSelected(e.target.checked ? new Set(proxies.map((p) => p.id)) : new Set())
                }
                className="accent-[var(--accent,#76B900)]"
              />
            </Th>
            <Th>名称</Th>
            <Th>协议</Th>
            <Th>地址</Th>
            <Th>分组</Th>
            <Th>公网 IP</Th>
            <Th>国家</Th>
            <Th>延迟</Th>
            <Th>状态</Th>
            <Th>启用</Th>
            <Th>最后检测</Th>
            <Th>操作</Th>
          </>
        }
      >
        {proxies.map((p) => (
          <tr key={p.id} className="hover:bg-white/[0.02]">
            <Td>
              <input
                type="checkbox"
                checked={selected.has(p.id)}
                onChange={() => toggleSelect(p.id)}
                className="accent-[var(--accent,#76B900)]"
              />
            </Td>
            <Td className="font-medium text-gray-200">{p.name}</Td>
            <Td>
              <code className="rounded bg-white/5 px-1.5 py-0.5 text-xs uppercase text-blue-300">
                {p.protocol}
              </code>
            </Td>
            <Td className="font-mono text-xs text-gray-400">
              {p.host}:{p.port}
            </Td>
            <Td className="text-gray-400">{p.group_name || "—"}</Td>
            <Td className="font-mono text-xs text-gray-400">{p.public_ip || "—"}</Td>
            <Td className="text-gray-400">{p.country || "—"}</Td>
            <Td>{fmtLatency(p.latency_ms)}</Td>
            <Td>
              <Badge status={p.status} />
            </Td>
            <Td>
              <Toggle
                checked={p.enabled}
                disabled={busyId === p.id}
                onChange={(v) => setEnabled(p, v)}
              />
            </Td>
            <Td className="text-xs text-gray-500">{fmtTime(p.last_check_at)}</Td>
            <Td>
              <div className="flex items-center gap-1">
                <button
                  title="获取 IP"
                  disabled={busyId === p.id}
                  onClick={() => fetchIp(p)}
                  className="rounded p-1.5 text-gray-500 hover:bg-white/10 hover:text-gray-200"
                >
                  <Globe size={14} />
                </button>
                <button
                  title="编辑"
                  onClick={() => setEditItem(p)}
                  className="rounded p-1.5 text-gray-500 hover:bg-white/10 hover:text-gray-200"
                >
                  <Pencil size={14} />
                </button>
                <button
                  title="删除"
                  onClick={() => remove(p)}
                  className="rounded p-1.5 text-gray-500 hover:bg-red-500/15 hover:text-red-400"
                >
                  <Trash2 size={14} />
                </button>
              </div>
            </Td>
          </tr>
        ))}
      </DataTable>

      <Modal open={importOpen} wide title="批量导入代理" onClose={() => setImportOpen(false)}>
        <p className="mb-3 text-xs leading-relaxed text-gray-500">
          每行一条：名称---协议://[user:pass@]host:port，或直接写代理地址
        </p>
        <Textarea
          rows={10}
          placeholder={"美国01---socks5://127.0.0.1:10001\nhttp://127.0.0.1:10003"}
          value={importText}
          onChange={(e) => setImportText(e.target.value)}
        />
        <div className="mt-4 flex justify-end gap-2">
          <Button onClick={() => setImportOpen(false)}>取消</Button>
          <Button variant="primary" onClick={doImport} disabled={!importText.trim()}>
            导入
          </Button>
        </div>
      </Modal>

      <Modal
        open={!!editItem}
        title={editItem?.id ? "编辑代理" : "添加代理"}
        onClose={() => setEditItem(null)}
      >
        <form onSubmit={save} className="space-y-3">
          <Field label="名称">
            <Input
              value={editItem?.name ?? ""}
              onChange={(e) => setEditItem((p) => ({ ...p, name: e.target.value }))}
              required
            />
          </Field>
          <div className="grid grid-cols-3 gap-3">
            <Field label="协议">
              <Select
                value={editItem?.protocol ?? "socks5"}
                onChange={(e) => setEditItem((p) => ({ ...p, protocol: e.target.value }))}
              >
                <option value="socks5">socks5</option>
                <option value="socks5h">socks5h</option>
                <option value="http">http</option>
                <option value="https">https</option>
              </Select>
            </Field>
            <Field label="Host">
              <Input
                value={editItem?.host ?? ""}
                onChange={(e) => setEditItem((p) => ({ ...p, host: e.target.value }))}
                required
              />
            </Field>
            <Field label="端口">
              <Input
                type="number"
                min={1}
                max={65535}
                value={editItem?.port ?? ""}
                onChange={(e) => setEditItem((p) => ({ ...p, port: Number(e.target.value) }))}
                required
              />
            </Field>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <Field label="用户名（可选）">
              <Input
                value={editItem?.username ?? ""}
                onChange={(e) => setEditItem((p) => ({ ...p, username: e.target.value }))}
                placeholder="无认证则留空"
              />
            </Field>
            <Field label="密码（可选）">
              <Input
                type="password"
                value={editItem?.password ?? ""}
                onChange={(e) => setEditItem((p) => ({ ...p, password: e.target.value }))}
                placeholder={editItem?.id ? "留空保持不变（•••••• 为已设置）" : "无认证则留空"}
              />
              {editItem?.id && (
                <label className="mt-1 flex items-center gap-1.5 text-xs text-gray-500">
                  <input
                    type="checkbox"
                    checked={editItem?._clearPassword === true}
                    onChange={(e) =>
                      setEditItem((p) => p && ({ ...p, _clearPassword: e.target.checked, password: "" } as typeof p))
                    }
                    className="accent-[var(--accent,#76B900)]"
                  />
                  清除已保存的密码
                </label>
              )}
            </Field>
          </div>
          <Field label="分组">
            <Select
              value={editItem?.group ?? ""}
              onChange={(e) =>
                setEditItem((p) => ({ ...p, group: e.target.value ? Number(e.target.value) : null }))
              }
            >
              <option value="">未分组</option>
              {groups.map((g) => (
                <option key={g.id} value={g.id}>
                  {g.name}
                </option>
              ))}
            </Select>
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
    </div>
  );
}
