<script lang="ts">
    import { tick } from "svelte";
    import * as purple from "../purple_ipc";
    import type { PurpleStreamEvent, PurpleMatchResultData } from "../purple_ipc";

    // ── Props ─────────────────────────────────────────────────────────────────
    interface Props { modelNames?: string[] }
    let { modelNames = [] }: Props = $props();

    // ── Default models ────────────────────────────────────────────────────────
    const DEFAULT_RED  = "deephat/DeepHat-V1-7B:latest";
    const DEFAULT_BLUE = "hf.co/fdtn-ai/Foundation-Sec-8B-Q4_K_M-GGUF:latest";
    const FALLBACK     = "qwen3:14b";

    function allModels(): string[] {
        const base = [DEFAULT_RED, DEFAULT_BLUE, FALLBACK, "qwen3:1.7b"];
        return [...new Set([...base, ...modelNames])];
    }

    // ── Panel phase ───────────────────────────────────────────────────────────
    type PanelPhase = "idle" | "generating" | "running" | "done";
    let panelPhase = $state<PanelPhase>("idle");

    // ── Config ────────────────────────────────────────────────────────────────
    let difficulty = $state<"easy" | "medium" | "hard">("medium");
    let seedInput  = $state("");
    let redModel   = $state(DEFAULT_RED);
    let blueModel  = $state(DEFAULT_BLUE);

    // ── Scenario preview ──────────────────────────────────────────────────────
    let scenarioInfo = $state<purple.PurpleScenarioInfo | null>(null);

    // ── Match tracking ────────────────────────────────────────────────────────
    let matchId      = $state<string | null>(null);
    let matchPhase   = $state("");
    let currentRound = $state(0);
    let totalRounds  = $state(6);
    let matchResult  = $state<PurpleMatchResultData | null>(null);
    let errorMsg     = $state("");

    // ── Log entries ───────────────────────────────────────────────────────────
    interface LogEntry {
        time:     string;
        phase:    string;
        round?:   number;
        team?:    "red" | "blue" | "sys";
        content:  string;
        moveType?: string;
    }
    let logs       = $state<LogEntry[]>([]);
    let logScrollEl = $state<HTMLElement | null>(null);

    $effect(() => {
        const _ = logs.length;
        tick().then(() => {
            if (logScrollEl) logScrollEl.scrollTop = logScrollEl.scrollHeight;
        });
    });

    // ── Chrono ────────────────────────────────────────────────────────────────
    let elapsed  = $state(0);
    let chronoId = $state<ReturnType<typeof setInterval> | null>(null);

    $effect(() => {
        if (panelPhase === "running") {
            if (!chronoId) {
                elapsed = 0;
                chronoId = setInterval(() => { elapsed += 1; }, 1000);
            }
        } else {
            if (chronoId) { clearInterval(chronoId); chronoId = null; }
        }
        return () => { if (chronoId) clearInterval(chronoId); };
    });

    function fmt(s: number): string {
        const m = Math.floor(s / 60).toString().padStart(2, "0");
        return `${m}:${(s % 60).toString().padStart(2, "0")}`;
    }

    function hhmm(): string {
        const d = new Date();
        return [d.getHours(), d.getMinutes(), d.getSeconds()]
            .map(n => n.toString().padStart(2, "0")).join(":");
    }

    function addLog(phase: string, round: number | undefined,
                    team: LogEntry["team"], content: string, moveType?: string) {
        logs = [...logs, { time: hhmm(), phase, round, team, content, moveType }];
    }

    // ── Streaming events ──────────────────────────────────────────────────────
    function handleStream(ev: PurpleStreamEvent) {
        if (ev.phase)              matchPhase   = ev.phase;
        if (ev.round !== undefined) currentRound = ev.round;
        if (ev.total_rounds)        totalRounds  = ev.total_rounds;

        switch (ev.event) {
            case "match_started":
                addLog("SETUP", undefined, "sys",
                    `Match ${ev.match_id?.slice(0,8)} · seed ${ev.scenario_seed ?? "?"} · ${ev.difficulty ?? difficulty}`);
                break;

            case "round_started":
                addLog(ev.phase ?? "", ev.round, "sys",
                    `──── Round ${ev.round ?? "?"} · ${ev.phase ?? ""} ────`);
                break;

            case "match_complete":
                if (ev.result) matchResult = ev.result as PurpleMatchResultData;
                addLog("FIN", undefined, "sys", "Match terminé.");
                panelPhase = "done";
                break;

            case "match_error":
                errorMsg   = ev.error ?? "Erreur inconnue";
                panelPhase = "done";
                addLog("ERR", undefined, "sys", errorMsg);
                break;

            case "match_timeout":
                errorMsg   = "Timeout — 60 min dépassées";
                panelPhase = "done";
                addLog("ERR", undefined, "sys", errorMsg);
                break;

            default: {
                const raw = ev as Record<string, unknown>;
                if (raw["red_move"]) {
                    const m = raw["red_move"] as Record<string, unknown>;
                    addLog(ev.phase ?? matchPhase, ev.round, "red",
                        String(m["content"] ?? "").slice(0, 300),
                        String(m["move_type"] ?? ""));
                }
                if (raw["blue_move"]) {
                    const m = raw["blue_move"] as Record<string, unknown>;
                    addLog(ev.phase ?? matchPhase, ev.round, "blue",
                        String(m["content"] ?? "").slice(0, 300),
                        String(m["move_type"] ?? ""));
                }
            }
        }
    }

    // ── Handlers ──────────────────────────────────────────────────────────────
    async function handleStart() {
        panelPhase   = "generating";
        logs         = [];
        matchResult  = null;
        errorMsg     = "";
        currentRound = 0;
        matchPhase   = "";
        const seed   = seedInput.trim() ? parseInt(seedInput, 10) : undefined;

        try {
            scenarioInfo = (await purple.generateScenario({ difficulty, seed })).scenario;
        } catch { scenarioInfo = null; }

        panelPhase = "running";
        try {
            const res = await purple.startMatch(
                {
                    seed,
                    difficulty,
                    sparring_token: "",  // PURPLE_SKIP_TOKEN=1 en dev
                    skip_safety: true,
                },
                handleStream,
            );
            matchId = res.match_id;
        } catch (e: unknown) {
            errorMsg   = e instanceof Error ? e.message : String(e);
            panelPhase = "done";
        }
    }

    async function handleStop() {
        try { await purple.stopMatch(); } catch { /* ignore */ }
    }

    function handleReset() {
        purple.stop().catch(() => {});
        panelPhase   = "idle";
        logs         = [];
        matchResult  = null;
        errorMsg     = "";
        elapsed      = 0;
        matchId      = null;
        scenarioInfo = null;
        currentRound = 0;
        matchPhase   = "";
    }

    // ── Export ────────────────────────────────────────────────────────────────
    let exportTooltip = $state(false);
    function handleExport() {
        exportTooltip = true;
        setTimeout(() => { exportTooltip = false; }, 3000);
    }

    // ── Helpers ───────────────────────────────────────────────────────────────
    const PHASE_COLS: Record<string, string> = {
        RECON: "#EF4444", EXPLOITATION: "#F97316", DEFENSE: "#3B82F6",
        REMEDIATION: "#06B6D4", POST_EXPLOIT: "#8B5CF6",
        ASSESSMENT: "#A3E635", SETUP: "#6B7280",
    };
    function phaseColor(p: string): string {
        return PHASE_COLS[p.toUpperCase()] ?? "#6B7280";
    }

    function badgeLabel(): string {
        if (errorMsg && panelPhase === "done") return "ERREUR";
        const map: Record<PanelPhase, string> = {
            idle: "IDLE", generating: "GÉNÉRATION",
            running: "MATCH EN COURS", done: "TERMINÉ",
        };
        return map[panelPhase];
    }

    function scoreBar(n: number): string { return `${Math.min(100, Math.max(0, n))}%`; }

    function asNum(v: unknown): number {
        return typeof v === "number" ? v : 0;
    }
    function asBool(v: unknown): boolean { return !!v; }

    let dpoCount = $derived(
        matchResult
            ? (Array.isArray((matchResult as Record<string,unknown>)["dpo_pairs"])
                ? ((matchResult as Record<string,unknown>)["dpo_pairs"] as unknown[]).length
                : (asNum((matchResult as Record<string,unknown>)["dpo_pairs_count"])))
            : 0
    );

    function pct(n: number): string { return `${(n * 100).toFixed(0)} %`; }

    // Progress bar percent for running match (phases are sequential)
    const PHASES_ORDER = ["SETUP", "RECON", "EXPLOITATION", "DEFENSE", "REMEDIATION", "POST_EXPLOIT", "ASSESSMENT"];
    let phaseProgress = $derived(
        Math.round(((PHASES_ORDER.indexOf(matchPhase.toUpperCase()) + 1) / PHASES_ORDER.length) * 100)
    );
</script>

<!-- ─────────────────────────────────────────────────────────────────────── -->
<!-- HEADER                                                                  -->
<!-- ─────────────────────────────────────────────────────────────────────── -->
<div class="pp-wrap">
<div class="pp-header">
    <div class="pp-title-row">
        <!-- Shield + crossed-swords icon -->
        <svg class="pp-icon" width="22" height="22" viewBox="0 0 24 24" fill="none"
             xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
            <path d="M12 3 L20 7 V13 C20 17.4 16.4 21.2 12 22 C7.6 21.2 4 17.4 4 13 V7 Z"
                  fill="#7C3AED" opacity="0.3" stroke="#7C3AED" stroke-width="1.5" stroke-linejoin="round"/>
            <line x1="9"  y1="9"  x2="15" y2="15" stroke="#EF4444" stroke-width="1.5" stroke-linecap="round"/>
            <line x1="15" y1="9"  x2="9"  y2="15" stroke="#0EA5E9" stroke-width="1.5" stroke-linecap="round"/>
        </svg>
        <div>
            <span class="pp-title">Purple Team</span>
            <span class="pp-subtitle">Cyber Range</span>
        </div>
    </div>
    <span class="status-badge"
          class:badge-idle={panelPhase === "idle"}
          class:badge-gen={panelPhase === "generating"}
          class:badge-run={panelPhase === "running"}
          class:badge-done={panelPhase === "done" && !errorMsg}
          class:badge-err={!!errorMsg && panelPhase === "done"}>
        {badgeLabel()}
    </span>
</div>

<!-- ─────────────────────────────────────────────────────────────────────── -->
<!-- IDLE — CONFIG                                                           -->
<!-- ─────────────────────────────────────────────────────────────────────── -->
{#if panelPhase === "idle" || panelPhase === "generating"}
<div class="pp-body pp-config">

    <!-- Difficulty pills -->
    <div class="cfg-section">
        <span class="cfg-label" id="diff-label">Difficulté</span>
        <div class="diff-pills" role="group" aria-labelledby="diff-label">
            {#each (["easy","medium","hard"] as const) as d}
                <button
                    class="diff-pill"
                    class:pill-active={difficulty === d}
                    onclick={() => { difficulty = d; }}
                    disabled={panelPhase === "generating"}
                >
                    {d === "easy" ? "Easy" : d === "medium" ? "Medium" : "Hard"}
                </button>
            {/each}
        </div>
    </div>

    <!-- Seed -->
    <div class="cfg-section cfg-row">
        <label class="cfg-label" for="pp-seed">Seed</label>
        <input
            id="pp-seed"
            class="cfg-input"
            type="number"
            min="0"
            placeholder="Aléatoire"
            bind:value={seedInput}
            disabled={panelPhase === "generating"}
        />
    </div>

    <!-- Model selectors -->
    <div class="cfg-section cfg-row">
        <label class="cfg-label" for="pp-red-model">
            <span class="dot-red"></span>Red
        </label>
        <select id="pp-red-model" class="cfg-select" bind:value={redModel}
                disabled={panelPhase === "generating"}>
            {#each allModels() as m}
                <option value={m}>{m}</option>
            {/each}
        </select>
    </div>
    <div class="cfg-section cfg-row">
        <label class="cfg-label" for="pp-blue-model">
            <span class="dot-blue"></span>Blue
        </label>
        <select id="pp-blue-model" class="cfg-select" bind:value={blueModel}
                disabled={panelPhase === "generating"}>
            {#each allModels() as m}
                <option value={m}>{m}</option>
            {/each}
        </select>
    </div>

    <p class="cfg-note">
        Les modèles sont sélectionnés via env vars <code>PURPLE_RED_MODEL</code> /
        <code>PURPLE_BLUE_MODEL</code>. Assurez-vous que <code>PURPLE_SKIP_TOKEN=1</code>
        est activé en développement.
    </p>

    <!-- Launch button -->
    <button class="launch-btn" onclick={handleStart}
            disabled={panelPhase === "generating"}>
        {#if panelPhase === "generating"}
            <span class="btn-spinner"></span>
            Génération du scénario…
        {:else}
            <svg width="13" height="13" viewBox="0 0 13 13" fill="currentColor" aria-hidden="true">
                <polygon points="2,1 12,6.5 2,12"/>
            </svg>
            Lancer le match
        {/if}
    </button>

    <!-- Scenario preview (after generation) -->
    {#if scenarioInfo && panelPhase === "generating"}
        <div class="scenario-preview">
            <div class="prev-title">Scénario généré</div>
            <div class="prev-row"><span class="prev-key">Objectif</span><span>{scenarioInfo.objective}</span></div>
            <div class="prev-row"><span class="prev-key">Services</span><span>{scenarioInfo.services.join(", ")}</span></div>
            <div class="prev-row"><span class="prev-key">MITRE</span><span>{scenarioInfo.mitre_techniques.join(" · ")}</span></div>
        </div>
    {/if}

</div>

<!-- ─────────────────────────────────────────────────────────────────────── -->
<!-- RUNNING — MATCH VIEW                                                    -->
<!-- ─────────────────────────────────────────────────────────────────────── -->
{:else if panelPhase === "running"}
<div class="pp-body pp-running">

    <!-- Progress header -->
    <div class="run-header">
        <div class="run-left">
            <span class="run-phase" style="color: {phaseColor(matchPhase)}">{matchPhase || "SETUP"}</span>
            <span class="run-round">Round {currentRound}/{totalRounds}</span>
            <span class="run-chrono">{fmt(elapsed)}</span>
        </div>
        <button class="stop-btn" onclick={handleStop}>■ Arrêter</button>
    </div>

    <!-- Phase progress bar -->
    <div class="phase-bar">
        <div class="phase-fill" style="width: {phaseProgress}%;
             background: {phaseColor(matchPhase)};"></div>
    </div>

    <!-- Scenario info strip -->
    {#if scenarioInfo}
        <div class="scenario-strip">
            <span class="strip-obj">{scenarioInfo.objective}</span>
            <span class="strip-sep">·</span>
            <span class="strip-svcs">{scenarioInfo.services.join(", ")}</span>
        </div>
    {/if}

    <!-- Live log -->
    <div class="log-zone" bind:this={logScrollEl}>
        {#each logs as entry (entry.time + entry.team + entry.round)}
            <div class="log-line"
                 class:log-red={entry.team === "red"}
                 class:log-blue={entry.team === "blue"}
                 class:log-sys={entry.team === "sys"}>
                <span class="log-ts">{entry.time}</span>
                {#if entry.round}
                    <span class="log-rnd">R{entry.round}</span>
                {/if}
                {#if entry.phase}
                    <span class="log-phase" style="color: {phaseColor(entry.phase)}">
                        {entry.phase}
                    </span>
                {/if}
                {#if entry.moveType}
                    <span class="log-move">[{entry.moveType}]</span>
                {/if}
                <span class="log-content">{entry.content}</span>
            </div>
        {/each}
        {#if logs.length === 0}
            <div class="log-wait">Démarrage du match<span class="dots">...</span></div>
        {/if}
    </div>

</div>

<!-- ─────────────────────────────────────────────────────────────────────── -->
<!-- DONE — RESULTS                                                          -->
<!-- ─────────────────────────────────────────────────────────────────────── -->
{:else if panelPhase === "done"}
<div class="pp-body pp-results" role="region" aria-label="Résultats du match">

    {#if errorMsg && !matchResult}
        <!-- Error state -->
        <div class="result-error">
            <span class="err-icon">⚠</span>
            <span>{errorMsg}</span>
        </div>
        <button class="reset-btn" onclick={handleReset}>← Nouveau match</button>
    {:else if matchResult}
        <!-- Winner banner -->
        {@const winner = matchResult.winner}
        {@const rs = matchResult.red_score}
        {@const bs = matchResult.blue_score}
        <div class="winner-banner"
             class:banner-red={winner === "red"}
             class:banner-blue={winner === "blue"}
             class:banner-draw={winner === "draw"}>
            {#if winner === "red"}
                🏆 <strong>Pyrolith (Red)</strong> remporte le match
            {:else if winner === "blue"}
                🏆 <strong>Cryolith (Blue)</strong> remporte le match
            {:else}
                ⚖ Égalité
            {/if}
        </div>

        <!-- Score bars -->
        <div class="score-section">
            <div class="score-row">
                <span class="score-label red-name">Red</span>
                <div class="score-track">
                    <div class="score-fill fill-red" style="width: {scoreBar(asNum(rs?.total))}"></div>
                </div>
                <span class="score-num red-name">{asNum(rs?.total).toFixed(0)}</span>
            </div>
            <div class="score-row">
                <span class="score-label blue-name">Blue</span>
                <div class="score-track">
                    <div class="score-fill fill-blue" style="width: {scoreBar(asNum(bs?.total))}"></div>
                </div>
                <span class="score-num blue-name">{asNum(bs?.total).toFixed(0)}</span>
            </div>
        </div>

        <!-- Metric cards -->
        <div class="metric-cards">
            <!-- Red metrics -->
            <div class="metric-card metric-red">
                <div class="card-title red-name">⚔ Red Team — Pyrolith</div>
                <div class="metric-row">
                    <span class="met-label">Objectif atteint</span>
                    <span class="met-val">{asBool(rs?.objective_achieved) ? "✅" : "❌"}</span>
                </div>
                <div class="metric-row">
                    <span class="met-label">Services compromis</span>
                    <span class="met-val">{asNum(rs?.services_compromised)}</span>
                </div>
                <div class="metric-row">
                    <span class="met-label">Évasion détection</span>
                    <span class="met-val">{pct(asNum(rs?.detection_evasion))}</span>
                </div>
                <div class="metric-row">
                    <span class="met-label">Diversité techniques</span>
                    <span class="met-val">{asNum(rs?.technique_diversity)} types</span>
                </div>
                <div class="metric-row met-penalty">
                    <span class="met-label">Pénalités</span>
                    <span class="met-val">−{asNum(rs?.penalties).toFixed(0)} pts</span>
                </div>
            </div>

            <!-- Blue metrics -->
            <div class="metric-card metric-blue">
                <div class="card-title blue-name">🛡 Blue Team — Cryolith</div>
                <div class="metric-row">
                    <span class="met-label">Intrusion détectée</span>
                    <span class="met-val">{asBool(bs?.detected) ? "✅" : "❌"}</span>
                </div>
                <div class="metric-row">
                    <span class="met-label">Règles Sigma valides</span>
                    <span class="met-val">{asNum(bs?.sigma_valid)} ({asNum(bs?.sigma_matching)} match)</span>
                </div>
                <div class="metric-row">
                    <span class="met-label">Patch proposé</span>
                    <span class="met-val">{asBool(bs?.patch_proposed) ? "✅" : "❌"}</span>
                </div>
                <div class="metric-row">
                    <span class="met-label">Patch efficace</span>
                    <span class="met-val">{asBool(bs?.patch_effective) ? "✅" : "❌"}</span>
                </div>
                <div class="metric-row">
                    <span class="met-label">Faux positifs</span>
                    <span class="met-val">{asNum(bs?.false_positives)}</span>
                </div>
            </div>
        </div>

        <!-- DPO export count -->
        {#if dpoCount > 0}
            <div class="dpo-banner">
                📊 <strong>{dpoCount}</strong> paire{dpoCount > 1 ? "s" : ""} DPO exportée{dpoCount > 1 ? "s" : ""}
                pour l'entraînement → <code>~/.0lith/dpo_data/</code>
            </div>
        {/if}

        <!-- Log replay (collapsible) -->
        {#if logs.length > 0}
            <details class="log-detail">
                <summary>Log du match ({logs.length} entrées)</summary>
                <div class="log-zone log-zone-sm" bind:this={logScrollEl}>
                    {#each logs as entry (entry.time + entry.team + entry.round)}
                        <div class="log-line"
                             class:log-red={entry.team === "red"}
                             class:log-blue={entry.team === "blue"}
                             class:log-sys={entry.team === "sys"}>
                            <span class="log-ts">{entry.time}</span>
                            {#if entry.round}<span class="log-rnd">R{entry.round}</span>{/if}
                            {#if entry.phase}<span class="log-phase" style="color:{phaseColor(entry.phase)}">{entry.phase}</span>{/if}
                            {#if entry.moveType}<span class="log-move">[{entry.moveType}]</span>{/if}
                            <span class="log-content">{entry.content}</span>
                        </div>
                    {/each}
                </div>
            </details>
        {/if}

        <!-- Actions -->
        <div class="result-actions">
            <button class="launch-btn" onclick={handleReset}>▶ Nouveau match</button>
            <div class="export-wrap">
                <button class="export-btn" onclick={handleExport}>Exporter logs</button>
                {#if exportTooltip}
                    <span class="export-tooltip">~/.0lith/arena_logs/</span>
                {/if}
            </div>
        </div>
    {:else}
        <!-- Match finished without result (cancelled early) -->
        <div class="result-error">Match annulé ou résultat indisponible.</div>
        <button class="reset-btn" onclick={handleReset}>← Retour</button>
    {/if}

</div>
{/if}
</div>

<!-- ─────────────────────────────────────────────────────────────────────── -->
<!-- STYLES                                                                  -->
<!-- ─────────────────────────────────────────────────────────────────────── -->
<style>
    /* ── Wrapper ──────────────────────────────────────────────────────────── */
    .pp-wrap {
        flex: 1;
        display: flex;
        flex-direction: column;
        background: var(--bg-primary, #282C33);
        overflow: hidden;
        min-height: 0;
        color: #d1d5db;
        font-size: 13px;
    }

    /* ── Header ───────────────────────────────────────────────────────────── */
    .pp-header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 10px 16px;
        background: var(--bg-secondary, #2F343E);
        border-bottom: 1px solid #3a3f4b;
        flex-shrink: 0;
    }
    .pp-title-row {
        display: flex;
        align-items: center;
        gap: 10px;
    }
    .pp-icon { flex-shrink: 0; }
    .pp-title {
        font-size: 15px;
        font-weight: 600;
        color: #e5e7eb;
    }
    .pp-subtitle {
        margin-left: 6px;
        font-size: 11px;
        color: #6b7280;
        text-transform: uppercase;
        letter-spacing: 0.06em;
    }

    /* ── Status badge ─────────────────────────────────────────────────────── */
    .status-badge {
        font-size: 10px;
        font-weight: 700;
        letter-spacing: 0.08em;
        padding: 3px 8px;
        border-radius: 4px;
        text-transform: uppercase;
    }
    .badge-idle { background: #374151; color: #9ca3af; }
    .badge-gen  { background: #1e3a5f; color: #60a5fa; }
    .badge-run  { background: #3b1e40; color: #c084fc; animation: pulse 2s infinite; }
    .badge-done { background: #14532d; color: #4ade80; }
    .badge-err  { background: #450a0a; color: #f87171; }

    @keyframes pulse {
        0%, 100% { opacity: 1; }
        50%       { opacity: 0.65; }
    }

    /* ── Shared body ──────────────────────────────────────────────────────── */
    .pp-body {
        flex: 1;
        overflow-y: auto;
        padding: 20px 20px 24px;
        display: flex;
        flex-direction: column;
        gap: 14px;
        min-height: 0;
    }

    /* ── Config panel ─────────────────────────────────────────────────────── */
    .pp-config { max-width: 520px; align-self: center; width: 100%; }

    .cfg-section { display: flex; flex-direction: column; gap: 6px; }
    .cfg-row { flex-direction: row; align-items: center; gap: 10px; }
    .cfg-label {
        font-size: 11px;
        font-weight: 600;
        color: #9ca3af;
        text-transform: uppercase;
        letter-spacing: 0.06em;
        min-width: 64px;
    }

    .diff-pills { display: flex; gap: 6px; }
    .diff-pill {
        padding: 5px 16px;
        border-radius: 6px;
        border: 1px solid #4b5563;
        background: transparent;
        color: #9ca3af;
        cursor: pointer;
        font-size: 12px;
        font-weight: 500;
        transition: all 0.15s;
    }
    .diff-pill:hover:not(:disabled) { border-color: #7C3AED; color: #c4b5fd; }
    .diff-pill.pill-active { background: #7C3AED; border-color: #7C3AED; color: #fff; }
    .diff-pill:disabled { opacity: 0.5; cursor: default; }

    .cfg-input, .cfg-select {
        flex: 1;
        background: var(--bg-tertiary, #3A3F4B);
        border: 1px solid #4b5563;
        border-radius: 6px;
        color: #e5e7eb;
        padding: 6px 10px;
        font-size: 12px;
        outline: none;
        min-width: 0;
    }
    .cfg-input:focus, .cfg-select:focus { border-color: #7C3AED; }
    .cfg-input::placeholder { color: #6b7280; }
    .cfg-select option { background: #2F343E; }
    .cfg-input:disabled, .cfg-select:disabled { opacity: 0.5; }

    .dot-red, .dot-blue {
        display: inline-block;
        width: 8px;
        height: 8px;
        border-radius: 50%;
        margin-right: 4px;
        vertical-align: middle;
    }
    .dot-red  { background: #EF4444; }
    .dot-blue { background: #0EA5E9; }

    .cfg-note {
        font-size: 11px;
        color: #6b7280;
        line-height: 1.5;
        background: rgba(255,255,255,0.03);
        border: 1px solid #374151;
        border-radius: 6px;
        padding: 8px 10px;
    }
    .cfg-note code { color: #a5b4fc; font-size: 10.5px; }

    /* ── Launch / reset buttons ───────────────────────────────────────────── */
    .launch-btn {
        display: flex;
        align-items: center;
        justify-content: center;
        gap: 7px;
        padding: 9px 20px;
        background: #15803d;
        border: none;
        border-radius: 7px;
        color: #fff;
        font-size: 13px;
        font-weight: 600;
        cursor: pointer;
        transition: background 0.15s;
        align-self: flex-start;
    }
    .launch-btn:hover:not(:disabled) { background: #166534; }
    .launch-btn:disabled { opacity: 0.6; cursor: default; }

    .reset-btn {
        padding: 7px 14px;
        background: transparent;
        border: 1px solid #4b5563;
        border-radius: 6px;
        color: #9ca3af;
        font-size: 12px;
        cursor: pointer;
        transition: border-color 0.15s;
        align-self: flex-start;
    }
    .reset-btn:hover { border-color: #7C3AED; color: #c4b5fd; }

    .btn-spinner {
        width: 12px; height: 12px;
        border: 2px solid #ffffff40;
        border-top-color: #fff;
        border-radius: 50%;
        animation: spin 0.7s linear infinite;
        flex-shrink: 0;
    }
    @keyframes spin { to { transform: rotate(360deg); } }

    /* ── Scenario preview ─────────────────────────────────────────────────── */
    .scenario-preview {
        background: rgba(124,58,237,0.1);
        border: 1px solid rgba(124,58,237,0.35);
        border-radius: 8px;
        padding: 12px 14px;
        display: flex;
        flex-direction: column;
        gap: 5px;
    }
    .prev-title { font-size: 11px; font-weight: 700; color: #c4b5fd; text-transform: uppercase; letter-spacing: 0.08em; margin-bottom: 2px; }
    .prev-row { display: flex; gap: 8px; font-size: 12px; }
    .prev-key { color: #9ca3af; min-width: 72px; flex-shrink: 0; }

    /* ── Running panel ────────────────────────────────────────────────────── */
    .pp-running { gap: 10px; }

    .run-header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        flex-shrink: 0;
    }
    .run-left { display: flex; align-items: center; gap: 10px; }
    .run-phase { font-size: 12px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.06em; }
    .run-round { font-size: 12px; color: #9ca3af; }
    .run-chrono { font-size: 13px; font-weight: 600; color: #e5e7eb; font-variant-numeric: tabular-nums; }

    .stop-btn {
        padding: 6px 14px;
        background: #7f1d1d;
        border: 1px solid #991b1b;
        border-radius: 6px;
        color: #fca5a5;
        font-size: 12px;
        font-weight: 600;
        cursor: pointer;
        transition: background 0.15s;
    }
    .stop-btn:hover { background: #991b1b; }

    .phase-bar {
        height: 3px;
        background: #374151;
        border-radius: 2px;
        overflow: hidden;
        flex-shrink: 0;
    }
    .phase-fill {
        height: 100%;
        border-radius: 2px;
        transition: width 0.6s ease, background 0.4s;
    }

    .scenario-strip {
        font-size: 11px;
        color: #6b7280;
        display: flex;
        gap: 6px;
        flex-wrap: wrap;
        flex-shrink: 0;
    }
    .strip-sep { color: #4b5563; }

    /* ── Log zone ─────────────────────────────────────────────────────────── */
    .log-zone {
        flex: 1;
        overflow-y: auto;
        background: #1a1d23;
        border: 1px solid #2d3139;
        border-radius: 8px;
        padding: 10px;
        font-family: "Cascadia Code", "Fira Code", monospace;
        font-size: 11.5px;
        line-height: 1.6;
        min-height: 0;
        scrollbar-width: thin;
        scrollbar-color: #374151 transparent;
    }
    .log-zone-sm { max-height: 240px; flex: none; }

    .log-line { display: flex; gap: 6px; flex-wrap: wrap; align-items: baseline; }
    .log-red .log-content  { color: #fca5a5; }
    .log-blue .log-content { color: #93c5fd; }
    .log-sys .log-content  { color: #9ca3af; font-style: italic; }

    .log-ts    { color: #4b5563; font-size: 10px; flex-shrink: 0; }
    .log-rnd   { color: #6b7280; font-size: 10px; flex-shrink: 0; }
    .log-phase { font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em; flex-shrink: 0; }
    .log-move  { color: #8b5cf6; font-size: 10px; flex-shrink: 0; }
    .log-content { flex: 1; min-width: 0; word-break: break-word; }
    .log-wait  { color: #6b7280; font-style: italic; }

    .dots { display: inline-block; animation: dotdot 1.4s infinite steps(4, end); }
    @keyframes dotdot {
        0%  { clip-path: inset(0 100% 0 0); }
        33% { clip-path: inset(0  66% 0 0); }
        66% { clip-path: inset(0  33% 0 0); }
        100%{ clip-path: inset(0    0 0 0); }
    }

    /* ── Results panel ────────────────────────────────────────────────────── */
    .pp-results { gap: 14px; }

    .winner-banner {
        text-align: center;
        padding: 14px;
        border-radius: 8px;
        font-size: 16px;
        font-weight: 700;
    }
    .banner-red  { background: rgba(239,68,68,0.15); border: 1px solid rgba(239,68,68,0.4); color: #fca5a5; }
    .banner-blue { background: rgba(14,165,233,0.15); border: 1px solid rgba(14,165,233,0.4); color: #93c5fd; }
    .banner-draw { background: rgba(107,114,128,0.15); border: 1px solid #374151; color: #9ca3af; }

    .score-section { display: flex; flex-direction: column; gap: 8px; }
    .score-row { display: flex; align-items: center; gap: 10px; }
    .score-label { width: 36px; font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.06em; }
    .score-track { flex: 1; height: 8px; background: #374151; border-radius: 4px; overflow: hidden; }
    .score-fill  { height: 100%; border-radius: 4px; transition: width 0.8s ease; }
    .fill-red  { background: #EF4444; }
    .fill-blue { background: #0EA5E9; }
    .score-num { width: 30px; text-align: right; font-size: 13px; font-weight: 700; }

    .red-name  { color: #EF4444; }
    .blue-name { color: #0EA5E9; }

    /* ── Metric cards ─────────────────────────────────────────────────────── */
    .metric-cards { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
    @media (max-width: 520px) { .metric-cards { grid-template-columns: 1fr; } }

    .metric-card {
        background: var(--bg-secondary, #2F343E);
        border-radius: 8px;
        padding: 12px 14px;
        display: flex;
        flex-direction: column;
        gap: 7px;
    }
    .metric-red  { border-left: 3px solid #EF4444; }
    .metric-blue { border-left: 3px solid #0EA5E9; }

    .card-title { font-size: 12px; font-weight: 700; margin-bottom: 2px; }
    .metric-row { display: flex; justify-content: space-between; align-items: center; }
    .met-label  { font-size: 11.5px; color: #9ca3af; }
    .met-val    { font-size: 12px; font-weight: 600; color: #e5e7eb; }
    .met-penalty .met-val { color: #f87171; }

    /* ── DPO banner ───────────────────────────────────────────────────────── */
    .dpo-banner {
        background: rgba(124,58,237,0.1);
        border: 1px solid rgba(124,58,237,0.3);
        border-radius: 6px;
        padding: 9px 12px;
        font-size: 12px;
        color: #c4b5fd;
    }
    .dpo-banner code { font-size: 11px; color: #a5b4fc; }

    /* ── Log detail (collapsible) ─────────────────────────────────────────── */
    .log-detail summary {
        cursor: pointer;
        font-size: 11.5px;
        color: #6b7280;
        user-select: none;
        padding: 2px 0;
    }
    .log-detail summary:hover { color: #9ca3af; }

    /* ── Error ────────────────────────────────────────────────────────────── */
    .result-error {
        background: rgba(239,68,68,0.1);
        border: 1px solid rgba(239,68,68,0.3);
        border-radius: 8px;
        padding: 14px;
        color: #fca5a5;
        font-size: 13px;
        display: flex;
        align-items: center;
        gap: 8px;
    }
    .err-icon { font-size: 18px; }

    /* ── Result actions ───────────────────────────────────────────────────── */
    .result-actions { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
    .export-wrap { position: relative; }
    .export-btn {
        padding: 7px 14px;
        background: transparent;
        border: 1px solid #4b5563;
        border-radius: 6px;
        color: #9ca3af;
        font-size: 12px;
        cursor: pointer;
        transition: border-color 0.15s;
    }
    .export-btn:hover { border-color: #6b7280; color: #d1d5db; }
    .export-tooltip {
        position: absolute;
        bottom: calc(100% + 6px);
        left: 50%;
        transform: translateX(-50%);
        background: #1f2937;
        border: 1px solid #374151;
        border-radius: 4px;
        padding: 4px 8px;
        font-size: 11px;
        color: #d1d5db;
        white-space: nowrap;
        pointer-events: none;
    }
</style>
