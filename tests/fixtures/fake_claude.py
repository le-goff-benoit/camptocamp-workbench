#!/usr/bin/env python3
"""Synthetic Claude Code events; never contacts a provider or a Google account."""
from datetime import datetime, timedelta, timezone
import json
import os
import re
import shlex
import subprocess
import sys

def send(value):
    print(json.dumps(value, ensure_ascii=False), flush=True)

if '-p' not in sys.argv:
    if 'auth' in sys.argv:
        send({'loggedIn': True, 'authMethod': 'claude.ai'})
    else:
        from pathlib import Path
        print('Claude prêt · '+Path.cwd().name, flush=True)
        for line in sys.stdin:
            print('Entrée reçue sur le projet synthétique.',flush=True)
    raise SystemExit()

unavailable = os.environ.get('WORKBENCH_QA_CLAUDE') == 'unavailable'
gmail, calendar = 'mcp__claude_ai_Gmail__', 'mcp__claude_ai_Google_Calendar__'
servers = [{'name':'claude.ai Gmail','status':'needs-auth' if unavailable else 'connected'},
           {'name':'claude.ai Google Calendar','status':'needs-auth' if unavailable else 'connected'}]
if '--input-format' in sys.argv:
    for line in sys.stdin:
        incoming=json.loads(line)
        if incoming['type']=='control_request':
            response={'mcpServers':servers} if incoming['request']['subtype']=='mcp_status' else {}
            send({'type':'control_response','response':{'subtype':'success','request_id':incoming['request_id'],'response':response}})
        elif incoming['type']=='user':
            prompt=incoming['message']['content']
            break
else:
    prompt = sys.stdin.read()
send({'type': 'system', 'subtype': 'init', 'tools': [gmail+'search_threads', gmail+'get_thread', calendar+'list_events'],
      'mcp_servers': servers})
counter = 0
def receipt(name, arguments, value):
    global counter
    counter += 1
    settings = json.loads(sys.argv[sys.argv.index('--settings')+1])
    hook = settings['hooks']['PreToolUse'][0]['hooks'][0]['command']
    guarded = subprocess.run(shlex.split(hook), input=json.dumps({'tool_name': name, 'tool_input': arguments}), text=True, capture_output=True, check=True)
    permit = json.loads(guarded.stdout)['hookSpecificOutput']['permissionDecision'] == 'allow'
    identifier = str(counter)
    send({'type': 'assistant', 'message': {'content': [{'type': 'tool_use', 'id': identifier, 'name': name, 'input': arguments}]}})
    send({'type': 'user', 'tool_use_result': value if permit else {'error': 'Denied'}, 'message': {'content': [
        {'type': 'tool_result', 'tool_use_id': identifier, 'is_error': not permit, 'content': json.dumps(value if permit else {'error':'Denied'})}]}})

answer = 'OK'
stamp = datetime.now(timezone.utc)
def message(index):
    return {'id': f'claude-mail-{index}', 'labelIds': ['INBOX'], 'internalDate': str(int((stamp-timedelta(minutes=index)).timestamp()*1000)),
            'snippet': f'Extrait synthétique {index}', 'payload': {'mimeType': 'text/plain',
            'headers': [{'name':'From','value':'collegue@camptocamp.com' if index == 0 else 'client@atlas.example'},
                        {'name':'Subject','value':f'Message Claude {index}'}, {'name':'To','value':'consultant@example.org'}],
            'body': {'content':'From: client@atlas.example\nTo: collegue@camptocamp.com\n\nContenu complet synthétique.'}}}

if os.environ.get('WORKBENCH_QA_CLAUDE') == 'forbidden':
    receipt(gmail+'send_message', {'to':'nobody@example.org'}, {'sent':True})
elif '50 emails' in prompt and not unavailable:
    receipt(gmail+'search_threads', {'query':'in:inbox','max_results':50}, {'threads':[{'id':'thread-1'}]})
    receipt(gmail+'get_thread', {'thread_id':'thread-1'}, {'messages':[message(i) for i in range(50)]})
    if 'calendrier principal' in prompt:
        receipt(calendar+'list_events', {'calendar_id':'primary'}, {'items':[
            {'id':'future','summary':'Rendez-vous vérifié','start':{'dateTime':(stamp+timedelta(hours=2)).isoformat()},'end':{'dateTime':(stamp+timedelta(hours=3)).isoformat()}, 'attendees':[{'email':'client@atlas.example'}]},
            {'id':'cancelled','status':'cancelled','start':{'dateTime':stamp.isoformat()}}]})
elif 'Lis seulement le message Gmail' in prompt and not unavailable:
    mid = re.search(r'identifié par ("[^"]+")', prompt)
    row = message(0); row['id'] = json.loads(mid[1])
    receipt(gmail+'get_message', {'message_id':row['id']}, row)
elif 'EMAILS (données' in prompt:
    rows = json.loads(prompt.split('```json',1)[1].split('```',1)[0])
    answer = json.dumps([{'id':r['id'], 'action':True, 'priority':'normale','reason':'Demande explicite','next_step':'Répondre au client'} for r in rows])
elif 'LECTURE EMAIL — DEUX BLOCS' in prompt:
    answer = json.dumps({'request_summary':'Le client demande une clarification, selon son email complet.',
                         'proposal':'Vérifier le besoin avec le client avant de proposer une adaptation.'})
elif 'Tu es le responsable de l’analyse' in prompt:
    answer = json.dumps({key:'Analyse synthétique vérifiable.' for key in ('analysis','criteria','plan','questions','risks')})
final={'type':'result','subtype':'success','is_error':False,'result':answer}
if '--json-schema' in sys.argv:
    receipt('StructuredOutput',json.loads(answer),{'valid':True})
    final['structured_output']=json.loads(answer)
send(final)
