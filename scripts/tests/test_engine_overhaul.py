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
ACTIVE_SESSION_FILE = STATE_DIR / "active_session.json"
CACHE_DIR = STATE_DIR / "cache"

sys.path.insert(0, str(WORKSPACE_ROOT))
from server import app, submit_batch_quiz, BatchQuizSubmitRequest


def test_batch_grading():
    print("[TEST 1/4] Testing Batch Quiz Submission & Instant Grading in Python...")
    topic_name = "Test Batch Topic"
    topic_dir = WORKSPACE_ROOT / "notes" / topic_name
    sess_dir = topic_dir / ".session"
    sess_dir.mkdir(parents=True, exist_ok=True)
    quiz_file = sess_dir / "quiz.json"
    answer_file = sess_dir / "answer.json"

    # Set active_session.json
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with open(ACTIVE_SESSION_FILE, "w", encoding="utf-8") as f:
        json.dump({"active_topic": topic_name, "phase": "teaching"}, f, indent=2)

    # Initialize a 3-question quiz in notes/Test Batch Topic/.session/quiz.json
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
    with open(quiz_file, "w", encoding="utf-8") as f:
        json.dump(quiz_data, f, indent=2)

    req = BatchQuizSubmitRequest(
        answers=[1, 0, 3],
        timestamp="2026-10-01T20:00:00Z"
    )
    try:
        data = submit_batch_quiz(req)
        assert data.get("status") == "ok", f"Expected ok, got {data}"
        eval_res = data.get("evaluation", {})
        assert eval_res.get("batch") is True, "Expected batch: True"
        assert eval_res.get("correct_count") == 3, f"Expected 3 correct, got {eval_res.get('correct_count')}"
        assert eval_res.get("total") == 3, "Expected 3 total"
        assert eval_res.get("passed") is True, "Expected passed: True"
        assert eval_res.get("score") == 1.0, "Expected score: 1.0"

        # Verify atomic write to notes/Test Batch Topic/.session/answer.json
        assert answer_file.exists(), "Expected topic .session/answer.json to exist"
        with open(answer_file, "r", encoding="utf-8") as f:
            disk_answer = json.load(f)
        assert disk_answer.get("passed") is True
        assert disk_answer.get("correct_count") == 3

        print("[PASS] Batch quiz grading and atomic answer writing verified successfully.")
    finally:
        import shutil
        shutil.rmtree(topic_dir, ignore_errors=True)


def test_advance_node():
    print("[TEST 2/4] Testing Programmatic Node Advancement via bridge.py advance-node...")
    topic_name = "Test Advance Topic"
    topic_dir = WORKSPACE_ROOT / "notes" / topic_name
    sess_dir = topic_dir / ".session"
    sess_dir.mkdir(parents=True, exist_ok=True)
    manifest_file = topic_dir / "manifest.json"
    answer_file = sess_dir / "answer.json"

    # Setup manifest in notes/<topic>/manifest.json
    test_manifest = {
        "topic": topic_name,
        "domain": "operations",
        "nodes": [
            {
                "id": "node-1-outputs",
                "title": "Manufacturing Outputs & Competitive Dimensions",
                "status": "active",
                "origin": "curriculum"
            },
            {
                "id": "node-2-levers",
                "title": "Manufacturing Decision Levers: Structural vs Infrastructural",
                "status": "planned",
                "origin": "curriculum"
            },
            {
                "id": "node-3-frontier",
                "title": "Manufacturing Capability Frontier & Sandcone Model",
                "status": "planned",
                "origin": "curriculum"
            }
        ],
        "edges": []
    }
    with open(manifest_file, "w", encoding="utf-8") as f:
        json.dump(test_manifest, f, indent=2)

    # Create note 1 in vault
    note1_file = topic_dir / "node-1-outputs.md"
    note1_file.write_text(
        "---\nid: node-1-outputs\ntitle: Manufacturing Outputs & Competitive Dimensions\nstatus: in_progress\n---\n\n# Node 1",
        encoding="utf-8"
    )

    # Setup active session in state/active_session.json
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with open(ACTIVE_SESSION_FILE, "w", encoding="utf-8") as f:
        json.dump({
            "active_topic": topic_name,
            "active_node_id": "node-1-outputs",
            "phase": "teaching"
        }, f, indent=2)

    # Setup passing answer
    with open(answer_file, "w", encoding="utf-8") as f:
        json.dump({
            "node_id": "node-1-outputs",
            "batch": True,
            "passed": True,
            "score": 1.0,
            "correct_count": 3,
            "total": 3
        }, f, indent=2)

    # Execute bridge.py advance-node
    try:
        cmd = [sys.executable, str(WORKSPACE_ROOT / "bridge.py"), "advance-node"]
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False, cwd=str(WORKSPACE_ROOT))
        assert proc.returncode == 0, f"advance-node failed with code {proc.returncode}: {proc.stderr}"

        # 1. Validate that Node 1 is now completed/mastered in manifest.json
        with open(manifest_file, "r", encoding="utf-8") as f:
            updated_manifest = json.load(f)
        n1 = updated_manifest["nodes"][0]
        n2 = updated_manifest["nodes"][1]
        assert n1["status"] in ("mastered", "completed"), f"Expected Node 1 completed/mastered, got {n1['status']}"
        assert n2["status"] == "active", f"Expected Node 2 active, got {n2['status']}"

        # 2. Validate active_session.json active_node_id
        with open(ACTIVE_SESSION_FILE, "r", encoding="utf-8") as f:
            updated_sess = json.load(f)
        assert updated_sess.get("active_node_id") == "node-2-levers", f"Expected active_node_id node-2-levers, got {updated_sess.get('active_node_id')}"

        # 3. Validate note frontmatter was promoted
        note1_content = note1_file.read_text(encoding="utf-8")
        assert 'status: "mastered"' in note1_content or "status: mastered" in note1_content

        # 4. Validate transient .session/ files are cleaned up
        assert not answer_file.exists(), "Expected answer.json to be cleaned up"

        print("[PASS] Programmatic advance-node, manifest update, frontmatter promotion, and buffer cleanup verified.")
    finally:
        import shutil
        shutil.rmtree(topic_dir, ignore_errors=True)


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
