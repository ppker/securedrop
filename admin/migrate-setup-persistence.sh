#!/bin/bash
# Part 2 of migration: Configure Tails persistence and bind-mount
# This script is executed as root via pkexec
set -e
set -o pipefail

LOG_FILE="$1"

if [[ -z "$LOG_FILE" ]]; then
    echo "ERROR: Missing required argument"
    echo "Usage: $0 <log_file_path>"
    exit 1
fi

ADMIN_CONFIG_DIR='/live/persistence/TailsData_unlocked/securedrop-admin'
ADMIN_CONFIG_LINE='/home/amnesia/.config/securedrop-admin source=securedrop-admin'
PERSISTENCE_FILE='/live/persistence/TailsData_unlocked/persistence.conf'
NEW_CONFIG_DIR="/home/amnesia/.config/securedrop-admin"

# Create the persistent config directory
if [[ ! -d "$ADMIN_CONFIG_DIR" ]]; then
    mkdir -p "$ADMIN_CONFIG_DIR" 2>&1 | tee -a "$LOG_FILE"
    chown amnesia:amnesia "$ADMIN_CONFIG_DIR" 2>&1 | tee -a "$LOG_FILE"
    chmod 700 "$ADMIN_CONFIG_DIR" 2>&1 | tee -a "$LOG_FILE"
    echo "- Created persistent config directory: $ADMIN_CONFIG_DIR" | tee -a "$LOG_FILE"
else
    echo "- Persistent config directory already exists: $ADMIN_CONFIG_DIR" | tee -a "$LOG_FILE"
fi

# Add persistence configuration line if not already present
if ! grep -qP '^/home/amnesia/.config/securedrop-admin\h+source=securedrop-admin' "$PERSISTENCE_FILE"; then
    echo "$ADMIN_CONFIG_LINE" >> "$PERSISTENCE_FILE" 2>&1 | tee -a "$LOG_FILE"
    echo "- Added persistence configuration to $PERSISTENCE_FILE" | tee -a "$LOG_FILE"
else
    echo "- Persistence configuration already present in $PERSISTENCE_FILE" | tee -a "$LOG_FILE"
fi

# Manually activate the persistence bind-mount without requiring reboot
if ! mountpoint -q "$NEW_CONFIG_DIR" 2>/dev/null; then
    echo "Activating persistence bind-mount for $NEW_CONFIG_DIR..." | tee -a "$LOG_FILE"
    # Create the target directory if it doesn't exist (as amnesia user)
    if [[ ! -d "$NEW_CONFIG_DIR" ]]; then
        sudo -u amnesia mkdir -p "$NEW_CONFIG_DIR" 2>&1 | tee -a "$LOG_FILE"
    fi
    # Bind-mount the persistent directory
    mount --bind "$ADMIN_CONFIG_DIR" "$NEW_CONFIG_DIR" 2>&1 | tee -a "$LOG_FILE"
    echo "- Activated persistence bind-mount (will persist after reboot)" | tee -a "$LOG_FILE"
else
    echo "- Persistence bind-mount already active" | tee -a "$LOG_FILE"
fi

exit 0
