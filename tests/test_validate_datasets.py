"""Tests for bin/validate-datasets.py (opskit #114, ledger rows 23/30/33).

The schemas declared required fields and constrained enums, and nothing checked a
single real record against either — tests/test_schemas.py validates the schema
*files*, not the data. Every consumer therefore had to assume nothing and guess
defensively.

Two behaviours matter most and both are easy to get wrong:

- It **reports** rather than fails by default. Enforcing on introduction would
  break immediately and unfixably (no record currently carries `owner`), and a
  check that can never pass gets ignored — worse than no check at all.
- Findings are **grouped by rule**, because "58 records missing `owner`" is one
  decision to make, while 58 separate lines read as 58 chores and get scrolled
  past.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VALIDATE = ROOT / "bin" / "validate-datasets.py"

VALID = {
    "name": "gw-01", "status": "active", "owner": "acme", "maturity": 1,
    "role": "router", "os": "RouterOS", "os_version": "7.21",
}


def _make_root(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "schemas").mkdir(parents=True)
    for name in ("device.schema.json", "env.schema.json"):
        (root / "schemas" / name).write_text((ROOT / "schemas" / name).read_text())
    return root


def _env(root: Path, name: str = "acme", env_yml: str | None = None) -> Path:
    d = root / "environments" / name / "datasets" / "devices"
    d.mkdir(parents=True, exist_ok=True)
    (root / "environments" / name / "env.yml").write_text(env_yml or _minimal_env(name))
    return d


def _minimal_env(name: str) -> str:
    return (
        f"name: {name}\ndisplay_name: {name.title()}\n"
        "ticket:\n  prefix: ACME\n"
        "domains:\n  primary: acme.local\n"
        "subnets:\n  primary: 192.0.2.0/24\n"
        "connectivity:\n  probes:\n    - host: 192.0.2.1\n"
        "vault:\n  backend: none\n"
        "source_of_truth:\n  type: git-yaml\n"
        "execution:\n  type: cli\n"
    )


def _record(devices: Path, name: str, fields: dict, ext: str = "md") -> None:
    import yaml
    body = yaml.safe_dump(fields, sort_keys=False)
    text = f"---\n{body}---\n" if ext == "md" else body
    (devices / f"{name}.{ext}").write_text(text)


def _run(root: Path, *args: str):
    env = {**os.environ, "OPSKIT_ROOT": str(root)}
    return subprocess.run(
        [sys.executable, str(VALIDATE), "--repo-root", str(root), *args],
        capture_output=True, text=True, env=env, timeout=60,
    )


# ── happy path and formats ────────────────────────────────────────────────────

def test_a_valid_layer_reports_clean(tmp_path):
    root = _make_root(tmp_path)
    _record(_env(root), "gw-01", VALID)

    result = _run(root)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "All records valid" in result.stdout


def test_md_front_matter_and_plain_yaml_are_both_read(tmp_path):
    root = _make_root(tmp_path)
    devices = _env(root)
    _record(devices, "gw-01", VALID, ext="md")
    _record(devices, "gw-02", {**VALID, "name": "gw-02"}, ext="yml")

    result = _run(root)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "2 device record(s)" in result.stdout


def test_the_committed_example_environment_is_skipped(tmp_path):
    """It is a template with placeholder data; validating it is noise."""
    root = _make_root(tmp_path)
    _record(_env(root, "example"), "broken", {"name": "x"})

    result = _run(root)

    assert "example" not in result.stdout


def test_no_environments_is_not_an_error(tmp_path):
    """environments/ is gitignored, so a fresh clone has none."""
    result = _run(_make_root(tmp_path))

    assert result.returncode == 0
    assert "No environments" in result.stdout


# ── the reporting contract ────────────────────────────────────────────────────

def test_problems_are_reported_without_failing_by_default(tmp_path):
    root = _make_root(tmp_path)
    _record(_env(root), "gw-01", {"name": "gw-01", "status": "active", "maturity": 1})

    result = _run(root)

    assert result.returncode == 0, "default mode must not fail"
    assert "missing required field `owner`" in result.stdout
    assert "Reporting only" in result.stdout


def test_strict_fails_on_the_same_input(tmp_path):
    root = _make_root(tmp_path)
    _record(_env(root), "gw-01", {"name": "gw-01", "status": "active", "maturity": 1})

    result = _run(root, "--strict")

    assert result.returncode == 1
    assert "missing required field `owner`" in result.stdout


def test_strict_passes_a_clean_layer(tmp_path):
    root = _make_root(tmp_path)
    _record(_env(root), "gw-01", VALID)

    assert _run(root, "--strict").returncode == 0


# ── grouping ──────────────────────────────────────────────────────────────────

def test_a_systemic_gap_is_one_line_with_a_count(tmp_path):
    """The whole point: 6 records missing a field is one decision, not 6 chores."""
    root = _make_root(tmp_path)
    devices = _env(root)
    for i in range(6):
        _record(devices, f"host-{i}", {"name": f"host-{i}", "status": "active",
                                       "maturity": 1})

    result = _run(root)

    assert "6/6 device records — missing required field `owner`" in result.stdout
    # A sample is enough; the full list would defeat the grouping.
    assert "+2 more" in result.stdout


def test_enum_violations_are_grouped_by_field(tmp_path):
    root = _make_root(tmp_path)
    devices = _env(root)
    for i in range(3):
        _record(devices, f"ct-{i}", {**VALID, "name": f"ct-{i}", "role": "lxc"})

    result = _run(root)

    assert "role: enum" in result.stdout
    assert "3/3" in result.stdout


# ── unreadable records ────────────────────────────────────────────────────────

def test_unterminated_front_matter_is_reported(tmp_path):
    """These are worse than invalid: every tool that reads front matter skips
    them silently, so the device is simply invisible."""
    root = _make_root(tmp_path)
    devices = _env(root)
    (devices / "half.md").write_text("---\nname: half\nstatus: active\n")

    result = _run(root)

    assert "not terminated" in result.stdout


def test_a_record_that_is_not_a_mapping_is_reported(tmp_path):
    root = _make_root(tmp_path)
    (_env(root) / "list.yml").write_text("- one\n- two\n")

    result = _run(root)

    assert "expected a mapping" in result.stdout


def test_invalid_yaml_is_reported_not_crashed_on(tmp_path):
    root = _make_root(tmp_path)
    (_env(root) / "bad.yml").write_text("key: [unclosed\n")

    result = _run(root)

    assert result.returncode == 0
    assert "invalid YAML" in result.stdout


def test_one_unreadable_record_does_not_stop_the_others(tmp_path):
    root = _make_root(tmp_path)
    devices = _env(root)
    (devices / "bad.yml").write_text("key: [unclosed\n")
    _record(devices, "gw-01", {"name": "gw-01", "status": "active", "maturity": 1})

    result = _run(root)

    assert "invalid YAML" in result.stdout
    assert "owner" in result.stdout


# ── env.yml validation ────────────────────────────────────────────────────────

def test_env_yml_is_validated_too(tmp_path):
    root = _make_root(tmp_path)
    d = root / "environments" / "acme" / "datasets" / "devices"
    d.mkdir(parents=True)
    (root / "environments" / "acme" / "env.yml").write_text("name: acme\n")

    result = _run(root)

    assert "env.yml" in result.stdout
    assert "missing required field" in result.stdout


def test_a_declared_format_mismatch_is_flagged(tmp_path):
    root = _make_root(tmp_path)
    devices = _env(root, env_yml=_minimal_env("acme").replace(
        "source_of_truth:\n  type: git-yaml\n",
        "source_of_truth:\n  type: git-yaml\n  format: md\n"))
    _record(devices, "gw-01", VALID, ext="yml")

    result = _run(root)

    assert "declares source_of_truth.format: md" in result.stdout


# ── schema versions (ledger row 33) ───────────────────────────────────────────

def test_both_schemas_declare_a_version():
    """Without one, a layer written a year ago is indistinguishable from current."""
    for name in ("device.schema.json", "env.schema.json"):
        schema = json.loads((ROOT / "schemas" / name).read_text())
        assert isinstance(schema.get("x-opskit-schema-version"), int), name


def test_versions_flags_a_layer_that_declares_none(tmp_path):
    root = _make_root(tmp_path)
    _env(root)

    result = _run(root, "--versions")

    assert "declares no schema_version" in result.stdout


def test_versions_flags_a_lagging_layer(tmp_path):
    root = _make_root(tmp_path)
    _env(root, env_yml=_minimal_env("acme") + "schema_version: 0\n")

    result = _run(root, "--versions")

    assert "may need a re-fit" in result.stdout


def test_versions_accepts_a_current_layer(tmp_path):
    root = _make_root(tmp_path)
    current = json.loads((ROOT / "schemas" / "env.schema.json").read_text())
    version = current["x-opskit-schema-version"]
    _env(root, env_yml=_minimal_env("acme") + f"schema_version: {version}\n")

    result = _run(root, "--versions")

    assert "may need a re-fit" not in result.stdout
    assert str(version) in result.stdout


def test_schema_version_is_optional_so_existing_layers_still_validate(tmp_path):
    """Introducing the key must not invalidate every layer on day one."""
    root = _make_root(tmp_path)
    _record(_env(root), "gw-01", VALID)

    result = _run(root, "--strict")

    assert result.returncode == 0, result.stdout


# ── scoping ───────────────────────────────────────────────────────────────────

def test_env_flag_limits_the_run(tmp_path):
    root = _make_root(tmp_path)
    _record(_env(root, "acme"), "gw-01", VALID)
    _record(_env(root, "other"), "bad", {"name": "bad"})

    result = _run(root, "--env", "acme")

    assert result.returncode == 0
    assert "other" not in result.stdout
