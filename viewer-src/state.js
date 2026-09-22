// idle -> searching -> results -> focus. Esc walks back one step.
// The scene and the panels only ever read this object and redraw from it.

export function createState(onChange) {
  const state = {
    name: 'idle',
    matches: [],        // node ids found by the last search, best first
    around: [],         // ids lit with the matches: what a recall's facts are about
    asked: false,       // a question's answer is on screen, with or without matches
    focusId: null,
    highlight: new Set(), // ids that stay bright; empty means everything is bright
  };

  const emit = () => onChange(state);

  return {
    current: state,

    searching() {
      state.name = 'searching';
      emit();
    },

    // `asked` is true right after a question: even when nothing in the graph
    // matched there is an answer, or a "nothing found", on screen, and that
    // must be a state one can walk back from. Coming back from a focus keeps it.
    results(ids, around = state.around, asked = state.asked) {
      state.matches = ids;
      state.around = around;
      state.asked = asked;
      state.focusId = null;
      state.name = ids.length || asked ? 'results' : 'idle';
      state.highlight = new Set([...ids, ...around]);
      emit();
    },

    focus(id, neighborIds) {
      state.name = 'focus';
      state.focusId = id;
      state.highlight = new Set([id, ...neighborIds]);
      emit();
    },

    back() {
      if (state.name === 'focus' && (state.matches.length || state.asked)) this.results(state.matches);
      else this.reset();
    },

    /** Straight to idle from anywhere: nothing selected, the whole graph lit. */
    reset() {
      if (state.name === 'idle') return;
      state.matches = [];
      state.around = [];
      state.asked = false;
      state.focusId = null;
      state.name = 'idle';
      state.highlight = new Set();
      emit();
    },
  };
}
