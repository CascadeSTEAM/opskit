#!/usr/bin/env python3
"""Read the agents.yml config for the active environment.

Usage:
    python3 bin/read-agents.py                  # print full config as JSON
    python3 bin/read-agents.py dns              # print just the dns section
    python3 bin/read-agents.py dns.instances    # print just dns.instances

Resolves ACTIVE_ENV the same way as active_env.py (export > .env > error).
Fails silently (exit 0, empty output) if the file does not exist — agents
should treat this as "no env-specific overrides, use defaults".

Does not validate — just loads YAML and prints JSON.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    print("WARNING: PyYAML not installed — skipping agents.yml", file=sys.stderr)
    sys.exit(0)


def _load_env_dir() -> Path | None:
    """Return the active environment's directory, or None."""
    sys.path.insert(0, str(Path(__file__).parent))
    from active_env import resolve

    env_name, _ = resolve(Path(__file__).parent.parent)
    if not env_name:
        return None
    return Path(__file__).parent.parent / "environments" / env_name


def main(argv: list[str]) -> int:
    env_dir = _load_env_dir()
    agents_file = env_dir / "agents.yml" if env_dir else None

    if not agents_file or not agents_file.exists():
        # No agents.yml — agents fall back to defaults.
        return 0

    try:
        data = yaml.safe_load(agents_file.read_text())
    except Exception as exc:
        print(f"ERROR: Failed to parse {agents_file}: {exc}", file=sys.stderr)
        return 1

    if not data:
        return 0

    # Support dotted-path queries: "dns.instances.0.name" → {"name": "bms"}
    # Accept either one dotted arg or multiple space-separated args that get
    # joined (both "dns.instances" and "dns" "instances" work).
    path_parts = argv
    if path_parts:
        parts = ".".join(path_parts).split(".")
        result = data
        for part in parts:
            if isinstance(result, dict):
                result = result.get(part, {})
            elif isinstance(result, list):
                try:
                    result = result[int(part)]
                except (ValueError, IndexError):
                    result = {}
                    break
            else:
                result = {}
                break
        print(json.dumps(result, indent=2))
    else:
        print(json.dumps(data, indent=2))

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
