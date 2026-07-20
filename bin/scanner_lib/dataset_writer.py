"""
Write scanned device data into a dataset's YAML files.

Merges with existing device files:
  - New devices: created at L1 maturity
  - Existing devices: updated monitoring fields only (preserves manual data)
  - IPAM: updated with discovered IPs, MACs, vendors
  - Services: updated with detected services
"""

import ipaddress
import yaml
from pathlib import Path
from datetime import date
from typing import Optional

from .parser import classify_device

# Fields that should be updated by scan vs preserved from manual entry
SCAN_UPDATE_FIELDS = {'monitoring', 'system.os', 'system.firmware'}
PRESERVED_FIELDS = {'access', 'metadata.created', 'metadata.created_by',
                    'config_backup', 'dependencies', 'physical_connections',
                    'power', 'description'}


def _today() -> str:
    return date.today().isoformat()


def load_exclusions(ds_path: Path) -> list:
    """CIDRs under network.exclude_cidrs in the dataset's network.yml.

    These are addresses REACHABLE from this network but belonging to a
    different environment's dataset (e.g. Cascade STEAM's 10.99.10.0/24 is
    visible across the BMS WireGuard route and sits inside BMS's 10.99.0.0/16
    — scanning it from BMS must not file CS hosts into the BMS dataset).
    """
    net_file = ds_path / 'network.yml'
    if not net_file.exists():
        return []
    try:
        with open(net_file) as fh:
            net = (yaml.safe_load(fh) or {}).get('network', {})
        return [ipaddress.ip_network(c) for c in net.get('exclude_cidrs', [])]
    except Exception as exc:
        print(f"  WARNING: could not read exclude_cidrs from {net_file}: {exc}")
        return []


def is_excluded(ip: str, exclusions: list) -> bool:
    if not ip or not exclusions:
        return False
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return any(addr in net for net in exclusions)


def filter_excluded_hosts(hosts: list[dict], ds_path: Path) -> list[dict]:
    """Drop scanned hosts whose IP falls in an excluded CIDR, with a warning."""
    exclusions = load_exclusions(ds_path)
    if not exclusions:
        return hosts
    kept = []
    dropped = 0
    for h in hosts:
        if is_excluded(h.get('ip', ''), exclusions):
            dropped += 1
        else:
            kept.append(h)
    if dropped:
        cidrs = ', '.join(str(n) for n in exclusions)
        print(f"  Excluded {dropped} host(s) in out-of-scope CIDRs ({cidrs}) — "
              f"they belong to a different environment's dataset")
    return kept


def _hostname_safe(name: str) -> str:
    """Create a safe hostname from IP or DNS name."""
    if not name:
        return ''
    # If it looks like an IP, use prefix
    if name.count('.') == 3:
        return ''
    # Take first part of DNS name, sanitize
    safe = name.split('.')[0].lower()
    safe = ''.join(c for c in safe if c.isalnum() or c in '-_')
    return safe


def _guess_hostname(host: dict) -> str:
    """Best-effort hostname from scan data."""
    if host.get('hostname'):
        name = _hostname_safe(host['hostname'])
        if name:
            return name
    # Fallback: use IP-based name
    ip = host.get('ip', '')
    if ip:
        return f"host-{ip.replace('.', '-')}"
    return f"unknown-{hash(str(host)) % 10000}"


def _device_from_scan(host: dict, dataset_name: str, scan_source: str) -> dict:
    """Create a minimal L1 device dict from scan data.
    
    If host['_existing_hostname'] is set, uses that hostname for IP-based matching.
    """
    hostname = host.get('_existing_hostname', '') or _guess_hostname(host)
    device_type = classify_device(host)
    fqdn = host.get('hostname', '') or f"{hostname}.local"
    scan_ip = host.get('ip', '')
    device = {
        'device': {
            'hostname': hostname,
            'fqdn': fqdn,
            'type': device_type,
            'status': 'discovered',
            'networks': [dataset_name],
            'networking': {
                'interfaces': [
                    {
                        'name': 'eth0',
                        'type': 'physical',
                        'mac': host.get('mac', ''),
                        'ipv4': f"{scan_ip}/24",
                        'dhcp': 'unknown',
                        'status': 'up' if host.get('status') == 'up' else 'unknown',
                    }
                ]
            },
            'system': {
                'os': host.get('os_guess', ''),
            },
            'access': {'methods': []},
            'monitoring': {
                'reachable': host.get('status') == 'up',
                'ping_response': host.get('status') == 'up',
                'last_seen': _today(),
                'last_scan': _today(),
            },
            'metadata': {
                'created': _today(),
                'created_by': 'bms-scanner',
                'updated': _today(),
                'updated_by': 'bms-scanner',
                'source': scan_source,
                'maturity': 'L1',
            },
        }
    }
    return device


def write_device_file(device: dict, devices_dir: Path) -> str:
    """
    Write a device YAML file. Returns the filename.
    Merges with existing file if one exists (preserves higher-maturity fields).
    """
    hostname = device['device']['hostname']
    filepath = devices_dir / f"{hostname}.yml"

    existing = {}
    if filepath.exists():
        with open(filepath) as fh:
            existing = yaml.safe_load(fh) or {}

    if existing:
        # Merge: scan updates monitoring fields, preserves manual data
        merged = existing
        scan = device

        # Update monitoring
        if 'monitoring' in scan.get('device', {}):
            merged.setdefault('device', {}).setdefault('monitoring', {})
            merged['device']['monitoring'].update(scan['device']['monitoring'])

        # Update OS if scan has better info
        scan_os = scan.get('device', {}).get('system', {}).get('os')
        if scan_os and not merged.get('device', {}).get('system', {}).get('os'):
            merged.setdefault('device', {}).setdefault('system', {})
            merged['device']['system']['os'] = scan_os

        # Add new interfaces (by MAC) if not already present
        scan_interfaces = scan.get('device', {}).get('networking', {}).get('interfaces', [])
        existing_interfaces = merged.get('device', {}).get('networking', {}).get('interfaces', [])
        existing_macs = {i.get('mac', '') for i in existing_interfaces if i.get('mac')}

        for iface in scan_interfaces:
            mac = iface.get('mac', '')
            if mac and mac not in existing_macs:
                existing_interfaces.append(iface)
                existing_macs.add(mac)

        # Update metadata
        merged.setdefault('device', {}).setdefault('metadata', {})
        merged['device']['metadata']['updated'] = _today()
        merged['device']['metadata']['updated_by'] = 'bms-scanner'

        device = merged
    else:
        # New device: ensure devices_dir exists
        devices_dir.mkdir(parents=True, exist_ok=True)

    with open(filepath, 'w') as fh:
        yaml.dump(device, fh, default_flow_style=False, sort_keys=False, allow_unicode=True)

    if existing:
        print(f"  Updated: {hostname} (was L{existing.get('device', {}).get('metadata', {}).get('maturity', '?')})")
    else:
        print(f"  Created: {hostname} (L1)")

    return filepath.name


def update_ipam(hosts: list[dict], ipam_path: Path, dataset_name: str) -> None:
    """
    Update IPAM with discovered hosts.
    Merges with existing IPAM — adds new entries, updates MAC/vendor on existing.
    """
    existing = {'ipam': {'allocations': []}}
    if ipam_path.exists():
        with open(ipam_path) as fh:
            raw = yaml.safe_load(fh) or {}
            # Support both {ipam: {allocations: ...}} and flat {allocations: ...}
            if 'ipam' in raw:
                existing['ipam'] = raw['ipam']
            else:
                existing['ipam'] = raw

    allocations = existing['ipam'].setdefault('allocations', [])
    existing_ips = {a['ip']: a for a in allocations
                    if isinstance(a.get('ip'), str) and '.' in a['ip']}

    new_count = 0
    update_count = 0
    for host in hosts:
        ip = host.get('ip', '')
        if not ip:
            continue

        hostname = _guess_hostname(host)
        device_ref = f"devices/{hostname}" if hostname else ""

        if ip in existing_ips:
            entry = existing_ips[ip]
            # Update MAC and vendor if scan has them and entry doesn't
            if host.get('mac') and not entry.get('mac'):
                entry['mac'] = host['mac']
                entry['vendor'] = host.get('vendor', '')
                update_count += 1
            # Update source if entry was manual
            if entry.get('source') == 'manual' and entry.get('mac', '') != host.get('mac', ''):
                pass  # Don't override manual entries
            else:
                entry['source'] = 'nmap-scan'
        else:
            # New IP — add as discovered
            new_entry = {
                'ip': ip,
                'hostname': hostname,
                'device_ref': device_ref,
                'type': 'dhcp',
                'status': 'allocated',
                'purpose': f"Discovered by nmap scan — {classify_device(host)}",
                'source': 'nmap-scan',
            }
            if host.get('mac'):
                new_entry['mac'] = host['mac']
            if host.get('vendor'):
                new_entry['vendor'] = host['vendor']
            if host.get('hostname'):
                new_entry['notes'] = f"DNS: {host['hostname']}"

            allocations.append(new_entry)
            new_count += 1

    # Update IPAM header
    existing['ipam']['network'] = existing['ipam'].get('network', dataset_name)
    existing['ipam']['last_updated'] = _today()

    ipam_path.parent.mkdir(parents=True, exist_ok=True)
    with open(ipam_path, 'w') as fh:
        yaml.dump(existing, fh, default_flow_style=False, sort_keys=False, allow_unicode=True)

    print(f"  IPAM: {new_count} new, {update_count} updated")


def update_services(hosts: list[dict], services_path: Path) -> None:
    """
    Update services.yml with port-based service detection.
    Only adds services for well-known ports.
    """
    # Known service mapping: port -> service info
    KNOWN_SERVICES = {
        22: {'name': 'SSH', 'type': 'infrastructure'},
        53: {'name': 'DNS', 'type': 'infrastructure'},
        80: {'name': 'HTTP', 'type': 'web'},
        443: {'name': 'HTTPS', 'type': 'web'},
        3000: {'name': 'Web App (3000)', 'type': 'web'},
        3128: {'name': 'Squid Proxy', 'type': 'proxy'},
        3389: {'name': 'RDP', 'type': 'remote-access'},
        5900: {'name': 'VNC', 'type': 'remote-access'},
        8000: {'name': 'Web App (8000)', 'type': 'web'},
        8080: {'name': 'HTTP Alt', 'type': 'web'},
        8443: {'name': 'HTTPS Alt', 'type': 'web'},
        9090: {'name': 'Prometheus', 'type': 'monitoring'},
        11434: {'name': 'Ollama', 'type': 'ai_inference'},
    }

    existing = {'services': []}
    if services_path.exists():
        with open(services_path) as fh:
            existing = yaml.safe_load(fh) or {'services': []}

    existing_names = {s['name'] for s in existing.get('services', []) if s.get('name')}
    new_services = []

    for host in hosts:
        hostname = _guess_hostname(host)
        for port_info in host.get('ports', []):
            port = port_info['port']
            if port in KNOWN_SERVICES and KNOWN_SERVICES[port]['name'] not in existing_names:
                svc = KNOWN_SERVICES[port]
                new_svc = {
                    'name': svc['name'],
                    'type': svc['type'],
                    'protocol': 'tcp',
                    'default_port': port,
                    'endpoints': [
                        {
                            'url': f"http://{hostname}.local:{port}",
                            'device': hostname,
                            'status': 'active',
                        }
                    ],
                }
                new_services.append(new_svc)
                existing_names.add(svc['name'])

    if new_services:
        existing['services'].extend(new_services)

    services_path.parent.mkdir(parents=True, exist_ok=True)
    with open(services_path, 'w') as fh:
        yaml.dump(existing, fh, default_flow_style=False, sort_keys=False, allow_unicode=True)

    if new_services:
        print(f"  Services: {len(new_services)} new ({', '.join(s['name'] for s in new_services)})")


def write_devices(hosts: list[dict], ds_path: Path, dataset_name: str) -> None:
    """Write all discovered hosts to YAML device files, update IPAM + services."""
    devices_dir = ds_path / 'devices'
    devices_dir.mkdir(parents=True, exist_ok=True)

    hosts = filter_excluded_hosts(hosts, ds_path)
    live = [h for h in hosts if h.get('status') == 'up']

    written = 0
    for host in live:
        device = _device_from_scan(host, dataset_name, 'nmap')
        fname = write_device_file(device, devices_dir)
        if fname:
            written += 1

    print(f"  Scanner: wrote/updated {written} device files")

    # IPAM
    ipam_path = ds_path / 'ipam.yml'
    if ipam_path.exists():
        update_ipam(live, ipam_path, dataset_name)

    # Services
    services_path = ds_path / 'services.yml'
    if services_path.exists():
        update_services(live, services_path)
