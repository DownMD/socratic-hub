import copy
import json
import os
import random
import re
import shutil
import signal
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

BASE_DIR = Path(__file__).resolve().parent
STATE_DIR = BASE_DIR / "state"
NOTES_DIR = BASE_DIR / "notes"
STATIC_DIR = BASE_DIR / "static"
INDEX_FILE = STATIC_DIR / "index.html"
KNOWLEDGE_GRAPH_FILE = STATE_DIR / "knowledge_graph.json"
PAUSE_FLAG = STATE_DIR / "pause.flag"
ACTIVE_SESSION_FILE = STATE_DIR / "active_session.json"
CACHE_DIR = STATE_DIR / "cache"

try:
    from scripts.clean_knowledge_graph import transitive_reduction, MERGE_MAP
except ImportError:
    import sys
    sys.path.append(str(BASE_DIR))
    from scripts.clean_knowledge_graph import transitive_reduction, MERGE_MAP

DEFAULT_STATE: Dict[str, Any] = {
    "session_active": False,
    "topic": None,
    "status": "standby",
    "phase": "idle",
    "active_node": None,
    "active_node_id": None,
    "current_node": "",
    "notes": "",
    "lesson_markdown": "",
    "quiz": None,
    "active_quiz": None,
    "dag_mermaid": "graph TD\n",
    "latest_answer": None,
    "quiz_history": [],
    "reference_scope": None
}

DEFAULT_ACTIVE_SESSION_SKELETON: Dict[str, Any] = {
    "active_topic": None,
    "phase": "idle",
    "active_node_id": None,
    "reference_scope": {"collection": "general", "tags": []}
}

DEFAULT_KNOWLEDGE_GRAPH_SKELETON: Dict[str, Any] = {
    "nodes": [],
    "links": []
}


def ensure_state_skeletons() -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    NOTES_DIR.mkdir(parents=True, exist_ok=True)

    if not ACTIVE_SESSION_FILE.exists() or ACTIVE_SESSION_FILE.stat().st_size == 0 or not ACTIVE_SESSION_FILE.read_text(encoding="utf-8").strip():
        with open(ACTIVE_SESSION_FILE, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_ACTIVE_SESSION_SKELETON, f, indent=2)

    if not KNOWLEDGE_GRAPH_FILE.exists() or KNOWLEDGE_GRAPH_FILE.stat().st_size == 0 or not KNOWLEDGE_GRAPH_FILE.read_text(encoding="utf-8").strip():
        with open(KNOWLEDGE_GRAPH_FILE, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_KNOWLEDGE_GRAPH_SKELETON, f, indent=2)



def safe_replace(src: Path, dst: Path, max_retries: int = 5) -> None:
    for attempt in range(max_retries):
        try:
            src.replace(dst)
            return
        except (PermissionError, OSError):
            if attempt == max_retries - 1:
                raise
            time.sleep(0.05 * pow(2, attempt))


def atomic_write_file(path: Path, content: str | bytes) -> None:
    """Atomic write with flush, fsync, and retry-safe POSIX replacement."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f"{path.name}.tmp")
    mode = "wb" if isinstance(content, bytes) else "w"
    encoding = None if isinstance(content, bytes) else "utf-8"
    with open(tmp_path, mode, encoding=encoding) as f:
        f.write(content)
        f.flush()
        try:
            os.fsync(f.fileno())
        except (AttributeError, OSError):
            pass
    safe_replace(tmp_path, path)


def atomic_write_json(path: Path, data: Any) -> None:
    """Atomic JSON write with flush, fsync, and retry-safe POSIX replacement."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f"{path.name}.tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.flush()
        try:
            os.fsync(f.fileno())
        except (AttributeError, OSError):
            pass
    safe_replace(tmp_path, path)


def delete_pause_flag() -> None:
    if PAUSE_FLAG.exists():
        try:
            PAUSE_FLAG.unlink(missing_ok=True)
        except Exception:
            pass


def create_pause_flag() -> Dict[str, Any]:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "action": "PAUSE",
        "timestamp": datetime.now(timezone.utc).isoformat()
    }
    tmp_flag = PAUSE_FLAG.with_name(f"{PAUSE_FLAG.name}.tmp")
    with open(tmp_flag, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    safe_replace(tmp_flag, PAUSE_FLAG)
    return payload


def sanitize_topic(topic: str) -> str:
    s = re.sub(r'[^a-zA-Z0-9]+', '-', topic.strip().lower())
    s = re.sub(r'-+', '-', s).strip('-')
    return s or "default"


def get_topic_notes_dir(topic_name: Optional[str]) -> Optional[Path]:
    """Resolve canonical notes directory for a topic.

    Guards against empty, 'Not Set', or 'not-set' to prevent phantom directory creation.
    Resolution order:
    1. Empty / 'Not Set' / 'not-set' / 'none' -> None
    2. NOTES_DIR / topic_name exists -> return it (Title Case canonical)
    3. NOTES_DIR / sanitize_topic(topic_name) exists -> return it (legacy slug)
    4. Otherwise -> return NOTES_DIR / topic_name (Title Case default)
    """
    if not topic_name or topic_name.strip().lower() in ("not set", "not-set", "none", ""):
        return None
    cleaned = topic_name.strip()
    canonical = NOTES_DIR / cleaned
    if canonical.exists():
        return canonical
    slug = NOTES_DIR / sanitize_topic(cleaned)
    if slug.exists():
        return slug
    return canonical


def clean_label(label: str) -> str:
    s = re.sub(r'^(?:Node\s*\d+[:.]\s*|Baseline[:.]\s*|\d+[\.\)]\s*)', '', str(label).strip(), flags=re.IGNORECASE)
    return s.strip()


def to_canonical_id(text: str) -> str:
    clean = re.sub(r'^(?:Node\s*\d+[:.]\s*|Baseline[:.]\s*|\d+[\.\)]\s*)', '', str(text).strip(), flags=re.IGNORECASE).strip()
    s = re.sub(r'[^a-zA-Z0-9]+', '-', clean.lower()).strip('-')
    return s or "default"


def canonical_id(label: str) -> str:
    return to_canonical_id(label)


def find_fuzzy_concept_match(candidate_title: str, existing_nodes: List[Dict[str, Any]]) -> Optional[str]:
    """
    Fuzzy token-set matching to identify duplicate concepts:
    - Tokenizes into lowercase alphanumeric word sets, excluding punctuation and stopwords ("and", "or", "the", "of", "in", "&").
    - Calculates Token Jaccard overlap: len(A & B) / len(A | B).
    - Checks multi-word subset containment: A.issubset(B) or B.issubset(A) when min(len(A), len(B)) >= 3.
    - If Jaccard >= 0.60 OR subset containment holds, returns existing canonical node ID.
    """
    if not candidate_title:
        return None

    stopwords = {"and", "or", "the", "of", "in", "&"}

    def tokenize(text: str) -> set:
        if not text:
            return set()
        cleaned = clean_label(str(text))
        tokens = re.findall(r'[a-zA-Z0-9]+', cleaned.lower())
        return {t for t in tokens if t not in stopwords}

    cand_set = tokenize(candidate_title)
    if not cand_set:
        return None

    for node in existing_nodes:
        node_id = str(node.get("id", "")).strip()
        node_label = str(node.get("label", "")).strip()

        # Check against label first, fallback to id
        node_set = tokenize(node_label)
        if not node_set and node_id:
            node_set = tokenize(node_id)
        if not node_set:
            continue

        union = cand_set | node_set
        intersection = cand_set & node_set
        jaccard = (len(intersection) / len(union)) if union else 0.0

        subset_contained = False
        if min(len(cand_set), len(node_set)) >= 3:
            if cand_set.issubset(node_set) or node_set.issubset(cand_set):
                subset_contained = True

        if jaccard >= 0.60 or subset_contained:
            return node_id

    return None


def normalize_concept_id(text: str) -> str:
    """Normalize text into an alphanumeric identifier stripping punctuation and apostrophe s."""
    if not text:
        return ""
    cleaned = clean_label(str(text))
    cleaned = re.sub(r"['\u2019]s\b", "s", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "-", cleaned.lower()).strip("-")
    cleaned = re.sub(r"-s-", "s-", cleaned)
    if cleaned.endswith("-s"):
        cleaned = cleaned[:-2] + "s"
    return cleaned


def find_matching_node_key(cand_id: str, cand_title: str, nodes_dict: Dict[str, Dict[str, Any]]) -> Optional[str]:
    """Find existing node key in nodes_dict by exact key, canonical ID, normalized concept ID, alias, or fuzzy title match."""
    if not nodes_dict:
        return None
    # 1. Exact match
    if cand_id and cand_id in nodes_dict:
        return cand_id

    # 2. Canonical ID match
    cand_cid = to_canonical_id(cand_id)
    cand_ctitle = to_canonical_id(cand_title)
    cand_cids = {c for c in (cand_cid, cand_ctitle) if c and c != "default"}

    for key, node in nodes_dict.items():
        node_cids = {
            to_canonical_id(key),
            to_canonical_id(node.get("id", "")),
            to_canonical_id(node.get("title", "")),
            to_canonical_id(node.get("label", ""))
        }
        for al in node.get("aliases", []):
            node_cids.add(to_canonical_id(str(al)))
        node_cids.discard("default")
        node_cids.discard("")
        if cand_cids & node_cids:
            return key

    # 3. Normalized concept ID match
    cand_norm_id = normalize_concept_id(cand_id)
    cand_norm_title = normalize_concept_id(cand_title)
    cand_norms = {c for c in (cand_norm_id, cand_norm_title) if c}

    for key, node in nodes_dict.items():
        node_norms = {
            normalize_concept_id(key),
            normalize_concept_id(node.get("id", "")),
            normalize_concept_id(node.get("title", "")),
            normalize_concept_id(node.get("label", ""))
        }
        for al in node.get("aliases", []):
            node_norms.add(normalize_concept_id(str(al)))
        node_norms.discard("")
        if cand_norms & node_norms:
            return key

    # 4. Fuzzy concept match
    existing_list = list(nodes_dict.values())
    matched_id = None
    if cand_title:
        matched_id = find_fuzzy_concept_match(cand_title, existing_list)
    if not matched_id and cand_id:
        matched_id = find_fuzzy_concept_match(cand_id.replace("-", " "), existing_list)
    if matched_id:
        if matched_id in nodes_dict:
            return matched_id
        for key, node in nodes_dict.items():
            if node.get("id") == matched_id:
                return key

    return None


def parse_frontmatter(content: str) -> Dict[str, Any]:
    fm_match = re.match(r'^---\s*\r?\n([\s\S]*?)\r?\n---\s*(\r?\n|$)', content)
    fm_text = ""
    if fm_match:
        fm_text = fm_match.group(1)
    else:
        hdr_match = re.match(r'^(id:\s*[\w-]+[\r\n]+[\s\S]*?)(?:\r?\n\r?\n|$)', content.strip(), re.IGNORECASE)
        if hdr_match:
            fm_text = hdr_match.group(1)
    if not fm_text:
        title_match = re.search(r'^#\s+([^\r\n]+)', content, re.MULTILINE)
        if title_match:
            return {"title": title_match.group(1).strip()}
        return {}

    data: Dict[str, Any] = {}
    current_list_key: Optional[str] = None
    for line in fm_text.splitlines():
        line_strip = line.strip()
        if not line_strip or line_strip.startswith('#'):
            continue
        if line_strip.startswith('- ') and current_list_key:
            item = line_strip[2:].strip().strip('"\'')
            data[current_list_key].append(item)
            continue
        if ':' in line:
            parts = line.split(':', 1)
            key = parts[0].strip()
            val = parts[1].strip().strip('"\'')
            if not val:
                current_list_key = key
                data[key] = []
            else:
                current_list_key = None
                data[key] = val
        else:
            current_list_key = None

    if "title" not in data:
        title_match = re.search(r'^#\s+([^\r\n]+)', content, re.MULTILINE)
        if title_match:
            data["title"] = title_match.group(1).strip()

    return data


def get_active_session() -> Dict[str, Any]:
    """Retrieve ephemeral active session pointer from state/active_session.json."""
    if not ACTIVE_SESSION_FILE.exists():
        return DEFAULT_ACTIVE_SESSION_SKELETON.copy()
    try:
        data = json.loads(ACTIVE_SESSION_FILE.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return {**DEFAULT_ACTIVE_SESSION_SKELETON, **data}
    except Exception:
        pass
    return DEFAULT_ACTIVE_SESSION_SKELETON.copy()


def save_active_session(sess: Dict[str, Any]) -> None:
    """Atomically save active session pointer to state/active_session.json."""
    atomic_write_json(ACTIVE_SESSION_FILE, sess)


def get_active_topic_dir() -> Optional[Path]:
    """Resolve topic directory for the active session."""
    sess = get_active_session()
    topic = sess.get("active_topic")
    if not topic or topic in ("Not Set", "not-set", "none", ""):
        return None
    return get_topic_notes_dir(topic)


def load_topic_manifest(topic_name_or_dir: Any) -> Optional[Dict[str, Any]]:
    """Load canonical manifest.json for a topic, synthesizing and reconciling notes on disk."""
    if isinstance(topic_name_or_dir, Path):
        t_dir = topic_name_or_dir
    else:
        t_dir = get_topic_notes_dir(str(topic_name_or_dir))
    if not t_dir or not t_dir.exists():
        return None
    synth = synthesize_manifest_for_topic(t_dir)
    if synth and synth.get("nodes"):
        return synth
    man_file = t_dir / "manifest.json"
    if man_file.exists():
        try:
            data = json.loads(man_file.read_text(encoding="utf-8"))
            if isinstance(data, dict) and data.get("nodes"):
                return data
        except Exception:
            pass
    return None


def save_topic_manifest(topic_name_or_dir: Any, manifest: Dict[str, Any]) -> None:
    """Atomically save topic manifest.json."""
    if isinstance(topic_name_or_dir, Path):
        t_dir = topic_name_or_dir
    else:
        t_dir = get_topic_notes_dir(str(topic_name_or_dir))
    if not t_dir:
        return
    t_dir.mkdir(parents=True, exist_ok=True)
    man_file = t_dir / "manifest.json"
    atomic_write_json(man_file, manifest)


def compile_mermaid_dag(manifest: Dict[str, Any]) -> str:
    """Dynamically compile Mermaid flowchart string from manifest nodes and prerequisites.
    Prunes nodes with 0 incoming and 0 outgoing edges unless active or diagnostic.
    """
    nodes = manifest.get("nodes", [])
    if not nodes:
        return "graph TD\n"

    # Map all IDs, canonical IDs, and aliases to nodes
    id_map: Dict[str, str] = {}
    for node in nodes:
        nid = str(node.get("id", "")).strip()
        if not nid:
            continue
        id_map[nid] = nid
        id_map[nid.lower()] = nid
        id_map[to_canonical_id(nid)] = nid
        id_map[normalize_concept_id(nid)] = nid
        if node.get("title"):
            id_map[to_canonical_id(node["title"])] = nid
            id_map[normalize_concept_id(node["title"])] = nid
        if node.get("label"):
            id_map[to_canonical_id(node["label"])] = nid
            id_map[normalize_concept_id(node["label"])] = nid
        for al in node.get("aliases", []):
            id_map[str(al).strip()] = nid
            id_map[str(al).strip().lower()] = nid
            id_map[to_canonical_id(al)] = nid
            id_map[normalize_concept_id(al)] = nid

    # Compute incoming prerequisites and outgoing dependents
    incoming: Dict[str, set] = {str(n.get("id", "")).strip(): set() for n in nodes}
    outgoing: Dict[str, set] = {str(n.get("id", "")).strip(): set() for n in nodes}

    for node in nodes:
        nid = str(node.get("id", "")).strip()
        prereqs = node.get("prerequisites", [])
        if isinstance(prereqs, str):
            prereqs = [prereqs]
        for pr in prereqs:
            clean_pr = str(pr).replace("[[", "").replace("]]", "").strip()
            src_id = (
                id_map.get(clean_pr)
                or id_map.get(clean_pr.lower())
                or id_map.get(to_canonical_id(clean_pr))
                or id_map.get(normalize_concept_id(clean_pr))
            )
            if src_id and src_id in incoming and src_id != nid:
                incoming[nid].add(src_id)
                outgoing[src_id].add(nid)

    # Prune any node that has 0 incoming prerequisites AND 0 outgoing dependents UNLESS
    # it is explicitly marked as active or origin == 'diagnostic'
    filtered_nodes = []
    for node in nodes:
        nid = str(node.get("id", "")).strip()
        nst = str(node.get("status", "")).lower().strip()
        badge = str(node.get("badge_label", "")).lower().strip()
        origin = str(node.get("origin", "")).lower().strip()
        is_active = (nst in ("active", "in_progress") or "active" in badge or "progress" in badge)
        is_diag = (origin == "diagnostic" or "baseline" in badge)

        in_cnt = len(incoming.get(nid, set()))
        out_cnt = len(outgoing.get(nid, set()))

        if len(nodes) > 1 and in_cnt == 0 and out_cnt == 0 and not is_active and not is_diag:
            continue  # Prune isolated phantom node
        filtered_nodes.append(node)

    if not filtered_nodes:
        filtered_nodes = nodes

    lines = [
        "flowchart TD",
        "  classDef completed stroke:#22c55e,stroke-width:2px;",
        "  classDef active stroke:#38bdf8,stroke-width:3px;",
        "  classDef pending stroke:#475569,stroke-width:1px;",
        "  classDef mastered stroke:#22c55e,stroke-width:2px;",
        ""
    ]
    id_to_key: Dict[str, str] = {}
    for idx, node in enumerate(filtered_nodes):
        nid = str(node.get("id", f"node_{idx}")).strip()
        nkey = f"N{idx+1}"
        id_to_key[nid] = nkey
        id_to_key[nid.lower()] = nkey
        id_to_key[to_canonical_id(nid)] = nkey
        id_to_key[normalize_concept_id(nid)] = nkey
        if node.get("title"):
            id_to_key[to_canonical_id(node["title"])] = nkey
            id_to_key[normalize_concept_id(node["title"])] = nkey
        if node.get("label"):
            id_to_key[to_canonical_id(node["label"])] = nkey
            id_to_key[normalize_concept_id(node["label"])] = nkey
        for al in node.get("aliases", []):
            id_to_key[str(al).strip()] = nkey
            id_to_key[str(al).strip().lower()] = nkey
            id_to_key[to_canonical_id(al)] = nkey
            id_to_key[normalize_concept_id(al)] = nkey
        nlbl = str(node.get("title") or node.get("label") or nid).replace('"', "'").strip()
        nst = str(node.get("status", "pending")).lower().strip()
        if nst in ("in_progress", "active"):
            nst = "active"
        elif nst not in ("completed", "active", "pending", "mastered"):
            nst = "pending"
        lines.append(f'  {nkey}["{nlbl}"]:::{nst}')

    lines.append("")
    edges_added = set()
    for idx, node in enumerate(filtered_nodes):
        nid = str(node.get("id", f"node_{idx}")).strip()
        nkey = id_to_key.get(nid) or f"N{idx+1}"
        prereqs = node.get("prerequisites", [])
        if isinstance(prereqs, str):
            prereqs = [prereqs]
        for pr in prereqs:
            clean_pr = str(pr).replace("[[", "").replace("]]", "").strip()
            pr_key = (
                id_to_key.get(clean_pr)
                or id_to_key.get(clean_pr.lower())
                or id_to_key.get(to_canonical_id(clean_pr))
                or id_to_key.get(normalize_concept_id(clean_pr))
            )
            if pr_key and pr_key != nkey and (pr_key, nkey) not in edges_added:
                edges_added.add((pr_key, nkey))
                lines.append(f"  {pr_key} --> {nkey}")

    return "\n".join(lines) + "\n"


def synthesize_manifest_for_topic(topic_dir: Path) -> Dict[str, Any]:
    """Synthesize and auto-reconcile manifest.json from existing manifest, topic notes,
    state/knowledge_graph.json, session.json, curriculum.json, and roadmap.mmd."""
    topic_name = topic_dir.name.replace("-", " ").title()
    domain = "general"
    ref_scope = {"collection": "general", "tags": []}
    nodes_dict: Dict[str, Dict[str, Any]] = {}
    alias_map: Dict[str, str] = {}
    initial_node_ids = set()

    def add_or_merge_node(
        cand_id: str,
        cand_title: str,
        cand_prereqs: List[str],
        cand_status: Optional[str] = None,
        cand_badge: Optional[str] = None,
        cand_origin: Optional[str] = None,
        node_number: Optional[int] = None
    ) -> str:
        clean_cand_title = clean_label(cand_title or cand_id)
        matched_key = find_matching_node_key(cand_id, clean_cand_title, nodes_dict)

        if matched_key:
            existing = nodes_dict[matched_key]
            existing.setdefault("aliases", [])
            for a in (cand_id, clean_cand_title, to_canonical_id(clean_cand_title), to_canonical_id(cand_id)):
                if a and a not in existing["aliases"] and a != existing["id"]:
                    existing["aliases"].append(a)
            for a in (cand_id, clean_cand_title, to_canonical_id(clean_cand_title), to_canonical_id(cand_id), normalize_concept_id(cand_id), normalize_concept_id(clean_cand_title)):
                if a:
                    alias_map[a] = existing["id"]

            for pr in cand_prereqs:
                if pr and pr not in existing["prerequisites"]:
                    existing["prerequisites"].append(pr)

            ex_st = str(existing.get("status", "")).lower()
            cand_st = str(cand_status or "").lower()
            if cand_st in ("mastered", "completed"):
                existing["status"] = "mastered"
                existing["badge_label"] = "Curriculum Mastered"
            elif cand_st in ("active", "in_progress") and ex_st not in ("mastered", "completed"):
                existing["status"] = cand_status or "active"
                existing["badge_label"] = "In Progress"
            elif cand_st in ("planned", "pending") and not existing.get("status"):
                existing["status"] = cand_st

            if cand_origin and not existing.get("origin"):
                existing["origin"] = cand_origin
            if node_number and not existing.get("node_number"):
                existing["node_number"] = node_number
            return existing["id"]
        else:
            nid = cand_id or to_canonical_id(clean_cand_title)
            nodes_dict[nid] = {
                "id": nid,
                "title": clean_cand_title,
                "label": clean_cand_title,
                "prerequisites": list(cand_prereqs),
                "status": cand_status or "planned",
                "badge_label": cand_badge or ("Curriculum Mastered" if cand_status in ("mastered", "completed") else "In Progress"),
                "aliases": []
            }
            if cand_origin:
                nodes_dict[nid]["origin"] = cand_origin
            if node_number:
                nodes_dict[nid]["node_number"] = node_number
            alias_map[nid] = nid
            alias_map[to_canonical_id(nid)] = nid
            alias_map[normalize_concept_id(nid)] = nid
            if clean_cand_title:
                alias_map[clean_cand_title] = nid
                alias_map[to_canonical_id(clean_cand_title)] = nid
                alias_map[normalize_concept_id(clean_cand_title)] = nid
            return nid

    # 1. Ingest existing manifest.json if present on disk
    man_file = topic_dir / "manifest.json"
    existing_manifest_raw = None
    if man_file.exists():
        try:
            existing_manifest_raw = json.loads(man_file.read_text(encoding="utf-8"))
            if isinstance(existing_manifest_raw, dict):
                topic_name = existing_manifest_raw.get("topic") or topic_name
                domain = existing_manifest_raw.get("domain") or domain
                ref_scope = existing_manifest_raw.get("reference_scope") or ref_scope
                for m_node in existing_manifest_raw.get("nodes", []):
                    nid = m_node.get("id") or to_canonical_id(m_node.get("label") or m_node.get("title"))
                    if nid:
                        initial_node_ids.add(nid)
                        initial_node_ids.add(to_canonical_id(nid))
                        add_or_merge_node(
                            nid,
                            m_node.get("title") or m_node.get("label") or nid,
                            m_node.get("prerequisites") or [],
                            m_node.get("status", "planned"),
                            m_node.get("badge_label"),
                            m_node.get("origin"),
                            m_node.get("node_number")
                        )
        except Exception:
            pass

    # 2. Ingest state/knowledge_graph.json cluster for this topic
    try:
        kg = load_knowledge_graph()
        topic_slug = sanitize_topic(topic_dir.name)
        topic_name_slug = sanitize_topic(topic_name)
        for kn in kg.get("nodes", []):
            k_topics = kn.get("topics") or []
            if isinstance(k_topics, str):
                k_topics = [k_topics]
            norm_k_topics = [sanitize_topic(t) for t in k_topics]
            if topic_slug in norm_k_topics or topic_name_slug in norm_k_topics:
                kn_id = kn.get("id") or to_canonical_id(kn.get("label") or "")
                add_or_merge_node(
                    kn_id,
                    kn.get("label") or kn_id,
                    [],
                    kn.get("status") or "planned",
                    kn.get("badge_label"),
                    kn.get("origin")
                )

        # Ingest knowledge graph prerequisite edges
        for ke in kg.get("edges", []):
            src = ke.get("source")
            tgt = ke.get("target")
            if src and tgt:
                src_canon = alias_map.get(src) or alias_map.get(to_canonical_id(src)) or src
                tgt_canon = alias_map.get(tgt) or alias_map.get(to_canonical_id(tgt)) or tgt
                if tgt_canon in nodes_dict and src_canon in nodes_dict and src_canon != tgt_canon:
                    if src_canon not in nodes_dict[tgt_canon]["prerequisites"]:
                        nodes_dict[tgt_canon]["prerequisites"].append(src_canon)
    except Exception:
        pass

    session_file = topic_dir / "session.json"
    session_completed: List[str] = []
    session_current = ""
    if session_file.exists():
        try:
            s_data = json.loads(session_file.read_text(encoding="utf-8"))
            topic_name = s_data.get("topic") or topic_name
            ref_scope = s_data.get("reference_scope") or ref_scope
            session_completed = [clean_label(c) for c in (s_data.get("completed_nodes") or [])]
            session_current = clean_label(s_data.get("current_node") or "")
        except Exception:
            pass

    curr_file = topic_dir / "curriculum.json"
    if curr_file.exists():
        try:
            c_data = json.loads(curr_file.read_text(encoding="utf-8"))
            topic_name = c_data.get("topic") or topic_name
            for c_node in (c_data.get("nodes") or []):
                nid = c_node.get("id") or to_canonical_id(c_node.get("label") or c_node.get("title"))
                clean_prereqs = [
                    str(p).replace("[[", "").replace("]]", "").strip()
                    for p in (c_node.get("prerequisites") or [])
                    if str(p).replace("[", "").replace("]", "").strip()
                ]
                add_or_merge_node(
                    nid,
                    c_node.get("title") or c_node.get("label") or nid,
                    clean_prereqs,
                    c_node.get("status", "planned"),
                    c_node.get("badge_label", ""),
                    c_node.get("origin"),
                    c_node.get("node_number")
                )
        except Exception:
            pass

    # 3. Scan all *.md files in notes/<topic>/ (excluding hidden folders like .session and .diagnostic)
    missing_notes_merged = False
    for md_path in sorted(topic_dir.glob("*.md")):
        if md_path.name.startswith(".") or md_path.name.lower() in ("notes.md", "lesson_notes.md"):
            continue
        try:
            content = md_path.read_text(encoding="utf-8")
            fm = parse_frontmatter(content)
            nid = fm.get("id") or md_path.stem
            clean_title = fm.get("title") or md_path.stem.replace("-", " ").title()
            if not domain or domain == "general":
                domain = fm.get("domain") or domain
            raw_prereqs = fm.get("prerequisites") or []
            clean_prereqs = []
            for rp in raw_prereqs:
                c_p = str(rp).replace("[[", "").replace("]]", "").replace("[", "").replace("]", "").strip()
                if c_p and c_p not in clean_prereqs:
                    clean_prereqs.append(c_p)
            
            fm_status = str(fm.get("status") or "").strip().strip('"\'')
            if fm_status.lower() in ("mastered", "completed"):
                status = "mastered"
            elif fm_status:
                status = fm_status
            else:
                if any(to_canonical_id(c) == to_canonical_id(clean_title) for c in session_completed):
                    status = "mastered"
                elif session_current and to_canonical_id(session_current) == to_canonical_id(clean_title):
                    status = "active"
                elif "[!success]" in content:
                    status = "mastered"
                else:
                    status = "pending"

            badge = "Curriculum Mastered" if status in ("mastered", "completed") else ("In Progress" if status in ("active", "in_progress") else "Planned")
            
            matched_key = find_matching_node_key(nid, clean_title, nodes_dict)
            if not matched_key and nid not in initial_node_ids and to_canonical_id(nid) not in initial_node_ids:
                missing_notes_merged = True

            add_or_merge_node(nid, clean_title, clean_prereqs, status, badge, fm.get("origin"))
        except Exception:
            pass

    roadmap_file = topic_dir / "roadmap.mmd"
    if roadmap_file.exists():
        try:
            r_text = roadmap_file.read_text(encoding="utf-8")
            key_to_id: Dict[str, str] = {}
            node_defs = re.findall(r'([a-zA-Z0-9_\-]+)\s*\["?([^"\]]+)"?\](?::::(\w+))?', r_text)
            for nk, raw_lbl, st in node_defs:
                lbl = clean_label(raw_lbl)
                cid = to_canonical_id(lbl)
                status = "mastered" if st in ("completed", "mastered") else ("active" if st == "active" else "planned")
                badge = "Curriculum Mastered" if status in ("mastered", "completed") else "In Progress"
                resolved_id = add_or_merge_node(cid, lbl, [], status, badge)
                key_to_id[nk] = resolved_id
                alias_map[nk] = resolved_id

            edge_defs = re.findall(r'([a-zA-Z0-9_\-]+)(?:\[[^\]]*\])?\s*-->\s*([a-zA-Z0-9_\-]+)', r_text)
            for sk, tk in edge_defs:
                s_id = alias_map.get(sk) or key_to_id.get(sk) or to_canonical_id(sk)
                t_id = alias_map.get(tk) or key_to_id.get(tk) or to_canonical_id(tk)
                s_canon = alias_map.get(s_id, s_id)
                t_canon = alias_map.get(t_id, t_id)
                if s_canon and t_canon and t_canon in nodes_dict and s_canon != t_canon:
                    if s_canon not in nodes_dict[t_canon]["prerequisites"]:
                        nodes_dict[t_canon]["prerequisites"].append(s_canon)
        except Exception:
            pass

    for node in nodes_dict.values():
        clean_prs = []
        for pr in node.get("prerequisites", []):
            raw_pr = str(pr).replace("[[", "").replace("]]", "").strip()
            resolved = alias_map.get(raw_pr) or alias_map.get(to_canonical_id(raw_pr)) or alias_map.get(normalize_concept_id(raw_pr)) or raw_pr
            if resolved in alias_map:
                resolved = alias_map[resolved]
            if resolved and resolved != node["id"] and resolved in nodes_dict and resolved not in clean_prs:
                clean_prs.append(resolved)
        node["prerequisites"] = clean_prs

    manifest_result = {
        "topic": topic_name,
        "domain": domain,
        "reference_scope": ref_scope,
        "nodes": list(nodes_dict.values())
    }

    # Atomically save manifest.json on disk if missing notes were merged or manifest changed
    if missing_notes_merged or not man_file.exists() or existing_manifest_raw != manifest_result:
        save_topic_manifest(topic_dir, manifest_result)

    return manifest_result


def reconcile_startup_state() -> None:
    """Startup crash recovery, orphan directory sweep, transient cleanup, and legacy manifest synthesis."""
    if not NOTES_DIR.exists():
        return

    # 1. Orphan Directory Sweep: purge any notes/*/ containing .diagnostic/ but lacking a valid manifest.json
    for item in list(NOTES_DIR.iterdir()):
        if item.is_dir() and not item.name.startswith("."):
            diag_dir = item / ".diagnostic"
            manifest_file = item / "manifest.json"
            if diag_dir.exists() and (not manifest_file.exists() or manifest_file.stat().st_size == 0):
                has_notes = any(f.suffix == ".md" and f.name.lower() not in ("notes.md", "lesson_notes.md") for f in item.iterdir() if f.is_file())
                if not has_notes:
                    try:
                        shutil.rmtree(item, ignore_errors=True)
                    except Exception:
                        pass

    # 2. Transient Cleanup: unlink dangling .tmp files, leftover .session/ directories, or state/pause.flag
    for root, _, files in os.walk(NOTES_DIR):
        for f in files:
            if f.endswith(".tmp"):
                try:
                    (Path(root) / f).unlink(missing_ok=True)
                except Exception:
                    pass
    if STATE_DIR.exists():
        for f in STATE_DIR.glob("*.tmp"):
            try:
                f.unlink(missing_ok=True)
            except Exception:
                pass

    active_sess = get_active_session()
    active_top = active_sess.get("active_topic")
    is_paused = (active_sess.get("phase") == "PAUSED")

    for item in NOTES_DIR.iterdir():
        if item.is_dir() and not item.name.startswith("."):
            sess_dir = item / ".session"
            if sess_dir.exists():
                is_active_topic = bool(active_top and (sanitize_topic(active_top) == sanitize_topic(item.name) or active_top.strip().lower() == item.name.strip().lower()))
                if not is_active_topic or active_sess.get("phase") in ("idle", "standby", ""):
                    try:
                        shutil.rmtree(sess_dir, ignore_errors=True)
                    except Exception:
                        pass

    if not is_paused and PAUSE_FLAG.exists():
        delete_pause_flag()

    # 3. Legacy Manifest Synthesis (Operational Guard 2)
    for item in NOTES_DIR.iterdir():
        if item.is_dir() and not item.name.startswith("."):
            man_file = item / "manifest.json"
            if not man_file.exists() or man_file.stat().st_size == 0:
                synth = synthesize_manifest_for_topic(item)
                if synth and synth.get("nodes"):
                    save_topic_manifest(item, synth)


def load_knowledge_graph() -> Dict[str, Any]:
    if not KNOWLEDGE_GRAPH_FILE.exists():
        return {"nodes": [], "edges": [], "links": []}
    try:
        with open(KNOWLEDGE_GRAPH_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if not isinstance(data, dict):
                return {"nodes": [], "edges": [], "links": []}
            data.setdefault("nodes", [])
            data.setdefault("edges", [])
            data.setdefault("links", [])
            return data
    except Exception:
        return {"nodes": [], "edges": [], "links": []}


def save_knowledge_graph(kg: Dict[str, Any]) -> None:
    KNOWLEDGE_GRAPH_FILE.parent.mkdir(parents=True, exist_ok=True)
    temp_file = KNOWLEDGE_GRAPH_FILE.with_suffix(".tmp")
    with open(temp_file, "w", encoding="utf-8") as f:
        json.dump(kg, f, indent=2, ensure_ascii=False)
    safe_replace(temp_file, KNOWLEDGE_GRAPH_FILE)


def bootstrap_knowledge_graph() -> Dict[str, Any]:
    nodes_map: Dict[str, Dict[str, Any]] = {}
    edges_list: List[Dict[str, Any]] = []
    existing_edge_keys = set()

    if NOTES_DIR.exists():
        for item in sorted(NOTES_DIR.iterdir()):
            if item.is_dir():
                topic_name = item.name.replace("-", " ").title()
                session_file = item / "session.json"
                roadmap_file = item / "roadmap.mmd"
                completed_nodes = []
                current_node = ""

                if session_file.exists():
                    try:
                        with open(session_file, "r", encoding="utf-8") as f:
                            s_data = json.load(f)
                            topic_name = s_data.get("topic") or topic_name
                            completed_nodes = s_data.get("completed_nodes") or []
                            current_node = s_data.get("current_node") or ""
                    except Exception:
                        pass

                key_to_cid: Dict[str, str] = {}
                if roadmap_file.exists():
                    try:
                        r_text = roadmap_file.read_text(encoding="utf-8")
                        node_defs = re.findall(r'([a-zA-Z0-9_\-]+)\s*\["?([^"\]]+)"?\]', r_text)
                        for n_key, raw_lbl in node_defs:
                            lbl = clean_label(raw_lbl)
                            cid = to_canonical_id(lbl)
                            key_to_cid[n_key] = cid
                            is_completed = any(clean_label(c).lower() == lbl.lower() for c in completed_nodes)
                            if is_completed:
                                st = "mastered"
                            elif current_node and clean_label(current_node).lower() == lbl.lower():
                                st = "active"
                            else:
                                st = "planned"

                            key = cid
                            if key in nodes_map:
                                existing = nodes_map[key]
                                if existing.get("status") != "mastered" and st == "mastered":
                                    existing["status"] = "mastered"
                                if topic_name not in existing.get("topics", []):
                                    existing.setdefault("topics", []).append(topic_name)
                            else:
                                nodes_map[key] = {
                                    "id": cid,
                                    "label": lbl,
                                    "status": st,
                                    "topics": [topic_name]
                                }

                        edge_defs = re.findall(r'([a-zA-Z0-9_\-]+)(?:\[[^\]]*\])?\s*-->\s*([a-zA-Z0-9_\-]+)', r_text)
                        for src_k, tgt_k in edge_defs:
                            src_cid = key_to_cid.get(src_k) or to_canonical_id(src_k)
                            tgt_cid = key_to_cid.get(tgt_k) or to_canonical_id(tgt_k)
                            if src_cid and tgt_cid and src_cid != tgt_cid and (src_cid, tgt_cid) not in existing_edge_keys:
                                existing_edge_keys.add((src_cid, tgt_cid))
                                edges_list.append({
                                    "source": src_cid,
                                    "target": tgt_cid,
                                    "relation": "prerequisite"
                                })
                    except Exception:
                        pass

                for c_node in completed_nodes:
                    lbl = clean_label(c_node)
                    cid = to_canonical_id(lbl)
                    key = cid
                    if key in nodes_map:
                        nodes_map[key]["status"] = "mastered"
                        if topic_name not in nodes_map[key].get("topics", []):
                            nodes_map[key].setdefault("topics", []).append(topic_name)
                    else:
                        nodes_map[key] = {
                            "id": cid,
                            "label": lbl,
                            "status": "mastered",
                            "topics": [topic_name]
                        }

    kg = {
        "nodes": list(nodes_map.values()),
        "edges": edges_list
    }
    kg = validate_and_repair_graph_edges(kg)
    save_knowledge_graph(kg)
    return kg


def validate_and_repair_graph_edges(kg: Dict[str, Any]) -> Dict[str, Any]:
    nodes = kg.get("nodes", [])
    edges = kg.get("edges", [])

    node_id_map: Dict[str, str] = {}
    for n in nodes:
        nid = n.get("id")
        if not nid:
            continue
        node_id_map[nid] = nid
        node_id_map[nid.lower()] = nid
        lbl = n.get("label")
        if lbl:
            c_lbl = clean_label(lbl)
            node_id_map[c_lbl] = nid
            node_id_map[c_lbl.lower()] = nid
            cid = to_canonical_id(lbl)
            if cid:
                node_id_map[cid] = nid
                node_id_map[cid.lower()] = nid

    valid_node_ids = set(node_id_map.values())
    valid_edges = []
    seen = set()

    for e in edges:
        raw_s = str(e.get("source", "")).strip()
        raw_t = str(e.get("target", "")).strip()
        s = node_id_map.get(raw_s) or node_id_map.get(raw_s.lower())
        t = node_id_map.get(raw_t) or node_id_map.get(raw_t.lower())
        if s and t and s != t and s in valid_node_ids and t in valid_node_ids:
            if (s, t) not in seen:
                seen.add((s, t))
                valid_edges.append({
                    "source": s,
                    "target": t,
                    "relation": e.get("relation", "prerequisite")
                })

    # Auto-reconstruction if edges are missing or malformed for curriculum topics
    jlpt_nodes = [n for n in nodes if any("jlpt" in str(t).lower() for t in n.get("topics", []))]
    process_nodes = [n for n in nodes if any("process" in str(t).lower() for t in n.get("topics", []))]

    jlpt_edge_count = sum(1 for e in valid_edges if e["source"] in {n["id"] for n in jlpt_nodes})
    process_edge_count = sum(1 for e in valid_edges if e["source"] in {n["id"] for n in process_nodes})

    if len(jlpt_nodes) >= 2 and jlpt_edge_count < 5:
        roadmap_file = NOTES_DIR / "JLPT N5 Grammar & Syntax" / "roadmap.mmd"
        if roadmap_file.exists():
            try:
                r_text = roadmap_file.read_text(encoding="utf-8")
                raw_k_map = {}
                for nk, nlbl in re.findall(r'([a-zA-Z0-9_\-]+)\s*\["?([^"\]]+)"?\]', r_text):
                    cid = node_id_map.get(clean_label(nlbl)) or node_id_map.get(to_canonical_id(nlbl))
                    if cid:
                        raw_k_map[nk] = cid
                for sk, tk in re.findall(r'([a-zA-Z0-9_\-]+)(?:\[[^\]]*\])?\s*-->\s*([a-zA-Z0-9_\-]+)', r_text):
                    s_id = raw_k_map.get(sk) or node_id_map.get(sk)
                    t_id = raw_k_map.get(tk) or node_id_map.get(tk)
                    if s_id and t_id and s_id != t_id and (s_id, t_id) not in seen:
                        seen.add((s_id, t_id))
                        valid_edges.append({"source": s_id, "target": t_id, "relation": "prerequisite"})
            except Exception:
                pass

    if len(process_nodes) >= 2 and process_edge_count < 5:
        roadmap_file = NOTES_DIR / "Process Analysis" / "roadmap.mmd"
        if roadmap_file.exists():
            try:
                r_text = roadmap_file.read_text(encoding="utf-8")
                raw_k_map = {}
                for nk, nlbl in re.findall(r'([a-zA-Z0-9_\-]+)\s*\["?([^"\]]+)"?\]', r_text):
                    cid = node_id_map.get(clean_label(nlbl)) or node_id_map.get(to_canonical_id(nlbl))
                    if cid:
                        raw_k_map[nk] = cid
                for sk, tk in re.findall(r'([a-zA-Z0-9_\-]+)(?:\[[^\]]*\])?\s*-->\s*([a-zA-Z0-9_\-]+)', r_text):
                    s_id = raw_k_map.get(sk) or node_id_map.get(sk)
                    t_id = raw_k_map.get(tk) or node_id_map.get(tk)
                    if s_id and t_id and s_id != t_id and (s_id, t_id) not in seen:
                        seen.add((s_id, t_id))
                        valid_edges.append({"source": s_id, "target": t_id, "relation": "prerequisite"})
            except Exception:
                pass

    kg["edges"] = valid_edges
    kg["links"] = valid_edges
    return kg
_QUIZ_CACHE: Dict[str, Dict[str, Any]] = {}


def sanitize_and_normalize_quiz(raw_text: str) -> Dict[str, Any]:
    raw_text = raw_text.strip()
    if not raw_text:
        return {"questions": []}

    if raw_text in _QUIZ_CACHE:
        return copy.deepcopy(_QUIZ_CACHE[raw_text])

    parsed = None
    try:
        parsed = json.loads(raw_text)
    except Exception:
        # Regex pass: escape isolated \ preceding non-JSON control characters so LaTeX formulas do not break JSON parsing
        fixed = re.sub(r'\\(?![\\"/bfnrt]|u[0-9a-fA-F]{4})', r'\\\\', raw_text)
        try:
            parsed = json.loads(fixed)
        except Exception:
            fixed2 = re.sub(r'\\(?!["\\])', r'\\\\', raw_text)
            try:
                parsed = json.loads(fixed2)
            except Exception:
                return {"questions": []}

    # Normalize parsed JSON structure:
    # If root is a list [...], wrap it in {"questions": [...]}
    if isinstance(parsed, list):
        payload: Dict[str, Any] = {"questions": parsed}
    elif isinstance(parsed, dict):
        if "questions" in parsed and isinstance(parsed["questions"], list):
            payload = parsed
        elif "question" in parsed or "prompt" in parsed or "title" in parsed:
            payload = {
                "node_id": parsed.get("node_id"),
                "questions": [parsed]
            }
        else:
            payload = parsed
            if "questions" not in payload or not isinstance(payload["questions"], list):
                payload["questions"] = []
    else:
        return {"questions": []}

    norm_questions: List[Dict[str, Any]] = []
    raw_qs = payload.get("questions", [])
    if isinstance(raw_qs, list):
        for idx, q in enumerate(raw_qs):
            if not isinstance(q, dict):
                continue
            item = dict(q)
            # Normalize question fields: map prompt or title to question
            if not item.get("question"):
                if item.get("prompt"):
                    item["question"] = item["prompt"]
                elif item.get("title"):
                    item["question"] = item["title"]
                else:
                    item["question"] = ""

            # Normalize options: if options is an object {"A": "...", "B": "..."}, convert to standard array ["A) ...", "B) ..."]
            opts = item.get("options")
            if isinstance(opts, dict):
                norm_opts = []
                for k in sorted(opts.keys()):
                    val = str(opts[k])
                    if val.strip().startswith(f"{k})") or val.strip().startswith(f"{k}."):
                        norm_opts.append(val)
                    else:
                        norm_opts.append(f"{k}) {val}")
                item["options"] = norm_opts
            elif isinstance(opts, list):
                item["options"] = [str(o) for o in opts]
            else:
                item["options"] = []

            # Atomically shuffle options upon normalizing each question:
            if not parsed.get("_shuffled") and item.get("options"):
                paired = list(enumerate(item.get("options", [])))
                random.shuffle(paired)
                # Update correct_idx to match the new position of the correct answer
                orig_correct = item.get("correct_idx", item.get("correct_index", 0))
                try:
                    orig_correct = int(orig_correct)
                except (ValueError, TypeError):
                    orig_correct = 0
                new_correct = next((i for i, (orig_i, _) in enumerate(paired) if orig_i == orig_correct), 0)
                item["options"] = [opt for _, opt in paired]
                item["correct_idx"] = new_correct
                item["correct_index"] = new_correct

            if not item.get("id"):
                item["id"] = f"q{idx + 1}"

            norm_questions.append(item)

    payload["questions"] = norm_questions
    payload["_shuffled"] = True
    if len(_QUIZ_CACHE) > 50:
        _QUIZ_CACHE.clear()
    _QUIZ_CACHE[raw_text] = copy.deepcopy(payload)
    return payload


def load_state() -> Dict[str, Any]:
    """Hydrates session state strictly from state/active_session.json and topic manifest."""
    data = DEFAULT_STATE.copy()

    # 1. Ephemeral Active Session pointer strictly from state/active_session.json
    active_sess = get_active_session()
    active_topic = active_sess.get("active_topic")
    active_phase = active_sess.get("phase") or "idle"

    has_active_topic = bool(
        active_topic and
        active_topic not in ("", "Not Set", "not-set", "none", None)
    )

    if has_active_topic:
        status = "active"
        session_active = True
    else:
        if str(active_phase).lower() == "reading":
            status = "reading"
            session_active = True
        elif str(active_phase).lower() in ("idle", "standby", ""):
            status = "standby"
            session_active = False
        else:
            status = "active"
            session_active = True

    t_dir = get_topic_notes_dir(active_topic) if has_active_topic else None
    manifest = None
    if has_active_topic and t_dir and t_dir.exists():
        manifest = synthesize_manifest_for_topic(t_dir)

    # Dynamic DAG compilation
    compiled_dag = "graph TD\n"
    if manifest:
        data["manifest"] = manifest
        compiled_dag = compile_mermaid_dag(manifest)
    data["dag_mermaid"] = compiled_dag

    # Active Node resolution
    active_nid = active_sess.get("active_node_id")
    active_lbl = None
    if manifest and manifest.get("nodes"):
        nodes = manifest["nodes"]
        if active_nid:
            for n in nodes:
                if str(n.get("id")) == str(active_nid) or to_canonical_id(n.get("id", "")) == to_canonical_id(active_nid):
                    active_lbl = n.get("title") or n.get("label") or active_nid
                    break
        if not active_lbl:
            for n in nodes:
                if str(n.get("status", "")).lower() == "active":
                    active_nid = n.get("id")
                    active_lbl = n.get("title") or n.get("label") or active_nid
                    break
        if not active_lbl:
            for n in nodes:
                if str(n.get("status", "")).lower() not in ("mastered", "completed"):
                    active_nid = n.get("id")
                    active_lbl = n.get("title") or n.get("label") or active_nid
                    break

    # Read active note markdown directly from topic vault
    note_content = ""
    if has_active_topic and t_dir and active_nid:
        cand_files = [
            t_dir / f"{active_nid}.md",
            t_dir / f"{to_canonical_id(active_nid)}.md"
        ]
        if active_lbl:
            cand_files.append(t_dir / f"{to_canonical_id(active_lbl)}.md")
        for cf in cand_files:
            if cf.exists() and cf.is_file():
                try:
                    note_content = cf.read_text(encoding="utf-8")
                    break
                except Exception:
                    pass

    if not note_content and has_active_topic and t_dir:
        cand_notes = t_dir / "notes.md"
        if cand_notes.exists():
            try:
                note_content = cand_notes.read_text(encoding="utf-8")
            except Exception:
                pass

    data["lesson_markdown"] = note_content
    data["notes"] = note_content

    # Active quiz reading from .session/ or .diagnostic/
    q_data = None
    if has_active_topic and t_dir:
        target_quiz_file = (t_dir / ".diagnostic" / "diagnostic_quiz.json") if active_phase == "probing" else (t_dir / ".session" / "quiz.json")
        if target_quiz_file.exists():
            try:
                raw_q = target_quiz_file.read_text(encoding="utf-8").strip()
                if raw_q:
                    q_data = sanitize_and_normalize_quiz(raw_q)
            except Exception:
                pass

    data["active_quiz"] = q_data
    data["quiz"] = q_data

    # Latest answer reading from .session/ or .diagnostic/
    ans_data = None
    if has_active_topic and t_dir:
        target_ans_file = (t_dir / ".diagnostic" / "baseline_passes.json") if active_phase == "probing" else (t_dir / ".session" / "answer.json")
        if target_ans_file.exists():
            try:
                ans_data = json.loads(target_ans_file.read_text(encoding="utf-8"))
            except Exception:
                pass

    data["latest_answer"] = ans_data
    data["quiz_history"] = [ans_data] if ans_data else []

    data["topic"] = active_topic if has_active_topic else None
    data["phase"] = active_phase
    data["session_active"] = session_active
    data["status"] = status
    data["active_node_id"] = active_nid
    data["active_node"] = active_lbl
    data["current_node"] = active_lbl or ""
    data["reference_scope"] = active_sess.get("reference_scope")

    return data


def save_state(state: Dict[str, Any]) -> None:
    """Persist session mutations into state/active_session.json and notes/<active_topic>/manifest.json. Deprecates state/state.json."""
    active_sess = get_active_session()
    changed = False

    if "topic" in state and state["topic"] != active_sess.get("active_topic"):
        active_sess["active_topic"] = state["topic"]
        changed = True
    if "phase" in state and state["phase"] != active_sess.get("phase"):
        active_sess["phase"] = state["phase"]
        changed = True
    if "active_node_id" in state and state["active_node_id"] != active_sess.get("active_node_id"):
        active_sess["active_node_id"] = state["active_node_id"]
        changed = True
    if "reference_scope" in state and state["reference_scope"]:
        if state["reference_scope"] != active_sess.get("reference_scope"):
            active_sess["reference_scope"] = state["reference_scope"]
            changed = True

    if changed:
        save_active_session(active_sess)

    # If manifest is present and active topic exists, save manifest
    if "manifest" in state and state["manifest"]:
        topic = active_sess.get("active_topic")
        if topic:
            t_dir = get_topic_notes_dir(topic)
            if t_dir and t_dir.exists():
                save_topic_manifest(t_dir, state["manifest"])


app = FastAPI(title="Autonomous 1-on-1 Learning Hub Backend")

# Enable CORS for all origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup_flush_buffers():
    """Startup reconciliation, buffer flush, and state skeletons assurance."""
    ensure_state_skeletons()
    reconcile_startup_state()
    state = load_state()
    state["quiz_history"] = []
    state["latest_answer"] = None
    save_state(state)


# Pydantic Request Models
class TopicRequest(BaseModel):
    topic: str
    reference_scope: Optional[Dict[str, Any]] = None
    mode: Optional[str] = "study"


class QuizRequest(BaseModel):
    question: str
    options: List[str]
    correct_idx: int
    explanation: str


class AnswerRequest(BaseModel):
    selected_idx: int
    question_idx: Optional[int] = 0


class BatchQuizSubmitRequest(BaseModel):
    node_id: Optional[str] = None
    answers: List[int]
    timestamp: Optional[str] = None


class DagRequest(BaseModel):
    mermaid: str


class LessonRequest(BaseModel):
    markdown_chunk: str


class ArchiveRequest(BaseModel):
    topic: Optional[str] = ""


class RestoreRequest(BaseModel):
    topic: str


class DiscardTopicRequest(BaseModel):
    topic: str


class GraphSyncRequest(BaseModel):
    nodes: List[Dict[str, Any]] = Field(default_factory=list)
    edges: List[Dict[str, Any]] = Field(default_factory=list)


# REST Endpoints
@app.get("/api/graph/global")
def get_global_graph() -> Dict[str, Any]:
    kg = load_knowledge_graph()
    if not kg.get("nodes"):
        kg = bootstrap_knowledge_graph()
    kg = validate_and_repair_graph_edges(kg)
    return kg


@app.post("/api/graph/sync")
def sync_knowledge_graph(req: GraphSyncRequest) -> Dict[str, Any]:
    kg = load_knowledge_graph()
    existing_nodes = kg.get("nodes", [])
    existing_edges = kg.get("edges", [])

    STATUS_RANK = {"planned": 1, "active": 2, "mastered": 3}
    nodes_by_cid: Dict[str, Dict[str, Any]] = {}
    id_alias_map: Dict[str, str] = {}

    # Seed with existing nodes
    for n in existing_nodes:
        raw_lbl = n.get("label", "")
        raw_id = str(n.get("id", "")).strip()
        c_lbl = clean_label(raw_lbl) if raw_lbl else ""
        cid = to_canonical_id(raw_id or c_lbl)
        if not cid:
            continue
        n["id"] = cid
        if not n.get("label"):
            n["label"] = c_lbl or cid
        nodes_by_cid[cid] = n
        id_alias_map[cid] = cid
        id_alias_map[cid.lower()] = cid
        if raw_id:
            id_alias_map[raw_id] = cid
            id_alias_map[raw_id.lower()] = cid
        if c_lbl:
            id_alias_map[c_lbl] = cid
            id_alias_map[c_lbl.lower()] = cid

    diagnostic_cids = set()
    # Process incoming nodes
    for in_node in req.nodes:
        raw_label = in_node.get("label", "")
        raw_id = str(in_node.get("id", "")).strip()
        in_label = clean_label(raw_label)
        cid = to_canonical_id(raw_id or in_label)
        if not cid:
            continue

        if in_node.get("origin") == "diagnostic":
            diagnostic_cids.add(cid)
            if raw_id:
                diagnostic_cids.add(to_canonical_id(raw_id))
            if in_label:
                diagnostic_cids.add(to_canonical_id(in_label))

        in_status = str(in_node.get("status", "planned")).lower()
        if in_status not in STATUS_RANK:
            in_status = "planned"

        in_topics = in_node.get("topics", [])
        if isinstance(in_topics, str):
            in_topics = [in_topics]
        elif not isinstance(in_topics, list):
            in_topics = []

        # Record aliases for edge resolution
        id_alias_map[cid] = cid
        id_alias_map[cid.lower()] = cid
        if raw_id:
            id_alias_map[raw_id] = cid
            id_alias_map[raw_id.lower()] = cid
        if in_label:
            id_alias_map[in_label] = cid
            id_alias_map[in_label.lower()] = cid

        # Check for fuzzy match against existing nodes if not directly in nodes_by_cid
        if cid not in nodes_by_cid:
            fuzzy_id = find_fuzzy_concept_match(in_label or raw_label or raw_id, list(nodes_by_cid.values()))
            if fuzzy_id and fuzzy_id in nodes_by_cid:
                cid = fuzzy_id

        if cid in nodes_by_cid:
            existing = nodes_by_cid[cid]
            curr_status = str(existing.get("status", "planned")).lower()
            if curr_status == "mastered":
                final_status = "mastered"
            else:
                final_status = in_status if STATUS_RANK.get(in_status, 1) > STATUS_RANK.get(curr_status, 1) else curr_status
            existing["status"] = final_status

            if in_label and (not existing.get("label") or existing["label"] == existing["id"]):
                existing["label"] = in_label

            existing_topics = existing.get("topics", [])
            if isinstance(existing_topics, str):
                existing_topics = [existing_topics]
            elif not isinstance(existing_topics, list):
                existing_topics = []

            for t in in_topics:
                if t and t not in existing_topics:
                    existing_topics.append(t)
            existing["topics"] = existing_topics
            if in_node.get("origin"):
                existing["origin"] = in_node["origin"]
            if in_node.get("badge_label"):
                existing["badge_label"] = in_node["badge_label"]
        else:
            new_node = {
                "id": cid,
                "label": in_label or cid,
                "status": in_status,
                "topics": list(dict.fromkeys([t for t in in_topics if t])),
                "origin": in_node.get("origin"),
                "badge_label": in_node.get("badge_label")
            }
            nodes_by_cid[cid] = new_node

    def resolve_endpoint(val: Any) -> str:
        if not val:
            return ""
        s = str(val).strip()
        if s in id_alias_map:
            return id_alias_map[s]
        s_low = s.lower()
        if s_low in id_alias_map:
            return id_alias_map[s_low]
        c = to_canonical_id(s)
        if c in nodes_by_cid:
            return c
        return c or s

    unique_edges: List[Dict[str, Any]] = []
    seen_edge_pairs = set()

    # Preserve all existing edges first
    for e in existing_edges:
        src = resolve_endpoint(e.get("source"))
        tgt = resolve_endpoint(e.get("target"))
        if src and tgt and src != tgt:
            pair = (src, tgt)
            if pair not in seen_edge_pairs:
                seen_edge_pairs.add(pair)
                unique_edges.append({
                    "source": src,
                    "target": tgt,
                    "relation": e.get("relation", "prerequisite")
                })

    # Merge incoming edges
    for in_edge in req.edges:
        src = resolve_endpoint(in_edge.get("source"))
        tgt = resolve_endpoint(in_edge.get("target"))
        if src and tgt and src != tgt:
            pair = (src, tgt)
            if pair not in seen_edge_pairs:
                seen_edge_pairs.add(pair)
                unique_edges.append({
                    "source": src,
                    "target": tgt,
                    "relation": in_edge.get("relation", "prerequisite")
                })

    # Graph Degree Guard:
    # Enforce pre-flight validation: every node in state/knowledge_graph.json must satisfy in_degree + out_degree >= 1.
    # If an isolated node (degree 0) is detected, reject insertion or auto-link it to its canonical downstream target.
    degree_map: Dict[str, int] = {node_id: 0 for node_id in nodes_by_cid}
    for e in unique_edges:
        s = e.get("source")
        t = e.get("target")
        if s in degree_map:
            degree_map[s] += 1
        if t in degree_map:
            degree_map[t] += 1

    isolated_node_ids = [nid for nid, deg in degree_map.items() if deg == 0]
    if isolated_node_ids:
        curriculum_nodes = []
        active_sess = get_active_session()
        active_top = active_sess.get("active_topic")
        if active_top:
            t_dir = get_topic_notes_dir(active_top)
            if t_dir:
                m = load_topic_manifest(t_dir)
                if m:
                    curriculum_nodes = m.get("nodes", [])

        for nid in isolated_node_ids:
            linked = False
            # 1. Attempt downstream auto-link via curriculum prerequisites
            for c_node in curriculum_nodes:
                c_id = to_canonical_id(c_node.get("id", ""))
                c_prereqs = [to_canonical_id(p) for p in c_node.get("prerequisites", [])]
                if nid in c_prereqs and c_id in nodes_by_cid and c_id != nid:
                    pair = (nid, c_id)
                    if pair not in seen_edge_pairs:
                        seen_edge_pairs.add(pair)
                        unique_edges.append({
                            "source": nid,
                            "target": c_id,
                            "relation": "prerequisite"
                        })
                        degree_map[nid] = degree_map.get(nid, 0) + 1
                        degree_map[c_id] = degree_map.get(c_id, 0) + 1
                        linked = True
                        break

            # 2. Attempt upstream auto-link via curriculum prerequisites
            if not linked:
                for c_node in curriculum_nodes:
                    c_id = to_canonical_id(c_node.get("id", ""))
                    if c_id == nid:
                        for p in c_node.get("prerequisites", []):
                            p_cid = to_canonical_id(p)
                            if p_cid in nodes_by_cid and p_cid != nid:
                                pair = (p_cid, nid)
                                if pair not in seen_edge_pairs:
                                    seen_edge_pairs.add(pair)
                                    unique_edges.append({
                                        "source": p_cid,
                                        "target": nid,
                                        "relation": "prerequisite"
                                    })
                                    degree_map[nid] = degree_map.get(nid, 0) + 1
                                    degree_map[p_cid] = degree_map.get(p_cid, 0) + 1
                                    linked = True
                                    break
                        if linked:
                            break

            # 3. If degree is still 0, reject insertion of the isolated node (exempt diagnostic roots and mastered nodes)
            if degree_map.get(nid, 0) == 0:
                node_data = nodes_by_cid.get(nid, {})
                is_exempt = (
                    node_data.get("origin") == "diagnostic" or
                    str(node_data.get("status", "")).lower() == "mastered" or
                    nid in diagnostic_cids
                )
                if not is_exempt:
                    nodes_by_cid.pop(nid, None)

    updated_kg = {
        "nodes": list(nodes_by_cid.values()),
        "edges": unique_edges
    }
    updated_kg = validate_and_repair_graph_edges(updated_kg)
    updated_kg["edges"] = transitive_reduction(updated_kg["edges"])
    save_knowledge_graph(updated_kg)
    return {"status": "ok", "graph": updated_kg}

@app.get("/api/state")
def get_state() -> Dict[str, Any]:
    return load_state()


@app.post("/api/topic")
def set_topic(req: TopicRequest) -> Dict[str, Any]:
    topic_clean = req.topic.strip()
    active_sess = get_active_session()
    active_sess["active_topic"] = topic_clean
    active_sess["phase"] = "probing"
    active_sess["active_node_id"] = None
    if req.reference_scope is not None:
        active_sess["reference_scope"] = req.reference_scope
    save_active_session(active_sess)

    # Ensure topic directory and .diagnostic scratchpad exist
    t_dir = get_topic_notes_dir(topic_clean)
    if t_dir:
        t_dir.mkdir(parents=True, exist_ok=True)
        (t_dir / ".diagnostic").mkdir(parents=True, exist_ok=True)

    state = load_state()
    return {"status": "ok", "state": state}


@app.get("/api/quiz")
def get_quiz() -> Dict[str, Any]:
    active_sess = get_active_session()
    t_dir = get_active_topic_dir()
    phase = active_sess.get("phase", "idle")

    if t_dir:
        target_f = (t_dir / ".diagnostic" / "diagnostic_quiz.json") if phase == "probing" else (t_dir / ".session" / "quiz.json")
        if target_f.exists():
            try:
                raw_text = target_f.read_text(encoding="utf-8").strip()
                if raw_text:
                    return sanitize_and_normalize_quiz(raw_text)
            except Exception:
                pass

    return {"questions": []}


@app.post("/api/quiz")
def set_quiz(req: QuizRequest) -> Dict[str, Any]:
    delete_pause_flag()
    quiz_dict = {
        "question": req.question,
        "options": req.options,
        "correct_idx": req.correct_idx,
        "explanation": req.explanation
    }

    active_sess = get_active_session()
    t_dir = get_active_topic_dir()
    phase = active_sess.get("phase", "idle")

    if t_dir:
        if phase == "probing":
            target_dir = t_dir / ".diagnostic"
            target_f = target_dir / "diagnostic_quiz.json"
        else:
            target_dir = t_dir / ".session"
            target_f = target_dir / "quiz.json"
        target_dir.mkdir(parents=True, exist_ok=True)
        atomic_write_json(target_f, quiz_dict)

        # Clear answer in session if exists
        ans_f = t_dir / ".session" / "answer.json"
        if ans_f.exists():
            ans_f.unlink(missing_ok=True)

    state = load_state()
    state["active_quiz"] = quiz_dict
    state["latest_answer"] = None
    state["quiz_history"] = []
    save_state(state)
    return {"status": "ok", "state": state}


@app.post("/api/submit-quiz")
def submit_batch_quiz(req: BatchQuizSubmitRequest) -> Dict[str, Any]:
    delete_pause_flag()
    state = load_state()

    t_dir = get_active_topic_dir()
    active_sess = get_active_session()
    phase = active_sess.get("phase", "idle")

    active_quiz = None
    if t_dir:
        target_f = (t_dir / ".diagnostic" / "diagnostic_quiz.json") if phase == "probing" else (t_dir / ".session" / "quiz.json")
        if target_f.exists():
            try:
                content = target_f.read_text(encoding="utf-8").strip()
                if content:
                    active_quiz = sanitize_and_normalize_quiz(content)
            except Exception:
                pass

    if not active_quiz:
        active_quiz = state.get("active_quiz")

    if not active_quiz:
        raise HTTPException(status_code=400, detail="No active quiz available to answer.")

    timestamp = req.timestamp or datetime.now(timezone.utc).isoformat()
    node_id = req.node_id or state.get("active_node_id") or state.get("active_node") or active_quiz.get("node_id")

    if "questions" in active_quiz and isinstance(active_quiz["questions"], list):
        questions = active_quiz["questions"]
        rationales = []
        correct_count = 0
        for idx, q in enumerate(questions):
            sel_idx = req.answers[idx] if idx < len(req.answers) else -1
            target_idx = q.get("correct_index")
            if target_idx is None:
                target_idx = q.get("correct_idx", 0)
            is_correct = (sel_idx == target_idx)
            if is_correct:
                correct_count += 1
            rationales.append({
                "question_idx": idx,
                "selected_idx": sel_idx,
                "correct_idx": target_idx,
                "correct": is_correct,
                "question": q.get("question", ""),
                "explanation": q.get("explanation", "")
            })

        total = len(questions)
        score = (correct_count / total) if total > 0 else 0.0
        passed = (total > 0 and score >= 0.70)
        evaluation = {
            "node_id": node_id,
            "batch": True,
            "answers": req.answers,
            "results": rationales,
            "rationales": rationales,
            "correct_count": correct_count,
            "total": total,
            "score": score,
            "passed": passed,
            "correct": passed,
            "timestamp": timestamp
        }
    else:
        sel_idx = req.answers[0] if req.answers else -1
        target_idx = active_quiz.get("correct_index")
        if target_idx is None:
            target_idx = active_quiz.get("correct_idx", 0)
        is_correct = (sel_idx == target_idx)
        single_rationales = [{
            "question_idx": 0,
            "selected_idx": sel_idx,
            "correct_idx": target_idx,
            "correct": is_correct,
            "question": active_quiz.get("question", ""),
            "explanation": active_quiz.get("explanation", "")
        }]
        evaluation = {
            "node_id": node_id,
            "batch": False,
            "answers": req.answers,
            "results": single_rationales,
            "rationales": single_rationales,
            "selected_idx": sel_idx,
            "correct_idx": target_idx,
            "correct_count": 1 if is_correct else 0,
            "total": 1,
            "score": 1.0 if is_correct else 0.0,
            "correct": is_correct,
            "passed": is_correct,
            "question": active_quiz.get("question", ""),
            "explanation": active_quiz.get("explanation", ""),
            "timestamp": timestamp
        }

    # Write evaluation atomically strictly to topic .session/ (or .diagnostic/)
    if t_dir:
        if phase == "probing":
            diag_p = t_dir / ".diagnostic" / "baseline_passes.json"
            t_dir.mkdir(parents=True, exist_ok=True)
            (t_dir / ".diagnostic").mkdir(parents=True, exist_ok=True)
            atomic_write_json(diag_p, evaluation)
        sess_dir = t_dir / ".session"
        sess_dir.mkdir(parents=True, exist_ok=True)
        atomic_write_json(sess_dir / "answer.json", evaluation)

    state["latest_answer"] = evaluation
    state["quiz_history"] = [evaluation]
    save_state(state)

    return {"status": "ok", "evaluation": evaluation, "latest_answer": evaluation}


@app.post("/api/answer")
def submit_answer(req: AnswerRequest) -> Dict[str, Any]:
    delete_pause_flag()
    state = load_state()
    active_quiz = state.get("active_quiz")
    if not active_quiz:
        raise HTTPException(status_code=400, detail="No active quiz available to answer.")

    if "questions" in active_quiz and isinstance(active_quiz["questions"], list):
        q_idx = req.question_idx if req.question_idx is not None else 0
        questions = active_quiz["questions"]
        if q_idx < 0 or q_idx >= len(questions):
            raise HTTPException(status_code=400, detail="Question index out of bounds.")
        q = questions[q_idx]
        options = q.get("options", [])
        if req.selected_idx < 0 or req.selected_idx >= len(options):
            raise HTTPException(status_code=400, detail="Selected option index is out of bounds.")
        target_idx = q.get("correct_index", q.get("correct_idx"))
        is_correct = (req.selected_idx == target_idx)
        answer_record = {
            "question_idx": q_idx,
            "selected_idx": req.selected_idx,
            "correct": is_correct,
            "question": q.get("question", "")
        }
    else:
        options = active_quiz.get("options", [])
        if req.selected_idx < 0 or req.selected_idx >= len(options):
            raise HTTPException(status_code=400, detail="Selected option index is out of bounds.")
        target_idx = active_quiz.get("correct_index", active_quiz.get("correct_idx"))
        is_correct = (req.selected_idx == target_idx)
        answer_record = {
            "selected_idx": req.selected_idx,
            "correct": is_correct,
            "question": active_quiz.get("question", "")
        }

    t_dir = get_active_topic_dir()
    if t_dir:
        sess_dir = t_dir / ".session"
        sess_dir.mkdir(parents=True, exist_ok=True)
        atomic_write_json(sess_dir / "answer.json", answer_record)

    state["latest_answer"] = answer_record
    if "quiz_history" not in state or not isinstance(state["quiz_history"], list):
        state["quiz_history"] = []
    state["quiz_history"].append(answer_record)
    save_state(state)

    return {"status": "ok", "latest_answer": answer_record}


@app.get("/api/latest-answer")
def get_latest_answer() -> Dict[str, Any]:
    t_dir = get_active_topic_dir()
    if t_dir:
        active_sess = get_active_session()
        target_ans = (t_dir / ".diagnostic" / "baseline_passes.json") if active_sess.get("phase") == "probing" else (t_dir / ".session" / "answer.json")
        if target_ans.exists():
            try:
                data = json.loads(target_ans.read_text(encoding="utf-8"))
                return {"latest_answer": data}
            except Exception:
                pass
    state = load_state()
    return {"latest_answer": state.get("latest_answer")}


@app.post("/api/pause")
def pause_session() -> Dict[str, Any]:
    """Operational Guard 3: Atomically pause session, preserving .session/quiz.json intact."""
    create_pause_flag()

    active_sess = get_active_session()
    active_sess["phase"] = "PAUSED"
    save_active_session(active_sess)

    state = load_state()
    state["phase"] = "PAUSED"
    save_state(state)

    return {"status": "success", "message": "Session paused"}


@app.post("/api/dag")
def set_dag(req: DagRequest) -> Dict[str, Any]:
    state = load_state()
    state["dag_mermaid"] = req.mermaid
    state["phase"] = "teaching"
    save_state(state)
    return {"status": "ok", "state": state}


@app.post("/api/lesson")
def append_lesson(req: LessonRequest) -> Dict[str, Any]:
    state = load_state()
    state["lesson_markdown"] = (state.get("lesson_markdown") or "") + req.markdown_chunk
    save_state(state)
    return {"status": "ok", "state": state}


@app.get("/api/notes/{node_id}")
def get_node_note(node_id: str) -> Dict[str, Any]:
    clean_id = to_canonical_id(node_id)
    clean_norm = clean_id.replace("-", "")
    kg = load_knowledge_graph()
    kg_nodes = kg.get("nodes", [])
    kg_edges = kg.get("edges", [])

    node_meta = None
    for n in kg_nodes:
        nid = n.get("id", "")
        nlabel = n.get("label", "")
        if (nid == clean_id or 
            nid == node_id or 
            to_canonical_id(nlabel) == clean_id or 
            to_canonical_id(nlabel) == to_canonical_id(node_id) or
            clean_norm == nid.replace("-", "") or
            MERGE_MAP.get(clean_id) == nid or
            MERGE_MAP.get(nid) == clean_id or
            MERGE_MAP.get(to_canonical_id(node_id)) == nid):
            node_meta = n
            break

    label = node_meta.get("label", "") if node_meta else ""
    clean_label_str = clean_label(label).lower() if label else ""

    candidates = {
        node_id.lower(),
        clean_id.lower(),
        f"{node_id}.md".lower(),
        f"{clean_id}.md".lower(),
    }
    target_labels = set()
    if label:
        label_cid = to_canonical_id(label).lower()
        candidates.add(clean_label_str)
        candidates.add(label_cid)
        candidates.add(f"{label_cid}.md")
        target_labels.add(clean_label_str)
        target_labels.add(label.lower())
    if node_meta and node_meta.get("id"):
        m_id = str(node_meta["id"]).lower()
        candidates.add(m_id)
        candidates.add(f"{m_id}.md")
        m_cid = to_canonical_id(m_id).lower()
        candidates.add(m_cid)
        candidates.add(f"{m_cid}.md")
        target_labels.add(m_id)

    for k, v in MERGE_MAP.items():
        if clean_id in (k, v) or node_id.lower() in (k, v) or (node_meta and node_meta.get("id") in (k, v)):
            candidates.add(k.lower())
            candidates.add(f"{k.lower()}.md")
            candidates.add(v.lower())
            candidates.add(f"{v.lower()}.md")

    state = load_state()
    active_topic = state.get("topic")

    # Check active topic first if available
    candidate_topics = []
    if active_topic and active_topic != "Not Set":
        candidate_topics.append(active_topic)

    meta_topics = node_meta.get("topics", []) if node_meta else []
    for t in meta_topics:
        if t and t not in candidate_topics:
            candidate_topics.append(t)

    # A. Standalone files: check notes/<topic>/<concept_id>.md or notes/<concept_id>.md
    matched_file = None
    topic_dirs = []
    for t in candidate_topics:
        d = get_topic_notes_dir(t)
        if d.exists() and d.is_dir() and d not in topic_dirs:
            topic_dirs.append(d)

    for t_dir in topic_dirs:
        for c in candidates:
            c_name = c if c.endswith(".md") else f"{c}.md"
            cand_p = t_dir / c_name
            if cand_p.exists() and cand_p.is_file() and cand_p.name.lower() not in ("notes.md", "lesson_notes.md"):
                matched_file = cand_p
                break
        if matched_file:
            break

    if not matched_file:
        for c in candidates:
            c_name = c if c.endswith(".md") else f"{c}.md"
            cand_p = NOTES_DIR / c_name
            if cand_p.exists() and cand_p.is_file() and cand_p.name.lower() != "lesson_notes.md":
                matched_file = cand_p
                break

    if not matched_file:
        for t_dir in topic_dirs:
            for f in t_dir.glob("*.md"):
                if f.name.lower() in ("notes.md", "lesson_notes.md"):
                    continue
                try:
                    txt = f.read_text(encoding="utf-8")
                    fm = parse_frontmatter(txt)
                    fm_id = str(fm.get("id", "")).lower()
                    fm_title = str(fm.get("title", "")).lower()
                    if (fm_id and (fm_id in candidates or to_canonical_id(fm_id).lower() in candidates)) or \
                       (fm_title and (fm_title in candidates or to_canonical_id(fm_title).lower() in candidates)):
                        matched_file = f
                        break
                except Exception:
                    pass
            if matched_file:
                break

    if not matched_file and NOTES_DIR.exists():
        for root, _, files in os.walk(NOTES_DIR):
            for f in files:
                if not f.endswith(".md") or f.lower() in ("notes.md", "lesson_notes.md"):
                    continue
                p = Path(root) / f
                if f.lower() in candidates or p.stem.lower() in candidates:
                    matched_file = p
                    break
                try:
                    txt = p.read_text(encoding="utf-8")
                    fm = parse_frontmatter(txt)
                    fm_id = str(fm.get("id", "")).lower()
                    if fm_id and (fm_id in candidates or to_canonical_id(fm_id).lower() in candidates):
                        matched_file = p
                        break
                except Exception:
                    pass
            if matched_file:
                break

    if matched_file and matched_file.exists():
        content = matched_file.read_text(encoding="utf-8")
        fm = parse_frontmatter(content)
        origin = fm.get("origin")
        badge_label = fm.get("badge_label")
        if not origin and node_meta:
            origin = node_meta.get("origin")
            badge_label = badge_label or node_meta.get("badge_label")
        if not origin:
            origin = "diagnostic" if (node_meta and node_meta.get("origin") == "diagnostic") else "curriculum"
            badge_label = "Baseline Knowledge" if origin == "diagnostic" else "Curriculum Mastered"
        status = fm.get("status") or (node_meta.get("status") if node_meta else "mastered")
        parent_dir_topic = matched_file.parent.name if matched_file.parent != NOTES_DIR else ""
        return {
            "found": True,
            "content": content,
            "id": node_id,
            "origin": origin,
            "badge_label": badge_label,
            "status": status,
            "title": fm.get("title") or (node_meta.get("label") if node_meta else node_id),
            "topic": fm.get("topic") or (node_meta.get("topics", [""])[0] if node_meta and node_meta.get("topics") else (parent_dir_topic or (candidate_topics[0] if candidate_topics else "")))
        }

    # Helper for matching section headers
    def matches_section_header(raw_header: str) -> bool:
        h_clean = clean_label(raw_header).lower()
        h_cid = to_canonical_id(raw_header)
        h_clean_cid = to_canonical_id(h_clean)

        # 1. Exact clean label matching
        if clean_label_str and h_clean == clean_label_str:
            return True
        if h_clean in target_labels:
            return True
        if h_clean == clean_id.lower() or h_clean == node_id.lower():
            return True

        # 2. Canonical ID matching
        if h_cid == clean_id or h_clean_cid == clean_id:
            return True
        if h_cid in candidates or h_clean_cid in candidates:
            return True

        # 3. Bidirectional substring/containment
        if clean_id in h_cid or h_cid in clean_id:
            return True
        if clean_id in h_clean_cid or h_clean_cid in clean_id:
            return True
        if clean_norm in h_cid.replace("-", "") or h_cid.replace("-", "") in clean_norm:
            return True

        # 4. Merge map checks
        if MERGE_MAP.get(h_cid) == clean_id or MERGE_MAP.get(h_clean_cid) == clean_id:
            return True
        if MERGE_MAP.get(clean_id) == h_cid or MERGE_MAP.get(clean_id) == h_clean_cid:
            return True

        # 5. Baseline header matching
        if "baseline" in raw_header.lower():
            base_concept = clean_label(raw_header).lower()
            if (base_concept == node_id.lower() or
                to_canonical_id(base_concept) == clean_id or
                to_canonical_id(base_concept) in candidates or
                to_canonical_id(base_concept).replace("-", "") == clean_norm):
                return True

        return False

    # B. Topic Archives (notes/<topic_folder>/notes.md)
    if NOTES_DIR.exists():
        checked_archive_paths = set()
        topic_folders = []
        for t in candidate_topics:
            t_dir = get_topic_notes_dir(t)
            if t_dir.exists() and t_dir.is_dir():
                topic_folders.append(t_dir)
        for child in NOTES_DIR.iterdir():
            if child.is_dir() and child not in topic_folders:
                topic_folders.append(child)

        for tf in topic_folders:
            archive_file = tf / "notes.md"
            if archive_file.exists() and archive_file.is_file() and archive_file not in checked_archive_paths:
                checked_archive_paths.add(archive_file)
                try:
                    txt = archive_file.read_text(encoding="utf-8")
                    sections = re.split(r'\n(?=##\s+)', txt)
                    for sec in sections:
                        sec_strip = sec.strip()
                        if not sec_strip:
                            continue
                        lines = sec_strip.splitlines()
                        if not lines or not lines[0].startswith("##"):
                            continue
                        raw_header = re.sub(r'^##\s+', '', lines[0]).strip()
                        if matches_section_header(raw_header):
                            is_baseline = "baseline" in raw_header.lower()
                            origin = "diagnostic" if is_baseline else ((node_meta.get("origin") if node_meta else None) or "curriculum")
                            status = "mastered" if is_baseline else ((node_meta.get("status") if node_meta else None) or "mastered")
                            badge_label = "Baseline Knowledge" if is_baseline else ((node_meta.get("badge_label") if node_meta else None) or "Curriculum Mastered")
                            topic_name = (node_meta.get("topics", [""])[0] if node_meta and node_meta.get("topics") else tf.name)
                            return {
                                "found": True,
                                "content": sec_strip,
                                "id": node_id,
                                "origin": origin,
                                "badge_label": badge_label,
                                "status": status,
                                "title": clean_label(raw_header),
                                "topic": topic_name
                            }
                except Exception:
                    pass


    # D. Graph Fallback
    prereqs = []
    for edge in kg_edges:
        tgt = edge.get("target")
        if tgt == clean_id or tgt == node_id or (node_meta and tgt == node_meta.get("id")):
            src = edge.get("source")
            src_node = next((n for n in kg_nodes if n.get("id") == src or to_canonical_id(n.get("label", "")) == src), None)
            prereqs.append({
                "id": src,
                "label": src_node.get("label", src) if src_node else src,
                "status": src_node.get("status", "planned") if src_node else "planned"
            })

    status = node_meta.get("status", "planned") if node_meta else "planned"
    label = node_meta.get("label", node_id) if node_meta else node_id
    topic = (node_meta.get("topics", [""])[0] if node_meta and node_meta.get("topics") else (active_topic or ""))
    origin = node_meta.get("origin") if node_meta else ("planned" if status == "planned" else None)
    badge_label = node_meta.get("badge_label") if node_meta else ("Planned" if status == "planned" else None)

    return {
        "found": False,
        "status": status,
        "label": label,
        "topic": topic,
        "origin": origin,
        "badge_label": badge_label,
        "prerequisites": prereqs
    }



@app.get("/api/topics")
def get_topics() -> Dict[str, Any]:
    try:
        kg = load_knowledge_graph()
        kg_nodes = kg.get("nodes", [])

        topics_by_slug: Dict[str, Dict[str, Any]] = {}

        # 1. Discover from notes/ directory
        if NOTES_DIR.exists():
            for item in sorted(NOTES_DIR.iterdir()):
                if item.is_dir() and not item.name.startswith("."):
                    slug = sanitize_topic(item.name)
                    if slug in ("not-set", "default", ""):
                        continue
                    display_name = item.name.replace("-", " ").title()
                    completed_nodes = []
                    current_node = ""
                    updated_at = ""
                    total_count = 0
                    mastered_count = 0
                    active_node = "None"
                    domain = "General"
                    all_nodes = []

                    # Check manifest.json first
                    manifest_file = item / "manifest.json"
                    if manifest_file.exists():
                        try:
                            m_data = json.loads(manifest_file.read_text(encoding="utf-8"))
                            display_name = m_data.get("topic") or display_name
                            domain = m_data.get("domain") or "General"
                            m_nodes = m_data.get("nodes", [])
                            total_count = len(m_nodes)
                            all_nodes = [mn.get("title") or mn.get("label") or mn.get("id") for mn in m_nodes]
                            for mn in m_nodes:
                                st = str(mn.get("status", "")).lower()
                                title = mn.get("title") or mn.get("label") or mn.get("id")
                                if st in ("mastered", "completed"):
                                    mastered_count += 1
                                    completed_nodes.append(title)
                                elif st == "active" and active_node == "None":
                                    active_node = title
                                    current_node = title
                            mtime = manifest_file.stat().st_mtime
                            updated_at = datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat()
                        except Exception:
                            pass

                    # Fallback to session.json
                    session_file = item / ".session" / "session.json"
                    if not session_file.exists():
                        session_file = item / "session.json"
                    if session_file.exists():
                        try:
                            s_data = json.loads(session_file.read_text(encoding="utf-8"))
                            display_name = s_data.get("topic") or display_name
                            domain = s_data.get("domain") or domain or "General"
                            if not completed_nodes:
                                completed_nodes = s_data.get("completed_nodes") or []
                            if not current_node:
                                current_node = s_data.get("current_node") or ""
                            if not updated_at:
                                updated_at = s_data.get("timestamp") or ""
                        except Exception:
                            pass

                    if not updated_at:
                        notes_file = item / "notes.md"
                        target_f = manifest_file if manifest_file.exists() else (session_file if session_file.exists() else notes_file)
                        if target_f.exists():
                            mtime = target_f.stat().st_mtime
                            updated_at = datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat()
                        else:
                            updated_at = datetime.now(timezone.utc).isoformat()

                    if total_count == 0:
                        total_count = len(completed_nodes)
                        mastered_count = len(completed_nodes)

                    if active_node == "None":
                        active_node = current_node or "None"

                    status = "completed" if (total_count > 0 and mastered_count >= total_count) else "in_progress"

                    topics_by_slug[slug] = {
                        "name": display_name,
                        "slug": slug,
                        "domain": domain,
                        "status": status,
                        "nodes": all_nodes,
                        "completed_nodes": completed_nodes,
                        "current_node": current_node,
                        "updated_at": updated_at,
                        "total_nodes": total_count,
                        "mastered_nodes": mastered_count,
                        "active_node": active_node
                    }

        # 2. Discover from state/knowledge_graph.json
        kg_topic_nodes: Dict[str, List[Dict[str, Any]]] = {}
        for node in kg_nodes:
            node_topics = node.get("topics") or []
            if isinstance(node_topics, str):
                node_topics = [node_topics]
            for t_raw in node_topics:
                t_str = str(t_raw).strip()
                if not t_str:
                    continue
                t_slug = sanitize_topic(t_str)
                if t_slug in ("not-set", "default", ""):
                    continue
                if t_slug not in kg_topic_nodes:
                    kg_topic_nodes[t_slug] = []
                kg_topic_nodes[t_slug].append(node)

                if t_slug not in topics_by_slug:
                    topics_by_slug[t_slug] = {
                        "name": t_str,
                        "slug": t_slug,
                        "domain": "General",
                        "status": "in_progress",
                        "nodes": [],
                        "completed_nodes": [],
                        "current_node": "",
                        "updated_at": "",
                        "total_nodes": 0,
                        "mastered_nodes": 0,
                        "active_node": "None"
                    }

        # 3. Enrich if manifest didn't provide node counts
        for slug, t_data in topics_by_slug.items():
            if t_data.get("total_nodes", 0) == 0:
                nodes_for_topic = kg_topic_nodes.get(slug, [])
                if nodes_for_topic:
                    t_data["total_nodes"] = len(nodes_for_topic)
                    t_data["mastered_nodes"] = sum(1 for n in nodes_for_topic if str(n.get("status", "")).lower() == "mastered")
                    active_lbl = None
                    for n in nodes_for_topic:
                        if str(n.get("status", "")).lower() == "active":
                            active_lbl = n.get("label")
                            break
                    if not active_lbl and t_data.get("current_node"):
                        active_lbl = t_data.get("current_node")
                    if not active_lbl:
                        for n in nodes_for_topic:
                            if str(n.get("status", "")).lower() == "planned":
                                active_lbl = n.get("label")
                                break
                    t_data["active_node"] = active_lbl or t_data.get("current_node") or "None"
                    if not t_data.get("nodes"):
                        t_data["nodes"] = [n.get("label") or n.get("id") for n in nodes_for_topic]
                    tot = t_data["total_nodes"]
                    mast = t_data["mastered_nodes"]
                    t_data["status"] = "completed" if (tot > 0 and mast >= tot) else "in_progress"

        topic_list = list(topics_by_slug.values())
        topic_list.sort(key=lambda t: t.get("updated_at", ""), reverse=True)
        return {"topics": topic_list}
    except Exception:
        return {"topics": []}


@app.delete("/api/topics/{topic_name}")
def delete_topic(topic_name: str) -> Dict[str, Any]:
    cleaned = topic_name.strip()
    if not cleaned:
        raise HTTPException(status_code=400, detail="Topic name must not be empty.")

    target_dir = get_topic_notes_dir(cleaned)
    if not target_dir or not target_dir.exists():
        raise HTTPException(status_code=404, detail=f"Topic '{cleaned}' not found.")

    # 1. Purge notes/<topic_name>/ directory
    shutil.rmtree(target_dir, ignore_errors=True)

    # 2. Purge from state/knowledge_graph.json
    try:
        kg = load_knowledge_graph()
        slug = sanitize_topic(cleaned)
        modified_nodes = []
        for n in kg.get("nodes", []):
            topics = n.get("topics", [])
            if isinstance(topics, str):
                topics = [topics]
            new_topics = [t for t in topics if sanitize_topic(str(t)) != slug and str(t).strip().lower() != cleaned.lower()]
            if new_topics:
                n["topics"] = new_topics
                modified_nodes.append(n)
        valid_ids = {n["id"] for n in modified_nodes}
        modified_edges = [
            e for e in kg.get("edges", [])
            if e.get("source") in valid_ids and e.get("target") in valid_ids
        ]
        kg["nodes"] = modified_nodes
        kg["edges"] = modified_edges
        save_knowledge_graph(kg)
    except Exception:
        pass

    # 3. If currently active, reset session
    active_sess = get_active_session()
    current_topic = active_sess.get("active_topic", "")
    if current_topic and (sanitize_topic(current_topic) == sanitize_topic(cleaned) or current_topic.lower() == cleaned.lower()):
        reset_state()

    return {"status": "ok", "deleted": cleaned}


@app.post("/api/topics/load")
def load_topic(req: TopicRequest) -> Dict[str, Any]:
    """Load a saved topic into the active study workspace (restore notes + roadmap + update state)."""
    topic_name = req.topic.strip()
    if not topic_name:
        raise HTTPException(status_code=400, detail="Topic name must not be empty.")

    target_dir = get_topic_notes_dir(topic_name)
    if not target_dir or not target_dir.exists() or not target_dir.is_dir():
        available = [p.name for p in NOTES_DIR.iterdir() if p.is_dir()]
        raise HTTPException(
            status_code=404,
            detail=f"Topic directory for '{topic_name}' not found. Available topics: {available}"
        )
    sanitized = target_dir.name

    manifest = synthesize_manifest_for_topic(target_dir)

    restored_topic_name = manifest.get("topic") or topic_name
    restored_ref_scope = manifest.get("reference_scope") or {"collection": "general", "tags": []}

    # Find active node
    active_node = ""
    active_node_id = ""
    nodes = manifest.get("nodes", [])
    for n in nodes:
        st = str(n.get("status", "")).lower()
        if st in ("active", "in_progress"):
            active_node = n.get("title") or n.get("label") or n.get("id")
            active_node_id = n.get("id")
            break
    if not active_node:
        for n in nodes:
            st = str(n.get("status", "")).lower()
            if st not in ("mastered", "completed"):
                active_node = n.get("title") or n.get("label") or n.get("id")
                active_node_id = n.get("id")
                break
    if not active_node and nodes:
        active_node = nodes[-1].get("title") or nodes[-1].get("label") or nodes[-1].get("id")
        active_node_id = nodes[-1].get("id")

    req_mode = getattr(req, "mode", "study") or "study"
    phase = "reading" if req_mode == "read" else "teaching"

    # Update active session
    active_sess = get_active_session()
    active_sess["active_topic"] = restored_topic_name
    active_sess["phase"] = phase
    active_sess["active_node_id"] = active_node_id
    active_sess["reference_scope"] = restored_ref_scope
    save_active_session(active_sess)

    # Compile Mermaid DAG dynamically from manifest
    compiled_dag = compile_mermaid_dag(manifest)

    # Restore lesson notes: Guarantee restored_notes loads markdown from notes/<topic>/<active_node_id>.md
    restored_notes = ""
    cand_note_files = []
    if active_node_id:
        cand_note_files.append(target_dir / f"{active_node_id}.md")
        cand_note_files.append(target_dir / f"{to_canonical_id(active_node_id)}.md")
    if active_node:
        cand_note_files.append(target_dir / f"{to_canonical_id(active_node)}.md")
    cand_note_files.append(target_dir / "notes.md")

    for cnf in cand_note_files:
        if cnf.exists() and cnf.is_file():
            try:
                restored_notes = cnf.read_text(encoding="utf-8")
                if restored_notes.strip():
                    break
            except Exception:
                pass

    if not restored_notes.strip():
        md_files = sorted([f for f in target_dir.glob("*.md") if f.is_file() and not f.name.startswith(".")])
        if md_files:
            try:
                restored_notes = md_files[0].read_text(encoding="utf-8")
            except Exception:
                pass

    # Purge any transient .session/ answer or quiz if starting anew in study mode
    if req_mode != "read":
        sess_dir = target_dir / ".session"
        if sess_dir.exists():
            (sess_dir / "answer.json").unlink(missing_ok=True)

    state_payload = {
        "status": "active",
        "session_active": True,
        "topic": restored_topic_name,
        "phase": phase,
        "active_node": active_node,
        "active_node_id": active_node_id,
        "notes": restored_notes,
        "lesson_markdown": restored_notes,
        "manifest": manifest,
        "quiz": None,
        "dag_mermaid": compiled_dag,
        "reference_scope": restored_ref_scope
    }
    save_state(state_payload)

    return {
        "success": True,
        "state": state_payload
    }


@app.post("/api/archive")
def archive_topic(req: Optional[ArchiveRequest] = None) -> Dict[str, Any]:
    topic_name = str(req.topic or "").strip() if req and req.topic else ""
    reference_scope = None
    if not topic_name:
        active_sess = get_active_session()
        topic_name = str(active_sess.get("active_topic") or "").strip()
        reference_scope = active_sess.get("reference_scope")

    if not topic_name:
        reset_state()
        return {"status": "skipped", "message": "Cannot archive empty or not-set topic"}

    target_dir = get_topic_notes_dir(topic_name)
    if not target_dir:
        reset_state()
        return {"status": "skipped", "message": "Cannot archive empty or not-set topic"}
    target_dir.mkdir(parents=True, exist_ok=True)
    sanitized = target_dir.name

    # Purge .session directory
    sess_dir = target_dir / ".session"
    if sess_dir.exists():
        shutil.rmtree(sess_dir, ignore_errors=True)

    # Extract completed nodes and current node from manifest
    manifest = load_topic_manifest(target_dir)
    completed_nodes: List[str] = []
    current_node = ""
    if manifest:
        for n in manifest.get("nodes", []):
            st = str(n.get("status", "")).lower()
            if st in ("completed", "mastered"):
                completed_nodes.append(n.get("title") or n.get("label") or n.get("id"))
            elif st == "active" and not current_node:
                current_node = n.get("title") or n.get("label") or n.get("id")

    session_data = {
        "topic": topic_name,
        "sanitized_topic": sanitized,
        "completed_nodes": completed_nodes,
        "current_node": current_node,
        "reference_scope": reference_scope,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }
    session_file = target_dir / "session.json"
    with open(session_file, "w", encoding="utf-8") as f:
        json.dump(session_data, f, indent=2, ensure_ascii=False)

    reset_state()
    return {"status": "ok", "archive_dir": str(target_dir), "session": session_data}


@app.post("/api/restore")
def restore_topic(req: RestoreRequest) -> Dict[str, Any]:
    topic_name = req.topic.strip()
    if not topic_name:
        raise HTTPException(status_code=400, detail="Topic name must not be empty.")

    target_dir = get_topic_notes_dir(topic_name)
    if not target_dir or not target_dir.exists() or not target_dir.is_dir():
        available = [p.name for p in NOTES_DIR.iterdir() if p.is_dir()]
        raise HTTPException(
            status_code=404,
            detail=f"Topic archive '{topic_name}' not found. Available topics: {available}"
        )

    load_res = load_topic(TopicRequest(topic=topic_name, mode="study"))
    session_file = target_dir / "session.json"
    session_data = {}
    if session_file.exists():
        try:
            session_data = json.loads(session_file.read_text(encoding="utf-8"))
        except Exception:
            pass
    if not session_data:
        session_data = {
            "topic": topic_name,
            "completed_nodes": [],
            "current_node": load_res.get("state", {}).get("active_node", ""),
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
    return session_data


@app.post("/api/topics/discard")
def discard_topic(req: DiscardTopicRequest) -> Dict[str, Any]:
    topic_name = req.topic.strip()
    if not topic_name:
        raise HTTPException(status_code=400, detail="Topic name must not be empty.")

    target_dir = get_topic_notes_dir(topic_name)
    if target_dir and target_dir.exists() and target_dir.is_dir():
        session_file = target_dir / "session.json"
        if session_file.exists():
            session_file.unlink(missing_ok=True)

    # If current state matches discarded topic, reset state
    state = load_state()
    active_top = state.get("topic", "")
    if active_top and (active_top == topic_name or sanitize_topic(active_top) == sanitize_topic(topic_name)):
        return reset_state()

    return {"status": "ok", "discarded": topic_name}


@app.post("/api/reset")
def reset_state() -> Dict[str, Any]:
    delete_pause_flag()

    # Purge .session/ directory in active topic vault
    active_sess = get_active_session()
    active_topic = active_sess.get("active_topic")
    if active_topic:
        top_dir = get_active_topic_dir()
        if top_dir and (top_dir / ".session").exists():
            shutil.rmtree(top_dir / ".session", ignore_errors=True)

    # Reset active_session.json
    save_active_session({
        "active_topic": None,
        "phase": "idle",
        "active_node_id": None,
        "reference_scope": {"collection": "general", "tags": []}
    })

    blank_state = {
        "session_active": False,
        "topic": None,
        "status": "standby",
        "phase": "idle",
        "active_node": None,
        "active_node_id": None,
        "current_node": "",
        "notes": "",
        "lesson_markdown": "",
        "dag_mermaid": "graph TD\n",
        "quiz": None,
        "active_quiz": None,
        "latest_answer": None,
        "quiz_history": []
    }

    return {
        "success": True,
        "status": "ok",
        "state": blank_state
    }


@app.post("/api/shutdown")
@app.post("/api/kill")
def shutdown_server():
    try:
        reset_state()
    except Exception:
        pass
    def kill():
        import time
        time.sleep(0.5)
        os.kill(os.getpid(), signal.SIGTERM)
    threading.Thread(target=kill).start()
    return {"status": "shutting_down"}


# Static Files Mount & Root Route
STATIC_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
def serve_index():
    if not INDEX_FILE.exists():
        raise HTTPException(status_code=404, detail="Frontend index.html not found.")
    return FileResponse(str(INDEX_FILE))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="127.0.0.1", port=8000, reload=False, access_log=False)

