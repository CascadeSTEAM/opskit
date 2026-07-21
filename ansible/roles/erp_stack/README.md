# erp_stack

Deploys or upgrades a Frappe/ERPNext Docker Compose stack (built by your own
image pipeline and published to a container registry) on a Docker host. One
role, any number of stacks — each deployment is a host (or host group) plus
group_vars.

Distilled from a prior production cutover playbook, keeping its two
load-bearing decisions:

- **Host bind mounts, never named volumes** — site/db/queue data lives under
  `{{ erp_stack_data_root }}` on the host, visible and backup-able, immune to
  the "data only exists in a container layer" failure mode.
- **Secrets via ansible-vault, never `bw` lookups or CLI args** — the MariaDB
  root password comes from vaulted group_vars and only ever lands in the
  root-owned, `0600` compose file.

## Phases (run one with `--tags <phase>`)

| Tag | What it does |
|-----|--------------|
| `preflight` | Required vars present, Docker up, image reachable (hints at GHCR auth if not) |
| `deploy` | Data dirs, rendered compose file, `pull`, `up -d`, wait for backend |
| `sites` | `bench new-site` for missing sites (only when `erp_stack_create_sites`) |
| `migrate` | `bench migrate` per site (default on — required after image upgrades) |
| `verify` | HTTP probe of every site through the frontend |

## Key variables (see `defaults/main.yml` for the full list)

| Variable | Default | Purpose |
|----------|---------|---------|
| `erp_stack_use_case` | `main` | Image variant → image `erp-<use_case>` |
| `erp_stack_image_tag` | `latest` | Image tag to run; bump this to upgrade |
| `erp_stack_name` | `<use_case>-erpnext` | Compose project + `/opt/<name>` data root |
| `erp_stack_http_port` | `8080` | Host port the nginx frontend publishes |
| `erp_stack_sites` | `[]` | Bench sites — drives create/migrate/verify |
| `erp_stack_create_sites` | `false` | Create missing sites on first deploy |
| `erp_stack_site_apps` | `[]` | Apps installed into newly created sites |
| `erp_stack_db_root_password` | — | **Required, vaulted** |
| `erp_stack_admin_password` | — | **Required (vaulted) when creating sites** |

A single host can carry several stacks — give each an alias host in the
`erp_stacks` group with its own port and `erp_stack_name`, so their host_vars
never collide.

## Worked example: a new deployment

Inventory (`environments/<env>/ansible/inventory.yml`) — put the Docker host in
the `erp_stacks` group the playbook targets by default:

```yaml
erp_stacks:
  hosts:
    acme-erp:
      ansible_host: 198.51.100.26
      ansible_user: root
      ansible_ssh_common_args: '-o ProxyJump=root@jump.example.org:22'
```

`group_vars/acme_erp.yml` (or `host_vars`):

```yaml
erp_stack_use_case: acme
erp_stack_image_tag: v16.2.0
erp_stack_sites: [erp.acme.example]
erp_stack_create_sites: true          # first deploy only; flip off after
erp_stack_site_apps: [erpnext, builder, raven]
```

`group_vars/acme_erp_vault.yml` (encrypt with `ansible-vault encrypt`):

```yaml
erp_stack_db_root_password: "..."
erp_stack_admin_password: "..."
```

First deploy, then any later image upgrade:

```bash
ansible-playbook playbooks/deploy-erp-stack.yml -l acme-erp --ask-vault-pass
ansible-playbook playbooks/deploy-erp-stack.yml -l acme-erp \
  -e erp_stack_image_tag=v16.2.1 --ask-vault-pass
```

## Prerequisites

- Docker + Compose v2 on the target host
- Registry pull credentials on the host if the image packages are private
- TLS/reverse-proxying is out of scope; point the environment's reverse proxy
  at `<host>:{{ erp_stack_http_port }}` per site

## Not covered (by design)

- **Data migration from an existing stack** (named volumes → bind mounts,
  staged cutover on an alternate port): that is a one-time operation — keep
  your original cutover playbook for the pattern.
- **Backups**: schedule them against `{{ erp_stack_data_root }}` on the host.
