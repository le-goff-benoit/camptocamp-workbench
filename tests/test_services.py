import base64
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import threading
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen
import zipfile

from test_core import Fixture
from backend.documents import Documents
from backend.google_sources import GoogleSources, SCOPES
from backend.server import App, handler
from backend.storage import Problem, atomic, read
from backend.terminals import Terminals


class ServiceTests(Fixture):
    def test_pdf_text_is_really_extracted_and_indexed(self):
        docs = self.base / 'pdf-documents'; docs.mkdir()
        stream = b'BT /F1 12 Tf 50 740 Td (Politique paie validation double.) Tj ET'
        objects = [b'<< /Type /Catalog /Pages 2 0 R >>', b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
                   b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>',
                   b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
                   b'<< /Length ' + str(len(stream)).encode() + b' >>\nstream\n' + stream + b'\nendstream']
        data, offsets = b'%PDF-1.4\n', [0]
        for number, obj in enumerate(objects, 1):
            offsets.append(len(data)); data += str(number).encode() + b' 0 obj\n' + obj + b'\nendobj\n'
        start = len(data)
        data += b'xref\n0 6\n0000000000 65535 f \n' + b''.join(f'{offset:010d} 00000 n \n'.encode() for offset in offsets[1:])
        data += b'trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n' + str(start).encode() + b'\n%%EOF\n'
        (docs / 'procedure.pdf').write_bytes(data)
        settings = self.core.settings(); settings['library'] = [{'id': 'paie', 'name': 'Paie', 'path': str(docs)}]; self.core.save_settings(settings)
        library = Documents(self.core)
        self.assertEqual(library.index('paie')['indexed'], 1)
        self.assertEqual(len(library.search('validation double')), 1)

    def test_word_library_is_searchable_and_changed_sources_are_not_returned(self):
        docs = self.base / 'documents'; docs.mkdir()
        document = docs / 'procedure.docx'
        xml = '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>Contrôle des acomptes avant validation.</w:t></w:r></w:p></w:body></w:document>'
        with zipfile.ZipFile(document, 'w') as archive:
            archive.writestr('word/document.xml', xml)
        settings = self.core.settings(); settings['library'] = [{'id': 'rh', 'name': 'RH', 'path': str(docs)}]; self.core.save_settings(settings)
        library = Documents(self.core)
        self.assertEqual(library.index('rh')['indexed'], 1)
        self.assertEqual(len(library.search('acomptes')), 1)
        document.write_bytes(b'changed')
        self.assertEqual(library.search('acomptes'), [])

    def test_text_library_search_works_without_ripgrep(self):
        docs = self.base / 'regles'; docs.mkdir(); (docs / '.git').mkdir()
        (docs / 'feries.csv').write_text('nom,date\nLundi du Jeûne fédéral,2026-09-21\n')
        (docs / '.git' / 'copie.csv').write_text('Lundi du Jeûne fédéral\n')
        (docs / 'note.bin').write_text('Lundi du Jeûne fédéral\n')
        settings = self.core.settings(); settings['library'] = [{'id': 'rh', 'name': 'RH', 'path': str(docs)}]; self.core.save_settings(settings)
        from unittest import mock
        with mock.patch('backend.core.shutil.which', return_value=None):
            items = self.core.library_search('jeûne FÉDÉRAL')['items']
        self.assertEqual([(Path(i['path']).name, i['line']) for i in items], [('feries.csv', 2)])
        self.assertIn('2026-09-21', items[0]['text'])

    def test_document_symlink_is_not_indexed(self):
        docs = self.base / 'documents'; docs.mkdir()
        (docs / 'secret.docx').symlink_to(self.base / 'outside.docx')
        settings = self.core.settings(); settings['library'] = [{'id': 'rh', 'name': 'RH', 'path': str(docs)}]; self.core.save_settings(settings)
        self.assertEqual(Documents(self.core).index('rh')['indexed'], 0)

    def test_google_oauth_uses_pkce_scopes_and_rejects_wrong_state(self):
        google = GoogleSources(self.core)
        google.set_client({'installed': {'client_id': 'synthetic.apps.googleusercontent.com', 'client_secret': 'not-a-real-secret'}})
        result = google.begin('http://127.0.0.1:12345/workbench/oauth/google/callback')
        self.assertIn('code_challenge_method=S256', result['url'])
        self.assertIn('gmail.readonly', result['url'])
        with self.assertRaisesRegex(Problem, 'état invalide'):
            google.callback('wrong-state', 'not-a-code')
        self.assertFalse(google.auth_path.exists())

    def test_google_sync_reads_messages_and_events_without_mutations(self):
        rid = self.release()
        settings = self.core.settings(); settings['projects'][self.project] = {'emails': ['client@atlas.example'], 'intake_release': rid}; self.core.save_settings(settings)
        google = GoogleSources(self.core)
        seen = []
        def fake_get(url):
            seen.append(url)
            if url.endswith('/profile'): return {'emailAddress': 'consultant@example.org'}
            if '/messages?' in url: return {'messages': [{'id': 'gmail-1'}]}
            if '/messages/' in url: return {'id': 'gmail-1', 'payload': {'headers': [{'name': 'From', 'value': 'client@atlas.example'}, {'name': 'Subject', 'value': 'Demande reçue'}], 'mimeType': 'text/plain', 'body': {'data': base64.urlsafe_b64encode(b'Besoin de suivi.').decode()}}}
            if '/events?' in url: return {'items': [{'id': 'calendar-1', 'summary': 'Réunion client', 'organizer': {'email': 'consultant@example.org'}, 'attendees': [{'email': 'consultant@example.org', 'self': True}, {'email': 'client@atlas.example'}], 'start': {'date': '2026-11-10'}}]}
            self.fail('Endpoint inattendu : ' + url)
        google.get = fake_get
        google.synchronize()
        google.synchronize()
        self.assertEqual(len(self.core.requests(self.project)), 2)
        self.assertEqual(len(self.core.intake_items()), 2)
        self.assertTrue(all('/send' not in url and '/modify' not in url for url in seen))

    def test_two_terminals_are_independent_and_start_in_repository(self):
        terminals = Terminals(self.core)
        self.addCleanup(terminals.shutdown)
        first = terminals.open(self.project)
        second = terminals.open(self.project)
        terminals.write(first['id'], 'pwd\nprintf "FIRST_é_ok\\n"\n')
        terminals.write(second['id'], 'printf "SECOND_独立_ok\\n"\n')
        first_text = second_text = ''
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            first_text = terminals.output(first['id'])['text']
            second_text = terminals.output(second['id'])['text']
            if 'FIRST_é_ok' in first_text and 'SECOND_独立_ok' in second_text and str(self.repo) in first_text:
                break
            time.sleep(.05)
        self.assertIn(str(self.repo), first_text)
        self.assertIn('FIRST_é_ok', first_text)
        self.assertNotIn('SECOND_独立_ok', first_text)
        self.assertIn('SECOND_独立_ok', second_text)
        self.assertEqual(len(terminals.list()), 2)

    def test_batched_output_reads_each_session_from_its_own_cursor(self):
        terminals = Terminals(self.core)
        self.addCleanup(terminals.shutdown)
        first, second = terminals.open(self.project), terminals.open(self.project)
        terminals.write(first['id'], 'printf "BATCH_ONE\\n"\n')
        terminals.write(second['id'], 'printf "BATCH_TWO\\n"\n')
        cursors, texts = {first['id']: 0, second['id']: 0, 'gone': 0}, {first['id']: '', second['id']: ''}
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            result = terminals.outputs(cursors)
            for tid in texts:
                texts[tid] += result[tid]['text']
                cursors[tid] = result[tid]['cursor']
            if 'BATCH_ONE' in texts[first['id']] and 'BATCH_TWO' in texts[second['id']]:
                break
            time.sleep(.05)
        self.assertIn('BATCH_ONE', texts[first['id']])
        self.assertNotIn('BATCH_TWO', texts[first['id']])
        self.assertIn('BATCH_TWO', texts[second['id']])
        self.assertTrue(result['gone']['missing'])
        again = terminals.outputs({first['id']: cursors[first['id']]})
        self.assertNotIn('BATCH_ONE', again[first['id']]['text'])


class HttpTests(Fixture):
    def setUp(self):
        super().setUp()
        self.app = App(self.base / 'state', 18796, 18795)
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), handler(self.app))
        self.port = self.server.server_address[1]
        self.app.allowed_hosts.add(f'127.0.0.1:{self.port}')
        self.app.origins.add(f'http://127.0.0.1:{self.port}')
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.cleanup_server)

    def cleanup_server(self):
        self.app.stop.set()
        self.server.shutdown()
        self.server.server_close()

    def post(self, action, data=None, ui=False, origin=None):
        headers = {'Content-Type': 'application/json'}
        if ui:
            headers.update({'Origin': origin or f'http://127.0.0.1:{self.port}', 'Cookie': 'workbench_session=' + self.app.token, 'X-Workbench-UI': '1'})
        else:
            headers['X-Workbench-Key'] = self.app.token
            if origin:
                headers['Origin'] = origin
        request = Request(f'http://127.0.0.1:{self.port}/workbench/api', data=json.dumps({'action': action, 'data': data or {}}).encode(), headers=headers, method='POST')
        try:
            with urlopen(request) as response:
                return response.status, json.load(response)
        except HTTPError as error:
            return error.code, json.load(error)

    def test_service_key_cannot_impersonate_human_approval(self):
        record = self.request()
        self.move(record, 'start-analysis')
        fresh = self.move(record, 'propose-plan', note='Plan à décider.')
        code, result = self.post('request.transition', {'project': self.project, 'request': record['id'], 'revision': fresh['revision'], 'action': 'approve-plan', 'human': True})
        self.assertEqual(code, 400)
        self.assertIn('humaine', result['error'])
        code, result = self.post('request.transition', {'project': self.project, 'request': record['id'], 'revision': fresh['revision'], 'action': 'approve-plan'}, ui=True)
        self.assertEqual(code, 200)
        self.assertEqual(result['result']['stage'], 'realisation')

    def test_cross_origin_and_unauthenticated_requests_are_rejected(self):
        code, result = self.post('snapshot', ui=True, origin='https://untrusted.example')
        self.assertEqual(code, 400)
        self.assertIn('Origine', result['error'])
        request = Request(f'http://127.0.0.1:{self.port}/workbench/api', data=b'{"action":"snapshot"}', headers={'Content-Type': 'application/json', 'Origin': f'http://127.0.0.1:{self.port}'}, method='POST')
        with self.assertRaises(HTTPError) as error:
            urlopen(request)
        self.assertEqual(error.exception.code, 401)

    def test_agent_has_no_terminal_input_or_settings_access(self):
        code, _ = self.post('terminal.open', {'project': self.project})
        self.assertEqual(code, 400)
        code, _ = self.post('settings.save', {'settings': self.core.settings()})
        self.assertEqual(code, 400)
