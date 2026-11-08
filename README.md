# self-healing-whois

This is my project for trying AI-assisted repair in a Python library. It is a fork of [python-whois](https://github.com/richardpenman/whois), which looks up domain registration information.

The original library already does the WHOIS lookup and most of the parsing. My addition handles one particular problem: what happens when the response has an expiration date, but the parser does not recognize its label?

For example, a parser might understand `Expiry Date:` but miss `Domain valid until:`. This project sends the failed response to an AI provider, asks for a repair, checks it against old examples, and uses it if the checks pass.

**This is still an experimental project.** I have tested normal domain lookups and a deliberately changed label with a real AI provider. That does not mean it can fix every registry format.

## What I added

- A background worker that asks an AI provider for an expiration-date regex repair.
- Checks against historical WHOIS examples before accepting a repair.
- An API for passing the key, model name, and endpoint directly.
- An in-memory cache so accepted repairs can be reused in the same process.
- An offline demo, a real AI verification script, and tests.

I did not write the original WHOIS client or all the domain parsers. Those come from python-whois, and the original license is kept in this repository.

## How it works

```text
Look up a domain
    |
Try the existing parser
    |
    +-- Expiration found --> return the result
    |
    +-- Expiration missing --> ask AI for a repair
                                  |
                            check old examples
                                  |
                            accept or reject
```

With healing enabled, a normal successful parse does not call AI. If the expiration date is missing, the default behavior is to wait for a checked repair. If that fails, the library raises `WhoisHealingError` instead of pretending it found a date.

The repair runs in a background thread, but waiting for it still makes that lookup slower. You can use `wait_for_repair=False` to get a partial result immediately. In that mode, keep the process running and do another lookup after the repair finishes.

## Installation

You need **Python 3.12 or newer**.

Version `0.1.1` has been installed and tested from TestPyPI in a separate Codespaces environment:

```bash
python -m pip install python-dateutil
python -m pip install --index-url https://test.pypi.org/simple/ --no-deps self-healing-whois==0.1.1
```

To work on the code, clone or download this repository, open a terminal in its folder, and run:

```bash
python -m venv .venv
```

Activate it on Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
```

Or on Linux/macOS:

```bash
source .venv/bin/activate
```

Then install the project and development tools:

```bash
python -m pip install -e ".[dev]"
```

The package name is `self-healing-whois`, but the Python import is `self_healing_whois`. This keeps it separate from the original library's `whois` import.

## Basic lookup

You do not need an AI key for a normal lookup:

```python
import self_healing_whois

result = self_healing_whois.whois("thispersondoesnotexist.com")
print(result)
print(result.expiration_date)
```

WHOIS lookups need internet access. Some servers or networks may block or limit requests.

## Using AI repair

Pass all three settings yourself. The library does not choose a default provider.

```python
from getpass import getpass
import self_healing_whois

client = self_healing_whois.enable_healing(
    api_key=getpass("API key: "),
    model=input("Model ID: ").strip(),
    endpoint=input("Full chat-completions endpoint: ").strip(),
)

try:
    result = self_healing_whois.whois("example.com")
    print(result)
except self_healing_whois.WhoisHealingError as error:
    print("Could not repair the expiration date:", error)
finally:
    self_healing_whois.disable_healing()
```

You can also pass strings or values from your application's environment variables. The prompts above are just one way to provide them. Do not put real keys in code that you upload to GitHub.

The endpoint must support the chat-completions request format used by this project. The library does not automatically work with every provider's API format. Network and WHOIS errors can still happen separately from repair errors.

Call `enable_healing()` once when your application starts and `disable_healing()` when it finishes. Configuration is shared within that Python process. You do not need a separate worker terminal.

Printing the result does not show the demo's before/after messages. Only expiration dates are repaired; other fields can still be empty. You can inspect the original response using `result.text`.

### Optional settings

| Setting | Default | What it does |
| --- | --- | --- |
| `wait_for_repair` | `True` | Wait for repair when the expiration date is missing |
| `repair_timeout` | `150` seconds | How long the caller waits for repair |
| `timeout` | `120` seconds | AI request socket timeout, up to 120 seconds |
| `queue_size` | `256` | Maximum number of waiting samples |
| `max_scopes` | `128` | Maximum parser/domain-suffix groups with cached repairs |
| `corpus_path` | Included JSON file | Optional replacement set of historical examples |

The WHOIS request has its own timeout, which you pass to `whois()`. The low-level `WhoisEntry.load()` method does not wait for background repair. For that use case, call `client.finish_lookup(entry)` explicitly.

## Trying the demos

Run these commands from the repository folder with the virtual environment activated.

### Offline demo

```bash
python examples/demo_healing.py
```

This uses a fake AI provider, so it needs no API key. It shows a missing date becoming a parsed date:

```text
Before: None
After:  2030-01-02 00:00:00+00:00
```

### Real AI test

Copy `.env.example` to `.env` if you do not already have one. Fill in your settings:

```dotenv
WHOIS_LLM_ENDPOINT=https://YOUR_PROVIDER/chat/completions
WHOIS_LLM_MODEL=model_name
WHOIS_LLM_API_KEY=YOUR_API_KEY
```

Then run:

```bash
python scripts/verify_ai_repair.py
```

This script reads `.env` from the project folder. Existing environment variables take priority. The library itself does not require a `.env` file.

The script changes a known expiration label, makes one real AI request, and checks that:

- The expected date is restored.
- The repair also works for a different date.
- The original label still works.

A successful run ends with:

```text
Repair status: accepted
After repair: 2031-04-05 00:00:00+00:00
PASS: known date restored, unseen date parsed, original parsing preserved.
```

This is a controlled test, not proof that a live registry changed its format. Provider usage limits and charges still apply. A normal website lookup might not call AI at all because the existing parser already works.

## Where the repairs are stored

Everything learned at runtime stays in memory. There is no SQLite database or runtime storage file.

When you stop the process or disable healing, the learned repairs are cleared. Different processes do not share repairs. The included `healing_corpus.json` contains historical examples for checking candidates; live lookups do not update it.

For debugging, `client.job_status(result)` reports the job status, attempt count, and error type. A result that did not need repair has no job.

## Tests

```bash
python -m pytest -q
```

The default tests run offline. They cover parsing, repair validation, waiting, rejected repairs, malformed provider responses, and cleanup. You do not need a real API key to run them.

The latest local run passed 57 tests. The repository also keeps upstream tests that need network access; those are not part of the default run. The GitHub Actions workflow is set up to run the offline tests, demo, and build on Python 3.12 and 3.13.

To build the package:

```bash
python -m build
```

## Files in this project

This is a fork, so some files belong to the original library. Here is what the main files do and what should go on GitHub.

| Path | Purpose | Commit? |
| --- | --- | --- |
| `README.md` | Setup, usage, limitations, and this guide | Yes |
| `LICENSE.txt` | Original MIT license and attribution | Yes; preserve it |
| `setup.py` | Package metadata, dependencies, Python requirement, dev extras | Yes |
| `pyproject.toml` | Build backend and default offline pytest configuration | Yes |
| `MANIFEST.in` | Data, docs, examples, and tests included in source packages | Yes |
| `requirements.txt` | Upstream pinned dateutil dependency | Yes |
| `.gitignore` | Excludes credentials, databases, caches, and environments | Yes |
| `.env.example` | Provider-neutral template without credentials | Yes |
| `.github/workflows/python-package.yml` | Automated tests and build | Yes |
| `.vscode/settings.json`, `.vscode/tasks.json` | Interpreter, tests, and task shortcuts | Optional |
| `self_healing_whois/__init__.py` | Public lookup API and healing exports | Yes |
| `self_healing_whois/whois.py` | Upstream WHOIS network client | Yes |
| `self_healing_whois/parser.py` | TLD parsers and failure-observation hook | Yes |
| `self_healing_whois/exceptions.py` | Lookup errors and `WhoisHealingError` | Yes |
| `self_healing_whois/time_zones.py` | Date/time-zone parsing data | Yes |
| `self_healing_whois/data/public_suffix_list.dat` | Domain suffix data | Yes |
| `self_healing_whois/healing.py` | In-memory queue, bounded rule/history cache, worker, waiting, lifecycle | Yes |
| `self_healing_whois/healing_worker.py` | Provider transport and pure regression validation | Yes |
| `self_healing_whois/healing_config.py` | Small `.env` loader for the live verification tool | Yes |
| `self_healing_whois/healing_corpus.json` | Historical WHOIS examples used to check repairs | Yes |
| `examples/demo_healing.py` | Offline demonstration with a fake model | Yes |
| `scripts/verify_ai_repair.py` | Real-provider verification with known expected dates | Yes |
| `scripts/build_healing_corpus.py` | Rebuilds corpus from upstream fixtures | Yes |
| `docs/SELF_HEALING.md` | Architecture, validation, operations, troubleshooting | Yes |
| `docs/PUBLISHING.md` | Release checks and publishing instructions | Yes |
| `docs/UPSTREAM_README.md` | Preserved original upstream README | Yes |
| `test/test_parser.py` | Upstream parser and date tests | Yes |
| `test/test_healing.py` | Validation, memory bounds, deduplication, and shutdown tests | Yes |
| `test/test_library_healing.py` | Direct-key API and transparent repair tests | Yes |
| `test/test_healing_config.py` | `.env` loading and precedence test | Yes |
| `test/test_verify_ai_repair.py` | Tests for the verification tool and provider responses | Yes |
| `test/test_main.py`, `test/test_query.py` | Upstream extraction/live tests; some require network | Yes |
| `test/test_ipv6.py`, `test/test_nicclient.py` | Upstream network-client behavior tests | Yes |
| `test/__init__.py`, `test/samples/` | Test package and raw/expected fixtures | Yes |
| `.env` | Your real API credentials | **No** |
| `.venv/` | Installed Python environment | **No** |
| `__pycache__/`, `.pytest_cache/`, `*.egg-info/`, `build/`, `dist/` | Generated files | **No** |
| `.git/` | Local repository metadata managed by Git | Never upload manually |

Keep `setup.py`, `pyproject.toml`, and `MANIFEST.in`. They are part of how the package is built and installed with its data files. `requirements.txt` keeps the upstream pinned dependency; normal package installation uses the dependencies in `setup.py`.

## Things it cannot do yet

- It only repairs expiration-date extraction, not all WHOIS fields.
- It accepts a limited set of English expiration labels and regex shapes. It does not run arbitrary AI-generated Python or regex.
- If the response has no expiration date, AI should not invent one.
- Repairs need historical examples for the relevant parser and domain suffix. Missing coverage or conflicting dates cause rejection.
- Passing the checks does not guarantee a repair will work on every future response.
- Large responses over 32 KiB are skipped. Queues and caches also have size limits.
- A retained failed job gets one AI attempt. There is no automatic retry loop. Restarting healing clears that state.
- An AI request already in progress cannot be cancelled immediately during shutdown, but it cannot publish a repair after shutdown.

The failed WHOIS response is sent to the provider you configure. It can contain contact details. This project does not save it to disk, but the provider has its own data policies.

## Publishing and GitHub

See [docs/PUBLISHING.md](docs/PUBLISHING.md) for the release steps. TestPyPI installation and the AI repair test have passed for `0.1.1`; a main PyPI release is a separate upload.

Before pushing, check that `.env`, `.venv`, caches, and build output are not included. `.env.example` is safe to commit because it only contains placeholders. Ignoring a file does not remove it from earlier commits if it was already tracked.

## Credits

This project is based on Richard Penman's [python-whois](https://github.com/richardpenman/whois), starting from commit `f686713155810ba125d59a30e962a38933f12dfe`.

The original README is kept in [docs/UPSTREAM_README.md](docs/UPSTREAM_README.md), and the original MIT license and attribution are in [LICENSE.txt](LICENSE.txt).
