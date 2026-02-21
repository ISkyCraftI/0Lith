<script lang="ts">
    import * as chat from "../stores/chat.svelte";
    import * as backend from "../stores/pythonBackend.svelte";

    let inputText = $state("");
    let textarea: HTMLTextAreaElement;
    let disabled = $derived(chat.isLoading() || !backend.isConnected());

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
    <div class="input-bar">
        <textarea
            bind:this={textarea}
            bind:value={inputText}
            oninput={handleInput}
            onkeydown={handleKeydown}
            placeholder={backend.isConnected()
                ? "Ecris un message... (Shift+Enter pour nouvelle ligne)"
                : "Backend disconnected..."}
            {disabled}
            rows="1"
        ></textarea>

        {#if chat.isLoading()}
            <button class="btn btn-cancel" onclick={() => chat.cancelMessage()}>
                <svg
                    width="18"
                    height="18"
                    viewBox="0 0 24 24"
                    fill="currentColor"
                    ><rect x="6" y="6" width="12" height="12" rx="2" /></svg
                >
            </button>
        {:else}
            <button
                class="btn btn-send"
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
