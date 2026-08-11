"""Tests for bin/device_notes.py — shared device-dataset loader.

Extracted from bin/generate-network-docs.py's load_devices() during the
review of PR #192, which needed the same loader plus frontmatter-aware .md
parsing. One implementation instead of two silently-drifting copies.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "bin"))

import device_notes  # noqa: E402


class TestSplitFrontmatter:
    def test_returns_the_frontmatter_block_when_two_fences_present(self):
        text = "---\nname: gw\nrole: router\n---\n\nSome prose about this device.\n"
        assert device_notes.split_frontmatter(text) == "name: gw\nrole: router"

    def test_returns_the_whole_text_when_no_fences_present(self):
        text = "name: gw\nrole: router\n"
        assert device_notes.split_frontmatter(text) == text

    def test_returns_the_whole_text_when_only_one_fence_present(self):
        """A malformed device note (opening '---' with no closing one) must
        still be handed to yaml.safe_load() whole — a single leading '---'
        is a valid YAML document-start marker, so this can still parse."""
        text = "---\nname: gw\nrole: router\n"
        assert device_notes.split_frontmatter(text) == text


class TestLoadDevices:
    def test_loads_yml_records(self, tmp_path):
        (tmp_path / "gw.yml").write_text("name: gw\nrole: router\nip_address: 198.51.100.1\n")
        devices = device_notes.load_devices(tmp_path)
        assert devices["gw"]["role"] == "router"

    def test_ignores_md_files_unless_extra_glob_requests_them(self, tmp_path):
        (tmp_path / "gw.yml").write_text("name: gw\nrole: router\n")
        (tmp_path / "note.md").write_text("---\nname: note\nrole: server\n---\nprose\n")
        devices = device_notes.load_devices(tmp_path)
        assert "gw" in devices
        assert "note" not in devices

    def test_loads_md_with_frontmatter_and_prose_body(self, tmp_path):
        """The real device-note convention: two '---' fences, free-form
        prose after. Feeding the whole file to yaml.safe_load() raises
        ComposerError — reproduced against 155/157 real device notes."""
        (tmp_path / "note.md").write_text(
            "---\nname: note\nrole: server\nstatus: active\n---\n\n"
            "This device runs several services and has a long history.\n"
        )
        devices = device_notes.load_devices(tmp_path, extra_glob="*.md")
        assert devices["note"]["role"] == "server"

    def test_md_with_only_one_fence_still_parses(self, tmp_path):
        (tmp_path / "note.md").write_text("---\nname: note\nrole: server\n")
        devices = device_notes.load_devices(tmp_path, extra_glob="*.md")
        assert devices["note"]["role"] == "server"

    def test_unparseable_file_is_skipped_with_a_warning_not_fatal(self, tmp_path, capsys):
        (tmp_path / "good.yml").write_text("name: good\nrole: router\n")
        (tmp_path / "bad.yml").write_text("name: bad\nrole:\n  - not: [valid\n")
        devices = device_notes.load_devices(tmp_path)
        assert "good" in devices
        assert "bad" not in devices
        assert "skipping unparseable" in capsys.readouterr().err

    def test_unwraps_the_nested_device_key(self, tmp_path):
        (tmp_path / "srv.yml").write_text("device:\n  name: srv\n  role: server\n")
        devices = device_notes.load_devices(tmp_path)
        assert devices["srv"]["role"] == "server"

    def test_records_merged_into_another_are_skipped(self, tmp_path):
        (tmp_path / "old.yml").write_text("name: old\n_merged_into: new\n")
        devices = device_notes.load_devices(tmp_path)
        assert "old" not in devices

    def test_missing_devices_dir_returns_empty(self, tmp_path):
        assert device_notes.load_devices(tmp_path / "does-not-exist") == {}

    def test_name_falls_back_to_the_filename_stem(self, tmp_path):
        (tmp_path / "unnamed.yml").write_text("role: router\n")
        devices = device_notes.load_devices(tmp_path)
        assert "unnamed" in devices
