# Rule: No Secrets in Output

Never include plaintext passwords, API tokens, SSH keys, or credentials in any file, commit message, or chat output.

- Use vault references: `vault: <item-name>`
- Use placeholders: `<VAULT:item-name>`
- Never hardcode credentials in scripts or configs
- Pre-commit hook rejects commits with potential secrets
