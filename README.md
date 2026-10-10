# Socratic Hub: Autonomous Pedagogical Learning Engine

[![Version: 3.0.0](https://img.shields.io/badge/Version-3.0.0-blue.svg)](CHANGELOG.md)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python Version](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)
[![Tests](https://img.shields.io/badge/Tests-Passing-brightgreen.svg)](scripts/tests/)
[![Architecture](https://img.shields.io/badge/Architecture-Encapsulated%20Vaults-orange.svg)](#architecture--specifications)
[![Pedagogy](https://img.shields.io/badge/Pedagogy-Alvar%20Method-purple.svg)](#pedagogical-framework)

> **Quick AI Agent Setup**  
> Paste this single prompt into your IDE agent (Antigravity, Cursor, Claude Code, or Windsurf) in an empty folder:
> ```text
> Clone [https://github.com/DownMD/socratic-hub](https://github.com/DownMD/socratic-hub) into this empty workspace, then read and execute INIT.md to set up the learning hub for this IDE.
> ```
>
> **Quick AI Agent Update**  
> Already have Socratic Hub installed? Paste this prompt into your existing workspace agent:
> ```text
> Pull latest changes from origin main, install any new dependencies from requirements.txt, and restart server:app on port 8000.
> ```

---

Socratic Hub is an autonomous, stateful, and topic-agnostic learning engine based on the Alvar Method (formalized through the Amos Blomqvist 1-on-1 tutoring framework). Rather than delivering passive text dumps or unstructured chat responses, Socratic Hub transforms any subject into an interactive pedagogical journey governed by active recall, topological prerequisite graphs, and adversarial verification.

Mastery must be demonstrated through structured, multi-tier diagnostic checkpoints before downstream nodes unlock. Every verified lesson is synthesized into an Obsidian-compatible local knowledge vault in real time.

---

## What's New

### v3.0.0 — Self-Contained Vaults & Sub-Agent Orchestration
* Encapsulated Topic Vaults: Purged all shared root state skeletons (state/curriculum.json, state/quiz.json). All curriculums, lesson notes, and active session checkpoints are isolated inside self-contained topic vaults (notes/<Topic>/manifest.json and notes/<Topic>/<node_id>.md).
* Sub-Agent Pipeline (.agents/):
  * prior-knowledge-crawler: Crawls historical topic vaults during diagnostic probing to categorize concepts (REUSE_CANONICAL, EXTEND_CONTEXT, DOMAIN_HOMONYM, NOVEL) and prevent redundant notes.
  * theoretical-verifier: Adversarial academic auditor executing Tier 1 local textbook citation extraction and Tier 2 live web grounding to catch misconceptions before authoring.
* Zero-Token Static Read Mode: Inspect and study any existing topic vault directly from the dashboard without invoking an active LLM loop.
* Vault Search & Status Filtering: Search topic vaults across all child concepts and filter by status ([ALL], [IN PROGRESS], [COMPLETED]) or domain tags.
* HUD Branch Jumper & Resizer Hardening: Relocated translucent parallel branch navigation HUD to the roadmap panel with pointer-capture drag resizing and center-to-center SVG zoom math.

### v2.1.0 — Knowledge Cosmos & Visual Tuning
* Dynamic Radial Geometry: Multi-discipline topics project along balanced angular rays with automatic inner-void scaling, eliminating spoke crowding across 50+ topics.
* Golden-Ratio Spectral Palette: Each discipline dynamically inherits high-contrast chromatic families (137.5 deg), with mastered nodes casting real-time Canvas glow bloom in their topic's native hue.
* Zero-Physics LOD Dimming: High-performance canvas filtering dims unselected domains without reheating simulation physics.

---

## Engine in Action

### 1. Interactive Roadmap & Knowledge Graph
Visualize topological dependencies, completed milestones, and active branches in real time via dynamic Mermaid DAGs and the interactive 2D Knowledge Cosmos.
<p align="center">
  <img src="assets/roadmap-preview.png" alt="Curriculum Traversal & Roadmap" width="850">
</p>

### 2. Socratic Probing & Active Recall Dialogue
Engage in focused, step-by-step dialogue where every lesson demands active synthesis rather than passive absorption.
<p align="center">
  <img src="assets/socratic-session.png" alt="Active Recall Dialogue Session" width="850">
</p>

### 3. Live Verification & Mastery State
Multi-tier diagnostic gates and lookahead academic audits verify concept retention and textbook rigor before advancing.
<p align="center">
  <img src="assets/verification-flow.png" alt="Automated State & Node Verification" width="850">
</p>

---

## Pedagogical Framework

Socratic Hub structures learning around three core computational pillars:

### 1. First-Principles Scaffolding
* Topological Prerequisite Decomposition: Complex subjects are broken down into granular atomic nodes (12-25+ nodes per topic) structured as a Directed Acyclic Graph (DAG).
* Zero Orphan Concepts: Every lesson explicitly connects back to foundational primitives or previously verified baseline nodes. No floating facts.
* Parallel Track Depth: The engine generates parallel prerequisite tracks, ensuring foundational mechanics are internalized prior to studying operational trade-offs.

### 2. Active Probing over Passive Reading
* Diagnostic Boundary Probing: When introducing a topic, Socratic Hub conducts targeted multi-track diagnostic probing (Tier 1 Primitives, Tier 2 Core Mechanics, Tier 3 Advanced Integration) to discover your exact knowledge boundary without wasteful repetition.
* Anti-Guessing Guardrails: Success at intermediate mechanics triggers advanced edge checks to rule out lucky guesses, while failures automatically identify prerequisite floors.
* Strict Mastery Gating: Learners advance only upon passing randomized, adversarial 3-tier assessments (grounding definitions, operational trade-offs, and misconception traps).

### 3. Self-Healing & Decoupled State
* Stateful Topic Isolation: Engine progress is decoupled from transient LLM context windows and maintained on disk in self-contained topic vaults (notes/<Topic>/manifest.json and state/active_session.json).
* Obsidian-Ready Knowledge Vault: Completed nodes write atomically to Markdown (notes/<Topic>/<node_id>.md) with YAML frontmatter, callouts, and cross-track wikilinks.
* Deterministic Resumability: Sessions can pause, recover, or survive IDE restarts with zero loss of curriculum state or progress history.

---

## Why Socratic Hub?

| Feature | Standard LLM Chat (ChatGPT, Claude) | Socratic Hub |
|---|---|---|
| Learning Mode | Passive reading / wall of text | Active recall, step-by-step Socratic dialogue |
| Pacing | Unconstrained, easy to skim | Strict progression gating—mastery unlocks next node |
| Curriculum Structure | Flat, linear, or ad-hoc explanations | Topological DAG with dependency tracking |
| Prior Knowledge | Assumed or re-explained from scratch | Automated multi-track diagnostic baseline probing |
| Note Taking | Copy-paste manually from chat | Automatic generation of Obsidian-ready markdown vault |
| Privacy & Storage | Ephemeral, hosted on third-party cloud | 100% local files, local state, and local web dashboard |

---

## Universal Topic Agnosticism

Socratic Hub contains no hardcoded subject domains. Its structural decomposition applies across any field:

* Systems Engineering & Computer Science:
  .teach Distributed Consensus and Raft Protocol
  .teach Linux eBPF Kernel Tracing

* Linguistics & Natural Languages:
  .teach Mandarin Phonology and Tonal Contours
  .teach PIE Morphological Reconstruction

* Quantitative Finance & Economics:
  .teach Black-Scholes Model and Option Greeks
  .teach Central Bank Liquidity Mechanics

* Biomedical & Natural Sciences:
  .teach CRISPR-Cas9 Gene Editing Mechanisms
  .teach Organic Chemistry Stereochemistry

---

## Quickstart

### Prerequisites
* Python 3.10+
* Git

### 1. Clone & Set Up Workspace
git clone https://github.com/DownMD/socratic-hub.git
cd socratic-hub

Recommended: Create and activate a Python virtual environment:
# macOS/Linux
python3 -m venv .venv
source .venv/bin/activate

# Windows (PowerShell)
python -m venv .venv
.venv\Scripts\Activate.ps1

### 2. Install Dependencies
python -m pip install -r requirements.txt

### 3. Launch Local Server
Start the local dashboard and API engine at http://localhost:8000:
python -m uvicorn server:app --host 127.0.0.1 --port 8000 --no-access-log

### 4. Start Learning
In your IDE's agent chat window (Antigravity, Cursor, Claude Code, or Windsurf), enter:
.teach <topic>

---

## Control Commands

| Command | Action |
|---|---|
| .teach <topic> | Decomposes topic, runs diagnostic probing, builds DAG, and begins learning |
| .resume <topic> | Resumes an active or paused session at the current unmastered node |
| .stop | Archives the current session, saves progress, and pauses learning |
| .start / .open | Launches the local dashboard without altering active session state |
| .kill | Archives the session and cleanly shuts down the local background server |

---

## Supported IDEs & Agent Configurations

Socratic Hub integrates with major AI development environments via IDE-specific rule configurations pointing to the core state machine:

| Environment | Agent Instruction File | Integration Details |
|---|---|---|
| Google Antigravity | AGENTS.md | Primary state machine specification and subagent verifier rules |
| Cursor | .cursorrules | Root agent rules forwarding to AGENTS.md |
| Claude Code | CLAUDE.md | CLI agent instructions and command triggers |
| Windsurf | .windsurfrules | Cascade rules forwarding to AGENTS.md |
| GitHub Copilot | .github/copilot-instructions.md | Copilot chat persona and file boundary constraints |

Detailed setup and troubleshooting instructions are provided in INIT.md.

---

## Architecture & Specifications

Technical documentation is located in the .doc/ directory:

* .doc/pedagogy_and_agents.md — Pedagogical framework, Amos Blomqvist framework, diagnostic budgets, and pedagogical blueprints.
* .doc/roadmap_and_curriculum.md — DAG generation algorithm, topological sorting, prior knowledge scanning, and deduplication logic.
* .doc/api_and_state.md — REST API endpoints, active session tracking, and vault manifest schemas.
* .doc/architecture.md — IPC bridge mechanisms, file system state boundaries, and subagent verification pipelines.
* .doc/frontend_guide.md — Real-time reactive dashboard, Knowledge Cosmos 2D graph renderer, and theme specifications.
* .doc/maintenance.md — Vault synchronization, reference ingestion, and documentation generator scripts.

---

## Attribution

The pedagogical tenets embodied in this project—including prerequisite track partitioning, multi-tiered diagnostic probing, active recall gates, and first-principles mastery scaffolding—are based on the Alvar Method developed by educational theorist Eero Alvar, implemented via the Amos Blomqvist 1-on-1 tutoring architecture.

Socratic Hub provides the autonomous software implementation: multi-agent coordination, file-based state orchestration, interactive web visualization, and automated knowledge graph synthesis.

---

## License

This project is licensed under the MIT License. Copyright (c) 2026 Down MD.
