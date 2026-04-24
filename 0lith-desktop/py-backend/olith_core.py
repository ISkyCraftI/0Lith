#!/usr/bin/env python3
"""
0Lith V1 — Backend IPC Principal
=================================
Thin init: creates OlithBackend, registers all command handlers, starts the IPC loop.

Protocol: JSON line-delimited stdin/stdout
  Request:  {"id": "uuid", "command": "...", ...params}
  Response: {"id": "uuid", "status": "ok|error", ...data}
"""

import io
import subprocess
import sys
import threading

# Force UTF-8 on stdout/stdin (Windows defaults to cp1252)
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.stdin = io.TextIOWrapper(sys.stdin.buffer, encoding="utf-8")

# olith_shared applies Mem0 monkey-patch on import
from olith_shared import log_info  # noqa: F401 (side-effect import)
from olith_ollama import is_ollama_running, start_ollama
from olith_history import ChatHistory
from olith_memory_init import MEM0_CONFIG, check_qdrant_embedded

from ipc.dispatcher import Dispatcher
from ipc.protocol import run

import handlers.status as h_status
import handlers.chat as h_chat
import handlers.memory as h_memory
import handlers.gaming as h_gaming
import handlers.filesystem as h_fs
import handlers.tasks as h_tasks


# ============================================================================
# BACKEND STATE
# ============================================================================

class OlithBackend:
    def __init__(self):
        self.memory = None
        self.gaming_mode = False
        self.ollama_proc: subprocess.Popen | None = None
        self.project_root: str | None = None
        self._pending_threads: list[threading.Thread] = []
        self._threads_lock = threading.Lock()
        self._chat_lock = threading.Lock()
        self._cancel_event = threading.Event()
        self.history = ChatHistory()

    def _track_thread(self, thread: threading.Thread) -> None:
        with self._threads_lock:
            self._pending_threads = [t for t in self._pending_threads if t.is_alive()]
            self._pending_threads.append(thread)

    def _init_memory_lazy(self) -> None:
        if self.memory:
            return
        if not check_qdrant_embedded():
            return

        import copy
        use_graph = True
        try:
            import kuzu  # noqa: F401
        except ImportError:
            use_graph = False

        config = copy.deepcopy(MEM0_CONFIG)

        from olith_shared import retry_on_failure, log_error
        try:
            from mem0 import Memory
            if not use_graph:
                config.pop("graph_store", None)
            self.memory = retry_on_failure(
                lambda: Memory.from_config(config_dict=config),
                max_retries=2, base_delay=2.0, exceptions=(Exception,),
            )
            log_info("memory", "Mem0 initialized successfully")
        except Exception as e:
            log_error("memory", f"Mem0 init failed: {e}")

    def shutdown(self) -> None:
        with self._threads_lock:
            threads = list(self._pending_threads)
            self._pending_threads.clear()
        for t in threads:
            t.join(timeout=5)
        if self.ollama_proc and self.ollama_proc.poll() is None:
            self.ollama_proc.terminate()
            try:
                self.ollama_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.ollama_proc.kill()


# ============================================================================
# MAIN
# ============================================================================

def main() -> None:
    backend = OlithBackend()

    if not is_ollama_running():
        backend.ollama_proc = start_ollama()

    d = Dispatcher(backend)

    # Status & info
    d.register("status",           h_status.cmd_status)
    d.register("agents_list",      h_status.cmd_agents_list)
    d.register("system_info",      h_status.cmd_system_info)

    # Chat, cancel, arena, history
    d.register("chat",             h_chat.cmd_chat,          needs_emit=True)
    d.register("cancel",           h_chat.cmd_cancel)
    d.register("arena",            h_chat.cmd_arena,         needs_emit=True)
    d.register("clear_history",    h_chat.cmd_clear_history)
    d.register("list_sessions",    h_chat.cmd_list_sessions)
    d.register("load_session",     h_chat.cmd_load_session)
    d.register("new_session",      h_chat.cmd_new_session)

    # Memory
    d.register("memory_init",      h_memory.cmd_memory_init)
    d.register("search",           h_memory.cmd_search)
    d.register("feedback",         h_memory.cmd_feedback)
    d.register("clear_memories",   h_memory.cmd_clear_memories)

    # Gaming mode
    d.register("gaming_mode",      h_gaming.cmd_gaming_mode)

    # Filesystem
    d.register("set_project_root", h_fs.cmd_set_project_root)
    d.register("read_file",        h_fs.cmd_read_file)
    d.register("list_files",       h_fs.cmd_list_files)
    d.register("search_files",     h_fs.cmd_search_files)

    # Tasks (#User)
    d.register("list_tasks",       h_tasks.cmd_list_tasks)
    d.register("resolve_tasks",    h_tasks.cmd_resolve_tasks)

    try:
        run(d)
    finally:
        backend.shutdown()


if __name__ == "__main__":
    main()
