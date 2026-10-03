// Local State Cache
let cachedState = {
  topic: "",
  phase: "idle",
  dag_mermaid: "",
  current_node: "",
  lesson_markdown: "",
  active_quiz: null,
  latest_answer: null,
  quiz_history: []
};

let mermaidReady = false;
let mermaidRenderCount = 0;
let selectedOptionLocal = null;
let multiAnswersLocal = {};
let currentQuizSignature = '';

function getQuizSignature(quizData) {
  if (!quizData) return '';
  const qs = quizData.questions || (quizData.options ? [quizData] : []);
  if (!Array.isArray(qs) || qs.length === 0) return '';
  return qs.map(q => {
    const qText = q.question || q.prompt || q.title || '';
    const opts = Array.isArray(q.options) ? q.options : (q.options && typeof q.options === 'object' ? Object.values(q.options) : []);
    return `${qText}:::${opts.join('|')}`;
  }).join('###');
}

window.addEventListener('mermaid-ready', () => {
  mermaidReady = true;
  if (cachedState.dag_mermaid) {
    renderMermaidDAG(cachedState.dag_mermaid);
  }
  const lessonContainer = document.getElementById('lesson-content');
  if (lessonContainer) {
    runMermaidOnNotes(lessonContainer);
  }
});

// Helper: HTML Entity Decoding & Syntax Sanitization
function sanitizeMermaidCode(rawCode) {
  if (!rawCode || typeof rawCode !== 'string') return '';

  let code = rawCode.trim();

  // Strip leading and trailing markdown code fences (```mermaid or ```) and trim surrounding whitespace
  code = code.replace(/^```(?:mermaid)?\s*/i, '');
  code = code.replace(/```\s*$/i, '');
  code = code.trim();

  // Decode standard HTML entities: replace &gt; with >, &lt; with <, &amp; with &, and &quot; with "
  code = code
    .replace(/&gt;/g, '>')
    .replace(/&lt;/g, '<')
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/&amp;/g, '&');

  code = code.trim();

  // Ensure graph declaration (e.g., flowchart TD or flowchart LR) is intact
  const lines = code.split('\n').map(line => line.trim()).filter(line => line.length > 0 && !line.startsWith('%%'));
  if (lines.length === 0) return '';

  const validGraphTypeRegex = /^\s*(graph|flowchart|subgraph|sequenceDiagram|classDiagram|stateDiagram(?:-v2)?|erDiagram|journey|gantt|pie|quadrantChart|requirementDiagram|gitGraph|mindmap|timeline|xychart-beta|sankey-beta)\b/im;
  const hasDeclaration = lines.some(line => validGraphTypeRegex.test(line));
  if (!hasDeclaration) {
    code = 'flowchart TD\n' + code;
  }

  return code;
}

// Helper: Intercept code blocks tagged with language "mermaid" or raw text blocks starting with flowchart, graph, subgraph
function interceptMermaidBlocks(html) {
  if (!html) return html;

  // Convert <pre><code class="language-mermaid">...</code></pre> to <div class="mermaid">...</div>
  html = html.replace(/<pre><code class="(?:language-|lang-)?mermaid">([\s\S]*?)<\/code><\/pre>/gi, (match, code) => {
    const clean = sanitizeMermaidCode(code);
    if (!clean) return match;
    const encoded = clean
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
    return `<div class="mermaid" data-code="${encoded}">${encoded}</div>`;
  });

  // Also intercept raw code blocks starting with flowchart, graph, or subgraph
  html = html.replace(/<pre><code>((?:flowchart|graph|subgraph)\b[\s\S]*?)<\/code><\/pre>/gi, (match, code) => {
    const clean = sanitizeMermaidCode(code);
    if (!clean) return match;
    const encoded = clean
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
    return `<div class="mermaid" data-code="${encoded}">${encoded}</div>`;
  });

  return html;
}

// Diagram Lightbox Modal Functions
function openDiagramModal(svgElement) {
  const modal = document.getElementById('diagram-modal');
  const modalBody = document.getElementById('diagram-modal-body');
  if (!modal || !modalBody || !svgElement) return;

  modalBody.innerHTML = '';
  const clonedSvg = svgElement.cloneNode(true);

  // Unconstrained resolution for comfortable inspection
  clonedSvg.removeAttribute('width');
  clonedSvg.removeAttribute('height');
  clonedSvg.style.maxWidth = 'none';
  clonedSvg.style.width = 'auto';
  clonedSvg.style.height = 'auto';

  modalBody.appendChild(clonedSvg);
  modal.classList.remove('hidden');
  document.body.style.overflow = 'hidden';
}

function closeDiagramModal() {
  const modal = document.getElementById('diagram-modal');
  const modalBody = document.getElementById('diagram-modal-body');
  if (!modal) return;
  modal.classList.add('hidden');
  if (modalBody) {
    modalBody.innerHTML = '';
  }
  document.body.style.overflow = '';
}

function setupDiagramModal() {
  const modal = document.getElementById('diagram-modal');
  const closeBtn = document.getElementById('btn-close-diagram-modal');

  if (closeBtn && !closeBtn.dataset.listenerBound) {
    closeBtn.dataset.listenerBound = 'true';
    closeBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      closeDiagramModal();
    });
  }

  if (modal && !modal.dataset.listenerBound) {
    modal.dataset.listenerBound = 'true';
    modal.addEventListener('click', (e) => {
      const isInsideSvg = e.target.closest('#diagram-modal-body svg');
      const isHeader = e.target.closest('#diagram-modal-header');
      if (!isInsideSvg && !isHeader) {
        closeDiagramModal();
      }
    });
  }
}

window.openDiagramModal = openDiagramModal;
window.closeDiagramModal = closeDiagramModal;

// Initialize modal triggers on document load
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', setupDiagramModal);
} else {
  setupDiagramModal();
}

// Helper: Attach lightbox click listeners and hover tag to rendered .mermaid containers
function attachDiagramLightboxHandlers(container) {
  if (!container) return;
  const mermaidContainers = container.querySelectorAll('.mermaid');
  mermaidContainers.forEach(el => {
    el.classList.add('group');

    // Subtle hover indicator overlay corner tag: [ CLICK TO EXPAND ]
    if (!el.querySelector('.diagram-expand-tag')) {
      const tag = document.createElement('span');
      tag.className = 'diagram-expand-tag font-mono text-[10px] text-slate-400 bg-slate-900/80 px-2 py-0.5 rounded border border-slate-700 absolute top-2 right-2 opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none select-none';
      tag.textContent = '[ CLICK TO EXPAND ]';
      el.appendChild(tag);
    }

    if (!el.dataset.lightboxBound) {
      el.dataset.lightboxBound = 'true';
      el.addEventListener('click', (e) => {
        if (e.target.closest('a')) return;
        const svg = el.querySelector('svg');
        if (svg) {
          openDiagramModal(svg);
        }
      });
    }
  });
}

// Helper: Clean up auto-injected Mermaid error elements and orphaned temporary render divs from DOM
function cleanupMermaidErrorDOM(container) {
  const errorSelectors = [
    'svg[id^="dmermaid"]',
    'div[id^="dmermaid"]',
    '#mermaid-error',
    '[id^="dmermaid-"]',
    'svg[aria-roledescription="error"]',
    '.error-icon',
    '.error-text'
  ];
  errorSelectors.forEach(sel => {
    try {
      document.querySelectorAll(sel).forEach(el => el.remove());
    } catch (e) {
      // ignore
    }
  });

  // Clear any orphaned temporary render divs left behind by Mermaid in document.body
  try {
    const directBodyChildren = Array.from(document.body.children);
    for (const child of directBodyChildren) {
      if (child.id && (child.id.startsWith('mermaid-') || child.id.startsWith('dmermaid-'))) {
        child.remove();
      }
    }
  } catch (e) {
    // ignore
  }

  if (container) {
    try {
      const insideErrors = container.querySelectorAll('svg[id^="dmermaid"], div[id^="dmermaid"], #mermaid-error, [id^="dmermaid-"], .error-icon, .error-text');
      insideErrors.forEach(el => el.remove());
    } catch (e) {
      // ignore
    }
  }
}

// Helper: Render Mermaid diagrams inside arbitrary HTML container
async function runMermaidOnNotes(container) {
  if (!container) return;
  if (!window.mermaid || !mermaidReady) return;

  const mermaidContainers = Array.from(container.querySelectorAll('.mermaid'));
  for (const el of mermaidContainers) {
    if (el.dataset.rendered === 'true') continue;
    const rawCode = el.dataset.code || el.textContent || el.innerText;
    const cleanCode = sanitizeMermaidCode(rawCode);
    if (!cleanCode) continue;

    const id = "mermaid-note-" + Math.random().toString(36).substring(2, 9);
    try {
      const { svg } = await window.mermaid.render(id, cleanCode);
      el.innerHTML = svg;
      el.dataset.rendered = 'true';
    } catch (err) {
      console.warn("Mermaid fallback:", err);
      cleanupMermaidErrorDOM(container);
      const orphan = document.getElementById(id) || document.getElementById('d' + id);
      if (orphan) orphan.remove();
    }
  }

  attachDiagramLightboxHandlers(container);
}

// Helper: KaTeX Math rendering
function renderMath(element) {
  if (window.renderMathInElement) {
    renderMathInElement(element, {
      delimiters: [
        { left: '$$', right: '$$', display: true },
        { left: '$', right: '$', display: false },
        { left: '\\(', right: '\\)', display: false },
        { left: '\\[', right: '\\]', display: true }
      ],
      throwOnError: false
    });
  }
}

// Helper: Update Header Info
function updateHeader(state) {
  const topicEl = document.getElementById('header-topic');
  const phaseEl = document.getElementById('header-phase');
  const phaseDotEl = document.getElementById('header-phase-dot');

  topicEl.textContent = state.topic || 'Not Set';
  phaseEl.textContent = state.phase || 'idle';

  // Update Phase styling
  const phase = (state.phase || 'idle').toLowerCase();
  phaseDotEl.className = 'w-2 h-2 rounded-full ';
  if (phase === 'probing') {
    phaseDotEl.className += 'bg-amber-400 shadow-sm shadow-amber-400';
    phaseEl.className = 'uppercase font-bold tracking-wider text-amber-400';
  } else if (phase === 'teaching') {
    phaseDotEl.className += 'bg-indigo-400 shadow-sm shadow-indigo-400';
    phaseEl.className = 'uppercase font-bold tracking-wider text-indigo-400';
  } else if (phase === 'evaluating') {
    phaseDotEl.className += 'bg-violet-400 shadow-sm shadow-violet-400';
    phaseEl.className = 'uppercase font-bold tracking-wider text-violet-400';
  } else if (phase === 'paused') {
    phaseDotEl.className += 'bg-amber-400 shadow-sm shadow-amber-400';
    phaseEl.className = 'uppercase font-bold tracking-wider text-amber-400';
  } else {
    phaseDotEl.className += 'bg-slate-500';
    phaseEl.className = 'uppercase font-bold tracking-wider text-slate-400';
  }
}

// Helper: Render Mermaid DAG / Roadmap
async function renderRoadmap(code) {
  const container = document.getElementById('dag-container');
  if (!container) return;

  // 1. Pre-Render Validation Guard:
  if (!code || typeof code !== 'string' || !code.trim()) {
    container.innerHTML = '';
    return;
  }

  const cleanCode = sanitizeMermaidCode(code);
  if (!cleanCode) {
    container.innerHTML = '';
    return;
  }

  // Check if it contains a valid graph directive matching /^\s*(graph|flowchart)\s+(TD|TB|LR|RL)/im
  const validDirective = /^\s*(graph|flowchart)\s+(TD|TB|LR|RL)/im.test(cleanCode);
  if (!validDirective) {
    container.innerHTML = '';
    return;
  }

  if (!window.mermaid || !mermaidReady) {
    return; // Will retry when mermaid is ready
  }

  const id = "mermaid-dag-" + Date.now();
  try {
    const { svg } = await window.mermaid.render(id, cleanCode);
    container.innerHTML = svg;
  } catch (err) {
    console.warn("Mermaid fallback:", err);
    cleanupMermaidErrorDOM(container);
    const orphan = document.getElementById(id) || document.getElementById('d' + id);
    if (orphan) orphan.remove();
    container.innerHTML = '';
  }
}

// Backward-compatible alias
const renderMermaidDAG = renderRoadmap;
window.renderRoadmap = renderRoadmap;
window.renderMermaidDAG = renderRoadmap;

// Backward compatibility shim for notes-scroll-area -> notes-panel
const _rawGetElementById = document.getElementById.bind(document);
document.getElementById = function(id) {
  if (id === 'notes-scroll-area') {
    return _rawGetElementById('notes-panel') || _rawGetElementById('notes-scroll-area');
  }
  return _rawGetElementById(id);
};

// Helper: Split raw lesson notes markdown into historical and active module sections
function splitLessonNotes(markdown, activeNodeId, activeNodeLabel) {
  if (!markdown || !markdown.trim()) {
    return { previousMarkdown: '', activeMarkdown: '', activeNodeNum: null };
  }

  // Discrete node sections based on heading delimiters: (?=^#+\s*Node\s*\d+) or (?=^Node\s*\d+:)
  const delimiterRegex = /(?=^#+\s*Node\s*\d+|^Node\s*\d+:)/im;
  const rawParts = markdown.split(delimiterRegex);

  if (rawParts.length <= 1 && !/(?:^#+\s*Node\s*\d+|^Node\s*\d+:)/im.test(rawParts[0])) {
    return { previousMarkdown: '', activeMarkdown: markdown, activeNodeNum: null };
  }

  let preamble = '';
  const sections = [];

  for (const part of rawParts) {
    if (!part || !part.trim()) continue;
    const headerMatch = part.match(/^(?:#+\s*)?Node\s*(\d+)[:.]?\s*([^\n\r]*)/im);
    if (!headerMatch) {
      preamble += (preamble ? '\n\n' : '') + part.trim();
    } else {
      const nodeNum = parseInt(headerMatch[1], 10);
      const title = (headerMatch[2] || '').trim();
      const slug = title.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
      sections.push({
        nodeNum,
        title,
        slug,
        raw: part.trim()
      });
    }
  }

  if (sections.length === 0) {
    return { previousMarkdown: '', activeMarkdown: markdown, activeNodeNum: null };
  }

  let targetNum = null;
  if (activeNodeLabel) {
    const m = String(activeNodeLabel).match(/^(\d+)[\.\)]/);
    if (m) targetNum = parseInt(m[1], 10);
  }
  if (targetNum === null && activeNodeId) {
    const m = String(activeNodeId).match(/(?:node[-_]?)?(\d+)/i);
    if (m) targetNum = parseInt(m[1], 10);
  }

  let activeIdx = -1;
  if (targetNum !== null) {
    activeIdx = sections.findIndex(s => s.nodeNum === targetNum);
  }
  if (activeIdx === -1 && activeNodeId) {
    const cleanId = String(activeNodeId).toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
    activeIdx = sections.findIndex(s => s.slug === cleanId || cleanId.includes(s.slug) || s.slug.includes(cleanId));
  }

  // Fallback: section matching active_node_id or latest section if undefined
  if (activeIdx === -1) {
    activeIdx = sections.length - 1;
  }

  const activeSection = sections[activeIdx];
  const activeNodeNum = activeSection ? activeSection.nodeNum : targetNum;

  // Previous Lessons: all sections matching node IDs < active_node_id
  const previousSections = (activeNodeNum !== null)
    ? sections.filter(s => s.nodeNum < activeNodeNum)
    : sections.slice(0, activeIdx);

  const previousMarkdown = previousSections.map(s => s.raw).join('\n\n---\n\n');
  const activeMarkdown = activeSection ? activeSection.raw : markdown;

  return {
    previousMarkdown,
    activeMarkdown,
    activeNodeNum
  };
}

// Helper: Render Lesson Markdown + Viewport Separation + KaTeX
function renderLesson(markdown, activeNodeId = null, activeNodeLabel = null) {
  const container = document.getElementById('lesson-content');
  if (!container) return;

  if (!markdown || !markdown.trim()) {
    container.innerHTML = `
      <div class="py-16 text-center text-slate-500">
        <svg class="w-10 h-10 mx-auto mb-3 opacity-30 text-emerald-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s3.332.477 4.5 1.253m0-13C13.168 5.477 14.754 5 16.5 5c1.747 0 3.332.477 4.5 1.253v13C19.832 18.477 18.247 18 16.5 18c-1.746 0-3.332.477-4.5 1.253"></path>
        </svg>
        <p class="text-xs">No lesson notes available yet.</p>
        <p class="text-[11px] text-slate-600 mt-1">Teaching stream will populate and render math in real-time.</p>
      </div>
    `;
    return;
  }

  const effectiveActiveId = activeNodeId || (cachedState && (cachedState.active_node_id || cachedState.active_node)) || null;
  const effectiveActiveLabel = activeNodeLabel || (cachedState && cachedState.active_node) || null;

  const { previousMarkdown, activeMarkdown, activeNodeNum } = splitLessonNotes(markdown, effectiveActiveId, effectiveActiveLabel);
  const prevRangeText = (activeNodeNum && activeNodeNum > 1) ? `Nodes 1 to ${activeNodeNum - 1}` : 'Nodes 1 to N-1';

  let renderedHtml = '';
  if (previousMarkdown && previousMarkdown.trim()) {
    let renderedPrev = window.marked ? window.marked.parse(previousMarkdown) : previousMarkdown;
    renderedPrev = interceptMermaidBlocks(renderedPrev);
    renderedHtml += `
      <details id="previous-notes-drawer" style="margin-bottom: 1rem; border-bottom: 1px solid #334155; padding-bottom: 0.5rem;">
        <summary style="cursor: pointer; color: #94a3b8; font-size: 0.85rem; font-weight: 600;">[+] Completed Module Notes (${prevRangeText})</summary>
        <div id="previous-notes-content" style="padding-top: 0.75rem; color: #94a3b8;">${renderedPrev}</div>
      </details>
    `;
  } else {
    renderedHtml += `
      <details id="previous-notes-drawer" style="display: none; margin-bottom: 1rem; border-bottom: 1px solid #334155; padding-bottom: 0.5rem;">
        <summary style="cursor: pointer; color: #94a3b8; font-size: 0.85rem; font-weight: 600;">[+] Completed Module Notes (${prevRangeText})</summary>
        <div id="previous-notes-content" style="padding-top: 0.75rem; color: #94a3b8;"></div>
      </details>
    `;
  }

  let renderedActive = window.marked ? window.marked.parse(activeMarkdown) : activeMarkdown;
  renderedActive = interceptMermaidBlocks(renderedActive);
  renderedHtml += `
    <div id="active-lesson-container">${renderedActive}</div>
  `;

  container.innerHTML = renderedHtml;

  // Collapsible toggle text updater
  const drawer = document.getElementById('previous-notes-drawer');
  if (drawer) {
    const summary = drawer.querySelector('summary');
    if (summary) {
      drawer.addEventListener('toggle', () => {
        summary.textContent = drawer.open
          ? `[-] Completed Module Notes (${prevRangeText})`
          : `[+] Completed Module Notes (${prevRangeText})`;
      });
    }
  }

  // Convert Markdown + KaTeX math
  renderMath(container);

  // Render in-note Mermaid diagrams as SVGs
  runMermaidOnNotes(container);

  // Reset scroll position so active lesson heading is immediately visible at the top
  const panelNotes = document.getElementById('panel-notes');
  if (panelNotes) {
    panelNotes.scrollTop = 0;
  }
}

// Helper: Render Active Quiz
function renderQuiz(quizData, latestAnswer) {
  const container = document.getElementById('quiz-container');
  const pill = document.getElementById('quiz-status-pill');

  if (!quizData) {
    if (pill) {
      pill.textContent = 'Idle';
      pill.className = 'text-[10px] font-mono px-2 py-0.5 rounded-full bg-slate-800 text-slate-400 border border-slate-700/60';
    }
    if (container) {
      container.innerHTML = `
        <div class="py-16 text-center text-slate-500">
          <svg class="w-10 h-10 mx-auto mb-3 opacity-30 text-violet-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"></path>
          </svg>
          <div class="quiz-empty text-xs text-slate-500">Awaiting checkpoint assessment...</div>
        </div>
      `;
    }
    selectedOptionLocal = null;
    multiAnswersLocal = {};
    currentQuizSignature = '';
    return;
  }

  const newQuizSig = getQuizSignature(quizData);
  if (newQuizSig !== currentQuizSignature) {
    currentQuizSignature = newQuizSig;
    selectedOptionLocal = null;
    multiAnswersLocal = {};
  }

  if (cachedState && String(cachedState.phase).toUpperCase() === 'PAUSED') {
    const topicName = (cachedState.topic && cachedState.topic !== "Not Set") ? cachedState.topic : "topic";
    if (pill) {
      pill.textContent = '[PAUSED]';
      pill.className = 'text-[10px] font-mono px-2 py-0.5 rounded bg-amber-950/40 text-amber-400 border border-amber-500/30';
    }
    if (container) {
      container.innerHTML = `
        <div class="p-6 rounded-xl bg-slate-900/90 border border-slate-800 text-center space-y-3 font-mono">
          <div class="inline-block px-2.5 py-1 rounded bg-slate-800 text-amber-400 text-xs font-bold border border-amber-500/30">
            [SESSION: PAUSED]
          </div>
          <p class="text-xs text-slate-300 leading-relaxed font-sans">
            Session paused. Run <span class="font-mono text-indigo-300 font-semibold">.resume ${escapeHtml(topicName)}</span> in your chat to continue.
          </p>
          <div class="text-[11px] text-slate-500 font-mono">
            [STANDBY] Progress preserved. Web server remains active.
          </div>
        </div>
      `;
    }
    return;
  }

  // Concurrent Batch Assessment Rendering for all questions (1 to 3+)
  const questions = Array.isArray(quizData)
    ? quizData
    : (quizData.questions || (quizData.options ? [quizData] : []));

  if (!questions || questions.length === 0) {
    if (pill) {
      pill.textContent = 'Idle';
      pill.className = 'text-[10px] font-mono px-2 py-0.5 rounded-full bg-slate-800 text-slate-400 border border-slate-700/60';
    }
    if (container) {
      container.innerHTML = `<div class="quiz-empty py-16 text-center text-slate-500 font-mono text-xs">Awaiting checkpoint assessment...</div>`;
    }
    return;
  }

  if (pill) {
    pill.textContent = 'Active Checkpoint';
    pill.className = 'text-[10px] font-mono px-2 py-0.5 rounded-full bg-violet-950/60 text-violet-300 border border-violet-500/30 animate-pulse';
  }

  const isGraded = Boolean(
    latestAnswer &&
    (latestAnswer.results || latestAnswer.rationales || latestAnswer.batch !== undefined || latestAnswer.passed !== undefined || latestAnswer.correct !== undefined || latestAnswer.score !== undefined)
  );

  // If graded, synchronize multiAnswersLocal from latestAnswer
  if (isGraded) {
    if (latestAnswer.answers && Array.isArray(latestAnswer.answers)) {
      latestAnswer.answers.forEach((ans, idx) => {
        multiAnswersLocal[idx] = ans;
      });
    } else if (latestAnswer.selected_idx !== undefined) {
      multiAnswersLocal[0] = latestAnswer.selected_idx;
    }
  }

  const answeredCount = Object.keys(multiAnswersLocal).filter(k => multiAnswersLocal[k] !== undefined && multiAnswersLocal[k] !== null).length;
  const allAnswered = answeredCount === questions.length;

  let html = `<div class="space-y-6">`;
  html += `
    <div class="flex items-center justify-between text-xs font-mono text-slate-400 pb-2 border-b border-slate-800">
      <span class="font-semibold text-indigo-300">[BATCH ASSESSMENT: ${questions.length} QUESTION${questions.length > 1 ? 'S' : ''}]</span>
      <span class="text-[11px] ${allAnswered ? 'text-emerald-400 font-semibold' : 'text-slate-500'}">${answeredCount}/${questions.length} Selected</span>
    </div>
  `;

  questions.forEach((q, qIdx) => {
    const qCorrectIdx = q.correct_index !== undefined ? q.correct_index : q.correct_idx;
    const chosenIdx = multiAnswersLocal[qIdx];
    const hasChosen = chosenIdx !== undefined && chosenIdx !== null;
    const questionText = q.question || q.prompt || q.title || "";

    let options = [];
    if (Array.isArray(q.options)) {
      options = q.options;
    } else if (q.options && typeof q.options === 'object') {
      options = Object.entries(q.options).map(([k, v]) => {
        const valStr = String(v);
        return (valStr.startsWith(`${k})`) || valStr.startsWith(`${k}.`)) ? valStr : `${k}) ${valStr}`;
      });
    }

    html += `
      <div class="bg-slate-900/90 border border-slate-800 rounded-xl p-4 shadow-lg space-y-4">
        <div class="flex items-start gap-2.5">
          <span class="w-6 h-6 rounded-md bg-indigo-500/20 text-indigo-400 flex items-center justify-center font-bold text-xs shrink-0 mt-0.5">Q${qIdx + 1}</span>
          <div class="text-sm font-semibold text-slate-100 leading-snug">
            ${escapeHtml(questionText)}
          </div>
        </div>

        <div class="space-y-2 pt-1">
    `;

    options.forEach((opt, optIdx) => {
      let btnStyle = "w-full text-left p-3 rounded-lg border text-xs font-medium transition-all flex items-start gap-3 ";
      const letter = String.fromCharCode(65 + optIdx);

      if (!isGraded) {
        if (optIdx === chosenIdx) {
          btnStyle += "bg-indigo-950/70 border-indigo-500 text-indigo-100 ring-1 ring-indigo-500/50 shadow-md shadow-indigo-950/50 cursor-pointer";
        } else {
          btnStyle += "bg-slate-800/60 border-slate-700/60 text-slate-300 hover:bg-slate-800 hover:border-indigo-500/60 hover:text-white cursor-pointer";
        }
        html += `
          <button type="button" onclick="selectMultiOption(${qIdx}, ${optIdx})" class="${btnStyle}">
            <span class="w-5 h-5 rounded-full border ${optIdx === chosenIdx ? 'border-indigo-400 bg-indigo-500/30 text-indigo-300' : 'border-current'} flex items-center justify-center text-[10px] font-bold shrink-0 mt-0.5">${letter}</span>
            <span class="quiz-option-text flex-1">${escapeHtml(opt)}</span>
            ${optIdx === chosenIdx ? `<span class="w-2 h-2 rounded-full bg-indigo-400 shrink-0 self-center"></span>` : ''}
          </button>
        `;
      } else {
        // Graded mode
        if (optIdx === chosenIdx) {
          if (optIdx === qCorrectIdx) {
            btnStyle += "bg-emerald-950/60 border-emerald-500 text-emerald-200 shadow-md shadow-emerald-950/50 cursor-default";
          } else {
            btnStyle += "bg-rose-950/60 border-rose-500 text-rose-200 shadow-md shadow-rose-950/50 cursor-default";
          }
        } else if (optIdx === qCorrectIdx) {
          btnStyle += "bg-emerald-950/30 border-emerald-500/50 text-emerald-300/80 cursor-default";
        } else {
          btnStyle += "bg-slate-900/40 border-slate-800 text-slate-500 cursor-not-allowed opacity-50";
        }

        html += `
          <button type="button" disabled class="${btnStyle}">
            <span class="w-5 h-5 rounded-full border border-current flex items-center justify-center text-[10px] font-bold shrink-0 mt-0.5">${letter}</span>
            <span class="quiz-option-text flex-1">${escapeHtml(opt)}</span>
            ${optIdx === chosenIdx ? (optIdx === qCorrectIdx ? 
              `<svg class="w-4 h-4 text-emerald-400 shrink-0 ml-auto" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"></path></svg>` : 
              `<svg class="w-4 h-4 text-rose-400 shrink-0 ml-auto" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path></svg>`) : ''}
          </button>
        `;
      }
    });

    html += `</div>`;

    if (isGraded && q.explanation) {
      const isCorrect = (chosenIdx === qCorrectIdx);
      html += `
        <div class="mt-4 pt-3 border-t border-slate-800/80">
          <div class="p-3.5 rounded-lg ${isCorrect ? 'bg-emerald-950/30 border border-emerald-500/30' : 'bg-rose-950/30 border border-rose-500/30'}">
            <div class="flex items-center gap-2 mb-1.5 font-mono">
              <span class="text-xs font-bold ${isCorrect ? 'text-emerald-400' : 'text-rose-400'}">
                ${isCorrect ? '[CORRECT ASSESSMENT]' : '[INCORRECT ASSESSMENT]'}
              </span>
            </div>
            <div class="text-xs text-slate-300 leading-relaxed">
              ${escapeHtml(q.explanation)}
            </div>
          </div>
        </div>
      `;
    }

    html += `</div>`;
  });

  // Bottom Action / Status Area
  if (!isGraded) {
    html += `
      <div class="pt-2 flex items-center gap-2">
        <button id="btn-submit-assessment" type="button" ${allAnswered ? '' : 'disabled'} onclick="submitBatchAssessment()" class="flex-1 py-3.5 px-4 rounded-xl font-mono text-xs font-bold transition-all flex items-center justify-center gap-2 ${allAnswered ? 'bg-indigo-600 hover:bg-indigo-500 text-white shadow-lg shadow-indigo-950/50 cursor-pointer' : 'bg-slate-800/80 border border-slate-700/60 text-slate-500 cursor-not-allowed opacity-60'}">
          <span>${allAnswered ? '[ SUBMIT ASSESSMENT ]' : `[ SELECT ALL ANSWERS TO SUBMIT (${answeredCount}/${questions.length}) ]`}</span>
        </button>
        <button type="button" onclick="pauseSession()" class="btn-secondary py-3.5 px-3 rounded-xl font-mono text-xs font-semibold text-slate-400 hover:text-white bg-slate-900 border border-slate-700/80 hover:border-slate-500 transition-all cursor-pointer shrink-0" title="Pause session">[PAUSE]</button>
      </div>
    `;
  } else {
    const isPassed = Boolean(latestAnswer.passed || latestAnswer.correct || (latestAnswer.score !== undefined && latestAnswer.score >= 0.70));
    const correctCount = latestAnswer.correct_count !== undefined ? latestAnswer.correct_count : (isPassed ? questions.length : 0);
    html += `
      <div class="pt-2 space-y-3 font-mono">
        <div class="p-4 rounded-xl border text-center space-y-1 ${isPassed ? 'bg-emerald-950/40 border-emerald-500 text-emerald-200' : 'bg-rose-950/40 border-rose-500 text-rose-200'}">
          <div class="text-sm font-bold">${isPassed ? '[ASSESSMENT PASSED]' : '[ASSESSMENT FAILED]'}</div>
          <div class="text-xs">${correctCount} / ${questions.length} correct</div>
        </div>
        ${!isPassed ? `
          <button type="button" onclick="retryAssessment()" class="w-full py-2.5 px-4 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-bold border border-slate-700 transition-all cursor-pointer">
            [ RETRY ASSESSMENT ]
          </button>
        ` : `
          <div class="text-center text-xs text-emerald-400 font-semibold py-1">
            [MASTERY VERIFIED - ADVANCING TO NEXT NODE]
          </div>
        `}
      </div>
    `;
  }

  html += `</div>`;
  container.innerHTML = html;
  renderMath(container);
}

// Option Selection & Batch Submission Handlers
function selectMultiOption(qIdx, optIdx) {
  if (!cachedState.active_quiz) return;
  multiAnswersLocal[qIdx] = optIdx;
  renderQuiz(cachedState.active_quiz, null);
}

async function submitBatchAssessment() {
  if (!cachedState.active_quiz) return;
  const quiz = cachedState.active_quiz;
  const questions = Array.isArray(quiz)
    ? quiz
    : (quiz.questions && Array.isArray(quiz.questions) ? quiz.questions : (quiz.options ? [quiz] : []));

  const answeredCount = Object.keys(multiAnswersLocal).filter(k => multiAnswersLocal[k] !== undefined && multiAnswersLocal[k] !== null).length;
  if (answeredCount < questions.length) return;

  const answers = questions.map((_, idx) => multiAnswersLocal[idx]);
  let nodeId = quiz.node_id;
  if (!nodeId && cachedState) {
    nodeId = cachedState.active_node_id || cachedState.active_node || cachedState.current_node;
  }
  if (!nodeId && cachedState && cachedState.topic && cachedState.topic !== "Not Set") {
    nodeId = cachedState.topic.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '');
  }

  const payload = {
    node_id: nodeId || null,
    answers: answers,
    timestamp: new Date().toISOString()
  };

  try {
    const resp = await fetch('/api/submit-quiz', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    if (resp.ok) {
      const data = await resp.json();
      cachedState.latest_answer = data.latest_answer || data.evaluation;
      renderQuiz(cachedState.active_quiz, cachedState.latest_answer);
    }
  } catch (err) {
    console.error('Failed to submit batch assessment:', err);
  }
}

function selectSingleOption(idx) {
  selectMultiOption(0, idx);
}

async function submitSingleAssessment() {
  await submitBatchAssessment();
}

function retryAssessment() {
  multiAnswersLocal = {};
  selectedOptionLocal = null;
  if (cachedState) {
    cachedState.latest_answer = null;
    renderQuiz(cachedState.active_quiz, null);
  }
}

function pauseSession() {
  if (!confirm('Are you sure you want to pause the session?')) return;
  fetch('/api/pause', { method: 'POST' })
    .then(res => res.json())
    .then(data => {
      const topicName = (cachedState && cachedState.topic && cachedState.topic !== "Not Set") ? cachedState.topic : "topic";

      // Display in-panel message:
      const quizContainer = document.getElementById('quiz-container');
      if (quizContainer) {
        quizContainer.innerHTML = `
          <div class="p-6 rounded-xl bg-slate-900/90 border border-slate-800 text-center space-y-3 font-mono">
            <div class="inline-block px-2.5 py-1 rounded bg-slate-800 text-amber-400 text-xs font-bold border border-amber-500/30">
              [SESSION: PAUSED]
            </div>
            <p class="text-xs text-slate-300 leading-relaxed font-sans">
              Session paused. Run <span class="font-mono text-indigo-300 font-semibold">.resume ${escapeHtml(topicName)}</span> in your chat to continue.
            </p>
            <div class="text-[11px] text-slate-500 font-mono">
              [STANDBY] Progress preserved. Web server remains active.
            </div>
          </div>
        `;
      }

      // Disable quiz inputs
      const quizInputs = document.querySelectorAll('#panel-quiz button:not(#btn-pause-session):not([onclick*="collapseQuizPanel"]), #panel-quiz input');
      quizInputs.forEach(el => {
        el.disabled = true;
      });

      const pill = document.getElementById('quiz-status-pill');
      if (pill) {
        pill.textContent = '[PAUSED]';
        pill.className = 'text-[10px] font-mono px-2 py-0.5 rounded bg-amber-950/40 text-amber-400 border border-amber-500/30';
      }

      if (cachedState) {
        cachedState.phase = "PAUSED";
        updateHeader(cachedState);
      }

      if (typeof showToast === 'function') {
        showToast("Session paused. Run '.resume <topic>' to continue.");
      }
    })
    .catch(err => {
      console.error('Failed to pause session:', err);
      if (typeof showToast === 'function') {
        showToast("Error pausing session", "error");
      }
    });
}

// Reset Session
async function resetSession() {
  if (!confirm('Are you sure you want to reset the session state?')) return;
  try {
    const resp = await fetch('/api/reset', { method: 'POST' });
    if (resp.ok) {
      const data = await resp.json();
      selectedOptionLocal = null;
      cachedState = data.state;
      updateUI(cachedState, true);
    }
  } catch (err) {
    console.error('Failed to reset session:', err);
  }
}

function escapeHtml(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
}

let cachedActiveNote = null;
let isReferenceMode = false;
let currentReferenceNode = null;

// Roadmap Column Resizer
function setupRoadmapResizer() {
  const resizer = document.getElementById('roadmap-resizer');
  const roadmapPanel = document.getElementById('panel-roadmap');
  if (!resizer || !roadmapPanel) return;

  const savedWidth = localStorage.getItem('roadmap_panel_width');
  if (savedWidth) {
    roadmapPanel.style.width = savedWidth;
  }

  let isDragging = false;
  let startX = 0;
  let startWidth = 0;

  resizer.addEventListener('mousedown', (e) => {
    isDragging = true;
    startX = e.clientX;
    startWidth = roadmapPanel.getBoundingClientRect().width;
    resizer.classList.add('is-dragging');
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';
  });

  window.addEventListener('mousemove', (e) => {
    if (!isDragging) return;
    const deltaX = e.clientX - startX;
    const newWidth = Math.max(180, Math.min(window.innerWidth * 0.6, startWidth + deltaX));
    roadmapPanel.style.width = `${newWidth}px`;
  });

  window.addEventListener('mouseup', () => {
    if (isDragging) {
      isDragging = false;
      resizer.classList.remove('is-dragging');
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
      localStorage.setItem('roadmap_panel_width', `${roadmapPanel.getBoundingClientRect().width}px`);
    }
  });
}

// Collapsible Side Panels Navigation & Handlers
function collapseRoadmapPanel() {
  const panel = document.getElementById('panel-roadmap');
  const rail = document.getElementById('roadmap-collapsed-rail');
  const resizer = document.getElementById('roadmap-resizer');
  if (!panel) return;

  panel.classList.add('panel-rail-collapsed');
  if (rail) rail.classList.remove('hidden');
  if (resizer) resizer.classList.add('hidden');
}

function expandRoadmapPanel() {
  const panel = document.getElementById('panel-roadmap');
  const rail = document.getElementById('roadmap-collapsed-rail');
  const resizer = document.getElementById('roadmap-resizer');
  if (!panel) return;

  panel.classList.remove('panel-rail-collapsed');
  if (rail) rail.classList.add('hidden');
  if (resizer) resizer.classList.remove('hidden');
}

function toggleRoadmapPanel() {
  const panel = document.getElementById('panel-roadmap');
  if (!panel) return;
  if (panel.classList.contains('panel-rail-collapsed')) {
    expandRoadmapPanel();
  } else {
    collapseRoadmapPanel();
  }
}

function collapseQuizPanel() {
  const panel = document.getElementById('panel-quiz');
  const rail = document.getElementById('quiz-collapsed-rail');
  if (!panel) return;

  panel.classList.add('panel-rail-collapsed');
  if (rail) rail.classList.remove('hidden');
}

function expandQuizPanel() {
  const panel = document.getElementById('panel-quiz');
  const rail = document.getElementById('quiz-collapsed-rail');
  if (!panel) return;

  panel.classList.remove('panel-rail-collapsed');
  if (rail) rail.classList.add('hidden');
}

function toggleQuizPanel() {
  const panel = document.getElementById('panel-quiz');
  if (!panel) return;
  if (panel.classList.contains('panel-rail-collapsed')) {
    expandQuizPanel();
  } else {
    collapseQuizPanel();
  }
}

function setupCollapsiblePanels() {
  const panelRoadmap = document.getElementById('panel-roadmap');
  const railRoadmap = document.getElementById('roadmap-collapsed-rail');
  const btnToggleRoadmap = document.getElementById('btn-toggle-roadmap');
  const btnExpandRoadmap = document.getElementById('btn-expand-roadmap');

  const panelQuiz = document.getElementById('panel-quiz');
  const railQuiz = document.getElementById('quiz-collapsed-rail');
  const btnToggleQuiz = document.getElementById('btn-toggle-quiz');
  const btnExpandQuiz = document.getElementById('btn-expand-quiz');

  // Collapse Roadmap: Header button [ < ]
  if (btnToggleRoadmap && !btnToggleRoadmap.dataset.initialized) {
    btnToggleRoadmap.dataset.initialized = 'true';
    btnToggleRoadmap.addEventListener('click', (e) => {
      e.stopPropagation();
      collapseRoadmapPanel();
    });
  }

  // Expand Roadmap: Rail button [ > ]
  if (btnExpandRoadmap && !btnExpandRoadmap.dataset.initialized) {
    btnExpandRoadmap.dataset.initialized = 'true';
    btnExpandRoadmap.addEventListener('click', (e) => {
      e.stopPropagation();
      expandRoadmapPanel();
    });
  }

  // Click anywhere on #panel-roadmap or #roadmap-collapsed-rail when collapsed
  if (panelRoadmap && !panelRoadmap.dataset.railClickListener) {
    panelRoadmap.dataset.railClickListener = 'true';
    panelRoadmap.addEventListener('click', () => {
      if (panelRoadmap.classList.contains('panel-rail-collapsed')) {
        expandRoadmapPanel();
      }
    });
  }
  if (railRoadmap && !railRoadmap.dataset.railClickListener) {
    railRoadmap.dataset.railClickListener = 'true';
    railRoadmap.addEventListener('click', () => {
      expandRoadmapPanel();
    });
  }

  // Collapse Quiz: Header button [ > ]
  if (btnToggleQuiz && !btnToggleQuiz.dataset.initialized) {
    btnToggleQuiz.dataset.initialized = 'true';
    btnToggleQuiz.addEventListener('click', (e) => {
      e.stopPropagation();
      collapseQuizPanel();
    });
  }

  // Expand Quiz: Rail button [ < ]
  if (btnExpandQuiz && !btnExpandQuiz.dataset.initialized) {
    btnExpandQuiz.dataset.initialized = 'true';
    btnExpandQuiz.addEventListener('click', (e) => {
      e.stopPropagation();
      expandQuizPanel();
    });
  }

  // Click anywhere on #panel-quiz or #quiz-collapsed-rail when collapsed
  if (panelQuiz && !panelQuiz.dataset.railClickListener) {
    panelQuiz.dataset.railClickListener = 'true';
    panelQuiz.addEventListener('click', () => {
      if (panelQuiz.classList.contains('panel-rail-collapsed')) {
        expandQuizPanel();
      }
    });
  }
  if (railQuiz && !railQuiz.dataset.railClickListener) {
    railQuiz.dataset.railClickListener = 'true';
    railQuiz.addEventListener('click', () => {
      expandQuizPanel();
    });
  }
}

window.collapseRoadmapPanel = collapseRoadmapPanel;
window.expandRoadmapPanel = expandRoadmapPanel;
window.toggleRoadmapPanel = toggleRoadmapPanel;
window.collapseQuizPanel = collapseQuizPanel;
window.expandQuizPanel = expandQuizPanel;
window.toggleQuizPanel = toggleQuizPanel;

function startCheckpoint() {
  expandQuizPanel();
  const quizArea = document.getElementById('quiz-scroll-area');
  if (quizArea) {
    quizArea.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }
}

// Helper: Check if a node corresponds to the active lesson node
function isActiveLessonNode(nodeId, nodeLabel) {
  if (!cachedState) return false;
  const activeId = (cachedState.active_node_id || '').toLowerCase().trim();
  const activeNode = (cachedState.active_node || cachedState.current_node || '').toLowerCase().trim();
  const targetId = (nodeId || '').toLowerCase().trim();
  const targetLabel = (nodeLabel || '').toLowerCase().trim();

  if (!targetId && !targetLabel) return false;

  // Exact ID or label match with active_node_id or active_node
  if (activeId && (targetId === activeId || targetLabel === activeId)) return true;
  if (activeNode && (targetId === activeNode || targetLabel === activeNode)) return true;

  // Clean label comparisons
  const cleanActive = activeNode.replace(/^(?:node\s*\d+[:.]\s*|baseline[:.]\s*|\d+[\.\)]\s*)/i, '').trim();
  const cleanTarget = (targetLabel || targetId).replace(/^(?:node\s*\d+[:.]\s*|baseline[:.]\s*|\d+[\.\)]\s*)/i, '').trim();
  if (cleanActive && cleanTarget && cleanActive === cleanTarget) return true;

  // Canonical ID comparisons
  const canonActive = cleanActive.replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '');
  const canonTarget = (targetId || cleanTarget).replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '');
  const canonActiveId = activeId.replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '');
  if (canonTarget && (canonTarget === canonActive || canonTarget === canonActiveId)) return true;
  if (canonTarget && canonActive && (canonTarget.includes(canonActive) || canonActive.includes(canonTarget)) && canonTarget.length > 3) return true;

  // Number comparison (e.g. node-1 and Node 1: ...)
  const activeNums = (activeId + ' ' + activeNode).match(/node[-_\s]?(\d+)|\b(\d+)[\.\:]/i);
  const targetNums = (targetId + ' ' + targetLabel).match(/node[-_\s]?(\d+)|\b(\d+)[\.\:]/i);
  const actN = activeNums ? (activeNums[1] || activeNums[2]) : null;
  const tgtN = targetNums ? (targetNums[1] || targetNums[2]) : null;
  if (actN !== null && tgtN !== null && actN === tgtN) return true;

  return false;
}

// Return back to active lesson note and exit Reference Mode
function exitReferenceMode() {
  isReferenceMode = false;
  currentReferenceNode = null;

  const refBanner = document.getElementById('reference-mode-banner');
  if (refBanner) refBanner.classList.add('hidden');

  const lessonContainer = document.getElementById('lesson-content');
  const activeMarkdown = (cachedState && cachedState.lesson_markdown) || cachedActiveNote || '';
  if (lessonContainer) {
    if (activeMarkdown) {
      renderLesson(activeMarkdown, cachedState.active_node_id, cachedState.active_node);
    } else {
      lessonContainer.innerHTML = `
        <div class="py-16 text-center text-slate-500">
          <p class="text-xs">No active lesson notes available yet.</p>
        </div>
      `;
    }
  }
}

// Backward compatibility alias
function returnToActiveLesson() {
  exitReferenceMode();
}

// Load arbitrary node into lesson notes workspace (Reference Mode) with Smart Active-Node Routing
async function loadNodeReference(nodeId, nodeLabel) {
  if (!nodeId) return;

  // Check if nodeId matches state.active_node_id or represents the active lesson
  if (isActiveLessonNode(nodeId, nodeLabel)) {
    exitReferenceMode();
    return;
  }

  const lessonContainer = document.getElementById('lesson-content');
  const refBanner = document.getElementById('reference-mode-banner');
  const refTitle = document.getElementById('reference-node-title');
  if (!lessonContainer) return;

  // Cache active lesson note before switching if not already in reference mode
  if (!isReferenceMode && cachedState && cachedState.lesson_markdown) {
    cachedActiveNote = cachedState.lesson_markdown;
  }

  isReferenceMode = true;
  currentReferenceNode = { id: nodeId, label: nodeLabel || nodeId };

  if (refBanner && refTitle) {
    refTitle.textContent = nodeLabel || nodeId;
    refBanner.classList.remove('hidden');
  }

  lessonContainer.innerHTML = `
    <div class="py-12 text-center text-slate-400 font-mono text-xs">
      <span>Loading reference note for "${escapeHtml(nodeLabel || nodeId)}"...</span>
    </div>
  `;

  try {
    const resp = await fetch(`/api/notes/${encodeURIComponent(nodeId)}`);
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const data = await resp.json();

    if (data.found && data.content) {
      const cleaned = stripFrontmatter(data.content);
      const processed = preprocessWikilinks(cleaned);
      let html = (typeof marked !== 'undefined') ? marked.parse(processed) : processed;
      html = interceptMermaidBlocks(html);
      html = formatObsidianCallouts(html);
      lessonContainer.innerHTML = html;
      renderMath(lessonContainer);
      runMermaidOnNotes(lessonContainer);
    } else {
      const statusLower = (data.status || 'planned').toLowerCase();
      const isMastered = statusLower === 'mastered';
      const token = (data.origin === 'diagnostic') ? '[BASELINE]' : (isMastered ? '[MASTERED]' : (statusLower === 'active' ? '[ACTIVE]' : '[PLANNED]'));
      const prereqs = data.prerequisites || [];
      let prereqHtml = '';
      if (prereqs.length > 0) {
        prereqHtml = `
          <div class="mt-4 pt-4 border-t border-slate-800">
            <div class="text-xs font-mono font-semibold text-slate-400 uppercase tracking-wider mb-2">[PREREQUISITES]</div>
            <div class="flex flex-wrap gap-2">
              ${prereqs.map(p => {
                const pId = typeof p === 'object' ? p.id : p;
                const pLbl = typeof p === 'object' ? (p.label || p.id) : p;
                return `<button onclick="loadNodeReference('${pId}', '${escapeHtml(pLbl)}')" class="graph-wikilink text-xs font-mono">[ ${escapeHtml(pLbl)} ]</button>`;
              }).join('')}
            </div>
          </div>
        `;
      }

      lessonContainer.innerHTML = `
        <div class="rounded-xl bg-slate-900/60 border border-slate-800 p-6 shadow-lg">
          <div class="inline-block px-2 py-0.5 rounded text-[11px] font-mono text-slate-400 border border-slate-700 bg-slate-800/80 mb-3">
            ${token}
          </div>
          <h2 class="text-lg font-bold text-slate-100 !mt-0 !mb-2 font-mono">${escapeHtml(data.label || nodeLabel || nodeId)}</h2>
          <p class="text-xs text-slate-400 leading-relaxed font-mono">
            Lesson notes have not been compiled for this node yet.
          </p>
          ${prereqHtml}
        </div>
      `;
    }
  } catch (err) {
    console.warn('Failed to load note into workspace:', err);
    lessonContainer.innerHTML = `
      <div class="p-6 rounded-xl bg-slate-900/60 border border-slate-800 text-xs font-mono text-slate-400">
        [NOTE UNAVAILABLE FOR NODE: ${escapeHtml(nodeId)}]
      </div>
    `;
  }
}

// Backward-compatibility alias
const loadNoteIntoWorkspace = loadNodeReference;

// Attach delegated click listener on Roadmap nodes
function setupRoadmapClickDelegation() {
  const container = document.getElementById('dag-container');
  if (!container) return;

  container.addEventListener('click', (e) => {
    const nodeEl = e.target.closest('.node');
    if (!nodeEl) return;

    // Direct active-class shortcut
    if (nodeEl.classList.contains('active')) {
      exitReferenceMode();
      return;
    }

    let label = '';
    const labelSpan = nodeEl.querySelector('.nodeLabel') || nodeEl.querySelector('text') || nodeEl.querySelector('tspan');
    if (labelSpan) {
      label = labelSpan.textContent.trim();
    } else {
      label = nodeEl.textContent.trim();
    }

    if (label) {
      const cleanLabel = label.replace(/^(?:node\s*\d+[:.]\s*|baseline[:.]\s*|\d+[\.\)]\s*)/i, '').trim();
      const canonicalId = cleanLabel.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '');
      loadNodeReference(canonicalId, label);
    }
  });
}

// Global window bindings for inline HTML onclick handlers
window.loadNodeReference = loadNodeReference;
window.loadNoteIntoWorkspace = loadNodeReference;
window.exitReferenceMode = exitReferenceMode;
window.returnToActiveLesson = exitReferenceMode;

// Explicit user action to enter Study Mode
let isStudyViewExplicitlyActive = false;

// Resume Paused Session from Idle Card
function resumeStudySession() {
  isStudyViewExplicitlyActive = true;
  const studyEl = document.getElementById('workspace-study');
  const idleEl = document.getElementById('workspace-idle');
  const badgeEl = document.getElementById('header-session-badge');

  if (studyEl && idleEl) {
    studyEl.classList.remove('hidden');
    idleEl.classList.add('hidden');
  }
  if (badgeEl) {
    badgeEl.textContent = '[ACTIVE]';
    badgeEl.className = 'text-[10px] uppercase font-mono font-semibold tracking-wider px-2 py-0.5 rounded bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 shadow-sm animate-pulse';
  }
  if (cachedState.dag_mermaid) {
    renderMermaidDAG(cachedState.dag_mermaid);
  }
  if (cachedState.lesson_markdown) {
    renderLesson(cachedState.lesson_markdown, cachedState.active_node_id, cachedState.active_node);
  }
  renderQuiz(cachedState.active_quiz, cachedState.latest_answer);
}

// Discard / Reset Session from Idle Card
async function discardStudySession() {
  await resetSession(true);
}

// Update Paused Session Card inside #workspace-idle
function updatePausedSessionCard(state) {
  const card = document.getElementById('unfinished-session-card');
  const titleEl = document.getElementById('unfinished-topic-title');
  const nodeEl = document.getElementById('unfinished-node-label');
  if (!card) return;

  const hasPausedSession = Boolean(
    state.topic &&
    state.topic !== "Not Set" &&
    state.phase &&
    state.phase.toUpperCase() !== "IDLE"
  );

  if (hasPausedSession && !isStudyViewExplicitlyActive) {
    if (titleEl) titleEl.textContent = `Topic: ${state.topic}`;
    const activeNodeName = state.active_node || state.current_node || 'In Progress';
    if (nodeEl) nodeEl.textContent = `Current Node: ${activeNodeName}`;
    card.classList.remove('hidden');
  } else {
    card.classList.add('hidden');
  }
}

// Reset Session (used by top navbar [RESET] and [DISCARD / RESET])
async function resetSession(skipConfirm = false) {
  if (!skipConfirm && !confirm('Are you sure you want to reset the session state?')) return;
  try {
    const resp = await fetch('/api/reset', { method: 'POST' });
    if (resp.ok) {
      const data = await resp.json();
      selectedOptionLocal = null;
      isStudyViewExplicitlyActive = false;
      isReferenceMode = false;
      cachedActiveNote = null;

      // Merge returned state
      const blankState = data.state || {
        session_active: false,
        topic: "Not Set",
        phase: "IDLE",
        active_node: null,
        notes: "",
        quiz: null
      };
      cachedState = { ...cachedState, ...blankState };

      // Explicitly enforce Idle Command Center visibility
      const studyEl = document.getElementById('workspace-study');
      const idleEl = document.getElementById('workspace-idle');
      if (studyEl) studyEl.classList.add('hidden');
      if (idleEl) idleEl.classList.remove('hidden');

      // Immediately update header labels to clean standby
      updateHeader(cachedState);
      const badgeEl = document.getElementById('header-session-badge');
      if (badgeEl) {
        badgeEl.textContent = '[STANDBY]';
        badgeEl.className = 'text-[10px] uppercase font-mono font-semibold tracking-wider px-2 py-0.5 rounded bg-slate-800 text-slate-400 border border-slate-700/60';
      }

      // Hide paused session card
      updatePausedSessionCard(cachedState);

      // Clear roadmap and notes views
      const dagContainer = document.getElementById('dag-container');
      if (dagContainer) {
        dagContainer.innerHTML = `
          <div class="py-16 text-center text-slate-500 font-mono text-xs">
            <p>[NO ROADMAP GENERATED]</p>
            <p class="text-[11px] text-slate-600 mt-1">DAG will render upon curriculum initialization.</p>
          </div>
        `;
      }
      const lessonContent = document.getElementById('lesson-content');
      if (lessonContent) {
        lessonContent.innerHTML = `
          <div class="py-16 text-center text-slate-500 font-mono text-xs">
            <p>[NO LESSON NOTES AVAILABLE]</p>
            <p class="text-[11px] text-slate-600 mt-1">Teaching stream will render notes and math in real-time.</p>
          </div>
        `;
      }
      renderQuiz(null, null);

      showToast("Workspace state reset to clean idle standby.");
    }
  } catch (err) {
    console.error('Failed to reset session:', err);
  }
}

// Reactive State Dispatcher
function updateUI(newState, force = false) {
  // Header update
  if (force || newState.topic !== cachedState.topic || newState.phase !== cachedState.phase) {
    updateHeader(newState);
  }

  const studyEl = document.getElementById('workspace-study');
  const idleEl = document.getElementById('workspace-idle');
  const badgeEl = document.getElementById('header-session-badge');

  // Update paused session card inside Idle Center
  updatePausedSessionCard(newState);

  // Automatic Real-Time Transition:
  const phaseUpper = String(newState.phase || '').toUpperCase();
  const isSessionActive = Boolean(
    newState.session_active === true ||
    (phaseUpper && phaseUpper !== 'IDLE' && newState.topic && newState.topic !== 'Not Set')
  );

  if (studyEl && idleEl) {
    if (isSessionActive) {
      // When state.session_active === true (or phase is not IDLE):
      // If #workspace-study is currently hidden, transition automatically!
      if (studyEl.classList.contains('hidden')) {
        isStudyViewExplicitlyActive = true;
        idleEl.classList.add('hidden');
        studyEl.classList.remove('hidden');
        if (badgeEl) {
          badgeEl.textContent = '[ACTIVE]';
          badgeEl.className = 'text-[10px] uppercase font-mono font-semibold tracking-wider px-2 py-0.5 rounded bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 shadow-sm animate-pulse';
        }
        if (newState.dag_mermaid) {
          renderMermaidDAG(newState.dag_mermaid);
        }
        if (newState.lesson_markdown) {
          renderLesson(newState.lesson_markdown, newState.active_node_id, newState.active_node);
        }
      } else {
        if (badgeEl && badgeEl.textContent !== '[ACTIVE]') {
          badgeEl.textContent = '[ACTIVE]';
          badgeEl.className = 'text-[10px] uppercase font-mono font-semibold tracking-wider px-2 py-0.5 rounded bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 shadow-sm animate-pulse';
        }
      }
    } else {
      // When state.session_active === false or state.phase === "IDLE":
      // Keep #workspace-idle visible and #workspace-study hidden unless explicitly resumed
      if (!isStudyViewExplicitlyActive) {
        studyEl.classList.add('hidden');
        idleEl.classList.remove('hidden');
        if (badgeEl) {
          badgeEl.textContent = '[STANDBY]';
          badgeEl.className = 'text-[10px] uppercase font-mono font-semibold tracking-wider px-2 py-0.5 rounded bg-slate-800 text-slate-400 border border-slate-700/60';
        }
      }
    }
  }

  // Column 1: DAG Roadmap
  if (force || newState.dag_mermaid !== cachedState.dag_mermaid) {
    renderMermaidDAG(newState.dag_mermaid);
  }

  // Column 2: Lesson Notes
  if (!isReferenceMode) {
    const activeNodeChanged = (newState.active_node_id && newState.active_node_id !== cachedState.active_node_id) ||
                              (newState.active_node && newState.active_node !== cachedState.active_node);
    if (force || newState.lesson_markdown !== cachedState.lesson_markdown || activeNodeChanged) {
      cachedActiveNote = newState.lesson_markdown;
      renderLesson(newState.lesson_markdown, newState.active_node_id, newState.active_node);
    }
  }

  // Column 3: Quiz
  const oldQuizSig = getQuizSignature(cachedState.active_quiz);
  const newQuizSig = getQuizSignature(newState.active_quiz);
  const quizSignatureChanged = oldQuizSig !== newQuizSig;
  const quizChanged = JSON.stringify(newState.active_quiz) !== JSON.stringify(cachedState.active_quiz);
  const answerChanged = JSON.stringify(newState.latest_answer) !== JSON.stringify(cachedState.latest_answer);
  if (force || quizChanged || answerChanged) {
    if (quizSignatureChanged) {
      selectedOptionLocal = null;
      multiAnswersLocal = {};
      currentQuizSignature = newQuizSig;
      // Pulse the mini-rail if quiz becomes active while collapsed
      const railDot = document.getElementById('rail-quiz-dot');
      if (railDot && newState.active_quiz) {
        railDot.className = 'w-2 h-2 rounded-full bg-violet-400 animate-ping';
      } else if (railDot) {
        railDot.className = 'w-2 h-2 rounded-full bg-slate-600';
      }
    }
    renderQuiz(newState.active_quiz, newState.latest_answer);
  }

  cachedState = newState;
}


// Command Click-to-Copy Helper
async function copyCommand(text) {
  if (!text) return;
  try {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      await navigator.clipboard.writeText(text);
    } else {
      const textarea = document.createElement('textarea');
      textarea.value = text;
      document.body.appendChild(textarea);
      textarea.select();
      document.execCommand('copy');
      document.body.removeChild(textarea);
    }
    showToast(`Copied "${text}" to clipboard! Paste into chat to execute.`);
  } catch (err) {
    console.warn('Clipboard write error:', err);
    showToast(`Copied "${text}"`, 'success');
  }
}

// Guide Modal Controls
function openGuideModal() {
  const modal = document.getElementById('guide-modal');
  if (modal) {
    modal.classList.remove('hidden');
  }
}

function closeGuideModal() {
  const modal = document.getElementById('guide-modal');
  if (modal) {
    modal.classList.add('hidden');
  }
}

// Toast Banner System
function showToast(message, type = 'success') {
  const container = document.getElementById('toast-container');
  if (!container) return;

  const toast = document.createElement('div');
  toast.className = 'pointer-events-auto max-w-md bg-slate-900/95 border border-indigo-500/50 text-slate-100 shadow-2xl shadow-indigo-950/60 rounded-xl p-3.5 text-xs flex items-start gap-3 backdrop-blur-md transition-all duration-300 transform translate-y-3 opacity-0 ring-1 ring-white/10 font-mono';

  const icon = document.createElement('div');
  icon.className = 'shrink-0 mt-0.5 text-indigo-400 font-bold';
  icon.innerText = '[INFO]';

  const text = document.createElement('div');
  text.className = 'flex-1 leading-relaxed text-slate-200';
  text.innerText = message;

  toast.appendChild(icon);
  toast.appendChild(text);
  container.appendChild(toast);

  requestAnimationFrame(() => {
    toast.classList.remove('translate-y-3', 'opacity-0');
    toast.classList.add('translate-y-0', 'opacity-100');
  });

  setTimeout(() => {
    toast.classList.remove('translate-y-0', 'opacity-100');
    toast.classList.add('translate-y-2', 'opacity-0');
    setTimeout(() => toast.remove(), 350);
  }, 5500);
}

// Saved Topics Menu Management & Robust Discovery
async function loadSavedTopics() {
  const containers = document.querySelectorAll('.topics-list-container, #saved-topics-dropdown, #topic-list-container, #saved-topics-list, #idle-topic-picker-list');
  try {
    const res = await fetch('/api/topics');
    if (!res.ok) throw new Error(`HTTP ${res.status} ${res.statusText}`);
    const data = await res.json();
    const topics = Array.isArray(data) ? data : (data.topics || []);

    if (typeof checkUnfinishedSession === 'function') {
      checkUnfinishedSession(topics);
    }

    const countBadge = document.getElementById('saved-topics-count');
    if (countBadge) {
      if (topics.length > 0) {
        countBadge.innerText = topics.length;
        countBadge.classList.remove('hidden');
      } else {
        countBadge.classList.add('hidden');
      }
    }

    containers.forEach(container => {
      if (topics.length === 0) {
        container.innerHTML = '<div class="topic-empty-item">[NO SAVED TOPICS FOUND]</div>';
        return;
      }
      container.innerHTML = topics.map(t => `
        <div class="topic-item" data-topic="${escapeHtml(t.name)}">
          <div class="topic-item-header">
            <span class="topic-item-title">${escapeHtml(t.name)}</span>
            <span class="topic-badge monospace">[${t.mastered_nodes}/${t.total_nodes} MASTERED]</span>
          </div>
          <div class="topic-item-sub">Active: ${escapeHtml(t.active_node || 'None')}</div>
        </div>
      `).join('');
    });
  } catch (err) {
    console.error('Failed to load saved topics:', err);
    containers.forEach(container => {
      container.innerHTML = `<div class="topic-error-item">[ERROR: ${err.message}]</div>`;
    });
  }
}
const fetchSavedTopics = loadSavedTopics;

function toggleSavedTopicsDropdown() {
  const menu = document.getElementById('saved-topics-menu');
  const chevron = document.getElementById('saved-topics-chevron');
  if (!menu) return;
  const isHidden = menu.classList.contains('hidden');
  if (isHidden) {
    menu.classList.remove('hidden');
    if (chevron) chevron.classList.add('rotate-180');
    loadSavedTopics();
  } else {
    menu.classList.add('hidden');
    if (chevron) chevron.classList.remove('rotate-180');
  }
}

function closeSavedTopicsDropdown() {
  const menu = document.getElementById('saved-topics-menu');
  const chevron = document.getElementById('saved-topics-chevron');
  if (menu && !menu.classList.contains('hidden')) {
    menu.classList.add('hidden');
    if (chevron) chevron.classList.remove('rotate-180');
  }
}

document.addEventListener('click', (e) => {
  const container = document.getElementById('saved-topics-dropdown-container');
  if (container && !container.contains(e.target)) {
    closeSavedTopicsDropdown();
  }
});

// Idle Center Inline Topic Picker
function openIdleTopicPicker() {
  const picker = document.getElementById('idle-topic-picker');
  const btn = document.getElementById('btn-idle-topics');
  if (!picker) return;
  picker.classList.remove('hidden');
  if (btn) {
    btn.classList.add('border-indigo-500/50', 'bg-indigo-950/30');
    btn.classList.remove('border-slate-700/80');
  }
  loadSavedTopics();
}

function closeIdleTopicPicker() {
  const picker = document.getElementById('idle-topic-picker');
  const btn = document.getElementById('btn-idle-topics');
  if (!picker) return;
  picker.classList.add('hidden');
  if (btn) {
    btn.classList.remove('border-indigo-500/50', 'bg-indigo-950/30');
    btn.classList.add('border-slate-700/80');
  }
}

// Select and Restore a Saved Topic
async function selectSavedTopic(topicName) {
  closeSavedTopicsDropdown();
  closeIdleTopicPicker();
  try {
    const resp = await fetch('/api/topics/load', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ topic: topicName })
    });
    if (!resp.ok) {
      throw new Error(`Failed to load topic: ${resp.statusText}`);
    }
    const result = await resp.json();

    // Activate study view: hide #workspace-idle, show #workspace-study
    isStudyViewExplicitlyActive = true;
    const studyEl = document.getElementById('workspace-study');
    const idleEl = document.getElementById('workspace-idle');
    if (studyEl && idleEl) {
      idleEl.classList.add('hidden');
      studyEl.classList.remove('hidden');
    }

    // Update top navbar status badge to [ACTIVE]
    const badgeEl = document.getElementById('header-session-badge');
    if (badgeEl) {
      badgeEl.textContent = '[ACTIVE]';
      badgeEl.className = 'text-[10px] uppercase font-mono font-semibold tracking-wider px-2 py-0.5 rounded bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 shadow-sm animate-pulse';
    }
    const topicEl = document.getElementById('header-topic');
    if (topicEl) topicEl.textContent = topicName;
    const phaseEl = document.getElementById('header-phase');
    if (phaseEl) {
      phaseEl.textContent = 'teaching';
      phaseEl.className = 'uppercase font-bold tracking-wider text-indigo-400 font-mono';
    }
    const phaseDot = document.getElementById('header-phase-dot');
    if (phaseDot) phaseDot.className = 'w-2 h-2 rounded-full bg-indigo-400 shadow-sm shadow-indigo-400';

    // Instantly reload state, roadmap and notes panels
    await pollState();

    // Copy .resume command to clipboard
    const resumeCommand = `.resume ${topicName}`;
    try {
      if (navigator.clipboard && navigator.clipboard.writeText) {
        await navigator.clipboard.writeText(resumeCommand);
      } else {
        const textarea = document.createElement('textarea');
        textarea.value = resumeCommand;
        document.body.appendChild(textarea);
        textarea.select();
        document.execCommand('copy');
        document.body.removeChild(textarea);
      }
    } catch (clipErr) {
      console.warn('Clipboard write error:', clipErr);
    }

    // Display toast confirmation
    showToast(`Loaded ${topicName} onto dashboard! Command copied: paste '.resume ${topicName}' into Antigravity chat.`);
  } catch (err) {
    console.error('Error loading topic:', err);
    showToast(`Failed to load topic "${topicName}": ${err.message}`, 'error');
  }
}

// Delegated click event listener for .topic-item
document.addEventListener('click', (e) => {
  const topicItem = e.target.closest('.topic-item');
  if (topicItem) {
    const topicName = topicItem.getAttribute('data-topic');
    if (topicName) {
      selectSavedTopic(topicName);
    }
  }
});

// Polling State Fetcher
async function pollState() {
  try {
    const response = await fetch('/api/state');
    if (response.ok) {
      const state = await response.json();
      updateUI(state);
    }
  } catch (err) {
    // Network or server restart blip, ignore silently
  }
}

// Automated Polling Loop (1500ms, visible tabs only)
setInterval(() => {
  if (document.visibilityState === 'visible') {
    pollState();
  }
}, 1500);

// Periodic saved topics refresh (every 10s)
setInterval(() => {
  if (document.visibilityState === 'visible') {
    fetchSavedTopics();
  }
}, 10000);

// Initial load
document.addEventListener('DOMContentLoaded', () => {
  pollState();
  fetchSavedTopics();
  setupGraphNavControls();
  setupGraphResizer();
  setupRoadmapResizer();
  setupRoadmapClickDelegation();
  setupCollapsiblePanels();
});

// ==========================================
// Obsidian 2D Global Knowledge Graph Canvas
// ==========================================
let knowledgeGraphInstance = null;
let graphDataCache = { nodes: [], links: [] };
let selectedNode = null;
let hoverNode = null;
const neighborsMap = new Map(); // nodeId -> Set of neighbor IDs
const linksMap = new Map();     // nodeId -> Set of link objects
let searchQuery = '';

function rebuildAdjacencyMaps(nodes, links) {
  neighborsMap.clear();
  linksMap.clear();

  const degreeCounts = new Map();

  nodes.forEach(node => {
    neighborsMap.set(node.id, new Set());
    linksMap.set(node.id, new Set());
    degreeCounts.set(node.id, 0);
  });

  links.forEach(link => {
    const srcId = (typeof link.source === 'object' && link.source !== null) ? link.source.id : link.source;
    const tgtId = (typeof link.target === 'object' && link.target !== null) ? link.target.id : link.target;

    if (!neighborsMap.has(srcId)) neighborsMap.set(srcId, new Set());
    if (!neighborsMap.has(tgtId)) neighborsMap.set(tgtId, new Set());
    neighborsMap.get(srcId).add(tgtId);
    neighborsMap.get(tgtId).add(srcId);

    if (!linksMap.has(srcId)) linksMap.set(srcId, new Set());
    if (!linksMap.has(tgtId)) linksMap.set(tgtId, new Set());
    linksMap.get(srcId).add(link);
    linksMap.get(tgtId).add(link);

    degreeCounts.set(srcId, (degreeCounts.get(srcId) || 0) + 1);
    degreeCounts.set(tgtId, (degreeCounts.get(tgtId) || 0) + 1);
  });

  nodes.forEach(node => {
    const degree = degreeCounts.get(node.id) || 0;
    node.__degree = degree;
    node.__size = Math.max(3.5, Math.min(12, 3 + Math.sqrt(degree) * 2));
  });
}

function isFocusLink(focus, link) {
  if (!focus) return false;
  const fLinks = linksMap.get(focus.id);
  if (fLinks && fLinks.has(link)) return true;
  const srcId = (typeof link.source === 'object' && link.source !== null) ? link.source.id : link.source;
  const tgtId = (typeof link.target === 'object' && link.target !== null) ? link.target.id : link.target;
  return srcId === focus.id || tgtId === focus.id;
}

function matchesSearch(nodeOrId) {
  if (!searchQuery) return false;
  let label = '';
  let topics = [];
  if (typeof nodeOrId === 'object' && nodeOrId !== null) {
    label = (nodeOrId.label || nodeOrId.id || '').toLowerCase();
    topics = (nodeOrId.topics || []).map(t => String(t).toLowerCase());
  } else if (typeof nodeOrId === 'string') {
    label = nodeOrId.toLowerCase();
  }
  return label.includes(searchQuery) || topics.some(t => t.includes(searchQuery));
}

function stripFrontmatter(md) {
  if (!md) return '';
  return md.replace(/^---[\r\n]+[\s\S]*?[\r\n]+---[\r\n]*/, '').trim();
}

function preprocessWikilinks(md) {
  if (!md) return '';
  return md.replace(/\[\[(.*?)\]\]/g, (match, target) => {
    const cleanTarget = target.trim();
    return `<a class="graph-wikilink" data-target="${cleanTarget}">[[ ${cleanTarget} ]]</a>`;
  });
}

function closeNoteDrawer() {
  const drawer = document.getElementById('graph-note-drawer');
  const resizer = document.getElementById('graph-resizer');
  const viewportEl = document.getElementById('graph-viewport');

  if (drawer) drawer.classList.add('hidden');
  if (resizer) resizer.classList.add('hidden');

  if (knowledgeGraphInstance && viewportEl) {
    knowledgeGraphInstance.width(viewportEl.clientWidth);
  }
}

function formatObsidianCallouts(html) {
  if (!html) return '';
  return html.replace(/<blockquote>([\s\S]*?)<\/blockquote>/gi, (match, inner) => {
    const calloutMatch = inner.match(/<p>\s*\[!(info|success|warning|note|tip|important)\]\s*([^\n<]*)(?:<br\s*\/?>|\n)?([\s\S]*?)<\/p>/i);
    if (!calloutMatch) return match;
    const type = calloutMatch[1].toLowerCase();
    const isSuccess = type === 'success';
    const defaultTitle = isSuccess ? 'Curriculum Mastery' : 'Verified Baseline Knowledge';
    const rawTitle = calloutMatch[2].trim();
    const displayTitle = rawTitle || defaultTitle;
    const firstPBody = calloutMatch[3].trim();
    const bodyContent = firstPBody ? `<div class="callout-content">${firstPBody}</div>` : '';
    const remaining = inner.replace(calloutMatch[0], bodyContent).trim();
    return `
      <blockquote class="obsidian-callout callout-${type}">
        <div class="callout-title font-mono">
          <span class="callout-heading">[${displayTitle.toUpperCase()}]</span>
        </div>
        ${remaining}
      </blockquote>
    `;
  });
}

async function openNoteDrawer(node) {
  const drawer = document.getElementById('graph-note-drawer');
  const resizer = document.getElementById('graph-resizer');
  const viewportEl = document.getElementById('graph-viewport');
  const topicEl = document.getElementById('note-drawer-topic');
  const bodyEl = document.getElementById('note-drawer-body');
  if (!drawer || !bodyEl) return;

  const nodeId = typeof node === 'object' ? (node.id || '') : String(node);
  const nodeLabel = typeof node === 'object' ? (node.label || node.id || '') : String(node);
  const nodeTopics = (typeof node === 'object' && Array.isArray(node.topics)) ? node.topics.join(', ') : '';
  const nodeOrigin = (typeof node === 'object' && node.origin) ? node.origin : '';
  const nodeStatus = (typeof node === 'object' && node.status) ? node.status : 'planned';

  function updateDrawerBadge(origin, status) {
    if (!topicEl) return;
    const normOrigin = (origin || '').toLowerCase();
    const normStatus = (status || 'planned').toLowerCase();

    if (normOrigin === 'diagnostic') {
      topicEl.className = 'note-badge badge-baseline font-mono';
      topicEl.innerHTML = '[BASELINE]';
    } else if (normOrigin === 'curriculum' || normStatus === 'mastered') {
      topicEl.className = 'note-badge badge-curriculum font-mono';
      topicEl.innerHTML = '[MASTERED]';
    } else if (normStatus === 'active') {
      topicEl.className = 'note-badge badge-active font-mono';
      topicEl.innerHTML = '[ACTIVE]';
    } else {
      topicEl.className = 'note-badge badge-planned font-mono';
      topicEl.innerHTML = '[PLANNED]';
    }
  }

  updateDrawerBadge(nodeOrigin, nodeStatus);

  bodyEl.innerHTML = `<div class="p-6 text-xs text-slate-400 flex items-center gap-2">
    <svg class="animate-spin h-4 w-4 text-indigo-400" fill="none" viewBox="0 0 24 24">
      <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
      <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z"></path>
    </svg>
    <span>Loading notes for "${nodeLabel}"...</span>
  </div>`;

  // Apply saved or default (50%) width
  const savedWidth = localStorage.getItem('graph_drawer_width') || '50%';
  drawer.style.width = savedWidth;

  drawer.classList.remove('hidden');
  if (resizer) resizer.classList.remove('hidden');

  // Recalculate canvas width
  if (knowledgeGraphInstance && viewportEl) {
    knowledgeGraphInstance.width(viewportEl.clientWidth);
  }

  try {
    const resp = await fetch(`/api/notes/${encodeURIComponent(nodeId)}`);
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const data = await resp.json();

    const origin = data.origin || nodeOrigin;
    const status = data.status || nodeStatus;
    updateDrawerBadge(origin, status);

    if (data.found && data.content) {
      const cleaned = stripFrontmatter(data.content);
      const processed = preprocessWikilinks(cleaned);
      let html = (typeof marked !== 'undefined') ? marked.parse(processed) : processed;
      html = interceptMermaidBlocks(html);
      html = formatObsidianCallouts(html);
      bodyEl.innerHTML = html;

      if (window.renderMathInElement) {
        try {
          window.renderMathInElement(bodyEl, {
            delimiters: [
              { left: '$$', right: '$$', display: true },
              { left: '$', right: '$', display: false },
              { left: '\\[', right: '\\]', display: true },
              { left: '\\(', right: '\\)', display: false }
            ],
            throwOnError: false
          });
        } catch (mathErr) {
          console.warn('Math render error:', mathErr);
        }
      }
      runMermaidOnNotes(bodyEl);
    } else {
      // Placeholder card for not found / planned / locked node
      const statusLower = (status || 'planned').toLowerCase();
      const isMastered = statusLower === 'mastered';
      const statusColor = (origin === 'diagnostic') ? 'sky' : (isMastered ? 'emerald' : (statusLower === 'active' ? 'amber' : 'slate'));
      const statusBadge = (origin === 'diagnostic') ? '[BASELINE]' : (isMastered ? '[MASTERED]' : (statusLower === 'active' ? '[ACTIVE]' : '[PLANNED]'));

      const prereqs = data.prerequisites || [];
      let prereqHtml = '';
      if (prereqs.length > 0) {
        prereqHtml = `
          <div class="mt-4 pt-4 border-t border-slate-800">
            <div class="text-xs font-semibold text-slate-400 font-mono uppercase tracking-wider mb-2.5">[PREREQUISITES REQUIRED]</div>
            <div class="flex flex-wrap gap-2">
              ${prereqs.map(p => {
                const pId = typeof p === 'object' ? p.id : p;
                const pLbl = typeof p === 'object' ? (p.label || p.id) : p;
                const pStatus = typeof p === 'object' ? (p.status || 'planned') : 'planned';
                const pToken = pStatus === 'mastered' ? '[M]' : '[P]';
                return `<button class="graph-wikilink text-xs font-mono flex items-center gap-1.5" data-target="${pId}" title="Inspect prerequisite ${pLbl}">
                  <span class="${pStatus === 'mastered' ? 'text-emerald-400' : 'text-slate-400'}">${pToken}</span>
                  <span>${pLbl}</span>
                </button>`;
              }).join('')}
            </div>
          </div>
        `;
      } else {
        prereqHtml = `
          <div class="mt-4 pt-4 border-t border-slate-800 text-xs text-slate-500 font-mono italic">
            Foundational concept with no incoming prerequisites.
          </div>
        `;
      }

      bodyEl.innerHTML = `
        <div class="rounded-xl bg-slate-900/60 border border-slate-800 p-5 shadow-lg">
          <div class="flex items-center gap-2 mb-3">
            <span class="px-2 py-0.5 rounded text-[11px] font-mono font-semibold bg-${statusColor}-500/10 text-${statusColor}-400 border border-${statusColor}-500/20">
              ${statusBadge}
            </span>
          </div>
          <h2 class="text-lg font-bold text-slate-100 !mt-0 !mb-2">${data.label || nodeLabel}</h2>
          <p class="text-xs text-slate-400 leading-relaxed mb-0">
            Lesson notes have not been compiled for this node yet. Complete earlier prerequisite nodes to unlock and study this concept in interactive teaching mode.
          </p>
          ${prereqHtml}
        </div>
      `;
    }

    // Attach click listeners to all .graph-wikilink in drawer
    bodyEl.querySelectorAll('.graph-wikilink').forEach(link => {
      link.addEventListener('click', e => {
        e.preventDefault();
        const targetSlug = link.getAttribute('data-target');
        if (targetSlug) {
          navigateToGraphNode(targetSlug);
        }
      });
    });
  } catch (err) {
    console.error('Error fetching node note:', err);
    bodyEl.innerHTML = `
      <div class="p-4 rounded bg-red-950/40 border border-red-800 text-xs text-red-300">
        Failed to load note: ${err.message}
      </div>
    `;
  }
}

function navigateToGraphNode(targetSlug) {
  if (!targetSlug) return;
  const cleanTarget = targetSlug.toLowerCase().replace(/^(?:node\s*\d+[:.]\s*|\d+[\.\)]\s*)/i, '').trim().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '');
  const data = (knowledgeGraphInstance && typeof knowledgeGraphInstance.graphData === 'function')
    ? knowledgeGraphInstance.graphData()
    : graphDataCache;
  const nodes = (data && data.nodes) || [];

  let foundNode = nodes.find(n => {
    const nId = String(n.id || '').toLowerCase();
    const nLabel = String(n.label || '').toLowerCase();
    const nClean = nLabel.replace(/^(?:node\s*\d+[:.]\s*|\d+[\.\)]\s*)/i, '').trim();
    const nSlug = nClean.replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '');
    return nId === cleanTarget || nId === targetSlug.toLowerCase() || nLabel === targetSlug.toLowerCase() || nSlug === cleanTarget;
  });

  if (foundNode) {
    selectedNode = foundNode;
    hoverNode = null;
    if (knowledgeGraphInstance && typeof foundNode.x === 'number' && typeof foundNode.y === 'number') {
      knowledgeGraphInstance.centerAt(foundNode.x, foundNode.y, 450);
      knowledgeGraphInstance.zoom(2.0, 450);
    }
    openNoteDrawer(foundNode);
  } else {
    openNoteDrawer({ id: cleanTarget, label: targetSlug });
  }
}

function initForceGraph() {
  const container = document.getElementById('graph-viewport');
  if (!container || typeof ForceGraph === 'undefined') return;

  knowledgeGraphInstance = ForceGraph()(container)
    .backgroundColor('#0b0c10')
    .width(container.clientWidth || window.innerWidth)
    .height(container.clientHeight || (window.innerHeight - 56))
    .autoPauseRedraw(false)
    .cooldownTicks(120)
    .warmupTicks(40)
    .d3VelocityDecay(0.3)
    .enableZoomInteraction(true)
    .enablePanInteraction(true)
    .minZoom(0.1)
    .maxZoom(10)
    .linkCurvature(0.12)
    .linkDirectionalParticles(link => {
      const focus = hoverNode || selectedNode;
      return (focus && isFocusLink(focus, link)) ? 2 : 0;
    })
    .linkDirectionalParticleWidth(link => {
      const focus = hoverNode || selectedNode;
      return (focus && isFocusLink(focus, link)) ? 2 : 0;
    })
    .linkDirectionalParticleSpeed(0.005)
    .linkDirectionalParticleColor(() => '#38bdf8')
    .linkDirectionalArrowLength(link => {
      const focus = hoverNode || selectedNode;
      if (focus) {
        return isFocusLink(focus, link) ? 4 : 2;
      }
      return 3;
    })
    .linkDirectionalArrowRelPos(1)
    .linkDirectionalArrowColor(link => {
      const focus = hoverNode || selectedNode;
      if (focus) {
        return isFocusLink(focus, link) ? 'rgba(56, 189, 248, 0.8)' : 'rgba(148, 163, 184, 0.05)';
      }
      return 'rgba(148, 163, 184, 0.15)';
    })
    .linkColor(link => {
      try {
        const focus = hoverNode || selectedNode;
        if (focus) {
          return isFocusLink(focus, link) ? 'rgba(56, 189, 248, 0.7)' : 'rgba(148, 163, 184, 0.05)';
        }
        if (searchQuery) {
          const srcMatch = matchesSearch(link.source);
          const tgtMatch = matchesSearch(link.target);
          return (srcMatch && tgtMatch) ? 'rgba(56, 189, 248, 0.7)' : 'rgba(148, 163, 184, 0.05)';
        }
      } catch (err) {
        console.error('Error in linkColor:', err);
      }
      return 'rgba(148, 163, 184, 0.15)';
    })
    .linkWidth(link => {
      try {
        const focus = hoverNode || selectedNode;
        if (focus) {
          return isFocusLink(focus, link) ? 1.5 : 0.8;
        }
        if (searchQuery) {
          const srcMatch = matchesSearch(link.source);
          const tgtMatch = matchesSearch(link.target);
          return (srcMatch && tgtMatch) ? 1.5 : 0.8;
        }
      } catch (err) {
        console.error('Error in linkWidth:', err);
      }
      return 1;
    })
    .nodeCanvasObject((node, ctx, globalScale) => {
      try {
        const focus = hoverNode || selectedNode;
        const isHovered = Boolean(hoverNode && (node === hoverNode || node.id === hoverNode.id));
        const isSelected = Boolean(selectedNode && (node === selectedNode || node.id === selectedNode.id));
        const isNeighbor = Boolean(focus && neighborsMap.get(focus.id)?.has(node.id));
        const isConnected = isHovered || isSelected || isNeighbor;

        node.__hovered = isHovered;
        node.__highlighted = isConnected;

        // Dynamic degree and scaled radius: Math.max(3.5, Math.min(12, 3 + Math.sqrt(degree) * 2))
        const degree = typeof node.__degree === 'number' ? node.__degree : 0;
        const r = node.__size || Math.max(3.5, Math.min(12, 3 + Math.sqrt(degree) * 2));

        // Hover dimming: full opacity (1.0) for connected/focus, 0.2 for non-connected
        let alpha = 1.0;
        if (focus) {
          alpha = isConnected ? 1.0 : 0.2;
        } else if (searchQuery) {
          alpha = matchesSearch(node) ? 1.0 : 0.2;
        }

        ctx.save();
        ctx.globalAlpha = alpha;

        const status = (node.status || 'planned').toLowerCase();
        const isActiveNode = status === 'active' || (cachedState && cachedState.current_node && (node.id === cachedState.current_node || node.id === cachedState.current_node_id));

        // Status color coding: Mastered: #22c55e (Emerald), Active: #38bdf8 (Sky), Planned: #64748b (Slate)
        let nodeFill = '#64748b';
        let strokeColor = 'rgba(148, 163, 184, 0.4)';
        if (status === 'mastered') {
          nodeFill = '#22c55e';
          strokeColor = 'rgba(134, 239, 172, 0.6)';
        } else if (status === 'active' || isActiveNode) {
          nodeFill = '#38bdf8';
          strokeColor = 'rgba(186, 230, 253, 0.8)';
        }

        // Active lesson node outer glow ring
        if (status === 'active' || isActiveNode) {
          ctx.save();
          ctx.beginPath();
          ctx.arc(node.x, node.y, r + 4, 0, 2 * Math.PI, false);
          ctx.strokeStyle = 'rgba(56, 189, 248, 0.85)';
          ctx.lineWidth = 1.5 / globalScale;
          ctx.shadowColor = '#38bdf8';
          ctx.shadowBlur = 8;
          ctx.stroke();
          ctx.restore();
        }

        // Clean circular core node with subtle 1px stroke
        ctx.beginPath();
        ctx.arc(node.x, node.y, r, 0, 2 * Math.PI, false);
        ctx.fillStyle = nodeFill;
        ctx.fill();
        ctx.strokeStyle = strokeColor;
        ctx.lineWidth = 1 / globalScale;
        ctx.stroke();

        // Level of Detail (LOD) & Pill Labels
        const k = globalScale;
        const shouldDrawLabel = (k >= 0.75 || Boolean(node.__hovered || node.__highlighted)) || Boolean(searchQuery && matchesSearch(node));

        if (shouldDrawLabel) {
          // Semantic Detail Un-truncation (LOD) with Hysteresis
          const fullLabel = String(node.label || node.id || '');
          if (k > 1.35) {
            node.__isExpanded = true;
          } else if (k < 1.15) {
            node.__isExpanded = false;
          } else if (node.__isExpanded === undefined) {
            node.__isExpanded = false;
          }

          let label = fullLabel;
          if (!node.__isExpanded && fullLabel.length > 18) {
            label = fullLabel.slice(0, 18) + '...';
          }

          // Screen-Space Font Normalization: constant visual 11px font size without dividing or scaling by k
          const fontSize = 11;
          ctx.font = '11px monospace';
          const textMetrics = ctx.measureText(label);
          const textWidth = textMetrics.width;

          // Pill padding (3px 8px) and border radius (4px)
          const pillPaddingX = 8;
          const pillPaddingY = 3;
          const pillW = textWidth + pillPaddingX * 2;
          const pillH = fontSize + pillPaddingY * 2;
          const cornerRadius = Math.min(4, pillH / 2, pillW / 2);

          // Label Positioning: centered beneath node circle, offset tightly from perimeter
          const pillOffset = 4;
          const pillX = node.x - pillW / 2;
          const pillY = node.y + r + pillOffset;

          // Rounded dark pill background (fill: rgba(15, 23, 42, 0.85), border: rgba(51, 65, 85, 0.6))
          ctx.beginPath();
          if (ctx.roundRect) {
            ctx.roundRect(pillX, pillY, pillW, pillH, cornerRadius);
          } else {
            ctx.moveTo(pillX + cornerRadius, pillY);
            ctx.lineTo(pillX + pillW - cornerRadius, pillY);
            ctx.quadraticCurveTo(pillX + pillW, pillY, pillX + pillW, pillY + cornerRadius);
            ctx.lineTo(pillX + pillW, pillY + pillH - cornerRadius);
            ctx.quadraticCurveTo(pillX + pillW, pillY + pillH, pillX + pillW - cornerRadius, pillY + pillH);
            ctx.lineTo(pillX + cornerRadius, pillY + pillH);
            ctx.quadraticCurveTo(pillX, pillY + pillH, pillX, pillY + pillH - cornerRadius);
            ctx.lineTo(pillX, pillY + cornerRadius);
            ctx.quadraticCurveTo(pillX, pillY, pillX + cornerRadius, pillY);
            ctx.closePath();
          }
          ctx.fillStyle = 'rgba(15, 23, 42, 0.85)';
          ctx.fill();
          ctx.strokeStyle = 'rgba(51, 65, 85, 0.6)';
          ctx.lineWidth = 1;
          ctx.stroke();

          // Monospace text centered in pill
          ctx.textAlign = 'center';
          ctx.textBaseline = 'middle';
          ctx.fillStyle = '#e2e8f0';
          ctx.fillText(label, node.x, pillY + pillH / 2);
        }

        ctx.restore();
      } catch (err) {
        console.error('Error in nodeCanvasObject:', err);
      }
    })
    .nodePointerAreaPaint((node, color, ctx) => {
      const r = (node.__size || 6) + 4;
      ctx.fillStyle = color;
      ctx.beginPath();
      ctx.arc(node.x, node.y, r, 0, 2 * Math.PI, false);
      ctx.fill();
    })
    .onNodeHover(node => {
      try {
        const container = document.getElementById('graph-viewport');
        hoverNode = node || null;
        if (container) {
          container.style.cursor = node ? 'pointer' : 'default';
        }
      } catch (err) {
        console.error('Error in onNodeHover:', err);
      }
    })
    .onNodeClick(node => {
      try {
        if (!node) return;
        if (selectedNode === node || (selectedNode && selectedNode.id === node.id)) {
          selectedNode = null;
          closeNoteDrawer();
        } else {
          selectedNode = node;
          hoverNode = null;
          if (knowledgeGraphInstance) {
            knowledgeGraphInstance.centerAt(node.x, node.y, 450);
            knowledgeGraphInstance.zoom(2.0, 450);
          }
          openNoteDrawer(node);
        }
      } catch (err) {
        console.error('Error in onNodeClick:', err);
      }
    })
    .onBackgroundClick(() => {
      try {
        selectedNode = null;
        hoverNode = null;
        closeNoteDrawer();
      } catch (err) {
        console.error('Error in onBackgroundClick:', err);
      }
    })
    .onNodeDrag((node, translate) => {
      // Physics Reheating: tug and flex connected nodes when dragged
      if (knowledgeGraphInstance) {
        knowledgeGraphInstance.d3ReheatSimulation();
      }
    });

  if (typeof d3 !== 'undefined') {
    knowledgeGraphInstance
      .d3Force('charge', d3.forceManyBody().strength(-400))
      .d3Force('collide', d3.forceCollide().radius(node => (node.__size || 6) + 24))
      .d3Force('center', d3.forceCenter().strength(0.05));
    if (knowledgeGraphInstance.d3Force('link')) {
      knowledgeGraphInstance.d3Force('link').distance(90);
    }
  } else {
    if (knowledgeGraphInstance.d3Force('charge')) {
      knowledgeGraphInstance.d3Force('charge').strength(-400);
    }
    if (knowledgeGraphInstance.d3Force('link')) {
      knowledgeGraphInstance.d3Force('link').distance(90);
    }
  }

  const searchInput = document.getElementById('graph-search');
  if (searchInput) {
    searchInput.addEventListener('input', e => {
      searchQuery = e.target.value.trim().toLowerCase();
    });
  }

  // Zero idle CPU: Initial pause animation
  knowledgeGraphInstance.pauseAnimation();
}

async function openGraphModal() {
  const modal = document.getElementById('graph-modal');
  if (!modal) return;
  modal.classList.remove('hidden');

  selectedNode = null;
  hoverNode = null;
  closeNoteDrawer();

  const container = document.getElementById('graph-viewport');
  const w = container ? (container.clientWidth || window.innerWidth) : window.innerWidth;
  const h = container ? (container.clientHeight || (window.innerHeight - 56)) : (window.innerHeight - 56);

  if (!knowledgeGraphInstance) {
    initForceGraph();
  }

  if (knowledgeGraphInstance) {
    knowledgeGraphInstance.width(w).height(h);
  }

  try {
    const resp = await fetch('/api/graph/global');
    if (resp.ok) {
      const data = await resp.json();
      const nodes = data.nodes || [];
      const edges = data.edges || [];
      const links = edges.map(e => ({
        source: e.source,
        target: e.target,
        relation: e.relation || 'prerequisite'
      }));

      graphDataCache = { nodes, links };
      rebuildAdjacencyMaps(nodes, links);

      const countEl = document.getElementById('graph-node-count');
      if (countEl) {
        countEl.innerText = `${nodes.length} concept${nodes.length === 1 ? '' : 's'}`;
      }

      if (knowledgeGraphInstance) {
        knowledgeGraphInstance.graphData(graphDataCache);
        knowledgeGraphInstance.resumeAnimation();

        // Auto-framing: 120ms timeout ensures D3 warmup ticks and layout have settled before framing
        setTimeout(() => {
          if (knowledgeGraphInstance && container) {
            knowledgeGraphInstance.width(container.clientWidth || w).height(container.clientHeight || h);
            knowledgeGraphInstance.zoomToFit(400, 60);
          }
        }, 120);
      }
    }
  } catch (err) {
    console.error('Failed to load global knowledge graph:', err);
  }
  setupGraphNavControls();
}

function closeGraphModal() {
  const modal = document.getElementById('graph-modal');
  if (!modal) return;
  modal.classList.add('hidden');
  selectedNode = null;
  hoverNode = null;
  closeNoteDrawer();
  const container = document.getElementById('graph-viewport');
  if (container) {
    container.style.cursor = 'default';
  }
  if (knowledgeGraphInstance) {
    knowledgeGraphInstance.pauseAnimation();
  }
}

// Floating HUD Navigation Handlers
function graphZoomIn() {
  if (!knowledgeGraphInstance) return;
  const currentZoom = knowledgeGraphInstance.zoom();
  knowledgeGraphInstance.zoom(currentZoom * 1.35, 300);
}

function graphZoomOut() {
  if (!knowledgeGraphInstance) return;
  const currentZoom = knowledgeGraphInstance.zoom();
  knowledgeGraphInstance.zoom(currentZoom / 1.35, 300);
}

function graphFitView() {
  if (!knowledgeGraphInstance) return;
  knowledgeGraphInstance.zoomToFit(400, 60);
}

function graphResetView() {
  if (!knowledgeGraphInstance) return;
  selectedNode = null;
  hoverNode = null;
  closeNoteDrawer();
  const searchInput = document.getElementById('graph-search');
  if (searchInput) {
    searchInput.value = '';
    searchQuery = '';
  }
  knowledgeGraphInstance.zoomToFit(400, 60);
  knowledgeGraphInstance.d3ReheatSimulation();
}

// Drag-to-Resize Implementation for Split-Pane
let isDraggingResizer = false;

function setupGraphResizer() {
  const resizer = document.getElementById('graph-resizer');
  const drawer = document.getElementById('graph-note-drawer');
  const viewportEl = document.getElementById('graph-viewport');
  if (!resizer || !drawer || !viewportEl) return;

  // Read initial saved width: localStorage.getItem('graph_drawer_width') || '50%'
  const savedWidth = localStorage.getItem('graph_drawer_width') || '50%';
  drawer.style.width = savedWidth;

  if (resizer.dataset.initialized === 'true') return;
  resizer.dataset.initialized = 'true';

  resizer.addEventListener('mousedown', (e) => {
    e.preventDefault();
    isDraggingResizer = true;
    resizer.classList.add('is-dragging');
    document.body.style.userSelect = 'none';

    // Temporarily set pointer-events: none on canvas to prevent intercepting mouse moves
    const canvas = viewportEl.querySelector('canvas');
    if (canvas) {
      canvas.style.pointerEvents = 'none';
    }
  });

  window.addEventListener('mousemove', (e) => {
    if (!isDraggingResizer) return;
    // Calculate new drawer width from the right edge
    const newWidth = window.innerWidth - e.clientX;
    const minW = 280;
    const maxW = Math.max(minW, window.innerWidth - 250);
    const clampedWidth = Math.min(Math.max(newWidth, minW), maxW);

    drawer.style.width = clampedWidth + 'px';

    // Synchronize the graph canvas dimensions live
    if (knowledgeGraphInstance && viewportEl) {
      knowledgeGraphInstance.width(viewportEl.clientWidth);
    }
  });

  window.addEventListener('mouseup', () => {
    if (isDraggingResizer) {
      isDraggingResizer = false;
      resizer.classList.remove('is-dragging');
      document.body.style.userSelect = '';

      const canvas = viewportEl.querySelector('canvas');
      if (canvas) {
        canvas.style.pointerEvents = '';
      }

      localStorage.setItem('graph_drawer_width', drawer.style.width);

      if (knowledgeGraphInstance && viewportEl) {
        knowledgeGraphInstance.width(viewportEl.clientWidth);
      }
    }
  });
}

function setupGraphNavControls() {
  const btnIn = document.getElementById('btn-graph-zoom-in');
  const btnOut = document.getElementById('btn-graph-zoom-out');
  const btnFit = document.getElementById('btn-graph-zoom-fit');
  const btnReset = document.getElementById('btn-graph-reset');
  const btnCloseDrawer = document.getElementById('btn-close-drawer');

  if (btnIn) {
    btnIn.onclick = () => {
      if (!knowledgeGraphInstance) return;
      knowledgeGraphInstance.zoom(knowledgeGraphInstance.zoom() * 1.35, 300);
    };
  }
  if (btnOut) {
    btnOut.onclick = () => {
      if (!knowledgeGraphInstance) return;
      knowledgeGraphInstance.zoom(knowledgeGraphInstance.zoom() / 1.35, 300);
    };
  }
  if (btnFit) {
    btnFit.onclick = () => {
      if (!knowledgeGraphInstance) return;
      knowledgeGraphInstance.zoomToFit(400, 60);
    };
  }
  if (btnReset) {
    btnReset.onclick = graphResetView;
  }
  if (btnCloseDrawer) {
    btnCloseDrawer.onclick = () => {
      closeNoteDrawer();
      selectedNode = null;
    };
  }
  setupGraphResizer();
}

document.addEventListener('keydown', e => {
  if (e.key === 'Escape') {
    const diagramModal = document.getElementById('diagram-modal');
    if (diagramModal && !diagramModal.classList.contains('hidden')) {
      closeDiagramModal();
      return;
    }
    const guideModal = document.getElementById('guide-modal');
    if (guideModal && !guideModal.classList.contains('hidden')) {
      closeGuideModal();
      return;
    }
    const modal = document.getElementById('graph-modal');
    if (modal && !modal.classList.contains('hidden')) {
      const drawer = document.getElementById('graph-note-drawer');
      const isDrawerOpen = drawer && !drawer.classList.contains('hidden');
      if (isDrawerOpen) {
        closeNoteDrawer();
        selectedNode = null;
      } else if (selectedNode !== null) {
        selectedNode = null;
      } else {
        closeGraphModal();
      }
    }
  }
});

window.addEventListener('resize', () => {
  const modal = document.getElementById('graph-modal');
  if (modal && !modal.classList.contains('hidden') && knowledgeGraphInstance) {
    const container = document.getElementById('graph-viewport');
    if (container) {
      knowledgeGraphInstance.width(container.clientWidth).height(container.clientHeight);
    }
  }
});
