#!/usr/bin/env python3
"""
0Lith — Purple Team IPC Process
================================
Processus séparé pour les simulations Purple Team (Red vs Blue).
Spawné par Tauri comme processus indépendant (comme olith_watcher.py).

Protocole IPC : JSON line-delimited stdin/stdout (même convention que olith_core.py)
  Request:  {"id": "uuid", "command": "...", ...params}
  Response: {"id": "uuid", "status": "ok|error", ...data}
  Stream:   {"id": "uuid", "status": "purple", ...event_data}  (non-résolvant)

Commandes:
  purple_generate_scenario  — Génère un scénario depuis seed + difficulty
  purple_start_match        — Lance un match (HMAC token requis)
  purple_match_status       — Statut du match en cours
  purple_match_result       — Résultat du dernier match terminé
  purple_stop_match         — Annule le match en cours

Sécurité:
  - purple_start_match DOIT contenir un champ sparring_token valide (HMAC-SHA256)
  - Clé lue depuis ~/.0lith/sparring.key ou env var OLITH_SPARRING_SECRET
  - Token attendu : HMAC-SHA256(secret, "olith-sparring").hexdigest()
  - Un seul match à la fois (threading.Lock)
  - Timeout global 60 min par match (asyncio.wait_for)
  - Monolith ne peut pas déclencher un match — seul le frontend (utilisateur) le peut

Dev flags (env vars):
  PURPLE_SKIP_TOKEN=1   — Bypass HMAC check
  PURPLE_SKIP_GVISOR=1  — Bypass gVisor check
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import io
import json
import logging
import os
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

# Force UTF-8 sur stdout/stdin (Windows utilise cp1252 par défaut)
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.stdin  = io.TextIOWrapper(sys.stdin.buffer,  encoding="utf-8")

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [purple] %(levelname)s %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("olith.purple")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SPARRING_KEY_PATH   = Path.home() / ".0lith" / "sparring.key"
SPARRING_SECRET_ENV = "OLITH_SPARRING_SECRET"
MATCH_TIMEOUT_S     = 3600  # 60 minutes

from config import (
    OLLAMA_URL, PYROLITH_URL,
    PYROLITH_MODEL, CRYOLITH_MODEL, FALLBACK_MODEL,
)
CRYOLITH_URL = OLLAMA_URL  # Blue team uses local Ollama, same as OLLAMA_URL

# Dev flags — bypass safety checks without touching production code
SKIP_GVISOR = os.environ.get("PURPLE_SKIP_GVISOR", "0") == "1"
SKIP_TOKEN  = os.environ.get("PURPLE_SKIP_TOKEN",  "0") == "1"

# ---------------------------------------------------------------------------
# Thread-safe stdout
# ---------------------------------------------------------------------------

_stdout_lock = threading.Lock()


def _print_json(data: dict) -> None:
    """Écrit une ligne JSON sur stdout de manière thread-safe."""
    with _stdout_lock:
        print(json.dumps(data, ensure_ascii=False), flush=True)


# ---------------------------------------------------------------------------
# LLM callables (async — attendus par MatchProtocol)
# ---------------------------------------------------------------------------

async def _call_ollama(
    base_url: str, model: str, prompt: str, timeout: int = 300
) -> str:
    """Appelle un modèle Ollama via /api/chat (non-streaming).

    Args:
        base_url: URL de base Ollama (ex: http://localhost:11434).
        model: Nom du modèle.
        prompt: Prompt utilisateur.
        timeout: Timeout total en secondes.

    Returns:
        Réponse textuelle du modèle.

    Raises:
        Exception propagée pour le fallback.
    """
    import aiohttp

    payload = {
        "model":    model,
        "messages": [{"role": "user", "content": prompt}],
        "stream":   False,
        "options":  {"num_ctx": 2048},
    }
    async with aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=timeout)
    ) as session:
        async with session.post(f"{base_url}/api/chat", json=payload) as resp:
            resp.raise_for_status()
            data = await resp.json()
            return data.get("message", {}).get("content", "")


async def _call_with_fallback(
    base_url: str, primary: str, prompt: str, timeout: int = 300
) -> str:
    """Appelle primary; auto-fallback qwen3:14b si réponse < 20 chars ou erreur."""
    try:
        response = await _call_ollama(base_url, primary, prompt, timeout)
        if len(response.strip()) >= 20:
            return response
        logger.warning(
            f"Model {primary} returned short response "
            f"({len(response.strip())} chars) — falling back"
        )
    except Exception as e:
        logger.warning(
            f"Primary model {primary} failed: {type(e).__name__} — "
            f"falling back to {FALLBACK_MODEL}"
        )

    return await _call_ollama(
        "http://localhost:11434", FALLBACK_MODEL, prompt, timeout=180
    )


async def call_pyrolith(prompt: str) -> str:
    """Callable async Red Team (Pyrolith → DeepHat)."""
    return await _call_with_fallback(PYROLITH_URL, PYROLITH_MODEL, prompt, timeout=300)


async def call_cryolith(prompt: str) -> str:
    """Callable async Blue Team (Cryolith → Foundation-Sec)."""
    return await _call_with_fallback(CRYOLITH_URL, CRYOLITH_MODEL, prompt, timeout=300)


# ---------------------------------------------------------------------------
# HMAC token validation
# ---------------------------------------------------------------------------

def _load_sparring_secret() -> str | None:
    """Charge le secret depuis env var OLITH_SPARRING_SECRET ou ~/.0lith/sparring.key."""
    secret = os.environ.get(SPARRING_SECRET_ENV, "")
    if secret:
        return secret
    if SPARRING_KEY_PATH.exists():
        return SPARRING_KEY_PATH.read_text(encoding="utf-8").strip()
    return None


def _validate_sparring_token(token: str) -> tuple[bool, str]:
    """Valide le token HMAC-SHA256 du frontend.

    Token attendu : HMAC-SHA256(secret, b"olith-sparring").hexdigest()

    Args:
        token: Token fourni dans la requête IPC.

    Returns:
        (valid, reason)
    """
    if SKIP_TOKEN:
        return True, "Token check skipped (PURPLE_SKIP_TOKEN=1 — dev mode)"

    if not token:
        return False, "Missing sparring_token in request"

    secret = _load_sparring_secret()
    if not secret:
        return False, (
            f"Sparring secret not found. "
            f"Set {SPARRING_SECRET_ENV} env var or create {SPARRING_KEY_PATH}"
        )

    expected = hmac.new(
        secret.encode("utf-8"),
        b"olith-sparring",
        hashlib.sha256,
    ).hexdigest()

    if hmac.compare_digest(token, expected):
        return True, "Token valid"
    return False, "Invalid sparring token — HMAC mismatch"


# ---------------------------------------------------------------------------
# Internal match state
# ---------------------------------------------------------------------------

@dataclass
class _MatchState:
    """État interne d'un match en cours ou terminé."""
    match_id:      str
    scenario_seed: int
    difficulty:    str
    phase:         str         = "setup"
    rounds_done:   int         = 0
    started_at:    float       = field(default_factory=time.monotonic)
    finished:      bool        = False
    error:         str | None  = None
    result:        dict | None = None  # MatchResult.to_dict() une fois terminé


# ---------------------------------------------------------------------------
# PurpleTeamProcess
# ---------------------------------------------------------------------------

class PurpleTeamProcess:
    """Processus Purple Team — boucle IPC synchrone + orchestration async.

    Design:
    - Boucle IPC synchrone (for line in sys.stdin), identique à olith_core.py
    - Match exécuté dans un thread daemon via asyncio.run()
    - Un seul match à la fois (threading.Lock — acquire non-bloquant)
    - threading.Event passé directement à MatchProtocol comme cancel_event
      (MatchProtocol n'utilise que .is_set(), compatible threading.Event)
    - Timeout global 60 min via asyncio.wait_for dans la coroutine du match
    - emit() est thread-safe via _stdout_lock
    """

    def __init__(self) -> None:
        self._match_lock     = threading.Lock()   # Mutex single-match
        self._cancel_event   = threading.Event()  # Annulation du match courant
        self._match_state:   _MatchState | None = None
        self._match_thread:  threading.Thread | None = None

    # ------------------------------------------------------------------
    # IPC dispatch
    # ------------------------------------------------------------------

    def handle_request(self, request: dict, emit: Callable) -> dict:
        """Dispatche une requête IPC vers le handler correspondant.

        Args:
            request: Dict avec au minimum "id" et "command".
            emit: Callable(data: dict) pour les événements streamés.

        Returns:
            Dict de réponse finale {id, status, ...data}.
        """
        req_id  = request.get("id", str(uuid.uuid4()))
        command = request.get("command", "")

        handlers: dict[str, Callable] = {
            "purple_generate_scenario": self.cmd_generate_scenario,
            "purple_start_match":       self.cmd_start_match,
            "purple_match_status":      self.cmd_match_status,
            "purple_match_result":      self.cmd_match_result,
            "purple_stop_match":        self.cmd_stop_match,
        }

        handler = handlers.get(command)
        if handler is None:
            return {
                "id":      req_id,
                "status":  "error",
                "message": (
                    f"Unknown command: {command!r}. "
                    f"Valid: {sorted(handlers)}"
                ),
            }

        try:
            data = handler(request, emit=emit, req_id=req_id)
            return {"id": req_id, "status": "ok", **data}
        except Exception as e:
            logger.exception(f"Command {command!r} failed: {e}")
            return {
                "id":      req_id,
                "status":  "error",
                "message": f"{type(e).__name__}: {e}",
            }

    # ------------------------------------------------------------------
    # Command handlers
    # ------------------------------------------------------------------

    def cmd_generate_scenario(
        self, request: dict, *, emit: Callable, req_id: str
    ) -> dict:
        """Génère un scénario déterministe (seed + difficulty).

        Request params:
            seed (int, default 42): Graine de génération.
            difficulty (str, default "medium"): "easy" | "medium" | "hard".
            control (bool, default False): Génère un scénario de contrôle.

        Returns:
            {"scenario": {seed, difficulty, services, objective,
                          mitre_techniques, control_scenario}}
        """
        from purple.scenario_generator import ScenarioGenerator

        seed       = int(request.get("seed", 42))
        difficulty = str(request.get("difficulty", "medium"))
        control    = bool(request.get("control", False))

        gen = ScenarioGenerator()
        config = (
            gen.generate_control(seed=seed, difficulty=difficulty)
            if control
            else gen.generate(seed=seed, difficulty=difficulty)
        )

        return {
            "scenario": {
                "seed":             config.seed,
                "difficulty":       config.difficulty,
                "services":         [s.service_name for s in config.services],
                "objective":        config.objective,
                "mitre_techniques": sorted(config.mitre_techniques),
                "control_scenario": config.control_scenario,
            }
        }

    def cmd_start_match(
        self, request: dict, *, emit: Callable, req_id: str
    ) -> dict:
        """Lance un match Purple Team dans un thread séparé.

        Valide le token HMAC, exécute les safety checks, puis démarre le match.
        Le match streame des events via emit() pendant tout son déroulement.

        Request params:
            sparring_token (str): HMAC-SHA256 requis sauf PURPLE_SKIP_TOKEN=1.
            seed (int, default 42): Seed du scénario.
            difficulty (str, default "medium"): "easy" | "medium" | "hard".
            skip_safety (bool, default False): Bypass safety checks (dev uniquement).

        Returns:
            {"match_id", "scenario_seed", "difficulty", "message"}

        Raises:
            ValueError: Token invalide.
            RuntimeError: Match déjà en cours, ou safety checks échoués.
        """
        # 1 — Validate HMAC token
        token = str(request.get("sparring_token", ""))
        valid, reason = _validate_sparring_token(token)
        if not valid:
            raise ValueError(f"Sparring token rejected: {reason}")
        logger.info(f"Sparring token: {reason}")

        # 2 — Single-match mutex (non-blocking)
        if not self._match_lock.acquire(blocking=False):
            raise RuntimeError(
                "A match is already running. "
                "Stop it first with purple_stop_match."
            )

        seed        = int(request.get("seed", 42))
        difficulty  = str(request.get("difficulty", "medium"))
        skip_safety = bool(request.get("skip_safety", False))

        try:
            # 3 — Safety checks (token already validated above)
            if not skip_safety:
                from purple.safety_checks import SafetyChecker
                checker = SafetyChecker(skip_gvisor=SKIP_GVISOR, skip_token=True)
                ok, results = checker.run_all()
                if not ok:
                    failures = [
                        f"{r.name}: {r.reason}"
                        for r in results
                        if not r.passed and not r.warning_only
                    ]
                    raise RuntimeError(
                        f"Pre-match safety checks failed: {'; '.join(failures)}"
                    )
                logger.info("Pre-match safety checks passed")

            # 4 — Generate scenario
            from purple.scenario_generator import ScenarioGenerator
            config   = ScenarioGenerator().generate(seed=seed, difficulty=difficulty)
            match_id = str(uuid.uuid4())

            # 5 — Reset cancel + init state
            self._cancel_event.clear()
            self._match_state = _MatchState(
                match_id=match_id,
                scenario_seed=seed,
                difficulty=difficulty,
            )

            # 6 — Start match thread
            self._match_thread = threading.Thread(
                target=self._run_match_thread,
                args=(config, match_id, emit, req_id),
                daemon=True,
                name=f"purple-{match_id[:8]}",
            )
            self._match_thread.start()

            logger.info(
                f"Match {match_id} started (seed={seed}, difficulty={difficulty})"
            )
            return {
                "match_id":      match_id,
                "scenario_seed": seed,
                "difficulty":    difficulty,
                "message": (
                    "Match started. Round events will be streamed as "
                    "status='purple' on the same request id."
                ),
            }

        except Exception:
            self._match_lock.release()
            raise

    def cmd_match_status(
        self, request: dict, *, emit: Callable, req_id: str
    ) -> dict:
        """Retourne le statut du match en cours.

        Returns:
            {"running", "match_id", "phase", "rounds_done", "elapsed_s",
             "finished", "error"}
        """
        state = self._match_state
        if state is None:
            return {"running": False, "message": "No match has been started yet"}

        elapsed = time.monotonic() - state.started_at
        return {
            "running":     not state.finished,
            "match_id":    state.match_id,
            "phase":       state.phase,
            "rounds_done": state.rounds_done,
            "elapsed_s":   round(elapsed, 1),
            "finished":    state.finished,
            "error":       state.error,
        }

    def cmd_match_result(
        self, request: dict, *, emit: Callable, req_id: str
    ) -> dict:
        """Retourne le résultat du dernier match terminé.

        Returns:
            {"available": True, "result": MatchResult.to_dict()} si terminé,
            {"available": False, "message": ...} sinon.
        """
        state = self._match_state
        if state is None:
            return {"available": False, "message": "No match has been run yet"}
        if not state.finished:
            return {
                "available":   False,
                "message":     "Match still in progress",
                "phase":       state.phase,
                "rounds_done": state.rounds_done,
            }
        if state.result is None:
            return {
                "available": False,
                "message":   "Match finished without result (crashed before finalize)",
                "error":     state.error,
            }
        return {"available": True, "result": state.result}

    def cmd_stop_match(
        self, request: dict, *, emit: Callable, req_id: str
    ) -> dict:
        """Annule le match en cours.

        Envoie le signal d'annulation — le match s'arrête proprement
        après le round courant (pas d'interruption brutale).

        Returns:
            {"stopped": True|False, "match_id"?, "message"}
        """
        state = self._match_state
        if state is None or state.finished:
            return {"stopped": False, "message": "No active match to stop"}

        self._cancel_event.set()
        logger.info(f"Stop signal sent for match {state.match_id}")
        return {
            "stopped":  True,
            "match_id": state.match_id,
            "message": (
                "Cancellation signal sent. "
                "Match will stop cleanly after the current round."
            ),
        }

    # ------------------------------------------------------------------
    # Match thread + async coroutine
    # ------------------------------------------------------------------

    def _run_match_thread(
        self,
        scenario: Any,
        match_id: str,
        emit: Callable,
        req_id: str,
    ) -> None:
        """Exécute le match dans un thread daemon via asyncio.run().

        Libère self._match_lock dans le bloc finally, quel que soit le résultat.
        """
        try:
            asyncio.run(
                self._run_match_async(scenario, match_id, emit, req_id)
            )
        except Exception as e:
            logger.exception(f"Match thread {match_id} crashed: {e}")
            if self._match_state:
                self._match_state.finished = True
                self._match_state.error    = f"{type(e).__name__}: {e}"
            emit({
                "id":       req_id,
                "status":   "purple",
                "event":    "match_error",
                "match_id": match_id,
                "error":    str(e),
            })
        finally:
            try:
                self._match_lock.release()
            except RuntimeError:
                pass  # Already released (shouldn't happen)

    async def _run_match_async(
        self,
        scenario: Any,
        match_id: str,
        emit: Callable,
        req_id: str,
    ) -> None:
        """Coroutine principale du match, wrappée dans un timeout global 60 min.

        Notes:
        - threading.Event est passé directement comme cancel_event à MatchProtocol.
          MatchProtocol n'utilise que .is_set(), ce qui est compatible.
        - CyberRange est utilisé via async context manager (deploy + teardown auto).
        - DPO pairs sont exportées dans ~/.0lith/dpo_data/ après le match.
        """
        from purple.cyber_range import CyberRange
        from purple.match_protocol import MatchProtocol
        from purple.scorer import Scorer
        from purple.dpo_exporter import DPOExporter

        async def _match_body() -> None:
            async with CyberRange(scenario) as cyber_range:
                # Attendre que les conteneurs soient sains
                try:
                    await asyncio.wait_for(
                        cyber_range.wait_healthy(timeout=60), timeout=90
                    )
                except asyncio.TimeoutError:
                    raise RuntimeError(
                        "Cyber Range did not become healthy within 90s"
                    )

                protocol = MatchProtocol(
                    scenario=scenario,
                    cyber_range=cyber_range,
                    red_llm=call_pyrolith,
                    blue_llm=call_cryolith,
                    cancel_event=self._cancel_event,  # threading.Event (.is_set() only)
                )

                emit({
                    "id":            req_id,
                    "status":        "purple",
                    "event":         "match_started",
                    "match_id":      match_id,
                    "scenario_seed": scenario.seed,
                    "difficulty":    scenario.difficulty,
                })

                # Stream des événements round-by-round
                async for event in protocol.run():
                    # Mise à jour de l'état pour les status queries
                    if self._match_state:
                        phase_val = event.get("phase")
                        if phase_val:
                            self._match_state.phase = phase_val
                        if event.get("event") == "round_complete":
                            self._match_state.rounds_done += 1

                    emit({
                        "id":       req_id,
                        "status":   "purple",
                        "match_id": match_id,
                        **event,
                    })

                    if self._cancel_event.is_set():
                        logger.info(f"Match {match_id} cancelled by user request")
                        break

                # Finalisation : scoring + export DPO
                result = await protocol.finalize(
                    scorer=Scorer(),
                    exporter=DPOExporter(),
                )

                if self._match_state:
                    self._match_state.result   = result.to_dict()
                    self._match_state.phase    = result.phase_reached.value
                    self._match_state.finished = True

                emit({
                    "id":       req_id,
                    "status":   "purple",
                    "event":    "match_complete",
                    "match_id": match_id,
                    "result":   result.to_dict(),
                })
                logger.info(
                    f"Match {match_id} complete — winner={result.winner}, "
                    f"dpo_pairs={len(result.dpo_pairs)}, "
                    f"duration={result.duration_seconds:.0f}s"
                )

                # Export paires DPO
                if result.dpo_pairs:
                    dpo_dir = Path.home() / ".0lith" / "dpo_data"
                    dpo_dir.mkdir(parents=True, exist_ok=True)
                    exporter = DPOExporter()
                    exported = exporter.export_to_jsonl(result.dpo_pairs, dpo_dir)
                    logger.info(
                        f"DPO export: {len(result.dpo_pairs)} pairs → {exported}"
                    )

        try:
            await asyncio.wait_for(_match_body(), timeout=MATCH_TIMEOUT_S)
        except asyncio.TimeoutError:
            logger.error(
                f"Match {match_id} exceeded {MATCH_TIMEOUT_S // 60}min timeout"
            )
            if self._match_state:
                self._match_state.finished = True
                self._match_state.error    = "Match timed out after 60 minutes"
            emit({
                "id":       req_id,
                "status":   "purple",
                "event":    "match_timeout",
                "match_id": match_id,
                "error":    "Match timed out after 60 minutes",
            })
        finally:
            # Assure que le cancel event est set pour libérer d'éventuels waiters
            self._cancel_event.set()


# ============================================================================
# MAIN — Boucle IPC stdin/stdout
# ============================================================================

def main() -> None:
    """Point d'entrée du processus Purple Team.

    Même structure que olith_core.py : boucle synchrone sur sys.stdin,
    une ligne JSON par requête, une ligne JSON par réponse.
    Les événements streamés (status="purple") sont émis en parallèle
    depuis le thread du match via emit().
    """
    process = PurpleTeamProcess()

    def emit(data: dict) -> None:
        """Émet un event non-résolvant (streaming) de manière thread-safe."""
        _print_json(data)

    logger.info("0Lith Purple Team process ready — listening for IPC commands")

    try:
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue

            try:
                request = json.loads(line)
            except json.JSONDecodeError as e:
                _print_json({"status": "error", "message": f"Invalid JSON: {e}"})
                continue

            response = process.handle_request(request, emit=emit)
            _print_json(response)

    except KeyboardInterrupt:
        pass
    finally:
        logger.info("Purple Team process shutting down")


if __name__ == "__main__":
    main()
