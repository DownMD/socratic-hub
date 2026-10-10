# API & State

> Last rebuilt: .doc --all (2026-10-09)

---

## FastAPI Route Registry

All routes are declared in `server.py`. The app is exposed on `http://localhost:8000`.

### State & Session

| Method | Route | Description |
|---|---|---|
| `GET` | `/api/state` | Returns full hydrated session state blob from `state/active_session.json` and active topic `manifest.json`. Client polls this ~1s to re-render. |
| `POST` | `/api/topic` | Sets active topic + reference scope. Writes `state/active_session.json`. Sets phase to `probing`. |
| `POST` | `/api/reset` | Clears active session data. Resets `state/active_session.json` to idle. |
| `POST` | `/api/pause` | Creates `state/pause.flag`, sets phase to `PAUSED` in `state/active_session.json`. |
| `POST` | `/api/shutdown` | Sends `SIGTERM` to the Uvicorn process after a 0.5s delay. |

### Quiz & Answer

| Method | Route | Description |
|---|---|---|
| `GET` | `/api/quiz` | Returns the active quiz from `notes/<topic>/.session/quiz.json` (or `.diagnostic/diagnostic_quiz.json`), sanitized and normalized. |
| `POST` | `/api/quiz` | Writes quiz questions to `notes/<topic>/.session/quiz.json` (or `.diagnostic/diagnostic_quiz.json`). |
| `POST` | `/api/submit-quiz` | Batch quiz submission. Evaluates all answers, writes `notes/<topic>/.session/answer.json`, returns evaluation payload with `passed`, `score`, `rationales`. |
| `POST` | `/api/answer` | Single-item answer submission. Writes answer record to topic `.session/answer.json`. |
| `GET` | `/api/latest-answer` | Returns `latest_answer` from active topic's `.session/answer.json`. Used by `bridge.py wait-answer` polling loop. |

### DAG & Notes

| Method | Route | Description |
|---|---|---|
| `POST` | `/api/dag` | Dynamically compiles or overrides Mermaid DAG string in state. |
| `POST` | `/api/lesson` | Appends a markdown chunk to active note in `notes/<topic>/<node_id>.md`. |
| `GET` | `/api/notes/{node_id}` | Resolves note by node ID directly from topic vault file `notes/<topic>/<node_id>.md` or knowledge graph metadata. |

### Topics & Vault Management

| Method | Route | Description |
|---|---|---|
| `GET` | `/api/topics` | Lists all discovered topic vaults from `notes/` directories with metadata (`total_nodes`, `mastered_nodes`, `domain`, `status`). |
| `POST` | `/api/topics/load` | Loads a saved topic (`mode='study'` or zero-token `mode='read'`), sets active topic in `state/active_session.json`, compiles Mermaid DAG from `manifest.json`. |
| `DELETE` | `/api/topics/{topic_name}` | Permanently deletes a topic vault directory. |
| `POST` | `/api/archive` | Archives current session, marks completed nodes as `mastered` in knowledge graph. |
| `POST` | `/api/restore` | Restores topic vault into active session. |

### Knowledge Graph

| Method | Route | Description |
|---|---|---|
| `GET` | `/api/graph/global` | Returns the global knowledge graph (`state/knowledge_graph.json`), bootstrapping from vault notes if empty. |
| `POST` | `/api/graph/sync` | Merges incoming nodes and edges into the knowledge graph with status ranking, fuzzy deduplication, and degree guard. |

### Static Files

| Method | Route | Description |
|---|---|---|
| `GET` | `/` | Serves `static/index.html`. |
| `GET` | `/static/*` | Mounts `static/` as a static file server. |

---

## Pydantic Request Models

```python
TopicRequest            # topic: str, reference_scope: Optional[Dict], mode: Optional[str]
QuizRequest             # question, options, correct_idx, explanation
AnswerRequest           # selected_idx, question_idx (default 0)
BatchQuizSubmitRequest  # node_id, answers: List[int], timestamp
DagRequest              # mermaid: str
LessonRequest           # markdown_chunk: str
ArchiveRequest          # topic: Optional[str]
RestoreRequest          # topic: str
GraphSyncRequest        # nodes: List[Dict], edges: List[Dict]
```

---

## State JSON Schemas

### `state/active_session.json`

```json
{
  "active_topic": "<Topic Name>",
  "phase": "idle | probing | teaching | reading | PAUSED | completed",
  "active_node_id": "<Node ID> | null",
  "reference_scope": {
    "collection": "<Collection Name>",
    "tags": ["<tag-1>", "<tag-2>"]
  }
}
```

### `notes/<Topic Name>/manifest.json`

```json
{
  "topic": "<Topic Name>",
  "domain": "<Domain>",
  "reference_scope": {
    "collection": "<Collection Name>",
    "tags": ["<tag-1>", "<tag-2>"]
  },
  "nodes": [
    {
      "id": "<Node ID>",
      "title": "<Node Title>",
      "prerequisites": ["<Prerequisite Node ID>"],
      "status": "completed | active | planned | mastered",
      "origin": "curriculum | diagnostic",
      "badge_label": "Curriculum Mastered | In Progress | Baseline Knowledge"
    }
  ],
  "edges": [
    {
      "source": "<Source Node ID>",
      "target": "<Target Node ID>"
    }
  ]
}
```

### `notes/<Topic Name>/.session/quiz.json` (Multi-item Assessment Format)

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

### `notes/<Topic Name>/.session/answer.json` (Batch Evaluation Payload)

```json
{
  "node_id": "<Node ID>",
  "batch": true,
  "answers": [2, 0, 1],
  "results": [{"question_idx": 0, "selected_idx": 2, "correct_idx": 2, "correct": true, "explanation": "..."}],
  "correct_count": 3,
  "total": 3,
  "score": 1.0,
  "passed": true,
  "timestamp": "2026-10-09T08:00:00+00:00"
}
```

> **Pass Threshold**: `bridge.py advance-node` considers a score ≥ 0.70 OR `passed: true` OR `correct_count == total` as passing.

### `state/cache/<topic_slug>/verification_<node_id>.json`

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

### Lookahead Cache (`state/cache/<topic_slug>/`)

- Files are scoped by topic slug: `state/cache/<topic_slug>/verification_<node_id>.json`.
- When Node N is being taught, lookahead verification audits for N+1 and N+2 are pre-staged by the `theoretical-verifier` sub-agent.
- The `[HORIZON_STATUS]` output reports Active, Cached, and Missing IDs.
- If a cache file is missing, the verifier is dispatched asynchronously in the background **without blocking** the UI.

### Atomic Write Pattern

Every file mutation uses a `.tmp` → `replace` pattern:
```python
tmp = target.with_name(f"{target.name}.tmp")
with open(tmp, "w", encoding="utf-8") as f:
    json.dump(data, f, indent=2, ensure_ascii=False)
tmp.replace(target)
```

### State Hydration Order (`load_state`)

On every `/api/state` call, `load_state()` hydrates strictly from:
1. `state/active_session.json` (active topic, phase, active_node_id, reference_scope)
2. `notes/<active_topic>/manifest.json` (dynamic Mermaid DAG compilation and nodes list)
3. `notes/<active_topic>/<active_node_id>.md` (lesson markdown)
4. `notes/<active_topic>/.session/quiz.json` (active_quiz)
5. `notes/<active_topic>/.session/answer.json` (latest_answer)
6. Derives `status` (`active` if valid topic, `reading` if read mode, `standby` if idle with no topic).

### Canonical Topic Notes Directory Resolution (`get_topic_notes_dir`)

`server.py` and `bridge.py` share the centralized `get_topic_notes_dir(topic_name)` helper:
- **Phantom Guard**: If `topic_name` is empty, `None`, `"Not Set"`, `"not-set"`, or `"none"` $\to$ returns `None` (preventing phantom directory creation).
- **Title Case Canonical First**: Returns `notes/<Topic Name>` if existing.
- **Legacy Slug Fallback**: Returns `notes/<slug>` if existing from prior archives.
- **Default Creation**: Returns `notes/<Topic Name>` (Title Case default).

### Knowledge Graph Status Ranking

When merging via `/api/graph/sync`, statuses are ranked:
- `planned` = 1
- `active` = 2  
- `mastered` = 3

A node's status can only be promoted upward, never downgraded. If a node is `mastered`, it **cannot** be overwritten even by an `active` sync request.

### Degree Guard

After every `/api/graph/sync`, isolated nodes (degree = 0) are auto-linked via:
1. Manifest `prerequisites` fields (downstream link)
2. Manifest prerequisite parents (upstream link)
3. If still degree = 0 after both passes $\to$ the node is rejected and not inserted.
