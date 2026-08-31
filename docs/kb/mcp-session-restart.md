# opencode MCP Servers Show "Connection closed" After a Machine Crash

## The Problem

The laptop crashes (power loss, forced reboot) while an opencode session is
active. After reloading the session and generating a fresh vault session token,
then restarting opencode, most MCP servers fail to connect:

```
erpnext      MCP error -32000: Connection closed
proxmox      MCP error -32000: Connection closed
technitium   MCP error -32000: Connection closed
wireguard    MCP error -32000: Connection closed
collab       Connected                    <-- green, only this one
```

The tell is the pattern: **only the server that needs no secrets connects.**

## The Fix

Close the **entire shell** (the terminal/process that launched opencode), not
just the opencode session, then start a fresh one:

1. Quit the terminal window or process tree that runs opencode.
2. Unlock the vault and export a fresh session token:
   ```
   export BW_SESSION=$(bw unlock --raw)
   ```
3. Relaunch opencode.

All MCP servers that depend on vault secrets now connect — you no longer need
to restart once just for the token.

## Why This Happens

The MCP servers are launched by the opencode **server process**, which was
started *before* the crash with a session token that has since auto-locked (or
died with the crash). `bin/mcp-run.sh` resolves each server's secrets from the
vault at launch; with no usable session reachable from the opencode process,
the `bw get item` call fails and the server process dies immediately.

The servers fall into two groups:

- `collab` declares **no secrets** in `mcp/vault-map.local.json`, so it starts
  with or without a vault session — which is why it is the one that stays
  green and makes the failure look selective.
- `erpnext`, `proxmox`, `technitium`, and `wireguard` each declare secrets, so
  they need a live session and die the moment one is missing.

Resetting the token and restarting only the opencode *session* leaves the old
server process (with the stale/no session) intact, so the failure persists.
Closing the whole shell reaps those stale processes and starts fresh ones
under the new session environment.

> The durable fix (making crash recovery not need a full shell close) is
> tracked in opskit issue #292.

## If It Keeps Happening / Prevention

- Confirm the diagnosis before touching anything:
  `bin/mcp-run.sh <server> --check` — it reports whether `BW_SESSION` is
  unlocked and every maps to the vault. Only `collab` needs none.
- A session token is a live key; if a "Connection closed" recurs later, the
  token may have simply auto-locked — re-export `BW_SESSION` in the shell that
  owns opencode, then restart opencode.
- After a crash, close the shell (step 1) before assuming the second restart
  failed — a fresh shell carries the new `BW_SESSION` into the MCP launches.

## Quick Reference

| Step | Command | Expected / Note |
|------|---------|-----------------|
| Diagnose | `bin/mcp-run.sh <server> --check` | `BW_SESSION ... unlocked`; launch path OK |
| Fix | Close the whole shell, then `export BW_SESSION=$(bw unlock --raw)` | New shell carries the fresh token |
| Verify | Relaunch opencode | 5/5 MCP servers connect |
