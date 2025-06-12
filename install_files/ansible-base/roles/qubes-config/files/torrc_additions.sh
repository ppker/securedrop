#!/bin/bash
set -e

LINE='ClientOnionAuthDir /rw/usrlocal/lib/tor/onion_auth'
TORRC='/etc/tor/torrc'

# Create /etc/tor directory if it doesn't exist
if [ ! -d "$(dirname "$TORRC")" ]; then
    mkdir -p "$(dirname "$TORRC")"
fi

# Create torrc file if it doesn't exist
if [ ! -f "$TORRC" ]; then
    touch "$TORRC"
fi

# Add the line if not present
if ! grep -Fxq "$LINE" "$TORRC"; then
    echo "$LINE" >> "$TORRC"
fi

# Restart tor
systemctl restart tor
