import importlib.util
from pathlib import Path

from self_healing_whois.healing import pattern_for

spec = importlib.util.spec_from_file_location('verify_ai_repair', Path(__file__).parents[1] / 'scripts' / 'verify_ai_repair.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_verification_flow():
    class Fake:
        def propose(self, text):
            return {'label': 'Domain valid until', 'pattern': pattern_for('Domain valid until'),
                    'evidence': '2031-04-05'}
    assert module.verify(Fake())


def test_rejected_proposal_fails_verification():
    class Fake:
        def propose(self, text):
            return {'abstain': True}
    assert not module.verify(Fake())


import io
import json
import pytest
from self_healing_whois.healing_worker import Provider, ProviderResponseError


@pytest.mark.parametrize('payload, expected', [
    ({'choices': [{'message': {'content': None}}]}, 'no text content'),
    ({'choices': [{'message': {'content': []}}]}, 'no text content'),
    ({'choices': [{'message': {'content': '  '}}]}, 'no text content'),
    ({'choices': []}, 'no usable choices'),
    ({'choices': [{'message': None}]}, 'no usable message'),
    ({'error': {'message': 'private-provider-detail'}}, 'error payload'),
    ([], 'JSON object'),
    ({'choices': [{'message': {'content': '[]'}}]}, 'JSON object'),
])
def test_invalid_provider_response(monkeypatch, payload, expected):
    monkeypatch.setattr('urllib.request.urlopen',
                        lambda *a, **kw: io.BytesIO(json.dumps(payload).encode()))
    with pytest.raises(ProviderResponseError, match=expected) as error:
        Provider('https://example.test/chat/completions', 'test', 'secret').propose('test')
    assert 'private-provider-detail' not in str(error.value)
    assert 'secret' not in str(error.value)


def test_provider_response_success(monkeypatch):
    proposal = {'label': 'Domain valid until',
                'pattern': pattern_for('Domain valid until'), 'evidence': '2031-04-05'}
    payload = {'choices': [{'message': {'content': json.dumps(proposal)}}]}
    monkeypatch.setattr('urllib.request.urlopen',
                        lambda *a, **kw: io.BytesIO(json.dumps(payload).encode()))
    assert Provider('https://example.test/chat/completions', 'test').propose('test') == proposal
