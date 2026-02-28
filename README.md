<p align="center">
  <img src="Logo_texture.svg" alt="0Lith" width="100" />
</p>

<h1 align="center">0Lith</h1>

<p align="center">
  Your sovereign, local, multi-agent AI cockpit.<br/>
  Cybersecurity · Development · Anticipation.
</p>

<p align="center">
  <img src="https://img.shields.io/badge/status-alpha%20v0.1-orange" />
  <img src="https://img.shields.io/badge/license-AGPL--3.0-blue" />
  <img src="https://img.shields.io/badge/python-3.12-blue" />
  <img src="https://img.shields.io/badge/Tauri-2-purple" />
  <img src="https://img.shields.io/badge/platform-Windows%20%7C%20Linux-lightgrey" />
  <img src="https://img.shields.io/badge/GPU-RTX%205070%20Ti%2016%20GB-green" />
</p>

---

## What is 0Lith?

0Lith (pronounced "Olith") is a **personal multi-agent AI cockpit** that runs **entirely offline** — no cloud, no paid API, no data leaving your machine. Five specialized agents collaborate through an intelligent dispatcher, share persistent memory, and learn your habits over time.

Born on February 6, 2025 with a single conviction: a personal AI assistant should run on **your** hardware, know **your** context after months of use, and never depend on a third-party server. 0Lith is the only open-source tool that combines multi-agent orchestration, a native desktop GUI, 100% local execution, and cybersecurity specialization.

## Demo

<p align="center">
  <img src="docs/screenshot.png" alt="0Lith screenshot" width="700" />
</p>

> Demo GIF coming soon.

## Agents

| Agent | Role | Model | Specialty |
|-------|------|-------|-----------|
| **Hodolith** | Dispatcher | Qwen3 1.7B | Classifies every message and routes it to the right agent. Always in VRAM (~2 GB). |
| **Monolith** | Orchestrator | Qwen3 14B | Chain-of-thought reasoning, planning, coordination. |
| **Aerolith** | Coder | Qwen3 Coder 30B | Code generation, review, and debugging. CPU offload (~5 min per response). |
| **Cryolith** | Blue Team | Foundation-Sec 8B | Log analysis, anomaly detection, SIEM rules. |
| **Pyrolith** | Red Team | DeepHat V1 7B | Pentesting, CTF, exploitation. Sandboxed in Docker. |

Agent names follow a Greek convention: *Hodo-* (path), *Mono-* (single), *Aero-* (air), *Pyro-* (fire), *Cryo-* (ice) — all with the *-lith* suffix (stone) meaning solid foundation.

## Architecture

```
┌──────────────────────────────────────────────┐
│  Tauri 2 (Rust)          Svelte 5 (Frontend) │
│  ├─ Sidecar Python ◄────► IPC stdin/stdout   │
│  └─ Window management     Chat + Sidebar     │
├──────────────────────────────────────────────┤
│  Python Backend                               │
│  ├─ olith_core.py      Reactive chat (IPC)   │
│  ├─ olith_agents.py    Routing + execution   │
│  ├─ olith_watcher.py   Proactive background  │
│  ├─ olith_history.py   Session persistence   │
│  ├─ olith_tools.py     Sandboxed tools       │
│  └─ olith_shared.py    Shared helpers        │
├──────────────────────────────────────────────┤
│  Local Infrastructure                         │
│  ├─ Ollama             LLM inference         │
│  ├─ Qdrant             Vector database       │
│  ├─ Mem0               Intelligent memory    │
│  └─ Docker             Pyrolith isolation    │
└──────────────────────────────────────────────┘
```

## Hardware Requirements

| Component | Requirement | Notes |
|-----------|-------------|-------|
| **GPU** | NVIDIA ≥ 12 GB VRAM | Tested on RTX 5070 Ti 16 GB (Blackwell) |
| **RAM** | 32 GB recommended | Agents + Python overhead + OS headroom |
| **Storage** | 100 GB+ NVMe | OS + Ollama model cache + Qdrant indexes |
| **OS** | Windows 10/11 or Linux (Ubuntu 22+) | Windows 11 recommended |

### VRAM budget (16 GB example)

| Always loaded | ~2 GB | Hodolith (1.5 GB) + embedding model (0.6 GB) |
|---------------|-------|----------------------------------------------|
| Monolith on demand | ~10 GB | Total ~12 GB / 16 GB |
| Cryolith on demand | ~5 GB | Total ~7 GB / 16 GB |
| Aerolith on demand | ~18 GB | CPU offload — slow but functional |
| Pyrolith (Docker) | ~5 GB | Separate VRAM pool via `--gpus all` |

> **Gaming Mode**: all models unloaded → 0 GB used by 0Lith → full VRAM free for games.

## Prerequisites

- [Ollama](https://ollama.com) **≥ 0.16.1** — required for RTX 5070 Ti / Blackwell GPU support (0.15.x silently falls back to CPU)
- [Docker Desktop](https://docker.com) — for Qdrant vector DB and Pyrolith sandbox
- [Node.js](https://nodejs.org) ≥ 18
- [Rust](https://rustup.rs) (for Tauri compilation)
- **Python 3.12** — not 3.13+, Kuzu graph DB is incompatible

## Quickstart

```bash
# 1. Clone the repository
git clone https://github.com/ISkyCraftI/0Lith.git
cd 0Lith
```

```bash
# 2. Pull Ollama models
ollama pull qwen3:1.7b               # Hodolith — dispatcher
ollama pull qwen3:14b                # Monolith — orchestrator
ollama pull qwen3-coder:30b          # Aerolith — coder
ollama pull qwen3-embedding:0.6b     # Embeddings (1024 dims, code-aware)
ollama pull hf.co/fdtn-ai/Foundation-Sec-8B-Q4_K_M-GGUF  # Cryolith
```

```bash
# 3. Start Docker services
# Qdrant vector database
docker run -d --name qdrant -p 6333:6333 -p 6334:6334 \
  -v ~/.qdrant/storage:/qdrant/storage qdrant/qdrant

# Pyrolith — red team agent (isolated Ollama instance)
docker run -d --name pyrolith -p 11435:11434 --gpus all ollama/ollama
docker exec pyrolith ollama pull deephat/DeepHat-V1-7B
```

```bash
# 4. Install Python dependencies and initialize memory
cd 0lith-desktop/py-backend
pip install -r requirements.txt
python olith_memory_init.py
```

```bash
# 5. Install frontend dependencies and launch
cd ..
npm install
npm run tauri dev
```

## Ollama Configuration

Recommended environment variables for rotating model loading on 16 GB VRAM:

```bash
OLLAMA_MAX_LOADED_MODELS=2     # Max 2 models in VRAM simultaneously
OLLAMA_KEEP_ALIVE=5m           # Release VRAM after 5 min idle
OLLAMA_NUM_PARALLEL=1          # One thread per model (saves VRAM)
OLLAMA_FLASH_ATTENTION=true    # Flash attention
OLLAMA_KV_CACHE_TYPE=q8_0      # Quantized KV cache
```

## Tech Stack

| Layer | Technology | Role |
|-------|-----------|------|
| Desktop | Tauri 2 (Rust) | Native window, Python sidecar, IPC |
| Frontend | Svelte 5 (runes) | Reactive UI, chat, sidebar |
| Backend | Python 3.12 | Agents, routing, memory, tools |
| Inference | Ollama (llama.cpp) | Quantized GGUF models Q4_K_M |
| Embeddings | qwen3-embedding:0.6b | #1 MTEB Multilingual, 1024 dims, code-aware |
| Memory | Mem0 + Qdrant | Fact extraction, semantic search |
| Graph | Kuzu (optional) | Knowledge graph, multi-hop relations |
| Isolation | Docker | Sandbox for the offensive agent |
| Styling | TailwindCSS 4 + bits-ui | UI components, dark theme |

## Features (v0.1)

- [x] Multi-agent chat with automatic routing via Hodolith
- [x] Real-time streaming responses
- [x] Shared memory across agents (Mem0 + Qdrant + qwen3-embedding:0.6b)
- [x] Session persistence (JSON, `~/.0lith/chats/`)
- [x] Session history in the sidebar
- [x] Sandboxed filesystem tools (path validation, symlink protection)
- [x] Graceful response cancellation (IPC + fallback kill)
- [x] Exponential backoff retry (Ollama, Mem0)
- [x] Intelligent memory filtering (ignores trivial messages)
- [x] Cross-platform system info (psutil)
- [x] Status indicators: Backend, Ollama, Qdrant
- [x] Gaming Mode (full VRAM release)
- [x] System Tray (background persistence, notifications, Gaming Mode menu)
- [x] Proactive background loop (olith_watcher.py, file watcher, suggestions panel)
- [x] Sandboxed tools for agents (file read/search, system info)

## Roadmap

```
DONE ────────────────────────────────────────
✅ Phase 0 : Svelte ↔ Tauri ↔ Python IPC prototype
✅ Phase 1 : Full Python backend (agents, Hodolith routing, Mem0/Qdrant)
✅ Phase 2 : Chat interface (agent sidebar, streaming, markdown, dark theme)
✅ Phase 3 : Gaming Mode (VRAM unload, sidebar + tray toggle)
✅ Phase 3 : System Tray (background, notifications, Show/Hide/Quit)
✅ Phase 3 : Background loop (file watcher, proactive suggestions)
✅ Security : filesystem sandbox, lane queue, IPC cancel, retry + backoff
✅ Persistence : JSON sessions, history sidebar

SHORT TERM ──────────────────────────────────
⬜ Shadow Thinking (proactive memory anticipation via Mem0)
⬜ OLithEye animated SVG (dynamic logo, color per agent)
⬜ Sidebar tabs (Agents / History separated)
⬜ MCP Server for Zed.dev

MEDIUM TERM ─────────────────────────────────
⬜ Pluggable agents via YAML (dock architecture)
⬜ Game Dev dock (Storylith, Artlith, Gamelith)
⬜ Personal dock (Schedulith, Econolith)
⬜ Overnight sparring: Pyrolith vs Cryolith on CVEs

LONG TERM ───────────────────────────────────
⬜ Google Takeout ingestion pipeline
⬜ Calendar + health data integration
⬜ Per-agent LoRA fine-tuning (QLoRA via Unsloth)
⬜ Multi-machine network (Tailscale)
⬜ MemOS migration (when mature)
```

## Philosophy

**Offline first** — Everything runs locally. No cloud. No API keys. No network dependency.

**VRAM is sacred** — Gaming always has priority. 0Lith retreats silently when you launch a game.

**Memory is the moat** — 0Lith's advantage over Claude or GPT isn't raw intelligence — it's that after months of use, it knows your patterns, your style, and your context.

**Each month is usable** — Never "under construction". Month 1 = good chat. Month 2 = proactive suggestions. Month 3 = pluggable agents. Stop at any point and it's already useful.

**Level 2 never without permission** — The system observes and suggests, but never acts autonomously on critical actions.

## Contributing

The project is in alpha and developed solo for now. Issues and suggestions are welcome.

**License note**: 0Lith is AGPL-3.0. Commercial use or distribution requires either compliance with AGPL (open-sourcing your modifications) or a separate commercial license agreement.

## License

[GNU Affero General Public License v3.0](LICENSE) — Copyright (C) 2025 ISkyCraftI

---

<p align="center">
  <em>Forged in stone, sharpened by fire, protected by ice.</em>
</p>
