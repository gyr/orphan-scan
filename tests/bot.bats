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
