"""Read native Codex Google tools directly; no model reformats the source records."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import base64
from html.parser import HTMLParser
import json
import re

from .dashboard import instant
from .mail import EMAIL_LIMIT, forwarded_addresses, internal_sender
from .storage import require


def unpack(result, provider):
    require(not result.get('isError'), f'La lecture {provider} a été refusée. Vérifiez sa connexion dans Codex.')
    value = result.get('structuredContent')
    if not isinstance(value, dict):
        for item in result.get('content', []):
            if item.get('type') == 'text':
                try:
                    candidate = json.loads(item['text'])
                    if isinstance(candidate, dict):
                        value = candidate
                        break
                except ValueError:
                    continue
    require(isinstance(value, dict), f'Le connecteur {provider} n’a pas fourni de relevé exploitable.')
    return value


def native_date(value):
    if isinstance(value, dict):
        value = value.get('dateTime') or value.get('date') or ''
    value = str(value or '')
    # The native connector renders all-day dates as a midnight without a zone.
    return value[:10] if len(value) == 19 and value.endswith('T00:00:00') else value


def addresses(value, limit=40):
    """Participant emails from native payloads (strings, lists or attendee objects)."""
    items = value if isinstance(value, list) else [value] if value else []
    found = []
    for item in items:
        text = item.get('email', '') if isinstance(item, dict) else str(item)
        found += re.findall(r'[\w.+-]+@[\w-]+(?:\.[\w-]+)+', text)
    return ', '.join(dict.fromkeys(a.casefold() for a in found[:limit]))


def mail_rows(profile, result, limit=EMAIL_LIMIT):
    account = profile.get('email')
    require(account, 'Le compte Gmail n’a pas été confirmé.')
    text = lambda value, limit=1000: str(value or '')[:limit]
    rows = [{'account': account, 'external_id': text(row.get('id')), 'title': text(row.get('subject')),
             'sender': text(row.get('from_')), 'date': text(row.get('email_ts')),
             'url': text(row.get('display_url')), 'body': text(row.get('snippet'), 1000),
             'participants': addresses([row.get(k) for k in ('to', 'cc') if row.get(k)])}
            for row in result.get('emails', [])]
    return sorted(rows, key=lambda r: instant(r['date']), reverse=True)[:limit]


class MailText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.text = []
        self.hidden = []

    def handle_data(self, data):
        if not self.hidden:
            self.text.append(data)

    def handle_starttag(self, tag, attrs):
        if tag in {'head', 'style', 'script'}:
            self.hidden.append(tag)
        if self.hidden:
            return
        if tag in {'br', 'div', 'p', 'tr', 'blockquote'}:
            self.text.append('\n')

    def handle_endtag(self, tag):
        if tag in self.hidden:
            self.hidden = self.hidden[:self.hidden.index(tag)]
            return
        if self.hidden:
            return
        if tag in {'div', 'p', 'tr', 'blockquote'}:
            self.text.append('\n')


def message_text(data):
    texts = {'text/plain': [], 'text/html': []}
    def walk(part):
        if part.get('filename'):
            return
        mime, body = part.get('mime_type'), part.get('body') or {}
        if mime in texts:
            value = body.get('content')
            if value is None and body.get('base64_url_content'):
                value = base64.urlsafe_b64decode(body['base64_url_content'] + '===').decode('utf-8', 'replace')
            if value:
                texts[mime].append(value)
        for child in part.get('parts') or []:
            walk(child)
    walk(data.get('payload') or {})
    if texts['text/plain']:
        return '\n'.join(texts['text/plain'])
    parser = MailText()
    parser.feed('\n'.join(texts['text/html']))
    return ''.join(parser.text) or data.get('snippet') or ''


def enrich_forwards(call, rows):
    """Read internal emails fully: client headers can lie beyond Gmail's snippet."""
    def enrich(row):
        if internal_sender(row['sender']):
            data = unpack(call('gmail.read_email', {'message_id': row['external_id']}), 'Gmail')
            body = message_text(data)
            row = {**row, 'forwarded_participants': forwarded_addresses(body)}
        return row
    with ThreadPoolExecutor(max_workers=4) as pool:
        return list(pool.map(enrich, rows))


def mail_pages(call, profile, result, query, limit=EMAIL_LIMIT, accept=None):
    rows, seen, pages = [], set(), 0
    while True:
        batch = [row for row in mail_rows(profile, result, limit) if row['external_id'] not in seen]
        for row in enrich_forwards(call, batch):
            seen.add(row['external_id'])
            if accept is None or accept(row):
                rows.append(row)
        cursor, pages = result.get('next_page_token'), pages+1
        if not cursor or len(rows) >= limit or pages >= 5:
            break
        size = EMAIL_LIMIT if accept else limit-len(rows)
        result = unpack(call('gmail.search_emails', {'query': query, 'max_results': size, 'next_page_token': cursor}), 'Gmail')
    rows.sort(key=lambda row: instant(row['date']), reverse=True)
    return rows[:limit], bool(cursor) or len(rows) > limit


def read_emails(call, query, limit=EMAIL_LIMIT, accept=None):
    """The latest matching project emails, independently of the inbox snapshot."""
    with ThreadPoolExecutor(max_workers=2) as pool:
        profile = pool.submit(call, 'gmail.get_profile', {})
        first = pool.submit(call, 'gmail.search_emails', {'query': query, 'max_results': min(EMAIL_LIMIT, limit)})
        result = unpack(first.result(), 'Gmail')
        return mail_pages(call, unpack(profile.result(), 'Gmail'), result, query, limit, accept)


def read_sources(call):
    """call(name, arguments) is an authenticated native mcpServer/tool/call."""
    stamp = datetime.now(timezone.utc)
    calendar_args = {'calendar_id': 'primary', 'time_min': (stamp-timedelta(days=7)).isoformat(),
                     'time_max': (stamp+timedelta(days=14)).isoformat(), 'max_results': 100,
                     'timezone_str': 'Europe/Zurich'}
    requests = [('gmail.get_profile', {}, 'Gmail'), ('google_calendar.get_profile', {}, 'Google Calendar'),
                ('gmail.search_emails', {'query': 'in:inbox', 'max_results': EMAIL_LIMIT}, 'Gmail'),
                ('google_calendar.search_events', calendar_args, 'Google Calendar')]
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(call, name, args) for name, args, _ in requests]
        values = [unpack(future.result(), provider) for future, (_, _, provider) in zip(futures, requests)]
    mail_profile, calendar_profile, mail_result, calendar_result = values
    mail_account, calendar_account = mail_profile.get('email'), calendar_profile.get('email')
    require(mail_account and calendar_account, 'Le compte des sources Google n’a pas été confirmé.')
    text = lambda value, limit=1000: str(value or '')[:limit]
    emails, _ = mail_pages(call, mail_profile, mail_result, 'in:inbox')
    events = list(calendar_result.get('events', []))
    cursor = calendar_result.get('next_page_token')
    pages = 1
    while cursor and pages < 5:
        page = unpack(call('google_calendar.search_events', {**calendar_args, 'next_page_token': cursor}), 'Google Calendar')
        events.extend(page.get('events', []))
        cursor, pages = page.get('next_page_token'), pages + 1
    require(not cursor, 'Le calendrier est trop volumineux pour ce relevé. Les aperçus précédents sont conservés.')
    rows, seen = [], set()
    for event in events:
        identifier, start = text(event.get('id')), native_date(event.get('start'))
        if not identifier or identifier in seen or not instant(start) or event.get('status') == 'cancelled' or event.get('event_type') == 'workingLocation' or event.get('my_response_status') == 'declined':
            continue
        seen.add(identifier)
        rows.append({'account': calendar_account, 'external_id': identifier, 'title': text(event.get('summary')),
                     'date': start, 'end': native_date(event.get('end')), 'body': '',
                     'sender': text((event.get('organizer') or {}).get('email')),
                     'url': text(event.get('display_url') or event.get('url')),
                     'participants': addresses(event.get('attendees') or [])})
    past = sorted((r for r in rows if instant(r['date']) <= stamp.timestamp()), key=lambda r: instant(r['date']), reverse=True)
    future = sorted((r for r in rows if instant(r['date']) > stamp.timestamp()), key=lambda r: instant(r['date']))
    return {'emails': emails, 'events': past[:10] + future[:30]}
