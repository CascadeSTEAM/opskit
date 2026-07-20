# Rule: No Plaintext Credentials — Ever

Applies to ALL files: Markdown docs, Ansible YAML, scripts, inventory, configs.
The pre-commit hook enforces this for both `.md` and `ansible/`/`inventory/` `.yml` files.

## What counts as a credential

Any value for keys named: `password`, `secret`, `api_key`, `api_token`, `auth_token`,
`db_root_password`, `admin_pass`, `_pass`, `_password`, `_token`, `_secret`.

## Required alternatives

| File type | Correct approach |
|-----------|-----------------|
| Ansible group_vars / vars | `ansible-vault encrypt_string 'value' --name 'var'` → `!vault |` block |
| Ansible task (runtime lookup) | `{{ lookup('pipe', 'bw get password <item-name>') }}` |
| Ansible playbook variable | `"{{ vault_<varname> }}"` sourced from an encrypted vars file |
| Markdown docs / plans | `Bitwarden: <item-name>` or `<BITWARDEN:item-name>` |
| Scripts | `bw get password <item-name>` or `bw get item <item-id>` |

## Examples

**Wrong — rejected by pre-commit hook:**
Any `password:`, `secret:`, `api_token:`, or `auth_token:` key set to a bare string
value in an Ansible YAML file. The hook pattern: `(password|secret|api_key|api_token|auth_token)\s*:\s*\S{6,}`

**Right — Ansible Vault encrypted string:**
```yaml
db_root_password: !vault |
  $ANSIBLE_VAULT;1.1;AES256
  ...
```

**Right — runtime Bitwarden lookup:**
```yaml
db_root_password: "{{ lookup('pipe', 'bw get password MariaDB Root: frappe-helpdesk') }}"
```

## Session note for AI agents

Before writing any credential value into a file, stop and ask:
> "Is this credential stored in Bitwarden? If yes, use `bw get item <name>` to retrieve it
> at runtime. Do NOT write the value into the file."

`bw get item <name>` is always available when `BW_SESSION` is set in the environment.
Check Bitwarden first — assume the credential already exists there.

## Known items in Bitwarden (CS environment)

| Item name | What it is |
|-----------|-----------|
| `Frappe Admin: support.cascadesteam.org` | Frappe/ERPNext site admin password |
| `Frappe Admin: helpdesk.<tenant-domain>` | tenant admin password |
| `MariaDB Root: frappe-helpdesk` | MariaDB root password on cs-helpdesk (CT106) |
| `Server: frappe-helpdesk` | SSH/server credentials for cs-helpdesk |
