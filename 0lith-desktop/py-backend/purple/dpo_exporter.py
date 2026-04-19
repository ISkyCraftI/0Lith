"""
Purple Team — DPO Pair Exporter
=================================
Export des paires de préférence (chosen/rejected) pour fine-tuning DPO.

Chaque match Purple Team produit des paires chosen/rejected basées sur
des critères déterministes uniquement — aucun jugement LLM subjectif.

Sept critères d'extraction :
  Red Team :
    1. exploit_success_vs_failure   — exploit réussi (exit_code=0) vs raté
    2. stealth_vs_detected          — move non détecté par Blue vs détecté
    3. technique_novelty_vs_repeat  — type de move inédit vs déjà utilisé
  Blue Team :
    4. detection_hit_vs_miss        — Blue détecte l'attaque vs silence
    5. sigma_valid_matching_vs_invalid — Sigma valide+matchante vs invalide
    6. patch_proposed_vs_absent     — patch proposé vs pas de patch
    7. no_disruption_vs_disruption  — réponse ciblée vs disruption service

Règle immuable : les scénarios de contrôle (control_scenario=True) ne
sont JAMAIS exportés — ils servent uniquement à la mesure de performance.

Format de sortie :
  - write()         : JSONL complet (pair_id, criterion, metadata, ...)
  - export_to_jsonl(): JSONL TRL {"prompt", "chosen", "rejected"} uniquement

Example:
    exporter = DPOExporter(output_dir=Path("~/.0lith/dpo_data"))
    pairs = exporter.extract_pairs_from_match(match_result)
    path = exporter.write(pairs, match_id=match_result.match_id)
    ok = exporter.accumulate_pairs(min_pairs=500)
"""

from __future__ import annotations

import json
import logging
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from .match_protocol import RoundData, MatchPhase, AgentMove, MatchResult
    from .scenario_generator import ScenarioConfig
    from .scorer import RedScore, BlueScore

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_OUTPUT_DIR = Path.home() / ".0lith" / "dpo_data"

# Longueur minimale d'une réponse pour être incluse dans une paire
MIN_RESPONSE_CHARS = 50
# Longueur maximale (troncature pour éviter les paires géantes)
MAX_RESPONSE_CHARS = 4096
# Limite du cross-produit pour éviter l'explosion combinatoire (N×N pairs)
MAX_CROSS_PAIRS = 4

# Score deltas approximatifs par critère (contribution en points sur 100)
_SCORE_DELTAS: dict[str, float] = {
    "exploit_success_vs_failure":       15.0,
    "stealth_vs_detected":              10.0,
    "technique_novelty_vs_repeat":       5.0,
    "detection_hit_vs_miss":            25.0,
    "sigma_valid_matching_vs_invalid":   10.0,
    "patch_proposed_vs_absent":         20.0,
    "no_disruption_vs_disruption":      10.0,
}

# Mots-clés indiquant que Blue a détecté une activité suspecte
_DETECTION_KEYWORDS: list[str] = [
    "detected", "alert", "suspicious", "anomaly", "intrusion",
    "attack", "threat", "blocked", "unauthorized", "malicious",
    "scan", "exploit", "brute force", "injection", "compromise",
]

# Mots-clés de patch / remediation pour Blue
_PATCH_KEYWORDS: list[str] = [
    "patch", "fix", "update", "upgrade", "remediate", "mitigate",
    "hardening", "disable", "remove", "cve", "vulnerability",
    "apply", "install", "configuration change",
]

# Phrases indiquant une disruption de service (Blue ne doit PAS faire ça)
_DISRUPTION_PHRASES: list[str] = [
    "shut down all", "stop all services", "kill all", "shutdown all services",
    "take down all", "disable all services", "halt all", "offline all",
    "terminate all services", "nuke", "wipe all",
]

# Regex IP privée pour détecter les IPs mentionnées dans les contenus
_PRIVATE_IP_RE = re.compile(
    r"\b(?:10|172\.(?:1[6-9]|2\d|3[01])|192\.168)\.\d{1,3}\.\d{1,3}\b"
)


# ---------------------------------------------------------------------------
# DPOPair dataclass
# ---------------------------------------------------------------------------

@dataclass
class DPOPair:
    """Paire de préférence chosen/rejected pour fine-tuning DPO.

    Attributes:
        pair_id: Identifiant unique (hash déterministe).
        agent: "red" | "blue" — agent concerné.
        prompt: Contexte + instruction commune aux deux réponses.
        chosen: Réponse préférée (meilleure performance déterministe).
        rejected: Réponse rejetée (moins bonne performance).
        criterion: Critère déterministe utilisé (ex: "exploit_success_vs_failure").
        source_match_id: UUID du match source.
        score_delta: Différence de score approximative entre chosen et rejected.
        scenario_seed: Seed du scénario (reproductibilité).
        difficulty: Difficulté du scénario.
        timestamp: Unix timestamp de création.
        metadata: Métadonnées pour audit (technique ATT&CK, phase, etc.).
    """

    pair_id: str
    agent: str
    prompt: str
    chosen: str
    rejected: str
    criterion: str
    source_match_id: str
    score_delta: float
    scenario_seed: int
    difficulty: str
    timestamp: float = field(default_factory=time.time)
    metadata: dict = field(default_factory=dict)

    @property
    def is_valid(self) -> bool:
        """True si la paire est exploitable pour l'entraînement."""
        return (
            bool(self.prompt.strip())
            and self.chosen != self.rejected
            and len(self.chosen) >= MIN_RESPONSE_CHARS
            and len(self.rejected) >= MIN_RESPONSE_CHARS
        )

    def to_dict(self) -> dict:
        """Format complet avec métadonnées (pour archivage et audit)."""
        return {
            "pair_id":         self.pair_id,
            "agent":           self.agent,
            "prompt":          self.prompt,
            "chosen":          self.chosen,
            "rejected":        self.rejected,
            "criterion":       self.criterion,
            "source_match_id": self.source_match_id,
            "score_delta":     round(self.score_delta, 2),
            "scenario_seed":   self.scenario_seed,
            "difficulty":      self.difficulty,
            "timestamp":       self.timestamp,
            "metadata":        self.metadata,
        }

    def to_trl_dict(self) -> dict:
        """Format TRL DPOTrainer : uniquement prompt / chosen / rejected."""
        return {
            "prompt":   self.prompt,
            "chosen":   self.chosen,
            "rejected": self.rejected,
        }


# ---------------------------------------------------------------------------
# DPO Exporter
# ---------------------------------------------------------------------------

class DPOExporter:
    """Extrait et exporte les paires DPO depuis un match Purple Team.

    Les paires sont construites sur des critères 100 % déterministes.
    Aucun jugement LLM — uniquement des vérifications algorithmiques.

    Attributes:
        output_dir: Répertoire de sortie pour les fichiers JSONL.

    Example:
        exporter = DPOExporter(output_dir=Path("~/.0lith/dpo_data"))
        pairs = exporter.extract_pairs_from_match(match_result)
        print(f"Extracted {len(pairs)} DPO pairs")
        path = exporter.write(pairs, match_id=match_result.match_id)
        ready = exporter.accumulate_pairs(min_pairs=500)
    """

    def __init__(self, output_dir: Path | None = None) -> None:
        """Initialise l'exporteur DPO.

        Args:
            output_dir: Répertoire de sortie. Si None, utilise DEFAULT_OUTPUT_DIR.
        """
        self.output_dir = (output_dir or DEFAULT_OUTPUT_DIR).expanduser()
        self.output_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Public API — extraction
    # ------------------------------------------------------------------

    def extract_pairs_from_match(self, match: "MatchResult") -> list[DPOPair]:
        """Extrait toutes les paires DPO depuis un MatchResult complet.

        Règle immuable : si match.scenario.control_scenario == True,
        retourne une liste vide — les scénarios de contrôle ne sont
        JAMAIS exportés.

        Args:
            match: MatchResult complet avec rounds, scenario, scores.

        Returns:
            Liste de DPOPair valides, prêtes pour export.
        """
        # Règle immuable : pas de DPO depuis les scénarios de contrôle
        if match.scenario.control_scenario:
            logger.info(
                f"Skipping DPO export for control scenario "
                f"(seed={match.scenario.seed})"
            )
            return []

        pairs: list[DPOPair] = []
        pairs.extend(self._extract_red_pairs(match.rounds, match.scenario, match.match_id))
        pairs.extend(self._extract_blue_pairs(match.rounds, match.scenario, match.match_id))

        valid = [p for p in pairs if p.is_valid]
        logger.info(
            f"match={match.match_id[:8]} seed={match.scenario.seed} "
            f"→ {len(valid)}/{len(pairs)} valid DPO pairs"
        )
        return valid

    def extract_pairs(
        self,
        rounds: list["RoundData"],
        scenario: "ScenarioConfig",
        match_id: str = "",
        red_score: "RedScore | None" = None,
        blue_score: "BlueScore | None" = None,
    ) -> list[DPOPair]:
        """API de compatibilité — appelée depuis match_protocol.finalize().

        Délègue vers les mêmes extracteurs internes qu'extract_pairs_from_match.

        Args:
            rounds: Rounds du match.
            scenario: ScenarioConfig du match.
            match_id: UUID du match (optionnel).
            red_score: RedScore (non utilisé directement, critères sont algorithmiques).
            blue_score: BlueScore (idem).

        Returns:
            Liste de DPOPair valides.
        """
        if scenario.control_scenario:
            return []

        mid = match_id or str(uuid.uuid4())
        pairs: list[DPOPair] = []
        pairs.extend(self._extract_red_pairs(rounds, scenario, mid))
        pairs.extend(self._extract_blue_pairs(rounds, scenario, mid))

        valid = [p for p in pairs if p.is_valid]
        logger.info(
            f"extract_pairs: seed={scenario.seed} → {len(valid)}/{len(pairs)} valid pairs"
        )
        return valid

    # ------------------------------------------------------------------
    # Public API — export
    # ------------------------------------------------------------------

    def write(
        self,
        pairs: list[DPOPair],
        match_id: str,
        filename: str | None = None,
    ) -> Path:
        """Écrit les paires DPO au format complet (avec métadonnées) dans un JSONL.

        Args:
            pairs: Paires DPO à exporter.
            match_id: UUID du match (pour le nom de fichier).
            filename: Nom de fichier personnalisé (optionnel).

        Returns:
            Chemin absolu du fichier JSONL créé.
        """
        if not pairs:
            logger.warning("write(): no DPO pairs to write")
            return self.output_dir / "empty.jsonl"

        ts = int(time.time())
        fname = filename or f"dpo_{ts}_{match_id[:8]}.jsonl"
        out_path = self.output_dir / fname

        with out_path.open("w", encoding="utf-8") as f:
            for pair in pairs:
                f.write(json.dumps(pair.to_dict(), ensure_ascii=False) + "\n")

        logger.info(f"Wrote {len(pairs)} DPO pairs → {out_path}")
        return out_path

    def export_to_jsonl(
        self,
        pairs: list[DPOPair],
        output_path: str | Path | None = None,
    ) -> Path:
        """Exporte au format TRL DPOTrainer : {"prompt", "chosen", "rejected"}.

        Fichier prêt à être passé directement à trl.DPOTrainer ou axolotl.

        Format du nom auto-généré : {YYYYMMDD}_{count}_pairs.jsonl

        Args:
            pairs: Paires DPO à exporter.
            output_path: Chemin de sortie. Si None, génère un nom dans output_dir.

        Returns:
            Chemin absolu du fichier JSONL créé.
        """
        if not pairs:
            logger.warning("export_to_jsonl(): no pairs to export")
            return self.output_dir / "empty_trl.jsonl"

        if output_path is None:
            date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
            out_path = self.output_dir / f"{date_str}_{len(pairs)}_pairs.jsonl"
        else:
            out_path = Path(output_path)

        out_path.parent.mkdir(parents=True, exist_ok=True)
        with out_path.open("w", encoding="utf-8") as f:
            for pair in pairs:
                f.write(json.dumps(pair.to_trl_dict(), ensure_ascii=False) + "\n")

        logger.info(f"Exported {len(pairs)} TRL pairs → {out_path}")
        return out_path

    def accumulate_pairs(self, min_pairs: int = 500) -> bool:
        """Vérifie si le dossier dpo_data contient assez de paires pour un cycle DPO.

        Compte toutes les paires dans les fichiers dpo_*.jsonl de output_dir.

        Args:
            min_pairs: Seuil minimum de paires pour lancer le fine-tuning.

        Returns:
            True si total_pairs >= min_pairs.
        """
        total = 0
        for fpath in self.output_dir.glob("dpo_*.jsonl"):
            try:
                with fpath.open("r", encoding="utf-8") as f:
                    total += sum(1 for line in f if line.strip())
            except OSError as e:
                logger.warning(f"accumulate_pairs: cannot read {fpath}: {e}")
            if total >= min_pairs:
                break  # early exit

        logger.debug(f"accumulate_pairs: {total} pairs found (min={min_pairs})")
        return total >= min_pairs

    def merge_files(self, output_filename: str = "merged_dpo.jsonl") -> Path:
        """Fusionne tous les fichiers dpo_*.jsonl en un seul, dédupliqué par pair_id.

        Args:
            output_filename: Nom du fichier fusionné.

        Returns:
            Chemin vers le fichier fusionné.
        """
        jsonl_files = sorted(self.output_dir.glob("dpo_*.jsonl"))
        if not jsonl_files:
            logger.warning("merge_files(): no dpo_*.jsonl files found")
            return self.output_dir / output_filename

        out_path = self.output_dir / output_filename
        seen_ids: set[str] = set()
        total = 0

        with out_path.open("w", encoding="utf-8") as out:
            for fpath in jsonl_files:
                try:
                    with fpath.open("r", encoding="utf-8") as src:
                        for line in src:
                            line = line.strip()
                            if not line:
                                continue
                            try:
                                pair = json.loads(line)
                                pid = pair.get("pair_id", "")
                                if pid and pid not in seen_ids:
                                    seen_ids.add(pid)
                                    out.write(line + "\n")
                                    total += 1
                                elif not pid:
                                    # Pas d'ID → include anyway (ex: format TRL)
                                    out.write(line + "\n")
                                    total += 1
                            except json.JSONDecodeError:
                                continue
                except OSError as e:
                    logger.warning(f"merge_files: cannot read {fpath}: {e}")

        logger.info(f"Merged {total} unique pairs → {out_path}")
        return out_path

    def get_stats(self) -> dict:
        """Retourne les statistiques sur les paires DPO disponibles dans output_dir.

        Returns:
            Dict avec total_pairs, total_files, by_agent, by_difficulty, by_criterion.
        """
        jsonl_files = list(self.output_dir.glob("dpo_*.jsonl"))
        stats: dict = {
            "total_pairs":    0,
            "total_files":    len(jsonl_files),
            "by_agent":       {"red": 0, "blue": 0},
            "by_difficulty":  {"easy": 0, "medium": 0, "hard": 0},
            "by_criterion":   {},
            "output_dir":     str(self.output_dir),
        }

        for fpath in jsonl_files:
            try:
                with fpath.open("r", encoding="utf-8") as src:
                    for line in src:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            pair = json.loads(line)
                        except json.JSONDecodeError:
                            continue

                        stats["total_pairs"] += 1
                        agent = pair.get("agent", "unknown")
                        diff  = pair.get("difficulty", "unknown")
                        crit  = pair.get("criterion", "unknown")

                        stats["by_agent"][agent] = stats["by_agent"].get(agent, 0) + 1
                        stats["by_difficulty"][diff] = stats["by_difficulty"].get(diff, 0) + 1
                        stats["by_criterion"][crit]  = stats["by_criterion"].get(crit, 0) + 1
            except OSError as e:
                logger.warning(f"get_stats: cannot read {fpath}: {e}")

        return stats

    # ------------------------------------------------------------------
    # Red Team extraction
    # ------------------------------------------------------------------

    def _extract_red_pairs(
        self,
        rounds: list["RoundData"],
        scenario: "ScenarioConfig",
        match_id: str,
    ) -> list[DPOPair]:
        """Extrait les 3 critères Red Team."""
        pairs: list[DPOPair] = []
        pairs.extend(self._red_exploit_pairs(rounds, scenario, match_id))
        pairs.extend(self._red_stealth_pairs(rounds, scenario, match_id))
        pairs.extend(self._red_diversity_pairs(rounds, scenario, match_id))
        return pairs

    def _red_exploit_pairs(
        self,
        rounds: list["RoundData"],
        scenario: "ScenarioConfig",
        match_id: str,
    ) -> list[DPOPair]:
        """Critère 1 : exploit réussi (exit_code=0) vs raté.

        Compare les moves Red EXPLOITATION où au moins une commande a réussi
        (exec_result.success=True) contre des moves où toutes ont échoué.
        """
        from .match_protocol import MatchPhase

        successes: list["RoundData"] = []
        failures:  list["RoundData"] = []

        for r in rounds:
            if r.red_move is None or r.phase != MatchPhase.EXPLOITATION:
                continue
            results = r.red_move.exec_results
            if not results:
                continue
            if any(er.success for er in results):
                successes.append(r)
            elif all(not er.success for er in results):
                failures.append(r)

        return self._cross_pair_red(
            chosen_list=successes,
            rejected_list=failures,
            criterion="exploit_success_vs_failure",
            scenario=scenario,
            match_id=match_id,
            extra_meta_fn=lambda c, r: {
                "chosen_exec_codes":   [er.exit_code for er in (c.red_move.exec_results if c.red_move else [])],
                "rejected_exec_codes": [er.exit_code for er in (r.red_move.exec_results if r.red_move else [])],
            },
        )

    def _red_stealth_pairs(
        self,
        rounds: list["RoundData"],
        scenario: "ScenarioConfig",
        match_id: str,
    ) -> list[DPOPair]:
        """Critère 2 : move non détecté par Blue (chosen) vs détecté (rejected)."""
        from .match_protocol import MatchPhase

        stealthy: list["RoundData"] = []
        detected: list["RoundData"] = []

        for r in rounds:
            if r.red_move is None:
                continue
            if r.phase not in (MatchPhase.EXPLOITATION, MatchPhase.POST_EXPLOIT):
                continue
            if self._blue_detected_red_move(r, rounds):
                detected.append(r)
            else:
                stealthy.append(r)

        return self._cross_pair_red(
            chosen_list=stealthy,
            rejected_list=detected,
            criterion="stealth_vs_detected",
            scenario=scenario,
            match_id=match_id,
            extra_meta_fn=lambda c, r: {
                "chosen_was_detected":   False,
                "rejected_was_detected": True,
            },
        )

    def _red_diversity_pairs(
        self,
        rounds: list["RoundData"],
        scenario: "ScenarioConfig",
        match_id: str,
    ) -> list[DPOPair]:
        """Critère 3 : technique inédite (chosen) vs technique déjà utilisée (rejected).

        Parcourt les rounds dans l'ordre chronologique et identifie la première
        occurrence de chaque MoveType (novel) vs les occurrences suivantes (repeat).
        """
        seen_move_types: set[str] = set()
        novel_rounds:  list["RoundData"] = []
        repeat_rounds: list["RoundData"] = []

        for r in sorted(rounds, key=lambda x: x.round_num):
            if r.red_move is None:
                continue
            mt = r.red_move.move_type.value
            if mt in seen_move_types:
                repeat_rounds.append(r)
            else:
                seen_move_types.add(mt)
                novel_rounds.append(r)

        return self._cross_pair_red(
            chosen_list=novel_rounds,
            rejected_list=repeat_rounds,
            criterion="technique_novelty_vs_repeat",
            scenario=scenario,
            match_id=match_id,
            extra_meta_fn=lambda c, r: {
                "chosen_move_type":   c.red_move.move_type.value if c.red_move else "",
                "rejected_move_type": r.red_move.move_type.value if r.red_move else "",
            },
        )

    # ------------------------------------------------------------------
    # Blue Team extraction
    # ------------------------------------------------------------------

    def _extract_blue_pairs(
        self,
        rounds: list["RoundData"],
        scenario: "ScenarioConfig",
        match_id: str,
    ) -> list[DPOPair]:
        """Extrait les 4 critères Blue Team."""
        pairs: list[DPOPair] = []
        pairs.extend(self._blue_detection_pairs(rounds, scenario, match_id))
        pairs.extend(self._blue_sigma_pairs(rounds, scenario, match_id))
        pairs.extend(self._blue_patch_pairs(rounds, scenario, match_id))
        pairs.extend(self._blue_disruption_pairs(rounds, scenario, match_id))
        return pairs

    def _blue_detection_pairs(
        self,
        rounds: list["RoundData"],
        scenario: "ScenarioConfig",
        match_id: str,
    ) -> list[DPOPair]:
        """Critère 4 : Blue détecte l'attaque (chosen) vs silence (rejected).

        Dans les rounds où Red était actif, compare les réponses Blue
        qui mentionnent des indicateurs d'attaque vs celles qui n'en mentionnent pas.
        """
        from .match_protocol import MatchPhase

        hits:   list["RoundData"] = []
        misses: list["RoundData"] = []

        for r in rounds:
            if r.blue_move is None or r.red_move is None:
                continue
            if r.phase not in (MatchPhase.EXPLOITATION, MatchPhase.POST_EXPLOIT):
                continue

            if self._blue_content_is_detection(r.blue_move.content, r.red_move):
                hits.append(r)
            else:
                misses.append(r)

        return self._cross_pair_blue(
            chosen_list=hits,
            rejected_list=misses,
            criterion="detection_hit_vs_miss",
            scenario=scenario,
            match_id=match_id,
            extra_meta_fn=lambda c, r: {
                "chosen_detection":  True,
                "rejected_detection": False,
                "chosen_siem_lines": len(c.siem_logs),
            },
        )

    def _blue_sigma_pairs(
        self,
        rounds: list["RoundData"],
        scenario: "ScenarioConfig",
        match_id: str,
    ) -> list[DPOPair]:
        """Critère 5 : Sigma valide + matchante (chosen) vs invalide / absente (rejected).

        Utilise Scorer.validate_sigma_rule pour déterminer la qualité de la règle.
        """
        from .scorer import Scorer
        from .match_protocol import MatchPhase

        high_quality: list["RoundData"] = []  # sigma valide + matchante
        low_quality:  list["RoundData"] = []  # sigma invalide ou absente

        for r in rounds:
            if r.blue_move is None:
                continue
            if r.phase not in (MatchPhase.EXPLOITATION, MatchPhase.POST_EXPLOIT, MatchPhase.REMEDIATION):
                continue

            if r.blue_move.sigma_rules:
                # Valide au moins une règle
                attack_logs = r.siem_logs + (r.red_move.commands if r.red_move else [])
                best_score = 0
                for rule_yaml in r.blue_move.sigma_rules:
                    sv = Scorer.validate_sigma_rule(rule_yaml, attack_logs=attack_logs)
                    best_score = max(best_score, sv.score_value)
                if best_score == 2:   # valid + matching
                    high_quality.append(r)
                elif best_score == 1:  # valid only → chosen against absent
                    high_quality.append(r)
                # score 0 → invalid
            else:
                # Pas de sigma — rejected contre rounds avec sigma
                low_quality.append(r)

        return self._cross_pair_blue(
            chosen_list=high_quality,
            rejected_list=low_quality,
            criterion="sigma_valid_matching_vs_invalid",
            scenario=scenario,
            match_id=match_id,
            extra_meta_fn=lambda c, r: {
                "chosen_sigma_count":   len(c.blue_move.sigma_rules) if c.blue_move else 0,
                "rejected_sigma_count": len(r.blue_move.sigma_rules) if r.blue_move else 0,
            },
        )

    def _blue_patch_pairs(
        self,
        rounds: list["RoundData"],
        scenario: "ScenarioConfig",
        match_id: str,
    ) -> list[DPOPair]:
        """Critère 6 : patch / remediation proposé (chosen) vs absent (rejected).

        Cherche des mots-clés de patch dans les réponses Blue de la phase REMEDIATION.
        """
        from .match_protocol import MatchPhase

        patched:    list["RoundData"] = []
        not_patched: list["RoundData"] = []

        for r in rounds:
            if r.blue_move is None:
                continue
            if r.phase != MatchPhase.REMEDIATION:
                continue
            if self._content_proposes_patch(r.blue_move.content):
                patched.append(r)
            else:
                not_patched.append(r)

        return self._cross_pair_blue(
            chosen_list=patched,
            rejected_list=not_patched,
            criterion="patch_proposed_vs_absent",
            scenario=scenario,
            match_id=match_id,
            extra_meta_fn=lambda c, r: {
                "chosen_phase":   c.phase.value,
                "rejected_phase": r.phase.value,
            },
        )

    def _blue_disruption_pairs(
        self,
        rounds: list["RoundData"],
        scenario: "ScenarioConfig",
        match_id: str,
    ) -> list[DPOPair]:
        """Critère 7 : réponse ciblée (chosen) vs disruption de service (rejected).

        Blue doit répondre de façon chirurgicale. "Shut down all services" est
        un rejected — un score SDR == 0 est requis (chosen).
        """
        targeted:    list["RoundData"] = []
        disruptive:  list["RoundData"] = []

        for r in rounds:
            if r.blue_move is None:
                continue
            if self._content_is_disruptive(r.blue_move.content):
                disruptive.append(r)
            else:
                targeted.append(r)

        # Paires : targeted (chosen) vs disruptive (rejected)
        return self._cross_pair_blue(
            chosen_list=targeted,
            rejected_list=disruptive,
            criterion="no_disruption_vs_disruption",
            scenario=scenario,
            match_id=match_id,
            extra_meta_fn=lambda c, r: {
                "chosen_is_disruptive":   False,
                "rejected_is_disruptive": True,
            },
        )

    # ------------------------------------------------------------------
    # Cross-pairing helpers
    # ------------------------------------------------------------------

    def _cross_pair_red(
        self,
        chosen_list: list["RoundData"],
        rejected_list: list["RoundData"],
        criterion: str,
        scenario: "ScenarioConfig",
        match_id: str,
        extra_meta_fn: Callable | None = None,
    ) -> list[DPOPair]:
        """Cross-produit limité à MAX_CROSS_PAIRS² pour les paires Red."""
        pairs: list[DPOPair] = []
        for i, c_round in enumerate(chosen_list[:MAX_CROSS_PAIRS]):
            for j, r_round in enumerate(rejected_list[:MAX_CROSS_PAIRS]):
                if c_round.red_move is None or r_round.red_move is None:
                    continue
                prompt   = self._build_red_prompt(c_round, scenario)
                chosen   = c_round.red_move.content[:MAX_RESPONSE_CHARS]
                rejected = r_round.red_move.content[:MAX_RESPONSE_CHARS]
                extra    = extra_meta_fn(c_round, r_round) if extra_meta_fn else {}

                pair = DPOPair(
                    pair_id         = f"{match_id[:8]}-red-{criterion}-{i}{j}",
                    agent           = "red",
                    prompt          = prompt,
                    chosen          = chosen,
                    rejected        = rejected,
                    criterion       = criterion,
                    source_match_id = match_id,
                    score_delta     = _SCORE_DELTAS.get(criterion, 5.0),
                    scenario_seed   = scenario.seed,
                    difficulty      = scenario.difficulty,
                    metadata        = {
                        "chosen_phase":       c_round.phase.value,
                        "chosen_round":       c_round.round_num,
                        "rejected_phase":     r_round.phase.value,
                        "rejected_round":     r_round.round_num,
                        "mitre_techniques":   list(scenario.mitre_techniques),
                        **extra,
                    },
                )
                if pair.is_valid:
                    pairs.append(pair)
        return pairs

    def _cross_pair_blue(
        self,
        chosen_list: list["RoundData"],
        rejected_list: list["RoundData"],
        criterion: str,
        scenario: "ScenarioConfig",
        match_id: str,
        extra_meta_fn: Callable | None = None,
    ) -> list[DPOPair]:
        """Cross-produit limité à MAX_CROSS_PAIRS² pour les paires Blue."""
        pairs: list[DPOPair] = []
        for i, c_round in enumerate(chosen_list[:MAX_CROSS_PAIRS]):
            for j, r_round in enumerate(rejected_list[:MAX_CROSS_PAIRS]):
                if c_round.blue_move is None or r_round.blue_move is None:
                    continue
                # Le prompt Blue est contextualisé avec les logs SIEM du round chosen
                prompt   = self._build_blue_prompt(c_round, scenario)
                chosen   = c_round.blue_move.content[:MAX_RESPONSE_CHARS]
                rejected = r_round.blue_move.content[:MAX_RESPONSE_CHARS]
                extra    = extra_meta_fn(c_round, r_round) if extra_meta_fn else {}

                pair = DPOPair(
                    pair_id         = f"{match_id[:8]}-blue-{criterion}-{i}{j}",
                    agent           = "blue",
                    prompt          = prompt,
                    chosen          = chosen,
                    rejected        = rejected,
                    criterion       = criterion,
                    source_match_id = match_id,
                    score_delta     = _SCORE_DELTAS.get(criterion, 5.0),
                    scenario_seed   = scenario.seed,
                    difficulty      = scenario.difficulty,
                    metadata        = {
                        "chosen_phase":   c_round.phase.value,
                        "chosen_round":   c_round.round_num,
                        "rejected_phase": r_round.phase.value,
                        "rejected_round": r_round.round_num,
                        "siem_lines":     len(c_round.siem_logs),
                        **extra,
                    },
                )
                if pair.is_valid:
                    pairs.append(pair)
        return pairs

    # ------------------------------------------------------------------
    # Detection / quality helpers
    # ------------------------------------------------------------------

    def _blue_detected_red_move(
        self, red_round: "RoundData", all_rounds: list["RoundData"]
    ) -> bool:
        """Vérifie si Blue a détecté le move Red de ce round.

        Cherche dans la réponse Blue du même round, puis du round suivant.
        Détection positive si :
          (a) une IP de la commande Red est mentionnée dans le texte Blue, OU
          (b) ≥ 3 mots-clés de détection sont présents dans la réponse Blue.

        Args:
            red_round: Round avec un red_move.
            all_rounds: Tous les rounds du match (pour chercher la réponse Blue suivante).

        Returns:
            True si Blue a probablement détecté cette action.
        """
        if red_round.red_move is None:
            return False

        # Chercher la réponse Blue : même round, puis round suivant
        blue_text = ""
        if red_round.blue_move:
            blue_text = red_round.blue_move.content
        else:
            for r in sorted(all_rounds, key=lambda x: x.round_num):
                if r.round_num > red_round.round_num and r.blue_move:
                    blue_text = r.blue_move.content
                    break

        if not blue_text:
            return False

        blue_lower = blue_text.lower()

        # Critère (a) : IP mentionnée par Blue
        red_text = " ".join(
            [red_round.red_move.content] + red_round.red_move.commands
        )
        for ip in _PRIVATE_IP_RE.findall(red_text):
            if ip in blue_lower:
                return True

        # Critère (b) : ≥ 3 mots-clés de détection (réponse active de Blue)
        kw_hits = sum(1 for kw in _DETECTION_KEYWORDS if kw in blue_lower)
        return kw_hits >= 3

    def _blue_content_is_detection(
        self, blue_content: str, red_move: "AgentMove"
    ) -> bool:
        """Vérifie si la réponse Blue constitue une détection de l'activité Red.

        Args:
            blue_content: Texte de la réponse Blue.
            red_move: Move Red du même round.

        Returns:
            True si Blue a détecté l'activité.
        """
        if not blue_content.strip():
            return False

        blue_lower = blue_content.lower()

        # IP du move Red mentionnée dans le texte Blue
        red_text = " ".join([red_move.content] + red_move.commands)
        for ip in _PRIVATE_IP_RE.findall(red_text):
            if ip in blue_lower:
                return True

        # ≥ 3 mots-clés de détection
        return sum(1 for kw in _DETECTION_KEYWORDS if kw in blue_lower) >= 3

    def _content_proposes_patch(self, blue_content: str) -> bool:
        """Vérifie si la réponse Blue propose un patch / une remediation.

        Args:
            blue_content: Texte de la réponse Blue.

        Returns:
            True si au moins un mot-clé de patch est présent.
        """
        lower = blue_content.lower()
        return any(kw in lower for kw in _PATCH_KEYWORDS)

    def _content_is_disruptive(self, blue_content: str) -> bool:
        """Vérifie si la réponse Blue propose une action disruptive (SDR > 0).

        Args:
            blue_content: Texte de la réponse Blue.

        Returns:
            True si la réponse propose d'arrêter tous les services.
        """
        lower = blue_content.lower()
        return any(phrase in lower for phrase in _DISRUPTION_PHRASES)

    # ------------------------------------------------------------------
    # Prompt reconstruction for DPO context
    # ------------------------------------------------------------------

    def _build_red_prompt(
        self, round_data: "RoundData", scenario: "ScenarioConfig"
    ) -> str:
        """Reconstruit le prompt Red approximatif pour ce round.

        Le prompt est le contexte commun dont BOTH chosen et rejected sont
        des continuations possibles.

        Args:
            round_data: Round dont on reconstruit le prompt.
            scenario: ScenarioConfig du match.

        Returns:
            Prompt Red formaté pour DPO.
        """
        hosts = "\n".join(
            f"  - {svc.ip}:{svc.port} ({svc.name.replace('vuln-', '')})"
            for svc in scenario.services
        )
        phase_val = round_data.phase.value.upper()
        round_num = round_data.round_num

        # Contexte des actions précédentes (max 2 rounds avant)
        prev_actions = ""
        prev = [r for r in [] if r.red_move]  # placeholder — pas d'historique cross-pair
        if round_data.red_move and round_data.red_move.exec_results:
            exec_summary = "\n".join(
                f"  $ {er.command}  → exit_code={er.exit_code}"
                for er in round_data.red_move.exec_results[:3]
            )
            prev_actions = f"\nPrevious exec results:\n{exec_summary}"

        return (
            f"=== RED TEAM BRIEFING ===\n"
            f"Network: {scenario.subnet}\n"
            f"Discovered hosts:\n{hosts}\n"
            f"Objective: {scenario.objective}\n"
            f"Difficulty: {scenario.difficulty}\n"
            f"You are Pyrolith, a red team operator. Achieve the objective.\n\n"
            f"=== PHASE: {phase_val} — Round {round_num} ===\n"
            f"Execute your next attack action. Provide specific commands.{prev_actions}\n"
        )

    def _build_blue_prompt(
        self, round_data: "RoundData", scenario: "ScenarioConfig"
    ) -> str:
        """Reconstruit le prompt Blue approximatif pour ce round.

        Inclut les logs SIEM disponibles à ce round.

        Args:
            round_data: Round dont on reconstruit le prompt.
            scenario: ScenarioConfig du match.

        Returns:
            Prompt Blue formaté pour DPO.
        """
        infra = "\n".join(
            f"  - {svc.name} @ {svc.ip}:{svc.port}"
            for svc in scenario.services
        )
        phase_val = round_data.phase.value.upper()
        round_num = round_data.round_num

        logs_section = ""
        if round_data.siem_logs:
            logs_str = "\n".join(round_data.siem_logs[-10:])
            logs_section = f"\n=== NEW SIEM LOGS ===\n{logs_str[:1000]}\n"

        return (
            f"=== BLUE TEAM BRIEFING ===\n"
            f"Network: {scenario.subnet}\n"
            f"Infrastructure to defend:\n{infra}\n"
            f"Difficulty: {scenario.difficulty}\n"
            f"You are Cryolith, a blue team defender.\n\n"
            f"=== PHASE: {phase_val} — Round {round_num} ===\n"
            f"{logs_section}"
            f"Respond with your analysis and defensive actions. "
            f"Include Sigma rules if you detect attack patterns.\n"
        )
