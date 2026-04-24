from olith_memory_init import AGENTS, OLLAMA_URL, PYROLITH_URL, check_service, check_qdrant_embedded, check_ollama_model
from olith_ollama import get_loaded_models
from olith_tools import tool_system_info
from olith_agents import AGENT_COLORS, AGENT_EMOJIS


def cmd_status(backend, request: dict) -> dict:
    if backend.gaming_mode:
        qdrant_ok = check_qdrant_embedded()
        return {
            "ollama": False,
            "qdrant": qdrant_ok,
            "pyrolith_docker": False,
            "memory_initialized": backend.memory is not None,
            "models": {},
            "loaded_models": [],
            "vram_used_gb": 0,
            "gaming_mode": True,
        }

    ollama_ok = check_service("Ollama", OLLAMA_URL)
    qdrant_ok = check_qdrant_embedded()
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
        "memory_initialized": backend.memory is not None,
        "models": models,
        "loaded_models": loaded_models,
        "vram_used_gb": vram_used_gb,
    }


def cmd_agents_list(backend, request: dict) -> dict:
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


def cmd_system_info(backend, request: dict) -> dict:
    return tool_system_info()
