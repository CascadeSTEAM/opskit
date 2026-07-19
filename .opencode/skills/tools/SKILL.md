---
name: tools
mode: skill
triggers: security,audit,lynis,rkhunter,fail2ban,firewalld,openscap,auditd,hardening
description: Security audit and hardening tools quick-reference — scan commands and key gotchas
---

# tools

> **All scans are read-only.** No changes, no installs. Load this skill before running any security audit tool.

0. Track usage: `python3 bin/automation-ladder.py tick --skill tools` — if the output has `"offer_upgrade": true`, offer codification per Development Principles; permanent "no" → `python3 bin/automation-ladder.py mute --skill tools`.

## Scan Commands

| Tool | Command | Check |
|------|---------|-------|
| lynis | `sudo lynis audit system --quick 2>/dev/null | tail -30` | `Hardening index` < 70 = room to improve |
| rkhunter | `sudo rkhunter --check --skip-keypress --quiet 2>/dev/null` | Check `/var/log/rkhunter.log` for `Warning` |
| fail2ban | `sudo fail2ban-client status sshd 2>/dev/null` | Shows banned IPs + jail status |
| firewalld | `sudo firewall-cmd --list-all 2>/dev/null` | Open services/ports |
| open ports | `ss -tlnp 2>/dev/null` | Listening TCP services |

## OpenSCAP (Quarterly)

```bash
sudo oscap xccdf eval --profile cis_level1_server \
  --results /tmp/oscap-results.xml --report /tmp/oscap-report.html \
  /usr/share/xml/scap/ssg/content/ssg-ubuntu2404-ds.xml
```

## auditd Key Commands

```bash
sudo systemctl enable --now auditd
sudo auditctl -l | head -10
sudo ausearch -k identity --start recent | tail -5
```

**WARNING:** Default log rotation caps quick on active systems. Set `max_log_file=50`, `num_logs=4`, `space_left_action=SYSLOG` in `/etc/audit/auditd.conf`.

## Install

Install via Ansible role or: `sudo apt install lynis rkhunter fail2ban firewalld` (Debian/Ubuntu).
