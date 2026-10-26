#!/bin/sh
# Host: collected encrypted statements -> serialized registry reservations -> parked workers.
# No statement plaintext or decryption key is used on this host. A failed reservation or
# snapshot transfer leaves workers parked. Hetzner discovery is the default; Boat
# requires --provider boat --worker-id ID (repeat for a wave). Delivery only: use the
# approved launcher with original pinned settings and cumulative budget to resume.
set -eu
here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec python3 "$here/statement_round.py" "$@"
