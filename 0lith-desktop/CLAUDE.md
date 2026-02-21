# 0Lith Desktop — CLAUDE.md

## Project Overview
0Lith is a **personal multi-agent AI cockpit** — not just a chatbot. It observes, learns, suggests, and executes. Tauri 2 + Svelte 5 (runes) + Python 3.12 backend. 5 AI agents run locally via Ollama on RTX 5070 Ti (16 GB VRAM). Zero cloud dependency.

## User
- Name: **Matthieu**
- Language: French (conversations, commit messages, UI labels in French preferred)
- Priorities: Gaming (LoL etc.) coexists with 0Lith — VRAM is shared, never monopolized
- Vision: Autonomous system that learns patterns, predicts needs, suggests proactively

## Autonomy Levels (Critical Design Rule)
| Level | Behavior | Permission |
|-------|----------|------------|
| **0 — OBSERVE** | Read files, memorize, correlate, shadow think | None |
| **1 — SUGGEST** | Proactive notifications, recommendations | None (notification) |
| **2 — ACT** | Write/send/modify/execute | **EXPLICIT user approval** |

**Absolute rule**: 0Lith NEVER performs Level 2 actions without Matthieu's explicit "go". No emails sent, no files modified, no messages posted autonomously. Ever.

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
- Memory: Mem0 + Qdrant (Docker) + optional Kuzu graph
- Embeddings: qwen3-embedding:0.6b (1024 dimensions) via Ollama

## The 5 Agents (Cybersecurity Dock V1)
| Agent | Model | Role | Emoji | Color | VRAM | Location |
|-------|-------|------|-------|-------|------|----------|
| Hodolith | qwen3:1.7b | Dispatcher + Observer | 🟡 | #EAB308 | ~1.5 GB | local |
| Monolith | qwen3:14b | Orchestrator, general reasoning | 🔵 | #3B82F6 | ~10 GB | local |
| Aerolith | qwen3-coder:30b | Coder (slow but high quality) | 🟢 | #43AA8B | ~18 GB (CPU offload) | local |
| Cryolith | Foundation-Sec-8B | Blue Team defense | 🔷 | #0EA5E9 | ~5 GB | local |
| Pyrolith | DeepHat-V1-7B | Red Team offensive | 🔴 | #EF4444 | ~5 GB | Docker :11435 |

## Agent Dock Architecture
0Lith is built as a **dock**: fixed core + pluggable agent modules.

```
CORE (always active): Hodolith + Mem0 + Qdrant + qwen3-embedding:0.6b
DOCK Cybersec (V1):   Monolith, Aerolith, Cryolith, Pyrolith
DOCK Game Dev (M3+):  Storylith, Artlith, Gamelith (future YAML configs)
DOCK Personal (M4+):  Schedulith, Econolith (future YAML configs)
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
- **qwen3 /no_think**: qwen3 models use `<think>...</think>` by default. Mem0 fact extraction breaks without `/no_think`. Class-level monkey patch on `OllamaLLM.generate_response` is applied at module top of olith_core.py.
- **Windows cp1252**: stdout must be forced to UTF-8 (`io.TextIOWrapper`) for emoji support.
- **Hodolith routing**: Must strip `<think>` tags from qwen3 output before JSON parsing. Falls back to text matching if JSON parse fails.
- **Pyrolith Docker**: Uses Ollama API (`/api/chat`, `/api/tags`), NOT OpenAI-compatible endpoints.
- **Aerolith 30B**: Exceeds 16 GB VRAM, Ollama does CPU offload. Expect 3-5 min responses. Timeout set to 600s. Frontend MUST handle slow responses gracefully (progress indicator, no freeze).
- **Mem0 + Qdrant**: Qdrant must be running before olith_core.py starts. `docker start qdrant`.
- **Kuzu**: Optional. Only works with Python 3.12. System works fine without it (vector-only mode).

## Color Scheme
- Background primary: `#282C33`
- Background secondary: `#2F343E`
- Background tertiary: `#3A3F4B`
- NOT blue/slate — warm dark grays preferred
- Agent colors: Hodolith #EAB308, Monolith #3B82F6, Aerolith #43AA8B, Cryolith #0EA5E9, Pyrolith #EF4444

## Project Status
- [x] Phase 0: Ping-pong IPC prototype
- [x] Phase 1: Backend Python (olith_core.py, Hodolith routing, Mem0/Qdrant)
- [x] Phase 2: Frontend chat interface (sidebar, markdown, VRAM indicators, streaming)
- [x] Phase 3: Gaming mode (VRAM unload toggle)
- [x] Phase 3: System tray (background persistence, notifications)
- [x] Phase 3: Background loop (olith_watcher.py, file watcher, suggestions panel)
- [ ] Phase 3: Shadow Thinking (proactive memory preparation)
- [ ] Phase 3: Chat persistence (SQLite or JSON history)
- [ ] Future: Agent dock YAML configs
- [ ] Future: Game dev dock (Storylith, Artlith, Gamelith)
- [ ] Future: Personal dock (Schedulith, Econolith)
- [ ] Future: Google Takeout ingestion pipeline
- [ ] Future: Gaming habit learning (LoL stats, play patterns)

## Commands
- Dev: `cd C:\Users\skycr\Perso\0Lith\0lith-desktop && npm run tauri dev`
- Build: `npm run tauri build`
- Python backend deps: `cd py-backend && pip install -r requirements.txt`
- Qdrant Docker: `docker start qdrant` (port 6333)
- Pyrolith Docker: `docker start pyrolith` (port 11435, needs `--gpus all`)
- Memory init: `cd py-backend && python olith_memory_init.py`
- Memory test: `cd py-backend && python olith_memory_init.py --test`
- Memory reset: `cd py-backend && python olith_memory_init.py --reset`

## File Structure
```
0lith-desktop/
├── src-tauri/              # Rust/Tauri 2 backend
│   ├── src/lib.rs
│   ├── capabilities/default.json
│   └── tauri.conf.json
├── src/                    # Svelte 5 frontend
│   ├── lib/components/     # AgentCard, ChatInterface, MessageBubble, etc.
│   ├── lib/stores/         # agents.svelte.ts, suggestions.svelte.ts
│   ├── lib/types/          # agents.ts
│   └── App.svelte
├── py-backend/             # Python backend
│   ├── olith_core.py       # IPC chat (reactive)
│   ├── olith_watcher.py    # Background loop (proactive, Phase 3)
│   ├── olith_memory_init.py
│   └── requirements.txt
└── agents/                 # YAML agent configs (future Month 3)
```

## Design Principles
1. **Offline first**: Everything local. No cloud dependency. No API keys needed.
2. **VRAM is sacred**: Gaming always takes priority. 0Lith retreats silently.
3. **Memory is the moat**: Aerolith's advantage over Claude Code isn't intelligence — it's knowing Matthieu's patterns, style, and history after months of context.
4. **Each month is usable**: Never "under construction". Month 1 = good chat. Month 2 = proactive suggestions. Month 3 = pluggable agents. Stop at any point and it's still useful.
5. **Level 2 never without permission**: The system suggests, never acts autonomously.
