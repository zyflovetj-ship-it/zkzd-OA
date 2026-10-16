import { getAccessToken } from "./client";

export type RealtimeEventPayload = Record<string, unknown>;
export type RealtimeEventHandler = (
  type: string,
  payload: RealtimeEventPayload
) => void;

interface ConnectOptions {
  onEvent: RealtimeEventHandler;
  onStatus?: (connected: boolean) => void;
}

/**
 * 基于 fetch 的 SSE 客户端（手动解析 text/event-stream）。
 *
 * 为何不用原生 EventSource：EventSource 无法在握手时携带 Authorization 头，
 * 只能把令牌塞进 URL 查询参数 —— 违反「令牌不得进入 URL」的安全规范。
 * 故采用 fetch + ReadableStream 手动解析，令牌始终留在请求头中。
 *
 * 实时能力保障：断线后指数退避自动重连（1s→15s 封顶），重连时复用最新访问令牌。
 */
export function connectEventStream(opts: ConnectOptions): () => void {
  const base = (import.meta.env.VITE_API_BASE as string) || "http://localhost:8000";
  const url = `${base}/api/events/stream`;
  let aborted = false;
  let retryDelay = 1000;
  let controller: AbortController | null = null;
  let buffer = "";

  const scheduleReconnect = () => {
    if (aborted) return;
    const delay = retryDelay;
    retryDelay = Math.min(retryDelay * 2, 15000);
    window.setTimeout(connect, delay);
  };

  const handleFrame = (frame: string) => {
    let event = "message";
    let data = "";
    for (const raw of frame.split("\n")) {
      const line = raw.replace(/\r/g, "");
      if (line.startsWith("event:")) event = line.slice(6).trim();
      else if (line.startsWith("data:")) data += line.slice(5).trim();
    }
    if (!data) return;
    try {
      const parsed = JSON.parse(data) as RealtimeEventPayload & {
        payload?: RealtimeEventPayload;
      };
      opts.onEvent(event, parsed.payload ?? parsed);
    } catch {
      /* 忽略无法解析的帧 */
    }
  };

  const connect = async () => {
    if (aborted) return;
    const token = getAccessToken();
    if (!token) {
      // 未拿到令牌（如刚进入登录页）：延后重试，登录后自动建立连接
      window.setTimeout(connect, 2000);
      return;
    }
    controller = new AbortController();
    try {
      const res = await fetch(url, {
        method: "GET",
        headers: {
          Authorization: `Bearer ${token}`,
          Accept: "text/event-stream",
        },
        signal: controller.signal,
      });
      if (!res.ok || !res.body) {
        opts.onStatus?.(false);
        scheduleReconnect();
        return;
      }
      opts.onStatus?.(true);
      retryDelay = 1000;
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        let idx: number;
        while ((idx = buffer.indexOf("\n\n")) !== -1) {
          const frame = buffer.slice(0, idx);
          buffer = buffer.slice(idx + 2);
          handleFrame(frame);
        }
      }
      scheduleReconnect();
    } catch {
      if (!aborted) {
        opts.onStatus?.(false);
        scheduleReconnect();
      }
    }
  };

  connect();

  return () => {
    aborted = true;
    controller?.abort();
  };
}
