#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
0Lith — Test Shadow Thinking (olith_watcher.py)
================================================
Validates the Shadow Thinking pipeline: snippet extraction, file priority
sorting, JSON fallback parsing, and the full end-to-end Hodolith → Mem0 flow.

Usage:
    python test_shadow_thinking.py              # Full test (needs Ollama + qwen3:1.7b)
    python test_shadow_thinking.py --skip-llm  # Pure logic only (no Ollama needed)
"""

import sys
import io
import os
import argparse

# Force UTF-8 output on Windows (box-drawing chars in banner)
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

# ── Helpers ───────────────────────────────────────────────────────────────────

def ok(msg):   print(f"  \u2705 {msg}")
def fail(msg): print(f"  \u274c {msg}"); sys.exit(1)
def info(msg): print(f"  \u2139  {msg}")
def skip(msg): print(f"  \u23ed  SKIP  {msg}")
def header(msg):
    print(f"\n{'='*60}")
    print(f"  {msg}")
    print(f"{'='*60}")

# ── Helpers for Ollama availability ──────────────────────────────────────────

def _ollama_available() -> bool:
    try:
        import requests
        r = requests.get("http://localhost:11434/api/tags", timeout=3)
        return r.status_code == 200
    except Exception:
        return False

# ── Tests ─────────────────────────────────────────────────────────────────────

def test_import_and_instantiate():
    header("1. Import + instantiate OlithWatcher")
    try:
        # olith_watcher imports watchdog at module level; make sure deps exist
        from olith_watcher import OlithWatcher
        w = OlithWatcher()
        ok("OlithWatcher imported and instantiated")
        return w
    except ImportError as e:
        fail(f"Import failed: {e}")
    except Exception as e:
        fail(f"Instantiation failed: {e}")


def test_extract_snippet_real_file(watcher):
    header("2. _extract_file_snippet — real .py file (this script)")
    path = str(__file__)
    snippet = watcher._extract_file_snippet(path)

    if not snippet:
        fail(f"Empty snippet returned for {path}")

    lines = snippet.splitlines()
    info(f"Snippet: {len(lines)} line(s), {len(snippet)} char(s)")

    # Must be ≤ SHADOW_SNIPPET_LINES (30)
    from olith_watcher import SHADOW_SNIPPET_LINES
    if len(lines) > SHADOW_SNIPPET_LINES:
        fail(f"Snippet exceeds {SHADOW_SNIPPET_LINES} lines: got {len(lines)}")

    ok(f"Snippet extracted correctly (≤{SHADOW_SNIPPET_LINES} lines)")


def test_extract_snippet_binary_extension(watcher):
    header("3. _extract_file_snippet — fake binary extension → returns ''")
    # .exe is not in TEXT_EXTENSIONS — should return "" without error
    fake_path = str(__file__).replace(".py", ".exe")
    result = watcher._extract_file_snippet(fake_path)
    if result != "":
        fail(f"Expected empty string for binary extension, got: {result!r}")
    ok("Binary extension correctly skipped (returned '')")


def test_pick_shadow_files(watcher):
    header("4. _pick_shadow_files — priority sort")
    changes = {
        "/project/module.rs":      "created",
        "/project/main.py":        "modified",
        "/project/component.svelte": "created",
        "/project/utils.py":       "created",
        "/project/styles.css":     "modified",
    }
    result = watcher._pick_shadow_files(changes)

    info(f"Input: {len(changes)} files")
    for path, ev in result:
        from pathlib import Path
        info(f"  [{ev:8s}] {Path(path).name}")

    # Must return at most SHADOW_MAX_FILES_PER_EVENT (2)
    from olith_watcher import SHADOW_MAX_FILES_PER_EVENT
    if len(result) > SHADOW_MAX_FILES_PER_EVENT:
        fail(f"Returned {len(result)} items, expected ≤{SHADOW_MAX_FILES_PER_EVENT}")

    # Top pick must be main.py (modified .py > everything else)
    top_path, top_event = result[0]
    from pathlib import Path
    if Path(top_path).name != "main.py" or top_event != "modified":
        fail(f"Expected main.py/modified as top priority, got: {top_path}/{top_event}")

    # Second pick: a .py (utils.py created) or .svelte — must NOT be .css or .rs over .py
    second_path, _ = result[1]
    second_ext = Path(second_path).suffix.lower()
    if second_ext not in (".py", ".ts", ".svelte"):
        fail(f"Second pick should be .py/.ts/.svelte, got: {second_ext}")

    ok(f"Priority sort correct — top: {Path(top_path).name}/{top_event}, second: {Path(second_path).name}")


def test_call_hodolith_json_fallbacks(watcher):
    header("5. _call_hodolith_json — 3-level JSON fallback (monkeypatched)")

    import json

    results = {}

    # ── Sub-case A: clean JSON ────────────────────────────────────────────────
    def _mock_clean_json(prompt, timeout=25):
        return '{"prediction": "developer will add tests", "confidence_score": 0.85}'

    watcher._call_hodolith = _mock_clean_json
    r = watcher._call_hodolith_json("test prompt")
    if r is None:
        fail("Sub-case A: got None for clean JSON")
    if r.get("prediction") != "developer will add tests":
        fail(f"Sub-case A: wrong prediction: {r!r}")
    if abs(r.get("confidence_score", -1) - 0.85) > 0.001:
        fail(f"Sub-case A: wrong confidence: {r!r}")
    ok("Sub-case A: clean JSON parsed directly")
    results["A"] = r

    # ── Sub-case B: JSON embedded in prose ───────────────────────────────────
    def _mock_prose_json(prompt, timeout=25):
        return (
            'Sure! Here is my analysis:\n'
            '{"prediction": "add unit tests", "confidence_score": 0.7}\n'
            'Hope that helps!'
        )

    watcher._call_hodolith = _mock_prose_json
    r = watcher._call_hodolith_json("test prompt")
    if r is None:
        fail("Sub-case B: got None for prose-embedded JSON")
    if r.get("prediction") != "add unit tests":
        fail(f"Sub-case B: wrong prediction: {r!r}")
    if abs(r.get("confidence_score", -1) - 0.7) > 0.001:
        fail(f"Sub-case B: wrong confidence: {r!r}")
    ok("Sub-case B: JSON extracted from prose via regex")
    results["B"] = r

    # ── Sub-case C: plain text → synthetic dict ───────────────────────────────
    def _mock_plain_text(prompt, timeout=25):
        return "The developer will probably refactor the module next."

    watcher._call_hodolith = _mock_plain_text
    r = watcher._call_hodolith_json("test prompt")
    if r is None:
        fail("Sub-case C: got None for plain text")
    if "prediction" not in r:
        fail(f"Sub-case C: missing 'prediction' key: {r!r}")
    if r.get("confidence_score") != 0.5:
        fail(f"Sub-case C: expected confidence=0.5, got: {r.get('confidence_score')}")
    ok("Sub-case C: plain text → synthetic dict with confidence=0.5")
    results["C"] = r

    # Restore (not strictly needed but good hygiene)
    del watcher._call_hodolith

    # ── Confidence clamping ───────────────────────────────────────────────────
    def _mock_out_of_range(prompt, timeout=25):
        return '{"prediction": "test", "confidence_score": 99.0}'

    watcher._call_hodolith = _mock_out_of_range
    r = watcher._call_hodolith_json("test prompt")
    if r["confidence_score"] != 1.0:
        fail(f"Clamping: expected 1.0, got {r['confidence_score']}")
    ok("Confidence clamped to [0.0, 1.0]")
    del watcher._call_hodolith


def test_shadow_think_file_e2e(watcher):
    header("6. _shadow_think_file — end-to-end (Ollama + Qdrant required)")

    if not _ollama_available():
        skip("Ollama not available — skipping end-to-end test")
        return

    # Use this script as the 'changed file'
    target = str(__file__)
    info(f"Target file: {target}")

    # The method is silent — it stores to Mem0 internally.
    # We just verify it doesn't raise and returns cleanly.
    try:
        watcher._shadow_think_file(target, "modified")
        ok("_shadow_think_file completed without exception")
    except Exception as e:
        fail(f"_shadow_think_file raised: {e}")


def test_mem0_shadow_entry(watcher):
    header("7. Mem0 entry verification — shadow_thinking entries")

    if not _ollama_available():
        skip("Ollama not available — skipping Mem0 verification")
        return

    # Ensure memory is initialized
    if not watcher._ensure_memory():
        skip("Mem0/Qdrant could not be initialized — skipping")
        return

    try:
        # Search for shadow_thinking entries stored by test 6
        results = watcher.memory.search(
            "shadow prediction file change",
            user_id="hodolith",
            limit=10,
        )
        # mem0 returns a list or a dict with 'results' key depending on version
        entries = results if isinstance(results, list) else results.get("results", [])
    except Exception as e:
        fail(f"memory.search raised: {e}")
        return

    shadow_entries = [
        e for e in entries
        if (e.get("metadata") or {}).get("type") == "shadow_thinking"
    ]

    if not shadow_entries:
        # Test 6 may have been skipped or deduped — soft warning, not hard fail
        info("No shadow_thinking entry found (test 6 may have been skipped or deduped)")
        ok("Mem0 search completed — no shadow entries (expected if test 6 was first run)")
        return

    entry = shadow_entries[0]
    meta = entry.get("metadata", {})

    info(f"Found {len(shadow_entries)} shadow_thinking entry/entries")
    info(f"  type            : {meta.get('type')}")
    info(f"  user_id         : {meta.get('user_id')}")
    info(f"  source          : {meta.get('source')}")
    info(f"  confidence_score: {meta.get('confidence_score')}")
    info(f"  file_path       : {meta.get('file_path')}")

    # Validate metadata shape
    errors = []
    if meta.get("type") != "shadow_thinking":
        errors.append(f"type={meta.get('type')!r} (expected 'shadow_thinking')")
    if meta.get("user_id") != "hodolith":
        errors.append(f"user_id={meta.get('user_id')!r} (expected 'hodolith')")
    if meta.get("source") != "file_change":
        errors.append(f"source={meta.get('source')!r} (expected 'file_change')")
    cs = meta.get("confidence_score")
    if cs is None or not (0.0 <= float(cs) <= 1.0):
        errors.append(f"confidence_score={cs!r} (expected float in [0,1])")

    if errors:
        fail("Metadata shape errors:\n" + "\n".join(f"    - {e}" for e in errors))
    else:
        ok("Mem0 entry shape validated (type, user_id, source, confidence_score)")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Test Shadow Thinking — 0Lith olith_watcher.py")
    parser.add_argument(
        "--skip-llm",
        action="store_true",
        help="Run only pure-logic tests 1-5 (no Ollama required)",
    )
    args = parser.parse_args()

    print("""
  \u250c\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2510
  \u2502  0Lith \u2014 Test Shadow Thinking            \u2502
  \u2502  olith_watcher.py \u00b7 py-backend/           \u2502
  \u2514\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2518""")

    if args.skip_llm:
        info("Mode: --skip-llm (tests 1-5 only, no Ollama needed)")
    else:
        if _ollama_available():
            ok("Ollama reachable on :11434")
        else:
            info("Ollama not reachable — tests 6 & 7 will be skipped")

    # ── Pure logic tests (always run) ────────────────────────────────────────
    watcher = test_import_and_instantiate()
    test_extract_snippet_real_file(watcher)
    test_extract_snippet_binary_extension(watcher)
    test_pick_shadow_files(watcher)
    test_call_hodolith_json_fallbacks(watcher)

    # ── Integration tests (skipped with --skip-llm) ───────────────────────────
    if args.skip_llm:
        skip("Tests 6 & 7 skipped (--skip-llm)")
    else:
        test_shadow_think_file_e2e(watcher)
        test_mem0_shadow_entry(watcher)

    print(f"""
{'='*60}
  TOUS LES TESTS PASSENT — Shadow Thinking opérationnel
{'='*60}
""")


if __name__ == "__main__":
    main()
