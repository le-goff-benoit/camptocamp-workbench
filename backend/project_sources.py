"""Per-project Gmail queries and local snapshots; never create a task from a match."""
import json
from email.utils import getaddresses
from pathlib import Path
import re
import threading
import time

from .core import clean, now
from .dashboard import instant
from .native_sources import read_emails
from .mail import EMAIL_LIMIT, internal_sender
from .storage import atomic, read, safe


class ProjectEmails:
    def __init__(self, core, call, providers=None):
        self.core, self.call, self.lock, self.locks = core, call, threading.RLock(), {}
        self.providers = providers

    def search(self, project_id):
        project = self.core.project(project_id)
        pref = self.core.settings().get('projects', {}).get(project_id, {})
        explicit = clean(pref.get('mail_query', ''), 2000)
        if explicit:
            return {'query': explicit, 'basis': 'Recherche configurée', 'suggested': False}
        quote = lambda text: '"' + text.replace('"', '').replace('\\', '') + '"'
        terms = [t for t in dict.fromkeys(project.get('emails', []) + project.get('domains', [])) if re.fullmatch(r'[\w.+@-]+', t)]
        if terms:
            any_of = ' '.join(f'{field}:{term}' for term in terms for field in ('from', 'to', 'cc'))
            # Internal forwards have no client in their envelope. Verify their
            # quoted headers after reading, to exclude signatures and mentions.
            inherited = f' · repris de {project["criteria_from"]}' if project.get('criteria_from') else ''
            forwards = ' '.join(f'(from:camptocamp.com {quote(term)})' for term in terms)
            return {'query': '-in:spam -in:trash {' + any_of + ' ' + forwards + '}',
                    'basis': 'Adresses et domaines client · transferts internes inclus' + inherited, 'suggested': False}
        common = Path(project.get('common_git') or project['path'])
        base = pref.get('name') or (common.parent.name if common.name == '.git' else project['name'])
        base = re.split(r'(?:[_-](?:gestion|staging|production|backup|old|audit|20\d{2}|\d{6}))', base, maxsplit=1, flags=re.I)[0]
        words = [w for w in re.split(r'[_\s-]+', base) if w.casefold() not in {'odoo', 'sa', 'sarl', 'git', 'main', 'master'} and not re.fullmatch(r'(?:v)?\d+(?:\.\d+)*', w)]
        term = ' '.join(words).strip() or project['name']
        return {'query': '-in:spam -in:trash ' + quote(term), 'basis': 'Nom du dépôt · recherche à ajuster si besoin', 'suggested': True}

    def path(self, project_id):
        return safe(self.core.state, f'project-sources/{project_id}.json')

    def cached(self, project_id):
        search = self.search(project_id)
        path = self.path(project_id)
        saved = json.loads(read(path)) if path.exists() else {}
        provider = self.providers.selected('sources') if self.providers else 'codex'
        current = saved.get('query') == search['query'] and saved.get('provider', 'codex') == provider
        return {**search, 'provider': provider, 'updated': saved.get('updated') if current else None,
                'emails': saved.get('emails', [])[:EMAIL_LIMIT] if current else [],
                'more': (bool(saved.get('more')) or len(saved.get('emails', [])) > EMAIL_LIMIT) and current}

    def fetch(self, project_id, force=False):
        with self.lock:
            lock = self.locks.setdefault(project_id, threading.Lock())
        with lock:
            data = self.cached(project_id)
            if not force and time.time() - instant(data['updated']) < 60:
                return data
            project = self.core.project(project_id)
            explicit = self.core.settings().get('projects', {}).get(project_id, {}).get('mail_query')
            def accept(row):
                if explicit or not (project['emails'] or project['domains']):
                    return True
                # Preserve direct participant searches, including ambiguous ones;
                # only the additional internal-forward candidates need filtering.
                participants = {a.casefold() for _, a in getaddresses([row.get('sender', ''), row.get('participants', '')])
                                if a and not a.casefold().endswith('@camptocamp.com')}
                if participants.intersection(project['emails']) or {a.rsplit('@', 1)[-1] for a in participants}.intersection(project['domains']):
                    return True
                tagged = self.core.project_for(row) if internal_sender(row.get('sender')) else None
                return bool(tagged and (tagged['id'] == project_id or (project.get('criteria_from') and tagged['name'] == project['criteria_from'])))
            emails, more = self.providers.read_emails(data['query'], accept) if self.providers else read_emails(self.call, data['query'], accept=accept)
            result = {**data, 'emails': emails, 'more': more, 'updated': now(), 'tasks_created': 0}
            atomic(self.path(project_id), json.dumps(result, ensure_ascii=False))
            return result
