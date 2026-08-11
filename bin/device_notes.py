"""device_notes.py — shared device-dataset loader for docs-generation tools.

bin/generate-network-docs.py and bin/generate-base-view.py both read the same
environments/<env>/datasets/devices/ convention. One definition here instead
of two copies that silently drift (opskit #192 review).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n?(.*)$", re.DOTALL)


def split_frontmatter(text: str) -> str:
    """The YAML frontmatter block of `text` if it has one, else `text` itself.

    A device note stored as .md is frontmatter (delimited by two '---' lines)
    followed by free-form prose — not a single valid YAML document, so
    feeding the whole file to yaml.safe_load() raises ComposerError on every
    real device note that has a body (opskit #192 review: 155/157 sampled).
    """
    m = _FRONTMATTER_RE.match(text)
    return m.group(1) if m else text


def load_devices(devices_dir: Path, extra_glob: str | None = None) -> dict:
    """Device records from devices_dir/*.yml (and extra_glob, e.g. '*.md').

    Returns name -> record. Tolerates both the flat shape (top-level
    name/ip_address keys) and the scanner's nested shape (everything under a
    'device' key). A record that fails to load is skipped with a warning,
    not fatal — one bad file must not blank out the rest of the inventory.
    """
    devices: dict = {}
    if not devices_dir.is_dir():
        return devices

    patterns = ["*.yml"] + ([extra_glob] if extra_glob else [])
    files: list[Path] = []
    for pattern in patterns:
        files.extend(sorted(devices_dir.glob(pattern)))

    for f in files:
        try:
            text = f.read_text()
            if f.suffix == ".md":
                text = split_frontmatter(text)
            data = yaml.safe_load(text)
        except Exception as e:  # noqa: BLE001 — one bad file must not abort the loop
            print(f"  WARNING: skipping unparseable {f.name}: {e}", file=sys.stderr)
            continue
        if not isinstance(data, dict):
            continue
        record = data.get("device") if isinstance(data.get("device"), dict) else data
        if record.get("_merged_into"):
            continue
        devices[record.get("name", f.stem)] = record
    return devices
