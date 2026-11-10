import subprocess

from test_core import Fixture


class MailClassificationTests(Fixture):
    def setUp(self):
        super().setUp()
        settings = self.core.settings()
        settings['projects'][self.project] = {'domains': ['atlas.example']}
        self.core.save_settings(settings)

    def test_colleague_forward_is_tagged_from_original_client_headers(self):
        for body in ['---------- Forwarded message ---------\nFrom: Client <client@atlas.example>\nTo: collegue@camptocamp.com\n\nBonjour.',
                     'De : Client <client@atlas.example> Envoyé : lundi À : collegue@camptocamp.com Objet : Question',
                     '> Von: Client <client@atlas.example>\n> An: collegue@camptocamp.com']:
            with self.subTest(body=body):
                source = {'kind': 'email', 'sender': 'Collègue <collegue@camptocamp.com>',
                          'participants': 'consultant@camptocamp.com', 'title': 'Fwd: Question', 'body': body}
                tagged = self.core.project_for(source)
                self.assertIsNotNone(tagged)
                self.assertEqual(tagged['id'], self.project)
                self.assertIn('transféré', tagged['by'])
                self.assertFalse(self.core.match(source)['certain'])

    def test_signature_or_external_quoted_content_does_not_identify_client(self):
        source = {'sender': 'collegue@camptocamp.com', 'title': 'Question', 'body': 'Signature : contact@atlas.example'}
        self.assertIsNone(self.core.project_for(source))
        source.update(sender='unknown@example.org', body='From: client@atlas.example')
        self.assertIsNone(self.core.project_for(source))

    def test_direct_participants_take_priority_and_ambiguous_forwards_are_untagged(self):
        other = self.base / 'projects/boreal'
        other.mkdir()
        subprocess.run(['git', 'init', '-q', other], check=True)
        self.core.refresh_projects()
        second = next(p['id'] for p in self.core.projects() if p['path'] == str(other))
        settings = self.core.settings()
        settings['projects'][second] = {'domains': ['boreal.example']}
        self.core.save_settings(settings)
        source = {'sender': 'collegue@camptocamp.com', 'title': 'Fwd: Atlas',
                  'body': 'From: contact@atlas.example\nTo: contact@boreal.example'}
        self.assertIsNone(self.core.project_for(source))
        source['participants'] = 'contact@boreal.example'
        self.assertEqual(self.core.project_for(source)['id'], second)
