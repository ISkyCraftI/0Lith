<script lang="ts">
    import * as arena from "../stores/arena.svelte";

    let score  = $derived(arena.getScore());
    let review = $derived(arena.getReview());
    let winner = $derived(
        score.red > score.blue ? "red" : score.blue > score.red ? "blue" : "draw"
    );

    const LOG_DIR = `~/.0lith/arena_logs/`;
    let exportTooltip = $state(false);

    function handleExport() {
        exportTooltip = true;
        setTimeout(() => { exportTooltip = false; }, 3000);
    }
</script>

{#if review}
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

<style>
    .review-section {
        border-top: 1px solid var(--border);
        background: var(--bg-secondary);
        padding: 12px 14px;
        flex-shrink: 0;
        max-height: 220px;
        overflow-y: auto;
    }
    .review-final-score {
        display: flex; align-items: center; justify-content: center;
        gap: 10px;
        font-size: 18px; font-weight: 800;
        font-variant-numeric: tabular-nums;
        margin-bottom: 12px;
    }
    .rfs-red  { color: #ef4444; }
    .rfs-blue { color: #0ea5e9; }
    .rfs-sep  { color: var(--text-muted); font-weight: 400; font-size: 16px; }

    .review-cards { display: flex; gap: 12px; }
    .review-card {
        flex: 1; padding: 10px 12px;
        border-radius: 6px;
        border: 1px solid var(--border);
        background: var(--bg-primary);
        min-width: 0; position: relative;
    }
    .review-card-red  { border-left: 3px solid #ef4444; }
    .review-card-blue { border-left: 3px solid #0ea5e9; }
    .review-winner { box-shadow: 0 0 0 1px rgba(255,255,255,0.07); }
    .winner-badge {
        display: inline-flex; align-items: center;
        padding: 2px 8px; border-radius: 4px;
        font-size: 9px; font-weight: 800;
        letter-spacing: 0.1em; text-transform: uppercase;
        margin-bottom: 6px;
    }
    .winner-badge-red  { background: rgba(239,68,68,0.2); color: #ef4444; }
    .winner-badge-blue { background: rgba(14,165,233,0.2); color: #0ea5e9; }
    .review-card-label {
        font-size: 10px; font-weight: 700;
        letter-spacing: 0.05em; text-transform: uppercase; margin-bottom: 6px;
    }
    .red-name  { color: #ef4444; }
    .blue-name { color: #0ea5e9; }
    .review-text {
        font-size: 12px; color: var(--text-secondary);
        line-height: 1.6; margin: 0; word-break: break-word;
    }

    .review-actions {
        margin-top: 10px;
        display: flex;
        justify-content: flex-end;
    }
    .export-wrapper { position: relative; display: inline-flex; }
    .export-btn {
        padding: 4px 12px; background: transparent;
        border: 1px solid var(--border); border-radius: 5px;
        font-size: 11px; color: var(--text-muted); cursor: pointer;
        transition: border-color 0.15s, color 0.15s;
    }
    .export-btn:hover { border-color: var(--text-secondary); color: var(--text-secondary); }
    .export-tooltip {
        position: absolute; bottom: calc(100% + 6px); right: 0;
        background: #1a1e24;
        border: 1px solid var(--border); border-radius: 5px;
        padding: 5px 10px; font-size: 11px; color: var(--text-muted);
        font-family: monospace; white-space: nowrap; pointer-events: none;
    }
</style>
