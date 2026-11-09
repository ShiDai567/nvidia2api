import { afterEach, describe, expect, it, vi } from "vitest";
import { readChatEvents, splitReasoning, streamChat } from "./chat-stream";

afterEach(() => vi.unstubAllGlobals());

describe("对话流", () => {
  it("流结束前处理分片，并支持跨分片的 CRLF 和中文", async () => {
    const encoder = new TextEncoder();
    let controller!: ReadableStreamDefaultController<Uint8Array>;
    const stream = new ReadableStream<Uint8Array>({
      start(c) {
        controller = c;
      },
    });
    const events: Record<string, unknown>[] = [];
    const reading = readChatEvents(stream, (event) => events.push(event));
    const bytes = encoder.encode('data: {"text":"你好"}\r\n\r\n');
    controller.enqueue(bytes.slice(0, bytes.length - 3));
    controller.enqueue(bytes.slice(bytes.length - 3));
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(events).toEqual([{ text: "你好" }]);
    controller.enqueue(encoder.encode('data: {"text":"完成"}\n\n'));
    controller.close();
    await reading;
    expect(events).toEqual([{ text: "你好" }, { text: "完成" }]);
  });

  it("未结束的思考内容也能显示", () => {
    expect(splitReasoning("<think>正在思考")).toEqual({ reasoning: "正在思考", content: "" });
    expect(splitReasoning("<think>思考</think>答案")).toEqual({
      reasoning: "思考",
      content: "答案",
    });
    expect(splitReasoning("答案", "推理")).toEqual({ reasoning: "推理", content: "答案" });
  });

  it("请求尚未结束时逐次回调回复", async () => {
    const encoder = new TextEncoder();
    let controller!: ReadableStreamDefaultController<Uint8Array>;
    const body = new ReadableStream<Uint8Array>({
      start(c) {
        controller = c;
      },
    });
    const fetchMock = vi.fn().mockResolvedValue(new Response(body));
    vi.stubGlobal("fetch", fetchMock);
    const updates: string[] = [];
    const request = streamChat("test", [{ role: "user", content: "你好" }], (message) =>
      updates.push(message.content),
    );
    controller.enqueue(encoder.encode('data: {"choices":[{"delta":{"content":"你"}}]}\n\n'));
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(updates).toEqual(["你"]);
    expect(JSON.parse(fetchMock.mock.calls[0][1].body).stream).toBe(true);
    controller.enqueue(encoder.encode('data: {"choices":[{"delta":{"content":"好"}}]}\n\n'));
    controller.close();
    await request;
    expect(updates).toEqual(["你", "你好"]);
  });

  it("流内错误会立即抛出并关闭读取", async () => {
    const cancel = vi.fn();
    const body = new ReadableStream<Uint8Array>({
      start(c) {
        c.enqueue(new TextEncoder().encode('data: {"error":{"message":"失败"}}\n\n'));
      },
      cancel,
    });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(body)));
    await expect(streamChat("test", [], () => {})).rejects.toThrow("失败");
    expect(cancel).toHaveBeenCalled();
  });
});
