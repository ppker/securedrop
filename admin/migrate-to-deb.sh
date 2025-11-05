#!/bin/bash
# Migration script from git-based to debian-package-based SecureDrop installer
# This script performs a one-time migration for existing users
set -e
set -o pipefail

# Error handler - outputs to terminal only (wrapper handles zenity dialogs)
error_exit() {
    local message="$1"
    echo "ERROR: $message" >&2
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

# Verify root script exist
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_SCRIPT="$SCRIPT_DIR/configure-tails-persistence.sh"
if [[ ! -f "$ROOT_SCRIPT" ]]; then
    error_exit "Helper script not found.\n\nExpected: $ROOT_SCRIPT"
fi

# Run the root script
echo "Configuring Tails persistence (requires password)..."
if ! pkexec bash "$ROOT_SCRIPT"; then
    error_exit "Failed to configure Tails persistence."
fi

# Verify installation
if ! command -v /usr/bin/securedrop-admin >/dev/null 2>&1; then
    error_exit "Package installed but securedrop-admin command not found.\n\nInstallation may have failed."
fi
echo "- securedrop-admin command is available"

NEW_CONFIG_DIR="$HOME/.config/securedrop-admin"

# Copy site-specific config
SITE_SPECIFIC_FILE="$OLD_CONFIG_DIR/group_vars/all/site-specific"
if [[ -f "$SITE_SPECIFIC_FILE" ]]; then
    cp "$SITE_SPECIFIC_FILE" "$NEW_CONFIG_DIR/"
    echo "- Migrated: site-specific"

    # Parse site-specific for GPG public key filenames and copy them
    ossec_key=$(grep '^ossec_alert_gpg_public_key:' "$SITE_SPECIFIC_FILE" | awk '{print $2}' | tr -d "'\"")
    if [[ -n "$ossec_key" && "$ossec_key" != "''" && -f "$OLD_CONFIG_DIR/$ossec_key" ]]; then
        cp "$OLD_CONFIG_DIR/$ossec_key" "$NEW_CONFIG_DIR/"
        echo "- Migrated: $ossec_key (OSSEC GPG public key)"
    elif [[ -n "$ossec_key" && "$ossec_key" != "''" ]]; then
        echo "! Not found (skipping): $ossec_key (OSSEC GPG public key)"
    fi

    securedrop_key=$(grep '^securedrop_app_gpg_public_key:' "$SITE_SPECIFIC_FILE" | awk '{print $2}' | tr -d "'\"")
    if [[ -n "$securedrop_key" && "$securedrop_key" != "''" && -f "$OLD_CONFIG_DIR/$securedrop_key" ]]; then
        cp "$OLD_CONFIG_DIR/$securedrop_key" "$NEW_CONFIG_DIR/"
        echo "- Migrated: $securedrop_key (SecureDrop GPG public key)"
    elif [[ -n "$securedrop_key" && "$securedrop_key" != "''" ]]; then
        echo "! Not found (skipping): $securedrop_key (SecureDrop GPG public key)"
    fi
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
