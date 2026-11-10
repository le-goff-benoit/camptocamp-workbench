from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
import json
import os
from pathlib import Path
import shutil
from unittest.mock import Mock, patch

from test_core import Fixture
from backend.agents import Agents
from backend.claude_bridge import ClaudeBridge, GMAIL
from backend.claude_guard import allowed_tool
from backend.claude_sources import emails_from
from backend.dashboard import Dashboard
from backend.providers import Providers
from backend.server import App
from backend.storage import Problem
from backend.triage import Triage
from test_email_review import settled


class ProviderTests(Fixture):
    def test_email_review_uses_either_provider_and_remains_human_only(self):
        app = App(self.base/'state-review', 18890, 18891)
        self.addCleanup(app.stop.set); self.addCleanup(app.providers.shutdown)
        for provider in ('codex', 'claude'):
            settings = app.core.settings()
            settings['providers'] = {'sources': provider, 'analysis': provider}
            app.core.save_settings(settings)
            with self.assertRaisesRegex(Problem, 'interface utilisateur'):
                app.rpc('email.review', {'message': 'review-'+provider})
            app.rpc('email.review', {'message': 'review-'+provider}, human=True)
            result = settled(app.email_reviews, 'review-'+provider)
            self.assertEqual(result['status'], 'ready', result)
            self.assertEqual(result['provider'], provider)
            self.assertTrue(result['request_summary'])
            self.assertTrue(result['proposal'])
            self.assertEqual(app.rpc('email.review', {'message':'review-'+provider}, human=True), result)

    def setUp(self):
        super().setUp()
        binary = self.base/'bin'; binary.mkdir()
        for name, fixture in [('claude','fake_claude.py'),('codex','fake_codex.py')]:
            shutil.copyfile(Path(__file__).parent/'fixtures'/fixture, binary/name)
            (binary/name).chmod(0o755)
        environment = patch.dict(os.environ, {'PATH':str(binary)+os.pathsep+os.environ['PATH']})
        environment.start(); self.addCleanup(environment.stop)
        self.dashboard = Dashboard(self.core, Agents(self.core))
        self.providers = Providers(self.core, self.dashboard.update_sources)
        self.addCleanup(self.providers.shutdown)

    def choose(self, sources='claude', analysis='claude', automatic=False):
        value = self.core.settings()
        value.update(providers={'sources':sources,'analysis':analysis}, source_sync={'enabled':automatic})
        self.core.save_settings(value)

    def test_settings_default_to_codex_and_reject_unknown_providers(self):
        self.assertEqual(self.providers.selected('sources'), 'codex')
        settings = self.core.settings(); settings['providers']['sources'] = 'unknown'
        with self.assertRaises(Problem):
            self.core.save_settings(settings)
        self.assertEqual(self.providers.selected('sources'), 'codex')

    def test_claude_reads_actual_receipts_and_preserves_fifty_emails_and_tags(self):
        self.choose()
        result = self.providers.refresh_sources()
        self.assertEqual((result['emails'],result['events'],result['tasks_created']), (50,1,0))
        rows = self.dashboard.snapshot()['emails']
        self.assertEqual(rows[0]['external_id'], 'claude-mail-0')
        self.assertEqual(rows[0]['forwarded_participants'], 'client@atlas.example')
        self.assertEqual(self.dashboard.source_status()['provider'], 'claude')
        self.assertEqual(self.core.requests(self.project), [])

    def test_missing_claude_connector_keeps_the_previous_snapshot(self):
        self.choose()
        self.providers.refresh_sources()
        previous = self.dashboard.sources_path.read_bytes()
        with patch.dict(os.environ, {'WORKBENCH_QA_CLAUDE':'unavailable'}):
            with self.assertRaisesRegex(Problem, 'aperçus précédents'):
                self.providers.refresh_sources()
        self.assertEqual(self.dashboard.sources_path.read_bytes(), previous)
        self.assertIn('Gmail', self.providers.sync_status()['error'])

    def test_writes_and_secrets_are_denied_even_if_the_model_requests_them(self):
        self.assertFalse(allowed_tool(GMAIL+'send_message', {}, [GMAIL+'search_threads'], self.repo))
        self.assertFalse(allowed_tool('Read', {'file_path':str(self.repo/'.env')}, ['Read'], self.repo))
        self.assertFalse(allowed_tool('Read', {'file_path':str(self.base/'elsewhere')}, ['Read'], self.repo))
        self.assertTrue(allowed_tool('Read', {'file_path':str(self.repo/'README.md')}, ['Read'], self.repo))
        with patch.dict(os.environ, {'WORKBENCH_QA_CLAUDE':'forbidden'}):
            with self.assertRaisesRegex(Problem, 'Outil refusé'):
                self.providers.claude.ask('Ne fais rien.', 'Aucun outil.')

    def test_sources_and_analysis_can_use_different_providers(self):
        self.choose(sources='codex')
        self.providers.codex.refresh_sources = Mock(return_value={'emails':1})
        self.assertEqual(self.providers.refresh_sources()['emails'], 1)
        triage = Triage(self.core,self.providers.ask,lambda:self.providers.label('analysis'))
        result = triage.analyze([{'external_id':'one','title':'Question','body':'Merci de répondre.'}])
        self.assertEqual(result['emails'][0]['triage']['by'], 'Claude Code')

    def test_sync_is_due_every_five_minutes_and_does_not_overlap(self):
        self.choose(automatic=True)
        self.providers.claude.refresh_sources = Mock(return_value={'emails':50})
        stamp = datetime.now(timezone.utc).timestamp()
        self.assertTrue(self.providers.sync_due(stamp))
        self.assertFalse(self.providers.sync_due(stamp+299))
        self.assertTrue(self.providers.sync_due(stamp+301))
        self.assertEqual(self.providers.claude.refresh_sources.call_count, 2)
        self.providers.refresh_lock.acquire()
        try:
            self.assertFalse(self.providers.sync_due(stamp+700))
        finally:
            self.providers.refresh_lock.release()

    def test_full_message_can_be_read_through_the_selected_provider(self):
        self.choose()
        data = self.providers.native_call('gmail.read_email', {'message_id':'mail-test-1'})['structuredContent']
        self.assertEqual(data['id'], 'mail-test-1')
        self.assertIn('Contenu complet', data['payload']['body']['content'])

    def test_model_prose_is_not_used_as_a_source(self):
        self.assertEqual(emails_from([{'name':GMAIL+'search_threads','value':{'text':'Je pense avoir reçu un email.'}}]), [])

    def test_claude_native_fields_preserve_full_forward_headers_and_recipients(self):
        value={'content':'Présentation', 'structuredContent':{'messages':[{'id':'native-mail','subject':'Transfert',
            'internalDate':'1794300000000','sender':'collegue@camptocamp.com', 'toRecipients':['client@atlas.example'],
            'snippet':'Court extrait.', 'plaintextBody':'Introduction.\n'*500+'From: client@atlas.example\nTo: collegue@camptocamp.com',
            'viewUrl':'https://mail.google.com/mail/u/0/#all/native-mail'}]}}
        row=emails_from([{'name':GMAIL+'get_thread','value':value}])[0]
        self.assertEqual(row['forwarded_participants'],'client@atlas.example')
        self.assertIn('client@atlas.example',row['participants'])
        self.assertEqual(row['body'],'Court extrait.')
        settings=self.core.settings(); settings['projects'][self.project]={'domains':['atlas.example']}; self.core.save_settings(settings)
        self.assertTrue(self.core.match(row)['certain'])

    def test_claude_can_prepare_a_plan_without_changing_the_project(self):
        self.choose()
        answer=self.providers.claude.analyze('Tu es le responsable de l’analyse de cette demande.',self.repo,
                                            {'type':'object','required':['analysis','criteria','plan','questions','risks']})
        self.assertEqual(set(answer),{'analysis','criteria','plan','questions','risks'})
        self.assertEqual([p.name for p in self.repo.iterdir()],['.git'])

    def test_analysis_does_not_erase_verified_google_connection_status(self):
        self.providers.claude.check()
        previous=self.providers.claude.status()['servers']
        self.providers.claude.ask('Réponds OK.', 'Aucun outil.')
        self.assertEqual(self.providers.claude.status()['servers'],previous)

    def test_native_claude_message_import_preserves_sender_and_complete_text(self):
        row={'id':'flat-mail-1','subject':'Demande du client','sender':'client@atlas.example',
             'date':'2026-11-10T10:00:00Z','toRecipients':['consultant@example.org'],
             'snippet':'Court extrait.','plaintextBody':'Texte complet du message, au-delà du court extrait.'}
        self.providers.claude.run=Mock(return_value={'records':[{'name':GMAIL+'get_message','isError':False,
                                                                'value':{'structuredContent':row}}]})
        payload=self.providers.claude.native_call('gmail.read_email',{'message_id':'flat-mail-1'})['structuredContent']['payload']
        head={h['name']:h['value'] for h in payload['headers']}
        self.assertEqual(head['from'],'client@atlas.example')
        self.assertEqual(head['to'],'consultant@example.org')
        self.assertEqual(payload['body']['content'],row['plaintextBody'])

    def test_mail_import_opens_existing_task_in_its_actual_release(self):
        app = App(self.base/'state-app', 18890, 18891)
        self.addCleanup(app.stop.set); self.addCleanup(app.providers.shutdown)
        settings = app.core.settings(); settings.update(roots=[str(self.repo.parent)],library=[]); app.core.save_settings(settings)
        release = app.core.create_release(self.project, 'Source email')['id']
        other = app.core.create_release(self.project, 'Autre release')['id']
        message = EmailMessage(); message['Subject']='Objet'; message['From']='client@example.org'; message.set_content('Texte intégral.')
        app.odoo.message = Mock(return_value=(message,'Objet'))
        first = app.rpc('mail.to_release',{'project':self.project,'release':release,'message':'mail-test-1','title':'Tâche claire'},human=True)
        second = app.rpc('mail.to_release',{'project':self.project,'release':other,'message':'mail-test-1'},human=True)
        self.assertEqual(first['request'],second['request'])
        self.assertFalse(second['added']); self.assertEqual(second['release'], release)
        self.assertEqual(app.odoo.message.call_count,1)
        self.assertEqual(app.core.request(self.project,first['request'])['title'],'Tâche claire')
