#!/usr/bin/env bash
set -euo pipefail

VERSION="1.0.0"
TMP_DIR=$(mktemp -d)
PRODUCTCOMPOSE_FILE="${BOT_FILE:-000productcompose/default.productcompose}"
IBS_BUILD_PROJECT="${BOT_PROJECT:-SUSE:SLFO:Main}"
BOT_OUTPUT="${BOT_OUTPUT:-text}"

# LOG_LEVEL: 0=quiet 1=info(default) 2=debug
LOG_LEVEL=1

trap 'rm -rf "${TMP_DIR}"' EXIT

# ─── Constants ─────────────────────────────────────────────────────────────────

EXIT_OK=0
EXIT_USAGE=64

# ─── Args ──────────────────────────────────────────────────────────────────────

usage() {
    cat <<EOF
Usage: bot.sh [OPTIONS]

Detect orphaned source packages newly added to the SLES product compose.

Options:
  -h, --help            Show this help and exit
  -V, --version         Print version and exit
  -q, --quiet           Suppress INFO logs (errors still shown)
  -v, --verbose         Enable DEBUG logs
      --project NAME    IBS build project  [env: BOT_PROJECT, default: SUSE:SLFO:Main]
      --file PATH       productcompose path [env: BOT_FILE, default: 000productcompose/default.productcompose]
      --output FORMAT   Output format: text (default) or json  [env: BOT_OUTPUT]
      --timeout SECS    Network timeout per attempt [env: BOT_TIMEOUT, default: 30]
      --retries N       Retry count for network calls [env: BOT_RETRIES, default: 3]

Exit codes:
  0   Clean — no orphans
  1   Internal error
  2   Orphans found
  64  Bad usage (EX_USAGE)
  69  Preflight failed: missing dep or auth (EX_UNAVAILABLE)
  124 Network call timed out after all retries
EOF
}

parse_args() {
    while [[ $# -gt 0 ]]; do
        case "$1" in
            -h|--help)
                usage
                exit "${EXIT_OK}"
                ;;
            -V|--version)
                printf '%s\n' "${VERSION}"
                exit "${EXIT_OK}"
                ;;
            -q|--quiet)
                LOG_LEVEL=0
                shift
                ;;
            -v|--verbose)
                LOG_LEVEL=2
                shift
                ;;
            --project)
                IBS_BUILD_PROJECT="${2:?--project requires a value}"
                shift 2
                ;;
            --file)
                PRODUCTCOMPOSE_FILE="${2:?--file requires a value}"
                shift 2
                ;;
            --output)
                BOT_OUTPUT="${2:?--output requires a value}"
                shift 2
                ;;
            *)
                printf '%s [ERROR] unknown option: %s\n' "$(_ts)" "$1" >&2
                usage >&2
                exit "${EXIT_USAGE}"
                ;;
        esac
    done
}

# ─── Logging ───────────────────────────────────────────────────────────────────

_ts() { date -u +"%Y-%m-%dT%H:%M:%SZ" 2>/dev/null || printf 'unknown-time'; }

log_info()  { (( LOG_LEVEL >= 1 )) && printf '%s [INFO]  %s\n' "$(_ts)" "$*" >&2 || return 0; }
log_warn()  { printf '%s [WARN]  %s\n' "$(_ts)" "$*" >&2; }
log_error() { printf '%s [ERROR] %s\n' "$(_ts)" "$*" >&2; }
log_debug() { (( LOG_LEVEL >= 2 )) && printf '%s [DEBUG] %s\n' "$(_ts)" "$*" >&2 || return 0; }

# ─── Output ────────────────────────────────────────────────────────────────────

# emit_report <orphans_newline_separated> <checked_count> <failed_binaries_newline_separated>
emit_report() {
    local orphans="$1"
    local checked="$2"
    local failed="$3"

    if [[ "${BOT_OUTPUT}" == "json" ]]; then
        local orphan_json failed_json
        orphan_json=$(printf '%s\n' "${orphans}" | awk 'NF' \
            | jq -Rn '[inputs]')
        failed_json=$(printf '%s\n' "${failed}" | awk 'NF' \
            | jq -Rn '[inputs]')
        printf '{"orphans":%s,"checked":%s,"failed_binaries":%s}\n' \
            "${orphan_json}" "${checked}" "${failed_json}"
    else
        if [[ -n "${orphans}" ]]; then
            printf '%s\n' "${orphans}"
        fi
    fi
}

# ─── Pipeline ──────────────────────────────────────────────────────────────────

resolve_workdir() {
    if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1 || [ ! -f "${PRODUCTCOMPOSE_FILE}" ]; then
        git clone gitea@src.suse.de:products/SLES.git "${TMP_DIR}/SLES"
        cd "${TMP_DIR}/SLES"
    fi
}

extract_added_binaries() {
    local last_sha git_diff binaries
    last_sha=$(git log -1 --format="%H" -- "${PRODUCTCOMPOSE_FILE}")
    [[ -n "${last_sha}" ]] || { log_error "no commits touch ${PRODUCTCOMPOSE_FILE}"; exit 1; }
    git_diff=$(git show "${last_sha}" -- "${PRODUCTCOMPOSE_FILE}")
    binaries=$(awk '/^\+[[:space:]]+-[[:space:]]+[A-Za-z0-9]/ { print $3 }' <<< "${git_diff}" | sort -u)
    if [[ -n "${BOT_TEST_FIXTURES:-}" ]]; then
        binaries="${binaries}
cargo1.94
cargo1.81
graphviz
graphviz-devel
graphviz-plugins-core
foobar"
    fi
    log_debug "NEW BINARIES:\\n${binaries}"
    printf '%s' "${binaries}"
}

resolve_sources() {
    local binaries="$1"
    export IBS_BUILD_PROJECT
    local results
    # shellcheck disable=SC2016
    results=$(printf '%s\n' "${binaries}" | grep -v '^$' | xargs -P4 -I{} bash -c '
        binary="$1"
        source_pkg=$(osc -A https://api.suse.de bse -B "${IBS_BUILD_PROJECT}" --csv "${binary}" \
            | awk -F"|" -v project="${IBS_BUILD_PROJECT}" "\$1 == project { print \$2 }")
        if [[ -n "${source_pkg}" ]]; then
            echo "SRC:${source_pkg}"
        else
            echo "FAIL:${binary}"
        fi
    ' _ {})

    SOURCES=$(awk -F':' '/^SRC:/ { print $2 }' <<< "${results}" | sort -u)
    FAILED_BINARIES=$(awk -F':' '/^FAIL:/ { print $2 }' <<< "${results}" | sort -u)
    if [[ -n "${BOT_TEST_FIXTURES:-}" ]]; then
        SOURCES="${SOURCES}
kernel-default
patterns-containers
patterns-container"
    fi
    log_debug "NEW SOURCES:\\n${SOURCES}"
    log_debug "FAILED BINARIES (No source found):\\n${FAILED_BINARIES}"
}

fetch_maintainership() {
    git archive --remote=ssh://gitea@src.suse.de/products/SLFO.git slfo-main _maintainership.json | tar -xO
}

find_orphans() {
    local sources="$1"
    local maintainership_json="$2"

    if [[ -z "${sources//[[:space:]]/}" ]]; then
        log_info "no new sources to check — nothing to do"
        return 0
    fi

    local sources_arr
    mapfile -t sources_arr < <(printf '%s\n' "${sources}" | awk 'NF')
    jq -rn '
        input as $db |
        $ARGS.positional[] as $pkg |
        if ($db.packages[$pkg] | . != null and ((.users | . != null and length > 0) or (.groups | . != null and length > 0))) then
            empty
        else
            "-- ORPHANED: \($pkg)"
        end
    ' --args "${sources_arr[@]}" <<< "${maintainership_json}"
}

# ─── Main ──────────────────────────────────────────────────────────────────────

main() {
    parse_args "$@"
    resolve_workdir

    local binaries
    binaries=$(extract_added_binaries)

    resolve_sources "${binaries}"

    local maintainership_json
    maintainership_json=$(fetch_maintainership)

    local source_count
    source_count=$(printf '%s\n' "${SOURCES}" | awk 'NF' | wc -l | tr -d ' ')
    log_info "checking ${source_count} source(s) against maintainership db"

    # exit 0 = clean, exit 1 = script error (set -e), exit 2 = orphans found
    local orphan_report
    orphan_report=$(find_orphans "${SOURCES}" "${maintainership_json}")

    emit_report "${orphan_report}" "${source_count}" "${FAILED_BINARIES:-}"

    if [[ -n "${orphan_report}" ]]; then
        exit 2
    fi

    log_info "all sources have maintainers — clean"
}

main "$@"
