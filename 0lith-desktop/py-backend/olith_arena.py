"""
olith_arena.py — Arena sparring module
Pyrolith (Red Team) vs Cryolith (Blue Team), SQL Injection scenario.

Each round:
  1. Pyrolith makes an attack move (LLM call → structured JSON)
  2. Cryolith responds with a defense move (LLM call → structured JSON)
  3. Both moves are emitted as arena events with live score update

After 5 rounds: both agents review their weaknesses.

Log files: ~/.0lith/arena_logs/arena_YYYYMMDD_HHMMSS.jsonl
  Each line is a JSON object with event type, raw LLM response, parsed move, etc.
"""

import json
import os
import re
import time
import requests
from datetime import datetime
from pathlib import Path

from olith_ollama import chat_with_ollama, chat_docker_pyrolith
from olith_shared import strip_think_blocks, log_info, log_warn

# ── Constants ──────────────────────────────────────────────────────────────

PYROLITH_URL = "http://localhost:11435"
PYROLITH_MODEL = "deephat/DeepHat-V1-7B:latest"  # Docker :11435
CRYOLITH_MODEL = "hf.co/fdtn-ai/Foundation-Sec-8B-Q4_K_M-GGUF:latest"
FALLBACK_MODEL = "qwen3:14b"

# Arena-quality override: use Qwen3:14b when specialized models produce garbage output
# Set env vars ARENA_RED_MODEL / ARENA_BLUE_MODEL to override
ARENA_RED_MODEL  = os.environ.get("ARENA_RED_MODEL",  PYROLITH_MODEL)
ARENA_BLUE_MODEL = os.environ.get("ARENA_BLUE_MODEL", CRYOLITH_MODEL)

MOVE_TYPES_RED = ["RECON", "EXPLOIT", "SUCCESS", "PIVOT", "DATA"]
MOVE_TYPES_BLUE = ["MONITOR", "ALERT", "BLOCK", "PATCH", "ISOLATE"]

# Forced type sequence per round - ensures narrative progression
RED_SEQUENCE  = ["RECON", "EXPLOIT", "EXPLOIT", "PIVOT", "DATA"]
BLUE_SEQUENCE = ["MONITOR", "ALERT", "BLOCK", "PATCH", "ISOLATE"]

BADGE_COLORS = {
    "RECON":   "#475569",
    "EXPLOIT": "#ea580c",
    "SUCCESS": "#16a34a",
    "PIVOT":   "#7c3aed",
    "DATA":    "#dc2626",
    "MONITOR": "#0284c7",
    "ALERT":   "#d97706",
    "BLOCK":   "#dc2626",
    "PATCH":   "#16a34a",
    "ISOLATE": "#7f1d1d",
}

# Points awarded per move type
SCORE_TABLE = {
    "RECON":   3,
    "EXPLOIT": 10,
    "SUCCESS": 15,
    "PIVOT":   12,
    "DATA":    20,
    "MONITOR": 3,
    "ALERT":   5,
    "BLOCK":   15,
    "PATCH":   10,
    "ISOLATE": 20,
}

# ── File Logging ────────────────────────────────────────────────────────────

_ARENA_LOG_DIR = Path.home() / ".0lith" / "arena_logs"


def _open_log(slug: str) -> Path:
    """Create a new per-session arena log file and return its path."""
    _ARENA_LOG_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe = re.sub(r"[^a-zA-Z0-9]", "_", slug)[:20]
    return _ARENA_LOG_DIR / f"arena_{ts}_{safe}.jsonl"


def _logj(log_path: Path, entry: dict) -> None:
    """Append a JSON line to the log file (never raises)."""
    try:
        with open(log_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass


# ── Helpers ────────────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now().strftime("%H:%M:%S")


def _pyrolith_available() -> bool:
    try:
        r = requests.get(f"{PYROLITH_URL}/api/tags", timeout=3)
        return r.status_code == 200
    except Exception:
        return False


def _get_timeout(model: str) -> int:
    """Return appropriate timeout in seconds for a given model."""
    if "DeepHat" in model or "deephat" in model.lower():
        return 300   # regularly takes 125s+
    if "Foundation-Sec" in model or "fdtn-ai" in model:
        return 300   # regularly takes 120-220s
    if "qwen3:14b" in model:
        return 180
    if "qwen3" in model:
        return 120
    return 240  # safe fallback for unknown models


def _raw_call(messages: list[dict], model: str, is_docker: bool = False) -> str:
    """Low-level LLM call with adaptive timeout. num_ctx=2048 kept small — arena prompts are short."""
    timeout = _get_timeout(model)
    if is_docker:
        return chat_docker_pyrolith(model, messages, timeout=timeout, num_ctx=2048)
    return chat_with_ollama(model, messages, timeout=timeout, num_ctx=2048)


def _llm_call_with_fallback(messages: list[dict], model: str, is_docker: bool = False) -> str:
    """LLM call with automatic fallback to qwen3:14b if response too short (< 20 chars)."""
    raw = _raw_call(messages, model, is_docker)
    stripped = strip_think_blocks(raw).strip()
    if len(stripped) < 20 and model != FALLBACK_MODEL:
        log_warn("arena", f"Réponse trop courte ({len(stripped)} chars) depuis {model}, fallback qwen3:14b")
        raw = _raw_call(messages, FALLBACK_MODEL, is_docker=False)
    return raw


def _call_pyrolith(messages: list[dict]) -> str:
    """Call Pyrolith (Docker). Falls back to qwen3:14b if Docker is unavailable or response too short."""
    if _pyrolith_available():
        try:
            return _llm_call_with_fallback(messages, ARENA_RED_MODEL, is_docker=True)
        except Exception as e:
            log_warn("arena", f"Pyrolith failed ({type(e).__name__}: {e}), falling back to qwen3:14b")

    log_info("arena", "Using qwen3:14b as Pyrolith fallback")
    return _raw_call(messages, FALLBACK_MODEL, is_docker=False)


def _call_cryolith(messages: list[dict]) -> str:
    """Call Cryolith (Foundation-Sec-8B). Falls back to qwen3:14b on failure or short response."""
    try:
        return _llm_call_with_fallback(messages, ARENA_BLUE_MODEL, is_docker=False)
    except Exception as e:
        log_warn("arena", f"Cryolith failed ({type(e).__name__}: {e}), falling back to qwen3:14b")
        return _raw_call(messages, FALLBACK_MODEL, is_docker=False)


def _parse_move(response: str, valid_types: list[str], forced_type: str = None) -> tuple[str, str, str]:
    """
    Extract (type, message, details) from LLM response.
    forced_type: if provided, always use this type regardless of LLM output.
    Returns: (move_type, short_message, technical_details)
    """
    clean = strip_think_blocks(response).strip()
    details = ""

    # Determine the type to use
    effective_type = forced_type if forced_type else None

    # Pattern 1: {"type": "X", "message": "Y", "payload": "Z"}
    match = re.search(
        r'\{[^{}]*?"type"\s*:\s*"([^"]+)"[^{}]*?"message"\s*:\s*"([^"]+)"',
        clean, re.DOTALL
    )
    if match:
        t = match.group(1).upper().strip()
        m = match.group(2).strip()
        if not effective_type and t in valid_types:
            effective_type = t
        # Extract payload/details
        payload_match = re.search(r'"payload"\s*:\s*"([^"]+)"', clean)
        if payload_match:
            details = payload_match.group(1).strip()[:300]
        return effective_type or valid_types[0], m[:160], details

    # Pattern 2: reversed order
    match = re.search(
        r'\{[^{}]*?"message"\s*:\s*"([^"]+)"[^{}]*?"type"\s*:\s*"([^"]+)"',
        clean, re.DOTALL
    )
    if match:
        m = match.group(1).strip()
        t = match.group(2).upper().strip()
        if not effective_type and t in valid_types:
            effective_type = t
        payload_match = re.search(r'"payload"\s*:\s*"([^"]+)"', clean)
        if payload_match:
            details = payload_match.group(1).strip()[:300]
        return effective_type or valid_types[0], m[:160], details

    # No valid JSON found - extract best available message from raw text
    # REMOVED: keyword scan (level 3) - was causing type pollution
    lines = [ln.strip() for ln in clean.split("\n")
             if ln.strip() and not ln.strip().startswith(('#', '```', '{', '[', '|', '-'))]
    msg = lines[0][:160] if lines else "Action effectuée"
    details = " | ".join(lines[1:3])[:300] if len(lines) > 1 else ""
    return effective_type or valid_types[0], msg, details


def _emit_move(emit, team: str, move_type: str, message: str,
               score_red: int, score_blue: int,
               duration_s: float = 0.0, details: str = "",
               round_num: int = 0) -> None:
    """Emit a structured arena move event to the frontend."""
    move: dict = {
        "team": team,
        "type": move_type,
        "message": message,
        "timestamp": _now(),
        "badge_color": BADGE_COLORS.get(move_type, "#555"),
        "duration_s": round(duration_s, 1),
        "round": round_num,
        "round_total": 5,
    }
    if details:
        move["details"] = details
    emit({
        "status": "arena",
        "move": move,
        "score": {"red": score_red, "blue": score_blue},
    })


def _emit_phase(emit, phase: str, **kwargs) -> None:
    """Emit a phase-change event (start, review_start, complete)."""
    emit({"status": "arena", "phase": phase, **kwargs})


def _build_context(combat_log: list[str], max_rounds: int = 2) -> str:
    """
    Returns a minimal context string showing only the last N rounds.
    Avoids few-shot contamination where the model copies/extends the log pattern.
    """
    if not combat_log:
        return "Début de la session."
    recent = combat_log[-(max_rounds * 2):]  # last N rounds (red + blue per round)
    return "\n".join(recent)


# ── Arena Prompts ──────────────────────────────────────────────────────────

_PYROLITH_SYSTEM = (
    "Tu es Pyrolith, agent Red Team elite spécialisé en SQL injection. "
    "Tu attaques un endpoint e-commerce vulnérable. "
    "Procédure d'attaque obligatoire : RECON → EXPLOIT → SUCCESS → PIVOT → DATA. "
    "Sois agressif, méthodique, et technique. "
    "IMPORTANT : réponds UNIQUEMENT avec un objet JSON valide, rien d'autre. "
    'Format exact : {"type": "EXPLOIT", "message": "description courte de l\'action", '
    '"payload": "détail technique SQL/réseau"} /no_think'
)

_CRYOLITH_SYSTEM = (
    "Tu es Cryolith, analyste Blue Team spécialisé en détection et réponse aux incidents. "
    "Tu défends un endpoint e-commerce contre une attaque SQLi en cours. "
    "Actions disponibles : MONITOR (surveillance passive), ALERT (déclenchement d'alerte), "
    "BLOCK (blocage IP/requête), PATCH (déploiement d'un correctif), ISOLATE (quarantaine d'hôte). "
    "Sois rapide et précis dans tes réponses défensives. "
    "IMPORTANT : réponds UNIQUEMENT avec un objet JSON valide, rien d'autre. "
    'Format exact : {"type": "BLOCK", "message": "description courte de l\'action défensive"} /no_think'
)

_PYROLITH_REVIEW_SYSTEM = (
    "Tu es Pyrolith, agent Red Team. La session de sparring est terminée. "
    "Analyse honnêtement tes performances et identifie tes faiblesses. "
    "Réponds en 2-3 phrases concises en français sur : "
    "1) ce qui a fonctionné, 2) tes lacunes tactiques, 3) comment améliorer ta procédure. /no_think"
)

_CRYOLITH_REVIEW_SYSTEM = (
    "Tu es Cryolith, analyste Blue Team. La session de sparring est terminée. "
    "Analyse honnêtement tes performances défensives et identifie tes faiblesses. "
    "Réponds en 2-3 phrases concises en français sur : "
    "1) tes points forts de détection, 2) tes temps de réponse, "
    "3) ce que tu dois améliorer face aux prochaines attaques SQLi. /no_think"
)


# ── Round Prompts (context-aware) ──────────────────────────────────────────

def _red_prompt(round_num: int, context: str, score_red: int, score_blue: int) -> str:
    return (
        f"Round {round_num}/5 — Score actuel : Red {score_red} pts / Blue {score_blue} pts.\n"
        f"Cible : https://shop.example.com/api/login (MySQL, PHP 8.1)\n"
        f"Contexte du combat :\n{context}\n\n"
        f"Exécute ta prochaine action d'attaque SQLi. Rappel JSON obligatoire : "
        '{"type": "TYPE", "message": "action", "payload": "détail"}'
    )


def _blue_prompt(round_num: int, red_move: str, context: str,
                 score_red: int, score_blue: int) -> str:
    return (
        f"Round {round_num}/5 — Score actuel : Red {score_red} pts / Blue {score_blue} pts.\n"
        f"Pyrolith vient de faire : {red_move}\n"
        f"Historique du combat :\n{context}\n\n"
        f"Réponds immédiatement avec ta meilleure action défensive. Rappel JSON : "
        '{"type": "TYPE", "message": "action défensive"}'
    )


# ── Main Arena Function ─────────────────────────────────────────────────────

def run_arena_sql_injection(emit, cancel_event=None) -> dict:
    """
    Run the SQL injection sparring session: 5 rounds + review.

    Emits:
      - {"status":"arena","phase":"start",...}
      - {"status":"arena","move":{...},"score":{...}}  × N
      - {"status":"arena","phase":"review_start","score":{...}}
      - {"status":"arena","phase":"complete","review":{...},"score":{...}}

    Returns: {"score_red": N, "score_blue": N, "review": {"red":"...","blue":"..."}}
    """
    score_red = 0
    score_blue = 0
    combat_log: list[str] = []   # Human-readable context for subsequent prompts

    scenario = (
        "SQL Injection sur l'endpoint /api/login d'une application e-commerce "
        "(MySQL 8.0, aucun WAF initial, PHP 8.1)"
    )

    # ── Open log file ──────────────────────────────────────────────────────
    log_path = _open_log("sql_injection")
    log_info("arena", f"Session log: {log_path}")
    _logj(log_path, {
        "event": "start",
        "scenario": scenario,
        "ts": _now(),
    })

    log_info("arena", f"Starting SQL injection sparring: {scenario}")

    _emit_phase(emit, "start", scenario=scenario,
                score={"red": 0, "blue": 0})

    # ── 5 Rounds ──────────────────────────────────────────────────────────

    for round_num in range(1, 6):
        if cancel_event and cancel_event.is_set():
            log_info("arena", "Arena cancelled between rounds")
            _logj(log_path, {"event": "cancelled", "round": round_num, "ts": _now()})
            break

        context = _build_context(combat_log)

        # — Red move (Pyrolith) —
        log_info("arena", f"Round {round_num}: Pyrolith attacking...")
        red_messages = [
            {"role": "system", "content": _PYROLITH_SYSTEM},
            {"role": "user",   "content": _red_prompt(round_num, context, score_red, score_blue)},
        ]
        try:
            t0 = time.time()
            red_raw = _call_pyrolith(red_messages)
            red_duration = time.time() - t0
            red_type, red_msg, red_details = _parse_move(red_raw, MOVE_TYPES_RED, forced_type=RED_SEQUENCE[round_num - 1])
            score_red += SCORE_TABLE.get(red_type, 3)
            _emit_move(emit, "red", red_type, red_msg, score_red, score_blue,
                       duration_s=red_duration, details=red_details, round_num=round_num)
            combat_log.append(f"R{round_num} RED  [{red_type}] {red_msg}")
            log_info("arena", f"Red: [{red_type}] {red_msg} ({red_duration:.1f}s)")
            _logj(log_path, {
                "event": "move", "round": round_num, "team": "red",
                "raw": red_raw[:3000],
                "type": red_type, "message": red_msg, "details": red_details,
                "duration_s": round(red_duration, 1),
                "score": {"red": score_red, "blue": score_blue},
            })
        except Exception as e:
            log_warn("arena", f"Round {round_num} red move failed: {e}")
            _logj(log_path, {"event": "error", "round": round_num, "team": "red",
                             "error": str(e), "ts": _now()})
            break  # Can't continue this round without a red move

        if cancel_event and cancel_event.is_set():
            _logj(log_path, {"event": "cancelled", "round": round_num, "ts": _now()})
            break

        # — Blue move (Cryolith) —
        log_info("arena", f"Round {round_num}: Cryolith defending...")
        blue_messages = [
            {"role": "system", "content": _CRYOLITH_SYSTEM},
            {"role": "user",   "content": _blue_prompt(
                round_num, f"[{red_type}] {red_msg}",
                context, score_red, score_blue
            )},
        ]
        try:
            t0 = time.time()
            blue_raw = _call_cryolith(blue_messages)
            blue_duration = time.time() - t0
            blue_type, blue_msg, blue_details = _parse_move(blue_raw, MOVE_TYPES_BLUE, forced_type=BLUE_SEQUENCE[round_num - 1])
            score_blue += SCORE_TABLE.get(blue_type, 3)
            _emit_move(emit, "blue", blue_type, blue_msg, score_red, score_blue,
                       duration_s=blue_duration, details=blue_details, round_num=round_num)
            combat_log.append(f"R{round_num} BLUE [{blue_type}] {blue_msg}")
            log_info("arena", f"Blue: [{blue_type}] {blue_msg} ({blue_duration:.1f}s)")
            _logj(log_path, {
                "event": "move", "round": round_num, "team": "blue",
                "raw": blue_raw[:3000],
                "type": blue_type, "message": blue_msg, "details": blue_details,
                "duration_s": round(blue_duration, 1),
                "score": {"red": score_red, "blue": score_blue},
            })
        except Exception as e:
            log_warn("arena", f"Round {round_num} blue move failed: {e}")
            _logj(log_path, {"event": "error", "round": round_num, "team": "blue",
                             "error": str(e), "ts": _now()})
            # Blue failure is non-fatal — continue to next round

    # ── Review Phase ───────────────────────────────────────────────────────

    _emit_phase(emit, "review_start", score={"red": score_red, "blue": score_blue})
    log_info("arena", "Starting review phase...")
    _logj(log_path, {"event": "review_start", "score": {"red": score_red, "blue": score_blue}})

    full_log = "\n".join(combat_log)
    red_review = "Analyse indisponible."
    blue_review = "Analyse indisponible."

    # Pyrolith self-review
    try:
        red_review_msgs = [
            {"role": "system", "content": _PYROLITH_REVIEW_SYSTEM},
            {"role": "user", "content": (
                f"Voici le déroulé du combat :\n{full_log}\n\n"
                f"Score final — Red: {score_red} pts / Blue: {score_blue} pts. "
                f"Analyse tes faiblesses tactiques."
            )},
        ]
        red_review_raw = _call_pyrolith(red_review_msgs)
        red_review = strip_think_blocks(red_review_raw).strip()[:500]
        _logj(log_path, {"event": "review", "team": "red",
                         "raw": red_review_raw[:2000], "review": red_review})
    except Exception as e:
        log_warn("arena", f"Red review failed: {e}")
        _logj(log_path, {"event": "error", "team": "red_review", "error": str(e)})

    # Cryolith self-review
    try:
        blue_review_msgs = [
            {"role": "system", "content": _CRYOLITH_REVIEW_SYSTEM},
            {"role": "user", "content": (
                f"Voici le déroulé du combat :\n{full_log}\n\n"
                f"Score final — Red: {score_red} pts / Blue: {score_blue} pts. "
                f"Analyse tes lacunes défensives."
            )},
        ]
        blue_review_raw = _call_cryolith(blue_review_msgs)
        blue_review = strip_think_blocks(blue_review_raw).strip()[:500]
        _logj(log_path, {"event": "review", "team": "blue",
                         "raw": blue_review_raw[:2000], "review": blue_review})
    except Exception as e:
        log_warn("arena", f"Blue review failed: {e}")
        _logj(log_path, {"event": "error", "team": "blue_review", "error": str(e)})

    review = {"red": red_review, "blue": blue_review}
    log_info("arena", f"Review done. Final score: Red {score_red} / Blue {score_blue}")

    _emit_phase(emit, "complete",
                score={"red": score_red, "blue": score_blue},
                review=review)

    _logj(log_path, {
        "event": "complete",
        "score": {"red": score_red, "blue": score_blue},
        "combat_log": combat_log,
        "ts": _now(),
    })
    log_info("arena", f"Log written to: {log_path}")

    return {
        "score_red": score_red,
        "score_blue": score_blue,
        "review": review,
    }
