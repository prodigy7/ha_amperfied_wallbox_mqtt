"""Minimal .env loader for the test scripts.

Deliberately not `source .env` in Bash, because special characters in the
password (e.g. `$`) would otherwise be interpreted by the shell as variable
expansion, silently mangling the password. This loader reads KEY=VALUE lines
directly and sets os.environ, without any shell involvement.
"""
from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def load_dotenv(path: Path = REPO_ROOT / ".env") -> None:
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        os.environ.setdefault(key, value)
