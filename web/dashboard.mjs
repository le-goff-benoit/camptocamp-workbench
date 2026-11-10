import { taskMeasures } from './measurements.mjs';
import { escape as e, icon, ago } from './text.mjs';

export const labels = { ouverte:'À cadrer', 'en-cours':'En cours', 'a-faire':'Prêt à poursuivre', 'attente-validation':'Votre décision attendue', 'a-verifier':'À vérifier', bloquee:'Bloquée', terminee:'Prête pour clôture', cloturee:'Clôturée', archive:'Historique', validated:'Reçue', stale:'Preuve à revérifier', pending:'À faire', ready:'Prête', running:'En cours', done:'Déclarée terminée', unverified:'Non vérifiée', failed:'Échec', blocked:'Bloquée' };
const attentionLabels = { bloquee: 'Bloquée', 'attente-validation': 'Plan à valider', 'a-verifier': 'À vérifier' };
const attentionIcons = { bloquee: 'alert', 'attente-validation': 'flag', 'a-verifier': 'check' };

const date = value => { const d = new Date(value); return Number.isNaN(+d) ? 'Date non renseignée' : new Intl.DateTimeFormat('fr-CH',{dateStyle:'medium',timeStyle:value?.includes('T')?'short':undefined}).format(d); };
const minutes = value => Number.isFinite(value) ? value < 60 ? `${value.toLocaleString('fr-CH',{maximumFractionDigits:1})} min` : `${Math.floor(value/60)} h ${Math.round(value%60)} min` : 'Non mesuré';
const tokens = value => Number.isFinite(value) ? value.toLocaleString('fr-CH') : 'Non mesuré';
const freshness = updated => `<span class="source-freshness">${icon('clock')}${updated ? 'Relevé ' + e(ago(updated)) : 'Sources à connecter'}</span>`;

export function metricCards(overview, compact = false) {
  const m = taskMeasures(overview.effort_rows ?? [], []);
  const cells = [
    ['Estimation initiale', Number.isFinite(m.initial) ? minutes(m.initial) : 'À estimer'],
    ['Estimation révisée', Number.isFinite(m.revised) ? minutes(m.revised) : '—'],
    [`Réalisé agents${m.partial ? ' · partiel' : ''}`, minutes(m.actual)],
    [`Jetons${m.tokenPartial ? ' · partiels' : ''}`, tokens(m.tokens)],
  ];
  return `<div class="metric-strip${compact ? ' compact' : ''}">${cells.map(([label, value]) => `<div><small>${label}</small><strong>${value}</strong></div>`).join('')}</div>`;
}

export function progressHTML(received, total) {
  if (!total) return '';
  return `<span class="progress" title="${received} demande(s) reçue(s) sur ${total}"><span class="progress-track"><span style="width:${Math.round(100 * received / total)}%"></span></span>${received}/${total} reçue${received > 1 ? 's' : ''}</span>`;
}

export function overviewHTML(overview, { metrics = true } = {}) {
  const notes = [overview.blocked ? overview.blocked + ' blocage(s)' : '', overview.decisions ? overview.decisions + ' décision(s) attendue(s)' : ''].filter(Boolean).join(' · ');
  return `<div class="release-health"><span class="badge ${e(overview.state)}">${e(labels[overview.state]??overview.state)}</span><strong>${e(overview.next_action)}</strong>${progressHTML(overview.received, overview.total)}${notes ? `<small>${notes}</small>` : ''}</div>${metrics ? metricCards(overview) + `<p class="hint">${e(overview.effort_basis)} · ${e(overview.scope)}</p>` : ''}${overview.tasks?.length?`<div class="task-summary">${overview.tasks.map(t=>`<div class="task-summary-row"><div><strong>${e(t.id)} · ${e(t.title)}</strong>${t.reason?`<small>${e(t.reason)}</small>`:''}</div><span class="badge ${e(t.status)}">${e(labels[t.status]??t.status)}</span></div>`).join('')}</div>`:''}${overview.warnings?.length?`<details class="notice warning"><summary>Réserves sur le suivi (${overview.warnings.length})</summary>${overview.warnings.map(w=>`<p>${e(w)}</p>`).join('')}</details>`:''}`;
}

export function metricsHTML(overview) {
  const rows = overview.effort_rows ?? [];
  const totals = overview.effort_totals;
  return `${metricCards(overview)}<p class="hint">${e(overview.scope)} Les temps partiels, les compteurs manquants et les changements de périmètre restent explicitement distingués.</p>${rows.length?`<div class="table-scroll"><table class="metrics-table"><thead><tr><th>Travail / rôle</th><th>Initial</th><th>Révisé</th><th>Réalisé</th><th>Écart comparable</th><th>Jetons</th></tr></thead><tbody>${rows.map(row=>{const m=taskMeasures([row],[]);return `<tr><td><strong>${e(row.title??row.task)}</strong><small>${e(row.agent)}</small></td><td>${m.initial===null?'À estimer':minutes(m.initial)}</td><td>${m.revised===null?'—':minutes(m.revised)}</td><td>${minutes(m.actual)}${m.partial?' · partiel':''}</td><td>${Number.isFinite(m.delta)?(m.delta>0?'+':'')+minutes(m.delta):'Non comparable'}</td><td>${tokens(m.tokens)}${m.tokenPartial?' · partiel':''}</td></tr>`;}).join('')}</tbody></table></div>`:'<div class="notice info">Aucune estimation ou mesure consolidée n’est enregistrée pour cette release. Le temps d’ouverture de la conversation n’est pas utilisé comme temps de travail.</div>'}${totals&&Object.keys(totals.known_costs??{}).length?`<div class="card section"><h3>Coûts connus</h3>${Object.entries(totals.known_costs).map(([basis,value])=>`<p>${e(basis)} : ${e(value)}</p>`).join('')}<small>${totals.unpriced_entries??0} relevé(s) sans coût disponible. Ces montants ne sont pas un tarif client.</small></div>`:''}${overview.warnings?.length?`<p class="hint">${overview.warnings.map(e).join(' · ')}</p>`:''}`;
}

function flagHTML(t) {
  if (!t?.action) return '';
  return `<span class="flag ${e(t.priority)}" title="${e(t.reason)}">${icon('flag', 'sm')}${t.priority === 'haute' ? 'Urgent' : 'Action'}</span>`;
}
export function emailRows(emails, options = '') {
  const { project = '', showProject = false } = typeof options === 'string' ? { project: options } : options;
  return emails.map(item => {
    const sender = String(item.sender || item.account || '').replace(/<[^>]+>/g, '').replace(/"/g, '').replace(/\s+[^\s]+@[^\s]+$/, '').trim();
    const t = item.triage;
    const tag = showProject ? projectTag(item) : '';
    return `<button class="mail-row${t?.action ? ' flagged' : ''}" data-mail="${e(item.external_id)}" data-mail-project="${e(project)}" aria-label="Lire l’email : ${e(item.title)}"><span class="mail-meta"><span class="mail-sender">${e(sender)}</span>${tag}<time datetime="${e(item.date)}" title="${e(date(item.date))}">${e(ago(item.date))}</time></span><span class="mail-subject">${flagHTML(t)}${e(item.title || 'Sans objet')}</span>${t?.action && t.next_step ? `<span class="mail-next">${icon('arrow-right', 'sm')}${e(t.next_step)}</span>` : `<span class="mail-snippet">${e(item.body?.slice(0, 200) || '')}</span>`}</button>`;
  }).join('');
}
export const actionCount = emails => emails.filter(m => m.triage?.action).length;
export const triageState = emails => emails.length && emails.every(m => m.triage) ? 'done' : emails.some(m => m.triage) ? 'partial' : 'none';

function eventTitle(event) {
  try {
    const url = new URL(event.url);
    if (url.protocol === 'https:' && ['calendar.google.com', 'www.google.com'].includes(url.hostname))
      return `<a class="event-title" href="${e(url.href)}" target="_blank" rel="noreferrer" title="Ouvrir dans Google Agenda">${e(event.title)}${icon('external')}</a>`;
  } catch {}
  return `<strong>${e(event.title)}</strong>`;
}

export const projectTag = (row, clickable = false) => row?.project_name
  ? (clickable ? `<button class="project-tag" data-project="${e(row.project)}" title="Ouvrir le projet${row.project_by ? ' · rattaché par ' + e(row.project_by) : ''}">${e(row.project_name)}</button>`
    : `<span class="project-tag" title="${row.project_by ? 'Rattaché par ' + e(row.project_by) : ''}">${e(row.project_name)}</span>`) : '';

export function projectFilterHTML(rows, selected = '') {
  const projects = [...new Map(rows.filter(r => r?.project).map(r => [r.project, r.project_name])).entries()].sort((a, b) => String(a[1]).localeCompare(String(b[1])));
  if (!projects.length && !selected) return '';
  return `<label class="filter-select" title="Filtrer par projet">${icon('folder', 'sm')}<select id="project-filter" aria-label="Filtrer par projet"><option value="">Tous les projets</option>${projects.map(([id, name]) => `<option value="${e(id)}" ${id === selected ? 'selected' : ''}>${e(name)}</option>`).join('')}</select></label>`;
}

export function agendaRows(events, { days = true } = {}) {
  const dayFormat = new Intl.DateTimeFormat('fr-CH', { weekday: 'long', day: 'numeric', month: 'long' });
  const today = new Date().toDateString(), tomorrow = new Date(Date.now() + 86400000).toDateString();
  let current = '';
  return events.map(event => {
    const at = new Date(event.date), valid = Number.isFinite(+at);
    const clock = event.date?.length === 10 ? 'Journée' : valid ? new Intl.DateTimeFormat('fr-CH', { hour: '2-digit', minute: '2-digit' }).format(at) : '—';
    const key = valid ? at.toDateString() : '';
    const label = key === today ? 'Aujourd’hui' : key === tomorrow ? 'Demain' : valid ? dayFormat.format(at) : 'Date inconnue';
    const header = days && key !== current ? `<div class="agenda-day">${e(label)}</div>` : '';
    current = key;
    const now = valid && event.end && +at <= Date.now() && Date.now() < +new Date(event.end);
    return `${header}<div class="agenda-row${now ? ' now' : ''}"><div class="agenda-time">${e(clock)}${!days && valid ? `<small>${e(label)}</small>` : ''}</div><div class="agenda-body">${eventTitle(event)}${event.project_name ? `<div class="agenda-meta">${projectTag(event, true)}</div>` : ''}</div></div>`;
  }).join('');
}

const noSources = `<div class="panel-empty">${icon('plug','lg')}Aucune donnée récupérée pour le moment.<br><button class="secondary small" data-action="refresh-codex">${icon('refresh')}Actualiser mes emails et mon agenda</button></div>`;

export function attentionRows(rows) {
  return rows.map(r => `<button class="attention-row" data-open-request="${e(r.id)}" data-project-id="${e(r.project)}" data-release-id="${e(r.release)}" aria-label="Ouvrir ${e(r.title)}"><span class="attention-icon ${e(r.status)}">${icon(attentionIcons[r.status] ?? 'flag')}</span><span class="what"><strong>${e(r.title)}</strong><small>${e(r.project_name)} · ${e(r.release_title)}${r.status === 'bloquee' && r.blocked_reason ? ' · ' + e(r.blocked_reason) : ''}</small></span><span class="row"><span class="badge ${e(r.status)}">${e(attentionLabels[r.status] ?? r.status)}</span>${icon('chevron-right','go')}</span></button>`).join('');
}

export function triageButton(scope, emails, label = 'Analyser les actions') {
  const state = triageState(emails);
  return `<button class="ghost small" data-action="${scope}" title="Le fournisseur choisi dans Paramètres lit l’objet, l’expéditeur et l’extrait, puis repère les actions attendues.">${icon('sparkle')}${state === 'done' ? 'Analyse à jour' : label}</button>`;
}

export async function renderSources(rpc, kind, isCurrent = () => true, ui = {}) {
  const d = await rpc('dashboard.get'); if (!isCurrent()) return;
  const emails = kind === 'emails', pf = ui.projectFilter ?? '';
  const inProject = row => !pf || row.project === pf;
  const content = document.querySelector('#content');
  if (!emails) {
    const next = d.next_events.filter(inProject), past = (d.past_events ?? []).filter(inProject);
    content.innerHTML = `<div class="page narrow"><div class="page-head"><div><h1>Agenda</h1>${freshness(d.source_updated)}</div><div class="page-actions">${projectFilterHTML([...d.next_events, ...(d.past_events ?? [])], pf)}<button class="ghost" data-action="refresh-codex">${icon('refresh')}Actualiser</button></div></div><section class="panel">${next.length ? agendaRows(next) : d.next_events.length ? '<div class="panel-empty">Aucun rendez-vous à venir pour ce projet.</div>' : noSources}</section>${past.length ? `<div class="section-title"><h2>Événements passés</h2></div><section class="panel">${agendaRows(past.slice(0, 5))}</section>` : ''}</div>`;
    return d;
  }
  const filter = ui.mailFilter ?? 'all';
  const previous = document.querySelector('#email-filter'), query = previous?.value ?? '', focused = previous && document.activeElement === previous;
  const count = actionCount(d.emails.filter(inProject));
  content.innerHTML = `<div class="page narrow"><div class="page-head"><div><h1>Emails récents</h1>${freshness(d.source_updated)}</div><div class="page-actions">${triageButton('triage-inbox', d.emails)}<button class="ghost" data-action="refresh-codex">${icon('refresh')}Actualiser</button></div></div>
    <div class="toolbar"><div class="search-field">${icon('search')}<input id="email-filter" type="search" aria-label="Rechercher dans les emails" placeholder="Expéditeur, sujet…"></div><div class="segmented" role="tablist" aria-label="Filtrer les emails"><button role="tab" data-mail-filter="all" aria-selected="${filter === 'all'}" class="${filter === 'all' ? 'active' : ''}">Tous</button><button role="tab" data-mail-filter="action" aria-selected="${filter === 'action'}" class="${filter === 'action' ? 'active' : ''}">À traiter${count ? `<span class="count">${count}</span>` : ''}</button></div>${projectFilterHTML(d.emails, pf)}</div>
    <section class="panel" id="source-list"></section></div>`;
  const field = document.querySelector('#email-filter');
  const apply = () => {
    const search = field.value.toLocaleLowerCase();
    const rows = d.emails.filter(m => (filter !== 'action' || m.triage?.action) && inProject(m) && [m.title, m.sender, m.body].join(' ').toLocaleLowerCase().includes(search));
    document.querySelector('#source-list').innerHTML = d.emails.length ? (rows.length ? emailRows(rows, { showProject: true }) : `<div class="panel-empty">${filter === 'action' && triageState(d.emails) === 'none' ? 'Lancez « Analyser les actions » pour repérer les emails qui attendent une réponse.' : 'Aucun email ne correspond.'}</div>`) : noSources;
  };
  field.oninput = apply; field.value = query; apply(); if (focused) field.focus();
  return d;
}

export async function renderDashboard(rpc, isCurrent = () => true, ui = {}) {
  const d = await rpc('dashboard.get'); if (!isCurrent()) return;
  const pf = ui.projectFilter ?? '', inProject = row => !pf || row.project === pf;
  const open = d.open_releases.filter(inProject).slice(0, 6), attention = (d.attention ?? []).filter(inProject);
  const mails = d.emails.filter(inProject), events = d.next_events.filter(inProject);
  const today = new Intl.DateTimeFormat('fr-CH', { weekday: 'long', day: 'numeric', month: 'long' }).format(new Date());
  const count = actionCount(mails);
  const shown = [...mails.filter(m => m.triage?.action), ...mails.filter(m => !m.triage?.action)].slice(0, 5);
  const releaseRow = r => `<div class="release-list-row"><button class="release-title" data-dashboard-project="${e(r.project)}" data-dashboard-release="${e(r.id)}"><span class="release-project">${e(r.project_name)}</span>${e(r.title)}</button><div class="release-status" data-release-summary data-project="${e(r.project)}" data-release="${e(r.id)}"><span class="skeleton" style="width:90px"></span></div></div>`;
  document.querySelector('#content').innerHTML = `<div class="page">
    <div class="page-head home-greeting"><div><div class="eyebrow">${e(today)}</div><h1>${new Date().getHours() < 18 ? 'Bonjour' : 'Bonsoir'}</h1></div><div class="page-actions">${projectFilterHTML([...d.emails, ...d.next_events, ...(d.attention ?? []), ...d.open_releases], pf)}${freshness(d.source_updated)}<button class="ghost small" data-action="refresh-codex">${icon('refresh')}Actualiser</button></div></div>
    ${attention.length ? `<section class="block"><div class="block-head"><h2>${icon('flag')}À traiter <span class="count">${attention.length}</span></h2></div><div class="list">${attentionRows(attention)}</div></section>` : ''}
    <div class="grid-2"><section class="block"><div class="block-head"><h2>${icon('mail')}Emails récents${count ? ` <span class="count warn">${count} à traiter</span>` : ''}</h2><div class="row">${triageButton('triage-inbox', d.emails, 'Analyser')}<button class="ghost small" data-nav="emails">Tout voir${icon('arrow-right')}</button></div></div><div class="list">${d.emails.length ? (shown.length ? emailRows(shown, { showProject: true }) : '<div class="panel-empty">Aucun email récent pour ce projet.</div>') : noSources}</div></section>
    <section class="block agenda-panel"><div class="block-head"><h2>${icon('calendar')}Prochains rendez-vous</h2><button class="ghost small" data-nav="agenda">Agenda${icon('arrow-right')}</button></div><div class="list">${d.next_events.length ? (events.length ? agendaRows(events.slice(0, 6)) : '<div class="panel-empty">Aucun rendez-vous à venir pour ce projet.</div>') : noSources}</div></section></div>
    ${open.length ? `<section class="block"><div class="block-head"><h2>${icon('layers')}Releases en cours <span class="count">${pf ? open.length : d.open_release_count}</span></h2><button class="ghost small" data-nav="projects">Projets${icon('arrow-right')}</button></div><div class="list">${open.map(releaseRow).join('')}</div></section>` : ''}
  </div>`;
  let cursor = 0;
  const elements = [...document.querySelectorAll('[data-release-summary]')];
  async function load() { while (cursor < elements.length) { const target = elements[cursor++]; try {
    const o = await rpc('release.overview', { project: target.dataset.project, release: target.dataset.release });
    if (!target.isConnected) return;
    target.innerHTML = `<span class="badge ${e(o.state)}" title="${e(o.next_action)}">${e(labels[o.state] ?? o.state)}</span>`;
  } catch (error) { target.innerHTML = '<span class="badge stale">À vérifier</span>'; } } }
  void Promise.all([load(), load()]); return d;
}
