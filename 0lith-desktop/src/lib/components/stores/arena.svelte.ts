/**
 * arena.svelte.ts — Arena sparring state store (Svelte 5 runes)
 *
 * Manages the Pyrolith vs Cryolith sparring session:
 * - Sends the "arena" IPC command with onStream callback
 * - Accumulates arena_move events into reactive state
 * - Tracks score, phase, and post-match review
 */

import * as backend from "./pythonBackend.svelte";
import type { ArenaMove, ArenaEvent, ArenaResponse, IPCResponse, IPCRequest } from "../../types/ipc";

export type ArenaPhase = "idle" | "running" | "review" | "done";

// ── Reactive state ──────────────────────────────────────────────────────────

let moves    = $state<ArenaMove[]>([]);
let scoreRed = $state(0);
let scoreBlue = $state(0);
let phase    = $state<ArenaPhase>("idle");
let review   = $state<{ red: string; blue: string } | null>(null);
let scenario = $state("");
let error    = $state<string | null>(null);

// ── Accessors ───────────────────────────────────────────────────────────────

export function getMoves(): ArenaMove[] { return moves; }
export function getScore()    { return { red: scoreRed, blue: scoreBlue }; }
export function getPhase()    { return phase; }
export function getReview()   { return review; }
export function getScenario() { return scenario; }
export function getError()    { return error; }

export function getRedMoves()  { return moves.filter((m) => m.team === "red"); }
export function getBlueMoves() { return moves.filter((m) => m.team === "blue"); }

export function getCombatLog(): string {
    if (moves.length === 0) return "";
    return moves
        .map((m) => {
            const team = m.team === "red" ? "RED " : "BLUE";
            const dur  = m.duration_s && m.duration_s >= 0.1 ? ` [${m.duration_s.toFixed(1)}s]` : "";
            return `${m.timestamp}  ${team}  [${m.type.padEnd(7)}]  ${m.message}${dur}`;
        })
        .join("\n");
}

// ── Actions ─────────────────────────────────────────────────────────────────

export async function startArena(scenarioStr: string = "SQL Injection") {
    moves    = [];
    scoreRed = 0;
    scoreBlue = 0;
    review   = null;
    error    = null;
    phase    = "running";
    scenario = scenarioStr;

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
            return;
        }

        if (evt.move) {
            moves = [...moves, evt.move];
            if (evt.score) { scoreRed = evt.score.red; scoreBlue = evt.score.blue; }
        }
    };

    try {
        const res = (await backend.send(
            { id: crypto.randomUUID(), command: "arena", scenario: scenarioStr },
            600_000, // 10 min max for full sparring session
            onStream,
        )) as ArenaResponse;

        // Final resolution (status: "ok") — update with authoritative values
        phase    = "done";
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
    moves    = [];
    scoreRed = 0;
    scoreBlue = 0;
    phase    = "idle";
    review   = null;
    error    = null;
    scenario = "";
}
