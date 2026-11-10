"""Google desktop OAuth/PKCE and read-only, paginated Gmail/Calendar intake."""
import base64
from datetime import datetime, timedelta, timezone
import hashlib
import json
import secrets
import threading
import time
from urllib.error import HTTPError
from urllib.parse import urlencode, quote
from urllib.request import Request, urlopen

from .core import now, clean
from .storage import atomic, read, require, safe, locked

SCOPES = ['https://www.googleapis.com/auth/gmail.readonly', 'https://www.googleapis.com/auth/calendar.readonly']


class GoogleSources:
    def __init__(self, core):
        self.core, self.pending, self.lock = core, {}, threading.RLock()
        self.auth_path = safe(core.state, 'private/google-auth.json')
        self.client_path = safe(core.state, 'private/google-client.json')
        self.last_path = safe(core.state, 'google-status.json')
        self.sync_lock = threading.Lock()

    def status(self):
        status = {'configured': self.client_path.exists(), 'connected': self.auth_path.exists(), 'scopes': SCOPES,
                  'provider': 'Google', 'readonly': True, 'account': None}
        if self.last_path.exists():
            status.update(json.loads(read(self.last_path)))
        status['stage'] = 'connected' if status['connected'] else 'authorization_required' if status['configured'] else 'client_required'
        return status

    def set_client(self, document):
        require(isinstance(document, dict) and isinstance(document.get('installed'), dict), 'Fichier OAuth Google de type Application de bureau attendu')
        client = document['installed']
        require(isinstance(client.get('client_id'), str) and client['client_id'].endswith('.apps.googleusercontent.com'), 'Client OAuth Google invalide')
        atomic(self.client_path, json.dumps({k: client[k] for k in ['client_id', 'client_secret'] if k in client}))
        return self.status()

    def begin(self, redirect_uri):
        require(self.client_path.exists(), 'Importez d’abord le fichier client OAuth Google pour application de bureau')
        client = json.loads(read(self.client_path))
        verifier = secrets.token_urlsafe(48)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
        state = secrets.token_urlsafe(32)
        with self.lock:
            self.pending = {state: {'verifier': verifier, 'redirect_uri': redirect_uri, 'expires': time.time() + 600}}
        return {'url': 'https://accounts.google.com/o/oauth2/v2/auth?' + urlencode({
            'client_id': client['client_id'], 'redirect_uri': redirect_uri, 'response_type': 'code',
            'scope': ' '.join(SCOPES), 'access_type': 'offline', 'prompt': 'consent', 'state': state,
            'code_challenge': challenge, 'code_challenge_method': 'S256'})}

    def _token_request(self, parameters):
        client = json.loads(read(self.client_path))
        parameters.update(client)
        req = Request('https://oauth2.googleapis.com/token', data=urlencode(parameters).encode(), method='POST')
        try:
            with urlopen(req, timeout=25) as response:
                return json.load(response)
        except HTTPError as error:
            try:
                reason = json.loads(error.read(8192)).get('error', '')
            except (ValueError, AttributeError):
                reason = ''
            message = {
                'invalid_client': 'Client OAuth Google refusé. Importez le JSON d’un client de type Application de bureau.',
                'invalid_grant': 'Autorisation Google expirée ou déjà utilisée. Relancez Connecter Google.',
                'redirect_uri_mismatch': 'Retour OAuth refusé : le client Google doit être de type Application de bureau.',
                'access_denied': 'Autorisation Google refusée. Vérifiez votre compte et les utilisateurs de test de l’application.',
            }.get(reason, 'Google a refusé l’authentification. Vérifiez le client OAuth et reconnectez le compte.')
            raise ValueError(message) from error

    def callback(self, state, code):
        with self.lock:
            pending = self.pending.pop(state, None)
        require(pending and pending['expires'] > time.time(), 'Connexion OAuth expirée ou état invalide')
        token = self._token_request({'grant_type': 'authorization_code', 'code': code,
                                     'redirect_uri': pending['redirect_uri'], 'code_verifier': pending['verifier']})
        require(all(s in token.get('scope', '').split() for s in SCOPES), 'Les deux permissions de lecture sont requises ; connexion non enregistrée')
        token['expires_at'] = time.time() + token.get('expires_in', 3600)
        atomic(self.auth_path, json.dumps(token))
        return self.status()

    def _token(self):
        require(self.auth_path.exists(), 'Compte Google non connecté')
        with self.lock:
            token = json.loads(read(self.auth_path))
            if token['expires_at'] <= time.time() + 60:
                require(token.get('refresh_token'), 'Reconnectez le compte Google')
                refresh = self._token_request({'grant_type': 'refresh_token', 'refresh_token': token['refresh_token']})
                token.update(refresh)
                token['expires_at'] = time.time() + refresh.get('expires_in', 3600)
                atomic(self.auth_path, json.dumps(token))
            return token['access_token']

    def get(self, url):
        require(url.startswith(('https://gmail.googleapis.com/', 'https://www.googleapis.com/calendar/')), 'Endpoint Google non autorisé')
        request = Request(url, headers={'Authorization': 'Bearer ' + self._token()})
        try:
            with urlopen(request, timeout=25) as response:
                return json.load(response)
        except HTTPError as error:
            raise ValueError(f'Lecture Google impossible (HTTP {error.code}) ; vérifier les APIs et permissions du compte.') from error

    def synchronize(self):
        require(self.sync_lock.acquire(blocking=False), 'Une synchronisation est déjà en cours')
        try:
            return self._synchronize()
        except Exception as error:
            state = self.status()
            atomic(self.last_path, json.dumps({'last_error': str(error), 'last_attempt': now(), 'account': state.get('account')}))
            raise
        finally:
            self.sync_lock.release()

    def _synchronize(self):
        settings = self.core.settings().get('intake', {})
        query = clean(settings.get('gmail_query', 'in:inbox newer_than:7d'), 500)
        require(query, 'Filtre Gmail nécessaire avant lecture')
        profile = self.get('https://gmail.googleapis.com/gmail/v1/users/me/profile')
        account = profile['emailAddress']
        count, page, pages = 0, None, 0
        while pages < 5:
            params = {'q': query, 'maxResults': 25}
            if page:
                params['pageToken'] = page
            messages = self.get('https://gmail.googleapis.com/gmail/v1/users/me/messages?' + urlencode(params))
            for reference in messages.get('messages', []):
                key = hashlib.sha256(('email\n' + account + '\n' + reference['id']).encode()).hexdigest()
                if safe(self.core.state, 'inbox/' + key + '.json').exists():
                    continue
                message = self.get('https://gmail.googleapis.com/gmail/v1/users/me/messages/' + quote(reference['id'], safe='') + '?format=full')
                headers = {h['name'].casefold(): h['value'] for h in message.get('payload', {}).get('headers', [])}
                text = []
                def parts(part):
                    if part.get('mimeType') == 'text/plain' and part.get('body', {}).get('data'):
                        encoded = part['body']['data']
                        text.append(base64.urlsafe_b64decode(encoded + '=' * (-len(encoded) % 4)).decode('utf-8', 'replace'))
                    for child in part.get('parts', []):
                        parts(child)
                parts(message.get('payload', {}))
                self.core.ingest({'kind': 'email', 'account': account, 'external_id': message['id'],
                                  'sender': headers.get('from', ''), 'participants': [], 'title': headers.get('subject', ''),
                                  'body': '\n'.join(text)[:100000] or message.get('snippet', ''),
                                  'date': headers.get('date', ''), 'url': 'https://mail.google.com/mail/u/0/#inbox/' + message['id']})
                count += 1
            page = messages.get('nextPageToken')
            pages += 1
            if not page:
                break
        gmail_more = bool(page)
        calendar_id = clean(settings.get('calendar_id', 'primary'), 500)
        start = datetime.now(timezone.utc) - timedelta(days=1)
        end = start + timedelta(days=15)
        page, pages = None, 0
        while pages < 5:
            params = {'timeMin': start.isoformat(), 'timeMax': end.isoformat(), 'singleEvents': 'true', 'maxResults': 100}
            if page:
                params['pageToken'] = page
            events = self.get('https://www.googleapis.com/calendar/v3/calendars/' + quote(calendar_id, safe='') + '/events?' + urlencode(params))
            for event in events.get('items', []):
                if event.get('status') == 'cancelled':
                    continue
                # Only external attendees/organizers are candidates; the mailbox owner is not a client.
                participants = [a['email'] for a in event.get('attendees', []) if a.get('email') and not a.get('self') and a['email'].casefold() != account.casefold()]
                organizer = event.get('organizer', {}).get('email', '')
                if organizer.casefold() == account.casefold():
                    organizer = ''
                self.core.ingest({'kind': 'calendar', 'account': account + ':' + calendar_id,
                                  'external_id': event['id'], 'sender': organizer, 'participants': participants,
                                  'title': event.get('summary', 'Événement'), 'body': event.get('description', '')[:100000],
                                  'url': event.get('htmlLink', ''), 'date': event.get('start', {}).get('dateTime') or event.get('start', {}).get('date', '')})
                count += 1
            page = events.get('nextPageToken')
            pages += 1
            if not page:
                break
        result = {'account': account, 'last_sync': now(), 'last_error': None, 'processed': count,
                  'truncated': gmail_more or bool(page), 'coverage': 'Gmail : filtre configuré, 125 messages maximum ; calendrier : hier à J+13, 500 événements maximum.'}
        atomic(self.last_path, json.dumps(result, ensure_ascii=False))
        return result

    def background(self, stop):
        while not stop.wait(30):
            settings = self.core.settings().get('intake', {})
            if not settings.get('enabled') or not self.auth_path.exists():
                continue
            status = self.status()
            last = status.get('last_attempt') or status.get('last_sync')
            if last:
                elapsed = (datetime.now(timezone.utc) - datetime.fromisoformat(last)).total_seconds()
                if elapsed < max(5, int(settings.get('poll_minutes', 15))) * 60:
                    continue
            try:
                self.synchronize()
            except Exception:
                pass  # Error is persisted and visible in Connections, never retried in a tight loop.
