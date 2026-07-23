# Idea Ledger

Raw enhancement/tooling ideas land here first, as a single ledger
row — not as an individual GitHub issue per idea. This keeps early,
overlapping ideas cheap to capture and consolidatable before they
become tracked work (Development Principle 1: never lose an idea —
but a ticket flood isn't the win condition either).

**Capture vs. triage.** Anyone (an agent or a human) can *capture* an
idea any time via `bin/idea.py add` — no judgment call required, no
board noise. *Triage* — clustering overlapping rows, deciding what's
worth a GitHub issue, and filing it — is a separate, deliberate pass,
done by the `idea-triage` skill
(`.opencode/skills/idea-triage/SKILL.md`). A row only gets a GH# once
triage has actually filed (or matched it to) an issue.

Manage this table with `bin/idea.py` (`add`, `list`, `search`,
`mark`) rather than hand-editing — it keeps pipe-escaping and row
numbering consistent. Run `bin/idea.py --help` for full usage.

| Date | Desire (1-5) | Title | Description | Status | GH# |
|------|--------------|-------|-------------|--------|-----|
| 2026-07-20 | 3 | opskit init: refuse case-insensitive duplicate env names | init scaffolded an uppercase twin of an existing environment; it should detect case-insensitive collisions and refuse (or offer to adopt the existing env) | accepted | 23 |
| 2026-07-20 | 4 | flag inventory hosts missing device YAMLs | generic check: every host in an environment inventory should have a datasets/devices YAML; scan or a lint command should report gaps | accepted | 24 |
| 2026-07-20 | 3 | run opskit lint in CI e2e job | the e2e-pipeline CI job scaffolds a fake env and scans a fixture; running opskit lint against it (and against environments/example) would catch inventory/device-YAML drift on every PR | accepted | 29 |
| 2026-07-21 | 4 | opskit scan: auto-elevate or warn when local-subnet scan runs unprivileged | on a local LAN, nmap needs root for ARP; without it the scan writes device YAMLs with empty MACs and no vendor. cmd_scan should detect a local subnet + non-root and either re-exec with sudo or emit a clear warning (nmap_runner already has use_sudo). Found during a live LAN scan. | new |  |
| 2026-07-21 | 3 | opskit scan: resolve hostnames from DNS/DHCP, not just reverse-PTR | scan named only ~14% of hosts on a live LAN; the authoritative names came from the Technitium DHCP lease table + Proxmox CT map. scan could optionally query an env-configured DNS/DHCP source (or PVE API) to name hosts instead of leaving host-<ip> stubs. | new |  |
| 2026-07-22 | 4 | System baseline capture skill | Codify the manual process of capturing a known-good system state for comparison during troubleshooting. Should capture: OS/kernel, GPU/drivers, display config (KScreen), key packages, services, network config. Output a device YAML baseline file that can be used to restage from scratch. Surfaced during a hands-on display-config debug session on a workstation. | accepted | 37 |
| 2026-07-22 | 4 | Guard branch names against client tokens | publication-guard.sh checks staged content + commit messages but NOT branch names; the AGENTS.md client-data rule explicitly forbids client-identifying branch names. Add a pre-push hook (and/or CI check) rejecting branch names that contain any .client-tokens entry. Surfaced when a client-named feature branch was found already pushed to the public origin. | new |  |
| 2026-07-23 | 3 | Weak-signal access-list pattern for CAPsMAN APs | After an AP outage, IoT clients fail over to a distant AP and stick there at unusable signal. Codify a CAPsMAN access-list (reject below ~-85 dBm) as a reusable Ansible-managed pattern so sticky clients re-home automatically. | new |  |
| 2026-07-23 | 3 | Detect duplicate DHCP client hostnames; manage reservations | Devices sharing a client hostname make the DHCP-updated DNS A record flap between them; hostname-less devices get no record. Teach scan/tooling to detect collisions and generate DHCP reservations with unique hostnames. | new |  |
| 2026-07-23 | 2 | Fix stale endsession skill (missing end-session script) | skills/endsession instructs 'npm run session:end' via scripts/end-session.ts, but neither package.json nor scripts/ exists in this repo. Port the script or rewrite the skill to match the manual AGENTS.md shutdown procedure. | new |  |
