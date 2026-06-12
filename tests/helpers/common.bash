#!/usr/bin/env bash
# Shared setup/teardown and assertion helpers for the bot.sh bats suite.

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
MOCK_DIR=""

setup_mocks() {
    MOCK_DIR="$(mktemp -d)"
    export PATH="${MOCK_DIR}:${PATH}"
    export BOT_TEST_FIXTURES=1
}

teardown_mocks() {
    [[ -n "${MOCK_DIR}" ]] && rm -rf "${MOCK_DIR}"
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
