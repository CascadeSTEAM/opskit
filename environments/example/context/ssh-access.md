# SSH Access Map — EXAMPLE (fictional, documentation-range values)

<!-- Generated file. Real environments render this into
     environments/<env>/context/ (gitignored) from datasets/ and ~/.ssh/config.
     Credentials are referenced by vault entry name — never inline.
     See docs/local-agent-context.md. -->

## Site A — Hypervisors

| Alias | IP | User | Key | Notes |
|-------|-----|------|-----|-------|
| ex-hv-01 | 198.51.100.5 | `root` | default | Web UI: https://198.51.100.5:8006 |
| ex-hv-02 | 198.51.100.7 | `root` | default | |

## Site A — Workstations

| Alias | IP | User | Key | Notes |
|-------|-----|------|-----|-------|
| ex-lab-01 | 198.51.100.211 | `labadmin` | `~/.ssh/example-workstations` | passwordless |
| ex-lab-02 | 198.51.100.212 | `labadmin` | `~/.ssh/example-workstations` | **unreachable** — verify first |

## Site A — Network & Services

| Alias | IP | Access | Notes |
|-------|-----|--------|-------|
| ex-gw-01 | 198.51.100.1 | SSH key | RouterOS; Web UI: https://198.51.100.1 |
| ex-dns-01 | 198.51.100.4 | `root` | Technitium; Web UI: http://198.51.100.4:5380 |
| ex-mon-01 | 198.51.100.100 | `root` | Grafana on :3000; password: vault `mon-grafana` |
