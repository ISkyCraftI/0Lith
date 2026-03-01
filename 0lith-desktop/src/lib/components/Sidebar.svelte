<script lang="ts">
    import OLithEye from "./OLithEye.svelte";
    import * as agentsStore from "./stores/agents.svelte";
    import * as chat from "./stores/chat.svelte";
    import * as gaming from "./stores/gaming.svelte";
    import * as sessionsStore from "./stores/sessions.svelte";
    import * as backend from "./stores/pythonBackend.svelte";
    import * as arenaStore from "./stores/arena.svelte";
    import type { Agent, AgentId, AgentStatus, IPCRequest, ChatMessage } from "../types/ipc";

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
    let arenaPhase = $derived(arenaStore.getPhase());
    let arenaActive = $derived(arenaPhase === "running" || arenaPhase === "review");

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

    let sessionsList = $derived(sessionsStore.getSessions());
    let currentSessionId = $derived(sessionsStore.getCurrentSessionId());

    // Fetch sessions on mount
    $effect(() => {
        sessionsStore.fetchSessions();
    });

    function formatRelativeDate(ts: number): string {
        const now = Date.now();
        const diff = now - ts;
        const day = 86400000;
        if (diff < day) return "Aujourd'hui";
        if (diff < day * 2) return "Hier";
        const d = new Date(ts);
        return d.toLocaleDateString("fr-FR", { day: "numeric", month: "short" });
    }

    const AGENT_COLORS: Record<string, string> = {
        hodolith: "#FFB02E",
        monolith: "#181A1E",
        aerolith: "#43AA8B",
        cryolith: "#7BDFF2",
        pyrolith: "#BF0603",
    };
    const AGENT_EMOJIS: Record<string, string> = {
        hodolith: "🟨",
        monolith: "⬛",
        aerolith: "⬜",
        cryolith: "🟦",
        pyrolith: "🟥",
    };
    const AGENT_NAMES: Record<string, string> = {
        hodolith: "Hodolith",
        monolith: "Monolith",
        aerolith: "Aerolith",
        cryolith: "Cryolith",
        pyrolith: "Pyrolith",
    };

    async function handleSelectSession(sessionId: string) {
        if (sessionId === currentSessionId) return;
        const rawMessages = await sessionsStore.loadSession(sessionId);
        if (!rawMessages) return;

        // Clear backend conversation history before loading a different session
        backend.send(
            { id: crypto.randomUUID(), command: "clear_history" } as IPCRequest,
            5000,
        ).catch(() => {});

        // Map backend messages to ChatMessage format with agent metadata
        const mapped: ChatMessage[] = rawMessages.map((m: any) => ({
            id: crypto.randomUUID(),
            type: m.type ?? "user",
            content: m.content ?? "",
            timestamp: m.timestamp ?? Date.now(),
            agentId: m.agent_id as AgentId | undefined,
            agentName: m.agent_name ?? (m.agent_id ? AGENT_NAMES[m.agent_id] : undefined),
            agentColor: m.agent_color ?? (m.agent_id ? AGENT_COLORS[m.agent_id] : undefined),
            agentEmoji: m.agent_emoji ?? (m.agent_id ? AGENT_EMOJIS[m.agent_id] : undefined),
        }));

        chat.loadSessionMessages(mapped);
    }

    async function handleNewSession() {
        // Clear backend conversation history
        backend.send(
            { id: crypto.randomUUID(), command: "clear_history" } as IPCRequest,
            5000,
        ).catch(() => {});

        const id = await sessionsStore.newSession();
        if (id) {
            chat.loadSessionMessages([]); // Clear without triggering clearMessages() side-effects
        }

        // Focus the input bar
        setTimeout(() => {
            const textarea = document.querySelector<HTMLTextAreaElement>(".input-bar textarea");
            textarea?.focus();
        }, 50);
    }
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
            {@const isArenaFighter = arenaActive && (agent.id === "pyrolith" || agent.id === "cryolith")}
            <div class="agent-item" class:active={isActive}>
                <OLithEye size={28} agentColor={agent.color} animated={false} />
                <div class="agent-info">
                    <div class="agent-name">{agent.name}</div>
                    <div class="agent-meta">
                        <span class="agent-role">{agent.role}</span>
                        {#if isArenaFighter}
                            <span class="arena-badge" title="Actif dans l'Arena">ARENA</span>
                        {:else if loaded}
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

    <!-- Session history -->
    <div class="history-header">
        <span class="history-label">Historique</span>
        <button class="new-session-btn" onclick={handleNewSession} title="Nouvelle conversation">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <line x1="12" y1="5" x2="12" y2="19" /><line x1="5" y1="12" x2="19" y2="12" />
            </svg>
        </button>
    </div>

    <div class="sessions-list">
        {#if sessionsList.length === 0}
            <div class="no-sessions">Aucune conversation</div>
        {:else}
            {#each sessionsList.slice(0, 20) as session (session.session_id)}
                <button
                    class="session-item"
                    class:session-active={session.session_id === currentSessionId}
                    onclick={() => handleSelectSession(session.session_id)}
                >
                    <div class="session-preview">{session.preview.length > 60 ? session.preview.slice(0, 60) + "…" : session.preview}</div>
                    <div class="session-meta">
                        <span class="session-date">{formatRelativeDate(session.updated_at)}</span>
                        <span class="session-count">{session.message_count} msg</span>
                    </div>
                </button>
            {/each}
        {/if}
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

        {#if arenaActive}
            <div class="arena-vram-section">
                <div class="arena-vram-label">Arena en cours</div>
                <div class="arena-vram-row">
                    <span class="arena-dot arena-dot-red"></span>
                    <span class="arena-vram-name">Pyrolith</span>
                    <span class="arena-vram-info">Docker :11435 · ~5 GB</span>
                </div>
                <div class="arena-vram-row">
                    <span class="arena-dot arena-dot-blue"></span>
                    <span class="arena-vram-name">Cryolith</span>
                    <span class="arena-vram-info">Foundation-Sec · ~5 GB</span>
                </div>
            </div>
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
    .arena-badge {
        font-size: 0.55rem;
        padding: 0px 4px;
        border-radius: 3px;
        background: rgba(234, 88, 12, 0.2);
        color: #ea580c;
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
    .arena-vram-section {
        margin-top: 0.5rem;
        padding-top: 0.5rem;
        border-top: 1px solid var(--border);
    }
    .arena-vram-label {
        font-size: 0.6rem;
        color: #ea580c;
        text-transform: uppercase;
        letter-spacing: 0.08em;
        margin-bottom: 0.3rem;
        font-weight: 600;
    }
    .arena-vram-row {
        display: flex;
        align-items: center;
        gap: 5px;
        padding: 1px 0;
    }
    .arena-dot {
        width: 5px;
        height: 5px;
        border-radius: 50%;
        flex-shrink: 0;
    }
    .arena-dot-red  { background: #ef4444; }
    .arena-dot-blue { background: #0ea5e9; }
    .arena-vram-name {
        font-size: 0.65rem;
        color: var(--text-secondary);
        font-weight: 600;
        min-width: 55px;
    }
    .arena-vram-info {
        font-size: 0.55rem;
        color: var(--text-muted);
        font-variant-numeric: tabular-nums;
    }
    .gaming-bar {
        background: #6b7280 !important;
    }
    .gaming-text {
        color: #6b7280;
    }

    /* ── Session history ── */
    .history-header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 0.75rem 1rem 0.25rem;
        border-top: 1px solid var(--border);
    }
    .history-label {
        font-size: 0.65rem;
        color: var(--text-muted);
        text-transform: uppercase;
        letter-spacing: 0.1em;
    }
    .new-session-btn {
        width: 22px;
        height: 22px;
        border: none;
        border-radius: 4px;
        background: none;
        color: var(--text-muted);
        cursor: pointer;
        display: flex;
        align-items: center;
        justify-content: center;
        transition: background 0.15s, color 0.15s;
    }
    .new-session-btn:hover {
        background: var(--bg-tertiary);
        color: var(--text-primary);
    }
    .sessions-list {
        flex: 1;
        overflow-y: auto;
        padding: 0.25rem 0.5rem;
        min-height: 0;
    }
    .no-sessions {
        font-size: 0.7rem;
        color: var(--text-muted);
        padding: 0.5rem;
        text-align: center;
        opacity: 0.6;
    }
    .session-item {
        display: block;
        width: 100%;
        padding: 0.4rem 0.5rem;
        border: none;
        border-left: 2px solid transparent;
        border-radius: 4px;
        background: none;
        color: var(--text-secondary);
        text-align: left;
        cursor: pointer;
        transition: background 0.15s, border-color 0.15s;
        margin-bottom: 1px;
    }
    .session-item:hover {
        background: var(--bg-tertiary);
    }
    .session-item.session-active {
        background: #3A3F4B;
        border-left-color: var(--text-primary);
    }
    .session-preview {
        font-size: 0.75rem;
        line-height: 1.3;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
    }
    .session-meta {
        display: flex;
        align-items: center;
        gap: 0.4rem;
        margin-top: 0.15rem;
    }
    .session-date {
        font-size: 0.6rem;
        color: var(--text-muted);
    }
    .session-count {
        font-size: 0.55rem;
        color: var(--text-muted);
        opacity: 0.7;
    }
</style>
