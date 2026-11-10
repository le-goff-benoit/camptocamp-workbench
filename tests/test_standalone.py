from unittest.mock import patch

from test_core import Fixture
from backend.server import App
from backend.storage import Problem


class StandaloneTests(Fixture):
    def test_odoo_project_can_open_an_integrated_release_without_external_agents(self):
        (self.repo/'.odoo-agents').mkdir()
        self.core.refresh_projects()
        app = App(self.base/'state', 18890, 18891)
        self.addCleanup(app.stop.set); self.addCleanup(app.providers.shutdown)
        with patch.object(app.odoo, 'runtime', return_value={'available': False}):
            release = app.rpc('release.create', {'project': self.project, 'title': 'Travail autonome'}, human=True)
        self.assertNotIn('/', release['id'])
        request = app.core.create_request(self.project, release['id'], 'Demande du client', 'Critères à préciser')
        self.assertEqual(request['stage'], 'nouvelle')

    def test_an_open_historical_release_is_not_replaced_by_a_second_workflow(self):
        (self.repo/'.odoo-agents').mkdir()
        legacy = self.repo/'changelog/2026-11-10_old'; legacy.mkdir(parents=True)
        (legacy/'README.md').write_text('# Historique\n<!-- release ouverte -->\n')
        self.core.refresh_projects()
        app = App(self.base/'state', 18890, 18891)
        self.addCleanup(app.stop.set); self.addCleanup(app.providers.shutdown)
        with patch.object(app.odoo, 'runtime', return_value={'available': False}):
            with self.assertRaisesRegex(Problem, 'historique est ouverte'):
                app.rpc('release.create', {'project': self.project, 'title': 'Nouveau'}, human=True)
