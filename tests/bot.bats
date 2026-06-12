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

@test "--quiet suppresses INFO but errors still appear" {
    run "${REPO_ROOT}/bot.sh" --quiet --bogus-flag 2>&1
    [ "${status}" -eq 64 ]
    [[ "${output}" =~ \[ERROR\] ]]
    [[ ! "${output}" =~ \[INFO\] ]]
}

@test "--verbose enables DEBUG log output" {
    create_fake_workspace
    install_git_mock
    install_osc_mock
    install_jq_passthrough
    run bash -c "cd '${WORKSPACE}' && '${REPO_ROOT}/bot.sh' --verbose" 2>&1
    [[ "${output}" =~ \[DEBUG\] ]]
}

@test "--output json produces valid JSON on stdout" {
    create_fake_workspace
    install_git_mock
    install_osc_mock
    install_jq_passthrough
    # Run and capture only stdout (no 2>&1) — json goes to stdout
    run bash -c "cd '${WORKSPACE}' && '${REPO_ROOT}/bot.sh' --output json 2>/dev/null"
    [ "${status}" -eq 0 ] || [ "${status}" -eq 2 ]
    # stdout must be valid JSON
    printf '%s' "${output}" | /usr/bin/jq -e . >/dev/null
}

@test "--output text (default) still emits orphan lines on stdout" {
    create_fake_workspace
    install_jq_passthrough
    # git mock that returns an orphaned source (maintainership db is empty)
    install_git_mock
    install_osc_mock
    # Run in text mode (default); orphans should appear on stdout
    run bash -c "cd '${WORKSPACE}' && '${REPO_ROOT}/bot.sh' 2>/dev/null"
    # BOT_TEST_FIXTURES is set (setup_mocks) so orphans will exist
    [[ "${output}" =~ "-- ORPHANED:" ]]
}

@test "transient osc failure retries and eventually succeeds" {
    create_fake_workspace
    install_jq_passthrough
    # git mock: archive returns maintainership that includes src-pkg so no orphans on success
    install_mock git '
case "$1" in
    rev-parse) exit 0 ;;
    log)       echo "aaabbbccc111" ;;
    show)      printf "+  - newpkg\n" ;;
    clone)     exit 0 ;;
    archive)
        tmpd=$(mktemp -d)
        printf "%s" '"'"'{"packages":{"src-pkg":{"users":["someone"],"groups":[]}}}'"'"' \
            > "${tmpd}/_maintainership.json"
        tar -C "${tmpd}" -c _maintainership.json
        rm -rf "${tmpd}"
        ;;
    *)         exit 0 ;;
esac
'
    # osc mock: fails twice, succeeds on third attempt
    local attempt_file="${MOCK_DIR}/osc_attempt"
    printf '0' > "${attempt_file}"
    install_mock osc "
count=\$(cat '${attempt_file}')
count=\$((count + 1))
printf '%s' \"\${count}\" > '${attempt_file}'
if [ \"\${count}\" -lt 3 ]; then
    exit 1
fi
echo 'SUSE:SLFO:Main|src-pkg|x86_64|standard'
"
    run bash -c "cd '${WORKSPACE}' && BOT_TEST_FIXTURES= BOT_RETRIES=3 BOT_TIMEOUT=5 '${REPO_ROOT}/bot.sh'" 2>&1
    [ "${status}" -eq 0 ]
    [[ "${output}" =~ \[WARN\] ]]
}

@test "retry exhaustion exits non-zero with ERROR log" {
    create_fake_workspace
    install_git_mock
    install_jq_passthrough
    # osc mock: always fails
    install_mock osc 'exit 1'
    run bash -c "cd '${WORKSPACE}' && BOT_TEST_FIXTURES= BOT_RETRIES=2 BOT_TIMEOUT=5 '${REPO_ROOT}/bot.sh'" 2>&1
    [ "${status}" -ne 0 ]
    [[ "${output}" =~ \[ERROR\] ]]
}

@test "failing osc auth triggers exit 69 with actionable message" {
    # osc exists but 'osc whois' fails → simulates expired/missing credentials
    # BOT_FORCE_PREFLIGHT=1 bypasses the BOT_TEST_FIXTURES skip
    # osc is called as: osc -A https://... whois  (whois is $4, not $1)
    install_mock osc '
if printf "%s\n" "$@" | grep -q "^whois$"; then
    exit 1
fi
echo "SUSE:SLFO:Main|src-pkg|x86_64|standard"
'
    run bash -c "BOT_FORCE_PREFLIGHT=1 '${REPO_ROOT}/bot.sh'" 2>&1
    [ "${status}" -eq 69 ]
    [[ "${output}" =~ "osc authentication failed" ]]
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
