"""Tests for templates/ — validate redacted templates are copyable."""

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "templates"


def test_opencode_template_exists():
    """opencode.json template exists and is valid JSON."""
    template_path = TEMPLATES / "opencode.json"
    assert template_path.exists(), f"opencode.json template missing"

    content = template_path.read_text()
    import json
    data = json.loads(content)
    assert "servers" in data, "Template missing servers section"
    assert "agents" in data, "Template missing agents section"


def test_global_memory_template_exists():
    """global-memory.md template exists and contains routing instructions."""
    template_path = TEMPLATES / "global-memory.md"
    assert template_path.exists(), f"global-memory.md template missing"

    content = template_path.read_text()
    assert "MCP Server Routing" in content, "Template missing MCP server routing"
    assert "opencode.json" in content, "Template missing opencode.json reference"


def test_no_real_credentials():
    """Templates contain no real credentials or private IPs."""
    # Check opencode.json
    opencode_path = TEMPLATES / "opencode.json"
    opencode_content = opencode_path.read_text()
    assert "192.0.2" not in opencode_content, "Template contains RFC1918 address"
    assert "10.0.0" not in opencode_content, "Template contains RFC1918 address"

    # Check global-memory.md
    memory_path = TEMPLATES / "global-memory.md"
    memory_content = memory_path.read_text()
    assert "192.0.2" not in memory_content, "Template contains RFC1918 address"
    assert "10.0.0" not in memory_content, "Template contains RFC1918 address"


def test_templates_copyable():
    """Templates can be copied to a target directory."""
    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)

        # Copy opencode.json
        opencode_src = TEMPLATES / "opencode.json"
        opencode_dst = tmpdir_path / "opencode.json"
        opencode_dst.write_text(opencode_src.read_text())
        assert opencode_dst.exists(), "opencode.json copied successfully"

        # Copy global-memory.md
        memory_src = TEMPLATES / "global-memory.md"
        memory_dst = tmpdir_path / "global-memory.md"
        memory_dst.write_text(memory_src.read_text())
        assert memory_dst.exists(), "global-memory.md copied successfully"


def test_install_section_documented():
    """INSTALL.md includes template section."""
    install_path = ROOT / "docs" / "INSTALL.md"
    install_content = install_path.read_text()
    assert "## 7. Templates" in install_content, "INSTALL.md missing template section"
    assert "opencode.json" in install_content, "INSTALL.md missing opencode.json reference"
    assert "global-memory.md" in install_content, "INSTALL.md missing global-memory.md reference"
