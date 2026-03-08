"""
0Lith — TimeTree Sync
=====================
Récupère les événements TimeTree via `timetree-exporter`, parse le .ics généré,
calcule les créneaux libres et retourne la liste pour SchedulerAgent.plan_day().

Fallback : lit C:\\Users\\skycr\\Perso\\Arkhe\\Weekly\\disponibilites.md si l'export échoue.
"""

import logging
import os
import re
import subprocess
import sys
import tempfile
from datetime import date, datetime, time
from pathlib import Path

from dotenv import load_dotenv

# ── Env ───────────────────────────────────────────────────────────────────────
# api/ → obsidian-bridge/ → 0Lith/ → Perso/
_ROOT_ENV = Path(__file__).parent.parent.parent.parent / ".env"
load_dotenv(_ROOT_ENV, override=False)

# ── Logging ───────────────────────────────────────────────────────────────────
log = logging.getLogger(__name__)

# ── Constantes ────────────────────────────────────────────────────────────────
WORK_START = time(8, 0)
WORK_END = time(20, 0)
MIN_SLOT_MIN = 15
EXPORT_TIMEOUT_SEC = 60
FALLBACK_MD = Path(r"C:\Users\skycr\Perso\Arkhe\Weekly\disponibilites.md")
_TMP_ICS = Path(tempfile.gettempdir()) / "timetree_export_0lith.ics"
_FR_WEEKDAYS = {
    "Lundi": 0,
    "Mardi": 1,
    "Mercredi": 2,
    "Jeudi": 3,
    "Vendredi": 4,
    "Samedi": 5,
    "Dimanche": 6,
}

# ── Public API ────────────────────────────────────────────────────────────────


def get_free_slots(target_date: date, ics_path: Path | None = None) -> list[dict]:
    """
    Retourne les créneaux libres pour target_date.

    Chaque slot : {"start": datetime, "end": datetime, "duration_min": int}
    """
    _created_tmp = False
    try:
        if ics_path is None:
            ics_path = _export_ics()
            _created_tmp = True
            if ics_path is None:
                return _parse_fallback_md(target_date)

        try:
            events = parse_ics_events(ics_path, target_date)
        except Exception as exc:
            log.warning("parse_ics_events failed (%s) — using fallback", exc)
            return _parse_fallback_md(target_date)

        return compute_free_slots(events, target_date)

    finally:
        if _created_tmp and _TMP_ICS.exists():
            try:
                _TMP_ICS.unlink()
            except OSError:
                pass


def parse_ics_events(
    ics_path: Path, target_date: date
) -> list[tuple[datetime, datetime]]:
    """
    Parse un fichier .ics et retourne les événements qui chevauchent target_date.

    Returns:
        Liste de (dtstart, dtend) en heure locale naive.
    """
    from icalendar import Calendar  # type: ignore[import-untyped]

    day_start = datetime.combine(target_date, time(0, 0))
    day_end = datetime.combine(target_date, time(23, 59, 59, 999999))

    events: list[tuple[datetime, datetime]] = []

    raw = ics_path.read_bytes()
    cal = Calendar.from_ical(raw)

    for component in cal.walk():
        if component.name != "VEVENT":
            continue

        dt_start_raw = component.decoded("DTSTART")
        all_day = isinstance(dt_start_raw, date) and not isinstance(
            dt_start_raw, datetime
        )

        if all_day:
            dtstart = datetime.combine(dt_start_raw, time(0, 0))
            # DTEND for all-day is exclusive next day in iCal spec
            if "DTEND" in component:
                dt_end_raw = component.decoded("DTEND")
                dtend_raw_dt = (
                    datetime.combine(dt_end_raw, time(0, 0))
                    if isinstance(dt_end_raw, date) and not isinstance(dt_end_raw, datetime)
                    else dt_end_raw
                )
                dtend = dt_end_raw if isinstance(dt_end_raw, datetime) else dtend_raw_dt
            elif "DURATION" in component:
                dtend = dtstart + component.decoded("DURATION")
            else:
                dtend = datetime.combine(dt_start_raw, time(23, 59, 59))
        else:
            # Strip timezone — convert to local then make naive
            dtstart = dt_start_raw.astimezone().replace(tzinfo=None)
            if "DTEND" in component:
                dt_end_raw = component.decoded("DTEND")
                dtend = dt_end_raw.astimezone().replace(tzinfo=None)
            elif "DURATION" in component:
                dtend = dtstart + component.decoded("DURATION")
            else:
                dtend = dtstart

        # Keep events that overlap with target_date
        if dtstart < day_end and dtend > day_start:
            events.append((dtstart, dtend))

    return events


def compute_free_slots(
    events: list[tuple[datetime, datetime]],
    target_date: date,
    work_start: time = WORK_START,
    work_end: time = WORK_END,
) -> list[dict]:
    """
    Calcule les créneaux libres à partir d'une liste d'événements.

    Fonction pure : aucun I/O.
    """
    ws = datetime.combine(target_date, work_start)
    we = datetime.combine(target_date, work_end)

    # 1. Clip events to work window
    clipped: list[tuple[datetime, datetime]] = []
    for dtstart, dtend in events:
        start = max(dtstart, ws)
        end = min(dtend, we)
        if start < end:
            clipped.append((start, end))

    # 2. Sort + merge overlapping intervals
    clipped.sort(key=lambda x: x[0])
    merged: list[tuple[datetime, datetime]] = []
    for start, end in clipped:
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))

    # 3. Compute gaps
    boundaries = [(ws, ws)] + merged + [(we, we)]
    free_slots: list[dict] = []
    for i in range(len(boundaries) - 1):
        gap_start = boundaries[i][1]  # end of previous block
        gap_end = boundaries[i + 1][0]  # start of next block
        if gap_start < gap_end:
            duration = int((gap_end - gap_start).total_seconds() / 60)
            if duration >= MIN_SLOT_MIN:
                free_slots.append(
                    {"start": gap_start, "end": gap_end, "duration_min": duration}
                )

    return free_slots


def get_free_slots_as_strings(target_date: date) -> list[str]:
    """
    Adaptateur pour SchedulerAgent.plan_day(free_slots).

    Returns:
        Liste de strings "HH:MM-HH:MM".
    """
    return [
        f"{s['start'].strftime('%H:%M')}-{s['end'].strftime('%H:%M')}"
        for s in get_free_slots(target_date)
    ]


# ── Fonctions internes ────────────────────────────────────────────────────────


def _export_ics() -> Path | None:
    """
    Lance timetree-exporter et écrit le résultat dans _TMP_ICS.

    Returns:
        Path vers le fichier .ics si succès, None sinon.
    """
    email = os.environ.get("TIMETREE_EMAIL")
    password = os.environ.get("TIMETREE_PASSWORD")
    code = os.environ.get("TIMETREE_CALENDAR_CODE")

    if not (email and password and code):
        missing = [
            k
            for k, v in {
                "TIMETREE_EMAIL": email,
                "TIMETREE_PASSWORD": password,
                "TIMETREE_CALENDAR_CODE": code,
            }.items()
            if not v
        ]
        log.warning("Missing env vars for timetree-exporter: %s — using fallback", missing)
        return None

    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    try:
        result = subprocess.run(
            [sys.executable, "-m", "timetree_exporter",
             "-e", email, "-c", code, "--output", str(_TMP_ICS)],
            timeout=EXPORT_TIMEOUT_SEC,
            env=env,
            capture_output=True,
        )
    except FileNotFoundError:
        log.warning("timetree_exporter module not found — using fallback")
        return None
    except subprocess.TimeoutExpired:
        log.warning("timetree-exporter timed out after %ss — using fallback", EXPORT_TIMEOUT_SEC)
        return None

    if result.returncode != 0:
        log.warning(
            "timetree-exporter exited %d: %s — using fallback",
            result.returncode,
            result.stderr.decode(errors="replace").strip(),
        )
        return None

    if not _TMP_ICS.exists() or _TMP_ICS.stat().st_size == 0:
        log.warning("timetree-exporter produced empty/missing .ics — using fallback")
        return None

    return _TMP_ICS


def _parse_fallback_md(target_date: date) -> list[dict]:
    """
    Lit disponibilites.md et retourne les créneaux pour le jour de target_date.
    """
    if not FALLBACK_MD.exists():
        log.error("Fallback file not found: %s", FALLBACK_MD)
        return []

    target_weekday = target_date.weekday()  # 0=Monday … 6=Sunday
    slot_re = re.compile(r"^-\s*(\d{2}:\d{2})-(\d{2}:\d{2})\s*$")

    slots: list[dict] = []
    active = False

    for raw_line in FALLBACK_MD.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()

        if line.startswith("<!--"):
            log.debug("Skipping comment: %s", line)
            continue

        # Section header: ## Lundi / ## Mardi / …
        if line.startswith("## "):
            day_name = line[3:].strip()
            active = _FR_WEEKDAYS.get(day_name) == target_weekday
            continue

        if not active:
            continue

        m = slot_re.match(line)
        if not m:
            if line:
                log.debug("Skipping malformed line: %r", line)
            continue

        start_t = datetime.strptime(m.group(1), "%H:%M").time()
        end_t = datetime.strptime(m.group(2), "%H:%M").time()
        dtstart = datetime.combine(target_date, start_t)
        dtend = datetime.combine(target_date, end_t)
        duration = int((dtend - dtstart).total_seconds() / 60)

        if duration >= MIN_SLOT_MIN:
            slots.append({"start": dtstart, "end": dtend, "duration_min": duration})

    return slots


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    today = date.today()
    slots = get_free_slots_as_strings(today)
    print(f"Créneaux libres — {today.isoformat()}")
    if slots:
        for s in slots:
            print(f"  {s}")
    else:
        print("  (aucun créneau disponible)")
