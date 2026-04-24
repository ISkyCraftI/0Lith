"""
0Lith — Central configuration.

All model names, service URLs, and runtime paths are defined here.
Override any value via environment variable before launching the backend.
"""

import os

OLLAMA_URL     = os.getenv("OLLAMA_URL",     "http://localhost:11434")
PYROLITH_URL   = os.getenv("PYROLITH_URL",   "http://localhost:11435")

HODOLITH_MODEL = os.getenv("HODOLITH_MODEL", "qwen3:1.7b")
MONOLITH_MODEL = os.getenv("MONOLITH_MODEL", "qwen3:14b")
AEROLITH_MODEL = os.getenv("AEROLITH_MODEL", "qwen3-coder:30b")
CRYOLITH_MODEL = os.getenv("CRYOLITH_MODEL", "hf.co/fdtn-ai/Foundation-Sec-8B-Q4_K_M-GGUF:latest")
PYROLITH_MODEL = os.getenv("PYROLITH_MODEL", "deephat/DeepHat-V1-7B:latest")
FALLBACK_MODEL = os.getenv("FALLBACK_MODEL", "qwen3:14b")
EMBED_MODEL    = os.getenv("EMBED_MODEL",    "qwen3-embedding:0.6b")

DATA_DIR       = os.getenv("OLITH_DATA_DIR", os.path.expanduser("~/.0lith"))
