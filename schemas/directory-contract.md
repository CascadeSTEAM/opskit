# opskit Directory Contract

Every opskit environment lives under `environments/<env>/`. This document defines
the directory structure, what each path means, and what tooling may expect.

## Root layout

```
environments/<env>/
├── env.yml              # Environment declaration (required)
├── ansible/
│   ├── inventory.yml    # Ansible inventory (required)
│   ├── group_vars/      # Group variables (optional)
│   └── host_vars/       # Per-host variables — generated from SoT (optional)
├── datasets/            # CMDB exports from SoT — generated, not canonical (required if SoT != none)
│   ├── devices/         # Device YAMLs
│   ├── ipam.yml         # IP address management
│   ├── network.yml      # Subnets, gateways, DHCP scopes
│   ├── services.yml     # Service registry
│   └── vlans.yml        # VLAN definitions
├── base-view.yml        # Device-note generation config (optional)
└── playbooks/           # Environment-specific playbooks (optional)
```

## Rules

1. **`env.yml` is the entry point.** Every component that needs to know about an
   environment reads `env.yml`. There is no other source of environment identity.
2. **`datasets/` is generated.** When `source_of_truth.type` is `netbox`, datasets
   are exports from the NetBox API. When `type` is `git-yaml`, datasets are
   canonical and hand-edited. Mixing is not supported.
3. **`ansible/inventory.yml` is the Ansible inventory.** It is the single inventory
   file for this environment. Playbooks are scoped to one environment via
   `-i environments/$ACTIVE_ENV/ansible/inventory.yml`.
4. **`base-view.yml` is optional.** It configures device-note generation for Obsidian
   or other documentation systems. The schema is defined in `schemas/base-view.schema.json`.
5. **`playbooks/` are site-specific.** Generic playbooks live in opskit's
   `ansible/playbooks/`. Environment playbooks are one-offs that don't generalize.

## Environment enumeration

Tooling discovers environments by globbing `environments/*/env.yml`. Adding an
environment = creating a directory with an `env.yml`. No hardcoded lists.

## Validation

The schema validation suite enforces:
- `env.yml` conforms to `schemas/env.schema.json`
- Directory tree matches this contract (required paths exist, no unexpected paths)
- Device YAMLs conform to `schemas/device.schema.json`
- Cross-environment references resolve
