"""Email display limits and client addresses in forwarded headers."""
from email.utils import getaddresses
import re

EMAIL_LIMIT = 50
ADDRESS = re.compile(r'[\w.+-]+@[\w-]+(?:\.[\w-]+)+')
HEADERS = re.compile(r'(?im)(?<!\S)(from|de|von|to|à|an|cc|bcc|cci|sent|envoyé|gesendet|date|subject|objet|betreff)\s*:\s*')


def internal_sender(sender):
    return any(address.casefold().endswith('@camptocamp.com') for _, address in getaddresses([sender or '']))


def forwarded_addresses(body):
    """Only quoted address headers identify a client; ordinary signatures do not."""
    text = str(body or '').replace('> ', ' ')
    headers = list(HEADERS.finditer(text))
    if not any(h[1].casefold() in {'from', 'de', 'von'} for h in headers):
        return ''
    found = []
    for index, header in enumerate(headers):
        if header[1].casefold() not in {'from', 'de', 'von', 'to', 'à', 'an', 'cc', 'bcc', 'cci'}:
            continue
        end = headers[index+1].start() if index+1 < len(headers) else len(text)
        value = text[header.end():end].split('\n', 1)[0].split('\r', 1)[0]
        found.extend(ADDRESS.findall(value))
    return ', '.join(dict.fromkeys(a.casefold() for a in found if not a.casefold().endswith('@camptocamp.com')))
