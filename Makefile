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
lint:  ## Shell syntax + shellcheck (if installed) over scripts and hooks
	@for f in bin/*.sh .githooks/pre-commit .githooks/commit-msg; do bash -n "$$f" || exit 1; done
	@if command -v shellcheck >/dev/null; then shellcheck bin/*.sh || echo "(shellcheck findings above are informational)"; else echo "(shellcheck not installed — syntax check only)"; fi

.PHONY: guard
guard:  ## Run the publication guards against uncommitted staged changes
	bash bin/publication-guard.sh --cached
