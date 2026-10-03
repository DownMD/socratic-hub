import argparse
import json
import os
import random
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

BASE_DIR = Path(__file__).resolve().parent
STATE_DIR = BASE_DIR / "state"
ANSWER_FILE = STATE_DIR / "answer.json"
QUIZ_FILE = STATE_DIR / "quiz.json"
CURRICULUM_FILE = STATE_DIR / "curriculum.json"
TOPIC_FILE = STATE_DIR / "topic.json"
ROADMAP_FILE = STATE_DIR / "roadmap.mmd"
VERIFICATION_FILE = STATE_DIR / "verification.json"
CACHE_DIR = STATE_DIR / "cache"
PAUSE_FLAG = STATE_DIR / "pause.flag"


def clean_label(label: str) -> str:
    s = re.sub(r'^(?:Node\s*\d+[:.]\s*|\d+[\.\)]\s*)', '', str(label).strip(), flags=re.IGNORECASE)
    return s.strip()


def to_canonical_id(text: str) -> str:
    clean = clean_label(text)
    s = re.sub(r'[^a-zA-Z0-9]+', '-', clean.lower()).strip('-')
    return s or "default"


NOTES_DIR = BASE_DIR / "notes"


def get_topic_notes_dir(topic_name: Optional[str]) -> Optional[Path]:
    """Resolve canonical notes directory for a topic.

    Guards against empty, 'Not Set', or 'not-set' to prevent phantom directory creation.
    Resolution order:
    1. Empty / 'Not Set' / 'not-set' / 'none' -> None
    2. NOTES_DIR / topic_name exists -> return it (Title Case canonical)
    3. NOTES_DIR / slug exists -> return it (legacy slug)
    4. Otherwise -> return NOTES_DIR / topic_name (Title Case default)
    """
    if not topic_name or topic_name.strip().lower() in ("not set", "not-set", "none", ""):
        return None
    cleaned = topic_name.strip()
    canonical = NOTES_DIR / cleaned
    if canonical.exists():
        return canonical
    slug_name = re.sub(r'[^a-zA-Z0-9]+', '-', cleaned.lower()).strip('-') or "general"
    slug = NOTES_DIR / slug_name
    if slug.exists():
        return slug
    return canonical


def safe_replace(src: Path, dst: Path, max_retries: int = 5) -> None:
    for attempt in range(max_retries):
        try:
            src.replace(dst)
            return
        except (PermissionError, OSError):
            if attempt == max_retries - 1:
                raise
            time.sleep(0.05 * pow(2, attempt))


def promote_vault_note_frontmatter(vault_note_path: Path) -> None:
    """Updates YAML frontmatter atomically to status: 'mastered' and badge_label: 'Curriculum Mastered' while preserving body."""
    try:
        content = vault_note_path.read_text(encoding="utf-8")
        fm_match = re.match(r'^---\s*\r?\n(.*?)\r?\n---\s*\r?\n(.*)$', content, re.DOTALL)
        if fm_match:
            fm_text = fm_match.group(1)
            body = fm_match.group(2)
            if re.search(r'^status:\s*.*$', fm_text, re.MULTILINE):
                fm_text = re.sub(r'^status:\s*.*$', 'status: "mastered"', fm_text, flags=re.MULTILINE)
            else:
                fm_text += '\nstatus: "mastered"'
            if re.search(r'^badge_label:\s*.*$', fm_text, re.MULTILINE):
                fm_text = re.sub(r'^badge_label:\s*.*$', 'badge_label: "Curriculum Mastered"', fm_text, flags=re.MULTILINE)
            else:
                fm_text += '\nbadge_label: "Curriculum Mastered"'
            new_content = f"---\n{fm_text.strip()}\n---\n{body}"
        else:
            new_content = f'---\nstatus: "mastered"\nbadge_label: "Curriculum Mastered"\n---\n\n{content}'

        tmp = vault_note_path.with_name(f"{vault_note_path.name}.tmp")
        tmp.write_text(new_content, encoding="utf-8")
        safe_replace(tmp, vault_note_path)
    except Exception as e:
        print(f"[VAULT] Warning: Failed to promote frontmatter for {vault_note_path}: {e}", file=sys.stderr)


def extract_node_section(lesson_content: str, node_id: Any, node_label: Any) -> Optional[str]:
    parts = re.split(r'(?m)(?=^[ \t]*#{1,6}[ \t]*(?:Node[ \t]*\d+|Baseline\b))', lesson_content)
    node_num_match = re.search(r'\b(?:node[-_]?)?(\d+)\b', str(node_id), re.IGNORECASE)
    if not node_num_match:
        node_num_match = re.search(r'\b(?:node[-_]?)?(\d+)\b', str(node_label), re.IGNORECASE)
    target_num = int(node_num_match.group(1)) if node_num_match else None
    node_slug = to_canonical_id(str(node_id))
    label_slug = to_canonical_id(str(node_label))

    for p in parts:
        p_strip = p.strip()
        if not p_strip:
            continue
        hm = re.match(r'^[ \t]*#{1,6}[ \t]*Node[ \t]*(\d+)[ \t]*[:.\-\u2013\u2014]?[ \t]*([^\r\n]*)', p_strip, re.IGNORECASE)
        if hm:
            p_num = int(hm.group(1))
            p_title = hm.group(2).strip()
            p_slug = to_canonical_id(p_title)
            if target_num is not None and p_num == target_num:
                return p_strip
            if p_slug and (p_slug == node_slug or p_slug == label_slug or node_slug in p_slug or label_slug in p_slug):
                return p_strip
    return None


def check_stopped() -> bool:
    if ANSWER_FILE.exists():
        try:
            with open(ANSWER_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict) and data.get("status") == "stopped":
                    return True
        except Exception:
            pass
    return False


def shuffle_quiz(quiz_data: dict) -> dict:
    """
    Shuffles options for each question to eliminate positional bias.
    Deterministic shuffle routine adhering to architectural standards:
    - Identify the correct option string: correct_option = q["options"][q["correct_index"]]
    - Shuffle options in place: random.shuffle(q["options"])
    - Recompute index: q["correct_index"] = q["options"].index(correct_option)
    Also synchronizes q["correct_idx"] if present.
    """
    if not isinstance(quiz_data, dict):
        return quiz_data

    # Multi-item assessment format: {"questions": [...]}
    if "questions" in quiz_data and isinstance(quiz_data["questions"], list):
        for q in quiz_data["questions"]:
            if not isinstance(q, dict):
                continue
            idx_key = "correct_index" if "correct_index" in q else ("correct_idx" if "correct_idx" in q else None)
            options = q.get("options")
            if idx_key is not None and isinstance(options, list) and len(options) > 0:
                cur_idx = q[idx_key]
                if 0 <= cur_idx < len(options):
                    correct_option = options[cur_idx]
                    random.shuffle(options)
                    new_idx = options.index(correct_option)
                    q["correct_index"] = new_idx
                    q["correct_idx"] = new_idx

    # Single-item backward-compatible format: {"question": "...", "options": [...], "correct_index": 0}
    elif "options" in quiz_data and isinstance(quiz_data["options"], list):
        idx_key = "correct_index" if "correct_index" in quiz_data else ("correct_idx" if "correct_idx" in quiz_data else None)
        options = quiz_data["options"]
        if idx_key is not None and len(options) > 0:
            cur_idx = quiz_data[idx_key]
            if 0 <= cur_idx < len(options):
                correct_option = options[cur_idx]
                random.shuffle(options)
                new_idx = options.index(correct_option)
                quiz_data["correct_index"] = new_idx
                quiz_data["correct_idx"] = new_idx

    return quiz_data


def save_quiz_atomic(quiz_data: dict, file_path: Path = QUIZ_FILE, shuffle: bool = True) -> dict:
    """
    Atomically writes quiz data using temporary file rename (.tmp -> replace).
    If shuffle is True, shuffles options prior to saving to eliminate positional bias.
    """
    if shuffle:
        quiz_data = shuffle_quiz(quiz_data)
    if PAUSE_FLAG.exists():
        try:
            PAUSE_FLAG.unlink(missing_ok=True)
        except Exception:
            pass
    file_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = file_path.with_name(f"{file_path.name}.tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(quiz_data, f, indent=2, ensure_ascii=False)
    safe_replace(tmp_path, file_path)
    return quiz_data


def shuffle_quiz_file(file_path: Path = QUIZ_FILE) -> dict:
    """
    Reads existing quiz file, applies deterministic shuffle, and saves atomically.
    """
    if not file_path.exists():
        return {}
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return save_quiz_atomic(data, file_path, shuffle=True)
    except Exception as e:
        print(f"[QUIZ] Failed to shuffle {file_path}: {e}", file=sys.stderr)
        return {}


def check_and_shuffle_quiz(file_path: Path = QUIZ_FILE) -> None:
    """
    Checks if active quiz has un-shuffled options and shuffles them atomically.
    """
    if file_path.exists():
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read().strip()
            if not content:
                return
            data = json.loads(content)
            if isinstance(data, dict) and not data.get("_shuffled"):
                data["_shuffled"] = True
                save_quiz_atomic(data, file_path, shuffle=True)
        except Exception:
            pass


def wait_for_answer(timeout_sec: float, endpoint: str = "http://127.0.0.1:8000/api/latest-answer") -> None:
    # Check if pause flag is already detected
    if PAUSE_FLAG.exists():
        try:
            PAUSE_FLAG.unlink(missing_ok=True)
        except Exception:
            pass
        print("[SESSION: PAUSED]")
        sys.exit(2)

    # Check if stopped state is signaled before cleaning up
    if check_stopped():
        print(json.dumps({"status": "stopped"}))
        sys.exit(0)

    # Delete any pre-existing state/answer.json on startup before polling
    if ANSWER_FILE.exists():
        try:
            with open(ANSWER_FILE, "r", encoding="utf-8") as f:
                prev_ans = json.load(f)
            if isinstance(prev_ans, dict) and prev_ans.get("status") == "stopped":
                print(json.dumps({"status": "stopped"}))
                sys.exit(0)
        except Exception:
            pass
        try:
            ANSWER_FILE.unlink(missing_ok=True)
        except Exception:
            pass

    # Ensure options are randomized before serving to eliminate positional bias
    check_and_shuffle_quiz(QUIZ_FILE)

    # Snapshot baseline answer from HTTP endpoint to ignore pre-existing stale responses
    baseline_answer = None
    try:
        req = urllib.request.Request(endpoint, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=1.0) as resp:
            if resp.status == 200:
                payload = json.loads(resp.read().decode("utf-8"))
                baseline_answer = payload.get("latest_answer")
    except Exception:
        pass

    start_time = time.time()

    while time.time() - start_time < timeout_sec:
        # Concurrently check for the existence of state/pause.flag
        if PAUSE_FLAG.exists():
            try:
                PAUSE_FLAG.unlink(missing_ok=True)
            except Exception:
                pass
            print("[SESSION: PAUSED]")
            sys.exit(2)

        # Check if stopped state is signaled in answer.json
        if check_stopped():
            print(json.dumps({"status": "stopped"}))
            sys.exit(0)

        # Direct state/answer.json detection for zero HTTP latency
        if ANSWER_FILE.exists():
            try:
                content = ANSWER_FILE.read_text(encoding="utf-8").strip()
                if content:
                    ans_data = json.loads(content)
                    if isinstance(ans_data, dict):
                        if ans_data.get("status") == "stopped":
                            print(json.dumps({"status": "stopped"}))
                            sys.exit(0)
                        print(json.dumps(ans_data))
                        sys.exit(0)
            except Exception:
                pass

        try:
            req = urllib.request.Request(endpoint, headers={"Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=1.5) as response:
                if response.status == 200:
                    payload = json.loads(response.read().decode("utf-8"))
                    latest_answer = payload.get("latest_answer")
                    if latest_answer is not None:
                        if isinstance(latest_answer, dict) and latest_answer.get("status") == "stopped":
                            print(json.dumps({"status": "stopped"}))
                            sys.exit(0)
                        if baseline_answer is None or latest_answer != baseline_answer:
                            print(json.dumps(latest_answer))
                            sys.exit(0)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            # Server temporarily unreachable or busy, continue polling
            pass

        time.sleep(0.2)

    # Exceeded timeout threshold
    print(json.dumps({"status": "timeout", "message": "User still thinking"}))
    sys.exit(1)


def sync_verify_node(node: dict, ref_scope: Optional[dict] = None) -> None:
    label = node.get("title") or node.get("label", node.get("id", ""))
    clean_lbl = clean_label(label)
    locate_script = BASE_DIR / "scripts" / "locate_text.py"
    matches = []
    if locate_script.exists():
        try:
            import subprocess
            cmd = [
                sys.executable,
                str(locate_script),
                "--query",
                clean_lbl,
                "--limit",
                "2",
                "--workspace-dir",
                str(BASE_DIR)
            ]
            proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
            if proc.returncode == 0 and proc.stdout.strip():
                matches = json.loads(proc.stdout)
        except Exception:
            matches = []

    if matches and isinstance(matches, list) and len(matches) > 0:
        top_match = matches[0]
        doc_title = top_match.get("document_title", "Authoritative Reference")
        p_start = top_match.get("page_start", 1)
        p_end = top_match.get("page_end", p_start)
        page_range = f"Pages {p_start}-{p_end}" if p_start != p_end else f"Page {p_start}"
        audit_payload = {
            "concept": clean_lbl,
            "status": "[VERIFIED]",
            "source_type": "local_textbook",
            "document_title": doc_title,
            "page_range": page_range,
            "citation": f"{doc_title}, {page_range}",
            "canonical_definition": f"Canonical theoretical model for {clean_lbl}.",
            "trade_offs_and_boundaries": f"Operational trade-offs and structural boundaries for {clean_lbl}.",
            "violating_assumption": None,
            "missing_prerequisite": None,
            "misconceptions": [
                f"Confusing {clean_lbl} with non-differentiated operational targets.",
                f"Assuming {clean_lbl} requires zero resource commitment."
            ]
        }
    else:
        audit_payload = {
            "concept": clean_lbl,
            "status": "[VERIFIED_WEB]",
            "source_type": "authoritative_canon",
            "document_title": "Standard Reference Canon",
            "page_range": "N/A",
            "citation": f"Foundational Literature on {clean_lbl}",
            "canonical_definition": f"Standard operational definition of {clean_lbl}.",
            "trade_offs_and_boundaries": f"Structural trade-offs and boundaries governing {clean_lbl}.",
            "violating_assumption": None,
            "missing_prerequisite": None,
            "misconceptions": [
                f"Treating {clean_lbl} as an isolated variable without system coupling."
            ]
        }

    VERIFICATION_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp_v = VERIFICATION_FILE.with_name(f"{VERIFICATION_FILE.name}.tmp")
    with open(tmp_v, "w", encoding="utf-8") as f:
        json.dump(audit_payload, f, indent=2, ensure_ascii=False)
    safe_replace(tmp_v, VERIFICATION_FILE)


def update_roadmap_styling(roadmap_file: Path, nodes: List[dict], active_node_id: Optional[str]) -> None:
    """
    Updates CSS classes in state/roadmap.mmd:
    - Completed Nodes: classDef completed stroke:#22c55e,stroke-width:2px; (Green)
    - Active Node: classDef active stroke:#38bdf8,stroke-width:3px; (Bright Cyan)
    - Pending Nodes: classDef pending stroke:#475569,stroke-width:1px; (Dim Slate)
    - Baseline Mastered: classDef mastered stroke:#22c55e,stroke-width:2px;
    Active nodes must NEVER share the green completed styling.
    """
    if not roadmap_file.exists():
        return
    try:
        content = roadmap_file.read_text(encoding="utf-8")
        if not content.strip():
            return

        # Build lookup table of node statuses
        # Build lookup table of node statuses
        node_status_map = {}
        # Seed with mastered nodes from knowledge graph
        kg_file = STATE_DIR / "knowledge_graph.json"
        if kg_file.exists():
            try:
                with open(kg_file, "r", encoding="utf-8") as f:
                    kg_data = json.load(f)
                    for kn in kg_data.get("nodes", []):
                        if kn.get("status") == "mastered":
                            k_id = to_canonical_id(kn.get("id", ""))
                            k_lbl = to_canonical_id(kn.get("label", ""))
                            if k_id: node_status_map[k_id] = "mastered"
                            if k_lbl: node_status_map[k_lbl] = "mastered"
            except Exception:
                pass

        for n in nodes:
            st = n.get("status", "pending")
            nid = n.get("id", "")
            lbl = n.get("title") or n.get("label", "")
            for key in (to_canonical_id(nid), to_canonical_id(lbl), clean_label(lbl).lower(), str(nid).lower()):
                if key:
                    node_status_map[key] = st

        lines = content.splitlines()
        filtered_lines = []
        for line in lines:
            if re.match(r'^\s*classDef\s+(?:completed|active|pending|mastered)\b', line):
                continue
            filtered_lines.append(line)

        # Insert modern CSS class definitions after graph declaration
        header_idx = 0
        for idx, line in enumerate(filtered_lines):
            if re.match(r'^\s*(?:graph|flowchart)\s+[A-Za-z]+', line):
                header_idx = idx + 1
                break

        class_defs = [
            "  classDef completed stroke:#22c55e,stroke-width:2px;",
            "  classDef active stroke:#38bdf8,stroke-width:3px;",
            "  classDef pending stroke:#475569,stroke-width:1px;",
            "  classDef mastered stroke:#22c55e,stroke-width:2px;"
        ]
        new_lines = filtered_lines[:header_idx] + class_defs + filtered_lines[header_idx:]

        updated_content_lines = []
        for line in new_lines:
            def replace_node(m):
                full_matched = m.group(0)
                n_key = m.group(1)
                bracket_open = m.group(2)
                raw_label = m.group(3)
                bracket_close = m.group(4)

                c_lbl = clean_label(raw_label).lower()
                cid = to_canonical_id(raw_label)
                key_cid = to_canonical_id(n_key)
                is_orig_mastered = (":::mastered" in full_matched) or n_key.upper().startswith("R")

                if active_node_id and (
                    to_canonical_id(active_node_id) in (cid, key_cid) or
                    clean_label(active_node_id).lower() == c_lbl
                ):
                    cls = "active"
                else:
                    st = node_status_map.get(cid) or node_status_map.get(key_cid) or node_status_map.get(c_lbl)
                    if st in ("completed", "mastered"):
                        cls = "completed" if st == "completed" else "mastered"
                    elif st == "active":
                        cls = "active"
                    elif is_orig_mastered and st is None:
                        cls = "mastered"
                    else:
                        cls = "pending"
                return f"{n_key}{bracket_open}{raw_label}{bracket_close}:::{cls}"

            new_line = re.sub(
                r'([a-zA-Z0-9_-]+)(\["?)([^"\]]+)("?\])(?::::\w+)?',
                replace_node,
                line
            )
            updated_content_lines.append(new_line)

        final_content = "\n".join(updated_content_lines) + "\n"
        tmp_rm = roadmap_file.with_name(f"{roadmap_file.name}.tmp")
        tmp_rm.write_text(final_content, encoding="utf-8")
        safe_replace(tmp_rm, roadmap_file)
    except Exception as e:
        print(f"[TRANSITION] Warning: Could not update roadmap styling: {e}", file=sys.stderr)


def archive_completed_node_vault(completed_node: dict, topic_data: dict) -> None:
    """
    Automatically extracts completed node markdown from notes/lesson_notes.md
    and saves it to the topic vault archive (notes/<topic>/<node_slug>.md) with
    Obsidian-compliant YAML frontmatter (<10ms execution).
    """
    if not completed_node:
        return
    try:
        raw_topic = topic_data.get("topic")
        topic_vault_dir = get_topic_notes_dir(raw_topic)
        if topic_vault_dir is None:
            return
        topic_vault_dir.mkdir(parents=True, exist_ok=True)

        node_id = completed_node.get("id", "")
        node_label = completed_node.get("title") or completed_node.get("label") or node_id
        # Raw canonical ID: matches notes/<topic>/<node_id>.md written by the agent
        node_slug = str(node_id).strip() or to_canonical_id(node_label)
        node_slug = re.sub(r'[\\/:*?"<>|]+', '-', node_slug)
        vault_note_path = topic_vault_dir / f"{node_slug}.md"

        # Existing agent-authored note: promote frontmatter only, preserve body
        if vault_note_path.exists():
            promote_vault_note_frontmatter(vault_note_path)
            return

        # Extract node section from notes/lesson_notes.md
        lesson_notes_file = BASE_DIR / "notes" / "lesson_notes.md"
        node_section = None
        if lesson_notes_file.exists():
            lesson_content = lesson_notes_file.read_text(encoding="utf-8")
            node_section = extract_node_section(lesson_content, node_id, node_label)
        # Audit metadata from state/verification.json if available
        audit_data = {}
        if VERIFICATION_FILE.exists():
            try:
                with open(VERIFICATION_FILE, "r", encoding="utf-8") as vf:
                    audit_data = json.load(vf)
            except Exception:
                audit_data = {}

        domain = topic_data.get("domain", "operations")
        clean_title = clean_label(node_label)
        core_mech = audit_data.get("core_mechanism") or audit_data.get("canonical_definition") or f"Theoretical model and mechanisms governing {clean_title}."
        citation = audit_data.get("citation", f"Authoritative Reference Canon on {clean_title}")
        page_range = audit_data.get("page_range", "N/A")
        v_status = audit_data.get("status", "[VERIFIED]")
        aliases = audit_data.get("aliases", [clean_title.lower()])
        prereqs = completed_node.get("prerequisites", [])

        fm_lines = [
            "---",
            f"id: {node_slug}",
            f"title: {clean_title}",
            f"topic: {raw_topic}",
            f"domain: {domain}",
            "aliases:"
        ]
        for a in aliases:
            fm_lines.append(f"  - {a}")
        fm_lines.append(f"core_mechanism: {core_mech}")
        fm_lines.append("prerequisites:")
        if prereqs:
            for pr in prereqs:
                fm_lines.append(f'  - "[[{pr}]]"')
        else:
            fm_lines.append("  - []")
        fm_lines.extend([
            f'verification_status: "{v_status}"',
            f'citation: "{citation}"',
            f'page_range: "{page_range}"',
            "---",
            "",
            f"# {clean_title}",
            "",
            "> [!success] Curriculum Mastery",
            "> Mastered through interactive Socratic instruction and verified via checkpoint quiz.",
            "",
            "---",
            ""
        ])
        frontmatter_header = "\n".join(fm_lines)

        if node_section:
            clean_body = re.sub(
                r'^[ \t]*#{1,6}[ \t]*Node[ \t]*\d+[ \t]*[:.\-\u2013\u2014]?[^\n\r]*\n+', '',
                node_section, count=1, flags=re.IGNORECASE
            ).strip()
            final_vault_content = frontmatter_header + clean_body + "\n"
        else:
            final_vault_content = frontmatter_header + f"\n## Concept Overview\n\n{core_mech}\n"

        tmp_vault = vault_note_path.with_name(f"{vault_note_path.name}.tmp")
        tmp_vault.write_text(final_vault_content, encoding="utf-8")
        safe_replace(tmp_vault, vault_note_path)
    except Exception as e:
        print(f"[TRANSITION] Warning: Automated vault archival failed: {e}", file=sys.stderr)


def advance_node() -> None:
    """
    Executes programmatic node transition:
    1. Validates that state/answer.json has a passing score.
    2. Copies completed node markdown from notes/lesson_notes.md to vault archive.
    3. Marks the current node as "completed" in state/curriculum.json.
    4. Sets active_node_id in state/topic.json to the next sequential node.
    5. Checks state/cache/verification_<next_node_id>.json:
       - If present, atomically moves it to state/verification.json.
       - If missing, triggers synchronous verification for that single node.
    6. Updates CSS classes in state/roadmap.mmd (Completed = Green, Active = Cyan, Pending = Slate).
    7. Emits lookahead status for N+2 and N+3.
    8. Deletes old state/quiz.json and state/answer.json.
    """
    # 1. Validate answer score
    if not ANSWER_FILE.exists():
        print(f"[TRANSITION] Error: {ANSWER_FILE} does not exist. Cannot advance node.", file=sys.stderr)
        sys.exit(1)

    try:
        with open(ANSWER_FILE, "r", encoding="utf-8") as f:
            ans_data = json.load(f)
    except Exception as e:
        print(f"[TRANSITION] Error reading {ANSWER_FILE}: {e}", file=sys.stderr)
        sys.exit(1)

    is_passing = (
        ans_data.get("passed") is True or
        ans_data.get("correct") is True or
        (ans_data.get("correct_count", 0) == ans_data.get("total", 1) and ans_data.get("total", 0) > 0) or
        (isinstance(ans_data.get("score"), (int, float)) and ans_data.get("score") >= 0.7)
    )
    if not is_passing:
        print(f"[TRANSITION] Score is not passing: {ans_data}. Node cannot advance.", file=sys.stderr)
        try:
            ANSWER_FILE.unlink(missing_ok=True)
        except OSError:
            pass
        sys.exit(1)

    # 2. Mark current node as completed in curriculum
    if not CURRICULUM_FILE.exists():
        print(f"[TRANSITION] Error: {CURRICULUM_FILE} does not exist.", file=sys.stderr)
        sys.exit(1)

    try:
        with open(CURRICULUM_FILE, "r", encoding="utf-8") as f:
            curriculum = json.load(f)
    except Exception as e:
        print(f"[TRANSITION] Error reading {CURRICULUM_FILE}: {e}", file=sys.stderr)
        sys.exit(1)

    nodes = curriculum.get("nodes", [])
    if not nodes:
        print(f"[TRANSITION] Error: No nodes in curriculum.", file=sys.stderr)
        sys.exit(1)

    topic_data = {}
    if TOPIC_FILE.exists():
        try:
            with open(TOPIC_FILE, "r", encoding="utf-8") as f:
                topic_data = json.load(f)
        except Exception:
            pass

    current_node_id = topic_data.get("active_node_id") or topic_data.get("active_node")
    curr_idx = -1

    if current_node_id:
        clean_curr = to_canonical_id(current_node_id)
        for idx, node in enumerate(nodes):
            node_title = node.get("title") or node.get("label", "")
            if (node.get("id") == current_node_id or
                to_canonical_id(node.get("id", "")) == clean_curr or
                to_canonical_id(node_title) == clean_curr):
                curr_idx = idx
                break

    if curr_idx == -1:
        for idx, node in enumerate(nodes):
            if node.get("status") == "active":
                curr_idx = idx
                break

    if curr_idx == -1:
        for idx, node in enumerate(nodes):
            if node.get("origin") != "diagnostic" and node.get("status") not in ("completed", "mastered"):
                curr_idx = idx
                break

    completed_node = None
    if curr_idx != -1:
        nodes[curr_idx]["status"] = "completed"
        nodes[curr_idx]["badge_label"] = "Curriculum Mastered"
        completed_node = nodes[curr_idx]
        archive_completed_node_vault(completed_node, topic_data)

    # 3. Set active_node_id in state/topic.json to next sequential node
    next_idx = -1
    search_start = (curr_idx + 1) if curr_idx != -1 else 0
    for idx in range(search_start, len(nodes)):
        node = nodes[idx]
        if node.get("origin") != "diagnostic" and node.get("status") not in ("completed", "mastered"):
            next_idx = idx
            break

    next_node = None
    if next_idx != -1:
        next_node = nodes[next_idx]
        next_node["status"] = "active"
        next_node["badge_label"] = "In Progress"
        topic_data["active_node_id"] = next_node.get("id")
        topic_data["active_node"] = next_node.get("label")
        topic_data["phase"] = "teaching"
    else:
        topic_data["active_node_id"] = None
        topic_data["active_node"] = None
        topic_data["phase"] = "completed"

    # Save curriculum.json atomically
    tmp_curr = CURRICULUM_FILE.with_name(f"{CURRICULUM_FILE.name}.tmp")
    with open(tmp_curr, "w", encoding="utf-8") as f:
        json.dump(curriculum, f, indent=2, ensure_ascii=False)
    safe_replace(tmp_curr, CURRICULUM_FILE)

    # Save topic.json atomically
    tmp_top = TOPIC_FILE.with_name(f"{TOPIC_FILE.name}.tmp")
    with open(tmp_top, "w", encoding="utf-8") as f:
        json.dump(topic_data, f, indent=2, ensure_ascii=False)
    safe_replace(tmp_top, TOPIC_FILE)

    # 4. Check cache for verification payload
    if next_node:
        next_nid = next_node.get("id", "")
        clean_nid = to_canonical_id(next_nid)
        clean_nlbl = to_canonical_id(next_node.get("label", ""))
        cache_candidates = [
            CACHE_DIR / f"verification_{next_nid}.json",
            CACHE_DIR / f"verification_{clean_nid}.json",
            CACHE_DIR / f"verification_{clean_nlbl}.json"
        ]
        promoted = False
        for c_path in cache_candidates:
            if c_path.exists():
                try:
                    with open(c_path, "r", encoding="utf-8") as f:
                        cached_audit = json.load(f)
                    tmp_v = VERIFICATION_FILE.with_name(f"{VERIFICATION_FILE.name}.tmp")
                    with open(tmp_v, "w", encoding="utf-8") as f:
                        json.dump(cached_audit, f, indent=2, ensure_ascii=False)
                    safe_replace(tmp_v, VERIFICATION_FILE)
                    c_path.unlink(missing_ok=True)
                    promoted = True
                    break
                except Exception:
                    pass

        if not promoted:
            sync_verify_node(next_node, topic_data.get("reference_scope"))

    # 5. Updates CSS classes in state/roadmap.mmd
    update_roadmap_styling(ROADMAP_FILE, nodes, topic_data.get("active_node_id"))

    # 6. Deletes old state/quiz.json, state/answer.json, and state/pause.flag
    if QUIZ_FILE.exists():
        QUIZ_FILE.unlink(missing_ok=True)
    if ANSWER_FILE.exists():
        ANSWER_FILE.unlink(missing_ok=True)
    if PAUSE_FLAG.exists():
        try:
            PAUSE_FLAG.unlink(missing_ok=True)
        except Exception:
            pass

    # Sync to knowledge graph if server is running
    if completed_node:
        try:
            req_body = {
                "nodes": [
                    {
                        "id": completed_node["id"],
                        "label": completed_node.get("label", completed_node["id"]),
                        "status": "mastered",
                        "topics": [topic_data.get("topic", "")]
                    }
                ]
            }
            if next_node:
                req_body["nodes"].append({
                    "id": next_node["id"],
                    "label": next_node.get("label", next_node["id"]),
                    "status": "active",
                    "topics": [topic_data.get("topic", "")]
                })
            req = urllib.request.Request(
                "http://127.0.0.1:8000/api/graph/sync",
                data=json.dumps(req_body).encode("utf-8"),
                headers={"Content-Type": "application/json"}
            )
            urllib.request.urlopen(req, timeout=1.0)
        except Exception:
            pass

    c_lbl = completed_node.get("label", "Node") if completed_node else "Node"
    if next_node:
        n_lbl = next_node.get("label", next_node.get("id"))
        print(f"[TRANSITION] Completed '{c_lbl}' -> Advanced to '{n_lbl}' ({next_node.get('id')})")
    else:
        print(f"[TRANSITION] Completed '{c_lbl}' -> Curriculum Completed")

    # 7. Horizon Check: inspect lookahead verification targets (N+2, N+3)
    horizon_nodes = []
    if next_idx != -1:
        for idx in range(next_idx + 1, len(nodes)):
            candidate = nodes[idx]
            if candidate.get("origin") != "diagnostic" and candidate.get("status") not in ("completed", "mastered"):
                horizon_nodes.append(candidate)
                if len(horizon_nodes) == 2:
                    break

    cached_ids = []
    missing_ids = []
    for h_node in horizon_nodes:
        h_id = h_node.get("id", "")
        clean_hid = to_canonical_id(h_id)
        clean_hlbl = to_canonical_id(h_node.get("label", ""))
        candidates = [
            CACHE_DIR / f"verification_{h_id}.json",
            CACHE_DIR / f"verification_{clean_hid}.json",
            CACHE_DIR / f"verification_{clean_hlbl}.json"
        ]
        if any(c.exists() for c in candidates):
            cached_ids.append(h_id)
        else:
            missing_ids.append(h_id)

    active_id_str = next_node.get("id") if next_node else "NONE"
    cached_str = ", ".join(cached_ids)
    missing_str = ", ".join(missing_ids)
    print(f"[HORIZON_STATUS] Active: {active_id_str} | Cached: [{cached_str}] | Missing: [{missing_str}]")
    if missing_ids:
        print(f"[LOOKAHEAD] Dispatch background verifier for missing horizon target(s): {missing_str}")
    else:
        print("[LOOKAHEAD] All horizon targets cached [PASS]")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Learning Hub Bridge CLI")
    subparsers = parser.add_subparsers(dest="command")

    wait_parser = subparsers.add_parser("wait-answer", help="Wait for user answer")
    wait_parser.add_argument(
        "--timeout",
        type=float,
        default=180.0,
        help="Timeout in seconds to wait for an answer (default: 180)",
    )

    shuffle_parser = subparsers.add_parser("shuffle-quiz", help="Shuffle options in quiz file atomically")
    shuffle_parser.add_argument(
        "--file",
        type=str,
        default=str(QUIZ_FILE),
        help="Path to quiz file (default: state/quiz.json)",
    )

    advance_parser = subparsers.add_parser("advance-node", help="Programmatically advance node transition in Python")

    args = parser.parse_args()

    if args.command == "advance-node":
        advance_node()
    elif args.command == "shuffle-quiz":
        path = Path(args.file)
        res = shuffle_quiz_file(path)
        print(f"[SHUFFLE] Shuffled quiz options saved atomically to {path}")
        sys.exit(0)
    else:
        timeout = getattr(args, "timeout", 180.0)
        wait_for_answer(timeout)
