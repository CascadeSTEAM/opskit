#!/usr/bin/env python3
"""
Proxmox MCP launcher — wires `proxmox-mcp-plus` into this repo's vault-resolving
launcher, per environment (opskit issue #86).

WHY A WRAPPER RATHER THAN A SERVER
  proxmox-mcp-plus already provides the tool surface; what was missing was
  everything around it. The runtime entry pointed at a PROXMOX_MCP_CONFIG that
  was set nowhere, so the server exited during init and reported a bare
  `MCP error -32000: Connection closed` — the same silent launch failure #80
  exists to prevent. Credentials would also have had to live in a plaintext
  config file on disk, against `no-plaintext-creds`.

  Naming this file `<server>-mcp-server.py` means `bin/mcp-run.sh proxmox` finds
  it with no changes to the launcher: secrets arrive as environment variables
  resolved from the vault, this script turns them into what the upstream server
  expects, and execs it.

THE TOKEN SPLIT
  A Proxmox API token identity is stored as one string, `user@realm!tokenname`,
  which is also how the vault item records it. The upstream server needs
  PROXMOX_USER and PROXMOX_TOKEN_NAME separately — passing the combined form
  produces a malformed PVEAPIToken header and a 401 that looks like a bad
  credential. Splitting here keeps the vault map free of transforms: one vault
  field maps to one environment variable, and the parsing lives in code where it
  is testable.

CONFIGURATION
  mcp/tenants-proxmox.local.json (gitignored — see tenants-proxmox.example.json):

    {
      "<env>": {
        "host": "<hostname-or-address>",
        "port": 8006,
        "verify_ssl": false,
        "env_token_identity": "PROXMOX_<ENV>_TOKEN_IDENTITY",
        "env_token_value":    "PROXMOX_<ENV>_TOKEN_VALUE",
        "description": "..."
      }
    }

  Host and port are topology, not secrets, so they live here rather than in the
  vault map. The environment is selected by PROXMOX_ENV, else ACTIVE_ENV from
  .env — the same environment the rest of the toolkit is pointed at.

  PROXMOX_TENANTS_FILE overrides the path (the test suite uses it so the suite
  never reads a developer's real file — opskit #76).

Usage:
  bin/mcp-run.sh proxmox              # secrets from the vault, then exec
  python3 mcp/proxmox-mcp-server.py --check   # validate config, launch nothing
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(os.environ.get("OPSKIT_ROOT") or Path(__file__).resolve().parents[1])

_TENANTS_FILE = (
    Path(os.environ["PROXMOX_TENANTS_FILE"])
    if os.environ.get("PROXMOX_TENANTS_FILE")
    else Path(__file__).parent / "tenants-proxmox.local.json"
)

UPSTREAM = ["uvx", "proxmox-mcp-plus"]


def _die(msg: str, *hints: str) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    for h in hints:
        print(f"  {h}", file=sys.stderr)
    sys.exit(1)


def load_tenants() -> dict:
    if not _TENANTS_FILE.exists():
        return {}
    try:
        return json.loads(_TENANTS_FILE.read_text())
    except json.JSONDecodeError as exc:
        _die(f"{_TENANTS_FILE.name} is not valid JSON: {exc}")
    return {}


def active_env() -> str:
    """PROXMOX_ENV wins, else ACTIVE_ENV from .env — one source of truth for
    which environment the toolkit is pointed at."""
    if os.environ.get("PROXMOX_ENV"):
        return os.environ["PROXMOX_ENV"].strip()
    dotenv = REPO_ROOT / ".env"
    if dotenv.exists():
        for line in dotenv.read_text().splitlines():
            if line.startswith("ACTIVE_ENV="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def split_identity(identity: str) -> tuple:
    """`root@pam!mcp-claude` -> ("root@pam", "mcp-claude").

    Refuses a value without a token name rather than guessing: a combined
    identity sent as PROXMOX_USER yields a malformed auth header and a 401 that
    reads as a wrong credential.
    """
    identity = (identity or "").strip()
    if "!" not in identity:
        raise ValueError(
            f"token identity {identity!r} has no '!' — expected user@realm!tokenname"
        )
    user, _, token_name = identity.partition("!")
    if not user or not token_name:
        raise ValueError(f"token identity {identity!r} is missing a user or token name")
    return user, token_name


def build_env(env_name: str, cfg: dict, source: dict) -> dict:
    identity = source.get(cfg.get("env_token_identity", ""), "")
    secret = source.get(cfg.get("env_token_value", ""), "")
    if not identity:
        _die(
            f"{cfg.get('env_token_identity')} is not set for environment '{env_name}'",
            "secrets come from the vault via: bin/mcp-run.sh proxmox",
        )
    if not secret:
        _die(f"{cfg.get('env_token_value')} is not set for environment '{env_name}'")

    try:
        user, token_name = split_identity(identity)
    except ValueError as exc:
        _die(str(exc), "the vault item's username field holds the full identity")

    host = str(cfg.get("host") or "").strip()
    if not host:
        _die(f"environment '{env_name}' has no host in {_TENANTS_FILE.name}")

    out = dict(source)
    out.update({
        "PROXMOX_HOST": host,
        "PROXMOX_PORT": str(cfg.get("port", 8006)),
        "PROXMOX_USER": user,
        "PROXMOX_TOKEN_NAME": token_name,
        "PROXMOX_TOKEN_VALUE": secret,
        "PROXMOX_VERIFY_SSL": "true" if cfg.get("verify_ssl", False) else "false",
    })
    return out


def resolve(source: dict) -> tuple:
    tenants = load_tenants()
    if not tenants:
        _die(
            f"{_TENANTS_FILE.name} not found or empty",
            "copy mcp/tenants-proxmox.example.json and fill in your environments",
        )
    env_name = active_env()
    if not env_name:
        _die(
            "no environment selected",
            "set ACTIVE_ENV (bin/switch-env.sh <env>) or PROXMOX_ENV",
            f"configured: {', '.join(sorted(tenants))}",
        )
    if env_name not in tenants:
        _die(
            f"environment '{env_name}' has no Proxmox node configured",
            f"configured: {', '.join(sorted(tenants))}",
            f"add it to {_TENANTS_FILE.name} if this environment has one",
        )
    return env_name, build_env(env_name, tenants[env_name], source)


def check() -> int:
    """Validate everything that would otherwise fail as a silent MCP startup."""
    ok = True
    print("=== proxmox-mcp launcher check ===")

    if shutil.which(UPSTREAM[0]):
        print(f"  ✓ {UPSTREAM[0]:<18} {shutil.which(UPSTREAM[0])}")
    else:
        ok = False
        print(f"  ✗ {UPSTREAM[0]:<18} not on PATH — install uv "
              f"(ansible/playbooks/workstation-mcp-toolchain.yml)", file=sys.stderr)

    tenants = load_tenants()
    if tenants:
        print(f"  ✓ {'tenants file':<18} {_TENANTS_FILE} ({len(tenants)} environment(s))")
    else:
        ok = False
        print(f"  ✗ {'tenants file':<18} {_TENANTS_FILE} missing or empty", file=sys.stderr)

    env_name = active_env()
    if env_name:
        print(f"  ✓ {'environment':<18} {env_name}")
    else:
        ok = False
        print(f"  ✗ {'environment':<18} none selected (ACTIVE_ENV / PROXMOX_ENV)",
              file=sys.stderr)

    if tenants and env_name:
        cfg = tenants.get(env_name)
        if not cfg:
            ok = False
            print(f"  ✗ {'node':<18} environment '{env_name}' has no Proxmox node "
                  f"configured", file=sys.stderr)
        else:
            print(f"  ✓ {'node':<18} {cfg.get('host')}:{cfg.get('port', 8006)}")
            for key in ("env_token_identity", "env_token_value"):
                var = cfg.get(key, "")
                if not var:
                    ok = False
                    print(f"  ✗ {key:<18} not declared in the tenants file", file=sys.stderr)
                elif os.environ.get(var):
                    print(f"  ✓ {var:<18} set")
                else:
                    ok = False
                    print(f"  ✗ {var:<18} not set — resolve it from the vault via "
                          f"bin/mcp-run.sh proxmox", file=sys.stderr)

    print()
    if ok:
        print("  Launch path OK. Credentials are used at launch, not verified here.")
        return 0
    print("  Problems above — this server would fail to serve tools.", file=sys.stderr)
    return 1


def main() -> int:
    if "--check" in sys.argv:
        return check()
    if not shutil.which(UPSTREAM[0]):
        _die(f"{UPSTREAM[0]} is not on PATH",
             "install uv: bin/ap.sh playbooks/workstation-mcp-toolchain.yml")
    _env_name, env = resolve(dict(os.environ))
    os.execvpe(UPSTREAM[0], UPSTREAM, env)
    return 1  # unreachable; execvpe replaces the process


if __name__ == "__main__":
    sys.exit(main())
