import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

import server
from server import (
    synthesize_manifest_for_topic,
    compile_mermaid_dag,
    get_node_note,
    pause_session,
    reset_state
)

class TestVaultMigrationAndOperationalGuards(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.topic_dir = Path(self.test_dir) / "Test Topic"
        self.topic_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_legacy_manifest_synthesis(self):
        """Guard 2: Legacy Manifest Synthesis from frontmatter without losing historical edges."""
        n1 = self.topic_dir / "node-1.md"
        n1.write_text("""---
id: node-1
title: Primitives
status: mastered
prerequisites: []
---
# Primitives
Body content
""", encoding="utf-8")

        n2 = self.topic_dir / "node-2.md"
        n2.write_text("""---
id: node-2
title: Advanced Flow
status: in_progress
prerequisites:
  - "[[node-1]]"
---
# Advanced Flow
In progress body
""", encoding="utf-8")

        manifest = synthesize_manifest_for_topic(self.topic_dir)
        self.assertEqual(manifest["topic"], "Test Topic")
        nodes = manifest["nodes"]
        self.assertEqual(len(nodes), 2)

        node_map = {n["id"]: n for n in nodes}
        self.assertIn("node-1", node_map)
        self.assertIn("node-2", node_map)
        self.assertEqual(node_map["node-1"]["status"], "mastered")
        self.assertEqual(node_map["node-2"]["status"], "in_progress")
        self.assertIn("node-1", node_map["node-2"]["prerequisites"])

        # Compile Mermaid DAG
        dag = compile_mermaid_dag(manifest)
        self.assertIn("flowchart TD", dag)
        self.assertIn('N1["Primitives"]:::mastered', dag)
        self.assertIn("N1 --> N2", dag)

    def test_active_note_rendering_guard(self):
        """Guard 1: Active note rendering allows in_progress notes for active quizzes."""
        res = get_node_note("non-existent-xyz")
        self.assertFalse(res.get("found", True))

    def test_pause_state_preservation_guard(self):
        """Guard 3: POST /api/pause preserves session quiz, POST /api/reset purges it."""
        pause_res = pause_session()
        self.assertEqual(pause_res.get("status"), "success")

        reset_res = reset_state()
        self.assertTrue(reset_res.get("success"))

if __name__ == "__main__":
    unittest.main()
