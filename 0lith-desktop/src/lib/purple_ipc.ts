/**
 * 0Lith — Purple Team IPC
 * =======================
 * Types et fonctions pour communiquer avec olith_purple.py via stdin/stdout
 * JSON line-delimited (même protocole que pythonBackend.svelte.ts).
 *
 * Protocole:
 *   Request:  {"id": "uuid", "command": "...", ...params}
 *   Response: {"id": "uuid", "status": "ok|error", ...data}
 *   Stream:   {"id": "uuid", "status": "purple", ...event_data}  (non-résolvant)
 *
 * Lifecycle:
 *   - Le processus n'est PAS démarré au boot de l'app.
 *   - Il est démarré ON DEMAND via start() lors du lancement d'un match.
 *   - Il est stoppé via stop() ou automatiquement sur "app-quit".
 */

import { Command } from "@tauri-apps/plugin-shell";
import { listen } from "@tauri-apps/api/event";

// ---------------------------------------------------------------------------
// Request types
// ---------------------------------------------------------------------------

export interface PurpleGenerateScenarioRequest {
  seed?: number;
  difficulty: "easy" | "medium" | "hard";
  control?: boolean;
}

export interface PurpleStartMatchRequest {
  seed?: number;
  difficulty: "easy" | "medium" | "hard";
  sparring_token: string;
  skip_safety?: boolean;
}

export type PurpleMatchStatusRequest = Record<string, never>;
export type PurpleMatchResultRequest = Record<string, never>;
export type PurpleStopMatchRequest   = Record<string, never>;

// ---------------------------------------------------------------------------
// Response data types
// ---------------------------------------------------------------------------

export interface PurpleScenarioInfo {
  seed:               number;
  difficulty:         string;
  services:           string[];
  objective:          string;
  mitre_techniques:   string[];
  control_scenario:   boolean;
}

export interface PurpleGenerateScenarioResponse {
  scenario: PurpleScenarioInfo;
}

export interface PurpleStartMatchResponse {
  match_id:       string;
  scenario_seed:  number;
  difficulty:     string;
  message:        string;
}

export interface PurpleMatchStatusResponse {
  running:      boolean;
  match_id?:    string;
  phase?:       string;
  rounds_done?: number;
  elapsed_s?:   number;
  finished?:    boolean;
  error?:       string;
  message?:     string;
}

export interface PurpleScoreDetail {
  total:                 number;
  // Red fields
  objective_achieved?:   boolean;
  services_compromised?: number;
  detection_evasion?:    number;
  efficiency?:           number;
  technique_diversity?:  number;
  penalties?:            number;
  // Blue fields
  detected?:             boolean;
  detection_round?:      number;
  sigma_valid?:          number;
  sigma_matching?:       number;
  patch_proposed?:       boolean;
  root_cause_identified?:boolean;
  false_positives?:      number;
  disruptions?:          number;
  [key: string]: unknown;
}

export interface PurpleMatchResultData {
  match_id:         string;
  winner:           "red" | "blue" | "draw";
  red_score:        PurpleScoreDetail;
  blue_score:       PurpleScoreDetail;
  dpo_pairs_count:  number;
  duration_seconds: number;
  phase_reached:    string;
  error?:           string;
  [key: string]: unknown;
}

export interface PurpleMatchResultResponse {
  available: boolean;
  result?:   PurpleMatchResultData;
  message?:  string;
  error?:    string;
}

export interface PurpleStopMatchResponse {
  stopped:   boolean;
  match_id?: string;
  message:   string;
}

// ---------------------------------------------------------------------------
// Stream event types (status = "purple")
// ---------------------------------------------------------------------------

export type PurpleEventType =
  | "match_started"
  | "round_started"
  | "move_generated"
  | "round_complete"
  | "match_complete"
  | "match_error"
  | "match_timeout";

export interface PurpleAgentMoveEvent {
  content:    string;
  move_type:  string;
  commands?:  string[];
  duration_s?: number;
  [key: string]: unknown;
}

export interface PurpleStreamEvent {
  id:           string;
  status:       "purple";
  event:        PurpleEventType;
  match_id:     string;
  // Phase / round tracking
  phase?:       string;
  round?:       number;
  total_rounds?: number;
  elapsed_s?:   number;
  // Move data (round events)
  red_move?:    PurpleAgentMoveEvent;
  blue_move?:   PurpleAgentMoveEvent;
  score?:       { red: number; blue: number };
  // Completion
  result?:      PurpleMatchResultData;
  // Error
  error?:       string;
  // Match started fields
  scenario_seed?: number;
  difficulty?:    string;
  [key: string]: unknown;
}

export type PurpleStreamCallback = (event: PurpleStreamEvent) => void;

// ---------------------------------------------------------------------------
// Internal IPC envelope
// ---------------------------------------------------------------------------

interface _PurpleIPCRequest {
  id:      string;
  command: string;
  [key: string]: unknown;
}

interface _PurpleIPCResponse {
  id:      string;
  status:  "ok" | "error" | "purple";
  message?: string;
  [key: string]: unknown;
}

type _PendingRequest = {
  resolve: (value: _PurpleIPCResponse) => void;
  reject:  (reason: Error) => void;
  timer:   ReturnType<typeof setTimeout>;
  onStream?: PurpleStreamCallback;
};

// ---------------------------------------------------------------------------
// Process state
// ---------------------------------------------------------------------------

let child: Awaited<ReturnType<typeof Command.prototype.spawn>> | null = null;
let connected = false;
let buffer    = "";

const pending = new Map<string, _PendingRequest>();

let _appQuitUnlisten: (() => void) | null = null;

// ---------------------------------------------------------------------------
// stdout line handler
// ---------------------------------------------------------------------------

function _handleStdout(data: string): void {
  buffer += data;
  const lines = buffer.split("\n");
  buffer = lines.pop() ?? "";

  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed) continue;

    let parsed: _PurpleIPCResponse;
    try {
      parsed = JSON.parse(trimmed) as _PurpleIPCResponse;
    } catch {
      // Non-JSON debug output from Python
      continue;
    }

    const req = pending.get(parsed.id);
    if (!req) continue;

    if (parsed.status === "purple") {
      // Streaming event — call callback, don't resolve
      req.onStream?.(parsed as unknown as PurpleStreamEvent);
    } else {
      // Final response (ok / error) — resolve
      clearTimeout(req.timer);
      pending.delete(parsed.id);
      req.resolve(parsed);
    }
  }
}

function _handleStderr(data: string): void {
  console.warn("[purple stderr]", data);
}

// ---------------------------------------------------------------------------
// Lifecycle
// ---------------------------------------------------------------------------

/**
 * Démarre le processus olith_purple.py.
 * No-op si déjà connecté.
 */
export async function start(): Promise<void> {
  if (connected) return;

  const cmd = Command.create("python-purple", ["../py-backend/olith_purple.py"]);

  cmd.stdout.on("data", _handleStdout);
  cmd.stderr.on("data", _handleStderr);

  cmd.on("close", () => {
    connected = false;
    child     = null;
    buffer    = "";
    // Reject all pending requests
    for (const [id, req] of pending) {
      clearTimeout(req.timer);
      req.reject(new Error("Purple Team process closed"));
      pending.delete(id);
    }
  });

  child     = await cmd.spawn();
  connected = true;
  buffer    = "";

  // Listen for app-quit to stop gracefully
  if (!_appQuitUnlisten) {
    _appQuitUnlisten = await listen("app-quit", () => {
      stop().catch(() => {});
    });
  }
}

/**
 * Arrête le processus olith_purple.py.
 */
export async function stop(): Promise<void> {
  if (child) {
    try { await child.kill(); } catch { /* ignore */ }
    child     = null;
    connected = false;
    buffer    = "";
  }
}

export function isConnected(): boolean {
  return connected;
}

// ---------------------------------------------------------------------------
// Low-level send
// ---------------------------------------------------------------------------

async function _send<T>(
  command: string,
  params:  Record<string, unknown>,
  timeoutMs: number,
  onStream?: PurpleStreamCallback,
): Promise<T> {
  if (!connected) await start();

  const id = crypto.randomUUID();
  const request: _PurpleIPCRequest = { id, command, ...params };

  return new Promise<T>((resolve, reject) => {
    const timer = setTimeout(() => {
      pending.delete(id);
      reject(new Error(`Purple timeout after ${timeoutMs}ms for command: ${command}`));
    }, timeoutMs);

    pending.set(id, {
      resolve: (r) => resolve(r as unknown as T),
      reject,
      timer,
      onStream,
    });

    const payload = JSON.stringify(request) + "\n";
    child!.write(payload).catch((err: Error) => {
      clearTimeout(timer);
      pending.delete(id);
      reject(err);
    });
  });
}

// ---------------------------------------------------------------------------
// Public API — one function per command
// ---------------------------------------------------------------------------

/**
 * Génère un scénario déterministe depuis seed + difficulty.
 * Rapide (~10ms) — pas de LLM.
 */
export async function generateScenario(
  params: PurpleGenerateScenarioRequest,
): Promise<PurpleGenerateScenarioResponse> {
  return _send<PurpleGenerateScenarioResponse>(
    "purple_generate_scenario",
    params as unknown as Record<string, unknown>,
    10_000,
  );
}

/**
 * Lance un match Purple Team.
 * Retourne immédiatement avec le match_id.
 * Les événements de round sont streamés via onStream (status="purple").
 * La promesse se résout sur le dernier "ok" de fin de match.
 *
 * Timeout: 65 min (match max 60 min + 5 min de marge).
 */
export async function startMatch(
  params:   PurpleStartMatchRequest,
  onStream: PurpleStreamCallback,
): Promise<PurpleStartMatchResponse> {
  if (!connected) await start();

  return _send<PurpleStartMatchResponse>(
    "purple_start_match",
    params as unknown as Record<string, unknown>,
    65 * 60 * 1000,
    onStream,
  );
}

/**
 * Retourne le statut du match en cours (polling).
 */
export async function getMatchStatus(): Promise<PurpleMatchStatusResponse> {
  return _send<PurpleMatchStatusResponse>(
    "purple_match_status",
    {},
    5_000,
  );
}

/**
 * Retourne le résultat complet du dernier match terminé.
 */
export async function getMatchResult(): Promise<PurpleMatchResultResponse> {
  return _send<PurpleMatchResultResponse>(
    "purple_match_result",
    {},
    5_000,
  );
}

/**
 * Envoie le signal d'annulation au match en cours.
 * Le match s'arrête proprement après le round courant.
 */
export async function stopMatch(): Promise<PurpleStopMatchResponse> {
  if (!connected) {
    return { stopped: false, message: "Purple process not running" };
  }
  return _send<PurpleStopMatchResponse>(
    "purple_stop_match",
    {},
    5_000,
  );
}
