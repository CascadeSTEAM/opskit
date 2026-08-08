"""Tests for bin/scanner_lib/dns_source.py — DNS/DHCP as a scan source (#145).

Two defects motivate this module, and both are silent:

  * nmap gets hostnames from reverse PTR only, which is empty for most LAN
    clients, so a scan leaves a pile of `host-a-b-c-d` stubs that identify
    nothing — while the DHCP server knows every one of those names.
  * Several DHCP clients can present the same hostname. Device-YAML identity
    merging then collapses two real devices into one and a host disappears
    from the dataset without anything reporting an error.

Everything here runs against fixture lease data: no network, no live server.
"""

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from bin.scanner_lib import dns_source  # noqa: E402


def _lease(host, mac, ip):
    return {"hostName": host, "hardwareAddress": mac, "ipAddress": ip}


def _device(hostname, mac=None, ip=None):
    iface = {"name": "eth0"}
    if mac:
        iface["mac"] = mac
    if ip:
        iface["ipv4"] = f"{ip}/24"
    return {
        "device": {
            "hostname": hostname,
            "type": "server",
            "networking": {"interfaces": [iface]},
        }
    }


class HostnameResolutionTestCase(unittest.TestCase):
    def test_a_scanner_stub_gets_the_leased_name(self):
        devices = {"host-192-0-2-50": _device("host-192-0-2-50",
                                              mac="AA:BB:CC:00:00:01",
                                              ip="192.0.2.50")}
        leases = [_lease("printer-lab", "aa:bb:cc:00:00:01", "192.0.2.50")]

        resolved = dns_source.resolve_hostnames(devices, leases)

        self.assertEqual(resolved, {"host-192-0-2-50": "printer-lab"})
        self.assertEqual(devices["host-192-0-2-50"]["device"]["hostname"],
                         "printer-lab")

    def test_a_curated_name_is_never_overwritten(self):
        """A human-set name outranks whatever DHCP happens to say."""
        devices = {"gw": _device("border-router", mac="AA:BB:CC:00:00:01")}
        leases = [_lease("dhcp-guessed-name", "aa:bb:cc:00:00:01", "192.0.2.1")]

        resolved = dns_source.resolve_hostnames(devices, leases)

        self.assertEqual(resolved, {})
        self.assertEqual(devices["gw"]["device"]["hostname"], "border-router")

    def test_mac_match_beats_ip_match(self):
        """An address is reassigned routinely, a NIC much less so. A stale
        IP-keyed lease must not rename the device now holding that address."""
        devices = {"host-192-0-2-50": _device("host-192-0-2-50",
                                              mac="AA:BB:CC:00:00:01",
                                              ip="192.0.2.50")}
        leases = [
            _lease("stale-previous-tenant", "99:99:99:99:99:99", "192.0.2.50"),
            _lease("correct-device", "aa:bb:cc:00:00:01", "192.0.2.77"),
        ]

        dns_source.resolve_hostnames(devices, leases)

        self.assertEqual(devices["host-192-0-2-50"]["device"]["hostname"],
                         "correct-device")

    def test_ip_is_used_when_no_mac_matches(self):
        devices = {"host-192-0-2-50": _device("host-192-0-2-50", ip="192.0.2.50")}
        leases = [_lease("by-address", "aa:bb:cc:00:00:09", "192.0.2.50")]

        dns_source.resolve_hostnames(devices, leases)

        self.assertEqual(devices["host-192-0-2-50"]["device"]["hostname"],
                         "by-address")

    def test_the_source_is_recorded(self):
        """So a later reader can tell an inferred name from a curated one."""
        devices = {"host-192-0-2-50": _device("host-192-0-2-50",
                                              mac="AA:BB:CC:00:00:01")}
        leases = [_lease("leased", "aa:bb:cc:00:00:01", "192.0.2.50")]

        dns_source.resolve_hostnames(devices, leases)

        meta = devices["host-192-0-2-50"]["device"]["metadata"]
        self.assertEqual(meta["hostname_source"], "dhcp_mac")

    def test_placeholder_lease_names_are_ignored(self):
        """A lease saying 'unknown' is not an identity."""
        devices = {"host-192-0-2-50": _device("host-192-0-2-50",
                                              mac="AA:BB:CC:00:00:01")}
        for junk in ("", "-", "unknown", "localhost"):
            leases = [_lease(junk, "aa:bb:cc:00:00:01", "192.0.2.50")]
            self.assertEqual(dns_source.resolve_hostnames(devices, leases), {})

    def test_mac_formatting_differences_still_match(self):
        """The scanner and the DHCP server disagree about case and separators."""
        devices = {"host-192-0-2-50": _device("host-192-0-2-50",
                                              mac="AA-BB-CC-00-00-01")}
        leases = [_lease("matched", "aa:bb:cc:00:00:01", "192.0.2.50")]

        dns_source.resolve_hostnames(devices, leases)

        self.assertEqual(devices["host-192-0-2-50"]["device"]["hostname"],
                         "matched")


class LeasePrecedenceTestCase(unittest.TestCase):
    """Which lease wins when several describe the same thing (#145 review)."""

    def test_a_renewal_beats_the_lease_it_replaced(self):
        """Whichever lease the server returned first used to win, so a device
        that had been renamed could be renamed *back* by a stale record — a
        silent wrong rename in the dataset."""
        stale = dict(_lease("old-name", "aa:bb:cc:00:00:01", "192.0.2.50"),
                     leaseExpires="2020-01-01T00:00:00Z")
        current = dict(_lease("current-name", "aa:bb:cc:00:00:01", "192.0.2.50"),
                       leaseExpires="2026-08-08T00:00:00Z")

        for order in ([stale, current], [current, stale]):
            devices = {"h": _device("host-192-0-2-50", mac="AA:BB:CC:00:00:01")}
            dns_source.resolve_hostnames(devices, order)
            self.assertEqual(devices["h"]["device"]["hostname"], "current-name",
                             f"stale lease won for order {order is order}")

    def test_a_lease_with_no_expiry_loses_to_one_that_has_it(self):
        undated = _lease("undated", "aa:bb:cc:00:00:01", "192.0.2.50")
        dated = dict(_lease("dated", "aa:bb:cc:00:00:01", "192.0.2.50"),
                     leaseExpires="2026-08-08T00:00:00Z")

        devices = {"h": _device("host-192-0-2-50", mac="AA:BB:CC:00:00:01")}
        dns_source.resolve_hostnames(devices, [undated, dated])

        self.assertEqual(devices["h"]["device"]["hostname"], "dated")

    def test_the_first_interface_names_a_multi_nic_device(self):
        """With two leased NICs the match used to tie-break on the hex value of
        the MAC — deterministic but meaningless. Interface order is the only
        signal about which NIC is primary."""
        doc = _device("host-192-0-2-50")
        doc["device"]["networking"]["interfaces"] = [
            {"name": "eth0", "mac": "AA:BB:CC:00:00:02"},
            {"name": "eth1", "mac": "AA:BB:CC:00:00:01"},
        ]
        leases = [
            _lease("primary-nic", "aa:bb:cc:00:00:02", "192.0.2.50"),
            _lease("secondary-nic", "aa:bb:cc:00:00:01", "192.0.2.51"),
        ]

        devices = {"h": doc}
        dns_source.resolve_hostnames(devices, leases)

        self.assertEqual(devices["h"]["device"]["hostname"], "primary-nic")


class DuplicateHostnameTestCase(unittest.TestCase):
    def test_two_macs_one_name_is_reported(self):
        leases = [
            _lease("esp-device", "aa:bb:cc:00:00:01", "192.0.2.10"),
            _lease("esp-device", "aa:bb:cc:00:00:02", "192.0.2.11"),
        ]

        dups = dns_source.find_duplicate_hostnames(leases)

        self.assertEqual(len(dups), 1)
        self.assertEqual(dups[0]["hostname"], "esp-device")
        self.assertEqual(len(dups[0]["macs"]), 2)

    def test_a_renewed_lease_is_not_a_duplicate(self):
        """Same MAC twice is one device renewing, not two devices clashing."""
        leases = [
            _lease("laptop", "aa:bb:cc:00:00:01", "192.0.2.10"),
            _lease("laptop", "AA:BB:CC:00:00:01", "192.0.2.12"),
        ]

        self.assertEqual(dns_source.find_duplicate_hostnames(leases), [])

    def test_the_conflict_is_flagged_on_the_device_record(self):
        """It must survive into the dataset, not just one run's console."""
        devices = {"a": _device("esp-device", mac="AA:BB:CC:00:00:01"),
                   "b": _device("esp-device", mac="AA:BB:CC:00:00:02"),
                   "c": _device("unrelated", mac="AA:BB:CC:00:00:99")}
        leases = [
            _lease("esp-device", "aa:bb:cc:00:00:01", "192.0.2.10"),
            _lease("esp-device", "aa:bb:cc:00:00:02", "192.0.2.11"),
        ]

        dns_source.flag_duplicate_leases(devices, leases)

        for name in ("a", "b"):
            problems = devices[name]["device"]["problems"]
            self.assertEqual(problems["duplicate_dhcp_hostname"]["hostname"],
                             "esp-device")
        self.assertNotIn("problems", devices["c"]["device"])


class LeaseCacheTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="dns-source-test-"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_missing_cache_is_a_no_op(self):
        """Environments with no DNS/DHCP source wired must scan unchanged."""
        summary = dns_source.enrich_from_leases(self.tmp, {})

        self.assertEqual(summary["lease_records"], 0)
        self.assertEqual(summary["hostnames_resolved"], 0)

    def test_a_corrupt_cache_does_not_wedge_enrichment(self):
        (self.tmp / dns_source.LEASE_CACHE_NAME).write_text("{not json")

        self.assertEqual(dns_source.load_leases(self.tmp), [])

    def test_both_cache_shapes_are_accepted(self):
        bare = [_lease("a", "aa:bb:cc:00:00:01", "192.0.2.10")]
        (self.tmp / dns_source.LEASE_CACHE_NAME).write_text(json.dumps(bare))
        self.assertEqual(len(dns_source.load_leases(self.tmp)), 1)

        (self.tmp / dns_source.LEASE_CACHE_NAME).write_text(
            json.dumps({"leases": bare}))
        self.assertEqual(len(dns_source.load_leases(self.tmp)), 1)

    def test_round_trip_through_the_cache(self):
        leases = [_lease("printer-lab", "aa:bb:cc:00:00:01", "192.0.2.50")]
        dns_source.write_lease_cache(self.tmp, leases)

        devices = {"host-192-0-2-50": _device("host-192-0-2-50",
                                              mac="AA:BB:CC:00:00:01")}
        summary = dns_source.enrich_from_leases(self.tmp, devices)

        self.assertEqual(summary["lease_records"], 1)
        self.assertEqual(summary["hostnames_resolved"], 1)
        self.assertEqual(devices["host-192-0-2-50"]["device"]["hostname"],
                         "printer-lab")


class EnricherIntegrationTestCase(unittest.TestCase):
    """The phase must be wired into enrich_dataset, not merely importable."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="dns-enrich-test-"))
        self.devices_dir = self.tmp / "devices"
        self.devices_dir.mkdir()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write(self, name, doc):
        (self.devices_dir / f"{name}.yml").write_text(
            yaml.dump(doc, default_flow_style=False, sort_keys=False))

    def test_enrichment_applies_leases_and_persists_them(self):
        from bin.scanner_lib import enricher

        self._write("host-192-0-2-50",
                    _device("host-192-0-2-50", mac="AA:BB:CC:00:00:01",
                            ip="192.0.2.50"))
        dns_source.write_lease_cache(
            self.tmp, [_lease("printer-lab", "aa:bb:cc:00:00:01", "192.0.2.50")])

        summary = enricher.enrich_dataset(self.tmp)

        self.assertEqual(summary["hostnames_resolved"], 1)
        written = yaml.safe_load(
            (self.devices_dir / "host-192-0-2-50.yml").read_text())
        self.assertEqual(written["device"]["hostname"], "printer-lab")

    def test_enrichment_without_a_lease_cache_is_unchanged(self):
        from bin.scanner_lib import enricher

        self._write("srv", _device("srv", mac="AA:BB:CC:00:00:01"))

        summary = enricher.enrich_dataset(self.tmp)

        self.assertEqual(summary["hostnames_resolved"], 0)
        self.assertEqual(summary["duplicate_hostnames"], [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
