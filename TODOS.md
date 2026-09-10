# Wazuh manager LXC on nexus — plan outline

## Goal
Move the Wazuh manager from phoenix (workstation, Docker single-node) to nexus (Proxmox node, LXC + Docker).

## Steps

1. **Create LXC on nexus**
   - Use `ansible/playbooks/provision-wazuh-manager-lxc.yml` (derived from `provision-runner-lxc.yml`)
   - Parameters:
     - `target_host=nexus`
     - `ct_id=<id>` (find a free ID on nexus)
     - `ct_ip=<address/prefix>` (allocate from nexus subnet)
     - `ct_gateway=<address>` (nexus gateway, usually .1)
     - `ssh_allow_source=<cidr>` (trusted LAN CIDR)
   - Sizing: 4 cores, 8GB RAM, 60GB disk (manager needs disk for indexes + logs)

2. **Deploy Wazuh manager inside LXC**
   - Use `ansible/roles/wazuh_manager_docker` role (already exists in worktree/monitoring-wazuh)
   - Install Docker Engine and Compose v2 (same as provision-runner-lxc.yml play 2)
   - Checkout `wazuh-docker` repo, render compose file + manager config
   - Generate indexer certificates
   - Start Wazuh stack

3. **Update environment configuration**
    - Change `wazuh_manager` in `environments/<env>/ansible/group_vars/all.yml` to new LXC IP
   - Change `wazuh_manager_host` from `phoenix` to `wazuh-manager` (LXC alias)
   - Keep `wazuh_manager_container: single-node-wazuh.manager-1` (still containerised)

4. **Re-deploy agents**
    - Run `bin/ap.sh deploy-wazuh-agent.yml -e target=cluster-llm,ai-node-211,ai-node-214,ai-node-215 --limit <env>`
   - Agents will reconnect to new manager address
   - `client.keys` is preserved — no re-enrollment needed

5. **Verify**
   - `agent_control -l` on manager lists every host as Active
    - Dashboard filter by `agent.group: <env>`

## Notes
- `wazuh_etc` volume (rules, decoders, `client.keys`) must be mounted/created on the new LXC
- Agent ids survive via `client.keys` — no re-enrollment needed
- Firewall: ensure 1514/tcp, 1515/tcp, 514/udp (if syslog listener) are open on the LXC
- Datacenter firewall on nexus must be enabled for container isolation