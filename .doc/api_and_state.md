# API & State

> Last rebuilt: .doc --all (2026-10-03)

---

## FastAPI Route Registry

All routes are declared in `server.py`. The app is exposed on `http://localhost:8000`.

### State & Session

| Method | Route | Description |
|---|---|---|
| `GET` | `/api/state` | Returns full hydrated session state blob. Client polls this ~1s to re-render. |
| `POST` | `/api/topic` | Sets active topic + reference scope. Writes `state/topic.json`. Sets phase to `probing`. |
| `POST` | `/api/reset` | Clears all active session data: quiz, roadmap, notes. Sets topic to blank, phase to `idle`. |
| `POST` | `/api/pause` | Creates `state/pause.flag`, sets phase to `PAUSED` in `topic.json`. |
| `POST` | `/api/shutdown` | Sends `SIGTERM` to the Uvicorn process after a 0.5s delay. |

### Quiz & Answer

| Method | Route | Description |
|---|---|---|
| `GET` | `/api/quiz` | Returns the active quiz from `state/quiz.json`, sanitized and normalized. |
| `POST` | `/api/quiz` | Single-item quiz write (legacy). Writes one question to state and clears answer. |
| `POST` | `/api/submit-quiz` | Batch quiz submission. Evaluates all answers, writes `state/answer.json`, returns evaluation payload with `passed`, `score`, `rationales`. |
| `POST` | `/api/answer` | Single-item answer submission (legacy). Writes one answer record. |
| `GET` | `/api/latest-answer` | Returns `latest_answer` from current state. Used by `bridge.py wait-answer` polling loop. |

### DAG & Notes

| Method | Route | Description |
|---|---|---|
| `POST` | `/api/dag` | Writes Mermaid DAG string to state and sets phase to `teaching`. |
| `POST` | `/api/lesson` | Appends a markdown chunk to in-memory state and `notes/lesson_notes.md`. |
| `GET` | `/api/notes/{node_id}` | Resolves a note by node ID via 3-tier lookup: vault file → `lesson_notes.md` section → knowledge graph metadata. |

### Topics & Archive

| Method | Route | Description |
|---|---|---|
| `GET` | `/api/topics` | Lists all discovered topics from `notes/` directories and `state/knowledge_graph.json`. |
| `POST` | `/api/topics/load` | Loads a saved topic: restores `lesson_notes.md` + `roadmap.mmd`, updates `topic.json`, resolves active node from KG. |
| `POST` | `/api/topics/discard` | Deletes `session.json` for a topic and resets state if it matches the active session. |
| `POST` | `/api/archive` | Archives current session: copies `lesson_notes.md` and `roadmap.mmd` into `notes/<topic>/`, extracts completed nodes, writes `session.json`, marks nodes as `mastered` in KG. |
| `POST` | `/api/restore` | Restores a topic from `notes/<topic>/` into active state. Legacy route (prefer `/api/topics/load`). |

### Knowledge Graph

| Method | Route | Description |
|---|---|---|
| `GET` | `/api/graph/global` | Returns the full knowledge graph (`state/knowledge_graph.json`), bootstrapping from notes if empty. |
| `POST` | `/api/graph/sync` | Merges incoming nodes and edges into the knowledge graph with status ranking, fuzzy deduplication, and degree guard. |

### Static Files

| Method | Route | Description |
|---|---|---|
| `GET` | `/` | Serves `static/index.html`. |
| `GET` | `/static/*` | Mounts `static/` as a static file server. |

---

## Pydantic Request Models

```python
TopicRequest         # topic: str, reference_scope: Optional[Dict]
QuizRequest          # question, options, correct_idx, explanation
AnswerRequest        # selected_idx, question_idx (default 0)
BatchQuizSubmitRequest  # node_id, answers: List[int], timestamp
DagRequest           # mermaid: str
LessonRequest        # markdown_chunk: str
ArchiveRequest       # topic: Optional[str]
RestoreRequest       # topic: str
DiscardTopicRequest  # topic: str
GraphSyncRequest     # nodes: List[Dict], edges: List[Dict]
```

---

## State JSON Schemas

### `state/topic.json`

```json
{
  "topic": "<Topic Name>",
  "phase": "idle | probing | teaching | PAUSED | completed",
  "active_node_id": "<Node ID> | null",
  "active_node": "<Node Title> | null",
  "reference_scope": {
    "collection": "<Collection Name>",
    "tags": ["<tag-1>", "<tag-2>"]
  }
}
```

### `state/curriculum.json`

```json
{
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
```

### `state/quiz.json` (Multi-item Assessment Format)

```json
{
  "node_id": "<Node ID>",
  "questions": [
    {
      "id": "q1",
      "question": "Plain text with double-escaped LaTeX: \\( C_i = \\frac{m_i}{p_i} \\)",
      "options": ["A) ...", "B) ...", "C) ...", "D) ..."],
      "correct_idx": 2,
      "explanation": "..."
    }
  ]
}
```

> **Math Escaping Invariant**: All LaTeX within JSON must use double-escaped backslashes (`\\(`, `\\frac{...}{...}`) to prevent JSON parse failures.

### `state/answer.json` (Batch Evaluation Payload)

```json
{
  "node_id": "...",
  "batch": true,
  "answers": [2, 0, 1],
  "results": [{"question_idx": 0, "selected_idx": 2, "correct_idx": 2, "correct": true, "explanation": "..."}],
  "correct_count": 3,
  "total": 3,
  "score": 1.0,
  "passed": true,
  "timestamp": "2026-10-03T03:06:13+00:00"
}
```

> **Pass Threshold**: `bridge.py advance-node` considers a score ≥ 0.70 OR `passed: true` OR `correct_count == total` as passing.

### `state/verification.json`

```json
{
  "concept": "<Node Title>",
  "status": "[VERIFIED] | [VERIFIED_WEB]",
  "source_type": "local_textbook | authoritative_canon",
  "document_title": "...",
  "page_range": "Pages 12-15 | N/A",
  "citation": "...",
  "canonical_definition": "...",
  "trade_offs_and_boundaries": "...",
  "violating_assumption": null,
  "missing_prerequisite": null,
  "misconceptions": ["...", "..."]
}
```

### `state/knowledge_graph.json`

```json
{
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
    { "source": "<Prerequisite Node ID>", "target": "<Node ID>", "relation": "prerequisite" }
  ]
}
```

---

## Caching Invariants

### Lookahead Cache (`state/cache/`)

- Files are named `state/cache/verification_<node_id>.json` using the **exact** `id` from `state/curriculum.json`.
- When `advance-node` runs, it promotes the cache file for the next node to `state/verification.json` and deletes the cache entry.
- The `[HORIZON_STATUS]` output shows Active, Cached, and Missing IDs.
- If a cache file is missing, the verifier must be dispatched asynchronously in the background **without blocking** the UI.

### Atomic Write Pattern

Every state file mutation uses a `.tmp` → `replace` pattern:
```python
tmp = target.with_name(f"{target.name}.tmp")
with open(tmp, "w") as f:
    json.dump(data, f, indent=2)
tmp.replace(target)
```

### State Hydration Order (load_state)

On every `/api/state` call, `load_state()` hydrates in this order:
1. `state/state.json` (primary unified state snapshot)
2. Overlays from `state/topic.json` (topic, phase, active_node_id, reference_scope)
3. Overlays from `state/roadmap.mmd` (dag_mermaid)
4. Overlays from `notes/lesson_notes.md` (lesson_markdown, notes)
5. Overlays from `state/quiz.json` (active_quiz)
6. Recomputes `session_active` from topic + phase values.

### Canonical Topic Notes Directory Resolution (`get_topic_notes_dir`)

`server.py` and `bridge.py` share the centralized `get_topic_notes_dir(topic_name)` helper:
- **Phantom Guard**: If `topic_name` is empty, `None`, `"Not Set"`, `"not-set"`, or `"none"` $\to$ returns `None` (preventing `notes/not-set/` creation).
- **Title Case Canonical First**: Returns `notes/<Topic Name>` if existing.
- **Legacy Slug Fallback**: Returns `notes/<slug>` if existing from prior archives.
- **Default Creation**: Returns `notes/<Topic Name>` (Title Case default).

### Knowledge Graph Status Ranking

When merging via `/api/graph/sync`, statuses are ranked:
- `planned` = 1
- `active` = 2  
- `mastered` = 3

A node's status can only be promoted upward, never downgraded. Exception: if a node is `mastered`, it **cannot** be overwritten even by an `active` sync request.

### Degree Guard

After every `/api/graph/sync`, isolated nodes (degree = 0) are auto-linked via:
1. Curriculum `prerequisites` fields (downstream link)
2. Curriculum prerequisite parents (upstream link)
3. If still degree = 0 after both passes → the node is rejected and not inserted.
