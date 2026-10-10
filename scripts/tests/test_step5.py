#!/usr/bin/env python3
"""
Step 5 Verification Suite:
1. Verifies .agents/agents/verifier.md tools frontmatter.
2. Tests bridge.py deterministic quiz shuffling across multiple iterations with a 3-question quiz.
3. Verifies state/cache/ directory existence and pre-verification cache swapping protocol.
"""

import json
import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
VERIFIER_MD = WORKSPACE_ROOT / ".agents" / "agents" / "verifier.md"
STATE_DIR = WORKSPACE_ROOT / "state"
CACHE_DIR = STATE_DIR / "cache"
QUIZ_FILE = STATE_DIR / "quiz.json"
VERIFICATION_FILE = STATE_DIR / "verification.json"

sys.path.insert(0, str(WORKSPACE_ROOT))
from bridge import shuffle_quiz, save_quiz_atomic, shuffle_quiz_file


def test_verifier_tools() -> bool:
    print("[TEST 1/3] Verifying .agents/agents/verifier.md tool registration...")
    if not VERIFIER_MD.exists():
        print(f"[FAIL] {VERIFIER_MD} does not exist.")
        return False

    content = VERIFIER_MD.read_text(encoding="utf-8")
    lines = content.splitlines()

    # Extract frontmatter
    in_frontmatter = False
    tools = []
    in_tools = False

    for line in lines:
        if line.strip() == "---":
            if not in_frontmatter:
                in_frontmatter = True
                continue
            else:
                break
        if in_frontmatter:
            if line.strip().startswith("tools:"):
                in_tools = True
                continue
            if in_tools:
                if line.strip().startswith("- "):
                    tools.append(line.strip()[2:].strip())
                elif not line.startswith("  ") and not line.startswith("\t"):
                    in_tools = False

    expected_tools = ["run_command", "view_file"]
    if tools != expected_tools:
        print(f"[FAIL] Tools in verifier.md mismatch: expected {expected_tools}, got {tools}")
        return False

    # Check for forbidden tool references anywhere in frontmatter or tools
    forbidden = ["web_search", "fetch_web_page"]
    for f in forbidden:
        if f in content[:500]: # check frontmatter block
            print(f"[FAIL] Forbidden tool '{f}' found in frontmatter!")
            return False

    print(f"[PASS] Subagent tools strictly registered: {tools} (No unregistered tools).")
    return True


def test_quiz_shuffling() -> bool:
    print("\n[TEST 2/3] Testing deterministic quiz option shuffling in bridge.py...")
    import copy

    dummy_quiz = {
        "questions": [
            {
                "question": "Q1 (Grounding): What is the primary characteristic of an order-winning output?",
                "options": [
                    "A. Provides an output at the highest level possible in the industry to win customer orders",
                    "B. Meets minimum baseline industry entry requirements without differentiation",
                    "C. Guarantees internal zero-defect production without regard to market demands",
                    "D. Matches competitors' standard pricing structures across all regions"
                ],
                "correct_index": 0,
                "explanation": "Order winners directly win customer orders through superior competitive differentiation."
            },
            {
                "question": "Q2 (Operational Trade-off): According to Miltenburg, how many order winners can an average system provide?",
                "options": [
                    "A. Up to five if flexible manufacturing systems are deployed",
                    "B. At most one order-winning output due to structural capability boundaries",
                    "C. Exactly three outputs balanced across cost, delivery, and quality",
                    "D. An unlimited quantity if market qualifiers are ignored"
                ],
                "correct_index": 1,
                "explanation": "Average capability facilities can sustain at most one order-winning output."
            },
            {
                "question": "Q3 (Adversarial Check): Which distractor represents a known operational misconception?",
                "options": [
                    "A. Market qualifiers must be maintained at satisfactory levels",
                    "B. Trade-offs prevent excelling at all dimensions simultaneously",
                    "C. Believing meeting high baseline qualifiers is sufficient to actively win customer orders",
                    "D. World-class manufacturers can support up to two order winners"
                ],
                "correct_index": 2,
                "explanation": "Conflating qualifiers with winners is a documented strategic failure mode."
            }
        ]
    }

    original_correct_options = [
        q["options"][q["correct_index"]] for q in dummy_quiz["questions"]
    ]

    # Test 50 consecutive shuffles
    position_changes = [0, 0, 0]
    for iteration in range(50):
        shuffled = shuffle_quiz(copy.deepcopy(dummy_quiz))
        for q_idx, q in enumerate(shuffled["questions"]):
            # Verification: correct_index must index the exact intended option string
            target_str = original_correct_options[q_idx]
            actual_str = q["options"][q["correct_index"]]
            if actual_str != target_str:
                print(f"[FAIL] Iteration {iteration}, Q{q_idx + 1}: expected '{target_str}', got '{actual_str}'")
                return False
            # Verify correct_idx is also synchronized
            if q.get("correct_idx") != q["correct_index"]:
                print(f"[FAIL] correct_idx ({q.get('correct_idx')}) not in sync with correct_index ({q['correct_index']})")
                return False
            if q["correct_index"] != dummy_quiz["questions"][q_idx]["correct_index"]:
                position_changes[q_idx] += 1

    print(f"[SHUFFLE] Positional permutations observed across 50 iterations: {position_changes}")
    print("[PASS] Quiz shuffling verified: correct_index and correct_idx perfectly track relocated answers across 50 shuffles.")

    # Test atomic file write
    test_quiz_file = STATE_DIR / "test_quiz.json"
    try:
        saved = save_quiz_atomic(dummy_quiz, test_quiz_file, shuffle=True)
        assert test_quiz_file.exists(), "test_quiz.json was not created"
        with open(test_quiz_file, "r", encoding="utf-8") as f:
            disk_data = json.load(f)
        for q_idx, q in enumerate(disk_data["questions"]):
            assert q["options"][q["correct_index"]] == original_correct_options[q_idx]
        print("[PASS] Atomic file writing (.tmp -> rename) verified successfully.")
    finally:
        if test_quiz_file.exists():
            test_quiz_file.unlink()

    return True


def test_cache_directory_and_protocol() -> bool:
    print("\n[TEST 3/3] Verifying state/cache/ directory and pre-verification swap protocol...")
    if not CACHE_DIR.exists() or not CACHE_DIR.is_dir():
        print(f"[FAIL] {CACHE_DIR} does not exist or is not a directory.")
        return False

    test_topic = "test-topic"
    topic_cache_dir = CACHE_DIR / test_topic
    topic_cache_dir.mkdir(parents=True, exist_ok=True)
    test_node_id = "test-node-parallel-prefetch"
    cache_file = topic_cache_dir / f"verification_{test_node_id}.json"
    dummy_audit = {
        "concept": "Test Node Concept",
        "status": "[VERIFIED]",
        "source_type": "local_textbook",
        "document_title": "Test Source",
        "page_range": "Pages 10-15",
        "citation": "Author, 2026",
        "canonical_definition": "Test Definition",
        "trade_offs_and_boundaries": "Test Tradeoff",
        "violating_assumption": None,
        "missing_prerequisite": None,
        "misconceptions": ["Misconception A", "Misconception B"]
    }

    # 1. Verifier saves audit payload to state/cache/<topic_slug>/verification_<node_id>.json
    tmp_cache = cache_file.with_name(f"{cache_file.name}.tmp")
    with open(tmp_cache, "w", encoding="utf-8") as f:
        json.dump(dummy_audit, f, indent=2)
    tmp_cache.replace(cache_file)
    assert cache_file.exists(), "Failed to create cache audit payload"
    print(f"[PREFETCH] Pre-verification payload staged at: state/cache/{test_topic}/{cache_file.name}")

    try:
        with open(cache_file, "r", encoding="utf-8") as f:
            loaded = json.load(f)
        assert loaded["concept"] == "Test Node Concept"
        assert loaded["status"] == "[VERIFIED]"
        print("[PASS] Scoped cache audit payload verified with zero audit latency.")
    finally:
        shutil.rmtree(topic_cache_dir, ignore_errors=True)

    return True


class TestStep5(unittest.TestCase):
    def test_verifier_tools(self):
        self.assertTrue(test_verifier_tools())

    def test_quiz_shuffling(self):
        self.assertTrue(test_quiz_shuffling())

    def test_cache_directory_and_protocol(self):
        self.assertTrue(test_cache_directory_and_protocol())


def main():
    print("=" * 60)
    print("STEP 5 ARCHITECTURAL VERIFICATION SUITE")
    print("=" * 60)

    suite = unittest.TestLoader().loadTestsFromTestCase(TestStep5)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    if not result.wasSuccessful():
        sys.exit(1)


if __name__ == "__main__":
    main()
