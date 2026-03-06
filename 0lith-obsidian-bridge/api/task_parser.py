"""
0Lith — Task Parser
===================
Parse les tâches Markdown du vault Obsidian (format Dataview + Tasks Plugin).

Formats supportés :
  - [ ] Description simple
  - [ ] Description 🔺 📅 2026-03-15
    [duration:: 90min] [energy:: high] [project:: 0Lith] #dev
"""

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Optional


# ── Regex ────────────────────────────────────────────────────────────────────

# Checkbox (incomplète ou complète)
_RE_TASK = re.compile(r"^(\s*)-\s+\[( |x|X)\]\s+(.+)$", re.MULTILINE)

# Priorité emoji
_PRIORITY_MAP: dict[str, str] = {
    "🔺": "critical",
    "⏫": "critical",
    "🔼": "high",
    "🔽": "low",
    "⬇️": "low",
    "⬇": "low",
}

# Deadline Obsidian Tasks Plugin : 📅 YYYY-MM-DD
_RE_DEADLINE = re.compile(r"📅\s*(\d{4}-\d{2}-\d{2})")

# Scheduled : ⏳ YYYY-MM-DD
_RE_SCHEDULED = re.compile(r"⏳\s*(\d{4}-\d{2}-\d{2})")

# Champs Dataview inline : [key:: value]
_RE_INLINE = re.compile(r"\[(\w+)::\s*([^\]]+)\]")

# Tags : #word (évite les couleurs hex #AABBCC)
_RE_TAG = re.compile(r"#([a-zA-ZÀ-ÿ][a-zA-ZÀ-ÿ0-9_/-]*)")


# ── Dataclass ─────────────────────────────────────────────────────────────────

@dataclass
class Task:
    """Représente une tâche Obsidian parsée."""

    description: str
    """Texte de la tâche, nettoyé des métadonnées."""

    priority: str = "normal"
    """critical | high | normal | low"""

    deadline: Optional[date] = None
    """Date limite (📅 YYYY-MM-DD)."""

    scheduled: Optional[date] = None
    """Date planifiée (⏳ YYYY-MM-DD)."""

    duration: Optional[str] = None
    """Durée estimée, ex. '90min', '2h'."""

    energy: Optional[str] = None
    """Niveau d'énergie requis : high | medium | low."""

    project: Optional[str] = None
    """Projet associé."""

    tags: list[str] = field(default_factory=list)
    """Liste de tags sans le #."""

    source_file: str = ""
    """Chemin relatif au vault de la note source."""

    completed: bool = False
    """True si la case est cochée [x]."""

    raw: str = ""
    """Ligne brute originale."""

    def to_dict(self) -> dict:
        """Sérialise la tâche en dict JSON-compatible."""
        return {
            "description": self.description,
            "priority": self.priority,
            "deadline": self.deadline.isoformat() if self.deadline else None,
            "scheduled": self.scheduled.isoformat() if self.scheduled else None,
            "duration": self.duration,
            "energy": self.energy,
            "project": self.project,
            "tags": self.tags,
            "source_file": self.source_file,
            "completed": self.completed,
        }

    def to_prompt_line(self) -> str:
        """Formatage compact pour injection dans un prompt LLM."""
        parts = [f"- {self.description}"]
        if self.priority != "normal":
            parts.append(f"[{self.priority}]")
        if self.deadline:
            parts.append(f"deadline:{self.deadline.isoformat()}")
        if self.duration:
            parts.append(f"durée:{self.duration}")
        if self.energy:
            parts.append(f"énergie:{self.energy}")
        if self.project:
            parts.append(f"projet:{self.project}")
        return " ".join(parts)


# ── Parser ────────────────────────────────────────────────────────────────────

def parse_tasks(content: str, source_file: str = "") -> list[Task]:
    """
    Parse toutes les tâches Markdown d'un texte.

    Args:
        content: Contenu brut de la note Markdown.
        source_file: Chemin relatif de la note (pour traçabilité).

    Returns:
        Liste de Task parsées.
    """
    tasks: list[Task] = []

    for match in _RE_TASK.finditer(content):
        checkbox = match.group(2)
        raw_line = match.group(3).strip()

        completed = checkbox.lower() == "x"
        task = _parse_task_line(raw_line, completed, source_file)
        tasks.append(task)

    return tasks


def _parse_task_line(raw_line: str, completed: bool, source_file: str) -> Task:
    """Parse une ligne de tâche en Task."""
    text = raw_line

    # Priorité
    priority = "normal"
    for emoji, level in _PRIORITY_MAP.items():
        if emoji in text:
            priority = level
            text = text.replace(emoji, "").strip()
            break

    # Deadline
    deadline: Optional[date] = None
    m = _RE_DEADLINE.search(text)
    if m:
        try:
            deadline = date.fromisoformat(m.group(1))
        except ValueError:
            pass
        text = _RE_DEADLINE.sub("", text).strip()

    # Scheduled
    scheduled: Optional[date] = None
    m = _RE_SCHEDULED.search(text)
    if m:
        try:
            scheduled = date.fromisoformat(m.group(1))
        except ValueError:
            pass
        text = _RE_SCHEDULED.sub("", text).strip()

    # Champs Dataview inline [key:: value]
    inline: dict[str, str] = {}
    for key, value in _RE_INLINE.findall(text):
        inline[key.lower()] = value.strip()
    text = _RE_INLINE.sub("", text).strip()

    # Tags #word
    tags = _RE_TAG.findall(text)
    text = _RE_TAG.sub("", text).strip()

    # Nettoyage résiduel des espaces multiples
    description = re.sub(r"\s{2,}", " ", text).strip()

    return Task(
        description=description,
        priority=inline.get("priority", priority),
        deadline=deadline,
        scheduled=scheduled,
        duration=inline.get("duration") or inline.get("durée"),
        energy=inline.get("energy") or inline.get("énergie"),
        project=inline.get("project") or inline.get("projet"),
        tags=tags,
        source_file=source_file,
        completed=completed,
        raw=raw_line,
    )
