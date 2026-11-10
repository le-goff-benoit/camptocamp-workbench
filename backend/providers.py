"""Select the native CLI used for source reads and analysis, independently."""
import shutil
from datetime import datetime, timezone
import json
import threading

from .claude_bridge import ClaudeBridge
from .codex_bridge import CodexBridge
from .native_sources import read_emails
from .core import now
from .dashboard import instant
from .storage import Problem, atomic, read, require, safe

LABELS = {'codex': 'Codex', 'claude': 'Claude Code'}


class Providers:
    def __init__(self, core, sink):
        self.core = core
        self.codex, self.claude = CodexBridge(core, sink), ClaudeBridge(core, sink)
        self.refresh_lock = threading.Lock()
        self.sync_path = safe(core.state, 'source-sync.json')

    def selected(self, purpose):
        value = self.core.settings().get('providers', {}).get(purpose, 'codex')
        require(value in LABELS, 'Choisissez Codex ou Claude Code dans Paramètres.')
        return value

    def label(self, purpose):
        return LABELS[self.selected(purpose)]

    def status(self):
        return {'selected': {key: self.selected(key) for key in ('sources', 'analysis')},
                'codex': {'installed': bool(shutil.which('codex'))}, 'claude': self.claude.status(), 'sync': self.sync_status()}

    def sync_status(self):
        saved = json.loads(read(self.sync_path)) if self.sync_path.exists() else {}
        return {**saved, 'enabled': bool(self.core.settings().get('source_sync', {}).get('enabled')),
                'interval_seconds': 300, 'running': self.refresh_lock.locked()}

    def refresh_sources(self):
        require(self.refresh_lock.acquire(blocking=False), 'Une actualisation est déjà en cours. Patientez quelques instants.')
        saved = self.sync_status()
        provider = self.selected('sources')
        saved.update(last_attempt=now(), provider=provider)
        atomic(self.sync_path, json.dumps(saved))
        try:
            result = getattr(self, provider).refresh_sources()
            saved.update(last_success=now(), error=None)
            return result
        except Exception as error:
            saved['error'] = str(error)[:400]
            raise
        finally:
            atomic(self.sync_path, json.dumps(saved))
            self.refresh_lock.release()

    def sync_due(self, timestamp=None):
        status = self.sync_status()
        if not status['enabled'] or status['running']:
            return False
        stamp = timestamp if timestamp is not None else datetime.now(timezone.utc).timestamp()
        if stamp-instant(status.get('last_attempt')) < 300:
            return False
        self.refresh_sources()
        return True

    def background(self, stop):
        while not stop.wait(10):
            try:
                self.sync_due()
            except Exception:
                pass  # The error and last successful snapshot remain visible.

    def native_call(self, tool, arguments):
        return getattr(self, self.selected('sources')).native_call(tool, arguments)

    def read_emails(self, query, accept):
        if self.selected('sources') == 'claude':
            return self.claude.read_emails(query, accept)
        return read_emails(self.codex.native_call, query, accept=accept)

    def ask(self, text, instructions, timeout=240):
        return getattr(self, self.selected('analysis')).ask(text, instructions, timeout)

    def shutdown(self):
        self.codex.shutdown()
        self.claude.shutdown()
