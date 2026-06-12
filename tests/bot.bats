#!/usr/bin/env bats
# bats test suite for bot.sh

load helpers/common
load helpers/fixtures

REPO_ROOT="$(cd "$(dirname "${BATS_TEST_FILENAME}")/.." && pwd)"

setup() {
    setup_mocks
}

teardown() {
    teardown_mocks
}

@test "bot.sh is executable" {
    [ -x "${REPO_ROOT}/bot.sh" ]
}

@test "log output contains [INFO] tag on stderr" {
    create_fake_workspace
    install_git_mock
    install_osc_mock
    install_jq_passthrough
    run bash -c "cd '${WORKSPACE}' && '${REPO_ROOT}/bot.sh'" 2>&1
    [[ "${output}" =~ \[INFO\] ]]
}

@test "empty SOURCES (all binaries unresolvable) exits 0, not 2" {
    create_fake_workspace
    # git mock: show returns a diff line that produces a binary, but osc always fails to resolve it
    install_git_mock
    install_jq_passthrough
    # osc mock that always fails to resolve (returns nothing)
    install_mock osc 'echo ""'
    # BOT_TEST_FIXTURES adds extra binaries/sources — disable it so SOURCES stays empty
    run bash -c "cd '${WORKSPACE}' && BOT_TEST_FIXTURES= '${REPO_ROOT}/bot.sh'" 2>&1
    [ "${status}" -eq 0 ]
    # stdout must be empty (no orphan lines)
    [[ -z "$(bash -c "cd '${WORKSPACE}' && BOT_TEST_FIXTURES= '${REPO_ROOT}/bot.sh' 2>/dev/null")" ]]
}
