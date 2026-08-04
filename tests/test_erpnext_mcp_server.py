"""Tests for mcp/erpnext-mcp-server.py -- party management (opskit issue #74).

Everything here is offline: FrappeClient is replaced with a MagicMock double
(spec'd against the real class so a call to a nonexistent method fails loudly)
and `get_client` is monkeypatched to hand that double back -- no network, no
live Frappe/ERPNext call, ever. The module is loaded fresh per test via
importlib (mirrors tests/test_frappe_exec.py) because the file lives at
mcp/erpnext-mcp-server.py, not an importable package name.

Coverage focus (opskit issue #74):
  - the 1:1 Customer <-> HD Customer invariant: paired create (and refused
    half-create with rollback), rename propagation, paired disable/delete,
    merge
  - the drift check, in both directions of mismatch
  - the two confirmed API traps: Dynamic Link cannot be queried directly,
    and child-table fields are silently dropped from list queries -- so a
    tool must never trust a list response for a child-table field
  - delete refusing (actionable message) rather than a raw traceback when
    Frappe reports linked records
"""

import importlib.util
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import requests

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "mcp" / "erpnext-mcp-server.py"


def load_module():
    spec = importlib.util.spec_from_file_location("erpnext_mcp_under_test", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


TENANT = "client1"  # the tenant key baked into the fixture below


@pytest.fixture
def isolated_tenants_file(tmp_path, monkeypatch):
    """Point ERPNEXT_TENANTS_FILE at a throwaway fixture file so the module
    (loaded fresh per test via `load_module`, below) never reads a
    developer's real, gitignored mcp/tenants.local.json -- whether or not
    one exists, and regardless of what it contains (opskit issue #76: the
    suite used to inherit whatever that file happened to hold, so it passed
    with no local file and failed for anyone with real tenant config)."""
    fixture_file = tmp_path / "tenants.local.json"
    fixture_file.write_text(json.dumps({
        TENANT: {"site": "helpdesk.example.org", "description": "Fixture tenant for tests"},
    }))
    monkeypatch.setenv("ERPNEXT_TENANTS_FILE", str(fixture_file))
    return fixture_file


@pytest.fixture
def mod(isolated_tenants_file):
    return load_module()


@pytest.fixture
def fake_client(mod):
    """A FrappeClient double, spec'd so typos/renamed methods fail loudly.
    Individual tests configure .get/.post/.put/.delete/.run_method as needed."""
    return MagicMock(spec=mod.FrappeClient)


@pytest.fixture
def wire_client(mod, fake_client, monkeypatch):
    """Point get_client(tenant) at fake_client for every tenant."""
    monkeypatch.setattr(mod, "get_client", lambda tenant: fake_client)
    return fake_client


def http_error(status_code=409, body=None):
    resp = requests.Response()
    resp.status_code = status_code
    if body is not None:
        resp._content = json.dumps(body).encode("utf-8")
    return requests.HTTPError(response=resp)


# ---------------------------------------------------------------------------
# Trap #1 -- Dynamic Link is a child table, cannot be queried via /api/resource
# Trap #2 -- child-table fields are silently dropped from list results
# ---------------------------------------------------------------------------

class TestChildTableTrap:
    def test_list_party_refuses_child_table_field(self, mod, wire_client):
        result = json.loads(mod.erpnext_list_party(
            tenant=TENANT, doctype="Contact", fields=json.dumps(["name", "links"]),
        ))
        assert "error" in result
        assert "child-table" in result["error"]
        # Must refuse BEFORE ever hitting the API -- no query attempted at all.
        wire_client.get.assert_not_called()

    def test_list_party_allows_plain_fields(self, mod, wire_client):
        wire_client.get.return_value = {"data": [{"name": "C-0001"}]}
        result = json.loads(mod.erpnext_list_party(tenant=TENANT, doctype="Contact"))
        assert result["count"] == 1
        wire_client.get.assert_called_once()

    def test_get_party_always_fetches_single_doc(self, mod, wire_client):
        """Requesting fields=['name','links'] on a LIST endpoint returns bare
        'name' with no error -- erpnext_get_party must never go through the
        list endpoint, so `links` is always genuinely present."""
        wire_client.get.return_value = {
            "data": {"name": "C-0001", "links": [{"link_doctype": "Customer", "link_name": "Acme"}]}
        }
        result = json.loads(mod.erpnext_get_party(tenant=TENANT, doctype="Contact", name="C-0001"))
        assert result["record"]["links"] == [{"link_doctype": "Customer", "link_name": "Acme"}]
        # The resource path must be the single-doc form "Contact/C-0001", not
        # a list call with a fields= filter.
        called_resource = wire_client.get.call_args[0][0]
        assert called_resource == "Contact/C-0001"

    def test_get_party_links_never_queries_dynamic_link_directly(self, mod, wire_client):
        """Trap #1: /api/resource/Dynamic Link raises PermissionError. This
        tool must reach party links only through the parent (Contact/Address)
        document, never by naming 'Dynamic Link' as a resource."""

        def fake_get(resource, params=None):
            if resource == "Contact":
                return {"data": [{"name": "CT-1"}, {"name": "CT-2"}]}
            if resource == "Address":
                return {"data": []}
            if resource == "Contact/CT-1":
                return {"data": {"name": "CT-1", "links": [{"link_doctype": "Customer", "link_name": "Acme"}]}}
            if resource == "Contact/CT-2":
                return {"data": {"name": "CT-2", "links": [{"link_doctype": "Customer", "link_name": "Other"}]}}
            raise AssertionError(f"unexpected resource queried: {resource}")

        wire_client.get.side_effect = fake_get
        result = json.loads(mod.erpnext_get_party_links(
            tenant=TENANT, party_doctype="Customer", party_name="Acme",
        ))
        assert result["contacts"] == ["CT-1"]
        assert result["addresses"] == []
        # No call ever named "Dynamic Link" as a resource.
        for call in wire_client.get.call_args_list:
            assert "Dynamic Link" not in call.args[0]

    def test_get_party_links_would_miss_everything_if_it_trusted_list_links(self, mod, wire_client):
        """Regression guard for the false-orphan failure mode described in
        the issue: if this tool ever regresses to reading `links` off a LIST
        response, every contact would look linkless. Simulate exactly that
        broken list response (bare 'name' only) alongside a correct
        single-doc response, and confirm the tool still finds the match --
        proving it is not relying on the list response's (missing) links."""

        def fake_get(resource, params=None):
            if resource == "Contact":
                # Trap #2 in action: no 'links' key at all, even though the
                # caller asked a list-style query for it elsewhere.
                return {"data": [{"name": "CT-1"}]}
            if resource == "Address":
                return {"data": []}
            if resource == "Contact/CT-1":
                return {"data": {"name": "CT-1", "links": [{"link_doctype": "Customer", "link_name": "Acme"}]}}
            raise AssertionError(f"unexpected resource queried: {resource}")

        wire_client.get.side_effect = fake_get
        result = json.loads(mod.erpnext_get_party_links(
            tenant=TENANT, party_doctype="Customer", party_name="Acme",
        ))
        assert result["contacts"] == ["CT-1"]


# ---------------------------------------------------------------------------
# The 1:1 invariant -- paired create
# ---------------------------------------------------------------------------

class TestCreateCustomerPaired:
    def test_creates_both_records_together(self, mod, wire_client):
        wire_client.post.side_effect = [
            {"data": {"name": "Acme"}},
            {"data": {"name": "Acme", "erpnext_customer": "Acme"}},
        ]
        result = json.loads(mod.erpnext_create_customer(tenant=TENANT, customer_name="Acme"))
        assert "error" not in result
        assert result["customer"]["name"] == "Acme"
        assert result["hd_customer"]["erpnext_customer"] == "Acme"

        (cust_doctype, cust_doc), _ = wire_client.post.call_args_list[0]
        (hd_doctype, hd_doc), _ = wire_client.post.call_args_list[1]
        assert cust_doctype == "Customer"
        assert hd_doctype == "HD Customer"
        assert hd_doc["erpnext_customer"] == "Acme"

    def test_half_create_is_refused_and_rolled_back(self, mod, wire_client):
        wire_client.post.side_effect = [
            {"data": {"name": "Acme"}},          # Customer succeeds
            RuntimeError("HD Customer schema rejected the payload"),  # HD Customer fails
        ]
        wire_client.delete.return_value = {}

        result = json.loads(mod.erpnext_create_customer(tenant=TENANT, customer_name="Acme"))
        assert "error" in result
        assert "half-create" in result["error"].lower()
        wire_client.delete.assert_called_once_with("Customer/Acme")

    def test_half_create_rollback_failure_is_reported_not_hidden(self, mod, wire_client):
        wire_client.post.side_effect = [
            {"data": {"name": "Acme"}},
            RuntimeError("HD Customer schema rejected the payload"),
        ]
        wire_client.delete.side_effect = RuntimeError("delete also failed")

        result = json.loads(mod.erpnext_create_customer(tenant=TENANT, customer_name="Acme"))
        assert "ROLLBACK FAILED" in result["error"]
        assert "Acme" in result["error"]

    def test_customer_creation_failure_creates_nothing(self, mod, wire_client):
        wire_client.post.side_effect = RuntimeError("Customer validation failed")
        result = json.loads(mod.erpnext_create_customer(tenant=TENANT, customer_name="Acme"))
        assert "error" in result
        wire_client.delete.assert_not_called()
        assert wire_client.post.call_count == 1

    def test_bridge_uses_actual_returned_name_not_input_label(self, mod, wire_client):
        """Guards the Customer <-> HD Customer bridge against conflating the
        display label (customer_name) with the real primary key
        (Customer.name). Today cust_master_name == "Customer Name" so the two
        happen to match, but if it were ever "Naming Series" Customer.name
        would be a generated value like 'CUST-00042' while customer_name
        stayed the display label -- the bridge must resolve to the real
        primary key regardless."""
        wire_client.post.side_effect = [
            {"data": {"name": "CUST-00042"}},  # Customer.name != customer_name
            {"data": {"name": "Acme Corp", "erpnext_customer": "CUST-00042"}},
        ]
        result = json.loads(mod.erpnext_create_customer(tenant=TENANT, customer_name="Acme Corp"))
        assert "error" not in result

        (_, hd_doc), _ = wire_client.post.call_args_list[1]
        assert hd_doc["erpnext_customer"] == "CUST-00042"
        assert hd_doc["erpnext_customer"] != "Acme Corp"

    def test_missing_created_name_in_response_refuses_rather_than_guessing(self, mod, wire_client):
        """If the Customer POST response is missing 'data.name', the code must
        not fall back to guessing the primary key from customer_name -- that
        guess could mis-pair the bridge or, on rollback, delete an unrelated
        pre-existing Customer that happens to share the label."""
        wire_client.post.return_value = {"data": {}}
        result = json.loads(mod.erpnext_create_customer(tenant=TENANT, customer_name="Acme"))
        assert "error" in result
        assert wire_client.post.call_count == 1  # HD Customer must never be attempted
        wire_client.delete.assert_not_called()


# ---------------------------------------------------------------------------
# Rename propagation
# ---------------------------------------------------------------------------

class TestRenamePropagation:
    def test_rename_propagates_mirrored_name_and_bridge(self, mod, wire_client):
        # Mirrored naming: HD Customer's own name equals the old Customer name.
        wire_client.get.return_value = {"data": [{"name": "OldCo", "erpnext_customer": "OldCo"}]}
        wire_client.run_method.return_value = {}
        wire_client.put.return_value = {}

        result = json.loads(mod.erpnext_rename_customer(tenant=TENANT, old_name="OldCo", new_name="NewCo"))
        assert "error" not in result
        assert result["warnings"] == []

        rename_calls = wire_client.run_method.call_args_list
        assert rename_calls[0].args[0] == "frappe.client.rename_doc"
        assert rename_calls[0].args[1]["doctype"] == "Customer"
        assert rename_calls[0].args[1]["old_name"] == "OldCo"
        assert rename_calls[0].args[1]["new_name"] == "NewCo"
        assert rename_calls[1].args[1]["doctype"] == "HD Customer"
        assert rename_calls[1].args[1]["old_name"] == "OldCo"
        assert rename_calls[1].args[1]["new_name"] == "NewCo"

        put_resource, put_doc = wire_client.put.call_args.args
        assert put_resource == "HD Customer/NewCo"
        assert put_doc == {"erpnext_customer": "NewCo"}

    def test_rename_with_distinct_hd_name_updates_bridge_only(self, mod, wire_client):
        wire_client.get.return_value = {"data": [{"name": "HD-9", "erpnext_customer": "OldCo"}]}
        wire_client.run_method.return_value = {}
        wire_client.put.return_value = {}

        result = json.loads(mod.erpnext_rename_customer(tenant=TENANT, old_name="OldCo", new_name="NewCo"))
        assert "error" not in result

        # Only the Customer itself was renamed -- HD Customer keeps its own name.
        assert wire_client.run_method.call_count == 1
        put_resource, put_doc = wire_client.put.call_args.args
        assert put_resource == "HD Customer/HD-9"
        assert put_doc == {"erpnext_customer": "NewCo"}

    def test_rename_refuses_when_unpaired(self, mod, wire_client):
        wire_client.get.return_value = {"data": []}
        result = json.loads(mod.erpnext_rename_customer(tenant=TENANT, old_name="Ghost", new_name="NewCo"))
        assert "error" in result
        wire_client.run_method.assert_not_called()

    def test_rename_customer_side_failure_leaves_nothing_changed(self, mod, wire_client):
        wire_client.get.return_value = {"data": [{"name": "OldCo", "erpnext_customer": "OldCo"}]}
        wire_client.run_method.side_effect = RuntimeError("rename_doc rejected")
        result = json.loads(mod.erpnext_rename_customer(tenant=TENANT, old_name="OldCo", new_name="NewCo"))
        assert "error" in result
        wire_client.put.assert_not_called()


# ---------------------------------------------------------------------------
# Drift check -- the regression test for the invariant, both directions
# ---------------------------------------------------------------------------

class TestDriftCheck:
    def _wire(self, wire_client, customers, hd_customers):
        wire_client.get.side_effect = lambda resource, params=None: (
            {"data": customers} if resource == "Customer" else {"data": hd_customers}
        )

    def test_clean_when_fully_paired(self, mod, wire_client):
        self._wire(wire_client, [{"name": "A"}], [{"name": "hdA", "erpnext_customer": "A"}])
        result = json.loads(mod.erpnext_check_party_drift(tenant=TENANT))
        assert result["clean"] is True
        assert result["customers_without_hd_customer"] == []
        assert result["hd_customers_with_empty_bridge"] == []
        assert result["hd_customers_with_dangling_bridge"] == []

    def test_detects_customer_with_no_hd_customer(self, mod, wire_client):
        self._wire(
            wire_client,
            [{"name": "A"}, {"name": "B"}],
            [{"name": "hdA", "erpnext_customer": "A"}],
        )
        result = json.loads(mod.erpnext_check_party_drift(tenant=TENANT))
        assert result["clean"] is False
        assert result["customers_without_hd_customer"] == ["B"]

    def test_detects_empty_bridge(self, mod, wire_client):
        self._wire(
            wire_client,
            [{"name": "A"}],
            [{"name": "hdA", "erpnext_customer": "A"}, {"name": "hdOrphan", "erpnext_customer": ""}],
        )
        result = json.loads(mod.erpnext_check_party_drift(tenant=TENANT))
        assert result["clean"] is False
        assert result["hd_customers_with_empty_bridge"] == ["hdOrphan"]

    def test_detects_dangling_bridge_pointing_at_nonexistent_customer(self, mod, wire_client):
        self._wire(
            wire_client,
            [{"name": "A"}],
            [{"name": "hdA", "erpnext_customer": "A"}, {"name": "hdGhost", "erpnext_customer": "DoesNotExist"}],
        )
        result = json.loads(mod.erpnext_check_party_drift(tenant=TENANT))
        assert result["clean"] is False
        assert {"hd_customer": "hdGhost", "erpnext_customer": "DoesNotExist"} in result["hd_customers_with_dangling_bridge"]

    def test_detects_duplicate_pairing(self, mod, wire_client):
        self._wire(
            wire_client,
            [{"name": "A"}],
            [{"name": "hd1", "erpnext_customer": "A"}, {"name": "hd2", "erpnext_customer": "A"}],
        )
        result = json.loads(mod.erpnext_check_party_drift(tenant=TENANT))
        assert result["clean"] is False
        assert sorted(result["duplicate_pairings"]["A"]) == ["hd1", "hd2"]


# ---------------------------------------------------------------------------
# Delete: refuse safely rather than a raw traceback; never a silent partial
# ---------------------------------------------------------------------------

class TestDeleteCustomer:
    def _wire_no_links(self, wire_client, hd_name="hdA"):
        def fake_get(resource, params=None):
            if resource == "HD Customer":
                return {"data": [{"name": hd_name, "erpnext_customer": "Acme"}]}
            # every precheck probe (Sales Invoice, HD Ticket, ...) comes back empty
            return {"data": []}
        wire_client.get.side_effect = fake_get

    def test_precheck_refuses_when_customer_side_linked(self, mod, wire_client):
        def fake_get(resource, params=None):
            if resource == "HD Customer":
                return {"data": [{"name": "hdA", "erpnext_customer": "Acme"}]}
            if resource == "Sales Invoice":
                return {"data": [{"name": "SINV-0001"}]}
            return {"data": []}
        wire_client.get.side_effect = fake_get

        result = json.loads(mod.erpnext_delete_customer(tenant=TENANT, customer_name="Acme"))
        assert "error" in result
        assert "Sales Invoice" in result["error"]
        wire_client.delete.assert_not_called()

    def test_precheck_refuses_when_hd_ticket_linked(self, mod, wire_client):
        def fake_get(resource, params=None):
            if resource == "HD Customer":
                return {"data": [{"name": "hdA", "erpnext_customer": "Acme"}]}
            if resource == "HD Ticket":
                return {"data": [{"name": "0099"}]}
            return {"data": []}
        wire_client.get.side_effect = fake_get

        result = json.loads(mod.erpnext_delete_customer(tenant=TENANT, customer_name="Acme"))
        assert "error" in result
        assert "HD Ticket" in result["error"]
        wire_client.delete.assert_not_called()

    def test_deletes_both_sides_when_clean(self, mod, wire_client):
        self._wire_no_links(wire_client)
        wire_client.delete.return_value = {}

        result = json.loads(mod.erpnext_delete_customer(tenant=TENANT, customer_name="Acme"))
        assert "error" not in result
        assert result["deleted"] == {"hd_customer": True, "customer": True}
        deleted_resources = [c.args[0] for c in wire_client.delete.call_args_list]
        assert "HD Customer/hdA" in deleted_resources
        assert "Customer/Acme" in deleted_resources

    def test_link_exists_error_translated_to_actionable_message(self, mod, wire_client):
        self._wire_no_links(wire_client)
        wire_client.delete.side_effect = http_error(status_code=409, body={"exc_type": "LinkExistsError"})

        result = json.loads(mod.erpnext_delete_customer(tenant=TENANT, customer_name="Acme"))
        assert "error" in result
        assert "traceback" not in result["error"].lower()
        assert "disable" in result["error"].lower() or "merge" in result["error"].lower()

    def test_partial_delete_is_reported_honestly_not_as_success(self, mod, wire_client):
        self._wire_no_links(wire_client)
        # HD Customer delete succeeds, Customer delete then fails.
        wire_client.delete.side_effect = [
            {},  # HD Customer/hdA succeeds
            http_error(status_code=409, body={"exc_type": "LinkExistsError"}),  # Customer/Acme fails
        ]

        result = json.loads(mod.erpnext_delete_customer(tenant=TENANT, customer_name="Acme"))
        assert "error" in result
        assert "PARTIAL DELETE" in result["error"]
        assert "hdA" in result["error"]
        assert "Acme" in result["error"]


# ---------------------------------------------------------------------------
# Merge
# ---------------------------------------------------------------------------

class TestMergeCustomer:
    def _wire_paired(self, wire_client):
        def fake_get(resource, params=None):
            filters = json.loads(params["filters"])
            value = filters[0][2]
            if value == "Source":
                return {"data": [{"name": "hdSource", "erpnext_customer": "Source"}]}
            if value == "Target":
                return {"data": [{"name": "hdTarget", "erpnext_customer": "Target"}]}
            return {"data": []}
        wire_client.get.side_effect = fake_get

    def test_merges_both_sides(self, mod, wire_client):
        self._wire_paired(wire_client)
        wire_client.run_method.return_value = {}

        result = json.loads(mod.erpnext_merge_customer(tenant=TENANT, source_name="Source", target_name="Target"))
        assert result["warnings"] == []
        calls = wire_client.run_method.call_args_list
        assert calls[0].args[1] == {
            "doctype": "Customer", "old_name": "Source", "new_name": "Target", "merge": 1,
        }
        assert calls[1].args[1] == {
            "doctype": "HD Customer", "old_name": "hdSource", "new_name": "hdTarget", "merge": 1,
        }

    def test_refuses_when_either_side_unpaired(self, mod, wire_client):
        wire_client.get.return_value = {"data": []}
        result = json.loads(mod.erpnext_merge_customer(tenant=TENANT, source_name="Source", target_name="Target"))
        assert "error" in result
        wire_client.run_method.assert_not_called()

    def test_hd_side_merge_failure_reported_as_warning_not_silent(self, mod, wire_client):
        self._wire_paired(wire_client)
        wire_client.run_method.side_effect = [{}, RuntimeError("HD Customer merge rejected")]

        result = json.loads(mod.erpnext_merge_customer(tenant=TENANT, source_name="Source", target_name="Target"))
        assert "error" not in result
        assert result["warnings"], "expected a warning about the inconsistent invariant"
        assert "hdSource" in result["warnings"][0]


# ---------------------------------------------------------------------------
# Generic party tools must refuse Customer/HD Customer where pairing matters
# ---------------------------------------------------------------------------

class TestGenericPartyGuards:
    def test_create_party_rejects_customer(self, mod, wire_client):
        result = json.loads(mod.erpnext_create_party(tenant=TENANT, doctype="Customer", data="{}"))
        assert "error" in result
        assert "erpnext_create_customer" in result["error"]
        wire_client.post.assert_not_called()

    def test_create_party_rejects_hd_customer(self, mod, wire_client):
        result = json.loads(mod.erpnext_create_party(tenant=TENANT, doctype="HD Customer", data="{}"))
        assert "error" in result
        wire_client.post.assert_not_called()

    def test_create_party_allows_supplier(self, mod, wire_client):
        wire_client.post.return_value = {"data": {"name": "Sup-1"}}
        result = json.loads(mod.erpnext_create_party(
            tenant=TENANT, doctype="Supplier", data=json.dumps({"supplier_name": "Acme Supply"}),
        ))
        assert "error" not in result
        wire_client.post.assert_called_once()

    def test_update_party_blocks_bridge_field_edit(self, mod, wire_client):
        result = json.loads(mod.erpnext_update_party(
            tenant=TENANT, doctype="HD Customer", name="hdA",
            data=json.dumps({"erpnext_customer": "SomethingElse"}),
        ))
        assert "error" in result
        assert "erpnext_customer" in result["error"]
        wire_client.put.assert_not_called()

    def test_update_party_allows_other_fields(self, mod, wire_client):
        wire_client.put.return_value = {"data": {"name": "hdA", "domain": "example.org"}}
        result = json.loads(mod.erpnext_update_party(
            tenant=TENANT, doctype="HD Customer", name="hdA", data=json.dumps({"domain": "example.org"}),
        ))
        assert "error" not in result
        wire_client.put.assert_called_once()

    def test_disable_party_rejects_customer(self, mod, wire_client):
        result = json.loads(mod.erpnext_disable_party(tenant=TENANT, doctype="Customer", name="Acme"))
        assert "error" in result
        assert "erpnext_disable_customer" in result["error"]
        wire_client.put.assert_not_called()

    def test_delete_party_rejects_customer(self, mod, wire_client):
        result = json.loads(mod.erpnext_delete_party(tenant=TENANT, doctype="Customer", name="Acme"))
        assert "error" in result
        assert "erpnext_delete_customer" in result["error"]
        wire_client.delete.assert_not_called()

    def test_delete_party_translates_link_exists_error(self, mod, wire_client):
        wire_client.delete.side_effect = http_error(status_code=409, body={"exc_type": "LinkExistsError"})
        result = json.loads(mod.erpnext_delete_party(tenant=TENANT, doctype="Supplier", name="Acme Supply"))
        assert "error" in result
        assert "linked records" in result["error"]

    def test_invalid_doctype_rejected(self, mod, wire_client):
        result = json.loads(mod.erpnext_list_party(tenant=TENANT, doctype="Bogus Doctype"))
        assert "error" in result
        wire_client.get.assert_not_called()


# ---------------------------------------------------------------------------
# Tickets for a party, resolved through the bridge
# ---------------------------------------------------------------------------

class TestListCustomerTickets:
    def test_lists_via_bridge_not_raw_customer_name(self, mod, wire_client):
        def fake_get(resource, params=None):
            if resource == "HD Customer":
                return {"data": [{"name": "hdA", "erpnext_customer": "Acme"}]}
            if resource == "HD Ticket":
                filters = json.loads(params["filters"])
                assert filters[0] == ["customer", "=", "hdA"]
                return {"data": [{"name": "0001"}]}
            raise AssertionError(resource)
        wire_client.get.side_effect = fake_get

        result = json.loads(mod.erpnext_list_customer_tickets(tenant=TENANT, customer_name="Acme"))
        assert result["count"] == 1
        assert result["hd_customer"] == "hdA"

    def test_refuses_when_unpaired(self, mod, wire_client):
        wire_client.get.return_value = {"data": []}
        result = json.loads(mod.erpnext_list_customer_tickets(tenant=TENANT, customer_name="Ghost"))
        assert "error" in result


# ---------------------------------------------------------------------------
# erpnext_get_customer -- paired fetch
# ---------------------------------------------------------------------------

class TestGetCustomer:
    def test_returns_paired_docs(self, mod, wire_client):
        def fake_get(resource, params=None):
            if resource == "Customer/Acme":
                return {"data": {"name": "Acme"}}
            if resource == "HD Customer":
                return {"data": [{"name": "hdA", "erpnext_customer": "Acme"}]}
            if resource == "HD Customer/hdA":
                return {"data": {"name": "hdA", "erpnext_customer": "Acme"}}
            raise AssertionError(resource)
        wire_client.get.side_effect = fake_get

        result = json.loads(mod.erpnext_get_customer(tenant=TENANT, customer_name="Acme"))
        assert result["paired"] is True
        assert result["hd_customer"]["name"] == "hdA"

    def test_reports_unpaired(self, mod, wire_client):
        def fake_get(resource, params=None):
            if resource == "Customer/Acme":
                return {"data": {"name": "Acme"}}
            if resource == "HD Customer":
                return {"data": []}
            raise AssertionError(resource)
        wire_client.get.side_effect = fake_get

        result = json.loads(mod.erpnext_get_customer(tenant=TENANT, customer_name="Acme"))
        assert result["paired"] is False
        assert result["hd_customer"] is None


# ---------------------------------------------------------------------------
# Direct unit tests for the small helpers
# ---------------------------------------------------------------------------

class TestIsLinkExistsError:
    def test_true_on_409(self, mod):
        assert mod._is_link_exists_error(http_error(status_code=409)) is True

    def test_true_when_body_mentions_it(self, mod):
        err = http_error(status_code=417, body={"exc_type": "LinkExistsError", "exception": "..."})
        assert mod._is_link_exists_error(err) is True

    def test_false_for_unrelated_error(self, mod):
        err = http_error(status_code=500, body={"exc_type": "ValidationError"})
        assert mod._is_link_exists_error(err) is False

    def test_false_when_no_response(self, mod):
        assert mod._is_link_exists_error(requests.HTTPError()) is False


class TestFindHdCustomerFor:
    def test_returns_none_when_no_match(self, mod):
        client = MagicMock(spec=mod.FrappeClient)
        client.get.return_value = {"data": []}
        assert mod._find_hd_customer_for(client, "Ghost") is None

    def test_returns_first_match(self, mod):
        client = MagicMock(spec=mod.FrappeClient)
        client.get.return_value = {"data": [{"name": "hdA", "erpnext_customer": "Acme"}]}
        found = mod._find_hd_customer_for(client, "Acme")
        assert found["name"] == "hdA"


# ---------------------------------------------------------------------------
# Regression guard for opskit issue #76: this suite must never depend on the
# presence, absence, or content of a developer's real, gitignored
# mcp/tenants.local.json. The `mod` fixture achieves this by pointing
# ERPNEXT_TENANTS_FILE at a throwaway fixture file (see `isolated_tenants_file`
# above) instead of relying on the module's hardcoded default path. These
# tests pin down that the override is actually load-bearing -- if the
# ERPNEXT_TENANTS_FILE coupling in mcp/erpnext-mcp-server.py were ever
# removed (reverting to reading only the fixed default path), the module
# would fall back to reading whatever is (or isn't) really on disk, and the
# assertions below -- which check for exact fixture content that has nothing
# to do with the default fallback tenant -- would fail.
# ---------------------------------------------------------------------------

class TestTenantConfigIsolation:
    def test_module_tenants_come_from_the_injected_file(self, mod, isolated_tenants_file):
        on_disk = json.loads(isolated_tenants_file.read_text())
        assert mod.TENANTS == on_disk

    def test_env_override_wins_with_multiple_distinct_tenants(self, tmp_path, monkeypatch):
        """A from-scratch check (independent of the `mod`/`isolated_tenants_file`
        fixtures) that ERPNEXT_TENANTS_FILE, when pointed at a file with
        multiple tenants whose keys/sites differ from the module's built-in
        fallback ('client1'), is what the module actually loads."""
        fixture_file = tmp_path / "custom_tenants.json"
        fixture_file.write_text(json.dumps({
            "alpha": {"site": "helpdesk.alpha.example.org", "description": "Fixture tenant alpha"},
            "beta": {"site": "helpdesk.beta.example.org", "description": "Fixture tenant beta"},
        }))
        monkeypatch.setenv("ERPNEXT_TENANTS_FILE", str(fixture_file))

        module = load_module()

        assert set(module.TENANTS) == {"alpha", "beta"}
        assert "client1" not in module.TENANTS
        assert module.TENANTS["alpha"]["site"] == "helpdesk.alpha.example.org"
        assert module.TENANTS["beta"]["site"] == "helpdesk.beta.example.org"
