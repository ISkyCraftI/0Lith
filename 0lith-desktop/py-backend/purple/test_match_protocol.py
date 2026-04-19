"""
Tests for purple/match_protocol.py — LLM call path, history management,
context asymmetry, _strip_think, _run_round scaffolding.

Run: python py-backend/purple/test_match_protocol.py
  or: python -m pytest py-backend/purple/test_match_protocol.py -v
"""

from __future__ import annotations

import asyncio
import sys
import os
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from purple.match_protocol import (
    AgentMove,
    MatchPhase,
    MatchProtocol,
    MoveType,
    RoundData,
)
from purple.cyber_range import CyberRange, RangeStatus, ExecResult
from purple.scenario_generator import ScenarioConfig, ServiceConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_svc(name: str = "vuln-webapp", ip: str = "10.42.1.1", port: int = 5000) -> ServiceConfig:
    return ServiceConfig(name=name, image=f"0lith/{name}:latest",
                        ip=ip, port=port, vulns=[], credentials=None)


def _make_scenario() -> ScenarioConfig:
    return ScenarioConfig(
        seed=42,
        difficulty="easy",
        services=[
            _make_svc("vuln-webapp", port=5000),
            _make_svc("vuln-ssh", ip="10.42.1.2", port=22),
        ],
        objective="Retrieve /flag.txt",
        objective_techniques=["T1190"],
        max_rounds=3,
        time_budget_minutes=10,
    )


def _make_protocol(
    red_llm=None,
    blue_llm=None,
    red_model: str | None = None,
    blue_model: str | None = None,
) -> MatchProtocol:
    """Creates a MatchProtocol with a mock CyberRange (HEALTHY, no Docker)."""
    scenario = _make_scenario()
    cr = CyberRange(scenario, use_gvisor=False)
    cr.status = RangeStatus.HEALTHY
    return MatchProtocol(
        scenario=scenario,
        cyber_range=cr,
        red_llm=red_llm,
        blue_llm=blue_llm,
        red_model=red_model,
        blue_model=blue_model,
    )


# ---------------------------------------------------------------------------
# _strip_think
# ---------------------------------------------------------------------------

class TestStripThink(unittest.TestCase):

    def test_removes_think_block(self) -> None:
        text = "<think>some internal reasoning</think>Final answer."
        self.assertEqual(MatchProtocol._strip_think(text), "Final answer.")

    def test_removes_multiline_think(self) -> None:
        text = "<think>\nstep 1\nstep 2\n</think>\nResponse."
        self.assertEqual(MatchProtocol._strip_think(text), "Response.")

    def test_no_think_block(self) -> None:
        text = "Clean response without think."
        self.assertEqual(MatchProtocol._strip_think(text), text)

    def test_multiple_think_blocks(self) -> None:
        text = "<think>a</think>text<think>b</think>end"
        self.assertEqual(MatchProtocol._strip_think(text), "textend")

    def test_empty_think(self) -> None:
        self.assertEqual(MatchProtocol._strip_think("<think></think>hello"), "hello")

    def test_empty_string(self) -> None:
        self.assertEqual(MatchProtocol._strip_think(""), "")


# ---------------------------------------------------------------------------
# _update_history / history cap
# ---------------------------------------------------------------------------

class TestUpdateHistory(unittest.TestCase):

    def setUp(self) -> None:
        self.p = _make_protocol()

    def test_adds_two_entries(self) -> None:
        self.p._update_history("red", "user msg", "assistant msg")
        h = self.p._agent_history["red"]
        self.assertEqual(len(h), 2)
        self.assertEqual(h[0]["role"], "user")
        self.assertEqual(h[1]["role"], "assistant")

    def test_caps_at_four_entries(self) -> None:
        for i in range(4):
            self.p._update_history("red", f"user {i}", f"resp {i}")
        self.assertEqual(len(self.p._agent_history["red"]), 4)

    def test_rolling_window(self) -> None:
        """After 3 rounds, only last 2 survive."""
        for i in range(3):
            self.p._update_history("red", f"u{i}", f"a{i}")
        h = self.p._agent_history["red"]
        self.assertEqual(len(h), 4)
        self.assertEqual(h[0]["content"], "u1")  # round 2 user
        self.assertEqual(h[2]["content"], "u2")  # round 3 user

    def test_blue_history_independent_from_red(self) -> None:
        self.p._update_history("red", "r", "red resp")
        self.p._update_history("blue", "b", "blue resp")
        self.assertEqual(len(self.p._agent_history["red"]), 2)
        self.assertEqual(len(self.p._agent_history["blue"]), 2)


# ---------------------------------------------------------------------------
# _inject_history_into_prompt (callable fallback path)
# ---------------------------------------------------------------------------

class TestInjectHistory(unittest.TestCase):

    def setUp(self) -> None:
        self.p = _make_protocol()
        self.p._agent_system["red"] = "You are Red Team."

    def test_no_history_returns_prompt(self) -> None:
        result = self.p._inject_history_into_prompt("red", "do recon")
        self.assertIn("do recon", result)
        self.assertIn("You are Red Team.", result)

    def test_history_injected(self) -> None:
        self.p._update_history("red", "previous user msg", "previous assistant msg")
        result = self.p._inject_history_into_prompt("red", "current task")
        self.assertIn("CONVERSATION HISTORY", result)
        self.assertIn("previous user msg", result)
        self.assertIn("previous assistant msg", result)
        self.assertIn("current task", result)

    def test_blue_history_not_in_red_prompt(self) -> None:
        self.p._update_history("blue", "blue analysis", "blue resp")
        result = self.p._inject_history_into_prompt("red", "red task")
        self.assertNotIn("blue analysis", result)


# ---------------------------------------------------------------------------
# _call_agent — callable path
# ---------------------------------------------------------------------------

class TestCallAgentCallablePath(unittest.IsolatedAsyncioTestCase):

    async def test_callable_path_returns_response(self) -> None:
        async def fake_llm(prompt): return "Recon complete — found port 5000"
        p = _make_protocol(red_llm=fake_llm)
        p._agent_system["red"] = "You are Red."
        result = await p._call_agent("red", "scan the network", "You are Red.")
        self.assertIn("Recon complete", result)

    async def test_callable_path_strips_think(self) -> None:
        async def llm_with_think(prompt):
            return "<think>reasoning</think>Final answer here"
        p = _make_protocol(red_llm=llm_with_think)
        result = await p._call_agent("red", "attack", "")
        self.assertEqual(result, "Final answer here")

    async def test_callable_path_updates_history(self) -> None:
        async def fake_llm(prompt): return "I scanned and found CVE-2021-41773"
        p = _make_protocol(red_llm=fake_llm)
        await p._call_agent("red", "run exploit", "")
        self.assertEqual(len(p._agent_history["red"]), 2)
        self.assertEqual(p._agent_history["red"][0]["role"], "user")
        self.assertEqual(p._agent_history["red"][1]["role"], "assistant")

    async def test_callable_timeout_returns_error_string(self) -> None:
        async def slow_llm(prompt):
            await asyncio.sleep(10)
            return "too late"
        p = _make_protocol(red_llm=slow_llm)
        result = await p._call_agent("red", "run", "", timeout=1)
        self.assertIn("TIMEOUT", result)
        # History should NOT be updated on timeout
        self.assertEqual(len(p._agent_history["red"]), 0)

    async def test_callable_exception_returns_error_string(self) -> None:
        async def failing_llm(prompt): raise ConnectionError("Ollama down")
        p = _make_protocol(red_llm=failing_llm)
        result = await p._call_agent("red", "run", "")
        self.assertIn("ERROR", result)

    async def test_no_llm_configured_returns_error(self) -> None:
        p = _make_protocol()  # Neither callable nor model
        result = await p._call_agent("red", "run", "")
        self.assertIn("ERROR", result)
        self.assertIn("No LLM configured", result)


# ---------------------------------------------------------------------------
# _call_agent — direct Ollama path (mock _ollama_call directly)
# aiohttp is not available in dev env, so we mock at the method boundary.
# ---------------------------------------------------------------------------

class TestCallAgentOllamaPath(unittest.IsolatedAsyncioTestCase):
    """Tests for the model-direct path in _call_agent.

    Strategy: patch MatchProtocol._ollama_call instead of aiohttp to avoid
    requiring the aiohttp package in unit tests (it's only needed at runtime).
    """

    async def test_ollama_path_returns_response(self) -> None:
        p = _make_protocol(red_model="pyrolith-v2")
        with patch.object(p, "_ollama_call", AsyncMock(return_value="nmap -sV 10.42.1.1")):
            result = await p._call_agent("red", "scan hosts", "You are Red.")
        self.assertIn("nmap", result)

    async def test_ollama_path_strips_think(self) -> None:
        p = _make_protocol(red_model="pyrolith-v2")
        with patch.object(p, "_ollama_call", AsyncMock(return_value="<think>plan</think>curl http://10.42.1.1:5000/")):
            result = await p._call_agent("red", "exploit", "")
        self.assertNotIn("<think>", result)
        self.assertIn("curl", result)

    async def test_ollama_path_updates_history(self) -> None:
        p = _make_protocol(red_model="pyrolith-v2")
        with patch.object(p, "_ollama_call", AsyncMock(return_value="Persistent backdoor installed via cron")):
            await p._call_agent("red", "persist", "")
        self.assertEqual(len(p._agent_history["red"]), 2)

    async def test_ollama_path_passes_system_and_history(self) -> None:
        """_ollama_call should receive system prompt and agent history."""
        p = _make_protocol(red_model="pyrolith-v2")
        p._agent_history["red"] = [
            {"role": "user",      "content": "prev user"},
            {"role": "assistant", "content": "prev resp"},
        ]
        captured: dict = {}

        async def capture_ollama_call(url, model, system, history, prompt, timeout):
            captured["url"]     = url
            captured["model"]   = model
            captured["system"]  = system
            captured["history"] = list(history)
            captured["prompt"]  = prompt
            return "ok response here — enough chars"

        with patch.object(p, "_ollama_call", side_effect=capture_ollama_call):
            await p._call_agent("red", "user msg", "SYSTEM_ROLE")

        self.assertEqual(captured["model"],  "pyrolith-v2")
        self.assertEqual(captured["system"], "SYSTEM_ROLE")
        self.assertEqual(len(captured["history"]), 2)
        self.assertEqual(captured["prompt"], "user msg")

    async def test_ollama_short_response_falls_back(self) -> None:
        """Primary returns < 20 chars → _ollama_call called a second time (fallback)."""
        p = _make_protocol(red_model="pyrolith-v2")
        call_count = [0]
        responses = ["ok", "Proper fallback response here"]

        async def side_effect(**kwargs):
            r = responses[min(call_count[0], len(responses) - 1)]
            call_count[0] += 1
            return r

        with patch.object(p, "_ollama_call", side_effect=side_effect):
            result = await p._call_agent("red", "exploit", "")

        self.assertEqual(call_count[0], 2)
        self.assertIn("Proper fallback response here", result)

    async def test_ollama_error_falls_back(self) -> None:
        """Primary raises → _ollama_call called a second time with fallback model."""
        p = _make_protocol(red_model="pyrolith-v2")
        call_count = [0]

        async def side_effect(url, model, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                raise ConnectionError("primary down")
            return "Fallback worked fine here"

        with patch.object(p, "_ollama_call", side_effect=side_effect):
            result = await p._call_agent("red", "exploit", "")

        self.assertEqual(call_count[0], 2)
        self.assertIn("Fallback worked fine here", result)

    async def test_ollama_both_fail_returns_error_string(self) -> None:
        """Both primary and fallback fail → returns error string, no exception."""
        p = _make_protocol(red_model="pyrolith-v2")

        with patch.object(p, "_ollama_call", AsyncMock(side_effect=ConnectionError("down"))):
            result = await p._call_agent("red", "exploit", "")

        self.assertIn("ERROR", result)
        # Should NOT raise

    async def test_ollama_uses_correct_url_per_agent(self) -> None:
        """Red uses red_url, Blue uses blue_url."""
        p = _make_protocol(red_model="pyrolith-v2", blue_model="cryolith-v2")
        p._red_url  = "http://red-host:11435"
        p._blue_url = "http://blue-host:11434"
        captured_urls: list[str] = []

        async def capture(url, model, **kwargs):
            captured_urls.append(url)
            return "response with enough content here to pass"

        with patch.object(p, "_ollama_call", side_effect=capture):
            await p._call_agent("red", "r", "")
            await p._call_agent("blue", "b", "")

        self.assertIn("http://red-host:11435",  captured_urls)
        self.assertIn("http://blue-host:11434", captured_urls)


# ---------------------------------------------------------------------------
# Context asymmetry: Red ≠ Blue (key invariant)
# ---------------------------------------------------------------------------

class TestContextAsymmetry(unittest.TestCase):

    def setUp(self) -> None:
        self.p = _make_protocol()
        self.p._red_briefing = self.p._build_red_briefing()
        self.p._blue_briefing = self.p._build_blue_briefing()

    def test_red_prompt_does_not_contain_siem(self) -> None:
        prompt = self.p._build_red_prompt(MatchPhase.RECON, 1)
        self.assertNotIn("SIEM", prompt)
        self.assertNotIn("siem", prompt)

    def test_blue_prompt_does_not_contain_commands(self) -> None:
        # Inject some red history to be sure it doesn't leak
        self.p._agent_history["red"] = [
            {"role": "user", "content": "nmap -sV 10.42.1.1"},
            {"role": "assistant", "content": "Open ports: 5000"},
        ]
        prompt = self.p._build_blue_prompt(MatchPhase.EXPLOITATION, 1, ["syslog line"])
        # Red commands must NOT be in blue prompt
        self.assertNotIn("nmap", prompt)
        self.assertNotIn("Open ports: 5000", prompt)

    def test_red_prompt_contains_briefing_and_objective(self) -> None:
        prompt = self.p._build_red_prompt(MatchPhase.RECON, 1)
        self.assertIn("10.42.1.1", prompt)   # IP from briefing
        self.assertIn("Retrieve /flag.txt", prompt)  # objective

    def test_blue_prompt_contains_siem_logs(self) -> None:
        logs = ["Jan 1 12:00:00 host sshd[1234]: Invalid user admin"]
        prompt = self.p._build_blue_prompt(MatchPhase.EXPLOITATION, 1, logs)
        self.assertIn("Invalid user admin", prompt)

    def test_blue_context_uses_own_rounds_only(self) -> None:
        """Blue context is built from self.rounds, not from Red move data."""
        blue_move = AgentMove(
            agent="blue",
            phase=MatchPhase.EXPLOITATION,
            round_num=1,
            move_type=MoveType.ALERT,
            content="Detected port scan pattern from 10.42.1.1",
        )
        red_move = AgentMove(
            agent="red",
            phase=MatchPhase.EXPLOITATION,
            round_num=1,
            move_type=MoveType.EXPLOIT,
            content="nmap -sV 10.42.1.2",
        )
        rd = RoundData(phase=MatchPhase.EXPLOITATION, round_num=1)
        rd.blue_move = blue_move
        rd.red_move  = red_move
        self.p.rounds.append(rd)

        ctx = self.p._build_blue_context()
        self.assertIn("Detected port scan pattern", ctx)
        # Blue context must NOT include Red move content
        self.assertNotIn("nmap -sV", ctx)

    def test_red_context_shows_exec_results(self) -> None:
        """Red context includes exec output from previous rounds."""
        exec_res = ExecResult(
            service="vuln-webapp",
            command="ls /",
            stdout="bin etc flag.txt var",
            stderr="",
            exit_code=0,
        )
        round_data = RoundData(phase=MatchPhase.RECON, round_num=1)
        move = AgentMove(
            agent="red",
            phase=MatchPhase.RECON,
            round_num=1,
            move_type=MoveType.SCAN,
            content="Scanned",
            exec_results=[exec_res],
        )
        round_data.red_move = move
        self.p.rounds.append(round_data)

        ctx = self.p._build_red_context()
        self.assertIn("ls /", ctx)
        self.assertIn("flag.txt", ctx)


# ---------------------------------------------------------------------------
# _call_agent_move wraps AgentMove correctly
# ---------------------------------------------------------------------------

class TestCallAgentMove(unittest.IsolatedAsyncioTestCase):

    async def test_red_move_extracts_commands(self) -> None:
        async def llm(prompt):
            return "I will run:\n```bash\nnmap -sV 10.42.1.1\ncurl http://10.42.1.1:5000/\n```"
        p = _make_protocol(red_llm=llm)
        p._agent_system["red"] = ""
        move = await p._call_agent_move(
            agent="red", prompt="scan", phase=MatchPhase.RECON, round_num=1, timeout=30
        )
        self.assertIsInstance(move, AgentMove)
        self.assertIn("nmap -sV 10.42.1.1", move.commands)
        self.assertIn("curl http://10.42.1.1:5000/", move.commands)
        self.assertEqual(move.agent, "red")

    async def test_blue_move_extracts_sigma(self) -> None:
        sigma_rule = """
title: Port Scan Detection
logsource:
  product: linux
detection:
  keywords: nmap
  condition: keywords
"""
        async def llm(prompt):
            return f"Detection:```yaml\n{sigma_rule}\n```"
        p = _make_protocol(blue_llm=llm)
        p._agent_system["blue"] = ""
        move = await p._call_agent_move(
            agent="blue", prompt="analyze", phase=MatchPhase.EXPLOITATION, round_num=1, timeout=30
        )
        self.assertEqual(len(move.sigma_rules), 1)
        self.assertIn("logsource", move.sigma_rules[0])

    async def test_move_type_inferred_from_phase(self) -> None:
        async def llm(prompt): return "monitoring network traffic"
        p = _make_protocol(blue_llm=llm)
        p._agent_system["blue"] = ""
        move = await p._call_agent_move(
            agent="blue", prompt="check", phase=MatchPhase.RECON, round_num=1, timeout=30
        )
        self.assertEqual(move.move_type, MoveType.MONITOR)

    async def test_duration_recorded(self) -> None:
        async def llm(prompt): return "response with meaningful content here"
        p = _make_protocol(red_llm=llm)
        p._agent_system["red"] = ""
        move = await p._call_agent_move(
            agent="red", prompt="go", phase=MatchPhase.EXPLOITATION, round_num=1, timeout=30
        )
        self.assertGreaterEqual(move.duration_s, 0)


# ---------------------------------------------------------------------------
# _run_setup initializes system prompts and briefings
# ---------------------------------------------------------------------------

class TestRunSetup(unittest.IsolatedAsyncioTestCase):

    async def test_setup_populates_system_prompts(self) -> None:
        p = _make_protocol()
        events = []
        async for event in p._run_setup():
            events.append(event)

        self.assertIn("red", p._agent_system)
        self.assertIn("blue", p._agent_system)
        self.assertIn("Pyrolith", p._agent_system["red"])
        self.assertIn("Cryolith", p._agent_system["blue"])

    async def test_setup_populates_briefings(self) -> None:
        p = _make_protocol()
        async for _ in p._run_setup():
            pass
        self.assertIn("RED TEAM BRIEFING", p._red_briefing)
        self.assertIn("BLUE TEAM BRIEFING", p._blue_briefing)

    async def test_setup_emits_phase_start_complete(self) -> None:
        p = _make_protocol()
        events = []
        async for e in p._run_setup():
            events.append(e)
        event_types = [e["event"] for e in events]
        self.assertIn("phase_start", event_types)
        self.assertIn("phase_complete", event_types)


# ---------------------------------------------------------------------------
# Cancellation support
# ---------------------------------------------------------------------------

class TestCancellation(unittest.IsolatedAsyncioTestCase):

    async def test_cancel_before_phase_stops_run(self) -> None:
        """Setting cancel_event before run() starts should yield no phase events."""
        import asyncio as _asyncio
        p = _make_protocol()
        p._cancel_event.set()

        events = []
        async for event in p.run():
            events.append(event)

        # Only setup events should appear; no recon/exploit phases
        phase_starts = [e for e in events if e.get("event") == "phase_start"
                       and e.get("phase") != "setup"]
        self.assertEqual(phase_starts, [])

    async def test_cancel_sets_correct_phase(self) -> None:
        """After cancellation during run, finalize returns SETUP or SCORING."""
        p = _make_protocol()
        p._cancel_event.set()

        async for _ in p.run():
            pass

        # Phase should still be SETUP (we short-circuited before RECON)
        self.assertIn(p.phase, (MatchPhase.SETUP, MatchPhase.SCORING))


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    unittest.main(verbosity=2)
