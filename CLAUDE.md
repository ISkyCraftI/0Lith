# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository Layout

The git root is `C:\Users\skycr\Perso\0Lith\`. The actual application lives in `0lith-desktop/`. There is a detailed `0lith-desktop/CLAUDE.md` — read it for in-depth architecture, gotchas, and design rules.

```
0Lith/
├── 0lith-desktop/      # Tauri 2 + Svelte 5 + Python desktop app
│   ├── src/            # Svelte 5 frontend
│   ├── src-tauri/      # Rust/Tauri 2 shell + capabilities
│   └── py-backend/     # Python 3.12 multi-agent backend
└── Reflexions/         # Research docs, market analysis, strategy
```

## Common Commands

All commands run from `0lith-desktop/` unless noted.

```bash
# Full dev (Tauri + Vite + Python IPC)
npm run tauri dev

# Production build
npm run tauri build

# TypeScript/Svelte type check
npm run check

# Python deps
pip install -r py-backend/requirements.txt

# External services (must be running before dev)
docker start qdrant        # Qdrant vector DB on :6333
docker start pyrolith      # Pyrolith LLM on :11435

# Memory management
python py-backend/olith_memory_init.py          # Init
python py-backend/olith_memory_init.py --test   # Verify
python py-backend/olith_memory_init.py --reset  # Wipe + re-init
```

## Architecture Summary

**Stack**: Tauri 2 · Svelte 5 runes · TypeScript · Python 3.12 · TailwindCSS 4

**IPC**: Two persistent Python processes are spawned at startup via `tauri-plugin-shell`:
- `olith_core.py` — reactive chat backend (command router → agent system → Ollama)
- `olith_watcher.py` — proactive background loop (file watcher, suggestions)

Both communicate via **JSON line-delimited stdin/stdout** with UUID-correlated requests/responses. The Tauri process CWD is `src-tauri/`, so shell spawn paths use `../py-backend/`.

**Agent routing**: Every user message hits `Hodolith` (qwen3:1.7b) first for classification, then routes to one of: Monolith (14b general), Aerolith (30b coder), Cryolith (8b blue team), Pyrolith (7b red team via Docker).

**Memory**: Mem0 + Qdrant (vector) + optional Kuzu (graph). Embeddings: qwen3-embedding:0.6b (1024 dims, code-aware, #1 MTEB Multilingual). MemOS v2.0 flagged for Phase 2 evaluation (Tool Memory, KV-cache injection).

**Key rules** (from `0lith-desktop/CLAUDE.md`):
- Python must be **3.12** (not 3.13+) — Kuzu requirement
- Svelte **5 runes only** — `$state`, `$derived`, `$effect` (no Svelte 4 `writable()`)
- **Tauri 2** — shell permissions live in `src-tauri/capabilities/default.json`
- qwen3 models emit `<think>...</think>` blocks — strip before parsing JSON routing responses
- Gaming Mode unloads all models from VRAM; 0Lith must never monopolize the RTX 5070 Ti

## Immediate Sprint Priorities

From `Reflexions/Matrice Einsenhower.md` — ranked by urgency and impact:

### This Week (Urgent + Important)
1. ~~**Repo cleanup**: fix `.gitignore` (remove `__pycache__`, `.obsidian` from tracking), clean cached files~~ **DONE** — gitignore enhanced, Reflexions/ staged, root CLAUDE.md committed
2. **English README**: pitch, demo GIF, hardware requirements, 5-step quickstart, roadmap
3. **AGPL-3.0 license**: add LICENSE file
4. **One working end-to-end demo**: red team OR blue team flow that can be shown

### Next 2-4 Weeks (Important)
5. Demo video 2-3 min (key content for r/LocalLLaMA, HN)
6. Installer bundle (.exe/.dmg with Ollama + models + Qdrant + GUI)
7. GitHub topics, issue templates, Sponsors activation
8. r/LocalLLaMA launch post preparation

### Feature Priorities (by impact)
1. Shadow Thinking (proactive memory anticipation) — 2-3 days
2. Conversation deletion + multi-select — 0.5 day
3. Sidebar tabs (Agents / History) — 1 day
4. OLithEye animated SVG — 1-2 days
5. MCP Server for Zed.dev — 2-3 days
6. Agents enfichables YAML (dock architecture) — 2-3 days

## Business Context

**Positioning**: Only tool combining multi-agents + desktop GUI + 100% local + cybersecurity specialization. No competitor covers all four.

**License**: AGPL-3.0 (open-source, copyleft for commercial forks)

**Revenue model**: GitHub Sponsors + commercial AGPL license + B2B consulting (NIS2/DORA compliance deployment)

**Market**: On-device AI $20-30B (2025), cybersecurity AI $30.9B → $86-104B by 2030. Regulatory tailwinds: NIS2 (Oct 2024), DORA (Jan 2025), EU AI Act.

**Window**: 18-36 months before Big Tech (Apple, Microsoft, Google) ships competitive local multi-agent desktop tools.

See `Reflexions/Etude de Marché.md` and `Reflexions/0Lith_et_marche_potentiel.md` for full analysis.

## Reflexions Reference

The `Reflexions/` folder contains research and strategy documentation:

| File | Content |
|------|---------|
| `0Lith_Memory_Architecture.md` | Full technical spec: Mem0 + Qdrant + Kuzu architecture, why NOT a Bibliolith LLM, multi-agent scoping, 5-level memory hierarchy |
| `0Lith_Embeddings_Memory_Research.md` | Embedding model comparison (Qwen3 vs Snowflake), MemOS/Memory-R1/Mem-α breakthroughs, phase roadmap |
| `Etude de Marché.md` | Market analysis ($30B cybersec AI), competitive landscape (25+ tools), regulatory tailwinds, business model, launch strategy |
| `Matrice Einsenhower.md` | Priority matrix for current sprint — repo cleanup, English README, AGPL, demo, launch prep |
| `IDEAS.md` | Full backlog with status tracking (same as root IDEAS.md, synced copy) |
| `Mission.md` | Original project charter with phase specs (same as root Mission.md, synced copy) |
| `idées de noms agents.md` | Agent naming conventions for future docks |

## Git specifiactions

Never push on Github by adding Claude or Claude Code as a coauthor. ISkyCraftI has to push alone.
