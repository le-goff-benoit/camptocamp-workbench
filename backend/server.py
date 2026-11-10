"""Authenticated loopback HTTP API, also mounted inside the OpenClaw gateway."""
import argparse
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
import os
from pathlib import Path
import secrets
import signal
import threading
from urllib.parse import parse_qs, urlsplit, unquote

from .agents import Agents
from .core import Workbench
from .google_sources import GoogleSources
from .memory import Memory
from .odoo_releases import OdooReleases
from .documents import Documents
from .dashboard import Dashboard
from .providers import Providers
from .project_sources import ProjectEmails
from .storage import Problem, atomic, read, require, safe, sha
from .terminals import Terminals
from .triage import Triage
from .email_review import EmailReviews

ROOT = Path(__file__).resolve().parents[1]
PREFIX = '/workbench'


class App:
    def __init__(self, state, port=18794, gateway_port=18793):
        self.core = Workbench(state)
        self.port, self.gateway_port = port, gateway_port
        self.allowed_hosts = {f'127.0.0.1:{p}' for p in [port, gateway_port]} | {f'localhost:{p}' for p in [port, gateway_port]}
        self.origins = {'http://' + host for host in self.allowed_hosts}
        self.token_path = safe(self.core.state, 'private/session-token')
        if not self.token_path.exists():
            atomic(self.token_path, secrets.token_urlsafe(40))
        self.token = read(self.token_path)
        self.terminals, self.google = Terminals(self.core), GoogleSources(self.core)
        self.memory, self.documents = Memory(self.core), Documents(self.core)
        self.agents = Agents(self.core)
        self.dashboard = Dashboard(self.core, self.agents)
        self.providers = Providers(self.core, self.dashboard.update_sources)
        self.codex = self.providers.codex
        self.agents.providers = self.providers
        self.project_emails = ProjectEmails(self.core, self.providers.native_call, self.providers)
        self.triage = Triage(self.core, self.providers.ask, lambda: self.providers.label('analysis'))
        self.odoo = OdooReleases(self.core, self.providers.native_call)
        self.email_reviews = EmailReviews(self.core, self.odoo.message, self.email_analyst)
        self.stop = threading.Event()
        threading.Thread(target=self.google.background, args=(self.stop,), daemon=True).start()
        threading.Thread(target=self.providers.background, args=(self.stop,), daemon=True).start()

    def email_analyst(self):
        provider = self.providers.selected('analysis')
        return provider, getattr(self.providers, provider).ask

    def with_triage(self, sources):
        return {**sources, 'emails': self.triage.annotate(sources.get('emails', []))}

    def with_projects(self, rows):
        result = []
        for row in rows:
            project = self.core.project_for(row)
            result.append({**row, 'project': project and project['id'], 'project_name': project and project['name'], 'project_by': project and project['by']})
        return result

    def inbox_emails(self, rows):
        """Flags plus the project each inbox email belongs to, by the configured client rules."""
        return self.with_projects(self.triage.annotate(rows))

    def rpc(self, action, data, *, human=False):
        core = self.core
        if action in {'settings.save', 'release.create', 'mail.to_release', 'request.create', 'request.transition', 'release.close', 'intake.ingest', 'intake.assign', 'agent.analyze'}:
            self.dashboard.cache.clear()
        if action == 'snapshot':
            return {'projects': core.projects(), 'inbox': core.intake_items(), 'jobs': self.agents.list(), 'terminals': self.terminals.list(),
                    'settings': core.settings(), 'google': self.google.status(), 'native_sources': self.dashboard.source_status(),
                    'providers': self.providers.status(), 'workflow': self.odoo.runtime(),
                    'gateway': f'http://127.0.0.1:{self.gateway_port}/', 'version': '0.4.0'}
        if action == 'system.gateway-url':
            require(human, 'Ouverture de la console réservée à l’utilisateur')
            from urllib.parse import quote
            config = json.loads(read(Path.home() / '.openclaw-workbench/openclaw.json'))
            credential = config.get('gateway', {}).get('auth', {}).get('token')
            require(isinstance(credential, str), 'Utilisez le lanceur natif OpenClaw pour sa connexion')
            return {'url': f'http://127.0.0.1:{self.gateway_port}/#token=' + quote(credential, safe='')}
        if action == 'dashboard.get':
            result = dict(self.dashboard.snapshot())
            result['emails'] = self.inbox_emails(result['emails'])
            result['next_events'] = self.with_projects(result['next_events'])
            result['past_events'] = self.with_projects(result['past_events'])
            return result
        if action == 'email.triage':
            require(human, 'Analyse des emails réservée à l’interface utilisateur')
            if data.get('project'):
                rows = self.project_emails.cached(data['project'])['emails']
                return self.triage.analyze(rows, bool(data.get('force')))
            result = self.triage.analyze(self.dashboard.snapshot()['emails'], bool(data.get('force')))
            result['emails'] = self.inbox_emails(result['emails'])
            return result
        if action == 'email.review':
            require(human, 'Lecture et analyse d’un email réservées à l’interface utilisateur')
            return self.email_reviews.get(data.get('message'), data.get('force', False))
        if action == 'projects.refresh':
            require(human, 'Nouvelle découverte réservée à l’interface')
            core.refresh_projects()
            self.dashboard.cache.clear()
            return core.projects()
        if action == 'sources.refresh':
            require(human, 'Actualisation réservée à l’interface utilisateur')
            result = self.providers.refresh_sources()
            self.dashboard.cache.clear()
            return result
        if action == 'providers.check':
            require(human, 'Vérification des connexions réservée à l’interface utilisateur')
            require(data.get('provider') == 'claude', 'Fournisseur inconnu')
            return self.providers.claude.check()
        if action == 'dashboard.sources':
            result = self.dashboard.update_sources(data.get('emails'), data.get('events'))
            self.dashboard.cache.clear()
            return result
        if action == 'release.overview':
            return self.dashboard.overview(data['project'], data['release'])
        if action == 'project.get':
            return {'project': core.project(data['project']), 'releases': core.releases(data['project']),
                    'requests': core.requests(data['project']), 'environments': core.environments(data['project']),
                    'email_sources': self.with_triage(self.project_emails.cached(data['project']))}
        if action == 'project.emails':
            require(human, 'Lecture Gmail réservée à l’interface utilisateur')
            return self.with_triage(self.project_emails.fetch(data['project'], bool(data.get('force'))))
        if action == 'environment.add':
            require(human, 'Ajout d’environnement réservé à l’utilisateur')
            return core.add_environment(data['project'], data['name'], data['kind'], data.get('url', ''), data.get('path', ''), data.get('series', ''))
        if action == 'settings.save':
            require(human, 'Réglage réservé à l’interface utilisateur')
            return core.save_settings(data['settings'])
        if action == 'release.create':
            if core.project(data['project']).get('odoo'):
                require(human, 'Ouverture de release Odoo réservée à l’utilisateur')
                if self.odoo.runtime()['available']:
                    return self.odoo.open(data['project'], data['title'])
                require(not any(r['legacy'] and r['status'] == 'ouverte' for r in core.releases(data['project'])),
                        'Une release historique est ouverte. Consultez-la et utilisez son moteur pour la poursuivre avant d’ouvrir une release intégrée.')
            return core.create_release(data['project'], data['title'])
        if action == 'release.board':
            return self.odoo.board(data['project'], data['release'])
        if action == 'mail.to_release':
            require(human, 'Rattachement d’un email réservé à l’utilisateur')
            project, release, message_id = data['project'], data['release'], data['message']
            if '/' in str(release):
                return self.odoo.add_mail(project, release, message_id)
            source_key = sha('gmail\n' + message_id)
            existing = next((r for r in core.requests(project) if r.get('source', {}).get('key') == source_key), None)
            if existing:
                return {'added': False, 'request': existing['id'], 'release': existing['release']}
            message, subject = self.odoo.message(message_id)
            body = message.get_body(preferencelist=('plain', 'html'))
            text = f"De : {message.get('From', '')}\nDate : {message.get('Date', '')}\n\n" + (body.get_content() if body else '')
            request = core.create_request(project, release, data.get('title') or subject or 'Email reçu', text,
                                          source={'kind': 'email', 'external_id': message_id, 'sender': str(message.get('From', '')),
                                                  'date': str(message.get('Date', '')), 'key': source_key})
            return {'added': True, 'subject': subject, 'request': request['id'], 'release': request['release']}
        if action == 'mail.preview':
            require(human, 'Lecture du message complet réservée à l’interface utilisateur')
            message, subject = self.odoo.message(data['message'])
            body = message.get_body(preferencelist=('plain', 'html'))
            text = body.get_content() if body else ''
            if body and body.get_content_subtype() == 'html':
                from .native_sources import MailText
                parser = MailText(); parser.feed(text); text = ''.join(parser.text)
            return {'subject': subject, 'body': text}
        if action == 'request.create':
            return core.create_request(data['project'], data['release'], data['title'], data.get('description', ''),
                                       dependencies=data.get('depends_on'), risk=data.get('risk', 'normal'))
        if action == 'request.get':
            return core.request(data['project'], data['request'])
        if action == 'request.transition':
            return core.transition(data['project'], data['request'], data['action'], data['revision'], human=human,
                                   note=data.get('note', ''), checks=data.get('checks'), body=data.get('body'))
        if action == 'release.close':
            return core.close_release(data['project'], data['release'], data['note'], human=human)
        if action == 'document.get':
            return core.document(data['project'], data['kind'], data.get('release'))
        if action == 'document.save':
            require(human, 'Édition du document réservée à l’interface')
            return core.save_document(data['project'], data['kind'], data['body'], data['revision'], data.get('release'))
        if action == 'proof.save':
            require(human, 'Dépôt de preuve réservé à l’interface')
            require(data['name'].endswith('.md') and '/' not in data['name'] and '\\' not in data['name'], 'Nom de preuve Markdown attendu')
            folder = core.release_folder(data['project'], data['release'])
            path = safe(folder, 'preuves/' + data['name'])
            require(not path.exists(), 'Une preuve de ce nom existe déjà')
            require(isinstance(data['body'], str) and 0 < len(data['body']) <= 200000, 'Preuve vide ou trop longue')
            atomic(path, data['body'] + '\n')
            return {'path': 'preuves/' + data['name'], 'sha256': sha(read(path))}
        if action == 'proof.list':
            folder = core.release_folder(data['project'], data['release'])
            base = safe(folder, 'preuves')
            if not base.is_dir():
                return []
            return sorted('preuves/' + p.name for p in base.iterdir() if p.is_file() and not p.is_symlink() and not p.name.startswith('.'))
        if action == 'agent.analyze':
            return self.agents.start(data['project'], data['request'])
        if action == 'terminal.open':
            require(human, 'Ouverture d’un terminal réservée à l’interface')
            prompt = ''
            if data.get('request'):
                record = core.request(data['project'], data['request'])
                prompt = f'Demande {record["id"]}, release {record["release"]}. Lis MEMORY.md et memory/releases/{record["release"]}/demandes/{record["id"]}.md. '
                prompt += ('Le plan a été approuvé. Réalise le périmètre autorisé, conserve les preuves des contrôles ciblés. ' if record['stage'] == 'realisation' else 'Analyse le besoin en lecture seule et propose le travail nécessaire. ')
                prompt += 'Pour cette demande Workbench, conserve le parcours simple et ses fichiers Markdown, sans créer en parallèle un second moteur de suivi. '
                prompt += 'Un responsable applique les rôles utiles ; aucune délégation systématique. Pour Odoo, conserve le briefing, la série du projet, les règles de droits et données, installation/update et tests ciblés, puis recette globale à la clôture. '
                prompt += 'N’écris jamais en production sans accord explicite sur chaque opération.'
            return self.terminals.open(data['project'], data.get('kind', 'shell'), prompt, environment=data.get('environment'))
        if action == 'terminal.output':
            require(human, 'Lecture du terminal réservée à l’interface')
            return self.terminals.output(data['id'], data.get('cursor', 0))
        if action == 'terminal.outputs':
            require(human, 'Lecture du terminal réservée à l’interface')
            return self.terminals.outputs(data.get('cursors', {}))
        if action == 'terminal.write':
            require(human, 'Entrée terminal réservée à l’interface')
            return self.terminals.write(data['id'], data['data'])
        if action == 'terminal.resize':
            require(human, 'Réglage terminal réservé à l’interface')
            return self.terminals.resize(data['id'], data['rows'], data['cols'])
        if action == 'terminal.close':
            require(human, 'Arrêt terminal réservé à l’interface')
            return self.terminals.close(data['id'])
        if action == 'library.search':
            result = core.library_search(data['query'], data.get('entry'))
            result['documents'] = self.documents.search(data['query'])
            result['coverage'] = 'Recherche textuelle locale et index PDF/Word construit depuis la bibliothèque. Les documents modifiés doivent être réindexés.'
            return result
        if action == 'library.index':
            require(human, 'Indexation réservée à l’utilisateur')
            return self.documents.index(data['entry'])
        if action == 'memory.context':
            return self.memory.context(data['project'], data.get('query', ''), data.get('release'))
        if action == 'memory.notes':
            return self.memory.notes(data['project'])
        if action == 'memory.propose':
            return self.memory.propose(data['project'], data['title'], data['body'], data['source'], data.get('kind', 'fact'))
        if action == 'memory.confirm':
            return self.memory.confirm(data['project'], data['id'], human=human)
        if action == 'intake.ingest':
            return core.ingest(data['source'])
        if action == 'intake.assign':
            require(human, 'Rattachement réservé à l’utilisateur en cas d’ambiguïté')
            return core.assign_intake(data['id'], data['project'], data['release'])
        if action == 'intake.eml':
            require(human, 'Import réservé à l’utilisateur')
            return core.import_email(data['content'], data['account'])
        if action == 'google.client':
            require(human, 'Configuration OAuth réservée à l’utilisateur')
            return self.google.set_client(data['client'])
        if action == 'google.connect':
            require(human, 'Connexion réservée à l’utilisateur')
            return self.google.begin(f'http://127.0.0.1:{self.port}/workbench/oauth/google/callback')
        if action == 'google.sync':
            require(human, 'Synchronisation manuelle réservée à l’utilisateur')
            return self.google.synchronize()
        raise Problem('Commande inconnue')


def handler(app):
    class Handler(BaseHTTPRequestHandler):
        server_version = 'Workbench/0.4'

        def log_message(self, *_args):
            pass  # Never log URLs, OAuth codes, terminal input or source contents.

        def reply(self, *args, **kwargs):
            try:
                return self._reply(*args, **kwargs)
            except (BrokenPipeError, ConnectionResetError):
                return  # A navigation closed this response; do not retry a completed mutation.

        def _reply(self, status, data, content_type='application/json; charset=utf-8', cookie=None):
            if isinstance(data, (dict, list)):
                data = json.dumps(data, ensure_ascii=False).encode()
            elif isinstance(data, str):
                data = data.encode()
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'self'; base-uri 'none'; form-action 'self'")
            if cookie:
                self.send_header('Set-Cookie', cookie)
            self.end_headers()
            self.wfile.write(data)

        def host_ok(self):
            return self.headers.get('Host', '') in app.allowed_hosts

        def authenticated(self):
            if not self.host_ok():
                return False, False
            cookie = SimpleCookie()
            try:
                cookie.load(self.headers.get('Cookie', ''))
            except Exception:
                return False, False
            session = cookie.get('workbench_session')
            ui = bool(session and secrets.compare_digest(session.value, app.token))
            agent = secrets.compare_digest(self.headers.get('X-Workbench-Key', ''), app.token)
            return ui or agent, ui

        def do_GET(self):
            if not self.host_ok():
                return self.reply(403, {'error': 'Hôte non autorisé'})
            parsed = urlsplit(self.path)
            path = unquote(parsed.path)
            if path == PREFIX + '/oauth/google/callback':
                query = parse_qs(parsed.query)
                try:
                    app.google.callback(query.get('state', [''])[0], query.get('code', [''])[0])
                    return self.reply(200, 'Compte Google connecté. Vous pouvez revenir dans Workbench.', 'text/plain; charset=utf-8')
                except Exception:
                    return self.reply(400, 'Connexion Google refusée ou expirée. Recommencez depuis Connexions.', 'text/plain; charset=utf-8')
            if path == PREFIX + '/health':
                return self.reply(200, {'ok': True, 'version': '0.4.0'})
            if path in {PREFIX, PREFIX + '/', PREFIX + '/index.html'}:
                return self.reply(200, (ROOT / 'web/index.html').read_bytes(), 'text/html; charset=utf-8')
            if path.startswith(PREFIX + '/static/'):
                try:
                    target = safe(ROOT / 'web', path[len(PREFIX + '/static/'):])
                    require(target.is_file() and target.suffix in {'.js', '.mjs', '.css', '.svg', '.png', '.ttf', '.woff2'}, 'Ressource inconnue')
                    return self.reply(200, target.read_bytes(), mimetypes.guess_type(target)[0] or 'application/octet-stream')
                except (Problem, OSError):
                    return self.reply(404, {'error': 'Ressource inconnue'})
            return self.reply(404, {'error': 'Route inconnue'})

        def do_POST(self):
            try:
                require(self.host_ok(), 'Hôte non autorisé')
                require(self.headers.get('Origin') in app.origins or (not self.headers.get('Origin') and self.headers.get('X-Workbench-Key')), 'Origine non autorisée')
                require(self.headers.get('Content-Type', '').split(';')[0] == 'application/json', 'JSON requis')
                size = int(self.headers.get('Content-Length', '0'))
                require(0 < size <= 2_000_000, 'Requête trop volumineuse ou vide')
                data = json.loads(self.rfile.read(size))
                path = urlsplit(self.path).path
                if path == PREFIX + '/session':
                    require(secrets.compare_digest(str(data.get('token', '')), app.token), 'Accès refusé')
                    return self.reply(200, {'ok': True}, cookie=f'workbench_session={app.token}; HttpOnly; SameSite=Strict; Path=/workbench')
                allowed, ui = self.authenticated()
                if not allowed:
                    return self.reply(401, {'error': 'Ouvrez Workbench avec son lanceur local pour vous authentifier.'})
                require(path == PREFIX + '/api', 'Route inconnue')
                human = ui and self.headers.get('X-Workbench-UI') == '1' and self.headers.get('Origin') in app.origins
                return self.reply(200, {'ok': True, 'result': app.rpc(data['action'], data.get('data', {}), human=human)})
            except (Problem, ValueError, KeyError, TypeError, OSError) as error:
                return self.reply(400, {'ok': False, 'error': str(error)[:700]})
            except Exception:
                return self.reply(500, {'ok': False, 'error': 'Erreur interne ; opération non confirmée. Rechargez le suivi avant de réessayer.'})
    return Handler


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--state', required=True)
    parser.add_argument('--port', type=int, default=18794)
    parser.add_argument('--gateway-port', type=int, default=18793)
    args = parser.parse_args()
    app = App(args.state, args.port, args.gateway_port)
    server = ThreadingHTTPServer(('127.0.0.1', args.port), handler(app))
    server.daemon_threads = True
    print(f'Workbench prêt sur http://127.0.0.1:{args.port}/workbench/', flush=True)
    def stop(*_args):
        app.stop.set()
        app.terminals.shutdown()
        app.providers.shutdown()
        threading.Thread(target=server.shutdown, daemon=True).start()
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    server.serve_forever()


if __name__ == '__main__':
    main()
