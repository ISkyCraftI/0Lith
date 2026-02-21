<script lang="ts">
    import OLithEye from "./OLithEye.svelte";
    import * as agentsStore from "../stores/agents.svelte";
    import * as chat from "../stores/chat.svelte";
    import * as gaming from "../stores/gaming.svelte";
    import type { Agent, AgentId, AgentStatus } from "../types/ipc";

    interface Props {
        loadedModels?: Array<{
            name: string;
            size_gb: number;
            vram_gb: number;
        }>;
        vramUsedGb?: number;
        onRefreshStatus?: () => void;
        onMemoryInit?: () => void;
        onToggleGaming?: () => void;
    }

    let {
        loadedModels = [],
        vramUsedGb = 0,
        onRefreshStatus,
        onMemoryInit,
        onToggleGaming,
    }: Props = $props();

    let agents = $derived(agentsStore.getAgents());
    let statuses = $derived(agentsStore.getAllStatuses());
    let activeAgent = $derived(chat.getActiveAgent());

    const defaultAgents: Agent[] = [
        {
            id: "hodolith",
            name: "Hodolith",
            role: "Dispatcher",
            model: "qwen3:1.7b",
            color: "#FFB02E",
            emoji: "🟨",
            description: "",
            capabilities: [],
            location: "local",
        },
        {
            id: "monolith",
            name: "Monolith",
            role: "Orchestrateur",
            model: "qwen3:14b",
            color: "#181A1E",
            emoji: "⬛",
            description: "",
            capabilities: [],
            location: "local",
        },
        {
            id: "aerolith",
            name: "Aerolith",
            role: "Codeur",
            model: "qwen3-coder:30b",
            color: "#43AA8B",
            emoji: "⬜",
            description: "",
            capabilities: [],
            location: "local",
        },
        {
            id: "cryolith",
            name: "Cryolith",
            role: "Blue Team",
            model: "Foundation-Sec-8B",
            color: "#7BDFF2",
            emoji: "🟦",
            description: "",
            capabilities: [],
            location: "local",
        },
        {
            id: "pyrolith",
            name: "Pyrolith",
            role: "Red Team",
            model: "DeepHat-V1-7B",
            color: "#BF0603",
            emoji: "🟥",
            description: "",
            capabilities: [],
            location: "docker",
        },
    ];

    let displayAgents = $derived(agents.length > 0 ? agents : defaultAgents);

    let gamingMode = $derived(gaming.isGaming());

    // Eye state mapping from active agent status
    let sidebarEyeState = $derived.by(() => {
        if (gamingMode) return "gaming" as const;
        if (!activeAgent) return "idle" as const;
        const s = statuses[activeAgent] as AgentStatus | undefined;
        if (s === "thinking") return "thinking" as const;
        if (s === "responding") return "responding" as const;
        return "idle" as const;
    });

    // Eye color from active agent
    let eyeColor = $derived.by(() => {
        if (!activeAgent) return "#FFFFFF";
        const agent = displayAgents.find((a) => a.id === activeAgent);
        return agent?.color ?? "#FFFFFF";
    });

    // Check if a model is currently loaded in VRAM
    function isModelLoaded(agent: Agent): boolean {
        return loadedModels.some((m) =>
            m.name.includes(agent.model.split(":")[0]),
        );
    }

    function getModelVram(agent: Agent): number {
        const found = loadedModels.find((m) =>
            m.name.includes(agent.model.split(":")[0]),
        );
        return found?.vram_gb ?? 0;
    }

    let settingsOpen = $state(false);
</script>

<aside class="sidebar">
    <div class="sidebar-header">
        <OLithEye
            size={32}
            agentColor={eyeColor}
            eyeState={sidebarEyeState}
            clickable
        />
        <div class="title">0Lith</div>
        <div class="version">v0.1</div>
    </div>

    <div class="agents-label">Agents</div>

    <div class="agents-list">
        {#each displayAgents as agent (agent.id)}
            {@const status = statuses[agent.id] ?? "idle"}
            {@const isActive = activeAgent === agent.id}
            {@const loaded = isModelLoaded(agent)}
            <div class="agent-item" class:active={isActive}>
                <OLithEye size={28} agentColor={agent.color} animated={false} />
                <div class="agent-info">
                    <div class="agent-name">{agent.name}</div>
                    <div class="agent-meta">
                        <span class="agent-role">{agent.role}</span>
                        {#if loaded}
                            <span
                                class="vram-badge"
                                title="{getModelVram(agent)} GB VRAM">GPU</span
                            >
                        {:else}
                            <span class="disk-badge" title="Model on disk"
                                >DISK</span
                            >
                        {/if}
                    </div>
                </div>
                <div
                    class="status-dot"
                    class:thinking={status === "thinking"}
                    class:offline={status === "offline"}
                    style="background: {status === 'offline'
                        ? 'var(--text-muted)'
                        : status === 'thinking'
                          ? 'var(--warning)'
                          : 'var(--success)'};"
                ></div>
            </div>
        {/each}
    </div>

    <!-- VRAM indicator -->
    <div class="vram-section">
        {#if gamingMode}
            <div class="vram-label gaming-label">Gaming Mode</div>
            <div class="vram-bar-container">
                <div class="vram-bar gaming-bar" style="width: 0%;"></div>
            </div>
            <div class="vram-text gaming-text">VRAM Free — 16 GB available</div>
        {:else if vramUsedGb > 0}
            <div class="vram-label">VRAM Usage</div>
            <div class="vram-bar-container">
                <div
                    class="vram-bar"
                    style="width: {Math.min((vramUsedGb / 16) * 100, 100)}%;"
                ></div>
            </div>
            <div class="vram-text">{vramUsedGb} / 16 GB</div>
        {/if}
    </div>

    <div class="sidebar-footer">
        <div class="settings-wrapper">
            <button
                class="gear-btn"
                onclick={() => (settingsOpen = !settingsOpen)}
                title="Paramètres"
            >
                <svg
                    width="16"
                    height="16"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    stroke-width="2"
                    stroke-linecap="round"
                    stroke-linejoin="round"
                >
                    <circle cx="12" cy="12" r="3" /><path
                        d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"
                    />
                </svg>
            </button>
            {#if settingsOpen}
                <div class="settings-menu">
                    {#if onMemoryInit}
                        <button
                            class="menu-item"
                            onclick={() => {
                                onMemoryInit();
                                settingsOpen = false;
                            }}
                        >
                            Memory Init
                        </button>
                    {/if}
                    {#if onRefreshStatus}
                        <button
                            class="menu-item"
                            onclick={() => {
                                onRefreshStatus();
                                settingsOpen = false;
                            }}
                        >
                            Refresh Status
                        </button>
                    {/if}
                    <button
                        class="menu-item"
                        onclick={() => {
                            chat.clearMessages();
                            settingsOpen = false;
                        }}
                    >
                        Clear chat
                    </button>
                    <div class="menu-divider"></div>
                    {#if onToggleGaming}
                        <button
                            class="menu-item gaming-toggle"
                            class:gaming-active={gamingMode}
                            onclick={() => {
                                onToggleGaming();
                                settingsOpen = false;
                            }}
                        >
                            <svg
                                width="14"
                                height="14"
                                viewBox="0 0 24 24"
                                fill="none"
                                stroke="currentColor"
                                stroke-width="2"
                                stroke-linecap="round"
                                stroke-linejoin="round"
                            >
                                <rect
                                    x="2"
                                    y="6"
                                    width="20"
                                    height="12"
                                    rx="2"
                                />
                                <circle cx="8.5" cy="12" r="1.5" />
                                <circle cx="15.5" cy="12" r="1.5" />
                                <path d="M6 10v4" /><path d="M5 12h3" />
                            </svg>
                            {gamingMode ? "Exit Gaming Mode" : "Gaming Mode"}
                        </button>
                    {/if}
                </div>
            {/if}
        </div>
    </div>
</aside>

<style>
    .sidebar {
        width: 220px;
        min-width: 220px;
        background: var(--bg-secondary);
        border-right: 1px solid var(--border);
        display: flex;
        flex-direction: column;
        height: 100%;
    }
    .sidebar-header {
        padding: 0.75rem 1rem;
        display: flex;
        align-items: center;
        gap: 0.5rem;
        border-bottom: 1px solid var(--border);
    }
    .title {
        font-size: 1.2rem;
        font-weight: 800;
        letter-spacing: -0.03em;
    }
    .version {
        font-size: 0.65rem;
        color: var(--text-muted);
    }
    .agents-label {
        font-size: 0.65rem;
        color: var(--text-muted);
        text-transform: uppercase;
        letter-spacing: 0.1em;
        padding: 0.75rem 1rem 0.25rem;
    }
    .agents-list {
        flex: 1;
        overflow-y: auto;
        padding: 0.25rem 0.5rem;
    }
    .agent-item {
        display: flex;
        align-items: center;
        gap: 0.5rem;
        padding: 0.4rem 0.5rem;
        border-radius: 6px;
        cursor: default;
        transition: background 0.15s;
    }
    .agent-item:hover {
        background: var(--bg-tertiary);
    }
    .agent-item.active {
        background: var(--bg-tertiary);
    }
    .agent-info {
        flex: 1;
        min-width: 0;
    }
    .agent-name {
        font-size: 0.8rem;
        font-weight: 600;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
    }
    .agent-meta {
        display: flex;
        align-items: center;
        gap: 0.35rem;
    }
    .agent-role {
        font-size: 0.65rem;
        color: var(--text-muted);
    }
    .vram-badge {
        font-size: 0.55rem;
        padding: 0px 4px;
        border-radius: 3px;
        background: rgba(34, 197, 94, 0.15);
        color: var(--success);
        font-weight: 600;
        letter-spacing: 0.03em;
    }
    .disk-badge {
        font-size: 0.55rem;
        padding: 0px 4px;
        border-radius: 3px;
        background: rgba(100, 116, 139, 0.15);
        color: var(--text-muted);
        font-weight: 600;
        letter-spacing: 0.03em;
    }
    .status-dot {
        width: 8px;
        height: 8px;
        border-radius: 50%;
        flex-shrink: 0;
    }
    .status-dot.thinking {
        animation: pulse 1.2s infinite;
    }
    @keyframes pulse {
        0%,
        100% {
            opacity: 1;
        }
        50% {
            opacity: 0.3;
        }
    }
    .vram-section {
        padding: 0.5rem 0.75rem;
        border-top: 1px solid var(--border);
    }
    .vram-label {
        font-size: 0.6rem;
        color: var(--text-muted);
        text-transform: uppercase;
        letter-spacing: 0.08em;
        margin-bottom: 0.3rem;
    }
    .vram-bar-container {
        height: 4px;
        background: var(--bg-tertiary);
        border-radius: 2px;
        overflow: hidden;
    }
    .vram-bar {
        height: 100%;
        background: linear-gradient(90deg, var(--success), var(--warning));
        border-radius: 2px;
        transition: width 0.3s;
    }
    .vram-text {
        font-size: 0.6rem;
        color: var(--text-muted);
        margin-top: 0.2rem;
        font-variant-numeric: tabular-nums;
    }
    .sidebar-footer {
        padding: 0.4rem 0.5rem;
        border-top: 1px solid var(--border);
    }
    .settings-wrapper {
        position: relative;
    }
    .gear-btn {
        width: 28px;
        height: 28px;
        border: none;
        border-radius: 6px;
        background: none;
        color: var(--text-muted);
        cursor: pointer;
        display: flex;
        align-items: center;
        justify-content: center;
        transition:
            background 0.15s,
            color 0.15s;
    }
    .gear-btn:hover {
        background: var(--bg-tertiary);
        color: var(--text-primary);
    }
    .settings-menu {
        position: absolute;
        bottom: 100%;
        left: 0;
        margin-bottom: 4px;
        background: var(--bg-tertiary);
        border: 1px solid var(--border);
        border-radius: 6px;
        padding: 0.25rem 0;
        min-width: 140px;
        z-index: 10;
    }
    .menu-item {
        display: block;
        width: 100%;
        padding: 0.35rem 0.75rem;
        background: none;
        border: none;
        color: var(--text-secondary);
        font-size: 0.7rem;
        text-align: left;
        cursor: pointer;
        transition: background 0.1s;
    }
    .menu-item:hover {
        background: var(--bg-secondary);
        color: var(--text-primary);
    }
    .menu-divider {
        height: 1px;
        background: var(--border);
        margin: 0.2rem 0;
    }
    .gaming-toggle {
        display: flex;
        align-items: center;
        gap: 0.4rem;
    }
    .gaming-toggle.gaming-active {
        color: #6b7280;
    }
    .gaming-label {
        color: #6b7280;
    }
    .gaming-bar {
        background: #6b7280 !important;
    }
    .gaming-text {
        color: #6b7280;
    }
</style>
