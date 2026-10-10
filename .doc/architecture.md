# Architecture

> Last rebuilt: .doc --all (2026-10-09)

---

## System Topology

```
┌────────────────────────────────────────────────────────────────┐
│                    Antigravity Agent (AI)                       │
│   Drives all teaching state transitions via file-backed IPC    │
│   Dispatches sub-agents (.agents/) for crawling & verification │
└──────────────┬─────────────────────────────────────────────────┘
               │ Writes vault notes & session state
               ▼
┌────────────────────────────────────────────────────────────────┐
│                 Self-Contained Topic Vault                     │
│                 notes/<Topic Name>/                            │
│  manifest.json │ <node_id>.md (Atomic Obsidian Notes)          │
│  .session/ (quiz.json, answer.json)                            │
│  .diagnostic/ (prior_candidates.json, diagnostic_quiz.json)    │
└──────────────┬─────────────────────────────────────────────────┘
               │ Ephemeral session pointer
               ▼
┌────────────────────────────────────────────────────────────────┐
│                  state/  (Minimal State Layer)                 │
│  active_session.json │ knowledge_graph.json                    │
│  cache/<topic_slug>/verification_<node_id>.json                │
└──────────┬──────────────────────────────┬──────────────────────┘
           │ watches active_session.json  │ bridge.py executes
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
│  HUD Branch Jumper │ Resizer Pointer Capture                   │
└────────────────────────────────────────────────────────────────┘
```

---

## Core Design Principles

| Principle | Implementation |
|---|---|
| **Encapsulated Topic Vaults** | All curriculum manifests, lesson notes, and transient assessment artifacts live in self-contained directories under `notes/<Topic Name>/`. Root state directory contains zero curriculum or lesson skeletons. |
| **Sub-Agent Pipeline** | Specialized sub-agents in `.agents/` handle prior knowledge semantic crawling (`prior-knowledge-crawler`) and adversarial theoretical verification (`theoretical-verifier`). |
| **File-driven orchestration** | All transitions happen through writes to topic vaults and `state/active_session.json`; the server independently watches these and reflects changes to the client. |
| **Agent reads no server source** | AGENTS.md restricts the agent from reading `server.py`, `bridge.py`, `static/index.html`, `static/app.js`, or `static/styles.css` during teaching — all orchestration is strictly file-driven. |
| **Atomic writes** | Every file mutation uses a `.tmp` → `rename` pattern to eliminate partial reads or file corruption. |
| **Zero orphan nodes** | The knowledge graph degree guard (`/api/graph/sync`) auto-links or rejects any node with `in_degree + out_degree = 0`. |
| **Lookahead caching** | Verification payloads for upcoming nodes are pre-audited in `state/cache/<topic_slug>/` while Node N is being taught. |

---

## Self-Contained Vault Directory Layout

Each topic in `notes/<Topic Name>/` forms an autonomous vault:

```
notes/<Topic Name>/
├── manifest.json              # Canonical DAG nodes, directed edges, domain, and completion state
├── <node_id>.md               # Atomic lesson notes with Obsidian YAML frontmatter and wikilinks
├── .session/                  # Ephemeral session artifacts (purged upon advance or archive)
│   ├── quiz.json              # Active multi-item assessment questions
│   └── answer.json            # Submission evaluation and pass/fail record
└── .diagnostic/               # Baseline diagnostic artifacts
    ├── prior_candidates.json  # Crawler candidate classifications
    ├── diagnostic_quiz.json   # Multi-tier diagnostic questions
    └── baseline_passes.json   # Verified baseline knowledge records
```

---

## Sub-Agent Architecture (`.agents/`)

Socratic Hub orchestrates two specialized autonomous sub-agents:

### 1. `prior-knowledge-crawler` (`.agents/prior_knowledge_crawler.md`)
- **Mandate**: Semantic crawler auditing historical vault masteries against planned curriculum concepts.
- **Execution**: Triggered in Phase 1 via `python scripts/scan_prior_knowledge.py --topic "<topic>" --output "notes/<topic>/.diagnostic/prior_candidates.json"`.
- **Classification Taxonomy**:
  - `REUSE_CANONICAL`: Exact match (same name/mechanism, same domain) $\to$ link existing vault note directly via relative wikilink.
  - `EXTEND_CONTEXT`: Partial match (same domain, specialized subtype) $\to$ extend definition in new note while linking prior concept.
  - `DOMAIN_HOMONYM`: Identical name, completely different domain $\to$ disambiguate with explicit domain scoping.
  - `NOVEL`: No prior conceptual intersection $\to$ new concept entirely.

### 2. `theoretical-verifier` (`.agents/theoretical_verifier.md`)
- **Mandate**: Adversarial academic auditor verifying theoretical models, operational trade-offs, and citations.
- **Hierarchy of Ground Truth**:
  - Tier 1: Local textbook chunks via `python scripts/locate_text.py --query "<concept>"`.
  - Tier 2: Authoritative web canon (`[VERIFIED_WEB]`).
- **Cache Target**: Persists audit payloads to `state/cache/<topic_slug>/verification_<node_id>.json`.

---

## Session Lifecycle

```
flowchart TD
    A[".teach <topic>"] --> B["Phase: probing\nstate/active_session.json"]
    B --> C["Prior Knowledge Crawl\nprior-knowledge-crawler"]
    C --> D["Multi-tier Diagnostic MCQs\nbridge.py wait-answer"]
    D --> E["Baseline nodes captured\nPOST /api/graph/sync"]
    E --> F["Phase 2: Plan & Verify\nnotes/<topic>/manifest.json"]
    F --> G["Phase: teaching\nactive_node_id set"]
    G --> H["Author active lesson note\nnotes/<topic>/<node_id>.md"]
    H --> I["Write notes/<topic>/.session/quiz.json\nbridge.py wait-answer"]
    I --> J{Quiz passed?}
    J -- Yes --> K["bridge.py advance-node\nPromotes frontmatter to 'mastered'\nUpdates manifest.json\nWipes .session/"]
    J -- No --> I
    K --> L{More nodes?}
    L -- Yes --> G
    L -- No --> M["phase: completed\nscripts/sync_vault_index.py --rebuild"]
```

---

## Key File Paths

| File | Purpose |
|---|---|
| `server.py` | FastAPI backend: REST API endpoints, dynamic Mermaid compilation, state hydration |
| `bridge.py` | CLI bridge subprocess: `wait-answer`, `advance-node`, `shuffle-quiz` |
| `state/active_session.json` | Ephemeral pointer: active topic, phase, active_node_id, reference_scope |
| `state/knowledge_graph.json` | Global persistent node/edge knowledge cosmos across all topics |
| `state/cache/<topic_slug>/` | Topic-scoped lookahead verification cache (`verification_<node_id>.json`) |
| `state/pause.flag` | Sentinel file; bridge exits with code 2 when present |
| `notes/<Topic>/manifest.json` | Canonical curriculum DAG specification for the topic vault |
| `notes/<Topic>/<node_id>.md` | Atomic Obsidian-compliant vault note with YAML frontmatter |
| `notes/<Topic>/.session/` | Ephemeral directory holding `quiz.json` and `answer.json` |
| `notes/<Topic>/.diagnostic/` | Diagnostic directory holding baseline quiz and prior candidate scans |
| `.agents/prior_knowledge_crawler.md` | Prior Knowledge Crawler sub-agent contract |
| `.agents/theoretical_verifier.md` | Theoretical Verifier sub-agent contract |

---

## Pause & Resume Flow

```
flowchart TD
    P["POST /api/pause"] --> PF["Creates state/pause.flag\nSets phase: PAUSED in active_session.json"]
    PF --> BR["bridge.py detects pause.flag\nExits code 2 → [SESSION: PAUSED]"]
    BR --> WAIT["Agent outputs standby notification\nServer stays live on :8000"]
    WAIT --> R[".resume <topic>"]
    R --> RC["Read notes/<topic>/manifest.json\nFind active or first non-completed node"]
    RC --> VP["Verify cache in state/cache/<topic_slug>/"]
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

**Shutdown** (via Python, consistent cross-platform execution):
```
python -c "import urllib.request; req = urllib.request.Request('http://localhost:8000/api/shutdown', data=b'', headers={'Content-Type': 'application/json'}); urllib.request.urlopen(req, timeout=2)"
```
