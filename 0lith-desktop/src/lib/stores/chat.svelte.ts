import * as backend from "./pythonBackend.svelte";
import type { StreamCallback } from "./pythonBackend.svelte";
import * as agentsStore from "./agents.svelte";
import type {
  ChatMessage,
  AgentId,
  IPCRequest,
  IPCResponse,
  ChatResponse,
} from "../types/ipc";

const MAX_MESSAGE_LENGTH = 10000;
const MAX_HISTORY = 500;

let messages = $state<ChatMessage[]>([]);
let loading = $state(false);
let streaming = $state(false);
let elapsed = $state(0);
let activeAgent = $state<AgentId | null>(null);
let tabVisible = $state(true);

let timerInterval: ReturnType<typeof setInterval> | null = null;

// Pause timer when tab is hidden (#13)
if (typeof document !== "undefined") {
  document.addEventListener("visibilitychange", () => {
    tabVisible = document.visibilityState === "visible";
  });
}

function startTimer() {
  elapsed = 0;
  timerInterval = setInterval(() => {
    if (tabVisible) elapsed += 0.1;
  }, 100);
}

function stopTimer() {
  if (timerInterval) {
    clearInterval(timerInterval);
    timerInterval = null;
  }
}

function addMessage(msg: Omit<ChatMessage, "id" | "timestamp">): string {
  const id = crypto.randomUUID();
  messages = [
    ...messages,
    {
      ...msg,
      id,
      timestamp: Date.now(),
    },
  ];
  // Cap history to prevent memory leaks
  if (messages.length > MAX_HISTORY) {
    messages = messages.slice(-MAX_HISTORY);
  }
  return id;
}

export function updateMessage(id: string, updates: Partial<ChatMessage>): void {
  messages = messages.map((m) => (m.id === id ? { ...m, ...updates } : m));
}

export function getMessages(): ChatMessage[] {
  return messages;
}

export function isLoading(): boolean {
  return loading;
}

export function isStreaming(): boolean {
  return streaming;
}

export function getElapsed(): number {
  return elapsed;
}

export function getActiveAgent(): AgentId | null {
  return activeAgent;
}

export async function sendMessage(text: string): Promise<void> {
  if (!text.trim() || loading) return;

  // Validate message length
  if (text.length > MAX_MESSAGE_LENGTH) {
    addMessage({
      type: "error",
      content: `Message trop long (${text.length} chars, max ${MAX_MESSAGE_LENGTH}).`,
    });
    return;
  }

  // Add user message
  addMessage({ type: "user", content: text });

  loading = true;
  activeAgent = null;
  startTimer();

  let streamingMsgId: string | null = null;
  let routingReceived = false;

  // Streaming callback: receives routing and token chunks
  const onStream: StreamCallback = (data: IPCResponse) => {
    if (data.status === "routing") {
      routingReceived = true;
      const agentId = data.agent_id as AgentId;
      activeAgent = agentId;
      agentsStore.setStatus(agentId, "thinking");

      // Add routing pill
      addMessage({
        type: "routing",
        content: (data.route_reason as string) ?? "",
        agentId,
        agentName: (data.agent_name as string) ?? agentId,
        agentColor: (data.agent_color as string) ?? "#666",
        agentEmoji: (data.agent_emoji as string) ?? "?",
      });

      // Create empty streaming agent message
      streamingMsgId = addMessage({
        type: "agent",
        content: "",
        agentId,
        agentName: (data.agent_name as string) ?? agentId,
        agentColor: (data.agent_color as string) ?? "#666",
        agentEmoji: (data.agent_emoji as string) ?? "?",
      });
    } else if (data.status === "streaming" && data.chunk) {
      streaming = true;
      if (!streamingMsgId) {
        // No routing was received (direct agent call), create message now
        streamingMsgId = addMessage({
          type: "agent",
          content: data.chunk,
        });
      } else {
        // Append chunk to existing streaming message
        const existing = messages.find((m) => m.id === streamingMsgId);
        if (existing) {
          updateMessage(streamingMsgId, {
            content: existing.content + data.chunk,
          });
        }
      }
    }
  };

  try {
    const res = await backend.send(
      { id: crypto.randomUUID(), command: "chat", message: text } as IPCRequest,
      300000, // 5min — covers Aerolith's 30B model cold start
      onStream,
    );

    if (res.status === "error") {
      addMessage({ type: "error", content: res.message ?? "Unknown error" });
      return;
    }

    const chat = res as ChatResponse;
    const responseTime = Math.round(elapsed * 10) / 10;

    if (streamingMsgId) {
      updateMessage(streamingMsgId, {
        content: chat.response,
        agentId: chat.agent_id,
        agentName: chat.agent_name,
        agentColor: chat.agent_color,
        agentEmoji: chat.agent_emoji,
        responseTime,
      });
    } else {
      if (chat.route_reason) {
        addMessage({
          type: "routing",
          content: chat.route_reason,
          agentId: chat.agent_id,
          agentName: chat.agent_name,
          agentColor: chat.agent_color,
          agentEmoji: chat.agent_emoji,
        });
      }
      addMessage({
        type: "agent",
        content: chat.response,
        agentId: chat.agent_id,
        agentName: chat.agent_name,
        agentColor: chat.agent_color,
        agentEmoji: chat.agent_emoji,
        responseTime,
      });
    }

    agentsStore.setStatus(chat.agent_id, "idle");
    activeAgent = chat.agent_id;
  } catch (e: any) {
    addMessage({ type: "error", content: e?.message ?? "Request failed" });
  } finally {
    stopTimer();
    loading = false;
    streaming = false;
  }
}

export async function cancelMessage(): Promise<void> {
  stopTimer();
  loading = false;
  streaming = false;
  activeAgent = null;
  addMessage({ type: "system", content: "Request cancelled." });
  // Kill and restart Python process (also closes any active HTTP streams)
  await backend.stop();
  await backend.start();
}

export function addSystemMessage(text: string): void {
  addMessage({ type: "system", content: text });
}

export function clearMessages(): void {
  messages = [];
}

export function sendFeedback(
  messageId: string,
  rating: "up" | "down" | null,
  reason?: string,
): void {
  const msg = messages.find((m) => m.id === messageId);
  if (!msg || msg.type !== "agent") return;

  updateMessage(messageId, { rating, ratingReason: reason });

  if (rating) {
    // Fire-and-forget — no need to await
    backend
      .send(
        {
          id: crypto.randomUUID(),
          command: "feedback",
          message_id: messageId,
          agent_id: msg.agentId,
          rating,
          reason: reason ?? "",
          content: msg.content.slice(0, 500),
        } as IPCRequest,
        5000,
      )
      .catch(() => {});
  }
}
