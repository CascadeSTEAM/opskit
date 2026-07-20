# Architecture

opskit is a convention-driven toolkit. It does not own data — your environments own the data. opskit provides the tools, schemas, and pipelines to work with that data.

## Data flow

```
environments/<env>/env.yml          ──── declared by you
         │
         ├── bin/switch-env.sh       reads ACTIVE_ENV → sets .env
         ├── bin/check-connectivity  reads connectivity.probes → reachability test
         ├── bin/ap.sh               reads ansible.inventory → playbook execution
         ├── bin/open-ticket.sh      reads ticket.prefix → helpdesk integration
         │
         └── bin/scan.py / bin/opskit scan
              reads subnets → nmap → YAML → enrich → resolve uplinks
              │
              ├── datasets/devices/*.yml  (created/updated by scan)
              ├── datasets/ipam.yml       (maintained by scan)
              └── datasets/services.yml   (maintained by scan)
```

## Scan pipeline (4 phases)

### Phase 1 — Discover
`nmap_runner.discover()` runs `nmap -sn` on each subnet from env.yml.
Auto-scales timeout by subnet size (/24 → 60s, /16 → 380s).
`parser.parse_discovery()` extracts IP, MAC, vendor, hostname from XML.

If hosts are found: `nmap_runner.portscan()` runs a TCP scan on live hosts.
`parser.parse_portscan()` merges port/OS data into host records.

### Phase 2 — Write
`dataset_writer.write_devices()` creates/updates YAML files:
- New devices: created at L1 maturity from nmap data
- Existing devices: monitoring/OS fields updated, manual fields preserved
- `ipam.yml` and `services.yml` updated with discovered data

### Phase 3 — Enrich
`enricher.enrich_dataset()` runs a 9-phase post-scan pipeline:
1. Dedup by MAC (strong) + IP (weak, different MACs never merge)
2. Reference remapping after merges
3. Type/interface normalization
4. Parent-child from `hosted_on` field or description inference
5. Infrastructure linking (DNS servers, gateways → `depends_on`)
6. Docker Swarm peer linking
7. BMC → physical host pairing
8. Stale reference cleanup
9. Idempotent write (only writes files that changed)

### Phase 4 — Resolve uplinks
`device_registry.py` resolves network topology:
1. Load all device YAMLs into a MAC-keyed registry
2. If router reachable: pull bridge host table + LLDP neighbors via SSH
3. Map each device's switch port → gateway device (router, switch, hypervisor)
4. LXC/QEMU containers get `uplink_host = proxmox_host`
5. Walk uplink chains to root (router), detect cycles, broken refs, orphans
6. Write `uplink_host` back to YAML files

## Component map

```
bin/
  opskit                     Unified CLI (argparse subcommands)
  scan.py                    Standalone scanner entry point (CI-compatible)
  switch-env.sh              Set ACTIVE_ENV + probe connectivity
  check-connectivity.sh      Probe all connectivity targets
  ap.sh                      Ansible playbook runner with --limit
  open-ticket.sh             Helpdesk ticket management

  scanner_lib/
    nmap_runner.py           nmap subprocess wrapper
    parser.py                XML → structured host dicts
    dataset_writer.py        Host dicts → YAML device files
    enricher.py              9-phase post-scan enrichment
    scaffold.py              Dataset directory scaffolding
  device_registry.py         MAC-keyed identity resolution + uplink validation
  enrich-uplinks.py          SSH bridge/LLDP topology (standalone)
  generate-network-docs.py   Ansible facts → markdown docs
  semaphore-sync.py          Catalogue → Semaphore API sync
  automation-ladder.py       Manual process tracking + escalation
  lifecycle-processor.py     Proposal → plan → completed transitions

ansible/
  roles/                     13 Ansible roles
  playbooks/                 13 Ansible playbooks
  ansible.cfg                Inventory path: environments/<env>/ansible/

mcp/
  erpnext-mcp-server.py      Frappe Helpdesk MCP server
  technitium-mcp-server.py   Technitium DNS MCP server
  semaphore-mcp-adapter.py   Semaphore UI MCP integration

schemas/
  env.schema.json            JSON Schema for env.yml
  device.schema.json         JSON Schema for device.yml
  directory-contract.md      Required directory layout
  sot-adapter-interface.md   Source-of-truth adapter spec
  inventory-conventions.md   Device naming + YAML conventions

.opencode/
  rules/                     9 AI behavioral rules
  skills/                    9 AI skills (domain knowledge)
```

## Conventions

- **Data-driven everything** — no hardcoded hostnames, subnets, or env names
- **Environments are self-contained** — `environments/<env>/` has env.yml + datasets + ansible inventory + playbooks
- **Git isolation** — `environments/*/` (except `example/`) is gitignored
- **Nmap is discovery, not identity** — MAC address is ground truth; nmap results merge into existing YAMLs, never overwrite manual data
- **No plaintext credentials** — vault references only; pre-commit hook enforces
