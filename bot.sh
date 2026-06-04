#!/usr/bin/env bash
set -euo pipefail

TMP_DIR=$(mktemp -d)
PRODUCTCOMPOSE_FILE="000productcompose/default.productcompose"
IBS_BUILD_PROJECT="SUSE:SLFO:Main"

trap 'rm -rf "${TMP_DIR}"' EXIT

debug() {
    printf -- "-- DEBUG START --\n%b\n" "$*" >&2
    printf -- "-- DEBUG END --\n" >&2
}

# clone SLES repo if not inside a git repository or productcompose file does not exist
if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1 || [ ! -f "${PRODUCTCOMPOSE_FILE}" ]; then
    git clone gitea@src.suse.de:products/SLES.git "${TMP_DIR}/SLES"
    cd "${TMP_DIR}/SLES"
fi

# retrieve the lastet binaries added
LAST_SHA=$(git log -1 --format="%H" -- "${PRODUCTCOMPOSE_FILE}")
[[ -n "${LAST_SHA}" ]] || { printf -- 'ERROR: no commits touch %s\n' "${PRODUCTCOMPOSE_FILE}" >&2; exit 1; }
GIT_DIFF=$(git show "${LAST_SHA}" -- "${PRODUCTCOMPOSE_FILE}")
BINARIES=$(awk '/^\+[[:space:]]+-[[:space:]]+[A-Za-z0-9]/ { print $3 }' <<< "${GIT_DIFF}" | sort -u)
if [[ -n "${BOT_TEST_FIXTURES:-}" ]]; then
    BINARIES="${BINARIES}
cargo1.94
cargo1.81
graphviz
graphviz-devel
graphviz-plugins-core
foobar"
fi
debug "NEW BINARIES:\\n${BINARIES}"

# find the source packages (-P4 to avoid hammering the IBS API)
export IBS_BUILD_PROJECT
# shellcheck disable=SC2016
RESULTS=$(printf '%s\n' "${BINARIES}" | grep -v '^$' | xargs -P4 -I{} bash -c '
    binary="$1"
    source_pkg=$(osc -A https://api.suse.de bse -B "${IBS_BUILD_PROJECT}" --csv "${binary}" \
        | awk -F"|" -v project="${IBS_BUILD_PROJECT}" "\$1 == project { print \$2 }")
    if [[ -n "${source_pkg}" ]]; then
        echo "SRC:${source_pkg}"
    else
        echo "FAIL:${binary}"
    fi
' _ {})

# Extract variables from results
SOURCES=$(awk -F':' '/^SRC:/ { print $2 }' <<< "${RESULTS}" | sort -u)
FAILED_BINARIES=$(awk -F':' '/^FAIL:/ { print $2 }' <<< "${RESULTS}" | sort -u)
if [[ -n "${BOT_TEST_FIXTURES:-}" ]]; then
    SOURCES="${SOURCES}
kernel-default
patterns-containers
patterns-container"
fi
debug "NEW SOURCES:\\n${SOURCES}"
debug "FAILED BINARIES (No source found):\\n${FAILED_BINARIES}"

# retrieve maintainership json
MAINTAINERSHIP_JSON=$(git archive --remote=ssh://gitea@src.suse.de/products/SLFO.git slfo-main _maintainership.json | tar -xO)

# check if new sources has a maintainer in maintainership json
# exit 0 = clean, exit 1 = script error (set -e), exit 2 = orphans found
mapfile -t SOURCES_ARR <<< "${SOURCES}"
ORPHAN_REPORT=$(jq -rn '
    input as $db |
    $ARGS.positional[] as $pkg |
    if ($db.packages[$pkg] | . != null and ((.users | . != null and length > 0) or (.groups | . != null and length > 0))) then
        empty
    else
        "-- ORPHANED: \($pkg)"
    end
' --args "${SOURCES_ARR[@]}" <<< "${MAINTAINERSHIP_JSON}")

if [[ -n "${ORPHAN_REPORT}" ]]; then
    printf '%s\n' "${ORPHAN_REPORT}"
    exit 2
fi
