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

1. Write `notes/<topic>/.diagnostic/diagnostic_quiz.json` with `question`, `options`, `correct_idx`, `explanation`.
2. Run `bridge.py wait-answer --timeout 180`.
3. On pass: register concept via `POST /api/graph/sync` with `status: "mastered"`, `origin: "diagnostic"`, `badge_label: "Baseline Knowledge"`.
4. Synthesize atomic baseline note directly in `notes/<topic>/<node_id>.md` (frontmatter: `id`, `title`, `domain`, `status: "mastered"`, `origin: "diagnostic"`, wikilinks).

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

Before drafting `notes/<topic>/manifest.json`, the agent **must** read `state/knowledge_graph.json` and reuse Phase 1 baseline node IDs and titles **verbatim**. Rephrasing is strictly prohibited.

---

## Phase 3: Teaching Loop

### Strict One-Node-at-a-Time Sequencing

```
Node N active
  → Write notes directly (notes/<topic>/<node_id>.md)
  → Write quiz (notes/<topic>/.session/quiz.json)
  → [HEADLESS notification]
  → bridge.py wait-answer
  → On pass: bridge.py advance-node
  → Node N+1 active
```

### Direct Note Authoring & Frontmatter Invariants

Every lesson is authored directly into `notes/<topic>/<node_id>.md` with Obsidian YAML frontmatter matching the node in `notes/<topic>/manifest.json`:

```yaml
---
id: "<node_id>"
title: "<Exact Title from manifest.json>"
domain: "<domain>"
topic: "<Topic Name>"
status: "in_progress"
origin: "curriculum"
badge_label: "Active Lesson"
---
```

And for baseline notes:
```yaml
---
id: "<node_id>"
title: "<Exact Concept Title>"
domain: "<domain>"
topic: "<Topic Name>"
status: "mastered"
origin: "diagnostic"
badge_label: "Baseline Knowledge"
---
```

When `bridge.py advance-node` runs upon quiz completion, it directly promotes the note's frontmatter to `status: "mastered"`, updates `manifest.json`, and outputs the next node to teach.

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
- Saves to `state/cache/<topic_slug>/verification_<node_id>.json` using the **exact** `id` from `notes/<topic>/manifest.json`.
- These run **asynchronously** (via detached subagent tasks) and must **never block** the active teaching UI.
- `bridge.py advance-node` checks the cache and promotes it — or falls back to synchronous verification.

---

## Sub-Agent Architecture (.agents/)

The engine orchestrates specialized autonomous sub-agents with dedicated identity specifications:

### Prior Knowledge Crawler (`.agents/prior_knowledge_crawler.md`)
- **Role**: Semantic auditor analyzing historical vault masteries against planned curriculum concepts.
- **Trigger**: Executed in Phase 1 via `python scripts/scan_prior_knowledge.py --topic "<topic>" --output "notes/<topic>/.diagnostic/prior_candidates.json"`.
- **Classification Output**: Tags every candidate concept:
  - `REUSE_CANONICAL`: Link existing vault note directly via relative wikilink.
  - `EXTEND_CONTEXT`: Extend definition in new note while linking prior concept.
  - `DOMAIN_HOMONYM`: Disambiguate with explicit domain scoping.
  - `NOVEL`: New concept entirely.

### Theoretical Verifier (`.agents/theoretical_verifier.md`)
- **Role**: Adversarial academic auditor verifying theoretical models, operational trade-offs, prerequisites, and citations.
- **Execution**: Audits upcoming nodes (N+1, N+2) against local textbook chunks and authoritative web sources.
- **Cache Persistence**: Writes structured audit payloads directly to `state/cache/<topic_slug>/verification_<node_id>.json`.

---

## Assessment Standards

Each node quiz has exactly **3 questions**:

| Question | Type |
|---|---|
| Q1 | Grounding definition (what is X?) |
| Q2 | Operational trade-off (when to use X vs Y?) |
| Q3 | Adversarial misconception check (what is NOT true about X?) |

- Options are **randomised** before writing to `notes/<topic>/.session/quiz.json` via `bridge.py shuffle_quiz()`.
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
| `[BAN] B` | Never read `notes/<topic>/manifest.json` immediately after `bridge.py advance-node` — trust stdout |
| `[SEQUENCE] D` | Never generate `notes/<topic>/.session/quiz.json` before `notes/<topic>/<node_id>.md` is written |
