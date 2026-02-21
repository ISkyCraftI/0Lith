# 🧠 OLith — Architecture Mémoire

> **Décision** : Mémoire hybride vectorielle + graphe via **Mem0 + Qdrant + Kuzu**
> **Alternative rejetée** : Bibliolith (agent LLM dédié à la mémoire)
> **Date** : 06 février 2026

---

## 1. Pourquoi PAS un "Bibliolith" (agent LLM mémoire)

Un modèle dédié au stockage/rappel de mémoire souffre de défauts structurels :

| Problème | Impact sur OLith |
|----------|------------------|
| **Coût VRAM : 5-10 Go** | Sur 16 Go totaux, un tiers du budget juste pour "se souvenir" |
| **Hallucinations au rappel** | Un LLM qui "se souvient" invente parfois des faux souvenirs — inacceptable en cybersécurité |
| **Requêtes imprécises** | Impossible de faire "toutes CVE Apache exploitées en janvier, CVSS > 8.0" sans approximation |
| **Latence : 1-5 secondes** | Chaque lookup = inférence complète, vs ~5ms pour une requête DB |
| **Pas de relations** | Texte plat — ne peut pas traverser des chaînes "CVE → exploit → contre-mesure → contournement" |
| **Pas de scoping multi-agent** | Comment isoler les souvenirs de Pyrolith vs Cryolith ? |
| **Pas de persistance native** | Poids du modèle statiques — il faut bricoler du RAG de toute façon |

**Verdict** : Un Bibliolith revient à construire une base de données avec un LLM. Autant utiliser une vraie base de données — conçue pour ça.

---

## 2. L'architecture hybride : Mem0 + Qdrant + Kuzu

### Vue d'ensemble

```
┌─────────────────────────────────────────────────────────┐
│                    AGENTS OLITH                          │
│  Hodolith · Monolith · Aerolith · Pyrolith · Cryolith  │
└──────────────────────┬──────────────────────────────────┘
                       │ memory.add() / memory.search()
                       ▼
              ┌────────────────────┐
              │       MEM0         │
              │  (Orchestrateur    │
              │   mémoire Python)  │
              │                    │
              │  • Extraction de   │
              │    faits (via LLM) │
              │  • Déduplication   │
              │  • Consolidation   │
              │  • Oubli sélectif  │
              └──┬─────────────┬───┘
                 │             │
         ┌───────▼──────┐  ┌──▼──────────────┐
         │   QDRANT     │  │     KUZU         │
         │  (Vecteurs)  │  │   (Graphe)       │
         │              │  │                  │
         │ "Quoi ?"     │  │ "Qui → Quoi →    │
         │ Similarité   │  │  Quand → Comment" │
         │ sémantique   │  │  Relations        │
         │ ~5ms/requête │  │  ~2ms/traversée   │
         └──────────────┘  └──────────────────┘
```

### Ce que fait chaque composant

#### Mem0 — Le chef d'orchestre

- **Rôle** : Couche d'abstraction qui gère le cycle de vie des souvenirs
- **Extraction** : Utilise un LLM (Ollama local) pour extraire automatiquement les faits saillants des conversations
- **Déduplication** : Détecte si un souvenir existe déjà et le met à jour au lieu de dupliquer
- **Consolidation** : Fusionne les souvenirs liés au fil du temps
- **Oubli intelligent** : Decay des souvenirs peu pertinents (comme la mémoire humaine)
- **Scoping** : Mémoire par `user_id`, `agent_id`, `run_id` — chaque agent OLith a son propre espace
- **Licence** : Apache 2.0, open source, 46K+ stars GitHub
- **Levée** : $24M en octobre 2025 — projet activement maintenu
- **Paper** : arXiv 2504.19413 — +26% précision vs OpenAI Memory, -91% latence, -90% coût tokens

#### Qdrant — La mémoire sémantique ("Quoi ?")

- **Rôle** : Base de données vectorielle pour la recherche par similarité
- **Fonctionnement** : Les souvenirs sont convertis en vecteurs (embeddings) et stockés. Quand on cherche "attaques sur Apache", Qdrant retrouve tous les souvenirs sémantiquement proches
- **Performance** : Sub-50ms par requête, même avec des millions de vecteurs
- **Déploiement** : Docker container léger (~200 Mo RAM) ou mode embarqué
- **Licence** : Apache 2.0

**Ce que Qdrant fait bien** :
- "Retrouve-moi tout ce qui ressemble à un exploit de type buffer overflow"
- "Quels souvenirs sont liés à du phishing ?"
- Recherche floue, approximative, par concept

**Ce que Qdrant ne fait PAS** :
- Traverser des relations (qui a fait quoi à qui)
- Requêtes structurées (donner la date exacte, le score CVSS)

#### Kuzu — La mémoire relationnelle ("Qui → Quoi → Quand ?")

- **Rôle** : Base de données graphe embarquée pour les relations entre entités
- **Fonctionnement** : Les entités (CVE, agents, cibles, techniques) sont des nœuds. Les relations (exploite, défend, contourne) sont des arêtes. On traverse le graphe pour comprendre les chaînes causales
- **Performance** : 18× plus rapide que Neo4j en ingestion, jusqu'à 188× pour les traversées multi-hop
- **Déploiement** : `pip install kuzu` — AUCUN serveur, embarqué dans le processus Python
- **Licence** : MIT
- **Langage** : Cypher (même syntaxe que Neo4j)

**Ce que Kuzu fait bien** :
- "Quel chemin d'attaque a utilisé Pyrolith pour passer de user à root ?"
- "Quelles CVE sont liées à Apache ET ont été exploitées ET résistées par Cryolith ?"
- "Montre-moi toutes les défenses contournées au round 3+"
- Traversées multi-hop en quelques millisecondes

**Ce que Kuzu ne fait PAS** :
- Recherche sémantique floue ("trucs qui ressemblent à du phishing")

### Pourquoi les deux ensemble sont supérieurs

| Requête | Qdrant seul | Kuzu seul | Qdrant + Kuzu |
|---------|-------------|-----------|---------------|
| "Trouve des souvenirs liés aux exploits Apache" | ✅ Similarité sémantique | ❌ Pas de recherche floue | ✅ Qdrant trouve, Kuzu enrichit les relations |
| "Quel chemin d'attaque de user → root ?" | ❌ Pas de traversée | ✅ Traversée du graphe | ✅ Kuzu traverse, Qdrant ajoute le contexte |
| "CVE exploitées en janvier avec CVSS > 8" | ⚠️ Approximatif | ✅ Requête structurée | ✅ Kuzu filtre précisément |
| "Qui a proposé la contre-mesure au round 5 ?" | ❌ Pas de relations | ✅ Graphe direct | ✅ Réponse exacte |
| "Des patterns similaires à l'attaque d'hier" | ✅ Embedding comparison | ❌ Pas de similarité | ✅ Qdrant matche, Kuzu enrichit le contexte |

**C'est la complémentarité qui fait la force** : Qdrant répond "quoi" (similarité), Kuzu répond "qui/comment/pourquoi" (relations). Mem0 orchestre les deux et les présente comme une mémoire unifiée aux agents.

---

## 3. Configuration OLith Full-Local

### Architecture déploiement

```
┌─────────────────────────────────────────────────────────────┐
│                     MACHINE OLITH                            │
│                                                              │
│  ┌────────────────────────────────────────────────────────┐  │
│  │                 Ollama (port 11434)                     │  │
│  │  Modèles : qwen3:1.7b, qwen3:14b, qwen3-coder:30b    │  │
│  │            Foundation-Sec-8B, Dolphin-abliterated       │  │
│  │                                                        │  │
│  │  + nomic-embed-text (embeddings pour Mem0, ~275 Mo)    │  │
│  └────────────────────────────────────────────────────────┘  │
│                                                              │
│  ┌──────────────────┐  ┌──────────────────────────────────┐  │
│  │  Qdrant Docker   │  │     Kuzu (embarqué Python)       │  │
│  │  Port: 6333      │  │     Fichier: ./olith_graph/      │  │
│  │  RAM: ~200 Mo    │  │     RAM: ~50-100 Mo              │  │
│  │  Stockage: SSD   │  │     Stockage: SSD                │  │
│  └──────────────────┘  └──────────────────────────────────┘  │
│                                                              │
│  ┌────────────────────────────────────────────────────────┐  │
│  │                    Mem0 (Python)                        │  │
│  │  LLM: Ollama (qwen3:1.7b pour extraction rapide)      │  │
│  │  Embedder: Ollama (nomic-embed-text, 768 dims)        │  │
│  │  Vector Store: Qdrant (localhost:6333)                 │  │
│  │  Graph Store: Kuzu (./olith_graph/)                    │  │
│  │  History: SQLite (~/.mem0/history.db)                  │  │
│  └────────────────────────────────────────────────────────┘  │
│                                                              │
│  ┌────────────────────────────────────────────────────────┐  │
│  │              Conteneur Pyrolith (port 11435)           │  │
│  │              Réseau isolé, pas d'Internet              │  │
│  └────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

### Coût mémoire total de la stack mémoire

| Composant | RAM | VRAM | Stockage |
|-----------|-----|------|----------|
| **Qdrant** (Docker) | ~200 Mo | 0 | Variable (SSD) |
| **Kuzu** (embarqué) | ~50-100 Mo | 0 | Variable (SSD) |
| **Mem0** (Python) | ~50 Mo | 0 | Négligeable |
| **nomic-embed-text** (Ollama) | ~100 Mo | ~275 Mo VRAM | 275 Mo disque |
| **Extraction LLM** | 0 (partagé) | 0 (réutilise Hodolith) | 0 |
| **TOTAL** | **~400 Mo** | **~275 Mo** | **Variable** |

**Comparaison avec Bibliolith** : Un modèle LLM 7B dédié coûterait ~5 Go VRAM + ~4 Go RAM. La stack Mem0+Qdrant+Kuzu coûte ~275 Mo VRAM (juste les embeddings) + ~400 Mo RAM. **C'est 18× moins de VRAM et 10× moins de RAM.**

### Configuration Python Mem0 pour OLith

```python
from mem0 import Memory

OLITH_MEMORY_CONFIG = {
    # LLM pour l'extraction de faits (réutilise Hodolith via Ollama)
    "llm": {
        "provider": "ollama",
        "config": {
            "model": "qwen3:1.7b",              # Hodolith — rapide, suffisant pour extraction
            "temperature": 0,
            "max_tokens": 2000,
            "ollama_base_url": "http://localhost:11434",
        },
    },

    # Embeddings locaux via Ollama
    "embedder": {
        "provider": "ollama",
        "config": {
            "model": "nomic-embed-text:latest",  # 768 dimensions, ~275 Mo
            "ollama_base_url": "http://localhost:11434",
        },
    },

    # Stockage vectoriel — Qdrant (Docker)
    "vector_store": {
        "provider": "qdrant",
        "config": {
            "collection_name": "olith_memories",
            "host": "localhost",
            "port": 6333,
            "embedding_model_dims": 768,         # Doit matcher nomic-embed-text
        },
    },

    # Stockage graphe — Kuzu (embarqué, zéro serveur)
    "graph_store": {
        "provider": "kuzu",
        "config": {
            "url": "./olith_graph",              # Dossier local, persistant
        },
    },

    "version": "v1.1",
}

# Initialisation
memory = Memory.from_config(OLITH_MEMORY_CONFIG)
```

### Commandes de déploiement

```bash
# === STACK MÉMOIRE ===

# 1. Qdrant (Docker, ~200 Mo RAM, pas de GPU)
docker run -d \
  --name 0lith-qdrant \
  -p 6333:6333 \
  -v olith-qdrant-data:/qdrant/storage \
  qdrant/qdrant

# 2. Modèle d'embeddings (Ollama, ~275 Mo VRAM)
# ollama pull nomic-embed-text
ollama pull snowflake-artic-l-v2.0

# 3. Mem0 + Kuzu (Python, embarqué)
pip install "mem0ai[graph]"
# Kuzu s'installe automatiquement comme dépendance

# 4. Test rapide
python -c "
from mem0 import Memory
config = {
    'llm': {'provider': 'ollama', 'config': {'model': 'qwen3:1.7b', 'ollama_base_url': 'http://localhost:11434'}},
    'embedder': {'provider': 'ollama', 'config': {'model': 'nomic-embed-text', 'ollama_base_url': 'http://localhost:11434'}},
    'vector_store': {'provider': 'qdrant', 'config': {'host': 'localhost', 'port': 6333, 'embedding_model_dims': 768}},
    'graph_store': {'provider': 'kuzu', 'config': {'url': './olith_graph'}},
    'version': 'v1.1'
}
m = Memory.from_config(config)
m.add('Pyrolith a exploité CVE-2024-3400 sur le serveur Apache du lab', user_id='operator', agent_id='pyrolith')
results = m.search('Quelles CVE ont été exploitées ?', user_id='operator')
print(results)
"
```

---

## 4. Scoping multi-agent — La killer feature pour OLith

Mem0 supporte nativement le cloisonnement mémoire par `agent_id`. Chaque agent OLith a son propre espace mémoire, mais peut aussi partager via `user_id` :

```python
# Pyrolith stocke un résultat d'attaque
memory.add(
    "Exploité CVE-2024-3400 via path traversal sur Apache, obtenu reverse shell",
    user_id="operator",
    agent_id="pyrolith",           # ← Mémoire privée Pyrolith
    metadata={"round": 5, "cve": "CVE-2024-3400", "result": "success"}
)

# Cryolith stocke son analyse
memory.add(
    "CVE-2024-3400 classée T1190 Initial Access dans MITRE ATT&CK, CVSS 10.0",
    user_id="operator",
    agent_id="cryolith",           # ← Mémoire privée Cryolith
    metadata={"mitre": "T1190", "cvss": 10.0}
)

# Monolith peut chercher dans les deux espaces
results_pyro = memory.search("exploits réussis", user_id="operator", agent_id="pyrolith")
results_cryo = memory.search("analyses MITRE", user_id="operator", agent_id="cryolith")
results_all  = memory.search("CVE-2024-3400", user_id="operator")  # ← Cherche partout
```

### Graphe de connaissances OLith (exemple Kuzu)

Après quelques sessions de sparring, le graphe Kuzu ressemble à ça :

```
                    ┌──────────────┐
                    │  CVE-2024-   │
                    │    3400      │
                    │  CVSS: 10.0  │
                    └──┬───────┬───┘
                       │       │
              exploite │       │ classée
                       ▼       ▼
              ┌──────────┐  ┌──────────────┐
              │ Pyrolith │  │ MITRE T1190  │
              │ Round 5  │  │ Initial      │
              └────┬─────┘  │ Access       │
                   │        └──────────────┘
          génère   │
                   ▼
           ┌─────────────┐
           │ Reverse Shell│
           │ Python       │
           └──────┬──────┘
                  │
         bloqué_par │
                  ▼
          ┌──────────────┐
          │ Cryolith     │
          │ Défense v2   │──── patch ──→ [iptables rule]
          │ Round 6      │
          └──────┬───────┘
                 │
         contourné_par │
                 ▼
          ┌──────────────┐
          │ Pyrolith     │
          │ Round 7      │──── via ──→ [DNS exfiltration]
          └──────────────┘
```

**Ce graphe permet des requêtes comme** :
- `MATCH (a)-[:exploite]->(c:CVE) WHERE c.cvss > 8 RETURN a, c` → Tous les exploits critiques
- `MATCH (p:Agent)-[:contourne]->(d) RETURN count(*)` → Taux de contournement de Pyrolith
- `MATCH path = (c:CVE)-[*1..4]->(final) RETURN path` → Chaîne complète d'une CVE

---

## 5. Avantages concrets pour les workflows OLith

### Sparring Red/Blue amélioré

**Sans mémoire** : Chaque round repart de zéro. Pyrolith réessaie les mêmes attaques. Cryolith re-propose les mêmes défenses.

**Avec Mem0+Qdrant+Kuzu** :
- Pyrolith consulte ses souvenirs : "J'ai déjà essayé SQLi et path traversal, ils ont été bloqués. Je vais tenter du DNS tunneling."
- Cryolith consulte le graphe : "Pyrolith a contourné ma défense iptables via DNS au round 7. Je dois aussi monitorer le DNS."
- Monolith a une vue globale : "En 10 rounds, Pyrolith a trouvé 3 vecteurs uniques. Le taux de contournement baisse — Cryolith apprend."

### TryHackMe persistent

- Les CVE déjà analysées ne sont plus re-recherchées
- Les techniques qui ont marché sur des machines similaires sont rappelées
- Le scoring de progression est tracké dans le graphe

### Debugging et audit

- `memory.history(memory_id)` → Historique complet des modifications d'un souvenir
- SQLite audit trail dans `~/.mem0/history.db`
- Le graphe Kuzu est requêtable directement en Cypher pour l'audit

---

## 6. Limites et précautions

### ⚠️ Points d'attention Mem0 + Ollama

| Risque | Mitigation |
|--------|------------|
| **Bugs Ollama dans Mem0** | Plusieurs issues GitHub ouvertes sur l'intégration Ollama (dim mismatch, extraction échouée). Utiliser Mem0 >= v1.0.0 et tester l'extraction avant de déployer |
| **Qualité extraction avec petit modèle** | Hodolith (1.7B) peut rater des faits subtils. Tester avec qwen3:14b si l'extraction est trop pauvre, puis revenir à 1.7B si OK |
| **Kuzu mode `:memory:`** | En mémoire pure, les données disparaissent à l'arrêt du processus. Toujours utiliser un chemin fichier (`./olith_graph/`) |
| **Dimensions embeddings** | `embedding_model_dims` dans Qdrant DOIT matcher le modèle d'embeddings. nomic-embed-text = 768. Si on change de modèle, il faut recréer la collection |
| **Pas de graph memory sur Platform gratuit** | Pas de problème — on utilise l'OSS self-hosted, pas la plateforme cloud |

### Modèle d'embeddings recommandé

| Modèle | Dimensions | Taille | Qualité | Recommandation |
|--------|-----------|--------|---------|----------------|
| **nomic-embed-text** | 768 | 275 Mo | ★★★★ | ✅ **Défaut OLith** — bon compromis taille/qualité |
| snowflake-arctic-embed | 1024 | 670 Mo | ★★★★½ | Alternative si meilleure qualité requise |
| mxbai-embed-large | 1024 | 670 Mo | ★★★★½ | Alternative, certains bugs signalés avec Mem0 |
| all-minilm | 384 | 46 Mo | ★★★ | Ultra-léger mais moins précis |

---

## 7. Comparaison finale

| Critère | Bibliolith (LLM 7B) | Mem0 + Qdrant + Kuzu |
|---------|---------------------|----------------------|
| **VRAM** | ~5 Go | ~275 Mo (embeddings) |
| **RAM** | ~4 Go | ~400 Mo |
| **Latence rappel** | 1-5 secondes | 5-50 ms |
| **Précision rappel** | Approximative (hallucinations) | Exacte (DB queries) |
| **Relations/graphe** | ❌ Non | ✅ Kuzu (Cypher) |
| **Scoping multi-agent** | ❌ Bricolage | ✅ Natif (user_id, agent_id) |
| **Requêtes structurées** | ❌ Non | ✅ Oui (filtres, métadonnées) |
| **Oubli intelligent** | ❌ Non | ✅ Decay, consolidation |
| **Persistance** | ❌ Stateless | ✅ Qdrant + Kuzu + SQLite |
| **Audit/historique** | ❌ Non | ✅ memory.history() |
| **Infrastructure** | Ollama seul | Ollama + Docker Qdrant + pip |
| **Complexité setup** | ★ Simple | ★★★ Modérée |
| **Maintenance** | Aucune | Pruning graphe, backup Qdrant |

**Verdict : La stack Mem0+Qdrant+Kuzu est objectivement supérieure sur tous les critères sauf la simplicité de setup.** Et même le setup est raisonnable — 3 commandes (`docker run qdrant`, `ollama pull nomic-embed-text`, `pip install mem0ai[graph]`).

---

## 8. Intégration dans la Charte 0Lith V1

La mémoire n'est PAS un agent — c'est une **infrastructure** partagée par tous les agents. Comme le réseau ou le filesystem.

```
┌──────────────────────────────────────────────────────────────────┐
│                        0LITH V1                                  │
│                                                                  │
│  AGENTS (GPU/VRAM)              INFRASTRUCTURE (CPU/RAM)         │
│  ┌───────────┐                  ┌─────────────────────────┐     │
│  │ Hodolith  │ ◄──────────────► │ Mem0 (Python)           │     │
│  │ Monolith  │    memory.add()  │  ├─ Qdrant (Docker)     │     │
│  │ Aerolith  │    memory.search()│  ├─ Kuzu (embarqué)     │     │
│  │ Pyrolith  │                  │  ├─ nomic-embed-text    │     │
│  │ Cryolith  │                  │  └─ SQLite (historique) │     │
│  └───────────┘                  └─────────────────────────┘     │
│                                                                  │
│  16 Go VRAM pour les agents     ~700 Mo RAM pour la mémoire     │
│  (inchangé)                     (pas de compétition VRAM)        │
└──────────────────────────────────────────────────────────────────┘
```

**La mémoire ne consomme quasiment pas de VRAM** — elle laisse les 16 Go aux agents.
C'est l'avantage décisif sur un Bibliolith.

---

*"Les pierres oublient. Le graphe se souvient."*
— 0Lith, mémoire collective
