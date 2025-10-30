#!/bin/bash
# Wrapper script for migrate-to-deb.sh that runs in detached terminal
# This script handles UI/UX while the actual migration logic is in migrate-to-deb.sh
set -e
set -o pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "========================================"
echo "SecureDrop Workstation Migration"
echo "========================================"
echo ""
echo "Migrating from git-based to package-based installer..."
echo ""

# Run the actual migration script
if "$SCRIPT_DIR/migrate-to-deb.sh"; then
    echo ""
    echo "========================================"
    echo "Migration completed successfully!"
    echo "========================================"
    echo ""
    exit 0
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
