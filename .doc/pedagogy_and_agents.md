# Pedagogy & Agents

> Last rebuilt: .doc --all (2026-10-03)

---

## The Amos Blomqvist Teaching Framework

The agent implements a **Socratic 1-on-1 pedagogical loop** with four phases:

| Phase | State Value | What Happens |
|---|---|---|
| `probing` | `phase: "probing"` | Diagnostic MCQs establish the learner's knowledge boundary |
| `teaching` | `phase: "teaching"` | One node at a time: notes written → quiz served → bridge polls answer |
| `completed` | `phase: "completed"` | Final node passed; vault indexed |
| `idle` | `phase: "idle"` | No active session |

---

## Phase 1: Diagnostic Probing Algorithm

### Multi-Track Prerequisite Partitioning

Before writing any diagnostic questions, the agent decomposes the topic into its **distinct parallel prerequisite tracks** (e.g., for `<Topic Name>`: foundational track vs. applied mechanics track). Each track is probed independently — never collapsed into a single linear ladder.

### Diagnostic Tiers

Each track has 3 tiers:

| Tier | Scope | Strategy |
|---|---|---|
| Tier 1 | Prerequisites & Primitives | Probed only on failure at Tier 2 |
| Tier 2 | Core Mechanics & Operational Trade-offs | **Starting probe** for each track |
| Tier 3 | Advanced Integration & Edge Dynamics | Probed on success at Tier 2 (anti-guessing guard) |

### Question Budget

```
Budget = clamp(3, 2 × [number of prerequisite tracks], 8)
```

- 1 track → 3–5 questions
- 2–3 tracks → 5–8 questions
- **Hard ceiling: never exceed 8 questions** regardless of topic complexity.

### Quiz Delivery & Baseline Capture

1. Write `state/quiz.json` with `question`, `options`, `correct_idx`, `explanation`.
2. Run `bridge.py wait-answer --timeout 180`.
3. On pass: register concept via `POST /api/graph/sync` with `status: "mastered"`, `origin: "diagnostic"`, `badge_label: "Baseline Knowledge"`.

---

## Phase 2: Plan & Verify

### Universal Domain Depth

The agent generates **12 to 25+ granular nodes** regardless of local reference corpora. A representative curriculum for `<Topic Name>` may have 12–25+ nodes across parallel tracks.

### Adaptive Topology Selection

| Architecture | Use When |
|---|---|
| **Multi-Track Lattice** | Complex domains with intersecting theoretical + practical tracks |
| **Strict Sequential Pipeline** | Purely cumulative procedural or algorithmic topics |
| **Hub-and-Spoke / Radial** | Topic centred on a single core equation or engine that powers sub-domains |
| **Hybrid Pipeline-Branching** | Sequential foundational trunk that bifurcates into specialised parallel tracks |

### Pre-Audit Strategy

| Tier | Method | Tag |
|---|---|---|
| Tier 1 | `scripts/locate_text.py --query <concept> --limit 2` | `[VERIFIED]` |
| Tier 2 | Authoritative external web search | `[VERIFIED_WEB]` |

**Zero-Pruning Invariant**: The verifier must **never** emit `[INVALID_PREREQUISITE]` or prune a node solely because it is absent from local reference files.

### Baseline Contract Immutability

Before drafting `state/roadmap.mmd` or `state/curriculum.json`, the agent **must** read `state/knowledge_graph.json` and reuse Phase 1 baseline node IDs and titles **verbatim**. Rephrasing is strictly prohibited.

---

## Phase 3: Teaching Loop

### Strict One-Node-at-a-Time Sequencing

```
Node N active
  → Write notes (lesson_notes.md + notes/<topic>/<node_id>.md)
  → Write quiz (state/quiz.json)
  → [HEADLESS notification]
  → bridge.py wait-answer
  → On pass: bridge.py advance-node
  → Node N+1 active
```

### Exact Header Invariants

Every lesson appended to `notes/lesson_notes.md` must match **character-for-character** the `title` field in `state/curriculum.json`:

```
## Node <N>: <Exact Title from curriculum.json>
```

And for baseline notes:
```
## Baseline: <Exact Concept Title>
```

These patterns are parsed by `bridge.py advance-node` via regex to extract the section for vault archival.

### Headless Chat Policy

The agent **never** outputs lesson markdown, quiz questions, or syllabus overviews into the chat. The only permitted chat output is the monospace notification:

```
[NODE <N> ACTIVE: <NODE TITLE>]
-----------------------------------------------------
Lesson notes and batch assessment live at http://localhost:8000.
Awaiting submission via dashboard.
-----------------------------------------------------
```

---

## Domain-Adaptive Scaffolding Blueprints

### Blueprint 1: Quantitative & Engineering Domains

- `### The Core Mechanism` — concrete system explanation without jargon
- `### Intuition & Physical Mental Model` — analogy before math
- `### Mathematical Formulation` — KaTeX (`$...$`, `$$...$$`) with explicit variable definitions
- `### Operational Trade-offs & Traps` — bottlenecks, edge conditions
- `### Practitioner Heuristic` — 1–2 sentence diagnostic rule

### Blueprint 2: Language Acquisition & Humanities

- `### The Communicative Job` — what the pattern does and what nuance it conveys
- `### Sentence Pattern & Structure` — Markdown visual pattern boxes (no pseudo-algebraic LaTeX)
- `### Contrast Matrix` — mandatory Markdown table for confusable markers (e.g., に vs で)
- `### Real-World Examples` — full native text + romaji + literal + natural gloss
- `### The English Speaker's Trap` — incorrect vs correct sentences highlighting L1 interference
- `### Decision Heuristic` — 3-second mental test

### Blueprint 3: Practical Skills, Hobbies & Workflows

- `### The Objective` — what success looks and feels like
- `### Step-by-Step Mechanics` — sequenced actionable steps
- `### Diagnostic Feedback` — tactile/visual/output cues for wrong technique
- `### Common Beginner Errors & Fixes` — Markdown table: Symptom → Root Cause → Correction

### Blueprint 4: Business, Strategy & Management

- `### The Core Strategic Friction` — fundamental trade-off, conflicting incentives, resource bottleneck
- `### Framework Mechanics` — interlocking incentives, constraints, and feedback loops (no buzzwords)
- `### Concrete Scenario` — specific operational case with defined roles and constraints
- `### Strategic Trade-Off Matrix` — Markdown table: Option / Immediate Benefit / Hidden Cost / Second-Order Risk
- `### Managerial Heuristic` — 1–2 sentence decision rule for allocation under uncertainty

### First-Principles Domain Inference Engine (Unmatched Domains)

For topics that don't fit Blueprints 1–4 (law, history, biology, philosophy, etc.):

1. `### The Core Dilemma / Driving Question` — what fundamental problem does this concept solve?
2. `### Working Mechanism & Causal Chain` — step-by-step cause → effect breakdown
3. `### Concrete Anchor Case` — real-world instance or experiment
4. `### Practical Mental Filter` — simple diagnostic rule or test

---

## Voice Directive

The agent writes like a **senior practitioner sketching on a whiteboard**. Specifically banned:
- Academic posturing: "ubiquitous", "pervasive", "conflates", "transpires", "predication", "locus", "paradigm"
- Corporate filler: "synergy", "holistic paradigm", "strategic alignment"
- Treating grammar as algebra: no `Predicate = [NP] + V` LaTeX blocks for language topics

---

## Visual Diagram Semantics

| Diagram Type | When to Use |
|---|---|
| `flowchart LR` | Genuine multi-stage material flows where items physically move workstation to workstation |
| `flowchart TD` | Decision rules, branching logic, particle/form selection |
| Markdown table | Comparing 2–4 distinct concepts — preferred over complex diagrams |

**Never** draw grammar taxonomies or part-of-speech hierarchies as conveyor-belt horizontal flows.

---

## Verification Pipeline

### Adversarial Verifier Strategy

1. **Tier 1**: Run `scripts/locate_text.py --query "<concept>" --limit 2` against `references/processed/`.
   - Returns: `document_title`, `page_start`, `page_end`.
   - Tags the audit as `[VERIFIED]` with citation.
2. **Tier 2**: If not found locally, search authoritative external sources.
   - Tags the audit as `[VERIFIED_WEB]`.
3. If a genuine `[CONTRADICTION]` is found: adopt the textbook formulation and include a conflicting-intuition callout in the notes.
4. If `[UNVERIFIED]`: halt progression and emit `[AUDIT_FAILED]` in chat.

### Sliding-Window Lookahead (Horizon = 2)

While Node N is active and `bridge.py wait-answer` is running, the agent dispatches background verification for Nodes N+1 and N+2:
- Saves to `state/cache/verification_<node_id>.json` using the **exact** `id` from `state/curriculum.json`.
- These run **asynchronously** (via detached subagent tasks) and must **never block** the active teaching UI.
- `bridge.py advance-node` checks the cache and promotes it — or falls back to synchronous verification.

---

## Assessment Standards

Each node quiz has exactly **3 questions**:

| Question | Type |
|---|---|
| Q1 | Grounding definition (what is X?) |
| Q2 | Operational trade-off (when to use X vs Y?) |
| Q3 | Adversarial misconception check (what is NOT true about X?) |

- Options are **randomised** before writing to `state/quiz.json` via `bridge.py shuffle_quiz()`.
- The shuffle is deterministic: identify correct option string → shuffle list → recompute index.
- `correct_idx` and `correct_index` are both updated after shuffle.
- A quiz is considered passed if `score >= 0.70` OR `passed: true` OR `correct_count == total`.

---

## Global Operational Bans

| Ban | Rule |
|---|---|
| `[BAN] A` | Never scan, grep, or read `server.py`, `bridge.py`, `static/index.html`, `static/app.js`, `static/styles.css` during teaching |
| `[BAN] B` | Never run `scripts/sync_vault_index.py --rebuild` during an active teaching session |
| `[BAN] B` | Never run `scripts/scan_prior_knowledge.py` sequentially per concept — batch only |
| `[BAN] B` | Never read `state/roadmap.mmd`, `state/curriculum.json`, or `state/verification.json` immediately after `bridge.py advance-node` — trust stdout |
| `[SEQUENCE] D` | Never generate `state/quiz.json` before `notes/lesson_notes.md` is written |
