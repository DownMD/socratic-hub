# INIT.md: Bootstrap & Repair Guide

This file is written for an AI coding agent. Execute the steps in order. Every command is a `python` one-liner so it works in PowerShell, cmd, bash and zsh. Run all commands from the repository root.

The rule files (`.cursorrules`, `CLAUDE.md`, `.windsurfrules`, `.github/copilot-instructions.md`) are committed to the repo. Use this file to **repair** them or to bootstrap a fresh clone. `AGENTS.md` is always the source of truth.

## 1. Detect your harness

Check in this order and stop at the first match. Do not guess from the model name.

| Signal | Harness | Rule file |
|---|---|---|
| `.cursor/` exists, or `CURSOR_*` env vars, or you are Cursor | Cursor | `.cursorrules` |
| `CLAUDECODE` / `CLAUDE_CODE*` env var, or you are a terminal-only CLI agent | Claude Code | `CLAUDE.md` |
| `.windsurf/` exists, or `WINDSURF_*` / `CODEIUM_*` env vars | Windsurf | `.windsurfrules` |
| You are GitHub Copilot (agent or chat) | Copilot | `.github/copilot-instructions.md` |
| Antigravity, or anything else that reads `AGENTS.md` natively | Antigravity / generic | none (use `AGENTS.md`) |

If detection is ambiguous, treat all four rule files as required.

## 2. Verify / repair the rule file

For your harness, check the file exists:

```
python -c "import pathlib,sys; f=sys.argv[1]; print('OK' if pathlib.Path(f).is_file() else 'MISSING')" .cursorrules
```

- `OK`: leave it untouched. Never overwrite a user-edited file.
- `MISSING`: recreate it from the matching template below, or restore it with `git checkout -- <file>`.

Templates, in short (each starts with `<!-- Source of truth: AGENTS.md. On any conflict, AGENTS.md wins. -->`):

- **`.cursorrules`**: front-load bans (never edit `server.py`, `bridge.py`, `static/*` during teaching; never grep server/frontend source; never write lesson text in chat; never write outside `state/` and `notes/`), then the role, triggers and chat whitelist.
- **`CLAUDE.md`**: `@AGENTS.md` import, then headless-CLI rules: non-interactive `python` commands, minimal stdout, `wait-answer` exit code 2 means pause.
- **`.windsurfrules`**: file-driven state sync: re-read `state/*.json` every turn, atomic writes, one `POST /api/graph/sync`, `advance-node` stdout is authoritative.
- **`.github/copilot-instructions.md`**: tutor role, boundary contracts (file perimeter, chat whitelist, header contract), 3-phase summary.
- **Antigravity / native**: nothing to create.

## 3. Install dependencies

```
python -m pip install -r requirements.txt
```

Only `fastapi`, `uvicorn`, `pydantic` (server) and `pypdf` (reference ingestion) are third-party. `bridge.py`, `scripts/locate_text.py`, `scripts/scan_prior_knowledge.py` and `scripts/sync_vault_index.py` use only the standard library.

## 4. Check port 8000 and launch the server

The port is fixed at 8000 (`server.py` and `bridge.py` both use it).

**4a. Is our server already running?**

```
python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/state', timeout=2); print('OURS')"
```

If it prints `OURS`, skip to step 5. Do not launch a second server.

**4b. Is the port taken by something else?**

```
python -c "import socket,sys; s=socket.socket(); s.settimeout(0.5); sys.exit(0 if s.connect_ex(('127.0.0.1',8000))==0 else 1)"
```

Exit code `0` means another process owns port 8000. **Stop** and tell the user:

```
[PORT_CONFLICT] Port 8000 is in use by a process that is not the learning hub. Free the port and re-run INIT.md. Do not kill the other process yourself.
```

**4c. Port is free: launch detached and silent**

```
python -c "import subprocess,sys,os; kw=dict(creationflags=0x208) if os.name=='nt' else dict(start_new_session=True); subprocess.Popen([sys.executable,'-m','uvicorn','server:app','--host','127.0.0.1','--port','8000','--no-access-log'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,**kw)"
```

Wait one second (`python -c "import time; time.sleep(1)"`), then repeat 4a. Retry up to 3 times. If it still fails, report the failure and stop.

## 5. Verify starter state

```
python -c "import json; [json.load(open(f,encoding='utf-8')) for f in ('state/topic.json','state/knowledge_graph.json','state/curriculum.json')]; print('STATE OK')"
```

If a file is missing or invalid, restore it with `git checkout -- <file>`. Clean starter values:

- `state/topic.json`: `{"topic": "", "phase": "idle", "active_node_id": null, "active_node": null, "reference_scope": {"collection": "general", "tags": []}}`
- `state/knowledge_graph.json`: `{"nodes": [], "edges": []}`
- `state/curriculum.json`: `{"nodes": []}`
- `state/roadmap.mmd`: the four `classDef` lines only (`completed`, `active`, `pending`, `mastered`).

## 6. Stop git status churn (skip-worktree)

These tracked files are rewritten at runtime. Mark them so your local study progress does not show up in `git status` or get committed by accident. Skip this step if the directory is not a git repository.

```
python -c "import subprocess; subprocess.run(['git','update-index','--skip-worktree','state/topic.json','state/knowledge_graph.json','state/curriculum.json','state/roadmap.mmd','notes/lesson_notes.md'],check=False)"
```

To reverse it (for example, to commit an intentional template change):

```
python -c "import subprocess; subprocess.run(['git','update-index','--no-skip-worktree','state/topic.json','state/knowledge_graph.json','state/curriculum.json','state/roadmap.mmd','notes/lesson_notes.md'],check=False)"
```

## 7. Hand off

Reply with the `[ONLINE]` message from `AGENTS.md` section 2. Then wait for the user to run `.teach <topic>` or `.resume <topic>`.
