SHELL      := /usr/bin/env bash
BATS       ?= bats
SHELLCHECK ?= shellcheck
PREFIX     ?= /usr/local

.PHONY: help lint test check install uninstall clean

help: ## Show this help
	@awk 'BEGIN{FS=":.*##"} /^[a-zA-Z_-]+:.*##/ {printf "  %-12s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

lint: ## Static analysis (shellcheck)
	$(SHELLCHECK) -x bot.sh

test: ## Run bats test suite
	$(BATS) tests/

check: lint test ## Lint + tests (CI entry point)

install: ## Install bot.sh to $(PREFIX)/bin
	install -Dm755 bot.sh $(PREFIX)/bin/bot

uninstall: ## Remove bot from $(PREFIX)/bin
	rm -f $(PREFIX)/bin/bot

clean: ## Remove generated artefacts
	rm -rf .tmp/
