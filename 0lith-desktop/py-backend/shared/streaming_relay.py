"""Shared LLM call utilities used by both arena (sync) and purple (async)."""

from olith_ollama import chat_with_ollama, chat_docker_pyrolith
from olith_shared import strip_think_blocks, log_warn
from config import FALLBACK_MODEL


def get_model_timeout(model: str) -> int:
    """Adaptive timeout in seconds based on model identity."""
    m = model.lower()
    if "deephat" in m:
        return 300   # DeepHat-V1-7B regularly takes 125 s+
    if "foundation-sec" in model or "fdtn-ai" in m:
        return 300   # Foundation-Sec-8B regularly takes 120-220 s
    if "qwen3:14b" in model:
        return 180
    if "qwen3" in m:
        return 120
    return 240


def sync_call_with_fallback(
    messages: list[dict],
    model: str,
    *,
    is_docker: bool = False,
    fallback_model: str = FALLBACK_MODEL,
    min_chars: int = 20,
    num_ctx: int = 2048,
) -> str:
    """Sync LLM call with adaptive timeout + short-response fallback.

    Returns raw response string (think blocks not stripped — caller decides).
    Falls back to fallback_model when the stripped text is shorter than min_chars.
    """
    timeout = get_model_timeout(model)

    def _call(m: str, docker: bool) -> str:
        if docker:
            return chat_docker_pyrolith(m, messages, timeout=timeout, num_ctx=num_ctx)
        return chat_with_ollama(m, messages, timeout=timeout, num_ctx=num_ctx)

    raw = _call(model, is_docker)
    if model != fallback_model and len(strip_think_blocks(raw).strip()) < min_chars:
        log_warn("relay", f"Short response ({len(strip_think_blocks(raw).strip())} chars) from {model}, retrying with {fallback_model}")
        raw = _call(fallback_model, False)
    return raw
