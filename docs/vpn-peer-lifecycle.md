# VPN peer lifecycle

How VPN access is granted, delivered, audited, and revoked. Before this existed,
adding a user was undocumented clicking in a web UI and removing one had no
defined path at all — which is how a configuration acquires live credentials
nobody can account for (issue #90).

The tools are `mcp/wireguard-mcp-server.py`, launched with
`bin/mcp-run.sh wireguard`. Everything below assumes the runtime is up and the
vault is unlocked (`export BW_SESSION=$(bw unlock --raw)` **before** starting it).

## The rule that shapes all of this

**A client config contains a private key. Whoever holds it *is* that VPN
account.** So the config never crosses the tool boundary: there is deliberately
no `get_config` tool, and `create_peer` does not return the config it generated.
A tool result is transcript — logged, summarised, pasted into tickets — so a
returned config would be a credential leak by construction.

Delivery has exactly one sanctioned route: `wireguard_deliver_config`, which
puts it in a Bitwarden Send with a finite access count and a deletion date, and
returns only the URL.

## Granting access

1. **Open a ticket.** Every infra change needs one (`bin/open-ticket.sh`); the
   tool records the active ticket in the inventory row automatically.

2. **Create the peer.** Name it `owner_device` — a future auditor needs to know
   both who and which machine:

   ```
   wireguard_create_peer(env="<env>", name="dana_laptop",
                         owner_note="Dana, replacement laptop")
   ```

   It allocates the next free address and **mirrors the reference peer's scope**,
   so a new user gets the same access the team already has rather than a
   hand-typed guess. If no scope can be determined it refuses — a full tunnel is
   a privilege decision, never a fallback. An explicit `0.0.0.0/0` comes back
   flagged `full_tunnel: true`.

3. **Store the credential in the vault** under the name the tool reports
   (`<ENV> WireGuard peer - <name>`). Deriving the name means a later session can
   find it without searching free text and guessing which of several
   similarly-named items is authoritative.

4. **Deliver it:**

   ```
   wireguard_deliver_config(env="<env>", name="dana_laptop",
                            max_access_count=1, delete_in_days=2)
   ```

   Send the URL over any channel. If you set `send_password`, send that over a
   *different* one. A QR scanned in person is better still — nothing transits.

5. **Verify:** `wireguard_verify(env="<env>")` should report `clean: true`.

## Revoking access

```
wireguard_revoke_peer(env="<env>", name="dana_laptop", confirm=True)
```

WireGuard has no sessions to expire — removing the peer makes its private key
inert immediately. It is **not restorable**: the key lives server-side, so
restoring access means creating and redelivering a new peer. `confirm=True` is
required, and the tool verifies the peer is actually gone rather than trusting
the delete response.

Then: delete the vault item, and leave the inventory row in place marked
revoked — `verify` will report it as `stale`, which is the correct record of
"access existed and was removed". Deleting the row erases the history.

## Auditing

Two different questions:

- **`wireguard_audit`** — does any peer *look* wrong? Flags full-tunnel scope,
  zero cumulative transfer, and names that carry no owner.
- **`wireguard_verify`** — does the record match reality? Reports `untracked`
  (live but unrecorded), `stale` (recorded but gone), and `mismatched` (address
  or scope differs).

`untracked` is the finding that matters: live access with no recorded owner
cannot be audited or safely revoked. Resolve one by identifying the holder and
adding an inventory row, or by revoking it — never by deleting the row.

### Two traps worth knowing

**`latest_handshake` is weak evidence.** It resets when the interface restarts,
so "No Handshake" means "not since the last restart", never "never used". Acting
on it alone will cut off a live user.

**Zero cumulative transfer is stronger but still ambiguous** — a peer issued
minutes ago also has zero. Check the issue date in the vault item before
concluding a peer is abandoned.

## Where things live

| What | Where | Why |
|---|---|---|
| Peer inventory | `environments/<env>/datasets/wireguard-peers.json` | names people and devices — the gitignored private layer, never the public repo |
| Peer credentials | vault, `<ENV> WireGuard peer - <name>` | derived name, so it is findable |
| Dashboard admin credential | vault, per environment | includes the **TOTP seed** — see below |
| Endpoint config | `mcp/tenants-wireguard.local.json` | gitignored; hosts are topology |

## Authentication gotcha

The dashboard account has **TOTP enabled**, and the vault item holds the seed
alongside the password. A password-only login fails with *"your username,
password or OTP is incorrect"* — which reads as a wrong password and sends you
hunting for a rotated credential. That misdiagnosis nearly led to a credential
reset on a live container.

The launcher supplies the seed via `bin/mcp-run.sh` (`"field": "totp"` in the
vault map) and the server derives a fresh code per request. If the seed is
missing, the tools say so explicitly rather than blaming the password.
