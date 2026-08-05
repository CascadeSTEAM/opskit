#!/usr/bin/env python3
"""Generate mikromcp's router config from this repo's device datasets.

opskit #105: ~/.mikromcp/routers.yaml was hand-maintained outside the repo — not
generated from it, not rebuildable, and drifting from the datasets in both
directions (a router missing entirely, a rosVersion two minor releases stale
because someone recorded the bootloader firmware instead of the OS). This makes
the datasets canonical and the config a build artifact.

Design choice, for maintainability as environments are added: everything is
DERIVED BY CONVENTION from facts already in the device record, with no per-device
wiring to keep in sync. Adding an environment means adding device records; there
is nothing else to edit here.

    routers.yaml id  <-  "<env>-<device name>"
    envPrefix        <-  "MIKROTIK_" + id, uppercased, non-alphanumerics to "_"
    host             <-  ip_address
    rosVersion       <-  os_version
    tags             <-  [env] + the record's own tags

A device record may override transport details under a `mikromcp:` key (port,
tls, reject_unauthorized, ssh_port) for the cases convention cannot know — most
importantly the move to 443/TLS once www-ssl is enabled per-device (#94), which
will land on one device at a time.

Selection is `os: RouterOS`. That deliberately excludes MikroTik gear running
SwOS, which has no RouterOS REST API and would fail every call.

Devices that cannot be wired are NOT silently dropped: they are listed, with the
reason, in a comment block at the top of the generated file. A missing router was
invisible before precisely because omission left no trace.

Usage:
  bin/gen-mikromcp-config.py --print          # to stdout
  bin/gen-mikromcp-config.py --check          # exit 1 if the live file differs
  bin/gen-mikromcp-config.py --write          # write it (backs up the existing)
  bin/gen-mikromcp-config.py --env-prefixes   # the env var names the vault map needs
"""

from __future__ import annotations

import argparse
import datetime
import difflib
import re
import shutil
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_TARGET = Path.home() / ".mikromcp" / "routers.yaml"

# Only RouterOS speaks the REST API mikromcp is built on.
MANAGED_OS = "routeros"


def parse_front_matter(path: Path) -> dict | None:
    """Read YAML front matter from a `---`-delimited markdown device record."""
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return None
    end = text.find("\n---", 3)
    if end == -1:
        return None
    try:
        data = yaml.safe_load(text[3:end])
    except yaml.YAMLError:
        return None
    return data if isinstance(data, dict) else None


def device_files(repo_root: Path) -> list[tuple[str, Path]]:
    """(env, path) for every device record, excluding the committed templates."""
    found = []
    for env_dir in sorted((repo_root / "environments").glob("*")):
        if not env_dir.is_dir() or env_dir.name == "example":
            continue
        devices = env_dir / "datasets" / "devices"
        if not devices.is_dir():
            continue
        for f in sorted(devices.glob("*.md")):
            found.append((env_dir.name, f))
    return found


def router_id(env: str, name: str) -> str:
    return f"{env}-{name}"


def env_prefix(rid: str) -> str:
    return "MIKROTIK_" + re.sub(r"[^A-Za-z0-9]+", "_", rid).upper()


def collect(repo_root: Path) -> tuple[dict, list[tuple[str, str]]]:
    """Returns (routers, skipped) where skipped is [(id, reason)]."""
    routers: dict = {}
    skipped: list[tuple[str, str]] = []

    for env, path in device_files(repo_root):
        rec = parse_front_matter(path)
        if not rec:
            continue
        if str(rec.get("os", "")).strip().lower() != MANAGED_OS:
            continue

        name = rec.get("name") or path.stem
        rid = router_id(env, name)

        if str(rec.get("status", "")).lower() == "decommissioned":
            skipped.append((rid, "status: decommissioned"))
            continue

        host = rec.get("ip_address")
        if not host:
            skipped.append((rid, "no ip_address in the device record"))
            continue

        version = rec.get("os_version")
        if version in (None, ""):
            # rosVersion is a required field in mikromcp's schema, and it selects
            # the WiFi API path (7.x vs 6.x). Guessing it would be worse than
            # refusing: a wrong value silently sends calls to the wrong endpoint.
            skipped.append((rid, "no os_version in the device record"))
            continue

        over = rec.get("mikromcp") or {}
        if over.get("enabled") is False:
            skipped.append((rid, str(over.get("reason") or "disabled in the device record")))
            continue

        tls_on = bool(over.get("tls", False))
        tags = [env] + [t for t in (rec.get("tags") or []) if t != env]

        routers[rid] = {
            "host": str(host),
            "port": int(over.get("port", 443 if tls_on else 80)),
            "tls": {
                "enabled": tls_on,
                # Left honest rather than convenient: claiming TLS while skipping
                # verification is worse than plain HTTP, because it looks secure.
                "rejectUnauthorized": bool(over.get("reject_unauthorized", tls_on)),
            },
            "credentials": {
                # mikromcp accepts credentials.source "vault" in its schema but
                # raises VAULT_NOT_SUPPORTED, so resolution happens in
                # bin/mcp-run.sh and arrives here as environment variables.
                "source": "env",
                "envPrefix": env_prefix(rid),
            },
            "tags": tags,
            "rosVersion": str(version),
        }
        if "ssh_port" in over:
            routers[rid]["sshPort"] = int(over["ssh_port"])

    return routers, skipped


def render(routers: dict, skipped: list[tuple[str, str]]) -> str:
    # No timestamp in the output, deliberately. A generation date would make
    # --check report drift every day after the file was written, with no dataset
    # change — and a drift detector that cries wolf is one people stop reading.
    # "When was it generated" is git history and the file's mtime.
    lines = [
        "# GENERATED FILE — do not edit by hand.",
        "#",
        "# Built from opskit device datasets by bin/gen-mikromcp-config.py.",
        "#",
        "# Edit the device record in environments/<env>/datasets/devices/ and",
        "# regenerate. Hand edits are lost, and drift here caused opskit #105:",
        "# a router missing entirely, and a stale version recorded from the",
        "# bootloader firmware instead of the OS.",
        "#",
        "# Credentials come from the environment, resolved from the vault at launch",
        "# by bin/mcp-run.sh. Run this for the variable names the vault map needs:",
        "#   bin/gen-mikromcp-config.py --env-prefixes",
    ]
    if skipped:
        lines += [
            "#",
            "# NOT INCLUDED — RouterOS devices in the datasets that could not be",
            "# wired. Listed so omission leaves a trace:",
        ]
        for rid, reason in skipped:
            lines.append(f"#   {rid}: {reason}")
    lines.append("")

    body = yaml.safe_dump(
        {"routers": routers}, default_flow_style=False, sort_keys=True, width=100
    )
    return "\n".join(lines) + body


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--print", action="store_true", help="write the config to stdout")
    mode.add_argument("--check", action="store_true", help="exit 1 if the target differs")
    mode.add_argument("--write", action="store_true", help="write the target file")
    mode.add_argument("--env-prefixes", action="store_true",
                      help="list the env var names each router expects")
    ap.add_argument("--target", type=Path, default=DEFAULT_TARGET)
    ap.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    args = ap.parse_args()

    routers, skipped = collect(args.repo_root)

    if not routers:
        print("ERROR: no RouterOS devices with an ip_address and os_version found",
              file=sys.stderr)
        return 1

    if args.env_prefixes:
        for rid in sorted(routers):
            p = routers[rid]["credentials"]["envPrefix"]
            print(f"{rid}\t{p}_USER\t{p}_PASS")
        return 0

    rendered = render(routers, skipped)

    if args.print:
        sys.stdout.write(rendered)
        return 0

    if args.check:
        current = args.target.read_text(encoding="utf-8") if args.target.is_file() else ""
        if current == rendered:
            print(f"OK: {args.target} matches the datasets ({len(routers)} routers)")
            return 0
        print(f"DRIFT: {args.target} differs from the datasets", file=sys.stderr)
        for line in difflib.unified_diff(
            current.splitlines(), rendered.splitlines(),
            fromfile=str(args.target), tofile="generated", lineterm="",
        ):
            print(line, file=sys.stderr)
        print("\nRegenerate with: bin/gen-mikromcp-config.py --write", file=sys.stderr)
        return 1

    args.target.parent.mkdir(parents=True, exist_ok=True)
    if args.target.is_file():
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        backup = args.target.with_suffix(args.target.suffix + f".bak-{stamp}")
        shutil.copy2(args.target, backup)
        print(f"backed up  {backup}")
    args.target.write_text(rendered, encoding="utf-8")
    print(f"wrote      {args.target} ({len(routers)} routers, {len(skipped)} skipped)")
    for rid, reason in skipped:
        print(f"  skipped  {rid}: {reason}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
