"""Releases du dispositif Odoo (`changelog/<id>`) lues et alimentées par ses propres outils.

Workbench n'écrit jamais lui-même dans ces dossiers : l'ouverture passe par
`odoo-release.sh open`, un email par `odoo_mail.py --release`, et le tableau du
plan vient de `odoo_plan.py status --json` (lecture seule).
"""
from email.message import EmailMessage
from email.utils import format_datetime
from datetime import datetime, timezone
import base64
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

from .core import clean
from .storage import Problem, require, safe

SCRIPTS = Path(os.environ.get('ODOO_AGENTS_HOME', Path.home() / '.odoo19-agents')) / 'scripts'
PLAN_COLUMNS = [('todo', 'À faire', {'pending', 'deferred'}), ('doing', 'En cours', {'running'}),
                ('review', 'À réceptionner', {'awaiting_receipt'}), ('attention', 'À traiter', {'blocked', 'stale', 'interrupted'}),
                ('done', 'Reçues', {'validated'})]
DONE = re.compile(r'^(fait|réalisé|realise|terminé|termine|livré|livre|reçu|recu|ok|✅|✔)', re.I)
TODO = re.compile(r'^(à faire|a faire|—|-|)$', re.I)


def run(args, timeout=60, cwd=None):
    result = subprocess.run(args, capture_output=True, text=True, timeout=timeout, cwd=cwd)
    if result.returncode != 0:
        raise Problem((result.stderr or result.stdout).strip()[:400] or 'Outil du dispositif Odoo en échec')
    return result.stdout


def points(readme):
    """Le tableau de suivi du README, avec la même lecture que `odoo-release.sh points`."""
    rows = []
    for line in readme.splitlines():
        if not re.match(r'^\| *\d+ *\|', line):
            continue
        cells = [c.strip() for c in line.strip().strip('|').split('|')]
        state = cells[-1] if len(cells) > 2 else ''
        column = 'done' if DONE.match(state) else 'todo' if TODO.match(state) else 'doing'
        rows.append({'id': cells[0], 'title': cells[1] if len(cells) > 1 else '', 'state': state, 'column': column})
    return rows


def mails(demande):
    return [m.group(1).strip() for m in re.finditer(r'(?m)^## Mail — (.+)$', demande)]


class OdooReleases:
    def __init__(self, core, call=None):
        self.core, self.call = core, call

    def runtime(self):
        home = self.core.settings().get('workflow_home')
        scripts = Path(home).expanduser()/'scripts' if home else SCRIPTS
        missing = [name for name in ('odoo-release.sh', 'odoo_plan.py', 'odoo_mail.py') if not (scripts/name).is_file()]
        return {'available': not missing, 'home': str(scripts.parent), 'missing': missing}

    def script(self, name):
        runtime = self.runtime()
        require(runtime['available'], 'Commandes du workflow Odoo manquantes. Configurez le moteur dans Paramètres → Workflow des releases Odoo.')
        return Path(runtime['home'])/'scripts'/name

    def folder(self, project_id, release_id):
        require(re.fullmatch(r'(changelog|release)/[\w.-]+', release_id or ''), 'Release Odoo invalide')
        folder = safe(self.core.root(project_id), release_id)
        require((folder / 'README.md').is_file() and not folder.is_symlink(), 'Release introuvable')
        return folder

    def is_open(self, folder):
        return bool(re.search(r'<!--\s*(release ouverte|lot ouvert)\s*-->', (folder / 'README.md').read_text(errors='replace'), re.I))

    def board(self, project_id, release_id):
        folder = self.folder(project_id, release_id)
        demande = folder / 'demande.md'
        result = {'release': release_id, 'open': self.is_open(folder),
                  'mails': mails(demande.read_text(errors='replace')) if demande.is_file() else [],
                  'demande': demande.is_file()}
        if (folder / 'plan.json').is_file():
            columns = [{'id': c, 'label': label, 'items': []} for c, label, _ in PLAN_COLUMNS]
            try:
                view = json.loads(run(['python3', str(self.script('odoo_plan.py')), 'status', str(folder), '--json'], timeout=45))
            except (Problem, ValueError, subprocess.TimeoutExpired) as error:
                return {**result, 'kind': 'plan', 'columns': columns, 'error': f'Plan illisible : {error}'}
            for task in view.get('tasks', []):
                target = next((c for (cid, _, names), c in zip(PLAN_COLUMNS, columns) if task['status'] in names), columns[0])
                target['items'].append(task)
            return {**result, 'kind': 'plan', 'columns': columns, 'next': view.get('next', ''), 'totals': view.get('totals', {})}
        rows = points((folder / 'README.md').read_text(errors='replace'))
        columns = [{'id': c, 'label': label, 'items': [r for r in rows if r['column'] == c]}
                   for c, label in [('todo', 'À faire'), ('doing', 'En cours'), ('done', 'Réalisés')]]
        return {**result, 'kind': 'points', 'columns': columns,
                'next': '' if rows else 'Aucun plan ni point suivi : préparer le plan avec /odoo-plan dans un terminal du projet.'}

    def open(self, project_id, title):
        title = ' '.join(clean(title, 200).splitlines())
        require(title, 'Titre requis')
        root = self.core.root(project_id)
        release_tool = self.script('odoo-release.sh')
        run([str(release_tool), 'open', str(root), title], timeout=60)
        current = run([str(release_tool), 'current', str(root)], timeout=30).strip()
        require(current, 'La release n’a pas été ouverte')
        return {'id': str(Path(current).resolve().relative_to(root.resolve())), 'title': Path(current).name, 'status': 'ouverte', 'legacy': True}

    def message(self, message_id):
        """L'email Gmail complet, reconstitué en .eml pour `odoo_mail.py`."""
        require(self.call, 'Lecture Gmail indisponible')
        require(re.fullmatch(r'[\w-]{6,64}', message_id or ''), 'Identifiant d’email invalide')
        from .native_sources import unpack
        data = unpack(self.call('gmail.read_email', {'message_id': message_id}), 'Gmail')
        payload = data.get('payload') or {}
        headers = {h.get('name', '').casefold(): h.get('value', '') for h in payload.get('headers', [])}
        texts, attachments = {}, []

        def walk(part):
            body, mime = part.get('body') or {}, part.get('mime_type', '')
            content = body.get('content')
            if content is None and body.get('base64_url_content'):
                content = base64.urlsafe_b64decode(body['base64_url_content'] + '===').decode('utf-8', 'replace')
            if part.get('filename'):
                attachments.append(part['filename'])
            elif mime in ('text/plain', 'text/html') and content and mime not in texts:
                texts[mime] = content
            for child in part.get('parts') or []:
                walk(child)
        walk(payload)
        message = EmailMessage()
        for name in ('from', 'to', 'cc', 'subject', 'date', 'message-id'):
            if headers.get(name):
                message[name.title() if name != 'message-id' else 'Message-ID'] = headers[name].replace('\n', ' ')
        if 'date' not in headers and data.get('internal_date'):
            message['Date'] = format_datetime(datetime.fromtimestamp(int(data['internal_date']) / 1000, timezone.utc))
        text = texts.get('text/plain') or data.get('snippet') or ''
        if attachments:
            text += '\n\n[Pièces jointes à récupérer dans Gmail : ' + ', '.join(attachments) + ']'
        message.set_content(text)
        if texts.get('text/html') and not texts.get('text/plain'):
            message.clear_content(); message.set_content(texts['text/html'], subtype='html')
        return message, headers.get('subject') or data.get('snippet', '')[:80]

    def add_mail(self, project_id, release_id, message_id):
        folder = self.folder(project_id, release_id)
        require(self.is_open(folder), 'Release clôturée : ouvrez-en une autre pour y verser cet email.')
        message, subject = self.message(message_id)
        demande = folder / 'demande.md'
        marker = f'<!-- gmail:{message_id} -->'
        if demande.is_file() and marker in demande.read_text(errors='replace'):
            return {'added': False, 'subject': subject, 'path': str(demande.relative_to(self.core.root(project_id)))}
        with tempfile.TemporaryDirectory(prefix='workbench-mail-') as tmp:
            eml = Path(tmp) / f'gmail-{message_id}.eml'
            eml.write_bytes(bytes(message))
            run(['python3', str(self.script('odoo_mail.py')), str(eml), '--release', str(folder)], timeout=60)
        with demande.open('a', encoding='utf-8') as handle:
            handle.write(f'\n{marker}\n')
        return {'added': True, 'subject': subject, 'path': str(demande.relative_to(self.core.root(project_id)))}
