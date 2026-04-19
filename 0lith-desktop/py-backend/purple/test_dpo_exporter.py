"""
Tests pour purple/dpo_exporter.py
Run: python py-backend/purple/test_dpo_exporter.py
"""

from __future__ import annotations

import json
import sys
import os
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from purple.dpo_exporter import DPOExporter, DPOPair, MIN_RESPONSE_CHARS
from purple.scenario_generator import ScenarioGenerator
from purple.match_protocol import (
    AgentMove, RoundData, MatchPhase, MoveType, MatchResult,
)
from purple.scorer import RedScore, BlueScore

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

GEN = ScenarioGenerator()

LONG_TEXT  = "A" * (MIN_RESPONSE_CHARS + 10)
SHORT_TEXT = "A" * (MIN_RESPONSE_CHARS - 5)

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

def make_scenario(seed=42, difficulty="medium", control=False):
    s = GEN.generate(seed=seed, difficulty=difficulty)
    if control:
        # Toggle control_scenario via generate_control
        s = GEN.generate_control(seed=seed, difficulty=difficulty)
    return s


def make_red_move(phase, round_num, content, commands=None, move_type=MoveType.EXPLOIT, exec_ok=None):
    from purple.cyber_range import ExecResult
    move = AgentMove(
        agent="red", phase=phase, round_num=round_num,
        move_type=move_type, content=content,
        commands=commands or [],
    )
    if exec_ok is not None:
        move.exec_results = [
            ExecResult(
                service="vuln-webapp", command="cmd",
                stdout="ok" if exec_ok else "", stderr="",
                exit_code=0 if exec_ok else 1,
            )
        ]
    return move


def make_blue_move(phase, round_num, content, sigma_rules=None, move_type=MoveType.ALERT):
    return AgentMove(
        agent="blue", phase=phase, round_num=round_num,
        move_type=move_type, content=content,
        sigma_rules=sigma_rules or [],
    )


def make_round(phase, round_num, red_content="", blue_content="",
               sigma_rules=None, siem_logs=None,
               exec_ok=None, red_move_type=MoveType.EXPLOIT):
    rd = RoundData(phase=phase, round_num=round_num)
    if red_content:
        rd.red_move = make_red_move(phase, round_num, red_content,
                                    move_type=red_move_type, exec_ok=exec_ok)
    if blue_content:
        rd.blue_move = make_blue_move(phase, round_num, blue_content,
                                      sigma_rules=sigma_rules)
    rd.siem_logs = siem_logs or []
    return rd


def make_match(scenario, rounds, match_id="test-match-0000"):
    red_score  = RedScore(objective_achieved=True)
    blue_score = BlueScore(detected_intrusion=True)
    return MatchResult(
        match_id=match_id,
        scenario=scenario,
        rounds=rounds,
        red_score=red_score,
        blue_score=blue_score,
        dpo_pairs=[],
        duration_seconds=60.0,
        logs_path="/tmp",
        phase_reached=MatchPhase.DONE,
    )


def tmp_exporter() -> DPOExporter:
    d = tempfile.mkdtemp(prefix="olith-dpo-test-")
    return DPOExporter(output_dir=Path(d))


# ---------------------------------------------------------------------------
# DPOPair dataclass tests
# ---------------------------------------------------------------------------

def test_dpopair_is_valid():
    p = DPOPair(
        pair_id="p1", agent="red", prompt="Q?",
        chosen=LONG_TEXT, rejected=LONG_TEXT + "X",
        criterion="c", source_match_id="m",
        score_delta=10.0, scenario_seed=1, difficulty="medium",
    )
    assert p.is_valid


def test_dpopair_invalid_too_short():
    p = DPOPair(
        pair_id="p2", agent="red", prompt="Q?",
        chosen=SHORT_TEXT, rejected=LONG_TEXT,
        criterion="c", source_match_id="m",
        score_delta=5.0, scenario_seed=1, difficulty="easy",
    )
    assert not p.is_valid


def test_dpopair_invalid_identical():
    p = DPOPair(
        pair_id="p3", agent="blue", prompt="Q?",
        chosen=LONG_TEXT, rejected=LONG_TEXT,
        criterion="c", source_match_id="m",
        score_delta=0.0, scenario_seed=1, difficulty="hard",
    )
    assert not p.is_valid


def test_dpopair_invalid_empty_prompt():
    p = DPOPair(
        pair_id="p4", agent="blue", prompt="   ",
        chosen=LONG_TEXT, rejected=LONG_TEXT + "Y",
        criterion="c", source_match_id="m",
        score_delta=5.0, scenario_seed=1, difficulty="medium",
    )
    assert not p.is_valid


def test_dpopair_to_dict_fields():
    p = DPOPair(
        pair_id="p5", agent="red", prompt="Q?",
        chosen=LONG_TEXT, rejected=LONG_TEXT + "Z",
        criterion="exploit_success_vs_failure",
        source_match_id="match-abc",
        score_delta=15.0, scenario_seed=42, difficulty="hard",
        metadata={"key": "val"},
    )
    d = p.to_dict()
    assert d["pair_id"]         == "p5"
    assert d["source_match_id"] == "match-abc"
    assert d["score_delta"]     == 15.0
    assert d["criterion"]       == "exploit_success_vs_failure"
    assert d["metadata"]        == {"key": "val"}


def test_dpopair_to_trl_dict():
    p = DPOPair(
        pair_id="p6", agent="blue", prompt="system prompt",
        chosen=LONG_TEXT, rejected=LONG_TEXT + "Q",
        criterion="detection_hit_vs_miss",
        source_match_id="m", score_delta=25.0,
        scenario_seed=1, difficulty="medium",
    )
    trl = p.to_trl_dict()
    assert set(trl.keys()) == {"prompt", "chosen", "rejected"}
    assert trl["prompt"] == "system prompt"


# ---------------------------------------------------------------------------
# Control scenario guard
# ---------------------------------------------------------------------------

def test_control_scenario_no_pairs():
    exporter = tmp_exporter()
    scenario = make_scenario(seed=10, control=True)
    assert scenario.control_scenario is True

    rounds = [
        make_round(MatchPhase.EXPLOITATION, 1,
                   red_content=LONG_TEXT, blue_content=LONG_TEXT,
                   exec_ok=True),
    ]
    match = make_match(scenario, rounds)
    pairs = exporter.extract_pairs_from_match(match)
    assert pairs == [], "Control scenarios must never produce DPO pairs"


def test_control_scenario_extract_pairs_compat():
    exporter = tmp_exporter()
    scenario = make_scenario(seed=11, control=True)
    pairs = exporter.extract_pairs(rounds=[], scenario=scenario)
    assert pairs == []


# ---------------------------------------------------------------------------
# Red Team — exploit_success_vs_failure
# ---------------------------------------------------------------------------

def test_red_exploit_pairs_produced():
    exporter = tmp_exporter()
    scenario = make_scenario(seed=1)
    rounds = [
        make_round(MatchPhase.EXPLOITATION, 1,
                   red_content=LONG_TEXT + " success nmap exploit", exec_ok=True),
        make_round(MatchPhase.EXPLOITATION, 2,
                   red_content=LONG_TEXT + " failed attempt", exec_ok=False),
    ]
    pairs = exporter.extract_pairs(rounds, scenario, match_id="test-exploit")
    exploit_pairs = [p for p in pairs if p.criterion == "exploit_success_vs_failure"]
    assert len(exploit_pairs) >= 1, "Should produce at least 1 exploit pair"


def test_red_exploit_pairs_chosen_is_success():
    exporter = tmp_exporter()
    scenario = make_scenario(seed=2)
    success_text = LONG_TEXT + " successfully exploited the vulnerability"
    failure_text = LONG_TEXT + " exploit failed, connection refused"
    rounds = [
        make_round(MatchPhase.EXPLOITATION, 1, red_content=success_text, exec_ok=True),
        make_round(MatchPhase.EXPLOITATION, 2, red_content=failure_text, exec_ok=False),
    ]
    pairs = exporter.extract_pairs(rounds, scenario, match_id="test-chosen")
    exploit_pairs = [p for p in pairs if p.criterion == "exploit_success_vs_failure"]
    assert len(exploit_pairs) >= 1
    p = exploit_pairs[0]
    assert p.chosen == success_text[:4096]
    assert p.rejected == failure_text[:4096]
    assert p.score_delta == 15.0


def test_red_exploit_no_exec_results_skipped():
    """Rounds sans exec_results ne contribuent pas aux paires exploit."""
    exporter = tmp_exporter()
    scenario = make_scenario(seed=3)
    rounds = [
        make_round(MatchPhase.EXPLOITATION, 1, red_content=LONG_TEXT),  # pas d'exec
        make_round(MatchPhase.EXPLOITATION, 2, red_content=LONG_TEXT + "X"),  # pas d'exec
    ]
    pairs = exporter.extract_pairs(rounds, scenario, match_id="test-no-exec")
    exploit_pairs = [p for p in pairs if p.criterion == "exploit_success_vs_failure"]
    assert len(exploit_pairs) == 0, "Rounds without exec_results should not produce exploit pairs"


# ---------------------------------------------------------------------------
# Red Team — stealth_vs_detected
# ---------------------------------------------------------------------------

def test_red_stealth_vs_detected():
    exporter = tmp_exporter()
    scenario = make_scenario(seed=5)
    # IP du scenario pour le test de détection
    ip = scenario.services[0].ip

    stealthy_text = LONG_TEXT + " using encrypted channel, no traces"
    detected_text = LONG_TEXT + " standard nmap scan on target"
    blue_detects  = LONG_TEXT + f" detected suspicious activity from {ip}, alert raised"
    blue_silent   = LONG_TEXT + " reviewing normal baseline traffic metrics"

    rounds = [
        make_round(MatchPhase.EXPLOITATION, 1,
                   red_content=stealthy_text,
                   blue_content=blue_silent),   # Blue ne détecte pas
        make_round(MatchPhase.EXPLOITATION, 2,
                   red_content=detected_text,
                   blue_content=blue_detects),  # Blue détecte (IP mentionnée)
    ]
    # Injecter l'IP dans le contenu Red pour que _blue_detected_red_move la trouve
    rounds[1].red_move.content = detected_text + f" targeting {ip}"

    pairs = exporter.extract_pairs(rounds, scenario, match_id="test-stealth")
    stealth_pairs = [p for p in pairs if p.criterion == "stealth_vs_detected"]
    assert len(stealth_pairs) >= 1


# ---------------------------------------------------------------------------
# Red Team — technique_novelty_vs_repeat
# ---------------------------------------------------------------------------

def test_red_diversity_pairs():
    exporter = tmp_exporter()
    scenario = make_scenario(seed=6)
    # Round 1: SCAN (novel)
    r1 = RoundData(phase=MatchPhase.RECON, round_num=1)
    r1.red_move = make_red_move(MatchPhase.RECON, 1, LONG_TEXT + " initial scan",
                                move_type=MoveType.SCAN)
    # Round 2: EXPLOIT (novel)
    r2 = RoundData(phase=MatchPhase.EXPLOITATION, round_num=2)
    r2.red_move = make_red_move(MatchPhase.EXPLOITATION, 2, LONG_TEXT + " first exploit",
                                move_type=MoveType.EXPLOIT)
    # Round 3: EXPLOIT (repeat!)
    r3 = RoundData(phase=MatchPhase.EXPLOITATION, round_num=3)
    r3.red_move = make_red_move(MatchPhase.EXPLOITATION, 3, LONG_TEXT + " repeated exploit",
                                move_type=MoveType.EXPLOIT)

    pairs = exporter.extract_pairs([r1, r2, r3], scenario, match_id="test-diversity")
    diversity_pairs = [p for p in pairs if p.criterion == "technique_novelty_vs_repeat"]
    assert len(diversity_pairs) >= 1
    # Le chosen doit être une technique novel, le rejected une technique repeat
    p = diversity_pairs[0]
    assert p.score_delta == 5.0


# ---------------------------------------------------------------------------
# Blue Team — detection_hit_vs_miss
# ---------------------------------------------------------------------------

def test_blue_detection_hit_vs_miss():
    exporter = tmp_exporter()
    scenario = make_scenario(seed=7)
    ip = scenario.services[0].ip

    # Round 1: Blue détecte (mentions IP et keywords)
    detection_text = (
        LONG_TEXT + f" detected unauthorized access from {ip}, "
        f"suspicious scan detected alert raised blocked malicious threat"
    )
    # Round 2: Blue ne détecte pas (réponse générique)
    miss_text = LONG_TEXT + " reviewing traffic, all baseline metrics normal today"

    r1 = make_round(MatchPhase.EXPLOITATION, 1,
                    red_content=LONG_TEXT + f" attack from {ip}",
                    blue_content=detection_text)
    r2 = make_round(MatchPhase.EXPLOITATION, 2,
                    red_content=LONG_TEXT + " another attack",
                    blue_content=miss_text)
    # L'IP dans red_move permet à _blue_content_is_detection de la trouver
    r1.red_move.content = LONG_TEXT + f" attack from {ip}"

    pairs = exporter.extract_pairs([r1, r2], scenario, match_id="test-detection")
    detection_pairs = [p for p in pairs if p.criterion == "detection_hit_vs_miss"]
    assert len(detection_pairs) >= 1


# ---------------------------------------------------------------------------
# Blue Team — sigma_valid_matching_vs_invalid
# ---------------------------------------------------------------------------

def test_blue_sigma_pairs():
    exporter = tmp_exporter()
    scenario = make_scenario(seed=8)

    # Round avec sigma valide
    r_good = make_round(
        MatchPhase.EXPLOITATION, 1,
        red_content=LONG_TEXT + " nmap scan launched",
        blue_content=LONG_TEXT + " detected scan, created rule",
        sigma_rules=[VALID_SIGMA],
        siem_logs=["nmap -sS detected on eth0", "port scan from 10.42.0.1"],
    )
    # Round sans sigma
    r_bad = make_round(
        MatchPhase.EXPLOITATION, 2,
        red_content=LONG_TEXT,
        blue_content=LONG_TEXT + " monitoring traffic, no specific action",
        sigma_rules=[],
    )

    pairs = exporter.extract_pairs([r_good, r_bad], scenario, match_id="test-sigma")
    sigma_pairs = [p for p in pairs if p.criterion == "sigma_valid_matching_vs_invalid"]
    assert len(sigma_pairs) >= 1
    p = sigma_pairs[0]
    assert p.agent == "blue"
    assert p.score_delta == 10.0


# ---------------------------------------------------------------------------
# Blue Team — patch_proposed_vs_absent
# ---------------------------------------------------------------------------

def test_blue_patch_pairs():
    exporter = tmp_exporter()
    scenario = make_scenario(seed=9)

    r_patch = make_round(
        MatchPhase.REMEDIATION, 1,
        blue_content=LONG_TEXT + " recommend to patch the vulnerability by updating apache, apply the fix via apt upgrade to mitigate CVE",
    )
    r_no_patch = make_round(
        MatchPhase.REMEDIATION, 2,
        blue_content=LONG_TEXT + " the attack was interesting, we should monitor more",
    )

    pairs = exporter.extract_pairs([r_patch, r_no_patch], scenario, match_id="test-patch")
    patch_pairs = [p for p in pairs if p.criterion == "patch_proposed_vs_absent"]
    assert len(patch_pairs) >= 1
    p = patch_pairs[0]
    assert p.chosen == r_patch.blue_move.content[:4096]
    assert p.score_delta == 20.0


# ---------------------------------------------------------------------------
# Blue Team — no_disruption_vs_disruption
# ---------------------------------------------------------------------------

def test_blue_disruption_pairs():
    exporter = tmp_exporter()
    scenario = make_scenario(seed=10)

    r_targeted = make_round(
        MatchPhase.POST_EXPLOIT, 1,
        blue_content=LONG_TEXT + " isolating the compromised webapp container and applying firewall rule",
    )
    r_disruptive = make_round(
        MatchPhase.POST_EXPLOIT, 2,
        blue_content=LONG_TEXT + " I recommend to shut down all services immediately to stop the attack",
    )

    pairs = exporter.extract_pairs([r_targeted, r_disruptive], scenario, match_id="test-disruption")
    disrupt_pairs = [p for p in pairs if p.criterion == "no_disruption_vs_disruption"]
    assert len(disrupt_pairs) >= 1
    p = disrupt_pairs[0]
    assert p.chosen == r_targeted.blue_move.content[:4096]
    assert p.rejected == r_disruptive.blue_move.content[:4096]


# ---------------------------------------------------------------------------
# Prompt reconstruction
# ---------------------------------------------------------------------------

def test_red_prompt_contains_context():
    exporter = tmp_exporter()
    scenario = make_scenario(seed=1)
    r = make_round(MatchPhase.EXPLOITATION, 2, red_content=LONG_TEXT)
    prompt = exporter._build_red_prompt(r, scenario)
    assert scenario.subnet in prompt or scenario.objective in prompt
    assert "EXPLOITATION" in prompt


def test_blue_prompt_contains_siem_logs():
    exporter = tmp_exporter()
    scenario = make_scenario(seed=1)
    logs = ["2024-01-01 SRC=10.42.1.5 nmap scan detected"]
    r = make_round(MatchPhase.EXPLOITATION, 1,
                   blue_content=LONG_TEXT, siem_logs=logs)
    prompt = exporter._build_blue_prompt(r, scenario)
    assert "SIEM" in prompt
    assert "nmap scan detected" in prompt


# ---------------------------------------------------------------------------
# Write / export_to_jsonl / accumulate_pairs
# ---------------------------------------------------------------------------

def test_write_creates_file():
    exporter = tmp_exporter()
    p = DPOPair(
        pair_id="w1", agent="red", prompt="Q?",
        chosen=LONG_TEXT, rejected=LONG_TEXT + "X",
        criterion="test", source_match_id="m",
        score_delta=5.0, scenario_seed=1, difficulty="easy",
    )
    path = exporter.write([p], match_id="testmatch")
    assert path.exists()
    lines = path.read_text().splitlines()
    assert len(lines) == 1
    d = json.loads(lines[0])
    assert d["pair_id"] == "w1"
    assert d["source_match_id"] == "m"
    assert d["score_delta"] == 5.0


def test_write_empty_returns_empty_path():
    exporter = tmp_exporter()
    path = exporter.write([], match_id="empty")
    assert "empty" in path.name


def test_export_to_jsonl_trl_format():
    exporter = tmp_exporter()
    pairs = [
        DPOPair(
            pair_id=f"e{i}", agent="blue", prompt="P",
            chosen=LONG_TEXT, rejected=LONG_TEXT + str(i),
            criterion="test", source_match_id="m",
            score_delta=3.0, scenario_seed=1, difficulty="medium",
        )
        for i in range(5)
    ]
    path = exporter.export_to_jsonl(pairs)
    assert path.exists()
    lines = [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
    assert len(lines) == 5
    for line in lines:
        assert set(line.keys()) == {"prompt", "chosen", "rejected"}


def test_export_to_jsonl_auto_filename():
    exporter = tmp_exporter()
    pairs = [
        DPOPair(
            pair_id="auto1", agent="red", prompt="P",
            chosen=LONG_TEXT, rejected=LONG_TEXT + "Z",
            criterion="test", source_match_id="m",
            score_delta=5.0, scenario_seed=2, difficulty="hard",
        )
    ]
    path = exporter.export_to_jsonl(pairs, output_path=None)
    # Filename format: YYYYMMDD_N_pairs.jsonl
    assert "_pairs.jsonl" in path.name
    assert "1" in path.name  # count = 1


def test_accumulate_pairs_below_threshold():
    exporter = tmp_exporter()
    # No files yet
    assert exporter.accumulate_pairs(min_pairs=10) is False


def test_accumulate_pairs_above_threshold():
    exporter = tmp_exporter()
    # Write 3 pairs
    pairs = [
        DPOPair(
            pair_id=f"acc{i}", agent="red", prompt="P",
            chosen=LONG_TEXT, rejected=LONG_TEXT + str(i),
            criterion="test", source_match_id="m",
            score_delta=1.0, scenario_seed=1, difficulty="easy",
        )
        for i in range(3)
    ]
    exporter.write(pairs, match_id="acc-test")
    assert exporter.accumulate_pairs(min_pairs=3) is True
    assert exporter.accumulate_pairs(min_pairs=4) is False


# ---------------------------------------------------------------------------
# merge_files
# ---------------------------------------------------------------------------

def test_merge_deduplicates():
    exporter = tmp_exporter()
    p = DPOPair(
        pair_id="dup1", agent="red", prompt="P",
        chosen=LONG_TEXT, rejected=LONG_TEXT + "M",
        criterion="test", source_match_id="m",
        score_delta=5.0, scenario_seed=1, difficulty="medium",
    )
    # Write same pair twice in two files
    exporter.write([p], match_id="file1", filename="dpo_111_file1.jsonl")
    exporter.write([p], match_id="file2", filename="dpo_222_file2.jsonl")

    merged = exporter.merge_files()
    lines = [json.loads(l) for l in merged.read_text().splitlines() if l.strip()]
    pair_ids = [l["pair_id"] for l in lines]
    assert pair_ids.count("dup1") == 1, "Duplicate pair_id should appear only once"


# ---------------------------------------------------------------------------
# get_stats
# ---------------------------------------------------------------------------

def test_get_stats():
    exporter = tmp_exporter()
    pairs = [
        DPOPair(
            pair_id=f"s{i}", agent="red" if i % 2 == 0 else "blue",
            prompt="P", chosen=LONG_TEXT, rejected=LONG_TEXT + str(i),
            criterion="exploit_success_vs_failure",
            source_match_id="m", score_delta=5.0,
            scenario_seed=1, difficulty="medium",
        )
        for i in range(4)
    ]
    exporter.write(pairs, match_id="stats-test")
    stats = exporter.get_stats()
    assert stats["total_pairs"] == 4
    assert stats["total_files"] >= 1
    assert stats["by_criterion"].get("exploit_success_vs_failure", 0) == 4
    assert stats["by_difficulty"].get("medium", 0) == 4


# ---------------------------------------------------------------------------
# extract_pairs_from_match integration
# ---------------------------------------------------------------------------

def test_extract_pairs_from_match_full():
    exporter = tmp_exporter()
    scenario = make_scenario(seed=42)
    ip = scenario.services[0].ip

    rounds = [
        # RECON: Red scanne (novel SCAN)
        make_round(MatchPhase.RECON, 1,
                   red_content=LONG_TEXT + " initial network scan",
                   red_move_type=MoveType.SCAN),
        # EXPLOITATION: Red réussit (exec_ok=True), Blue détecte
        make_round(MatchPhase.EXPLOITATION, 1,
                   red_content=LONG_TEXT + f" exploit targeting {ip}",
                   blue_content=LONG_TEXT + f" detected attack from {ip} alert suspicious blocked intrusion threat",
                   exec_ok=True, sigma_rules=[VALID_SIGMA],
                   siem_logs=["nmap port scan from 10.42.0.5"]),
        # EXPLOITATION: Red échoue, Blue miss
        make_round(MatchPhase.EXPLOITATION, 2,
                   red_content=LONG_TEXT + " failed exploit attempt",
                   blue_content=LONG_TEXT + " no unusual activity observed baseline normal",
                   exec_ok=False),
        # POST_EXPLOIT: Red (novel PERSISTENCE), Blue ciblé
        make_round(MatchPhase.POST_EXPLOIT, 1,
                   red_content=LONG_TEXT + " establishing persistence backdoor",
                   blue_content=LONG_TEXT + " isolating compromised host applying patch fix update CVE",
                   red_move_type=MoveType.PERSISTENCE),
        # REMEDIATION: Blue patch + sigma
        make_round(MatchPhase.REMEDIATION, 1,
                   blue_content=LONG_TEXT + " applying patch to remediate CVE-2021-44228 update apache fix vulnerability"),
        # REMEDIATION: Blue disruptif (rejected)
        make_round(MatchPhase.REMEDIATION, 2,
                   blue_content=LONG_TEXT + " I recommend to shut down all services immediately to contain the threat"),
    ]
    # Injecter l'IP dans red_move du round EXPLOITATION 1
    rounds[1].red_move.content = LONG_TEXT + f" exploit targeting {ip}"

    match = make_match(scenario, rounds)
    pairs = exporter.extract_pairs_from_match(match)

    assert len(pairs) > 0, "Should produce at least 1 DPO pair from a rich match"

    # Tous les champs sont bien remplis
    for p in pairs:
        assert p.is_valid, f"Pair {p.pair_id} is not valid"
        assert p.source_match_id == "test-match-0000"
        assert p.scenario_seed == scenario.seed
        assert p.agent in ("red", "blue")
        assert p.score_delta > 0.0

    # Vérifier les critères produits
    criteria = {p.criterion for p in pairs}
    print(f"  Criteria produced: {criteria}")


def test_extract_pairs_from_match_control_skipped():
    exporter = tmp_exporter()
    control = make_scenario(seed=1, control=True)
    rounds = [
        make_round(MatchPhase.EXPLOITATION, 1,
                   red_content=LONG_TEXT, blue_content=LONG_TEXT + "X", exec_ok=True),
    ]
    match = make_match(control, rounds)
    pairs = exporter.extract_pairs_from_match(match)
    assert pairs == []


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    tests = [
        # DPOPair
        test_dpopair_is_valid,
        test_dpopair_invalid_too_short,
        test_dpopair_invalid_identical,
        test_dpopair_invalid_empty_prompt,
        test_dpopair_to_dict_fields,
        test_dpopair_to_trl_dict,
        # Control scenario guard
        test_control_scenario_no_pairs,
        test_control_scenario_extract_pairs_compat,
        # Red — exploit
        test_red_exploit_pairs_produced,
        test_red_exploit_pairs_chosen_is_success,
        test_red_exploit_no_exec_results_skipped,
        # Red — stealth
        test_red_stealth_vs_detected,
        # Red — diversity
        test_red_diversity_pairs,
        # Blue — detection
        test_blue_detection_hit_vs_miss,
        # Blue — sigma
        test_blue_sigma_pairs,
        # Blue — patch
        test_blue_patch_pairs,
        # Blue — disruption
        test_blue_disruption_pairs,
        # Prompts
        test_red_prompt_contains_context,
        test_blue_prompt_contains_siem_logs,
        # Write / export
        test_write_creates_file,
        test_write_empty_returns_empty_path,
        test_export_to_jsonl_trl_format,
        test_export_to_jsonl_auto_filename,
        test_accumulate_pairs_below_threshold,
        test_accumulate_pairs_above_threshold,
        # Merge
        test_merge_deduplicates,
        # Stats
        test_get_stats,
        # Integration
        test_extract_pairs_from_match_full,
        test_extract_pairs_from_match_control_skipped,
    ]

    passed = failed = 0
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
        print("\nFailed:")
        for name, err in errors:
            print(f"  - {name}: {err}")
        sys.exit(1)
    else:
        print("All tests green.")
