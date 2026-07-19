# Contributing

opskit follows the [DocWright lifecycle](https://github.com/growlf/docwright):
issues → proposals → plans → docs.

## Development setup

```bash
./setup-opskit.sh
cp environments/example/ environments/my-test/
# Edit environments/my-test/env.yml
source bin/switch-env.sh my-test
```

## Conventions

- **Ansible as the interface** — every system-state change is a playbook or role
- **Data-driven** — env enumeration, ticket gating, and tool configuration all
  come from `env.yml`, never hardcoded
- **Red Hat CoP GPA** — all Ansible content follows the [Automation Good
  Practices](https://redhat-cop.github.io/automation-good-practices/)
- **MIT license** — all contributions under the same license

## Testing

```bash
pytest tests/
ansible-lint ansible/
shellcheck bin/*.sh
```
