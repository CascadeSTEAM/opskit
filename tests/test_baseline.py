"""Tests for bin/baseline.py — system baseline capture/compare/rebuild tool.

Capture and diff talk to live systems over SSH, so they are not exercised
here; the deterministic, offline paths (save_baseline, rebuild, status, and
the parsing helpers) are. The OPSKIT_ROOT override lets the CLI run against a
temp repo root, matching the pattern used by env-sync.sh and bin/opskit.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "bin" / "baseline.py"

sys.path.insert(0, str(ROOT / "bin"))
import baseline  # noqa: E402

SAMPLE = {
    "captured_at": "2026-07-22T10:00:00",
    "host": "wkstn-01",
    "user": "root",
    "local": True,
    "os": {
        "pretty_name": "Ubuntu 24.04 LTS",
        "kernel": "6.8.0-40-generic",
        "hostname": "wkstn-01",
    },
    "gpu": {
        "devices": ["00:02.0 VGA Intel"],
        "packages": ["mesa-utils 24.0", "i965-va-driver 2.4"],
    },
    "display": {
        "display_manager": "sddm",
        "desktop": "KDE",
        "session_type": "wayland",
        "kscreen_outputs": {
            "user/edid1": {
                "metadata": {"name": "eDP-1", "fullname": "BOE panel"},
                "mode": {"size": {"width": 1200, "height": 1920}},
                "rotation": 1,
                "scale": 1,
                "id": "abc",
            }
        },
    },
    "packages": ["plasma-desktop", "sddm", "openssh-server"],
    "services": ["sshd", "sddm"],
    "network": {
        "interfaces": ["wlan0 UP 192.0.2.5/24"],
        "routes": ["default via 192.0.2.1"],
        "dns": ["nameserver 192.0.2.1"],
    },
}


def _cli(root: Path, *args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ, OPSKIT_ROOT=str(root))
    return subprocess.run(
        [sys.executable, str(BASELINE), *args],
        capture_output=True,
        text=True,
        env=env,
    )


@pytest.fixture
def seeded(tmp_path, monkeypatch):
    """A temp repo root with one captured baseline (wkstn-01 in testenv)."""
    monkeypatch.setattr(baseline, "ENVS_DIR", tmp_path / "environments")
    baseline.save_baseline("testenv", "wkstn-01", SAMPLE)
    baseline.update_status("testenv", "wkstn-01")
    return tmp_path


class TestParsingHelpers:
    def test_extract_scalar(self):
        content = "os: Ubuntu 24.04 LTS\nkernel: 6.8.0\n"
        assert baseline._extract_scalar(content, "os") == "Ubuntu 24.04 LTS"
        assert baseline._extract_scalar(content, "kernel") == "6.8.0"
        assert baseline._extract_scalar(content, "missing") is None

    def test_list_under_stops_at_dedent(self):
        content = (
            "packages_baseline:\n"
            "  - alpha\n"
            "  - beta\n"
            "systemd_services:\n"
            "  - gamma\n"
        )
        assert baseline._list_under(content, "packages_baseline:") == ["alpha", "beta"]
        assert baseline._list_under(content, "systemd_services:") == ["gamma"]

    def test_list_under_nested_indent(self):
        content = "gpu:\n  - dev0\n  packages:\n    - pkg-a 1.0\n    - pkg-b 2.0\nnext:\n"
        assert baseline._list_under(content, "  packages:") == ["pkg-a 1.0", "pkg-b 2.0"]


class TestSaveBaseline:
    def test_writes_device_yaml(self, tmp_path, monkeypatch):
        monkeypatch.setattr(baseline, "ENVS_DIR", tmp_path / "environments")
        f = baseline.save_baseline("testenv", "wkstn-01", SAMPLE)
        assert f.exists()
        text = f.read_text()
        assert "name: wkstn-01" in text
        assert "os: Ubuntu 24.04 LTS" in text
        assert "baseline_captured: 2026-07-22T10:00:00" in text
        assert "rebuild_notes:" in text

    def test_status_file_updated(self, tmp_path, monkeypatch):
        monkeypatch.setattr(baseline, "ENVS_DIR", tmp_path / "environments")
        baseline.save_baseline("testenv", "wkstn-01", SAMPLE)
        baseline.update_status("testenv", "wkstn-01")
        status = tmp_path / "environments" / "testenv" / "baseline-status.yml"
        assert status.exists()
        assert "wkstn-01: baselined" in status.read_text()


class TestRebuild:
    def test_generates_valid_bash_script(self, seeded):
        r = _cli(seeded, "rebuild", "testenv", "wkstn-01")
        assert r.returncode == 0, r.stderr
        script = seeded / "environments" / "testenv" / "rebuild" / "wkstn-01-rebuild.sh"
        assert script.exists()
        # The generated restage script must itself be valid bash.
        check = subprocess.run(["bash", "-n", str(script)], capture_output=True, text=True)
        assert check.returncode == 0, check.stderr
        body = script.read_text()
        assert "apt-get install -y" in body
        assert "plasma-desktop" in body
        # GPU driver package, version token stripped:
        assert "mesa-utils" in body
        assert "mesa-utils 24.0" not in body

    def test_missing_baseline_reports_and_writes_nothing(self, tmp_path):
        r = _cli(tmp_path, "rebuild", "testenv", "ghost")
        assert "No baseline found" in r.stderr
        assert not (tmp_path / "environments" / "testenv" / "rebuild").exists()


class TestStatus:
    def test_reports_baselined_host(self, seeded):
        r = _cli(seeded, "status", "testenv")
        assert r.returncode == 0, r.stderr
        assert "wkstn-01" in r.stdout
        assert "baselined" in r.stdout

    def test_reports_pending_host(self, seeded):
        # A device with no baseline_captured marker shows as pending.
        devices = seeded / "environments" / "testenv" / "datasets" / "devices"
        (devices / "new-box.md").write_text("---\nname: new-box\n")
        r = _cli(seeded, "status", "testenv")
        assert "new-box" in r.stdout
        assert "pending" in r.stdout
