# wazuh_agent

Install the Wazuh agent on Debian/Ubuntu hosts, enroll it with the environment's
manager (auto-enrollment on 1515, events on 1514/tcp), and ship the telemetry that
matters on that host: syslog/auth/dpkg/kern, syscollector inventory, rootcheck, SCA,
FIM on system dirs, the Docker events wodle when a docker socket exists, and
Suricata's slim EVE stream when `/var/log/suricata/eve-wazuh.json` (or `eve.json`)
exists.

Environment-specific values live in `environments/<env>/ansible/group_vars/` —
never here. The role refuses to run while `wazuh_manager` is still the
documentation placeholder.

| Variable | Default | Meaning |
|---|---|---|
| `wazuh_manager` | `198.18.42.10` (placeholder) | manager address agents enroll with |
| `wazuh_agent_group` | `default` | manager-side agent group (use the env name) |
| `wazuh_agent_name` | `inventory_hostname` | keeps manager == inventory |
| `wazuh_agent_suricata` | auto | force on/off shipping Suricata EVE |
| `wazuh_agent_docker_listener` | `auto` | docker events wodle |
| `wazuh_agent_extra_localfiles` | `[]` | extra `{location, log_format}` entries |

Playbooks: `ansible/playbooks/deploy-wazuh-agent.yml` (hosts) and
`ansible/playbooks/deploy-wazuh-agent-groups.yml` (manager-side shared `agent.conf`
per group, rendered from `templates/agent.conf.j2`). Docs: `docs/wazuh-agents.md`.

## Phoenix-style extras (added 2026-09-09; used by ansible/playbooks/monitoring-phoenix.yml)
- `wazuh_agent_fim_directories` / `wazuh_agent_fim_ignores` — extra real-time FIM sets
- `wazuh_agent_sca_policies` (+ `wazuh_agent_sca_remote_commands`) — custom SCA YAML from the
  env layer, installed under `/var/ossec/etc/sca/` (not `etc/shared`, which the manager wipes)
- `wazuh_agent_firewalld_drop` — ships `files/firewalld-drop` (stateful AR protocol, rich
  rules, runtime-only) for hosts that enforce with firewalld
