#!/usr/bin/env python3
"""Resolve the active helpdesk ticket — the single definition of that precedence.

opskit #158 (ledger row 42). `.current-ticket` is one mutable file at the repo
root, and `bin/switch-env.sh` clears it unconditionally, so two sessions sharing
a clone shared one global: switching environments in either destroyed the other's
active ticket. The observed consequence was a session left with no ticket for its
infra commits while `commit-msg` still demanded one.

**An exported `OPSKIT_TICKET` wins over `.current-ticket`**, so a session can pin
itself and stop caring what any other session does. Deliberately the same shape
as the `ACTIVE_ENV` fix (#126/#127) and the `OPSKIT_ROOT` override — one pattern
to learn, not three.

Used by the Python readers as a module and by the shell readers as a CLI:

    TICKET=$(python3 "$REPO_ROOT/bin/active_ticket.py" || true)

Resolution reports its *source* as well as its value, because "which ticket am I
on, and why" is the question an operator actually has when this goes wrong.

NOTE: a ticket id contains the client's helpdesk prefix, which is client-
identifying (docs/client-data-policy.md). This module moves it between local
files and local processes only — nothing here may ever be published.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

TICKET_FILE = ".current-ticket"

# Source labels, so callers can explain themselves rather than just assert.
SOURCE_ENV_VAR = "OPSKIT_TICKET environment variable (session-pinned)"
SOURCE_FILE = ".current-ticket"
SOURCE_NONE = "unset"


def _from_file(repo_root: Path) -> str:
    path = repo_root / TICKET_FILE
    if not path.is_file():
        return ""
    try:
        return path.read_text().strip()
    except OSError:
        return ""


def resolve(repo_root: Path | str | None = None) -> tuple[str, str]:
    """Returns (ticket id, human-readable source). Id is "" if unset.

    An exported variable wins deliberately and unconditionally — including when
    it disagrees with the file. Falling back to the file on a mismatch would
    restore the race this exists to end.
    """
    if repo_root is None:
        repo_root = (os.environ.get("OPSKIT_ROOT")
                     or Path(__file__).resolve().parent.parent)
    repo_root = Path(repo_root)

    pinned = os.environ.get("OPSKIT_TICKET", "").strip()
    if pinned:
        return pinned, SOURCE_ENV_VAR

    from_file = _from_file(repo_root)
    if from_file:
        return from_file, SOURCE_FILE

    return "", SOURCE_NONE


def is_pinned() -> bool:
    """True when this session pinned itself, so the file will not take effect."""
    return bool(os.environ.get("OPSKIT_TICKET", "").strip())


def main(argv: list[str]) -> int:
    ticket, source = resolve()

    if "--source" in argv:
        print(source)
        return 0 if ticket else 1
    if "--verbose" in argv:
        print(f"{ticket or '(unset)'} — from {source}")
        return 0 if ticket else 1
    if "--is-pinned" in argv:
        return 0 if is_pinned() else 1

    # Default: just the id, for `TICKET=$(... || true)` in shell callers.
    if ticket:
        print(ticket)
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
