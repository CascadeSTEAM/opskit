#!/usr/bin/env python3
"""
Technitium DNS MCP Server — Zone, record, and DHCP management across configured servers.

DNS Tools:
  dns_list_servers      List configured servers and their reachability status
  dns_list_zones        List all zones on a server
  dns_get_records       Get records for a zone (optionally filtered to a subdomain)
  dns_compare           Compare a hostname across all servers + local resolver (detects split-brain)
  dns_update_record     Add or update a record on a primary zone
  dns_delete_record     Delete a record from a primary zone
  dns_resync_zone       Force zone transfer from primary to secondary
  dns_flush_local_cache Flush systemd-resolved cache on this machine

DHCP Tools:
  dhcp_list_scopes        List all DHCP scopes on a server
  dhcp_get_scope          Get full scope details (options, exclusions, reservations)
  dhcp_list_leases        List active DHCP leases for a scope
  dhcp_add_reservation    Add a static IP reservation
  dhcp_remove_reservation Remove a static IP reservation
  dhcp_clear_static_routes Remove Option 121 static routes from a scope (fixes Android/Samsung no-internet)

Usage:
  python3 scripts/technitium-mcp-server.py            # stdio MCP server
  python3 scripts/technitium-mcp-server.py --test      # smoke-test all tools

Server configuration:
  Servers are loaded from a gitignored mcp/tenants-technitium.local.json
  (next to this script) if present; otherwise a single example server is
  used. The file maps server names to {"url", "description", "env_pass",
  "username"}:

    {
      "client1": {
        "url": "http://dns.example.local:5380",
        "description": "Example client DNS+DHCP",
        "env_pass": "TECHNITIUM_CLIENT1_PASS",
        "username": "admin"
      }
    }

Environment (or .env):
  Each server reads the password from the env var named by its "env_pass"
  key, e.g.:
  TECHNITIUM_CLIENT1_PASS=<password>
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import requests

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:
    print("ERROR: mcp package not installed. Run: pip install mcp", file=sys.stderr)
    sys.exit(1)

REPO_ROOT = Path(__file__).parent.parent.resolve()

_SERVERS_FILE = Path(__file__).parent / "tenants-technitium.local.json"


def _load_servers() -> dict:
    """Load server config from gitignored tenants-technitium.local.json, else example fallback."""
    if _SERVERS_FILE.exists():
        return json.loads(_SERVERS_FILE.read_text())
    return {
        "client1": {
            "url": "http://dns.example.local:5380",
            "description": "Example client DNS+DHCP",
            "env_pass": "TECHNITIUM_CLIENT1_PASS",
            "username": "admin",
        },
    }


SERVERS = _load_servers()

mcp = FastMCP("technitium-dns")


def load_env():
    env_file = REPO_ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k, v)


class TechnitiumClient:
    def __init__(self, server_name: str):
        cfg = SERVERS[server_name]
        self.server_name = server_name
        self.base_url = cfg["url"].rstrip("/")
        self.username = cfg["username"]
        password = os.environ.get(cfg["env_pass"], "")
        if not password:
            raise RuntimeError(
                f"Password for '{server_name}' not set. "
                f"Add {cfg['env_pass']} to .env or export it."
            )
        self.password = password
        self.token: str = ""
        self._login()

    def _login(self):
        resp = requests.get(
            f"{self.base_url}/api/user/login",
            params={"user": self.username, "pass": self.password, "includeToken": "true"},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("status") != "ok":
            raise RuntimeError(
                f"Login to '{self.server_name}' failed: {data.get('errorMessage', resp.text)}"
            )
        self.token = data["token"]

    def _call(self, method: str, endpoint: str, params: dict = None) -> dict:
        all_params = {"token": self.token, **(params or {})}
        fn = requests.get if method == "GET" else requests.post
        resp = fn(f"{self.base_url}/api/{endpoint}", params=all_params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        if data.get("status") == "error":
            err = data.get("errorMessage", "")
            if "token" in err.lower() or "session" in err.lower():
                self._login()
                return self._call(method, endpoint, params)
            raise RuntimeError(f"Technitium API error on {self.server_name}: {err}")
        return data

    def get(self, endpoint: str, params: dict = None) -> dict:
        return self._call("GET", endpoint, params)

    def post(self, endpoint: str, params: dict = None) -> dict:
        return self._call("POST", endpoint, params)


_clients: dict[str, TechnitiumClient] = {}


def get_client(server: str) -> TechnitiumClient:
    if server not in SERVERS:
        raise ValueError(f"Unknown server '{server}'. Choose: {', '.join(SERVERS.keys())}")
    if server not in _clients:
        load_env()
        _clients[server] = TechnitiumClient(server)
    return _clients[server]


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

@mcp.tool()
def dns_list_servers() -> str:
    """
    List all configured DNS servers with their URLs and reachability status.
    Use this to know which server names to pass to other tools.
    """
    load_env()
    results = {}
    for name, cfg in SERVERS.items():
        ip = cfg["url"].split("//")[1].split(":")[0]
        has_pass = bool(os.environ.get(cfg["env_pass"], ""))
        try:
            r = requests.get(cfg["url"] + "/api/user/login",
                             params={"user": "healthcheck", "pass": "x"},
                             timeout=4)
            reachable = r.status_code in (200, 401, 400)
        except Exception:
            reachable = False
        results[name] = {
            "url": cfg["url"],
            "ip": ip,
            "description": cfg["description"],
            "credential_configured": has_pass,
            "reachable": reachable,
        }
    return json.dumps({"servers": results}, indent=2)


@mcp.tool()
def dns_list_zones(server: str) -> str:
    """
    List all DNS zones on a server.

    Args:
        server: Server name (see dns_list_servers for configured names)
    """
    try:
        client = get_client(server)
        data = client.get("zones/list")
        zones = data.get("response", {}).get("zones", [])
        return json.dumps({
            "server": server,
            "count": len(zones),
            "zones": [
                {"name": z["name"], "type": z.get("type"), "disabled": z.get("disabled", False)}
                for z in zones
            ],
        }, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def dns_get_records(server: str, zone: str, subdomain: str = None) -> str:
    """
    Get DNS records for a zone, optionally filtered to a specific subdomain.

    Args:
        server:    Server name (see dns_list_servers for configured names)
        zone:      Zone name (e.g. 'example.org')
        subdomain: Fully-qualified name to filter to (e.g. 'support.example.org').
                   If omitted, returns all records in the zone.
    """
    try:
        client = get_client(server)
        domain = subdomain if subdomain else zone
        data = client.get("zones/records/get", {"zone": zone, "domain": domain})
        records = data.get("response", {}).get("records", [])
        simplified = []
        for r in records:
            rdata = r.get("rData", {})
            rtype = r.get("type", "")
            if rtype == "A":
                value = rdata.get("ipAddress", str(rdata))
            elif rtype == "CNAME":
                value = rdata.get("cname", str(rdata))
            elif rtype == "NS":
                value = rdata.get("nameServer", str(rdata))
            elif rtype == "MX":
                value = f"{rdata.get('preference', 10)} {rdata.get('exchange', '')}"
            elif rtype == "TXT":
                value = rdata.get("text", str(rdata))
            elif rtype == "SRV":
                value = (f"{rdata.get('priority',0)} {rdata.get('weight',0)} "
                         f"{rdata.get('port',0)} {rdata.get('target','')}")
            elif rtype == "PTR":
                value = rdata.get("ptrName", str(rdata))
            else:
                value = str(rdata)
            simplified.append({
                "name": r.get("name"),
                "type": rtype,
                "ttl": r.get("ttl"),
                "value": value,
            })
        return json.dumps({
            "server": server,
            "zone": zone,
            "filter": subdomain or "(all)",
            "count": len(simplified),
            "records": simplified,
        }, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def dns_compare(hostname: str) -> str:
    """
    Compare DNS resolution for a hostname across ALL configured servers and the local resolver.
    Detects split-brain (servers returning different answers) without requiring authentication.
    This is the first tool to run when a DNS-related site issue is reported.

    Args:
        hostname: FQDN to check (e.g. 'support.example.org')
    """
    load_env()
    results = {}

    for name, cfg in SERVERS.items():
        server_ip = cfg["url"].split("//")[1].split(":")[0]
        try:
            r = subprocess.run(
                ["dig", f"@{server_ip}", hostname, "A", "+short", "+time=3", "+tries=1"],
                capture_output=True, text=True, timeout=6,
            )
            answers = [a.strip() for a in r.stdout.strip().splitlines()
                       if a.strip() and not a.startswith(";")]
            results[name] = {
                "server_ip": server_ip,
                "answers": answers if answers else ["NXDOMAIN"],
            }
        except Exception as e:
            results[name] = {"server_ip": server_ip, "error": str(e)}

    # Local system resolver
    try:
        r = subprocess.run(
            ["dig", hostname, "A", "+short", "+time=3"],
            capture_output=True, text=True, timeout=6,
        )
        answers = [a.strip() for a in r.stdout.strip().splitlines()
                   if a.strip() and not a.startswith(";")]
        results["local-resolver"] = {
            "server_ip": "127.0.0.53",
            "answers": answers if answers else ["NXDOMAIN"],
        }
    except Exception as e:
        results["local-resolver"] = {"server_ip": "127.0.0.53", "error": str(e)}

    # Detect split-brain
    answer_sets = [
        frozenset(v.get("answers", []))
        for v in results.values()
        if "answers" in v
    ]
    unique = [list(s) for s in set(answer_sets)]
    split_brain = len(unique) > 1

    return json.dumps({
        "hostname": hostname,
        "split_brain": split_brain,
        "consensus": unique[0] if not split_brain and unique else None,
        "results": results,
        "recommendation": (
            "Run dns_resync_zone to sync secondary from primary."
            if split_brain else "All servers agree."
        ),
    }, indent=2)


@mcp.tool()
def dns_update_record(
    server: str,
    zone: str,
    domain: str,
    record_type: str,
    value: str,
    ttl: int = 3600,
) -> str:
    """
    Add or update a DNS record on a primary zone.
    If a record with the same name and type already exists, it is replaced.
    Secondary zones are read-only — use dns_resync_zone after updating the primary.

    Args:
        server:      Server name (must be the primary server for the zone)
        zone:        Zone name (e.g. 'example.org')
        domain:      FQDN of the record (e.g. 'support.example.org')
        record_type: Record type: 'A', 'CNAME', 'TXT', 'MX', etc.
        value:       Record value (IP for A, hostname for CNAME, etc.)
        ttl:         Time-to-live in seconds (default 3600)
    """
    try:
        client = get_client(server)

        # Check current value
        try:
            current_data = client.get("zones/records/get", {"zone": zone, "domain": domain})
            current_records = [
                r for r in current_data.get("response", {}).get("records", [])
                if r.get("type") == record_type
            ]
        except Exception:
            current_records = []

        # Delete existing record of same type if present
        deleted = False
        if current_records:
            rdata = current_records[0].get("rData", {})
            old_value = (
                rdata.get("ipAddress") or rdata.get("cname") or
                rdata.get("nameServer") or str(rdata)
            )
            if old_value != value:
                client.post("zones/records/delete", {
                    "zone": zone, "domain": domain,
                    "type": record_type, "value": old_value,
                })
                deleted = True
            else:
                return json.dumps({
                    "server": server, "domain": domain,
                    "message": "Record already correct — no change needed.",
                    "current": value,
                })

        # Add the new/updated record
        add_params = {
            "zone": zone, "domain": domain,
            "type": record_type, "ttl": str(ttl),
        }
        if record_type == "A":
            add_params["ipAddress"] = value
        elif record_type == "CNAME":
            add_params["cname"] = value
        else:
            add_params["value"] = value

        client.post("zones/records/add", add_params)

        return json.dumps({
            "server": server,
            "domain": domain,
            "type": record_type,
            "value": value,
            "ttl": ttl,
            "action": "updated" if deleted else "added",
            "message": f"Record {'updated' if deleted else 'added'} successfully. "
                       "Run dns_resync_zone if this server has secondaries.",
        }, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def dns_delete_record(
    server: str,
    zone: str,
    domain: str,
    record_type: str,
    value: str,
) -> str:
    """
    Delete a specific DNS record from a primary zone.

    Args:
        server:      Server name (must be the primary server for the zone)
        zone:        Zone name (e.g. 'example.org')
        domain:      FQDN of the record (e.g. 'old.example.org')
        record_type: Record type: 'A', 'CNAME', etc.
        value:       Exact current value of the record to delete
    """
    try:
        client = get_client(server)
        client.post("zones/records/delete", {
            "zone": zone, "domain": domain,
            "type": record_type, "value": value,
        })
        return json.dumps({
            "server": server,
            "domain": domain,
            "type": record_type,
            "value": value,
            "message": "Record deleted. Run dns_resync_zone if this server has secondaries.",
        }, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def dns_resync_zone(server: str, zone: str) -> str:
    """
    Force a zone transfer on a secondary DNS server so it pulls the latest records from primary.
    Run this after updating records on the primary to ensure both servers agree.

    Args:
        server: Secondary server to resync (see dns_list_servers)
        zone:   Zone name to resync (e.g. 'example.org')
    """
    try:
        client = get_client(server)
        client.post("zones/resync", {"zone": zone})
        return json.dumps({
            "server": server,
            "zone": zone,
            "message": (
                f"Zone resync triggered on {server}. "
                "Allow a few seconds then run dns_compare to verify."
            ),
        }, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def dns_flush_local_cache() -> str:
    """
    Flush the systemd-resolved DNS cache on this machine.
    Run this after fixing DNS records so the local resolver picks up the new values immediately.
    """
    try:
        r = subprocess.run(
            ["resolvectl", "flush-caches"],
            capture_output=True, text=True, timeout=10,
        )
        if r.returncode != 0:
            return json.dumps({"error": r.stderr.strip() or "resolvectl flush-caches failed"})
        return json.dumps({
            "message": "Local DNS cache flushed successfully.",
            "note": "Re-run dns_compare to verify resolution from this machine.",
        }, indent=2)
    except FileNotFoundError:
        return json.dumps({"error": "resolvectl not found — not a systemd-resolved system"})
    except Exception as e:
        return json.dumps({"error": str(e)})


# ---------------------------------------------------------------------------
# DHCP Tools
# ---------------------------------------------------------------------------

@mcp.tool()
def dhcp_list_scopes(server: str) -> str:
    """
    List all DHCP scopes on a server with their status and address range.
    Use this first to discover scope names before calling other DHCP tools.

    Args:
        server: Server name (see dns_list_servers for configured names)
    """
    try:
        client = get_client(server)
        data = client.get("dhcp/scopes/list")
        scopes = data.get("response", {}).get("scopes", [])
        return json.dumps({
            "server": server,
            "count": len(scopes),
            "scopes": [
                {
                    "name": s.get("name"),
                    "enabled": s.get("enabled", False),
                    "startingAddress": s.get("startingAddress"),
                    "endingAddress": s.get("endingAddress"),
                    "subnetMask": s.get("subnetMask"),
                    "leased": s.get("leased", 0),
                    "available": s.get("available", 0),
                }
                for s in scopes
            ],
        }, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def dhcp_get_scope(server: str, scope_name: str) -> str:
    """
    Get full details for a DHCP scope: router, DNS servers, options, exclusions, reservations.
    Look here to diagnose DHCP option issues (e.g. Option 121 staticRoutes, Option 15 domain).

    Args:
        server:     Server name (see dns_list_servers for configured names)
        scope_name: Scope name (from dhcp_list_scopes, e.g. 'Default')
    """
    try:
        client = get_client(server)
        data = client.get("dhcp/scopes/get", {"name": scope_name})
        scope = data.get("response", {})
        # Surface the fields most relevant to diagnostics
        result = {
            "server": server,
            "name": scope.get("name"),
            "enabled": scope.get("enabled"),
            "startingAddress": scope.get("startingAddress"),
            "endingAddress": scope.get("endingAddress"),
            "subnetMask": scope.get("subnetMask"),
            "routerAddress": scope.get("routerAddress"),
            "dnsServers": scope.get("dnsServers"),
            "domainName": scope.get("domainName"),
            "leaseTime": scope.get("leaseTimeDays"),
            "staticRoutes": scope.get("staticRoutes", []),
            "exclusionRanges": scope.get("exclusionRanges", []),
            "reservedLeases": [
                {
                    "hostName": r.get("hostName"),
                    "hardwareAddress": r.get("hardwareAddress"),
                    "ipAddress": r.get("ipAddress"),
                    "comments": r.get("comments"),
                }
                for r in scope.get("reservedLeases", [])
            ],
        }
        return json.dumps(result, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def dhcp_list_leases(server: str, scope_name: str) -> str:
    """
    List active DHCP leases for a scope. Shows hostname, MAC, IP, and expiry.
    Useful for identifying devices and verifying reservations are working.

    Args:
        server:     Server name (see dns_list_servers for configured names)
        scope_name: Scope name (from dhcp_list_scopes, e.g. 'Default')
    """
    try:
        client = get_client(server)
        data = client.get("dhcp/leases/list", {"scopeName": scope_name})
        leases = data.get("response", {}).get("leases", [])
        return json.dumps({
            "server": server,
            "scope": scope_name,
            "count": len(leases),
            "leases": [
                {
                    "hostName": l.get("hostName", ""),
                    "hardwareAddress": l.get("hardwareAddress"),
                    "ipAddress": l.get("address"),
                    "leaseExpires": l.get("leaseExpires"),
                    "type": l.get("type"),
                }
                for l in leases
            ],
        }, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def dhcp_add_reservation(
    server: str,
    scope_name: str,
    ip_address: str,
    hardware_address: str,
    hostname: str,
    comments: str = "",
) -> str:
    """
    Add a static IP reservation to a DHCP scope (MAC → IP binding).
    The device will always receive the same IP when it requests a lease.

    Args:
        server:           Server name (see dns_list_servers for configured names)
        scope_name:       Scope name (e.g. 'Default')
        ip_address:       IP to reserve (must be within the scope range)
        hardware_address: Device MAC address (e.g. 'AA:BB:CC:DD:EE:FF')
        hostname:         Friendly name for the reservation
        comments:         Optional description
    """
    try:
        client = get_client(server)
        client.post("dhcp/scopes/addReservation", {
            "name": scope_name,
            "ipAddress": ip_address,
            "hardwareAddress": hardware_address,
            "hostName": hostname,
            "comments": comments,
        })
        return json.dumps({
            "server": server,
            "scope": scope_name,
            "hostname": hostname,
            "ipAddress": ip_address,
            "hardwareAddress": hardware_address,
            "message": "Reservation added. Device will receive this IP on next lease renewal.",
        }, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def dhcp_remove_reservation(server: str, scope_name: str, ip_address: str) -> str:
    """
    Remove a static IP reservation from a DHCP scope.

    Args:
        server:     Server name (see dns_list_servers for configured names)
        scope_name: Scope name (e.g. 'Default')
        ip_address: Reserved IP to remove
    """
    try:
        client = get_client(server)
        client.post("dhcp/scopes/removeReservation", {
            "name": scope_name,
            "ipAddress": ip_address,
        })
        return json.dumps({
            "server": server,
            "scope": scope_name,
            "ipAddress": ip_address,
            "message": "Reservation removed.",
        }, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def dhcp_clear_static_routes(server: str, scope_name: str) -> str:
    """
    Remove all Option 121 static routes from a DHCP scope.

    This fixes the Android/Samsung 'connected but no internet' bug caused by Option 121
    pushing routes that override the device's default gateway. Run dhcp_get_scope first
    to confirm staticRoutes is non-empty, then run this to clear them.

    After clearing, affected devices must reconnect (forget + rejoin WiFi) to get a
    new lease without the bad routes.

    Args:
        server:     Server name (see dns_list_servers for configured names)
        scope_name: Scope name (e.g. 'Default')
    """
    try:
        client = get_client(server)

        # Fetch current scope to confirm there are routes and get all other fields
        data = client.get("dhcp/scopes/get", {"name": scope_name})
        scope = data.get("response", {})
        current_routes = scope.get("staticRoutes", [])

        if not current_routes:
            return json.dumps({
                "server": server,
                "scope": scope_name,
                "message": "No static routes configured — nothing to clear.",
            }, indent=2)

        # Update scope with staticRoutes set to empty
        client.post("dhcp/scopes/set", {
            "name": scope_name,
            "newName": scope_name,
            "startingAddress": scope.get("startingAddress", ""),
            "endingAddress": scope.get("endingAddress", ""),
            "subnetMask": scope.get("subnetMask", ""),
            "routerAddress": scope.get("routerAddress", ""),
            "staticRoutes": "",
        })

        return json.dumps({
            "server": server,
            "scope": scope_name,
            "removed_routes": current_routes,
            "message": (
                "Option 121 static routes cleared. "
                "Affected devices must forget + rejoin the network to get a clean lease."
            ),
        }, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


# ---------------------------------------------------------------------------
# Smoke test
# ---------------------------------------------------------------------------

def test_tools():
    load_env()
    print("=== Testing Technitium DNS MCP Tools ===\n")

    server = next(iter(SERVERS))

    print("1. dns_list_servers()")
    print(dns_list_servers())
    print()

    print(f"2. dns_list_zones(server='{server}')")
    print(dns_list_zones(server=server))
    print()

    print(f"3. dns_get_records(server='{server}', zone='example.org', subdomain='support.example.org')")
    print(dns_get_records(server=server, zone="example.org", subdomain="support.example.org"))
    print()

    print("4. dns_compare(hostname='support.example.org')")
    print(dns_compare(hostname="support.example.org"))
    print()

    print("5. dns_flush_local_cache()")
    print(dns_flush_local_cache())
    print()

    print("=== Tests complete ===")


if __name__ == "__main__":
    if "--test" in sys.argv:
        test_tools()
    else:
        mcp.run(transport="stdio")
