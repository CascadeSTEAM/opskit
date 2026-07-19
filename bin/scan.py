#!/usr/bin/env python3
"""
opskit Network Scanner — discover hosts, port scan, and update datasets.
Reads subnets and environment config from environments/<env>/env.yml.

Usage:
  bin/scan.py [--env ENV]                         # Scan active or specified env
  bin/scan.py --fixture nmap-output.xml            # Process fixture XML (CI/test)
  bin/scan.py --list                               # List available environments
  bin/scan.py --fixture nmap.xml --no-scan          # Parse only, no live nmap
"""

import argparse
import os
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(REPO_ROOT))

from bin.scanner_lib import nmap_runner, parser, dataset_writer, scaffold, enricher
import yaml


def _active_env() -> str:
    env_file = REPO_ROOT / '.env'
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if line.startswith("ACTIVE_ENV="):
                return line.split("=", 1)[1].strip().strip('"')
    return ""


def _env_path(name: str) -> Path:
    return REPO_ROOT / 'environments' / name


def _env_yml(name: str) -> Path:
    return _env_path(name) / 'env.yml'


def _datasets_dir(env_name: str) -> Path:
    return _env_path(env_name) / 'datasets'


def _load_env_config(env_name: str) -> dict:
    yml_path = _env_yml(env_name)
    if not yml_path.exists():
        raise FileNotFoundError(f"Environment '{env_name}' not found: {yml_path}")
    return yaml.safe_load(yml_path.read_text())


def _subnets_from_env(env_config: dict) -> list[str]:
    return list(env_config.get('subnets', {}).values())


def list_environments():
    envs_dir = REPO_ROOT / 'environments'
    if not envs_dir.exists():
        return
    for d in sorted(envs_dir.iterdir()):
        if d.is_dir() and (d / 'env.yml').exists():
            print(f"  {d.name}")


def scan_env(env_name: str, fixture_xml: str | None = None, dry_run: bool = False):
    config = _load_env_config(env_name)
    subnets = _subnets_from_env(config)
    ds_dir = _datasets_dir(env_name)

    if not subnets:
        print(f"  No subnets configured for '{env_name}' in env.yml")
        return

    print(f"  Environment: {config.get('display_name', env_name)} ({env_name})")
    print(f"  Subnets: {', '.join(subnets)}")

    if fixture_xml:
        print(f"  Mode: fixture (using {fixture_xml})")
        hosts = parser.parse_portscan(fixture_xml)
    else:
        print("  Mode: live nmap scan")
        if dry_run:
            print("  [DRY RUN] Would run: nmap -sn " + " ".join(subnets))
            return
        discovery_xml = nmap_runner.run_discovery(subnets)
        if not discovery_xml:
            print("  ERROR: nmap discovery failed")
            return
        hosts = parser.parse_discovery(discovery_xml)
        if hosts:
            portscan_xml = nmap_runner.run_portscan([h['ip'] for h in hosts if h['status'] == 'up'])
            if portscan_xml:
                hosts = parser.parse_portscan(portscan_xml, hosts)

    print(f"  Discovered {len(hosts)} hosts")

    # Ensure dataset directory exists
    devices_dir = ds_dir / 'devices'
    devices_dir.mkdir(parents=True, exist_ok=True)

    # Write device YAMLs
    dataset_writer.write_devices(hosts, ds_dir, env_name)

    # Enrich (relationships, uplinks)
    enricher.enrich_dataset(ds_dir)

    print(f"  Done — datasets written to {ds_dir}")


def main():
    parser = argparse.ArgumentParser(description="opskit Network Scanner")
    parser.add_argument('--env', help='Environment name (default: ACTIVE_ENV from .env)')
    parser.add_argument('--fixture', help='Path to nmap XML fixture (CI/test mode)')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be scanned, no network access')
    parser.add_argument('--list', action='store_true', help='List available environments')
    args, _ = parser.parse_known_args()

    if args.list:
        print("Available environments:")
        list_environments()
        sys.exit(0)

    env_name = args.env or _active_env()
    if not env_name:
        print("ERROR: No environment specified and ACTIVE_ENV not set.", file=sys.stderr)
        print("Run: bin/switch-env.sh <env>  or  bin/scan.py --env <env>", file=sys.stderr)
        sys.exit(1)

    env_yml = _env_yml(env_name)
    if not env_yml.exists():
        print(f"ERROR: Environment '{env_name}' not found: {env_yml}", file=sys.stderr)
        sys.exit(1)

    scan_env(env_name, fixture_xml=args.fixture, dry_run=args.dry_run)


if __name__ == '__main__':
    main()
