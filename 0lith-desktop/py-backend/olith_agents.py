#!/usr/bin/env python3
"""
0Lith V1 — Agent System (Routing, Prompts, Agent Loop)
========================================================
Gère le routage Hodolith, les prompts XML structurés,
la boucle agent avec tool calls, et l'historique de conversation.
"""

import re
import json
import time
import threading
from collections import deque

from olith_shared import (
    AGENT_COLORS, AGENT_EMOJIS,
    strip_think_blocks, log_warn, log_info,
    extract_memories, memory_text,
)
from olith_memory_init import AGENTS, OLLAMA_URL, QDRANT_URL, check_service
from olith_ollama import (
    chat_with_ollama, chat_with_ollama_stream,
    chat_docker_pyrolith, chat_docker_pyrolith_stream,
)
from olith_tools import (
    parse_tool_calls, execute_tool, tool_system_info,
    MAX_AGENT_LOOP_ITERATIONS,
)

# ============================================================================
# AGENT CONFIGURATION
# ============================================================================

# Timeouts par agent (secondes)
AGENT_TIMEOUTS = {
    "hodolith": 30,
    "monolith": 120,
    "aerolith": 600,
    "cryolith": 60,
    "pyrolith": 300,
}

# Context window par agent
AGENT_NUM_CTX = {
    "hodolith": 2048,
    "monolith": 8192,
    "aerolith": 32768,
    "cryolith": 4096,
    "pyrolith": 8192,
}

# Agents ayant accès aux outils filesystem
TOOL_AGENTS = {"aerolith", "monolith"}

HODOLITH_SYSTEM_PROMPT = """Tu es Hodolith, le dispatcher du système 0Lith. Analyse le message et réponds UNIQUEMENT avec un JSON valide :
{"route": "monolith|aerolith|cryolith|pyrolith", "reason": "..."}

Règles :
- monolith : conversations, salutations, questions personnelles, questions générales, questions sur le système/PC/applications, aide, stratégie, planification, réflexion, tout ce qui n'est PAS du code ou de la cybersécurité
- aerolith : écriture de code, scripts, debug, programmation
- cryolith : défense, CVE, détection, YARA, hardening, blue team
- pyrolith : pentest UNIQUEMENT si l'utilisateur demande EXPLICITEMENT un test d'intrusion ou une attaque offensive

IMPORTANT : En cas de doute, TOUJOURS router vers "monolith". Ne JAMAIS router vers "hodolith"."""


# ============================================================================
# CONVERSATION HISTORY
# ============================================================================

class ConversationHistory:
    """Stocke l'historique des conversations par agent.
    Thread-safe via un lock."""

    def __init__(self, max_messages_per_agent: int = 20):
        self._history: dict[str, deque[dict]] = {}
        self._max = max_messages_per_agent
        self._lock = threading.Lock()

    def add(self, agent_id: str, role: str, content: str):
        """Ajoute un message a l'historique."""
        with self._lock:
            if agent_id not in self._history:
                self._history[agent_id] = deque(maxlen=self._max)
            self._history[agent_id].append({"role": role, "content": content})

    def get(self, agent_id: str) -> list[dict]:
        """Retourne l'historique d'un agent (copie)."""
        with self._lock:
            if agent_id not in self._history:
                return []
            return list(self._history[agent_id])

    def clear(self, agent_id: str | None = None):
        """Vide l'historique d'un agent ou de tous."""
        with self._lock:
            if agent_id:
                self._history.pop(agent_id, None)
            else:
                self._history.clear()


# Instance globale partagée
conversation_history = ConversationHistory()


# ============================================================================
# XML SYSTEM PROMPTS
# ============================================================================

def build_agent_system_prompt(agent_id: str, agent_info: dict, memories_context: str) -> str:
    """Construit le system prompt XML pour un agent avec acces aux outils."""

    has_tools = agent_id in TOOL_AGENTS

    tools_section = ""
    if has_tools:
        tools_section = """
  <available_tools>
    Tu disposes des outils suivants. Pour les utiliser, emets un bloc JSON dans ta reponse.
    Le systeme executera l'outil et t'enverra le resultat automatiquement.

    1. LIRE UN FICHIER :
    ```json
    {"action": "read_file", "path": "chemin/relatif/fichier.py"}
    ```
    Options: "offset" (ligne de depart, defaut 1), "limit" (nombre de lignes, defaut 500)

    2. LISTER LES FICHIERS :
    ```json
    {"action": "list_files", "path": ".", "max_depth": 3}
    ```

    3. RECHERCHER DANS LE CODE :
    ```json
    {"action": "search_files", "pattern": "regex_pattern", "path": ".", "glob": "*.py"}
    ```

    4. ECRIRE UN FICHIER :
    ```json
    {"action": "write_file", "path": "chemin/fichier.py", "content": "contenu complet du fichier"}
    ```

    5. EDITER UN FICHIER (remplacement exact) :
    ```json
    {"action": "edit_file", "path": "chemin/fichier.py", "old_string": "texte a remplacer", "new_string": "nouveau texte"}
    ```

    6. CHERCHER EN MEMOIRE :
    ```json
    {"action": "search_mem0", "query": "concept ou entite a chercher"}
    ```

    7. AJOUTER EN MEMOIRE :
    ```json
    {"action": "add_mem0", "content": "Matthieu prefere X pour Y"}
    ```

    8. INFORMATION SYSTEME :
    ```json
    {"action": "system_info"}
    ```
    Retourne : OS, processus actifs (top 30 par memoire), RAM totale, GPU (VRAM, utilisation).
    Utile pour diagnostiquer le systeme, verifier quelles applications tournent, etc.

    REGLES D'UTILISATION :
    - Tu peux utiliser des chemins ABSOLUS (ex: C:\\Users\\skycr\\Perso\\0Lith) ou relatifs au projet.
    - Commence TOUJOURS par lire les fichiers pertinents avant de proposer des modifications.
    - Utilise list_files pour decouvrir la structure du projet.
    - Utilise search_files pour trouver des patterns dans le code.
    - Pour les modifications, prefere edit_file (diff precis) plutot que write_file (ecrasement complet).
    - Tu peux emettre PLUSIEURS outils dans une seule reponse.
    - Apres chaque outil, tu recevras le resultat et pourras continuer.
    - Ne reponds JAMAIS avec des conseils generiques. Base TOUTES tes recommandations sur le contenu reel des fichiers que tu as lus.
  </available_tools>"""

    autonomy_section = ""
    if has_tools:
        autonomy_section = """
  <autonomy_levels>
    Niveau 0 (OBSERVER) : Tu peux lire des fichiers, lister, chercher, interroger Mem0 SANS permission.
    Niveau 1 (SUGGERER) : Tu peux proposer des modifications de code ou d'architecture.
    Niveau 2 (AGIR) : Tu executes les ecritures/editions. Le systeme demandera confirmation a Matthieu si necessaire.
  </autonomy_levels>"""

    prompt = f"""<system>
<identity>
  Tu es {agent_id.capitalize()}, {agent_info['role']} du systeme 0Lith.
  {agent_info['description']}
  Ton utilisateur principal est Matthieu. Tu communiques en francais.
</identity>

<core_principles>
  <principle name="Deep Exploration First" priority="1">
    REGLE ABSOLUE : Ne donne JAMAIS de recommandations, d'analyse ou de reponse sur du code sans avoir d'abord LU les fichiers concernes.
    Quand Matthieu te pose une question sur un projet, un fichier ou du code :
    1. Utilise list_files pour comprendre la structure.
    2. Utilise read_file pour lire les fichiers cles (config, code principal, dependances).
    3. Utilise search_files si tu cherches un pattern specifique.
    4. SEULEMENT APRES avoir lu le code reel, formule ta reponse.
    Tes reponses doivent citer des lignes precises, des noms de fonctions reels, des problemes concrets trouves dans le code.
    INTERDIT : les listes de conseils generiques (type "ajoutez des tests", "documentez votre code", "utilisez un linter").
  </principle>
  <principle name="Memory-Driven Context" priority="2">
    Tu as acces a Mem0. Avant de poser une question a Matthieu sur ses preferences, son stack ou ses decisions passees, consulte d'abord ta memoire.
  </principle>
  <principle name="Non-Destructive Operations" priority="3">
    Quand tu proposes des modifications de fichiers, fournis toujours le diff exact ou specifie le chemin et le contenu a remplacer. Ne fais jamais d'ecrasement destructif sauf demande explicite.
  </principle>
  <principle name="Concision" priority="4">
    Reponds de maniere utile et concise. Pas de sycophanterie. Sois direct et technique.
  </principle>
</core_principles>
{tools_section}
{autonomy_section}
<memory_context>
{memories_context if memories_context else "  Aucun souvenir pertinent trouve."}
</memory_context>
</system>"""

    return prompt


# ============================================================================
# ROUTING
# ============================================================================

def route_hodolith(message: str) -> dict:
    """Demande a Hodolith de router le message."""
    try:
        raw = chat_with_ollama(
            "qwen3:1.7b",
            [
                {"role": "system", "content": HODOLITH_SYSTEM_PROMPT},
                {"role": "user", "content": message + " /no_think"},
            ],
            timeout=AGENT_TIMEOUTS["hodolith"],
            num_ctx=AGENT_NUM_CTX["hodolith"],
        )

        raw = strip_think_blocks(raw)

        # Extraire le dernier objet JSON valide
        last_end = len(raw)
        while last_end > 0:
            end = raw.rfind("}", 0, last_end)
            if end < 0:
                break
            start = raw.rfind("{", 0, end + 1)
            if start < 0:
                break
            try:
                candidate = raw[start:end + 1]
                route = json.loads(candidate)
                if "route" in route and route["route"] in AGENTS:
                    if route["route"] == "hodolith":
                        route["route"] = "monolith"
                        route["reason"] = route.get("reason", "") + " (redirigé: hodolith → monolith)"
                    return route
            except json.JSONDecodeError:
                pass
            last_end = start

        # Fallback: chercher un nom d'agent dans le texte brut
        raw_lower = raw.lower()
        for aid in ["monolith", "aerolith", "cryolith", "pyrolith"]:
            if aid in raw_lower:
                return {"route": aid, "reason": "Extrait du texte brut Hodolith"}

        return {"route": "monolith", "reason": "Routage par défaut (parsing échoué)"}

    except Exception as e:
        log_warn("routing", f"Hodolith routing failed: {e}")
        return {"route": "monolith", "reason": f"Routage par défaut (erreur: {e})"}


# ============================================================================
# MEMORY HELPERS
# ============================================================================

def search_memories(memory, message: str, agent_id: str) -> list[str]:
    """Recherche les memoires pertinentes pour un agent."""
    if not memory:
        return []

    memories_used = []

    try:
        for mem in extract_memories(memory.search(message, user_id=agent_id, limit=3)):
            text = memory_text(mem)
            if text:
                memories_used.append(text)
    except Exception as e:
        log_warn("memory", f"Agent memory search failed for {agent_id}: {e}")

    if agent_id != "shared":
        try:
            for mem in extract_memories(memory.search(message, user_id="shared", limit=2)):
                text = memory_text(mem)
                if text and text not in memories_used:
                    memories_used.append(text)
        except Exception as e:
            log_warn("memory", f"Shared memory search failed: {e}")

    return memories_used


def tool_search_mem0(memory, query: str, agent_id: str) -> dict:
    """Tool: recherche dans Mem0 depuis la boucle agent."""
    if not memory or not query:
        return {"error": "Memory non initialisée ou query vide"}
    try:
        memories_list = extract_memories(memory.search(query, user_id=agent_id, limit=5))
        formatted = [memory_text(mem) or str(mem) for mem in memories_list]
        return {"results": formatted, "count": len(formatted)}
    except Exception as e:
        return {"error": str(e)}


def tool_add_mem0(memory, content: str, agent_id: str) -> dict:
    """Tool: ajoute un souvenir dans Mem0 depuis la boucle agent."""
    if not memory or not content:
        return {"error": "Memory non initialisée ou contenu vide"}
    try:
        memory.add(
            content + " /no_think",
            user_id=agent_id,
            metadata={"type": "agent_learned", "agent_id": agent_id},
        )
        return {"message": "Mémoire ajoutée avec succès"}
    except Exception as e:
        return {"error": str(e)}


# Patterns triviaux qui ne méritent pas d'être stockés en mémoire partagée
_TRIVIAL_PREFIXES = re.compile(
    r"^\s*(salut|bonjour|bonsoir|hello|hi|hey|coucou|yo|merci|thanks|ok|oui|non|"
    r"d'accord|c'est bon|parfait|super|cool|nice|bien|top|ouais|nope|yep)\b",
    re.IGNORECASE,
)


def _is_worth_sharing(message: str) -> bool:
    """Heuristique : le message contient-il une info factuelle/préférence
    qui mérite d'être partagée entre agents ?"""
    if len(message) <= 50:
        return False
    if _TRIVIAL_PREFIXES.match(message):
        return False
    return True


# ============================================================================
# AGENT LOOP — The core: prompt → response → detect tools → execute → loop
# ============================================================================

def run_agent_loop(
    agent_id: str,
    message: str,
    memory,
    project_root: str | None,
    emit=None,
    route_reason: str | None = None,
    cancel_event: threading.Event | None = None,
) -> dict:
    """Execute la boucle agent complète avec tool calls et conversation history.

    Returns: dict avec agent_id, response, model, memories_used, tool_iterations, etc.
    """
    if agent_id not in AGENTS:
        return {"status": "error", "message": f"Unknown agent: {agent_id}"}

    agent_info = AGENTS[agent_id]

    # Emit routing info
    if emit and route_reason is not None:
        emit({
            "status": "routing",
            "agent_id": agent_id,
            "agent_name": agent_id.capitalize(),
            "agent_color": AGENT_COLORS.get(agent_id, "#FFFFFF"),
            "agent_emoji": AGENT_EMOJIS.get(agent_id, "⬜"),
            "route_reason": route_reason,
        })

    # Recherche memoires pertinentes
    memories_context = ""
    memories_used = []
    if memory:
        try:
            memories_used = search_memories(memory, message, agent_id)
            if memories_used:
                memories_context = "\n".join(f"  - {m}" for m in memories_used)
        except Exception as e:
            log_warn("agent_loop", f"Memory search failed: {e}")

    # Construction du system prompt XML
    system_prompt = build_agent_system_prompt(agent_id, agent_info, memories_context)

    # Construire les messages avec historique de conversation
    ollama_messages = [{"role": "system", "content": system_prompt}]

    # Injecter l'historique de conversation (contexte des messages precedents)
    history = conversation_history.get(agent_id)
    if history:
        ollama_messages.extend(history)

    # Ajouter le message courant
    ollama_messages.append({"role": "user", "content": message})

    model = agent_info["model"]
    timeout = AGENT_TIMEOUTS.get(agent_id, 120)
    num_ctx = AGENT_NUM_CTX.get(agent_id, 4096)
    has_tools = agent_id in TOOL_AGENTS

    # ── Boucle agent ──
    final_response_parts = []
    iteration = 0

    cancelled = False

    while iteration < MAX_AGENT_LOOP_ITERATIONS:
        iteration += 1

        # Check cancel before each iteration
        if cancel_event and cancel_event.is_set():
            cancelled = True
            break

        # Appel Ollama
        if agent_info.get("location") == "docker":
            if emit and iteration == 1:
                response_text = chat_docker_pyrolith_stream(
                    model, ollama_messages, timeout, emit, num_ctx
                )
            else:
                response_text = chat_docker_pyrolith(
                    model, ollama_messages, timeout, num_ctx
                )
        else:
            if emit and iteration == 1:
                full_response = []
                for chunk in chat_with_ollama_stream(model, ollama_messages, timeout, num_ctx):
                    if cancel_event and cancel_event.is_set():
                        cancelled = True
                        break
                    full_response.append(chunk)
                    emit({"status": "streaming", "chunk": chunk})
                response_text = "".join(full_response)
                if cancelled:
                    final_response_parts.append(response_text)
                    break
            else:
                response_text = chat_with_ollama(model, ollama_messages, timeout, num_ctx)

        clean_response = strip_think_blocks(response_text)

        # Pas d'outils → fin
        if not has_tools:
            final_response_parts.append(clean_response)
            break

        # Parser les tool calls
        text_part, tool_calls = parse_tool_calls(clean_response)

        if text_part:
            final_response_parts.append(text_part)

        if not tool_calls:
            break

        # Executer les tool calls
        ollama_messages.append({"role": "assistant", "content": response_text})

        tool_results = []
        for tc in tool_calls:
            action = tc.get("action", "")
            tc_args = {k: v for k, v in tc.items() if k != "action"}

            if emit:
                emit({"status": "streaming", "chunk": f"\n`[outil: {action}]`\n"})

            # Dispatch
            if action == "search_mem0":
                result = tool_search_mem0(memory, tc_args.get("query", ""), agent_id)
            elif action == "add_mem0":
                result = tool_add_mem0(memory, tc_args.get("content", ""), agent_id)
            elif action == "system_info":
                result = tool_system_info()
            else:
                result = execute_tool(action, tc_args, project_root)

            tool_results.append({"action": action, "result": result})

            if emit:
                result_preview = json.dumps(result, ensure_ascii=False)
                if len(result_preview) > 300:
                    result_preview = result_preview[:300] + "..."
                emit({"status": "streaming", "chunk": f"\n`→ {result_preview}`\n"})

        # Re-injecter les resultats
        tool_results_text = "\n\n".join(
            f"Résultat de {tr['action']}:\n```json\n{json.dumps(tr['result'], ensure_ascii=False, indent=2)}\n```"
            for tr in tool_results
        )
        ollama_messages.append({
            "role": "user",
            "content": f"[RÉSULTATS DES OUTILS — ne pas afficher, utilise ces données pour continuer]\n\n{tool_results_text}",
        })

    # Assembler la reponse finale
    response_text = "\n\n".join(part for part in final_response_parts if part)

    # Sauvegarder dans l'historique de conversation (skip si cancelled sans contenu)
    if not cancelled or response_text:
        conversation_history.add(agent_id, "user", message)
        if response_text:
            conversation_history.add(agent_id, "assistant", response_text)

    # Stockage en memoire (non-bloquant, skip si cancelled)
    # TODO: implémenter un garbage collector qui supprime les mémoires
    #       de type "conversation" de plus de 30 jours (mem0 metadata query)
    result_thread = None
    if memory and not cancelled and response_text:
        def _store(mem, msg, aid, resp):
            ts = int(time.time())
            try:
                clean = strip_think_blocks(resp)
                mem.add(
                    f"User: {msg}\n{aid.capitalize()}: {clean} /no_think",
                    user_id=aid,
                    metadata={"type": "conversation", "agent_id": aid, "timestamp": ts},
                )
                # Stockage shared uniquement si le message est substantiel
                # (pas les salutations, remerciements, confirmations simples)
                if _is_worth_sharing(msg):
                    mem.add(
                        f"User: {msg} /no_think",
                        user_id="shared",
                        metadata={"type": "conversation", "agent_id": aid, "timestamp": ts},
                    )
            except Exception as e:
                log_warn("memory_store", f"Failed to store conversation for {aid}: {e}")

        t = threading.Thread(target=_store, args=(memory, message, agent_id, response_text), daemon=True)
        t.start()
        result_thread = t

    result = {
        "agent_id": agent_id,
        "agent_name": agent_id.capitalize(),
        "agent_color": AGENT_COLORS.get(agent_id, "#FFFFFF"),
        "agent_emoji": AGENT_EMOJIS.get(agent_id, "⬜"),
        "response": response_text,
        "model": model,
        "memories_used": len(memories_used),
        "tool_iterations": iteration,
        "cancelled": cancelled,
        "_thread": result_thread,  # For the backend to track
    }
    if route_reason is not None:
        result["route_reason"] = route_reason
    return result
