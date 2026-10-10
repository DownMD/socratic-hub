#!/usr/bin/env python3
"""
Canonical Documentation Generator and Audit Script.
Ensures .doc/ markdown specifications remain topic-agnostic and decoupled
from active user state in state/ or notes/.
"""

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Tuple

WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
DOC_DIR = WORKSPACE_ROOT / ".doc"
STATE_DIR = WORKSPACE_ROOT / "state"
NOTES_DIR = WORKSPACE_ROOT / "notes"

# Canonical mock constants for topic-agnostic documentation schemas
DOC_MOCK_STATE = {
    "topic": "<Topic Name>",
    "phase": "idle",
    "active_node_id": "<Node ID>",
    "active_node": "<Node Title>",
    "reference_scope": {"collection": "general", "tags": []}
}

DOC_MOCK_CURRICULUM = {
    "nodes": [
        {
            "id": "<Node ID>",
            "title": "<Node Title>",
            "prerequisites": ["<Prerequisite Node ID>"],
            "status": "completed | active | pending | mastered",
            "description": "...",
            "badge_label": "Curriculum Mastered | In Progress | Active Lesson"
        }
    ]
}

DOC_MOCK_QUIZ = {
    "node_id": "<Node ID>",
    "questions": [
        {
            "id": "q1",
            "question": "Plain text with double-escaped LaTeX: \\( C_i = \\frac{m_i}{p_i} \\)",
            "options": ["A) ...", "B) ...", "C) ...", "D) ..."],
            "correct_idx": 0,
            "explanation": "..."
        }
    ]
}

DOC_MOCK_ANSWER = {
    "node_id": "<Node ID>",
    "batch": True,
    "answers": [0, 1, 2],
    "results": [
        {"question_idx": 0, "selected_idx": 0, "correct_idx": 0, "correct": True, "explanation": "..."}
    ],
    "correct_count": 3,
    "total": 3,
    "score": 1.0,
    "passed": True,
    "timestamp": "2026-10-06T00:00:00+00:00"
}

DOC_MOCK_VERIFICATION = {
    "concept": "<Node Title>",
    "status": "[VERIFIED] | [VERIFIED_WEB]",
    "source_type": "local_textbook | authoritative_canon",
    "document_title": "...",
    "page_range": "Pages 12-15 | N/A",
    "citation": "...",
    "canonical_definition": "...",
    "trade_offs_and_boundaries": "...",
    "violating_assumption": None,
    "missing_prerequisite": None,
    "misconceptions": ["...", "..."]
}

DOC_MOCK_KNOWLEDGE_GRAPH = {
    "nodes": [
        {
            "id": "<Node ID>",
            "label": "<Node Title>",
            "status": "mastered | active | planned",
            "topics": ["<Topic Name>"],
            "origin": "diagnostic | curriculum",
            "badge_label": "Baseline Knowledge | Curriculum Mastered | Active Lesson"
        }
    ],
    "edges": [
        {"source": "<Prerequisite Node ID>", "target": "<Node ID>", "relation": "prerequisite"}
    ]
}

DOC_MOCK_ROADMAP = """flowchart TD
  classDef completed stroke:#22c55e,stroke-width:2px;
  classDef active stroke:#38bdf8,stroke-width:3px;
  classDef pending stroke:#475569,stroke-width:1px;
  classDef mastered stroke:#22c55e,stroke-width:2px;

  R1["<Baseline Concept>"]:::mastered
  N1["<Node 1 Title>"]:::completed
  N2["<Node 2 Title>"]:::active
  N3["<Node 3 Title>"]:::pending

  R1 --> N1
  N1 --> N2
  N2 --> N3
"""

# Banned pattern list representing specific study state that must never leak into docs
BANNED_LEAK_PATTERNS = [
    r"\bJLPT\b",
    r"\bN5\b",
    r"\bwa-ga-case\b",
    r"\bdirectional-temporal\b",
    r"\bnode-1-core-case\b",
    r"\bnode-2-directional\b",
]


def audit_documentation() -> Tuple[bool, List[str]]:
    """Audits all .doc/*.md files to ensure zero state leakage or hardcoded study topics."""
    errors: List[str] = []
    if not DOC_DIR.exists():
        return False, [f"Documentation directory {DOC_DIR} does not exist."]

    # Check active topic from state/active_session.json if it exists and has content
    active_topic = None
    session_file = STATE_DIR / "active_session.json"
    if session_file.exists():
        try:
            sdata = json.loads(session_file.read_text(encoding="utf-8"))
            top = (sdata.get("active_topic") or sdata.get("topic") or "").strip()
            if top and top.lower() not in ("not set", "default"):
                active_topic = top
        except Exception:
            pass

    for md_file in sorted(DOC_DIR.glob("*.md")):
        content = md_file.read_text(encoding="utf-8")

        # 1. Check for banned historical leak patterns
        for pattern in BANNED_LEAK_PATTERNS:
            if re.search(pattern, content, re.IGNORECASE):
                errors.append(f"{md_file.name}: Contains banned pattern '{pattern}'")

        # 2. Check if active workspace topic leaked into docs
        if active_topic and re.search(re.escape(active_topic), content, re.IGNORECASE):
            errors.append(f"{md_file.name}: Leaked active workspace topic '{active_topic}'")

    return (len(errors) == 0), errors


def rebuild_documentation() -> bool:
    """Validates and confirms documentation suite is synchronized and clean."""
    ok, errors = audit_documentation()
    if not ok:
        print("[FAIL] Documentation contains state leaks:")
        for err in errors:
            print(f"  - {err}")
        return False

    print("[DOC REBUILD COMPLETE]")
    print("-" * 53)
    print("All documentation modules in .doc/ verified topic-agnostic:")
    for md_file in sorted(DOC_DIR.glob("*.md")):
        print(f"- .doc/{md_file.name}")
    print("-" * 53)
    return True


def main():
    parser = argparse.ArgumentParser(description="Audit and manage topic-agnostic .doc/ suite.")
    parser.add_argument("--check", action="store_true", help="Audit documentation for state leaks")
    parser.add_argument("--rebuild", action="store_true", help="Rebuild and verify documentation")
    args = parser.parse_args()

    if args.rebuild:
        success = rebuild_documentation()
    else:
        success, errors = audit_documentation()
        if success:
            print("[PASS] All .doc/ specifications are clean, topic-agnostic, and decoupled from state.")
        else:
            print("[FAIL] Documentation audit found state leakage:")
            for err in errors:
                print(f"  - {err}")

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
