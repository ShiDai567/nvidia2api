"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Bot, Brain, ChevronDown, ChevronRight, CornerDownLeft, Loader2, Trash2 } from "lucide-react";
import { AdminChatResponse, API_BASE_URL, api, asList, getToken, Model } from "@/lib/api";
import { Button, Card, PageHeader, Select } from "@/components/ui";
import { Markdown } from "@/components/markdown";
import { toast } from "@/components/toaster";

interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  reasoning?: string;
  meta?: AdminChatResponse["meta"];
}

const MESSAGES_KEY = "nvidia2api_chat_messages";
const MODEL_KEY = "nvidia2api_chat_model";

const THINK_RE = /<think>([\s\S]*?)<\/think>/i;

function splitReasoning(raw: string, explicitReasoning?: string) {
  if (explicitReasoning && explicitReasoning.trim()) {
    // NVIDIA returns reasoning_content separately; content may still hold <think> tags
    const content = raw.replace(THINK_RE, "").trim();
    return { reasoning: explicitReasoning.trim(), content };
  }
  const m = raw.match(THINK_RE);
  if (m) {
    return { reasoning: m[1].trim(), content: raw.replace(THINK_RE, "").trim() };
  }
  return { reasoning: "", content: raw };
}

function loadStoredMessages(): ChatMessage[] {
  try {
    const raw = localStorage.getItem(MESSAGES_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    if (Array.isArray(parsed)) {
      return parsed.filter(
        (m): m is ChatMessage =>
          m &&
          typeof m.content === "string" &&
          (m.role === "user" || m.role === "assistant"),
      );
    }
  } catch {
    // ignore corrupted storage
  }
  return [];
}

export default function ChatPage() {
  const [models, setModels] = useState<Model[]>([]);
  const [model, setModel] = useState("");
  const [input, setInput] = useState("");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [restored, setRestored] = useState(false);
  const [sending, setSending] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  // 中途退出后重新进入：恢复上次对话内容与模型选择
  useEffect(() => {
    setMessages(loadStoredMessages());
    setModel(localStorage.getItem(MODEL_KEY) ?? "");
    setRestored(true);
  }, []);

  // 对话内容（含流式过程中的中间状态）实时落盘，刷新/退出不丢失
  useEffect(() => {
    if (!restored) return;
    try {
      if (messages.length) localStorage.setItem(MESSAGES_KEY, JSON.stringify(messages));
      else localStorage.removeItem(MESSAGES_KEY);
    } catch {
      // storage full / unavailable — ignore
    }
  }, [messages, restored]);

  useEffect(() => {
    if (model) localStorage.setItem(MODEL_KEY, model);
  }, [model]);

  useEffect(() => {
    api
      .get("/api/admin/models")
      .then((d) => asList<Model>(d))
      .then((list) => {
        const enabled = list.filter((m) => m.enabled);
        setModels(enabled);
        // 已恢复的模型选择仍然有效时保留，否则用第一个可用模型
        setModel((cur) =>
          cur && enabled.some((m) => m.model_name === cur) ? cur : (enabled[0]?.model_name ?? ""),
        );
      })
      .catch((e) => toast.error(e.message));
  }, []);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const send = useCallback(async () => {
    const text = input.trim();
    if (!text || sending) return;
    if (!model) {
      toast.error("请先在“模型”页面启用至少一个模型");
      return;
    }
    setInput("");
    const history: ChatMessage[] = [...messages, { role: "user", content: text }];
    // Streamed assistant message placeholder — updated in place per SSE chunk
    const assistant: ChatMessage = { role: "assistant", content: "", reasoning: "" };
    setMessages([...history, assistant]);
    setSending(true);

    let content = "";
    let reasoning = "";
    let meta: ChatMessage["meta"];
    let failed = false;

    const paint = () => {
      const { reasoning: r, content: c } = splitReasoning(content, reasoning || undefined);
      setMessages((prev) => {
        const next = prev.slice();
        next[next.length - 1] = { role: "assistant", content: c, reasoning: r, meta };
        return next;
      });
    };

    try {
      const res = await fetch(`${API_BASE_URL}/api/admin/chat`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Token ${getToken() ?? ""}`,
        },
        body: JSON.stringify({
          model,
          stream: true,
          messages: history.map((m) => ({ role: m.role, content: m.content })),
        }),
      });
      if (!res.ok || !res.body) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err?.error?.message || `HTTP ${res.status}`);
      }
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buf = "";
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        const events = buf.split("\n\n");
        buf = events.pop() ?? "";
        for (const evt of events) {
          const line = evt.trim();
          if (!line.startsWith("data:")) continue;
          const raw = line.slice(5).trim();
          if (raw === "[DONE]") continue;
          let data: Record<string, unknown>;
          try {
            data = JSON.parse(raw);
          } catch {
            continue;
          }
          if (data.error) {
            failed = true;
            const e = data.error as { message?: string };
            content = `⚠ ${e.message || "请求失败"}`;
            paint();
            toast.error(e.message || "请求失败");
            continue;
          }
          if (data.meta) {
            meta = { ...(meta ?? {}), ...(data.meta as ChatMessage["meta"]) };
            paint();
            continue;
          }
          if (data.summary) {
            meta = { ...(meta ?? {}), ...(data.summary as ChatMessage["meta"]) };
            paint();
            continue;
          }
          const delta = (data.choices as { delta?: Record<string, string> }[])?.[0]?.delta;
          if (delta?.content) content += delta.content;
          if (delta?.reasoning_content) reasoning += delta.reasoning_content;
          if (delta) paint();
        }
      }
      paint();
      if (!content && !reasoning && !failed) {
        setMessages(history); // nothing arrived
        toast.error("未收到有效响应");
      }
    } catch (e) {
      setMessages(history);
      toast.error(e instanceof Error ? e.message : "请求失败");
    } finally {
      setSending(false);
    }
  }, [input, messages, model, sending]);

  return (
    <div className="flex h-[calc(100vh-7rem)] flex-col">
      <PageHeader title="对话" subtitle="通过竞速引擎直接测试已启用的模型" actions={
        <>
          <Select
            value={model}
            onChange={(e) => setModel(e.target.value)}
            className="w-64 !bg-white/[0.03]"
          >
            <option value="">选择模型…</option>
            {models.map((m) => (
              <option key={m.id} value={m.model_name}>
                {m.display_name || m.model_name}
              </option>
            ))}
          </Select>
          <Button
            onClick={() => setMessages([])}
            disabled={!messages.length}
            variant="ghost"
          >
            <Trash2 size={14} /> 清空
          </Button>
        </>
      } />

      <Card className="flex-1 overflow-y-auto p-4">
        {messages.length === 0 ? (
          <div className="flex h-full flex-col items-center justify-center gap-2 text-gray-600">
            <Bot size={30} />
            <p className="text-sm">选择模型并开始对话。请求会经过代理竞速引擎转发到 NVIDIA。</p>
          </div>
        ) : (
          <div className="space-y-4">
            {messages.map((m, i) => (
              <div key={i} className={m.role === "user" ? "flex justify-end" : "flex justify-start"}>
                <div
                  className={
                    m.role === "user"
                      ? "max-w-[75%] rounded-2xl rounded-br-md bg-accent/15 px-4 py-2.5 text-sm text-gray-100"
                      : "max-w-[80%] rounded-2xl rounded-bl-md border border-white/10 bg-white/[0.04] px-4 py-2.5 text-sm text-gray-200"
                  }
                >
                  {m.reasoning && <ReasoningBlock text={m.reasoning} />}
                  {m.role === "user"
                    ? <p className="whitespace-pre-wrap leading-relaxed">{m.content}</p>
                    : m.content
                      ? <Markdown>{m.content}</Markdown>
                      : <p className="text-gray-600">&nbsp;</p>}
                  {m.meta && (
                    <div className="mt-2 border-t border-white/10 pt-2 text-[11px] text-gray-500">
                      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                        <span>首字 {Math.round(m.meta.first_token_ms ?? m.meta.first_chunk_ms ?? 0)}ms</span>
                        <span>总耗时 {Math.round(m.meta.duration_ms ?? m.meta.first_chunk_ms ?? 0)}ms</span>
                        <span>线路: {m.meta.route_type === "direct" ? "直连" : m.meta.proxy_name}</span>
                        <span>Key: {m.meta.key_name}</span>
                      </div>
                      <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-gray-500">
                        <span>输入 {m.meta.prompt_tokens ?? m.meta.usage?.prompt_tokens ?? 0}</span>
                        <span>输出 {m.meta.completion_tokens ?? m.meta.usage?.completion_tokens ?? 0}</span>
                        <span>缓存 {m.meta.cached_tokens ?? 0}</span>
                        <span>合计 {m.meta.total_tokens ?? m.meta.usage?.total_tokens ?? 0}</span>
                      </div>
                      {(m.meta.routes?.length ?? 0) > 0 && (
                        <div className="mt-1.5 space-y-0.5">
                          {(m.meta.routes ?? []).map((r, i) => (
                            <div key={i} className="flex items-center gap-2">
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
                              <span className="text-gray-400">
                                {r.kind === "direct" ? "直连" : r.proxy_name} + {r.key_name}
                              </span>
                              <span className="text-gray-600">
                                {r.status === "winner"
                                  ? `${r.latency_ms}ms · 胜出`
                                  : r.status === "cancelled"
                                    ? "已取消"
                                    : `${r.error}${r.http_status ? ` (${r.http_status})` : ""}`}
                              </span>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  )}
                </div>
              </div>
            ))}
            {sending && (
              <div className="flex items-center gap-2 text-sm text-gray-500">
                <Loader2 size={14} className="animate-spin" /> 竞速请求中…
              </div>
            )}
            <div ref={bottomRef} />
          </div>
        )}
      </Card>

      <div className="mt-3 flex items-end gap-2">
        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              void send();
            }
          }}
          rows={2}
          placeholder="输入消息，Enter 发送，Shift+Enter 换行"
          className="flex-1 resize-none rounded-xl border border-white/10 bg-white/[0.03] px-4 py-3 text-sm text-gray-200 outline-none transition-colors placeholder:text-gray-600 focus:border-accent/60"
        />
        <Button variant="primary" onClick={() => void send()} disabled={!input.trim() || sending}>
          {sending ? <Loader2 size={16} className="animate-spin" /> : <CornerDownLeft size={16} />}
          发送
        </Button>
      </div>
    </div>
  );
}


function ReasoningBlock({ text }: { text: string }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="mb-2 rounded-lg border border-amber-500/15 bg-amber-500/[0.05]">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-1.5 px-3 py-2 text-[11px] font-medium text-amber-300/90"
      >
        <Brain size={12} />
        思考过程
        {open ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
      </button>
      {open && (
        <div className="max-h-72 overflow-y-auto border-t border-amber-500/10 px-3 py-2 text-[12px] italic leading-relaxed text-gray-400/90">
          <p className="whitespace-pre-wrap">{text}</p>
        </div>
      )}
    </div>
  );
}
