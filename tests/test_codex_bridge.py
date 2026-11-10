import os
from pathlib import Path
import shutil
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from test_core import Fixture
from backend.agents import Agents
from backend.codex_bridge import CodexBridge
from backend.dashboard import Dashboard
from backend.storage import Problem


class CodexBridgeTests(Fixture):
    def setUp(self):
        super().setUp()
        binary = self.base / 'bin'
        binary.mkdir()
        shutil.copyfile(Path(__file__).parent / 'fixtures/fake_codex.py', binary / 'codex')
        (binary / 'codex').chmod(0o755)
        environment = patch.dict(os.environ, {'PATH': str(binary) + os.pathsep + os.environ['PATH']})
        environment.start()
        self.addCleanup(environment.stop)
        self.dashboard = Dashboard(self.core, Agents(self.core))
        self.codex = CodexBridge(self.core, self.dashboard.update_sources)
        self.addCleanup(self.codex.shutdown)

    def test_refresh_stores_validated_native_sources_without_creating_anything(self):
        result = self.codex.refresh_sources()
        self.assertEqual((result['emails'], result['tasks_created']), (1, 0))
        self.assertEqual(self.dashboard.snapshot()['emails'][0]['title'], 'Email relevé pendant la recette')
        self.assertEqual(self.core.requests(self.project), [])

    def test_failed_google_read_preserves_previous_sources(self):
        self.dashboard.update_sources(emails=[{'account': 'test@example.org', 'external_id': 'previous', 'title': 'Message conservé', 'date': '2026-11-09T12:00:00Z'}])
        with patch.dict(os.environ, {'WORKBENCH_QA_SOURCES': 'unavailable'}):
            with self.assertRaisesRegex(Problem, 'aperçus précédents sont conservés'):
                self.codex.refresh_sources()
        self.dashboard.cache.clear()
        self.assertEqual(self.dashboard.snapshot()['emails'][0]['title'], 'Message conservé')

    def test_refresh_accepts_all_fifty_recent_emails(self):
        stamp = datetime.now(timezone.utc)
        def call(tool, args):
            if tool.endswith('get_profile'):
                value = {'email': 'consultant@example.org'}
            elif tool == 'gmail.search_emails':
                self.assertEqual(args['max_results'], 50)
                value = {'emails': [{'id': f'mail-{i}', 'email_ts': (stamp-timedelta(minutes=i)).isoformat(),
                                     'subject': f'Message {i}', 'from_': 'client@example.org'} for i in reversed(range(50))]}
            else:
                value = {'events': []}
            return {'structuredContent': value}
        with patch.object(self.codex, 'native_call', side_effect=call):
            result = self.codex.refresh_sources()
        self.assertEqual((result['emails'], result['tasks_created']), (50, 0))
        self.assertEqual([r['external_id'] for r in self.dashboard.snapshot()['emails']], [f'mail-{i}' for i in range(50)])
        self.assertEqual(self.core.requests(self.project), [])

    def test_only_google_read_tools_are_callable(self):
        with self.assertRaises(Problem):
            self.codex.native_call('gmail.send_email', {'to': 'x@example.org'})

    def test_chat_endpoints_are_gone(self):
        from backend.server import App
        app = App(self.base / 'state-app', 18890, 18891)
        self.addCleanup(app.codex.shutdown)
        self.addCleanup(app.stop.set)
        for action in ['chat.get', 'chat.send', 'chat.new', 'chat.cancel']:
            with self.assertRaisesRegex(Problem, 'Commande inconnue'):
                app.rpc(action, {'project': None, 'text': 'Bonjour'}, human=True)
