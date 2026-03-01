<script lang="ts">
    import { onMount, onDestroy } from "svelte";
    import { listen } from "@tauri-apps/api/event";
    import { invoke } from "@tauri-apps/api/core";
    import { resolveResource } from "@tauri-apps/api/path";
    import TitleBar from "./lib/components/TitleBar.svelte";
    import ResizeHandles from "./lib/components/ResizeHandles.svelte";
    import ArenaView from "./lib/components/ArenaView.svelte";
    import Sidebar from "./lib/components/Sidebar.svelte";
    import ChatArea from "./lib/components/ChatArea.svelte";
    import InputBar from "./lib/components/InputBar.svelte";
    import StatusBar from "./lib/components/StatusBar.svelte";
    import SuggestionsBar from "./lib/components/SuggestionsBar.svelte";
    import * as backend from "./lib/components/stores/pythonBackend.svelte";
    import * as agentsStore from "./lib/components/stores/agents.svelte";
    import * as chat from "./lib/components/stores/chat.svelte";
    import * as gaming from "./lib/components/stores/gaming.svelte";
    import * as watcher from "./lib/components/stores/watcher.svelte";
    import * as arenaStore from "./lib/components/stores/arena.svelte";
    import type {
        IPCRequest,
        AgentsListResponse,
        StatusResponse,
        MemoryInitResponse,
        GamingModeResponse,
        LoadedModel,
    } from "./lib/types/ipc";

    let activeTab = $state<"chat" | "arena">("chat");
    let statusInterval: ReturnType<typeof setInterval> | undefined;
    let ollamaOk = $state(false);
    let qdrantOk = $state(false);
    let loadedModels = $state<LoadedModel[]>([]);
    let vramUsedGb = $state(0);
    let watcherSuggestions = $derived(watcher.getSuggestions());
    let arenaLocked = $derived(
        arenaStore.getPhase() === "running" || arenaStore.getPhase() === "review"
    );

    async function fetchStatus() {
        try {
            const statusRes = (await backend.send(
                { id: crypto.randomUUID(), command: "status" } as IPCRequest,
                15000,
            )) as StatusResponse;
            if (statusRes.status === "ok") {
                ollamaOk = statusRes.ollama;
                qdrantOk = statusRes.qdrant;
                loadedModels = statusRes.loaded_models ?? [];
                vramUsedGb = statusRes.vram_used_gb ?? 0;
                // Update Pyrolith agent status based on Docker availability
                agentsStore.setStatus("pyrolith", statusRes.pyrolith_docker ? "idle" : "offline");
            }
        } catch (e: any) {
            chat.addSystemMessage(`Status refresh failed: ${e?.message || e}`);
        }
    }

    async function handleRefreshStatus() {
        chat.addSystemMessage("Refreshing status...");
        await fetchStatus();
        chat.addSystemMessage(
            `Status: Ollama ${ollamaOk ? "OK" : "OFF"}, Qdrant ${qdrantOk ? "OK" : "OFF"}, VRAM ${vramUsedGb.toFixed(1)} GB, ${loadedModels.length} model(s) loaded.`,
        );
    }

    async function handleMemoryInit() {
        chat.addSystemMessage("Initializing agent memories...");
        try {
            const res = (await backend.send(
                {
                    id: crypto.randomUUID(),
                    command: "memory_init",
                } as IPCRequest,
                120000,
            )) as MemoryInitResponse;
            if (res.status === "ok") {
                chat.addSystemMessage(
                    `Memory initialized: ${res.agents_registered} agents registered.`,
                );
            } else {
                chat.addSystemMessage(
                    `Memory init error: ${res.message ?? "unknown"}`,
                );
            }
        } catch (e: any) {
            chat.addSystemMessage(`Memory init failed: ${e?.message || e}`);
        }
    }

    async function handleToggleGaming() {
        const newState = !gaming.isGaming();
        try {
            const res = (await backend.send(
                {
                    id: crypto.randomUUID(),
                    command: "gaming_mode",
                    enabled: newState,
                } as IPCRequest,
                60000, // 60s: Ollama restart can take ~15s
            )) as GamingModeResponse;
            if (res.status === "ok") {
                gaming.setGaming(res.gaming_mode);
                // Sync tray checkbox with current state
                invoke("sync_tray_gaming", { checked: res.gaming_mode }).catch(
                    () => {},
                );
                if (res.gaming_mode) {
                    chat.addSystemMessage(
                        `Gaming Mode ON — ${res.models_unloaded} model(s) unloaded from VRAM.`,
                    );
                    await watcher.pause();
                } else {
                    chat.addSystemMessage(
                        "Gaming Mode OFF — models will reload on next chat.",
                    );
                    await watcher.resume();
                }
                await fetchStatus();
            } else {
                chat.addSystemMessage(
                    `Gaming mode error: ${res.message ?? "unknown"}`,
                );
            }
        } catch (e: any) {
            chat.addSystemMessage(`Gaming mode failed: ${e?.message || e}`);
        }
    }

    async function handleAcceptSuggestion(id: string) {
        const text = await watcher.acceptSuggestion(id);
        if (text) {
            await chat.sendMessage(text);
        }
    }

    async function handleDismissSuggestion(id: string) {
        await watcher.dismissSuggestion(id);
    }

    onMount(async () => {
        // Listen for tray gaming mode toggle
        listen("tray-gaming-toggle", () => {
            handleToggleGaming();
        });

        try {
            await backend.start();

            // Set project root for filesystem tools
            // resolveResource("") gives src-tauri/, so go up one level to get the project root
            try {
                const tauriDir = await resolveResource("");
                // tauriDir = .../0lith-desktop/src-tauri/ — go up one level
                const projectRoot = tauriDir.replace(
                    /[/\\]src-tauri[/\\]?$/,
                    "",
                );
                await backend.send(
                    {
                        id: crypto.randomUUID(),
                        command: "set_project_root",
                        path: projectRoot,
                    } as IPCRequest,
                    5000,
                );
            } catch {
                console.warn("Could not set project root dynamically");
            }

            // Fetch agents list
            const agentsRes = (await backend.send(
                {
                    id: crypto.randomUUID(),
                    command: "agents_list",
                } as IPCRequest,
                10000,
            )) as AgentsListResponse;
            if (agentsRes.status === "ok" && agentsRes.agents) {
                agentsStore.setAgents(agentsRes.agents);
            }

            // Initial status fetch — slight delay to let Ollama/Qdrant respond
            await new Promise((r) => setTimeout(r, 1500));
            await fetchStatus();

            // Auto-refresh status every 30s
            statusInterval = setInterval(fetchStatus, 30_000);

            // Start background watcher (optional — does not block app)
            try {
                await watcher.start();
            } catch {
                console.warn("Watcher start failed — suggestions disabled");
            }

        } catch (e: any) {
            chat.addSystemMessage(`Connection failed: ${e?.message || e}`);
        }
    });

    onDestroy(() => {
        if (statusInterval !== undefined) clearInterval(statusInterval);
    });
</script>

<ResizeHandles />
<TitleBar {activeTab} {arenaLocked} onTabChange={(t) => (activeTab = t)} />
<div class="app-layout">
    <Sidebar
        {loadedModels}
        {vramUsedGb}
        onRefreshStatus={handleRefreshStatus}
        onMemoryInit={handleMemoryInit}
        onToggleGaming={handleToggleGaming}
    />
    <div class="main-area">
        {#if activeTab === "chat"}
            <ChatArea />
            <SuggestionsBar
                suggestions={watcherSuggestions}
                onAccept={handleAcceptSuggestion}
                onDismiss={handleDismissSuggestion}
            />
            <InputBar />
        {:else}
            <ArenaView />
        {/if}
    </div>
</div>
<StatusBar ollama={ollamaOk} qdrant={qdrantOk} />

<style>
    .app-layout {
        display: flex;
        height: calc(100vh - 72px); /* minus titlebar (48px) + status bar (24px) */
        overflow: hidden;
    }
    .main-area {
        flex: 1;
        display: flex;
        flex-direction: column;
        min-width: 0;
    }
</style>
