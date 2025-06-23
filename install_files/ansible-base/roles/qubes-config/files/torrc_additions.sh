#!/bin/bash
set -e

ONION_AUTH_DIR='/var/lib/tor/onion_auth'
LINE="ClientOnionAuthDir $ONION_AUTH_DIR"
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

# Install onion_auth files in /var/lib/tor
if [ ! -d "$ONION_AUTH_DIR" ]; then
    mkdir -p "$ONION_AUTH_DIR"
fi
cp /rw/config/onion_auth/* $ONION_AUTH_DIR
chown -R debian-tor:debian-tor /var/lib/tor

# Restart tor
systemctl restart tor
