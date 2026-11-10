// Per-browser conveniences only (pinned projects, recents, panel sizes).
// Nothing here is workflow state; every access tolerates blocked storage.
const KEY = 'workbench.prefs.v1';
const defaults = { pinned: [], recent: [], terminalHeight: 260 };
let cache = null;

function load() {
  if (cache) return cache;
  try { cache = { ...defaults, ...JSON.parse(localStorage.getItem(KEY) || '{}') }; }
  catch { cache = { ...defaults }; }
  return cache;
}
function save() {
  try { localStorage.setItem(KEY, JSON.stringify(cache)); } catch { /* private window: keep in memory */ }
}

export const prefs = {
  get: name => load()[name],
  set(name, value) { load()[name] = value; save(); },
  isPinned: id => load().pinned.includes(id),
  togglePin(id) {
    const list = load().pinned;
    cache.pinned = list.includes(id) ? list.filter(p => p !== id) : [...list, id];
    save();
    return cache.pinned.includes(id);
  },
  visit(id) {
    cache = load();
    cache.recent = [id, ...cache.recent.filter(p => p !== id)].slice(0, 8);
    save();
  },
};
