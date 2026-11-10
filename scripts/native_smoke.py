"""Explicit single real Codex run on a synthetic project, never a customer repo."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.core import Workbench
from backend.agents import Agents
from backend.storage import atomic

with tempfile.TemporaryDirectory(prefix='workbench-native-') as directory:
    base = Path(directory)
    repo = base / 'projects/atlas-native'
    repo.mkdir(parents=True)
    subprocess.run(['git', 'init', '-q', repo], check=True)
    atomic(repo / 'README.md', '# Atlas synthétique\n\nCe dépôt fictif sert uniquement à vérifier un analyste en lecture seule.\nLa méthode actuelle demande de vérifier les décisions avant de produire un compte rendu.\nAucun logiciel métier ni donnée client.\n')
    initial_source = (repo / 'README.md').read_bytes()
    core = Workbench(base / 'state')
    settings = core.settings(); settings.update(roots=[str(base / 'projects')], library=[]); core.save_settings(settings)
    project = core.projects()[0]['id']
    release = core.create_release(project, 'Analyse synthétique native')
    request = core.create_request(project, release['id'], 'Compte rendu de deux réunions',
        'Proposer uniquement une méthode courte pour transformer deux notes de réunion fournies en compte rendu, actions et email préparé non envoyé. '
        'Les responsables et dates manquants doivent rester inconnus. Aucun accès externe ni code demandé.')
    agents = Agents(core)
    job = agents.start(project, request['id'])
    print('Analyse Codex réelle démarrée sur un dépôt fictif, sans écriture métier.', flush=True)
    deadline = time.monotonic() + 640
    while time.monotonic() < deadline:
        result = next(j for j in agents.list() if j['id'] == job['id'])
        if result['status'] != 'running':
            break
        time.sleep(1)
    record = core.request(project, request['id'])
    proof = {'job': result, 'stage': record['stage'], 'status': record['status'],
             'source_unchanged': (repo / 'README.md').read_bytes() == initial_source,
             'scope': 'Un essai réel Codex ; sources synthétiques ; aucun service Google, aucune comparaison de modèles.'}
    (ROOT / '.runtime').mkdir(exist_ok=True)
    atomic(ROOT / '.runtime/native-smoke.json', json.dumps(proof, ensure_ascii=False, indent=2))
    print(json.dumps({key: proof[key] for key in ['stage', 'status', 'source_unchanged', 'scope']}, ensure_ascii=False))
    print('Résultat fournisseur : ' + result['status'])
    if result['status'] != 'done':
        print(result.get('error', 'Essai incomplet'))
        raise SystemExit(1)
