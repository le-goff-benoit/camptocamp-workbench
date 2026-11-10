"""Small stdio client for the public Claude Agent SDK control protocol."""
import json
import queue
import threading
import time
import uuid

from .storage import require


def events(process, prompt, timeout, required=(), discover=False):
    inbox = queue.Queue()
    def drain():
        for line in process.stdout:
            inbox.put(line)
        inbox.put(None)
    threading.Thread(target=drain, daemon=True).start()
    def send(value):
        process.stdin.write(json.dumps(value, ensure_ascii=False)+'\n')
        process.stdin.flush()
    init_id, status_id = str(uuid.uuid4()), None
    deadline, discovery_deadline, next_poll = time.monotonic()+timeout, time.monotonic()+45, 0
    sent, initialized = False, False
    send({'type':'control_request','request_id':init_id,'request':{'subtype':'initialize','hooks':None}})
    while time.monotonic() < deadline:
        if initialized and not sent and status_id is None and time.monotonic() >= next_poll:
            if required or discover:
                status_id = str(uuid.uuid4())
                send({'type':'control_request','request_id':status_id,'request':{'subtype':'mcp_status'}})
            else:
                send({'type':'user','session_id':'','parent_tool_use_id':None,'client_composed':True,
                      'message':{'role':'user','content':prompt}})
                sent = True
        try:
            line = inbox.get(timeout=.25)
        except queue.Empty:
            continue
        require(line is not None, 'Claude Code est arrêté. Vérifiez sa connexion dans Connexions.')
        try:
            message = json.loads(line)
        except ValueError:
            continue
        kind = message.get('type')
        if kind == 'control_response':
            reply = message.get('response') or {}
            require(reply.get('subtype') == 'success', 'Claude Code a refusé la vérification des connecteurs.')
            if reply.get('request_id') == init_id:
                initialized = True
            elif reply.get('request_id') == status_id:
                status_id = None
                servers = (reply.get('response') or {}).get('mcpServers', [])
                safe_servers = [{k:s[k] for k in ('name','status') if k in s} for s in servers]
                ready = all(any(s.get('name') == name and s.get('status') == 'connected' for s in servers) for name in required)
                complete = servers and not any(s.get('status') == 'pending' for s in servers)
                unavailable = any(s.get('name') in required and s.get('status') in {'failed','disabled','needs-auth'} for s in servers)
                if ready and (required or complete) or unavailable or time.monotonic() >= discovery_deadline:
                    metadata = {'type':'system','subtype':'connection_status','mcp_servers':safe_servers,
                                'tools':[t['name'] for s in servers for t in s.get('tools',[]) if t.get('name')]}
                    yield metadata
                    if discover:
                        yield {'type':'result','is_error':False,'result':'Connexions vérifiées.'}
                        return
                    require(ready, 'Connecteurs Claude indisponibles : '+', '.join(required)+'. Vérifiez-les dans Connexions.')
                    send({'type':'user','session_id':'','parent_tool_use_id':None,'client_composed':True,
                          'message':{'role':'user','content':prompt}})
                    sent = True
                else:
                    next_poll = time.monotonic()+1
        elif kind == 'control_request':
            send({'type':'control_response','response':{'subtype':'success','request_id':message['request_id'],
                  'response':{'behavior':'deny','message':'Workbench autorise uniquement les lectures demandées.'}}})
        else:
            yield message
            if kind == 'result':
                return
    require(False, 'Claude Code ne répond pas. Vérifiez sa connexion puis réessayez.')
