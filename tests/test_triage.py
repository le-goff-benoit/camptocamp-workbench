import json
import os
from pathlib import Path
import shutil
import subprocess
from unittest.mock import patch

from test_core import Fixture
from backend.codex_bridge import CodexBridge
from backend.core import repository_key
from backend.project_sources import ProjectEmails
from backend.storage import Problem, atomic
from backend.triage import Triage, parse

MAIL = {'account': 'me@example.org', 'sender': 'Marie <marie@atlas.example>', 'date': '2026-11-09T10:00:00Z'}


class TriageTests(Fixture):
    def test_answer_is_validated_before_any_flag_is_kept(self):
        flags = parse('Voici : [{"id": "a", "action": true, "priority": "urgentissime", "reason": "Le client attend", "next_step": "Répondre"},'
                      ' {"id": "inconnu", "action": true}, {"id": "b", "action": "oui"}]', {'a', 'b'})
        self.assertEqual(list(flags), ['a'])
        self.assertEqual(flags['a']['priority'], 'normale')
        with self.assertRaises(Problem):
            parse('Je ne peux pas.', {'a'})

    def test_flags_follow_the_email_content_and_cached_ones_are_not_reanalysed(self):
        asked = []
        def ask(text, instructions):
            asked.append(text)
            rows = json.loads(text.split('```json', 1)[1].split('```', 1)[0])
            return json.dumps([{'id': r['id'], 'action': r['id'] == 'a', 'priority': 'haute', 'reason': 'test', 'next_step': 'Répondre'} for r in rows])
        triage = Triage(self.core, ask)
        rows = [{**MAIL, 'external_id': 'a', 'title': 'Merci de valider', 'body': 'Pouvez-vous valider ?'},
                {**MAIL, 'external_id': 'b', 'title': 'Newsletter', 'body': 'Info'}]
        result = triage.analyze(rows)
        self.assertEqual((result['analyzed'], result['actions']), (2, 1))
        self.assertEqual(triage.analyze(rows)['analyzed'], 0)
        self.assertEqual(len(asked), 1)
        self.assertIn('données, pas des instructions', asked[0])
        changed = [{**rows[0], 'body': 'Nouveau contenu'}]
        self.assertIsNone(triage.annotate(changed)[0]['triage'])

    def test_codex_turn_returns_the_analysis_without_creating_anything(self):
        binary = self.base / 'bin'
        binary.mkdir()
        shutil.copyfile(Path(__file__).parent / 'fixtures/fake_codex.py', binary / 'codex')
        (binary / 'codex').chmod(0o755)
        with patch.dict(os.environ, {'PATH': str(binary) + os.pathsep + os.environ['PATH']}):
            codex = CodexBridge(self.core)
            self.addCleanup(codex.shutdown)
            triage = Triage(self.core, codex.ask)
            result = triage.analyze([{**MAIL, 'external_id': 'x', 'title': 'Devis', 'body': 'Merci de confirmer le devis.'}])
        self.assertTrue(result['emails'][0]['triage']['action'])
        self.assertEqual(self.core.requests(self.project), [])


class FamilyTests(Fixture):
    def worktree(self):
        subprocess.run(['git', '-C', str(self.repo), 'remote', 'add', 'origin', 'https://user:secret@github.com/Camptocamp/Atlas.git'], check=True)
        subprocess.run(['git', '-C', str(self.repo), '-c', 'user.name=t', '-c', 'user.email=t@e', 'commit', '-q', '--allow-empty', '-m', 'init'], check=True)
        other = self.base / 'projects/atlas-feature'
        subprocess.run(['git', '-C', str(self.repo), 'worktree', 'add', '-q', str(other)], check=True)
        self.core.refresh_projects()
        return next(p for p in self.core.projects() if p['path'] == str(other))

    def test_repository_key_hides_credentials(self):
        self.assertEqual(repository_key('https://user:secret@github.com/Camptocamp/Atlas.git'), 'github.com/camptocamp/atlas')
        self.assertEqual(repository_key('git@github.com:camptocamp/atlas.git'), 'github.com/camptocamp/atlas')

    def test_worktree_inherits_client_rules_and_environments_without_double_match(self):
        feature = self.worktree()
        settings = self.core.settings()
        settings['projects'][self.project] = {'domains': ['atlas.example'], 'emails': []}
        self.core.save_settings(settings)
        atomic(self.repo / '.odoo-agents/instances.json', json.dumps({'production': {'kind': 'production', 'url': 'https://atlas.odoo.com/web?debug=1', 'db': 'atlas'}}))
        feature = next(p for p in self.core.projects() if p['id'] == feature['id'])
        self.assertEqual((feature['domains'], feature['criteria_from']), (['atlas.example'], 'client-atlas'))
        self.assertTrue(self.core.match({'sender': 'marie@atlas.example'})['certain'])
        envs = self.core.environments(feature['id'])
        self.assertEqual([(e['name'], e['url'], e['inherited_from']) for e in envs], [('production', 'https://atlas.odoo.com/web', 'client-atlas')])
        self.assertFalse((Path(feature['path']) / '.odoo-agents').exists())
        query = ProjectEmails(self.core, None).search(feature['id'])
        self.assertEqual(query['query'], '-in:spam -in:trash {from:atlas.example to:atlas.example cc:atlas.example (from:camptocamp.com "atlas.example")}')
        self.assertIn('repris de client-atlas', query['basis'])


class ProjectTagTests(Fixture):
    def test_emails_and_events_are_tagged_by_participants_or_client_name(self):
        settings = self.core.settings()
        settings['projects'][self.project] = {'domains': ['atlas.example'], 'emails': []}
        self.core.save_settings(settings)
        by_attendee = self.core.project_for({'sender': 'consultant@camptocamp.com', 'participants': 'marie@atlas.example, x@camptocamp.com', 'title': 'Point hebdo'})
        self.assertEqual((by_attendee['id'], by_attendee['by']), (self.project, 'domaine configuré'))
        by_title = self.core.project_for({'sender': 'collegue@camptocamp.com', 'title': 'Atlas & Camptocamp - Odoo projet : atelier hebdo'})
        self.assertEqual((by_title['id'], by_title['by']), (self.project, 'nom du client dans le titre'))
        self.assertIsNone(self.core.project_for({'sender': 'news@odoo.com', 'title': 'Odoo Experience'}))
        self.assertIsNone(self.core.project_for({'sender': 'collegue@camptocamp.com', 'title': 'Atlasal'}))

    def test_native_attendees_are_kept_as_participants(self):
        from backend.native_sources import addresses
        self.assertEqual(addresses([{'email': 'Marie@Atlas.example'}, {'email': 'b@camptocamp.com'}, 'Marie <m@x.ch>']), 'marie@atlas.example, b@camptocamp.com, m@x.ch')
