"""Consultant cockpit: durable sources, release states and Tricorder measurements."""
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import importlib.util
import json
from pathlib import Path
import re
import sys
import threading
import time

from .core import clean, now
from .mail import EMAIL_LIMIT
from .storage import atomic, read, require, safe

ATTENTION = ['bloquee', 'attente-validation', 'a-verifier']
_reader = None
_reader_lock = threading.Lock()


def tricorder_reader():
    global _reader
    with _reader_lock:
        if _reader is None:
            folder = Path.home() / 'odoo-tricorder/backend'
            if not (folder / 'catalog.py').is_file():
                return None  # Optional compatibility reader, never an installation prerequisite.
            sys.path.insert(0, str(folder))
            spec = importlib.util.spec_from_file_location('_workbench_tricorder_catalog', folder / 'catalog.py')
            _reader = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(_reader)
    return _reader


def instant(value):
    try:
        dt = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).timestamp()
    except (ValueError, TypeError):
        try:
            return parsedate_to_datetime(value).timestamp()
        except (ValueError, TypeError):
            return 0


class Dashboard:
    def __init__(self, core, agents):
        self.core, self.agents = core, agents
        self.sources_path = safe(core.state, 'dashboard-sources.json')
        self.cache, self.lock = {}, threading.RLock()

    def source_status(self):
        saved = json.loads(read(self.sources_path)) if self.sources_path.exists() else {}
        return {'updated': saved.get('updated'), 'emails': len(saved.get('email', [])), 'events': len(saved.get('calendar', [])),
                'provider': saved.get('provider', 'codex')}

    def update_sources(self, emails=None, events=None, provider='codex'):
        previous = json.loads(read(self.sources_path)) if self.sources_path.exists() else {}
        for kind, rows, limit in [('email', emails, EMAIL_LIMIT), ('calendar', events, 40)]:
            if rows is None:
                continue
            require(isinstance(rows, list) and len(rows) <= limit, 'Trop de sources pour le dashboard')
            validated = []
            for row in rows:
                require(isinstance(row, dict), 'Source invalide')
                item = {field: clean(row.get(field, ''), 5000 if field in {'body', 'participants', 'forwarded_participants'} else 1000) for field in ['account', 'external_id', 'title', 'sender', 'date', 'end', 'url', 'body', 'participants', 'forwarded_participants']}
                require(item['account'] and item['external_id'] and item['date'], 'Compte, identifiant et date de la source requis')
                item.update(kind=kind, fetched=now(), via=('Claude Code' if provider == 'claude' else 'Codex') + ' · connexion native')
                validated.append(item)
            previous[kind] = validated
        # Microseconds: two snapshots in the same second must still be told apart by the UI.
        previous['updated'] = datetime.now(timezone.utc).isoformat(timespec='microseconds')
        previous['provider'] = provider
        with self.lock:
            atomic(self.sources_path, json.dumps(previous, ensure_ascii=False, indent=2))
            self.cache.clear()
        return {'emails': len(previous.get('email', [])), 'events': len(previous.get('calendar', [])), 'updated': previous['updated'], 'tasks_created': 0}

    def snapshot(self):
        with self.lock:
            cached = self.cache.get('snapshot')
            if cached and time.monotonic() - cached[0] < 15:
                return cached[1]
        projects, releases, alerts, attention = self.core.projects(), [], [], []
        for project in projects:
            if not project['available']:
                alerts.append({'project': project['name'], 'message': project['warning']})
                continue
            try:
                for release in self.core.releases(project['id']):
                    folder = safe(Path(project['path']), release['path'])
                    title = release['title']
                    if release['legacy']:
                        header = re.search(r'^#\s+(.+)', read(safe(folder, 'README.md')), re.M)
                        if header:
                            title = header[1]
                    match = re.match(r'(\d{4}-\d{2}-\d{2})', folder.name)
                    sort_at = instant(release.get('created') or (match[1] if match else '')) or folder.stat().st_mtime
                    releases.append({**release, 'title': title, 'project': project['id'], 'project_name': project['name'], 'sort_at': sort_at})
                open_ids = {r['id'] for r in releases if r['project'] == project['id'] and not r['legacy'] and r['status'] == 'ouverte'}
                if open_ids:
                    for request in self.core.requests(project['id']):
                        if request['release'] in open_ids and request['status'] in ATTENTION:
                            attention.append({'project': project['id'], 'project_name': project['name'],
                                              'release': request['release'], 'release_title': request['release_title'],
                                              **{k: request.get(k) for k in ['id', 'title', 'status', 'stage', 'updated', 'blocked_reason']}})
            except (OSError, ValueError):
                alerts.append({'project': project['name'], 'message': 'Un dossier de release nécessite une vérification.'})
        releases.sort(key=lambda r: r['sort_at'], reverse=True)
        opened = [r for r in releases if r['status'] == 'ouverte']
        saved = json.loads(read(self.sources_path)) if self.sources_path.exists() else {}
        intake = self.core.intake_items()
        emails = saved.get('email', [i['source'] for i in intake if i['source']['kind'] == 'email'])
        events = saved.get('calendar', [i['source'] for i in intake if i['source']['kind'] == 'calendar'])
        stamp = time.time()
        past = sorted([e for e in events if 0 < instant(e.get('date')) <= stamp], key=lambda e: instant(e['date']), reverse=True)
        future = sorted([e for e in events if instant(e.get('date')) > stamp], key=lambda e: instant(e['date']))
        result = {'projects': len(projects), 'open_releases': opened[:12], 'open_release_count': len(opened),
                  'latest_release': releases[0] if releases else None,
                  'last_email': max(emails, key=lambda e: instant(e.get('date')), default=None),
                  'emails': sorted(emails, key=lambda e: instant(e.get('date')), reverse=True)[:EMAIL_LIMIT],
                  'last_event': past[0] if past else None, 'past_events': past[:10], 'next_events': future[:30],
                  'source_updated': saved.get('updated'), 'alerts': alerts,
                  'attention': sorted(attention, key=lambda r: (ATTENTION.index(r['status']), r.get('updated') or ''))[:20],
                  'active_jobs': [j for j in self.agents.list() if j['status'] == 'running']}
        with self.lock:
            self.cache['snapshot'] = (time.monotonic(), result)
        return result

    def overview(self, project_id, release_id):
        key = (project_id, release_id)
        with self.lock:
            cached = self.cache.get(key)
            if cached and time.monotonic() - cached[0] < 20:
                return cached[1]
        project = self.core.project(project_id)
        release = next((r for r in self.core.releases(project_id) if r['id'] == release_id), None)
        require(release, 'Release inconnue')
        root = Path(project['path'])
        tasks, flows, effort, warnings = [], [], None, []
        if release['legacy']:
            reader = tricorder_reader()
            if reader is None:
                from .odoo_releases import points
                tasks = [{**row, 'status': {'todo': 'pending', 'doing': 'running', 'done': 'validated'}[row['column']]}
                         for row in points(read(safe(root, release['path'] + '/README.md')))]
                warnings.append('Lecteur de mesures historiques absent. Les mesures restent inconnues ; le tableau des points est disponible.')
            elif release_id.startswith('changelog/'):
                tasks, warnings = reader.plan_tasks(root, release_id.split('/', 1)[1])
                for path, unassigned in reader.related_flows(root, release_id.split('/', 1)[1]):
                    if unassigned:
                        continue
                    try:
                        flows.append(reader.flow_details(root, path))
                    except Exception as error:
                        warnings.append(str(error)[:200])
            if reader is not None:
                effort = reader.effort_details(safe(root, release['path']))
        else:
            tasks = self.core.requests(project_id, release_id)
        rows = (effort or {}).get('rows', [])
        warnings += (effort or {}).get('warnings', [])
        blocked = [t for t in tasks if t['status'] in {'blocked', 'bloquee', 'failed', 'stale'}]
        decisions = [t for t in tasks if t['status'] in {'attente-validation', 'a-verifier', 'waiting', 'awaiting_approval'}]
        running = [t for t in tasks if t['status'] in {'running', 'en-cours', 'claimed'}]
        received = [t for t in tasks if t['status'] in {'validated', 'terminee'}]
        ready = [t for t in tasks if t['status'] in {'ready', 'pending', 'a-faire'}]
        human_nodes = [n for f in flows for n in f.get('nodes', []) if n.get('executor') == 'human' and n['status'] == 'ready']
        state = 'bloquee' if blocked else 'attente-validation' if decisions or human_nodes else 'en-cours' if running else 'a-faire' if ready else 'a-verifier' if tasks and len(received) < len(tasks) else 'terminee' if tasks else 'ouverte'
        if release['status'] in {'cloturee', 'archive'}:
            state = 'cloturee' if not release['legacy'] else 'archive'
        next_action = 'Résoudre le blocage' if blocked else 'Valider la suite' if decisions or human_nodes else 'Consulter le travail en cours' if running else 'Lancer le prochain travail' if ready else 'Préparer la clôture' if tasks and len(received) == len(tasks) else 'Vérifier le suivi et les preuves' if tasks else 'Préciser le plan et ses critères'
        if state in {'cloturee', 'archive'}:
            next_action = 'Consulter le bilan'
        jobs = [j for j in self.agents.list() if j['project'] == project_id and any(t['id'] == j['request'] for t in tasks)]
        result = {'state': state, 'next_action': next_action, 'total': len(tasks), 'received': len(received),
                  'blocked': len(blocked), 'decisions': len(decisions) + len(human_nodes),
                  'tasks': [{k: t.get(k) for k in ['id', 'title', 'status', 'stage', 'reason']} for t in tasks],
                  'effort_rows': rows, 'effort_totals': (effort or {}).get('totals'),
                  'effort_basis': 'Tricorder · effort.json' if effort and not effort.get('unverified') else 'Non mesuré',
                  'warnings': warnings, 'jobs': jobs, 'scope': 'Temps d’exécution des agents ; aucun temps humain ni barème client.'}
        with self.lock:
            self.cache[key] = (time.monotonic(), result)
        return result
