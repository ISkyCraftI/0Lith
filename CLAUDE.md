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
# Full dev — standard (no WDAC/HVCI restriction)
npm run tauri dev

# Full dev — WDAC/HVCI machine (Memory Integrity ON, signs binary after each Rust build)
# Terminal 1:
npm run dev                    # Vite HMR only
# Terminal 2 (PowerShell, from 0lith-desktop/):
.\scripts\dev-sign.ps1         # cargo build + sign + launch exe

# Production build
npm run tauri build

# TypeScript/Svelte type check
npm run check

# Python deps
pip install -r py-backend/requirements.txt

# External services (must be running before dev)
# Qdrant: no Docker needed — embedded mode, data in py-backend/qdrant_data/ (auto-created)
docker start pyrolith      # Pyrolith LLM on :11435 — pending Docker security hardening

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
- `olith_tasks.py` — `#User` tag detection + `~/.0lith/Tasks/User_needed.md` management (imported by core and agents)

Both communicate via **JSON line-delimited stdin/stdout** with UUID-correlated requests/responses. The Tauri process CWD is `src-tauri/`, so shell spawn paths use `../py-backend/`.

**Agent routing**: Every user message hits `Hodolith` (qwen3:1.7b) first for classification, then routes to one of: Monolith (14b general), Aerolith (30b coder), Cryolith (8b blue team), Pyrolith (7b red team via Docker).

**Memory**: Mem0 + Qdrant (currently Docker, pending migration to embedded `QdrantClient(path=...)`) + optional Kuzu (graph). Embeddings: qwen3-embedding:0.6b (1024 dims, code-aware, #1 MTEB Multilingual). MemOS v2.0 flagged for Phase 2 evaluation (Tool Memory, KV-cache injection).

**Key rules** (from `0lith-desktop/CLAUDE.md`):
- Python must be **3.12** (not 3.13+) — Kuzu requirement
- Svelte **5 runes only** — `$state`, `$derived`, `$effect` (no Svelte 4 `writable()`)
- **Tauri 2** — shell permissions live in `src-tauri/capabilities/default.json`
- qwen3 models emit `<think>...</think>` blocks — strip before parsing JSON routing responses
- Gaming Mode unloads all models from VRAM; 0Lith must never monopolize the RTX 5070 Ti
- `.claude/` and `__pycache__/` are in `.gitignore` ✓ — verified
- `#User` tag — agents emit `#User <question>` on its own line when blocked; `olith_tasks.py` logs to `~/.0lith/Tasks/User_needed.md`; items marked `[x]` are auto-removed on next chat; IPC: `list_tasks`, `resolve_tasks`

## Immediate Sprint Priorities

From `Reflexions/Matrice Einsenhower.md` — ranked by urgency and impact:

### This Week (Urgent + Important)
1. ~~**Repo cleanup**: fix `.gitignore` (remove `__pycache__`, `.obsidian` from tracking), clean cached files~~ **DONE** — gitignore enhanced, Reflexions/ staged, root CLAUDE.md committed
2. ~~**English README**: pitch, demo GIF, hardware requirements, 5-step quickstart, roadmap~~ **DONE** — README.md rewritten in English, README.fr.md kept as French copy (with 🇫🇷/🇬🇧 links)
3. ~~**AGPL-3.0 license**: add LICENSE file~~ **DONE** — LICENSE added at root
4. ~~**One working end-to-end demo**: red team OR blue team flow~~ **DONE** — Arena v2: SQL Injection sparring (5 rounds, live streaming, score + review) + UX v2: scenario selector, round progress dots, Unicode badges, loading animation, winner badge, export log + robustesse: timeouts adaptatifs par modèle, fallback automatique qwen3:14b, séquences de types forcées, contexte réduit (max 2 rounds), session 30 min

### Next 2-4 Weeks (Important)
5. Demo video 2-3 min (key content for r/LocalLLaMA, HN)
6. Installer bundle (.exe/.dmg with Ollama + models + Qdrant + GUI)
7. GitHub topics, issue templates, Sponsors activation
8. r/LocalLLaMA launch post preparation

### Critical — Infrastructure & Security
1. ~~**Qdrant embedded mode**: replace Docker with `QdrantClient(path="./qdrant_data")` in `olith_memory_init.py` — removes `docker start qdrant` requirement entirely~~ **DONE**
2. **Pyrolith Docker hardening**: non-root user, `--cap-drop=ALL`, isolated bridge network, no outbound internet by default
3. **Shadow Thinking** — 2-3 days *(olith_watcher.py shadow loop exists; Mem0 pre-answer storage needs wiring to chat)*

### High — Next sprint
4. **Agent output JSON schema**: standardize structured responses to prevent frontend parse bugs
5. **Aerolith loading UI**: "Aerolith réfléchit… 3-5 min", progress bar, cancel — don't drop the 30B, make the wait dignified
6. ~~**Hodolith routing clarity**: Monolith *plans/reasons about* code, Aerolith *writes* code — update routing prompt~~ **DONE** — prompts rewritten in English with explicit Monolith/Aerolith boundary
7. Conversation deletion + multi-select — 0.5 day

### Medium — Month 2-3
8. Startup health checks (Ollama up? models pulled? Pyrolith container ready?)
9. Memory token budget (≤ 512 tokens injected into small model contexts)
10. Monthly memory pruning (Monolith reviews Mem0 entries > 30 days)
11. Training Mode (Pyrolith vs Cryolith CVE sparring overnight + morning briefing)
12. Sidebar tabs (Agents / History) — 1 day
13. OLithEye animated SVG — 1-2 days
14. MCP Server for Zed.dev — 2-3 days
15. Agents enfichables YAML (dock architecture) — 2-3 days

## Business Context

**Positioning**: Only tool combining multi-agents + desktop GUI + 100% local + cybersecurity specialization. No competitor covers all four.

**License**: AGPL-3.0 (open-source, copyleft for commercial forks)

**Revenue model**: GitHub Sponsors + commercial AGPL license + B2B consulting (NIS2/DORA compliance deployment)

**Market**: On-device AI $20-30B (2025), cybersecurity AI $30.9B → $86-104B by 2030. Regulatory tailwinds: NIS2 (Oct 2024), DORA (Jan 2025), EU AI Act.

**Window**: 18-36 months before Big Tech (Apple, Microsoft, Google) ships competitive local multi-agent desktop tools.


## Git specifiactions

Never push on Github by adding Claude or Claude Code as a coauthor. ISkyCraftI has to push alone.
