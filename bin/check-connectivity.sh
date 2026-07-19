#!/bin/bash
# opskit check-connectivity.sh — Probe network reachability for an environment
# Reads connectivity.probes from environments/<env>/env.yml
# Usage: bin/check-connectivity.sh [ENV]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
RED='\033[0;31m'; NC='\033[0m'

ENV="${1:-}"
if [ -z "$ENV" ]; then
    ENV=$(grep "^ACTIVE_ENV=" "$REPO_ROOT/.env" 2>/dev/null | cut -d= -f2 | tr -d '"')
fi
if [ -z "$ENV" ]; then
    echo -e "${RED}No environment specified and ACTIVE_ENV not set.${NC}" >&2
    exit 1
fi

ENV_YML="$REPO_ROOT/environments/$ENV/env.yml"
if [ ! -f "$ENV_YML" ]; then
    echo -e "${RED}Environment '$ENV' not found (no $ENV_YML).${NC}" >&2
    exit 1
fi

python3 - "$ENV_YML" "$ENV" <<'PYEOF'
import sys, yaml, subprocess, socket

yml = yaml.safe_load(open(sys.argv[1]))
conn = yml.get('connectivity', {})
probes = conn.get('probes', [])

if not probes:
    print(f"[connectivity] No probes configured for env '{sys.argv[2]}'.")
    sys.exit(0)

all_ok = True
for probe in probes:
    host = probe['host']
    desc = probe.get('description', host)
    port = probe.get('port', None)

    if port:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(3)
        result = sock.connect_ex((host, port))
        sock.close()
        ok = result == 0
    else:
        result = subprocess.run(['ping', '-c', '1', '-W', '2', host],
                                capture_output=True, timeout=5)
        ok = result.returncode == 0

    status = '\033[0;32mreachable\033[0m' if ok else '\033[0;31munreachable\033[0m'
    print(f"[connectivity] {desc} ({host}) — {status}")
    if not ok:
        all_ok = False

sys.exit(0 if all_ok else 1)
PYEOF
