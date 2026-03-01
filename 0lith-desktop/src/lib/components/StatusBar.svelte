<script lang="ts">
    import * as backend from "./stores/pythonBackend.svelte";
    import * as chat from "./stores/chat.svelte";

    interface Props {
        ollama?: boolean;
        qdrant?: boolean;
    }

    let { ollama = false, qdrant = false }: Props = $props();

    let activeAgent = $derived(chat.getActiveAgent());
    let connected = $derived(backend.isConnected());

    function formatElapsed(t: number): string {
        if (t < 60) return `${t.toFixed(1)}s`;
        const m = Math.floor(t / 60);
        const s = Math.round(t % 60);
        return `${m}m ${s}s`;
    }
</script>

<div class="status-bar">
    <div class="status-item">
        <span
            class="dot"
            style="background: {connected ? 'var(--success)' : 'var(--error)'}"
        ></span>
        <span>Backend</span>
    </div>
    <div class="separator"></div>
    <div class="status-item">
        <span
            class="dot"
            style="background: {ollama ? 'var(--success)' : 'var(--error)'}"
        ></span>
        <span>Ollama</span>
    </div>
    <div class="separator"></div>
    <div class="status-item">
        <span
            class="dot"
            style="background: {qdrant ? 'var(--success)' : 'var(--error)'}"
        ></span>
        <span>Qdrant</span>
    </div>
    {#if activeAgent}
        <div class="separator"></div>
        <div class="status-item">
            <span>Agent: {activeAgent}</span>
        </div>
    {/if}
    {#if chat.isLoading()}
        <div class="separator"></div>
        <div class="status-item timer">
            {formatElapsed(chat.getElapsed())}
        </div>
    {/if}
</div>

<style>
    .status-bar {
        display: flex;
        align-items: center;
        gap: 0.5rem;
        padding: 0.25rem 1rem;
        background: #0f172a;
        border-top: 1px solid var(--border);
        font-size: 0.65rem;
        color: var(--text-secondary);
        min-height: 24px;
    }
    .status-item {
        display: flex;
        align-items: center;
        gap: 0.3rem;
    }
    .dot {
        width: 6px;
        height: 6px;
        border-radius: 50%;
    }
    .separator {
        width: 1px;
        height: 10px;
        background: var(--border);
    }
    .timer {
        color: var(--warning);
        font-variant-numeric: tabular-nums;
    }
</style>
