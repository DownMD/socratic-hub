import json
import os
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
STATE_FILE = STATE_DIR / "state.json"
STATE_JSON_FILE = STATE_FILE
NOTES_DIR = BASE_DIR / "notes"
NOTES_FILE = NOTES_DIR / "lesson_notes.md"
STATIC_DIR = BASE_DIR / "static"
INDEX_FILE = STATIC_DIR / "index.html"
TOPIC_FILE = STATE_DIR / "topic.json"
QUIZ_FILE = STATE_DIR / "quiz.json"
ROADMAP_FILE = STATE_DIR / "roadmap.mmd"
ANSWER_FILE = STATE_DIR / "answer.json"
KNOWLEDGE_GRAPH_FILE = STATE_DIR / "knowledge_graph.json"
PAUSE_FLAG = STATE_DIR / "pause.flag"
CURRICULUM_FILE = STATE_DIR / "curriculum.json"

DEFAULT_STATE: Dict[str, Any] = {
    "session_active": False,
    "topic": "Not Set",
    "phase": "IDLE",
    "active_node": None,
    "active_node_id": None,
    "current_node": "",
    "notes": "",
    "lesson_markdown": "",
    "quiz": None,
    "active_quiz": None,
    "dag_mermaid": "",
    "latest_answer": None,
    "quiz_history": [],
    "reference_scope": None
}

DEFAULT_TOPIC_SKELETON: Dict[str, Any] = {
    "topic": "",
    "phase": "idle",
    "active_node_id": None,
    "active_node": None,
    "reference_scope": {"collection": "general", "tags": []}
}

DEFAULT_CURRICULUM_SKELETON: Dict[str, Any] = {
    "topic": "",
    "nodes": []
}

DEFAULT_KNOWLEDGE_GRAPH_SKELETON: Dict[str, Any] = {
    "nodes": [],
    "links": []
}

DEFAULT_ROADMAP_SKELETON: str = """graph TD
  classDef completed stroke:#22c55e,stroke-width:2px;
  classDef active stroke:#38bdf8,stroke-width:3px;
  classDef pending stroke:#475569,stroke-width:1px;
  classDef mastered stroke:#22c55e,stroke-width:2px;
"""

DEFAULT_LESSON_NOTES_PLACEHOLDER: str = "<!-- Active lesson notes will appear here -->\n"


def ensure_state_skeletons() -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    NOTES_DIR.mkdir(parents=True, exist_ok=True)

    if not TOPIC_FILE.exists() or TOPIC_FILE.stat().st_size == 0 or not TOPIC_FILE.read_text(encoding="utf-8").strip():
        with open(TOPIC_FILE, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_TOPIC_SKELETON, f, indent=2)

    if not CURRICULUM_FILE.exists() or CURRICULUM_FILE.stat().st_size == 0 or not CURRICULUM_FILE.read_text(encoding="utf-8").strip():
        with open(CURRICULUM_FILE, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_CURRICULUM_SKELETON, f, indent=2)

    if not KNOWLEDGE_GRAPH_FILE.exists() or KNOWLEDGE_GRAPH_FILE.stat().st_size == 0 or not KNOWLEDGE_GRAPH_FILE.read_text(encoding="utf-8").strip():
        with open(KNOWLEDGE_GRAPH_FILE, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_KNOWLEDGE_GRAPH_SKELETON, f, indent=2)

    if not ROADMAP_FILE.exists() or ROADMAP_FILE.stat().st_size == 0 or not ROADMAP_FILE.read_text(encoding="utf-8").strip():
        with open(ROADMAP_FILE, "w", encoding="utf-8") as f:
            f.write(DEFAULT_ROADMAP_SKELETON)

    if not NOTES_FILE.exists() or NOTES_FILE.stat().st_size == 0 or not NOTES_FILE.read_text(encoding="utf-8").strip():
        with open(NOTES_FILE, "w", encoding="utf-8") as f:
            f.write(DEFAULT_LESSON_NOTES_PLACEHOLDER)



def safe_replace(src: Path, dst: Path, max_retries: int = 5) -> None:
    for attempt in range(max_retries):
        try:
            src.replace(dst)
            return
        except (PermissionError, OSError):
            if attempt == max_retries - 1:
                raise
            time.sleep(0.05 * pow(2, attempt))


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


def parse_frontmatter(content: str) -> Dict[str, Any]:
    fm_match = re.match(r'^---\s*\r?\n([\s\S]*?)\r?\n---\s*\r?\n', content)
    if not fm_match:
        return {}
    fm_text = fm_match.group(1)
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
    return data


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
                        node_defs = re.findall(r'(\w+)\s*\["?([^"\]]+)"?\]', r_text)
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

                        edge_defs = re.findall(r'(\w+)(?:\[[^\]]*\])?\s*-->\s*(\w+)', r_text)
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
    save_knowledge_graph(kg)
    return kg
def sanitize_and_normalize_quiz(raw_text: str) -> Dict[str, Any]:
    raw_text = raw_text.strip()
    if not raw_text:
        return {"questions": []}

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

            if not item.get("id"):
                item["id"] = f"q{idx + 1}"

            norm_questions.append(item)

    payload["questions"] = norm_questions
    return payload


def load_state() -> Dict[str, Any]:
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = DEFAULT_STATE.copy()
    else:
        data = DEFAULT_STATE.copy()

    # Ensure all default keys exist
    for k, v in DEFAULT_STATE.items():
        if k not in data:
            data[k] = v

    state_dirty = False
    if TOPIC_FILE.exists():
        try:
            with open(TOPIC_FILE, "r", encoding="utf-8") as f:
                t_data = json.load(f)
                if "topic" in t_data and data.get("topic") != t_data["topic"]:
                    data["topic"] = t_data["topic"] or "Not Set"
                    state_dirty = True
                if "phase" in t_data and data.get("phase") != t_data["phase"]:
                    data["phase"] = t_data["phase"] or "IDLE"
                    state_dirty = True
                if "reference_scope" in t_data and data.get("reference_scope") != t_data["reference_scope"]:
                    data["reference_scope"] = t_data["reference_scope"]
                    state_dirty = True
                if "active_node" in t_data and data.get("active_node") != t_data["active_node"]:
                    data["active_node"] = t_data["active_node"]
                    data["current_node"] = t_data["active_node"]
                    state_dirty = True
                if "active_node_id" in t_data and data.get("active_node_id") != t_data["active_node_id"]:
                    data["active_node_id"] = t_data["active_node_id"]
                    state_dirty = True
        except Exception:
            pass

    if ROADMAP_FILE.exists():
        try:
            with open(ROADMAP_FILE, "r", encoding="utf-8") as f:
                m_content = f.read()
                if data.get("dag_mermaid") != m_content:
                    data["dag_mermaid"] = m_content
                    state_dirty = True
        except Exception:
            pass

    if NOTES_FILE.exists():
        try:
            with open(NOTES_FILE, "r", encoding="utf-8") as f:
                n_content = f.read()
                if data.get("lesson_markdown") != n_content:
                    data["lesson_markdown"] = n_content
                    data["notes"] = n_content
                    state_dirty = True
        except Exception:
            pass

    if QUIZ_FILE.exists():
        try:
            raw_q = QUIZ_FILE.read_text(encoding="utf-8").strip()
            if not raw_q:
                if data.get("active_quiz") is not None:
                    data["active_quiz"] = None
                    data["quiz"] = None
                    state_dirty = True
            else:
                q_data = sanitize_and_normalize_quiz(raw_q)
                if not q_data or not q_data.get("questions"):
                    if data.get("active_quiz") is not None:
                        data["active_quiz"] = None
                        data["quiz"] = None
                        state_dirty = True
                else:
                    old_q = data.get("active_quiz") or {}
                    if q_data != old_q:
                        delete_pause_flag()
                        data["active_quiz"] = q_data
                        data["quiz"] = q_data
                        data["latest_answer"] = None
                        data["quiz_history"] = []
                        if ANSWER_FILE.exists():
                            ANSWER_FILE.unlink(missing_ok=True)
                        state_dirty = True
                    else:
                        data["active_quiz"] = q_data
                        data["quiz"] = q_data
        except Exception:
            pass

    is_active = bool(
        data.get("topic") and
        data.get("topic") not in ("", "Not Set") and
        str(data.get("phase", "")).lower() not in ("idle", "")
    )
    if data.get("session_active") != is_active:
        data["session_active"] = is_active
        state_dirty = True

    active_lbl = data.get("active_node") or data.get("current_node") or None
    data["active_node"] = active_lbl
    data["current_node"] = active_lbl or ""
    data["notes"] = data.get("notes") or data.get("lesson_markdown") or ""
    data["lesson_markdown"] = data["notes"]
    data["quiz"] = data.get("quiz") or data.get("active_quiz")
    data["active_quiz"] = data["quiz"]

    if state_dirty:
        save_state(data)

    return data


def save_state(state: Dict[str, Any]) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    temp_file = STATE_FILE.with_suffix(".tmp")
    is_idle = (state.get("session_active") is False) or (state.get("topic") in ("Not Set", "") and str(state.get("phase", "")).upper() == "IDLE")
    if is_idle:
        payload = {
            "session_active": False,
            "topic": "Not Set",
            "phase": "IDLE",
            "active_node": None,
            "notes": "",
            "quiz": None
        }
    else:
        payload = state

    with open(temp_file, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    safe_replace(temp_file, STATE_FILE)


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
    """Purge quiz_history and latest_answer on startup and ensure state skeletons."""
    ensure_state_skeletons()
    state = load_state()
    state["quiz_history"] = []
    state["latest_answer"] = None
    save_state(state)


# Pydantic Request Models
class TopicRequest(BaseModel):
    topic: str
    reference_scope: Optional[Dict[str, Any]] = None


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
        if CURRICULUM_FILE.exists():
            try:
                with open(CURRICULUM_FILE, "r", encoding="utf-8") as f:
                    c_data = json.load(f)
                    curriculum_nodes = c_data.get("nodes", [])
            except Exception:
                pass

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
    save_knowledge_graph(updated_kg)
    return {"status": "ok", "graph": updated_kg}

@app.get("/api/state")
def get_state() -> Dict[str, Any]:
    return load_state()


@app.post("/api/topic")
def set_topic(req: TopicRequest) -> Dict[str, Any]:
    state = load_state()
    state["topic"] = req.topic
    state["phase"] = "probing"
    if req.reference_scope is not None:
        state["reference_scope"] = req.reference_scope
    save_state(state)
    topic_payload = {"topic": req.topic, "phase": "probing"}
    if req.reference_scope is not None:
        topic_payload["reference_scope"] = req.reference_scope
    TOPIC_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(TOPIC_FILE, "w", encoding="utf-8") as f:
        json.dump(topic_payload, f, indent=2)
    return {"status": "ok", "state": state}


@app.get("/api/quiz")
def get_quiz() -> Dict[str, Any]:
    if not QUIZ_FILE.exists():
        return {"questions": []}
    try:
        raw_text = QUIZ_FILE.read_text(encoding="utf-8").strip()
        if not raw_text:
            return {"questions": []}
        return sanitize_and_normalize_quiz(raw_text)
    except Exception:
        return {"questions": []}


@app.post("/api/quiz")
def set_quiz(req: QuizRequest) -> Dict[str, Any]:
    delete_pause_flag()
    state = load_state()
    state["active_quiz"] = {
        "question": req.question,
        "options": req.options,
        "correct_idx": req.correct_idx,
        "explanation": req.explanation
    }
    state["latest_answer"] = None
    state["quiz_history"] = []
    save_state(state)
    if ANSWER_FILE.exists():
        ANSWER_FILE.unlink(missing_ok=True)
    return {"status": "ok", "state": state}


@app.post("/api/submit-quiz")
def submit_batch_quiz(req: BatchQuizSubmitRequest) -> Dict[str, Any]:
    delete_pause_flag()
    state = load_state()
    active_quiz = state.get("active_quiz")
    if not active_quiz and QUIZ_FILE.exists():
        try:
            content = QUIZ_FILE.read_text(encoding="utf-8").strip()
            if content:
                active_quiz = sanitize_and_normalize_quiz(content)
        except Exception:
            pass

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

    # Flush in-memory buffers
    state["latest_answer"] = evaluation
    state["quiz_history"] = [evaluation]
    save_state(state)

    # Purge stale buffers and atomically write evaluation payload to state/answer.json (.tmp -> replace)
    ANSWER_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp_answer = ANSWER_FILE.with_name(f"{ANSWER_FILE.name}.tmp")
    with open(tmp_answer, "w", encoding="utf-8") as f:
        json.dump(evaluation, f, indent=2, ensure_ascii=False)
    safe_replace(tmp_answer, ANSWER_FILE)

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

    state["latest_answer"] = answer_record
    if "quiz_history" not in state or not isinstance(state["quiz_history"], list):
        state["quiz_history"] = []
    state["quiz_history"].append(answer_record)
    save_state(state)

    ANSWER_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp_answer = ANSWER_FILE.with_name(f"{ANSWER_FILE.name}.tmp")
    with open(tmp_answer, "w", encoding="utf-8") as f:
        json.dump(answer_record, f, indent=2)
    safe_replace(tmp_answer, ANSWER_FILE)

    return {"status": "ok", "latest_answer": answer_record}


@app.get("/api/latest-answer")
def get_latest_answer() -> Dict[str, Any]:
    state = load_state()
    return {"latest_answer": state.get("latest_answer")}


@app.post("/api/pause")
def pause_session() -> Dict[str, Any]:
    create_pause_flag()

    topic_data = {}
    if TOPIC_FILE.exists():
        try:
            with open(TOPIC_FILE, "r", encoding="utf-8") as f:
                topic_data = json.load(f)
        except Exception:
            topic_data = {}
    topic_data["phase"] = "PAUSED"
    TOPIC_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp_topic = TOPIC_FILE.with_name(f"{TOPIC_FILE.name}.tmp")
    with open(tmp_topic, "w", encoding="utf-8") as f:
        json.dump(topic_data, f, indent=2)
    safe_replace(tmp_topic, TOPIC_FILE)

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

    # Append directly to notes/lesson_notes.md
    NOTES_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(NOTES_FILE, "a", encoding="utf-8") as f:
        f.write(req.markdown_chunk)

    return {"status": "ok", "state": state}


@app.get("/api/notes/{node_id}")
def get_node_note(node_id: str) -> Dict[str, Any]:
    clean_id = to_canonical_id(node_id)
    kg = load_knowledge_graph()
    kg_nodes = kg.get("nodes", [])
    kg_edges = kg.get("edges", [])

    node_meta = None
    for n in kg_nodes:
        if n.get("id") == clean_id or to_canonical_id(n.get("label", "")) == clean_id or n.get("id") == node_id:
            node_meta = n
            break

    candidates = {
        node_id.lower(),
        clean_id.lower(),
        f"{node_id}.md".lower(),
        f"{clean_id}.md".lower(),
    }
    if node_meta:
        if node_meta.get("label"):
            label_slug = to_canonical_id(node_meta["label"]).lower()
            candidates.add(label_slug)
            candidates.add(f"{label_slug}.md")
        if node_meta.get("id"):
            m_id = str(node_meta["id"]).lower()
            candidates.add(m_id)
            candidates.add(f"{m_id}.md")
            m_cid = to_canonical_id(m_id).lower()
            candidates.add(m_cid)
            candidates.add(f"{m_cid}.md")

    state = load_state()
    active_topic = state.get("topic")
    if (not active_topic or active_topic == "Not Set") and TOPIC_FILE.exists():
        try:
            with open(TOPIC_FILE, "r", encoding="utf-8") as f:
                t_data = json.load(f)
                active_topic = t_data.get("topic") or active_topic
        except Exception:
            pass

    # 1. Check if notes/<topic>/{node_id}.md exists.
    matched_file = None
    topic_dirs = []
    t_dir = get_topic_notes_dir(active_topic) if active_topic else None
    if t_dir and t_dir.exists() and t_dir.is_dir():
        topic_dirs.append(t_dir)

    for t_dir in topic_dirs:
        if t_dir.exists() and t_dir.is_dir():
            direct_candidates = [
                t_dir / f"{node_id}.md",
                t_dir / f"{clean_id}.md",
                t_dir / node_id,
                t_dir / clean_id
            ]
            for dc in direct_candidates:
                if dc.exists() and dc.is_file():
                    matched_file = dc
                    break
            if matched_file:
                break

            for f in t_dir.glob("*.md"):
                f_lower = f.name.lower()
                stem_lower = f.stem.lower()
                if f_lower in candidates or stem_lower in candidates:
                    matched_file = f
                    break
                try:
                    txt = f.read_text(encoding="utf-8")
                    fm = parse_frontmatter(txt)
                    fm_id = str(fm.get("id", "")).lower()
                    if fm_id and (fm_id in candidates or to_canonical_id(fm_id).lower() in candidates):
                        matched_file = f
                        break
                except Exception:
                    pass
            if matched_file:
                break

    # If not found in active topic directory, search other topic directories in NOTES_DIR
    if not matched_file and NOTES_DIR.exists():
        for root, _, files in os.walk(NOTES_DIR):
            for f in files:
                if not f.endswith(".md") or f.lower() == "lesson_notes.md":
                    continue
                f_lower = f.lower()
                stem_lower = Path(f).stem.lower()
                if f_lower in candidates or stem_lower in candidates:
                    matched_file = Path(root) / f
                    break
                try:
                    p = Path(root) / f
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
        return {
            "found": True,
            "content": content,
            "id": node_id,
            "origin": origin,
            "badge_label": badge_label,
            "status": status,
            "title": fm.get("title") or (node_meta.get("label") if node_meta else node_id),
            "topic": fm.get("topic") or (node_meta.get("topics", [""])[0] if node_meta and node_meta.get("topics") else (active_topic or ""))
        }

    # 2. Fallback: inspect notes/lesson_notes.md directly and extract matching section
    if NOTES_FILE.exists():
        try:
            txt = NOTES_FILE.read_text(encoding="utf-8")
            target_labels = set()
            if node_meta and node_meta.get("label"):
                target_labels.add(clean_label(node_meta["label"]).lower())
                target_labels.add(str(node_meta["label"]).lower())
            if node_meta and node_meta.get("id"):
                target_labels.add(str(node_meta["id"]).lower())

            curr_node_title = None
            if CURRICULUM_FILE.exists():
                try:
                    curr_data = json.loads(CURRICULUM_FILE.read_text(encoding="utf-8"))
                    for cn in curr_data.get("nodes", []):
                        cn_id = str(cn.get("id", "")).lower()
                        if cn_id == node_id.lower() or cn_id == clean_id.lower() or to_canonical_id(cn_id) == clean_id.lower():
                            if cn.get("title"):
                                curr_node_title = cn.get("title")
                                target_labels.add(clean_label(cn["title"]).lower())
                                target_labels.add(cn["title"].lower())
                except Exception:
                    pass

            node_num_match = re.search(r'node[-_]?(\d+)|\b(\d+)\b', node_id, re.IGNORECASE)
            node_num = int(node_num_match.group(1) or node_num_match.group(2)) if node_num_match else None

            sections = re.split(r'\n(?=##\s+)', txt)
            for sec in sections:
                sec_strip = sec.strip()
                if not sec_strip:
                    continue
                lines = sec_strip.splitlines()
                if not lines or not lines[0].startswith("##"):
                    continue

                raw_header = re.sub(r'^##\s+', '', lines[0]).strip()
                header_clean = clean_label(raw_header).lower()
                header_cid = to_canonical_id(raw_header)
                header_clean_cid = to_canonical_id(header_clean)

                sec_num_match = re.search(r'node\s*(\d+)|\b(\d+)[\.\:]', raw_header, re.IGNORECASE)
                sec_num = int(sec_num_match.group(1) or sec_num_match.group(2)) if sec_num_match else None

                match_found = False
                if header_clean in target_labels or header_clean == clean_id.lower() or header_clean == node_id.lower():
                    match_found = True
                elif header_cid in candidates or header_cid == clean_id or header_clean_cid in candidates or header_clean_cid == clean_id:
                    match_found = True
                elif node_num is not None and sec_num is not None and node_num == sec_num:
                    match_found = True
                elif curr_node_title and (clean_label(curr_node_title).lower() in header_clean or header_clean in clean_label(curr_node_title).lower()):
                    match_found = True
                elif "baseline" in raw_header.lower():
                    base_concept = clean_label(raw_header).lower()
                    if base_concept == node_id.lower() or to_canonical_id(base_concept) == clean_id:
                        match_found = True

                if match_found:
                    is_baseline = "baseline" in raw_header.lower()
                    origin = "diagnostic" if is_baseline else ((node_meta.get("origin") if node_meta else None) or "curriculum")
                    is_active = (
                        clean_id == to_canonical_id(state.get("active_node_id", "")) or
                        clean_id == to_canonical_id(state.get("active_node", "")) or
                        (node_num is not None and sec_num is not None and node_num == sec_num and state.get("phase", "").lower() == "teaching")
                    )
                    status = "mastered" if is_baseline else ((node_meta.get("status") if node_meta else None) or ("active" if is_active else "mastered"))
                    badge_label = "Baseline Knowledge" if is_baseline else ((node_meta.get("badge_label") if node_meta else None) or ("Active Lesson" if status == "active" else "Curriculum Mastered"))
                    return {
                        "found": True,
                        "content": sec_strip,
                        "id": node_id,
                        "origin": origin,
                        "badge_label": badge_label,
                        "status": status,
                        "title": clean_label(raw_header),
                        "topic": (node_meta.get("topics", [""])[0] if node_meta and node_meta.get("topics") else (active_topic or ""))
                    }
        except Exception:
            pass

    # 3. If file does not exist: inspect state/knowledge_graph.json to find node metadata
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
        # Load knowledge graph for node count and topic enrichment
        kg = load_knowledge_graph()
        kg_nodes = kg.get("nodes", [])

        # Accumulator for unique topics keyed by slug
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

                    session_file = item / "session.json"
                    if session_file.exists():
                        try:
                            with open(session_file, "r", encoding="utf-8") as f:
                                s_data = json.load(f)
                                display_name = s_data.get("topic") or display_name
                                completed_nodes = s_data.get("completed_nodes") or []
                                current_node = s_data.get("current_node") or ""
                                updated_at = s_data.get("timestamp") or ""
                        except Exception:
                            pass

                    if not updated_at:
                        notes_file = item / "notes.md"
                        target_f = session_file if session_file.exists() else notes_file
                        if target_f.exists():
                            mtime = target_f.stat().st_mtime
                            updated_at = datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat()
                        else:
                            updated_at = datetime.now(timezone.utc).isoformat()

                    topics_by_slug[slug] = {
                        "name": display_name,
                        "slug": slug,
                        "completed_nodes": completed_nodes,
                        "current_node": current_node,
                        "updated_at": updated_at,
                        "total_nodes": len(completed_nodes),
                        "mastered_nodes": len(completed_nodes),
                        "active_node": current_node or "None"
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
                        "completed_nodes": [],
                        "current_node": "",
                        "updated_at": "",
                        "total_nodes": 0,
                        "mastered_nodes": 0,
                        "active_node": "None"
                    }

        # 3. Calculate statistics and active node for all topics
        for slug, t_data in topics_by_slug.items():
            nodes_for_topic = kg_topic_nodes.get(slug, [])
            if nodes_for_topic:
                total_count = len(nodes_for_topic)
                mastered_count = sum(1 for n in nodes_for_topic if str(n.get("status", "")).lower() == "mastered")

                # Find active node:
                # 1. Any node with status == 'active'
                # 2. Match session.json current_node if present
                # 3. First node with status == 'planned'
                # 4. Fallback to current_node or "None"
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

                t_data["total_nodes"] = total_count
                t_data["mastered_nodes"] = mastered_count
                t_data["active_node"] = active_lbl or t_data.get("current_node") or "None"
            else:
                if not t_data.get("active_node") or t_data.get("active_node") == "None":
                    t_data["active_node"] = t_data.get("current_node") or "None"

        topic_list = list(topics_by_slug.values())
        topic_list.sort(key=lambda t: t.get("updated_at", ""), reverse=True)
        return {"topics": topic_list}
    except Exception:
        # Defensively return 200 with empty list on any error
        return {"topics": []}


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

    # Restore notes.md
    restored_notes = ""
    if target_dir.exists() and (target_dir / "notes.md").exists():
        shutil.copy2(target_dir / "notes.md", NOTES_FILE)
        restored_notes = NOTES_FILE.read_text(encoding="utf-8")

    # Restore roadmap.mmd
    restored_roadmap = ""
    if target_dir.exists() and (target_dir / "roadmap.mmd").exists():
        ROADMAP_FILE.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(target_dir / "roadmap.mmd", ROADMAP_FILE)
        restored_roadmap = ROADMAP_FILE.read_text(encoding="utf-8")

    # Restore or construct state/curriculum.json
    archived_curr = target_dir / "curriculum.json"
    CURRICULUM_FILE.parent.mkdir(parents=True, exist_ok=True)
    if archived_curr.exists():
        tmp_curr = CURRICULUM_FILE.with_name(f"{CURRICULUM_FILE.name}.tmp")
        shutil.copy2(archived_curr, tmp_curr)
        safe_replace(tmp_curr, CURRICULUM_FILE)
    else:
        min_nodes = []
        kg = load_knowledge_graph()
        kg_nodes = kg.get("nodes", [])
        kg_edges = kg.get("edges", [])
        topic_kg_nodes = [
            n for n in kg_nodes
            if sanitized in [sanitize_topic(str(t)) for t in (n.get("topics") or [])]
        ]
        if topic_kg_nodes:
            prereq_map: Dict[str, List[str]] = {}
            for e in kg_edges:
                src = str(e.get("source", ""))
                tgt = str(e.get("target", ""))
                if tgt and src:
                    prereq_map.setdefault(tgt, []).append(src)
            for idx, n in enumerate(topic_kg_nodes):
                nid = n.get("id") or f"node-{idx+1}"
                nlbl = n.get("label") or nid
                nst = str(n.get("status", "pending")).lower()
                c_status = "completed" if nst == "mastered" else ("active" if nst == "active" else "pending")
                badge = "Curriculum Mastered" if c_status == "completed" else ("In Progress" if c_status == "active" else "Pending")
                min_nodes.append({
                    "id": nid,
                    "title": nlbl,
                    "prerequisites": prereq_map.get(nid, []),
                    "status": c_status,
                    "badge_label": badge
                })
        elif session_data.get("completed_nodes"):
            comp_nodes = session_data.get("completed_nodes", [])
            for idx, cn in enumerate(comp_nodes):
                nid = to_canonical_id(cn)
                min_nodes.append({
                    "id": nid,
                    "title": cn,
                    "prerequisites": [to_canonical_id(comp_nodes[idx-1])] if idx > 0 else [],
                    "status": "completed",
                    "badge_label": "Curriculum Mastered"
                })
            curr_n = session_data.get("current_node")
            if curr_n and curr_n not in comp_nodes:
                min_nodes.append({
                    "id": to_canonical_id(curr_n),
                    "title": curr_n,
                    "prerequisites": [to_canonical_id(comp_nodes[-1])] if comp_nodes else [],
                    "status": "active",
                    "badge_label": "In Progress"
                })

        min_curriculum = {"nodes": min_nodes}
        tmp_curr = CURRICULUM_FILE.with_name(f"{CURRICULUM_FILE.name}.tmp")
        with open(tmp_curr, "w", encoding="utf-8") as f:
            json.dump(min_curriculum, f, indent=2, ensure_ascii=False)
        safe_replace(tmp_curr, CURRICULUM_FILE)

    # Read session.json for metadata
    session_data: Dict[str, Any] = {}
    if target_dir.exists() and (target_dir / "session.json").exists():
        try:
            with open(target_dir / "session.json", "r", encoding="utf-8") as f:
                session_data = json.load(f)
        except Exception:
            session_data = {}

    restored_topic_name = session_data.get("topic") or topic_name
    restored_current_node = session_data.get("current_node") or ""

    # Reads state/knowledge_graph.json to find the active or next planned node
    kg = load_knowledge_graph()
    kg_nodes = kg.get("nodes", [])
    active_node = None

    # First look for active node
    for node in kg_nodes:
        node_topics = [sanitize_topic(str(t)) for t in (node.get("topics") or [])]
        if sanitized in node_topics:
            if str(node.get("status", "")).lower() == "active":
                active_node = node.get("label")
                break

    # If no active node found in KG, look for next planned node
    if not active_node:
        for node in kg_nodes:
            node_topics = [sanitize_topic(str(t)) for t in (node.get("topics") or [])]
            if sanitized in node_topics:
                if str(node.get("status", "")).lower() == "planned":
                    active_node = node.get("label")
                    break

    # Fallback to restored current_node or "None"
    if not active_node:
        active_node = restored_current_node or "None"

    # Update state/topic.json
    TOPIC_FILE.parent.mkdir(parents=True, exist_ok=True)
    topic_payload = {"topic": restored_topic_name, "phase": "teaching"}
    restored_ref_scope = session_data.get("reference_scope")
    if restored_ref_scope:
        topic_payload["reference_scope"] = restored_ref_scope
    tmp_top = TOPIC_FILE.with_name(f"{TOPIC_FILE.name}.tmp")
    with open(tmp_top, "w", encoding="utf-8") as f:
        json.dump(topic_payload, f, indent=2)
    safe_replace(tmp_top, TOPIC_FILE)

    # Clear answer and quiz
    if ANSWER_FILE.exists():
        ANSWER_FILE.unlink(missing_ok=True)
    if QUIZ_FILE.exists():
        try:
            with open(QUIZ_FILE, "w", encoding="utf-8") as f:
                json.dump({"questions": []}, f, indent=2)
        except Exception:
            pass

    # Build and save new state
    state = load_state()
    state["session_active"] = True
    state["topic"] = restored_topic_name
    state["phase"] = "TEACHING"
    state["dag_mermaid"] = restored_roadmap
    state["lesson_markdown"] = restored_notes
    state["notes"] = restored_notes
    state["active_quiz"] = None
    state["quiz"] = None
    state["latest_answer"] = None
    state["current_node"] = active_node
    state["active_node"] = active_node
    state["reference_scope"] = restored_ref_scope
    save_state(state)

    # Explicitly ensure state/state.json has the requested fields:
    # { "session_active": true, "topic": topic, "phase": "TEACHING", "active_node": active_node_label }
    state_payload = {
        "session_active": True,
        "topic": restored_topic_name,
        "phase": "TEACHING",
        "active_node": active_node,
        "notes": restored_notes,
        "quiz": None,
        "dag_mermaid": restored_roadmap
    }
    tmp_st = STATE_JSON_FILE.with_name(f"{STATE_JSON_FILE.name}.tmp")
    with open(tmp_st, "w", encoding="utf-8") as f:
        json.dump(state_payload, f, indent=2, ensure_ascii=False)
    safe_replace(tmp_st, STATE_JSON_FILE)

    return {
        "success": True,
        "state": state_payload
    }


@app.post("/api/archive")
def archive_topic(req: Optional[ArchiveRequest] = None) -> Dict[str, Any]:
    topic_name = req.topic.strip() if req and req.topic else ""
    reference_scope = None
    if not topic_name:
        # Read from state/topic.json
        if TOPIC_FILE.exists():
            try:
                with open(TOPIC_FILE, "r", encoding="utf-8") as f:
                    t_data = json.load(f)
                    topic_name = t_data.get("topic", "").strip()
                    reference_scope = t_data.get("reference_scope")
            except Exception:
                pass
    else:
        if TOPIC_FILE.exists():
            try:
                with open(TOPIC_FILE, "r", encoding="utf-8") as f:
                    t_data = json.load(f)
                    reference_scope = t_data.get("reference_scope")
            except Exception:
                pass

    if not topic_name:
        state = load_state()
        topic_name = state.get("topic", "").strip()
        if not reference_scope:
            reference_scope = state.get("reference_scope")
    if not topic_name:
        topic_name = "untitled"

    if not reference_scope:
        state = load_state()
        reference_scope = state.get("reference_scope")

    target_dir = get_topic_notes_dir(topic_name)
    if not target_dir:
        return {"status": "skipped", "message": "Cannot archive empty or not-set topic"}
    target_dir.mkdir(parents=True, exist_ok=True)
    sanitized = target_dir.name

    # Move or copy current notes/lesson_notes.md to notes/<sanitized_topic>/notes.md
    if NOTES_FILE.exists():
        shutil.copy2(NOTES_FILE, target_dir / "notes.md")

    # If state/roadmap.mmd exists, copy it to notes/<sanitized_topic>/roadmap.mmd
    if ROADMAP_FILE.exists():
        shutil.copy2(ROADMAP_FILE, target_dir / "roadmap.mmd")

    # If state/curriculum.json exists, atomically copy it to notes/<sanitized_topic>/curriculum.json
    if CURRICULUM_FILE.exists():
        archive_curr = target_dir / "curriculum.json"
        tmp_curr = target_dir / "curriculum.json.tmp"
        try:
            shutil.copy2(CURRICULUM_FILE, tmp_curr)
            safe_replace(tmp_curr, archive_curr)
        except Exception:
            try:
                shutil.copy2(CURRICULUM_FILE, archive_curr)
            except Exception:
                pass

    # Extract completed nodes and current node
    completed_nodes: List[str] = []
    current_node = ""
    notes_path = target_dir / "notes.md"
    if notes_path.exists():
        try:
            content = notes_path.read_text(encoding="utf-8")
            # Look for top-level node headers like "## Node 1: ..." or "## ..."
            node_matches = re.findall(r'^##(?!\#)\s+(?:Node\s*\d+:\s*)?([^\r\n]+)', content, flags=re.MULTILINE)
            node_matches = [m.strip() for m in node_matches]
            if node_matches:
                completed_nodes = node_matches
                current_node = completed_nodes[-1]
        except Exception:
            pass

    state = load_state()
    if state.get("current_node") and not current_node:
        current_node = state["current_node"]

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

    # Automatically mark completed nodes for the archived topic as "mastered" in state/knowledge_graph.json
    if completed_nodes:
        try:
            kg = load_knowledge_graph()
            kg_nodes = kg.get("nodes", [])
            kg_dirty = False
            for c_node in completed_nodes:
                c_lbl = clean_label(c_node)
                c_key = c_lbl.lower()
                c_cid = canonical_id(c_lbl)
                matched = False
                for node in kg_nodes:
                    if node.get("id") == c_cid or clean_label(node.get("label", "")).lower() == c_key:
                        node["status"] = "mastered"
                        if topic_name and topic_name not in node.get("topics", []):
                            node.setdefault("topics", []).append(topic_name)
                        matched = True
                        kg_dirty = True
                        break
                if not matched:
                    fuzzy_id = find_fuzzy_concept_match(c_lbl, kg_nodes)
                    if fuzzy_id:
                        for node in kg_nodes:
                            if node.get("id") == fuzzy_id:
                                node["status"] = "mastered"
                                if topic_name and topic_name not in node.get("topics", []):
                                    node.setdefault("topics", []).append(topic_name)
                                matched = True
                                kg_dirty = True
                                break
                if not matched:
                    kg_nodes.append({
                        "id": c_cid,
                        "label": c_lbl,
                        "status": "mastered",
                        "topics": [topic_name] if topic_name else []
                    })
                    kg_dirty = True
            if kg_dirty:
                kg["nodes"] = kg_nodes
                save_knowledge_graph(kg)
        except Exception:
            pass

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
    sanitized = target_dir.name

    # Restore notes.md into notes/lesson_notes.md
    restored_notes = ""
    if (target_dir / "notes.md").exists():
        shutil.copy2(target_dir / "notes.md", NOTES_FILE)
        restored_notes = NOTES_FILE.read_text(encoding="utf-8")

    # Restore roadmap.mmd into state/roadmap.mmd
    restored_roadmap = ""
    if (target_dir / "roadmap.mmd").exists():
        ROADMAP_FILE.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(target_dir / "roadmap.mmd", ROADMAP_FILE)
        restored_roadmap = ROADMAP_FILE.read_text(encoding="utf-8")

    # Read session.json
    session_file = target_dir / "session.json"
    session_data = {}
    if session_file.exists():
        try:
            with open(session_file, "r", encoding="utf-8") as f:
                session_data = json.load(f)
        except Exception:
            session_data = {}
    if not session_data:
        session_data = {
            "topic": topic_name,
            "completed_nodes": [],
            "current_node": "",
            "timestamp": datetime.now(timezone.utc).isoformat()
        }

    # Update state/topic.json with {"topic": "<topic>", "phase": "teaching"}
    TOPIC_FILE.parent.mkdir(parents=True, exist_ok=True)
    topic_payload = {"topic": session_data.get("topic", topic_name), "phase": "teaching"}
    restored_ref_scope = session_data.get("reference_scope")
    if restored_ref_scope:
        topic_payload["reference_scope"] = restored_ref_scope
    with open(TOPIC_FILE, "w", encoding="utf-8") as f:
        json.dump(topic_payload, f, indent=2)

    # Clear state/answer.json and state/quiz.json
    if ANSWER_FILE.exists():
        ANSWER_FILE.unlink(missing_ok=True)
    if QUIZ_FILE.exists():
        try:
            with open(QUIZ_FILE, "w", encoding="utf-8") as f:
                json.dump({"questions": []}, f, indent=2)
        except Exception:
            pass

    # Update state.json
    state = load_state()
    state["session_active"] = True
    state["topic"] = session_data.get("topic", topic_name)
    state["phase"] = "teaching"
    state["dag_mermaid"] = restored_roadmap
    state["lesson_markdown"] = restored_notes
    state["notes"] = restored_notes
    state["active_quiz"] = None
    state["quiz"] = None
    state["latest_answer"] = None
    state["current_node"] = session_data.get("current_node", "")
    state["active_node"] = session_data.get("current_node", "")
    state["reference_scope"] = restored_ref_scope
    save_state(state)

    # Return the contents of notes/<sanitized_topic>/session.json
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
    # Write {"status": "stopped"} to state/answer.json
    ANSWER_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(ANSWER_FILE, "w", encoding="utf-8") as f:
        json.dump({"status": "stopped"}, f, indent=2)

    # Clear state/quiz.json
    if QUIZ_FILE.exists():
        try:
            with open(QUIZ_FILE, "w", encoding="utf-8") as f:
                json.dump({"questions": []}, f, indent=2)
        except Exception:
            pass

    # Reset state/roadmap.mmd with valid default Mermaid class definition headers
    ROADMAP_FILE.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(ROADMAP_FILE, "w", encoding="utf-8") as f:
            f.write(DEFAULT_ROADMAP_SKELETON)
    except Exception:
        pass

    # Reset notes/lesson_notes.md with initial placeholder/comment
    NOTES_FILE.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(NOTES_FILE, "w", encoding="utf-8") as f:
            f.write(DEFAULT_LESSON_NOTES_PLACEHOLDER)
    except Exception:
        pass

    # Write state/topic.json with valid initial skeleton structure
    TOPIC_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(TOPIC_FILE, "w", encoding="utf-8") as f:
        json.dump(DEFAULT_TOPIC_SKELETON, f, indent=2)

    # Write state/curriculum.json with valid initial skeleton structure
    CURRICULUM_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(CURRICULUM_FILE, "w", encoding="utf-8") as f:
        json.dump(DEFAULT_CURRICULUM_SKELETON, f, indent=2)

    # Write state/knowledge_graph.json if missing or cleared
    KNOWLEDGE_GRAPH_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not KNOWLEDGE_GRAPH_FILE.exists() or KNOWLEDGE_GRAPH_FILE.stat().st_size == 0:
        with open(KNOWLEDGE_GRAPH_FILE, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_KNOWLEDGE_GRAPH_SKELETON, f, indent=2)
    else:
        try:
            with open(KNOWLEDGE_GRAPH_FILE, "r", encoding="utf-8") as f:
                kg_data = json.load(f)
            if not kg_data.get("nodes"):
                with open(KNOWLEDGE_GRAPH_FILE, "w", encoding="utf-8") as f:
                    json.dump(DEFAULT_KNOWLEDGE_GRAPH_SKELETON, f, indent=2)
        except Exception:
            with open(KNOWLEDGE_GRAPH_FILE, "w", encoding="utf-8") as f:
                json.dump(DEFAULT_KNOWLEDGE_GRAPH_SKELETON, f, indent=2)

    # Overwrite state/state.json with clean blank idle structure
    blank_state = {
        "session_active": False,
        "topic": "Not Set",
        "phase": "IDLE",
        "active_node": None,
        "notes": "",
        "quiz": None,
        "latest_answer": None,
        "quiz_history": []
    }
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    full_state = DEFAULT_STATE.copy()
    full_state.update(blank_state)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(full_state, f, indent=2, ensure_ascii=False)

    return {
        "success": True,
        "status": "ok",
        "state": {
            "session_active": False,
            "topic": "Not Set",
            "phase": "IDLE",
            "active_node": None,
            "notes": "",
            "quiz": None
        }
    }


@app.post("/api/shutdown")
def shutdown_server():
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

