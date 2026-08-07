#!/usr/bin/env python3
"""bw_session.py — the one definition of "where the vault session comes from".

A session may be supplied two ways (issue #152): the `BW_SESSION` environment
variable, or a file (default `~/.cache/opskit/bw-session`, overridable with
`BW_SESSION_FILE`). The environment variable wins when both are present.

Before this module the rule lived only in `bin/mcp-run.sh`, so the launcher
accepted a file-based session while `bin/bw-management.py` and `install.sh`
reported it missing — the repo's own diagnostics contradicting each other on the
repo's own documented setup (#155). Copying the fallback into each caller is the
copy-not-inherit defect this project keeps paying for (#80, #143, #146), so the
rule lives here once and every caller asks.

Stdlib only, and importable before `make deps`: `install.sh` runs it on a
machine that has no venv yet.

Library:
    from bw_session import resolve, SessionError
    token, source = resolve()          # raises SessionError with a usable message

CLI (for shell callers):
    bin/bw_session.py --source   # where a session would come from; no secret
    bin/bw_session.py --check    # exit 0/1 with a human-readable reason
    bin/bw_session.py --token    # the token on stdout, for $(...) capture
"""

from __future__ import annotations

import argparse
import os
import stat
import sys
from pathlib import Path

DEFAULT_REL = ".cache/opskit/bw-session"


class SessionError(Exception):
    """No usable session, with an operator-actionable message."""


def session_file_path() -> Path | None:
    """The configured session-file path, or None when none is discoverable.

    HOME is not guaranteed to exist: `env -i`, cron, and systemd units with a
    scrubbed environment all run without it, and dereferencing it blindly took
    down the whole launcher once (#154). No HOME simply means no default path.
    """
    override = os.environ.get("BW_SESSION_FILE")
    if override:
        return Path(override)
    home = os.environ.get("HOME")
    return Path(home) / DEFAULT_REL if home else None


def _read_session_file(path: Path) -> str:
    """Read the token, refusing a file whose permissions we cannot vouch for.

    Fail closed: a mode we cannot read is a refusal, not a pass. A session token
    is a live key to every secret in the vault, so an unverifiable guard that
    reports success is worse than no guard.

    The mode check follows symlinks on purpose — a link's own mode is 0777 on
    Linux and says nothing about who can read the token; the target's mode is
    what governs (#154).
    """
    try:
        mode = stat.S_IMODE(path.stat().st_mode)  # stat() follows symlinks
    except OSError as exc:
        raise SessionError(
            f"cannot read the file mode of {path} ({exc.strerror}), so its "
            f"permissions cannot be verified and it will not be used.\n"
            f"  Export the session instead:  export BW_SESSION=$(bw unlock --raw)"
        ) from exc

    if mode & 0o077:
        raise SessionError(
            f"{path} is mode {mode:o} — readable beyond its owner.\n"
            f"  A vault session token is a live key to every secret. Fix:\n"
            f"    chmod 600 {path}"
        )

    try:
        return path.read_text().strip()
    except OSError as exc:
        raise SessionError(f"cannot read {path}: {exc.strerror}") from exc


def resolve() -> tuple[str, str]:
    """Return (token, source). Raises SessionError when no usable session exists.

    `source` is either the literal "environment" or the session file's path —
    callers report it, because an operator chasing a stale token needs to know
    which one is actually in play, and refreshing the wrong one looks like the
    fix not working.
    """
    env_token = os.environ.get("BW_SESSION")
    if env_token:
        return env_token, "environment"

    path = session_file_path()
    if path is None:
        raise SessionError(
            "BW_SESSION is not set and no session file path is discoverable "
            "(HOME is unset).\n"
            "  Export the session:  export BW_SESSION=$(bw unlock --raw)"
        )
    try:
        present = path.is_file()
    except OSError as exc:
        # is_file() only swallows "missing"-shaped errors; EACCES (a session
        # file inside a directory we may not traverse) propagates. Without this
        # the operator gets a raw traceback instead of the actionable message
        # every other failure here produces.
        raise SessionError(
            f"cannot examine {path} ({exc.strerror}).\n"
            f"  Export the session instead:  export BW_SESSION=$(bw unlock --raw)"
        ) from exc

    if not present:
        raise SessionError(
            f"BW_SESSION is not set and {path} does not exist.\n"
            f"  Either:  export BW_SESSION=$(bw unlock --raw)\n"
            f"  Or:      mkdir -p {path.parent} && "
            f"(umask 077; bw unlock --raw > {path})"
        )

    token = _read_session_file(path)
    if not token:
        # A redirect creates the file before `bw` runs, so a failed unlock
        # leaves a correctly-permissioned EMPTY file behind. Saying "not set"
        # here would tell the operator to write the file they just wrote.
        raise SessionError(
            f"{path} exists but is EMPTY — a redirect creates the file before "
            f"bw runs, so a failed unlock leaves it empty.\n"
            f"  Re-run:  (umask 077; bw unlock --raw > {path})"
        )
    return token, str(path)


def refresh_hint(source: str) -> str:
    """How to refresh the session that is actually in play."""
    if source == "environment":
        return "re-run: export BW_SESSION=$(bw unlock --raw)"
    return f"refresh the session file: (umask 077; bw unlock --raw > {source})"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--source", action="store_true",
                      help="where a session would come from (prints no secret)")
    mode.add_argument("--check", action="store_true",
                      help="exit 0 if a session is usable, 1 otherwise")
    mode.add_argument("--token", action="store_true",
                      help="print the session token for $(...) capture")
    args = ap.parse_args(argv)

    try:
        token, source = resolve()
    except SessionError as exc:
        # Never on stdout: a caller doing $(... --token) must not capture prose.
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if args.token:
        print(token)
    else:
        print(source)
    return 0


if __name__ == "__main__":
    sys.exit(main())
