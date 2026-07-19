# opskit

A generic sysadmin toolset — Ansible catalogue, CMDB pipeline, MCP servers, and
documentation framework for running heterogeneous network environments.

**opskit is glue, conventions, and a curated catalogue.** The heavy lifting is
done by mature FOSS projects: [Semaphore UI](https://semaphoreui.com) for
execution, [NetBox](https://netbox.dev) for IPAM/DCIM, [Zabbix](https://zabbix.com)
for monitoring, [Vaultwarden](https://github.com/dani-garcia/vaultwarden) for
secrets, and [DocWright](https://github.com/growlf/docwright) for governance.

## Quick start

```bash
curl -fsSL https://raw.githubusercontent.com/CascadeSTEAM/opskit/main/setup-opskit.sh | bash
```

See [docs/onboarding/](docs/onboarding/) for environment setup and the example
environment in `environments/example/`.

## License

MIT — see [LICENSE](LICENSE).
