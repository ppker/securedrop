#!/bin/bash
# Part 1 of migration: Install the securedrop-admin debian package
# This script is executed as root via pkexec
set -e
set -o pipefail

DEB_PACKAGE="$1"
LOG_FILE="$2"

if [[ -z "$DEB_PACKAGE" ]] || [[ -z "$LOG_FILE" ]]; then
    echo "ERROR: Missing required arguments"
    echo "Usage: $0 <deb_package_path> <log_file_path>"
    exit 1
fi

# Install the debian package
if ! dpkg -i "$DEB_PACKAGE" 2>&1 | tee -a "$LOG_FILE"; then
    echo "dpkg had issues, attempting to fix dependencies..." | tee -a "$LOG_FILE"
    if ! apt-get install -f -y 2>&1 | tee -a "$LOG_FILE"; then
        echo "ERROR: Failed to install package and fix dependencies" | tee -a "$LOG_FILE"
        exit 1
    fi
fi

echo "- Package installed successfully" | tee -a "$LOG_FILE"
exit 0
