> **Quick AI Agent Setup**  
> Paste this single prompt into your IDE agent (Cursor, Claude Code, Antigravity, or Windsurf) in an empty folder:
> ```text
> Clone https://github.com/DownMD/socratic-hub into this empty workspace, then read and execute INIT.md to set up the learning hub for this IDE.
> ```

# Socratic Hub

**Socratic Hub is an AI tutor that doesn't just lecture or dump text on you.** It teaches one small step at a time, checks that you understood with a quiz, and saves your notes to an Obsidian-compatible vault.

## Why use it instead of ChatGPT?

- **You can't skip ahead.** The next lesson only unlocks after you pass the quiz for the current one.
- **You see the whole path.** Every topic gets a visual Mermaid roadmap showing what to learn and in what order.
- **Your notes write themselves.** Each lesson you master is saved as a Markdown note in `notes/`, ready to open in Obsidian.
- **It runs on your machine.** The dashboard and all your notes and progress are stored locally in plain files. Nothing is sent to a hosted service by this project.

## How it works

1. **Diagnose:** a few quick questions find out what you already know, so you don't relearn it.
2. **Roadmap:** the tutor builds a step-by-step plan for your topic and shows it as a diagram.
3. **Lesson:** you get one short lesson at a time on the dashboard at `http://localhost:8000`.
4. **Quiz & Save:** you take a short quiz. Pass it and the lesson is saved to your vault, and the next one opens.

## Quickstart

1. **Clone** the repo and open it in your IDE:
   ```bash
   git clone https://github.com/DownMD/socratic-hub.git
   cd socratic-hub
   ```
2. **Install** the dependencies (Python 3.10+):
   ```bash
   python -m pip install -r requirements.txt
   ```
3. **Start** the server, then open <http://localhost:8000>:
   ```bash
   python -m uvicorn server:app --host 127.0.0.1 --port 8000 --no-access-log
   ```
   Port 8000 is fixed. If something else is using it, ask your agent to follow [`INIT.md`](INIT.md).
4. **Learn:** in your IDE's AI chat, type:
   ```text
   .teach <topic>
   ```

Not sure where to start? Paste the one-line prompt at the top of this page into your AI chat and it will set everything up for you.

### Commands

| Command | What it does |
|---|---|
| `.teach <topic>` | Start learning a new topic |
| `.resume <topic>` | Pick up where you left off |
| `.stop` | Save and pause the current session |
| `.start` / `.open` | Start the dashboard |
| `.kill` | Save and shut the server down |

## Supported IDEs

Open the repo in your IDE and it picks up its own instructions file.

| IDE | Instructions file |
|---|---|
| Antigravity | `AGENTS.md` |
| Cursor | `.cursorrules` |
| Claude Code | `CLAUDE.md` |
| Windsurf | `.windsurfrules` |
| GitHub Copilot | `.github/copilot-instructions.md` |

`AGENTS.md` is the main rulebook; the others point back to it. Setup or repair help is in [`INIT.md`](INIT.md).

## Pedagogy & Attribution

The teaching ideas here (checking prior knowledge first, tiered mastery checks, one concept at a time, practical lesson style) come from the **Amos Blomqvist framework by Eero Alvar**. This project does not own or redefine that framework. It is the software that puts it to work: the multi-agent orchestration, the backend, and the visualizations (dashboard, knowledge graph, roadmaps).

More technical detail lives in [`.doc/`](.doc/).

## License

[MIT](LICENSE). Copyright (c) 2026 Down MD.
