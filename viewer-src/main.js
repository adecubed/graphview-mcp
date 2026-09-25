import { api, download, request } from './api.js';
import { createScene } from './scene.js';
import { createState } from './state.js';
import {
  onAnswerToggle, onBack, onColorMode, onDimensions, onExport, onFit, onGroupsToggle, onQuestion, renderAnswer,
  renderCoverage, renderDetail, renderGroups, renderIslands, renderTimeline, renderFilters, renderResults, renderStatus,
} from './panels.js';

const MAX_MISSING_TO_FETCH = 10;

let colors = { node_types: {}, edge_types: {}, sources: {} };
let meta = {};

const scene = createScene(document.getElementById('graph'), {
  onNodeClick: (node) => focusNode(node.id),
  onBackgroundClick: () => goBack(),
  onLeave: () => machine.reset(),
});

/** Give up a path that is waiting for its other end. True if there was one. */
function cancelPath() {
  if (!pathOrigin) return false;
  pathOrigin = null;
  document.getElementById('notice').textContent = '';
  return true;
}

/** Home: drop any selection and show the whole graph. */
function goHome() {
  cancelPath();
  machine.reset();
  document.getElementById('question').value = '';
  scene.frameAll();
}

/** One step back, and the camera follows: to the matches, or to the whole graph. */
function goBack() {
  if (cancelPath()) return;
  if (machine.current.name === 'idle') return;
  machine.back();
  if (machine.current.name === 'results') scene.frame(machine.current.matches);
  else scene.frameAll();
}

// What's in here: the groups the memory declares, and the one lit up right now.
let groups = [];
let activeGroup = null;

const machine = createState((state) => {
  scene.setHighlight(state.highlight);
  scene.slow(state.name === 'searching');
  renderStatus(state.name, scene.counts(), meta);
  if (state.name !== 'focus') renderDetail(null);
  // An open node needs the room: the groups fold to their title until it closes.
  document.getElementById('whats-here').classList.toggle('collapsed', state.name === 'focus');
  if (state.name === 'idle') {
    renderResults(null);
    renderAnswer(null);
    if (activeGroup) { activeGroup = null; renderGroups(groups, showGroup); }
  }
});

function showGroup(group) {
  if (activeGroup === group.name) return goHome();
  const ids = group.ids.filter((id) => scene.has(id));
  activeGroup = group.name;
  renderGroups(groups, showGroup, group.name);
  machine.results(ids, [], true);
  const missing = group.count - ids.length;
  renderAnswer({ mode: 'group', answer: `${group.name}: ${ids.length} in the graph${missing ? `, ${missing} not loaded` : ''}` });
  renderResults(scene.pick(ids), colors, focusNode);
  setTimeout(() => scene.frame(ids), 80);
}

function fail(error) {
  document.getElementById('notice').textContent = error.message;
}

// "Path from here": the node it starts from, until the other end is picked.
let pathOrigin = null;

function startPath(node) {
  pathOrigin = { id: node.id, label: node.label };
  fail(new Error(`path from ${node.label}: click another node, or search and pick one (Esc cancels)`));
}

async function showPath(origin, id) {
  pathOrigin = null;
  fail(new Error(''));
  const found = await api('path', { from: origin.id, to: id });
  if (!found.found) return fail(new Error(`no path between ${origin.label} and that node`));
  scene.add({ nodes: found.nodes, links: found.links.map((l) => ({ ...l, props: {} })) });
  const ids = found.nodes.map((n) => n.id);
  machine.results(ids, [], true);
  renderAnswer({ mode: 'path', answer: `${found.nodes.map((n) => n.label).join('  →  ')}\n${found.steps} step${found.steps === 1 ? '' : 's'}` });
  renderResults(found.nodes, colors, focusNode);
  setTimeout(() => scene.frame(ids), 80);
}

/** Bring a node into the scene if sampling left it out. */
async function ensureLoaded(id) {
  if (scene.has(id)) return;
  scene.add(await api('neighbors', { id, depth: 1, limit: 200 }));
}

async function focusNode(id) {
  try {
    if (pathOrigin && pathOrigin.id !== id) return await showPath(pathOrigin, id);
    const wasLoaded = scene.has(id);
    await ensureLoaded(id);
    const detail = await api('node', { id });
    if (detail.error) throw new Error(detail.error);
    machine.focus(id, scene.neighborIds(id));
    renderDetail(detail, colors, focusNode, startPath, (id, prop) => api('lookup', { id, prop }));
    // A node that was just added has no position until the layout ticks.
    setTimeout(() => scene.flyTo(id), wasLoaded ? 50 : 600);
  } catch (error) {
    fail(error);
  }
}

async function ask(question) {
  if (!question) return goBack();
  machine.searching();
  try {
    const result = await api('search', { q: question, limit: 50 });
    const { matches } = result;
    const missing = matches.filter((m) => !m.unlinked && !scene.has(m.id)).slice(0, MAX_MISSING_TO_FETCH);
    for (const node of missing) await ensureLoaded(node.id);
    const visible = matches.filter((m) => scene.has(m.id));
    // A recall finds facts; what they are about is one link away, so light that up too.
    const around = result.mode === 'recall' ? visible.flatMap((m) => scene.neighborIds(m.id)) : [];
    machine.results(visible.map((m) => m.id), around, true);
    renderAnswer(result);
    // Hits the graph does not hold are still part of the answer: listed, not clickable.
    renderResults(matches.filter((m) => m.unlinked || scene.has(m.id)), colors, focusNode);
    if (result.notice) fail(new Error(result.notice));
    if (visible.length) setTimeout(() => scene.frame(visible.map((m) => m.id)), missing.length ? 600 : 50);
  } catch (error) {
    machine.back();
    fail(error);
  }
}

async function start() {
  try {
    colors = await api('types');
    const graph = await api('graph');
    meta = graph.meta;
    scene.setColors(colors);
    scene.add(graph);
    renderFilters(colors, (hidden) => scene.setHidden(hidden));
    const coverage = await api('coverage');
    if (coverage.available) scene.setCoverage(coverage.hits);
    renderCoverage(coverage, (question) => {
      document.getElementById('question').value = question;
      ask(question);
    });
    onColorMode(scene.metrics(), (mode) => scene.setColorMode(mode));
    onAnswerToggle();
    onExport(async () => {
      const day = new Date().toISOString().slice(0, 10);
      await download('worklist', { format: 'md' }, `graphview-worklist-${day}.md`);
      // The export has just added today's line: say what moved since the one before.
      const { history } = await api('worklist/history');
      const now = history[history.length - 1];
      const before = history[history.length - 2];
      const signed = (n) => (n > 0 ? `+${n}` : String(n));
      const line = (name) => (before && before[name] !== undefined
        ? `${now[name]} ${name} (${signed(now[name] - before[name])})`
        : `${now[name]} ${name}`);
      const counts = ['duplicates', 'hubs', 'islands', 'unlinked']
        .filter((name) => now[name] !== undefined).map(line).join(', ');
      return before ? `${counts} since ${before.date}` : `${counts}. Export again later to see the trend.`;
    });
    renderTimeline(scene.births(), scene.counts().nodes, {
      onCutoff: (time) => scene.setCutoff(time),
      onPlaying: (on) => {
        if (on) goHome(); // a selection would hide most of what is about to appear
        scene.setAutoRotate(on);
      },
    });
    renderIslands(scene.islands(), (what, hide) => {
      if (what === 'rim') scene.setRimHidden(hide); else scene.setIslandsHidden(hide);
      if (machine.current.name === 'idle') scene.frameAll();
    });
    onQuestion(ask, goBack, goHome);
    onBack(goBack);
    onGroupsToggle();
    api('groups').then((found) => { groups = found.groups || []; renderGroups(groups, showGroup); })
      .catch(() => renderGroups([], showGroup));
    onFit(goHome);
    onDimensions((dim) => scene.setDimensions(dim));
    renderStatus('idle', scene.counts(), meta);
    setTimeout(() => machine.current.name === 'idle' && scene.frameAll(), 1500);
    // Give the layout a moment, so there are positions to fly to.
    if (request.query) {
      document.getElementById('question').value = request.query;
      setTimeout(() => ask(request.query), 1800);
    } else if (request.focus) {
      setTimeout(() => focusNode(request.focus), 1800);
    }
  } catch (error) {
    fail(error);
  }
}

start();
