<script lang="ts">
    import type { WatcherEvent } from "../types/ipc";

    interface Props {
        suggestions: WatcherEvent[];
        onAccept: (id: string) => void;
        onDismiss: (id: string) => void;
    }

    let { suggestions, onAccept, onDismiss }: Props = $props();

    function typeIcon(type: string): string {
        switch (type) {
            case "file_change":
                return "M";
            case "schedule":
                return "S";
            case "shadow":
                return "T";
            default:
                return "?";
        }
    }

    function typeColor(type: string): string {
        switch (type) {
            case "file_change":
                return "#43AA8B";
            case "schedule":
                return "var(--warning)";
            case "shadow":
                return "#FFB02E";
            default:
                return "var(--text-muted)";
        }
    }

    function truncate(text: string, max: number = 80): string {
        return text.length > max ? text.slice(0, max) + "..." : text;
    }
</script>

{#if suggestions.length > 0}
    <div class="suggestions-bar">
        <div class="suggestions-inner">
            <span class="suggestions-label">Suggestions</span>
            <div class="chips">
                {#each suggestions as suggestion (suggestion.id)}
                    <div class="chip" title={suggestion.text}>
                        <span
                            class="chip-type"
                            style="color: {typeColor(suggestion.type)}"
                        >
                            {typeIcon(suggestion.type)}
                        </span>
                        <span class="chip-text"
                            >{truncate(suggestion.text)}</span
                        >
                        <button
                            class="chip-accept"
                            onclick={() => onAccept(suggestion.id)}
                            title="Envoyer comme message"
                        >
                            <svg
                                width="12"
                                height="12"
                                viewBox="0 0 24 24"
                                fill="none"
                                stroke="currentColor"
                                stroke-width="3"
                            >
                                <polyline points="20 6 9 17 4 12" />
                            </svg>
                        </button>
                        <button
                            class="chip-dismiss"
                            onclick={() => onDismiss(suggestion.id)}
                            title="Ignorer"
                        >
                            <svg
                                width="12"
                                height="12"
                                viewBox="0 0 24 24"
                                fill="none"
                                stroke="currentColor"
                                stroke-width="3"
                            >
                                <line x1="18" y1="6" x2="6" y2="18" />
                                <line x1="6" y1="6" x2="18" y2="18" />
                            </svg>
                        </button>
                    </div>
                {/each}
            </div>
        </div>
    </div>
{/if}

<style>
    .suggestions-bar {
        border-top: 1px solid var(--border);
        background: var(--bg-secondary);
        overflow: hidden;
        animation: slideDown 0.2s ease-out;
    }

    @keyframes slideDown {
        from {
            max-height: 0;
            opacity: 0;
        }
        to {
            max-height: 200px;
            opacity: 1;
        }
    }

    .suggestions-inner {
        max-width: 800px;
        margin: 0 auto;
        padding: 0.4rem 1rem;
        display: flex;
        align-items: center;
        gap: 0.5rem;
    }

    .suggestions-label {
        font-size: 0.6rem;
        color: var(--text-muted);
        text-transform: uppercase;
        letter-spacing: 0.08em;
        flex-shrink: 0;
    }

    .chips {
        display: flex;
        gap: 0.4rem;
        overflow-x: auto;
        flex: 1;
        scrollbar-width: none;
    }
    .chips::-webkit-scrollbar {
        display: none;
    }

    .chip {
        display: flex;
        align-items: center;
        gap: 0.3rem;
        padding: 0.25rem 0.5rem;
        background: var(--bg-tertiary);
        border: 1px solid var(--border);
        border-radius: 6px;
        flex-shrink: 0;
        max-width: 350px;
        transition: border-color 0.15s;
    }
    .chip:hover {
        border-color: var(--text-muted);
    }

    .chip-type {
        font-size: 0.65rem;
        font-weight: 700;
        flex-shrink: 0;
        width: 14px;
        text-align: center;
    }

    .chip-text {
        font-size: 0.7rem;
        color: var(--text-secondary);
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
    }

    .chip-accept,
    .chip-dismiss {
        background: none;
        border: none;
        cursor: pointer;
        padding: 2px;
        border-radius: 3px;
        display: flex;
        align-items: center;
        justify-content: center;
        flex-shrink: 0;
        color: var(--text-muted);
        transition:
            color 0.1s,
            background 0.1s;
    }
    .chip-accept:hover {
        color: var(--success);
        background: rgba(34, 197, 94, 0.1);
    }
    .chip-dismiss:hover {
        color: var(--error);
        background: rgba(239, 68, 68, 0.1);
    }
</style>
