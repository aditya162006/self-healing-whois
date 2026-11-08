"""Opt-in, bounded expiration fallback with in-memory background repairs."""
from __future__ import annotations

import hashlib
from collections import OrderedDict
from dataclasses import dataclass, field
import json
import queue
import re
import threading
from datetime import datetime
from pathlib import Path

MAX_TEXT = 32768
_client = None


def scope(entry):
    return type(entry).__name__ + ':' + entry.domain.rstrip('.').lower().rsplit('.', 1)[-1]


def pattern_for(label):
    """Only literal, expiration-related field labels can enter live parsing."""
    if not isinstance(label, str) or not re.fullmatch(r'[A-Za-z][A-Za-z -]{2,79}', label):
        raise ValueError('invalid label')
    if not re.search(r'expir|valid until|paid till|renewal', label, re.I):
        raise ValueError('label does not describe expiration')
    return r'^[ \t]*' + re.escape(label) + r'[ \t]*[:=][ \t]*([^\r\n]{1,128})$'


def compile_rule(rule):
    expected = pattern_for(rule['label'])
    if rule['pattern'] != expected:
        raise ValueError('pattern is outside the bounded grammar')
    return re.compile(expected, re.I | re.M)


def extract(compiled, text):
    from .parser import datetime_parse
    values = []
    for match in compiled.finditer(text):
        value = datetime_parse(match.group(1).strip())
        if not isinstance(value, datetime):
            raise ValueError('unrecognized or incomplete date')
        if value not in values:
            values.append(value)
    return values[0] if len(values) == 1 else (values or None)


def normalized(value):
    if isinstance(value, list):
        return sorted(str(v) for v in value)
    return [] if value is None else [str(value)]


def load_corpus(path=None):
    source = Path(path) if path else Path(__file__).with_name('healing_corpus.json')
    corpus = json.loads(source.read_text(encoding='utf-8'))
    if not isinstance(corpus, list) or not corpus:
        raise ValueError('corpus must be a nonempty list')
    for case in corpus:
        if not isinstance(case, dict) or not isinstance(case.get('scope'), str) or not isinstance(case.get('text'), str) or not isinstance(case.get('expected'), list):
            raise ValueError('each corpus case needs scope, text and expected fields')
    return corpus


@dataclass
class _Job:
    scope: str
    text: str
    status: str = 'pending'
    error: str | None = None
    attempts: int = 0
    done: threading.Event = field(default_factory=threading.Event)


class HealingClient:
    """One bounded, process-local queue and worker. No runtime files are written."""
    def __init__(self, *, provider, corpus=None, queue_size=256,
                 wait_for_repair=True, repair_timeout=150, max_scopes=128):
        if not isinstance(queue_size, int) or queue_size <= 0:
            raise ValueError('queue_size must be a positive integer')
        if repair_timeout <= 0 or not isinstance(max_scopes, int) or max_scopes <= 0:
            raise ValueError('repair_timeout and max_scopes must be positive')
        self.wait_for_repair = wait_for_repair
        self.repair_timeout = repair_timeout
        self.max_scopes = max_scopes
        self.queue = queue.Queue(queue_size)
        self._jobs = OrderedDict()
        self._job_limit = 2 * queue_size + 1
        self._rules = {}
        self._compiled = {}
        self._history = {}
        self._lock = threading.RLock()
        self.stop = threading.Event()
        self.dropped = 0
        cases = load_corpus() if corpus is None else corpus
        self.worker_thread = threading.Thread(target=self._run, args=(provider, cases),
                                              name='whois-healing-repair', daemon=True)
        self.worker_thread.start()

    def _apply_rule(self, entry):
        with self._lock:
            rules = self._compiled.get(scope(entry), ())
        for compiled in rules:
            try:
                value = extract(compiled, entry.text)
            except ValueError:
                continue
            if value:
                entry['expiration_date'] = value
                return True
        return False

    def _submit(self, entry):
        digest = hashlib.sha256((scope(entry) + '\0' + entry.text).encode()).hexdigest()
        with self._lock:
            if self.stop.is_set():
                return None
            if digest in self._jobs:
                return self._jobs[digest]
            while len(self._jobs) >= self._job_limit:
                terminal = next((key for key, job in self._jobs.items() if job.done.is_set()), None)
                if terminal is None:
                    self.dropped += 1
                    return None
                del self._jobs[terminal]
            job = _Job(scope(entry), entry.text)
            try:
                self.queue.put_nowait(job)
            except queue.Full:
                self.dropped += 1
                return None
            self._jobs[digest] = job
            return job

    def observe(self, entry):
        if self.stop.is_set() or entry.get('expiration_date') or not entry.text or len(entry.text) > MAX_TEXT:
            return
        if not self._apply_rule(entry):
            self._submit(entry)

    def job_status(self, entry):
        """Return a status snapshot, without raw text, secrets, or disk access."""
        digest = hashlib.sha256((scope(entry) + '\0' + entry.text).encode()).hexdigest()
        with self._lock:
            job = self._jobs.get(digest)
            return None if job is None else {'status': job.status, 'attempts': job.attempts, 'error': job.error}

    def finish_lookup(self, entry):
        from .exceptions import WhoisHealingError
        if not self.wait_for_repair or entry.get('expiration_date'):
            return
        if not entry.text or len(entry.text) > MAX_TEXT:
            raise WhoisHealingError('Response is empty or exceeds the repair size limit.')
        if self._apply_rule(entry):
            return
        job = self._submit(entry)
        if job is None:
            raise WhoisHealingError('Healing is stopped or its memory queue is full.')
        if not job.done.wait(self.repair_timeout):
            raise WhoisHealingError('Timed out waiting for a validated expiration repair.')
        if not self.stop.is_set() and self._apply_rule(entry):
            return
        raise WhoisHealingError('Expiration repair was rejected, failed, or cancelled; no date was invented.')

    def _run(self, provider, corpus):
        from .healing_worker import validate
        while not self.stop.is_set():
            try:
                job = self.queue.get(timeout=.1)
            except queue.Empty:
                continue
            try:
                with self._lock:
                    if self.stop.is_set():
                        continue
                    job.status = 'working'
                    job.attempts = 1
                    previous = list(self._rules.get(job.scope, ()))
                    history = list(self._history.get(job.scope, ()))
                try:
                    proposal = provider.propose(job.text)
                except Exception as exc:
                    with self._lock:
                        if not self.stop.is_set():
                            job.status, job.error = 'failed', type(exc).__name__
                    continue
                if self.stop.is_set():
                    continue
                try:
                    rule = validate(proposal, job.text, job.scope, list(corpus) + history, previous)
                    if rule not in previous:
                        if len(previous) >= 8:
                            raise ValueError('rule limit reached')
                        previous.append(rule)
                    if len(history) >= 32:
                        raise ValueError('historical example limit reached')
                    case = {'scope': job.scope, 'text': job.text,
                            'expected': normalized(extract(compile_rule(rule), job.text))}
                    compiled = tuple(compile_rule(r) for r in previous)
                    with self._lock:
                        if self.stop.is_set():
                            continue
                        if job.scope not in self._rules and len(self._rules) >= self.max_scopes:
                            raise ValueError('scope limit reached')
                        self._rules[job.scope] = previous
                        self._compiled[job.scope] = compiled
                        self._history[job.scope] = history + [case]
                        job.status = 'accepted'
                except (ValueError, KeyError, TypeError):
                    with self._lock:
                        if not self.stop.is_set():
                            job.status, job.error = 'rejected', 'validation_failed'
            finally:
                with self._lock:
                    job.text = ''  # only accepted bounded history retains examples
                    job.done.set()
                self.queue.task_done()

    def close(self):
        """Clear runtime state. An outstanding HTTP request cannot be cancelled."""
        self.stop.set()
        with self._lock:
            for job in self._jobs.values():
                job.status = 'cancelled'
                job.text = ''
                job.done.set()
            self._jobs.clear()
            self._rules.clear()
            self._compiled.clear()
            self._history.clear()
            while True:
                try:
                    self.queue.get_nowait()
                    self.queue.task_done()
                except queue.Empty:
                    break
        self.worker_thread.join(timeout=1)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def enable_healing(*, api_key, model, endpoint, queue_size=256, timeout=120,
                   corpus_path=None, wait_for_repair=True, repair_timeout=150,
                   max_scopes=128):
    """Start process-wide in-memory repair. Key, model and endpoint are required.

    No runtime state is saved to disk. Rules reset on disable or process exit.
    By default self_healing_whois.whois returns a repaired expiration or raises WhoisHealingError.
    Each distinct retained failure gets one model attempt per client lifetime.
    """
    from .healing_worker import Provider
    for name, value in [('api_key', api_key), ('model', model), ('endpoint', endpoint)]:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(name + ' must be a nonempty string')
    provider = Provider(endpoint.strip(), model.strip(), api_key.strip(), timeout=timeout)
    return enable(provider=provider, corpus=load_corpus(corpus_path), queue_size=queue_size,
                  wait_for_repair=wait_for_repair, repair_timeout=repair_timeout,
                  max_scopes=max_scopes)


def enable(*, provider, **kwargs):
    """Start an in-memory client with a custom provider (used by demos/tests)."""
    global _client
    disable()
    _client = HealingClient(provider=provider, **kwargs)
    return _client


def disable():
    global _client
    previous, _client = _client, None
    if previous:
        previous.close()


def observe(entry):
    client = _client
    if client is not None:
        client.observe(entry)


def finish_lookup(entry):
    client = _client
    if client is not None:
        client.finish_lookup(entry)
