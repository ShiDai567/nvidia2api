"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  Bot,
  Brain,
  ChevronDown,
  ChevronRight,
  ArrowDown,
  ArrowUp,
  Copy,
  Loader2,
  MessageSquarePlus,
  Trash2,
} from "lucide-react";
import Link from "next/link";
import { api, asList, Model } from "@/lib/api";
import { Button, Select } from "@/components/ui";
import { Markdown } from "@/components/markdown";
import { toast } from "@/components/toaster";
import { streamChat, type ChatMessage } from "@/lib/chat-stream";

const MESSAGES_KEY = "nvidia2api_chat_messages";
const MODEL_KEY = "nvidia2api_chat_model";

function loadStoredMessages(): ChatMessage[] {
  try {
    const raw = localStorage.getItem(MESSAGES_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    if (Array.isArray(parsed)) {
      return parsed.filter(
        (m): m is ChatMessage =>
          m && typeof m.content === "string" && (m.role === "user" || m.role === "assistant"),
      );
    }
  } catch {
    // ignore corrupted storage
  }
  return [];
}

// Keep at most this many messages locally; older turns are trimmed (context
// sent upstream is capped separately).
const MAX_STORED_MESSAGES = 60;
export default function ChatPage() {
  const [models, setModels] = useState<Model[]>([]);
  const [model, setModel] = useState("");
  const [input, setInput] = useState("");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [restored, setRestored] = useState(false);
  const [sending, setSending] = useState(false);
  const [followLatest, setFollowLatest] = useState(true);
  const bottomRef = useRef<HTMLDivElement>(null);
  const requestRef = useRef<AbortController | null>(null);

  useEffect(() => () => requestRef.current?.abort(), []);

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
      if (messages.length)
        localStorage.setItem(MESSAGES_KEY, JSON.stringify(messages.slice(-MAX_STORED_MESSAGES)));
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
    if (followLatest) bottomRef.current?.scrollIntoView({ block: "end" });
  }, [messages, followLatest]);

  const send = useCallback(async () => {
    const text = input.trim();
    if (!text || sending || requestRef.current) return;
    if (!model) {
      toast.error("请先在“模型”页面启用至少一个模型");
      return;
    }
    setInput("");
    setFollowLatest(true);
    const history: ChatMessage[] = [...messages, { role: "user", content: text }];
    // Streamed assistant message placeholder — updated in place per SSE chunk
    const assistant: ChatMessage = { role: "assistant", content: "", reasoning: "" };
    setMessages([...history, assistant]);
    setSending(true);

    const controller = new AbortController();
    requestRef.current = controller;
    let received = false;
    try {
      await streamChat(
        model,
        history,
        (message) => {
          if (message.content || message.reasoning) received = true;
          setMessages((prev) => [...prev.slice(0, -1), message]);
        },
        controller.signal,
      );
    } catch (e) {
      if (!controller.signal.aborted) {
        if (!received) setMessages(history);
        toast.error(e instanceof Error ? e.message : "请求失败");
      }
    } finally {
      requestRef.current = null;
      setSending(false);
    }
  }, [input, messages, model, sending]);

  return (
    <div className="flex h-[calc(100dvh-8rem)] min-h-[420px] flex-col md:h-[calc(100dvh-3rem)]">
      <header className="flex flex-wrap items-center justify-between gap-3 border-b border-white/10 pb-4">
        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-md bg-accent/10 text-accent">
            <MessageSquarePlus size={18} />
          </div>
          <div>
            <h1 className="text-lg font-semibold text-gray-100">对话</h1>
            <p className="text-xs text-gray-500">{sending ? "正在生成回复" : "模型对话工作台"}</p>
          </div>
        </div>
        <div className="flex min-w-0 items-center gap-2">
          <label htmlFor="chat-model" className="sr-only">
            选择模型
          </label>
          <Select
            id="chat-model"
            value={model}
            onChange={(e) => setModel(e.target.value)}
            disabled={sending}
            className="w-40 !bg-white/[0.03] sm:w-64"
          >
            <option value="">选择模型…</option>
            {models.map((m) => (
              <option key={m.id} value={m.model_name}>
                {m.display_name || m.model_name}
              </option>
            ))}
          </Select>
          <Button
            onClick={() => {
              if (window.confirm("确定清空当前对话吗？")) setMessages([]);
            }}
            disabled={!messages.length || sending}
            variant="ghost"
            title="清空对话"
          >
            <Trash2 size={15} /> <span className="hidden sm:inline">清空</span>
          </Button>
        </div>
      </header>

      <div className="relative min-h-0 flex-1">
        <div
          onScroll={(e) => {
            const el = e.currentTarget;
            setFollowLatest(el.scrollHeight - el.scrollTop - el.clientHeight < 80);
          }}
          className="h-full overflow-y-auto px-1 py-6 sm:px-4"
        >
          {messages.length === 0 ? (
            <div className="mx-auto flex h-full max-w-3xl flex-col justify-center px-2 pb-8">
              <div className="mb-5 flex h-12 w-12 items-center justify-center rounded-md border border-accent/20 bg-accent/10 text-accent">
                <Bot size={24} />
              </div>
              <h2 className="text-xl font-semibold text-gray-100">开始一段对话</h2>
              <p className="mt-2 text-sm leading-relaxed text-gray-400">
                选择模型，在下方输入消息即可开始。
              </p>
              {!model && (
                <Link href="/models" className="mt-4 w-fit text-sm text-accent hover:underline">
                  前往启用模型 →
                </Link>
              )}
            </div>
          ) : (
            <div className="mx-auto max-w-3xl space-y-7">
              {messages.map((m, i) => (
                <div
                  key={i}
                  className={m.role === "user" ? "flex justify-end" : "flex justify-start"}
                >
                  <div
                    className={
                      m.role === "user"
                        ? "max-w-[90%] rounded-lg bg-white/[0.08] px-4 py-3 text-sm text-gray-100 sm:max-w-[75%]"
                        : "min-w-0 w-full text-sm text-gray-200"
                    }
                  >
                    {m.role === "assistant" && (
                      <div className="mb-3 flex items-center gap-2 text-xs font-medium text-gray-400">
                        <Bot size={16} className="text-accent" /> 助手
                      </div>
                    )}
                    {m.reasoning && (
                      <ReasoningBlock
                        text={m.reasoning}
                        streaming={sending && i === messages.length - 1}
                      />
                    )}
                    {m.role === "user" ? (
                      <p className="whitespace-pre-wrap leading-relaxed">{m.content}</p>
                    ) : m.content ? (
                      <Markdown>{m.content}</Markdown>
                    ) : (
                      <p className="text-gray-600">&nbsp;</p>
                    )}
                    {m.meta && (
                      <details className="mt-4 text-xs text-gray-500">
                        <summary className="w-fit cursor-pointer hover:text-gray-300">
                          请求详情
                        </summary>
                        <div className="mt-2 border-l border-white/10 pl-3 text-[11px] text-gray-500">
                          <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                            <span>
                              首字 {Math.round(m.meta.first_token_ms ?? m.meta.first_chunk_ms ?? 0)}
                              ms
                            </span>
                            <span>
                              总耗时 {Math.round(m.meta.duration_ms ?? m.meta.first_chunk_ms ?? 0)}
                              ms
                            </span>
                            <span>
                              线路: {m.meta.route_type === "direct" ? "直连" : m.meta.proxy_name}
                            </span>
                            <span>Key: {m.meta.key_name}</span>
                          </div>
                          <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-gray-500">
                            <span>
                              输入 {m.meta.prompt_tokens ?? m.meta.usage?.prompt_tokens ?? 0}
                            </span>
                            <span>
                              输出{" "}
                              {m.meta.completion_tokens ?? m.meta.usage?.completion_tokens ?? 0}
                            </span>
                            <span>缓存 {m.meta.cached_tokens ?? 0}</span>
                            <span>
                              合计 {m.meta.total_tokens ?? m.meta.usage?.total_tokens ?? 0}
                            </span>
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
                                    {r.status === "winner"
                                      ? "●"
                                      : r.status === "failed"
                                        ? "✕"
                                        : "○"}
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
                      </details>
                    )}
                    {m.role === "assistant" &&
                      m.content &&
                      !(sending && i === messages.length - 1) && (
                        <button
                          type="button"
                          title="复制回复"
                          aria-label="复制回复"
                          onClick={() => {
                            void navigator.clipboard.writeText(m.content).then(
                              () => toast.success("已复制回复"),
                              () => toast.error("复制失败"),
                            );
                          }}
                          className="mt-3 rounded p-1 text-gray-500 hover:bg-white/5 hover:text-gray-200"
                        >
                          <Copy size={14} />
                        </button>
                      )}
                  </div>
                </div>
              ))}
              {sending &&
                !messages[messages.length - 1]?.content &&
                !messages[messages.length - 1]?.reasoning && (
                  <div className="flex items-center gap-2 text-sm text-gray-500">
                    <Loader2 size={14} className="animate-spin" /> 竞速请求中…
                  </div>
                )}
              <div ref={bottomRef} />
            </div>
          )}
        </div>
        {!followLatest && (
          <button
            type="button"
            onClick={() => setFollowLatest(true)}
            aria-label="回到最新消息"
            title="回到最新消息"
            className="absolute bottom-3 right-4 rounded-full border border-white/15 bg-[#202027] p-2 text-gray-200 shadow-lg hover:bg-[#303039]"
          >
            <ArrowDown size={16} />
          </button>
        )}
      </div>

      <div className="mx-auto w-full max-w-3xl pt-3">
        <div className="rounded-lg border border-white/15 bg-white/[0.04] focus-within:border-accent/60">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              // Don't send while an IME (中文输入法等) is composing
              if (e.nativeEvent.isComposing) return;
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                void send();
              }
            }}
            rows={3}
            aria-label="输入消息"
            placeholder="输入消息…"
            className="block max-h-48 min-h-[72px] w-full resize-y bg-transparent px-4 pt-3 text-sm text-gray-200 outline-none placeholder:text-gray-500"
          />
          <div className="flex items-center justify-between gap-2 px-3 pb-3">
            <span className="text-xs text-gray-500">Enter 发送 · Shift + Enter 换行</span>
            <Button
              variant="primary"
              onClick={() => void send()}
              disabled={!input.trim() || sending || !model}
            >
              {sending ? <Loader2 size={16} className="animate-spin" /> : <ArrowUp size={16} />}{" "}
              发送
            </Button>
          </div>
        </div>
        <p className="mt-2 text-center text-xs text-gray-500">对话保存在当前浏览器中</p>
      </div>
    </div>
  );
}

function ReasoningBlock({ text, streaming }: { text: string; streaming: boolean }) {
  const [open, setOpen] = useState(streaming);
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
