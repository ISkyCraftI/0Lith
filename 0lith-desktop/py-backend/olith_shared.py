#!/usr/bin/env python3
"""
0Lith V1 — Shared Constants, Utilities, and Mem0 Patch
========================================================
Module partagé entre olith_core.py et olith_watcher.py.
Évite la duplication de code.
"""

import sys
import re

# ============================================================================
# MEM0 MONKEY-PATCH — Disable qwen3 <think> blocks in Mem0 fact extraction
# ============================================================================

def patch_mem0_ollama():
    """Patch Mem0's OllamaLLM to append /no_think to user messages.
    Must be called BEFORE any Mem0 import that triggers LLM usage."""
    try:
        from mem0.llms.ollama import OllamaLLM as _OllamaLLM

        _orig_generate = _OllamaLLM.generate_response

        def _patched_generate(self, messages, **kwargs):
            for msg in messages:
                if msg.get("role") == "user":
                    msg["content"] += " /no_think"
            return _orig_generate(self, messages, **kwargs)

        _OllamaLLM.generate_response = _patched_generate
    except ImportError:
        pass  # mem0 not installed


# Apply patch on import
patch_mem0_ollama()


# ============================================================================
# LOGGING
# ============================================================================

def log_warn(context: str, message: str):
    """Log a warning to stderr (visible in Tauri devtools, not in IPC stdout)."""
    sys.stderr.write(f"[WARN] [{context}] {message}\n")
    sys.stderr.flush()


def log_error(context: str, message: str):
    """Log an error to stderr."""
    sys.stderr.write(f"[ERROR] [{context}] {message}\n")
    sys.stderr.flush()


def log_info(context: str, message: str):
    """Log info to stderr."""
    sys.stderr.write(f"[INFO] [{context}] {message}\n")
    sys.stderr.flush()


# ============================================================================
# TEXT PROCESSING
# ============================================================================

def strip_think_blocks(text: str) -> str:
    """Remove qwen3 <think>...</think> blocks from a response."""
    return re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL).strip()


# ============================================================================
# SHARED CONSTANTS
# ============================================================================

# Extensions de fichiers lisibles (eviter les binaires)
TEXT_EXTENSIONS = {
    ".py", ".js", ".ts", ".svelte", ".rs", ".json", ".yaml", ".yml",
    ".toml", ".md", ".css", ".html", ".sh", ".ps1", ".bat", ".txt",
    ".cfg", ".ini", ".env", ".lock", ".sql", ".vue", ".jsx", ".tsx",
    ".go", ".java", ".c", ".cpp", ".h", ".hpp", ".rb", ".php",
    ".xml", ".csv", ".dockerfile", ".gitignore", ".editorconfig",
}

# Repertoires toujours ignores
IGNORED_DIRS = {
    "node_modules", ".git", "__pycache__", "target", "dist",
    ".svelte-kit", "build", ".next", "venv", ".venv", "env",
    ".ollama", ".cache", ".npm", ".yarn",
}

# Extensions surveillees par le watcher
WATCHED_EXTENSIONS = {
    '.py', '.js', '.ts', '.svelte', '.rs', '.json', '.yaml', '.yml',
    '.toml', '.md', '.css', '.html', '.sh', '.ps1', '.bat',
}

# Couleurs hex des agents
AGENT_COLORS = {
    "hodolith": "#FFB02E",
    "monolith": "#181A1E",
    "aerolith": "#43AA8B",
    "cryolith": "#7BDFF2",
    "pyrolith": "#BF0603",
}

AGENT_EMOJIS = {
    "hodolith": "🟨",
    "monolith": "⬛",
    "aerolith": "⬜",
    "cryolith": "🟦",
    "pyrolith": "🟥",
}
