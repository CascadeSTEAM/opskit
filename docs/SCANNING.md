# Scanning

How `opskit scan` discovers, enriches, and links devices on your network.

## Quick reference

```bash
opskit scan                    # full pipeline
opskit scan --dry-run          # preview nmap commands
opskit scan --discover-only    # nmap only, list live hosts
opskit scan --enrich-only      # re-run enrichment on existing YAMLs
opskit scan --uplinks-only     # only resolve topology
opskit scan --skip-enrich      # skip dedup phase
opskit scan --skip-uplinks     # skip topology resolution
opskit scan --no-router        # skip router SSH for bridge/LLDP
opskit scan --timeout 600      # manual timeout override
opskit scan --fixture nmap.xml # process existing nmap XML (CI/test)
```

## How discovery works

1. Reads `subnets` from `environments/<env>/env.yml`
2. Runs `nmap -sn` on each subnet to find live hosts (ARP sweep)
3. Runs `nmap -sV` (TCP port scan) on live hosts
4. Parses nmap XML into structured host records

**Timeout auto-scaling** — larger subnets get proportionally more time:

| Subnet | IPs | Timeout |
|--------|-----|---------|
| /24 | 256 | 60s |
| /23 | 512 | 60s |
| /16 | 65K | ~380s |
| /12 | 1M | 3600s (capped) |

**Nmap arguments**: `-sn --max-rtt-timeout 300ms --max-retries 1`
These speed up large scans by reducing retries on dead IPs.

## How device YAMLs are written

`dataset_writer.py` maps each discovered host to a YAML file in `datasets/devices/`:

```
environments/<env>/datasets/
  devices/
    my-router.yml
    printer-office.yml
    laptop-john.yml
  ipam.yml
  services.yml
  network.yml
```

For new devices: a minimal L1-maturity YAML is created with IP, MAC, vendor, and
a hostname derived from nmap data (DNS, mDNS, or a synthetic name).

For existing devices: only monitoring fields (`last_seen`, `last_scan`,
`reachable`, `ping_response`) are updated. Manual data (description, credentials,
dependencies) is **never overwritten** by nmap.

## How enrichment works

`enricher.py` runs 9 phases on the device directory:

1. **Deduplication** — Devices with the same MAC are merged. Scoring:
   curated name > maturity level > reference count > access config > recency.
   Different MACs are **never** merged, even with the same IP.

2. **Reference remapping** — After a merge, all other devices that referenced
   the discarded name are updated to point at the kept name.

3. **Type/interface normalization** — `lxc_container` → `lxc`, clean compound
   MAC addresses, deduplicate interface lists.

4. **Parent-child** — Resolves `hosted_on` from explicit field (trusted) or
   prose description (inferred, guarded: only VMs/containers gain parents).

5. **Infrastructure linking** — DNS servers and gateways detected in device
   configs get `depends_on` links.

6. **Docker Swarm peers** — Nodes referencing the same swarm get peer links.

7. **BMC pairing** — Management controllers paired to physical hosts by subnet.

8. **Stale cleanup** — References to deleted device files are removed.

9. **Idempotent write** — Only files that actually changed are rewritten.

## How topology resolution works

`device_registry.py` builds a MAC-keyed canonical registry and resolves uplinks:

1. Every device YAML is loaded and registered by MAC address
2. If the router is reachable via SSH, the bridge host table and LLDP neighbor
   table are pulled (from `topology.router_ssh` in env.yml)
3. Each switch port is mapped to its gateway device (highest infrastructure
   priority on that port: router > switch > hypervisor > AP)
4. Each device's `uplink_host` is resolved — containers get their Proxmox host,
   devices on switch ports get the port's gateway device
5. Uplink chains are walked to root (the router). Cycles, broken references,
   and orphan chains are flagged as validation errors
6. Resolved `uplink_host` values are written back to the device YAMLs

Without router access (or with `--no-router`), the registry still validates
existing chains but cannot resolve new topology from bridge/LLDP data.

## Merging manual data

The scanner never overwrites manually-set fields. Source priority for identity
resolution:

```
manual (5) > proxmox (4) > technitium (3) > lldp (2) > bridge (1) > nmap (0)
```

A device manually documented in YAML will always win over nmap results.

## Performance

- /24 subnet: ~30-60 seconds
- /16 subnet: ~5-10 minutes
- /12 subnet: may take hours — consider splitting into smaller subnets

Use `--dry-run` first to preview, and `--timeout` to extend for large networks.
