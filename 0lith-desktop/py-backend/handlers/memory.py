import copy
import threading

from olith_memory_init import AGENTS, MEM0_CONFIG
from olith_shared import log_info, log_warn, log_error, extract_memories, memory_text
from olith_agents import conversation_history


def cmd_memory_init(backend, request: dict) -> dict:
    use_graph = True
    try:
        import kuzu  # noqa: F401
    except ImportError:
        use_graph = False

    backend.memory = None
    backend._init_memory_lazy()

    if not backend.memory:
        return {"message": "Memory initialization failed", "status": "error"}

    try:
        from olith_memory_init import (
            register_agent_identities,
            register_agent_relations,
            register_sparring_protocol,
        )
        register_agent_identities(backend.memory, verbose=False)
        register_agent_relations(backend.memory, verbose=False)
        register_sparring_protocol(backend.memory, verbose=False)
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


def cmd_search(backend, request: dict) -> dict:
    query = request.get("query", "").strip()
    agent_id = request.get("agent_id", "")

    if not query:
        return {"results": [], "message": "Empty query"}
    if not agent_id or agent_id not in AGENTS:
        return {"results": [], "message": f"Invalid agent_id: {agent_id}"}
    if not backend.memory:
        return {"results": [], "message": "Memory not initialized. Run memory_init first."}

    try:
        results = backend.memory.search(query, user_id=agent_id, limit=5)
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


def cmd_feedback(backend, request: dict) -> dict:
    agent_id = request.get("agent_id", "monolith")
    rating = request.get("rating", "up")
    reason = request.get("reason", "")
    content = request.get("content", "")

    if not backend.memory:
        backend._init_memory_lazy()
    if not backend.memory:
        return {"stored": False, "message": "Memory not available"}

    if rating == "up":
        text = f"User approved this response style. Response excerpt: {content[:200]} /no_think"
    else:
        text = f"User disliked response: {reason or 'no reason given'}. Response excerpt: {content[:200]} /no_think"

    try:
        def _store():
            try:
                backend.memory.add(text, user_id=agent_id, metadata={
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


def cmd_clear_memories(backend, request: dict) -> dict:
    if not backend.memory:
        backend._init_memory_lazy()
    if not backend.memory:
        return {"cleared": False, "message": "Memory not available"}

    agent_id = request.get("agent_id")
    targets = [agent_id] if agent_id else [
        "hodolith", "monolith", "aerolith", "cryolith", "pyrolith", "shared"
    ]

    cleared = []
    for aid in targets:
        try:
            backend.memory.delete_all(user_id=aid)
            cleared.append(aid)
            log_info("memory", f"Memories cleared for {aid}")
        except Exception as e:
            log_warn("memory", f"Failed to clear memories for {aid}: {e}")

    conversation_history.clear(agent_id)
    return {"cleared": True, "agents": cleared}
