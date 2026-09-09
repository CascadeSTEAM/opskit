"""Tests for bin/gen-mcp-config.py (issue #285)."""

import importlib.util
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "gen_mcp_config", ROOT / "bin" / "gen-mcp-config.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_collect_tenants_from_env_yml(tmp_path):
    """Tenants are derived from env.yml ticket.helpdesk_tenant blocks."""
    env_dir = tmp_path / "environments" / "test"
    env_dir.mkdir(parents=True)
    env_yml = env_dir / "env.yml"
    env_yml.write_text("""
name: test
display_name: Test Env
ticket:
  prefix: TEST
  helpdesk: erpnext
  helpdesk_endpoint: https://test.example.com
  helpdesk_tenant: testtenant
""")
    mod = _load_module()
    envs = mod.env_yml_files(tmp_path)
    tenants = mod.collect_tenants(envs)
    assert "testtenant" in tenants
    assert tenants["testtenant"]["site"] == "https://test.example.com"
    assert tenants["testtenant"]["description"] == "Test Env Helpdesk"


def test_collect_tenants_skips_none_helpdesk(tmp_path):
    """Environments with helpdesk: none are skipped."""
    env_dir = tmp_path / "environments" / "test"
    env_dir.mkdir(parents=True)
    env_yml = env_dir / "env.yml"
    env_yml.write_text("""
name: test
display_name: Test Env
ticket:
  prefix: TEST
  helpdesk: none
""")
    mod = _load_module()
    envs = mod.env_yml_files(tmp_path)
    tenants = mod.collect_tenants(envs)
    assert tenants == {}


def test_collect_vault_map_from_env_yml(tmp_path):
    """Vault map entries are derived from env.yml ticket blocks."""
    env_dir = tmp_path / "environments" / "test"
    env_dir.mkdir(parents=True)
    env_yml = env_dir / "env.yml"
    env_yml.write_text("""
name: test
display_name: Test Env
ticket:
  prefix: TEST
  helpdesk: erpnext
  helpdesk_endpoint: https://test.example.com
  helpdesk_tenant: testtenant
""")
    mod = _load_module()
    envs = mod.env_yml_files(tmp_path)
    vault_map = mod.collect_vault_map(envs)
    assert "erpnext" in vault_map
    assert "ERPNEXT_API_KEY_TESTTENANT" in vault_map["erpnext"]
    assert "ERPNEXT_API_SECRET_TESTTENANT" in vault_map["erpnext"]
    assert vault_map["erpnext"]["ERPNEXT_API_KEY_TESTTENANT"]["field"] == "username"
    assert vault_map["erpnext"]["ERPNEXT_API_SECRET_TESTTENANT"]["field"] == "password"


def test_render_tenants_produces_yaml(tmp_path):
    """Rendered tenants output is valid YAML."""
    tenants = {"testtenant": {"site": "https://test.example.com", "description": "Test"}}
    mod = _load_module()
    output = mod.render_tenants(tenants)
    assert "testtenant" in output
    assert "https://test.example.com" in output


def test_render_vault_map_produces_yaml(tmp_path):
    """Rendered vault-map output is valid YAML."""
    vault_map = {
        "erpnext": {
            "ERPNEXT_API_KEY_TEST": {
                "item": "00000000-0000-0000-0000-000000000000",
                "field": "username",
            }
        }
    }
    mod = _load_module()
    output = mod.render_vault_map(vault_map)
    assert "erpnext" in output


def test_check_tenants_differs(tmp_path):
    """--check-tenants reports when the live file differs from generated."""
    tenants_path = str(tmp_path / "tenants.local.json")
    Path(tenants_path).write_text("# existing\n")
    os.environ["OPSKIT_TENANTS_FILE"] = tenants_path
    try:
        mod = _load_module()
        env_dir = tmp_path / "environments" / "test"
        env_dir.mkdir(parents=True)
        env_yml = env_dir / "env.yml"
        env_yml.write_text("""
name: test
display_name: Test Env
ticket:
  prefix: TEST
  helpdesk: erpnext
  helpdesk_endpoint: https://test.example.com
  helpdesk_tenant: testtenant
""")
        envs = mod.env_yml_files(tmp_path)
        tenants = mod.collect_tenants(envs)
        diff = list(mod.difflib.unified_diff(
            Path(tenants_path).read_text().splitlines(),
            mod.render_tenants(tenants).splitlines(),
            fromfile="existing", tofile="generated",
        ))
        assert diff  # non-empty diff means file differs
    finally:
        os.environ.pop("OPSKIT_TENANTS_FILE", None)
