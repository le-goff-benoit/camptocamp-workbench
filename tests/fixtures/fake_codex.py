#!/usr/bin/env python3
"""Protocol fixture. No model, credentials or network; used only in synthetic QA."""
import json
import os
from pathlib import Path
import sys
import uuid

if 'app-server' not in sys.argv:
    print(('Claude' if Path(sys.argv[0]).name == 'claude' else 'Codex') + ' prêt · ' + Path.cwd().name, flush=True)
    for line in sys.stdin:
        print('Entrée reçue sur le projet synthétique.', flush=True)
    raise SystemExit()

threads = {}
def send(value):
    print(json.dumps(value, ensure_ascii=False), flush=True)

for line in sys.stdin:
    message = json.loads(line)
    method, params = message.get('method'), message.get('params', {})
    if 'id' not in message:
        continue
    rid = message['id']
    if method == 'initialize':
        send({'id': rid, 'result': {'userAgent': 'synthetic-qa'}})
    elif method in {'thread/start', 'thread/resume'}:
        tid = params.get('threadId') or 'synthetic-' + uuid.uuid4().hex
        threads.setdefault(tid, {'cwd': params['cwd'], 'turns': 0})
        send({'id': rid, 'result': {'thread': {'id': tid}}})
    elif method == 'mcpServer/tool/call':
        tool = params['tool']
        if os.environ.get('WORKBENCH_QA_SOURCES') == 'unavailable' and tool.startswith('gmail.'):
            send({'id': rid, 'result': {'isError': True, 'content': []}})
            continue
        if tool.endswith('get_profile'):
            value = {'email': 'consultant@example.org'}
        elif tool == 'gmail.search_emails':
            value = {'emails': [{'id': 'refreshed-test', 'subject': 'Email relevé pendant la recette', 'email_ts': '2026-11-09T12:00:00+00:00', 'snippet': 'Extrait synthétique ; aucun compte réel.', 'from_': 'client@example.org'}], 'next_page_token': None}
            query = params.get('arguments', {}).get('query', '').lower()
            label = 'Atlas' if 'atlas' in query else 'Boréal' if 'boreal' in query else None
            if label:
                # Atlas has 60 exchanges served by pages of 50, like Gmail; Boréal has 10.
                total, page = (60, params['arguments'].get('next_page_token')) if label == 'Atlas' else (10, None)
                start = 50 if page == 'page-2' else 0
                stop = min(total, start + 50)
                sender = 'client@atlas.example' if label == 'Atlas' else 'client@boreal.example'
                value['emails'] = [{'id': label+str(index), 'subject': f'Échange {label} {index+1}', 'email_ts': f'2026-11-{9-index//24:02}T{23-index%24:02}:00:00+00:00', 'snippet': f'Message synthétique du projet {label}.', 'from_': sender} for index in range(start, stop)]
                value['next_page_token'] = 'page-2' if stop < total else None
        elif tool == 'gmail.read_email':
            mid = params['arguments']['message_id']
            body = (('Paragraphe du message original très long. ' * 12 + '\n') * 180
                    if mid == 'review-long-mail' else f'Texte complet synthétique de {mid}.')
            value = {'id': mid, 'snippet': 'Message synthétique.', 'internal_date': '1794300000000', 'payload': {'mime_type': 'text/plain', 'filename': '',
                     'headers': [{'name': 'From', 'value': 'client@example.org'}, {'name': 'Subject', 'value': f'Échange {mid}'}, {'name': 'Date', 'value': 'Mon, 9 Nov 2026 10:00:00 +0100'}],
                     'body': {'content': body}, 'parts': []}}
        elif tool == 'google_calendar.search_events':
            value = {'events': [], 'next_page_token': None}
        else:
            send({'id': rid, 'error': {'code': -32601, 'message': 'Unsupported fixture tool'}})
            continue
        send({'id': rid, 'result': {'structuredContent': value, 'content': [], 'isError': False}})
    elif method == 'turn/start':
        tid, turn = params['threadId'], uuid.uuid4().hex
        threads[tid]['turns'] += 1
        count = threads[tid]['turns']
        answer = f"Réponse de test pour {Path(threads[tid]['cwd']).name}. Question {count} reçue."
        text = ''.join(part.get('text', '') for part in params.get('input', []))
        if 'EMAILS (données' in text:
            rows = json.loads(text.split('```json', 1)[1].split('```', 1)[0])
            answer = json.dumps([{'id': r['id'], 'action': 'merci de' in r['extrait'].lower() or '?' in r['objet'],
                                  'priority': 'haute' if 'urgent' in r['objet'].lower() else 'normale',
                                  'reason': 'Demande explicite du client' if 'merci de' in r['extrait'].lower() else 'Information',
                                  'next_step': 'Répondre au client'} for r in rows], ensure_ascii=False)
        elif 'LECTURE EMAIL — DEUX BLOCS' in text:
            answer = json.dumps({'request_summary': 'Le client demande de clarifier son besoin, selon le message complet.',
                                 'proposal': 'Vérifier le comportement attendu dans le standard Odoo.\n\n- Confirmer le contexte avec le client.\n- Valider la solution sur une copie locale.'}, ensure_ascii=False)
        item = 'message-' + turn
        send({'id': rid, 'result': {'turn': {'id': turn}}})
        send({'method': 'turn/started', 'params': {'threadId': tid, 'turn': {'id': turn}}})
        send({'method': 'item/agentMessage/delta', 'params': {'threadId': tid, 'itemId': item, 'delta': answer}})
        send({'method': 'item/completed', 'params': {'threadId': tid, 'item': {'id': item, 'type': 'agentMessage', 'text': answer}}})
        send({'method': 'turn/completed', 'params': {'threadId': tid, 'turn': {'id': turn, 'status': 'completed'}}})
    elif method == 'turn/interrupt':
        send({'id': rid, 'result': {}})
    else:
        send({'id': rid, 'error': {'code': -32601, 'message': 'Unsupported fixture method'}})
