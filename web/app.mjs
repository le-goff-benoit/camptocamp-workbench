// OpenClaw — single-page interface.
// State lives in the URL (?v=…&p=…&r=…&t=…&d=…&q=…) so views can be reloaded,
// shared locally and navigated with the browser history.
import { renderDashboard, renderSources, overviewHTML, metricsHTML, progressHTML } from './dashboard.mjs';
import { escape, icon, initials, matchesProject, ago } from './text.mjs';
import { markdown } from './markdown.mjs';
import { prefs } from './prefs.mjs';
import { createPalette } from './palette.mjs';
import { renderProjectDashboard, loadProjectEmails, paintProjectEmails, setProjectMailFilter } from './project-dashboard.mjs';
import { chooseAgent, agentLogo, chooserOpen } from './chooser.mjs';
import { providerSettingsHTML, workflowSettingsHTML, connectionsHTML, providerName } from './configuration.mjs';

const $ = (selector, scope = document) => scope.querySelector(selector);
const $$ = (selector, scope = document) => [...scope.querySelectorAll(selector)];
const e = escape;

const VIEWS = new Set(['dashboard', 'emails', 'agenda', 'projects', 'project', 'library', 'connections', 'settings']);
const TABS = [['overview', 'Vue d’ensemble', 'home'], ['requests', 'Demandes', 'list'], ['documents', 'Documents', 'file'], ['metrics', 'Mesures', 'chart'], ['memory', 'Mémoire', 'book-open']];
const DOCS = [['plan', 'Plan'], ['decisions', 'Décisions'], ['release-journal', 'Journal'], ['qa', 'Recette']];
const stages = ['nouvelle', 'analyse', 'plan', 'realisation', 'verification', 'terminee'];
const stageNames = { nouvelle: 'Demande', analyse: 'Analyse', plan: 'Plan', realisation: 'Réalisation', verification: 'Vérification', terminee: 'Réception' };
const statusNames = { 'a-faire': 'À faire', 'en-cours': 'En cours', 'attente-validation': 'Plan à valider', 'a-verifier': 'À vérifier', bloquee: 'Bloquée', terminee: 'Reçue' };
const viewNames = { dashboard: 'Aujourd’hui', emails: 'Emails récents', agenda: 'Agenda', projects: 'Projets', library: 'Bibliothèque', connections: 'Connexions', settings: 'Paramètres' };

const state = {
  view: 'dashboard', project: null, release: null, tab: 'overview', doc: 'plan', request: null, filter: 'all',
  snapshot: null, detail: null, record: null, dashboard: null, dashboardFetched: 0, dashboardRefreshed: 0,
  terminals: new Map(), selectedTerminal: null, lastTerminals: {}, panel: {}, query: '', crumbs: [], renderSeq: 0, mailFilter: 'all', projectFilter: '',
};
let modalAction;

/* ---------------------------------------------------------------- basics */
async function rpc(action, data = {}) {
  const response = await fetch('/workbench/api', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Workbench-UI': '1' }, body: JSON.stringify({ action, data }) });
  let payload;
  try { payload = await response.json(); } catch { throw new Error('Service OpenClaw indisponible. Vérifiez qu’il est démarré.'); }
  if (!response.ok || !payload.ok) throw new Error(payload.error === 'Commande inconnue' ? 'Fonction disponible après le redémarrage du service OpenClaw.' : payload.error ?? 'Service indisponible');
  return payload.result;
}
function toast(message, error = false) {
  const target = $('#toast'), panel = $('#terminal-panel'), area = $('#workspace').getBoundingClientRect();
  // Keep notifications inside the work area, above the terminal.
  target.style.setProperty('--toast-bottom', (panel.hidden ? 20 : panel.offsetHeight + 16) + 'px');
  target.style.setProperty('--toast-right', Math.max(16, innerWidth - area.right + 20) + 'px');
  target.textContent = message; target.classList.toggle('error', error); target.hidden = false;
  clearTimeout(toast.timer); toast.timer = setTimeout(() => { target.hidden = true; }, error ? 10000 : 4000);
}
$('#toast').onclick = () => { $('#toast').hidden = true; };

function modal(title, fields, action, submit = 'Enregistrer', { cancel = 'Annuler', wide = false, danger = false, secondary = false, email = false } = {}) {
  $('#modal-body').innerHTML = `<h2 id="modal-title" tabindex="-1">${e(title)}</h2>${fields}`;
  $('#modal-submit').textContent = submit; $('#modal-submit').className = danger ? 'danger' : secondary ? 'secondary' : '';
  $('#modal-cancel').hidden = cancel === false; $('#modal-cancel').textContent = cancel || 'Annuler';
  $('#modal').classList.toggle('wide', wide);
  $('#modal').classList.toggle('email-dialog', email);
  $('#modal-error').textContent = ''; modalAction = action;
  if (!$('#modal').open) $('#modal').showModal();
  const first = $('#modal-body').querySelector('input:not([type=checkbox]):not([type=file]):not([readonly]),textarea,select');
  (email ? $('#modal-title') : first ?? $('#modal-submit')).focus({ preventScroll: email });
  if (email) { $('#modal-body').scrollTop = 0; $('#modal').scrollTop = 0; }
}
const closeModal = () => $('#modal').open && $('#modal').close();
function confirmDialog(title, html, label, options = {}) {
  return new Promise(resolve => {
    let accepted = false;
    modal(title, html, async () => { accepted = true; closeModal(); }, label, options);
    $('#modal').addEventListener('close', () => resolve(accepted), { once: true });
  });
}
const input = (name, label, value = '', extra = '', hint = '') => `<label for="field-${name}">${e(label)}</label><input id="field-${name}" name="${name}" value="${e(value)}" ${extra}>${hint ? `<p class="field-hint">${e(hint)}</p>` : ''}`;
const area = (name, label, value = '', extra = '', hint = '') => `<label for="field-${name}">${e(label)}</label><textarea id="field-${name}" name="${name}" ${extra}>${e(value)}</textarea>${hint ? `<p class="field-hint">${e(hint)}</p>` : ''}`;
const select = (name, label, options, value = '') => `<label for="field-${name}">${e(label)}</label><select id="field-${name}" name="${name}">${options.map(([id, text]) => `<option value="${e(id)}" ${id === value ? 'selected' : ''}>${e(text)}</option>`).join('')}</select>`;
const badge = record => `<span class="badge ${e(record.status)}">${e(statusNames[record.status] ?? record.status)}</span>`;
function empty(title, text, button = '', action = '', iconName = 'layers') {
  return `<div class="empty"><div class="empty-icon">${icon(iconName)}</div><h1>${e(title)}</h1><p>${e(text)}</p>${button ? `<button data-action="${action}">${icon('plus')}${e(button)}</button>` : ''}</div>`;
}
/** « changelog/2026-10-08_01_transfert-et-audit » → « Transfert et audit · 08.10.2026 ». */
const releaseName = release => {
  if (!release?.legacy) return release?.title ?? '';
  const match = /^(\d{4})-(\d{2})-(\d{2})_\d+_(.+)$/.exec(String(release.title));
  if (!match) return release.title;
  const words = match[4].replace(/[-_]+/g, ' ').trim();
  return `${words.charAt(0).toUpperCase()}${words.slice(1)} · ${match[3]}.${match[2]}.${match[1]}`;
};
const projectById = id => state.snapshot?.projects.find(p => p.id === id);
const terminalLabel = kind => ({ shell: 'Terminal', codex: 'Codex', claude: 'Claude', 'claude-login': 'Connexion Claude', 'chatgpt-login': 'Connexion ChatGPT', 'openclaw-login': 'Connexion OpenClaw' }[kind] ?? kind);
const content = () => $('#content');
const page = (html, narrow = false) => { content().innerHTML = `<div class="page${narrow ? ' narrow' : ''}">${html}</div>`; };

/* ---------------------------------------------------------------- routing */
function urlFor() {
  const params = new URLSearchParams();
  if (state.view !== 'dashboard') params.set('v', state.view);
  if (state.view === 'project') {
    params.set('p', state.project);
    if (state.release) params.set('r', state.release);
    if (state.tab !== 'overview') params.set('t', state.tab);
    if (state.tab === 'documents' && state.doc !== 'plan') params.set('d', state.doc);
    if (state.request) params.set('q', state.request);
  }
  const query = params.toString();
  return location.pathname + (query ? '?' + query : '');
}
function readURL() {
  const params = new URLSearchParams(location.search);
  const project = params.get('p') ?? params.get('project');
  const tab = params.get('t');
  return {
    view: project ? 'project' : VIEWS.has(params.get('v')) ? params.get('v') : 'dashboard', project,
    release: params.get('r'), tab: TABS.some(([id]) => id === tab) ? tab : 'overview',
    doc: DOCS.some(([id]) => id === params.get('d')) ? params.get('d') : 'plan', request: params.get('q'),
  };
}
const editorDirty = () => { const editor = $('#document-editor'); return !!editor && editor.value !== editor.dataset.original; };
async function confirmLeave() {
  if (!editorDirty()) return true;
  return confirmDialog('Document non enregistré', '<p>Vos modifications seront perdues si vous quittez ce document.</p>', 'Quitter sans enregistrer', { cancel: 'Continuer l’édition', danger: true });
}
async function go(patch, { push = true } = {}) {
  if (!(await confirmLeave())) { if (!push) history.pushState(null, '', urlFor()); return; }
  if (patch.project && patch.project !== state.project) Object.assign(state, { release: null, tab: 'overview', request: null, filter: 'all' });
  Object.assign(state, patch);
  if (state.view === 'project' && state.project) prefs.visit(state.project);
  const url = urlFor();
  if (push && url !== location.pathname + location.search) history.pushState(null, '', url);
  else history.replaceState(null, '', url);
  $('#shell').classList.remove('sidebar-open'); $('#sidebar-scrim').hidden = true;
  $$('details.menu[open]').forEach(menu => menu.removeAttribute('open'));
  await render();
  if (push) content().scrollTop = 0;
}
const openProject = (project, extra = {}) => go({ view: 'project', project, request: null, tab: 'overview', ...extra });
window.addEventListener('popstate', () => { void go(readURL(), { push: false }).catch(error => toast(error.message, true)); });
window.addEventListener('beforeunload', event => { if (editorDirty()) { event.preventDefault(); event.returnValue = ''; } });

function setCrumbs(items) {
  state.crumbs = items;
  $('#breadcrumb').innerHTML = items.map((item, index) => {
    const sep = index ? icon('chevron-right', 'sep') : '';
    return index === items.length - 1 ? `${sep}<span class="current" title="${e(item.label)}">${e(item.label)}</span>` : `${sep}<button data-crumb="${index}">${e(item.label)}</button>`;
  }).join('');
  document.title = `${items.at(-1)?.label ?? 'Aujourd’hui'} · Workbench`;
}

/* ---------------------------------------------------------------- snapshot & sidebar */
async function snapshot() {
  state.snapshot = await rpc('snapshot');
  const running = state.snapshot.jobs.filter(j => j.status === 'running').length;
  $('#activity-indicator').hidden = !running; $('#activity-indicator').textContent = running ? `${running} analyse${running > 1 ? 's' : ''} en cours` : '';
  renderProjectShortcuts();
  updateTerminalCount();
  return state.snapshot;
}
async function refreshDashboardData(force = false) {
  if (!force && Date.now() - state.dashboardFetched < 20000) return state.dashboard;
  state.dashboardFetched = Date.now();
  try { state.dashboard = await rpc('dashboard.get'); renderProjectShortcuts(); } catch { /* sidebar badges are optional */ }
  return state.dashboard;
}
function attentionByProject() {
  const counts = {};
  for (const row of state.dashboard?.attention ?? []) counts[row.project] = (counts[row.project] ?? 0) + 1;
  return counts;
}
function renderProjectShortcuts() {
  if (!state.snapshot) return;
  const all = state.snapshot.projects, query = state.query.trim(), list = $('#project-shortcuts'), scroll = list.scrollTop;
  const attention = attentionByProject();
  const live = new Set(state.snapshot.terminals.filter(t => t.exit_code === null).map(t => t.project));
  const current = state.view === 'project' ? state.project : null;
  const row = p => `<button class="shortcut${p.id === current ? ' active' : ''}" data-project="${e(p.id)}" aria-label="Projet ${e(p.name)}" title="${e(p.path)}"><span class="project-initial">${e(initials(p.name))}</span><span class="project-name">${e(p.name)}</span><span class="marks">${attention[p.id] ? `<span class="attention-count" title="${attention[p.id]} demande(s) à traiter">${attention[p.id]}</span>` : ''}${live.has(p.id) ? '<span class="terminal-dot" title="Terminal ouvert"></span>' : ''}</span></button>`;
  const group = (label, iconName = '') => `<div class="shortcut-group">${iconName ? icon(iconName, 'sm') : ''}${e(label)}</div>`;
  $('#projects-total').textContent = query ? `${all.filter(p => matchesProject(p, query)).length}/${all.length}` : all.length;
  let html = '';
  if (query) {
    const rows = all.filter(p => matchesProject(p, query));
    html = rows.length ? rows.slice(0, 50).map(row).join('') + (rows.length > 50 ? `<button class="show-all" data-nav="projects">Voir les ${rows.length} résultats</button>` : '') : '<p class="no-projects">Aucun projet trouvé. Essayez un nom de client ou de dépôt.</p>';
  } else if (all.length <= 12) {
    const pinned = all.filter(p => prefs.isPinned(p.id));
    html = all.length ? [...pinned, ...all.filter(p => !prefs.isPinned(p.id))].map(row).join('') : '<p class="no-projects">Aucun projet découvert. Choisissez vos dossiers dans Paramètres.</p>';
  } else {
    const byId = new Map(all.map(p => [p.id, p]));
    const pinned = prefs.get('pinned').map(id => byId.get(id)).filter(Boolean);
    const recent = prefs.get('recent').filter(id => !prefs.isPinned(id)).map(id => byId.get(id)).filter(Boolean).slice(0, 6);
    const shown = new Set([...pinned, ...recent].map(p => p.id));
    if (current && !shown.has(current) && byId.get(current)) recent.unshift(byId.get(current));
    // Until enough projects are pinned or visited, suggest those with work in progress.
    const active = [...new Set((state.dashboard?.open_releases ?? []).map(r => r.project))].filter(id => !shown.has(id) && id !== current).map(id => byId.get(id)).filter(Boolean).slice(0, Math.max(0, 8 - pinned.length - recent.length));
    if (pinned.length) html += group('Épinglés', 'star') + pinned.map(row).join('');
    if (recent.length) html += group('Récents', 'clock') + recent.map(row).join('');
    if (active.length) html += group('Releases ouvertes', 'layers') + active.map(row).join('');
    if (!pinned.length && !recent.length && !active.length) html += '<p class="no-projects">Filtrez ou ouvrez un projet : vos projets récents et épinglés (★) apparaîtront ici.</p>';
    html += `<button class="show-all" data-nav="projects">${icon('folder', 'sm')}Voir les ${all.length} projets</button>`;
  }
  list.innerHTML = html;
  list.scrollTop = scroll;
}
function renderProjectRows() {
  const rows = state.snapshot.projects.filter(p => matchesProject(p, state.query));
  $('#projects-result-count').textContent = `${rows.length} projet${rows.length > 1 ? 's' : ''}`;
  const pinned = rows.filter(p => prefs.isPinned(p.id)), others = rows.filter(p => !prefs.isPinned(p.id));
  $('#projects-list').innerHTML = rows.length ? `<div class="project-list-head"><span></span><span>Projet</span><span class="branch">Branche</span><span></span></div>` + [...pinned, ...others].map(p => {
    const isPinned = prefs.isPinned(p.id);
    return `<article class="project-list-row" data-project="${e(p.id)}" tabindex="0" role="button" aria-label="Ouvrir ${e(p.name)}"><button class="icon-button" data-pin="${e(p.id)}" aria-pressed="${isPinned}" aria-label="${isPinned ? 'Désépingler' : 'Épingler'} ${e(p.name)}" title="${isPinned ? 'Désépingler' : 'Épingler'}">${icon('star')}</button><div><h2>${e(p.name)}${p.odoo ? '<span class="tag odoo">Odoo</span>' : ''}${p.available === false ? '<span class="tag prod">Git à vérifier</span>' : ''}</h2><div class="path">${e(p.path)}</div></div><span class="branch">${p.branch ? icon('branch') + e(p.branch) : '<span class="muted">Sans branche</span>'}</span><span class="project-open">Ouvrir →</span></article>`;
  }).join('') : '<div class="panel-empty">Aucun projet ne correspond à votre recherche.</div>';
}

/* ---------------------------------------------------------------- render */
async function render() {
  const seq = ++state.renderSeq;
  const navTarget = state.view === 'project' ? 'projects' : state.view;
  $$('.nav-item').forEach(item => item.classList.toggle('active', item.dataset.nav === navTarget));
  if (state.view === 'project' && !projectById(state.project)) { state.view = 'projects'; toast('Projet introuvable : vérifiez les dossiers de découverte.', true); }
  if (state.view !== 'project') setCrumbs([{ label: viewNames[state.view] ?? 'Aujourd’hui' }]);
  if (state.view === 'dashboard') {
    state.dashboardRefreshed = Date.now();
    const data = await renderDashboard(rpc, () => state.view === 'dashboard' && state.renderSeq === seq, state);
    if (data) { state.dashboard = data; state.dashboardFetched = Date.now(); renderProjectShortcuts(); }
  } else if (state.view === 'emails' || state.view === 'agenda') {
    const view = state.view; await renderSources(rpc, view, () => state.view === view, state);
  } else if (state.view === 'projects') renderProjects();
  else if (state.view === 'project') await renderProject(seq);
  else if (state.view === 'settings') renderSettings();
  else if (state.view === 'library') renderLibrary();
  else if (state.view === 'connections') renderConnections();
  if (seq !== state.renderSeq) return;
  renderProjectShortcuts();
  await syncTerminalScope();
}

function renderProjects() {
  page(`<div class="page-head"><div><h1>Projets</h1><p>Les dépôts Git découverts dans vos dossiers. Épinglez ceux que vous suivez pour les garder dans la barre latérale.</p></div><div class="page-actions"><button class="secondary small" data-action="refresh-projects">${icon('refresh')}Relancer la découverte</button><button class="secondary small" data-nav="settings">${icon('folder')}Dossiers de découverte</button></div></div><div class="search-field">${icon('search')}<input id="projects-filter" type="search" aria-label="Filtrer les projets" placeholder="Nom du projet, client, domaine ou chemin…" value="${e(state.query)}"></div><p class="hint" id="projects-result-count"></p><div id="projects-list" class="project-list"></div>`);
  renderProjectRows();
  $('#projects-filter').oninput = event => { state.query = event.target.value; $('#project-search').value = state.query; renderProjectShortcuts(); renderProjectRows(); };
}

/* ---------------------------------------------------------------- project */
function defaultRelease(releases) {
  return releases.find(r => !r.legacy && r.status === 'ouverte')?.id ?? releases.find(r => r.status === 'ouverte')?.id ?? releases[0]?.id ?? null;
}
function projectHeader(project) {
  const pinned = prefs.isPinned(project.id);
  const github = project.github_url ? `<a class="icon-button" href="${e(project.github_url)}" target="_blank" rel="noreferrer" aria-label="GitHub" title="Ouvrir le dépôt GitHub">${icon('github')}</a>` : '';
  return `<header class="project-header"><div class="project-title"><h1>${e(project.name)}</h1><div class="project-meta">${project.odoo ? '<span class="tag odoo">Odoo</span>' : ''}${project.branch ? `<span class="branch">${icon('branch')}${e(project.branch)}</span>` : ''}${project.available === false ? '<span class="tag prod">Git à vérifier</span>' : ''}<button class="path-copy" data-action="copy-path" title="Copier le chemin">${e(project.path)}${icon('copy')}</button></div></div>
    <div class="project-actions"><button class="secondary" data-action="show-project-terminal" aria-label="Terminal du projet" aria-haspopup="menu">${icon('terminal')}Terminal</button>${github}
    <button class="icon-button" data-action="toggle-pin" aria-pressed="${pinned}" aria-label="${pinned ? 'Désépingler le projet' : 'Épingler le projet'}" title="${pinned ? 'Désépingler' : 'Épingler dans la barre latérale'}">${icon('star')}</button>
    <details class="menu"><summary class="icon-button" aria-label="Plus d’actions" title="Plus d’actions">${icon('more')}</summary><div class="menu-list" role="menu"><button role="menuitem" data-action="new-environment">${icon('server')}Ajouter un environnement</button><button role="menuitem" data-action="new-release">${icon('layers')}Nouvelle release</button><hr><button role="menuitem" data-action="project-settings">${icon('settings')}Réglages du projet</button></div></details></div></header>`;
}
function releaseBar(releases, release, requests) {
  if (!releases.length) return `<div class="release-bar">${icon('layers')}<span class="muted">Aucune release pour le moment</span><span class="actions"><button class="small" data-action="new-release">${icon('plus')}Ouvrir une première release</button></span></div>`;
  const current = requests.filter(r => r.release === release?.id);
  const status = release?.status === 'ouverte' ? '<span class="badge en-cours">Ouverte</span>' : '<span class="badge cloturee">Clôturée</span>';
  const canRequest = release && !release.legacy && release.status === 'ouverte';
  return `<div class="release-bar">${icon('layers')}<select id="release-select" aria-label="Release affichée">${releases.map(r => `<option value="${e(r.id)}" ${r.id === release?.id ? 'selected' : ''}>${e(releaseName(r))}</option>`).join('')}</select>${status}${!release?.legacy ? progressHTML(current.filter(r => r.status === 'terminee').length, current.length) : ''}<span class="actions"><button class="secondary small" data-action="new-release">${icon('plus')}Nouvelle release</button>${canRequest ? `<button class="small" data-action="new-request">${icon('plus')}Nouvelle demande</button>` : ''}</span></div>`;
}
async function renderProject(seq = state.renderSeq) {
  const requested = state.project;
  const detail = await rpc('project.get', { project: requested });
  if (seq !== state.renderSeq || state.view !== 'project' || state.project !== requested) return;
  state.detail = detail;
  const { project, releases, requests } = detail;
  if (!releases.some(r => r.id === state.release)) { state.release = defaultRelease(releases); history.replaceState(null, '', urlFor()); }
  if (state.request) return renderRequest(seq);
  const release = releases.find(r => r.id === state.release);
  const current = requests.filter(r => r.release === state.release);
  setCrumbs([{ label: 'Projets', patch: { view: 'projects' } }, { label: project.name }]);
  page(`${projectHeader(project)}${releaseBar(releases, release, requests)}<nav class="tabs" role="tablist" aria-label="Sections du projet">${TABS.map(([id, name, iconName]) => `<button class="tab${state.tab === id ? ' active' : ''}" data-tab="${id}" role="tab" aria-selected="${state.tab === id}">${icon(iconName)}${name}${id === 'requests' && current.length ? `<span class="count">${current.length}</span>` : ''}</button>`).join('')}</nav><div id="project-body" role="tabpanel"></div>`);
  const body = $('#project-body');
  const stillHere = () => seq === state.renderSeq && state.view === 'project' && state.project === requested;
  if (state.tab === 'overview') renderProjectDashboard(detail, release, rpc, () => stillHere() && state.tab === 'overview');
  else if (state.tab === 'requests') await renderRequests(body, release, current, stillHere);
  else if (state.tab === 'documents') {
    if (!release) { body.innerHTML = empty('Ouvrez une release', 'Le plan, les décisions, le journal et la recette sont rattachés à une release.', 'Nouvelle release', 'new-release'); return; }
    const docs = release.legacy ? DOCS.slice(0, 1) : DOCS;
    body.innerHTML = (docs.length > 1 ? `<div class="segmented" role="tablist" aria-label="Documents de la release">${docs.map(([id, name]) => `<button role="tab" data-doc="${id}" aria-selected="${state.doc === id}" class="${state.doc === id ? 'active' : ''}">${name}</button>`).join('')}</div>` : '') + '<div id="document-area"></div>';
    await showDocument(docs.some(([id]) => id === state.doc) ? state.doc : 'plan', $('#document-area'));
  } else if (state.tab === 'metrics') {
    body.innerHTML = release ? '<p class="loading">Lecture des mesures…</p>' : empty('Aucune release', 'Les mesures sont calculées par release.');
    if (release) { const overview = await rpc('release.overview', { project: requested, release: state.release }); if (stillHere()) body.innerHTML = metricsHTML(overview); }
  } else if (state.tab === 'memory') await renderMemory(body, stillHere);
}
async function renderRequests(body, release, current, stillHere) {
  if (!release) { body.innerHTML = empty('Aucune release', 'Le plan et ses tâches sont rattachés à une release. Ouvrez-en une pour y verser les demandes et emails du client.', 'Nouvelle release', 'new-release'); return; }
  if (release.legacy) {
    body.innerHTML = '<p class="loading">Lecture du plan de la release…</p>';
    const board = await rpc('release.board', { project: state.project, release: state.release });
    if (!stillHere()) return;
    const totals = board.totals ?? {};
    const facts = board.kind === 'plan' ? [`${totals.tasks ?? 0} tâche(s)`, `${totals.received ?? 0} reçue(s)`, totals.ready ? `${totals.ready} prête(s)` : ''].filter(Boolean).join(' · ') : 'Suivi par points du README';
    const columns = board.columns.filter(c => c.items.length || !['attention'].includes(c.id)).map(c => ({ ...c, cards: c.items.map(board.kind === 'plan' ? taskCard : pointCard) }));
    body.innerHTML = `<div class="board-head"><div><strong>${board.kind === 'plan' ? 'Plan de la release' : 'Points suivis'}</strong><small>${e(facts)}</small></div>${board.next ? `<p class="next-step">${icon('arrow-right', 'sm')}${e(board.next)}</p>` : ''}</div>${board.error ? `<p class="error">${e(board.error)}</p>` : ''}${kanbanHTML(columns)}
      <section class="block section"><div class="block-head"><h2>${icon('mail')}Demande du client${board.mails.length ? ` <span class="count">${board.mails.length} email${board.mails.length > 1 ? 's' : ''}</span>` : ''}</h2>${board.demande ? `<button class="ghost small" data-action="toggle-demande">${icon('file')}Lire demande.md</button>` : ''}</div>${board.mails.length ? `<ul class="mail-list">${board.mails.map(m => `<li>${icon('mail', 'sm')}${e(m)}</li>`).join('')}</ul>` : `<p class="muted">${board.open ? 'Aucun email versé. Ouvrez un email du projet puis « Verser dans la release ».' : 'Aucun email versé dans cette release.'}</p>`}<div id="demande-doc" hidden></div></section>
      <details class="section folder-details"><summary>Dossier de la release (README)</summary><div id="legacy-document"></div></details>`;
    $('.folder-details').addEventListener('toggle', event => { if (event.target.open && !$('#legacy-document').children.length) void showDocument('plan', $('#legacy-document')); });
    return;
  }
  if (!current.length) {
    body.innerHTML = release.status === 'ouverte' ? empty('Un premier besoin pour cette release', 'Ajoutez une demande ou versez un email du projet. L’analyse préparera les critères et le plan.', 'Créer une demande', 'new-request', 'list') : empty('Release sans demande', 'Cette release clôturée ne contient aucune demande.');
    return;
  }
  const columns = STAGE_COLUMNS.map(([id, label, test]) => ({ id, label, cards: current.filter(test).map(requestCard) })).filter(c => c.cards.length || c.id !== 'bloquee');
  body.innerHTML = kanbanHTML(columns) + (release.status === 'ouverte' ? `<div class="section row between wrap"><small>La clôture exige la réception de chaque demande.</small><button class="secondary" data-action="close-release">Clôturer la release…</button></div>` : '');
}
const STAGE_COLUMNS = [
  ['cadrage', 'À cadrer', r => r.status !== 'bloquee' && ['nouvelle', 'analyse'].includes(r.stage)],
  ['plan', 'Plan à valider', r => r.status !== 'bloquee' && r.stage === 'plan'],
  ['realisation', 'En réalisation', r => r.status !== 'bloquee' && r.stage === 'realisation'],
  ['verification', 'À vérifier', r => r.status !== 'bloquee' && r.stage === 'verification'],
  ['bloquee', 'Bloquées', r => r.status === 'bloquee'],
  ['terminee', 'Reçues', r => r.status !== 'bloquee' && r.stage === 'terminee'],
];
function kanbanHTML(columns) {
  return `<div class="kanban">${columns.map(c => `<section class="kanban-col ${e(c.id)}" aria-label="${e(c.label)}"><header><h3>${e(c.label)}</h3><span class="count">${c.cards.length}</span></header><div class="kanban-cards">${c.cards.join('') || '<p class="kanban-empty">Rien ici</p>'}</div></section>`).join('')}</div>`;
}
function taskCard(t) {
  const facts = [t.route, t.criteria ? `${t.criteria} critère${t.criteria > 1 ? 's' : ''}` : '', Number.isFinite(t.forecast_minutes) ? `prévu ${Math.round(t.forecast_minutes)} min` : ''].filter(Boolean).join(' · ');
  const why = t.detail || t.waiting_for;
  return `<article class="kanban-card${t.ready ? ' ready' : ''}"><div class="kanban-card-head"><span class="request-id">${e(t.id)}</span>${t.ready ? '<span class="badge a-faire">Prête</span>' : ''}${t.risk === 'high' ? '<span class="tag prod">Risque élevé</span>' : ''}</div><h4>${e(t.title)}</h4>${facts ? `<small>${e(facts)}</small>` : ''}${why ? `<small class="kanban-why">${e(why)}</small>` : ''}${t.depends_on?.length && !t.waiting_for ? `<small class="kanban-deps">Après ${e(t.depends_on.join(', '))}</small>` : ''}</article>`;
}
function pointCard(p) {
  return `<article class="kanban-card"><div class="kanban-card-head"><span class="request-id">Point ${e(p.id)}</span></div><h4>${e(p.title)}</h4>${p.state && p.column !== 'todo' ? `<small class="kanban-why">${e(p.state)}</small>` : ''}</article>`;
}
function requestCard(r) {
  return `<article class="kanban-card clickable" role="button" tabindex="0" data-request="${e(r.id)}" aria-label="${e(r.title)}"><div class="kanban-card-head"><span class="request-id">${e(r.id)}</span>${r.risk === 'renforce' ? '<span class="tag prod">Renforcée</span>' : ''}</div><h4>${e(r.title)}</h4><small>${r.source?.kind === 'email' ? 'Email' + (r.source.sender ? ' · ' + e(r.source.sender.replace(/<[^>]+>/, '').trim()) : '') : 'Demande locale'}${r.updated ? ' · ' + e(ago(r.updated)) : ''}</small>${r.status === 'bloquee' && r.blocked_reason ? `<small class="kanban-why">${e(r.blocked_reason)}</small>` : ''}</article>`;
}
async function renderMemory(body, stillHere) {
  body.innerHTML = '<div id="memory-doc"></div><div id="journal-doc" class="section"></div><div id="memory-notes" class="section"></div>';
  await showDocument('memory', $('#memory-doc'));
  if (!stillHere()) return;
  await showDocument('journal', $('#journal-doc'));
  const notes = await rpc('memory.notes', { project: state.project });
  if (!stillHere() || !$('#memory-notes')) return;
  $('#memory-notes').innerHTML = `<div class="section-title"><h2>Notes et sources</h2><button class="secondary small" data-action="memory-note">${icon('plus')}Proposer une note</button></div><p class="hint">L’index reste court. Les faits détaillés sont datés et reliés à leur source ; leur promotion reste explicite.</p>` + (notes.length ? notes.map(n => `<article class="card source-item"><div class="row between"><h3>${e(n.title)}</h3><span class="badge ${n.status === 'confirmee' && n.fresh ? 'terminee' : 'attente-validation'}">${!n.fresh ? 'Source modifiée' : e(n.status)}</span></div><p class="source-preview">${e(n.body)}</p><small>${e(n.source)} · ${e(n.created)}</small>${n.status === 'proposee' && n.fresh && n.kind !== 'hypothese' ? `<div class="section"><button class="secondary small" data-memory-confirm="${e(n.id)}">Confirmer et ajouter à l’index…</button></div>` : ''}</article>`).join('') : '<p class="muted">Aucune note proposée.</p>');
}

async function showDocument(kind, target) {
  const doc = await rpc('document.get', { project: state.project, kind, release: state.release });
  const editable = !doc.readonly && ['memory', 'journal', 'plan', 'qa'].includes(kind);
  target.innerHTML = `<section class="card doc-card" data-doc-kind="${e(kind)}"><div class="doc-bar"><small>${icon('file')}${e(doc.path)}</small>${editable ? `<button class="secondary small" data-action="edit-document">${icon('edit')}Modifier</button>` : '<span class="tag">Lecture seule</span>'}</div><div class="doc-body md">${doc.body.trim() ? markdown(doc.body) : '<p class="muted">Aucun contenu pour ce document.</p>'}</div></section>`;
  target.querySelector('.doc-card').documentData = { ...doc, kind };
}
function editDocument(card) {
  const doc = card.documentData;
  card.innerHTML = `<div class="doc-bar"><small>${icon('edit')}${e(doc.path)} · édition</small><div class="row"><button class="ghost small" data-action="cancel-document">Annuler</button><button class="small" data-action="save-document" title="Ctrl+S">${icon('check')}Enregistrer</button></div></div><textarea id="document-editor" class="editor" aria-label="Contenu du document" spellcheck="true">${e(doc.body)}</textarea>`;
  const editor = $('#document-editor', card);
  Object.assign(editor.dataset, { original: doc.body, revision: doc.revision, kind: doc.kind });
  editor.focus(); editor.setSelectionRange(0, 0);
}
async function saveDocument() {
  const editor = $('#document-editor'); if (!editor) return;
  const result = await rpc('document.save', { project: state.project, kind: editor.dataset.kind, release: state.release, body: editor.value, revision: editor.dataset.revision });
  editor.dataset.original = editor.value;
  await showDocument(editor.dataset.kind, editor.closest('.doc-card').parentElement);
  toast('Document enregistré dans le dépôt.');
  return result;
}

/* ---------------------------------------------------------------- request */
async function renderRequest(seq = state.renderSeq) {
  const record = await rpc('request.get', { project: state.project, request: state.request });
  if (seq !== state.renderSeq) return;
  state.record = record;
  const index = stages.indexOf(record.stage);
  const job = state.snapshot.jobs.find(j => j.project === state.project && j.request === record.id);
  const project = state.detail.project;
  setCrumbs([{ label: 'Projets', patch: { view: 'projects' } }, { label: project.name, patch: { view: 'project', request: null, tab: 'overview' } }, { label: releaseName({ title: record.release_title }), patch: { view: 'project', request: null, tab: 'requests', release: record.release } }, { label: record.title }]);
  let next;
  if (record.status === 'bloquee') next = `<p class="error">${e(record.blocked_reason)}</p><div class="actions"><button data-action="resume">Reprendre…</button></div>`;
  else if (['nouvelle', 'analyse'].includes(record.stage)) next = `<p class="hint">${providerName(state.snapshot.settings.providers?.analysis)} lit le contexte et propose les critères et le plan. Aucun code modifié.</p>${job?.status === 'running' ? `<p class="loading">Analyse ${providerName(job.provider)} en cours…</p>` : ''}<div class="actions"><button data-action="analyze" ${job?.status === 'running' ? 'disabled' : ''}>${job?.status === 'running' ? 'Analyse en cours…' : 'Lancer l’analyse'}</button><button class="secondary" data-action="manual-plan">Saisir un plan</button></div>`;
  else if (record.stage === 'plan') next = `<p class="hint">Le plan attend votre décision. L’approbation autorise son périmètre local.</p><div class="actions"><button data-action="approve-plan">Approuver le plan…</button><button class="secondary" data-action="manual-plan">Modifier la proposition…</button><button class="secondary" data-action="block">Demander une révision…</button></div>`;
  else if (record.stage === 'realisation') next = `<p class="hint">Réalisez le périmètre approuvé, puis conservez les preuves des contrôles.</p><div class="actions"><button data-action="request-terminal" aria-haspopup="menu">${icon('terminal')}Ouvrir un terminal…</button><button class="secondary" data-action="verify">Remettre pour vérification…</button></div>`;
  else if (record.stage === 'verification') next = `<p class="hint">Examinez le résultat, les contrôles et les preuves avant réception.</p><div class="actions"><button data-action="receive">Réceptionner…</button><button class="secondary" data-action="block">Signaler un défaut…</button></div>`;
  else next = `<p class="hint">Demande reçue. La clôture de release et la livraison sont suivies séparément.</p><div class="actions"><button class="secondary" data-action="reopen">Réexaminer la réception…</button></div>`;
  const facts = [['Release', record.release_title], ['Contrôle', record.risk === 'renforce' ? 'Revue renforcée' : 'Ordinaire'], ['Source', record.source?.kind ? `${record.source.kind}${record.source.sender ? ' · ' + record.source.sender : ''}` : 'Demande locale'], ['Créée', record.created ? ago(record.created) : '—'], ['Modifiée', record.updated ? ago(record.updated) : '—'], ...(record.depends_on?.length ? [['Dépend de', record.depends_on.join(', ')]] : [])];
  const plan = record.plan_proposal && ['plan', 'realisation'].includes(record.stage) ? `<section class="card"><div class="row between"><h3>${record.stage === 'plan' ? 'Plan proposé · à décider' : 'Plan approuvé'}</h3>${record.stage === 'plan' ? '<span class="badge attente-validation">Décision attendue</span>' : '<span class="badge terminee">Approuvé</span>'}</div><div class="md compact section">${markdown(record.plan_proposal)}</div></section>` : '';
  page(`<button class="back" data-action="back-release">${icon('arrow-left')}Demandes de la release</button>
    <div class="page-head"><div><div class="eyebrow"><span class="request-id">${e(record.id)}</span>${record.risk === 'renforce' ? '<span class="tag prod">Revue renforcée</span>' : ''}</div><h1>${e(record.title)}</h1></div>${badge(record)}</div>
    <div class="stepper" aria-label="Étapes">${stages.map((s, i) => `<div class="${i === index ? 'current' : i < index ? 'past' : ''}" ${i === index ? 'aria-current="step"' : ''}>${i + 1}. ${stageNames[s]}</div>`).join('')}</div>
    <div class="request-detail"><div class="stack">${plan}<article class="card"><div class="md">${markdown(record.body.replace(/^# [^\n]+\n*/, ''))}</div></article></div>
    <aside class="request-aside"><section class="block"><h3>Prochaine action</h3>${next}${job?.status === 'failed' || job?.status === 'interrupted' ? `<p class="error">${e(job.error)}</p>` : ''}</section>
    <section class="block"><h3>Travail</h3><div class="actions"><button class="secondary" data-action="request-terminal" aria-haspopup="menu">${icon('terminal')}Ouvrir un terminal…</button><button class="secondary" data-action="add-proof">${icon('file')}Ajouter une preuve</button>${record.status !== 'terminee' && record.status !== 'bloquee' ? '<button class="ghost" data-action="block">Signaler un blocage…</button>' : ''}</div><dl class="facts">${facts.map(([k, v]) => `<dt>${e(k)}</dt><dd>${e(v)}</dd>`).join('')}</dl></section></aside></div>`);
}

/* ---------------------------------------------------------------- other views */
function renderSettings() {
  const settings = state.snapshot.settings;
  page(`<div class="page-head"><div><div class="eyebrow">Votre configuration</div><h1>Paramètres</h1><p>Choisissez les fournisseurs et les dossiers de travail.</p></div></div><form id="settings-form" class="config-layout"><div class="settings-grid">${providerSettingsHTML(settings)}<section class="card full config-card"><div><h2>Découverte des projets</h2><p class="hint">Workbench recherche les dépôts Git dans les dossiers indiqués.</p></div><div class="config-field">${area('roots', 'Dossiers à parcourir · un chemin par ligne', settings.roots.join('\n'), 'placeholder="/home/vous/Projets"')}</div><div class="config-field">${select('depth', 'Profondeur de découverte', [0, 1, 2, 3, 4].map(n => [String(n), n === 0 ? 'Dépôts à la racine uniquement' : `${n} niveau${n > 1 ? 'x' : ''} de sous-dossiers`]), String(settings.depth))}<p class="field-hint">La profondeur compte les sous-dossiers explorés à partir de chaque racine.</p></div></section>
${workflowSettingsHTML(settings, state.snapshot.workflow)}</div>
    <div class="form-actions"><button type="submit">${icon('check')}Enregistrer les paramètres</button></div></form>`, true);
  $('#settings-form').addEventListener('submit', async event => {
    event.preventDefault(); const form = new FormData(event.currentTarget);
    try {
      await rpc('settings.save', { settings: { ...settings, workflow_home: form.get('workflow-home'), providers: { sources: form.get('source-provider'), analysis: form.get('analysis-provider') }, source_sync: { enabled: form.has('source-auto-sync') }, roots: String(form.get('roots')).split('\n').map(s => s.trim()).filter(Boolean), depth: Number(form.get('depth')) } });
      toast('Paramètres enregistrés.'); await snapshot();
    } catch (error) { toast(error.message, true); }
  });
}
function renderLibrary() {
  const entries = state.snapshot.settings.library;
  page(`<div class="page-head"><div><div class="eyebrow">Connaissances partagées</div><h1>Bibliothèque</h1><p>Sources Odoo et documents métier, consultés en lecture seule.</p></div><button data-action="library-add">${icon('plus')}Ajouter un dossier</button></div><form id="library-search" class="library-form"><div class="search-field" style="flex:1;max-width:none;margin:0">${icon('search')}<input name="query" aria-label="Rechercher dans la bibliothèque" placeholder="Une règle, un modèle Odoo, une procédure…" required minlength="2"></div><button>Rechercher</button></form><div id="library-results"></div><div class="section-title"><h2>Sources</h2></div><div class="grid-2">${entries.map(entry => `<div class="card"><div class="row between"><span class="tag">${e(entry.category || 'Documents')}</span><small>Lecture seule</small></div><h3 class="section">${e(entry.name)}</h3><p class="hint" style="overflow-wrap:anywhere">${e(entry.path)}</p><button class="secondary small" data-library-index="${e(entry.id)}">${icon('refresh')}Indexer PDF / Word</button></div>`).join('') || '<p class="muted">Aucune source. Ajoutez un dossier documentaire.</p>'}</div>`);
  $('#library-search').addEventListener('submit', async event => {
    event.preventDefault(); const query = new FormData(event.currentTarget).get('query'); $('#library-results').innerHTML = '<p class="loading">Recherche en cours…</p>';
    try { const result = await rpc('library.search', { query }); const rows = [...result.items, ...(result.documents ?? [])]; $('#library-results').innerHTML = `<p class="hint">${rows.length} résultat(s) · ${e(result.coverage)}</p>` + (rows.length ? `<section class="panel">${rows.map(r => `<div class="library-result"><span class="tag">${e(r.entry)}</span> <small>${e(r.path)}${r.line ? ':' + r.line : ''}</small><pre>${e(r.text)}</pre></div>`).join('')}</section>` : ''); }
    catch (error) { $('#library-results').textContent = error.message; }
  });
}
function renderConnections() {
  const google = state.snapshot.google;
  page(connectionsHTML(state.snapshot) + `<div class="settings-grid section"><details class="card full config-card"><summary>Options avancées · connexion Google indépendante</summary><p>OpenClaw fournit la skill Google <strong>gog</strong>. Cette option nécessite un client OAuth Google de bureau. Elle sert à relever les sources indépendamment de Codex et Claude Code. Les règles de classement peuvent créer des demandes automatiquement.</p><div class="setup-step-links"><a href="https://github.com/openclaw/gogcli/blob/main/docs/quickstart.md" target="_blank" rel="noreferrer">Intégration native gog ↗</a><a href="https://console.cloud.google.com/auth/clients" target="_blank" rel="noreferrer">Clients OAuth Google ↗</a></div><p class="hint">Activer Gmail API et Google Calendar API, créer un client de type Application de bureau et télécharger son JSON. Aucun mot de passe ou token n’est à coller dans une conversation.</p><label for="google-client">Client OAuth Google de bureau (.json)</label><input id="google-client" type="file" accept=".json,application/json"><div class="row section"><button data-action="google-connect" ${google.configured ? '' : 'disabled'}>Connecter Google</button><button class="secondary" data-action="sync-google" ${google.connected ? '' : 'disabled'}>Relever les sources</button></div><div id="google-authorization-link"></div>${google.last_error ? `<p class="error">${e(google.last_error)}</p>` : ''}</details></div>`);
  $('#google-client').addEventListener('change', async event => { try { const client = JSON.parse(await event.target.files[0].text()); await rpc('google.client', { client }); toast('Client OAuth enregistré localement.'); await snapshot(); renderConnections(); } catch (error) { toast(error.message, true); } });
}

/* ---------------------------------------------------------------- terminals
   Panel per scope: 'open' (full), 'min' (a slim bar with the tabs) or 'hidden'. */
const WORKSPACE = '__workspace__';
function terminalScope() { return state.view === 'project' ? state.project : WORKSPACE; }
function scopedTerminals() { return [...state.terminals].filter(([, t]) => t.session.project === terminalScope()); }
const liveTerminals = () => scopedTerminals().filter(([, t]) => t.session.exit_code === null);
const panelMode = () => $('#terminal-panel').hidden ? 'hidden' : $('#terminal-panel').classList.contains('minimized') ? 'min' : 'open';
function updateTerminalCount() {
  const live = state.snapshot ? state.snapshot.terminals.filter(t => t.exit_code === null && t.project === terminalScope()).length : 0;
  $('#terminal-count').textContent = live || ''; $('#terminal-count').toggleAttribute('data-zero', !live);
  $('#terminal-toggle').setAttribute('aria-pressed', String(panelMode() === 'open'));
}
function setPanel(mode, remember = true) {
  const panel = $('#terminal-panel');
  panel.hidden = mode === 'hidden';
  panel.classList.toggle('minimized', mode === 'min');
  if (mode !== 'open') panel.classList.remove('maximized');
  if (remember) state.panel[terminalScope()] = mode;
  $('#terminal-hide').setAttribute('aria-label', mode === 'min' ? 'Déployer le terminal' : 'Réduire le terminal');
  $('#terminal-hide').innerHTML = icon(mode === 'min' ? 'chevron-up' : 'chevron-down');
  updateTerminalCount();
  if (mode === 'open') { const t = state.terminals.get(state.selectedTerminal); if (t) requestAnimationFrame(() => { t.fit.fit(); }); }
}
async function openTerminalChooser(anchor, { environment = null, request = null } = {}) {
  const scopeName = projectById(terminalScope())?.name ?? 'Espace général';
  const env = environment ? state.detail?.environments.find(x => x.id === environment)?.name : '';
  const kind = await chooseAgent(anchor, { context: env ? `${scopeName} · ${env}` : scopeName });
  if (kind) await newTerminal(kind, request, true, environment);
}
async function newTerminal(kind = 'shell', request = null, focus = true, environment = null) {
  const project = terminalScope();
  const session = await rpc('terminal.open', { project, kind, request, environment });
  await attachTerminal(session, focus);
  state.snapshot?.terminals.push(session);
  setPanel('open');
  renderProjectShortcuts();
}
async function syncTerminalScope() {
  const scope = terminalScope(), sessions = scopedTerminals(), live = liveTerminals();
  const id = sessions.some(([tid]) => tid === state.lastTerminals[scope]) ? state.lastTerminals[scope] : live[0]?.[0] ?? sessions[0]?.[0];
  selectTerminal(id, false);
  // A project with sessions shows at least its slim bar, so they are never forgotten.
  const remembered = state.panel[scope];
  setPanel(!id ? 'hidden' : remembered && remembered !== 'hidden' ? remembered : scope === WORKSPACE ? 'hidden' : 'min', false);
}
async function attachTerminal(session, focus = false) {
  if (!state.terminals.has(session.id)) {
    const container = document.createElement('div'); container.className = 'terminal-view'; container.dataset.id = session.id; $('#terminal-views').append(container);
    const terminal = new window.Terminal({ fontFamily: 'ui-monospace, "SFMono-Regular", "JetBrains Mono", Menlo, monospace', fontSize: 12.5, lineHeight: 1.2, cursorBlink: true, cursorStyle: 'bar', scrollback: 8000, allowProposedApi: false,
      theme: { background: '#1c2026', foreground: '#d8dee6', cursor: '#ff8a3d', cursorAccent: '#1c2026', selectionBackground: '#ff660040',
        black: '#2a3038', red: '#ef6b73', green: '#8fcf8a', yellow: '#e8c06a', blue: '#6cb4ee', magenta: '#c792ea', cyan: '#5fc7c0', white: '#c9d1d9',
        brightBlack: '#5c6773', brightRed: '#ff8a91', brightGreen: '#a6e3a1', brightYellow: '#f5d48a', brightBlue: '#8ccaf7', brightMagenta: '#dab2f3', brightCyan: '#7fdcd4', brightWhite: '#f0f3f6' } });
    const fit = new window.FitAddon.FitAddon(); terminal.loadAddon(fit); terminal.open(container);
    const record = { session, terminal, fit, container, cursor: 0, unread: false, input: Promise.resolve() };
    state.terminals.set(session.id, record);
    terminal.onData(data => { record.input = record.input.then(() => rpc('terminal.write', { id: session.id, data })).catch(error => toast(error.message, true)); });
    terminal.onResize(({ rows, cols }) => rpc('terminal.resize', { id: session.id, rows, cols }).catch(() => {}));
  }
  if (session.project === terminalScope()) selectTerminal(session.id, focus);
  else state.terminals.get(session.id).container.hidden = true;
}
function paintTerminalTabs() {
  const id = state.selectedTerminal, counters = {};
  $('#terminal-scope').textContent = projectById(terminalScope())?.name ?? 'Espace général';
  $('#terminal-tabs').innerHTML = scopedTerminals().map(([tid, r]) => {
    const kind = r.session.kind; counters[kind] = (counters[kind] ?? 0) + 1;
    const base = kind === 'shell' ? `Shell ${counters[kind]}` : `${terminalLabel(kind)}${counters[kind] > 1 ? ' ' + counters[kind] : ''}`;
    const label = `${base}${r.session.environment_name ? ' · ' + r.session.environment_name : ''}`;
    const stopped = r.session.exit_code !== null;
    return `<span class="term-tab${tid === id ? ' selected' : ''}${stopped ? ' stopped' : ''}"><button role="tab" aria-selected="${tid === id}" data-terminal="${e(tid)}" title="${e(r.session.title)}${stopped ? ' · arrêté' : ''}">${agentLogo(kind, 'sm')}<span>${e(label)}${stopped ? ' · arrêté' : ''}</span>${r.unread && tid !== id ? '<i class="unread" title="Nouvelle sortie"></i>' : ''}</button><button class="close" aria-label="Fermer ${e(r.session.title)}" title="Fermer" data-terminal-close="${e(tid)}">${icon('x')}</button></span>`;
  }).join('');
}
function selectTerminal(id, focus = true) {
  const scope = terminalScope();
  state.selectedTerminal = id;
  if (id) { state.lastTerminals[scope] = id; const record = state.terminals.get(id); if (record) record.unread = false; }
  for (const [tid, record] of state.terminals) record.container.hidden = tid !== id;
  paintTerminalTabs();
  if (focus && id && panelMode() !== 'open') setPanel('open');
  const selected = state.terminals.get(id);
  if (selected && panelMode() === 'open') requestAnimationFrame(() => { selected.fit.fit(); if (focus) selected.terminal.focus(); });
}
async function closeTerminal(id) {
  const record = state.terminals.get(id); if (!record) return;
  if (record.session.exit_code === null) {
    const ok = await confirmDialog('Fermer ce terminal', `<p>Le processus <strong>${e(record.session.title)}</strong> et ses commandes en cours seront arrêtés. Les fichiers du projet restent inchangés.</p>`, 'Arrêter et fermer', { danger: true });
    if (!ok) return;
    try { await rpc('terminal.close', { id }); } catch (error) { if (!/absent|terminé/.test(error.message)) throw error; }
  }
  record.terminal.dispose(); record.container.remove(); state.terminals.delete(id);
  if (state.snapshot) state.snapshot.terminals = state.snapshot.terminals.filter(t => t.id !== id);
  const remaining = scopedTerminals();
  selectTerminal(remaining.at(-1)?.[0], false);
  if (!remaining.length) setPanel('hidden');
  renderProjectShortcuts(); updateTerminalCount();
}
async function toggleTerminalPanel(anchor = $('#terminal-toggle')) {
  if (!scopedTerminals().length) return openTerminalChooser(anchor);
  setPanel(panelMode() === 'open' ? 'min' : 'open');
  if (panelMode() === 'open') state.terminals.get(state.selectedTerminal)?.terminal.focus();
}
const panelHeight = value => { const h = Math.round(Math.max(140, Math.min(innerHeight * .85, value))); $('#terminal-panel').style.height = h + 'px'; prefs.set('terminalHeight', h); };
$('#terminal-panel').style.height = (prefs.get('terminalHeight') || 280) + 'px';
$('#terminal-new').onclick = event => openTerminalChooser(event.currentTarget).catch(error => toast(error.message, true));
$('#terminal-hide').onclick = () => setPanel(panelMode() === 'min' ? 'open' : 'min');
$('#terminal-toolbar').onclick = event => { if (panelMode() === 'min' && event.target.isConnected && !event.target.closest('button')) setPanel('open'); };
$('#terminal-toolbar').ondblclick = event => { if (event.target.isConnected && !event.target.closest('button')) setPanel(panelMode() === 'min' ? 'open' : 'min'); };
$('#terminal-max').onclick = () => {
  if (panelMode() !== 'open') setPanel('open');
  const max = $('#terminal-panel').classList.toggle('maximized');
  $('#terminal-max').innerHTML = icon(max ? 'minimize' : 'maximize');
  $('#terminal-max').setAttribute('aria-label', max ? 'Rétablir la taille du terminal' : 'Agrandir le terminal');
};
$('#terminal-toggle').onclick = event => Promise.resolve(toggleTerminalPanel(event.currentTarget)).catch(error => toast(error.message, true));
$('#terminal-resizer').onpointerdown = event => {
  const start = event.clientY, height = panelMode() === 'open' ? $('#terminal-panel').offsetHeight : 140;
  if (panelMode() !== 'open') setPanel('open');
  $('#terminal-panel').classList.remove('maximized');
  event.target.setPointerCapture(event.pointerId);
  event.target.onpointermove = move => panelHeight(height + start - move.clientY);
  event.target.onpointerup = () => { event.target.onpointermove = null; };
};
$('#terminal-resizer').onkeydown = event => { if (['ArrowUp', 'ArrowDown'].includes(event.key)) { event.preventDefault(); if (panelMode() !== 'open') setPanel('open'); panelHeight($('#terminal-panel').offsetHeight + (event.key === 'ArrowUp' ? 30 : -30)); } };
new ResizeObserver(() => { const t = state.terminals.get(state.selectedTerminal); if (t && panelMode() === 'open') requestAnimationFrame(() => t.fit.fit()); }).observe($('#terminal-panel'));

let terminalPolling = false, batchOutputs = true;
setInterval(async () => {
  if (terminalPolling || panelMode() === 'hidden' || document.hidden) return;
  const scoped = scopedTerminals().filter(([, t]) => t.session.exit_code === null || t.cursor === 0);
  if (!scoped.length) return;
  terminalPolling = true;
  try {
    const cursors = Object.fromEntries(scoped.map(([id, t]) => [id, t.cursor]));
    let result;
    if (batchOutputs) {
      try { result = await rpc('terminal.outputs', { cursors }); }
      catch (error) { if (!/redémarrage|Commande inconnue/.test(error.message)) throw error; batchOutputs = false; }
    }
    if (!result) {
      // Service started before 0.4: read sessions one by one until it is restarted.
      result = {};
      for (const [id, cursor] of Object.entries(cursors)) {
        try { result[id] = await rpc('terminal.output', { id, cursor }); } catch { result[id] = { missing: true }; }
      }
    }
    let changed = false;
    for (const [id, out] of Object.entries(result)) {
      const t = state.terminals.get(id); if (!t) continue;
      if (out.missing) { if (t.session.exit_code === null) { t.session.exit_code = -1; t.terminal.write('\r\n\x1b[2m[Session terminée : service redémarré]\x1b[0m\r\n'); changed = true; } continue; }
      if (out.text && t.cursor > 0 && (id !== state.selectedTerminal || panelMode() !== 'open') && !t.unread) { t.unread = true; changed = true; }
      t.cursor = out.cursor;
      if (out.truncated) t.terminal.write('\r\n\x1b[2m[Historique ancien tronqué]\x1b[0m\r\n');
      if (out.text) t.terminal.write(out.text);
      if (t.session.exit_code !== out.exit_code) { t.session.exit_code = out.exit_code; changed = true; }
    }
    if (changed) paintTerminalTabs();
  } catch { /* transient: next tick retries */ }
  finally { terminalPolling = false; }
}, 250);

/* ---------------------------------------------------------------- actions */
async function transition(action, note, extra = {}) {
  await rpc('request.transition', { project: state.project, request: state.request, revision: state.record.revision, action, note, ...extra });
  closeModal(); await snapshot(); await renderRequest(); refreshDashboardData(true);
}
function mailTerminal(projectId) {
  const project = projectById(projectId);
  if (project) return `<button type="button" class="small" data-mail-terminal="${e(project.id)}" aria-haspopup="menu">${icon('terminal')}Ouvrir un terminal dans ${e(project.name)}</button>`;
  return `<button type="button" class="secondary small" data-mail-terminal="" aria-haspopup="menu" disabled title="Choisissez le projet de destination ci-dessous">${icon('terminal')}Ouvrir un terminal</button>`;
}
async function terminalFromMail(projectId) {
  const project = projectId || $('#mail-release-project')?.value;
  if (!project) { $('#mail-release-project')?.focus(); toast('Choisissez d’abord le projet de cet email.', true); return; }
  closeModal();
  await openProject(project);
  await openTerminalChooser($('[data-action="show-project-terminal"]'));
}
async function paintMailRelease(mail, projectId) {
  const target = $('#email-release'); if (!target) return;
  const projects = state.snapshot.projects;
  const pick = projectId || '';
  target.innerHTML = `<div class="email-import-head"><h3>${icon('layers', 'sm')}Transformer cet email en travail à suivre</h3><p class="hint">Choisissez le projet et la release de destination. Le message complet sera récupéré à la validation.</p></div><div class="config-field"><label for="mail-release-project">1. Projet de destination</label><select id="mail-release-project"><option value="">Choisir un projet…</option>${projects.map(p => `<option value="${e(p.id)}" ${p.id === pick ? 'selected' : ''}>${e(p.name)}</option>`).join('')}</select></div><div id="mail-release-target"></div><p id="email-import-error" class="error" role="alert"></p>`;
  const update = async () => {
    const project = $('#mail-release-project')?.value, slot = $('#mail-release-target'); if (!slot) return;
    const terminal = $('[data-mail-terminal]');
    if (terminal) { const selected = projectById(project); terminal.disabled = !selected; terminal.dataset.mailTerminal = project || ''; terminal.innerHTML = `${icon('terminal')}Ouvrir un terminal${selected ? ' dans ' + e(selected.name) : ''}`; }
    if (!project) { slot.innerHTML = '<p class="field-hint">Sélectionnez le projet pour afficher ses releases ouvertes.</p>'; return; }
    slot.innerHTML = '<span class="loading">Releases du projet…</span>';
    const detail = await rpc('project.get', { project });
    if (!slot.isConnected || $('#mail-release-project')?.value !== project) return;
    const open = detail.releases.filter(r => r.status === 'ouverte');
    slot.innerHTML = open.length
      ? `<div class="config-field"><label for="mail-release">2. Release ouverte</label><select id="mail-release">${open.length > 1 ? '<option value="">Choisir une release…</option>' : ''}${open.map(r => `<option value="${e(r.id)}">${e(releaseName(r))}</option>`).join('')}</select></div><div id="mail-import-action"></div>`
      : `<span class="muted">Aucune release ouverte dans ce projet.</span><button type="button" class="secondary small" data-mail-new-release="${e(mail.external_id)}">${icon('plus')}Ouvrir une release…</button>`;
    const action = () => {
      const chosen = open.find(r => r.id === $('#mail-release')?.value), panel = $('#mail-import-action');
      if (!panel) return;
      if (!chosen) { panel.innerHTML = '<p class="field-hint">Choisissez la release qui recevra cet email.</p>'; return; }
      panel.innerHTML = `${chosen.legacy ? '<p class="notice info">L’email sera ajouté à la demande de cette release Odoo. Les tâches de son plan restent gérées dans le projet.</p>' : `<div class="config-field"><label for="mail-task-title">3. Titre de la tâche</label><input id="mail-task-title" value="${e(mail.title || 'Email reçu')}" maxlength="220" required><p class="field-hint">Une nouvelle demande à analyser sera créée avec le contenu complet de l’email.</p></div>`}<p class="mail-destination">Destination : <strong>${e(detail.project.name)}</strong> · ${e(releaseName(chosen))}</p><button type="button" data-mail-release="${e(mail.external_id)}">${icon('plus')}${chosen.legacy ? 'Ajouter l’email à la demande' : 'Créer une tâche depuis cet email'}</button>`;
    };
    $('#mail-release')?.addEventListener('change', action);
    action();
  };
  const failed = error => { const panel = $('#email-import-error'); if (panel) panel.textContent = error.message; };
  $('#mail-release-project').addEventListener('change', () => { $('#email-import-error').textContent = ''; void update().catch(failed); });
  await update().catch(failed);
}
async function mailToRelease(messageId, release) {
  const project = $('#mail-release-project')?.value; release ??= $('#mail-release')?.value;
  if (!project || !release) return;
  const title = $('#mail-task-title')?.value.trim();
  if ($('#mail-task-title') && !title) { $('#mail-task-title').reportValidity(); return; }
  const button = $(`[data-mail-release="${CSS.escape(messageId)}"]`), original = button?.innerHTML;
  if (button) { button.disabled = true; button.innerHTML = '<span class="loading">Récupération de l’email complet…</span>'; }
  try {
    const result = await rpc('mail.to_release', { project, release, message: messageId, title });
    closeModal();
    toast(result.added === false ? 'Cet email est déjà enregistré. Ouverture de son suivi.' : result.request ? 'Tâche créée avec l’email complet. Elle est prête à être analysée.' : 'Email ajouté à la demande de la release.');
    await snapshot(); await openProject(project, { release: result.release || release, tab: 'requests', request: result.request || null });
  } catch (error) { const panel = $('#email-import-error'); if (panel) panel.textContent = error.message; else throw error;
  } finally { if (button?.isConnected) { button.disabled = false; button.innerHTML = original; } }
}
function readMail(id, project) {
  return (project ? rpc('project.get', { project }).then(d => d.email_sources) : rpc('dashboard.get')).then(d => d.emails.find(m => m.external_id === id));
}
async function loadMailReview(message, force = false) {
  const panel = $('#email-review');
  if (!panel) return;
  const current = () => panel.isConnected && $('#modal').open;
  const status = panel.querySelector('.email-review-status');
  const button = panel.querySelector('[data-action="mail-reanalyze"]');
  button.disabled = true;
  status.classList.remove('error');
  status.textContent = force ? 'Nouvelle analyse en cours…' : 'Lecture de l’analyse enregistrée…';
  try {
    let review;
    do {
      review = await rpc('email.review', { message, force }); force = false;
      if (!current()) return;
      panel.dataset.status = review.status;
      panel.dataset.attempt = review.attempt_id;
      for (const key of ['request_summary', 'proposal']) {
        const block = panel.querySelector(`[data-review-block="${key}"]`);
        if (review[key]) { block.innerHTML = markdown(review[key]); block.classList.remove('muted'); }
        else block.textContent = review.status === 'running' ? 'Analyse du message complet en cours…' : 'Analyse indisponible.';
      }
      const saved = review.analyzed ? `Analyse conservée · ${new Date(review.analyzed).toLocaleString('fr-CH')} · ${{ codex: 'Codex', claude: 'Claude Code' }[review.provider] || review.provider}` : '';
      status.textContent = review.status === 'running' ? 'Analyse du message complet en cours… Vous pouvez fermer cette fenêtre.'
        : review.status === 'failed' ? `${saved ? saved + '. ' : ''}${review.error} Cliquez sur Réanalyser pour réessayer.`
        : `${saved}. Elle reste identique à chaque ouverture, sauf réanalyse demandée.`;
      status.classList.toggle('error', review.status === 'failed');
      if (review.status === 'running') await new Promise(resolve => setTimeout(resolve, 1200));
    } while (review.status === 'running' && current());
  } catch (error) {
    if (current()) { status.textContent = `${error.message} Cliquez sur Réanalyser pour réessayer.`; status.classList.add('error'); }
  } finally { if (current()) button.disabled = false; }
}
const actions = {
  'mail-reanalyze': target => loadMailReview(target.dataset.message, true),
  'refresh-codex': async target => {
    const buttons = $$('[data-action="refresh-codex"]');
    buttons.forEach(button => { button.disabled = true; });
    if (target) target.innerHTML = '<span class="loading">Lecture Gmail et agenda…</span>';
    try { const result = await rpc('sources.refresh'); toast(`${result.emails} emails et ${result.events} événements actualisés.`); await snapshot(); await render(); }
    finally { buttons.forEach(button => { if (button.isConnected) button.disabled = false; }); }
  },
  'mail-preview': async target => {
    const original = target.innerHTML;
    const body = $('#modal-body .email-body'), note = $('#modal-body .email-toolbar > small');
    target.disabled = true; target.textContent = 'Lecture du message complet…';
    try { const result = await rpc('mail.preview', { message: target.dataset.message }); if (body?.isConnected && target.isConnected) { body.textContent = result.body || 'Ce message ne contient pas de texte.'; target.textContent = 'Message complet affiché'; if (note) note.textContent = 'Message complet chargé depuis Gmail.'; } }
    catch (error) { target.disabled = false; target.innerHTML = original; toast(error.message, true); }
  },
  'refresh-projects': async () => { toast('Découverte des projets en cours…'); await rpc('projects.refresh'); await snapshot(); renderProjects(); toast(`${state.snapshot.projects.length} projets découverts.`); },
  'copy-path': async () => { try { await navigator.clipboard.writeText(state.detail.project.path); toast('Chemin copié.'); } catch { toast('Copie impossible dans ce navigateur.', true); } },
  'toggle-pin': () => {
    const pinned = prefs.togglePin(state.project), button = $('[data-action="toggle-pin"]');
    button?.setAttribute('aria-pressed', String(pinned)); button?.setAttribute('aria-label', pinned ? 'Désépingler le projet' : 'Épingler le projet');
    renderProjectShortcuts(); toast(pinned ? 'Projet épinglé dans la barre latérale.' : 'Projet retiré des épinglés.');
  },
  'refresh-project-emails': () => { const id = state.project; return loadProjectEmails(id, rpc, () => state.view === 'project' && state.project === id && state.tab === 'overview', true); },
  'new-environment': () => {
    const project = state.detail.project;
    modal('Ajouter un environnement', input('name', 'Nom de l’environnement', '', 'required placeholder="Odoo local, Staging client…"') + select('kind', 'Type', [['local', 'Local'], ['test', 'Test'], ['staging', 'Staging'], ['production', 'Production'], ['other', 'Autre']]) + input('url', 'Adresse de l’environnement', '', 'type="url" placeholder="http://localhost:8069"') + input('path', 'Dossier pour les terminaux', project.path, '', 'Les boutons Terminal, Codex et Claude de cet environnement s’ouvriront dans ce dossier.') + input('series', 'Série Odoo · si concerné', '', 'placeholder="19.0"'), async form => {
      await rpc('environment.add', { project: state.project, name: form.get('name'), kind: form.get('kind'), url: form.get('url'), path: form.get('path'), series: form.get('series') }); closeModal(); await snapshot(); await renderProject(); toast('Environnement ajouté au projet.');
    }, 'Ajouter l’environnement');
    $('#field-kind').onchange = event => { if (event.target.value !== 'local' && $('#field-path').value === project.path) $('#field-path').value = ''; else if (event.target.value === 'local' && !$('#field-path').value) $('#field-path').value = project.path; };
  },
  'show-project-terminal': async target => {
    if (liveTerminals().length && panelMode() !== 'open') { setPanel('open'); state.terminals.get(state.selectedTerminal)?.terminal.focus(); return; }
    await openTerminalChooser(target);
  },
  'request-terminal': target => openTerminalChooser(target, { request: state.request }),
  'triage-inbox': async target => {
    target.disabled = true; target.innerHTML = '<span class="loading">Analyse des emails…</span>';
    try { const result = await rpc('email.triage', {}); toast(`${result.actions} email(s) à traiter${result.analyzed ? ` · ${result.analyzed} analysé(s) par Codex` : ' · analyse déjà à jour'}.`); state.mailFilter = result.actions ? state.mailFilter : 'all'; await render(); }
    finally { if (target.isConnected) target.disabled = false; }
  },
  'triage-project': async target => {
    const project = state.project; target.disabled = true; target.innerHTML = '<span class="loading">Analyse…</span>';
    try { const result = await rpc('email.triage', { project }); const panel = $(`[data-project-emails="${project}"]`); if (panel?.emailData) paintProjectEmails(project, { ...panel.emailData, emails: result.emails }); toast(`${result.actions} email(s) à traiter dans ce projet.`); }
    finally { if (target.isConnected) target.disabled = false; }
  },
  'back-release': () => go({ request: null, tab: 'requests' }),
  'new-release': (_, { mail = null } = {}) => {
    const odoo = state.detail?.project?.odoo && state.snapshot?.workflow?.available;
    const open = state.detail?.releases?.find(r => r.legacy && r.status === 'ouverte');
    if (odoo && open) { toast(`Une release est déjà ouverte : ${releaseName(open)}. Clôturez-la avant d’en ouvrir une autre.`, true); return go({ release: open.id, tab: 'requests', request: null }); }
    modal('Ouvrir une release', input('title', 'Titre de la release', '', 'required maxlength="200" placeholder="Ex. Facturation des abonnements"', odoo ? 'Créée par odoo-release.sh dans changelog/ : les agents la reprennent avec /odoo-plan et /odoo-start.' : 'Une release regroupe les demandes d’un même objectif ; son dossier est créé dans memory/releases/.') + (mail ? '<p class="hint">L’email sera versé dans la release dès son ouverture.</p>' : ''), async form => {
      const project = state.project;
      const release = await rpc('release.create', { project, title: form.get('title') });
      if (mail) await rpc('mail.to_release', { project, release: release.id, message: mail });
      closeModal(); await snapshot(); await go({ release: release.id, tab: 'requests', request: null }); toast(mail ? 'Release ouverte, email versé.' : 'Release ouverte.'); refreshDashboardData(true);
    }, 'Ouvrir la release');
  },
  'toggle-demande': async target => {
    const slot = $('#demande-doc'); if (!slot) return;
    slot.hidden = !slot.hidden;
    if (!slot.hidden && !slot.children.length) await showDocument('demande', slot);
    target.innerHTML = `${icon('file')}${slot.hidden ? 'Lire demande.md' : 'Masquer demande.md'}`;
  },
  'new-request': () => modal('Nouvelle demande', input('title', 'Titre', '', 'required maxlength="220" placeholder="Ce qui doit changer, en une phrase"') + area('description', 'Contexte et résultat souhaité', '', 'required placeholder="Qui est concerné, ce qui se passe aujourd’hui, ce qui est attendu…"', 'Ctrl+Entrée pour créer.') + select('risk', 'Niveau de contrôle', [['normal', 'Ordinaire · contrôles ciblés'], ['renforce', 'Droits, finance ou données existantes · revue renforcée']]), async form => {
    const request = await rpc('request.create', { project: state.project, release: state.release, title: form.get('title'), description: form.get('description'), risk: form.get('risk') }); closeModal(); await snapshot(); await go({ request: request.id });
  }, 'Créer la demande'),
  'project-settings': () => {
    const project = state.detail.project; const pref = state.snapshot.settings.projects[project.id] ?? {};
    modal('Réglages du projet', input('name', 'Nom affiché', project.name) + input('emails', 'Adresses client · séparées par des virgules', project.emails.join(', '), 'placeholder="marie@client.ch"') + input('domains', 'Domaines client · séparés par des virgules', project.domains.join(', '), 'placeholder="client.ch"', 'Ces adresses et domaines servent à retrouver tous les échanges du projet.') + input('mail_query', 'Recherche Gmail · facultatif', pref.mail_query ?? '', 'placeholder="Nom du client ou requête Gmail"', 'Remplace le critère automatique si elle est renseignée.'), async form => {
      const settings = structuredClone(state.snapshot.settings); settings.projects[project.id] = { ...pref, name: form.get('name'), emails: String(form.get('emails')).split(',').map(v => v.trim()).filter(Boolean), domains: String(form.get('domains')).split(',').map(v => v.trim().replace(/^@/, '')).filter(Boolean), mail_query: form.get('mail_query') };
      await rpc('settings.save', { settings }); closeModal(); await snapshot(); await renderProject(); toast('Règles du projet enregistrées.');
    });
  },
  'edit-document': (target) => editDocument(target.closest('.doc-card')),
  'cancel-document': async (target) => { const editor = $('#document-editor'); if (editor && editor.value !== editor.dataset.original && !(await confirmLeave())) return; editor.dataset.original = editor.value; await showDocument(editor.dataset.kind, target.closest('.doc-card').parentElement); },
  'save-document': () => saveDocument(),
  analyze: async () => { await rpc('agent.analyze', { project: state.project, request: state.request }); await snapshot(); await renderRequest(); toast('Analyse démarrée avec Codex, en lecture seule.'); },
  'manual-plan': async () => {
    if (state.record.stage === 'nouvelle') await transition('start-analysis', 'Analyse préparée manuellement.');
    modal('Proposition de plan', area('note', 'Analyse, critères et travaux proposés', state.record.plan_proposal ?? '', 'required rows="10"', 'Markdown accepté : titres, listes, cases à cocher.'), form => transition('propose-plan', form.get('note')), 'Proposer le plan', { wide: true });
  },
  'approve-plan': () => modal('Approuver ce plan', `<div class="card md compact">${markdown(state.record.plan_proposal)}</div><p class="hint">Cet accord porte sur ce plan. Une écriture en production devra être autorisée sur son opération exacte.</p>` + area('note', 'Commentaire de décision', 'Plan approuvé.'), form => transition('approve-plan', form.get('note')), 'Approuver ce plan', { wide: true }),
  verify: () => modal('Remettre le résultat', area('note', 'Résultat obtenu et contrôles réalisés', '', 'required'), form => transition('verify', form.get('note')), 'Passer en vérification'),
  block: () => modal('Signaler un blocage', area('note', 'Cause et information ou correction attendue', '', 'required'), form => transition('block', form.get('note')), 'Enregistrer le blocage'),
  resume: () => modal('Reprendre la demande', area('note', 'Comment le blocage est-il résolu ?', '', 'required'), form => transition('resume', form.get('note')), 'Reprendre'),
  receive: async () => {
    const proofs = await rpc('proof.list', { project: state.project, release: state.release }).catch(() => []);
    modal('Réceptionner la demande', area('note', 'Résultat vérifié et critères couverts', '', 'required') + input('proof', 'Preuve dans la release · ex. preuves/controle.md', proofs.at(-1) ?? '', `required list="proof-options" placeholder="preuves/controle.md"`, proofs.length ? `${proofs.length} preuve(s) disponible(s) dans la release.` : 'Aucune preuve encore : utilisez « Ajouter une preuve ».') + `<datalist id="proof-options">${proofs.map(p => `<option value="${e(p)}">`).join('')}</datalist><label class="checkline"><input name="independent" type="checkbox">La preuve contient une revue indépendante effectivement réalisée</label><p class="hint">Une preuve absente ou modifiée empêche la réception ou la clôture.</p>`, form => transition('receive', form.get('note'), { checks: [{ outcome: 'pass', proof: form.get('proof'), independent: form.has('independent') }] }), 'Confirmer la réception');
  },
  reopen: () => modal('Réexaminer la réception', area('note', 'Cause du réexamen et contrôles à refaire', '', 'required'), form => transition('reopen', form.get('note')), 'Rouvrir la vérification'),
  'add-proof': () => {
    const stamp = new Date().toISOString().slice(0, 16).replace(/[-:T]/g, '').replace(/^(\d{8})/, '$1-');
    modal('Conserver une preuve', input('name', 'Nom du fichier', `controle-${stamp}.md`, 'required pattern="[^/\\\\]+\\.md"', 'Fichier Markdown enregistré dans preuves/ de la release.') + area('body', 'Contrôle réalisé, résultat et limites', '', 'required rows="8"'), async form => { const result = await rpc('proof.save', { project: state.project, release: state.release, name: form.get('name'), body: form.get('body') }); closeModal(); toast('Preuve conservée : ' + result.path); }, 'Conserver la preuve');
  },
  'close-release': () => modal('Clôturer la release', area('note', 'Bilan de recette globale et suite', '', 'required'), async form => { await rpc('release.close', { project: state.project, release: state.release, note: form.get('note') }); closeModal(); await renderProject(); toast('Release clôturée. La livraison reste distincte.'); refreshDashboardData(true); }, 'Clôturer la release'),
  'new-terminal': () => newTerminal(),
  'codex-terminal': () => newTerminal('codex', state.view === 'project' ? state.request : null),
  'claude-terminal': () => newTerminal('claude', state.view === 'project' ? state.request : null),
  'chatgpt-login': () => newTerminal('chatgpt-login'),
  'claude-login': () => newTerminal('claude-login'),
  'check-claude': async target => {
    target.disabled = true; target.textContent = 'Vérification des connexions…';
    try { await rpc('providers.check', { provider: 'claude' }); await snapshot(); renderConnections(); toast('État des connexions Claude mis à jour.'); }
    finally { if (target.isConnected) { target.disabled = false; target.textContent = 'Vérifier les connexions Claude'; } }
  },
  'google-connect': async () => { const popup = window.open('about:blank', '_blank'); try { const result = await rpc('google.connect'); if (popup) { popup.opener = null; popup.location.href = result.url; } else { $('#google-authorization-link').innerHTML = '<p><a href="' + e(result.url) + '" target="_blank" rel="noreferrer">Ouvrir l’autorisation Google →</a></p>'; } toast('Autorisez la lecture dans la fenêtre Google.'); } catch (error) { popup?.close(); throw error; } },
  'sync-google': async () => { toast('Lecture des sources Google en cours…'); const result = await rpc('google.sync'); await snapshot(); if (state.view === 'connections') renderConnections(); toast(`${result.processed} source(s) traitée(s).${result.truncated ? ' Lecture partielle : plafond atteint.' : ''}`); },
  'library-add': () => modal('Ajouter un dossier documentaire', input('name', 'Nom de la source', '', 'required') + input('path', 'Dossier local', '', 'required placeholder="/home/vous/Documents/RH"') + select('category', 'Catégorie', ['Odoo', 'Comptabilité', 'RH', 'Paie', 'Procédures', 'Autres documents'].map(v => [v, v])), async form => { const settings = structuredClone(state.snapshot.settings); settings.library.push({ id: crypto.randomUUID(), name: form.get('name'), path: form.get('path'), category: form.get('category'), readonly: true }); await rpc('settings.save', { settings }); closeModal(); await snapshot(); renderLibrary(); }, 'Ajouter en lecture seule'),
  'memory-note': () => modal('Proposer une note mémoire', input('title', 'Fait ou décision à retrouver', '', 'required') + area('body', 'Note courte et précise', '', 'required') + input('source', 'Document source dans le projet', '', 'required placeholder="memory/releases/.../decisions.md"') + select('kind', 'Nature', [['fact', 'Fait vérifié à proposer'], ['decision', 'Décision documentée'], ['hypothese', 'Hypothèse à conserver comme telle']]), async form => { await rpc('memory.propose', { project: state.project, title: form.get('title'), body: form.get('body'), source: form.get('source'), kind: form.get('kind') }); closeModal(); await renderProject(); }, 'Proposer la note'),
};

/* ---------------------------------------------------------------- palette */
function paletteCommands() {
  const commands = [];
  let order = 0;
  const add = (group, label, iconName, run, extra = {}) => commands.push({ group, label, icon: iconName, run, order: order++, ...extra });
  const project = state.view === 'project' ? state.detail?.project : null;
  if (project) {
    const group = `Projet ${project.name}`;
    const release = state.detail.releases.find(r => r.id === state.release);
    add(group, 'Ouvrir Codex', 'terminal', () => newTerminal('codex', state.request), { keywords: 'terminal' });
    add(group, 'Ouvrir Claude', 'terminal', () => newTerminal('claude', state.request), { keywords: 'terminal' });
    add(group, 'Ouvrir un shell', 'terminal', () => newTerminal('shell', state.request), { keywords: 'terminal bash' });
    if (release && !release.legacy && release.status === 'ouverte') add(group, 'Nouvelle demande', 'plus', () => actions['new-request']());
    add(group, 'Nouvelle release', 'layers', () => actions['new-release']());
    for (const [id, name, iconName] of TABS.slice(1)) add(group, `Afficher : ${name}`, iconName, () => go({ tab: id, request: null }), { quiet: true });
    add(group, prefs.isPinned(project.id) ? 'Désépingler le projet' : 'Épingler le projet', 'star', () => actions['toggle-pin'](), { quiet: true });
    add(group, 'Réglages du projet', 'settings', () => actions['project-settings'](), { quiet: true });
    if (project.github_url) add(group, 'Ouvrir le dépôt GitHub', 'github', () => window.open(project.github_url, '_blank', 'noopener'), { quiet: true });
    add(group, 'Copier le chemin du projet', 'copy', () => actions['copy-path'](), { quiet: true });
  }
  const projects = state.snapshot?.projects ?? [];
  const recent = new Set([...prefs.get('pinned'), ...prefs.get('recent')]);
  for (const p of [...projects].sort((a, b) => Number(recent.has(b.id)) - Number(recent.has(a.id)))) {
    add(recent.has(p.id) ? 'Projets récents et épinglés' : 'Projets', p.name, prefs.isPinned(p.id) ? 'star' : 'folder', () => openProject(p.id), { hint: p.path, keywords: [...(p.domains ?? []), ...(p.emails ?? [])].join(' '), quiet: !recent.has(p.id) || p.id === project?.id });
  }
  for (const [view, iconName] of [['dashboard', 'home'], ['emails', 'mail'], ['agenda', 'calendar'], ['projects', 'folder'], ['library', 'book'], ['connections', 'plug'], ['settings', 'settings']]) add('Aller à', viewNames[view], iconName, () => go({ view, request: null }));
  if (scopedTerminals().length) add('Général', panelMode() === 'open' ? 'Réduire le terminal' : 'Afficher le terminal', 'terminal', () => toggleTerminalPanel());
  add('Général', 'Actualiser mes emails et mon agenda', 'refresh', () => actions['refresh-codex']());
  add('Général', 'Relancer la découverte des projets', 'refresh', () => actions['refresh-projects']().then(() => go({ view: 'projects' })), { quiet: true });
  return commands;
}
const palette = createPalette(paletteCommands);
$('#palette-open').onclick = () => palette.open();

/* ---------------------------------------------------------------- events */
document.addEventListener('click', async event => {
  if (!event.target.closest('details.menu')) $$('details.menu[open]').forEach(menu => menu.removeAttribute('open'));
  const target = event.target.closest('button,[data-project],[data-request],a[data-nav]'); if (!target) return;
  if (target.closest('details.menu') && target.dataset.action) target.closest('details.menu').removeAttribute('open');
  if (target.matches('a[data-nav]')) event.preventDefault();
  try {
    if (target.dataset.mail) {
      const mail = await readMail(target.dataset.mail, target.dataset.mailProject); if (!mail) return;
      let link = ''; try { const url = new URL(mail.url); if (url.protocol === 'https:' && url.hostname === 'mail.google.com') link = `<a class="button-link secondary small" href="${e(url.href)}" target="_blank" rel="noreferrer">Ouvrir dans Gmail${icon('external')}</a>`; } catch {}
      modal(mail.title || 'Sans objet', `<p class="email-head"><strong>${e(mail.sender)}</strong> · ${e(new Date(mail.date).toLocaleString('fr-CH'))}</p>
        <div id="email-review" class="email-review">
          <section class="email-review-block" aria-labelledby="mail-summary-title"><h3 id="mail-summary-title">Résumé de la demande du client</h3><div class="md compact muted" data-review-block="request_summary">Analyse du message complet en cours…</div></section>
          <section class="email-review-block" aria-labelledby="mail-proposal-title"><h3 id="mail-proposal-title">Ma proposition / analyse / solution</h3><div class="md compact muted" data-review-block="proposal">Analyse du message complet en cours…</div></section>
          <div class="email-review-meta"><p class="email-review-status" aria-live="polite"></p><button type="button" class="secondary small" data-action="mail-reanalyze" data-message="${e(mail.external_id)}" disabled>Réanalyser</button></div>
        </div>
        <details class="email-original"><summary>Message original</summary><div class="email-body">${e(mail.body || 'Aucun extrait disponible.')}</div><div class="email-toolbar"><button type="button" class="secondary small" data-action="mail-preview" data-message="${e(mail.external_id)}">Lire le message complet</button>${link}<small>Extrait du dernier relevé. Le bouton de lecture affiche le texte complet.</small></div></details>
        <div class="email-toolbar email-followup">${mailTerminal(target.dataset.mailProject || mail.project)}</div><div class="email-release" id="email-release"></div>`, async () => closeModal(), 'Fermer', { cancel: false, wide: true, secondary: true, email: true });
      void paintMailRelease(mail, target.dataset.mailProject || mail.project);
      void loadMailReview(mail.external_id);
    }
    else if (target.dataset.crumb) { const crumb = state.crumbs[Number(target.dataset.crumb)]; if (crumb?.patch) await go(crumb.patch); }
    else if (target.dataset.pin) { event.stopPropagation(); const pinned = prefs.togglePin(target.dataset.pin); target.setAttribute('aria-pressed', String(pinned)); renderProjectShortcuts(); if (state.view === 'projects') renderProjectRows(); }
    else if (target.dataset.mailTerminal !== undefined) await terminalFromMail(target.dataset.mailTerminal);
    else if (target.dataset.mailRelease) await mailToRelease(target.dataset.mailRelease);
    else if (target.dataset.mailNewRelease) { const project = $('#mail-release-project')?.value, messageId = target.dataset.mailNewRelease; closeModal(); await openProject(project); await actions['new-release'](null, { mail: messageId }); }
    else if (target.dataset.envTerminal) await openTerminalChooser(target, { environment: target.dataset.envTerminal });
    else if (target.dataset.mailFilter) { state.mailFilter = target.dataset.mailFilter; await render(); }
    else if (target.dataset.projectMailFilter) setProjectMailFilter(state.project, target.dataset.projectMailFilter);
    else if (target.dataset.openRequest) await openProject(target.dataset.projectId, { release: target.dataset.releaseId, tab: 'requests', request: target.dataset.openRequest });
    else if (target.dataset.dashboardProject) await openProject(target.dataset.dashboardProject, { release: target.dataset.dashboardRelease, tab: 'requests' });
    else if (target.dataset.nav) await go({ view: target.dataset.nav, request: null });
    else if (target.dataset.project) await openProject(target.dataset.project);
    else if (target.dataset.request) await go({ request: target.dataset.request });
    else if (target.dataset.tab) await go({ tab: target.dataset.tab, request: null });
    else if (target.dataset.doc) await go({ doc: target.dataset.doc });
    else if (target.dataset.action) await actions[target.dataset.action]?.(target);
    else if (target.dataset.terminal) selectTerminal(target.dataset.terminal);
    else if (target.dataset.terminalClose) await closeTerminal(target.dataset.terminalClose);
    else if (target.dataset.memoryConfirm) modal('Confirmer cette note', '<p>Après vérification de sa source, cette note sera marquée comme confirmée et ajoutée à l’index MEMORY.md.</p>', async () => { await rpc('memory.confirm', { project: state.project, id: target.dataset.memoryConfirm }); closeModal(); await renderProject(); }, 'Confirmer la note');
    else if (target.dataset.libraryIndex) { target.disabled = true; toast('Indexation des documents en cours…'); try { const result = await rpc('library.index', { entry: target.dataset.libraryIndex }); toast(`${result.indexed} document(s) indexé(s), ${result.errors.length} erreur(s). ${result.truncated ? 'Limite de volume atteinte.' : ''}`, result.errors.length > 0); $('#library-results').textContent = result.coverage + (result.errors.length ? '\n' + result.errors.map(x => x.path + ' : ' + x.error).join('\n') : ''); } finally { target.disabled = false; } }
  } catch (error) { toast(error.message, true); }
});
document.addEventListener('change', event => { if (event.target.id === 'project-filter') { state.projectFilter = event.target.value; void render(); return; } if (event.target.id === 'release-select') void go({ release: event.target.value, request: null }).catch(error => toast(error.message, true)); });
document.addEventListener('keydown', event => {
  const typing = event.target.closest('input,textarea,select,[contenteditable],.xterm');
  if (event.key === 'Enter' || event.key === ' ') { if (event.target.matches('[role="button"]:not(button)')) { event.preventDefault(); event.target.click(); } }
  if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k' && !event.target.closest('.xterm')) { event.preventDefault(); palette.open(); return; }
  if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 's' && $('#document-editor')) { event.preventDefault(); void saveDocument().catch(error => toast(error.message, true)); return; }
  if (event.ctrlKey && event.key === '`') { event.preventDefault(); void Promise.resolve(toggleTerminalPanel()).catch(error => toast(error.message, true)); return; }
  if (event.key === '/' && !typing && !$('#modal').open && !palette.isOpen && !chooserOpen()) { event.preventDefault(); if (innerWidth <= 900) { $('#shell').classList.add('sidebar-open'); $('#sidebar-scrim').hidden = false; } $('#project-search').focus(); return; }
  if (event.key === 'Escape') {
    if ($$('details.menu[open]').length) { $$('details.menu[open]').forEach(menu => menu.removeAttribute('open')); return; }
    if ($('#shell').classList.contains('sidebar-open')) { $('#shell').classList.remove('sidebar-open'); $('#sidebar-scrim').hidden = true; return; }
    if (event.target === $('#project-search')) { if (!state.query) event.target.blur(); }
  }
});
$('#modal-cancel').onclick = closeModal;
$('#modal-form').addEventListener('keydown', event => { if ((event.ctrlKey || event.metaKey) && event.key === 'Enter') { event.preventDefault(); $('#modal-form').requestSubmit(); } });
$('#modal-form').onsubmit = async event => { event.preventDefault(); $('#modal-submit').disabled = true; try { await modalAction(new FormData(event.currentTarget)); } catch (error) { $('#modal-error').textContent = error.message; } finally { $('#modal-submit').disabled = false; } };
$('#sidebar-toggle').onclick = () => { const open = $('#shell').classList.toggle('sidebar-open'); $('#sidebar-scrim').hidden = !open; };
$('#sidebar-scrim').onclick = () => { $('#shell').classList.remove('sidebar-open'); $('#sidebar-scrim').hidden = true; };
$('#project-search').oninput = event => { state.query = event.target.value; renderProjectShortcuts(); if (state.view === 'projects') { $('#projects-filter').value = state.query; renderProjectRows(); } };
$('#project-search').onkeydown = event => {
  if (event.key === 'Enter') { const project = state.snapshot?.projects.find(p => matchesProject(p, state.query)); if (project) { event.preventDefault(); void openProject(project.id); } }
  else if (event.key === 'Escape' && state.query) { event.preventDefault(); event.target.value = ''; state.query = ''; renderProjectShortcuts(); }
};

/* ---------------------------------------------------------------- polling & boot */
setInterval(async () => {
  if (!state.snapshot || $('#modal').open || palette.isOpen || document.hidden) return;
  try {
    const before = state.snapshot.jobs.filter(j => j.status === 'running').map(j => j.id).join();
    const sourceStamp = state.snapshot.native_sources?.updated;
    await snapshot();
    void refreshDashboardData();
    const after = state.snapshot.jobs.filter(j => j.status === 'running').map(j => j.id).join();
    if (before && before !== after && state.view === 'project' && state.request && !$('#document-editor')) await renderRequest();
    if (state.view === 'dashboard' && (sourceStamp !== state.snapshot.native_sources?.updated || Date.now() - state.dashboardRefreshed > 30000)) await render();
    else if (['emails', 'agenda'].includes(state.view) && sourceStamp !== state.snapshot.native_sources?.updated) await render();
  } catch { /* the next tick retries */ }
}, 7000);


async function boot() {
  const fragment = new URLSearchParams(location.hash.slice(1)); const token = fragment.get('access');
  if (token) { const response = await fetch('/workbench/session', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ token }) }); history.replaceState(null, '', location.pathname + location.search); if (!response.ok) throw new Error('Le lien de connexion a expiré. Utilisez le lanceur local.'); }
  await snapshot();
  Object.assign(state, readURL());
  if (state.view === 'project' && !projectById(state.project)) Object.assign(state, { view: 'dashboard', project: null });
  if (state.view === 'project') prefs.visit(state.project);
  history.replaceState(null, '', urlFor());
  for (const terminal of state.snapshot.terminals) if (terminal.exit_code === null) await attachTerminal(terminal);
  await render();
  void refreshDashboardData();
}
boot().catch(error => { content().innerHTML = empty('Ouvrir votre espace local', error.message + ' Utilisez « OpenClaw » dans les applications du bureau.', '', '', 'alert'); });
