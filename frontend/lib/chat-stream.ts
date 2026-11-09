import { API_BASE_URL, getToken, type AdminChatResponse } from "./api";

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  reasoning?: string;
  meta?: AdminChatResponse["meta"];
}

export function splitReasoning(raw: string, explicitReasoning = "") {
  const lower = raw.toLowerCase();
  const start = lower.indexOf("<think>");
  const end = start < 0 ? -1 : lower.indexOf("</think>", start + 7);
  if (start >= 0) {
    const embedded = raw.slice(start + 7, end < 0 ? undefined : end);
    const content = raw.slice(0, start) + (end < 0 ? "" : raw.slice(end + 8));
    return { reasoning: (explicitReasoning || embedded).trim(), content: content.trim() };
  }
  return { reasoning: explicitReasoning.trim(), content: raw };
}

export async function streamChat(
  model: string,
  messages: ChatMessage[],
  onUpdate: (message: ChatMessage) => void,
  signal?: AbortSignal,
) {
  const response = await fetch(`${API_BASE_URL}/api/admin/chat`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Token ${getToken() ?? ""}`,
    },
    body: JSON.stringify({
      model,
      stream: true,
      messages: messages.slice(-20).map(({ role, content }) => ({ role, content })),
    }),
    signal,
  });
  if (!response.ok || !response.body) {
    const error = await response.json().catch(() => ({}));
    throw new Error(error?.error?.message || `HTTP ${response.status}`);
  }

  let content = "";
  let reasoning = "";
  let meta: ChatMessage["meta"];
  let received = false;
  await readChatEvents(response.body, (event) => {
    if (event.error) {
      const error = event.error as { message?: string };
      throw new Error(error.message || "请求失败");
    }
    if (event.meta) meta = { ...meta, ...(event.meta as ChatMessage["meta"]) };
    if (event.summary) meta = { ...meta, ...(event.summary as ChatMessage["meta"]) };
    const delta = (event.choices as { delta?: Record<string, string> }[] | undefined)?.[0]?.delta;
    if (delta?.content) content += delta.content;
    if (delta?.reasoning_content) reasoning += delta.reasoning_content;
    if (content || reasoning) received = true;
    if (delta || event.meta || event.summary) {
      onUpdate({ role: "assistant", ...splitReasoning(content, reasoning), meta });
    }
  });
  if (!received) throw new Error("未收到有效响应");
}

export async function readChatEvents(
  stream: ReadableStream<Uint8Array>,
  onEvent: (data: Record<string, unknown>) => void,
) {
  const reader = stream.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  const dispatch = (event: string) => {
    const data = event
      .split(/\r\n|\r|\n/)
      .filter((line) => line.startsWith("data:"))
      .map((line) => line.slice(5).replace(/^ /, ""))
      .join("\n");
    if (!data || data === "[DONE]") return;
    let parsed: unknown;
    try {
      parsed = JSON.parse(data);
    } catch {
      // 忽略无效事件，继续接收后续数据。
      return;
    }
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
      onEvent(parsed as Record<string, unknown>);
    }
  };
  try {
    for (;;) {
      const { done, value } = await reader.read();
      buffer += decoder.decode(value, { stream: !done });
      const events = buffer.split(/\r\n\r\n|\n\n|\r\r/);
      buffer = events.pop() ?? "";
      events.forEach(dispatch);
      if (done) {
        if (buffer) dispatch(buffer);
        break;
      }
    }
  } catch (error) {
    await reader.cancel().catch(() => {});
    throw error;
  } finally {
    reader.releaseLock();
  }
}
