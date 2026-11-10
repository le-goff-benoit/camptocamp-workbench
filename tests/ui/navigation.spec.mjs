import { test, expect } from '@playwright/test';
import { readFileSync } from 'node:fs';

const fixture = () => JSON.parse(readFileSync('.runtime/qa.json', 'utf8'));
const api = (request, action, data) => request.post('/workbench/api', { headers: { 'Content-Type': 'application/json', Origin: 'http://127.0.0.1:18796', 'X-Workbench-Key': fixture().token }, data: { action, data } }).then(async r => { const body = await r.json(); expect(body.ok, body.error).toBeTruthy(); return body.result; });

test('Ctrl K opens a palette to jump to a project and run its actions', async ({ page }) => {
  await page.goto('/workbench/#access=' + fixture().token);
  await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
  await page.keyboard.press('Control+k');
  const palette = page.getByRole('dialog', { name: 'Rechercher ou lancer une action' });
  await expect(palette).toBeVisible();
  await page.getByRole('combobox', { name: 'Rechercher une commande' }).fill('atlas');
  await page.screenshot({ path: '.runtime/palette-0.4.png' });
  await page.keyboard.press('Enter');
  await expect(page.getByRole('heading', { name: 'atlas-demo', exact: true, level: 1 })).toBeVisible();
  await page.keyboard.press('Control+k');
  await page.getByRole('combobox', { name: 'Rechercher une commande' }).fill('nouvelle release');
  await page.keyboard.press('Enter');
  await expect(page.getByLabel('Titre de la release')).toBeFocused();
  await page.getByRole('button', { name: 'Annuler', exact: true }).click();
});

test('views live in the URL: reload keeps the tab and Back returns to the previous view', async ({ page }) => {
  await page.goto('/workbench/#access=' + fixture().token);
  await page.getByRole('button', { name: 'Projet atlas-demo', exact: true }).click();
  await page.getByRole('tab', { name: 'Documents', exact: true }).click();
  await expect(page).toHaveURL(/t=documents/);
  await page.reload();
  await expect(page.getByRole('tab', { name: 'Documents', exact: true })).toHaveAttribute('aria-selected', 'true');
  await page.goBack();
  await expect(page.getByRole('tab', { name: 'Vue d’ensemble', exact: true })).toHaveAttribute('aria-selected', 'true');
  await page.getByRole('navigation', { name: 'Fil d’Ariane' }).getByRole('button', { name: 'Projets' }).click();
  await expect(page.getByRole('heading', { name: 'Projets', exact: true, level: 1 })).toBeVisible();
});

test('a pinned project stays pinned after reload', async ({ page }) => {
  await page.goto('/workbench/#access=' + fixture().token);
  await page.getByRole('button', { name: 'Projet boreal-demo', exact: true }).click();
  await page.getByRole('button', { name: 'Épingler le projet' }).click();
  await expect(page.getByRole('button', { name: 'Désépingler le projet' })).toHaveAttribute('aria-pressed', 'true');
  await page.reload();
  await expect(page.getByRole('button', { name: 'Désépingler le projet' })).toBeVisible();
  // Pinned projects come first in the sidebar.
  await expect(page.locator('#project-shortcuts .shortcut').first()).toHaveAttribute('aria-label', 'Projet boreal-demo');
  await page.getByRole('button', { name: 'Désépingler le projet' }).click();
});

test('home lists what awaits a decision and opens the request directly', async ({ page, request }) => {
  const { project } = fixture();
  const release = await api(request, 'release.create', { project, title: 'Lot à décider' });
  const created = await api(request, 'request.create', { project, release: release.id, title: 'Valider les droits du portail', description: 'Synthétique.' });
  let record = await api(request, 'request.transition', { project, request: created.id, revision: (await api(request, 'request.get', { project, request: created.id })).revision, action: 'start-analysis', note: '' });
  record = await api(request, 'request.transition', { project, request: created.id, revision: record.revision, action: 'propose-plan', note: '## Plan\n\n- [ ] Vérifier les groupes\n- [x] Lire le besoin' });
  await page.goto('/workbench/#access=' + fixture().token);
  const row = page.getByRole('button', { name: 'Ouvrir Valider les droits du portail' });
  await expect(row).toContainText('Plan à valider');
  await page.screenshot({ path: '.runtime/home-0.4.png' });
  await row.click();
  await expect(page.getByRole('heading', { name: 'Valider les droits du portail', level: 1 })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Plan', level: 2 })).toBeVisible();
  await page.screenshot({ path: '.runtime/request-0.4.png' });
});

test('documents render as Markdown and are edited in place with Ctrl S', async ({ page }) => {
  await page.goto('/workbench/#access=' + fixture().token);
  await page.getByRole('button', { name: 'Projet atlas-demo', exact: true }).click();
  await page.getByRole('tab', { name: 'Documents', exact: true }).click();
  await page.getByRole('tab', { name: 'Recette', exact: true }).click();
  await expect(page.locator('.doc-body h1')).toHaveText('Recette de release');
  await page.getByRole('button', { name: 'Modifier', exact: true }).click();
  const editor = page.getByLabel('Contenu du document');
  await editor.press('Control+End');
  await editor.pressSequentially('\n\n## Contrôle navigateur\n\n- [x] Parcours vérifié');
  await page.keyboard.press('Control+s');
  await expect(page.getByRole('heading', { name: 'Contrôle navigateur', level: 2 })).toBeVisible();
  await expect(page.locator('.doc-body li.task.done')).toContainText('Parcours vérifié');
  await page.screenshot({ path: '.runtime/document-0.4.png' });
});

test('phone width keeps the project usable without horizontal scroll', async ({ page }) => {
  await page.setViewportSize({ width: 400, height: 820 });
  await page.goto('/workbench/?v=project&p=' + fixture().project + '#access=' + fixture().token);
  await expect(page.getByRole('heading', { name: 'atlas-demo', exact: true, level: 1 })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: '.runtime/phone-0.4.png', fullPage: false });
});

test('Codex flags the emails that expect an action and the list can be filtered', async ({ page, request }) => {
  const common = { account: 'consultant@example.org', sender: 'Marie Client <marie@atlas.example>', date: new Date().toISOString() };
  await api(request, 'dashboard.sources', { emails: [
    { ...common, external_id: 'triage-a', title: 'Devis portail', body: 'Merci de valider le devis avant vendredi.' },
    { ...common, external_id: 'triage-b', title: 'Newsletter Odoo', body: 'Les nouveautés du mois.' },
  ] });
  await page.goto('/workbench/?v=emails#access=' + fixture().token);
  await page.getByRole('button', { name: 'Analyser les actions' }).click();
  const flagged = page.locator('.mail-row.flagged');
  await expect(flagged).toHaveCount(1);
  await expect(flagged).toContainText('Devis portail');
  await expect(flagged).toContainText('Répondre au client');
  await page.getByRole('tab', { name: /À traiter/ }).click();
  await expect(page.locator('#source-list .mail-row')).toHaveCount(1);
  await page.screenshot({ path: '.runtime/emails-triage-0.4.png' });
  await page.getByRole('tab', { name: 'Tous', exact: true }).click();
  await expect(page.locator('#source-list .mail-row')).toHaveCount(2);
});

test('emails and meetings carry their project, can be filtered, and an email opens a terminal in its repository', async ({ page, request }) => {
  await page.goto('/workbench/#access=' + fixture().token);
  await page.getByRole('button', { name: 'Projet atlas-demo', exact: true }).click();
  await page.locator('summary[aria-label="Plus d’actions"]').click();
  await page.getByRole('menuitem', { name: 'Réglages du projet' }).click();
  await page.getByLabel('Domaines client · séparés par des virgules').fill('atlas.example');
  await page.getByRole('button', { name: 'Enregistrer', exact: true }).click();
  await expect(page.getByRole('status')).toHaveText('Règles du projet enregistrées.');
  const when = new Date(Date.now() + 3 * 3600000).toISOString();
  await api(request, 'dashboard.sources', {
    emails: [{ account: 'me@example.org', external_id: 'tag-a', sender: 'Marie <marie@atlas.example>', title: 'Question sur la facture', date: new Date().toISOString(), body: 'Bonjour' },
             { account: 'me@example.org', external_id: 'tag-b', sender: 'news@example.net', title: 'Lettre d’information', date: new Date().toISOString(), body: 'Infos' }],
    events: [{ account: 'me@example.org', external_id: 'ev-a', sender: 'moi@camptocamp.com', participants: 'marie@atlas.example', title: 'Atelier facturation', date: when },
             { account: 'me@example.org', external_id: 'ev-b', sender: 'moi@camptocamp.com', title: 'Formation interne', date: when }],
  });
  await page.locator('.nav-item[data-nav=dashboard]').click();
  await expect(page.locator('.mail-row').filter({ hasText: 'Question sur la facture' }).locator('.project-tag')).toHaveText('atlas-demo');
  await expect(page.locator('.agenda-row').filter({ hasText: 'Atelier facturation' }).getByRole('button', { name: 'atlas-demo' })).toBeVisible();
  await page.getByLabel('Filtrer par projet').selectOption({ label: 'atlas-demo' });
  await expect(page.locator('.mail-row')).toHaveCount(1);
  await expect(page.locator('.agenda-row')).toHaveCount(1);
  await page.screenshot({ path: '.runtime/home-projects-0.4.png' });
  await page.locator('.nav-item[data-nav=agenda]').click();
  await expect(page.getByLabel('Filtrer par projet')).toHaveValue(/.+/);
  await expect(page.locator('.agenda-row')).toHaveCount(1);
  await page.locator('.nav-item[data-nav=emails]').click();
  await expect(page.locator('#source-list .mail-row')).toHaveCount(1);
  await page.getByRole('button', { name: 'Lire l’email : Question sur la facture' }).click();
  await page.getByRole('button', { name: 'Ouvrir un terminal dans atlas-demo' }).click();
  await expect(page.getByRole('heading', { name: 'atlas-demo', exact: true, level: 1 })).toBeVisible();
  await page.getByRole('menuitem', { name: 'Shell simple' }).click();
  const view = page.locator('.terminal-view:not([hidden])');
  await expect(view.locator('.xterm-screen')).toContainText('bash-5.1$');
  await view.locator('textarea').pressSequentially('pwd'); await view.locator('textarea').press('Enter');
  await expect(view.locator('.xterm-screen')).toContainText(fixture().repo);
  await page.locator('#terminal-tabs .term-tab.selected button.close').click();
  await page.getByRole('button', { name: 'Arrêter et fermer', exact: true }).click();
  await expect(page.locator('#terminal-panel')).toBeHidden();
});
