"""
0Lith — Scheduler Agent
========================
Génère un planning journalier optimisé en envoyant les tâches à Monolith (qwen3:14b).
Écrit le résultat en Markdown dans Daily Plans/YYYY-MM-DD.md.
"""

import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import VAULT_PATH, DAILY_PLANS_FOLDER, MODEL_NAME

from api.task_parser import Task
from api import ollama_client


# ── Prompt system ─────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """\
Tu es Monolith, l'orchestrateur IA du système 0Lith. Tu planifies les journées de Matthieu.

Règles :
- Réponds UNIQUEMENT en Markdown Day Planner (format ci-dessous), sans commentaire.
- Alloue les tâches critiques et high en matinée quand l'énergie est peak.
- Respecte strictement les durées estimées.
- Ne dépasse pas les créneaux disponibles.
- Si une tâche dépasse le temps disponible, note-la en section "À reporter".
- Utilise ce format exact :

## Planning — {date}

### Matin
* [ ] HH:MM - HH:MM Titre de la tâche [Projet]

### Après-midi
* [ ] HH:MM - HH:MM Titre de la tâche [Projet]

### À reporter
* [ ] Tâche impossible à caser aujourd'hui (raison)
"""


# ── Agent ─────────────────────────────────────────────────────────────────────

class SchedulerAgent:
    """
    Agent de planification journalière.

    Workflow :
        1. Reçoit les tâches ouvertes et les créneaux libres.
        2. Construit un prompt structuré pour Monolith.
        3. Envoie à Ollama et retourne le planning Markdown.
        4. Optionnellement : écrit le planning dans le vault.
    """

    def plan_day(
        self,
        tasks: list[Task],
        free_slots: list[str],
        target_date: date | None = None,
    ) -> str:
        """
        Génère un planning journalier optimisé.

        Args:
            tasks: Liste des tâches ouvertes (non complétées).
            free_slots: Créneaux disponibles, ex. ["09:00-12:00", "14:00-18:00"].
            target_date: Date du planning (défaut : aujourd'hui).

        Returns:
            Planning en Markdown Day Planner format.
        """
        if target_date is None:
            target_date = date.today()

        prompt = self._build_prompt(tasks, free_slots, target_date)
        system = _SYSTEM_PROMPT.format(date=target_date.isoformat())

        return ollama_client.generate(
            prompt=prompt,
            system=system,
            model=MODEL_NAME,
            num_ctx=8192,
        )

    def write_daily_plan(self, target_date: date, markdown: str) -> Path:
        """
        Écrit le planning dans le vault Obsidian.

        Args:
            target_date: Date du planning.
            markdown: Contenu Markdown à écrire.

        Returns:
            Chemin absolu du fichier créé.
        """
        DAILY_PLANS_FOLDER.mkdir(parents=True, exist_ok=True)
        file_path = DAILY_PLANS_FOLDER / f"{target_date.isoformat()}.md"

        header = (
            f"---\n"
            f"date: {target_date.isoformat()}\n"
            f"generated: {datetime.now().isoformat(timespec='seconds')}\n"
            f"generator: 0Lith/Monolith\n"
            f"---\n\n"
        )

        file_path.write_text(header + markdown, encoding="utf-8")
        return file_path

    # ── Prompt builder ────────────────────────────────────────────────────────

    def _build_prompt(
        self,
        tasks: list[Task],
        free_slots: list[str],
        target_date: date,
    ) -> str:
        """Construit le prompt utilisateur pour Monolith."""
        lines: list[str] = [
            f"Date : {target_date.isoformat()}",
            "",
            "## Créneaux disponibles",
        ]
        for slot in free_slots:
            lines.append(f"- {slot}")

        lines += ["", "## Tâches à planifier"]

        # Tri : critical > high > normal > low, puis par deadline
        priority_order = {"critical": 0, "high": 1, "normal": 2, "low": 3}
        sorted_tasks = sorted(
            tasks,
            key=lambda t: (
                priority_order.get(t.priority, 2),
                t.deadline.isoformat() if t.deadline else "9999-12-31",
            ),
        )

        for task in sorted_tasks:
            lines.append(task.to_prompt_line())

        lines += [
            "",
            "Génère le planning journalier optimisé en Markdown Day Planner.",
            "Ne réponds QUE avec le Markdown, sans introduction ni conclusion.",
        ]

        return "\n".join(lines)
