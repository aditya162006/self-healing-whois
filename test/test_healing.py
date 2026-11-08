import io
import json
import threading
import time
from datetime import datetime, timezone

import pytest

from self_healing_whois import healing, WhoisHealingError
from self_healing_whois.healing_worker import Provider, validate
from self_healing_whois.parser import WhoisEntry

TEXT = 'Domain Name: EXAMPLE.COM\nRegistration valid until: 2030-01-02\n'
PROPOSAL = {'label': 'Registration valid until',
            'pattern': healing.pattern_for('Registration valid until'),
            'evidence': '2030-01-02'}
KEY = healing.scope(WhoisEntry.load('example.com', TEXT))
CORPUS = [{'scope': KEY, 'text': 'Expiry Date: 2028-01-01',
           'expected': ['2028-01-01 00:00:00+00:00']},
          {'scope': KEY, 'text': 'Creation Date: 2020-01-01', 'expected': []}]


class FakeProvider:
    def propose(self, text):
        return PROPOSAL


@pytest.fixture(autouse=True)
def cleanup():
    yield
    healing.disable()


def test_end_to_end_and_no_runtime_files(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    entry = WhoisEntry.load('example.com', TEXT)
    assert entry.expiration_date is None
    client = healing.enable(provider=FakeProvider(), corpus=CORPUS)
    client.finish_lookup(entry)
    assert entry.expiration_date == datetime(2030, 1, 2, tzinfo=timezone.utc)
    assert client.job_status(entry)['status'] == 'accepted'
    assert WhoisEntry.load('example.com', TEXT + 'Expiry Date: 2031-01-01').expiration_date.year == 2031
    assert WhoisEntry.load('example.net', TEXT).expiration_date is None
    healing.disable()
    assert list(tmp_path.iterdir()) == []
    assert not client._rules and not client._history and not client._jobs
    assert WhoisEntry.load('example.com', TEXT).expiration_date is None


@pytest.mark.parametrize('pattern', ['(a+)+$', '.*(.*)', '__import__("os")'])
def test_reject_arbitrary_regex(pattern):
    with pytest.raises(ValueError):
        validate(dict(PROPOSAL, pattern=pattern), TEXT, KEY, CORPUS)


def test_regression_and_missing_history():
    with pytest.raises(ValueError, match='historical regression'):
        validate(PROPOSAL, TEXT, KEY, CORPUS + [{'scope': KEY, 'text': TEXT, 'expected': []}])
    with pytest.raises(ValueError, match='no historical'):
        validate(PROPOSAL, TEXT, KEY, [])


@pytest.mark.parametrize('proposal', [dict(PROPOSAL, evidence='2031-01-01'), {'abstain': True}, {}, None])
def test_invalid_model_output(proposal):
    with pytest.raises((ValueError, KeyError)):
        validate(proposal, TEXT, KEY, CORPUS)


def test_failure_is_deduplicated_and_redacted():
    class Offline:
        calls = 0
        def propose(self, text):
            self.calls += 1
            raise TimeoutError('private-key-must-not-enter-status')
    provider = Offline()
    client = healing.enable(provider=provider, corpus=CORPUS)
    entry = WhoisEntry.load('example.com', TEXT)
    for _ in range(2):
        with pytest.raises(WhoisHealingError):
            client.finish_lookup(entry)
    assert provider.calls == 1
    assert client.job_status(entry) == {'status': 'failed', 'attempts': 1, 'error': 'TimeoutError'}
    assert not client._rules


def test_queue_full_does_not_wait(monkeypatch):
    monkeypatch.setattr(healing.HealingClient, '_run', lambda self, *args: self.stop.wait())
    client = healing.enable(provider=FakeProvider(), corpus=CORPUS, queue_size=1)
    WhoisEntry.load('example.com', TEXT)
    entry = WhoisEntry.load('example.com', TEXT.replace('2030', '2031'))
    assert client.dropped == 1
    with pytest.raises(WhoisHealingError, match='full'):
        client.finish_lookup(entry)


def test_rejected_rule_is_not_published():
    client = healing.enable(provider=FakeProvider(), corpus=[])
    entry = WhoisEntry.load('example.com', TEXT)
    with pytest.raises(WhoisHealingError):
        client.finish_lookup(entry)
    assert client.job_status(entry)['status'] == 'rejected'
    assert not client._rules


def test_bundled_history():
    corpus = healing.load_corpus()
    assert len(corpus) == 65
    validate(PROPOSAL, TEXT, KEY, corpus)


def test_provider_contract(monkeypatch):
    def respond(request, timeout):
        body = json.loads(request.data)
        assert timeout == 120
        assert body['messages'][1]['content'] == TEXT
        assert request.get_header('Authorization') == 'Bearer test-key'
        return io.BytesIO(json.dumps({'choices': [{'message': {'content': json.dumps(PROPOSAL)}}]}).encode())
    monkeypatch.setattr('urllib.request.urlopen', respond)
    assert Provider('https://model.example/v1/chat/completions', 'test', 'test-key').propose(TEXT) == PROPOSAL


def test_duplicate_waiters_share_one_request():
    calls = []
    class Slow:
        def propose(self, text):
            calls.append(text)
            time.sleep(.1)
            return PROPOSAL
    client = healing.enable(provider=Slow(), corpus=CORPUS)
    entries = [WhoisEntry.load('example.com', TEXT) for _ in range(4)]
    threads = [threading.Thread(target=client.finish_lookup, args=(entry,)) for entry in entries]
    for thread in threads: thread.start()
    for thread in threads:
        thread.join(5)
        assert not thread.is_alive()
    assert len(calls) == 1
    assert all(entry.expiration_date.year == 2030 for entry in entries)


def test_stop_wakes_waiter_and_prevents_late_publication():
    started, release = threading.Event(), threading.Event()
    class Slow:
        def propose(self, text):
            started.set()
            release.wait(5)
            return PROPOSAL
    client = healing.enable(provider=Slow(), corpus=CORPUS)
    entry = WhoisEntry.load('example.com', TEXT)
    assert started.wait(3)
    errors = []
    def wait():
        try:
            client.finish_lookup(entry)
        except WhoisHealingError:
            errors.append(True)
    waiter = threading.Thread(target=wait)
    waiter.start()
    client.close()
    release.set()
    waiter.join(3)
    client.worker_thread.join(3)
    assert errors == [True]
    assert not client._rules and not client._history and not client._jobs


def test_completed_job_cache_is_bounded():
    class Decline:
        def propose(self, text): return {'abstain': True}
    client = healing.enable(provider=Decline(), corpus=CORPUS, queue_size=1)
    for i in range(8):
        entry = WhoisEntry.load('example.com', TEXT + f'Comment: {i}\n')
        with pytest.raises(WhoisHealingError): client.finish_lookup(entry)
    assert len(client._jobs) <= client._job_limit
    assert all(job.text == '' for job in client._jobs.values())
