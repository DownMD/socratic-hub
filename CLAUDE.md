# Socratic Hub: Claude Code instructions

@AGENTS.md

<!-- AGENTS.md is the source of truth. The notes below only tune behavior for a terminal CLI. Repair via INIT.md. -->

## Terminal / headless rules
- Run everything non-interactively with `python ...`. Never wait on a prompt.
- Keep stdout minimal. Do not echo JSON, notes, or quiz content to the terminal. Print only the whitelisted status templates from AGENTS.md.
- Silence noisy commands (`> NUL 2>&1` on Windows, `> /dev/null 2>&1` elsewhere) unless you need their exit code or stdout (`advance-node` stdout is authoritative).
- Blocking step is `python bridge.py wait-answer --timeout 180`. Exit code 2 means pause: emit `[SESSION: PAUSED]` and end the turn.
- Do not edit `server.py`, `bridge.py`, or `static/*` while teaching. Stay inside `state/` and `notes/`.
- Health check: `python -c "import urllib.request; print(urllib.request.urlopen('http://localhost:8000/api/state', timeout=3).read().decode())"`.
