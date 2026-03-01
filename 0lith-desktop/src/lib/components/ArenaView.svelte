<script lang="ts">
    import { tick } from "svelte";
    import * as arena from "./stores/arena.svelte";
    import type { ArenaMove } from "../types/ipc";

    let redPanel = $state<HTMLElement | null>(null);
    let bluePanel = $state<HTMLElement | null>(null);

    let phase     = $derived(arena.getPhase());
    let score     = $derived(arena.getScore());
    let review    = $derived(arena.getReview());
    let redMoves  = $derived(arena.getRedMoves());
    let blueMoves = $derived(arena.getBlueMoves());
    let errMsg    = $derived(arena.getError());

    // Auto-scroll panels when new moves arrive
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

    async function handleStart() {
        await arena.startArena("SQL Injection");
    }

    async function handleStop() {
        await arena.stop();
    }

    function handleReset() {
        arena.reset();
        expandedMoves.clear();
    }

    // ── Expand state ────────────────────────────────────────────────────────
    let expandedMoves = $state(new Set<string>());

    function toggleExpand(key: string) {
        const next = new Set(expandedMoves);
        if (next.has(key)) { next.delete(key); } else { next.add(key); }
        expandedMoves = next;
    }

    function moveKey(move: ArenaMove): string {
        return move.timestamp + move.type + move.team;
    }

    function formatDuration(s: number | undefined): string {
        if (!s || s < 0.1) return "";
        return s >= 60 ? `${Math.floor(s / 60)}m${Math.round(s % 60)}s` : `${s.toFixed(1)}s`;
    }

    // ── Chronometer ──────────────────────────────────────────────────────────
    let elapsed = $state(0);
    let chronoInterval: ReturnType<typeof setInterval> | null = null;

    $effect(() => {
        if (phase === "running") {
            elapsed = 0;
            chronoInterval = setInterval(() => { elapsed += 1; }, 1000);
        } else {
            if (chronoInterval) { clearInterval(chronoInterval); chronoInterval = null; }
        }
        return () => { if (chronoInterval) clearInterval(chronoInterval); };
    });

    function formatTime(secs: number): string {
        const m = Math.floor(secs / 60).toString().padStart(2, "0");
        const s = (secs % 60).toString().padStart(2, "0");
        return `${m}:${s}`;
    }

    // Phase label helper
    function phaseLabel(): string {
        switch (phase) {
            case "running": return "En cours";
            case "review":  return "Revue";
            case "done":    return "Terminé";
            default:        return "";
        }
    }

    // ── Combat log ───────────────────────────────────────────────────────────
    let logOpen    = $state(false);
    let combatLog  = $derived(arena.getCombatLog());
    let allMoves   = $derived(arena.getMoves());
</script>

<!-- ─── IDLE STATE ──────────────────────────────────────────────────────── -->
{#if phase === "idle"}
<div class="arena-view arena-idle">
    <div class="arena-content">
        <div class="arena-icon" aria-hidden="true">
            <svg width="64" height="64" viewBox="0 0 64 64" fill="none" xmlns="http://www.w3.org/2000/svg">
                <!-- Pyrolith: flame -->
                <path
                    d="M20 48 C20 36 28 30 24 18 C30 26 34 20 32 10 C40 20 44 30 36 42 C40 38 42 32 40 26 C46 34 46 42 40 48 Z"
                    fill="#EF4444" opacity="0.85"
                />
                <!-- Cryolith: snowflake -->
                <line x1="44" y1="16" x2="44" y2="48" stroke="#0EA5E9" stroke-width="2.5" stroke-linecap="round" />
                <line x1="28" y1="32" x2="60" y2="32" stroke="#0EA5E9" stroke-width="2.5" stroke-linecap="round" />
                <line x1="33" y1="21" x2="55" y2="43" stroke="#0EA5E9" stroke-width="2.5" stroke-linecap="round" />
                <line x1="55" y1="21" x2="33" y2="43" stroke="#0EA5E9" stroke-width="2.5" stroke-linecap="round" />
            </svg>
        </div>
        <h2 class="arena-title">Arena</h2>
        <p class="arena-desc">Pyrolith (Red Team) vs Cryolith (Blue Team)</p>
        <p class="arena-sub">
            5 rounds d'injection SQL — chaque agent joue son rôle en temps réel,<br/>
            accumule des points, et analyse ses faiblesses à la fin.
        </p>
        <p class="arena-order">Ordre : Pyrolith attaque → Cryolith répond (×5 rounds)</p>

        {#if errMsg}
            <div class="arena-error">{errMsg}</div>
        {/if}

        <button class="start-btn" onclick={handleStart}>
            <svg width="14" height="14" viewBox="0 0 14 14" fill="currentColor" aria-hidden="true">
                <polygon points="3,1 13,7 3,13"/>
            </svg>
            Lancer l'injection SQL
        </button>
    </div>
</div>

<!-- ─── ACTIVE / REVIEW / DONE ─────────────────────────────────────────── -->
{:else}
<div class="arena-view arena-active">

    <!-- Header bar -->
    <div class="arena-header">
        <div class="header-left">
            <span class="scenario-label">SQL Injection</span>
            {#if phase !== "done"}
                <span class="phase-pill">{phaseLabel()}</span>
                <span class="chrono">{formatTime(elapsed)}</span>
            {/if}
        </div>
        <div class="header-score">
            <span class="score-red">Red {score.red}</span>
            <span class="score-sep">·</span>
            <span class="score-blue">Blue {score.blue}</span>
        </div>
        <div class="header-right">
            {#if phase === "done"}
                <button class="reset-btn" onclick={handleReset}>Réinitialiser</button>
            {:else}
                <button class="stop-btn" onclick={handleStop}>■ Arrêter</button>
            {/if}
        </div>
    </div>

    <!-- Team panels -->
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
                {#if phase === "running" && redMoves.length === 0}
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
                {#if phase === "running" && blueMoves.length === 0}
                    <div class="waiting">En attente de réponse défensive…</div>
                {/if}
            </div>
        </div>
    </div>

    <!-- Combat log (collapsible) -->
    {#if allMoves.length > 0}
        <div class="log-section">
            <button class="log-toggle" onclick={() => (logOpen = !logOpen)}>
                <span class="log-chevron" class:log-open={logOpen}>›</span>
                Log de combat
                <span class="log-count">{allMoves.length} mouvements</span>
            </button>
            {#if logOpen}
                <pre class="log-content">{combatLog}</pre>
            {/if}
        </div>
    {/if}

    <!-- Review section (post-match) -->
    {#if phase === "done" && review}
        <div class="review-section">
            <div class="review-header">Analyse post-combat</div>
            <div class="review-cards">
                <div class="review-card review-card-red">
                    <div class="review-card-label red-name">Pyrolith — Faiblesses</div>
                    <p class="review-text">{review.red}</p>
                </div>
                <div class="review-card review-card-blue">
                    <div class="review-card-label blue-name">Cryolith — Lacunes défensives</div>
                    <p class="review-text">{review.blue}</p>
                </div>
            </div>
        </div>
    {/if}
</div>
{/if}

<!-- ─── Move Row Component ──────────────────────────────────────────────── -->
{#snippet MoveRow({ move }: { move: ArenaMove })}
    {@const key = moveKey(move)}
    {@const expanded = expandedMoves.has(key)}
    {@const hasDetails = !!(move.details && move.details.trim())}
    <div class="move-row" class:move-expanded={expanded}>
        <span class="move-time">{move.timestamp}</span>
        <span class="move-badge" style="background: {move.badge_color}">{move.type}</span>
        {#if move.duration_s && move.duration_s >= 0.1}
            <span class="move-duration">{formatDuration(move.duration_s)}</span>
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
    /* ── Layout ──────────────────────────────────────────────────────────── */
    .arena-view {
        flex: 1;
        display: flex;
        flex-direction: column;
        background: var(--bg-primary);
        overflow: hidden;
        min-height: 0;
    }

    /* ── Idle ────────────────────────────────────────────────────────────── */
    .arena-idle {
        align-items: center;
        justify-content: center;
    }
    .arena-content {
        display: flex;
        flex-direction: column;
        align-items: center;
        gap: 14px;
        max-width: 420px;
        text-align: center;
        padding: 40px 24px;
    }
    .arena-icon { opacity: 0.75; margin-bottom: 4px; }
    .arena-title {
        font-size: 22px;
        font-weight: 700;
        color: var(--text-primary);
        margin: 0;
        letter-spacing: 0.02em;
    }
    .arena-desc {
        font-size: 14px;
        color: var(--text-secondary);
        margin: 0;
    }
    .arena-sub {
        font-size: 12px;
        color: var(--text-muted);
        margin: 0;
        line-height: 1.7;
    }
    .arena-order {
        font-size: 11px;
        color: var(--text-muted);
        margin: 0;
        opacity: 0.7;
    }
    .arena-error {
        background: rgba(239,68,68,0.1);
        border: 1px solid rgba(239,68,68,0.3);
        border-radius: 6px;
        padding: 8px 14px;
        font-size: 12px;
        color: #ef4444;
        max-width: 100%;
        word-break: break-word;
    }
    .start-btn {
        display: inline-flex;
        align-items: center;
        gap: 8px;
        margin-top: 8px;
        padding: 9px 22px;
        background: #dc2626;
        color: #fff;
        border: none;
        border-radius: 6px;
        font-size: 13px;
        font-weight: 600;
        cursor: pointer;
        letter-spacing: 0.02em;
        transition: background 0.15s;
    }
    .start-btn:hover { background: #b91c1c; }
    .start-btn:active { background: #991b1b; }

    /* ── Header bar ──────────────────────────────────────────────────────── */
    .arena-header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 8px 16px;
        border-bottom: 1px solid var(--border);
        background: var(--bg-secondary);
        flex-shrink: 0;
        gap: 12px;
    }
    .header-left {
        display: flex;
        align-items: center;
        gap: 10px;
        flex: 1;
    }
    .scenario-label {
        font-size: 12px;
        font-weight: 600;
        color: var(--text-secondary);
        letter-spacing: 0.04em;
        text-transform: uppercase;
    }
    .phase-pill {
        padding: 2px 8px;
        background: rgba(234,88,12,0.15);
        border: 1px solid rgba(234,88,12,0.3);
        border-radius: 10px;
        font-size: 11px;
        color: #ea580c;
        font-weight: 500;
    }
    .chrono {
        font-size: 11px;
        font-weight: 600;
        font-variant-numeric: tabular-nums;
        color: var(--text-muted);
        letter-spacing: 0.04em;
    }
    .header-score {
        display: flex;
        align-items: center;
        gap: 8px;
        font-size: 13px;
        font-weight: 700;
        font-variant-numeric: tabular-nums;
        flex-shrink: 0;
    }
    .score-red  { color: #ef4444; }
    .score-blue { color: #0ea5e9; }
    .score-sep  { color: var(--text-muted); font-weight: 400; }
    .header-right { flex: 1; display: flex; justify-content: flex-end; }
    .reset-btn {
        padding: 5px 14px;
        background: transparent;
        border: 1px solid var(--border);
        border-radius: 5px;
        font-size: 12px;
        color: var(--text-muted);
        cursor: pointer;
        transition: border-color 0.15s, color 0.15s;
    }
    .reset-btn:hover { border-color: var(--text-secondary); color: var(--text-secondary); }
    .stop-btn {
        padding: 5px 14px;
        background: transparent;
        border: 1px solid rgba(239,68,68,0.4);
        border-radius: 5px;
        font-size: 12px;
        color: #ef4444;
        cursor: pointer;
        transition: border-color 0.15s, background 0.15s;
    }
    .stop-btn:hover { border-color: #ef4444; background: rgba(239,68,68,0.08); }

    /* ── Panels ──────────────────────────────────────────────────────────── */
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
    .panel-red  { background: rgba(239,68,68,0.03); }
    .panel-blue { background: rgba(14,165,233,0.03); }

    .panel-header {
        display: flex;
        align-items: center;
        gap: 8px;
        padding: 8px 16px 7px;
        border-bottom: 1px solid var(--border);
        flex-shrink: 0;
    }
    .team-dot {
        width: 7px;
        height: 7px;
        border-radius: 50%;
        flex-shrink: 0;
    }
    .red-dot  { background: #ef4444; }
    .blue-dot { background: #0ea5e9; }
    .team-name {
        font-size: 11px;
        font-weight: 600;
        letter-spacing: 0.05em;
        text-transform: uppercase;
    }
    .red-name  { color: #ef4444; }
    .blue-name { color: #0ea5e9; }

    .panel-moves {
        flex: 1;
        overflow-y: auto;
        padding: 4px 0;
    }
    .panel-moves::-webkit-scrollbar { width: 4px; }
    .panel-moves::-webkit-scrollbar-track { background: transparent; }
    .panel-moves::-webkit-scrollbar-thumb { background: var(--border); border-radius: 2px; }

    /* ── VS divider ──────────────────────────────────────────────────────── */
    .vs-divider {
        display: flex;
        flex-direction: column;
        align-items: center;
        width: 32px;
        flex-shrink: 0;
        border-left: 1px solid var(--border);
        border-right: 1px solid var(--border);
        background: var(--bg-secondary);
    }
    .vs-line {
        flex: 1;
        width: 1px;
        background: var(--border);
    }
    .vs-pill {
        padding: 6px 0;
        font-size: 9px;
        font-weight: 800;
        letter-spacing: 0.1em;
        color: var(--text-muted);
        writing-mode: vertical-rl;
        text-orientation: mixed;
        transform: rotate(180deg);
    }

    /* ── Move row ────────────────────────────────────────────────────────── */
    .move-row {
        display: flex;
        align-items: baseline;
        gap: 8px;
        padding: 5px 14px;
        border-bottom: 1px solid rgba(255,255,255,0.03);
        cursor: default;
    }
    .move-expanded {
        background: rgba(255,255,255,0.02);
    }
    .move-time {
        font-size: 10px;
        color: var(--text-muted);
        font-variant-numeric: tabular-nums;
        min-width: 52px;
        flex-shrink: 0;
    }
    .move-badge {
        padding: 2px 7px;
        border-radius: 3px;
        font-size: 9px;
        font-weight: 700;
        letter-spacing: 0.08em;
        color: #fff;
        flex-shrink: 0;
        text-transform: uppercase;
    }
    .move-duration {
        font-size: 9px;
        color: var(--text-muted);
        font-variant-numeric: tabular-nums;
        flex-shrink: 0;
        opacity: 0.7;
    }
    .move-msg {
        font-size: 12px;
        color: var(--text-secondary);
        line-height: 1.4;
        flex: 1;
        min-width: 0;
        word-break: break-word;
    }
    .expand-btn {
        flex-shrink: 0;
        width: 16px;
        height: 16px;
        border: none;
        background: transparent;
        color: var(--text-muted);
        cursor: pointer;
        font-size: 14px;
        line-height: 1;
        padding: 0;
        display: flex;
        align-items: center;
        justify-content: center;
        border-radius: 3px;
        transition: transform 0.15s, color 0.15s;
    }
    .expand-btn:hover { color: var(--text-secondary); }
    .expand-btn.expand-open { transform: rotate(90deg); color: var(--text-secondary); }
    .move-details {
        padding: 5px 14px 8px 88px;
        font-size: 11px;
        color: var(--text-muted);
        line-height: 1.5;
        word-break: break-word;
        font-family: monospace;
        background: rgba(0,0,0,0.15);
        border-bottom: 1px solid rgba(255,255,255,0.03);
    }

    .waiting {
        padding: 16px 14px;
        font-size: 12px;
        color: var(--text-muted);
        font-style: italic;
    }

    /* ── Review section ──────────────────────────────────────────────────── */
    .review-section {
        border-top: 1px solid var(--border);
        background: var(--bg-secondary);
        padding: 14px 16px;
        flex-shrink: 0;
        max-height: 200px;
        overflow-y: auto;
    }
    .review-header {
        font-size: 11px;
        font-weight: 600;
        color: var(--text-muted);
        text-transform: uppercase;
        letter-spacing: 0.05em;
        margin-bottom: 10px;
    }
    .review-cards {
        display: flex;
        gap: 12px;
    }
    .review-card {
        flex: 1;
        padding: 10px 14px;
        border-radius: 6px;
        border: 1px solid var(--border);
        background: var(--bg-primary);
        min-width: 0;
    }
    .review-card-red  { border-left: 3px solid #ef4444; }
    .review-card-blue { border-left: 3px solid #0ea5e9; }
    .review-card-label {
        font-size: 10px;
        font-weight: 700;
        letter-spacing: 0.05em;
        text-transform: uppercase;
        margin-bottom: 6px;
    }
    .review-text {
        font-size: 12px;
        color: var(--text-secondary);
        line-height: 1.6;
        margin: 0;
        word-break: break-word;
    }

    /* ── Combat log ──────────────────────────────────────────────────────── */
    .log-section {
        border-top: 1px solid var(--border);
        flex-shrink: 0;
    }
    .log-toggle {
        display: flex;
        align-items: center;
        gap: 6px;
        width: 100%;
        padding: 6px 16px;
        background: none;
        border: none;
        color: var(--text-muted);
        font-size: 11px;
        font-weight: 500;
        cursor: pointer;
        text-align: left;
        transition: background 0.1s, color 0.1s;
    }
    .log-toggle:hover {
        background: var(--bg-secondary);
        color: var(--text-secondary);
    }
    .log-chevron {
        font-size: 13px;
        line-height: 1;
        transition: transform 0.15s;
        display: inline-block;
    }
    .log-chevron.log-open {
        transform: rotate(90deg);
    }
    .log-count {
        margin-left: auto;
        font-size: 10px;
        color: var(--text-muted);
        opacity: 0.7;
    }
    .log-content {
        margin: 0;
        padding: 8px 16px 10px;
        font-family: monospace;
        font-size: 10.5px;
        line-height: 1.6;
        color: var(--text-muted);
        background: var(--bg-secondary);
        border-top: 1px solid var(--border);
        white-space: pre-wrap;
        word-break: break-word;
        max-height: 180px;
        overflow-y: auto;
    }
    .log-content::-webkit-scrollbar { width: 4px; }
    .log-content::-webkit-scrollbar-track { background: transparent; }
    .log-content::-webkit-scrollbar-thumb { background: var(--border); border-radius: 2px; }
</style>
