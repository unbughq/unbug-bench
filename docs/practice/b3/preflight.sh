#!/bin/sh
# Offline validation only. Exit 3 means valid preparation, never launch authority.
exec python3 -B "$(dirname "$0")/preflight.py" "$@"
