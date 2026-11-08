"""Build a regression corpus from upstream's checked-in expected results."""
import json
from pathlib import Path

from self_healing_whois.healing import normalized, scope
from self_healing_whois.parser import WhoisEntry

root = Path(__file__).resolve().parents[1]
cases = []
skipped = []
for sample in sorted((root / 'test/samples/whois').iterdir()):
    expected_file = root / 'test/samples/expected' / sample.name
    if not expected_file.is_file():
        continue
    expected = json.loads(expected_file.read_text(encoding='utf-8'))
    if 'expiration_date' not in expected:
        continue
    text = sample.read_text(encoding='utf-8')
    try:
        entry = WhoisEntry.load(sample.name, text)
        value = normalized(expected['expiration_date'])
        if normalized(entry.get('expiration_date')) != value:
            skipped.append(sample.name)
            continue
    except Exception:
        skipped.append(sample.name)
        continue
    cases.append({'scope': scope(entry), 'domain': sample.name,
                  'text': entry.text, 'expected': value})
(root / 'self_healing_whois/healing_corpus.json').write_text(json.dumps(cases, indent=2), encoding='utf-8')
print(f'Wrote {len(cases)} verified historical cases; skipped {skipped}')
