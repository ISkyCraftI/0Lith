/**
 * arena.svelte.ts — Arena sparring state store (Svelte 5 runes)
 *
 * Manages the Pyrolith vs Cryolith sparring session:
 * - Sends the "arena" IPC command with onStream callback
 * - Accumulates arena_move events into reactive state
 * - Tracks score, phase, round progress, and post-match review
 * - Persists the last session result to localStorage
 */

import * as backend from "./pythonBackend.svelte";
import type { ArenaMove, ArenaEvent, ArenaResponse, IPCResponse, IPCRequest } from "../../types/ipc";

export type ArenaPhase = "idle" | "running" | "review" | "done";

export interface ArenaResult {
    red: number;
    blue: number;
    duration_s: number;
    winner: "red" | "blue" | "draw";
    scenario: string;
    timestamp: string;
}

// ── Reactive state ──────────────────────────────────────────────────────────

let moves     = $state<ArenaMove[]>([]);
let scoreRed  = $state(0);
let scoreBlue = $state(0);
let phase     = $state<ArenaPhase>("idle");
let review    = $state<{ red: string; blue: string } | null>(null);
let scenario  = $state("");
let error     = $state<string | null>(null);
let roundNum  = $state(0);
let lastResult = $state<ArenaResult | null>(null);

// Restore last result from localStorage on module load
try {
    const stored = localStorage.getItem("arena_last_result");
    if (stored) lastResult = JSON.parse(stored) as ArenaResult;
} catch { /* ignore parse errors */ }

// ── Accessors ───────────────────────────────────────────────────────────────

export function getMoves(): ArenaMove[]   { return moves; }
export function getScore()                { return { red: scoreRed, blue: scoreBlue }; }
export function getPhase()                { return phase; }
export function getReview()               { return review; }
export function getScenario()             { return scenario; }
export function getError()                { return error; }
export function getRoundNum(): number     { return roundNum; }
export function getRoundTotal(): number   { return 5; }
export function getLastResult(): ArenaResult | null { return lastResult; }

export function getRedMoves()  { return moves.filter((m) => m.team === "red"); }
export function getBlueMoves() { return moves.filter((m) => m.team === "blue"); }

export function getCombatLog(): string {
    if (moves.length === 0) return "";
    return moves
        .map((m) => {
            const team = m.team === "red" ? "RED " : "BLUE";
            const dur  = m.duration_s && m.duration_s >= 0.1 ? ` [${m.duration_s.toFixed(1)}s]` : "";
            const rnd  = m.round ? ` R${m.round}` : "";
            return `${m.timestamp}${rnd}  ${team}  [${m.type.padEnd(7)}]  ${m.message}${dur}`;
        })
        .join("\n");
}

// ── Actions ─────────────────────────────────────────────────────────────────

export async function startArena(scenarioStr: string = "SQL Injection") {
    moves     = [];
    scoreRed  = 0;
    scoreBlue = 0;
    review    = null;
    error     = null;
    phase     = "running";
    scenario  = scenarioStr;
    roundNum  = 0;

    const sessionStart = Date.now();

    const onStream = (data: IPCResponse) => {
        if (data.status !== "arena") return;
        const evt = data as ArenaEvent;

        if (evt.phase === "review_start") {
            phase = "review";
            if (evt.score) { scoreRed = evt.score.red; scoreBlue = evt.score.blue; }
            return;
        }

        if (evt.phase === "complete") {
            phase = "done";
            if (evt.score)  { scoreRed = evt.score.red; scoreBlue = evt.score.blue; }
            if (evt.review) { review = evt.review; }

            // Persist last result to localStorage
            const finalRed  = evt.score?.red  ?? scoreRed;
            const finalBlue = evt.score?.blue ?? scoreBlue;
            const result: ArenaResult = {
                red: finalRed,
                blue: finalBlue,
                duration_s: Math.round((Date.now() - sessionStart) / 1000),
                winner: finalRed > finalBlue ? "red" : finalBlue > finalRed ? "blue" : "draw",
                scenario: scenarioStr,
                timestamp: new Date().toISOString(),
            };
            lastResult = result;
            try { localStorage.setItem("arena_last_result", JSON.stringify(result)); } catch { /* ignore */ }
            return;
        }

        if (evt.move) {
            moves = [...moves, evt.move];
            if (evt.score) { scoreRed = evt.score.red; scoreBlue = evt.score.blue; }
            if (evt.move.round) roundNum = evt.move.round;
        }
    };

    try {
        const res = (await backend.send(
            { id: crypto.randomUUID(), command: "arena", scenario: scenarioStr },
            1_800_000, // 30 min — covers typical slow-model runs (~25 min measured)
            onStream,
        )) as ArenaResponse;

        // Final resolution (status: "ok") — update with authoritative values
        phase     = "done";
        scoreRed  = res.score_red  ?? scoreRed;
        scoreBlue = res.score_blue ?? scoreBlue;
        if (res.review) review = res.review;
    } catch (e: unknown) {
        const msg = e instanceof Error ? e.message : String(e);
        error = msg;
        phase = "idle";
    }
}

export async function stop(): Promise<void> {
    try {
        await backend.send(
            { id: crypto.randomUUID(), command: "cancel" } as IPCRequest,
            5000,
        );
    } catch {
        // cancel is best-effort — arena loop will stop at next round boundary
    }
}

export function reset() {
    moves     = [];
    scoreRed  = 0;
    scoreBlue = 0;
    phase     = "idle";
    review    = null;
    error     = null;
    scenario  = "";
    roundNum  = 0;
}
