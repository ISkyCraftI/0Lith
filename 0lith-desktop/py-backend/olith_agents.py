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

HODOLITH_SYSTEM_PROMPT = """You are Hodolith, the dispatcher of the 0Lith system. Analyze the message and reply ONLY with valid JSON:
{"route": "monolith|aerolith|cryolith|pyrolith", "reason": "..."}

Rules:
- monolith: conversations, greetings, personal questions, general questions, system/PC/application questions, help, strategy, planning, reasoning — anything that is NOT code or cybersecurity
- aerolith: writing code, scripts, debugging, programming
- cryolith: defense, CVE, detection, YARA, hardening, blue team
- pyrolith: offensive pentesting ONLY when the user EXPLICITLY requests an intrusion test or offensive attack

IMPORTANT: When in doubt, ALWAYS route to "monolith". NEVER route to "hodolith"."""


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
    You have access to the following tools. To use them, emit a JSON block in your response.
    The system will execute the tool and send you back the result automatically.

    1. READ A FILE:
    ```json
    {"action": "read_file", "path": "relative/path/to/file.py"}
    ```
    Options: "offset" (start line, default 1), "limit" (number of lines, default 500)

    2. LIST FILES:
    ```json
    {"action": "list_files", "path": ".", "max_depth": 3}
    ```

    3. SEARCH IN CODE:
    ```json
    {"action": "search_files", "pattern": "regex_pattern", "path": ".", "glob": "*.py"}
    ```

    4. WRITE A FILE:
    ```json
    {"action": "write_file", "path": "path/to/file.py", "content": "full file content"}
    ```

    5. EDIT A FILE (exact replacement):
    ```json
    {"action": "edit_file", "path": "path/to/file.py", "old_string": "text to replace", "new_string": "new text"}
    ```

    6. SEARCH MEMORY:
    ```json
    {"action": "search_mem0", "query": "concept or entity to search"}
    ```

    7. ADD TO MEMORY:
    ```json
    {"action": "add_mem0", "content": "User prefers X for Y"}
    ```

    8. SYSTEM INFO:
    ```json
    {"action": "system_info"}
    ```
    Returns: OS, active processes (top 30 by memory), total RAM, GPU (VRAM, usage).
    Useful for diagnosing the system, checking which applications are running, etc.

    USAGE RULES:
    - You can use ABSOLUTE paths (e.g. C:\\Users\\skycr\\Perso\\0Lith) or paths relative to the project.
    - ALWAYS start by reading relevant files before proposing any modifications.
    - Use list_files to discover the project structure.
    - Use search_files to find patterns in code.
    - For modifications, prefer edit_file (precise diff) over write_file (full overwrite).
    - You can emit MULTIPLE tools in a single response.
    - After each tool, you will receive the result and can continue.
    - NEVER respond with generic advice. Base ALL your recommendations on the actual content of files you have read.
  </available_tools>"""

    autonomy_section = ""
    if has_tools:
        autonomy_section = """
  <autonomy_levels>
    Level 0 (OBSERVE): You can read files, list, search, query Mem0 WITHOUT permission.
    Level 1 (SUGGEST): You can propose code or architecture modifications.
    Level 2 (ACT): You execute writes/edits. The system will ask the User for confirmation if needed.
  </autonomy_levels>"""

    prompt = f"""<system>
<identity>
  You are {agent_id.capitalize()}, {agent_info['role']} of the 0Lith system.
  {agent_info['description']}
  Your primary user is the User. You communicate in French (unless the user writes in another language).
</identity>

<core_principles>
  <principle name="Deep Exploration First" priority="1">
    ABSOLUTE RULE: NEVER give recommendations, analysis or answers about code without first READING the relevant files.
    When the User asks about a project, a file, or code:
    1. Use list_files to understand the structure.
    2. Use read_file to read key files (config, main code, dependencies).
    3. Use search_files if you are looking for a specific pattern.
    4. ONLY AFTER reading the actual code, formulate your response.
    Your answers must cite exact line numbers, real function names, concrete issues found in the code.
    FORBIDDEN: generic advice lists (e.g. "add tests", "document your code", "use a linter").
  </principle>
  <principle name="Memory-Driven Context" priority="2">
    You have access to Mem0. Before asking the User about their preferences, stack or past decisions, consult your memory first.
  </principle>
  <principle name="Non-Destructive Operations" priority="3">
    When proposing file modifications, always provide the exact diff or specify the path and content to replace. Never do destructive overwrites unless explicitly requested.
  </principle>
  <principle name="Concision" priority="4">
    Respond in a useful and concise way. No sycophancy. Be direct and technical.
  </principle>
  <principle name="User Tag" priority="5">
    If you are blocked, lack critical information only the User can provide, or need a human decision before continuing, use the #User tag.
    Place #User at the start of a line, followed by your precise question on the same line.
    Example: "#User Do you have the API token X required to continue?"
    This tag is automatically logged to ~/.0lith/Tasks/User_needed.md.
    Only use #User when genuinely blocked — not for comfort questions.
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

    # Enregistrer les tags #User dans User_needed.md
    if response_text and not cancelled:
        try:
            from olith_tasks import add_user_tags
            add_user_tags(agent_id, message, response_text)
        except Exception as e:
            log_warn("tasks", f"Failed to process #User tags: {e}")

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
