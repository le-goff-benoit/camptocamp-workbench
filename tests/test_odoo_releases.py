"""Releases Odoo : tableau du plan ou des points, ouverture et email versés par les outils du dispositif."""
import base64
import json
from pathlib import Path
import subprocess
import unittest
from unittest import mock

from test_core import Fixture
from backend import odoo_releases
from backend.odoo_releases import OdooReleases, points
from backend.storage import Problem

TOOLS = (odoo_releases.SCRIPTS / 'odoo-release.sh').is_file() and (odoo_releases.SCRIPTS / 'odoo_mail.py').is_file()
README = '''<!-- release ouverte -->
# Essai

| # | Point | Test | État |
|---|---|---|---|
| 1 | Corriger la TVA des acomptes | test_tva | à faire |
| 2 | Bloquer la double validation | — | Diagnostic établi, correctif en cours |
| 3 | Libellé des factures | test_label | fait |
'''


def gmail_message(message_id='18c0ffee1234'):
    text = base64.urlsafe_b64encode('Bonjour,\nmerci de corriger la TVA.\nMarie'.encode()).decode()
    return {'structuredContent': {'id': message_id, 'snippet': 'Bonjour, merci de corriger la TVA.', 'internal_date': '1794300000000',
            'payload': {'mime_type': 'multipart/mixed', 'headers': [
                {'name': 'From', 'value': 'Marie <marie@client.ch>'}, {'name': 'To', 'value': 'consultant@example.com'},
                {'name': 'Subject', 'value': 'TVA des acomptes'}, {'name': 'Date', 'value': 'Mon, 9 Nov 2026 10:00:00 +0100'}],
                'parts': [{'mime_type': 'text/plain', 'filename': '', 'body': {'base64_url_content': text}},
                          {'mime_type': 'application/pdf', 'filename': 'facture.pdf', 'body': {'attachment_id': 'x'}}]}}}


class OdooReleaseTests(Fixture):
    def setUp(self):
        super().setUp()
        (self.repo / '.odoo-agents').mkdir()
        self.folder = self.repo / 'changelog/2026-11-09_01_essai'
        self.folder.mkdir(parents=True)
        (self.folder / 'README.md').write_text(README)
        self.release = 'changelog/2026-11-09_01_essai'
        self.calls = []

        def call(tool, arguments):
            self.calls.append((tool, arguments))
            return gmail_message(arguments['message_id'])
        self.odoo = OdooReleases(self.core, call)

    def test_points_go_to_columns_by_their_state(self):
        rows = points(README)
        self.assertEqual([(r['id'], r['column']) for r in rows], [('1', 'todo'), ('2', 'doing'), ('3', 'done')])
        board = self.odoo.board(self.project, self.release)
        self.assertEqual(board['kind'], 'points')
        self.assertTrue(board['open'])
        self.assertEqual({c['id']: len(c['items']) for c in board['columns']}, {'todo': 1, 'doing': 1, 'done': 1})

    def test_plan_tasks_go_to_kanban_columns(self):
        (self.folder / 'plan.json').write_text('{}')
        view = {'tasks': [{'id': 'T01', 'title': 'A', 'status': 'validated'}, {'id': 'T02', 'title': 'B', 'status': 'running'},
                          {'id': 'T03', 'title': 'C', 'status': 'pending', 'ready': True}, {'id': 'T04', 'title': 'D', 'status': 'stale'}],
                'next': 'Poursuivre T02.', 'totals': {'tasks': 4, 'received': 1}}
        with mock.patch.object(self.odoo, 'script', return_value=Path('fixture-odoo_plan.py')), mock.patch.object(odoo_releases, 'run', return_value=json.dumps(view)) as run:
            board = self.odoo.board(self.project, self.release)
        self.assertIn('--json', run.call_args.args[0])
        columns = {c['id']: [t['id'] for t in c['items']] for c in board['columns']}
        self.assertEqual(columns, {'todo': ['T03'], 'doing': ['T02'], 'review': [], 'attention': ['T04'], 'done': ['T01']})
        self.assertEqual(board['next'], 'Poursuivre T02.')

    def test_unreadable_plan_is_reported_not_hidden(self):
        (self.folder / 'plan.json').write_text('{}')
        with mock.patch.object(self.odoo, 'script', return_value=Path('fixture-odoo_plan.py')), mock.patch.object(odoo_releases, 'run', side_effect=Problem('schéma inconnu')):
            board = self.odoo.board(self.project, self.release)
        self.assertIn('schéma inconnu', board['error'])

    def test_release_path_cannot_escape_the_project(self):
        for bad in ['../x', 'changelog/../../etc', 'memory/releases/x', '/etc']:
            with self.assertRaises(Problem):
                self.odoo.folder(self.project, bad)

    def test_gmail_message_becomes_a_complete_eml(self):
        message, subject = self.odoo.message('18c0ffee1234')
        self.assertEqual(subject, 'TVA des acomptes')
        self.assertEqual(message['From'], 'Marie <marie@client.ch>')
        self.assertIn('merci de corriger la TVA', message.get_content())
        self.assertIn('facture.pdf', message.get_content())
        with self.assertRaises(Problem):
            self.odoo.message('../../etc')

    @unittest.skipUnless(TOOLS, 'dispositif Odoo absent')
    def test_email_is_poured_once_into_the_open_release(self):
        result = self.odoo.add_mail(self.project, self.release, '18c0ffee1234')
        self.assertTrue(result['added'])
        demande = (self.folder / 'demande.md').read_text()
        self.assertIn('TVA des acomptes', demande)
        self.assertIn('merci de corriger la TVA', demande)
        self.assertEqual(len(self.odoo.board(self.project, self.release)['mails']), 1)
        again = self.odoo.add_mail(self.project, self.release, '18c0ffee1234')
        self.assertFalse(again['added'])
        self.assertEqual((self.folder / 'demande.md').read_text(), demande)

    def test_closed_release_refuses_an_email(self):
        (self.folder / 'README.md').write_text(README.replace('<!-- release ouverte -->', ''))
        with self.assertRaises(Problem):
            self.odoo.add_mail(self.project, self.release, '18c0ffee1234')
        self.assertEqual(self.calls, [])

    @unittest.skipUnless(TOOLS, 'dispositif Odoo absent')
    def test_open_uses_the_release_script_and_refuses_a_second_one(self):
        (self.folder / 'README.md').write_text(README.replace('<!-- release ouverte -->', ''))
        subprocess.run(['git', '-C', str(self.repo), 'commit', '-q', '--allow-empty', '-m', 'init'], check=True,
                       env={'GIT_AUTHOR_NAME': 't', 'GIT_AUTHOR_EMAIL': 't@example.com', 'GIT_COMMITTER_NAME': 't', 'GIT_COMMITTER_EMAIL': 't@example.com', 'PATH': '/usr/bin:/bin'})
        release = self.odoo.open(self.project, 'Facturation des acomptes')
        self.assertTrue(release['id'].startswith('changelog/'))
        self.assertTrue(self.odoo.is_open(self.repo / release['id']))
        self.assertIn(release['id'], [r['id'] for r in self.core.releases(self.project) if r['status'] == 'ouverte'])
        with self.assertRaises(Problem):
            self.odoo.open(self.project, 'Une autre')


if __name__ == '__main__':
    unittest.main()
