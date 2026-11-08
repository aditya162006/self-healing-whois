# Publishing self-healing-whois

The distribution is `self-healing-whois`, imported as `self_healing_whois`.
Version `0.1.0` is an experimental release. No upload is performed automatically.
The preserved upstream README describes the original library, not this fork's
installation name. Original license and attribution must remain included.

## Is GitHub required?

No. You can manually upload a wheel and source archive to PyPI from your computer.
A public source repository is recommended for issue reports and transparency.
When your fork is on GitHub, add its actual Source and Issues URLs to
`project_urls` in `setup.py`. Do not present the upstream repository as your fork.
GitHub Actions-based Trusted Publishing is a separate, optional workflow.

## Prepare and inspect

Create accounts on PyPI and TestPyPI, enable two-factor authentication, and check
that the desired name can be registered. This code change does not reserve it.
The two services use separate accounts/tokens. Never put publishing tokens into
the package, its README, or a Git commit.

From the project root and its activated virtual environment:

```powershell
python -m pip install -e ".[dev]"
python -m pytest -q
python examples/demo_healing.py
python -m build --outdir dist/self-healing-whois-0.1.0
python -m twine check dist/self-healing-whois-0.1.0/*
```

Use this release-specific directory, not a wildcard over old `dist/` contents.
Check it contains only `self_healing_whois-0.1.0` wheel/source archives. Do not
upload old `python_whois` artifacts. Inspect archives for `.env`, credentials,
runtime data, and required package data before upload.

## TestPyPI first

```powershell
python -m twine upload --repository testpypi dist/self-healing-whois-0.1.0/*
```

Paste the TestPyPI API token at the hidden prompt. In a fresh environment,
install dependencies from ordinary PyPI and the test release from TestPyPI:

```powershell
python -m pip install python-dateutil
python -m pip install --index-url https://test.pypi.org/simple/ --no-deps self-healing-whois==0.1.0
python -c "import self_healing_whois; print(self_healing_whois.__file__)"
```

Test from outside the checkout to ensure imports use the installed artifact.
Run the offline example and real-provider verification as appropriate; do not
confuse successful imports with validation of live WHOIS or AI services.

## Publish

After checking the TestPyPI installation:

```powershell
python -m twine upload dist/self-healing-whois-0.1.0/*
```

Use the real PyPI token. After publication, users can run:

```powershell
python -m pip install self-healing-whois
```

Future releases need a new version and release directory. PyPI does not let you
replace an already uploaded file with different contents under the same filename.

References: [Python packaging tutorial](https://packaging.python.org/en/latest/tutorials/packaging-projects/)
and [PyPI publishing documentation](https://docs.pypi.org/publishing/publishing-to-pypi/).
