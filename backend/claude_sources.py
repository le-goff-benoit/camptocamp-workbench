"""Normalize actual Claude connector receipts into Workbench source records."""
import base64
from datetime import datetime, timezone

from .dashboard import instant
from .mail import forwarded_addresses, internal_sender


def objects(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from objects(child)
    elif isinstance(value, list):
        for child in value:
            yield from objects(child)


def payload(value):
    if isinstance(value, dict) and isinstance(value.get('structuredContent'), dict):
        return value['structuredContent']
    return value


def headers(message):
    values = (message.get('payload') or {}).get('headers') or message.get('headers') or []
    if isinstance(values, dict):
        return {k.casefold(): v for k, v in values.items()}
    return {h.get('name', '').casefold(): h.get('value', '') for h in values if isinstance(h, dict)}


def recipients(value):
    if isinstance(value, list):
        return ', '.join(recipients(item) for item in value)
    if isinstance(value, dict):
        return str(value.get('emailAddress') or value.get('email') or value.get('address') or '')
    return str(value or '')


def date(value):
    if isinstance(value, (float, int)) or str(value or '').isdigit():
        stamp = float(value)
        return datetime.fromtimestamp(stamp/1000 if stamp > 10**11 else stamp, timezone.utc).isoformat()
    if instant(value):
        return str(value)
    return ''


def message_body(message):
    from .native_sources import MailText
    plain, html = [], []
    for part in objects(message.get('payload') or {}):
        if part.get('filename'):
            continue
        mime = part.get('mimeType') or part.get('mime_type')
        body = part.get('body')
        if mime not in {'text/plain', 'text/html'} or not isinstance(body, dict):
            continue
        text = body.get('content')
        encoded = body.get('data') or body.get('base64_url_content')
        if text is None and encoded:
            text = base64.urlsafe_b64decode(encoded+'===').decode('utf-8', 'replace')
        if text:
            (plain if mime == 'text/plain' else html).append(text)
    if plain:
        return '\n'.join(plain)
    if html:
        parser = MailText(); parser.feed('\n'.join(html))
        return ''.join(parser.text)
    for key in ('plaintextBody', 'body', 'body_text', 'bodyText', 'textBody', 'text'):
        if isinstance(message.get(key), str):
            return message[key]
    if isinstance(message.get('htmlBody'), str):
        parser = MailText(); parser.feed(message['htmlBody']); return ''.join(parser.text)
    if isinstance(message.get('snippet'), str):
        return message['snippet']
    return ''


def emails_from(records, *, inbox=False):
    rows = {}
    for receipt in records:
        if receipt.get('isError') or not receipt.get('name', '').startswith('mcp__claude_ai_Gmail__'):
            continue
        for message in objects(receipt.get('value')):
            head = headers(message)
            identifier = message.get('id') or message.get('message_id') or message.get('messageId')
            subject = head.get('subject') or message.get('subject')
            stamp = date(message.get('internalDate') or message.get('internal_date') or head.get('date')
                         or message.get('date') or message.get('email_ts') or message.get('received_at'))
            sender = head.get('from') or message.get('from') or message.get('from_') or message.get('sender')
            if not identifier or subject is None or not stamp or not isinstance(sender, str):
                continue
            labels = message.get('labelIds') or message.get('label_ids')
            if inbox and labels is not None and 'INBOX' not in labels:
                continue
            body = message_body(message)
            row = {'account': 'claude:Gmail', 'external_id': str(identifier), 'title': str(subject),
                   'sender': sender, 'date': stamp, 'participants': ', '.join(recipients(head.get(k) or message.get(k) or message.get(k+'Recipients')) for k in ('to', 'cc')),
                   'body': str(message.get('snippet') or body)[:5000],
                   'url': message.get('viewUrl') or message.get('url') or message.get('display_url') or 'https://mail.google.com/mail/u/0/#all/'+str(identifier),
                   'forwarded_participants': forwarded_addresses(body) if internal_sender(sender) else ''}
            rows[str(identifier)] = row
    return sorted(rows.values(), key=lambda r: instant(r['date']), reverse=True)


def event_date(value):
    return (value.get('dateTime') or value.get('date') or '') if isinstance(value, dict) else value or ''


def events_from(records):
    rows = {}
    for receipt in records:
        if receipt.get('isError') or not receipt.get('name', '').startswith('mcp__claude_ai_Google_Calendar__'):
            continue
        for event in objects(receipt.get('value')):
            identifier, start = event.get('id') or event.get('event_id'), event_date(event.get('start'))
            if not identifier or not start or not instant(start) or event.get('status') == 'cancelled' or event.get('eventType') == 'workingLocation':
                continue
            attendees = event.get('attendees') or []
            if any(a.get('self') and a.get('responseStatus') == 'declined' for a in attendees if isinstance(a, dict)):
                continue
            rows[str(identifier)] = {'account': 'claude:Google Calendar', 'external_id': str(identifier),
                'title': event.get('summary') or event.get('title') or '', 'date': start, 'end': event_date(event.get('end')),
                'sender': (event.get('organizer') or {}).get('email', ''),
                'participants': ', '.join(a['email'] for a in attendees if isinstance(a, dict) and a.get('email')),
                'url': event.get('htmlLink') or event.get('url') or '', 'body': ''}
    return list(rows.values())


def successful(records, prefix, operations):
    return any(not r.get('isError') and r.get('name', '').startswith(prefix)
               and r['name'].removeprefix(prefix) in operations and isinstance(r.get('value'), (dict, list)) for r in records)
