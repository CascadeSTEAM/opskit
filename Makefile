# opskit Makefile — the single entrypoint for the test/lint gate.
# CI runs exactly `make test`; developers run exactly `make test`.
# If they ever behave differently, that is a bug (issue #19).

VENV := .venv
STAMP := $(VENV)/.deps-stamp

$(STAMP): requirements-dev.txt
	python3 -m venv $(VENV)
	$(VENV)/bin/pip install --quiet --upgrade pip
	$(VENV)/bin/pip install --quiet -r requirements-dev.txt
	touch $(STAMP)

.PHONY: deps
deps: $(STAMP)  ## Create/refresh the venv from requirements-dev.txt

.PHONY: test
test: deps  ## Full test gate — required before any PR (AGENTS.md)
	$(VENV)/bin/python -m pytest tests/ -q

.PHONY: lint
lint: lint-ansible  ## Shell syntax + shellcheck + ansible-lint over the repo
	@for f in bin/*.sh .githooks/pre-commit .githooks/commit-msg; do bash -n "$$f" || exit 1; done
	@if command -v shellcheck >/dev/null; then shellcheck bin/*.sh || echo "(shellcheck findings above are informational)"; else echo "(shellcheck not installed — syntax check only)"; fi

.PHONY: lint-ansible
lint-ansible:  ## ansible-lint over tracked playbooks/roles (zero failures expected — #87)
	@# Degrades like the shellcheck step above rather than failing, so `make lint`
	@# stays usable on a machine without the Ansible toolchain installed.
	@if ! command -v ansible-lint >/dev/null; then \
		echo "(ansible-lint not installed — skipping; pipx install ansible-lint)"; \
	else \
		ansible-lint ansible/; \
	fi
	@# Uses .ansible-lint.yml. Never pass --skip-list with an unskippable rule
	@# (syntax-check, load-failure) — ansible-lint then aborts instead of
	@# linting, which is how #83 went unnoticed. `make test` guards the config.

.PHONY: guard
guard:  ## Run the publication guards against uncommitted staged changes
	bash bin/publication-guard.sh --cached
