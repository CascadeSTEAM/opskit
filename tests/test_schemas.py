"""Schema validation tests for opskit environment contract."""
import json
import yaml
from pathlib import Path
from typing import Any


ROOT = Path(__file__).parent.parent


def _load_json_schema(name: str) -> dict:
    path = ROOT / "schemas" / name
    return json.loads(path.read_text())


def _load_yaml(path: Path) -> Any:
    return yaml.safe_load(path.read_text())


class TestEnvSchema:
    """Validate env.yml against env.schema.json."""

    @classmethod
    def setup_class(cls):
        from jsonschema import Draft202012Validator
        cls.schema = _load_json_schema("env.schema.json")
        cls.validator = Draft202012Validator(cls.schema)

    def test_example_env_conforms(self):
        env = _load_yaml(ROOT / "environments/example/env.yml")
        errors = list(self.validator.iter_errors(env))
        assert not errors, f"Example env.yml has schema errors: {errors}"

    def test_required_fields(self):
        """Env with missing required fields should fail."""
        minimal = {"name": "test"}
        errors = list(self.validator.iter_errors(minimal))
        assert len(errors) > 0

    def test_name_pattern(self):
        """Name must match lowercase + hyphens pattern."""
        bad_names = ["Test", "TEST", "has_underscore", ""]
        for name in bad_names:
            env = {"name": name}
            errors = list(self.validator.iter_errors(env))
            assert len(errors) > 0, f"Name '{name}' should be invalid"

    def test_ticket_prefix_pattern(self):
        """Ticket prefix must be 2-4 uppercase letters."""
        env = _load_yaml(ROOT / "environments/example/env.yml")
        env["ticket"]["prefix"] = "invalid123"
        errors = list(self.validator.iter_errors(env))
        assert len(errors) > 0

    def test_netbox_sot_requires_url(self):
        """When SoT type is netbox, netbox_url is required."""
        env = _load_yaml(ROOT / "environments/example/env.yml")
        env["source_of_truth"]["type"] = "netbox"
        del env["source_of_truth"]["netbox_url"]
        errors = list(self.validator.iter_errors(env))
        assert len(errors) > 0, "netbox_url should be required when type=netbox"

    def test_semaphore_execution_requires_url(self):
        """When execution type is semaphore, semaphore_url is required."""
        env = _load_yaml(ROOT / "environments/example/env.yml")
        env["execution"]["type"] = "semaphore"
        env["execution"]["semaphore_project"] = "test"
        errors = list(self.validator.iter_errors(env))
        assert len(errors) > 0, "semaphore_url should be required when type=semaphore"

    def test_subnets_are_valid_cidr(self):
        """All subnet values must be valid CIDR notation."""
        env = _load_yaml(ROOT / "environments/example/env.yml")
        for name, cidr in env["subnets"].items():
            parts = cidr.split("/")
            assert len(parts) == 2, f"Subnet '{name}': '{cidr}' is not CIDR"
            assert 0 <= int(parts[1]) <= 32, f"Subnet '{name}': prefix length out of range"


class TestDeviceSchema:
    """Validate device YAMLs against device.schema.json."""

    @classmethod
    def setup_class(cls):
        from jsonschema import Draft202012Validator
        cls.schema = _load_json_schema("device.schema.json")
        cls.validator = Draft202012Validator(cls.schema)

    def test_all_example_devices_conform(self):
        devices_dir = ROOT / "environments/example/datasets/devices"
        yml_files = list(devices_dir.glob("*.yml"))
        assert len(yml_files) == 5, f"Expected 5 devices, found {len(yml_files)}"

        for path in sorted(yml_files):
            device = _load_yaml(path)
            errors = list(self.validator.iter_errors(device))
            assert not errors, f"{path.name}: {errors}"

    def test_device_owner_matches_environment(self):
        """Every device's owner field must be 'example'."""
        devices_dir = ROOT / "environments/example/datasets/devices"
        for path in devices_dir.glob("*.yml"):
            device = _load_yaml(path)
            assert device["owner"] == "example", f"{path.name}: owner={device['owner']}, expected 'example'"

    def test_mac_address_format(self):
        """MAC addresses use colon separators."""
        devices_dir = ROOT / "environments/example/datasets/devices"
        for path in devices_dir.glob("*.yml"):
            device = _load_yaml(path)
            if "mac_address" in device:
                parts = device["mac_address"].split(":")
                assert len(parts) == 6, f"{path.name}: invalid MAC {device['mac_address']}"


class TestDirectoryContract:
    """Validate environment directory structure."""

    def test_required_paths_exist(self):
        env_dir = ROOT / "environments/example"
        required = [
            "env.yml",
            "ansible/",
            "datasets/",
            "datasets/devices/",
        ]
        for path in required:
            full = env_dir / path
            assert full.exists(), f"Required path missing: {path}"

    def test_no_real_environment_leaks(self):
        """Only environments/example/ should exist in git."""
        envs_dir = ROOT / "environments"
        env_dirs = [d for d in envs_dir.iterdir() if d.is_dir() and d.name != "example"]
        assert not env_dirs, f"Real environment directories found: {env_dirs}"
