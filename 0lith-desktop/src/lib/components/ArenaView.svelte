<script lang="ts">
    import { tick } from "svelte";
    import * as arena from "./stores/arena.svelte";
    import type { ArenaMove } from "../types/ipc";

    let redPanel  = $state<HTMLElement | null>(null);
    let bluePanel = $state<HTMLElement | null>(null);

    let phase      = $derived(arena.getPhase());
    let score      = $derived(arena.getScore());
    let review     = $derived(arena.getReview());
    let redMoves   = $derived(arena.getRedMoves());
    let blueMoves  = $derived(arena.getBlueMoves());
    let errMsg     = $derived(arena.getError());
    let roundNum   = $derived(arena.getRoundNum());
    let roundTotal = $derived(arena.getRoundTotal());
    let lastResult = $derived(arena.getLastResult());

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

    // ── Scenario selection ───────────────────────────────────────────────────
    let selectedScenario = $state("SQL Injection");
    const scenarios = [
        { id: "SQL Injection",          label: "SQL Injection",         enabled: true  },
        { id: "Phishing",               label: "Phishing",              enabled: false },
        { id: "Privilege Escalation",   label: "Privilege Escalation",  enabled: false },
    ];

    async function handleStart() {
        await arena.startArena(selectedScenario);
    }

    async function handleStop() {
        await arena.stop();
    }

    function handleReset() {
        arena.reset();
        expandedMoves.clear();
        expandedMoves = new Set(expandedMoves);
    }

    async function handleNewSession() {
        arena.reset();
        expandedMoves = new Set();
        await arena.startArena(selectedScenario);
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

    // ── Duration formatting & coloring ───────────────────────────────────────
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

    // ── Move type symbols ────────────────────────────────────────────────────
    const TYPE_SYMBOLS: Record<string, string> = {
        RECON:   "◉",
        EXPLOIT: "⚔",
        SUCCESS: "✦",
        PIVOT:   "⚔",
        DATA:    "⚔",
        MONITOR: "◈",
        ALERT:   "▲",
        BLOCK:   "■",
        PATCH:   "✦",
        ISOLATE: "■",
    };

    function typeSymbol(t: string): string {
        return TYPE_SYMBOLS[t] ?? "·";
    }

    // ── Chronometer ──────────────────────────────────────────────────────────
    let elapsed = $state(0);
    let chronoInterval: ReturnType<typeof setInterval> | null = null;

    $effect(() => {
        if (phase === "running" || phase === "review") {
            if (!chronoInterval) {
                elapsed = 0;
                chronoInterval = setInterval(() => { elapsed += 1; }, 1000);
            }
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

    function formatDurationShort(secs: number): string {
        const m = Math.floor(secs / 60);
        const s = secs % 60;
        return m > 0 ? `${m}m${s.toString().padStart(2, "0")}s` : `${s}s`;
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

    // ── Round progress dots ──────────────────────────────────────────────────
    // Completed dots alternate red/blue (R1=red, R2=blue, etc.)
    function roundDotClass(i: number): string {
        const num = i + 1; // 1-indexed round
        if (num < roundNum) return num % 2 === 1 ? "dot-done dot-red" : "dot-done dot-blue";
        if (num === roundNum) return "dot-active";
        return "dot-pending";
    }

    // ── Loading indicator ────────────────────────────────────────────────────
    // Pyrolith goes first each round (red), then Cryolith (blue)
    let generatingRed  = $derived(
        phase === "running" && redMoves.length === blueMoves.length
    );
    let generatingBlue = $derived(
        phase === "running" && redMoves.length > blueMoves.length
    );

    // ── Combat log ───────────────────────────────────────────────────────────
    let logOpen   = $state(false);
    let combatLog = $derived(arena.getCombatLog());
    let allMoves  = $derived(arena.getMoves());

    // ── Winner computation ───────────────────────────────────────────────────
    let winner = $derived(
        score.red > score.blue ? "red" : score.blue > score.red ? "blue" : "draw"
    );

    // ── Export log ───────────────────────────────────────────────────────────
    // Display the log directory path in a tooltip — no Tauri shell:open available in this scope
    const LOG_DIR = `~/.0lith/arena_logs/`;
    let exportTooltip = $state(false);

    function handleExport() {
        exportTooltip = true;
        setTimeout(() => { exportTooltip = false; }, 3000);
    }
</script>

<!-- ─── IDLE STATE ──────────────────────────────────────────────────────── -->
{#if phase === "idle"}
<div class="arena-view arena-idle">
    <div class="arena-content">

        <!-- Logo SVG — 80px with flame pulse -->
        <div class="arena-icon" aria-hidden="true">
            <svg width="80" height="80" viewBox="0 0 64 64" fill="none" xmlns="http://www.w3.org/2000/svg">
                <path class="flame-pulse"
                    d="M20 48 C20 36 28 30 24 18 C30 26 34 20 32 10 C40 20 44 30 36 42 C40 38 42 32 40 26 C46 34 46 42 40 48 Z"
                    fill="#EF4444" opacity="0.85"
                />
                <line x1="44" y1="16" x2="44" y2="48" stroke="#0EA5E9" stroke-width="2.5" stroke-linecap="round" />
                <line x1="28" y1="32" x2="60" y2="32" stroke="#0EA5E9" stroke-width="2.5" stroke-linecap="round" />
                <line x1="33" y1="21" x2="55" y2="43" stroke="#0EA5E9" stroke-width="2.5" stroke-linecap="round" />
                <line x1="55" y1="21" x2="33" y2="43" stroke="#0EA5E9" stroke-width="2.5" stroke-linecap="round" />
            </svg>
        </div>

        <h2 class="arena-title">Arena</h2>
        <p class="arena-desc">Pyrolith (Red Team) vs Cryolith (Blue Team)</p>
        <p class="arena-sub">
            5 rounds — chaque agent joue son rôle en temps réel,<br/>
            accumule des points, et analyse ses faiblesses à la fin.
        </p>
        <p class="arena-order">Ordre : Pyrolith attaque → Cryolith répond (×5 rounds)</p>

        <!-- Scenario selector -->
        <div class="scenario-pills">
            {#each scenarios as sc}
                <button
                    class="scenario-pill"
                    class:pill-active={selectedScenario === sc.id}
                    class:pill-disabled={!sc.enabled}
                    disabled={!sc.enabled}
                    onclick={() => { if (sc.enabled) selectedScenario = sc.id; }}
                >
                    {sc.label}
                    {#if !sc.enabled}
                        <span class="pill-soon">Bientôt</span>
                    {/if}
                </button>
            {/each}
        </div>

        {#if errMsg}
            <div class="arena-error">{errMsg}</div>
        {/if}

        <button class="start-btn" onclick={handleStart}>
            <svg width="14" height="14" viewBox="0 0 14 14" fill="currentColor" aria-hidden="true">
                <polygon points="3,1 13,7 3,13"/>
            </svg>
            Lancer {selectedScenario}
        </button>

        <!-- Last session stats -->
        {#if lastResult}
            <p class="last-result">
                Dernière session :
                <span class="lr-red">Red {lastResult.red}</span>
                —
                <span class="lr-blue">Blue {lastResult.blue}</span>
                ·
                <span class="lr-time">{formatDurationShort(lastResult.duration_s)}</span>
                {#if lastResult.winner !== "draw"}
                    · <span class="lr-winner" class:lr-winner-red={lastResult.winner === "red"} class:lr-winner-blue={lastResult.winner === "blue"}>
                        {lastResult.winner === "red" ? "Pyrolith gagne" : "Cryolith gagne"}
                    </span>
                {:else}
                    · <span class="lr-winner">Égalité</span>
                {/if}
            </p>
        {/if}

    </div>
</div>

<!-- ─── ACTIVE / REVIEW / DONE ─────────────────────────────────────────── -->
{:else}
<div class="arena-view arena-active">

    <!-- Header bar -->
    <div class="arena-header">
        <div class="header-left">
            <span class="scenario-label">{arena.getScenario() || "SQL Injection"}</span>
            {#if phase !== "done"}
                <span class="phase-pill">{phaseLabel()}</span>
                <span class="chrono">{formatTime(elapsed)}</span>
            {/if}
        </div>

        <!-- Round progress dots -->
        {#if phase !== "done"}
            <div class="round-dots" title="Progression rounds">
                {#each Array(roundTotal) as _, i}
                    <span class="round-dot {roundDotClass(i)}"></span>
                {/each}
            </div>
        {/if}

        <div class="header-score">
            <span class="score-red">Red {score.red}</span>
            <span class="score-sep">·</span>
            <span class="score-blue">Blue {score.blue}</span>
        </div>
        <div class="header-right">
            {#if phase === "done"}
                <button class="new-session-btn" onclick={handleNewSession}>▶ Nouvelle session</button>
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
            <div class="review-final-score">
                <span class="rfs-red">Red {score.red}</span>
                <span class="rfs-sep">—</span>
                <span class="rfs-blue">Blue {score.blue}</span>
            </div>
            <div class="review-cards">
                <div class="review-card review-card-red" class:review-winner={winner === "red"}>
                    {#if winner === "red"}
                        <div class="winner-badge winner-badge-red">VICTOIRE</div>
                    {/if}
                    <div class="review-card-label red-name">Pyrolith — Faiblesses</div>
                    <p class="review-text">{review.red}</p>
                </div>
                <div class="review-card review-card-blue" class:review-winner={winner === "blue"}>
                    {#if winner === "blue"}
                        <div class="winner-badge winner-badge-blue">VICTOIRE</div>
                    {/if}
                    <div class="review-card-label blue-name">Cryolith — Lacunes défensives</div>
                    <p class="review-text">{review.blue}</p>
                </div>
            </div>
            <div class="review-actions">
                <div class="export-wrapper">
                    <button class="export-btn" onclick={handleExport}>Exporter le log</button>
                    {#if exportTooltip}
                        <span class="export-tooltip">{LOG_DIR}</span>
                    {/if}
                </div>
            </div>
        </div>
    {/if}
</div>
{/if}

<!-- ─── Move Row Snippet ──────────────────────────────────────────────────── -->
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
        max-width: 460px;
        text-align: center;
        padding: 40px 24px;
    }
    .arena-icon { opacity: 0.8; margin-bottom: 4px; }

    @keyframes flame-pulse {
        0%, 100% { opacity: 0.85; transform-origin: bottom center; transform: scaleY(1); }
        50%       { opacity: 1;    transform-origin: bottom center; transform: scaleY(1.04); }
    }
    .flame-pulse {
        animation: flame-pulse 2s ease-in-out infinite;
    }

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

    /* ── Scenario pills ──────────────────────────────────────────────────── */
    .scenario-pills {
        display: flex;
        gap: 8px;
        flex-wrap: wrap;
        justify-content: center;
        margin-top: 4px;
    }
    .scenario-pill {
        display: inline-flex;
        align-items: center;
        gap: 5px;
        padding: 5px 14px;
        border: 1px solid var(--border);
        border-radius: 20px;
        background: transparent;
        color: var(--text-muted);
        font-size: 12px;
        cursor: pointer;
        transition: border-color 0.15s, color 0.15s, background 0.15s;
    }
    .scenario-pill:hover:not(.pill-disabled) {
        border-color: var(--text-secondary);
        color: var(--text-secondary);
    }
    .scenario-pill.pill-active {
        border-color: #ef4444;
        color: #ef4444;
        background: rgba(239,68,68,0.08);
    }
    .scenario-pill.pill-disabled {
        opacity: 0.4;
        cursor: not-allowed;
    }
    .pill-soon {
        font-size: 9px;
        padding: 1px 5px;
        border-radius: 4px;
        background: rgba(255,255,255,0.07);
        color: var(--text-muted);
        letter-spacing: 0.04em;
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
        margin-top: 4px;
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
    .start-btn:hover  { background: #b91c1c; }
    .start-btn:active { background: #991b1b; }

    /* ── Last result ──────────────────────────────────────────────────────── */
    .last-result {
        font-size: 11px;
        color: var(--text-muted);
        margin: 0;
        opacity: 0.8;
    }
    .lr-red    { color: #ef4444; }
    .lr-blue   { color: #0ea5e9; }
    .lr-time   { font-variant-numeric: tabular-nums; }
    .lr-winner { color: var(--text-muted); }
    .lr-winner-red  { color: #ef4444; }
    .lr-winner-blue { color: #0ea5e9; }

    /* ── Header bar ──────────────────────────────────────────────────────── */
    .arena-header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 7px 14px;
        border-bottom: 1px solid var(--border);
        background: var(--bg-secondary);
        flex-shrink: 0;
        gap: 10px;
    }
    .header-left {
        display: flex;
        align-items: center;
        gap: 8px;
        flex: 1;
        min-width: 0;
    }
    .scenario-label {
        font-size: 12px;
        font-weight: 600;
        color: var(--text-secondary);
        letter-spacing: 0.04em;
        text-transform: uppercase;
        white-space: nowrap;
    }
    .phase-pill {
        padding: 2px 8px;
        background: rgba(234,88,12,0.15);
        border: 1px solid rgba(234,88,12,0.3);
        border-radius: 10px;
        font-size: 11px;
        color: #ea580c;
        font-weight: 500;
        white-space: nowrap;
    }
    .chrono {
        font-size: 11px;
        font-weight: 600;
        font-variant-numeric: tabular-nums;
        color: var(--text-muted);
        letter-spacing: 0.04em;
    }

    /* ── Round progress dots ──────────────────────────────────────────────── */
    .round-dots {
        display: flex;
        align-items: center;
        gap: 5px;
        flex-shrink: 0;
    }
    .round-dot {
        width: 7px;
        height: 7px;
        border-radius: 50%;
        flex-shrink: 0;
        transition: background 0.3s;
    }
    .dot-pending { background: rgba(255,255,255,0.12); }
    .dot-done.dot-red  { background: #ef4444; }
    .dot-done.dot-blue { background: #0ea5e9; }

    @keyframes dot-blink {
        0%, 100% { opacity: 1; }
        50%       { opacity: 0.25; }
    }
    .dot-active {
        background: rgba(255,255,255,0.5);
        animation: dot-blink 1s ease-in-out infinite;
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

    .header-right {
        flex: 1;
        display: flex;
        align-items: center;
        justify-content: flex-end;
        gap: 8px;
    }
    .reset-btn {
        padding: 4px 12px;
        background: transparent;
        border: 1px solid var(--border);
        border-radius: 5px;
        font-size: 12px;
        color: var(--text-muted);
        cursor: pointer;
        transition: border-color 0.15s, color 0.15s;
        white-space: nowrap;
    }
    .reset-btn:hover { border-color: var(--text-secondary); color: var(--text-secondary); }
    .new-session-btn {
        padding: 4px 12px;
        background: rgba(239,68,68,0.1);
        border: 1px solid rgba(239,68,68,0.35);
        border-radius: 5px;
        font-size: 12px;
        color: #ef4444;
        cursor: pointer;
        font-weight: 600;
        transition: background 0.15s, border-color 0.15s;
        white-space: nowrap;
    }
    .new-session-btn:hover { background: rgba(239,68,68,0.18); border-color: #ef4444; }
    .stop-btn {
        padding: 4px 12px;
        background: transparent;
        border: 1px solid rgba(239,68,68,0.4);
        border-radius: 5px;
        font-size: 12px;
        color: #ef4444;
        cursor: pointer;
        transition: border-color 0.15s, background 0.15s;
        white-space: nowrap;
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
    .panel-red  { background: rgba(239,68,68,0.025); }
    .panel-blue { background: rgba(14,165,233,0.025); }

    .panel-header {
        display: flex;
        align-items: center;
        gap: 8px;
        padding: 8px 14px 7px;
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
        gap: 6px;
        padding: 5px 12px;
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
    .move-round {
        font-size: 9px;
        color: var(--text-muted);
        font-weight: 600;
        opacity: 0.55;
        flex-shrink: 0;
        min-width: 16px;
    }
    .move-badge {
        display: inline-flex;
        align-items: center;
        gap: 3px;
        padding: 2px 6px;
        border-radius: 6px;
        font-size: 9px;
        font-weight: 700;
        letter-spacing: 0.06em;
        color: #fff;
        flex-shrink: 0;
        text-transform: uppercase;
    }
    .badge-sym {
        font-size: 8px;
        opacity: 0.9;
    }
    .move-duration {
        font-size: 9px;
        font-variant-numeric: tabular-nums;
        flex-shrink: 0;
    }
    .dur-fast { color: #22c55e; }
    .dur-mid  { color: #f97316; }
    .dur-slow { color: #ef4444; }

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
        width: 18px;
        height: 18px;
        border: 1px solid rgba(255,255,255,0.08);
        background: rgba(255,255,255,0.04);
        color: var(--text-muted);
        cursor: pointer;
        font-size: 13px;
        line-height: 1;
        padding: 0;
        display: flex;
        align-items: center;
        justify-content: center;
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
        font-size: 11px;
        color: var(--text-muted);
        line-height: 1.5;
        word-break: break-word;
        font-family: monospace;
        background: rgba(0,0,0,0.15);
        border-bottom: 1px solid rgba(255,255,255,0.03);
    }

    /* ── Waiting / generating ────────────────────────────────────────────── */
    .waiting {
        padding: 16px 12px;
        font-size: 12px;
        color: var(--text-muted);
        font-style: italic;
    }
    .generating {
        padding: 10px 12px;
        font-size: 11px;
        font-style: italic;
    }
    .generating-red  { color: rgba(239,68,68,0.7); }
    .generating-blue { color: rgba(14,165,233,0.7); }

    @keyframes dots {
        0%   { opacity: 0.2; }
        33%  { opacity: 1;   }
        66%  { opacity: 0.5; }
        100% { opacity: 0.2; }
    }
    .dots-anim {
        display: inline-block;
        animation: dots 1.2s steps(1, end) infinite;
    }

    /* ── Review section ──────────────────────────────────────────────────── */
    .review-section {
        border-top: 1px solid var(--border);
        background: var(--bg-secondary);
        padding: 12px 14px;
        flex-shrink: 0;
        max-height: 220px;
        overflow-y: auto;
    }
    .review-final-score {
        display: flex;
        align-items: center;
        justify-content: center;
        gap: 10px;
        font-size: 18px;
        font-weight: 800;
        font-variant-numeric: tabular-nums;
        margin-bottom: 12px;
    }
    .rfs-red  { color: #ef4444; }
    .rfs-blue { color: #0ea5e9; }
    .rfs-sep  { color: var(--text-muted); font-weight: 400; font-size: 16px; }

    .review-cards {
        display: flex;
        gap: 12px;
    }
    .review-card {
        flex: 1;
        padding: 10px 12px;
        border-radius: 6px;
        border: 1px solid var(--border);
        background: var(--bg-primary);
        min-width: 0;
        position: relative;
    }
    .review-card-red  { border-left: 3px solid #ef4444; }
    .review-card-blue { border-left: 3px solid #0ea5e9; }
    .review-winner {
        box-shadow: 0 0 0 1px rgba(255,255,255,0.07);
    }
    .winner-badge {
        display: inline-flex;
        align-items: center;
        padding: 2px 8px;
        border-radius: 4px;
        font-size: 9px;
        font-weight: 800;
        letter-spacing: 0.1em;
        text-transform: uppercase;
        margin-bottom: 6px;
    }
    .winner-badge-red  { background: rgba(239,68,68,0.2); color: #ef4444; }
    .winner-badge-blue { background: rgba(14,165,233,0.2); color: #0ea5e9; }

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

    .review-actions {
        margin-top: 10px;
        display: flex;
        justify-content: flex-end;
    }
    .export-wrapper {
        position: relative;
        display: inline-flex;
    }
    .export-btn {
        padding: 4px 12px;
        background: transparent;
        border: 1px solid var(--border);
        border-radius: 5px;
        font-size: 11px;
        color: var(--text-muted);
        cursor: pointer;
        transition: border-color 0.15s, color 0.15s;
    }
    .export-btn:hover { border-color: var(--text-secondary); color: var(--text-secondary); }
    .export-tooltip {
        position: absolute;
        bottom: calc(100% + 6px);
        right: 0;
        background: #1a1e24;
        border: 1px solid var(--border);
        border-radius: 5px;
        padding: 5px 10px;
        font-size: 11px;
        color: var(--text-muted);
        font-family: monospace;
        white-space: nowrap;
        pointer-events: none;
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
        padding: 6px 14px;
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
    .log-chevron.log-open { transform: rotate(90deg); }
    .log-count {
        margin-left: auto;
        font-size: 10px;
        color: var(--text-muted);
        opacity: 0.7;
    }
    .log-content {
        margin: 0;
        padding: 8px 14px 10px;
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
