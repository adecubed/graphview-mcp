import ForceGraph3D from '3d-force-graph';
import { forceX, forceY, forceZ } from 'd3-force-3d';
import SpriteText from 'three-spritetext';
import {
  AdditiveBlending, BufferGeometry, CanvasTexture, Group, LineBasicMaterial, LineLoop, MOUSE,
  Sprite, SpriteMaterial, Vector2, Vector3,
} from 'three';
import { UnrealBloomPass } from 'three/examples/jsm/postprocessing/UnrealBloomPass.js';

// The glow comes from the node sprites themselves (additive blending), so the
// bloom pass is optional: ?bloom=1 adds it. With bloom on, the background must
// be pure black, or it skips its colour-space conversion and comes out grey.
const WANT_BLOOM = new URLSearchParams(location.search).get('bloom') === '1';
// ?labels=0 shows no node names at all, neither on the nodes nor on hover: for
// recording a real memory without putting the names in it on screen.
const SHOW_LABELS = new URLSearchParams(location.search).get('labels') !== '0';
const BACKGROUND = WANT_BLOOM ? '#000000' : '#070b1c';
const BACKGROUND_RGB = [1, 3, 5].map((i) => parseInt(BACKGROUND.slice(i, i + 2), 16));
const DIM = 0.22; // how much of its colour a link keeps when it is not highlighted
const DIM_NODE_OPACITY = 0.16;
const FALLBACK = '#8aa0b5';
const ISLAND_MAX = 12; // a component this small, apart from the main one, is an island

const idOf = (end) => (typeof end === 'object' ? end.id : end);
const linkKey = (l) => `${idOf(l.source)}|${idOf(l.target)}|${l.type}`;

function dimmed(hex) {
  const rgb = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16));
  const mix = rgb.map((c, i) => Math.round(BACKGROUND_RGB[i] + (c - BACKGROUND_RGB[i]) * DIM));
  return `rgb(${mix.join(',')})`;
}

const escapeHtml = (text) => String(text).replace(/[&<>"']/g, (c) => (
  { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

/** One white texture for every node: soft halo, bright ring, solid core. Tinted per node. */
function makeNodeTexture() {
  const size = 256;
  const canvas = document.createElement('canvas');
  canvas.width = canvas.height = size;
  const ctx = canvas.getContext('2d');
  const c = size / 2;

  const halo = ctx.createRadialGradient(c, c, 0, c, c, c);
  halo.addColorStop(0, 'rgba(255,255,255,0.55)');
  halo.addColorStop(0.28, 'rgba(255,255,255,0.22)');
  halo.addColorStop(0.6, 'rgba(255,255,255,0.06)');
  halo.addColorStop(1, 'rgba(255,255,255,0)');
  ctx.fillStyle = halo;
  ctx.fillRect(0, 0, size, size);

  ctx.beginPath();
  ctx.arc(c, c, size * 0.2, 0, Math.PI * 2);
  ctx.lineWidth = size * 0.035;
  ctx.strokeStyle = 'rgba(255,255,255,0.95)';
  ctx.stroke();

  ctx.beginPath();
  ctx.arc(c, c, size * 0.085, 0, Math.PI * 2);
  ctx.fillStyle = 'rgba(255,255,255,1)';
  ctx.fill();

  return new CanvasTexture(canvas);
}

export function createScene(element, { onNodeClick, onBackgroundClick, onLeave }) {
  const data = { nodes: [], links: [] };
  const nodeIds = new Set();
  const linkKeys = new Set();
  const nodeTexture = makeNodeTexture();
  let colors = { node_types: {}, edge_types: {}, sources: {} };
  let colorMode = 'type';
  let hidden = { node_types: new Set(), edge_types: new Set(), sources: new Set() };
  let hideIslands = false;
  let hideRim = false;
  let islands = { count: 0, nodes: 0, rim: 0 };
  let highlight = new Set();
  let labelThreshold = Infinity;
  let dimensions = 3;
  let cutoff = null; // time-lapse: only nodes born by this moment are shown; null shows all

  // Colour by a measure instead of a category: any property most nodes carry as a
  // number or a date (confidence, times reinforced, last seen…), plus degree and
  // creation date. Values are ranked, not scaled, so one outlier cannot flatten
  // everything else into a single shade.
  const RAMP = ['#34307a', '#3b6fd4', '#2ec4b6', '#b5e48c', '#ffd166'];
  const NO_VALUE = '#3a4660';
  const ISO_DATE = /^\d{4}-\d{2}-\d{2}/;
  let metricRank = null; // node id -> 0..1, when a metric colours the graph
  let recallHits = null; // node id -> times retrieved, once a coverage pass has been loaded
  let recallTypes = null;

  const metricValue = (n, name) => {
    // A node no question reached counts as zero, not as missing: "never" is the finding.
    // Only for the kinds of node the search returns at all: a search that lists
    // facts says nothing about entities, so those stay grey rather than "never".
    if (name === 'recall_hits') {
      if (!recallHits) return undefined;
      if (!recallTypes) recallTypes = new Set(data.nodes.filter((m) => recallHits.has(m.id)).map((m) => m.type));
      return recallTypes.has(n.type) ? recallHits.get(n.id) || 0 : undefined;
    }
    const raw = name === 'degree' ? n.degree : name === 'created_at' ? n.created_at : n.props?.[name];
    if (typeof raw === 'number') return Number.isFinite(raw) ? raw : undefined;
    if (typeof raw === 'string' && ISO_DATE.test(raw)) {
      const time = Date.parse(raw);
      return Number.isFinite(time) ? time : undefined;
    }
    return undefined;
  };

  function ramp(t) {
    const at = Math.min(Math.max(t, 0), 1) * (RAMP.length - 1);
    const i = Math.min(Math.floor(at), RAMP.length - 2);
    const mix = (k) => {
      const a = parseInt(RAMP[i].slice(k, k + 2), 16);
      const b = parseInt(RAMP[i + 1].slice(k, k + 2), 16);
      return Math.round(a + (b - a) * (at - i)).toString(16).padStart(2, '0');
    };
    return `#${mix(1)}${mix(3)}${mix(5)}`;
  }

  function rankBy(name) {
    const valued = data.nodes.map((n) => [n.id, metricValue(n, name)]).filter(([, v]) => v !== undefined);
    valued.sort((a, b) => a[1] - b[1]);
    const ranks = new Map();
    valued.forEach(([id, value], i) => {
      // equal values share the rank of the first of them
      const first = i > 0 && valued[i - 1][1] === value ? ranks.get(valued[i - 1][0]) : i / Math.max(valued.length - 1, 1);
      ranks.set(id, first);
    });
    const isDate = valued.length && valued[0][1] > 1e11;
    const show = (v) => (isDate ? new Date(v).toISOString().slice(0, 10) : String(Math.round(v * 100) / 100));
    return { ranks, low: valued.length ? show(valued[0][1]) : '', high: valued.length ? show(valued[valued.length - 1][1]) : '' };
  }

  const nodeHex = (n) => {
    if (metricRank) return metricRank.has(n.id) ? ramp(metricRank.get(n.id)) : NO_VALUE;
    return (colorMode === 'source' ? colors.sources[n.source]?.color
      : colors.node_types[n.type]?.color) || FALLBACK;
  };
  const isLit = (n) => highlight.size === 0 || highlight.has(n.id);
  const linkLit = (l) => highlight.size === 0
    || (highlight.has(idOf(l.source)) && highlight.has(idOf(l.target)));
  // A node with no date has always been there, as far as the time-lapse can tell.
  const born = (n) => cutoff === null || n.born === undefined || n.born <= cutoff;
  const nodeShown = (n) => born(n) && !hidden.node_types.has(n.type) && !hidden.sources.has(n.source)
    && !(hideIslands && n.island && !highlight.has(n.id))
    && !(hideRim && n.rim && !highlight.has(n.id));
  // Close to uniform on purpose: size hints at importance, colour and position do the rest.
  let rimNodeSize = 8;
  const nodeSize = (n) => (n.rim && !highlight.has(n.id)
    ? rimNodeSize : 9 + Math.min(n.degree, 400) ** 0.5 * 1.5);

  function nodeObject(n) {
    const lit = isLit(n);
    const group = new Group();
    const glow = new Sprite(new SpriteMaterial({
      map: nodeTexture,
      color: nodeHex(n),
      transparent: true,
      opacity: !lit ? DIM_NODE_OPACITY : (n.rim && !highlight.has(n.id) ? 0.85 : 1),
      blending: AdditiveBlending,
      depthWrite: false,
    }));
    const size = lit ? nodeSize(n) : nodeSize(n) * 0.55;
    glow.scale.set(size, size, 1);
    group.add(glow);

    const wantsLabel = SHOW_LABELS
      && (highlight.size ? highlight.has(n.id) : n.degree >= labelThreshold);
    if (wantsLabel) {
      const label = new SpriteText(n.label.length > 28 ? `${n.label.slice(0, 27)}…` : n.label);
      label.color = '#dcecff';
      label.textHeight = highlight.size ? 4.6 : 3.6;
      label.backgroundColor = 'rgba(7,11,28,0.6)';
      label.padding = 1;
      label.position.y = size * 0.32 + 4;
      label.material.depthWrite = false;
      group.add(label);
    }
    return group;
  }

  const graph = ForceGraph3D({ controlType: 'orbit' })(element)
    .backgroundColor(BACKGROUND)
    .showNavInfo(false)
    .nodeId('id')
    .nodeVal((n) => 1 + n.degree ** 0.7)
    // The tooltip is rendered as HTML, so the label must be escaped.
    .nodeLabel((n) => (SHOW_LABELS
      ? `${escapeHtml(n.label)} <span style="opacity:.6">${escapeHtml(n.type)}</span>`
      : escapeHtml(n.type)))
    .nodeVisibility(nodeShown)
    .nodeThreeObject(nodeObject)
    .linkColor((l) => {
      const hex = colors.edge_types[l.type]?.color || FALLBACK;
      return linkLit(l) ? hex : dimmed(hex);
    })
    .linkOpacity(0.35)
    .linkWidth((l) => (highlight.size && linkLit(l) ? 0.7 : 0))
    .linkVisibility((l) => !hidden.edge_types.has(l.type)
      && nodeShown(l.source) && nodeShown(l.target)
      && (cutoff === null || l.born === undefined || l.born <= cutoff))
    .linkDirectionalParticles((l) => (highlight.size && linkLit(l) ? 2 : 0))
    .linkDirectionalParticleWidth(1.4)
    .linkDirectionalParticleSpeed(0.006)
    .onNodeClick(onNodeClick)
    .onBackgroundClick(onBackgroundClick)
    .graphData(data);

  // The rim's outline: a unit circle in each plane, scaled to the rim radius.
  // One circle in 2D; in 3D the three great circles sketch the shell.
  const outline = new Group();
  const circle = Array.from({ length: 129 }, (_, i) => {
    const a = (i / 128) * Math.PI * 2;
    return new Vector3(Math.cos(a), Math.sin(a), 0);
  });
  for (const [rx, ry] of [[0, 0], [Math.PI / 2, 0], [0, Math.PI / 2]]) {
    const loop = new LineLoop(new BufferGeometry().setFromPoints(circle),
      new LineBasicMaterial({ color: FALLBACK, transparent: true, opacity: 0.16, depthWrite: false }));
    loop.rotation.set(rx, ry, 0);
    outline.add(loop);
  }
  outline.visible = false;
  graph.scene().add(outline);

  // ?debug=1 exposes the graph and its data on window, for poking at from the console.
  if (new URLSearchParams(location.search).get('debug') === '1') window.__graphview = { graph, data };

  graph.d3Force('charge').strength(-140);
  graph.d3Force('link').distance(55);
  // A pull to the centre, or disconnected islands drift out of reach. Islands
  // have nothing else holding them, so they get a firmer one.
  const pull = (n) => (n.island ? 0.08 : 0.04); // firmer, but not enough to bury them in the middle
  graph.d3Force('x', forceX(0).strength(pull));
  graph.d3Force('y', forceY(0).strength(pull));
  graph.d3Force('z', forceZ(0).strength(pull));

  // Wheel zooms towards the pointer, not towards the centre, and the pivot
  // moves with it: point at a far cluster, scroll, and you are there.
  // Right-drag (or ctrl+drag) pans.
  const controls = graph.controls();
  controls.zoomToCursor = true;
  controls.screenSpacePanning = true;
  controls.zoomSpeed = 1.2;

  // Zooming out towards the pointer makes the view drift sideways and the graph
  // slide off screen. So: in, towards the pointer; out, straight back, while the
  // pivot eases home to the centre of the graph. Capture phase, so this runs
  // before the controls read the same wheel event.
  const CENTRE = new Vector3(0, 0, 0);
  let leaveDistance = Infinity;
  graph.renderer().domElement.addEventListener('wheel', (event) => {
    const zoomingOut = event.deltaY > 0;
    controls.zoomToCursor = !zoomingOut;
    if (!zoomingOut) return;
    // In 2D the camera must stay square to the plane, so the pivot is left alone.
    if (dimensions === 3) controls.target.lerp(CENTRE, 0.12);
    // Backing away this far means leaving the selection, not inspecting it.
    if (highlight.size && graph.camera().position.length() > leaveDistance) onLeave();
  }, { capture: true, passive: true });

  // Framing works from the node positions in the data, not from the rendered
  // objects: those sit at the origin until the layout has drawn a frame, and a
  // fit computed then puts the camera inside the graph.
  const positioned = (filter) => data.nodes.filter((n) => Number.isFinite(n.x) && filter(n));

  /** Never let the camera back away so far that the graph fades to nothing. */
  function limitDistance() {
    const nodes = positioned(() => true);
    if (!nodes.length) return;
    const radius = Math.max(100, ...nodes.map((n) => Math.hypot(n.x, n.y, n.z || 0)));
    controls.maxDistance = radius * 3.5;
    leaveDistance = radius * 1.6 + 150; // the margin keeps a focus on a rim node from leaving at once
  }

  /** Move the camera so the chosen nodes fill the view, keeping its current direction. */
  function fit(filter, margin = 1.12, ms = 1200) {
    const nodes = positioned(filter);
    if (!nodes.length) return;
    const centre = new Vector3();
    for (const n of nodes) centre.add(new Vector3(n.x, n.y, n.z || 0));
    centre.divideScalar(nodes.length);
    const radius = Math.max(30, ...nodes.map((n) => Math.hypot(n.x - centre.x, n.y - centre.y, (n.z || 0) - centre.z)));
    const camera = graph.camera();
    const vertical = (camera.fov * Math.PI) / 360;
    const horizontal = Math.atan(Math.tan(vertical) * (innerWidth / innerHeight));
    const distance = Math.min((radius * margin) / Math.sin(Math.min(vertical, horizontal)),
      controls.maxDistance || Infinity);
    const direction = dimensions === 2
      ? new Vector3(0, 0, 1)
      : camera.position.clone().sub(controls.target).normalize();
    if (!direction.lengthSq()) direction.set(0, 0, 1);
    const position = centre.clone().add(direction.multiplyScalar(distance));
    graph.cameraPosition(position, centre, ms);
  }

  if (WANT_BLOOM) try {
    const bloom = new UnrealBloomPass(new Vector2(innerWidth || 1, innerHeight || 1), 0.45, 0.3, 0.3);
    graph.postProcessingComposer().addPass(bloom);
  } catch (error) {
    console.warn('bloom unavailable, continuing without it', error);
  }

  let hadSize = Boolean(innerWidth && innerHeight);
  addEventListener('resize', () => {
    if (!innerWidth || !innerHeight) return; // a hidden window has no size to render into
    graph.width(innerWidth).height(innerHeight);
    graph.postProcessingComposer().setSize(innerWidth, innerHeight);
    if (!hadSize) { hadSize = true; if (aim) aim(); } // first real size: frame what was waiting
  });

  // While the layout is still moving, a camera flight lands where the target
  // used to be. So the current aim is repeated until the engine stops, unless
  // the user takes the camera, which cancels it.
  let aim = null;
  let engineRunning = true;
  let ticks = 0;
  graph.onEngineTick(() => {
    engineRunning = true;
    ticks += 1;
    if (ticks % 8 === 0) placeRim(false);
  });
  graph.onEngineStop(() => {
    engineRunning = false;
    placeRim(true);
    limitDistance();
    if (aim) aim();
  });
  controls.addEventListener('start', () => { aim = null; });
  setInterval(() => { if (aim && engineRunning) aim(); }, 1800);

  function aimAt(action) {
    // A window with no size (a tab loaded in the background) gives the camera
    // maths nothing to work with and it ends up inside the graph. Wait for one.
    aim = () => { if (innerWidth && innerHeight) action(); };
    aim();
  }

  function refresh() {
    paintOutline(data.nodes.filter((n) => n.rim));
    graph
      .nodeVisibility(graph.nodeVisibility())
      .nodeThreeObject(graph.nodeThreeObject())
      .linkColor(graph.linkColor())
      .linkWidth(graph.linkWidth())
      .linkVisibility(graph.linkVisibility())
      .linkDirectionalParticles(graph.linkDirectionalParticles());
  }

  function updateLabelThreshold() {
    // Permanent labels only for the best-connected nodes: 12% of them, 5 to 40.
    const degrees = data.nodes.map((n) => n.degree).sort((a, b) => b - a);
    const keep = Math.min(degrees.length, Math.max(5, Math.min(40, Math.round(degrees.length * 0.12))));
    labelThreshold = Math.max(2, degrees[keep - 1] ?? Infinity);
  }

  /**
   * Nodes with no links at all do not float around: they form the rim, a ring in
   * 2D and a shell in 3D, just outside everything that is connected. What the
   * memory holds but has not tied to anything marks where the graph ends.
   * Their positions are pinned (fx/fy/fz), so the layout leaves them alone.
   */
  /** The outline takes the colour of what the rim is made of: its most common node colour. */
  function paintOutline(rim) {
    const tally = new Map();
    for (const n of rim) tally.set(nodeHex(n), (tally.get(nodeHex(n)) || 0) + 1);
    const [hex] = [...tally.entries()].sort((a, b) => b[1] - a[1])[0] || [FALLBACK];
    for (const loop of outline.children) loop.material.color.set(hex);
  }

  function placeRim(settled) {
    const rim = data.nodes.filter((n) => n.rim);
    outline.visible = rim.length > 0 && !hideRim;
    if (!rim.length) return;
    const reach = data.nodes.filter((n) => !n.rim && n.x !== undefined)
      .map((n) => Math.hypot(n.x, n.y, dimensions === 3 ? n.z || 0 : 0))
      .sort((a, b) => a - b);
    const inner = reach.length ? reach[Math.floor(reach.length * 0.97)] : 0;
    const radius = Math.max(inner * 1.22 + 40, 160);
    const golden = Math.PI * (3 - Math.sqrt(5));
    outline.scale.setScalar(radius + (dimensions === 2 && rim.length > 360 ? 11 : 0));
    paintOutline(rim);
    // Seen whole, the graph is thousands of units wide: the rim's nodes scale
    // with it, or the ring of single memories thins into a bare line.
    const wanted = Math.max(8, Math.min(22, radius / 85));
    if (Math.abs(wanted - rimNodeSize) > 1) {
      rimNodeSize = wanted;
      graph.nodeThreeObject(graph.nodeThreeObject());
    }
    outline.children.forEach((loop, i) => { loop.visible = dimensions === 3 || i === 0; });
    rim.forEach((n, i) => {
      if (dimensions === 2) {
        // Two staggered rings when one would be too crowded.
        const rings = rim.length > 360 ? 2 : 1;
        const angle = (i / rim.length) * Math.PI * 2;
        const r = radius + (i % rings) * 22;
        n.fx = Math.cos(angle) * r;
        n.fy = Math.sin(angle) * r;
        n.fz = 0;
      } else {
        const y = 1 - (2 * (i + 0.5)) / rim.length; // Fibonacci sphere: even spacing
        const ringRadius = Math.sqrt(1 - y * y);
        n.fx = Math.cos(golden * i) * ringRadius * radius;
        n.fy = y * radius;
        n.fz = Math.sin(golden * i) * ringRadius * radius;
      }
      if (settled || n.x === undefined) {
        n.x = n.fx; n.y = n.fy; n.z = n.fz;
        n.__threeObj?.position.set(n.fx, n.fy, n.fz);
      }
    });
  }

  /** Mark the nodes of every small component that is not the main one. */
  function markIslands() {
    const parent = new Map(data.nodes.map((n) => [n.id, n.id]));
    const find = (id) => {
      while (parent.get(id) !== id) {
        parent.set(id, parent.get(parent.get(id)));
        id = parent.get(id);
      }
      return id;
    };
    for (const l of data.links) parent.set(find(idOf(l.source)), find(idOf(l.target)));
    const sizes = new Map();
    for (const n of data.nodes) sizes.set(find(n.id), (sizes.get(find(n.id)) || 0) + 1);
    const biggest = Math.max(0, ...sizes.values());
    islands = { count: 0, nodes: 0, rim: 0 };
    for (const [, size] of sizes) {
      if (size === 1 && biggest > 1) {
        islands.rim += 1;
      } else if (size <= ISLAND_MAX && size < biggest) {
        islands.count += 1;
        islands.nodes += size;
      }
    }
    for (const n of data.nodes) {
      const size = sizes.get(find(n.id));
      const wasRim = n.rim;
      n.rim = size === 1 && biggest > 1;
      // A rim node that gains a link goes back to the layout.
      if (wasRim && !n.rim) { n.fx = undefined; n.fy = undefined; n.fz = undefined; }
      n.island = !n.rim && size <= ISLAND_MAX && size < biggest;
    }
  }

  return {
    /** Merge nodes and links into the scene; returns how many nodes were new. */
    add(incoming) {
      let added = 0;
      for (const node of incoming.nodes) {
        if (nodeIds.has(node.id)) continue;
        const time = Date.parse(node.created_at);
        if (Number.isFinite(time)) node.born = time;
        nodeIds.add(node.id);
        data.nodes.push(node);
        added += 1;
      }
      for (const link of incoming.links) {
        const key = linkKey(link);
        if (linkKeys.has(key) || !nodeIds.has(idOf(link.source)) || !nodeIds.has(idOf(link.target))) continue;
        linkKeys.add(key);
        const time = Date.parse(link.props?.created_at);
        if (Number.isFinite(time)) link.born = time;
        data.links.push(link);
      }
      if (added) {
        updateLabelThreshold();
        markIslands();
        // Thousands of links add up to a fog: fade them as they multiply.
        graph.linkOpacity(Math.max(0.07, Math.min(0.3, 240 / (data.links.length || 1))));
        // Curved links read better, but each one is a many-segment line
        // recomputed on every tick, so only small graphs get them.
        graph.linkCurvature(data.links.length <= 1500 ? 0.18 : 0);
        // Some layout before the first frame, so the graph opens with its shape
        // already there instead of as a ball that then explodes.
        if (data.nodes.length > 400) graph.warmupTicks(40).cooldownTime(20000);
        else graph.warmupTicks(120);
        placeRim(false);
        graph.graphData(data);
        // Browsers pause the layout of a background tab; the rim must not wait for it.
        for (const delay of [1200, 4000, 9000]) setTimeout(() => placeRim(true), delay);
      }
      return added;
    },

    has: (id) => nodeIds.has(id),
    counts: () => ({ nodes: data.nodes.length, links: data.links.length }),
    islands: () => islands,

    neighborIds(id) {
      const out = [];
      for (const l of data.links) {
        if (idOf(l.source) === id) out.push(idOf(l.target));
        else if (idOf(l.target) === id) out.push(idOf(l.source));
      }
      return out;
    },

    setColors(next) { colors = next; refresh(); },
    setCoverage(hits) { recallHits = new Map(Object.entries(hits)); recallTypes = null; },

    /** Measures worth colouring by: carried as a number or a date by a fair share of the nodes. */
    metrics() {
      const names = new Set(['degree', 'created_at']);
      if (recallHits) names.add('recall_hits');
      for (const n of data.nodes) for (const key of Object.keys(n.props || {})) names.add(key);
      const enough = Math.max(10, data.nodes.length * 0.15);
      return [...names].filter((name) => {
        const values = data.nodes.map((n) => metricValue(n, name)).filter((v) => v !== undefined);
        return values.length >= enough && new Set(values).size > 2;
      }).sort();
    },

    /** 'type', 'source', or 'metric:<name>'. Returns the legend for a metric, else null. */
    setColorMode(mode) {
      colorMode = mode;
      let legend = null;
      if (mode.startsWith('metric:')) {
        const ranked = rankBy(mode.slice(7));
        metricRank = ranked.ranks;
        legend = { low: ranked.low, high: ranked.high, colours: RAMP };
      } else {
        metricRank = null;
      }
      refresh();
      return legend;
    },
    setHidden(next) { hidden = next; refresh(); },
    setIslandsHidden(on) { hideIslands = on; refresh(); },
    /** Birth times of the dated nodes, oldest first: the time-lapse's frames. */
    births: () => data.nodes.filter((n) => n.born !== undefined).map((n) => n.born)
      .sort((a, b) => a - b),

    /** Show the graph as it was at `time` (ms), or whole again with null. Only
     *  visibility changes, so this is cheap enough to call many times a second. */
    setCutoff(time) {
      cutoff = time;
      graph.nodeVisibility(graph.nodeVisibility()).linkVisibility(graph.linkVisibility());
    },

    /** A slow turn while the time-lapse plays; it only makes sense in 3D. */
    setAutoRotate(on) {
      // The turn and a repeated aim would fight over the camera; the turn wins.
      if (on) aim = null;
      controls.autoRotate = on && dimensions === 3;
      controls.autoRotateSpeed = 0.7;
    },

    setRimHidden(on) { hideRim = on; outline.visible = !on && islands.rim > 0; refresh(); },
    setHighlight(ids) { highlight = ids; refresh(); },

    slow(on) { graph.d3VelocityDecay(on ? 0.85 : 0.4); },

    flyTo(id) {
      aimAt(() => {
        const n = data.nodes.find((node) => node.id === id);
        if (!n || n.x === undefined) return;
        const distance = 60 + Math.cbrt(1 + n.degree) * 20;
        if (dimensions === 2) { // straight above the node
          graph.cameraPosition({ x: n.x, y: n.y, z: distance * 2.2 }, { x: n.x, y: n.y, z: 0 }, 1200);
          return;
        }
        const length = Math.hypot(n.x, n.y, n.z) || 1;
        const k = 1 + distance / length;
        graph.cameraPosition({ x: n.x * k, y: n.y * k, z: n.z * k }, n, 1200);
      });
    },

    frame(ids) {
      const wanted = new Set(ids);
      aimAt(() => fit((n) => wanted.has(n.id), 1.5));
    },

    /** 2 lays the graph flat, seen from above, drag pans. 3 is the free-rotating space. */
    setDimensions(next) {
      if (next === dimensions) return;
      dimensions = next;
      const flat = next === 2;
      controls.enableRotate = !flat;
      controls.mouseButtons.LEFT = flat ? MOUSE.PAN : MOUSE.ROTATE;
      if (flat) for (const n of data.nodes) { n.z = 0; n.vz = 0; }
      graph.numDimensions(next);
      placeRim(true);
      const distance = graph.camera().position.length() || 600;
      // Square to the plane in 2D; a slightly raised three-quarter view back in 3D.
      const position = flat ? { x: 0, y: 0, z: distance } : { x: distance * 0.45, y: distance * 0.3, z: distance * 0.85 };
      graph.cameraPosition(position, { x: 0, y: 0, z: 0 }, 900);
      setTimeout(() => this.frameAll(), 1600);
    },

    frameAll() {
      limitDistance();
      aimAt(() => { limitDistance(); fit(nodeShown); });
    },
  };
}
