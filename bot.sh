#!/usr/bin/env bash
set -euo pipefail

VERSION="1.0.0"
TMP_DIR=$(mktemp -d)
PRODUCTCOMPOSE_FILE="${BOT_FILE:-000productcompose/default.productcompose}"
IBS_BUILD_PROJECT="${BOT_PROJECT:-SUSE:SLFO:Main}"
BOT_OUTPUT="${BOT_OUTPUT:-text}"
BOT_TIMEOUT="${BOT_TIMEOUT:-30}"
BOT_RETRIES="${BOT_RETRIES:-3}"

# LOG_LEVEL: 0=quiet 1=info(default) 2=debug
LOG_LEVEL=1

trap 'rm -rf "${TMP_DIR}"' EXIT

# ─── Constants ─────────────────────────────────────────────────────────────────

EXIT_OK=0
EXIT_USAGE=64
EXIT_PREFLIGHT=69

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
            --timeout)
                BOT_TIMEOUT="${2:?--timeout requires a value}"
                shift 2
                ;;
            --retries)
                BOT_RETRIES="${2:?--retries requires a value}"
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

# ─── Network ───────────────────────────────────────────────────────────────────

# with_retry <label> <cmd> [args...]
# Runs <cmd> up to BOT_RETRIES times with timeout BOT_TIMEOUT.
# Returns 0 on first success; logs WARN on each failure; logs ERROR and returns
# the last exit code when retries are exhausted.
with_retry() {
    local label="$1"; shift
    local attempt=1 sleep_for=1 rc
    while :; do
        rc=0
        timeout "${BOT_TIMEOUT}" "$@" || rc=$?
        if (( rc == 0 )); then return 0; fi
        if (( attempt >= BOT_RETRIES )); then
            log_error "${label} failed after ${attempt} attempt(s) (last rc=${rc})"
            return "${rc}"
        fi
        log_warn "${label} failed (attempt ${attempt}/${BOT_RETRIES}, rc=${rc}), retrying in ${sleep_for}s"
        sleep "${sleep_for}"
        attempt=$(( attempt + 1 ))
        sleep_for=$(( sleep_for * 2 ))
    done
}

# ─── Preflight ─────────────────────────────────────────────────────────────────

preflight() {
    # Skipped whenever BOT_TEST_FIXTURES is set (even to empty), unless BOT_FORCE_PREFLIGHT=1.
    if [[ -n "${BOT_TEST_FIXTURES+x}" && -z "${BOT_FORCE_PREFLIGHT:-}" ]]; then
        return 0
    fi

    local missing=()
    for bin in git jq awk osc xargs timeout ssh; do
        command -v "${bin}" >/dev/null 2>&1 || missing+=("${bin}")
    done
    if (( ${#missing[@]} > 0 )); then
        log_error "missing dependencies: ${missing[*]}"
        log_error "install the missing tools and retry"
        exit "${EXIT_PREFLIGHT}"
    fi

    if ! timeout 10 osc -A https://api.suse.de whois >/dev/null 2>&1; then
        log_error "osc authentication failed for https://api.suse.de — run 'osc -A https://api.suse.de login' or set credentials"
        exit "${EXIT_PREFLIGHT}"
    fi

    local ssh_rc=0
    timeout 10 ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new \
        -T gitea@src.suse.de 2>/dev/null || ssh_rc=$?
    if (( ssh_rc == 255 )); then
        log_error "ssh to gitea@src.suse.de failed — check your SSH key"
        exit "${EXIT_PREFLIGHT}"
    fi
}

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
        with_retry "git clone SLES" git clone gitea@src.suse.de:products/SLES.git "${TMP_DIR}/SLES"
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
    log_debug "NEW BINARIES:"$'\n'"${binaries}"
    printf '%s' "${binaries}"
}

resolve_sources() {
    local binaries="$1"
    export IBS_BUILD_PROJECT BOT_TIMEOUT BOT_RETRIES LOG_LEVEL
    export -f with_retry log_warn log_error log_info log_debug _ts

    local results_file
    results_file=$(mktemp "${TMP_DIR}/results.XXXXXX")
    local xargs_rc=0

    # shellcheck disable=SC2016
    printf '%s\n' "${binaries}" | grep -v '^$' | \
        xargs -P4 -I{} bash -c '
            binary="$1"
            osc_out=""
            osc_out=$(with_retry "osc bse ${binary}" \
                osc -A https://api.suse.de bse -B "${IBS_BUILD_PROJECT}" --csv "${binary}") || exit 1
            source_pkg=$(awk -F"|" -v project="${IBS_BUILD_PROJECT}" \
                "\$1 == project { print \$2 }" <<< "${osc_out}")
            if [[ -n "${source_pkg}" ]]; then
                printf "SRC:%s\n" "${source_pkg}"
            else
                printf "FAIL:%s\n" "${binary}"
            fi
        ' _ {} >> "${results_file}" || xargs_rc=$?

    if (( xargs_rc != 0 )); then
        log_error "source resolution failed — one or more osc lookups exhausted retries"
        exit 1
    fi

    local results
    results=$(< "${results_file}")

    SOURCES=$(awk -F':' '/^SRC:/ { print $2 }' <<< "${results}" | sort -u)
    FAILED_BINARIES=$(awk -F':' '/^FAIL:/ { print $2 }' <<< "${results}" | sort -u)
    if [[ -n "${BOT_TEST_FIXTURES:-}" ]]; then
        SOURCES="${SOURCES}
kernel-default
patterns-containers
patterns-container"
    fi
    log_debug "NEW SOURCES:"$'\n'"${SOURCES}"
    log_debug "FAILED BINARIES (No source found):"$'\n'"${FAILED_BINARIES}"
}

fetch_maintainership() {
    local archive_tmp attempt sleep_for rc
    archive_tmp=$(mktemp "${TMP_DIR}/archive.XXXXXX")
    attempt=1
    sleep_for=1
    while :; do
        rc=0
        timeout "${BOT_TIMEOUT}" git archive \
            --remote=ssh://gitea@src.suse.de/products/SLFO.git \
            slfo-main _maintainership.json > "${archive_tmp}" || rc=$?
        if (( rc == 0 )); then
            tar -xO < "${archive_tmp}"
            return 0
        fi
        if (( attempt >= BOT_RETRIES )); then
            log_error "git archive (SLFO maintainership) failed after ${attempt} attempt(s) (rc=${rc})"
            exit 1
        fi
        log_warn "git archive (SLFO maintainership) failed (attempt ${attempt}/${BOT_RETRIES}, rc=${rc}), retrying in ${sleep_for}s"
        sleep "${sleep_for}"
        attempt=$(( attempt + 1 ))
        sleep_for=$(( sleep_for * 2 ))
        : > "${archive_tmp}"
    done
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
    preflight
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
