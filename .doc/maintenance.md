# Maintenance Procedures (.doc, .gem, .refer)

Loaded on demand when the user invokes `.doc`, `.doc --all`, `.gem`, or `.refer`. These tasks run outside a teaching loop; the `state/` and `notes/` perimeter in `AGENTS.md` applies to teaching turns only.

---

## 1. Generate Modular Documentation (`.doc`, `.doc --all`)

### Command Variants & Scope
- **`.doc` (default)**: Incremental update covering recent changes or the currently active topic module.
- **`.doc --all`**: Exhaustive repository-wide architecture, schema, frontend, and pedagogical audit resulting in a comprehensive rebuild and synchronization of the entire `.doc/` suite across all modules.

### Exclusion List
Skip the following directories and files during documentation audits:
- `state/` (MANDATORY: Active user session state must NEVER be scanned or read during documentation generation; all schemas must use canonical mock constants)
- `notes/` (MANDATORY: User lesson notes and personal vaults must NEVER be scanned or leaked into documentation)
- `references/` and `references.*`
- `.git/`
- `__pycache__/`
- `.venv/` and `env/`
- Static media, assets, and fonts.

### Canonical Mock Schemas (`scripts/generate_docs.py`)
Documentation specifications must remain strictly topic-agnostic. All markdown schema examples in `.doc/` MUST use canonical mock state definitions from `scripts/generate_docs.py` rather than reading from active working files:
```python
DOC_MOCK_STATE = {
    "topic": "<Topic Name>",
    "phase": "idle",
    "active_node_id": "<Node ID>",
    "active_node": "<Node Title>",
    "reference_scope": {"collection": "general", "tags": []}
}
```

### Execution Procedure for `.doc --all`
Execute an exhaustive repository-wide audit and synchronize all target documentation files:
1. **Backend Audit**: Scan backend routes, state machines, and background process runners (`server.py`, `bridge.py`).
2. **Frontend Audit**: Scan frontend layout, D3 visualization loops, Mermaid zoom/pan, and event bindings (`index.html`, `static/app.js`, `static/styles.css`).
3. **State & Validation Audit**: Inspect code-level state contracts in `server.py` and `bridge.py` against `DOC_MOCK_STATE`. NEVER read live runtime files in `state/` or `notes/`.
4. **Pedagogical & Policy Audit**: Scan pedagogical blueprints, voice directives, and verification pipelines (`AGENTS.md`).
5. **Target Artifact Rebuild**: Synchronize and update the documentation suite in `.doc/` (or run `python scripts/generate_docs.py --rebuild`):
   - `.doc/architecture.md`: System topology, client-server sync, and session lifecycle.
   - `.doc/api_and_state.md`: FastAPI route registry, state schemas, and caching invariants.
   - `.doc/frontend_guide.md`: UI panels, D3/Mermaid integration, CSS design tokens, and hotkeys.
   - `.doc/pedagogy_and_agents.md`: Domain blueprints, first-principles fallback logic, and verification rules.
   - `.doc/roadmap_and_curriculum.md`: DAG synthesis, fuzzy token-set deduplication, and quiz progression.
6. **Leakage Verification**: Run `python scripts/generate_docs.py --check` to assert zero state leaks.

Output upon completion:
```
[DOC REBUILD COMPLETE]
-----------------------------------------------------
All 5 documentation modules in .doc/ synchronized:
- .doc/architecture.md
- .doc/api_and_state.md
- .doc/frontend_guide.md
- .doc/pedagogy_and_agents.md
- .doc/roadmap_and_curriculum.md
-----------------------------------------------------
```

---

## 2. Generate AI Collaborator Primer (`.gem`)
- Inspect workspace and compile `AIStartupGuide.md` at workspace root.
- Output: "AI Collaborator context compiled to AIStartupGuide.md. You can copy-paste its contents into a new AI session."

---

## 3. Ingest & Pre-Process References (`.refer`)
- Standard: `python scripts/ingest_references.py`. Formulate 3-5 tags for untagged documents in `references/tags.json` and re-run.
- Catalog Listing: `python scripts/ingest_references.py --list` (with optional `--collection <name>` or `--tag <name>`).
- Rebuild: `python scripts/ingest_references.py --rebuild`.
