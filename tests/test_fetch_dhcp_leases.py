"""Tests for bin/fetch-dhcp-leases.py — the DHCP lease fetcher (#145).

The fetch is deliberately separate from enrichment so that enrichment runs
offline against a cache. That makes this script the one piece that talks to a
live server, so what is worth pinning here is its *contract*, not its network
behaviour: it must fail loudly rather than write an empty or partial cache,
and it must never leave the dataset in a state the enricher would read as
"the server says these devices have no names".
"""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "bin" / "fetch-dhcp-leases.py"

spec = importlib.util.spec_from_file_location("fetch_dhcp_leases", SCRIPT)
fetcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fetcher)


def test_the_script_exists_and_is_executable():
    assert SCRIPT.is_file()
    assert SCRIPT.stat().st_mode & 0o111, "needs to be runnable directly"


def test_it_hardcodes_no_infrastructure_values():
    """Committed tooling stays environment-agnostic (#134)."""
    import re
    rfc1918 = re.compile(
        r"\b(10\.\d{1,3}\.\d{1,3}\.\d{1,3}"
        r"|192\.168\.\d{1,3}\.\d{1,3}"
        r"|172\.(1[6-9]|2[0-9]|3[01])\.\d{1,3}\.\d{1,3})\b"
    )
    assert not rfc1918.search(SCRIPT.read_text())


def test_a_scope_listing_error_aborts_rather_than_caching_nothing(monkeypatch):
    """Writing an empty cache would make the enricher conclude the server
    knows no hostnames — a silent wrong answer instead of a loud failure."""
    monkeypatch.setattr(fetcher, "_call_tool",
                        lambda tool, **kw: {"error": "auth failed"})

    with pytest.raises(RuntimeError, match="auth failed"):
        fetcher.fetch("someenv", None)


def test_a_server_with_no_scopes_is_an_error_not_an_empty_cache(monkeypatch):
    monkeypatch.setattr(fetcher, "_call_tool", lambda tool, **kw: {"scopes": []})

    with pytest.raises(RuntimeError, match="no scopes"):
        fetcher.fetch("someenv", None)


def test_one_failing_scope_fails_the_whole_fetch(monkeypatch):
    """A partial cache is worse than none: the enricher cannot tell the
    difference between 'not leased' and 'that scope errored'."""
    def fake(tool, **kw):
        if tool == "dhcp_list_leases" and kw["scope_name"] == "bad":
            return {"error": "scope unavailable"}
        return {"leases": [{"hostName": "a", "hardwareAddress": "aa",
                            "ipAddress": "192.0.2.10"}]}

    monkeypatch.setattr(fetcher, "_call_tool", fake)

    with pytest.raises(RuntimeError, match="scope unavailable"):
        fetcher.fetch("someenv", ["good", "bad"])


def test_leases_from_every_scope_are_collected(monkeypatch):
    def fake(tool, **kw):
        return {"leases": [{"hostName": kw["scope_name"],
                            "hardwareAddress": f"aa:bb:cc:00:00:0{kw['scope_name'][-1]}",
                            "ipAddress": "192.0.2.10"}]}

    monkeypatch.setattr(fetcher, "_call_tool", fake)

    leases = fetcher.fetch("someenv", ["scope1", "scope2"])

    assert len(leases) == 2
    assert {lease["hostName"] for lease in leases} == {"scope1", "scope2"}


def test_scopes_are_discovered_when_none_are_named(monkeypatch):
    calls = []

    def fake(tool, **kw):
        calls.append(tool)
        if tool == "dhcp_list_scopes":
            return {"scopes": [{"name": "Default"}]}
        return {"leases": []}

    monkeypatch.setattr(fetcher, "_call_tool", fake)
    fetcher.fetch("someenv", None)

    assert "dhcp_list_scopes" in calls


def test_the_cache_it_writes_is_what_the_enricher_reads():
    """The two halves are separate modules; this pins the format between them."""
    from bin.scanner_lib import dns_source
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        ds = Path(tmp)
        leases = [{"hostName": "printer", "hardwareAddress": "aa:bb:cc:00:00:01",
                   "ipAddress": "192.0.2.50"}]
        dns_source.write_lease_cache(ds, leases)

        assert dns_source.load_leases(ds) == leases
        assert json.loads((ds / dns_source.LEASE_CACHE_NAME).read_text())["leases"]
