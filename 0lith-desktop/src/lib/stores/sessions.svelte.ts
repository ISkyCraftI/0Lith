import * as backend from "./pythonBackend.svelte";
import type {
  IPCRequest,
  SessionInfo,
  ListSessionsResponse,
  LoadSessionResponse,
  NewSessionResponse,
  ChatMessage,
} from "../types/ipc";

let sessions = $state<SessionInfo[]>([]);
let currentSessionId = $state<string | null>(null);

export function getSessions(): SessionInfo[] {
  return sessions;
}

export function getCurrentSessionId(): string | null {
  return currentSessionId;
}

export function setCurrentSessionId(id: string | null): void {
  currentSessionId = id;
}

export async function fetchSessions(): Promise<void> {
  try {
    const res = (await backend.send({
      id: crypto.randomUUID(),
      command: "list_sessions",
    } as IPCRequest)) as ListSessionsResponse;

    if (res.status === "ok" && res.sessions) {
      sessions = res.sessions;
    }
  } catch {
    // Silently fail — sessions list is non-critical
  }
}

export async function loadSession(
  sessionId: string,
): Promise<ChatMessage[] | null> {
  try {
    const res = (await backend.send({
      id: crypto.randomUUID(),
      command: "load_session",
      session_id: sessionId,
    } as IPCRequest)) as LoadSessionResponse;

    if (res.status === "ok" && res.messages) {
      currentSessionId = sessionId;
      return res.messages;
    }
    return null;
  } catch {
    return null;
  }
}

export async function newSession(): Promise<string | null> {
  try {
    const res = (await backend.send({
      id: crypto.randomUUID(),
      command: "new_session",
    } as IPCRequest)) as NewSessionResponse;

    if (res.status === "ok" && res.session_id) {
      currentSessionId = res.session_id;
      await fetchSessions();
      return res.session_id;
    }
    return null;
  } catch {
    return null;
  }
}
