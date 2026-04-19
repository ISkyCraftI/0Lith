# 0Lith Desktop — CLAUDE.md

## Project Overview
0Lith is a **personal multi-agent AI cockpit** — not just a chatbot. It observes, learns, suggests, and executes. Tauri 2 + Svelte 5 (runes) + Python 3.12 backend. 5 AI agents run locally via Ollama on RTX 5070 Ti (16 GB VRAM). Zero cloud dependency.

## User
- Identity: anonymous (kept private in public repo)
- Language: French (conversations, commit messages, UI labels in French preferred)
- Priorities: Gaming (LoL etc.) coexists with 0Lith — VRAM is shared, never monopolized
- Vision: Autonomous system that learns patterns, predicts needs, suggests proactively

## Autonomy Levels (Critical Design Rule)
| Level | Behavior | Permission |
|-------|----------|------------|
| **0 — OBSERVE** | Read files, memorize, correlate, shadow think | None |
| **1 — SUGGEST** | Proactive notifications, recommendations | None (notification) |
| **2 — ACT** | Write/send/modify/execute | **EXPLICIT user approval** |

**Absolute rule**: 0Lith NEVER performs Level 2 actions without the User's explicit approval. No emails sent, no files modified, no messages posted autonomously. Ever.

## Tech Stack — Critical Rules
- **Tauri 2** (NOT v1) — APIs are completely different. Reference: https://v2.tauri.app
- **Svelte 5 runes** ($state, $derived, $effect, $props) — NOT Svelte 4 stores (no writable())
- **TailwindCSS 4**
- **bits-ui** for components (NOT shadcn-svelte — Svelte 5 stability)
- **Python 3.12** (NOT 3.13+ — Kuzu incompatible)
- IPC: JSON line-delimited stdin/stdout with UUID correlation

## Architecture
- Tauri CWD is `src-tauri/`, all relative paths from JS/Python must use `../py-backend/`
- Shell permissions in `src-tauri/capabilities/default.json` (NOT tauri.conf.json)
- Python backend: `py-backend/olith_core.py` — persistent process, not spawn-per-request
- Background loop: `py-backend/olith_watcher.py` — separate process for proactive features (Phase 3)
- Memory: Mem0 + Qdrant (embedded `QdrantClient(path="./qdrant_data")`, no Docker) + optional Kuzu graph
- Embeddings: qwen3-embedding:0.6b (1024 dimensions) via Ollama

## The 5 Agents (Cybersecurity Dock V1)
| Agent | Model | Role | Emoji | Color | VRAM | Location |
|-------|-------|------|-------|-------|------|----------|
| Hodolith | qwen3:1.7b | Dispatcher + Observer | yellow | #EAB308 | ~1.5 GB | local |
| Monolith | qwen3:14b | Orchestrator, general reasoning | black | #3B82F6 | ~10 GB | local |
| Aerolith | qwen3-coder:30b | Coder (slow but high quality) | green | #43AA8B | ~18 GB (CPU offload) | local |
| Cryolith | Foundation-Sec-8B | Blue Team defense | blue | #0EA5E9 | ~5 GB | local |
| Pyrolith | DeepHat-V1-7B | Red Team offensive | red | #EF4444 | ~5 GB | Docker :11435 |

## Agent Dock Architecture
0Lith is built as a **dock**: fixed core + pluggable agent modules.

```
CORE (always active): Hodolith + Mem0 + Qdrant + qwen3-embedding:0.6b
DOCK Cybersec (V1):   Monolith, Aerolith, Cryolith, Pyrolith
DOCK Personal (M3+):  Schedulith, Econolith (future YAML configs)
DOCK Game Dev (M4+):  Storylith, Artlith, Gamelith (future YAML configs)
```

Adding an agent = adding a YAML file in `/agents/`, not code changes. YAML agent configs are planned for Month 3. Until then, agents are hardcoded in `olith_memory_init.py`.

## VRAM Constraint (16 GB) & Gaming Mode
- Always loaded: Hodolith (1.7B) + embedding model (0.6B) ≈ 2 GB
- Only ONE large agent at a time (Monolith/Aerolith/Cryolith swap dynamically)
- Pyrolith runs in Docker with `--gpus all`, separate VRAM budget

### Three VRAM Modes
```
WORK MODE (default):
  Hodolith + Embedding always loaded (~2 GB)
  1 heavy agent on demand (~5-10 GB)
  Max: ~12 GB / 16 GB

GAMING MODE (manual toggle or future auto-detect):
  ALL models unloaded from VRAM (Ollama keep_alive=0)
  Hodolith falls back to CPU-only (slow but functional)
  Suggestions queue silently, displayed after session
  0Lith VRAM: ~0 GB → 16 GB free for gaming
  Enventually, have an agent that is silently there to monitor gaming activity and provide insights

NIGHT MODE (PC idle, no gaming):
  Pyrolith vs Cryolith sparring on recent CVEs
  Hodolith observes and prepares morning summary
  No VRAM constraint
```

Future auto-detect: monitor for `LeagueClient.exe`, `RiotClientServices.exe`, or GPU usage > 80%.

## Streaming Architecture
- **Ollama streaming**: `stream: True` in `/api/chat` — yields JSON lines with `{"message":{"content":"token"}, "done": false}`
- **IPC protocol**: Backend emits intermediate JSON lines during generation:
  - `{"id":"uuid", "status":"routing", "agent_id":"monolith", ...}` — routing result (instant)
  - `{"id":"uuid", "status":"streaming", "chunk":"token"}` — each token as it arrives
  - `{"id":"uuid", "status":"ok", "response":"full text", ...}` — final response
- **Frontend flow**: `pythonBackend.send()` accepts optional `onStream` callback. Streaming messages call the callback; final `ok`/`error` resolves the promise.
- **Chat store**: Creates an empty agent message bubble on routing, appends chunks via `updateMessage()`, finalizes on `ok`.
- **Thinking indicator**: Shows "Réflexion..." until routing arrives, then "{Agent} réfléchit..." until first token, then hides.
- **Hodolith routing uses non-streaming** `chat_with_ollama()` (needs full JSON response to parse).

## Background Loop (Phase 3 — olith_watcher.py)
Separate Python process from olith_core.py. Launched in parallel by Tauri.

**Responsibilities:**
- File watcher: detect project file changes (watchdog)
- Schedule checker: read iCal/schedule.json, detect free slots
- Shadow Thinking: Hodolith analyzes file diffs, extrapolates next steps, pre-prepares answers in Mem0 (tagged `shadow_thinking`, never displayed until relevant)
- Suggestion generator: emits `{"event": "suggestion", ...}` via stdout

**Critical**: Background loop NEVER performs Level 2 actions. Observe and suggest only.

**Prediction learning loop:**
```
0Lith suggests X → User accepts    → Mem0: "prediction correct"
                 → User modifies   → Mem0: "prefers Y over X"
                 → User dismisses  → Mem0: "wrong direction, adjust"
```

## Known Gotchas
- **#User tag**: When an agent is blocked and needs human input, it emits `#User <question>` on its own line. `olith_tasks.py` detects this and appends to `~/.0lith/Tasks/User_needed.md`. On each chat, `resolve_completed()` removes lines marked `[x]`. IPC commands: `list_tasks`, `resolve_tasks`.
- **qwen3 /no_think**: qwen3 models use `<think>...</think>` by default. Mem0 fact extraction breaks without `/no_think`. Class-level monkey patch on `OllamaLLM.generate_response` is applied at module top of olith_core.py.
- **Windows cp1252**: stdout must be forced to UTF-8 (`io.TextIOWrapper`) for emoji support.
- **Hodolith routing**: Must strip `<think>` tags from qwen3 output before JSON parsing. Falls back to text matching if JSON parse fails.
- **Pyrolith Docker**: Uses Ollama API (`/api/chat`, `/api/tags`), NOT OpenAI-compatible endpoints. Current setup is **not hardened** — pending: run as non-root, `--cap-drop=ALL`, isolated bridge network with no outbound internet.
- **Aerolith 30B**: Exceeds 16 GB VRAM, Ollama does CPU offload. Expect 3-5 min responses. Timeout set to 600s. Frontend MUST handle slow responses gracefully (progress indicator, no freeze). Don't remove the 30B — make the wait dignified.
- **Mem0 + Qdrant**: Runs in embedded mode (`QdrantClient(path="./qdrant_data")`). No Docker required — `qdrant_data/` is created automatically on first use. Known quirk: `delete_collection` updates `meta.json` but leaves `storage.sqlite` on disk; `olith_memory_init.py` and tests handle this by wiping the physical folder before recreating. Recollection dimensions: 1024.
- **Shadow Thinking**: `olith_watcher.py` stores per-file Hodolith predictions in Mem0 with `type: "shadow_thinking"`, `confidence_score` (0–1), `file_path`, `source: "file_change"`. Max 2 predictions per file-change batch (prioritises `.py` > `.ts`/`.svelte` > `.rs`, `modified` > `created`). Predictions are **never emitted to the UI** — they surface automatically when `search_memories()` in `olith_agents.py` runs a semantic search during a related chat. Key methods: `_extract_file_snippet()`, `_call_hodolith_json()`, `_pick_shadow_files()`, `_shadow_think_file()`.
- **Kuzu**: Optional. Only works with Python 3.12. System works fine without it (vector-only mode).
- **Memory token overflow**: Mem0 can inject too many retrieved memories into small model contexts (Hodolith 1.7B, Cryolith 8B). Implement a hard token budget (≤ 512 tokens for memory context) to prevent attention saturation.
- **Monolith/Aerolith boundary**: Monolith *reasons and plans about* code; Aerolith *writes* code. Hodolith routing prompt currently captures this but the distinction should be explicit: never route "how to approach this algorithm" to Aerolith, never route "write this function" to Monolith.
- **Agent output schema**: Agents return free-form text; the frontend parses it with regex/heuristics. A strict JSON schema for structured responses (especially tool calls and routing) would eliminate a class of UI parse bugs.
- **Purple Team module** (`py-backend/purple/`): Game Master pour simulations adversariales Red vs Blue. Architecture : 80 % Python déterministe, 20 % LLM narratif uniquement. `ScenarioGenerator` est 100 % déterministe via seed (même seed = même scénario exact — testé). `CyberRange` génère un docker-compose.yml éphémère avec réseau `--internal` + gVisor. `Scorer` ne fait JAMAIS appel au LLM — vérifications binaires uniquement (flag exfiltré, Sigma valide, patch efficace). `SafetyChecker` doit passer avant tout match (gVisor, réseau isolé, ports Qdrant/Kuzu non exposés, token HMAC). Logs : `~/.0lith/arena_logs/`, DPO export : `~/.0lith/dpo_data/`. **Prérequis non encore implémentés** : gVisor installé, images Docker `0lith/vuln-*` buildées, token HMAC configuré. Dev mode : `PURPLE_SKIP_GVISOR=1`, `PURPLE_SKIP_TOKEN=1`. Dépendance : `aiohttp` (pour les appels LLM async).
- **`olith_purple.py`** — **COMPLET + WIRÉ** : Processus IPC standalone (spawné par Tauri comme `olith_watcher.py`). 5 commandes : `purple_generate_scenario` (seed+difficulty→config JSON), `purple_start_match` (valide HMAC→safety checks→lance thread), `purple_match_status` (phase/rounds/elapsed), `purple_match_result` (MatchResult.to_dict()), `purple_stop_match` (cancel event). Token HMAC-SHA256 lu depuis `~/.0lith/sparring.key` ou `OLITH_SPARRING_SECRET` env var. Un seul match à la fois (`threading.Lock` non-bloquant). Timeout global 60 min (`asyncio.wait_for`). Match tourne dans un thread daemon (`asyncio.run()`). `threading.Event` passé directement comme `cancel_event` à `MatchProtocol` (compatible car seul `.is_set()` est utilisé). Events streamés via `status="purple"` sur le même `req_id`. **Wiring Tauri** : `python-purple` dans `capabilities/default.json` (shell:allow-spawn + shell:allow-execute) ; `lib.rs` émet `"app-quit"` avant `app.exit(0)` ; `src/lib/purple_ipc.ts` : types + fonctions `start/stop/generateScenario/startMatch/getMatchStatus/getMatchResult/stopMatch` — démarré ON DEMAND, s'arrête sur `"app-quit"`. **Reste à faire** : tab frontend `PurpleView.svelte`.
- **Cyber Range Docker images** (`py-backend/docker/`) — **Phase 2 minimal** : 4 images buildées localement, taggées `0lith/<name>:latest`. Build order : `vuln-webapp` → `vuln-ssh` → `siem-lite` → `noise-gen`. Scripts de build/test dans `py-backend/docker/` (voir section Purple Team Commands ci-dessous). Images attendues par `cyber_range.py` : `0lith/vuln-webapp:latest`, `0lith/vuln-ssh:latest`, `0lith/noise-gen:latest`, `0lith/siem-lite:latest`. `docker/docker-compose.template.yml` : template de test manuel (réseau `10.42.0.0/24`, internal:true). **Flag injection** : `vuln-webapp` lit `FLAG_VALUE` depuis env var (injecté par `scenario_generator` via `env_overrides`) — défaut `FLAG{0lith_cyber_range_pwned}`. **vuln-ssh** : exception root (SSH requiert root pour bind :22 + chpasswd). **siem-lite** : port `5514/udp` (non-root) — pour port 514 standard, ajouter `CAP_NET_BIND_SERVICE`. **noise-gen** : génère du trafic HTTP bénin vers `/`, `/products`, `/search?q=...`, `/comment` — rend détection plus réaliste.
- **DPO Exporter** (`purple/dpo_exporter.py`) — **COMPLET, testé (29/29)** : `DPOPair` utilise `source_match_id` (pas `match_id`) et a `score_delta: float`. Sept critères d'extraction déterministes — Red : `exploit_success_vs_failure` (exit_code=0 vs 1), `stealth_vs_detected` (IP/≥3 mots-clés détection), `technique_novelty_vs_repeat` (première occurrence MoveType vs répétition) ; Blue : `detection_hit_vs_miss`, `sigma_valid_matching_vs_invalid` (via Scorer.validate_sigma_rule), `patch_proposed_vs_absent` (mots-clés patch/fix/CVE), `no_disruption_vs_disruption` (phrases "shut down all services"). Règle immuable : `control_scenario=True` → liste vide, jamais exporté. `export_to_jsonl(pairs)` → format TRL `{"prompt","chosen","rejected"}` uniquement. `accumulate_pairs(min_pairs=500)` → compte dans `dpo_*.jsonl`. Cross-produit limité à `MAX_CROSS_PAIRS=4` pour éviter l'explosion combinatoire.
- **Scorer** (`purple/scorer.py`) — **COMPLET, testé (40/40)** : `RedScore.total` et `BlueScore.total` sont des **champs** calculés via `__post_init__` (pas des méthodes — appeler `.total()` lèvera `TypeError`). `calculate_evasion_rate()` attend `red_actions: list[dict]` avec clés `"ip"`, `"commands"`, `"move_type"` (pas `list[str]`). `check_objective()` mode 3 (credential extract) ne s'active que si le `scenario.objective` contient "credential"/"password"/"admin"/"hash". `_check_root_cause()` cherche les IDs MITRE ATT&CK du scénario dans le texte Blue (ex: "T1190") — utiliser `scenario.mitre_techniques` pour construire les tests. `SigmaValidation.score_value` : 2 si valid+matching, 1 si valid sans match, 0 si invalide.
- **ScenarioGenerator** (`purple/scenario_generator.py`) — **COMPLET, testé** : `generate(seed, difficulty)` déterministe. `to_docker_compose(config)` → YAML complet valide (internal network, gVisor, cap_drop, read_only, env vars vulns). `generate_briefings(config)` → tuple (red_brief, blue_brief) — asymétrie stricte : vulns/credentials jamais exposés, objectif absent du briefing Blue. `generate_control(seed, diff)` → scénario de benchmark (control_scenario=True, jamais en DPO). `generate_batch(count, diff, base_seed, control_ratio)` pour Training Mode nuit. Catalogue : 8 services (webapp/ssh/ftp/smb/dns/mail/db/log4j), 24 techniques MITRE ATT&CK, vulns par tier (easy/medium/hard), credentials faibles/forts selon difficulté, objectifs cohérents avec les services déployés.
- **Purple Team safety** : Red n'a JAMAIS accès direct aux conteneurs — Purple exécute les commandes en proxy via `exec_command()`. Les collections Qdrant Red/Blue sont strictement séparées (pas de cross-contamination). Le réseau Docker du range est `--internal=true` — aucun conteneur ne peut atteindre internet ou l'hôte.
- **WDAC/HVCI (dev machine)**: HVCI (Memory Integrity ON) + Smart App Control blocks unsigned Rust binaries. Fix: self-signed cert `CN=0Lith Dev` (thumbprint `DACA80CF...`) trusted in `LocalMachine\Root` + `TrustedPublisher`. Binary must be signed after each `cargo build` via `scripts/dev-sign.ps1`. Cargo target redirected to `AppData\Local\olith-build` (see `.cargo/config.toml`, gitignored). See top of `dev-sign.ps1` for one-time setup.
- **Store import paths**: Stores live in `src/lib/components/stores/`. They must import types via `../../types/ipc` (NOT `../types/ipc`). Components import stores via `./stores/...` (relative to `lib/components/`).

## Purple Team — Docker Cyber Range Commands

```bash
# Prérequis : se placer dans py-backend/docker/
cd 0lith-desktop/py-backend/docker

# Build les 4 images (vuln-webapp → vuln-ssh → siem-lite → noise-gen)
./build_all.sh

# Build force rebuild (sans cache Docker)
./build_all.sh --no-cache

# Tests d'intégration complets (5 tests : HTTP 200, SQLi FLAG{, SSH port, SIEM logs, noise-gen)
./test_cyber_range.sh

# Tests en mode debug (conserve les conteneurs après)
./test_cyber_range.sh --keep

# Démarrage manuel du range de test (subnet 10.42.1.0/24)
docker compose -f docker-compose.test.yml up -d

# Arrêt + nettoyage complet (volumes inclus)
docker compose -f docker-compose.test.yml down --volumes --remove-orphans

# Logs temps réel
docker compose -f docker-compose.test.yml logs -f

# Vérifier les tailles des images
docker images "0lith/*"
```

**WSL2/Docker Desktop** : les IPs conteneurs (10.42.1.x) ne sont pas routables depuis l'hôte Windows.
Les tests utilisent `docker exec` (intra-réseau) ou les ports exposés (`localhost:18080`, `localhost:12222`, `localhost:15514`).

**gVisor** (`runsc`) : optionnel en développement, **requis en production** pour isoler les conteneurs vulnérables.
- Dev : `PURPLE_SKIP_GVISOR=1` dans l'environnement
- Prod : `runtime: runsc` dans docker-compose + `gvisor-containerd-shim` installé
- `SafetyChecker` refuse de lancer un match si gVisor absent et `skip_safety=False`

## Color Scheme
- Background primary: `#282C33`
- Background secondary: `#2F343E`
- Background tertiary: `#3A3F4B`
- NOT blue/slate — warm dark grays preferred
- Agent colors: Hodolith #EAB308, Monolith #3B82F6, Aerolith #43AA8B, Cryolith #0EA5E9, Pyrolith #EF4444

## Memory Architecture Evolution

**V1 (current)**: Mem0 + Qdrant + Kuzu — pragmatic, battle-tested, Ollama-native.
- Embeddings: `qwen3-embedding:0.6b` (1024 dims, code-aware, #1 MTEB Multilingual)
- Multi-agent scoping: `agent_id` + `user_id` for private/shared memories
- VRAM overhead: ~350 MB (embeddings only), Qdrant + Kuzu run on CPU
- Why NOT a "Bibliolith" LLM for memory: would cost 5-10 GB VRAM, hallucination risk, 1-5s latency vs 5ms

**V2 (evaluate when V1 stable)**: MemOS v2.0 (Shanghai Jiao Tong University)
- MemCube abstraction: plaintext + KV-cache + LoRA weights + tool trajectories
- +38.9% vs Mem0, -94% latency via KV-cache injection
- Tool Memory: replay sparring trajectories for faster planning
- Requires: Docker + Redis Streams, more complex setup

**V3 (future)**: Memory-R1 / Mem-α — RL-trained memory management
- Agent learns WHEN to add/update/delete memories (+57% F1 vs Mem0)
- Requires pre-trained RL models on Ollama (not yet available)

Full research: `Reflexions/0Lith_Memory_Architecture.md` and `Reflexions/0Lith_Embeddings_Memory_Research.md`.

## Project Status

### Completed
- [x] Phase 0: Ping-pong IPC prototype
- [x] Phase 1: Backend Python (olith_core.py, Hodolith routing, Mem0/Qdrant)
- [x] Phase 2: Frontend chat interface (sidebar, markdown, VRAM indicators, streaming)
- [x] Phase 3: Gaming mode (VRAM unload toggle)
- [x] Phase 3: System tray (background persistence, notifications)
- [x] Phase 3: Background loop (olith_watcher.py, file watcher, suggestions panel)
- [x] Phase 3: Chat persistence (JSON history, `~/.0lith/chats/`, session sidebar)
- [x] Infra: `.claude/` and `__pycache__/` correctly excluded from git (`.gitignore` verified ✓)
- [x] Launch: Repo cleanup — gitignore enhanced, Reflexions/ staged, root CLAUDE.md added
- [x] Launch: AGPL-3.0 license added (LICENSE at root), English README (README.md), French copy kept as README.fr.md

### 🔴 Critical — Do now
- [x] Phase 3: Shadow Thinking — `_shadow_think_file()` in olith_watcher.py: per-file Hodolith prediction stored in Mem0 (`shadow_thinking` tag, `confidence_score`); never emitted to UI; surfaces via normal memory retrieval in chat
- [x] Infra: Switch Qdrant to embedded mode (`QdrantClient(path="./qdrant_data")`) — eliminates Docker dependency for Qdrant entirely
- [ ] Security: Harden Pyrolith Docker — non-root user, `--cap-drop=ALL`, isolated bridge network, no outbound internet

### 🟠 High — Next sprint
- [x] Frontend: Custom TitleBar — decorations: false, Chat/Arena tab navigation, window controls (─ □ ✕)
- [x] Launch: Arena — SQL Injection sparring demo (Pyrolith vs Cryolith, 5 rounds + review, live streaming)
- [x] Arena UX v1 — stop button, tab lock (flash red), elapsed chrono, per-move timer + expandable details, ARENA sidebar badge, InputBar lock, collapsible log strip, per-session `.jsonl` file log in `~/.0lith/arena_logs/`
- [x] Arena v2 robustesse — `_get_timeout()` adaptatif par modèle (DeepHat/Foundation-Sec=300s), `_llm_call_with_fallback()` retry auto qwen3:14b, `_build_context(max_rounds=2)`, séquences forcées, round fields dans les events, `num_ctx=2048`, session timeout 30 min
- [x] Arena v2 UI — scenario pills, round dots (● ● ○ ○ ○), symboles Unicode (◉ ⚔ ■ ✦ ◈ ▲), durée colorée, loading animation, badge VICTOIRE, bouton Nouvelle session, export log tooltip, `ArenaResult` localStorage
- [x] Accessibility — aria-labels InputBar (Annuler/Envoyer), ChatMessage (feedback), OLithEye tabindex fix
- [ ] Backend: Standardize agent outputs to strict JSON schema (eliminates frontend parse bugs)
- [ ] Frontend: Aerolith loading state UI ("Aerolith réfléchit… 3-5 min", progress bar, cancel)
- [x] Backend: Clarify Monolith/Aerolith boundary in Hodolith routing prompt (Monolith plans/reasons, Aerolith writes) — done, prompts rewritten in English with explicit boundary
- [ ] Feature: Conversation deletion + multi-select
- [x] Purple Team Phase 1: `olith_purple.py` — processus IPC standalone complet (5 commandes, HMAC token, single-match mutex, 60min timeout, streaming events)
- [x] Purple Team Phase 1 — wiring Tauri : `capabilities/default.json` + `python-purple` spawn permission ; `lib.rs` émet `"app-quit"` avant `app.exit(0)` pour cleanup gracieux ; `src/lib/purple_ipc.ts` : types IPC complets + fonctions `start/stop/generateScenario/startMatch/getMatchStatus/getMatchResult/stopMatch` — processus démarré ON DEMAND (pas au boot), tué sur `"app-quit"` Tauri ou explicitement
- [x] Purple Team Phase 1 — tab frontend : `PurplePanel.svelte` (config → match → résultats) + onglet Purple dans `TitleBar.svelte` + wiring `App.svelte` — 4 états (idle/generating/running/done), log live en temps réel, barres de score, métriques Red/Blue, compteur DPO
- [x] Purple Team: images Docker Phase 2 minimal (vuln-webapp, vuln-ssh, noise-gen, siem-lite) + docker-compose.template.yml
- [ ] Purple Team: builder les images (`cd py-backend/docker && docker build -t 0lith/vuln-webapp:latest ./vuln-webapp` etc.)
- [x] Purple Team: implémenter les TODO dans `cyber_range.py` — `check_health()` TCP/HTTP/UDP réels (5 retries, 2s backoff, asyncio.gather parallèle), `exec_command()` security filter (docker/mount/nsenter/proc/IPs hors subnet), `read_siem_logs()` (tail_n=200, since_line incrémental), `cleanup_on_error()` (compose down --remove-orphans) — testé 44/44
- [x] Purple Team: `match_protocol.py` complet — `_call_agent(agent, prompt, system, timeout) → str` Ollama direct + callable fallback, `_ollama_call()` messages structurés (system+history+user), `_strip_think()`, `_update_history()` (cap 4 entries / 2 rounds), `_inject_history_into_prompt()` (callable path), asymétrie Red/Blue garantie (Red ≠ SIEM, Blue ≠ commandes), `_call_agent_move()` wrapping AgentMove, backward-compat constructor (`red_llm`/`blue_llm` optionnels) — testé 42/42
- [x] Purple Team: implémenter `_test_patch()` dans scorer.py (replay exploit sur conteneurs live) — extraction du dernier bloc code Blue avec keywords remédiation, replay exploit Red, asyncio.wait_for 15s par commande, conservatif (erreur → False) — testé 14/14
- [x] Purple Team: scorer.py complet et testé (40/40) — RedScore, BlueScore, SigmaValidation, evasion rate, check_objective
- [x] Purple Team: dpo_exporter.py complet et testé (29/29) — 7 critères, export TRL, accumulate_pairs

### 🟡 Medium — Month 2-3
- [ ] Launch: Demo video 2-3 min (r/LocalLLaMA, Hacker News)
- [ ] Infra: Startup health checks (Ollama up? models pulled? Pyrolith container ready?) before launching Tauri
- [ ] Memory: Strict token budget for memory injection (≤ 512 tokens, prevents small model overflow)
- [ ] Memory: Monthly pruning — Monolith reviews Mem0 entries > 30 days, deletes outdated/contradicted facts
- [ ] Feature: Sidebar tabs (Agents / History separated)
- [ ] Feature: OLithEye animated SVG (5 states: idle, thinking, responding, sleeping, gaming)
- [ ] Feature: MCP Server for Zed.dev
- [ ] Feature: Agent dock YAML configs
- [ ] Training Mode: Pyrolith vs Cryolith CVE sparring overnight + morning briefing

### Future
- [ ] Game dev dock (Storylith, Artlith, Gamelith)
- [ ] Personal dock (Schedulith, Econolith)
- [ ] Google Takeout ingestion pipeline
- [ ] Per-agent LoRA fine-tuning — pipeline dans `0lith-training/` (Pyrolith v2 + Cryolith v2, bf16 LoRA sur Qwen3.5-4B)

## Launch Preparation

Immediate non-code priorities (from `Reflexions/Matrice Einsenhower.md`):

**This week:**
1. ~~Repo cleanup: fix `.gitignore`, remove `__pycache__`/`.obsidian` from tracking~~ **DONE**
2. ~~Add AGPL-3.0 LICENSE file~~ **DONE**
3. ~~English README: pitch, demo GIF, hardware requirements, 5-step quickstart~~ **DONE** (README.fr.md kept as French copy)
4. One working end-to-end demo (red OR blue team flow)

**Next 2-4 weeks:**
5. Demo video 2-3 min (r/LocalLLaMA, Hacker News)
6. Installer bundle (.exe with Ollama + models + Qdrant + GUI)
7. GitHub topics, issue templates, Sponsors activation
8. r/LocalLLaMA launch post

## Business Context

**Positioning**: Only tool combining multi-agents + desktop GUI + 100% local + cybersecurity. No competitor covers all four.

**License**: AGPL-3.0 (copyleft — commercial forks need license)

**Revenue**: GitHub Sponsors + commercial AGPL license + B2B NIS2/DORA consulting

**Market**: Cybersecurity AI $30.9B (2025) → $86-104B (2030). Regulatory push: NIS2, DORA, EU AI Act.

**Window**: 18-36 months before Big Tech ships local multi-agent desktop tools.

Full analysis: `Reflexions/Etude de Marché.md`.

## Commands
- Dev (standard): `cd C:\Users\skycr\Perso\0Lith\0lith-desktop && npm run tauri dev`
- Dev (WDAC machine — 2 terminals required):
  - Terminal 1: `npm run dev` (Vite HMR on :5173 — must be running first)
  - Terminal 2: `.\scripts\dev-sign.ps1` (cargo build + Authenticode sign + launch)
- Build: `npm run tauri build`
- Type check: `npm run check`
- Python backend deps: `cd py-backend && pip install -r requirements.txt`
- Qdrant embedded: no Docker needed — data auto-created in `py-backend/qdrant_data/`
- Pyrolith Docker: `docker start pyrolith` (port 11435, needs `--gpus all`) — *pending security hardening*
- Memory init: `cd py-backend && python olith_memory_init.py`
- Memory test: `cd py-backend && python olith_memory_init.py --test`
- Memory reset: `cd py-backend && python olith_memory_init.py --reset`

## TitleBar & Navigation

Custom title bar replacing native OS decorations (`"decorations": false` in `tauri.conf.json`).

**Component**: `src/lib/components/TitleBar.svelte`
- `data-tauri-drag-region` on the root div — entire bar is draggable, buttons excluded
- Window API: `getCurrentWindow()` from `@tauri-apps/api/window` — minimize / toggleMaximize / close
- Permissions in `capabilities/default.json`: `core:window:allow-minimize`, `core:window:allow-toggle-maximize`, `core:window:allow-close`
- Height: 48px — layout height adjusted to `calc(100vh - 72px)` (titlebar 48 + statusbar 24)

**Tabs**:
- `Chat` — main chat interface (default)
- `Arena` — Pyrolith vs Cryolith SQL Injection sparring (live, streaming)

**Tab state**: `$state<'chat' | 'arena'>` in `App.svelte`, passed down as props.

**ArenaView**: `src/lib/components/ArenaView.svelte` — two-panel sparring UI (see Arena section below).

## Arena — SQL Injection Sparring

Live red-vs-blue IPC sparring demo: Pyrolith (Red) attacks, Cryolith (Blue) defends, 5 rounds + weakness review.

**IPC flow**: `frontend.send({command:"arena"}, 1_800_000, onStream)` — same streaming pattern as chat. 30 min budget (slow models ~25 min typical).
- Per-move events: `{"id":"…", "status":"arena", "move":{...}, "score":{...}}` — non-resolving (calls `onStream`)
- Final: `{"id":"…", "status":"ok", "score_red":N, "score_blue":N, "review":{...}}` — resolves promise
- Move events include `round` (1-5) and `round_total` (5) fields — used by store `getRoundNum()` and frontend round dots

**Arena files**:
| File | Role |
|------|------|
| `py-backend/olith_arena.py` | Core logic: 5-round loop, LLM calls, JSON parsing, emit helpers |
| `py-backend/olith_core.py` | `cmd_arena()` handler — uses `_chat_lock` to serialize with chat |
| `src/lib/types/ipc.ts` | `ArenaMove`, `ArenaEvent`, `ArenaResponse` types |
| `src/lib/components/stores/arena.svelte.ts` | Svelte 5 runes store: moves, score, phase, review, error |
| `src/lib/components/ArenaView.svelte` | Two-panel UI: Red (left) / VS / Blue (right), score bar, review |

**Models**:
- Pyrolith: `deephat/DeepHat-V1-7B:latest` on Docker port 11435 → fallback `qwen3:14b`
- Cryolith: `hf.co/fdtn-ai/Foundation-Sec-8B-Q4_K_M-GGUF:latest` → fallback `qwen3:14b`

**Score table** (per move type):
```
Red:  RECON=3, EXPLOIT=10, SUCCESS=15, PIVOT=12, DATA=20
Blue: MONITOR=3, ALERT=5,  BLOCK=15,  PATCH=10,  ISOLATE=20
```

**Phases**: `idle → running → review → done`

**Key gotchas**:
- `status:"arena"` added to non-resolving list in `pythonBackend.svelte.ts` (alongside `"streaming"`, `"routing"`)
- Arena uses `_chat_lock` — chat is blocked while arena runs (expected; ~25 min typical with slow models)
- `_parse_move(forced_type)` uses regex patterns + fallback only — **keyword scan removed** (caused type pollution); type always set via `RED_SEQUENCE[round-1]` / `BLUE_SEQUENCE[round-1]` regardless of LLM output
- **Forced sequences**: `RED_SEQUENCE = ["RECON","EXPLOIT","EXPLOIT","PIVOT","DATA"]`, `BLUE_SEQUENCE = ["MONITOR","ALERT","BLOCK","PATCH","ISOLATE"]` — ensures narrative progression per round
- **Context window**: `_build_context(max_rounds=2)` injects only last 4 lines — prevents few-shot contamination where models continue the combat log sequence
- **Adaptive timeouts**: `_get_timeout(model)` — DeepHat/Foundation-Sec=300s (regularly 120-220s), qwen3:14b=180s, qwen3=120s, unknown=240s; `num_ctx=2048` for arena calls (prompts are short, smaller ctx = faster inference)
- **Auto-fallback**: `_llm_call_with_fallback()` — if stripped response < 20 chars → auto-retry with `qwen3:14b` (catches Foundation-Sec generating `#` in 1-2s); exceptions in `_call_pyrolith`/`_call_cryolith` also fall through to qwen3:14b with `type(e).__name__` in log
- **Model overrides**: `ARENA_RED_MODEL = os.environ.get("ARENA_RED_MODEL", PYROLITH_MODEL)` — set env var to `qwen3:14b` to bypass slow models without code change
- **Session timeout**: `1_800_000ms` (30 min) in `arena.svelte.ts` — covers ~25 min typical runs; old 600s caused premature rejection at round 4
- **Svelte 5 snippets** must use `{@render MoveRow({ move })}` — NOT `<MoveRow {move} />` — silent render failure otherwise
- **Stop button** sends `{command:"cancel"}` → `cmd_cancel()` sets `_cancel_event` → arena loop breaks between rounds
- **Tab lock**: `App.svelte` derives `arenaLocked` from arena phase; passed to `TitleBar` which flashes "Chat" tab red and blocks navigation while arena is `running|review`
- **InputBar lock**: orange notice banner + disabled textarea/button while arena is active; uses same `arenaStore.getPhase()` derivation
- **ARENA badge**: sidebar shows orange `ARENA` badge (instead of DISK/GPU) for Pyrolith + Cryolith while `arenaActive`
- **Per-move timing**: `duration_s` float + `details` payload + `round`/`round_total` int in each move event; frontend shows `Xs` color-coded duration (green <5s, orange 5-30s, red >30s), `R{n}` round prefix, Unicode type symbol, `›` expand button
- **Round progress dots**: `getRoundNum()` / `getRoundTotal()` from store; header shows `● ● ○ ○ ○` — active dot blinks, completed dots alternate red/blue
- **Loading animation**: CSS `dots-anim` shows "Pyrolith génère son attaque..." or "Cryolith génère sa réponse..." in the active panel; derived from `redMoves.length > blueMoves.length`
- **ArenaResult persistence**: on `done`, store builds `ArenaResult{red, blue, duration_s, winner, scenario, timestamp}` → saved to `localStorage` key `arena_last_result`; loaded on module init; exposed via `getLastResult()`; displayed as "Dernière session" on idle screen
- **Scenario selector**: idle screen has pills — SQL Injection (active), Phishing + Privilege Escalation (disabled, "Bientôt" badge); button label is dynamic `"Lancer {scenario}"`
- **Review section**: `VICTOIRE` badge on winner card (red or blue), large centered score `Red N — Blue N`, "Nouvelle session" button (resets + restarts), "Exporter le log" button shows `~/.0lith/arena_logs/` path in tooltip (3s)
- **Error resilience**: each LLM call wrapped in `try/except`; red team failure breaks the round + logs to file; blue team failure is non-fatal (continues to next round); review failures fall back to `"Analyse indisponible."`
- **File log**: each arena session writes `~/.0lith/arena_logs/arena_YYYYMMDD_HHMMSS_sql_injection.jsonl` — one JSON line per event (start / move / review / error / complete); includes `raw` LLM response (truncated to 3000 chars) for post-mortem debugging
- **Collapsible log strip**: `ArenaView.svelte` has a `"Log de combat"` toggle; shows `HH:MM:SS R{n}  RED  [TYPE   ]  message [Xs]` in monospace `<pre>`; built from `arena.getCombatLog()`

## File Structure
```
0lith-desktop/
├── src-tauri/              # Rust/Tauri 2 backend
│   ├── src/lib.rs          # System tray, gaming mode sync, window management
│   ├── capabilities/default.json  # Window + shell permissions
│   └── tauri.conf.json     # decorations: false (custom titlebar)
├── src/                    # Svelte 5 frontend
│   ├── lib/components/     # TitleBar, Sidebar, ChatArea, ChatMessage, InputBar, StatusBar, ArenaView, PurplePanel, ResizeHandles, OLithEye
│   │   └── stores/         # pythonBackend, chat, agents, sessions, gaming, watcher, arena (.svelte.ts)
│   ├── lib/types/ipc.ts    # Full IPC protocol types (chat, arena, watcher)
│   ├── lib/purple_ipc.ts   # Purple Team IPC types + process management (on-demand spawn)
│   └── App.svelte
├── py-backend/             # Python backend
│   ├── olith_core.py       # IPC chat router (reactive)
│   ├── olith_agents.py     # Agent routing + execution (Hodolith → agents)
│   ├── olith_ollama.py     # Ollama API wrapper (streaming, retry, process mgmt)
│   ├── olith_tools.py      # Sandboxed filesystem tools + system info
│   ├── olith_history.py    # JSON session persistence (~/.0lith/chats/)
│   ├── olith_shared.py     # Mem0 monkey-patch, think-block stripping, logging
│   ├── olith_arena.py      # Arena sparring logic (5 rounds, scoring, review, emit helpers)
│   ├── olith_purple.py     # Purple Team orchestrator entry point (IPC: "purple_match")
│   ├── olith_watcher.py    # Background loop (proactive, file watcher, suggestions)
│   ├── olith_memory_init.py # Agent identities + Mem0/Qdrant/Kuzu setup
│   ├── olith_tasks.py      # #User tag detection + User_needed.md management
│   ├── requirements.txt
│   └── purple/             # Purple Team module (Game Master)
│       ├── __init__.py
│       ├── scenario_generator.py  # Scénarios déterministes (seed + difficulté, DAG services)
│       ├── cyber_range.py         # Docker compose lifecycle (deploy/teardown/exec_command)
│       ├── match_protocol.py      # Protocole 6 phases, asymétrie d'info Red/Blue
│       ├── scorer.py              # Scoring 100 % déterministe (pas de LLM)
│       ├── dpo_exporter.py        # Export paires chosen/rejected pour fine-tuning DPO
│       └── safety_checks.py      # Vérifications pré-match (gVisor, réseau isolé, token HMAC)
│   └── docker/             # Images Docker pour le Cyber Range
│       ├── vuln-webapp/        # Flask app vulnérable (SQLi/XSS/Auth-Bypass) — 0lith/vuln-webapp:latest
│       │   ├── Dockerfile
│       │   └── app.py
│       ├── vuln-ssh/           # Serveur SSH mal configuré — 0lith/vuln-ssh:latest
│       │   ├── Dockerfile
│       │   └── entrypoint.sh
│       ├── noise-gen/          # Générateur de trafic légitime — 0lith/noise-gen:latest
│       │   ├── Dockerfile
│       │   └── generator.py
│       ├── siem-lite/          # Collecteur syslog rsyslog — 0lith/siem-lite:latest
│       │   ├── Dockerfile
│       │   ├── rsyslog-siem.conf
│       │   └── entrypoint.sh
│       └── docker-compose.template.yml  # Template de test manuel Phase 2
└── agents/                 # YAML agent configs (future)
```

## Design Principles
1. **Offline first**: Everything local. No cloud dependency. No API keys needed.
2. **VRAM is sacred**: Gaming always takes priority. 0Lith retreats silently.
3. **Memory is the moat**: 0Lith's advantage over cloud AI isn't intelligence — it's knowing the User's patterns, style, and history after months of context.
4. **Each month is usable**: Never "under construction". Month 1 = good chat. Month 2 = proactive suggestions. Month 3 = pluggable agents. Stop at any point and it's still useful.
5. **Level 2 never without permission**: The system suggests, never acts autonomously.
6. **Sovereign by design**: AGPL license, zero cloud, zero telemetry. Data never leaves the machine.
