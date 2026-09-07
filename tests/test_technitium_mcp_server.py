"""Tests for mcp/technitium-mcp-server.py — credential/token transport (#299)
plus the DHCP scope-dns/route tool contracts (#298).

Unit tests that mock the Technitium API to verify:
- login credentials and the session token travel in the POST form body, never
  in URL query strings (which the server access log and any proxy records);
- the reachability probe in dns_list_servers does not perform a fake login;
- dhcp_update_scope_dns / dhcp_clear_static_routes POST the exact verified
  param set, respect the empty-list guard, and verify writes by re-fetching.
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
PASSWORD = "testpass"


def _resp(payload, status=200):
    r = MagicMock()
    r.status_code = status
    r.json.return_value = payload
    return r


def _import_module():
    import importlib.util
    sys.modules.pop("technitium_mcp_server", None)
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


class _Api:
    """Stands in for the Technitium API surface.

    Login and every tool call now travel as POST form bodies (#299), so one
    routed post-handler serves all of it and records every request URL plus
    the posted data dicts for exact assertions.
    """

    def __init__(self, scope_before: dict, scope_after: dict = None):
        self.login_resp = _resp({"status": "ok", "token": TOKEN})
        self.scope_responses = [_resp({"status": "ok", "response": scope_before})]
        if scope_after is not None:
            self.scope_responses.append(_resp({"status": "ok", "response": scope_after}))
        self.post_resp = _resp({"status": "ok"})
        self.posted = []
        self.urls = []
        self.responses = {}

    def handle(self, url, data=None, params=None, **kwargs):
        self.urls.append(url)
        if data is not None:
            self.posted.append(data)
        if params is not None:
            self.posted.append(params)
        if "login" in url:
            return self.login_resp
        for frag, resp in self.responses.items():
            if frag in url:
                return resp
        if "scopes/get" in url:
            return self.scope_responses.pop(0)
        return self.post_resp


SCOPE_DEFAULTS = {
    "name": "Default",
    "startingAddress": "192.0.2.100",
    "endingAddress": "192.0.2.200",
    "subnetMask": "255.255.255.0",
    "routerAddress": "192.0.2.1",
    "leaseTime": 1440,
    "domainName": "",
}


def _server_config_dir() -> Path:
    d = ROOT / "tests" / "_fixtures" / "technitium"
    d.mkdir(parents=True, exist_ok=True)
    return d


class _TestCaseBase(unittest.TestCase):
    def setUp(self):
        self.test_dir = _server_config_dir()
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
        os.environ["TECHNITIUM_TEST_PASS"] = PASSWORD

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


class TestCredentialTransport(_TestCaseBase):
    def test_login_posts_credentials_in_form_body_not_url(self):
        api = _Api(scope_before={**SCOPE_DEFAULTS, "dnsServers": ["192.0.2.4"]})
        mock_requests = MagicMock()
        mock_requests.post.side_effect = api.handle
        mod = _load_with_mock(mock_requests)

        result = json.loads(mod.dhcp_get_scope(server="test-server", scope_name="Default"))
        self.assertEqual(result["name"], "Default")

        login_calls = [c for c in mock_requests.post.call_args_list if "login" in c.args[0]]
        self.assertEqual(len(login_calls), 1)
        self.assertEqual(login_calls[0].args[0], "http://dns.example.local:5380/api/user/login")
        self.assertEqual(login_calls[0].kwargs.get("data"), {
            "user": "admin", "pass": PASSWORD, "includeToken": "true",
        })
        self.assertNotIn("params", login_calls[0].kwargs)

    def test_no_secrets_in_any_request_url(self):
        api = _Api(
            scope_before={**SCOPE_DEFAULTS, "dnsServers": ["192.0.2.4"]},
            scope_after={**SCOPE_DEFAULTS, "dnsServers": ["203.0.113.53"]},
        )
        mock_requests = MagicMock()
        mock_requests.post.side_effect = api.handle
        mod = _load_with_mock(mock_requests)
        json.loads(mod.dhcp_update_scope_dns(
            server="test-server", scope_name="Default", dns_servers=["203.0.113.53"],
        ))

        self.assertTrue(api.urls)
        for url in api.urls:
            self.assertNotIn(PASSWORD, url)
            self.assertNotIn("test-token", url)
            self.assertNotIn("?", url)

    def test_reachability_probe_does_not_attempt_login(self):
        mock_requests = MagicMock()
        mock_requests.get.return_value = _resp({})
        mod = _load_with_mock(mock_requests)
        result = json.loads(mod.dns_list_servers())

        server = result["servers"]["test-server"]
        self.assertTrue(server["reachable"])
        self.assertEqual(server["url"], "http://dns.example.local:5380")
        get_urls = [c.args[0] for c in mock_requests.get.call_args_list]
        self.assertEqual(get_urls, ["http://dns.example.local:5380"])
        self.assertFalse(list(mock_requests.post.call_args_list))


class TestUnexpectedEnvelopeSurfaced(_TestCaseBase):
    """#253: a listing whose response lacks its list key must surface the raw
    envelope as an error, not return a silently-empty list that a caller like
    fetch-dhcp-leases.py would read as 'the server has no scopes/leases'."""

    def test_scopes_list_unexpected_envelope_is_an_error(self):
        api = _Api(scope_before=SCOPE_DEFAULTS)
        api.responses["dhcp/scopes/list"] = _resp(
            {"status": "ok", "response": {"zones": ["x"]}})
        mock_requests = MagicMock()
        mock_requests.post.side_effect = api.handle
        mod = _load_with_mock(mock_requests)

        result = json.loads(mod.dhcp_list_scopes(server="test-server"))
        self.assertIn("error", result)
        self.assertIn("no 'scopes' key", result["error"])
        self.assertIn("zones", result["error"])

    def test_leases_list_unexpected_envelope_is_an_error(self):
        api = _Api(scope_before=SCOPE_DEFAULTS)
        api.responses["dhcp/leases/list"] = _resp({"status": "ok", "response": {}})
        mock_requests = MagicMock()
        mock_requests.post.side_effect = api.handle
        mod = _load_with_mock(mock_requests)

        result = json.loads(mod.dhcp_list_leases(server="test-server", scope_name="Default"))
        self.assertIn("error", result)
        self.assertIn("no 'leases' key", result["error"])
        self.assertIn("Default", result["error"])


class TestDhcpUpdateScopeDns(_TestCaseBase):
    def _run_update(self, api: _Api, mock_requests: MagicMock, dns_servers):
        mock_requests.post.side_effect = api.handle
        mod = _load_with_mock(mock_requests)
        return json.loads(mod.dhcp_update_scope_dns(
            server="test-server", scope_name="Default", dns_servers=dns_servers,
        ))

    def test_update_sends_exact_param_set(self):
        api = _Api(
            scope_before={**SCOPE_DEFAULTS, "dnsServers": ["192.0.2.4", "198.51.100.1"]},
            scope_after={**SCOPE_DEFAULTS, "dnsServers": ["203.0.113.53"]},
        )
        mock_requests = MagicMock()
        result = self._run_update(api, mock_requests, ["203.0.113.53"])

        self.assertEqual(result["before"], ["192.0.2.4", "198.51.100.1"])
        self.assertEqual(result["after"], ["203.0.113.53"])
        self.assertEqual(result["message"], "DNS servers updated successfully.")

        set_calls = [d for d in api.posted if "dnsServers" in d]
        self.assertEqual(set_calls[-1], {
            "token": TOKEN,
            "name": "Default",
            "dnsServers": "203.0.113.53",
            "useThisDnsServer": "false",
        })

        # Verification re-fetched the scope after the write (over POST bodies).
        self.assertEqual(
            api.urls.count("http://dns.example.local:5380/api/dhcp/scopes/get"), 2)

    def test_update_refuses_empty_list(self):
        api = _Api(scope_before={**SCOPE_DEFAULTS, "dnsServers": ["192.0.2.4"]})
        mock_requests = MagicMock()
        result = self._run_update(api, mock_requests, [])

        self.assertIn("refusing to clear", result["error"])
        self.assertFalse(any("dnsServers" in d for d in api.posted))

    def test_no_update_when_unchanged(self):
        api = _Api(scope_before={**SCOPE_DEFAULTS, "dnsServers": ["192.0.2.4"]})
        mock_requests = MagicMock()
        result = self._run_update(api, mock_requests, ["192.0.2.4"])

        self.assertEqual(result["message"], "DNS servers unchanged — no update needed.")
        self.assertFalse(any("dnsServers" in d for d in api.posted))

    def test_update_reports_verification_mismatch(self):
        stale = {**SCOPE_DEFAULTS, "dnsServers": ["192.0.2.4", "198.51.100.1"]}
        api = _Api(scope_before=stale, scope_after=stale)
        mock_requests = MagicMock()
        result = self._run_update(api, mock_requests, ["203.0.113.53"])

        self.assertIn("still shows the old DNS servers", result["error"])
        self.assertEqual(result["after_actual"], ["192.0.2.4", "198.51.100.1"])
        self.assertTrue(any("dnsServers" in d for d in api.posted))

    def test_error_returns_json_error(self):
        mock_requests = MagicMock()
        mock_requests.post.side_effect = Exception("Connection refused")
        mod = _load_with_mock(mock_requests)
        result = json.loads(mod.dhcp_update_scope_dns(
            server="test-server", scope_name="Default", dns_servers=["203.0.113.53"],
        ))
        self.assertIn("error", result)
        self.assertIn("Connection refused", result["error"])


class TestDhcpClearStaticRoutes(_TestCaseBase):
    def _run_clear(self, api: _Api, mock_requests: MagicMock):
        mock_requests.post.side_effect = api.handle
        mod = _load_with_mock(mock_requests)
        return json.loads(mod.dhcp_clear_static_routes(
            server="test-server", scope_name="Default",
        ))

    def test_clear_sends_name_and_static_routes_only(self):
        routes = ["192.0.2.64/26,192.0.2.1"]
        api = _Api(
            scope_before={**SCOPE_DEFAULTS, "staticRoutes": routes},
            scope_after={**SCOPE_DEFAULTS, "staticRoutes": ""},
        )
        mock_requests = MagicMock()
        result = self._run_clear(api, mock_requests)

        self.assertEqual(result["removed_routes"], routes)
        self.assertIn("static routes cleared", result["message"])

        clear_calls = [d for d in api.posted if "staticRoutes" in d]
        self.assertEqual(clear_calls[-1], {
            "token": TOKEN,
            "name": "Default",
            "staticRoutes": "",
        })

    def test_clear_nothing_to_clear(self):
        api = _Api(scope_before={**SCOPE_DEFAULTS, "staticRoutes": ""})
        mock_requests = MagicMock()
        result = self._run_clear(api, mock_requests)

        self.assertEqual(result["message"], "No static routes configured — nothing to clear.")
        self.assertFalse(any("staticRoutes" in d for d in api.posted))

    def test_clear_reports_verification_failure(self):
        routes = ["192.0.2.64/26,192.0.2.1"]
        stale = {**SCOPE_DEFAULTS, "staticRoutes": routes}
        api = _Api(scope_before=stale, scope_after=stale)
        mock_requests = MagicMock()
        result = self._run_clear(api, mock_requests)

        self.assertIn("still present", result["error"])
        self.assertEqual(result["after_actual"], routes)
        self.assertTrue(api.posted)


if __name__ == "__main__":
    unittest.main()