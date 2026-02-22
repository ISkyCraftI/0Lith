<p align="center">
  <img src="Logo_texture.svg" alt="0Lith" width="80" />
</p>

<h1 align="center">0Lith</h1>

<p align="center">
  Système multi-agents IA souverain, local, et personnel.<br/>
  Cybersécurité · Développement · Anticipation.
</p>

<p align="center">
  <img src="https://img.shields.io/badge/status-alpha%20v0.1-orange" />
  <img src="https://img.shields.io/badge/license-MIT-blue" />
  <img src="https://img.shields.io/badge/platform-Windows%20%7C%20Linux-lightgrey" />
  <img src="https://img.shields.io/badge/GPU-RTX%205070%20Ti%2016%20Go-green" />
</p>

---

## Qu'est-ce que 0Lith ?

0Lith (prononcé "zérolith") est un cockpit multi-agents qui tourne **entièrement en local** — aucun cloud, aucune API payante, aucune donnée qui quitte ta machine. Cinq agents spécialisés collaborent via un dispatcher intelligent, partagent une mémoire persistante, et apprennent de tes habitudes au fil du temps.

Le projet est né le 6 février 2025, un mois après le lancement de Claude Cowork (12 jan – 10 fév 2025), avec une conviction : un assistant IA personnel devrait tourner sur **ton** hardware, connaître **ton** contexte après des mois d'utilisation, et ne jamais dépendre d'un serveur tiers.

<p align="center">
  <img src="docs/screenshot.png" alt="0Lith screenshot" width="700" />
</p>

## Les agents

| Agent | Rôle | Modèle | Spécialité |
|-------|------|--------|------------|
| **Hodolith** | Dispatcher | Qwen3 1.7B | Classifie chaque message et le route vers le bon agent. Toujours en VRAM (~2 Go). |
| **Monolith** | Orchestrateur | Qwen3 14B | Raisonnement en chaîne de pensée, planification, coordination. |
| **Aerolith** | Codeur | Qwen3 Coder 30B | Génération, review et debugging de code. CPU offload (~5 min par réponse). |
| **Cryolith** | Défensif (Blue Team) | Foundation-Sec 8B | Analyse de logs, détection d'anomalies, règles SIEM. |
| **Pyrolith** | Offensif (Red Team) | DeepHat V1 7B | Pentesting, CTF, exploitation. Isolé dans Docker. |

Les noms suivent une convention grecque : *Hodo-* (chemin), *Mono-* (unique), *Aero-* (air), *Pyro-* (feu), *Cryo-* (glace), avec le suffixe *-lith* (pierre) — solide, fondation.

## Architecture

```
┌──────────────────────────────────────────────┐
│  Tauri 2 (Rust)          Svelte 5 (Frontend) │
│  ├─ Sidecar Python ◄────► IPC stdin/stdout   │
│  └─ Window management     Chat + Sidebar     │
├──────────────────────────────────────────────┤
│  Python Backend                               │
│  ├─ olith_core.py      Chat réactif (IPC)    │
│  ├─ olith_agents.py    Routage + exécution   │
│  ├─ olith_watcher.py   Background proactif   │
│  ├─ olith_history.py   Persistance sessions  │
│  ├─ olith_tools.py     Outils sandboxés      │
│  └─ olith_shared.py    Helpers partagés      │
├──────────────────────────────────────────────┤
│  Infra locale                                 │
│  ├─ Ollama             Inférence LLM         │
│  ├─ Qdrant             Base vectorielle      │
│  ├─ Mem0               Mémoire intelligente  │
│  └─ Docker             Isolation Pyrolith    │
└──────────────────────────────────────────────┘
```

## Prérequis

- **GPU** : NVIDIA avec ≥12 Go VRAM (testé sur RTX 5070 Ti 16 Go)
- **RAM** : 32 Go recommandé
- **OS** : Windows 10/11 ou Linux (Ubuntu 22+)
- **Logiciels** :
  - [Ollama](https://ollama.com) ≥ 0.6
  - [Docker Desktop](https://docker.com) (pour Pyrolith)
  - [Node.js](https://nodejs.org) ≥ 18
  - [Rust](https://rustup.rs) (pour Tauri)
  - Python ≥ 3.11

## Installation

```bash
# 1. Cloner le repo
git clone https://github.com/ISkyCraftI/0Lith.git
cd 0Lith

# 2. Télécharger les modèles Ollama
ollama pull qwen3:1.7b          # Hodolith — dispatcher
ollama pull qwen3:14b           # Monolith — orchestrateur
ollama pull qwen3-coder:30b     # Aerolith — codeur

# Modèles spécialisés (cybersec)
ollama pull deephat/DeepHat-V1-7B                          # Pyrolith
ollama pull hf.co/fdtn-ai/Foundation-Sec-8B-Q4_K_M-GGUF   # Cryolith

# 3. Lancer Qdrant
docker run -d --name qdrant -p 6333:6333 -p 6334:6334 \
  -v ~/.qdrant/storage:/qdrant/storage qdrant/qdrant

# 4. Installer les dépendances Python
cd 0lith-desktop/py-backend
pip install -r requirements.txt

# 5. Initialiser la mémoire
python olith_memory_init.py

# 6. Installer les dépendances frontend et lancer
cd ..
npm install
npm run tauri dev
```

## Configuration Ollama recommandée

Pour optimiser le chargement rotatif des modèles sur 16 Go de VRAM :

```bash
# Max 2 modèles en VRAM simultanément
export OLLAMA_MAX_LOADED_MODELS=2

# Libérer la VRAM après 5 min d'inactivité
export OLLAMA_KEEP_ALIVE=5m

# Un seul thread par modèle (économise la VRAM)
export OLLAMA_NUM_PARALLEL=1

# Attention flash + cache KV quantifié
export OLLAMA_FLASH_ATTENTION=true
export OLLAMA_KV_CACHE_TYPE=q8_0
```

## Stack technique

| Couche | Technologie | Rôle |
|--------|-------------|------|
| Desktop | Tauri 2 (Rust) | Fenêtre native, sidecar Python, IPC |
| Frontend | Svelte 5 (runes) | UI réactive, chat, sidebar |
| Backend | Python 3.11+ | Agents, routage, mémoire, outils |
| Inférence | Ollama (llama.cpp) | Modèles GGUF quantifiés Q4_K_M |
| Mémoire | Mem0 + Qdrant | Extraction de faits, recherche sémantique |
| Graphe | Kuzu (optionnel) | Knowledge graph, relations multi-hop |
| Isolation | Docker | Sandbox pour l'agent offensif |
| Styling | Tailwind + bits-ui | Composants UI, dark theme |

## Fonctionnalités actuelles (v0.1)

- [x] Chat multi-agents avec routage automatique via Hodolith
- [x] Streaming des réponses en temps réel
- [x] Mémoire partagée entre agents (Mem0 + Qdrant)
- [x] Persistance des conversations (JSON, `~/.0lith/chats/`)
- [x] Historique des sessions dans la sidebar
- [x] Sandbox filesystem (validation de chemin, protection symlink)
- [x] Cancel gracieux des réponses (IPC + fallback kill)
- [x] Retry avec backoff exponentiel (Ollama, Mem0)
- [x] Filtrage mémoire intelligent (ignore les messages triviaux)
- [x] Cross-platform system info (psutil)
- [x] Indicateurs de statut : Backend, Ollama, Qdrant

## Roadmap

```
FAIT ────────────────────────────────────
✅ Chat réactif avec 5 agents
✅ Mémoire vectorielle persistante
✅ Interface Tauri + Svelte 5
✅ Sécurité : sandbox, lane queue, cancel, retry

EN COURS ────────────────────────────────
🔄 Frontend sessions (sidebar complète)
🔄 Suppression de conversations

COURT TERME ─────────────────────────────
⬜ Onglets sidebar (Agents / Historique)
⬜ OLithEye animé (logo SVG dynamique)
⬜ Gaming Mode (libérer la VRAM)
⬜ System Tray (background, notifications)
⬜ MCP Server pour Zed.dev
⬜ README + docs complètes

MOYEN TERME ─────────────────────────────
⬜ Système proactif (file watcher, suggestions)
⬜ Shadow Thinking (anticipation)
⬜ Agents enfichables via YAML
⬜ Dock Game Dev (Storylith, Artlith, Gamelith)

LONG TERME ──────────────────────────────
⬜ Google Takeout ingestion
⬜ Calendrier + données santé
⬜ Fine-tuning LoRA par agent
⬜ Réseau multi-machine (Tailscale)
⬜ BCI (Brain Computer Interface)
```

## Philosophie

**Offline first** — Tout tourne en local. Pas de cloud. Pas de clé API. Pas de dépendance réseau.

**La VRAM est sacrée** — Le gaming a toujours la priorité. 0Lith se retire silencieusement quand tu lances un jeu.

**La mémoire est le fossé** — L'avantage de 0Lith sur Claude ou GPT n'est pas l'intelligence brute, c'est qu'après des mois d'utilisation il connaît tes patterns, ton style, et ton contexte.

**Chaque mois est utilisable** — Jamais "en construction". Mois 1 = bon chat. Mois 2 = suggestions proactives. Mois 3 = agents enfichables. On peut s'arrêter à tout moment et c'est déjà utile.

**Niveau 2 jamais sans permission** — Le système observe et suggère, mais n'agit jamais de manière autonome sur des actions critiques.

## Contribuer

Le projet est en alpha et développé en solo pour l'instant. Les issues et suggestions sont les bienvenues.

## Licence

MIT

---

<p align="center">
  <em>Forgé dans la pierre, affûté par le feu, protégé par la glace.</em>
</p>
