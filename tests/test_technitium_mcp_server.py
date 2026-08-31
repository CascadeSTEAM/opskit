"""Tests for mcp/technitium-mcp-server.py — DHCP DNS update tool.

Unit tests that mock the Technitium API to verify dhcp_update_scope_dns
correctly reads scope state, POSTs the update, and returns the before/after diff.
"""

import asyncio
import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "mcp" / "technitium-mcp-server.py"


class TestDhcpUpdateScopeDns(unittest.TestCase):
    def setUp(self):
        # Create a minimal server config for the test
        self.test_dir = Path(__file__).resolve().parents[1] / "tests" / "_fixtures" / "technitium"
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
        # Clean up cached clients
        import importlib
        # Remove any cached module
        for mod_name in list(sys.modules.keys()):
            if "technitium" in mod_name.lower():
                del sys.modules[mod_name]

    def _import_module(self):
        """Import the server module with our test config."""
        import importlib.util
        # Force reimport
        if "technitium_mcp_server" in sys.modules:
            del sys.modules["technitium_mcp_server"]
        spec = importlib.util.spec_from_file_location(
            "technitium_mcp_server", SERVER
        )
        mod = importlib.util.module_from_spec(spec)
        sys.modules["technitium_mcp_server"] = mod
        spec.loader.exec_module(mod)
        return mod

    @patch("sys.modules", new_callable=lambda: dict(sys.modules))
    def _patch_requests(self, mock_sysmodules):
        """Create a test environment with mocked requests."""
        # We can't use @patch on sys.modules directly, so we use a different approach
        pass

    def test_update_changes_dns_servers(self):
        """When DNS servers differ, the tool POSTs the update and returns diff."""
        mod = self._import_module()

        # Patch requests at the module level
        mock_requests = MagicMock()

        # Mock login
        mock_login_resp = MagicMock()
        mock_login_resp.json.return_value = {"status": "ok", "token": "test-token"}
        mock_login_resp.raise_for_status.return_value = None

        # Mock get scope (returns current dnsServers)
        mock_get_scope_resp = MagicMock()
        mock_get_scope_resp.json.return_value = {
            "status": "ok",
            "response": {
                "name": "Default",
                "startingAddress": "192.0.2.100",
                "endingAddress": "192.0.2.200",
                "subnetMask": "255.255.255.0",
                "routerAddress": "192.0.2.1",
                "dnsServers": ["192.0.2.4", "198.51.100.1"],
                "staticRoutes": "",
                "leaseTime": 1440,
                "domainName": "",
            },
        }

        # Mock post scope (update)
        mock_post_resp = MagicMock()
        mock_post_resp.json.return_value = {"status": "ok"}

        def side_effect(*args, **kwargs):
            url = args[0] if args else kwargs.get("url", "")
            if "login" in url:
                return mock_login_resp
            elif "scopes/get" in url:
                return mock_get_scope_resp
            elif "scopes/set" in url:
                return mock_post_resp
            return mock_login_resp

        mock_requests.get.side_effect = side_effect
        mock_requests.post.side_effect = side_effect

        # Patch requests in the module
        import sys
        original_requests = sys.modules.get("requests")
        if "technitium_mcp_server" in sys.modules:
            del sys.modules["technitium_mcp_server"]

        # Re-import with mocked requests
        with patch.dict(sys.modules, {"requests": mock_requests}):
            spec = __import__("importlib").util.spec_from_file_location(
                "technitium_mcp_server", SERVER
            )
            mod = __import__("importlib").util.module_from_spec(spec)
            sys.modules["technitium_mcp_server"] = mod
            spec.loader.exec_module(mod)

            result = mod.dhcp_update_scope_dns(
                server="test-server",
                scope_name="Default",
                dns_servers=["192.0.2.4"],
            )
            result_data = json.loads(result)

            assert result_data.get("before") == ["192.0.2.4", "198.51.100.1"]
            assert result_data.get("after") == ["192.0.2.4"]
            assert result_data.get("message") == "DNS servers updated successfully."
            assert result_data.get("scope") == "Default"

            # Verify POST was called with dnsServers
            post_call = mock_requests.post.call_args
            post_params = post_call[0][0]  # URL
            post_kwargs = post_call[1]
            dns_param = post_params if isinstance(post_params, str) else ""
            # The params are in the POST call
            assert any("dnsServers" in str(post_call) for _ in [1]), "dnsServers should be in POST params"

    def test_no_update_when_unchanged(self):
        """When DNS servers are already the target, no POST is sent."""
        mod = self._import_module()

        mock_requests = MagicMock()

        mock_login_resp = MagicMock()
        mock_login_resp.json.return_value = {"status": "ok", "token": "test-token"}

        mock_get_scope_resp = MagicMock()
        mock_get_scope_resp.json.return_value = {
            "status": "ok",
            "response": {
                "name": "Default",
                "startingAddress": "192.0.2.100",
                "endingAddress": "192.0.2.200",
                "subnetMask": "255.255.255.0",
                "routerAddress": "192.0.2.1",
                "dnsServers": ["192.0.2.4"],
                "staticRoutes": "",
                "leaseTime": 1440,
            },
        }

        def side_effect(*args, **kwargs):
            url = args[0] if args else kwargs.get("url", "")
            if "login" in url:
                return mock_login_resp
            elif "scopes/get" in url:
                return mock_get_scope_resp
            return mock_login_resp

        mock_requests.get.side_effect = side_effect
        mock_requests.post.side_effect = side_effect

        import sys
        if "technitium_mcp_server" in sys.modules:
            del sys.modules["technitium_mcp_server"]

        with patch.dict(sys.modules, {"requests": mock_requests}):
            spec = __import__("importlib").util.spec_from_file_location(
                "technitium_mcp_server", SERVER
            )
            mod = __import__("importlib").util.module_from_spec(spec)
            sys.modules["technitium_mcp_server"] = mod
            spec.loader.exec_module(mod)

            result = mod.dhcp_update_scope_dns(
                server="test-server",
                scope_name="Default",
                dns_servers=["192.0.2.4"],
            )
            result_data = json.loads(result)

            assert result_data.get("message") == "DNS servers unchanged — no update needed."
            # POST should NOT have been called
            assert not mock_requests.post.called

    def test_error_returns_json_error(self):
        """When the API call fails, the tool returns a JSON error object."""
        mod = self._import_module()

        mock_requests = MagicMock()
        mock_requests.get.side_effect = Exception("Connection refused")

        import sys
        if "technitium_mcp_server" in sys.modules:
            del sys.modules["technitium_mcp_server"]

        with patch.dict(sys.modules, {"requests": mock_requests}):
            spec = __import__("importlib").util.spec_from_file_location(
                "technitium_mcp_server", SERVER
            )
            mod = __import__("importlib").util.module_from_spec(spec)
            sys.modules["technitium_mcp_server"] = mod
            spec.loader.exec_module(mod)

            result = mod.dhcp_update_scope_dns(
                server="test-server",
                scope_name="Default",
                dns_servers=["192.0.2.4"],
            )
            result_data = json.loads(result)

            assert "error" in result_data
            assert "Connection refused" in result_data["error"]


if __name__ == "__main__":
    unittest.main()
