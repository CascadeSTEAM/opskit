# Rule: No Secrets in Output

Never include plaintext passwords, API tokens, SSH keys, or credentials in any file, commit message, or chat output.

- Use Bitwarden references: `Bitwarden: <item-name>`
- Use placeholders: `<vaultwarden:item-name>`
- Never hardcode credentials in scripts or configs
- Pre-commit hook rejects commits with potential secrets
