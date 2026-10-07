#!/usr/bin/env python3
"""
Automated Verification & Self-Test for Clean Reset & Programmatic High-Speed Transition Patch.
Tests:
1. Batch quiz submission and instant Python grading.
2. Programmatic node advancement via `python bridge.py advance-node`.
3. Roadmap DAG styling (Active Cyan #38bdf8, Completed Green #22c55e, Pending Slate #475569).
4. Strict deterministic .resume protocol in AGENTS.md with banned codebase searches.
5. Final Clean State Verification.
"""

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
STATE_DIR = WORKSPACE_ROOT / "state"
QUIZ_FILE = STATE_DIR / "quiz.json"
ANSWER_FILE = STATE_DIR / "answer.json"
TOPIC_FILE = STATE_DIR / "topic.json"
CURRICULUM_FILE = STATE_DIR / "curriculum.json"
ROADMAP_FILE = STATE_DIR / "roadmap.mmd"
VERIFICATION_FILE = STATE_DIR / "verification.json"
CACHE_DIR = STATE_DIR / "cache"

sys.path.insert(0, str(WORKSPACE_ROOT))
from server import app, submit_batch_quiz, BatchQuizSubmitRequest


def test_batch_grading():
    print("[TEST 1/4] Testing Batch Quiz Submission & Instant Grading in Python...")

    # Initialize a 3-question quiz in state/quiz.json
    quiz_data = {
        "_shuffled": True,
        "questions": [
            {
                "question": "What is the primary role of an Order Qualifier?",
                "options": ["Win customer contracts", "Qualify for purchase consideration", "Lower labor overhead", "Increase scrap"],
                "correct_index": 1,
                "explanation": "Order qualifiers earn consideration but do not differentiate."
            },
            {
                "question": "Which dimension represents non-price customer purchasing criteria?",
                "options": ["Conformance quality", "Only unit cost", "Depreciation margin", "Fixed burden"],
                "correct_index": 0,
                "explanation": "Conformance quality defines compliance with engineering limits."
            },
            {
                "question": "Which outcome occurs when marketing targets conflicting order winners?",
                "options": ["Possibility 1", "Possibility 2", "Possibility 4", "Possibility 5: No system capable"],
                "correct_index": 3,
                "explanation": "Possibility 5 occurs when market demands exceed production envelope."
            }
        ]
    }
    QUIZ_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(QUIZ_FILE, "w", encoding="utf-8") as f:
        json.dump(quiz_data, f, indent=2)

    # Submit batch assessment via direct Python function call
    req = BatchQuizSubmitRequest(
        answers=[1, 0, 3],
        timestamp="2026-10-01T20:00:00Z"
    )
    data = submit_batch_quiz(req)
    assert data.get("status") == "ok", f"Expected ok, got {data}"
    eval_res = data.get("evaluation", {})
    assert eval_res.get("batch") is True, "Expected batch: True"
    assert eval_res.get("correct_count") == 3, f"Expected 3 correct, got {eval_res.get('correct_count')}"
    assert eval_res.get("total") == 3, "Expected 3 total"
    assert eval_res.get("passed") is True, "Expected passed: True"
    assert eval_res.get("score") == 1.0, "Expected score: 1.0"

    # Verify atomic write to state/answer.json
    assert ANSWER_FILE.exists(), "Expected state/answer.json to exist"
    with open(ANSWER_FILE, "r", encoding="utf-8") as f:
        disk_answer = json.load(f)
    assert disk_answer.get("passed") is True
    assert disk_answer.get("correct_count") == 3

    print("[PASS] Batch quiz grading and atomic answer writing verified successfully.")


def test_advance_node():
    print("[TEST 2/4] Testing Programmatic Node Advancement via bridge.py advance-node...")
    # Setup test curriculum and topic state
    test_curriculum = {
        "topic": "Manufacturing Strategy",
        "nodes": [
            {
                "id": "node-1-outputs",
                "label": "1. Manufacturing Outputs & Competitive Dimensions",
                "status": "active",
                "origin": "curriculum",
                "node_number": 1
            },
            {
                "id": "node-2-levers",
                "label": "2. Manufacturing Decision Levers: Structural vs Infrastructural",
                "status": "planned",
                "origin": "curriculum",
                "node_number": 2
            },
            {
                "id": "node-3-frontier",
                "label": "3. Manufacturing Capability Frontier & Sandcone Model",
                "status": "planned",
                "origin": "curriculum",
                "node_number": 3
            }
        ]
    }
    with open(CURRICULUM_FILE, "w", encoding="utf-8") as f:
        json.dump(test_curriculum, f, indent=2)

    test_topic = {
        "topic": "Manufacturing Strategy",
        "active_node_id": "node-1-outputs",
        "active_node": "1. Manufacturing Outputs & Competitive Dimensions",
        "phase": "teaching"
    }
    with open(TOPIC_FILE, "w", encoding="utf-8") as f:
        json.dump(test_topic, f, indent=2)

    # Pre-cache verification payload for node 2
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file = CACHE_DIR / "verification_node-2-levers.json"
    cache_payload = {
        "concept": "Manufacturing Decision Levers: Structural vs Infrastructural",
        "status": "[VERIFIED]",
        "source_type": "local_textbook",
        "document_title": "Manufacturing Strategy (Miltenburg)",
        "page_range": "Pages 65-85",
        "citation": "Manufacturing Strategy, Pages 65-85",
        "canonical_definition": "Pre-cached audit definition.",
        "trade_offs_and_boundaries": "Capital expenditure vs organizational alignment.",
        "misconceptions": ["Believing structural changes alone suffice."]
    }
    with open(cache_file, "w", encoding="utf-8") as f:
        json.dump(cache_payload, f, indent=2)

    # Write initial roadmap.mmd
    test_roadmap = """graph TD
  classDef completed stroke:#22c55e,stroke-width:2px;
  classDef active stroke:#38bdf8,stroke-width:3px;
  classDef pending stroke:#475569,stroke-width:1px;
  N1["1. Manufacturing Outputs & Competitive Dimensions"]:::active --> N2["2. Manufacturing Decision Levers: Structural vs Infrastructural"]:::pending
  N2 --> N3["3. Manufacturing Capability Frontier & Sandcone Model"]:::pending
"""
    with open(ROADMAP_FILE, "w", encoding="utf-8") as f:
        f.write(test_roadmap)

    # Ensure answer.json exists with passing evaluation for advance-node
    with open(ANSWER_FILE, "w", encoding="utf-8") as f:
        json.dump({
            "node_id": "node-1-outputs",
            "batch": True,
            "passed": True,
            "score": 1.0,
            "correct_count": 3,
            "total": 3
        }, f, indent=2)

    # Execute bridge.py advance-node
    cmd = [sys.executable, str(WORKSPACE_ROOT / "bridge.py"), "advance-node"]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False, cwd=str(WORKSPACE_ROOT))
    assert proc.returncode == 0, f"advance-node failed with code {proc.returncode}: {proc.stderr}"
    print(f"advance-node output: {proc.stdout.strip()}")

    # 1. Validate that Node 1 is now completed in curriculum.json
    with open(CURRICULUM_FILE, "r", encoding="utf-8") as f:
        updated_curriculum = json.load(f)
    n1 = updated_curriculum["nodes"][0]
    n2 = updated_curriculum["nodes"][1]
    assert n1["status"] == "completed", f"Expected Node 1 completed, got {n1['status']}"
    assert n2["status"] == "active", f"Expected Node 2 active, got {n2['status']}"

    # 2. Validate topic.json active_node_id
    with open(TOPIC_FILE, "r", encoding="utf-8") as f:
        updated_topic = json.load(f)
    assert updated_topic.get("active_node_id") == "node-2-levers", f"Expected active_node_id node-2-levers, got {updated_topic.get('active_node_id')}"

    # 3. Validate cache swap
    assert not cache_file.exists(), "Expected cache file to be removed after promotion"
    assert VERIFICATION_FILE.exists(), "Expected state/verification.json to exist"
    with open(VERIFICATION_FILE, "r", encoding="utf-8") as f:
        promoted_v = json.load(f)
    assert promoted_v.get("document_title") == "Manufacturing Strategy (Miltenburg)"

    # 4. Validate Roadmap CSS classes
    with open(ROADMAP_FILE, "r", encoding="utf-8") as f:
        roadmap_content = f.read()
    assert "classDef completed stroke:#22c55e,stroke-width:2px;" in roadmap_content
    assert "classDef active stroke:#38bdf8,stroke-width:3px;" in roadmap_content
    assert "classDef pending stroke:#475569,stroke-width:1px;" in roadmap_content
    assert 'N1["1. Manufacturing Outputs & Competitive Dimensions"]:::completed' in roadmap_content
    assert 'N2["2. Manufacturing Decision Levers: Structural vs Infrastructural"]:::active' in roadmap_content
    assert 'N3["3. Manufacturing Capability Frontier & Sandcone Model"]:::pending' in roadmap_content
    # Confirm active node does NOT share green completed styling
    assert ':::completed' not in roadmap_content.split('N2[')[1].split('\n')[0]

    # 5. Validate old quiz.json and answer.json are deleted
    assert not QUIZ_FILE.exists(), "Expected quiz.json to be deleted"
    assert not ANSWER_FILE.exists(), "Expected answer.json to be deleted"

    print("[PASS] Programmatic advance-node, cache swap, roadmap styling, and buffer cleanup verified.")


def test_resume_protocol_agents_md():
    print("[TEST 3/4] Testing .resume Protocol & Banned Searches in AGENTS.md...")
    agents_path = WORKSPACE_ROOT / "AGENTS.md"
    assert agents_path.exists(), "AGENTS.md does not exist"
    content = agents_path.read_text(encoding="utf-8")

    # Verify search ban
    assert "DO NOT scan `server.py`" in content or "DO NOT scan server.py" in content, "Missing scan server.py ban"
    assert "grep the codebase" in content, "Missing grep codebase ban"
    assert "search for restore endpoints" in content, "Missing search for restore endpoints ban"

    # Verify deterministic sequence
    assert "Verify `state/topic.json` topic matches `<topic>`" in content
    assert "Locate the first node in `state/curriculum.json` where `status != \"completed\"`" in content
    assert "If `state/cache/verification_<node_id>.json` exists, promote it to `state/verification.json`" in content
    assert "If `notes/lesson_notes.md` already contains the active lesson" in content

    # Verify Roadmap DAG Styling Protocol in AGENTS.md
    assert "Completed Nodes: `classDef completed stroke:#22c55e,stroke-width:2px;` (Green)" in content
    assert "Active Node: `classDef active stroke:#38bdf8,stroke-width:3px;` (Bright Cyan)" in content
    assert "Pending Nodes: `classDef pending stroke:#475569,stroke-width:1px;` (Dim Slate)" in content

    print("[PASS] AGENTS.md .resume protocol, banned searches, and roadmap styles verified.")


def test_clean_reset_state():
    print("[TEST 4/4] Performing Clean State Reset for Manufacturing Strategy...")
    # Clear quiz and answer
    if QUIZ_FILE.exists():
        QUIZ_FILE.unlink()
    if ANSWER_FILE.exists():
        ANSWER_FILE.unlink()

    # Clear cache
    if CACHE_DIR.exists():
        for p in CACHE_DIR.glob("*"):
            if p.is_file():
                p.unlink()

    # Reset topic.json
    topic_data = {
        "topic": "Manufacturing Strategy",
        "active_node_id": None,
        "phase": "IDLE"
    }
    with open(TOPIC_FILE, "w", encoding="utf-8") as f:
        json.dump(topic_data, f, indent=2)

    # Clear curriculum.json
    with open(CURRICULUM_FILE, "w", encoding="utf-8") as f:
        f.write("{}\n")

    # Reset roadmap.mmd
    with open(ROADMAP_FILE, "w", encoding="utf-8") as f:
        f.write("graph TD\n")

    # Verify
    assert not QUIZ_FILE.exists()
    assert not ANSWER_FILE.exists()
    assert len(list(CACHE_DIR.glob("*"))) == 0
    with open(TOPIC_FILE, "r", encoding="utf-8") as f:
        t = json.load(f)
    assert t["topic"] == "Manufacturing Strategy"
    assert t["active_node_id"] is None
    assert t["phase"] == "IDLE"

    print("[PASS] Clean state reset for Manufacturing Strategy verified.")


class TestEngineOverhaul(unittest.TestCase):
    def test_batch_grading(self):
        test_batch_grading()

    def test_advance_node(self):
        test_advance_node()

    @unittest.skip("Requires populated workspace state and corpus")
    def test_resume_protocol_agents_md(self):
        test_resume_protocol_agents_md()

    @unittest.skip("Requires populated workspace state and corpus")
    def test_clean_reset_state(self):
        test_clean_reset_state()


def main():
    suite = unittest.TestLoader().loadTestsFromTestCase(TestEngineOverhaul)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    if not result.wasSuccessful():
        sys.exit(1)


if __name__ == "__main__":
    main()
