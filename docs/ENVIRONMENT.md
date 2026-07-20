# Environment contract (`env.yml`)

Every opskit environment is declared by a single `environments/<env>/env.yml` file.
All tooling reads from it — nothing is hardcoded.

## Schema

The formal schema is at `schemas/env.schema.json`. Validate:

```bash
python3 -c "
import jsonschema, yaml
schema = yaml.safe_load(open('schemas/env.schema.json'))
data = yaml.safe_load(open('environments/example/env.yml'))
jsonschema.validate(data, schema)
print('valid')
"
```

## Required fields

| Field | Type | Example | Notes |
|-------|------|---------|-------|
| `name` | string | `homelab` | Slug: lowercase, hyphens only |
| `display_name` | string | `Home Lab` | Human-readable |
| `ticket.prefix` | string | `HL` | 2-4 uppercase letters for commit messages |
| `domains.primary` | string | `homelab.local` | Primary DNS domain |
| `subnets` | object | `{mgmt: 10.0.0.0/24}` | Named CIDRs, key=role |
| `connectivity.probes` | array | `[{host: 10.0.0.1}]` | Reachability checks |
| `vault.backend` | string | `vaultwarden` | `vaultwarden`, `openbao`, or `none` |
| `source_of_truth.type` | string | `git-yaml` | `netbox` or `git-yaml` |
| `execution.type` | string | `cli` | `cli` or `semaphore` |

## Optional fields

| Field | Notes |
|-------|-------|
| `ticket.helpdesk` | `erpnext`, `github_issues`, or `none` |
| `ticket.helpdesk_endpoint` | ERPNext API URL (if `helpdesk: erpnext`) |
| `ticket.helpdesk_tenant` | ERPNext tenant name |
| `connectivity.vpn_bringup` | Command to bring up VPN (for remote envs) |
| `vault.collection` | Vaultwarden collection or OpenBao mount path |
| `vault.cross_env_credentials` | Allowlist for cross-environment credential access |
| `source_of_truth.netbox_url` | NetBox API URL (required if `type: netbox`) |
| `source_of_truth.netbox_token_ref` | Vault item with NetBox token (required if `type: netbox`) |
| `execution.semaphore_url` | Semaphore UI URL (required if `type: semaphore`) |
| `execution.semaphore_project` | Semaphore project name |
| `topology.router` | Core router hostname for uplink chain validation |
| `topology.router_ssh` | SSH alias for bridge/LLDP topology discovery |
| `referenced_devices` | Devices in other envs that this env depends on |
| `ansible.ssh_user` | Default Ansible SSH user (default: `root`) |
| `ansible.ssh_key_path` | SSH identity file path |
| `ansible.ssh_jump` | SSH jump host alias |

## Complete example

```yaml
name: homelab
display_name: Home Lab

ticket:
  prefix: HL
  helpdesk: none

domains:
  primary: homelab.local

subnets:
  mgmt: 10.0.0.0/24
  servers: 10.0.10.0/24
  iot: 10.0.20.0/24

connectivity:
  probes:
    - host: 10.0.0.1
      port: 22
      description: router SSH
    - host: 10.0.10.10
      description: DNS server
  vpn_bringup: sudo wg-quick up homelab

vault:
  backend: vaultwarden
  collection: homelab

source_of_truth:
  type: git-yaml

execution:
  type: cli

topology:
  router: ubiquiti-gateway
  router_ssh: gateway

ansible:
  ssh_user: admin
  ssh_jump: gateway

referenced_devices: []
cross_env_credentials: []
```

## How tools read env.yml

| Tool | Reads |
|------|-------|
| `switch-env.sh` | `name`, `display_name`, `connectivity.probes` |
| `check-connectivity.sh` | `connectivity.probes` |
| `ap.sh` | `name` (for inventory path) |
| `open-ticket.sh` | `ticket.prefix`, `ticket.helpdesk_endpoint`, `ticket.helpdesk_tenant` |
| `scan.py` / `opskit scan` | `subnets`, `topology.*` |
| `commit-msg` hook | `ticket.prefix` |
