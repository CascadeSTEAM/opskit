#!/usr/bin/env python3
"""Report client tokens the publication guards are probably missing.

opskit #133. Every guard in this repo — added lines, file paths, commit messages,
branch names — resolves its token list from `.client-tokens` plus the
`environments/*` directory names. That list is hand-maintained and nothing verified
it, so an unlisted client was simply unprotected and nothing said so. A client-named
branch reached the public remote that way.

The facts are already written down: every `env.yml` declares a display name, domains
and a ticket prefix, and device records carry hostnames. Those are precisely the
strings that must never be published.

REPORTS ONLY. It never writes `.client-tokens`. A list that grew itself would start
blocking innocuous words, and the response to a guard that cries wolf is
`ALLOW_CLIENT_TOKENS=1` — which disables every guard at once, not just the noisy one.

Reads only gitignored layers and prints nothing not already visible locally. Do not
paste its output anywhere public: it is, by construction, a list of client
identifiers.

Usage:
  bin/suggest-client-tokens.py            # what is missing
  bin/suggest-client-tokens.py --all      # also show what is already covered
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(os.environ.get("OPSKIT_ROOT", Path(__file__).resolve().parent.parent))

GREEN, YELLOW, RED, DIM, NC = "\033[0;32m", "\033[1;33m", "\033[0;31m", "\033[2m", "\033[0m"

# Public suffixes and infrastructure words that are not client identifiers. Matching
# on these would flag half the repo.
STOPWORDS = {
    "com", "org", "net", "io", "dev", "local", "lan", "internal", "home", "arpa",
    "co", "uk", "us", "ca", "info", "cloud", "app", "site", "tech",
    "www", "mail", "vpn", "dns", "ns", "api", "admin", "support", "helpdesk",
    "server", "host", "router", "switch", "gateway", "proxy", "backup",
    "prod", "dev", "test", "staging", "lab", "none", "example", "default",
    # Words that legitimately appear in DOMAIN position without naming anyone:
    # a DHCP-assigned name is "<host>.dhcp.<client>.<tld>".
    "dhcp", "dyn", "dynamic", "static", "wifi", "wlan", "guest", "corp", "ad",
}

# Below this length a token matches too much prose to be usable.
MIN_SAFE_LENGTH = 4


def load_yaml(path: Path) -> dict:
    try:
        data = yaml.safe_load(path.read_text())
    except (OSError, yaml.YAMLError):
        return {}
    return data if isinstance(data, dict) else {}


def env_layers(repo_root: Path) -> list[Path]:
    base = repo_root / "environments"
    if not base.is_dir():
        return []
    return sorted(d for d in base.iterdir()
                  if d.is_dir() and d.name != "example" and not d.name.startswith("."))


def words_from(text: str) -> set[str]:
    """Alphabetic runs of 3+ chars, lowercased. Digits are never identifiers."""
    return {w.lower() for w in re.findall(r"[A-Za-z]{3,}", str(text))}


def candidates_for(layer: Path) -> dict[str, set[str]]:
    """{candidate token: set of places it was found}."""
    found: dict[str, set[str]] = {}

    def note(word: str, where: str) -> None:
        found.setdefault(word, set()).add(where)

    cfg = load_yaml(layer / "env.yml")

    for word in words_from(cfg.get("display_name", "")):
        note(word, "env.yml display_name")

    domains = cfg.get("domains") or {}
    if isinstance(domains, dict):
        for key, value in domains.items():
            # Drop the public suffix; "cascadesteam.org" contributes "cascadesteam".
            for part in str(value).split("."):
                for word in words_from(part):
                    note(word, f"env.yml domains.{key}")

    ticket = cfg.get("ticket") or {}
    if isinstance(ticket, dict) and ticket.get("prefix"):
        for word in words_from(ticket["prefix"]):
            note(word, "env.yml ticket.prefix")

    vault = cfg.get("vault") or {}
    if isinstance(vault, dict) and vault.get("collection"):
        for word in words_from(vault["collection"]):
            note(word, "env.yml vault.collection")

    # Hostnames: take only the DOMAIN part, never the host label.
    #
    # The leftmost label names the machine — alpine, ansible, apache, brother, bulb,
    # cacher. Those are infrastructure words, not client identifiers, and suggesting
    # them produced exactly the noise this tool warns about: a list full of common
    # words leads to habitual ALLOW_CLIENT_TOKENS=1, which disables every guard.
    # The client lives in the domain: csrouter.<client>.local.
    devices = layer / "datasets" / "devices"
    if devices.is_dir():
        for record in sorted(devices.iterdir())[:200]:
            if record.suffix not in (".md", ".yml", ".yaml"):
                continue
            text = record.read_text(errors="replace")[:4000]
            for m in re.finditer(r"^hostname:\s*(\S+)", text, re.M):
                labels = m.group(1).split(".")
                if len(labels) < 2:
                    continue          # a bare machine name carries no client
                for part in labels[1:]:
                    for word in words_from(part):
                        note(word, "device hostname domain")

    return found


def covered_tokens(repo_root: Path) -> set[str]:
    """What the guards already match on: .client-tokens plus env directory names."""
    tokens = {d.name.lower() for d in env_layers(repo_root)}
    tokens_file = repo_root / ".client-tokens"
    if tokens_file.is_file():
        for line in tokens_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                tokens.add(line.lower())
    if os.environ.get("CLIENT_TOKENS"):
        for part in re.split(r"[,\s]+", os.environ["CLIENT_TOKENS"]):
            if part:
                tokens.add(part.lower())
    return tokens


def variants(token: str) -> list[str]:
    """Spellings a person might plausibly use.

    Word-boundary matching means each needs its own entry: a short abbreviation does
    not match the spelled-out name, which is exactly how a client went unguarded.
    """
    out = {token}
    if token.endswith("s") and len(token) > 4:
        out.add(token[:-1])          # widgets -> widget
    else:
        out.add(token + "s")
    return sorted(out)


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--all", action="store_true", help="also list already-covered tokens")
    ap.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    args = ap.parse_args()

    layers = env_layers(args.repo_root)
    if not layers:
        print("No environment layers present — nothing to derive tokens from.")
        return 0

    covered = covered_tokens(args.repo_root)
    missing: dict[str, tuple[set[str], set[str]]] = {}   # token -> (layers, places)
    unsafe: dict[str, str] = {}
    already: set[str] = set()

    for layer in layers:
        for token, places in candidates_for(layer).items():
            if token in STOPWORDS:
                continue
            if token in covered:
                already.add(token)
                continue
            if len(token) < MIN_SAFE_LENGTH:
                unsafe[token] = f"only {len(token)} characters — would match too much prose"
                continue
            layers_seen, places_seen = missing.setdefault(token, (set(), set()))
            layers_seen.add(layer.name)
            places_seen |= places

    print(f"Derived from {len(layers)} environment layer(s). "
          f"{len(covered)} token(s) currently guarded.\n")

    if missing:
        print(f"{RED}Candidate identifiers NOT currently guarded:{NC}")
        for token in sorted(missing):
            layers_seen, places = missing[token]
            print(f"  {RED}✗{NC} {token}")
            print(f"      {DIM}found in: {', '.join(sorted(places))} "
                  f"({', '.join(sorted(layers_seen))}){NC}")
            print(f"      {DIM}suggested entries: {' '.join(variants(token))}{NC}")
        print()

    if unsafe:
        print(f"{YELLOW}Too short or generic to use safely — decide deliberately:{NC}")
        for token, why in sorted(unsafe.items()):
            print(f"  {YELLOW}⚠{NC} {token} — {why}")
        print(f"  {DIM}A token that matches ordinary prose leads to habitual "
              f"ALLOW_CLIENT_TOKENS=1, which disables every guard at once.{NC}\n")

    if args.all and already:
        print(f"{GREEN}Already guarded:{NC} {', '.join(sorted(already))}\n")

    if not missing:
        print(f"{GREEN}No unguarded candidates found.{NC}")

    print(f"{DIM}Nothing was written. Add confirmed entries to .client-tokens "
          f"(one per line).{NC}")
    print(f"{DIM}This output lists client identifiers — do not paste it anywhere "
          f"public.{NC}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
