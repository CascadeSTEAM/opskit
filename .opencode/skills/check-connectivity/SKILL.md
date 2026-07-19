---
name: check-connectivity
description: Probe active environment network reachability before any network-sensitive operation
mode: skill
triggers: /check-connectivity
---

0. Track usage: `python3 bin/automation-ladder.py tick --skill check-connectivity` — if the output has `"offer_upgrade": true`, tell the operator and offer codification per Development Principles (Ansible playbook if the work changes system state, repo script if dev-workflow); a permanent "no" → `python3 bin/automation-ladder.py mute --skill check-connectivity`.

Run the connectivity probe for the active environment:

```bash
bash bin/check-connectivity.sh
```

- Exit 0 (on-site or VPN up): proceed normally.
- Exit 1 (unreachable): stop. Tell the operator which hosts are down and the exact command to restore connectivity. Do not attempt infrastructure operations until the probe passes.
