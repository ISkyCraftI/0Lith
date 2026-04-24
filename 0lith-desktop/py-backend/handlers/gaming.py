from olith_shared import log_warn
from olith_ollama import get_loaded_models, start_ollama, stop_ollama


def cmd_gaming_mode(backend, request: dict) -> dict:
    enabled = bool(request.get("enabled", False))
    backend.gaming_mode = enabled
    models_unloaded = 0

    if enabled:
        try:
            loaded, _ = get_loaded_models()
            models_unloaded = len(loaded)
        except Exception as e:
            log_warn("gaming", f"Failed to count loaded models: {e}")
        stop_ollama()
    else:
        backend.ollama_proc = start_ollama()

    return {"gaming_mode": enabled, "models_unloaded": models_unloaded}
