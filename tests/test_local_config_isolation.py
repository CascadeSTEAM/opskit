"""No test result may depend on gitignored local config (opskit #122, row 16).

The failure this prevents is specific and was real: a merged change passed CI and
failed locally on the byte-identical commit, because a module read a gitignored
config file at import time and the suite inherited it. CI never has that file, so
the suite was permanently green while an operator with real config saw 41 failures.

Detection alone is not enough — a suite that behaves differently per machine is
broken even if something notices. So tests/conftest.py isolates every config path
for the whole session, and these tests hold that arrangement in place:

- every server that reads a gitignored path must honour an env override, or a new
  server silently reintroduces the hazard
- the isolation fixture must actually be in effect
"""

import re
from pathlib import Path

import pytest

from tests.conftest import CONFIG_PATH_VARS

ROOT = Path(__file__).resolve().parents[1]
SERVERS = sorted((ROOT / "mcp").glob("*-mcp-server.py"))

# A path literal that only exists on a configured machine.
LOCAL_PATH = re.compile(r'"[^"]*\.local\.json"')
# `os.environ[...]` or `os.environ.get(...)` near it means an override exists.
OVERRIDE = re.compile(r'os\.environ(?:\.get)?\(?\[?["\']([A-Z0-9_]+)["\']')


def test_there_are_servers_to_check():
    """A vacuous pass here would hide every other assertion in this module."""
    assert SERVERS, "no mcp/*-mcp-server.py found"


@pytest.mark.parametrize("server", SERVERS, ids=lambda p: p.name)
def test_a_server_reading_local_config_honours_an_override(server):
    """Otherwise its tests read whatever the developer happens to have."""
    source = server.read_text()
    local_refs = LOCAL_PATH.findall(source)
    if not local_refs:
        pytest.skip(f"{server.name} reads no *.local.json")

    env_vars = set(OVERRIDE.findall(source))
    declared = set(CONFIG_PATH_VARS) & env_vars

    assert declared, (
        f"{server.name} reads {local_refs[0]} but honours none of the known "
        f"config-path overrides {CONFIG_PATH_VARS}. Add one, and register it in "
        f"tests/conftest.py — otherwise this server's tests inherit real local "
        f"config and CI will disagree with a configured machine."
    )


@pytest.mark.parametrize("var", CONFIG_PATH_VARS)
def test_the_isolation_fixture_is_in_effect(var, isolate_local_config):
    """The fixture is autouse, but a fixture that silently stopped applying would
    reintroduce the original bug invisibly — so assert it, do not assume it."""
    import os

    value = os.environ.get(var)

    assert value is not None, f"{var} is not isolated"
    assert not Path(value).exists(), (
        f"{var} points at {value}, which exists — tests would read real config"
    )


def test_every_registered_override_is_used_by_some_server():
    """A stale entry in CONFIG_PATH_VARS is a lie about what is isolated."""
    all_source = "\n".join(s.read_text() for s in SERVERS)
    unused = [v for v in CONFIG_PATH_VARS if v not in all_source]

    assert not unused, (
        f"{unused} listed in tests/conftest.py but read by no server — remove them "
        f"or the isolation list overstates what it covers"
    )
