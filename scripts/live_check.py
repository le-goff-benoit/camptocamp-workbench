"""Read-only proof against the installed local Gateway, never a customer service."""
import json
from pathlib import Path
import subprocess
import sys
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.storage import atomic, read

base = 'http://127.0.0.1:18793'
state = Path.home() / '.local/share/openclaw-workbench'
access = read(state / 'private/session-token')
headers = {'Content-Type': 'application/json', 'Origin': base}

def get(path):
    with urlopen(base + path, timeout=10) as response:
        return response.status, response.headers, response.read()

def post(path, data, extra=None):
    request = Request(base + path, data=json.dumps(data).encode(), headers={**headers, **(extra or {})}, method='POST')
    with urlopen(request, timeout=20) as response:
        return response.status, response.headers, json.load(response)

result = {'scope': 'Instance Workbench locale ; lecture de santé, ressources, dashboard, suivi et outils MCP uniquement.'}
status, _, body = get('/workbench/health')
assert status == 200 and json.loads(body)['ok']
result['health'] = 'pass'
result['version'] = json.loads(body)['version']
for path in ['/workbench/static/workbench.css', '/workbench/static/chooser.mjs', '/workbench/static/brand/camptocamp-logo.png', '/workbench/static/fonts/Lato-Regular.ttf']:
    status, response_headers, body = get(path)
    assert status == 200 and body
result['brand_assets'] = 'pass'
_, _, email_ui = get('/workbench/static/app.mjs')
assert 'Résumé de la demande du client' in email_ui.decode() and 'Ma proposition / analyse / solution' in email_ui.decode()
result['email_review_assets'] = 'pass'
try:
    post('/workbench/api', {'action': 'snapshot'})
    raise AssertionError('Unauthenticated access accepted')
except HTTPError as error:
    assert error.code == 401
result['unauthenticated_api_rejected'] = 'pass'
status, session_headers, body = post('/workbench/session', {'token': access})
assert 'HttpOnly' in session_headers['Set-Cookie'] and 'SameSite=Strict' in session_headers['Set-Cookie']
_, _, snapshot = post('/workbench/api', {'action': 'snapshot'}, {'Cookie': 'workbench_session=' + access, 'X-Workbench-UI': '1'})
assert snapshot['ok']
result['configured_project_roots'] = len(snapshot['result']['settings']['roots'])
result['independent_google_connected'] = snapshot['result']['google']['connected']
browser_headers = {'Cookie': 'workbench_session=' + access, 'X-Workbench-UI': '1'}
for extra, code, expected in [({'X-Workbench-Key': access}, 401, ''),
                              ({'Cookie': 'workbench_session=' + access}, 400, 'interface utilisateur'),
                              (browser_headers, 400, 'Identifiant d’email invalide')]:
    try:
        # Invalid ID: verifies the installed route and its human guard without
        # reading any message, creating cache entries or calling a model.
        post('/workbench/api', {'action': 'email.review', 'data': {'message': '!'}}, extra)
        raise AssertionError('Invalid email review request accepted')
    except HTTPError as error:
        assert error.code == code and expected in json.load(error).get('error', '')
result['email_review_installed_and_human_only'] = 'pass'
_, _, dashboard = post('/workbench/api', {'action': 'dashboard.get'}, browser_headers)
assert dashboard['ok']
cockpit = dashboard['result']
result['discovered_projects'] = cockpit['projects']
result['open_release_folders'] = cockpit['open_release_count']
result['git_warnings'] = len(cockpit['alerts'])
result['native_email_snapshot_available'] = bool(cockpit['last_email'])
result['native_events_available'] = bool(cockpit['last_event'] or cockpit['next_events'])
if cockpit['open_releases']:
    release = cockpit['open_releases'][0]
    _, _, overview = post('/workbench/api', {'action': 'release.overview', 'data': {'project': release['project'], 'release': release['id']}}, browser_headers)
    assert overview['ok'] and overview['result']['state'] and overview['result']['next_action']
    result['release_status_and_measures'] = 'pass'
messages = [{'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {}},
            {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list'},
            {'jsonrpc': '2.0', 'id': 3, 'method': 'tools/call', 'params': {'name': 'workbench_dashboard', 'arguments': {}}}]
bridge = subprocess.run([sys.executable, str(ROOT / 'scripts/codex_mcp.py')], input=''.join(json.dumps(m) + '\n' for m in messages), capture_output=True, text=True, timeout=30, check=True)
answers = [json.loads(line) for line in bridge.stdout.splitlines()]
assert len(answers) == 3 and len(answers[1]['result']['tools']) == 7
assert not answers[2]['result'].get('isError')
assert json.loads(answers[2]['result']['content'][0]['text'])['projects'] == cockpit['projects']
result['native_codex_mcp_read'] = 'pass'
configuration = json.loads(read(Path.home() / '.openclaw-workbench/openclaw.json'))
_, _, invocation = post('/tools/invoke', {'tool': 'workbench_status', 'args': {}},
                         {'Authorization': 'Bearer ' + configuration['gateway']['auth']['token']})
assert invocation.get('ok') and invocation.get('result')
result['openclaw_tool_invocation'] = 'pass'
atomic(ROOT / '.runtime/live-check.json', json.dumps(result, ensure_ascii=False, indent=2))
print(json.dumps(result, ensure_ascii=False, indent=2))
