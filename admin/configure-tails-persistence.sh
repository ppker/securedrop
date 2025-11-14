#!/bin/bash
# Part 2 of migration: Configure Tails persistence and bind-mount
# This script is executed as root via pkexec
set -e
set -o pipefail

# Environment configuration
# To configure an alternate repo or signing key, create a file named
# ~/securedrop_bootstrap.env, which sets the APT_REPO_URL and
# APT_SIGNING_KEY_FILE env vars to appropriate values.

APT_SOURCES_DIR='/live/persistence/TailsData_unlocked/apt-sources.list.d'
SECUREDROP_SOURCES_FILE="$APT_SOURCES_DIR/securedrop.sources"

if [[ -e /home/amnesia/securedrop_bootstrap.env ]]; then
    source /home/amnesia/securedrop_bootstrap.env
else
    APT_REPO_URL="https://apt.freedom.press"
    APT_SIGNING_KEY_FILE="fpf-signing-key-2021.pub"
fi

ADMIN_CONFIG_DIR='/live/persistence/TailsData_unlocked/securedrop-admin'
ADMIN_CONFIG_LINE='/home/amnesia/.config/securedrop-admin source=securedrop-admin'
PERSISTENCE_FILE='/live/persistence/TailsData_unlocked/persistence.conf'
NEW_CONFIG_DIR="/home/amnesia/.config/securedrop-admin"

# Create the persistent config directory
if [[ ! -d "$ADMIN_CONFIG_DIR" ]]; then
    mkdir -p "$ADMIN_CONFIG_DIR"
    chown amnesia:amnesia "$ADMIN_CONFIG_DIR"
    chmod 700 "$ADMIN_CONFIG_DIR"
    echo "- Created persistent config directory: $ADMIN_CONFIG_DIR"
else
    echo "- Persistent config directory already exists: $ADMIN_CONFIG_DIR"
fi

# Add persistence configuration line if not already present
if ! grep -qP '^/home/amnesia/.config/securedrop-admin\h+source=securedrop-admin' "$PERSISTENCE_FILE"; then
    echo "$ADMIN_CONFIG_LINE" >> "$PERSISTENCE_FILE"
    echo "- Added persistence configuration to $PERSISTENCE_FILE"
else
    echo "- Persistence configuration already present in $PERSISTENCE_FILE"
fi

# Manually activate the persistence bind-mount without requiring reboot
if ! mountpoint -q "$NEW_CONFIG_DIR" 2>/dev/null; then
    echo "Activating persistence bind-mount for $NEW_CONFIG_DIR..."
    # Create the target directory if it doesn't exist (as amnesia user)
    if [[ ! -d "$NEW_CONFIG_DIR" ]]; then
        sudo -u amnesia mkdir -p "$NEW_CONFIG_DIR"
    fi
    # Bind-mount the persistent directory
    mount --bind "$ADMIN_CONFIG_DIR" "$NEW_CONFIG_DIR"
    echo "- Activated persistence bind-mount (will persist after reboot)"
else
    echo "- Persistence bind-mount already active"
fi

# Configure apt repository persistence
APT_PERSISTENCE_LINE='/etc/apt/sources.list.d  source=apt-sources.list.d,link'

echo "Configuring SecureDrop APT repository..."

# Add APT sources persistence to persistence.conf
if ! grep -qP '^/etc/apt/sources\.list\.d\h+source=apt-sources\.list\.d,link' "$PERSISTENCE_FILE"; then
    echo "$APT_PERSISTENCE_LINE" >> "$PERSISTENCE_FILE"
    echo "- Added APT sources persistence to $PERSISTENCE_FILE"
else
    echo "- APT sources persistence already present in $PERSISTENCE_FILE"
fi

# Create persistent APT sources directory
if [[ ! -d "$APT_SOURCES_DIR" ]]; then
    mkdir -p "$APT_SOURCES_DIR"
    echo "- Created APT sources directory: $APT_SOURCES_DIR"
else
    echo "- APT sources directory already exists: $APT_SOURCES_DIR"
fi

# Create the SecureDrop repository sources file with inline GPG key
cat > "$SECUREDROP_SOURCES_FILE" << EOF
Types: deb
URIs: tor+$APT_REPO_URL
Suites: trixie
Components: main
Signed-By:
EOF

# Append the GPG key with proper indentation (leading space on each line)
# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GPG_KEY_FILE="$SCRIPT_DIR/../install_files/ansible-base/roles/install-fpf-repo/files/$APT_SIGNING_KEY_FILE"

if [[ -f "$GPG_KEY_FILE" ]]; then
    sed 's/^/ /' "$GPG_KEY_FILE" >> "$SECUREDROP_SOURCES_FILE"
else
    echo "ERROR: $APT_SIGNING_KEY_FILE not found at $GPG_KEY_FILE"
    exit 1
fi

# Set proper permissions and ownership
chmod 644 "$SECUREDROP_SOURCES_FILE"
chown root:root "$SECUREDROP_SOURCES_FILE"

echo "- Created SecureDrop repository sources file: $SECUREDROP_SOURCES_FILE"
echo "  Repository: $APT_REPO_URL"
echo "  Signing key: $APT_SIGNING_KEY_FILE"

# Manually activate the APT sources bind-mount without requiring reboot
if ! mountpoint -q /etc/apt/sources.list.d 2>/dev/null; then
    echo "Activating APT sources bind-mount..."
    # The directory should already exist, but verify
    if [[ ! -d /etc/apt/sources.list.d ]]; then
        mkdir -p /etc/apt/sources.list.d
    fi
    # Bind-mount the persistent APT sources directory
    mount --bind "$APT_SOURCES_DIR" /etc/apt/sources.list.d
    echo "- Activated APT sources bind-mount (will persist after reboot)"
else
    echo "- APT sources bind-mount already active"
fi

# Update apt cache and install securedrop-admin
echo "Installing securedrop-admin package from repository..."
if apt-get update; then
    echo "- APT cache updated successfully"
else
    echo "! Warning: apt-get update had issues, but continuing..."
fi

if apt-get install -y securedrop-admin; then
    echo "- securedrop-admin package installed successfully"
else
    echo "ERROR: Failed to install securedrop-admin package"
    exit 1
fi

exit 0
