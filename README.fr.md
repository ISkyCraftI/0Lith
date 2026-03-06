<p align="center">
  <img src="Logo_texture.svg" alt="0Lith" width="100" />
</p>

<h1 align="center">0Lith</h1>

<p align="center">
  Ton cockpit multi-agents IA souverain et local.<br/>
  Cybersécurité · Développement · Anticipation.
</p>

<p align="center">
  <img src="https://img.shields.io/badge/status-alpha%20v0.1-orange" />
  <img src="https://img.shields.io/badge/license-AGPL--3.0-blue" />
  <img src="https://img.shields.io/badge/python-3.12-blue" />
  <img src="https://img.shields.io/badge/Tauri-2-purple" />
  <img src="https://img.shields.io/badge/platform-Windows%20%7C%20Linux-lightgrey" />
  <img src="https://img.shields.io/badge/GPU-RTX%205070%20Ti%2016%20Go-green" />
</p>

<p align="center">
  <a href="README.md">🇬🇧 Read in English</a>
</p>

---

## Qu'est-ce que 0Lith ?

0Lith (prononcé "Olith") est un **cockpit multi-agents IA personnel** qui tourne **entièrement en local** — aucun cloud, aucune API payante, aucune donnée qui quitte ta machine. Cinq agents spécialisés collaborent via un dispatcher intelligent, partagent une mémoire persistante, et apprennent de tes habitudes au fil du temps.

Né le 6 février 2025 avec une conviction : un assistant IA personnel devrait tourner sur **ton** hardware, connaître **ton** contexte après des mois d'utilisation, et ne jamais dépendre d'un serveur tiers. 0Lith est le seul outil open-source qui combine orchestration multi-agents, GUI desktop native, exécution 100% locale, et spécialisation cybersécurité.

## Démo

<p align="center">
  <img src="docs/screenshot.png" alt="0Lith screenshot" width="700" />
</p>

> GIF de démonstration à venir.

## Les agents

| Agent | Rôle | Modèle | Spécialité |
|-------|------|--------|------------|
| **Hodolith** | Dispatcher | Qwen3 1.7B | Classifie chaque message et le route vers le bon agent. Toujours en VRAM (~2 Go). |
| **Monolith** | Orchestrateur | Qwen3 14B | Raisonnement en chaîne de pensée, planification, coordination. |
| **Aerolith** | Codeur | Qwen3 Coder 30B | Génération, review et debugging de code. CPU offload (~5 min par réponse). |
| **Cryolith** | Blue Team | Foundation-Sec 8B | Analyse de logs, détection d'anomalies, règles SIEM. |
| **Pyrolith** | Red Team | DeepHat V1 7B | Pentesting, CTF, exploitation. Isolé dans Docker. |

Les noms suivent une convention grecque : *Hodo-* (chemin), *Mono-* (unique), *Aero-* (air), *Pyro-* (feu), *Cryo-* (glace) — avec le suffixe *-lith* (pierre) symbolisant une fondation solide.

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
│  ├─ olith_arena.py     Sparring Red vs Blue  │
│  ├─ olith_watcher.py   Background proactif   │
│  ├─ olith_history.py   Persistance sessions  │
│  ├─ olith_tools.py     Outils sandboxés      │
│  ├─ olith_tasks.py     Tag #User + tâches    │
│  └─ olith_shared.py    Helpers partagés      │
├──────────────────────────────────────────────┤
│  Infra locale                                 │
│  ├─ Ollama             Inférence LLM         │
│  ├─ Qdrant             Base vectorielle      │
│  ├─ Mem0               Mémoire intelligente  │
│  └─ Docker             Isolation Pyrolith    │
└──────────────────────────────────────────────┘
```

## Matériel requis

| Composant | Requis | Notes |
|-----------|--------|-------|
| **GPU** | NVIDIA ≥ 12 Go VRAM | Testé sur RTX 5070 Ti 16 Go (Blackwell) |
| **RAM** | 32 Go recommandé | Agents + Python + OS |
| **Stockage** | 100 Go+ NVMe | OS + cache Ollama + index Qdrant |
| **OS** | Windows 10/11 ou Linux (Ubuntu 22+) | Windows 11 recommandé |

### Budget VRAM (exemple 16 Go)

| Toujours chargé | ~2 Go | Hodolith (1,5 Go) + modèle d'embeddings (0,6 Go) |
|-----------------|-------|--------------------------------------------------|
| Monolith à la demande | ~10 Go | Total ~12 Go / 16 Go |
| Cryolith à la demande | ~5 Go | Total ~7 Go / 16 Go |
| Aerolith à la demande | ~18 Go | CPU offload — lent mais fonctionnel |
| Pyrolith (Docker) | ~5 Go | Pool VRAM séparé via `--gpus all` |

> **Gaming Mode** : tous les modèles déchargés → 0 Go utilisé par 0Lith → VRAM entière disponible pour les jeux.

## Prérequis

- [Ollama](https://ollama.com) **≥ 0.16.1** — requis pour RTX 5070 Ti / Blackwell (0.15.x retombe silencieusement sur CPU)
- [Docker Desktop](https://docker.com) — pour Qdrant et le sandbox Pyrolith
- [Node.js](https://nodejs.org) ≥ 18
- [Rust](https://rustup.rs) (pour la compilation Tauri)
- **Python 3.12** — pas 3.13+, incompatible avec la base de graphe Kuzu

## Démarrage rapide

```bash
# 1. Cloner le repo
git clone https://github.com/ISkyCraftI/0Lith.git
cd 0Lith
```

```bash
# 2. Télécharger les modèles Ollama
ollama pull qwen3:1.7b               # Hodolith — dispatcher
ollama pull qwen3:14b                # Monolith — orchestrateur
ollama pull qwen3-coder:30b          # Aerolith — codeur
ollama pull qwen3-embedding:0.6b     # Embeddings (1024 dims, code-aware)
ollama pull hf.co/fdtn-ai/Foundation-Sec-8B-Q4_K_M-GGUF  # Cryolith
```

```bash
# 3. Lancer les services Docker
# Base vectorielle Qdrant (migration prévue vers le mode embarqué — Docker ne sera plus requis)
docker run -d --name qdrant -p 6333:6333 -p 6334:6334 \
  -v ~/.qdrant/storage:/qdrant/storage qdrant/qdrant

# Pyrolith — agent Red Team (instance Ollama isolée)
docker run -d --name pyrolith -p 11435:11434 --gpus all ollama/ollama
docker exec pyrolith ollama pull deephat/DeepHat-V1-7B
```

```bash
# 4. Installer les dépendances Python et initialiser la mémoire
cd 0lith-desktop/py-backend
pip install -r requirements.txt
python olith_memory_init.py
```

```bash
# 5. Installer les dépendances frontend et lancer
cd ..
npm install
npm run tauri dev
```

## Configuration Ollama

Variables d'environnement recommandées pour le chargement rotatif des modèles sur 16 Go de VRAM :

```bash
OLLAMA_MAX_LOADED_MODELS=2     # Max 2 modèles en VRAM simultanément
OLLAMA_KEEP_ALIVE=5m           # Libérer la VRAM après 5 min d'inactivité
OLLAMA_NUM_PARALLEL=1          # Un thread par modèle (économise la VRAM)
OLLAMA_FLASH_ATTENTION=true    # Flash attention
OLLAMA_KV_CACHE_TYPE=q8_0      # Cache KV quantifié
```

## Stack technique

| Couche | Technologie | Rôle |
|--------|-------------|------|
| Desktop | Tauri 2 (Rust) | Fenêtre native, sidecar Python, IPC |
| Frontend | Svelte 5 (runes) | UI réactive, chat, sidebar |
| Backend | Python 3.12 | Agents, routage, mémoire, outils |
| Inférence | Ollama (llama.cpp) | Modèles GGUF quantifiés Q4_K_M |
| Embeddings | qwen3-embedding:0.6b | #1 MTEB Multilingual, 1024 dims, code-aware |
| Mémoire | Mem0 + Qdrant | Extraction de faits, recherche sémantique |
| Graphe | Kuzu (optionnel) | Knowledge graph, relations multi-hop |
| Isolation | Docker | Sandbox pour l'agent offensif |
| Styling | TailwindCSS 4 + bits-ui | Composants UI, dark theme |

## Fonctionnalités (v0.1)

- [x] Chat multi-agents avec routage automatique via Hodolith
- [x] Streaming des réponses en temps réel
- [x] Mémoire partagée entre agents (Mem0 + Qdrant + qwen3-embedding:0.6b)
- [x] Persistance des conversations (JSON, `~/.0lith/chats/`)
- [x] Historique des sessions dans la sidebar
- [x] Sandbox filesystem (validation de chemin, protection symlink)
- [x] Cancel gracieux des réponses (IPC + fallback kill)
- [x] Retry avec backoff exponentiel (Ollama, Mem0)
- [x] Filtrage mémoire intelligent (ignore les messages triviaux)
- [x] Cross-platform system info (psutil)
- [x] Indicateurs de statut : Backend, Ollama, Qdrant
- [x] Gaming Mode (libération complète de la VRAM)
- [x] System Tray (background, notifications, menu Gaming Mode)
- [x] Background loop proactif (olith_watcher.py, file watcher, panel suggestions)
- [x] Outils sandboxés pour agents (lecture/recherche de fichiers, system info)
- [x] **Arena** — Sparring SQLi Pyrolith (Red) vs Cryolith (Blue) : 5 rounds en direct, streaming temps réel, score, analyse post-combat
- [x] UX Arena — bouton stop, verrouillage onglet, chrono, timer par mouvement, détails dépliables, badge ARENA, sélecteur scénario, dots progression rounds, symboles Unicode, animation chargement, badge VICTOIRE, export session
- [x] Robustesse Arena — timeouts adaptatifs par modèle, fallback auto qwen3:14b, séquences de types forcées, fenêtre contexte 2 rounds, session 30 min
- [x] Logs de session Arena (`~/.0lith/arena_logs/`) — fichier `.jsonl` par session avec les réponses LLM brutes
- [x] Système de tâches `#User` — les agents signalent leurs blocages dans `~/.0lith/Tasks/User_needed.md`, nettoyé automatiquement au prochain message

## Roadmap

```
FAIT ────────────────────────────────────────
✅ Phase 0 : Prototype IPC Svelte ↔ Tauri ↔ Python
✅ Phase 1 : Backend Python complet (agents, routage Hodolith, Mem0/Qdrant)
✅ Phase 2 : Interface chat (sidebar agents, streaming, markdown, dark theme)
✅ Phase 3 : Gaming Mode (déchargement VRAM, toggle sidebar + tray)
✅ Phase 3 : System Tray (background, notifications, Show/Hide/Quit)
✅ Phase 3 : Background loop (file watcher, suggestions proactives)
✅ Sécurité : sandbox filesystem, lane queue, cancel IPC, retry + backoff
✅ Persistance : sessions JSON, historique sidebar
✅ Arena : sparring SQLi Pyrolith vs Cryolith (5 rounds, direct, score + analyse)

COURT TERME ─────────────────────────────────
⬜ Shadow Thinking (anticipation proactive via Mem0)
⬜ OLithEye animé (logo SVG dynamique, couleur par agent)
⬜ Onglets sidebar (Agents / Historique séparés)
⬜ MCP Server pour Zed.dev

MOYEN TERME ─────────────────────────────────
⬜ Training Mode (sparring nocturne Pyrolith vs Cryolith sur des CVE + briefing matin)
⬜ Agents enfichables via YAML (dock architecture)
⬜ Dock Game Dev (Storylith, Artlith, Gamelith)
⬜ Dock Personnel (Schedulith, Econolith)

LONG TERME ──────────────────────────────────
⬜ Pipeline d'ingestion Google Takeout
⬜ Intégration calendrier + données santé
⬜ Fine-tuning LoRA par agent (QLoRA via Unsloth)
⬜ Réseau multi-machine (Tailscale)
⬜ Migration vers MemOS (quand mature)
```

## Philosophie

**Offline first** — Tout tourne en local. Pas de cloud. Pas de clé API. Pas de dépendance réseau.

**La VRAM est sacrée** — Le gaming a toujours la priorité. 0Lith se retire silencieusement quand tu lances un jeu.

**La mémoire est le fossé** — L'avantage de 0Lith sur Claude ou GPT n'est pas l'intelligence brute, c'est qu'après des mois d'utilisation il connaît tes patterns, ton style, et ton contexte.

**Chaque mois est utilisable** — Jamais "en construction". Mois 1 = bon chat. Mois 2 = suggestions proactives. Mois 3 = agents enfichables. On peut s'arrêter à tout moment et c'est déjà utile.

**Niveau 2 jamais sans permission** — Le système observe et suggère, mais n'agit jamais de manière autonome sur des actions critiques.

## Contribuer

Le projet est en alpha et développé en solo pour l'instant. Les issues et suggestions sont les bienvenues.

**Note sur la licence** : 0Lith est AGPL-3.0. L'utilisation ou la distribution commerciale nécessite soit la conformité AGPL (open-sourcing de tes modifications) soit un accord de licence commerciale séparé.

## Licence

[GNU Affero General Public License v3.0](LICENSE) — Copyright (C) 2025 ISkyCraftI

---

<p align="center">
  <em>Forgé dans la pierre, affûté par le feu, protégé par la glace.</em>
</p>
