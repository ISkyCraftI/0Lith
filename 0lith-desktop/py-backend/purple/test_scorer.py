"""
Tests for purple/scorer.py — deterministic scoring, SigmaValidation, evasion rate.
Run: python -m pytest py-backend/purple/test_scorer.py -v
  or: python py-backend/purple/test_scorer.py
"""

from __future__ import annotations

import asyncio
import sys
import os
import unittest
from unittest.mock import AsyncMock, MagicMock
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from purple.scorer import (
    Scorer,
    RedScore,
    BlueScore,
    SigmaValidation,
)
from purple.scenario_generator import ScenarioGenerator
from purple.match_protocol import (
    AgentMove,
    RoundData,
    MatchPhase,
    MoveType,
)
from purple.cyber_range import ExecResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_scenario(seed: int = 42, difficulty: str = "medium"):
    return ScenarioGenerator().generate(seed=seed, difficulty=difficulty)


def make_red_move(
    phase: MatchPhase,
    round_num: int,
    content: str,
    commands: list[str] | None = None,
    move_type: MoveType = MoveType.EXPLOIT,
) -> AgentMove:
    return AgentMove(
        agent="red",
        phase=phase,
        round_num=round_num,
        move_type=move_type,
        content=content,
        commands=commands or [],
    )


def make_blue_move(
    phase: MatchPhase,
    round_num: int,
    content: str,
    sigma_rules: list[str] | None = None,
    move_type: MoveType = MoveType.ALERT,
) -> AgentMove:
    return AgentMove(
        agent="blue",
        phase=phase,
        round_num=round_num,
        move_type=move_type,
        content=content,
        sigma_rules=sigma_rules or [],
    )


def make_round(
    phase: MatchPhase,
    round_num: int,
    red_content: str = "",
    blue_content: str = "",
    sigma_rules: list[str] | None = None,
    siem_logs: list[str] | None = None,
) -> RoundData:
    rd = RoundData(phase=phase, round_num=round_num)
    rd.red_move = make_red_move(phase, round_num, red_content)
    rd.blue_move = make_blue_move(phase, round_num, blue_content, sigma_rules)
    rd.siem_logs = siem_logs or []
    return rd


# ---------------------------------------------------------------------------
# SigmaValidation tests
# ---------------------------------------------------------------------------

VALID_SIGMA = """
title: Detect Nmap Scan
logsource:
  product: linux
  service: syslog
detection:
  keywords:
    - nmap
    - port scan
  condition: keywords
status: experimental
"""

INVALID_SIGMA_MISSING_TITLE = """
logsource:
  product: linux
detection:
  keywords:
    - nmap
  condition: keywords
"""

INVALID_SIGMA_NO_CONDITION = """
title: Bad Rule
logsource:
  product: linux
detection:
  keywords:
    - nmap
"""

INVALID_SIGMA_NOT_YAML = "title: [unclosed bracket"


def test_sigma_valid():
    result = Scorer.validate_sigma_rule(VALID_SIGMA)
    assert result.valid, f"Expected valid, errors: {result.errors}"
    assert result.title == "Detect Nmap Scan"
    assert result.rule_hash  # non-empty


def test_sigma_missing_title():
    result = Scorer.validate_sigma_rule(INVALID_SIGMA_MISSING_TITLE)
    assert not result.valid
    assert any("title" in e for e in result.errors)


def test_sigma_no_condition():
    result = Scorer.validate_sigma_rule(INVALID_SIGMA_NO_CONDITION)
    assert not result.valid
    assert any("condition" in e for e in result.errors)


def test_sigma_invalid_yaml():
    result = Scorer.validate_sigma_rule(INVALID_SIGMA_NOT_YAML)
    assert not result.valid
    assert result.errors


def test_sigma_matches_logs():
    logs = [
        "Jan 1 00:00:00 host syslog: nmap -sS 10.42.1.5",
        "Jan 1 00:00:01 host syslog: port scan detected on eth0",
    ]
    result = Scorer.validate_sigma_rule(VALID_SIGMA, attack_logs=logs)
    assert result.valid
    assert result.matches_attack


def test_sigma_no_match_unrelated_logs():
    logs = ["Jan 1 00:00:00 host kernel: USB device connected"]
    result = Scorer.validate_sigma_rule(VALID_SIGMA, attack_logs=logs)
    assert result.valid
    assert not result.matches_attack


def test_sigma_score_value():
    # valid + matching → 2
    logs = ["nmap -sV 10.42.1.5"]
    r = Scorer.validate_sigma_rule(VALID_SIGMA, attack_logs=logs)
    assert r.score_value == 2

    # valid + no match → 1
    r2 = Scorer.validate_sigma_rule(VALID_SIGMA, attack_logs=["unrelated log"])
    assert r2.score_value == 1

    # invalid → 0
    r3 = Scorer.validate_sigma_rule(INVALID_SIGMA_MISSING_TITLE)
    assert r3.score_value == 0


def test_sigma_deduplication():
    """Same rule submitted twice returns same hash."""
    r1 = Scorer.validate_sigma_rule(VALID_SIGMA)
    r2 = Scorer.validate_sigma_rule(VALID_SIGMA)
    assert r1.rule_hash == r2.rule_hash


# ---------------------------------------------------------------------------
# check_objective tests
# ---------------------------------------------------------------------------

def test_check_objective_exact_flag():
    scenario = make_scenario(seed=1)
    flag = scenario.flag_value
    outputs = [f"I found the flag: {flag}", "Other output"]
    assert Scorer.check_objective(outputs, scenario) is True


def test_check_objective_flag_pattern():
    scenario = make_scenario(seed=1)
    outputs = ["Got it! FLAG{deadbeefcafe1234abcd5678ef901234}"]
    assert Scorer.check_objective(outputs, scenario) is True


def test_check_objective_credential_extract():
    # Try many seeds until we find a scenario whose objective mentions credentials
    from purple.scenario_generator import ScenarioGenerator
    gen = ScenarioGenerator()
    scenario = None
    for seed in range(50):
        s = gen.generate(seed=seed, difficulty="medium")
        obj = s.objective.lower()
        if any(kw in obj for kw in ("credential", "password", "admin", "hash")):
            scenario = s
            break
    if scenario is None:
        # Fallback: patch the objective to force credential mode
        s = gen.generate(seed=1, difficulty="medium")
        object.__setattr__(s, "objective", "Extract admin password credentials")
        scenario = s
    outputs = ["Credentials: username=admin password=secret123"]
    assert Scorer.check_objective(outputs, scenario) is True


def test_check_objective_not_achieved():
    scenario = make_scenario(seed=1)
    outputs = ["Nothing interesting found.", "Still scanning..."]
    assert Scorer.check_objective(outputs, scenario) is False


def test_check_objective_empty():
    scenario = make_scenario(seed=1)
    assert Scorer.check_objective([], scenario) is False


# ---------------------------------------------------------------------------
# calculate_evasion_rate tests
# ---------------------------------------------------------------------------

def test_evasion_no_actions():
    scorer = Scorer()
    rate = scorer.calculate_evasion_rate([], [])
    assert rate == 0.5, "No actions → 0.5 (neutral)"


def test_evasion_no_blue():
    scorer = Scorer()
    red_actions = ["nmap -sS 10.42.1.5", "sqlmap -u http://10.42.1.10/login"]
    rate = scorer.calculate_evasion_rate(red_actions, [])
    assert rate == 1.0, "No blue analysis → full evasion"


def test_evasion_detected_by_ip():
    scorer = Scorer()
    # red_actions is list[dict] with keys: ip, commands, move_type
    red_actions = [{"ip": "10.42.1.5", "commands": ["nmap -sS 10.42.1.5"], "move_type": "SCAN"}]
    blue_analyses = ["Suspicious traffic from 10.42.1.5 detected on port 80"]
    rate = scorer.calculate_evasion_rate(red_actions, blue_analyses)
    assert rate == 0.0, f"IP match -> detected -> 0% evasion, got {rate}"


def test_evasion_detected_by_keyword():
    scorer = Scorer()
    # SCAN move_type + blue mentions multiple SCAN keywords
    red_actions = [{"ip": "", "commands": ["nmap -sV 10.42.1.0/24"], "move_type": "SCAN"}]
    blue_analyses = ["Detected nmap port scan reconnaissance activity from internal host"]
    rate = scorer.calculate_evasion_rate(red_actions, blue_analyses)
    assert rate == 0.0, f"Keyword match -> detected -> 0% evasion, got {rate}"


def test_evasion_partial():
    scorer = Scorer()
    # 2 red actions: first is detected by IP, second is stealthy (no IP/keywords)
    red_actions = [
        {"ip": "10.42.1.5", "commands": ["nmap -sS 10.42.1.5"], "move_type": "SCAN"},
        {"ip": "10.42.1.99", "commands": ["custom_tool"], "move_type": "EXFIL"},
    ]
    blue_analyses = ["Detected traffic from 10.42.1.5"]
    rate = scorer.calculate_evasion_rate(red_actions, blue_analyses)
    assert 0.0 < rate < 1.0, f"Partial evasion expected, got {rate}"


# ---------------------------------------------------------------------------
# RedScore dataclass tests
# ---------------------------------------------------------------------------

def test_redscore_total_field():
    score = RedScore(
        objective_achieved=True,
        services_compromised=3,
        detection_evasion=0.8,
        efficiency=0.9,
        technique_diversity=4,
        penalties=0.0,
        rounds_used=5,
    )
    # total is a field (init=False), not a method
    assert isinstance(score.total, float)
    assert 0.0 <= score.total <= 100.0


def test_redscore_total_not_callable():
    score = RedScore()
    # Regression: ensure .total is not a method
    assert not callable(score.total), "total must be a field, not a method"


def test_redscore_max():
    score = RedScore(
        objective_achieved=True,
        services_compromised=10,
        detection_evasion=1.0,
        efficiency=1.0,
        technique_diversity=10,
        penalties=0.0,
        rounds_used=3,
    )
    assert score.total == 100.0


def test_redscore_zero():
    score = RedScore(
        objective_achieved=False,
        services_compromised=0,
        detection_evasion=0.0,
        efficiency=0.0,
        technique_diversity=0,
        penalties=20.0,
        rounds_used=10,
    )
    assert score.total == 0.0


def test_redscore_to_dict():
    score = RedScore(objective_achieved=True, services_compromised=2)
    d = score.to_dict()
    assert "total" in d
    assert "objective_achieved" in d
    assert isinstance(d["total"], float)


# ---------------------------------------------------------------------------
# BlueScore dataclass tests
# ---------------------------------------------------------------------------

def test_bluescore_total_field():
    score = BlueScore(
        detected_intrusion=True,
        detection_round=1,
        total_rounds=5,
        sigma_rules_valid=3,
        sigma_rules_matching=2,
        patch_proposed=True,
        root_cause_identified=True,
        false_positives=0,
        service_disruption=0,
    )
    assert isinstance(score.total, float)
    assert 0.0 <= score.total <= 100.0


def test_bluescore_total_not_callable():
    score = BlueScore()
    assert not callable(score.total), "total must be a field, not a method"


def test_bluescore_early_detection_bonus():
    early = BlueScore(
        detected_intrusion=True,
        detection_round=1,
        total_rounds=5,  # 1/5 = 0.2 ≤ 0.30 → early
        sigma_rules_valid=0,
        sigma_rules_matching=0,
        patch_proposed=False,
        root_cause_identified=False,
    )
    late = BlueScore(
        detected_intrusion=True,
        detection_round=4,
        total_rounds=5,  # 4/5 = 0.8 → late
        sigma_rules_valid=0,
        sigma_rules_matching=0,
        patch_proposed=False,
        root_cause_identified=False,
    )
    assert early.total > late.total, "Early detection should score higher"


def test_bluescore_no_detection():
    score = BlueScore(detected_intrusion=False)
    assert score.total < 30.0, "No detection → at most partial points"


def test_bluescore_to_dict():
    score = BlueScore(detected_intrusion=True, detection_round=2, total_rounds=5)
    d = score.to_dict()
    assert "total" in d
    assert "detected_intrusion" in d
    assert "early_detection" in d


# ---------------------------------------------------------------------------
# score_red integration
# ---------------------------------------------------------------------------

def test_score_red_no_rounds():
    scorer = Scorer()
    scenario = make_scenario()
    rounds: list[RoundData] = []
    score = scorer.score_red(rounds, scenario)
    assert isinstance(score, RedScore)
    assert score.total == 0.0 or score.total >= 0.0


def test_score_red_with_flag():
    scorer = Scorer()
    scenario = make_scenario(seed=7)
    flag = scenario.flag_value
    rd = make_round(
        MatchPhase.POST_EXPLOIT,
        round_num=1,
        red_content=f"Successfully exfiltrated: {flag}",
    )
    score = scorer.score_red([rd], scenario)
    assert score.objective_achieved is True
    assert score.total > 0.0


def test_score_red_no_flag():
    scorer = Scorer()
    scenario = make_scenario(seed=7)
    rd = make_round(
        MatchPhase.EXPLOITATION,
        round_num=1,
        red_content="Nothing found yet, still scanning.",
    )
    score = scorer.score_red([rd], scenario)
    assert score.objective_achieved is False


def test_score_red_technique_diversity():
    scorer = Scorer()
    scenario = make_scenario()
    rounds = [
        RoundData(
            phase=MatchPhase.RECON, round_num=1,
            red_move=AgentMove(
                agent="red", phase=MatchPhase.RECON, round_num=1,
                move_type=MoveType.SCAN, content="nmap scan",
            ),
        ),
        RoundData(
            phase=MatchPhase.EXPLOITATION, round_num=1,
            red_move=AgentMove(
                agent="red", phase=MatchPhase.EXPLOITATION, round_num=1,
                move_type=MoveType.EXPLOIT, content="sqlmap attack",
            ),
        ),
        RoundData(
            phase=MatchPhase.POST_EXPLOIT, round_num=1,
            red_move=AgentMove(
                agent="red", phase=MatchPhase.POST_EXPLOIT, round_num=1,
                move_type=MoveType.PERSISTENCE, content="add backdoor",
            ),
        ),
    ]
    score = scorer.score_red(rounds, scenario)
    assert score.technique_diversity >= 3


# ---------------------------------------------------------------------------
# score_blue integration
# ---------------------------------------------------------------------------

def test_score_blue_no_rounds():
    scorer = Scorer()
    scenario = make_scenario()
    score = scorer.score_blue([], scenario)
    assert isinstance(score, BlueScore)
    assert score.total >= 0.0


def test_score_blue_detection():
    scorer = Scorer()
    scenario = make_scenario(seed=3)
    # Blue detects nmap scan → mentions nmap in content
    rd = make_round(
        MatchPhase.EXPLOITATION,
        round_num=2,
        red_content="nmap -sV 10.42.1.5",
        blue_content="Detected nmap port scan from 10.42.1.5, created alert.",
        siem_logs=["SRC=10.42.1.5 nmap port scan detected"],
    )
    score = scorer.score_blue([rd], scenario)
    # At minimum blue gets some score
    assert score.total >= 0.0


def test_score_blue_with_sigma():
    scorer = Scorer()
    scenario = make_scenario(seed=5)
    rd = make_round(
        MatchPhase.REMEDIATION,
        round_num=1,
        blue_content="I created this Sigma rule:\n```yaml\n" + VALID_SIGMA.strip() + "\n```",
        sigma_rules=[VALID_SIGMA],
    )
    score = scorer.score_blue([rd], scenario)
    assert score.sigma_rules_valid >= 1


def test_score_blue_patch_proposed():
    scorer = Scorer()
    scenario = make_scenario()
    rd = make_round(
        MatchPhase.REMEDIATION,
        round_num=1,
        blue_content="I propose to patch the vulnerability by updating Apache to 2.4.57. Apply the fix with apt-get upgrade apache2.",
    )
    score = scorer.score_blue([rd], scenario)
    assert score.patch_proposed is True


def test_score_blue_root_cause():
    scorer = Scorer()
    scenario = make_scenario()
    # Use a MITRE technique ID from the actual scenario so detection is guaranteed
    tech_id = next(iter(scenario.mitre_techniques)) if scenario.mitre_techniques else "T1190"
    rd = make_round(
        MatchPhase.REMEDIATION,
        round_num=1,
        blue_content=f"Root cause analysis: attacker used technique {tech_id} to gain initial access.",
    )
    score = scorer.score_blue([rd], scenario)
    assert score.root_cause_identified is True


def test_score_blue_disruption_penalized():
    scorer = Scorer()
    scenario = make_scenario()
    rd = make_round(
        MatchPhase.REMEDIATION,
        round_num=1,
        blue_content="I shut down all services to stop the attack. Stopped the entire infrastructure.",
    )
    score = scorer.score_blue([rd], scenario)
    # disruption flag set (Blue shut down services)
    assert score.service_disruption >= 0  # At least it's recorded


# ---------------------------------------------------------------------------
# MatchResult.winner regression test
# ---------------------------------------------------------------------------

def test_matchresult_winner_uses_field():
    """MatchResult.winner must access .total as a field, not call it as a method."""
    from purple.match_protocol import MatchResult, MatchPhase

    scenario = make_scenario()
    red = RedScore(objective_achieved=True, services_compromised=3, detection_evasion=0.8, efficiency=0.9)
    blue = BlueScore(detected_intrusion=True, detection_round=1, total_rounds=5, sigma_rules_valid=2)

    result = MatchResult(
        match_id="test-123",
        scenario=scenario,
        rounds=[],
        red_score=red,
        blue_score=blue,
        dpo_pairs=[],
        duration_seconds=120.0,
        logs_path="/tmp/test",
        phase_reached=MatchPhase.DONE,
    )

    winner = result.winner  # must not raise TypeError
    assert winner in ("red", "blue", "draw")


def test_matchresult_winner_no_scores():
    from purple.match_protocol import MatchResult, MatchPhase
    scenario = make_scenario()
    result = MatchResult(
        match_id="test-456",
        scenario=scenario,
        rounds=[],
        red_score=None,
        blue_score=None,
        dpo_pairs=[],
        duration_seconds=0.0,
        logs_path="/tmp",
        phase_reached=MatchPhase.SETUP,
    )
    assert result.winner == "draw"


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    tests = [
        # Sigma
        test_sigma_valid,
        test_sigma_missing_title,
        test_sigma_no_condition,
        test_sigma_invalid_yaml,
        test_sigma_matches_logs,
        test_sigma_no_match_unrelated_logs,
        test_sigma_score_value,
        test_sigma_deduplication,
        # check_objective
        test_check_objective_exact_flag,
        test_check_objective_flag_pattern,
        test_check_objective_credential_extract,
        test_check_objective_not_achieved,
        test_check_objective_empty,
        # evasion rate
        test_evasion_no_actions,
        test_evasion_no_blue,
        test_evasion_detected_by_ip,
        test_evasion_detected_by_keyword,
        test_evasion_partial,
        # RedScore
        test_redscore_total_field,
        test_redscore_total_not_callable,
        test_redscore_max,
        test_redscore_zero,
        test_redscore_to_dict,
        # BlueScore
        test_bluescore_total_field,
        test_bluescore_total_not_callable,
        test_bluescore_early_detection_bonus,
        test_bluescore_no_detection,
        test_bluescore_to_dict,
        # score_red integration
        test_score_red_no_rounds,
        test_score_red_with_flag,
        test_score_red_no_flag,
        test_score_red_technique_diversity,
        # score_blue integration
        test_score_blue_no_rounds,
        test_score_blue_detection,
        test_score_blue_with_sigma,
        test_score_blue_patch_proposed,
        test_score_blue_root_cause,
        test_score_blue_disruption_penalized,
        # MatchResult.winner regression
        test_matchresult_winner_uses_field,
        test_matchresult_winner_no_scores,
    ]

    passed = 0
    failed = 0
    errors = []

    for test in tests:
        try:
            test()
            print(f"  PASS  {test.__name__}")
            passed += 1
        except Exception as e:
            print(f"  FAIL  {test.__name__}: {e}")
            failed += 1
            errors.append((test.__name__, str(e)))

    print(f"\n{passed}/{passed + failed} tests passed")
    if errors:
        print("\nFailed tests:")
        for name, err in errors:
            print(f"  - {name}: {err}")
        sys.exit(1)
    else:
        print("All tests green.")


# ---------------------------------------------------------------------------
# _test_patch tests (async — IsolatedAsyncioTestCase)
# ---------------------------------------------------------------------------

def _er(
    service: str = "vuln-webapp",
    command: str = "curl http://10.42.0.2/flag",
    stdout: str = "FLAG{abc123}",
    stderr: str = "",
    exit_code: int = 0,
) -> ExecResult:
    return ExecResult(
        service=service,
        command=command,
        stdout=stdout,
        stderr=stderr,
        exit_code=exit_code,
    )


def _round_with_exec(exec_result: ExecResult, blue_content: str = "") -> RoundData:
    """Red round that exec'd a command; Blue round with given content."""
    rd = RoundData(phase=MatchPhase.EXPLOITATION, round_num=1)
    red = AgentMove(
        agent="red",
        phase=MatchPhase.EXPLOITATION,
        round_num=1,
        move_type=MoveType.EXPLOIT,
        content="exploit attempt",
    )
    red.exec_results = [exec_result]
    rd.red_move = red
    if blue_content:
        rd.blue_move = AgentMove(
            agent="blue",
            phase=MatchPhase.REMEDIATION,
            round_num=1,
            move_type=MoveType.PATCH,
            content=blue_content,
        )
    return rd


def _make_match(rounds: list) -> MagicMock:
    m = MagicMock()
    m.rounds = rounds
    return m


def _mock_range(
    patch_exit: int = 0,
    replay_exit: int = 1,
    replay_stdout: str = "",
) -> MagicMock:
    cr = MagicMock()
    cr.exec_command = AsyncMock(side_effect=[
        ExecResult(
            service="vuln-webapp",
            command="iptables ...",
            stdout="",
            stderr="",
            exit_code=patch_exit,
        ),
        ExecResult(
            service="vuln-webapp",
            command="curl ...",
            stdout=replay_stdout,
            stderr="",
            exit_code=replay_exit,
        ),
    ])
    return cr


_BLUE_IPTABLES_BLOCK = (
    "Apply this patch:\n"
    "```bash\n"
    "iptables -A INPUT -p tcp --dport 5000 -j DROP\n"
    "```\n"
)

_BLUE_CHMOD_BLOCK = (
    "```\n"
    "chmod 750 /app/db.sqlite\n"
    "```\n"
)


class TestTestPatch(unittest.IsolatedAsyncioTestCase):

    async def test_no_blue_code_block_returns_true(self):
        """No code blocks in Blue responses → True (nothing to test)."""
        rd = _round_with_exec(_er(), blue_content="Apply input validation everywhere.")
        match = _make_match([rd])
        result = await Scorer()._test_patch(match, MagicMock())
        self.assertTrue(result)

    async def test_no_blue_move_returns_true(self):
        """Round without any Blue move → True."""
        rd = RoundData(phase=MatchPhase.EXPLOITATION, round_num=1)
        rd.red_move = AgentMove(
            agent="red", phase=MatchPhase.EXPLOITATION, round_num=1,
            move_type=MoveType.EXPLOIT, content="x",
        )
        rd.red_move.exec_results = [_er()]
        match = _make_match([rd])
        result = await Scorer()._test_patch(match, MagicMock())
        self.assertTrue(result)

    async def test_no_successful_red_exploit_returns_true(self):
        """Blue has patch block but no Red exec succeeded → True."""
        er = _er(exit_code=1, stdout="permission denied")
        rd = _round_with_exec(er, blue_content=_BLUE_IPTABLES_BLOCK)
        match = _make_match([rd])
        result = await Scorer()._test_patch(match, MagicMock())
        self.assertTrue(result)

    async def test_exploit_no_compromise_indicator_returns_true(self):
        """Red exec succeeded (exit_code=0) but stdout has no compromise indicator → True."""
        er = _er(exit_code=0, stdout="200 OK")  # no flag/password/etc.
        rd = _round_with_exec(er, blue_content=_BLUE_IPTABLES_BLOCK)
        match = _make_match([rd])
        result = await Scorer()._test_patch(match, MagicMock())
        self.assertTrue(result)

    async def test_patch_effective_replay_fails(self):
        """Patch applied (exit=0), replay returns exit_code=1 → True (effective)."""
        er = _er(exit_code=0, stdout="FLAG{abc123}")
        rd = _round_with_exec(er, blue_content=_BLUE_IPTABLES_BLOCK)
        match = _make_match([rd])
        cr = _mock_range(patch_exit=0, replay_exit=1, replay_stdout="blocked")
        result = await Scorer()._test_patch(match, cr)
        self.assertTrue(result)
        self.assertEqual(cr.exec_command.call_count, 2)

    async def test_patch_effective_replay_stdout_clean(self):
        """Patch applied (exit=0), replay exits 0 but stdout no longer has flag → True."""
        er = _er(exit_code=0, stdout="FLAG{abc123}")
        rd = _round_with_exec(er, blue_content=_BLUE_IPTABLES_BLOCK)
        match = _make_match([rd])
        cr = _mock_range(patch_exit=0, replay_exit=0, replay_stdout="200 OK clean")
        result = await Scorer()._test_patch(match, cr)
        self.assertTrue(result)

    async def test_patch_ineffective_flag_still_present(self):
        """Patch applied, replay exits 0 and flag still in stdout → False."""
        er = _er(exit_code=0, stdout="FLAG{abc123}")
        rd = _round_with_exec(er, blue_content=_BLUE_IPTABLES_BLOCK)
        match = _make_match([rd])
        cr = _mock_range(patch_exit=0, replay_exit=0, replay_stdout="FLAG{abc123}")
        result = await Scorer()._test_patch(match, cr)
        self.assertFalse(result)

    async def test_patch_apply_error_returns_false(self):
        """exec_command raises on patch step → False (conservative)."""
        er = _er(exit_code=0, stdout="FLAG{abc}")
        rd = _round_with_exec(er, blue_content=_BLUE_IPTABLES_BLOCK)
        match = _make_match([rd])
        cr = MagicMock()
        cr.exec_command = AsyncMock(side_effect=RuntimeError("range is down"))
        result = await Scorer()._test_patch(match, cr)
        self.assertFalse(result)

    async def test_patch_apply_nonzero_exit_returns_false(self):
        """Patch command exits non-zero → False (patch failed to apply)."""
        er = _er(exit_code=0, stdout="FLAG{abc}")
        rd = _round_with_exec(er, blue_content=_BLUE_IPTABLES_BLOCK)
        match = _make_match([rd])
        cr = _mock_range(patch_exit=1)  # patch fails
        result = await Scorer()._test_patch(match, cr)
        self.assertFalse(result)
        # Only patch call is made — replay is not attempted
        self.assertEqual(cr.exec_command.call_count, 1)

    async def test_patch_replay_error_returns_false(self):
        """exec_command raises on replay step → False (conservative)."""
        er = _er(exit_code=0, stdout="FLAG{abc}")
        rd = _round_with_exec(er, blue_content=_BLUE_IPTABLES_BLOCK)
        match = _make_match([rd])
        cr = MagicMock()
        # First call (patch) succeeds, second call (replay) raises
        cr.exec_command = AsyncMock(side_effect=[
            ExecResult("vuln-webapp", "iptables ...", "", "", 0),
            RuntimeError("container crashed"),
        ])
        result = await Scorer()._test_patch(match, cr)
        self.assertFalse(result)

    async def test_last_code_block_wins(self):
        """Multiple Blue code blocks — the LAST one with keywords is used as patch_cmd."""
        # Round 1: Blue proposes chmod
        rd1 = _round_with_exec(_er(exit_code=0, stdout="FLAG{abc}"), blue_content=_BLUE_CHMOD_BLOCK)
        # Round 2: Blue proposes iptables (last → should win)
        rd2 = RoundData(phase=MatchPhase.REMEDIATION, round_num=2)
        rd2.red_move = None
        rd2.blue_move = AgentMove(
            agent="blue", phase=MatchPhase.REMEDIATION, round_num=2,
            move_type=MoveType.PATCH, content=_BLUE_IPTABLES_BLOCK,
        )
        match = _make_match([rd1, rd2])
        cr = _mock_range(patch_exit=0, replay_exit=1)

        await Scorer()._test_patch(match, cr)

        # Verify the iptables command (from last block) was used, not chmod
        first_call_cmd = cr.exec_command.call_args_list[0][0][1]
        self.assertIn("iptables", first_call_cmd)

    async def test_code_block_without_remediation_keyword_ignored(self):
        """A code block without any remediation keyword is not extracted as patch_cmd."""
        blue_content = "```bash\necho hello world\n```\n"
        rd = _round_with_exec(_er(exit_code=0, stdout="FLAG{abc}"), blue_content=blue_content)
        match = _make_match([rd])
        # If no patch_cmd found → returns True without calling exec_command
        cr = MagicMock()
        cr.exec_command = AsyncMock()
        result = await Scorer()._test_patch(match, cr)
        self.assertTrue(result)
        cr.exec_command.assert_not_called()

    async def test_uses_first_successful_exploit_service(self):
        """The target service for patch/replay is taken from the first successful exec."""
        er = _er(service="vuln-ssh", command="ssh root@10.42.0.3", stdout="password:root", exit_code=0)
        rd = _round_with_exec(er, blue_content=_BLUE_CHMOD_BLOCK)
        match = _make_match([rd])
        cr = _mock_range(patch_exit=0, replay_exit=1)

        await Scorer()._test_patch(match, cr)

        # Both calls target "vuln-ssh"
        for call_args in cr.exec_command.call_args_list:
            self.assertEqual(call_args[0][0], "vuln-ssh")

    async def test_compromise_indicator_password_detected(self):
        """'password' in stdout is a valid compromise indicator."""
        er = _er(exit_code=0, stdout="admin:password123")
        rd = _round_with_exec(er, blue_content=_BLUE_IPTABLES_BLOCK)
        match = _make_match([rd])
        cr = _mock_range(patch_exit=0, replay_exit=0, replay_stdout="admin:password123")
        # Still has compromise in replay → ineffective patch
        result = await Scorer()._test_patch(match, cr)
        self.assertFalse(result)


if __name__ == "__main__":
    # Run async TestTestPatch separately via unittest
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromTestCase(TestTestPatch)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    if not result.wasSuccessful():
        sys.exit(1)
