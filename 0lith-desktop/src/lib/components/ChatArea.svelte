<script lang="ts">
    import { tick } from "svelte";
    import ChatMessage from "./ChatMessage.svelte";
    import OLithEye from "./OLithEye.svelte";
    import * as chat from "../stores/chat.svelte";

    function formatElapsed(t: number): string {
        if (t < 60) return `${t.toFixed(1)}s`;
        const m = Math.floor(t / 60);
        const s = Math.round(t % 60);
        return `${m}m ${s}s`;
    }

    let scrollContainer: HTMLDivElement;

    // Auto-scroll when messages change
    $effect(() => {
        const msgs = chat.getMessages();
        if (msgs.length > 0 && scrollContainer) {
            tick().then(() => {
                scrollContainer.scrollTop = scrollContainer.scrollHeight;
            });
        }
    });
</script>

<div class="chat-area" bind:this={scrollContainer}>
    {#if chat.getMessages().length === 0}
        <div class="empty">
            <OLithEye
                size={150}
                animated={true}
                eyeState="idle"
                clickable
                trackMouse
            />
            <div class="logo">0Lith</div>
            <div class="subtitle">Multi-Agent Cybersecurity System</div>
            <div class="hint">
                Send a message to start a conversation. Hodolith will route it
                to the right agent.
            </div>
        </div>
    {:else}
        <div class="messages">
            {#each chat.getMessages() as message (message.id)}
                <ChatMessage {message} />
            {/each}
        </div>
    {/if}

    {#if chat.isLoading() && !chat.isStreaming()}
        <div class="thinking">
            <div class="thinking-dots">
                <span></span><span></span><span></span>
            </div>
            <span class="thinking-text">
                {chat.getActiveAgent()
                    ? `${chat.getActiveAgent()} réfléchit...`
                    : "Réflexion..."}
                ({formatElapsed(chat.getElapsed())})
            </span>
        </div>
    {/if}
</div>

<style>
    .chat-area {
        flex: 1;
        overflow-y: auto;
        padding: 1rem;
    }
    .empty {
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        height: 100%;
        gap: 0.5rem;
        opacity: 0.5;
    }
    .logo {
        font-size: 2.5rem;
        font-weight: 800;
        letter-spacing: -0.05em;
    }
    .subtitle {
        font-size: 0.875rem;
        color: var(--text-secondary);
    }
    .hint {
        font-size: 0.75rem;
        color: var(--text-muted);
        margin-top: 1rem;
        max-width: 400px;
        text-align: center;
    }
    .messages {
        display: flex;
        flex-direction: column;
        gap: 0.25rem;
        max-width: 800px;
        margin: 0 auto;
    }
    .thinking {
        display: flex;
        align-items: center;
        gap: 0.5rem;
        padding: 0.5rem 1rem;
        margin-top: 0.5rem;
        max-width: 800px;
        margin-left: auto;
        margin-right: auto;
    }
    .thinking-text {
        font-size: 0.8rem;
        color: var(--warning);
    }
    .thinking-dots {
        display: flex;
        gap: 3px;
    }
    .thinking-dots span {
        width: 6px;
        height: 6px;
        border-radius: 50%;
        background: var(--warning);
        animation: bounce 1.2s infinite;
    }
    .thinking-dots span:nth-child(2) {
        animation-delay: 0.2s;
    }
    .thinking-dots span:nth-child(3) {
        animation-delay: 0.4s;
    }
    @keyframes bounce {
        0%,
        80%,
        100% {
            opacity: 0.3;
            transform: scale(0.8);
        }
        40% {
            opacity: 1;
            transform: scale(1);
        }
    }
</style>
