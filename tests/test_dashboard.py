from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

from test_core import Fixture
from backend.agents import Agents
from backend.dashboard import Dashboard
from backend.storage import Problem, atomic, read


class DashboardTests(Fixture):
    def setUp(self):
        super().setUp()
        self.dashboard = Dashboard(self.core, Agents(self.core))

    def test_sources_are_real_snapshots_and_do_not_create_tasks(self):
        stamp = datetime.now(timezone.utc)
        self.release()
        source = {'account': 'me@example.org', 'external_id': 'email-1', 'title': 'Décisions du client', 'sender': 'client@example.org', 'date': stamp.isoformat(), 'body': 'Demande effectivement lue.'}
        self.dashboard.update_sources(emails=[source], events=[{**source, 'external_id': 'past', 'title': 'Réunion passée', 'date': (stamp-timedelta(days=1)).isoformat()}, {**source, 'external_id': 'next', 'title': 'Réunion à préparer', 'date': (stamp+timedelta(days=1)).isoformat()}])
        result = self.dashboard.snapshot()
        self.assertEqual(result['last_email']['title'], source['title'])
        self.assertEqual(result['last_event']['title'], 'Réunion passée')
        self.assertEqual(result['next_events'][0]['title'], 'Réunion à préparer')
        self.assertEqual(self.core.requests(self.project), [])

    def test_home_lists_requests_awaiting_the_consultant_across_projects(self):
        waiting, idle = self.request(), self.request()
        self.move(waiting, 'start-analysis')
        self.move(waiting, 'propose-plan', note='Plan à décider.')
        self.move(idle, 'start-analysis')
        attention = self.dashboard.snapshot()['attention']
        self.assertEqual([(r['id'], r['status']) for r in attention], [(waiting['id'], 'attente-validation')])
        self.assertEqual(attention[0]['project'], self.project)
        self.move(waiting, 'block', note='Information client manquante.')
        self.dashboard.cache.clear()
        blocked = self.dashboard.snapshot()['attention'][0]
        self.assertEqual((blocked['status'], blocked['blocked_reason']), ('bloquee', 'Information client manquante.'))

    def test_oversized_refresh_preserves_previous_snapshot(self):
        source = {'account': 'me@example.org', 'external_id': 'previous', 'title': 'Précédent', 'date': '2026-11-09T12:00:00Z'}
        self.dashboard.update_sources(emails=[source])
        previous = self.dashboard.sources_path.read_bytes()
        with self.assertRaisesRegex(Problem, 'Trop de sources'):
            self.dashboard.update_sources(emails=[{**source, 'external_id': str(i)} for i in range(51)])
        self.assertEqual(self.dashboard.sources_path.read_bytes(), previous)

    def test_current_release_calls_for_human_plan_decision(self):
        record = self.request()
        self.move(record, 'start-analysis')
        self.move(record, 'propose-plan', note='Analyser les sources puis vérifier.')
        overview = self.dashboard.overview(self.project, record['release'])
        self.assertEqual(overview['state'], 'attente-validation')
        self.assertEqual(overview['decisions'], 1)
        self.assertEqual(overview['effort_rows'], [])
        self.assertEqual(overview['effort_basis'], 'Non mesuré')

    def test_historical_overview_is_available_without_the_optional_reader(self):
        folder = self.repo / 'changelog/2026-11-01_standalone'
        folder.mkdir(parents=True)
        atomic(folder / 'README.md', '# Suivi\n<!-- release ouverte -->\n\n| 1 | Besoin client | test | à faire |\n| 2 | Libellé | test | fait |\n')
        with patch('backend.dashboard.tricorder_reader', return_value=None):
            overview = self.dashboard.overview(self.project, 'changelog/' + folder.name)
        self.assertEqual((overview['total'], overview['received']), (2, 1))
        self.assertIsNone(overview['effort_totals'])
        self.assertEqual(overview['effort_basis'], 'Non mesuré')
        self.assertTrue(overview['warnings'])

    @unittest.skipUnless((Path.home() / 'odoo-tricorder/backend/catalog.py').is_file(), 'lecteur historique facultatif absent')
    def test_tricorder_estimates_and_recorded_usage_are_reused_read_only(self):
        folder = self.repo / 'changelog/2026-11-01_synthetic'
        folder.mkdir(parents=True)
        atomic(folder / 'README.md', '# Suivi synthétique\n<!-- release ouverte -->\n\n| 1 | Travail synthétique | À faire |\n')
        stamp = '2026-11-01T10:00:00+00:00'
        line = {'task': 'P1', 'agent': 'analyst', 'expected_minutes': 20}
        data = {'schema': 1, 'release': folder.name, 'tasks': {'P1': 'Travail synthétique'},
                'estimates': [{'revision': 1, 'at': '2026-11-01T09:00:00+00:00', 'lines': [line]}],
                'entries': [{'id': 'entry1', 'task': 'P1', 'agent': 'analyst', 'status': 'complete', 'seconds': 600,
                             'tokens': {'input_tokens': 100, 'output_tokens': 20, 'cached_input_tokens': 30, 'cache_write_input_tokens': 0, 'total_tokens': 120},
                             'started_at': stamp, 'ended_at': '2026-11-01T10:10:00+00:00', 'provider_cost': {'amount': 0.03, 'currency': 'USD', 'basis': 'native'}}], 'rate_cards': []}
        atomic(folder / 'effort.json', json.dumps(data))
        original = (folder / 'effort.json').read_bytes()
        overview = self.dashboard.overview(self.project, 'changelog/' + folder.name)
        self.assertEqual(overview['effort_basis'], 'Tricorder · effort.json')
        self.assertEqual(overview['effort_totals']['planned_initial_minutes'], 20)
        self.assertEqual(overview['effort_totals']['actual_minutes'], 10)
        self.assertEqual(overview['effort_totals']['tokens'], 120)
        self.assertEqual(original, (folder / 'effort.json').read_bytes())
        self.assertFalse((folder / 'bilan-effort.md').exists())

    def test_mcp_bridge_exposes_tracking_without_approval_or_provider_secrets(self):
        path = Path(__file__).resolve().parents[1] / 'scripts/codex_mcp.py'
        spec = importlib.util.spec_from_file_location('workbench_bridge_test', path)
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        bridge = module.Bridge(self.base/'state')
        listing = bridge.handle({'jsonrpc':'2.0','id':1,'method':'tools/list'})
        names = {t['name'] for t in listing['result']['tools']}
        readonly = next(t for t in listing['result']['tools'] if t['name'] == 'workbench_dashboard')
        self.assertTrue(readonly['annotations']['readOnlyHint'])
        self.assertIn('workbench_dashboard_sources', names)
        sources = next(t for t in listing['result']['tools'] if t['name'] == 'workbench_dashboard_sources')
        self.assertEqual(sources['inputSchema']['properties']['emails']['maxItems'], 50)
        self.assertFalse(any('approve' in name or 'terminal' in name for name in names))
        bridge.call = Mock(side_effect=Exception('Do not expose sensitive diagnostics'))
        response = bridge.handle({'jsonrpc':'2.0','id':2,'method':'tools/call','params':{'name':'workbench_status','arguments':{}}})
        self.assertTrue(response['result']['isError'])
        self.assertNotIn('sensitive diagnostics', json.dumps(response))
