"""DNS/DHCP server as a scan source (opskit #145).

nmap learns hostnames only from reverse PTR, which is empty for most LAN
clients — so a scan produces a pile of `host-192-0-2-50` stubs that carry no
identity. The environment's DNS/DHCP server already knows those names: it
handed them out.

Two jobs, one integration surface:

  1. **Hostname resolution** — fill `hostname` for devices reverse PTR missed,
     matching on MAC first (an address can move; a NIC usually does not) and
     falling back to IP.

  2. **Duplicate-hostname detection** — several DHCP clients can legitimately
     present the same name. That corrupts device-YAML identity merging: two
     devices collapse into one and a real host silently disappears from the
     dataset. Detected and reported as a topology problem rather than
     merged.

Lease data is passed in rather than fetched here, so every behaviour below is
testable against fixtures with no network and no live server. Populate the
cache with `bin/fetch-dhcp-leases.py`.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

# Names the scanner invents when it learns nothing: host-192-0-2-50, and the
# dataset_writer's occasional unknown-N form. These are placeholders to be
# replaced, not identities to be preserved.
STUB_NAME = re.compile(r'^(host-\d+-\d+-\d+-\d+|unknown-\d+)$')
_STUB_NAME = STUB_NAME  # module-local alias

# Names a DHCP server hands out that identify nothing.
_USELESS_LEASE_NAMES = {'', '-', 'unknown', 'localhost', 'dhcp', 'client'}

LEASE_CACHE_NAME = 'dhcp-leases.json'


def load_leases(ds_path: Path) -> list[dict]:
    """Cached lease records for a dataset, or [] when none have been fetched.

    Accepts either a bare list or the wrapper the MCP tool returns
    (`{"leases": [...]}`), and tolerates several scopes concatenated.
    """
    cache = ds_path / LEASE_CACHE_NAME
    if not cache.is_file():
        return []
    try:
        data = json.loads(cache.read_text())
    except (OSError, json.JSONDecodeError):
        return []

    if isinstance(data, dict):
        data = data.get('leases', [])
    if not isinstance(data, list):
        return []
    return [entry for entry in data if isinstance(entry, dict)]


def _norm_mac(mac) -> str:
    if not mac:
        return ''
    return re.sub(r'[^0-9a-f]', '', str(mac).lower())


def _lease_name(lease: dict) -> str:
    name = str(lease.get('hostName') or lease.get('hostname') or '').strip()
    # Trailing dot and domain suffix are DNS artefacts, not the device's name.
    name = name.rstrip('.')
    if name.lower() in _USELESS_LEASE_NAMES:
        return ''
    return name


def _lease_ip(lease: dict) -> str:
    return str(lease.get('ipAddress') or lease.get('address') or '').strip()


def _lease_expiry(lease: dict) -> str:
    """Sortable expiry string, or '' when the server did not supply one.

    Compared as text on purpose: Technitium emits ISO-8601, which sorts
    correctly as a string, and a lease whose format we do not recognise should
    lose to one we do rather than crash the run.
    """
    return str(lease.get('leaseExpires') or lease.get('leaseExpiry') or '').strip()


def _freshest_first(leases: list[dict]) -> list[dict]:
    """Most recently expiring lease first — that is the current one.

    Without this, whichever lease the server happened to return first won, so
    a device that had been renamed could be renamed *back* by a stale record.
    A silent wrong rename in the dataset is exactly the corruption this module
    must not cause.
    """
    return sorted(leases, key=_lease_expiry, reverse=True)


def index_leases(leases: list[dict]) -> tuple[dict, dict]:
    """(by_mac, by_ip) → hostname, skipping leases that name nothing.

    Fresh leases win: entries are indexed newest-first and `setdefault` keeps
    the first seen, so a renewal beats the record it replaced.
    """
    by_mac, by_ip = {}, {}
    for lease in _freshest_first(leases):
        name = _lease_name(lease)
        if not name:
            continue
        mac = _norm_mac(lease.get('hardwareAddress') or lease.get('mac'))
        if mac:
            by_mac.setdefault(mac, name)
        ip = _lease_ip(lease)
        if ip:
            by_ip.setdefault(ip, name)
    return by_mac, by_ip


def find_duplicate_hostnames(leases: list[dict]) -> list[dict]:
    """Hostnames claimed by more than one distinct MAC.

    Two leases for one MAC are just a renewal. Two MACs answering to one name
    are two devices the dataset cannot tell apart — which is what corrupts
    identity merging, so it is reported rather than silently resolved.
    """
    seen: dict[str, dict[str, str]] = {}
    for lease in leases:
        name = _lease_name(lease)
        if not name:
            continue
        mac = _norm_mac(lease.get('hardwareAddress') or lease.get('mac'))
        if not mac:
            continue
        seen.setdefault(name.lower(), {})[mac] = _lease_ip(lease)

    return [
        {
            'hostname': name,
            'macs': sorted(macs),
            'ips': sorted(ip for ip in macs.values() if ip),
        }
        for name, macs in sorted(seen.items())
        if len(macs) > 1
    ]


def _device_macs_and_ips(dev: dict) -> tuple[list[str], list[str]]:
    """MACs and addresses in **interface order**, de-duplicated.

    Order is preserved rather than sorted because it is the only signal about
    which interface is the primary one. Sorting would tie-break on the hex
    value of the MAC, so a device with two leased NICs would take whichever
    address happened to sort lower — deterministic, but meaningless.
    """
    macs, ips = [], []
    net = dev.get('device', {}).get('networking', {})
    for iface in net.get('interfaces', []) or []:
        if not isinstance(iface, dict):
            continue
        mac = _norm_mac(iface.get('mac'))
        if mac and mac not in macs:
            macs.append(mac)
        addr = str(iface.get('ipv4') or '').split('/')[0].strip()
        if addr and addr not in ips:
            ips.append(addr)
    return macs, ips


def needs_hostname(dev: dict) -> bool:
    """True when the record has no real name — absent, or a scanner stub."""
    name = str(dev.get('device', {}).get('hostname') or '').strip()
    return not name or bool(_STUB_NAME.match(name))


def resolve_hostnames(devices: dict[str, dict], leases: list[dict]) -> dict:
    """Fill hostnames from lease data, in place.

    MAC match wins over IP match: an address is reassigned routinely, a NIC
    much less so, and a stale IP-keyed lease would otherwise rename the wrong
    device — a silent identity corruption rather than a visible failure.

    Returns {device_name: resolved_hostname} for the records changed.
    """
    by_mac, by_ip = index_leases(leases)
    resolved = {}

    for name, dev in devices.items():
        if not needs_hostname(dev):
            continue
        macs, ips = _device_macs_and_ips(dev)

        # First matching interface wins, in interface order (see
        # _device_macs_and_ips) — the primary NIC names the device.
        found = next((by_mac[m] for m in macs if m in by_mac), '')
        source = 'dhcp_mac'
        if not found:
            found = next((by_ip[i] for i in ips if i in by_ip), '')
            source = 'dhcp_ip'
        if not found:
            continue

        record = dev.setdefault('device', {})
        record['hostname'] = found
        record.setdefault('metadata', {})['hostname_source'] = source
        resolved[name] = found

    return resolved


def flag_duplicate_leases(devices: dict[str, dict], leases: list[dict]) -> list[dict]:
    """Record duplicate-hostname conflicts on the affected device records.

    The flag lives on the device so it survives into the dataset and shows up
    wherever the record is read, rather than only in one run's console output.
    """
    duplicates = find_duplicate_hostnames(leases)
    if not duplicates:
        return []

    by_mac = {}
    for dup in duplicates:
        for mac in dup['macs']:
            by_mac[mac] = dup

    for dev in devices.values():
        macs, _ = _device_macs_and_ips(dev)
        hit = next((by_mac[m] for m in macs if m in by_mac), None)
        if hit:
            problems = dev.setdefault('device', {}).setdefault('problems', {})
            problems['duplicate_dhcp_hostname'] = {
                'hostname': hit['hostname'],
                'claimed_by': hit['macs'],
                'detail': (
                    'Several DHCP clients present this hostname. Device identity '
                    'merging cannot tell them apart — set a reservation so each '
                    'keeps a stable name (opskit #145).'
                ),
            }

    return duplicates


def enrich_from_leases(ds_path: Path, devices: dict[str, dict]) -> dict:
    """Both passes, for the cached lease data of one dataset.

    A no-op returning zeroes when no lease cache exists, so the scanner runs
    unchanged in environments that have not wired a DNS/DHCP source.
    """
    leases = load_leases(ds_path)
    if not leases:
        return {'lease_records': 0, 'hostnames_resolved': 0, 'duplicate_hostnames': []}

    resolved = resolve_hostnames(devices, leases)
    duplicates = flag_duplicate_leases(devices, leases)

    return {
        'lease_records': len(leases),
        'hostnames_resolved': len(resolved),
        'duplicate_hostnames': duplicates,
    }


def write_lease_cache(ds_path: Path, leases: list[dict]) -> Path:
    """Persist fetched leases beside the dataset. Returns the path written."""
    cache = ds_path / LEASE_CACHE_NAME
    cache.write_text(json.dumps({'leases': leases}, indent=2, sort_keys=True) + '\n')
    return cache


def load_yaml_devices(devices_dir: Path) -> dict[str, dict]:
    """Device records keyed by file stem — the shape the enricher passes in."""
    devices = {}
    for path in sorted(devices_dir.glob('*.yml')):
        try:
            data = yaml.safe_load(path.read_text())
        except (OSError, yaml.YAMLError):
            continue
        if isinstance(data, dict) and 'device' in data:
            devices[path.stem] = data
    return devices
