# MISSION: Créer l'application Desktop 0Lith avec Tauri 2 + Python Backend

## CONTEXTE

Je développe un système multi-agents appelé **0Lith** (avec un zéro) pour la cybersécurité et l'assistance au développement. J'ai déjà un système de mémoire fonctionnel en Python (Mem0 + Qdrant + optionnellement Kuzu) avec 5 agents spécialisés qui tournent via Ollama en local sur une RTX 5070 Ti (16 Go VRAM).

### Les 5 agents 0Lith

| Agent | Modèle Ollama | Rôle | Emoji | Couleur hex |
|-------|---------------|------|-------|-------------|
| **Hodolith** | `qwen3:1.7b` | Dispatcher — route les requêtes | 🟨 | `#FFB02E` |
| **Monolith** | `qwen3:14b` | Orchestrateur — raisonnement /think | ⬛ | `#181A1E` |
| **Aerolith** | `qwen3-coder:30b` | Codeur — génération de code | 🟩 | `#43AA8B` |
| **Cryolith** | `Foundation-Sec-8B-Q4_K_M` | Blue Team — défense, CVE, détection | 🟦 | `#7BDFF2` |
| **Pyrolith** | `DeepHat-V1-7B` (Docker) | Red Team — pentest, exploitation | 🟥 | `#BF0603` |

L'interface n'est pas statique. Chaque agent est représenté par une "pupille" (basée sur `Base.png`) qui sert d'indicateur d'état et de présence.

### Comportement de la Pupille
[[Agents/Base.png]]
L'icône centrale de l'agent actif réagit en temps réel :
- **Clignement** : Aléatoire pour simuler la vie.
- **Regard** : La pupille se déplace vers la zone de chat lors d'une réponse, ou vers le code lors d'une action d'Aerolith.
- **3 points horizontaux** : Montée et descente lente lors des phases de réflexion.
- **Changement de Couleur** : La pupille adopte la couleur spécifique de l'agent qui prend la main.

### Background

Fond Principal : #282C33

### Contrainte VRAM importante

La RTX 5070 Ti a 16 Go de VRAM. Tous les agents ne peuvent pas tourner simultanément :

- **Toujours actifs** : Hodolith (1.7B, ~1.5 Go) + qwen3-embedding:0.6b (~0.4 Go) = ~2 Go
- **Swap dynamique** : Un seul "gros" agent à la fois parmi Monolith (14B, ~10 Go), Aerolith (30B, ~18 Go via CPU offload partiel), Cryolith (8B, ~5 Go)
- **Pyrolith** : Tourne dans Docker, séparé, chargé uniquement pendant le sparring
- **Aerolith (30B)** : Dépasse les 16 Go VRAM — Ollama fera du CPU offload automatique. C'est volontaire : je préfère un codeur lent (3-5 min) mais de haute qualité, autonome même sans réseau. Le frontend doit gérer les réponses lentes (timeout élevé, indicateur de progression).

### Fichier existant

Le fichier `olith_memory_init.py` (fourni) contient :
- Configuration Mem0 avec qwen3-embedding:0.6b + Qdrant + Kuzu
- Définition complète des 5 agents (identité, capacités, relations)
- Protocole de sparring Red vs Blue
- Tests de vérification mémoire
- Mode dégradé sans Kuzu (vecteurs seulement)

## OBJECTIF FINAL

Application desktop native (Tauri 2) qui :
1. Affiche un dashboard des 5 agents avec leurs couleurs et statuts
2. Communique avec le backend Python via process spawn (stdin/stdout JSON)
3. Permet de chatter avec les agents (routage automatique via Hodolith)
4. Observe les modifications de fichiers d'un projet (file watcher)
5. Tourne en arrière-plan (system tray)
6. Est optimisée pour performance (< 50MB RAM idle, hors modèles Ollama)

---

## STACK TECHNIQUE

| Couche | Technologie | Version | Notes |
|--------|-------------|---------|-------|
| **Framework desktop** | Tauri | **2.x** (pas v1) | Utiliser les plugins v2 |
| **Frontend** | Svelte | **5** (runes syntax) | Pas Svelte 4 |
| **Langage frontend** | TypeScript | 5.x | Strict mode |
| **Styling** | TailwindCSS 4 | 4.x | |
| **Composants UI** | bits-ui | latest | Alternative stable à shadcn-svelte pour Svelte 5 |
| **Icônes** | Lucide Svelte | latest | |
| **Backend** | Python | 3.12 | **PAS 3.13+** (incompatible Kuzu) |
| **Communication** | Process spawn | stdin/stdout | JSON line-delimited |
| **Mémoire** | Mem0 + Qdrant | latest | Docker pour Qdrant |
| **Graphe (optionnel)** | Kuzu | 0.8.x+ | Embarqué, pas de serveur |
| **Embeddings** | qwen3-embedding:0.6b | via Ollama | 1024 dimensions |
| **LLMs** | Ollama | latest | Tous les modèles locaux |

### Points critiques Tauri 2 vs Tauri 1

> **ATTENTION** : Tauri 2 a une API très différente de Tauri 1. Ne pas utiliser de code Tauri v1.

- **System tray** : Plugin `@tauri-apps/plugin-tray-icon` (pas une feature Cargo)
- **Shell/Sidecar** : Plugin `@tauri-apps/plugin-shell` avec feature `open` ou `shell-sidecar`
- **Process spawn** : `Command.create()` depuis `@tauri-apps/plugin-shell` côté JS
- **Config** : `tauri.conf.json` v2 a un schema différent (pas de `tauri.allowlist`)
- **Permissions** : Système de capabilities/permissions dans `src-tauri/capabilities/`
- **Invoke** : `import { invoke } from '@tauri-apps/api/core'` (pas `@tauri-apps/api/tauri`)

Toujours consulter https://v2.tauri.app/start/ pour la syntaxe correcte.

---

## STRUCTURE DU PROJET

```
0lith-desktop/
├── src-tauri/                  # Backend Rust/Tauri 2
│   ├── src/
│   │   └── lib.rs              # Tauri 2 utilise lib.rs, pas main.rs
│   ├── capabilities/
│   │   └── default.json        # Permissions Tauri 2
│   ├── Cargo.toml
│   ├── tauri.conf.json
│   └── icons/
├── src/                        # Frontend Svelte 5
│   ├── lib/
│   │   ├── components/
│   │   │   ├── AgentCard.svelte
│   │   │   ├── ChatInterface.svelte
│   │   │   ├── StatusIndicator.svelte
│   │   │   └── Sidebar.svelte
│   │   ├── stores/
│   │   │   └── agents.svelte.ts    # Runes (.svelte.ts)
│   │   └── types/
│   │       └── agents.ts
│   ├── App.svelte
│   └── main.ts
├── py-backend/                 # Backend Python
│   ├── olith_core.py           # Wrapper IPC principal
│   ├── olith_memory_init.py    # Fichier existant (fourni)
│   ├── file_watcher.py         # Observer de fichiers
│   └── requirements.txt
├── package.json
├── svelte.config.js
├── tsconfig.json
├── tailwind.config.js
└── vite.config.ts
```

---

## PHASE 0: PROTOTYPE PING-PONG (FAIRE EN PREMIER)

> **CRITIQUE** : Ne pas passer à la Phase 1 tant que ce ping-pong ne fonctionne pas.

L'objectif est de valider la chaîne complète Svelte → Tauri → Python → Tauri → Svelte avec le minimum de code possible.

### Étape 0.1: Créer le projet Tauri 2 + Svelte 5

```bash
# Créer avec le template officiel Tauri 2
npm create tauri-app@latest 0lith-desktop -- --template svelte-ts
cd 0lith-desktop
npm install
```

Si `npm create tauri-app@latest` ne propose pas Svelte 5, utiliser :
```bash
npm create vite@latest 0lith-desktop -- --template svelte-ts
cd 0lith-desktop
npm install
npx @tauri-apps/cli@latest init
npm install @tauri-apps/cli@latest @tauri-apps/api@latest
```

### Étape 0.2: Installer le plugin shell pour Tauri 2

```bash
# Plugin shell Tauri 2 (côté JS)
npm install @tauri-apps/plugin-shell
```

Dans `src-tauri/Cargo.toml`, ajouter :
```toml
[dependencies]
tauri = { version = "2", features = [] }
tauri-plugin-shell = "2"
serde = { version = "1", features = ["derive"] }
serde_json = "1"
```

Dans `src-tauri/capabilities/default.json` :
```json
{
  "$schema": "../gen/schemas/desktop-schema.json",
  "identifier": "default",
  "description": "Default capabilities",
  "windows": ["main"],
  "permissions": [
    "core:default",
    "shell:allow-spawn",
    "shell:allow-stdin-write"
  ]
}
```

### Étape 0.3: Script Python minimal

**Fichier: `py-backend/ping.py`**
```python
#!/usr/bin/env python3
"""Ping-pong minimal pour valider l'IPC Tauri <-> Python."""
import sys
import json

def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
            response = {
                "status": "ok",
                "echo": request.get("message", ""),
                "agent": "hodolith",
                "python_version": sys.version,
            }
            print(json.dumps(response), flush=True)
        except json.JSONDecodeError as e:
            print(json.dumps({"status": "error", "message": str(e)}), flush=True)

if __name__ == "__main__":
    main()
```

### Étape 0.4: Appel Python depuis Svelte via Tauri 2

**Dans `src-tauri/src/lib.rs`** :
```rust
use tauri::Manager;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
```

**Dans `src/App.svelte`** (test minimal Svelte 5 runes) :
```svelte
<script lang="ts">
  import { Command } from '@tauri-apps/plugin-shell';

  let response = $state('');
  let loading = $state(false);

  async function ping() {
    loading = true;
    try {
      const cmd = Command.create('python-backend', [
        'py-backend/ping.py'
      ]);

      // Écouter stdout
      cmd.stdout.on('data', (data: string) => {
        try {
          const parsed = JSON.parse(data);
          response = JSON.stringify(parsed, null, 2);
        } catch { }
      });

      const child = await cmd.spawn();

      // Envoyer un message via stdin
      await child.write(JSON.stringify({ message: 'Hello from 0Lith!' }) + '\n');
    } catch (e) {
      response = `Erreur: ${e}`;
    }
    loading = false;
  }
</script>

<main class="p-8">
  <h1 class="text-2xl font-bold mb-4">🔷 0Lith — Test IPC</h1>
  <button onclick={ping} class="bg-blue-600 text-white px-4 py-2 rounded">
    {loading ? 'Envoi...' : 'Ping Python'}
  </button>
  {#if response}
    <pre class="mt-4 p-4 bg-gray-100 rounded text-sm">{response}</pre>
  {/if}
</main>
```

### Étape 0.5: Configurer le spawn Python dans `tauri.conf.json`

```json
{
  "plugins": {
    "shell": {
      "scope": [
        {
          "name": "python-backend",
          "cmd": "python",
          "args": [
            { "validator": "\\S+" }
          ]
        }
      ]
    }
  }
}
```

> **Note Windows** : Le `cmd` peut être `python` ou `python3` selon l'installation. Si Python est dans un venv, utiliser le chemin complet : `py-backend/.venv/Scripts/python.exe`

### Critères de succès Phase 0 ✅ VALIDÉ

- [x] `npm run tauri dev` lance l'application
- [x] Le bouton "Ping Python" envoie un message JSON
- [x] Python le reçoit sur stdin, répond sur stdout
- [x] Svelte affiche la réponse dans l'interface
- [x] Aucune erreur dans la console Rust ni dans la console navigateur

---

## PHASE 1: BACKEND PYTHON COMPLET

### Étape 1.1: Wrapper principal IPC

**Fichier: `py-backend/olith_core.py`**

Ce fichier remplace `ping.py` et devient le vrai backend. Il doit :

```python
"""
Protocole IPC : JSON line-delimited sur stdin/stdout.

Format requête (Frontend → Python) :
  {"id": "uuid", "command": "chat|status|search|memory_init", ...params}

Format réponse (Python → Frontend) :
  {"id": "uuid", "status": "ok|error", ...data}

Chaque requête a un "id" unique pour matcher requête/réponse côté frontend.
"""
```

**Commandes à implémenter** :

| Commande | Params | Description |
|----------|--------|-------------|
| `status` | — | Retourne état Ollama, Qdrant, chaque agent (modèle chargé ou non) |
| `chat` | `message: str`, `agent_id?: str` | Si agent_id fourni → direct. Sinon → Hodolith route. |
| `search` | `query: str`, `agent_id: str` | Recherche mémoire Mem0 |
| `memory_init` | — | Lance `olith_memory_init.py` (enregistre identités) |
| `agents_list` | — | Retourne la liste des 5 agents avec métadonnées |

**Pour la commande `chat`** — Communication avec Ollama :
```python
import requests

def chat_with_ollama(model: str, messages: list[dict], stream: bool = False) -> str:
    """Appel direct à l'API Ollama."""
    response = requests.post(
        "http://localhost:11434/api/chat",
        json={
            "model": model,
            "messages": messages,
            "stream": stream,
            "options": {
                "num_ctx": 8192,  # Contexte suffisant
            }
        },
        timeout=600,  # 10 min — Aerolith 30B peut être très lent
    )
    response.raise_for_status()
    return response.json()["message"]["content"]
```

**Flow de routage** :
1. User envoie message
2. Hodolith (qwen3:1.7b) analyse et décide quel agent répondre
3. L'agent choisi reçoit le message + ses mémoires pertinentes (via Mem0 search)
4. L'agent répond
5. La réponse + le contexte sont stockés en mémoire (via Mem0 add)

**Le system prompt de Hodolith pour le routage** :
```
Tu es Hodolith, le dispatcher du système 0Lith. Analyse le message de l'utilisateur
et réponds UNIQUEMENT avec un JSON :
{"route": "monolith|aerolith|cryolith|pyrolith|hodolith", "reason": "..."}

Règles de routage :
- Questions générales, stratégie, planification → monolith
- Écriture de code, scripts, debug, outils → aerolith
- Défense, CVE, détection, YARA, hardening → cryolith
- Pentest, exploitation, red team, attaque → pyrolith
- Questions simples sur le système 0Lith → hodolith (toi-même)
```

### Étape 1.2: Gestion du streaming ✅ IMPLEMENTÉ

Le streaming est implémenté end-to-end. Le protocole IPC envoie des réponses partielles :

```python
# Réponse streaming : plusieurs lignes JSON avec le même "id"
# 1. Routing (immédiat après Hodolith)
{"id": "abc", "status": "routing", "agent_id": "monolith", "agent_name": "Monolith", ...}
# 2. Tokens (au fur et à mesure de la génération Ollama)
{"id": "abc", "status": "streaming", "chunk": "Voici le début"}
{"id": "abc", "status": "streaming", "chunk": " de ma réponse"}
# 3. Final (après génération complète + stockage mémoire)
{"id": "abc", "status": "ok", "response": "Voici le début de ma réponse", ...}
```

**Implémentation :**
- Backend : `chat_with_ollama_stream()` generator + `emit()` callback dans `cmd_chat()`
- Frontend : `pythonBackend.send()` accepte `onStream` callback, `handleStdout` dispatch `streaming`/`routing` au callback
- Chat store : crée une bulle agent vide au routing, append les chunks, finalise au `ok`
- UI : indicateur "Réflexion..." disparaît dès le premier token (le texte stream dans la bulle)

### Étape 1.3: File Watcher

**Fichier: `py-backend/file_watcher.py`**

Utilise `watchdog` pour surveiller un dossier projet. Quand un fichier est modifié :
1. Notifier le frontend via stdout (event JSON)
2. Optionnellement analyser le diff avec Aerolith

```python
# Format des événements file watcher :
{"event": "file_changed", "path": "/project/src/main.py", "change_type": "modified"}
{"event": "file_changed", "path": "/project/src/utils.py", "change_type": "created"}
```

### Étape 1.4: Requirements

**Fichier: `py-backend/requirements.txt`**
```
mem0ai>=1.0.0
qdrant-client>=1.7.0
watchdog>=3.0.0
requests>=2.31.0
ollama>=0.4.0
```

> **Note** : Kuzu n'est PAS dans les requirements de base. Il est optionnel.
> Si Python 3.12 : `pip install kuzu` devrait fonctionner.
> Si Python 3.13+ : Kuzu ne compile pas. Le système fonctionne sans (mode vecteurs uniquement).
> Pour installer avec graphe : `pip install "mem0ai[graph]"`

### Critères de succès Phase 1 ✅ VALIDÉ

- [x] `python py-backend/olith_core.py` accepte JSON sur stdin, répond sur stdout
- [x] Commande `status` retourne l'état réel d'Ollama et Qdrant
- [x] Commande `chat` route via Hodolith et obtient une réponse d'un agent
- [x] Commande `search` retourne des mémoires depuis Qdrant
- [x] Timeout de 600s pour les réponses lentes (Aerolith 30B)
- [x] Les erreurs retournent `{"status": "error", "message": "..."}`, jamais de crash

---

## PHASE 2: FRONTEND INTERFACE

### Étape 2.1: Setup CSS et composants

```bash
npm install -D tailwindcss @tailwindcss/vite
npm install bits-ui lucide-svelte
```

**Thème de couleurs des agents** dans `tailwind.config.js` ou via CSS custom properties :
```css
:root {
  --hodolith: #EAB308;
  --monolith: #3B82F6;
  --aerolith: #22C55E;
  --cryolith: #0EA5E9;
  --pyrolith: #EF4444;
  --bg-primary: #0F172A;    /* Slate 900 — dark theme */
  --bg-secondary: #1E293B;  /* Slate 800 */
  --text-primary: #F8FAFC;  /* Slate 50 */
}
```

**Direction artistique** : Dark theme obligatoire. L'UI doit évoquer un terminal de sécurité / SOC dashboard. Pas de blanc, pas de mode clair.

### Étape 2.2: Types TypeScript

**Fichier: `src/lib/types/agents.ts`**
```typescript
export type AgentId = 'hodolith' | 'monolith' | 'aerolith' | 'cryolith' | 'pyrolith';
export type AgentRole = 'Dispatcher' | 'Orchestrateur' | 'Codeur' | 'Blue Team' | 'Red Team';
export type AgentStatus = 'idle' | 'thinking' | 'responding' | 'loading_model' | 'error' | 'offline';

export interface Agent {
  id: AgentId;
  name: string;
  role: AgentRole;
  model: string;
  color: string;       // Hex
  emoji: string;
  status: AgentStatus;
  description: string;
  capabilities: string[];
  vram_gb: number;     // VRAM estimée
}

export interface ChatMessage {
  id: string;
  agentId: AgentId;
  content: string;
  timestamp: number;
  type: 'user' | 'agent' | 'system' | 'routing';
  isStreaming?: boolean;
}

export interface IPCRequest {
  id: string;
  command: 'chat' | 'status' | 'search' | 'memory_init' | 'agents_list';
  [key: string]: unknown;
}

export interface IPCResponse {
  id: string;
  status: 'ok' | 'error' | 'streaming' | 'done';
  [key: string]: unknown;
}
```

### Étape 2.3: Store agents (Svelte 5 runes)

**Fichier: `src/lib/stores/agents.svelte.ts`**
```typescript
// Utiliser les runes Svelte 5, PAS les stores Svelte 4
// $state, $derived, $effect — PAS writable(), derived()
```

### Étape 2.4: Layout principal

```
┌──────────────────────────────────────────────────────┐
│  🔷 0Lith                              ─  □  ×      │
├────────────┬─────────────────────────────────────────┤
│            │                                         │
│  AGENTS    │           CHAT AREA                     │
│            │                                         │
│ 🟡 Hodolith│  [Hodolith] Routage vers Monolith...   │
│   idle     │  [Monolith] Voici mon analyse...        │
│            │                                         │
│ 🔵 Monolith│                                         │
│   thinking │                                         │
│            │                                         │
│ 🟢 Aerolith│                                         │
│   idle     │                                         │
│            │                                         │
│ 🔷 Cryolith│                                         │
│   idle     │                                         │
│            │                                         │
│ 🔴 Pyrolith│                                         │
│   offline  │                                         │
│            ├─────────────────────────────────────────┤
│            │  [Message input...              ] [⏎]  │
│ ⚙ Settings │                                         │
├────────────┴─────────────────────────────────────────┤
│  Mem: 2.1 GB VRAM │ Qdrant: ✅ │ Ollama: ✅          │
└──────────────────────────────────────────────────────┘
```

**Composants requis** :

| Composant | Description |
|-----------|-------------|
| `Sidebar.svelte` | Liste des agents + settings |
| `AgentCard.svelte` | Carte d'un agent (nom, status, couleur) |
| `StatusIndicator.svelte` | Pastille animée (idle/thinking/error) |
| `ChatInterface.svelte` | Zone de chat principale |
| `MessageBubble.svelte` | Un message (user ou agent) avec markdown |
| `InputBar.svelte` | Input + bouton envoi + stop generation |
| `StatusBar.svelte` | Barre d'état en bas (VRAM, services) |

### Étape 2.5: Chat Interface — Détails

Le chat doit :
- Afficher le routage de Hodolith (ex: "🟡 Routé vers Monolith")
- Montrer quel agent répond (couleur + emoji)
- Support Markdown basique dans les réponses (code blocks surtout)
- Bouton "Stop generation" quand un agent répond
- Auto-scroll en bas
- Indicateur quand Aerolith charge le modèle 30B (peut prendre 30s+)
- Gérer les timeouts gracieusement (message "L'agent met plus de temps que prévu...")

### Critères de succès Phase 2 ✅ VALIDÉ

- [x] Dark theme cohérent, pas de blanc
- [x] Les 5 agents s'affichent dans la sidebar avec bonnes couleurs
- [x] Status des agents se met à jour (idle → thinking → responding)
- [x] Chat envoie message → reçoit routage Hodolith → reçoit réponse agent
- [x] Les code blocks sont rendus correctement dans les réponses
- [x] L'interface reste responsive même quand Aerolith prend 5 min

---

## PHASE 3: FEATURES AVANCÉES

### Étape 3.1: System Tray ✅ IMPLEMENTÉ

- Icône dans la barre système avec menu Show/Hide/Gaming Mode/Quit
- L'app continue de tourner en arrière-plan quand on ferme la fenêtre
- Notifications via `@tauri-apps/plugin-notification`
- Gaming Mode checkbox synchronisée avec le frontend

### Étape 3.2: File Watcher Integration ✅ IMPLEMENTÉ

- `olith_watcher.py` lancé en parallèle de `olith_core.py` par Tauri
- Surveillance des fichiers via watchdog
- Suggestions émises via stdout JSON, affichées dans SuggestionsBar
- Pause automatique en Gaming Mode

### Étape 3.3: Persistance locale ✅ IMPLEMENTÉ

- Historique de chat : fichiers JSON dans `~/.0lith/chats/`
- `olith_history.py` : session list, load, save, delete
- Historique des sessions dans la sidebar avec preview + date relative

### Étape 3.4: Gaming Mode ✅ IMPLEMENTÉ

- Toggle dans la sidebar et le menu system tray
- Décharge tous les modèles de la VRAM (Ollama keep_alive=0)
- `sync_tray_gaming` commande Tauri pour synchroniser l'état

### Étape 3.5: Sparring Mode (UI dédiée) — À FAIRE

Vue spéciale pour les sessions de sparring Red vs Blue :
- Split view : Pyrolith (gauche, rouge) vs Cryolith (droite, bleu)
- Monolith supervise (bandeau en haut)
- Timeline des actions attaque/défense
- Score et évaluation finale

---

## PROTOCOLE IPC — SPÉCIFICATION COMPLÈTE

### Transport

- **Mécanisme** : Process spawn via `@tauri-apps/plugin-shell`
- **Format** : JSON line-delimited (un JSON par ligne, terminé par `\n`)
- **Direction** : Bidirectionnel — Frontend écrit sur stdin, Python répond sur stdout
- **Encoding** : UTF-8
- **Erreurs Python** : stderr est capturé séparément pour le logging

### Schéma des messages

```typescript
// Frontend → Python (stdin)
interface Request {
  id: string;          // UUID v4, pour matcher la réponse
  command: string;     // Nom de la commande
  [key: string]: any;  // Paramètres spécifiques
}

// Python → Frontend (stdout)
interface Response {
  id: string;          // Même UUID que la requête
  status: 'ok' | 'error' | 'streaming' | 'done';
  [key: string]: any;  // Données de réponse
}

// Python → Frontend (événements non-sollicités)
interface Event {
  event: string;       // Type d'événement (pas de champ "id")
  [key: string]: any;  // Données
}
```

### Différencier réponse vs événement

- Si le JSON a un champ `id` → c'est une réponse à une requête
- Si le JSON a un champ `event` (sans `id`) → c'est un événement push (file watcher, etc.)

### Timeouts recommandés

| Commande | Timeout | Raison |
|----------|---------|--------|
| `status` | 10s | Rapide, juste des checks HTTP |
| `chat` (Hodolith) | 30s | 1.7B, très rapide |
| `chat` (Monolith) | 120s | 14B, raisonnement /think |
| `chat` (Aerolith) | 600s | 30B, CPU offload, peut être très lent |
| `chat` (Cryolith) | 60s | 8B, rapide |
| `chat` (Pyrolith) | 120s | 7B Docker, latence réseau interne |
| `search` | 10s | Qdrant est rapide |
| `memory_init` | 60s | Enregistre ~26 mémoires |

---

## TESTS & VALIDATION

### Phase 0 (bloquant) ✅
- [x] `npm run tauri dev` lance l'app sans erreur
- [x] Bouton ping → Python reçoit → Python répond → Svelte affiche
- [x] Fonctionne sur Windows (priorité)

### Phase 1 ✅
- [x] `python py-backend/olith_core.py` accepte JSON sur stdin
- [x] Commande `status` vérifie Ollama et Qdrant en temps réel
- [x] Commande `chat` avec routage Hodolith fonctionne
- [x] Les mémoires Mem0 sont stockées et récupérées

### Phase 2 ✅
- [x] Dark theme, pas de blanc
- [x] Les 5 agents s'affichent avec statuts corrects
- [x] Chat complet : input → routage → réponse → affiché
- [x] Responsive même avec Aerolith lent (5 min)

### Phase 3 ✅ (partiel)
- [x] System tray fonctionne sur Windows
- [x] File watcher détecte les modifications
- [x] Historique de chat persiste entre sessions
- [x] Gaming Mode décharge la VRAM
- [ ] Shadow Thinking (anticipation proactive)
- [ ] Sparring Mode UI

---

## CONTRAINTES TECHNIQUES

1. **Tauri 2 uniquement** — pas de code Tauri v1, vérifier la doc v2.tauri.app
2. **Svelte 5 runes** — `$state`, `$derived`, `$effect`, PAS `writable()` / Svelte 4 stores
3. **Performance** : < 50 MB RAM idle (hors Ollama/Qdrant)
4. **Windows first** : C'est ma plateforme principale
5. **Offline first** : Aucune dépendance réseau obligatoire, tout est local
6. **Sécurité** : Pas de `eval()`, sanitize tous les inputs, pas d'injection dans les commandes shell
7. **Timeout Aerolith** : Le frontend DOIT gérer les réponses lentes (600s) sans freeze
8. **Python 3.11/3.12** : Pas 3.13+ (compatibilité Kuzu)
9. **Pas de PyInstaller** : Python est exécuté directement (l'utilisateur a Python installé)

---

## PRIORITÉS D'EXÉCUTION

```
SPRINT 0 — Validation IPC ✅ FAIT
└─ Phase 0 : Tauri 2 + Svelte 5 + Python ping-pong

SPRINT 1 — Backend fonctionnel ✅ FAIT
├─ Phase 1 : Backend Python complet (olith_core, agents, ollama, tools)
└─ Intégrer olith_memory_init.py + Mem0/Qdrant

SPRINT 2 — UI complète ✅ FAIT
├─ Phase 2 : Composants frontend (sidebar, chat, streaming, markdown)
└─ Chat complet avec routage Hodolith

SPRINT 3 — Features avancées ✅ FAIT (partiel)
├─ System tray + gaming mode + file watcher + persistance
└─ Reste : Shadow Thinking, Sparring UI, agents YAML

SPRINT 4 — Prochaines étapes ⭐
├─ Shadow Thinking (anticipation proactive)
├─ Agents enfichables YAML (dock architecture)
└─ MCP Server pour Zed.dev
```

---

## LIVRABLES ATTENDUS

1. **Application fonctionnelle** qui se lance avec `npm run tauri dev`
2. **README.md** avec instructions de setup (prérequis, installation, lancement)
3. **Le protocole IPC** documenté (ce document fait office de spec)
4. **Tests manuels** pour chaque phase (checklist ci-dessus)

---

## COMMANDES POUR DÉMARRER

```bash
# 1. Créer le projet
npm create tauri-app@latest 0lith-desktop -- --template svelte-ts
cd 0lith-desktop

# 2. Installer plugins Tauri 2
npm install @tauri-apps/plugin-shell @tauri-apps/api

# 3. Setup Python backend
mkdir py-backend
cp /chemin/vers/olith_memory_init.py py-backend/
cd py-backend
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install mem0ai qdrant-client watchdog requests ollama
cd ..

# 4. Installer dépendances frontend
npm install -D tailwindcss @tailwindcss/vite
npm install bits-ui lucide-svelte

# 5. Lancer en dev
npm run tauri dev
```

---

## NOTES IMPORTANTES

- **Commencer par Phase 0** — le ping-pong IPC. Tout le reste en dépend.
- **Ne pas optimiser prématurément** — faire marcher d'abord, optimiser ensuite.
- **Chaque phase est testable indépendamment** — valider avant de passer à la suite.
- **En cas de doute sur Tauri 2** → consulter https://v2.tauri.app, pas les vieux tutos.
- **Aerolith sera lent** — c'est voulu. L'UX doit le gérer (indicateur de progression, pas de freeze).
- **Le fichier `olith_memory_init.py` est fourni** — ne pas le réécrire, l'importer.
