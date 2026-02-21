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
# MEM0 RESULT HELPERS
# ============================================================================

def extract_memories(results) -> list[dict]:
    """Normalise les résultats Mem0 (list ou dict avec 'results' key) en liste."""
    if isinstance(results, dict):
        return results.get("results", [])
    if isinstance(results, list):
        return results
    return []


def memory_text(mem) -> str:
    """Extrait le texte d'un résultat mémoire Mem0."""
    if isinstance(mem, dict):
        return mem.get("memory", mem.get("text", ""))
    return str(mem)


# ============================================================================
# RETRY HELPER
# ============================================================================

def retry_on_failure(fn, max_retries=3, base_delay=1.0, exceptions=None):
    """Retry avec exponential backoff. Retourne le résultat ou relève la dernière exception."""
    import time
    import requests as _req
    if exceptions is None:
        exceptions = (_req.exceptions.ConnectionError, _req.exceptions.Timeout)
    last_error = None
    for attempt in range(max_retries):
        try:
            return fn()
        except exceptions as e:
            last_error = e
            if attempt < max_retries - 1:
                delay = base_delay * (2 ** attempt)
                log_warn("retry", f"Attempt {attempt+1} failed: {e}. Retrying in {delay}s...")
                time.sleep(delay)
    raise last_error


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
