---
name: sync-inventory
description: Refresh device inventory by deduplicating YAML sources then syncing notes from YAML + live Technitium DHCP for the active environment. Run proactively when notes are stale (>7 days), before network changes, or after DHCP modifications.
mode: skill
triggers: sync inventory,refresh inventory,update device list,inventory is stale,check device inventory,devices out of date,update assets
---

# Sync Device Inventory

Run without asking permission. Report what changed. Keep it brief.

**Full pipeline**: deduplicate YAML sources → sync notes from YAML + DHCP. Always run both layers.

## Auto-invoke when

- Device notes `last_updated` is >7 days ago
- About to reference device IPs/MACs for a network change
- Just added/removed a DHCP reservation or made scope changes
- A device IP in the notes doesn't match what Technitium reports live

## Steps

### 0. Track usage

`python3 scripts/automation-ladder.py tick --skill sync-inventory` — if `"offer_upgrade": true`, offer codification per Development Principles; permanent "no" → `automation-ladder.py mute --skill sync-inventory`.

### 1. Read ACTIVE_ENV

```bash
grep "^ACTIVE_ENV=" .env | cut -d= -f2
```

### 2. Check staleness

```bash
grep -h "^last_updated:" docs/reference/${ACTIVE_ENV}-devices/*.md 2>/dev/null \
  | sort | head -1
```

If the oldest `last_updated` is ≤7 days ago and no DHCP changes were just made, report "inventory is current" and stop.

### 3. Enrich YAML layer first

Run the enricher to deduplicate devices (same MAC/IP → merge) before syncing notes:

```bash
python3 scripts/scanner/scan.py --enrich --dataset ${ACTIVE_ENV} 2>&1
```

This prevents duplicate notes from being created from stale YAML entries.

### 4. Diff first

```bash
python3 scripts/sync-device-inventory.py --env ${ACTIVE_ENV} --source all --mode diff 2>&1
```

### 5. Run update

```bash
python3 scripts/sync-device-inventory.py --env ${ACTIVE_ENV} --source all --mode update 2>&1
```

### 6. Generate inventory report

```bash
python3 scripts/generate-inventory-report.py --env ${ACTIVE_ENV}
```

For cross-owner reports (e.g. all Cascade STEAM devices across all envs):

```bash
python3 scripts/generate-inventory-report.py --owner cascadesteam
```

### 6b. Pricing report (cascadesteam only; reads YAML, no API calls)

```bash
if [ "${ACTIVE_ENV}" = "cascadesteam" ]; then
  python3 scripts/generate-inventory-report.py --owner cascadesteam \
    --pricing inventory/datasets/cascadesteam/hardware-pricing.yml \
    --output docs/reference/cascadesteam-device-inventory-pricing.md
fi
```

### 7. Commit if changed

If any notes were created or updated:

```bash
git add docs/reference/${ACTIVE_ENV}-devices/ docs/reference/${ACTIVE_ENV}-device-inventory.md inventory/datasets/${ACTIVE_ENV}/ \
  docs/reference/cascadesteam-device-inventory-pricing.md inventory/datasets/cascadesteam/hardware-pricing.yml
git commit -m "chore: sync ${ACTIVE_ENV} device inventory $(date +%Y-%m-%d)"
```

### 8. Report

One line: `Synced <env>: <N> updated, <N> discovered, <N> unchanged. Report: docs/reference/<env>-device-inventory.md`
