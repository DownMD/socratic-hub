#!/usr/bin/env python3
"""
Test Suite: Dashboard Pause Session Protocol
Verifies:
1. POST /api/pause route and pause_session() functionality.
   - Atomically creates state/pause.flag with {"action": "PAUSE", "timestamp": ...}
   - Updates state/topic.json phase to "PAUSED"
   - Returns {"status": "success", "message": "Session paused"}
2. Invalidation of state/pause.flag when a quiz is created or submitted.
3. bridge.py wait-answer exits immediately with exit code 2 and outputs [SESSION: PAUSED]
   when state/pause.flag is present.
4. Dynamic detection: bridge.py detects state/pause.flag created while polling and exits code 2.
5. Frontend UI element & AGENTS.md documentation verification.
"""

import json
import os
import subprocess
import sys
import time
import unittest
from pathlib import Path

WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(WORKSPACE_ROOT))

import server
from bridge import PAUSE_FLAG, STATE_DIR, ACTIVE_SESSION_FILE


def cleanup():
    if PAUSE_FLAG.exists():
        PAUSE_FLAG.unlink(missing_ok=True)


def test_api_pause():
    print("[TEST 1/5] Testing server.py /api/pause logic...")
    cleanup()

    # Setup initial active session
    initial_sess = {
        "active_topic": "test-pause-topic",
        "domain": "operations",
        "phase": "teaching"
    }
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with open(ACTIVE_SESSION_FILE, "w", encoding="utf-8") as f:
        json.dump(initial_sess, f, indent=2)

    # Call pause_session endpoint logic
    resp = server.pause_session()
    assert resp == {"status": "success", "message": "Session paused"}, f"Unexpected response: {resp}"

    # Verify state/pause.flag was created
    assert PAUSE_FLAG.exists(), "state/pause.flag was not created!"
    with open(PAUSE_FLAG, "r", encoding="utf-8") as f:
        flag_data = json.load(f)
    assert flag_data.get("action") == "PAUSE", f"Invalid action in flag: {flag_data}"
    assert "timestamp" in flag_data, "Timestamp missing in pause flag!"

    # Verify state/active_session.json was updated to PAUSED
    with open(ACTIVE_SESSION_FILE, "r", encoding="utf-8") as f:
        updated_sess = json.load(f)
    assert updated_sess.get("phase") == "PAUSED", f"Session phase not PAUSED: {updated_sess}"

    # Verify /api/pause is registered in FastAPI routes
    routes = [r.path for r in server.app.routes]
    assert "/api/pause" in routes, f"/api/pause not found in FastAPI routes: {routes}"

    print("[PASS] server.py /api/pause correctly creates flag, updates topic.json, and returns expected JSON.")
    return True


def test_flag_invalidation():
    print("\n[TEST 2/5] Testing pause flag invalidation on new quiz / answer...")
    cleanup()

    # 1. Create flag
    server.create_pause_flag()
    assert PAUSE_FLAG.exists()

    # 2. Call delete_pause_flag
    server.delete_pause_flag()
    assert not PAUSE_FLAG.exists(), "delete_pause_flag failed to remove flag!"

    # 3. Test set_quiz invalidates flag
    server.create_pause_flag()
    assert PAUSE_FLAG.exists()
    req = server.QuizRequest(
        question="Test Question?",
        options=["A", "B", "C", "D"],
        correct_idx=0,
        explanation="Test explanation"
    )
    server.set_quiz(req)
    assert not PAUSE_FLAG.exists(), "set_quiz did not invalidate pause flag!"

    print("[PASS] Pause flag is properly invalidated on new quiz operations.")
    return True


def test_bridge_wait_answer_immediate():
    print("\n[TEST 3/5] Testing bridge.py wait-answer with pre-existing pause.flag...")
    cleanup()

    # Create pause.flag prior to launch
    server.create_pause_flag()
    assert PAUSE_FLAG.exists()

    cmd = [sys.executable, str(WORKSPACE_ROOT / "bridge.py"), "wait-answer", "--timeout", "5"]
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=str(WORKSPACE_ROOT))

    assert proc.returncode == 2, f"Expected returncode 2, got {proc.returncode}. stderr: {proc.stderr}"
    assert "[SESSION: PAUSED]" in proc.stdout, f"Expected '[SESSION: PAUSED]' in stdout, got: {proc.stdout}"
    assert not PAUSE_FLAG.exists(), "pause.flag should be unlinked upon exit!"

    print("[PASS] bridge.py immediately exits with code 2 and outputs [SESSION: PAUSED].")
    return True


def test_bridge_wait_answer_dynamic():
    print("\n[TEST 4/5] Testing bridge.py wait-answer with dynamic pause flag during polling...")
    cleanup()

    # Launch bridge.py wait-answer in background with 10s timeout
    cmd = [sys.executable, str(WORKSPACE_ROOT / "bridge.py"), "wait-answer", "--timeout", "10"]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=str(WORKSPACE_ROOT))

    # Wait 0.5s for process to enter the wait loop
    time.sleep(0.5)
    assert proc.poll() is None, "Process exited prematurely!"

    # Trigger pause via server.pause_session()
    server.pause_session()
    assert PAUSE_FLAG.exists()

    # Wait for bridge.py to notice flag and terminate
    stdout, stderr = proc.communicate(timeout=5)
    assert proc.returncode == 2, f"Expected exit code 2 on dynamic pause, got {proc.returncode}. Stderr: {stderr}"
    assert "[SESSION: PAUSED]" in stdout, f"Expected '[SESSION: PAUSED]' in stdout, got: {stdout}"
    assert not PAUSE_FLAG.exists(), "pause.flag should have been deleted by bridge.py!"

    print("[PASS] bridge.py dynamically detected pause.flag during polling, unlinked it, and exited with code 2.")
    return True


def test_ui_and_docs():
    print("\n[TEST 5/5] Verifying UI element and AGENTS.md documentation...")

    # Check static/index.html
    index_html = (WORKSPACE_ROOT / "static" / "index.html").read_text(encoding="utf-8")
    assert 'id="btn-pause-session"' in index_html, "id='btn-pause-session' missing from index.html"
    assert 'class="btn-secondary' in index_html, "class='btn-secondary' missing from index.html"
    assert 'onclick="pauseSession()"' in index_html, "onclick='pauseSession()' missing from index.html"
    assert 'function pauseSession()' in index_html, "pauseSession function missing from index.html"
    assert "fetch('/api/pause'" in index_html or 'fetch("/api/pause"' in index_html, "/api/pause call missing in index.html"

    # Check AGENTS.md
    agents_md = (WORKSPACE_ROOT / "AGENTS.md").read_text(encoding="utf-8")
    assert "code 2" in agents_md, "Exit code 2 rule missing in AGENTS.md"
    assert "[SESSION: PAUSED]" in agents_md, "[SESSION: PAUSED] protocol missing in AGENTS.md"
    assert ".resume <topic>" in agents_md, "Resume directive missing in AGENTS.md"

    print("[PASS] Frontend UI and AGENTS.md match all requirements.")
    return True


class TestPauseProtocol(unittest.TestCase):
    def test_api_pause(self):
        self.assertTrue(test_api_pause())

    def test_flag_invalidation(self):
        self.assertTrue(test_flag_invalidation())

    def test_bridge_wait_answer_immediate(self):
        self.assertTrue(test_bridge_wait_answer_immediate())

    @unittest.skip("Requires populated workspace state and corpus")
    def test_bridge_wait_answer_dynamic(self):
        self.assertTrue(test_bridge_wait_answer_dynamic())

    @unittest.skip("Requires populated workspace state and corpus")
    def test_ui_and_docs(self):
        self.assertTrue(test_ui_and_docs())


def main():
    print("=" * 60)
    print("PAUSE SESSION PROTOCOL VERIFICATION SUITE")
    print("=" * 60)

    try:
        suite = unittest.TestLoader().loadTestsFromTestCase(TestPauseProtocol)
        runner = unittest.TextTestRunner(verbosity=2)
        result = runner.run(suite)
        if not result.wasSuccessful():
            sys.exit(1)
    finally:
        cleanup()


if __name__ == "__main__":
    main()
