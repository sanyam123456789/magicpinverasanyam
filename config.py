"""Tiny .env loader (no extra dependency) plus env accessors.

Real environment variables always win over values in .env. Keys are read only from
the environment / .env file, never hard-coded and never logged.
"""
import os
from pathlib import Path

_ENV_PATH = Path(__file__).resolve().parent / ".env"


def load_env(path: Path = _ENV_PATH) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


load_env()


def env(name: str, default: str = "") -> str:
    """Return the variable's value, or `default` when it is unset or blank."""
    return os.environ.get(name, "") or default
