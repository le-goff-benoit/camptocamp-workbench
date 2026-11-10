import json
import subprocess
import time

from test_core import Fixture
from backend.project_sources import ProjectEmails
from backend.storage import Problem, atomic
from backend.terminals import Terminals


class ProjectDashboardTests(Fixture):
    def test_project_mail_queries_and_caches_are_separate(self):
        other = self.repo.parent / 'boreal'
        other.mkdir()
        subprocess.run(['git', 'init', '-q', other], check=True)
        self.core._projects_cache = None
        second = next(p['id'] for p in self.core.projects() if p['path'] == str(other))
        calls = []
        def call(tool, args):
            if tool.endswith('get_profile'):
                return {'structuredContent': {'email': 'consultant@example.org'}}
            calls.append(args['query'])
            return {'structuredContent': {'emails': [{'id': args['query'], 'subject': args['query'], 'email_ts': '2026-11-09T12:00:00Z', 'snippet': 'Extrait vérifié.'}]}}
        sources = ProjectEmails(self.core, call)
        atlas, boreal = sources.fetch(self.project), sources.fetch(second)
        self.assertIn('atlas', atlas['query'])
        self.assertIn('boreal', boreal['query'])
        self.assertNotEqual(atlas['emails'][0]['external_id'], boreal['emails'][0]['external_id'])
        sources.fetch(self.project)
        self.assertEqual(len(calls), 2)
        self.assertEqual(self.core.requests(self.project), [])

    def test_project_keeps_its_fifty_latest_emails_independently_of_inbox(self):
        calls = []
        def call(tool, args):
            if tool.endswith('get_profile'):
                return {'structuredContent': {'email': 'consultant@example.org'}}
            calls.append(args)
            return {'structuredContent': {'emails': [{'id': f'atlas-{i}', 'subject': f'Atlas {i}',
                    'email_ts': f'2026-11-09T{23-i//60:02}:{59-i%60:02}:00Z'} for i in range(50)],
                    'next_page_token': 'older'}}
        data = ProjectEmails(self.core, call).fetch(self.project)
        self.assertEqual(len(data['emails']), 50)
        self.assertEqual([r['external_id'] for r in data['emails']], [f'atlas-{i}' for i in range(50)])
        self.assertEqual(len(calls), 1)
        self.assertNotIn('in:inbox', calls[0]['query'])
        self.assertTrue(data['more'])

    def test_project_includes_internal_forwards_but_not_signature_mentions(self):
        settings = self.core.settings()
        settings['projects'][self.project] = {'domains': ['atlas.example']}
        self.core.save_settings(settings)
        queries = []
        def call(tool, args):
            if tool.endswith('get_profile'):
                data = {'email': 'consultant@camptocamp.com'}
            elif tool == 'gmail.read_email':
                body = 'From: client@atlas.example\nTo: collegue@camptocamp.com' if args['message_id'] == 'forward' else 'Signature : client@atlas.example'
                data = {'payload': {'mime_type': 'text/plain', 'body': {'content': body}}}
            elif args.get('next_page_token'):
                data = {'emails': [{'id': 'direct', 'subject': 'Client', 'from_': 'client@atlas.example', 'email_ts': '2026-11-09T10:00:00Z'}]}
            else:
                queries.append(args['query'])
                data = {'emails': [{'id': mid, 'subject': 'Question', 'from_': 'collegue@camptocamp.com',
                        'email_ts': '2026-11-09T12:00:00Z'} for mid in ['forward', 'signature']], 'next_page_token': 'older'}
            return {'structuredContent': data}
        data = ProjectEmails(self.core, call).fetch(self.project)
        self.assertEqual([r['external_id'] for r in data['emails']], ['forward', 'direct'])
        self.assertIn('(from:camptocamp.com "atlas.example")', queries[0])
        self.assertFalse(data['more'])
        self.assertEqual(self.core.requests(self.project), [])

    def test_environment_is_persisted_without_changing_canonical_instances_and_opens_its_directory(self):
        canonical = self.repo/'.odoo-agents/instances.json'
        atomic(canonical, json.dumps({'instances': {'test': {'url': 'https://test.example.org', 'kind': 'test'}}}))
        original = canonical.read_bytes()
        folder = self.base/'local-work'
        folder.mkdir()
        env = self.core.add_environment(self.project, 'Atelier local', 'local', path=str(folder))
        self.assertEqual(canonical.read_bytes(), original)
        self.assertEqual(len(self.core.environments(self.project)), 2)
        terminals = Terminals(self.core)
        self.addCleanup(terminals.shutdown)
        terminal = terminals.open(self.project, environment=env['id'])
        terminals.write(terminal['id'], 'pwd\n')
        deadline = time.monotonic()+3
        while time.monotonic()<deadline:
            output = terminals.output(terminal['id'])['text']
            if str(folder) in output:
                break
            time.sleep(.03)
        self.assertIn(str(folder), output)
        self.assertEqual(terminal['environment_name'], 'Atelier local')
        with self.assertRaises(Problem):
            self.core.add_environment(self.project, 'URL interdite', 'test', url='https://user:example-secret@example.org')

    def test_github_link_is_derived_without_remote_credentials(self):
        subprocess.run(['git', '-C', str(self.repo), 'remote', 'add', 'origin', 'https://user:example-secret@github.com/example/client-atlas.git'], check=True)
        self.assertEqual(self.core.project(self.project)['github_url'], 'https://github.com/example/client-atlas')
