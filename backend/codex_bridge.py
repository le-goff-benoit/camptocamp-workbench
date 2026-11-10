"""Native Codex app-server bridge (stdio), without any chat.

It serves three read-only uses: native Gmail/Calendar reads for the dashboard,
per-project email searches, and one-shot analysis turns (email triage)."""
import json
import os
import shutil
import signal
import subprocess
import threading

from .native_sources import read_sources
from .storage import Problem, require, safe

SOURCE_TOOLS = {'gmail.get_profile', 'gmail.search_emails', 'gmail.read_email', 'gmail.read_attachment', 'google_calendar.get_profile', 'google_calendar.search_events'}


class CodexBridge:
    def __init__(self, core, source_sink=None):
        self.core, self.source_sink = core, source_sink
        self.lock, self.start_lock, self.write_lock = threading.RLock(), threading.Lock(), threading.Lock()
        self.pending, self.waiters = {}, {}
        self.source_lock, self.source_thread, self.refresh_lock = threading.Lock(), None, threading.Lock()
        self.process, self.reader, self.sequence = None, None, 0

    # ---------------------------------------------------------------- process
    def _write(self, message):
        with self.write_lock:
            require(self.process is not None and self.process.poll() is None, 'Codex est arrêté. Réessayez.')
            self.process.stdin.write(json.dumps(message, ensure_ascii=False) + '\n')
            self.process.stdin.flush()

    def _rpc(self, method, params, timeout=45):
        with self.lock:
            self.sequence += 1
            rid, answer, event = self.sequence, {}, threading.Event()
            self.pending[rid] = (event, answer)
        try:
            self._write({'id': rid, 'method': method, 'params': params})
            require(event.wait(timeout), 'Codex ne répond pas. Vérifiez sa connexion puis réessayez.')
            require('error' not in answer, 'Codex a refusé la demande. Vérifiez sa connexion.')
            return answer.get('result', {})
        finally:
            with self.lock:
                self.pending.pop(rid, None)

    def _ensure(self):
        with self.start_lock:
            if self.process is not None and self.process.poll() is None:
                return
            require(shutil.which('codex'), 'Codex CLI est absent. Installez-le ou vérifiez le chemin de démarrage.')
            folder = safe(self.core.state, 'codex')
            folder.mkdir(parents=True, exist_ok=True)
            log = (folder / 'provider.log').open('a')
            # No Workbench tool is offered to the model: every use here is read-only.
            self.process = subprocess.Popen(
                ['codex', 'app-server', '-c', 'mcp_servers.camptocamp-workbench.enabled_tools=[]'],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=log, text=True, bufsize=1, start_new_session=True)
            log.close()
            self.source_thread = None
            self.reader = threading.Thread(target=self._reader, args=(self.process,), daemon=True)
            self.reader.start()
            self._rpc('initialize', {'clientInfo': {'name': 'camptocamp_workbench', 'title': 'Camptocamp Workbench', 'version': '0.4.0'}})
            self._write({'method': 'initialized', 'params': {}})

    def _reader(self, process):
        try:
            for line in process.stdout:
                try:
                    message = json.loads(line)
                    if 'method' in message:
                        if 'id' in message:
                            # Approval or elicitation requests are always refused.
                            self._write({'id': message['id'], 'error': {'code': -32601, 'message': 'Lecture seule : action non autorisée.'}})
                        else:
                            self._event(message['method'], message.get('params', {}))
                    else:
                        with self.lock:
                            pending = self.pending.get(message.get('id'))
                            if pending:
                                pending[1].update(message)
                                pending[0].set()
                except (ValueError, KeyError, TypeError, Problem):
                    continue
        finally:
            with self.lock:
                for event, answer in self.pending.values():
                    answer['error'] = 'Codex arrêté'
                    event.set()
                for waiter in self.waiters.values():
                    waiter['status'] = waiter['status'] or 'failed'
                    waiter['event'].set()

    def _event(self, method, params):
        thread = params.get('threadId')
        with self.lock:
            waiter = self.waiters.get(thread)
        if not waiter:
            return
        item = params.get('item', {})
        if method == 'turn/started':
            waiter['turn'] = params['turn']['id']
        elif method == 'item/started' and item.get('type') not in {None, 'agentMessage', 'reasoning', 'userMessage'}:
            waiter['status'] = 'tool'
            if waiter['turn']:
                threading.Thread(target=lambda: self._rpc('turn/interrupt', {'threadId': thread, 'turnId': waiter['turn']}, timeout=10), daemon=True).start()
        elif method == 'item/agentMessage/delta':
            key = params.get('itemId')
            waiter['blocks'][key] = waiter['blocks'].get(key, '') + params.get('delta', '')
        elif method == 'item/completed' and item.get('type') == 'agentMessage':
            waiter['blocks'][item['id']] = item.get('text', '')
        elif method == 'turn/completed':
            if waiter['status'] != 'tool':
                waiter['status'] = params['turn']['status']
            waiter['event'].set()

    # ---------------------------------------------------------------- uses
    def _source_thread(self):
        with self.source_lock:
            if self.source_thread is None:
                folder = safe(self.core.state, 'workspace')
                folder.mkdir(parents=True, exist_ok=True)
                self.source_thread = self._rpc('thread/start', {'cwd': str(folder), 'approvalPolicy': 'never', 'sandbox': 'read-only'})['thread']['id']
            return self.source_thread

    def native_call(self, tool, arguments):
        require(tool in SOURCE_TOOLS, 'Lecture native non autorisée')
        self._ensure()
        return self._rpc('mcpServer/tool/call', {'threadId': self._source_thread(), 'server': 'codex_apps', 'tool': tool, 'arguments': arguments}, timeout=60)

    def refresh_sources(self):
        """Read Gmail and Calendar natively, then store the validated snapshot.
        A failed read keeps the previous snapshot untouched."""
        require(self.source_sink is not None, 'Actualisation des sources indisponible.')
        require(self.refresh_lock.acquire(blocking=False), 'Une actualisation est déjà en cours.')
        try:
            try:
                payload = read_sources(self.native_call)
            except Problem as problem:
                raise Problem(f'{problem} Les aperçus précédents sont conservés.')
            return self.source_sink(emails=payload['emails'], events=payload['events'])
        finally:
            self.refresh_lock.release()

    def ask(self, text, instructions, timeout=240):
        """One read-only turn on a fresh thread; returns the final answer text.
        Any tool, command or file activity aborts the turn: this is pure analysis."""
        self._ensure()
        folder = safe(self.core.state, 'workspace')
        folder.mkdir(parents=True, exist_ok=True)
        params = {'cwd': str(folder), 'approvalPolicy': 'never', 'sandbox': 'read-only', 'developerInstructions': instructions}
        thread = self._rpc('thread/start', params)['thread']['id']
        waiter = {'event': threading.Event(), 'blocks': {}, 'status': None, 'turn': None}
        with self.lock:
            self.waiters[thread] = waiter
        try:
            result = self._rpc('turn/start', {'threadId': thread, 'input': [{'type': 'text', 'text': text}], 'cwd': str(folder),
                                              'approvalPolicy': 'never', 'sandboxPolicy': {'type': 'readOnly'}})
            waiter['turn'] = waiter['turn'] or result.get('turn', {}).get('id')
            if not waiter['event'].wait(timeout):
                if waiter['turn']:
                    try:
                        self._rpc('turn/interrupt', {'threadId': thread, 'turnId': waiter['turn']}, timeout=10)
                    except Problem:
                        pass
                raise Problem('L’analyse prend trop de temps. Réessayez dans un moment.')
            require(waiter['status'] != 'tool', 'Analyse arrêtée : Codex a tenté d’utiliser un outil.')
            require(waiter['status'] == 'completed', 'Codex n’a pas pu terminer l’analyse. Vérifiez sa connexion.')
            return '\n\n'.join(v for v in waiter['blocks'].values() if v)
        finally:
            with self.lock:
                self.waiters.pop(thread, None)

    def shutdown(self):
        if self.process is not None and self.process.poll() is None:
            os.killpg(self.process.pid, signal.SIGTERM)
            try:
                self.process.wait(timeout=4)
            except subprocess.TimeoutExpired:
                os.killpg(self.process.pid, signal.SIGKILL)
                self.process.wait(timeout=2)
        if self.process is not None:
            if self.reader and self.reader is not threading.current_thread():
                self.reader.join(timeout=3)
            self.process.stdin.close()
            self.process.stdout.close()
