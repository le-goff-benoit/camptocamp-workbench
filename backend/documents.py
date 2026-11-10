"""Read-only PDF/Word text extraction to a private, rebuildable local index."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import threading
import xml.etree.ElementTree as ET
import zipfile

from .core import SKIP, clean, now
from .storage import require, safe


class Documents:
    def __init__(self, core):
        self.core, self.lock = core, threading.Lock()
        self.path = core.state / 'documents.sqlite3'
        with sqlite3.connect(self.path) as db:
            db.execute('CREATE VIRTUAL TABLE IF NOT EXISTS documents USING fts5(entry UNINDEXED, path UNINDEXED, fingerprint UNINDEXED, indexed UNINDEXED, text)')

    def extract(self, path):
        require(path.stat().st_size <= 20_000_000, 'Document supérieur à 20 Mo')
        if path.suffix.casefold() == '.pdf':
            require(shutil.which('pdftotext'), 'pdftotext absent')
            result = subprocess.run(['pdftotext', '-layout', '-f', '1', '-l', '100', str(path), '-'], capture_output=True, timeout=15)
            require(result.returncode == 0, 'PDF non extractible (chiffré ou numérisé sans texte)')
            return result.stdout[:2_000_000].decode('utf-8', 'replace')
        if path.suffix.casefold() == '.docx':
            with zipfile.ZipFile(path) as archive:
                entry = archive.getinfo('word/document.xml')
                require(entry.file_size <= 5_000_000, 'Contenu Word trop volumineux')
                document = ET.fromstring(archive.read(entry))
                ns = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
                return '\n'.join(''.join(node.itertext()) for node in document.iter(ns + 'p'))[:2_000_000]
        raise ValueError('Format non pris en charge')

    def index(self, entry_id):
        require(self.lock.acquire(blocking=False), 'Une indexation est déjà en cours')
        try:
            entry = next((e for e in self.core.settings()['library'] if e['id'] == entry_id), None)
            require(entry, 'Source documentaire inconnue')
            root, count, errors, scanned = Path(entry['path']).resolve(), 0, [], 0
            with sqlite3.connect(self.path) as db:
                db.execute('DELETE FROM documents WHERE entry=?', (entry_id,))
                for directory, folders, files in os.walk(root, followlinks=False):
                    folders[:] = [n for n in folders if not n.startswith('.') and n not in SKIP and not (Path(directory) / n).is_symlink()]
                    for name in files:
                        path = Path(directory) / name
                        if path.suffix.casefold() not in {'.pdf', '.docx'} or path.is_symlink():
                            continue
                        scanned += 1
                        if scanned > 1000:
                            break
                        try:
                            safe(root, str(path.relative_to(root)))
                            text = self.extract(path)
                            stat = path.stat()
                            db.execute('INSERT INTO documents VALUES (?,?,?,?,?)', (entry_id, str(path), f'{stat.st_size}:{stat.st_mtime_ns}', now(), text))
                            count += 1
                        except Exception as error:
                            errors.append({'path': str(path), 'error': str(error)[:200]})
                    if scanned > 1000:
                        break
            return {'indexed': count, 'errors': errors[:25], 'truncated': scanned > 1000,
                    'coverage': 'Texte PDF (100 premières pages) et Word ; pas d’OCR ni de tableaux structurés.'}
        finally:
            self.lock.release()

    def search(self, query):
        words = re.findall(r'\w+', clean(query, 200))
        if not words:
            return []
        expression = ' AND '.join('"' + word + '"' for word in words)
        allowed = {e['id']: Path(e['path']).resolve() for e in self.core.settings()['library']}
        result = []
        with sqlite3.connect(self.path) as db:
            for entry, path, fingerprint, indexed, snippet in db.execute('SELECT entry,path,fingerprint,indexed,snippet(documents,4,\'\',\'\',\'…\',32) FROM documents WHERE documents MATCH ? LIMIT 50', (expression,)):
                if entry not in allowed:
                    continue
                try:
                    source = safe(allowed[entry], str(Path(path).relative_to(allowed[entry])))
                    stat = source.stat()
                    if fingerprint != f'{stat.st_size}:{stat.st_mtime_ns}':
                        continue
                    result.append({'entry': entry, 'path': path, 'indexed': indexed, 'text': snippet})
                except (ValueError, OSError):
                    continue
        return result
