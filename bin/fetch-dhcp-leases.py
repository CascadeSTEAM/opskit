#!/usr/bin/env python3
"""Cache the environment's DHCP leases beside its device dataset (opskit #145).

`opskit scan` learns hostnames only from reverse PTR, which is empty for most
LAN clients. The DNS/DHCP server knows those names — it handed them out. This
fetches them once, into a cache the enricher reads.

Fetch and enrichment are separate on purpose: enrichment then runs offline,
deterministically, and is testable against fixture lease data instead of a
live server.

    bin/fetch-dhcp-leases.py                    # active env, every scope
    bin/fetch-dhcp-leases.py --scope Default    # one scope
    bin/fetch-dhcp-leases.py --env <name>

Leases go to `environments/<env>/datasets/dhcp-leases.json`. That file records
real hostnames and addresses, so it lives in the gitignored environment layer
and never in the public repo (docs/client-data-policy.md).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

BIN_DIR = Path(__file__).resolve().parent
REPO_ROOT = BIN_DIR.parent
sys.path.insert(0, str(BIN_DIR))
sys.path.insert(0, str(REPO_ROOT))

import active_env  # noqa: E402

from bin.scanner_lib import dns_source  # noqa: E402

MCP_CALL = BIN_DIR / "mcp-call.py"
SERVER = "technitium"


def _call_tool(tool: str, **args) -> dict:
    """One Technitium MCP tool call via the sanctioned shell path."""
    cmd = [sys.executable, str(MCP_CALL), SERVER, tool]
    for key, value in args.items():
        cmd += ["--str", f"{key}={value}"]

    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(
            f"{tool} failed: {proc.stderr.strip() or proc.stdout.strip()}"
        )
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{tool} returned non-JSON output: {exc}") from exc


def _server_name(env_name: str) -> str:
    """Which configured Technitium server serves this environment."""
    return env_name


def fetch(env_name: str, scopes: list[str] | None) -> list[dict]:
    server = _server_name(env_name)

    if not scopes:
        listing = _call_tool("dhcp_list_scopes", server=server)
        if "error" in listing:
            raise RuntimeError(listing["error"])
        scopes = [s["name"] for s in listing.get("scopes", []) if s.get("name")]
        if not scopes:
            raise RuntimeError("the DHCP server reports no scopes")

    leases: list[dict] = []
    for scope in scopes:
        result = _call_tool("dhcp_list_leases", server=server, scope_name=scope)
        if "error" in result:
            raise RuntimeError(f"scope {scope}: {result['error']}")
        leases.extend(result.get("leases", []))
    return leases


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--env", help="environment name (default: active)")
    parser.add_argument("--scope", action="append", dest="scopes",
                        help="DHCP scope to fetch; repeatable (default: all)")
    args = parser.parse_args()

    env_name = args.env or active_env.resolve(REPO_ROOT)[0]
    if not env_name:
        print("ERROR: no active environment (bin/switch-env.sh <env>).", file=sys.stderr)
        return 1

    ds_path = REPO_ROOT / "environments" / env_name / "datasets"
    if not ds_path.is_dir():
        print(f"ERROR: no dataset directory at {ds_path}", file=sys.stderr)
        return 1

    try:
        leases = fetch(env_name, args.scopes)
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    cache = dns_source.write_lease_cache(ds_path, leases)
    duplicates = dns_source.find_duplicate_hostnames(leases)

    print(f"Cached {len(leases)} lease(s) to {cache}")
    if duplicates:
        print(f"\n{len(duplicates)} duplicate hostname(s) — device identity merging "
              f"cannot tell these apart:")
        for dup in duplicates:
            print(f"  {dup['hostname']}: {len(dup['macs'])} devices")
        print("Set a DHCP reservation for each so they keep stable identities.")
    print("\nRun bin/scan.py (or the enricher) to apply these to the dataset.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
