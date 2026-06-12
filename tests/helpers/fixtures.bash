#!/usr/bin/env bash
# Canned outputs and mock-installation helpers for specific binaries.

# Installs a git mock that:
#   - returns 0 for rev-parse (we are in a work tree)
#   - returns a fake SHA for log
#   - returns a fake diff for show
#   - is a no-op for clone
install_git_mock() {
    install_mock git '
case "$1" in
    rev-parse) exit 0 ;;
    log)       echo "aaabbbccc111" ;;
    show)      printf "+  - newpkg\n" ;;
    clone)     exit 0 ;;
    archive)
        # Pipe a tar stream containing a minimal _maintainership.json
        tmpd=$(mktemp -d)
        echo "{\"packages\":{}}" > "${tmpd}/_maintainership.json"
        tar -C "${tmpd}" -c _maintainership.json
        rm -rf "${tmpd}"
        ;;
    *)         exit 0 ;;
esac
'
}

# Installs an osc mock that resolves every binary to "src-pkg".
install_osc_mock() {
    install_mock osc '
echo "SUSE:SLFO:Main|src-pkg|x86_64|standard"
'
}

# Installs a jq passthrough (real jq may not be in the mock PATH).
install_jq_passthrough() {
    install_mock jq "exec /usr/bin/jq \"\$@\""
}
