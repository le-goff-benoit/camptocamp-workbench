import { escape as e, icon, ago } from './text.mjs';
import { emailRows, labels, progressHTML, actionCount, triageButton, triageState } from './dashboard.mjs';

const kindNames = { local: 'Local', test: 'Test', staging: 'Staging', production: 'Production', other: 'Autre' };
const PAGE = 50;
const projectMail = { filter: 'all', query: '', limit: PAGE };

export function environmentsHTML(rows) {
  if (!rows.length) return `<div class="panel-empty">Aucun environnement déclaré.<br><button class="ghost small" data-action="new-environment">${icon('plus')}Ajouter</button></div>`;
  return rows.map(env => {
    let link = '';
    try { const url = new URL(env.url); if (['http:', 'https:'].includes(url.protocol)) link = `<a class="env-link" href="${e(url.href)}" target="_blank" rel="noreferrer" title="${e(url.href)}">Ouvrir${icon('external')}</a>`; } catch {}
    const origin = env.inherited_from ? `<small class="env-origin" title="Déclaré dans le dossier ${e(env.inherited_from)} du même dépôt">via ${e(env.inherited_from)}</small>` : '';
    const terminal = env.path ? `<button class="ghost small" data-env-terminal="${e(env.id)}" title="${e(env.path)}">${icon('terminal')}Terminal…</button>` : '';
    return `<div class="environment-row"><div class="env-main"><span class="env-dot ${e(env.kind)}"></span><strong>${e(env.name)}</strong><span class="tag${env.kind === 'production' ? ' prod' : ''}">${e(kindNames[env.kind] ?? env.kind)}${env.series ? ' · ' + e(env.series) : ''}</span>${origin}</div><div class="env-actions">${link}${terminal}</div></div>`;
  }).join('');
}

function visibleMails(data) {
  const query = projectMail.query.toLocaleLowerCase();
  return data.emails.filter(m => (projectMail.filter !== 'action' || m.triage?.action) && (!query || [m.title, m.sender, m.body, m.participants].join(' ').toLocaleLowerCase().includes(query)));
}
function mailList(data, project) {
  if (!data.emails.length) return `<div class="panel-empty">${data.updated ? 'Aucun email trouvé avec ce critère.<br><button class="link" data-action="project-settings">Régler les adresses du client</button>' : '<span class="loading">Chargement des emails liés au projet…</span>'}</div>`;
  const rows = visibleMails(data);
  if (!rows.length) return `<div class="panel-empty">${projectMail.query ? 'Aucun email ne correspond à cette recherche.' : triageState(data.emails) === 'none' ? 'Lancez l’analyse pour repérer les emails qui attendent une action.' : 'Aucun email n’attend d’action.'}</div>`;
  const rest = rows.length - projectMail.limit;
  return emailRows(rows.slice(0, projectMail.limit), project) + (rest > 0 ? `<button class="ghost small mail-more" data-mail-more>${icon('chevron-down')}Afficher ${Math.min(rest, PAGE)} de plus · ${rest} restant${rest > 1 ? 's' : ''}</button>` : '');
}
function mailPanel(data, project) {
  const count = actionCount(data.emails), filter = projectMail.filter;
  const status = data.updated ? `${data.emails.length}${data.more ? '+' : ''} email${data.emails.length > 1 ? 's' : ''} · relevé ${e(ago(data.updated))}` : '<span class="loading">Lecture des échanges…</span>';
  return `<div class="block-head"><h2>${icon('mail')}Échanges</h2><div class="row"><div class="segmented compact" role="tablist" aria-label="Filtrer les échanges"><button role="tab" data-project-mail-filter="all" aria-selected="${filter === 'all'}" class="${filter === 'all' ? 'active' : ''}">Tous</button><button role="tab" data-project-mail-filter="action" aria-selected="${filter === 'action'}" class="${filter === 'action' ? 'active' : ''}">À traiter${count ? `<span class="count">${count}</span>` : ''}</button></div>${data.emails.length ? triageButton('triage-project', data.emails, 'Analyser') : ''}<button class="icon-button" data-action="refresh-project-emails" aria-label="Actualiser les échanges" title="Actualiser">${icon('refresh')}</button></div></div>
    ${data.emails.length > 8 ? `<div class="search-field mail-search">${icon('search')}<input type="search" data-project-mail-search aria-label="Rechercher dans les échanges du projet" placeholder="Expéditeur, sujet, contenu…" value="${e(projectMail.query)}"></div>` : ''}
    <div class="list" data-project-mail-rows>${mailList(data, project)}</div>
    <p class="block-foot"><span data-project-mail-status>${status}</span>${data.more ? ' · <span title="Affinez la recherche Gmail du projet pour les échanges plus anciens">50 plus récents</span>' : ''} · <span title="${e(data.query)}">${e(data.basis)}</span> · <button class="link" data-action="project-settings">Ajuster</button></p>`;
}

export function paintProjectEmails(project, data) {
  const panel = document.querySelector(`[data-project-emails="${project}"]`);
  if (!panel) return;
  const focused = document.activeElement?.matches?.('[data-project-mail-search]');
  panel.innerHTML = mailPanel(data, project); panel.emailData = data;
  const rows = () => panel.querySelector('[data-project-mail-rows]');
  const search = panel.querySelector('[data-project-mail-search]');
  if (search) {
    search.oninput = () => { projectMail.query = search.value; projectMail.limit = PAGE; rows().innerHTML = mailList(data, project); };
    if (focused) { search.focus(); search.setSelectionRange(search.value.length, search.value.length); }
  }
  panel.onclick = event => { if (event.target.closest('[data-mail-more]')) { projectMail.limit += PAGE; rows().innerHTML = mailList(data, project); } };
}
export function setProjectMailFilter(project, filter) {
  projectMail.filter = filter; projectMail.limit = PAGE;
  const panel = document.querySelector(`[data-project-emails="${project}"]`);
  if (panel?.emailData) paintProjectEmails(project, panel.emailData);
}

export function renderProjectDashboard(detail, release, rpc, isCurrent) {
  const { project, environments, email_sources: sources } = detail, body = document.querySelector('#project-body');
  Object.assign(projectMail, { filter: 'all', query: '', limit: PAGE });
  const releaseBlock = release
    ? `<div id="project-release-summary" class="release-summary"><div class="skeleton" style="width:60%"></div><div class="skeleton" style="width:40%"></div></div>`
    : `<p class="muted">Aucune release. Ouvrez-en une depuis la barre ci-dessus.</p>`;
  body.innerHTML = `<div class="grid-main"><section class="block project-emails-panel" data-project-emails="${e(project.id)}"></section><aside class="stack"><section class="block"><div class="block-head"><h2>${icon('layers')}${release?.status === 'ouverte' ? 'Release en cours' : 'Release'}</h2><button class="ghost small" data-tab="requests">Demandes${icon('arrow-right')}</button></div>${releaseBlock}</section><section class="block"><div class="block-head"><h2>${icon('server')}Environnements</h2><button class="ghost small" data-action="new-environment">${icon('plus')}Ajouter</button></div><div class="list">${environmentsHTML(environments)}</div></section></aside></div>`;
  paintProjectEmails(project.id, sources);
  if (release) void rpc('release.overview', { project: project.id, release: release.id }).then(o => {
    const target = document.querySelector('#project-release-summary'); if (!isCurrent() || !target) return;
    target.innerHTML = `<div class="release-health"><span class="badge ${e(o.state)}">${e(labels[o.state] ?? o.state)}</span>${progressHTML(o.received, o.total)}</div><p class="next-step">${icon('arrow-right', 'sm')}${e(o.next_action)}</p>`;
  }).catch(error => { if (isCurrent()) { const target = document.querySelector('#project-release-summary'); if (target) target.textContent = error.message; } });
  void loadProjectEmails(project.id, rpc, isCurrent);
}

export async function loadProjectEmails(project, rpc, isCurrent, force = false) {
  const panel = document.querySelector(`[data-project-emails="${project}"]`); if (!panel) return;
  const status = panel.querySelector('[data-project-mail-status]');
  if (status) status.innerHTML = '<span class="loading">Lecture des échanges du projet…</span>';
  try {
    const result = await rpc('project.emails', { project, force });
    if (!isCurrent() || !panel.isConnected) return;
    paintProjectEmails(project, result);
  } catch (error) {
    if (isCurrent() && panel.isConnected) {
      const target = panel.querySelector('[data-project-mail-status]');
      if (target) { target.textContent = error.message; target.classList.add('error'); }
      const rows = panel.querySelector('[data-project-mail-rows]');
      if (rows && !rows.querySelector('.mail-row')) rows.innerHTML = `<div class="panel-empty">${icon('alert', 'lg')}Les échanges n’ont pas pu être lus. Vérifiez la connexion Gmail du fournisseur choisi dans Connexions.</div>`;
    }
  }
}
