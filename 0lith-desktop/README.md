# 0lith-desktop

Tauri 2 + Svelte 5 + Python frontend/backend for the 0Lith project.

> For the full project README (pitch, quickstart, roadmap), see the [root README](../README.md).

## Structure

```
0lith-desktop/
├── src/                    # Svelte 5 frontend
│   ├── components/         # UI components + Svelte stores
│   │   └── stores/         # watcher.svelte.ts, backend.svelte.ts, etc.
│   ├── lib/                # ipc.ts (type definitions), helpers
│   └── App.svelte          # Root component
├── src-tauri/              # Tauri 2 shell
│   ├── capabilities/       # Shell permissions (default.json)
│   ├── src/                # Rust main + lib
│   └── tauri.conf.json     # App config
└── py-backend/             # Python 3.12 multi-agent backend
    ├── olith_core.py       # Reactive chat (IPC)
    ├── olith_agents.py     # Agent routing + execution
    ├── olith_watcher.py    # Proactive background loop
    ├── olith_history.py    # Session persistence
    ├── olith_tools.py      # Sandboxed tools
    ├── olith_shared.py     # Shared helpers
    ├── olith_memory_init.py
    └── requirements.txt
```

## Dev commands

```bash
# Full dev (Tauri + Vite + Python IPC)
npm run tauri dev

# Production build
npm run tauri build

# TypeScript/Svelte type check
npm run check

# Python deps
pip install -r py-backend/requirements.txt

# Memory management
python py-backend/olith_memory_init.py          # Init
python py-backend/olith_memory_init.py --test   # Verify
python py-backend/olith_memory_init.py --reset  # Wipe + re-init
```

## Key rules

- **Svelte 5 runes only** — `$state`, `$derived`, `$effect` (no Svelte 4 `writable()`)
- **Tauri 2** — shell permissions live in `src-tauri/capabilities/default.json`
- **Python 3.12** — not 3.13+, Kuzu is incompatible
- **Tauri CWD** is `src-tauri/` — Python spawn paths use `../py-backend/`
- qwen3 models emit `<think>...</think>` blocks — strip before parsing JSON

See [CLAUDE.md](CLAUDE.md) for full architecture details and gotchas.
