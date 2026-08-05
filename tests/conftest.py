"""Shared test isolation (opskit #122, ledger row 16).

A merged change once passed CI and failed locally on the byte-identical commit: a
module read a gitignored local config file at import time and the test suite
inherited it. CI never has that file, so the suite was permanently green while any
developer holding real config saw 41 failures.

That is the worst shape a suite can take — green stops meaning "this works" and
starts meaning "this works on a machine with no configuration", and the people who
hit the failures are the ones actually operating the tool.

The fix here is prevention rather than detection: point every config-path override
at a temporary directory for the whole session, so no test can read a real local
file regardless of what the developer has. Presence or absence then cannot matter
by construction, instead of by everyone remembering to isolate their own test.

Tests that want specific config still set their own override; an explicit
monkeypatch or env in a test wins over a session fixture.
"""

import os

import pytest

# Every environment variable a server consults for its tenants/servers config.
# A new server belongs here — tests/test_local_config_isolation.py fails if one
# reads a gitignored path without an override, which is what keeps this honest.
CONFIG_PATH_VARS = (
    "ERPNEXT_TENANTS_FILE",
    "PROXMOX_TENANTS_FILE",
    "TECHNITIUM_SERVERS_FILE",
    "WIREGUARD_TENANTS_FILE",
)

# Credentials a server might read. A developer's exported secrets must not be able
# to make a test pass — or fail — by accident.
CREDENTIAL_PREFIXES = ("ERPNEXT_", "PROXMOX_", "TECHNITIUM_", "WG_", "MIKROTIK_")


@pytest.fixture(scope="session", autouse=True)
def isolate_local_config(tmp_path_factory):
    """Redirect every config override into an empty temp dir for the session.

    Pointed at a path that does not exist, each server falls back to its own
    committed example config — the same thing CI sees — so a developer with real
    tenants configured gets identical results to CI.
    """
    empty = tmp_path_factory.mktemp("no-local-config")
    saved: dict[str, str | None] = {}

    for var in CONFIG_PATH_VARS:
        saved[var] = os.environ.get(var)
        os.environ[var] = str(empty / "absent.json")

    # Only strip credentials that are not already deliberately set by a test
    # runner; individual tests that need one set it themselves.
    for key in list(os.environ):
        if key.startswith(CREDENTIAL_PREFIXES) and key not in saved:
            saved[key] = os.environ[key]
            del os.environ[key]

    yield empty

    for var, value in saved.items():
        if value is None:
            os.environ.pop(var, None)
        else:
            os.environ[var] = value
