"""
0Lith — Obsidian Bridge
=======================
Configuration centrale. Surcharger via variables d'environnement.
"""

import os
from pathlib import Path

# ── Vault ───────────────────────────────────────────────────────────────────
VAULT_PATH: Path = Path(
    os.getenv("VAULT_PATH", r"C:\Users\skycr\Perso\Arkhe")
)

# Dossiers du vault où écrire les plans journaliers
DAILY_PLANS_FOLDER: Path = VAULT_PATH / "Daily Plans"

# Extensions à scanner
VAULT_EXTENSIONS: tuple[str, ...] = (".md",)

# Dossiers à ignorer lors du scan
VAULT_IGNORE_DIRS: set[str] = {".obsidian", ".trash", ".git", "__pycache__"}

# ── Ollama ───────────────────────────────────────────────────────────────────
OLLAMA_URL: str = os.getenv("OLLAMA_URL", "http://localhost:11434")

# Modèle Monolith — orchestrateur 0Lith (qwen3:14b)
MODEL_NAME: str = os.getenv("MODEL_NAME", "qwen3:14b")

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
WATCHER_INACTIVITY_SECONDS: int = int(os.getenv("WATCHER_INACTIVITY_SECONDS", "120"))

# Cooldown par fichier pour éviter les boucles infinies après écriture
WATCHER_COOLDOWN_SECONDS: int = int(os.getenv("WATCHER_COOLDOWN_SECONDS", "30"))

# Dossier interne 0Lith dans le vault (ignoré par le watcher)
OLITH_DIR: Path = VAULT_PATH / ".olith"

# Fichier de configuration des tags personnalisés (éditable dans Obsidian)
ACTIONS_CONFIG_FILE: Path = OLITH_DIR / "tags.md"

# ── API ──────────────────────────────────────────────────────────────────────
API_HOST: str = os.getenv("API_HOST", "127.0.0.1")
API_PORT: int = int(os.getenv("API_PORT", "8765"))
