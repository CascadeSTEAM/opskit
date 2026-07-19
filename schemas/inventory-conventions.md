# opskit Inventory & Variable Conventions

Adopted from the opskit umbrella plan §7 improvements 4-6.
Implements Red Hat CoP GPA §3.1.18 and §6.3-6.4.

## §7-4: Uniform group_vars contract

All Ansible group_vars use `env_*` prefix, scoped by group membership — no per-environment
variable name prefixes.

| Old (predecessor-ops-repo) | New (opskit) |
|-----------------------|---------------|
| `client1_domain`, `cs_domain`, `cascadesteam_domain` | `env_domain` (in each env's group_vars/all.yml) |
| `zabbix_server_ip` | `env_monitoring_server` |
| `cs_subnet`, `client1_subnet` | `env_subnet` |
| `zabbix_tier` | Host var, not group var (§7-5) |
| `ssh_user_cs`, `client1_ssh_user` | `env_ssh_user` (from env.yml ansible block) |

Implementation: `environments/<env>/ansible/group_vars/all.yml` defines `env_domain`,
`env_subnet`, `env_monitoring_server`, `env_ssh_user` — sourced from `env.yml` at
sync time (Phase 3 `semaphore-sync` generator). Playbooks reference `{{ env_domain }}`,
never `{{ cs_domain }}` or `{{ client1_domain }}`.

## §7-5: Inventory-group convention

Function/role-based subgroups — not tier-based. Tier is a **host property**, not a
group membership.

```
environments/<env>/ansible/inventory.yml:

all:
  children:
    routers:
      hosts:
        ex-gw-01:
    switches:
      hosts:
        ex-sw-01:
    servers:
      children:
        infrastructure:
          hosts:
            ex-srv-01:       # DNS, DHCP, monitoring
        application:
          hosts:
            ex-srv-02:       # Docker, web, API
    access_points:
      hosts:
        ex-ap-01:

Host vars (in host_vars/):
  ex-srv-01.yml:  tier: infrastructure, zabbix_tier: core
  ex-srv-02.yml:  tier: application, zabbix_tier: application
```

Tier becomes a host-level attribute for filtering: `hostvars[host].zabbix_tier` in
playbooks, `ansible_host_groups` in Zabbix auto-registration. This avoids
combinatorial group explosion (no `dns:primary`, `dns:secondary`, `monitoring:zabbix`,
`monitoring:netbox` groups).

Per GPA §3.1.18: "don't use host group names or at least make them a parameter" —
group names are never hardcoded in roles. Roles accept group names as parameters
with sensible defaults.

## §7-6: Data-driven environment enumeration

No hardcoded case statements anywhere. All tooling discovers environments by globbing
`environments/*/env.yml`.

| Component | Enumeration method |
|-----------|-------------------|
| `bin/switch-env.sh` | `ls environments/*/env.yml` → extract `name` field → validate |
| `bin/ap.sh` | Read `$ACTIVE_ENV` → `environments/$ACTIVE_ENV/ansible/inventory.yml` |
| `bin/open-ticket.sh` | Read `environments/$ACTIVE_ENV/env.yml` → ticket prefix + helpdesk config |
| `.githooks/pre-commit` | Same as open-ticket: read active env's env.yml for prefix |
| `bin/check-connectivity.sh` | Read `environments/$ACTIVE_ENV/env.yml` → connectivity.probes |
| `semaphore-sync` generator | Iterate all `environments/*/env.yml`, create Semaphore project per env |
| SoT adapters | Read `env.yml → source_of_truth.type + config` |

Adding an environment = `mkdir environments/<name>/` + `env.yml` + `ansible/inventory.yml`.
Zero tooling edits.
