<script lang="ts">
    import * as arena from "../stores/arena.svelte";

    interface Props {
        selectedScenario: string;
        onScenarioChange: (s: string) => void;
        onStart: () => Promise<void>;
    }
    let { selectedScenario, onScenarioChange, onStart }: Props = $props();

    const scenarios = [
        { id: "SQL Injection",        label: "SQL Injection",        enabled: true  },
        { id: "Phishing",             label: "Phishing",             enabled: false },
        { id: "Privilege Escalation", label: "Privilege Escalation", enabled: false },
    ];

    let errMsg     = $derived(arena.getError());
    let lastResult = $derived(arena.getLastResult());

    function formatDurationShort(secs: number): string {
        const m = Math.floor(secs / 60);
        const s = secs % 60;
        return m > 0 ? `${m}m${s.toString().padStart(2, "0")}s` : `${s}s`;
    }
</script>

<div class="arena-view arena-idle">
    <div class="arena-content">
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

        <div class="scenario-pills">
            {#each scenarios as sc}
                <button
                    class="scenario-pill"
                    class:pill-active={selectedScenario === sc.id}
                    class:pill-disabled={!sc.enabled}
                    disabled={!sc.enabled}
                    onclick={() => { if (sc.enabled) onScenarioChange(sc.id); }}
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

        <button class="start-btn" onclick={onStart}>
            <svg width="14" height="14" viewBox="0 0 14 14" fill="currentColor" aria-hidden="true">
                <polygon points="3,1 13,7 3,13"/>
            </svg>
            Lancer {selectedScenario}
        </button>

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

<style>
    .arena-view {
        flex: 1;
        display: flex;
        flex-direction: column;
        background: var(--bg-primary);
        overflow: hidden;
        min-height: 0;
    }
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
    .flame-pulse { animation: flame-pulse 2s ease-in-out infinite; }

    .arena-title {
        font-size: 22px; font-weight: 700;
        color: var(--text-primary); margin: 0; letter-spacing: 0.02em;
    }
    .arena-desc  { font-size: 14px; color: var(--text-secondary); margin: 0; }
    .arena-sub   { font-size: 12px; color: var(--text-muted); margin: 0; line-height: 1.7; }
    .arena-order { font-size: 11px; color: var(--text-muted); margin: 0; opacity: 0.7; }

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
    .scenario-pill.pill-disabled { opacity: 0.4; cursor: not-allowed; }
    .pill-soon {
        font-size: 9px; padding: 1px 5px; border-radius: 4px;
        background: rgba(255,255,255,0.07);
        color: var(--text-muted); letter-spacing: 0.04em;
    }

    .arena-error {
        background: rgba(239,68,68,0.1);
        border: 1px solid rgba(239,68,68,0.3);
        border-radius: 6px; padding: 8px 14px;
        font-size: 12px; color: #ef4444;
        max-width: 100%; word-break: break-word;
    }
    .start-btn {
        display: inline-flex; align-items: center; gap: 8px;
        margin-top: 4px; padding: 9px 22px;
        background: #dc2626; color: #fff;
        border: none; border-radius: 6px;
        font-size: 13px; font-weight: 600; cursor: pointer;
        letter-spacing: 0.02em; transition: background 0.15s;
    }
    .start-btn:hover  { background: #b91c1c; }
    .start-btn:active { background: #991b1b; }

    .last-result { font-size: 11px; color: var(--text-muted); margin: 0; opacity: 0.8; }
    .lr-red    { color: #ef4444; }
    .lr-blue   { color: #0ea5e9; }
    .lr-time   { font-variant-numeric: tabular-nums; }
    .lr-winner { color: var(--text-muted); }
    .lr-winner-red  { color: #ef4444; }
    .lr-winner-blue { color: #0ea5e9; }
</style>
