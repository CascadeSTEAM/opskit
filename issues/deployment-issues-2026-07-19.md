---
status: open
created: "2026-07-19"
priority: medium
tags: [bugs, remediation]
---

# Issues Found During BMS Semaphore + Netbox Deployment (2026-07-19)

## 1. open-ticket.sh — HELPDESK_TENANT Python NameError
- **File:** `bin/open-ticket.sh:98`
- **Symptom:** `NameError: name 'HELPDESK_TENANT' is not defined`
- **Cause:** Python heredoc uses both bash `${HELPDESK_TENANT}` and Python `HELPDESK_TENANT.upper()` in same line; bash interpolation replaces `$HELPDESK_TENANT` but the f-string's `HELPDESK_TENANT` is not a Python variable
- **Fix needed:** Pass the bash value into Python properly

## 2. netbox role — empty stubs
- **File:** `ansible/roles/netbox/tasks/main.yml`, `ansible/roles/netbox/defaults/main.yml`
- **Symptom:** Both files contained only `---` (empty YAML)
- **Status:** Fixed — filled out with Docker Compose-based tasks, defaults, and handlers

## 3. semaphore config template — bare expression
- **File:** `ansible/roles/semaphore/templates/config.json.j2`
- **Symptom:** Contained only `{{ semaphore_config | to_nice_json }}` with no schema
- **Status:** Fixed — replaced with full Semaphore config.json structure

## 4. pve3 — missing device YAML
- **File:** `environments/bms/datasets/devices/` (no pve3.yml)
- **Symptom:** pve3 (10.99.0.6) exists in inventory but has no device YAML
- **Risk:** Unknown resources, unknown children, blind spot in topology
- **Fix needed:** Run `opskit scan --discover-only` against pve3

## 5. Port 8080 conflict with quartz-preview
- **Symptom:** Netbox failed to bind port 8080 (already in use by `quartz-preview` container)
- **Status:** Fixed — Netbox moved to port 8081

## 6. Duplicate environment directories: bms/ vs BMS/
- **Symptom:** Both `environments/bms/` and `environments/BMS/` exist with differing content
- **Risk:** Operators may target wrong directory. `bms/` (lowercase) is more complete.
- **Fix needed:** Sync or remove `BMS/` (capitalized)

## 7. Netbox requires separate Postgres database
- **Symptom:** `django.db.utils.OperationalError: FATAL: database "netbox" does not exist`
- **Status:** Fixed — added `postgres-init.sh` mounted to `/docker-entrypoint-initdb.d/`
