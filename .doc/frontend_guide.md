# Frontend Guide

> Last rebuilt: .doc --all (2026-10-03)

---

## Stack & Dependencies

All loaded via CDN in `static/index.html`:

| Library | Version | Role |
|---|---|---|
| **TailwindCSS** | CDN (JIT) | Utility-first dark theme layout |
| **KaTeX** | 0.16.9 | LaTeX math rendering in lesson notes and quiz |
| **Marked.js** | latest | Markdown → HTML rendering |
| **Mermaid.js** | 10 (ESM) | DAG roadmap rendering in left panel |
| **D3.js** | v7 | Force layout engine for Knowledge Cosmos graph |
| **force-graph** | unpkg | Obsidian-style canvas graph renderer |
| **Custom CSS** | `static/styles.css` | Dark prose, panel layout, drag resizer, graph styles |
| **App Logic** | `static/app.js` | 101 KB, all client-side event handling and polling |

---

## Page Layout: Three-Column Study Workspace

The active study layout (`#workspace-study`) is a 3-column flex row that takes the full viewport height minus the 4rem header.

```
┌────────────────────────────────────────────────────────────────────┐
│  [Header: ALH branding │ [COMMANDS] │ [GRAPH] │ [SAVED TOPICS]    │
│            Topic badge │ Phase badge │ [SYNC] dot │ [RESET]       │
└────────────────────────────────────────────────────────────────────┘
┌─────────────────┐┌──────────────────────────────┐┌───────────────┐
│  Panel 1        ││  Panel 2                      ││  Panel 3      │
│  [ROADMAP]      ││  [VERIFIED LESSON NOTES]      ││  [CHECKPOINT  │
│                 ││                               ││   & QUIZ]     │
│  Mermaid DAG    ││  #previous-notes-drawer       ││               │
│  (left column)  ││  (collapsed details)          ││  3x MCQ       │
│                 ││                               ││  submission   │
│  25% width      ││  #active-lesson-container     ││  form         │
│  collapsible    ││  (markdown + KaTeX render)    ││               │
│  to 44px rail   ││  flex-1, scroll-y             ││  32% width    │
│                 ││                               ││  collapsible  │
└─────────────────┘└──────────────────────────────┘└───────────────┘
```

When no session is active, `#workspace-idle` is shown instead, containing the command reference cards and the Knowledge Graph / Saved Topics quick-action buttons.

---

## Panel Collapse / Rail System

Both `#panel-roadmap` and `#panel-quiz` support collapsing to a 44px vertical rail:

- Toggled by `#btn-toggle-roadmap` / `#btn-toggle-quiz`.
- Collapsed state: class `panel-rail-collapsed` added to the panel. CSS hides `panel-header`, `#dag-scroll-area`, and `#quiz-scroll-area`, and shows the `#roadmap-collapsed-rail` / `#quiz-collapsed-rail` containers instead.
- Collapsed rail shows a vertical monospace label (`.rail-vertical-label` with `writing-mode: vertical-rl`).
- Clicking the rail re-expands the panel.

**Draggable Resizer** (`#roadmap-resizer`): A 6px `col-resize` divider between Panel 1 and Panel 2. Drag events in `app.js` utilize Pointer Capture (`setPointerCapture`) to prevent cursor escape during rapid movement and dynamically update Panel 1 width as a percentage of the container.

---

## Left Panel: Mermaid DAG Roadmap

**Container**: `#dag-scroll-area` → `#dag-container`

- Mermaid.js is loaded as an ES module with `startOnLoad: false` and a dark theme.
- `window.mermaid = mermaid` is set on the `mermaid-ready` event so `app.js` can call it.
- On state update, `app.js` injects the `dag_mermaid` string into a `<div class="mermaid">` element and calls `mermaid.run()`.
- The active node count is shown in `#dag-node-count`.
- Mermaid SVG styling: `max-width: none; width: auto; min-height: 100%; height: auto` — never clipped.
- **HUD Branch Jumper** (`#roadmap-branch-hud`): Compact bottom-docked branch jumper displaying active tracks and enabling fast navigation across parallel prerequisite tracks without obscuring the diagram canvas.

**CSS class semantics** (applied by `bridge.py update_roadmap_styling`):

| Class | Colour | Meaning |
|---|---|---|
| `classDef completed` | `stroke:#22c55e` (green) | Node quiz passed and archived |
| `classDef active` | `stroke:#38bdf8` (bright cyan) | Currently active lesson node |
| `classDef pending` | `stroke:#475569` (dim slate) | Not yet reached |
| `classDef mastered` | `stroke:#22c55e` (green) | Baseline diagnostic mastery |

**Click-to-expand**: Clicking a Mermaid container (`cursor: zoom-in`) opens a lightbox modal with a larger SVG rendering.

---

## Center Panel: Verified Lesson Notes

**Container**: `#notes-panel` → `#lesson-content`

**Previous Notes Drawer** (`#previous-notes-drawer`):
- `<details>` element, initially `display: none`.
- Shows when there are completed node sections above the active lesson.
- Summary text: `[+] Completed Module Notes (Nodes 1 to N-1)`.

**Active Lesson Container** (`#active-lesson-container`):
- `app.js` renders the markdown from `lesson_markdown` via `marked.parse()`.
- After rendering, it calls KaTeX `renderMathInElement()` to render any `\(...\)` or `$$...$$` blocks.
- Inline Mermaid diagrams in lesson notes are detected and re-run via `mermaid.run()` after insertion.

**Reference Mode Banner** (`#reference-mode-banner`):
- Displayed as a sticky top bar when the user clicks a node in the Knowledge Graph modal to read its archived note.
- Shows the node title and a `[RETURN TO ACTIVE LESSON]` button that calls `returnToActiveLesson()`.

---

## Right Panel: Checkpoint & Quiz

**Container**: `#quiz-scroll-area` → `#quiz-container`

- `app.js` detects a new `active_quiz` payload and renders the 3-question form dynamically.
- Each question renders options as radio buttons.
- On submit: calls `POST /api/submit-quiz` with `answers: [selected_idx_q1, selected_idx_q2, selected_idx_q3]`.
- After submission, renders per-question feedback (correct/incorrect + explanation).
- **Pause Session button** (`#btn-pause-session`): Calls `POST /api/pause`, then outputs a standby message.
- **Status pill** (`#quiz-status-pill`): Shows `[IDLE]`, `[ACTIVE]`, `[SUBMITTED]`, or `[PAUSED]`.

---

## Knowledge Cosmos: D3 Force-Graph Modal

Opened via `[GRAPH]` button or `openGraphModal()`.

- Fetches `GET /api/graph/global` on open.
- Renders using `force-graph` library (Obsidian-canvas engine) over a `<canvas>`.
- Nodes are colour-coded by status:
  - `mastered` → green
  - `active` → cyan
  - `planned` → slate
  - `diagnostic` → sky blue
- Clicking a node opens the **note drawer** on the right side (`.note-drawer` panel) showing the vault markdown for that node (fetched from `GET /api/notes/{node_id}`).
- The note drawer is resizable via a horizontal drag bar (`.graph-resizer`).
- Floating navigation controls (`.graph-nav-controls`): zoom in, zoom out, fit view buttons. The **Fit View** (`FIT`) button computes the exact bounding-box centroid of all active nodes rather than the canvas origin, ensuring optimal centering and zoom framing without visual drift.
- `Esc` key: closes the note drawer or the graph modal.
- Clicking canvas background clears node focus and removes the dimming highlight.

---

## Header Status Indicators

| Element | Reflects |
|---|---|
| `#header-session-badge` | `[STANDBY]`, `[PROBING]`, `[TEACHING]`, `[PAUSED]`, `[COMPLETE]` |
| `#header-topic` | `state.topic` |
| `#header-phase` | `state.phase` (uppercase) |
| `#header-phase-dot` | Colour-coded dot: green (teaching), amber (probing), rose (paused), slate (idle) |
| `[SYNC]` dot | Animated emerald ping, always visible — indicates live polling is active |

---

## Saved Topics Dropdown & Vault Navigation

- `#btn-saved-topics` opens `#saved-topics-menu` (Tailwind dropdown).
- Fetches `GET /api/topics` and renders `.topic-item` cards per topic.
- **Status Filter Chips**: Filter topics by `[ALL]`, `[IN PROGRESS]`, and `[COMPLETED]` tabs.
- **Concept-Level Vault Search**: Real-time filtering across topic names AND individual child concept nodes/titles.
- **Zero-Token Static Reading Mode**: Selecting a topic in read mode (`POST /api/topics/load` with `mode='read'`) renders complete lesson notes and roadmaps instantly without active LLM orchestration.
- **Delete Topic**: Direct deletion of a topic vault via `POST /api/topics/delete` with confirmation modal.
- Also available as `#idle-topic-picker` in the idle command center.

---

## Keyboard & Navigation Hotkeys

| Key / Action | Behaviour |
|---|---|
| `Esc` | Closes note drawer or exits Knowledge Graph full-screen |
| Click canvas background | Clears active node focus and dimming in the graph |
| Drag `#roadmap-resizer` | Resizes Panel 1 width as a percentage of container |
| Drag `.graph-resizer` | Resizes the note drawer width in the graph modal |
| Click `.mermaid` container | Opens diagram lightbox modal |
| `.doc` (click chip) | Copies `.doc` command to clipboard |
| `.gem` (click chip) | Copies `.gem` command to clipboard |

---

## CSS Design Tokens & Key Variables

All variables live in `static/styles.css` (no CSS custom properties — values hardcoded per Tailwind conventions):

| Token | Value | Usage |
|---|---|---|
| Background (deepest) | `#0f172a` (slate-950) | Body, modals, code blocks |
| Background (card) | `#0f172a60` / `rgba(18,20,29,0.65)` | Command cards, panels |
| Border | `#334155` (slate-700) | Panel dividers, prose tables |
| Accent / Brand | `#6366f1` (indigo-500) | Buttons, active focus rings, roadmap resizer hover |
| Node active | `#38bdf8` (sky-400) | Active node stroke, code text, graph-wikilink |
| Node mastered | `#22c55e` (green-500) | Completed/mastered stroke |
| Text primary | `#f8fafc` (slate-50) | H1, strong |
| Text secondary | `#94a3b8` (slate-400) | Paragraphs, labels |
| Font (UI) | `ui-sans-serif, system-ui, sans-serif` | Body text |
| Font (mono) | `ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas` | All badges, labels, command chips |

**Scrollbar**: Custom 6px webkit scrollbar with rounded thumb (`rgba(71,85,105,0.5)`, hover `rgba(100,116,139,0.8)`).

**Prose dark** (`.prose-dark`): Used in lesson notes — headings h1→h3, paragraphs, tables, blockquotes, inline code, pre blocks all styled for dark theme.

**Callout system** (`.obsidian-callout`): Supports `callout-info` (cyan border, `#38bdf8`) and `callout-success` (green border, `#22c55e`) for Obsidian-style `> [!NOTE]` / `> [!success]` blocks in vault notes.

**Graph wikilinks** (`.graph-wikilink`): Rendered as styled `<span>` elements that trigger note-drawer fetch on click. Colour `#38bdf8`, hover `transform: translateY(-1px)`.
