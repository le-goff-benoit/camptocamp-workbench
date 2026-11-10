import { test, expect } from '@playwright/test';
import { readFileSync } from 'node:fs';

const fixture = () => JSON.parse(readFileSync('.runtime/qa.json','utf8'));
async function api(request, action, data={}) {
  const response=await request.post('/workbench/api',{headers:{'Content-Type':'application/json','Origin':'http://127.0.0.1:18796','X-Workbench-Key':fixture().token},data:{action,data}});
  const payload=await response.json(); expect(payload.ok).toBe(true); return payload.result;
}

test.afterEach(async({request})=>{
  const snapshot=await api(request,'snapshot');
  const settings={...snapshot.settings,providers:{sources:'codex',analysis:'codex'},source_sync:{enabled:false}};
  const response=await request.post('/workbench/api',{headers:{'Content-Type':'application/json','Origin':'http://127.0.0.1:18796',Cookie:'workbench_session='+fixture().token,'X-Workbench-UI':'1'},data:{action:'settings.save',data:{settings}}});
  expect((await response.json()).ok).toBe(true);
});

test('settings distinguish sources, analysis and five-minute synchronization',async({page})=>{
  await page.goto('/workbench/?v=settings#access='+fixture().token);
  await page.getByLabel('Emails et agenda',{exact:true}).selectOption('claude');
  await page.getByLabel('Analyses et propositions de plan',{exact:true}).selectOption('claude');
  await page.getByLabel('Actualiser automatiquement toutes les 5 minutes',{exact:false}).check();
  const sourceBox=await page.getByLabel('Emails et agenda',{exact:true}).boundingBox();
  const analysisBox=await page.getByLabel('Analyses et propositions de plan',{exact:true}).boundingBox();
  expect(Math.abs(sourceBox.y-analysisBox.y)).toBeLessThan(2);
  expect(sourceBox.height).toBe(analysisBox.height);
  await page.screenshot({path:'.runtime/settings-desktop.png',fullPage:true});
  await page.getByRole('button',{name:'Enregistrer les paramètres'}).click();
  await expect(page.getByRole('status')).toHaveText('Paramètres enregistrés.');
  await page.reload();
  await expect(page.getByLabel('Emails et agenda',{exact:true})).toHaveValue('claude');
  await expect(page.getByLabel('Actualiser automatiquement toutes les 5 minutes',{exact:false})).toBeChecked();
  await page.getByLabel('Actualiser automatiquement toutes les 5 minutes',{exact:false}).uncheck();
  await page.getByRole('button',{name:'Enregistrer les paramètres'}).click();
  await expect(page.getByRole('status')).toHaveText('Paramètres enregistrés.');
  await page.locator('.nav-item[data-nav=connections]').click();
  await page.getByRole('button',{name:'Vérifier les connexions Claude'}).click();
  await expect(page.getByRole('status')).toHaveText('État des connexions Claude mis à jour.');
  await expect(page.locator('.connector-list .connected')).toHaveCount(2);
  await page.screenshot({path:'.runtime/connections-desktop.png',fullPage:true});
  await page.getByRole('button',{name:'Actualiser les emails et l’agenda',exact:true}).click();
  await expect(page.getByRole('status')).toHaveText('50 emails et 1 événements actualisés.');
  await expect(page.locator('.notice.info')).toContainText('via Claude Code');
  await page.locator('.nav-item[data-nav=emails]').click();
  await expect(page.locator('#source-list .mail-row')).toHaveCount(50);
  await page.getByRole('button',{name:'Analyser les actions',exact:true}).click();
  await expect(page.locator('#source-list .mail-row.flagged')).toHaveCount(20);
  await page.getByRole('button',{name:'Paramètres',exact:true}).click();
  await page.getByLabel('Emails et agenda',{exact:true}).selectOption('codex');
  await page.getByLabel('Analyses et propositions de plan',{exact:true}).selectOption('codex');
  await page.getByRole('button',{name:'Enregistrer les paramètres'}).click();
  await expect(page.getByRole('status')).toHaveText('Paramètres enregistrés.');
});

test('email import names its destination, reads the full mail and opens the created task',async({page,request})=>{
  const release=await api(request,'release.create',{project:fixture().project,title:'Demandes depuis les emails'});
  await api(request,'dashboard.sources',{emails:[{account:'test@example.org',external_id:'mail-import-test',sender:'client@example.org',title:'Besoin à suivre',body:'Extrait seulement.',date:new Date().toISOString()}]});
  await page.goto('/workbench/?v=emails#access='+fixture().token);
  await page.getByRole('button',{name:'Lire l’email : Besoin à suivre',exact:true}).click();
  await expect(page.getByRole('dialog')).toContainText('Le message complet sera récupéré à la validation');
  await expect(page.getByLabel('1. Projet de destination')).toHaveValue('');
  await page.getByLabel('1. Projet de destination').selectOption(fixture().project);
  await page.getByLabel('2. Release ouverte').selectOption(release.id);
  await page.getByLabel('3. Titre de la tâche').fill('Vérifier le besoin du client');
  for(const label of ['1. Projet de destination','2. Release ouverte','3. Titre de la tâche']) {
    const control=await page.getByLabel(label).boundingBox();
    expect(control.height).toBeGreaterThanOrEqual(36);
    expect(control.height).toBeLessThan(50);
  }
  await expect(page.locator('.mail-destination')).toContainText('Demandes depuis les emails');
  await page.screenshot({path:'.runtime/email-import.png',fullPage:true,animations:'disabled'});
  await page.getByText('Message original',{exact:true}).click();
  await page.getByRole('button',{name:'Lire le message complet',exact:true}).click();
  await expect(page.locator('.email-body')).toContainText('Texte complet synthétique');
  await page.getByRole('button',{name:'Créer une tâche depuis cet email',exact:true}).click();
  await expect(page.getByRole('heading',{name:'Vérifier le besoin du client',exact:true})).toBeVisible();
  await expect(page.getByRole('status')).toContainText('Tâche créée avec l’email complet');
  await expect(page.locator('.request-detail')).toContainText('Texte complet synthétique');
  await expect(page.getByRole('button',{name:'Lancer l’analyse',exact:true})).toBeVisible();
});

test('configuration pages fit a narrow screen without overflowing controls',async({page})=>{
  await page.setViewportSize({width:400,height:820});
  for(const view of ['settings','connections']) {
    await page.goto('/workbench/?v='+view+'#access='+fixture().token);
    await expect(page.getByRole('heading',{name:view==='settings'?'Paramètres':'Connexions',exact:true,level:1})).toBeVisible();
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
    await page.screenshot({path:'.runtime/'+view+'-mobile.png',fullPage:true});
  }
});
