#!/bin/bash
# Wrapper script for migrate-to-deb.sh that runs in detached terminal
# This script handles UI/UX while the actual migration logic is in migrate-to-deb.sh
set -e
set -o pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Get the GUI updater parent PID from argument
GUI_UPDATER_PID="$1"

# Wait for securedrop-admin to disown this process
sleep 1

# Kill the GUI updater process if we have a PID
if [[ -n "$GUI_UPDATER_PID" ]]; then
    echo "Closing GUI updater (PID: $GUI_UPDATER_PID)..."
    kill "$GUI_UPDATER_PID" 2>/dev/null || true
    echo ""
fi

echo "========================================"
echo "SecureDrop Workstation Migration"
echo "========================================"
echo ""
echo "Migrating from git-based to package-based installer..."
echo ""

# Run the migration script
if "$SCRIPT_DIR/migrate-to-deb.sh"; then
    echo ""
    echo "========================================"
    echo "Migration completed successfully!"
    echo "========================================"
    echo ""

    # Inform user to click Install Every Time
    zenity --info \
        --title="Click Install Every Time" \
        --width=500 \
        --text="In the Additional Software notification above, click \"Install Every Time\"."
else
    echo ""
    echo "========================================"
    echo "ERROR: Migration failed!"
    echo "========================================"
    echo ""
    zenity --error \
        --title="Migration Failed" \
        --width=500 \
        --text="The migration failed. Please see the terminal output for details.\n\nYou may need to contact support."
    exit 1
fi

# Now run the configuration
echo ""
echo "========================================"
echo "SecureDrop Workstation Configuration"
echo "========================================"
echo ""
echo "Configuring your SecureDrop Workstation..."
echo ""

# Inform user they will need to enter password in the terminal
zenity --info \
    --title="Password Required" \
    --width=500 \
    --text="When the Console prompts for \"SUDO password:\", please type your Tails Administration password and press Enter."

# Run localconfig directly
if /usr/bin/securedrop-admin localconfig; then
    echo ""
    echo "========================================"
    echo "Configuration completed successfully!"
    echo "========================================"
    echo ""

    # Show reboot notification
    zenity --info \
        --title="Reboot Tails" \
        --width=500 \
        --text="Please REBOOT Tails to complete this SecureDrop Admin Workstation update."

    exit 0
else
    echo ""
    echo "========================================"
    echo "ERROR: Configuration failed!"
    echo "========================================"
    echo ""
    zenity --error \
        --title="Configuration Failed" \
        --width=500 \
        --text="The configuration failed. Please see the terminal output for details.\n\nYou may need to contact support."
    exit 1
fi
