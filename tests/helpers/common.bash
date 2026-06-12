#!/usr/bin/env bash
# Shared setup/teardown and assertion helpers for the bot.sh bats suite.

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
MOCK_DIR=""

WORKSPACE=""

setup_mocks() {
    MOCK_DIR="$(mktemp -d)"
    export PATH="${MOCK_DIR}:${PATH}"
    export BOT_TEST_FIXTURES=1
}

teardown_mocks() {
    [[ -n "${MOCK_DIR}" ]] && rm -rf "${MOCK_DIR}"
    [[ -n "${WORKSPACE}" ]] && rm -rf "${WORKSPACE}"
    WORKSPACE=""
}

# Create a temp directory that looks like an SLES checkout:
#   000productcompose/default.productcompose exists so bot.sh won't clone.
# Sets and exports WORKSPACE; call before run.
create_fake_workspace() {
    WORKSPACE="$(mktemp -d)"
    mkdir -p "${WORKSPACE}/000productcompose"
    touch "${WORKSPACE}/000productcompose/default.productcompose"
}

# Install a named mock executable into MOCK_DIR.
# Usage: install_mock <name> <body>
# <body> is the full bash script body (without shebang).
install_mock() {
    local name="$1"
    local body="$2"
    printf '#!/usr/bin/env bash\n%s\n' "${body}" > "${MOCK_DIR}/${name}"
    chmod +x "${MOCK_DIR}/${name}"
}
