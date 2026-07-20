"""
Run nmap scans against network targets.

Supports multiple scan profiles:
  - discovery: ARP ping sweep for live hosts (fast, local networks)
  - portscan: TCP fast scan on live hosts (top 100 ports)
  - full: Full port scan (slow, comprehensive)

Each profile is configurable per network type (local, vpn, wifi).
"""

import subprocess
import shutil
import os
import atexit
import uuid
from pathlib import Path
from typing import Optional

# Use project-local temp directory to avoid /tmp permission issues
_SCRIPT_DIR = Path(__file__).resolve().parent.parent
_TEMP_DIR = _SCRIPT_DIR / '.tmp'
_TEMP_DIR.mkdir(exist_ok=True)

# Track temp files for cleanup
_temp_files = []


def _cleanup():
    for f in _temp_files:
        try:
            if os.path.exists(f):
                os.unlink(f)
        except Exception:
            pass


atexit.register(_cleanup)


def _tempfile(suffix: str = '', prefix: str = 'tmp-') -> str:
    """Create a temp file path in project-local .tmp directory."""
    fname = f"{prefix}{uuid.uuid4().hex}{suffix}"
    fpath = str(_TEMP_DIR / fname)
    return fpath


def check_nmap() -> bool:
    """Returns True if nmap is installed."""
    return shutil.which('nmap') is not None


def _run(cmd: list[str], timeout: int = 300) -> tuple[str, str, int]:
    """Run a command, return (stdout, stderr, returncode)."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.stdout, r.stderr, r.returncode
    except subprocess.TimeoutExpired:
        return "", "TIMEOUT", -1
    except FileNotFoundError:
        return "", "nmap not found", -1


def discover(network: str, use_sudo: bool = False,
             exclude: Optional[list[str]] = None,
             timeout: int = 0) -> Optional[str]:
    """
    Run a ping/ARP sweep to discover live hosts.

    Returns path to XML result file, or None on failure.

    timeout=0 means auto-calculate: 60s + 1s per 200 addresses
    (e.g. /24 → 60s, /16 → 380s, /12 → 3600s).
    """
    if not check_nmap():
        print("  ERROR: nmap not installed")
        return None

    # Auto-calculate timeout from subnet size
    if timeout == 0:
        import ipaddress
        try:
            net = ipaddress.ip_network(network, strict=False)
            count = net.num_addresses
            timeout = max(60, min(3600, 60 + count // 200))
            if count > 65536:
                print(f"  ! {network} is {count:,} addresses — this will take a while")
                print(f"    Consider narrowing subnets or using --timeout")
        except ValueError:
            timeout = 120

    result_file = _tempfile(suffix='.xml', prefix='nmap-disc-')
    _temp_files.append(result_file)
    cmd = ['nmap', '-sn', '--max-rtt-timeout', '300ms', '--max-retries', '1',
           '-oX', result_file, network]
    if exclude:
        cmd.extend(['--exclude', ','.join(exclude)])

    if use_sudo:
        cmd.insert(0, 'sudo')

    print(f"  nmap discovery: {network}")
    stdout, stderr, rc = _run(cmd, timeout=timeout)
    if rc != 0:
        print(f"  nmap discovery failed (rc={rc}): {stderr[:200]}")
        return None

    # Quick sanity: check XML has hosts
    import xml.etree.ElementTree as ET
    try:
        tree = ET.parse(result_file)
        root = tree.getroot()
        count = len(root.findall('.//host'))
        print(f"  Discovered {count} live hosts")
    except Exception as e:
        print(f"  Warning: could not parse nmap output: {e}")

    return result_file


def portscan(targets: list[str], use_sudo: bool = False,
             profile: str = 'fast', timeout: int = 180) -> Optional[str]:
    """
    Run a TCP port scan on discovered targets.

    Profiles:
      - fast: top 100 ports (-F)
      - common: top 1000 ports (default)
      - full: all ports (-p-)

    Returns path to XML result file, or None on failure.
    """
    if not check_nmap():
        print("  ERROR: nmap not installed")
        return None
    if not targets:
        print("  No targets to scan")
        return None

    result_file = _tempfile(suffix='.xml', prefix='nmap-port-')
    _temp_files.append(result_file)
    cmd = ['nmap', '-sT', '-oX', result_file, '--open', '--reason']

    if profile == 'fast':
        cmd.append('-F')
    elif profile == 'full':
        cmd.append('-p-')

    if use_sudo:
        cmd.insert(0, 'sudo')

    cmd.extend(targets)

    # Rate-limit for remote networks, fast for local
    print(f"  nmap portscan ({profile}): {len(targets)} targets")
    stdout, stderr, rc = _run(cmd, timeout=timeout)
    if rc != 0:
        print(f"  nmap portscan failed (rc={rc}): {stderr[:200]}")
        return None

    return result_file


def get_device_ref_map(dataset_path: Path) -> tuple[dict[str, dict], dict[str, str]]:
    """
    Read existing device files from a dataset.

    Returns (hostname_map, ip_to_hostname).
      hostname_map: hostname → device info
      ip_to_hostname: ip → hostname (for matching scan results to existing devices)
    """
    """
    Read existing device files from a dataset and return a map of
    hostname → device info for intelligent merging.
    """
    import yaml
    devices_dir = dataset_path / 'devices'
    hostname_map = {}
    ip_to_hostname = {}
    if not devices_dir.exists():
        return hostname_map, ip_to_hostname
    for f in sorted(devices_dir.glob('*.yml')):
        try:
            with open(f) as fh:
                data = yaml.safe_load(fh)
            if data and 'device' in data:
                dev = data['device']
                hostname = dev.get('hostname', f.stem)
                existing_ips = [
                    iface.get('ipv4', '').split('/')[0]
                    for iface in dev.get('networking', {}).get('interfaces', [])
                    if iface.get('ipv4')
                ]
                hostname_map[hostname] = {
                    'file': f.name,
                    'maturity': dev.get('metadata', {}).get('maturity', 'L1'),
                    'existing_ips': existing_ips,
                    'source': dev.get('metadata', {}).get('source', 'manual'),
                }
                for ip in existing_ips:
                    ip_to_hostname[ip] = hostname
        except Exception:
            pass
    return hostname_map, ip_to_hostname
