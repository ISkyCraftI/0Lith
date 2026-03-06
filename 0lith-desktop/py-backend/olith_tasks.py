#!/usr/bin/env python3
"""
0Lith — Gestionnaire de tâches #User
=====================================
Détecte les tags #User dans les réponses agents et les consigne dans
~/.0lith/Tasks/User_needed.md.

Usage par les agents :
  Quand un agent est bloqué ou a besoin d'une réponse humaine, il inclut
  le tag #User dans sa réponse, suivi de la question sur la même ligne.
  Exemple : "#User Pouvez-vous me fournir votre token API Anthropic ?"

Le fichier User_needed.md est relu à chaque chat :
  - Les nouvelles questions #User sont ajoutées.
  - Les items marqués [x] (résolus) sont supprimés automatiquement.
"""

import re
import threading
from datetime import datetime
from pathlib import Path

TASKS_FILE = Path.home() / ".0lith" / "Tasks" / "User_needed.md"

_lock = threading.Lock()

# Correspond à "#User" suivi du texte de la question sur la même ligne
_USER_TAG_RE = re.compile(r"#User\b[:\s]*(.+?)$", re.IGNORECASE | re.MULTILINE)


# ============================================================================
# FICHIER
# ============================================================================

def _ensure_file() -> None:
    """Crée le dossier et le fichier s'ils n'existent pas."""
    TASKS_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not TASKS_FILE.exists():
        TASKS_FILE.write_text(
            "# 0Lith — Questions en attente de l'utilisateur\n\n"
            "Les agents ajoutent ici les blocages nécessitant une réponse humaine.\n"
            "Répondez dans le chat ou annotez directement ce fichier.\n"
            "Les items `[x]` sont supprimés automatiquement au prochain message.\n\n",
            encoding="utf-8",
        )


# ============================================================================
# EXTRACTION
# ============================================================================

def extract_user_tags(response_text: str) -> list[str]:
    """Retourne la liste des questions #User trouvées dans le texte de l'agent."""
    tags = []
    for match in _USER_TAG_RE.finditer(response_text):
        question = match.group(1).strip()
        if question:
            tags.append(question)
    return tags


# ============================================================================
# AJOUT
# ============================================================================

def add_user_tags(agent_id: str, user_message: str, response_text: str) -> int:
    """
    Analyse response_text, et ajoute chaque tag #User dans le fichier.
    Retourne le nombre de tags ajoutés.
    """
    tags = extract_user_tags(response_text)
    if not tags:
        return 0

    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    agent_name = agent_id.capitalize()

    # Contexte court du message utilisateur
    msg_short = user_message[:80].replace("\n", " ")
    if len(user_message) > 80:
        msg_short += "…"

    lines = []
    for tag in tags:
        tag_clean = tag.replace("\n", " ")[:300]
        lines.append(
            f"- [ ] [{ts}] **{agent_name}** _(re: {msg_short})_: {tag_clean}\n"
        )

    with _lock:
        _ensure_file()
        with open(TASKS_FILE, "a", encoding="utf-8") as f:
            for line in lines:
                f.write(line)

    return len(tags)


# ============================================================================
# NETTOYAGE
# ============================================================================

def resolve_completed() -> int:
    """
    Supprime du fichier les lignes marquées [x] (résolues).
    Retourne le nombre de lignes supprimées.
    """
    with _lock:
        if not TASKS_FILE.exists():
            return 0

        content = TASKS_FILE.read_text(encoding="utf-8")
        lines = content.splitlines(keepends=True)
        kept = [
            line for line in lines
            if not re.match(r"^\s*-\s*\[x\]", line, re.IGNORECASE)
        ]
        removed = len(lines) - len(kept)
        if removed > 0:
            TASKS_FILE.write_text("".join(kept), encoding="utf-8")

    return removed


# ============================================================================
# LECTURE (pour IPC)
# ============================================================================

def list_pending_tasks() -> list[dict]:
    """Retourne la liste des tâches en attente sous forme de dicts."""
    with _lock:
        if not TASKS_FILE.exists():
            return []
        content = TASKS_FILE.read_text(encoding="utf-8")

    tasks = []
    for line in content.splitlines():
        m = re.match(
            r"^\s*-\s*\[ \]\s*\[(.+?)\]\s*\*\*(.+?)\*\*.*?:\s*(.+)$",
            line,
        )
        if m:
            tasks.append({
                "timestamp": m.group(1),
                "agent": m.group(2),
                "question": m.group(3).strip(),
            })
    return tasks
