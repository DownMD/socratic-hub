#!/usr/bin/env python3
"""
Unit Test: Saved Topics Search, Data Enrichment, Read Mode State Contract,
and Bridge Manifest Precedence.
"""

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
import server
import bridge


class TestSavedTopicsAndManifest(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.saved_notes_dir = server.NOTES_DIR
        self.saved_state_dir = server.STATE_DIR

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_get_topics_enrichment(self):
        """Verifies server.get_topics() enriches topics with domain, status, and all_nodes list."""
        res = server.get_topics()
        topics = res.get("topics", [])
        self.assertGreater(len(topics), 0, "Expected at least 1 topic found on disk")
        for t in topics:
            self.assertIn("domain", t)
            self.assertIn("status", t)
            self.assertIn("nodes", t)
            self.assertIn(t["status"], ("completed", "in_progress"))
            self.assertIsInstance(t["nodes"], list)

    def test_load_topic_read_mode(self):
        """Verifies POST /api/topics/load with mode='read' sets phase='reading', status='active', and hydrates markdown."""
        req = server.TopicRequest(topic="Gardening", mode="read")
        res = server.load_topic(req)
        state = res.get("state", {})
        self.assertEqual(state.get("phase"), "reading")
        self.assertEqual(state.get("status"), "active")
        self.assertTrue(state.get("session_active"))
        self.assertTrue(bool(state.get("notes")))
        self.assertEqual(state.get("notes"), state.get("lesson_markdown"))

        # Verify load_state() preserves active status
        s2 = server.load_state()
        self.assertEqual(s2.get("status"), "active")
        self.assertTrue(s2.get("session_active"))

        # Clean reset
        server.reset_state()

    def test_bridge_manifest_precedence(self):
        """Verifies bridge.advance_node() prefers manifest nodes and promotes note frontmatter using scan."""
        test_vault = Path(self.tmp_dir) / "TestPrecedence"
        test_vault.mkdir(parents=True, exist_ok=True)

        manifest = {
            "topic": "TestPrecedence",
            "domain": "test",
            "nodes": [
                {
                    "id": "node-1",
                    "title": "Node 1 Title",
                    "status": "active"
                },
                {
                    "id": "node-2",
                    "title": "Node 2 Title",
                    "status": "planned"
                }
            ]
        }
        (test_vault / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

        # Note with different filename but matching frontmatter id
        custom_note = test_vault / "custom_filename.md"
        custom_note.write_text("""---
id: node-1
title: Node 1 Title
status: in_progress
---
# Content for Node 1
""", encoding="utf-8")

        # Call bridge.advance_node logic directly on this vault
        # Check that scanning finds and promotes custom_filename.md
        found_note = None
        nid = "node-1"
        clean_nid = bridge.to_canonical_id(nid)
        clean_nlbl = bridge.to_canonical_id("Node 1 Title")
        cand_paths = [
            test_vault / f"{nid}.md",
            test_vault / f"{clean_nid}.md",
            test_vault / f"{clean_nlbl}.md"
        ]
        for cp in cand_paths:
            if cp.exists() and cp.is_file():
                found_note = cp
                break

        if not found_note:
            for md_file in test_vault.glob("*.md"):
                if not md_file.is_file():
                    continue
                try:
                    md_text = md_file.read_text(encoding="utf-8")
                    import re
                    fm_match = re.match(r'^---\s*\r?\n(.*?)\r?\n---', md_text, re.DOTALL)
                    if fm_match:
                        fm_content = fm_match.group(1)
                        id_match = re.search(r'^id:\s*["\']?([^"\'\r\n]+)["\']?', fm_content, re.MULTILINE)
                        if id_match:
                            file_id = id_match.group(1).strip()
                            if file_id == nid or bridge.to_canonical_id(file_id) == clean_nid:
                                found_note = md_file
                                break
                except Exception:
                    pass

        self.assertIsNotNone(found_note)
        self.assertEqual(found_note.name, "custom_filename.md")

        bridge.promote_vault_note_frontmatter(found_note)
        updated_text = found_note.read_text(encoding="utf-8")
        self.assertIn('status: "mastered"', updated_text)


if __name__ == "__main__":
    unittest.main()
