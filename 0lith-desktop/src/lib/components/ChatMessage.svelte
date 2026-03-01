<script lang="ts">
    import { marked } from "marked";
    import DOMPurify from "dompurify";
    import OLithEye from "./OLithEye.svelte";
    import * as chat from "./stores/chat.svelte";
    import type { ChatMessage } from "../types/ipc";

    interface Props {
        message: ChatMessage;
    }

    let { message }: Props = $props();

    let showReasonInput = $state(false);
    let reasonText = $state("");

    let renderedHtml = $derived(
        message.type === "agent" || message.type === "user"
            ? DOMPurify.sanitize(marked.parse(message.content) as string)
            : "",
    );

    let timeStr = $derived(
        new Date(message.timestamp).toLocaleTimeString("fr-FR", {
            hour: "2-digit",
            minute: "2-digit",
        }),
    );

    // Format response time: "2.3s", "1m 12s", "2m 30s"
    let responseTimeStr = $derived.by(() => {
        if (!message.responseTime) return "";
        const t = message.responseTime;
        if (t < 60) return `${t.toFixed(1)}s`;
        const m = Math.floor(t / 60);
        const s = Math.round(t % 60);
        return `${m}m ${s}s`;
    });

    async function copyContent() {
        try {
            await navigator.clipboard.writeText(message.content);
        } catch {
            /* ignore */
        }
    }

    function handleThumbUp() {
        if (message.rating === "up") {
            chat.sendFeedback(message.id, null);
        } else {
            showReasonInput = false;
            reasonText = "";
            chat.sendFeedback(message.id, "up");
        }
    }

    function handleThumbDown() {
        if (message.rating === "down") {
            showReasonInput = false;
            reasonText = "";
            chat.sendFeedback(message.id, null);
        } else {
            showReasonInput = true;
        }
    }

    function submitReason() {
        chat.sendFeedback(message.id, "down", reasonText || undefined);
        showReasonInput = false;
    }
</script>

{#if message.type === "user"}
    <div class="msg msg-user">
        <div class="bubble-user">
            <div class="markdown-content">{@html renderedHtml}</div>
            <div class="meta">
                <span class="time">{timeStr}</span>
            </div>
        </div>
    </div>
{:else if message.type === "agent"}
    <div class="msg msg-agent">
        <div class="agent-line" style="background: {message.agentColor};"></div>
        <div class="agent-body">
            <div class="agent-header">
                <OLithEye
                    size={22}
                    agentColor={message.agentColor ?? "#FFFFFF"}
                    animated={false}
                />
                <span class="agent-name" style="color: {message.agentColor};">
                    {message.agentName}
                </span>
                <span class="meta-inline">
                    {#if responseTimeStr}
                        <span class="response-time">{responseTimeStr}</span>
                    {/if}
                    <span class="time">{timeStr}</span>
                </span>
            </div>
            <div class="agent-content">
                <div class="markdown-content">{@html renderedHtml}</div>
            </div>
            <div class="agent-actions" class:visible={message.rating != null}>
                <button class="action-btn" onclick={copyContent} title="Copier">
                    <svg
                        width="14"
                        height="14"
                        viewBox="0 0 24 24"
                        fill="none"
                        stroke="currentColor"
                        stroke-width="2"
                    >
                        <rect
                            x="9"
                            y="9"
                            width="13"
                            height="13"
                            rx="2"
                            ry="2"
                        />
                        <path
                            d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"
                        />
                    </svg>
                </button>
                <button
                    class="action-btn"
                    class:thumb-up={message.rating === "up"}
                    onclick={handleThumbUp}
                    title="Bonne réponse"
                >
                    <svg
                        width="14"
                        height="14"
                        viewBox="0 0 24 24"
                        fill="none"
                        stroke="currentColor"
                        stroke-width="2"
                    >
                        <path d="M7 10v12" /><path
                            d="M15 5.88L14 10h5.83a2 2 0 0 1 1.92 2.56l-2.33 8A2 2 0 0 1 17.5 22H4a2 2 0 0 1-2-2v-8a2 2 0 0 1 2-2h2.76a2 2 0 0 0 1.79-1.11L12 2h0a3.13 3.13 0 0 1 3 3.88Z"
                        />
                    </svg>
                </button>
                <button
                    class="action-btn"
                    class:thumb-down={message.rating === "down"}
                    onclick={handleThumbDown}
                    title="Mauvaise réponse"
                >
                    <svg
                        width="14"
                        height="14"
                        viewBox="0 0 24 24"
                        fill="none"
                        stroke="currentColor"
                        stroke-width="2"
                    >
                        <path d="M17 14V2" /><path
                            d="M9 18.12L10 14H4.17a2 2 0 0 1-1.92-2.56l2.33-8A2 2 0 0 1 6.5 2H20a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2h-2.76a2 2 0 0 0-1.79 1.11L12 22h0a3.13 3.13 0 0 1-3-3.88Z"
                        />
                    </svg>
                </button>
            </div>
            {#if showReasonInput}
                <div class="feedback-reason">
                    <input
                        type="text"
                        class="reason-input"
                        placeholder="Qu'est-ce qui ne va pas ?"
                        bind:value={reasonText}
                        onkeydown={(e) => {
                            if (e.key === "Enter") submitReason();
                        }}
                    />
                    <button class="reason-submit" onclick={submitReason}>
                        <svg
                            width="12"
                            height="12"
                            viewBox="0 0 24 24"
                            fill="none"
                            stroke="currentColor"
                            stroke-width="2"
                        >
                            <path d="M22 2L11 13" /><path
                                d="M22 2L15 22L11 13L2 9L22 2Z"
                            />
                        </svg>
                    </button>
                </div>
            {/if}
        </div>
    </div>
{:else if message.type === "routing"}
    <div class="msg msg-center">
        <div class="routing">
            <span style="color: var(--hodolith);">Hodolith</span>
            <span class="arrow">&rarr;</span>
            <span style="color: {message.agentColor};">{message.agentName}</span
            >
            <span class="reason">({message.content})</span>
        </div>
    </div>
{:else if message.type === "system"}
    <div class="msg msg-center">
        <div class="system-msg">{message.content}</div>
    </div>
{:else if message.type === "error"}
    <div class="msg msg-center">
        <div class="error-msg">{message.content}</div>
    </div>
{/if}

<style>
    .msg {
        margin: 0.25rem 0;
        display: flex;
        gap: 0;
    }
    .msg-user {
        justify-content: flex-end;
        padding: 0.25rem 1rem;
    }
    .msg-agent {
        justify-content: flex-start;
        align-items: stretch;
    }
    .msg-center {
        justify-content: center;
        padding: 0.15rem 1rem;
    }

    /* User bubble - compact, right aligned */
    .bubble-user {
        max-width: 70%;
        padding: 0.5rem 0.75rem;
        background: var(--bg-tertiary);
        border-radius: 12px 12px 2px 12px;
        font-size: 0.875rem;
    }

    /* Agent message - line on left, no background */
    .agent-line {
        width: 3px;
        flex-shrink: 0;
        border-radius: 2px;
    }
    .agent-body {
        flex: 1;
        min-width: 0;
        padding: 0.5rem 1rem;
    }
    .agent-header {
        display: flex;
        align-items: center;
        gap: 0.4rem;
        margin-bottom: 0.35rem;
    }
    .agent-name {
        font-size: 0.75rem;
        font-weight: 700;
    }
    .meta-inline {
        margin-left: auto;
        display: flex;
        align-items: center;
        gap: 0.4rem;
    }
    .agent-content {
        font-size: 0.875rem;
        line-height: 1.55;
        color: var(--text-primary);
    }
    .agent-actions {
        margin-top: 0.3rem;
        display: inline-flex;
        align-items: center;
        gap: 2px;
        opacity: 0;
        transition: opacity 0.15s;
    }
    .agent-actions.visible,
    .msg-agent:hover .agent-actions {
        opacity: 1;
    }
    .action-btn {
        background: none;
        border: none;
        color: var(--text-muted);
        cursor: pointer;
        padding: 3px;
        border-radius: 4px;
        display: inline-flex;
        align-items: center;
    }
    .action-btn:hover {
        color: var(--text-primary);
        background: var(--bg-tertiary);
    }
    .action-btn.thumb-up {
        color: #22c55e;
    }
    .action-btn.thumb-down {
        color: #ef4444;
    }

    .feedback-reason {
        display: flex;
        align-items: center;
        gap: 0.35rem;
        margin-top: 0.3rem;
    }
    .reason-input {
        flex: 1;
        max-width: 300px;
        padding: 0.25rem 0.5rem;
        font-size: 0.75rem;
        background: var(--bg-tertiary);
        border: 1px solid var(--border);
        border-radius: 6px;
        color: var(--text-primary);
        outline: none;
    }
    .reason-input:focus {
        border-color: var(--text-muted);
    }
    .reason-input::placeholder {
        color: var(--text-muted);
    }
    .reason-submit {
        background: none;
        border: none;
        color: var(--text-muted);
        cursor: pointer;
        padding: 4px;
        border-radius: 4px;
        display: inline-flex;
        align-items: center;
    }
    .reason-submit:hover {
        color: var(--text-primary);
        background: var(--bg-tertiary);
    }

    /* Shared meta */
    .meta {
        display: flex;
        align-items: center;
        gap: 0.5rem;
        margin-top: 0.2rem;
        justify-content: flex-end;
    }
    .time {
        font-size: 0.6rem;
        color: var(--text-muted);
    }
    .response-time {
        font-size: 0.6rem;
        color: var(--text-muted);
        font-variant-numeric: tabular-nums;
    }

    /* Routing pill */
    .routing {
        font-size: 0.7rem;
        color: var(--text-muted);
        display: inline-flex;
        align-items: center;
        gap: 0.3rem;
        padding: 0.15rem 0.5rem;
        background: var(--bg-secondary);
        border-radius: 10px;
    }
    .arrow {
        color: var(--text-muted);
    }
    .reason {
        color: var(--text-muted);
        font-style: italic;
        max-width: 250px;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
    }

    /* System/Error */
    .system-msg {
        font-size: 0.7rem;
        color: var(--text-muted);
        padding: 0.15rem 0.5rem;
        background: var(--bg-secondary);
        border-radius: 10px;
    }
    .error-msg {
        font-size: 0.7rem;
        color: var(--error);
        padding: 0.15rem 0.5rem;
        background: rgba(239, 68, 68, 0.1);
        border: 1px solid rgba(239, 68, 68, 0.3);
        border-radius: 10px;
    }
</style>
