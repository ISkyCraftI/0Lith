<script lang="ts">
    import * as arena from "../stores/arena.svelte";

    let logOpen   = $state(false);
    let combatLog = $derived(arena.getCombatLog());
    let allMoves  = $derived(arena.getMoves());
</script>

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

<style>
    .log-section { border-top: 1px solid var(--border); flex-shrink: 0; }
    .log-toggle {
        display: flex; align-items: center; gap: 6px;
        width: 100%; padding: 6px 14px;
        background: none; border: none;
        color: var(--text-muted);
        font-size: 11px; font-weight: 500;
        cursor: pointer; text-align: left;
        transition: background 0.1s, color 0.1s;
    }
    .log-toggle:hover { background: var(--bg-secondary); color: var(--text-secondary); }
    .log-chevron {
        font-size: 13px; line-height: 1;
        transition: transform 0.15s;
        display: inline-block;
    }
    .log-chevron.log-open { transform: rotate(90deg); }
    .log-count { margin-left: auto; font-size: 10px; color: var(--text-muted); opacity: 0.7; }
    .log-content {
        margin: 0; padding: 8px 14px 10px;
        font-family: monospace; font-size: 10.5px;
        line-height: 1.6; color: var(--text-muted);
        background: var(--bg-secondary);
        border-top: 1px solid var(--border);
        white-space: pre-wrap; word-break: break-word;
        max-height: 180px; overflow-y: auto;
    }
    .log-content::-webkit-scrollbar { width: 4px; }
    .log-content::-webkit-scrollbar-track { background: transparent; }
    .log-content::-webkit-scrollbar-thumb { background: var(--border); border-radius: 2px; }
</style>
