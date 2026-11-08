"""One real model request, followed by an isolated end-to-end repair check."""
import json
import os
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

from self_healing_whois import healing
from self_healing_whois.healing_worker import Provider, ProviderResponseError
from self_healing_whois.healing_config import load_env
from self_healing_whois.parser import WhoisEntry

BASELINE = ('Domain Name: EXAMPLE.COM\nCreation Date: 2020-01-01\n'
            'Expiry Date: 2031-04-05\n')
BROKEN = BASELINE.replace('Expiry Date:', 'Domain valid until:')


def verify(provider):
    """Verify actual background validation and in-memory publication."""
    healing.disable()
    original = WhoisEntry.load('example.com', BASELINE).expiration_date
    assert original == datetime(2031, 4, 5, tzinfo=timezone.utc)
    entry = WhoisEntry.load('example.com', BROKEN)
    assert entry.expiration_date is None
    print('Baseline expiration:', original)
    print('Changed field label: Expiry Date -> Domain valid until')
    print('Before repair: None')
    client = healing.enable(provider=provider)
    try:
        try:
            client.finish_lookup(entry)
        except Exception:
            status = client.job_status(entry)
            print('Repair status:', status['status'] if status else 'not queued')
            print('FAIL: no repair accepted.', status['error'] if status else '')
            return False
        print('Repair status:', client.job_status(entry)['status'])
        print('After repair:', entry.expiration_date)
        assert entry.expiration_date == original
        unseen = BROKEN.replace('2031-04-05', '2032-05-06')
        assert WhoisEntry.load('example.com', unseen).expiration_date == datetime(2032, 5, 6, tzinfo=timezone.utc)
        assert WhoisEntry.load('example.com', BASELINE).expiration_date == original
        print('PASS: known date restored, unseen date parsed, original parsing preserved.')
        return True
    finally:
        healing.disable()


class ReportingProvider:
    def __init__(self, provider):
        self.provider = provider

    def propose(self, text):
        print('Sending one request to AI provider (socket timeout: 120 seconds)...', flush=True)
        try:
            proposal = self.provider.propose(text)
        except urllib.error.HTTPError as exc:
            hints = {400: 'Request/key/model may be invalid.',
                     402: 'Billing/credits issue. Check your AI provider project credits in your provider dashboard.',
                     401: 'Authentication failed.', 403: 'Access denied; check key restrictions and model access.',
                     404: 'Model or endpoint not found.', 429: 'Quota/rate limit exceeded; check your provider dashboard.',
                     503: 'AI provider service is temporarily unavailable. Retry later.'}
            print(f'AI provider HTTP {exc.code}:', hints.get(exc.code, 'Provider request failed.'))
            raise
        except ProviderResponseError as exc:
            print('AI provider response invalid:', str(exc))
            raise
        except TimeoutError:
            print('AI provider timed out. Key validity and AI repair are still unverified; retry later.')
            raise
        except json.JSONDecodeError:
            print('AI provider response could not be parsed as the required JSON. Repair is not verified.')
            raise
        except Exception as exc:
            print('AI provider request/response failed:', type(exc).__name__)
            raise
        print('PASS: AI provider returned a parsed response using your key and selected model.')
        return proposal


def main():
    print('Real AI test: one API request using synthetic WHOIS text; provider limits/pricing apply.')
    print('All repair state stays in memory and is cleared when the test ends.')
    load_env(Path(__file__).resolve().parents[1] / '.env')
    model = os.environ.get('WHOIS_LLM_MODEL', '').strip()
    key = os.environ.get('WHOIS_LLM_API_KEY', '').strip()
    endpoint = os.environ.get('WHOIS_LLM_ENDPOINT', '').strip()
    if not model or not key or not endpoint:
        raise SystemExit('Set WHOIS_LLM_ENDPOINT, WHOIS_LLM_MODEL and WHOIS_LLM_API_KEY in .env.')
    print('Model:', model)
    provider = ReportingProvider(Provider(
        endpoint, model, key))
    try:
        success = verify(provider)
    except Exception as exc:
        print('FAIL:', type(exc).__name__, '- verification did not complete.')
        success = False
    raise SystemExit(0 if success else 1)


if __name__ == '__main__':
    main()
