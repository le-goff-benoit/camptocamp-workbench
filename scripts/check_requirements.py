"""Read-only dependency check. Never reads accounts, tokens or provider settings."""
import json
import platform
import shutil
import sqlite3
import subprocess
import sys

VERSIONS = {'openclaw': '2026.5.18', 'codex': '0.167.0', 'claude': '2.1.322'}


def check():
    checks = []
    def add(name, ok, detail, required=True):
        checks.append({'name': name, 'ok': bool(ok), 'detail': detail, 'required': required})
    add('Linux', sys.platform.startswith('linux'), platform.system() + ' ; installation de bureau Linux / WSL2 avec bureau')
    add('Python', sys.version_info >= (3, 10), platform.python_version())
    try:
        with sqlite3.connect(':memory:') as db:
            db.execute('CREATE VIRTUAL TABLE check_fts USING fts5(text)')
        add('SQLite FTS5', True, sqlite3.sqlite_version)
    except sqlite3.Error:
        add('SQLite FTS5', False, 'Utiliser le paquet Python de la distribution avec SQLite FTS5')
    for name in ('git', 'bash', 'xdg-open', 'pdftotext'):
        add(name, shutil.which(name), 'présent' if shutil.which(name) else 'absent')
    node = shutil.which('node')
    try:
        version = subprocess.run([node, '--version'], capture_output=True, text=True, timeout=10).stdout.strip() if node else ''
        parts = tuple(int(n) for n in version.lstrip('v').split('.')[:3])
        add('Node.js', parts >= (22, 19, 0), version or 'absent ; minimum 22.19.0 pour OpenClaw 2026.5.18')
    except (ValueError, OSError, subprocess.TimeoutExpired):
        add('Node.js', False, 'absent ou version illisible')
    for name, tested in VERSIONS.items():
        binary = shutil.which(name)
        version = ''
        if binary:
            try:
                version = subprocess.run([binary, '--version'], capture_output=True, text=True, timeout=15).stdout.strip().splitlines()[0]
            except (OSError, subprocess.TimeoutExpired, IndexError):
                pass
        add(name, bool(binary), (version or 'absent') + ' ; version de référence ' + tested, required=name == 'openclaw')
    add('systemd utilisateur', bool(shutil.which('systemctl')), 'facultatif ; repli en processus local prévu', required=False)
    return checks


if __name__ == '__main__':
    checks = check()
    if '--json' in sys.argv:
        print(json.dumps(checks, ensure_ascii=False, indent=2))
    else:
        for row in checks:
            flag = 'OK' if row['ok'] else 'MANQUANT' if row['required'] else 'OPTIONNEL'
            print(f"{flag:10} {row['name']} : {row['detail']}")
        print('Aucun profil d’agent, moteur de workflow externe ou compte Google partagé n’est requis.')
        print('Un fournisseur connecté est nécessaire pour Gmail/Calendar et les analyses, pas pour le suivi manuel.')
    raise SystemExit(1 if any(c['required'] and not c['ok'] for c in checks) else 0)
