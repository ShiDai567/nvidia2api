"use client";

import { useCallback, useEffect, useState } from "react";
import { Plus, RefreshCw, Save, Trash2 } from "lucide-react";
import { api } from "@/lib/api";
import { Button, Card, Input, PageHeader } from "@/components/ui";
import { toast } from "@/components/toaster";

type Rule = { id: number; forbidden_text: string; replacement_text: string; enabled: boolean };

export default function ContentReviewPage() {
  const [rules, setRules] = useState<Rule[]>([]);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [forbidden, setForbidden] = useState("");
  const [replacement, setReplacement] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setRules(await api.get<Rule[]>("/api/admin/content-review-rules"));
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "加载失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  async function addRule() {
    if (!forbidden) return toast.error("请填写违禁文本");
    setSaving(true);
    try {
      await api.post("/api/admin/content-review-rules", {
        forbidden_text: forbidden, replacement_text: replacement,
      });
      setForbidden("");
      setReplacement("");
      await load();
      toast.success("规则已添加");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "添加失败");
    } finally {
      setSaving(false);
    }
  }

  async function updateRule(rule: Rule, patch: Partial<Rule>) {
    try {
      const updated = await api.patch<Rule>(`/api/admin/content-review-rules/${rule.id}`, patch);
      setRules((items) => items.map((item) => item.id === rule.id ? updated : item));
      toast.success("规则已保存");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "保存失败");
      await load();
    }
  }

  async function removeRule(rule: Rule) {
    try {
      await api.del(`/api/admin/content-review-rules/${rule.id}`);
      setRules((items) => items.filter((item) => item.id !== rule.id));
      toast.success("规则已删除");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "删除失败");
    }
  }

  return (
    <div>
      <PageHeader title="内容审查" subtitle="模型返回内容会按启用规则顺序进行文本替换" actions={
        <Button onClick={load} loading={loading}><RefreshCw size={14} /></Button>
      } />
      <Card className="mb-5">
        <h2 className="mb-3 text-sm font-medium text-gray-200">添加替换规则</h2>
        <div className="grid gap-3 md:grid-cols-[1fr_1fr_auto]">
          <Input aria-label="违禁文本" placeholder="违禁文本（A）" value={forbidden}
            onChange={(e) => setForbidden(e.target.value)} />
          <Input aria-label="替换文本" placeholder="替换为（B，可留空删除）" value={replacement}
            onChange={(e) => setReplacement(e.target.value)} />
          <Button variant="primary" onClick={addRule} loading={saving}><Plus size={14} /> 添加规则</Button>
        </div>
      </Card>
      <Card>
        {rules.length === 0 ? <p className="text-sm text-gray-500">{loading ? "加载中…" : "暂无审查规则"}</p> :
          <div className="space-y-3">
            {rules.map((rule) => <RuleRow key={rule.id} rule={rule} onSave={updateRule} onDelete={removeRule} />)}
          </div>}
      </Card>
    </div>
  );
}

function RuleRow({ rule, onSave, onDelete }: {
  rule: Rule;
  onSave: (rule: Rule, patch: Partial<Rule>) => Promise<void>;
  onDelete: (rule: Rule) => Promise<void>;
}) {
  const [forbidden, setForbidden] = useState(rule.forbidden_text);
  const [replacement, setReplacement] = useState(rule.replacement_text);
  return <div className="grid items-center gap-3 rounded-lg border border-white/5 p-3 md:grid-cols-[1fr_1fr_auto_auto]">
    <Input aria-label="违禁文本" value={forbidden} onChange={(e) => setForbidden(e.target.value)} />
    <Input aria-label="替换文本" value={replacement} onChange={(e) => setReplacement(e.target.value)} />
    <label className="flex items-center gap-2 text-xs text-gray-400">
      <input type="checkbox" checked={rule.enabled} onChange={(e) => void onSave(rule, { enabled: e.target.checked })} /> 启用
    </label>
    <div className="flex gap-2">
      <Button onClick={() => void onSave(rule, { forbidden_text: forbidden, replacement_text: replacement })}><Save size={14} /> 保存</Button>
      <Button variant="danger" onClick={() => void onDelete(rule)}><Trash2 size={14} /></Button>
    </div>
  </div>;
}
