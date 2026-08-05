"""Tests for bin/gen-mikromcp-config.py — device datasets → mikromcp config.

opskit #105: the router config was hand-maintained outside the repo and drifted
from the datasets in both directions — a router missing entirely, and a
rosVersion two minor versions stale because someone had recorded the bootloader
firmware instead of the OS version. Generating it makes the datasets canonical.

The properties worth pinning are the ones whose failure is silent: a device
quietly dropped, a guessed version, or a config that claims TLS while skipping
certificate verification.
"""

import subprocess
import sys
import textwrap
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
GEN = ROOT / "bin" / "gen-mikromcp-config.py"


def _device(root: Path, env: str, name: str, **fields) -> Path:
    d = root / "environments" / env / "datasets" / "devices"
    d.mkdir(parents=True, exist_ok=True)
    body = {"name": name, "status": "active", "maturity": 1, **fields}
    path = d / f"{name}.md"
    path.write_text("---\n" + yaml.safe_dump(body, sort_keys=False) + "---\n")
    return path


def _run(root: Path, *args: str, target: Path | None = None):
    cmd = [sys.executable, str(GEN), "--repo-root", str(root), *args]
    if target is not None:
        cmd += ["--target", str(target)]
    return subprocess.run(cmd, capture_output=True, text=True)


def _routers(root: Path) -> dict:
    result = _run(root, "--print")
    assert result.returncode == 0, result.stderr
    return yaml.safe_load(result.stdout)["routers"]


def _routeros(**extra):
    return {"os": "RouterOS", "ip_address": "192.0.2.1", "os_version": "7.21", **extra}


# ── derivation ────────────────────────────────────────────────────────────────

def test_id_and_env_prefix_are_derived_from_env_and_name(tmp_path):
    _device(tmp_path, "site1", "gw", **_routeros())
    routers = _routers(tmp_path)

    assert list(routers) == ["site1-gw"]
    assert routers["site1-gw"]["credentials"]["envPrefix"] == "MIKROTIK_SITE1_GW"


def test_host_and_version_come_from_the_record(tmp_path):
    _device(tmp_path, "site1", "gw", **_routeros(ip_address="192.0.2.7", os_version="7.23.1"))
    r = _routers(tmp_path)["site1-gw"]

    assert r["host"] == "192.0.2.7"
    assert r["rosVersion"] == "7.23.1"


def test_credentials_use_env_not_vault_source(tmp_path):
    """mikromcp accepts source 'vault' in its schema but raises
    VAULT_NOT_SUPPORTED, so the launcher resolves and passes env vars."""
    _device(tmp_path, "site1", "gw", **_routeros())

    assert _routers(tmp_path)["site1-gw"]["credentials"]["source"] == "env"


def test_env_name_is_always_a_tag_and_never_duplicated(tmp_path):
    _device(tmp_path, "site1", "gw", **_routeros(tags=["site1", "core"]))

    assert _routers(tmp_path)["site1-gw"]["tags"] == ["site1", "core"]


def test_names_with_punctuation_produce_a_valid_env_prefix(tmp_path):
    _device(tmp_path, "site-1", "ap.office-2", **_routeros())
    prefix = _routers(tmp_path)["site-1-ap.office-2"]["credentials"]["envPrefix"]

    assert prefix == "MIKROTIK_SITE_1_AP_OFFICE_2"
    assert prefix.replace("_", "").isalnum()


# ── selection ─────────────────────────────────────────────────────────────────

def test_swos_devices_are_excluded(tmp_path):
    """SwOS has no RouterOS REST API; an entry for it would fail every call."""
    _device(tmp_path, "site1", "gw", **_routeros())
    _device(tmp_path, "site1", "sw", os="SwOS", ip_address="192.0.2.2", os_version="2.18")

    assert list(_routers(tmp_path)) == ["site1-gw"]


def test_the_committed_example_environment_is_ignored(tmp_path):
    _device(tmp_path, "site1", "gw", **_routeros())
    _device(tmp_path, "example", "ex-gw", **_routeros(ip_address="198.51.100.9"))

    assert list(_routers(tmp_path)) == ["site1-gw"]


def test_decommissioned_devices_are_excluded_but_reported(tmp_path):
    _device(tmp_path, "site1", "gw", **_routeros())
    _device(tmp_path, "site1", "old", **_routeros(ip_address="192.0.2.9",
                                                  status="decommissioned"))
    result = _run(tmp_path, "--print")

    assert "site1-old" not in yaml.safe_load(result.stdout)["routers"]
    assert "site1-old: status: decommissioned" in result.stdout


def test_a_device_without_an_os_version_is_skipped_not_guessed(tmp_path):
    """rosVersion selects the WiFi API path (7.x vs 6.x). A guess would silently
    send calls to the wrong endpoint, which is worse than refusing."""
    _device(tmp_path, "site1", "gw", **_routeros())
    _device(tmp_path, "site1", "nover", os="RouterOS", ip_address="192.0.2.3")
    result = _run(tmp_path, "--print")

    assert "site1-nover" not in yaml.safe_load(result.stdout)["routers"]
    assert "no os_version" in result.stdout


def test_a_device_without_an_ip_is_skipped(tmp_path):
    _device(tmp_path, "site1", "gw", **_routeros())
    _device(tmp_path, "site1", "noip", os="RouterOS", os_version="7.21")
    result = _run(tmp_path, "--print")

    assert "no ip_address" in result.stdout


def test_skipped_devices_are_always_named_in_the_output(tmp_path):
    """Omission left no trace before, which is how a router stayed missing."""
    _device(tmp_path, "site1", "gw", **_routeros())
    _device(tmp_path, "site1", "noip", os="RouterOS", os_version="7.21")
    result = _run(tmp_path, "--print")

    assert "NOT INCLUDED" in result.stdout
    assert "site1-noip" in result.stdout


def test_explicitly_disabled_device_reports_its_reason(tmp_path):
    _device(tmp_path, "site1", "gw", **_routeros())
    _device(tmp_path, "site1", "ap", **_routeros(
        ip_address="192.0.2.4",
        mikromcp={"enabled": False, "reason": "credential unknown"},
    ))
    result = _run(tmp_path, "--print")

    assert "site1-ap" not in yaml.safe_load(result.stdout)["routers"]
    assert "credential unknown" in result.stdout


# ── transport defaults and overrides ──────────────────────────────────────────

def test_plain_http_is_the_default_while_www_ssl_is_not_enabled(tmp_path):
    _device(tmp_path, "site1", "gw", **_routeros())
    r = _routers(tmp_path)["site1-gw"]

    assert r["port"] == 80
    assert r["tls"] == {"enabled": False, "rejectUnauthorized": False}


def test_enabling_tls_defaults_the_port_and_turns_on_verification(tmp_path):
    """Claiming TLS while skipping verification looks secure and is not, so
    verification follows tls unless overridden explicitly."""
    _device(tmp_path, "site1", "gw", **_routeros(mikromcp={"tls": True}))
    r = _routers(tmp_path)["site1-gw"]

    assert r["port"] == 443
    assert r["tls"] == {"enabled": True, "rejectUnauthorized": True}


def test_verification_can_be_disabled_explicitly_for_a_pinned_cert(tmp_path):
    _device(tmp_path, "site1", "gw",
            **_routeros(mikromcp={"tls": True, "reject_unauthorized": False}))

    assert _routers(tmp_path)["site1-gw"]["tls"]["rejectUnauthorized"] is False


def test_port_and_ssh_port_overrides_are_honoured(tmp_path):
    _device(tmp_path, "site1", "gw", **_routeros(mikromcp={"port": 8080, "ssh_port": 2222}))
    r = _routers(tmp_path)["site1-gw"]

    assert r["port"] == 8080
    assert r["sshPort"] == 2222


# ── modes ─────────────────────────────────────────────────────────────────────

def test_check_detects_drift_and_prints_a_diff(tmp_path):
    _device(tmp_path, "site1", "gw", **_routeros())
    target = tmp_path / "routers.yaml"
    target.write_text("routers: {}\n")

    result = _run(tmp_path, "--check", target=target)

    assert result.returncode == 1
    assert "DRIFT" in result.stderr
    assert "site1-gw" in result.stderr


def test_check_passes_on_a_freshly_written_file(tmp_path):
    _device(tmp_path, "site1", "gw", **_routeros())
    target = tmp_path / "routers.yaml"

    assert _run(tmp_path, "--write", target=target).returncode == 0
    assert _run(tmp_path, "--check", target=target).returncode == 0


def test_write_backs_up_an_existing_file(tmp_path):
    _device(tmp_path, "site1", "gw", **_routeros())
    target = tmp_path / "routers.yaml"
    target.write_text("original\n")

    _run(tmp_path, "--write", target=target)
    backups = list(tmp_path.glob("routers.yaml.bak-*"))

    assert len(backups) == 1
    assert backups[0].read_text() == "original\n"


def test_generated_file_says_it_is_generated(tmp_path):
    _device(tmp_path, "site1", "gw", **_routeros())
    result = _run(tmp_path, "--print")

    assert "do not edit by hand" in result.stdout.lower()


def test_env_prefixes_lists_both_variables_per_router(tmp_path):
    _device(tmp_path, "site1", "gw", **_routeros())
    result = _run(tmp_path, "--env-prefixes")

    assert result.returncode == 0
    assert result.stdout.split() == [
        "site1-gw", "MIKROTIK_SITE1_GW_USER", "MIKROTIK_SITE1_GW_PASS",
    ]


def test_no_routers_at_all_is_an_error_not_an_empty_file(tmp_path):
    """Writing an empty config would remove every device from the tooling."""
    _device(tmp_path, "site1", "sw", os="SwOS", ip_address="192.0.2.2", os_version="2.18")
    result = _run(tmp_path, "--print")

    assert result.returncode == 1
    assert "no RouterOS devices" in result.stderr


def test_malformed_front_matter_does_not_abort_the_run(tmp_path):
    _device(tmp_path, "site1", "gw", **_routeros())
    bad = tmp_path / "environments" / "site1" / "datasets" / "devices" / "bad.md"
    bad.write_text(textwrap.dedent("""\
        ---
        name: bad
          bogus: [unclosed
        ---
        """))

    assert list(_routers(tmp_path)) == ["site1-gw"]


def test_output_is_deterministic(tmp_path):
    """Two runs must byte-match, or --check reports phantom drift forever."""
    _device(tmp_path, "site1", "b", **_routeros())
    _device(tmp_path, "site1", "a", **_routeros(ip_address="192.0.2.5"))

    assert _run(tmp_path, "--print").stdout == _run(tmp_path, "--print").stdout
