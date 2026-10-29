#!/bin/sh
# One founder prompt; only ciphertext and public metadata are written.
set -eu
here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
for arg in "$@"; do
  if [ "$arg" = --dry-run ]; then exec python3 -B "$here/migrate-legacy-checkpoints.py" "$@"; fi
done
command -v caffeinate >/dev/null || { echo 'Real migration requires Mac caffeinate' >&2; exit 2; }
exec caffeinate -i python3 -B "$here/migrate-legacy-checkpoints.py" "$@"
