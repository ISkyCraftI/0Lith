"""
0Lith — Ollama Client
=====================
Client HTTP vers Ollama. Réutilise les patterns de olith_ollama.py :
- Session requests partagée (connection pooling)
- Retry 2x sur erreur réseau
- Strip des blocs <think>...</think> (qwen3 spécifique)
- generate() non-streaming via /api/chat
- embed() via /api/embeddings (pour la recherche sémantique)
"""

import re
import sys
import time
import json
from pathlib import Path
from typing import Optional

import requests

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import OLLAMA_URL, MODEL_NAME, OLLAMA_TIMEOUT, OLLAMA_NUM_CTX


# ── Session partagée ──────────────────────────────────────────────────────────

_session = requests.Session()
_session.headers.update({"Content-Type": "application/json"})

# Regex pour stripper les blocs de réflexion qwen3
_RE_THINK = re.compile(r"<think>.*?</think>", re.DOTALL)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _strip_think(text: str) -> str:
    """Supprime les blocs <think>...</think> émis par qwen3."""
    return _RE_THINK.sub("", text).strip()


def _retry(fn, max_retries: int = 2, base_delay: float = 1.0):
    """Exécute fn avec retry exponentiel sur RequestException."""
    last_error: Optional[Exception] = None
    for attempt in range(max_retries + 1):
        try:
            return fn()
        except requests.RequestException as e:
            last_error = e
            if attempt < max_retries:
                time.sleep(base_delay * (2 ** attempt))
    raise last_error


# ── API publique ──────────────────────────────────────────────────────────────

def generate(
    prompt: str,
    system: Optional[str] = None,
    model: str = MODEL_NAME,
    timeout: int = OLLAMA_TIMEOUT,
    num_ctx: int = OLLAMA_NUM_CTX,
) -> str:
    """
    Envoie un prompt à Ollama (non-streaming) et retourne la réponse.

    Args:
        prompt: Message utilisateur.
        system: Prompt système optionnel.
        model: Identifiant du modèle Ollama (défaut : Monolith qwen3:14b).
        timeout: Timeout HTTP en secondes.
        num_ctx: Taille de la fenêtre de contexte.

    Returns:
        Réponse textuelle du modèle, sans blocs <think>.

    Raises:
        requests.RequestException: Si Ollama est inaccessible après retries.
    """
    messages: list[dict] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    def _call() -> str:
        resp = _session.post(
            f"{OLLAMA_URL}/api/chat",
            json={
                "model": model,
                "messages": messages,
                "stream": False,
                "options": {"num_ctx": num_ctx},
            },
            timeout=timeout,
        )
        resp.raise_for_status()
        content = resp.json()["message"]["content"]
        return _strip_think(content)

    return _retry(_call)


def embed(text: str, model: str = "qwen3-embedding:0.6b") -> list[float]:
    """
    Génère un embedding via Ollama.

    Args:
        text: Texte à encoder.
        model: Modèle d'embedding (défaut : qwen3-embedding:0.6b).

    Returns:
        Vecteur d'embedding (liste de floats).

    Raises:
        requests.RequestException: Si Ollama est inaccessible.
        RuntimeError: Si le modèle d'embedding n'est pas disponible.
    """
    def _call() -> list[float]:
        resp = _session.post(
            f"{OLLAMA_URL}/api/embeddings",
            json={"model": model, "prompt": text},
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()
        if "embedding" not in data:
            raise RuntimeError(f"Ollama embedding response invalide : {data}")
        return data["embedding"]

    return _retry(_call)


def is_available() -> bool:
    """Vérifie si Ollama répond sur son API."""
    try:
        r = _session.get(f"{OLLAMA_URL}/api/tags", timeout=3)
        return r.status_code == 200
    except Exception:
        return False


def get_loaded_models() -> list[str]:
    """Retourne la liste des modèles actuellement chargés en VRAM."""
    try:
        r = _session.get(f"{OLLAMA_URL}/api/ps", timeout=5)
        r.raise_for_status()
        return [m.get("name", "") for m in r.json().get("models", [])]
    except Exception:
        return []
