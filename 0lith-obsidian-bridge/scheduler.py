"""
0Lith — Scheduler (déterministe, sans LLM)
==========================================
Exécutable toutes les heures via cron/Task Scheduler.

Pipeline :
  1. Scanne les tâches ouvertes du vault Obsidian
  2. Score chaque tâche (priorité / urgence / énergie / taille)
  3. Récupère les créneaux libres TimeTree (ou fallback disponibilites.md)
  4. Parse le Daily Note existant → conserve les [x] complétés
  5. Planifie les [ ] ouverts avec affinité de bande énergétique
  6. Ecrit/met à jour Daily Plans/YYYY-MM-DD.md (Day Planner compatible)

Usage:
    python scheduler.py                         # aujourd'hui, écrit dans vault
    python scheduler.py --dry-run               # affiche sans écrire
    python scheduler.py --date 2026-03-10       # date précise
    python scheduler.py --date today            # alias explicite
    python scheduler.py --vault /chemin/vault   # override VAULT_PATH
"""

import argparse
import re
import sys
import logging
import tempfile
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from config import VAULT_PATH, DAILY_PLANS_FOLDER
from api.obsidian_reader import ObsidianIndex
from api.task_parser import Task
from api.timetree_sync import get_free_slots

# ── Logging (stderr uniquement — aucun fichier dans le vault) ─────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s — %(message)s",
    datefmt="%H:%M:%S",
    stream=sys.stderr,
)
log = logging.getLogger("scheduler")

# ── Constantes ────────────────────────────────────────────────────────────────

PRIORITY_WEIGHTS = {"critical": 1.0, "high": 0.7, "medium": 0.4, "low": 0.1}
ENERGY_WEIGHTS   = {"high": 1.0, "medium": 0.6, "low": 0.3}
PRIORITY_EMOJI   = {"critical": "🔺", "high": "🔼", "normal": "", "low": "🔽"}

# Bandes horaires par niveau d'énergie
ENERGY_BANDS: dict[str, tuple[time, time]] = {
    "high":   (time(9,  0), time(12, 0)),
    "medium": (time(13, 0), time(17, 0)),
    "low":    (time(17, 0), time(22, 0)),
}
# Ordre de fallback si la bande préférée est pleine
BAND_FALLBACK_ORDER = ["high", "medium", "low"]

DEFAULT_TASK_DURATION_MIN = 30
MIN_SLOT_MIN = 15

_FR_WEEKDAYS = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]
_FR_MONTHS   = [
    "", "janvier", "février", "mars", "avril", "mai", "juin",
    "juillet", "août", "septembre", "octobre", "novembre", "décembre",
]

# Regex pour parser les lignes du daily note existant
_RE_COMPLETED = re.compile(r"^- \[x\] (\d{2}:\d{2}) - (\d{2}:\d{2}) (.+)$")
_RE_OPEN      = re.compile(r"^- \[ \] (\d{2}:\d{2}) - (\d{2}:\d{2}) (.+)$")


# ── Dataclasses ───────────────────────────────────────────────────────────────

@dataclass
class ScheduledBlock:
    start: datetime
    end: datetime
    task: Task | None       # None pour les blocs récupérés verbatim depuis le fichier existant
    raw_line: str           # ligne Markdown originale (conservée pour les [x])
    completed: bool
    effective_band: str = "medium"  # bande dans laquelle la tâche a été placée


# ── Helpers ───────────────────────────────────────────────────────────────────

def duration_to_minutes(s: str | None) -> int:
    """
    Convertit une chaîne de durée en minutes entières.

    "90min" -> 90 | "2h" -> 120 | "1h30" -> 90 | None -> 0
    """
    if not s:
        return 0
    m = re.fullmatch(r"(?:(\d+)h)?(?:(\d+)(?:min)?)?", s.strip())
    if not m or not m.group(0):
        return 0
    hours   = int(m.group(1)) if m.group(1) else 0
    minutes = int(m.group(2)) if m.group(2) else 0
    return hours * 60 + minutes


def compute_score(task: Task, now: datetime) -> float:
    """
    Score de priorité composite (0.0 – 1.0+).

    40% importance · 35% urgence · 15% bonus petite taille · 10% énergie
    """
    importance = PRIORITY_WEIGHTS.get(task.priority, 0.4)

    if task.deadline:
        deadline_dt = datetime.combine(task.deadline, datetime.min.time())
        hours_left  = (deadline_dt - now).total_seconds() / 3600
        urgency = 1.0 if hours_left <= 0 else max(0.1, 1.0 - hours_left / 168)
    else:
        urgency = 0.1

    estimated_minutes = duration_to_minutes(task.duration)
    size_bonus        = max(0, 1.0 - estimated_minutes / 240)
    energy_score      = ENERGY_WEIGHTS.get(task.energy or "", 0.6)

    return 0.40 * importance + 0.35 * urgency + 0.15 * size_bonus + 0.10 * energy_score


def slot_energy_band(slot_start: datetime) -> str:
    """Retourne 'high' / 'medium' / 'low' selon l'heure de début du créneau."""
    h = slot_start.time()
    for band, (band_start, band_end) in ENERGY_BANDS.items():
        if band_start <= h < band_end:
            return band
    return "low"


def _fmt_date_fr(d: date) -> str:
    """'Vendredi 07 mars 2026'"""
    return f"{_FR_WEEKDAYS[d.weekday()]} {d.day:02d} {_FR_MONTHS[d.month]} {d.year}"


# ── Gestion des créneaux ──────────────────────────────────────────────────────

def clip_slots_to_now(slots: list[dict], target_date: date, now: datetime) -> list[dict]:
    """
    Si target_date est aujourd'hui, supprime ou rogne les créneaux passés.
    Retourne les slots inchangés pour une date future.
    """
    if target_date != date.today():
        return list(slots)

    result: list[dict] = []
    for s in slots:
        if s["end"] <= now:
            continue  # entièrement écoulé
        start    = max(s["start"], now)
        duration = int((s["end"] - start).total_seconds() / 60)
        if duration >= MIN_SLOT_MIN:
            result.append({"start": start, "end": s["end"], "duration_min": duration})
    return result


def subtract_completed_from_slots(
    slots: list[dict], completed: list[ScheduledBlock]
) -> list[dict]:
    """
    Soustrait les intervalles déjà occupés (blocs complétés) des créneaux libres.
    Résultats < MIN_SLOT_MIN sont supprimés.
    """
    result = list(slots)

    for block in completed:
        new_result: list[dict] = []
        for s in result:
            bs, be = block.start, block.end
            ss, se = s["start"], s["end"]

            if be <= ss or bs >= se:
                # Aucun chevauchement
                new_result.append(s)
                continue

            # Partie avant le bloc
            if ss < bs:
                dur = int((bs - ss).total_seconds() / 60)
                if dur >= MIN_SLOT_MIN:
                    new_result.append({"start": ss, "end": bs, "duration_min": dur})

            # Partie après le bloc
            if be < se:
                dur = int((se - be).total_seconds() / 60)
                if dur >= MIN_SLOT_MIN:
                    new_result.append({"start": be, "end": se, "duration_min": dur})

        result = new_result

    result.sort(key=lambda s: s["start"])
    return result


# ── Parse du fichier existant ─────────────────────────────────────────────────

def parse_existing_daily(file_path: Path, target_date: date) -> list[ScheduledBlock]:
    """
    Extrait les blocs COMPLETÉS (- [x]) du daily note existant.
    Les blocs ouverts (- [ ]) sont ignorés — ils seront re-planifiés.
    """
    if not file_path.exists():
        return []

    blocks: list[ScheduledBlock] = []
    for raw_line in file_path.read_text(encoding="utf-8").splitlines():
        m = _RE_COMPLETED.match(raw_line.strip())
        if not m:
            continue
        try:
            start = datetime.combine(target_date, time.fromisoformat(m.group(1)))
            end   = datetime.combine(target_date, time.fromisoformat(m.group(2)))
        except ValueError:
            continue
        blocks.append(ScheduledBlock(
            start=start, end=end, task=None,
            raw_line=raw_line.strip(), completed=True,
        ))

    log.info("%d bloc(s) complété(s) récupérés depuis le fichier existant", len(blocks))
    return blocks


# ── Collecte ──────────────────────────────────────────────────────────────────

def collect_open_tasks(vault_path: Path) -> list[Task]:
    """Retourne toutes les tâches ouvertes du vault via ObsidianIndex."""
    index = ObsidianIndex(vault_path)
    return index.get_all_tasks(include_completed=False)


# ── Planification greedy ──────────────────────────────────────────────────────

def schedule_tasks(
    tasks: list[Task],
    free_slots: list[dict],
    target_date: date,
    now: datetime,
) -> tuple[list[ScheduledBlock], list[Task]]:
    """
    Planification greedy avec affinité de bande énergétique.

    Chaque tâche est placée dans la bande horaire qui correspond à son niveau
    d'énergie (high→matin, medium→après-midi, low→soir). Si la bande préférée
    est pleine, on passe à la suivante.

    Returns:
        (blocs planifiés, tâches non placées)
    """
    clipped = clip_slots_to_now(free_slots, target_date, now)

    # Curseurs : pour chaque slot, l'heure à partir de laquelle on peut encore placer
    cursors: list[datetime] = [s["start"] for s in clipped]
    slot_ends: list[datetime] = [s["end"] for s in clipped]

    scheduled: list[ScheduledBlock] = []
    unscheduled: list[Task] = []

    for task in tasks:
        preferred = task.energy or "medium"
        duration  = duration_to_minutes(task.duration) or DEFAULT_TASK_DURATION_MIN

        placed = False

        # Essayer les bandes dans l'ordre : préférée d'abord, puis les autres
        bands_to_try = [preferred] + [b for b in BAND_FALLBACK_ORDER if b != preferred]

        for band in bands_to_try:
            band_start, band_end = ENERGY_BANDS[band]

            for i, slot in enumerate(clipped):
                # Le slot doit appartenir à cette bande
                if slot_energy_band(slot["start"]) != band:
                    continue

                cursor = cursors[i]
                slot_end = slot_ends[i]

                # La tâche doit tenir dans le temps restant du slot
                task_end = cursor + timedelta(minutes=duration)
                if task_end > slot_end:
                    continue

                scheduled.append(ScheduledBlock(
                    start=cursor,
                    end=task_end,
                    task=task,
                    raw_line="",
                    completed=False,
                    effective_band=band,
                ))
                cursors[i] = task_end
                placed = True
                break

            if placed:
                break

        if not placed:
            unscheduled.append(task)

    return scheduled, unscheduled


# ── Suggestion ────────────────────────────────────────────────────────────────

def find_suggestion(
    scheduled: list[ScheduledBlock],
    free_slots_clipped: list[dict],
) -> str:
    """
    Identifie le plus grand créneau libre résiduel après placement des tâches.
    """
    # Reconstruire les gaps : pour chaque slot clipé, calculer ce qui reste
    # après les tâches planifiées
    gaps: list[tuple[datetime, int]] = []  # (start, duration_min)

    for slot in free_slots_clipped:
        # Tâches dans ce slot, triées par début
        tasks_in_slot = sorted(
            [b for b in scheduled
             if not b.completed
             and b.start >= slot["start"]
             and b.end <= slot["end"]],
            key=lambda b: b.start,
        )

        cursor = slot["start"]
        for block in tasks_in_slot:
            gap_min = int((block.start - cursor).total_seconds() / 60)
            if gap_min >= MIN_SLOT_MIN:
                gaps.append((cursor, gap_min))
            cursor = block.end

        # Gap final dans le slot
        remaining = int((slot["end"] - cursor).total_seconds() / 60)
        if remaining >= MIN_SLOT_MIN:
            gaps.append((cursor, remaining))

    if not gaps:
        return "Journée bien remplie — pas de créneau libre identifié."

    best_start, best_min = max(gaps, key=lambda g: g[1])
    h = f"{best_start.hour}h{best_start.minute:02d}"
    return (
        f"Il te reste {best_min} min libres à {h} — "
        f"idéal pour relire tes notes ou traiter 2-3 tâches courtes."
    )


# ── Rendu Markdown ────────────────────────────────────────────────────────────

def render_markdown(
    target_date: date,
    all_blocks: list[ScheduledBlock],
    unscheduled: list[Task],
    free_slots_original: list[dict],
    free_slots_clipped: list[dict],
    now: datetime,
) -> str:
    """Construit le Markdown Day Planner final."""
    lines: list[str] = []

    # ── Titre ──────────────────────────────────────────────────────────────────
    lines.append(f"## Planning du jour — {_fmt_date_fr(target_date)}")
    lines.append("")

    # ── Blockquote résumé ──────────────────────────────────────────────────────
    n_slots     = len(free_slots_original)
    n_planned   = sum(1 for b in all_blocks if not b.completed)
    n_completed = sum(1 for b in all_blocks if b.completed)
    n_deferred  = len(unscheduled)
    lines.append(
        f"> Mise à jour à {now.strftime('%H:%M')} · "
        f"{n_slots} créneau(x) libre(s) · "
        f"{n_planned} tâche(s) planifiée(s) · "
        f"{n_completed} complétée(s) · "
        f"{n_deferred} à reporter"
    )
    lines.append("")

    # ── Liste des blocs (triés par heure) ─────────────────────────────────────
    for block in sorted(all_blocks, key=lambda b: b.start):
        if block.completed:
            # Conserver la ligne originale verbatim
            lines.append(block.raw_line)
        else:
            task = block.task
            assert task is not None

            checkbox = "- [ ]"
            time_range = f"{block.start.strftime('%H:%M')} - {block.end.strftime('%H:%M')}"
            emoji = PRIORITY_EMOJI.get(task.priority, "")
            desc  = task.description
            proj  = f"[{task.project}]" if task.project else ""
            energy_tag = f"⚡ {block.effective_band}"

            parts = [p for p in [checkbox, time_range, desc, emoji, proj, energy_tag] if p]
            lines.append(" ".join(parts))

    # ── A reporter ─────────────────────────────────────────────────────────────
    if unscheduled:
        lines.append("")
        lines.append("### A reporter")
        lines.append("")
        for task in unscheduled:
            emoji = PRIORITY_EMOJI.get(task.priority, "")
            proj  = f"[{task.project}]" if task.project else ""
            parts = [p for p in ["- [ ]", task.description, emoji, proj] if p]
            lines.append(" ".join(parts))

    # ── Suggestion ─────────────────────────────────────────────────────────────
    lines.append("")
    suggestion = find_suggestion(
        [b for b in all_blocks if not b.completed],
        free_slots_clipped,
    )
    lines.append(f"💡 Suggestion : {suggestion}")

    return "\n".join(lines) + "\n"


# ── Ecriture atomique ─────────────────────────────────────────────────────────

def write_daily_plan(file_path: Path, markdown: str) -> None:
    """
    Ecriture atomique : temp file → rename.
    Pas de frontmatter YAML (incompatible avec le plugin Day Planner).
    """
    file_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = file_path.with_suffix(".tmp")
    tmp.write_text(markdown, encoding="utf-8")
    tmp.replace(file_path)


# ── Orchestration ─────────────────────────────────────────────────────────────

def run(
    vault_path: Path = VAULT_PATH,
    target_date: date | None = None,
    dry_run: bool = False,
) -> Path | str:
    """
    Pipeline complet de planification journalière.

    Returns:
        Path du fichier écrit, ou le markdown brut si dry_run.
    """
    target_date = target_date or date.today()
    now = datetime.now()

    # 1. Tâches
    log.info("Collecte des tâches ouvertes dans %s…", vault_path)
    tasks = collect_open_tasks(vault_path)
    scored = sorted(tasks, key=lambda t: compute_score(t, now), reverse=True)
    log.info("%d tâche(s) ouverte(s)", len(scored))

    # 2. Créneaux TimeTree
    log.info("Récupération des créneaux pour %s…", target_date.isoformat())
    free_slots = get_free_slots(target_date)
    log.info("%d créneau(x) disponible(s)", len(free_slots))

    # 3. Blocs déjà complétés dans le fichier existant
    daily_path = DAILY_PLANS_FOLDER / f"{target_date.isoformat()}.md"
    completed_blocks = parse_existing_daily(daily_path, target_date)

    # 4. Soustraire le temps des complétés des slots libres
    slots_available = subtract_completed_from_slots(free_slots, completed_blocks)

    # 5. Planifier les tâches ouvertes
    scheduled, unscheduled = schedule_tasks(scored, slots_available, target_date, now)
    log.info(
        "%d tâche(s) planifiée(s), %d à reporter",
        len(scheduled), len(unscheduled),
    )

    # 6. Assembler + rendre
    all_blocks = completed_blocks + scheduled
    free_slots_clipped = clip_slots_to_now(free_slots, target_date, now)
    markdown = render_markdown(
        target_date, all_blocks, unscheduled,
        free_slots, free_slots_clipped, now,
    )

    # 7. Sortie
    if dry_run:
        print(markdown)
        return markdown

    write_daily_plan(daily_path, markdown)
    log.info("Planning ecrit : %s", daily_path)
    return daily_path


# ── CLI ───────────────────────────────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Génère ou met à jour le planning journalier Obsidian (sans LLM).",
    )
    parser.add_argument(
        "--vault", metavar="PATH", default=None,
        help="Chemin du vault Obsidian (défaut : VAULT_PATH depuis config.py)",
    )
    parser.add_argument(
        "--date", metavar="DATE", default=None,
        help="Date cible au format YYYY-MM-DD ou 'today' (défaut : aujourd'hui)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Affiche le planning sans écrire dans le vault",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()

    vault_path = Path(args.vault) if args.vault else VAULT_PATH

    target_date: date | None = None
    if args.date and args.date.lower() != "today":
        try:
            target_date = date.fromisoformat(args.date)
        except ValueError:
            print(
                f"Erreur : date invalide '{args.date}'. Format attendu : YYYY-MM-DD.",
                file=sys.stderr,
            )
            sys.exit(1)

    result = run(vault_path=vault_path, target_date=target_date, dry_run=args.dry_run)
    if not args.dry_run:
        print(f"Planning ecrit : {result}")
