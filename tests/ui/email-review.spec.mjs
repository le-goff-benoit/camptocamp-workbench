import { test, expect } from '@playwright/test';
import { readFileSync } from 'node:fs';

const fixture = () => JSON.parse(readFileSync('.runtime/qa.json', 'utf8'));
async function source(request, id, title, body = 'Extrait seulement.') {
  const response = await request.post('/workbench/api', {
    headers: { 'Content-Type': 'application/json', Origin: 'http://127.0.0.1:18796', 'X-Workbench-Key': fixture().token },
    data: { action: 'dashboard.sources', data: { emails: [{ account: 'test@example.org', external_id: id,
      sender: 'collegue@camptocamp.com', title, body, date: new Date().toISOString() }] } },
  });
  expect((await response.json()).ok).toBe(true);
}

test('opening an email shows two saved blocks and only explicit reanalysis changes its attempt', async ({ page, request }) => {
  const title = 'Demande client transférée';
  await source(request, 'review-saved-mail', title);
  await page.goto('/workbench/?v=emails#access=' + fixture().token);
  const open = () => page.getByRole('button', { name: 'Lire l’email : ' + title, exact: true }).click();
  await open();
  const panel = page.locator('#email-review');
  await expect(panel).toHaveAttribute('data-status', 'ready');
  await expect(panel.locator('.email-review-block')).toHaveCount(2);
  await expect(page.getByRole('heading', { name: 'Résumé de la demande du client', exact: true })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Ma proposition / analyse / solution', exact: true })).toBeVisible();
  await expect(panel.locator('[data-review-block=request_summary]')).toContainText('selon le message complet');
  await expect(panel.locator('[data-review-block=proposal] li')).toHaveCount(2);
  expect(await page.locator('.email-original').evaluate(node => node.open)).toBe(false);
  expect(await page.locator('#modal-body').evaluate(node => node.scrollTop)).toBe(0);
  const attempt = await panel.getAttribute('data-attempt');
  await page.screenshot({ path: '.runtime/email-review-desktop.png', animations: 'disabled' });
  await page.getByRole('button', { name: 'Fermer', exact: true }).click();
  await source(request, 'review-saved-mail', title, 'Extrait modifié par une synchronisation ultérieure.');
  await page.reload();
  await open();
  await expect(panel).toHaveAttribute('data-status', 'ready');
  await expect(panel).toHaveAttribute('data-attempt', attempt);
  await expect(panel.locator('.email-review-status')).toContainText('reste identique à chaque ouverture');
  await page.getByRole('button', { name: 'Réanalyser', exact: true }).click();
  await expect(panel).not.toHaveAttribute('data-attempt', attempt);
  await expect(panel).toHaveAttribute('data-status', 'ready');
});

test('a long original email stays contained and the two blocks open at the top on mobile', async ({ page, request }) => {
  const title = 'Question détaillée du client';
  await source(request, 'review-long-mail', title, 'Extrait de la demande.');
  await page.setViewportSize({ width: 400, height: 820 });
  await page.goto('/workbench/?v=emails#access=' + fixture().token);
  await page.getByRole('button', { name: 'Lire l’email : ' + title, exact: true }).click();
  await expect(page.locator('#email-review')).toHaveAttribute('data-status', 'ready');
  expect(await page.locator('#modal-body').evaluate(node => node.scrollTop)).toBe(0);
  expect(await page.locator('#modal').evaluate(node => node.scrollWidth <= node.clientWidth)).toBe(true);
  await page.screenshot({ path: '.runtime/email-review-mobile.png', animations: 'disabled' });
  await page.getByText('Message original', { exact: true }).click();
  await page.getByRole('button', { name: 'Lire le message complet', exact: true }).click();
  await expect(page.locator('.email-body')).toContainText('Paragraphe du message original très long.');
  const body = await page.locator('.email-body').boundingBox();
  expect(body.height).toBeLessThanOrEqual(281);
  expect(await page.locator('#modal-body').evaluate(node => node.scrollWidth <= node.clientWidth)).toBe(true);
  const close = await page.getByRole('button', { name: 'Fermer', exact: true }).boundingBox();
  expect(close.y + close.height).toBeLessThan(820);
  await page.getByRole('button', { name: 'Fermer', exact: true }).click();
  await expect(page.getByRole('dialog')).not.toBeVisible();
});
