# Credential lifecycle — issue, track, revoke

Creating a scoped credential is a recurring operation, and it was being done
entirely by hand. There will be many: different services, different groups,
different privilege scopes. This is the codified path (opskit #103), and it
follows the precedent #90 set for VPN peers — the two are one doctrine over
two credential classes.

## The direction of truth

This is the decision the issue asked for, stated once so two copies never
appear with no defined direction:

| Thing | Owner |
|---|---|
| The secret **value** | **The vault.** Nothing else stores it, ever. |
| The **metadata** — scope, role, purpose, ticket, revocation | **The inventory** (`bin/token-inventory.py`) |
| The **grant** on the target system | The target system, created by the playbook |

**Ansible reads from the vault at run time; it does not keep its own copy.**
`ansible-vault`-encrypted `host_vars` are *not* a second source of truth for
these credentials, and this repo's launcher convention already does the same
thing for MCP servers: `bin/mcp-run.sh` resolves secrets from the vault at
launch, so nothing is written to disk.

Rejected: syncing the vault into `ansible-vault`. A sync has a direction that
is easy to state and easy to get backwards, and the failure is silent — the
copy keeps working while diverging. The repo has already been bitten by
exactly this class of problem (copies that could not tell they were stale) more
than once.

Existing `ansible-vault` files stay where they are; the rule is about
credentials issued from here onwards.

## Issue

```bash
ansible-playbook -i environments/$ACTIVE_ENV/ansible/inventory.yml \
  ansible/playbooks/provision-proxmox-api-token.yml \
  -e target_host=<node> -e token_user=<name> -e token_name=<id> \
  -e token_path=/vms/100 -e token_role=PVEAuditor
```

The playbook creates the account (no password — token auth only), creates the
token with `privsep=1`, and grants the role at the scoped path.

**Two things it encodes that are easy to get wrong by hand:**

1. **The privsep intersection.** With `privsep=1` the effective rights are the
   intersection of the token ACL and the user ACL. Granted on the token only,
   reads succeed but listings return an **empty array rather than an error** —
   indistinguishable from "there is nothing here". So the role is granted to
   both, and the play fails if it cannot read back both grants.

2. **Narrow scope structurally, not from memory.** `token_path` has no default,
   and a grant at `/` is refused unless `allow_root_grant=true` is passed
   explicitly.

The token value is displayed **exactly once**. Store it in the vault
immediately, under the name the play prints.

## Track

```bash
bin/token-inventory.py add --service proxmox --identity 'svc@pve!mcp' \
    --scope /vms --role PVEAuditor --purpose "MCP launcher"
bin/token-inventory.py list
```

The vault holds the secret; it does not answer *which tokens exist, what can
each reach, which service uses it, which ticket authorised it*. Without those,
a credential is unattributable the moment the session ends.

The inventory stores **metadata only** — it rejects anything token-value-shaped
— and lives in the gitignored environment layer, since it names services and
scopes. The vault item name is **derived**, not invented per session, so a
token is findable later.

## Revoke

```bash
bin/token-inventory.py revoke --identity 'svc@pve!mcp' --reason "rotated"
```

Revocation is as easy as issue, deliberately: a grant with no matching removal
is how stale credentials accumulate.

The entry is **marked revoked, not deleted**. "This token was revoked on
`<date>`, for `<reason>`, under `<ticket>`" is the fact an audit needs, and a
deleted row cannot state it. The command then prints the two remaining steps —
remove the grant on the server, delete the vault item.

## Adding another service

Same three parts: a playbook that provisions idempotently and refuses an
over-broad grant by default, an inventory entry, and a documented revocation.
`--service` is a free string, so the inventory already accepts new classes.
WireGuard peers are the second class today and are handled by the
`wireguard` MCP server under the same doctrine (#90).
