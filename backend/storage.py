"""Small, inspectable Markdown records with atomic writes and conflict checks."""
import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import tempfile


class Problem(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise Problem(message)


def sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


def safe(root, relative):
    root = Path(root).resolve()
    rel = Path(relative)
    require(not rel.is_absolute() and '..' not in rel.parts, 'Chemin hors du dossier autorisé')
    target = root / rel
    cursor = root
    for part in rel.parts:
        cursor = cursor / part
        require(not cursor.is_symlink(), 'Lien symbolique refusé pour ce document')
    require(target.resolve().is_relative_to(root), 'Chemin hors du dossier autorisé')
    return target


def read(path, limit=2_000_000):
    path = Path(path)
    require(path.is_file() and path.stat().st_size <= limit, 'Document absent ou trop volumineux')
    return path.read_text(encoding='utf-8')


def atomic(path, text, expected=None):
    path = Path(path)
    require(not path.is_symlink(), 'Lien symbolique refusé')
    path.parent.mkdir(parents=True, exist_ok=True)
    if expected is not None:
        require(path.exists() and sha(read(path)) == expected,
                'Le document a changé. Rechargez avant de sauvegarder.')
    fd, temporary = tempfile.mkstemp(prefix='.workbench-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as output:
            output.write(text)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def encode(meta, body):
    return '---\n' + ''.join(f'{key}: {json.dumps(value, ensure_ascii=False)}\n' for key, value in meta.items()) + '---\n\n' + body.strip() + '\n'


def decode(text):
    require(text.startswith('---\n') and '\n---\n' in text[4:], 'Métadonnées Markdown absentes')
    header, body = text[4:].split('\n---\n', 1)
    meta = {}
    for line in header.splitlines():
        key, value = line.split(':', 1)
        meta[key] = json.loads(value)
    return meta, body.strip()


@contextlib.contextmanager
def locked(directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / '.lock').open('a') as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)
