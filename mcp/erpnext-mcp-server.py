#!/usr/bin/env python3
"""
ERPNext MCP Server — Frappe Helpdesk management across configured tenants.

Tools:
  erpnext_list_tickets       List tickets with optional status/priority filters
  erpnext_get_ticket         Get full ticket details
  erpnext_create_ticket      Create a new support ticket
  erpnext_update_ticket      Update ticket fields (status, priority, assigned_to)
  erpnext_add_reply          Add a reply or internal comment to a ticket
  erpnext_get_communications Get communication history for a ticket

Usage:
  python3 scripts/erpnext-mcp-server.py            # stdio MCP server
  python3 scripts/erpnext-mcp-server.py --test      # smoke-test all tools

Tenant configuration:
  Tenants are loaded from a gitignored mcp/tenants.local.json (next to this
  script) if present; otherwise a single example tenant is used. The file
  maps tenant keys to {"site", "description"}:

    {
      "client1": {
        "site": "helpdesk.client1.example.org",
        "description": "Example client helpdesk"
      }
    }

Environment (or .env):
  Each tenant reads ERPNEXT_ADMIN_PASSWORD_<TENANT_KEY_UPPERCASED>, e.g.:
  ERPNEXT_ADMIN_PASSWORD_CLIENT1=<password for helpdesk.client1.example.org>
  # ERPNEXT_ADMIN_PASSWORD=<password>   # fallback used for any tenant without its own var
"""

import asyncio
import json
import os
import sys
from pathlib import Path
from urllib.parse import quote

import requests

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:
    print("ERROR: mcp package not installed. Run: pip install mcp", file=sys.stderr)
    sys.exit(1)

REPO_ROOT = Path(__file__).parent.parent.resolve()

_TENANTS_FILE = Path(__file__).parent / "tenants.local.json"


def _load_tenants() -> dict:
    """Load tenant config from gitignored tenants.local.json, else example fallback."""
    if _TENANTS_FILE.exists():
        return json.loads(_TENANTS_FILE.read_text())
    return {
        "client1": {
            "site": "helpdesk.client1.example.org",
            "description": "Example client helpdesk",
        },
    }


TENANTS = _load_tenants()

mcp = FastMCP("erpnext-helpdesk")


def load_env():
    env_file = REPO_ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k, v)


class FrappeClient:
    def __init__(self, base_url: str, site: str, password: str):
        self.base_url = base_url.rstrip("/")
        self.site = site
        self.password = password
        self.session = requests.Session()
        self._login()

    def _login(self):
        resp = self.session.post(
            f"{self.base_url}/api/method/login",
            data={"usr": "Administrator", "pwd": self.password},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("message") != "Logged In":
            raise RuntimeError(f"Login failed for {self.site}: {resp.text}")

    def _ensure_auth(self):
        if not self.session.cookies.get("sid", domain=self.site):
            self._login()

    def _request(self, method: str, resource: str, **kwargs):
        url = f"{self.base_url}/api/resource/{resource}"
        self._ensure_auth()
        resp = self.session.request(method, url, **kwargs)
        if resp.status_code in (401, 417):
            self._login()
            resp = self.session.request(method, url, **kwargs)
        resp.raise_for_status()
        return resp.json()

    def get(self, resource: str, params: dict = None):
        return self._request("GET", resource, params=params, timeout=15)

    def post(self, resource: str, data: dict):
        return self._request("POST", resource, json=data, timeout=15)

    def put(self, resource: str, data: dict):
        return self._request("PUT", resource, json=data, timeout=15)

    def run_method(self, method: str, params: dict = None):
        url = f"{self.base_url}/api/method/{method}"
        self._ensure_auth()
        resp = self.session.post(url, data=params or {}, timeout=15)
        resp.raise_for_status()
        return resp.json()


_clients: dict[str, FrappeClient] = {}


def get_client(tenant: str) -> FrappeClient:
    if tenant not in _clients:
        load_env()
        site = TENANTS[tenant]["site"]
        env_key = f"ERPNEXT_ADMIN_PASSWORD_{tenant.upper()}"
        password = os.environ.get(env_key) or os.environ.get("ERPNEXT_ADMIN_PASSWORD")
        if not password:
            raise RuntimeError(
                f"{env_key} (or ERPNEXT_ADMIN_PASSWORD) not set. Add to .env or export it."
            )
        # Connect to each tenant's real domain directly rather than a shared
        # IP + Host header -- both tenants sit behind cs-caddy's automatic
        # HTTPS, which redirects plain-HTTP-by-IP requests to the real
        # hostname, and a cert issued for that hostname won't validate
        # against a bare-IP connection anyway.
        _clients[tenant] = FrappeClient(f"https://{site}", site, password)
    return _clients[tenant]


@mcp.tool()
def erpnext_list_tickets(
    tenant: str,
    status: str = None,
    priority: str = None,
    agent_group: str = None,
    limit: int = 20,
) -> str:
    """
    List HD Tickets for a tenant.

    Args:
        tenant: Tenant name (e.g. 'client1'; see erpnext_list_tenants).
        status: Filter by status (e.g. 'Open', 'Resolved', 'Closed', 'Replied').
        priority: Filter by priority ('Low', 'Medium', 'High', 'Urgent').
        agent_group: Filter by assigned agent group.
        limit: Max results (default 20, max 100).
    """
    if tenant not in TENANTS:
        return f"Invalid tenant '{tenant}'. Choose: {', '.join(TENANTS.keys())}"

    filters = []
    if status:
        filters.append(["status", "=", status])
    if priority:
        filters.append(["priority", "=", priority])
    if agent_group:
        filters.append(["agent_group", "=", agent_group])

    params = {"limit_page_length": min(limit, 100)}
    if filters:
        params["filters"] = json.dumps(filters)

    try:
        client = get_client(tenant)
        result = client.get("HD Ticket", params)
        tickets = result.get("data", [])
        return json.dumps({"tenant": tenant, "count": len(tickets), "tickets": tickets}, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def erpnext_get_ticket(tenant: str, ticket_id: str) -> str:
    """
    Get full details of a single HD Ticket.

    Args:
        tenant: Tenant name (e.g. 'client1'; see erpnext_list_tenants).
        ticket_id: Ticket ID (e.g. '0054').
    """
    if tenant not in TENANTS:
        return f"Invalid tenant '{tenant}'. Choose: {', '.join(TENANTS.keys())}"

    try:
        client = get_client(tenant)
        result = client.get(f"HD Ticket/{quote(ticket_id)}")
        return json.dumps({"tenant": tenant, "ticket": result.get("data", {})}, indent=2, default=str)
    except requests.HTTPError as e:
        if e.response.status_code == 404:
            return json.dumps({"error": f"Ticket '{ticket_id}' not found on {tenant}"})
        return json.dumps({"error": str(e)})
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def erpnext_create_ticket(
    tenant: str,
    subject: str,
    raised_by: str,
    description: str,
    priority: str = "Medium",
    status: str = "Open",
    agent_group: str = None,
    customer: str = None,
    contact: str = None,
) -> str:
    """
    Create a new HD Ticket on a tenant.

    Args:
        tenant: Tenant name (e.g. 'client1'; see erpnext_list_tenants).
        subject: Ticket subject/title.
        raised_by: Email address of the person raising the ticket.
        description: Ticket description (supports HTML).
        priority: Priority ('Low', 'Medium', 'High', 'Urgent'). Default Medium.
        status: Status ('Open', 'Replied', 'Resolved', 'Closed'). Default Open.
        agent_group: Agent group to assign to (optional).
        customer: Customer name (optional, will use raised_by if omitted).
        contact: Contact name (optional).
    """
    if tenant not in TENANTS:
        return f"Invalid tenant '{tenant}'. Choose: {', '.join(TENANTS.keys())}"

    try:
        client = get_client(tenant)
        doc = {
            "subject": subject,
            "raised_by": raised_by,
            "description": description,
            "priority": priority,
            "status": status,
        }
        if agent_group:
            doc["agent_group"] = agent_group
        if customer:
            doc["customer"] = customer
        if contact:
            doc["contact"] = contact

        result = client.post("HD Ticket", doc)
        return json.dumps({
            "tenant": tenant,
            "message": "Ticket created successfully",
            "ticket": result.get("data", {}),
        }, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def erpnext_update_ticket(
    tenant: str,
    ticket_id: str,
    status: str = None,
    priority: str = None,
    subject: str = None,
    agent_group: str = None,
    description: str = None,
) -> str:
    """
    Update fields on an existing HD Ticket.

    Args:
        tenant: Tenant name (e.g. 'client1'; see erpnext_list_tenants).
        ticket_id: Ticket ID to update.
        status: New status ('Open', 'Replied', 'Resolved', 'Closed').
        priority: New priority ('Low', 'Medium', 'High', 'Urgent').
        subject: New subject.
        agent_group: Assign to a different agent group.
        description: Update description.
    """
    if tenant not in TENANTS:
        return f"Invalid tenant '{tenant}'. Choose: {', '.join(TENANTS.keys())}"

    doc = {}
    if status is not None:
        doc["status"] = status
    if priority is not None:
        doc["priority"] = priority
    if subject is not None:
        doc["subject"] = subject
    if agent_group is not None:
        doc["agent_group"] = agent_group
    if description is not None:
        doc["description"] = description

    if not doc:
        return json.dumps({"error": "No fields provided to update"})

    try:
        client = get_client(tenant)
        result = client.put(f"HD Ticket/{quote(ticket_id)}", doc)
        return json.dumps({
            "tenant": tenant,
            "message": f"Ticket {ticket_id} updated successfully",
            "ticket": result.get("data", {}),
        }, indent=2)
    except requests.HTTPError as e:
        if e.response.status_code == 404:
            return json.dumps({"error": f"Ticket '{ticket_id}' not found on {tenant}"})
        return json.dumps({"error": str(e)})
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def erpnext_add_reply(
    tenant: str,
    ticket_id: str,
    content: str,
    reply_type: str = "Reply",
    sender: str = None,
) -> str:
    """
    Add a reply or internal comment to a ticket.

    Args:
        tenant: Tenant name (e.g. 'client1'; see erpnext_list_tenants).
        ticket_id: Ticket ID to reply to.
        content: Message content (supports HTML, plain text will be wrapped).
        reply_type: 'Reply' for customer-facing reply, 'Comment' for internal note.
        sender: Sender email (defaults to Administrator).
    """
    if tenant not in TENANTS:
        return f"Invalid tenant '{tenant}'. Choose: {', '.join(TENANTS.keys())}"

    if reply_type not in ("Reply", "Comment"):
        return json.dumps({"error": "reply_type must be 'Reply' or 'Comment'"})

    try:
        client = get_client(tenant)
        comm = {
            "reference_doctype": "HD Ticket",
            "reference_name": ticket_id,
            "communication_type": "Communication" if reply_type == "Reply" else "Comment",
            "communication_medium": "Email" if reply_type == "Reply" else "Chat",
            "content": content,
            "subject": f"Re: {ticket_id}",
            "sent_or_received": "Sent",
        }
        if sender:
            comm["sender"] = sender

        result = client.post("Communication", comm)
        return json.dumps({
            "tenant": tenant,
            "ticket_id": ticket_id,
            "message": f"{reply_type} added to ticket {ticket_id}",
            "communication": result.get("data", {}),
        }, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def erpnext_get_communications(
    tenant: str,
    ticket_id: str,
    limit: int = 50,
) -> str:
    """
    Get communication history for a ticket.

    Args:
        tenant: Tenant name (e.g. 'client1'; see erpnext_list_tenants).
        ticket_id: Ticket ID to get communications for.
        limit: Max communications to return (default 50, max 200).
    """
    if tenant not in TENANTS:
        return f"Invalid tenant '{tenant}'. Choose: {', '.join(TENANTS.keys())}"

    try:
        client = get_client(tenant)
        params = {
            "filters": json.dumps([
                ["reference_doctype", "=", "HD Ticket"],
                ["reference_name", "=", ticket_id],
            ]),
            "fields": json.dumps([
                "name", "subject", "communication_type",
                "communication_medium", "content", "sender",
                "creation", "sent_or_received",
            ]),
            "limit_page_length": min(limit, 200),
        }
        result = client.get("Communication", params)
        comms = result.get("data", [])
        return json.dumps({
            "tenant": tenant,
            "ticket_id": ticket_id,
            "count": len(comms),
            "communications": comms,
        }, indent=2, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def erpnext_list_tenants() -> str:
    """List available tenants and their site URLs."""
    return json.dumps({
        "tenants": {
            k: {"site": v["site"], "description": v["description"]}
            for k, v in TENANTS.items()
        }
    }, indent=2)


def test_tools():
    load_env()
    if not any(os.environ.get(f"ERPNEXT_ADMIN_PASSWORD_{t.upper()}") or os.environ.get("ERPNEXT_ADMIN_PASSWORD") for t in TENANTS):
        print("No ERPNEXT_ADMIN_PASSWORD_<TENANT> (or ERPNEXT_ADMIN_PASSWORD) set. Edit .env first.")
        sys.exit(1)

    print("=== Testing ERPNext MCP Tools ===\n")

    tenant = next(iter(TENANTS))

    print("1. erpnext_list_tenants()")
    print(erpnext_list_tenants())
    print()

    print(f"2. erpnext_list_tickets(tenant='{tenant}', limit=3)")
    print(erpnext_list_tickets(tenant=tenant, limit=3))
    print()

    print(f"3. erpnext_get_ticket(tenant='{tenant}', ticket_id='0001')")
    print(erpnext_get_ticket(tenant=tenant, ticket_id="0001"))
    print()

    print(f"4. erpnext_get_communications(tenant='{tenant}', ticket_id='0001')")
    print(erpnext_get_communications(tenant=tenant, ticket_id="0001"))
    print()

    print(f"5. erpnext_create_ticket(tenant='{tenant}', ...)")
    result = erpnext_create_ticket(
        tenant=tenant,
        subject="MCP Test Ticket - please ignore",
        raised_by="test@opencode.ai",
        description="<p>Automated test from ERPNext MCP server.</p>",
        priority="Low",
        status="Open",
    )
    print(result)
    data = json.loads(result)
    tid = data.get("ticket", {}).get("name", "")
    if tid:
        print(f"\n6. erpnext_add_reply(tenant='{tenant}', ticket_id='{tid}', ...)")
        print(erpnext_add_reply(tenant=tenant, ticket_id=tid, content="<p>Test reply from MCP.</p>", reply_type="Comment"))
        print(f"\n7. erpnext_update_ticket(tenant='{tenant}', ticket_id='{tid}', status='Closed')")
        print(erpnext_update_ticket(tenant=tenant, ticket_id=tid, status="Closed", priority="Low"))
        print(f"\n8. erpnext_get_communications(tenant='{tenant}', ticket_id='{tid}')")
        print(erpnext_get_communications(tenant=tenant, ticket_id=tid))
    print()
    print("=== Tests passed ===")


if __name__ == "__main__":
    if "--test" in sys.argv:
        test_tools()
    else:
        mcp.run(transport="stdio")
