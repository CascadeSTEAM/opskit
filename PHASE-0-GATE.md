# Phase 0 Gate Checklist

From the [opskit umbrella plan](https://github.com/CascadeSTEAM/opskit/blob/main/docs/umbrella-plan.md).

- [ ] Name decided: **opskit**
- [ ] License decided: **MIT**
- [ ] GitHub org: **CascadeSTEAM**
- [ ] Packaging: **setup-opskit.sh** (DocWright pattern)
- [ ] Execution plane: **Semaphore UI** (adopted)
- [ ] Source of truth: **NetBox-canonical**
- [ ] Repo scaffolded with directory tree per umbrella §6
- [ ] `.gitignore` guarantees: `environments/*/` ignored except `environments/example/`; `customer/` ignored; `data/` ignored
- [ ] CI green: gitleaks, shellcheck, ansible-lint, pytest
- [ ] Credentials rotated: zabbix-management.skill plaintext, S1 (Zabbix admin in git), S2 (Zabbix PSK in git)
- [ ] Fresh git history (no import from the predecessor private ops repo)
