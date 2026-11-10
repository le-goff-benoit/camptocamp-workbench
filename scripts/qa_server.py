"""Disposable, synthetic workspace used only by the browser test suite."""
from http.server import ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import shutil
import signal
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.server import App, handler
from backend.storage import atomic

with tempfile.TemporaryDirectory(prefix='workbench-ui-') as directory:
    base = Path(directory)
    repo = base / 'projects/atlas-demo'
    repo.mkdir(parents=True)
    subprocess.run(['git', 'init', '-q', repo], check=True)
    subprocess.run(['git', '-C', str(repo), 'remote', 'add', 'origin', 'git@github.com:example/atlas-demo.git'], check=True)
    atomic(repo / 'README.md', '# Projet Atlas\n\nDépôt de démonstration synthétique, sans données client.\n')
    other = base / 'projects/boreal-demo'
    other.mkdir(parents=True)
    subprocess.run(['git', 'init', '-q', other], check=True)
    # Boréal is an Odoo project with an open agents release tracked by points.
    (other / '.odoo-agents').mkdir()
    atomic(other / 'changelog/2026-11-09_01_acomptes/README.md', '<!-- release ouverte -->\n# Acomptes\n\n## Points\n\n| # | Point | Test | État |\n|---|---|---|---|\n| 1 | Corriger la TVA des acomptes | test_tva | à faire |\n| 2 | Libellé des factures | test_label | fait |\n')
    binaries = base / 'bin'
    binaries.mkdir()
    for command in ['codex', 'claude']:
        shutil.copyfile(ROOT/'tests/fixtures'/('fake_claude.py' if command == 'claude' else 'fake_codex.py'), binaries/command)
        (binaries/command).chmod(0o755)
    os.environ['PATH'] = str(binaries) + os.pathsep + os.environ['PATH']
    app = App(base / 'state', 18796, 18795)
    # A synthetic adapter keeps browser QA independent from any private engine.
    workflow = base / 'fixture-workflow'
    (workflow/'scripts').mkdir(parents=True)
    for name in ('odoo-release.sh', 'odoo_plan.py', 'odoo_mail.py'):
        shutil.copyfile(ROOT/'tests/fixtures/fake_workflow.py', workflow/'scripts'/name)
        (workflow/'scripts'/name).chmod(0o755)
    settings = app.core.settings()
    settings.update(roots=[str(base / 'projects')], library=[], workflow_home=str(workflow))
    app.core.save_settings(settings)
    (ROOT / '.runtime').mkdir(exist_ok=True)
    atomic(ROOT / '.runtime/qa.json', json.dumps({'token': app.token, 'project': app.core.projects()[0]['id'], 'repo': str(repo), 'other_repo': str(other)}))
    def stop(*_args):
        app.stop.set()
        app.providers.shutdown()
        app.terminals.shutdown()
        raise SystemExit(0)
    signal.signal(signal.SIGTERM, stop)
    ThreadingHTTPServer(('127.0.0.1', 18796), handler(app)).serve_forever()
