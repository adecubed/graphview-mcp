// DOM panels. Everything that comes from the data goes in through textContent.

const $ = (id) => document.getElementById(id);

function el(tag, { text, className, ...attrs } = {}, children = []) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, value);
  node.append(...children);
  return node;
}

function swatch(color) {
  const dot = el('span', { className: 'swatch' });
  dot.style.color = color;
  return dot;
}

export function renderFilters(types, onChange) {
  const hidden = { node_types: new Set(), edge_types: new Set(), sources: new Set() };
  const lists = { node_types: $('node-types'), edge_types: $('edge-types'), sources: $('sources') };

  for (const [group, list] of Object.entries(lists)) {
    list.replaceChildren();
    for (const [name, info] of Object.entries(types[group])) {
      const box = el('input', { type: 'checkbox' });
      box.checked = true;
      box.addEventListener('change', () => {
        if (box.checked) hidden[group].delete(name); else hidden[group].add(name);
        onChange(hidden);
      });
      list.append(el('li', {}, [el('label', {}, [
        box, swatch(info.color), el('span', { text: name }),
        el('span', { text: String(info.count), className: 'count' }),
      ])]));
    }
  }

  const toggle = $('filters-toggle');
  toggle.addEventListener('click', () => {
    const panel = $('filters');
    panel.hidden = !panel.hidden;
    toggle.setAttribute('aria-expanded', String(!panel.hidden));
  });
}

/** Small disconnected groups: say how many there are, let the viewer hide them. */
export function renderIslands(islands, onChange) {
  $('islands-section').hidden = islands.count === 0 && islands.rim === 0;
  $('islands-row').hidden = islands.count === 0;
  $('islands-count').textContent = String(islands.count);
  $('islands-count').title = `${islands.count} small disconnected groups, ${islands.nodes} nodes in all`;
  $('hide-islands').addEventListener('change', (event) => onChange('islands', event.target.checked));
  $('rim-row').hidden = islands.rim === 0;
  $('rim-count').textContent = String(islands.rim);
  $('rim-count').title = `${islands.rim} nodes with no links: they form the rim around the graph`;
  $('hide-rim').addEventListener('change', (event) => onChange('rim', event.target.checked));
}

/** The written answer that came with a recall, above the list of what it found. */
export function renderAnswer(result) {
  const text = result?.answer || '';
  $('answer').hidden = !text;
  $('answer-text').textContent = text;
  $('answer-mode').textContent = { recall: 'answer · from recall', path: 'path' }[result?.mode] || 'answer';
}

export function onAnswerToggle() {
  const button = $('answer-toggle');
  button.addEventListener('click', () => {
    const open = button.getAttribute('aria-expanded') !== 'true';
    button.setAttribute('aria-expanded', String(open));
    button.textContent = open ? 'hide' : 'show';
    $('answer-text').hidden = !open;
  });
}

/** Colour by type, by source, or by any measure the nodes carry. `handler` returns a legend or null. */
export function onColorMode(metrics, handler) {
  const select = $('color-mode');
  for (const name of metrics) {
    select.append(el('option', { value: `metric:${name}`, text: name.replaceAll('_', ' ') }));
  }
  select.addEventListener('change', () => {
    const legend = handler(select.value);
    $('legend').hidden = !legend;
    if (!legend) return;
    $('legend-low').textContent = legend.low;
    $('legend-high').textContent = legend.high;
    $('legend-bar').style.background = `linear-gradient(90deg, ${legend.colours.join(', ')})`;
  });
}

/** 2D / 3D switch. The choice is remembered; ?dim=2 or ?dim=3 in the URL wins. */
export function onDimensions(handler) {
  const buttons = [...document.querySelectorAll('#dims button')];
  const apply = (dim) => {
    for (const b of buttons) b.setAttribute('aria-pressed', String(Number(b.dataset.dim) === dim));
    $('hint-drag').textContent = dim === 2 ? 'drag: pan' : 'drag: rotate';
    handler(dim);
  };
  for (const b of buttons) {
    b.addEventListener('click', () => {
      const dim = Number(b.dataset.dim);
      try { localStorage.setItem('graphview.dim', String(dim)); } catch { /* private mode */ }
      apply(dim);
    });
  }
  let saved = null;
  try { saved = localStorage.getItem('graphview.dim'); } catch { /* private mode */ }
  const asked = new URLSearchParams(location.search).get('dim') || saved;
  if (asked === '2') apply(2);
}

export function onBack(handler) {
  $('back').addEventListener('click', handler);
}

/**
 * Time-lapse: a slider over the dated nodes, oldest to newest, and a play button.
 * Frames are node births, not days, so the graph grows at an even pace however
 * bursty its history was. `births` is sorted; the last position means "now".
 */
export function renderTimeline(births, total, { onCutoff, onPlaying }) {
  const bar = $('timeline');
  // A time-lapse of one instant is no time-lapse: the dates must actually differ.
  if (births.length < 10 || births[0] === births[births.length - 1]) {
    bar.hidden = true;
    return;
  }
  bar.hidden = false;
  const slider = $('time-slider');
  const play = $('time-play');
  const undated = total - births.length;
  slider.max = String(births.length);
  slider.value = slider.max;
  let timer = null;

  const show = () => {
    const at = Number(slider.value);
    const whole = at >= births.length;
    onCutoff(whole ? null : births[Math.max(at - 1, 0)]);
    const day = new Date(births[Math.max(Math.min(at, births.length) - 1, 0)]).toISOString().slice(0, 10);
    $('time-label').textContent = whole ? `now · ${total} nodes` : `${day} · ${at + undated} of ${total}`;
  };

  const stop = () => {
    clearInterval(timer);
    timer = null;
    play.textContent = '\u25B6';
    onPlaying(false);
  };

  const start = () => {
    if (Number(slider.value) >= births.length) slider.value = '0';
    play.textContent = '\u275A\u275A';
    onPlaying(true);
    const step = Math.max(1, Math.round(births.length / 260)); // about 22 seconds in all
    timer = setInterval(() => {
      slider.value = String(Math.min(Number(slider.value) + step, births.length));
      show();
      if (Number(slider.value) >= births.length) stop();
    }, 85);
  };

  const toggle = () => (timer ? stop() : start());
  play.addEventListener('click', toggle);
  slider.addEventListener('input', () => { if (timer) stop(); show(); });
  addEventListener('keydown', (event) => {
    const typing = ['TEXTAREA', 'INPUT'].includes(document.activeElement?.tagName)
      && document.activeElement !== slider;
    if (!typing && event.key.toLowerCase() === 't') toggle();
  });
  show();
}

/**
 * What the last coverage pass found. Questions that expected a text the search
 * did not bring back come first: click one to run it and see what came instead.
 */
export function renderCoverage(report, onAsk) {
  $('coverage').hidden = !report.available;
  if (!report.available) return;
  const s = report.summary;
  const judged = s.with_expectation
    ? ` Expected text in the listed hits: ${s.expected_retrieved} of ${s.with_expectation}`
      + `; in the composed answer: ${s.expected_in_answer ?? '?'}.` : '';
  const reach = Object.entries(s.reach_by_type || {})
    .map(([kind, [reached, total]]) => `${reached} of ${total} ${kind}`).join(', ');
  $('coverage-note').textContent = `${report.date}: ${s.questions} questions reached ${reach || 'nothing'}.`
    + `${judged} Colour by "recall hits" to see where.`;
  // nowhere, then only in the composed answer, then in the listed hits, then nothing expected
  const grade = (q) => (q.retrieved === null ? 'none' : q.retrieved ? 'hits' : q.in_answer ? 'answer' : 'nowhere');
  const order = { nowhere: 0, answer: 1, hits: 2, none: 3 };
  const rows = report.questions.filter((q) => !q.origin.startsWith('probe:'))
    .sort((a, b) => order[grade(a)] - order[grade(b)]).slice(0, 80);
  const list = $('coverage-questions');
  list.replaceChildren();
  for (const row of rows) {
    const wanted = row.expected.map((group) => group.join(' / ')).join(' + ');
    const [mark, why] = {
      hits: ['✓', `expected text is in the listed hits (${wanted})`],
      answer: ['◐', `expected text is only in the composed answer, not in the listed hits (${wanted})`],
      nowhere: ['✗', `expected text came back nowhere (${wanted})`],
      none: ['·', `${row.hits.length} nodes retrieved`],
    }[grade(row)];
    const button = el('button', { type: 'button', title: why }, [
      el('span', { className: `mark mark-${grade(row)}`, text: mark }), el('span', { text: row.question })]);
    button.addEventListener('click', () => onAsk(row.question));
    list.append(el('li', {}, [button]));
  }
}

/** The worklist button: what to go and fix at the source, as a file. */
export function onExport(handler) {
  const button = $('export');
  button.addEventListener('click', async () => {
    button.disabled = true;
    $('export-note').textContent = 'preparing…';
    try {
      $('export-note').textContent = await handler();
    } catch (error) {
      $('export-note').textContent = error.message;
    }
    button.disabled = false;
  });
}

/** The way home: a button and the H key bring the whole graph back into view. */
export function onFit(handler) {
  $('fit').addEventListener('click', handler);
  addEventListener('keydown', (event) => {
    const typing = ['TEXTAREA', 'INPUT'].includes(document.activeElement?.tagName);
    if (!typing && event.key.toLowerCase() === 'h') handler();
  });
}

export function renderStatus(stateName, counts, meta) {
  document.body.dataset.state = stateName;
  $('back').hidden = stateName === 'idle';
  $('clear').hidden = stateName === 'idle';
  $('state-name').textContent = stateName;
  $('counts').textContent = `${counts.nodes} nodes · ${counts.links} links`;
  const notes = [];
  if (meta.sampled) notes.push(`showing ${counts.nodes} of ${meta.total_nodes}`);
  if (meta.warnings?.length) notes.push(`${meta.warnings.length} warning(s)`);
  $('notice').textContent = notes.join(' · ');
  $('notice').title = (meta.warnings || []).join('\n');
}

function formatValue(value) {
  if (Array.isArray(value)) return value.map((v) => (typeof v === 'object' ? JSON.stringify(v) : v)).join('\n');
  if (value && typeof value === 'object') return JSON.stringify(value, null, 1);
  return String(value);
}

export function renderDetail(detail, colors, onPick, onPathFrom, onLookup) {
  const panel = $('detail');
  if (!detail) {
    panel.hidden = true;
    panel.replaceChildren();
    return;
  }
  const { node, links, refs = {} } = detail;
  const parts = [
    el('h1', { text: node.label }),
    el('div', { className: 'kind', text: `${node.type} · ${node.source} · ${node.degree} links` }),
  ];
  if (onPathFrom) {
    const pathButton = el('button', { type: 'button', className: 'action', text: 'path from here…',
      title: 'Then pick another node: the shortest chain between the two lights up' });
    pathButton.addEventListener('click', () => onPathFrom(node));
    parts.push(pathButton);
  }

  // A long text prop reads better as a paragraph than squeezed into the list.
  const bodyKey = ['content', 'text', 'description', 'summary']
    .find((key) => typeof node.props?.[key] === 'string' && node.props[key]);
  if (bodyKey) parts.push(el('p', { className: 'body', text: node.props[bodyKey] }));
  const props = Object.entries(node.props || {}).filter(([k, v]) => k !== bodyKey && !(k in refs)
    && v !== null && v !== '' && !(Array.isArray(v) && !v.length));
  if (node.created_at) props.push(['created_at', node.created_at]);
  if (props.length) {
    const list = el('dl');
    for (const [key, value] of props) list.append(el('dt', { text: key }), el('dd', { text: formatValue(value) }));
    parts.push(list);
  }

  // A reference prop (the episodes a fact came from, say) is a count until asked:
  // resolving it costs a query, and most of the time the fact itself is enough.
  for (const [prop, ref] of Object.entries(refs)) {
    const box = el('div', { className: 'refs' });
    const button = el('button', { type: 'button', className: 'action',
      text: `${prop.replaceAll('_', ' ')}: ${ref.count} ${ref.lookup}${ref.count === 1 ? '' : 's'} · show` });
    button.addEventListener('click', async () => {
      button.disabled = true;
      try {
        const found = await onLookup(node.id, prop);
        const list = el('ul', { className: 'rows' });
        for (const row of found.rows || []) {
          const { id, ...rest } = row;
          const when = Object.values(rest).find((v) => typeof v === 'string' && /^\d{4}-\d{2}-\d{2}/.test(v));
          const text = Object.entries(rest).filter(([, v]) => v !== when && v !== null && v !== '')
            .map(([, v]) => String(v)).join(' · ');
          list.append(el('li', {}, [el('span', { className: 'when', text: when ? when.slice(0, 10) : '' }),
            el('span', { text: text.length > 240 ? `${text.slice(0, 239)}…` : text })]));
        }
        if (!(found.rows || []).length) list.append(el('li', { text: found.error || 'nothing found' }));
        button.replaceWith(el('h2', { text: `${prop.replaceAll('_', ' ')} (${(found.rows || []).length} of ${ref.count})` }), list);
      } catch (error) {
        button.textContent = error.message;
      }
    });
    box.append(button);
    if (ref.shared_with) {
      // The same list on other nodes means the writer stamped a whole batch on
      // everything it produced: say so before someone reads the rows as evidence.
      const others = `${ref.shared_with} other node${ref.shared_with === 1 ? '' : 's'}`;
      box.append(el('p', { className: 'note',
        text: `The same ${ref.count} ${ref.lookup}s are listed on ${others}: a batch, not this node's own sources.` }));
    }
    parts.push(box);
  }

  for (const [type, entries] of Object.entries(links)) {
    const heading = el('h2', {}, [swatch(colors.edge_types[type]?.color || '#8aa0b5'), ` ${type} (${entries.length})`]);
    heading.style.display = 'flex';
    heading.style.alignItems = 'center';
    heading.style.gap = '6px';
    const list = el('ul', { className: 'links' });
    for (const entry of entries.slice(0, 200)) {
      const button = el('button', { type: 'button' }, [
        el('span', { className: 'arrow', text: entry.direction === 'out' ? '→' : '←' }),
        swatch(colors.node_types[entry.node.type]?.color || '#8aa0b5'),
        el('span', { text: entry.node.label }),
      ]);
      button.addEventListener('click', () => onPick(entry.node.id));
      list.append(el('li', {}, [button]));
    }
    parts.push(heading, list);
  }
  panel.replaceChildren(...parts);
  panel.hidden = false;
  panel.scrollTop = 0;
}

export function renderResults(matches, colors, onPick) {
  const list = $('results');
  list.replaceChildren();
  list.hidden = matches === null;
  if (matches === null) return;
  if (!matches.length) {
    list.append(el('li', { text: 'nothing found' }));
    return;
  }
  for (const node of matches) {
    const head = el('span', { className: 'head' }, [
      swatch(colors.node_types[node.type]?.color || '#8aa0b5'),
      el('span', { text: node.label }),
      el('span', { className: 'type', text: node.unlinked ? 'not in the graph' : node.type }),
    ]);
    const parts = [head];
    if (node.snippet) parts.push(el('span', { className: 'snippet', text: node.snippet }));
    const button = el('button', { type: 'button', className: 'hit' }, parts);
    if (node.unlinked) button.disabled = true;
    else button.addEventListener('click', () => onPick(node.id));
    list.append(el('li', {}, [button]));
  }
}

export function onQuestion(submit, cancel, clear) {
  const box = $('question');
  $('clear').addEventListener('click', () => { clear(); box.focus(); });
  box.addEventListener('input', () => {
    box.style.height = 'auto';
    box.style.height = `${box.scrollHeight}px`;
  });
  box.addEventListener('keydown', (event) => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      submit(box.value.trim());
    }
  });
  addEventListener('keydown', (event) => {
    if (event.key === 'Escape') {
      cancel();
    } else if (event.key === '/' && document.activeElement !== box) {
      event.preventDefault();
      box.focus();
    }
  });
}
