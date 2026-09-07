"""Tests for mcp/technitium-mcp-server.py — DHCP scope DNS/route tools.

Unit tests that mock the Technitium API to verify dhcp_update_scope_dns and
dhcp_clear_static_routes POST the exact verified param set (no phantom
params), short-circuit unchanged state, refuse a destructive empty-list
input, and verify writes by re-fetching the scope rather than trusting the
write response (opskit #298).
"""

import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "mcp" / "technitium-mcp-server.py"

TOKEN = "test-token"


def _resp(payload):
    r = MagicMock()
    r.json.return_value = payload
    return r


def _import_module():
    import importlib.util
    if "technitium_mcp_server" in sys.modules:
        del sys.modules["technitium_mcp_server"]
    spec = importlib.util.spec_from_file_location("technitium_mcp_server", SERVER)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["technitium_mcp_server"] = mod
    spec.loader.exec_module(mod)
    return mod


def _load_with_mock(mock_requests):
    """Re-import the module with a patched requests, returning the fresh module."""
    sys.modules.pop("technitium_mcp_server", None)
    with patch.dict(sys.modules, {"requests": mock_requests}):
        return _import_module()


class _ScopeApi:
    """Stands in for the Technitium API surface the two tools touch."""

    def __init__(self, scope_before: dict, scope_after: dict = None):
        self.login_resp = _resp({"status": "ok", "token": TOKEN})
        self.scope_responses = [_resp({"status": "ok", "response": scope_before})]
        if scope_after is not None:
            self.scope_responses.append(_resp({"status": "ok", "response": scope_after}))
        self.post_resp = _resp({"status": "ok"})
        self.posted_params = []

    def should_be_dns_updated(self) -> bool:
        return "dnsServers" in (self.posted_params[-1] if self.posted_params else {})

    def get_handler(self):
        responses = list(self.scope_responses)

        def handler(url, **kwargs):
            if "login" in url:
                return self.login_resp
            return responses.pop(0)

        return handler

    def post_handler(self):
        def handler(url, params=None, **kwargs):
            self.posted_params.append(params or {})
            return self.post_resp

        return handler


SCOPE_DEFAULTS = {
    "name": "Default",
    "startingAddress": "192.0.2.100",
    "endingAddress": "192.0.2.200",
    "subnetMask": "255.255.255.0",
    "routerAddress": "192.0.2.1",
    "leaseTime": 1440,
    "domainName": "",
}


class TestDhcpUpdateScopeDns(unittest.TestCase):
    def setUp(self):
        self.test_dir = ROOT / "tests" / "_fixtures" / "technitium"
        self.test_dir.mkdir(parents=True, exist_ok=True)
        self.servers_file = self.test_dir / "tenants-technitium.local.json"
        self.servers_file.write_text(
            json.dumps({
                "test-server": {
                    "url": "http://dns.example.local:5380",
                    "description": "Test server",
                    "env_pass": "TECHNITIUM_TEST_PASS",
                    "username": "admin",
                },
            })
        )
        os.environ["TECHNITIUM_SERVERS_FILE"] = str(self.servers_file)
        os.environ["TECHNITIUM_TEST_PASS"] = "testpass"

    def tearDown(self):
        if self.servers_file.exists():
            self.servers_file.unlink()
            self.servers_file.parent.rmdir()
            self.servers_file.parent.parent.rmdir()
        for key in ("TECHNITIUM_SERVERS_FILE", "TECHNITIUM_TEST_PASS"):
            os.environ.pop(key, None)
        for mod_name in list(sys.modules.keys()):
            if "technitium" in mod_name.lower():
                del sys.modules[mod_name]

    def _run_update(self, api: _ScopeApi, mock_requests: MagicMock, dns_servers):
        mock_requests.get.side_effect = api.get_handler()
        mock_requests.post.side_effect = api.post_handler()
        mod = _load_with_mock(mock_requests)
        return json.loads(mod.dhcp_update_scope_dns(
            server="test-server", scope_name="Default", dns_servers=dns_servers,
        )), mod

    def test_update_sends_exact_param_set(self):
        """POST carries only name/dnsServers/useThisDnsServer + token, then verifies."""
        api = _ScopeApi(
            scope_before={**SCOPE_DEFAULTS, "dnsServers": ["192.0.2.4", "198.51.100.1"]},
            scope_after={**SCOPE_DEFAULTS, "dnsServers": ["203.0.113.53"]},
        )
        mock_requests = MagicMock()
        result, mod = self._run_update(api, mock_requests, ["203.0.113.53"])

        self.assertEqual(result["before"], ["192.0.2.4", "198.51.100.1"])
        self.assertEqual(result["after"], ["203.0.113.53"])
        self.assertEqual(result["message"], "DNS servers updated successfully.")

        self.assertEqual(api.posted_params[-1], {
            "token": TOKEN,
            "name": "Default",
            "dnsServers": "203.0.113.53",
            "useThisDnsServer": "false",
        })

        # Verification re-fetched the scope after the write.
        get_urls = [c.args[0] for c in mock_requests.get.call_args_list]
        self.assertEqual(get_urls.count("http://dns.example.local:5380/api/dhcp/scopes/get"), 2)

    def test_update_refuses_empty_list(self):
        """An empty dns_servers list is refused — clearing must never be a typo side effect."""
        api = _ScopeApi(scope_before={**SCOPE_DEFAULTS, "dnsServers": ["192.0.2.4"]})
        mock_requests = MagicMock()
        result, _ = self._run_update(api, mock_requests, [])

        self.assertIn("refusing to clear", result["error"])
        self.assertFalse(api.posted_params)

    def test_no_update_when_unchanged(self):
        """Target already set → short-circuit, no POST, no verification re-fetch."""
        api = _ScopeApi(scope_before={**SCOPE_DEFAULTS, "dnsServers": ["192.0.2.4"]})
        mock_requests = MagicMock()
        result, _ = self._run_update(api, mock_requests, ["192.0.2.4"])

        self.assertEqual(result["message"], "DNS servers unchanged — no update needed.")
        self.assertFalse(api.posted_params)

    def test_update_reports_verification_mismatch(self):
        """Write 'succeeds' but scope still shows old DNS → error with the actual value."""
        stale = {**SCOPE_DEFAULTS, "dnsServers": ["192.0.2.4", "198.51.100.1"]}
        api = _ScopeApi(scope_before=stale, scope_after=stale)
        mock_requests = MagicMock()
        result, _ = self._run_update(api, mock_requests, ["203.0.113.53"])

        self.assertIn("still shows the old DNS servers", result["error"])
        self.assertEqual(result["after_actual"], ["192.0.2.4", "198.51.100.1"])
        self.assertTrue(api.posted_params)

    def test_error_returns_json_error(self):
        mock_requests = MagicMock()
        mock_requests.get.side_effect = Exception("Connection refused")
        mod = _load_with_mock(mock_requests)
        result = json.loads(mod.dhcp_update_scope_dns(
            server="test-server", scope_name="Default", dns_servers=["203.0.113.53"],
        ))
        self.assertIn("error", result)
        self.assertIn("Connection refused", result["error"])


class TestDhcpClearStaticRoutes(unittest.TestCase):
    def setUp(self):
        self.test_dir = ROOT / "tests" / "_fixtures" / "technitium"
        self.test_dir.mkdir(parents=True, exist_ok=True)
        self.servers_file = self.test_dir / "tenants-technitium.local.json"
        self.servers_file.write_text(
            json.dumps({
                "test-server": {
                    "url": "http://dns.example.local:5380",
                    "description": "Test server",
                    "env_pass": "TECHNITIUM_TEST_PASS",
                    "username": "admin",
                },
            })
        )
        os.environ["TECHNITIUM_SERVERS_FILE"] = str(self.servers_file)
        os.environ["TECHNITIUM_TEST_PASS"] = "testpass"

    def tearDown(self):
        if self.servers_file.exists():
            self.servers_file.unlink()
            self.servers_file.parent.rmdir()
            self.servers_file.parent.parent.rmdir()
        for key in ("TECHNITIUM_SERVERS_FILE", "TECHNITIUM_TEST_PASS"):
            os.environ.pop(key, None)
        for mod_name in list(sys.modules.keys()):
            if "technitium" in mod_name.lower():
                del sys.modules[mod_name]

    def _run_clear(self, api: _ScopeApi, mock_requests: MagicMock):
        mock_requests.get.side_effect = api.get_handler()
        mock_requests.post.side_effect = api.post_handler()
        mod = _load_with_mock(mock_requests)
        return json.loads(mod.dhcp_clear_static_routes(
            server="test-server", scope_name="Default",
        ))

    def test_clear_sends_name_and_static_routes_only(self):
        """Clearing sends only {name, staticRoutes: ''}; success reported after verify."""
        routes = ["192.0.2.64/26,192.0.2.1"]
        api = _ScopeApi(
            scope_before={**SCOPE_DEFAULTS, "staticRoutes": routes},
            scope_after={**SCOPE_DEFAULTS, "staticRoutes": ""},
        )
        mock_requests = MagicMock()
        result = self._run_clear(api, mock_requests)

        self.assertEqual(result["removed_routes"], routes)
        self.assertIn("static routes cleared", result["message"])

        self.assertEqual(api.posted_params[-1], {
            "token": TOKEN,
            "name": "Default",
            "staticRoutes": "",
        })

    def test_clear_nothing_to_clear(self):
        api = _ScopeApi(scope_before={**SCOPE_DEFAULTS, "staticRoutes": ""})
        mock_requests = MagicMock()
        result = self._run_clear(api, mock_requests)

        self.assertEqual(result["message"], "No static routes configured — nothing to clear.")
        self.assertFalse(api.posted_params)

    def test_clear_reports_verification_failure(self):
        routes = ["192.0.2.64/26,192.0.2.1"]
        stale = {**SCOPE_DEFAULTS, "staticRoutes": routes}
        api = _ScopeApi(scope_before=stale, scope_after=stale)
        mock_requests = MagicMock()
        result = self._run_clear(api, mock_requests)

        self.assertIn("still present", result["error"])
        self.assertEqual(result["after_actual"], routes)
        self.assertTrue(api.posted_params)


if __name__ == "__main__":
    unittest.main()