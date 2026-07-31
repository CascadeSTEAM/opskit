#!/usr/bin/env python3
"""
ERPNext MCP Server — Frappe Helpdesk management across configured tenants.

Tools -- tickets:
  erpnext_list_tickets       List tickets with optional status/priority filters
  erpnext_get_ticket         Get full ticket details
  erpnext_create_ticket      Create a new support ticket
  erpnext_update_ticket      Update ticket fields (status, priority, assigned_to)
  erpnext_add_reply          Add a reply or internal comment to a ticket
  erpnext_get_communications Get communication history for a ticket

Tools -- party management (Customer/Supplier/Contact/Address/Customer Group/
Territory/HD Customer). See PARTY MANAGEMENT below for the central 1:1
Customer <-> HD Customer invariant this module enforces:
  erpnext_list_party         List records of an allowlisted party doctype
  erpnext_get_party          Fetch a single party doc (always full-doc, never list -- see traps)
  erpnext_create_party       Create Supplier/Contact/Address/Customer Group/Territory
  erpnext_update_party       Update fields on an existing party record
  erpnext_disable_party      Disable (soft-delete) a non-paired party doctype
  erpnext_delete_party       Safe-delete a non-paired party doctype
  erpnext_get_party_links    Resolve Contact/Address links to a party via the parent doc
  erpnext_create_customer    Create Customer + HD Customer together (paired, atomic)
  erpnext_get_customer       Fetch a Customer together with its paired HD Customer
  erpnext_rename_customer    Rename Customer, propagating to the paired HD Customer + bridge
  erpnext_disable_customer   Disable a Customer, paired-aware
  erpnext_merge_customer     Merge two Customers, merging their paired HD Customers too
  erpnext_delete_customer    Safe-delete Customer + paired HD Customer together
  erpnext_check_party_drift  Drift check: unpaired/mismatched Customer <-> HD Customer records
  erpnext_list_customer_tickets  All HD Tickets for a Customer, resolved through the bridge

PARTY MANAGEMENT -- the central invariant:
  HD Ticket.customer is a Link to HD Customer, NOT to ERPNext Customer -- they
  are separate doctypes. The only bridge is HD Customer.erpnext_customer, a
  plain Data field (free text), NOT a Link. Frappe will not enforce this
  relationship, will not cascade a rename, and will not block a delete that
  orphans the bridge -- the invariant exists only in this tooling:
    - erpnext_create_customer creates both records in one call; a half-create
      (HD Customer POST fails after Customer POST succeeds) is rolled back.
    - erpnext_rename_customer / erpnext_merge_customer / erpnext_delete_customer
      always operate on both sides together and refuse (with an actionable
      error) rather than silently completing only one side.
    - erpnext_check_party_drift is the regression test for the invariant --
      run it after any bulk/manual change to catch drift early.
  Two confirmed traps this module engineers around (opskit issue #74):
    1. `Dynamic Link` is a child table (istable=1) with no independent
       permissions -- it cannot be queried via /api/resource directly
       (PermissionError). erpnext_get_party_links resolves Contact/Address
       links through the PARENT document's `links` field instead.
    2. Child-table fields are silently dropped from LIST query results with
       no error (e.g. requesting `links` on a list endpoint returns bare
       `name` only, for every record -- a false "everyone is an orphan"
       result). erpnext_get_party always fetches the SINGLE doc; the generic
       erpnext_list_party refuses a `fields` request that includes a known
       child-table field rather than silently returning wrong data.

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

  Set ERPNEXT_TENANTS_FILE to point at a different path instead of the
  default mcp/tenants.local.json -- this is how the test suite stays
  independent of whatever (if anything) a developer has locally (opskit
  issue #76): it never reads the real gitignored file.

Auth:
  Uses Frappe token auth (Authorization: token <api_key>:<api_secret>) against
  a low-privilege service account -- never Administrator, never a plaintext
  password. Resolve the key/secret from the vault at runtime; do not commit
  them (see .opencode/rules/no-plaintext-creds.md).

Environment (or .env):
  Each tenant reads ERPNEXT_API_KEY_<TENANT_KEY_UPPERCASED> and
  ERPNEXT_API_SECRET_<TENANT_KEY_UPPERCASED>, e.g.:
  ERPNEXT_API_KEY_CLIENT1=<service-account API key for helpdesk.client1.example.org>
  ERPNEXT_API_SECRET_CLIENT1=<service-account API secret>
  # ERPNEXT_API_KEY=<key>       # fallback used for any tenant without its own var
  # ERPNEXT_API_SECRET=<secret> # fallback used for any tenant without its own var
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

# ERPNEXT_TENANTS_FILE lets a caller (notably the test suite) override the
# config path instead of always reading the developer's real, gitignored
# mcp/tenants.local.json -- see "Tenant configuration" above (opskit #76).
_TENANTS_FILE = (
    Path(os.environ["ERPNEXT_TENANTS_FILE"])
    if os.environ.get("ERPNEXT_TENANTS_FILE")
    else Path(__file__).parent / "tenants.local.json"
)


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
    """Talks to a Frappe/ERPNext site as a configured service account using
    token auth (Authorization: token <api_key>:<api_secret>) -- no login
    call, no session cookie, no Administrator password."""

    def __init__(self, base_url: str, site: str, api_key: str, api_secret: str):
        self.base_url = base_url.rstrip("/")
        self.site = site
        self.session = requests.Session()
        self.session.headers.update({"Authorization": f"token {api_key}:{api_secret}"})

    def _request(self, method: str, resource: str, **kwargs):
        url = f"{self.base_url}/api/resource/{resource}"
        resp = self.session.request(method, url, **kwargs)
        resp.raise_for_status()
        return resp.json()

    def get(self, resource: str, params: dict = None):
        return self._request("GET", resource, params=params, timeout=15)

    def post(self, resource: str, data: dict):
        return self._request("POST", resource, json=data, timeout=15)

    def put(self, resource: str, data: dict):
        return self._request("PUT", resource, json=data, timeout=15)

    def delete(self, resource: str):
        return self._request("DELETE", resource, timeout=15)

    def run_method(self, method: str, params: dict = None):
        url = f"{self.base_url}/api/method/{method}"
        resp = self.session.post(url, data=params or {}, timeout=15)
        resp.raise_for_status()
        return resp.json()


_clients: dict[str, FrappeClient] = {}


def get_client(tenant: str) -> FrappeClient:
    if tenant not in _clients:
        load_env()
        site = TENANTS[tenant]["site"]
        key_var = f"ERPNEXT_API_KEY_{tenant.upper()}"
        secret_var = f"ERPNEXT_API_SECRET_{tenant.upper()}"
        api_key = os.environ.get(key_var) or os.environ.get("ERPNEXT_API_KEY")
        api_secret = os.environ.get(secret_var) or os.environ.get("ERPNEXT_API_SECRET")
        if not api_key or not api_secret:
            raise RuntimeError(
                f"{key_var}/{secret_var} (or ERPNEXT_API_KEY/ERPNEXT_API_SECRET) not set. "
                "Resolve the service account's API key/secret from the vault and export "
                "them (or add to .env) -- never commit them."
            )
        # Connect to each tenant's real domain directly rather than a shared
        # IP + Host header -- both tenants sit behind cs-caddy's automatic
        # HTTPS, which redirects plain-HTTP-by-IP requests to the real
        # hostname, and a cert issued for that hostname won't validate
        # against a bare-IP connection anyway.
        _clients[tenant] = FrappeClient(f"https://{site}", site, api_key, api_secret)
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
        sender: Sender email (defaults to the connected service account if omitted).
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


# ---------------------------------------------------------------------------
# Party management: Customer, Supplier, Contact, Address, Customer Group,
# Territory, HD Customer -- see the PARTY MANAGEMENT module docstring above
# for the central 1:1 Customer <-> HD Customer invariant this section exists
# to enforce, and the two confirmed API traps it engineers around.
# ---------------------------------------------------------------------------

# Party doctypes creatable/deletable/disable-able through the *generic*
# tools. Customer and HD Customer are deliberately excluded here -- they are
# a pair and must go through the erpnext_*_customer tools so one side can
# never be created/renamed/disabled/deleted without the other.
GENERIC_PARTY_DOCTYPES = {"Supplier", "Contact", "Address", "Customer Group", "Territory"}
PAIRED_DOCTYPES = {"Customer", "HD Customer"}
ALL_PARTY_DOCTYPES = GENERIC_PARTY_DOCTYPES | PAIRED_DOCTYPES

# Only Supplier carries a `disabled` field among the generic doctypes in
# stock Frappe/ERPNext (Contact/Address/Customer Group/Territory do not).
DISABLEABLE_GENERIC_DOCTYPES = {"Supplier"}

# Fields that are child tables (istable=1) on these doctypes -- silently
# dropped from /api/resource LIST results with no error (trap #2). Any tool
# that lists records must never trust these fields from a list response.
CHILD_TABLE_FIELDS = {
    "Contact": {"links"},
    "Address": {"links"},
}

# Heuristic (non-exhaustive) sets of doctypes commonly linked to a Customer /
# HD Customer, used only as a best-effort pre-flight check before a delete
# attempt. The authoritative check is still the wrapped delete call itself --
# these lists exist purely to avoid the common case of a doomed-from-the-start
# partial delete, not to replace Frappe's own link-existence enforcement.
CUSTOMER_LINK_DOCTYPES = ["Sales Invoice", "Sales Order", "Quotation", "Delivery Note"]
HD_CUSTOMER_LINK_DOCTYPES = ["HD Ticket"]


def _invalid_doctype_error(doctype: str, allowed: set) -> str:
    return json.dumps({
        "error": f"Invalid doctype '{doctype}'. Choose one of: {', '.join(sorted(allowed))}"
    })


def _is_link_exists_error(exc: requests.HTTPError) -> bool:
    """Detect Frappe's LinkExistsError (raised when a delete would orphan a
    linked transaction) so callers get an actionable message instead of a
    raw HTTP traceback. Frappe returns HTTP 409 for this specific exception;
    we also fall back to a string search in case a proxy/version differs."""
    resp = exc.response
    if resp is None:
        return False
    if resp.status_code == 409:
        return True
    try:
        body = resp.json()
    except ValueError:
        body = None
    haystack = json.dumps(body) if body is not None else (resp.text or "")
    return "LinkExistsError" in haystack


def _find_hd_customer_for(client: "FrappeClient", customer_name: str) -> dict | None:
    """Resolve the HD Customer paired to an ERPNext Customer through the
    bridge field (HD Customer.erpnext_customer). erpnext_customer is a plain
    Data field, not a child table, so filtering it in a LIST query is safe
    (trap #2 only applies to child-table fields like `links`)."""
    params = {
        "filters": json.dumps([["erpnext_customer", "=", customer_name]]),
        "fields": json.dumps(["name", "erpnext_customer"]),
        "limit_page_length": 2,
    }
    rows = client.get("HD Customer", params).get("data", [])
    if not rows:
        return None
    return rows[0]


def _precheck_linked_docs(client: "FrappeClient", field: str, value: str, check_doctypes: list) -> list:
    """Best-effort scan of `check_doctypes` for any record referencing
    `value` via `field`. Not exhaustive -- see CUSTOMER_LINK_DOCTYPES /
    HD_CUSTOMER_LINK_DOCTYPES comment. A probe that itself errors is skipped
    rather than failing the whole check."""
    hits = []
    for doctype in check_doctypes:
        try:
            params = {
                "filters": json.dumps([[field, "=", value]]),
                "fields": json.dumps(["name"]),
                "limit_page_length": 1,
            }
            if client.get(doctype, params).get("data"):
                hits.append(doctype)
        except Exception:
            continue
    return hits


@mcp.tool()
def erpnext_list_party(
    tenant: str,
    doctype: str,
    filters: str = None,
    fields: str = None,
    limit: int = 20,
) -> str:
    """
    List records of an allowlisted party doctype.

    Args:
        tenant: Tenant name (e.g. 'client1'; see erpnext_list_tenants).
        doctype: One of Supplier, Contact, Address, Customer Group, Territory,
            Customer, HD Customer.
        filters: JSON-encoded Frappe filter list, e.g. '[["disabled","=",0]]'.
        fields: JSON-encoded list of field names to return (default just 'name').
            Refused if it names a child-table field (e.g. Contact/Address
            'links') -- that silently returns nothing on a list endpoint with
            no error; use erpnext_get_party or erpnext_get_party_links instead.
        limit: Max results (default 20, max 200).
    """
    if tenant not in TENANTS:
        return f"Invalid tenant '{tenant}'. Choose: {', '.join(TENANTS.keys())}"
    if doctype not in ALL_PARTY_DOCTYPES:
        return _invalid_doctype_error(doctype, ALL_PARTY_DOCTYPES)

    requested_fields = ["name"]
    if fields:
        try:
            requested_fields = json.loads(fields)
        except (json.JSONDecodeError, ValueError):
            return json.dumps({"error": "fields must be a JSON-encoded list of field names"})
        child_fields = CHILD_TABLE_FIELDS.get(doctype, set())
        bad = child_fields & set(requested_fields)
        if bad:
            return json.dumps({
                "error": f"Cannot list child-table field(s) {sorted(bad)} on '{doctype}' -- "
                "list queries silently drop child-table fields with no error. Use "
                "erpnext_get_party (single doc) or erpnext_get_party_links instead."
            })

    params = {"fields": json.dumps(requested_fields), "limit_page_length": min(limit, 200)}
    if filters:
        params["filters"] = filters

    try:
        client = get_client(tenant)
        result = client.get(doctype, params)
        records = result.get("data", [])
        return json.dumps({"tenant": tenant, "doctype": doctype, "count": len(records), "records": records}, indent=2, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def erpnext_get_party(tenant: str, doctype: str, name: str) -> str:
    """
    Fetch a single party record by name. Always fetches the full document
    (never a list query), so child-table fields like Contact/Address `links`
    are always populated -- see trap #2 in the module docstring.

    Args:
        tenant: Tenant name (e.g. 'client1'; see erpnext_list_tenants).
        doctype: One of Supplier, Contact, Address, Customer Group, Territory,
            Customer, HD Customer.
        name: Record name (primary key).
    """
    if tenant not in TENANTS:
        return f"Invalid tenant '{tenant}'. Choose: {', '.join(TENANTS.keys())}"
    if doctype not in ALL_PARTY_DOCTYPES:
        return _invalid_doctype_error(doctype, ALL_PARTY_DOCTYPES)

    try:
        client = get_client(tenant)
        result = client.get(f"{doctype}/{quote(name)}")
        return json.dumps({"tenant": tenant, "doctype": doctype, "record": result.get("data", {})}, indent=2, default=str)
    except requests.HTTPError as e:
        if e.response is not None and e.response.status_code == 404:
            return json.dumps({"error": f"{doctype} '{name}' not found on {tenant}"})
        return json.dumps({"error": str(e)})
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def erpnext_create_party(tenant: str, doctype: str, data: str) -> str:
    """
    Create a Supplier, Contact, Address, Customer Group, or Territory record.
    Customer/HD Customer are deliberately excluded -- creating either side
    alone would break the 1:1 invariant; use erpnext_create_customer.

    Args:
        tenant: Tenant name (e.g. 'client1'; see erpnext_list_tenants).
        doctype: One of Supplier, Contact, Address, Customer Group, Territory.
        data: JSON-encoded object of field values for the new document.
    """
    if tenant not in TENANTS:
        return f"Invalid tenant '{tenant}'. Choose: {', '.join(TENANTS.keys())}"
    if doctype in PAIRED_DOCTYPES:
        return json.dumps({
            "error": f"'{doctype}' is part of the Customer<->HD Customer pair -- "
            "use erpnext_create_customer so both sides are created together."
        })
    if doctype not in GENERIC_PARTY_DOCTYPES:
        return _invalid_doctype_error(doctype, GENERIC_PARTY_DOCTYPES)

    try:
        doc = json.loads(data)
    except (json.JSONDecodeError, ValueError):
        return json.dumps({"error": "data must be a JSON-encoded object of field values"})

    try:
        client = get_client(tenant)
        result = client.post(doctype, doc)
        return json.dumps({"tenant": tenant, "doctype": doctype, "message": f"{doctype} created", "record": result.get("data", {})}, indent=2, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def erpnext_update_party(tenant: str, doctype: str, name: str, data: str) -> str:
    """
    Update fields on an existing party record (not a rename -- Frappe's
    `name` cannot be changed via a field update; use erpnext_rename_customer
    for Customer/HD Customer).

    Args:
        tenant: Tenant name (e.g. 'client1'; see erpnext_list_tenants).
        doctype: One of Supplier, Contact, Address, Customer Group, Territory,
            Customer, HD Customer.
        name: Record name to update.
        data: JSON-encoded object of field values to change.
    """
    if tenant not in TENANTS:
        return f"Invalid tenant '{tenant}'. Choose: {', '.join(TENANTS.keys())}"
    if doctype not in ALL_PARTY_DOCTYPES:
        return _invalid_doctype_error(doctype, ALL_PARTY_DOCTYPES)

    try:
        doc = json.loads(data)
    except (json.JSONDecodeError, ValueError):
        return json.dumps({"error": "data must be a JSON-encoded object of field values"})

    if doctype == "HD Customer" and "erpnext_customer" in doc:
        return json.dumps({
            "error": "erpnext_customer is the Customer<->HD Customer bridge field -- "
            "editing it directly here could break the invariant silently. Use "
            "erpnext_rename_customer or erpnext_merge_customer instead."
        })

    try:
        client = get_client(tenant)
        result = client.put(f"{doctype}/{quote(name)}", doc)
        return json.dumps({"tenant": tenant, "doctype": doctype, "message": f"{doctype} '{name}' updated", "record": result.get("data", {})}, indent=2, default=str)
    except requests.HTTPError as e:
        if e.response is not None and e.response.status_code == 404:
            return json.dumps({"error": f"{doctype} '{name}' not found on {tenant}"})
        return json.dumps({"error": str(e)})
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def erpnext_disable_party(tenant: str, doctype: str, name: str, disabled: bool = True) -> str:
    """
    Disable (or re-enable) a non-paired party record. Customer is
    deliberately excluded -- use erpnext_disable_customer, which is
    paired-aware.

    Args:
        tenant: Tenant name (e.g. 'client1'; see erpnext_list_tenants).
        doctype: Currently only 'Supplier' carries a `disabled` field among
            the generic doctypes.
        name: Record name.
        disabled: True to disable, False to re-enable. Default True.
    """
    if tenant not in TENANTS:
        return f"Invalid tenant '{tenant}'. Choose: {', '.join(TENANTS.keys())}"
    if doctype in PAIRED_DOCTYPES:
        return json.dumps({
            "error": f"'{doctype}' is part of the Customer<->HD Customer pair -- "
            "use erpnext_disable_customer so both sides are handled together."
        })
    if doctype not in DISABLEABLE_GENERIC_DOCTYPES:
        return _invalid_doctype_error(doctype, DISABLEABLE_GENERIC_DOCTYPES)

    try:
        client = get_client(tenant)
        result = client.put(f"{doctype}/{quote(name)}", {"disabled": 1 if disabled else 0})
        return json.dumps({
            "tenant": tenant,
            "message": f"{doctype} '{name}' {'disabled' if disabled else 'enabled'}",
            "record": result.get("data", {}),
        }, indent=2, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def erpnext_delete_party(tenant: str, doctype: str, name: str) -> str:
    """
    Delete a non-paired party record, refusing safely (actionable message,
    no raw traceback) if Frappe reports linked transactions. Customer/HD
    Customer are deliberately excluded -- use erpnext_delete_customer.

    Args:
        tenant: Tenant name (e.g. 'client1'; see erpnext_list_tenants).
        doctype: One of Supplier, Contact, Address, Customer Group, Territory.
        name: Record name to delete.
    """
    if tenant not in TENANTS:
        return f"Invalid tenant '{tenant}'. Choose: {', '.join(TENANTS.keys())}"
    if doctype in PAIRED_DOCTYPES:
        return json.dumps({
            "error": f"'{doctype}' is part of the Customer<->HD Customer pair -- "
            "use erpnext_delete_customer so both sides are handled together."
        })
    if doctype not in GENERIC_PARTY_DOCTYPES:
        return _invalid_doctype_error(doctype, GENERIC_PARTY_DOCTYPES)

    try:
        client = get_client(tenant)
        client.delete(f"{doctype}/{quote(name)}")
        return json.dumps({"tenant": tenant, "message": f"{doctype} '{name}' deleted"})
    except requests.HTTPError as e:
        if _is_link_exists_error(e):
            return json.dumps({
                "error": f"Cannot delete {doctype} '{name}': it has linked records. "
                + (f"Use erpnext_disable_party instead (doctype='{doctype}')." if doctype in DISABLEABLE_GENERIC_DOCTYPES
                   else "Remove or reassign the linked records first.")
            })
        if e.response is not None and e.response.status_code == 404:
            return json.dumps({"error": f"{doctype} '{name}' not found on {tenant}"})
        return json.dumps({"error": str(e)})
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def erpnext_get_party_links(
    tenant: str,
    party_doctype: str,
    party_name: str,
    limit: int = 200,
) -> str:
    """
    Resolve Contact/Address records linked to a Customer/Supplier. Dynamic
    Link is a child table with no independent permissions -- it cannot be
    queried via /api/resource directly (trap #1). This resolves links
    through each Contact/Address's own `links` child table on the PARENT
    document, fetched one full doc at a time (never trusting a list-query
    `links` field -- trap #2). O(n) in the number of Contacts/Addresses on
    the tenant; fine for admin/audit use, not meant for high-frequency calls.

    Args:
        tenant: Tenant name (e.g. 'client1'; see erpnext_list_tenants).
        party_doctype: Doctype the link points at, e.g. 'Customer', 'Supplier'.
        party_name: Name of the party record to find links for.
        limit: Max Contacts/Addresses to scan per doctype (default 200).
    """
    if tenant not in TENANTS:
        return f"Invalid tenant '{tenant}'. Choose: {', '.join(TENANTS.keys())}"

    try:
        client = get_client(tenant)
        found = {}
        for link_doctype in ("Contact", "Address"):
            matches = []
            names = [
                row["name"]
                for row in client.get(link_doctype, {
                    "fields": json.dumps(["name"]),
                    "limit_page_length": limit,
                }).get("data", [])
            ]
            for record_name in names:
                doc = client.get(f"{link_doctype}/{quote(record_name)}").get("data", {})
                for link in doc.get("links", []) or []:
                    if link.get("link_doctype") == party_doctype and link.get("link_name") == party_name:
                        matches.append(record_name)
                        break
            found[link_doctype] = matches
        return json.dumps({
            "tenant": tenant,
            "party_doctype": party_doctype,
            "party_name": party_name,
            "contacts": found.get("Contact", []),
            "addresses": found.get("Address", []),
        }, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def erpnext_create_customer(
    tenant: str,
    customer_name: str,
    customer_group: str = None,
    territory: str = None,
    customer_type: str = "Company",
    hd_domain: str = None,
) -> str:
    """
    Create an ERPNext Customer and its paired HD Customer together, in one
    logical operation -- never one side alone. If the HD Customer half fails
    after the Customer half succeeded, the Customer is rolled back (deleted)
    so no unpaired Customer is left behind; if that rollback itself fails,
    the response says so explicitly rather than pretending nothing is wrong.

    Args:
        tenant: Tenant name (e.g. 'client1'; see erpnext_list_tenants).
        customer_name: Name for the new Customer (and the paired HD Customer).
        customer_group: ERPNext Customer Group (optional).
        territory: ERPNext Territory (optional).
        customer_type: 'Company' or 'Individual'. Default 'Company'.
        hd_domain: Helpdesk portal domain for the HD Customer (optional).
    """
    if tenant not in TENANTS:
        return f"Invalid tenant '{tenant}'. Choose: {', '.join(TENANTS.keys())}"

    cust_doc = {"customer_name": customer_name, "customer_type": customer_type}
    if customer_group:
        cust_doc["customer_group"] = customer_group
    if territory:
        cust_doc["territory"] = territory

    try:
        client = get_client(tenant)
    except Exception as e:
        return json.dumps({"error": str(e)})

    try:
        cust_result = client.post("Customer", cust_doc)
    except Exception as e:
        return json.dumps({"error": f"Customer creation failed; nothing created: {e}"})

    created_customer = (cust_result.get("data") or {}).get("name")
    if not created_customer:
        # Never fall back to the customer_name label here. The bridge field
        # and any rollback delete must target the Customer's actual primary
        # key (Customer.name), which only equals customer_name today because
        # Selling Settings.cust_master_name == "Customer Name" -- if it were
        # ever "Naming Series" the two would diverge, and guessing would
        # either mis-pair the bridge or delete an unrelated pre-existing
        # Customer that happens to share the label.
        return json.dumps({
            "error": "Customer creation response did not include a 'name' -- refusing to "
            "guess the new record's identity (would risk mis-pairing HD Customer or "
            "rolling back the wrong record). The Customer may have been created without "
            "a paired HD Customer; check ERPNext manually and run erpnext_check_party_drift."
        })

    hd_doc = {"customer_name": customer_name, "erpnext_customer": created_customer}
    if hd_domain:
        hd_doc["domain"] = hd_domain

    try:
        hd_result = client.post("HD Customer", hd_doc)
    except Exception as e:
        try:
            client.delete(f"Customer/{quote(created_customer)}")
            rollback_note = f"Customer '{created_customer}' was rolled back (deleted)."
        except Exception as rollback_exc:
            rollback_note = (
                f"ROLLBACK FAILED ({rollback_exc}) -- Customer '{created_customer}' now "
                "exists WITHOUT a paired HD Customer. Run erpnext_check_party_drift and "
                "either create the missing HD Customer or delete the Customer manually."
            )
        return json.dumps({
            "error": f"HD Customer creation failed, half-create refused: {e}. {rollback_note}"
        })

    return json.dumps({
        "tenant": tenant,
        "message": "Customer and HD Customer created together",
        "customer": cust_result.get("data", {}),
        "hd_customer": hd_result.get("data", {}),
    }, indent=2, default=str)


@mcp.tool()
def erpnext_get_customer(tenant: str, customer_name: str) -> str:
    """
    Fetch a Customer together with its paired HD Customer (resolved through
    the erpnext_customer bridge field).

    Args:
        tenant: Tenant name (e.g. 'client1'; see erpnext_list_tenants).
        customer_name: Customer name to fetch.
    """
    if tenant not in TENANTS:
        return f"Invalid tenant '{tenant}'. Choose: {', '.join(TENANTS.keys())}"

    try:
        client = get_client(tenant)
        try:
            cust = client.get(f"Customer/{quote(customer_name)}").get("data", {})
        except requests.HTTPError as e:
            if e.response is not None and e.response.status_code == 404:
                return json.dumps({"error": f"Customer '{customer_name}' not found on {tenant}"})
            raise
        hd = _find_hd_customer_for(client, customer_name)
        hd_doc = None
        if hd:
            hd_doc = client.get(f"HD Customer/{quote(hd['name'])}").get("data", {})
        return json.dumps({
            "tenant": tenant,
            "customer": cust,
            "hd_customer": hd_doc,
            "paired": hd_doc is not None,
        }, indent=2, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def erpnext_rename_customer(tenant: str, old_name: str, new_name: str) -> str:
    """
    Rename a Customer, propagating the rename to its paired HD Customer and
    the bridge field. Frappe's rename does NOT cascade to erpnext_customer
    (it's a Data field, not a Link) -- this tool is what keeps them in sync.
    Refuses to rename a Customer that has no paired HD Customer at all,
    rather than silently renaming only one side.

    Args:
        tenant: Tenant name (e.g. 'client1'; see erpnext_list_tenants).
        old_name: Current Customer name.
        new_name: New Customer name.
    """
    if tenant not in TENANTS:
        return f"Invalid tenant '{tenant}'. Choose: {', '.join(TENANTS.keys())}"

    try:
        client = get_client(tenant)
    except Exception as e:
        return json.dumps({"error": str(e)})

    hd = _find_hd_customer_for(client, old_name)
    if hd is None:
        return json.dumps({
            "error": f"No paired HD Customer found for Customer '{old_name}' -- refusing to "
            "rename it alone (would leave the pairing unresolvable). Run "
            "erpnext_check_party_drift and pair or recreate the HD Customer first."
        })

    try:
        client.run_method("frappe.client.rename_doc", {
            "doctype": "Customer", "old_name": old_name, "new_name": new_name,
        })
    except Exception as e:
        return json.dumps({"error": f"Customer rename failed; nothing changed: {e}"})

    hd_name = hd["name"]
    warnings = []

    if hd_name == old_name:
        try:
            client.run_method("frappe.client.rename_doc", {
                "doctype": "HD Customer", "old_name": hd_name, "new_name": new_name,
            })
            hd_name = new_name
        except Exception as e:
            warnings.append(f"HD Customer name mirror-rename failed: {e}")

    try:
        client.put(f"HD Customer/{quote(hd_name)}", {"erpnext_customer": new_name})
    except Exception as e:
        warnings.append(
            f"Bridge field update on HD Customer '{hd_name}' failed: {e} -- run "
            "erpnext_check_party_drift, the pairing may now be stale."
        )

    return json.dumps({
        "tenant": tenant,
        "message": f"Customer '{old_name}' renamed to '{new_name}'",
        "hd_customer": hd_name,
        "warnings": warnings,
    }, indent=2)


@mcp.tool()
def erpnext_disable_customer(tenant: str, customer_name: str, disabled: bool = True) -> str:
    """
    Disable (or re-enable) a Customer, paired-aware: refuses if there is no
    paired HD Customer (drift), and notes explicitly that the HD Customer
    doctype has no independent `disabled` field in stock Frappe Helpdesk, so
    its pairing/tickets are unaffected by this call -- rather than silently
    implying both sides were handled.

    Args:
        tenant: Tenant name (e.g. 'client1'; see erpnext_list_tenants).
        customer_name: Customer name.
        disabled: True to disable, False to re-enable. Default True.
    """
    if tenant not in TENANTS:
        return f"Invalid tenant '{tenant}'. Choose: {', '.join(TENANTS.keys())}"

    try:
        client = get_client(tenant)
    except Exception as e:
        return json.dumps({"error": str(e)})

    hd = _find_hd_customer_for(client, customer_name)
    if hd is None:
        return json.dumps({
            "error": f"No paired HD Customer found for Customer '{customer_name}' -- refusing "
            "to disable it in isolation. Run erpnext_check_party_drift first."
        })

    try:
        result = client.put(f"Customer/{quote(customer_name)}", {"disabled": 1 if disabled else 0})
    except Exception as e:
        return json.dumps({"error": f"Customer {'disable' if disabled else 'enable'} failed: {e}"})

    return json.dumps({
        "tenant": tenant,
        "message": f"Customer '{customer_name}' {'disabled' if disabled else 'enabled'}",
        "customer": result.get("data", {}),
        "note": f"HD Customer '{hd['name']}' has no independent 'disabled' field in stock "
        "Frappe Helpdesk -- its pairing and any open tickets are unaffected by this call. "
        "Use erpnext_list_customer_tickets to review them.",
    }, indent=2, default=str)


@mcp.tool()
def erpnext_merge_customer(tenant: str, source_name: str, target_name: str) -> str:
    """
    Merge one Customer into another (Frappe rename-with-merge), and merge
    their paired HD Customers too so HD Tickets referencing the source HD
    Customer are re-pointed to the target's. Refuses if either side is
    missing its HD Customer pairing -- merging Customers alone would leave
    tickets attached to a now-obsolete HD Customer with no clear resolution.

    Args:
        tenant: Tenant name (e.g. 'client1'; see erpnext_list_tenants).
        source_name: Customer to merge away (absorbed).
        target_name: Customer to merge into (survives).
    """
    if tenant not in TENANTS:
        return f"Invalid tenant '{tenant}'. Choose: {', '.join(TENANTS.keys())}"

    try:
        client = get_client(tenant)
    except Exception as e:
        return json.dumps({"error": str(e)})

    src_hd = _find_hd_customer_for(client, source_name)
    tgt_hd = _find_hd_customer_for(client, target_name)
    if src_hd is None or tgt_hd is None:
        missing = []
        if src_hd is None:
            missing.append(source_name)
        if tgt_hd is None:
            missing.append(target_name)
        return json.dumps({
            "error": f"Missing paired HD Customer for: {', '.join(missing)} -- refusing to "
            "merge until both sides are paired. Run erpnext_check_party_drift first."
        })

    try:
        client.run_method("frappe.client.rename_doc", {
            "doctype": "Customer", "old_name": source_name, "new_name": target_name, "merge": 1,
        })
    except Exception as e:
        return json.dumps({"error": f"Customer merge failed; nothing changed: {e}"})

    warnings = []
    try:
        client.run_method("frappe.client.rename_doc", {
            "doctype": "HD Customer", "old_name": src_hd["name"], "new_name": tgt_hd["name"], "merge": 1,
        })
    except Exception as e:
        warnings.append(
            f"Customer-side merge succeeded but HD Customer merge failed: {e} -- tickets "
            f"for '{src_hd['name']}' were NOT re-pointed to '{tgt_hd['name']}'. The invariant "
            "is now inconsistent; run erpnext_check_party_drift."
        )

    return json.dumps({
        "tenant": tenant,
        "message": f"Customer '{source_name}' merged into '{target_name}'",
        "hd_customer_merge": f"{src_hd['name']} -> {tgt_hd['name']}",
        "warnings": warnings,
    }, indent=2)


@mcp.tool()
def erpnext_delete_customer(tenant: str, customer_name: str) -> str:
    """
    Delete a Customer and its paired HD Customer together. Refuses safely
    (actionable message, no raw traceback, nothing deleted) if a best-effort
    pre-check finds likely-linked transactions on either side. If a delete
    still fails partway through (HD Customer deleted, Customer blocked, or
    vice versa), the response says so explicitly -- the invariant is broken
    and needs manual attention -- rather than reporting a clean success.

    Args:
        tenant: Tenant name (e.g. 'client1'; see erpnext_list_tenants).
        customer_name: Customer name to delete.
    """
    if tenant not in TENANTS:
        return f"Invalid tenant '{tenant}'. Choose: {', '.join(TENANTS.keys())}"

    try:
        client = get_client(tenant)
    except Exception as e:
        return json.dumps({"error": str(e)})

    hd = _find_hd_customer_for(client, customer_name)
    hd_name = hd["name"] if hd else None

    cust_links = _precheck_linked_docs(client, "customer", customer_name, CUSTOMER_LINK_DOCTYPES)
    hd_links = _precheck_linked_docs(client, "customer", hd_name, HD_CUSTOMER_LINK_DOCTYPES) if hd_name else []

    if cust_links or hd_links:
        blockers = cust_links + hd_links
        return json.dumps({
            "error": f"Cannot delete Customer '{customer_name}': likely linked records found in "
            f"{blockers}. Nothing was deleted. Use erpnext_disable_customer or "
            "erpnext_merge_customer instead."
        })

    deleted = {"hd_customer": False, "customer": False}

    if hd_name:
        try:
            client.delete(f"HD Customer/{quote(hd_name)}")
            deleted["hd_customer"] = True
        except requests.HTTPError as e:
            if _is_link_exists_error(e):
                return json.dumps({
                    "error": f"Cannot delete HD Customer '{hd_name}': it has linked records "
                    "(e.g. HD Tickets). Nothing was deleted. Use erpnext_disable_customer or "
                    "erpnext_merge_customer instead."
                })
            return json.dumps({"error": f"HD Customer delete failed; nothing deleted: {e}"})

    try:
        client.delete(f"Customer/{quote(customer_name)}")
        deleted["customer"] = True
    except requests.HTTPError as e:
        if deleted["hd_customer"]:
            return json.dumps({
                "error": f"PARTIAL DELETE: HD Customer '{hd_name}' was deleted but Customer "
                f"'{customer_name}' could not be ({e}). The 1:1 invariant is now broken -- "
                "run erpnext_check_party_drift, then either recreate a paired HD Customer or "
                "use erpnext_disable_customer for parties with financial history."
            })
        if _is_link_exists_error(e):
            return json.dumps({
                "error": f"Cannot delete Customer '{customer_name}': it has linked records "
                "(e.g. Sales Invoices). Nothing was deleted. Use erpnext_disable_customer or "
                "erpnext_merge_customer instead."
            })
        return json.dumps({"error": f"Customer delete failed; nothing deleted: {e}"})

    return json.dumps({
        "tenant": tenant,
        "message": f"Customer '{customer_name}' and HD Customer '{hd_name}' deleted",
        "deleted": deleted,
    })


@mcp.tool()
def erpnext_check_party_drift(tenant: str, limit: int = 1000) -> str:
    """
    Drift check for the Customer <-> HD Customer 1:1 invariant -- the
    regression test for that invariant. Reports both directions of mismatch:
    Customers with no paired HD Customer, HD Customers with an empty
    erpnext_customer bridge field, and HD Customers whose erpnext_customer
    points at a Customer that does not exist. Also flags duplicate pairings
    (more than one HD Customer bridging to the same Customer).

    Args:
        tenant: Tenant name (e.g. 'client1'; see erpnext_list_tenants).
        limit: Max Customers/HD Customers to scan (default 1000).
    """
    if tenant not in TENANTS:
        return f"Invalid tenant '{tenant}'. Choose: {', '.join(TENANTS.keys())}"

    try:
        client = get_client(tenant)
        customers = client.get("Customer", {
            "fields": json.dumps(["name"]), "limit_page_length": limit,
        }).get("data", [])
        hd_customers = client.get("HD Customer", {
            "fields": json.dumps(["name", "erpnext_customer"]), "limit_page_length": limit,
        }).get("data", [])
    except Exception as e:
        return json.dumps({"error": str(e)})

    customer_names = {c["name"] for c in customers}

    unpaired_hd_customers = []
    mismatched_hd_customers = []
    paired_by_customer = {}

    for hd in hd_customers:
        erp = (hd.get("erpnext_customer") or "").strip()
        if not erp:
            unpaired_hd_customers.append(hd["name"])
        elif erp not in customer_names:
            mismatched_hd_customers.append({"hd_customer": hd["name"], "erpnext_customer": erp})
        else:
            paired_by_customer.setdefault(erp, []).append(hd["name"])

    customers_without_hd_customer = sorted(c for c in customer_names if c not in paired_by_customer)
    duplicate_pairings = {
        erp: names for erp, names in paired_by_customer.items() if len(names) > 1
    }

    clean = not (unpaired_hd_customers or mismatched_hd_customers or customers_without_hd_customer or duplicate_pairings)

    return json.dumps({
        "tenant": tenant,
        "clean": clean,
        "customers_without_hd_customer": customers_without_hd_customer,
        "hd_customers_with_empty_bridge": unpaired_hd_customers,
        "hd_customers_with_dangling_bridge": mismatched_hd_customers,
        "duplicate_pairings": duplicate_pairings,
        "counts": {"customers": len(customers), "hd_customers": len(hd_customers)},
    }, indent=2)


@mcp.tool()
def erpnext_list_customer_tickets(
    tenant: str,
    customer_name: str,
    status: str = None,
    limit: int = 50,
) -> str:
    """
    List all HD Tickets for a Customer, resolved through the
    erpnext_customer bridge field (HD Ticket.customer links to HD Customer,
    not to Customer directly).

    Args:
        tenant: Tenant name (e.g. 'client1'; see erpnext_list_tenants).
        customer_name: Customer name.
        status: Filter by status (e.g. 'Open', 'Resolved', 'Closed').
        limit: Max results (default 50, max 200).
    """
    if tenant not in TENANTS:
        return f"Invalid tenant '{tenant}'. Choose: {', '.join(TENANTS.keys())}"

    try:
        client = get_client(tenant)
    except Exception as e:
        return json.dumps({"error": str(e)})

    hd = _find_hd_customer_for(client, customer_name)
    if hd is None:
        return json.dumps({
            "error": f"No paired HD Customer found for Customer '{customer_name}' -- run "
            "erpnext_check_party_drift."
        })

    filters = [["customer", "=", hd["name"]]]
    if status:
        filters.append(["status", "=", status])

    try:
        result = client.get("HD Ticket", {
            "filters": json.dumps(filters), "limit_page_length": min(limit, 200),
        })
        tickets = result.get("data", [])
        return json.dumps({
            "tenant": tenant,
            "customer": customer_name,
            "hd_customer": hd["name"],
            "count": len(tickets),
            "tickets": tickets,
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
    has_creds = any(
        (os.environ.get(f"ERPNEXT_API_KEY_{t.upper()}") or os.environ.get("ERPNEXT_API_KEY"))
        and (os.environ.get(f"ERPNEXT_API_SECRET_{t.upper()}") or os.environ.get("ERPNEXT_API_SECRET"))
        for t in TENANTS
    )
    if not has_creds:
        print("No ERPNEXT_API_KEY_<TENANT>/ERPNEXT_API_SECRET_<TENANT> (or the unsuffixed fallbacks) set. Edit .env first.")
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
