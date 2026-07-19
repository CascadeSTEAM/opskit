"""
device_registry.py — Canonical device identity and relationship resolution.

The registry is the hub of the gather→resolve→write pipeline:

  Phase 1 GATHER  (no I/O): each scanner feeds raw records into register()
  Phase 2 RESOLVE (pure):   merge_identities() then resolve_uplinks()
  Phase 3 VALIDATE:         validate() — check every node reaches router
  Phase 4 WRITE:            write_md() + write_yaml_uplinks()

MAC address is the ground truth identity key.  Two records with the same
MAC are always the same physical device regardless of hostname.  Two records
with the same IP but no MAC are flagged as probable duplicates for human
review — we never auto-merge on IP alone.

Source priority (higher wins for scalar fields when merging):
  manual=5  proxmox=4  technitium=3  lldp=2  bridge=1  nmap=0
"""

from __future__ import annotations
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from datetime import date

import yaml

TODAY = date.today().isoformat()

# ── Source priority ───────────────────────────────────────────────────────────

SOURCE_PRIORITY: dict[str, int] = {
    'manual': 5,
    'proxmox': 4,
    'technitium': 3,
    'lldp': 2,
    'bridge': 1,
    'nmap': 0,
}

# Infrastructure device types whose presence on a port defines the gateway
INFRA_PRIORITY: dict[str, int] = {
    'router': 4, 'switch': 3, 'hypervisor': 2,
    'access-point': 1, 'access_point': 1,
}

# Scalar fields — lower-priority source cannot overwrite a higher-priority value
SCALAR_FIELDS = [
    'hostname', 'ip', 'mac', 'type', 'role', 'vendor', 'model', 'os',
    'status', 'proxmox_host', 'proxmox_id', 'proxmox_type',
    'connection', 'band', 'dhcp', 'credentials', 'environment',
]

# Generic hostname patterns produced by scanners when identity is unknown
_PLACEHOLDER_RE = re.compile(
    r'^(ct-\d+|host-[\d-]+|embedded-linux-\d+|wlan\d+|eth\d+|DEFAULT|unknown-\d+)$',
    re.IGNORECASE,
)


def is_placeholder(hostname: str) -> bool:
    return bool(_PLACEHOLDER_RE.match((hostname or '').strip()))


def normalize_mac(mac: str) -> str:
    if not mac:
        return ''
    cleaned = re.sub(r'[^a-fA-F0-9]', '', mac)
    if len(cleaned) != 12:
        return mac.upper().strip()
    return ':'.join(cleaned[i:i+2] for i in range(0, 12, 2)).upper()


# ── Canonical device record ───────────────────────────────────────────────────

@dataclass
class CanonicalDevice:
    # Ground-truth identity
    mac: str = ''           # normalized MAC — primary key when present

    # Best-known values (updated by merge priority)
    hostname:     str = ''
    ip:           str = ''
    type:         str = 'unknown'
    role:         str = 'unknown'
    vendor:       str = ''
    model:        str = ''
    os:           str = ''
    status:       str = 'unknown'
    credentials:  bool = False
    environment:  str = ''

    # Network topology (resolved in Phase 2)
    uplink_host:  str = ''
    proxmox_host: str = ''
    proxmox_id:   str = ''
    proxmox_type: str = ''

    # WiFi / DHCP extras
    connection:   str = ''
    band:         str = ''
    dhcp:         str = ''

    # Provenance
    sources:      list[str] = field(default_factory=list)
    merged_from:  list[str] = field(default_factory=list)   # other hostnames folded in
    source_priority: int = -1   # highest priority seen so far

    # Validation output (populated by validate())
    uplink_chain:  list[str] = field(default_factory=list)
    validation_errors: list[str] = field(default_factory=list)


# ── Registry ─────────────────────────────────────────────────────────────────

class DeviceRegistry:
    """
    Gather→resolve→write pipeline for network device inventory.

    Usage:
        reg = DeviceRegistry(router_hostname='crs326-router')
        for record in yaml_scan():  reg.register(record, 'manual')
        for record in dhcp_scan():  reg.register(record, 'technitium')
        reg.resolve_uplinks(bridge_table, lldp_neighbors)
        problems = reg.validate()
        reg.write_md(out_dir, config)
    """

    def __init__(self, router_hostname: str = 'crs326-router'):
        self.router_hostname = router_hostname
        self._by_mac:      dict[str, CanonicalDevice] = {}   # MAC → device
        self._by_ip:       dict[str, str] = {}               # IP  → MAC
        self._by_hostname: dict[str, str] = {}               # hostname → MAC
        # Devices with no MAC, keyed by IP (can't merge reliably)
        self._no_mac:      dict[str, CanonicalDevice] = {}   # IP → device
        # Topology (set before resolve)
        self._bridge_table:   dict[str, str] = {}   # MAC → port
        self._lldp_neighbors: dict[str, str] = {}   # port → device identity

    # ── Gather ────────────────────────────────────────────────────────────────

    def register(self, record: dict, source: str) -> Optional[CanonicalDevice]:
        """
        Add a raw scan record to the registry.  Returns the canonical device.

        record keys (all optional):
          mac, ip, hostname, type, role, vendor, model, os, status,
          proxmox_host, proxmox_id, credentials, environment,
          connection, band, dhcp
        """
        mac  = normalize_mac(record.get('mac') or '')
        ip   = str(record.get('ip')       or '').strip()
        hn   = str(record.get('hostname') or '').strip().lower()
        prio = SOURCE_PRIORITY.get(source, 0)

        # ── Find or create canonical device ──────────────────────────────────

        device: Optional[CanonicalDevice] = None

        if mac:
            device = self._by_mac.get(mac)
            if device is None and ip and ip in self._by_ip:
                device = self._by_mac.get(self._by_ip[ip])
        elif ip:
            # No MAC — look up in no-MAC store or by hostname
            device = self._no_mac.get(ip)
            if device is None and hn and hn in self._by_hostname:
                existing_mac = self._by_hostname[hn]
                device = self._by_mac.get(existing_mac)

        if device is None:
            device = CanonicalDevice(mac=mac)
            if mac:
                self._by_mac[mac] = device
            elif ip:
                self._no_mac[ip] = device

        # ── Merge fields by priority ──────────────────────────────────────────

        self._merge(device, record, source, prio)

        # ── Update lookup tables ──────────────────────────────────────────────

        if mac:
            if ip:
                old_ip = self._by_ip.get(ip)
                if old_ip and old_ip != mac:
                    # IP moved to a different MAC — update
                    self._by_ip[ip] = mac
                elif not old_ip:
                    self._by_ip[ip] = mac
            if hn:
                self._by_hostname[hn] = mac

        return device

    def _merge(self, device: CanonicalDevice, record: dict, source: str, prio: int) -> None:
        """Merge record into device.  Higher-priority source wins for scalars."""
        if source not in device.sources:
            device.sources.append(source)

        # Track merged hostname aliases — only genuine different names
        hn = str(record.get('hostname') or '').strip().lower()
        if hn and hn not in device.merged_from:
            device.merged_from.append(hn)

        # Scalar fields: higher-priority source wins
        if prio >= device.source_priority:
            for f in SCALAR_FIELDS:
                val = record.get(f)
                if val is None or val == '':
                    continue
                if isinstance(val, bool):
                    setattr(device, f, val)
                    continue
                sv = str(val).strip()
                if sv and sv not in ('unknown', 'Unknown'):
                    setattr(device, f, sv)
            device.source_priority = prio

        # Proxmox fields always win when source is proxmox (runtime state)
        if source == 'proxmox':
            for f in ('proxmox_host', 'proxmox_id', 'proxmox_type', 'status'):
                val = record.get(f)
                if val not in (None, '', 'unknown'):
                    setattr(device, f, str(val).strip())

    def set_topology(self, bridge_table: dict[str, str],
                     lldp_neighbors: dict[str, str]) -> None:
        """
        Provide network topology data before resolve_uplinks().

        bridge_table:   {normalized_MAC: port_name}
        lldp_neighbors: {port_name: device_identity_hostname}
        """
        self._bridge_table   = bridge_table
        self._lldp_neighbors = lldp_neighbors

    # ── Resolve ───────────────────────────────────────────────────────────────

    def merge_identities(self) -> list[str]:
        """
        Merge no-MAC devices into MAC-keyed devices where possible.
        Returns list of merge actions taken.
        """
        actions = []
        to_remove = []

        for ip, no_mac_dev in self._no_mac.items():
            # Check if a MAC-keyed device now exists for this IP
            mac = self._by_ip.get(ip)
            if mac and mac in self._by_mac:
                mac_dev = self._by_mac[mac]
                # Merge no-mac record into the MAC-keyed device
                self._merge(mac_dev, {
                    'hostname': no_mac_dev.hostname,
                    'type': no_mac_dev.type,
                    'role': no_mac_dev.role,
                    'vendor': no_mac_dev.vendor,
                    'model': no_mac_dev.model,
                    'os': no_mac_dev.os,
                    'status': no_mac_dev.status,
                }, no_mac_dev.sources[0] if no_mac_dev.sources else 'unknown',
                no_mac_dev.source_priority)
                for src in no_mac_dev.sources[1:]:
                    if src not in mac_dev.sources:
                        mac_dev.sources.append(src)
                actions.append(
                    f'merged {no_mac_dev.hostname!r} (no-MAC at {ip}) into {mac_dev.hostname!r} ({mac})'
                )
                to_remove.append(ip)

        for ip in to_remove:
            del self._no_mac[ip]

        return actions

    def resolve_uplinks(self) -> list[str]:
        """
        Assign uplink_host to every device using bridge table topology.

        Returns list of resolution notes (informational).
        """
        notes = []

        # ── Build port → gateway map ──────────────────────────────────────────
        port_to_gateway: dict[str, tuple[str, int]] = {}  # port → (hostname, priority)

        all_devices = list(self._by_mac.values()) + list(self._no_mac.values())

        for dev in all_devices:
            pri = INFRA_PRIORITY.get((dev.type or '').lower().replace('_', '-'), 0)
            if pri == 0:
                continue
            mac = normalize_mac(dev.mac)
            port = self._bridge_table.get(mac) if mac else None
            if not port:
                continue
            existing = port_to_gateway.get(port)
            if not existing or pri > existing[1]:
                port_to_gateway[port] = (dev.hostname, pri)
                notes.append(f'port {port} → gateway {dev.hostname!r} (priority {pri})')

        # LLDP fills gaps for managed devices the bridge table identifies by hostname
        for port, identity in self._lldp_neighbors.items():
            if port in port_to_gateway:
                continue
            lkp = self._by_hostname.get(identity.lower())
            if lkp:
                dev = self._by_mac.get(lkp)
                if dev:
                    pri = INFRA_PRIORITY.get((dev.type or '').replace('_', '-'), 0)
                    if pri > 0:
                        port_to_gateway[port] = (dev.hostname, pri)
                        notes.append(f'port {port} → {dev.hostname!r} (via LLDP)')

        # ── Assign uplink_host ────────────────────────────────────────────────

        for dev in all_devices:
            if dev.hostname == self.router_hostname:
                continue

            # Containers: network exits through their Proxmox host
            if dev.proxmox_host and (dev.type or '') in ('lxc', 'qemu'):
                dev.uplink_host = dev.proxmox_host
                continue

            mac  = normalize_mac(dev.mac)
            port = self._bridge_table.get(mac) if mac else None

            if not port or port == 'bridgeLocal':
                dev.uplink_host = self.router_hostname
                continue

            gateway_hn, _ = port_to_gateway.get(port, (None, 0))
            if not gateway_hn:
                dev.uplink_host = self.router_hostname
                notes.append(f'{dev.hostname}: port={port} has no gateway → direct to router')
            elif gateway_hn == dev.hostname:
                # This device IS the gateway for its port
                dev.uplink_host = self.router_hostname
            else:
                dev.uplink_host = gateway_hn

        return notes

    # ── Validate ──────────────────────────────────────────────────────────────

    def validate(self) -> list[str]:
        """
        Walk uplink chains.  Returns list of problems (empty = all good).
        Populates dev.uplink_chain and dev.validation_errors on each device.
        """
        problems = []
        all_devices = list(self._by_mac.values()) + list(self._no_mac.values())

        hn_to_dev: dict[str, CanonicalDevice] = {}
        for dev in all_devices:
            if dev.hostname:
                hn_to_dev[dev.hostname.lower()] = dev

        for dev in all_devices:
            if dev.hostname.lower() == self.router_hostname.lower():
                dev.uplink_chain = [dev.hostname]
                continue

            chain:   list[str] = [dev.hostname]
            visited: set[str]  = {dev.hostname.lower()}
            current = dev.uplink_host
            ok = False

            while current:
                if current.lower() == self.router_hostname.lower():
                    chain.append(current)
                    ok = True
                    break
                if current.lower() in visited:
                    msg = f'CYCLE: {dev.hostname} → ... → {current}'
                    problems.append(msg)
                    dev.validation_errors.append(msg)
                    break
                if len(chain) > 12:
                    msg = f'DEPTH: {dev.hostname} chain exceeds 12 hops'
                    problems.append(msg)
                    dev.validation_errors.append(msg)
                    break
                next_dev = hn_to_dev.get(current.lower())
                if not next_dev:
                    msg = f'BROKEN: {dev.hostname} → {current} (not in registry)'
                    problems.append(msg)
                    dev.validation_errors.append(msg)
                    break
                visited.add(current.lower())
                chain.append(current)
                current = next_dev.uplink_host

            if not ok and not dev.validation_errors:
                msg = f'ORPHAN: {dev.hostname} chain did not reach router'
                problems.append(msg)
                dev.validation_errors.append(msg)

            dev.uplink_chain = chain

        return problems

    # ── Audit ─────────────────────────────────────────────────────────────────

    def audit(self) -> None:
        """Print audit report: duplicates, placeholders, validation errors."""
        all_devices = list(self._by_mac.values()) + list(self._no_mac.values())

        # MAC duplicates: only report genuine merges (different names for same device)
        merged = [
            (d.hostname, [a for a in d.merged_from if a.lower() != d.hostname.lower()])
            for d in all_devices
            if any(a.lower() != d.hostname.lower() for a in d.merged_from)
        ]
        ip_only = list(self._no_mac.values())

        placeholders = [d for d in all_devices if is_placeholder(d.hostname)]
        errors = [d for d in all_devices if d.validation_errors]

        if merged:
            print(f'\n  ── Merged identities ({len(merged)}) — same MAC, different names ──')
            for hn, aliases in sorted(merged):
                print(f'  {hn}: absorbed {", ".join(aliases)}')

        if ip_only:
            print(f'\n  ── IP-only devices ({len(ip_only)}) — no MAC, probable duplicates ──')
            for d in sorted(ip_only, key=lambda x: x.ip):
                print(f'  {d.ip}: hostname={d.hostname!r} sources={d.sources}')

        if placeholders:
            print(f'\n  ── Placeholder hostnames ({len(placeholders)}) ──')
            for d in sorted(placeholders, key=lambda x: x.hostname):
                print(f'  {d.hostname}: type={d.type} ip={d.ip}')

        if errors:
            print(f'\n  ── Validation errors ({len(errors)}) ──')
            for d in sorted(errors, key=lambda x: x.hostname):
                for e in d.validation_errors:
                    print(f'  {e}')

        total = len(merged) + len(ip_only) + len(placeholders) + len(errors)
        if total == 0:
            print('  Registry clean — no duplicates, placeholders, or broken chains.')

    # ── Write ─────────────────────────────────────────────────────────────────

    def write_uplinks_to_md(self, out_dir: Path, ref_fields: dict,
                            env: str, mode: str = 'update') -> tuple[int, int]:
        """
        Write uplink_host (and only uplink_host) back to existing .md files.
        Does not touch any other fields — the sync pipeline owns those.

        Returns (updated, skipped).
        """
        updated = skipped = 0
        all_devices = list(self._by_mac.values()) + list(self._no_mac.values())

        for dev in all_devices:
            if not dev.hostname or dev.hostname == self.router_hostname:
                continue
            if not dev.uplink_host:
                continue

            slug = re.sub(r'[^a-z0-9-]+', '-', dev.hostname.lower()).strip('-')
            note_path = out_dir / f'{slug}.md'

            # Also try merged-from slugs
            if not note_path.exists():
                for alias in dev.merged_from:
                    safe = re.sub(r'[^a-z0-9-]+', '-', alias.lower()).strip('-')
                    alt = out_dir / f'{safe}.md'
                    if alt.exists():
                        note_path = alt
                        break

            if not note_path.exists():
                skipped += 1
                continue

            content = note_path.read_text()
            fm_match = re.match(r'^(---\n)(.*?)(\n---)', content, re.DOTALL)
            if not fm_match:
                skipped += 1
                continue

            fm_text = fm_match.group(2)
            existing = re.search(r'^uplink_host:\s*(.*)$', fm_text, re.MULTILINE)
            current_val = existing.group(1).strip() if existing else ''

            if current_val == dev.uplink_host:
                skipped += 1
                continue

            if mode == 'diff':
                action = f'{current_val!r} → ' if current_val else 'set '
                print(f'  [uplink] {dev.hostname}: {action}{dev.uplink_host}')
                updated += 1
                continue

            if existing:
                new_fm = re.sub(
                    r'^uplink_host:.*$', f'uplink_host: {dev.uplink_host}',
                    fm_text, flags=re.MULTILINE
                )
            else:
                new_fm = fm_text.rstrip('\n') + f'\nuplink_host: {dev.uplink_host}'

            new_content = content[:fm_match.start(2)] + new_fm + content[fm_match.end(2):]
            note_path.write_text(new_content)
            updated += 1

        return updated, skipped

    def write_uplinks_to_yaml(self, yaml_dir: Path) -> tuple[int, int]:
        """
        Write uplink_host back to YAML source files for manually-documented devices.
        This ensures uplink_host survives subsequent --source yaml syncs.

        Returns (updated, skipped).
        """
        updated = skipped = 0

        for dev in self._by_mac.values():
            if 'manual' not in dev.sources:
                continue
            if not dev.hostname or not dev.uplink_host:
                continue

            slug = re.sub(r'[^a-z0-9-]+', '-', dev.hostname.lower()).strip('-')
            yml_path = yaml_dir / f'{slug}.yml'
            if not yml_path.exists():
                skipped += 1
                continue

            raw = yaml.safe_load(yml_path.read_text()) or {}
            d = raw.get('device', raw)
            if d.get('uplink_host') == dev.uplink_host:
                skipped += 1
                continue

            d['uplink_host'] = dev.uplink_host
            if 'device' in raw:
                raw['device'] = d
            else:
                raw = d
            yml_path.write_text(
                yaml.dump(raw, default_flow_style=False, sort_keys=False,
                          allow_unicode=True, width=120)
            )
            updated += 1

        return updated, skipped

    # ── Accessors ─────────────────────────────────────────────────────────────

    def all_devices(self) -> list[CanonicalDevice]:
        return list(self._by_mac.values()) + list(self._no_mac.values())

    def get_by_hostname(self, hostname: str) -> Optional[CanonicalDevice]:
        mac = self._by_hostname.get(hostname.lower())
        if mac:
            return self._by_mac.get(mac)
        return self._no_mac.get(hostname)

    def summary(self) -> str:
        return (f'{len(self._by_mac)} MAC-keyed + {len(self._no_mac)} IP-only = '
                f'{len(self._by_mac) + len(self._no_mac)} canonical devices')
