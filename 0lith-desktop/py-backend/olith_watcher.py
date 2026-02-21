#!/usr/bin/env python3
"""
0Lith V1 — Background Watcher (Level 0-1: Observe & Suggest)
==============================================================
Separate process from olith_core.py. Launched in parallel by Tauri.

Protocol (push-based, NOT request-response):
  Output: {"event": "suggestion", "type": "file_change|schedule|shadow", "id": "uuid", "text": "...", "context": {...}, "timestamp": 1234}
  Output: {"event": "status", "watching": true, "watch_dir": "...", "paused": false, "ollama_available": true}
  Input:  {"command": "pause|resume|set_watch_dir|feedback", ...}

CRITICAL: This process NEVER performs Level 2 actions. Observe and suggest ONLY.
"""

import sys
import io
import os
import json
import uuid
import time
import copy
import threading
import hashlib
import traceback
from pathlib import Path
from collections import deque

import requests
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

# Force UTF-8 (same pattern as olith_core.py — Windows uses cp1252 by default)
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stdin = io.TextIOWrapper(sys.stdin.buffer, encoding='utf-8')

# Shared utilities (also applies Mem0 /no_think patch on import)
from olith_shared import (
    strip_think_blocks, log_warn, log_error, log_info,
    extract_memories, memory_text,
    WATCHED_EXTENSIONS as _SHARED_WATCHED,
    IGNORED_DIRS as _SHARED_IGNORED,
)

from olith_memory_init import (
    MEM0_CONFIG,
    OLLAMA_URL,
    QDRANT_URL,
    check_service,
)

# ============================================================================
# CONSTANTS
# ============================================================================

DEBOUNCE_SECONDS = 3.0
SHADOW_THINK_INTERVAL = 300  # 5 minutes
STATUS_INTERVAL = 30         # 30 seconds
MAX_DIFF_FILES = 10
HODOLITH_MODEL = "qwen3:1.7b"  # Small model only — VRAM is sacred

WATCHED_EXTENSIONS = _SHARED_WATCHED
IGNORED_DIRS = _SHARED_IGNORED

SCHEDULE_PATH = Path.home() / ".0lith" / "schedule.json"


# ============================================================================
# EMIT HELPERS
# ============================================================================

def emit(data: dict):
    """Send a JSON line to stdout (to frontend)."""
    try:
        print(json.dumps(data, ensure_ascii=False), flush=True)
    except Exception as e:
        log_warn("watcher_emit", f"Failed to emit: {e}")


def emit_suggestion(type_: str, text: str, context: dict) -> str:
    """Emit a suggestion event. Returns the suggestion ID."""
    suggestion_id = str(uuid.uuid4())
    emit({
        "event": "suggestion",
        "type": type_,
        "id": suggestion_id,
        "text": text,
        "context": context,
        "timestamp": int(time.time() * 1000),
    })
    return suggestion_id


def emit_status(watcher):
    """Emit current watcher status."""
    emit({
        "event": "status",
        "watching": watcher.watching,
        "watch_dir": str(watcher.watch_dir) if watcher.watch_dir else "",
        "paused": watcher.paused,
        "ollama_available": watcher.ollama_available,
    })


# ============================================================================
# FILE CHANGE HANDLER (watchdog)
# ============================================================================

class DebouncedFileHandler(FileSystemEventHandler):
    """Collects file changes, debounces, then triggers analysis."""

    def __init__(self, watcher):
        super().__init__()
        self.watcher = watcher
        self.pending_changes = {}  # path -> event_type
        self.timer = None
        self.lock = threading.Lock()

    def _should_watch(self, path: str) -> bool:
        """Filter by extension and ignore patterns."""
        p = Path(path)
        for part in p.parts:
            if part in IGNORED_DIRS:
                return False
        return p.suffix.lower() in WATCHED_EXTENSIONS

    def on_any_event(self, event):
        if event.is_directory:
            return
        if not self._should_watch(event.src_path):
            return
        if self.watcher.paused:
            return

        with self.lock:
            self.pending_changes[event.src_path] = event.event_type

            if self.timer:
                self.timer.cancel()
            self.timer = threading.Timer(
                DEBOUNCE_SECONDS,
                self._flush_changes
            )
            self.timer.daemon = True
            self.timer.start()

    def _flush_changes(self):
        """Called after debounce period. Triggers analysis."""
        with self.lock:
            if not self.pending_changes:
                return
            changes = dict(self.pending_changes)
            self.pending_changes.clear()

        threading.Thread(
            target=self.watcher.analyze_changes,
            args=(changes,),
            daemon=True,
        ).start()


# ============================================================================
# MAIN WATCHER CLASS
# ============================================================================

class OlithWatcher:
    def __init__(self, watch_dir=None):
        self.watch_dir = Path(watch_dir) if watch_dir else None
        self.watching = False
        self.paused = False
        self.ollama_available = False
        self.memory = None
        self.observer = None
        self.file_handler = None
        self.recent_suggestions = deque(maxlen=20)
        self._init_lock = threading.Lock()

    def start_watching(self):
        """Start the watchdog observer on the configured directory."""
        if not self.watch_dir or not self.watch_dir.exists():
            return
        if self.observer and self.observer.is_alive():
            return

        self.file_handler = DebouncedFileHandler(self)
        self.observer = Observer()
        self.observer.schedule(
            self.file_handler,
            str(self.watch_dir),
            recursive=True,
        )
        self.observer.daemon = True
        self.observer.start()
        self.watching = True

    def stop_watching(self):
        """Stop the watchdog observer."""
        if self.observer and self.observer.is_alive():
            self.observer.stop()
            self.observer.join(timeout=5)
        self.observer = None
        self.watching = False

    def _ensure_memory(self):
        """Lazy-init Mem0 (same pattern as olith_core.py)."""
        if self.memory:
            return True
        with self._init_lock:
            if self.memory:
                return True
            try:
                if not check_service("Qdrant", f"{QDRANT_URL}/collections"):
                    return False
                config = copy.deepcopy(MEM0_CONFIG)
                try:
                    import kuzu  # noqa: F401
                except ImportError:
                    config.pop("graph_store", None)
                from mem0 import Memory
                self.memory = Memory.from_config(config_dict=config)
                return True
            except Exception as e:
                log_warn("watcher_memory", f"Mem0 init failed: {e}")
                return False

    def _check_ollama(self) -> bool:
        """Check if Ollama is available."""
        try:
            r = requests.get(f"{OLLAMA_URL}/api/tags", timeout=3)
            self.ollama_available = r.status_code == 200
        except Exception:
            self.ollama_available = False  # Expected when Ollama is not running
        return self.ollama_available

    def _call_hodolith(self, prompt: str, timeout: int = 30):
        """Call qwen3:1.7b for analysis. Returns None if unavailable."""
        if not self._check_ollama():
            return None
        try:
            response = requests.post(
                f"{OLLAMA_URL}/api/chat",
                json={
                    "model": HODOLITH_MODEL,
                    "messages": [
                        {"role": "system", "content":
                            "Tu es un assistant d'analyse de code. "
                            "Analyse les changements et suggere les prochaines etapes. "
                            "Reponds en 1-2 phrases concises. /no_think"
                        },
                        {"role": "user", "content": prompt + " /no_think"},
                    ],
                    "stream": False,
                    "keep_alive": "5m",
                    "options": {"num_ctx": 2048},
                },
                timeout=timeout,
            )
            response.raise_for_status()
            text = response.json()["message"]["content"]
            text = strip_think_blocks(text)
            return text
        except Exception as e:
            log_warn("watcher_hodolith", f"Call failed: {e}")
            return None

    def analyze_changes(self, changes: dict):
        """Analyze file changes and emit suggestions."""
        if self.paused or not changes:
            return

        file_list = list(changes.keys())[:MAX_DIFF_FILES]
        summary_lines = []
        for path, event_type in list(changes.items())[:MAX_DIFF_FILES]:
            rel = path
            if self.watch_dir:
                try:
                    rel = str(Path(path).relative_to(self.watch_dir))
                except ValueError:
                    pass
            summary_lines.append(f"  {event_type}: {rel}")

        change_summary = "\n".join(summary_lines)

        # Deduplicate
        content_hash = hashlib.md5(change_summary.encode()).hexdigest()[:8]
        if content_hash in self.recent_suggestions:
            return
        self.recent_suggestions.append(content_hash)

        # Try AI analysis (graceful degradation if Ollama is down)
        analysis = self._call_hodolith(
            f"Fichiers modifies dans le projet:\n{change_summary}\n\n"
            f"Quel est le prochain pas logique? Que devrait faire le developpeur?"
        )

        if analysis:
            suggestion_id = emit_suggestion(
                "file_change",
                analysis,
                {"files": file_list, "diff_summary": change_summary},
            )
            self._store_shadow_thinking(
                f"File changes detected: {change_summary}\nAnalysis: {analysis}",
                {"suggestion_id": suggestion_id, "type": "file_change"},
            )
        else:
            # Ollama unavailable — emit a simpler suggestion without AI
            if len(changes) >= 3:
                emit_suggestion(
                    "file_change",
                    f"{len(changes)} fichiers modifies recemment.",
                    {"files": file_list, "diff_summary": change_summary},
                )

    def _store_shadow_thinking(self, text: str, metadata: dict):
        """Store pre-analyzed result in Mem0 with shadow_thinking tag."""
        if not self._ensure_memory():
            return
        try:
            self.memory.add(
                text + " /no_think",
                user_id="hodolith",
                metadata={
                    "type": "shadow_thinking",
                    "user_id": "hodolith",
                    **metadata,
                    "timestamp": int(time.time()),
                },
            )
        except Exception as e:
            log_warn("watcher_shadow_store", f"Failed to store shadow thinking: {e}")

    def store_feedback(self, suggestion_id: str, action: str, modified_text=None):
        """Store user feedback about a suggestion in Mem0."""
        if not self._ensure_memory():
            return
        feedback_map = {
            "accepted": "prediction correct - user accepted the suggestion",
            "dismissed": "wrong direction - user dismissed the suggestion, adjust",
            "modified": f"user prefers a different approach: {modified_text or 'unspecified'}",
        }
        feedback_text = feedback_map.get(action, f"feedback: {action}")
        try:
            self.memory.add(
                f"{feedback_text} (suggestion_id: {suggestion_id}) /no_think",
                user_id="hodolith",
                metadata={
                    "type": "prediction_feedback",
                    "user_id": "hodolith",
                    "suggestion_id": suggestion_id,
                    "action": action,
                },
            )
        except Exception as e:
            log_warn("watcher_feedback", f"Failed to store feedback: {e}")

    def check_schedule(self):
        """Check schedule.json for upcoming events / free slots."""
        if not SCHEDULE_PATH.exists():
            return
        try:
            with open(SCHEDULE_PATH, 'r', encoding='utf-8') as f:
                schedule = json.load(f)
            now = int(time.time())
            events = schedule.get("events", [])
            for event in events:
                start = event.get("start_ts", 0)
                if 0 < (start - now) < 1800:  # within 30 minutes
                    emit_suggestion(
                        "schedule",
                        f"Evenement dans {(start - now) // 60} min: {event.get('title', '?')}",
                        {"schedule_slot": event.get("title", "")},
                    )
        except Exception as e:
            log_warn("watcher_schedule", f"Schedule check failed: {e}")

    def shadow_think_cycle(self):
        """Periodic shadow thinking: analyze recent activity, pre-prepare answers."""
        if self.paused or not self._check_ollama():
            return
        if not self._ensure_memory():
            return

        try:
            results = self.memory.search(
                "recent file changes and project activity",
                user_id="hodolith",
                limit=3,
            )
            memories = extract_memories(results)

            if not memories:
                return

            context_texts = []
            for mem in memories:
                text = memory_text(mem)
                if text:
                    context_texts.append(text)

            if not context_texts:
                return

            analysis = self._call_hodolith(
                "Contexte recent du projet:\n" +
                "\n".join(f"- {t[:200]}" for t in context_texts) +
                "\n\nQue pourrait demander l'utilisateur bientot? "
                "Pre-prepare une reponse utile."
            )

            if analysis:
                self._store_shadow_thinking(
                    f"Shadow thinking: {analysis}",
                    {"type": "shadow"},
                )
                emit_suggestion(
                    "shadow",
                    analysis,
                    {"shadow_query": "proactive analysis"},
                )
        except Exception as e:
            log_warn("watcher_shadow", f"Shadow think cycle failed: {e}")

    def handle_stdin_command(self, cmd: dict):
        """Process a command from the frontend."""
        command = cmd.get("command", "")

        if command == "pause":
            self.paused = True
            emit_status(self)

        elif command == "resume":
            self.paused = False
            emit_status(self)

        elif command == "set_watch_dir":
            new_dir = cmd.get("watch_dir", "")
            if new_dir:
                new_path = Path(new_dir).resolve()
                home = Path.home().resolve()
                # Security: only allow directories under user's home
                if new_path.exists() and new_path.is_dir() and str(new_path).startswith(str(home)):
                    self.stop_watching()
                    self.watch_dir = new_path
                    self.start_watching()
            emit_status(self)

        elif command == "feedback":
            suggestion_id = cmd.get("suggestion_id", "")
            action = cmd.get("action", "")
            modified_text = cmd.get("modified_text")
            if suggestion_id and action:
                threading.Thread(
                    target=self.store_feedback,
                    args=(suggestion_id, action, modified_text),
                    daemon=True,
                ).start()


# ============================================================================
# MAIN
# ============================================================================

def main():
    watch_dir = None
    if len(sys.argv) > 1:
        watch_dir = sys.argv[1]

    watcher = OlithWatcher(watch_dir)

    if watcher.watch_dir:
        watcher.start_watching()

    watcher._check_ollama()
    emit_status(watcher)

    def periodic_loop():
        last_schedule_check = 0
        last_shadow_think = 0
        last_status = 0
        while True:
            now = time.time()
            try:
                if now - last_status >= STATUS_INTERVAL:
                    watcher._check_ollama()
                    emit_status(watcher)
                    last_status = now

                if now - last_schedule_check >= 300:
                    watcher.check_schedule()
                    last_schedule_check = now

                if now - last_shadow_think >= SHADOW_THINK_INTERVAL:
                    if not watcher.paused:
                        watcher.shadow_think_cycle()
                    last_shadow_think = now
            except Exception as e:
                log_warn("watcher_loop", f"Periodic loop error: {e}")
            time.sleep(5)

    periodic_thread = threading.Thread(target=periodic_loop, daemon=True)
    periodic_thread.start()

    # Main thread: read stdin commands
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            cmd = json.loads(line)
            watcher.handle_stdin_command(cmd)
        except json.JSONDecodeError:
            pass  # Ignore malformed input lines
        except Exception as e:
            log_warn("watcher_stdin", f"Command handling error: {e}")


if __name__ == "__main__":
    main()
