#!/usr/bin/env python3
"""
enrich-uplinks.py — Infer uplink_host for yeticraft device docs from the
MikroTik CRS326 bridge host table + LLDP neighbor table.

The bridge host table maps each device MAC → which switch port it appears on.
LLDP neighbors identify managed devices (APs, switches) by hostname/platform.
Together they give a complete picture of the network topology.

Algorithm:
  1. SSH to router; pull bridge host table (MAC → port) + LLDP neighbors
  2. Load device YAML files; build MAC → hostname map
  3. For each switch port, find its "gateway" device (the infra device on
     that port whose type is access-point / switch / hypervisor / router).
     LLDP identity takes priority over bridge-table type inference.
     That device's uplink is crs326-router (it's directly wired).
  4. Every other device on that port gets uplink_host = gateway hostname.
  5. Devices on ports with NO known gateway (e.g. direct single-device drops)
     fall back to crs326-router — they're directly wired to the switch.
  6. Devices on the router bridge itself get uplink_host = crs326-router.
  7. Write updated frontmatter + patch index.base with the uplink_host ref field.

Usage:
  # Dry run — show what would change
  python3 scripts/enrich-uplinks.py

  # Write changes
  python3 scripts/enrich-uplinks.py --write

  # Use pre-captured data files instead of live SSH
  python3 scripts/enrich-uplinks.py --bridge-file /tmp/bridge.txt \\
                                     --lldp-file /tmp/lldp.txt
"""

import argparse
import re
import subprocess
import sys
from pathlib import Path

import yaml

# ── Config ────────────────────────────────────────────────────────────────────

VAULT_ROOT    = Path(__file__).resolve().parent.parent
DEVICES_DIR   = VAULT_ROOT / 'docs' / 'reference' / 'yeticraft-devices'
INDEX_BASE    = DEVICES_DIR / 'index.base'
ROUTER_SSH    = 'example-router'

# Infrastructure device types and their priority (higher = more upstream)
# When multiple infra devices share a port, the highest-priority one is the gateway.
INFRA_PRIORITY = {'router': 4, 'switch': 3, 'hypervisor': 2, 'access-point': 1, 'access_point': 1}
INFRA_TYPES    = set(INFRA_PRIORITY.keys())

# The top-level router (no uplink_host)
ROUTER_HOSTNAME = 'crs326-router'

# ── SSH helpers ───────────────────────────────────────────────────────────────

def ssh_cmd(host: str, cmd: str) -> str:
    """Run a command on a MikroTik via SSH. Returns stdout."""
    result = subprocess.run(
        ['ssh', '-o', 'ConnectTimeout=5', '-o', 'BatchMode=yes', host, cmd],
        capture_output=True, text=True, timeout=10
    )
    if result.returncode != 0:
        print(f'ERROR: SSH to {host} failed ({cmd}): {result.stderr.strip()}', file=sys.stderr)
        sys.exit(1)
    return result.stdout

def fetch_bridge_table(host: str) -> str:
    return ssh_cmd(host, '/interface bridge host print terse')

def fetch_lldp_neighbors(host: str) -> str:
    return ssh_cmd(host, '/ip neighbor print terse')

# ── Parsing ───────────────────────────────────────────────────────────────────

def parse_lldp_neighbors(raw: str) -> dict[str, str]:
    """Return {port: identity/mac} from LLDP neighbor table.
    Prefers named identity (e.g. 'example-house-hap') over MAC for each port.
    When multiple neighbors share a port, keeps the one with an identity.
    """
    port_to_identity: dict[str, str] = {}
    for line in raw.splitlines():
        m_port  = re.search(r'interface=(\S+?)(?:,|\s)', line)
        m_id    = re.search(r'identity=(\S+)', line)
        m_mac   = re.search(r'mac-address=([0-9A-Fa-f:]+)', line)
        if not m_port:
            continue
        # Use the first interface name only (before comma)
        port    = m_port.group(1).split(',')[0]
        identity = m_id.group(1) if m_id and m_id.group(1) else ''
        mac     = m_mac.group(1).upper() if m_mac else ''
        if port in ('bridgeLocal',):
            continue
        # Prefer entries with a real identity name
        if identity and identity not in ('MikroTik',):
            port_to_identity[port] = identity
        elif port not in port_to_identity and mac:
            port_to_identity[port] = mac
    return port_to_identity

def parse_bridge_table(raw: str) -> dict[str, str]:
    """Return {normalized_mac: port_name} for external (non-local) entries."""
    mac_to_port: dict[str, str] = {}
    for line in raw.splitlines():
        # Skip local/router-own entries (DL flag) and gateway-facing (ether1)
        if ' DL ' in line or 'ether1-gateway' in line:
            continue
        m_mac  = re.search(r'mac-address=([0-9A-Fa-f:]+)', line)
        m_port = re.search(r'on-interface=(\S+)', line)
        if not m_mac or not m_port:
            continue
        mac_raw = m_mac.group(1).upper()
        port    = m_port.group(1)
        # Skip bridgeLocal itself — those are directly on the router's bridge
        # We'll handle them separately
        mac_to_port[mac_raw] = port
    return mac_to_port

def normalize_mac(mac: str) -> str:
    return mac.upper().replace('-', ':').strip()

# ── Device file loading ───────────────────────────────────────────────────────

def load_devices() -> dict[str, dict]:
    """Return {filename_stem: frontmatter_dict} for all .md files in DEVICES_DIR."""
    devices: dict[str, dict] = {}
    for md_file in DEVICES_DIR.glob('*.md'):
        text = md_file.read_text()
        m = re.match(r'^---\n(.*?)\n---', text, re.DOTALL)
        if not m:
            continue
        try:
            fm = yaml.safe_load(m.group(1)) or {}
        except yaml.YAMLError:
            continue
        if isinstance(fm, dict):
            devices[md_file.name] = {'fm': fm, 'path': md_file, 'raw': text}
    return devices

# ── Topology inference ────────────────────────────────────────────────────────

def build_uplinks(
    mac_to_port: dict[str, str],
    devices: dict[str, dict],
    lldp_port_to_identity: dict[str, str] | None = None,
) -> dict[str, str]:
    """Return {hostname: uplink_host} for every device we can resolve."""

    # Build MAC → hostname from device files
    mac_to_hostname: dict[str, str] = {}
    for info in devices.values():
        fm  = info['fm']
        mac = normalize_mac(str(fm.get('mac', '') or ''))
        hn  = str(fm.get('hostname', '') or '')
        if mac and hn:
            mac_to_hostname[mac] = hn

    # For each port, find the highest-priority infrastructure gateway device
    port_to_gateway: dict[str, str] = {}
    port_to_priority: dict[str, int] = {}
    for info in devices.values():
        fm   = info['fm']
        mac  = normalize_mac(str(fm.get('mac', '') or ''))
        hn   = str(fm.get('hostname', '') or '')
        typ  = str(fm.get('type', '') or '').lower()
        if not mac or not hn:
            continue
        priority = INFRA_PRIORITY.get(typ, 0)
        if priority > 0:
            port = mac_to_port.get(mac)
            if port and priority > port_to_priority.get(port, 0):
                port_to_gateway[port]  = hn
                port_to_priority[port] = priority

    # LLDP identity can override bridge-table inferred gateway for managed devices
    if lldp_port_to_identity:
        hostname_set = {info['fm'].get('hostname', '') for info in devices.values()}
        for port, identity in lldp_port_to_identity.items():
            if identity in hostname_set and port not in port_to_gateway:
                port_to_gateway[port] = identity
                print(f'  [lldp] {port} → {identity}')

    # Assign uplink_host keyed by MAC (not hostname) to handle duplicate hostnames
    uplinks: dict[str, str] = {}  # mac → uplink_host
    for info in devices.values():
        fm  = info['fm']
        mac = normalize_mac(str(fm.get('mac', '') or ''))
        hn  = str(fm.get('hostname', '') or '')
        if not hn or not mac:
            continue

        # The top-level router has no uplink
        if hn == ROUTER_HOSTNAME:
            continue

        port = mac_to_port.get(mac)

        if not port or port == 'bridgeLocal':
            # Directly on the router's bridge → uplink is the router
            uplinks[mac] = ROUTER_HOSTNAME
            continue

        gateway = port_to_gateway.get(port)
        if not gateway:
            # No known infrastructure gateway on this port → device is
            # directly wired to the router (single-device drop or unknown
            # unmanaged switch). Fall back to the top-level router.
            print(f'  [direct] {hn}: port={port} — no gateway found, assuming direct to {ROUTER_HOSTNAME}')
            uplinks[mac] = ROUTER_HOSTNAME
            continue

        if gateway == hn:
            # This device IS the gateway for its port → its uplink is the router
            uplinks[mac] = ROUTER_HOSTNAME
        else:
            uplinks[mac] = gateway

    return uplinks

# ── YAML patching ─────────────────────────────────────────────────────────────

def patch_frontmatter(raw: str, field: str, value: str) -> tuple[str, bool]:
    """Set or replace a frontmatter field. Returns (new_text, changed)."""
    fm_match = re.match(r'^(---\n)(.*?)(\n---)', raw, re.DOTALL)
    if not fm_match:
        return raw, False

    fm_text = fm_match.group(2)

    # Check if field already has the right value
    existing = re.search(rf'^{re.escape(field)}:\s*(.*)$', fm_text, re.MULTILINE)
    if existing:
        current = existing.group(1).strip()
        if current == value:
            return raw, False  # already correct
        # Replace the line
        new_fm = re.sub(
            rf'^{re.escape(field)}:.*$', f'{field}: {value}', fm_text, flags=re.MULTILINE
        )
    else:
        # Append before closing ---
        new_fm = fm_text.rstrip('\n') + f'\n{field}: {value}'

    new_raw = raw[:fm_match.start(2)] + new_fm + raw[fm_match.end(2):]
    return new_raw, True

def patch_index_base(write: bool) -> bool:
    """Add uplink_host as a type:ref field to index.base if not present."""
    if not INDEX_BASE.exists():
        print(f'  [!] index.base not found at {INDEX_BASE}', file=sys.stderr)
        return False

    raw = INDEX_BASE.read_text()

    if 'uplink_host:' in raw:
        print('  [✓] index.base already has uplink_host field')
        return False

    # Insert after proxmox_host block (which ends with "edgeLabel: hosted-on")
    uplink_block = (
        '    uplink_host:\n'
        '      type: ref\n'
        '      target: hostname\n'
        '      edgeLabel: uplink-to\n'
    )
    if 'proxmox_host:' in raw:
        # Insert after the proxmox_host block
        insert_after = '      edgeLabel: hosted-on\n'
        if insert_after in raw:
            new_raw = raw.replace(insert_after, insert_after + uplink_block, 1)
        else:
            new_raw = raw.replace('proxmox_host:\n', 'proxmox_host:\n', 1)
            new_raw = raw  # fallback: don't modify
    else:
        new_raw = raw

    changed = new_raw != raw
    if changed:
        print('  [+] index.base: adding uplink_host ref field')
        if write:
            INDEX_BASE.write_text(new_raw)
    return changed

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--write', action='store_true', help='Write changes (default: dry run)')
    parser.add_argument('--bridge-file', help='Use pre-captured bridge table file instead of SSH')
    parser.add_argument('--lldp-file', help='Use pre-captured LLDP neighbor file instead of SSH')
    args = parser.parse_args()

    mode = 'WRITE' if args.write else 'DRY RUN'
    print(f'\nenrich-uplinks — {mode}\n{"─"*40}')

    # Pull bridge table
    if args.bridge_file:
        raw_bridge = Path(args.bridge_file).read_text()
        print(f'  Using bridge table from {args.bridge_file}')
    else:
        print(f'  Pulling bridge table from {ROUTER_SSH}...')
        raw_bridge = fetch_bridge_table(ROUTER_SSH)

    mac_to_port = parse_bridge_table(raw_bridge)
    print(f'  {len(mac_to_port)} external MACs in bridge table')

    # Pull LLDP neighbor table
    if args.lldp_file:
        raw_lldp = Path(args.lldp_file).read_text()
        print(f'  Using LLDP table from {args.lldp_file}')
    else:
        print(f'  Pulling LLDP neighbor table from {ROUTER_SSH}...')
        raw_lldp = fetch_lldp_neighbors(ROUTER_SSH)

    lldp = parse_lldp_neighbors(raw_lldp)
    print(f'  {len(lldp)} LLDP neighbors found')

    # Load device files
    devices = load_devices()
    print(f'  {len(devices)} device files in {DEVICES_DIR.relative_to(VAULT_ROOT)}')

    # Compute uplinks
    print()
    uplinks = build_uplinks(mac_to_port, devices, lldp)

    # Report and apply
    print(f'\n  Uplink assignments ({len(uplinks)} devices):')
    changed_files: list[Path] = []

    for filename, info in sorted(devices.items()):
        fm  = info['fm']
        hn  = str(fm.get('hostname', '') or '')
        mac = normalize_mac(str(fm.get('mac', '') or ''))
        if not hn or mac not in uplinks:
            continue

        new_uplink   = uplinks[mac]
        current      = str(fm.get('uplink_host', '') or '').strip()

        if current == new_uplink:
            print(f'    = {hn}: {new_uplink} (unchanged)')
            continue

        action = f'set  ' if not current else f'{current!r} → '
        print(f'    + {hn}: {action}{new_uplink}')

        new_raw, changed = patch_frontmatter(info['raw'], 'uplink_host', new_uplink)
        if changed:
            changed_files.append((info['path'], new_raw))

    # Patch index.base
    print()
    patch_index_base(args.write)

    # Write device files
    if changed_files:
        print(f'\n  {"Writing" if args.write else "Would write"} {len(changed_files)} device file(s)')
        if args.write:
            for path, new_raw in changed_files:
                path.write_text(new_raw)
                print(f'    wrote {path.name}')
    else:
        print('  No device files to update')

    if not args.write and (changed_files or True):
        print(f'\n  Run with --write to apply changes.')

    # Report duplicate IPs — these are scan artifacts that need human review
    ip_to_files: dict[str, list[str]] = {}
    for filename, info in devices.items():
        ip = str(info['fm'].get('ip', '') or '').strip()
        if ip:
            ip_to_files.setdefault(ip, []).append(filename)
    dupes = {ip: files for ip, files in ip_to_files.items() if len(files) > 1}
    if dupes:
        print(f'\n  ⚠  {len(dupes)} duplicate IP(s) detected — likely scan artifacts:')
        for ip, files in sorted(dupes.items()):
            print(f'    {ip}: {", ".join(sorted(files))}')
        print('  Review and merge or delete the duplicate device files.')

    print()


if __name__ == '__main__':
    main()
