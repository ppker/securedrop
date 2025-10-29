#!/bin/bash
# tailsconfig script for migration from git-based to deb-based installer
# This script runs localconfig and notifies the user to reboot
set -e
set -o pipefail

# Logging
LOG_FILE="/tmp/securedrop-tailsconfig.log"
exec > >(tee -a "$LOG_FILE") 2>&1

echo "=== SecureDrop git-to-deb Tailsconfig Script Started at $(date) ==="

# Error handler - shows GUI dialog and exits
error_exit() {
    local message="$1"
    echo "ERROR: $message"
    if command -v zenity >/dev/null 2>&1; then
        zenity --error \
            --title="SecureDrop Tailsconfig Error" \
            --width=400 \
            --text="$message\n\nSee log file: $LOG_FILE"
    else
        echo "CRITICAL: zenity not available for GUI error display"
    fi
    exit 1
}

/usr/bin/securedrop-admin localconfig || error_exit "securedrop-admin localconfig failed."

# Show reboot notification
if command -v zenity >/dev/null 2>&1; then
    zenity --info \
        --title="SecureDrop Migration Complete" \
        --width=500 \
        --text="Migration to the debian-based installer is complete.\n\n\
Please REBOOT Tails to complete the setup.\n\n\
After reboot:\n\
• The GNOME shell extension will be loaded\n\
• Desktop shortcuts will use the new configuration\n\
• The GUI updater will no longer run\n\
• Use 'securedrop-admin' command for all operations\n\n\
Log file: $LOG_FILE"
fi

echo ""
echo "=== Tailsconfig completed successfully at $(date) ==="
