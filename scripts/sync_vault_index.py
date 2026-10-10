#!/usr/bin/env python3
"""
Vault Knowledge Indexer Engine.
Recursively indexes completed notes in notes/ and extracts frontmatter metadata
into notes/index.json for fast, zero-dependency prior knowledge scanning.
Adheres strictly to zero-emoji typography, file-backed IPC standards,
standard library execution, and atomic file writes.
"""

import sys
import os
import re
import json
import argparse
from pathlib import Path
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple


def get_workspace_root(workspace_arg: Optional[str] = None) -> Path:
    """Resolves workspace root directory safely."""
    if workspace_arg:
        return Path(workspace_arg).resolve()
    return Path(__file__).resolve().parent.parent


def atomic_write_json(file_path: Path, data: Any) -> None:
    """Atomically writes JSON payload using temporary file and atomic replace."""
    file_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = file_path.with_name(f"{file_path.name}.tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    tmp_path.replace(file_path)


def parse_frontmatter(content: str) -> Tuple[Optional[Dict[str, Any]], str]:
    """
    Extracts frontmatter between leading '---' fences and returns (metadata_dict, body_text).
    Returns (None, content) if no valid frontmatter is found.
    """
    match = re.search(r'^---\s*\n(.*?)\n---', content, re.DOTALL)
    if not match:
        return None, content

    yaml_text = match.group(1)
    body = content[match.end():].strip()
    data: Dict[str, Any] = {}
    current_key: Optional[str] = None

    for line in yaml_text.splitlines():
        raw_line = line.rstrip()
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        # Check list item under current_key (e.g. "  - item" or "- item")
        list_match = re.match(r'^\s*-\s+(.*)$', raw_line)
        if list_match and current_key:
            val = list_match.group(1).strip()
            if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
                val = val[1:-1]
            if not isinstance(data.get(current_key), list):
                data[current_key] = []
            data[current_key].append(val)
            continue

        # Check key: value
        kv_match = re.match(r'^([a-zA-Z0-9_\-]+)\s*:\s*(.*)$', raw_line)
        if kv_match:
            key = kv_match.group(1).strip()
            raw_val = kv_match.group(2).strip()
            current_key = key

            if not raw_val:
                data[key] = []
                continue

            # Inline list: [a, b, c]
            if raw_val.startswith('[') and raw_val.endswith(']'):
                items = []
                for x in raw_val[1:-1].split(','):
                    x_clean = x.strip()
                    if (x_clean.startswith('"') and x_clean.endswith('"')) or (x_clean.startswith("'") and x_clean.endswith("'")):
                        x_clean = x_clean[1:-1]
                    if x_clean:
                        items.append(x_clean)
                data[key] = items
            else:
                # String value
                val = raw_val
                if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
                    val = val[1:-1]
                data[key] = val
        else:
            # Continuation line or unparsed syntax
            continue

    # Post-process list fields that might have been provided as comma-separated string
    for list_key in ["aliases", "prerequisites", "unlocks", "tags"]:
        if list_key in data and isinstance(data[list_key], str):
            val_str = data[list_key]
            if val_str:
                data[list_key] = [
                    x.strip().strip('"').strip("'")
                    for x in val_str.split(',')
                    if x.strip()
                ]
            else:
                data[list_key] = []

    return data, body


def extract_fallback_core_mechanism(body: str) -> str:
    """Extracts a one-sentence conceptual summary from markdown body if frontmatter lacks core_mechanism."""
    for pattern in [
        r'###\s*(?:\d+[\.\)]\s*)?Core\s*Mechanisms?.*?\n+(.*?)(?:\n\n|\n#|$)',
        r'###\s*(?:\d+[\.\)]\s*)?Core\s*Concepts?.*?\n+(.*?)(?:\n\n|\n#|$)',
        r'###\s*(?:\d+[\.\)]\s*)?The\s*Communicative\s*Job.*?\n+(.*?)(?:\n\n|\n#|$)',
        r'###\s*(?:\d+[\.\)]\s*)?Sentence\s*Pattern\s*&\s*Structure.*?\n+(.*?)(?:\n\n|\n#|$)',
        r'###\s*(?:\d+[\.\)]\s*)?The\s*Objective.*?\n+(.*?)(?:\n\n|\n#|$)',
        r'###\s*(?:\d+[\.\)]\s*)?The\s*Core\s*Strategic\s*Friction.*?\n+(.*?)(?:\n\n|\n#|$)',
        r'###\s*(?:\d+[\.\)]\s*)?The\s*Core\s*Dilemma\s*/\s*Driving\s*Question.*?\n+(.*?)(?:\n\n|\n#|$)',
        r'###\s*(?:\d+[\.\)]\s*)?Motivation.*?\n+(.*?)(?:\n\n|\n#|$)',
        r'###\s*(?:\d+[\.\)]\s*)?Prerequisite Foundation.*?\n+(.*?)(?:\n\n|\n#|$)',
    ]:
        m = re.search(pattern, body, re.IGNORECASE | re.DOTALL)
        if m:
            text = m.group(1).strip()
            lines = [l.strip() for l in text.splitlines() if l.strip() and not l.strip().startswith('>') and not l.strip().startswith('#')]
            for line in lines:
                line = re.sub(r'^[*\-+\d\.]+\s*', '', line)
                line = re.sub(r'\[\[(.*?)\]\]', r'\1', line)
                line = re.sub(r'[*_`$]', '', line).strip()
                if len(line) > 20:
                    first_sent = re.split(r'(?<=[.!?])\s+', line)[0]
                    return first_sent.strip()
    return ""


def parse_note_file(note_path: Path, workspace_root: Path) -> Optional[Dict[str, Any]]:
    """Parses a markdown note and extracts indexed concept representation."""
    try:
        with open(note_path, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception as e:
        sys.stderr.write(f"[STANDBY] Warning: Failed to read note {note_path}: {e}\n")
        return None

    frontmatter, body = parse_frontmatter(content)
    if not frontmatter:
        return None

    # Operational Guard 1: Filter strictly for completed/mastered notes, skip in_progress active notes
    status = str(frontmatter.get("status") or "").lower().strip()
    if status == "in_progress":
        return None

    note_id = str(frontmatter.get("id") or note_path.stem).strip()
    if not note_id:
        return None

    # Derive topic
    topic = str(frontmatter.get("topic") or "").strip()
    if not topic:
        parent_name = note_path.parent.name
        topic = parent_name if parent_name != "notes" else "general"

    # Derive domain (default to topic name if absent)
    domain = str(frontmatter.get("domain") or "").strip()
    if not domain:
        domain = topic

    # Derive title
    title = str(frontmatter.get("title") or "").strip()
    if not title:
        title_match = re.search(r'^#\s+(.+)$', body, re.MULTILINE)
        if title_match:
            title = title_match.group(1).strip()
        else:
            title = note_id.replace('-', ' ').replace('_', ' ').title()

    # Aliases
    aliases = frontmatter.get("aliases", [])
    if isinstance(aliases, list):
        aliases = [str(a).strip() for a in aliases if str(a).strip()]
    elif isinstance(aliases, str):
        aliases = [x.strip() for x in aliases.split(',') if x.strip()]
    else:
        aliases = []

    # Core mechanism
    core_mechanism = str(frontmatter.get("core_mechanism") or "").strip()
    if not core_mechanism:
        core_mechanism = extract_fallback_core_mechanism(body)

    # Citation & verification status
    citation = str(frontmatter.get("citation") or "").strip()
    verification_status = str(frontmatter.get("verification_status") or "[VERIFIED]").strip()

    # Prerequisites
    prerequisites = frontmatter.get("prerequisites", [])
    if isinstance(prerequisites, list):
        prerequisites = [str(p).strip() for p in prerequisites if str(p).strip()]
    elif isinstance(prerequisites, str):
        prerequisites = [x.strip() for x in prerequisites.split(',') if x.strip()]
    else:
        prerequisites = []

    # Path relative to workspace with forward slashes
    try:
        rel_path = os.path.relpath(note_path.resolve(), workspace_root.resolve()).replace("\\", "/")
    except Exception:
        rel_path = note_path.as_posix()

    return {
        "id": note_id,
        "title": title,
        "topic": topic,
        "domain": domain,
        "path": rel_path,
        "aliases": aliases,
        "core_mechanism": core_mechanism,
        "citation": citation,
        "verification_status": verification_status,
        "prerequisites": prerequisites,
    }


def is_excluded_file(file_path: Path) -> bool:
    """Checks whether a markdown file should be excluded from concept indexing."""
    name_lower = file_path.name.lower()
    if name_lower in ("index.md", "readme.md", "notes.md", "lesson_notes.md"):
        return True
    if name_lower.endswith(".tmp") or name_lower.endswith(".tmp.md"):
        return True
    return False


def build_alias_map(concepts: Dict[str, Dict[str, Any]]) -> Dict[str, str]:
    """Assembles an inverted alias_map mapping lowercased aliases to canonical note IDs."""
    alias_map: Dict[str, str] = {}
    for cid, cdata in concepts.items():
        for alias in cdata.get("aliases", []):
            cleaned = alias.strip().lower()
            if cleaned:
                alias_map[cleaned] = cid
    return alias_map


def sync_vault(workspace_root: Path, rebuild: bool = True, note_arg: Optional[str] = None) -> None:
    """Indexes notes into notes/index.json and writes stdout summary."""
    notes_dir = workspace_root / "notes"
    index_file = notes_dir / "index.json"

    concepts: Dict[str, Dict[str, Any]] = {}

    if not rebuild and note_arg:
        # Incremental note sync
        if index_file.exists():
            try:
                with open(index_file, "r", encoding="utf-8") as f:
                    existing_data = json.load(f)
                    concepts = existing_data.get("concepts", {})
            except Exception as e:
                sys.stderr.write(f"[STANDBY] Warning: Failed to parse existing index.json: {e}\n")
                concepts = {}

        target_note_path = Path(note_arg)
        if not target_note_path.is_absolute():
            target_note_path = workspace_root / target_note_path

        if target_note_path.exists() and not is_excluded_file(target_note_path):
            parsed = parse_note_file(target_note_path, workspace_root)
            if parsed:
                concepts[parsed["id"]] = parsed
        else:
            # File deleted or excluded, remove if present
            try:
                target_rel = os.path.relpath(target_note_path.resolve(), workspace_root.resolve()).replace("\\", "/")
            except Exception:
                target_rel = target_note_path.as_posix()
            concepts = {cid: c for cid, c in concepts.items() if c.get("path") != target_rel}

    else:
        # Full vault rebuild
        if notes_dir.exists():
            for md_file in notes_dir.rglob("*.md"):
                if is_excluded_file(md_file):
                    continue
                parsed = parse_note_file(md_file, workspace_root)
                if parsed:
                    concepts[parsed["id"]] = parsed

    alias_map = build_alias_map(concepts)
    now_iso = datetime.now(timezone.utc).isoformat()

    output_payload = {
        "total_notes": len(concepts),
        "last_updated": now_iso,
        "alias_map": alias_map,
        "concepts": concepts,
    }

    atomic_write_json(index_file, output_payload)

    result = {
        "status": "[INDEX]",
        "indexed_notes": len(concepts),
        "total_aliases": len(alias_map),
    }
    print(json.dumps(result, ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser(description="Vault Knowledge Indexer")
    parser.add_argument("--rebuild", action="store_true", help="Rebuild full vault index")
    parser.add_argument("--note", type=str, default=None, help="Incremental note path to sync")
    parser.add_argument("--workspace-dir", type=str, default=None, help="Workspace root directory")

    args = parser.parse_args()
    workspace_root = get_workspace_root(args.workspace_dir)

    is_rebuild = args.rebuild or (not args.note)
    sync_vault(workspace_root=workspace_root, rebuild=is_rebuild, note_arg=args.note)


if __name__ == "__main__":
    main()
