#!/usr/bin/env python3
"""Resolve the active environment — the single definition of that precedence.

opskit #126 (ledger row 11). `ACTIVE_ENV` lived only in `.env` at the repo root, so
two sessions sharing a clone shared one mutable global: when either ran
`bin/switch-env.sh`, every other session silently changed environment mid-task. The
observed consequence was a ticket opened with the wrong environment's prefix — filed
against the wrong client's helpdesk.

**An exported `ACTIVE_ENV` wins over `.env`**, so a session can pin itself and stop
caring what any other session does. Same shape as the existing `OPSKIT_ROOT`
override.

Six readers previously reimplemented the same three-line parse, and had already
drifted: `switch-env.sh` consulted the environment variable for display while every
other reader ignored it. Hence one implementation, used by the Python readers as a
module and by the shell readers as a CLI:

    ACTIVE_ENV=$(python3 "$REPO_ROOT/bin/active_env.py" || true)

Resolution reports its *source* as well as its value, because "which environment am
I in, and why" is the question an operator actually has when this goes wrong.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Source labels, so callers can explain themselves rather than just assert.
SOURCE_ENV_VAR = "ACTIVE_ENV environment variable (session-pinned)"
SOURCE_DOTENV = ".env"
SOURCE_NONE = "unset"


def _from_dotenv(repo_root: Path) -> str:
    env_file = repo_root / ".env"
    if not env_file.is_file():
        return ""
    try:
        lines = env_file.read_text().splitlines()
    except OSError:
        return ""
    for line in lines:
        if line.startswith("ACTIVE_ENV="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def resolve(repo_root: Path | str | None = None) -> tuple[str, str]:
    """Returns (environment name, human-readable source). Name is "" if unset.

    An exported variable wins deliberately and unconditionally — including when it
    disagrees with `.env`. Falling back to `.env` on a mismatch would restore the
    race this exists to end.
    """
    if repo_root is None:
        repo_root = os.environ.get("OPSKIT_ROOT") or Path(__file__).resolve().parent.parent
    repo_root = Path(repo_root)

    pinned = os.environ.get("ACTIVE_ENV", "").strip()
    if pinned:
        return pinned, SOURCE_ENV_VAR

    from_file = _from_dotenv(repo_root)
    if from_file:
        return from_file, SOURCE_DOTENV

    return "", SOURCE_NONE


def is_pinned() -> bool:
    """True when this session has pinned itself, so `.env` will not take effect."""
    return bool(os.environ.get("ACTIVE_ENV", "").strip())


def main(argv: list[str]) -> int:
    name, source = resolve()

    if "--source" in argv:
        print(source)
        return 0 if name else 1
    if "--verbose" in argv:
        print(f"{name or '(unset)'} — from {source}")
        return 0 if name else 1

    # Default: just the name, for `ACTIVE_ENV=$(... || true)` in shell callers.
    if name:
        print(name)
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
