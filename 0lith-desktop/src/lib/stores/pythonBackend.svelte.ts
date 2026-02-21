import { Command } from "@tauri-apps/plugin-shell";
import type { IPCRequest, IPCResponse } from "../types/ipc";

export type StreamCallback = (data: IPCResponse) => void;

type PendingRequest = {
  resolve: (value: IPCResponse) => void;
  reject: (reason: Error) => void;
  timer: ReturnType<typeof setTimeout>;
  onStream?: StreamCallback;
};

let child: Awaited<ReturnType<typeof Command.prototype.spawn>> | null =
  $state(null);
let connected = $state(false);
let error = $state("");
let intentionalStop = false;
let restartAttempts = 0;
const MAX_RESTART_ATTEMPTS = 3;

const pending = new Map<string, PendingRequest>();

// Buffer pour reconstituer les lignes JSON completes
let buffer = "";

function handleStdout(data: string) {
  buffer += data;
  const lines = buffer.split("\n");
  // Garder le dernier element (potentiellement incomplet)
  buffer = lines.pop() ?? "";

  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed) continue;

    try {
      const response: IPCResponse = JSON.parse(trimmed);
      const req = pending.get(response.id);
      if (req) {
        if (response.status === "streaming" || response.status === "routing") {
          // Intermediate message — call stream callback, don't resolve
          req.onStream?.(response);
        } else {
          // Final response (ok, error, done) — resolve the promise
          clearTimeout(req.timer);
          pending.delete(response.id);
          req.resolve(response);
        }
      }
    } catch {
      // Ligne non-JSON (debug output Python), ignorer
    }
  }
}

function handleStderr(data: string) {
  error += data;
}

export async function start(): Promise<void> {
  if (connected) return;

  const cmd = Command.create("python-backend", ["../py-backend/olith_core.py"]);

  cmd.stdout.on("data", handleStdout);
  cmd.stderr.on("data", handleStderr);

  cmd.on("close", () => {
    connected = false;
    child = null;
    // Rejeter toutes les requetes en attente
    for (const [id, req] of pending) {
      clearTimeout(req.timer);
      req.reject(new Error("Python process closed"));
      pending.delete(id);
    }
    // Auto-restart on unexpected crash
    if (!intentionalStop && restartAttempts < MAX_RESTART_ATTEMPTS) {
      restartAttempts++;
      const delay = restartAttempts * 2000; // 2s, 4s, 6s backoff
      setTimeout(() => {
        start().catch(() => {});
      }, delay);
    }
  });

  child = await cmd.spawn();
  connected = true;
  intentionalStop = false;
  restartAttempts = 0;
  error = "";
  buffer = "";
}

export async function stop(): Promise<void> {
  intentionalStop = true;
  if (child) {
    try {
      await child.kill();
    } catch {
      /* ignore */
    }
    child = null;
    connected = false;
  }
}

export async function send(
  request: IPCRequest,
  timeoutMs: number = 30000,
  onStream?: StreamCallback,
): Promise<IPCResponse> {
  if (!child || !connected) {
    await start();
  }

  return new Promise<IPCResponse>((resolve, reject) => {
    const timer = setTimeout(() => {
      pending.delete(request.id);
      reject(
        new Error(
          `Timeout after ${timeoutMs}ms for command: ${request.command}`,
        ),
      );
    }, timeoutMs);

    pending.set(request.id, { resolve, reject, timer, onStream });

    const payload = JSON.stringify(request) + "\n";
    child!.write(payload).catch((err: Error) => {
      clearTimeout(timer);
      pending.delete(request.id);
      reject(err);
    });
  });
}

export function isConnected(): boolean {
  return connected;
}

export function getError(): string {
  return error;
}

export function clearError(): void {
  error = "";
}
