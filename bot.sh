#!/usr/bin/env bash
set -euo pipefail

TMP_DIR=$(mktemp -d)
PRODUCTCOMPOSE_FILE="000productcompose/default.productcompose"
IBS_BUILD_PROJECT="SUSE:SLFO:Main"

# LOG_LEVEL: 0=quiet 1=info(default) 2=debug
LOG_LEVEL=1

trap 'rm -rf "${TMP_DIR}"' EXIT

# ─── Logging ───────────────────────────────────────────────────────────────────

_ts() { date -u +"%Y-%m-%dT%H:%M:%SZ"; }

log_info()  { (( LOG_LEVEL >= 1 )) && printf '%s [INFO]  %s\n' "$(_ts)" "$*" >&2 || return 0; }
log_warn()  { printf '%s [WARN]  %s\n' "$(_ts)" "$*" >&2; }
log_error() { printf '%s [ERROR] %s\n' "$(_ts)" "$*" >&2; }
log_debug() { (( LOG_LEVEL >= 2 )) && printf '%s [DEBUG] %s\n' "$(_ts)" "$*" >&2 || return 0; }

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
    local sources_arr
    mapfile -t sources_arr <<< "${sources}"
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
    resolve_workdir

    local binaries
    binaries=$(extract_added_binaries)

    resolve_sources "${binaries}"

    local maintainership_json
    maintainership_json=$(fetch_maintainership)

    log_info "checking $(printf '%s\n' "${SOURCES}" | grep -c .) source(s) against maintainership db"

    # exit 0 = clean, exit 1 = script error (set -e), exit 2 = orphans found
    local orphan_report
    orphan_report=$(find_orphans "${SOURCES}" "${maintainership_json}")

    if [[ -n "${orphan_report}" ]]; then
        printf '%s\n' "${orphan_report}"
        exit 2
    fi

    log_info "all sources have maintainers — clean"
}

main "$@"
