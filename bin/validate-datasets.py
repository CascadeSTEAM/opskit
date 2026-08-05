#!/usr/bin/env python3
"""Validate environment data against the schemas that claim to describe it.

opskit #114 (ledger rows 23, 30, 33). schemas/device.schema.json and
schemas/env.schema.json declare required fields and constrained enums, and until
now nothing checked a single real record against either. tests/test_schemas.py
validates the schema *files*, not the data.

The cost of that gap is paid by every consumer: none can rely on a required field
being present, so each reinvents defensive guesswork. The mikromcp config
generator added in #105 has to skip records field-by-field for exactly this
reason.

REPORTS BY DEFAULT, does not fail. Enforcing on day one would break immediately
and unfixably — no device record currently carries the required `owner` — and a
check that always fails gets skipped, which is worse than no check. Use --strict
once a layer is clean, and in CI.

Findings are grouped by rule rather than by file: "16 records missing `owner`" is
one systemic gap to decide about, where sixteen separate lines read as sixteen
chores and get scrolled past.

Usage:
  bin/validate-datasets.py                 # every environment, report only
  bin/validate-datasets.py --env <name>    # just one
  bin/validate-datasets.py --strict        # exit 1 if anything fails
  bin/validate-datasets.py --versions      # schema-version report only
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator

REPO_ROOT = Path(os.environ.get("OPSKIT_ROOT", Path(__file__).resolve().parent.parent))
SCHEMA_DIR = REPO_ROOT / "schemas"

GREEN, YELLOW, RED, DIM, NC = "\033[0;32m", "\033[1;33m", "\033[0;31m", "\033[2m", "\033[0m"


def load_schema(name: str) -> dict:
    return json.loads((SCHEMA_DIR / name).read_text())


def schema_version(schema: dict) -> str | None:
    return schema.get("x-opskit-schema-version")


def front_matter(path: Path) -> tuple[dict | None, str | None]:
    """Read a record, whether it is `.yml` or `.md` with YAML front matter.

    Both shapes are accepted regardless of what env.yml declares. The declared
    format says what the layer is *converging on*; punishing a half-migrated
    layer for containing both would make the check useless exactly when it is
    most wanted.
    """
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".md":
        if not text.startswith("---"):
            return None, "no YAML front matter (file starts without ---)"
        end = text.find("\n---", 3)
        if end == -1:
            return None, "front matter is not terminated by ---"
        text = text[3:end]
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        return None, f"invalid YAML: {str(exc).splitlines()[0]}"
    if data is None:
        return None, "empty record"
    if not isinstance(data, dict):
        return None, f"expected a mapping, got {type(data).__name__}"
    return data, None


def environments(repo_root: Path, only: str | None = None) -> list[Path]:
    base = repo_root / "environments"
    if not base.is_dir():
        return []
    out = []
    for d in sorted(base.iterdir()):
        if not d.is_dir() or d.name == "example":
            continue
        if only and d.name != only:
            continue
        out.append(d)
    return out


def device_records(env_dir: Path) -> list[Path]:
    devices = env_dir / "datasets" / "devices"
    if not devices.is_dir():
        return []
    return sorted(p for p in devices.iterdir()
                  if p.suffix in (".md", ".yml", ".yaml") and p.is_file())


def declared_format(env_cfg: dict) -> str | None:
    sot = env_cfg.get("source_of_truth") or {}
    return sot.get("format") if isinstance(sot, dict) else None


def validate_record(validator: Draft202012Validator, data: dict) -> list[tuple[str, str]]:
    """Returns [(rule, detail)] — rule is the grouping key."""
    findings = []
    for err in validator.iter_errors(data):
        if err.validator == "required":
            # One finding per missing field, so counts group meaningfully.
            missing = err.message.split("'")[1] if "'" in err.message else err.message
            findings.append((f"missing required field `{missing}`", ""))
        else:
            where = ".".join(str(p) for p in err.absolute_path) or "(root)"
            findings.append((f"{where}: {err.validator}", err.message.split("\n")[0][:120]))
    return findings


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--env", help="validate only this environment")
    ap.add_argument("--strict", action="store_true",
                    help="exit 1 when anything fails validation")
    ap.add_argument("--versions", action="store_true",
                    help="report schema versions only")
    ap.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    args = ap.parse_args()

    device_schema = load_schema("device.schema.json")
    env_schema = load_schema("env.schema.json")
    device_validator = Draft202012Validator(device_schema)
    env_validator = Draft202012Validator(env_schema)

    envs = environments(args.repo_root, args.env)
    if not envs:
        target = f" matching '{args.env}'" if args.env else ""
        print(f"No environments{target} found (environments/ is gitignored — "
              f"nothing to validate in a fresh clone).")
        return 0

    current_env_version = schema_version(env_schema)
    current_device_version = schema_version(device_schema)
    total_problems = 0

    if args.versions:
        print(f"Current contract: env schema {current_env_version}, "
              f"device schema {current_device_version}\n")
        for env_dir in envs:
            cfg, err = (front_matter(env_dir / "env.yml")
                        if (env_dir / "env.yml").is_file() else (None, "no env.yml"))
            got = (cfg or {}).get("schema_version")
            if got is None:
                print(f"  {YELLOW}?{NC} {env_dir.name:<10} declares no schema_version "
                      f"(current: {current_env_version})")
                total_problems += 1
            elif str(got) != str(current_env_version):
                print(f"  {YELLOW}!{NC} {env_dir.name:<10} schema_version {got} "
                      f"< current {current_env_version} — may need a re-fit")
                total_problems += 1
            else:
                print(f"  {GREEN}✓{NC} {env_dir.name:<10} schema_version {got}")
        return 1 if (args.strict and total_problems) else 0

    for env_dir in envs:
        print(f"\n{env_dir.name}")
        env_problems = 0

        env_file = env_dir / "env.yml"
        if not env_file.is_file():
            print(f"  {RED}✗{NC} no env.yml")
            env_problems += 1
            env_cfg = {}
        else:
            env_cfg, err = front_matter(env_file)
            if err:
                print(f"  {RED}✗{NC} env.yml unreadable: {err}")
                env_problems += 1
                env_cfg = {}
            else:
                findings = validate_record(env_validator, env_cfg)
                for rule, detail in findings:
                    print(f"  {RED}✗{NC} env.yml — {rule}"
                          + (f" {DIM}{detail}{NC}" if detail else ""))
                env_problems += len(findings)

        records = device_records(env_dir)
        fmt = declared_format(env_cfg)
        exts = {p.suffix for p in records}
        if fmt and exts and f".{fmt}" not in exts:
            print(f"  {YELLOW}⚠{NC} env.yml declares source_of_truth.format: {fmt} "
                  f"but records are {', '.join(sorted(exts))}")

        # Group by rule: a systemic gap is one decision, not N chores.
        by_rule: dict[str, list[str]] = defaultdict(list)
        unreadable: list[tuple[str, str]] = []
        for path in records:
            data, err = front_matter(path)
            if err:
                unreadable.append((path.name, err))
                continue
            for rule, _detail in validate_record(device_validator, data):
                by_rule[rule].append(path.name)

        for name, err in unreadable:
            print(f"  {RED}✗{NC} {name}: {err}")
        env_problems += len(unreadable)

        for rule in sorted(by_rule, key=lambda r: (-len(by_rule[r]), r)):
            files = by_rule[rule]
            shown = ", ".join(files[:4]) + (f", +{len(files) - 4} more" if len(files) > 4 else "")
            print(f"  {RED}✗{NC} {len(files)}/{len(records)} device records — {rule}")
            print(f"      {DIM}{shown}{NC}")
        env_problems += sum(len(v) for v in by_rule.values())

        if env_problems == 0:
            print(f"  {GREEN}✓{NC} {len(records)} device record(s) and env.yml valid")
        total_problems += env_problems

    print()
    if total_problems == 0:
        print(f"{GREEN}All records valid.{NC}")
        return 0

    print(f"{YELLOW}{total_problems} validation problem(s).{NC}")
    if args.strict:
        return 1
    # Reporting mode is the point, not a weakness: enforcing before the backlog
    # is cleared produces a check nobody can ever make pass, which gets ignored.
    print(f"{DIM}Reporting only. Use --strict to fail (CI, or a clean layer).{NC}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
