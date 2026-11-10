#!/usr/bin/env python3
"""Native Codex MCP bridge to local tracking; never authenticates Google itself."""
import argparse
import json
from pathlib import Path
import sys
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.mail import EMAIL_LIMIT

STRING = {'type': 'string'}
SOURCE = {'type': 'object', 'properties': {key: STRING for key in ['account', 'external_id', 'title', 'sender', 'date', 'end', 'url', 'body']},
          'required': ['account', 'external_id', 'title', 'date'], 'additionalProperties': False}


def schema(properties, required=None):
    return {'type': 'object', 'properties': properties, 'required': list(properties) if required is None else required, 'additionalProperties': False}


TOOLS = [
    ('workbench_status', 'Lire les projets locaux et les demandes du consultant.', 'snapshot', schema({})),
    ('workbench_project', 'Lire les releases, demandes et environnements déclarés d’un projet.', 'project.get', schema({'project': STRING})),
    ('workbench_dashboard', 'Lire le dashboard consultant : emails et événements effectivement récupérés, releases actives.', 'dashboard.get', schema({})),
    ('workbench_release_overview', 'Lire le statut, la prochaine action et les mesures Tricorder d’une release.', 'release.overview', schema({'project': STRING, 'release': STRING})),
    ('workbench_dashboard_sources', 'Mettre à jour les cartes du dashboard avec les seuls emails et événements effectivement lus avec les plugins autorisés. Aucun email envoyé, aucune tâche créée.', 'dashboard.sources', schema({'emails': {'type': 'array', 'items': SOURCE, 'maxItems': EMAIL_LIMIT}, 'events': {'type': 'array', 'items': SOURCE, 'maxItems': 40}}, [])),
    ('workbench_ingest', 'Créer/classer une demande depuis un email ou événement réellement lu. Correspondance certaine par règles configurées, sinon à trier. Identifiant source et compte empêchent les doublons.', 'intake.ingest', schema({'source': {'type': 'object', 'properties': {**SOURCE['properties'], 'kind': {'type': 'string', 'enum': ['email', 'calendar']}}, 'required': ['kind', 'account', 'external_id', 'title', 'body'], 'additionalProperties': False}})),
    ('workbench_memory', 'Lire l’index court et les références mémoire pertinentes du projet.', 'memory.context', schema({'project': STRING, 'query': STRING, 'release': STRING}, ['project'])),
]


class Bridge:
    def __init__(self, state, port=18794):
        self.state, self.port = Path(state), port

    def call(self, action, arguments):
        key = (self.state / 'private/session-token').read_text()
        request = Request(f'http://127.0.0.1:{self.port}/workbench/api',
                          data=json.dumps({'action': action, 'data': arguments}).encode(), method='POST',
                          headers={'Content-Type': 'application/json', 'X-Workbench-Key': key})
        with urlopen(request, timeout=90) as response:
            result = json.load(response)
        if not result.get('ok'):
            raise ValueError('Commande Workbench refusée')
        value = result['result']
        if action == 'snapshot':
            return {'projects': value['projects'], 'jobs': [{k: j.get(k) for k in ['id', 'project', 'request', 'status']} for j in value['jobs']]}
        return value

    def handle(self, request):
        method, params = request.get('method'), request.get('params', {})
        if 'id' not in request:
            return None
        rid = request['id']
        try:
            if method == 'initialize':
                value = {'protocolVersion': '2024-11-05', 'capabilities': {'tools': {}}, 'serverInfo': {'name': 'camptocamp-workbench', 'version': '0.4.0'},
                         'instructions': 'Ce serveur gère uniquement le suivi local. Utiliser les plugins Gmail et Google Calendar déjà autorisés pour lire les sources, puis transmettre les résultats effectivement lus. En cas de 401, demander la réauthentification ; ne pas inventer de données. Un dashboard ne crée pas de tâches. Aucun outil d’approbation humaine ni terminal n’est exposé.'}
            elif method == 'ping':
                value = {}
            elif method == 'tools/list':
                readonly = {'snapshot', 'project.get', 'dashboard.get', 'release.overview', 'memory.context'}
                value = {'tools': [{'name': n, 'description': d, 'inputSchema': s,
                                    'annotations': {'readOnlyHint': a in readonly, 'destructiveHint': False,
                                                    'idempotentHint': a in readonly or a == 'intake.ingest', 'openWorldHint': False}}
                                   for n, d, a, s in TOOLS]}
            elif method == 'tools/call':
                tool = next((t for t in TOOLS if t[0] == params.get('name')), None)
                if not tool:
                    raise ValueError('Outil inconnu')
                args = params.get('arguments', {})
                if not isinstance(args, dict) or set(args) - set(tool[3]['properties']) or any(k not in args for k in tool[3]['required']):
                    raise ValueError('Arguments invalides')
                try:
                    answer = self.call(tool[2], args)
                    value = {'content': [{'type': 'text', 'text': json.dumps(answer, ensure_ascii=False)}]}
                except Exception:
                    value = {'isError': True, 'content': [{'type': 'text', 'text': 'Workbench indisponible ou opération refusée. Ouvrez Camptocamp Workbench et vérifiez son état.'}]}
            else:
                return {'jsonrpc': '2.0', 'id': rid, 'error': {'code': -32601, 'message': 'Méthode inconnue'}}
            return {'jsonrpc': '2.0', 'id': rid, 'result': value}
        except (ValueError, TypeError, KeyError):
            return {'jsonrpc': '2.0', 'id': rid, 'error': {'code': -32602, 'message': 'Requête invalide'}}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--state', default=str(Path.home() / '.local/share/openclaw-workbench'))
    parser.add_argument('--port', type=int, default=18794)
    args = parser.parse_args()
    bridge = Bridge(args.state, args.port)
    for line in sys.stdin:
        if len(line) > 1_000_000:
            continue
        try:
            response = bridge.handle(json.loads(line))
        except (ValueError, TypeError):
            response = {'jsonrpc': '2.0', 'id': None, 'error': {'code': -32700, 'message': 'JSON invalide'}}
        if response is not None:
            print(json.dumps(response, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
