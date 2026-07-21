"""Tests for scanner_lib.parser — discovery/portscan merge (issue #33)."""
from pathlib import Path

from bin.scanner_lib import parser

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
DISCOVERY = str(FIXTURES / "discovery.xml")
PORTSCAN = str(FIXTURES / "portscan.xml")


def test_parse_discovery_finds_all_hosts():
    hosts = parser.parse_discovery(DISCOVERY)
    ips = {h["ip"] for h in hosts}
    assert ips == {"192.0.2.10", "192.0.2.11", "192.0.2.12"}


def test_parse_portscan_standalone():
    hosts = parser.parse_portscan(PORTSCAN)
    ips = {h["ip"] for h in hosts}
    assert ips == {"192.0.2.10", "192.0.2.11", "192.0.2.20"}


def test_merge_retains_all_discovery_hosts():
    # Regression for #33: merging portscan into discovery dropped every host
    # that was already in discovery, returning only brand-new ones.
    discovery = parser.parse_discovery(DISCOVERY)
    merged = parser.parse_portscan(PORTSCAN, discovery)
    ips = {h["ip"] for h in merged}
    # .10/.11/.12 from discovery + .20 newly seen in portscan
    assert ips == {"192.0.2.10", "192.0.2.11", "192.0.2.12", "192.0.2.20"}


def test_merge_enriches_existing_hosts_with_open_ports():
    discovery = parser.parse_discovery(DISCOVERY)
    merged = parser.parse_portscan(PORTSCAN, discovery)
    by_ip = {h["ip"]: h for h in merged}
    ssh_ports = [p["port"] for p in by_ip["192.0.2.10"]["ports"]]
    assert 22 in ssh_ports
    assert 80 not in ssh_ports  # closed ports excluded
    assert by_ip["192.0.2.10"]["mac"] == "AA:BB:CC:00:00:10"


def test_merge_retains_discovery_host_absent_from_portscan():
    discovery = parser.parse_discovery(DISCOVERY)
    merged = parser.parse_portscan(PORTSCAN, discovery)
    by_ip = {h["ip"]: h for h in merged}
    # .12 was in discovery but not portscanned — must survive with no ports
    assert "192.0.2.12" in by_ip
    assert by_ip["192.0.2.12"]["ports"] == []


def test_merge_no_duplicate_ips():
    discovery = parser.parse_discovery(DISCOVERY)
    merged = parser.parse_portscan(PORTSCAN, discovery)
    ips = [h["ip"] for h in merged]
    assert len(ips) == len(set(ips))
