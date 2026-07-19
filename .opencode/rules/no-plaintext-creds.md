# Rule: No Plaintext Credentials — Ever

Applies to ALL files: Markdown docs, Ansible YAML, scripts, inventory, configs.
The pre-commit hook enforces this.

## What counts as a credential

Any value for keys named: `password`, `secret`, `api_key`, `api_token`, `auth_token`,
`db_root_password`, `admin_pass`, `_pass`, `_password`, `_token`, `_secret`.

## Required alternatives

| File type | Correct approach |
|-----------|-----------------|
| Ansible group_vars / vars | `ansible-vault encrypt_string` → `!vault` block |
| Ansible task (runtime lookup) | `{{ lookup('env', 'VAR_NAME') }}` or vault lookup |
| Marksdown docs / plans | `vault: <item-name>` |
| Scripts | Read from environment at runtime, never hardcode |

## Session guidance

Before writing any credential value into a file, stop and ask:
> "Is this credential stored in vault? If yes, use a vault reference. Do NOT write the plaintext value."

Check vault first — assume the credential already exists there.
