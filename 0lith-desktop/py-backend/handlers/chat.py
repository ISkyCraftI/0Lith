from olith_memory_init import AGENTS
from olith_shared import log_info, log_warn
from olith_agents import route_hodolith, run_agent_loop, conversation_history


def cmd_chat(backend, request: dict, emit) -> dict:
    """Serialized via _chat_lock to avoid conversation_history and VRAM conflicts."""
    if not backend._chat_lock.acquire(blocking=False):
        log_info("chat", "Waiting for previous chat to finish...")
        backend._chat_lock.acquire()

    backend._cancel_event.clear()

    try:
        return _cmd_chat_inner(backend, request, emit)
    finally:
        backend._chat_lock.release()


def _cmd_chat_inner(backend, request: dict, emit) -> dict:
    message = request.get("message", "").strip()
    if not message:
        return {"message": "Empty message", "status": "error"}

    agent_id = request.get("agent_id")
    route_reason = None

    if not backend.memory:
        backend._init_memory_lazy()

    if not agent_id:
        route = route_hodolith(message)
        agent_id = route["route"]
        route_reason = route.get("reason", "")

    if agent_id not in AGENTS:
        return {"message": f"Unknown agent: {agent_id}", "status": "error"}

    result = run_agent_loop(
        agent_id=agent_id,
        message=message,
        memory=backend.memory,
        project_root=backend.project_root,
        emit=emit,
        route_reason=route_reason,
        cancel_event=backend._cancel_event,
    )

    bg_thread = result.pop("_thread", None)
    if bg_thread:
        backend._track_thread(bg_thread)

    try:
        from olith_tasks import resolve_completed
        resolve_completed()
    except Exception as e:
        log_warn("tasks", f"resolve_completed failed: {e}")

    if not result.get("cancelled"):
        sid = backend.history.current_session or backend.history.new_session()
        backend.history.save_message(sid, {"type": "user", "content": message})
        backend.history.save_message(sid, {
            "type": "agent",
            "content": result.get("response", ""),
            "agent_id": result.get("agent_id"),
            "agent_name": result.get("agent_name"),
        })
        result["session_id"] = sid

    return result


def cmd_cancel(backend, request: dict) -> dict:
    backend._cancel_event.set()
    log_info("chat", "Cancel requested")
    return {"message": "Cancelled"}


def cmd_arena(backend, request: dict, emit) -> dict:
    """Serialized via _chat_lock (exclusive with cmd_chat)."""
    if not backend._chat_lock.acquire(blocking=False):
        log_info("arena", "Waiting for previous session to finish...")
        backend._chat_lock.acquire()

    backend._cancel_event.clear()

    try:
        from olith_arena import run_arena_sql_injection
        return run_arena_sql_injection(emit, backend._cancel_event)
    finally:
        backend._chat_lock.release()


def cmd_clear_history(backend, request: dict) -> dict:
    agent_id = request.get("agent_id")
    conversation_history.clear(agent_id)
    return {"message": f"History cleared for {'all agents' if not agent_id else agent_id}"}


def cmd_list_sessions(backend, request: dict) -> dict:
    return {"sessions": backend.history.list_sessions()}


def cmd_load_session(backend, request: dict) -> dict:
    session_id = request.get("session_id", "")
    if not session_id:
        return {"message": "Missing session_id", "status": "error"}
    messages = backend.history.load_session(session_id)
    if not messages:
        return {"messages": [], "message": f"Session '{session_id}' not found or empty"}
    backend.history._current_session = session_id
    return {"session_id": session_id, "messages": messages}


def cmd_new_session(backend, request: dict) -> dict:
    sid = backend.history.new_session()
    conversation_history.clear()
    return {"session_id": sid, "message": "New session started"}
