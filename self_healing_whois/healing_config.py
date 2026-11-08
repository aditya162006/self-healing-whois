"""Load simple KEY=value settings without executing or expanding file contents."""
import os
from pathlib import Path


def load_env(path):
    path = Path(path)
    if not path.is_file():
        return
    allowed = {'WHOIS_LLM_ENDPOINT', 'WHOIS_LLM_MODEL', 'WHOIS_LLM_API_KEY'}
    for line in path.read_text(encoding='utf-8-sig').splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        name, separator, value = line.partition('=')
        name, value = name.strip(), value.strip()
        if separator and name in allowed:
            if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
                value = value[1:-1]
            os.environ.setdefault(name, value)
