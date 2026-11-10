"""Projects, releases, requests, documentary library and deterministic intake."""
from datetime import datetime, timezone
from email import policy
from email.parser import BytesParser
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import uuid
from urllib.parse import urlsplit, urlunsplit

from .storage import Problem, atomic, decode, encode, locked, read, require, safe, sha

STAGES = ['nouvelle', 'analyse', 'plan', 'realisation', 'verification', 'terminee']
SKIP = {'.git', 'node_modules', 'odoo-sources', 'nobackup', '.cache', '.venv', 'venv', 'filestore', 'build-artifacts', 'dist', '__pycache__'}
DOCS = {'memory': 'MEMORY.md', 'journal': 'JOURNAL.md', 'plan': 'plan.md', 'decisions': 'decisions.md', 'release-journal': 'journal.md', 'qa': 'qa.md', 'demande': 'demande.md'}


def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def slug(text):
    value = re.sub(r'[^a-z0-9_-]+', '-', text.casefold()).strip('-')[:65]
    require(value, 'Un titre est nécessaire')
    return value


def clean(text, size=10000):
    require(isinstance(text, str) and len(text) <= size, 'Texte absent ou trop long')
    return text.replace('\x00', '').strip()


def git(path, *args):
    result = subprocess.run(['git', '-C', str(path), *args], capture_output=True, text=True, timeout=8,
                            env={**os.environ, 'GIT_OPTIONAL_LOCKS': '0'})
    return result.stdout.strip() if result.returncode == 0 else ''


def repository_key(remote):
    """host/owner/repo of a Git remote, without scheme, credentials or .git suffix."""
    remote = (remote or '').strip()
    scp = re.fullmatch(r'[\w.-]+@([\w.-]+):(.+)', remote)
    if scp:
        host, path = scp[1], scp[2]
    else:
        parts = urlsplit(remote)
        host, path = parts.hostname or '', parts.path
    path = path.strip('/').removesuffix('.git')
    return f'{host.casefold()}/{path.casefold()}' if host and path else ''


def source_fingerprint(root):
    """Fingerprint actual local source contents, excluding mutable workflow records."""
    root = Path(root)
    result = subprocess.run(['git', '-C', str(root), 'ls-files', '-co', '--exclude-standard', '-z'], capture_output=True, timeout=10)
    require(result.returncode == 0, 'État Git inaccessible pour la réception')
    paths = sorted(set(result.stdout.decode('utf-8', 'replace').split('\0')) - {''})
    require(len(paths) < 50000, 'Dépôt trop volumineux pour cette réception locale')
    digest, total = hashlib.sha256(), 0
    suffixes = {'.py', '.js', '.mjs', '.cjs', '.ts', '.tsx', '.xml', '.csv', '.yml', '.yaml', '.json', '.toml', '.ini', '.sh', '.css', '.html', '.md', '.rst', '.txt'}
    for relative in paths:
        parts = Path(relative).parts
        if not parts or parts[0] in {'memory', '.odoo-agents', 'node_modules', 'build-artifacts', '.runtime', 'MEMORY.md', 'JOURNAL.md'} or Path(relative).suffix not in suffixes:
            continue
        path = safe(root, relative)
        digest.update(relative.encode())
        if path.is_file():
            total += path.stat().st_size
            require(total <= 100_000_000, 'Sources trop volumineuses pour cette réception locale')
            digest.update(path.read_bytes())
        else:
            digest.update(b'<deleted>')
    return digest.hexdigest()


class Workbench:
    def __init__(self, state):
        self.state = Path(state).resolve()
        self._projects_cache = None
        self.state.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.settings_path = self.state / 'settings.json'
        if not self.settings_path.exists():
            odoo = Path.home() / 'odoo-sources'
            self.save_settings({'roots': [], 'depth': 2, 'projects': {}, 'library': [
                {'id': 'odoo', 'name': 'Sources Odoo', 'path': str(odoo), 'category': 'Odoo', 'readonly': True}
            ] if odoo.exists() else [], 'intake': {'automatic': True, 'poll_minutes': 15, 'enabled': False}})

    def settings(self):
        return json.loads(read(self.settings_path))

    def save_settings(self, value):
        providers = value.setdefault('providers', {})
        require(isinstance(providers, dict), 'Fournisseurs invalides')
        for purpose in ('sources', 'analysis'):
            providers.setdefault(purpose, 'codex')
            require(providers[purpose] in {'codex', 'claude'}, 'Fournisseur inconnu : choisissez Codex ou Claude Code')
        sync = value.setdefault('source_sync', {'enabled': False})
        require(isinstance(sync, dict) and isinstance(sync.get('enabled', False), bool), 'Synchronisation automatique invalide')
        sync['interval_seconds'] = 300
        workflow = clean(value.get('workflow_home', ''), 2000)
        if workflow:
            require(Path(workflow).expanduser().is_dir(), 'Le dossier du moteur de workflow n’existe pas')
            workflow = str(Path(workflow).expanduser().resolve())
        value['workflow_home'] = workflow
        require(isinstance(value.get('roots'), list) and len(value['roots']) <= 12, 'Douze racines maximum')
        for root in value['roots']:
            require(Path(root).expanduser().is_dir(), f'Dossier inaccessible : {root}')
        value['roots'] = list(dict.fromkeys(str(Path(p).expanduser().resolve()) for p in value['roots']))
        require(0 <= int(value.get('depth', 2)) <= 4, 'Profondeur entre 0 et 4')
        require(isinstance(value.get('projects', {}), dict), 'Configuration des projets invalide')
        for key, project in value.get('projects', {}).items():
            require(isinstance(project, dict), 'Projet invalide')
            project['mail_query'] = clean(project.get('mail_query', ''), 2000)
            for field in ['emails', 'domains']:
                require(isinstance(project.get(field, []), list), 'Adresses et domaines : listes attendues')
                project[field] = [clean(item, 250).casefold() for item in project.get(field, []) if clean(item, 250)]
        for entry in value.get('library', []):
            require(Path(entry['path']).expanduser().is_dir(), 'Racine documentaire inaccessible')
            entry['path'] = str(Path(entry['path']).expanduser().resolve())
            entry['readonly'] = True
        with locked(self.state):
            atomic(self.settings_path, json.dumps(value, ensure_ascii=False, indent=2) + '\n')
        self._projects_cache = None
        return value

    def projects(self):
        import time
        # Discovery spawns several Git processes per repository: keep it for a minute.
        # Settings changes and the explicit refresh action invalidate it.
        if self._projects_cache and time.monotonic() - self._projects_cache[0] < 60:
            return self._projects_cache[1]
        settings, found, visited = self.settings(), [], set()

        def visit(folder, depth):
            try:
                if folder.is_symlink():
                    return
                path = folder.resolve()
                if str(path) in visited:
                    return
                visited.add(str(path))
                # A container (notably $HOME) can itself be a Git repository.
                # Continue the bounded traversal so it cannot hide nested projects.
                if (path / '.git').exists() and path != Path.home().resolve():
                    key = hashlib.sha256(str(path).encode()).hexdigest()[:16]
                    pref = settings.get('projects', {}).get(key, {})
                    valid = git(path, 'rev-parse', '--show-toplevel') == str(path)
                    common = git(path, 'rev-parse', '--path-format=absolute', '--git-common-dir')
                    found.append({'id': key, 'path': str(path), 'name': pref.get('name') or path.name,
                                  'branch': git(path, 'branch', '--show-current'),
                                  'common_git': common, 'family': repository_key(git(path, 'remote', 'get-url', 'origin')) or common,
                                  'emails': pref.get('emails', []), 'domains': pref.get('domains', []),
                                  'odoo': (path / '.odoo-agents').is_dir(), 'available': valid,
                                  'warning': '' if valid else 'Dépôt Git non reconnu : vérifier le fichier .git ou le worktree.'})
                if depth:
                    for child in sorted(path.iterdir()):
                        if not child.name.startswith('.') and child.name not in SKIP and child.is_dir():
                            visit(child, depth - 1)
            except (OSError, subprocess.TimeoutExpired):
                return

        for root in settings['roots']:
            visit(Path(root), int(settings.get('depth', 2)))
        # Worktrees and clones of one repository share the client's rules: a checkout
        # without its own addresses inherits them, but never becomes a second match.
        for project in found:
            project['criteria_from'] = ''
            if project['emails'] or project['domains'] or not project['family']:
                continue
            source = next((p for p in found if p is not project and p['family'] == project['family']
                           and (p['emails'] or p['domains']) and not p.get('criteria_from')), None)
            if source:
                project.update(emails=list(source['emails']), domains=list(source['domains']), criteria_from=source['name'])
        result = sorted(found, key=lambda item: item['name'].casefold())
        self._projects_cache = (time.monotonic(), result)
        return result

    def refresh_projects(self):
        self._projects_cache = None

    def project(self, project_id):
        result = next((p for p in self.projects() if p['id'] == project_id), None)
        require(result, 'Projet introuvable. Vérifiez le dossier de découverte dans les paramètres.')
        remote = git(result['path'], 'remote', 'get-url', 'origin')
        match = re.fullmatch(r'git@github\.com:([^\s?#]+)', remote)
        parsed = urlsplit(remote)
        repository = match[1] if match else parsed.path.lstrip('/') if parsed.hostname == 'github.com' else ''
        repository = repository[:-4] if repository.endswith('.git') else repository
        url = 'https://github.com/' + repository if re.fullmatch(r'[\w.-]+/[\w.-]+', repository) else ''
        return {**result, 'github_url': url}

    def root(self, project_id):
        return Path(self.project(project_id)['path'])

    def releases(self, project_id):
        root, result = self.root(project_id), []
        base = safe(root, 'memory/releases')
        if base.is_dir():
            for folder in sorted(base.iterdir(), reverse=True):
                if folder.is_symlink() or not folder.is_dir():
                    continue
                marker = safe(base, folder.name + '/release.md')
                if marker.is_file():
                    try:
                        meta, body = decode(read(marker))
                        result.append({**meta, 'legacy': False, 'path': str(folder.relative_to(root))})
                    except (ValueError, OSError):
                        continue
        for name in ['changelog', 'release']:
            old = safe(root, name)
            if old.is_dir():
                for folder in sorted(old.iterdir(), reverse=True):
                    if folder.is_symlink() or not folder.is_dir():
                        continue
                    doc = safe(old, folder.name + '/README.md')
                    if doc.is_file():
                        content = read(doc)
                        result.append({'id': name + '/' + folder.name, 'title': folder.name,
                                       'status': 'ouverte' if re.search(r'<!--\s*(release ouverte|lot ouvert)\s*-->', content, re.I) else 'archive',
                                       'legacy': True, 'path': str(folder.relative_to(root))})
        return result

    def release_folder(self, project_id, release_id):
        require(re.fullmatch(r'[a-zA-Z0-9_-]+', release_id or ''), 'Identifiant de release invalide')
        folder = safe(self.root(project_id), 'memory/releases/' + release_id)
        require((folder / 'release.md').is_file(), 'Release introuvable')
        return folder

    def create_release(self, project_id, title):
        root, title = self.root(project_id), ' '.join(clean(title, 200).splitlines())
        require(title, 'Titre requis')
        rid = datetime.now().strftime('%Y-%m-%d') + '_' + slug(title) + '_' + uuid.uuid4().hex[:5]
        folder = safe(root, 'memory/releases/' + rid)
        with locked(self.state / 'locks' / project_id):
            meta = {'id': rid, 'title': title, 'status': 'ouverte', 'created': now()}
            atomic(safe(root, f'memory/releases/{rid}/release.md'), encode(meta, f'# {title}\n\nObjectif à préciser dans le plan.'))
            for name, body in {
                'plan.md': f'# Plan — {title}\n\n## Objectif\n\n{title}\n\n## Critères de réception\n\nDéfinis dans les analyses des demandes.\n\n## Travaux\n\nLes propositions ci-dessous sont synchronisées depuis les demandes.\n\n<!-- workbench:plans -->\nAucun plan proposé pour le moment.\n<!-- /workbench:plans -->',
                'decisions.md': '# Décisions\n\nLes décisions humaines et leurs motifs sont conservés ici.',
                'journal.md': f'# Journal de release\n\n- {now()} — Release ouverte.',
                'qa.md': '# Recette de release\n\nLes contrôles et leurs preuves sont ajoutés à la réception.',
            }.items():
                atomic(safe(folder, name), body + '\n')
            if not safe(root, 'MEMORY.md').exists():
                atomic(safe(root, 'MEMORY.md'), '# Mémoire du projet\n\nFaits durables et décisions acceptées. Les détails sont dans memory/releases/.\n')
            self.append(safe(root, 'JOURNAL.md'), f'Release « {title} » ouverte : memory/releases/{rid}/.')
        return meta

    def append(self, path, message):
        content = read(path) if path.exists() else '# Journal\n'
        atomic(path, content.rstrip() + f'\n\n- {now()} — {message}\n')

    def requests(self, project_id, release_id=None):
        result = []
        releases = [r for r in self.releases(project_id) if not r['legacy'] and (not release_id or r['id'] == release_id)]
        for release in releases:
            folder = self.release_folder(project_id, release['id'])
            requests = safe(folder, 'demandes')
            if not requests.is_dir():
                continue
            for path in sorted(requests.glob('*.md')):
                safe(folder, str(path.relative_to(folder)))
                try:
                    content = read(path)
                    meta, body = decode(content)
                    result.append({**meta, 'body': body, 'revision': sha(content), 'release_title': release['title']})
                except (ValueError, OSError):
                    continue
        return result

    def request(self, project_id, request_id):
        require(re.fullmatch(r'D-[a-f0-9]{12}', request_id or ''), 'Identifiant de demande invalide')
        result = next((r for r in self.requests(project_id) if r['id'] == request_id), None)
        require(result, 'Demande introuvable')
        return result

    def request_path(self, project_id, record):
        return safe(self.release_folder(project_id, record['release']), 'demandes/' + record['id'] + '.md')

    def create_request(self, project_id, release_id, title, description='', source=None, dependencies=None, risk='normal'):
        folder, title = self.release_folder(project_id, release_id), ' '.join(clean(title, 220).splitlines())
        require(title, 'Titre requis')
        require(decode(read(safe(folder, 'release.md')))[0]['status'] == 'ouverte', 'Release clôturée')
        require(risk in {'normal', 'renforce'}, 'Risque invalide')
        dependencies = dependencies or []
        for dep in dependencies:
            self.request(project_id, dep)
        with locked(self.state / 'locks' / project_id):
            if source:
                existing = next((r for r in self.requests(project_id) if r.get('source', {}).get('key') == source.get('key')), None)
                if existing:
                    return existing
            meta = {'id': 'D-' + uuid.uuid4().hex[:12], 'title': title, 'release': release_id,
                    'stage': 'nouvelle', 'status': 'a-faire', 'risk': risk, 'created': now(), 'updated': now(),
                    'depends_on': dependencies, 'source': {k: v for k, v in (source or {}).items() if k in {'kind', 'account', 'external_id', 'sender', 'url', 'date', 'key'}}, 'checks': [], 'decisions': []}
            body = f'# {title}\n\n## Demande\n\n{clean(description, 100000)}\n\n## Analyse\n\nÀ réaliser.\n\n## Critères\n\nÀ préciser.\n\n## Résultat\n\nÀ produire.'
            atomic(safe(folder, 'demandes/' + meta['id'] + '.md'), encode(meta, body))
            self.append(safe(folder, 'journal.md'), f'Demande {meta["id"]} créée : {title}.')
        return {**meta, 'body': body}

    def transition(self, project_id, request_id, action, revision, *, human=False, note='', checks=None, body=None):
        with locked(self.state / 'locks' / project_id):
            record = self.request(project_id, request_id)
            require(record['revision'] == revision, 'La demande a changé. Rechargez avant de continuer.')
            require(record['status'] != 'terminee' or action == 'reopen', 'Demande terminée ; demander un réexamen explicite.')
            folder = self.release_folder(project_id, record['release'])
            require(decode(read(safe(folder, 'release.md')))[0]['status'] == 'ouverte', 'Release clôturée')
            note = clean(note)
            stage = record['stage']
            if action == 'reopen':
                require(human and stage == 'terminee' and note, 'Réexamen humain motivé requis')
                record.setdefault('receipt_history', []).append({k: record.get(k) for k in ['received', 'checks', 'source_fingerprint']})
                record.update(stage='verification', status='a-verifier', checks=[])
            elif action == 'start-analysis':
                require(stage == 'nouvelle', 'Analyse déjà démarrée')
                record.update(stage='analyse', status='en-cours')
            elif action == 'propose-plan':
                require(stage in {'analyse', 'plan'}, 'Analyser la demande avant de proposer le plan')
                require(note, 'Résumé du plan requis')
                record.update(stage='plan', status='attente-validation')
                record['plan_revision'] = sha(note)
                record['plan_proposal'] = note
            elif action == 'approve-plan':
                require(human and stage == 'plan' and record['status'] == 'attente-validation', 'Décision humaine sur le plan attendue')
                for dep in record['depends_on']:
                    require(self.request(project_id, dep)['status'] == 'terminee', 'Une dépendance reste à recevoir')
                record['decisions'].append({'at': now(), 'kind': 'plan', 'proposal': record['plan_revision'], 'note': note})
                record.update(stage='realisation', status='en-cours')
                self.append(safe(folder, 'decisions.md'), f'Plan approuvé par l’utilisateur pour {request_id}, empreinte {record["plan_revision"][:12]}. {note}')
            elif action == 'verify':
                require(stage == 'realisation', 'Réalisation attendue avant la vérification')
                require(note, 'Résultat de réalisation requis')
                record.update(stage='verification', status='a-verifier')
            elif action == 'receive':
                require(human and stage == 'verification', 'Réception humaine attendue')
                require(note and checks and all(c.get('outcome') == 'pass' and c.get('proof') for c in checks), 'Contrôles réussis et preuves requis')
                require(record.get('risk') != 'renforce' or any(c.get('independent') is True for c in checks), 'Risque renforcé : revue indépendante requise')
                for check in checks:
                    proof = safe(folder, check['proof'])
                    require(proof.is_file() and read(proof).strip(), 'Preuve locale absente ou vide')
                    check['sha256'] = sha(read(proof))
                record.update(stage='terminee', status='terminee', checks=checks, received=now(),
                              source_fingerprint=source_fingerprint(self.root(project_id)))
                self.append(safe(folder, 'decisions.md'), f'Réception humaine de {request_id}. {note}')
            elif action == 'block':
                require(note, 'Motif du blocage requis')
                record.update(status='bloquee', blocked_reason=note)
            elif action == 'resume':
                require(human and record['status'] == 'bloquee', 'Reprise humaine d’une demande bloquée attendue')
                record.update(status='attente-validation' if stage == 'plan' else 'a-verifier' if stage == 'verification' else 'en-cours')
            else:
                raise Problem('Transition inconnue')
            if body is not None:
                record['body'] = clean(body, 100000)
            record['updated'] = now()
            content = record.pop('body')
            for key in ['revision', 'release_title']:
                record.pop(key, None)
            atomic(self.request_path(project_id, record), encode(record, content))
            if action in {'propose-plan', 'approve-plan'}:
                self.sync_plan(project_id, record['release'])
            summary = note.splitlines()[0][:180] if note else ''
            self.append(safe(folder, 'journal.md'), f'{request_id} : {action}. {summary} — détail : demandes/{request_id}.md')
        return self.request(project_id, request_id)

    def sync_plan(self, project_id, release_id):
        path = safe(self.release_folder(project_id, release_id), 'plan.md')
        text = read(path)
        plans = []
        for request in self.requests(project_id, release_id):
            if request.get('plan_proposal'):
                accepted = any(d['kind'] == 'plan' and d['proposal'] == request.get('plan_revision') for d in request['decisions'])
                plans.append(f'### {request["id"]} — {request["title"]}\n\n' + ('Plan approuvé.' if accepted else 'Proposition à décider.') + '\n\n' + request['plan_proposal'] + f'\n\n[Analyse et critères](demandes/{request["id"]}.md)')
        block = '<!-- workbench:plans -->\n' + '\n\n'.join(plans) + '\n<!-- /workbench:plans -->'
        if '<!-- workbench:plans -->' in text:
            text = re.sub(r'<!-- workbench:plans -->.*?<!-- /workbench:plans -->', lambda _: block, text, flags=re.S)
        else:
            text += '\n\n' + block
        atomic(path, text.rstrip() + '\n')

    def close_release(self, project_id, release_id, note, *, human=False):
        require(human and clean(note), 'Clôture humaine motivée requise')
        folder = self.release_folder(project_id, release_id)
        with locked(self.state / 'locks' / project_id):
            requests = self.requests(project_id, release_id)
            require(requests and all(r['status'] == 'terminee' for r in requests), 'Toutes les demandes doivent être reçues')
            for request in requests:
                require(request.get('source_fingerprint') == source_fingerprint(self.root(project_id)),
                        'Les sources ont changé depuis une réception ; vérifier à nouveau les demandes concernées')
                for check in request.get('checks', []):
                    proof = safe(folder, check['proof'])
                    require(proof.is_file() and sha(read(proof)) == check['sha256'], 'Une preuve a changé depuis la réception')
            marker = safe(folder, 'release.md')
            meta, body = decode(read(marker))
            require(meta['status'] == 'ouverte', 'Release déjà clôturée')
            meta.update(status='cloturee', closed=now())
            atomic(marker, encode(meta, body))
            self.append(safe(folder, 'decisions.md'), 'Clôture de la release par l’utilisateur. ' + note)
            self.append(safe(self.root(project_id), 'JOURNAL.md'), f'Release {release_id} clôturée. {note}')
        return meta

    def document(self, project_id, kind, release_id=None):
        require(kind in DOCS, 'Document inconnu')
        root = self.root(project_id)
        if kind in {'memory', 'journal'}:
            path = safe(root, DOCS[kind])
            canonical = safe(root, '.odoo-agents/' + ('PROJECT.md' if kind == 'memory' else 'JOURNAL.md'))
            if not path.exists() and canonical.is_file():
                # Odoo projects keep their memory with the agents; Workbench only reads it.
                content = read(canonical)
                return {'path': str(canonical.relative_to(root)), 'body': content, 'revision': sha(content), 'readonly': True}
            content = read(path) if path.exists() else ''
            return {'path': str(path.relative_to(root)), 'body': content, 'revision': sha(content), 'readonly': False}
        else:
            if release_id and '/' in release_id:
                release = next((r for r in self.releases(project_id) if r['id'] == release_id and r['legacy']), None)
                require(release, 'Archive inconnue')
                path = safe(root, release['path'] + '/' + ('README.md' if kind == 'plan' else DOCS[kind]))
            else:
                path = safe(self.release_folder(project_id, release_id), DOCS[kind])
        content = read(path) if path.exists() else ''
        return {'path': str(path.relative_to(root)), 'body': content, 'revision': sha(content), 'readonly': bool(release_id and '/' in release_id)}

    def save_document(self, project_id, kind, body, revision, release_id=None):
        doc = self.document(project_id, kind, release_id)
        require(not doc['readonly'], 'Les dossiers historiques restent en lecture seule')
        require(kind in {'memory', 'journal', 'plan', 'qa'}, 'Journal des décisions et des transitions géré par le moteur')
        with locked(self.state / 'locks' / project_id):
            path = safe(self.root(project_id), doc['path'])
            require(sha(read(path) if path.exists() else '') == revision, 'Le document a changé. Rechargez.')
            atomic(path, clean(body, 200000) + '\n')
        return self.document(project_id, kind, release_id)

    def environments(self, project_id):
        local = self.settings().get('projects', {}).get(project_id, {}).get('environments', [])
        result = [{**row, 'source': 'workbench'} for row in local if isinstance(row, dict)]
        project = self.project(project_id)
        result += self.declared_environments(Path(project['path']), project['id'])
        seen = {(r.get('name', '').casefold(), r.get('url', '')) for r in result}
        # Other checkouts of the same repository often hold the canonical declaration.
        for sibling in self.projects():
            if sibling['id'] == project_id or not project.get('family') or sibling.get('family') != project['family']:
                continue
            try:
                rows = self.declared_environments(Path(sibling['path']), sibling['id'])
            except (Problem, OSError, ValueError):
                continue
            for row in rows:
                if (row['name'].casefold(), row['url']) not in seen:
                    seen.add((row['name'].casefold(), row['url']))
                    result.append({**row, 'inherited_from': sibling['name']})
        return result

    def declared_environments(self, root, key):
        result = []
        path = safe(root, '.odoo-agents/instances.json')
        if not path.is_file():
            return result
        data = json.loads(read(path))
        rows = data.get('instances', data) if isinstance(data, dict) else data
        if isinstance(rows, dict):
            rows = [{'name': key, **v} for key, v in rows.items() if isinstance(v, dict)]
        require(isinstance(rows, list), 'Format des environnements non reconnu')
        for index, row in enumerate(rows):
            if not isinstance(row, dict):
                continue
            item = {key: row.get(key, '') for key in ['name', 'kind', 'platform', 'series']}
            item.update(id=f'declared-{key[:6]}-{index}', source='declared', path='')
            item['database'] = row.get('database', row.get('db', ''))
            url = urlsplit(str(row.get('url', '')))
            host = url.hostname or ''
            if ':' in host:
                host = '[' + host + ']'
            if url.port:
                host += ':' + str(url.port)
            item['url'] = urlunsplit((url.scheme, host, url.path, '', '')) if url.scheme in {'http', 'https'} else ''
            result.append(item)
        return result

    def add_environment(self, project_id, name, kind, url='', path='', series=''):
        self.project(project_id)
        name, url, path, series = clean(name, 120), clean(url, 1500), clean(path, 1500), clean(series, 50)
        require(name, 'Donnez un nom à cet environnement.')
        require(kind in {'local', 'test', 'staging', 'production', 'other'}, 'Type d’environnement invalide')
        require(url or path, 'Renseignez une adresse ou un dossier de travail.')
        if url:
            parsed = urlsplit(url)
            require(parsed.scheme in {'http', 'https'} and parsed.hostname, 'Adresse HTTP ou HTTPS attendue')
            require(not parsed.username and not parsed.password and not parsed.query and not parsed.fragment,
                    'Utilisez l’adresse de base, sans identifiants ni paramètres.')
        if path:
            folder = Path(path).expanduser().resolve()
            require(folder.is_dir(), 'Le dossier de travail n’existe pas.')
            path = str(folder)
        item = {'id': 'env-' + uuid.uuid4().hex[:12], 'name': name, 'kind': kind, 'url': url, 'path': path, 'series': series}
        with locked(self.state):
            settings = self.settings()
            pref = settings.setdefault('projects', {}).setdefault(project_id, {})
            entries = pref.setdefault('environments', [])
            require(not any(e.get('name', '').casefold() == name.casefold() for e in entries), 'Un environnement de ce nom existe déjà.')
            entries.append(item)
            atomic(self.settings_path, json.dumps(settings, ensure_ascii=False, indent=2) + '\n')
        return item

    def match(self, source):
        from email.utils import getaddresses
        participants = source.get('participants', [])
        participants = [participants] if isinstance(participants, str) else participants
        addresses = {address.casefold() for _, address in getaddresses([source.get('sender', ''), *participants]) if address}
        # Our own colleagues are on every thread: they never identify a client.
        addresses = {a for a in addresses if not a.endswith('@camptocamp.com')}
        exact, domains = [], []
        for project in self.projects():
            if project.get('criteria_from'):
                continue
            if addresses.intersection(project['emails']):
                exact.append(project)
            if {a.rsplit('@', 1)[-1] for a in addresses}.intersection(project['domains']):
                domains.append(project)
        matches = exact or domains
        return {'certain': len(matches) == 1, 'reason': 'adresse exacte' if exact else 'domaine configuré' if domains else 'aucune règle',
                'projects': [{'id': p['id'], 'name': p['name']} for p in matches]}

    def project_for(self, source):
        """The single project an email or event belongs to: participants first,
        forwarded client headers, then the client's name in the title."""
        found = self.match(source)
        if len(found['projects']) == 1:
            return {**found['projects'][0], 'by': found['reason']}
        if found['projects']:
            return None
        from .mail import forwarded_addresses, internal_sender
        if source.get('kind') != 'calendar' and internal_sender(source.get('sender')):
            forwarded = self.match({'participants': [source.get('forwarded_participants') or forwarded_addresses(source.get('body'))]})
            if len(forwarded['projects']) == 1:
                return {**forwarded['projects'][0], 'by': 'en-têtes du message transféré'}
            if forwarded['projects']:
                return None
        title = (source.get('title') or '').casefold()
        hits = []
        for project in self.projects():
            if project.get('criteria_from'):
                continue
            labels = set()
            for domain in project['domains'] + [a.rsplit('@', 1)[-1] for a in project['emails']]:
                label = domain.split('.')[0]
                labels |= {label, label.replace('-', '')} | ({label.split('-')[0]} if len(label.split('-')[0]) >= 4 else set())
            if any(re.search(r'(?<![\w-])' + re.escape(label) + r'(?![\w-])', title) for label in labels if len(label) >= 4):
                hits.append(project)
        return {'id': hits[0]['id'], 'name': hits[0]['name'], 'by': 'nom du client dans le titre'} if len(hits) == 1 else None

    def intake_items(self):
        folder = safe(self.state, 'inbox')
        items = [json.loads(read(p)) for p in folder.glob('*.json')] if folder.exists() else []
        return sorted(items, key=lambda item: item['created'], reverse=True)

    def ingest(self, source):
        require(source.get('kind') in {'email', 'calendar'}, 'Source email ou calendrier attendue')
        require(clean(source.get('external_id', ''), 1000), 'Identifiant externe requis pour éviter les doublons')
        source = {k: source.get(k) for k in ['kind', 'account', 'external_id', 'sender', 'participants', 'title', 'body', 'url', 'date']}
        source['account'] = clean(source.get('account') or '', 250)
        require(source['account'], 'Compte source requis')
        for key in ['external_id', 'sender', 'title', 'url', 'date']:
            source[key] = clean(source.get(key) or '', 1000)
        source['body'] = clean(source.get('body') or '', 100000)
        require(isinstance(source.get('participants') or [], list), 'Participants invalides')
        source['participants'] = [clean(p, 250) for p in (source.get('participants') or [])][:100]
        key = sha(source['kind'] + '\n' + source['account'] + '\n' + source['external_id'])
        target = safe(self.state, 'inbox/' + key + '.json')
        with locked(self.state / 'intake-lock'):
            if target.exists():
                return json.loads(read(target))
            match = self.match(source)
            item = {'id': key, 'source': source, 'match': match, 'status': 'a-trier', 'created': now()}
            if self.settings().get('intake', {}).get('automatic') and match['certain']:
                project_id = match['projects'][0]['id']
                setting = self.settings().get('projects', {}).get(project_id, {})
                release_id = setting.get('intake_release')
                opened = [r for r in self.releases(project_id) if not r['legacy'] and r['status'] == 'ouverte']
                if release_id not in {r['id'] for r in opened}:
                    release_id = opened[0]['id'] if len(opened) == 1 else None
                if release_id:
                    request = self.create_request(project_id, release_id, source['title'][:220] or 'Demande reçue', source['body'], source={**source, 'key': key})
                    item.update(status='creee', project=project_id, request=request['id'])
                else:
                    item['reason'] = 'Choisir la release de destination dans les paramètres du projet'
            atomic(target, json.dumps(item, ensure_ascii=False, indent=2) + '\n')
        return item

    def assign_intake(self, intake_id, project_id, release_id):
        require(re.fullmatch(r'[a-f0-9]{64}', intake_id), 'Identifiant de source invalide')
        with locked(self.state / 'intake-lock'):
            path = safe(self.state, 'inbox/' + intake_id + '.json')
            item = json.loads(read(path))
            if item['status'] == 'creee':
                return item
            source = item['source']
            request = self.create_request(project_id, release_id, source['title'][:220] or 'Demande reçue', source['body'], source={**source, 'key': intake_id})
            item.update(status='creee', project=project_id, request=request['id'])
            atomic(path, json.dumps(item, ensure_ascii=False, indent=2) + '\n')
            return item

    def library_search(self, query, entry_id=None):
        import threading
        query = clean(query, 200)
        require(len(query) >= 2, 'Deux caractères minimum')
        entries = [e for e in self.settings().get('library', []) if not entry_id or e['id'] == entry_id]
        result = []
        suffixes = ['md', 'rst', 'txt', 'csv', 'py', 'xml']
        ripgrep = shutil.which('rg')
        for entry in entries:
            if ripgrep:
                args = [ripgrep, '--json', '--fixed-strings', '--ignore-case', '--max-filesize', '2M', '--max-count', '3',
                        '--glob', '!**/.git/**', '--glob', '!**/node_modules/**', '--glob', '!**/filestore/**',
                        *[a for s in suffixes for a in ('--glob', '*.' + s)],
                        '--glob', '!**/secrets/**', '--glob', '!**/.env*', '--', query, entry['path']]
            else:  # grep is always present; ripgrep is only faster
                args = ['grep', '-rIinFZ', '-m', '3', *['--include=*.' + s for s in suffixes], '--exclude=.env*',
                        *['--exclude-dir=' + d for d in ('.git', 'node_modules', 'filestore', 'secrets')], '--', query, entry['path']]
            proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, errors='replace')
            deadline = threading.Timer(12, proc.kill)
            deadline.start()
            try:
                for line in proc.stdout:
                    if ripgrep:
                        item = json.loads(line)
                        if item['type'] != 'match':
                            continue
                        data = item['data']
                        name, number, text = data['path']['text'], data['line_number'], data['lines']['text']
                    else:
                        name, _, rest = line.partition('\0')
                        number, _, text = rest.partition(':')
                        if not number.isdigit():
                            continue
                        number = int(number)
                    path = Path(name).resolve()
                    if not path.is_relative_to(Path(entry['path']).resolve()):
                        continue
                    result.append({'entry': entry['name'], 'category': entry.get('category', ''), 'path': str(path),
                                   'line': number, 'text': text.strip()[:400]})
                    if len(result) >= 100:
                        break
            finally:
                deadline.cancel()
                proc.terminate() if proc.poll() is None else None
                proc.communicate(timeout=5)
            if len(result) >= 100:
                break
        return {'items': result, 'limit': 100, 'coverage': 'Recherche textuelle locale ; PDF et documents bureautiques non indexés.'}

    def import_email(self, content, account):
        message = BytesParser(policy=policy.default).parsebytes(content.encode())
        body = message.get_body(preferencelist=('plain',))
        return self.ingest({'kind': 'email', 'account': account,
                            'external_id': str(message.get('Message-ID') or sha(content)),
                            'sender': str(message.get('From', '')), 'participants': [],
                            'title': str(message.get('Subject', '')), 'body': body.get_content() if body else '',
                            'date': str(message.get('Date', ''))})
