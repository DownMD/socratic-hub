#!/usr/bin/env python3
"""
Unit Test Suite for Canonical Documentation Generator & Decoupled State Schemas.
Verifies that documentation generator logic and .doc/ files never leak active study state.
"""

import sys
import unittest
from pathlib import Path

WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(WORKSPACE_ROOT))

from scripts.generate_docs import (
    DOC_MOCK_STATE,
    DOC_MOCK_CURRICULUM,
    DOC_MOCK_QUIZ,
    DOC_MOCK_KNOWLEDGE_GRAPH,
    audit_documentation,
    rebuild_documentation,
)


class TestDocGenerator(unittest.TestCase):
    def test_doc_mock_state_schema(self):
        """Verify that DOC_MOCK_STATE uses topic-agnostic placeholders."""
        self.assertEqual(DOC_MOCK_STATE["topic"], "<Topic Name>")
        self.assertEqual(DOC_MOCK_STATE["phase"], "idle")
        self.assertEqual(DOC_MOCK_STATE["active_node_id"], "<Node ID>")
        self.assertEqual(DOC_MOCK_STATE["active_node"], "<Node Title>")
        self.assertIn("collection", DOC_MOCK_STATE["reference_scope"])

    def test_no_state_leakage_in_doc_suite(self):
        """Verify that all markdown files in .doc/ pass the topic-agnostic audit."""
        ok, errors = audit_documentation()
        self.assertTrue(ok, f"State leakage detected in .doc/: {errors}")

    def test_maintenance_excludes_state_and_notes(self):
        """Verify that .doc/maintenance.md explicitly excludes state/ and notes/."""
        maintenance_md = (WORKSPACE_ROOT / ".doc" / "maintenance.md").read_text(encoding="utf-8")
        self.assertIn("- `state/`", maintenance_md)
        self.assertIn("- `notes/`", maintenance_md)
        self.assertIn("DOC_MOCK_STATE", maintenance_md)

    def test_rebuild_documentation_success(self):
        """Verify that rebuild_documentation runs cleanly."""
        self.assertTrue(rebuild_documentation())


def main():
    suite = unittest.TestLoader().loadTestsFromTestCase(TestDocGenerator)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    if not result.wasSuccessful():
        sys.exit(1)


if __name__ == "__main__":
    main()
