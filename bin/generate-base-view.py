#!/usr/bin/env python3
"""generate-base-view.py — Build docs/devices/index.base + index.md for an environment.

Usage:
    generate-base-view.py [<env>] [--write]

Fills the gap documented in schemas/directory-contract.md rule 4: `base-view.yml`
is optional per-environment config for "device-note generation," but nothing ever
consumed it. Some environments carry a hand-written docs/devices/index.base +
index.md in their own private repos that match its shape; others never got one.

Reads environments/<env>/base-view.yml if present (schema: views.index.title /
group_by / sort — see environments/example/base-view.yml). Falls back to the
convention already in use by the environments that have no base-view.yml at
all, so an environment needs no config to get output.

Device records come from datasets/devices/*.yml and *.md (the git-yaml source of
truth format allows either extension). A record that fails to parse is skipped
with a warning, not fatal — one bad file (e.g. a malformed baseline capture)
shouldn't block the rest of the environment's inventory.

Default is dry-run; pass --write to create the files.
"""

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

import yaml

BIN_DIR = Path(__file__).resolve().parent
REPO_ROOT = Path(os.environ.get("OPSKIT_ROOT") or BIN_DIR.parent)
ENVS_DIR = REPO_ROOT / "environments"

sys.path.insert(0, str(BIN_DIR))
import active_env  # noqa: E402

INDEX_FIELDS = ["name", "role", "status", "ip_address"]


def load_base_view(env_dir: Path) -> dict:
    base_view_file = env_dir / "base-view.yml"
    if not base_view_file.is_file():
        return {}
    data = yaml.safe_load(base_view_file.read_text())
    return data if isinstance(data, dict) else {}


def load_devices(env_dir: Path) -> dict:
    """Device records from datasets/devices/*.yml and *.md, name -> record."""
    devices = {}
    devices_dir = env_dir / "datasets" / "devices"
    if not devices_dir.is_dir():
        return devices
    files = sorted(devices_dir.glob("*.yml")) + sorted(devices_dir.glob("*.md"))
    for f in files:
        try:
            data = yaml.safe_load(f.read_text())
        except yaml.YAMLError as e:
            print(f"  WARNING: skipping unparseable {f.name}: {e}", file=sys.stderr)
            continue
        if not isinstance(data, dict):
            continue
        record = data.get("device") if isinstance(data.get("device"), dict) else data
        if record.get("_merged_into"):
            continue
        devices[record.get("name", f.stem)] = record
    return devices


def field_value(record: dict, *names, default="-"):
    for name in names:
        value = record.get(name)
        if value:
            return value
    return default


def build_index_base(title: str, sort_field: str) -> dict:
    return {
        "obsidian": True,
        "name": title,
        "fields": [{"name": name, "type": "text"} for name in INDEX_FIELDS],
        "filters": [],
        "sort": [{"field": sort_field, "order": "asc"}],
    }


def build_index_md(title: str, devices: dict, group_by: str, sort_field: str) -> str:
    now = datetime.now().strftime("%Y-%m-%d")
    lines = [f"# {title}", "", f"Auto-generated from device records. Last updated: {now}", ""]

    groups = {}
    for name, record in devices.items():
        group = record.get(group_by, "unknown")
        groups.setdefault(group, []).append((name, record))

    if not groups:
        lines.append("_No device records found in the environment's datasets._")
        lines.append("")
        return "\n".join(lines)

    for group in sorted(groups):
        lines.append(f"## {group}")
        lines.append("")
        lines.append("| Name | IP | Status | OS | Services |")
        lines.append("|------|-----|--------|----|----------|")
        for name, record in sorted(groups[group], key=lambda item: item[1].get(sort_field, item[0])):
            ip = field_value(record, "ip_address", "ip")
            status = field_value(record, "status")
            os_ = field_value(record, "os")
            services = record.get("services")
            services = ", ".join(services) if isinstance(services, list) else field_value(record, "services")
            lines.append(f"| [[{name}]] | {ip} | {status} | {os_} | {services} |")
        lines.append("")

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("env", nargs="?", help="Environment name (default: active environment)")
    parser.add_argument("--write", action="store_true", help="Write files (default: dry run)")
    args = parser.parse_args()

    repo_root = Path(os.environ.get("OPSKIT_ROOT") or REPO_ROOT)
    if args.env:
        env_name, source = args.env, "command line"
    else:
        env_name, source = active_env.resolve(repo_root)
        if not env_name:
            print("ERROR: no active environment (set one with bin/switch-env.sh <env>, or pass <env>).")
            return 1

    env_dir = repo_root / "environments" / env_name
    if not env_dir.is_dir():
        print(f"ERROR: environments/{env_name}/ does not exist ({source}).")
        return 1

    base_view = load_base_view(env_dir)
    index_view = base_view.get("views", {}).get("index", {})
    title = index_view.get("title", f"{env_name} — Device Inventory")
    group_by = index_view.get("group_by", "role")
    sort_field = index_view.get("sort", "name")

    devices = load_devices(env_dir)
    mode = "WRITE" if args.write else "DRY RUN"
    print(f"\ngenerate-base-view — {env_name} — {mode}\n{'─' * 40}")
    print(f"  title: {title}")
    print(f"  group_by: {group_by}, sort: {sort_field}")
    print(f"  devices found: {len(devices)}")
    if not devices:
        print("  (no usable device records — index will be empty)")

    docs_dir = env_dir / "docs" / "devices"
    index_base_file = docs_dir / "index.base"
    index_md_file = docs_dir / "index.md"

    index_base_content = json.dumps(build_index_base(title, sort_field), indent=2)
    index_md_content = build_index_md(title, devices, group_by, sort_field)

    print(f"  would write: {index_base_file}")
    print(f"  would write: {index_md_file}")

    if args.write:
        docs_dir.mkdir(parents=True, exist_ok=True)
        index_base_file.write_text(index_base_content + "\n")
        index_md_file.write_text(index_md_content + "\n")
        print("\nWritten.")
    else:
        print("\nDry run — pass --write to create these files.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
