import threading
import time

import pytest

import self_healing_whois as whois
from self_healing_whois import healing
from self_healing_whois.healing_worker import Provider
from self_healing_whois.parser import WhoisEntry

TEXT = 'Domain Name: EXAMPLE.COM\nDomain valid until: 2031-04-05\n'


def wait_for(check):
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        if check():
            return
        time.sleep(.02)
    raise AssertionError('background operation timed out')


@pytest.fixture(autouse=True)
def cleanup():
    yield
    whois.disable_healing()


def test_import_configure_and_repair_without_scripts(tmp_path, monkeypatch):
    started, release = threading.Event(), threading.Event()
    def propose(self, text):
        assert self.api_key == 'unit-test-secret'
        assert self.model == 'test-model'
        assert threading.current_thread().name == 'whois-healing-repair'
        started.set()
        assert release.wait(5)
        return {'label': 'Domain valid until', 'pattern': healing.pattern_for('Domain valid until'),
                'evidence': '2031-04-05'}
    monkeypatch.setattr(Provider, 'propose', propose)
    client = whois.enable_healing(endpoint='https://model.example/v1/chat/completions', api_key='unit-test-secret', model='test-model')
    try:
        assert WhoisEntry.load('example.com', TEXT).expiration_date is None
        assert started.wait(5)
        # The provider is blocked, but lookups still return immediately.
        assert WhoisEntry.load('example.com', TEXT).expiration_date is None
        release.set()
        wait_for(lambda: client.job_status(WhoisEntry.load('example.com', TEXT))['status'] == 'accepted')
        assert WhoisEntry.load('example.com', TEXT).expiration_date.year == 2031
        assert 'unit-test-secret' not in str(client.job_status(WhoisEntry.load('example.com', TEXT)))
    finally:
        release.set()
        whois.disable_healing()
    assert not client.worker_thread.is_alive()
    assert WhoisEntry.load('example.com', TEXT).expiration_date is None


def test_context_manager_stops_threads(tmp_path):
    with whois.enable_healing(endpoint='https://model.example/v1/chat/completions', api_key='test', model='test') as client:
        assert client.worker_thread.is_alive()
    assert client.stop.is_set()
    assert not client.worker_thread.is_alive()
    assert WhoisEntry.load('example.com', TEXT).expiration_date is None


@pytest.mark.parametrize('kwargs', [{'api_key': '', 'model': 'test'}, {'api_key': 'test', 'model': ''}])
def test_bad_configuration_fails_at_startup(kwargs):
    with pytest.raises(ValueError):
        whois.enable_healing(endpoint='https://model.example/v1/chat/completions', **kwargs)
    assert healing._client is None


def test_public_lookup_returns_repaired_result(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(whois.NICClient, 'whois_lookup', lambda *a, **k: TEXT)
    monkeypatch.setattr(Provider, 'propose', lambda self, text: {
        'label': 'Domain valid until', 'pattern': healing.pattern_for('Domain valid until'),
        'evidence': '2031-04-05'})
    whois.enable_healing(endpoint='https://model.example/v1/chat/completions', api_key='test', model='test')
    result = whois.whois('example.com')
    assert result.expiration_date.year == 2031
    assert capsys.readouterr().out == ''
    assert 'Before repair' not in str(result)


def test_public_lookup_rejected_repair_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(whois.NICClient, 'whois_lookup', lambda *a, **k: TEXT)
    monkeypatch.setattr(Provider, 'propose', lambda self, text: {'abstain': True})
    whois.enable_healing(endpoint='https://model.example/v1/chat/completions', api_key='test', model='test')
    with pytest.raises(whois.WhoisHealingError, match='rejected'):
        whois.whois('example.com')


def test_public_lookup_timeout_and_async_option(tmp_path, monkeypatch):
    monkeypatch.setattr(whois.NICClient, 'whois_lookup', lambda *a, **k: TEXT)
    monkeypatch.setattr(healing.HealingClient, '_run', lambda self, *args: self.stop.wait())
    whois.enable_healing(endpoint='https://model.example/v1/chat/completions', api_key='test', model='test',
                         repair_timeout=.15)
    with pytest.raises(whois.WhoisHealingError, match='Timed out'):
        whois.whois('example.com')
    whois.enable_healing(endpoint='https://model.example/v1/chat/completions', api_key='test', model='test',
                         wait_for_repair=False)
    assert whois.whois('example.com').expiration_date is None


def test_successful_lookup_does_not_call_model(tmp_path, monkeypatch):
    monkeypatch.setattr(whois.NICClient, 'whois_lookup', lambda *a, **k: TEXT.replace('Domain valid until', 'Expiry Date'))
    def unexpected(self, text):
        raise AssertionError('Model should not be called for a native success')
    monkeypatch.setattr(Provider, 'propose', unexpected)
    client = whois.enable_healing(endpoint='https://model.example/v1/chat/completions', api_key='test', model='test')
    assert whois.whois('example.com').expiration_date.year == 2031
    assert client.queue.empty()


def test_endpoint_is_required():
    with pytest.raises(TypeError, match='endpoint'):
        whois.enable_healing(api_key='test', model='test')


@pytest.mark.parametrize('endpoint', ['', None])
def test_invalid_endpoint_is_rejected(endpoint):
    with pytest.raises(ValueError, match='endpoint'):
        whois.enable_healing(api_key='test', model='test', endpoint=endpoint)
