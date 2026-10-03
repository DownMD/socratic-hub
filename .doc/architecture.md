# Architecture

> Last rebuilt: .doc --all (2026-10-03)

---

## System Topology

```
┌────────────────────────────────────────────────────────────────┐
│                    Antigravity Agent (AI)                       │
│   Drives all teaching state transitions via file writes        │
└──────────────┬─────────────────────────────────────────────────┘
               │ Writes state/ JSON files
               ▼
┌────────────────────────────────────────────────────────────────┐
│                  state/  (Shared State Layer)                   │
│  topic.json │ curriculum.json │ quiz.json │ answer.json        │
│  roadmap.mmd │ verification.json │ knowledge_graph.json        │
│  cache/verification_<node_id>.json                             │
└──────────┬──────────────────────────────┬──────────────────────┘
           │ file-watch (load_state())    │ bridge.py polls
           ▼                              ▼
┌──────────────────────┐      ┌─────────────────────────────────┐
│  server.py (FastAPI) │      │  bridge.py (CLI subprocess)      │
│  port 8000           │      │  wait-answer / advance-node /    │
│  Uvicorn ASGI host   │      │  shuffle-quiz                    │
└──────────┬───────────┘      └─────────────────────────────────┘
           │ HTTP REST
           ▼
┌────────────────────────────────────────────────────────────────┐
│            Browser Client  (static/index.html)                 │
│  Polls /api/state every ~1s to re-render UI                    │
│  Submits answers via POST /api/submit-quiz                     │
│  D3 force-graph canvas │ Mermaid DAG │ Markdown lesson viewer  │
└────────────────────────────────────────────────────────────────┘
```

---

## Core Design Principles

| Principle | Implementation |
|---|---|
| **File-driven orchestration** | All state transitions happen through writes to `state/` JSON files; the server independently watches these and reflects changes to the client on the next poll |
| **Agent reads no server source** | `[BAN] A` in AGENTS.md prohibits the agent from reading `server.py`, `bridge.py`, `static/index.html`, `static/app.js`, or `static/styles.css` during teaching — all orchestration is file-driven |
| **Atomic writes** | Every state mutation uses a `.tmp` → `rename` pattern to prevent partial reads |
| **Zero orphan nodes** | The knowledge graph degree guard (`/api/graph/sync`) rejects or auto-links any node with `in_degree + out_degree = 0` |
| **Sliding-window lookahead** | Verification payloads for nodes N+1 and N+2 are pre-computed in `state/cache/` while Node N is being taught |

---

## Session Lifecycle

```
flowchart TD
    A[".teach <topic>"] --> B["Phase: probing\nstate/topic.json"]
    B --> C["Diagnostic MCQs\nbridge.py wait-answer"]
    C --> D["Baseline nodes captured\nPOST /api/graph/sync"]
    D --> E["Phase 2: Plan & Verify\nstate/roadmap.mmd\nstate/curriculum.json"]
    E --> F["Phase: teaching\nstate/topic.json"]
    F --> G["Node N active\nnotes/lesson_notes.md\nnotes/<topic>/<node_id>.md"]
    G --> H["state/quiz.json written\nbridge.py wait-answer"]
    H --> I{Quiz passed?}
    I -- Yes --> J["bridge.py advance-node\nstate/curriculum.json updated\nstate/roadmap.mmd restyled"]
    I -- No --> H
    J --> K{More nodes?}
    K -- Yes --> G
    K -- No --> L["phase: completed\nscripts/sync_vault_index.py --rebuild"]
```

---

## Key File Paths

| File | Purpose |
|---|---|
| `server.py` | FastAPI backend, 1908 lines, all REST routes, state hydration |
| `bridge.py` | CLI subprocess (784 lines): `wait-answer`, `advance-node`, `shuffle-quiz` |
| `state/topic.json` | Active topic name, phase, active_node_id, reference_scope |
| `state/curriculum.json` | Node list with id, title, prerequisites, status, badge_label |
| `state/roadmap.mmd` | Mermaid flowchart DAG, CSS classes updated by `advance-node` |
| `state/quiz.json` | Active multi-item quiz payload (3 questions with options, correct_idx, explanation) |
| `state/answer.json` | Bridge output after quiz pass; signals `advance-node` via `passed: true` |
| `state/verification.json` | Audit payload for active node (status, citation, misconceptions) |
| `state/cache/verification_<id>.json` | Lookahead pre-verification cache for N+1 / N+2 |
| `state/knowledge_graph.json` | Global persistent node/edge graph across all topics |
| `state/pause.flag` | Sentinel file; bridge exits code 2 when it exists |
| `state/state.json` | Hydrated session state snapshot (unified root state) |
| `notes/lesson_notes.md` | Append-only lesson notes: `## Baseline: X` and `## Node N: Title` |
| `notes/<Topic Name>/<node_id>.md` | Per-node Title Case canonical vault note with Obsidian YAML frontmatter |

---

## Pause & Resume Flow

```
flowchart TD
    P["POST /api/pause"] --> PF["Creates state/pause.flag\nSets phase: PAUSED in topic.json"]
    PF --> BR["bridge.py detects pause.flag\nExits code 2 → [SESSION: PAUSED]"]
    BR --> WAIT["Agent outputs standby notification\nServer stays live on :8000"]
    WAIT --> R[".resume <topic>"]
    R --> RC["Read state/curriculum.json\nFind active node"]
    RC --> VP["Promote state/cache/verification_<id>.json\n→ state/verification.json"]
    VP --> WA["bridge.py wait-answer resumes"]
```

---

## Server Startup & Shutdown

**Start:**
```
python -m uvicorn server:app --host 127.0.0.1 --port 8000 --no-access-log
```
On startup, `startup_flush_buffers()` purges `quiz_history` and `latest_answer` to prevent stale answer replays.

**Verify:**
```
python -c "import urllib.request; print(urllib.request.urlopen('http://localhost:8000/api/state', timeout=3).read().decode())"
```

**Shutdown** (via Python, so it behaves the same on every shell):
```
python -c "import urllib.request; req = urllib.request.Request('http://localhost:8000/api/shutdown', data=b'', headers={'Content-Type': 'application/json'}); urllib.request.urlopen(req, timeout=2)"
```
