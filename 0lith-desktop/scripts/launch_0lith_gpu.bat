@echo off
TITLE 0Lith - Ollama GPU Accelerator
SETLOCAL

:: --- CONFIGURATION MATERIELLE (RTX 5070 Ti - 16 Go) ---

:: Autorise le chargement de 2 modeles simultanement (ex: Hodolith + Monolith)
set OLLAMA_MAX_LOADED_MODELS=2

:: Garde les modeles en memoire pendant 24h pour eviter le rechargement de 2 min
set OLLAMA_KEEP_ALIVE=24h

:: Force l'utilisation de Flash Attention pour booster la vitesse
set OLLAMA_FLASH_ATTENTION=1

:: --- LANCEMENT ---

echo [0Lith] Initialisation d'Ollama avec optimisation GPU...
echo [0Lith] VRAM Cible : 16 Go (RTX 5070 Ti)
echo [0Lith] Mode : Multi-agents actif (Hodolith + 1)
echo.

ollama serve
