#!/bin/bash
# Migration script from git-based to debian-package-based SecureDrop installer
# This script performs a one-time migration for existing users
set -e
set -o pipefail

# Logging
LOG_FILE="/tmp/securedrop-migration.log"
exec > >(tee -a "$LOG_FILE") 2>&1

# Error handler - shows GUI dialog and exits
error_exit() {
    local message="$1"
    echo "ERROR: $message"
    if command -v zenity >/dev/null 2>&1; then
        zenity --error \
            --title="SecureDrop Migration Error" \
            --width=400 \
            --text="$message\n\nSee log file: $LOG_FILE"
    else
        echo "CRITICAL: zenity not available for GUI error display"
    fi
    exit 1
}

# Check if running on Tails
if [[ ! -f /etc/os-release ]] || ! grep -q 'NAME="Tails"' /etc/os-release; then
    error_exit "This script must be run on Tails.\n\nCurrent system is not Tails."
fi
echo "- Running on Tails"

# Check Tails version >= 7
tails_version=$(grep '^VERSION=' /etc/os-release | cut -d= -f2 | tr -d '"')
tails_major_version=$(echo "$tails_version" | cut -d. -f1)
if (( tails_major_version < 7 )); then
    error_exit "This migration requires Tails 7 or later.\n\nCurrent version: $tails_version\n\nPlease upgrade Tails before migrating."
fi
echo "- Tails version: $tails_version"

# Check if old config directory exists
OLD_CONFIG_DIR="$HOME/Persistent/securedrop/install_files/ansible-base"
if [[ ! -d "$OLD_CONFIG_DIR" ]]; then
    error_exit "Old configuration directory not found.\n\nExpected: $OLD_CONFIG_DIR\n\nThis script is for migrating existing installations only."
fi
echo "- Old config directory found: $OLD_CONFIG_DIR"

# Check if deb package exists
# TODO: In production, this will be replaced with apt repository installation
DEB_PACKAGE="$HOME/Persistent/securedrop-admin.deb"
if [[ ! -f "$DEB_PACKAGE" ]]; then
    error_exit "Debian package not found.\n\nExpected: $DEB_PACKAGE\n\nPlease ensure the package file is in place before migrating.\n\nNote: This is temporary for development. Production will use apt repository."
fi
echo "- Debian package found: $DEB_PACKAGE"

# TODO: In production, we will add a persistent APT repository
# For now, install from local deb file
if ! pkexec dpkg -i "$DEB_PACKAGE" 2>&1 | tee -a "$LOG_FILE"; then
    echo "dpkg had issues, attempting to fix dependencies..."
    if ! pkexec apt-get install -f -y 2>&1 | tee -a "$LOG_FILE"; then
        error_exit "Failed to install package and fix dependencies.\n\nSee log for details: $LOG_FILE"
    fi
fi
echo "- Package installed successfully"

# Verify installation
if ! command -v /usr/bin/securedrop-admin >/dev/null 2>&1; then
    error_exit "Package installed but securedrop-admin command not found.\n\nInstallation may have failed."
fi
echo "- securedrop-admin command is available"

# Get the script directory to find tails-bootstrap.sh
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BOOTSTRAP_SCRIPT="$SCRIPT_DIR/tails-bootstrap.sh"

if [[ ! -f "$BOOTSTRAP_SCRIPT" ]]; then
    error_exit "Tails bootstrap script not found.\n\nExpected: $BOOTSTRAP_SCRIPT"
fi

echo "Running tails-bootstrap.sh..."
if ! pkexec bash "$BOOTSTRAP_SCRIPT" 2>&1 | tee -a "$LOG_FILE"; then
    error_exit "Failed to configure Tails persistence.\n\nSee log for details: $LOG_FILE"
fi
echo "- Tails persistence configured"

# TODO: Make package install on every boot
# In production, this will be handled by a persistent APT repository
# For development/testing, the .deb needs to be manually reinstalled after reboot
# or we need to add a startup script to reinstall it
echo "TODO: In production, package will persist via APT repository"

NEW_CONFIG_DIR="$HOME/.config/securedrop-admin"
mkdir -p "$NEW_CONFIG_DIR"
echo "- Created new config directory: $NEW_CONFIG_DIR"

# Copy site-specific config
if [[ -f "$OLD_CONFIG_DIR/group_vars/all/site-specific" ]]; then
    cp "$OLD_CONFIG_DIR/group_vars/all/site-specific" "$NEW_CONFIG_DIR/"
    echo "- Migrated: site-specific"
else
    echo "! Not found (skipping): site-specific"
fi

# Copy Tor v3 keys
if [[ -f "$OLD_CONFIG_DIR/tor_v3_keys.json" ]]; then
    cp "$OLD_CONFIG_DIR/tor_v3_keys.json" "$NEW_CONFIG_DIR/"
    echo "- Migrated: tor_v3_keys.json"
else
    echo "! Not found (skipping): tor_v3_keys.json"
fi

# Copy auth files
for auth_file in app-journalist.auth_private app-ssh.auth_private mon-ssh.auth_private; do
    if [[ -f "$OLD_CONFIG_DIR/$auth_file" ]]; then
        cp "$OLD_CONFIG_DIR/$auth_file" "$NEW_CONFIG_DIR/"
        echo "- Migrated: $auth_file"
    else
        echo "! Not found (skipping): $auth_file"
    fi
done

# Copy source onion address
if [[ -f "$OLD_CONFIG_DIR/app-sourcev3-ths" ]]; then
    cp "$OLD_CONFIG_DIR/app-sourcev3-ths" "$NEW_CONFIG_DIR/"
    echo "- Migrated: app-sourcev3-ths"
else
    echo "! Not found (skipping): app-sourcev3-ths"
fi

# Set correct permissions
chmod 700 "$NEW_CONFIG_DIR"
if compgen -G "$NEW_CONFIG_DIR/*" > /dev/null; then
    chmod 600 "$NEW_CONFIG_DIR"/*
    echo "- Set permissions on config directory and files"
else
    echo "! No files in config directory to set permissions on"
fi

# Delete update flag so GUI updater doesn't try to run again
UPDATE_FLAG="$HOME/Persistent/.securedrop/securedrop_update.flag"
if [[ -f "$UPDATE_FLAG" ]]; then
    rm "$UPDATE_FLAG"
    echo "- Deleted GUI updater flag: $UPDATE_FLAG"
else
    echo "! GUI updater flag not found (already deleted?): $UPDATE_FLAG"
fi
