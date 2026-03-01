<script lang="ts">
    import { getCurrentWindow } from "@tauri-apps/api/window";

    interface Props {
        activeTab: "chat" | "arena";
        arenaLocked?: boolean;
        onTabChange: (tab: "chat" | "arena") => void;
        onToggleSidebar?: () => void;
    }

    let { activeTab, arenaLocked = false, onTabChange, onToggleSidebar }: Props = $props();

    const win = getCurrentWindow();

    let flashChat = $state(false);

    function handleTabClick(tab: "chat" | "arena") {
        if (tab === "chat" && arenaLocked) {
            flashChat = true;
            setTimeout(() => { flashChat = false; }, 500);
            return;
        }
        onTabChange(tab);
    }

    function minimize() {
        win.minimize();
    }

    function toggleMaximize() {
        win.toggleMaximize();
    }

    function close() {
        win.close();
    }
</script>

<div class="titlebar" data-tauri-drag-region>
    <!-- Left: sidebar toggle -->
    <div class="titlebar-left" data-tauri-drag-region>
        <button
            class="icon-btn"
            onclick={onToggleSidebar}
            title="Toggle sidebar"
            aria-label="Toggle sidebar"
        >
            <svg
                width="16"
                height="16"
                viewBox="0 0 16 16"
                fill="none"
                xmlns="http://www.w3.org/2000/svg"
            >
                <rect
                    x="2"
                    y="3.5"
                    width="12"
                    height="1.5"
                    rx="0.75"
                    fill="currentColor"
                />
                <rect
                    x="2"
                    y="7.25"
                    width="12"
                    height="1.5"
                    rx="0.75"
                    fill="currentColor"
                />
                <rect
                    x="2"
                    y="11"
                    width="12"
                    height="1.5"
                    rx="0.75"
                    fill="currentColor"
                />
            </svg>
        </button>
    </div>

    <!-- Center: tab navigation -->
    <div class="titlebar-center" data-tauri-drag-region>
        <nav class="tabs" aria-label="Navigation">
            <button
                class="tab"
                class:active={activeTab === "chat"}
                class:tab-locked={flashChat}
                onclick={() => handleTabClick("chat")}
            >
                Chat
            </button>
            <button
                class="tab"
                class:active={activeTab === "arena"}
                onclick={() => handleTabClick("arena")}
            >
                Arena
            </button>
        </nav>
    </div>

    <!-- Right: window controls -->
    <div class="titlebar-right">
        <button
            class="win-btn"
            onclick={minimize}
            title="Minimize"
            aria-label="Minimize"
        >
            <svg
                width="10"
                height="1"
                viewBox="0 0 10 1"
                fill="none"
                xmlns="http://www.w3.org/2000/svg"
            >
                <rect width="10" height="1" fill="currentColor" />
            </svg>
        </button>
        <button
            class="win-btn"
            onclick={toggleMaximize}
            title="Maximize"
            aria-label="Maximize"
        >
            <svg
                width="10"
                height="10"
                viewBox="0 0 10 10"
                fill="none"
                xmlns="http://www.w3.org/2000/svg"
            >
                <rect
                    x="0.5"
                    y="0.5"
                    width="9"
                    height="9"
                    stroke="currentColor"
                    stroke-width="1"
                    fill="none"
                />
            </svg>
        </button>
        <button
            class="win-btn close"
            onclick={close}
            title="Close"
            aria-label="Close"
        >
            <svg
                width="10"
                height="10"
                viewBox="0 0 10 10"
                fill="none"
                xmlns="http://www.w3.org/2000/svg"
            >
                <line
                    x1="0.5"
                    y1="0.5"
                    x2="9.5"
                    y2="9.5"
                    stroke="currentColor"
                    stroke-width="1.2"
                    stroke-linecap="round"
                />
                <line
                    x1="9.5"
                    y1="0.5"
                    x2="0.5"
                    y2="9.5"
                    stroke="currentColor"
                    stroke-width="1.2"
                    stroke-linecap="round"
                />
            </svg>
        </button>
    </div>
</div>

<style>
    .titlebar {
        display: flex;
        align-items: center;
        height: 48px;
        background: var(--bg-secondary);
        border-bottom: 1px solid var(--border);
        user-select: none;
        flex-shrink: 0;
    }

    /* Left */
    .titlebar-left {
        display: flex;
        align-items: center;
        padding-left: 8px;
        width: 120px;
        flex-shrink: 0;
    }

    .icon-btn {
        display: flex;
        align-items: center;
        justify-content: center;
        width: 28px;
        height: 28px;
        border: none;
        border-radius: 6px;
        background: transparent;
        color: var(--text-muted);
        cursor: pointer;
        transition:
            background 0.15s,
            color 0.15s;
    }

    .icon-btn:hover {
        background: var(--bg-tertiary);
        color: var(--text-primary);
    }

    /* Center */
    .titlebar-center {
        flex: 1;
        display: flex;
        align-items: center;
        justify-content: center;
        gap: 12px;
    }

    .tabs {
        display: flex;
        align-items: center;
        gap: 2px;
        background: var(--bg-primary);
        border-radius: 8px;
        padding: 2px;
    }

    .tab {
        border: none;
        background: transparent;
        color: var(--text-muted);
        font-size: 12px;
        font-weight: 500;
        padding: 4px 18px;
        border-radius: 6px;
        cursor: pointer;
        transition:
            background 0.15s,
            color 0.15s;
        line-height: 1.4;
    }

    .tab:hover:not(.active) {
        color: var(--text-primary);
        background: var(--bg-tertiary);
    }

    .tab.active {
        background: #f0f0f0;
        color: #1a1a1a;
        font-weight: 600;
    }

    @keyframes flash-locked {
        0%   { background: transparent; color: var(--text-muted); }
        30%  { background: rgba(239,68,68,0.2); color: #ef4444; }
        70%  { background: rgba(239,68,68,0.2); color: #ef4444; }
        100% { background: transparent; color: var(--text-muted); }
    }
    .tab-locked {
        animation: flash-locked 500ms ease forwards;
    }

    /* Right: window controls */
    .titlebar-right {
        display: flex;
        align-items: stretch;
        height: 100%;
        flex-shrink: 0;
    }

    .win-btn {
        display: flex;
        align-items: center;
        justify-content: center;
        width: 46px;
        height: 100%;
        border: none;
        background: transparent;
        color: var(--text-secondary);
        cursor: pointer;
        transition:
            background 0.1s,
            color 0.1s;
    }

    .win-btn:hover {
        background: rgba(255, 255, 255, 0.08);
        color: var(--text-primary);
    }

    .win-btn.close:hover {
        background: #c42b1c;
        color: #fff;
    }
</style>
