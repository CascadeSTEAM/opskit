# Critical Inventory Facts — EXAMPLE (fictional, documentation-range values)

<!-- Generated file. Real environments render this into
     environments/<env>/context/ (gitignored) from datasets/.
     See docs/local-agent-context.md. -->

## Network Boundary

- **Example Site A:** `198.51.100.0/24` — `sitea.example.local` — Main campus
- **Example Site B:** `192.0.2.0/24` — `siteb.example.local` — Home/office
- Physically separate sites. Site A reached from Site B via WireGuard.

## Hypervisors

| Hostname | IP | Hardware | BMC | BMC IP | Notes |
|----------|-----|----------|-----|--------|-------|
| ex-hv-01 | 198.51.100.5 | Dell R730 | iDRAC | 198.51.100.205 | Primary, hosts most LXCs |
| ex-hv-02 | 198.51.100.7 | HP DL360p | iLO | 198.51.100.207 | General workload |
| ex-hv-03 | 192.0.2.10 | Custom, GPU | — | — | ONLY Site B hypervisor |

## CRITICAL: Ambiguous Names

| Context | IP | What it IS |
|---------|-----|------------|
| Site A `ex-hv-02` | 198.51.100.7 | Proxmox hypervisor |
| Site B `ex-hv-02` | 192.0.2.142 | Desktop + LLM host — NOT a hypervisor |

Two different machines in two different networks. Do not conflate them.
