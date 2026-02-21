import { Command } from "@tauri-apps/plugin-shell";
import type {
  WatcherEvent,
  WatcherCommand,
  WatcherStatusEvent,
} from "../types/ipc";

// ── State ──

let child: Awaited<ReturnType<typeof Command.prototype.spawn>> | null =
  $state(null);
let connected = $state(false);
let paused = $state(false);
let suggestions = $state<WatcherEvent[]>([]);
let watcherStatus = $state<WatcherStatusEvent | null>(null);

const MAX_SUGGESTIONS = 5;

// Line buffer (same pattern as pythonBackend.svelte.ts)
let buffer = "";

function handleStdout(data: string) {
  buffer += data;
  const lines = buffer.split("\n");
  buffer = lines.pop() ?? "";

  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed) continue;

    try {
      const parsed = JSON.parse(trimmed);

      if (parsed.event === "suggestion") {
        const evt = parsed as WatcherEvent;
        suggestions = [evt, ...suggestions].slice(0, MAX_SUGGESTIONS);
      } else if (parsed.event === "status") {
        watcherStatus = parsed as WatcherStatusEvent;
        paused = watcherStatus.paused;
      }
    } catch {
      // Non-JSON output from Python, ignore
    }
  }
}

function handleStderr(data: string) {
  console.warn("[watcher stderr]", data);
}

// ── Lifecycle ──

export async function start(watchDir?: string): Promise<void> {
  if (connected) return;

  const cmd = Command.create("python-watcher", [
    "../py-backend/olith_watcher.py",
  ]);

  cmd.stdout.on("data", handleStdout);
  cmd.stderr.on("data", handleStderr);

  cmd.on("close", () => {
    connected = false;
    child = null;
  });

  child = await cmd.spawn();
  connected = true;
  buffer = "";

  // Set watch directory via stdin command (args are locked by shell scope)
  if (watchDir) {
    await sendCommand({ command: "set_watch_dir", watch_dir: watchDir });
  }
}

export async function stop(): Promise<void> {
  if (child) {
    try {
      await child.kill();
    } catch {
      /* ignore */
    }
    child = null;
    connected = false;
    suggestions = [];
    watcherStatus = null;
  }
}

async function sendCommand(cmd: WatcherCommand): Promise<void> {
  if (!child || !connected) return;
  const payload = JSON.stringify(cmd) + "\n";
  await child.write(payload).catch(() => {});
}

// ── Public API ──

export function isConnected(): boolean {
  return connected;
}

export function isPaused(): boolean {
  return paused;
}

export function getSuggestions(): WatcherEvent[] {
  return suggestions;
}

export function getStatus(): WatcherStatusEvent | null {
  return watcherStatus;
}

export async function pause(): Promise<void> {
  paused = true;
  await sendCommand({ command: "pause" });
}

export async function resume(): Promise<void> {
  paused = false;
  await sendCommand({ command: "resume" });
}

export async function setWatchDir(dir: string): Promise<void> {
  await sendCommand({ command: "set_watch_dir", watch_dir: dir });
}

export async function acceptSuggestion(id: string): Promise<string> {
  const suggestion = suggestions.find((s) => s.id === id);
  const text = suggestion?.text ?? "";
  suggestions = suggestions.filter((s) => s.id !== id);
  await sendCommand({
    command: "feedback",
    suggestion_id: id,
    action: "accepted",
  });
  return text;
}

export async function dismissSuggestion(id: string): Promise<void> {
  suggestions = suggestions.filter((s) => s.id !== id);
  await sendCommand({
    command: "feedback",
    suggestion_id: id,
    action: "dismissed",
  });
}

export function clearSuggestions(): void {
  suggestions = [];
}
