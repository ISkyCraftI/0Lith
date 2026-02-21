# OLith — Recherche Approfondie : Embeddings & Systèmes de Mémoire Agent
## État de l'art Février 2026

---

## 1. Snowflake Arctic Embed 2 vs Qwen3-Embedding : Le Verdict

### Snowflake Arctic Embed 2 (décembre 2024)

| Propriété | Valeur |
|-----------|--------|
| **Paramètres** | 113M (medium) / 303M (large) |
| **Dimensions** | 768 (medium) / 1024 (large), MRL → 256 |
| **MTEB Retrieval** | 0.554 (medium) / bon (large) |
| **Langues** | Multilingue (EN + FR/ES/IT/DE focus) |
| **Contexte** | 8192 tokens |
| **VRAM** | ~250 Mo (medium) / ~700 Mo (large) |
| **Licence** | Apache 2.0 |
| **Date** | Décembre 2024 |
| **Sur Ollama** | `ollama pull snowflake-arctic-embed2` (568 Mo) |

**Points forts** : Ultra-léger, très rapide (>100 docs/sec sur A10), excellente compressibilité MRL (3-4x avec <3% dégradation), bon pour l'anglais.

**Limites** : Date de 2024, pas de support instructions custom, pas de code retrieval optimisé, couverture multilingue limitée (5-6 langues focus), pas de compréhension de langages de programmation.

---

### Qwen3-Embedding (mai 2025) — **Le nouveau #1 mondial**

| Propriété | 0.6B | 4B | 8B |
|-----------|------|-----|-----|
| **MTEB Multilingual** | Bon | Très bon | **70.58 (#1 mondial)** |
| **Dimensions** | 32-1024 (MRL flexible) | 32-1024 | 32-1024 |
| **Langues** | 100+ langues + code | 100+ | 100+ |
| **Contexte** | 32 768 tokens | 32 768 | 32 768 |
| **VRAM estimé** | ~400 Mo (FP16) / ~350 Mo (Q4) | ~2.5 Go (Q4) | ~5 Go (Q4) |
| **Licence** | Apache 2.0 | Apache 2.0 | Apache 2.0 |
| **Instructions** | ✅ Oui (+1-5% perf) | ✅ Oui | ✅ Oui |
| **Code retrieval** | ✅ Natif | ✅ Natif | ✅ Natif |
| **Sur Ollama** | `ollama pull qwen3-embedding:0.6b` | `qwen3-embedding:4b` | `qwen3-embedding` |

**Points forts** :
- **#1 mondial MTEB Multilingual** (score 70.58, juin 2025)
- **Instruction-aware** : tu peux personnaliser le comportement par tâche (ex: `Instruct: Given a cybersecurity vulnerability description, retrieve related exploits`)
- **Dimensions flexibles** : de 32 à 1024 via MRL — tu choisis le ratio qualité/stockage
- **Code retrieval natif** : comprend Python, Bash, exploits — crucial pour OLith
- **100+ langues** : FR/EN bilingue natif + langages de programmation
- **Contexte 32K** : 4× plus long que Arctic Embed 2 — peut embedder des rapports entiers
- **Famille Qwen3** : même base que tes agents Monolith/Hodolith, synergie maximale

---

### Comparaison directe pour OLith

| Critère | Arctic Embed 2 | Qwen3-Embedding 0.6B | **Recommandé** |
|---------|---------------|----------------------|----------------|
| Qualité embeddings | Bonne | Supérieure (+15-20%) | 🏆 Qwen3 |
| VRAM | ~250 Mo | ~350-400 Mo | ≈ Égal |
| Vitesse | Très rapide | Rapide | Arctic légèrement |
| Code/exploits | ❌ Non optimisé | ✅ Natif | 🏆 Qwen3 |
| Instructions custom | ❌ Non | ✅ Oui (+5%) | 🏆 Qwen3 |
| Contexte max | 8K tokens | 32K tokens | 🏆 Qwen3 |
| Multilingual FR/EN | Limité | Excellent | 🏆 Qwen3 |
| Synergie OLith | Aucune | Même famille Qwen3 | 🏆 Qwen3 |
| Maturité | 14 mois | 9 mois | Arctic |
| Date | Déc 2024 | Mai 2025 | Qwen3 plus récent |

**🎯 Verdict : `qwen3-embedding:0.6b` est le choix optimal pour OLith.**

Raisons :
1. Même famille que tes LLM agents → cohérence sémantique
2. Code retrieval natif → indispensable pour exploits CVE, scripts pentest
3. Instructions custom → tu peux dire "retrieve cybersecurity memories" et gagner 5%
4. 32K contexte → peut embedder un rapport Nmap complet en un seul vecteur
5. VRAM raisonnable (~350 Mo) → laisse de la place pour tes agents

**Commande :**
```bash
ollama pull qwen3-embedding:0.6b
```

**Configuration Mem0 mise à jour :**
```python
"embedder": {
    "provider": "ollama",
    "config": {
        "model": "qwen3-embedding:0.6b",
        "ollama_base_url": "http://localhost:11434"
    }
}
```

> ⚠️ **Note importante** : Qwen3-Embedding utilise le **dernier token** comme `<|endoftext|>`. Ollama gère ça automatiquement, mais si tu utilises l'API directement, il faut l'ajouter manuellement. Les dimensions par défaut sont 1024, mais tu peux les réduire via MRL.

---

## 2. Les Étudiants Chinois qui ont Révolutionné la Mémoire Agent

Tu avais raison — il y a eu deux percées majeures par des équipes chinoises en 2025.

### 2A. MemOS — "Memory Operating System" (Shanghai Jiao Tong + Zhejiang University)

**Paper** : arXiv:2507.03724 (juillet 2025)
**Équipe** : Zhiyu Li, Shichao Song, Chenyang Xi et ~30 chercheurs
**Institutions** : MemTensor (Shanghai), Shanghai Jiao Tong University, Renmin University, China Telecom Research
**GitHub** : github.com/MemTensor/MemOS (4.4K+ ⭐)
**Licence** : MIT (open-source)

#### Le concept révolutionnaire : la mémoire comme ressource OS

MemOS traite la **mémoire comme un citoyen de première classe** — exactement comme un OS gère CPU et stockage. Là où Mem0 fait du CRUD basique (add/search/update), MemOS introduit un système complet de gouvernance mémoire.

#### Architecture 3 couches (inspirée d'un vrai OS)

```
┌─────────────────────────────────────────┐
│  Interface Layer (API Cortex)           │  ← Requêtes mémoire read/write
├─────────────────────────────────────────┤
│  Operation Layer (MemScheduler)         │  ← Décide quoi activer/compresser/oublier
│  • Next-Scene Prediction               │     (comme le prefrontal cortex)
│  • Memory Fusion & Migration            │
├─────────────────────────────────────────┤
│  Infrastructure Layer (Storage)         │  ← Hot/Warm/Cold tiers
│  • RAM-like (fréquent)                  │
│  • SSD-like (sessions)                  │
│  • Deep storage (archives)              │
└─────────────────────────────────────────┘
```

#### MemCube — L'abstraction unifiée

Le cœur de MemOS est le **MemCube** : une unité mémoire standardisée qui encapsule :

1. **Plaintext Memory** : connaissances textuelles (CVE, rapports, faits)
2. **Activation Memory** : KV-cache pour accélérer l'inférence (réutilisation de contexte)
3. **Parameter Memory** : poids LoRA, adaptations de modèle
4. **Tool Memory** (v2.0) : trajectoires d'appels d'outils pour améliorer le planning

Chaque MemCube contient :
- **Metadata** : timestamp, origine, type sémantique, version
- **Governance** : contrôle d'accès, TTL (durée de vie), priorité, tags de conformité
- **Behavioral metrics** : fréquence d'utilisation, pertinence, decay

#### Benchmarks : MemOS écrase tout

| Benchmark | Métrique | MemOS vs Mem0 | MemOS vs OpenAI Memory |
|-----------|----------|---------------|------------------------|
| LOCOMO (overall) | F1/BLEU | **+38.9%** | **+159% temporal reasoning** |
| Latence | p95 | Plus rapide | **-94% via KV-cache injection** |
| LoCoMo temporal | Temporal reasoning | Dominant | **+159%** |

MemOS surpasse : MIRIX, Mem0, Zep, Memobase, MemU, et Supermemory.

#### Versions et évolution

| Version | Date | Nouveautés |
|---------|------|------------|
| v1.0 Stellar (星河) | Juillet 2025 | Premier release, MemCube, plaintext + KV-cache |
| v1.0.0 MemCube | Août 2025 | Word game demo, LongMemEval, NebulaGraph |
| v2.0 Stardust (星尘) | Décembre 2025 | Knowledge base, multi-modal, Tool Memory, Redis Streams, MCP |

#### Compatibilité MemOS

- **LLM** : HuggingFace, OpenAI, **Ollama** ✅
- **Plateforme** : Linux (Windows/Mac en dev)
- **Installation** : `pip install MemoryOS`
- **Déploiement** : Docker + Redis Streams (v2.0) ou lightweight

---

### 2B. MemoryOS (EMNLP 2025 — Beijing)

**Paper** : "Memory OS of AI Agent" — EMNLP 2025 (Suzhou, Chine)
**Auteurs** : Jiazheng Kang, Mingming Ji, Zhe Zhao, Ting Bai
**Résultats** : +48.36% F1, +46.18% BLEU-1 sur LoCoMo

Architecture hiérarchique à 3 niveaux :
- **Short-term** : dialogue courant (FIFO)
- **Mid-term** : chaînes de dialogue récentes (segmented page organization)
- **Long-term** : mémoire personnelle persistante

> Note : C'est un paper académique (pas d'implémentation open-source aussi mature que MemOS).

---

### 2C. Memory-R1 (août 2025 — Munich/Cambridge/Hong Kong)

**Paper** : arXiv:2508.19828
**Concept** : Utiliser le **Reinforcement Learning** (PPO/GRPO) pour apprendre à gérer la mémoire

Deux agents spécialisés :
1. **Memory Manager** : apprend quand ADD, UPDATE, DELETE, NOOP
2. **Answer Agent** : filtre et raisonne sur les mémoires récupérées (Memory Distillation)

**Résultats vs Mem0** : +57.3% F1, +41.5% BLEU-1, +33.8% LLM-as-Judge (sur Qwen-2.5-7B)

**Pourquoi c'est important** : Mem0 utilise des heuristiques codées en dur pour décider quoi stocker. Memory-R1 prouve qu'un agent peut **apprendre** à mieux gérer sa mémoire via RL — les mises à jour ne fragmentent plus la mémoire.

---

### 2D. Mem-α (septembre 2025) — La suite logique

**Paper** : arXiv:2509.25911
**Concept** : Même approche RL que Memory-R1, mais pour des **architectures mémoire complexes** (multi-composants : épisodique, sémantique, procédurale)

Critique de Memory-R1 : structures mémoire trop simples (listes de faits). Mem-α entraîne l'agent à naviguer des systèmes mémoire sophistiqués avec différents types de mémoire.

---

## 3. Impact sur la Stack OLith : Recommandation Révisée

### Constat : Mem0 reste le meilleur choix pragmatique pour OLith V1

Malgré les avancées de MemOS et Memory-R1, voici pourquoi **Mem0 + Qdrant + Kuzu reste optimal** pour toi maintenant :

| Critère | Mem0 | MemOS | Memory-R1 |
|---------|------|-------|-----------|
| **Maturité production** | ✅ v1.0+, battle-tested | ⚠️ v2.0 récent | ❌ Paper seulement |
| **Ollama natif** | ✅ Supporté | ✅ Supporté | ❌ Non |
| **Qdrant intégré** | ✅ Natif | ❌ Pas directement | ❌ Non |
| **Kuzu intégré** | ✅ Natif (v0.1.117) | ❌ NebulaGraph | ❌ Non |
| **Graph memory** | ✅ Oui (Mem0g) | ✅ Oui (hiérarchique) | ❌ Non |
| **Multi-agent scoping** | ✅ agent_id/user_id | ⚠️ Multi-tenant v2.0 | ❌ Non |
| **Complexité install** | `pip install mem0ai` | Docker + Redis + config | Requiert RL training |
| **VRAM overhead** | Minimal (~350 Mo avec embeddings) | Variable (MemReader-4B = 2.5 Go+) | Requiert fine-tune 7B |
| **Cas d'usage** | Agents locaux, simple-robuste | Enterprise, multi-session | Recherche |

### Feuille de route recommandée

**Phase 1 (maintenant) — Stack pragmatique** :
```
Mem0 + qwen3-embedding:0.6b + Qdrant + Kuzu
```
- Installe et valide la mémoire inter-agents
- Tes agents se souviennent de leur nom, de CVE, de sessions de sparring
- Coût VRAM total mémoire : ~350 Mo

**Phase 2 (quand OLith V1 fonctionne) — Évaluer MemOS** :
- MemOS v2.0 apporte Tool Memory (trajectoires d'outils) → pertinent pour sparring
- KV-cache injection → -94% latence → sparring plus rapide
- Mais nécessite migration et test de compatibilité Ollama

**Phase 3 (futur) — Memory-R1 / Mem-α** :
- Quand/si des modèles pré-entraînés RL pour mémoire sont disponibles sur Ollama
- L'idée d'un agent qui *apprend* à gérer sa mémoire est le futur, mais pas encore plug-and-play

---

## 4. Configuration Finale Recommandée pour OLith

### Embeddings

```bash
# Remplace nomic-embed-text par qwen3-embedding
ollama pull qwen3-embedding:0.6b

# Vérifie que ça fonctionne
curl http://localhost:11434/api/embed \
  -d '{"model": "qwen3-embedding:0.6b", "input": "CVE-2024-1234 buffer overflow"}'
```


### Configuration Mem0 mise à jour

```python
from mem0 import Memory

config = {
    "llm": {
        "provider": "ollama",
        "config": {
            "model": "qwen3:1.7b",  # Hodolith pour extraction rapide
            "ollama_base_url": "http://localhost:11434"
        }
    },
    "embedder": {
        "provider": "ollama",
        "config": {
            "model": "qwen3-embedding:0.6b",  # ← NOUVEAU : #1 mondial
            "ollama_base_url": "http://localhost:11434"
        }
    },
    "vector_store": {
        "provider": "qdrant",
        "config": {
            "host": "localhost",
            "port": 6333,
            "collection_name": "olith_memories",
            "embedding_model_dims": 1024,  # ← CHANGÉ : 1024 par défaut Qwen3
            "distance": "cosine"
        }
    },
    "graph_store": {
        "provider": "kuzu",
        "config": {
            "url": "./olith_graph"
        }
    },
    "version": "v1.1"
}

memory = Memory.from_config(config_dict=config)
```

### Premier test : faire que tes agents se souviennent

```python
# Étape 1 : Apprendre les identités des agents
memory.add(
    "Je suis Hodolith, le dispatcher du système OLith. Mon rôle est de router les requêtes.",
    agent_id="hodolith",
    metadata={"type": "identity", "priority": "critical"}
)

memory.add(
    "Je suis Monolith, l'orchestrateur principal d'OLith basé sur Qwen3-14B.",
    agent_id="monolith",
    metadata={"type": "identity", "priority": "critical"}
)

memory.add(
    "Je suis Pyrolith, l'agent offensif d'OLith spécialisé en pentest et red team.",
    agent_id="pyrolith",
    metadata={"type": "identity", "priority": "critical"}
)

memory.add(
    "Je suis Cryolith, l'analyste défensif d'OLith spécialisé en blue team et CVE.",
    agent_id="cryolith",
    metadata={"type": "identity", "priority": "critical"}
)

# Étape 2 : Vérifier la récupération
result = memory.search("Quel est mon nom et mon rôle ?", agent_id="pyrolith")
print(result)
# → Devrait retourner l'identité de Pyrolith
```

### Budget VRAM révisé avec qwen3-embedding:0.6b

| Composant | VRAM |
|-----------|------|
| qwen3-embedding:0.6b (embeddings) | ~350 Mo |
| Qdrant (Docker, CPU) | 0 Mo VRAM |
| Kuzu (embedded, CPU) | 0 Mo VRAM |
| Mem0 (Python, CPU) | 0 Mo VRAM |
| **Total mémoire stack** | **~350 Mo** |
| Agent actif (ex: Qwen3-14B) | ~10-11 Go |
| **Total avec 1 agent** | **~11 Go / 16 Go VRAM** |

---

## 5. Résumé des Découvertes

### Sur les embeddings :
- **Snowflake Arctic Embed 2** était un bon choix en 2024, mais il est dépassé en 2025
- **Qwen3-Embedding** est le #1 mondial MTEB Multilingual (score 70.58)
- La version 0.6B suffit pour OLith : qualité supérieure, code-aware, instruction-aware, 32K contexte
- Même famille que tes agents → cohérence sémantique maximale

### Sur les systèmes de mémoire :
- **MemOS** (Shanghai Jiao Tong) a révolutionné le concept de mémoire agent avec MemCubes (+159% vs OpenAI, +38.9% vs baselines)
- **MemoryOS** (EMNLP 2025, Beijing) a proposé une hiérarchie short/mid/long-term (+48% F1)
- **Memory-R1** a prouvé que le RL peut apprendre à gérer la mémoire (+57% vs Mem0)
- **Mem-α** étend ça aux architectures mémoire complexes

### Pour OLith V1 :
- **Mem0 + Qdrant + Kuzu reste le choix pragmatique** : mature, Ollama-natif, zéro infrastructure
- **Migrer vers `qwen3-embedding:0.6b`** au lieu de Snowflake ou nomic-embed-text
- **MemOS est l'avenir** mais nécessite plus de maturité pour remplacer Mem0 sur un setup local
- Les dimensions d'embedding passent de 768 (nomic) à **1024** (qwen3) → recréer la collection Qdrant

---

*Document généré le 7 février 2026 — Recherche OLith*
