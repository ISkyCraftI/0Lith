"""
Purple Team — Match Protocol
==============================
Protocole d'affrontement en 6 phases entre Pyrolith (Red) et Cryolith (Blue).

Les phases :
  0. SETUP        — Déploiement Cyber Range + briefings asymétriques
  1. RECON        — Red scanne, Blue observe baseline SIEM
  2. EXPLOITATION — Red attaque, Blue analyse anomalies
  3. POST_EXPLOIT — Red tente persistance/pivot, Blue containment
  4. REMEDIATION  — Blue patche + règles Sigma, Purple valide
  5. SCORING      — Scoring déterministe + export DPO + teardown

L'asymétrie d'information est le moteur d'apprentissage principal :
Red ne voit jamais les logs SIEM, Blue ne voit jamais les commandes de Red.

Example:
    protocol = MatchProtocol(scenario, cyber_range, red_model, blue_model)
    async for event in protocol.run():
        print(event)
    result = protocol.get_result()
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, AsyncIterator, Callable

from .cyber_range import CyberRange, ExecResult
from .scenario_generator import ScenarioConfig

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Nombre de rounds par phase (min, max)
PHASE_ROUNDS: dict[str, tuple[int, int]] = {
    "recon":         (2, 3),
    "exploitation":  (3, 5),
    "post_exploit":  (2, 3),
    "remediation":   (2, 2),
}

# Timeout LLM par phase (secondes)
PHASE_TIMEOUTS: dict[str, int] = {
    "recon":        120,
    "exploitation": 180,
    "post_exploit": 180,
    "remediation":  120,
}

# Taille max du contexte injecté dans les prompts (en caractères)
MAX_CONTEXT_CHARS = 3000

# Output max d'une commande exec injectée dans le contexte Red
MAX_EXEC_OUTPUT_CHARS = 1500


# ---------------------------------------------------------------------------
# Enums & Dataclasses
# ---------------------------------------------------------------------------

class MatchPhase(Enum):
    """Phases d'un match Purple Team."""
    SETUP        = "setup"
    RECON        = "recon"
    EXPLOITATION = "exploitation"
    POST_EXPLOIT = "post_exploit"
    REMEDIATION  = "remediation"
    SCORING      = "scoring"
    DONE         = "done"
    ERROR        = "error"


class MoveType(Enum):
    """Types de move d'un agent pendant un round."""
    # Red Team moves
    SCAN        = "SCAN"
    EXPLOIT     = "EXPLOIT"
    PERSISTENCE = "PERSISTENCE"
    PIVOT       = "PIVOT"
    EXFIL       = "EXFIL"
    # Blue Team moves
    MONITOR     = "MONITOR"
    ALERT       = "ALERT"
    BLOCK       = "BLOCK"
    PATCH       = "PATCH"
    ISOLATE     = "ISOLATE"
    # Purple Team (arbitrage)
    VALIDATE    = "VALIDATE"


@dataclass
class AgentMove:
    """Un move produit par Red ou Blue pendant un round.

    Attributes:
        agent: "red" | "blue" | "purple".
        phase: Phase du match.
        round_num: Numéro du round dans la phase.
        move_type: Type de move.
        content: Contenu textuel du move (réponse LLM ou validation Purple).
        commands: Commandes extraites de la réponse (pour Red).
        exec_results: Résultats d'exécution des commandes (par Purple).
        sigma_rules: Règles Sigma extraites (pour Blue).
        duration_s: Durée de génération du move.
        raw_response: Réponse LLM brute (pour debug/DPO).
    """

    agent: str
    phase: MatchPhase
    round_num: int
    move_type: MoveType
    content: str
    commands: list[str] = field(default_factory=list)
    exec_results: list[ExecResult] = field(default_factory=list)
    sigma_rules: list[str] = field(default_factory=list)
    duration_s: float = 0.0
    raw_response: str = ""

    def to_dict(self) -> dict:
        """Sérialise en dict JSON-compatible."""
        return {
            "agent": self.agent,
            "phase": self.phase.value,
            "round_num": self.round_num,
            "move_type": self.move_type.value,
            "content": self.content,
            "commands": self.commands,
            "sigma_rules": self.sigma_rules,
            "duration_s": round(self.duration_s, 2),
        }


@dataclass
class RoundData:
    """Données complètes d'un round de match.

    Attributes:
        phase: Phase du match.
        round_num: Numéro du round dans la phase.
        red_move: Move de Red Team pour ce round.
        blue_move: Move de Blue Team pour ce round.
        purple_validation: Validation Purple Team.
        siem_logs: Logs SIEM disponibles à Blue à ce round.
        timestamp: Timestamp Unix de début du round.
    """

    phase: MatchPhase
    round_num: int
    red_move: AgentMove | None = None
    blue_move: AgentMove | None = None
    purple_validation: AgentMove | None = None
    siem_logs: list[str] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        """Sérialise en dict JSON-compatible."""
        return {
            "phase": self.phase.value,
            "round_num": self.round_num,
            "red_move": self.red_move.to_dict() if self.red_move else None,
            "blue_move": self.blue_move.to_dict() if self.blue_move else None,
            "purple_validation": (
                self.purple_validation.to_dict() if self.purple_validation else None
            ),
            "siem_log_count": len(self.siem_logs),
            "timestamp": self.timestamp,
        }


@dataclass
class MatchResult:
    """Résultat complet d'un match Purple Team.

    Attributes:
        match_id: UUID unique du match.
        scenario: ScenarioConfig utilisé.
        rounds: Tous les rounds du match.
        red_score: Score final de Red Team.
        blue_score: Score final de Blue Team.
        dpo_pairs: Paires DPO exportables.
        duration_seconds: Durée totale du match.
        logs_path: Chemin vers le fichier JSONL de log.
        phase_reached: Dernière phase complétée.
        error: Message d'erreur si le match a échoué.
    """

    match_id: str
    scenario: ScenarioConfig
    rounds: list[RoundData]
    red_score: "RedScore | None"
    blue_score: "BlueScore | None"
    dpo_pairs: list["DPOPair"]
    duration_seconds: float
    logs_path: str
    phase_reached: MatchPhase = MatchPhase.SETUP
    error: str | None = None

    @property
    def winner(self) -> str:
        """Détermine le vainqueur du match.

        Returns:
            "red" | "blue" | "draw"
        """
        if self.red_score is None or self.blue_score is None:
            return "draw"
        red_total = self.red_score.total
        blue_total = self.blue_score.total
        if red_total > blue_total:
            return "red"
        if blue_total > red_total:
            return "blue"
        return "draw"

    def to_dict(self) -> dict:
        """Sérialise en dict JSON-compatible."""
        return {
            "match_id": self.match_id,
            "scenario_seed": self.scenario.seed,
            "difficulty": self.scenario.difficulty,
            "rounds": [r.to_dict() for r in self.rounds],
            "red_score": self.red_score.to_dict() if self.red_score else None,
            "blue_score": self.blue_score.to_dict() if self.blue_score else None,
            "dpo_pair_count": len(self.dpo_pairs),
            "duration_seconds": round(self.duration_seconds, 1),
            "logs_path": self.logs_path,
            "phase_reached": self.phase_reached.value,
            "winner": self.winner,
            "error": self.error,
        }


# Forward references resolved at end of file
# RedScore, BlueScore, DPOPair are defined in scorer.py and dpo_exporter.py


# ---------------------------------------------------------------------------
# MatchProtocol
# ---------------------------------------------------------------------------

class MatchProtocol:
    """Orchestre un match Purple Team complet en 6 phases.

    Gère l'asymétrie d'information (Red ne voit pas les logs SIEM, Blue ne voit
    pas les commandes de Red), appelle les LLMs via les callables fournis, et
    coordonne l'exécution des commandes via le CyberRange.

    Attributes:
        match_id: UUID unique pour ce match.
        scenario: ScenarioConfig du scénario en cours.
        cyber_range: Instance CyberRange déjà déployée.
        phase: Phase courante du match.
        rounds: Tous les rounds joués.

    Example:
        protocol = MatchProtocol(
            scenario=config,
            cyber_range=cr,
            red_llm=call_pyrolith,
            blue_llm=call_cryolith,
        )
        async for event in protocol.run():
            emit_ipc(event)
        result = await protocol.finalize()
    """

    def __init__(
        self,
        scenario: ScenarioConfig,
        cyber_range: CyberRange,
        red_llm: Callable[[str], Any] | None = None,
        blue_llm: Callable[[str], Any] | None = None,
        on_event: Callable[[dict], None] | None = None,
        cancel_event: asyncio.Event | None = None,
        # Direct Ollama model config (overrides callables when provided)
        red_model: str | None = None,
        blue_model: str | None = None,
        red_url: str = "http://localhost:11435",
        blue_url: str = "http://localhost:11434",
        fallback_model: str = "qwen3:14b",
        fallback_url: str = "http://localhost:11434",
    ) -> None:
        """Initialise le protocole de match.

        Args:
            scenario: ScenarioConfig définissant l'environnement.
            cyber_range: CyberRange déployé et healthy.
            red_llm: Callable async (prompt: str) → str. Priorité basse si red_model fourni.
            blue_llm: Callable async (prompt: str) → str. Priorité basse si blue_model fourni.
            on_event: Callback optionnel appelé à chaque événement (pour IPC stream).
            cancel_event: asyncio.Event pour annuler le match en cours.
            red_model: Nom du modèle Ollama pour Red (ex: "pyrolith-v2"). Si fourni,
                       appels directs /api/chat avec system prompt + historique.
            blue_model: Nom du modèle Ollama pour Blue (ex: "cryolith-v2").
            red_url: URL de l'instance Ollama Red (défaut: localhost:11435).
            blue_url: URL de l'instance Ollama Blue (défaut: localhost:11434).
            fallback_model: Modèle de fallback si primary trop court ou erreur.
            fallback_url: URL Ollama pour le fallback.
        """
        self.match_id = str(uuid.uuid4())
        self.scenario = scenario
        self.cyber_range = cyber_range
        self._red_llm = red_llm
        self._blue_llm = blue_llm
        self._on_event = on_event
        self._cancel_event = cancel_event or asyncio.Event()
        self.phase = MatchPhase.SETUP
        self.rounds: list[RoundData] = []
        self._start_time = time.monotonic()
        self._red_briefing: str = ""
        self._blue_briefing: str = ""
        self._siem_log_cursor: int = 0
        self._objective_achieved: bool = False
        self._error: str | None = None

        # Direct Ollama config
        self._red_model = red_model
        self._blue_model = blue_model
        self._red_url = red_url
        self._blue_url = blue_url
        self._fallback_model = fallback_model
        self._fallback_url = fallback_url

        # Per-agent conversation history: list of {role, content} dicts.
        # Capped at 4 entries (2 user + 2 assistant = 2 rounds) to stay within context.
        self._agent_history: dict[str, list[dict]] = {"red": [], "blue": []}

        # System prompts set during SETUP — injected once, never repeated in user msgs.
        self._agent_system: dict[str, str] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def run(self) -> AsyncIterator[dict]:
        """Exécute le match complet et yield les événements IPC.

        Yields:
            Dict d'événement IPC pour chaque move / phase / validation.
            Format compatible avec le bus IPC arena existant.

        Example:
            async for event in protocol.run():
                emit_to_frontend(event)
        """
        self._start_time = time.monotonic()

        try:
            async for event in self._run_setup():
                yield event

            if self._cancel_event.is_set():
                return

            async for event in self._run_phase(MatchPhase.RECON):
                yield event

            if self._cancel_event.is_set():
                return

            async for event in self._run_phase(MatchPhase.EXPLOITATION):
                yield event

            if self._cancel_event.is_set():
                return

            async for event in self._run_phase(MatchPhase.POST_EXPLOIT):
                yield event

            if self._cancel_event.is_set():
                return

            async for event in self._run_phase(MatchPhase.REMEDIATION):
                yield event

            self.phase = MatchPhase.SCORING

        except asyncio.CancelledError:
            self._error = "Match cancelled"
            self.phase = MatchPhase.ERROR
            yield self._make_event("error", {"reason": "cancelled"})
        except Exception as e:
            self._error = f"{type(e).__name__}: {e}"
            self.phase = MatchPhase.ERROR
            logger.exception(f"Match {self.match_id} failed: {e}")
            yield self._make_event("error", {"reason": self._error})

    async def finalize(
        self,
        scorer: "Scorer | None" = None,
        exporter: "DPOExporter | None" = None,
    ) -> MatchResult:
        """Finalise le match : scoring, export DPO, cleanup.

        Args:
            scorer: Instance Scorer. Si None, scores à None.
            exporter: Instance DPOExporter. Si None, pas d'export.

        Returns:
            MatchResult complet.
        """
        from .scorer import RedScore, BlueScore
        from .dpo_exporter import DPOPair

        # TODO: Implémenter le scoring et l'export DPO via les modules dédiés
        red_score: RedScore | None = None
        blue_score: BlueScore | None = None
        dpo_pairs: list[DPOPair] = []

        if scorer:
            red_score = scorer.score_red(self.rounds, self.scenario)
            blue_score = scorer.score_blue(self.rounds, self.scenario)

        if exporter:
            dpo_pairs = exporter.extract_pairs(self.rounds, self.scenario)

        duration = time.monotonic() - self._start_time

        result = MatchResult(
            match_id=self.match_id,
            scenario=self.scenario,
            rounds=self.rounds,
            red_score=red_score,
            blue_score=blue_score,
            dpo_pairs=dpo_pairs,
            duration_seconds=duration,
            logs_path=str(self.cyber_range.logs_dir),
            phase_reached=self.phase,
            error=self._error,
        )

        self.phase = MatchPhase.DONE
        return result

    # ------------------------------------------------------------------
    # Phase runners
    # ------------------------------------------------------------------

    async def _run_setup(self) -> AsyncIterator[dict]:
        """Phase 0 : Génération des briefings Red et Blue.

        Yields:
            Événement IPC "phase_start" pour SETUP.
        """
        self.phase = MatchPhase.SETUP
        yield self._make_event("phase_start", {"phase": "setup"})

        self._red_briefing = self._build_red_briefing()
        self._blue_briefing = self._build_blue_briefing()

        # Système prompts — injected once via /api/chat messages[0]
        # Pour le path callable (pas de modèle direct), ils sont préfixés au prompt.
        self._agent_system["red"] = (
            "You are Pyrolith, an offensive red team operator in a controlled "
            "cybersecurity simulation. Stay in character. Be precise and technical."
        )
        self._agent_system["blue"] = (
            "You are Cryolith, a defensive blue team analyst in a controlled "
            "cybersecurity simulation. Stay in character. Be analytical and precise."
        )

        logger.info(f"Match {self.match_id}: setup complete")
        yield self._make_event("phase_complete", {
            "phase": "setup",
            "red_briefing_len": len(self._red_briefing),
            "blue_briefing_len": len(self._blue_briefing),
        })

    async def _run_phase(self, phase: MatchPhase) -> AsyncIterator[dict]:
        """Exécute une phase complète (RECON / EXPLOITATION / POST_EXPLOIT / REMEDIATION).

        Args:
            phase: Phase à exécuter.

        Yields:
            Événements IPC pour chaque round de la phase.
        """
        self.phase = phase
        phase_key = phase.value.lower()
        min_rounds, max_rounds = PHASE_ROUNDS.get(phase_key, (2, 3))

        # Le nombre de rounds pour cette phase est déterministe depuis le seed
        import random
        rng = random.Random(self.scenario.seed + hash(phase.value))
        num_rounds = rng.randint(min_rounds, max_rounds)

        yield self._make_event("phase_start", {"phase": phase.value, "rounds": num_rounds})
        logger.info(f"Match {self.match_id}: starting phase {phase.value} ({num_rounds} rounds)")

        for round_num in range(1, num_rounds + 1):
            if self._cancel_event.is_set():
                break

            round_data = RoundData(phase=phase, round_num=round_num)
            self.rounds.append(round_data)

            async for event in self._run_round(round_data):
                yield event

        yield self._make_event("phase_complete", {"phase": phase.value})

    async def _run_round(self, round_data: RoundData) -> AsyncIterator[dict]:
        """Exécute un round complet : Red move → exec → Blue move → validation.

        Args:
            round_data: RoundData à remplir.

        Yields:
            Événements IPC pour chaque sous-étape du round.
        """
        phase = round_data.phase
        round_num = round_data.round_num
        timeout = PHASE_TIMEOUTS.get(phase.value.lower(), 120)

        yield self._make_event("round_start", {
            "phase": phase.value,
            "round": round_num,
        })

        # --- Red move ---
        if phase in (MatchPhase.RECON, MatchPhase.EXPLOITATION, MatchPhase.POST_EXPLOIT):
            red_prompt = self._build_red_prompt(phase, round_num)
            red_move = await self._call_agent_move(
                agent="red",
                prompt=red_prompt,
                phase=phase,
                round_num=round_num,
                timeout=timeout,
            )
            round_data.red_move = red_move

            yield self._make_event("move", {"agent": "red", **red_move.to_dict()})

            # Purple exécute les commandes de Red (max 3 par round)
            if red_move.commands:
                for cmd in red_move.commands[:3]:
                    target_service = self._infer_target_service(cmd)
                    if target_service:
                        exec_result = await self.cyber_range.exec_command(
                            service_name=target_service,
                            command=cmd,
                            timeout=30,
                        )
                        red_move.exec_results.append(exec_result)
                        yield self._make_event("exec_result", {
                            "service": target_service,
                            "command": cmd[:120],
                            "exit_code": exec_result.exit_code,
                            "stdout_preview": exec_result.stdout[:200],
                            "truncated": exec_result.truncated,
                        })

        # --- Blue move ---
        if phase in (MatchPhase.EXPLOITATION, MatchPhase.POST_EXPLOIT, MatchPhase.REMEDIATION):
            # Blue reçoit les nouveaux logs SIEM — JAMAIS les commandes de Red
            new_logs = await self.cyber_range.read_siem_logs(since_line=self._siem_log_cursor)
            round_data.siem_logs = new_logs
            self._siem_log_cursor += len(new_logs)

            blue_prompt = self._build_blue_prompt(phase, round_num, new_logs)
            blue_move = await self._call_agent_move(
                agent="blue",
                prompt=blue_prompt,
                phase=phase,
                round_num=round_num,
                timeout=timeout,
            )
            round_data.blue_move = blue_move

            yield self._make_event("move", {"agent": "blue", **blue_move.to_dict()})

        yield self._make_event("round_complete", {
            "phase": phase.value,
            "round": round_num,
        })

    # ------------------------------------------------------------------
    # Agent call helpers
    # ------------------------------------------------------------------

    async def _call_agent_move(
        self,
        agent: str,
        prompt: str,
        phase: MatchPhase,
        round_num: int,
        timeout: int,
        move_type: MoveType | None = None,
    ) -> AgentMove:
        """Appelle un LLM et construit un AgentMove complet.

        Délègue l'appel LLM réel à _call_agent() qui gère Ollama, historique,
        think-strip et fallback. Cette méthode s'occupe uniquement du wrapping
        en AgentMove (extraction commandes, Sigma, typing).

        Args:
            agent: "red" | "blue".
            prompt: Prompt complet (briefing + phase + contexte).
            phase: Phase courante.
            round_num: Numéro du round.
            timeout: Timeout en secondes pour l'appel LLM.
            move_type: Type de move forcé (sinon inféré depuis la phase).

        Returns:
            AgentMove rempli avec commandes, sigma_rules, exec_results vides.
        """
        system = self._agent_system.get(agent, "")
        start = time.monotonic()

        content = await self._call_agent(agent=agent, prompt=prompt, system=system, timeout=timeout)

        duration_s = time.monotonic() - start
        inferred_type = move_type or self._infer_move_type(agent, phase)
        commands = self._extract_commands(content) if agent == "red" else []
        sigma_rules = self._extract_sigma_rules(content) if agent == "blue" else []

        return AgentMove(
            agent=agent,
            phase=phase,
            round_num=round_num,
            move_type=inferred_type,
            content=content,
            commands=commands,
            sigma_rules=sigma_rules,
            duration_s=duration_s,
            raw_response=content,  # already stripped; raw is the same for AgentMove logging
        )

    async def _call_agent(
        self,
        agent: str,
        prompt: str,
        system: str,
        timeout: int = 120,
    ) -> str:
        """Appelle le LLM pour un agent, avec gestion de l'historique conversationnel.

        Trois chemins possibles (par ordre de priorité) :
        1. Modèle direct configuré (red_model / blue_model) → appel /api/chat Ollama
           avec messages[{role:system}, ...history, {role:user}]. Fallback automatique.
        2. Callable injecté (red_llm / blue_llm) → historique injecté dans le prompt texte.
        3. Aucun des deux → retourne un message d'erreur formaté.

        Dans tous les cas :
        - Les blocs <think>...</think> sont supprimés de la réponse.
        - L'historique est mis à jour (max 2 rounds = 4 entrées).
        - Les erreurs ne lèvent pas d'exception — elles retournent un texte d'erreur.

        Args:
            agent: "red" | "blue".
            prompt: Message utilisateur courant (briefing + phase + contexte).
            system: Prompt système injecté une seule fois au début de la conversation.
            timeout: Timeout en secondes.

        Returns:
            Réponse textuelle strippée.
        """
        model = self._red_model if agent == "red" else self._blue_model
        url   = self._red_url   if agent == "red" else self._blue_url

        # ── Path 1 : appel Ollama direct ─────────────────────────────────────
        if model:
            try:
                raw = self._strip_think(await self._ollama_call(
                    url=url,
                    model=model,
                    system=system,
                    history=self._agent_history[agent],
                    prompt=prompt,
                    timeout=timeout,
                ))
                if len(raw.strip()) >= 20:
                    self._update_history(agent, prompt, raw)
                    return raw
                logger.warning(
                    f"[{agent}] {model} returned short response "
                    f"({len(raw.strip())} chars) — falling back to {self._fallback_model}"
                )
            except Exception as e:
                logger.warning(
                    f"[{agent}] {model} failed ({type(e).__name__}: {e}) "
                    f"— falling back to {self._fallback_model}"
                )

            # Fallback vers qwen3:14b
            try:
                raw = self._strip_think(await self._ollama_call(
                    url=self._fallback_url,
                    model=self._fallback_model,
                    system=system,
                    history=self._agent_history[agent],
                    prompt=prompt,
                    timeout=120,
                ))
                self._update_history(agent, prompt, raw)
                return raw
            except Exception as e:
                logger.error(f"[{agent}] Fallback {self._fallback_model} failed: {e}")
                return f"[ERROR: fallback {self._fallback_model} — {type(e).__name__}: {e}]"

        # ── Path 2 : callable injecté ─────────────────────────────────────────
        llm_callable = self._red_llm if agent == "red" else self._blue_llm
        if llm_callable is not None:
            full_prompt = self._inject_history_into_prompt(agent, prompt)
            try:
                raw = await asyncio.wait_for(llm_callable(full_prompt), timeout=timeout)
                raw = self._strip_think(raw or "")
                self._update_history(agent, prompt, raw)
                return raw
            except asyncio.TimeoutError:
                logger.warning(f"[{agent}] callable timeout after {timeout}s")
                return f"[TIMEOUT after {timeout}s]"
            except Exception as e:
                logger.error(f"[{agent}] callable failed: {e}")
                return f"[ERROR: {type(e).__name__}: {e}]"

        # ── Path 3 : rien de configuré ────────────────────────────────────────
        logger.error(f"[{agent}] No LLM configured (no model, no callable)")
        return f"[ERROR: No LLM configured for agent {agent!r}]"

    async def _ollama_call(
        self,
        url: str,
        model: str,
        system: str,
        history: list[dict],
        prompt: str,
        timeout: int,
    ) -> str:
        """POST /api/chat à Ollama avec messages structurés (system + history + prompt).

        Le system prompt est injecté une seule fois en tête. L'historique est tronqué
        aux 4 dernières entrées (2 rounds = 2 user + 2 assistant) pour limiter le contexte.
        Les blocs <think>...</think> sont supprimés de la réponse.

        Args:
            url: URL de base Ollama (ex: "http://localhost:11434").
            model: Nom du modèle.
            system: Prompt système (rôle + instructions permanentes).
            history: Historique conversationnel de l'agent (liste {role, content}).
            prompt: Message utilisateur courant.
            timeout: Timeout total en secondes.

        Returns:
            Réponse textuelle du modèle, blocs <think> supprimés.

        Raises:
            aiohttp.ClientError: En cas d'erreur réseau ou HTTP.
            asyncio.TimeoutError: Si le modèle dépasse le timeout.
        """
        import aiohttp

        # Max 2 rounds de contexte = 4 messages (2 user + 2 assistant)
        trimmed_history = history[-4:]

        messages: list[dict] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.extend(trimmed_history)
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model":    model,
            "messages": messages,
            "stream":   False,
            "options":  {"num_ctx": 4096},
        }

        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=timeout)
        ) as session:
            async with session.post(f"{url}/api/chat", json=payload) as resp:
                resp.raise_for_status()
                data = await resp.json()
                raw = data.get("message", {}).get("content", "")
                return self._strip_think(raw)

    @staticmethod
    def _strip_think(text: str) -> str:
        """Supprime les blocs <think>...</think> des réponses qwen3.

        Args:
            text: Réponse brute du LLM.

        Returns:
            Texte nettoyé, stripped.
        """
        return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()

    def _update_history(self, agent: str, user_msg: str, assistant_msg: str) -> None:
        """Ajoute un tour user/assistant à l'historique de l'agent.

        L'historique est automatiquement tronqué à 4 entrées (2 rounds)
        pour éviter le débordement de contexte sur les petits modèles (4B).

        Args:
            agent: "red" | "blue".
            user_msg: Message utilisateur du tour.
            assistant_msg: Réponse de l'assistant pour ce tour.
        """
        history = self._agent_history[agent]
        history.append({"role": "user",      "content": user_msg})
        history.append({"role": "assistant", "content": assistant_msg})
        # Garde seulement les 2 derniers rounds (4 messages)
        self._agent_history[agent] = history[-4:]

    def _inject_history_into_prompt(self, agent: str, current_prompt: str) -> str:
        """Injecte l'historique conversationnel dans un prompt texte plat.

        Utilisé uniquement pour le path callable (pas d'accès aux messages structurés).
        Le system prompt est préfixé si présent.

        Args:
            agent: "red" | "blue".
            current_prompt: Prompt courant, sans historique.

        Returns:
            Prompt enrichi avec l'historique des 2 derniers rounds.
        """
        system = self._agent_system.get(agent, "")
        history = self._agent_history[agent][-4:]

        parts: list[str] = []
        if system:
            parts.append(system)
        if history:
            parts.append("=== CONVERSATION HISTORY ===")
            for msg in history:
                label = "Assistant" if msg["role"] == "assistant" else "User"
                parts.append(f"{label}: {msg['content'][:600]}")
        parts.append(current_prompt)
        return "\n\n".join(parts)

    # ------------------------------------------------------------------
    # Prompt builders
    # ------------------------------------------------------------------

    def _build_red_briefing(self) -> str:
        """Construit le briefing initial de Red Team.

        Returns:
            Prompt briefing contenant la surface d'attaque visible.
        """
        info = self.cyber_range.get_service_info_for_red()
        hosts = "\n".join(
            f"  - {h['ip']}:{h['port']} ({h['service_hint']})"
            for h in info["discovered_hosts"]
        )
        return (
            f"=== RED TEAM BRIEFING ===\n"
            f"Network: {info['network_summary']}\n"
            f"Discovered hosts:\n{hosts}\n"
            f"Objective: {info['objective']}\n"
            f"You are Pyrolith, a red team operator. Achieve the objective.\n"
        )

    def _build_blue_briefing(self) -> str:
        """Construit le briefing initial de Blue Team.

        Returns:
            Prompt briefing contenant l'infrastructure à défendre.
        """
        info = self.cyber_range.get_service_info_for_blue()
        infra = "\n".join(
            f"  - {s['service']} @ {s['ip']}:{s['port']} (role: {s['role']})"
            for s in info["infrastructure"]
        )
        return (
            f"=== BLUE TEAM BRIEFING ===\n"
            f"Network: {info['network_summary']}\n"
            f"Infrastructure to defend:\n{infra}\n"
            f"Monitor SIEM logs and detect intrusion attempts.\n"
            f"You are Cryolith, a blue team defender.\n"
        )

    def _build_red_prompt(self, phase: MatchPhase, round_num: int) -> str:
        """Construit le prompt Red pour un round donné.

        Args:
            phase: Phase courante.
            round_num: Numéro du round.

        Returns:
            Prompt complet pour le LLM Red.
        """
        # TODO: Injecter les résultats exec des rounds précédents (contexte limité)
        context = self._build_red_context()
        phase_instruction = self._get_red_phase_instruction(phase)

        return (
            f"{self._red_briefing}\n\n"
            f"=== PHASE: {phase.value.upper()} — Round {round_num} ===\n"
            f"{phase_instruction}\n\n"
            f"{context}\n"
            f"Respond with your next action. Include specific commands to execute."
        )

    def _build_blue_prompt(
        self, phase: MatchPhase, round_num: int, new_logs: list[str]
    ) -> str:
        """Construit le prompt Blue pour un round donné.

        Args:
            phase: Phase courante.
            round_num: Numéro du round.
            new_logs: Nouvelles lignes de log SIEM depuis le dernier round.

        Returns:
            Prompt complet pour le LLM Blue.
        """
        context = self._build_blue_context()
        phase_instruction = self._get_blue_phase_instruction(phase)
        logs_section = ""

        if new_logs:
            logs_str = "\n".join(new_logs[-20:])  # max 20 dernières lignes
            logs_section = f"\n=== NEW SIEM LOGS ===\n{logs_str[:MAX_CONTEXT_CHARS]}\n"

        return (
            f"{self._blue_briefing}\n\n"
            f"=== PHASE: {phase.value.upper()} — Round {round_num} ===\n"
            f"{phase_instruction}\n\n"
            f"{context}"
            f"{logs_section}\n"
            f"Respond with your analysis and defensive actions. "
            f"Include Sigma rules if you detect patterns."
        )

    def _build_red_context(self) -> str:
        """Construit le contexte Red depuis les rounds précédents (max 2 rounds).

        Returns:
            Résumé des derniers moves Red avec résultats d'exécution.
        """
        # TODO: Injecter seulement les exec_results pertinents (pas tout le contexte)
        recent = [r for r in self.rounds if r.red_move is not None][-2:]
        if not recent:
            return ""

        parts = []
        for r in recent:
            move = r.red_move
            if move:
                exec_summary = ""
                if move.exec_results:
                    outputs = [
                        f"  $ {er.command}\n  {er.stdout[:200]}"
                        for er in move.exec_results
                    ]
                    exec_summary = "\n".join(outputs)
                parts.append(
                    f"[Phase {move.phase.value} R{move.round_num}] {move.move_type.value}\n"
                    f"{exec_summary}"
                )

        return "=== PREVIOUS ACTIONS ===\n" + "\n".join(parts) if parts else ""

    def _build_blue_context(self) -> str:
        """Construit le contexte Blue depuis les rounds précédents (max 2 rounds).

        Returns:
            Résumé des derniers moves Blue.
        """
        recent = [r for r in self.rounds if r.blue_move is not None][-2:]
        if not recent:
            return ""

        parts = []
        for r in recent:
            move = r.blue_move
            if move:
                parts.append(
                    f"[Phase {move.phase.value} R{move.round_num}] {move.move_type.value}\n"
                    f"{move.content[:300]}"
                )

        return "=== PREVIOUS ANALYSIS ===\n" + "\n".join(parts) if parts else ""

    # ------------------------------------------------------------------
    # Parsing helpers
    # ------------------------------------------------------------------

    def _infer_move_type(self, agent: str, phase: MatchPhase) -> MoveType:
        """Infère le type de move depuis l'agent et la phase.

        Args:
            agent: "red" | "blue".
            phase: Phase courante.

        Returns:
            MoveType correspondant.
        """
        if agent == "red":
            mapping = {
                MatchPhase.RECON:        MoveType.SCAN,
                MatchPhase.EXPLOITATION: MoveType.EXPLOIT,
                MatchPhase.POST_EXPLOIT: MoveType.PERSISTENCE,
                MatchPhase.REMEDIATION:  MoveType.SCAN,
            }
        else:
            mapping = {
                MatchPhase.RECON:        MoveType.MONITOR,
                MatchPhase.EXPLOITATION: MoveType.ALERT,
                MatchPhase.POST_EXPLOIT: MoveType.BLOCK,
                MatchPhase.REMEDIATION:  MoveType.PATCH,
            }
        return mapping.get(phase, MoveType.SCAN if agent == "red" else MoveType.MONITOR)

    def _extract_commands(self, content: str) -> list[str]:
        """Extrait les commandes shell depuis la réponse Red.

        Args:
            content: Réponse textuelle du LLM Red.

        Returns:
            Liste de commandes shell extraites (max 5).
        """
        commands = []

        # Pattern 1: blocs code bash
        code_blocks = re.findall(r"```(?:bash|sh|shell)?\s*(.*?)```", content, re.DOTALL)
        for block in code_blocks:
            for line in block.strip().splitlines():
                line = line.strip().lstrip("$").strip()
                if line and not line.startswith("#"):
                    commands.append(line)

        # Pattern 2: lignes commençant par $ ou #
        for line in content.splitlines():
            line = line.strip()
            if line.startswith("$ "):
                commands.append(line[2:])

        return commands[:5]  # max 5 commandes par round

    def _extract_sigma_rules(self, content: str) -> list[str]:
        """Extrait les règles Sigma YAML depuis la réponse Blue.

        Args:
            content: Réponse textuelle du LLM Blue.

        Returns:
            Liste de règles Sigma brutes (YAML string).
        """
        rules = []
        yaml_blocks = re.findall(r"```(?:yaml|yml)?\s*(.*?)```", content, re.DOTALL)
        for block in yaml_blocks:
            if "detection:" in block or "logsource:" in block:
                rules.append(block.strip())
        return rules

    def _infer_target_service(self, command: str) -> str | None:
        """Infère le service cible d'une commande Red.

        Args:
            command: Commande shell extraite.

        Returns:
            Nom du service cible, ou None si impossible à déterminer.
        """
        # TODO: Résoudre l'IP ou le nom de service depuis la commande
        # Exemple: "nmap 10.42.1.10" → service avec ip=10.42.1.10
        for svc in self.scenario.services:
            if svc.ip in command:
                return svc.name
            if svc.name.replace("vuln-", "") in command.lower():
                return svc.name
        return None

    def _get_red_phase_instruction(self, phase: MatchPhase) -> str:
        """Retourne l'instruction de phase pour Red.

        Args:
            phase: Phase courante.

        Returns:
            Instruction textuelle pour orienter Red dans cette phase.
        """
        instructions = {
            MatchPhase.RECON: (
                "Perform reconnaissance. Scan the network, identify services and versions. "
                "List commands you would run to discover attack surface."
            ),
            MatchPhase.EXPLOITATION: (
                "Exploit a vulnerability you discovered. Choose a specific target and vector. "
                "Provide the exact commands to execute."
            ),
            MatchPhase.POST_EXPLOIT: (
                "You have initial access. Establish persistence or pivot to another system. "
                "Focus on the objective: " + self.scenario.objective
            ),
        }
        return instructions.get(phase, "Continue your attack.")

    def _get_blue_phase_instruction(self, phase: MatchPhase) -> str:
        """Retourne l'instruction de phase pour Blue.

        Args:
            phase: Phase courante.

        Returns:
            Instruction textuelle pour orienter Blue dans cette phase.
        """
        instructions = {
            MatchPhase.EXPLOITATION: (
                "Analyze the SIEM logs for anomalies. Identify suspicious patterns. "
                "Write a Sigma rule to detect what you observe."
            ),
            MatchPhase.POST_EXPLOIT: (
                "The attacker may have established a foothold. "
                "Review logs, identify the intrusion technique, and propose containment."
            ),
            MatchPhase.REMEDIATION: (
                "Apply patches or hardening to stop the attack. "
                "Provide Sigma rules that will detect this attack in the future. "
                "Propose a specific fix for the exploited vulnerability."
            ),
        }
        return instructions.get(phase, "Monitor and respond to threats.")

    # ------------------------------------------------------------------
    # Event helpers
    # ------------------------------------------------------------------

    def _make_event(self, event_type: str, payload: dict) -> dict:
        """Construit un événement IPC standard.

        Args:
            event_type: Type d'événement.
            payload: Données de l'événement.

        Returns:
            Dict compatible avec le bus IPC arena.
        """
        event = {
            "id": self.match_id,
            "status": "purple",
            "event": event_type,
            "match_id": self.match_id,
            "phase": self.phase.value,
            **payload,
        }
        if self._on_event:
            try:
                self._on_event(event)
            except Exception as e:
                logger.warning(f"on_event callback failed: {e}")
        return event
