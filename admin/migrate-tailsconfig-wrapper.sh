#!/bin/bash
# Wrapper script for migrate-tailsconfig.sh that runs in detached terminal
# This script handles UI/UX while the actual configuration logic is in migrate-tailsconfig.sh
set -e
set -o pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "========================================"
echo "SecureDrop Workstation Configuration"
echo "========================================"
echo ""
echo "Configuring your SecureDrop Workstation..."
echo ""

# Run the actual tailsconfig script
if "$SCRIPT_DIR/migrate-tailsconfig.sh"; then
    echo ""
    echo "========================================"
    echo "Configuration completed successfully!"
    echo "========================================"
    echo ""

    # Show reboot notification
    zenity --info \
        --title="Reboot Tails" \
        --width=500 \
        --text="Reboot Tails to complete finish updating."
    exit 0
else
    echo ""
    echo "========================================"
    echo "ERROR: Configuration failed!"
    echo "========================================"
    echo ""
    exit 1
fi
