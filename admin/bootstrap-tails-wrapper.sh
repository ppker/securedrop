#!/bin/bash
# Bootstrap script for fresh Tails installations
# This script sets up SecureDrop admin tools on Tails via APT
set -e
set -o pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Check if running on Tails
if ! grep -q 'NAME="Tails"' /etc/os-release; then
    zenity --error \
        --title="Unsupported Platform" \
        --width=500 \
        --text="This command only works on Tails.\n\nCurrent platform is not supported."
    exit 1
fi

echo "========================================"
echo "SecureDrop Admin Tools Bootstrap"
echo "========================================"
echo ""
echo "This will install the SecureDrop admin tools on Tails..."
echo ""

# Run the root script
ROOT_SCRIPT="$SCRIPT_DIR/configure-tails-persistence.sh"
echo "Configuring Tails persistence (requires password)..."
if ! pkexec bash "$ROOT_SCRIPT"; then
    echo ""
    echo "========================================"
    echo "ERROR: Bootstrap failed!"
    echo "========================================"
    echo ""
    zenity --error \
        --title="Bootstrap Failed" \
        --width=500 \
        --text="Failed to configure Tails persistence.\n\nPlease see the terminal output for details."
    exit 1
fi

# Verify installation
if ! command -v /usr/bin/securedrop-admin >/dev/null 2>&1; then
    echo ""
    echo "========================================"
    echo "ERROR: Installation failed!"
    echo "========================================"
    echo ""
    zenity --error \
        --title="Bootstrap Failed" \
        --width=500 \
        --text="Package installed but securedrop-admin command not found.\n\nInstallation may have failed."
    exit 1
fi

echo ""
echo "========================================"
echo "Bootstrap completed successfully!"
echo "========================================"
echo ""

# Inform user to click Install Every Time
zenity --info \
    --title="Click Install Every Time" \
    --width=500 \
    --text="In the Additional Software notification above, click \"Install Every Time\"."

# Show final instructions
zenity --info \
    --title="Reboot Tails" \
    --width=500 \
    --text="Please REBOOT Tails to complete bootstrapping SecureDrop Admin Tools."

exit 0
