"""
0Lith — Obsidian Bridge
=======================
Configuration centrale. Surcharger via variables d'environnement.
"""

import os
from pathlib import Path

try:
    from dotenv import load_dotenv
    # Bridge .env first, then fallback to workspace root .env
    _here = Path(__file__).parent
    load_dotenv(_here / ".env", override=False)
    load_dotenv(_here.parent.parent / ".env", override=False)
except ImportError:
    pass  # python-dotenv not installed — use os env vars directly

# ── Vault ───────────────────────────────────────────────────────────────────
VAULT_PATH: Path = Path(
    os.getenv("VAULT_PATH", r"C:\Users\skycr\Perso\Arkhe")
)

# Dossiers du vault où écrire les plans journaliers
DAILY_PLANS_FOLDER: Path = Path(
    os.getenv("DAILY_PLANS_FOLDER", r"C:\Users\skycr\Perso\Arkhe\Daily Plans")
)

# Extensions à scanner
VAULT_EXTENSIONS: tuple[str, ...] = (".md",)

# Dossiers à ignorer lors du scan
_default_ignore = ".obsidian,.trash,.git,__pycache__"
VAULT_IGNORE_DIRS: set[str] = set(
    os.getenv("VAULT_IGNORE_DIRS", _default_ignore).split(",")
)

# ── Ollama ───────────────────────────────────────────────────────────────────
OLLAMA_URL: str = os.getenv("OLLAMA_URL", "http://localhost:11434")

# Modèle Monolith — orchestrateur 0Lith (qwen3:14b)
MODEL_NAME: str = os.getenv("MODEL_NAME", "qwen3:14b")

# Modèles requis pour le health check
REQUIRED_MODELS: list[str] = os.getenv(
    "REQUIRED_MODELS", "qwen3:14b"
).split(",")

# Timeout en secondes pour les appels LLM
OLLAMA_TIMEOUT: int = int(os.getenv("OLLAMA_TIMEOUT", "120"))

# Taille de la fenêtre de contexte
OLLAMA_NUM_CTX: int = int(os.getenv("OLLAMA_NUM_CTX", "8192"))

# ── Qdrant (recherche sémantique — bonus) ────────────────────────────────────
QDRANT_URL: str = os.getenv("QDRANT_URL", "http://localhost:6333")
QDRANT_COLLECTION: str = "arkhe_notes"
EMBEDDING_MODEL: str = "qwen3-embedding:0.6b"
EMBEDDING_DIMS: int = 1024

# ── Watcher ──────────────────────────────────────────────────────────────────
# Délai d'inactivité avant déclenchement de l'action IA (en secondes)
WATCHER_INACTIVITY_SECONDS: int = int(os.getenv("WATCHER_INACTIVITY_SECONDS", "60"))

# Cooldown par fichier pour éviter les boucles infinies après écriture
WATCHER_COOLDOWN_SECONDS: int = int(os.getenv("WATCHER_COOLDOWN_SECONDS", "30"))

# Dossier interne 0Lith dans le vault (ignoré par le watcher)
OLITH_DIR: Path = VAULT_PATH / ".olith"

# Fichier de configuration des tags personnalisés (éditable dans Obsidian)
ACTIONS_CONFIG_FILE: Path = OLITH_DIR / "tags.md"

# Obsidian Local REST API (community plugin — optionnel)
# Plugin: https://github.com/coddingtonbear/obsidian-local-rest-api
# API key : Obsidian → Settings → Local REST API
OBSIDIAN_API_URL: str = os.getenv("OBSIDIAN_API_URL", "http://localhost:27123")
OBSIDIAN_API_KEY: str = os.getenv("OBSIDIAN_API_KEY", "")

# Intervalle entre les scans périodiques de tags (secondes). 0 = désactivé.
WATCHER_SCAN_INTERVAL_SECONDS: int = int(os.getenv("WATCHER_SCAN_INTERVAL_SECONDS", "60"))

# ── API ──────────────────────────────────────────────────────────────────────
API_HOST: str = os.getenv("API_HOST", "127.0.0.1")
API_PORT: int = int(os.getenv("API_PORT", "8765"))
