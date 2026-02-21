#!/usr/bin/env python3
"""
0Lith V1 — Backend IPC Principal
=================================
Thin dispatcher: routes les commandes IPC vers les modules specialises.

Protocole IPC : JSON line-delimited
  Request:  {"id": "uuid", "command": "...", ...params}
  Response: {"id": "uuid", "status": "ok|error", ...data}

Modules:
  olith_shared.py   — Constantes, logging, Mem0 patch
  olith_ollama.py   — Ollama API wrapper, process management
  olith_tools.py    — Filesystem tools, tool-call parser
  olith_agents.py   — Agent loop, routing, XML prompts, conversation history
  olith_memory_init.py — Agent definitions, Mem0 config
"""

import sys
import io
import json
import uuid
import copy
import traceback
import threading
import subprocess
from pathlib import Path

# Force UTF-8 sur stdout/stdin (Windows utilise cp1252 par defaut)
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stdin = io.TextIOWrapper(sys.stdin.buffer, encoding='utf-8')

# Import shared (also applies Mem0 patch on import)
from olith_shared import log_warn, log_error, log_info, extract_memories, memory_text

from olith_memory_init import (
    AGENTS,
    MEM0_CONFIG,
    OLLAMA_URL,
    QDRANT_URL,
    PYROLITH_URL,
    check_service,
    check_ollama_model,
    register_agent_identities,
    register_agent_relations,
    register_sparring_protocol,
)

from olith_ollama import (
    get_session,
    is_ollama_running,
    start_ollama,
    stop_ollama,
    get_loaded_models,
)

from olith_tools import (
    tool_read_file,
    tool_list_files,
    tool_search_files,
    tool_system_info,
)

from olith_agents import (
    AGENT_COLORS, AGENT_EMOJIS,
    route_hodolith,
    run_agent_loop,
    conversation_history,
)

from olith_history import ChatHistory

import requests


# ============================================================================
# BACKEND PRINCIPAL
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

    def _track_thread(self, thread: threading.Thread):
        """Track a background thread for cleanup on shutdown."""
        with self._threads_lock:
            self._pending_threads = [t for t in self._pending_threads if t.is_alive()]
            self._pending_threads.append(thread)

    def shutdown(self):
        """Graceful shutdown: wait for pending threads, clean up Ollama process."""
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

    # ── IPC Dispatch ────────────────────────────────────────────────────

    def handle_request(self, request: dict, emit=None) -> dict:
        """Dispatche une requete IPC vers le bon handler."""
        req_id = request.get("id", str(uuid.uuid4()))
        command = request.get("command", "")

        def _emit(data: dict):
            if emit:
                emit({"id": req_id, **data})

        try:
            handler = self._get_handler(command)
            if not handler:
                return {"id": req_id, "status": "error", "message": f"Unknown command: {command}"}

            # Commands that need emit
            if command == "chat":
                data = handler(request, _emit)
            else:
                data = handler(request)

            return {"id": req_id, "status": "ok", **data}

        except requests.exceptions.ConnectionError as e:
            return {"id": req_id, "status": "error", "message": f"Service unavailable: {e}"}
        except requests.exceptions.Timeout as e:
            return {"id": req_id, "status": "error", "message": f"Timeout: {e}"}
        except Exception as e:
            log_error("ipc", f"Command '{command}' failed: {traceback.format_exc()}")
            return {"id": req_id, "status": "error", "message": str(e)}

    def _get_handler(self, command: str):
        """Retourne le handler pour une commande IPC."""
        handlers = {
            "status":           self.cmd_status,
            "agents_list":      self.cmd_agents_list,
            "chat":             self.cmd_chat,
            "search":           self.cmd_search,
            "memory_init":      self.cmd_memory_init,
            "gaming_mode":      self.cmd_gaming_mode,
            "set_project_root": self.cmd_set_project_root,
            "read_file":        self.cmd_read_file,
            "list_files":       self.cmd_list_files,
            "search_files":     self.cmd_search_files,
            "clear_history":    self.cmd_clear_history,
            "feedback":         self.cmd_feedback,
            "system_info":      self.cmd_system_info,
            "clear_memories":   self.cmd_clear_memories,
            "cancel":           self.cmd_cancel,
            "list_sessions":    self.cmd_list_sessions,
            "load_session":     self.cmd_load_session,
            "new_session":      self.cmd_new_session,
        }
        return handlers.get(command)

    # ── status ──────────────────────────────────────────────────────────

    def cmd_status(self, request: dict) -> dict:
        """Retourne l'etat de tous les services et modeles."""
        if self.gaming_mode:
            qdrant_ok = check_service("Qdrant", f"{QDRANT_URL}/collections")
            return {
                "ollama": False,
                "qdrant": qdrant_ok,
                "pyrolith_docker": False,
                "memory_initialized": self.memory is not None,
                "models": {},
                "loaded_models": [],
                "vram_used_gb": 0,
                "gaming_mode": True,
            }

        ollama_ok = check_service("Ollama", OLLAMA_URL)
        qdrant_ok = check_service("Qdrant", f"{QDRANT_URL}/collections")
        pyrolith_ok = check_service("Pyrolith", f"{PYROLITH_URL}/api/tags")

        models = {}
        if ollama_ok:
            for agent_id, info in AGENTS.items():
                if info.get("location") == "docker":
                    models[agent_id] = pyrolith_ok
                else:
                    models[agent_id] = check_ollama_model(info["model"])

        loaded_models, vram_used_gb = get_loaded_models()

        return {
            "ollama": ollama_ok,
            "qdrant": qdrant_ok,
            "pyrolith_docker": pyrolith_ok,
            "memory_initialized": self.memory is not None,
            "models": models,
            "loaded_models": loaded_models,
            "vram_used_gb": vram_used_gb,
        }

    # ── agents_list ─────────────────────────────────────────────────────

    def cmd_agents_list(self, request: dict) -> dict:
        """Retourne la liste des 5 agents avec metadata."""
        agents = []
        for agent_id, info in AGENTS.items():
            agents.append({
                "id": agent_id,
                "name": agent_id.capitalize(),
                "role": info["role"],
                "model": info["model"],
                "color": AGENT_COLORS.get(agent_id, "#FFFFFF"),
                "emoji": AGENT_EMOJIS.get(agent_id, "⬜"),
                "description": info["description"],
                "capabilities": info["capabilities"],
                "location": info.get("location", "local"),
            })
        return {"agents": agents}

    # ── chat ────────────────────────────────────────────────────────────

    def cmd_chat(self, request: dict, emit=None) -> dict:
        """Chat avec routage + memoire + streaming + boucle agent.
        Sérialisé via _chat_lock pour éviter les conflits de conversation_history et VRAM."""
        if not self._chat_lock.acquire(blocking=False):
            log_info("chat", "Waiting for previous chat to finish...")
            self._chat_lock.acquire()

        self._cancel_event.clear()

        try:
            return self._cmd_chat_inner(request, emit)
        finally:
            self._chat_lock.release()

    def _cmd_chat_inner(self, request: dict, emit=None) -> dict:
        """Logique interne de cmd_chat (appelée sous _chat_lock)."""
        message = request.get("message", "").strip()
        if not message:
            return {"message": "Empty message", "status": "error"}

        agent_id = request.get("agent_id")
        route_reason = None

        # Auto-init memory
        if not self.memory:
            self._init_memory_lazy()

        # Routage via Hodolith si pas d'agent_id explicite
        if not agent_id:
            route = route_hodolith(message)
            agent_id = route["route"]
            route_reason = route.get("reason", "")

        if agent_id not in AGENTS:
            return {"message": f"Unknown agent: {agent_id}", "status": "error"}

        # Deleguer a la boucle agent
        result = run_agent_loop(
            agent_id=agent_id,
            message=message,
            memory=self.memory,
            project_root=self.project_root,
            emit=emit,
            route_reason=route_reason,
            cancel_event=self._cancel_event,
        )

        # Track the memory storage thread
        bg_thread = result.pop("_thread", None)
        if bg_thread:
            self._track_thread(bg_thread)

        # Persist user message + agent response
        if not result.get("cancelled"):
            sid = self.history.current_session or self.history.new_session()
            self.history.save_message(sid, {"type": "user", "content": message})
            self.history.save_message(sid, {
                "type": "agent",
                "content": result.get("response", ""),
                "agent_id": result.get("agent_id"),
                "agent_name": result.get("agent_name"),
            })
            result["session_id"] = sid

        return result

    def cmd_cancel(self, request: dict) -> dict:
        """Signale l'annulation du chat en cours via _cancel_event."""
        self._cancel_event.set()
        log_info("chat", "Cancel requested")
        return {"message": "Cancelled"}

    # ── chat history ─────────────────────────────────────────────────────
    # TODO frontend: connecter list_sessions, load_session, new_session aux composants Svelte

    def cmd_list_sessions(self, request: dict) -> dict:
        """Retourne la liste des sessions de chat persistées."""
        return {"sessions": self.history.list_sessions()}

    def cmd_load_session(self, request: dict) -> dict:
        """Charge les messages d'une session."""
        session_id = request.get("session_id", "")
        if not session_id:
            return {"message": "Missing session_id", "status": "error"}
        messages = self.history.load_session(session_id)
        if not messages:
            return {"messages": [], "message": f"Session '{session_id}' not found or empty"}
        self.history._current_session = session_id
        return {"session_id": session_id, "messages": messages}

    def cmd_new_session(self, request: dict) -> dict:
        """Force la création d'une nouvelle session de chat."""
        sid = self.history.new_session()
        conversation_history.clear()
        return {"session_id": sid, "message": "New session started"}

    # ── gaming_mode ──────────────────────────────────────────────────────

    def cmd_gaming_mode(self, request: dict) -> dict:
        """Active/desactive le gaming mode."""
        enabled = bool(request.get("enabled", False))
        self.gaming_mode = enabled
        models_unloaded = 0

        if enabled:
            try:
                loaded, _ = get_loaded_models()
                models_unloaded = len(loaded)
            except Exception as e:
                log_warn("gaming", f"Failed to count loaded models: {e}")
            stop_ollama()
        else:
            self.ollama_proc = start_ollama()

        return {"gaming_mode": enabled, "models_unloaded": models_unloaded}

    # ── search (Mem0) ───────────────────────────────────────────────────

    def cmd_search(self, request: dict) -> dict:
        """Recherche dans la memoire Mem0."""
        query = request.get("query", "").strip()
        agent_id = request.get("agent_id", "")

        if not query:
            return {"results": [], "message": "Empty query"}
        if not agent_id or agent_id not in AGENTS:
            return {"results": [], "message": f"Invalid agent_id: {agent_id}"}
        if not self.memory:
            return {"results": [], "message": "Memory not initialized. Run memory_init first."}

        try:
            results = self.memory.search(query, user_id=agent_id, limit=5)
        except Exception as e:
            log_warn("search", f"Mem0 search failed: {e}")
            return {"results": [], "message": f"Search failed: {e}"}

        memories_list = extract_memories(results)

        formatted = []
        for mem in memories_list:
            entry = {"text": memory_text(mem) or str(mem)}
            if isinstance(mem, dict):
                entry["score"] = mem.get("score")
                entry["metadata"] = mem.get("metadata")
            formatted.append(entry)

        return {"results": formatted, "agent_id": agent_id, "query": query}

    # ── filesystem (IPC direct) ─────────────────────────────────────────

    def cmd_set_project_root(self, request: dict) -> dict:
        """Definit le project_root pour le sandbox filesystem."""
        path = request.get("path", "").strip()
        if not path:
            return {"message": "Path vide", "status": "error"}
        p = Path(path).resolve()
        if not p.is_dir():
            return {"message": f"Répertoire introuvable: {path}", "status": "error"}
        self.project_root = str(p)
        log_info("project", f"Project root set: {self.project_root}")
        return {"project_root": self.project_root, "message": f"Projet ouvert: {self.project_root}"}

    def cmd_read_file(self, request: dict) -> dict:
        """IPC: lecture directe d'un fichier."""
        return tool_read_file(
            request.get("path", ""),
            self.project_root,
            request.get("offset", 1),
            request.get("limit", 500),
        )

    def cmd_list_files(self, request: dict) -> dict:
        """IPC: listing direct d'un repertoire."""
        return tool_list_files(
            request.get("path", "."),
            self.project_root,
            request.get("max_depth", 3),
        )

    def cmd_search_files(self, request: dict) -> dict:
        """IPC: recherche directe dans les fichiers."""
        return tool_search_files(
            request.get("pattern", ""),
            self.project_root,
            request.get("path", "."),
            request.get("glob", ""),
        )

    # ── conversation history ────────────────────────────────────────────

    def cmd_clear_history(self, request: dict) -> dict:
        """Vide l'historique de conversation."""
        agent_id = request.get("agent_id")
        conversation_history.clear(agent_id)
        return {"message": f"History cleared for {'all agents' if not agent_id else agent_id}"}

    # ── feedback ────────────────────────────────────────────────────────

    def cmd_feedback(self, request: dict) -> dict:
        """Stocke le feedback utilisateur sur une reponse agent dans Mem0."""
        agent_id = request.get("agent_id", "monolith")
        rating = request.get("rating", "up")
        reason = request.get("reason", "")
        content = request.get("content", "")

        if not self.memory:
            self._init_memory_lazy()
        if not self.memory:
            return {"stored": False, "message": "Memory not available"}

        if rating == "up":
            text = f"User approved this response style. Response excerpt: {content[:200]} /no_think"
        else:
            text = f"User disliked response: {reason or 'no reason given'}. Response excerpt: {content[:200]} /no_think"

        try:
            import threading
            def _store():
                try:
                    self.memory.add(text, user_id=agent_id, metadata={
                        "type": "chat_feedback",
                        "rating": rating,
                        "reason": reason,
                    })
                    log_info("feedback", f"{rating} for {agent_id}" + (f": {reason}" if reason else ""))
                except Exception as e:
                    log_error("feedback", f"Failed to store: {e}")
            threading.Thread(target=_store, daemon=True).start()
        except Exception as e:
            log_error("feedback", f"Failed: {e}")
            return {"stored": False, "message": str(e)}

        return {"stored": True}

    # ── system_info ─────────────────────────────────────────────────────

    def cmd_system_info(self, request: dict) -> dict:
        """Retourne les infos systeme (OS, processus, RAM, GPU)."""
        return tool_system_info()

    # ── clear_memories ──────────────────────────────────────────────────

    def cmd_clear_memories(self, request: dict) -> dict:
        """Purge les memoires Mem0 pour un agent ou tous les agents."""
        if not self.memory:
            self._init_memory_lazy()
        if not self.memory:
            return {"cleared": False, "message": "Memory not available"}

        agent_id = request.get("agent_id")
        targets = [agent_id] if agent_id else [
            "hodolith", "monolith", "aerolith", "cryolith", "pyrolith", "shared"
        ]

        cleared = []
        for aid in targets:
            try:
                self.memory.delete_all(user_id=aid)
                cleared.append(aid)
                log_info("memory", f"Memories cleared for {aid}")
            except Exception as e:
                log_warn("memory", f"Failed to clear memories for {aid}: {e}")

        # Also clear conversation history
        conversation_history.clear(agent_id)

        return {"cleared": True, "agents": cleared}

    # ── memory_init ─────────────────────────────────────────────────────

    def _init_memory_lazy(self):
        """Initialise Mem0 si pas deja fait."""
        if self.memory:
            return
        try:
            if not check_service("Qdrant", f"{QDRANT_URL}/collections"):
                return
        except Exception:
            return

        use_graph = True
        try:
            import kuzu  # noqa: F401
        except ImportError:
            use_graph = False

        config = copy.deepcopy(MEM0_CONFIG)

        from olith_shared import retry_on_failure
        try:
            from mem0 import Memory
            if not use_graph:
                config.pop("graph_store", None)

            def _init():
                return Memory.from_config(config_dict=config)

            self.memory = retry_on_failure(_init, max_retries=2, base_delay=2.0, exceptions=(Exception,))
            log_info("memory", "Mem0 initialized successfully")
        except Exception as e:
            log_error("memory", f"Mem0 init failed: {e}")

    def cmd_memory_init(self, request: dict) -> dict:
        """Initialise Mem0 et enregistre les identites des agents."""
        use_graph = True
        try:
            import kuzu  # noqa: F401
        except ImportError:
            use_graph = False

        self.memory = None
        self._init_memory_lazy()

        if not self.memory:
            return {"message": "Memory initialization failed", "status": "error"}

        try:
            register_agent_identities(self.memory, verbose=False)
            register_agent_relations(self.memory, verbose=False)
            register_sparring_protocol(self.memory, verbose=False)
        except Exception as e:
            log_error("memory_init", f"Registration failed: {e}")
            return {"message": f"Registration failed: {e}", "status": "error"}

        return {
            "message": "Memory initialized successfully",
            "agents_registered": len(AGENTS),
            "relations_registered": True,
            "sparring_protocol": True,
            "graph_enabled": use_graph,
        }


# ============================================================================
# MAIN — Boucle IPC stdin/stdout
# ============================================================================

def main():
    backend = OlithBackend()

    if not is_ollama_running():
        backend.ollama_proc = start_ollama()

    def emit(data: dict):
        """Envoie un message intermediaire sur stdout (pour streaming)."""
        print(json.dumps(data, ensure_ascii=False), flush=True)

    try:
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue

            try:
                request = json.loads(line)
            except json.JSONDecodeError as e:
                response = {"status": "error", "message": f"Invalid JSON: {e}"}
                print(json.dumps(response), flush=True)
                continue

            response = backend.handle_request(request, emit=emit)
            print(json.dumps(response, ensure_ascii=False), flush=True)
    finally:
        backend.shutdown()


if __name__ == "__main__":
    main()
