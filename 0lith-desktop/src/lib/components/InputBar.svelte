<script lang="ts">
    import * as chat from "./stores/chat.svelte";
    import * as backend from "./stores/pythonBackend.svelte";
    import * as arenaStore from "./stores/arena.svelte";

    let inputText = $state("");
    let textarea: HTMLTextAreaElement;
    let arenaLocked = $derived(
        arenaStore.getPhase() === "running" || arenaStore.getPhase() === "review"
    );
    let disabled = $derived(chat.isLoading() || !backend.isConnected() || arenaLocked);

    function handleKeydown(e: KeyboardEvent) {
        if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            send();
        }
    }

    async function send() {
        const text = inputText.trim();
        if (!text || disabled) return;
        inputText = "";
        // Reset textarea height
        if (textarea) textarea.style.height = "auto";
        await chat.sendMessage(text);
    }

    function handleInput() {
        if (textarea) {
            textarea.style.height = "auto";
            textarea.style.height = Math.min(textarea.scrollHeight, 150) + "px";
        }
    }
</script>

<div class="input-bar-wrapper">
    {#if arenaLocked}
        <div class="arena-notice">
            <span class="arena-notice-dot"></span>
            Arena en cours — envoi désactivé pendant le combat
        </div>
    {/if}
    <div class="input-bar">
        <textarea
            bind:this={textarea}
            bind:value={inputText}
            oninput={handleInput}
            onkeydown={handleKeydown}
            placeholder={arenaLocked
                ? "Arena en cours — passe sur l'onglet Arena pour suivre le combat"
                : backend.isConnected()
                  ? "Ecris un message... (Shift+Enter pour nouvelle ligne)"
                  : "Backend disconnected..."}
            {disabled}
            rows="1"
        ></textarea>

        {#if chat.isLoading()}
            <button class="btn btn-cancel" aria-label="Annuler" onclick={() => chat.cancelMessage()}>
                <svg
                    width="18"
                    height="18"
                    viewBox="0 0 24 24"
                    fill="currentColor"
                    aria-hidden="true"
                    ><rect x="6" y="6" width="12" height="12" rx="2" /></svg
                >
            </button>
        {:else}
            <button
                class="btn btn-send"
                aria-label="Envoyer"
                onclick={send}
                disabled={!inputText.trim() || disabled}
            >
                <svg
                    width="18"
                    height="18"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    stroke-width="2"
                    aria-hidden="true"
                    ><line x1="22" y1="2" x2="11" y2="13" /><polygon
                        points="22 2 15 22 11 13 2 9 22 2"
                    /></svg
                >
            </button>
        {/if}
    </div>
</div>

<style>
    .input-bar-wrapper {
        border-top: 1px solid var(--border);
        background: var(--bg-primary);
    }
    .arena-notice {
        display: flex;
        align-items: center;
        gap: 7px;
        padding: 5px 1rem;
        font-size: 11px;
        color: #ea580c;
        background: rgba(234,88,12,0.06);
        border-bottom: 1px solid rgba(234,88,12,0.15);
    }
    .arena-notice-dot {
        width: 5px;
        height: 5px;
        border-radius: 50%;
        background: #ea580c;
        flex-shrink: 0;
        animation: pulse-dot 1.5s infinite;
    }
    @keyframes pulse-dot {
        0%, 100% { opacity: 1; }
        50%       { opacity: 0.3; }
    }
    .input-bar {
        display: flex;
        align-items: flex-end;
        gap: 0.5rem;
        padding: 0.75rem 1rem;
        max-width: 800px;
        margin: 0 auto;
        width: 100%;
    }
    textarea {
        flex: 1;
        resize: none;
        padding: 0.6rem 0.8rem;
        background: var(--bg-secondary);
        color: var(--text-primary);
        border: 1px solid var(--border);
        border-radius: 8px;
        font-family: inherit;
        font-size: 0.875rem;
        line-height: 1.4;
        outline: none;
        min-height: 38px;
        max-height: 150px;
    }
    textarea:focus {
        border-color: var(--accent);
    }
    textarea:disabled {
        opacity: 0.5;
    }
    .btn {
        width: 38px;
        height: 38px;
        border: none;
        border-radius: 8px;
        cursor: pointer;
        display: flex;
        align-items: center;
        justify-content: center;
        flex-shrink: 0;
        background: none;
        color: var(--text-muted);
        transition:
            background 0.15s,
            color 0.15s;
    }
    .btn:hover {
        background: var(--bg-tertiary);
        color: var(--text-primary);
    }
    .btn-send:disabled {
        opacity: 0.3;
        cursor: default;
    }
    .btn-send:disabled:hover {
        background: none;
        color: var(--text-muted);
    }
    .btn-cancel {
        color: var(--error);
    }
    .btn-cancel:hover {
        background: rgba(239, 68, 68, 0.1);
        color: var(--error);
    }
</style>
