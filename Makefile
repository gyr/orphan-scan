SHELL      := /usr/bin/env bash
SHELLCHECK ?= shellcheck
PREFIX     ?= /usr/local

.PHONY: help lint install uninstall clean

help: ## Show this help
	@awk 'BEGIN{FS=":.*##"} /^[a-zA-Z_-]+:.*##/ {printf "  %-12s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

lint: ## Static analysis (shellcheck)
	$(SHELLCHECK) -x bot.sh

install: ## Install bot.sh to $(PREFIX)/bin
	install -Dm755 bot.sh $(PREFIX)/bin/bot

uninstall: ## Remove bot from $(PREFIX)/bin
	rm -f $(PREFIX)/bin/bot

clean: ## Remove generated artefacts
	rm -rf .tmp/
