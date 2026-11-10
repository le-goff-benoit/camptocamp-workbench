#!/usr/bin/env python3
"""Synthetic historical mail adapter for browser tests only. Not a workflow engine."""
from email import policy
from email.parser import BytesParser
from pathlib import Path
import sys

if Path(sys.argv[0]).name != 'odoo_mail.py':
    raise SystemExit('Fixture : commande non attendue')
folder = Path(sys.argv[sys.argv.index('--release')+1])
message = BytesParser(policy=policy.default).parsebytes(Path(sys.argv[1]).read_bytes())
body = message.get_body(preferencelist=('plain',))
with (folder/'demande.md').open('a', encoding='utf-8') as stream:
    stream.write('\n## Mail — ' + str(message['Subject']) + '\n\n' + (body.get_content() if body else '') + '\n')
