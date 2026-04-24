<script lang="ts">
    import * as arena from "./stores/arena.svelte";
    import ArenaSetup from "./arena/ArenaSetup.svelte";
    import ArenaRound from "./arena/ArenaRound.svelte";
    import ArenaCombatLog from "./arena/ArenaCombatLog.svelte";
    import ArenaScoreboard from "./arena/ArenaScoreboard.svelte";

    let phase      = $derived(arena.getPhase());
    let score      = $derived(arena.getScore());
    let roundNum   = $derived(arena.getRoundNum());
    let roundTotal = $derived(arena.getRoundTotal());

    let selectedScenario = $state("SQL Injection");

    async function handleStart() {
        await arena.startArena(selectedScenario);
    }

    async function handleStop() {
        await arena.stop();
    }

    function handleReset() {
        arena.reset();
    }

    async function handleNewSession() {
        arena.reset();
        await arena.startArena(selectedScenario);
    }

    // Chronometer — runs while arena is active
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

    function phaseLabel(): string {
        switch (phase) {
            case "running": return "En cours";
            case "review":  return "Revue";
            case "done":    return "Terminé";
            default:        return "";
        }
    }

    function roundDotClass(i: number): string {
        const num = i + 1;
        if (num < roundNum) return num % 2 === 1 ? "dot-done dot-red" : "dot-done dot-blue";
        if (num === roundNum) return "dot-active";
        return "dot-pending";
    }
</script>

{#if phase === "idle"}
    <ArenaSetup
        {selectedScenario}
        onScenarioChange={(s) => (selectedScenario = s)}
        onStart={handleStart}
    />
{:else}
    <div class="arena-view arena-active">
        <!-- Header bar: scenario, phase, chrono, round dots, score, action buttons -->
        <div class="arena-header">
            <div class="header-left">
                <span class="scenario-label">{arena.getScenario() || "SQL Injection"}</span>
                {#if phase !== "done"}
                    <span class="phase-pill">{phaseLabel()}</span>
                    <span class="chrono">{formatTime(elapsed)}</span>
                {/if}
            </div>

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

        <!-- Live round panels (Red + VS + Blue) -->
        <ArenaRound />

        <!-- Collapsible combat log strip -->
        <ArenaCombatLog />

        <!-- Post-match review (score, winner badge, export) -->
        {#if phase === "done"}
            <ArenaScoreboard />
        {/if}
    </div>
{/if}

<style>
    .arena-view {
        flex: 1;
        display: flex;
        flex-direction: column;
        background: var(--bg-primary);
        overflow: hidden;
        min-height: 0;
    }

    /* Header bar */
    .arena-header {
        display: flex; align-items: center; justify-content: space-between;
        padding: 7px 14px;
        border-bottom: 1px solid var(--border);
        background: var(--bg-secondary);
        flex-shrink: 0; gap: 10px;
    }
    .header-left {
        display: flex; align-items: center; gap: 8px;
        flex: 1; min-width: 0;
    }
    .scenario-label {
        font-size: 12px; font-weight: 600;
        color: var(--text-secondary);
        letter-spacing: 0.04em; text-transform: uppercase; white-space: nowrap;
    }
    .phase-pill {
        padding: 2px 8px;
        background: rgba(234,88,12,0.15);
        border: 1px solid rgba(234,88,12,0.3);
        border-radius: 10px;
        font-size: 11px; color: #ea580c; font-weight: 500; white-space: nowrap;
    }
    .chrono {
        font-size: 11px; font-weight: 600;
        font-variant-numeric: tabular-nums;
        color: var(--text-muted); letter-spacing: 0.04em;
    }

    /* Round progress dots */
    .round-dots { display: flex; align-items: center; gap: 5px; flex-shrink: 0; }
    .round-dot {
        width: 7px; height: 7px;
        border-radius: 50%; flex-shrink: 0; transition: background 0.3s;
    }
    .dot-pending { background: rgba(255,255,255,0.12); }
    .dot-done.dot-red  { background: #ef4444; }
    .dot-done.dot-blue { background: #0ea5e9; }

    @keyframes dot-blink {
        0%, 100% { opacity: 1; }
        50%       { opacity: 0.25; }
    }
    .dot-active { background: rgba(255,255,255,0.5); animation: dot-blink 1s ease-in-out infinite; }

    .header-score {
        display: flex; align-items: center; gap: 8px;
        font-size: 13px; font-weight: 700;
        font-variant-numeric: tabular-nums; flex-shrink: 0;
    }
    .score-red  { color: #ef4444; }
    .score-blue { color: #0ea5e9; }
    .score-sep  { color: var(--text-muted); font-weight: 400; }

    .header-right {
        flex: 1; display: flex; align-items: center;
        justify-content: flex-end; gap: 8px;
    }
    .reset-btn {
        padding: 4px 12px; background: transparent;
        border: 1px solid var(--border); border-radius: 5px;
        font-size: 12px; color: var(--text-muted); cursor: pointer;
        transition: border-color 0.15s, color 0.15s; white-space: nowrap;
    }
    .reset-btn:hover { border-color: var(--text-secondary); color: var(--text-secondary); }
    .new-session-btn {
        padding: 4px 12px;
        background: rgba(239,68,68,0.1);
        border: 1px solid rgba(239,68,68,0.35); border-radius: 5px;
        font-size: 12px; color: #ef4444; cursor: pointer; font-weight: 600;
        transition: background 0.15s, border-color 0.15s; white-space: nowrap;
    }
    .new-session-btn:hover { background: rgba(239,68,68,0.18); border-color: #ef4444; }
    .stop-btn {
        padding: 4px 12px; background: transparent;
        border: 1px solid rgba(239,68,68,0.4); border-radius: 5px;
        font-size: 12px; color: #ef4444; cursor: pointer;
        transition: border-color 0.15s, background 0.15s; white-space: nowrap;
    }
    .stop-btn:hover { border-color: #ef4444; background: rgba(239,68,68,0.08); }
</style>
