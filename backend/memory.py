"""Small memory index, dated notes and explicit promotion of sourced facts."""
import json
import hashlib
from pathlib import Path
import re
import uuid

from .core import clean, now
from .storage import atomic, decode, encode, locked, read, require, safe, sha


class Memory:
    def __init__(self, core):
        self.core = core

    def source_digest(self, path):
        require(path.is_file() and path.stat().st_size <= 20_000_000, 'Source absente ou supérieure à 20 Mo')
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def notes(self, project):
        root = self.core.root(project)
        folder = safe(root, 'memory/notes')
        result = []
        if folder.exists():
            for path in sorted(folder.glob('*.md')):
                safe(folder, path.name)
                meta, body = decode(read(path))
                try:
                    source = safe(root, meta['source'])
                    meta['fresh'] = self.source_digest(source) == meta['source_hash']
                except (ValueError, OSError):
                    meta['fresh'] = False
                result.append({**meta, 'body': body, 'path': str(path.relative_to(root))})
        return result

    def propose(self, project, title, text, source, kind='fact'):
        require(kind in {'fact', 'decision', 'hypothese'}, 'Type de note invalide')
        root = self.core.root(project)
        source_path = safe(root, source)
        require(source_path.is_file(), 'Source locale requise pour la note')
        title, text = clean(title, 180), clean(text, 6000)
        require(title and text, 'Titre et contenu requis')
        nid = 'M-' + uuid.uuid4().hex[:12]
        meta = {'id': nid, 'title': title, 'kind': kind, 'status': 'proposee', 'created': now(),
                'source': source, 'source_hash': self.source_digest(source_path)}
        with locked(self.core.state / 'locks' / project):
            atomic(safe(root, 'memory/notes/' + nid + '.md'), encode(meta, text))
        return meta

    def confirm(self, project, note_id, *, human=False):
        require(human, 'La promotion d’une note nécessite une décision humaine')
        require(re.fullmatch(r'M-[a-f0-9]{12}', note_id), 'Note inconnue')
        root = self.core.root(project)
        with locked(self.core.state / 'locks' / project):
            path = safe(root, 'memory/notes/' + note_id + '.md')
            meta, body = decode(read(path))
            require(meta['status'] == 'proposee', 'Note déjà confirmée')
            require(meta['kind'] != 'hypothese', 'Une hypothèse reste une hypothèse ; créer une note factuelle avec une preuve')
            source = safe(root, meta['source'])
            require(self.source_digest(source) == meta['source_hash'], 'La source a changé ; réexaminer la note')
            meta.update(status='confirmee', confirmed=now())
            atomic(path, encode(meta, body))
            index = safe(root, 'MEMORY.md')
            text = read(index) if index.exists() else '# Mémoire du projet\n'
            atomic(index, text.rstrip() + f'\n\n- [{meta["title"]}](memory/notes/{note_id}.md) — confirmé le {now()[:10]}.\n')
        return meta

    def context(self, project, query='', release=None):
        root = self.core.root(project)
        path = safe(root, 'MEMORY.md')
        text = read(path) if path.exists() else ''
        index = '\n'.join(text.splitlines()[:120])[:8000]
        words = {w.casefold() for w in re.findall(r'\w{3,}', clean(query, 300))}
        notes = self.notes(project)
        selected = sorted(notes, key=lambda n: sum(w in (n['title'] + ' ' + n['body']).casefold() for w in words), reverse=True)
        if words:
            selected = [n for n in selected if any(w in (n['title'] + ' ' + n['body']).casefold() for w in words)]
        references = []
        if release:
            folder = self.core.release_folder(project, release)
            references = [str(safe(folder, name).relative_to(root)) for name in ['plan.md', 'decisions.md', 'journal.md'] if safe(folder, name).exists()]
        return {'index': index, 'index_truncated': len(index) < len(text),
                'notes': [{k: n[k] for k in ['id', 'title', 'status', 'kind', 'source', 'fresh', 'path']} for n in selected[:12]],
                'release_references': references, 'rule': 'Consulter les notes et sources utiles à la demande ; une note périmée ou proposée ne vaut pas fait acquis.'}
