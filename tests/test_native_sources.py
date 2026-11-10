from datetime import datetime, timedelta, timezone
import base64
import unittest

from backend.native_sources import read_sources


class NativeSourcesTests(unittest.TestCase):
    def test_short_inbox_page_is_completed_to_fifty_from_next_page(self):
        calls = []
        stamp = datetime.now(timezone.utc)
        def call(tool, args):
            if tool.endswith('get_profile'):
                data = {'email': 'consultant@example.org'}
            elif tool == 'gmail.search_emails':
                calls.append(args)
                indexes = range(49, 50) if args.get('next_page_token') else range(49)
                data = {'emails': [{'id': f'mail-{i}', 'subject': str(i), 'from_': 'client@example.org',
                                   'email_ts': (stamp-timedelta(minutes=i)).isoformat()} for i in indexes],
                        'next_page_token': 'older' if len(calls) == 1 else 'still-older'}
            else:
                data = {'events': []}
            return {'structuredContent': data}
        rows = read_sources(call)['emails']
        self.assertEqual(len(rows), 50)
        self.assertEqual([r['external_id'] for r in rows], [f'mail-{i}' for i in range(50)])
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[1]['next_page_token'], 'older')

    def test_native_pagination_accounts_and_non_meeting_entries(self):
        stamp = datetime.now(timezone.utc)
        previous, future = (stamp-timedelta(hours=2)).isoformat(), (stamp+timedelta(hours=2)).isoformat()
        event = lambda identifier, **extra: {'id': identifier, 'summary': 'Rendez-vous vérifié', 'start': future, 'end': future, **extra}
        def call(tool, args):
            if tool == 'gmail.get_profile':
                value = {'email': 'mail@example.org'}
            elif tool == 'google_calendar.get_profile':
                value = {'email': 'calendar@example.org'}
            elif tool == 'gmail.search_emails':
                value = {'emails': [{'id': 'mail1', 'subject': 'Email vérifié', 'email_ts': previous, 'snippet': 'Extrait réellement renvoyé.'}]}
            elif args.get('next_page_token'):
                value = {'events': [event('past', start=previous), event('next')], 'next_page_token': None}
            else:
                value = {'events': [event('location', event_type='workingLocation'), event('cancelled', status='cancelled'), event('refused', my_response_status='declined'), event('unknown', start=''), event('next')], 'next_page_token': 'page2'}
            return {'structuredContent': value, 'content': [], 'isError': False}
        result = read_sources(call)
        self.assertEqual(result['emails'][0]['account'], 'mail@example.org')
        self.assertEqual([r['external_id'] for r in result['events']], ['past', 'next'])
        self.assertEqual({r['account'] for r in result['events']}, {'calendar@example.org'})

    def test_internal_forward_headers_are_read_beyond_snippet_in_plain_or_html_mail(self):
        stamp = datetime.now(timezone.utc).isoformat()
        for mime, body in [('text/plain', 'Introduction longue.\n'*400 + '\nFrom: Client <client@atlas.example>\nTo: collegue@camptocamp.com'),
                           ('text/html', '<div>Introduction.</div><div><b>De :</b> Client &lt;client@atlas.example&gt;</div>')]:
            with self.subTest(mime=mime):
                calls = []
                def call(tool, args):
                    calls.append((tool, args))
                    if tool.endswith('get_profile'):
                        data = {'email': 'consultant@camptocamp.com'}
                    elif tool == 'gmail.search_emails':
                        data = {'emails': [{'id': 'forwarded', 'subject': 'Question', 'from_': 'collegue@camptocamp.com',
                                            'email_ts': stamp, 'snippet': 'Introduction sans nom de client.'}]}
                    elif tool == 'gmail.read_email':
                        data = {'payload': {'mime_type': 'multipart/alternative', 'parts': [
                            {'mime_type': 'text/plain', 'filename': 'signature.txt', 'body': {'content': 'From: wrong@boreal.example'}},
                            {'mime_type': mime, 'body': {'base64_url_content': base64.urlsafe_b64encode(body.encode()).decode()}}]}}
                    else:
                        data = {'events': []}
                    return {'structuredContent': data}
                row = read_sources(call)['emails'][0]
                self.assertEqual(row['forwarded_participants'], 'client@atlas.example')
                self.assertEqual(row['body'], 'Introduction sans nom de client.')
                self.assertIn(('gmail.read_email', {'message_id': 'forwarded'}), calls)
