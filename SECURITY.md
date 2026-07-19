# Security

## Reporting

Report security issues to the maintainer directly. Do not file public issues for
credential exposures or vulnerabilities.

## Hard rules (shipped as policy atoms)

1. **No plaintext credentials.** Every secret is fetched at runtime from
   Vaultwarden (or equivalent vault). Never at rest in this repo.
2. **Least privilege.** Every service account, API token, and tool user has the
   minimum permissions needed.
3. **Runtime vault fetch only.** Credentials are resolved at execution time,
   never baked into images, configs, or committed files.

## Secret scanning

gitleaks runs in CI on every push. The `.githooks/pre-commit` hook also scans
for common credential patterns. Both are enforced — commits that fail scanning
are rejected.

## Environment isolation

Real environment data lives in gitignored paths (`environments/*/` except
`environments/example/`). See `.gitignore` for the full isolation design.
