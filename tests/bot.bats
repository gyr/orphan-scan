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

@test "--help exits 0 and prints usage to stdout" {
    run "${REPO_ROOT}/bot.sh" --help
    [ "${status}" -eq 0 ]
    [[ "${output}" =~ "Usage:" ]]
}

@test "--version exits 0 and prints version string" {
    run "${REPO_ROOT}/bot.sh" --version
    [ "${status}" -eq 0 ]
    [[ "${output}" =~ [0-9]+\.[0-9]+\.[0-9]+ ]]
}

@test "unknown flag exits 64 with usage on stderr" {
    run "${REPO_ROOT}/bot.sh" --bogus-flag
    [ "${status}" -eq 64 ]
    [[ "${output}" =~ "Usage:" ]]
}

@test "--project override is passed to osc invocation" {
    create_fake_workspace
    install_git_mock
    install_jq_passthrough
    # osc mock that echoes the project argument so we can assert it
    install_mock osc 'echo "CUSTOM_PROJECT|src-pkg|x86_64|standard"'
    # also install an osc that records its args
    local capture_file="${MOCK_DIR}/osc_args"
    install_mock osc "echo \"\$@\" >> '${capture_file}'; echo 'CUSTOM_PROJECT|src-pkg|x86_64|standard'"
    run bash -c "cd '${WORKSPACE}' && BOT_TEST_FIXTURES= '${REPO_ROOT}/bot.sh' --project CUSTOM_PROJECT" 2>&1
    grep -q 'CUSTOM_PROJECT' "${capture_file}"
}

@test "BOT_PROJECT env var sets the project" {
    create_fake_workspace
    install_git_mock
    install_jq_passthrough
    local capture_file="${MOCK_DIR}/osc_args"
    install_mock osc "echo \"\$@\" >> '${capture_file}'; echo 'ENV_PROJECT|src-pkg|x86_64|standard'"
    run bash -c "cd '${WORKSPACE}' && BOT_TEST_FIXTURES= BOT_PROJECT=ENV_PROJECT '${REPO_ROOT}/bot.sh'" 2>&1
    grep -q 'ENV_PROJECT' "${capture_file}"
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
