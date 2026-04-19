"""
Purple Team — Match Scorer
===========================
Scoring déterministe d'un match Purple Team.

Priorité absolue aux vérifications binaires/algorithmiques (flag exfiltré,
Sigma valide, patch proposé). Le jugement LLM est exclu — 100 % Python.

Trois méthodes publiques clés, utilisables de façon indépendante :

    scorer = Scorer()

    # Validation d'une règle Sigma avec matching sur logs d'attaque
    result = Scorer.validate_sigma_rule(yaml_str, attack_logs)

    # Vérification binaire de l'objectif Red
    achieved = Scorer.check_objective(red_outputs, scenario)

    # Taux d'évasion : proportion d'actions Red non détectées par Blue
    rate = scorer.calculate_evasion_rate(red_actions, blue_analyses)

    # Scoring complet d'un match
    red = scorer.score_red(rounds, scenario)
    blue = scorer.score_blue(rounds, scenario)

Formules normalisées 0-100 :
  Red:  40% objectif + 20% évasion + 15% diversité + 15% efficacité + 10% services
  Blue: 30% détection + 25% Sigma + 20% patch + 15% root_cause + 10% pas de disruption
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .cyber_range import CyberRange
    from .match_protocol import MatchResult, RoundData, MatchPhase
    from .scenario_generator import ScenarioConfig

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Sigma validation constants
# ---------------------------------------------------------------------------

# Champs obligatoires au niveau racine d'une règle Sigma
SIGMA_REQUIRED_ROOT: frozenset[str] = frozenset({"title", "logsource", "detection"})

# `condition` doit être présent à l'intérieur du bloc `detection`
SIGMA_REQUIRED_IN_DETECTION: frozenset[str] = frozenset({"condition"})

# Valeurs acceptées pour le champ `status` (optionnel)
SIGMA_VALID_STATUSES: frozenset[str] = frozenset({
    "stable", "test", "experimental", "deprecated", "unsupported",
})

# ---------------------------------------------------------------------------
# Keyword maps for evasion rate detection
# ---------------------------------------------------------------------------

# Move type → mots-clés que Blue écrirait si elle détecte ce type d'action
_MOVE_DETECTION_KEYWORDS: dict[str, list[str]] = {
    "SCAN":        ["scan", "nmap", "port", "reconnais", "enumerat", "discovery",
                    "probe", "banner"],
    "EXPLOIT":     ["exploit", "injection", "sqli", "sql ", "brute force", "brute-force",
                    "unauthorized", "buffer overflow", "rce", "remote code"],
    "PERSISTENCE": ["persistence", "backdoor", "cron", "startup", "scheduled task",
                    "registry", "autorun"],
    "PIVOT":       ["pivot", "lateral", "jump", "tunnel", "proxy chain", "move"],
    "EXFIL":       ["exfil", "transfer", "download", "flag", "/flag", "data theft",
                    "exfiltrat"],
}

# Commandes shell → indicateurs de détection associés
_COMMAND_DETECTION_KEYWORDS: dict[str, list[str]] = {
    "nmap":       ["port scan", "scan", "nmap"],
    "sqlmap":     ["sql injection", "sqli", "database attack"],
    "hydra":      ["brute force", "password", "credential stuffing"],
    "metasploit": ["exploit", "meterpreter", "shellcode"],
    "msfconsole": ["exploit", "metasploit"],
    "wget":       ["download", "transfer", "exfiltrat"],
    "curl":       ["http request", "web", "transfer"],
    "nc":         ["netcat", "reverse shell", "backdoor"],
    "ssh":        ["ssh", "remote access"],
    "ftp":        ["ftp", "file transfer"],
    "smbclient":  ["smb", "share", "lateral"],
}

# ---------------------------------------------------------------------------
# Scoring weights — pondérations des composantes (somme = 100 chaque team)
# ---------------------------------------------------------------------------

# Red Team: 40 + 20 + 15 + 15 + 10 = 100
RED_MAX_POINTS: dict[str, float] = {
    "objective":   40.0,
    "evasion":     20.0,
    "diversity":   15.0,
    "efficiency":  15.0,
    "services":    10.0,
}

# Blue Team: 30 + 25 + 20 + 15 + 10 = 100
BLUE_MAX_POINTS: dict[str, float] = {
    "detection":   30.0,
    "sigma":       25.0,
    "patch":       20.0,
    "root_cause":  15.0,
    "disruption":  10.0,
}

# Pénalités Red (soustraites au total, max = 20 points)
RED_PENALTY_PER_FAILED_EXPLOIT:    float = 2.0
RED_PENALTY_PER_REPEAT_TECHNIQUE:  float = 1.0
RED_MAX_PENALTY:                   float = 20.0

# Pénalités Blue (soustraites au total, max = 10 points)
BLUE_PENALTY_PER_FALSE_POSITIVE:   float = 2.0
BLUE_MAX_FP_PENALTY:               float = 10.0

# Seuil de "détection précoce" : proportion de rounds total
EARLY_DETECTION_THRESHOLD: float = 0.30

# Minimum de caractères dans une réponse LLM pour être considérée valide
MIN_VALID_RESPONSE_LEN: int = 20

# Mots-clés de détection haut niveau (utilisés pour la détection d'intrusion)
DETECTION_KEYWORDS: list[str] = [
    "detected", "suspicious", "anomal", "intrusion", "attack", "alert",
    "brute force", "sqli", "injection", "exploit", "unauthorized", "malicious",
    "scan", "probe", "backdoor", "exfil",
]

# Mots-clés de sur-réaction Blue (disruption de services)
DISRUPTION_KEYWORDS: list[str] = [
    "shutdown all", "block all traffic", "disable all services",
    "stop all", "take down", "shut down everything",
]

# Mots-clés de patch / hardening dans les réponses Blue
PATCH_KEYWORDS: list[str] = [
    "patch", "update", "upgrade", "fix", "harden", "disable",
    "block", "restrict", "firewall", "waf", "rate limit",
    "input validation", "prepared statement", "parameterized",
    "remove", "uninstall", "mitigate",
]

# Mots-clés indiquant qu'un bloc de code Blue est une commande de remédiation
_PATCH_CODE_KEYWORDS: list[str] = [
    "iptables", "chmod", "sed", "patch", "apt", "systemctl",
    "firewall-cmd", "ufw", "chown", "passwd", "set -e",
    "update", "upgrade", "remove", "uninstall", "disable",
]

# Indicateurs de compromission dans la sortie d'un exploit Red réussi
_COMPROMISE_INDICATORS: list[str] = [
    "flag{", "password", "passwd", "hash:", "root@", "compromised",
    "admin", "token", "secret", "exfil",
]

# Regex pour extraire les blocs de code (```...``` et `...`)
_CODE_BLOCK_RE = re.compile(r"```(?:\w+)?\s*\n?(.*?)```", re.DOTALL)


# ---------------------------------------------------------------------------
# SigmaValidation
# ---------------------------------------------------------------------------

@dataclass
class SigmaValidation:
    """Résultat de la validation d'une règle Sigma.

    Attributes:
        valid: True si la règle est syntaxiquement et structurellement correcte.
        matches_attack: True si la règle matche au moins un log d'attaque fourni.
            Toujours False si `attack_logs` était vide à la validation.
        errors: Liste des erreurs de validation (vide si valid=True).
        title: Titre de la règle extrait (vide si YAML invalide).
        detection_keywords: Mots-clés/patterns extraits de la section detection.
        rule_hash: Hash MD5 du yaml_str normalisé (pour déduplication).
    """

    valid: bool
    matches_attack: bool
    errors: list[str]
    title: str = ""
    detection_keywords: list[str] = field(default_factory=list)
    rule_hash: str = ""

    @property
    def score_value(self) -> int:
        """Valeur de scoring : 2 si valide + matching, 1 si valide, 0 sinon."""
        if self.valid and self.matches_attack:
            return 2
        return 1 if self.valid else 0


# ---------------------------------------------------------------------------
# RedScore
# ---------------------------------------------------------------------------

@dataclass
class RedScore:
    """Score final de Red Team, normalisé 0-100.

    Attributes:
        objective_achieved: True si Red a atteint l'objectif (flag/credentials).
        services_compromised: Nombre de services où Red a obtenu un accès.
        detection_evasion: Proportion d'actions Red non détectées par Blue (0.0-1.0).
        efficiency: Rapidité d'exécution — 1.0 si très rapide, 0.0 si tous les rounds
            utilisés. Calculé comme max(0, 1 - rounds_used/max_rounds).
        technique_diversity: Nombre de MoveType distincts utilisés.
        penalties: Points de pénalité cumulés (exploits ratés + techniques répétées).
        rounds_used: Nombre de rounds effectivement joués.
        breakdown: Détail des points par composante (pour le DPO et le debug).
        notes: Annotations qualitatives générées pendant le scoring.
        total: Score composite normalisé [0, 100]. Calculé automatiquement.
    """

    objective_achieved: bool = False
    services_compromised: int = 0
    detection_evasion: float = 0.0
    efficiency: float = 0.0
    technique_diversity: int = 0
    penalties: float = 0.0
    rounds_used: int = 0
    breakdown: dict[str, float] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    total: float = field(init=False, default=0.0)

    def __post_init__(self) -> None:
        """Calcule le score total après initialisation des champs."""
        self.total = self._compute_total()

    def _compute_total(self) -> float:
        """Formule : 40% objectif + 20% évasion + 15% diversité + 15% efficacité + 10% services.

        Returns:
            Score normalisé dans [0.0, 100.0].
        """
        pts = 0.0

        # 40 pts — objectif (binaire)
        pts += RED_MAX_POINTS["objective"] * int(self.objective_achieved)

        # 20 pts — évasion (ratio continu)
        pts += RED_MAX_POINTS["evasion"] * max(0.0, min(1.0, self.detection_evasion))

        # 15 pts — diversité (3 pts par technique distincte, max 5 techniques → 15)
        pts += min(RED_MAX_POINTS["diversity"], 3.0 * self.technique_diversity)

        # 15 pts — efficacité (ratio continu : plus vite = plus de points)
        pts += RED_MAX_POINTS["efficiency"] * max(0.0, min(1.0, self.efficiency))

        # 10 pts — services compromis (5 pts par service, cap à 2 → 10)
        pts += min(RED_MAX_POINTS["services"], 5.0 * self.services_compromised)

        # Pénalités (max RED_MAX_PENALTY)
        pts -= min(RED_MAX_PENALTY, self.penalties)

        return max(0.0, min(100.0, pts))

    def to_dict(self) -> dict:
        """Sérialise en dict JSON-compatible."""
        return {
            "total": round(self.total, 1),
            "objective_achieved": self.objective_achieved,
            "services_compromised": self.services_compromised,
            "detection_evasion": round(self.detection_evasion, 3),
            "efficiency": round(self.efficiency, 3),
            "technique_diversity": self.technique_diversity,
            "penalties": round(self.penalties, 1),
            "rounds_used": self.rounds_used,
            "breakdown": {k: round(v, 2) for k, v in self.breakdown.items()},
            "notes": self.notes,
        }


# ---------------------------------------------------------------------------
# BlueScore
# ---------------------------------------------------------------------------

@dataclass
class BlueScore:
    """Score final de Blue Team, normalisé 0-100.

    Attributes:
        detected_intrusion: True si Blue a identifié qu'une attaque était en cours.
        detection_round: Round (1-indexed) de la première détection. 0 = jamais.
        total_rounds: Nombre total de rounds du match (pour calculer l'early detection).
        sigma_rules_valid: Nombre de règles Sigma structurellement valides.
        sigma_rules_matching: Parmi les valides, combien matchent les logs d'attaque.
        patch_proposed: True si Blue a proposé un patch ou une mesure de hardening.
        root_cause_identified: True si Blue a nommé la bonne technique/CVE.
        false_positives: Nombre d'alertes sur du trafic légitime (noise-gen).
        service_disruption: Nombre de services cassés par les actions défensives.
        breakdown: Détail des points par composante.
        notes: Annotations qualitatives.
        total: Score composite normalisé [0, 100]. Calculé automatiquement.
    """

    detected_intrusion: bool = False
    detection_round: int = 0
    total_rounds: int = 1
    sigma_rules_valid: int = 0
    sigma_rules_matching: int = 0
    patch_proposed: bool = False
    root_cause_identified: bool = False
    false_positives: int = 0
    service_disruption: int = 0
    breakdown: dict[str, float] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    total: float = field(init=False, default=0.0)

    def __post_init__(self) -> None:
        """Calcule le score total après initialisation des champs."""
        self.total = self._compute_total()

    @property
    def early_detection(self) -> bool:
        """True si la première détection s'est faite dans les 30 % premiers rounds."""
        if self.detection_round <= 0 or self.total_rounds <= 0:
            return False
        return (self.detection_round / self.total_rounds) <= EARLY_DETECTION_THRESHOLD

    def _compute_total(self) -> float:
        """Formule : 30% détection + 25% Sigma + 20% patch + 15% root_cause + 10% disruption.

        Returns:
            Score normalisé dans [0.0, 100.0].
        """
        pts = 0.0

        # 30 pts — détection (plein si précoce, partial si tardive)
        if self.detected_intrusion:
            if self.detection_round > 0 and self.total_rounds > 0:
                timing = self.detection_round / self.total_rounds
                if timing <= EARLY_DETECTION_THRESHOLD:
                    pts += BLUE_MAX_POINTS["detection"]  # 30 pts
                else:
                    # Dégradation linéaire : 30 → 15 sur la deuxième moitié des rounds
                    pts += BLUE_MAX_POINTS["detection"] * (1.0 - 0.5 * timing)
            else:
                pts += BLUE_MAX_POINTS["detection"]

        # 25 pts — Sigma : valid (4 pts/règle, max 15) + matching (5 pts/règle, max 10)
        sigma_pts = min(15.0, 4.0 * self.sigma_rules_valid)
        sigma_pts += min(10.0, 5.0 * self.sigma_rules_matching)
        pts += min(BLUE_MAX_POINTS["sigma"], sigma_pts)

        # 20 pts — patch proposé (binaire)
        if self.patch_proposed:
            pts += BLUE_MAX_POINTS["patch"]

        # 15 pts — root cause identifiée (binaire)
        if self.root_cause_identified:
            pts += BLUE_MAX_POINTS["root_cause"]

        # 10 pts — pas de disruption de service (binaire)
        if self.service_disruption == 0:
            pts += BLUE_MAX_POINTS["disruption"]

        # Pénalités faux positifs (max BLUE_MAX_FP_PENALTY)
        pts -= min(BLUE_MAX_FP_PENALTY, BLUE_PENALTY_PER_FALSE_POSITIVE * self.false_positives)

        return max(0.0, min(100.0, pts))

    def to_dict(self) -> dict:
        """Sérialise en dict JSON-compatible."""
        return {
            "total": round(self.total, 1),
            "detected_intrusion": self.detected_intrusion,
            "detection_round": self.detection_round,
            "early_detection": self.early_detection,
            "total_rounds": self.total_rounds,
            "sigma_rules_valid": self.sigma_rules_valid,
            "sigma_rules_matching": self.sigma_rules_matching,
            "patch_proposed": self.patch_proposed,
            "root_cause_identified": self.root_cause_identified,
            "false_positives": self.false_positives,
            "service_disruption": self.service_disruption,
            "breakdown": {k: round(v, 2) for k, v in self.breakdown.items()},
            "notes": self.notes,
        }


# ---------------------------------------------------------------------------
# Scorer
# ---------------------------------------------------------------------------

class Scorer:
    """Score déterministe d'un match Purple Team.

    Aucun LLM dans le scoring — 100 % algorithmique.
    Trois méthodes peuvent être appelées indépendamment (utile pour les tests) :
      - validate_sigma_rule()   — méthode statique
      - check_objective()       — méthode statique
      - calculate_evasion_rate()

    Example:
        scorer = Scorer()
        red = scorer.score_red(rounds, scenario)
        blue = scorer.score_blue(rounds, scenario)
        print(f"Red: {red.total:.1f}  Blue: {blue.total:.1f}")
        winner = "red" if red.total > blue.total else "blue"
    """

    def __init__(self, cyber_range: "CyberRange | None" = None) -> None:
        """Initialise le scorer.

        Args:
            cyber_range: Instance CyberRange active. Réservé pour un futur
                replay d'exploit lors de la validation de patch (pas encore implémenté).
        """
        self._cyber_range = cyber_range

    # ------------------------------------------------------------------
    # Public API — top-level scoring
    # ------------------------------------------------------------------

    def score_red(
        self,
        rounds: list["RoundData"],
        scenario: "ScenarioConfig",
    ) -> RedScore:
        """Calcule le score Red depuis les rounds d'un match.

        Args:
            rounds: Tous les RoundData du match.
            scenario: ScenarioConfig du scénario joué.

        Returns:
            RedScore avec total normalisé 0-100.
        """
        from .match_protocol import MatchPhase

        red_rounds = [r for r in rounds if r.red_move is not None]
        blue_analyses = [r.blue_move.content for r in rounds if r.blue_move]

        # ---- Métriques ----
        objective_achieved = self.check_objective(
            self._collect_red_outputs(rounds), scenario
        )
        services_compromised = self._count_compromised_services(rounds, MatchPhase)
        evasion = self.calculate_evasion_rate(
            self._build_red_actions(rounds, scenario), blue_analyses
        )
        diversity = self._count_move_type_diversity(rounds)
        failed = self._count_failed_exploits(rounds, MatchPhase)
        repeated = self._count_repeated_techniques(rounds)
        rounds_used = len(red_rounds)
        max_rounds = max(scenario.max_rounds, 1)
        efficiency = max(0.0, 1.0 - rounds_used / max_rounds)
        penalties = min(
            RED_MAX_PENALTY,
            failed * RED_PENALTY_PER_FAILED_EXPLOIT
            + repeated * RED_PENALTY_PER_REPEAT_TECHNIQUE,
        )

        breakdown = {
            "objective":  RED_MAX_POINTS["objective"] * int(objective_achieved),
            "evasion":    round(RED_MAX_POINTS["evasion"] * evasion, 2),
            "diversity":  round(min(RED_MAX_POINTS["diversity"], 3.0 * diversity), 2),
            "efficiency": round(RED_MAX_POINTS["efficiency"] * efficiency, 2),
            "services":   round(min(RED_MAX_POINTS["services"], 5.0 * services_compromised), 2),
            "penalties":  round(-penalties, 2),
        }

        notes: list[str] = []
        if objective_achieved:
            notes.append(f"Flag exfiltrated successfully.")
        if evasion >= 0.8:
            notes.append(f"Excellent evasion rate: {evasion:.0%} of actions undetected.")
        elif evasion <= 0.2:
            notes.append(f"Poor evasion: Blue detected {1-evasion:.0%} of actions.")
        if failed > 0:
            notes.append(f"{failed} failed exploit(s) — indicates noise or poor recon.")
        if repeated > 0:
            notes.append(f"{repeated} repeated technique(s) — reduces diversity score.")

        score = RedScore(
            objective_achieved=objective_achieved,
            services_compromised=services_compromised,
            detection_evasion=evasion,
            efficiency=efficiency,
            technique_diversity=diversity,
            penalties=penalties,
            rounds_used=rounds_used,
            breakdown=breakdown,
            notes=notes,
        )
        logger.info(
            f"Red score: {score.total:.1f}/100 "
            f"(obj={objective_achieved}, evasion={evasion:.2f}, div={diversity})"
        )
        return score

    def score_blue(
        self,
        rounds: list["RoundData"],
        scenario: "ScenarioConfig",
    ) -> BlueScore:
        """Calcule le score Blue depuis les rounds d'un match.

        Args:
            rounds: Tous les RoundData du match.
            scenario: ScenarioConfig du scénario joué.

        Returns:
            BlueScore avec total normalisé 0-100.
        """
        from .match_protocol import MatchPhase

        total_rounds = max(len(rounds), 1)
        attack_logs = self._collect_siem_logs(rounds)

        # ---- Métriques ----
        detected, detection_round = self._check_detection(rounds)
        sigma_valid, sigma_matching = self._validate_and_match_sigma(rounds, attack_logs)
        patch_proposed = self._check_patch_proposed(rounds)
        root_cause = self._check_root_cause(rounds, scenario)
        false_positives = self._count_false_positives(rounds)
        service_disruption = self._count_service_disruptions(rounds)

        breakdown = {
            "detection": round(
                BLUE_MAX_POINTS["detection"] * int(detected)
                * (1.0 if (detection_round > 0 and detection_round / total_rounds <= EARLY_DETECTION_THRESHOLD)
                   else (1.0 - 0.5 * detection_round / total_rounds if detection_round > 0 else 1.0)),
                2,
            ),
            "sigma_valid":    round(min(15.0, 4.0 * sigma_valid), 2),
            "sigma_matching": round(min(10.0, 5.0 * sigma_matching), 2),
            "patch":          BLUE_MAX_POINTS["patch"] * int(patch_proposed),
            "root_cause":     BLUE_MAX_POINTS["root_cause"] * int(root_cause),
            "disruption":     BLUE_MAX_POINTS["disruption"] * int(service_disruption == 0),
            "fp_penalty":     round(-BLUE_PENALTY_PER_FALSE_POSITIVE * false_positives, 2),
        }

        notes: list[str] = []
        if detected:
            timing_pct = f"{detection_round / total_rounds:.0%}" if detection_round > 0 else "?"
            suffix = " (early!)" if detection_round > 0 and detection_round / total_rounds <= EARLY_DETECTION_THRESHOLD else ""
            notes.append(f"Intrusion detected at round {detection_round}/{total_rounds} ({timing_pct}){suffix}.")
        else:
            notes.append("Intrusion NOT detected.")
        if sigma_valid > 0:
            notes.append(f"{sigma_valid} valid Sigma rule(s), {sigma_matching} matching attack logs.")
        if not patch_proposed:
            notes.append("No patch or hardening proposed.")
        if false_positives > 0:
            notes.append(f"{false_positives} false positive(s) on legitimate traffic.")
        if service_disruption > 0:
            notes.append(f"WARNING: {service_disruption} service disruption(s) detected.")

        score = BlueScore(
            detected_intrusion=detected,
            detection_round=detection_round,
            total_rounds=total_rounds,
            sigma_rules_valid=sigma_valid,
            sigma_rules_matching=sigma_matching,
            patch_proposed=patch_proposed,
            root_cause_identified=root_cause,
            false_positives=false_positives,
            service_disruption=service_disruption,
            breakdown=breakdown,
            notes=notes,
        )
        logger.info(
            f"Blue score: {score.total:.1f}/100 "
            f"(detected={detected}, sigma={sigma_valid}/{sigma_matching}, patch={patch_proposed})"
        )
        return score

    # ------------------------------------------------------------------
    # Public API — standalone validators (testables indépendamment)
    # ------------------------------------------------------------------

    @staticmethod
    def validate_sigma_rule(
        yaml_str: str,
        attack_logs: list[str] | None = None,
    ) -> SigmaValidation:
        """Valide une règle Sigma YAML et teste si elle matche des logs d'attaque.

        Vérifications effectuées (dans l'ordre) :
          1. YAML syntaxiquement valide (yaml.safe_load)
          2. Type racine = dict
          3. Présence des champs obligatoires : title, logsource, detection
          4. `title` est une chaîne non-vide
          5. `logsource` est un dict avec au moins un champ (category/product/service)
          6. `detection` est un dict contenant `condition`
          7. `condition` est une chaîne non-vide
          8. (optionnel) Si attack_logs fournis : test de matching par keywords

        Args:
            yaml_str: Contenu YAML brut de la règle Sigma.
            attack_logs: Lignes de log SIEM de l'attaque (optionnel).
                Si fourni, teste si la règle matche au moins un log.

        Returns:
            SigmaValidation avec valid, matches_attack, errors, title,
            detection_keywords, rule_hash.
        """
        import hashlib

        errors: list[str] = []
        title = ""
        detection_keywords: list[str] = []
        rule_hash = hashlib.md5(yaml_str.strip().encode()).hexdigest()[:8]

        # 1. Import PyYAML
        try:
            import yaml
        except ImportError:
            return SigmaValidation(
                valid=False,
                matches_attack=False,
                errors=["PyYAML not installed — pip install pyyaml"],
                rule_hash=rule_hash,
            )

        # 2. Parse YAML
        try:
            parsed = yaml.safe_load(yaml_str)
        except yaml.YAMLError as e:
            return SigmaValidation(
                valid=False,
                matches_attack=False,
                errors=[f"YAML parse error: {e}"],
                rule_hash=rule_hash,
            )

        if not isinstance(parsed, dict):
            return SigmaValidation(
                valid=False,
                matches_attack=False,
                errors=["Root element must be a YAML mapping (dict)"],
                rule_hash=rule_hash,
            )

        # 3. Champs obligatoires racine
        missing = SIGMA_REQUIRED_ROOT - parsed.keys()
        if missing:
            errors.append(f"Missing required fields: {sorted(missing)}")

        # 4. Validation du champ `title`
        raw_title = parsed.get("title", "")
        if not isinstance(raw_title, str) or not raw_title.strip():
            errors.append("Field 'title' must be a non-empty string")
        else:
            title = raw_title.strip()

        # 5. Validation de `logsource`
        logsource = parsed.get("logsource")
        if logsource is not None:
            if not isinstance(logsource, dict):
                errors.append("Field 'logsource' must be a mapping")
            elif not any(k in logsource for k in ("category", "product", "service")):
                errors.append(
                    "Field 'logsource' must contain at least one of: "
                    "category, product, service"
                )

        # 6. Validation de `detection`
        detection = parsed.get("detection")
        if detection is not None:
            if not isinstance(detection, dict):
                errors.append("Field 'detection' must be a mapping")
            else:
                # 7. `condition` requis dans detection
                condition = detection.get("condition")
                if condition is None:
                    errors.append("'detection.condition' is required")
                elif not isinstance(condition, str) or not condition.strip():
                    errors.append("'detection.condition' must be a non-empty string")

                # Extraire les keywords de detection pour le matching
                detection_keywords = Scorer._extract_sigma_keywords(detection)

        valid = len(errors) == 0

        # 8. Matching contre les logs d'attaque
        matches_attack = False
        if valid and attack_logs and detection_keywords:
            matches_attack = Scorer._sigma_matches_logs(detection_keywords, attack_logs)

        if valid:
            logger.debug(
                f"Sigma rule '{title}' valid — "
                f"{len(detection_keywords)} keywords, matches={matches_attack}"
            )
        else:
            logger.debug(f"Sigma rule invalid: {errors}")

        return SigmaValidation(
            valid=valid,
            matches_attack=matches_attack,
            errors=errors,
            title=title,
            detection_keywords=detection_keywords,
            rule_hash=rule_hash,
        )

    @staticmethod
    def check_objective(
        red_outputs: list[str],
        scenario: "ScenarioConfig",
    ) -> bool:
        """Vérifie si Red a atteint l'objectif du scénario.

        Trois modes de détection (dans l'ordre de priorité) :
          1. Flag exact : cherche scenario.flag_value dans chaque output.
          2. Pattern FLAG{…} : regex pour toute valeur de flag (cas où
             le flag a été imprimé avec un format légèrement différent).
          3. Indicateur de credentials : si l'objectif mentionne "credentials"
             ou "credentials", cherche des patterns username/password dans les outputs.

        Args:
            red_outputs: Liste de chaînes (stdout des commandes exec de Red).
            scenario: ScenarioConfig avec flag_value et objective.

        Returns:
            True si l'objectif est considéré comme atteint.
        """
        if not red_outputs:
            return False

        # 1. Flag exact
        if scenario.flag_value:
            for out in red_outputs:
                if scenario.flag_value in out:
                    logger.info(f"Objective achieved: exact flag match ({scenario.flag_value})")
                    return True

        # 2. Pattern FLAG{...} générique
        flag_pattern = re.compile(r"FLAG\{[0-9a-f]{8,32}\}", re.IGNORECASE)
        for out in red_outputs:
            if flag_pattern.search(out):
                logger.info("Objective achieved: FLAG{...} pattern found in output")
                return True

        # 3. Credential extraction (si objectif le demande)
        objective_lower = scenario.objective.lower()
        if any(kw in objective_lower for kw in ("credential", "password", "admin", "hash")):
            cred_pattern = re.compile(
                r"(password|passwd|pwd|hash)\s*[:=]\s*\S+",
                re.IGNORECASE,
            )
            for out in red_outputs:
                if cred_pattern.search(out):
                    logger.info("Objective achieved: credential extraction pattern found")
                    return True

        return False

    def calculate_evasion_rate(
        self,
        red_actions: list[dict],
        blue_analyses: list[str],
    ) -> float:
        """Calcule le taux d'évasion de Red Team.

        Pour chaque action Red (IP cible + commandes + move_type), vérifie si
        au moins une analyse Blue mentionne des indicateurs de cette action.
        Le taux d'évasion = proportion d'actions non détectées.

        Une action est considérée **détectée** si Blue mentionne :
          - L'IP du service ciblé, OU
          - ≥ 2 mots-clés associés au move_type de l'action, OU
          - Au moins un mot-clé associé aux commandes exécutées.

        Args:
            red_actions: Liste de dicts avec clés :
                - "ip"        : IP du service cible (str, peut être vide)
                - "commands"  : liste de commandes exécutées (list[str])
                - "move_type" : type de move Red (str, ex: "EXPLOIT")
            blue_analyses: Liste des contenus textuels des blue_moves.

        Returns:
            Float dans [0.0, 1.0]. 1.0 = jamais détecté, 0.0 = toujours détecté.
            Retourne 0.5 si aucune action Red ou aucune analyse Blue (valeur neutre).
        """
        if not red_actions:
            return 0.5
        if not blue_analyses:
            # Blue n'a produit aucune analyse → toutes les actions ont évadé
            return 1.0

        combined_blue = " ".join(blue_analyses).lower()
        detected_count = 0

        for action in red_actions:
            if self._is_action_detected(action, combined_blue):
                detected_count += 1

        evasion = 1.0 - (detected_count / len(red_actions))
        logger.debug(
            f"Evasion rate: {evasion:.2f} "
            f"({len(red_actions) - detected_count}/{len(red_actions)} undetected)"
        )
        return round(evasion, 3)

    # ------------------------------------------------------------------
    # Private — action detection helpers
    # ------------------------------------------------------------------

    def _is_action_detected(self, action: dict, blue_text_lower: str) -> bool:
        """Détermine si une action Red spécifique a été détectée par Blue.

        Args:
            action: Dict {"ip", "commands", "move_type"}.
            blue_text_lower: Texte combiné de toutes les analyses Blue, en minuscules.

        Returns:
            True si au moins un indicateur de l'action est présent dans blue_text_lower.
        """
        # Indicateur 1 : IP ciblée mentionnée par Blue
        ip = action.get("ip", "")
        if ip and len(ip) >= 7 and ip in blue_text_lower:
            return True

        # Indicateur 2 : keywords du move_type (≥ 2 matches requis)
        move_type = action.get("move_type", "")
        move_keywords = _MOVE_DETECTION_KEYWORDS.get(move_type, [])
        move_hits = sum(1 for kw in move_keywords if kw in blue_text_lower)
        if move_hits >= 2:
            return True

        # Indicateur 3 : keywords des commandes exécutées (1 match suffit)
        commands = action.get("commands", [])
        for cmd in commands:
            cmd_lower = cmd.lower().split()[0] if cmd.strip() else ""
            cmd_keywords = _COMMAND_DETECTION_KEYWORDS.get(cmd_lower, [])
            if any(kw in blue_text_lower for kw in cmd_keywords):
                return True

        return False

    # ------------------------------------------------------------------
    # Private — Red scoring helpers
    # ------------------------------------------------------------------

    def _collect_red_outputs(self, rounds: list["RoundData"]) -> list[str]:
        """Collecte tous les stdout des execs de Red Team.

        Args:
            rounds: Tous les rounds du match.

        Returns:
            Liste de chaînes (stdout), une par exec_result.
        """
        outputs: list[str] = []
        for r in rounds:
            if r.red_move:
                for er in r.red_move.exec_results:
                    if er.stdout:
                        outputs.append(er.stdout)
                # Inclure aussi le contenu textuel du move (Red peut décrire le flag)
                if r.red_move.content:
                    outputs.append(r.red_move.content)
        return outputs

    def _build_red_actions(
        self,
        rounds: list["RoundData"],
        scenario: "ScenarioConfig",
    ) -> list[dict]:
        """Construit la liste des actions Red pour le calcul d'évasion.

        Args:
            rounds: Tous les rounds.
            scenario: ScenarioConfig pour résoudre les IPs.

        Returns:
            Liste de dicts {"ip", "commands", "move_type"}.
        """
        actions: list[dict] = []
        svc_ip_map = {s.name: s.ip for s in scenario.services}

        for r in rounds:
            if not r.red_move:
                continue
            move = r.red_move

            if move.exec_results:
                for er in move.exec_results:
                    actions.append({
                        "ip": svc_ip_map.get(er.service, ""),
                        "commands": [er.command] if er.command else [],
                        "move_type": move.move_type.value,
                    })
            else:
                # Pas d'execs — action purement textuelle
                actions.append({
                    "ip": "",
                    "commands": move.commands[:3],
                    "move_type": move.move_type.value,
                })

        return actions

    def _count_compromised_services(
        self,
        rounds: list["RoundData"],
        MatchPhase: type,
    ) -> int:
        """Compte les services compromis (exec réussi en phase EXPLOITATION ou POST_EXPLOIT).

        Args:
            rounds: Tous les rounds.
            MatchPhase: Classe enum MatchPhase (passée pour éviter l'import circulaire).

        Returns:
            Nombre de services distincts compromis.
        """
        compromised: set[str] = set()
        for r in rounds:
            if r.red_move and r.phase in (
                MatchPhase.EXPLOITATION, MatchPhase.POST_EXPLOIT
            ):
                for er in r.red_move.exec_results:
                    if er.success and er.service:
                        compromised.add(er.service)
        return len(compromised)

    def _count_move_type_diversity(self, rounds: list["RoundData"]) -> int:
        """Compte les MoveType distincts utilisés par Red.

        Args:
            rounds: Tous les rounds.

        Returns:
            Nombre de MoveType Red distincts.
        """
        types: set[str] = set()
        for r in rounds:
            if r.red_move:
                types.add(r.red_move.move_type.value)
        return len(types)

    def _count_failed_exploits(
        self,
        rounds: list["RoundData"],
        MatchPhase: type,
    ) -> int:
        """Compte les exploits ayant échoué (exec avec exit_code != 0 en EXPLOITATION).

        Args:
            rounds: Tous les rounds.
            MatchPhase: Classe enum MatchPhase.

        Returns:
            Nombre d'exploits ratés.
        """
        count = 0
        for r in rounds:
            if r.red_move and r.phase == MatchPhase.EXPLOITATION:
                for er in r.red_move.exec_results:
                    if not er.success:
                        count += 1
        return count

    def _count_repeated_techniques(self, rounds: list["RoundData"]) -> int:
        """Compte les répétitions de MoveType (même type utilisé 2+ fois).

        Args:
            rounds: Tous les rounds.

        Returns:
            Nombre total de répétitions (total moves Red - distinct move types).
        """
        types: list[str] = [
            r.red_move.move_type.value
            for r in rounds if r.red_move
        ]
        return max(0, len(types) - len(set(types)))

    # ------------------------------------------------------------------
    # Private — Blue scoring helpers
    # ------------------------------------------------------------------

    def _collect_siem_logs(self, rounds: list["RoundData"]) -> list[str]:
        """Collecte tous les logs SIEM de tous les rounds.

        Args:
            rounds: Tous les rounds.

        Returns:
            Liste de lignes de log.
        """
        logs: list[str] = []
        for r in rounds:
            logs.extend(r.siem_logs)
        return logs

    def _check_detection(
        self, rounds: list["RoundData"]
    ) -> tuple[bool, int]:
        """Vérifie si Blue a détecté une intrusion et à quel round.

        Une détection est confirmée si Blue mentionne des mots-clés de
        détection OU si Blue a produit des règles Sigma.

        Args:
            rounds: Tous les rounds.

        Returns:
            Tuple (detected: bool, first_detection_round: int).
            first_detection_round = 0 si jamais détecté.
        """
        for i, r in enumerate(rounds, start=1):
            if not r.blue_move:
                continue
            content_lower = r.blue_move.content.lower()
            has_keywords = any(kw in content_lower for kw in DETECTION_KEYWORDS)
            has_sigma = bool(r.blue_move.sigma_rules)
            if has_keywords or has_sigma:
                return True, i
        return False, 0

    def _validate_and_match_sigma(
        self,
        rounds: list["RoundData"],
        attack_logs: list[str],
    ) -> tuple[int, int]:
        """Valide toutes les règles Sigma et compte celles qui matchent les logs.

        Args:
            rounds: Tous les rounds.
            attack_logs: Logs SIEM collectés pendant le match.

        Returns:
            Tuple (sigma_valid: int, sigma_matching: int).
            sigma_matching <= sigma_valid toujours.
        """
        seen_hashes: set[str] = set()
        valid_count = 0
        matching_count = 0

        for r in rounds:
            if not r.blue_move:
                continue
            for rule_str in r.blue_move.sigma_rules:
                result = self.validate_sigma_rule(rule_str, attack_logs)
                # Déduplication par hash pour éviter de compter la même règle deux fois
                if result.rule_hash in seen_hashes:
                    continue
                seen_hashes.add(result.rule_hash)

                if result.valid:
                    valid_count += 1
                    if result.matches_attack:
                        matching_count += 1

        return valid_count, matching_count

    def _check_patch_proposed(self, rounds: list["RoundData"]) -> bool:
        """Vérifie si Blue a proposé un patch ou une mesure de hardening.

        Args:
            rounds: Tous les rounds.

        Returns:
            True si au moins un blue_move mentionne un patch.
        """
        from .match_protocol import MatchPhase
        for r in rounds:
            if r.blue_move and r.phase in (MatchPhase.REMEDIATION, MatchPhase.POST_EXPLOIT):
                content_lower = r.blue_move.content.lower()
                if any(kw in content_lower for kw in PATCH_KEYWORDS):
                    return True
        # Fallback : toute mention de patch dans n'importe quelle phase
        for r in rounds:
            if r.blue_move:
                content_lower = r.blue_move.content.lower()
                if any(kw in content_lower for kw in PATCH_KEYWORDS[:5]):
                    return True
        return False

    def _check_root_cause(
        self,
        rounds: list["RoundData"],
        scenario: "ScenarioConfig",
    ) -> bool:
        """Vérifie si Blue a identifié la bonne technique ou CVE d'attaque.

        Cherche dans les textes Blue :
          1. Les IDs de techniques MITRE ATT&CK du scénario (ex: "T1190")
          2. Les noms de techniques ATT&CK (ex: "exploit public-facing")
          3. Les noms des vulnérabilités actives (ex: "sqli", "log4shell")

        Args:
            rounds: Tous les rounds.
            scenario: ScenarioConfig avec mitre_techniques et services.vulns.

        Returns:
            True si au moins une correspondance trouvée.
        """
        blue_text = " ".join(
            r.blue_move.content for r in rounds if r.blue_move
        ).lower()

        # Techniques MITRE (ex: "T1190", "t1190")
        for tech_id in scenario.mitre_techniques:
            if tech_id.lower() in blue_text:
                logger.debug(f"Root cause: MITRE {tech_id} found in Blue analysis")
                return True

        # Noms de techniques (ex: "exploit public-facing application")
        try:
            from .scenario_generator import MITRE_TECHNIQUES
            for tech_id in scenario.mitre_techniques:
                tech_name = MITRE_TECHNIQUES.get(tech_id, "").lower()
                if tech_name and len(tech_name) > 5 and tech_name in blue_text:
                    logger.debug(f"Root cause: technique name '{tech_name}' found")
                    return True
        except ImportError:
            pass

        # Noms des vulnérabilités actives dans les services
        for svc in scenario.services:
            for vuln in svc.vulns:
                # "log4shell_cve_2021_44228" → ["log4shell", "cve", "2021", "44228"]
                keywords = re.split(r"[_\-]", vuln)
                for kw in keywords:
                    if len(kw) >= 4 and kw in blue_text:
                        logger.debug(f"Root cause: vuln keyword '{kw}' found in Blue analysis")
                        return True

        return False

    def _count_false_positives(self, rounds: list["RoundData"]) -> int:
        """Compte les alertes Blue sur du trafic légitime (faux positifs).

        Heuristique : round avec blue_move alertant MAIS sans red_move
        correspondant ET dont les logs SIEM ne contiennent que du trafic normal.

        Args:
            rounds: Tous les rounds.

        Returns:
            Nombre estimé de faux positifs.
        """
        count = 0
        for r in rounds:
            if r.blue_move and r.red_move is None:
                content_lower = r.blue_move.content.lower()
                if any(kw in content_lower for kw in DETECTION_KEYWORDS):
                    # Blue alerte sans qu'il y ait eu d'action Red → faux positif
                    count += 1
        return count

    def _count_service_disruptions(self, rounds: list["RoundData"]) -> int:
        """Compte les disruptions de service causées par Blue (sur-réaction).

        Args:
            rounds: Tous les rounds.

        Returns:
            Nombre de sur-réactions détectées.
        """
        count = 0
        for r in rounds:
            if r.blue_move:
                content_lower = r.blue_move.content.lower()
                if any(kw in content_lower for kw in DISRUPTION_KEYWORDS):
                    count += 1
        return count

    # ------------------------------------------------------------------
    # Public — Patch effectiveness test (async, requires live CyberRange)
    # ------------------------------------------------------------------

    async def _test_patch(
        self,
        match: "MatchResult",
        cyber_range: "CyberRange",
    ) -> bool:
        """Vérifie si le patch Blue neutralise l'exploit Red (replay sur conteneurs live).

        Séquence :
          a) Extraire la dernière commande de remédiation des blocs de code Blue.
          b) Trouver le premier exec Red réussi (exit_code=0 + indicateur de compromission).
             Si aucun → True (rien à vérifier).
          c) Appliquer le patch via exec_command (timeout 15s) + attendre 2s.
          d) Rejouer l'exploit ; si exit_code ≠ 0 OU sortie sans indicateur → True (patch OK).
             Sinon → False (patch inefficace).

        En cas d'erreur à n'importe quelle étape → log + return False (conservatif).

        Args:
            match: Résultat de match avec rounds et scénario.
            cyber_range: CyberRange en état HEALTHY/DEGRADED.

        Returns:
            True si le patch est efficace (ou s'il n'y a rien à tester), False sinon.
        """
        # ── Step a: Extract last Blue remediation command ─────────────────────
        patch_cmd: str | None = None

        for r in match.rounds:
            if r.blue_move is None:
                continue
            content = r.blue_move.content
            for block_match in _CODE_BLOCK_RE.finditer(content):
                block = block_match.group(1).strip()
                if not block:
                    continue
                block_lower = block.lower()
                if any(kw in block_lower for kw in _PATCH_CODE_KEYWORDS):
                    # Take first non-empty line of the block as the runnable command
                    first_line = next(
                        (ln.strip() for ln in block.splitlines() if ln.strip()), None
                    )
                    if first_line:
                        patch_cmd = first_line  # last valid block wins (loop continues)

        if patch_cmd is None:
            logger.info("_test_patch: no Blue patch code block found → True (no patch to test)")
            return True

        # ── Step b: Find first successful Red exploit ─────────────────────────
        red_exploit = None
        for r in match.rounds:
            if r.red_move is None:
                continue
            for er in r.red_move.exec_results:
                if er.exit_code == 0:
                    out_lower = (er.stdout or "").lower()
                    if any(ind in out_lower for ind in _COMPROMISE_INDICATORS):
                        red_exploit = er
                        break
            if red_exploit is not None:
                break

        if red_exploit is None:
            logger.info("_test_patch: no successful Red exploit found → True (nothing to replay)")
            return True

        target_service = red_exploit.service
        exploit_cmd = red_exploit.command

        # ── Step c: Apply the patch ───────────────────────────────────────────
        try:
            patch_result = await asyncio.wait_for(
                cyber_range.exec_command(target_service, patch_cmd, timeout=15),
                timeout=15.0,
            )
        except Exception as e:
            logger.error(f"_test_patch: patch application failed: {e}")
            return False

        if patch_result.exit_code != 0:
            logger.warning(
                f"_test_patch: patch command returned exit_code={patch_result.exit_code}, "
                f"stderr={patch_result.stderr!r} — treating as patch failure"
            )
            return False

        await asyncio.sleep(2)

        # ── Step d: Replay the exploit ────────────────────────────────────────
        try:
            replay_result = await asyncio.wait_for(
                cyber_range.exec_command(target_service, exploit_cmd, timeout=15),
                timeout=15.0,
            )
        except Exception as e:
            logger.error(f"_test_patch: exploit replay failed: {e}")
            return False

        replay_out_lower = (replay_result.stdout or "").lower()
        exploit_neutralized = (
            replay_result.exit_code != 0
            or not any(ind in replay_out_lower for ind in _COMPROMISE_INDICATORS)
        )

        if exploit_neutralized:
            logger.info(
                f"_test_patch: patch EFFECTIVE — replay exit_code={replay_result.exit_code}, "
                "output no longer contains compromise indicators"
            )
        else:
            logger.warning(
                f"_test_patch: patch INEFFECTIVE — replay exit_code={replay_result.exit_code}, "
                "compromise indicators still present in output"
            )

        return exploit_neutralized

    # ------------------------------------------------------------------
    # Private — Sigma helpers (statiques)
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_sigma_keywords(detection: dict) -> list[str]:
        """Extrait les chaînes de recherche depuis le bloc detection d'une règle Sigma.

        Parcourt récursivement le bloc detection en ignorant `condition`.
        Retourne toutes les valeurs string non-vides trouvées.

        Args:
            detection: Dict du bloc `detection:` d'une règle Sigma.

        Returns:
            Liste de chaînes/patterns à rechercher dans les logs.
        """
        keywords: list[str] = []

        def _walk(obj: object) -> None:
            if isinstance(obj, str) and obj.strip():
                keywords.append(obj.strip().lower())
            elif isinstance(obj, list):
                for item in obj:
                    _walk(item)
            elif isinstance(obj, dict):
                for key, val in obj.items():
                    if key == "condition":
                        continue  # la condition est une expression, pas un keyword
                    _walk(val)

        _walk(detection)
        return keywords

    @staticmethod
    def _sigma_matches_logs(keywords: list[str], logs: list[str]) -> bool:
        """Vérifie si au moins un keyword Sigma apparaît dans les logs.

        Matching simple : substring case-insensitive.

        Args:
            keywords: Patterns extraits de la règle Sigma.
            logs: Lignes de log SIEM.

        Returns:
            True si au moins un keyword matche au moins une ligne de log.
        """
        if not keywords or not logs:
            return False
        logs_combined = "\n".join(logs).lower()
        return any(kw in logs_combined for kw in keywords if len(kw) >= 3)
