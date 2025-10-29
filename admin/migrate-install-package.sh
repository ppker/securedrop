#!/bin/bash
# Part 1 of migration: Install the securedrop-admin debian package
# This script is executed as root via pkexec
set -e
set -o pipefail

DEB_PACKAGE="$1"

if [[ -z "$DEB_PACKAGE" ]]; then
    echo "ERROR: Missing required arguments"
    echo "Usage: $0 <deb_package_path>"
    exit 1
fi

# Install the debian package
if ! dpkg -i "$DEB_PACKAGE"; then
    echo "dpkg had issues, attempting to fix dependencies..."
    if ! apt-get install -f -y; then
        echo "ERROR: Failed to install package and fix dependencies"
        exit 1
    fi
fi

echo "- Package installed successfully"
exit 0
