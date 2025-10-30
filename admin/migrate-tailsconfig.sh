#!/bin/bash
# tailsconfig script for migration from git-based to deb-based installer
# This script runs localconfig and notifies the user to reboot
set -e
set -o pipefail

# Error handler - shows GUI dialog and exits
error_exit() {
    local message="$1"
    echo "ERROR: $message"
    if command -v zenity >/dev/null 2>&1; then
        zenity --error \
            --title="SecureDrop Tailsconfig Error" \
            --width=400 \
            --text="$message"
    else
        echo "CRITICAL: zenity not available for GUI error display"
    fi
    exit 1
}

/usr/bin/securedrop-admin localconfig || error_exit "securedrop-admin localconfig failed."
