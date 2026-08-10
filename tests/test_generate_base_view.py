"""Tests for bin/generate-base-view.py.

base-view.yml was documented (schemas/directory-contract.md rule 4) as optional
per-environment config for Obsidian device-note generation, but nothing ever
consumed it, and no environment had a docs/devices/index.base or index.md
without one hand-written outside this repo. These tests cover the generator
offline against a fake environment tree.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "bin" / "generate-base-view.py"


@pytest.fixture
def fake_repo(tmp_path):
    devices = tmp_path / "environments" / "testenv" / "datasets" / "devices"
    devices.mkdir(parents=True)
    (devices / "gw.yml").write_text(
        "name: gw\nrole: router\nstatus: active\nip_address: 198.51.100.1\n"
    )
    # Two '---' fences + a prose body: the real device-note convention (not
    # a single YAML document), per opskit #192 review.
    (devices / "srv.md").write_text(
        "---\nname: srv\nrole: server\nstatus: active\nip: 198.51.100.10\n"
        "os: Debian\nservices:\n  - web\n  - dns\n---\n\n"
        "Some free-form notes about this server that are not YAML at all.\n"
    )
    return tmp_path


def run(repo_root, *args):
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True, text=True,
        env={"PATH": "/usr/bin:/bin", "OPSKIT_ROOT": str(repo_root)},
    )


def test_dry_run_does_not_write_files(fake_repo):
    result = run(fake_repo, "testenv")
    assert result.returncode == 0, result.stdout + result.stderr
    docs_dir = fake_repo / "environments" / "testenv" / "docs" / "devices"
    assert not docs_dir.exists()
    assert "Dry run" in result.stdout


def test_write_creates_index_base_and_index_md(fake_repo):
    result = run(fake_repo, "testenv", "--write")
    assert result.returncode == 0, result.stdout + result.stderr

    index_base = fake_repo / "environments" / "testenv" / "docs" / "devices" / "index.base"
    index_md = fake_repo / "environments" / "testenv" / "docs" / "devices" / "index.md"
    assert index_base.is_file()
    assert index_md.is_file()

    data = json.loads(index_base.read_text())
    assert data["obsidian"] is True
    assert data["name"] == "testenv — Device Inventory"
    assert [f["name"] for f in data["fields"]] == ["name", "role", "status", "ip_address"]

    text = index_md.read_text()
    assert "## router" in text
    assert "## server" in text
    assert "[[gw]]" in text and "198.51.100.1" in text
    # srv's ip field is 'ip', not 'ip_address' — must still resolve, not show '-'
    assert "[[srv]]" in text and "198.51.100.10" in text
    assert "web, dns" in text


def test_base_view_yml_overrides_title_and_group_by(fake_repo):
    env_dir = fake_repo / "environments" / "testenv"
    (env_dir / "base-view.yml").write_text(
        "views:\n  index:\n    title: Custom Title\n    group_by: status\n    sort: name\n"
    )
    result = run(fake_repo, "testenv", "--write")
    assert result.returncode == 0, result.stdout + result.stderr

    index_base = env_dir / "docs" / "devices" / "index.base"
    data = json.loads(index_base.read_text())
    assert data["name"] == "Custom Title"

    text = (env_dir / "docs" / "devices" / "index.md").read_text()
    assert "## active" in text  # grouped by status, not role


def test_unparseable_device_file_is_skipped_not_fatal(fake_repo):
    devices = fake_repo / "environments" / "testenv" / "datasets" / "devices"
    (devices / "broken.md").write_text("---\nname: broken\nrole:\n  - not: [valid\n")

    result = run(fake_repo, "testenv", "--write")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "skipping unparseable" in result.stderr

    text = (fake_repo / "environments" / "testenv" / "docs" / "devices" / "index.md").read_text()
    assert "broken" not in text
    assert "gw" in text  # the other, valid records still make it in


def test_no_device_records_produces_empty_but_valid_index(tmp_path):
    (tmp_path / "environments" / "empty" / "datasets" / "devices").mkdir(parents=True)
    result = run(tmp_path, "empty", "--write")
    assert result.returncode == 0, result.stdout + result.stderr

    text = (tmp_path / "environments" / "empty" / "docs" / "devices" / "index.md").read_text()
    assert "No device records found" in text


def test_fails_clearly_without_an_environment(tmp_path):
    result = run(tmp_path)
    assert result.returncode == 1
    assert "no active environment" in result.stdout.lower()


def test_fails_clearly_when_environment_does_not_exist(tmp_path):
    result = run(tmp_path, "nope")
    assert result.returncode == 1
    assert "does not exist" in result.stdout


def test_frontmatter_plus_prose_body_md_is_parsed(fake_repo):
    """The real device-note convention: two '---' fences with free-form
    markdown prose after the closing one. Feeding that whole file to
    yaml.safe_load() raises ComposerError (opskit #192 review, reproduced
    against 155/157 real device notes) — the fixture's srv.md has exactly
    this shape."""
    result = run(fake_repo, "testenv", "--write")
    assert result.returncode == 0, result.stdout + result.stderr

    text = (fake_repo / "environments" / "testenv" / "docs" / "devices" / "index.md").read_text()
    assert "[[srv]]" in text
    assert "198.51.100.10" in text
    assert "web, dns" in text


def test_explicit_null_group_by_value_falls_back_to_unknown(fake_repo):
    devices = fake_repo / "environments" / "testenv" / "datasets" / "devices"
    (devices / "blank-role.yml").write_text("name: blank-role\nrole:\nstatus: active\n")

    result = run(fake_repo, "testenv", "--write")
    assert result.returncode == 0, result.stdout + result.stderr

    text = (fake_repo / "environments" / "testenv" / "docs" / "devices" / "index.md").read_text()
    assert "## unknown" in text
    assert "[[blank-role]]" in text


def test_mixed_type_group_by_values_do_not_crash(fake_repo):
    """group_by is operator-configurable via base-view.yml and can point at
    any field — a device with an int value for that field and another
    missing it entirely must not crash sorted() comparing str to int."""
    env_dir = fake_repo / "environments" / "testenv"
    (env_dir / "base-view.yml").write_text(
        "views:\n  index:\n    group_by: vlan\n    sort: name\n"
    )
    devices = env_dir / "datasets" / "devices"
    (devices / "has-vlan.yml").write_text("name: has-vlan\nvlan: 10\nstatus: active\n")

    result = run(fake_repo, "testenv", "--write")
    assert result.returncode == 0, result.stdout + result.stderr
    text = (env_dir / "docs" / "devices" / "index.md").read_text()
    assert "## 10" in text
    assert "## unknown" in text


def test_explicit_null_sort_field_value_does_not_crash(fake_repo):
    devices = fake_repo / "environments" / "testenv" / "datasets" / "devices"
    (devices / "blank-name-field.yml").write_text(
        "name: blank-name-field\nrole: router\nstatus: active\n"
    )
    env_dir = fake_repo / "environments" / "testenv"
    (env_dir / "base-view.yml").write_text(
        "views:\n  index:\n    group_by: role\n    sort: notes\n"
    )

    result = run(fake_repo, "testenv", "--write")
    assert result.returncode == 0, result.stdout + result.stderr


def test_empty_services_list_renders_placeholder_not_blank(fake_repo):
    devices = fake_repo / "environments" / "testenv" / "datasets" / "devices"
    (devices / "no-services.yml").write_text(
        "name: no-services\nrole: router\nstatus: active\nservices: []\n"
    )

    result = run(fake_repo, "testenv", "--write")
    assert result.returncode == 0, result.stdout + result.stderr

    text = (fake_repo / "environments" / "testenv" / "docs" / "devices" / "index.md").read_text()
    row = [line for line in text.splitlines() if "[[no-services]]" in line][0]
    assert row.strip().endswith("| - |")


def test_dict_shaped_service_entries_render_by_name(fake_repo):
    """Real device notes use both shapes for `services`: a plain string, or
    a richer dict with a 'name' field (found live in a real environment's
    data — `", ".join(services)` crashes with TypeError on the dict shape)."""
    devices = fake_repo / "environments" / "testenv" / "datasets" / "devices"
    (devices / "rich-services.yml").write_text(
        "name: rich-services\nrole: router\nstatus: active\n"
        "services:\n  - name: nginx\n    type: systemd\n  - plain-string-service\n"
    )

    result = run(fake_repo, "testenv", "--write")
    assert result.returncode == 0, result.stdout + result.stderr

    text = (fake_repo / "environments" / "testenv" / "docs" / "devices" / "index.md").read_text()
    row = [line for line in text.splitlines() if "[[rich-services]]" in line][0]
    assert "nginx" in row
    assert "plain-string-service" in row


def test_device_notes_loader_is_shared_with_generate_network_docs():
    """opskit #192 review: two near-identical loaders drift silently — both
    tools must load through the one shared implementation."""
    import ast

    tree = ast.parse((ROOT / "bin" / "generate-base-view.py").read_text())
    imported = {n.names[0].name for n in ast.walk(tree) if isinstance(n, ast.Import)}
    assert "device_notes" in imported

    other_tree = ast.parse((ROOT / "bin" / "generate-network-docs.py").read_text())
    other_imported = {n.names[0].name for n in ast.walk(other_tree) if isinstance(n, ast.Import)}
    assert "device_notes" in other_imported
