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
let isInitialPollComplete = false;
let isAwaitingAgent = false;

let currentRoadmapMode = null; // 'standby' | 'active'
let currentNotesMode = null;   // 'standby' | 'active'

function isSessionStandby(state) {
  if (!state) return true;
  return !state.topic || state.topic === "Not Set" || state.status === "standby" || state.status === "idle";
}

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
  const isStandby = isSessionStandby(cachedState);
  if (!isStandby && cachedState.dag_mermaid) {
    renderMermaidDAG(cachedState.dag_mermaid);
  }
  const lessonContainer = document.getElementById('lesson-content');
  if (lessonContainer && !isStandby) {
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

  if (topicEl) topicEl.textContent = state.topic || 'Not Set';
  if (phaseEl) phaseEl.textContent = state.phase || 'idle';

  const phase = (state.phase || 'idle').toLowerCase();
  if (phaseDotEl && phaseEl) {
    if (phase === 'probing') {
      phaseDotEl.className = 'w-2 h-2 rounded-full bg-amber-400';
      phaseEl.className = 'uppercase font-semibold tracking-wider text-amber-400 font-mono';
    } else if (phase === 'teaching') {
      phaseDotEl.className = 'w-2 h-2 rounded-full bg-sky-400';
      phaseEl.className = 'uppercase font-semibold tracking-wider text-sky-400 font-mono';
    } else if (phase === 'evaluating') {
      phaseDotEl.className = 'w-2 h-2 rounded-full bg-emerald-400';
      phaseEl.className = 'uppercase font-semibold tracking-wider text-emerald-400 font-mono';
    } else if (phase === 'paused') {
      phaseDotEl.className = 'w-2 h-2 rounded-full bg-amber-400';
      phaseEl.className = 'uppercase font-semibold tracking-wider text-amber-400 font-mono';
    } else {
      phaseDotEl.className = 'w-2 h-2 rounded-full bg-zinc-600';
      phaseEl.className = 'uppercase font-semibold tracking-wider text-zinc-500 font-mono';
    }
  }
}

// Roadmap D3 Pan/Zoom Persistence State
let roadmapZoomBehavior = null;
let currentRoadmapTransform = null;
let roadmapDragStartPos = null;

function resetRoadmapZoom() {
  const container = document.getElementById('dag-container');
  if (!container || !roadmapZoomBehavior) return;
  const svg = d3.select(container).select('svg');
  if (svg.empty()) return;

  const scrollArea = document.getElementById('dag-scroll-area');
  const width = (scrollArea && scrollArea.clientWidth) || container.clientWidth || 400;
  const height = (scrollArea && scrollArea.clientHeight) || container.clientHeight || 500;

  const g = svg.select('g');
  if (g.empty()) return;
  const bbox = g.node().getBBox();
  if (!bbox || bbox.width === 0 || bbox.height === 0) return;

  const padding = 40;
  const scale = Math.max(0.4, Math.min(1.15, Math.min((width - padding) / bbox.width, (height - padding) / bbox.height)));
  const tx = (width - bbox.width * scale) / 2 - bbox.x * scale;
  const ty = Math.max(20, (height - bbox.height * scale) / 2 - bbox.y * scale);

  const initialTransform = d3.zoomIdentity.translate(tx, ty).scale(scale);
  currentRoadmapTransform = initialTransform;
  svg.transition().duration(300).call(roadmapZoomBehavior.transform, initialTransform);
}

function zoomRoadmapBy(factor) {
  const container = document.getElementById('dag-container');
  if (!container || !roadmapZoomBehavior) return;
  const svg = d3.select(container).select('svg');
  if (svg.empty()) return;
  svg.transition().duration(200).call(roadmapZoomBehavior.scaleBy, factor);
}

function setupRoadmapHUDControls() {
  const btnIn = document.getElementById('btn-dag-zoom-in');
  const btnOut = document.getElementById('btn-dag-zoom-out');
  const btnReset = document.getElementById('btn-dag-reset');

  if (btnIn && !btnIn.dataset.bound) {
    btnIn.dataset.bound = 'true';
    btnIn.addEventListener('click', () => zoomRoadmapBy(1.3));
  }
  if (btnOut && !btnOut.dataset.bound) {
    btnOut.dataset.bound = 'true';
    btnOut.addEventListener('click', () => zoomRoadmapBy(1 / 1.3));
  }
  if (btnReset && !btnReset.dataset.bound) {
    btnReset.dataset.bound = 'true';
    btnReset.addEventListener('click', () => resetRoadmapZoom());
  }
}

const ROADMAP_STANDBY_HTML = '<div class="h-full flex flex-col items-center justify-center p-4 text-center select-none opacity-60"><div class="w-8 h-8 mb-2 rounded border border-slate-800 bg-slate-900/40 flex items-center justify-center text-slate-500"><svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M9 20l-5.447-2.724A1 1 0 013 16.382V5.618a1 1 0 011.447-.894L9 7m0 13l6-3m-6 3V7m6 10l4.553 2.276A1 1 0 0021 18.382V7.618a1 1 0 00-.553-.894L15 4m0 13V4m0 0L9 7"/></svg></div><span class="text-[11px] font-mono text-slate-400">DAG Roadmap Inactive</span><span class="text-[10px] text-slate-600 mt-0.5">Select a topic or run .teach to compile graph</span></div>';

function renderRoadmapStandby() {
  const container = document.getElementById('dag-container');
  if (!container) return;
  setupRoadmapHUDControls();
  currentRoadmapMode = 'standby';
  container.innerHTML = ROADMAP_STANDBY_HTML;
}

// Helper: Render Mermaid DAG / Roadmap with D3 Zoom & Persistent Camera
async function renderRoadmap(code) {
  const container = document.getElementById('dag-container');
  if (!container) return;

  setupRoadmapHUDControls();

  const isStandby = isSessionStandby(cachedState);
  const mermaidCode = code || '';
  const isRoadmapEmpty = isStandby || !mermaidCode || !mermaidCode.trim() || mermaidCode.trim().split('\n').filter(l => {
    const s = l.trim();
    return s && !s.startsWith('classDef') && !s.startsWith('graph') && s !== 'graph TD';
  }).length === 0;

  if (isStandby || isRoadmapEmpty) {
    if (currentRoadmapMode !== 'standby' || !container.querySelector('.font-mono')) {
      renderRoadmapStandby();
    }
    return;
  }

  currentRoadmapMode = 'active';

  const cleanCode = sanitizeMermaidCode(mermaidCode);
  if (!cleanCode) {
    return;
  }

  // Check if it contains a valid graph directive matching /^\s*(graph|flowchart)\s+(TD|TB|LR|RL)/im
  const validDirective = /^\s*(graph|flowchart)\s+(TD|TB|LR|RL)/im.test(cleanCode);
  if (!validDirective) {
    return;
  }

  if (!window.mermaid || !mermaidReady) {
    return; // Will retry when mermaid is ready
  }

  const id = "mermaid-dag-" + Date.now();
  try {
    const { svg: svgHtml } = await window.mermaid.render(id, cleanCode);
    container.innerHTML = svgHtml;

    // Attach D3 Zoom to the rendered SVG
    if (typeof d3 !== 'undefined') {
      const svg = d3.select(container).select('svg');
      if (!svg.empty()) {
        svg.attr('width', '100%').attr('height', '100%').style('max-width', 'none');
        const g = svg.select('g');
        if (!g.empty()) {
          roadmapZoomBehavior = d3.zoom()
            .scaleExtent([0.4, 3.0])
            .on('zoom', (event) => {
              currentRoadmapTransform = event.transform;
              g.attr('transform', event.transform);
            });

          svg.call(roadmapZoomBehavior);
          svg.on('dblclick.zoom', () => resetRoadmapZoom());

          // Persist the roadmap's zoom transform across state re-renders so SVG updates don't reset the camera position
          if (currentRoadmapTransform) {
            svg.call(roadmapZoomBehavior.transform, currentRoadmapTransform);
          } else {
            resetRoadmapZoom();
          }
        }
      }
    }
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
window.resetRoadmapZoom = resetRoadmapZoom;
window.zoomRoadmapBy = zoomRoadmapBy;

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

// Global Click-to-Copy Helper for Standby Cheat Sheet
window.copyToClipboard = function(text, el) {
  const doFeedback = () => {
    if (el) {
      const feedback = el.querySelector('.copy-hint');
      if (feedback) {
        const orig = feedback.textContent;
        feedback.textContent = 'COPIED';
        feedback.classList.add('text-emerald-400');
        setTimeout(() => {
          feedback.textContent = orig;
          feedback.classList.remove('text-emerald-400');
        }, 1400);
      }
    }
  };

  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(text).then(doFeedback).catch(() => {
      try {
        const ta = document.createElement('textarea');
        ta.value = text;
        document.body.appendChild(ta);
        ta.select();
        document.execCommand('copy');
        document.body.removeChild(ta);
        doFeedback();
      } catch (e) {}
    });
  } else {
    try {
      const ta = document.createElement('textarea');
      ta.value = text;
      document.body.appendChild(ta);
      ta.select();
      document.execCommand('copy');
      document.body.removeChild(ta);
      doFeedback();
    } catch (e) {}
  }
};

function renderNotesStandby() {
  const container = document.getElementById('lesson-content');
  if (!container) return;
  const notesPanel = document.getElementById('notes-panel');
  const panelNotes = document.getElementById('panel-notes');
  if (notesPanel) notesPanel.style.overflowY = 'hidden';
  if (panelNotes) panelNotes.style.overflowY = 'hidden';
  container.style.overflowY = 'hidden';

  currentNotesMode = 'standby';
  container.innerHTML = `
        <div class="h-full flex flex-col justify-center max-w-xl mx-auto px-6 py-3 text-slate-400 select-text overflow-hidden">
          <!-- Minimalist Header -->
          <div class="mb-3 pb-2 border-b border-white/[0.06]">
            <div class="flex items-center gap-2 text-xs font-mono tracking-wider text-slate-300 uppercase">
              <span class="w-1.5 h-1.5 rounded-full bg-slate-500"></span>
              <span>Workspace Standby</span>
              <span class="text-slate-600">/</span>
              <span class="text-slate-500 text-[11px] lowercase">command reference</span>
            </div>
            <p class="text-[12px] text-slate-500 mt-1 font-sans">Click any command to copy it directly to your clipboard.</p>
          </div>

          <div class="space-y-3.5 font-mono text-xs">
            <!-- Core Learning -->
            <div>
              <div class="text-[10px] tracking-widest uppercase text-slate-500 mb-2">// Core Learning</div>
              <div class="space-y-1">
                <div onclick="copyToClipboard('.teach <topic>', this)" class="group flex items-center justify-between py-1.5 px-2 rounded hover:bg-white/[0.04] transition-colors cursor-pointer border border-transparent hover:border-white/[0.05]">
                  <span class="text-slate-200 group-hover:text-purple-300 transition-colors">.teach &lt;topic&gt;</span>
                  <div class="flex items-center gap-3">
                    <span class="text-[11px] text-slate-500 font-sans">Diagnose & generate DAG</span>
                    <span class="copy-hint text-[9px] text-slate-600 group-hover:text-slate-400 font-mono">COPY</span>
                  </div>
                </div>

                <div onclick="copyToClipboard('.teach <topic> --ref <scope>', this)" class="group flex items-center justify-between py-1.5 px-2 rounded hover:bg-white/[0.04] transition-colors cursor-pointer border border-transparent hover:border-white/[0.05]">
                  <span class="text-slate-200 group-hover:text-purple-300 transition-colors">.teach &lt;topic&gt; --ref &lt;scope&gt;</span>
                  <div class="flex items-center gap-3">
                    <span class="text-[11px] text-slate-500 font-sans">Scope material reference</span>
                    <span class="copy-hint text-[9px] text-slate-600 group-hover:text-slate-400 font-mono">COPY</span>
                  </div>
                </div>

                <div onclick="copyToClipboard('.teach <topic> --domain <name>', this)" class="group flex items-center justify-between py-1.5 px-2 rounded hover:bg-white/[0.04] transition-colors cursor-pointer border border-transparent hover:border-white/[0.05]">
                  <span class="text-slate-200 group-hover:text-purple-300 transition-colors">.teach &lt;topic&gt; --domain &lt;name&gt;</span>
                  <div class="flex items-center gap-3">
                    <span class="text-[11px] text-slate-500 font-sans">Explicit subject domain</span>
                    <span class="copy-hint text-[9px] text-slate-600 group-hover:text-slate-400 font-mono">COPY</span>
                  </div>
                </div>

                <div onclick="copyToClipboard('.review <topic>', this)" class="group flex items-center justify-between py-1.5 px-2 rounded hover:bg-white/[0.04] transition-colors cursor-pointer border border-transparent hover:border-white/[0.05]">
                  <span class="text-slate-200 group-hover:text-purple-300 transition-colors">.review &lt;topic&gt;</span>
                  <div class="flex items-center gap-3">
                    <span class="text-[11px] text-slate-500 font-sans">Targeted retrieval quiz</span>
                    <span class="copy-hint text-[9px] text-slate-600 group-hover:text-slate-400 font-mono">COPY</span>
                  </div>
                </div>
              </div>
            </div>

            <!-- Session Management -->
            <div>
              <div class="text-[10px] tracking-widest uppercase text-slate-500 mb-2">// Session Controls</div>
              <div class="space-y-1">
                <div onclick="copyToClipboard('.pause', this)" class="group flex items-center justify-between py-1.5 px-2 rounded hover:bg-white/[0.04] transition-colors cursor-pointer border border-transparent hover:border-white/[0.05]">
                  <span class="text-slate-300 group-hover:text-slate-100 transition-colors">.pause</span>
                  <div class="flex items-center gap-3">
                    <span class="text-[11px] text-slate-500 font-sans">Suspend active teaching loop</span>
                    <span class="copy-hint text-[9px] text-slate-600 group-hover:text-slate-400 font-mono">COPY</span>
                  </div>
                </div>

                <div onclick="copyToClipboard('.resume', this)" class="group flex items-center justify-between py-1.5 px-2 rounded hover:bg-white/[0.04] transition-colors cursor-pointer border border-transparent hover:border-white/[0.05]">
                  <span class="text-slate-300 group-hover:text-slate-100 transition-colors">.resume</span>
                  <div class="flex items-center gap-3">
                    <span class="text-[11px] text-slate-500 font-sans">Resume active lesson & quiz</span>
                    <span class="copy-hint text-[9px] text-slate-600 group-hover:text-slate-400 font-mono">COPY</span>
                  </div>
                </div>

                <div onclick="copyToClipboard('.archive', this)" class="group flex items-center justify-between py-1.5 px-2 rounded hover:bg-white/[0.04] transition-colors cursor-pointer border border-transparent hover:border-white/[0.05]">
                  <span class="text-slate-300 group-hover:text-slate-100 transition-colors">.archive</span>
                  <div class="flex items-center gap-3">
                    <span class="text-[11px] text-slate-500 font-sans">Save topic notes & graph to library</span>
                    <span class="copy-hint text-[9px] text-slate-600 group-hover:text-slate-400 font-mono">COPY</span>
                  </div>
                </div>

                <div onclick="copyToClipboard('.reset', this)" class="group flex items-center justify-between py-1.5 px-2 rounded hover:bg-white/[0.04] transition-colors cursor-pointer border border-transparent hover:border-white/[0.05]">
                  <span class="text-slate-400 group-hover:text-rose-300 transition-colors">.kill / .reset</span>
                  <div class="flex items-center gap-3">
                    <span class="text-[11px] text-slate-500 font-sans">Reset workspace to standby</span>
                    <span class="copy-hint text-[9px] text-slate-600 group-hover:text-slate-400 font-mono">COPY</span>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
  `;
}

// Helper: Render Lesson Markdown + Viewport Separation + KaTeX
function renderLesson(markdown, activeNodeId = null, activeNodeLabel = null) {
  const container = document.getElementById('lesson-content');
  if (!container) return;

  const isStandby = isSessionStandby(cachedState);
  const isNotesEmpty = isStandby || !markdown || !markdown.trim() || markdown.trim().startsWith('<!--');

  if (isStandby || isNotesEmpty) {
    if (currentNotesMode !== 'standby' || !container.querySelector('.tracking-widest')) {
      renderNotesStandby();
    }
    return;
  }

  currentNotesMode = 'active';
  const notesPanel = document.getElementById('notes-panel');
  const panelNotes = document.getElementById('panel-notes');
  if (notesPanel) notesPanel.style.overflowY = 'auto';
  if (panelNotes) panelNotes.style.overflowY = 'auto';
  container.style.overflowY = 'auto';

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
  if (panelNotes) {
    panelNotes.scrollTop = 0;
  }
}

// Backward-compatible alias
const updateLessonNotes = renderLesson;
window.renderLesson = renderLesson;
window.updateLessonNotes = updateLessonNotes;

// Helper: Render Active Quiz
function renderQuiz(quizData, latestAnswer) {
  const container = document.getElementById('quiz-container');
  const pill = document.getElementById('quiz-status-pill');

  if (isAwaitingAgent) {
    const newQuizSig = getQuizSignature(quizData);
    if (newQuizSig && newQuizSig === currentQuizSignature) {
      return;
    }
    isAwaitingAgent = false;
  }

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
      if (isInitialPollComplete) {
        container.innerHTML = `<div class="quiz-empty py-16 text-center text-slate-500 font-mono text-xs">Awaiting checkpoint assessment...</div>`;
      }
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

  let html = `<div class="space-y-4">`;
  html += `
    <div class="flex items-center justify-between text-xs font-mono text-zinc-400 pb-2 border-b border-[#27272a]">
      <span class="font-semibold text-zinc-200">[BATCH ASSESSMENT: ${questions.length} QUESTION${questions.length > 1 ? 'S' : ''}]</span>
      <span class="text-[11px] ${allAnswered ? 'text-emerald-400 font-semibold' : 'text-zinc-500'}">${answeredCount}/${questions.length} Selected</span>
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
      <div class="bg-[#131419] border border-[#27272a] rounded-md p-3.5 space-y-3">
        <div class="flex items-start gap-2.5">
          <span class="w-5 h-5 rounded bg-[#18181b] border border-[#27272a] text-zinc-300 flex items-center justify-center font-mono text-[10px] font-bold shrink-0 mt-0.5">Q${qIdx + 1}</span>
          <div class="text-xs font-semibold text-zinc-100 leading-snug">
            ${escapeHtml(questionText)}
          </div>
        </div>

        <div class="space-y-1.5 pt-1">
    `;

    options.forEach((opt, optIdx) => {
      let btnStyle = "w-full text-left p-2.5 rounded-md border text-xs font-medium transition-all flex items-start gap-2.5 ";
      const letter = String.fromCharCode(65 + optIdx);

      if (!isGraded) {
        if (optIdx === chosenIdx) {
          btnStyle += "bg-sky-950/30 border-sky-500 text-sky-100 ring-1 ring-sky-500/40 cursor-pointer";
        } else {
          btnStyle += "bg-[#16171b] border-[#27272a] text-zinc-300 hover:bg-[#1c1d22] hover:border-[#3f3f46] hover:text-white cursor-pointer";
        }
        html += `
          <button type="button" onclick="selectMultiOption(${qIdx}, ${optIdx})" class="${btnStyle}">
            <span class="w-4 h-4 rounded border ${optIdx === chosenIdx ? 'border-sky-400 bg-sky-500/20 text-sky-300' : 'border-[#27272a] bg-[#18181b] text-zinc-400'} flex items-center justify-center text-[9px] font-mono font-bold shrink-0 mt-0.5">${letter}</span>
            <span class="quiz-option-text flex-1">${escapeHtml(opt)}</span>
            ${optIdx === chosenIdx ? `<span class="w-1.5 h-1.5 rounded-full bg-sky-400 shrink-0 self-center"></span>` : ''}
          </button>
        `;
      } else {
        // Graded mode
        if (optIdx === chosenIdx) {
          if (optIdx === qCorrectIdx) {
            btnStyle += "bg-emerald-950/40 border-emerald-500 text-emerald-200 cursor-default";
          } else {
            btnStyle += "bg-rose-950/40 border-rose-500 text-rose-200 cursor-default";
          }
        } else if (optIdx === qCorrectIdx) {
          btnStyle += "bg-emerald-950/20 border-emerald-500/40 text-emerald-300/80 cursor-default";
        } else {
          btnStyle += "bg-[#121316] border-[#27272a] text-zinc-600 cursor-not-allowed opacity-50";
        }

        html += `
          <button type="button" disabled class="${btnStyle}">
            <span class="w-4 h-4 rounded border border-current flex items-center justify-center text-[9px] font-mono font-bold shrink-0 mt-0.5">${letter}</span>
            <span class="quiz-option-text flex-1">${escapeHtml(opt)}</span>
            ${optIdx === chosenIdx ? (optIdx === qCorrectIdx ? 
              `<svg class="w-3.5 h-3.5 text-emerald-400 shrink-0 ml-auto" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"></path></svg>` : 
              `<svg class="w-3.5 h-3.5 text-rose-400 shrink-0 ml-auto" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path></svg>`) : ''}
          </button>
        `;
      }
    });

    html += `</div>`;

    if (isGraded && q.explanation) {
      const isCorrect = (chosenIdx === qCorrectIdx);
      html += `
        <div class="mt-3 pt-2.5 border-t border-[#27272a]">
          <div class="p-3 rounded-md ${isCorrect ? 'bg-emerald-950/30 border border-emerald-500/30' : 'bg-rose-950/30 border border-rose-500/30'}">
            <div class="flex items-center gap-2 mb-1 font-mono">
              <span class="text-xs font-bold ${isCorrect ? 'text-emerald-400' : 'text-rose-400'}">
                ${isCorrect ? '[CORRECT ASSESSMENT]' : '[INCORRECT ASSESSMENT]'}
              </span>
            </div>
            <div class="text-xs text-zinc-300 leading-relaxed">
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
      <div class="pt-1 flex items-center gap-2">
        <button id="btn-submit-assessment" type="button" ${allAnswered ? '' : 'disabled'} onclick="submitBatchAssessment()" class="flex-1 py-2.5 px-4 rounded-md font-mono text-xs font-semibold transition-all flex items-center justify-center gap-2 ${allAnswered ? 'bg-zinc-100 hover:bg-white text-zinc-950 cursor-pointer shadow-sm' : 'bg-[#18181b] border border-[#27272a] text-zinc-600 cursor-not-allowed opacity-60'}">
          <span>${allAnswered ? 'Submit Assessment' : `Select All Answers to Submit (${answeredCount}/${questions.length})`}</span>
        </button>
        <button type="button" onclick="pauseSession()" class="py-2.5 px-3 rounded-md font-mono text-xs font-medium text-zinc-400 hover:text-white bg-[#18181b] border border-[#27272a] hover:border-[#3f3f46] transition-all cursor-pointer shrink-0" title="Pause session">Pause</button>
      </div>
    `;
  } else {
    const isPassed = Boolean(latestAnswer.passed || latestAnswer.correct || (latestAnswer.score !== undefined && latestAnswer.score >= 0.70));
    const correctCount = latestAnswer.correct_count !== undefined ? latestAnswer.correct_count : (isPassed ? questions.length : 0);
    html += `
      <div class="pt-1 space-y-2.5 font-mono">
        <div class="p-3 rounded-md border text-center space-y-1 ${isPassed ? 'bg-emerald-950/30 border-emerald-500/40 text-emerald-200' : 'bg-rose-950/30 border-rose-500/40 text-rose-200'}">
          <div class="text-xs font-bold">${isPassed ? '[ASSESSMENT PASSED]' : '[ASSESSMENT FAILED]'}</div>
          <div class="text-[11px]">${correctCount} / ${questions.length} correct</div>
        </div>
        ${isPassed ? `
          <div class="text-center text-xs text-emerald-400 font-semibold py-1">
            [MASTERY VERIFIED - ADVANCING TO NEXT NODE]
          </div>
        ` : `
          <div class="text-center text-xs text-rose-400 font-semibold py-1">
            [AWAITING AGENT REMEDIATION]
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
      isAwaitingAgent = true;

      const quizContainer = document.getElementById('quiz-container');
      if (quizContainer) {
        quizContainer.innerHTML = `
          <div class="h-full flex flex-col items-center justify-center p-6 text-center select-none">
            <div class="w-10 h-10 mb-3 rounded-full border border-sky-800/80 bg-sky-950/40 flex items-center justify-center text-sky-400 animate-pulse">
              <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>
            </div>
            <h4 class="text-xs font-mono font-semibold text-slate-200 uppercase tracking-wider mb-1">Assessment Submitted</h4>
            <p class="text-[11px] text-slate-400 max-w-[240px] mb-3">Compiling lesson notes and updating roadmap...</p>
            <div class="p-2.5 rounded bg-slate-900/80 border border-slate-800 text-[11px] font-mono text-slate-400 max-w-xs">
              Return to your <span class="text-sky-300">Editor Chat</span>. Once generation finishes, reply <code class="text-emerald-400 bg-black/40 px-1 py-0.5 rounded">Ready</code> to proceed.
            </div>
          </div>
        `;
      }
      const pill = document.getElementById('quiz-status-pill');
      if (pill) {
        pill.textContent = 'Submitted';
        pill.className = 'text-[10px] font-mono px-2 py-0.5 rounded-full bg-sky-950/60 text-sky-300 border border-sky-500/30';
      }
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

const submitBatchQuiz = submitBatchAssessment;
const submitAnswer = submitSingleAssessment;

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
      currentNotesMode = null;
      renderLesson(activeMarkdown, cachedState.active_node_id, cachedState.active_node);
    } else {
      renderLesson('');
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

  container.addEventListener('pointerdown', (e) => {
    roadmapDragStartPos = { x: e.clientX, y: e.clientY };
  });

  container.addEventListener('click', (e) => {
    // Differentiate click from drag on roadmap nodes (movement threshold > 5px)
    if (roadmapDragStartPos) {
      const dist = Math.hypot(e.clientX - roadmapDragStartPos.x, e.clientY - roadmapDragStartPos.y);
      if (dist > 5) {
        return; // Suppress note navigation when dragging/panning
      }
    }

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
      renderRoadmapStandby();
      renderNotesStandby();
      renderQuiz(null, null);

      showToast("Workspace state reset to clean idle standby.");
    }
  } catch (err) {
    console.error('Failed to reset session:', err);
  }
}

// Reactive State Dispatcher
function updateUI(newState, force = false) {
  // Check the actual session state from /api/state:
  const isStandby = !newState.topic || newState.topic === "Not Set" || newState.status === "standby" || newState.status === "idle";

  const prevCachedState = cachedState;
  cachedState = newState;

  // Header update
  if (force || newState.topic !== prevCachedState.topic || newState.phase !== prevCachedState.phase) {
    updateHeader(newState);
  }

  const studyEl = document.getElementById('workspace-study');
  const idleEl = document.getElementById('workspace-idle');
  const badgeEl = document.getElementById('header-session-badge');

  // Update paused session card inside Idle Center
  updatePausedSessionCard(newState);

  if (isStandby) {
    if (badgeEl) {
      badgeEl.textContent = '[STANDBY]';
      badgeEl.className = 'text-[10px] uppercase font-mono font-semibold tracking-wider px-2 py-0.5 rounded bg-slate-800 text-slate-400 border border-slate-700/60';
    }

    if (!isStudyViewExplicitlyActive && studyEl && idleEl) {
      studyEl.classList.add('hidden');
      idleEl.classList.remove('hidden');
    }

    // Force currentRoadmapMode = 'standby' and render the minimal roadmap placeholder (do not render stale roadmap.mmd content)
    if (currentRoadmapMode !== 'standby' || force) {
      renderRoadmapStandby();
    }

    // Force currentNotesMode = 'standby' and render the command reference cheat sheet (do not render stale notes/lesson_notes.md content)
    if (currentNotesMode !== 'standby' || force) {
      renderNotesStandby();
    }

    // Ensure the assessment column displays the idle awaiting state
    renderQuiz(null, null);

    return;
  }

  // Automatic Real-Time Transition when isStandby is FALSE and a real topic is actively mounted:
  if (studyEl && idleEl) {
    if (studyEl.classList.contains('hidden')) {
      isStudyViewExplicitlyActive = true;
      idleEl.classList.add('hidden');
      studyEl.classList.remove('hidden');
      if (badgeEl) {
        badgeEl.textContent = '[ACTIVE]';
        badgeEl.className = 'text-[10px] uppercase font-mono font-semibold tracking-wider px-2 py-0.5 rounded bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 shadow-sm animate-pulse';
      }
    } else {
      if (badgeEl && badgeEl.textContent !== '[ACTIVE]') {
        badgeEl.textContent = '[ACTIVE]';
        badgeEl.className = 'text-[10px] uppercase font-mono font-semibold tracking-wider px-2 py-0.5 rounded bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 shadow-sm animate-pulse';
      }
    }
  }

  // Column 1: DAG Roadmap (Only render active roadmap nodes when isStandby is FALSE)
  if (force || currentRoadmapMode !== 'active' || newState.dag_mermaid !== prevCachedState.dag_mermaid) {
    renderMermaidDAG(newState.dag_mermaid);
  }

  // Column 2: Lesson Notes (Only render active lesson note markdown when isStandby is FALSE)
  if (!isReferenceMode) {
    const activeNodeChanged = (newState.active_node_id && newState.active_node_id !== prevCachedState.active_node_id) ||
                              (newState.active_node && newState.active_node !== prevCachedState.active_node);
    if (force || currentNotesMode !== 'active' || newState.lesson_markdown !== prevCachedState.lesson_markdown || activeNodeChanged) {
      cachedActiveNote = newState.lesson_markdown;
      renderLesson(newState.lesson_markdown, newState.active_node_id, newState.active_node);
    }
  }

  // Column 3: Quiz
  const oldQuizSig = getQuizSignature(prevCachedState.active_quiz);
  const newQuizSig = getQuizSignature(newState.active_quiz);
  const quizSignatureChanged = oldQuizSig !== newQuizSig;
  const quizChanged = JSON.stringify(newState.active_quiz) !== JSON.stringify(prevCachedState.active_quiz);
  const answerChanged = JSON.stringify(newState.latest_answer) !== JSON.stringify(prevCachedState.latest_answer);
  if (force || quizChanged || answerChanged) {
    if (quizSignatureChanged) {
      isAwaitingAgent = false;
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
}

const renderState = updateUI;
window.renderState = updateUI;


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
      const wasFirstPoll = !isInitialPollComplete;
      if (wasFirstPoll) {
        isInitialPollComplete = true;
      }
      updateUI(state);
      // If this was the first poll and state was idle/empty, ensure empty placeholders render smoothly
      if (wasFirstPoll) {
        if (!state.dag_mermaid) {
          renderRoadmap('');
        }
        if (!state.notes && !state.lesson_markdown) {
          renderLesson('', null, null);
        }
        if (!state.quiz && !state.active_quiz) {
          const quizContainer = document.getElementById('quiz-container');
          if (quizContainer && (!quizContainer.hasChildNodes() || quizContainer.innerText.trim() === '')) {
            renderQuiz(null, null);
          }
        }
      }
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
  setupRoadmapHUDControls();
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
let topicAngleMap = new Map();
let coreRadius = 140;
let depthSpacing = 75;

let lineageNodeIds = new Set();
let lineageLinkSet = new Set();
const incomingPrereqMap = new Map(); // targetId -> Array of { sourceId, link }

function rebuildAdjacencyMaps(nodes, links) {
  neighborsMap.clear();
  linksMap.clear();
  incomingPrereqMap.clear();

  const degreeCounts = new Map();
  const inDegreeCounts = new Map();

  nodes.forEach(node => {
    neighborsMap.set(node.id, new Set());
    linksMap.set(node.id, new Set());
    incomingPrereqMap.set(node.id, []);
    degreeCounts.set(node.id, 0);
    inDegreeCounts.set(node.id, 0);
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

    if (!incomingPrereqMap.has(tgtId)) incomingPrereqMap.set(tgtId, []);
    incomingPrereqMap.get(tgtId).push({ sourceId: srcId, link });

    degreeCounts.set(srcId, (degreeCounts.get(srcId) || 0) + 1);
    degreeCounts.set(tgtId, (degreeCounts.get(tgtId) || 0) + 1);
    inDegreeCounts.set(tgtId, (inDegreeCounts.get(tgtId) || 0) + 1);
  });

  // 1. Compute Topological Prerequisite Depth within topics:
  // Roots: origin === "diagnostic" || badge_label === "Baseline Knowledge" || inDegree === 0
  const nodeMap = new Map();
  nodes.forEach(node => {
    nodeMap.set(node.id, node);
    const origin = String(node.origin || '').toLowerCase();
    const badge = String(node.badge_label || '').toLowerCase();
    const inDeg = inDegreeCounts.get(node.id) || 0;
    const isRoot = origin === 'diagnostic' || badge === 'baseline knowledge' || inDeg === 0;
    node.__isRoot = isRoot;
    node.__depth = isRoot ? 0 : null;
  });

  // Traverse downstream: child.depth = Math.max(child.depth, parent.depth + 1)
  let changed = true;
  let iterations = 0;
  while (changed && iterations < 50) {
    changed = false;
    iterations++;
    links.forEach(link => {
      const srcId = (typeof link.source === 'object' && link.source !== null) ? link.source.id : link.source;
      const tgtId = (typeof link.target === 'object' && link.target !== null) ? link.target.id : link.target;
      const srcNode = nodeMap.get(srcId);
      const tgtNode = nodeMap.get(tgtId);
      if (srcNode && tgtNode && srcNode.__depth !== null && srcNode.__depth !== undefined) {
        const candidateDepth = srcNode.__depth + 1;
        if (tgtNode.__depth === null || tgtNode.__depth === undefined || candidateDepth > tgtNode.__depth) {
          tgtNode.__depth = candidateDepth;
          changed = true;
        }
      }
    });
  }

  nodes.forEach(node => {
    if (node.__depth === null || node.__depth === undefined) {
      node.__depth = 0;
    }
    const inDeg = inDegreeCounts.get(node.id) || 0;
    const totalDeg = degreeCounts.get(node.id) || 0;
    node.__inDegree = inDeg;
    node.__outDegree = Math.max(0, totalDeg - inDeg);
    node.__degree = totalDeg;
    const degree = node.__inDegree + node.__outDegree;
    const baseR = node.__depth === 0 ? 5.5 : Math.max(2.8, Math.min(6.5, 2.8 + Math.sqrt(degree) * 1.1));
    node.__size = baseR;
  });
}

function updateLineageTracing(focus) {
  lineageNodeIds.clear();
  lineageLinkSet.clear();
  if (!focus) return;

  const focusId = typeof focus === 'object' ? focus.id : focus;
  lineageNodeIds.add(focusId);

  // Recursively collect all ancestor prerequisite nodes and links
  const queue = [focusId];
  const visited = new Set([focusId]);

  while (queue.length > 0) {
    const currId = queue.shift();
    const inPrereqs = incomingPrereqMap.get(currId) || [];
    inPrereqs.forEach(({ sourceId, link }) => {
      lineageNodeIds.add(sourceId);
      lineageLinkSet.add(link);
      if (!visited.has(sourceId)) {
        visited.add(sourceId);
        queue.push(sourceId);
      }
    });
  }
}

function isLineageLink(link) {
  if (lineageLinkSet.has(link)) return true;
  const srcId = (typeof link.source === 'object' && link.source !== null) ? link.source.id : link.source;
  const tgtId = (typeof link.target === 'object' && link.target !== null) ? link.target.id : link.target;
  return lineageNodeIds.has(srcId) && lineageNodeIds.has(tgtId);
}

function isFocusLink(focus, link) {
  if (!focus) return false;
  if (isLineageLink(link)) return true;
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

// Dynamic topic constellation islands
const topicCentersMap = new Map();

function computeTopicClusterCenters(nodes) {
  topicCentersMap.clear();
  const topicsSet = new Set();
  (nodes || []).forEach(n => {
    const ts = n.topics || [];
    if (Array.isArray(ts)) {
      ts.forEach(t => { if (t) topicsSet.add(t); });
    } else if (typeof ts === 'string' && ts) {
      topicsSet.add(ts);
    }
  });

  const topicsList = Array.from(topicsSet);
  const nTopics = topicsList.length;
  if (nTopics === 0) return;

  if (nTopics === 1) {
    topicCentersMap.set(topicsList[0], { x: 0, y: 0 });
  } else if (nTopics === 2) {
    topicCentersMap.set(topicsList[0], { x: -340, y: 0 });
    topicCentersMap.set(topicsList[1], { x: 340, y: 0 });
  } else {
    topicsList.forEach((topic, idx) => {
      const x = (idx - (nTopics - 1) / 2) * 640;
      topicCentersMap.set(topic, { x, y: 0 });
    });
  }
}

function getTopicCenterX(node) {
  if (!node) return 0;
  const ts = node.topics || [];
  const primaryTopic = Array.isArray(ts) ? ts[0] : ts;
  if (primaryTopic && topicCentersMap.has(primaryTopic)) {
    return topicCentersMap.get(primaryTopic).x;
  }
  return 0;
}

function getTopicCenterY(node) {
  if (!node) return 0;
  const ts = node.topics || [];
  const primaryTopic = Array.isArray(ts) ? ts[0] : ts;
  if (primaryTopic && topicCentersMap.has(primaryTopic)) {
    return topicCentersMap.get(primaryTopic).y;
  }
  return 0;
}

const topicHueMap = new Map();

function initForceGraph() {
  const container = document.getElementById('graph-viewport');
  if (!container || typeof ForceGraph === 'undefined') return;

  knowledgeGraphInstance = ForceGraph()(container)
    .backgroundColor('#09090b')
    .width(container.clientWidth || window.innerWidth)
    .height(container.clientHeight || (window.innerHeight - 56))
    .autoPauseRedraw(false)
    .cooldownTicks(90)
    .warmupTicks(60)
    .d3VelocityDecay(0.36)
    .enableZoomInteraction(true)
    .enablePanInteraction(true)
    .minZoom(0.1)
    .maxZoom(10)
    .linkCurvature(0)
    .linkDirectionalParticles(link => {
      const focus = hoverNode || selectedNode;
      if (!focus) return 0;
      if (isLineageLink(link)) return 3;
      return isFocusLink(focus, link) ? 2 : 0;
    })
    .linkDirectionalParticleWidth(link => {
      const focus = hoverNode || selectedNode;
      if (!focus) return 0;
      if (isLineageLink(link)) return 2.2;
      return isFocusLink(focus, link) ? 1.8 : 0;
    })
    .linkDirectionalParticleSpeed(0.006)
    .linkDirectionalParticleColor(() => '#38bdf8')
    .linkDirectionalArrowLength(0)
    .linkWidth(link => (hoverNode || selectedNode) && isLineageLink(link) ? 1.4 : 0.7)
    .linkColor(link => {
      const focus = hoverNode || selectedNode;
      if (focus) {
        if (isLineageLink(link)) return '#38bdf8';
        if (isFocusLink(focus, link)) return 'rgba(56, 189, 248, 0.6)';
        return 'rgba(255, 255, 255, 0.03)';
      }
      return 'rgba(148, 163, 184, 0.14)';
    })
    .nodeCanvasObject((node, ctx, globalScale) => {
      if (!Number.isFinite(node.x) || !Number.isFinite(node.y)) return;
      try {
        const focus = hoverNode || selectedNode;
        const isHovered = Boolean(hoverNode && (node === hoverNode || node.id === hoverNode.id));
        const isSelected = Boolean(selectedNode && (node === selectedNode || node.id === selectedNode.id));
        const isLineage = Boolean(focus && lineageNodeIds.has(node.id));
        const isNeighbor = Boolean(focus && neighborsMap.get(focus.id)?.has(node.id));
        const isConnected = isHovered || isSelected || isLineage || isNeighbor;

        node.__hovered = isHovered;
        node.__highlighted = isConnected;

        const degree = (node.__inDegree || 0) + (node.__outDegree || 0);
        const baseR = node.__depth === 0 ? 5.2 : Math.max(2.8, Math.min(6.2, 2.8 + Math.sqrt(degree) * 1.05));
        node.__size = baseR;

        const primaryTopic = (node.topics && node.topics[0]) || '';
        const hue = topicHueMap.get(primaryTopic) ?? 210;
        const isMastered = node.status === 'mastered';
        const isActive = node.status === 'active' || (window.activeConceptId === node.id);
        const isFocus = focus && (node === focus || lineageNodeIds.has(node.id));

        let coreColor;
        let glowColor = 'transparent';
        let blur = 0;

        if (isActive) {
          // Active lesson: electric sky blue beacon
          coreColor = '#38bdf8';
          glowColor = 'rgba(56, 189, 248, 0.45)';
          blur = 14 / globalScale;
        } else if (isMastered) {
          // Mastered: Vibrant topic-colored neon star with luminous bloom
          coreColor = `hsl(${hue}, 85%, 62%)`;
          glowColor = `hsla(${hue}, 85%, 62%, 0.38)`;
          blur = 10 / globalScale;
        } else {
          // Planned: Subdued ambient topic dust (readable cluster, but unlit)
          coreColor = `hsl(${hue}, 28%, 38%)`;
          blur = 0;
        }

        if (isFocus) {
          coreColor = '#ffffff';
          glowColor = 'rgba(255, 255, 255, 0.5)';
          blur = 8 / globalScale;
        }

        // Alpha dimming when another node is hovered/focused
        const nodeAlpha = (focus && !isFocus) ? 0.18 : 1.0;

        ctx.save();
        ctx.globalAlpha = nodeAlpha;

        // Pass 1: Outer soft ambient aura for mastered / active nodes
        if (blur > 0) {
          ctx.beginPath();
          ctx.arc(node.x, node.y, baseR + (node.__depth === 0 ? 3.5 : 2.5) / globalScale, 0, 2 * Math.PI);
          ctx.fillStyle = glowColor;
          ctx.fill();
        }

        // Pass 2: Solid core with canvas bloom
        ctx.beginPath();
        ctx.arc(node.x, node.y, baseR, 0, 2 * Math.PI);
        ctx.fillStyle = coreColor;
        if (blur > 0) {
          ctx.shadowColor = coreColor;
          ctx.shadowBlur = blur;
        }
        ctx.fill();
        ctx.restore();

        // Level of Detail: Show label text for active, focused, search match, or zoomed in (globalScale >= 2.0)
        const shouldDrawLabel = (focus && isFocus) || (isActive && !focus) || (globalScale >= 2.0) || Boolean(searchQuery && matchesSearch(node));

        if (shouldDrawLabel) {
          const label = String(node.label || node.id || '');
          if (label) {
            const fontSize = 10 / globalScale;
            ctx.save();
            ctx.globalAlpha = nodeAlpha;
            ctx.font = `${fontSize}px ui-monospace, SFMono-Regular, monospace`;
            ctx.textAlign = 'center';
            ctx.textBaseline = 'top';

            const textY = node.y + baseR + (3 / globalScale);
            const textColor = (isHovered || isSelected) ? '#f4f4f5' : (isFocus ? '#38bdf8' : (isActive ? '#38bdf8' : '#a1a1aa'));

            ctx.shadowColor = 'rgba(0, 0, 0, 0.95)';
            ctx.shadowBlur = 3 / globalScale;
            ctx.fillStyle = textColor;
            ctx.fillText(label, node.x, textY);
            ctx.restore();
          }
        }
      } catch (err) {
        console.error('Error in nodeCanvasObject:', err);
      }
    })
    .nodePointerAreaPaint((node, color, ctx) => {
      const r = (node.__size || 4) + 6;
      ctx.fillStyle = color;
      ctx.beginPath();
      ctx.arc(node.x, node.y, r, 0, 2 * Math.PI, false);
      ctx.fill();
    })
    .onRenderFramePost((ctx, globalScale) => {
      try {
        if (globalScale < 0.32) return;
        const headerAlpha = Math.min(0.65, Math.max(0.0, (globalScale - 0.32) * 2.5));

        const graphData = knowledgeGraphInstance ? knowledgeGraphInstance.graphData() : graphDataCache;
        if (!graphData) return;

        const topicClusters = new Map();
        (graphData.nodes || []).forEach(node => {
          const topic = (node.topics && node.topics[0]) || '';
          if (!topic || Number.isNaN(node.x) || Number.isNaN(node.y)) return;
          if (!topicClusters.has(topic)) topicClusters.set(topic, []);
          topicClusters.get(topic).push(node);
        });

        topicClusters.forEach((clusterNodes, topic) => {
          if (!clusterNodes.length) return;
          const avgX = clusterNodes.reduce((acc, n) => acc + n.x, 0) / clusterNodes.length;
          const minY = Math.min(...clusterNodes.map(n => n.y));

          ctx.save();
          const fontSize = Math.max(12, Math.min(22, 15 / globalScale));
          ctx.font = `600 ${fontSize}px "JetBrains Mono", monospace`;
          ctx.fillStyle = `rgba(148, 163, 184, ${headerAlpha})`;
          ctx.textAlign = 'center';
          ctx.textBaseline = 'bottom';
          ctx.fillText(`// ${topic.toUpperCase()}`, avgX, minY - (26 / globalScale));
          ctx.restore();
        });
      } catch (err) {
        console.error('Error rendering topic headers:', err);
      }
    })
    .onNodeHover(node => {
      try {
        const container = document.getElementById('graph-viewport');
        hoverNode = node || null;
        updateLineageTracing(hoverNode || selectedNode);
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
          updateLineageTracing(hoverNode);
          closeNoteDrawer();
        } else {
          selectedNode = node;
          hoverNode = null;
          updateLineageTracing(selectedNode);
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
        updateLineageTracing(null);
        closeNoteDrawer();
      } catch (err) {
        console.error('Error in onBackgroundClick:', err);
      }
    })
    .onNodeDrag((node, translate) => {
      // Intentionally do NOT call d3ReheatSimulation() on continuous drag to prevent velocity explosion / NaN crash
    })
    .onNodeDragEnd(node => {
      if (knowledgeGraphInstance) {
        knowledgeGraphInstance.d3AlphaTarget(0);
      }
    });

  // Obsidian D3 Physics Simulation Tuning (Fan-out Sector Physics)
  if (typeof d3 !== 'undefined') {
    knowledgeGraphInstance
      .cooldownTicks(90)
      .warmupTicks(60)
      .d3VelocityDecay(0.36)
      .d3Force('charge', d3.forceManyBody().strength(-280).distanceMax(550))
      .d3Force('collide', d3.forceCollide().radius(d => (d.__size || 4) + 20).iterations(3))
      .d3Force('radial', null)
      .d3Force('topicRayX', d3.forceX(d => {
        const t = (d.topics && d.topics[0]) || '';
        const ang = topicAngleMap.get(t) ?? 0;
        const r = coreRadius + (d.__depth || 0) * depthSpacing;
        return r * Math.cos(ang);
      }).strength(0.08))
      .d3Force('topicRayY', d3.forceY(d => {
        const t = (d.topics && d.topics[0]) || '';
        const ang = topicAngleMap.get(t) ?? 0;
        const r = coreRadius + (d.__depth || 0) * depthSpacing;
        return r * Math.sin(ang);
      }).strength(0.06));

    if (knowledgeGraphInstance.d3Force('link')) {
      knowledgeGraphInstance.d3Force('link')
        .distance(link => {
          const d1 = (link.source && link.source.__depth) || 0;
          const d2 = (link.target && link.target.__depth) || 0;
          return 50 + Math.abs(d1 - d2) * 18;
        })
        .strength(0.35);
    }
  } else {
    if (knowledgeGraphInstance.d3Force('charge')) {
      knowledgeGraphInstance.d3Force('charge').strength(-280);
    }
    if (knowledgeGraphInstance.d3Force('link')) {
      knowledgeGraphInstance.d3Force('link').distance(50);
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

      computeTopicClusterCenters(nodes);
      graphDataCache = { nodes, links };
      rebuildAdjacencyMaps(nodes, links);

      // Topic Baseline Separation Across Open Central Void
      const topicsList = Array.from(new Set(nodes.flatMap(n => n.topics || []).filter(Boolean)));
      const nTopics = Math.max(1, topicsList.length);
      // Expand central void dynamically as topics grow so baselines never crowd
      coreRadius = Math.max(140, 48 * Math.sqrt(nTopics));
      depthSpacing = Math.max(50, 75 - Math.min(25, nTopics * 0.4));

      topicAngleMap.clear();
      topicCentersMap.clear();
      topicsList.forEach((t, i) => {
        const ang = (2 * Math.PI * i) / nTopics + Math.PI;
        topicAngleMap.set(t, ang);
        topicCentersMap.set(t, { x: coreRadius * Math.cos(ang), y: coreRadius * Math.sin(ang) });
      });

      // Build topicHueMap once inside openGraphModal() based on topicsList:
      topicHueMap.clear();
      topicsList.forEach((topic, idx) => {
        // 137.508 degrees is the golden angle; guarantees maximum hue separation
        const hue = (idx * 137.508 + 210) % 360;
        topicHueMap.set(topic, hue);
      });

      if (knowledgeGraphInstance) {
        knowledgeGraphInstance.d3Force('radial', null);
      }

      // Pre-position nodes so topic baselines are spaced across a central void:
      nodes.forEach(node => {
        delete node.fx;
        delete node.fy;
        const depth = node.__depth || 0;
        const primaryTopic = (node.topics && node.topics[0]) || '';
        const angle = topicAngleMap.get(primaryTopic) ?? 0;
        const radius = coreRadius + depth * depthSpacing;
        const spread = (Math.random() - 0.5) * (Math.PI / nTopics) * 0.5;
        node.x = radius * Math.cos(angle + spread);
        node.y = radius * Math.sin(angle + spread);
      });

      nodes.forEach(node => {
        if (typeof node.x !== 'number' || isNaN(node.x)) {
          node.x = 0;
          node.y = 0;
        }
      });

      const countEl = document.getElementById('graph-node-count');
      if (countEl) {
        countEl.innerText = `${nodes.length} concept${nodes.length === 1 ? '' : 's'}`;
      }

      if (knowledgeGraphInstance) {
        knowledgeGraphInstance.graphData(graphDataCache);
        knowledgeGraphInstance.resumeAnimation();
        setTimeout(() => {
          if (knowledgeGraphInstance && container) {
            knowledgeGraphInstance.width(container.clientWidth || w).height(container.clientHeight || h);
            knowledgeGraphInstance.zoomToFit(300, 60);
          }
        }, 60);
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
  knowledgeGraphInstance.zoomToFit(400, 50);
}

function graphResetView() {
  if (!knowledgeGraphInstance) return;
  selectedNode = null;
  hoverNode = null;
  updateLineageTracing(null);
  closeNoteDrawer();
  const searchInput = document.getElementById('graph-search');
  if (searchInput) {
    searchInput.value = '';
    searchQuery = '';
  }
  knowledgeGraphInstance.zoomToFit(400, 50);
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
