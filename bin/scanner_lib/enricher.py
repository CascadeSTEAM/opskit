"""
Enrich device YAML files with cross-links, deduplication, and relationships.

After a scan, devices have raw data but no graph connectivity. This module:
  1. Deduplicates devices (same MAC or same IP → merge into one)
  2. Extracts parent-child relationships from descriptions and fields
  3. Builds bidirectional links (host → children, child → host)
  4. Links infrastructure (DNS, gateway, BMC → physical host)
  5. Links cluster peers (Docker Swarm, Proxmox cluster)
  6. Normalizes schema inconsistencies (type spelling, MAC format, duplicate interfaces)
  7. Tags unresolved scanner stubs

Usage:
  from scripts.scanner.lib.enricher import enrich_dataset
  enrich_dataset(ds_path)
"""

import re
import yaml
from pathlib import Path
from datetime import date, datetime, timezone
from collections import defaultdict
from typing import Optional


def _today() -> str:
    return date.today().isoformat()


# ─── Normalization ───────────────────────────────────────────────

def _normalize_type(dtype: str) -> str:
    """Normalize device type strings."""
    t = dtype.lower().strip()
    t = t.replace('lxc_container', 'lxc')
    t = t.replace('vm_container', 'vm')
    return t


def _clean_mac(mac: str) -> str:
    """Extract clean MAC from compound strings like 'AA:BB:CC:00:00:98,IP=10.99.0.22/16,TYPE=VETH'."""
    if not mac:
        return ''
    # Take first part before comma
    clean = mac.split(',')[0].strip()
    # Validate format XX:XX:XX:XX:XX:XX
    if re.match(r'^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$', clean):
        return clean.upper()
    return ''


def _clean_interfaces(device: dict) -> list[dict]:
    """Remove duplicate interfaces (same name+MAC) and clean MAC strings."""
    dev = device.get('device', {})
    interfaces = dev.get('networking', {}).get('interfaces', [])
    seen = set()
    cleaned = []
    for iface in interfaces:
        mac = _clean_mac(iface.get('mac', ''))
        name = iface.get('name', '')
        key = (name, mac)
        if key in seen:
            continue
        seen.add(key)
        iface = dict(iface)
        if mac:
            iface['mac'] = mac
        cleaned.append(iface)
    return cleaned


# ─── Deduplication ───────────────────────────────────────────────

def _load_all_devices(devices_dir: Path) -> dict[str, dict]:
    """Load all device YAMLs, keyed by filename stem.

    Skips already-merged tombstones (defensive; merges now delete the file)
    and WARNS about unparseable files instead of silently dropping them.
    """
    devices = {}
    for f in sorted(devices_dir.glob('*.yml')):
        try:
            with open(f) as fh:
                data = yaml.safe_load(fh)
        except Exception as exc:
            print(f"  WARNING: skipping unparseable {f.name}: {exc}")
            continue
        if not data or 'device' not in data:
            continue
        if data['device'].get('_merged_into'):
            continue  # tombstone from an older enricher version
        devices[f.stem] = data
    return devices


_STUB_NAME = re.compile(r'^host-\d+-\d+-\d+-\d+$')

# BMC pairing heuristic prefixes — site-specific convention (adjust per environment; see Phase 7 note)
_BMC_MGMT_PREFIX = '10.99.5.'
_BMC_MAIN_PREFIX = '10.99.0.'


def _count_references(name: str, devices: dict[str, dict]) -> int:
    """Count how many other devices reference *name* in dependency fields."""
    count = 0
    for other_dev in devices.values():
        deps = other_dev.get('device', {}).get('dependencies', {})
        for field in ('depends_on', 'hosted_on', 'provides_service_to', 'children'):
            refs = deps.get(field, [])
            if isinstance(refs, list) and name in refs:
                count += 1
    return count


def _has_access_config(dev: dict) -> int:
    """Return 1 if the device has human-configured access (SSH, web, API)."""
    access = dev.get('device', {}).get('access', {})
    methods = access.get('methods', [])
    creds = access.get('credentials', {})
    if methods and any(m not in ('icmp', '') for m in methods):
        return 1
    if creds and any(v for v in creds.values() if v):
        return 1
    return 0


def _last_updated_recency(dev: dict) -> int:
    """Days since last update — lower is better (more recent).

    Returns 99999 if no date found so unknowns sort last.
    """
    now = datetime.now(timezone.utc)
    for field in ('updated', 'last_seen'):
        date_str = dev.get('device', {}).get('metadata', {}).get(field, '')
        if date_str:
            try:
                d = datetime.fromisoformat(date_str)
                if d.tzinfo is None:
                    d = d.replace(tzinfo=timezone.utc)
                return (now - d).days
            except (ValueError, TypeError):
                pass
    # Try monitoring.last_seen
    ls = dev.get('device', {}).get('monitoring', {}).get('last_seen', '')
    if ls:
        try:
            d = datetime.fromisoformat(ls)
            if d.tzinfo is None:
                d = d.replace(tzinfo=timezone.utc)
            return (now - d).days
        except (ValueError, TypeError):
            pass
    return 99999


def _dedup_score(name: str, dev: dict,
                  ref_counts: dict[str, int] | None = None) -> tuple:
    """Sort key for choosing which duplicate to KEEP.

    Scoring tuple (highest wins):
      1. curated (human-named) beats scanner stub
      2. maturity level
      3. referenced by other devices (more inbound refs = more "live")
      4. has access config (SSH/web creds = human configured it)
      5. last updated recency (days since update, lower is better → negate)
      6. data volume (final tiebreaker)
    """
    is_curated = 0 if _STUB_NAME.match(name) else 1
    maturity = {'L0': 0, 'L1': 1, 'L2': 2, 'L3': 3}.get(
        dev.get('device', {}).get('metadata', {}).get('maturity', 'L0'), 0)
    refs = (ref_counts or {}).get(name, 0)
    access = _has_access_config(dev)
    recency = -_last_updated_recency(dev)  # negate so newer (lower days) = higher score
    data_vol = len(str(dev))
    return (is_curated, maturity, refs, access, recency, data_vol)


def _extract_macs(device: dict) -> set[str]:
    """Get all clean MAC addresses from a device."""
    macs = set()
    for iface in device.get('device', {}).get('networking', {}).get('interfaces', []):
        mac = _clean_mac(iface.get('mac', ''))
        if mac:
            macs.add(mac)
    return macs


def _extract_ips(device: dict) -> set[str]:
    """Get all IP addresses (without CIDR) from a device."""
    ips = set()
    for iface in device.get('device', {}).get('networking', {}).get('interfaces', []):
        ipv4 = iface.get('ipv4', '')
        if ipv4:
            ip = ipv4.split('/')[0]
            if ip:
                ips.add(ip)
    return ips


def _merge_devices(keep: dict, discard: dict) -> dict:
    """Merge discard into keep, preserving higher-quality data."""
    k = keep.get('device', {})
    d = discard.get('device', {})

    # Keep the hostname from the device with more data
    if not k.get('fqdn') and d.get('fqdn'):
        k['fqdn'] = d['fqdn']
    if not k.get('description') and d.get('description'):
        k['description'] = d['description']

    # Merge interfaces (add any from discard not in keep)
    keep_macs = {_clean_mac(i.get('mac', '')) for i in k.get('networking', {}).get('interfaces', []) if _clean_mac(i.get('mac', ''))}
    for iface in d.get('networking', {}).get('interfaces', []):
        mac = _clean_mac(iface.get('mac', ''))
        if mac and mac not in keep_macs:
            k.setdefault('networking', {}).setdefault('interfaces', []).append(iface)
            keep_macs.add(mac)

    # Merge dependencies (union)
    k_deps = k.setdefault('dependencies', {})
    d_deps = d.get('dependencies', {})
    for key in ('depends_on', 'hosted_on', 'provides_service_to', 'children'):
        if key in d_deps:
            existing = set(k_deps.get(key, []))
            existing.update(d_deps[key])
            k_deps[key] = sorted(existing)

    # Merge tags
    keep_tags = set(k.get('tags', []))
    keep_tags.update(d.get('tags', []))
    if keep_tags:
        k['tags'] = sorted(keep_tags)

    # Merge runs_services
    keep_svcs = {s.get('name'): s for s in k.get('runs_services', [])}
    for svc in d.get('runs_services', []):
        if svc.get('name') and svc['name'] not in keep_svcs:
            k.setdefault('runs_services', []).append(svc)
            keep_svcs[svc['name']] = svc

    # Keep higher maturity
    k_maturity = k.get('metadata', {}).get('maturity', 'L0')
    d_maturity = d.get('metadata', {}).get('maturity', 'L0')
    maturity_order = {'L0': 0, 'L1': 1, 'L2': 2, 'L3': 3}
    if maturity_order.get(d_maturity, 0) > maturity_order.get(k_maturity, 0):
        k.setdefault('metadata', {})['maturity'] = d_maturity

    # Update metadata
    k.setdefault('metadata', {})['updated'] = _today()
    k.setdefault('metadata', {})['updated_by'] = 'enricher'

    return keep


def deduplicate(devices_dir: Path) -> dict[str, str]:
    """
    Find and merge duplicate devices.
    Returns {discarded_filename: kept_filename} mapping.
    """
    devices = _load_all_devices(devices_dir)
    if not devices:
        return {}

    # Pre-compute inbound reference counts so _dedup_score can rank
    # curated-vs-curated ties by which name other devices actually point to.
    ref_counts: dict[str, int] = {}
    for name in devices:
        ref_counts[name] = _count_references(name, devices)

    # Build lookup indices
    mac_to_names: dict[str, list[str]] = defaultdict(list)
    ip_to_names: dict[str, list[str]] = defaultdict(list)

    for name, dev in devices.items():
        for mac in _extract_macs(dev):
            mac_to_names[mac].append(name)
        for ip in _extract_ips(dev):
            ip_to_names[ip].append(name)

    # Find duplicate groups
    merged = {}  # discard → keep
    processed = set()

    # MAC-based dedup (strongest signal)
    for mac, names in sorted(mac_to_names.items()):
        if len(names) <= 1:
            continue
        scored = [(n, _dedup_score(n, devices[n], ref_counts)) for n in names if n not in merged]
        if len(scored) <= 1:
            continue
        scored.sort(key=lambda x: x[1], reverse=True)
        keep_name = scored[0][0]
        for n, _ in scored[1:]:
            merged[n] = keep_name
            processed.add(n)

    # IP-based dedup (for pairs not caught by MAC).
    # A shared IP is a WEAK signal: VIPs, NAT, and DHCP churn all produce
    # different devices with the same address. Only merge when the MAC
    # evidence does not contradict — never merge two devices whose MAC sets
    # are both non-empty and disjoint (that's two different NICs).
    for ip, names in sorted(ip_to_names.items()):
        if len(names) <= 1:
            continue
        candidates = [n for n in names if n not in processed and n not in merged]
        if len(candidates) <= 1:
            continue
        scored = [(n, _dedup_score(n, devices[n], ref_counts)) for n in candidates]
        scored.sort(key=lambda x: x[1], reverse=True)
        keep_name = scored[0][0]
        keep_macs = _extract_macs(devices[keep_name])
        for n, _ in scored[1:]:
            other_macs = _extract_macs(devices[n])
            if keep_macs and other_macs and not (keep_macs & other_macs):
                continue  # different hardware sharing an IP — not a duplicate
            merged[n] = keep_name
            processed.add(n)

    # Resolve chains (A→B, B→C ⇒ A→C) so nothing merges into a discarded file
    def _final_keep(n: str) -> str:
        seen_chain = set()
        while n in merged and n not in seen_chain:
            seen_chain.add(n)
            n = merged[n]
        return n

    merged = {d: _final_keep(k) for d, k in merged.items()}

    # Apply merges: fold discard into keep, write keep, DELETE discard.
    # The discarded content lives on in the keep file and in git history —
    # leaving tombstone files behind re-enters them into every later phase.
    for discard_name, keep_name in merged.items():
        keep_path = devices_dir / f"{keep_name}.yml"
        discard_path = devices_dir / f"{discard_name}.yml"
        if not keep_path.exists() or not discard_path.exists():
            continue

        keep_dev = devices[keep_name]
        discard_dev = devices[discard_name]
        _merge_devices(keep_dev, discard_dev)

        with open(keep_path, 'w') as fh:
            yaml.dump(keep_dev, fh, default_flow_style=False, sort_keys=False, allow_unicode=True)
        discard_path.unlink()

    return merged


# ─── Relationship Extraction ─────────────────────────────────────

# Patterns for extracting parent-child from descriptions
_CT_ON_HOST = re.compile(
    r'(?:LXC|CT|VM|container)\s*(?:#?\s*)?(\d+)\s+on\s+(\w+)',
    re.IGNORECASE
)
_CT_NUMBER = re.compile(
    r'(?:LXC|CT|VM|container)\s*(?:#?\s*)?(\d+)',
    re.IGNORECASE
)
_ON_HOST = re.compile(
    r'\bon\s+(\w+)\b',
    re.IGNORECASE
)
_DOCKER_SWARM = re.compile(r'docker\s+swarm', re.IGNORECASE)
_DOCKER_NODE = re.compile(r'docker\s+(?:swarm\s+)?node', re.IGNORECASE)

# Words after "on" that are never hostnames
_PARENT_STOPWORDS = {
    'on', 'the', 'a', 'an', 'is', 'at', 'in', 'for', 'with',
    'docker', 'port', 'demand', 'boot', 'standby', 'node', 'all',
    'this', 'that', 'same', 'local', 'swarm', 'wifi', 'battery',
}


def _extract_parent_from_description(device: dict) -> tuple[Optional[str], Optional[str]]:
    """Try to extract (parent_host, ct_number) from description."""
    desc = device.get('device', {}).get('description', '')
    if not desc:
        return None, None

    m = _CT_ON_HOST.search(desc)
    if m:
        return m.group(2).lower(), m.group(1)

    # Try just "on <host>"
    m = _ON_HOST.search(desc)
    if m:
        host = m.group(1).lower()
        # Filter out common false positives ("on Docker", "on port 53", ...)
        if host not in _PARENT_STOPWORDS:
            # Try to find CT number separately
            m2 = _CT_NUMBER.search(desc)
            ct = m2.group(1) if m2 else None
            return host, ct

    return None, None


def _extract_parent_from_fields(device: dict) -> Optional[str]:
    """Get parent from hosted_on ONLY.

    Never infer a parent from depends_on: Phase 5 of this very tool appends
    gateway/DNS entries there, so depends_on[0] made physical hypervisors
    "hosted_on" the router on re-runs (2026-07-14 dataset corruption).
    """
    hosted = device.get('device', {}).get('dependencies', {}).get('hosted_on', [])
    if hosted:
        return hosted[0]
    return None


def _is_host_type(dtype: str) -> bool:
    """Is this device type a host that runs containers/VMs?"""
    return dtype in ('hypervisor', 'server')


def _is_container_type(dtype: str) -> bool:
    """Is this device type a container or VM?"""
    return dtype in ('lxc', 'vm')


# ─── Infrastructure Linking ──────────────────────────────────────

def _get_dns_servers(device: dict) -> list[str]:
    """Extract DNS server IPs from device interfaces."""
    servers = []
    for iface in device.get('device', {}).get('networking', {}).get('interfaces', []):
        for dns in iface.get('dns', []):
            if dns not in servers:
                servers.append(dns)
    return servers


def _get_gateway(device: dict) -> Optional[str]:
    """Extract default gateway from device interfaces."""
    for iface in device.get('device', {}).get('networking', {}).get('interfaces', []):
        gw = iface.get('gateway')
        if gw:
            return gw
    return None


# ─── Main Enrichment ─────────────────────────────────────────────

def enrich_dataset(ds_path: Path) -> dict:
    """
    Run full enrichment on a dataset directory.
    Returns summary dict with counts of changes.
    """
    devices_dir = ds_path / 'devices'
    if not devices_dir.exists():
        return {'error': 'No devices directory'}

    summary = {
        'dedup_merged': 0,
        'dedup_pairs': [],
        'parent_child_links': 0,
        'infra_links': 0,
        'type_normalized': 0,
        'interfaces_cleaned': 0,
        'stubs_tagged': 0,
        'swarm_links': 0,
        'bmc_links': 0,
    }

    # Phase 1: Deduplication
    merged = deduplicate(devices_dir)
    summary['dedup_merged'] = len(merged)
    summary['dedup_pairs'] = [(d, k) for d, k in merged.items()]

    # Phase 2: Load all devices (post-dedup)
    devices = _load_all_devices(devices_dir)

    # Snapshot originals: Phase 9 writes only files whose content actually
    # changed (rewriting ~100 curated YAMLs every run churns git and invites
    # merge conflicts with humans editing the same files).
    def _dump(dev: dict) -> str:
        return yaml.dump(dev, default_flow_style=False, sort_keys=False, allow_unicode=True)

    originals = {name: _dump(dev) for name, dev in devices.items()}

    # Remap references from merged-away names onto the kept names — the
    # discarded files are gone, so dangling refs would otherwise be dropped
    # by Phase 8 instead of following the merge.
    if merged:
        ref_keys = ('depends_on', 'hosted_on', 'provides_service_to', 'children', 'peers')
        for name, dev in devices.items():
            deps = dev.get('device', {}).get('dependencies', {})
            for key in ref_keys:
                if key in deps:
                    remapped = []
                    for ref in deps[key]:
                        ref = merged.get(ref, ref)
                        if ref != name and ref not in remapped:
                            remapped.append(ref)
                    deps[key] = remapped

    # Phase 3: Normalize types and clean interfaces
    for name, dev in devices.items():
        dtype = dev.get('device', {}).get('type', '')
        normalized = _normalize_type(dtype)
        if normalized != dtype:
            dev['device']['type'] = normalized
            summary['type_normalized'] += 1

        cleaned = _clean_interfaces(dev)
        orig_count = len(dev.get('device', {}).get('networking', {}).get('interfaces', []))
        if len(cleaned) < orig_count:
            dev['device']['networking']['interfaces'] = cleaned
            summary['interfaces_cleaned'] += orig_count - len(cleaned)

        # Tag scanner stubs (pattern-based, not hardcoded to one subnet family)
        if _STUB_NAME.match(name):
            tags = set(dev.get('device', {}).get('tags', []))
            if 'scanner-stub' not in tags:
                tags.add('scanner-stub')
                dev['device']['tags'] = sorted(tags)
                summary['stubs_tagged'] += 1

    # Phase 4: Build parent-child relationships
    # Collect all known hostnames
    all_hostnames = set(devices.keys())
    # Also add common aliases
    hostname_aliases = {}
    for name, dev in devices.items():
        fqdn = dev.get('device', {}).get('fqdn', '')
        if fqdn:
            alias = fqdn.split('.')[0].lower()
            if alias != name:
                hostname_aliases[alias] = name

    def resolve_host(h: str) -> Optional[str]:
        """Resolve a hostname deterministically.

        Exact name, then fqdn alias, then UNIQUE prefix match over a sorted
        list (min 3 chars). Ambiguity resolves to None — a wrong graph edge
        is worse than a missing one. (The old bidirectional substring match
        iterated a set: nondeterministic across runs and over-eager.)
        """
        h = h.lower()
        if h in all_hostnames:
            return h
        if h in hostname_aliases:
            return hostname_aliases[h]
        if len(h) < 3:
            return None
        matches = sorted(n for n in all_hostnames if n.startswith(h))
        return matches[0] if len(matches) == 1 else None

    # Extract parent-child from descriptions
    parent_children: dict[str, list[str]] = defaultdict(list)  # host → [children]
    child_parent: dict[str, str] = {}  # child → host

    inferred_children: set[str] = set()

    for name, dev in devices.items():
        dtype = _normalize_type(dev.get('device', {}).get('type', ''))

        # Priority 1: explicit hosted_on field (trusted as-is)
        parent = _extract_parent_from_fields(dev)
        from_description = False

        # Priority 2: inferred from prose description (guarded below)
        if not parent:
            parent, _ct = _extract_parent_from_description(dev)
            from_description = parent is not None

        if not parent:
            continue
        resolved = resolve_host(parent)
        if not resolved or resolved == name:
            continue

        if from_description:
            # Inference guard: only containers/VMs may gain a parent from
            # prose, and only a hypervisor/server may BE that parent. A
            # physical box never gets hosted_on by inference (see 2026-07-14
            # corruption: hypervisors "hosted_on" the router).
            parent_type = _normalize_type(
                devices[resolved].get('device', {}).get('type', ''))
            if not (_is_container_type(dtype) and _is_host_type(parent_type)):
                continue
            inferred_children.add(name)

        child_parent[name] = resolved
        parent_children[resolved].append(name)

    # Apply parent-child to devices
    for child, host in child_parent.items():
        dev = devices[child]
        deps = dev.get('device', {}).setdefault('dependencies', {})

        # Add hosted_on if not present
        if 'hosted_on' not in deps:
            deps['hosted_on'] = [host]
        elif host not in deps['hosted_on']:
            deps['hosted_on'].append(host)

        # Add depends_on if not present
        if 'depends_on' not in deps:
            deps['depends_on'] = [host]
        elif host not in deps['depends_on']:
            deps['depends_on'].append(host)

        # Prose-derived links are guesses — mark them so humans can tell
        # scanned fact from inference.
        if child in inferred_children:
            deps['hosted_on_inferred'] = True

        summary['parent_child_links'] += 1

    # Add children list to hosts
    for host, children in parent_children.items():
        dev = devices[host]
        deps = dev.get('device', {}).setdefault('dependencies', {})
        existing = set(deps.get('children', []))
        existing.update(children)
        deps['children'] = sorted(existing)

    # Phase 5: Infrastructure linking
    # Build IP→device map
    ip_to_device: dict[str, str] = {}
    for name, dev in devices.items():
        for ip in _extract_ips(dev):
            ip_to_device[ip] = name

    # Link devices to DNS and gateway
    for name, dev in devices.items():
        deps = dev.get('device', {}).setdefault('dependencies', {})
        dns_servers = _get_dns_servers(dev)
        gateway = _get_gateway(dev)
        own_ips = _extract_ips(dev)

        # DNS links (skip self: a DNS server lists itself as resolver)
        for dns_ip in dns_servers:
            if dns_ip in own_ips:
                continue
            target = ip_to_device.get(dns_ip)
            if target and target != name:
                existing = set(deps.get('depends_on', []))
                if target not in existing:
                    deps.setdefault('depends_on', []).append(target)
                    summary['infra_links'] += 1

        # Gateway link (skip self: routers gateway to themselves)
        if gateway and gateway not in own_ips:
            target = ip_to_device.get(gateway)
            if target and target != name:
                existing = set(deps.get('depends_on', []))
                if target not in existing:
                    deps.setdefault('depends_on', []).append(target)
                    summary['infra_links'] += 1

    # Phase 6: Docker Swarm peer linking
    swarm_nodes = []
    for name, dev in devices.items():
        desc = dev.get('device', {}).get('description', '')
        dtype = dev.get('device', {}).get('type', '')
        if _DOCKER_SWARM.search(desc) or (_DOCKER_NODE.search(desc) and dtype == 'server'):
            swarm_nodes.append(name)

    if len(swarm_nodes) > 1:
        for node in swarm_nodes:
            dev = devices[node]
            deps = dev.get('device', {}).setdefault('dependencies', {})
            peers = [n for n in swarm_nodes if n != node]
            existing = set(deps.get('peers', []))
            existing.update(peers)
            deps['peers'] = sorted(existing)
            summary['swarm_links'] += len(peers)

    # Phase 7: BMC → physical host linking.
    # SITE-SPECIFIC HEURISTIC (adjust per environment): assumes mgmt subnet _BMC_MGMT_PREFIX and
    # a same-last-octet host on _BMC_MAIN_PREFIX. Octet pairing is a guess —
    # links are marked inferred. TODO: move the prefixes to per-dataset meta
    # (network.yml) instead of module constants.
    bmc_hosts = {}  # bmc_name → physical_host_name
    for name, dev in devices.items():
        dtype = dev.get('device', {}).get('type', '')
        if dtype == 'bmc':
            for ip in _extract_ips(dev):
                if ip.startswith(_BMC_MGMT_PREFIX):
                    last_octet = ip.split('.')[-1]
                    main_ip = f"{_BMC_MAIN_PREFIX}{last_octet}"
                    if main_ip in ip_to_device:
                        bmc_hosts[name] = ip_to_device[main_ip]

    for bmc, host in bmc_hosts.items():
        dev = devices[bmc]
        deps = dev.get('device', {}).setdefault('dependencies', {})
        existing = set(deps.get('depends_on', []))
        if host not in existing:
            deps.setdefault('depends_on', []).append(host)
            deps['bmc_pairing_inferred'] = True
            summary['bmc_links'] += 1
        # Also add BMC to host's children
        host_dev = devices.get(host, {})
        host_deps = host_dev.get('device', {}).setdefault('dependencies', {})
        existing_children = set(host_deps.get('children', []))
        if bmc not in existing_children:
            host_deps.setdefault('children', []).append(bmc)

    # Phase 8: Validate — remove references to non-existent device files
    existing_files = {f.stem for f in devices_dir.glob('*.yml')}
    stale_removed = 0
    for name, dev in devices.items():
        deps = dev.get('device', {}).get('dependencies', {})
        for key in ('depends_on', 'hosted_on', 'provides_service_to', 'children', 'peers'):
            if key in deps:
                original = deps[key]
                filtered = [ref for ref in original if ref in existing_files]
                if len(filtered) < len(original):
                    deps[key] = filtered
                    stale_removed += len(original) - len(filtered)

    summary['stale_refs_removed'] = stale_removed

    # Phase 9: Write ONLY devices whose content actually changed
    written = 0
    for name, dev in devices.items():
        filepath = devices_dir / f"{name}.yml"
        if not filepath.exists():
            continue
        new_content = _dump(dev)
        if new_content != originals.get(name):
            with open(filepath, 'w') as fh:
                fh.write(new_content)
            written += 1
    summary['files_written'] = written

    return summary


def print_summary(summary: dict) -> None:
    """Print a human-readable summary of enrichment changes."""
    print(f"\n  Enrichment Summary:")
    print(f"  {'─' * 40}")

    if summary['dedup_merged']:
        print(f"  Deduplication:  {summary['dedup_merged']} duplicates merged")
        for discard, keep in summary['dedup_pairs']:
            print(f"    {discard} → {keep}")

    if summary['type_normalized']:
        print(f"  Type cleanup:   {summary['type_normalized']} normalized")

    if summary['interfaces_cleaned']:
        print(f"  Interfaces:     {summary['interfaces_cleaned']} duplicates removed")

    if summary['stubs_tagged']:
        print(f"  Scanner stubs:  {summary['stubs_tagged']} tagged")

    if summary['parent_child_links']:
        print(f"  Parent→Child:   {summary['parent_child_links']} links added")

    if summary['infra_links']:
        print(f"  Infrastructure: {summary['infra_links']} DNS/gateway links")

    if summary['swarm_links']:
        print(f"  Docker Swarm:   {summary['swarm_links']} peer links")

    if summary['bmc_links']:
        print(f"  BMC→Host:       {summary['bmc_links']} management links")

    total = (summary['dedup_merged'] + summary['parent_child_links'] +
             summary['infra_links'] + summary['swarm_links'] + summary['bmc_links'])
    if summary.get('files_written'):
        print(f"  Files written:  {summary['files_written']}")

    if total == 0 and not summary.get('files_written'):
        print(f"  No changes needed — all devices already enriched")
    else:
        print(f"  {'─' * 40}")
        print(f"  Total: {total} relationships added/fixed")
