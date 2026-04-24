<script lang="ts">
    import { tick } from "svelte";
    import * as arena from "../stores/arena.svelte";
    import type { ArenaMove } from "../../types/ipc";

    let redPanel  = $state<HTMLElement | null>(null);
    let bluePanel = $state<HTMLElement | null>(null);

    let phase     = $derived(arena.getPhase());
    let redMoves  = $derived(arena.getRedMoves());
    let blueMoves = $derived(arena.getBlueMoves());

    $effect(() => {
        const _ = redMoves.length;
        tick().then(() => {
            if (redPanel) redPanel.scrollTop = redPanel.scrollHeight;
        });
    });
    $effect(() => {
        const _ = blueMoves.length;
        tick().then(() => {
            if (bluePanel) bluePanel.scrollTop = bluePanel.scrollHeight;
        });
    });

    let generatingRed  = $derived(phase === "running" && redMoves.length === blueMoves.length);
    let generatingBlue = $derived(phase === "running" && redMoves.length > blueMoves.length);

    let expandedMoves = $state(new Set<string>());

    function moveKey(move: ArenaMove): string {
        return move.timestamp + move.type + move.team;
    }

    function toggleExpand(key: string) {
        const next = new Set(expandedMoves);
        if (next.has(key)) { next.delete(key); } else { next.add(key); }
        expandedMoves = next;
    }

    function formatDuration(s: number | undefined): string {
        if (!s || s < 0.1) return "";
        return s >= 60 ? `${Math.floor(s / 60)}m${Math.round(s % 60)}s` : `${s.toFixed(1)}s`;
    }

    function durationClass(s: number | undefined): string {
        if (!s || s < 0.1) return "";
        if (s < 5)  return "dur-fast";
        if (s < 30) return "dur-mid";
        return "dur-slow";
    }

    const TYPE_SYMBOLS: Record<string, string> = {
        RECON:   "◉", EXPLOIT: "⚔", SUCCESS: "✦", PIVOT: "⚔", DATA: "⚔",
        MONITOR: "◈", ALERT:   "▲", BLOCK:   "■", PATCH: "✦", ISOLATE: "■",
    };

    function typeSymbol(t: string): string {
        return TYPE_SYMBOLS[t] ?? "·";
    }
</script>

<div class="panels">
    <!-- Red panel -->
    <div class="panel panel-red">
        <div class="panel-header">
            <span class="team-dot red-dot"></span>
            <span class="team-name red-name">Pyrolith — Red Team</span>
        </div>
        <div class="panel-moves" bind:this={redPanel}>
            {#each redMoves as move (move.timestamp + move.type)}
                {@render MoveRow({ move })}
            {/each}
            {#if generatingRed}
                <div class="generating generating-red">Pyrolith génère son attaque<span class="dots-anim">...</span></div>
            {:else if phase === "running" && redMoves.length === 0}
                <div class="waiting">Attente du premier mouvement…</div>
            {/if}
        </div>
    </div>

    <!-- VS divider -->
    <div class="vs-divider">
        <div class="vs-line"></div>
        <div class="vs-pill">VS</div>
        <div class="vs-line"></div>
    </div>

    <!-- Blue panel -->
    <div class="panel panel-blue">
        <div class="panel-header">
            <span class="team-dot blue-dot"></span>
            <span class="team-name blue-name">Cryolith — Blue Team</span>
        </div>
        <div class="panel-moves" bind:this={bluePanel}>
            {#each blueMoves as move (move.timestamp + move.type)}
                {@render MoveRow({ move })}
            {/each}
            {#if generatingBlue}
                <div class="generating generating-blue">Cryolith génère sa réponse<span class="dots-anim">...</span></div>
            {:else if phase === "running" && blueMoves.length === 0}
                <div class="waiting">En attente de réponse défensive…</div>
            {/if}
        </div>
    </div>
</div>

{#snippet MoveRow({ move }: { move: ArenaMove })}
    {@const key = moveKey(move)}
    {@const expanded = expandedMoves.has(key)}
    {@const hasDetails = !!(move.details && move.details.trim())}
    {@const sym = typeSymbol(move.type)}
    {@const durClass = durationClass(move.duration_s)}
    <div class="move-row" class:move-expanded={expanded}>
        <span class="move-time">{move.timestamp}</span>
        {#if move.round}
            <span class="move-round">R{move.round}</span>
        {/if}
        <span class="move-badge" style="background: {move.badge_color}">
            <span class="badge-sym">{sym}</span>{move.type}
        </span>
        {#if move.duration_s && move.duration_s >= 0.1}
            <span class="move-duration {durClass}">{formatDuration(move.duration_s)}</span>
        {/if}
        <span class="move-msg">{move.message}</span>
        {#if hasDetails}
            <button
                class="expand-btn"
                class:expand-open={expanded}
                onclick={() => toggleExpand(key)}
                title={expanded ? "Réduire" : "Détails"}
            >›</button>
        {/if}
    </div>
    {#if expanded && hasDetails}
        <div class="move-details">{move.details}</div>
    {/if}
{/snippet}

<style>
    .panels {
        display: flex;
        flex: 1;
        min-height: 0;
        overflow: hidden;
    }
    .panel {
        flex: 1;
        display: flex;
        flex-direction: column;
        min-width: 0;
        overflow: hidden;
    }
    .panel-red  { background: rgba(239,68,68,0.025); }
    .panel-blue { background: rgba(14,165,233,0.025); }

    .panel-header {
        display: flex; align-items: center; gap: 8px;
        padding: 8px 14px 7px;
        border-bottom: 1px solid var(--border);
        flex-shrink: 0;
    }
    .team-dot { width: 7px; height: 7px; border-radius: 50%; flex-shrink: 0; }
    .red-dot  { background: #ef4444; }
    .blue-dot { background: #0ea5e9; }
    .team-name { font-size: 11px; font-weight: 600; letter-spacing: 0.05em; text-transform: uppercase; }
    .red-name  { color: #ef4444; }
    .blue-name { color: #0ea5e9; }

    .panel-moves { flex: 1; overflow-y: auto; padding: 4px 0; }
    .panel-moves::-webkit-scrollbar { width: 4px; }
    .panel-moves::-webkit-scrollbar-track { background: transparent; }
    .panel-moves::-webkit-scrollbar-thumb { background: var(--border); border-radius: 2px; }

    .vs-divider {
        display: flex; flex-direction: column; align-items: center;
        width: 32px; flex-shrink: 0;
        border-left: 1px solid var(--border);
        border-right: 1px solid var(--border);
        background: var(--bg-secondary);
    }
    .vs-line { flex: 1; width: 1px; background: var(--border); }
    .vs-pill {
        padding: 6px 0;
        font-size: 9px; font-weight: 800; letter-spacing: 0.1em;
        color: var(--text-muted);
        writing-mode: vertical-rl; text-orientation: mixed;
        transform: rotate(180deg);
    }

    .move-row {
        display: flex; align-items: baseline; gap: 6px;
        padding: 5px 12px;
        border-bottom: 1px solid rgba(255,255,255,0.03);
        cursor: default;
    }
    .move-expanded { background: rgba(255,255,255,0.02); }
    .move-time {
        font-size: 10px; color: var(--text-muted);
        font-variant-numeric: tabular-nums;
        min-width: 52px; flex-shrink: 0;
    }
    .move-round {
        font-size: 9px; color: var(--text-muted);
        font-weight: 600; opacity: 0.55;
        flex-shrink: 0; min-width: 16px;
    }
    .move-badge {
        display: inline-flex; align-items: center; gap: 3px;
        padding: 2px 6px; border-radius: 6px;
        font-size: 9px; font-weight: 700; letter-spacing: 0.06em;
        color: #fff; flex-shrink: 0; text-transform: uppercase;
    }
    .badge-sym { font-size: 8px; opacity: 0.9; }
    .move-duration { font-size: 9px; font-variant-numeric: tabular-nums; flex-shrink: 0; }
    .dur-fast { color: #22c55e; }
    .dur-mid  { color: #f97316; }
    .dur-slow { color: #ef4444; }
    .move-msg {
        font-size: 12px; color: var(--text-secondary);
        line-height: 1.4; flex: 1; min-width: 0; word-break: break-word;
    }
    .expand-btn {
        flex-shrink: 0; width: 18px; height: 18px;
        border: 1px solid rgba(255,255,255,0.08);
        background: rgba(255,255,255,0.04);
        color: var(--text-muted); cursor: pointer;
        font-size: 13px; line-height: 1; padding: 0;
        display: flex; align-items: center; justify-content: center;
        border-radius: 4px;
        transition: transform 0.15s, color 0.15s, background 0.15s;
    }
    .expand-btn:hover {
        color: var(--text-secondary);
        background: rgba(255,255,255,0.09);
        border-color: rgba(255,255,255,0.16);
    }
    .expand-btn.expand-open { transform: rotate(90deg); color: var(--text-secondary); }
    .move-details {
        padding: 5px 12px 8px 96px;
        font-size: 11px; color: var(--text-muted);
        line-height: 1.5; word-break: break-word;
        font-family: monospace;
        background: rgba(0,0,0,0.15);
        border-bottom: 1px solid rgba(255,255,255,0.03);
    }

    .waiting { padding: 16px 12px; font-size: 12px; color: var(--text-muted); font-style: italic; }
    .generating { padding: 10px 12px; font-size: 11px; font-style: italic; }
    .generating-red  { color: rgba(239,68,68,0.7); }
    .generating-blue { color: rgba(14,165,233,0.7); }

    @keyframes dots {
        0%   { opacity: 0.2; }
        33%  { opacity: 1;   }
        66%  { opacity: 0.5; }
        100% { opacity: 0.2; }
    }
    .dots-anim { display: inline-block; animation: dots 1.2s steps(1, end) infinite; }
</style>
