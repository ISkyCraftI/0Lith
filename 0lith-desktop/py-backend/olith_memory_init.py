#!/usr/bin/env python3
"""
0Lith V1 — Memory Initialization & Agent Identity System
=========================================================
Ce script initialise la mémoire partagée de tous les agents 0Lith.
Chaque agent reçoit son identité, ses capacités, et ses relations.

Stack : Mem0 + Qdrant (vecteurs) + Kuzu (graphe) + qwen3-embedding:0.6b

Usage:
    python olith_memory_init.py              # Init complète
    python olith_memory_init.py --test       # Test de récupération mémoire
    python olith_memory_init.py --reset      # Reset + re-init
    python olith_memory_init.py --status     # Vérifie l'état des services
"""

import sys
import json
import time
import argparse
import requests
from pathlib import Path
from datetime import datetime

# ============================================================================
# CONFIGURATION
# ============================================================================

OLLAMA_URL = "http://localhost:11434"
# Embedded Qdrant — path resolved relative to this script (no Docker required)
QDRANT_DATA_PATH: Path = Path(__file__).parent / "qdrant_data"
# Legacy Docker URL — kept for backward compat in callers that import QDRANT_URL
QDRANT_URL = "http://localhost:6333"
PYROLITH_URL = "http://localhost:11435"  # Docker DeepHat

# Mem0 config — Qwen3-Embedding + Qdrant + Kuzu
MEM0_CONFIG = {
    "llm": {
        "provider": "ollama",
        "config": {
            "model": "qwen3:1.7b",             # Hodolith — extraction rapide
            "ollama_base_url": OLLAMA_URL,
            "temperature": 0.1,                 # Déterministe pour extraction mémoire
        }
    },
    "embedder": {
        "provider": "ollama",
        "config": {
            "model": "qwen3-embedding:0.6b",    # #1 mondial MTEB, code-aware
            "ollama_base_url": OLLAMA_URL,
        }
    },
    "vector_store": {
        "provider": "qdrant",
        "config": {
            # Embedded mode — no Docker, data persisted in py-backend/qdrant_data/
            "path": str(QDRANT_DATA_PATH),
            "collection_name": "olith_memories",
            "embedding_model_dims": 1024,       # Qwen3-Embedding default
        }
    },
    "graph_store": {
        "provider": "kuzu",
        "config": {
            "url": "./olith_graph_db",          # Base locale embarquée
        }
    },
    "version": "v1.1",
}


# ============================================================================
# AGENT DEFINITIONS — Qui est qui dans 0Lith
# ============================================================================

AGENTS = {
    "hodolith": {
        "model": "qwen3:1.7b",
        "role": "Dispatcher",
        "color": "🟡",
        "description": (
            "Hodolith est le Dispatcher du système 0Lith. "
            "C'est le premier agent contacté par l'utilisateur. "
            "Son rôle est d'analyser chaque requête entrante et de la router "
            "vers l'agent spécialisé approprié. Il est rapide et léger (1.7B params). "
            "Il ne traite jamais directement les requêtes complexes — il délègue."
        ),
        "capabilities": [
            "Analyse d'intention et classification de requêtes",
            "Routage intelligent vers Monolith, Aerolith, Pyrolith, ou Cryolith",
            "Réponses rapides pour les questions simples",
            "Gestion de la file d'attente des tâches multi-agents",
        ],
        "routes_to": ["monolith", "aerolith", "pyrolith", "cryolith"],
        "location": "local",
    },

    "monolith": {
        "model": "qwen3:14b",
        "role": "Orchestrateur",
        "color": "⬛",
        "description": (
            "Monolith est l'Orchestrateur principal d'0Lith, basé sur Qwen3-14B. "
            "C'est le cerveau stratégique du système. Il gère le raisonnement complexe, "
            "la planification de missions, la synthèse d'informations provenant de "
            "plusieurs agents, et la prise de décision finale. "
            "Il utilise le mode /think pour le raisonnement profond (Chain-of-Thought). "
            "Monolith coordonne les sessions de sparring entre Pyrolith et Cryolith."
        ),
        "capabilities": [
            "Raisonnement complexe et multi-étapes (/think mode)",
            "Planification de missions de pentest et d'audit",
            "Synthèse et corrélation d'informations multi-sources",
            "Coordination des sessions de sparring Pyrolith vs Cryolith",
            "Rédaction de rapports d'analyse et recommandations",
            "Prise de décision stratégique en cybersécurité",
        ],
        "routes_to": ["aerolith", "pyrolith", "cryolith"],
        "location": "local",
    },

    "aerolith": {
        "model": "qwen3-coder:30b",
        "role": "Codeur",
        "color": "⚪",
        "description": (
            "Aerolith est le Codeur d'0Lith, basé sur Qwen3-Coder-30B. "
            "C'est le spécialiste du développement logiciel et de l'écriture de code. "
            "Il génère des scripts, outils, exploits personnalisés, automatisations, "
            "et analyseurs. Il comprend Python, Bash, PowerShell, C, JavaScript, "
            "et les langages de configuration (YAML, JSON, HCL). "
            "Aerolith est aussi capable de lire et d'auditer du code source."
        ),
        "capabilities": [
            "Génération de code (Python, Bash, PowerShell, C, JS)",
            "Écriture de scripts d'automatisation et d'outils pentest",
            "Audit de code source et détection de vulnérabilités",
            "Création d'exploits personnalisés sur demande de Monolith",
            "Refactoring et optimisation de code existant",
            "Génération de configurations (Docker, YAML, Terraform)",
        ],
        "routes_to": [],
        "location": "local",
    },

    "cryolith": {
        "model": "hf.co/fdtn-ai/Foundation-Sec-8B-Q4_K_M-GGUF:latest",
        "role": "Analyste Défensif (Blue Team)",
        "color": "🔵",
        "description": (
            "Cryolith est l'Analyste Défensif d'0Lith, basé sur Foundation-Sec-8B "
            "(Cisco). C'est le spécialiste de la cybersécurité défensive (Blue Team). "
            "Il analyse les CVE, évalue les risques, propose des mitigations, "
            "détecte les anomalies, et rédige des règles de détection (YARA, Sigma, Snort). "
            "Pendant les sessions de sparring, Cryolith défend contre les attaques "
            "de Pyrolith et apprend de chaque confrontation."
        ),
        "capabilities": [
            "Analyse de CVE et évaluation CVSS",
            "Proposition de mitigations et correctifs",
            "Rédaction de règles de détection (YARA, Sigma, Snort, Suricata)",
            "Analyse de logs et détection d'anomalies",
            "Hardening de systèmes et configurations sécurisées",
            "Défense active pendant les sessions de sparring vs Pyrolith",
            "Threat intelligence et analyse de TTPs (MITRE ATT&CK)",
        ],
        "routes_to": [],
        "location": "local",
    },

    "pyrolith": {
        "model": "deephat/DeepHat-V1-7B:latest",
        "role": "Agent Offensif (Red Team)",
        "color": "🔴",
        "description": (
            "Pyrolith est l'Agent Offensif d'0Lith, basé sur DeepHat-V1-7B. "
            "Il est isolé dans un conteneur Docker pour des raisons de sécurité. "
            "C'est le spécialiste du pentest, de l'exploitation de vulnérabilités, "
            "et de la simulation d'attaques. Il connaît les techniques offensives, "
            "les outils (Metasploit, Nmap, Burp, Cobalt Strike, etc.), et les TTPs "
            "des groupes APT. Pendant les sessions de sparring, Pyrolith attaque "
            "et Cryolith défend."
        ),
        "capabilities": [
            "Simulation d'attaques et pentest",
            "Exploitation de CVE et création d'exploits",
            "Reconnaissance et énumération de cibles",
            "Techniques de post-exploitation et mouvement latéral",
            "Social engineering et phishing (simulation)",
            "Attaque active pendant les sessions de sparring vs Cryolith",
            "Connaissance des outils offensifs (Metasploit, Nmap, Burp, etc.)",
        ],
        "routes_to": [],
        "location": "docker",
        "docker_url": PYROLITH_URL,
    },
}

# Relations inter-agents pour le graphe Kuzu
AGENT_RELATIONS = [
    ("hodolith",  "ROUTES_TO",    "monolith",  "Requêtes complexes, stratégie, coordination"),
    ("hodolith",  "ROUTES_TO",    "aerolith",  "Requêtes de code, scripts, outils"),
    ("hodolith",  "ROUTES_TO",    "pyrolith",  "Requêtes offensives, pentest, exploits"),
    ("hodolith",  "ROUTES_TO",    "cryolith",  "Requêtes défensives, CVE, détection"),
    ("monolith",  "COORDINATES",  "pyrolith",  "Lance et supervise les attaques sparring"),
    ("monolith",  "COORDINATES",  "cryolith",  "Lance et supervise les défenses sparring"),
    ("monolith",  "DELEGATES_TO", "aerolith",  "Demande l'écriture de code/outils"),
    ("pyrolith",  "SPARS_WITH",   "cryolith",  "Sessions de sparring Red vs Blue"),
    ("cryolith",  "DEFENDS_AGAINST", "pyrolith", "Contre les attaques de Pyrolith"),
    ("aerolith",  "SUPPORTS",     "pyrolith",  "Fournit des exploits/scripts custom"),
    ("aerolith",  "SUPPORTS",     "cryolith",  "Fournit des outils de défense/détection"),
]


# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def check_service(name: str, url: str, timeout: int = 3) -> bool:
    """Vérifie si un service HTTP est accessible."""
    try:
        r = requests.get(url, timeout=timeout)
        return r.status_code == 200
    except requests.exceptions.ConnectionError:
        return False
    except Exception:
        return False


def check_qdrant_embedded(data_path: Path = None) -> bool:
    """Vérifie si le Qdrant embarqué est accessible (crée le dossier si nécessaire)."""
    if data_path is None:
        data_path = QDRANT_DATA_PATH
    try:
        data_path.mkdir(parents=True, exist_ok=True)
        from qdrant_client import QdrantClient
        client = QdrantClient(path=str(data_path))
        client.get_collections()
        client.close()
        return True
    except Exception:
        return False


def migrate_from_docker_qdrant(data_path: Path = None) -> int:
    """
    Migre les vecteurs depuis Docker Qdrant (localhost:6333) vers le mode embarqué.

    Tente une connexion au Qdrant Docker. Si la collection olith_memories existe
    et contient des points, ils sont copiés vers le client embarqué.

    Returns:
        Nombre de points migrés (0 si Docker indisponible ou collection vide).
    """
    if data_path is None:
        data_path = QDRANT_DATA_PATH
    try:
        from qdrant_client import QdrantClient
        from qdrant_client.models import VectorParams, Distance, PointStruct

        # Connexion au Qdrant Docker (timeout court — pas bloquant)
        docker_client = QdrantClient(host="localhost", port=6333, timeout=3)
        collections = [c.name for c in docker_client.get_collections().collections]

        if "olith_memories" not in collections:
            docker_client.close()
            return 0

        info = docker_client.get_collection("olith_memories")
        if info.points_count == 0:
            docker_client.close()
            return 0

        # Initialiser le client embarqué et créer la collection si absente
        data_path.mkdir(parents=True, exist_ok=True)
        embedded_client = QdrantClient(path=str(data_path))
        embedded_cols = [c.name for c in embedded_client.get_collections().collections]

        if "olith_memories" not in embedded_cols:
            embedded_client.create_collection(
                "olith_memories",
                vectors_config=VectorParams(size=1024, distance=Distance.COSINE),
            )

        # Copie de tous les points par pages de 100
        migrated = 0
        offset = None
        while True:
            results, next_offset = docker_client.scroll(
                "olith_memories",
                limit=100,
                offset=offset,
                with_vectors=True,
                with_payload=True,
            )
            if results:
                points = [
                    PointStruct(id=p.id, vector=p.vector, payload=p.payload)
                    for p in results
                ]
                embedded_client.upsert("olith_memories", points=points)
                migrated += len(points)
            if next_offset is None:
                break
            offset = next_offset

        embedded_client.close()
        docker_client.close()
        return migrated
    except Exception:
        return 0


def _maybe_migrate():
    """Lance la migration Docker→embarqué si le dossier embarqué est absent ou vide."""
    if QDRANT_DATA_PATH.exists() and any(QDRANT_DATA_PATH.iterdir()):
        return  # Données embarquées déjà présentes
    migrated = migrate_from_docker_qdrant()
    if migrated > 0:
        print_ok(f"Migration Docker → embarqué : {migrated} vecteurs copiés")
    else:
        print_info("Qdrant embarqué vide — sera initialisé par Mem0 au premier usage")


def check_ollama_model(model: str) -> bool:
    """Vérifie si un modèle Ollama est disponible localement."""
    try:
        r = requests.get(f"{OLLAMA_URL}/api/tags", timeout=5)
        if r.status_code == 200:
            models = [m["name"] for m in r.json().get("models", [])]
            # Vérification flexible (avec ou sans :latest)
            return any(model in m or m.startswith(model) for m in models)
    except Exception:
        pass
    return False


def print_header(text: str):
    width = 70
    print(f"\n{'='*width}")
    print(f"  {text}")
    print(f"{'='*width}")


def print_ok(text: str):
    print(f"  ✅ {text}")


def print_warn(text: str):
    print(f"  ⚠️  {text}")


def print_fail(text: str):
    print(f"  ❌ {text}")


def print_info(text: str):
    print(f"  ℹ️  {text}")


# ============================================================================
# STATUS CHECK
# ============================================================================

def check_status() -> dict:
    """Vérifie l'état de tous les services et modèles."""
    print_header("0Lith V1 — Vérification des Services")

    status = {}

    # 1. Ollama
    ollama_ok = check_service("Ollama", OLLAMA_URL)
    status["ollama"] = ollama_ok
    if ollama_ok:
        print_ok(f"Ollama actif ({OLLAMA_URL})")
    else:
        print_fail(f"Ollama inaccessible ({OLLAMA_URL})")
        print_info("Lance Ollama : ollama serve")

    # 2. Qdrant embarqué (mode embedded — no Docker)
    qdrant_ok = check_qdrant_embedded()
    status["qdrant"] = qdrant_ok
    if qdrant_ok:
        print_ok(f"Qdrant embarqué prêt ({QDRANT_DATA_PATH})")
    else:
        print_fail(f"Qdrant embarqué inaccessible ({QDRANT_DATA_PATH})")
        print_info("pip install qdrant-client")

    # 3. Modèles Ollama
    print()
    required_models = {
        "qwen3:1.7b":              "Hodolith (Dispatcher)",
        "qwen3:14b":               "Monolith (Orchestrateur)",
        "qwen3-embedding:0.6b":    "Embeddings (Mémoire)",
    }
    optional_models = {
        "qwen3-coder:30b":         "Aerolith (Codeur) — VRAM: ~18 Go, swap dynamique",
        "Foundation-Sec-8B":       "Cryolith (Blue Team) — custom import",
    }

    for model, desc in required_models.items():
        found = check_ollama_model(model) if ollama_ok else False
        status[model] = found
        if found:
            print_ok(f"Modèle {model} — {desc}")
        else:
            print_fail(f"Modèle {model} manquant — {desc}")
            print_info(f"  ollama pull {model}")

    for model, desc in optional_models.items():
        found = check_ollama_model(model) if ollama_ok else False
        status[model] = found
        if found:
            print_ok(f"Modèle {model} — {desc}")
        else:
            print_warn(f"Modèle {model} absent — {desc}")

    # 4. Docker Pyrolith
    pyrolith_ok = check_service("Pyrolith", f"{PYROLITH_URL}/v1/models")
    status["pyrolith_docker"] = pyrolith_ok
    if pyrolith_ok:
        print_ok(f"Pyrolith Docker actif ({PYROLITH_URL})")
    else:
        print_warn(f"Pyrolith Docker inactif ({PYROLITH_URL})")
        print_info("C'est normal si le conteneur n'est pas lancé.")

    # 5. Mem0
    try:
        import mem0  # noqa: F401
        print_ok("Bibliothèque mem0ai installée")
        status["mem0"] = True
    except ImportError:
        print_fail("mem0ai non installé")
        print_info("pip install mem0ai")
        status["mem0"] = False

    # 6. Kuzu
    try:
        import kuzu  # noqa: F401
        print_ok("Bibliothèque kuzu installée")
        status["kuzu"] = True
    except ImportError:
        print_warn("kuzu non installé (graphe mémoire indisponible)")
        print_info('pip install kuzu  # ou pip install "mem0ai[graph]"')
        status["kuzu"] = False

    return status


# ============================================================================
# MEMORY INITIALIZATION
# ============================================================================

def init_memory(use_graph: bool = True):
    """Initialise Mem0 avec la config 0Lith."""
    from mem0 import Memory

    # Migration Docker → embarqué si le dossier n'existe pas encore
    _maybe_migrate()

    config = MEM0_CONFIG.copy()

    # Si Kuzu n'est pas dispo, on fonctionne sans graphe
    if not use_graph:
        config.pop("graph_store", None)
        print_warn("Mode sans graphe (Kuzu indisponible)")

    print_info("Initialisation de Mem0...")
    memory = Memory.from_config(config_dict=config)
    print_ok("Mem0 initialisé")
    return memory


def register_agent_identities(memory, verbose: bool = True):
    """Enregistre l'identité de chaque agent dans la mémoire partagée."""
    print_header("Enregistrement des Identités des Agents")

    timestamp = datetime.now().isoformat()

    for agent_id, info in AGENTS.items():
        if verbose:
            print(f"\n  {info['color']} {agent_id.upper()} — {info['role']}")
            print(f"     Modèle: {info['model']}")

        # 1. Identité principale
        identity_text = (
            f"Mon nom est {agent_id.capitalize()}. {info['description']}"
        )
        memory.add(
            identity_text,
            user_id=agent_id,
            metadata={
                "user_id": agent_id,
                "type": "identity",
                "priority": "critical",
                "created": timestamp,
                "model": info["model"],
                "role": info["role"],
            }
        )
        if verbose:
            print_ok("Identité enregistrée")

        # 2. Capacités
        caps_text = (
            f"En tant que {agent_id.capitalize()} ({info['role']}), "
            f"mes capacités sont : {'; '.join(info['capabilities'])}."
        )
        memory.add(
            caps_text,
            user_id=agent_id,
            metadata={
                "user_id": agent_id,
                "type": "capabilities",
                "priority": "high",
                "created": timestamp,
            }
        )
        if verbose:
            print_ok("Capacités enregistrées")

        # 3. Connaissance du système 0Lith global
        team_text = (
            f"Je fais partie du système 0Lith V1, un framework multi-agent "
            f"de cybersécurité composé de 5 agents : "
            f"Hodolith (Dispatcher, qwen3:1.7b), "
            f"Monolith (Orchestrateur, qwen3:14b), "
            f"Aerolith (Codeur, qwen3-coder:30b), "
            f"Cryolith (Blue Team, Foundation-Sec-8B), "
            f"Pyrolith (Red Team, DeepHat-7B en Docker). "
            f"Notre mémoire est partagée via Mem0 + Qdrant + Kuzu. "
            f"Notre embedding model est qwen3-embedding:0.6b."
        )
        memory.add(
            team_text,
            user_id=agent_id,
            metadata={
                "user_id": agent_id,
                "type": "system_knowledge",
                "priority": "high",
                "created": timestamp,
            }
        )
        if verbose:
            print_ok("Connaissance système enregistrée")

    # Petit délai pour laisser Qdrant indexer
    time.sleep(1)
    print(f"\n  📊 {len(AGENTS)} agents enregistrés avec 3 mémoires chacun "
          f"= {len(AGENTS) * 3} mémoires totales")


def register_agent_relations(memory, verbose: bool = True):
    """Enregistre les relations entre agents (pour le graphe Kuzu)."""
    print_header("Enregistrement des Relations Inter-Agents")

    timestamp = datetime.now().isoformat()

    for source, relation, target, context in AGENT_RELATIONS:
        relation_text = (
            f"{source.capitalize()} {relation.replace('_', ' ').lower()} "
            f"{target.capitalize()} : {context}."
        )
        memory.add(
            relation_text,
            user_id=source,
            metadata={
                "user_id": source,
                "type": "relation",
                "relation_type": relation,
                "source_agent": source,
                "target_agent": target,
                "created": timestamp,
            }
        )
        if verbose:
            source_color = AGENTS[source]["color"]
            target_color = AGENTS[target]["color"]
            print(f"  {source_color} {source} —[{relation}]→ "
                  f"{target_color} {target}")

    time.sleep(1)
    print(f"\n  📊 {len(AGENT_RELATIONS)} relations enregistrées")


def register_sparring_protocol(memory, verbose: bool = True):
    """Enregistre le protocole de sparring Red vs Blue."""
    print_header("Enregistrement du Protocole de Sparring")

    timestamp = datetime.now().isoformat()

    sparring_protocol = (
        "Le sparring est un exercice où Pyrolith (Red Team) attaque et "
        "Cryolith (Blue Team) défend. Monolith supervise et évalue. "
        "Protocole : 1) Monolith définit le scénario (CVE, type d'attaque, cible). "
        "2) Pyrolith planifie et exécute l'attaque. "
        "3) Cryolith détecte, analyse et propose des défenses. "
        "4) Monolith évalue les performances des deux côtés. "
        "5) Les résultats sont mémorisés pour améliorer les futures sessions. "
        "Aerolith intervient si du code custom est nécessaire."
    )

    # Enregistré pour les 3 agents impliqués
    for agent in ["monolith", "pyrolith", "cryolith"]:
        memory.add(
            sparring_protocol,
            user_id=agent,
            metadata={
                "user_id": agent,
                "type": "protocol",
                "protocol_name": "sparring",
                "priority": "high",
                "created": timestamp,
            }
        )

    if verbose:
        print_ok("Protocole sparring enregistré pour Monolith, Pyrolith, Cryolith")

    # Quelques CVE exemples pour amorcer la mémoire
    sample_cves = [
        {
            "text": (
                "CVE-2024-3094 : Backdoor dans xz-utils (liblzma) versions 5.6.0 et 5.6.1. "
                "Vecteur : supply chain attack via un mainteneur compromis. "
                "Impact : exécution de code à distance via sshd. Score CVSS : 10.0 (Critique). "
                "Mitigation : downgrader vers xz-utils 5.4.x, vérifier les signatures."
            ),
            "cve_id": "CVE-2024-3094",
            "severity": "critical",
            "cvss": 10.0,
        },
        {
            "text": (
                "CVE-2024-6387 : RegreSSHion — Race condition dans OpenSSH sshd. "
                "Versions affectées : 8.5p1 à 9.7p1. "
                "Impact : exécution de code à distance en root (unauthenticated). "
                "Score CVSS : 8.1 (Élevé). "
                "Mitigation : mettre à jour OpenSSH vers 9.8p1+, limiter MaxStartups."
            ),
            "cve_id": "CVE-2024-6387",
            "severity": "high",
            "cvss": 8.1,
        },
    ]

    for cve in sample_cves:
        for agent in ["pyrolith", "cryolith"]:
            memory.add(
                cve["text"],
                user_id=agent,
                metadata={
                    "user_id": agent,
                    "type": "cve",
                    "cve_id": cve["cve_id"],
                    "severity": cve["severity"],
                    "cvss": cve["cvss"],
                    "created": timestamp,
                }
            )

    if verbose:
        print_ok(f"{len(sample_cves)} CVE exemples enregistrés pour Pyrolith & Cryolith")

# ============================================================================
# TESTS
# ============================================================================

def test_memory_retrieval(memory):
    """Teste la récupération mémoire pour chaque agent."""
    print_header("Test de Récupération Mémoire")

    test_queries = [
        ("hodolith",  "Quel est mon nom et mon rôle ?"),
        ("monolith",  "Quels agents je coordonne ?"),
        ("aerolith",  "Quels langages de programmation je maîtrise ?"),
        ("cryolith",  "Comment défendre contre CVE-2024-3094 ?"),
        ("pyrolith",  "Comment exploiter une race condition dans OpenSSH ?"),
        ("monolith",  "Comment fonctionne le sparring ?"),
        ("hodolith",  "Vers quel agent router une demande de pentest ?"),
    ]

    passed = 0
    failed = 0

    for agent_id, query in test_queries:
        color = AGENTS[agent_id]["color"]
        print(f"\n  {color} {agent_id.upper()} ← \"{query}\"")

        try:
            results = memory.search(query, user_id=agent_id, filters={"user_id": agent_id}, limit=3)

            # Mem0 retourne soit une liste soit un dict avec "results"
            if isinstance(results, dict):
                memories = results.get("results", [])
            elif isinstance(results, list):
                memories = results
            else:
                memories = []

            if memories:
                for i, mem in enumerate(memories):
                    # Extraire le texte selon la structure retournée
                    text = ""
                    if isinstance(mem, dict):
                        text = mem.get("memory", mem.get("text", str(mem)))
                    else:
                        text = str(mem)

                    # Tronquer pour affichage
                    display = text[:120] + "..." if len(text) > 120 else text
                    score = ""
                    if isinstance(mem, dict) and "score" in mem:
                        score = f" (score: {mem['score']:.3f})"
                    print(f"     [{i+1}]{score} {display}")
                passed += 1
                print_ok("Mémoires trouvées")
            else:
                failed += 1
                print_fail("Aucune mémoire trouvée")

        except Exception as e:
            failed += 1
            print_fail(f"Erreur : {e}")

    print(f"\n  📊 Résultats : {passed}/{passed+failed} tests réussis")
    if failed > 0:
        print_warn(f"{failed} test(s) échoué(s)")
    else:
        print_ok("Tous les tests passent !")

    return failed == 0


def test_cross_agent_knowledge(memory):
    """Teste la connaissance croisée entre agents."""
    print_header("Test de Connaissance Croisée")

    # Chaque agent devrait savoir qui sont les autres
    for agent_id in AGENTS:
        color = AGENTS[agent_id]["color"]
        results = memory.search(
            "Quels sont les agents du système OLith ?",  # On garde la question
            user_id=agent_id,                            # On passe l'ID
            filters={"user_id": agent_id},               # LE FIX EST ICI (indispensable pour Kuzu)
            limit=1
        )

        if isinstance(results, dict):
            memories = results.get("results", [])
        elif isinstance(results, list):
            memories = results
        else:
            memories = []

        if memories:
            print(f"  {color} {agent_id.upper()} connaît le système 0Lith ✅")
        else:
            print(f"  {color} {agent_id.upper()} ne connaît PAS le système ❌")


# ============================================================================
# RESET
# ============================================================================

def reset_memory(memory):
    """Supprime toutes les mémoires existantes."""
    print_header("Reset de la Mémoire 0Lith")
    print_warn("Suppression de toutes les mémoires...")

    for agent_id in AGENTS:
        try:
            memory.delete_all(agent_id=agent_id)
            print_ok(f"Mémoires de {agent_id} supprimées")
        except Exception as e:
            print_warn(f"Erreur pour {agent_id}: {e}")

    # Laisser le temps à Qdrant de traiter
    time.sleep(2)
    print_ok("Reset terminé")


# ============================================================================
# MAIN
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="0Lith V1 — Initialisation de la Mémoire Agent"
    )
    parser.add_argument("--test", action="store_true",
                        help="Tester la récupération mémoire")
    parser.add_argument("--reset", action="store_true",
                        help="Reset + ré-initialisation complète")
    parser.add_argument("--status", action="store_true",
                        help="Vérifier l'état des services")
    parser.add_argument("--no-graph", action="store_true",
                        help="Fonctionner sans Kuzu (vecteurs seulement)")
    args = parser.parse_args()

    print(r"""
     █████╗ ██╗     ██╗████████╗██╗  ██╗
    ██╔══██╗██║     ██║╚══██╔══╝██║  ██║
    ██║  ██║██║     ██║   ██║   ███████║
    ██║  ██║██║     ██║   ██║   ██╔══██║
    ╚█████╔╝███████╗██║   ██║   ██║  ██║
     ╚════╝ ╚══════╝╚═╝   ╚═╝   ╚═╝  ╚═╝
     Memory System v1.1 — Multi-Agent Cybersecurity
    """)

    # --- Status check ---
    if args.status:
        check_status()
        return

    # --- Vérifications préalables ---
    status = check_status()

    # Vérifier les services critiques
    if not status.get("ollama"):
        print_fail("\nOllama est requis. Lance-le et réessaie.")
        sys.exit(1)
    # Qdrant embarqué — créé automatiquement, pas de Docker requis
    if not status.get("qdrant"):
        print_warn("\nQdrant embarqué inaccessible — vérifie l'installation de qdrant-client.")
        print_info("pip install qdrant-client")

    # Vérifier si Kuzu est disponible
    use_graph = status.get("kuzu", False) and not args.no_graph
    if not use_graph:
        print_warn("\nMode sans graphe activé (Kuzu non disponible)")
        print_info("La mémoire fonctionnera en mode vectoriel uniquement.")
        print_info("Les relations entre agents ne seront pas stockées dans un graphe.")

    # --- Initialisation ---
    try:
        memory = init_memory(use_graph=use_graph)
    except Exception as e:
        print_fail(f"\nErreur d'initialisation Mem0 : {e}")
        print_info("Vérifie que qdrant-client est installé (pip install qdrant-client) et qu'Ollama tourne.")
        sys.exit(1)

    # --- Reset si demandé ---
    if args.reset:
        reset_memory(memory)

    # --- Test seul ---
    if args.test and not args.reset:
        test_memory_retrieval(memory)
        test_cross_agent_knowledge(memory)
        return

    # --- Initialisation complète ---
    print_header("Initialisation Complète de la Mémoire 0Lith")

    t0 = time.time()

    register_agent_identities(memory)
    register_agent_relations(memory)
    register_sparring_protocol(memory)

    elapsed = time.time() - t0
    print_header(f"Initialisation Terminée en {elapsed:.1f}s")

    # Test automatique après init
    print_info("Lancement des tests de vérification...")
    time.sleep(2)  # Laisser Qdrant indexer

    all_passed = test_memory_retrieval(memory)
    test_cross_agent_knowledge(memory)

    if all_passed:
        print_header("🎯 0Lith V1 Memory System — OPÉRATIONNEL")
    else:
        print_header("⚠️  Certains tests ont échoué — vérifiez la configuration")

    print(f"""
    Prochaines étapes :
    ─────────────────────────────────────────────────────
    1. Teste la mémoire :  python olith_memory_init.py --test
    2. Reset si besoin :   python olith_memory_init.py --reset
    3. Status services :   python olith_memory_init.py --status

    Dans ton code agent, récupère les mémoires avec :
        from mem0 import Memory
        memory = Memory.from_config(config_dict=MEM0_CONFIG)
        memories = memory.search("query", agent_id="monolith")
    """)


if __name__ == "__main__":
    main()
