import { spawn } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { request as httpRequest } from 'node:http';
import { dirname, resolve, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const object = (properties, required = Object.keys(properties)) => ({ type: 'object', properties, required, additionalProperties: false });
const str = { type: 'string' };

export default {
  id: 'workbench', name: 'Projets et releases',
  register(api) {
    const config = api.pluginConfig ?? {};
    const stateDir = config.stateDir;
    if (!stateDir) throw new Error('workbench.stateDir requis');
    const port = config.backendPort ?? 18794;
    const gatewayPort = config.gatewayPort ?? 18793;
    let child;
    async function rpc(action, data = {}) {
      const key = readFileSync(join(stateDir, 'private/session-token'), 'utf8');
      const response = await fetch(`http://127.0.0.1:${port}/workbench/api`, {
        method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Workbench-Key': key },
        body: JSON.stringify({ action, data }), signal: AbortSignal.timeout(30000),
      });
      const result = await response.json();
      if (!response.ok || !result.ok) throw new Error(result.error ?? 'Workbench indisponible');
      return result.result;
    }
    api.registerService({
      id: 'workbench-backend',
      async start() {
        try {
          const response = await fetch(`http://127.0.0.1:${port}/workbench/health`, { signal: AbortSignal.timeout(1200) });
          if (response.ok) return;
        } catch {}
        child = spawn('python3', ['-m', 'backend.server', '--state', stateDir, '--port', String(port), '--gateway-port', String(gatewayPort)],
          { cwd: root, stdio: ['ignore', 'pipe', 'pipe'] });
        child.stdout.on('data', () => {});
        child.stderr.on('data', chunk => api.logger.warn('Service Workbench : ' + String(chunk).slice(0, 500)));
        child.on('error', error => api.logger.error('Démarrage Workbench : ' + error.message));
        for (let attempt = 0; attempt < 40; attempt++) {
          try {
            const response = await fetch(`http://127.0.0.1:${port}/workbench/health`, { signal: AbortSignal.timeout(500) });
            if (response.ok) return;
          } catch {}
          await new Promise(r => setTimeout(r, 100));
        }
        throw new Error('Le service Workbench ne répond pas');
      },
      stop() { if (child && child.exitCode === null) child.kill('SIGTERM'); },
    });
    api.registerHttpRoute({
      path: '/workbench', match: 'prefix', auth: 'plugin',
      async handler(req, res) {
        if (!['127.0.0.1', '::1', '::ffff:127.0.0.1'].includes(req.socket.remoteAddress)) {
          res.writeHead(403); res.end('Interface locale uniquement'); return true;
        }
        // Do not attach the agent credential here: browser access requires its own HttpOnly session.
        const headers = { ...req.headers };
        delete headers['x-workbench-key'];
        delete headers['x-forwarded-host'];
        delete headers['x-forwarded-for'];
        const upstream = httpRequest({ hostname: '127.0.0.1', port, path: req.url, method: req.method, headers }, response => {
          res.writeHead(response.statusCode ?? 502, response.headers);
          response.pipe(res);
        });
        upstream.setTimeout(240000, () => upstream.destroy(new Error('Délai du service dépassé')));
        upstream.on('error', () => { if (!res.headersSent) res.writeHead(502); res.end('Service Workbench indisponible'); });
        req.pipe(upstream);
        return true;
      },
    });
    const tools = [
      ['workbench_status', 'Consulter les projets configurés, demandes entrantes et travaux actifs.', object({}), 'snapshot', result => ({
        projects: result.projects, inbox: result.inbox.map(i => ({ id: i.id, status: i.status, title: i.source.title, match: i.match })),
        jobs: result.jobs.map(j => ({ id: j.id, project: j.project, request: j.request, status: j.status })),
      })],
      ['workbench_project', 'Lire les releases, demandes et environnements déclarés d’un projet.', object({ project: str }), 'project.get'],
      ['workbench_create_release', 'Ouvrir une release locale explicitement demandée par l’utilisateur.', object({ project: str, title: str }), 'release.create'],
      ['workbench_create_request', 'Créer une demande titrée dans une release ouverte, sans lancer de travail.', object({
        project: str, release: str, title: str, description: str, risk: { type: 'string', enum: ['normal', 'renforce'] },
      }, ['project', 'release', 'title', 'description']), 'request.create'],
      ['workbench_transition', 'Proposer une transition de travail. Aucune approbation ni réception humaine accessible.', object({
        project: str, request: str, revision: str,
        action: { type: 'string', enum: ['start-analysis', 'propose-plan', 'verify', 'block'] }, note: str, body: str,
      }, ['project', 'request', 'revision', 'action', 'note']), 'request.transition'],
      ['workbench_ingest', 'Enregistrer un email ou événement effectivement lu. Routage par règles configurées, déduplication par compte et identifiant.', object({ source: {
        type: 'object', properties: Object.fromEntries(['kind', 'account', 'external_id', 'sender', 'title', 'body', 'url', 'date'].map(k => [k, str])),
        required: ['kind', 'account', 'external_id', 'sender', 'title', 'body'], additionalProperties: false,
      } }), 'intake.ingest'],
      ['workbench_library', 'Chercher du texte dans les sources documentaires configurées, en lecture seule.', object({ query: str, entry: str }, ['query']), 'library.search'],
      ['workbench_analyze', 'Lancer une analyse Codex en lecture seule pour une demande autorisée. Peut consommer l’abonnement connecté.', object({ project: str, request: str }), 'agent.analyze'],
      ['workbench_memory', 'Lire le petit index mémoire et retrouver les références utiles sans charger tous les journaux.', object({ project: str, query: str, release: str }, ['project']), 'memory.context'],
      ['workbench_memory_note', 'Proposer une note datée reliée à une source locale. La promotion en fait confirmé reste humaine.', object({ project: str, title: str, body: str, source: str, kind: { type: 'string', enum: ['fact', 'decision', 'hypothese'] } }, ['project', 'title', 'body', 'source']), 'memory.propose'],
    ];
    for (const [name, description, parameters, action, project] of tools) {
      api.registerTool({ name, label: name, description, parameters,
        async execute(_id, params) {
          const result = await rpc(action, params);
          return { content: [{ type: 'text', text: JSON.stringify(project ? project(result) : result) }] };
        },
      });
    }
    api.registerCommand({ name: 'workbench', description: 'Ouvrir les projets et releases locaux', acceptsArgs: false, requireAuth: true,
      handler: () => ({ text: `Projets et releases : http://127.0.0.1:${gatewayPort}/workbench/ — utilisez le lanceur local pour ouvrir une session authentifiée.` }),
    });
    api.registerControlUiDescriptor({ id: 'projects-releases', surface: 'settings', label: 'Projets et releases',
      description: 'Suivi local, terminaux, mémoire Markdown et bibliothèque',
      schema: { url: '/workbench/', command: '/workbench' }, requiredScopes: ['operator.read'],
    });
  },
};
