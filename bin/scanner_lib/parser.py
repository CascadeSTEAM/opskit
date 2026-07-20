"""
Parse nmap XML output into structured device data.

Output format:
[
    {
        'ip': '192.0.2.1',
        'mac': 'AA:BB:CC:00:00:97',
        'vendor': 'Routerboard.com',
        'hostname': 'router.example.local',
        'status': 'up',
        'ports': [
            {'port': 22, 'protocol': 'tcp', 'service': 'ssh', 'state': 'open'},
        ],
        'os_guess': '',
    },
    ...
]
"""

import xml.etree.ElementTree as ET
from typing import Optional


def parse_discovery(xml_path: str) -> list[dict]:
    """Parse nmap -sn (ping sweep) XML output."""
    tree = ET.parse(xml_path)
    root = tree.getroot()
    hosts = []

    for h in root.findall('.//host'):
        ip_el = h.find('.//address[@addrtype="ipv4"]')
        mac_el = h.find('.//address[@addrtype="mac"]')
        hostname_el = h.find('.//hostname')
        status_el = h.find('.//status')

        if ip_el is None:
            continue

        device = {
            'ip': ip_el.get('addr'),
            'mac': mac_el.get('addr') if mac_el is not None else '',
            'vendor': mac_el.get('vendor') if mac_el is not None else '',
            'hostname': hostname_el.get('name') if hostname_el is not None else '',
            'status': status_el.get('state') if status_el is not None else 'unknown',
            'ports': [],
            'os_guess': '',
        }
        hosts.append(device)

    return hosts


def parse_portscan(xml_path: str, existing_hosts: Optional[list[dict]] = None) -> list[dict]:
    """
    Parse nmap port scan XML output.
    Merges port info into existing_hosts if provided, otherwise returns fresh data.
    """
    tree = ET.parse(xml_path)
    root = tree.getroot()

    # Build lookup by IP from existing discovery data
    existing_by_ip = {}
    if existing_hosts:
        for h in existing_hosts:
            existing_by_ip[h['ip']] = h

    hosts = []
    for h in root.findall('.//host'):
        ip_el = h.find('.//address[@addrtype="ipv4"]')
        if ip_el is None:
            continue
        ip = ip_el.get('addr')

        # Start with existing data or fresh record
        if ip in existing_by_ip:
            device = existing_by_ip[ip]
        else:
            mac_el = h.find('.//address[@addrtype="mac"]')
            hostname_el = h.find('.//hostname')
            device = {
                'ip': ip,
                'mac': mac_el.get('addr') if mac_el is not None else '',
                'vendor': mac_el.get('vendor') if mac_el is not None else '',
                'hostname': hostname_el.get('name') if hostname_el is not None else '',
                'status': 'up',
                'ports': [],
                'os_guess': '',
            }

        # Parse ports
        ports = h.findall('.//port')
        for p in ports:
            port_id = p.get('portid')
            protocol = p.get('protocol', 'tcp')
            state_el = p.find('state')
            service_el = p.find('service')
            if state_el is None:
                continue
            port_info = {
                'port': int(port_id) if port_id else 0,
                'protocol': protocol,
                'service': service_el.get('name', '') if service_el is not None else '',
                'state': state_el.get('state', 'unknown'),
            }
            # Only include open ports
            if port_info['state'] == 'open':
                device['ports'].append(port_info)

        # OS detection (if available)
        os_el = h.find('.//osmatch')
        if os_el is not None:
            device['os_guess'] = os_el.get('name', '')

        if ip not in existing_by_ip:
            hosts.append(device)

    return hosts


def merge_results(discovery_hosts: list[dict], portscan_hosts: list[dict]) -> list[dict]:
    """Merge discovery and portscan results into a single list."""
    by_ip = {}
    for h in discovery_hosts:
        by_ip[h['ip']] = h
    for h in portscan_hosts:
        if h['ip'] in by_ip:
            by_ip[h['ip']]['ports'] = h.get('ports', [])
            if h.get('os_guess'):
                by_ip[h['ip']]['os_guess'] = h['os_guess']
            if h.get('hostname') and not by_ip[h['ip']]['hostname']:
                by_ip[h['ip']]['hostname'] = h['hostname']
        else:
            by_ip[h['ip']] = h
    return list(by_ip.values())


def classify_device(host: dict) -> str:
    """Guess device type from ports and vendor."""
    vendor = (host.get('vendor') or '').lower()
    ports = {p['port']: p['service'] for p in host.get('ports', [])}

    if vendor in ('routerboard.com',):
        return 'router' if 80 in ports or 443 in ports else 'switch'
    if vendor in ('ubiquiti networks',):
        return 'switch'
    if 22 in ports and 53 in ports:
        return 'lxc'  # likely DNS container
    if 3389 in ports or 5900 in ports:
        return 'workstation'
    if 80 in ports:
        if 443 in ports:
            return 'server'
        return 'other'  # could be printer, camera, etc.
    if 23 in ports:
        return 'ups'  # telnet often on UPS/power devices
    if 22 in ports:
        return 'lxc'  # SSH-only: likely container
    if ports:
        return 'server'

    return 'other'
