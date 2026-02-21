#!/usr/bin/env python3
"""
0Lith V1 — Ollama API Wrapper + Process Management
====================================================
Gere les appels a l'API Ollama (streaming et non-streaming)
et le cycle de vie du processus Ollama (start/stop/gaming mode).
"""

import os
import sys
import json
import time
import subprocess
import requests

from olith_shared import log_warn, log_error, log_info, retry_on_failure
from olith_memory_init import OLLAMA_URL, PYROLITH_URL

# ============================================================================
# CONNECTION POOLING — Reutilise les connexions TCP
# ============================================================================

# Session partagee pour tous les appels HTTP (connection pooling)
_session = requests.Session()
_session.headers.update({"Content-Type": "application/json"})


def get_session() -> requests.Session:
    """Retourne la session HTTP partagee."""
    return _session


# ============================================================================
# OLLAMA API
# ============================================================================

def chat_with_ollama(
    model: str,
    messages: list[dict],
    timeout: int = 120,
    num_ctx: int = 4096,
) -> str:
    """Appel direct a l'API Ollama (non-streaming). Retourne le contenu de la reponse."""
    def _call():
        response = _session.post(
            f"{OLLAMA_URL}/api/chat",
            json={
                "model": model,
                "messages": messages,
                "stream": False,
                "keep_alive": "5m",
                "options": {"num_ctx": num_ctx},
            },
            timeout=timeout,
        )
        response.raise_for_status()
        return response.json()["message"]["content"]

    return retry_on_failure(_call, max_retries=2, base_delay=1.0)


def chat_with_ollama_stream(
    model: str,
    messages: list[dict],
    timeout: int = 120,
    num_ctx: int = 4096,
):
    """Appel streaming a l'API Ollama. Yield chaque token au fur et a mesure."""
    def _connect():
        resp = _session.post(
            f"{OLLAMA_URL}/api/chat",
            json={
                "model": model,
                "messages": messages,
                "stream": True,
                "keep_alive": "5m",
                "options": {"num_ctx": num_ctx},
            },
            timeout=timeout,
            stream=True,
        )
        resp.raise_for_status()
        return resp

    response = retry_on_failure(_connect, max_retries=2, base_delay=1.0)
    for line in response.iter_lines():
        if line:
            data = json.loads(line)
            content = data.get("message", {}).get("content", "")
            if content:
                yield content
            if data.get("done", False):
                return


def chat_docker_pyrolith(
    model: str,
    messages: list[dict],
    timeout: int = 300,
    num_ctx: int = 8192,
) -> str:
    """Appel a Pyrolith via Docker Ollama (port 11435)."""
    response = _session.post(
        f"{PYROLITH_URL}/api/chat",
        json={
            "model": model,
            "messages": messages,
            "stream": False,
            "options": {"num_ctx": num_ctx},
        },
        timeout=timeout,
    )
    response.raise_for_status()
    return response.json()["message"]["content"]


def chat_docker_pyrolith_stream(
    model: str,
    messages: list[dict],
    timeout: int = 300,
    emit=None,
    num_ctx: int = 8192,
) -> str:
    """Appel streaming a Pyrolith via Docker Ollama (port 11435)."""
    response = _session.post(
        f"{PYROLITH_URL}/api/chat",
        json={
            "model": model,
            "messages": messages,
            "stream": True,
            "options": {"num_ctx": num_ctx},
        },
        timeout=timeout,
        stream=True,
    )
    response.raise_for_status()
    full_response = []
    for line in response.iter_lines():
        if line:
            data = json.loads(line)
            content = data.get("message", {}).get("content", "")
            if content:
                full_response.append(content)
                if emit:
                    emit({"status": "streaming", "chunk": content})
            if data.get("done", False):
                break
    return "".join(full_response)


# ============================================================================
# OLLAMA PROCESS MANAGEMENT
# ============================================================================

OLLAMA_GPU_ENV = {
    **os.environ,
    "OLLAMA_MAX_LOADED_MODELS": "2",
    "OLLAMA_KEEP_ALIVE": "24h",
    "OLLAMA_FLASH_ATTENTION": "1",
}


def is_ollama_running() -> bool:
    """Check if Ollama is responding on its API."""
    try:
        r = _session.get(f"{OLLAMA_URL}/api/tags", timeout=3)
        return r.status_code == 200
    except Exception:
        return False


def start_ollama() -> subprocess.Popen | None:
    """Start Ollama serve with GPU-optimized env vars. Returns the process."""
    if is_ollama_running():
        return None
    try:
        proc = subprocess.Popen(
            ["ollama", "serve"],
            env=OLLAMA_GPU_ENV,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        for _ in range(30):
            time.sleep(0.5)
            if is_ollama_running():
                log_info("ollama", "Ollama started successfully")
                return proc
        log_warn("ollama", "Ollama started but not responding after 15s")
        return proc
    except FileNotFoundError:
        log_error("ollama", "Ollama binary not found")
        return None


def stop_ollama():
    """Stop all Ollama processes. Graceful shutdown first, then force kill."""
    try:
        _session.delete(f"{OLLAMA_URL}/api/shutdown", timeout=3)
        for _ in range(10):
            time.sleep(0.5)
            if not is_ollama_running():
                return
    except Exception:
        pass

    try:
        if sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/F", "/IM", "ollama.exe", "/T"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            subprocess.run(
                ["taskkill", "/F", "/IM", "ollama_llama_server.exe", "/T"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        else:
            subprocess.run(
                ["pkill", "-f", "ollama serve"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
    except Exception as e:
        log_warn("ollama", f"Force kill failed: {e}")


def get_loaded_models() -> tuple[list[dict], float]:
    """Get currently loaded models and total VRAM usage.
    Returns (loaded_models_list, vram_used_gb)."""
    loaded_models = []
    vram_used = 0

    for url, prefix in [(OLLAMA_URL, ""), (PYROLITH_URL, "[Docker] ")]:
        try:
            r = _session.get(f"{url}/api/ps", timeout=5)
            if r.status_code == 200:
                for m in r.json().get("models", []):
                    size_vram = m.get("size_vram", 0)
                    size = m.get("size", 0)
                    loaded_models.append({
                        "name": f"{prefix}{m.get('name', '')}",
                        "size_gb": round(size / 1e9, 1),
                        "vram_gb": round(size_vram / 1e9, 1),
                    })
                    vram_used += size_vram
        except Exception:
            pass

    return loaded_models, round(vram_used / 1e9, 1)
