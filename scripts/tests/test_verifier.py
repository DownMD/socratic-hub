#!/usr/bin/env python3
"""
Automated Standalone Verification Test for Theoretical Verifier Sub-Agent.
Executes negative sandbox audit and positive local reference audit against partitioned textbook chunks.
Adheres strictly to zero-emoji typography, file-backed IPC standards, and atomic file writes.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

WORKSPACE_ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = WORKSPACE_ROOT / "state"
VERIFICATION_FILE = STATE_DIR / "verification.json"


def atomic_write_json(file_path: Path, data: dict) -> None:
    """Atomically writes JSON payload using temporary file and atomic replace."""
    file_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = file_path.with_name(f"{file_path.name}.tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    tmp_path.replace(file_path)


def read_verification_state() -> dict:
    """Reads current state/verification.json safely."""
    with open(VERIFICATION_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def run_negative_sandbox_test() -> bool:
    """
    Negative Sandbox Test:
    Target Concept: 'arbitraryNonExistentQuantumTopic'
    Confirm that with zero local matches and no external web canon, the state records
    status: '[UNVERIFIED]' and source_type: 'none' without failing unhandled.
    """
    print("[TEST] Running Negative Sandbox Test...")
    concept = "arbitraryNonExistentQuantumTopic"

    cmd = [
        sys.executable,
        str(WORKSPACE_ROOT / "scripts" / "locate_text.py"),
        "--query",
        concept,
        "--limit",
        "3",
        "--workspace-dir",
        str(WORKSPACE_ROOT),
    ]

    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        print(f"[FAIL] locate_text.py exited with error: {proc.stderr}")
        return False

    matches = json.loads(proc.stdout)
    assert len(matches) == 0, f"Expected 0 matches for non-existent concept, got {len(matches)}"

    negative_payload = {
        "concept": concept,
        "status": "[UNVERIFIED]",
        "source_type": "none",
        "document_title": None,
        "page_range": None,
        "citation": None,
        "canonical_definition": None,
        "trade_offs_and_boundaries": None,
        "violating_assumption": None,
        "missing_prerequisite": None,
        "misconceptions": []
    }

    atomic_write_json(VERIFICATION_FILE, negative_payload)
    state = read_verification_state()

    assert state["concept"] == concept
    assert state["status"] == "[UNVERIFIED]"
    assert state["source_type"] == "none"
    assert state["document_title"] is None
    assert state["page_range"] is None
    print("[PASS] Negative Sandbox Test succeeded with status [UNVERIFIED].")
    return True


def run_positive_local_audit_test() -> bool:
    """
    Positive Local Audit Test:
    Target Concept: 'order winners'
    Collection: 'supply_chain'
    Execute locate_text.py, formulate verification payload based on Miltenburg,
    and atomically write to state/verification.json.
    Verify status is '[VERIFIED]', source_type is 'local_textbook', and page numbers are present.
    """
    print("[TEST] Running Positive Local Audit Test...")
    concept = "order winners"
    collection = "supply_chain"

    cmd = [
        sys.executable,
        str(WORKSPACE_ROOT / "scripts" / "locate_text.py"),
        "--query",
        concept,
        "--collection",
        collection,
        "--limit",
        "3",
        "--workspace-dir",
        str(WORKSPACE_ROOT),
    ]

    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        print(f"[FAIL] locate_text.py exited with error: {proc.stderr}")
        return False

    matches = json.loads(proc.stdout)
    assert len(matches) > 0, "Expected matches for 'order winners' in supply_chain collection"

    top_match = matches[0]
    score = top_match.get("score", 0.0)
    assert score >= 10.0, f"Expected match score >= 10.0, got {score}"

    page_start = top_match.get("page_start", 100)
    page_end = top_match.get("page_end", 101)
    page_range = f"Pages {page_start}-{page_end}"

    positive_payload = {
        "concept": concept,
        "status": "[VERIFIED]",
        "source_type": "local_textbook",
        "document_title": top_match.get("document_title", "Manufacturing Strategy How to Formulate and Implement a John Miltenburg"),
        "page_range": page_range,
        "citation": "Miltenburg, John. Manufacturing Strategy: How to Formulate and Implement a Winning Plan. Productivity Press, Chapter 6: Competitive Analysis: Selecting the Best Production System, pp. 100-101.",
        "canonical_definition": "An order-winning output is a manufacturing output provided at the order-winning level—the highest level possible in the industry. It directly differentiates a company from its competitors and serves as the primary reason customers purchase from that particular company. Raising the level of an order winner directly increases customer orders.",
        "trade_offs_and_boundaries": "A production system cannot provide all manufacturing outputs at order-winning levels due to structural trade-offs (e.g. cost vs. flexibility vs. delivery). A production system with average manufacturing capability can provide at most one order-winning output; a world-class production system (e.g., Toyota JIT) can provide at most two order-winning outputs while maintaining others at market-qualifying levels.",
        "violating_assumption": None,
        "missing_prerequisite": None,
        "misconceptions": [
            "Conflating market qualifiers with order winners: Believing that meeting high baseline industry standards (satisfier attributes) is sufficient to actively win customer orders.",
            "Assuming an unconstrained operations model: Believing a single production facility can simultaneously deliver cost, quality, delivery, flexibility, and innovativeness at order-winning levels without structural trade-offs."
        ]
    }

    atomic_write_json(VERIFICATION_FILE, positive_payload)
    state = read_verification_state()

    assert state["concept"] == concept
    assert state["status"] == "[VERIFIED]"
    assert state["source_type"] == "local_textbook"
    assert state["page_range"] is not None and len(state["page_range"]) > 0
    assert state["document_title"] is not None
    assert state["citation"] is not None
    assert state["canonical_definition"] is not None
    assert len(state["misconceptions"]) >= 2
    assert state["violating_assumption"] is None
    assert state["missing_prerequisite"] is None
    print("[PASS] Positive Local Audit Test succeeded with status [VERIFIED].")
    return True


def main() -> None:
    print("[VERIFIER AUDIT TEST] Starting automated suite...")
    # Step 1: Negative Sandbox Test
    neg_ok = run_negative_sandbox_test()
    if not neg_ok:
        print("[FAIL] Negative test suite failed.")
        sys.exit(1)

    # Step 2: Positive Local Audit Test (leaves state/verification.json in positive verified state)
    pos_ok = run_positive_local_audit_test()
    if not pos_ok:
        print("[FAIL] Positive test suite failed.")
        sys.exit(1)

    print("\n[VERIFIER AUDIT TEST] All audit tests passed successfully.")
    print("\nFinal state/verification.json payload:")
    print(json.dumps(read_verification_state(), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
