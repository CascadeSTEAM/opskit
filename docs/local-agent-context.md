# Local Agent Context — Generate It, Never Commit It

opskit is a public repo. Agent files (`agents/`), skills (`skills/`), and rules
(`rules/`) are committed and therefore MUST stay environment-agnostic: no real
IPs, hostnames, usernames, MACs, serials, or site topology. But agents work far
better with a concrete fact sheet of *your* network in front of them. This
document describes how to have both.

## The Two-Layer Model

```
Committed (public)                      Generated (gitignored, per environment)
──────────────────                      ────────────────────────────────────────
agents/*.md          generic behavior   environments/<env>/context/
skills/*/SKILL.md    + "read context    ├── critical-facts.md     ← site facts, host tables
rules/*.md             at runtime"      ├── ssh-access.md         ← alias → host → user map
docs/ + templates    methodology        └── <domain>-devices.md   ← per-agent device tables
bin/scan.py etc.     generators
environments/example/context/           fictional sample of the generated layer
```

`environments/*/` (everything except `example/`) is already gitignored, so the
`context/` layer can never be committed. The pre-commit hook additionally
blocks staged RFC1918 addresses anywhere in the tree (see Enforcement below).

## How Context Files Are Generated

1. **Populate datasets.** `bin/scan.py` (nmap discovery) enriches
   `environments/<env>/datasets/devices/*.yml` with IPs, MACs, OS, hardware,
   roles. Ansible fact-gathering (`bin/generate-network-docs.py`) adds
   interface/topology detail. Hand-edit anything the scanners can't know
   (owner, do-not-touch flags, BMC addresses).

2. **Generate fact sheets from datasets.** Ask your agent (or write a small
   script — automation-ladder it once you've done this twice) to render
   `environments/<env>/context/` from the datasets:
   - `critical-facts.md` — network boundaries, hypervisor table, ambiguous
     names, cross-site gotchas. Anything an agent commonly gets wrong.
   - `ssh-access.md` — table of SSH alias → address → user → key → quirks,
     derived from datasets + `~/.ssh/config`. Never raw credentials; reference
     vault/Bitwarden entries by name.
   - `<domain>-devices.md` — per-domain device tables (e.g. all MikroTik
     devices for the `@mikrotik` subagent).

   The format to follow is shown, with entirely fictional values, in
   `environments/example/context/`.

3. **Agents read the context layer at session start.** Committed agent files
   instruct: "read `environments/$ACTIVE_ENV/context/` if present, else derive
   from datasets." They never embed the data themselves.

4. **Regenerate after infra changes** — the document-as-you-go rule applies to
   the context layer too: change a device, update its dataset YAML, re-render.

## Rules for Anything Committed

- Addresses in committed files use documentation ranges only:
  `192.0.2.0/24`, `198.51.100.0/24`, `203.0.113.0/24` (RFC 5737), MACs from
  `00:11:22:*` or `AA:BB:CC:*`, hostnames like `ex-gw-01` / `example.local`.
- Example tables must be labeled as examples, adjacent to the instruction to
  read real data at runtime.
- Migrating content from a private ops repo? Treat every file as radioactive:
  strip it to structure + placeholders before it touches this repo. This is
  exactly how the 2026-07 leak happened — fact sheets written against live
  networks were bulk-copied here verbatim.

## Enforcement

- `.githooks/pre-commit` blocks commits whose staged additions contain
  RFC1918 addresses (`10.*`, `192.168.*`, `172.16–31.*`). For a legitimate
  generic example, prefer documentation ranges; if you truly need a private
  address in a committed file, override once with `ALLOW_PRIVATE_IPS=1 git commit …`.
- Only `environments/example/` may be committed (same hook).
- CI runs gitleaks for credential-shaped strings.
