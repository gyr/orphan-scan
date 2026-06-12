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
