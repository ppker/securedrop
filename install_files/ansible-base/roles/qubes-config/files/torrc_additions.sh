#!/bin/bash
set -e

LINE='ClientOnionAuthDir /rw/usrlocal/lib/tor/onion_auth'
TORRC='/etc/tor/torrc'

if grep -Fxq "$LINE" "$TORRC"; then
    exit 0
else
    echo "$LINE" >> "$TORRC"
    systemctl restart tor
fi
