#!/usr/bin/env python3
"""Generate a network-architecture fact sheet for the active environment.

Sources, in order:
  1. environments/<env>/datasets/devices/*.yml — the canonical device records
  2. /tmp/*-network-facts.yml — optional per-node output of
     ansible/playbooks/gather-network-facts.yml, merged in when present

Output goes to environments/<env>/context/network-architecture.md — the
gitignored context layer. Real topology is environment data and never belongs
in the public repo (docs/client-data-policy.md, opskit #134), so this script
holds no addresses, hostnames, or node lists of its own and never writes
into docs/.
"""

from __future__ import annotations

import os
import re
import sys
from datetime import datetime
from pathlib import Path

import yaml

BIN_DIR = Path(__file__).resolve().parent
REPO_ROOT = BIN_DIR.parent
sys.path.insert(0, str(BIN_DIR))

import active_env  # noqa: E402


def read_facts_file(filepath: Path):
    """Read one gather-network-facts output file."""
    try:
        content = filepath.read_text()
        # Remove the comment header if present
        content = re.sub(r'^# Network Facts for .*$', '', content, flags=re.MULTILINE)
        return yaml.safe_load(content)
    except Exception as e:
        print(f"Error reading {filepath}: {e}")
        return None


def get_all_facts() -> dict:
    """Facts from every node file the gather playbook left in /tmp."""
    facts = {}
    for facts_file in sorted(Path('/tmp').glob('*-network-facts.yml')):
        node_name = facts_file.stem.replace('-network-facts', '')
        data = read_facts_file(facts_file)
        if data:
            facts[node_name] = data
    return facts


def load_devices(env_dir: Path) -> dict:
    """Device records from the environment's datasets, name → record.

    Tolerates both the flat shape (top-level name/ip_address keys) and the
    scanner's nested shape (everything under a 'device' key).
    """
    devices = {}
    devices_dir = env_dir / 'datasets' / 'devices'
    if not devices_dir.is_dir():
        return devices
    for f in sorted(devices_dir.glob('*.yml')):
        try:
            data = yaml.safe_load(f.read_text())
        except Exception as e:
            print(f"  WARNING: skipping unparseable {f.name}: {e}")
            continue
        if not isinstance(data, dict):
            continue
        record = data.get('device') if isinstance(data.get('device'), dict) else data
        if record.get('_merged_into'):
            continue
        devices[record.get('name', f.stem)] = record
    return devices


def render_value(lines: list, key, value, indent=''):
    if isinstance(value, dict):
        lines.append(f"{indent}**{key}:**")
        for k, v in value.items():
            lines.append(f"{indent}  - {k}: {v}")
    elif isinstance(value, list):
        lines.append(f"{indent}**{key}:**")
        for item in value:
            lines.append(f"{indent}  - {item}")
    else:
        lines.append(f"{indent}**{key}:** {value}")


def generate_docs(env_name: str, devices: dict, facts: dict) -> str:
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    lines = [
        "# Network Architecture",
        "",
        f"**Environment:** {env_name}  ",
        f"**Auto-generated:** {now}  ",
        "**Source:** device datasets + Ansible facts gathering  ",
        "",
        "---",
        "",
        "## Devices",
        "",
    ]

    if devices:
        lines.append("| Device | IP | Role | Status | Notes |")
        lines.append("|--------|-----|------|--------|-------|")
        for name, dev in sorted(devices.items()):
            ip = dev.get('ip_address', 'N/A')
            role = dev.get('role') or dev.get('type', 'N/A')
            status = dev.get('status', 'N/A')
            notes = str(dev.get('notes', '')).replace('|', '\\|').replace('\n', ' ')[:80]
            lines.append(f"| {name} | {ip} | {role} | {status} | {notes} |")
    else:
        lines.append("_No device records found in the environment's datasets._")
    lines.append("")

    if facts:
        lines.append("## Gathered Network Facts")
        lines.append("")
        lines.append("| Node | IP Address | Gateway | DNS | Interface |")
        lines.append("|------|------------|---------|-----|-----------|")
        for node in sorted(facts):
            data = facts[node]
            row = [data.get(k, 'N/A') for k in
                   ('IP Address', 'Gateway', 'DNS Servers', 'Interface')]
            lines.append(f"| {node} | " + " | ".join(str(v) for v in row) + " |")
        lines.append("")

        lines.append("## Detailed Network Facts")
        lines.append("")
        for node in sorted(facts):
            lines.append(f"### {node}")
            lines.append("")
            for key, value in facts[node].items():
                render_value(lines, key, value)
            lines.append("")

    return "\n".join(lines) + "\n"


def main() -> int:
    repo_root = Path(os.environ.get("OPSKIT_ROOT") or REPO_ROOT)
    env_name, source = active_env.resolve(repo_root)
    if not env_name:
        print("ERROR: no active environment (set one with bin/switch-env.sh <env>).")
        return 1

    env_dir = repo_root / 'environments' / env_name
    if not env_dir.is_dir():
        print(f"ERROR: environments/{env_name}/ does not exist ({source}).")
        return 1

    devices = load_devices(env_dir)
    facts = get_all_facts()
    if not devices and not facts:
        print("No device records and no facts files found.")
        print("Populate the environment's datasets (bin/scan.py) or run:")
        print("  bin/ap.sh gather-network-facts.yml")
        return 1

    docs_content = generate_docs(env_name, devices, facts)

    context_dir = env_dir / 'context'
    context_dir.mkdir(parents=True, exist_ok=True)
    output_file = context_dir / 'network-architecture.md'
    output_file.write_text(docs_content)

    print(f"Documentation generated: {output_file}")
    print(f"   Devices documented: {len(devices)}; nodes with facts: {len(facts)}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
