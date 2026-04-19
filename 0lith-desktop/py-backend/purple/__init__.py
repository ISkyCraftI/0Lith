"""
0Lith — Purple Team Module
==========================
Orchestrateur Game Master pour les simulations adversariales Red vs Blue.

Génère des environnements Docker conteneurisés dynamiques, orchestre des matchs
en 6 phases, score de façon déterministe, et exporte des paires DPO pour fine-tuning.

Architecture (cf. files/02_PURPLE_TEAM_DIGITAL_TWIN.md) :
  - 80 % code Python déterministe (scénarios, Docker, scoring, export)
  - 20 % LLM uniquement pour les briefings narratifs et cas ambigus

Usage:
    from purple import ScenarioGenerator, CyberRange, MatchProtocol, Scorer, DPOExporter
"""

from .scenario_generator import ScenarioGenerator, ScenarioConfig, ServiceConfig
from .cyber_range import CyberRange, RangeStatus
from .match_protocol import MatchProtocol, MatchResult, RoundData, MatchPhase
from .scorer import Scorer, RedScore, BlueScore
from .dpo_exporter import DPOExporter, DPOPair
from .safety_checks import SafetyChecker, SafetyCheckResult

__all__ = [
    # Scenario
    "ScenarioGenerator",
    "ScenarioConfig",
    "ServiceConfig",
    # Range
    "CyberRange",
    "RangeStatus",
    # Match
    "MatchProtocol",
    "MatchResult",
    "RoundData",
    "MatchPhase",
    # Scoring
    "Scorer",
    "RedScore",
    "BlueScore",
    # Export
    "DPOExporter",
    "DPOPair",
    # Safety
    "SafetyChecker",
    "SafetyCheckResult",
]

__version__ = "0.1.0"
